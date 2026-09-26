"""Synthetic workstation Brain workflow; no live clinical database access."""
import sys
from types import SimpleNamespace
from pathlib import Path
from concurrent.futures import Future

import pytest

from modules.ai_imaging.eagle_eye_modes import resolve_eagle_eye_mode
from modules.ai_imaging.eagle_eye_brain import study_workflow as workflow
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError


def test_process_evidence_distinguishes_commit_headroom_from_physical_ram(tmp_path, monkeypatch):
    import json
    import psutil
    from modules.ai_imaging.eagle_eye_brain import process_evidence as evidence
    child = SimpleNamespace(children=lambda **kw: [],
                            memory_info=lambda: SimpleNamespace(rss=100, private=700))
    monkeypatch.setattr(psutil, 'Process', lambda pid: child)
    monkeypatch.setattr(psutil, 'virtual_memory', lambda: SimpleNamespace(available=900))
    monkeypatch.setattr(evidence, 'system_commit', lambda: (995, 1000), raising=False)
    sample = evidence.ProcessEvidence(tmp_path, 'synthetic.exe')
    sample.sample(SimpleNamespace(pid=123))
    sample.finish(7, 'failed')
    value = json.loads((tmp_path / 'process-diagnostics.jsonl').read_text())
    assert value['minimum_available_memory_bytes'] == 900
    assert value['minimum_commit_headroom_bytes'] == 5
    assert value['peak_tree_private_bytes'] == 700


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows-owned subprocess contract')
def test_failed_brain_process_keeps_local_diagnostics_without_exposing_them(tmp_path):
    import threading
    from modules.ai_imaging.eagle_eye_brain.runtime import run_process
    with pytest.raises(BrainError) as error:
        run_process([sys.executable, '-c',
                     "import sys; print('SYNTHETIC_PRIVATE_DETAIL', file=sys.stderr); sys.exit(7)"],
                    tmp_path, threading.Event(), timeout=15)
    assert '7' in str(error.value)
    assert 'SYNTHETIC_PRIVATE_DETAIL' not in str(error.value)
    assert 'SYNTHETIC_PRIVATE_DETAIL' in (tmp_path / 'process.log').read_text()
    import json
    evidence = json.loads((tmp_path / 'process-diagnostics.jsonl').read_text())
    assert evidence['returncode'] == 7
    assert evidence['outcome'] == 'failed'
    assert 'SYNTHETIC_PRIVATE_DETAIL' not in json.dumps(evidence)
    assert str(tmp_path) not in json.dumps(evidence)


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows-owned subprocess contract')
@pytest.mark.parametrize('cancel_running', [False, True])
def test_brain_process_evidence_preserves_timeout_and_cancel(tmp_path, cancel_running):
    import json
    import threading
    from modules.ai_imaging.eagle_eye_brain.runtime import run_process
    cancel = threading.Event()
    timer = threading.Timer(.3, cancel.set) if cancel_running else None
    if timer:
        timer.start()
    try:
        with pytest.raises(BrainError):
            run_process([sys.executable, '-c', 'import time; time.sleep(10)'], tmp_path, cancel,
                        timeout=5 if cancel_running else .2)
    finally:
        if timer:
            timer.join(timeout=2)
    evidence = json.loads((tmp_path / 'process-diagnostics.jsonl').read_text())
    assert evidence['outcome'] == ('cancelled' if cancel_running else 'timed_out')
    assert evidence['returncode'] is not None


@pytest.mark.parametrize('modality,description,picker_expected', [
    ('MR', 't1_mprage_sag', False), ('MR', 'MRI LUMBAR SPINE', True),
    ('MR', 'MRI KNEE', True), ('MG', 'Mammography', False), ('DX', 'Hand', False)])
def test_toolbar_enters_workspace_without_any_analysis_picker(monkeypatch, modality, description, picker_expected):
    """Execute the real click handler without constructing the workstation."""
    import ast
    from modules.ai_imaging import eagle_eye_function_dialog as entry
    source = Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py')
    tree = ast.parse(source.read_text(encoding='utf-8'))
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == '_on_ai_analysis_clicked')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
    viewer = SimpleNamespace(metadata={'series': {'modality': modality,
        'series_description': description, 'study_uid': 'synthetic-study'}})
    called = []
    patient = SimpleNamespace(selected_widget=SimpleNamespace(vtk_widget=SimpleNamespace(image_viewer=viewer)),
        method_add_new_tab=lambda **kwargs: called.append(("workspace", kwargs["study_uid"])))
    toolbar = SimpleNamespace(patient_widget=patient,
        _trigger_eagle_eye_analysis_pipeline=lambda: called.append('native') or True)
    def choose(*args, **kwargs):
        pytest.fail('Opening Eagle Eye must not select or run a function')
    monkeypatch.setattr(entry, 'choose_eagle_eye_function',
                        choose)
    namespace['_on_ai_analysis_clicked'](toolbar)
    assert called == [('workspace', 'synthetic-study')]


