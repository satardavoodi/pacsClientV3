"""
Education Course Importer
=========================

A reusable migration + enrichment engine that imports external course packages
into the AI-PACS Education module (``courses`` / ``slides`` / ``slide_content``).

It supersedes the basic :func:`course_database.import_course_folder_to_my_courses`
helper with a richer, loss-less pipeline while reusing the same public database
helpers (it never alters the schema or the existing import functions).

Design goals
------------
* **Parse metadata.** Read course-level ``course.json`` and per-item ``item.json``
  (``schemaVersion`` "1.1", produced by the PooyanPacs
  ``generate-elearning-metadata.ps1`` tool) and fall back gracefully to a pure
  folder scan when the JSON is missing or empty.
* **Detect + register resources by type** (DICOM study / image / PDF / video /
  audio / presentation / document / text / encrypted-original / archive) so the
  existing educational viewers pick them up unchanged.
* **Preserve everything.** Every source byte is copied into the per-course asset
  store.  Nothing is ever deleted.  Files that cannot be rendered (encrypted
  ``*.IPcryp`` originals, archives, office documents) are still copied and kept
  in an archival record so no educational material is lost.
* **Normalise for compatibility.** DICOM is re-grouped into the
  ``<study>/<series_number>/*.dcm`` layout the educational viewer requires
  (``educational_patient_viewer_widget._resolve_dicom_folder``).  This is a
  re-organisation only -- every instance file is preserved.
* **Enrich + normalise pedagogically.** Factual metadata is derived from the
  DICOM headers themselves (Modality / StudyDescription / SeriesDescription /
  BodyPartExamined); AI-drafted descriptions / learning objectives / keywords are
  added and *clearly flagged* as ``AI-generated draft`` so a human can review
  them.  Items are re-ordered into a more pedagogical sequence (overview / normal
  before complex cases).
* **Observability.** A migration log and a machine- + human-readable validation
  report are written for every run.

Transport-agnostic
------------------
A local folder, a downloaded cloud package, a Google-Drive sync folder or a
consultation education bundle all expose the same "course folder that contains
item folders" shape, so the same importer serves all of them
(:meth:`EducationCourseImporter.import_course_package` /
:meth:`EducationCourseImporter.import_learn_root`).
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# Reuse the existing public DB helpers -- additive, no schema changes.
from modules.education.course_database import (
    insert_course,
    insert_slide,
    insert_slide_content,
    update_course,
    update_slide,
    get_all_courses,
    get_slides_for_course,
    _ensure_course_storage,  # internal but stable; returns course_{pk} root
)

logger = logging.getLogger("education.course_importer")

# ---------------------------------------------------------------------------
# Resource type tables
# ---------------------------------------------------------------------------
DICOM_EXTS = {".dcm", ".dic", ".ima"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
PDF_EXTS = {".pdf"}
VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".webm", ".m4v"}
AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".aac", ".m4a", ".flac"}
PRESENTATION_EXTS = {".ppt", ".pptx", ".odp", ".key"}
DOC_EXTS = {".doc", ".docx", ".odt", ".rtf"}
TEXT_EXTS = {".txt", ".md", ".csv"}
ARCHIVE_EXTS = {".zip", ".rar", ".7z", ".tar", ".gz", ".tgz"}
ENCRYPTED_EXTS = {".ipcryp", ".ipdcom", ".ipe"}
# Sidecar metadata files that are not themselves educational "resources".
METADATA_NAMES = {"course.json", "item.json", "course-summary.txt",
                  "configcourseitem.ipe", "configlearn.ipe"}

CONTENT_ORIGIN = "migrated_pooyanpacs"
DEFAULT_AUTHOR = "PooyanPacs Teaching Library (migrated)"
AI_FLAG = "AI-generated draft - please review."

# pydicom tags we actually need (keeps header reads fast).
_DICOM_TAGS = [
    "Modality", "StudyDescription", "SeriesDescription", "BodyPartExamined",
    "ProtocolName", "StudyInstanceUID", "SeriesInstanceUID", "SeriesNumber",
]


# ---------------------------------------------------------------------------
# Small text-normalisation helpers (safe, conservative)
# ---------------------------------------------------------------------------
_SPELL_FIXES = {
    "extrimity": "extremity",
    "extremeity": "extremity",
    "abdoman": "abdomen",
    "abdomin": "abdomen",
    "cervial": "cervical",
    "lumber": "lumbar",
    "thoraxic": "thoracic",
    "shouder": "shoulder",
    "kneee": "knee",
    "righ": "right",
    "lef": "left",
    "saggital": "sagittal",
    "saggittal": "sagittal",
    "axail": "axial",
    "coronoal": "coronal",
    # Seen in the PooyanPacs teaching study descriptions.
    "exteimiti": "extremity",
    "exteimit": "extremity",
    "extremiti": "extremity",
    "extremeti": "extremity",
    "ankel": "ankle",
    "anlke": "ankle",
    "scarpbook": "scrapbook",
    "uppe": "upper",
    "lowe": "lower",
}

# Standalone tokens that encode laterality (mapped to a clean suffix).
_LATERALITY = {"lt": "Left", "left": "Left", "rt": "Right", "right": "Right",
               "bilateral": "Bilateral", "bilat": "Bilateral"}
# Standalone scanner/technologist noise tokens dropped from titles.
_TITLE_NOISE = {"k", "x", "p2", "p3", "tra", "cor", "sag", "fs", "tse", "pd",
                "stir", "t1", "t2", "256", "448", "320", "512"}

_BODY_PART_TO_SPECIALTY = {
    # MSK
    "SHOULDER": "MSK", "KNEE": "MSK", "HIP": "MSK", "WRIST": "MSK",
    "ANKLE": "MSK", "ELBOW": "MSK", "FOOT": "MSK", "HAND": "MSK",
    "FEMUR": "MSK", "TIBIA": "MSK", "HUMERUS": "MSK", "EXTREMITY": "MSK",
    "TMJ": "MSK", "JOINT": "MSK", "PELVIS": "MSK", "SACRUM": "MSK",
    # Neuro / spine
    "BRAIN": "Neuro", "HEAD": "Neuro", "SKULL": "Neuro", "ORBIT": "Neuro",
    "CSPINE": "Spine", "TSPINE": "Spine", "LSPINE": "Spine", "SPINE": "Spine",
    "CERVICAL": "Spine", "LUMBAR": "Spine", "THORACIC": "Spine",
    # Body
    "CHEST": "Chest", "THORAX": "Chest", "LUNG": "Chest",
    "ABDOMEN": "Abdomen", "LIVER": "Abdomen", "KIDNEY": "Abdomen",
    "NECK": "Head/Neck", "SINUS": "Head/Neck", "FACE": "Head/Neck",
    "BREAST": "Breast", "HEART": "Cardiac", "CARDIAC": "Cardiac",
}


def _clean_text(value: Optional[str]) -> str:
    """Normalise DICOM-style descriptions into readable text."""
    text = str(value or "").strip()
    if not text:
        return ""
    # DICOM uses '^' as a component separator and frequently has stray dots/underscores.
    text = text.replace("^", " ").replace("_", " ")
    text = re.sub(r"\s*\.\s*", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .-")
    # Conservative spelling correction, word by word, case-insensitive.
    out_words = []
    for word in text.split(" "):
        low = word.lower()
        fixed = _SPELL_FIXES.get(low)
        out_words.append(fixed if fixed else word)
    return " ".join(out_words).strip()


def _smart_title(value: str) -> str:
    """Title-case while keeping common acronyms uppercase."""
    text = _clean_text(value)
    if not text:
        return ""
    acronyms = {"MR", "MRI", "CT", "US", "XR", "CR", "DX", "MG", "PX", "PET",
                "T1", "T2", "FS", "TSE", "STIR", "FLAIR", "DWI", "ADC", "TMJ",
                "RT", "LT", "PD", "GRE", "TOF", "MIP", "3D", "2D",
                "AP", "PA", "LAT", "OBL", "TFCC"}
    words = []
    for w in text.split(" "):
        wl = w.upper()
        if wl in acronyms:
            words.append(wl)
        else:
            # Title-case everything else (so FOOT/HAND/KNEE -> Foot/Hand/Knee).
            words.append(w.capitalize())
    return " ".join(words)


def _normalize_anatomy_title(raw: str) -> str:
    """Turn a raw DICOM StudyDescription into a clean anatomy title.

    Fixes spelling, lifts laterality (LT/RT) into a "(Left)/(Right)" suffix and
    drops standalone scanner/technologist noise tokens.  Example:
    ``"Lower Exteimiti FOOT LT -K"`` -> ``"Lower Extremity Foot (Left)"``.
    """
    text = _clean_text(raw)
    if not text:
        return ""
    laterality = ""
    kept: List[str] = []
    for tok in text.replace("&", " & ").split():
        low = tok.lower().strip("-").strip(".")
        if low in _LATERALITY:
            laterality = laterality or _LATERALITY[low]
        elif low in _TITLE_NOISE:
            continue
        else:
            kept.append(tok)
    base = _smart_title(" ".join(kept)).strip(" -&")
    if laterality:
        base = f"{base} ({laterality})" if base else laterality
    return base


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Configuration + result records
# ---------------------------------------------------------------------------
@dataclass
class ImportConfig:
    """Tunable knobs for an import run."""
    copy_assets: bool = True          # copy every source byte into the asset store
    derive_dicom_facts: bool = True   # read DICOM headers for factual metadata
    enrich_ai: bool = True            # add AI-drafted (flagged) text
    normalize_order: bool = True      # re-order items pedagogically
    overrides: Dict[str, Any] = field(default_factory=dict)  # curated per-course text
    skip_if_already_imported: bool = True  # idempotency on import_source_path
    dry_run: bool = False             # scan + report only, no DB writes / no copy
    progress: Optional[Callable[[str], None]] = None


@dataclass
class CourseResult:
    source_path: str
    course_pk: Optional[int] = None
    course_name: str = ""
    item_count: int = 0
    resource_count: int = 0
    dicom_studies: int = 0
    images: int = 0
    documents: int = 0
    presentations: int = 0
    videos: int = 0
    encrypted_archived: int = 0
    archives: int = 0
    bytes_copied: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    skipped: bool = False


# ---------------------------------------------------------------------------
# DICOM fact extraction
# ---------------------------------------------------------------------------
def _read_dicom_header(path: Path):
    try:
        import warnings as _warnings
        import pydicom
        with _warnings.catch_warnings():
            # Some teaching files carry non-conformant UIDs; pydicom still reads
            # them fine -- silence the noisy VR warnings.  pydicom validates
            # values lazily on access, so force-decode (and cache) the tags we
            # use here, inside the suppression block, so later attribute access
            # in the scanner does not re-emit the warning.
            _warnings.simplefilter("ignore")
            ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
            for _kw in _DICOM_TAGS:
                try:
                    getattr(ds, _kw, None)
                except Exception:
                    pass
            return ds
    except Exception:
        return None


def _is_dicom_file(path: Path) -> bool:
    if path.suffix.lower() in DICOM_EXTS:
        return True
    # Extension-less DICOM: sniff the DICM magic at byte offset 128.
    try:
        with open(path, "rb") as fp:
            fp.seek(128)
            return fp.read(4) == b"DICM"
    except Exception:
        return False


def _leaf_dicom_dirs(root: Path) -> List[Path]:
    """Return folders that directly contain at least one DICOM instance."""
    out: List[Path] = []
    for dirpath, _dirs, files in os.walk(root):
        d = Path(dirpath)
        if d.name.lower() == "cachefile":
            continue  # JPEG preview cache, handled separately
        for f in files:
            if _is_dicom_file(d / f):
                out.append(d)
                break
    return out


@dataclass
class SeriesInfo:
    series_number: int
    series_uid: str
    description: str
    files: List[Path]


@dataclass
class StudyInfo:
    study_uid: str
    modality: str
    study_description: str
    body_part: str
    series: Dict[int, SeriesInfo] = field(default_factory=dict)

    @property
    def instance_count(self) -> int:
        return sum(len(s.files) for s in self.series.values())


def scan_item_dicom(item_dir: Path) -> List[StudyInfo]:
    """
    Group every DICOM instance under ``item_dir`` by study + series.

    One header is read per leaf series folder (fast); the file's StudyInstanceUID
    / SeriesNumber / Modality / descriptions drive grouping and enrichment.
    """
    studies: Dict[str, StudyInfo] = {}
    next_synthetic_series = [1]

    for leaf in _leaf_dicom_dirs(item_dir):
        files = [leaf / f for f in os.listdir(leaf) if _is_dicom_file(leaf / f)]
        if not files:
            continue
        ds = _read_dicom_header(files[0])
        study_uid = str(getattr(ds, "StudyInstanceUID", "") or "").strip() if ds else ""
        series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "").strip() if ds else ""
        modality = str(getattr(ds, "Modality", "") or "").strip() if ds else ""
        study_desc = _clean_text(getattr(ds, "StudyDescription", "")) if ds else ""
        series_desc = _clean_text(getattr(ds, "SeriesDescription", "")) if ds else ""
        body_part = str(getattr(ds, "BodyPartExamined", "") or "").strip().upper() if ds else ""
        try:
            series_number = int(getattr(ds, "SeriesNumber", None))
        except (TypeError, ValueError):
            series_number = None

        if not study_uid:
            # Fall back to the folder name so unreadable studies still group.
            study_uid = f"local::{leaf.parent.name or item_dir.name}"

        study = studies.get(study_uid)
        if study is None:
            study = StudyInfo(study_uid=study_uid, modality=modality,
                              study_description=study_desc, body_part=body_part)
            studies[study_uid] = study
        # Keep the richest facts seen.
        study.modality = study.modality or modality
        study.study_description = study.study_description or study_desc
        study.body_part = study.body_part or body_part

        if series_number is None or series_number in study.series:
            # Avoid collisions / missing numbers with a synthetic, stable id.
            series_number = next_synthetic_series[0]
            next_synthetic_series[0] += 1
            while series_number in study.series:
                series_number = next_synthetic_series[0]
                next_synthetic_series[0] += 1
        study.series[series_number] = SeriesInfo(
            series_number=series_number, series_uid=series_uid,
            description=series_desc, files=files,
        )

    return list(studies.values())


# ---------------------------------------------------------------------------
# Enrichment
# ---------------------------------------------------------------------------
def _specialty_for(body_parts: List[str]) -> List[str]:
    regions = []
    for bp in body_parts:
        up = bp.upper()
        for key, spec in _BODY_PART_TO_SPECIALTY.items():
            if key in up and spec not in regions:
                regions.append(spec)
    return regions


def _objectives_for(modality: str, body_part: str) -> List[str]:
    """Readable, body-part/modality-aware objectives with NO placeholder text."""
    bp = _smart_title(body_part)
    mod = (modality or "").upper()
    if bp and mod:
        return [
            f"Review the normal {bp} anatomy on {mod}.",
            f"Apply a systematic approach to interpreting {mod} of the {bp.lower()}.",
            f"Recognise common {bp.lower()} pathology and key imaging findings.",
        ]
    if bp:
        return [
            f"Review the normal {bp} anatomy.",
            f"Apply a systematic approach to {bp.lower()} interpretation.",
            f"Recognise common {bp.lower()} pathology and key findings.",
        ]
    if mod:
        return [
            f"Review the normal appearances on {mod} in this case.",
            f"Apply a systematic approach to {mod} interpretation.",
            "Recognise the key imaging findings in this case.",
        ]
    return [
        "Review the normal appearances in this teaching case.",
        "Apply a systematic interpretation approach.",
        "Recognise the key imaging findings.",
    ]


def build_item_enrichment(item_meta: Dict[str, Any],
                          studies: List[StudyInfo],
                          loose_resources: List[Dict[str, Any]],
                          config: ImportConfig,
                          course_modality: str = "",
                          course_body_part: str = "") -> Dict[str, Any]:
    """Produce normalised + (optionally) AI-flagged metadata for one item.

    ``course_modality`` / ``course_body_part`` are fall-backs used to enrich items
    that carry no DICOM facts of their own (so they never ship placeholder text).
    """
    src_title = str(item_meta.get("itemTitle") or item_meta.get("itemName") or "").strip()
    src_desc = str(item_meta.get("itemDescription") or "").strip()
    meta = item_meta.get("metadata") or {}

    modality = (meta.get("modality") or "").strip()
    body_part = (meta.get("anatomicalRegion") or "").strip()
    diagnosis = (meta.get("diagnosis") or "").strip()
    study_descs: List[str] = []
    series_descs: List[str] = []
    for st in studies:
        modality = modality or st.modality
        body_part = body_part or st.body_part
        if st.study_description:
            study_descs.append(st.study_description)
        for s in st.series.values():
            if s.description:
                series_descs.append(s.description)

    has_dicom = bool(studies)
    eff_modality = modality or course_modality
    eff_body = body_part or course_body_part

    # Title: prefer a real, non-placeholder source title, else derive cleanly.
    placeholder = (not src_title) or re.fullmatch(r"Item-?\d+", src_title or "", re.I)
    if not placeholder:
        title = _smart_title(src_title)
    elif has_dicom:
        anatomy = _normalize_anatomy_title(study_descs[0]) if study_descs else ""
        if not anatomy and eff_body:
            anatomy = _smart_title(eff_body)
        mod = (eff_modality or "").upper()
        if anatomy and mod:
            title = f"{mod} - {anatomy}"
        elif anatomy:
            title = anatomy
        elif mod:
            title = f"{mod} Teaching Case"
        else:
            title = "Teaching Case"
    else:
        # No DICOM of its own -> supplementary material (named from course context).
        ctx = _smart_title(eff_body)
        title = f"{ctx} - Supplementary Material" if ctx else "Supplementary Material"

    ai_flags: List[str] = []
    # Description.
    description = src_desc
    if not description and config.enrich_ai:
        parts = []
        if eff_modality and eff_body:
            parts.append(f"{eff_modality.upper()} teaching case of the "
                         f"{_smart_title(eff_body).lower()}.")
        elif study_descs:
            parts.append(f"Teaching case: {_normalize_anatomy_title(study_descs[0])}.")
        if has_dicom:
            n_series = sum(len(s.series) for s in studies)
            n_inst = sum(s.instance_count for s in studies)
            parts.append(f"Includes {len(studies)} DICOM study(ies), "
                         f"{n_series} series, {n_inst} images.")
            uniq_series = ", ".join(sorted({_smart_title(s) for s in series_descs if s})[:6])
            if uniq_series:
                parts.append(f"Series: {uniq_series}.")
        else:
            parts.append("Supplementary teaching material for this course.")
        description = " ".join(parts).strip()
        if description:
            ai_flags.append("description")

    # Learning objectives + keywords (AI-drafted, course-aware fall-backs).
    objectives: List[str] = []
    keywords: List[str] = []
    if config.enrich_ai:
        objectives = _objectives_for(eff_modality, eff_body)
        ai_flags.append("objectives")
        for token in [(eff_modality or "").upper(), _smart_title(eff_body)]:
            if token and token not in keywords:
                keywords.append(token)
        for s in sorted({_smart_title(x) for x in series_descs if x})[:5]:
            if s and s not in keywords:
                keywords.append(s)
        keywords.append("Teaching case")

    return {
        "title": title or "Teaching Case",
        "description": description,
        "diagnosis": diagnosis,
        "modality": eff_modality,
        "body_part": eff_body,
        "objectives": objectives,
        "keywords": keywords,
        "ai_flags": ai_flags,
        "has_dicom": has_dicom,
    }


def compose_slide_notes(enr: Dict[str, Any], provenance: str) -> str:
    """Render an item's enrichment into the slide_notes text block."""
    lines: List[str] = []
    if enr.get("description"):
        lines.append(enr["description"])
    if enr.get("diagnosis"):
        lines.append("")
        lines.append(f"Diagnosis: {enr['diagnosis']}")
    if enr.get("objectives"):
        lines.append("")
        lines.append("Learning objectives:")
        lines.extend(f"  - {o}" for o in enr["objectives"])
    if enr.get("keywords"):
        lines.append("")
        lines.append("Keywords: " + ", ".join(enr["keywords"]))
    lines.append("")
    lines.append(provenance)
    if enr.get("ai_flags"):
        lines.append(f"[{AI_FLAG}]")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# The importer
