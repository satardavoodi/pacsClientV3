"""EchoMind — per-chat case metadata (storage + three-layer merge).

WHAT THIS IS
------------
Every EchoMind chat (``ai_sessions.sid``) gets a persistent record describing the
CASE it is about: patient, study/studies, reception services, modality, regions.
It is **not** the report and **not** the conversation — it is the context a report
is generated *from*.

WHAT READS THIS — updated 2026-08-09
-----------------------------------
``ai_chat_pages._build_gate_profile()`` reads the EFFECTIVE record on every Turbo
report and turns ``case.regions`` into the region packages the prompt carries. That
is the only prompt consumer: Send, correction, standardize and the assist flows still
do not read this module, and ``build_report_system_prompt`` is untouched.

The consequence worth holding on to: what the gate acts on is exactly what the
physician was shown on the metadata card and could have corrected. Do not add a
second, invisible detection path that feeds the prompt without feeding the card.
See ``docs/echomind/03-region-gating.md``.

THE THREE LAYERS — why this is not one blob
-------------------------------------------
    auto  — what detection produced (DICOM, reception, dictation, later an LLM)
    user  — ONLY the fields the physician edited (sparse)
    effective = deep_merge(auto, user)     # user wins, field by field

Storing them apart is what lets re-detection refresh ``auto`` **without destroying
the physician's corrections**, lets the UI say "detected" vs "you set this", and
makes "reset this field" a delete rather than a guess. A single merged blob forces
a bad trade: either a refresh silently clobbers user intent, or one edit freezes
all future enrichment.

SAFETY NOTES BAKED IN
---------------------
* ``sex`` is **never inferred**. It is populated only from a verified source and is
  otherwise absent. Measured on this installation: DICOM ``patients.sex`` is 3%
  populated (60/1807). The report prompts carry a deliberate rule — *"Do NOT infer
  or assume the patient's sex … NEVER output both male and female organs"* — which
  exists because guessing produced wrong reports. A blank field invites a guess, so
  this module refuses to fill it and records provenance when something else does.
* Region mapping is **conservative**: an unrecognised body part maps to nothing
  rather than to a plausible-looking guess. Under-detection is recoverable (the
  consumer falls back to the full prompt); a wrong region is not.
* Every auto-detected value carries **provenance** (source + confidence) so a
  consumer can refuse low-confidence data and the UI can be honest about it.

Pure stdlib apart from the DB connection helper, so the merge/build logic is unit
testable without Qt or a database.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

#: Canonical region keys. These are the vocabulary the (later) prompt-gating step
#: will select region blocks with, so they intentionally mirror the per-modality
#: GROUPING VOCABULARY headings already in ``openai_reporter``.
REGION_KEYS: Tuple[str, ...] = (
    "brain", "head_neck", "chest", "abdomen", "pelvis", "paranasal_sinuses",
    "spine_cervical", "spine_thoracic", "spine_lumbar", "spine",
    "shoulder", "hip", "knee", "ankle_foot", "wrist_hand", "extremity",
    "breast", "prostate", "thyroid", "scrotum", "obstetric",
    # 2026-08-08: the three CT regions with real tariff volume and no coverage —
    # temporal bone 11 service codes, orbit 9, maxillofacial/dental 8. A region that
    # is not in this tuple can never be detected, so the blocks written for them
    # would have been unreachable.
    "temporal_bone", "orbit", "dental_maxillofacial",
    # added 2026-08-09 with the radiography library: `elbow` is a real MSK
    # radiograph region the CT-derived list never needed, and `bone_density`
    # is DEXA, a study family with its own report shape rather than a slice
    # of an existing region.
    "elbow", "bone_density",
)

#: DICOM ``body_part`` / ``body_part_examined`` -> canonical region key(s).
#: Values are the ones actually present in this installation (measured), plus the
#: obvious synonyms. UNKNOWN VALUES MAP TO NOTHING — never to a guess.
_DICOM_REGION_MAP: Dict[str, Tuple[str, ...]] = {
    "BRAIN": ("brain",),
    # 2026-08-08: a paranasal-sinus CT reported orbits and dentition as normal but
    # not the sinuses. Without a region key it cannot be detected or gated on.
    "SINUS": ("paranasal_sinuses",),
    "SINUSES": ("paranasal_sinuses",),
    "PNS": ("paranasal_sinuses",),
    "PARANASALSINUS": ("paranasal_sinuses",),
    "PARANASALSINUSES": ("paranasal_sinuses",),
    "PARANASAL_SINUSES": ("paranasal_sinuses",),
    "HEAD": ("brain",),
    "SKULL": ("brain",),
    "TEMPORALBONE": ("temporal_bone",),
    "TEMPORAL_BONE": ("temporal_bone",),
    "PETROUS": ("temporal_bone",),
    "IAC": ("temporal_bone",),
    "INNEREAR": ("temporal_bone",),
    "EAR": ("temporal_bone",),
    "MASTOID": ("temporal_bone",),
    "ORBIT": ("orbit",),
    "ORBITS": ("orbit",),
    "EYE": ("orbit",),
    "MAXILLOFACIAL": ("dental_maxillofacial",),
    "MANDIBLE": ("dental_maxillofacial",),
    "MAXILLA": ("dental_maxillofacial",),
    "ELBOW": ("elbow",),
    "OLECRANON": ("elbow",),
    "RADIUS": ("elbow", "wrist_hand"),
    "BONE DENSITY": ("bone_density",),
    "DEXA": ("bone_density",),
    "DXA": ("bone_density",),
    "ELBOW": ("elbow",),
    "OLECRANON": ("elbow",),
    "RADIUS": ("elbow", "wrist_hand"),
    "BONE DENSITY": ("bone_density",),
    "DEXA": ("bone_density",),
    "DXA": ("bone_density",),
    "TMJ": ("dental_maxillofacial",),
    "JAW": ("dental_maxillofacial",),
    "DENTAL": ("dental_maxillofacial",),
    "FACE": ("dental_maxillofacial",),
    "NECK": ("head_neck",),
    "CHEST": ("chest",),
    "THORAX": ("chest",),
    "LUNG": ("chest",),
    "ABDOMEN": ("abdomen",),
    "ABDOMENPELVIS": ("abdomen", "pelvis"),      # multi-region in ONE tag
    "ABDOMEN_PELVIS": ("abdomen", "pelvis"),
    "PELVIS": ("pelvis",),
    "CSPINE": ("spine_cervical",),
    "TSPINE": ("spine_thoracic",),
    "LSPINE": ("spine_lumbar",),
    "SPINE": ("spine",),
    "SHOULDER": ("shoulder",),
    "HIP": ("hip",),
    "KNEE": ("knee",),
    "ANKLE": ("ankle_foot",),
    "FOOT": ("ankle_foot",),
    # 2026-08-11: a left-heel radiograph gated to nothing. The calcaneus IS the heel.
    "CALCANEUS": ("ankle_foot",),
    "CALCANEUM": ("ankle_foot",),
    "HEEL": ("ankle_foot",),
    "WRIST": ("wrist_hand",),
    "HAND": ("wrist_hand",),
    "BREAST": ("breast",),
    "PROSTATE": ("prostate",),
    "THYROID": ("thyroid",),
    "SCROTUM": ("scrotum",),
    "EXTREMITY": ("extremity",),
}


# ═══════════════════════════════════════════════════════════════════════════
# Pure logic — no DB, no Qt. Unit-testable on its own.
# ═══════════════════════════════════════════════════════════════════════════

def normalize_region(raw: Any) -> Tuple[str, ...]:
    """Map a DICOM body-part string to canonical region key(s).

    Returns an EMPTY tuple for anything unrecognised — deliberately. A wrong
    region silently removes the correct reporting rules; a missing one only falls
    back to the full prompt.
    """
    if not raw:
        return ()
    key = "".join(ch for ch in str(raw).upper() if ch.isalnum() or ch == "_").strip("_")
    if not key:
        return ()
    if key in _DICOM_REGION_MAP:
        return _DICOM_REGION_MAP[key]
    # tolerate simple suffixes/prefixes ("CTCHEST", "CHESTW")
    for token, regions in _DICOM_REGION_MAP.items():
        if len(token) >= 4 and token in key:
            return regions
    return ()


def deep_merge(base: Any, override: Any) -> Any:
    """Merge ``override`` onto ``base``; dicts merge recursively, everything else
    replaces. ``None`` in the override is treated as "not set" so a sparse user
    layer cannot accidentally blank an auto-detected field.
    """
    if isinstance(base, dict) and isinstance(override, dict):
        out = dict(base)
        for k, v in override.items():
            if v is None:
                continue
            out[k] = deep_merge(out.get(k), v) if k in out else copy.deepcopy(v)
        return out
    if override is None:
        return copy.deepcopy(base)
    return copy.deepcopy(override)


def merge_layers(auto: Optional[dict], user: Optional[dict]) -> dict:
    """The effective record: the user's edits win, field by field."""
    return deep_merge(auto or {}, user or {})


