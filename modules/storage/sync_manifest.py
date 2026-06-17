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
import os
import threading
import time
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


# ── Pixel-presence verification (single-source-of-truth, 2026-06-16) ─────────
# build_local_manifest counts FINISHED .dcm files; it does not look inside them.
# A header-only stub (intact header, EMPTY PixelData — observed: 46472 DX) is a
# finished .dcm, so it counts toward completeness: the study reads "Downloaded",
# resync reports "no change", and the open path skips download — while the image
# cannot render. This optional pass treats a pixel-less IMAGE stub as NOT a
# finished instance, so the EXISTING missing/partial detection (used by BOTH the
# open-skip and the resync decisions) catches it. Staged + reversible:
#   AIPACS_SYNC_VERIFY_PIXELS = 0/off (default)  -> no scan, no behaviour change
#                             | log/observe       -> scan + log [STATE_INCONSISTENCY] only
#                             | 1/on/enforce       -> also exclude stubs from the count
# Bounded: only files below _STUB_PROBE_MAX_BYTES are parsed (a real image is far
# larger), so a normal series of full images pays only a size stat per file.
# Default flipped to 'enforce' (2026-06-16, activation): the single disk-first
# authority now actively excludes pixel-less stubs so badge/open/resync report
# honest completeness (no false-green). Revert with AIPACS_SYNC_VERIFY_PIXELS=0
# (off) or =observe (log-only). Safe: the stub predicate is precise (only <32 KB
# files parsed; only Rows&Columns&BitsAllocated + empty PixelData flagged → no
# false positives on real images) and the verdict is read-only.
_SYNC_VERIFY_MODE = os.getenv("AIPACS_SYNC_VERIFY_PIXELS", "enforce").strip().lower()
_SYNC_VERIFY_OBSERVE = _SYNC_VERIFY_MODE in (
    "log", "observe", "1", "on", "true", "yes", "enforce",
)
_SYNC_VERIFY_ENFORCE = _SYNC_VERIFY_MODE in ("1", "on", "true", "yes", "enforce")
_STUB_PROBE_MAX_BYTES = 32768


def _pixelless_stub_count(series_dir: Path) -> int:
    """Count finished ``.dcm`` files in ``series_dir`` that are header-only image
    stubs — they DECLARE image pixels (Rows & Columns & BitsAllocated) but carry
    an empty/absent PixelData element. Bounded + precise: only files below
    ``_STUB_PROBE_MAX_BYTES`` are parsed (a real image is far larger), and an
    object with no Rows/Columns (SR/PDF/PR) is never counted. Never raises."""
    stubs = 0
    try:
        import pydicom
        for f in series_dir.iterdir():
            try:
                if not (f.is_file() and f.suffix.lower() == _DICOM_EXT):
                    continue
                if f.stat().st_size >= _STUB_PROBE_MAX_BYTES:
                    continue  # a real image — far larger than any header-only stub
                ds = pydicom.dcmread(str(f), force=True)
                declares_image = (
                    bool(getattr(ds, "Rows", None))
                    and bool(getattr(ds, "Columns", None))
                    and bool(getattr(ds, "BitsAllocated", None))
                )
                if declares_image and not bool(ds.get("PixelData", None)):
                    stubs += 1
            except Exception:
                continue
    except Exception:
        return 0
    return stubs


# ── Study-state verdict cache (Phase 1, smoothness, 2026-06-16) ──────────────
# The disk-first manifest is re-derived independently by several readers (UI
# badge, open-skip, resync, DM) for the SAME study within a short window — the
# redundant disk scans are both a state-fragmentation source AND a perf cost.
# This memoizes the manifest per study, keyed by a CHEAP disk signature (series
# sub-dir mtimes + DB facts) that auto-invalidates the instant files are added /
# removed (incl. by the download subprocess — mtime is cross-process), with a
# short TTL backstop. PURE memo: the verdict value is identical; it is only
# recomputed when disk/DB actually change. Disable with AIPACS_STUDY_STATE_CACHE=0;
# invalidate explicitly via invalidate_study_state() on download/delete events.
_MANIFEST_CACHE_ENABLED = (os.getenv("AIPACS_STUDY_STATE_CACHE", "1") or "1").strip() != "0"
try:
    _MANIFEST_CACHE_TTL = max(1.0, float(os.getenv("AIPACS_STUDY_STATE_CACHE_TTL_S", "30") or "30"))
except (TypeError, ValueError):
    _MANIFEST_CACHE_TTL = 30.0
_MANIFEST_CACHE_MAX = 256
_MANIFEST_CACHE: Dict[str, Any] = {}
_MANIFEST_CACHE_LOCK = threading.Lock()


