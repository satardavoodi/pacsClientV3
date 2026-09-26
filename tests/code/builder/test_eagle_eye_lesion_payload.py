import hashlib
import json
from pathlib import Path
import pytest

from builder.eagle_eye_lesion_payload import validate_payload, stage_eagle_eye_lesions


def make_lesion_payload(root):
    files = ['python/python.exe', 'python/Lib/site-packages/lst_ai/segment.py', 'runner.py']
    files += [f'data/model/UNet3D_MS_final_mdl{x}.pt' for x in 'ABC']
    files += ['python/Scripts/lst', 'data/atlas/sub-mni152_space-mni_t1.nii.gz']
    files += [f'python/Lib/site-packages/brainles_hd_bet/model_weights/{i}.model' for i in range(5)]
    hashes = {}
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic fixture')
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = root / 'manifest.json'
    manifest.write_text(json.dumps({'version': '2.0.0rc1', 'format_version': 1, 'sha256': hashes}))
    (root / 'acceptance.json').write_text(json.dumps({'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest(),
                                                     'offline_inference': 'passed', 'live_gui': 'passed',
                                                     'distribution_rights_review': 'approved'}))
    return root


def test_lesion_payload_rejects_changed_model_and_missing_acceptance(tmp_path):
    root = make_lesion_payload(tmp_path)
    validate_payload(root)
    (root / 'acceptance.json').unlink()
    with pytest.raises(RuntimeError, match='acceptance'):
        validate_payload(root)
    validate_payload(root, for_distribution=False)
    (root / 'runner.py').write_bytes(b'changed')
    with pytest.raises(Exception, match='incomplete or changed'):
        validate_payload(root, for_distribution=False)


def test_standard_does_not_copy_lesion_bytes(tmp_path, monkeypatch):
    from builder import distribution_profiles as profiles
    from tests.code.builder.test_distribution_profiles import source_stage, add_complete_slicer_runtime
    source = source_stage(tmp_path)
    payload = add_complete_slicer_runtime(source)
    make_lesion_payload(payload / 'eagle_eye/brain-lesions')
    copied = []
    original = profiles._link_or_copy
    def record(source, destination):
        copied.append(Path(source))
        return original(source, destination)
    monkeypatch.setattr(profiles, '_link_or_copy', record)
    target = profiles.stage_edition(source, tmp_path / 'standard', profiles.EDITIONS['standard'])
    assert not any('brain-lesions' in p.parts for p in copied)
    assert not (target / 'plugin_packages/advanced_mpr/payload/eagle_eye').exists()


def test_lesion_staging_copies_only_sealed_files(tmp_path, monkeypatch):
    source = make_lesion_payload(tmp_path / 'source')
    (source / 'untracked.txt').write_text('not payload')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_LESION_SOURCE', str(source))
    target = stage_eagle_eye_lesions(tmp_path / 'target')
    assert (target / 'runner.py').is_file()
    assert not (target / 'untracked.txt').exists()


def add_synthetic_2d_engine(source, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain import lesions_2d
    engine = source / 'mindglide'; engine.mkdir()
    files = ['model.pt', 'runner.py', 'site-packages-v1/mindglide/infer.py', 'site-packages-v1/monai/__init__.py']
    hashes = {}
    for name in files:
        p = engine / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'synthetic engine'); hashes[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    monkeypatch.setattr(lesions_2d, 'MODEL_SHA256', hashes['model.pt'])
    shared = {}
    for name in ['python/python.exe', 'python/python310.dll', 'python/python310.zip',
                 'python/Lib/site-packages/torch/__init__.py', 'python/Lib/site-packages/numpy/__init__.py']:
        p = source / name; p.parent.mkdir(parents=True, exist_ok=True)
        if not p.exists(): p.write_bytes(b'synthetic runtime')
        shared[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (engine / 'manifest.json').write_text(json.dumps(dict(version='1.3.0', model_sha256=hashes['model.pt'],
         python_sha256=shared['python/python.exe'], sha256=hashes, shared_sha256=shared)))
    # Parent inventory contains shared runtime, as the real sealed LST bundle does.
    p = source / 'manifest.json'; parent = json.loads(p.read_text()); parent['sha256'].update(shared)
    p.write_text(json.dumps(parent))
    receipt = json.loads((source / 'acceptance.json').read_text())
    receipt['manifest_sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
    (source / 'acceptance.json').write_text(json.dumps(receipt))
    return engine


def test_2d_payload_cannot_reuse_3d_distribution_acceptance(tmp_path, monkeypatch):
    source = make_lesion_payload(tmp_path / 'source')
    engine = add_synthetic_2d_engine(source, monkeypatch)
    validate_payload(source, for_distribution=False)
    with pytest.raises(RuntimeError, match='2D lesion redistribution'):
        validate_payload(source)
    (engine / 'unsealed.bin').write_bytes(b'not for distribution')
    monkeypatch.setenv('AIPACS_EAGLE_EYE_LESION_SOURCE', str(source))
    target = stage_eagle_eye_lesions(tmp_path / 'target', for_distribution=False)
    assert (target / 'mindglide/model.pt').is_file()
    assert not (target / 'mindglide/unsealed.bin').exists()
    (target / 'python/python310.dll').write_bytes(b'changed runtime')
    with pytest.raises(Exception):
        validate_payload(target, for_distribution=False)
