"""Owned background inference with private temporary pixels and reviewable masks."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import tempfile
import time

import numpy as np

from .assist_assets import validate_assist, WEIGHTS
from .mask_geometry import validate_box, propose_endplates
from .geometry import LEVELS, validate_landmarks


def image_binding(image):
    identity = image['identity']
    return dict(study_uid=identity['study_uid'], series_uid=identity['series_uid'],
                sop_uid=identity['sop_uid'], source_sha256=image['source_sha256'],
                projection=image['projection'], shape=list(image['pixels'].shape))


def _run(image, mode, cancel, box=None, runtime_seal=None, progress=None):
    from .service import bundle_root
    from ..eagle_eye_alignment import service as alignment
    from modules.mpr.advanced_3d_slicer.owned_process import ProcessJob
    pixels = np.asarray(image['pixels'])
    report = progress or (lambda *_: None)
    report(0, 4, 'Validating the local model and selected image')
    if pixels.ndim != 2 or pixels.dtype != np.uint8 or pixels.size > 80_000_000:
        raise ValueError('Expected bounded grayscale radiograph pixels.')
    root = bundle_root().resolve()/'assist'
    validate_assist(root, cancel)
    runtime = alignment.bundle_root().resolve()
    if runtime_seal is None:
        alignment.validate_bundle(runtime, cancel)
    else:
        runtime_seal.verify(runtime, cancel)
    if cancel.is_set():
        raise ValueError('Analysis cancelled.')
    origin = (0, 0)
    request = dict(mode=mode)
    if mode == 'sam':
        box = validate_box(box, pixels.shape)
        # Include context outside the box while retaining small body detail in
        # SAM's 1024-pixel encoder. Coordinate conversion is explicitly reversible.
        padding = np.maximum(16, (box[2:]-box[:2])*.35)
        x0, y0 = np.maximum(0, np.floor(box[:2]-padding)).astype(int)
        x1, y1 = np.minimum(pixels.shape[::-1], np.ceil(box[2:]+padding+1)).astype(int)
        pixels = pixels[y0:y1, x0:x1]
        if pixels.size > 16_000_000:
            raise ValueError('Select a smaller single-body region.')
        origin = (int(x0), int(y0))
        request['box'] = (box-np.array([x0, y0, x0, y0])).tolist()
    with tempfile.TemporaryDirectory(prefix='aipacs-spine-assist-') as temporary:
        folder = Path(temporary)
        np.save(folder/'input.npy', pixels, allow_pickle=False)
        (folder/'request.json').write_text(json.dumps(request), encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_'))}
        env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', CUDA_VISIBLE_DEVICES='-1',
                   HF_HUB_OFFLINE='1', OMP_NUM_THREADS='4')
        owner, process = ProcessJob(), None
        report(1, 4, 'Running the segmentation model')
        try:
            process = subprocess.Popen([str(runtime/'runtime/python.exe'), '-E', '-s', '-B',
                                        str(root/'worker.py'), str(root), str(folder)], cwd=folder, env=env,
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            owner.assign(process)
            deadline = time.monotonic()+240
            while process.poll() is None:
                if cancel.wait(.1):
                    raise ValueError('Analysis cancelled.')
                if time.monotonic() > deadline:
                    raise ValueError('Local analysis timed out. Manual placement remains available.')
            if cancel.is_set():
                raise ValueError('Analysis cancelled.')
            if process.returncode:
                raise ValueError('Local model execution failed. Verify the prepared package and retry.')
            result = json.loads((folder/'result.json').read_text(encoding='utf-8'))
            report(2, 4, 'Validating the generated mask')
            if mode == 'sam':
                mask = np.load(folder/'mask.npy', allow_pickle=False)
                if mask.dtype != np.bool_ or mask.shape != pixels.shape:
                    raise ValueError('Segmentation output has unexpected dimensions.')
                result.update(mask=mask, origin=origin)
            return result
        finally:
            owner.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=15)


def segment_body(image, level, box, cancel, *, runtime_seal=None, progress=None):
    from ..eagle_eye_remote.settings import remote_required
    if remote_required():
        from ..eagle_eye_remote.routing import spine_segmentation
        return spine_segmentation(image, level, box, cancel, progress)
    if level not in LEVELS or level == 'S1':
        raise ValueError('SAM body fitting supports C1-L5. Place S1 endplate landmarks manually.')
    if image['projection'] not in ('coronal', 'lateral'):
        raise ValueError('Unknown radiographic projection.')
    box = validate_box(box, image['pixels'].shape)
    result = _run(image, 'sam', cancel, box, runtime_seal,
                  **({'progress': progress} if progress is not None else {}))
    score = result.get('score')
    if not isinstance(score, (int, float)) or not np.isfinite(score):
        raise ValueError('The segmentation model returned an invalid quality estimate.')
    result.update(binding=image_binding(image), level=level, box=box.tolist(),
                  model='SAM ViT-B; reader-selected body; independent endplate fits',
                  weight_sha256=WEIGHTS['sam_vit_b.pth'][1],
                  mask_sha256=hashlib.sha256(result['mask'].tobytes()).hexdigest())
    result['proposal'] = None
    try:
        if score < .7:
            raise ValueError('Low SAM mask-quality estimate. Refine the box or place endplates manually.')
        mask = result['mask']
        x0, y0 = result['origin']
        bx0, by0, bx1, by1 = box-np.array([x0, y0, x0, y0])
        inside = mask[max(0, int(np.floor(by0))):min(mask.shape[0], int(np.ceil(by1))+1),
                      max(0, int(np.floor(bx0))):min(mask.shape[1], int(np.ceil(bx1))+1)].sum()
        if inside < .9*mask.sum():
            raise ValueError('The mask extends outside the selected body box. Refine the box.')
        proposal = propose_endplates(result['mask'], result['origin'])
        validate_landmarks({level: proposal['points']}, image['pixels'].shape)
        result['proposal'] = proposal
        result['proposal_error'] = ''
    except ValueError as exc:
        result['proposal_error'] = str(exc)
    if progress is not None:
        progress(3, 4, 'Preparing the mask and endplate preview')
    return result


def predict_scoliovis(image, cancel, *, runtime_seal=None):
    if image['projection'] != 'coronal':
        raise ValueError('ScolioVis is an AP model. Use SAM/manual endplates for lateral images.')
    result = _run(image, 'scoliovis', cancel, runtime_seal=runtime_seal)
    result.update(binding=image_binding(image), weight_sha256=WEIGHTS['scoliovis.pt'][1])
    return result
