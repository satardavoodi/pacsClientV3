"""Synthetic-only HTTP, source and artifact boundary tests; no live PACS/database."""
import hashlib
from http.server import ThreadingHTTPServer
import io
import json
from pathlib import Path
import threading
import time
import urllib.request
import urllib.error
import uuid
import zipfile

import pytest

from modules.ai_imaging.eagle_eye_remote import contracts, artifacts, client, server, source, settings


def request(module='bone-age'):
    return dict(protocol=1, request_id=uuid.uuid4().hex, module=module, study_uid='1.2.3', series={}, parameters={})


@pytest.mark.parametrize('field,value', [('path', 'C:/patient.dcm'), ('pixels', [1, 2]), ('url', 'https://untrusted/')])
def test_request_rejects_client_paths_pixels_and_urls(field, value):
    value = {**request(), field: value}
    with pytest.raises(ValueError):
        contracts.validate(value)


def test_request_requires_exact_series_roles_and_count():
    value = request('brain-lesions')
    with pytest.raises(ValueError):
        contracts.validate(value)
    value['series'] = {'t1': {'series_uid': '1.2.3.4', 'expected_count': 3},
                       'flair': {'series_uid': '1.2.3.5', 'expected_count': 3}}
    assert contracts.validate(value) == value
    value['series']['flair']['series_uid'] = '1.2.3.4'
    with pytest.raises(ValueError):
        contracts.validate(value)


class SyntheticSource:
    def stage(self, request, destination, cancel):
        destination.mkdir()
        path = destination / 'synthetic.dcm'
        path.write_bytes(b'fixture-source-not-an-export')
        return [dict(path=str(path), study_uid='1.2.3', series_uid='1.2.3.4', sop_uid='1.2.3.4.5',
                     sha256=contracts.digest(path), roles=['primary'])]


def synthetic_runner(job, cancel):
    directory = job / 'work'
    directory.mkdir()
    (directory / 'report.pdf').write_bytes(b'%PDF-1.4 synthetic')
    (directory / 't1.nii.gz').write_bytes(b'private-source-volume')
    (directory / 'model.pth').write_bytes(b'private-weight')
    (directory / 'process-diagnostics.jsonl').write_text('{"private":"synthetic"}\n')
    return {'status': 'review_required', 'artifact_directory': str(directory),
            'report': str(directory / 'report.pdf'), 'pdf_available': True, 'value': 12.5}


@pytest.fixture
def http_service(tmp_path, monkeypatch):
    jobs = server.Jobs(tmp_path / 'server', SyntheticSource(), synthetic_runner)
    token = 'a' * 64
    monkeypatch.setenv('EAGLE_TEST_TOKEN', token)
    http = ThreadingHTTPServer(('127.0.0.1', 0), server.handler(jobs, {'first': token, 'second': 'b' * 64}))
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    cfg = {'url': f'http://127.0.0.1:{http.server_port}', 'token_env': 'EAGLE_TEST_TOKEN'}
    try:
        yield jobs, cfg
    finally:
        http.shutdown()
        http.server_close()
        jobs.close()
        worker.join(timeout=3)


def test_http_reference_job_returns_only_derived_artifacts(http_service, tmp_path):
    jobs, cfg = http_service
    result = client.Client(cfg).analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client')
    directory = Path(result['artifact_directory'])
    assert result['value'] == 12.5
    assert Path(result['report']).read_bytes() == b'%PDF-1.4 synthetic'
    assert not (directory / 't1.nii.gz').exists()
    assert not (directory / 'model.pth').exists()
    assert not (directory / 'process-diagnostics.jsonl').exists()
    assert result['source_binding'][0]['sop_uid'] == '1.2.3.4.5'
    body = json.loads(next(jobs.root.glob('*/request.json')).read_text())
    assert set(body) == {'protocol', 'request_id', 'module', 'study_uid', 'series', 'parameters'}
    assert 'fixture-source' not in json.dumps(body)


def test_transport_loss_does_not_cancel_server_work(http_service, tmp_path, monkeypatch):
    _, cfg = http_service
    connection = client.Client(cfg)
    actual = connection.json
    cancellations = []

    def interrupted(path, body=None, method=None):
        if path.endswith('/cancel'):
            cancellations.append(path)
        if path.startswith('/v1/jobs/') and body is None:
            raise RuntimeError('Synthetic disconnected transport')
        return actual(path, body, method)

    monkeypatch.setattr(connection, 'json', interrupted)
    with pytest.raises(RuntimeError):
        connection.analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client')
    assert cancellations == []


