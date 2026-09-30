"""Hash-verified, Server-only portable Breast and Bone Age installer payloads."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from modules.ai_imaging.eagle_eye_engines.service import digest, validate_bundle

REPO = Path(__file__).resolve().parents[1]
ENGINES = ('breast', 'bone-age')


def source_for(engine: str) -> Path:
    if engine not in ENGINES:
        raise ValueError('Unknown Eagle Eye engine.')
    name = 'AIPACS_EAGLE_EYE_' + engine.upper().replace('-', '_') + '_SOURCE'
    configured = os.environ.get(name, '').strip()
    if not configured:
        raise ValueError(f'{name} must point to a sealed portable engine bundle.')
    return Path(configured).resolve()


def validate_payload(source: Path, engine: str, *, for_distribution: bool = True) -> dict:
    source = Path(source).resolve()
    if engine not in ENGINES or not source.is_dir():
        raise ValueError(f'Portable {engine} engine source is unavailable.')
    manifest = validate_bundle(source, engine)
    if manifest.get('format_version') != 2 or manifest.get('deployment') != 'standalone-python':
        raise ValueError(f'{engine} must use a standalone Python runtime, not a development venv.')
    if (source / 'runtime/pyvenv.cfg').exists() or (source / 'runtime/Scripts/python.exe').exists():
        raise ValueError(f'{engine} still depends on a local Python installation.')
    probe_path = source / 'runtime-probe.json'
    if not probe_path.is_file():
        raise ValueError(f'{engine} is missing its isolated interpreter probe.')
    probe = json.loads(probe_path.read_text(encoding='utf-8'))
    if (probe.get('status') != 'passed'
            or probe.get('manifest_sha256') != digest(source / 'manifest.json')):
        raise ValueError(f'{engine} interpreter probe does not match its model manifest.')
    if for_distribution:
        approval_path = source / 'distribution-approval.json'
        if not approval_path.is_file():
            raise ValueError(f'{engine} redistribution approval is missing.')
        approval = json.loads(approval_path.read_text(encoding='utf-8'))
        if (approval.get('approved') is not True
                or approval.get('manifest_sha256') != digest(source / 'manifest.json')
                or not approval.get('rights_evidence')):
            raise ValueError(f'{engine} redistribution approval does not match this bundle.')
    return manifest


def stage_engine(payload: Path, engine: str, *, for_distribution: bool = True) -> Path:
    source = source_for(engine)
    manifest = validate_payload(source, engine, for_distribution=for_distribution)
    destination = Path(payload) / 'eagle_eye' / engine
    if destination.exists():
        raise FileExistsError(f'{engine} stage must be new.')
    destination.mkdir(parents=True)
    for name in manifest['sha256']:
        item = destination / name
        item.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / name, item)
    for name in ('manifest.json', 'runtime-probe.json'):
        shutil.copy2(source / name, destination / name)
    if for_distribution:
        shutil.copy2(source / 'distribution-approval.json',
                     destination / 'distribution-approval.json')
    validate_payload(destination, engine, for_distribution=for_distribution)
    return destination
