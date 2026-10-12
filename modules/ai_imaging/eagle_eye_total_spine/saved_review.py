"""Worker-only recovery of existing, source-bound spine results; no inference."""
from copy import deepcopy
import numpy as np


def prepare(result, study_uid):
    from ..eagle_eye_brain.saved_results import _same_study
    from ..eagle_eye_remote.radiograph_binding import bind_result
    from . import service
    from .geometry import CORNERS, validate_landmarks
    from .measurements import measure_view
    import pydicom

    if result.get('server_module') != 'total-spine' or not _same_study(result, study_uid):
        raise ValueError('Saved spine result belongs to another examination.')
    result = deepcopy(result)
    if not isinstance(result.get('notes', ''), str) or len(result.get('notes', '')) > 2000:
        raise ValueError('Invalid saved spine notes.')
    snapshots = result.get('review_views')
    detection = snapshots is None
    if detection:
        binding = result.get('binding') or {}
        snapshots = [dict(image=dict(identity=binding, projection=binding.get('projection')),
                          candidates=result.get('candidates'), region=result.get('region'))]
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 2:
        raise ValueError('Saved spine review data is unavailable.')
    sources = result.get('source_binding')
    if not isinstance(sources, list) or len(sources) != len(snapshots):
        raise ValueError('Saved source evidence is incomplete.')
    rows = service.study_images(study_uid)
    views = []
    for snapshot in snapshots:
        metadata = snapshot.get('image') or {}
        identity = metadata.get('identity') or {}
        projection = metadata.get('projection')
        if identity.get('study_uid') != study_uid or projection not in ('coronal', 'lateral'):
            raise ValueError('Saved spine projection identity is invalid.')
        matches = [s for s in sources if all(s.get(k) == identity.get(k)
                   for k in ('study_uid', 'series_uid', 'sop_uid'))]
        if len(matches) != 1 or any(v['image']['projection'] == projection for v in views):
            raise ValueError('Saved spine sources are ambiguous.')
        image = None
        for row in rows:
            if row['series_uid'] != identity.get('series_uid'):
                continue
            ds = pydicom.dcmread(row['path'], stop_before_pixels=True)
            if str(ds.get('SOPInstanceUID', '')) == identity.get('sop_uid'):
                image = service.load_view(row['path'], study_uid, row['series_uid'], projection)
                break
        if image is None:
            raise ValueError('Saved spine source image is not available locally. Load the original series and reopen the study.')
        if detection:
            bind_result(result, image, 'total-spine')
        elif (matches[0].get('sha256') != image['source_sha256']
              and (not image.get('radiograph_binding')
                   or metadata.get('radiograph_binding') != image['radiograph_binding'])):
            raise ValueError('Saved spine source pixels or geometry changed.')
        state = dict(image=image, points=deepcopy(snapshot.get('points', {})),
                     markers=deepcopy(snapshot.get('markers', {})),
                     pedicles=deepcopy(snapshot.get('pedicles', {})),
                     curves=deepcopy(snapshot.get('curves', [])),
                     rotations=deepcopy(snapshot.get('rotations', [])),
                     provenance=deepcopy(snapshot.get('provenance', {})),
                     positive_image_right=snapshot.get('positive_image_right', True),
                     acquisition_confirmed=bool(snapshot.get('acquisition_confirmed', False)),
                     landmarks_reviewed=bool(snapshot.get('landmarks_reviewed', False)),
                     candidates=deepcopy(snapshot.get('candidates', [])), region=snapshot.get('region'))
        if (any(not isinstance(state[k], dict) for k in ('points', 'markers', 'pedicles', 'provenance'))
                or not isinstance(state['curves'], list) or len(state['curves']) > 5
                or not isinstance(state['rotations'], list) or len(state['rotations']) > 26):
            raise ValueError('Invalid saved spine review structure.')
        if detection:
            if not isinstance(state['candidates'], list) or len(state['candidates']) > 100:
                raise ValueError('Invalid saved vertebral candidates.')
            for candidate in state['candidates']:
                corners = np.asarray(candidate.get('corners'), dtype=float)
                if corners.shape != (4, 2):
                    raise ValueError('Invalid saved vertebral corners.')
                validate_landmarks({'L1': dict(zip(CORNERS, corners.tolist()))}, image['pixels'].shape)
            box = np.asarray(state['region'], dtype=float)
            h, w = image['pixels'].shape
            if (box.shape != (4,) or not np.isfinite(box).all()
                    or not (0 <= box[0] < box[2] <= w and 0 <= box[1] < box[3] <= h)):
                raise ValueError('Invalid saved spine region.')
        else:
            # Restore reader calibration only after proving source equivalence.
            spacing = metadata.get('spacing', image['spacing'])
            image = dict(image, spacing=tuple(spacing), calibrated=bool(metadata.get('calibrated', False)),
                         calibration_method=metadata.get('calibration_method', image.get('calibration_method')))
            state['image'] = image
            validate_landmarks(state['points'], image['pixels'].shape)
            measure_view(state)
            from .review_workflow import curve_is_reviewed
            if any(not curve_is_reviewed(state, curve) for curve in state['curves']):
                state['landmarks_reviewed'] = False
        views.append(state)
    return dict(views=views, notes=result.get('notes', ''),
                report_result=result if not detection else None,
                provenance=result, parent_job_id=result.get('server_job_id'))
