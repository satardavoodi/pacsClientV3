"""Synthetic client/server correction contracts; no patient database."""
import copy
import json
import uuid

import pytest
from modules.ai_imaging.eagle_eye_brain.contracts import BrainError
from test_eagle_eye_remote import http_service

from modules.ai_imaging.eagle_eye_remote import contracts, artifacts


def request(module, correction):
    roles = {'primary': dict(series_uid='1.2.3.4', sop_uid='1.2.3.4.5', expected_count=1)}
    if module.startswith('brain'):
        roles = {'t1': dict(series_uid='1.2.3.4', expected_count=1)}
        if module == 'brain-lesions':
            roles['flair'] = dict(series_uid='1.2.3.6', expected_count=1)
    return dict(protocol=1, request_id=uuid.uuid4().hex, module=module,
                study_uid='1.2.3', series=roles, parameters={'correction': correction})


@pytest.mark.parametrize('module', ['brain', 'brain-lesions'])
def test_remote_brain_result_includes_editable_reference_and_mask(tmp_path, module):
    job = tmp_path / ('a' * 32); root = job / 'work'; root.mkdir(parents=True)
    lesion = module == 'brain-lesions'
    for name in ('flair.nii.gz', 'resampled.nii.gz', 'labels.nii.gz', 'space-flair_seg-lst.nii.gz'):
        (root / name).write_bytes(b'synthetic')
    (root / 'label_names.json').write_text('{"1":"Synthetic label"}')
    result = dict(artifact_directory=str(root))
    if lesion:
        result.update(analysis_type='brain_lesions', mask_path=str(root / 'space-flair_seg-lst.nii.gz'))
    req = request(module, {}); req['parameters'] = {}
    artifacts.publish(job, req, [], result)
    import zipfile
    with zipfile.ZipFile(job / 'artifacts.zip') as archive:
        packet = json.loads(archive.read('envelope.json'))['result']
        assert packet['review_assets']['image']['artifact'] in archive.namelist()
        assert packet['review_assets']['mask']['artifact'] in archive.namelist()
        assert packet['analysis_series'] == req['series']
        assert 't1.nii.gz' not in archive.namelist()


def test_spine_correction_is_admitted_on_existing_job_contract():
    value = dict(parent_job_id='a'*32, views=[dict(role='primary', projection='coronal',
        spacing=[1, 1], calibrated=False, radiograph_binding={'version': 1, 'sha256': 'a'*64},
        review_protocol='selected-endplates-v1', points={}, markers={}, pedicles={}, curves=[],
        rotations=[], positive_image_right=False, acquisition_confirmed=True, landmarks_reviewed=False)],
        reviewed=False, notes='')
    assert contracts.validate(request('total-spine', value))['parameters']['correction'] == value


def label_images():
    import numpy as np
    import SimpleITK as sitk
    original = sitk.GetImageFromArray(np.ones((3, 4, 5), dtype=np.uint16))
    original.SetSpacing((1, 2, 3)); original.SetOrigin((2, 3, 4))
    edited = sitk.Image(original); edited[0, 0, 0] = 0
    return original, edited


@pytest.mark.parametrize('module', ['brain', 'brain-lesions'])
def test_mask_round_trip_keeps_parent_geometry_and_only_changes_labels(module):
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    original, edited = label_images()
    payload = review.encode(original, edited, 'a'*32, 'b'*64)
    assert contracts.validate(request(module, payload))
    restored = review.decode(payload, original)
    assert restored.GetOrigin() == original.GetOrigin()
    assert restored.GetSpacing() == original.GetSpacing()
    assert (sitk.GetArrayFromImage(restored) == sitk.GetArrayFromImage(edited)).all()
    assert original[0, 0, 0] == 1


@pytest.mark.parametrize('kind', ['geometry', 'label', 'shape', 'expanded', 'trailing', 'oversize'])
def test_invalid_mask_cannot_become_a_server_revision(kind):
    import base64
    import zlib
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    original, edited = label_images()
    if kind == 'geometry':
        edited.SetOrigin((0, 0, 0))
        with pytest.raises((ValueError, BrainError)):
            review.encode(original, edited, 'a'*32, 'b'*64)
        return
    value = review.encode(original, edited, 'a'*32, 'b'*64)
    if kind == 'label':
        value['labels_zlib'] = base64.b64encode(zlib.compress(b'\x02\x00' * 60)).decode()
    elif kind == 'shape': value['shape'] = [3, 4, 6]
    elif kind == 'expanded': value['labels_zlib'] = base64.b64encode(zlib.compress(b'\0' * 100000)).decode()
    elif kind == 'trailing': value['labels_zlib'] += 'AAAA'
    elif kind == 'oversize': value['shape'] = [2048, 2048, 2048]
    with pytest.raises((ValueError, BrainError)): review.decode(value, original)


