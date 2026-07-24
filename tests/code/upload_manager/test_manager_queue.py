"""Offscreen UploadManager queue/control tests (ADR-0009). Needs a QApplication;
run with QT_QPA_PLATFORM=offscreen. Uses a fake transfer (no network/Drive)."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

# Q0 2026-07-14: these tests start a real `UploadManager` worker QThread that, under the
# scattered `-n auto` distribution, outlives the test and contaminates the next one through the
# shared `store_mod._STORE` global. The failure is NOT in the call phase, so an `xfail`
# quarantine cannot convert it — so the module is marked `flaky_parallel` and runs SERIALLY
# (`run_test.ps1`'s second pass), where it is deterministic. Real fix = drain the worker in the
# fixture (a naive drain added teardown errors; needs care). Tracked as test-isolation debt.
pytestmark = pytest.mark.flaky_parallel

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication

from modules.upload_manager.core.enums import UploadStatus
from modules.upload_manager.core.models import UploadJob
from modules.upload_manager.manager import UploadManager
from modules.upload_manager.state import store as store_mod


@pytest.fixture(autouse=True)
def _app():
    app = QApplication.instance() or QApplication([])
    # fresh store per test
    store_mod._STORE = None
    # Drain every UploadManager built during the test. Each manager starts a real
    # UploadWorker QThread; a running QThread destroyed at teardown/process-exit makes
    # Qt __fastfail (native exit 0xC0000409) — this was the flaky_parallel native crash,
    # and a worker outliving the test also contaminated the next one via the shared
    # store_mod._STORE global. shutdown() cooperatively cancels the active upload and
    # JOINS the worker (synchronous wait; no event-pump that could re-fire notifications).
    _created: list = []
    _orig_init = UploadManager.__init__

    def _tracking_init(self, *args, **kwargs):
        _orig_init(self, *args, **kwargs)
        _created.append(self)

    UploadManager.__init__ = _tracking_init
    try:
        yield app
    finally:
        UploadManager.__init__ = _orig_init
        for _mgr in _created:
            try:
                _mgr.shutdown()
            except Exception:
                pass
        store_mod._STORE = None
    return


def _job(jid, transfer):
    return UploadJob(job_id=jid, transfer=transfer, patient_name="P", assigned_consultant="c@x")


def test_enqueue_creates_queued_state():
    mgr = UploadManager()
    done = []
    job = _job("j1", lambda c, p, pr: done.append(1) or "remote-1")
    mgr.enqueue(job)
    st = store_mod.get_state_store().get("j1")
    assert st is not None and st.status in (UploadStatus.QUEUED, UploadStatus.UPLOADING)


def test_remove_completed_keeps_active():
    mgr = UploadManager()
    # nothing active; remove_completed must be a safe no-op
    mgr.remove_completed()
    assert mgr._active is None


def test_retry_only_failed_or_cancelled():
    mgr = UploadManager()
    mgr.enqueue(_job("j1", lambda c, p, pr: "r"))
    # a queued/uploading job cannot be retried
    mgr.retry("j1")
    st = store_mod.get_state_store().get("j1")
    assert st.retry_count == 0
