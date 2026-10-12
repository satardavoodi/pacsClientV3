"""B95 exact singleton-vectorized physical peak extraction. Research utility; not a trained detector.

Rows use (x_pixels, y_pixels, score). Spacing is (row_mm, column_mm).
Only threshold-qualified regional maxima enter plateau collapse and Euclidean NMS.
"""
import numpy as np
from scipy import ndimage


def extract_physical_peaks(score_map, *, threshold, spacing_yx_mm,
                           min_distance_mm, valid_mask=None, max_peaks=None):
    """Return float64 N by 3 array; an empty result has shape (0, 3).

    Flat regional maxima collapse with 8-connectivity to the pixel nearest their
    centroid in physical space (ties: row, then column). Subsequent NMS is ordered
    by descending score, then row and column. Distances equal to the minimum are
    allowed. max_peaks is an optional safety cap, never a minimum output quota.
    threshold is absolute and inclusive; a constant map above it emits one peak.
    """
    field = np.asarray(score_map, dtype=np.float64)
    if field.ndim != 2 or 0 in field.shape or not np.isfinite(field).all():
        raise ValueError('score_map must be a nonempty finite two-dimensional array')
    spacing = np.asarray(spacing_yx_mm, dtype=np.float64)
    if spacing.shape != (2,) or not np.isfinite(spacing).all() or (spacing <= 0).any():
        raise ValueError('spacing_yx_mm must contain two finite positive values')
    if not np.isfinite(threshold):
        raise ValueError('threshold must be finite')
    if not np.isfinite(min_distance_mm) or min_distance_mm < 0:
        raise ValueError('min_distance_mm must be finite and nonnegative')
    if max_peaks is not None and (isinstance(max_peaks, bool) or not isinstance(max_peaks, (int, np.integer)) or max_peaks < 0):
        raise ValueError('max_peaks must be a nonnegative integer or None')
    mask = np.ones(field.shape, dtype=bool) if valid_mask is None else np.asarray(valid_mask)
    if mask.shape != field.shape or mask.dtype != np.bool_:
        raise ValueError('valid_mask must be a boolean array matching score_map')
    empty = np.empty((0, 3), dtype=np.float64)
    if max_peaks == 0 or not mask.any():
        return empty
    masked = np.where(mask, field, -np.inf)
    maxima = mask & (field >= threshold) & (masked == ndimage.maximum_filter(masked, size=3, mode='constant', cval=-np.inf))
    labels, count = ndimage.label(maxima, structure=np.ones((3, 3), bool))
    # Single-pixel components need neither dilation nor centroid calculation.
    # Detect equal-valued nonmaximum neighbors in bulk, preserving shoulder rejection.
    sizes = np.bincount(labels.ravel(), minlength=count + 1)
    yy, xx = np.nonzero(maxima)
    single = sizes[labels[yy, xx]] == 1
    sy, sx = yy[single], xx[single]
    shoulder = np.zeros(len(sy), dtype=bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == 0 and dx == 0:
                continue
            ny, nx = sy + dy, sx + dx
            valid = (ny >= 0) & (ny < field.shape[0]) & (nx >= 0) & (nx < field.shape[1])
            i = np.flatnonzero(valid)
            vy, vx = ny[i], nx[i]
            shoulder[i] |= mask[vy, vx] & ~maxima[vy, vx] & (field[vy, vx] == field[sy[i], sx[i]])
    candidates = [(int(y), int(x), float(field[y, x])) for y, x in zip(sy[~shoulder], sx[~shoulder])]
    for label, region in enumerate(ndimage.find_objects(labels), 1):
        if sizes[label] == 1:
            continue
        yy, xx = np.where(labels[region] == label)
        yy = yy + region[0].start
        xx = xx + region[1].start
        # Adjacent maxima must have equal values; guard future algorithm changes.
        values = field[yy, xx]
        if not np.all(values == values[0]):
            raise RuntimeError('A regional-maximum plateau contains unequal scores')
        # A flat shoulder beside a higher point is not a regional maximum.
        # Local 3x3 equality alone leaves its interior falsely eligible.
        padded_region = (slice(max(0, region[0].start-1), min(field.shape[0], region[0].stop+1)),
                         slice(max(0, region[1].start-1), min(field.shape[1], region[1].stop+1)))
        component = labels[padded_region] == label
        border = ndimage.binary_dilation(component, structure=np.ones((3,3),bool)) & ~component
        shoulder = border & mask[padded_region] & (field[padded_region] == values[0]) & ~maxima[padded_region]
        if shoulder.any():
            continue
        d2 = ((yy - yy.mean()) * spacing[0]) ** 2 + ((xx - xx.mean()) * spacing[1]) ** 2
        representative = np.lexsort((xx, yy, d2))[0]
        candidates.append((int(yy[representative]), int(xx[representative]), float(values[0])))
    candidates.sort(key=lambda p: (-p[2], p[0], p[1]))
    kept = []
    # Spatial bins avoid quadratic scans on large native mammograms.
    bins = {}
    for y, x, score in candidates:
        py, px = y * spacing[0], x * spacing[1]
        if min_distance_mm > 0:
            key = (int(np.floor(py / min_distance_mm)), int(np.floor(px / min_distance_mm)))
            neighbors = (point for dy in (-1, 0, 1) for dx in (-1, 0, 1)
                         for point in bins.get((key[0] + dy, key[1] + dx), ()))
            if any((py - qy) ** 2 + (px - qx) ** 2 < min_distance_mm ** 2 for qy, qx in neighbors):
                continue
            bins.setdefault(key, []).append((py, px))
        kept.append((x, y, score))
        if max_peaks is not None and len(kept) >= max_peaks:
            break
    return np.asarray(kept, dtype=np.float64).reshape(-1, 3)
