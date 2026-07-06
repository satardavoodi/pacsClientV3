"""Regression guards: multi-study viewer→DM identity (P0) + DB ownership (P1).

From MULTI_STUDY_MULTI_PATIENT_ID_ARCHITECTURE_REVIEW_2026-06-16. The multi-study
viewer uses synthetic DISPLAY keys (study_slot*1_000_000 + original_series_number).
Those keys leaked to the Download Manager (tab's PRIMARY study_uid + display key),
the coordinator accepted any series_number without membership validation, and the
downloader computed progress totals from a mutable series_list — together a source
of wrong prioritisation, phantom critical-intent files, and inflated counts.

Three defense-in-depth layers (each flag-gated, default ON = fix active):
  L1  coordinator membership validation  (AIPACS_DM_MEMBERSHIP_VALIDATION)
  L2  immutable progress totals          (AIPACS_DM_IMMUTABLE_TOTALS)
  L3  canonical viewer→DM resolver        (AIPACS_DM_CANON_IDENTITY)
Plus P1 DB ownership-reassignment guard  (AIPACS_DB_ENFORCE_OWNER, ENFORCE-by-default since
OPT-18 2026-07-05; =0 restores observe-only).

The source-wiring test runs anywhere. The functional coordinator tests import the
download_manager package (PySide6 + package __init__), so run them on Windows; if a
home-panel suite is collected first the known latent package circular-import can
block collection — run this file (or the download_manager suite) first.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _read(rel: str) -> str:
    return (_REPO_ROOT / rel).read_text(encoding="utf-8", errors="ignore")


# ── source wiring (runs anywhere; catches a stale/missing fix in the build) ──
def test_source_wiring_present():
    coord = _read("modules/download_manager/coordinator/series_intent_coordinator.py")
    assert "_DM_MEMBERSHIP_VALIDATION" in coord
    assert "AIPACS_DM_MEMBERSHIP_VALIDATION" in coord
    assert "CriticalIntentRejected" in coord

    sd = _read("modules/download_manager/download/series_downloader.py")
    assert "_DM_IMMUTABLE_TOTALS" in sd
    assert "_frozen_progress_totals" in sd
    assert "_progress_totals" in sd

    vc = _read("PacsClient/pacs/patient_tab/ui/patient_ui/_vc_load.py")
    assert "_DM_CANON_IDENTITY" in vc
    assert "_resolve_canonical_series_identity" in vc
    # both viewer→DM call sites must route through the resolver
    assert vc.count("_resolve_canonical_series_identity(") >= 2

    db = _read("database/dicom_db.py")
    assert "_DB_ENFORCE_OWNER" in db
    assert "CrossPatientReassignment" in db
    assert "CrossStudyReassignment" in db
    # OPT-18 (2026-07-05): owner-reassignment enforcement is now DEFAULT ON (was
    # observe-only). The kill switch AIPACS_DB_ENFORCE_OWNER=0 restores observe-only.
    assert 'os.environ.get(\n    "AIPACS_DB_ENFORCE_OWNER", "1"' in db or \
        '"AIPACS_DB_ENFORCE_OWNER", "1"' in db, "OPT-18: enforcement must default ON"


# ── functional: coordinator membership validation (L1) — run on Windows ──────
def _coord_and_state(task_series, *, status_name="DOWNLOADING"):
    from modules.download_manager.coordinator import series_intent_coordinator as sic
    from modules.download_manager.core.models import DownloadTask, SeriesInfo
    from modules.download_manager.core.enums import DownloadStatus, DownloadPriority

    state = types.SimpleNamespace(
        status=getattr(DownloadStatus, status_name),
        priority=DownloadPriority.HIGH,
        viewed_series_number=None,
        completed_series=[],
        current_series_number=None,
    )

    class _SS:
        def get(self, _uid):
            return state

        def update(self, _uid, **kw):
            for k, v in kw.items():
                setattr(state, k, v)

    obj = types.SimpleNamespace()
    obj.state_store = _SS()
    obj._tasks = {
        "S": DownloadTask(
            study_uid="S", patient_id="P", patient_name="N", study_date="",
            modality="MR", description="", series_list=task_series,
        )
    }
    obj._intent_writes = []
    obj._write_critical_intent_file = lambda uid, sn: (obj._intent_writes.append((uid, sn)) or True)
    obj.negotiate_priority_change = lambda uid, pri: None
    obj._pause_downloads_for_preemption = lambda uids: None
    obj.request_critical_series = sic.SeriesIntentCoordinator.request_critical_series.__get__(obj)
    return obj, state, SeriesInfo


def _si(uid="", num="1", c=10):
    from modules.download_manager.core.models import SeriesInfo
    return SeriesInfo(series_uid=uid, series_number=num, series_description="d", modality="MR", image_count=c)


def test_reject_nonmember_display_key():
    obj, state, SeriesInfo = _coord_and_state([_si(None, "1", 10), _si(None, "2", 10)])
    # 1000003 is a multi-study display key that exists in NO real series list.
    assert obj.request_critical_series("S", "1000003") is False
    assert state.viewed_series_number is None      # never flipped
    assert obj._intent_writes == []                # no .critical_intent.json


def test_accept_member_by_number():
    obj, state, SeriesInfo = _coord_and_state(
        [_si("U1", "1", 10), _si("U2", "2", 10)], status_name="PENDING"
    )
    assert obj.request_critical_series("S", "2") is True
    assert state.viewed_series_number == "2"


def test_accept_member_by_series_uid_even_if_number_off():
    obj, state, SeriesInfo = _coord_and_state([_si("U1", "1", 10)], status_name="PENDING")
    # number doesn't match but the SeriesInstanceUID does → member.
    assert obj.request_critical_series("S", "999", series_uid="U1") is True


def test_fail_open_when_task_unknown():
    from modules.download_manager.core.enums import DownloadStatus, DownloadPriority
    obj, state, SeriesInfo = _coord_and_state([_si("U1", "1", 10)], status_name="PENDING")
    obj._tasks = {}  # task not yet registered (open/drag race) → cannot prove invalid
    assert obj.request_critical_series("S", "1000003") is True
