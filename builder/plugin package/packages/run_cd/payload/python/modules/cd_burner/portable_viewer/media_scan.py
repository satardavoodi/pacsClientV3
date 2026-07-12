"""DICOM media discovery for the AI-PACS Lite Viewer.

Pure-python (pydicom only) — no Qt imports here so the scan logic is fully
unit-testable headless and can run on a worker thread.

Strategy:
1. If a ``DICOMDIR`` file exists at the media root, read it via
   ``pydicom.fileset.FileSet`` (fast, standard patient CD layout).
2. Otherwise (or if DICOMDIR parsing fails / yields nothing), recursively
   scan for ``*.dcm`` / ``*.dicom`` and extension-less DICOM files.

The result is a flat, ordered list of :class:`SeriesRecord` grouped by
patient → study → series, which the viewer renders as a series list.
"""

from __future__ import annotations

import logging
import io
import os
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from pydicom import dcmread

if __package__:  # package-relative (dev run inside AI-PACS repo)
    from .optical_io import read_bytes
    from .viewer_meta import VIEWER_EXE_NAME
else:  # standalone build / direct script execution
    from optical_io import read_bytes  # type: ignore
    from viewer_meta import VIEWER_EXE_NAME  # type: ignore

logger = logging.getLogger(__name__)


def _dcmread_header(path: str):
    """Header-only dcmread, retry-buffered for reliable optical reads."""
    try:
        return dcmread(io.BytesIO(read_bytes(path)), stop_before_pixels=True)
    except Exception:
        return dcmread(path, stop_before_pixels=True)

# Directories that never contain patient DICOM data on AI-PACS media.
#
# "_internal" is the PyInstaller payload folder of the viewer's OWN bundle. It
# ships pydicom, whose package data includes ~25 sample .dcm test files. Without
# this entry a scan of the viewer's own folder would "discover" those samples
# and present them to the patient as if they were their images. See
# _is_viewer_bundle_dir() for the matching guard on the media-root search.
_SKIP_DIR_NAMES = {
    "viewer", "$recycle.bin", "system volume information", "__pycache__", "_internal",
}

# Files at the media root that are definitely not DICOM instances.
_SKIP_FILE_NAMES = {
    "autorun.inf",
    "start_here.txt",
    "run_viewer.cmd",
    "open_dicom_folder.cmd",
    "aipacs_media_info.json",
}


@dataclass
class InstanceRecord:
    """One image file (one SOP instance) on the media."""

    path: str
    instance_number: int = 0
    sop_uid: str = ""


@dataclass
class SeriesRecord:
    """One displayable series with its sorted instances."""

    series_uid: str
    series_number: int = 0
    description: str = ""
    modality: str = ""
    patient_name: str = ""
    patient_id: str = ""
    study_uid: str = ""
    study_description: str = ""
    study_date: str = ""
    instances: List[InstanceRecord] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return len(self.instances)

    def sort_instances(self) -> None:
        self.instances.sort(key=lambda r: (r.instance_number, r.path))

    def display_label(self) -> str:
        desc = self.description or "(no description)"
        prefix = f"{self.modality} " if self.modality else ""
        return f"{prefix}{self.series_number or '?'} — {desc} ({self.image_count} img)"


@dataclass
class ScanResult:
    """All series found on the media, plus scan diagnostics."""

    root: str = ""
    series: List[SeriesRecord] = field(default_factory=list)
    source: str = "none"  # "dicomdir" | "filescan" | "none"
    errors: List[str] = field(default_factory=list)

    @property
    def total_images(self) -> int:
        return sum(s.image_count for s in self.series)

    def patient_labels(self) -> List[str]:
        seen: List[str] = []
        for s in self.series:
            label = _patient_label(s.patient_name, s.patient_id)
            if label not in seen:
                seen.append(label)
        return seen


def _patient_label(name: str, pid: str) -> str:
    name = (name or "").strip() or "Unknown patient"
    pid = (pid or "").strip()
    return f"{name} [{pid}]" if pid else name


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _series_sort_key(series: SeriesRecord) -> Tuple:
    return (
        _patient_label(series.patient_name, series.patient_id).lower(),
        series.study_date or "",
        series.study_uid,
        series.series_number,
        series.series_uid,
    )


# ---------------------------------------------------------------------------
# DICOMDIR path
# ---------------------------------------------------------------------------

