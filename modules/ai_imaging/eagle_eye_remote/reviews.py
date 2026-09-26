"""Shared revision ownership/staging and server-only Alignment recalculation."""
import json
import math
import re
import shutil
from pathlib import Path

from .contracts import digest


class RevisionConflict(ValueError):
    pass


def validate_correction(value):
    from ..eagle_eye_alignment.geometry import LANDMARKS
    keys = {'parent_job_id', 'landmarks', 'spacing', 'calibrated', 'flipped',
            'acquisition_reviewed', 'landmarks_reviewed', 'notes'}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError('Invalid correction fields.')
    if not isinstance(value['parent_job_id'], str) or not re.fullmatch('[a-f0-9]{32}', value['parent_job_id']):
        raise ValueError('Invalid parent analysis.')
    for key in ('calibrated', 'flipped', 'acquisition_reviewed', 'landmarks_reviewed'):
        if type(value[key]) is not bool:
            raise ValueError('Invalid review state.')
    def pair(p, positive=False):
        return (isinstance(p, list) and len(p) == 2 and all(type(x) in (int, float)
                and math.isfinite(x) and (x > 0 if positive else x >= 0) for x in p))
    if not pair(value['spacing'], True):
        raise ValueError('Invalid calibration.')
    points = value['landmarks']
    if not isinstance(points, dict) or set(points) != {'R', 'L'}:
        raise ValueError('Both anatomical sides are required.')
    for side in points.values():
        if not isinstance(side, dict) or set(side) != set(LANDMARKS) or not all(pair(p) for p in side.values()):
            raise ValueError('Complete finite landmarks are required.')
    notes = value['notes']
    if (not isinstance(notes, dict) or set(notes) - {'indication','comparison','impression'}
            or any(not isinstance(v, str) or len(v) > 500 for v in notes.values())):
        raise ValueError('Invalid report notes.')
    if value['landmarks_reviewed'] and not value['acquisition_reviewed']:
        raise ValueError('Acquisition review is required.')


def check_parent(jobs, owner, request):
    correction = request['parameters'].get('correction')
    if not correction:
        return None
    parent = correction['parent_job_id']
    if parent is None and request['module'] == 'total-spine':
        return None
    state = jobs.get(owner, parent)
    original = json.loads((jobs.root / parent / 'request.json').read_text(encoding='utf-8'))
    source_match = original['series'] == request['series']
    if request['module'] == 'total-spine':
        source_match = (all(request['series'].get(k) == v for k, v in original['series'].items())
                        and set(request['series']) - set(original['series']) <= {'secondary'})
    if (state['status'] != 'succeeded' or not source_match
            or any(original[k] != request[k] for k in ('module','study_uid'))):
        raise ValueError('Correction does not match a completed source analysis.')
    if any(s.get('parent_job_id') == parent and s['status'] not in ('failed','cancelled','interrupted')
           for s in jobs.jobs.values()):
        raise RevisionConflict('A newer correction exists. Reload the latest server result.')
    return parent


def stage_parent(root, parent, destination, *, lease=None):
    parent_root = (Path(root) / parent).resolve()
    records = json.loads((parent_root / 'sources.json').read_text(encoding='utf-8'))
    destination.mkdir()
    staged = []
    for record in records:
        source = Path(record['path']).resolve()
        if not source.is_relative_to(parent_root / 'sources') or digest(source) != record['sha256']:
            raise ValueError('Retained source has changed or expired.')
        out = destination / source.relative_to(parent_root / 'sources')
        out.parent.mkdir(parents=True, exist_ok=True)
        mode = 'copy'
        if lease is not None:
            mode = lease.materialize(source, out, share=record.get('storage_mode') == 'hardlink')
        else:
            shutil.copyfile(source, out)
        if digest(out) != record['sha256']:
            raise ValueError('Retained source changed during staging.')
        staged.append(dict(record, path=str(out), storage_mode=mode))
    if not staged:
        raise ValueError('Retained sources are unavailable.')
    return staged


def calculate(request, records, output):
    import numpy as np
    from ..eagle_eye_alignment.service import load_image, validate_points
    from ..eagle_eye_alignment.geometry import measure_bilateral
    from ..eagle_eye_alignment.report import generate_report
    value = request['parameters']['correction']
    validate_correction(value)
    ref = request['series']['primary']
    record = next(r for r in records if r['sop_uid'] == ref['sop_uid'])
    image = load_image(record['path'], request['study_uid'], ref['series_uid'])
    if value['flipped']:
        image['pixels'] = np.ascontiguousarray(image['pixels'][:, ::-1])
    image.update(flipped=value['flipped'], spacing=tuple(value['spacing']), calibrated=value['calibrated'],
                 calibration_method='Operator-verified patient-plane scale' if value['calibrated'] else 'Unverified scale; lengths in pixels')
    validate_points(value['landmarks'], image['pixels'].shape)
    provenance = dict(parent_job_id=value['parent_job_id'], manually_edited=True,
                      acquisition_reviewed=value['acquisition_reviewed'], clinical_report_signed=False)
    result = generate_report(image, value['landmarks'], provenance, value['notes'], value['landmarks_reviewed'], root=output)
    result.update(landmarks=value['landmarks'], measurements=measure_bilateral(value['landmarks'], image['spacing'], calibrated=image['calibrated']),
                  parent_job_id=value['parent_job_id'], radiograph_binding=image['radiograph_binding'],
                  clinical_report_signed=False)
    return result