@pytest.mark.parametrize('module', ['brain', 'brain-lesions'])
def test_brain_server_revisions_remeasure_and_preserve_parent(tmp_path, monkeypatch, module):
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    from modules.ai_imaging.eagle_eye_brain import organized_report, lesion_report, ms_assessment
    original, edited = label_images()
    parent = tmp_path / ('a'*32); root = parent / 'work'; root.mkdir(parents=True)
    sitk.WriteImage(original, str(root/'labels.nii.gz'))
    sitk.WriteImage(original, str(root/'resampled.nii.gz'))
    sitk.WriteImage(original, str(root/'flair.nii.gz'))
    (root/'label_names.json').write_text('{"1":"Synthetic label"}')
    prior = dict(artifact_directory=str(root), posterior_rows=[{'synthetic': True}])
    if module == 'brain-lesions':
        prior.update(analysis_type='brain_lesions', mask_path=str(root/'labels.nii.gz'),
                     clinical_context={'primary_disease': 'other'}, lesion_topography={'stale': True})
    (parent/'worker-result.json').write_text(json.dumps(prior))
    before = (root/'labels.nii.gz').read_bytes()
    monkeypatch.setattr(organized_report, 'write_paged_pdf', lambda html, path, **kw: path.write_bytes(b'test'))
    monkeypatch.setattr(lesion_report, 'write_lesion_report', lambda r, i, m, d: (d/'report.pdf').write_bytes(b'test'))
    def topography(result, context_root, **kw):
        assert context_root == root
        assert 'lesion_topography' not in result
        return {'status': 'recalculated'}
    monkeypatch.setattr(ms_assessment, 'enrich_ms', topography)
    child = tmp_path / ('c'*32); (child/'work').mkdir(parents=True)
    payload = review.encode(original, edited, parent.name, contracts.digest(root/'labels.nii.gz'))
    result = review.calculate(request(module, payload), child/'work')
    measured = result['metrics']['total_volume_cm3'] if module == 'brain-lesions' else result['manual_rows'][0]['volume_cm3']
    assert measured == pytest.approx(59 * .006)
    assert result['posterior_rows'] == prior['posterior_rows']
    assert (root/'labels.nii.gz').read_bytes() == before
    (child/'worker-result.json').write_text(json.dumps(result))
    selected = review.assets(result)
    second_original = sitk.ReadImage(str(selected['mask']))
    second_edit = sitk.Image(second_original); second_edit[1, 0, 0] = 0
    second_payload = review.encode(second_original, second_edit, child.name, contracts.digest(selected['mask']))
    next_root = tmp_path / ('d'*32) / 'work'; next_root.mkdir(parents=True)
    second = review.calculate(request(module, second_payload), next_root)
    measured = second['metrics']['total_volume_cm3'] if module == 'brain-lesions' else second['manual_rows'][0]['volume_cm3']
    assert measured == pytest.approx(58 * .006)
    assert second['parent_job_id'] == child.name


