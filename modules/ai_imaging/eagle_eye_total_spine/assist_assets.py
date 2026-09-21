"""Pinned optional SAM/ScolioVis assets, nested under the Total Spine package."""
from pathlib import Path
import json

SAM_REVISION = 'dca509fe793f601edb92606367a655c15ac00fdf'
SCOLIOVIS_REVISION = '1edbe566c4acd4df33e0834db0f4cb9fa357ba2c'
WEIGHTS = {
    'sam_vit_b.pth': ('https://dl.fbaipublicfiles.com/segment_anything/sam_vit_b_01ec64.pth',
                      'ec2df62732614e57411cdcf32a23ffdf28910380d03139ee0f4fcbe91eb8c912'),
    'scoliovis.pt': ('https://github.com/Blankeos/scoliovis-training/releases/download/latest/keypointsrcnn_weights.pt',
                     '990f3ad661f07dc8975dc655876e2fc3bfa64c8da941c485465589083448c32b'),
}
SAM_FILES = ('__init__.py', 'build_sam.py', 'predictor.py', 'modeling/__init__.py',
             'modeling/common.py', 'modeling/image_encoder.py', 'modeling/mask_decoder.py',
             'modeling/prompt_encoder.py', 'modeling/sam.py', 'modeling/transformer.py',
             'utils/__init__.py', 'utils/transforms.py')
REQUIRED = {'worker.py', 'NOTICE', 'SAM_LICENSE', 'sam_vit_b.pth', 'scoliovis.pt',
            *('segment_anything/'+name for name in SAM_FILES)}


def validate_assist(root, cancel=None, *, for_distribution=False):
    from ..eagle_eye_alignment.service import digest
    root = Path(root).resolve()
    try:
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if (manifest['format_version'] != 1 or manifest['sam_revision'] != SAM_REVISION or
                manifest['scoliovis_revision'] != SCOLIOVIS_REVISION or
                set(manifest['sha256']) != REQUIRED):
            raise ValueError
        for name, expected in manifest['sha256'].items():
            if cancel is not None and cancel.is_set():
                raise ValueError('Analysis cancelled.')
            path = (root/name).resolve()
            if not path.is_relative_to(root) or digest(path) != expected:
                raise ValueError
        for name, (_, expected) in WEIGHTS.items():
            if manifest['sha256'][name] != expected:
                raise ValueError
    except (OSError, KeyError, TypeError, ValueError):
        raise ValueError('SAM/ScolioVis package is unavailable or changed. Run prepare_total_spine_assist.py.') from None
    if for_distribution:
        try:
            receipt = json.loads((root/'acceptance.json').read_text(encoding='utf-8'))
            if (receipt['manifest_sha256'] != digest(root/'manifest.json') or
                    any(receipt[k] != 'passed' for k in ('offline_inference', 'live_gui')) or
                    receipt['distribution_rights_review'] != 'approved'):
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError):
            raise RuntimeError('SAM/ScolioVis distribution requires separate model-bound acceptance.') from None
    return manifest
