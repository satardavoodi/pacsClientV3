"""
SimpleITK Helper Functions

Utility functions for working with SimpleITK in the MPR module.
"""

import logging
from typing import Tuple, Optional

import numpy as np
import SimpleITK as sitk

logger = logging.getLogger(__name__)


def sitk_to_numpy(image: sitk.Image) -> np.ndarray:
    """
    Convert SimpleITK image to numpy array.
    
    Note: SimpleITK arrays are in [z, y, x] order.
    
    Args:
        image: SimpleITK image
    
    Returns:
        Numpy array
    """
    return sitk.GetArrayFromImage(image)


def numpy_to_sitk(
    np_array: np.ndarray,
    spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0),
    direction: Optional[Tuple] = None
) -> sitk.Image:
    """
    Convert numpy array to SimpleITK image.
    
    Args:
        np_array: 3D numpy array in [z, y, x] order
        spacing: Voxel spacing (x, y, z)
        origin: Image origin (x, y, z)
        direction: Optional direction cosines (9 values)
    
    Returns:
        SimpleITK image
    """
    image = sitk.GetImageFromArray(np_array)
    image.SetSpacing(spacing)
    image.SetOrigin(origin)
    
    if direction is not None:
        image.SetDirection(direction)
    
    return image


def resample_to_isotropic(
    image: sitk.Image,
    target_spacing: Optional[float] = None,
    interpolation: str = "linear"
) -> sitk.Image:
    """
    Resample image to isotropic spacing.
    
    Args:
        image: Input SimpleITK image
        target_spacing: Target isotropic spacing (default: smallest current spacing)
        interpolation: Interpolation method ('nearest', 'linear', 'bspline')
    
    Returns:
        Resampled image with isotropic spacing
    """
    # Get current properties
    original_spacing = image.GetSpacing()
    original_size = image.GetSize()
    
    # Determine target spacing
    if target_spacing is None:
        target_spacing = min(original_spacing)
    
    new_spacing = [target_spacing, target_spacing, target_spacing]
    
    # Calculate new size
    new_size = [
        int(np.ceil(original_size[i] * original_spacing[i] / new_spacing[i]))
        for i in range(3)
    ]
    
    # Select interpolator
    interpolation = interpolation.lower()
    if interpolation == "nearest":
        sitk_interpolator = sitk.sitkNearestNeighbor
    elif interpolation == "bspline":
        sitk_interpolator = sitk.sitkBSpline
    else:
        sitk_interpolator = sitk.sitkLinear
    
    # Resample
    resampler = sitk.ResampleImageFilter()
    resampler.SetInterpolator(sitk_interpolator)
    resampler.SetOutputSpacing(new_spacing)
    resampler.SetSize(new_size)
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetDefaultPixelValue(-1024)  # Air in HU
    
    resampled = resampler.Execute(image)
    
    logger.info(f"Resampled from {original_spacing} to {new_spacing}")
    
    return resampled


def apply_window_level_sitk(
    image: sitk.Image,
    window: float,
    level: float
) -> sitk.Image:
    """
    Apply window/level to SimpleITK image.
    
    Args:
        image: Input image
        window: Window width
        level: Window center
    
    Returns:
        Image with window/level applied (0-255 output)
    """
    # Calculate min and max from window/level
    min_val = level - window / 2
    max_val = level + window / 2
    
    # Clamp and rescale
    output = sitk.IntensityWindowing(
        image,
        windowMinimum=min_val,
        windowMaximum=max_val,
        outputMinimum=0.0,
        outputMaximum=255.0
    )
    
    return sitk.Cast(output, sitk.sitkUInt8)


def get_image_info_sitk(image: sitk.Image) -> dict:
    """
    Get information about SimpleITK image.
    
    Args:
        image: SimpleITK image
    
    Returns:
        Dictionary with image properties
    """
    size = image.GetSize()
    spacing = image.GetSpacing()
    origin = image.GetOrigin()
    direction = image.GetDirection()
    
    # Calculate statistics
    stats = sitk.StatisticsImageFilter()
    stats.Execute(image)
    
    return {
        "size": size,
        "spacing": spacing,
        "origin": origin,
        "direction": direction,
        "pixel_type": image.GetPixelIDTypeAsString(),
        "num_dimensions": image.GetDimension(),
        "min_value": stats.GetMinimum(),
        "max_value": stats.GetMaximum(),
        "mean_value": stats.GetMean(),
        "physical_size": tuple(size[i] * spacing[i] for i in range(3)),
    }


def extract_slice(
    image: sitk.Image,
    plane: str,
    index: int
) -> sitk.Image:
    """
    Extract a 2D slice from 3D volume.
    
    Args:
        image: 3D SimpleITK image
        plane: Plane to extract ('axial', 'sagittal', 'coronal')
        index: Slice index
    
    Returns:
        2D SimpleITK image
    """
    size = image.GetSize()
    plane = plane.lower()
    
    if plane == "axial":
        # Extract Z slice
        return image[:, :, index]
    elif plane == "sagittal":
        # Extract X slice
        return image[index, :, :]
    elif plane == "coronal":
        # Extract Y slice
        return image[:, index, :]
    else:
        raise ValueError(f"Unknown plane: {plane}")


def apply_rescale_slope_intercept(
    image: sitk.Image,
    slope: float,
    intercept: float
) -> sitk.Image:
    """
    Apply DICOM rescale slope and intercept.
    
    HU = pixel_value * slope + intercept
    
    Args:
        image: Input image
        slope: Rescale slope
        intercept: Rescale intercept
    
    Returns:
        Image in HU values
    """
    return sitk.Cast(image, sitk.sitkFloat32) * slope + intercept


def create_test_volume(
    size: Tuple[int, int, int] = (100, 100, 50),
    spacing: Tuple[float, float, float] = (1.0, 1.0, 2.0)
) -> sitk.Image:
    """
    Create a test volume with simple geometric shapes.
    
    Useful for testing MPR functionality without real DICOM data.
    
    Args:
        size: Volume size (x, y, z)
        spacing: Voxel spacing
    
    Returns:
        SimpleITK image with test pattern
    """
    # Create empty volume
    np_array = np.zeros((size[2], size[1], size[0]), dtype=np.float32)
    
    # Add some geometric shapes
    center = (size[0] // 2, size[1] // 2, size[2] // 2)
    
    # Add a sphere
    for z in range(size[2]):
        for y in range(size[1]):
            for x in range(size[0]):
                dist = np.sqrt(
                    (x - center[0])**2 +
                    (y - center[1])**2 +
                    (z - center[2])**2
                )
                if dist < 20:
                    np_array[z, y, x] = 500  # Soft tissue
                elif dist < 25:
                    np_array[z, y, x] = 1000  # Bone-like
    
    # Add a vertical cylinder
    for z in range(size[2]):
        for y in range(size[1]):
            for x in range(size[0]):
                dist_xy = np.sqrt((x - 30)**2 + (y - center[1])**2)
                if dist_xy < 10:
                    np_array[z, y, x] = 200
    
    # Create SimpleITK image
    image = numpy_to_sitk(np_array, spacing)
    
    return image