def test_uncertain_submission_resumes_same_request_without_second_inference(http_service, tmp_path, monkeypatch):
    jobs, cfg = http_service
    connection = client.Client(cfg)
    actual = connection.json

    def lose_ack(path, body=None, method=None):
        result = actual(path, body, method)
        if path == '/v1/jobs' and body:
            raise RuntimeError('Synthetic lost submission acknowledgement')
        return result

    monkeypatch.setattr(connection, 'json', lose_ack)
    with pytest.raises(RuntimeError):
        connection.analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client')
    handles = list((tmp_path / 'client' / '.eagle-eye-jobs').glob('*.json'))
    assert len(handles) == 1
    result = client.Client(cfg).resume(handles[0], tmp_path / 'resumed')
    assert result['value'] == 12.5
    assert len(jobs.jobs) == 1


def test_explicit_client_cancel_still_cancels_owned_job(http_service, tmp_path, monkeypatch):
    _, cfg = http_service
    connection = client.Client(cfg)
    actual = connection.json
    cancelled = threading.Event()
    calls = []

    def cancel_after_ack(path, body=None, method=None):
        calls.append(path)
        result = actual(path, body, method)
        if path == '/v1/jobs' and body:
            cancelled.set()
        return result

    monkeypatch.setattr(connection, 'json', cancel_after_ack)
    with pytest.raises(RuntimeError, match='cancelled'):
        connection.analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client', cancel=cancelled)
    assert len([p for p in calls if p.endswith('/cancel')]) == 1


def test_observation_timeout_is_detached_and_handle_is_credential_bound(http_service, tmp_path):
    jobs, cfg = http_service
    with pytest.raises(client.DetachedAnalysis) as error:
        client.Client(cfg).analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client', timeout=0)
    handle = error.value.handle_path
    original = json.loads(handle.read_text())
    assert original['job_id'] in jobs.jobs
    assert 'a' * 64 not in handle.read_text()
    original['credential_binding'] = 'wrong-owner'
    handle.write_text(json.dumps(original))
    with pytest.raises(ValueError, match='another server or credential'):
        client.Client(cfg).resume(handle, tmp_path / 'resumed')


