"""Conservative 2D mask-to-endplate proposals, never anatomical confirmation."""
import numpy as np

from .geometry import CORNERS, vertebra


def validate_box(box, shape):
    box = np.asarray(box, dtype=float)
    h, w = shape
    if (box.shape != (4,) or not np.isfinite(box).all() or
            box[0] < 0 or box[1] < 0 or box[2] >= w or box[3] >= h or
            box[2]-box[0] < 12 or box[3]-box[1] < 12):
        raise ValueError('Draw a box around one visible vertebral body, at least 12 pixels wide and high.')
    if (box[2]-box[0])*(box[3]-box[1]) > 8_000_000:
        raise ValueError('The selected body region is too large. Select a single vertebra.')
    return box


def _fit_edge(x, y, thickness):
    keep = np.ones(len(x), dtype=bool)
    for _ in range(4):
        if keep.sum() < max(8, .7*len(x)):
            raise ValueError('The endplate boundary is irregular. Place its corners manually.')
        coefficients = np.polyfit(x[keep], y[keep], 1)
        residual = y - np.polyval(coefficients, x)
        mad = np.median(np.abs(residual[keep]-np.median(residual[keep])))
        keep = np.abs(residual) <= max(1.5, 3*1.4826*mad)
    error = float(np.sqrt(np.mean(residual[keep]**2)))
    if error > max(1.5, .06*thickness) or np.percentile(np.abs(residual), 90) > max(2., .12*thickness):
        raise ValueError('The mask does not define a straight endplate. Correct landmarks manually.')
    return coefficients, error


def propose_endplates(mask, origin=(0, 0)):
    """Fit upper/lower envelopes independently; retain wedging, reject ambiguity.

    The central 70% of the horizontal contour supplies each fit. Endpoints are
    line handles within that support, not a claim to anatomical corner detection.
    No minimum-area rectangle or whole-body principal axis substitutes for either
    endplate. Original image coordinates are returned; spacing is applied later.
    """
    import SimpleITK as sitk
    mask = np.asarray(mask)
    offset = np.asarray(origin, dtype=float)
    if (mask.ndim != 2 or mask.size > 16_000_000 or mask.dtype != np.bool_ or
            offset.shape != (2,) or not np.isfinite(offset).all()):
        raise ValueError('Expected a bounded binary mask and finite image origin.')
    if mask.sum() < 100:
        raise ValueError('The mask is empty or too small.')
    labels = sitk.GetArrayFromImage(sitk.ConnectedComponent(sitk.GetImageFromArray(mask.astype(np.uint8))))
    count = int(labels.max())
    sizes = np.bincount(labels.ravel()); sizes[0] = 0
    largest = int(sizes.argmax())
    if count > 1 and (sizes.sum()-sizes[largest]) > .02*sizes.sum():
        raise ValueError('The mask contains multiple components. Select one vertebral body.')
    body = labels == largest
    if any((body[0].any(), body[-1].any(), body[:, 0].any(), body[:, -1].any())):
        raise ValueError('The mask touches the crop border. Enlarge the body box.')
    filled = sitk.GetArrayFromImage(sitk.BinaryFillhole(sitk.GetImageFromArray(body.astype(np.uint8))))
    if (filled.sum()-body.sum()) > .02*body.sum():
        raise ValueError('The mask contains substantial holes. Refine the segmentation.')
    occupied = np.flatnonzero(body.any(axis=0))
    left, right = int(occupied[0]), int(occupied[-1])
    width = right-left
    if width < 16 or len(occupied) != width+1:
        raise ValueError('The body contour is too narrow or disconnected.')
    x = np.arange(left+int(np.ceil(.15*width)), right-int(np.ceil(.15*width))+1)
    top = np.argmax(body[:, x], axis=0)
    bottom = body.shape[0]-1-np.argmax(body[::-1, x], axis=0)
    thickness = float(np.median(bottom-top))
    if (body[:, x].sum(axis=0) < .95*(bottom-top+1)).any():
        raise ValueError('The mask has gaps between its upper and lower boundaries. Refine the segmentation.')
    if thickness < 8 or not .12 <= thickness/width <= 1.8:
        raise ValueError('The mask shape is unsuitable for a vertebral-body endplate proposal.')
    if (bottom-top < thickness*.3).any():
        raise ValueError('The body contour has a narrow bridge. Refine the segmentation.')
    upper, upper_error = _fit_edge(x, top, thickness)
    lower, lower_error = _fit_edge(x, bottom, thickness)
    endpoints = np.array([[x[0], np.polyval(upper, x[0])], [x[-1], np.polyval(upper, x[-1])],
                          [x[0], np.polyval(lower, x[0])], [x[-1], np.polyval(lower, x[-1])]]) + offset
    points = dict(zip(CORNERS, endpoints.tolist()))
    vertebra(points)
    return dict(points=points, method='Independent central contour endplate fits; reader review required',
                fit_rms_pixels=[upper_error, lower_error], anatomical_corners=False)