def edited_fields(user: Optional[dict], _prefix: str = "") -> List[str]:
    """Dotted paths the physician has explicitly set — what the UI marks as edited."""
    out: List[str] = []
    for k, v in (user or {}).items():
        path = f"{_prefix}{k}"
        if isinstance(v, dict):
            out.extend(edited_fields(v, f"{path}."))
        elif v is not None:
            out.append(path)
    return sorted(out)


def empty_record() -> dict:
    return {
        "schema_ver": SCHEMA_VERSION,
        "patient": {},
        "studies": [],
        "reception": {},
        "case": {},
        "provenance": {},
    }


#: Series that carry no anatomy and no demographics. The scanned reception sheet is
#: imported as a DOC series into the same study, and on this installation it sorts
#: FIRST -- which is how 866 studies ended up with a NULL patient sex despite every
#: CT slice in them carrying "M".
_NON_IMAGE_MODALITIES = {"DOC", "SR", "PR", "KO", "SEG", "RTSTRUCT", "PDF"}

#: PatientSex · PatientAge · StudyDescription · ProtocolName · BodyPartExamined ·
#: Modality. Reading only these is measurably cheaper than the whole header and makes
#: the intent explicit.
_FACT_TAGS = [0x00100040, 0x00101010, 0x00081030, 0x00181030, 0x00180015, 0x00080060]


def read_dicom_facts(study_path: Optional[str], *, max_series: int = 40) -> dict:
    """Read what the database lost, straight from the files on disk.

    MEASURED, NOT ASSUMED. On this installation the SQLite projection of the DICOM is
    lossy: ``patients.sex`` is populated for 3% of patients, ``patients.age`` 12%,
    ``series.body_part_examined`` 7%, ``series.protocol_name`` 0%,
    ``studies.study_description`` 19%. The files carry all of it. A metadata layer --
    and the region gate that will read it -- cannot be built on a 7% column.

    ONE header per series, pixels never touched, six tags: ~2.5 ms per series measured,
    ~40 ms for a 16-series CT. Bounded by ``max_series`` so a pathological study cannot
    stall chat creation.

    Fully swallowed by design: an unreadable or absent study yields ``{}`` and the
    caller simply gets a smaller record.
    """
    out: dict = {}
    path = (str(study_path or "")).strip()
    if not path or not os.path.isdir(path):
        return out
    try:
        import pydicom
    except Exception as exc:
        logger.debug("[EchoMind-meta] pydicom unavailable: %s", exc)
        return out

    body_parts: List[str] = []
    try:
        subs = sorted(
            os.path.join(path, d) for d in os.listdir(path)
            if os.path.isdir(os.path.join(path, d))
        )[:max_series]
    except OSError as exc:
        logger.debug("[EchoMind-meta] cannot list %s: %s", path, exc)
        return out

    for sub in subs:
        first = None
        try:
            for root, _dirs, files in os.walk(sub):
                if files:
                    first = os.path.join(root, sorted(files)[0])
                    break
        except OSError:
            continue
        if not first:
            continue
        try:
            ds = pydicom.dcmread(first, force=True, stop_before_pixels=True,
                                 specific_tags=_FACT_TAGS)
        except Exception:
            continue

        def _g(tag):
            v = getattr(ds, tag, None)
            return "" if v is None else str(v).strip()

        if _g("Modality").upper() in _NON_IMAGE_MODALITIES:
            continue          # the reception scan knows nothing about the patient

        # First non-empty wins: identical across every image series of a study, and a
        # series that omits a tag must not blank one that supplied it.
        for key, tag in (("sex", "PatientSex"), ("age", "PatientAge"),
                         ("study_description", "StudyDescription"),
                         ("protocol_name", "ProtocolName"),
                         # 2026-08-09: the only DICOM statement about contrast. Often
                         # absent or junk, so `detect_contrast` treats it as one vote.
                         ("contrast_agent", "ContrastBolusAgent")):
            if not out.get(key):
                val = _g(tag)
                if val:
                    out[key] = val

        bp = _g("BodyPartExamined").upper()
        if bp and bp not in body_parts:
            body_parts.append(bp)

    if body_parts:
        out["body_parts"] = body_parts
    return out


