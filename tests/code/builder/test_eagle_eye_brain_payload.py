"""Synthetic offline packaging and release evidence guards; no patient data."""
import json
from pathlib import Path
import pytest

from builder import eagle_eye_brain_payload as payload
from modules.ai_imaging.eagle_eye_brain.runtime import SYNTHSEG_REVISION, sha256


@pytest.fixture
def brain_payload(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic-brain'
    files = ['python/python.exe', 'SynthSeg/scripts/commands/SynthSeg_predict.py']
    files += ['SynthSeg/models/' + name for name in
              ('synthseg_2.0.h5', 'synthseg_robust_2.0.h5', 'synthseg_parc_2.0.h5', 'synthseg_qc_2.0.h5')]
    for name in files:
        path = source / 'model' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'SYNTHETIC TEST DATA - NOT EXECUTABLE')
    manifest = source / 'model/manifest.json'
    manifest.write_text(json.dumps(dict(format_version=2, revision=SYNTHSEG_REVISION,
        sha256={name: sha256(source / 'model' / name) for name in files})))
    hashes = {}
    for sex in ('male', 'female', 'unknown'):
        name = 'general' if sex == 'unknown' else sex
        path = source / 'references/volbrain' / f'bounds_{name}.csv'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('SYNTHETIC REFERENCE FIXTURE')
        hashes[sex] = sha256(path)
    monkeypatch.setattr(payload, 'HASHES', hashes)
    for name in ('README.md', 'license.txt'):
        (source / 'references/volbrain' / name).write_text('SYNTHETIC TEST PROVENANCE')
    (source / 'runtime-probe.json').write_text(json.dumps(dict(status='passed', inference_status='passed', model_manifest_sha256=sha256(manifest))))
    (source / 'distribution-approval.json').write_text(json.dumps(dict(approved=True,
        reference_revision=payload.REVISION, model_manifest_sha256=sha256(manifest),
        rights_evidence='SYNTHETIC TEST RECEIPT', clean_windows_acceptance='SYNTHETIC TEST RECEIPT')))
    return source


def test_missing_distribution_evidence_blocks_staging(brain_payload, tmp_path):
    (brain_payload / 'distribution-approval.json').unlink()
    with pytest.raises((OSError, ValueError)):
        payload.stage_eagle_eye_brain(tmp_path / 'output', brain_payload)
    assert not (tmp_path / 'output/eagle_eye/brain').exists()


def test_cli_probe_alone_cannot_approve_distribution(brain_payload):
    path = brain_payload / 'runtime-probe.json'
    record = json.loads(path.read_text())
    record.pop('inference_status')
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='full portable inference'):
        payload.validate_payload(brain_payload)


def test_install_acceptance_is_after_candidate_creation(brain_payload):
    path = brain_payload / 'distribution-approval.json'
    record = json.loads(path.read_text())
    record.pop('clean_windows_acceptance')
    path.write_text(json.dumps(record))
    # This validates staging rights, not clinical/customer release acceptance.
    assert payload.validate_payload(brain_payload)['format_version'] == 2


def test_only_manifested_assets_ship(brain_payload, tmp_path):
    (brain_payload / 'patient-result.json').write_text('SYNTHETIC DO NOT SHIP')
    (brain_payload / 'model/old-reference.rds').write_text('SYNTHETIC DO NOT SHIP')
    staged = payload.stage_eagle_eye_brain(tmp_path / 'output', brain_payload)
    assert not (staged / 'patient-result.json').exists()
    assert not (staged / 'model/old-reference.rds').exists()
    assert payload.validate_payload(staged)['format_version'] == 2


def test_portable_payload_rejects_venv_base_dependency(brain_payload):
    (brain_payload / 'model/python/pyvenv.cfg').write_text('home = C:/developer/python')
    with pytest.raises(RuntimeError):
        payload.validate_payload(brain_payload)


def test_portable_command_uses_manifested_python(brain_payload, tmp_path):
    from modules.ai_imaging.eagle_eye_brain.runtime import synthseg_command
    from modules.ai_imaging.eagle_eye_brain.contracts import BrainPlan
    command = synthseg_command(brain_payload / 'model', tmp_path / 'job', BrainPlan())
    assert command[0] == brain_payload / 'model/python/python.exe'
    assert '-E' in command and '-s' in command


def test_standard_excludes_brain_before_copy(tmp_path):
    from builder import distribution_profiles as profiles
    root = tmp_path / 'advanced_mpr'
    ignore = profiles._edition_copy_ignore(root, profiles.EDITIONS['standard'])
    assert 'eagle_eye' in ignore(root / 'payload', ['eagle_eye', 'offline_lumbar'])