@pytest.mark.parametrize('modality,text,expected', [('MR','MRI BRAIN','brain_mri'),
    ('MR','HEAD t1_mprage_sag','brain_mri'), ('MR','MRI LUMBAR SPINE','lumbar_mri'),
    ('MR','CERVICAL SPINE',None), ('CT','BRAIN',None), ('MG','', 'mammography'),
    ('MR','BRAIN AND SPINE',None)])
def test_brain_routing_preserves_other_anatomy(modality,text,expected):
    assert resolve_eagle_eye_mode(modality,[text])==expected


def test_patient_storage_is_stable_isolated_and_path_safe(tmp_path):
    context=dict(patient_id='../SYNTHETIC',institution='TEST',birth_date='19800101',study_uid='1.2.3')
    first=workflow.patient_output_root(tmp_path,context)
    assert first.is_relative_to(tmp_path/'brain'/'patients')
    assert 'SYNTHETIC' not in str(first)
    assert first==workflow.patient_output_root(tmp_path,context)
    assert first!=workflow.patient_output_root(tmp_path,{**context,'patient_id':'ANOTHER'})
    assert first!=workflow.patient_output_root(tmp_path,{**context,'study_uid':'1.2.4'})
    with pytest.raises(BrainError): workflow.patient_output_root(tmp_path,{})


def test_series_list_uses_only_selected_study_repository(tmp_path,monkeypatch):
    seen=[]
    def records(study):
        seen.append(study)
        return [dict(series_uid='1.2.1',series_number=9,modality='MR',series_description='t1_mprage_sag',series_path=str(tmp_path)),
                dict(series_uid='1.2.2',series_number=18,modality='MR',series_description='t2_space_flair',series_path=''),
                dict(series_uid='1.2.3',modality='CT',series_path=str(tmp_path))]
    monkeypatch.setitem(sys.modules,'PacsClient.utils.db_manager',SimpleNamespace(get_series_by_study_uid=records))
    rows=workflow.load_study_series('1.2')
    assert seen==['1.2'] and len(rows)==2
    assert rows[0]['preferred'] and rows[0]['available']
    assert not rows[1]['preferred'] and not rows[1]['available']


