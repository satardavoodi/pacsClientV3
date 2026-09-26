"""Synthetic Windows source sharing, lifetime and fallback regression guards."""
import os
from pathlib import Path
import shutil
import threading

import pytest

from modules.ai_imaging.eagle_eye_remote import source


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
def test_link_shares_storage_but_denies_writes_and_allows_atomic_replacement(tmp_path):
    original, linked = tmp_path / 'pacs.dcm', tmp_path / 'job.dcm'
    original.write_bytes(b'original-synthetic')
    with source.SourceLease() as lease:
        assert lease.materialize(original, linked, share=True) == 'hardlink'
        assert original.samefile(linked)
        for path in (original, linked):
            with pytest.raises(OSError):
                path.write_bytes(b'forbidden')
        replacement = tmp_path / 'replacement.partial'
        replacement.write_bytes(b'new-synthetic')
        replacement.replace(original)
        assert original.read_bytes() == b'new-synthetic'
        assert linked.read_bytes() == b'original-synthetic'
    linked.unlink()
    assert original.read_bytes() == b'new-synthetic'


def test_unattested_storage_is_copied(tmp_path):
    original, staged = tmp_path / 'pacs.dcm', tmp_path / 'job.dcm'
    original.write_bytes(b'synthetic')
    with source.SourceLease() as lease:
        assert lease.materialize(original, staged, share=False) == 'copy'
        assert not original.samefile(staged)
        staged.write_bytes(b'independent')
        assert original.read_bytes() == b'synthetic'


def test_link_failure_falls_back_without_leaving_a_shared_alias(tmp_path, monkeypatch):
    original, staged = tmp_path / 'pacs.dcm', tmp_path / 'job.dcm'
    original.write_bytes(b'synthetic')
    monkeypatch.setattr(os, 'link', lambda *a, **k: (_ for _ in ()).throw(OSError('cross-volume')))
    with source.SourceLease() as lease:
        assert lease.materialize(original, staged, share=True) == 'copy'
        assert not original.samefile(staged)
        assert staged.read_bytes() == original.read_bytes()


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
def test_pin_failure_removes_alias_before_copy(tmp_path, monkeypatch):
    original, staged = tmp_path / 'pacs.dcm', tmp_path / 'job.dcm'
    original.write_bytes(b'synthetic')
    with source.SourceLease() as lease:
        monkeypatch.setattr(lease, 'pin', lambda p: (_ for _ in ()).throw(OSError('writer active')))
        assert lease.materialize(original, staged, share=True) == 'copy'
        assert not original.samefile(staged)
        assert original.read_bytes() == b'synthetic'


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
def test_provider_stages_only_selected_series_without_copy(tmp_path, monkeypatch):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
    inventory = []
    for number in (4, 5):
        path = tmp_path / f'input-{number}.dcm'
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        meta.MediaStorageSOPClassUID = MRImageStorage
        meta.MediaStorageSOPInstanceUID = f'1.2.3.{number}.1'
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = MRImageStorage, meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID, ds.SeriesInstanceUID = '1.2.3', f'1.2.3.{number}'
        ds.Modality = 'MR'
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.save_as(path, write_like_original=False)
        inventory.append(path)
    provider = source.PacsSource({})
    monkeypatch.setattr(provider, 'storage_files', lambda req: source.StorageFiles(inventory, atomic_replace=True))
    request = dict(module='lumbar', study_uid='1.2.3', series={
        'primary': dict(series_uid='1.2.3.4', expected_count=1)})
    destination = tmp_path / 'job'
    try:
        with source.SourceLease() as lease:
            records = provider.stage(request, destination, threading.Event(), lease=lease)
            assert len(records) == 1 and records[0]['storage_mode'] == 'hardlink'
            assert inventory[0].samefile(records[0]['path'])
            assert list(source.role_path(records, 'primary').glob('*.dcm')) == [Path(records[0]['path'])]
            with pytest.raises(OSError):
                Path(records[0]['path']).write_bytes(b'forbidden')
        shutil.rmtree(destination)
        assert all(p.is_file() for p in inventory)
    finally:
        provider.session.close()


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
def test_exception_releases_read_lease(tmp_path):
    original, staged = tmp_path / 'pacs.dcm', tmp_path / 'job.dcm'
    original.write_bytes(b'synthetic')
    with pytest.raises(RuntimeError):
        with source.SourceLease() as lease:
            lease.materialize(original, staged, share=True)
            raise RuntimeError('cancelled')
    staged.unlink()
    original.write_bytes(b'lease-released')


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
def test_child_process_cannot_write_shared_input(tmp_path):
    import subprocess
    import sys
    original, staged = tmp_path / 'pacs.dcm', tmp_path / 'job.dcm'
    original.write_bytes(b'synthetic')
    with source.SourceLease() as lease:
        lease.materialize(original, staged, share=True)
        result = subprocess.run([sys.executable, '-c',
            'from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b"bad")', str(staged)],
            capture_output=True, timeout=10)
        assert result.returncode != 0
        assert original.read_bytes() == b'synthetic'


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
def test_revision_reuses_version_after_pacs_replacement(tmp_path):
    import json
    from modules.ai_imaging.eagle_eye_remote.contracts import digest
    from modules.ai_imaging.eagle_eye_remote.reviews import stage_parent
    original = tmp_path / 'pacs.dcm'
    original.write_bytes(b'old')
    parent = tmp_path / 'parent'
    sources = parent / 'sources'; sources.mkdir(parents=True)
    retained = sources / 'image.dcm'
    with source.SourceLease() as lease:
        lease.materialize(original, retained, share=True)
    (parent / 'sources.json').write_text(json.dumps([dict(path=str(retained),
        sha256=digest(retained), storage_mode='hardlink')]))
    replacement = tmp_path / 'new'; replacement.write_bytes(b'new'); replacement.replace(original)
    with source.SourceLease() as lease:
        records = stage_parent(tmp_path, 'parent', tmp_path / 'revision', lease=lease)
        assert Path(records[0]['path']).samefile(retained)
        assert Path(records[0]['path']).read_bytes() == b'old'
        assert records[0]['storage_mode'] == 'hardlink'
    shutil.rmtree(parent)
    assert Path(records[0]['path']).read_bytes() == b'old'
    assert original.read_bytes() == b'new'


