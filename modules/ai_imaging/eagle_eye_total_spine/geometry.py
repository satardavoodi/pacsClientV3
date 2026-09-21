"""Deterministic projection geometry. Coordinates are source image x/y, y down."""
from __future__ import annotations

import math
import numpy as np

LEVELS = tuple([f'C{i}' for i in range(1, 8)] + [f'T{i}' for i in range(1, 13)] +
               [f'L{i}' for i in range(1, 6)] + ['S1'])
CORNERS = ('superior_left', 'superior_right', 'inferior_left', 'inferior_right')


def scale_xy(spacing):
    values = np.asarray(spacing, dtype=float)
    if values.shape != (2,) or not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError('Positive finite row and column spacing are required.')
    return values[::-1]


def point(value):
    result = np.asarray(value, dtype=float)
    if result.shape != (2,) or not np.isfinite(result).all():
        raise ValueError('A landmark must contain two finite coordinates.')
    return result


def vertebra(points, spacing=(1., 1.)):
    """Reject crossed, collapsed or upside-down corner assignments."""
    p = np.asarray([point(points[k]) for k in CORNERS]) * scale_xy(spacing)
    if p[0, 0] >= p[1, 0] or p[2, 0] >= p[3, 0]:
        raise ValueError('Endplate endpoints must be ordered image-left to image-right.')
    if p[0, 1] >= p[2, 1] or p[1, 1] >= p[3, 1]:
        raise ValueError('Superior corners must be above inferior corners.')
    polygon = p[[0, 1, 3, 2]]
    edges = np.roll(polygon, -1, axis=0) - polygon
    turns = edges[:, 0] * np.roll(edges, -1, axis=0)[:, 1] - edges[:, 1] * np.roll(edges, -1, axis=0)[:, 0]
    if (turns <= 1e-8).any():
        raise ValueError('Vertebral corners must form a non-degenerate convex outline.')
    return p


def endplate_points(points, endplate='superior', spacing=(1., 1.)):
    if endplate not in ('superior', 'inferior'):
        raise ValueError('Unknown endplate.')
    try:
        p = np.asarray([point(points[endplate+'_'+side]) for side in ('left', 'right')]) * scale_xy(spacing)
    except KeyError:
        raise ValueError('Place both endpoints of the selected '+endplate+' endplate.') from None
    if p[0, 0] >= p[1, 0]:
        raise ValueError('Endplate endpoints must be ordered image-left to image-right.')
    return p


def endplate_tilt(points, endplate='superior', spacing=(1., 1.)):
    p = endplate_points(points, endplate, spacing)
    d = p[1]-p[0]
    return math.degrees(math.atan2(d[1], d[0]))


def measure_curve(points, upper, lower, *, lower_endplate='inferior', spacing=(1., 1.)):
    """Use the upper superior and selected lower endplate; preserve angles >90."""
    if upper not in LEVELS or lower not in LEVELS or LEVELS.index(upper) >= LEVELS.index(lower):
        raise ValueError('Choose anatomically ordered, distinct end vertebrae.')
    a = endplate_points(points.get(upper, {}), 'superior', spacing)
    b = endplate_points(points.get(lower, {}), lower_endplate, spacing)
    if a[:, 1].mean() >= b[:, 1].mean():
        raise ValueError('End vertebrae are reversed in this upright image.')
    upper_tilt = endplate_tilt(points[upper], spacing=spacing)
    lower_tilt = endplate_tilt(points[lower], lower_endplate, spacing)
    return dict(upper=upper, lower=lower, upper_endplate='superior',
                lower_endplate=lower_endplate, cobb_deg=abs(upper_tilt-lower_tilt),
                upper_tilt_deg=upper_tilt, lower_tilt_deg=lower_tilt)


def suggest_apex(points, upper, lower, spacing=(1., 1.)):
    """Candidate only: greatest body-centroid distance from the end-centroid chord.

    This does not resolve an apical disc or replace the physician's apex selection.
    """
    if not all(set(CORNERS).issubset(points.get(level, {})) for level in (upper, lower)):
        return None
    measure_curve(points, upper, lower, spacing=spacing)
    try:
        a = vertebra(points[upper], spacing).mean(axis=0)
        b = vertebra(points[lower], spacing).mean(axis=0)
    except ValueError:
        return None
    d = b-a
    candidates = []
    for level in LEVELS[LEVELS.index(upper)+1:LEVELS.index(lower)]:
        if level in points and set(CORNERS).issubset(points[level]):
            try:
                c = vertebra(points[level], spacing).mean(axis=0)-a
            except ValueError:
                continue
            candidates.append((abs(float(d[0]*c[1]-d[1]*c[0])) / float(np.linalg.norm(d)), level))
    if not candidates or max(v for v, _ in candidates) < 1e-8:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def suggest_major_curve(points, spacing=(1., 1.)):
    """Maximum endplate-difference proposal, not a structural curve diagnosis.

    Search ordered, complete bodies. The physician can replace endpoints or
    record multiple curves. No Lenke/structural classification is inferred.
    """
    available = [level for level in LEVELS if level in points and set(CORNERS).issubset(points[level])]
    candidates = [measure_curve(points, a, b, spacing=spacing)
                  for i, a in enumerate(available) for b in available[i+1:]]
    if not candidates:
        raise ValueError('At least two complete vertebrae are required.')
    result = max(candidates, key=lambda candidate: candidate['cobb_deg'])
    return dict(name='Scoliosis Cobb', upper=result['upper'], lower=result['lower'],
                lower_endplate='inferior', apex='', convexity='not assessed',
                selection_source='Maximum endplate-difference proposal; verify curve endpoints')


def horizontal_offset(a, b, spacing=(1., 1.), *, calibrated=False, positive_image_right=True):
    """Horizontal plumb-line offset, never a perpendicular distance to a sloped line."""
    scale = scale_xy(spacing)
    value = float(point(a)[0]-point(b)[0])
    if calibrated:
        value *= scale[0]
    return {'value': value if positive_image_right else -value, 'unit': 'mm' if calibrated else 'px'}


def validate_landmarks(points, shape):
    height, width = shape
    if not isinstance(points, dict) or not set(points).issubset(LEVELS):
        raise ValueError('Unknown vertebral level.')
    for corners in points.values():
        if not isinstance(corners, dict) or not set(corners).issubset(CORNERS):
            raise ValueError('Unknown vertebral corner.')
        for value in corners.values():
            x, y = point(value)
            if not (0 <= x < width and 0 <= y < height):
                raise ValueError('A landmark lies outside the selected image.')
        if set(CORNERS).issubset(corners):
            vertebra(corners)


def rotation_record(level, grade, direction):
    """Nash-Moe is an ordinal reader assessment, never converted into degrees."""
    if level not in LEVELS or type(grade) is not int or grade not in range(5):
        raise ValueError('Select a vertebral level and Nash-Moe grade 0 to 4.')
    if direction not in ('none', 'right', 'left') or ((grade == 0) != (direction == 'none')):
        raise ValueError('Grade 0 requires no direction; grades 1 to 4 require right or left.')
    return dict(level=level, grade=grade, direction=direction, method='Nash-Moe',
                source='reader assessment', axial_degrees=None)
