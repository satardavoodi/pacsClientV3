"""
MPR Volume Loader with Orientation Fix

This module provides functions to load MHD files via SimpleITK and resample
to identity direction to fix orientation issues with vtkMetaImageReader.

Enable fix by setting environment variable:
    MPR_FIX_ORIENTATION=1

Author: Auto-generated patch for orientation fix
"""

import os
import numpy as np
import SimpleITK as sitk
import vtk
from vtk.util import numpy_support


def is_direction_identity(direction_tuple, tolerance=1e-6):
    """
    Check if the direction matrix (9-tuple) is identity.
    
    Args:
        direction_tuple: 9-element tuple representing 3x3 direction matrix (row-major)
        tolerance: numerical tolerance for comparison
    
    Returns:
        True if direction is identity, False otherwise
    """
    direction_matrix = np.array(direction_tuple).reshape(3, 3)
    identity = np.eye(3)
    return np.allclose(direction_matrix, identity, atol=tolerance)


def detect_acquisition_plane(direction_tuple):
    """
    Detect the acquisition plane from the direction matrix.
    
    The acquisition plane is determined by finding which patient axis (L/R, A/P, S/I)
    corresponds to the image Z-axis (slice direction).
    
    Args:
        direction_tuple: 9-element tuple representing 3x3 direction matrix (row-major)
        
    Returns:
        str: 'axial', 'sagittal', or 'coronal'
    """
    direction_matrix = np.array(direction_tuple).reshape(3, 3)
    
    # The Z column of the direction matrix tells us which patient axis is the slice direction
    # Column 2 (Z) of direction matrix = slice normal direction
    z_column = direction_matrix[:, 2]
    
    # Find which component has the largest absolute value
    abs_z = np.abs(z_column)
    dominant_axis = np.argmax(abs_z)
    
    # In LPS coordinate system:
    # X = Left-Right (dominant_axis=0 -> Sagittal)
    # Y = Anterior-Posterior (dominant_axis=1 -> Coronal)
    # Z = Superior-Inferior (dominant_axis=2 -> Axial)
    
    if dominant_axis == 0:
        return 'sagittal'
    elif dominant_axis == 1:
        return 'coronal'
    else:
        return 'axial'


def get_permutation_for_acquisition_plane(acquisition_plane):
    """
    Get the axis permutation needed to rearrange the image so that
    the acquisition plane becomes the Z-axis (for proper MPR display).
    
    Args:
        acquisition_plane: 'axial', 'sagittal', or 'coronal'
        
    Returns:
        tuple: (permutation for ZYX array, permutation for XYZ spacing/origin)
    """
    if acquisition_plane == 'axial':
        # Already correct, no permutation needed
        return None, None
    elif acquisition_plane == 'sagittal':
        # Sagittal: X is slice direction, need to swap X and Z
        # ZYX -> XYZ permutation: (2,1,0) means new_Z=old_X, new_Y=old_Y, new_X=old_Z
        return (2, 1, 0), (2, 1, 0)
    elif acquisition_plane == 'coronal':
        # Coronal: Y is slice direction, need to swap Y and Z
        # ZYX -> YXZ permutation: (1,0,2) means new_Z=old_Y, new_Y=old_X, new_X=old_Z
        return (1, 0, 2), (1, 0, 2)
    return None, None


