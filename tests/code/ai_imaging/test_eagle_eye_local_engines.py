"""Synthetic-only engine boundary checks; never access the live database."""
import ast
import hashlib
import json
from pathlib import Path

import pytest

from modules.ai_imaging.eagle_eye_engines import service


def test_development_runtime_records_resolved_base_interpreter(tmp_path):
    from tools.eagle_eye.prepare_breast_bone import normalize_runtime_home
    base = tmp_path / 'base'
    base.mkdir()
    (base / 'python.exe').write_bytes(b'synthetic interpreter')
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    cfg = runtime / 'pyvenv.cfg'
    cfg.write_text(f'home = {base / ".." / "base"}\ninclude-system-site-packages = false\n')
    normalize_runtime_home(runtime)
    assert cfg.read_text() == f'home = {base.resolve()}\ninclude-system-site-packages = false\n'
    (base / 'python.exe').unlink()
    with pytest.raises(ValueError, match='base interpreter'):
        normalize_runtime_home(runtime)


def test_named_classifier_tuples_are_unwrapped_without_dropping_members():
    from modules.ai_imaging.eagle_eye_engines.worker import normalize_estimators
    first, second = object(), object()
    assert normalize_estimators([[('xgb', first), ('ann', second)]]) == [[first, second]]


def test_incompatible_stacker_schema_fails_before_inference():
    from types import SimpleNamespace
    from modules.ai_imaging.eagle_eye_engines.worker import validate_stacker_schema
    cache = {'used_kinds': ['SINGLE', 'MV', 'BL', 'BOTH'],
             'stackers': {'fixture': SimpleNamespace(n_features_in_=9)}}
    with pytest.raises(ValueError, match='feature schema'):
        validate_stacker_schema(cache)
    cache['stackers']['fixture'].n_features_in_ = 4
    validate_stacker_schema(cache)


def test_unqualified_or_changed_engine_does_not_replace_working_remote_route(tmp_path, monkeypatch):
    monkeypatch.setattr(service, 'bundle_root', lambda engine: tmp_path)
    (tmp_path / 'manifest.json').write_text(json.dumps({'revision': 'current'}))
    assert not service.available('breast')
    (tmp_path / 'qualification.json').write_text(json.dumps({'revision': 'old', 'synthetic_smoke': 'passed'}))
    assert not service.available('breast')
    (tmp_path / 'qualification.json').write_text(json.dumps({'revision': 'current', 'synthetic_smoke': 'passed'}))
    assert service.available('breast')


def source(tmp_path, *, study='1.2.3', sex='M', modality='DX', frames=1):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian
    p = tmp_path / 'synthetic.dcm'
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = '1.2.840.10008.5.1.4.1.1.7'
    meta.MediaStorageSOPInstanceUID = '1.2.3.4.5'
    ds = FileDataset(str(p), {}, file_meta=meta, preamble=b'\0' * 128)
    ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.SOPInstanceUID = study, '1.2.3.4', '1.2.3.4.5'
    ds.Modality, ds.PatientSex, ds.BodyPartExamined = modality, sex, 'HAND'
    ds.Rows = ds.Columns = 8
    ds.SamplesPerPixel, ds.NumberOfFrames = 1, frames
    ds.PhotometricInterpretation = 'MONOCHROME2'
    ds.is_little_endian, ds.is_implicit_VR = True, False
    ds.save_as(p, write_like_original=False)
    return p


@pytest.mark.parametrize('change', [{'study': '1.2.99'}, {'sex': ''}, {'frames': 2}, {'modality': 'MR'}])
def test_rejects_incorrect_source(tmp_path, change):
    p = source(tmp_path, **change)
    with pytest.raises(ValueError):
        service.validate_sources([p], '1.2.3', 'bone-age')


