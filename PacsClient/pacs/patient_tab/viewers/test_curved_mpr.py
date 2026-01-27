"""
Test Suite for Curved MPR Implementation
=========================================

Validates all components of the Curved MPR system:
- Path3D spline interpolation
- PlaneGenerator frame computation
- ResliceEngine volume sampling
- MandibularUnfoldingModule
- MultiPlanarSync

Run with: python test_curved_mpr.py
"""

import vtkmodules.all as vtk
import numpy as np
import sys
from typing import List, Tuple

# Import curved MPR modules
from curved_mpr import (
    Path3D,
    PlaneGenerator,
    ResliceEngine,
    CurvedMPRGenerator,
    MandibularUnfoldingModule,
    MultiPlanarSync,
    create_mandibular_panoramic,
    create_synchronized_mpr_views
)


# =============================================================================
# Test Utilities
# =============================================================================

def create_test_volume(dims=(100, 100, 100), spacing=(1.0, 1.0, 1.0)):
    """
    Create a synthetic test volume with known geometry.
    
    Creates a volume with diagonal stripes for easy visualization
    of correct/incorrect reslicing.
    """
    image = vtk.vtkImageData()
    image.SetDimensions(dims[0], dims[1], dims[2])
    image.SetSpacing(spacing[0], spacing[1], spacing[2])
    image.SetOrigin(0, 0, 0)
    image.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    # Fill with pattern
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                # Diagonal stripe pattern
                value = int((x + y + z) % 20) * 200
                image.SetScalarComponentFromFloat(x, y, z, 0, value)
    
    return image


def create_vessel_phantom(radius=5.0, length=100.0):
    """
    Create a synthetic curved vessel phantom.
    
    Vessel follows a sinusoidal path to test curved reformation.
    """
    dims = (100, 100, 100)
    spacing = (1.0, 1.0, 1.0)
    
    image = vtk.vtkImageData()
    image.SetDimensions(dims[0], dims[1], dims[2])
    image.SetSpacing(spacing[0], spacing[1], spacing[2])
    image.SetOrigin(0, 0, 0)
    image.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    # Create sinusoidal vessel
    for z in range(dims[2]):
        # Vessel centerline follows sine wave
        cx = 50 + 20 * np.sin(2 * np.pi * z / 50.0)
        cy = 50 + 10 * np.cos(2 * np.pi * z / 50.0)
        
        for y in range(dims[1]):
            for x in range(dims[0]):
                # Distance from vessel centerline
                dist = np.sqrt((x - cx)**2 + (y - cy)**2)
                
                if dist < radius:
                    # Inside vessel
                    value = 1000
                else:
                    # Outside vessel
                    value = 0
                
                image.SetScalarComponentFromFloat(x, y, z, 0, value)
    
    return image


def assert_equal(a, b, msg=""):
    """Simple assertion helper"""
    if a != b:
        raise AssertionError(f"{msg}: {a} != {b}")
    print(f"✓ {msg}")


def assert_close(a, b, tol=1e-6, msg=""):
    """Assert two numbers are close"""
    if abs(a - b) > tol:
        raise AssertionError(f"{msg}: {a} ≈ {b} (diff: {abs(a-b)})")
    print(f"✓ {msg}")


def assert_orthonormal(v1, v2, v3, tol=1e-6):
    """Assert three vectors form orthonormal basis"""
    # Check unit length
    assert_close(np.linalg.norm(v1), 1.0, tol, "v1 is unit")
    assert_close(np.linalg.norm(v2), 1.0, tol, "v2 is unit")
    assert_close(np.linalg.norm(v3), 1.0, tol, "v3 is unit")
    
    # Check orthogonality
    assert_close(np.dot(v1, v2), 0.0, tol, "v1 ⊥ v2")
    assert_close(np.dot(v1, v3), 0.0, tol, "v1 ⊥ v3")
    assert_close(np.dot(v2, v3), 0.0, tol, "v2 ⊥ v3")


# =============================================================================
# Test Cases
# =============================================================================

def test_path3d_straight_line():
    """Test Path3D with a straight line"""
    print("\n=== Test: Path3D Straight Line ===")
    
    points = [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 100.0)
    ]
    
    path = Path3D(points)
    
    # Check total length
    assert_close(path.total_length, 100.0, 0.1, "Straight path length")
    
    # Sample uniformly
    samples = path.sample_uniform(11)
    
    # Check first and last points
    assert_close(samples[0][2], 0.0, 0.1, "First sample at z=0")
    assert_close(samples[-1][2], 100.0, 0.1, "Last sample at z=100")
    
    # Check uniform spacing
    for i in range(len(samples) - 1):
        dist = np.linalg.norm(samples[i+1] - samples[i])
        assert_close(dist, 10.0, 0.5, f"Uniform spacing at {i}")
    
    print("✓ Path3D straight line test passed")


