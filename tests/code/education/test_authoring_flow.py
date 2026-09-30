"""Synthetic real-Qt Build Course workflow with isolated persistence."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import Mock

import pytest
from PySide6 import QtWidgets, QtGui, QtCore
from modules.education import course_database as db
from tests.code.education.test_course_importer import temp_env


@pytest.fixture
def builder(temp_env, monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    for name in ("information", "warning", "critical"):
        monkeypatch.setattr(QtWidgets.QMessageBox, name, Mock())
    path = Path(db.__file__).with_name("education_module_redesigned.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "BuildCoursePage")
    ns = dict(vars(db))
    for module in (QtWidgets, QtGui, QtCore):
        ns.update({name: getattr(module, name) for name in dir(module) if not name.startswith("__")})
    ns.update(json=json, Path=Path, List=List, Dict=Dict, Any=Any,
              MODALITIES=["CT", "MRI"], LEVELS=["Basic", "Intermediate", "Advanced", "Expert"],
              BODY_REGIONS=["Chest", "MSK"], _retint_widget_tree=lambda *a: None,
              get_theme_manager=lambda: SimpleNamespace(current_theme=lambda: {}))
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), ns)
    page = ns["BuildCoursePage"]()
    page.title_input.setText("Synthetic lesson")
    page.author_input.setText("Teacher")
    page._create_course_card()
    yield page, ns
    page.close()
    page.deleteLater()
    app.processEvents()
    from modules.education import authoring_thumbnails
    if authoring_thumbnails._pool is not None:
        assert authoring_thumbnails._pool.waitForDone(5000)


def test_back_to_card_updates_same_course_and_keeps_slides(builder):
    page, _ = builder
    original = page.course_pk
    page._add_slide()
    page.title_input.setText("Revised lesson")
    page._create_course_card()
    assert page.course_pk == original
    assert len(db.get_all_courses()) == 1
    assert db.get_course_by_pk(original)["course_name"] == "Revised lesson"
    assert len(db.get_slides_for_course(original)) == 1


def test_add_and_switch_slide_save_pending_text(builder):
    page, _ = builder
    page._add_slide()
    first_pk = page.slides_cache[0]["slide_pk"]
    page.slide_name_input.setText("Question")
    page.slide_desc_input.setPlainText("Notes for the lecturer")
    page._add_slide()
    slides = db.get_slides_for_course(page.course_pk)
    assert slides[0]["slide_title"] == "Question"
    assert slides[0]["slide_notes"] == "Notes for the lecturer"
    page.slide_name_input.setText("Answer")
    page.slides_list.setCurrentRow(0)
    assert db.get_slides_for_course(page.course_pk)[1]["slide_title"] == "Answer"
    assert page.slides_cache[0]["slide_pk"] == first_pk


def test_failed_slide_save_keeps_selection_and_text(builder, monkeypatch):
    page, ns = builder
    page._add_slide()
    page._add_slide()
    page.slide_name_input.setText("Do not lose this")
    monkeypatch.setitem(ns, "update_slide", Mock(side_effect=RuntimeError("Synthetic disk failure")))
    page.slides_list.setCurrentRow(0)
    assert page.slides_list.currentRow() == 1
    assert page.slide_name_input.text() == "Do not lose this"
    QtWidgets.QMessageBox.critical.assert_called_once()


def test_finish_flushes_pending_slide_before_emitting(builder):
    page, _ = builder
    pk = page.course_pk
    page._add_slide()
    page.slide_name_input.setText("Saved on finish")
    delivered = []
    page.course_created.connect(delivered.append)
    page._finish_course_setup()
    assert len(delivered) == 1
    assert db.get_slides_for_course(pk)[0]["slide_title"] == "Saved on finish"


def test_imported_course_metadata_survives_card_edit(builder):
    page, _ = builder
    pk = page.course_pk
    db.update_course(pk, outline=json.dumps({"visibility": "Private", "objectives": ["Reason"]}),
                     modality="MR", tags=["ImportedCustom"], body_regions=["CustomRegion"], level="CustomLevel")
    page.load_course_for_edit(pk)
    page.title_input.setText("Revised")
    page._create_course_card()
    saved = db.get_course_by_pk(pk)
    assert saved["course_name"] == "Revised"
    assert saved["modality"] == "MR"
    assert saved["level"] == "CustomLevel"
    assert "ImportedCustom" in saved["tags"]
    assert json.loads(saved["outline"])["objectives"] == ["Reason"]


def test_item_reorder_failure_is_atomic(builder):
    page, _ = builder
    page._add_slide()
    slide_pk = page.slides_cache[0]["slide_pk"]
    pks = [db.insert_slide_content(slide_pk, "text", i, {"text": str(i)}) for i in (1, 2, 3)]
    page._load_items()
    page.items_list.setCurrentRow(0)
    with db.get_db_connection() as conn:
        conn.execute("CREATE TRIGGER fail_order BEFORE UPDATE OF content_order ON slide_content "
                     "WHEN NEW.content_order = 2 BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        conn.commit()
    page._move_item(1)
    rows = db.get_content_for_slide(slide_pk)
    assert [(r["content_pk"], r["content_order"]) for r in rows] == list(zip(pks, (1, 2, 3)))


def test_preview_uses_current_saved_content(builder):
    page, _ = builder
    page._add_slide()
    pk = page.slides_cache[0]["slide_pk"]
    db.insert_slide_content(pk, "text", 1, {"text": "Lesson"})
    page.slide_name_input.setText("Latest slide title")
    delivered = []
    page.preview_requested.connect(delivered.append)
    page._preview_course()
    assert delivered[0]["slides"][0]["slide_title"] == "Latest slide title"
    assert delivered[0]["slides"][0]["content"][0]["content_data"]["text"] == "Lesson"


def test_empty_draft_is_saved_but_not_presented(builder):
    page, _ = builder
    delivered = []
    page.preview_requested.connect(delivered.append)
    page._preview_course()
    assert not delivered
    assert db.get_course_by_pk(page.course_pk)


def test_existing_downloaded_course_is_editable(builder):
    page, _ = builder
    pk = db.insert_course("Downloaded", is_downloaded=True)
    assert page.load_course_for_edit(pk) is True
    assert page.course_pk == pk


def test_explicitly_locked_course_cannot_open_in_builder(builder):
    page, _ = builder
    pk = db.insert_course("Restricted copy", is_downloaded=True)
    with db.get_db_connection() as conn:
        conn.execute("UPDATE courses SET is_editable=0 WHERE course_pk=?", (pk,))
        conn.commit()
    assert page.load_course_for_edit(pk) is False


def test_course_edit_routes_to_builder(builder):
    page, _ = builder
    path = Path(db.__file__).with_name("education_module_redesigned.py")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EducationModuleRedesigned")
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "on_course_edited")
    ns = {"QMessageBox": QtWidgets.QMessageBox}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    shell = SimpleNamespace(build_page=page, tab_widget=Mock())
    ns["on_course_edited"](shell, {"course_pk": page.course_pk})
    shell.tab_widget.setCurrentWidget.assert_called_once_with(page)


def test_reorder_rejects_items_from_another_slide(builder):
    page, _ = builder
    page._add_slide()
    first = page.slides_cache[0]["slide_pk"]
    local = db.insert_slide_content(first, "text", 1, {"text": "A"})
    page._add_slide()
    second = page.slides_cache[1]["slide_pk"]
    foreign = db.insert_slide_content(second, "text", 1, {"text": "B"})
    with pytest.raises(ValueError):
        db.reorder_slide_content(first, [foreign])
    assert db.get_content_for_slide(first)[0]["content_pk"] == local


def test_cover_import_resumes_preview_for_same_course(builder, tmp_path):
    from PySide6.QtTest import QTest
    import time
    page, _ = builder
    pk = page.course_pk
    page._add_slide()
    db.insert_slide_content(page.slides_cache[0]["slide_pk"], "text", 1, {"text": "Lesson"})
    cover = tmp_path / "synthetic-cover.png"
    cover.write_bytes(b"synthetic asset copy fixture")
    page.cover_image_source = str(cover)
    delivered = []
    page.preview_requested.connect(delivered.append)
    page._preview_course()
    worker = page._cover_worker
    assert worker is not None
    assert page.load_course_for_edit(999) is False
    assert worker.wait(4000)
    deadline = time.monotonic() + 3
    while not delivered and time.monotonic() < deadline:
        QtWidgets.QApplication.processEvents()
        QTest.qWait(5)
    assert len(delivered) == 1 and delivered[0]["course_pk"] == pk
    assert len(db.get_all_courses()) == 1
    copied = Path(delivered[0]["thumbnail_path"])
    assert copied != cover and copied.read_bytes() == cover.read_bytes()


@pytest.mark.parametrize("size", [(1180, 800), (1024, 700)])
def test_slide_workspace_uses_available_height(builder, size):
    page, _ = builder
    page._add_slide()
    page.resize(*size)
    page.show()
    QtWidgets.QApplication.processEvents()
    editor = page.slide_name_input.parentWidget()
    top = editor.mapTo(page, QtCore.QPoint(0, 0)).y()
    assert top <= 160, f"Header consumes {top}px before slide editing"
    assert editor.height() >= page.height() * 0.70
    for button in page.findChildren(QtWidgets.QPushButton):
        if button.isVisible():
            bounds = QtCore.QRect(button.mapTo(page, QtCore.QPoint(0, 0)), button.size())
            assert page.rect().contains(bounds), button.text()


def test_item_actions_share_one_row(builder):
    page, _ = builder
    page.resize(1024,700)
    page.show()
    QtWidgets.QApplication.processEvents()
    assert len({button.y() for button in page.item_action_buttons}) == 1


def test_wide_editor_allocates_space_to_slide_titles(builder):
    page, _ = builder
    page.resize(1860,850)
    page.show()
    QtWidgets.QApplication.processEvents()
    assert page.slides_list.parentWidget().width() >= page.width() * 0.30
    assert page.slides_list.wordWrap()
    assert page.slides_list.textElideMode() == QtCore.Qt.ElideNone

def test_metadata_shares_row_and_header_actions_stay_above_editor(builder):
    page, _ = builder
    page._add_slide()
    page.resize(1500, 800)
    page.show()
    for _ in range(4):
        QtWidgets.QApplication.processEvents()
    name = page.slide_name_input
    description = page.slide_desc_input
    assert name.y() == description.y()
    assert description.x() > name.geometry().right()
    actions_bottom = page.step_actions.mapTo(page, QtCore.QPoint(0, page.step_actions.height())).y()
    editor_top = name.parentWidget().mapTo(page, QtCore.QPoint(0, 0)).y()
    assert actions_bottom < editor_top <= 110
    assert page.items_list.height() + page.authoring_separator.height() + 10 > page.height() * 0.55


def test_course_header_has_visible_full_width_separator(builder):
    page, _ = builder
    page.resize(1500, 800)
    page.show()
    QtWidgets.QApplication.processEvents()
    divider = page.authoring_separator
    assert divider.isVisible() and divider.height() >= 4
    assert divider.width() == page.authoring_splitter.width()
    assert page.step_two_title.geometry().bottom() < divider.y()
    assert divider.geometry().bottom() < page.authoring_splitter.y()