def test_tls_listener_requires_trusted_certificate_and_matching_host(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import ipaddress
    import secrets
    import socket
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic Eagle Eye test')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256()))
    cert_path, key_path, token_path = (tmp_path / name for name in ('fixture.pem', 'fixture.key', 'fixture.token'))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    token_path.write_text(secrets.token_hex(32), encoding='utf-8')
    monkeypatch.delenv('EAGLE_TLS_FIXTURE_TOKEN', raising=False)
    monkeypatch.setattr(source, 'source_provider', lambda cfg: SyntheticSource())
    http, jobs = server.create_server(dict(host='127.0.0.1', port=0,
        job_root=str(tmp_path / 'server'), pacs={}, clients={'fixture': str(token_path)},
        certificate=str(cert_path), private_key=str(key_path)))
    jobs.runner = synthetic_runner
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    cfg = dict(url=f'https://127.0.0.1:{http.server_port}', token_file=str(token_path),
               token_env='EAGLE_TLS_FIXTURE_TOKEN', ca_file=str(cert_path))
    try:
        # A peer that connects but never begins TLS must not block other clients.
        stalled_peer = socket.create_connection(('127.0.0.1', http.server_port), timeout=3)
        try:
            connection = client.Client(cfg)
            probe = urllib.request.Request(cfg['url'] + '/v1/capabilities',
                headers={'Authorization': 'Bearer ' + connection.token})
            with connection.opener.open(probe, timeout=2) as response:
                assert json.load(response)['protocol'] == 1
        finally:
            stalled_peer.close()
        assert client.Client(cfg).json('/v1/capabilities')['input_mode'] == 'pacs_references'
        result = client.Client(cfg).analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client')
        assert Path(result['report']).read_bytes() == b'%PDF-1.4 synthetic'
        for invalid in ({**cfg, 'ca_file': ''},
                        {**cfg, 'url': f'https://localhost:{http.server_port}'}):
            invalid_client = client.Client(invalid)
            with pytest.raises(urllib.error.URLError) as failure:
                invalid_client.opener.open(invalid['url'] + '/v1/capabilities', timeout=3)
            assert isinstance(failure.value.reason, ssl.SSLCertVerificationError)
            with pytest.raises(RuntimeError, match='request failed'):
                invalid_client.json('/v1/capabilities')
    finally:
        http.shutdown()
        http.server_close()
        jobs.close()
        worker.join(timeout=3)


def test_http_authentication_ownership_and_idempotency(http_service, monkeypatch):
    jobs, cfg = http_service
    c = client.Client(cfg)
    body = request()
    first = c.json('/v1/jobs', body)
    assert c.json('/v1/jobs', body) == first
    body['parameters'] = {'sex': 'F'}
    with pytest.raises(RuntimeError):
        c.json('/v1/jobs', body)
    monkeypatch.setenv('EAGLE_TEST_TOKEN', 'b' * 64)
    other = client.Client(cfg)
    with pytest.raises(RuntimeError):
        other.json('/v1/jobs/' + first['job_id'])
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(cfg['url'] + '/v1/capabilities')
    assert error.value.code == 401


def test_cancelled_job_never_publishes(tmp_path):
    entered = threading.Event()
    def runner(job, cancel):
        entered.set()
        assert cancel.wait(3)
        return synthetic_runner(job, cancel)
    jobs = server.Jobs(tmp_path, SyntheticSource(), runner)
    try:
        job_id = jobs.submit('fixture', request())['job_id']
        assert entered.wait(3)
        jobs.cancel('fixture', job_id)
        deadline = time.monotonic() + 3
        while jobs.get('fixture', job_id)['status'] != 'cancelled' and time.monotonic() < deadline:
            time.sleep(.01)
        assert jobs.get('fixture', job_id)['status'] == 'cancelled'
        assert not (tmp_path / job_id / 'artifacts.zip').exists()
    finally:
        jobs.close()


def test_restart_marks_unfinished_job_interrupted(tmp_path):
    job_id = uuid.uuid4().hex
    job = tmp_path / job_id
    job.mkdir()
    body = request()
    server.write_json(job / 'state.json', dict(status='running', owner='fixture', request_id=body['request_id'],
        job_id=job_id, fingerprint=contracts.fingerprint(body), module=body['module'], study_uid=body['study_uid']))
    jobs = server.Jobs(tmp_path, SyntheticSource(), synthetic_runner)
    try:
        assert jobs.get('fixture', job_id)['status'] == 'interrupted'
        assert jobs.submit('fixture', body)['job_id'] == job_id
    finally:
        jobs.close()


@pytest.mark.parametrize('name', ['../escape', 'C:/escape', '/escape', 'sub\\escape'])
def test_unsafe_artifact_names_are_rejected(tmp_path, name):
    archive = tmp_path / 'bad.zip'
    with zipfile.ZipFile(archive, 'w') as out:
        out.writestr(name, b'bad')
    with pytest.raises(ValueError):
        client.unpack(archive, tmp_path / 'result', request())


def test_artifact_envelope_binds_study_and_hashes(tmp_path):
    body = request()
    job = tmp_path / 'job'
    job.mkdir()
    result = synthetic_runner(job, threading.Event())
    artifacts.publish(job, body, [], result)
    wrong = {**body, 'study_uid': '1.2.999'}
    with pytest.raises(ValueError, match='identity'):
        client.unpack(job / 'artifacts.zip', tmp_path / 'wrong', wrong)
    with zipfile.ZipFile(job / 'artifacts.zip', 'a') as out:
        out.writestr('unexpected.dcm', b'not-allowed')
    with pytest.raises(ValueError, match='Unexpected'):
        client.unpack(job / 'artifacts.zip', tmp_path / 'unexpected', body)


def test_breast_export_preserves_series_binding_without_server_paths(tmp_path):
    import csv
    job = tmp_path / 'job'
    work = job / 'work'
    work.mkdir(parents=True)
    table = work / 'updated_csv_with_boxes.csv'
    record = dict(path='C:/private/source.dcm', study_uid='1.2.3',
                  series_uid='1.2.3.4', sop_uid='1.2.3.4.5', sha256='a' * 64)
    with table.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['dicom_full_path', 'box'])
        writer.writeheader()
        writer.writerow({'dicom_full_path': record['path'], 'box': '[[1,2,3,4]]'})
    result = {'artifact_directory': str(work), 'csv': str(table)}
    artifacts.publish(job, request('breast'), [record], result)
    with zipfile.ZipFile(job / 'artifacts.zip') as archive:
        row = next(csv.DictReader(io.StringIO(archive.read(table.name).decode())))
    reference = Path(row['dicom_full_path'])
    assert reference.parent.name == record['series_uid']
    assert reference.name == record['sop_uid'] + '.dcm'
    assert row['sop_instance_uid'] == record['sop_uid']
    assert not reference.is_absolute()
    assert row['box'] == '[[1,2,3,4]]'
    # The model worker prepares the same contract before publication; repeated
    # preparation must preserve identity and boxes rather than strip the series.
    before = table.read_bytes()
    artifacts.prepare_breast_tables(result, [record])
    assert table.read_bytes() == before
    with pytest.raises(ValueError, match='verified source'):
        artifacts.prepare_breast_tables(result, [{**record, 'series_uid': '1.2.99'}])


