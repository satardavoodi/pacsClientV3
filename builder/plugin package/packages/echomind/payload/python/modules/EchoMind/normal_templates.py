"""EchoMind — the physician's personal library of NORMAL-REPORT TEMPLATES.

WHAT THIS IS FOR
----------------
A radiologist keeps their own normal-report templates: for a normal knee MRI,
a normal abdominal CT, a normal thyroid ultrasound. When reporting they dictate
ONLY the pathology; the selected template supplies the structure and every
normal statement, and the model merges the two.

Before 2026-08-01 the templates lived in a Python list on one widget. They were
re-uploaded from a JSON file on **every launch**, could not be searched, renamed
or deleted, and carried no metadata to filter by. This module is the persistent
library behind that tab.

THE TWO RULES THIS MODULE EXISTS TO KEEP
----------------------------------------
1. **It is PURE stdlib — no Qt, no requests, no app imports.** That is what makes
   the parsing, the metadata inference, the search and the prompt rendering
   unit-testable offscreen, and it is why the UI can be swapped without touching
   any of it. Keep it that way. (Same reasoning as ``series_ref.py`` and
   ``patient_study_set.py``.)
2. **The physician's existing files must keep working, untouched.** The shipped
   format is a list of ``{"Name": ..., "Html": ...}``. Every extended field is
   OPTIONAL. A file authored two years ago imports with no warning and no edit.

THE FILE FORMAT
---------------
Legacy (still fully supported)::

    [ {"Name": "MRI Knee", "Html": "<p>Both menisci ...</p>"}, ... ]

Extended — every key beyond ``Name``/``Html`` is optional::

    [
      {
        "Name":        "MRI Knee — Right",
        "Number":      "12",                  # the physician's own numbering
        "Modality":    "MRI",
        "BodyRegion":  "Knee",
        "ExamType":    "Non-contrast",
        "Html":        "<p>Both menisci ...</p>",
        "Sections":    [ {"Title": "Menisci", "Normal": "Both menisci ..."} ],
        "Impression":  "Normal MRI of the right knee."
      }
    ]

A wrapper object is also accepted (``{"templates": [...]}``, ``{"items": [...]}``,
``{"data": [...]}``, ``{"reports": [...]}``) because real exports use all four.

WHAT REACHES THE MODEL
----------------------
``template_body_text()``. When the record has ``Sections`` they are rendered with
their titles, so the model receives the physician's structure explicitly instead
of one undifferentiated block; otherwise the body is converted to clean text.
The caller fences it (``===== NORMAL_TEMPLATE =====``) — see
``openai_reporter.build_report_system_prompt``.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

# ── the modality vocabulary the modality button actually sends ───────────────
# Filters have to line up with it or "show me my MRI templates" quietly misses
# the ones the physician labelled "mri" or "M.R.I".
CANONICAL_MODALITIES: Tuple[str, ...] = (
    "CT", "MRI", "SONOGRAPHY", "RADIOLOGY", "MAMOGRAPHY",
)

_MODALITY_ALIASES: Dict[str, str] = {
    "ct": "CT", "cat": "CT", "computed tomography": "CT", "ct scan": "CT",
    "cta": "CT", "ctv": "CT", "hrct": "CT", "cbct": "CT",
    "mr": "MRI", "mri": "MRI", "m.r.i": "MRI", "magnetic resonance": "MRI",
    "mra": "MRI", "mrv": "MRI", "mrcp": "MRI",
    "us": "SONOGRAPHY", "u/s": "SONOGRAPHY", "sono": "SONOGRAPHY",
    "sonography": "SONOGRAPHY", "ultrasound": "SONOGRAPHY",
    "ultrasonography": "SONOGRAPHY", "doppler": "SONOGRAPHY",
    "echo": "SONOGRAPHY",
    "xr": "RADIOLOGY", "x-ray": "RADIOLOGY", "xray": "RADIOLOGY",
    "radiograph": "RADIOLOGY", "radiography": "RADIOLOGY",
    "radiology": "RADIOLOGY", "dr": "RADIOLOGY", "cr": "RADIOLOGY",
    "dexa": "RADIOLOGY", "dxa": "RADIOLOGY", "bone age": "RADIOLOGY",
    "barium": "RADIOLOGY", "ivp": "RADIOLOGY", "kub": "RADIOLOGY",
    "mammo": "MAMOGRAPHY", "mammogram": "MAMOGRAPHY",
    "mammography": "MAMOGRAPHY", "mamography": "MAMOGRAPHY",
    "mamogram": "MAMOGRAPHY", "tomosynthesis": "MAMOGRAPHY",
}

# Body regions we can recognise in a template NAME. Deliberately conservative:
# a wrong guess in a filter hides a template the physician knows they uploaded,
# which is worse than no guess at all. Order matters — longer phrases first.
_BODY_REGIONS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("Brain",           ("brain", "head", "cranial", "skull", "sella", "pituitary")),
    ("Cervical Spine",  ("cervical spine", "c-spine", "cspine", "neck spine")),
    ("Thoracic Spine",  ("thoracic spine", "t-spine", "tspine", "dorsal spine")),
    ("Lumbar Spine",    ("lumbar spine", "l-spine", "lspine", "lumbosacral")),
    ("Spine",           ("spine", "vertebral")),
    ("Neck",            ("neck", "thyroid", "parotid", "salivary")),
    ("Chest",           ("chest", "thorax", "lung", "pulmonary", "cxr")),
    ("Cardiac",         ("cardiac", "heart", "coronary")),
    ("Abdomen",         ("abdomen", "abdominal", "liver", "hepatic", "pancreas",
                         "spleen", "biliary", "gallbladder")),
    ("Pelvis",          ("pelvis", "pelvic", "uterus", "ovary", "ovarian",
                         "prostate", "bladder")),
    ("Obstetric",       ("obstetric", "pregnancy", "fetal", "foetal", "ob ")),
    ("Breast",          ("breast", "mammo")),
    ("Renal",           ("renal", "kidney", "urinary", "kub")),
    ("Knee",            ("knee", "meniscus", "menisci")),
    ("Shoulder",        ("shoulder", "rotator cuff")),
    ("Hip",             ("hip", "femoral head")),
    ("Ankle",           ("ankle", "achilles")),
    ("Wrist",           ("wrist", "carpal")),
    ("Elbow",           ("elbow",)),
    ("Foot",            ("foot", "forefoot", "midfoot")),
    ("Hand",            ("hand", "finger")),
    ("Sinuses",         ("sinus", "pns", "paranasal")),
    ("Orbit",           ("orbit", "orbital")),
    ("Temporal Bone",   ("temporal bone", "iac", "mastoid")),
    ("Extremity",       ("extremity", "limb", "musculoskeletal", "msk")),
)

_SCHEMA_VERSION = 1
_LOCK = threading.Lock()


# ─────────────────────────────────────────────────────────────────────────────
#  HTML -> text (stdlib only, on purpose)
# ─────────────────────────────────────────────────────────────────────────────
def html_to_text(value: Any) -> str:
    """Convert a template body to clean plain text.

    Deliberately a small local implementation rather than a call into
    ``ai_chat_helpers.extract_plain_text_from_html``: that module imports Qt at
    module level, and importing Qt here would cost this module the one property
    that makes it worth having. Block-level tags become newlines so the
    physician's line structure survives.
    """
    s = "" if value is None else str(value)
    if not s.strip():
        return ""
    if "<" not in s:
        return s.strip()

    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "\n", s)
    s = re.sub(r"(?i)<br\s*/?>", "\n", s)
    s = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article)\s*>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "\n• ", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)

    # entities — the handful that actually show up in clinical templates
    for ent, ch in (
        ("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
        ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'"), ("&mdash;", "—"),
        ("&ndash;", "–"), ("&hellip;", "…"), ("&times;", "×"), ("&deg;", "°"),
    ):
        s = s.replace(ent, ch)
    s = re.sub(r"&#(\d+);", lambda m: _safe_chr(m.group(1)), s)
    s = s.replace("\xa0", " ")

    # A bullet does not need a blank line above it: `</p>` already emitted one
    # newline and `<li>` adds its own, which would render as a gap the
    # physician never put in their template.
    s = re.sub(r"\n\s*\n(\s*• )", r"\n\1", s)

    lines = [ln.rstrip() for ln in s.splitlines()]
    out: List[str] = []
    for ln in lines:
        if ln.strip():
            out.append(ln.strip())
        elif out and out[-1] != "":
            out.append("")
    return "\n".join(out).strip()


def _safe_chr(num: str) -> str:
    try:
        return chr(int(num))
    except Exception:
        return ""


# ─────────────────────────────────────────────────────────────────────────────
#  Metadata inference (only ever fills a field the file left EMPTY)
# ─────────────────────────────────────────────────────────────────────────────
def infer_modality(text: str) -> str:
    """Canonical modality guessed from a template name. '' when unsure."""
    low = f" {str(text or '').lower()} "
    best = ""
    best_len = 0
    for alias, canon in _MODALITY_ALIASES.items():
        # word-ish boundary so "us" doesn't match inside "sinus"
        if re.search(r"(?<![a-z])" + re.escape(alias) + r"(?![a-z])", low):
            if len(alias) > best_len:
                best, best_len = canon, len(alias)
    return best


def infer_body_region(text: str) -> str:
    low = str(text or "").lower()
    for region, needles in _BODY_REGIONS:
        for n in needles:
            if n in low:
                return region
    return ""


def extract_number(text: str) -> str:
    """A leading/trailing number the physician uses as their own identifier.

    Matches '12 - MRI Knee', 'MRI Knee #12', 'MRI Knee (12)', 'T-014 Chest'.
    A number embedded in the middle of a phrase is NOT treated as an id.
    """
    s = str(text or "").strip()
    if not s:
        return ""
    for pat in (
        r"^\s*#?\s*([0-9]{1,6})\s*[-–—:.)\]]\s+",     # "12 - name" / "12. name"
        r"[#]\s*([0-9]{1,6})\s*$",                     # "name #12"
        r"[(\[]\s*([0-9]{1,6})\s*[)\]]\s*$",           # "name (12)"
        r"^\s*([A-Za-z]{1,3}-[0-9]{1,6})\b",           # "T-014 name"
        r"\s([0-9]{1,6})\s*$",                          # "name 12"
    ):
        m = re.search(pat, s)
        if m:
            return m.group(1)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
#  Parsing / normalisation
# ─────────────────────────────────────────────────────────────────────────────
def _first(raw: Dict[str, Any], *keys: str) -> str:
    """Case-insensitive, alias-tolerant field read."""
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}
    for k in keys:
        v = lowered.get(k.strip().lower())
        if isinstance(v, str) and v.strip():
            return v.strip()
        if isinstance(v, (int, float)):
            return str(v)
    return ""


def _parse_sections(raw: Dict[str, Any]) -> List[Dict[str, str]]:
    lowered = {str(k).strip().lower(): v for k, v in raw.items()}
    val = lowered.get("sections")
    out: List[Dict[str, str]] = []
    if isinstance(val, list):
        for s in val:
            if isinstance(s, dict):
                title = _first(s, "title", "name", "section", "heading")
                normal = _first(s, "normal", "text", "html", "content", "findings")
                if title or normal:
                    out.append({"title": title, "normal": html_to_text(normal)})
            elif isinstance(s, str) and s.strip():
                out.append({"title": "", "normal": html_to_text(s)})
    elif isinstance(val, dict):
        for title, normal in val.items():
            out.append({"title": str(title), "normal": html_to_text(normal)})
    return out


def normalize_record(
    raw: Any,
    *,
    index: int = 0,
    source_file: str = "",
    now: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """One raw item -> (record, problem). Exactly one of the two is falsy.

    A problem is a HUMAN SENTENCE, not a code: it is shown to the physician in
    the import report. Silently dropping a malformed entry — which is what the
    old loader did — meant a file of 40 templates could import 12 with no hint
    that 28 were missing.
    """
    where = f"entry #{index + 1}"
    if not isinstance(raw, dict):
        return None, f"{where}: expected an object, found {type(raw).__name__}."

    name = _first(raw, "Name", "title", "template_name", "templateName")
    body_raw = _first(raw, "Html", "body", "text", "content", "template")
    sections = _parse_sections(raw)

    if not name:
        return None, f"{where}: no \"Name\" — a template must be nameable."
    if not body_raw and not sections:
        return None, f"{where} (\"{name}\"): no \"Html\" body and no \"Sections\" — nothing to use."

    body_text = html_to_text(body_raw)
    if not body_text and not sections:
        return None, f"{where} (\"{name}\"): the body contains no text once markup is removed."

    declared_modality = _first(raw, "Modality", "modality")
    declared_region = _first(raw, "BodyRegion", "body_region", "region", "bodyPart", "body_part")
    number = _first(raw, "Number", "number", "id_number", "code", "index")

    modality = canonical_modality(declared_modality)
    modality_inferred = False
    if not modality:
        modality = infer_modality(name)
        modality_inferred = bool(modality)

    body_region = declared_region
    region_inferred = False
    if not body_region:
        body_region = infer_body_region(name)
        region_inferred = bool(body_region)

    if not number:
        number = extract_number(name)

    rec = {
        "id": _first(raw, "id", "uid") or uuid.uuid4().hex,
        "name": name,
        "number": number,
        "modality": modality,
        "modality_inferred": modality_inferred,
        "body_region": body_region,
        "body_region_inferred": region_inferred,
        "exam_type": _first(raw, "ExamType", "exam_type", "exam", "protocol"),
        "html": body_raw,
        "text": body_text,
        "sections": sections,
        "impression": html_to_text(_first(raw, "Impression", "impression")),
        "notes": _first(raw, "Notes", "notes", "comment"),
        "source_file": os.path.basename(source_file) if source_file else "",
        "imported_at": now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return rec, ""


def parse_templates(text: str, *, source_file: str = "") -> Tuple[List[Dict[str, Any]], List[str]]:
    """Parse an uploaded file. Returns (records, problems).

    ``problems`` is never silently discarded by callers — the import dialog
    shows it. An empty ``records`` with a non-empty ``problems`` is the "we
    could not use this file, and here is exactly why" case.
    """
    raw_text = "" if text is None else str(text)
    if not raw_text.strip():
        return [], ["The file is empty."]

    payload: Any = None
    try:
        payload = json.loads(raw_text)
    except Exception as exc:
        # Legacy tolerance: some shipped template files use Python-literal
        # single quotes. `ast.literal_eval` accepts LITERALS ONLY (no calls, no
        # names), so this cannot execute anything from the file.
        try:
            import ast as _ast
            payload = _ast.literal_eval(raw_text)
        except Exception:
            return [], [f"Not valid JSON: {exc}"]

    if isinstance(payload, dict):
        for key in ("templates", "items", "data", "reports"):
            if isinstance(payload.get(key), list):
                payload = payload[key]
                break
        else:
            # a single template object is a reasonable thing to hand us
            payload = [payload]

    if not isinstance(payload, list):
        return [], [
            "Expected a list of templates (or an object with a "
            "\"templates\"/\"items\"/\"data\"/\"reports\" list); "
            f"found {type(payload).__name__}."
        ]

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    records: List[Dict[str, Any]] = []
    problems: List[str] = []
    for i, item in enumerate(payload):
        rec, problem = normalize_record(item, index=i, source_file=source_file, now=now)
        if rec:
            records.append(rec)
        elif problem:
            problems.append(problem)
    if not records and not problems:
        problems.append("The file contained no templates.")
    return records, problems


def canonical_modality(value: str) -> str:
    """Map any spelling of a modality onto the vocabulary the UI sends. '' if unknown."""
    s = str(value or "").strip()
    if not s:
        return ""
    up = s.upper()
    if up in CANONICAL_MODALITIES:
        return up
    return _MODALITY_ALIASES.get(s.lower(), "")


# ─────────────────────────────────────────────────────────────────────────────
#  Search
# ─────────────────────────────────────────────────────────────────────────────
def search_templates(
    records: List[Dict[str, Any]],
    query: str = "",
    *,
    modality: str = "",
    body_region: str = "",
) -> List[Dict[str, Any]]:
    """Filter a library. Pure; the UI calls it on every keystroke.

    The query matches the NAME, the NUMBER, the modality, the body region and
    the exam type — a physician who numbers their templates types "12" and a
    physician who does not types "knee", and both work.
    """
    q = str(query or "").strip().lower()
    mod = canonical_modality(modality) or str(modality or "").strip().upper()
    reg = str(body_region or "").strip().lower()

    terms = [t for t in re.split(r"\s+", q) if t]
    out = []
    for r in records:
        if mod and str(r.get("modality") or "").upper() != mod:
            continue
        if reg and str(r.get("body_region") or "").lower() != reg:
            continue
        if terms:
            hay = " ".join(str(r.get(k) or "") for k in
                           ("name", "number", "modality", "body_region", "exam_type", "notes")).lower()
            if not all(t in hay for t in terms):
                continue
        out.append(r)
    return out


def available_modalities(records: List[Dict[str, Any]]) -> List[str]:
    seen = {str(r.get("modality") or "").upper() for r in records}
    seen.discard("")
    return [m for m in CANONICAL_MODALITIES if m in seen] + sorted(seen - set(CANONICAL_MODALITIES))


def available_body_regions(records: List[Dict[str, Any]]) -> List[str]:
    seen = {str(r.get("body_region") or "").strip() for r in records}
    seen.discard("")
    return sorted(seen)


def display_label(record: Dict[str, Any]) -> str:
    """One line for a picker: '#12 · MRI Knee — Right · MRI · Knee'."""
    bits = []
    num = str(record.get("number") or "").strip()
    if num:
        bits.append(f"#{num}")
    bits.append(str(record.get("name") or "").strip() or "(unnamed)")
    tail = [str(record.get(k) or "").strip() for k in ("modality", "body_region")]
    tail = [t for t in tail if t]
    return " · ".join(bits + tail)


# ─────────────────────────────────────────────────────────────────────────────
#  What the model receives
# ─────────────────────────────────────────────────────────────────────────────
def template_body_text(record: Dict[str, Any]) -> str:
    """The template as the model should see it.

    With ``Sections`` the physician's structure is rendered EXPLICITLY (title,
    then its normal text) so the model does not have to infer section
    boundaries from a wall of prose. Without them the body is returned as clean
    text — unchanged from what the legacy path sent, so an existing template
    produces an identical prompt.

    NOTE: metadata (modality / body region / number) is deliberately NOT
    prepended. The modality is already sent to the model as its own argument,
    and the region is evident from the template. This text is the physician's
    template and nothing else.
    """
    if not isinstance(record, dict):
        return ""
    sections = record.get("sections") or []
    if sections:
        chunks: List[str] = []
        for s in sections:
            title = str(s.get("title") or "").strip()
            normal = str(s.get("normal") or "").strip()
            if title and normal:
                chunks.append(f"{title}:\n{normal}")
            elif title:
                chunks.append(f"{title}:")
            elif normal:
                chunks.append(normal)
        body = "\n\n".join(chunks).strip()
        impression = str(record.get("impression") or "").strip()
        if impression:
            body = f"{body}\n\nImpression:\n{impression}".strip()
        return body

    body = str(record.get("text") or "").strip() or html_to_text(record.get("html"))
    impression = str(record.get("impression") or "").strip()
    if impression:
        body = f"{body}\n\nImpression:\n{impression}".strip()
    return body


# ─────────────────────────────────────────────────────────────────────────────
#  Persistence — the whole point of the rewrite
# ─────────────────────────────────────────────────────────────────────────────
def library_dir() -> str:
    from PacsClient.utils.data_paths import ECHOMIND_DIR
    return os.path.join(str(ECHOMIND_DIR), "normal_templates")


def library_path() -> str:
    return os.path.join(library_dir(), "library.json")


def _atomic_write_json(path: str, data: Any) -> None:
    """Write-then-replace, per-writer temp name.

    `shutil.move` is NOT atomic (it falls back to copy2+unlink) and Windows
    `os.rename` raises when the destination exists — the project has been bitten
    by both. `os.replace` after an fsync is the contract used everywhere else.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.%d.part" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_library() -> List[Dict[str, Any]]:
    """The physician's saved templates. Never raises — an unreadable library
    must not take down the composer; it degrades to 'no templates yet'."""
    try:
        path = library_path()
        if not os.path.exists(path):
            return []
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("templates") or []
    if not isinstance(data, list):
        return []
    out = []
    for i, item in enumerate(data):
        rec, _problem = normalize_record(item, index=i)
        if rec:
            # preserve the stored id / import stamp rather than re-minting them
            if isinstance(item, dict):
                for k in ("id", "imported_at", "source_file"):
                    if item.get(k):
                        rec[k] = item[k]
            out.append(rec)
    return out


