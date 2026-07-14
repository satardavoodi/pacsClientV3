"""
Arc Probability Calculator — Lesion probability estimation along the correspondence arc.

This module computes a per-point probability score for each position along the
3D Cursor correspondence arc. The probability is based on:

1. **Image Features** (from the current mammogram):
   - Local pixel intensity (higher density → higher suspicion)
   - Local histogram statistics (mean, variance)
   - Texture contrast (local gradient magnitude)
   - Dense tissue proportion in a local window

2. **Geometric Priors** (from Kopans' Rule / anatomy):
   - Distance from nipple (lesions cluster at certain depths)
   - Position relative to pectoral line (upper-outer quadrant bias)
   - Angular position on the arc (central = more likely)

3. **Dataset Statistics** (optional, from annotated AI dataset):
   - Histogram of lesion positions relative to nipple/pectoral line
   - Typical density patterns around confirmed lesions

The output is a 1D array of probabilities (one per arc sample point)
that can be visualized as a heatmap overlay on the arc.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np


# ─── Configuration ───────────────────────────────────────────────────────────

# Local analysis window (pixels)
LOCAL_WINDOW_SIZE = 41  # NxN pixel window for feature extraction (larger = more context)

# Weights for combining probability factors
WEIGHT_DENSITY = 0.25       # Local tissue density
WEIGHT_TEXTURE = 0.15       # Texture contrast / gradient magnitude
WEIGHT_GEOMETRIC = 0.15     # Geometric prior (angular + radial)
WEIGHT_HISTOGRAM = 0.15     # Local histogram deviation from background
WEIGHT_ENTROPY = 0.15       # Local entropy (information content)
WEIGHT_CONTRAST = 0.15      # Local contrast (intensity range)

# Geometric prior: angular weighting (center of arc = more probable)
ANGULAR_SIGMA_DEG = 30.0    # Gaussian sigma for angular weighting

# Number of sample points along the arc for probability computation
ARC_PROBABILITY_SAMPLES = 64


@dataclass
class ArcProbabilityResult:
    """Result of probability computation along the arc."""
    # Per-sample probabilities (normalized 0..1)
    probabilities: np.ndarray  # shape: (n_samples,)
    # Sample positions in image pixel coordinates
    sample_positions_px: List[Tuple[float, float]] = field(default_factory=list)
    # Feature components (for debugging / visualization)
    density_scores: Optional[np.ndarray] = None
    texture_scores: Optional[np.ndarray] = None
    geometric_scores: Optional[np.ndarray] = None
    histogram_scores: Optional[np.ndarray] = None
    # Arc metadata
    center_x_px: float = 0.0
    center_y_px: float = 0.0
    radius_px: float = 0.0
    start_angle_rad: float = 0.0
    end_angle_rad: float = 0.0


def compute_arc_probability(
    pixel_array: Optional[np.ndarray],
    nipple_x_px: float,
    nipple_y_px: float,
    radius_px: float,
    start_angle_rad: float,
    end_angle_rad: float,
    pectoral_angle_deg: Optional[float] = None,
    n_samples: int = ARC_PROBABILITY_SAMPLES,
) -> ArcProbabilityResult:
    """
    Compute probability scores along the correspondence arc.

    Args:
        pixel_array: 2D numpy array of image intensities (rows x cols). Can be None.
        nipple_x_px: Nipple X position in image pixels.
        nipple_y_px: Nipple Y position in image pixels.
        radius_px: Arc radius in pixels.
        start_angle_rad: Start angle of the arc (radians).
        end_angle_rad: End angle of the arc (radians).
        pectoral_angle_deg: Pectoral line angle (degrees from vertical). Optional.
        n_samples: Number of sample points along the arc.

    Returns:
        ArcProbabilityResult with per-sample probabilities.
    """
    # Generate sample positions along the arc
    angles = np.linspace(start_angle_rad, end_angle_rad, n_samples)
    positions_px = []
    for angle in angles:
        x = nipple_x_px + radius_px * math.cos(angle)
        y = nipple_y_px + radius_px * math.sin(angle)
        positions_px.append((x, y))

    # Compute individual feature scores
    density_scores = _compute_density_scores(pixel_array, positions_px)
    texture_scores = _compute_texture_scores(pixel_array, positions_px)
    geometric_scores = _compute_geometric_scores(
        angles, start_angle_rad, end_angle_rad, pectoral_angle_deg
    )
    histogram_scores = _compute_histogram_scores(pixel_array, positions_px)
    entropy_scores = _compute_entropy_scores(pixel_array, positions_px)
    contrast_scores = _compute_contrast_scores(pixel_array, positions_px)

    # Combine scores with weights
    combined = (
        WEIGHT_DENSITY * density_scores
        + WEIGHT_TEXTURE * texture_scores
        + WEIGHT_GEOMETRIC * geometric_scores
        + WEIGHT_HISTOGRAM * histogram_scores
        + WEIGHT_ENTROPY * entropy_scores
        + WEIGHT_CONTRAST * contrast_scores
    )

    # Normalize to [0, 1]
    prob_min = combined.min()
    prob_max = combined.max()
    if prob_max > prob_min:
        probabilities = (combined - prob_min) / (prob_max - prob_min)
    else:
        probabilities = np.full(n_samples, 0.5)

    return ArcProbabilityResult(
        probabilities=probabilities,
        sample_positions_px=positions_px,
        density_scores=density_scores,
        texture_scores=texture_scores,
        geometric_scores=geometric_scores,
        histogram_scores=histogram_scores,
        center_x_px=nipple_x_px,
        center_y_px=nipple_y_px,
        radius_px=radius_px,
        start_angle_rad=start_angle_rad,
        end_angle_rad=end_angle_rad,
    )


# ─── Feature Extraction ──────────────────────────────────────────────────────


def _compute_density_scores(
    pixel_array: Optional[np.ndarray],
    positions_px: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Compute local tissue density score at each arc sample point.

    Higher density (brighter pixels in mammogram) → higher probability of
    dense tissue harboring a lesion.
    """
    n = len(positions_px)
    scores = np.zeros(n)

    if pixel_array is None:
        return scores + 0.5  # neutral when no image

    rows, cols = pixel_array.shape[:2]
    half_w = LOCAL_WINDOW_SIZE // 2

    # Global statistics for normalization
    global_mean = float(np.mean(pixel_array))
    global_std = float(np.std(pixel_array)) + 1e-6

    for idx, (px, py) in enumerate(positions_px):
        ix, iy = int(round(px)), int(round(py))

        # Extract local window (clamped to image bounds)
        y0 = max(0, iy - half_w)
        y1 = min(rows, iy + half_w + 1)
        x0 = max(0, ix - half_w)
        x1 = min(cols, ix + half_w + 1)

        if y1 <= y0 or x1 <= x0:
            scores[idx] = 0.0
            continue

        window = pixel_array[y0:y1, x0:x1].astype(np.float64)
        local_mean = float(np.mean(window))

        # Z-score of local density vs global
        z_score = (local_mean - global_mean) / global_std
        # Map to [0, 1] using sigmoid-like function
        scores[idx] = 1.0 / (1.0 + math.exp(-z_score))

    return scores


