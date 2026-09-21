"""Background-only model execution and identity-bound radiograph preparation."""
from pathlib import Path
import json
import os
import subprocess
import tempfile
import time

import numpy as np

from ..eagle_eye_alignment.service import digest, load_image, study_images as alignment_study_images
from .geometry import CORNERS, LEVELS, validate_landmarks, vertebra
from .inference import SOURCE_REVISION, WEIGHT_SHA256


def study_images(study_uid):
    """Read projection tags in the inventory worker, never infer from descriptions."""
    import pydicom
    rows = alignment_study_images(study_uid)
    for row in rows:
        ds = pydicom.dcmread(row['path'], stop_before_pixels=True)
        row['view_position'] = str(ds.get('ViewPosition', '')).strip().upper()
    return rows


def load_view(path, study_uid, series_uid, projection):
    import pydicom
    if projection not in ('coronal', 'lateral'):
        raise ValueError('Choose coronal or lateral projection.')
    image = load_image(path, study_uid, series_uid)
    ds = pydicom.dcmread(path, stop_before_pixels=True)
    position = str(ds.get('ViewPosition', '')).strip().upper()
    if ((projection == 'coronal' and position in ('LL', 'RL', 'LAT', 'LATERAL')) or
        (projection == 'lateral' and position in ('AP', 'PA'))):
        raise ValueError('DICOM ViewPosition conflicts with the selected projection.')
    if str(ds.get('SOPInstanceUID', '')) != image['identity']['sop_uid']:
        raise ValueError('The source identity changed during loading.')
    image.update(projection=projection, dicom_view_position=position)
    return image


def bundle_root():
    from ..eagle_eye.assets import installed_feature_roots
    override = os.environ.get('AIPACS_TOTAL_SPINE_BUNDLE')
    if override:
        return Path(override)
    roots = installed_feature_roots('total_spine')
    if not getattr(__import__('sys'), 'frozen', False):
        roots.insert(0, Path(__file__).resolve().parents[3]/'generated-files/eagle-eye/total-spine')
    for root in roots:
        if (root/'manifest.json').is_file():
            return root
    raise ValueError('Total Spine model package is unavailable. Manual landmark placement is available.')


def validate_bundle(root):
    root = Path(root).resolve()
    required = {'inference.py', 'model_last.pth', 'LICENSE', 'NOTICE', 'decoder.py',
                'models/__init__.py', 'models/spinal_net.py', 'models/dec_net.py',
                'models/model_parts.py', 'models/resnet.py'}
    try:
        manifest = json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        if (manifest['source_revision'] != SOURCE_REVISION or manifest['weight_sha256'] != WEIGHT_SHA256 or
            set(manifest['sha256']) != required or manifest['runtime_provider'] != 'alignment'):
            raise ValueError
        for name, expected in manifest['sha256'].items():
            path = (root/name).resolve()
            if not path.is_relative_to(root) or digest(path) != expected:
                raise ValueError
        if manifest['sha256']['model_last.pth'] != WEIGHT_SHA256:
            raise ValueError
    except (OSError, ValueError, KeyError, TypeError):
        raise ValueError('Total Spine model package is missing or changed. Run prepare_total_spine.py.') from None
    return manifest


def predict(image, cancel):
    from ..eagle_eye_alignment import service as alignment
    from modules.mpr.advanced_3d_slicer.owned_process import ProcessJob
    if image['projection'] != 'coronal':
        raise ValueError('This checkpoint supports coronal radiographs only. Place lateral points manually.')
    root = bundle_root().resolve()
    validate_bundle(root)
    runtime = alignment.bundle_root().resolve()
    alignment.validate_bundle(runtime, cancel)
    if cancel.is_set():
        raise ValueError('Analysis cancelled.')
    with tempfile.TemporaryDirectory(prefix='aipacs-total-spine-') as temporary:
        folder = Path(temporary)
        np.save(folder/'input.npy', image['pixels'], allow_pickle=False)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_'))}
        env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='-1',
                   HF_HUB_OFFLINE='1', OMP_NUM_THREADS='4')
        owner, process = ProcessJob(), None
        try:
            process = subprocess.Popen([str(runtime/'runtime/python.exe'), '-E', '-s', '-B',
                                        str(root/'inference.py'), str(root), str(folder/'input.npy'),
                                        str(folder/'result.json')], cwd=folder, env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            owner.assign(process)
            deadline = time.monotonic()+180
            while process.poll() is None:
                if cancel.wait(.1):
                    raise ValueError('Analysis cancelled.')
                if time.monotonic() > deadline:
                    raise ValueError('Total Spine analysis timed out. Manual placement is available.')
            if cancel.is_set():
                raise ValueError('Analysis cancelled.')
            if process.returncode:
                raise ValueError('The landmark model could not analyze this image. Manual placement is available.')
            return json.loads((folder/'result.json').read_text(encoding='utf-8'))
        finally:
            owner.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=15)


def assign_candidates(result, shape, first_level='T1'):
    """Explicit sequential numbering assumption; reject any missing/weak proposal.

    The model has a single vertebra class. It does NOT identify T1 or transitional
    anatomy. The caller must request numbering confirmation separately.
    """
    if first_level not in LEVELS:
        raise ValueError('Unknown first level.')
    candidates = result.get('candidates', [])
    start = LEVELS.index(first_level)
    if len(candidates) != 17 or start+17 > LEVELS.index('S1'):
        raise ValueError('The model requires 17 visible thoracolumbar bodies. Correct manually for incomplete or variant anatomy.')
    points = {}
    previous_y = -1.
    for level, item in zip(LEVELS[start:start+17], candidates):
        confidence = item.get('confidence')
        if not isinstance(confidence, (int, float)) or not np.isfinite(confidence) or not .2 <= confidence <= 1.:
            raise ValueError('A vertebra proposal has low confidence. Place points manually or use another complete image.')
        corners = np.asarray(item.get('corners'), dtype=float)
        if corners.shape != (4, 2):
            raise ValueError('Invalid landmark model output.')
        points[level] = dict(zip(CORNERS, corners.tolist()))
        center_y = float(vertebra(points[level])[:, 1].mean())
        if center_y <= previous_y:
            raise ValueError('Model proposals are not in upright order.')
        previous_y = center_y
    validate_landmarks(points, shape)
    return points
