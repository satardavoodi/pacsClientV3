"""Workspace entry must be observational until a function is explicitly selected."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[3]
TOOLBAR = "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py"
MAIN = "modules/ai_imaging/ai_module_ui/ai_mainwindow.py"
IMAGING = "modules/ai_imaging/ai_module_ui/service_tab/imaging_tab.py"


def method(path, name, namespace=None):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8-sig"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = dict(namespace or {})
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, "exec"), scope)
    return scope[name]


@pytest.mark.parametrize("modality,description", [
    ("MG", "Mammography"), ("DX", "Hand"),
    ("MR", "Lumbar spine"), ("MR", "Brain MPRAGE"),
])
def test_toolbar_opens_selected_study_without_picker_or_analysis(monkeypatch, modality, description):
    from modules.ai_imaging import eagle_eye_function_dialog as dialogs
    events = []
    def fail_picker(*args, **kwargs):
        pytest.fail("Function selection happened before entering the workspace")
    monkeypatch.setattr(dialogs, "choose_eagle_eye_function", fail_picker)
    viewer = SimpleNamespace(metadata={"series": {
        "modality": modality, "series_description": description, "study_uid": "selected-study",
    }})
    patient = SimpleNamespace(
        study_uid="primary-study", selected_widget=SimpleNamespace(image_viewer=viewer),
        method_add_new_tab=lambda **kw: events.append(kw),
    )
    toolbar = SimpleNamespace(patient_widget=patient,
        _trigger_eagle_eye_analysis_pipeline=lambda: pytest.fail("Analysis ran during entry"))
    method(TOOLBAR, "_on_ai_analysis_clicked")(toolbar)
    assert len(events) == 1
    assert events[0]["study_uid"] == "selected-study"
    assert events[0]["open_ai_client_tab"] is True


def test_lumbar_first_paint_does_not_start_capture():
    scheduled = []
    capture = lambda: pytest.fail("Capture started without a selected function")
    host = SimpleNamespace(
        patient_widget=SimpleNamespace(on_tab_activated=lambda: None),
        left_sidebar_layout_ui=lambda: None,
        _load_bone_age_feature_if_exists=lambda: None,
        fully_loaded=SimpleNamespace(emit=lambda: None),
        detect_modality=lambda: "MR", eagle_eye_mode="lumbar_mri",
        _eagle_eye_workflow=SimpleNamespace(start_capture=capture),
    )
    method(IMAGING, "_finalize_loading", {
        "QApplication": SimpleNamespace(processEvents=lambda: None),
        "QTimer": SimpleNamespace(singleShot=lambda delay, callback: scheduled.append(callback)),
    })(host)
    assert capture not in scheduled


def test_reopening_brain_workspace_does_not_prompt_again():
    scheduled = []
    host = SimpleNamespace(eagle_eye_mode="brain_mri",
        brain_tab=SimpleNamespace(choose_study_workflow=lambda: None),
        imaging_tab=SimpleNamespace(refresh_mg_ai_results=lambda: False))
    method(MAIN, "refresh_ai_results", {
        "QTimer": SimpleNamespace(singleShot=lambda delay, callback: scheduled.append(callback)),
    })(host)
    assert not scheduled


def test_brain_entry_uses_the_common_imaging_workspace():
    tree = ast.parse((ROOT / MAIN).read_text(encoding="utf-8-sig"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "AiMainWindow")
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    calls = [ast.unparse(n.func) for n in ast.walk(init) if isinstance(n, ast.Call)]
    assert "BrainVolumetryWidget" not in calls, "Brain must be constructed only in its requested popup"
    assert "ImagingToolsTab" in calls


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def workspace(qapp):
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    window = QWidget()
    window.eagle_eye_mode = "lumbar_mri"
    window._study_uid = "synthetic-study"
    window.imaging_tab = SimpleNamespace()
    controller = EagleEyeWorkspaceController(window)
    yield window, controller
    if controller._brain_widget is not None:
        controller._brain_widget._executor.shutdown(wait=False, cancel_futures=True)
    window.close()
    window.deleteLater()
    qapp.processEvents()


@pytest.mark.parametrize("mode,modality,label", [
    ("mammography", "MG", "Mammography Pathology Analysis"),
    ("bone_age", "DX", "Bone Age AI"),
    ("lumbar_mri", "MR", "Lumbar Pathology Analysis"),
    ("brain_mri", "MR", "Whole Brain Segmentation | T1 MPRAGE"),
])
def test_picker_exposes_named_function_and_cancel_starts_nothing(qapp, workspace, monkeypatch, mode, modality, label):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QListWidget
    window, controller = workspace
    window.eagle_eye_mode = mode
    controller._source_modality = modality
    calls = []
    monkeypatch.setattr(controller, "_start_native", lambda value: calls.append(value))
    monkeypatch.setattr(controller, "open_brain", lambda: calls.append("brain"))
    seen = []
    def cancel():
        dialog = qapp.activeModalWidget()
        seen.append(dialog.findChild(QListWidget).item(0).text())
        dialog.reject()
    QTimer.singleShot(0, cancel)
    controller.choose_function()
    assert seen == [label]
    assert calls == []
    assert not controller._choosing


def test_function_selection_dispatches_only_after_accept(qapp, workspace, monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialogButtonBox
    window, controller = workspace
    calls = []
    monkeypatch.setattr(controller, "_start_native", calls.append)
    def accept():
        assert calls == []
        qapp.activeModalWidget().findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).click()
    QTimer.singleShot(0, accept)
    controller.choose_function()
    assert calls == ["MR"]


def test_brain_tools_are_reusable_popup_and_do_not_replace_viewer(workspace, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    window, controller = workspace
    viewer = window.imaging_tab
    calls = []
    monkeypatch.setattr(BrainVolumetryWidget, "start_study_segmentation", lambda self: calls.append(self.study_uid))
    controller.open_brain()
    dialog = controller._brain_dialog
    assert dialog.isVisible() and dialog.parentWidget() is window
    assert dialog.width() <= 1000, "Brain popup must not expand to the width of an unwrapped consent line"
    assert window.imaging_tab is viewer
    dialog.close()
    assert controller._brain_widget._cancel.is_set()
    controller.open_brain()
    assert controller._brain_dialog is dialog
    assert calls == ["synthetic-study", "synthetic-study"]


def test_brain_lesion_entry_available_but_unknown_modality_disabled(qapp):
    from PySide6.QtCore import Qt
    from modules.ai_imaging.eagle_eye_function_dialog import EagleEyeFunctionDialog
    dialog = EagleEyeFunctionDialog("MR", mode="brain_mri")
    assert dialog.list.count() == 2
    assert "White-matter Lesions" in dialog.list.item(1).text()
    assert dialog.list.item(1).flags() & Qt.ItemIsEnabled
    dialog.deleteLater()
    unknown = EagleEyeFunctionDialog("CT")
    assert unknown._selected_key() is None
    unknown.deleteLater()


def test_sidebar_uses_same_navigation_entry_without_analysis(monkeypatch):
    from modules.ai_imaging import eagle_eye_workspace as entry
    calls = []
    monkeypatch.setattr(entry, "open_eagle_eye_workspace", calls.append)
    host = object()
    method("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py",
           "_on_sidebar_ai_module_clicked")(host)
    assert calls == [host]


def test_eagle_button_inside_workspace_opens_function_picker_without_another_tab():
    from modules.ai_imaging.eagle_eye_workspace import open_eagle_eye_workspace
    calls = []
    patient = SimpleNamespace(_eagle_eye_function_action=lambda: calls.append("choose"))
    open_eagle_eye_workspace(patient)
    assert calls == ["choose"]


@pytest.mark.parametrize("series_uid", ["synthetic-t1", ""])
def test_picker_refreshes_brain_type_after_empty_workspace_entry(workspace, monkeypatch, series_uid):
    from modules.ai_imaging import eagle_eye_function_dialog as dialogs
    window, controller = workspace
    window.eagle_eye_mode = None
    controller._source_modality = ""
    viewer = SimpleNamespace(metadata={"series": {
        "modality": "MR", "series_description": "t1_mprage_tra_p2_iso",
        "study_uid": "synthetic-study", "series_uid": series_uid,
    }})
    window.imaging_tab.patient_widget = SimpleNamespace(
        selected_widget=SimpleNamespace(image_viewer=viewer))
    choices = []
    monkeypatch.setattr(dialogs, "choose_eagle_eye_function",
                        lambda modality, **kw: choices.append((modality, kw['mode'])))
    controller.choose_function()
    assert choices == [("MR", "brain_mri")]
    assert window.eagle_eye_mode == window.imaging_tab.eagle_eye_mode == "brain_mri"


def test_picker_rejects_selection_from_another_study(workspace, monkeypatch):
    from modules.ai_imaging import eagle_eye_function_dialog as dialogs
    window, controller = workspace
    viewer = SimpleNamespace(metadata={"series": {
        "modality": "MR", "series_description": "Brain MPRAGE",
        "study_uid": "other-study", "series_uid": "other-t1",
    }})
    window.imaging_tab.patient_widget = SimpleNamespace(
        selected_widget=SimpleNamespace(image_viewer=viewer))
    messages = []
    monkeypatch.setattr(controller, "_message", messages.append)
    monkeypatch.setattr(dialogs, "choose_eagle_eye_function",
                        lambda *a, **kw: pytest.fail('Cross-study picker opened'))
    controller.choose_function()
    assert messages and 'study' in messages[0]


def test_lumbar_completion_only_starts_capture_in_matching_workspace(workspace, monkeypatch):
    from modules.ai_imaging.eagle_eye_lumbar import session_request
    window, controller = workspace
    calls = []
    window.imaging_tab = SimpleNamespace(
        patient_widget=SimpleNamespace(_preferred_eagle_eye_study_uid="other-study"),
        _eagle_eye_workflow=SimpleNamespace(start_capture=lambda: calls.append("capture")))
    monkeypatch.setattr(controller, "_message", lambda text: calls.append("warning"))
    monkeypatch.setattr(session_request, "take", lambda uid: calls.append(uid))
    controller._native_ready()
    assert calls == ["other-study", "warning"]
    calls.clear()
    window.imaging_tab.patient_widget._preferred_eagle_eye_study_uid = "synthetic-study"
    controller._native_ready()
    assert calls == ["capture"]


def test_brain_and_lumbar_share_mri_sidebar_classification():
    for mode in ("brain_mri", "lumbar_mri"):
        assert method(IMAGING, "detect_modality")(SimpleNamespace(eagle_eye_mode=mode)) == "MR"


@pytest.mark.parametrize("mode", ["mammography", "bone_age", "lumbar_mri", "brain_mri"])
def test_real_window_builds_imaging_and_lazy_tools_without_prompt(qapp, monkeypatch, mode):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.ai_module_ui import ai_mainwindow as main
    from modules.ai_imaging import eagle_eye_function_dialog as dialogs
    class Imaging(QWidget):
        fully_loaded = Signal()
        def __init__(self, **kwargs):
            super().__init__()
            self.patient_widget = QWidget(self)
            self.patient_widget.on_tab_activated = lambda: None
            self.patient_widget.on_tab_deactivated = lambda: None
        def refresh_mg_ai_results(self):
            return False
    monkeypatch.setattr(main, "ImagingToolsTab", Imaging)
    monkeypatch.setattr(main.AiMainWindow, "_sync_reception_patient_context", lambda self: None)
    calls = []
    monkeypatch.setattr(dialogs, "choose_eagle_eye_function", lambda *a, **kw: calls.append(kw["mode"]))
    window = main.AiMainWindow(study_uid="synthetic-study", eagle_eye_mode=mode)
    assert isinstance(window.imaging_tab, Imaging)
    assert window.function_button.minimumWidth() >= 240
    assert window.function_button.minimumHeight() >= 52
    assert window.function_button.isEnabled()
    assert [window.tab_widget.tabText(i) for i in range(window.tab_widget.count())] == [
        "Imaging Tools", "Data Set", "Model Training", "Reception Data"]
    window.imaging_tab.fully_loaded.emit()
    qapp.processEvents()
    assert window.function_button.isEnabled() and calls == []
    window.function_button.click()
    assert calls == [mode]
    window.refresh_ai_results()
    assert calls == [mode]
    window.deleteLater()
    qapp.processEvents()


def test_native_adapter_keeps_worker_and_study_identity_until_completion(workspace, monkeypatch):
    from modules.viewer.interactor_styles import ai_chat_interactorstyle as native
    window, controller = workspace
    window.eagle_eye_mode = "mammography"
    calls = []
    class Style:
        def __init__(self, image):
            self.busy = False
        def _ai_worker_busy(self):
            return self.busy
        def check_status(self, patient):
            calls.append(dict(self.image_viewer.metadata_fixed))
            self.busy = True
    monkeypatch.setattr(native, "AIChatInteractorStyle", Style)
    monkeypatch.setattr(controller, "_message", lambda message: calls.append("busy"))
    monkeypatch.setattr(controller, "_native_ready", lambda: calls.append("ready"))
    original = {"study_uid": "synthetic-study", "modality": "MG"}
    patient = SimpleNamespace(selected_widget=SimpleNamespace(image_viewer=SimpleNamespace(
        metadata_fixed=original, metadata={"series": original})))
    window.imaging_tab = SimpleNamespace(patient_widget=patient, _eagle_eye_workflow=None)
    controller._start_native("MG")
    style = controller._native_style
    controller._start_native("MG")
    assert controller._native_style is style
    assert calls == [original, "busy"]
    assert style.image_viewer.metadata_fixed is not original
    style._workspace_open_callback()
    assert calls[-1] == "ready"


def test_native_result_callback_refreshes_workspace_without_navigation():
    calls = []
    host = SimpleNamespace(_workspace_open_callback=lambda: calls.append("refresh"))
    method("modules/viewer/interactor_styles/ai_chat_interactorstyle.py", "open_ai_module")(host)
    assert calls == ["refresh"]


def test_lumbar_new_run_cannot_replace_running_analysis(qapp):
    from PySide6.QtCore import QObject
    from modules.ai_imaging.eagle_eye_lumbar.workflow_coordinator import EagleEyeWorkflowCoordinator
    host = QObject()
    coordinator = EagleEyeWorkflowCoordinator(host)
    coordinator._analysis_runner = SimpleNamespace(running=True)
    coordinator._start_series_probe = lambda: pytest.fail("A second capture replaced an active analysis")
    coordinator.start_capture()
    coordinator._analysis_runner = None


def test_legacy_image_tool_entry_navigates_without_attaching_analysis_style():
    calls = []
    toolbar = SimpleNamespace(
        _tool_unavailable_in_mpr=lambda *args: False,
        tool_selected=None, tool_access=SimpleNamespace(AI_CHAT="ai"),
        check_and_deactivate_tools=lambda: None,
        _on_ai_analysis_clicked=lambda: calls.append("workspace"))
    selected = SimpleNamespace(set_new_interactorstyle=lambda value: pytest.fail("Analysis style attached before entry"))
    method(TOOLBAR, "toggle_ai_chat", {"AIChatInteractorStyle": object})(toolbar, selected)
    assert calls == ["workspace"]


def test_workspace_delete_detaches_jobs_before_children_are_destroyed(qapp):
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    window = QWidget()
    window.eagle_eye_mode = "lumbar_mri"
    calls = []
    window.imaging_tab = SimpleNamespace(_eagle_eye_workflow=SimpleNamespace(teardown=lambda: calls.append("detach")))
    controller = EagleEyeWorkspaceController(window)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(window, QEvent.DeferredDelete)
    assert calls == ["detach"]


def test_imaging_toolbar_has_no_duplicate_section_title(qapp):
    from PySide6.QtWidgets import QHBoxLayout, QGroupBox
    from modules.ai_imaging.ai_module_ui.service_tab.abstract_tab import AbstractTab
    tab = AbstractTab()
    # Exercise the exact section registration used by Imaging Tools.
    tree = ast.parse((ROOT / IMAGING).read_text(encoding="utf-8-sig"))
    call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "add_section"
                and n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "Home")
    tab.home_layout = QHBoxLayout
    exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.Expr(value=call)], type_ignores=[])), IMAGING, "exec"), {"self": tab})
    page = tab.get_stacked_layout().currentWidget()
    assert not isinstance(page, QGroupBox) or not page.title(), "Duplicate Home title overlaps toolbar actions"
    tab.deleteLater()


def test_embedded_patient_navigation_hidden_without_deleting_controls(qapp):
    from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton
    patient = QWidget()
    patient.container_layout = QHBoxLayout(patient)
    patient.sidebar = QWidget(patient)
    side = QVBoxLayout(patient.sidebar)
    for name in ("btn_series", "btn_reception", "btn_ai_chat", "btn_ai_module", "btn_advanced_tools"):
        button = QPushButton(name)
        setattr(patient, name, button)
        side.addWidget(button)
    thumbnails = QWidget(patient)
    patient.container_layout.addWidget(patient.sidebar)
    patient.container_layout.addWidget(thumbnails)
    patient.show()
    qapp.processEvents()
    method(IMAGING, "_remove_patient_widget_buttons")(SimpleNamespace(patient_widget=patient))
    assert patient.sidebar.isHidden(), "Patient navigation must not occupy the Eagle Eye workspace"
    assert thumbnails.isVisible()
    assert patient.btn_series.parentWidget() is patient.sidebar, "Keep inherited callback targets alive"
    patient.close()
    patient.deleteLater()