# ---------------------------------------------------------------------------
class EducationCourseImporter:
    """Import + enrich external course packages into the Education module."""

    def __init__(self, config: Optional[ImportConfig] = None):
        self.config = config or ImportConfig()
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.results: List[CourseResult] = []
        self._log_lines: List[str] = []

    # -- logging -----------------------------------------------------------
    def _log(self, msg: str) -> None:
        line = f"{_now_iso()}  {msg}"
        self._log_lines.append(line)
        logger.info(msg)
        if self.config.progress:
            try:
                self.config.progress(msg)
            except Exception:
                pass

    # -- discovery ---------------------------------------------------------
    @staticmethod
    def _load_json(path: Path) -> Dict[str, Any]:
        try:
            with open(path, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception:
            return {}

    @staticmethod
    def find_course_folders(root: Path) -> List[Path]:
        """A Learn root contains many ``Course-*`` folders (or is one course)."""
        root = Path(root)
        if (root / "course.json").exists():
            return [root]
        courses = [p for p in sorted(root.iterdir()) if p.is_dir() and
                   (p / "course.json").exists()]
        if courses:
            return courses
        # Fallback: any sub-folder that itself has item-like sub-folders.
        return [p for p in sorted(root.iterdir()) if p.is_dir()]

    def _item_dirs(self, course_dir: Path, course_meta: Dict[str, Any]) -> List[Tuple[Path, Dict[str, Any]]]:
        """Return (item_dir, item_meta) pairs in source order."""
        pairs: List[Tuple[Path, Dict[str, Any]]] = []
        items = course_meta.get("items")
        if isinstance(items, list) and items:
            for it in items:
                rel = str(it.get("relativePath") or it.get("itemName") or "").strip()
                d = course_dir / rel if rel else None
                if d and d.is_dir():
                    im = self._load_json(d / "item.json") or {}
                    if not im:
                        im = dict(it)
                    pairs.append((d, im))
        if not pairs:  # folder-scan fallback
            for d in sorted(course_dir.iterdir()):
                if d.is_dir() and re.match(r"Item", d.name, re.I):
                    pairs.append((d, self._load_json(d / "item.json") or {}))
        return pairs

    # -- resource classification ------------------------------------------
    def _classify_loose_files(self, item_dir: Path) -> List[Dict[str, Any]]:
        """Classify non-DICOM, non-metadata files anywhere under the item."""
        resources: List[Dict[str, Any]] = []
        for dirpath, _dirs, files in os.walk(item_dir):
            d = Path(dirpath)
            # Skip DICOM trees + their JPEG preview caches (handled with DICOM).
            parts_lower = {p.lower() for p in d.relative_to(item_dir).parts}
            in_dicom_tree = any(p.startswith("dicom") for p in parts_lower) or \
                "cachefile" in parts_lower
            for f in files:
                fp = d / f
                ext = fp.suffix.lower()
                if f.lower() in METADATA_NAMES:
                    continue
                if _is_dicom_file(fp):
                    continue
                if in_dicom_tree and ext in IMAGE_EXTS:
                    continue  # DICOM cache preview -> part of the DICOM resource
                kind = self._kind_for_ext(ext)
                resources.append({
                    "kind": kind, "path": fp, "name": fp.stem,
                    "ext": ext, "size": _safe_size(fp),
                })
        return resources

    @staticmethod
    def _kind_for_ext(ext: str) -> str:
        if ext in IMAGE_EXTS:
            return "image"
        if ext in PDF_EXTS:
            return "pdf"
        if ext in VIDEO_EXTS:
            return "video"
        if ext in AUDIO_EXTS:
            return "audio"
        if ext in PRESENTATION_EXTS:
            return "presentation"
        if ext in DOC_EXTS:
            return "document"
        if ext in TEXT_EXTS:
            return "text"
        if ext in ARCHIVE_EXTS:
            return "archive"
        if ext in ENCRYPTED_EXTS:
            return "encrypted"
        return "other"

    # -- scan + enrich (shared by import + re-enrich) ----------------------
    def _scan_and_enrich(self, item_pairs: List[Tuple[Path, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        """Two-pass: derive course-level facts, then enrich items with those
        fall-backs, order pedagogically, and disambiguate duplicate titles."""
        raw: List[Tuple[Path, Dict[str, Any], List[StudyInfo], List[Dict[str, Any]]]] = []
        course_mods: List[str] = []
        course_bps: List[str] = []
        for item_dir, item_meta in item_pairs:
            studies = scan_item_dicom(item_dir) if self.config.derive_dicom_facts else []
            loose = self._classify_loose_files(item_dir)
            raw.append((item_dir, item_meta, studies, loose))
            for st in studies:
                if st.modality and st.modality not in course_mods:
                    course_mods.append(st.modality)
                if st.body_part and st.body_part not in course_bps:
                    course_bps.append(st.body_part)
        course_modality = course_mods[0] if course_mods else ""
        course_body = course_bps[0] if course_bps else ""

        scanned: List[Dict[str, Any]] = []
        for item_dir, item_meta, studies, loose in raw:
            enr = build_item_enrichment(item_meta, studies, loose, self.config,
                                        course_modality=course_modality,
                                        course_body_part=course_body)
            scanned.append({"dir": item_dir, "meta": item_meta, "studies": studies,
                            "loose": loose, "enr": enr})

        if self.config.normalize_order:
            scanned = self._order_items(scanned)
        self._disambiguate_titles(scanned)
        return scanned

    @staticmethod
    def _disambiguate_titles(scanned: List[Dict[str, Any]]) -> None:
        """Append ' - Case N' to items that share an identical title."""
        counts: Dict[str, int] = {}
        for s in scanned:
            t = s["enr"]["title"]
            counts[t] = counts.get(t, 0) + 1
        running: Dict[str, int] = {}
        for s in scanned:
            t = s["enr"]["title"]
            if counts.get(t, 0) > 1:
                running[t] = running.get(t, 0) + 1
                s["enr"]["title"] = f"{t} - Case {running[t]}"

    # -- public API --------------------------------------------------------
    def import_learn_root(self, root: str) -> List[CourseResult]:
        course_dirs = self.find_course_folders(Path(root))
        self._log(f"Discovered {len(course_dirs)} course folder(s) under {root}")
        for cd in course_dirs:
            try:
                self.results.append(self.import_course_package(cd))
            except Exception as exc:  # never let one course abort the batch
                logger.exception("Course import failed: %s", cd)
                self.results.append(CourseResult(source_path=str(cd),
                                                 errors=[f"fatal: {exc}"]))
        self._write_run_report()
        return self.results

    def import_course_package(self, course_dir: str) -> CourseResult:
        course_dir = Path(course_dir)
        result = CourseResult(source_path=str(course_dir))
        course_meta = self._load_json(course_dir / "course.json")
        self._log(f"=== Importing course: {course_dir.name} ===")

        # Idempotency guard.
        if self.config.skip_if_already_imported and not self.config.dry_run:
            for c in get_all_courses():
                if str(c.get("import_source_path") or "") == str(course_dir):
                    self._log(f"  already imported (course_pk={c.get('course_pk')}); skipping")
                    result.skipped = True
                    result.course_pk = c.get("course_pk")
                    result.course_name = c.get("course_name", "")
                    return result

        item_pairs = self._item_dirs(course_dir, course_meta)
        result.item_count = len(item_pairs)

        # ---- scan + enrich every item (two-pass, course-aware) ----------
        scanned = self._scan_and_enrich(item_pairs)

        # ---- course-level enrichment ------------------------------------
        course_enr = self._build_course_enrichment(course_dir, course_meta, scanned)
        result.facts = course_enr["facts"]
        result.course_name = course_enr["name"]

        if self.config.dry_run:
            for s in scanned:
                self._tally(result, s)
            self._log(f"  [dry-run] '{course_enr['name']}' "
                      f"items={result.item_count} dicom={result.dicom_studies} "
                      f"images={result.images} docs={result.documents} "
                      f"enc={result.encrypted_archived}")
            return result

        # ---- create course row ------------------------------------------
        course_pk = insert_course(
            name=course_enr["name"],
            description=course_enr["description"],
            author=course_enr["author"],
            outline=course_enr["outline"],
            tags=course_enr["keywords"],
            modality=course_enr["modality"],
            body_regions=course_enr["body_regions"],
            level=course_enr["level"],
            is_my_course=False,
            is_downloaded=True,
            resource_type="Course",
            content_origin=CONTENT_ORIGIN,
            validation_status="needs_correction" if course_enr["needs_review"] else "ok",
            needs_attention=bool(course_enr["needs_review"]),
            import_source_path=str(course_dir),
        )
        result.course_pk = course_pk
        course_root = _ensure_course_storage(course_pk)
        assets_root = course_root / "assets"
        assets_root.mkdir(parents=True, exist_ok=True)

        # ---- create slides + content ------------------------------------
        for order, s in enumerate(scanned, start=1):
            self._create_slide(course_pk, assets_root, order, s, result)

        # ---- thumbnail (first preview image) ----------------------------
        thumb = self._first_preview(scanned)
        if thumb:
            try:
                dest = course_root / ("thumbnail" + thumb.suffix.lower())
                shutil.copy2(thumb, dest)
                result.bytes_copied += _safe_size(thumb)
                update_course(course_pk=course_pk, thumbnail_path=str(dest))
            except Exception as exc:
                result.warnings.append(f"thumbnail: {exc}")

        # ---- per-course manifest ----------------------------------------
        manifest = self._write_course_manifest(course_root, course_dir, course_enr,
                                                scanned, result)
        update_course(
            course_pk=course_pk,
            import_manifest_path=str(manifest),
            validation_status="needs_correction" if (course_enr["needs_review"] or result.warnings) else "ok",
            needs_attention=bool(course_enr["needs_review"] or result.warnings),
        )
        self._log(f"  created course_pk={course_pk} '{course_enr['name']}' "
                  f"slides={result.item_count} resources={result.resource_count} "
                  f"copied={_human_size(result.bytes_copied)}")
        return result

    # -- re-enrichment (update-in-place; NO asset copy) --------------------
    def reenrich_existing(self, only_origin: str = CONTENT_ORIGIN) -> List[Dict[str, Any]]:
        """Recompute titles / descriptions / objectives / metadata for already
        imported courses and UPDATE the DB in place (no re-copy of assets).

        Re-scans each course's ``import_source_path`` for DICOM facts, applies the
        (improved) enrichment + overrides, updates the course row and every slide,
        and clears the "needs attention" flag for fully-populated courses.
        Slides are matched to source items by the ``Source: <Item>`` provenance
        line, so it is order-independent.
        """
        summaries: List[Dict[str, Any]] = []
        for course in get_all_courses():
            if only_origin and str(course.get("content_origin") or "") != only_origin:
                continue
            src = Path(str(course.get("import_source_path") or ""))
            pk = course["course_pk"]
            if not src.exists():
                self._log(f"  [reenrich] pk={pk}: source missing ({src}); skipped")
                summaries.append({"course_pk": pk, "skipped": "source missing"})
                continue
            course_meta = self._load_json(src / "course.json")
            item_pairs = self._item_dirs(src, course_meta)
            scanned = self._scan_and_enrich(item_pairs)
            course_enr = self._build_course_enrichment(src, course_meta, scanned)

            update_course(
                course_pk=pk,
                name=course_enr["name"],
                description=course_enr["description"],
                author=course_enr["author"],
                outline=course_enr["outline"],
                tags=course_enr["keywords"],
                modality=course_enr["modality"],
                body_regions=course_enr["body_regions"],
                level=course_enr["level"],
                validation_status="needs_correction" if course_enr["needs_review"] else "ok",
                needs_attention=course_enr["needs_review"],
            )

            # Map slides to scanned items by the provenance "Source: <Item>" line.
            by_name = {s["dir"].name: s for s in scanned}
            slides = get_slides_for_course(pk)
            updated = 0
            ordered_titles = {s["dir"].name: i + 1 for i, s in enumerate(scanned)}
            for sl in slides:
                m = re.search(r"Source:\s*(\S+)", sl.get("slide_notes") or "")
                key = m.group(1) if m else None
                s = by_name.get(key)
                if not s:
                    continue
                provenance = (f"Source: {s['dir'].name} "
                              f"(migrated from the PooyanPacs teaching library).")
                update_slide(slide_pk=sl["slide_pk"],
                             slide_order=ordered_titles.get(s["dir"].name, sl["slide_order"]),
                             title=s["enr"]["title"],
                             notes=compose_slide_notes(s["enr"], provenance))
                updated += 1

            self._log(f"  [reenrich] pk={pk} -> '{course_enr['name']}' "
                      f"slides_updated={updated}/{len(slides)} "
                      f"needs_review={course_enr['needs_review']}")
            summaries.append({"course_pk": pk, "name": course_enr["name"],
                              "slides_updated": updated, "slides_total": len(slides),
                              "needs_review": course_enr["needs_review"]})
        return summaries

    # -- ordering ----------------------------------------------------------
    @staticmethod
    def _order_items(scanned: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Overview/normal/anatomy items first, then numeric source order."""
        def rank(s: Dict[str, Any]) -> Tuple[int, int]:
            text = (s["enr"].get("title", "") + " " +
                    str(s["meta"].get("itemTitle", ""))).lower()
            pri = 1
            if any(k in text for k in ("overview", "introduction", "intro",
                                       "normal", "anatomy", "approach", "basics")):
                pri = 0
            try:
                src_order = int(s["meta"].get("itemOrder") or 0) or _first_int(s["dir"].name)
            except Exception:
                src_order = _first_int(s["dir"].name)
            return (pri, src_order)
        return sorted(scanned, key=rank)

    # -- course enrichment -------------------------------------------------
    def _build_course_enrichment(self, course_dir: Path, course_meta: Dict[str, Any],
                                 scanned: List[Dict[str, Any]]) -> Dict[str, Any]:
        modalities: List[str] = []
        body_parts: List[str] = []
        for s in scanned:
            m = (s["enr"].get("modality") or "").upper()
            if m and m not in modalities:
                modalities.append(m)
            bp = (s["enr"].get("body_part") or "").upper()
            if bp and bp not in body_parts:
                body_parts.append(bp)

        regions = _specialty_for(body_parts)
        dom_modality = modalities[0] if modalities else ""
        n_items = len(scanned)
        n_dicom = sum(len(s["studies"]) for s in scanned)

        # Overrides (curated AI text) keyed by source folder name or courseId.
        ov = {}
        ovs = self.config.overrides or {}
        for key in (course_dir.name, str(course_meta.get("courseId")),
                    str(course_meta.get("courseName") or "")):
            if key and key in ovs:
                ov = ovs[key]
                break

        src_title = str(course_meta.get("courseTitle") or course_meta.get("courseName") or "").strip()
        placeholder = (not src_title) or re.fullmatch(r"Course-?\d+", src_title or "", re.I)
        ai_flagged = False

        if ov.get("title"):
            name = ov["title"]
        elif placeholder:
            specialty = regions[0] if regions else ""
            bp_label = _smart_title(body_parts[0]) if len(body_parts) == 1 else (specialty or "Radiology")
            name = f"{(dom_modality + ' ') if dom_modality else ''}{bp_label} - Teaching Collection".strip()
            ai_flagged = True
        else:
            name = _smart_title(src_title)

        if ov.get("description"):
            description = ov["description"]
        else:
            description = str(course_meta.get("courseDescription") or "").strip()
            if not description and self.config.enrich_ai:
                bp_list = ", ".join(_smart_title(b) for b in body_parts[:6]) or "various regions"
                mod_list = ", ".join(modalities) or "imaging"
                description = (f"A migrated teaching collection of {n_items} item(s) "
                              f"covering {bp_list} ({mod_list}). Contains {n_dicom} "
                              f"DICOM teaching study(ies) with annotated preview images.")
                ai_flagged = True

        keywords = list(ov.get("keywords") or [])
        for token in modalities + [_smart_title(b) for b in body_parts] + regions:
            if token and token not in keywords:
                keywords.append(token)
        for tag in ("Teaching", "Migrated"):
            if tag not in keywords:
                keywords.append(tag)

        level = ov.get("level") or course_meta.get("level") or "Intermediate"
        author = ov.get("author") or DEFAULT_AUTHOR
        objectives = ov.get("objectives") or []

        outline_lines = [f"{i+1}. {s['enr'].get('title','Item')}" for i, s in enumerate(scanned)]
        outline = ""
        if objectives:
            outline += "Course objectives:\n" + "\n".join(f"  - {o}" for o in objectives) + "\n\n"
        outline += "Items:\n" + "\n".join(outline_lines)
        if ai_flagged or ov.get("ai"):
            outline += f"\n\n[{AI_FLAG}]"

        final_regions = regions or body_parts[:4]
        # "needs_review" means a genuinely-required field could not be filled --
        # NOT merely that text was AI-drafted.  After enrichment these are
        # populated, so fully-enriched courses are clean (no "Needs Fix" badge).
        needs_review = not (name and description and (dom_modality or final_regions))

        return {
            "name": name, "description": description, "author": author,
            "outline": outline, "keywords": keywords, "modality": dom_modality,
            "body_regions": final_regions, "level": level,
            "ai_flagged": ai_flagged or bool(ov.get("ai")),
            "needs_review": needs_review,
            "facts": {"modalities": modalities, "body_parts": body_parts,
                      "regions": regions, "n_items": n_items, "n_dicom_studies": n_dicom},
        }

    # -- slide / content creation -----------------------------------------
    def _create_slide(self, course_pk: int, assets_root: Path, order: int,
                      s: Dict[str, Any], result: CourseResult) -> None:
        enr = s["enr"]
        provenance = f"Source: {s['dir'].name} (migrated from the PooyanPacs teaching library)."
        slide_pk = insert_slide(course_fk=course_pk, slide_order=order,
                                title=enr["title"],
                                notes=compose_slide_notes(enr, provenance))
        item_assets = assets_root / s["dir"].name

        # Preserve EVERY non-DICOM source byte (CacheFile previews, encrypted
        # originals, item.json, loose media) under _originals/, mirroring the
        # source layout.  DICOM instances are materialised separately into the
        # viewer's <study>/<series>/ layout.  Nothing is ever discarded.
        origin_map = self._preserve_originals(s["dir"], item_assets, result)
        content_order = 1

        # 1) DICOM studies (normalised viewer layout) come first.
        for idx, study in enumerate(s["studies"], start=1):
            try:
                study_path = self._materialise_study(item_assets, idx, study, result)
                rep_series = sorted(study.series.keys())[0] if study.series else None
                name = (_normalize_anatomy_title(study.study_description)
                        or _smart_title(study.body_part)
                        or f"DICOM Study {idx}")
                insert_slide_content(
                    slide_fk=slide_pk, content_type="dicom", content_order=content_order,
                    content_data={
                        "name": name,
                        "path": str(study_path),
                        "description": f"{study.modality or 'DICOM'} study - "
                                       f"{len(study.series)} series, {study.instance_count} images",
                        "study_uid": study.study_uid,
                        "series_number": rep_series,
                        "modality": study.modality,
                        "body_part": study.body_part,
                    })
                content_order += 1
                result.dicom_studies += 1
                result.resource_count += 1
            except Exception as exc:
                result.warnings.append(f"{s['dir'].name}: DICOM study {idx} failed: {exc}")

        # 2) Loose resources -> register pointing at the preserved copy.
        encrypted = 0
        for res in s["loose"]:
            kind = res["kind"]
            if kind == "encrypted":
                encrypted += 1
                continue
            stored = origin_map.get(str(res["path"]))
            if stored is None:
                result.warnings.append(f"{s['dir'].name}: {res['path'].name} not preserved")
                continue
            try:
                ctype, cdata = self._content_for(kind, res, stored)
                insert_slide_content(slide_fk=slide_pk, content_type=ctype,
                                     content_order=content_order, content_data=cdata)
                content_order += 1
                result.resource_count += 1
                self._tally_kind(result, kind)
            except Exception as exc:
                result.warnings.append(f"{s['dir'].name}: resource {res['path'].name} failed: {exc}")

        # 3) One summary note for the preserved (undecryptable) encrypted originals.
        if encrypted:
            result.encrypted_archived += encrypted
            insert_slide_content(
                slide_fk=slide_pk, content_type="text", content_order=content_order,
                content_data={
                    "name": "Encrypted originals (archived)",
                    "text": (f"{encrypted} encrypted source file(s) (.IPcryp/.IPdcom) "
                             f"were preserved under _originals/ but cannot be rendered "
                             f"(no decryption key in this package)."),
                    "path": str(item_assets / "_originals"),
                })
            content_order += 1

        # 4) Guarantee every slide has at least one content row.
        if content_order == 1:
            insert_slide_content(slide_fk=slide_pk, content_type="text", content_order=1,
                                 content_data={"name": enr["title"],
                                               "text": enr.get("description") or
                                               "Educational item (no renderable media detected)."})

    # -- asset materialisation --------------------------------------------
    def _materialise_study(self, item_assets: Path, idx: int, study: StudyInfo,
                           result: CourseResult) -> Path:
        """Copy a study into ``<item>/study_<idx>/<series_number>/*`` (viewer layout)."""
        study_dir = item_assets / f"study_{idx}"
        study_dir.mkdir(parents=True, exist_ok=True)
        for series_number, series in study.series.items():
            series_dir = study_dir / str(series_number)
            series_dir.mkdir(parents=True, exist_ok=True)
            for f in series.files:
                dest = series_dir / f.name
                if dest.exists():
                    dest = series_dir / f"{f.stem}_{abs(hash(str(f))) % 9999}{f.suffix}"
                shutil.copy2(f, dest)
                result.bytes_copied += _safe_size(f)
        return study_dir

    def _preserve_originals(self, item_dir: Path, item_assets: Path,
                            result: CourseResult) -> Dict[str, Path]:
        """Copy every non-DICOM file under ``item_dir`` into ``_originals/<relpath>``.

        Returns a ``{source_path_str: dest_path}`` map so loose resources can be
        registered against their preserved copy.  DICOM instances are skipped
        here (materialised into the viewer layout instead).
        """
        mapping: Dict[str, Path] = {}
        if not self.config.copy_assets:
            return mapping
        originals_root = item_assets / "_originals"
        for dirpath, _dirs, files in os.walk(item_dir):
            d = Path(dirpath)
            for f in files:
                src = d / f
                if _is_dicom_file(src):
                    continue  # preserved via _materialise_study
                try:
                    rel = src.relative_to(item_dir)
                    dest = originals_root / rel
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    result.bytes_copied += _safe_size(src)
                    mapping[str(src)] = dest
                except Exception as exc:
                    result.warnings.append(f"{item_dir.name}: preserve {f} failed: {exc}")
        return mapping

    @staticmethod
    def _content_for(kind: str, res: Dict[str, Any], stored: Path) -> Tuple[str, Dict[str, Any]]:
        name = _smart_title(res["name"]) or res["name"]
        base = {"name": name, "path": str(stored), "source_name": res["path"].name}
        if kind == "image":
            return "image", {**base, "caption": name}
        if kind == "pdf":
            return "pdf", base
        if kind == "video":
            return "video", base
        if kind == "audio":
            return "audio", base
        if kind == "text":
            text = ""
            try:
                text = stored.read_text(encoding="utf-8", errors="replace")[:20000]
            except Exception:
                pass
            return "text", {**base, "text": text}
        if kind in ("presentation", "document"):
            # Routed to the viewport's "attachment" renderer (opens externally).
            label = {"presentation": "Presentation", "document": "Document"}[kind]
            return "attachment", {**base, "label": label}
        if kind in ("archive", "other"):
            label = {"archive": "Archive", "other": "Resource"}[kind]
            return "text", {**base,
                            "text": f"{label} resource '{res['path'].name}' "
                                    f"({_human_size(res['size'])}) preserved at the path "
                                    f"above. Open it with an external application."}
        return "text", {**base, "text": f"Resource: {res['path'].name}"}

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _first_preview(scanned: List[Dict[str, Any]]) -> Optional[Path]:
        for s in scanned:
            for dirpath, _d, files in os.walk(s["dir"]):
                if Path(dirpath).name.lower() == "cachefile":
                    for f in sorted(files):
                        if Path(f).suffix.lower() in IMAGE_EXTS:
                            return Path(dirpath) / f
        for s in scanned:
            for res in s["loose"]:
                if res["kind"] == "image":
                    return res["path"]
        return None

    @staticmethod
    def _tally_kind(result: CourseResult, kind: str) -> None:
        if kind == "image":
            result.images += 1
        elif kind in ("document", "text"):
            result.documents += 1
        elif kind == "presentation":
            result.presentations += 1
        elif kind == "video":
            result.videos += 1
        elif kind == "archive":
            result.archives += 1

    def _tally(self, result: CourseResult, s: Dict[str, Any]) -> None:
        result.dicom_studies += len(s["studies"])
        for res in s["loose"]:
            if res["kind"] == "encrypted":
                result.encrypted_archived += 1
            else:
                result.resource_count += 1
                self._tally_kind(result, res["kind"])
        result.resource_count += len(s["studies"])

    # -- reports -----------------------------------------------------------
    def _write_course_manifest(self, course_root: Path, course_dir: Path,
                               course_enr: Dict[str, Any], scanned: List[Dict[str, Any]],
                               result: CourseResult) -> Path:
        manifest = {
            "schema": "education-migration-v1",
            "run_id": self.run_id,
            "generated_at": _now_iso(),
            "source_folder": str(course_dir),
            "course_pk": result.course_pk,
            "course": {k: course_enr[k] for k in
                       ("name", "description", "author", "modality", "body_regions",
                        "level", "ai_flagged")},
            "facts": course_enr["facts"],
            "items": [{
                "source": s["dir"].name,
                "title": s["enr"]["title"],
                "modality": s["enr"].get("modality"),
                "body_part": s["enr"].get("body_part"),
                "dicom_studies": len(s["studies"]),
                "loose_resources": len(s["loose"]),
                "ai_flags": s["enr"].get("ai_flags", []),
            } for s in scanned],
            "totals": {
                "items": result.item_count,
                "resources": result.resource_count,
                "dicom_studies": result.dicom_studies,
                "images": result.images,
                "documents": result.documents,
                "presentations": result.presentations,
                "videos": result.videos,
                "encrypted_archived": result.encrypted_archived,
                "bytes_copied": result.bytes_copied,
            },
            "warnings": result.warnings,
        }
        path = course_root / "migration_manifest.json"
        try:
            with open(path, "w", encoding="utf-8") as fp:
                json.dump(manifest, fp, ensure_ascii=False, indent=2)
        except Exception as exc:
            result.warnings.append(f"manifest write failed: {exc}")
        return path

    def _write_run_report(self) -> Path:
        try:
            from PacsClient.utils.data_paths import EDUCATION_DIR, LOGS_DIR
            report_dir = Path(EDUCATION_DIR) / "migration_reports"
            log_dir = Path(LOGS_DIR)
        except Exception:
            report_dir = Path.cwd() / "education_migration_reports"
            log_dir = report_dir
        report_dir.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        summary = {
            "run_id": self.run_id,
            "generated_at": _now_iso(),
            "dry_run": self.config.dry_run,
            "courses": [{
                "source": r.source_path, "course_pk": r.course_pk,
                "name": r.course_name, "skipped": r.skipped,
                "items": r.item_count, "resources": r.resource_count,
                "dicom_studies": r.dicom_studies, "images": r.images,
                "documents": r.documents, "presentations": r.presentations,
                "videos": r.videos, "encrypted_archived": r.encrypted_archived,
                "bytes_copied": r.bytes_copied,
                "warnings": r.warnings, "errors": r.errors, "facts": r.facts,
            } for r in self.results],
            "totals": {
                "courses": len([r for r in self.results if not r.skipped]),
                "items": sum(r.item_count for r in self.results),
                "resources": sum(r.resource_count for r in self.results),
                "dicom_studies": sum(r.dicom_studies for r in self.results),
                "bytes_copied": sum(r.bytes_copied for r in self.results),
                "warnings": sum(len(r.warnings) for r in self.results),
                "errors": sum(len(r.errors) for r in self.results),
            },
        }
        report_path = report_dir / f"migration_{self.run_id}.json"
        with open(report_path, "w", encoding="utf-8") as fp:
            json.dump(summary, fp, ensure_ascii=False, indent=2)
        with open(log_dir / "education_import.log", "a", encoding="utf-8") as fp:
            fp.write("\n".join(self._log_lines) + "\n")
        self._log(f"Run report: {report_path}")
        return report_path


# ---------------------------------------------------------------------------
# Module-level conveniences
# ---------------------------------------------------------------------------
def _safe_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except Exception:
        return 0


def _first_int(text: str) -> int:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else 0


def migrate_pooyanpacs_learn(root: str, overrides: Optional[Dict[str, Any]] = None,
                             dry_run: bool = False,
                             progress: Optional[Callable[[str], None]] = None) -> List[CourseResult]:
    """Convenience entry-point used by the CLI runner + future callers."""
    cfg = ImportConfig(overrides=overrides or {}, dry_run=dry_run, progress=progress)
    return EducationCourseImporter(cfg).import_learn_root(root)
