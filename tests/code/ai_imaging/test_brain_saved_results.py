"""Synthetic study-bound result discovery; never reads the live database."""
import json
import hashlib
from pathlib import Path
import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def make_result(root, study, kind='brain', job='one'):
    folder=root/'brain'/'patients'/'synthetic'/'studies'/hashlib.sha256(study.encode()).hexdigest()/job
    folder.mkdir(parents=True, exist_ok=True)
    result={'artifact_directory':str(folder), 'patient_context':{'study_uid':study},
            'analysis_study_uid':study, 'analysis_type':kind, 'pdf_available':True}
    (folder/'result.json').write_text(json.dumps(result))
    (folder/'report.pdf').write_bytes(b'%PDF-1.4 synthetic')
    return folder, result


def test_saved_results_survive_reopen_and_are_study_isolated(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.saved_results import discover_results, load_result
    first, result=make_result(tmp_path, 'study-a')
    make_result(tmp_path, 'study-b')
    rows=discover_results(tmp_path, 'study-a')
    assert len(rows)==1
    assert load_result(tmp_path, 'study-a', rows[0]['path'])['artifact_directory']==str(first)
    assert discover_results(tmp_path, 'missing')==[]
    with pytest.raises(ValueError): load_result(tmp_path, 'study-b', rows[0]['path'])


def test_conflicting_identity_and_outside_artifacts_are_rejected(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.saved_results import discover_results
    folder,result=make_result(tmp_path,'study-a')
    result['analysis_study_uid']='study-b'
    (folder/'result.json').write_text(json.dumps(result))
    assert discover_results(tmp_path,'study-a')==[]
    result['analysis_study_uid']='study-a';result['artifact_directory']=str(tmp_path.parent)
    (folder/'result.json').write_text(json.dumps(result))
    assert discover_results(tmp_path,'study-a')==[]


def test_review_session_is_recovered_for_same_source_only(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.saved_results import discover_results, load_result
    folder,result=make_result(tmp_path,'study-a')
    session=tmp_path/'manual-reviews'/'session';session.mkdir(parents=True)
    (session/'session.json').write_text(json.dumps({'source_result':result}))
    rows=discover_results(tmp_path,'study-a')
    restored=load_result(tmp_path,'study-a',rows[0]['path'])
    assert restored['_saved_manual_session']==str(session)


def test_restored_result_exposes_review_without_submitting_inference(qapp):
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    widget=BrainVolumetryWidget(study_uid='study-a')
    result={'artifact_directory':'synthetic','analysis_study_uid':'study-a',
            'patient_context':{'study_uid':'study-a'},'posterior_rows':[], 'pdf_available':True}
    widget.restore_saved_result(result)
    assert widget._future is None
    assert widget._result['artifact_directory']=='synthetic'
    assert not widget.result_panel.isHidden()
    assert widget.pdf.isEnabled() and widget.manual_edit.isEnabled()
    widget._manual_session='unsaved-session'
    with pytest.raises(ValueError,match='active'):
        widget.restore_saved_result(result)
    assert widget._manual_session=='unsaved-session'
    widget.deleteLater()


def test_saved_panel_retains_open_error_during_automatic_refresh(qapp, monkeypatch, tmp_path):
    from concurrent.futures import Future
    from PacsClient.utils import data_paths
    from modules.ai_imaging.eagle_eye_brain.saved_results_widget import SavedBrainResultsWidget
    monkeypatch.setattr(data_paths,'AI_DIR',tmp_path)
    monkeypatch.setattr(SavedBrainResultsWidget, 'refresh', lambda *args, **kwargs: None)
    def fail(result): raise RuntimeError('synthetic failure')
    panel=SavedBrainResultsWidget(study_uid='study-a',open_result=fail)
    panel.refresh_timer.stop()
    panel._kind='open'; panel._future=Future(); panel._future.set_result({})
    panel._poll(); error=panel.status.text()
    panel._kind='discover'; panel._future=Future(); panel._future.set_result([])
    panel._poll()
    assert panel.status.text()==error
    assert panel.results.maximumHeight() <= 400
    assert panel.review_button.maximumWidth() <= 360
    panel.deleteLater()


def test_pdf_action_uses_selected_result_without_review_callback(qapp, monkeypatch, tmp_path):
    from concurrent.futures import Future
    from PySide6.QtGui import QDesktopServices
    from modules.ai_imaging.eagle_eye_brain.saved_results_widget import SavedBrainResultsWidget
    monkeypatch.setattr(SavedBrainResultsWidget, 'refresh', lambda *a, **k: None)
    calls=[]
    monkeypatch.setattr(QDesktopServices,'openUrl',lambda url:calls.append(url.toLocalFile()) or True)
    panel=SavedBrainResultsWidget(study_uid='study-a',open_result=lambda result:pytest.fail('Review callback called for PDF'))
    panel._kind='pdf';panel._future=Future()
    panel._future.set_result({'artifact_directory':str(tmp_path),'pdf_available':True})
    panel._poll()
    assert Path(calls[0])==tmp_path/'report.pdf'
    panel.deleteLater()
