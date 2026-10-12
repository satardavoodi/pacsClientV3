"""Worker-only restoration of source-bound Alignment archives; no inference."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np


class ReviewMetadataUnavailable(ValueError):
    """A valid historical PDF lacks enough state for editable measurements."""


def _read(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root) or path.stat().st_size > 16 * 1024**2:
        raise ValueError('Saved Alignment artifact is invalid.')
    return json.loads(path.read_text(encoding='utf-8'))


def _legacy_metadata(result, image, root):
    """Recover old locally submitted corrections from the retained request receipt."""
    from ..eagle_eye_remote.reviews import validate_correction
    handles = root.parent/'.eagle-eye-jobs'
    for index, path in enumerate(handles.glob('*.json')):
        if index >= 10000:break
        try:
            handle = _read(path, handles.resolve())
            request = handle.get('request', {})
            ref = request.get('series', {}).get('primary', {})
            if (handle.get('job_id') != result.get('server_job_id')
                    or request.get('module') != 'alignment'
                    or request.get('study_uid') != image['identity']['study_uid']
                    or any(ref.get(k) != image['identity'].get(k) for k in ('series_uid','sop_uid'))):
                continue
            correction = request.get('parameters', {}).get('correction')
            validate_correction(correction)
            if (correction['landmarks'] != result['landmarks']
                    or correction['parent_job_id'] != result.get('parent_job_id')):continue
            return dict(identity=image['identity'],landmarks=correction['landmarks'],
                        spacing=correction['spacing'], calibrated=correction['calibrated'],
                        horizontal_flip=correction['flipped'], notes=correction['notes'],
                        calibration_method='Saved operator scale' if correction['calibrated'] else 'Unverified scale; lengths in pixels')
        except (OSError, ValueError, TypeError, AttributeError):continue
    raise ReviewMetadataUnavailable('This older PDF lacks editable review metadata. Open the saved PDF or select its source image for a new review.')


def restore(result, image):
    from ..eagle_eye_remote.radiograph_binding import bind_result
    from .service import validate_points, digest
    result = deepcopy(result)
    bind_result(result, image, 'alignment')
    validate_points(result['landmarks'], image['pixels'].shape)
    restored = dict(image)
    notes = {}
    if result.get('pdf_available'):
        root = Path(result['artifact_directory']).resolve()
        modern = (root/'report.json').exists()
        payload = _read(root/'report.json', root) if modern else _legacy_metadata(result, image, root)
        if (any(payload.get('identity', {}).get(k) != image['identity'].get(k)
                for k in ('study_uid', 'series_uid', 'sop_uid'))
                or payload.get('landmarks') != result['landmarks']):
            raise ValueError('Saved report does not match the selected source and landmarks.')
        pdf = (root/'report.pdf').resolve()
        if not pdf.is_relative_to(root) or not pdf.is_file() or (modern and digest(pdf) != payload.get('pdf_sha256')):
            raise ValueError('Saved PDF changed. Retrieve the original server report again.')
        spacing = np.asarray(payload.get('spacing'), dtype=float)
        if spacing.shape != (2,) or not np.isfinite(spacing).all() or (spacing <= 0).any():
            raise ValueError('Saved image calibration is invalid.')
        if type(payload.get('horizontal_flip')) is not bool or type(payload.get('calibrated')) is not bool:
            raise ValueError('Saved image orientation or calibration is invalid.')
        if payload['horizontal_flip']:
            restored['pixels'] = np.ascontiguousarray(image['pixels'][:, ::-1])
        restored.update(spacing=tuple(spacing.tolist()), calibrated=payload['calibrated'],
                        flipped=payload['horizontal_flip'],
                        calibration_method=str(payload.get('calibration_method', 'Saved report scale')))
        notes = payload.get('notes', {})
        if (not isinstance(notes, dict) or set(notes)-{'indication','comparison','impression'}
                or any(not isinstance(v, str) or len(v)>500 for v in notes.values())):
            raise ValueError('Saved report notes are invalid.')
    return dict(image=restored, result=result, notes=notes)


def find(image, root=None):
    from PacsClient.utils.data_paths import AI_DIR
    root = Path(root or Path(AI_DIR)/'eagle_eye').resolve()
    candidates = []
    for index, path in enumerate(root.glob('remote-*/result.json')):
        if index >= 10000:
            break
        try:
            result = _read(path, root)
            if (result.get('server_module') not in (None, 'alignment')
                    or 'landmarks' not in result or not result.get('remote_analysis')
                    or Path(result.get('artifact_directory', '')).resolve() != path.parent.resolve()):
                continue
            sources = result.get('source_binding', [])
            if len(sources) != 1 or any(sources[0].get(k) != image['identity'].get(k)
                                      for k in ('study_uid', 'series_uid', 'sop_uid')):
                continue
            candidates.append((path.stat().st_mtime_ns, result))
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    if not candidates:
        return None
    # A damaged newest review must not silently fall back to older measurements
    # or trigger new inference that overwrites the user's expectation.
    return restore(max(candidates, key=lambda row: row[0])[1], image)


def load(path, study_uid, series_uid):
    from .service import load_image
    image = load_image(path, study_uid, series_uid)
    return dict(image=image, saved=find(image))


def prepare(result, study_uid):
    from . import service
    import pydicom
    sources = result.get('source_binding', [])
    if len(sources) != 1 or sources[0].get('study_uid') != study_uid:
        raise ValueError('Saved Alignment belongs to another examination.')
    source = sources[0]
    for row in service.study_images(study_uid):
        if row['series_uid'] != source.get('series_uid'):
            continue
        ds = pydicom.dcmread(row['path'], stop_before_pixels=True, specific_tags=['SOPInstanceUID'])
        if str(ds.get('SOPInstanceUID', '')) == source.get('sop_uid'):
            image = service.load_image(row['path'], study_uid, row['series_uid'])
            try:
                return dict(image=image, saved=restore(result, image), row=row)
            except ReviewMetadataUnavailable as error:
                root = Path(result['artifact_directory']).resolve()
                pdf = (root/'report.pdf').resolve()
                if not pdf.is_relative_to(root) or not pdf.is_file():raise
                return dict(image=image, saved=None, row=row, report=result, notice=str(error))
    raise ValueError('Load the original Alignment series in the viewer, then reopen this result.')
