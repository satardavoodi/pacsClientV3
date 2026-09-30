"""Real Qt authoring controls with synthetic payloads and no clinical imports.

Load the dialog class alone to avoid workstation configuration and database startup.
The unchanged class body, Qt signals, selection, validation and payload are exercised.
"""
import ast
from pathlib import Path
from typing import Any, Dict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from tests.code.education.test_course_importer import temp_env


def test_folder_drop_routes_local_url_and_rejects_remote(dialog_factory, monkeypatch):
    from PySide6.QtCore import QMimeData, QUrl, QPoint, QPointF
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    dialog, _ = dialog_factory()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("dicom_reference"))
    accepted = []
    monkeypatch.setattr(dialog, "_import_dicom_folder", accepted.append)
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/Synthetic/Study")])
    enter = QDragEnterEvent(QPoint(5,5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    dialog.dragEnterEvent(enter)
    assert enter.isAccepted()
    drop = QDropEvent(QPointF(5,5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    dialog.dropEvent(drop)
    assert accepted == ["C:/Synthetic/Study"]
    mime.setUrls([QUrl("https://example.test/study")])
    enter = QDragEnterEvent(QPoint(5,5), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier)
    dialog.dragEnterEvent(enter)
    assert not enter.isAccepted()


def test_new_folder_payload_can_be_saved_without_patient_database_link(dialog_factory):
    dialog, messages = dialog_factory()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("dicom_reference"))
    dialog.name_input.setText("Teaching study")
    dialog.content_type = "dicom"
    dialog.content_data = {"path": "synthetic-folder", "study_uid": "1.2.3"}
    dialog._save()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert dialog.get_payload()["content_type"] == "dicom"
    messages.warning.assert_not_called()


def test_folder_worker_result_replaces_old_database_reference(dialog_factory, temp_env, tmp_path):
    from tests.code.education.test_course_importer import _write_dicom
    from PySide6.QtTest import QTest
    folder = tmp_path / "study"
    _write_dicom(folder / "image.dcm", study_uid="1.2.3", series_uid="1.2.3.1", series_number=1)
    dialog, _ = dialog_factory("dicom_series", {"name": "Example", "study_uid": "1.2.9", "patient_id": "old", "series_number": 9})
    dialog._import_dicom_folder(str(folder))
    for _ in range(300):
        QtWidgets.QApplication.processEvents()
        if dialog._asset_worker is None:
            break
        QTest.qWait(10)
    assert dialog._asset_worker is None
    dialog._save()
    payload = dialog.get_payload()
    assert payload["content_type"] == "dicom"
    assert payload["content_data"]["study_uid"] == "1.2.3"
    assert "patient_id" not in payload["content_data"]
    assert "series_number" not in payload["content_data"]
    assert Path(payload["content_data"]["path"]).is_dir()


def test_name_option_applied_when_selected_after_source(dialog_factory, temp_env, tmp_path):
    from tests.code.education.test_authoring_previews import _pixels
    from PySide6.QtTest import QTest
    import pydicom
    source = tmp_path / "original" / "one.dcm"
    _pixels(source)
    dialog, _ = dialog_factory("dicom", {"name": "Lesson", "path": str(source.parent), "study_uid": "1.2.3"})
    dialog.replace_patient_name.setChecked(True)
    dialog.patient_alias.setText("Teaching^Example")
    dialog._save()
    for _ in range(300):
        QtWidgets.QApplication.processEvents()
        if dialog._asset_worker is None:
            break
        QTest.qWait(10)
    assert dialog.result() == QtWidgets.QDialog.Accepted
    result = dialog.get_payload()["content_data"]
    assert result["patient_name_changed"]
    assert str(pydicom.dcmread(next(Path(result["path"]).rglob("*.dcm"))).PatientName) == "Teaching^Example"
    assert str(pydicom.dcmread(source).PatientName) == "Original^Synthetic"


@pytest.fixture(scope="module")
def app():
    instance = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield instance


@pytest.fixture
def dialog_factory(app):
    path = Path(__file__).resolve().parents[3] / "modules/education/education_module_redesigned.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ItemMetaDialog")
    messages = SimpleNamespace(warning=Mock(), critical=Mock())
    namespace = {name: getattr(QtWidgets, name) for name in dir(QtWidgets)}
    namespace.update(Dict=Dict, Any=Any, Qt=Qt, QMessageBox=messages,
                     _retint_widget_tree=lambda *a: None,
                     get_theme_manager=lambda: SimpleNamespace(current_theme=lambda: {}))
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    dialogs = []

    def make(content_type=None, data=None):
        existing = {"content_type": content_type, "content_data": data} if content_type else None
        dialog = namespace["ItemMetaDialog"](7, existing)
        dialogs.append(dialog)
        return dialog, messages

    yield make
    for dialog in dialogs:
        dialog.close()
        dialog.deleteLater()
    app.processEvents()


def test_text_can_be_authored_without_a_file(dialog_factory):
    dialog, messages = dialog_factory()
    index = dialog.type_combo.findData("text")
    assert index >= 0, "Build Course must author text already supported by playback"
    dialog.type_combo.setCurrentIndex(index)
    dialog.name_input.setText("Learning objectives")
    dialog.text_input.setPlainText("Identify a teaching point.\nExplain the reasoning.")
    dialog._save()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert dialog.get_payload()["content_data"]["text"].startswith("Identify")
    assert dialog.get_payload()["content_type"] == "text"
    messages.warning.assert_not_called()


@pytest.mark.parametrize("content_type,data", [
    ("image", {"path": "synthetic.png"}),
    ("audio", {"path": "synthetic.wav"}),
    ("pdf", {"path": "synthetic.pdf"}),
    ("dicom_series", {"study_uid": "synthetic-study", "patient_id": "synthetic-patient", "series_number": 0}),
])
def test_type_switch_requires_a_new_source(dialog_factory, content_type, data):
    dialog, messages = dialog_factory(content_type, {"name": "Example", **data})
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("video"))
    dialog._save()
    assert dialog.result() != QtWidgets.QDialog.Accepted
    assert not dialog.source_input.text()
    assert not any(key in dialog.content_data for key in ("path", "study_uid", "patient_id", "series_number"))
    messages.warning.assert_called_once()


@pytest.mark.parametrize("content_type,data", [
    ("image", {"path": "synthetic.png"}),
    ("audio", {"path": "synthetic.wav"}),
    ("pdf", {"path": "synthetic.pdf"}),
    ("text", {"text": "First line\nSecond line"}),
    ("dicom", {"path": "synthetic-study-folder", "study_uid": "synthetic-study"}),
    ("dicom_series", {"study_uid": "synthetic-study", "patient_id": "synthetic-patient", "series_number": 0}),
    ("document", {"path": "synthetic.docx"}),
    ("future_type", {"path": "synthetic.dat", "extension_metadata": {"version": 2}}),
])
def test_existing_items_round_trip_without_relabeling(dialog_factory, content_type, data):
    original = {"name": "Original", "description": "Teaching point", "provenance": "synthetic", **data}
    dialog, messages = dialog_factory(content_type, original)
    dialog.name_input.setText("Revised")
    dialog._save()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert dialog.get_payload() == {"content_type": content_type, "content_data": {**original, "name": "Revised"}}
    assert original["name"] == "Original"
    messages.warning.assert_not_called()


def test_empty_text_is_not_accepted(dialog_factory):
    dialog, messages = dialog_factory("text", {"name": "Notes", "text": "   "})
    dialog._save()
    assert dialog.result() != QtWidgets.QDialog.Accepted
    messages.warning.assert_called_once()


def test_switch_away_and_back_does_not_restore_old_source(dialog_factory):
    dialog, _ = dialog_factory("image", {"name": "Image", "path": "synthetic.png"})
    original = dialog.type_combo.currentIndex()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("audio"))
    dialog.type_combo.setCurrentIndex(original)
    dialog._save()
    assert dialog.result() != QtWidgets.QDialog.Accepted