_AR_TO_FA = {ord("\u064a"): "\u06cc",   # Arabic yeh  -> Persian yeh
             ord("\u0643"): "\u06a9",   # Arabic kaf  -> Persian kaf
             ord("\u200c"): " "}         # ZWNJ -> space, so «بدون‌تزریق» still matches


def _fa_norm(value: Any) -> str:
    """Lowercased, Arabic-script-normalised text for keyword matching.

    Reception text is typed by staff on mixed keyboards, so the same word arrives with
    Arabic ي/ك or Persian ی/ک interchangeably. Matching without this finds one and
    misses the other for no visible reason.
    """
    return str(value or "").translate(_AR_TO_FA).lower().strip()


#: Tested BEFORE the with-forms, always. «بدون تزریق» contains «تزریق», so a with-first
#: order would read "without injection" as "with injection" — the exact inversion that
#: would license fabricated enhancement findings on a non-contrast study.
_CONTRAST_WITHOUT = (
    "بدون تزریق", "بدون کنتراست",
    # «مواد» (plural) is the form the reception system actually books with; only the
    # singular «ماده» was listed here until patient 52230 showed the miss.
    "بدون ماده حاجب", "بدون مواد حاجب", "بدون مده حاجب",
    "without contrast", "non-contrast", "noncontrast", "non contrast",
    "w/o contrast", "no contrast", "unenhanced", "without iv",
)
_CONTRAST_WITH = (
    "با تزریق", "با کنتراست", "با ماده حاجب", "با مواد حاجب", "با مده حاجب",
    # A dynamic / multiphase protocol IS a contrast protocol. Listing these matters
    # less for detecting "with" than for detecting the CONFLICT below: a booking that
    # names both a dynamic study and a non-contrast one must not resolve to either.
    "دینامیک", "تری فازیک", "تریفازیک", "سه فازی",
    "dynamic", "triphasic", "tri-phasic", "multiphasic", "multiphase",
    "with contrast", "post-contrast", "post contrast",
    "contrast-enhanced", "contrast enhanced", "with iv",
)
#: "With AND without" — a combined protocol, so contrast WAS administered. Matched
#: BEFORE the without-forms because «با و بدون ماده حاجب» contains «بدون ماده حاجب»
#: verbatim, and "with and without contrast" contains "without contrast". Patient
#: 52057 was booked exactly this way and was recorded as a non-contrast study, which
#: stripped the enhancement normal-lines off an MS protocol that had been injected.
_CONTRAST_BOTH = (
    "با و بدون", "بدون و با", "با و بدن",
    "قبل و بعد از تزریق", "بعد و قبل از تزریق",
    "with and without", "without and with", "pre and post", "pre- and post",
)

#: A ContrastBolusAgent holding one of these is the scanner saying "nothing given".
_AGENT_NULLS = ("", "none", "n/a", "na", "no", "-", "0", "nil")


def detect_contrast(*texts: Any, agent: Any = "") -> Tuple[str, str]:
    """(state, source) where state is 'with', 'without', or '' for unknown.

    NEVER GUESSES. Unknown is a first-class answer and the common one: the prompt
    already knows how to stay neutral about contrast, and a wrong confident answer
    here either suppresses real guidance or licenses a fabricated observation.

    `agent` (DICOM ContrastBolusAgent) outranks the booking text because it records
    what was administered rather than what was ordered — but only when it holds an
    actual agent name, since scanners routinely populate it with "NONE" or a blank.
    """
    a = _fa_norm(agent)
    if a and a not in _AGENT_NULLS and not any(p in a for p in _CONTRAST_WITHOUT):
        return "with", "dicom"

    # All the texts together, not first-match-wins. Patient 52230 was booked
    # «MRI دینامیک هر قسمت بدن بجز قلب / MRI ... شکم بدون مواد حاجب» — two services in
    # one string, one implying contrast and one excluding it. Reading whichever came
    # first would have stripped the enhancement normal-lines off a triphasic
    # post-contrast study. A booking that says both things says nothing.
    blob = " / ".join(x for x in (_fa_norm(t) for t in texts) if x)
    if not blob:
        return "", ""

    # First, and deliberately not part of the conflict test below: a with-and-without
    # protocol is not two studies disagreeing, it is one study that was injected.
    if any(p in blob for p in _CONTRAST_BOTH):
        return "with", "service_text"

    says_without = any(p in blob for p in _CONTRAST_WITHOUT)
    says_with = any(p in blob for p in _CONTRAST_WITH)
    if says_without and says_with:
        return "", "conflict"
    if says_without:
        return "without", "service_text"
    if says_with:
        return "with", "service_text"
    return "", ""


_ENV_REGION_FROM_TEXT = "AIPACS_REGION_FROM_TEXT"


def region_text_enabled() -> bool:
    """Kill switch. ``0`` restores DICOM-only region detection."""
    raw = os.environ.get(_ENV_REGION_FROM_TEXT)
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


