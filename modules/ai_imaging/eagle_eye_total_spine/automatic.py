"""Unnumbered geometric proposals; never assigns clinical levels or review state."""
from .geometry import CORNERS, vertebra, endplate_tilt


def candidate_pair(candidates, spacing):
    valid = []
    for index, candidate in enumerate(candidates):
        try:
            points = dict(zip(CORNERS, candidate['corners']))
            body = vertebra(points, spacing)
            valid.append((float(body[:, 1].mean()), index,
                          endplate_tilt(points, 'superior', spacing),
                          endplate_tilt(points, 'inferior', spacing)))
        except (KeyError, ValueError, TypeError):
            continue
    valid.sort()
    choices = [dict(upper=a[1], lower=b[1], degrees=abs(a[2]-b[3]))
               for i, a in enumerate(valid) for b in valid[i+1:] if a[0] < b[0]]
    return max(choices, key=lambda pair: pair['degrees']) if choices else None
