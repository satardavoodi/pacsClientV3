"""Native spine workspace access and source-connected Cobb construction."""
from types import SimpleNamespace
import numpy as np
import pytest
from test_eagle_eye_total_spine import qapp


def test_cobb_normals_start_on_actual_extended_endplates():
    from modules.ai_imaging.eagle_eye_total_spine.annotations import perpendicular_construction
    upper=np.array([[200.,200.],[260.,190.]])
    lower=np.array([[210.,650.],[270.,660.]])
    result=perpendicular_construction(upper,lower,(1000,500),(2.,1.))
    assert result['mode'] == 'source endplate perpendiculars'
    for pair, foot in zip((upper,lower), result['feet']):
        d=pair[1]-pair[0]; offset=np.array(foot)-pair[0]
        assert d[0]*offset[1]-d[1]*offset[0] == pytest.approx(0,abs=1e-6)
        normal=(np.array(result['intersection'])-foot)*[1,2]
        assert np.dot(d*[1,2],normal) == pytest.approx(0,abs=1e-6)
    assert sum(line.get('role')=='endplate_extension' for line in result['lines']) == 2


def test_spine_editor_embeds_and_reuses_without_loaded_viewer(qapp,monkeypatch):
    from PySide6.QtWidgets import QWidget,QTabWidget,QVBoxLayout
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    window=QWidget(); window.eagle_eye_mode=None; window._study_uid='synthetic-study'
    window.imaging_tab=SimpleNamespace(patient_widget=None)
    window.tab_widget=QTabWidget(window); QVBoxLayout(window).addWidget(window.tab_widget)
    window.tab_widget.addTab(QWidget(),'Imaging Tools')
    window.tab_widget.addTab(QWidget(),'Reception Data')
    scans=[]
    monkeypatch.setattr(TotalSpineWidget,'scan_study',lambda self:scans.append(self.study_uid))
    controller=EagleEyeWorkspaceController(window)
    controller.open_total_spine()
    editor=controller._total_spine_widget
    assert window.tab_widget.indexOf(editor) == -1
    editor.resultsReady.emit()
    assert window.tab_widget.currentWidget() is editor
    assert window.tab_widget.tabText(window.tab_widget.count()-2) == 'Reception Data'
    assert editor.study_uid=='synthetic-study' and scans==['synthetic-study']
    controller.open_total_spine()
    assert controller._total_spine_widget is editor and window.tab_widget.count()==3
    assert scans==['synthetic-study']
    controller.teardown(); assert editor._disposed
    window.close()


def test_real_workspace_has_only_function_picker_before_viewer_ready(qapp,monkeypatch):
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget
    from modules.ai_imaging.ai_module_ui import ai_mainwindow as main
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    class Imaging(QWidget):
        fully_loaded=Signal()
        def __init__(self,**kw):
            super().__init__(); self.patient_widget=QWidget(self)
            self.patient_widget.on_tab_activated=lambda:None
            self.patient_widget.on_tab_deactivated=lambda:None
    monkeypatch.setattr(main,'ImagingToolsTab',Imaging)
    monkeypatch.setattr(main.AiMainWindow,'_sync_reception_patient_context',lambda self:None)
    scans=[]
    monkeypatch.setattr(TotalSpineWidget,'scan_study',lambda self:scans.append(self.study_uid))
    window=main.AiMainWindow(study_uid='synthetic-study')
    assert not hasattr(window, 'spine_button')
    assert window.function_button.isEnabled()
    window.workspace_controller.teardown(); window.deleteLater(); qapp.processEvents()


