"""Synthetic completion-to-review tab regression guards."""
from concurrent.futures import Future
from types import SimpleNamespace
import pytest

from test_eagle_eye_total_spine import qapp


def test_marrow_completion_opens_large_reusable_review_tab(qapp, monkeypatch):
    from PySide6.QtWidgets import QWidget, QTabWidget, QVBoxLayout
    from modules.ai_imaging.lumbar_marrow_widget import LumbarMarrowWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    monkeypatch.setattr(LumbarMarrowWidget, 'load_series', lambda self: None)
    window = QWidget()
    window._study_uid = 'synthetic-study'
    window.eagle_eye_mode = None
    window.imaging_tab = SimpleNamespace(patient_widget=None)
    window.tab_widget = QTabWidget(window)
    QVBoxLayout(window).addWidget(window.tab_widget)
    window.tab_widget.addTab(QWidget(), 'Imaging Tools')
    controller = EagleEyeWorkspaceController(window)
    controller.open_marrow()
    widget = controller._marrow_widget
    assert hasattr(widget.review_page, 'table'), 'Review needs readable measurements outside the HTML image flow'
    assert window.tab_widget.count() == 1
    future = Future()
    future.set_result(({'report_html': 'synthetic.html'}, '<h1>Synthetic report</h1>', '/synthetic/report.html'))
    widget._future, widget._future_kind = future, 'analysis'
    widget.poll()
    assert window.tab_widget.count() == 2
    page = window.tab_widget.currentWidget()
    assert window.tab_widget.tabText(1) == 'Lumbar Bone Marrow'
    assert page.isAncestorOf(widget.report)
    assert not widget.isAncestorOf(widget.report)
    assert not controller._marrow_dialog.isVisible()
    assert 'Lumbar Bone Marrow' in widget.report.toPlainText()
    widget.resultsReady.emit()
    controller.open_marrow()
    assert window.tab_widget.count() == 2
    assert window.tab_widget.currentWidget() is page
    controller.teardown()
    window.close()


@pytest.mark.parametrize('cancelled', [False, True])
def test_failure_or_cancel_does_not_present_results(qapp, monkeypatch, cancelled):
    from modules.ai_imaging.lumbar_marrow_widget import LumbarMarrowWidget
    monkeypatch.setattr(LumbarMarrowWidget, 'load_series', lambda self: None)
    widget = LumbarMarrowWidget(study_uid='synthetic-study')
    emitted = []
    widget.resultsReady.connect(lambda: emitted.append(True))
    future = Future()
    future.set_exception(RuntimeError('Synthetic failure'))
    widget._future, widget._future_kind = future, 'analysis'
    if cancelled:
        widget._cancel.set()
    widget.poll()
    assert not emitted
    assert widget._result is None
    widget.teardown()
    widget.teardown()