def test_breast_worker_emits_portable_table_before_publication(tmp_path, monkeypatch):
    import csv
    from modules.ai_imaging.eagle_eye_remote import adapters
    from modules.ai_imaging.eagle_eye_engines import service
    table = tmp_path / 'updated_csv_with_boxes.csv'
    table.write_text('dicom_full_path,box\nC:/private/source.dcm,[]\n')
    record = dict(path='C:/private/source.dcm', study_uid='1.2.3',
                  series_uid='1.2.3.4', sop_uid='1.2.3.4.5')
    monkeypatch.setattr(service, 'run', lambda *a, **k: {
        'job_directory': str(tmp_path), 'csv': str(table)})
    result = adapters.execute(request('breast'), [record], tmp_path)
    row = next(csv.DictReader(io.StringIO(Path(result['csv']).read_text())))
    assert row['dicom_full_path'] == '1.2.3.4/1.2.3.4.5.dcm'
    assert row['series_instance_uid'] == '1.2.3.4'


def test_standard_cannot_fall_back_to_local_models(monkeypatch, tmp_path):
    import aipacs_runtime
    monkeypatch.delenv('AIPACS_EAGLE_EYE_WORKER', raising=False)
    monkeypatch.setenv('AIPACS_EAGLE_EYE_CLIENT_CONFIG', str(tmp_path / 'absent.json'))
    monkeypatch.setattr(settings.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile', lambda: {'distribution_edition': 'standard'})
    assert settings.remote_required()
    with pytest.raises(ValueError, match='HTTPS'):
        client.Client({})


def test_server_worker_does_not_recurse_to_remote(monkeypatch):
    monkeypatch.setenv('AIPACS_EAGLE_EYE_WORKER', '1')
    monkeypatch.setattr(settings, 'client_settings', lambda: {'url': 'https://fixture.invalid'})
    assert not settings.remote_required()


def dicom(path, *, study='1.2.3', sop='1.2.3.4.5'):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, DigitalXRayImageStorageForPresentation
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = DigitalXRayImageStorageForPresentation
    meta.MediaStorageSOPInstanceUID = sop
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = study, '1.2.3.4', sop
    ds.SOPClassUID, ds.Modality = meta.MediaStorageSOPClassUID, 'DX'
    ds.save_as(path, write_like_original=False)


def test_server_staging_rejects_wrong_study_duplicate_and_incomplete(tmp_path, monkeypatch):
    folder = tmp_path / 'pacs'
    folder.mkdir()
    dicom(folder / 'one.dcm', study='1.2.999')
    provider = source.PacsSource({})
    monkeypatch.setattr(provider, 'storage_files', lambda req: sorted(folder.glob('*.dcm')))
    with pytest.raises(ValueError, match='another study'):
        provider.stage(request(), tmp_path / 'wrong', threading.Event())
    dicom(folder / 'one.dcm')
    dicom(folder / 'two.dcm')
    with pytest.raises(ValueError, match='duplicate'):
        provider.stage(request(), tmp_path / 'duplicate', threading.Event())
    body = request()
    body['series'] = {'primary': {'series_uid': '1.2.3.4', 'expected_count': 3}}
    dicom(folder / 'two.dcm', sop='1.2.3.4.6')
    with pytest.raises(ValueError, match='incomplete'):
        provider.stage(body, tmp_path / 'incomplete', threading.Event())


def test_brain_remote_route_precedes_local_bundle_loading(monkeypatch, tmp_path):
    from modules.ai_imaging.eagle_eye_brain import service as brain_service
    from modules.ai_imaging.eagle_eye_remote import routing
    monkeypatch.setattr(settings, 'remote_required', lambda: True)
    monkeypatch.setattr(routing, 'brain', lambda *a, **k: {'remote': True})
    monkeypatch.setattr(brain_service, 'bundle_root', lambda: pytest.fail('Client loaded a model'))
    assert brain_service.run_analysis('unused', '', tmp_path) == {'remote': True}


def test_missing_classification_is_never_presented_as_a_normal_case():
    ui = Path(__file__).resolve().parents[3] / 'modules/viewer/interactor_styles/ai_chat_interactorstyle.py'
    assert 'This case is normal with the selected threshold.' not in ui.read_text(encoding='utf-8')


@pytest.mark.parametrize('positions,valid', [([0, 2, 4], True), ([0, 2, 6], False), ([0, 0, 2], False)])
def test_server_lumbar_rejects_gapped_or_duplicate_geometry(tmp_path, positions, valid):
    import pydicom
    from modules.ai_imaging.eagle_eye_remote.adapters import validate_lumbar_geometry
    files = []
    for index, position in enumerate(positions):
        path = tmp_path / f'{index}.dcm'
        dicom(path, sop=f'1.2.3.4.{index + 1}')
        ds = pydicom.dcmread(path)
        ds.Modality = 'MR'
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.ImagePositionPatient = [0, 0, position]
        ds.save_as(path, write_like_original=False)
        files.append(path)
    if valid:
        validate_lumbar_geometry(files)
    else:
        with pytest.raises(ValueError, match='gaps, duplicates'):
            validate_lumbar_geometry(files)
