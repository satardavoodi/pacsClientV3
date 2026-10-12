"""Versioned marrow input roles and conservative, editable sequence suggestions."""
import re

REQUIRED = frozenset({'primary', 'opposed', 't1', 't2'})
ROLES = ('primary', 'opposed', 't1', 't2', 'stir', 'multiecho', 'fat', 'water')


def require_roles(roles, version=2):
    roles = set(roles)
    required = REQUIRED if version == 2 else {'primary', 'fat', 'water', 'multiecho'}
    if required - roles:
        raise ValueError('Missing required marrow inputs: ' + ', '.join(sorted(required - roles)))
    if ('fat' in roles) != ('water' in roles):
        raise ValueError('Select both Dixon fat and water, or neither.')


def suggest(rows):
    """Only unambiguous sagittal metadata candidates; never guess between duplicates."""
    candidates = {role: [] for role in ROLES}
    for row in rows:
        meta = row.get('marrow_metadata', {})
        if not row.get('available') or not meta.get('sagittal'):
            continue
        text = re.sub(r'[^a-z0-9]+', ' ', str(meta.get('description', row.get('description', ''))).lower())
        tokens = set(text.split())
        role = None
        if 'stir' in tokens:
            role = 'stir'
        elif meta.get('echo_count', 0) >= 6:
            role = 'multiecho'
        elif 'dixon' in tokens or meta.get('dixon'):
            if tokens & {'opp', 'opposed', 'out', 'outphase'} or meta.get('component') == 'opposed':
                role = 'opposed'
            elif tokens & {'in', 'inphase'} or meta.get('component') == 'primary':
                role = 'primary'
            elif tokens & {'fat', 'f'} or meta.get('component') == 'fat':
                role = 'fat'
            elif tokens & {'water', 'w'} or meta.get('component') == 'water':
                role = 'water'
        elif not tokens & {'fs', 'fatsat', 'map', 'post', 'contrast', 'flair'}:
            if 't1' in tokens:
                role = 't1'
            elif 't2' in tokens:
                role = 't2'
        if role:
            candidates[role].append(row)
    return {role: items[0]['series_uid'] for role, items in candidates.items() if len(items) == 1}


def load_series(study_uid):
    """Runs in the existing client executor; no DICOM reads on the GUI thread."""
    from pathlib import Path
    import numpy as np
    import pydicom
    from .eagle_eye_brain.study_workflow import load_study_series
    rows = load_study_series(study_uid)
    for row in rows:
        if not row['available']:
            continue
        headers = []
        for path in sorted(Path(row['path']).iterdir()):
            if not path.is_file():
                continue
            try:
                d = pydicom.dcmread(path, stop_before_pixels=True)
                if str(d.get('StudyInstanceUID', '')) == study_uid and str(d.get('SeriesInstanceUID', '')) == row['series_uid']:
                    headers.append(d)
            except (OSError, ValueError, pydicom.errors.InvalidDicomError):
                continue
            if len(headers) >= 128:
                break
        if not headers:
            continue
        first = headers[0]
        orientation = np.asarray(first.get('ImageOrientationPatient', []), float)
        sagittal = orientation.size == 6 and abs(np.cross(orientation[:3], orientation[3:])[0]) > .9
        types = {str(v).upper() for v in first.get('ImageType', [])}
        component = next((role for role, names in [('opposed', {'OUT_PHASE', 'OPPOSED_PHASE'}),
                         ('primary', {'IN_PHASE'}), ('fat', {'FAT'}), ('water', {'WATER'})] if types & names), None)
        row['marrow_metadata'] = dict(sagittal=bool(sagittal), component=component, dixon=bool(component),
            description=' '.join(str(first.get(k, '')) for k in ('SeriesDescription', 'ProtocolName')),
            echo_count=len({float(d.EchoTime) for d in headers if d.get('EchoTime') is not None}))
    return rows
