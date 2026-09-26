"""Bounded label-only revisions through the existing authenticated job API."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import re
import shutil
import zlib

import numpy as np

from .contracts import digest, MAX_REVIEW_REQUEST

MAX_COMPRESSED = 16 * 1024**2
MAX_LABEL_BYTES = 128 * 1024**2


def validate(value):
    if not isinstance(value, dict) or set(value) != {'parent_job_id', 'source_mask_sha256', 'shape', 'labels_zlib'}:
        raise ValueError('Invalid segmentation correction fields.')
    if not re.fullmatch('[a-f0-9]{32}', str(value['parent_job_id'])) or not re.fullmatch('[a-f0-9]{64}', str(value['source_mask_sha256'])):
        raise ValueError('Invalid segmentation revision identity.')
    shape = value['shape']
    if not isinstance(shape, list) or len(shape) != 3 or any(type(n) is not int or not 1 <= n <= 2048 for n in shape):
        raise ValueError('Invalid segmentation dimensions.')
    if int(np.prod(shape)) * 2 > MAX_LABEL_BYTES:
        raise ValueError('Segmentation exceeds the review limit.')
    if not isinstance(value['labels_zlib'], str) or len(value['labels_zlib']) > (MAX_COMPRESSED + 2) // 3 * 4:
        raise ValueError('Compressed segmentation exceeds the review limit.')


def encode(original, edited, parent, source_hash, *, lesion=False):
    import SimpleITK as sitk
    from ..eagle_eye_brain.manual_review import validate_edit
    validate_edit(original, edited, lesion=lesion)
    array = sitk.GetArrayFromImage(edited)
    if array.nbytes > MAX_LABEL_BYTES or np.any(array > 65535) or np.any(array < 0):
        raise ValueError('Segmentation exceeds the label review limit.')
    data = zlib.compress(array.astype('<u2').tobytes())
    if len(data) > MAX_COMPRESSED:
        raise ValueError('Compressed segmentation exceeds the review limit.')
    value = dict(parent_job_id=parent, source_mask_sha256=source_hash,
                 shape=list(array.shape), labels_zlib=base64.b64encode(data).decode('ascii'))
    validate(value)
    return value


def decode(value, original, *, lesion=False):
    import SimpleITK as sitk
    from ..eagle_eye_brain.manual_review import validate_edit
    validate(value)
    if list(reversed(original.GetSize())) != value['shape']:
        raise ValueError('Corrected segmentation dimensions differ from the parent.')
    size = int(np.prod(value['shape'])) * 2
    try:
        compressed = base64.b64decode(value['labels_zlib'], validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(compressed, size + 1)
        if len(raw) != size or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Invalid expanded segmentation size.')
    except (ValueError, zlib.error) as exc:
        raise ValueError('Invalid compressed segmentation.') from exc
    array = np.frombuffer(raw, dtype='<u2').reshape(value['shape'])
    edited = sitk.GetImageFromArray(array)
    edited.CopyInformation(original)
    validate_edit(original, edited, lesion=lesion)
    return edited


def assets(result):
    """Explicit review files only, including the exact derived reference grid."""
    root = Path(result['artifact_directory']).resolve()
    if result.get('review_assets'):
        selected = {key: Path(path).resolve() for key, path in result['review_assets'].items()}
    elif result.get('analysis_type') == 'brain_lesions':
        selected = dict(image=root / 'flair.nii.gz', mask=Path(result['mask_path']).resolve())
    else:
        selected = dict(image=root / 'resampled.nii.gz', mask=root / 'labels.nii.gz', names=root / 'label_names.json')
    if any(not path.is_relative_to(root) or not path.is_file() for path in selected.values()):
        raise ValueError('The parent analysis lacks its owned review image or segmentation.')
    return selected


def submit(session, *, cancel=None, progress=None):
    import SimpleITK as sitk
    from .client import Client, save_handle, AnalysisFailed
    from ..eagle_eye_brain.contracts import BrainError
    if cancel is not None and cancel.is_set():
        raise BrainError('Manual recalculation cancelled.')
    directory = Path(session)
    manifest = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
    result = manifest['source_result']
    client = Client()
    module = 'brain-lesions' if manifest['lesion'] else 'brain'
    if module not in client.json('/v1/capabilities').get('correction_modules', []):
        raise ValueError('Update the Eagle Eye server to support segmentation corrections.')
    pending = directory / 'pending-server-review.json'
    if pending.is_file():
        handle = json.loads(pending.read_text(encoding='utf-8'))['handle']
        try:
            revised = client.resume(handle, directory, cancel=cancel, progress=progress)
        except AnalysisFailed:
            pending.unlink(missing_ok=True)
            raise
    else:
        if not (directory / 'corrected.nii.gz').is_file():
            raise BrainError('In Slicer, click Save correction for AI-PACS before recalculating.')
        if digest(manifest['source_mask']) != manifest['source_sha256']:
            raise ValueError('The source segmentation changed. Open a new review session.')
        original = sitk.ReadImage(str(directory / 'original.nii.gz'))
        edited = sitk.ReadImage(str(directory / 'corrected.nii.gz'))
        value = encode(original, edited, result['server_job_id'], manifest['source_sha256'], lesion=manifest['lesion'])
        from .client import DetachedAnalysis
        try:
            revised = client.analyze(module, result['analysis_study_uid'], result['analysis_series'],
                {'correction': value}, directory, cancel=cancel, progress=progress)
        except DetachedAnalysis as exc:
            save_handle(pending, {'handle': str(exc.handle_path)})
            raise
    pending.unlink(missing_ok=True)
    return revised


def calculate(request, output, cancel=None):
    import SimpleITK as sitk
    from ..eagle_eye_brain.manual_review import _recalculate_review
    output = Path(output)
    validate(request['parameters']['correction'])
    parent = output.parent.parent / request['parameters']['correction']['parent_job_id']
    original_result = json.loads((parent / 'worker-result.json').read_text(encoding='utf-8'))
    if not Path(original_result['artifact_directory']).resolve().is_relative_to(parent.resolve()):
        raise ValueError('Parent artifacts escaped their job.')
    selected = assets(original_result)
    value = request['parameters']['correction']
    if digest(selected['mask']) != value['source_mask_sha256']:
        raise ValueError('The corrected mask does not match the parent segmentation.')
    original = sitk.ReadImage(str(selected['mask']))
    edited = decode(value, original, lesion=request['module'] == 'brain-lesions')
    directory = output / 'manual-review'; directory.mkdir()
    shutil.copyfile(selected['mask'], directory / 'original.nii.gz')
    shutil.copyfile(selected['image'], directory / 'image.nii.gz')
    sitk.WriteImage(edited, str(directory / 'corrected.nii.gz'))
    manifest = dict(source_result=deepcopy(original_result), source_mask=str(selected['mask']),
                    source_sha256=value['source_mask_sha256'], lesion=request['module'] == 'brain-lesions')
    if not manifest['lesion']:
        manifest['label_names'] = json.loads(selected['names'].read_text(encoding='utf-8'))
    (directory / 'session.json').write_text(json.dumps(manifest), encoding='utf-8')
    revised = _recalculate_review(directory, cancel=cancel)
    root = Path(revised['artifact_directory'])
    # Each child owns the assets needed for another correction; never overwrite its parent.
    shutil.copyfile(selected['image'], root / 'review-image.nii.gz')
    revised['review_assets'] = dict(image=str(root / 'review-image.nii.gz'), mask=str(root / 'corrected.nii.gz'))
    if not manifest['lesion']:
        shutil.copyfile(selected['names'], root / 'label_names.json')
        revised['review_assets']['names'] = str(root / 'label_names.json')
    revised.update(parent_job_id=value['parent_job_id'], clinical_report_signed=False)
    return revised
