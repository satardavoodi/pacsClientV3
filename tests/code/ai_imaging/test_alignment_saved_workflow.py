"""Synthetic progress and exact-source restoration; never open the live database."""
import json
import threading
from concurrent.futures import Future

import pytest
from test_eagle_eye_alignment import image, points, qapp


def archive(tmp_path):
    im = image()
    im['identity'].update(series_uid='1.2.3.4', sop_uid='1.2.3.4.5')
    result = dict(server_module='alignment', remote_analysis=True, server_job_id='a'*32,
                  artifact_directory=str(tmp_path), landmarks={'R': points(), 'L': points('L')},
                  source_binding=[dict(im['identity'], sha256=im['source_sha256'])])
    (tmp_path/'result.json').write_text(json.dumps(result))
    return im, result


def test_running_operation_has_visible_top_progress(qapp):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    w = AlignmentWidget(study_uid='1.2.3')
    gate = threading.Event()
    try:
        w._submit('scan', lambda: gate.wait(5))
        assert not w.progress.isHidden()
        assert w.layout().indexOf(w.status) == 1
        w._progress_messages.put('Server is retrieving images from PACS')
        w._poll()
        assert 'retrieving' in w.status.text()
    finally:
        gate.set(); w.teardown(); w.close()


def test_saved_detection_restores_without_new_analysis(qapp, monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    im, result = archive(tmp_path)
    w = AlignmentWidget(study_uid='1.2.3'); w.preferred_series_uid='1.2.3.4'
    calls=[]
    monkeypatch.setattr(w, 'start_ai', lambda **kw: calls.append(kw))
    f=Future(); f.set_result(dict(image=im, saved=dict(result=result, image=im, notes={})))
    w._future=f; w._kind='load'; w._poll()
    assert not calls
    assert w.points == result['landmarks'] and w.metrics is not None
    assert not w.confirm.isChecked() and not w.review.isChecked()
    w.teardown(); w.close()


def test_saved_source_mismatch_is_rejected(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.saved_review import restore
    im, result = archive(tmp_path)
    result['source_binding'][0]['sop_uid']='9.9'
    with pytest.raises(ValueError): restore(result, im)


def test_saved_report_restores_scale_flip_notes_and_checks_pdf(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.saved_review import restore
    from modules.ai_imaging.eagle_eye_alignment.service import digest
    im, result = archive(tmp_path)
    result['pdf_available']=True
    (tmp_path/'report.pdf').write_bytes(b'%PDF-synthetic')
    payload=dict(identity=im['identity'],landmarks=result['landmarks'], spacing=[.3,.4],
                 calibrated=True,calibration_method='Synthetic scale',horizontal_flip=True,
                 notes={'impression':'Synthetic note'}, pdf_sha256=digest(tmp_path/'report.pdf'))
    (tmp_path/'report.json').write_text(json.dumps(payload))
    state=restore(result, im)
    assert state['image']['spacing']==(.3,.4) and state['image']['flipped']
    assert state['notes']==payload['notes']
    (tmp_path/'report.pdf').write_bytes(b'changed')
    with pytest.raises(ValueError): restore(result, im)


def test_radiograph_forwards_progress(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import routing
    im=image(); im['identity'].update(series_uid='1.2.3.4',sop_uid='1.2.3.4.5')
    seen=[]
    class Client:
        def analyze(self,*args,**kwargs):
            kwargs['progress']('Server is analyzing the study')
            return dict(source_binding=[dict(im['identity'],sha256=im['source_sha256'])])
    monkeypatch.setattr(routing,'Client',Client)
    routing.radiograph('alignment',im,threading.Event(),progress=seen.append)
    assert seen==['Server is analyzing the study']


def test_restored_report_can_submit_a_new_server_report(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_alignment.saved_review import restore
    from modules.ai_imaging.eagle_eye_alignment.service import digest
    from modules.ai_imaging.eagle_eye_remote import routing, contracts
    im, result = archive(tmp_path)
    result['pdf_available'] = True
    (tmp_path/'report.pdf').write_bytes(b'%PDF-synthetic')
    payload = dict(identity=im['identity'], landmarks=result['landmarks'], spacing=[.1,.1],
                   calibrated=False, horizontal_flip=False, notes={},
                   pdf_sha256=digest(tmp_path/'report.pdf'))
    (tmp_path/'report.json').write_text(json.dumps(payload))
    state = restore(result, im)
    accepted = []
    class Client:
        def json(self, endpoint):
            return {'correction_modules': ['alignment']}
        def analyze(self, module, study, series, parameters, destination, **kwargs):
            accepted.append(contracts.validate(dict(protocol=1, request_id='c'*32,
                module=module, study_uid=study, series=series, parameters=parameters)))
            return result
    monkeypatch.setattr(routing, 'Client', Client)
    routing.alignment_correction(state['image'], result['landmarks'], result, {}, False)
    assert len(accepted) == 1
    assert accepted[0]['parameters']['correction']['spacing'] == [.1,.1]


def test_archive_transfers_alignment_review_metadata(tmp_path):
    import zipfile
    from modules.ai_imaging.eagle_eye_remote.artifacts import publish
    job=tmp_path/'job'; job.mkdir(); out=job/'output'; out.mkdir()
    (out/'report.json').write_text('{"format_version":4}')
    request=dict(protocol=1,request_id='a'*32,module='alignment',study_uid='1.2.3')
    publish(job,request,[],dict(artifact_directory=str(out)))
    with zipfile.ZipFile(job/'artifacts.zip') as archive:
        assert 'report.json' in archive.namelist()


def test_legacy_report_recovers_only_matching_durable_request(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.saved_review import restore
    folder=tmp_path/'remote-result'; folder.mkdir()
    im,result=archive(folder); result['pdf_available']=True; result['parent_job_id']='b'*32
    (folder/'report.pdf').write_bytes(b'%PDF-synthetic')
    handles=tmp_path/'.eagle-eye-jobs'; handles.mkdir()
    correction=dict(parent_job_id='b'*32,landmarks=result['landmarks'],spacing=[.3,.4],calibrated=True,
                    flipped=True,acquisition_reviewed=False,landmarks_reviewed=False,notes={})
    handle=dict(job_id=result['server_job_id'],request=dict(module='alignment',study_uid=im['identity']['study_uid'],
                series={'primary':dict(series_uid='1.2.3.4',sop_uid='1.2.3.4.5')},parameters={'correction':correction}))
    path=handles/'handle.json'; path.write_text(json.dumps(handle))
    assert restore(result,im)['image']['spacing']==(.3,.4)
    handle['job_id']='c'*32; path.write_text(json.dumps(handle))
    with pytest.raises(ValueError): restore(result,im)


def test_lookup_does_not_reuse_other_series_or_hide_corrupt_latest(tmp_path):
    from modules.ai_imaging.eagle_eye_alignment.saved_review import find
    folder=tmp_path/'remote-example'; folder.mkdir()
    im,result=archive(folder)
    assert find(im,tmp_path)['result']['server_job_id']==result['server_job_id']
    im['identity']['series_uid']='9.9'
    assert find(im,tmp_path) is None
    im['identity']['series_uid']='1.2.3.4'
    result['source_binding'][0]['sha256']='changed'
    (folder/'result.json').write_text(json.dumps(result))
    with pytest.raises(ValueError):find(im,tmp_path)


def test_history_uses_saved_series_session_without_scan(qapp, monkeypatch, tmp_path):
    from types import SimpleNamespace
    from PySide6.QtWidgets import QWidget,QTabWidget
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentWidget
    im,result=archive(tmp_path)
    window=QWidget();window._study_uid='1.2.3';window.eagle_eye_mode='bone_age'
    window.imaging_tab=SimpleNamespace();window.tab_widget=QTabWidget(window)
    controller=EagleEyeWorkspaceController(window)
    monkeypatch.setattr(controller,'selected_series_uid',lambda:'9.9')
    calls=[]
    monkeypatch.setattr(AlignmentWidget,'scan_study',lambda self:pytest.fail('No scan/rerun on restore'))
    monkeypatch.setattr(AlignmentWidget,'restore_saved_result',lambda self,value:calls.append(value))
    try:
        controller.open_alignment(saved_result=result)
        assert controller._session_keys['alignment']=='1.2.3.4'
        assert calls==[result]
    finally:controller.teardown();window.deleteLater();qapp.processEvents()
