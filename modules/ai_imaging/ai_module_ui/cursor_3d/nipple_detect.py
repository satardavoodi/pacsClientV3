"""
Nipple Position Detection for Mammography Images.

Detects the nipple (anterior-most point of breast tissue) from DICOM pixel data
or estimates it from anatomical conventions when pixel data is unavailable.

The nipple position is critical for the 3D cursor system because it serves as
the anatomical anchor point from which lesion depths are measured.
"""

from __future__ import annotations

import os
from typing import Optional, Tuple

from .geometry import (
    ChestWallOrientation,
    ImageGeometry,
    NipplePosition,
    PixelSpacing,
)


def detect_nipple_position(
    dicom_path: Optional[str],
    laterality: str,
    view_position: str,
    image_geom: ImageGeometry,
    lesion_boxes_px: Optional[list] = None,
) -> NipplePosition:
    """
    Detect or estimate the nipple position for a mammogram.

    Strategy:
        1. If DICOM pixel data is available, detect nipple from image intensity.
        2. Otherwise, estimate from anatomical conventions and lesion positions.

    Args:
        dicom_path: Path to the DICOM file (may be None or invalid).
        laterality: 'R' or 'L'.
        view_position: 'CC' or 'MLO'.
        image_geom: Image geometry with pixel spacing.
        lesion_boxes_px: Optional list of lesion boxes [[x1,y1,x2,y2], ...] in pixels.

    Returns:
        NipplePosition with coordinates in both pixels and mm.
    """
    # Attempt detection from DICOM pixel data
    if dicom_path and os.path.isfile(str(dicom_path)):
        result = _detect_from_dicom_pixels(str(dicom_path), laterality, image_geom, view_position)
        if result is not None:
            return result

    # Fallback: estimate from anatomical conventions
    return _estimate_from_anatomy(laterality, view_position, image_geom, lesion_boxes_px)


