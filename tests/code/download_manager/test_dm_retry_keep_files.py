"""DM-R1 guard tests: a series retry must NOT wipe the series folder.

Root cause under test (patient 53346, 2026-08-05, download_diagnostics.log):
`_bg_series_retry` deleted the whole series folder whenever
existing_count >= expected_count, where expected_count came from the STALE
in-memory task. For a live/growing study the retry fires precisely because the
server count grew past that snapshot, so the check inverted into "wipe the
complete series and re-download all of it" — five consecutive full re-transfers
of series 203 (~185 MB for a 37 MB series), plus a WinError-32 race deleting
files the viewer held open.

Report: docs/reports/DM_53346_DELAY_AND_SERIES_203_REDOWNLOAD_2026-08-05.md
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.download_manager.ui.widget import _dm_retry
from modules.download_manager.core.enums import DownloadPriority, DownloadStatus  # noqa: F401

STUDY = "1.2.840.1.99.1.47.1.test.dmr1"
SERIES_NUM = "203"
SERIES_UID = "1.2.840.1.99.1.47.2.test.dmr1.203"


# ---------------------------------------------------------------------------
# flag semantics
# ---------------------------------------------------------------------------

def test_keep_files_flag_defaults_on():
    src = (PROJECT_ROOT / "modules" / "download_manager" / "ui" / "widget" / "_dm_retry.py").read_text(
        encoding="utf-8"
    )
    assert 'os.environ.get("AIPACS_DM_RETRY_KEEP_FILES", "1")' in src, (
        "DM-R1 must default ON; the wipe path is opt-in via the kill switch"
    )
    assert _dm_retry._DM_RETRY_KEEP_FILES is True


def test_no_production_caller_passes_force_clean_true():
    """Every auto/viewer retry is a fetch intent; only an explicit future
    'wipe and re-download' UI action may pass force_clean=True."""
    import re

    offenders = []
    for base in (PROJECT_ROOT / "modules", PROJECT_ROOT / "PacsClient"):
        for py in base.rglob("*.py"):
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if re.search(r"_on_series_retry\([^)]*force_clean\s*=\s*True", text):
                offenders.append(str(py.relative_to(PROJECT_ROOT)))
    assert offenders == [], f"unexpected force_clean=True callers: {offenders}"


# ---------------------------------------------------------------------------
# behavioural harness — run the real _on_series_retry with the bg job inline
# ---------------------------------------------------------------------------

@dataclass
class _Task:
    study_uid: str = STUDY
    series_list: list = field(default_factory=list)


class _StateStore:
    def __init__(self, state):
        self._state = state
        self.updates = []

    def get(self, uid):
        return self._state

    def update(self, uid, **kw):
        self.updates.append(kw)

    def _notify_observers(self, *a, **k):
        pass


class _Widget(_dm_retry._DMRetryMixin):
    def __init__(self, task, state):
        self._tasks = {STUDY: task}
        self.state_store = _StateStore(state)
        self.worker_pool = SimpleNamespace(
            get_active_count=lambda: 0,
            get_all_workers=lambda: [],
        )
        self.intent_coordinator = SimpleNamespace(
            request_critical_series=lambda *a, **k: True,
            request_study_priority=lambda *a, **k: True,
        )
        self._selected_study_uid = None
        self.worker_started = []

    # collaborators the retry path calls
    def refresh_table_order(self):
        pass

    def _pause_all_active_downloads(self):
        pass

    def _worker_is_active_for_study(self, uid):
        return False

    def _write_critical_intent_file(self, uid, num):
        return True

    def _start_download_worker(self, uid):
        self.worker_started.append(uid)
        return True

    def _start_next_pending(self):
        pass

    def _update_button_states(self, state):
        pass

    def _update_details_panel(self, uid):
        pass

    def _reconstruct_task_from_database(self, uid):
        return None


def _make_state():
    return SimpleNamespace(
        status=DownloadStatus.COMPLETED,
        completed_series=[SERIES_NUM],
        failed_series=[],
        skipped_series=[],
        current_series_number=None,
        current_series=None,
        error_message=None,
        is_auto_paused=False,
    )


def _make_series_dir(tmp_path, n_files):
    sdir = tmp_path / STUDY / SERIES_NUM
    sdir.mkdir(parents=True)
    for i in range(1, n_files + 1):
        (sdir / f"Instance_{i:04d}.dcm").write_bytes(b"x" * 600)
    return sdir


def _run_retry(tmp_path, monkeypatch, *, n_files, expected, force_clean=False):
    """Drive the REAL _on_series_retry with the background job run inline."""
    # bg job runs synchronously on this thread
    monkeypatch.setattr(_dm_retry, "_retry_bg_submit", lambda fn: fn())
    # the deferred main-thread continuation must not fire the worker machinery
    monkeypatch.setattr(
        _dm_retry, "QTimer", SimpleNamespace(singleShot=lambda _d, _cb: None)
    )
    # point the storage root at tmp
    import PacsClient.utils.config as cfg
    monkeypatch.setattr(cfg, "SOURCE_PATH", str(tmp_path), raising=False)

    task = _Task(series_list=[
        SimpleNamespace(series_number=SERIES_NUM, series_uid=SERIES_UID,
                        image_count=expected),
    ])
    widget = _Widget(task, _make_state())
    sdir = _make_series_dir(tmp_path, n_files)

    widget._on_series_retry(STUDY, SERIES_NUM, SERIES_UID, force_clean=force_clean)
    return sdir


def test_auto_retry_keeps_a_complete_looking_series(tmp_path, monkeypatch):
    """THE regression: disk == stale-expected must NOT be wiped on auto retry."""
    sdir = _run_retry(tmp_path, monkeypatch, n_files=71, expected=71)
    remaining = sorted(p.name for p in sdir.glob("*.dcm"))
    assert len(remaining) == 71, (
        "auto retry deleted a complete-looking series — this is the exact "
        "growing-study wipe that re-transferred series 203 five times"
    )


def test_auto_retry_keeps_files_when_disk_exceeds_stale_expected(tmp_path, monkeypatch):
    sdir = _run_retry(tmp_path, monkeypatch, n_files=80, expected=71)
    assert len(list(sdir.glob("*.dcm"))) == 80


def test_incremental_resume_branch_unchanged(tmp_path, monkeypatch):
    """disk < expected always kept files; must still hold."""
    sdir = _run_retry(tmp_path, monkeypatch, n_files=30, expected=71)
    assert len(list(sdir.glob("*.dcm"))) == 30


def test_force_clean_still_wipes(tmp_path, monkeypatch):
    """The explicit escape hatch must keep working for a future wipe action."""
    sdir = _run_retry(tmp_path, monkeypatch, n_files=71, expected=71, force_clean=True)
    assert not sdir.exists(), "force_clean=True must delete the series folder"


def test_kill_switch_restores_legacy_wipe(tmp_path, monkeypatch):
    """AIPACS_DM_RETRY_KEEP_FILES=0 must reproduce the pre-DM-R1 behaviour."""
    monkeypatch.setattr(_dm_retry, "_DM_RETRY_KEEP_FILES", False)
    sdir = _run_retry(tmp_path, monkeypatch, n_files=71, expected=71)
    assert not sdir.exists(), "legacy mode must wipe when disk >= expected"


def test_retry_still_restarts_the_worker(tmp_path, monkeypatch):
    """The no-wipe branch must not break the retry's actual purpose."""
    monkeypatch.setattr(_dm_retry, "_retry_bg_submit", lambda fn: fn())
    fired = []
    monkeypatch.setattr(
        _dm_retry, "QTimer",
        SimpleNamespace(singleShot=lambda _d, cb: fired.append(cb)),
    )
    import PacsClient.utils.config as cfg
    monkeypatch.setattr(cfg, "SOURCE_PATH", str(tmp_path), raising=False)

    task = _Task(series_list=[
        SimpleNamespace(series_number=SERIES_NUM, series_uid=SERIES_UID, image_count=71),
    ])
    widget = _Widget(task, _make_state())
    _make_series_dir(tmp_path, 71)

    widget._on_series_retry(STUDY, SERIES_NUM, SERIES_UID)
    # run the deferred main-thread continuation now
    for cb in list(fired):
        cb()
    assert widget.worker_started == [STUDY], (
        "retry must still start the download worker after keeping the files"
    )


# ---------------------------------------------------------------------------
# source pins
# ---------------------------------------------------------------------------

def test_no_wipe_branch_sits_before_the_delete(monkeypatch):
    src = (PROJECT_ROOT / "modules" / "download_manager" / "ui" / "widget" / "_dm_retry.py").read_text(
        encoding="utf-8"
    )
    i_keep = src.index("_DM_RETRY_KEEP_FILES and not force_clean")
    i_wipe = src.index("shutil.rmtree(series_path)", i_keep)
    assert i_keep < i_wipe, "the DM-R1 guard must gate the rmtree branch"
    block = src[i_keep:i_keep + 1400]
    assert "DM-R1" in block


def test_signature_carries_force_clean_default_false():
    import inspect

    sig = inspect.signature(_dm_retry._DMRetryMixin._on_series_retry)
    p = sig.parameters.get("force_clean")
    assert p is not None and p.default is False
