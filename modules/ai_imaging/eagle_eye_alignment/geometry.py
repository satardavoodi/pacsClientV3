"""Projection-space alignment measurements. No Qt, VTK, model or I/O dependencies."""
from __future__ import annotations

import math
import numpy as np

LANDMARKS = ('hip', 'knee', 'femur_lateral', 'femur_medial',
             'tibia_lateral', 'tibia_medial', 'ankle_lateral', 'ankle_medial')
MEASUREMENT_LABELS = dict(hka_deg='HKA',mldfa_deg='mLDFA',mpta_deg='MPTA',jlca_deg='JLCA',
                          ldta_deg='LDTA',ahka_deg='aHKA',mad='MAD',femur_length='Femoral length',
                          tibia_length='Tibial length',limb_length='Hip-to-ankle length')


def angle(a, b):
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    if norm < 1e-8:
        raise ValueError('Coincident landmarks: correct the points before measuring.')
    return math.degrees(math.acos(float(np.clip(np.dot(a, b) / norm, -1, 1))))


def measure_leg(points, side, spacing=(1.0, 1.0), *, calibrated=False):
    """Spacing is (row, column). HKA: negative varus, positive valgus.

    SGR supplies a shared knee center for both mechanical axes. Bone lengths
    instead end at their own joint-line midpoints. MAD is positive medially.
    """
    if side not in ('R', 'L'):
        raise ValueError('A verified anatomical side is required.')
    scale = np.asarray((spacing[1], spacing[0]), dtype=float)
    if not np.isfinite(scale).all() or (scale <= 0).any():
        raise ValueError('Invalid image spacing.')
    p = {key: np.asarray(points[key], dtype=float) * scale for key in LANDMARKS}
    if any(v.shape != (2,) or not np.isfinite(v).all() for v in p.values()):
        raise ValueError('Landmarks must have finite image coordinates.')
    h, k = p['hip'], p['knee']
    a = (p['ankle_lateral'] + p['ankle_medial']) / 2
    f = p['femur_lateral'] - p['femur_medial']
    t = p['tibia_medial'] - p['tibia_lateral']
    distal = p['ankle_lateral'] - p['ankle_medial']
    if not h[1] < k[1] < a[1]:
        raise ValueError('Check hip, knee and ankle order: the image must be upright.')
    medial = 1 if side == 'R' else -1
    if medial * t[0] <= 0 or medial * f[0] >= 0 or medial * distal[0] >= 0:
        raise ValueError('Check medial/lateral landmarks and image orientation.')
    u, v = k - h, a - k
    hka = medial * math.degrees(math.atan2(float(u[0]*v[1]-u[1]*v[0]), float(np.dot(u, v))))
    mldfa, mpta = angle(h-k, f), angle(a-k, t)
    jlca = angle(f, -t)
    jlca = min(jlca, 180-jlca)
    axis = a-h
    mad = medial * float(axis[0]*(k-h)[1]-axis[1]*(k-h)[0]) / float(np.linalg.norm(axis))
    femur_end = (p['femur_medial']+p['femur_lateral'])/2
    tibia_start = (p['tibia_medial']+p['tibia_lateral'])/2
    result = dict(hka_deg=hka, mldfa_deg=mldfa, mpta_deg=mpta,
                jlca_deg=jlca, ldta_deg=angle(k-a, distal),
                ahka_deg=mpta-mldfa, mad=mad,
                femur_length=float(np.linalg.norm(h-femur_end)),
                tibia_length=float(np.linalg.norm(a-tibia_start)),
                limb_length=float(np.linalg.norm(h-a)),
                length_unit='mm' if calibrated else 'px')
    if not calibrated and not np.array_equal(scale, (1., 1.)):
        raw = measure_leg(points, side)
        for key in ('mad', 'femur_length', 'tibia_length', 'limb_length'):
            result[key] = raw[key]
    return result


def measure_bilateral(points, spacing=(1., 1.), *, calibrated=False):
    # Unknown calibration still permits angles using the known pixel aspect.
    # Lengths remain native pixels until a patient-plane scale is verified.
    result = {s: measure_leg(points[s], s, spacing, calibrated=calibrated) for s in ('R', 'L')}
    result['lld'] = result['R']['limb_length'] - result['L']['limb_length']
    # A common absolute scale cancels; retain pixel aspect even when lengths
    # are reported in raw pixels. This describes projected hip-to-ankle length.
    scale = np.asarray((spacing[1], spacing[0]), dtype=float)
    lengths = {}
    for side in ('R', 'L'):
        p = points[side]
        ankle = (np.asarray(p['ankle_lateral']) + p['ankle_medial']) / 2
        lengths[side] = float(np.linalg.norm((ankle - p['hip']) * scale))
    difference = lengths['R'] - lengths['L']
    result['lld_percent'] = 100 * abs(difference) / max(lengths.values())
    result['shorter_side'] = ('equal' if math.isclose(lengths['R'], lengths['L'], rel_tol=1e-12)
                              else 'R' if difference < 0 else 'L')
    result['lld_percent_definition'] = '100 * abs(R - L) / max(R, L); pixel-aspect-corrected projected hip-to-ankle lengths'
    return result
