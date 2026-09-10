"""Validated Eagle Eye Brain payload, never the developer virtual environment."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

from modules.ai_imaging.eagle_eye_brain.runtime import validate_bundle, sha256
from modules.ai_imaging.eagle_eye_brain.volbrain_reference import HASHES, REVISION

REPO = Path(__file__).resolve().parents[1]
COMPILE_ONLY_MODEL_PREFIXES = ('python/Lib/site-packages/tensorflow/include/',)


def bundle_source():
    configured = os.environ.get('AIPACS_EAGLE_EYE_BRAIN_SOURCE')
    return Path(configured).resolve() if configured else REPO / 'generated-files/eagle-eye/brain-tf212-py310'


def validate_payload(source, *, for_distribution=True):
    source = Path(source).resolve()
    model = validate_bundle(source / 'model')
    if model['format_version'] != 2:
        raise ValueError('Eagle Eye Brain requires the portable Windows model format')
    reference = source / 'references/volbrain'
    for sex, digest in HASHES.items():
        name = 'general' if sex == 'unknown' else sex
        if sha256(reference / f'bounds_{name}.csv') != digest:
            raise ValueError('Eagle Eye Brain reference integrity failed')
    # A local runtime probe is evidence of relocation, not clinical acceptance.
    probe = json.loads((source / 'runtime-probe.json').read_text(encoding='utf-8'))
    if (probe.get('status') != 'passed' or
            probe.get('model_manifest_sha256') != sha256(source / 'model/manifest.json')):
        raise ValueError('Eagle Eye Brain portable runtime probe is missing or stale')
    if for_distribution:
        if probe.get('inference_status') != 'passed':
            raise ValueError('Eagle Eye Brain full portable inference has not passed')
        # This record must be supplied by the release owner with actual evidence.
        # Preparation never creates an approval or asserts redistribution rights.
        receipt = json.loads((source / 'distribution-approval.json').read_text(encoding='utf-8'))
        if (receipt.get('reference_revision') != REVISION or
                receipt.get('model_manifest_sha256') != sha256(source / 'model/manifest.json') or
                not receipt.get('rights_evidence') or
                receipt.get('approved') is not True):
            raise ValueError('Eagle Eye Brain redistribution evidence is incomplete or stale')
    return model


def stage_eagle_eye_brain(payload, source=None, *, for_distribution=True):
    source = Path(source) if source is not None else bundle_source()
    model = validate_payload(source, for_distribution=for_distribution)
    destination = Path(payload) / 'eagle_eye/brain'
    if destination.exists() or destination.resolve() == source.resolve():
        raise ValueError('Brain payload staging requires a fresh destination')
    # Copy only manifest-listed model files and explicit reference/provenance files.
    model_files = dict(model['sha256'])
    if not for_distribution:
        model_files = {
            name: digest for name, digest in model_files.items()
            if not name.startswith(COMPILE_ONLY_MODEL_PREFIXES)
        }
    names = ['model/manifest.json', 'runtime-probe.json']
    if for_distribution:
        names.append('distribution-approval.json')
    names.extend('model/' + name for name in model_files)
    names.extend('references/volbrain/bounds_' + sex + '.csv' for sex in ('male', 'female', 'general'))
    names.extend(['references/volbrain/README.md', 'references/volbrain/license.txt'])
    for relative in names:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    if not for_distribution and model_files != model['sha256']:
        staged_manifest = dict(model)
        staged_manifest['sha256'] = model_files
        manifest_path = destination / 'model/manifest.json'
        manifest_path.write_text(json.dumps(staged_manifest, indent=2), encoding='utf-8')
        probe_path = destination / 'runtime-probe.json'
        probe = json.loads(probe_path.read_text(encoding='utf-8'))
        probe['model_manifest_sha256'] = sha256(manifest_path)
        probe['packaging_exclusions'] = list(COMPILE_ONLY_MODEL_PREFIXES)
        probe_path.write_text(json.dumps(probe, indent=2), encoding='utf-8')
    validate_payload(destination, for_distribution=for_distribution)
    return destination
