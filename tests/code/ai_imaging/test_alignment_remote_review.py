"""Revision ownership and immutable parent guards using synthetic jobs only."""
import copy
import time
import uuid
import pytest
from modules.ai_imaging.eagle_eye_remote import contracts, server
from test_eagle_eye_remote import SyntheticSource, synthetic_runner, http_service
from test_eagle_eye_alignment import points


def request():
    return dict(protocol=1, request_id=uuid.uuid4().hex, module='alignment', study_uid='1.2.3',
                series={'primary': dict(series_uid='1.2.3.4', sop_uid='1.2.3.4.5', expected_count=1)}, parameters={})


def correction(parent):
    return dict(parent_job_id=parent, landmarks={s: points(s) for s in ('R','L')},
                spacing=[1.,1.], calibrated=False, flipped=False,
                acquisition_reviewed=False, landmarks_reviewed=False, notes={})


def wait(jobs, owner, identity):
    deadline = time.monotonic()+5
    while time.monotonic()<deadline:
        state=jobs.get(owner,identity)
        if state['status'] in ('succeeded','failed'):return state
        time.sleep(.01)
    pytest.fail('Synthetic job did not finish')


def test_revision_reuses_parent_sources_and_rejects_stale_or_foreign_parent(tmp_path):
    src=SyntheticSource()
    jobs=server.Jobs(tmp_path/'jobs',src,synthetic_runner)
    try:
        original=request();parent=jobs.submit('owner',original)['job_id']
        assert wait(jobs,'owner',parent)['status']=='succeeded'
        before=(jobs.root/parent/'artifacts.zip').read_bytes()
        src.stage=lambda *a: pytest.fail('Correction must not retrieve PACS again')
        edit=copy.deepcopy(original);edit['request_id']=uuid.uuid4().hex
        edit['parameters']={'correction':correction(parent)}
        with pytest.raises(KeyError):jobs.submit('other',edit)
        child=jobs.submit('owner',edit)['job_id']
        assert jobs.submit('owner',edit)['job_id']==child
        assert wait(jobs,'owner',child)['status']=='succeeded'
        assert (jobs.root/parent/'artifacts.zip').read_bytes()==before
        jobs.close()
        jobs=server.Jobs(tmp_path/'jobs',src,synthetic_runner)
        assert jobs.submit('owner',edit)['job_id']==child
        stale=copy.deepcopy(edit);stale['request_id']=uuid.uuid4().hex
        with pytest.raises(ValueError):jobs.submit('owner',stale)
    finally:jobs.close()


@pytest.mark.parametrize('field,value', [('flipped','yes'),('spacing',[0,1]),
    ('landmarks',{}),('notes',{'path':'C:/untrusted'}),('parent_job_id','../escape')])
def test_invalid_correction_rejected(field,value):
    req=request();edit=correction('a'*32);edit[field]=value;req['parameters']={'correction':edit}
    with pytest.raises(ValueError):contracts.validate(req)


def test_correction_recalculates_without_model_and_keeps_exact_edit(tmp_path, monkeypatch):
    import numpy as np
    from modules.ai_imaging.eagle_eye_remote import reviews
    from modules.ai_imaging.eagle_eye_alignment import service, report
    from modules.ai_imaging.eagle_eye_alignment.geometry import measure_bilateral
    req=request();edit=correction('a'*32);req['parameters']={'correction':edit}
    edit['landmarks']['R']['hip'][0]+=15
    image=dict(pixels=np.zeros((900,500),dtype=np.uint8), identity={}, source_sha256='a'*64,
               radiograph_binding={'version':1,'sha256':'b'*64})
    monkeypatch.setattr(service,'load_image',lambda *a:copy.deepcopy(image))
    monkeypatch.setattr(service,'predict',lambda *a:pytest.fail('No model rerun'))
    captured=[]
    def generate(im,p,prov,notes,reviewed,**kw):
        captured.append(copy.deepcopy(p))
        return dict(artifact_directory=str(tmp_path),pdf_available=True)
    monkeypatch.setattr(report,'generate_report',generate)
    result=reviews.calculate(req,[{'sop_uid':'1.2.3.4.5','path':'synthetic'}],tmp_path)
    assert captured==[edit['landmarks']]
    assert result['measurements']==measure_bilateral(edit['landmarks'],(1,1),calibrated=False)
    assert result['measurements']['R']['hka_deg'] != 0
    assert result['parent_job_id']=='a'*32


def test_ui_interrupted_report_keeps_draft_locked_until_resume(tmp_path, monkeypatch):
    from concurrent.futures import Future
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_alignment import widget
    from modules.ai_imaging.eagle_eye_remote.client import DetachedAnalysis
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(widget.AlignmentWidget,'scan_study',lambda self:None)
    view=widget.AlignmentWidget(study_uid='1.2.3')
    try:
        view._kind='report';f=Future();f.set_exception(DetachedAnalysis(tmp_path/'handle.json'));view._future=f
        view._poll()
        assert view._pending_report_handle==tmp_path/'handle.json'
        assert view.export.isEnabled() and view.export.text()=='Resume server result'
        assert not view.canvas.isEnabled() and not view.browse.isEnabled()
    finally:view.teardown();view.deleteLater();app.processEvents()


def test_http_correction_round_trip_and_conflict(http_service, tmp_path):
    from modules.ai_imaging.eagle_eye_remote.client import Client
    jobs, cfg = http_service
    client = Client(cfg)
    req = request()
    original = client.analyze('alignment', req['study_uid'], req['series'], {}, tmp_path/'client')
    parent = original['server_job_id']
    edit = correction(parent)
    child = client.analyze('alignment', req['study_uid'], req['series'],
                           {'correction': edit}, tmp_path/'client')
    assert child['server_job_id'] != parent
    assert jobs.get('first',child['server_job_id'])['parent_job_id'] == parent
    with pytest.raises(ValueError, match='newer server correction'):
        client.analyze('alignment', req['study_uid'], req['series'],
                       {'correction': edit}, tmp_path/'client')
