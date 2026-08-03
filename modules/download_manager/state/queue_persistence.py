"""Crash-durable download-queue persistence (OPT-46, 2026-07-28).

The DM's queue (which studies are PENDING/FAILED, their priority and retry_count) lives ONLY in the
in-memory ``state_store`` — a crash/restart loses it, so a study that was mid-download does not
resume on its own (the user must re-open the patient). The downloaded DATA is already safe (disk +
atomic ``.part``→``os.replace`` + the resume scan), but the *queue* was not durable. The pre-built
``download_progress`` / ``get_incomplete_downloads()`` restore path was never wired.

THIS module makes the queue durable, by design choices that keep it SAFE:

- **Disk, not the DB.** Each ENQUEUED study's minimal re-enqueue spec is written to a tiny JSON file
  at the study's OWN folder — ``<SOURCE_PATH>/<study_uid>/.dm_task.json``. It survives a crash, needs
  NO schema change, and — crucially — adds **no main-thread ``dicom.db`` write**, so it never
  interacts with the OPT-45 busy-timeout path or the download subprocess's WAL writes.
- **Exact replay, no lossy reconstruction.** The spec is the (sanitised) dict ``add_downloads`` was
  called with, so restore re-feeds the SAME proven ``add_downloads(..., start_immediately=False)``
  path — dedup (idempotent), validation, priority and concurrency are all reused, not reimplemented.
- **Self-cleaning + dedup vs disk resume.** The startup scan DELETES the spec of any study already
  COMPLETE on disk and skips it, so stale specs cannot accumulate and a finished study is never
  re-processed; a partially-downloaded study is re-enqueued and the existing resume scan skips its
  completed images (never a re-fetch).
- **Sanitised.** Only the fields ``add_downloads`` needs are stored (study/patient identity + the
  series list with image counts). Pixel/thumbnail bytes are NEVER written.
- **Flag-gated DEFAULT-OFF** (``AIPACS_DM_QUEUE_PERSIST``): it changes startup behaviour (auto-resume
  of interrupted downloads), so it ships opt-in until live-verified, then flips default-on. When off,
  NOTHING is written or scanned — byte-identical legacy.

Pure stdlib (``os``/``json``) so it is fully unit-testable offscreen; never raises into a caller.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

_SPEC_NAME = ".dm_task.json"

# Fields sufficient to rebuild a DownloadTask via add_downloads / _create_task_from_dict.
# NEVER persist thumbnail_data / thumbnail_path (bytes / display-only).
_STUDY_KEYS = (
    "study_uid", "patient_id", "patient_name", "study_date", "study_time",
    "modality", "study_description", "patient_age", "patient_sex",
    "patient_birth_date", "body_part",
)
_SERIES_KEYS = (
    "series_uid", "series_number", "image_count", "series_description",
    "institution_name", "manufacturer", "modality", "body_part_examined",
    "protocol_name",
)


def queue_persist_enabled() -> bool:
    """Default-OFF kill switch. ``AIPACS_DM_QUEUE_PERSIST=1`` enables persistence + restore."""
    return (os.getenv("AIPACS_DM_QUEUE_PERSIST", "0") or "0").strip() == "1"


def _spec_path(study_dir: str) -> str:
    return os.path.join(str(study_dir), _SPEC_NAME)


def sanitize_study_spec(study_dict: dict) -> dict:
    """Keep ONLY the re-enqueue fields (identity + series list w/ counts). Never bytes."""
    out: dict = {}
    for k in _STUDY_KEYS:
        if k in study_dict and study_dict[k] not in (None, ""):
            out[k] = study_dict[k]
    series_out = []
    for s in (study_dict.get("series") or []):
        if not isinstance(s, dict):
            continue
        row = {}
        for k in _SERIES_KEYS:
            v = s.get(k)
            if v not in (None, ""):
                row[k] = v
        if row.get("series_uid"):
            series_out.append(row)
    out["series"] = series_out
    return out


def _expected_image_count(spec: dict) -> int:
    total = 0
    for s in (spec.get("series") or []):
        try:
            total += int(s.get("image_count") or 0)
        except (TypeError, ValueError):
            continue
    return total


def _on_disk_dcm_count(study_dir: str) -> int:
    """Count finished ``.dcm`` across the study's series subfolders (``.part`` excluded)."""
    n = 0
    try:
        with os.scandir(study_dir) as it:
            for sub in it:
                if not sub.is_dir(follow_symlinks=False):
                    continue
                try:
                    with os.scandir(sub.path) as it2:
                        for f in it2:
                            nm = f.name
                            if f.is_file(follow_symlinks=False) and (
                                nm.endswith(".dcm") or nm.endswith(".dicom")
                            ):
                                n += 1
                except OSError:
                    continue
    except OSError:
        return 0
    return n


