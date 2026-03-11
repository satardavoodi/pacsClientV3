"""
VTK Helper Functions

Utility functions for working with VTK in the MPR module.
"""

import logging
from typing import Tuple, Optional

import numpy as np
import vtkmodules.all as vtk
from vtkmodules.util import numpy_support

logger = logging.getLogger(__name__)


def create_vtk_image_from_numpy(
    np_array: np.ndarray,
    spacing: Tuple[float, float, float] = (1.0, 1.0, 1.0),
    origin: Tuple[float, float, float] = (0.0, 0.0, 0.0)
) -> vtk.vtkImageData:
    """
    Create vtkImageData from numpy array.
    
    Args:
        np_array: 3D numpy array in [z, y, x] order
        spacing: Voxel spacing (x, y, z)
        origin: Volume origin (x, y, z)
    
    Returns:
        vtkImageData with proper geometry
    """
    # Get dimensions
    if np_array.ndim == 3:
        depth, height, width = np_array.shape
    elif np_array.ndim == 2:
        height, width = np_array.shape
        depth = 1
        np_array = np_array.reshape(1, height, width)
    else:
        raise ValueError(f"Expected 2D or 3D array, got {np_array.ndim}D")
    
    # Create VTK image data
    vtk_image = vtk.vtkImageData()
    vtk_image.SetDimensions(width, height, depth)
    vtk_image.SetSpacing(spacing)
    vtk_image.SetOrigin(origin)
    
    # Flatten array in Fortran order for VTK
    flat_array = np_array.flatten(order='F')
    
    # Determine VTK data type
    dtype_map = {
        np.int8: vtk.VTK_SIGNED_CHAR,
        np.uint8: vtk.VTK_UNSIGNED_CHAR,
        np.int16: vtk.VTK_SHORT,
        np.uint16: vtk.VTK_UNSIGNED_SHORT,
        np.int32: vtk.VTK_INT,
        np.uint32: vtk.VTK_UNSIGNED_INT,
        np.float32: vtk.VTK_FLOAT,
        np.float64: vtk.VTK_DOUBLE,
    }
    
    vtk_type = dtype_map.get(np_array.dtype.type, vtk.VTK_FLOAT)
    
    if np_array.dtype.type not in dtype_map:
        flat_array = flat_array.astype(np.float32)
    
    # Create VTK array
    vtk_array = numpy_support.numpy_to_vtk(
        flat_array,
        deep=True,
        array_type=vtk_type
    )
    
    # Set scalars
    vtk_image.GetPointData().SetScalars(vtk_array)
    
    return vtk_image


def vtk_image_to_numpy(vtk_image: vtk.vtkImageData) -> np.ndarray:
    """
    Convert vtkImageData to numpy array.
    
    Args:
        vtk_image: VTK image data
    
    Returns:
        3D numpy array in [z, y, x] order
    """
    # Get dimensions
    dims = vtk_image.GetDimensions()
    
    # Get scalars
    scalars = vtk_image.GetPointData().GetScalars()
    
    if scalars is None:
        raise ValueError("VTK image has no scalar data")
    
    # Convert to numpy
    np_array = numpy_support.vtk_to_numpy(scalars)
    
    # Reshape to 3D (Fortran order for VTK)
    np_array = np_array.reshape(dims[2], dims[1], dims[0], order='F')
    
    return np_array


