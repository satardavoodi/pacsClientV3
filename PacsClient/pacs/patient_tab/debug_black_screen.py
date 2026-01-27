# -*- coding: utf-8 -*-
"""
Debug tool for black screen in Curved MPR output
"""

import numpy as np
import vtk
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(current_dir, 'viewers'))

from curved_mpr import CurvedMPRGenerator


def check_image_data(image_data, name="Image"):
    """Comprehensive check of vtkImageData"""
    print(f"\n{'='*60}")
    print(f"Checking: {name}")
    print(f"{'='*60}")
    
    if image_data is None:
        print("[ERROR] Image is None!")
        return False
    
    # Dimensions
    dims = image_data.GetDimensions()
    print(f"Dimensions: {dims[0]} x {dims[1]} x {dims[2]}")
    
    total_voxels = dims[0] * dims[1] * dims[2]
    print(f"Total voxels: {total_voxels:,}")
    
    if total_voxels == 0:
        print("[ERROR] Zero voxels!")
        return False
    
    # Spacing
    spacing = image_data.GetSpacing()
    print(f"Spacing: {spacing}")
    
    # Origin
    origin = image_data.GetOrigin()
    print(f"Origin: {origin}")
    
    # Scalar type
    scalar_type = image_data.GetScalarType()
    type_names = {
        vtk.VTK_CHAR: "CHAR",
        vtk.VTK_UNSIGNED_CHAR: "UNSIGNED_CHAR",
        vtk.VTK_SHORT: "SHORT",
        vtk.VTK_UNSIGNED_SHORT: "UNSIGNED_SHORT",
        vtk.VTK_INT: "INT",
        vtk.VTK_UNSIGNED_INT: "UNSIGNED_INT",
        vtk.VTK_FLOAT: "FLOAT",
        vtk.VTK_DOUBLE: "DOUBLE"
    }
    type_name = type_names.get(scalar_type, f"Unknown({scalar_type})")
    print(f"Scalar type: {type_name}")
    
    # Scalars
    scalars = image_data.GetPointData().GetScalars()
    if scalars is None:
        print("[ERROR] No scalars!")
        return False
    
    num_tuples = scalars.GetNumberOfTuples()
    print(f"Number of scalar tuples: {num_tuples:,}")
    
    if num_tuples == 0:
        print("[ERROR] Zero scalar tuples!")
        return False
    
    # Scalar range
    scalar_range = image_data.GetScalarRange()
    print(f"Scalar range: [{scalar_range[0]:.2f}, {scalar_range[1]:.2f}]")
    
    if scalar_range[0] == 0 and scalar_range[1] == 0:
        print("[WARNING] All values are zero - IMAGE IS BLACK!")
        return False
    
    # Sample values
    print(f"\nSample values (first 10):")
    for i in range(min(10, num_tuples)):
        val = scalars.GetTuple1(i)
        print(f"  [{i}] = {val:.2f}")
    
    # Statistics
    from vtkmodules.util import numpy_support
    np_array = numpy_support.vtk_to_numpy(scalars)
    
    print(f"\nStatistics:")
    print(f"  Mean: {np.mean(np_array):.2f}")
    print(f"  Std: {np.std(np_array):.2f}")
    print(f"  Min: {np.min(np_array):.2f}")
    print(f"  Max: {np.max(np_array):.2f}")
    print(f"  Non-zero count: {np.count_nonzero(np_array):,} / {np_array.size:,}")
    
    non_zero_ratio = np.count_nonzero(np_array) / np_array.size
    print(f"  Non-zero ratio: {non_zero_ratio*100:.1f}%")
    
    if non_zero_ratio < 0.01:
        print(f"[WARNING] Less than 1% non-zero - mostly black!")
    
    print(f"\n[OK] Image appears valid")
    return True


def test_with_debug():
    """Test curved MPR with full debugging"""
    print("="*60)
    print("CURVED MPR BLACK SCREEN DEBUG")
    print("="*60)
    
    # Create test volume
    print("\n[1] Creating test volume...")
    dims = (100, 100, 100)
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(dims)
    image_data.SetSpacing(1.0, 1.0, 1.0)
    image_data.SetOrigin(0.0, 0.0, 0.0)
    image_data.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    scalars = image_data.GetPointData().GetScalars()
    
    # Fill with gradient + sphere
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                # Base value (gradient)
                base = 200 + (z * 10)
                
                # Add bright sphere
                center = np.array([50, 50, 50])
                pos = np.array([x, y, z])
                dist = np.linalg.norm(pos - center)
                
                if dist < 20:
                    value = int(3000 * (1.0 - dist / 20))
                else:
                    value = base
                
                idx = z * dims[0] * dims[1] + y * dims[0] + x
                scalars.SetTuple1(idx, value)
    
    check_image_data(image_data, "Input Volume")
    
    # Create path
    print("\n[2] Creating 3D path...")
    points = [
        (30.0, 40.0, 35.0),
        (40.0, 45.0, 42.0),
        (50.0, 50.0, 50.0),
        (60.0, 55.0, 58.0),
        (70.0, 60.0, 65.0),
    ]
    
    for i, pt in enumerate(points, 1):
        print(f"  Point {i}: ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    # Generate CPR
    print("\n[3] Generating Curved MPR...")
    generator = CurvedMPRGenerator(image_data)
    generator.set_centerline(points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=60,
        slice_height=60,
        num_slices=40
    )
    
    # Check output
    print("\n[4] Checking output...")
    is_valid = check_image_data(curved_mpr, "Curved MPR Output")
    
    if is_valid:
        print("\n" + "="*60)
        print("[SUCCESS] Curved MPR has valid data!")
        print("="*60)
        
        # Display instructions
        print("\nTo display this image:")
        print("1. Use vtkImageViewer2")
        print("2. Set proper Window/Level:")
        scalar_range = curved_mpr.GetScalarRange()
        window = scalar_range[1] - scalar_range[0]
        level = (scalar_range[1] + scalar_range[0]) / 2.0
        print(f"   Window: {window:.0f}")
        print(f"   Level: {level:.0f}")
        print("3. Set correct slice (middle slice recommended):")
        mid_slice = curved_mpr.GetDimensions()[2] // 2
        print(f"   Slice: {mid_slice} (of {curved_mpr.GetDimensions()[2]})")
        
        return True
    else:
        print("\n" + "="*60)
        print("[FAILURE] Curved MPR is black/invalid!")
        print("="*60)
        return False


if __name__ == "__main__":
    test_with_debug()

