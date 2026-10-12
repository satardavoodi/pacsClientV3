"""Presenter navigation regressions without initializing a clinical viewer."""
import ast
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import Mock
from PySide6.QtCore import Qt


def method(name, **namespace):
    path = Path(__file__).resolve().parents[3] / "modules/education/educational_patient_viewer_widget.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = dict(Qt=Qt, QListWidgetItem=object, Dict=Dict, Any=Any, **namespace)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), ns)
    return ns[name]


def test_delayed_video_switch_cannot_replace_newer_selection():
    pending = []
    dispatch = Mock()
    viewer = SimpleNamespace(_current_media_kind="video", _teardown_media=Mock(),
                             _dispatch_item_payload=dispatch, _clear_education_selection=Mock())
    click = method("_on_item_clicked", QTimer=SimpleNamespace(singleShot=lambda delay, fn: pending.append(fn)))
    first = {"content_type": "text", "content_data": {"text": "Old"}}
    second = {"content_type": "text", "content_data": {"text": "Current"}}
    click(viewer, SimpleNamespace(data=lambda role: first))
    viewer._current_media_kind = "text"
    click(viewer, SimpleNamespace(data=lambda role: second))
    for callback in pending:
        callback()
    assert dispatch.call_args.args == (second,)
    assert dispatch.call_count == 1


def test_unavailable_message_replaces_dicom_page_and_old_file():
    viewer = SimpleNamespace(_stop_media_playback=Mock(), media_message=Mock(), media_stack=Mock(),
                             education_content_stack=Mock(), _current_media_path="previous.mp4")
    method("_show_media_message")(viewer, "No items in this slide")
    viewer.education_content_stack.setCurrentIndex.assert_called_once_with(1)
    assert viewer._current_media_path is None


def test_external_resource_does_not_interrupt_presentation_automatically():
    desktop = Mock()
    viewer = SimpleNamespace(_stop_media_playback=Mock(), media_message=Mock(), media_stack=Mock(),
                             _set_media_controls=Mock(), external_resource_button=Mock())
    method("_show_external_resource", Path=Path, QDesktopServices=desktop,
           QUrl=SimpleNamespace(fromLocalFile=lambda path: path))(viewer, "Presentation", "synthetic.pptx")
    desktop.openUrl.assert_not_called()
    assert viewer._current_media_path == "synthetic.pptx"


def dicom_viewer():
    return SimpleNamespace(_stop_media_playback=Mock(), education_content_stack=Mock(),
                           _set_content_header=Mock(), _show_media_message=Mock(),
                           _load_single_series_on_demand=Mock(side_effect=lambda n, **kw: n == 1),
                           _find_first_series_number=Mock(return_value=1), change_series_on_viewer=Mock(),
                           _populate_education_series_rail=Mock(return_value=7),
                           _apply_default_education_layout=Mock(), on_tab_activated=Mock(),
                           switch_right_panel=Mock(), study_uid="previous-study", patient_id="previous-patient")


def test_explicit_missing_series_does_not_show_first_series(tmp_path):
    viewer = dicom_viewer()
    method("_load_dicom_content", Path=Path, QMessageBox=Mock(),
           get_study_source_path=lambda uid: (tmp_path, None))(viewer, "dicom_series",
                    {"study_uid": "synthetic-study", "patient_id": "synthetic-patient", "series_number": 2})
    viewer._find_first_series_number.assert_not_called()
    viewer.change_series_on_viewer.assert_not_called()


def test_missing_study_reference_never_reuses_previous_study(tmp_path):
    viewer = dicom_viewer()
    lookup = Mock(return_value=(tmp_path, None))
    method("_load_dicom_content", Path=Path, QMessageBox=Mock(),
           get_study_source_path=lookup)(viewer, "dicom_study", {})
    lookup.assert_not_called()
    viewer._load_single_series_on_demand.assert_not_called()


def test_blank_dicom_folder_is_not_working_directory():
    viewer = dicom_viewer()
    viewer._resolve_dicom_folder = Mock(return_value=(None, None))
    method("_load_dicom_content", Path=Path, QMessageBox=Mock())(viewer, "dicom", {"path": ""})
    viewer._resolve_dicom_folder.assert_not_called()


def test_explicit_series_resource_waits_for_user_selection(tmp_path):
    viewer = dicom_viewer()
    viewer._load_single_series_on_demand.side_effect = None
    viewer._load_single_series_on_demand.return_value = True
    method("_load_dicom_content", Path=Path, QMessageBox=Mock(),
           get_study_source_path=lambda uid: (tmp_path, None))(viewer, "dicom_series",
                    {"study_uid": "synthetic-study", "patient_id": "synthetic-patient", "series_number": 0})
    viewer.change_series_on_viewer.assert_not_called()
    viewer._load_single_series_on_demand.assert_not_called()
    viewer._populate_education_series_rail.assert_called_once()
    viewer._find_first_series_number.assert_not_called()
    viewer.education_content_stack.setCurrentIndex.assert_called_once_with(0)


