"""Stage the sealed Total Spine model; its CPU runtime belongs to Alignment."""
import json
import os
from pathlib import Path
import shutil


def validate_payload(source, *, for_distribution=True):
    from modules.ai_imaging.eagle_eye_total_spine.service import validate_bundle, digest
    source = Path(source)
    manifest = validate_bundle(source)
    if (source/'assist').exists():
        from modules.ai_imaging.eagle_eye_total_spine.assist_assets import validate_assist
        validate_assist(source/'assist', for_distribution=for_distribution)
    if for_distribution:
        try:
            receipt = json.loads((source/'acceptance.json').read_text(encoding='utf-8'))
            if (receipt['manifest_sha256'] != digest(source/'manifest.json') or
                receipt['offline_inference'] != 'passed' or receipt['live_gui'] != 'passed' or
                receipt['distribution_rights_review'] != 'approved'):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError('Total Spine distribution requires model-bound inference, GUI and distribution-rights acceptance.') from None
    return manifest


def stage_eagle_eye_total_spine(payload, *, for_distribution=True):
    source = Path(os.environ.get('AIPACS_EAGLE_EYE_TOTAL_SPINE_SOURCE') or
                  Path(__file__).resolve().parents[1]/'generated-files/eagle-eye/total-spine')
    manifest = validate_payload(source, for_distribution=for_distribution)
    target = Path(payload)/'eagle_eye/total-spine'
    if target.exists():
        raise RuntimeError('Total Spine staging requires a fresh destination.')
    if not (Path(payload)/'eagle_eye/alignment/runtime/python.exe').is_file():
        raise RuntimeError('Total Spine requires the existing Alignment portable CPU runtime.')
    for name in [*manifest['sha256'], 'manifest.json', 'acceptance.json']:
        item = source/name
        if item.is_file():
            destination = target/name; destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
    if (source/'assist').is_dir():
        from modules.ai_imaging.eagle_eye_total_spine.assist_assets import validate_assist
        assist = validate_assist(source/'assist', for_distribution=for_distribution)
        for name in [*assist['sha256'], 'manifest.json', 'acceptance.json']:
            item = source/'assist'/name
            if item.is_file():
                destination = target/'assist'/name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, destination)
    validate_payload(target, for_distribution=for_distribution)
    return target
