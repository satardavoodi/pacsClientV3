"""Explicit coronal reference observations; candidates are never diagnoses."""
import numpy as np
from .geometry import LEVELS, CORNERS, vertebra, validate_landmarks, horizontal_offset


def body_centers(view):
    bodies = {}
    for level, points in view['points'].items():
        if level not in LEVELS or not set(CORNERS).issubset(points):
            continue
        try:
            validate_landmarks({level: points}, view['image']['pixels'].shape)
            bodies[level] = vertebra(points)
        except (ValueError, KeyError):
            continue
    return bodies


def coronal_assessment(view, spec):
    bodies = body_centers(view)
    selected = {}
    for key in ('stable', 'neutral', 'last_touched'):
        level = spec.get(key, '')
        if level and (level not in LEVELS or not level.startswith(('T', 'L'))):
            raise ValueError('Choose a thoracic or lumbar '+key.replace('_', ' ')+' vertebra.')
        selected[key] = level or None
    result = dict(reader=selected, apex_csvl_candidate=None, apex_csvl_offset=None,
                  stable_candidate=None, neutral_candidate=None, last_touched_candidate=None,
                  touched_levels=[], source='Geometry proposals from available numbered bodies; reader review required',
                  coverage='Only supplied body outlines are evaluated; missing levels can change proposals')
    sacral = view.get('markers', {}).get('Sacral center')
    lo, hi = LEVELS.index(spec['upper']), LEVELS.index(spec['lower'])
    if sacral is not None:
        if any(float(p[:, 1].mean()) >= sacral[1] for p in bodies.values()):
            raise ValueError('The sacral reference must be below the measured vertebral bodies.')
        x = float(sacral[0])
        internal = [k for k in LEVELS[lo+1:hi] if k in bodies]
        if internal:
            apex = max(internal, key=lambda k: abs(float(bodies[k][:, 0].mean())-x))
            result['apex_csvl_candidate'] = apex
            result['apex_csvl_offset'] = horizontal_offset(bodies[apex].mean(0), sacral,
                view['image']['spacing'], calibrated=view['image']['calibrated'],
                positive_image_right=view.get('positive_image_right', True))
        # LTV convention: most cephalad thoracolumbar/lumbar body touched by CSVL.
        touched = [k for k in LEVELS if k in bodies and k in ('T11', 'T12', 'L1', 'L2', 'L3', 'L4', 'L5')
                   and bodies[k][:, 0].min() <= x <= bodies[k][:, 0].max()]
        result['touched_levels'] = touched
        result['last_touched_candidate'] = touched[0] if touched else None
        distal = [k for k in LEVELS[hi:] if k in bodies and k.startswith(('T', 'L'))
                  and bodies[k][:, 0].min() <= x <= bodies[k][:, 0].max()]
        if distal:
            result['stable_candidate'] = min(distal, key=lambda k:
                abs(float(bodies[k][:, 0].mean())-x)/float(np.ptp(bodies[k][:, 0])))
    apex = spec.get('apex', '').split('/')[0] or result['apex_csvl_candidate']
    if apex in LEVELS:
        zero = {r['level'] for r in view.get('rotations', []) if r['grade'] == 0 and r['direction'] == 'none'}
        result['neutral_candidate'] = next((k for k in LEVELS[LEVELS.index(apex)+1:] if k in zero), None)
    return result