def test_course_folder_uses_interactive_switch_not_inactive_sync_loader(tmp_path):
    viewer = dicom_viewer()
    viewer._resolve_dicom_folder = Mock(return_value=(str(tmp_path), 5))
    viewer._ensure_random_ids_in_series = Mock()
    viewer._populate_education_series_rail = Mock(return_value=6)
    viewer._apply_default_education_layout = Mock()
    viewer._fit_education_dicom = Mock()
    viewer.on_tab_activated = Mock()
    method("_load_dicom_content", Path=Path, QMessageBox=Mock(),
           QTimer=Mock())(viewer, "dicom", {"path": str(tmp_path), "study_uid": "synthetic-study", "series_number": 5})
    viewer._load_single_series_on_demand.assert_not_called()
    viewer.change_series_on_viewer.assert_not_called()
    viewer._populate_education_series_rail.assert_called_once()
    viewer.on_tab_activated.assert_called_once()
    viewer._ensure_random_ids_in_series.assert_not_called()

def test_standalone_viewer_visibility_drives_patient_lifecycle():
    from PySide6.QtWidgets import QApplication, QWidget
    app = QApplication.instance() or QApplication([])
    path = Path(__file__).resolve().parents[3] / "modules/education/educational_patient_viewer_widget.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    original = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "EducationalPatientViewerWidget")
    events = [n for n in original.body if isinstance(n, ast.FunctionDef) and n.name in {"showEvent", "hideEvent"}]
    assert len(events) == 2
    class Host(QWidget):
        active = False
        def on_tab_activated(self):self.active = True
        def on_tab_deactivated(self):self.active = False
    cls = ast.ClassDef(name="EducationHost", bases=[ast.Name(id="Host", ctx=ast.Load())], keywords=[], body=events, decorator_list=[])
    ns = {"Host": Host}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[])),str(path),"exec"),ns)
    viewer = ns["EducationHost"]()
    viewer.show();app.processEvents();assert viewer.active
    viewer.hide();app.processEvents();assert not viewer.active
    viewer.show();app.processEvents();assert viewer.active
    viewer.close()


def test_empty_resource_retires_previous_selection():
    viewer = SimpleNamespace(_item_generation=8, _current_media_kind="text",
        _teardown_media=Mock(), _clear_education_selection=Mock(),
        _dispatch_item_payload=Mock())
    method("_on_item_clicked")(viewer, SimpleNamespace(data=lambda role: None))
    assert viewer._item_generation == 9
    viewer._clear_education_selection.assert_called_once()
    viewer._dispatch_item_payload.assert_not_called()


def test_selection_reset_retires_rail_and_dicom_requests_before_blank():
    card = Mock()
    grid = Mock()
    grid.count.side_effect = [1, 0]
    grid.takeAt.return_value.widget.return_value = card
    controller = SimpleNamespace(_cancel_registry=Mock(),
        _viewer_request_token={0: 4}, lst_nodes_viewer=[object()],
        cleanup_all_viewers=Mock(), selected_widget=object(), _current_layout=(1, 2))
    owner = SimpleNamespace(_show_media_message=Mock(), _set_content_header=Mock(),
        _sidebar_build_task=Mock(), thumbnail_manager=Mock(), thumb_grid=grid,
        viewer_controller=controller, slide_content_frame=Mock(), study_uid="old", patient_id="old",
        import_folder_path="old", lst_thumbnails_data=[object()])
    owner._sidebar_build_task.done.return_value = False
    method("_clear_education_selection")(owner)
    owner._sidebar_build_task.cancel.assert_called_once()
    owner.thumbnail_manager.reset_all_states.assert_called_once()
    owner.slide_content_frame.reset.assert_called_once()
    card.hide.assert_called_once()
    card.deleteLater.assert_called_once()
    controller._cancel_registry.cancel_all.assert_called_once()
    controller.cleanup_all_viewers.assert_called_once()
    assert controller._viewer_request_token == {0: 5}
    assert controller.selected_widget is None
    assert owner.lst_thumbnails_data == []
    assert owner.study_uid == owner.patient_id == owner.import_folder_path == ""
    assert owner._education_rail_identity is None
    owner._show_media_message.assert_called_once_with("No media item selected")


def test_empty_course_clears_previous_presentation():
    owner = SimpleNamespace(slides=[], _item_generation=2,
        _teardown_media=Mock(), _clear_education_selection=Mock(), items_list=Mock())
    method("_set_current_slide")(owner, 0)
    assert owner._item_generation == 3
    owner._clear_education_selection.assert_called_once()
    owner.items_list.clear.assert_called_once()


def test_study_opens_complete_rail_without_loading_first_series(tmp_path):
    viewer = dicom_viewer()
    method("_load_dicom_content", Path=Path, QMessageBox=Mock(),
           get_study_source_path=lambda uid: (tmp_path, None))(viewer, "dicom_study",
                    {"study_uid": "synthetic-study"})
    viewer._find_first_series_number.assert_not_called()
    viewer._load_single_series_on_demand.assert_not_called()
    viewer.change_series_on_viewer.assert_not_called()
    viewer._populate_education_series_rail.assert_called_once()
    viewer.education_content_stack.setCurrentIndex.assert_called_once_with(0)
