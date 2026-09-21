"""Active-series handoff and honest background activity guards."""
from concurrent.futures import Future
from types import SimpleNamespace
import threading
import pytest

@pytest.fixture
def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])

def test_workspace_prefers_loaded_workspace_series_then_bound_source(app):
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    def patient(uid):
        return SimpleNamespace(selected_widget=SimpleNamespace(image_viewer=SimpleNamespace(
            metadata={'series': {'study_uid':'study', 'series_uid':uid, 'modality':'DX'}})))
    host=QWidget(); host.eagle_eye_mode=None; host._study_uid='study'
    host.imaging_tab=SimpleNamespace(patient_widget=patient('active'))
    controller=EagleEyeWorkspaceController(host)
    controller._source_identity=('study','original','4')
    try:
        assert controller.selected_series_uid() == 'active'
        host.imaging_tab.patient_widget=None
        assert controller.selected_series_uid() == 'original'
        host.imaging_tab.patient_widget=patient('other')
        host.imaging_tab.patient_widget.selected_widget.image_viewer.metadata['series']['study_uid']='elsewhere'
        assert controller.selected_series_uid() == ''
    finally:
        controller.teardown(); host.deleteLater()

def test_common_dialog_reports_busy_stage_and_stops_bar(app):
    from PySide6.QtWidgets import QWidget,QVBoxLayout,QLabel
    from modules.ai_imaging.background_analysis import BackgroundAnalysisDialog
    dialog=BackgroundAnalysisDialog(); QVBoxLayout(dialog)
    widget=QWidget(dialog); widget._future=Future(); widget._kind='inference'
    widget._cancel=threading.Event(); widget.status=QLabel('Locating vertebrae',widget)
    dialog.layout().addWidget(widget); dialog.bind_analysis(widget)
    try:
        dialog._update_activity()
        assert dialog.activity_bar.maximum() == 0
        assert 'Locating vertebrae' in dialog.activity_status.text()
        widget._future=None; widget.status.setText('Review proposals')
        dialog._update_activity()
        assert dialog.activity_bar.isHidden()
        assert dialog.activity_status.text() == 'Review proposals'
    finally: dialog.deleteLater()

