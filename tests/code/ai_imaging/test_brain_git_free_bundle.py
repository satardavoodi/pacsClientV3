"""Source service exports must resolve their own models without Git metadata."""
import pytest
import os
from pathlib import Path

from modules.ai_imaging.eagle_eye_brain import lesions, runtime


def isolate(monkeypatch, tmp_path):
    import aipacs_runtime
    from modules.ai_imaging.eagle_eye import assets
    monkeypatch.delenv('AIPACS_BRAIN_BUNDLE', raising=False)
    monkeypatch.delenv('AIPACS_BRAIN_LESION_BUNDLE', raising=False)
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: False)
    monkeypatch.setattr(aipacs_runtime, 'user_data_root', lambda: tmp_path / 'user-data')
    monkeypatch.setattr(aipacs_runtime, 'modules_runtime_search_roots', lambda: [])
    monkeypatch.setattr(assets, 'installed_feature_roots', lambda feature: [])
    for module in (lesions, runtime):
        monkeypatch.setattr(module, '__file__', str(tmp_path / 'modules/ai_imaging/eagle_eye_brain' / (module.__name__.split('.')[-1] + '.py')))


def test_exported_source_finds_lesions_without_git(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    model = tmp_path / 'generated-files/eagle-eye/brain-lesions'
    model.mkdir(parents=True)
    (model / 'manifest.json').write_text('{}')
    assert lesions.lesion_bundle() == model.resolve()


def test_exported_source_retains_anatomy_qualification(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    candidate = tmp_path / 'generated-files/eagle-eye/brain-tf212-py310'
    candidate.mkdir(parents=True)
    with pytest.raises(runtime.BrainError, match='not passed full inference'):
        runtime.bundle_root()


def test_explicit_missing_lesion_override_does_not_fall_back(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    model = tmp_path / 'generated-files/eagle-eye/brain-lesions'
    model.mkdir(parents=True)
    (model / 'manifest.json').write_text('{}')
    monkeypatch.setenv('AIPACS_BRAIN_LESION_BUNDLE', str(tmp_path / 'missing'))
    with pytest.raises(runtime.BrainError, match='not installed'):
        lesions.lesion_bundle()


def test_frozen_does_not_use_source_fallback(monkeypatch, tmp_path):
    isolate(monkeypatch, tmp_path)
    import aipacs_runtime
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: True)
    model = tmp_path / 'generated-files/eagle-eye/brain-lesions'
    model.mkdir(parents=True)
    (model / 'manifest.json').write_text('{}')
    for resolve in (lesions.lesion_bundle, runtime.bundle_root):
        with pytest.raises(runtime.BrainError, match='not installed'):
            resolve()


@pytest.mark.skipif(os.name != 'nt', reason='Windows path-length boundary')
def test_manifest_hash_reads_long_paths_without_machine_policy(monkeypatch, tmp_path):
    import hashlib
    target = tmp_path / ('a' * 90) / ('b' * 90) / ('c' * 90) / 'weights.dat'
    extended = Path('\\\\?\\' + str(target))
    extended.parent.mkdir(parents=True)
    extended.write_bytes(b'model fixture')
    original = Path.open

    def limited_open(path, *args, **kwargs):
        if len(str(path)) >= 260 and not str(path).startswith('\\\\?\\'):
            raise OSError(206, 'Windows path is too long')
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', limited_open)
    assert runtime.sha256(target) == hashlib.sha256(b'model fixture').hexdigest()
