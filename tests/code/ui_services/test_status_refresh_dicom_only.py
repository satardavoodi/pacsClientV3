"""Guard test for OPT-01 — dicom-only trim of the download-status refresh.

`update_study_download_status` used to POP the local-status flag cache for the row and
rebuild the status widget via `_compute_local_status_flags`, which — on a cache miss —
runs `os.walk(attachments)` + two DB queries (case-of-day, printed) for EVERY row on
EVERY refresh, on the GUI thread (a measured main-thread stall source, KPI 2026-07-01).

A DICOM download completing (or a manual status refresh) cannot change the
attachment/DB-derived flags, so re-deriving them is redundant. The trim refreshes ONLY
the `dicom` flag in place (kept authoritative via `_is_study_downloaded`) and preserves
the cached attachment/DB flags, so the widget rebuild reads a fresh cache entry with no
disk walk / DB query. Kill switch: AIPACS_STATUS_REFRESH_DICOM_ONLY=0 = legacy pop.

House style (mirrors test_status_refresh_chunked.py): source-pins guard the real edit
(no PySide6/QApplication needed) + a mirror-behavioral test reproduces the exact helper
algorithm (constructing a real PatientTableWidget needs a QApplication).
"""

from __future__ import annotations

import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PTW = REPO / "PacsClient" / "pacs" / "workstation_ui" / "home_ui" / "patient_table_widget.py"


def _src() -> str:
    return PTW.read_text(encoding="utf-8", errors="ignore")


# --- source-pins ---------------------------------------------------------------------

def test_flag_retired_trim_unconditional():
    s = _src()
    assert 'os.getenv("AIPACS_STATUS_REFRESH_DICOM_ONLY"' not in s, "flag retired — the dicom-only trim is unconditional now"


def test_helper_defined_and_wired():
    s = _src()
    assert "def _refresh_local_status_dicom_flag(self, cache_key, study_uid) -> bool:" in s
    # call site skips the legacy pop only when the helper handled the refresh
    assert "if not self._refresh_local_status_dicom_flag(cache_key, study_uid):" in s
    assert "self._local_status_cache.pop(cache_key, None)" in s, "legacy fallback must remain"


def test_helper_reads_dicom_from_disk_and_keeps_other_flags():
    s = _src()
    start = s.index("def _refresh_local_status_dicom_flag")
    body = s[start:start + 2600]
    # dicom stays authoritative (re-read from disk), other flags copied not recomputed
    assert "data['dicom'] = bool(self._is_study_downloaded(study_uid))" in body
    assert "data = dict(entry['data'])" in body
    # first-population / missing entry must fall through to the full recompute
    assert "return False" in body


def test_storage_clear_still_full_recomputes():
    s = _src()
    # refresh_download_statuses_local_only must also clear the flag cache so a storage
    # clear stays fully authoritative (not just the DICOM flag).
    start = s.index("def refresh_download_statuses_local_only")
    body = s[start:start + 1800]
    assert "self._local_status_cache.clear()" in body


# --- mirror-behavioral: exact algorithm of _refresh_local_status_dicom_flag -----------

class _Mirror:
    """Standalone re-implementation of the helper (a real widget needs a QApplication).

    ``full_recompute`` counts the times the caller would fall back to the legacy pop +
    ``_compute_local_status_flags`` (the os.walk + DB path we are eliminating)."""

    def __init__(self, enabled: bool = True):
        self._local_status_cache: dict = {}
        self._downloaded: set = set()
        self._enabled = enabled
        self.full_recompute = 0

    def _is_study_downloaded(self, study_uid) -> bool:
        return study_uid in self._downloaded

    def _refresh_local_status_dicom_flag(self, cache_key, study_uid) -> bool:
        try:
            if not self._enabled:
                return False
            entry = self._local_status_cache.get(cache_key)
            if not entry or not isinstance(entry.get("data"), dict):
                return False
            data = dict(entry["data"])
            data["dicom"] = bool(self._is_study_downloaded(study_uid))
            self._local_status_cache[cache_key] = {"data": data, "timestamp": time.time()}
            return True
        except Exception:
            return False

    def apply(self, cache_key, study_uid):
        """Mirror the call site: skip the legacy pop when the helper handled it."""
        if not self._refresh_local_status_dicom_flag(cache_key, study_uid):
            self._local_status_cache.pop(cache_key, None)
            self.full_recompute += 1  # caller would run _compute_local_status_flags


def test_refreshes_dicom_in_place_and_preserves_expensive_flags():
    m = _Mirror(enabled=True)
    key = ("u1", "p1")
    m._local_status_cache[key] = {
        "data": {"dicom": False, "documents": True, "voice": True,
                 "ai": False, "case_of_day": True, "printed": False},
        "timestamp": 0.0,
    }
    m._downloaded.add("u1")  # the study is now downloaded

    m.apply(key, "u1")

    data = m._local_status_cache[key]["data"]
    assert data["dicom"] is True                 # refreshed from disk
    assert data["documents"] is True and data["voice"] is True   # preserved…
    assert data["case_of_day"] is True and data["ai"] is False    # …with NO recompute
    assert m._local_status_cache[key]["timestamp"] > 0.0          # fresh -> cache hit
    assert m.full_recompute == 0                 # the os.walk + DB path never ran


def test_dicom_flag_goes_false_when_files_removed():
    m = _Mirror(enabled=True)
    key = ("u4", "p")
    m._local_status_cache[key] = {"data": {"dicom": True, "documents": True}, "timestamp": 0.0}
    # _downloaded stays empty -> study no longer on disk
    m.apply(key, "u4")
    assert m._local_status_cache[key]["data"]["dicom"] is False   # authoritative
    assert m._local_status_cache[key]["data"]["documents"] is True
    assert m.full_recompute == 0


def test_no_cache_entry_falls_back_to_full_recompute():
    m = _Mirror(enabled=True)
    handled = m._refresh_local_status_dicom_flag(("u2", "p"), "u2")
    assert handled is False          # first population must compute everything
    m.apply(("u2", "p"), "u2")
    assert m.full_recompute == 1     # caller pops -> _compute_local_status_flags runs
