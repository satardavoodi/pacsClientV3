"""Measurement-specific evidence and bounded candidate proposals."""
from copy import deepcopy
import hashlib
import json
import numpy as np
from .geometry import CORNERS, endplate_points


def required_points(points, spec):
    result = {}
    for level, plate in ((spec['upper'], 'superior'), (spec['lower'], spec.get('lower_endplate', 'inferior'))):
        values = points.get(level, {})
        endplate_points(values, plate)
        result.setdefault(level, {}).update({plate+'_'+side: values[plate+'_'+side] for side in ('left', 'right')})
    return result


def curve_evidence(view, spec):
    image = view['image']
    evidence = dict(points=required_points(view['points'], spec),
                    spec={k: spec.get(k) for k in ('name', 'upper', 'lower', 'lower_endplate')},
                    source=image['source_sha256'], identity=image['identity'], spacing=image['spacing'],
                    projection=image['projection'], acquisition=view.get('acquisition_confirmed'),
                    orientation=view.get('positive_image_right'))
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, allow_nan=False).encode()).hexdigest()


def curve_is_reviewed(view, spec):
    try:
        return spec.get('review_signature') == curve_evidence(view, spec)
    except (KeyError, ValueError, TypeError):
        return False


def predict_region(image, box, cancel, predictor, progress=None):
    """Owned worker path: crop pixels, then restore source coordinates and identity."""
    from ..eagle_eye_remote.settings import remote_required
    if remote_required():
        from ..eagle_eye_remote.routing import radiograph
        function = getattr(predictor, 'func', predictor)
        model = 'scoliovis' if getattr(function, '__name__', '') == 'predict_scoliovis' else 'isbi'
        return radiograph('total-spine', image, cancel, region=box, model=model)
    from .assist_service import image_binding
    report = progress or (lambda *_: None)
    report(0, 4, 'Preparing the selected spine region')
    h, w = image['pixels'].shape
    if box is None:
        raise ValueError('Select the spine region before requesting AI proposals.')
    values = np.asarray(box, dtype=float)
    if values.shape != (4,) or not np.isfinite(values).all():
        raise ValueError('Invalid spine region.')
    x0, y0 = np.floor(values[:2]).astype(int)
    x1, y1 = np.ceil(values[2:]).astype(int)
    if not (0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h) or min(x1-x0, y1-y0) < 32:
        raise ValueError('Select a spine region at least 32 pixels wide and high.')
    cropped = dict(image, pixels=np.ascontiguousarray(image['pixels'][y0:y1, x0:x1]))
    report(1, 4, 'Loading and running the vertebral model')
    result = deepcopy(predictor(cropped, cancel))
    if cancel.is_set():
        raise ValueError('Analysis cancelled.')
    report(2, 4, 'Validating landmarks and restoring image coordinates')
    valid = []
    for candidate in result.get('candidates', []):
        p = np.asarray(candidate.get('corners'), dtype=float)
        if p.shape != (4, 2) or not np.isfinite(p).all():
            continue
        if (p < 0).any() or (p[:, 0] >= x1-x0).any() or (p[:, 1] >= y1-y0).any():
            continue
        candidate['corners'] = (p + [x0, y0]).tolist()
        candidate['review_status'] = 'Needs anatomical review; confidence is not accuracy'
        valid.append(candidate)
    result.update(candidates=valid, binding=image_binding(image), region=[int(x0), int(y0), int(x1), int(y1)])
    report(3, 4, 'Preparing editable results')
    return result