#: Free text -> canonical region key(s). STRICTLY ORDERED, most specific first, and
#: each match is CONSUMED from the string before the next pattern is tried. Without
#: that, «ستون فقرات گردنی» (cervical spine) would also match the bare «گردن» and add
#: head_neck, and every lumbar-spine booking would gate as three regions.
#:
#: Short words are deliberately absent. «سر», «پا», «دست» and «ران» all occur inside
#: ordinary Persian words — «ایران» contains «ران» — so they are only reachable through
#: a qualified form («مچ دست», «مفصل ران»). A missed region falls back to the wider
#: DICOM set; a wrong one silently deletes the correct reporting rules.
_TEXT_REGION_PATTERNS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    # ── spine: every qualified form before the bare one
    ("ستون فقرات گردنی", ("spine_cervical",)),
    ("مهره های گردنی", ("spine_cervical",)),
    ("سرویکال", ("spine_cervical",)),
    ("cervical spine", ("spine_cervical",)),
    ("ستون فقرات سینه ای", ("spine_thoracic",)),
    ("ستون فقرات پشتی", ("spine_thoracic",)),
    ("مهره های پشتی", ("spine_thoracic",)),
    ("توراسیک", ("spine_thoracic",)),
    ("thoracic spine", ("spine_thoracic",)),
    ("dorsal spine", ("spine_thoracic",)),
    ("ستون فقرات کمری", ("spine_lumbar",)),
    ("مهره های کمری", ("spine_lumbar",)),
    ("لومبوساکرال", ("spine_lumbar",)),
    ("لومبار", ("spine_lumbar",)),
    ("lumbosacral", ("spine_lumbar",)),
    ("lumbar spine", ("spine_lumbar",)),
    ("ستون فقرات", ("spine",)),
    ("توتال اسپاین", ("spine",)),
    ("total spine", ("spine",)),
    # ── head and neck
    ("سینوس های پارانازال", ("paranasal_sinuses",)),
    ("سینوس پارانازال", ("paranasal_sinuses",)),
    ("پارانازال", ("paranasal_sinuses",)),
    ("paranasal", ("paranasal_sinuses",)),
    ("سینوس", ("paranasal_sinuses",)),
    ("استخوان تمپورال", ("temporal_bone",)),
    ("تمپورال", ("temporal_bone",)),
    ("ماستوئید", ("temporal_bone",)),
    ("temporal bone", ("temporal_bone",)),
    ("mastoid", ("temporal_bone",)),
    ("حدقه", ("orbit",)),
    ("اوربیت", ("orbit",)),
    ("orbit", ("orbit",)),
    ("فک و صورت", ("dental_maxillofacial",)),
    ("ماگزیلوفاشیال", ("dental_maxillofacial",)),
    ("maxillofacial", ("dental_maxillofacial",)),
    ("دندان", ("dental_maxillofacial",)),
    ("مغز", ("brain",)),
    ("جمجمه", ("brain",)),
    ("brain", ("brain",)),
    # The ADJECTIVE «گردنی» (cervical) modifies a spine structure — «نخاع گردنی»,
    # «دیسک گردنی», «لوردوز گردنی». The bare noun «گردن» is the neck itself.
    # Before the noun, or "cervical spinal cord" gates head_neck (patient 52057).
    ("گردنی", ("spine_cervical",)),
    ("سر و گردن", ("head_neck",)),
    ("نرم کام گردن", ("head_neck",)),
    ("گردن", ("head_neck",)),
    ("head and neck", ("head_neck",)),
    ("تیروئید", ("thyroid",)),
    ("thyroid", ("thyroid",)),
    # ── trunk
    ("قفسه سینه", ("chest",)),
    ("توراکس", ("chest",)),
    ("ریه", ("chest",)),
    ("chest", ("chest",)),
    ("thorax", ("chest",)),
    ("شکم و لگن", ("abdomen", "pelvis")),
    ("abdomen and pelvis", ("abdomen", "pelvis")),
    ("شکم", ("abdomen",)),
    ("کبد", ("abdomen",)),
    ("abdomen", ("abdomen",)),
    ("abdominal", ("abdomen",)),
    ("liver", ("abdomen",)),
    # Before the bare «لگن», which would otherwise consume it and lose the hip.
    # A pelvis-and-hip radiograph covers both, so it yields both.
    ("لگن و ران", ("pelvis", "hip")),
    ("لگن", ("pelvis",)),
    ("pelvis", ("pelvis",)),
    ("pelvic", ("pelvis",)),
    # ── organs with their own region
    ("پستان", ("breast",)),
    ("ماموگرافی", ("breast",)),
    ("breast", ("breast",)),
    ("mammograph", ("breast",)),
    ("پروستات", ("prostate",)),
    ("prostate", ("prostate",)),
    ("اسکروتوم", ("scrotum",)),
    ("بیضه", ("scrotum",)),
    ("scrotum", ("scrotum",)),
    ("بارداری", ("obstetric",)),
    ("حاملگی", ("obstetric",)),
    ("جنین", ("obstetric",)),
    ("obstetric", ("obstetric",)),
    # ── musculoskeletal: qualified forms only
    ("مچ دست", ("wrist_hand",)),
    ("مچ پا", ("ankle_foot",)),
    # The heel. «پاشنه پا» before «پاشنه» so the longer form claims its own span, and
    # both before any bare foot word. Patient 54120's booking read «پاشنه پاي چپ» and
    # matched nothing at all, so half a two-part study vanished from the gate.
    ("پاشنه پا", ("ankle_foot",)),
    ("پاشنه", ("ankle_foot",)),
    ("کالکانئوس", ("ankle_foot",)),
    ("کالکانوس", ("ankle_foot",)),
    ("calcaneus", ("ankle_foot",)),
    ("calcaneum", ("ankle_foot",)),
    ("heel", ("ankle_foot",)),
    ("مفصل ران", ("hip",)),
    ("هیپ", ("hip",)),
    ("wrist", ("wrist_hand",)),
    ("ankle", ("ankle_foot",)),
    ("hip joint", ("hip",)),
    ("شانه", ("shoulder",)),
    ("کتف", ("shoulder",)),
    ("shoulder", ("shoulder",)),
    ("زانو", ("knee",)),
    ("knee", ("knee",)),
    ("آرنج", ("elbow",)),
    ("elbow", ("elbow",)),
    ("سنجش تراکم استخوان", ("bone_density",)),
    ("دانسیتومتری", ("bone_density",)),
    ("bone density", ("bone_density",)),
    ("dexa", ("bone_density",)),
)


def _service_segments(text: Any) -> List[str]:
    """A booking often names SEVERAL studies, separated by "/" or "،".

    Patient 54120 was booked «راديوگرافي پاشنه پاي چپ دو نما / راديوگرافي زانوي چپ …» —
    two studies. Splitting them is what lets `regions_from_text_complete` notice that
    one of the two was not understood.
    """
    s = _fa_norm(text)
    if not s:
        return []
    out: List[str] = []
    for part in s.replace("\u060c", "/").replace(";", "/").split("/"):
        part = part.strip()
        if part:
            out.append(part)
    return out


def regions_from_text_complete(text: Any) -> bool:
    """True when EVERY study named in the booking resolved to a region.

    A booking naming two studies where only one is understood is a partial read, and a
    partial read must not be trusted to replace a wider set — that is how patient
    54120's heel disappeared while the knee survived.
    """
    segs = _service_segments(text)
    if not segs:
        return False
    return all(detect_regions_from_text(s) for s in segs)


