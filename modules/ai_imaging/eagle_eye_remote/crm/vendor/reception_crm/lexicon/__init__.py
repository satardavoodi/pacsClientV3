"""The reception lexicon: the agent's vocabulary and the query contract.

Two jobs, and they are deliberately separate:

  resolve()        a user's words  ->  a code the database actually stores
  validate_query() a model's JSON  ->  a checked query, or a refusal

The rule that makes this worth having: **an unresolvable value raises; it never
becomes a filter.** A filter that cannot match returns zero rows and `status: ok`,
which reads as a confident answer of "none". That is how the agent came to report
"0 patients" for radiology and sonography on a day with 35 and 85.

The data lives in lexicon.json, which is GENERATED from a live inspection
(scripts/build_lexicon.py). Nothing here hard-codes a field name or a code.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from .normalize import fold, squash

LEXICON_PATH = Path(__file__).with_name("lexicon.json")


# --------------------------------------------------------------------------- errors

class LexiconProblem(Exception):
    """Base: the request named something the data model cannot honour."""

    code = "LEXICON_PROBLEM"

    def __init__(self, message_en: str, message_fa: str = "", **extra):
        super().__init__(message_en)
        self.message_en = message_en
        self.message_fa = message_fa
        self.extra = extra

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message_en,
                "message_fa": self.message_fa, **self.extra}


class UnknownValue(LexiconProblem):
    """The term matches nothing. NEVER degrade this into an empty filter."""

    code = "UNKNOWN_VALUE"


class AmbiguousValue(LexiconProblem):
    """The term matches more than one concept. Ask; do not guess."""

    code = "AMBIGUOUS_VALUE"


class DisabledValue(LexiconProblem):
    """The concept exists but is switched off, so a filter on it finds ~nothing."""

    code = "DISABLED_VALUE"


class InvalidQuery(LexiconProblem):
    code = "INVALID_QUERY"


# --------------------------------------------------------------------------- loading

@lru_cache(maxsize=1)
def load(path: str | None = None) -> dict[str, Any]:
    p = Path(path) if path else LEXICON_PATH
    with p.open(encoding="utf-8") as fh:
        return json.load(fh)


def version() -> str:
    return load()["lexicon_version"]


# --------------------------------------------------------------------------- resolving

@dataclass
class Resolution:
    """What a user's words resolved to, and how sure we are."""

    value_set: str
    code: str
    display_en: str | None = None
    display_fa: str | None = None
    matched_on: str = ""
    exact: bool = True
    alternatives: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "value_set": self.value_set, "code": self.code,
            "display_en": self.display_en, "display_fa": self.display_fa,
            "matched_on": self.matched_on, "exact": self.exact,
            "alternatives": self.alternatives,
        }