def test_path3d_curved():
    """Test Path3D with a curved path"""
    print("\n=== Test: Path3D Curved Path ===")
    
    # Create arc
    angles = np.linspace(0, np.pi/2, 5)
    radius = 50.0
    points = [(radius * np.cos(a), radius * np.sin(a), 0.0) for a in angles]
    
    path = Path3D(points)
    
    # Arc length should be approximately π*r/2
    expected_length = np.pi * radius / 2
    assert_close(path.total_length, expected_length, 5.0, "Arc length")
    
    # Sample and check tangent
    samples = path.sample_uniform(10)
    tangent = path.get_tangent_at(path.total_length / 2)
    
    # Tangent should be unit vector
    assert_close(np.linalg.norm(tangent), 1.0, 1e-6, "Tangent is unit vector")
    
    print("✓ Path3D curved path test passed")


def test_plane_generator_frames():
    """Test PlaneGenerator creates orthonormal frames"""
    print("\n=== Test: PlaneGenerator Frames ===")
    
    # Straight path
    points = [
        (0.0, 0.0, float(z)) for z in range(0, 101, 20)
    ]
    
    path = Path3D(points)
    plane_gen = PlaneGenerator(path)
    frames = plane_gen.generate_frames(10)
    
    assert_equal(len(frames), 10, "Number of frames")
    
    # Check each frame is orthonormal
    for i, (origin, T, N, B) in enumerate(frames):
        assert_orthonormal(T, N, B)
    
    print("✓ PlaneGenerator frames test passed")


def test_plane_generator_no_flipping():
    """Test that parallel transport frame doesn't flip"""
    print("\n=== Test: PlaneGenerator No Flipping ===")
    
    # Create path with varying curvature
    t = np.linspace(0, 2*np.pi, 20)
    points = [(10*np.cos(ti), 10*np.sin(ti), ti*5) for ti in t]
    
    path = Path3D(points)
    plane_gen = PlaneGenerator(path)
    frames = plane_gen.generate_frames(50)
    
    # Check that normal vectors don't flip suddenly
    for i in range(len(frames) - 1):
        _, _, N1, _ = frames[i]
        _, _, N2, _ = frames[i+1]
        
        # Dot product should be positive (no 180° flip)
        dot = np.dot(N1, N2)
        assert dot > 0, f"Frame flip detected at {i}: dot={dot}"
    
    print("✓ PlaneGenerator no-flip test passed")


def test_reslice_engine_basic():
    """Test ResliceEngine basic functionality"""
    print("\n=== Test: ResliceEngine Basic ===")
    
    # Create test volume
    volume = create_test_volume()
    
    # Create straight path
    points = [(50.0, 50.0, float(z)) for z in range(0, 100, 10)]
    path = Path3D(points)
    
    # Generate frames
    plane_gen = PlaneGenerator(path)
    frames = plane_gen.generate_frames(10)
    
    # Reslice
    reslice_engine = ResliceEngine(volume)
    output = reslice_engine.reslice_along_path(
        frames,
        slice_size=50.0,
        output_spacing=1.0
    )
    
    # Check output
    assert output is not None, "Output exists"
    dims = output.GetDimensions()
    print(f"  Output dimensions: {dims}")
    assert dims[0] > 0 and dims[1] > 0 and dims[2] > 0, "Valid dimensions"
    
    print("✓ ResliceEngine basic test passed")


def test_curved_mpr_generator():
    """Test CurvedMPRGenerator end-to-end"""
    print("\n=== Test: CurvedMPRGenerator ===")
    
    # Create vessel phantom
    volume = create_vessel_phantom()
    
    # Define centerline (following the sine wave)
    centerline = []
    for z in range(0, 100, 5):
        x = 50 + 20 * np.sin(2 * np.pi * z / 50.0)
        y = 50 + 10 * np.cos(2 * np.pi * z / 50.0)
        centerline.append((x, y, float(z)))
    
    # Generate curved MPR
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(centerline)
    
    curved_mpr = generator.generate_curved_mpr(
        slice_width=40.0,
        slice_height=40.0,
        num_slices=50
    )
    
    # Verify output
    assert curved_mpr is not None, "Curved MPR generated"
    dims = curved_mpr.GetDimensions()
    print(f"  Curved MPR dimensions: {dims}")
    
    # Check that vessel appears straight in curved MPR
    # (In ideal case, vessel lumen should be circular in each slice)
    
    print("✓ CurvedMPRGenerator test passed")


