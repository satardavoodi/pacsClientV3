"""Geometry-checked marrow mask revisions through authenticated server jobs."""
import json
from pathlib import Path
import shutil


def submit(session, cancel):
    import SimpleITK as sitk
    from .eagle_eye_remote.client import Client, DetachedAnalysis, AnalysisFailed, save_handle
    from .eagle_eye_remote.contracts import digest
    from .eagle_eye_remote.segmentation_review import encode
    root = Path(session)
    manifest = json.loads((root / 'session.json').read_text(encoding='utf-8'))
    result = manifest['source_result']
    client = Client()
    if 'lumbar-marrow' not in client.json('/v1/capabilities').get('correction_modules', []):
        raise ValueError('Update Eagle Eye Server to enable marrow corrections.')
    pending = root / 'pending-marrow-review.json'
    if pending.is_file():
        handle = json.loads(pending.read_text(encoding='utf-8'))['handle']
        try:
            revised = client.resume(handle, root, cancel=cancel)
        except AnalysisFailed:
            pending.unlink(missing_ok=True)
            raise
        pending.unlink(missing_ok=True)
        revised['patient_context'] = result.get('patient_context', {})
        path = Path(revised['report_html'])
        return revised, path.read_text(encoding='utf-8'), str(path)
    if digest(manifest['source_mask']) != manifest['source_sha256']:
        raise ValueError('Original mask changed; open a new session.')
    if not (root / 'corrected.nii.gz').is_file():
        raise ValueError('Save correction for AI-PACS in Slicer first.')
    value = encode(sitk.ReadImage(str(root / 'original.nii.gz')), sitk.ReadImage(str(root / 'corrected.nii.gz')),
                   result['server_job_id'], manifest['source_sha256'])
    try:
        revised = client.analyze('lumbar-marrow', result['analysis_study_uid'], result['analysis_series'],
                                 {'correction': value}, root, cancel=cancel)
    except DetachedAnalysis as exc:
        save_handle(pending, {'handle':str(exc.handle_path)})
        raise
    revised['patient_context'] = result.get('patient_context', {})
    path = Path(revised['report_html'])
    return revised, path.read_text(encoding='utf-8'), str(path)


def calculate(request, output, cancel):
    import numpy as np
    import SimpleITK as sitk
    from .eagle_eye_remote.segmentation_review import assets, decode
    from .eagle_eye_remote.contracts import digest
    from .lumbar_marrow import measure
    value = request['parameters']['correction']
    output = Path(output)
    parent = output.parent.parent / value['parent_job_id']
    result = json.loads((parent / 'worker-result.json').read_text(encoding='utf-8'))
    if not Path(result['artifact_directory']).resolve().is_relative_to(parent.resolve()):
        raise ValueError('Parent artifacts escaped their job.')
    selected = assets(result)
    if digest(selected['mask']) != value['source_mask_sha256']:
        raise ValueError('Correction mask does not match parent.')
    edited = decode(value, sitk.ReadImage(str(selected['mask'])))
    if cancel.is_set():
        raise ValueError('Correction cancelled.')
    image = sitk.ReadImage(str(selected['image']))
    for getter in ('GetSize', 'GetSpacing', 'GetDirection', 'GetOrigin'):
        if not np.allclose(getattr(image, getter)(), getattr(edited, getter)()):
            raise ValueError('Reference image geometry changed.')
    if result.get('task') == 'lumbar_marrow_multiparametric_v1':
        from .marrow_multisequence import recalculate
        original_request = json.loads((parent / 'request.json').read_text(encoding='utf-8'))
        if (request['study_uid'] != original_request['study_uid']
                or request['series'] != original_request['series']):
            raise ValueError('Correction source references differ from the parent analysis.')
        output.mkdir(parents=True, exist_ok=True)
        revised = recalculate(result, edited, output, cancel)
        revised['parent_job_id'] = value['parent_job_id']
        revised['clinical_report_signed'] = False
        return revised
    labels = sitk.GetArrayFromImage(edited)
    output.mkdir(parents=True, exist_ok=True)
    np.save(output / 'labels.npy', labels, allow_pickle=False)
    sitk.WriteImage(edited, str(output / 'labels.nii.gz'))
    shutil.copyfile(selected['image'], output / 'review-image.nii.gz')
    shutil.copyfile(selected['names'], output / 'label_names.json')
    revised = measure(sitk.GetArrayFromImage(image), labels, result['affine_ras'], result['segments'], output,
                      {'t1_confirmed': True, 'clinical': result.get('clinical_context', {})})
    revised.update(artifact_directory=str(output), segments=result['segments'], affine_ras=result['affine_ras'],
                   shape_kji=list(labels.shape), labels_file=str(output / 'labels.npy'), parent_job_id=value['parent_job_id'],
                   clinical_report_signed=False, review_assets={'image':str(output / 'review-image.nii.gz'),
                       'mask':str(output / 'labels.nii.gz'), 'names':str(output / 'label_names.json')})
    return revised