def test_changed_series_identity_does_not_reach_pipeline(tmp_path,monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import patient_context, service
    monkeypatch.setattr(patient_context,'dicom_context',lambda path:dict(study_uid='different',series_uid='1.2.3'))
    monkeypatch.setattr(service,'run_analysis',lambda *a,**kw:pytest.fail('Wrong patient reached segmentation'))
    with pytest.raises(BrainError,match='no longer matches'):
        workflow.run_study_analysis(tmp_path,'1.2','1.2.3',root=tmp_path)


def test_pdf_export_is_complete_and_preserves_existing_on_failure(tmp_path,monkeypatch):
    job=tmp_path/'job';job.mkdir()
    original=b'%PDF-1.4\nsynthetic export fixture'
    (job/'report.pdf').write_bytes(original)
    result=dict(artifact_directory=str(job),pdf_available=True)
    target=tmp_path/'saved.pdf'
    workflow.export_pdf(result,target)
    assert target.read_bytes()==original
    (job/'report.pdf').write_bytes(b'not PDF')
    with pytest.raises(BrainError): workflow.export_pdf(result,target)
    assert target.read_bytes()==original
    assert not list(tmp_path.glob('.brain-report-*'))


def test_ui_refuses_unbound_sources_and_enables_completed_pdf_export(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    from modules.ai_imaging.eagle_eye_brain import report
    app=QApplication.instance() or QApplication([])
    widget=BrainVolumetryWidget(study_uid='1.2')
    widget.t1.setText('synthetic source');widget.confirm.setChecked(True)
    widget._start()
    assert widget._future is None and 'this examination' in widget.status.text()
    def reject_full_document(result):
        raise AssertionError('The result panel must not render the full paginated PDF HTML')
    monkeypatch.setattr(report,'report_html',reject_full_document)
    done=Future();done.set_result(dict(pdf_available=True,artifact_directory='synthetic',normative={}))
    widget._future=done
    widget._poll()
    assert widget.pdf.isEnabled() and widget.save_pdf.isEnabled()
    assert not widget.result_panel.isHidden()
    assert 'Ready for review' in widget.report.text()
    assert widget.save_pdf.minimumHeight() >= 36
    widget._executor.shutdown(wait=False,cancel_futures=True)
    widget.deleteLater();app.processEvents()


def test_sequence_popup_requires_explicit_selection_before_running(monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QCheckBox, QDialogButtonBox
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app=QApplication.instance() or QApplication([])
    widget=BrainVolumetryWidget(study_uid='1.2')
    called=[]
    monkeypatch.setattr(widget,'_load_demographics',lambda:called.append(widget._selected_series))
    row=dict(series_uid='1.2.3',number='9',description='t1_mprage_sag',image_count=176,
             path='synthetic',preferred=True,available=True)
    observed=[]
    def select():
        dialog=app.activeModalWidget()
        buttons=dialog.findChild(QDialogButtonBox)
        observed.append(not buttons.button(QDialogButtonBox.Ok).isEnabled())
        dialog.findChild(QListWidget).setCurrentRow(0)
        observed.append(not buttons.button(QDialogButtonBox.Ok).isEnabled())
        dialog.findChild(QCheckBox).setChecked(True)
        observed.append(buttons.button(QDialogButtonBox.Ok).isEnabled())
        buttons.button(QDialogButtonBox.Ok).click()
    QTimer.singleShot(0,select)
    widget._choose_t1_series([row])
    assert observed==[True,True,True] and called==[row]
    assert widget.t1.text()=='synthetic' and widget.confirm.isChecked()
    widget._executor.shutdown(wait=False,cancel_futures=True)
    widget.deleteLater();app.processEvents()


def test_study_pipeline_passes_verified_flair_to_service(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import patient_context, service, study_workflow
    def context(source):
        return dict(study_uid='study', series_uid=source, patient_id='synthetic')
    monkeypatch.setattr(patient_context, 'dicom_context', context)
    calls = []
    monkeypatch.setattr(service, 'run_analysis', lambda *a, **k: calls.append(a))
    study_workflow.run_study_analysis('t1', 'study', 't1', root=tmp_path,
                                      flair_source='flair', flair_series_uid='flair')
    assert calls[0][1] == 'flair'
    with pytest.raises(BrainError):
        study_workflow.run_study_analysis('t1', 'study', 't1', root=tmp_path,
                                          flair_source='flair', flair_series_uid='wrong')


def test_lesion_option_available_and_cancel_starts_no_work(monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QPushButton
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app=QApplication.instance() or QApplication([])
    widget=BrainVolumetryWidget(study_uid='1.2')
    observed=[]
    def cancel():
        dialog=app.activeModalWidget()
        lesion=next(button for button in dialog.findChildren(QPushButton) if 'Lesion' in button.text())
        observed.append(lesion.isEnabled())
        dialog.reject()
    QTimer.singleShot(0,cancel)
    widget.choose_study_workflow()
    assert observed==[True] and widget._future is None
    widget._executor.shutdown(wait=False,cancel_futures=True)
    widget.deleteLater();app.processEvents()


def test_flair_popup_requires_distinct_confirmed_series(monkeypatch):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QComboBox, QCheckBox, QListWidget, QDialogButtonBox
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app = QApplication.instance() or QApplication([])
    widget = BrainVolumetryWidget(study_uid='study')
    rows = [dict(series_uid=str(i), number=str(i), description=name, image_count=100,
                 path=name, preferred=i == 1, available=True)
            for i, name in ((1, 'T1 MPRAGE'), (2, '3D FLAIR'))]
    called = []
    monkeypatch.setattr(widget, '_load_demographics', lambda: called.append(widget._selected_flair))
    observed = []
    def select():
        dialog = app.activeModalWidget()
        QTimer.singleShot(2000, dialog.reject)
        dialog.findChild(QListWidget).setCurrentRow(0)
        checks = dialog.findChildren(QCheckBox)
        checks[0].setChecked(True)
        combo = dialog.findChild(QComboBox, 'brainFlairSeries')
        ok = dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok)
        combo.setCurrentIndex(1)
        checks[1].setChecked(True)
        observed.append(not ok.isEnabled())
        combo.setCurrentIndex(2)
        observed.append(ok.isEnabled())
        ok.click()
    QTimer.singleShot(0, select)
    widget._choose_t1_series(rows)
    assert observed == [True, True] and called == [rows[1]]
    assert widget.flair.text() == rows[1]['path'] and widget.flair.isReadOnly()
    widget._executor.shutdown(wait=False, cancel_futures=True)
    widget.deleteLater(); app.processEvents()
