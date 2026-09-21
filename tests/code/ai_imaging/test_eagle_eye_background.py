"""Eagle Eye computation must not take over the PACS application."""
from concurrent.futures import Future
from types import SimpleNamespace
import ast
from pathlib import Path
import pytest

@pytest.mark.parametrize("kind", ["brain", "lesions", "alignment"])
def test_closing_running_popup_keeps_job_and_reopens_same_owner(kind, monkeypatch):
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import Qt
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(BrainVolumetryWidget, "start_study_segmentation", lambda self: None)
    monkeypatch.setattr(AlignmentWidget, "scan_study", lambda self: None)
    window = QWidget(); window.eagle_eye_mode = "brain_mri"; window._study_uid = "synthetic"
    window.imaging_tab = SimpleNamespace()
    controller = EagleEyeWorkspaceController(window)
    opener = getattr(controller, "open_" + kind)
    opener()
    prefix = "lesion" if kind == "lesions" else kind
    dialog, widget = [getattr(controller, "_" + prefix + suffix) for suffix in ("_dialog", "_widget")]
    future = Future(); widget._future = future; widget._future_kind = "analysis"
    try:
        assert dialog.windowModality() == Qt.NonModal
        dialog.close(); app.processEvents()
        assert not widget._cancel.is_set(), "Closing the analysis popup cancelled the background job"
        assert not dialog.isVisible()
        opener()
        assert getattr(controller, "_" + prefix + "_dialog") is dialog
        assert widget._future is future and not widget._cancel.is_set()
        controller.teardown()
        assert widget._cancel.is_set(), "Destroying the workspace must still stop its owned job"
    finally:
        widget._future = None
        window.close(); window.deleteLater(); app.processEvents()

def test_server_analysis_does_not_use_application_modal_cover():
    path = Path(__file__).resolve().parents[3] / "modules/viewer/interactor_styles/ai_chat_interactorstyle.py"
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for method in (n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name in {"start_mg_process", "start_dx_process"}):
        assert not any(isinstance(n, ast.Attribute) and n.attr == "ApplicationModal" for n in ast.walk(method)), method.name
        assert any(isinstance(n,ast.ImportFrom) and n.module == "modules.ai_imaging.background_analysis" for n in ast.walk(method)), "Use compact, dismissible progress instead of a workstation-covering overlay"


def test_compact_progress_does_not_block_other_pacs_input():
    from PySide6.QtWidgets import QApplication, QWidget, QPushButton
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from modules.ai_imaging.background_analysis import BackgroundProgress
    app = QApplication.instance() or QApplication([])
    host = QWidget(); host.resize(800,600)
    button = QPushButton("PACS report editor",host); host.show()
    clicks=[]; button.clicked.connect(lambda: clicks.append(True))
    progress=BackgroundProgress.show_overlay(host,status="Processing")
    app.processEvents()
    assert QApplication.activeModalWidget() is None
    QTest.mouseClick(button,Qt.LeftButton)
    assert clicks == [True]
    assert progress.width() < host.width()
    progress.close();app.processEvents()
    assert host.isEnabled() and not progress.isVisible()
    BackgroundProgress.hide_overlay(progress)
    host.close();host.deleteLater();app.processEvents()


def test_pending_input_scan_is_cancelled_on_dismissal():
    from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout
    from modules.ai_imaging.background_analysis import BackgroundAnalysisDialog
    import threading
    app=QApplication.instance() or QApplication([])
    dialog=BackgroundAnalysisDialog(); QVBoxLayout(dialog)
    widget=QWidget(dialog); widget._future=Future(); widget._future_kind="series";widget._cancel=threading.Event()
    dialog.bind_analysis(widget);dialog.show();dialog.close()
    assert widget._cancel.is_set()
    dialog.deleteLater();app.processEvents()
