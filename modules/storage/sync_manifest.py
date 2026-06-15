"""Local study manifest + local-vs-server sync decision (READ-ONLY).

A single read-model for the "what does this study look like locally, and how does
that compare to the server?" question that is currently re-derived in several
places (``check_study_complete``, ``_detect_study_growth``, the right-panel cache
gate, ``validate_storage_consistency``). See the architecture review
``docs/reports/SYNC_DOWNLOAD_LIFECYCLE_REVIEW_2026-06-15.md`` §5.1.

Hard contract:
  * It performs **NO writes** and starts **NO downloads** — it only reads the DB
    (hint) and the disk (source of truth) and returns a pure decision.
  * Disk is the source of truth; the DB row (``studies.number_of_series`` /
    ``series.image_count`` / ``series.thumbnail_path``) is a hint only.
  * Pure/testable: the DB facts can be injected (``db_number_of_series`` /
    ``db_series``) so the disk + comparison logic can be unit-tested with no DB.

Nothing in the live open/render path depends on this yet — wiring it in is a
staged, flag-gated, golden-compared step (review §5.2 S2) so clinical behaviour
cannot change unreviewed.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from PacsClient.utils.config import SOURCE_PATH, THUMBNAIL_PATH
from PacsClient.utils.database import get_db_connection

logger = logging.getLogger(__name__)

# Study state vocabulary (matches the architecture-review brief).
STATE_NOT_DOWNLOADED = "NotDownloaded"
STATE_THUMBNAIL_ONLY = "ThumbnailOnly"
STATE_PARTIAL = "PartiallyDownloaded"
STATE_DOWNLOADED = "Downloaded"
STATE_STALE = "Stale"

_DICOM_EXT = ".dcm"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sn_sort_key(sn: str):
    try:
        return (0, int(sn))
    except (TypeError, ValueError):
        return (1, str(sn))


def _count_disk_instances(series_dir: Path) -> int:
    """Number of finished ``.dcm`` files in a series folder (``.part`` excluded —
    a partial write is ``<name>.dcm.part`` whose suffix is ``.part``)."""
    n = 0
    try:
        for f in series_dir.iterdir():
            try:
                if f.is_file() and f.suffix.lower() == _DICOM_EXT:
                    n += 1
            except OSError:
                continue
    except (OSError, ValueError):
        return 0
    return n


def _disk_series(study_dir: Path) -> Dict[str, int]:
    """{series_folder_name: finished_instance_count} for subfolders with >=1 .dcm."""
    out: Dict[str, int] = {}
    try:
        for child in study_dir.iterdir():
            try:
                if child.is_dir():
                    c = _count_disk_instances(child)
                    if c > 0:
                        out[child.name] = c
            except OSError:
                continue
    except (OSError, ValueError):
        pass
    return out


def _fetch_db_facts(study_uid: str):
    """Best-effort DB facts: (number_of_series|None,
    {series_number: {"image_count": int|None, "thumbnail_path": str}}).
    Returns (None, {}) on any error / missing column so a thin/legacy DB never
    breaks the read-model (disk remains the source of truth)."""
    number_of_series: Optional[int] = None
    series: Dict[str, Dict[str, Any]] = {}
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            try:
                row = cur.execute(
                    "SELECT number_of_series FROM studies WHERE study_uid=?",
                    (study_uid,),
                ).fetchone()
                if row and row[0] is not None:
                    number_of_series = int(row[0])
            except Exception:
                pass
            try:
                rows = cur.execute(
                    "SELECT s.series_number, s.image_count, s.thumbnail_path "
                    "FROM series s JOIN studies st ON s.study_fk = st.study_pk "
                    "WHERE st.study_uid=?",
                    (study_uid,),
                ).fetchall()
                for r in rows or []:
                    if r[0] is None:
                        continue
                    sn = str(r[0])
                    series[sn] = {
                        "image_count": (int(r[1]) if r[1] is not None else None),
                        "thumbnail_path": (str(r[2]) if r[2] is not None else ""),
                    }
            except Exception:
                pass
    except Exception:
        pass
    return number_of_series, series


def build_local_manifest(
    study_uid: str,
    *,
    db_number_of_series: Optional[int] = None,
    db_series: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build the local manifest for ``study_uid`` from DB (hint) + disk (truth).

    Pass ``db_number_of_series`` / ``db_series`` to skip the DB read (tests, or a
    caller that already has the facts); otherwise they are fetched best-effort.
    ``db_series`` maps ``series_number -> {"image_count", "thumbnail_path"}``.
    """
    study_uid = str(study_uid or "").strip()
    study_dir = SOURCE_PATH / study_uid
    try:
        study_dir_exists = study_dir.exists()
    except OSError:
        study_dir_exists = False

    if db_series is None and db_number_of_series is None:
        db_number_of_series, db_series = _fetch_db_facts(study_uid)
    db_series = db_series or {}

    disk = _disk_series(study_dir)
    all_sn = set(db_series.keys()) | set(disk.keys())

    series: Dict[str, Dict[str, Any]] = {}
    for sn in all_sn:
        db_info = db_series.get(sn) or {}
        db_count = db_info.get("image_count")
        disk_count = int(disk.get(sn, 0))
        thumb = THUMBNAIL_PATH / study_uid / f"{sn}.png"
        try:
            thumb_exists = thumb.exists()
        except OSError:
            thumb_exists = False
        complete: Optional[bool] = None
        if isinstance(db_count, int) and db_count > 0:
            complete = disk_count >= db_count
        series[sn] = {
            "db_image_count": db_count,
            "disk_instance_count": disk_count,
            "series_dir": str(study_dir / sn),
            "series_dir_exists": disk_count > 0,
            "thumbnail_path": str(thumb),
            "thumbnail_exists": thumb_exists,
            "complete": complete,
        }

    disk_series_count = sum(1 for v in series.values() if v["disk_instance_count"] > 0)
    thumb_only = sum(
        1 for v in series.values()
        if v["disk_instance_count"] == 0 and v["thumbnail_exists"]
    )
    return {
        "study_uid": study_uid,
        "study_dir": str(study_dir),
        "study_dir_exists": study_dir_exists,
        "db_number_of_series": db_number_of_series,
        "series": series,
        "disk_series_count": disk_series_count,
        "thumbnail_only_series_count": thumb_only,
        "last_checked": _now_iso(),
    }


