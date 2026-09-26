"""Source-bound spine edits and reports on the existing revision job queue."""
from copy import deepcopy
import json
import math
from pathlib import Path
import re


def validate(value, series):
    if not isinstance(value, dict) or set(value) != {'parent_job_id', 'views', 'reviewed', 'notes'}:
        raise ValueError('Invalid spine correction fields.')
    if value['parent_job_id'] is not None and not re.fullmatch('[a-f0-9]{32}', str(value['parent_job_id'])):
        raise ValueError('Invalid parent spine analysis.')
    if type(value['reviewed']) is not bool or not isinstance(value['notes'], str) or len(value['notes']) > 2000:
        raise ValueError('Invalid spine report review.')
    views = value['views']
    if not isinstance(views, list) or not 1 <= len(views) <= 2 or len(views) != len(series):
        raise ValueError('Select one distinct image per spine projection.')
    keys = {'role', 'projection', 'spacing', 'calibrated', 'radiograph_binding', 'review_protocol',
            'points', 'markers', 'pedicles', 'curves', 'rotations', 'positive_image_right',
            'acquisition_confirmed', 'landmarks_reviewed'}
    roles, projections = set(), set()
    for view in views:
        if not isinstance(view, dict) or set(view) != keys:
            raise ValueError('Invalid spine review snapshot.')
        role = view['role']
        if role not in series or role in roles or not series[role].get('sop_uid') or series[role]['expected_count'] != 1:
            raise ValueError('Spine source selection is incomplete.')
        roles.add(role)
        if view['projection'] not in ('coronal', 'lateral') or view['projection'] in projections:
            raise ValueError('Spine projections must be distinct.')
        projections.add(view['projection'])
        if view['review_protocol'] != 'selected-endplates-v1':
            raise ValueError('Unsupported spine review protocol.')
        for key in ('calibrated', 'positive_image_right', 'acquisition_confirmed', 'landmarks_reviewed'):
            if type(view[key]) is not bool:
                raise ValueError('Invalid spine review state.')
        spacing = view['spacing']
        if not isinstance(spacing, list) or len(spacing) != 2 or any(type(n) not in (int, float) or not math.isfinite(n) or n <= 0 for n in spacing):
            raise ValueError('Invalid spine calibration.')
        binding = view['radiograph_binding']
        if not isinstance(binding, dict) or set(binding) != {'version', 'sha256'} or binding['version'] != 1 or not re.fullmatch('[a-f0-9]{64}', str(binding['sha256'])):
            raise ValueError('Spine source geometry is not verified.')
        if any(not isinstance(view[k], dict) for k in ('points', 'markers', 'pedicles')) or any(not isinstance(view[k], list) for k in ('curves', 'rotations')):
            raise ValueError('Invalid spine measurement structure.')
        if len(view['curves']) > 5 or len(view['rotations']) > 26:
            raise ValueError('Too many spine measurements.')


def submit(views, study_uid, reviewed, notes, *, parent=None, cancel=None):
    from PacsClient.utils.data_paths import AI_DIR
    from .client import Client
    from ..eagle_eye_total_spine.measurements import validate_report_views
    from ..eagle_eye_total_spine.review_workflow import curve_is_reviewed
    validate_report_views(views, study_uid, reviewed=reviewed)
    series, snapshots = {}, []
    for index, view in enumerate(views):
        role = 'primary' if index == 0 else 'secondary'
        image = view['image']; identity = image['identity']
        series[role] = {k: identity[k] for k in ('series_uid', 'sop_uid')}
        series[role]['expected_count'] = 1
        snapshot = {k: deepcopy(v) for k, v in view.items() if k not in ('image', 'provenance')}
        snapshot.update(role=role, projection=image['projection'], spacing=list(image['spacing']),
            calibrated=bool(image['calibrated']), radiograph_binding=image['radiograph_binding'])
        for original, spec in zip(view['curves'], snapshot['curves']):
            spec.pop('review_signature', None)
            spec['endplates_reviewed'] = curve_is_reviewed(view, original)
        snapshots.append(snapshot)
    correction = dict(parent_job_id=parent, views=snapshots, reviewed=bool(reviewed), notes=notes)
    validate(correction, series)
    client = Client()
    if 'total-spine' not in client.json('/v1/capabilities').get('correction_modules', []):
        raise ValueError('Update the Eagle Eye server to support spine corrections.')
    return client.analyze('total-spine', study_uid, series, {'correction': correction},
                          Path(AI_DIR) / 'eagle_eye', cancel=cancel)


def calculate(request, records, output):
    from ..eagle_eye_total_spine.service import load_view
    from ..eagle_eye_total_spine.geometry import validate_landmarks
    from ..eagle_eye_total_spine.measurements import validate_report_views
    from ..eagle_eye_total_spine.review_workflow import curve_evidence
    from ..eagle_eye_total_spine.report import generate_report
    value = request['parameters']['correction']; validate(value, request['series'])
    views = []
    for snapshot in value['views']:
        ref = request['series'][snapshot['role']]
        record = next(r for r in records if r['sop_uid'] == ref['sop_uid'] and r['series_uid'] == ref['series_uid'])
        image = load_view(record['path'], request['study_uid'], ref['series_uid'], snapshot['projection'])
        if image['radiograph_binding'] != snapshot['radiograph_binding']:
            raise ValueError('Spine geometry differs from the displayed source.')
        image.update(spacing=tuple(snapshot['spacing']), calibrated=snapshot['calibrated'],
            calibration_method='Reader-verified patient-plane scale' if snapshot['calibrated'] else 'Unverified scale / pixel aspect')
        view = {k: deepcopy(v) for k, v in snapshot.items() if k not in ('role', 'projection', 'spacing', 'calibrated', 'radiograph_binding')}
        view['image'] = image
        view['provenance'] = dict(source='Remote manual correction', parent_job_id=value['parent_job_id'])
        validate_landmarks(view['points'], image['pixels'].shape)
        for spec in view['curves']:
            confirmation = spec.pop('endplates_reviewed', False)
            if type(confirmation) is not bool:
                raise ValueError('Invalid endplate review state.')
            spec.pop('review_signature', None)
            if confirmation:
                spec['review_signature'] = curve_evidence(view, spec)
        views.append(view)
    measurements = validate_report_views(views, request['study_uid'], reviewed=value['reviewed'])
    result = generate_report(views, request['study_uid'], value['reviewed'], value['notes'], root=output)
    result.update(measurements=measurements, parent_job_id=value['parent_job_id'],
                  clinical_report_signed=False, reviewed=value['reviewed'])
    return result
