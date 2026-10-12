"""Department vs Service: the centre-specific hierarchy, and how to resolve it.

## The rule

    Centre
      ↓
    Department / Section      ← administrative POLICY, configurable per centre
      ↓
    Service Group             ← a grouping inside a department
      ↓
    Service                   ← the catalogue entry: the work that is sold
      ↓
    Specific examination      ← what was actually performed on a reception line

**Department structure is a policy. Service identity is the work.** A centre may
give an examination its own department, or keep it as a service inside a broader
one, and it may change its mind. Nothing clinical changes when it does.

## Why this is not a theoretical concern

Measured at this centre on 1405/06/02, for «ماموگرافی»:

| resolved as… | receptions |
|---|---:|
| its own department (code 9) | ~0 — `Disabled: true` |
| every department its services live in (2, 4, 9) | **108** |
| the services actually performed | **4** |

Both department strategies are wrong, in opposite directions. The dedicated
department **under**-counts, because the centre retired it. The union of the
departments its services live in **over**-counts by 27×, because those
departments are the whole of Radiology and MRI.

So a department filter is not a conservative approximation of a service filter.
It is a different question with a different answer, and the answer is not close.

## Five levels the lexicon must keep apart

`department`, `service_group`, `service`, `modality`, `examination` are related
and are NOT interchangeable.

⚠️ In this software **`modality` IS the department**. The `Modality` collection
is the centre's department table — `_id` is the code, `PerFullName` is what the
operator sees on screen, and `Disabled` retires it. The word "modality" reads
clinical and is administrative, which is precisely how «ماموگرافی» came to
resolve to a switched-off department instead of to five live services.

## The resolution order

    concept
      → does an ACTIVE department carry this name?        (department level)
      → services whose name / internal name matches       (service level)
      → service groups whose name matches                 (group level)
      → the department, only as a last resort and labelled as such
      → build ONE deduplicated filter over whatever was found

`resolve_clinical_concept()` never returns "nothing found" when the catalogue
knows the words. It returns what it found, at which level, and how confident the
mapping is — so a caller can say "4 mammography studies" or "no mammography
service exists in this centre's catalogue", which are different sentences.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from .normalize import fold, squash

BUNDLED_CENTER_CONFIG_PATH = Path(__file__).resolve().parent.parent / "center_config.json"
# Compatibility for packaging checks and callers that used the old constant.
CENTER_CONFIG_PATH = BUNDLED_CENTER_CONFIG_PATH
ENV_CENTER_CONFIG_PATH = "RECEPTION_CENTER_CONFIG_PATH"


def center_config_path() -> Path:
    """The active centre map, never another clinic's bundled seed by accident.

    A frozen installer is universal. Its bundled map may be a migration seed
    for the centre it names, but runtime authority lives in ProgramData and is
    generated from the reception database on that machine. If bootstrap did
    not complete, returning the missing runtime path makes the failure loud;
    falling back to a bundled map from another clinic would be much worse.
    """
    override = os.getenv(ENV_CENTER_CONFIG_PATH)
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        from ..runtime import config_root

        return config_root() / "center_config.json"
    return BUNDLED_CENTER_CONFIG_PATH

#: The five levels, named so nothing has to infer them from a field name.
LEVELS = ("department", "service_group", "service", "modality", "examination")


@lru_cache(maxsize=1)
def load_center(path: str | None = None) -> dict[str, Any]:
    """This centre's configuration, as discovered from its own software.

    Missing is not fatal and IS loud: without it the resolver can still work
    from the lexicon's value sets, but only at the department level — which is
    the very failure this module exists to prevent. The caller is told.
    """
    target = Path(path) if path else center_config_path()
    try:
        with target.open(encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            return {"available": False, "reason": f"center config is not an object: {target}"}
        expected_center = str(os.getenv("RECEPTION_HTTP_API_CENTER") or "").strip()
        configured_center = str(payload.get("center") or "").strip()
        if expected_center and configured_center.casefold() != expected_center.casefold():
            named = configured_center or "unnamed/legacy"
            return {
                "available": False,
                "reason": (
                    f"center config belongs to {named!r}, but server is configured for "
                    f"{expected_center!r}; run center bootstrap on this machine"
                ),
            }
        return payload
    except FileNotFoundError:
        return {"available": False, "reason": f"no center_config.json at {target}"}
    except (OSError, json.JSONDecodeError) as exc:
        return {"available": False, "reason": f"unreadable: {type(exc).__name__}"}


def is_available() -> bool:
    return load_center().get("available") is not False


def reset_cache() -> None:
    """Reload after bootstrap or after server config selects a runtime map."""
    for cached in (
        load_center,
        departments,
        service_concepts,
        orphan_departments,
        _service_index,
        _group_index,
    ):
        cached.cache_clear()


@dataclass(frozen=True)
class Department:
    code: str
    short: str | None
    name_en: str | None
    name_fa: str | None
    disabled: bool

    @property
    def active(self) -> bool:
        return not self.disabled


@dataclass(frozen=True)
class ServiceConcept:
    """A centre-owned synonym set for one clinical service concept.

    The catalogue remains the source of service identity.  This overlay only
    says that words such as «کمر», «لومبر» and ``lumbar`` are alternative ways
    to ask for the same family of catalogue/performed-service names.
    """

    id: str
    label_fa: str
    aliases: tuple[str, ...]
    match_terms: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "labelFa": self.label_fa,
            "aliases": list(self.aliases),
            "matchTerms": list(self.match_terms),
        }


@dataclass(frozen=True)
class ConceptMatch:
    """What a clinical concept resolved to, at which level, and how sure.

    `level` is the headline. A caller that reports a number without saying it
    came from `department` when the concept had no service match is reporting a
    department's traffic as if it were the examination's.
    """

    concept: str
    level: str
    #: Exact catalogue service names — the filter that means "the work".
    services: tuple[str, ...] = ()
    #: Service group names, when the concept is a group rather than a service.
    service_groups: tuple[str, ...] = ()
    #: Department codes involved, for reporting — NOT for filtering unless
    #: `level == "department"`.
    departments: tuple[str, ...] = ()
    #: Departments that are switched off but still carry matching services.
    retired_departments: tuple[str, ...] = ()
    #: Department codes referenced by services but absent from the department
    #: table entirely — a department that was deleted, not merely disabled.
    orphan_departments: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    canonical_concept: str | None = None
    search_terms: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "concept": self.concept,
            "level": self.level,
            "serviceCount": len(self.services),
        }
        if self.services:
            out["services"] = list(self.services)
        if self.service_groups:
            out["serviceGroups"] = list(self.service_groups)
        if self.departments:
            out["departments"] = list(self.departments)
        if self.retired_departments:
            out["retiredDepartments"] = list(self.retired_departments)
        if self.orphan_departments:
            out["orphanDepartments"] = list(self.orphan_departments)
        if self.notes:
            out["notes"] = list(self.notes)
        if self.canonical_concept:
            out["canonicalConcept"] = self.canonical_concept
        if self.search_terms:
            out["expandedTerms"] = list(self.search_terms)
        return out

    def found(self) -> bool:
        return bool(self.services or self.service_groups or self.departments)


# --------------------------------------------------------------------------- #
# Indexes over the centre configuration
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def departments() -> tuple[Department, ...]:
    config = load_center()
    return tuple(
        Department(
            code=str(d.get("code")),
            short=d.get("short"),
            name_en=d.get("name_en"),
            name_fa=d.get("name_fa"),
            disabled=bool(d.get("disabled")),
        )
        for d in config.get("departments") or []
    )


def department(code: Any) -> Department | None:
    wanted = str(code)
    return next((d for d in departments() if d.code == wanted), None)


def active_departments() -> tuple[Department, ...]:
    return tuple(d for d in departments() if d.active)


@lru_cache(maxsize=1)
def service_concepts() -> tuple[ServiceConcept, ...]:
    """Centre-specific clinical aliases layered over the discovered catalogue."""
    from ..center_bootstrap import validate_active_concepts

    concepts: list[ServiceConcept] = []
    raw_concepts = validate_active_concepts(load_center().get("service_concepts") or [])
    for raw in raw_concepts:
        concept_id = str(raw.get("id") or "").strip()
        label_fa = str(raw.get("label_fa") or concept_id).strip()
        aliases = tuple(dict.fromkeys(
            str(value).strip() for value in (raw.get("aliases") or [])
            if len(fold(value)) >= MIN_CONCEPT_CHARS
        ))
        match_terms = tuple(dict.fromkeys(
            str(value).strip() for value in (raw.get("match_terms") or aliases)
            if len(fold(value)) >= MIN_CONCEPT_CHARS
        ))
        if concept_id and aliases and match_terms:
            concepts.append(ServiceConcept(concept_id, label_fa, aliases, match_terms))
    return tuple(concepts)


def service_concept(term: str) -> ServiceConcept | None:
    """Resolve an input alias exactly; substring expansion would be unsafe."""
    wanted_fold = fold(term)
    wanted_squash = squash(term)
    for concept in service_concepts():
        for alias in concept.aliases:
            if wanted_fold == fold(alias) or wanted_squash == squash(alias):
                return concept
    return None


def service_search_terms(term: str) -> tuple[str, ...]:
    """Terms a performed-service name may contain for this user concept."""
    concept = service_concept(term)
    return concept.match_terms if concept is not None else (str(term).strip(),)


@lru_cache(maxsize=1)
def orphan_departments() -> tuple[str, ...]:
    """Department codes referenced by services or groups but not in the table.

    At this centre that is code **6** — one service and two groups («عکس دندان
    (Cephalogram & OPG)», «کلیشه») still point at a department that was DELETED
    rather than disabled. It is the panoramic/dental department the owner
    described, and it survives only as a dangling code.
    """
    return tuple(load_center().get("orphan_departments") or [])


@lru_cache(maxsize=1)
def _service_index() -> tuple[dict[str, Any], ...]:
    """Every catalogue service with its search keys precomputed."""
    out = []
    for s in load_center().get("services") or []:
        name = s.get("name") or ""
        out.append({
            **s,
            "_keys": (fold(name), squash(name),
                      fold(s.get("internal_name")), fold(s.get("group_name"))),
        })
    return tuple(out)


@lru_cache(maxsize=1)
def _group_index() -> tuple[dict[str, Any], ...]:
    out = []
    for g in load_center().get("service_groups") or []:
        name = g.get("name") or ""
        out.append({**g, "_keys": (fold(name), squash(name))})
    return tuple(out)


def _matches(needle: str, keys: tuple) -> bool:
    """Substring match on any precomputed key.

    Substring rather than equality because catalogue names are long and
    descriptive — «ماموگرافی دو طرفه (روی4 فیلم مخصوص ماموگرافی)» has to be
    found by «ماموگرافی». The needle is required to be at least three
    characters by the caller, which is what keeps particles out.
    """
    return any(k and needle in k for k in keys)


# --------------------------------------------------------------------------- #
# The resolver
# --------------------------------------------------------------------------- #
#: Shortest concept worth resolving by SUBSTRING. Below this, Persian particles
#: match descriptive catalogue names and every question becomes every service.
MIN_CONCEPT_CHARS = 3


def _short_code(term: str, needle: str) -> ConceptMatch:
    """A term below the length floor, rescued only by an EXACT department code.

    ⚠️ «CT» is two characters, and the floor above turned it into "not found in
    this centre's service catalogue" — while «سی تی», the same department, said
    `department 1`. Two spellings of one word, two different answers, and the
    short one is the one the operator sees in the software and types into the
    agent. `scenario_router` had already learned this and dropped its own floor
    to two; this module had not, so the two layers held different opinions about
    the same word, which is precisely the shape of a silent zero.

    The rescue is EXACT equality, not substring, and against ACTIVE departments
    only. Both restrictions matter:

    * exact, because a two-character substring match against 519 descriptive
      catalogue names is how «تا» and «هر» once resolved to radiology — the
      failure the floor exists to prevent. Equality against a seven-row
      controlled vocabulary cannot do that;
    * active only, and only BELOW the floor, so this can never take precedence
      over the service level for a longer term. «ماموگرافی» is exactly equal to
      retired department 9's name; if exactness won generally, the whole
      department-versus-service rule would invert itself on the one case it was
      written for.

    This makes the vendor's own short codes resolvable — CT, MR, US, DX, BD —
    which is what the operator reads off the screen.
    """
    for dept in departments():
        if not dept.active:
            continue
        if any(needle == fold(x) for x in (dept.short, dept.name_en, dept.name_fa) if x):
            return ConceptMatch(
                concept=term,
                level="department",
                departments=(dept.code,),
                notes=(f"matched the active department short code {dept.short!r}",),
            )
    return ConceptMatch(concept=term, level="none",
                        notes=("term too short to resolve safely",))


def resolve_clinical_concept(term: str) -> ConceptMatch:
    """A clinical concept → what this centre actually calls it.

    Order, and the reason for each step:

    1. **An ACTIVE department by that name.** If the centre models the concept as
       a department and still uses it, the department is the right handle — it
       is what the operator sees and what the reports group by.
    2. **Services whose name, internal name or group name carries the concept.**
       This is the work, and it is the answer whenever a department was retired
       or never existed.
    3. **Service groups by that name**, for a concept that is a grouping rather
       than a single examination.
    4. **A DISABLED or absent department, reported as such.** Never used as a
       filter on its own — it is the evidence that the concept exists in this
       centre's history, which is worth saying when nothing else matched.

    A department is deliberately never combined with services into one filter:
    at this centre that union turns 4 mammography studies into 108, because the
    departments involved are Radiology and MRI entire.
    """
    needle_fold = fold(term)
    needle_squash = squash(term)
    if len(needle_fold) < MIN_CONCEPT_CHARS:
        return _short_code(term, needle_fold)

    mapped = service_concept(term)
    search_terms = service_search_terms(term)
    search_needles = tuple((fold(value), squash(value)) for value in search_terms)

    notes: list[str] = []

    # ---- 1. an active department by that name -----------------------------
    dept_hits = [
        d for d in departments()
        if any(needle_fold in fold(x) or needle_squash in squash(x)
               for x in (d.name_fa, d.name_en, d.short) if x)
    ]
    active_hits = [d for d in dept_hits if d.active]
    retired_hits = [d for d in dept_hits if d.disabled]

    # ---- 2. services ------------------------------------------------------
    service_hits = [
        s for s in _service_index()
        if any(_matches(folded, s["_keys"]) or _matches(squashed, s["_keys"])
               for folded, squashed in search_needles)
    ]
    group_hits = [
        g for g in _group_index()
        if any(_matches(folded, g["_keys"]) or _matches(squashed, g["_keys"])
               for folded, squashed in search_needles)
    ]

    service_depts = sorted({s["department"] for s in service_hits if s.get("department")})
    known = {d.code for d in departments()}
    orphans = tuple(sorted(set(service_depts) - known))
    retired_carrying = tuple(sorted(
        code for code in service_depts
        if (d := department(code)) is not None and d.disabled
    ))

    # ---- does an ACTIVE department own this concept outright? -------------
    #
    # ⚠️ Preferring services whenever any service matched is WRONG, and it is
    # wrong in the opposite direction to the bug this module was written for.
    # Measured on 1405/06/02: «ام آر آی» is an active department with 73
    # services, of which 63 carry the words in their name. A service filter
    # counted **33** receptions where the department counted **62** — because
    # ten services in that department are not called "MRI" anything.
    #
    # So: when the centre models the concept AS an active department and every
    # matching service is inside it, the department is the answer. The services
    # are a subset by construction and filtering on them silently drops the rest.
    #
    # Mammography is the other case and stays on the service path: no ACTIVE
    # department matches (code 9 is switched off) and its services are scattered
    # across departments 2, 4 and 9. Both cases now resolve the way the data
    # actually supports, rather than by one blanket preference.
    active_codes = {d.code for d in active_hits}
    escapes = sorted({s["department"] for s in service_hits} - active_codes)

    if active_hits and not escapes:
        return ConceptMatch(
            concept=term, level="department",
            departments=tuple(sorted(active_codes)),
            notes=(
                "the centre models this as an active department and every "
                f"matching service ({len(service_hits)}) sits inside it — the "
                "department is the complete set, the services are a subset",
            ),
        )

    if service_hits:
        if active_hits:
            notes.append(
                f"an active department of this name exists, but matching services "
                f"also sit outside it (departments {', '.join(escapes)}) — so the "
                f"concept is wider than the department and the service filter is "
                f"the right one"
            )
        if retired_hits or retired_carrying:
            notes.append(
                "a department of this name exists but is DISABLED; the services "
                "are live, so a department filter would under-count"
            )
        if len(service_depts) > 1:
            notes.append(
                f"these services span {len(service_depts)} departments "
                f"({', '.join(service_depts)}) — filtering by department would "
                f"return those departments entire, not this concept"
            )
        if orphans:
            notes.append(
                f"department code(s) {', '.join(orphans)} are referenced by these "
                f"services but absent from the department table — deleted, not disabled"
            )
        return ConceptMatch(
            concept=term, level="service",
            services=tuple(sorted({s["name"] for s in service_hits if s.get("name")})),
            service_groups=tuple(sorted({g["name"] for g in group_hits if g.get("name")})),
            departments=tuple(service_depts),
            retired_departments=retired_carrying,
            orphan_departments=orphans,
            notes=tuple(notes),
            canonical_concept=mapped.id if mapped else None,
            search_terms=search_terms if mapped else (),
        )

    if group_hits:
        return ConceptMatch(
            concept=term, level="service_group",
            service_groups=tuple(sorted({g["name"] for g in group_hits if g.get("name")})),
            departments=tuple(sorted({g["department"] for g in group_hits})),
            notes=("matched a service group; no individual service carries the name",),
            canonical_concept=mapped.id if mapped else None,
            search_terms=search_terms if mapped else (),
        )

    if retired_hits:
        return ConceptMatch(
            concept=term, level="retired_department",
            departments=tuple(d.code for d in retired_hits),
            retired_departments=tuple(d.code for d in retired_hits),
            notes=("this centre once had a department of this name and has "
                   "disabled it, and no catalogue service carries the name — so "
                   "there is nothing to count, which is different from zero work",),
        )

    return ConceptMatch(concept=term, level="none",
                        notes=("this centre's catalogue does not contain the term",))


# --------------------------------------------------------------------------- #
# The filter the query planner actually runs
# --------------------------------------------------------------------------- #
#: How many service names a single `$in` may carry.
#:
#: A concept that matches half the catalogue is not a concept, it is a word like
#: «سونوگرافی» that names a whole department. Refusing past this is deliberate:
#: an enormous `$in` is both a slow query on a clinical database and a sign the
#: term should have resolved at the department level instead.
MAX_SERVICES_IN_FILTER = 120


class ConceptTooBroad(Exception):
    """The term matches so much of the catalogue that it is a department, not a
    concept. Raised rather than truncated — a silently shortened `$in` gives a
    confident undercount, which is the failure this whole module exists to end."""


def concept_filter(match: ConceptMatch) -> dict[str, Any]:
    """A validated, deduplicated Mongo filter for one resolved concept.

    Returns a filter over `services[]`, because that is where the work is. The
    caller combines it with the date and the live-only guard.

    ⚠️ Deduplication matters twice over. Service names are deduplicated on the
    way in (`resolve_clinical_concept` returns a set), and the caller must count
    DISTINCT receptions when unwinding — a reception with two matching lines is
    one visit and two services, and reporting the line count as visits is the
    fan-out error the lexicon's counting rules already warn about.
    """
    if match.level in {"service", "service_group"} and match.services:
        if len(match.services) > MAX_SERVICES_IN_FILTER:
            raise ConceptTooBroad(
                f"{match.concept!r} matches {len(match.services)} catalogue services — "
                f"that is a department, not an examination. Resolve it as a department "
                f"or narrow the term."
            )
        return {"services.Service": {"$in": list(match.services)}}

    if match.level == "service_group" and match.service_groups:
        return {"services.ServiceGroup": {"$in": list(match.service_groups)}}

    if match.level == "department" and match.departments:
        # The one case where a department IS the right filter: the centre models
        # the concept as an active department and no service carries the name.
        # Matched on the LINE's own modality, not the reception's — a reception
        # is stamped with one department while its lines may belong to several.
        return {"services.Modality": {"$in": list(match.departments)}}

    raise ConceptTooBroad(
        f"{match.concept!r} did not resolve to anything filterable "
        f"(level={match.level}); do not guess a filter for it."
    )


def explain(match: ConceptMatch) -> str:
    """One Persian sentence a clinician can check the reasoning against.

    Published beside the number because "4 mammography studies" and "4
    mammography studies, found as services because the department is switched
    off" are the same figure with very different auditability.
    """
    if match.level == "service":
        parts = [f"«{match.concept}» به {len(match.services)} خدمت در فهرست خدمات این مرکز نگاشت شد"]
        if match.canonical_concept and match.search_terms:
            parts.append(
                "واژگان هم‌معنی مرکز نیز اعمال شد: " + "، ".join(match.search_terms)
            )
        if match.retired_departments:
            parts.append("بخش هم‌نام غیرفعال است، بنابراین شمارش بر مبنای خدمت انجام شد")
        if len(match.departments) > 1:
            parts.append(f"این خدمات در {len(match.departments)} بخش پراکنده‌اند")
        return "؛ ".join(parts) + "."
    if match.level == "department":
        return f"«{match.concept}» در این مرکز یک بخش فعال است و شمارش بر مبنای همان بخش انجام شد."
    if match.level == "service_group":
        return f"«{match.concept}» به یک گروه خدمتی نگاشت شد، نه یک خدمت مشخص."
    if match.level == "retired_department":
        return (f"«{match.concept}» زمانی یک بخش در این مرکز بوده و اکنون غیرفعال است، "
                f"و هیچ خدمتی با این نام در فهرست وجود ندارد.")
    return f"«{match.concept}» در فهرست خدمات این مرکز یافت نشد."