def _has_proven_partial(manifest: Dict[str, Any]) -> bool:
    """True if any series' on-disk count is below its KNOWN db image_count."""
    for v in manifest["series"].values():
        if v["complete"] is False:
            return True
    return False


def local_state(manifest: Dict[str, Any]) -> str:
    """Derive the brief's study state from the local manifest (disk-first)."""
    disk = manifest["disk_series_count"]
    expected = manifest["db_number_of_series"]
    if disk == 0:
        if manifest["thumbnail_only_series_count"] > 0:
            return STATE_THUMBNAIL_ONLY
        # The DB knows this study (expected series > 0) but no DICOM on disk ->
        # cleared / lost -> stale (must NOT be shown as downloaded).
        if isinstance(expected, int) and expected > 0:
            return STATE_STALE
        return STATE_NOT_DOWNLOADED
    if isinstance(expected, int) and expected > 0 and disk < expected:
        return STATE_PARTIAL
    if _has_proven_partial(manifest):
        return STATE_PARTIAL
    return STATE_DOWNLOADED


def evaluate_sync(
    study_uid: str,
    server_series: Optional[List[Dict[str, Any]]] = None,
    *,
    db_number_of_series: Optional[int] = None,
    db_series: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Local manifest + (optional) local-vs-server comparison — a pure decision.

    ``server_series``: optional list of ``{"series_number", "image_count"}`` from
    the server's study-info. When provided, the result lists what is missing:
      * ``missing_series``      — server series with no finished files on disk
      * ``partial_series``      — present but on-disk count < server image_count
      * ``missing_thumbnails``  — series with DICOM on disk but no thumbnail png
      * ``up_to_date``          — bool (nothing missing) or None if server not given

    NEVER downloads or writes — the caller decides what to do with the result.
    """
    manifest = build_local_manifest(
        study_uid, db_number_of_series=db_number_of_series, db_series=db_series
    )
    state = local_state(manifest)

    missing_thumbnails = sorted(
        (sn for sn, v in manifest["series"].items()
         if v["disk_instance_count"] > 0 and not v["thumbnail_exists"]),
        key=_sn_sort_key,
    )

    decision: Dict[str, Any] = {
        "study_uid": manifest["study_uid"],
        "state": state,
        "manifest": manifest,
        "checked_server": server_series is not None,
        "missing_series": [],
        "partial_series": [],
        "missing_thumbnails": missing_thumbnails,
        "up_to_date": None,
    }

    if server_series is None:
        return decision

    srv: Dict[str, int] = {}
    for s in server_series:
        try:
            sn = s.get("series_number")
        except AttributeError:
            continue
        if sn is None:
            continue
        try:
            cnt = int(s.get("image_count") or 0)
        except (TypeError, ValueError):
            cnt = 0
        srv[str(sn)] = cnt

    missing, partial = [], []
    for sn, cnt in srv.items():
        info = manifest["series"].get(sn)
        disk_count = info["disk_instance_count"] if info else 0
        if disk_count == 0:
            missing.append(sn)
        elif cnt > 0 and disk_count < cnt:
            partial.append(sn)

    decision["missing_series"] = sorted(missing, key=_sn_sort_key)
    decision["partial_series"] = sorted(partial, key=_sn_sort_key)
    decision["up_to_date"] = (
        not missing and not partial and not missing_thumbnails
    )
    return decision
