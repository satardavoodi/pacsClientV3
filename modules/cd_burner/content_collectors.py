"""Collect optional CD content: patient reports, captured images, attachments.

Sources (as-built, see docs/pipelines/cd-burner-portable-viewer.md):
* Reports      → ``ai_reception_reports`` DB table (HTML content) via
                 ``database.ai_reception_db.ai_get_reception_reports``.
* Captures and attachments both live in ``ATTACHMENT_PATH/<study_uid>/``
  (viewport captures are PNG files; attachments are any type).
  - "Include JPEG images"  → image-type files from that folder → ``JPEG/``
  - "Include attachments"  → non-image files from that folder → ``ATTACHMENTS/``

Every collector is defensive: missing subsystems / empty folders produce
warnings (or silence), never exceptions — the burn must not fail because
optional content is unavailable.
"""

from __future__ import annotations

import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tif", ".tiff",
}

REPORTS_DIRNAME = "REPORTS"
IMAGES_DIRNAME = "JPEG"
ATTACHMENTS_DIRNAME = "ATTACHMENTS"


@dataclass
class CollectResult:
    files: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.files)


def _safe_name(value: str, default: str = "UNKNOWN") -> str:
    value = re.sub(r"[^A-Za-z0-9_\-]+", "_", str(value or "")).strip("_")
    return value[:48] or default


def _study_attachment_dir(study_uid: str) -> Optional[Path]:
    try:
        from PacsClient.utils.config import ATTACHMENT_PATH

        folder = Path(ATTACHMENT_PATH) / str(study_uid)
        return folder if folder.is_dir() else None
    except Exception as exc:  # plugin-only / headless contexts
        logger.debug("Attachment path unavailable: %s", exc)
        return None


def _unique_dest(dest_dir: Path, name: str) -> Path:
    candidate = dest_dir / name
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while candidate.exists():
        candidate = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

def collect_reports(
    studies: List[dict],
    dest_root: str,
    progress: Optional[Callable[[str], None]] = None,
) -> CollectResult:
    """Export each study's reception reports as HTML files under REPORTS/."""
    result = CollectResult()
    try:
        from database.ai_reception_db import ai_get_reception_reports
    except Exception as exc:
        result.warnings.append(f"Report subsystem unavailable: {exc}")
        return result

    dest_dir = Path(dest_root) / REPORTS_DIRNAME
    seen_ids = set()

    for study in studies:
        study_uid = study.get("study_uid") or ""
        patient_id = study.get("patient_id") or ""
        reports = []
        try:
            if study_uid:
                reports = ai_get_reception_reports(study_uid=study_uid) or []
            if not reports and patient_id:
                reports = ai_get_reception_reports(patient_id=patient_id) or []
        except Exception as exc:
            result.warnings.append(f"Could not query reports for {patient_id or study_uid}: {exc}")
            continue

        for report in reports:
            report_id = report.get("id")
            if report_id in seen_ids:
                continue
            seen_ids.add(report_id)

            html = report.get("html_content") or ""
            if not html.strip():
                continue

            patient_dir = dest_dir / _safe_name(report.get("patient_id") or patient_id)
            patient_dir.mkdir(parents=True, exist_ok=True)
            file_path = _unique_dest(patient_dir, f"report_{report_id or len(seen_ids)}.html")
            try:
                if "<html" not in html.lower():
                    html = (
                        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
                        "<title>Patient Report</title></head><body>"
                        f"{html}</body></html>"
                    )
                file_path.write_text(html, encoding="utf-8")
                result.files.append(str(file_path))
                if progress:
                    progress(f"Report added: {file_path.name}")
            except Exception as exc:
                result.warnings.append(f"Could not write report {report_id}: {exc}")

    if not result.files and not result.warnings:
        result.warnings.append("No reports found for the selected studies")
    return result


# ---------------------------------------------------------------------------
# Captured images (JPEG/PNG) and attachments
# ---------------------------------------------------------------------------

def _collect_from_attachment_dirs(
    studies: List[dict],
    dest_root: str,
    dirname: str,
    want_images: bool,
    progress: Optional[Callable[[str], None]] = None,
) -> CollectResult:
    result = CollectResult()
    dest_dir = Path(dest_root) / dirname

    found_any_dir = False
    for study in studies:
        study_uid = study.get("study_uid") or ""
        if not study_uid:
            continue
        source = _study_attachment_dir(study_uid)
        if source is None:
            continue
        found_any_dir = True

        study_dest = dest_dir / _safe_name(study_uid[-16:])
        for item in sorted(source.iterdir()):
            if not item.is_file():
                continue
            is_image = item.suffix.lower() in IMAGE_EXTENSIONS
            if is_image != want_images:
                continue
            try:
                study_dest.mkdir(parents=True, exist_ok=True)
                target = _unique_dest(study_dest, item.name)
                shutil.copy2(str(item), str(target))
                result.files.append(str(target))
                if progress:
                    progress(f"Added: {item.name}")
            except Exception as exc:
                result.warnings.append(f"Could not copy {item.name}: {exc}")

    if not result.files:
        kind = "captured images" if want_images else "attachments"
        if found_any_dir:
            result.warnings.append(f"No {kind} found for the selected studies")
        else:
            result.warnings.append(f"No attachment folders exist for the selected studies ({kind})")
    return result


def collect_images(
    studies: List[dict],
    dest_root: str,
    progress: Optional[Callable[[str], None]] = None,
) -> CollectResult:
    """Copy captured/exported image files (PNG/JPEG/…) into JPEG/."""
    return _collect_from_attachment_dirs(studies, dest_root, IMAGES_DIRNAME, True, progress)


def collect_attachments(
    studies: List[dict],
    dest_root: str,
    progress: Optional[Callable[[str], None]] = None,
) -> CollectResult:
    """Copy non-image patient attachments into ATTACHMENTS/."""
    return _collect_from_attachment_dirs(studies, dest_root, ATTACHMENTS_DIRNAME, False, progress)