def _compute_texture_scores(
    pixel_array: Optional[np.ndarray],
    positions_px: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Compute texture contrast (gradient magnitude) at each arc sample point.

    Lesions often have different texture from surrounding tissue —
    higher local gradient magnitude suggests tissue boundaries / masses.
    """
    n = len(positions_px)
    scores = np.zeros(n)

    if pixel_array is None:
        return scores + 0.5

    rows, cols = pixel_array.shape[:2]
    half_w = LOCAL_WINDOW_SIZE // 2

    # Precompute gradient magnitude for the whole image (Sobel)
    try:
        grad_x = np.zeros_like(pixel_array, dtype=np.float64)
        grad_y = np.zeros_like(pixel_array, dtype=np.float64)

        # Simple Sobel-like gradient (avoid importing cv2)
        if rows > 2 and cols > 2:
            grad_x[:, 1:-1] = (
                pixel_array[:, 2:].astype(np.float64) -
                pixel_array[:, :-2].astype(np.float64)
            ) / 2.0
            grad_y[1:-1, :] = (
                pixel_array[2:, :].astype(np.float64) -
                pixel_array[:-2, :].astype(np.float64)
            ) / 2.0

        grad_mag = np.sqrt(grad_x ** 2 + grad_y ** 2)
        grad_global_max = float(np.percentile(grad_mag, 99)) + 1e-6
    except Exception:
        return scores + 0.5

    for idx, (px, py) in enumerate(positions_px):
        ix, iy = int(round(px)), int(round(py))

        y0 = max(0, iy - half_w)
        y1 = min(rows, iy + half_w + 1)
        x0 = max(0, ix - half_w)
        x1 = min(cols, ix + half_w + 1)

        if y1 <= y0 or x1 <= x0:
            scores[idx] = 0.0
            continue

        local_grad = grad_mag[y0:y1, x0:x1]
        local_mean_grad = float(np.mean(local_grad))

        # Normalize by global 99th percentile
        scores[idx] = min(1.0, local_mean_grad / grad_global_max)

    return scores


def _compute_geometric_scores(
    angles: np.ndarray,
    start_angle_rad: float,
    end_angle_rad: float,
    pectoral_angle_deg: Optional[float] = None,
) -> np.ndarray:
    """
    Compute geometric prior scores based on angular position along the arc.

    The geometric prior encodes:
    1. Center of arc is more probable than edges (Gaussian weighting).
    2. Upper-outer quadrant bias (if pectoral angle is known).
    """
    n = len(angles)
    scores = np.zeros(n)

    mid_angle = (start_angle_rad + end_angle_rad) / 2.0
    sigma_rad = math.radians(ANGULAR_SIGMA_DEG)

    for idx, angle in enumerate(angles):
        # Gaussian centered at mid-angle
        delta = angle - mid_angle
        gaussian = math.exp(-0.5 * (delta / sigma_rad) ** 2)
        scores[idx] = gaussian

    # If pectoral angle is known, add upper-outer quadrant bias
    if pectoral_angle_deg is not None:
        pect_rad = math.radians(pectoral_angle_deg)
        # Upper-outer quadrant is roughly perpendicular to pectoral line
        preferred_angle = mid_angle  # Already centered on the projected direction
        # Mild bias toward the pectoral line side
        for idx, angle in enumerate(angles):
            # Score slightly higher for positions closer to the pectoral line
            pect_proximity = math.cos(angle - pect_rad)
            scores[idx] *= (1.0 + 0.2 * max(0.0, pect_proximity))

    # Normalize
    s_max = scores.max()
    if s_max > 0:
        scores /= s_max

    return scores


def _compute_histogram_scores(
    pixel_array: Optional[np.ndarray],
    positions_px: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Compute local histogram deviation scores.

    Compares the local intensity distribution to the global background.
    Regions with distributions that deviate from the background (broader,
    shifted, bimodal) score higher as potential lesion sites.
    """
    n = len(positions_px)
    scores = np.zeros(n)

    if pixel_array is None:
        return scores + 0.5

    rows, cols = pixel_array.shape[:2]
    half_w = LOCAL_WINDOW_SIZE // 2

    # Global histogram for reference
    try:
        # Use 64 bins for efficiency
        n_bins = 64
        img_min = float(np.min(pixel_array))
        img_max = float(np.max(pixel_array))
        if img_max <= img_min:
            return scores + 0.5

        global_hist, bin_edges = np.histogram(
            pixel_array.ravel(), bins=n_bins, range=(img_min, img_max), density=True
        )
        global_hist = global_hist.astype(np.float64)
        global_hist /= (global_hist.sum() + 1e-10)  # normalize to PDF
    except Exception:
        return scores + 0.5

    for idx, (px, py) in enumerate(positions_px):
        ix, iy = int(round(px)), int(round(py))

        y0 = max(0, iy - half_w)
        y1 = min(rows, iy + half_w + 1)
        x0 = max(0, ix - half_w)
        x1 = min(cols, ix + half_w + 1)

        if y1 <= y0 or x1 <= x0:
            scores[idx] = 0.0
            continue

        window = pixel_array[y0:y1, x0:x1]

        try:
            local_hist, _ = np.histogram(
                window.ravel(), bins=n_bins, range=(img_min, img_max), density=True
            )
            local_hist = local_hist.astype(np.float64)
            local_hist /= (local_hist.sum() + 1e-10)

            # KL-divergence-like measure (symmetric)
            # Jensen-Shannon divergence
            m = 0.5 * (local_hist + global_hist)
            eps = 1e-10
            kl_local = np.sum(local_hist * np.log((local_hist + eps) / (m + eps)))
            kl_global = np.sum(global_hist * np.log((global_hist + eps) / (m + eps)))
            jsd = 0.5 * (kl_local + kl_global)

            # Map JSD to [0, 1] — higher divergence = more suspicious
            scores[idx] = min(1.0, jsd * 5.0)  # Scale factor tuned empirically
        except Exception:
            scores[idx] = 0.0

    return scores


def _compute_entropy_scores(
    pixel_array: Optional[np.ndarray],
    positions_px: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Compute local Shannon entropy at each arc sample point.

    Entropy measures information content — lesions/masses tend to have
    different entropy than uniform fatty tissue or structured parenchyma.
    """
    n = len(positions_px)
    scores = np.zeros(n)

    if pixel_array is None:
        return scores + 0.5

    rows, cols = pixel_array.shape[:2]
    half_w = LOCAL_WINDOW_SIZE // 2

    for idx, (px, py) in enumerate(positions_px):
        ix, iy = int(round(px)), int(round(py))
        y0 = max(0, iy - half_w)
        y1 = min(rows, iy + half_w + 1)
        x0 = max(0, ix - half_w)
        x1 = min(cols, ix + half_w + 1)

        if y1 <= y0 or x1 <= x0:
            continue

        window = pixel_array[y0:y1, x0:x1].ravel()
        try:
            hist, _ = np.histogram(window, bins=32, density=True)
            hist = hist[hist > 0]
            if len(hist) > 0:
                hist = hist / hist.sum()
                entropy = -np.sum(hist * np.log2(hist + 1e-10))
                # Normalize by max possible entropy (log2(32) ≈ 5)
                scores[idx] = min(1.0, entropy / 5.0)
        except Exception:
            pass

    return scores


def _compute_contrast_scores(
    pixel_array: Optional[np.ndarray],
    positions_px: List[Tuple[float, float]],
) -> np.ndarray:
    """
    Compute local contrast at each arc sample point.

    Local contrast = (max - min) / (max + min + eps) in the local window.
    Higher contrast suggests tissue boundaries or masses.
    """
    n = len(positions_px)
    scores = np.zeros(n)

    if pixel_array is None:
        return scores + 0.5

    rows, cols = pixel_array.shape[:2]
    half_w = LOCAL_WINDOW_SIZE // 2

    for idx, (px, py) in enumerate(positions_px):
        ix, iy = int(round(px)), int(round(py))
        y0 = max(0, iy - half_w)
        y1 = min(rows, iy + half_w + 1)
        x0 = max(0, ix - half_w)
        x1 = min(cols, ix + half_w + 1)

        if y1 <= y0 or x1 <= x0:
            continue

        window = pixel_array[y0:y1, x0:x1].astype(np.float64)
        w_min = float(np.min(window))
        w_max = float(np.max(window))
        denom = w_max + w_min + 1e-6
        scores[idx] = (w_max - w_min) / denom

    return scores


# ─── Dataset Statistics (optional enhancement) ─────────────────────────────


@dataclass
class DatasetLesionStats:
    """Statistical model built from annotated dataset lesion positions."""
    # Histogram of lesion distances from nipple (in fractions of image diagonal)
    distance_histogram: Optional[np.ndarray] = None
    distance_bins: Optional[np.ndarray] = None
    # Histogram of lesion angular positions relative to pectoral line
    angle_histogram: Optional[np.ndarray] = None
    angle_bins: Optional[np.ndarray] = None
    # Mean density around lesions (z-score from global mean)
    mean_lesion_density_zscore: float = 0.5
    # Std of density around lesions
    std_lesion_density_zscore: float = 1.0
    # Number of samples used to build the model
    n_samples: int = 0


def build_dataset_lesion_stats(
    annotations: List[dict],
    image_diagonals: Optional[List[float]] = None,
) -> DatasetLesionStats:
    """
    Build statistical model from dataset annotations.

    Each annotation dict should have:
        - 'center_x', 'center_y': lesion center in pixel coords
        - 'nipple_x', 'nipple_y': nipple position in pixel coords
        - 'image_width', 'image_height': image dimensions
        - 'pectoral_angle_deg': (optional) pectoral line angle

    This is called OFFLINE to build the model, not at runtime.
    """
    if not annotations:
        return DatasetLesionStats()

    distances = []
    angles = []

    for ann in annotations:
        try:
            cx = float(ann.get('center_x', 0))
            cy = float(ann.get('center_y', 0))
            nx = float(ann.get('nipple_x', 0))
            ny = float(ann.get('nipple_y', 0))
            w = float(ann.get('image_width', 1))
            h = float(ann.get('image_height', 1))

            # Distance from nipple (normalized by image diagonal)
            diag = math.sqrt(w * w + h * h)
            dist = math.sqrt((cx - nx) ** 2 + (cy - ny) ** 2) / diag
            distances.append(dist)

            # Angle from nipple
            angle = math.atan2(cy - ny, cx - nx)
            angles.append(angle)
        except Exception:
            continue

    if not distances:
        return DatasetLesionStats()

    dist_arr = np.array(distances)
    angle_arr = np.array(angles)

    dist_hist, dist_bins = np.histogram(dist_arr, bins=32, density=True)
    angle_hist, angle_bins = np.histogram(angle_arr, bins=36, range=(-math.pi, math.pi), density=True)

    return DatasetLesionStats(
        distance_histogram=dist_hist,
        distance_bins=dist_bins,
        angle_histogram=angle_hist,
        angle_bins=angle_bins,
        n_samples=len(distances),
    )


def enhance_probability_with_dataset(
    prob_result: ArcProbabilityResult,
    dataset_stats: Optional[DatasetLesionStats],
    image_diagonal_px: float = 1.0,
) -> ArcProbabilityResult:
    """
    Enhance arc probability scores using dataset statistics.

    Multiplies the image-based probability by a dataset-derived prior
    for each arc position.
    """
    if dataset_stats is None or dataset_stats.n_samples == 0:
        return prob_result

    n = len(prob_result.probabilities)
    dataset_prior = np.ones(n)

    if dataset_stats.distance_histogram is not None and dataset_stats.distance_bins is not None:
        # Compute distance-based prior for each arc point
        for idx, (px, py) in enumerate(prob_result.sample_positions_px):
            dist_from_center = math.sqrt(
                (px - prob_result.center_x_px) ** 2 +
                (py - prob_result.center_y_px) ** 2
            )
            normalized_dist = dist_from_center / max(1.0, image_diagonal_px)

            # Look up in distance histogram
            bin_idx = np.searchsorted(dataset_stats.distance_bins, normalized_dist) - 1
            bin_idx = max(0, min(bin_idx, len(dataset_stats.distance_histogram) - 1))
            dataset_prior[idx] *= (1.0 + dataset_stats.distance_histogram[bin_idx])

    # Normalize the prior
    prior_max = dataset_prior.max()
    if prior_max > 0:
        dataset_prior /= prior_max

    # Combine: weighted average of image-based and dataset-based
    DATASET_WEIGHT = 0.3
    enhanced = (1.0 - DATASET_WEIGHT) * prob_result.probabilities + DATASET_WEIGHT * dataset_prior

    # Re-normalize
    e_min, e_max = enhanced.min(), enhanced.max()
    if e_max > e_min:
        enhanced = (enhanced - e_min) / (e_max - e_min)

    prob_result.probabilities = enhanced
    return prob_result