def _concept_keys(concept: dict) -> list[tuple[str, str]]:
    """(normalised key, the surface form it came from) for one concept."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(surface):
        if not surface or not isinstance(surface, str):
            return
        for key in (squash(surface), fold(surface)):
            if key and key not in seen:
                seen.add(key)
                out.append((key, surface))

    add(concept.get("code"))
    add(concept.get("vendor_short"))
    add(concept.get("display_fa"))
    for lang in ("en", "fa"):
        disp = (concept.get("display") or {}).get(lang) or {}
        add(disp.get("preferred"))
        for s in (concept.get("acceptable") or {}).get(lang, []) or []:
            add(s)
    for s in concept.get("spelling_variants", []) or []:
        add(s)
    return out


@lru_cache(maxsize=32)
def _index(value_set: str) -> dict[str, list[dict]]:
    vs = load()["value_sets"].get(value_set)
    if vs is None:
        raise UnknownValue(
            f"no value set named {value_set!r}",
            extra_known=sorted(load()["value_sets"]),
        )
    idx: dict[str, list[dict]] = {}
    for concept in vs.get("concepts", []):
        for key, surface in _concept_keys(concept):
            idx.setdefault(key, [])
            if concept not in idx[key]:
                idx[key].append({"concept": concept, "surface": surface})
    return idx


def resolve(value_set: str, text: str, *, allow_disabled: bool = False) -> Resolution:
    """A user's words -> one code. Raises rather than guessing or returning None."""
    if text is None or str(text).strip() == "":
        raise UnknownValue(f"empty value for {value_set}")

    idx = _index(value_set)
    raw = str(text)
    hits = idx.get(squash(raw)) or idx.get(fold(raw))

    if not hits:
        # Substring fallback, still exact-normalised on one side.
        needle = squash(raw)
        loose = [h for key, hs in idx.items() if needle and needle in key for h in hs]
        seen_codes: set[str] = set()
        uniq = []
        for h in loose:
            c = str(h["concept"].get("code") or h["concept"].get("key"))
            if c not in seen_codes:
                seen_codes.add(c)
                uniq.append(h)
        if len(uniq) == 1:
            hits = uniq
            hits[0] = dict(hits[0], loose=True)
        elif len(uniq) > 1:
            raise AmbiguousValue(
                f"{raw!r} matches {len(uniq)} concepts in {value_set}",
                f"«{raw}» به چند مورد می‌خورد؛ کدام‌یک؟",
                candidates=[_label(h["concept"]) for h in uniq],
            )
        else:
            raise UnknownValue(
                f"{raw!r} is not a known {value_set}",
                f"«{raw}» در فهرست {value_set} یافت نشد.",
                known=[_label(c) for c in load()["value_sets"][value_set].get("concepts", [])][:40],
            )

    codes = {str(h["concept"].get("code") or h["concept"].get("key")) for h in hits}
    if len(codes) > 1:
        raise AmbiguousValue(
            f"{raw!r} matches {sorted(codes)} in {value_set}",
            f"«{raw}» مبهم است.",
            candidates=sorted(codes),
        )

    hit = hits[0]
    concept = hit["concept"]
    code = str(concept.get("code") or concept.get("key"))

    if concept.get("status") == "disabled" and not allow_disabled:
        raise DisabledValue(
            f"{value_set}={raw!r} exists (code {code}) but is disabled in this "
            f"database, so filtering on it returns almost nothing",
            f"«{raw}» در این مرکز غیرفعال است؛ فیلتر روی آن تقریباً چیزی برنمی‌گرداند.",
            code=code,
        )

    disp = concept.get("display") or {}
    return Resolution(
        value_set=value_set,
        code=code,
        display_en=(disp.get("en") or {}).get("preferred"),
        display_fa=(disp.get("fa") or {}).get("preferred") or concept.get("display_fa"),
        matched_on=hit["surface"],
        exact=not hit.get("loose"),
    )


def _label(concept: dict) -> str:
    disp = concept.get("display") or {}
    return (
        (disp.get("en") or {}).get("preferred")
        or (disp.get("fa") or {}).get("preferred")
        or concept.get("display_fa")
        or str(concept.get("code") or concept.get("key"))
    )


def try_resolve(value_set: str, text: str) -> Resolution | LexiconProblem:
    """Non-raising variant, for building a report of several terms at once."""
    try:
        return resolve(value_set, text)
    except LexiconProblem as exc:
        return exc


# --------------------------------------------------------------------- filter building

def modality_filter(text: str) -> dict[str, Any]:
    """Mongo filter for a modality named in any of its three vocabularies.

    Handles the measured fact that `receptions.modality` is a string on most rows
    and an embedded object on a few (201 vs 4 on 1405/06/01). A plain equality
    filter silently loses the object rows.
    """
    code = resolve("modality", text).code
    return {"$or": [{"modality": code}, {"modality._id": code}]}


def service_group_filter(text: str) -> dict[str, Any]:
    """Match a service group across its Arabic/Persian yeh spellings."""
    concept = None
    key = squash(text)
    for c in load()["value_sets"]["service_group"]["concepts"]:
        if c["key"] == key or key in c["key"]:
            concept = c
            break
    if concept is None:
        raise UnknownValue(
            f"{text!r} is not a known service group",
            f"گروه خدمتی «{text}» یافت نشد.",
        )
    return {"services.ServiceGroup": {"$in": concept["spelling_variants"]}}


def live_only() -> dict[str, Any]:
    return dict(load()["conventions"]["live_only"]["filter"])


# ------------------------------------------------------------------ query validation

#: The contract between the model and the orchestrator. Extensible by design:
#: unknown keys are reported, not silently dropped.
QUERY_KEYS = {
    "mode", "intent", "target_entity", "sources", "filters",
    "fields", "grouping", "sorting", "date_range", "comparison",
    "aggregation", "next_action", "answerable", "reason",
}

