"""Synthetic Server-engine staging guards; no patient images or real model files."""
import json
from pathlib import Path

import pytest

from builder import eagle_eye_engine_payload as payload


def fixture_bundle(root: Path, engine: str) -> Path:
    root.mkdir()
    required = ['runner.py', 'runtime/python.exe', 'source/worker.py',
                'weights/final_model.pth' if engine == 'bone-age'
                else 'weights/best_fcos_csv_delivery.pth']
    hashes = {}
    for name in required:
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'synthetic')
        hashes[name] = payload.digest(file)
    manifest = dict(format_version=2, engine=engine, deployment='standalone-python',
                    revision='fixture', sha256=hashes)
    (root / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
    (root / 'runtime-probe.json').write_text(json.dumps(dict(
        status='passed', manifest_sha256=payload.digest(root / 'manifest.json'))),
        encoding='utf-8')
    return root


@pytest.mark.parametrize('engine', payload.ENGINES)
def test_server_stage_copies_only_sealed_standalone_files(tmp_path, monkeypatch, engine):
    source = fixture_bundle(tmp_path / 'source', engine)
    (source / 'clinical-output.csv').write_text('must not ship', encoding='utf-8')
    name = 'AIPACS_EAGLE_EYE_' + engine.upper().replace('-', '_') + '_SOURCE'
    monkeypatch.setenv(name, str(source))
    stage = payload.stage_engine(tmp_path / 'payload', engine, for_distribution=False)
    assert (stage / 'runtime/python.exe').is_file()
    assert not (stage / 'clinical-output.csv').exists()
    assert not (stage / 'runtime/pyvenv.cfg').exists()
    assert payload.validate_payload(stage, engine, for_distribution=False)['revision'] == 'fixture'


def test_development_venv_cannot_enter_server_installer(tmp_path):
    source = fixture_bundle(tmp_path / 'source', 'breast')
    (source / 'runtime/pyvenv.cfg').write_text('home = C:/Developer/Python', encoding='utf-8')
    with pytest.raises(ValueError, match='virtual environment'):
        payload.validate_payload(source, 'breast', for_distribution=False)


def test_distribution_needs_bound_rights_receipt(tmp_path):
    source = fixture_bundle(tmp_path / 'source', 'bone-age')
    with pytest.raises(ValueError, match='redistribution approval'):
        payload.validate_payload(source, 'bone-age')
    (source / 'distribution-approval.json').write_text(json.dumps(dict(
        approved=True, manifest_sha256='0' * 64, rights_evidence=['fixture'])), encoding='utf-8')
    with pytest.raises(ValueError, match='does not match'):
        payload.validate_payload(source, 'bone-age')