def test_cancel_does_not_mutate_original_payload(dialog_factory):
    original = {"name": "Original", "path": "synthetic.png"}
    dialog, _ = dialog_factory("image", original)
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("audio"))
    dialog.reject()
    assert original == {"name": "Original", "path": "synthetic.png"}


@pytest.mark.parametrize("mode,expected", [("study", "dicom_study"), ("series", "dicom_series")])
def test_dicom_picker_keeps_persisted_reference_types(dialog_factory, monkeypatch, mode, expected):
    dialog, _ = dialog_factory()
    selected = dict(study_uid="synthetic-study", patient_id="synthetic-patient", mode=mode, series_number=0)
    picker = SimpleNamespace(exec=lambda: QtWidgets.QDialog.Accepted, get_selected_study=lambda: selected)
    monkeypatch.setitem(dialog._pick_source.__func__.__globals__, "StudyPickerDialog", lambda *a: picker)
    dialog.name_input.setText("Teaching study")
    dialog._pick_source()
    dialog._save()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    assert dialog.get_payload()["content_type"] == expected
    assert dialog.content_data["study_uid"] == "synthetic-study"
    assert ("series_number" in dialog.content_data) == (mode == "series")


def test_authored_text_survives_storage_and_actual_viewer_rendering(dialog_factory, temp_env):
    import html
    from modules.education import course_database as db

    dialog, _ = dialog_factory()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("text"))
    dialog.name_input.setText("Question <1>")
    dialog.text_input.setPlainText("Observe <evidence>.\nExplain & compare.")
    dialog._save()
    assert dialog.result() == QtWidgets.QDialog.Accepted
    course_pk = db.insert_course(name="Synthetic lesson", author="Test", is_my_course=True)
    slide_pk = db.insert_slide(course_pk, 1, title="Question")
    db.insert_slide_content(slide_pk, content_order=1, **dialog.get_payload())
    stored = db.get_course_with_slides(course_pk)["slides"][0]["content"][0]
    assert stored["content_type"] == "text"

    path = Path(db.__file__).with_name("educational_patient_viewer_widget.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_show_text")
    namespace = {"Dict": Dict, "Any": Any, "_html": html}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    text = QtWidgets.QTextBrowser()
    stack = QtWidgets.QStackedWidget()
    stack.addWidget(text)
    viewer = SimpleNamespace(_stop_media_playback=Mock(), media_text=text, media_stack=stack,
                             media_text_page=text, _set_media_controls=Mock())
    namespace["_show_text"](viewer, stored["content_data"])
    assert text.toPlainText() == "Question <1>\nObserve <evidence>.\nExplain & compare."
    viewer._set_media_controls.assert_called_once_with("text")
    stack.close()
    stack.deleteLater()


def test_dialog_import_waits_for_worker_and_preserves_cancel(dialog_factory, monkeypatch, app):
    import time
    import threading
    from PySide6.QtCore import QThread
    from PySide6.QtTest import QTest
    from modules.education import course_database as db

    gate = threading.Event()
    threads = []
    def copy(*args):
        threads.append(QThread.currentThread() == app.thread())
        gate.wait(2)
        return "synthetic-copy.png"
    monkeypatch.setattr(db, "save_course_asset", copy)
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *a: ("synthetic.png", ""))
    dialog, _ = dialog_factory()
    dialog.type_combo.setCurrentIndex(dialog.type_combo.findData("image"))
    dialog._pick_source()
    worker = dialog._asset_worker
    dialog.reject()
    assert dialog._asset_worker is worker
    gate.set()
    assert worker.wait(4000)
    deadline = time.monotonic() + 3
    while dialog._asset_worker is not None and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(5)
    assert dialog._asset_worker is None
    assert threads == [False]
    assert dialog.result() == QtWidgets.QDialog.Rejected
    assert "path" not in dialog.content_data
