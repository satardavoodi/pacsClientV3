"""Qt-free unit tests for the Upload Manager core models + state store (ADR-0009).

These run without PySide6. Worker/manager tests (which need an offscreen
QApplication) live in test_manager_queue.py.
"""
from modules.upload_manager.core.enums import UploadPriority, UploadStatus
from modules.upload_manager.core.models import UploadJobState
from modules.upload_manager.state.store import UploadStateStore


def test_progress_percent_speed_eta():
    st = UploadJobState(job_id="j1")
    st.note_progress(0, 10, 0, 1000)
    st.note_progress(5, 10, 500, 1000, "patients/x.dcm")
    assert st.uploaded_files == 5 and st.total_files == 10
    assert 49.0 <= st.percent <= 51.0
    assert st.remaining_bytes == 500 and st.remaining_files == 5
    assert st.current_path == "patients/x.dcm"
    assert st.is_active and not st.is_terminal


def test_status_enum_classification():
    assert UploadStatus.QUEUED.is_active and UploadStatus.UPLOADING.is_active
    assert UploadStatus.COMPLETED.is_terminal and UploadStatus.CANCELLED.is_terminal
    assert not UploadStatus.PAUSED.is_active and not UploadStatus.FAILED.is_terminal


def test_store_observer_lifecycle():
    store = UploadStateStore()
    events = []
    store.add_observer(lambda e, jid, s: events.append(e))
    store.create(UploadJobState(job_id="j1", priority=UploadPriority.HIGH))
    store.update("j1", status=UploadStatus.UPLOADING)
    store.touch("j1")
    store.remove("j1")
    assert events == ["created", "updated", "updated", "removed"]
    assert store.get("j1") is None


def test_observer_exception_never_breaks_store():
    store = UploadStateStore()
    store.add_observer(lambda e, jid, s: (_ for _ in ()).throw(RuntimeError("boom")))
    # must not raise
    store.create(UploadJobState(job_id="j1"))
    assert store.get("j1") is not None