def study_complete_on_disk(study_dir: str, spec: dict) -> bool:
    """True when the study's expected image count is known (>0) and met on disk.

    Conservative: an UNKNOWN expected count (0) is NOT complete → the study is re-enqueued and the
    normal resume/completeness logic decides. So we never mark-complete-and-skip a study we cannot
    prove is finished.
    """
    expected = _expected_image_count(spec)
    if expected <= 0:
        return False
    return _on_disk_dcm_count(study_dir) >= expected


def persist_task_spec(study_dir, study_dict: dict) -> bool:
    """Write ``<study_dir>/.dm_task.json`` atomically. Best-effort; never raises. No-op when off."""
    if not queue_persist_enabled():
        return False
    try:
        study_dir = str(study_dir)
        if not study_dir:
            return False
        os.makedirs(study_dir, exist_ok=True)
        spec = sanitize_study_spec(study_dict)
        if not spec.get("study_uid") or not spec.get("series"):
            return False  # nothing re-enqueueable
        dst = _spec_path(study_dir)
        tmp = dst + ".part"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(spec, fh, ensure_ascii=False)
        os.replace(tmp, dst)  # atomic — a crash never leaves a torn spec
        return True
    except Exception as exc:  # pragma: no cover - best-effort persistence
        logger.debug("[DM-QUEUE-PERSIST] persist skipped: %s", exc)
        return False


def clear_task_spec(study_dir) -> None:
    """Delete the spec (on completion / explicit removal). Best-effort; never raises."""
    try:
        p = _spec_path(str(study_dir))
        if os.path.isfile(p):
            os.remove(p)
    except Exception:
        pass


def scan_incomplete_task_specs(source_root) -> list:
    """Return the re-enqueue study dicts for all INCOMPLETE persisted studies.

    Walks ``<source_root>/<study_uid>/.dm_task.json``; for each: a study already COMPLETE on disk has
    its spec deleted and is skipped (self-cleaning); an incomplete one is returned for
    ``add_downloads``. Never raises — returns whatever it could read. No-op ([]) when the flag is off.
    """
    if not queue_persist_enabled():
        return []
    out: list = []
    try:
        source_root = str(source_root)
        if not os.path.isdir(source_root):
            return []
        with os.scandir(source_root) as it:
            for entry in it:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                spec_path = _spec_path(entry.path)
                if not os.path.isfile(spec_path):
                    continue
                try:
                    with open(spec_path, "r", encoding="utf-8") as fh:
                        spec = json.load(fh)
                except Exception:
                    continue  # torn/foreign file — leave it, skip
                if not isinstance(spec, dict) or not spec.get("study_uid") or not spec.get("series"):
                    continue
                if study_complete_on_disk(entry.path, spec):
                    clear_task_spec(entry.path)  # done — clean up, do not re-enqueue
                    continue
                out.append(spec)
    except Exception as exc:  # pragma: no cover
        logger.debug("[DM-QUEUE-PERSIST] scan skipped: %s", exc)
    return out
