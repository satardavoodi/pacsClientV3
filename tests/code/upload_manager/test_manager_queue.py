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
    yield app


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
