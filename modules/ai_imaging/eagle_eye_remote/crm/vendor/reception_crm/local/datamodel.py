"""What each reception field MEANS, and how to filter on it.

Why this module exists
----------------------
A live answer reported **0 BI-RADS 3 mammography reports in five months** and
concluded the clinic had none. The truth, measured afterwards: **418 receptions
included a mammography service and 15 of them carry a BI-RADS 3 report.**

The answer was not wrong because the search failed. It was wrong because the
question was routed to the wrong FIELD. Mammography is a *service* in this
system, not a modality — and the one modality actually named "Mammography"
(code 9) is `Disabled: true` and carries three reports in the entire archive.
Every real mammogram is billed as a service under modality 4 (Radiology) or 2
(MRI). No modality filter, however correct, could ever have found them.

So the fix is not a better search. It is knowing, before querying, which field
answers the question:

    "how many MRIs today"              -> modality
    "how many brain MRI services"      -> service (optionally + modality)
    "how many insured patients had MRI" -> modality + insurance

Everything here was MEASURED against the live database (`scripts/_probe_datamodel*.py`),
not inferred from field names.

The two rules that shape this file
----------------------------------
1. **An unrecognised value must refuse, never return nothing.** The original
   defect was `modality_filter("mammography")` quietly building
   `{"modality": "mammography"}` — a filter that matches zero documents and is
   indistinguishable from a filter that matched zero patients. Every resolver
   here raises :class:`UnknownValue` carrying the vocabulary that does exist, so
   the answer can say "there is no such modality; here are the ones there are".

2. **The vocabulary is read from the database, not hardcoded.** The map that
   caused this listed four modalities when the vendor had seven, and had been
   wrong since the day a fifth was added. `Modality` is a seven-row collection;
   reading it costs nothing and cannot go stale.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .mongo import LocalMongoUnavailable, reception_db

LOG = logging.getLogger("reception_crm.local.datamodel")

RECEPTIONS = "receptions"

#: The catalogue collections change about as often as the clinic buys a scanner.
#: Long enough that no question pays for a reload, short enough that a service
#: added this morning is filterable this afternoon.
CATALOG_TTL_SECONDS = 900.0


class FilterValueProblem(ValueError):
    """A filter that would return nothing for a reason that is not the data.

    Carries the vocabulary so the caller can *say* what exists. The whole point
    is that "this filter cannot match" and "no patients matched" stop looking
    alike — they were indistinguishable, and that is how a clinician was told
    there were no mammography cases when there were 418.
    """

    code = "FILTER_VALUE_PROBLEM"

    def __init__(self, meaning: str, value: str, known: list[str], hint_fa: str = "") -> None:
        self.meaning = meaning
        self.value = value
        self.known = known
        self.hint_fa = hint_fa
        super().__init__(self.summary() + (f" — {hint_fa}" if hint_fa else ""))

    def summary(self) -> str:
        return f"{self.meaning}={self.value!r} cannot be filtered on."

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "field": self.meaning,
            "value": self.value,
            "known": self.known,
            "messageFa": self.hint_fa,
        }


class UnknownValue(FilterValueProblem):
    """This database has no such thing at all."""

    code = "UNKNOWN_FILTER_VALUE"

    def summary(self) -> str:
        return (f"{self.meaning}={self.value!r} does not exist in this database. "
                f"Known: {', '.join(self.known)}")


class DisabledValue(FilterValueProblem):
    """It exists, it is switched off, and filtering on it can only return ~0.

    Distinct from :class:`UnknownValue` because the honest answer is different.
    "There is no such modality" would itself be false: modality 9 IS
    Mammography. It is `Disabled: true`, carries three reports in the whole
    archive, and every mammogram this centre performs is billed as a SERVICE
    under Radiology or MRI. Returning 0 from it — or denying it exists — are
    both wrong; saying which is right.
    """

    code = "MODALITY_DISABLED"

    def summary(self) -> str:
        return (f"{self.meaning}={self.value!r} exists but is disabled in this database, "
                f"so filtering on it returns almost nothing.")


# --------------------------------------------------------------------------- #
# Persian and Arabic letter forms
# --------------------------------------------------------------------------- #
#: The same service is spelled both «سونوگرافی کامل شکم و لگن» (294 receptions in
#: one month) and «سونوگرافي کامل شکم و لگن» (221) — Persian yeh against Arabic
#: yeh. Comparing raw strings does not find "one service performed 515 times";
#: it finds two services and halves whichever one you asked about.
_FOLD = str.maketrans({
    "ي": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
    "أ": "ا", "إ": "ا", "آ": "ا", "ؤ": "و", "ئ": "ی",
    "‌": " ",   # ZERO WIDTH NON-JOINER
    "ً": "", "ٌ": "", "ٍ": "",  # tanween
    "َ": "", "ُ": "", "ِ": "",  # short vowels
    "ّ": "", "ْ": "",
})

#: Arabic-Indic and Persian digits to ASCII, so «۳» and "3" are one thing.
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def fold(text: Any) -> str:
    """Normalise a Persian string for comparison. Idempotent, never raises."""
    if text is None:
        return ""
    folded = str(text).translate(_FOLD).translate(_DIGITS)
    return re.sub(r"\s+", " ", folded).strip().lower()


def fold_regex(text: str) -> str:
    """A regex that matches `text` whichever letter forms the database used.

    Built from the FOLDED needle, with every foldable character expanded back
    into a class of the forms it could have been stored as. Matching on the
    stored value directly is not possible — Mongo has no fold — so the pattern
    has to carry the variance instead.
    """
    variants = {"ی": "[یي]", "ک": "[کك]", "ه": "[هۀة]", "ا": "[اأإآ]", "و": "[وؤ]"}
    out = []
    for char in fold(text):
        if char in variants:
            out.append(variants[char])
        elif char == " ":
            out.append(r"[\s‌]+")
        else:
            out.append(re.escape(char))
    return "".join(out)


# --------------------------------------------------------------------------- #
# The vendor's catalogues, read from the database
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Modality:
    code: str
    name: str          # "MRI"
    name_fa: str       # "ام آر آی"
    short: str         # "MR"
    disabled: bool

    @property
    def label(self) -> str:
        return f"{self.name} ({self.name_fa})" + (" [disabled]" if self.disabled else "")


@dataclass
class _Cache:
    at: float = 0.0
    modalities: dict[str, Modality] = field(default_factory=dict)
    services: list[dict[str, Any]] = field(default_factory=list)

    def stale(self) -> bool:
        return (time.time() - self.at) > CATALOG_TTL_SECONDS


_cache = _Cache()
_lock = threading.Lock()

def _load_catalogues() -> _Cache:
    with _lock:
        if not _cache.stale() and _cache.modalities:
            return _cache
        modalities: dict[str, Modality] = {}
        services: list[dict[str, Any]] = []
        try:
            db = reception_db()
            for row in db["Modality"].find({}, max_time_ms=5000):
                code = str(row.get("_id"))
                modalities[code] = Modality(
                    code=code,
                    name=str(row.get("FullName") or row.get("Modality") or code),
                    name_fa=str(row.get("PerFullName") or ""),
                    short=str(row.get("Modality") or ""),
                    disabled=bool(row.get("Disabled")),
                )
            services = list(
                db["ServicesInfo"].find(
                    {}, {"_id": 1, "Service": 1, "Modality": 1, "ServiceGroup": 1},
                    max_time_ms=8000,
                )
            )
        except (LocalMongoUnavailable, Exception) as exc:  # noqa: BLE001
            LOG.warning("catalogue read failed (%s); consulting the local centre profile",
                        type(exc).__name__)
        if not modalities:
            from ..lexicon import center

            profile = center.load_center()
            if profile.get("available") is False or not profile.get("departments"):
                raise LocalMongoUnavailable(
                    "No verified local department catalogue; run bootstrap-center."
                )
            modalities = {
                str(d["code"]): Modality(
                    str(d["code"]), str(d.get("name_en") or ""),
                    str(d.get("name_fa") or ""), str(d.get("short") or ""),
                    bool(d.get("disabled")),
                ) for d in profile["departments"]
            }
        _cache.modalities = modalities
        _cache.services = services
        _cache.at = time.time()
        return _cache


def modalities() -> dict[str, Modality]:
    return dict(_load_catalogues().modalities)


def service_catalog() -> list[dict[str, Any]]:
    live = list(_load_catalogues().services)
    if live:
        return live

    # `center_config.json` is generated from this centre's own ServicesInfo and
    # bundled with every build.  It is the last-known centre catalogue when a
    # transient local Mongo failure prevents a fresh read.  Falling back here
    # keeps vocabulary/provenance useful without inventing a generic service
    # list; the actual reception query still runs against performed names.
    from ..lexicon import center

    return [
        {
            "_id": row.get("id"),
            "Service": row.get("name"),
            "Modality": row.get("department"),
            "ServiceGroup": row.get("group_name"),
        }
        for row in (center.load_center().get("services") or [])
        if row.get("name")
    ]


def reset_catalog_cache() -> None:
    """Test seam, and a way to pick up a vendor change without a restart."""
    with _lock:
        _cache.at = 0.0
        _cache.modalities = {}
        _cache.services = []


# --------------------------------------------------------------------------- #
# Resolvers: a human's word -> what the database stores
# --------------------------------------------------------------------------- #
def resolve_modality(value: Any) -> Modality:
    """Turn "MRI" / "ام آر آی" / "2" / "MR" into the modality it means.

    Raises :class:`UnknownValue` — never returns a filter that cannot match.
    That is the whole difference between this and the function it replaces.
    """
    known = modalities()
    wanted = fold(value)
    if not wanted:
        raise UnknownValue("modality", str(value), [m.label for m in known.values()])

    if wanted in known:
        return known[wanted]
    exact = [m for m in known.values()
             if wanted in {fold(m.name), fold(m.name_fa), fold(m.short)}]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise UnknownValue("ambiguous modality", str(value), [m.label for m in exact])

    # The LEXICON is the vocabulary authority. The vendor's own four strings
    # (code, name, name_fa, short) are all this function knew, so "ultrasound",
    # "echo", "sonogram", "x-ray" and "xray" were all rejected as non-existent
    # modalities — and the benchmark caught it: run 1 said "Sonography" and
    # worked, run 2 said "ultrasound" and failed. Same question, same day, two
    # answers, because the accepted vocabulary was narrower than the words
    # people use.
    #
    # Imported lazily and guarded: this module must keep working if the lexicon
    # file is missing, because a missing synonym table should narrow what can be
    # asked, never break what already works.
    # Two failures that look alike and are not: the lexicon FILE is missing
    # (a packaging fault — loud) versus the lexicon not knowing this term (the
    # normal negative answer — quiet). One `except Exception: pass` covered both,
    # and that is how a frozen build without lexicon.json shipped while every
    # test passed: PyInstaller does not follow an import to a data file, the
    # FileNotFoundError was swallowed, and the server told people that
    # «ultrasound» is not a modality in this database.
    try:
        from .. import lexicon as _lex
    except Exception as exc:  # noqa: BLE001 - import itself failed
        _warn_lexicon_missing(exc)
    else:
        try:
            # The bundled lexicon supplies WORDS, never another centre's IDs.
            resolved = _lex.resolve("modality", str(value), allow_disabled=True)
            concept = next(
                c for c in _lex.load()["value_sets"]["modality"]["concepts"]
                if str(c.get("code")) == resolved.code
            )
            names = {fold(surface) for _, surface in _lex._concept_keys(concept)
                     if surface != str(concept.get("code"))}
            matches = [m for m in known.values()
                       if names.intersection({fold(m.name), fold(m.name_fa), fold(m.short)})]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise UnknownValue("ambiguous modality", str(value), [m.label for m in matches])
        except FilterValueProblem:
            raise
        except _lex.LexiconProblem:
            pass                      # the term is genuinely unknown — stay quiet
        except Exception as exc:      # noqa: BLE001 - the FILE is unreadable
            _warn_lexicon_missing(exc)

    # A near miss is worth catching: "sono" for "Sonography". ONE direction only
    # — the input must be a fragment OF a catalogue name.
    #
    # The other direction used to be allowed too, and it silently turned a
    # SERVICE into a modality: "Brain MRI" contains "mri", so it resolved to the
    # whole MRI modality and would have answered 62 for a question about brain
    # studies. A wrong answer of that shape is worse than a refusal, because the
    # number looks reasonable. Synonyms are the lexicon's job now, so this loop
    # no longer needs to guess.
    matches = [m for m in known.values()
               if any(candidate and len(wanted) >= 3 and wanted in candidate
                      for candidate in (fold(m.name), fold(m.name_fa), fold(m.short)))]
    if len(matches) == 1:
        return matches[0]

    raise UnknownValue("modality", str(value), [m.label for m in known.values()])


# --------------------------------------------------------------------------- #
# Lexicon availability
# --------------------------------------------------------------------------- #
_lexicon_warned = False


def _warn_lexicon_missing(exc: BaseException) -> None:
    global _lexicon_warned
    if _lexicon_warned:
        return
    _lexicon_warned = True
    LOG.error(
        "LEXICON UNAVAILABLE (%s: %s). Modality synonyms are OFF — only the "
        "vendor's own names will resolve, and normal words like 'ultrasound' "
        "will be reported as non-existent modalities. This is a PACKAGING "
        "fault, not a data fault.",
        type(exc).__name__, exc,
    )


def lexicon_available() -> bool:
    """True when the lexicon file is loadable. Published on /api/health."""
    try:
        from .. import lexicon as _lex

        return bool(_lex.load().get("value_sets"))
    except Exception:  # noqa: BLE001
        return False


#: Where a discount actually is. Measured on 1405/06/01: `cashDeskDiscount`
#: carried all 13,580,000 of it across 3 receptions, while `discountTotal` —
#: the field whose name suggests it — was 0 on every reception. Filtering the
#: obvious field would have reported "no discounts were given".
DISCOUNT_FIELDS = (
    "cashDeskDiscount",
    "discountTotal",
    "customerClubDiscount",
    "fundDiscount",
)


# --------------------------------------------------------------------------- #
# Contrast: با / بدون  — the NEGATION is the discriminator
# --------------------------------------------------------------------------- #
#
# «چند تا MRI با تزریق» returned 0 against real data. Two reasons, and the
# second is the dangerous one:
#
#   1. The word «تزریق» (injection) appears NOWHERE in the service catalogue.
#      Contrast is written «با ماده حاجب» / «با کنتراست».
#   2. Matching on «کنتراست» alone matches «BEDOON کنتراست» — the studies
#      explicitly performed WITHOUT it. On 1405/06/01 that is 68 receptions
#      returned for a question about contrast. A wrong answer of that size,
#      built from a real substring match, is exactly the failure this module
#      exists to prevent.
#
# So contrast is a three-way classification, never a substring test.
_WITH_CONTRAST = re.compile(r"\bبا\s+(?:ماده\s+حاجب|مواد\s+حاجب|كنتراست|کنتراست)")
_WITHOUT_CONTRAST = re.compile(r"بدون\s+(?:ماده\s+حاجب|مواد\s+حاجب|كنتراست|کنتراست)")
_BOTH_CONTRAST = re.compile(r"با\s+و\s+بدون")

#: What a user might say for each. «تزریق» is here because people say it even
#: though the catalogue never does.
CONTRAST_TERMS = {
    "with": ("با تزریق", "تزریق", "با کنتراست", "با ماده حاجب", "with contrast",
             "contrast", "enhanced", "gado", "gadolinium"),
    "without": ("بدون تزریق", "بدون کنتراست", "بدون ماده حاجب", "without contrast",
                "non contrast", "noncontrast", "plain"),
    "both": ("با و بدون", "با و بدون کنتراست", "with and without"),
}


def contrast_of(service_name: Any) -> str:
    """Classify one catalogue service: 'with' | 'without' | 'both' | 'unknown'.

    Order matters: «با و بدون» contains «بدون», so the combined form has to be
    tested first or every combined study is filed as a plain one.
    """
    name = str(service_name or "")
    if _BOTH_CONTRAST.search(name):
        return "both"
    if _WITH_CONTRAST.search(name):
        return "with"
    if _WITHOUT_CONTRAST.search(name):
        return "without"
    return "unknown"


def contrast_intent(text: Any) -> str | None:
    """What the USER asked for: 'with' | 'without' | 'both' | None."""
    wanted = fold(text)
    if not wanted:
        return None
    # The combined form must win before ``without`` because «با و بدون
    # کنتراست» contains the complete phrase «بدون کنتراست». ``without`` still
    # wins before ``with`` because «بدون تزریق» contains «تزریق».
    for intent in ("both", "without", "with"):
        for term in CONTRAST_TERMS[intent]:
            if fold(term) in wanted:
                return intent
    return None


def contrast_classes_for_intent(intent: str) -> set[str]:
    """Stored contrast classes that satisfy one user intent.

    A combined study satisfies ``with`` because contrast was administered.  It
    does *not* satisfy ``without``: the user explicitly asked for a study where
    no contrast was administered.  The old map included it in both directions
    and therefore counted an injected study in a no-injection cohort.
    """
    return {
        "with": {"with", "both"},
        "without": {"without"},
        "both": {"both"},
    }.get(intent, set())


def _phrase_in_text(text: str, phrase: str) -> bool:
    """Whole-token phrase match over already-folded human text."""
    needle = fold(phrase)
    if not needle:
        return False
    pattern = r"(?<!\w)" + re.escape(needle).replace(r"\ ", r"\s+") + r"(?!\w)"
    return re.search(pattern, fold(text)) is not None


def modality_in_text(text: Any) -> Modality | None:
    """Infer one unambiguous configured modality named inside service text."""
    query = fold(text)
    if not query:
        return None
    hits: dict[str, Modality] = {}
    for item in modalities().values():
        if item.disabled:
            continue
        # Numeric department codes are valid explicit filter values, but not
        # safe words to infer from prose ("مرحله 2" is not necessarily MRI).
        candidates = (item.name, item.name_fa, item.short)
        if any(_phrase_in_text(query, candidate) for candidate in candidates if candidate):
            hits[item.code] = item
    return next(iter(hits.values())) if len(hits) == 1 else None


def _concept_in_service_text(text: Any):
    """Return one reviewed service concept mentioned as a whole phrase.

    Exact alias resolution remains the normal path.  This companion is only
    for compound service requests such as «MRI کمر بدون ماده حاجب», where the
    trusted alias is embedded in anatomy and contrast qualifiers.
    """
    from ..lexicon import center

    matches = {
        concept.id: concept
        for concept in center.service_concepts()
        if any(_phrase_in_text(str(text or ""), alias) for alias in concept.aliases)
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


_CONTRAST_SUBJECT_STOP_WORDS = {
    "با", "بدون", "و", "ماده", "مواد", "حاجب", "کنتراست", "تزریق",
    "with", "without", "and", "contrast", "non", "noncontrast", "plain",
}


def _unmapped_contrast_subject(text: Any, modality: Modality | None) -> str:
    """Remove contrast/modality qualifiers and retain the requested anatomy."""
    residual = fold(text)
    phrases = {
        fold(term)
        for terms in CONTRAST_TERMS.values()
        for term in terms
        if fold(term)
    }
    candidates = (
        [item for item in modalities().values() if not item.disabled]
        if modality is None else [modality]
    )
    for item in candidates:
        phrases.update(
            fold(value) for value in (item.name, item.name_fa, item.short)
            if fold(value)
        )
    for phrase in sorted(phrases, key=len, reverse=True):
        pattern = r"(?<!\w)" + re.escape(phrase).replace(r"\ ", r"\s+") + r"(?!\w)"
        residual = re.sub(pattern, " ", residual)
    tokens = re.findall(r"[^\W_]+", residual, flags=re.UNICODE)
    return " ".join(token for token in tokens if token not in _CONTRAST_SUBJECT_STOP_WORDS)


def contrast_service_resolution(
    value: Any, *, modality: Any = None,
) -> dict[str, Any]:
    """Explain anatomy + contrast resolution for a compound service request."""
    query = str(value or "").strip()
    resolved_modality = (
        resolve_modality(modality) if modality not in (None, "") else modality_in_text(query)
    )
    concept = _concept_in_service_text(query)
    subject = ""
    if concept is not None:
        terms = list(concept.match_terms)
    else:
        subject = _unmapped_contrast_subject(query, resolved_modality)
        terms = [subject] if subject else []

    modality_code = resolved_modality.code if resolved_modality is not None else None
    matched_catalogue = sorted({
        str(row.get("Service"))
        for row in service_catalog()
        if modality_code is None or str(row.get("Modality")) == modality_code
        if not terms or any(fold(term) in fold(row.get("Service")) for term in terms)
        if contrast_of(row.get("Service")) in contrast_classes_for_intent(
            contrast_intent(query) or ""
        )
    })
    return {
        "query": query,
        "contrastIntent": contrast_intent(query),
        "subject": subject or None,
        "canonicalConcept": concept.id if concept is not None else None,
        "labelFa": concept.label_fa if concept is not None else None,
        "expandedTerms": terms,
        "inferredModality": (
            resolved_modality.code
            if modality in (None, "") and resolved_modality else None
        ),
        "matchedCatalogServices": matched_catalogue,
    }


def narrow_contrast_services(
    value: Any, names: list[str], *, modality: Any = None,
) -> tuple[list[str], dict[str, Any]]:
    """Keep performed names satisfying both anatomy and contrast semantics."""
    resolution = contrast_service_resolution(value, modality=modality)
    intent = str(resolution.get("contrastIntent") or "")
    terms = [fold(term) for term in resolution.get("expandedTerms") or [] if fold(term)]
    wanted = contrast_classes_for_intent(intent)
    matched = [
        name for name in names
        if contrast_of(name) in wanted
        if not terms or any(term in fold(name) for term in terms)
    ]
    return sorted(dict.fromkeys(matched)), resolution


def services_by_contrast(intent: str, *, modality: str | None = None) -> list[str]:
    """Catalogue service names matching a contrast intent.

    «با تزریق» is answered by 'with' AND 'both': a study performed with and
    without contrast did involve an injection. Saying so is the honest answer;
    silently counting only one of them is not.
    """
    wanted = contrast_classes_for_intent(intent)
    out = []
    for row in service_catalog():
        if modality is not None and str(row.get("Modality")) != str(modality):
            continue
        if contrast_of(row.get("Service")) in wanted:
            out.append(row.get("Service"))
    return [s for s in out if s]


#: Said in Persian because it is shown to a receptionist. Named as a constant
#: because two different code paths need to say the same thing, and this is the
#: sentence that turns the original wrong answer into a right one.
SERVICE_NOT_MODALITY_FA = (
    "ماموگرافی در این سیستم یک «خدمت» است، نه یک مودالیتی: مودالیتی ۹ غیرفعال "
    "است و ماموگرافی‌ها زیر رادیولوژی و ام‌آر‌آی ثبت می‌شوند. با فیلتر «خدمت» "
    "جست‌وجو کنید."
)


def modality_filter(value: Any) -> dict[str, Any] | None:
    """Match a modality whichever way this database stored it.

    Several hundred receptions embed the whole Modality document in the
    ``modality`` field instead of its code (measured: 48 of 400 sampled), so a
    plain ``{"modality": "3"}`` silently misses them.

    A **disabled** modality raises rather than filtering. Mammography is the
    case that matters: modality 9 really is called Mammography, so calling it
    unknown would be false — but it is switched off and holds three reports in
    the entire archive, while 418 mammography receptions sit under Radiology
    and MRI as services. Filtering on it would return ~0 and be believed.
    """
    if value in (None, ""):
        return None
    resolved = resolve_modality(value)
    if resolved.disabled:
        hint = SERVICE_NOT_MODALITY_FA if "ماموگراف" in fold(resolved.name_fa) or \
            "mammo" in fold(resolved.name) else (
            f"مودالیتی «{resolved.name}» در این مرکز غیرفعال است و رکوردی زیر آن ثبت نمی‌شود."
        )
        raise DisabledValue(
            "modality", str(value),
            [m.label for m in modalities().values() if not m.disabled],
            hint,
        )
    return {"$or": [{"modality": resolved.code}, {"modality._id": resolved.code}]}


def service_filter(value: Any) -> dict[str, Any] | None:
    """Match what was PERFORMED, by service name.

    A substring match on the folded name rather than equality: there are 519
    services in the catalogue and 432 distinct names used in a single month,
    with the same procedure spelled several ways. Somebody asking for
    «ماموگرافی» means all ten mammography services, not one exact string.
    """
    if value in (None, ""):
        return None
    from ..lexicon import center

    terms = tuple(term for term in center.service_search_terms(str(value)) if fold(term))
    if not terms:
        return None
    filters = [
        {"services.Service": {"$regex": fold_regex(term), "$options": "i"}}
        for term in terms
    ]
    return filters[0] if len(filters) == 1 else {"$or": filters}


def matching_services(value: Any, *, modality: Any = None) -> list[str]:
    """Which catalogued services a service filter will actually match.

    Published with the answer so "418 mammography receptions" can say *which*
    services it counted. A count whose definition is invisible is a count
    nobody can check.
    """
    if value in (None, ""):
        return []
    from ..lexicon import center

    needles = tuple(fold(term) for term in center.service_search_terms(str(value)) if fold(term))
    modality_code = resolve_modality(modality).code if modality not in (None, "") else None
    return sorted({
        str(row.get("Service"))
        for row in service_catalog()
        if modality_code is None or str(row.get("Modality")) == modality_code
        if any(needle in fold(row.get("Service")) for needle in needles)
    })


def service_resolution(value: Any, *, modality: Any = None) -> dict[str, Any]:
    """Explain exactly how a user service term becomes a database filter."""
    from ..lexicon import center

    query = str(value or "").strip()
    mapped = center.service_concept(query)
    terms = list(center.service_search_terms(query)) if query else []
    return {
        "query": query,
        "canonicalConcept": mapped.id if mapped else None,
        "labelFa": mapped.label_fa if mapped else None,
        "expandedTerms": terms,
        "matchedCatalogServices": matching_services(query, modality=modality),
    }


#: `insuranceType` is a code on the reception. `InsuranceSetting` explains only
#: two of the five codes in use, so the rest are labelled from what the reception
#: itself carries (the per-insurer total fields) rather than invented. Codes with
#: no evidence are left unnamed ON PURPOSE — a guessed label on a financial
#: filter is worse than no label.
INSURANCE_CODES = {
    "2": "سلامت ایرانیان",
    "4": "تامین اجتماعی",
}


def insurance_filter(value: Any) -> dict[str, Any] | None:
    """Filter by insurer.

    Accepts a code, or a name for the two codes the vendor's `InsuranceSetting`
    collection actually names. Anything else refuses rather than guessing: the
    remaining codes (0, 1, 3) have no row in that collection, and inventing
    "1 = آزاد" would put a made-up label on a financial answer.
    """
    if value in (None, ""):
        return None
    wanted = fold(value)
    for code, name in INSURANCE_CODES.items():
        if wanted in (fold(code), fold(name)):
            return {"insuranceType": code}
    if wanted.isdigit():
        # A bare code the catalogue does not name is still a real stored value,
        # so it filters — the caller just gets no label for it.
        return {"insuranceType": wanted}
    raise UnknownValue(
        "insurance", str(value),
        [f"{code} ({name})" for code, name in INSURANCE_CODES.items()],
        "کدهای بیمهٔ دیگر در این پایگاه داده نام ندارند؛ با شمارهٔ کد جست‌وجو کنید.",
    )


#: Two different statuses that mean different things, and neither is a
#: top-level `status` field — there isn't one.
REPORT_STATUSES = (
    "completed", "pending", "awaiting_secretary_approval",
    "awaiting_physician_approval", "physician_approved",
)
WORKFLOW_STATUSES = ("waiting_appointment", "inProgress")


def report_status_filter(value: Any) -> dict[str, Any] | None:
    if value in (None, ""):
        return None
    wanted = str(value).strip()
    if wanted not in REPORT_STATUSES:
        raise UnknownValue("reportStatus", wanted, list(REPORT_STATUSES))
    return {"imagingWorkflow.report.status": wanted}


JALALI_DATE = re.compile(r"^\d{4}/\d{2}/\d{2}$")


def date_range_filter(date_from: str | None, date_to: str | None) -> dict[str, Any] | None:
    """`Date` is a zero-padded Jalali STRING, so a lexicographic range is valid.

    `createdAt` is a real datetime and must never be mixed into the same filter.
    """
    bounds: dict[str, Any] = {}
    if date_from and JALALI_DATE.match(str(date_from).strip()):
        bounds["$gte"] = str(date_from).strip()
    if date_to and JALALI_DATE.match(str(date_to).strip()):
        bounds["$lte"] = str(date_to).strip()
    return {"Date": bounds} if bounds else None


#: Excluded from every count unless a caller explicitly asks otherwise. The
#: vendor's own indexes all carry this flag, which is the clearest statement
#: available that their software never counts these rows either. Measured
#: impact on report counts is small (14 of 25,638) — it is here for
#: correctness, not because it moves a number.
LIVE_ONLY = {"deleted": {"$ne": True}}


# --------------------------------------------------------------------------- #
# The catalogue itself: meaning -> field -> filter
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Field:
    """One thing a question can be *about*, and how to ask the database for it."""

    meaning: str
    label_fa: str
    path: str
    build: Callable[[Any], dict[str, Any] | None]
    answers: tuple[str, ...]
    caveat_fa: str = ""
    indexed: bool = False


FIELDS: tuple[Field, ...] = (
    Field(
        meaning="modality",
        label_fa="مودالیتی",
        path="modality",
        build=modality_filter,
        answers=("چند تا ام آر آی", "بیماران سی تی", "سونوگرافی امروز"),
        caveat_fa=(
            "مودالیتی نوع دستگاه است، نه نوع خدمت. ماموگرافی و سنجش تراکم استخوان "
            "را با فیلتر «خدمت» بگیرید."
        ),
        indexed=True,
    ),
    Field(
        meaning="service",
        label_fa="خدمت",
        path="services.Service",
        build=service_filter,
        answers=("ماموگرافی", "ام آر آی مغز", "سونوگرافی پستان", "کدام خدمت‌ها"),
        caveat_fa=(
            "نام خدمت متن آزاد فارسی است و املای «ی/ي» و «ک/ك» متفاوت دارد؛ "
            "جست‌وجو باید هر دو شکل را بگیرد. روی این فیلد ایندکس نیست، پس بازهٔ "
            "تاریخ لازم است."
        ),
    ),
    Field(
        meaning="insurance",
        label_fa="بیمه",
        path="insuranceType",
        build=insurance_filter,
        answers=("بیماران بیمه‌ای", "تامین اجتماعی", "آزاد"),
        caveat_fa="فقط کدهای ۲ و ۴ در پایگاه داده نام دارند.",
    ),
    Field(
        meaning="reportStatus",
        label_fa="وضعیت گزارش",
        path="imagingWorkflow.report.status",
        build=report_status_filter,
        answers=("گزارش‌های نوشته‌نشده", "در انتظار تأیید پزشک"),
        caveat_fa="با وضعیت گردش کار (workflowStatus) یکی نیست.",
        indexed=True,
    ),
    Field(
        meaning="date",
        label_fa="تاریخ",
        path="Date",
        build=lambda v: date_range_filter(v, v),
        answers=("امروز", "این ماه", "۵ ماه گذشته"),
        caveat_fa="تاریخ جلالی رشته‌ای است؛ createdAt میلادی و چیز دیگری است.",
        indexed=True,
    ),
)

BY_MEANING = {f.meaning: f for f in FIELDS}


def describe_for_prompt() -> str:
    """The catalogue as the planner sees it. Generated, so it cannot drift."""
    lines = ["Fields you can filter a reception by — pick the one the question is about:"]
    for f in FIELDS:
        lines.append(f"* `{f.meaning}` ({f.label_fa}) — {f.path}")
        lines.append(f"    answers: {'، '.join(f.answers)}")
        if f.caveat_fa:
            lines.append(f"    caveat: {f.caveat_fa}")
    known = modalities()
    active = [m for m in known.values() if not m.disabled]
    off = [m for m in known.values() if m.disabled]
    lines.append("Modalities that exist: " + ", ".join(f"{m.code}={m.name}" for m in active))
    if off:
        lines.append("Disabled (present but unused): "
                     + ", ".join(f"{m.code}={m.name}" for m in off))
    return "\n".join(lines)