def detect_regions_from_text(text: Any) -> Tuple[str, ...]:
    """Canonical region keys named by free text. Empty tuple when nothing is named.

    Used on the reception booking and, narrowing-only, on the dictation. Matches are
    consumed as they are found so a qualified phrase cannot also satisfy a bare one.
    """
    s = _fa_norm(text)
    if not s:
        return ()
    # Claimed spans rather than string surgery, for two reasons. A more specific
    # pattern must be able to block a shorter one from re-matching the same characters
    # («ستون فقرات گردنی» must not also yield head_neck), AND the position of each
    # match has to survive so the result can be ordered by it.
    #
    # 2026-08-09, patient 52057: the order used to follow _TEXT_REGION_PATTERNS, so a
    # booking reading «MRI مغز ... / MRI سرویکال ...» came back
    # ('spine_cervical', 'brain') purely because the spine block is listed above the
    # head block. Region blocks render in gate order, so the report led with the
    # cervical spine while the physician had dictated the brain first and the title
    # said "brain and cervical spine". Order by WHERE each region is named.
    taken = [False] * len(s)
    hits: List[Tuple[int, str]] = []
    claimed = set()
    for pattern, regions in _TEXT_REGION_PATTERNS:
        start = 0
        while True:
            at = s.find(pattern, start)
            if at < 0:
                break
            if any(taken[at:at + len(pattern)]):
                start = at + 1
                continue
            for i in range(at, at + len(pattern)):
                taken[i] = True
            for r in regions:
                if r in REGION_KEYS and r not in claimed:
                    claimed.add(r)
                    hits.append((at, r))
            # EVERY occurrence is claimed, not just the first. Patient 52057 said
            # «مهره‌های گردنی» twice; stopping at the first left the second one
            # unclaimed, and the bare «گردن» then matched it and added head_neck to a
            # brain-and-cervical-spine study.
            start = at + len(pattern)
    hits.sort(key=lambda h: h[0])
    return tuple(r for _at, r in hits)


#: Free text -> study-type key, same ordered/consumed matching as the regions above.
#: Keys must match the package dictionaries in turbo_xr_modules.XR_SUBTYPE_PACKAGES
#: and turbo_us_modules.US_SUBTYPE_PACKAGES; `subtypes_for()` drops anything the
#: selected modality does not define, so a stray match costs nothing.
#:
#: ⚠️ The Persian spellings are the ones seen in this installation's booking text plus
#: the obvious variants. Reception wording is the ground truth and only he can confirm
#: it — a missed spelling silently falls back to the region-only prompt.
_TEXT_SUBTYPE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    # ── radiography: contrast and fluoroscopic studies
    ("هیستروسالپنگوگرافی", "xr_hsg"),
    ("هیستروسالپینگوگرافی", "xr_hsg"),
    ("هیستروسالپنگوگرام", "xr_hsg"),
    ("اچ اس جی", "xr_hsg"),
    ("hysterosalping", "xr_hsg"),
    ("hsg", "xr_hsg"),
    ("رتروگرید اورتروگرافی", "xr_rug"),
    ("سیستویورتروگرافی", "xr_rug"),
    ("سیستواورتروگرافی", "xr_rug"),
    ("وی سی یو جی", "xr_rug"),
    ("cystourethrograph", "xr_rug"),   # before the shorter form it contains
    ("urethrograph", "xr_rug"),
    ("vcug", "xr_rug"),
    ("پیلوگرافی وریدی", "xr_ivp"),
    ("اوروگرافی", "xr_ivp"),
    ("پیلوگرافی", "xr_ivp"),
    ("آی وی پی", "xr_ivp"),
    ("pyelograph", "xr_ivp"),
    ("urograph", "xr_ivp"),
    ("ivp", "xr_ivp"),
    ("ivu", "xr_ivp"),
    ("بلع باریم", "xr_barium_swallow"),
    ("باریم سوالو", "xr_barium_swallow"),
    ("ازوفاگوگرافی", "xr_barium_swallow"),
    ("barium swallow", "xr_barium_swallow"),
    ("oesophagram", "xr_barium_swallow"),
    ("esophagram", "xr_barium_swallow"),
    ("ترانزیت روده باریک", "xr_sbft"),
    ("انتروکلیزیس", "xr_sbft"),
    ("small bowel follow", "xr_sbft"),
    ("enteroclysis", "xr_sbft"),
    ("sbft", "xr_sbft"),
    ("باریم انما", "xr_barium_enema"),
    ("تنقیه باریم", "xr_barium_enema"),
    ("باریم انیما", "xr_barium_enema"),
    ("barium enema", "xr_barium_enema"),
    ("باریم میل", "xr_barium_meal"),
    ("ترانزیت مری معده", "xr_barium_meal"),
    ("barium meal", "xr_barium_meal"),
    ("upper gi series", "xr_barium_meal"),
    ("ترانزیت کولون", "xr_colon_transit"),
    ("زمان ترانزیت", "xr_colon_transit"),
    ("colon transit", "xr_colon_transit"),
    ("transit time", "xr_colon_transit"),
    ("فیستولوگرافی", "xr_fistulography"),
    ("fistulograph", "xr_fistulography"),
    # ── radiography: specialised projections and surveys
    ("سن استخوانی", "xr_bone_age"),
    ("تعیین سن استخوان", "xr_bone_age"),
    ("bone age", "xr_bone_age"),
    ("سروی اسکلتی", "xr_skeletal_survey"),
    ("بون سروی", "xr_skeletal_survey"),
    ("skeletal survey", "xr_skeletal_survey"),
    ("bone survey", "xr_skeletal_survey"),
    ("اسکنوگرام", "xr_limb_alignment"),
    ("الاینمنت اندام", "xr_limb_alignment"),
    ("long leg", "xr_limb_alignment"),
    ("limb alignment", "xr_limb_alignment"),
    ("scanogram", "xr_limb_alignment"),
    ("استخوان بینی", "xr_nasal_bone"),
    ("nasal bone", "xr_nasal_bone"),
    ("ماستوئید", "xr_mastoid"),
    ("mastoid view", "xr_mastoid"),
    ("فلکشن اکستنشن", "xr_spine_flexion_extension"),
    ("فلکشن و اکستنشن", "xr_spine_flexion_extension"),
    ("flexion and extension", "xr_spine_flexion_extension"),
    ("flexion-extension", "xr_spine_flexion_extension"),
    ("اوبلیک", "xr_spine_oblique"),
    ("oblique view", "xr_spine_oblique"),
    ("توتال اسپاین", "xr_spine_alignment"),
    ("الاینمنت ستون فقرات", "xr_spine_alignment"),
    ("total spine", "xr_spine_alignment"),
    ("spine alignment", "xr_spine_alignment"),
    ("scoliosis", "xr_spine_alignment"),
    ("شانه اختصاصی", "xr_shoulder_special"),
    ("shoulder special", "xr_shoulder_special"),
    # ── obstetric ultrasound
    ("نوکال ترانسلوسنسی", "ob_nt"),
    ("ان تی اسکن", "ob_nt"),
    ("غربالگری سه ماهه اول", "ob_nt"),
    ("nuchal translucency", "ob_nt"),
    ("آنومالی اسکن", "ob_anomaly"),
    ("غربالگری آنومالی", "ob_anomaly"),
    ("سونوگرافی آنومالی", "ob_anomaly"),
    ("anomaly scan", "ob_anomaly"),
    ("بیوفیزیکال پروفایل", "ob_bpp"),
    ("biophysical profile", "ob_bpp"),
    ("bpp", "ob_bpp"),
    ("داپلر بارداری", "ob_doppler"),
    ("داپلر جنین", "ob_doppler"),
    ("obstetric doppler", "ob_doppler"),
    ("حاملگی خارج رحمی", "ob_ectopic"),
    ("بارداری خارج رحمی", "ob_ectopic"),
    ("اکتوپیک", "ob_ectopic"),
    ("ectopic", "ob_ectopic"),
    ("جفت سرراهی", "ob_placenta"),
    ("پلاسنتا اکرتا", "ob_placenta"),
    ("placenta accreta", "ob_placenta"),
    ("placenta previa", "ob_placenta"),
    ("چند قلویی", "ob_multiple"),
    ("دوقلویی", "ob_multiple"),
    ("multiple pregnancy", "ob_multiple"),
    ("رشد جنین", "ob_growth"),
    ("محدودیت رشد", "ob_growth"),
    ("growth scan", "ob_growth"),
    ("سه ماهه اول", "ob_first_trimester"),
    ("تعیین سن بارداری", "ob_first_trimester"),
    ("first trimester", "ob_first_trimester"),
    ("dating scan", "ob_first_trimester"),
)


