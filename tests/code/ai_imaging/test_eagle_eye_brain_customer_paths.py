"""Installed-runtime discovery without developer directories or patient data."""
from pathlib import Path
import aipacs_runtime
from modules.ai_imaging.eagle_eye_brain import runtime, volbrain_reference


def test_installed_brain_bundle_is_found_without_environment_override(tmp_path, monkeypatch):
    monkeypatch.delenv('AIPACS_BRAIN_BUNDLE', raising=False)
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: True)
    monkeypatch.setattr(aipacs_runtime, 'user_data_root', lambda: tmp_path/'user')
    monkeypatch.setattr(aipacs_runtime, 'modules_runtime_search_roots', lambda: [tmp_path/'modules'])
    candidate=tmp_path/'modules'/'eagle_eye_brain'/'model'
    candidate.mkdir(parents=True); (candidate/'manifest.json').write_text('{}')
    assert runtime.bundle_root()==candidate


def test_reference_tables_can_be_provisioned_in_installed_module(tmp_path, monkeypatch):
    monkeypatch.setattr(aipacs_runtime,'user_data_root',lambda: tmp_path/'user')
    monkeypatch.setattr(aipacs_runtime,'modules_runtime_search_roots',lambda:[tmp_path/'modules'])
    candidate=tmp_path/'modules'/'eagle_eye_brain'/'references'/'volbrain'
    candidate.mkdir(parents=True);(candidate/'bounds_male.csv').write_text('synthetic')
    assert volbrain_reference.data_root()==candidate
    # A modified user override must be detected, not silently replaced by installed data.
    local=tmp_path/'user'/'ai/eagle_eye/brain/references/volbrain'
    local.mkdir(parents=True)
    assert volbrain_reference.data_root()==local


def test_frozen_app_ships_external_slicer_worker(monkeypatch):
    from builder.spec import spec_utils

    # Inspect the real data collector without generating configuration or a build.
    monkeypatch.setattr(spec_utils, 'sanitized_config_rel', lambda: 'missing-test-config')
    worker = Path(runtime.__file__).with_name('slicer_worker.py')
    assert (str(worker.resolve()), 'modules/ai_imaging/eagle_eye_brain') in spec_utils.app_a_datas()


def test_child_process_paths_do_not_depend_on_job_working_directory(tmp_path, monkeypatch):
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainPlan
    monkeypatch.chdir(tmp_path)
    command = runtime.synthseg_command(Path('model'), Path('job'), BrainPlan())
    assert command[0].is_absolute()
    assert command[4].is_absolute()
    assert command[command.index('--i') + 1].is_absolute()


def test_programdata_package_uses_eagle_eye_brain_layout(tmp_path, monkeypatch):
    monkeypatch.delenv('AIPACS_BRAIN_BUNDLE', raising=False)
    monkeypatch.setattr(aipacs_runtime, 'is_frozen', lambda: True)
    monkeypatch.setattr(aipacs_runtime, 'user_data_root', lambda: tmp_path / 'user')
    monkeypatch.setattr(aipacs_runtime, 'modules_runtime_search_roots', lambda: [])
    monkeypatch.setattr(aipacs_runtime, 'bundled_module_packages_search_roots', lambda: [tmp_path / 'packages'])
    feature = tmp_path / 'packages/advanced_mpr/payload/eagle_eye/brain'
    (feature / 'model').mkdir(parents=True)
    (feature / 'model/manifest.json').write_text('{}')
    (feature / 'references/volbrain').mkdir(parents=True)
    assert runtime.bundle_root() == feature / 'model'
    assert volbrain_reference.data_root() == feature / 'references/volbrain'


def test_development_candidate_requires_full_model_bound_probe(tmp_path):
    import json
    import pytest
    feature = tmp_path / 'generated-files/eagle-eye/brain-tf212-py310'
    (feature / 'model').mkdir(parents=True)
    manifest = feature / 'model/manifest.json'
    manifest.write_text('{}')
    with pytest.raises(runtime.BrainError):
        runtime.development_bundle(tmp_path)
    probe = dict(status='passed', inference_status='passed', model_manifest_sha256=runtime.sha256(manifest))
    (feature / 'runtime-probe.json').write_text(json.dumps(probe))
    assert runtime.development_bundle(tmp_path) == feature / 'model'
    manifest.write_text('{"changed": true}')
    with pytest.raises(runtime.BrainError):
        runtime.development_bundle(tmp_path)
