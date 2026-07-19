"""Patient / study DEMOGRAPHIC editing across every series and image of a study.

Backs the main-page right-click ``Edit patient / study info`` action.

WHAT THIS MODULE IS FOR
-----------------------
Correcting *demographic* DICOM tags that a modality or a reception desk got
wrong — a mis-typed name, the wrong Patient ID, a blank Institution Name, a
study stamped with the wrong date/time — on a study that is ALREADY on disk.

THE ONE HARD RULE: **IDENTITY IS NEVER REWRITTEN.**
--------------------------------------------------
``StudyInstanceUID`` / ``SeriesInstanceUID`` / ``SOPInstanceUID`` (and every
other UI-VR element) are **left byte-identical**. This is not a convenience —
it is what keeps the edit safe:

* the on-disk layout is ``SOURCE_PATH/<study_uid>/<series_number>/``, the
  thumbnails are ``THUMBNAIL_PATH/<study_uid>/<series_number>.png``, and
  ``studies.study_uid`` / ``series.series_uid`` key the local DB — regenerating
  a UID would orphan ALL of them at once;
* the viewport identity gate (``qt_fast_container._start_qt_viewer``) is
  fail-closed on ``series_uid``, and ``SeriesRef`` (OPT-35) resolves series
  identity from those same UIDs. A rewritten UID would present as the
  recurring "series won't display" class of defect.

The correct DICOM reading of a demographic correction is also that identity is
unchanged: it is the SAME physical exam of the SAME acquisition; only the
descriptive attributes were wrong. A NEW Study/Series/SOP identity is only
warranted when a genuinely NEW derived object is created (see
``modules/cd_burner/dicom_prepare.py``, which DOES remap UIDs — through a
single consistent old->new map — because anonymisation produces a new object).

Every write is verified: the UIDs are snapshotted before the edit and compared
after re-reading the written file. A mismatch fails the file and rolls the
whole study back from the backup.

SCOPE
-----
LOCAL ONLY. The AI-PACS server exposes no demographic-write endpoint (the
socket protocol is read-only apart from ``UpdateReportStatus``; the REST
surface only writes report content/status, approval flags, comments and
assignment). Edited values therefore live on this workstation until the
server-side record is corrected too — and a subsequent
"Refresh / Sync from server" will overwrite the local DB values with the
server's originals. ``server_push_supported()`` reports this so the UI can say
so plainly instead of implying the edit propagated.

Pure stdlib + pydicom. No Qt, no VTK, no DB — the caller owns those. Keep it
that way: it is why this can be unit-tested offscreen.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

#: Editable field -> (DICOM keyword, human label, VR).
#: PATIENT-level fields apply to every study of the patient; STUDY-level fields
#: are edited per study.
PATIENT_FIELDS: Dict[str, Tuple[str, str, str]] = {
    "patient_name": ("PatientName", "Patient Name", "PN"),
    "patient_id": ("PatientID", "Patient ID", "LO"),
    "patient_age": ("PatientAge", "Patient Age", "AS"),
}

STUDY_FIELDS: Dict[str, Tuple[str, str, str]] = {
    "institution_name": ("InstitutionName", "Institution Name", "LO"),
    "study_date": ("StudyDate", "Study Date", "DA"),
    "study_time": ("StudyTime", "Study Time", "TM"),
}

EDITABLE_FIELDS: Dict[str, Tuple[str, str, str]] = {**PATIENT_FIELDS, **STUDY_FIELDS}

#: Elements that must be byte-identical before and after an edit. Checked on
#: the file as WRITTEN, not just on the in-memory dataset.
PROTECTED_UID_KEYWORDS = frozenset(
    {
        "StudyInstanceUID",
        "SeriesInstanceUID",
        "SOPInstanceUID",
        "SOPClassUID",
        "FrameOfReferenceUID",
        "MediaStorageSOPInstanceUID",
        "MediaStorageSOPClassUID",
        "TransferSyntaxUID",
    }
)

#: UTF-8. Persian/Arabic patient names are routine here, and a name written
#: under a legacy single-byte character set comes back mojibake.
_UTF8_CHARSET = "ISO_IR 192"

_DICOM_SUFFIXES = (".dcm", ".dicom")

_RE_DATE = re.compile(r"^\d{8}$")
_RE_TIME = re.compile(r"^\d{2}(\d{2}(\d{2}(\.\d{1,6})?)?)?$")
_RE_AGE = re.compile(r"^\d{3}[DWMY]$")
_RE_AGE_LOOSE = re.compile(r"^\s*(\d{1,3})\s*([DWMYdwmy])?\s*$")


def server_push_supported() -> bool:
    """Whether edited demographics can be pushed back to the AI-PACS server.

    Always ``False`` today: no socket command and no REST endpoint accepts a
    demographic field (verified 2026-07-18). Exposed as a function rather than
    a constant so the UI has one honest place to ask, and so enabling a future
    server endpoint is a one-line change here instead of a copy-pasted string
    in a dialog.
    """
    return False


# ---------------------------------------------------------------------------
# Value normalisation + validation
# ---------------------------------------------------------------------------


def normalize_value(field_key: str, raw) -> str:
    """Coerce a UI string into its DICOM-canonical form. Never raises.

    Normalisation strips SEPARATORS ONLY (``2026-07-18`` -> ``20260718``,
    ``14:30:00`` -> ``143000``). It deliberately does NOT strip arbitrary
    characters: doing so would turn a typo like ``18 July 2026`` into an empty
    string, which reads as "clear this tag" and would silently DELETE the study
    date instead of reporting the mistake. Anything that is not a separator
    survives so that :func:`validate_edit` can reject it.
    """
    text = "" if raw is None else str(raw).strip()
    if not text:
        return ""
    if field_key == "study_date":
        return re.sub(r"[-/.\s]", "", text)
    if field_key == "study_time":
        cleaned = re.sub(r"[:\s]", "", text)
        if "." in cleaned:
            whole, _, frac = cleaned.partition(".")
            return whole + "." + frac[:6]
        return cleaned
    if field_key == "patient_age":
        m = _RE_AGE_LOOSE.match(text)
        if m:
            unit = (m.group(2) or "Y").upper()
            return f"{int(m.group(1)):03d}{unit}"
        return text.upper()
    return text


def validate_edit(values: Dict[str, str]) -> List[str]:
    """Return human-readable problems with ``values``. Empty list == valid.

    Only keys present in ``values`` are checked; an absent key means "leave
    unchanged". An empty string means "clear this tag", which is legal for
    every field here (all are type-2/type-3 in the relevant IODs) EXCEPT
    PatientID, which keys the whole local hierarchy.
    """
    errors: List[str] = []
    for key, raw in values.items():
        if key not in EDITABLE_FIELDS:
            errors.append(f"Unknown field '{key}'.")
            continue
        value = normalize_value(key, raw)
        label = EDITABLE_FIELDS[key][1]
        if not value:
            if key == "patient_id":
                errors.append("Patient ID cannot be empty.")
            continue
        if key == "study_date":
            if not _RE_DATE.match(value):
                errors.append(f"{label} must be 8 digits (YYYYMMDD), e.g. 20260718.")
            else:
                try:
                    datetime.strptime(value, "%Y%m%d")
                except ValueError:
                    errors.append(f"{label} '{value}' is not a real calendar date.")
        elif key == "study_time":
            if not _RE_TIME.match(value):
                errors.append(f"{label} must be HHMMSS (24-hour), e.g. 143000.")
            else:
                hh = int(value[0:2])
                mm = int(value[2:4]) if len(value) >= 4 else 0
                ss = int(value[4:6]) if len(value) >= 6 else 0
                if hh > 23 or mm > 59 or ss > 60:
                    errors.append(f"{label} '{value}' is not a valid time of day.")
        elif key == "patient_age":
            if not _RE_AGE.match(value):
                errors.append(
                    f"{label} must be 3 digits + D/W/M/Y, e.g. 045Y (45 years)."
                )
        elif key == "patient_id":
            if len(value) > 64:
                errors.append(f"{label} exceeds the 64-character DICOM limit.")
            if any(ch in value for ch in "\\\r\n\t"):
                errors.append(f"{label} contains an illegal character.")
        elif key == "patient_name":
            if any(ch in value for ch in "\r\n\t"):
                errors.append(f"{label} contains an illegal character.")
        elif key == "institution_name":
            if len(value) > 64:
                errors.append(f"{label} exceeds the 64-character DICOM limit.")
    return errors


# ---------------------------------------------------------------------------
# Enumeration + reading
# ---------------------------------------------------------------------------


def iter_series_dirs(study_dir: Path) -> Iterator[Path]:
    """Yield each series folder of a study, in numeric-ish order."""
    try:
        entries = [p for p in Path(study_dir).iterdir() if p.is_dir()]
    except OSError:
        return

    def _key(p: Path):
        name = p.name
        return (0, int(name)) if name.isdigit() else (1, 0, name)

    for path in sorted(entries, key=_key):
        yield path


def iter_study_dicom_files(study_dir: Path) -> Iterator[Path]:
    """Yield every complete instance file of a study.

    ``*.part`` is excluded on purpose: the download manager writes
    ``<name>.part`` then ``os.replace``s it into place, so a ``.part`` means the
    file is still being written. Editing one would corrupt an in-flight
    download. Sub-128-byte files are skipped for the same reason (they cannot
    hold a valid DICOM preamble).
    """
    root = Path(study_dir)
    if not root.is_dir():
        return
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in sorted(filenames):
            if name.endswith(".part"):
                continue
            if not name.lower().endswith(_DICOM_SUFFIXES):
                continue
            path = Path(dirpath) / name
            try:
                if path.stat().st_size < 128:
                    continue
            except OSError:
                continue
            yield path


def count_study_files(study_dir: Path) -> int:
    return sum(1 for _ in iter_study_dicom_files(study_dir))


def read_demographics(study_dir: Path) -> Dict[str, str]:
    """Read the current demographic values from a study's first readable file.

    Returns ``{}`` when nothing readable is present — the caller should then
    fall back to the values it already has (the patient-table row).
    """
    import pydicom

    for path in iter_study_dicom_files(study_dir):
        try:
            ds = pydicom.dcmread(
                str(path),
                stop_before_pixels=True,
                force=True,
                specific_tags=[kw for kw, _lbl, _vr in EDITABLE_FIELDS.values()],
            )
        except Exception:
            continue
        out: Dict[str, str] = {}
        for key, (keyword, _label, _vr) in EDITABLE_FIELDS.items():
            value = getattr(ds, keyword, None)
            out[key] = "" if value is None else str(value).strip()
        return out
    return {}


def _uid_snapshot(ds) -> Dict[str, str]:
    """Every UI-VR element in the dataset + file meta, keyed by tag.

    Tag-keyed rather than keyword-keyed so private and unknown UID elements are
    covered too — the guarantee is "no UID changed", not "no *known* UID
    changed".
    """
    snap: Dict[str, str] = {}
    try:
        for elem in ds.iterall():
            if elem.VR == "UI" and elem.value not in (None, ""):
                snap[str(elem.tag)] = str(elem.value)
    except Exception:
        pass
    meta = getattr(ds, "file_meta", None)
    if meta is not None:
        try:
            for elem in meta:
                if elem.VR == "UI" and elem.value not in (None, ""):
                    snap["meta:" + str(elem.tag)] = str(elem.value)
        except Exception:
            pass
    return snap


def _needs_utf8(values: Dict[str, str]) -> bool:
    return any(not str(v).isascii() for v in values.values() if v)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class StudyEditResult:
    study_uid: str
    study_dir: str
    total_files: int = 0
    edited_files: int = 0
    skipped_files: int = 0
    backup_dir: Optional[str] = None
    rolled_back: bool = False
    warnings: List[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and not self.rolled_back


@dataclass
class EditResult:
    applied_values: Dict[str, str] = field(default_factory=dict)
    studies: List[StudyEditResult] = field(default_factory=list)
    server_push_attempted: bool = False
    server_push_supported: bool = False
    server_push_note: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.studies) and all(s.ok for s in self.studies)

    @property
    def edited_files(self) -> int:
        return sum(s.edited_files for s in self.studies)

    @property
    def total_files(self) -> int:
        return sum(s.total_files for s in self.studies)

    def summary(self) -> str:
        if not self.studies:
            return "Nothing to edit — no DICOM files were found on disk."
        n_ok = sum(1 for s in self.studies if s.ok)
        parts = [
            f"{self.edited_files} of {self.total_files} image(s) updated "
            f"across {n_ok} of {len(self.studies)} stud(y/ies)."
        ]
        failed = [s for s in self.studies if not s.ok]
        for s in failed:
            state = "rolled back" if s.rolled_back else "failed"
            parts.append(f"Study {s.study_uid[:24]}…: {state} — {s.error or 'unknown error'}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


def backup_root_for(repo_root: Optional[Path] = None) -> Path:
    """``<repo>/backups`` — the convention the maintenance tools already use."""
    if repo_root is not None:
        return Path(repo_root) / "backups"
    return Path(__file__).resolve().parents[2] / "backups"


def _backup_study(study_dir: Path, study_uid: str, backup_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    safe_uid = re.sub(r"[^0-9A-Za-z._-]", "_", str(study_uid))[:64] or "study"
    dest = Path(backup_root) / f"dicom_edit_{safe_uid}_{stamp}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # ignore *.part: they belong to an in-flight download, not to this study's
    # committed state, and copying them would restore a partial file on rollback.
    shutil.copytree(
        str(study_dir), str(dest), ignore=shutil.ignore_patterns("*.part")
    )
    return dest


def _restore_study(study_dir: Path, backup_dir: Path) -> None:
    """Put every backed-up file back. Only touches files the backup contains."""
    backup = Path(backup_dir)
    for dirpath, _dirnames, filenames in os.walk(backup):
        rel = Path(dirpath).relative_to(backup)
        target_dir = Path(study_dir) / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in filenames:
            shutil.copy2(str(Path(dirpath) / name), str(target_dir / name))


# ---------------------------------------------------------------------------
# The edit
# ---------------------------------------------------------------------------


def _apply_to_dataset(ds, values: Dict[str, str], force_utf8: bool) -> bool:
    """Set the demographic tags on ``ds``. Returns True if anything changed."""
    changed = False
    if force_utf8:
        try:
            current = ds.get("SpecificCharacterSet", None)
            if str(current) != _UTF8_CHARSET:
                ds.SpecificCharacterSet = _UTF8_CHARSET
                changed = True
        except Exception:
            pass
    for key, new_value in values.items():
        keyword = EDITABLE_FIELDS[key][0]
        try:
            existing = getattr(ds, keyword, None)
            existing_text = "" if existing is None else str(existing).strip()
        except Exception:
            existing_text = ""
        if existing_text == new_value:
            continue
        try:
            setattr(ds, keyword, new_value)
            changed = True
        except Exception as exc:  # pragma: no cover - pydicom coercion failure
            raise ValueError(f"could not set {keyword}: {exc}") from exc
    return changed


def _write_atomic(ds, path: Path) -> None:
    """``.part`` temp then ``os.replace`` — the download manager's contract.

    ``os.replace`` is atomic on the same volume, so a crash mid-write can only
    ever leave a ``*.part`` (which every reader and the resume scan already
    ignore) — never a truncated ``.dcm`` that would look like a valid instance.
    """
    tmp = path.with_name(path.name + ".part")
    try:
        ds.save_as(str(tmp), write_like_original=False)
        os.replace(str(tmp), str(path))
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
        raise


def _edit_one_file(path: Path, values: Dict[str, str], force_utf8: bool) -> str:
    """Edit a single instance. Returns 'edited' | 'unchanged'. Raises on failure.

    Verifies UID immutability against the file as actually written — not the
    in-memory dataset — so a pydicom coercion or a transfer-syntax rewrite that
    disturbed an identity element cannot slip through.
    """
    import pydicom

    ds = pydicom.dcmread(str(path), force=True)
    before = _uid_snapshot(ds)

    changed = _apply_to_dataset(ds, values, force_utf8)
    if not changed:
        return "unchanged"

    if not getattr(ds, "file_meta", None):
        ds.fix_meta_info()

    _write_atomic(ds, path)

    verify = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
    after = _uid_snapshot(verify)
    for tag, original in before.items():
        if after.get(tag) != original:
            raise ValueError(
                f"UID immutability violated at {tag}: "
                f"{original!r} -> {after.get(tag)!r}"
            )
    return "edited"


def apply_demographic_edit(
    studies: Sequence[Tuple[str, Path]],
    values: Dict[str, str],
    *,
    backup_root: Optional[Path] = None,
    make_backup: bool = True,
    progress=None,
) -> EditResult:
    """Apply ``values`` to every image of every study in ``studies``.

    Args:
        studies: ``(study_uid, study_dir)`` pairs. A missing directory is
            reported, not fatal.
        values: field-key -> new value. Absent key == leave unchanged. Values
            are normalised and validated here; invalid input raises
            ``ValueError`` BEFORE anything is written.
        backup_root: where to copy originals. Defaults to ``<repo>/backups``.
        make_backup: when False, no backup and therefore NO rollback.
        progress: optional ``callable(done, total, study_uid)``, called from the
            calling thread. Run this whole function OFF the GUI thread.

    A study is all-or-nothing: any file that fails rolls that study back from
    its backup. Other studies are unaffected.
    """
    clean: Dict[str, str] = {}
    for key, raw in (values or {}).items():
        if key not in EDITABLE_FIELDS:
            raise ValueError(f"Unknown field '{key}'.")
        clean[key] = normalize_value(key, raw)

    problems = validate_edit(clean)
    if problems:
        raise ValueError("; ".join(problems))
    if not clean:
        raise ValueError("No fields to change.")

    force_utf8 = _needs_utf8(clean)
    root = Path(backup_root) if backup_root is not None else backup_root_for()

    result = EditResult(applied_values=dict(clean))
    result.server_push_supported = server_push_supported()
    if not result.server_push_supported:
        result.server_push_note = (
            "The server has no demographic-update endpoint, so this change is "
            "local to this workstation. 'Refresh / Sync from server' will "
            "restore the server's original values."
        )

    for study_uid, study_dir in studies:
        study_dir = Path(study_dir)
        sr = StudyEditResult(study_uid=str(study_uid), study_dir=str(study_dir))
        result.studies.append(sr)

        if not study_dir.is_dir():
            sr.error = "study folder not found on disk"
            continue

        files = list(iter_study_dicom_files(study_dir))
        sr.total_files = len(files)
        if not files:
            sr.warnings.append("no DICOM files on disk for this study")
            continue

        backup_dir: Optional[Path] = None
        if make_backup:
            try:
                backup_dir = _backup_study(study_dir, study_uid, root)
                sr.backup_dir = str(backup_dir)
            except Exception as exc:
                sr.error = f"backup failed, nothing was changed ({exc})"
                logger.exception("[DICOM-EDIT] backup failed for %s", study_uid)
                continue

        try:
            for index, path in enumerate(files, start=1):
                outcome = _edit_one_file(path, clean, force_utf8)
                if outcome == "edited":
                    sr.edited_files += 1
                else:
                    sr.skipped_files += 1
                if progress is not None:
                    try:
                        progress(index, len(files), str(study_uid))
                    except Exception:
                        pass
        except Exception as exc:
            sr.error = str(exc)
            logger.exception("[DICOM-EDIT] edit failed for study %s", study_uid)
            if backup_dir is not None:
                try:
                    _restore_study(study_dir, backup_dir)
                    sr.rolled_back = True
                    logger.warning(
                        "[DICOM-EDIT] study %s rolled back from %s",
                        study_uid,
                        backup_dir,
                    )
                except Exception:
                    sr.warnings.append(
                        f"ROLLBACK FAILED — originals are in {backup_dir}"
                    )
                    logger.exception(
                        "[DICOM-EDIT] rollback FAILED for %s", study_uid
                    )
            continue

        logger.info(
            "[DICOM-EDIT] study=%s edited=%d unchanged=%d total=%d backup=%s",
            study_uid,
            sr.edited_files,
            sr.skipped_files,
            sr.total_files,
            sr.backup_dir,
        )

    return result


def resolve_study_dirs(
    study_uids: Iterable[str], source_path: Optional[Path] = None
) -> List[Tuple[str, Path]]:
    """Map study UIDs to their on-disk folders (``SOURCE_PATH/<study_uid>``)."""
    if source_path is None:
        from PacsClient.utils.config import SOURCE_PATH as _SP

        source_path = Path(_SP)
    out: List[Tuple[str, Path]] = []
    seen = set()
    for uid in study_uids:
        text = str(uid or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append((text, Path(source_path) / text))
    return out