def read_mhd_via_sitk_and_make_identity(path):
    """
    Read MHD file using SimpleITK and fix orientation for proper MPR display.
    
    This fixes orientation issues caused by vtkMetaImageReader ignoring
    the TransformMatrix/Orientation in MHD files.
    
    For non-axial acquisitions (sagittal/coronal), the image is permuted so that
    the acquisition plane is displayed correctly in MPR.
    
    Args:
        path: Path to the MHD file
    
    Returns:
        tuple: (numpy_array_zyx, spacing_xyz, origin_xyz)
            - numpy_array_zyx: 3D numpy array in Z,Y,X order
            - spacing_xyz: tuple of (sx, sy, sz) spacing
            - origin_xyz: tuple of (ox, oy, oz) origin
    """
    # Read image using SimpleITK
    img = sitk.ReadImage(path)
    
    # Extract metadata
    spacing = img.GetSpacing()  # (sx, sy, sz)
    origin = img.GetOrigin()    # (ox, oy, oz)
    direction = img.GetDirection()  # 9-tuple (row-major 3x3 matrix)
    
    # Check if direction is identity and detect acquisition plane
    direction_is_identity = is_direction_identity(direction)
    acquisition_plane = detect_acquisition_plane(direction)
    resampled = False
    permuted = False
    
    # Always log for debugging
    print(f"[MPR FIX DEBUG] MHD loaded via SimpleITK")
    print(f"[MPR FIX DEBUG] Original direction matrix: {direction}")
    print(f"[MPR FIX DEBUG] DirectionIdentity={direction_is_identity}")
    print(f"[MPR FIX DEBUG] Acquisition plane detected: {acquisition_plane}")
    print(f"[MPR FIX DEBUG] Original spacing: {spacing}")
    print(f"[MPR FIX DEBUG] Original origin: {origin}")
    
    if not direction_is_identity:
        # FAST PATH: Use permute/flip instead of slow resample
        # Analyze direction matrix to determine required permutation and flips
        direction_matrix = np.array(direction).reshape(3, 3)
        
        # Find which input axis maps to which output axis
        # For each output axis, find which input axis has the largest component
        axis_mapping = []
        flip_axes = []
        
        for out_axis in range(3):
            col = direction_matrix[:, out_axis]
            abs_col = np.abs(col)
            in_axis = np.argmax(abs_col)
            axis_mapping.append(in_axis)
            # Check if we need to flip (negative component)
            if col[in_axis] < 0:
                flip_axes.append(out_axis)
        
        print(f"[MPR FIX DEBUG] FAST permute/flip mode")
        print(f"[MPR FIX DEBUG] Axis mapping (out->in): {axis_mapping}")
        print(f"[MPR FIX DEBUG] Flip axes: {flip_axes}")
        
        # Convert to numpy array
        np_array = sitk.GetArrayFromImage(img)  # Z,Y,X order
        
        # Apply permutation if needed
        # SimpleITK uses X,Y,Z but numpy uses Z,Y,X, so we need to convert
        # axis_mapping is in X,Y,Z order, convert to Z,Y,X for numpy
        numpy_perm = [2 - axis_mapping[2], 2 - axis_mapping[1], 2 - axis_mapping[0]]
        
        if numpy_perm != [0, 1, 2]:
            print(f"[MPR FIX DEBUG] Applying numpy permutation: {numpy_perm}")
            np_array = np.transpose(np_array, numpy_perm)
        
        # Apply flips
        # flip_axes is in X,Y,Z order, convert to Z,Y,X for numpy
        for flip_axis in flip_axes:
            numpy_flip_axis = 2 - flip_axis
            print(f"[MPR FIX DEBUG] Flipping axis {flip_axis} (numpy axis {numpy_flip_axis})")
            np_array = np.flip(np_array, axis=numpy_flip_axis)
        
        # Permute spacing and origin
        spacing = tuple(spacing[i] for i in axis_mapping)
        origin = tuple(origin[i] for i in axis_mapping)
        
        print(f"[MPR FIX DEBUG] After permute: shape={np_array.shape}, spacing={spacing}, origin={origin}")
        
        resampled = True  # Using same flag name for compatibility
        print(f"[MPR FIX DEBUG] Fast permute/flip completed")
        print(f"[MPR FIX DEBUG] Numpy array shape (Z,Y,X): {np_array.shape}")
        print(f"[MPR FIX DEBUG] Numpy array dtype: {np_array.dtype}")
    else:
        # Identity direction - just convert to numpy
        np_array = sitk.GetArrayFromImage(img)
        print(f"[MPR FIX DEBUG] ResampledToIdentity=False")
        print(f"[MPR FIX DEBUG] Numpy array shape (Z,Y,X): {np_array.shape}")
        print(f"[MPR FIX DEBUG] Numpy array dtype: {np_array.dtype}")
    
    # If acquisition plane is not axial AND we did NOT resample, permute axes
    # so that the acquisition plane becomes the Z-axis (main scrolling axis in MPR)
    # Note: After resample to identity, the image is already in standard axial orientation
    zyx_perm, xyz_perm = get_permutation_for_acquisition_plane(acquisition_plane)
    if zyx_perm is not None and not resampled:
        print(f"[MPR FIX DEBUG] Permuting axes for {acquisition_plane} acquisition: ZYX perm={zyx_perm}")
        np_array = np.transpose(np_array, zyx_perm)
        
        # Also permute spacing and origin
        spacing_list = list(spacing)
        origin_list = list(origin)
        spacing = tuple(spacing_list[i] for i in xyz_perm)
        origin = tuple(origin_list[i] for i in xyz_perm)
        permuted = True
        print(f"[MPR FIX DEBUG] After permutation - shape: {np_array.shape}, spacing: {spacing}, origin: {origin}")
    elif zyx_perm is not None and resampled:
        print(f"[MPR FIX DEBUG] Skipping permutation (already resampled to identity)")
    
    # Flip X axis for radiological convention (LPS to display convention)
    # In radiology, patient's left should appear on the right side of the display
    np_array = np.flip(np_array, axis=2)  # axis=2 is X in Z,Y,X order
    
    # Adjust origin for X flip
    # New origin_x = original_origin_x + (nx - 1) * spacing_x
    nx = np_array.shape[2]
    new_origin_x = origin[0] + (nx - 1) * spacing[0]
    origin = (new_origin_x, origin[1], origin[2])
    
    # Make sure array is contiguous for VTK
    np_array = np.ascontiguousarray(np_array)
    
    print(f"[MPR FIX DEBUG] X-axis flipped for radiological convention")
    print(f"[MPR FIX DEBUG] New origin after X flip: {origin}")
    print(f"[MPR FIX DEBUG] Final array shape: {np_array.shape}")
    
    return np_array, spacing, origin