def save_library(records: List[Dict[str, Any]]) -> bool:
    try:
        with _LOCK:
            _atomic_write_json(library_path(), {
                "schema_version": _SCHEMA_VERSION,
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "templates": list(records or []),
            })
        return True
    except Exception:
        return False


def _body_fingerprint(record: Dict[str, Any]) -> str:
    return re.sub(r"\s+", " ", template_body_text(record)).strip().lower()


def merge_into_library(
    existing: List[Dict[str, Any]],
    incoming: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[str], int]:
    """Add imported templates to the library. Returns (merged, notes, added).

    * identical name AND identical body  -> skipped (re-importing the same file
      is a no-op, which is what a physician expects)
    * same name, DIFFERENT body          -> kept under "name (2)" rather than
      overwriting; losing a template to a name collision is not acceptable
    """
    merged = list(existing or [])
    by_name = {str(r.get("name") or "").strip().lower(): r for r in merged}
    fingerprints = {_body_fingerprint(r) for r in merged}
    notes: List[str] = []
    added = 0

    for rec in incoming or []:
        name = str(rec.get("name") or "").strip()
        key = name.lower()
        fp = _body_fingerprint(rec)
        if key in by_name and fp in fingerprints:
            notes.append(f"\"{name}\" is already in your library — skipped.")
            continue
        if key in by_name:
            n = 2
            while f"{key} ({n})" in by_name:
                n += 1
            rec = dict(rec)
            rec["name"] = f"{name} ({n})"
            notes.append(
                f"\"{name}\" already exists with different content — "
                f"imported as \"{rec['name']}\"."
            )
        merged.append(rec)
        by_name[str(rec.get("name") or "").strip().lower()] = rec
        fingerprints.add(fp)
        added += 1
    return merged, notes, added


def find_by_id(records: List[Dict[str, Any]], template_id: str) -> Optional[Dict[str, Any]]:
    tid = str(template_id or "")
    if not tid:
        return None
    for r in records or []:
        if str(r.get("id") or "") == tid:
            return r
    return None


def update_record(
    records: List[Dict[str, Any]],
    template_id: str,
    **fields: Any,
) -> List[Dict[str, Any]]:
    """Rename / re-tag one template. Unknown keys are ignored on purpose."""
    allowed = {"name", "number", "modality", "body_region", "exam_type", "notes"}
    out = []
    for r in records or []:
        if str(r.get("id") or "") == str(template_id):
            r = dict(r)
            for k, v in fields.items():
                if k in allowed:
                    r[k] = str(v or "").strip()
                    if k == "modality":
                        r["modality"] = canonical_modality(r["modality"]) or r["modality"].upper()
                        r["modality_inferred"] = False
                    if k == "body_region":
                        r["body_region_inferred"] = False
        out.append(r)
    return out


def delete_record(records: List[Dict[str, Any]], template_id: str) -> List[Dict[str, Any]]:
    return [r for r in (records or []) if str(r.get("id") or "") != str(template_id)]
