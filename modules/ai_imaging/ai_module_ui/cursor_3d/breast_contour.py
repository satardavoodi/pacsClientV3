"""
Breast Contour Segmentation — Extract the breast tissue boundary.

The breast contour is the outer boundary of fibroglandular tissue visible
in the mammogram. It is used to:
    1. Clip correspondence arcs to valid tissue regions.
    2. Validate that projected lesion locations fall within the breast.
    3. Measure breast dimensions for geometric calculations.

Algorithm:
    1. Threshold the image to separate breast tissue from background.
    2. Apply morphological operations to clean noise.
    3. Find the largest connected component (breast blob).
    4. Extract the contour of this component.
    5. Optionally smooth the contour.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np


def segment_breast_contour(
    image: np.ndarray,
    threshold_value: Optional[int] = None,
    min_area_fraction: float = 0.05,
    morph_kernel_size: int = 5,
    smooth_epsilon: float = 0.005,
) -> Optional[np.ndarray]:
    """
    Segment the breast contour from a mammogram image.

    Args:
        image: Grayscale mammogram (H x W), dtype uint8.
        threshold_value: Binarization threshold. If None, use Otsu's method.
        min_area_fraction: Minimum contour area as fraction of image area.
        morph_kernel_size: Size of morphological operation kernel.
        smooth_epsilon: Contour smoothing parameter (fraction of perimeter).

    Returns:
        Contour as numpy array of shape (N, 1, 2) in OpenCV format, or None if failed.

    Physical Interpretation:
        The breast contour separates fibroglandular tissue (which attenuates X-rays)
        from the dark background (air). This boundary is critical for determining
        whether a projected lesion location is anatomically plausible.
    """
    if image is None or image.size == 0:
        return None

    h, w = image.shape[:2]

    # Step 1: Binarization
    if threshold_value is None:
        # Otsu's automatic thresholding
        _, binary = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(image, threshold_value, 255, cv2.THRESH_BINARY)

    # Step 2: Morphological operations to remove noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size))
    # Close small holes
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    # Remove small isolated regions
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)

    # Step 3: Find connected components
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, connectivity=8)

    if num_labels < 2:
        # No foreground component found
        return None

    # Find the largest component (excluding background label 0)
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest_label = np.argmax(areas) + 1  # +1 because we excluded background

    # Check minimum area
    largest_area = areas[largest_label - 1]
    if largest_area < (h * w * min_area_fraction):
        return None

    # Create mask of the largest component
    breast_mask = (labels == largest_label).astype(np.uint8) * 255

    # Step 4: Extract contour
    contours, _ = cv2.findContours(breast_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    # Select the contour (should be only one)
    contour = max(contours, key=cv2.contourArea)

    # Step 5: Smooth the contour
    if smooth_epsilon > 0:
        perimeter = cv2.arcLength(contour, closed=True)
        epsilon = smooth_epsilon * perimeter
        contour = cv2.approxPolyDP(contour, epsilon, closed=True)

    return contour


def is_point_inside_contour(point: Tuple[float, float], contour: np.ndarray) -> bool:
    """
    Test if a point lies inside the breast contour.

    Args:
        point: (x, y) in pixel coordinates.
        contour: OpenCV contour array.

    Returns:
        True if point is inside or on the contour boundary.
    """
    if contour is None or len(contour) == 0:
        return True  # No contour → assume everything is valid

    # cv2.pointPolygonTest returns:
    #   > 0 if inside, < 0 if outside, = 0 if on the boundary
    result = cv2.pointPolygonTest(contour, point, measureDist=False)
    return result >= 0


def clip_points_to_contour(points: List[Tuple[float, float]], contour: np.ndarray) -> List[Tuple[float, float]]:
    """
    Filter a list of points, keeping only those inside the breast contour.

    Args:
        points: List of (x, y) pixel coordinates.
        contour: OpenCV contour array.

    Returns:
        Filtered list of points inside the contour.
    """
    if contour is None or len(contour) == 0:
        return points

    return [pt for pt in points if is_point_inside_contour(pt, contour)]


def draw_breast_contour(image: np.ndarray, contour: np.ndarray, color=(255, 0, 0), thickness=2) -> np.ndarray:
    """
    Draw the breast contour on the image for visualization.

    Args:
        image: Input image (grayscale or RGB).
        contour: OpenCV contour array.
        color: Contour color (BGR for RGB image, gray value for grayscale).
        thickness: Contour line thickness.

    Returns:
        Image with drawn contour.
    """
    output = image.copy()
    if len(output.shape) == 2:
        # Convert grayscale to RGB for colored contour
        output = cv2.cvtColor(output, cv2.COLOR_GRAY2BGR)

    cv2.drawContours(output, [contour], -1, color, thickness)

    return output


def compute_contour_bounds(contour: np.ndarray) -> Tuple[int, int, int, int]:
    """
    Compute the bounding rectangle of the contour.

    Args:
        contour: OpenCV contour array.

    Returns:
        (x, y, width, height) bounding box.
    """
    x, y, w, h = cv2.boundingRect(contour)
    return x, y, w, h


def compute_breast_area_mm2(contour: np.ndarray, pixel_spacing_x: float, pixel_spacing_y: float) -> float:
    """
    Compute the breast area in square millimeters.

    Args:
        contour: OpenCV contour array.
        pixel_spacing_x: mm per pixel in x direction.
        pixel_spacing_y: mm per pixel in y direction.

    Returns:
        Area in mm².
    """
    area_px = cv2.contourArea(contour)
    area_mm2 = area_px * pixel_spacing_x * pixel_spacing_y
    return area_mm2
