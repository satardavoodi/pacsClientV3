from PySide6.QtWidgets import QApplication
from modules.education.study_picker_dialog import StudyPickerDialog
import pytest
from tests.code.education.test_course_importer import temp_env, _write_dicom


def test_flat_folder_import_preserves_bytes_and_series(temp_env, tmp_path):
    from modules.education.dicom_folder_import import import_dicom_folder
    from modules.education.course_database import insert_course
    from pathlib import Path
    folder = tmp_path / "flat"
    for index, series in enumerate((4, 9)):
        _write_dicom(folder / f"file{index}", study_uid="1.2.3", series_uid=f"1.2.3.{series}", series_number=series)
    result = import_dicom_folder(folder, insert_course("Synthetic"))
    target = Path(result["path"])
    assert result["study_uid"] == "1.2.3"
    assert (target / "4" / "00000000.dcm").read_bytes() == (folder / "file0").read_bytes()
    assert (target / "9" / "00000001.dcm").read_bytes() == (folder / "file1").read_bytes()


@pytest.mark.parametrize("second_study,second_series", [("1.2.4", "1.2.4.1"), ("1.2.3", "1.2.3.2")])
def test_ambiguous_folder_is_not_merged(temp_env, tmp_path, second_study, second_series):
    from modules.education.dicom_folder_import import import_dicom_folder
    from modules.education.course_database import insert_course
    folder = tmp_path / "mixed"
    _write_dicom(folder / "a.dcm", study_uid="1.2.3", series_uid="1.2.3.1", series_number=1)
    _write_dicom(folder / "b.dcm", study_uid=second_study, series_uid=second_series, series_number=1)
    with pytest.raises(ValueError):
        import_dicom_folder(folder, insert_course("Synthetic"))


def test_picker_constructs_and_filters_exact_patient_id(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(StudyPickerDialog, "load_studies", lambda self: None)
    picker = StudyPickerDialog()
    from PySide6.QtWidgets import QTableWidgetItem
    picker.studies_table.setRowCount(2)
    picker.studies_table.setItem(0,0,QTableWidgetItem("123"))
    picker.studies_table.setItem(1,0,QTableWidgetItem("1234"))
    picker.search_scope.setCurrentText("Patient ID (exact)")
    picker.search_input.setText("123")
    assert not picker.studies_table.isRowHidden(0)
    assert picker.studies_table.isRowHidden(1)
    picker.close()


def test_study_query_uses_worker_and_finishes_before_close(temp_env, monkeypatch):
    import threading
    from PySide6.QtTest import QTest
    from modules.education import study_picker_dialog as module
    app = QApplication.instance() or QApplication([])
    caller = threading.get_ident()
    threads = []
    connection = module.get_db_connection
    def tracked_connection():
        threads.append(threading.get_ident())
        return connection()
    monkeypatch.setattr(module, "get_db_connection", tracked_connection)
    picker = StudyPickerDialog()
    for _ in range(300):
        app.processEvents()
        if not picker._query_workers:
            break
        QTest.qWait(10)
    assert not picker._query_workers
    assert threads and all(thread != caller for thread in threads)
    picker.close()