def numpy_to_vtk_image(np_zyx, spacing_xyz, origin_xyz):
    """
    Convert numpy array to vtkImageData.
    
    Args:
        np_zyx: 3D numpy array in Z,Y,X order
        spacing_xyz: tuple of (sx, sy, sz) spacing
        origin_xyz: tuple of (ox, oy, oz) origin
    
    Returns:
        vtkImageData object ready for VTK pipeline
    """
    # Get dimensions from numpy array shape (z, y, x)
    nz, ny, nx = np_zyx.shape
    
    # Create vtkImageData
    vtk_image = vtk.vtkImageData()
    vtk_image.SetDimensions(nx, ny, nz)
    vtk_image.SetSpacing(spacing_xyz[0], spacing_xyz[1], spacing_xyz[2])
    vtk_image.SetOrigin(origin_xyz[0], origin_xyz[1], origin_xyz[2])
    
    # Flatten the numpy array in Fortran order for VTK (x varies fastest)
    # VTK expects data in x-y-z order where x varies fastest
    np_flat = np_zyx.flatten(order='C')  # C order: z varies slowest, x varies fastest
    
    # Determine VTK scalar type based on numpy dtype
    if np_zyx.dtype == np.float32:
        vtk_type = vtk.VTK_FLOAT
    elif np_zyx.dtype == np.float64:
        vtk_type = vtk.VTK_DOUBLE
    elif np_zyx.dtype == np.int16:
        vtk_type = vtk.VTK_SHORT
    elif np_zyx.dtype == np.uint16:
        vtk_type = vtk.VTK_UNSIGNED_SHORT
    elif np_zyx.dtype == np.int32:
        vtk_type = vtk.VTK_INT
    elif np_zyx.dtype == np.uint32:
        vtk_type = vtk.VTK_UNSIGNED_INT
    elif np_zyx.dtype == np.int8:
        vtk_type = vtk.VTK_CHAR
    elif np_zyx.dtype == np.uint8:
        vtk_type = vtk.VTK_UNSIGNED_CHAR
    else:
        # Default to float for unknown types
        np_flat = np_flat.astype(np.float32)
        vtk_type = vtk.VTK_FLOAT
    
    # Convert numpy array to VTK array
    vtk_array = numpy_support.numpy_to_vtk(
        num_array=np_flat,
        deep=True,
        array_type=vtk_type
    )
    vtk_array.SetName("ImageScalars")
    
    # Set scalars on the image data
    vtk_image.GetPointData().SetScalars(vtk_array)
    
    return vtk_image