def _detect_from_dicom_pixels(
    dicom_path: str,
    laterality: str,
    image_geom: ImageGeometry,
    view_position: str = 'CC',
) -> Optional[NipplePosition]:
    """
    Detect nipple position from DICOM pixel data.

    Algorithm:
        1. Read pixel data and normalize (handle MONOCHROME1 inversion).
        2. Build a binary breast mask (breast tissue vs background/air).
        3. Determine which side is the chest wall (using laterality + mask shape).
        4. Find the most anterior protruding point of the breast contour.
           - CC: the tissue point furthest from chest wall (at ~vertical center).
           - MLO: the tissue point furthest from chest wall (typically lower half).
    """
    try:
        import numpy as np
        import pydicom

        # Handle directory paths (pick first .dcm file)
        actual_path = dicom_path
        if os.path.isdir(actual_path):
            dcm_files = [f for f in os.listdir(actual_path) if f.lower().endswith('.dcm')]
            if not dcm_files:
                return None
            actual_path = os.path.join(actual_path, dcm_files[0])

        ds = pydicom.dcmread(actual_path, force=True)
        pixel_array = ds.pixel_array

        if pixel_array is None or pixel_array.size == 0:
            return None

        img = pixel_array.astype(np.float64)
        h, w = img.shape[:2]

        if img.max() == img.min():
            return None

        # ── Step 1: Handle MONOCHROME1 inversion ──
        # MONOCHROME1: high values = dark (background), low values = bright (tissue)
        # MONOCHROME2: high values = bright (tissue), low values = dark (background)
        # We need: high = tissue, low = background
        photometric = getattr(ds, 'PhotometricInterpretation', 'MONOCHROME2')
        if 'MONOCHROME1' in str(photometric).upper():
            img = img.max() - img  # invert

        # Normalize to [0, 1]
        img_min = img.min()
        img_max = img.max()
        if img_max - img_min < 1:
            return None
        img_norm = (img - img_min) / (img_max - img_min)

        # ── Step 2: Build binary breast mask ──
        # The breast is the bright region; background is dark (near zero).
        # Use a low threshold to separate breast from air.
        # Try adaptive threshold: use histogram to find the valley between
        # background peak and tissue peak.
        breast_mask = _build_breast_mask(img_norm, h, w)

        if breast_mask is None or breast_mask.sum() < (h * w * 0.05):
            return None  # Not enough tissue found

        # ── Step 3: Determine chest wall side ──
        # Standard mammography display:
        #   R breast: chest wall on RIGHT edge, anterior (nipple) on LEFT
        #   L breast: chest wall on LEFT edge, anterior (nipple) on RIGHT
        # Verify with the mask: the chest wall side has tissue touching the edge.
        chest_wall_on_right = (laterality == 'R')

        # Confirm with image data: the side where breast mask extends to the edge
        left_edge_tissue = breast_mask[:, :5].sum()
        right_edge_tissue = breast_mask[:, -5:].sum()

        if left_edge_tissue > right_edge_tissue * 2:
            chest_wall_on_right = False  # tissue touching left edge = chest wall on left
        elif right_edge_tissue > left_edge_tissue * 2:
            chest_wall_on_right = True  # tissue touching right edge = chest wall on right

        # ── Step 4: Find the most anterior protruding point ──
        if view_position == 'MLO':
            nipple_x, nipple_y = _find_nipple_from_mask_mlo(
                breast_mask, h, w, chest_wall_on_right
            )
        else:
            nipple_x, nipple_y = _find_nipple_from_mask_cc(
                breast_mask, h, w, chest_wall_on_right
            )

        if nipple_x is None:
            return None

        print(f"[3D-Cursor][NIPPLE] view={view_position} lat={laterality} "
              f"chest_wall_right={chest_wall_on_right} "
              f"nipple_px=({nipple_x}, {nipple_y}) "
              f"img_size=({w}x{h}) "
              f"relative_y={nipple_y/h:.2f}")

        return NipplePosition.from_pixels(
            x_px=float(nipple_x),
            y_px=float(nipple_y),
            spacing=image_geom.pixel_spacing,
            detected=True,
        )

    except Exception as exc:
        print(f"[3D-Cursor][NIPPLE] FAILED detection: {exc}")
        return None


def _build_breast_mask(img_norm, h: int, w: int):
    """
    Build a binary breast mask from a normalized [0,1] mammogram.

    Uses a percentile-based threshold that works reliably across different
    mammogram systems and exposure levels.
    """
    import numpy as np

    # The background (air) is typically a large portion of the image at very low values.
    # Use a threshold that separates background from tissue.
    # Strategy: find the threshold where ~20-40% of pixels are above it (breast area).

    # Compute histogram
    flat = img_norm.ravel()

    # Try percentile-based: the background peak is typically below the 30th percentile
    # The tissue starts above that.
    p10 = np.percentile(flat, 10)
    p30 = np.percentile(flat, 30)
    p50 = np.percentile(flat, 50)

    # If most of the image is dark (background), use a low threshold
    if p50 < 0.15:
        # Image is mostly background — threshold at ~5-10% of max
        threshold = 0.05
    elif p30 < 0.10:
        # Background is very dark, tissue starts above ~10%
        threshold = 0.08
    else:
        # Mixed — use Otsu-like: midpoint between background and tissue
        threshold = max(0.03, p10 + (p30 - p10) * 0.5)

    mask = img_norm > threshold

    # Clean up: remove small isolated pixels (noise)
    # Simple morphological opening via erosion + dilation
    try:
        from scipy import ndimage
        mask = ndimage.binary_erosion(mask, iterations=2)
        mask = ndimage.binary_dilation(mask, iterations=2)
    except ImportError:
        # Without scipy, do a simple row/column filter
        # Remove rows/columns with fewer than 10% tissue pixels
        row_tissue = mask.sum(axis=1)
        col_tissue = mask.sum(axis=0)
        min_row = h * 0.03
        min_col = w * 0.03
        for y in range(h):
            if row_tissue[y] < min_row:
                mask[y, :] = False
        for x in range(w):
            if col_tissue[x] < min_col:
                mask[:, x] = False

    return mask


