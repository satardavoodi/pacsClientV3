"""
Debug script to diagnose Curved MPR issues

This will help identify where the problem is occurring.
"""

import numpy as np
import vtk
from PacsClient.pacs.patient_tab.viewers.curved_mpr import CurvedMPRGenerator


def create_simple_test_volume():
    """Create a simple test volume with known values"""
    dims = (100, 100, 100)
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(dims)
    image_data.SetSpacing(1.0, 1.0, 1.0)
    image_data.SetOrigin(0.0, 0.0, 0.0)
    image_data.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    scalars = image_data.GetPointData().GetScalars()
    
    # Fill entire volume with non-zero value (1000)
    for i in range(scalars.GetNumberOfTuples()):
        scalars.SetTuple1(i, 1000)
    
    # Create a bright sphere in the center
    center = np.array([50, 50, 50])
    radius = 15
    
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                pos = np.array([x, y, z])
                dist = np.linalg.norm(pos - center)
                
                if dist < radius:
                    idx = z * dims[0] * dims[1] + y * dims[0] + x
                    scalars.SetTuple1(idx, 3000)
    
    print(f"Created test volume: {dims}")
    print(f"  Filled with value 1000")
    print(f"  Bright sphere at center (50,50,50) with value 3000")
    
    return image_data


def test_3d_path():
    """Test with proper 3D path"""
    print("\n" + "="*60)
    print("TEST 1: Proper 3D Path (Different Z values)")
    print("="*60)
    
    volume = create_simple_test_volume()
    
    # Path through the sphere with DIFFERENT Z values
    points = [
        (30.0, 40.0, 40.0),  # Z=40
        (40.0, 45.0, 45.0),  # Z=45
        (50.0, 50.0, 50.0),  # Z=50 (center of sphere)
        (60.0, 55.0, 55.0),  # Z=55
        (70.0, 60.0, 60.0),  # Z=60
    ]
    
    print("\nControl points:")
    for i, pt in enumerate(points, 1):
        print(f"  {i}: ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    z_range = max(p[2] for p in points) - min(p[2] for p in points)
    print(f"\nZ range: {z_range:.1f}mm")
    
    # Generate CPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=80,
        slice_height=80,
        num_slices=30
    )
    
    # Check result
    dims = curved_mpr.GetDimensions()
    scalar_range = curved_mpr.GetScalarRange()
    
    print(f"\nResult:")
    print(f"  Dimensions: {dims}")
    print(f"  Scalar range: {scalar_range}")
    
    if scalar_range[1] > 0:
        print(f"  ✓ CPR has valid data!")
        return True
    else:
        print(f"  ✗ CPR is empty (all zeros)")
        return False


def test_coplanar_path():
    """Test with coplanar points (all same Z)"""
    print("\n" + "="*60)
    print("TEST 2: Coplanar Path (Same Z value) - EXPECTED TO FAIL")
    print("="*60)
    
    volume = create_simple_test_volume()
    
    # Path in XY plane only (all Z=50)
    points = [
        (30.0, 40.0, 50.0),  # Z=50
        (40.0, 45.0, 50.0),  # Z=50
        (50.0, 50.0, 50.0),  # Z=50 (same!)
        (60.0, 55.0, 50.0),  # Z=50
        (70.0, 60.0, 50.0),  # Z=50
    ]
    
    print("\nControl points (ALL Z=50):")
    for i, pt in enumerate(points, 1):
        print(f"  {i}: ({pt[0]:.1f}, {pt[1]:.1f}, {pt[2]:.1f})")
    
    z_range = max(p[2] for p in points) - min(p[2] for p in points)
    print(f"\nZ range: {z_range:.1f}mm  ← PROBLEM!")
    
    # Generate CPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(points)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=80,
        slice_height=80,
        num_slices=30
    )
    
    # Check result
    dims = curved_mpr.GetDimensions()
    scalar_range = curved_mpr.GetScalarRange()
    
    print(f"\nResult:")
    print(f"  Dimensions: {dims}")
    print(f"  Scalar range: {scalar_range}")
    
    if scalar_range[1] > 0:
        print(f"  ⚠️ Unexpected: CPR has data despite coplanar points")
        return True
    else:
        print(f"  ✗ CPR is empty - THIS IS EXPECTED with coplanar points")
        print(f"  → User must pick points on DIFFERENT slices!")
        return False


def test_single_slice_extraction():
    """Test extracting a single slice to debug reslicing"""
    print("\n" + "="*60)
    print("TEST 3: Single Slice Extraction Debug")
    print("="*60)
    
    volume = create_simple_test_volume()
    
    # Simple reslice test at center
    reslice = vtk.vtkImageReslice()
    reslice.SetInputData(volume)
    reslice.SetOutputDimensionality(2)
    reslice.SetInterpolationModeToLinear()
    
    # Identity orientation (should see XY plane at Z=50)
    reslice.SetResliceAxesDirectionCosines(
        1, 0, 0,  # X axis
        0, 1, 0,  # Y axis
        0, 0, 1   # Z axis (normal)
    )
    
    # Origin at center
    reslice.SetResliceAxesOrigin(50, 50, 50)
    
    # Extent
    reslice.SetOutputExtent(-25, 24, -25, 24, 0, 0)
    reslice.SetOutputSpacing(1.0, 1.0, 1.0)
    reslice.SetOutputOrigin(0.0, 0.0, 0.0)
    
    reslice.Update()
    
    output = reslice.GetOutput()
    scalar_range = output.GetScalarRange()
    
    print(f"\nSimple axial slice at (50,50,50):")
    print(f"  Range: {scalar_range}")
    
    if scalar_range[1] > 2500:
        print(f"  ✓ Contains bright sphere (value 3000)")
        return True
    elif scalar_range[1] > 900:
        print(f"  ✓ Contains background (value 1000)")
        return True
    else:
        print(f"  ✗ Empty slice - reslicing is broken!")
        return False


if __name__ == "__main__":
    print("="*60)
    print("CURVED MPR DEBUG DIAGNOSTICS")
    print("="*60)
    
    # Run tests
    result1 = test_3d_path()
    result2 = test_coplanar_path()
    result3 = test_single_slice_extraction()
    
    print("\n" + "="*60)
    print("DIAGNOSTIC SUMMARY")
    print("="*60)
    print(f"  3D path test: {'✓ PASS' if result1 else '✗ FAIL'}")
    print(f"  Coplanar test: {'✓ Expected behavior' if not result2 else '⚠️ Unexpected'}")
    print(f"  Basic reslice: {'✓ PASS' if result3 else '✗ FAIL - VTK issue'}")
    
    print("\n" + "="*60)
    if result1 and result3:
        print("✓ CPR WORKS with proper 3D paths!")
        print("  → Use points on DIFFERENT slices (vary Z coordinate)")
    else:
        print("✗ FUNDAMENTAL ISSUE in reslicing")
    print("="*60)