def detect_subtypes_from_text(text: Any) -> Tuple[str, ...]:
    """Study-type keys named by free text, in the order they are named.

    Same claimed-span matching as `detect_regions_from_text`: a longer phrase blocks a
    shorter one from re-reading the same characters, and the result is ordered by
    position rather than by where the pattern happens to sit in the table.
    """
    s = _fa_norm(text)
    if not s:
        return ()
    taken = [False] * len(s)
    hits: List[Tuple[int, str]] = []
    claimed = set()
    for pattern, key in _TEXT_SUBTYPE_PATTERNS:
        start = 0
        while True:
            at = s.find(pattern, start)
            if at < 0:
                break
            if any(taken[at:at + len(pattern)]):
                start = at + 1
                continue
            for i in range(at, at + len(pattern)):
                taken[i] = True
            if key not in claimed:
                claimed.add(key)
                hits.append((at, key))
            start = at + len(pattern)
    hits.sort(key=lambda h: h[0])
    return tuple(k for _at, k in hits)


def build_auto_from_context(
    *,
    study: Optional[dict] = None,
    patient: Optional[dict] = None,
    series: Optional[Iterable[dict]] = None,
    modality_selected: Optional[str] = None,
    dicom_facts: Optional[dict] = None,
    reception_services: Optional[Iterable[dict]] = None,
) -> dict:
    """Build the ``auto`` layer from local DICOM rows. No network, no LLM.

    ``study``/``patient``/``series`` are plain dict rows as the DB returns them, so
    this stays testable without a database. Every field that lands carries
    provenance; anything absent is simply omitted rather than guessed.
    """
    rec = empty_record()
    prov: Dict[str, dict] = {}
    _facts = dicom_facts or {}

    # ── patient — identifiers only; sex is NEVER inferred (see module docstring)
    if patient:
        pid = (str(patient.get("patient_id") or "")).strip()
        if pid:
            rec["patient"]["patient_id"] = pid
            prov["patient.patient_id"] = {"source": "dicom", "confidence": "high"}
        sex = (str(patient.get("sex") or "")).strip().upper()
        sex_src = "dicom"
        if sex not in ("M", "F", "O"):
            # The patients table is 3% populated here. Fall back to the file.
            sex = (str(_facts.get("sex") or "")).strip().upper()
            sex_src = "dicom_file"
        if sex in ("M", "F", "O"):
            rec["patient"]["sex"] = sex
            prov["patient.sex"] = {"source": sex_src, "confidence": "high"}
        else:
            # explicit, so the UI shows "unknown" rather than an inviting blank
            rec["patient"]["sex"] = "unknown"
            prov["patient.sex"] = {"source": "none", "confidence": "low"}
        age = (str(patient.get("age") or "")).strip()
        age_src = "dicom"
        if not age:
            age = (str(_facts.get("age") or "")).strip()
            age_src = "dicom_file"
        if age:
            rec["patient"]["age"] = age
            prov["patient.age"] = {"source": age_src, "confidence": "high"}

    # ── study/studies
    regions: List[str] = []
    if study:
        entry = {
            "study_uid": (str(study.get("study_uid") or "")).strip() or None,
            "modality": (str(study.get("modality") or "")).strip().upper() or None,
            "body_part": (str(study.get("body_part") or "")).strip().upper() or None,
            "study_description": (str(study.get("study_description") or "")).strip() or None,
            "study_date": (str(study.get("study_date") or "")).strip() or None,
        }
        # The DB holds a description for 19% of studies. Prefer StudyDescription from
        # the file, and fall back to ProtocolName -- "04 Chest Abd Pelvis" describes the
        # study far better than a blank, and provenance records which tag it came from.
        if not entry["study_description"]:
            for key, tag in (("study_description", "StudyDescription"),
                             ("protocol_name", "ProtocolName")):
                val = (str(_facts.get(key) or "")).strip()
                if val:
                    entry["study_description"] = val
                    prov["studies.0.study_description"] = {
                        "source": "dicom_file", "tag": tag, "confidence":
                        "high" if key == "study_description" else "medium"}
                    break
        pn = (str(_facts.get("protocol_name") or "")).strip()
        if pn:
            entry["protocol_name"] = pn
        rec["studies"].append({k: v for k, v in entry.items() if v is not None})
        for r in normalize_region(entry.get("body_part")):
            if r not in regions:
                regions.append(r)

    # ── series body parts widen the region set (a CAP study often tags per series)
    for se in (series or []):
        for r in normalize_region(se.get("body_part_examined")):
            if r not in regions:
                regions.append(r)
    # ...and so do the ones read from the files. series.body_part_examined is 7%
    # populated here, so without this a Chest/Abdomen/Pelvis CT gates as chest alone
    # and the abdominal reporting rules are silently deleted.
    for bp in (_facts.get("body_parts") or []):
        for r in normalize_region(bp):
            if r not in regions:
                regions.append(r)

    # ── reception: what the patient was actually BOOKED for. The service axis
    # the gating design leans on, and the only source that distinguishes a plain CT
    # chest from a CT angiogram of the chest.
    _svc = [s for s in (reception_services or []) if isinstance(s, dict)]
    if _svc:
        rec["reception"]["services"] = _svc
        names = [str(s.get("Service") or "").strip() for s in _svc]
        names = [n for n in names if n]
        if names:
            rec["reception"]["service"] = " / ".join(names)
            prov["reception.service"] = {"source": "reception_api",
                                         "confidence": "high"}

    # ── case
    if modality_selected:
        rec["case"]["modality_selected"] = str(modality_selected).strip().upper()
        prov["case.modality_selected"] = {"source": "user_selection", "confidence": "high"}
    # ── the BOOKING decides the region set (owner decision 2026-08-09:
    # "dictation and service are the most reliable"). DICOM told us patient 52230's
    # MRI was ABDOMEN+PELVIS, so a seven-structure pelvic normal survey was generated
    # for a study booked and dictated as «شکم» — an abdomen MRI. None of it was
    # dictated; all of it asserted that structures had been examined.
    _region_source = "dicom"
    if region_text_enabled():
        _svc_text = rec["reception"].get("service")
        _svc_regions = list(detect_regions_from_text(_svc_text))
        _svc_complete = regions_from_text_complete(_svc_text)
        if _svc_regions and not _svc_complete:
            # Half-read booking: keep what both sources know rather than letting the
            # understood half delete the rest. 54120 — heel + knee, heel unreadable.
            logger.warning("[EchoMind-meta] booking only partly understood (%s from "
                           "%d segment(s)); keeping the union with DICOM %s",
                           _svc_regions, len(_service_segments(_svc_text)), regions)
            regions = regions + [r for r in _svc_regions if r not in regions]
            _region_source = "dicom+service_partial"
        elif _svc_regions:
            _overlap = [r for r in _svc_regions if r in regions]
            if _overlap or not regions:
                if regions and set(_svc_regions) != set(regions):
                    logger.info("[EchoMind-meta] regions %s -> %s (reception booking "
                                "outranks DICOM)", regions, _svc_regions)
                regions = _svc_regions
                _region_source = "service_text"
            else:
                # No overlap at all is a data problem, not a refinement: the booking
                # and the scanner describe different studies. Keep both rather than
                # pick a winner, and make it visible.
                logger.warning("[EchoMind-meta] booking regions %s share nothing with "
                               "DICOM %s — keeping the union",
                               _svc_regions, regions)
                regions = regions + [r for r in _svc_regions if r not in regions]
                _region_source = "dicom+service_conflict"

    if regions:
        rec["case"]["regions"] = regions
        rec["case"]["multi_region"] = len(regions) > 1
        prov["case.regions"] = {
            "source": _region_source,
            "confidence": "high" if _region_source == "service_text" else "medium"}

    # ── study type (2026-08-09). `case.subtype` has been read by the gate since the
    # study-type libraries were written and populated by nothing, so all 27 packages
    # were unreachable. Patient 53626's hysterosalpingogram was reported with the plain
    # abdominal radiograph normal template because `xr_hsg` never reached the prompt.
    if region_text_enabled():
        _subs = list(detect_subtypes_from_text(rec["reception"].get("service")))
        if not _subs:
            _subs = list(detect_subtypes_from_text(
                (rec.get("studies") or [{}])[0].get("study_description")))
        if _subs:
            rec["case"]["subtype"] = _subs
            prov["case.subtype"] = {"source": "service_text", "confidence": "medium"}
            logger.info("[EchoMind-meta] study type(s) detected: %s", _subs)

    # ── contrast (2026-08-09). `case.contrast` has been read by the Turbo gate since
    # it was written, and by RULES — NORMAL FINDINGS step 1 ("take the examination from
    # STUDY CONTEXT: modality, regions, contrast") — but NOTHING had ever populated it,
    # so the row never rendered and the rule pointed at a field that did not exist.
    # Booking text is checked first because it is the field a human actually filled in.
    _contrast, _csrc = detect_contrast(
        rec["reception"].get("service"),
        (rec.get("studies") or [{}])[0].get("study_description"),
        _facts.get("protocol_name"),
        agent=_facts.get("contrast_agent"),
    )
    if _contrast:
        rec["case"]["contrast"] = _contrast
        prov["case.contrast"] = {
            "source": _csrc,
            "confidence": "high" if _csrc == "dicom" else "medium",
        }

    rec["provenance"] = prov
    return rec