def create_lookup_table(
    num_colors: int = 256,
    range_min: float = 0.0,
    range_max: float = 255.0,
    hue_range: Tuple[float, float] = (0.0, 0.0),
    saturation_range: Tuple[float, float] = (0.0, 0.0),
    value_range: Tuple[float, float] = (0.0, 1.0)
) -> vtk.vtkLookupTable:
    """
    Create a grayscale or colored lookup table.
    
    Args:
        num_colors: Number of colors in table
        range_min: Minimum scalar value
        range_max: Maximum scalar value
        hue_range: HSV hue range (0-1)
        saturation_range: HSV saturation range (0-1)
        value_range: HSV value range (0-1)
    
    Returns:
        Configured vtkLookupTable
    """
    lut = vtk.vtkLookupTable()
    lut.SetNumberOfTableValues(num_colors)
    lut.SetTableRange(range_min, range_max)
    lut.SetRampToLinear()
    lut.SetHueRange(*hue_range)
    lut.SetSaturationRange(*saturation_range)
    lut.SetValueRange(*value_range)
    lut.SetAlphaRange(1.0, 1.0)
    lut.Build()
    
    return lut


def create_window_level_filter(
    window: float = 400.0,
    level: float = 40.0
) -> vtk.vtkImageMapToWindowLevelColors:
    """
    Create window/level filter for image display.
    
    Args:
        window: Window width
        level: Window center/level
    
    Returns:
        Configured vtkImageMapToWindowLevelColors
    """
    wl_filter = vtk.vtkImageMapToWindowLevelColors()
    wl_filter.SetWindow(window)
    wl_filter.SetLevel(level)
    
    return wl_filter


def create_image_reslice(
    interpolation: str = "linear"
) -> vtk.vtkImageReslice:
    """
    Create image reslice filter with specified interpolation.
    
    Args:
        interpolation: Interpolation method ('nearest', 'linear', 'cubic', 'lanczos')
    
    Returns:
        Configured vtkImageReslice
    """
    reslice = vtk.vtkImageReslice()
    reslice.SetOutputDimensionality(2)
    
    interpolation = interpolation.lower()
    
    if interpolation == "nearest":
        reslice.SetInterpolationModeToNearestNeighbor()
    elif interpolation == "linear":
        reslice.SetInterpolationModeToLinear()
    elif interpolation == "cubic":
        reslice.SetInterpolationModeToCubic()
    elif interpolation == "lanczos":
        interpolator = vtk.vtkImageSincInterpolator()
        interpolator.SetWindowFunctionToLanczos()
        interpolator.AntialiasingOn()
        reslice.SetInterpolator(interpolator)
    else:
        reslice.SetInterpolationModeToLinear()
    
    return reslice


def get_image_info(vtk_image: vtk.vtkImageData) -> dict:
    """
    Get information about VTK image.
    
    Args:
        vtk_image: VTK image data
    
    Returns:
        Dictionary with image properties
    """
    dims = vtk_image.GetDimensions()
    spacing = vtk_image.GetSpacing()
    origin = vtk_image.GetOrigin()
    bounds = vtk_image.GetBounds()
    scalar_range = vtk_image.GetScalarRange()
    
    return {
        "dimensions": dims,
        "spacing": spacing,
        "origin": origin,
        "bounds": bounds,
        "scalar_range": scalar_range,
        "physical_size": (
            dims[0] * spacing[0],
            dims[1] * spacing[1],
            dims[2] * spacing[2]
        ),
        "center": (
            (bounds[0] + bounds[1]) / 2,
            (bounds[2] + bounds[3]) / 2,
            (bounds[4] + bounds[5]) / 2
        ),
    }


def create_text_actor(
    text: str,
    position: Tuple[float, float] = (0.05, 0.95),
    color: Tuple[float, float, float] = (1.0, 1.0, 0.0),
    font_size: int = 14
) -> vtk.vtkTextActor:
    """
    Create a text actor for annotations.
    
    Args:
        text: Text to display
        position: Normalized viewport position (0-1)
        color: RGB color (0-1)
        font_size: Font size in points
    
    Returns:
        Configured vtkTextActor
    """
    actor = vtk.vtkTextActor()
    actor.SetInput(text)
    actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    actor.GetPositionCoordinate().SetValue(position[0], position[1])
    actor.GetTextProperty().SetFontSize(font_size)
    actor.GetTextProperty().SetColor(*color)
    actor.GetTextProperty().SetBold(True)
    
    return actor
