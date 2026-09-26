"""Semantic evidence for equivalent DICOM encodings of one radiograph."""
import hashlib
import json

import numpy as np


def fingerprint(ds, raw, pixels, valid, spacing, calibrated, method):
    """Run in the existing image-loading worker; never transmit source pixels."""
    geometry = {}
    for key in ('ImageOrientationPatient', 'ImagePositionPatient', 'PatientOrientation',
                'ViewPosition', 'Laterality', 'ImageLaterality', 'FrameOfReferenceUID',
                'PixelSpacingCalibrationType', 'PixelSpacingCalibrationDescription'):
        value = ds.get(key)
        geometry[key] = ([str(v) for v in value] if value is not None and
                         not isinstance(value, str) and hasattr(value, '__iter__')
                         else str(value) if value is not None else None)
    evidence = dict(version=1, shape=list(raw.shape), spacing=list(spacing),
                    calibrated=calibrated, calibration_method=method, geometry=geometry)
    h = hashlib.sha256(json.dumps(evidence, sort_keys=True, allow_nan=False).encode())
    for array in (raw, pixels, valid):
        array = np.ascontiguousarray(array, dtype=array.dtype.newbyteorder('<'))
        h.update(array.dtype.str.encode())
        h.update(memoryview(array).cast('B'))
    return dict(version=1, sha256=h.hexdigest())


def bind_result(result, image, module):
    """Verify server provenance, then map equivalent geometry to the local review."""
    bindings = result.get('source_binding', [])
    identity = image['identity']
    if len(bindings) != 1 or any(bindings[0].get(k) != identity[k]
                               for k in ('study_uid', 'series_uid', 'sop_uid')):
        raise ValueError('Server result belongs to another source image.')
    source = bindings[0]
    if source.get('sha256') != image['source_sha256']:
        local = image.get('radiograph_binding')
        if (not isinstance(local, dict) or local.get('version') != 1
                or not isinstance(local.get('sha256'), str) or len(local['sha256']) != 64
                or result.get('radiograph_binding') != local):
            raise ValueError('Server image differs from the displayed source. Reload the original study.')
    if module == 'total-spine':
        from ..eagle_eye_total_spine.assist_service import image_binding
        expected = image_binding(image)
        remote = dict(expected, source_sha256=source['sha256'])
        if result.get('binding') != remote:
            raise ValueError('Server spine geometry does not match the selected image.')
        # Preserve source_binding as immutable server provenance. Only the review
        # binding is translated after proof of equivalent inputs and geometry.
        result['binding'] = expected
    return result