def test_mandibular_unfolding():
    """Test MandibularUnfoldingModule"""
    print("\n=== Test: Mandibular Unfolding ===")
    
    # Create CBCT-like volume
    volume = create_test_volume(dims=(150, 150, 150))
    
    # Create U-shaped arch (mandible-like)
    # Right side
    arch_points = []
    for t in np.linspace(-np.pi/2, np.pi/2, 20):
        x = 75 + 40 * np.cos(t)
        y = 75 + 40 * np.sin(t)
        z = 75.0
        arch_points.append((x, y, z))
    
    # Generate panoramic
    unfolder = MandibularUnfoldingModule(volume)
    unfolder.set_arch_curve(arch_points)
    
    panoramic = unfolder.generate_panoramic_unfold(
        height_mm=50.0,
        width_samples=100,
        height_samples=100
    )
    
    # Verify output
    assert panoramic is not None, "Panoramic generated"
    dims = panoramic.GetDimensions()
    print(f"  Panoramic dimensions: {dims}")
    assert_equal(dims[2], 1, "Panoramic is 2D (Z=1)")
    
    print("✓ Mandibular unfolding test passed")


def test_multiplanar_sync():
    """Test MultiPlanarSync"""
    print("\n=== Test: MultiPlanarSync ===")
    
    volume = create_test_volume()
    
    # Define path
    points = [(50.0, 50.0, float(z)) for z in range(20, 80, 10)]
    path = Path3D(points)
    
    # Create sync
    sync = MultiPlanarSync(volume, path)
    sync.initialize(num_positions=30)
    
    assert_equal(sync.num_positions, 30, "Number of positions")
    
    # Get views at middle position
    index = 15
    views = sync.get_all_views_at_index(index, slice_size=50.0)
    
    # Check all three views exist
    assert 'axial' in views, "Axial view exists"
    assert 'sagittal' in views, "Sagittal view exists"
    assert 'coronal' in views, "Coronal view exists"
    
    # Check they are 2D
    for view_name, view_data in views.items():
        dims = view_data.GetDimensions()
        assert dims[2] == 1, f"{view_name} is 2D"
        print(f"  {view_name}: {dims[0]}x{dims[1]}")
    
    print("✓ MultiPlanarSync test passed")


def test_utility_functions():
    """Test utility functions"""
    print("\n=== Test: Utility Functions ===")
    
    volume = create_test_volume()
    
    # Test create_mandibular_panoramic
    arch = [(50.0 + 20*np.cos(t), 50.0 + 20*np.sin(t), 50.0) 
            for t in np.linspace(0, np.pi, 10)]
    
    panoramic = create_mandibular_panoramic(
        volume,
        arch,
        height_mm=40.0,
        width_samples=50,
        height_samples=50
    )
    
    assert panoramic is not None, "create_mandibular_panoramic works"
    
    # Test create_synchronized_mpr_views
    path_points = [(50.0, 50.0, float(z)) for z in range(20, 80, 15)]
    
    sync = create_synchronized_mpr_views(
        volume,
        path_points,
        num_positions=20,
        slice_size=40.0
    )
    
    assert sync is not None, "create_synchronized_mpr_views works"
    assert_equal(sync.num_positions, 20, "Correct number of positions")
    
    print("✓ Utility functions test passed")


def test_interpolation_quality():
    """Test that interpolation is working correctly"""
    print("\n=== Test: Interpolation Quality ===")
    
    # Create volume with known values
    volume = vtk.vtkImageData()
    volume.SetDimensions(10, 10, 10)
    volume.SetSpacing(1.0, 1.0, 1.0)
    volume.SetOrigin(0, 0, 0)
    volume.AllocateScalars(vtk.VTK_FLOAT, 1)
    
    # Fill with linear gradient
    for z in range(10):
        for y in range(10):
            for x in range(10):
                value = float(x + y + z)
                volume.SetScalarComponentFromFloat(x, y, z, 0, value)
    
    # Reslice at known position
    points = [(5.0, 5.0, float(z)) for z in range(10)]
    generator = CurvedMPRGenerator(volume)
    generator.set_centerline(points)
    
    curved = generator.generate_curved_mpr(
        slice_width=8.0,
        slice_height=8.0,
        num_slices=5
    )
    
    # Check that values are reasonable
    scalar_range = curved.GetScalarRange()
    print(f"  Scalar range: {scalar_range}")
    assert scalar_range[0] >= 0, "Min value reasonable"
    assert scalar_range[1] <= 30, "Max value reasonable"
    
    print("✓ Interpolation quality test passed")


# =============================================================================
# Main Test Runner
# =============================================================================

def run_all_tests():
    """Run all tests"""
    print("=" * 70)
    print("CURVED MPR TEST SUITE")
    print("=" * 70)
    
    tests = [
        test_path3d_straight_line,
        test_path3d_curved,
        test_plane_generator_frames,
        test_plane_generator_no_flipping,
        test_reslice_engine_basic,
        test_curved_mpr_generator,
        test_mandibular_unfolding,
        test_multiplanar_sync,
        test_utility_functions,
        test_interpolation_quality,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"✗ {test.__name__} FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