def _disk_signature(study_dir: Path, db_number_of_series, db_series) -> tuple:
    """Cheap change-detector for ``study_dir``: series sub-dir names + mtimes
    (a directory's mtime bumps when a .dcm is added/removed, incl. from the
    download subprocess) plus the DB facts that affect completeness. Far cheaper
    than the full per-series .dcm count, so a cache HIT costs only this; any real
    change (download / delete) flips it and forces a fresh scan."""
    try:
        parts = tuple(sorted(
            (c.name, c.stat().st_mtime_ns)
            for c in study_dir.iterdir() if c.is_dir()
        ))
    except (OSError, ValueError):
        parts = None
    db_sig = (
        db_number_of_series,
        tuple(sorted((str(k), (v or {}).get("image_count"))
                     for k, v in (db_series or {}).items())),
    )
    return (parts, db_sig)


def invalidate_study_state(study_uid: str) -> None:
    """Drop the cached manifest for ``study_uid`` (call on download-complete /
    delete / server-grow). Safe no-op if absent; never raises."""
    try:
        with _MANIFEST_CACHE_LOCK:
            _MANIFEST_CACHE.pop(str(study_uid or "").strip(), None)
    except Exception:
        pass


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
    """Build the local manifest for ``study_uid`` (DB hint + disk truth).

    Phase-1 verdict cache: memoized per study, keyed by a cheap disk signature,
    so the redundant scans by the several readers (badge / open / resync / DM)
    collapse to one (smoothness) while returning the SAME verdict value. The
    cache auto-invalidates on disk/DB change (+TTL backstop). Disable with
    AIPACS_STUDY_STATE_CACHE=0. NEVER writes; returns a read-only decision.
    """
    study_uid = str(study_uid or "").strip()
    if db_series is None and db_number_of_series is None:
        db_number_of_series, db_series = _fetch_db_facts(study_uid)
    db_series = db_series or {}

    if not (_MANIFEST_CACHE_ENABLED and study_uid):
        return _build_local_manifest_impl(
            study_uid, db_number_of_series=db_number_of_series, db_series=db_series
        )

    study_dir = SOURCE_PATH / study_uid
    sig = None
    try:
        sig = _disk_signature(study_dir, db_number_of_series, db_series)
        _now = time.monotonic()
        with _MANIFEST_CACHE_LOCK:
            ent = _MANIFEST_CACHE.get(study_uid)
            if ent is not None and ent[0] == sig and (_now - ent[1]) < _MANIFEST_CACHE_TTL:
                return ent[2]
    except Exception:
        sig = None

    manifest = _build_local_manifest_impl(
        study_uid, db_number_of_series=db_number_of_series, db_series=db_series
    )
    if sig is not None:
        try:
            with _MANIFEST_CACHE_LOCK:
                if len(_MANIFEST_CACHE) > _MANIFEST_CACHE_MAX:
                    _MANIFEST_CACHE.clear()
                _MANIFEST_CACHE[study_uid] = (sig, time.monotonic(), manifest)
        except Exception:
            pass
    return manifest


def _build_local_manifest_impl(
    study_uid: str,
    *,
    db_number_of_series: Optional[int] = None,
    db_series: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Uncached manifest build (DB hint + disk truth) — see build_local_manifest.

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
        # Pixel-presence verification (single-source-of-truth): a finished .dcm
        # with empty PixelData is not a usable instance. Default-off (no scan).
        # In observe mode it only logs [STATE_INCONSISTENCY]; in enforce mode it
        # excludes stubs from the count so this series reads as partial/missing
        # and the existing open-skip + resync paths re-fetch it.
        eff_disk_count = disk_count
        if _SYNC_VERIFY_OBSERVE and disk_count > 0:
            try:
                _stubs = _pixelless_stub_count(study_dir / sn)
            except Exception:
                _stubs = 0
            if _stubs > 0:
                _would_read_complete = (
                    isinstance(db_count, int) and db_count > 0 and disk_count >= db_count
                )
                logger.warning(
                    "[STATE_INCONSISTENCY] study=%s series=%s disk_files=%d "
                    "pixelless_stubs=%d db_image_count=%s would_read_complete=%s "
                    "enforce=%s — finished file(s) carry no pixel data",
                    study_uid, sn, disk_count, _stubs, db_count,
                    _would_read_complete, _SYNC_VERIFY_ENFORCE,
                )
                if _SYNC_VERIFY_ENFORCE:
                    eff_disk_count = max(0, disk_count - _stubs)
        complete: Optional[bool] = None
        if isinstance(db_count, int) and db_count > 0:
            complete = eff_disk_count >= db_count
        series[sn] = {
            "db_image_count": db_count,
            "disk_instance_count": eff_disk_count,
            "series_dir": str(study_dir / sn),
            "series_dir_exists": eff_disk_count > 0,
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