def test_source_hash_and_verified_sex(tmp_path):
    p = source(tmp_path)
    records, sex = service.validate_sources([p], '1.2.3', 'bone-age')
    assert sex == 'M'
    assert records[0]['sha256'] == hashlib.sha256(p.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        service.validate_sources([p], '1.2.3', 'bone-age', 'F')
    with pytest.raises(ValueError):
        service.validate_sources([p, p], '1.2.3', 'bone-age')


def test_wrist_acquisition_can_be_selected_for_bone_age_without_relabeling(tmp_path):
    import pydicom
    p = source(tmp_path)
    ds = pydicom.dcmread(p)
    ds.BodyPartExamined = 'WRIST'
    ds.save_as(p)
    before = service.digest(p)
    records, sex = service.validate_sources([p], '1.2.3', 'bone-age')
    assert records[0]['body_part'] == 'WRIST'
    assert sex == 'M' and service.digest(p) == before
    ds.BodyPartExamined = 'CHEST'
    ds.save_as(p)
    with pytest.raises(ValueError, match='hand or wrist'):
        service.validate_sources([p], '1.2.3', 'bone-age')


def test_wrist_result_preserves_coverage_review_warning(tmp_path, monkeypatch):
    import sys
    import types
    import pydicom
    p = source(tmp_path)
    ds = pydicom.dcmread(p)
    ds.BodyPartExamined = 'WRIST'
    ds.save_as(p)
    monkeypatch.setattr(service, 'validate_bundle', lambda *a, **k: {'revision': 'fixture'})
    monkeypatch.setitem(sys.modules, 'modules.mpr.advanced_3d_slicer.owned_process',
        types.SimpleNamespace(ProcessJob=lambda: types.SimpleNamespace(
            assign=lambda p: None, close=lambda: None)))
    def launch(command, **kwargs):
        (Path(command[-1]) / 'result.json').write_text(json.dumps({
            'status': 'success', 'study_id': '1.2.3', 'reliability_warnings': ['Existing warning']}))
        return types.SimpleNamespace(returncode=0, poll=lambda: 0, wait=lambda timeout: 0)
    monkeypatch.setattr(service.subprocess, 'Popen', launch)
    result = service.run('bone-age', [p], '1.2.3', tmp_path / 'results', root=tmp_path)
    assert result['input_coverage_confirmation_required'] is True
    assert result['reliability_warnings'][0] == 'Existing warning'
    assert 'full hand and distal forearm' in result['reliability_warnings'][1]
    assert json.loads((Path(result['job_directory']) / 'result.json').read_text()) == result


def test_missing_or_changed_bundle_is_rejected(tmp_path):
    paths = ['runner.py', 'runtime/Scripts/python.exe', 'source/worker.py', 'weights/final_model.pth']
    hashes = {}
    for name in paths:
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'fixture')
        hashes[name] = service.digest(p)
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(format_version=1, engine='bone-age', sha256=hashes)))
    service.validate_bundle(tmp_path, 'bone-age')
    (tmp_path / 'weights/final_model.pth').write_bytes(b'corrupt')
    with pytest.raises(ValueError):
        service.validate_bundle(tmp_path, 'bone-age')


def test_cancel_before_bundle_read(tmp_path):
    (tmp_path / 'manifest.json').write_text(json.dumps(dict(format_version=1, engine='bone-age', sha256={
        p: '0' for p in ('runner.py', 'runtime/Scripts/python.exe', 'source/worker.py', 'weights/final_model.pth')})))
    with pytest.raises(RuntimeError, match='cancelled'):
        service.validate_bundle(tmp_path, 'bone-age', lambda: True)


