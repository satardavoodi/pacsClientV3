"""Geometry in physical RAS millimetres; no Slicer, scene or GUI dependencies."""
import numpy as np


def segment_snapshot(binary, label, matrix, extent):
    """Detach just the selected label and account for a cropped VTK extent."""
    binary = np.asarray(binary)
    if binary.ndim != 3 or binary.size > 256 * 1024 * 1024:
        raise ValueError("Crop the source region before analyzing this large segment")
    affine = np.asarray(matrix, dtype=float).copy()
    if (affine.shape != (4, 4) or not np.isfinite(affine).all()
            or abs(np.linalg.det(affine[:3, :3])) < 1e-10):
        raise ValueError("Invalid segmentation geometry")
    if label <= 0:
        raise ValueError("Invalid segment label")
    mask = np.asarray(binary == label, dtype=np.uint8)
    affine[:3, 3] += affine[:3, :3] @ np.array(extent[::2])
    return mask, affine


def sample_path(points, step_mm=0.75):
    points = np.asarray(points, dtype=float)
    if points.ndim != 2 or points.shape[1] != 3 or len(points) < 2 or not np.isfinite(points).all():
        raise ValueError("Place at least two finite path points")
    if not np.isfinite(step_mm) or step_mm <= 0:
        raise ValueError("Path spacing must be positive")
    keep = np.r_[True, np.linalg.norm(np.diff(points, axis=0), axis=1) > 1e-6]
    points = points[keep]
    if len(points) < 2:
        raise ValueError("Path endpoints must be different")
    distance = np.r_[0., np.cumsum(np.linalg.norm(np.diff(points, axis=0), axis=1))]
    count = min(10000, max(2, int(np.ceil(distance[-1] / step_mm)) + 1))
    stations = np.linspace(0, distance[-1], count)
    return np.column_stack([np.interp(stations, distance, points[:, i]) for i in range(3)]), stations


def path_frames(points):
    """Parallel-transported orientation avoids arbitrary camera roll at bends."""
    points = np.asarray(points, dtype=float)
    tangents = np.gradient(points, axis=0)
    norms = np.linalg.norm(tangents, axis=1)
    if np.any(norms < 1e-8):
        raise ValueError("Path contains a reversal; refine the curve before navigation")
    tangents /= norms[:, None]
    ups = []
    up = np.eye(3)[np.argmin(np.abs(tangents[0]))]
    for tangent in tangents:
        up = up - np.dot(up, tangent) * tangent
        if np.linalg.norm(up) < 1e-6:
            up = np.eye(3)[np.argmin(np.abs(tangent))]
            up -= np.dot(up, tangent) * tangent
        up /= np.linalg.norm(up)
        ups.append(up.copy())
    return tangents, np.asarray(ups)


def diameter_stenosis(minimum, reference):
    if not np.isfinite([minimum, reference]).all() or reference <= 0 or minimum < 0:
        raise ValueError("Choose a positive reference diameter")
    return 100.0 * (1.0 - minimum / reference)