def test_remote_manual_recalculate_never_calls_local_measurement(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import manual_review
    from modules.ai_imaging.eagle_eye_remote import segmentation_review
    (tmp_path/'session.json').write_text(json.dumps({'source_result': {'remote_analysis': True}}))
    monkeypatch.setattr(manual_review, '_recalculate_review', lambda *a, **kw: pytest.fail('Local calculation'))
    monkeypatch.setattr(segmentation_review, 'submit', lambda *a, **kw: {'server_job_id': 'b'*32})
    assert manual_review.recalculate_review(tmp_path)['server_job_id'] == 'b'*32


def spine_snapshot():
    return dict(role='primary', projection='coronal', spacing=[1, 1], calibrated=False,
        radiograph_binding={'version': 1, 'sha256': 'a'*64}, review_protocol='selected-endplates-v1',
        points={'T4': {'superior_left': [10, 20], 'superior_right': [30, 20]},
                'T12': {'inferior_left': [10, 60], 'inferior_right': [30, 70]}},
        markers={}, pedicles={}, curves=[dict(name='Scoliosis Cobb', upper='T4', lower='T12',
            lower_endplate='inferior', endplates_reviewed=False)], rotations=[],
        positive_image_right=False, acquisition_confirmed=True, landmarks_reviewed=False)


def test_two_spine_projections_can_share_series_but_not_instance():
    first = spine_snapshot(); second = copy.deepcopy(first)
    second.update(role='secondary', projection='lateral')
    req = request('total-spine', dict(parent_job_id=None, views=[first, second], reviewed=False, notes=''))
    req['series']['secondary'] = dict(req['series']['primary'], sop_uid='1.2.3.4.6')
    assert contracts.validate(req)
    req['series']['secondary']['sop_uid'] = req['series']['primary']['sop_uid']
    with pytest.raises(ValueError): contracts.validate(req)


def test_spine_box_segmentation_supports_lateral_in_existing_api():
    req = request('total-spine', {})
    req['parameters'] = dict(model='sam', projection='lateral', level='L3', region=[10, 20, 40, 60])
    assert contracts.validate(req)
    req['parameters']['level'] = 'S1'
    with pytest.raises(ValueError): contracts.validate(req)


def test_spine_segmentation_on_standard_routes_to_server(monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import settings, routing
    from modules.ai_imaging.eagle_eye_total_spine import assist_service
    monkeypatch.setattr(settings, 'remote_required', lambda: True)
    monkeypatch.setattr(assist_service, '_run', lambda *a, **kw: pytest.fail('No client model'))
    monkeypatch.setattr(routing, 'spine_segmentation', lambda *a: {'origin': 'server', 'level': a[1]})
    assert assist_service.segment_body({}, 'L3', [1, 2, 3, 4], None)['origin'] == 'server'


def test_server_spine_mask_is_a_portable_artifact(tmp_path, monkeypatch):
    import numpy as np
    from modules.ai_imaging.eagle_eye_remote import adapters
    from modules.ai_imaging.eagle_eye_alignment import service as alignment
    from modules.ai_imaging.eagle_eye_total_spine import service, assist_service
    image = dict(radiograph_binding={'version': 1, 'sha256': 'a'*64})
    monkeypatch.setattr(alignment, 'load_image', lambda *a: image)
    monkeypatch.setattr(service, 'load_view', lambda *a: image)
    mask = np.ones((8, 8), dtype=bool)
    monkeypatch.setattr(assist_service, 'segment_body', lambda *a: dict(mask=mask.copy(), level='L3'))
    req = request('total-spine', {})
    req['parameters'] = dict(model='sam', projection='lateral', level='L3', region=[1, 2, 3, 4])
    job = tmp_path / ('a'*32); job.mkdir()
    result = adapters.execute(req, [dict(sop_uid='1.2.3.4.5', path='synthetic')], job/'work')
    assert 'mask' not in result
    assert np.array_equal(np.load(result['mask_file'], allow_pickle=False), mask)
    artifacts.publish(job, req, [], result)
    import zipfile
    with zipfile.ZipFile(job/'artifacts.zip') as archive:
        assert 'spine-mask.npy' in archive.namelist()


def test_large_mask_handle_resumes_without_changing_request(tmp_path, monkeypatch):
    import numpy as np
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    from modules.ai_imaging.eagle_eye_remote.client import Client, save_handle
    import hashlib
    original = sitk.GetImageFromArray(np.random.default_rng(1).integers(0, 3, (80, 80, 80), dtype=np.uint16))
    correction = review.encode(original, original, 'a'*32, 'b'*64)
    req = request('brain', correction)
    assert len(json.dumps(req)) > 65536
    monkeypatch.setenv('SYNTHETIC_REVIEW_TOKEN', 'a'*64)
    client = Client({'url': 'http://127.0.0.1:8002', 'token_env': 'SYNTHETIC_REVIEW_TOKEN'})
    handle = dict(version=1, server=client.url, credential_binding=hashlib.sha256(client.token.encode()).hexdigest(),
                  request=req, job_id=None)
    path = tmp_path/'pending.json'; save_handle(path, handle)
    monkeypatch.setattr(client, '_observe', lambda value, *a, **kw: value['request'])
    assert client.resume(path, tmp_path) == req


def test_spine_disconnection_locks_draft_and_exposes_resume(monkeypatch, tmp_path):
    from concurrent.futures import Future
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_total_spine.widget import TotalSpineWidget
    from modules.ai_imaging.eagle_eye_remote.client import DetachedAnalysis
    app = QApplication.instance() or QApplication([])
    widget = TotalSpineWidget(study_uid='1.2.3')
    try:
        widget._kind = 'report'; widget._target = None
        future = Future(); future.set_exception(DetachedAnalysis(tmp_path/'pending.json'))
        widget._future = future
        widget._poll()
        assert not widget.tabs.isEnabled()
        assert widget.draft.text() == 'Resume server result'
        assert widget.draft.isEnabled()
    finally:
        widget.teardown(); widget.deleteLater(); app.processEvents()


def test_result_download_disconnect_resumes_same_job(http_service, tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote.client import Client, DetachedAnalysis
    jobs, cfg = http_service
    client = Client(cfg); original_open = client.open
    def interrupted(path, *args, **kwargs):
        if path.endswith('/artifacts'):
            raise RuntimeError('Synthetic connection loss')
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(client, 'open', interrupted)
    with pytest.raises(DetachedAnalysis) as caught:
        client.analyze('bone-age', '1.2.3', {}, {}, tmp_path/'client')
    assert len(jobs.jobs) == 1
    monkeypatch.setattr(client, 'open', original_open)
    result = client.resume(caught.value.handle_path, tmp_path/'client')
    assert result['server_job_id'] in jobs.jobs
    assert len(jobs.jobs) == 1


def test_failed_pending_mask_unlocks_retry_without_local_calculation(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    from modules.ai_imaging.eagle_eye_remote.client import AnalysisFailed
    (tmp_path/'session.json').write_text(json.dumps({'lesion': False, 'source_result': {}}))
    (tmp_path/'pending-server-review.json').write_text(json.dumps({'handle': 'synthetic'}))
    class FakeClient:
        def json(self, *a): return {'correction_modules': ['brain']}
        def resume(self, *a, **kw): raise AnalysisFailed('Synthetic terminal failure')
    from modules.ai_imaging.eagle_eye_remote import client
    monkeypatch.setattr(client, 'Client', FakeClient)
    with pytest.raises(AnalysisFailed): review.submit(tmp_path)
    assert not (tmp_path/'pending-server-review.json').exists()


def test_lesion_disconnect_cannot_display_old_metrics_as_new_success(tmp_path):
    from concurrent.futures import Future
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.lesion_widget import BrainLesionWidget
    from modules.ai_imaging.eagle_eye_remote.client import DetachedAnalysis
    app = QApplication.instance() or QApplication([])
    view = BrainLesionWidget()
    try:
        view._result = {'metrics': {'candidate_count': 2, 'total_volume_cm3': 1.}}
        view._future_kind = 'manual_recalculate'
        future = Future(); future.set_exception(DetachedAnalysis(tmp_path/'pending.json'))
        view._future = future
        view._poll()
        assert 'interrupted' in view.status.text()
        assert view.manual_recalculate.text() == 'Resume server correction'
    finally:
        view.close(); view.deleteLater(); app.processEvents()


def test_empty_lesion_mask_allows_reader_to_add_first_binary_candidate():
    import numpy as np
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    from modules.ai_imaging.eagle_eye_brain.manual_slicer import segment_labels
    assert segment_labels(np.zeros((3, 3, 3)), lesion=True) == [1]
    original = sitk.GetImageFromArray(np.zeros((3, 3, 3), dtype=np.uint16))
    edited = sitk.Image(original); edited[1, 1, 1] = 1
    value = review.encode(original, edited, 'a'*32, 'b'*64, lesion=True)
    assert review.decode(value, original, lesion=True)[1, 1, 1] == 1
    edited[1, 1, 1] = 2
    with pytest.raises(BrainError): review.encode(original, edited, 'a'*32, 'b'*64, lesion=True)


def test_server_spine_angle_changes_without_inference(tmp_path, monkeypatch):
    import numpy as np
    from modules.ai_imaging.eagle_eye_remote import spine_review
    from modules.ai_imaging.eagle_eye_total_spine import service, report
    def load(path, study, series, projection):
        return dict(pixels=np.zeros((100, 100), dtype=np.uint8), spacing=(1, 1), calibrated=False,
            projection=projection, source_sha256='b'*64,
            identity={'study_uid': study, 'series_uid': series, 'sop_uid': '1.2.3.4.5'},
            radiograph_binding={'version': 1, 'sha256': 'a'*64})
    monkeypatch.setattr(service, 'load_view', load)
    monkeypatch.setattr(service, 'predict', lambda *a: pytest.fail('No inference for manual corrections'))
    monkeypatch.setattr(report, 'generate_report', lambda *a, **kw: {'artifact_directory': str(tmp_path)})
    snapshot = spine_snapshot()
    value = dict(parent_job_id='a'*32, views=[snapshot], reviewed=False, notes='')
    req = request('total-spine', value)
    records = [dict(path='synthetic', series_uid='1.2.3.4', sop_uid='1.2.3.4.5')]
    first = spine_review.calculate(req, records, tmp_path)
    snapshot['points']['T12']['inferior_right'][1] = 60
    second = spine_review.calculate(req, records, tmp_path)
    assert first['measurements'] != second['measurements']
    assert second['clinical_report_signed'] is False
    snapshot['radiograph_binding']['sha256'] = 'f'*64
    with pytest.raises(ValueError, match='geometry'):
        spine_review.calculate(req, records, tmp_path)


def test_brain_pending_result_cannot_start_a_different_analysis(monkeypatch):
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app = QApplication.instance() or QApplication([])
    view = BrainVolumetryWidget()
    try:
        view._pending_manual_review = True
        view._start()
        assert 'Resume' in view.status.text()
        assert view._future is None
    finally:
        view.close(); view.deleteLater(); app.processEvents()


@pytest.mark.parametrize('module', ['brain', 'brain-lesions', 'total-spine'])
def test_existing_http_jobs_support_new_revisions_and_conflicts(http_service, tmp_path, module):
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_remote.client import Client
    from modules.ai_imaging.eagle_eye_remote import segmentation_review as review
    jobs, cfg = http_service
    original, edited = label_images()
    def runner(job, cancel):
        root = job/'work'; root.mkdir()
        result = dict(artifact_directory=str(root), pdf_available=True)
        (root/'report.pdf').write_bytes(b'synthetic')
        if module.startswith('brain'):
            for name in ('flair.nii.gz', 'resampled.nii.gz', 'labels.nii.gz'):
                sitk.WriteImage(original, str(root/name))
            (root/'label_names.json').write_text('{"1":"Synthetic"}')
            if module == 'brain-lesions':
                result.update(analysis_type='brain_lesions', mask_path=str(root/'labels.nii.gz'))
        return result
    jobs.runner = runner
    client = Client(cfg)
    req = request(module, {})
    params = {'region': [0, 0, 100, 100]} if module == 'total-spine' else {}
    parent = client.analyze(module, req['study_uid'], req['series'], params, tmp_path/'client')
    if module == 'total-spine':
        value = dict(parent_job_id=parent['server_job_id'], views=[spine_snapshot()], reviewed=False, notes='')
    else:
        value = review.encode(original, edited, parent['server_job_id'], contracts.digest(parent['review_assets']['mask']))
    child = client.analyze(module, req['study_uid'], req['series'], {'correction': value}, tmp_path/'client')
    assert child['server_job_id'] != parent['server_job_id']
    with pytest.raises(ValueError, match='newer server correction'):
        client.analyze(module, req['study_uid'], req['series'], {'correction': value}, tmp_path/'client')
    foreign = dict(cfg, token_env='SYNTHETIC_FOREIGN_TOKEN')
    import os
    old = os.environ.get('SYNTHETIC_FOREIGN_TOKEN')
    os.environ['SYNTHETIC_FOREIGN_TOKEN'] = 'b'*64
    try:
        with pytest.raises(ValueError, match='rejected'):
            Client(foreign).analyze(module, req['study_uid'], req['series'], {'correction': value}, tmp_path/'foreign')
    finally:
        if old is None: os.environ.pop('SYNTHETIC_FOREIGN_TOKEN', None)
        else: os.environ['SYNTHETIC_FOREIGN_TOKEN'] = old
