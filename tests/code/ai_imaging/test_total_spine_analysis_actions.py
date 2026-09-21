"""Visible analysis entry points must not be confused with hiding the window."""
from concurrent.futures import Future
import pytest
from test_eagle_eye_total_spine import qapp, view

def test_spine_top_actions_expose_ai_and_measurement_separately(qapp,monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    widget=TotalSpineWidget(study_uid='synthetic'); editor=widget.editors[0]
    submitted=[]; monkeypatch.setattr(widget,'_submit',lambda kind,*a,**kw:submitted.append(kind))
    try:
        assert not widget.analyze_button.isEnabled()
        editor.accept_image(view()['image']); widget._refresh()
        assert widget.region_button.isEnabled()
        assert not widget.analyze_button.isEnabled()
        editor._set_region([20,20,400,800]); widget._refresh()
        assert widget.analyze_button.isEnabled()
        widget.analyze_button.click()
        assert submitted == ['inference']
        assert not editor.confirm.isChecked()
        widget.measure_button.click()
        toggle,content=editor.review_sections['Curves and clinical assessment']
        assert toggle.isChecked() and not content.isHidden()
        assert submitted == ['inference']
        widget._future=Future(); widget._refresh()
        assert not widget.analyze_button.isEnabled()
    finally: widget._future=None; widget.teardown(); widget.deleteLater()

def test_background_button_explicitly_says_hide(qapp):
    from PySide6.QtWidgets import QVBoxLayout,QWidget,QPushButton
    from modules.ai_imaging.background_analysis import BackgroundAnalysisDialog
    import threading
    dialog=BackgroundAnalysisDialog(); QVBoxLayout(dialog)
    child=QWidget(dialog); child._future=None; child._cancel=threading.Event()
    dialog.bind_analysis(child)
    try:
        button=dialog.findChild(QPushButton,'eagleEyeBackgroundButton')
        assert 'Hide' in button.text()
        assert 'start' in button.toolTip().lower()
    finally: dialog.deleteLater()
