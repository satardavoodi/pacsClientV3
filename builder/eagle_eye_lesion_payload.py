"""Eagle Eye only, hash-verified portable MS lesion payload staging."""
import json
import os
from pathlib import Path
import shutil


def validate_payload(source, *, for_distribution=True):
    from modules.ai_imaging.eagle_eye_brain.lesions import validate_lesion_bundle
    from modules.ai_imaging.eagle_eye_brain.runtime import sha256
    source = Path(source)
    manifest = validate_lesion_bundle(source)
    if for_distribution:
        try:
            receipt = json.loads((source / 'acceptance.json').read_text(encoding='utf-8'))
            if (receipt['manifest_sha256'] != sha256(source / 'manifest.json')
                    or receipt['offline_inference'] != 'passed' or receipt['live_gui'] != 'passed'
                    or receipt['distribution_rights_review'] != 'approved'):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError):
            raise RuntimeError('MS lesion distribution requires model-bound offline inference, GUI acceptance and asset rights review.') from None
    return manifest


def stage_eagle_eye_lesions(payload, *, for_distribution=True):
    source = Path(os.environ.get('AIPACS_EAGLE_EYE_LESION_SOURCE') or
                  Path(__file__).resolve().parents[1] / 'generated-files/eagle-eye/brain-lesions')
    manifest = validate_payload(source, for_distribution=for_distribution)
    target = Path(payload) / 'eagle_eye/brain-lesions'
    if target.exists():
        raise RuntimeError('Lesion payload staging requires a fresh destination.')
    for name in [*manifest['sha256'], 'manifest.json', 'acceptance.json']:
        item = source / name
        if item.is_file():
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
    validate_payload(target, for_distribution=for_distribution)
    return target
