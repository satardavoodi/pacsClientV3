"""Prepare hash-pinned offline SAM and ScolioVis without changing the PACS venv."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import sys
import urllib.request

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from modules.ai_imaging.eagle_eye_total_spine.assist_assets import (
    SAM_REVISION, SCOLIOVIS_REVISION, SAM_FILES, WEIGHTS, REQUIRED, validate_assist)


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    base = 'https://raw.githubusercontent.com/facebookresearch/segment-anything/'+SAM_REVISION+'/'
    for name in SAM_FILES:
        target = root/'segment_anything'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(base+'segment_anything/'+name, timeout=40) as response:
            content = response.read().decode('utf-8')
        # The automatic whole-image generator is deliberately excluded: this
        # integration uses one reader-selected body, not unlabeled object masks.
        if name == '__init__.py':
            content = content.replace('from .automatic_mask_generator import SamAutomaticMaskGenerator', '')
        target.write_text(content, encoding='utf-8')
    with urllib.request.urlopen(base+'LICENSE', timeout=40) as response:
        (root/'SAM_LICENSE').write_bytes(response.read())
    cache = REPO/'generated-files/eagle-eye/total-spine-assist-downloads'
    for name, (url, expected) in WEIGHTS.items():
        target = root/name
        if target.is_file() and sha(target) == expected:
            continue
        partial = target.with_suffix('.partial')
        if (cache/name).is_file() and sha(cache/name) == expected:
            shutil.copyfile(cache/name, partial)
        else:
            with urllib.request.urlopen(url, timeout=60) as source, partial.open('wb') as output:
                shutil.copyfileobj(source, output, 1024*1024)
        if sha(partial) != expected:
            raise ValueError('Downloaded weight does not match its pinned SHA-256: '+name)
        partial.replace(target)
    shutil.copyfile(REPO/'modules/ai_imaging/eagle_eye_total_spine/assist_worker.py', root/'worker.py')
    (root/'NOTICE').write_text(
        'SAM: Meta FAIR, https://github.com/facebookresearch/segment-anything, Apache-2.0.\n'
        'SAM source adapted only to omit the automatic mask generator export.\n'
        'ScolioVis: Taleon, Elizalde, Rubinos, WVSU-CICT 2023.\n'
        'https://github.com/Blankeos/scoliovis; released Keypoint R-CNN weights.\n'
        'No upstream ScolioVis source is bundled. An independent torchvision loader\n'
        'uses the published architecture and strict weights-only state loading.\n'
        'ScolioVis weight redistribution permission remains unresolved.\n'
        'Local research execution only; no clinical validation is asserted.\n', encoding='utf-8')
    manifest = dict(format_version=1, sam_revision=SAM_REVISION, scoliovis_revision=SCOLIOVIS_REVISION,
                    runtime_provider='alignment', sha256={name: sha(root/name) for name in sorted(REQUIRED)})
    (root/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    validate_assist(root)
    print('Prepared and verified SAM ViT-B and ScolioVis; no runtime packages were modified.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=REPO/'generated-files/eagle-eye/total-spine/assist')
    prepare(parser.parse_args().destination)