def _find_nipple_from_mask_cc(
    mask, h: int, w: int, chest_wall_on_right: bool
) -> Tuple[Optional[int], Optional[int]]:
    """
    CC view: find the most anterior point of the breast contour.

    The nipple is the point on the breast boundary that is FURTHEST from
    the chest wall edge. In CC view, this is typically near the vertical
    center of the breast tissue.
    """
    import numpy as np

    # For each row, find the anterior extent (furthest tissue from chest wall)
    anterior_x = np.full(h, -1, dtype=np.int32)

    if chest_wall_on_right:
        # Anterior side = LEFT → find leftmost tissue pixel per row
        for y in range(h):
            tissue_cols = np.where(mask[y, :])[0]
            if len(tissue_cols) > 0:
                anterior_x[y] = tissue_cols[0]  # leftmost = most anterior
    else:
        # Anterior side = RIGHT → find rightmost tissue pixel per row
        for y in range(h):
            tissue_cols = np.where(mask[y, :])[0]
            if len(tissue_cols) > 0:
                anterior_x[y] = tissue_cols[-1]  # rightmost = most anterior

    # Find valid rows (where tissue exists)
    valid = anterior_x >= 0
    if not valid.any():
        return None, None

    # The "most anterior" row = the one where tissue extends furthest from chest wall
    if chest_wall_on_right:
        # Furthest from right = MINIMUM x value (leftmost)
        # But only consider the central 60% of the breast vertically
        tissue_rows = np.where(valid)[0]
        y_min_tissue = tissue_rows[0]
        y_max_tissue = tissue_rows[-1]
        tissue_height = y_max_tissue - y_min_tissue
        y_search_start = y_min_tissue + int(tissue_height * 0.20)
        y_search_end = y_min_tissue + int(tissue_height * 0.80)

        search_mask = np.zeros(h, dtype=bool)
        search_mask[y_search_start:y_search_end] = True
        combined = valid & search_mask

        if not combined.any():
            combined = valid

        candidates = anterior_x.copy()
        candidates[~combined] = w  # set non-candidates to max (we want minimum)
        nipple_y = int(np.argmin(candidates))
        nipple_x = int(anterior_x[nipple_y])
    else:
        # Furthest from left = MAXIMUM x value (rightmost)
        tissue_rows = np.where(valid)[0]
        y_min_tissue = tissue_rows[0]
        y_max_tissue = tissue_rows[-1]
        tissue_height = y_max_tissue - y_min_tissue
        y_search_start = y_min_tissue + int(tissue_height * 0.20)
        y_search_end = y_min_tissue + int(tissue_height * 0.80)

        search_mask = np.zeros(h, dtype=bool)
        search_mask[y_search_start:y_search_end] = True
        combined = valid & search_mask

        if not combined.any():
            combined = valid

        candidates = anterior_x.copy()
        candidates[~combined] = -1  # set non-candidates to -1 (we want maximum)
        nipple_y = int(np.argmax(candidates))
        nipple_x = int(anterior_x[nipple_y])

    return nipple_x, nipple_y


