"""
modules.printing.data.series_repository
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Resolves DICOM file paths for a given series from the local study cache.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


def get_series_for_study(study_uid: str) -> List[dict]:
    """Return a list of series-info dicts for *study_uid*.

    Each dict contains at minimum:
        series_pk, series_number, series_description, modality,
        image_count, study_uid, series_path (str | None)

    Returns an empty list on any failure so the caller can degrade gracefully.
    """
    try:
        from database import manager as db_manager
        from database import core as database

        study_pk = db_manager.find_study_pk_with_study_uid(study_uid)
        if not study_pk:
            logger.warning("[printing.data] study_uid %s not found in DB", study_uid)
            return []

        rows = db_manager.get_series_by_study_pk(study_pk)
        result = []
        for row in rows:
            series_pk = row.get("series_pk")
            series_number = row.get("series_number")
            series_path = _resolve_series_path(study_uid, series_number)
            result.append(
                {
                    "series_pk": series_pk,
                    "series_uid": row.get("series_uid"),
                    "series_number": series_number,
                    "series_description": row.get("series_description") or "",
                    "modality": row.get("modality") or "",
                    "image_count": row.get("image_count") or 0,
                    "thumbnail_path": row.get("thumbnail_path"),
                    "study_uid": study_uid,
                    "series_path": str(series_path) if series_path else None,
                }
            )
        return result
    except Exception as exc:
        logger.exception("[printing.data] get_series_for_study failed: %s", exc)
        return []


def get_dicom_paths_for_series(
    series_pk: int,
    *,
    study_uid: Optional[str] = None,
    series_number: Optional[int] = None,
) -> List[str]:
    """Return sorted list of `.dcm` file paths for the given series.

    Strategy (first success wins):
    1. Walk `instances` table rows — each has an `instance_path`.
    2. Walk the on-disk series directory resolved from study_uid / series_number.
    3. Return empty list if nothing found.
    """
    paths: List[str] = []

    # Strategy 1 — DB instances table
    try:
        from database import manager as db_manager

        rows = db_manager.get_instances_by_series_pk(series_pk, group_id=0)
        if not rows:
            # Try group_id=1 as fallback
            rows = db_manager.get_instances_by_series_pk(series_pk, group_id=1)
        for row in rows:
            p = row.get("instance_path")
            if p and Path(p).is_file():
                paths.append(str(p))
    except Exception as exc:
        logger.debug("[printing.data] DB instance lookup failed: %s", exc)

    if paths:
        try:
            from natsort import natsorted
            return natsorted(paths)
        except ImportError:
            return sorted(paths)

    # Strategy 2 — filesystem scan
    if study_uid and series_number is not None:
        series_dir = _resolve_series_path(study_uid, series_number)
        if series_dir and series_dir.is_dir():
            dcm_files = [
                str(p)
                for p in series_dir.iterdir()
                if p.suffix.lower() in (".dcm", "") and p.is_file()
            ]
            try:
                from natsort import natsorted
                return natsorted(dcm_files)
            except ImportError:
                return sorted(dcm_files)

    return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _resolve_series_path(study_uid: str, series_number) -> Optional[Path]:
    """Return the on-disk directory that holds DICOMs for this series, or None."""
    try:
        from PacsClient.utils.data_paths import DICOM_IMAGES_DIR

        # Typical layout: DICOM_IMAGES_DIR / study_uid / Series_NNN
        study_dir = DICOM_IMAGES_DIR / str(study_uid)
        if not study_dir.is_dir():
            return None

        sn_str = str(series_number) if series_number is not None else ""

        # Try common naming conventions
        candidates = [
            study_dir / f"Series_{sn_str}",
            study_dir / f"series_{sn_str}",
            study_dir / sn_str,
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate

        # Last resort: any sub-directory whose name contains the series number
        if sn_str:
            for sub in study_dir.iterdir():
                if sub.is_dir() and sn_str in sub.name:
                    return sub

    except Exception as exc:
        logger.debug("[printing.data] _resolve_series_path failed: %s", exc)
    return None