FILTER_VALUE_SETS = {
    "modality": "modality",
    "insurance_type": "insurance_type",
    "insurance_source": "insurance_source",
    "report_status": "report_status",
    "service_group": "service_group",
    "transaction_type": "transaction_type",
}


@dataclass
class ValidatedQuery:
    query: dict[str, Any]
    resolved: dict[str, Resolution]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "resolved": {k: v.as_dict() for k, v in self.resolved.items()},
            "warnings": self.warnings,
        }


def validate_query(query: dict[str, Any]) -> ValidatedQuery:
    """Check a model-emitted query against the lexicon.

    Every coded filter value is resolved here, BEFORE anything touches the
    database. An unresolvable value raises, so the orchestrator can tell the user
    "that term is not in the catalogue" instead of running a query that cannot
    match and reporting zero.
    """
    if not isinstance(query, dict):
        raise InvalidQuery("query must be an object")

    unknown = set(query) - QUERY_KEYS
    warnings = [f"unrecognised key {k!r} (ignored)" for k in sorted(unknown)]

    if query.get("answerable") is False:
        return ValidatedQuery(query=query, resolved={}, warnings=warnings)

    entity = query.get("target_entity")
    if entity and entity not in load()["entities"]:
        raise InvalidQuery(
            f"unknown target_entity {entity!r}",
            known=sorted(load()["entities"]),
        )

    resolved: dict[str, Resolution] = {}
    for key, value in (query.get("filters") or {}).items():
        vs = FILTER_VALUE_SETS.get(key)
        if not vs or value in (None, ""):
            continue
        for item in (value if isinstance(value, list) else [value]):
            r = resolve(vs, item)
            resolved[f"{key}={item}"] = r
            if not r.exact:
                warnings.append(
                    f"{key}={item!r} matched {_short(r)} loosely - confirm if surprising"
                )

    agg = query.get("aggregation")
    if agg in ("count", "count_distinct") and entity:
        ck = (load()["entities"].get(entity) or {}).get("count_key")
        if ck:
            warnings.append(f"count grain for {entity} is distinct {ck}")

    return ValidatedQuery(query=query, resolved=resolved, warnings=warnings)


def _short(r: Resolution) -> str:
    return f"{r.code} ({r.display_en or r.display_fa})"


# ------------------------------------------------------------- prompt fragments

def describe_for_prompt(*, value_sets: list[str] | None = None,
                        entities: list[str] | None = None) -> str:
    """A trimmed lexicon fragment for the model.

    Deliberately NOT the whole file. The evidence is consistent that dumping a
    full schema costs accuracy: schema-linking studies measure 10-15% precision
    for the no-pruning baseline, and a single distractor degrades performance
    across models. Ask for the parts the question needs.
    """
    lex = load()
    out: list[str] = [f"# Reception lexicon v{lex['lexicon_version']}"]

    for name in entities or []:
        e = lex["entities"].get(name)
        if not e:
            continue
        out.append(f"\n## entity: {name}")
        out.append(f"  meaning : {e['human']}")
        out.append(f"  stored  : {e['software']}")
        if e.get("count_key"):
            out.append(f"  count by: distinct {e['count_key']}")
        for k in ("grain_warning", "three_vocabularies_warning", "note"):
            if e.get(k):
                out.append(f"  WARNING : {e[k]}")

    for name in value_sets or []:
        vs = lex["value_sets"].get(name)
        if not vs:
            continue
        out.append(f"\n## values: {name}   (field {vs.get('vendor_field')})")
        for k in ("storage_note", "collision_warning", "spelling_warning",
                  "meaning_is_inferred", "note"):
            if vs.get(k):
                out.append(f"  WARNING : {vs[k]}")
        for c in vs.get("concepts", [])[:40]:
            code = c.get("code") or c.get("key")
            label = _label(c)
            syn: list[str] = []
            for lang in ("en", "fa"):
                syn += (c.get("acceptable") or {}).get(lang, []) or []
            tail = f"  aka {', '.join(syn[:6])}" if syn else ""
            flag = "  [DISABLED]" if c.get("status") == "disabled" else ""
            out.append(f"  {code:>12} = {label}{flag}{tail}")

    out.append(
        "\nRules: use the CODE in filters, never the label. If a term is not in "
        "this list, do not invent a filter value - return "
        '{"answerable": false, "reason": "unknown_value", ...} instead.'
    )
    return "\n".join(out)