@pytest.mark.parametrize('policy,expected', [(None, False), ('unknown', False), ('atomic-replace-v1', True)])
def test_capability_is_explicit_and_preserves_identity_checks(tmp_path, monkeypatch, policy, expected):
    import json as json_module
    path = tmp_path / 'image.dcm'; path.write_bytes(b'synthetic')
    data = dict(study_info={'study_instance_uid': '1.2.3'},
                storage_info={'study_path': str(tmp_path), 'source_write_policy': policy})
    class Response:
        content = json_module.dumps(data).encode()
        def json(self): return data
        def __enter__(self): return self
        def __exit__(self, *args): pass
    provider = source.PacsSource({'url': 'http://127.0.0.1:8000', 'allowed_roots': [str(tmp_path)]})
    monkeypatch.setattr(provider, 'get', lambda url: Response())
    try:
        files = provider.storage_files({'study_uid': '1.2.3'})
        assert files == [path] and files.atomic_replace is expected
        with pytest.raises(ValueError, match='identity'):
            provider.storage_files({'study_uid': '1.2.9'})
    finally:
        provider.session.close()


@pytest.mark.skipif(os.name != 'nt', reason='Windows mandatory sharing semantics')
@pytest.mark.parametrize('outcome', ['success', 'failure', 'cancel'])
def test_job_holds_lease_through_runner_and_releases_on_every_exit(tmp_path, monkeypatch, outcome):
    import json
    import uuid
    from modules.ai_imaging.eagle_eye_remote import server
    from modules.ai_imaging.eagle_eye_remote.contracts import digest
    original = tmp_path / 'pacs.dcm'; original.write_bytes(b'synthetic')
    class Provider(source.PacsSource):
        def stage(self, request, destination, cancel, *, lease=None):
            destination.mkdir()
            out = destination / 'image.dcm'
            assert lease is not None
            mode = lease.materialize(original, out, share=True)
            return [dict(path=str(out), sha256=digest(out), storage_mode=mode)]
    entered = []
    def runner(job, cancel):
        record = json.loads((job / 'sources.json').read_text())[0]
        assert original.samefile(record['path'])
        with pytest.raises(OSError):
            Path(record['path']).write_bytes(b'forbidden')
        entered.append(True)
        if outcome == 'failure': raise RuntimeError('synthetic failure')
        if outcome == 'cancel': cancel.set()
        return {}
    monkeypatch.setattr(server, 'publish', lambda *a: {})
    jobs = server.Jobs(tmp_path / 'jobs', Provider({}), runner)
    try:
        result = jobs.submit('synthetic-owner', dict(protocol=1, request_id=uuid.uuid4().hex,
            module='bone-age', study_uid='1.2.3', series={}, parameters={}))
        jobs.executor.shutdown(wait=True)
        assert entered == [True]
        assert jobs.get('synthetic-owner', result['job_id'])['status'] == {
            'success': 'succeeded', 'failure': 'failed', 'cancel': 'cancelled'}[outcome]
        original.write_bytes(b'released')
    finally:
        jobs.close()