# ═══════════════════════════════════════════════════════════════════════════
# Storage — thin. Owns its own table; nothing else in the schema changes.
# ═══════════════════════════════════════════════════════════════════════════

def _conn():
    from PacsClient.utils.database import get_db_connection
    return get_db_connection()


def ensure_schema() -> None:
    """Idempotent. Safe to call on every access."""
    with _conn() as conn:
        conn.cursor().execute(
            """
            CREATE TABLE IF NOT EXISTS ai_session_meta(
                sid        TEXT PRIMARY KEY,
                auto_json  TEXT,
                user_json  TEXT,
                updated_at TEXT,
                schema_ver INTEGER
            )
            """
        )
        conn.commit()


def _loads(raw: Any) -> dict:
    if not raw:
        return {}
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else {}
    except Exception:
        logger.warning("[EchoMind-meta] unreadable metadata JSON — treating as empty")
        return {}


def load_layers(sid: str) -> Tuple[dict, dict]:
    """(auto, user) for a chat. Missing row -> ({}, {})."""
    sid = (sid or "").strip()
    if not sid:
        return {}, {}
    ensure_schema()
    with _conn() as conn:
        row = conn.cursor().execute(
            "SELECT auto_json, user_json FROM ai_session_meta WHERE sid = ?", (sid,)
        ).fetchone()
    if not row:
        return {}, {}
    return _loads(row[0]), _loads(row[1])


