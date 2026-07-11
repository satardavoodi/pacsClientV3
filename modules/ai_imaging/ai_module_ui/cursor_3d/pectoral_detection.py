"""
Pectoral Muscle Detection — Automatic detection of pectoral angle in MLO views.

The pectoral muscle angle (θ) is critical for accurate CC↔MLO lesion correlation.
It is the angle between the pectoral muscle edge and the vertical axis of the image.

Typical range: 40° to 60° from vertical.

Algorithm:
    1. Segment the upper-posterior region where the pectoral muscle is visible.
    2. Apply edge detection (Canny + Hough Line Transform).
    3. Filter lines by length, angle, and position.
    4. Select the strongest candidate as the pectoral edge.
    5. Return the angle in degrees from vertical.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class PectoralLine:
    """A detected pectoral muscle edge line."""
    rho: float  # Distance from origin in Hough space
    theta: float  # Angle in radians
    angle_deg: float  # Angle in degrees from vertical
    x1: int  # Start point (pixel coords)
    y1: int
    x2: int  # End point
    y2: int
    score: float  # Detection confidence (0-1)

    @property
    def length(self) -> float:
        """Line length in pixels."""
        return math.sqrt((self.x2 - self.x1)**2 + (self.y2 - self.y1)**2)


def detect_pectoral_angle(
    image: np.ndarray,
    laterality: str,
    roi_height_fraction: float = 0.5,
    roi_width_fraction: float = 0.6,
    min_angle_deg: float = 30.0,
    max_angle_deg: float = 60.0,
    min_line_length: int = 100,
    canny_low: int = 50,
    canny_high: int = 150,
) -> Optional[PectoralLine]:
    """
    Detect the pectoral muscle angle in an MLO mammogram.

    Args:
        image: Grayscale mammogram image (H x W), dtype uint8.
        laterality: 'R' or 'L' (determines which side to search).
        roi_height_fraction: Fraction of image height to search (top portion).
        roi_width_fraction: Fraction of image width to search.
        min_angle_deg: Minimum acceptable pectoral angle from vertical.
        max_angle_deg: Maximum acceptable pectoral angle from vertical.
        min_line_length: Minimum line length to consider (pixels).
        canny_low: Lower threshold for Canny edge detection.
        canny_high: Upper threshold for Canny edge detection.

    Returns:
        PectoralLine object if detected, None otherwise.

    Physical Interpretation:
        - θ = 0° → vertical line (parallel to chest wall)
        - θ = 45° → diagonal line
        - θ = 90° → horizontal line (perpendicular to chest wall)

        In MLO views, the pectoral muscle typically runs from the upper-posterior
        corner at an angle of 40-60° from vertical, creating a triangular region
        of higher density in the corner.
    """
    if image is None or image.size == 0:
        return None

    h, w = image.shape[:2]

    # Define ROI: upper region where pectoral muscle is visible
    roi_h = int(h * roi_height_fraction)
    roi_w = int(w * roi_width_fraction)

    # Laterality determines which corner
    if laterality == 'R':
        # R-MLO: chest wall on right → search upper-right
        roi = image[0:roi_h, (w - roi_w):w]
    else:
        # L-MLO: chest wall on left → search upper-left
        roi = image[0:roi_h, 0:roi_w]

    if roi.size == 0:
        return None

    # Step 1: Enhance contrast in ROI
    # Apply CLAHE (Contrast Limited Adaptive Histogram Equalization)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    roi_enhanced = clahe.apply(roi)

    # Step 2: Edge detection (Canny)
    edges = cv2.Canny(roi_enhanced, canny_low, canny_high, apertureSize=3)

    # Step 3: Morphological closing to connect edge fragments
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    # Step 4: Hough Line Transform (Probabilistic)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=np.pi / 180,
        threshold=50,
        minLineLength=min_line_length,
        maxLineGap=10,
    )

    if lines is None or len(lines) == 0:
        return None

    # Step 5: Filter and score candidate lines
    candidates: List[PectoralLine] = []

    for line_data in lines:
        x1, y1, x2, y2 = line_data[0]

        # Convert to absolute image coordinates
        if laterality == 'R':
            x1 += (w - roi_w)
            x2 += (w - roi_w)
        # For L breast, x coords are already correct (roi starts at 0)

        # Compute angle from vertical
        dx = x2 - x1
        dy = y2 - y1
        if abs(dx) < 1e-6:
            angle_deg = 0.0  # Vertical line
        else:
            angle_rad = math.atan2(abs(dy), abs(dx))
            angle_deg = math.degrees(angle_rad)

        # Filter by angle range
        if not (min_angle_deg <= angle_deg <= max_angle_deg):
            continue

        # Compute Hough (rho, theta)
        rho = x1 * math.cos(angle_rad) + y1 * math.sin(angle_rad)
        theta = angle_rad

        # Score: combination of line length and position (upper corner preferred)
        length = math.sqrt(dx**2 + dy**2)
        # Position score: closer to corner = higher score
        corner_x = w if laterality == 'R' else 0
        corner_dist = math.sqrt((x1 - corner_x)**2 + y1**2)
        position_score = max(0, 1.0 - corner_dist / (w / 2))
        # Length score: longer line = higher score
        length_score = min(1.0, length / (h * 0.8))
        # Combined score
        score = 0.6 * length_score + 0.4 * position_score

        candidates.append(PectoralLine(
            rho=rho,
            theta=theta,
            angle_deg=angle_deg,
            x1=x1, y1=y1, x2=x2, y2=y2,
            score=score,
        ))

    if not candidates:
        return None

    # Select the best candidate (highest score)
    best_line = max(candidates, key=lambda line: line.score)

    return best_line


def draw_pectoral_line(image: np.ndarray, pectoral: PectoralLine, color=(0, 255, 0), thickness=2) -> np.ndarray:
    """
    Draw the detected pectoral line on the image for visualization.

    Args:
        image: Input image (grayscale or RGB).
        pectoral: Detected PectoralLine.
        color: Line color (BGR for RGB image, gray value for grayscale).
        thickness: Line thickness in pixels.

    Returns:
        Image with drawn line.
    """
    output = image.copy()
    if len(output.shape) == 2:
        # Convert grayscale to RGB for colored line
        output = cv2.cvtColor(output, cv2.COLOR_GRAY2BGR)

    cv2.line(output, (pectoral.x1, pectoral.y1), (pectoral.x2, pectoral.y2), color, thickness)

    # Draw angle annotation
    text = f"{pectoral.angle_deg:.1f}°"
    cv2.putText(output, text, (pectoral.x1 + 10, pectoral.y1 + 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    return output


def estimate_pectoral_angle_fallback(laterality: str, view_position: str) -> float:
    """
    Fallback: estimate pectoral angle when detection fails.

    Args:
        laterality: 'R' or 'L'
        view_position: 'CC' or 'MLO'

    Returns:
        Estimated angle in degrees from vertical.

    Clinical literature suggests:
        - MLO: typical pectoral angle ≈ 45-55° from vertical.
        - CC: pectoral muscle not visible (N/A).
    """
    if view_position == 'MLO':
        return 45.0  # Default consistent with validation module (clinical mid-range)
    else:
        # CC view: no pectoral muscle edge visible
        return 0.0  # Not applicable
