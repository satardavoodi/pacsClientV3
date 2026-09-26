"""UI-worker bridges preserving existing result interfaces without uploading images."""
from pathlib import Path
import threading

from .client import Client


class CancelFlag:
    def __init__(self, check):
        self.check = check
    def is_set(self):
        return bool(self.check())
    def wait(self, seconds):
        import time
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline and not self.is_set():
            time.sleep(min(.05, max(0, deadline - time.monotonic())))
        return self.is_set()


def reference(path):
    """Only headers are used; the client never serializes the source pixel buffer."""
    import pydicom
    source = Path(path)
    files = [source] if source.is_file() else [p for p in source.iterdir() if p.is_file() and p.suffix.lower() in ('.dcm', '.dicom', '')]
    if not 1 <= len(files) <= 10000:
        raise ValueError('Select a complete PACS-backed DICOM series.')
    identity, seen = None, set()
    for filename in files:
        ds = pydicom.dcmread(filename, stop_before_pixels=True,
                             specific_tags=['StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID'])
        current = (str(ds.get('StudyInstanceUID', '')), str(ds.get('SeriesInstanceUID', '')))
        if identity is not None and identity != current:
            raise ValueError('Select one DICOM series from the current examination.')
        identity = current
        sop = str(ds.get('SOPInstanceUID', ''))
        if not sop or sop in seen:
            raise ValueError('Source inventory is incomplete or duplicated.')
        seen.add(sop)
    return identity[0], dict(series_uid=identity[1], expected_count=len(files))


def brain(t1, flair, output, *, plan=None, cancel=None, progress=None, reference_id='volbrain'):
    study, first = reference(t1)
    refs = {'t1': first}
    if flair:
        second_study, second = reference(flair)
        if second_study != study:
            raise ValueError('Select T1 and FLAIR from the same study.')
        refs['flair'] = second
    return Client().analyze('brain', study, refs,
        {'profile': getattr(plan, 'profile', 'standard'), 'reference_id': reference_id},
        output, cancel=cancel, progress=progress)


def lesions(t1, flair, study, t1_uid, flair_uid, output, *, cancel=None, progress=None, **params):
    first_study, first = reference(t1)
    second_study, second = reference(flair)
    if (first_study != study or second_study != study or first['series_uid'] != t1_uid
            or second['series_uid'] != flair_uid):
        raise ValueError('Selected source identities changed.')
    client = Client()
    if params.get('acquisition_mode') == '2d' and '2d' not in client.json('/v1/capabilities').get('lesion_acquisition_modes', []):
        raise ValueError('This Eagle Eye Server needs the 2D lesion update. No analysis was submitted.')
    return client.analyze('brain-lesions', study, {'t1': first, 'flair': second}, params,
                            output, cancel=cancel, progress=progress)


def radiograph(module, image, cancel, *, region=None, model='isbi'):
    from PacsClient.utils.data_paths import AI_DIR
    identity = image['identity']
    ref = {k: identity[k] for k in ('series_uid', 'sop_uid')}
    ref['expected_count'] = 1
    params = {} if module == 'alignment' else {'region': list(region), 'projection': 'coronal', 'model': model}
    result = Client().analyze(module, identity['study_uid'], {'primary': ref}, params,
                              Path(AI_DIR) / 'eagle_eye', cancel=cancel)
    from .radiograph_binding import bind_result
    return bind_result(result, image, module)


def study(module, study_uid, *, sex=None, threshold=.45, cancelled=lambda: False):
    from PacsClient.utils.data_paths import ATTACHMENTS_DIR
    normalized_sex = {'m': 'M', 'male': 'M', '0': 'M', 'f': 'F', 'female': 'F', '1': 'F'}.get(str(sex or '').lower())
    params = {'threshold': threshold} if module == 'breast' else {'sex': normalized_sex}
    result = Client().analyze(module, study_uid, {}, params, ATTACHMENTS_DIR / study_uid,
                              cancel=CancelFlag(cancelled))
    if module == 'breast':
        # Existing MG review widgets address CSV files relative to the study root.
        import shutil
        for key in ('csv', 'csv_classification'):
            if result.get(key):
                source = Path(result[key])
                target = ATTACHMENTS_DIR / study_uid / (source.stem + '_' + result['server_job_id'] + '.csv')
                temporary = target.with_suffix('.partial')
                shutil.copyfile(source, temporary)
                temporary.replace(target)
                result[key] = str(target)
    return result


def alignment_correction(image, points, provenance, notes, reviewed, cancel=None):
    from PacsClient.utils.data_paths import AI_DIR
    from .radiograph_binding import bind_result
    parent = provenance.get('server_job_id')
    if not parent:
        raise ValueError('Run server Alignment analysis before submitting a correction.')
    bind_result(provenance, image, 'alignment')
    identity = image['identity']
    ref = {key: identity[key] for key in ('series_uid', 'sop_uid')}
    ref['expected_count'] = 1
    correction = dict(parent_job_id=parent, landmarks=points, spacing=list(image['spacing']),
                      calibrated=bool(image['calibrated']), flipped=bool(image.get('flipped', False)),
                      acquisition_reviewed=provenance.get('acquisition_reviewed') is True,
                      landmarks_reviewed=bool(reviewed), notes=notes or {})
    client = Client()
    if 'alignment' not in client.json('/v1/capabilities').get('correction_modules', []):
        raise ValueError('This server does not support Alignment corrections. Update the Eagle Eye server.')
    result = client.analyze('alignment', identity['study_uid'], {'primary': ref},
                           {'correction': correction}, Path(AI_DIR)/'eagle_eye', cancel=cancel)
    return bind_result(result, image, 'alignment')


def resume_alignment_correction(image, handle_path, cancel=None):
    from PacsClient.utils.data_paths import AI_DIR
    from .radiograph_binding import bind_result
    result = Client().resume(handle_path, Path(AI_DIR)/'eagle_eye', cancel=cancel)
    return bind_result(result, image, 'alignment')


def spine_segmentation(image, level, box, cancel, progress=None):
    import hashlib
    import numpy as np
    from PacsClient.utils.data_paths import AI_DIR
    from .radiograph_binding import bind_result
    identity = image['identity']
    ref = {k: identity[k] for k in ('series_uid', 'sop_uid')}
    ref['expected_count'] = 1
    client = Client()
    if not client.json('/v1/capabilities').get('spine_box_segmentation'):
        raise ValueError('Update the Eagle Eye server to support vertebral body segmentation.')
    result = client.analyze('total-spine', identity['study_uid'], {'primary': ref},
        dict(model='sam', projection=image['projection'], level=level, region=list(box)),
        Path(AI_DIR) / 'eagle_eye', cancel=cancel)
    result = bind_result(result, image, 'total-spine')
    mask = np.load(result['mask_file'], allow_pickle=False, mmap_mode='r')
    if (mask.ndim != 2 or mask.size > 80_000_000 or mask.dtype.kind not in 'bu'
            or not np.isin(mask, (0, 1)).all()
            or hashlib.sha256(mask.tobytes()).hexdigest() != result['mask_sha256']
            or result.get('level') != level):
        raise ValueError('The server segmentation does not match the selected body.')
    result['mask'] = np.array(mask, copy=True)
    if progress is not None:
        progress(3, 4, 'Server mask and endplate preview received')
    return result