def load(sid: str) -> dict:
    """The EFFECTIVE record for a chat (auto with the user's edits applied)."""
    auto, user = load_layers(sid)
    return merge_layers(auto, user)


def _write(sid: str, *, auto: Optional[dict] = None, user: Optional[dict] = None) -> None:
    ensure_schema()
    now = datetime.now().isoformat(timespec="seconds")
    cur_auto, cur_user = load_layers(sid)
    new_auto = cur_auto if auto is None else auto
    new_user = cur_user if user is None else user
    with _conn() as conn:
        conn.cursor().execute(
            """
            INSERT INTO ai_session_meta(sid, auto_json, user_json, updated_at, schema_ver)
            VALUES(?, ?, ?, ?, ?)
            ON CONFLICT(sid) DO UPDATE SET
                auto_json  = excluded.auto_json,
                user_json  = excluded.user_json,
                updated_at = excluded.updated_at,
                schema_ver = excluded.schema_ver
            """,
            (sid, json.dumps(new_auto, ensure_ascii=False),
             json.dumps(new_user, ensure_ascii=False), now, SCHEMA_VERSION),
        )
        conn.commit()


def save_auto(sid: str, auto: dict) -> None:
    """Replace the auto layer. The user layer is untouched — that is the point."""
    sid = (sid or "").strip()
    if not sid:
        return
    _write(sid, auto=auto or {})


def set_user_field(sid: str, path: str, value: Any) -> None:
    """Record a physician edit at a dotted path (e.g. ``case.regions``)."""
    sid = (sid or "").strip()
    if not sid or not path:
        return
    _, user = load_layers(sid)
    node = user
    parts = path.split(".")
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            node[p] = nxt
        node = nxt
    node[parts[-1]] = value
    _write(sid, user=user)


def clear_user_field(sid: str, path: str) -> None:
    """Reset one field back to whatever detection says."""
    sid = (sid or "").strip()
    if not sid or not path:
        return
    _, user = load_layers(sid)
    node = user
    parts = path.split(".")
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            return
        node = nxt
    node.pop(parts[-1], None)
    _write(sid, user=user)


def clear_user_layer(sid: str) -> None:
    """Drop every physician edit for a chat; detection is untouched.

    The point of keeping two layers apart: "undo my corrections" must not
    also erase what was detected, and re-detection must not erase corrections.
    """
    sid = (sid or "").strip()
    if not sid:
        return
    _write(sid, user={})


def delete(sid: str) -> None:
    sid = (sid or "").strip()
    if not sid:
        return
    ensure_schema()
    with _conn() as conn:
        conn.cursor().execute("DELETE FROM ai_session_meta WHERE sid = ?", (sid,))
        conn.commit()


def populate_for_chat(
    sid: str,
    *,
    study_uid: Optional[str] = None,
    modality_selected: Optional[str] = None,
) -> dict:
    """Build and store the auto layer for a chat from local DICOM rows.

    Best-effort by design: any lookup failure yields a smaller record, never an
    exception. Called at chat creation, where it must never be able to stop a chat
    from opening.
    """
    sid = (sid or "").strip()
    if not sid:
        return {}
    study = patient = None
    series: List[dict] = []
    try:
        from PacsClient.utils import db_manager as db
        if study_uid:
            study = db.get_study_by_study_uid(study_uid) or None
            if study:
                try:
                    series = list(db.get_series_by_study_uid(study_uid) or [])
                except Exception:
                    series = []
                pk = study.get("patient_fk")
                if pk:
                    patient = db.get_patient_by_patient_pk(pk) or None
    except Exception as exc:
        logger.debug("[EchoMind-meta] DICOM lookup unavailable: %s", exc)

    facts = {}
    try:
        facts = read_dicom_facts((study or {}).get("study_path"))
    except Exception as exc:
        logger.debug("[EchoMind-meta] DICOM header read skipped: %s", exc)

    services: List[dict] = []
    try:
        pid = (str((patient or {}).get("patient_id") or "")).strip()
        if pid:
            from PacsClient.utils import ai_get_reception_services
            services = list(ai_get_reception_services(pid) or [])
    except Exception as exc:
        logger.debug("[EchoMind-meta] reception services unavailable: %s", exc)

    auto = build_auto_from_context(
        study=study, patient=patient, series=series,
        modality_selected=modality_selected, dicom_facts=facts,
        reception_services=services,
    )
    try:
        save_auto(sid, auto)
    except Exception as exc:
        logger.warning("[EchoMind-meta] could not persist metadata for %s: %s", sid, exc)
    return auto


# ═══════════════════════════════════════════════════════════════════════════
# Physician attribution
# ═══════════════════════════════════════════════════════════════════════════

def resolve_physician_id_from_identities(identities: Iterable[dict]) -> Optional[str]:
    """The physician to attribute work to, or None when it is ambiguous.

    DELIBERATELY CONSERVATIVE. For an audit trail, a WRONG attribution is worse
    than none: it would credit one radiologist with another's report. AI-PACS has
    no per-report login concept — ``external_identities`` records linked accounts,
    not an authenticated session — so this resolves a name only when every linked
    identity belongs to the same ``aipacs_user``. On a genuinely shared
    workstation it returns None, and the row is stored unattributed.

    Pure: takes rows, touches no database, so the rule is directly testable.
    """
    users = {
        (str(r.get("aipacs_user") or "")).strip()
        for r in (identities or [])
        if (str(r.get("aipacs_user") or "")).strip()
    }
    if len(users) == 1:
        return users.pop()
    return None


def resolve_physician_id() -> Optional[str]:
    """Best-effort physician id for the current workstation. None when unknown."""
    try:
        from PacsClient.utils.database import get_db_connection
        with get_db_connection() as conn:
            rows = conn.cursor().execute(
                "SELECT aipacs_user FROM external_identities"
            ).fetchall()
        return resolve_physician_id_from_identities(
            [{"aipacs_user": r[0]} for r in (rows or [])]
        )
    except Exception as exc:
        logger.debug("[EchoMind-meta] physician id unresolved: %s", exc)
        return None
