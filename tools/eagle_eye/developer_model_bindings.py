"""Validate all model bindings before staging or activating a Developer snapshot.

Host-private environments and settings are deliberately outside this inventory.
An explicit preserved calcium directory is allowed only with the reviewed seal.
"""
import argparse
import hashlib
import json
from pathlib import Path

MODEL_BINDINGS = (
    'generated-files/eagle-eye/bone-age',
    'generated-files/eagle-eye/breast',
    'generated-files/eagle-eye/brain-tf212-py310',
    'generated-files/eagle-eye/brain-lesions',
    'generated-files/eagle-eye/alignment',
    'generated-files/eagle-eye/total-spine',
    'generated-files/offline-lumbar',
    'generated-files/eagle-eye/calcium-b95',
)
CALCIUM_MANIFEST_SHA256 = '889df3e37ca6e7991e6190fe887f0ad8f16bb34fb7a7a1055959c51209ff10c6'


def _digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_calcium(root):
    """Reject a missing, changed, incomplete or unsealed calcium payload."""
    root = Path(root).resolve()
    manifest = root / 'manifest.json'
    if not manifest.is_file():
        raise ValueError('Missing calcium manifest.')
    if _digest(manifest) != CALCIUM_MANIFEST_SHA256:
        raise ValueError('Unapproved calcium manifest.')
    data = json.loads(manifest.read_text(encoding='utf-8'))
    hashes = data.get('sha256', {})
    if (data.get('format') != 'breast_calcium_v1' or not hashes
            or not {'runner.py', 'physical_peaks_fast.py'} <= hashes.keys()):
        raise ValueError('Invalid calcium manifest.')
    actual = {
        p.relative_to(root).as_posix() for p in root.rglob('*')
        if p.is_file() and p != manifest and '__pycache__' not in p.parts
    }
    if actual != set(hashes):
        raise ValueError('Calcium inventory differs from its seal.')
    for name, expected in hashes.items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or _digest(path) != expected:
            raise ValueError('Calcium integrity check failed.')
    return len(hashes)


def model_bindings(source, *, calcium_source=None):
    """Return verified targets; call again without overrides on the staged source."""
    source = Path(source).resolve()
    targets = {name: (source / name).resolve() for name in MODEL_BINDINGS}
    if calcium_source is not None:
        targets[MODEL_BINDINGS[-1]] = Path(calcium_source).resolve()
    for name, target in targets.items():
        if not target.is_dir():
            raise ValueError(f'Missing Developer model binding: {name}')
    validate_calcium(targets[MODEL_BINDINGS[-1]])
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--calcium-source', type=Path)
    args = parser.parse_args()
    bindings = model_bindings(args.source, calcium_source=args.calcium_source)
    print(json.dumps({'bindings': len(bindings), 'calcium_files': validate_calcium(
        bindings[MODEL_BINDINGS[-1]]), 'calcium_manifest_sha256': CALCIUM_MANIFEST_SHA256}))