def _find_nipple_from_mask_mlo(
    mask, h: int, w: int, chest_wall_on_right: bool
) -> Tuple[Optional[int], Optional[int]]:
    """
    MLO view: find the nipple as the APEX (tip) of the breast contour.

    In MLO the breast hangs obliquely forming a teardrop/comma shape.
    The nipple is at the TIP of this shape — the point where the anterior
    breast contour bulges outward the most.

    Algorithm (chord-apex + curvature):
        1. Extract the anterior breast contour as (x, y) points.
        2. Smooth the contour to remove noise.
        3. Draw a chord from the top of the contour to the bottom.
        4. The nipple = point with maximum perpendicular distance from the chord,
           combined with local curvature, biased toward the lower portion.

    This approach does NOT depend on pec line estimation (which is fragile).
    It directly finds the "nose" / protruding tip of the breast profile.
    """
    import numpy as np

    # ── Step 1: Extract anterior breast contour ──
    contour_x = np.full(h, -1, dtype=np.int32)

    if chest_wall_on_right:
        for y in range(h):
            tissue_cols = np.where(mask[y, :])[0]
            if len(tissue_cols) > 0:
                contour_x[y] = tissue_cols[0]  # leftmost = anterior
    else:
        for y in range(h):
            tissue_cols = np.where(mask[y, :])[0]
            if len(tissue_cols) > 0:
                contour_x[y] = tissue_cols[-1]  # rightmost = anterior

    valid = contour_x >= 0
    if not valid.any():
        return None, None

    tissue_rows = np.where(valid)[0]
    y_min_tissue = tissue_rows[0]
    y_max_tissue = tissue_rows[-1]
    tissue_height = y_max_tissue - y_min_tissue

    if tissue_height < 30:
        return None, None

    # ── Step 2: Build smooth contour arrays ──
    # Work only with the valid contour section
    y_vals = tissue_rows.astype(np.float64)
    x_vals = contour_x[tissue_rows].astype(np.float64)
    n_points = len(y_vals)

    # Moving average smoothing with a generous kernel
    kernel_size = max(15, tissue_height // 20)
    kernel = np.ones(kernel_size) / kernel_size
    x_smooth = np.convolve(x_vals, kernel, mode='same')

    # ── Step 3: Chord-distance method (find apex of the teardrop) ──
    # Exclude top 15% (pec muscle region) and bottom 5%
    i_start = int(n_points * 0.15)
    i_end = int(n_points * 0.95)
    if i_end <= i_start + 5:
        i_start = 0
        i_end = n_points

    # Chord endpoints: top and bottom of the search region
    p_top = np.array([x_smooth[i_start], y_vals[i_start]])
    p_bot = np.array([x_smooth[i_end - 1], y_vals[i_end - 1]])

    # Chord direction vector
    chord_vec = p_bot - p_top
    chord_len = np.linalg.norm(chord_vec)
    if chord_len < 1.0:
        return None, None
    chord_dir = chord_vec / chord_len

    # Compute perpendicular distance of each contour point to the chord
    search_len = i_end - i_start
    chord_distances = np.zeros(search_len)
    for i in range(search_len):
        idx = i_start + i
        pt = np.array([x_smooth[idx], y_vals[idx]])
        vec = pt - p_top
        # 2D cross product gives signed distance from the chord line
        cross = vec[0] * chord_dir[1] - vec[1] * chord_dir[0]
        chord_distances[i] = cross

    # For right chest wall, anterior = left → nipple protrudes left → NEGATIVE cross
    # For left chest wall, anterior = right → nipple protrudes right → POSITIVE cross
    if chest_wall_on_right:
        chord_distances = -chord_distances  # flip so positive = more anterior

    # ── Step 4: Curvature analysis ──
    # Compute local curvature — high curvature = sharp convex tip = nipple
    curvature = np.zeros(search_len)
    if search_len > 10:
        # Use the smoothed contour for curvature
        seg_x = x_smooth[i_start:i_end]
        seg_y = y_vals[i_start:i_end]

        # First and second derivatives (central differences)
        dx = np.gradient(seg_x)
        ddx = np.gradient(dx)
        dy = np.gradient(seg_y)
        ddy = np.gradient(dy)

        for i in range(search_len):
            denom = (dx[i]**2 + dy[i]**2) ** 1.5
            if denom > 1e-6:
                # Signed curvature
                kappa = (ddx[i] * dy[i] - ddy[i] * dx[i]) / denom
                # For right chest wall, convex tip curves leftward (negative curvature)
                if chest_wall_on_right:
                    curvature[i] = -kappa
                else:
                    curvature[i] = kappa

    # ── Step 5: Combine signals with vertical bias ──
    # Normalize chord distances to [0, 1]
    cd_max = chord_distances.max()
    if cd_max > 0:
        cd_norm = np.clip(chord_distances / cd_max, 0, 1)
    else:
        cd_norm = np.zeros(search_len)

    # Normalize curvature (only positive values = convex)
    cv_pos = np.clip(curvature, 0, None)
    cv_max = cv_pos.max()
    if cv_max > 0:
        cv_norm = cv_pos / cv_max
    else:
        cv_norm = np.zeros(search_len)

    # Vertical bias: prefer points in the lower 50-70% of the breast
    # (nipple is inferior in MLO)
    t = np.linspace(0, 1, search_len)
    # Gaussian bias centered at ~0.58 (lower half)
    vertical_bias = np.exp(-((t - 0.58) ** 2) / (2 * 0.18**2))
    # Normalize so it ranges from 0.2 to 1.0 (don't fully exclude upper points)
    vb_max = vertical_bias.max()
    if vb_max > 0:
        vertical_bias = 0.2 + 0.8 * (vertical_bias / vb_max)

    # Combined score: 55% chord distance + 25% curvature + 20% vertical position
    combined_score = 0.55 * cd_norm + 0.25 * cv_norm + 0.20 * vertical_bias

    # Find the best point
    best_idx_in_search = int(np.argmax(combined_score))
    best_idx = i_start + best_idx_in_search

    # Map back to the original image row
    nipple_y = int(y_vals[best_idx])

    # Get the actual tissue edge at that row (use the raw mask, not smoothed)
    tissue_cols = np.where(mask[nipple_y, :])[0]
    if len(tissue_cols) == 0:
        return None, None

    if chest_wall_on_right:
        nipple_x = int(tissue_cols[0])
    else:
        nipple_x = int(tissue_cols[-1])

    return nipple_x, nipple_y


def _estimate_from_anatomy(
    laterality: str,
    view_position: str,
    image_geom: ImageGeometry,
    lesion_boxes_px: Optional[list] = None,
) -> NipplePosition:
    """
    Estimate nipple position from anatomical conventions.

    Standard mammography display conventions:
        R breast: anterior edge on LEFT side of image.
        L breast: anterior edge on RIGHT side of image.

    CC view: nipple at ~5% from anterior edge, vertically centered (~45%).
    MLO view: nipple at ~5% from anterior edge, lower in the image (~60-65%)
              because the breast hangs obliquely and the nipple is inferior.
    """
    w_px = image_geom.width_px
    h_px = image_geom.height_px

    if not lesion_boxes_px:
        # No lesions available — use default anatomical position
        if laterality == 'R':
            nipple_x = w_px * 0.05
        else:
            nipple_x = w_px * 0.95

        if view_position == 'MLO':
            # In MLO, nipple is more inferior (lower in image)
            nipple_y = h_px * 0.62
        else:
            # In CC, nipple is roughly at vertical center of breast
            nipple_y = h_px * 0.45
    else:
        # Use lesion positions to refine nipple estimate
        if laterality == 'R':
            # Nipple is anterior (left side) of all lesions
            min_x = min(b[0] for b in lesion_boxes_px)
            nipple_x = max(0, min_x * 0.3)
        else:
            # Nipple is anterior (right side) of all lesions
            max_x = max(b[2] for b in lesion_boxes_px)
            nipple_x = min(w_px, max_x + (w_px - max_x) * 0.7)

        # Vertical position depends on view
        avg_y = sum((b[1] + b[3]) / 2 for b in lesion_boxes_px) / len(lesion_boxes_px)
        if view_position == 'CC':
            # CC: nipple roughly at the vertical center, slightly above lesions
            nipple_y = avg_y * 0.8
        else:
            # MLO: nipple is more inferior — use the maximum Y among lesions
            # (nipple is below or at the level of the lowest lesion)
            max_y = max((b[1] + b[3]) / 2 for b in lesion_boxes_px)
            nipple_y = min(h_px * 0.90, max_y + h_px * 0.05)

    return NipplePosition.from_pixels(
        x_px=float(nipple_x),
        y_px=float(nipple_y),
        spacing=image_geom.pixel_spacing,
        detected=False,
    )