def _scan_dicomdir(root: Path) -> Optional[List[SeriesRecord]]:
    """Read the standard DICOMDIR File-set. Returns None on failure."""
    dicomdir_path = root / "DICOMDIR"
    if not dicomdir_path.is_file():
        return None

    try:
        from pydicom.fileset import FileSet

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            fs = FileSet(str(dicomdir_path))
    except Exception as exc:  # corrupt / non-standard DICOMDIR
        logger.warning("DICOMDIR could not be read (%s); falling back to file scan", exc)
        return None

    series_map: Dict[str, SeriesRecord] = {}
    try:
        for instance in fs:
            try:
                path = str(instance.path)
                if not os.path.isfile(path):
                    continue
                series_uid = str(getattr(instance, "SeriesInstanceUID", "") or "")
                if not series_uid:
                    continue
                record = series_map.get(series_uid)
                if record is None:
                    record = SeriesRecord(
                        series_uid=series_uid,
                        series_number=_safe_int(getattr(instance, "SeriesNumber", 0)),
                        description=str(getattr(instance, "SeriesDescription", "") or ""),
                        modality=str(getattr(instance, "Modality", "") or ""),
                        patient_name=str(getattr(instance, "PatientName", "") or ""),
                        patient_id=str(getattr(instance, "PatientID", "") or ""),
                        study_uid=str(getattr(instance, "StudyInstanceUID", "") or ""),
                        study_description=str(getattr(instance, "StudyDescription", "") or ""),
                        study_date=str(getattr(instance, "StudyDate", "") or ""),
                    )
                    series_map[series_uid] = record
                record.instances.append(
                    InstanceRecord(
                        path=path,
                        instance_number=_safe_int(getattr(instance, "InstanceNumber", 0)),
                        sop_uid=str(getattr(instance, "SOPInstanceUID", "") or ""),
                    )
                )
            except Exception as exc:  # one bad record must not kill the scan
                logger.debug("Skipping DICOMDIR record: %s", exc)
                continue
    except Exception as exc:
        logger.warning("DICOMDIR iteration failed (%s); falling back to file scan", exc)
        return None

    series = [s for s in series_map.values() if s.instances]
    if not series:
        return None
    for s in series:
        s.sort_instances()
    series.sort(key=_series_sort_key)
    return series


# ---------------------------------------------------------------------------
# Recursive file-scan path
# ---------------------------------------------------------------------------

def _iter_candidate_files(root: Path):
    """Yield files that may be DICOM instances, skipping viewer/system dirs."""
    for dirpath, dirnames, filenames in os.walk(str(root)):
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIR_NAMES]
        for fname in filenames:
            lower = fname.lower()
            if lower in _SKIP_FILE_NAMES or lower == "dicomdir":
                continue
            suffix = Path(fname).suffix.lower()
            if suffix in (".dcm", ".dicom"):
                yield Path(dirpath) / fname
            elif suffix == "":
                yield Path(dirpath) / fname
            # Any other extension (.png/.txt/.exe/...) is ignored.


def _group_files_into_series(
    candidates,
    progress: Optional[Callable[[int, str], None]] = None,
    max_files: int = 50000,
    stats: Optional[Dict[str, int]] = None,
) -> List[SeriesRecord]:
    """Header-read each candidate file and group them patient → study → series.

    Shared by the recursive media scan and the drag-and-drop import, so both
    discover DICOM **by content**, never by file extension — patient CDs store
    instances as extension-less ``IM000000`` files.
    """
    series_map: Dict[str, SeriesRecord] = {}
    checked = 0
    valid = 0

    for path in candidates:
        if checked >= max_files:
            logger.warning("File scan stopped at %s files (safety cap)", max_files)
            break
        checked += 1
        if progress and checked % 100 == 0:
            progress(checked, f"Scanned {checked} files…")
        try:
            ds = _dcmread_header(str(path))
        except Exception:
            continue  # not a DICOM file

        series_uid = str(getattr(ds, "SeriesInstanceUID", "") or "")
        if not series_uid:
            continue
        valid += 1
        record = series_map.get(series_uid)
        if record is None:
            record = SeriesRecord(
                series_uid=series_uid,
                series_number=_safe_int(getattr(ds, "SeriesNumber", 0)),
                description=str(getattr(ds, "SeriesDescription", "") or ""),
                modality=str(getattr(ds, "Modality", "") or ""),
                patient_name=str(getattr(ds, "PatientName", "") or ""),
                patient_id=str(getattr(ds, "PatientID", "") or ""),
                study_uid=str(getattr(ds, "StudyInstanceUID", "") or ""),
                study_description=str(getattr(ds, "StudyDescription", "") or ""),
                study_date=str(getattr(ds, "StudyDate", "") or ""),
            )
            series_map[series_uid] = record
        record.instances.append(
            InstanceRecord(
                path=str(path),
                instance_number=_safe_int(getattr(ds, "InstanceNumber", 0)),
                sop_uid=str(getattr(ds, "SOPInstanceUID", "") or ""),
            )
        )

    if stats is not None:
        stats["checked"] = checked
        stats["valid"] = valid
        stats["invalid"] = checked - valid

    series = [s for s in series_map.values() if s.instances]
    for s in series:
        s.sort_instances()
    series.sort(key=_series_sort_key)
    return series