def test_all_candidate_endplates_visible_before_numbering(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    from test_eagle_eye_total_spine import view,body
    editor=ProjectionEditor('coronal'); editor.accept_image(view()['image'])
    editor.accept_candidates({'candidates':[{'corners':list(body(240,y).values())} for y in (100,200,300)]})
    assert sum(getattr(item, 'text', lambda: '')().startswith('Candidate ') for item in editor._candidate_lines)==3
    assert any('proposal' in getattr(item, 'text', lambda: '')() for item in editor._candidate_lines)
    assert not editor.points  # Visibility must not invent anatomical levels.
    editor.clear_image(); assert not editor._candidate_lines
    editor.close()


def test_automatic_input_runs_after_region_and_reveals_only_results(qapp, monkeypatch):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    from test_eagle_eye_total_spine import view, body
    widget=TotalSpineWidget(study_uid='synthetic-study')
    monkeypatch.setattr(widget, 'scan_study', lambda: None)
    widget.begin_automatic()
    editor=widget.editors[0]; editor.accept_image(view()['image'])
    submitted=[]
    monkeypatch.setattr(widget, '_submit', lambda *args, **kw: submitted.append((args,kw)))
    assert not editor.confirm.isChecked()
    editor._set_region([10,10,400,450])
    qapp.processEvents()
    assert submitted and submitted[0][0][0]=='inference'
    ready=[]; widget.resultsReady.connect(lambda:ready.append(True))
    widget._future=Future(); widget._kind='inference'; widget._target=editor
    widget._future.set_result({'candidates':[{'corners':list(body(240,y).values())} for y in (100,200)]})
    widget._poll()
    assert ready==[True] and not widget._automatic
    assert not editor.confirm.isChecked() and not editor.points
    assert editor.automatic_pair is not None
    widget.teardown(); widget.close()


def test_unloaded_workspace_catalog_resolution_is_off_thread(qapp, monkeypatch):
    import threading
    from PySide6.QtWidgets import QWidget, QPushButton
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging import eagle_eye_function_dialog as dialogs
    from PacsClient.utils import db_manager
    main_thread=threading.get_ident(); worker_threads=[]
    def catalog(study):
        assert study=='synthetic-study'
        worker_threads.append(threading.get_ident())
        return [{'modality':'DX'}]
    monkeypatch.setattr(db_manager,'get_series_by_study_uid',catalog)
    choices=[]
    monkeypatch.setattr(dialogs,'choose_eagle_eye_function',lambda modality, **kw:choices.append(modality))
    host=QWidget(); host.eagle_eye_mode=None; host._study_uid='synthetic-study'
    host.imaging_tab=SimpleNamespace(patient_widget=None); host.function_button=QPushButton(host)
    controller=EagleEyeWorkspaceController(host); controller.choose_function()
    controller._modality_future.result(timeout=2); controller._modality_ready()
    assert choices==['DX'] and worker_threads[0]!=main_thread
    assert host.function_button.isEnabled()
    controller.teardown(); host.close()


def test_cancelled_or_empty_analysis_does_not_reveal_review(qapp, monkeypatch):
    from concurrent.futures import Future
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    from test_eagle_eye_total_spine import view
    widget=TotalSpineWidget(study_uid='synthetic-study')
    monkeypatch.setattr(widget,'scan_study',lambda:None)
    widget.begin_automatic(); editor=widget.editors[0]; editor.accept_image(view()['image'])
    ready=[]; widget.resultsReady.connect(lambda:ready.append(True))
    for cancelled in (False, True):
        widget._future=Future(); widget._kind='inference'; widget._target=editor
        widget._future.set_result({'candidates':[]})
        if cancelled: widget._cancel.set()
        widget._poll()
        assert not ready and widget._automatic
    widget.teardown(); widget.close()


def test_candidate_pair_is_ordered_and_uses_physical_pixel_aspect():
    from modules.ai_imaging.eagle_eye_total_spine.automatic import candidate_pair
    candidates=[{'corners':[[10,100],[30,110],[10,120],[30,130]]},
                {'corners':[[10,200],[30,190],[10,220],[30,210]]}]
    pair=candidate_pair(list(reversed(candidates)),(2,1))
    assert pair=={'upper':1,'lower':0,'degrees':90.0}
    assert candidate_pair(candidates[:1],(1,1)) is None


def test_review_sections_fit_narrow_sidebar_without_horizontal_scrolling(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    editor=ProjectionEditor('coronal'); editor.resize(1100,850); editor.show(); qapp.processEvents()
    assert editor.review_sections['Vertebral numbering'][0].isChecked()
    assert editor.review_sections['Correct endplates'][0].isChecked()
    assert not editor.review_sections['Detection and field of view'][0].isChecked()
    assert not editor.review_sections['Pedicles and assisted placement'][0].isChecked()
    assert editor.review_scroll.horizontalScrollBar().maximum()==0
    editor.close()


def test_acquisition_controls_fit_when_expanded(qapp):
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor
    editor=ProjectionEditor('coronal'); editor.resize(1500,850); editor.show()
    editor.review_sections['Acquisition and scale'][0].setChecked(True)
    qapp.processEvents()
    assert editor.review_scroll.horizontalScrollBar().maximum()==0
    editor.close()


def test_result_reparent_fits_image_to_settled_viewport(qapp,monkeypatch):
    from PySide6.QtWidgets import QWidget,QTabWidget,QVBoxLayout
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    from test_eagle_eye_total_spine import view
    host=QWidget(); host.eagle_eye_mode=None; host._study_uid='synthetic-study'
    host.imaging_tab=SimpleNamespace(patient_widget=None)
    host.tab_widget=QTabWidget(); QVBoxLayout(host).addWidget(host.tab_widget)
    host.resize(1300,700); host.show()
    monkeypatch.setattr(TotalSpineWidget,'scan_study',lambda self:None)
    controller=EagleEyeWorkspaceController(host); controller.open_total_spine()
    widget=controller._total_spine_widget; widget.editors[0].accept_image(view()['image'])
    qapp.processEvents()
    widget._automatic=False; widget._automatic_visibility(False); widget.resultsReady.emit()
    qapp.processEvents(); qapp.processEvents()
    canvas=widget.editors[0].canvas
    rectangle=canvas.transform().mapRect(canvas.sceneRect())
    assert rectangle.height()<=canvas.viewport().height()+1
    assert rectangle.width()<=canvas.viewport().width()+1
    controller.teardown(); host.close()
