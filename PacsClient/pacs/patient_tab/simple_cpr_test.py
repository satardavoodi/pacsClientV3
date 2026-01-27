# -*- coding: utf-8 -*-
"""
Simple Curved MPR Test
"""

import numpy as np
import vtk
import sys
import os

# Add path
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(current_dir, 'viewers'))

from curved_mpr import CurvedMPRGenerator


def create_test_volume():
    """Create simple test volume with a bright sphere"""
    dims = (100, 100, 100)
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(dims)
    image_data.SetSpacing(1.0, 1.0, 1.0)
    image_data.SetOrigin(0.0, 0.0, 0.0)
    image_data.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    scalars = image_data.GetPointData().GetScalars()
    
    # Fill with background
    for i in range(scalars.GetNumberOfTuples()):
        scalars.SetTuple1(i, 100)
    
    # Create bright sphere at center
    center = np.array([50, 50, 50])
    radius = 20
    
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                pos = np.array([x, y, z])
                dist = np.linalg.norm(pos - center)
                
                if dist <= radius:
                    idx = z * dims[0] * dims[1] + y * dims[0] + x
                    value = int(3000 * (1.0 - dist / radius))
                    scalars.SetTuple1(idx, max(100, value))
    
    print("[TEST] Created volume: 100x100x100")
    print("[TEST] Bright sphere at (50,50,50) with radius 20")
    return image_data


def test_3d_path():
    """Test with proper 3D path through sphere"""
    print("\n" + "="*60)
    print("TEST 1: Proper 3D Path (varying Z)")
    print("="*60)
    
    volume = create_test_volume()
    
    # Path through sphere with DIFFERENT Z values
    points = [
        (30.0, 40.0, 35.0),   # Z=35
        (40.0, 45.0, 42.0),   # Z=42
        (50.0, 50.0, 50.0),   # Z=50 (center)
        (60.0, 55.0, 58.0),   # Z=58
        (70.0, 60.0, 65.0),   # Z=65
    ]
    
    print("\nControl points:")
    for i, pt in enumerate(points, 1):
        print(f"  {i}. ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    z_range = max(p[2] for p in points) - min(p[2] for p in points)
    print(f"\nZ range: {z_range:.1f}mm [GOOD]")
    
    # Generate CPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=60,
        slice_height=60,
        num_slices=40
    )
    
    # Check result
    dims = curved_mpr.GetDimensions()
    scalar_range = curved_mpr.GetScalarRange()
    
    print(f"\nResult:")
    print(f"  Dimensions: {dims[0]} x {dims[1]} x {dims[2]}")
    print(f"  Scalar range: [{scalar_range[0]:.0f}, {scalar_range[1]:.0f}]")
    
    success = scalar_range[1] > 1000
    
    if success:
        print(f"\n[PASS] CPR has valid data!")
        print(f"  Max value = {scalar_range[1]:.0f} (should be ~3000)")
        return True
    else:
        print(f"\n[FAIL] CPR is empty!")
        print(f"  Max value = {scalar_range[1]:.0f} (too low!)")
        return False


def test_coplanar_path():
    """Test with coplanar points (same Z)"""
    print("\n" + "="*60)
    print("TEST 2: Coplanar Path (same Z) - EXPECTED TO FAIL")
    print("="*60)
    
    volume = create_test_volume()
    
    # All points at Z=50
    points = [
        (30.0, 40.0, 50.0),   # Z=50
        (40.0, 45.0, 50.0),   # Z=50
        (50.0, 50.0, 50.0),   # Z=50
        (60.0, 55.0, 50.0),   # Z=50
        (70.0, 60.0, 50.0),   # Z=50
    ]
    
    print("\nControl points (all Z=50):")
    for i, pt in enumerate(points, 1):
        print(f"  {i}. ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    z_range = max(p[2] for p in points) - min(p[2] for p in points)
    print(f"\nZ range: {z_range:.1f}mm [PROBLEM!]")
    
    # Generate CPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=60,
        slice_height=60,
        num_slices=40
    )
    
    # Check result
    dims = curved_mpr.GetDimensions()
    scalar_range = curved_mpr.GetScalarRange()
    
    print(f"\nResult:")
    print(f"  Dimensions: {dims[0]} x {dims[1]} x {dims[2]}")
    print(f"  Scalar range: [{scalar_range[0]:.0f}, {scalar_range[1]:.0f}]")
    
    has_data = scalar_range[1] > 500
    
    if has_data:
        print(f"\n[UNEXPECTED] CPR has data despite coplanar points")
    else:
        print(f"\n[EXPECTED] CPR is empty - coplanar points detected")
        print(f"  --> SOLUTION: Pick points on DIFFERENT slices!")
    
    return not has_data


def main():
    print("="*60)
    print("Curved MPR OutputOrigin Fix Test")
    print("="*60)
    
    results = {}
    
    try:
        results['3D Path'] = test_3d_path()
    except Exception as e:
        print(f"\n[ERROR] in 3D Path test: {e}")
        import traceback
        traceback.print_exc()
        results['3D Path'] = False
    
    try:
        results['Coplanar'] = test_coplanar_path()
    except Exception as e:
        print(f"\n[ERROR] in Coplanar test: {e}")
        import traceback
        traceback.print_exc()
        results['Coplanar'] = False
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"  {test_name:20s}: {status}")
    
    print("\n" + "="*60)
    
    if results.get('3D Path'):
        print("[SUCCESS] CPR works with proper 3D paths!")
        print("  --> Users must pick points on DIFFERENT slices (vary Z)")
    else:
        print("[FAILURE] CPR still has issues!")
        print("  --> Further debugging needed")
    
    print("="*60)


if __name__ == "__main__":
    main()