def test_spine_scan_loads_exact_selected_series(app,monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    widget=TotalSpineWidget(study_uid='study')
    monkeypatch.setattr(widget,'scan_study',lambda:None)
    calls=[]; monkeypatch.setattr(widget,'load_image',lambda editor:calls.append(editor.series.currentData()))
    try:
        widget.begin_automatic(series_uid='chosen')
        future=Future(); future.set_result([
            {'series_uid':uid,'series_label':uid,'path':uid+'.dcm','label':'Image','view_position':'AP'}
            for uid in ('other','chosen')])
        widget._future=future; widget._kind='scan'; widget._poll()
        assert calls == ['chosen']
        assert widget.editors[0].series.currentData() == 'chosen'
    finally: widget.teardown(); widget.deleteLater()

def test_lumbar_background_status_opens_updates_and_closes_popup(app):
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.eagle_eye_lumbar.workflow_coordinator import EagleEyeWorkflowCoordinator
    host=QWidget(); host.set_processing_status=lambda *a,**k:None
    coordinator=EagleEyeWorkflowCoordinator(host)
    try:
        coordinator._set_status('Reading images',active=True)
        popup=coordinator._progress_popup
        assert popup.isVisible()
        coordinator._set_status('Verifying findings',active=True)
        assert coordinator._progress_popup is popup
        assert popup.status_label.text() == 'Verifying findings'
        coordinator._set_status('Complete',active=False)
        assert coordinator._progress_popup is None
        assert not popup.isVisible()
    finally: coordinator.teardown(); host.deleteLater()

def test_alignment_selected_series_starts_proposals_without_marking_reviewed(app,monkeypatch):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    widget=AlignmentWidget(study_uid='study'); widget.preferred_series_uid='chosen'
    calls=[]
    monkeypatch.setattr(widget,'_apply_image',lambda image:setattr(widget,'image',image))
    monkeypatch.setattr(widget,'_submit',lambda kind,*args,**kwargs:calls.append(kind))
    try:
        future=Future(); future.set_result({'identity':{'series_uid':'chosen'}})
        widget._future=future; widget._kind='load'; widget._poll()
        assert calls == ['ai']
        assert not widget.confirm.isChecked() and not widget.review.isChecked()
    finally: widget.teardown(); widget.deleteLater()

@pytest.mark.parametrize('position,answer,expected', [('AP',None,0),('LAT',None,1),('', 'Lateral',1)])
def test_spine_projection_uses_tags_or_only_asks_unknown(app,monkeypatch,position,answer,expected):
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget,QInputDialog
    widget=TotalSpineWidget(study_uid='study'); widget.preferred_series_uid='chosen'; widget._automatic=True
    rows=[{'series_uid':'chosen','series_label':'Chosen','path':'synthetic.dcm','label':'Image','view_position':position}]
    for editor in widget.editors: editor.set_inventory(rows)
    prompts=[]; loads=[]
    monkeypatch.setattr(QInputDialog,'getItem',lambda *args:(prompts.append(True) or answer, True))
    monkeypatch.setattr(widget,'load_image',lambda editor:loads.append(editor.projection))
    try:
        widget._load_preferred_series(rows)
        assert prompts == ([True] if answer else [])
        assert loads == [('coronal','lateral')[expected]]
        assert widget.tabs.currentIndex() == expected
        if expected: assert not widget._automatic
    finally: widget.teardown(); widget.deleteLater()

def test_missing_selected_spine_series_never_loads_another(app,monkeypatch):
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    widget=TotalSpineWidget(study_uid='study'); widget.preferred_series_uid='missing'
    monkeypatch.setattr(widget,'load_image',lambda editor:pytest.fail('Wrong series loaded'))
    try:
        widget._load_preferred_series([])
        assert 'selected series' in widget.status.text()
    finally: widget.teardown(); widget.deleteLater()

def test_lesion_pair_preselects_active_flair_without_confirming_it(app):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QComboBox,QCheckBox
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    widget=BrainLesionWidget(study_uid='study'); widget.preferred_series_uid='flair'
    rows=[dict(series_uid=uid, available=True, preferred=uid=='t1', description=description,
               number=str(index), image_count=10, path='synthetic')
          for index,(uid,description) in enumerate([('t1','T1'),('flair','3D FLAIR')])]
    observed=[]
    def inspect():
        dialog=app.activeModalWidget()
        observed.append(dialog.findChild(QComboBox,'lesionFlairSeries').currentData()['series_uid'])
        observed.append(dialog.findChild(QCheckBox).isChecked())
        dialog.reject()
    QTimer.singleShot(0,inspect)
    try:
        widget._choose_t1_series(rows)
        assert observed == ['flair',False]
    finally:
        widget._cancel.set(); widget._executor.shutdown(wait=False,cancel_futures=True); widget.deleteLater()

def test_brain_function_continues_after_required_input_confirmation(app,monkeypatch):
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    widget=BrainVolumetryWidget(study_uid='study'); widget.start_after_inputs=True
    called=[]; monkeypatch.setattr(widget,'_start',lambda:called.append(True))
    monkeypatch.setattr(widget,'_apply_demographics',lambda result:None)
    try:
        future=Future(); future.set_result({})
        widget._future=future; widget._future_kind='demographics'; widget._poll()
        assert called == [True]
    finally:
        widget._cancel.set(); widget._executor.shutdown(wait=False,cancel_futures=True); widget.deleteLater()

def test_spine_switching_active_series_preserves_previous_review(app,monkeypatch):
    from PySide6.QtWidgets import QWidget,QTabWidget,QVBoxLayout
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    host=QWidget(); host.eagle_eye_mode=None; host._study_uid='study'; host.imaging_tab=SimpleNamespace()
    host.tab_widget=QTabWidget(host); QVBoxLayout(host).addWidget(host.tab_widget)
    controller=EagleEyeWorkspaceController(host); selected=['first']; starts=[]
    monkeypatch.setattr(controller,'selected_series_uid',lambda:selected[0])
    monkeypatch.setattr(TotalSpineWidget,'begin_automatic',lambda self,**kw:starts.append(kw.get('series_uid')))
    try:
        controller.open_total_spine(); first=controller._total_spine_widget
        first.resultsReady.emit()
        selected[0]='second'; controller.open_total_spine(); second=controller._total_spine_widget
        assert first is not second
        assert host.tab_widget.indexOf(first) >= 0
        second.resultsReady.emit()
        assert host.tab_widget.currentWidget() is second
        selected[0]='first'; controller.open_total_spine()
        assert controller._total_spine_widget is first
        assert starts == ['first','second']
    finally: controller.teardown(); host.deleteLater()
