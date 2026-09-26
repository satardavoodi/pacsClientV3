"""Bounded source references and label-only revisions; no client source paths."""
import hashlib
import json
import math
import re

MODULES = ('breast', 'bone-age', 'brain', 'brain-lesions', 'lumbar', 'alignment', 'total-spine')
MAX_REVIEW_REQUEST = 24 * 1024**2
PARAMETERS = {
    'breast': {'threshold'}, 'bone-age': {'sex'},
    'brain': {'profile', 'reference_id', 'correction'},
    'brain-lesions': {'primary_disease', 'clinical_note', 'fazekas_overall', 'correction', 'acquisition_mode'},
    'lumbar': set(), 'alignment': {'correction'},
    'total-spine': {'projection', 'region', 'model', 'level', 'correction'},
}


def uid(value):
    if not isinstance(value, str) or len(value) > 64 or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', value):
        raise ValueError('A valid DICOM identity is required.')
    return value


def validate(request):
    if not isinstance(request, dict) or set(request) != {'protocol', 'request_id', 'module', 'study_uid', 'series', 'parameters'}:
        raise ValueError('Unsupported analysis request fields.')
    if request['protocol'] != 1 or request['module'] not in MODULES:
        raise ValueError('Unsupported analysis protocol or module.')
    if not re.fullmatch('[a-f0-9]{32}', str(request['request_id'])):
        raise ValueError('Invalid request identity.')
    uid(request['study_uid'])
    series = request['series']
    if not isinstance(series, dict) or len(series) > 4 or set(series) - {'primary', 'secondary', 't1', 'flair'}:
        raise ValueError('Unsupported input roles.')
    for item in series.values():
        if not isinstance(item, dict) or set(item) - {'series_uid', 'sop_uid', 'expected_count'}:
            raise ValueError('Only DICOM references may be submitted.')
        uid(item.get('series_uid'))
        if item.get('sop_uid'):
            uid(item['sop_uid'])
        if type(item.get('expected_count')) is not int or not 1 <= item['expected_count'] <= 10000:
            raise ValueError('A counted source series is required.')
    module = request['module']
    allowed_roles = {'brain': {'t1', 'flair'}, 'brain-lesions': {'t1', 'flair'},
                     'total-spine': {'primary', 'secondary'} if isinstance(request['parameters'], dict) and 'correction' in request['parameters'] else {'primary'}}.get(module, {'primary'})
    if set(series) - allowed_roles:
        raise ValueError('The selected roles do not belong to this analysis.')
    required = {'brain': {'t1'}, 'brain-lesions': {'t1', 'flair'},
                'lumbar': {'primary'}, 'alignment': {'primary'}, 'total-spine': {'primary'}}.get(module, set())
    if not required.issubset(series):
        raise ValueError('Select the required source series.')
    if module in ('alignment', 'total-spine') and not series['primary'].get('sop_uid'):
        raise ValueError('Select an exact source instance.')
    if module == 'total-spine' and len({(x['series_uid'], x.get('sop_uid')) for x in series.values()}) != len(series):
        raise ValueError('Each spine projection requires a distinct source instance.')
    if module != 'total-spine' and len({x['series_uid'] for x in series.values()}) != len(series):
        raise ValueError('Input roles must reference distinct series.')
    params = request['parameters']
    if not isinstance(params, dict) or set(params) - PARAMETERS[module]:
        raise ValueError('Unsupported analysis parameters.')
    limit = MAX_REVIEW_REQUEST if module in ('brain', 'brain-lesions') and 'correction' in params else 65536 if module == 'total-spine' and 'correction' in params else 16384
    if len(json.dumps(request, allow_nan=False)) > limit:
        raise ValueError('Analysis request is too large.')
    if 'correction' in params:
        if set(params) != {'correction'}:
            raise ValueError('A correction cannot change inference parameters.')
        if module in ('brain', 'brain-lesions'):
            from .segmentation_review import validate as validate_mask
            validate_mask(params['correction'])
        elif module == 'total-spine':
            from .spine_review import validate as validate_spine
            validate_spine(params['correction'], series)
        else:
            from .reviews import validate_correction
            validate_correction(params['correction'])
        return request
    if module == 'breast' and not .05 <= float(params.get('threshold', .45)) <= .95:
        raise ValueError('Invalid detection threshold.')
    if module == 'alignment' and 'correction' in params:
        from .reviews import validate_correction
        validate_correction(params['correction'])
    if module == 'bone-age' and params.get('sex') not in (None, 'M', 'F', 'male', 'female'):
        raise ValueError('Invalid sex.')
    if module == 'brain' and (params.get('profile', 'standard') not in ('standard', 'robust')
                              or params.get('reference_id', 'volbrain') != 'volbrain'):
        raise ValueError('Unsupported brain analysis profile.')
    if module == 'total-spine':
        model = params.get('model', 'isbi')
        projections = ('coronal', 'lateral') if model == 'sam' else ('coronal',)
        if params.get('projection', 'coronal') not in projections or model not in ('isbi', 'scoliovis', 'sam'):
            raise ValueError('Unsupported spine model or projection.')
        if model == 'sam' and not re.fullmatch(r'(?:C[1-7]|T(?:[1-9]|1[0-2])|L[1-5])', str(params.get('level', ''))):
            raise ValueError('Choose a supported vertebral body for segmentation.')
        if model != 'sam' and 'level' in params:
            raise ValueError('A vertebral level only applies to body segmentation.')
        region = params.get('region')
        if not isinstance(region, list) or len(region) != 4 or not all(type(v) in (int, float) and math.isfinite(v) for v in region):
            raise ValueError('Select a finite spine region.')
    if module == 'brain-lesions':
        if params.get('acquisition_mode', '3d') not in ('2d', '3d'):
            raise ValueError('Unsupported lesion acquisition mode.')
        if params.get('primary_disease', 'other') not in ('other', 'ms', 'svd'):
            raise ValueError('Unsupported lesion reporting context.')
        if not isinstance(params.get('clinical_note', ''), str) or len(params.get('clinical_note', '')) > 2000:
            raise ValueError('Clinical note exceeds the limit.')
    return request


def fingerprint(request):
    return hashlib.sha256(json.dumps(request, sort_keys=True, allow_nan=False).encode()).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()