def test_standard_never_selects_local_bundle(monkeypatch):
    import aipacs_runtime
    monkeypatch.setattr(service.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(aipacs_runtime, 'load_installation_profile', lambda: {'distribution_edition': 'standard'})
    assert service.bundle_root('breast') is None
    assert service.bundle_root('bone-age') is None


def test_study_inventory_requires_expected_count_without_live_db(tmp_path, monkeypatch):
    import sys
    import types
    source(tmp_path)
    row = dict(modality='DX', series_path=str(tmp_path), series_uid='1.2.3.4', image_count=2)
    monkeypatch.setitem(sys.modules, 'PacsClient.utils.db_manager', types.SimpleNamespace(get_series_by_study_uid=lambda uid: [row]))
    monkeypatch.setitem(sys.modules, 'PacsClient.utils.data_paths', types.SimpleNamespace(ATTACHMENTS_DIR=tmp_path / 'results'))
    calls = []
    monkeypatch.setattr(service, 'run', lambda *args, **kwargs: calls.append(args) or {'status': 'fixture'})
    with pytest.raises(ValueError, match='counted'):
        service.run_study('bone-age', '1.2.3')
    assert not calls
    row['image_count'] = 1
    assert service.run_study('bone-age', '1.2.3')['status'] == 'fixture'
    assert len(calls[0][1]) == 1


def test_detector_cannot_fall_back_to_random_weights():
    p = Path(service.__file__).parent / 'vendor/breast/FCOS_INFERENCE.py'
    tree = ast.parse(p.read_text(encoding='utf-8'))
    loader = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'load_model')
    assert isinstance(loader.body[0], ast.Raise)
    worker = (Path(service.__file__).parent / 'worker.py').read_text(encoding='utf-8')
    assert 'model.load_state_dict(state, strict=True)' in worker
    assert 'weights_only=True' in worker


def test_worker_has_no_api_or_training_import():
    tree = ast.parse((Path(service.__file__).parent / 'worker.py').read_text(encoding='utf-8'))
    imports = [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not any(any(x in line for x in ('requests', 'BoneAgeAPI', 'collect_for_finetuning')) for line in imports)


def test_gui_workers_route_to_local_engines():
    p = Path(service.__file__).parents[2] / 'viewer/interactor_styles/ai_chat_interactorstyle.py'
    tree = ast.parse(p.read_text(encoding='utf-8'))
    for name, engine in [('MamoWorker', 'breast'), ('BoneAgeWorker', 'bone-age')]:
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
        run = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run')
        assert f"run_study('{engine}'" in ast.unparse(run)


@pytest.mark.parametrize('outcome', ['failed', 'wrong-study', 'cancelled'])
def test_job_failure_never_publishes_and_releases_process(tmp_path, monkeypatch, outcome):
    import types
    import sys
    calls = []
    class Owner:
        def assign(self, process):
            calls.append('assigned')
        def close(self):
            calls.append('closed')
    class Child:
        returncode = 1 if outcome == 'failed' else 0
        def poll(self):
            return self.returncode
        def wait(self, timeout):
            calls.append('waited')
    def launch(command, **kwargs):
        calls.append('started')
        job = Path(command[-1])
        (job / 'result.json').write_text(json.dumps(dict(status='success', study_id='1.2.999')))
        if outcome == 'failed' and hasattr(kwargs['stderr'], 'write'):
            kwargs['stderr'].write(b'x' * 70000 + b'\nSynthetic engine failure\n')
            kwargs['stderr'].flush()
        return Child()
    monkeypatch.setitem(sys.modules, 'modules.mpr.advanced_3d_slicer.owned_process', types.SimpleNamespace(ProcessJob=Owner))
    monkeypatch.setattr(service, 'validate_bundle', lambda *a, **kw: {'revision': 'fixture'})
    monkeypatch.setattr(service.subprocess, 'Popen', launch)
    with pytest.raises(RuntimeError):
        service.run('bone-age', [], '1.2.3', tmp_path / 'jobs', root=tmp_path, smoke=True,
                    cancelled=lambda: outcome == 'cancelled' and 'started' in calls)
    assert calls == ['started', 'assigned', 'closed', 'waited']
    remaining = list((tmp_path / 'jobs').iterdir())
    if outcome == 'failed':
        assert len(remaining) == 1 and remaining[0].name == 'engine-failure.log'
        assert remaining[0].stat().st_size <= 65536
        assert remaining[0].read_bytes().endswith(b'Synthetic engine failure\n')
    else:
        assert remaining == []