def _scan_files(
    root: Path,
    progress: Optional[Callable[[int, str], None]] = None,
    max_files: int = 50000,
) -> List[SeriesRecord]:
    return _group_files_into_series(
        _iter_candidate_files(root), progress=progress, max_files=max_files
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_media(
    root: str,
    progress: Optional[Callable[[int, str], None]] = None,
) -> ScanResult:
    """Scan a folder (media root) for DICOM series.

    Never raises — failures are reported in ``ScanResult.errors``.
    """
    result = ScanResult(root=str(root))
    try:
        root_path = Path(root)
        if not root_path.is_dir():
            result.errors.append(f"Folder does not exist: {root}")
            return result

        series = _scan_dicomdir(root_path)
        if series:
            result.series = series
            result.source = "dicomdir"
            return result

        series = _scan_files(root_path, progress=progress)
        if series:
            result.series = series
            result.source = "filescan"
            return result

        result.errors.append("No DICOM images found on this media.")
    except Exception as exc:  # defensive: scan must never crash the viewer
        logger.exception("Media scan failed")
        result.errors.append(f"Scan failed: {exc}")
    return result


def scan_paths(
    paths: List[str],
    progress: Optional[Callable[[int, str], None]] = None,
) -> ScanResult:
    """Discover DICOM series from an arbitrary set of dropped/selected paths.

    This is the drag-and-drop / Open-Import entry point. It accepts, in any
    combination:

    * a single DICOM file (with **or without** a ``.dcm`` extension)
    * several files from one or more series
    * a series folder, a study folder, or a patient folder
    * a disc root containing ``DICOMDIR`` (the standard patient-CD layout)
    * the ``DICOMDIR`` file itself

    Discovery is by **content**, never by extension: patient CDs write
    instances as extension-less ``IM000000`` files, so an extension filter
    would find nothing. Read-only media is fine — nothing is ever written
    to the source.

    Never raises; problems land in ``ScanResult.errors``.
    """
    result = ScanResult(root="")
    try:
        raw = [str(p) for p in (paths or []) if str(p).strip()]
        if not raw:
            result.errors.append("Nothing was dropped.")
            return result

        # A folder that is a media root (has DICOMDIR) — or the DICOMDIR file
        # itself — goes through the fast, standard File-set reader first.
        for path in raw:
            candidate = Path(path)
            if candidate.name.upper() == "DICOMDIR" and candidate.is_file():
                candidate = candidate.parent
            if candidate.is_dir() and (candidate / "DICOMDIR").is_file():
                series = _scan_dicomdir(candidate)
                if series:
                    result.root = str(candidate)
                    result.series = series
                    result.source = "dicomdir"
                    logger.info(
                        "[LITE-DROP] dicomdir_import root=%s series=%d images=%d",
                        candidate, len(series), sum(s.image_count for s in series),
                    )
                    return result

        # Otherwise: expand folders recursively, take files as-is (no extension
        # filter — a dropped file is a deliberate user choice; we validate it by
        # parsing it), then group by content.
        files: List[Path] = []
        seen: set = set()
        missing = 0
        for path in raw:
            candidate = Path(path)
            try:
                if candidate.is_dir():
                    for found in _iter_candidate_files(candidate):
                        key = str(found)
                        if key not in seen:
                            seen.add(key)
                            files.append(found)
                elif candidate.is_file():
                    key = str(candidate)
                    if key not in seen and candidate.name.lower() != "dicomdir":
                        seen.add(key)
                        files.append(candidate)
                else:
                    missing += 1
            except OSError as exc:  # unreadable / disconnected media
                result.errors.append(f"Cannot read {candidate}: {exc}")

        if missing:
            result.errors.append(f"{missing} dropped path(s) no longer exist.")
        if not files:
            result.errors.append("No files were found in the dropped item(s).")
            return result

        stats: Dict[str, int] = {}
        series = _group_files_into_series(files, progress=progress, stats=stats)
        result.root = str(Path(raw[0]).parent if Path(raw[0]).is_file() else raw[0])
        logger.info(
            "[LITE-DROP] filescan_import files=%d valid_dicom=%d invalid=%d series=%d",
            stats.get("checked", 0), stats.get("valid", 0),
            stats.get("invalid", 0), len(series),
        )
        if series:
            result.series = series
            result.source = "filescan"
            return result

        result.errors.append(
            "The dropped item(s) contain no readable DICOM images."
        )
    except Exception as exc:  # defensive: a drop must never crash the viewer
        logger.exception("[LITE-DROP] scan_paths failed")
        result.errors.append(f"Import failed: {exc}")
    return result


def load_media_info(root: str) -> dict:
    """Read AIPACS_MEDIA_INFO.json at the media root (defensive, never raises).

    Returns {} when missing/unreadable. The burner writes a ``center`` object
    (imaging-center name/address/phone) which the viewer shows as a header.
    """
    try:
        import json

        path = Path(root) / "AIPACS_MEDIA_INFO.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.debug("Media info unreadable: %s", exc)
    return {}


def _is_viewer_bundle_dir(path: Path) -> bool:
    """True when *path* is the viewer's OWN program folder, not patient media.

    CLINICAL SAFETY. The viewer's PyInstaller bundle ships pydicom, and pydicom's
    package data contains ~25 sample ``.dcm`` files. ``RUN_VIEWER.cmd`` copies the
    viewer to ``%TEMP%\\AIPacsLiteViewer`` and runs it from there, so the exe's
    folder is a media-root candidate — and if the ``--import-folder`` argument is
    ever lost or malformed, the fallback "does this folder contain any DICOM?"
    probe would find those samples and the patient would be shown **someone
    else's test images** instead of their own study.

    A directory that holds the viewer executable, or a PyInstaller ``_internal``
    payload, is the program — never the media. Reject it outright.
    """
    try:
        if (path / VIEWER_EXE_NAME).is_file():
            return True
        if (path / "_internal" / "base_library.zip").is_file():
            return True
    except OSError:
        pass
    return False


def discover_media_root(
    cli_folder: Optional[str],
    exe_dir: Optional[str] = None,
) -> Optional[str]:
    """Pick the most plausible media root.

    Order: explicit CLI folder → env override → the executable's folder and
    its parent (the viewer lives in ``<root>/VIEWER`` on burned media) →
    current working directory.

    The viewer's own program folder is never accepted (see
    :func:`_is_viewer_bundle_dir`).
    """
    candidates: List[Path] = []
    if cli_folder:
        candidates.append(Path(cli_folder))
    env_folder = os.environ.get("AIPACS_IMPORT_FOLDER", "").strip()
    if env_folder:
        candidates.append(Path(env_folder))
    if exe_dir:
        exe_path = Path(exe_dir)
        candidates.extend([exe_path, exe_path.parent])
    candidates.append(Path.cwd())

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if str(resolved) in seen or not resolved.is_dir():
            continue
        seen.add(str(resolved))
        if _is_viewer_bundle_dir(resolved):
            continue  # the viewer's own folder is never patient media
        if (resolved / "DICOMDIR").is_file():
            return str(resolved)

    # Second pass: accept the first existing candidate that has any DICOM file
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            continue
        if not resolved.is_dir():
            continue
        if _is_viewer_bundle_dir(resolved):
            # Would otherwise match pydicom's bundled sample .dcm files and show
            # them to the patient as their own images.
            logger.warning(
                "[LITE-START] Skipping the viewer's own program folder as a media "
                "root candidate: %s", resolved,
            )
            continue
        checked = 0
        for path in _iter_candidate_files(resolved):
            if checked >= 200:  # plausibility probe only — full scan happens later
                break
            checked += 1
            try:
                _dcmread_header(str(path))
                return str(resolved)
            except Exception:
                continue
    return None
