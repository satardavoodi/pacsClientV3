import threading
import time


def test_visit_status_persistence_does_not_block_the_ui_thread(monkeypatch):
    from PacsClient.pacs.workstation_ui.home_ui.patient_table_widget import PatientTableWidget
    import PacsClient.utils as utils

    called = threading.Event()
    worker_threads = []

    def slow_write(study_uid, status):
        worker_threads.append(threading.get_ident())
        time.sleep(0.20)
        called.set()
        return True

    monkeypatch.setattr(utils, "set_visit_status", slow_write)

    class EmptyTable:
        def rowCount(self):
            return 0

    owner = type("Owner", (), {"results_table": EmptyTable()})()
    ui_thread = threading.get_ident()
    started = time.perf_counter()
    PatientTableWidget.update_visited_status(owner, "synthetic-study", "opened")
    elapsed = time.perf_counter() - started

    assert elapsed < 0.10
    assert called.wait(1.5)
    assert worker_threads == [worker_threads[0]]
    assert worker_threads[0] != ui_thread


def test_visit_status_schema_is_owned_by_startup_migration():
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    schema = (root / "database" / "dicom_db.py").read_text(encoding="utf-8")
    writer = (root / "database" / "manager.py").read_text(encoding="utf-8")

    assert "visit_status" in schema
    body = writer.split("def set_visit_status", 1)[1].split("def ", 1)[0]
    assert "ensure_visit_status_column()" not in body
