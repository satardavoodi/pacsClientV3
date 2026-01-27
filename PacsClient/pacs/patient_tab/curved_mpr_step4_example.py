"""
Curved MPR Module - Step 4 Example: Real Curved MPR Generation

This example demonstrates the new CurvedMPRGenerator class that creates
actual curved MPR images from control points and a volume.

New in Step 4:
--------------
- CurvedMPRGenerator class for true CPR computation
- Spline interpolation using vtkParametricSpline
- Orthonormal frame computation (T, N, B)
- Perpendicular plane extraction with vtkImageReslice
- Straightened reformation image generation
"""

import vtk
import numpy as np
from PacsClient.pacs.patient_tab.curved_mpr_module import CurvedMPRModule, CurvedMPRGenerator


def create_test_volume(dims=(100, 100, 100)):
    """Create a simple test volume with a diagonal gradient"""
    image_data = vtk.vtkImageData()
    image_data.SetDimensions(dims)
    image_data.SetSpacing(1.0, 1.0, 1.0)
    image_data.SetOrigin(0.0, 0.0, 0.0)
    image_data.AllocateScalars(vtk.VTK_UNSIGNED_SHORT, 1)
    
    # Fill with gradient pattern
    scalars = image_data.GetPointData().GetScalars()
    for z in range(dims[2]):
        for y in range(dims[1]):
            for x in range(dims[0]):
                idx = z * dims[0] * dims[1] + y * dims[0] + x
                # Diagonal gradient
                value = int((x + y + z) / 3.0 * 655.35)
                scalars.SetTuple1(idx, value)
    
    return image_data


def example_basic_generator():
    """Basic example of CurvedMPRGenerator usage"""
    print("=" * 60)
    print("Example 1: Basic CurvedMPRGenerator Usage")
    print("=" * 60)
    
    # Create test volume
    volume = create_test_volume()
    print(f"Created test volume: {volume.GetDimensions()}")
    
    # Define control points (curved path through volume)
    control_points = [
        (10.0, 20.0, 30.0),
        (25.0, 40.0, 35.0),
        (40.0, 60.0, 40.0),
        (60.0, 70.0, 50.0),
        (80.0, 75.0, 60.0),
    ]
    print(f"\nControl points: {len(control_points)} points")
    for i, pt in enumerate(control_points, 1):
        print(f"  Point {i}: {pt}")
    
    # Create generator
    print("\nCreating CurvedMPRGenerator...")
    generator = CurvedMPRGenerator(
        volume=volume,
        control_points=control_points,
        num_samples=150,
        slice_width=80,
        slice_height=80
    )
    
    # Generate curved MPR
    print("\nGenerating curved MPR image...")
    curved_mpr = generator.generate()
    
    print(f"\n✓ Curved MPR generated successfully!")
    print(f"  Output dimensions: {curved_mpr.GetDimensions()}")
    print(f"  Output spacing: {curved_mpr.GetSpacing()}")
    print(f"  Scalar range: {curved_mpr.GetScalarRange()}")
    
    return curved_mpr


def example_module_integration():
    """Example showing integration with CurvedMPRModule"""
    print("\n" + "=" * 60)
    print("Example 2: Module Integration")
    print("=" * 60)
    
    # Create module and volume
    module = CurvedMPRModule()
    volume = create_test_volume()
    
    # Start curved MPR mode
    print("\nStarting curved MPR mode...")
    module.start_curved_mpr(volume)
    
    # Simulate user adding points
    points = [
        (15.0, 15.0, 20.0),
        (30.0, 35.0, 30.0),
        (50.0, 55.0, 45.0),
        (70.0, 70.0, 65.0),
    ]
    
    print(f"\nAdding {len(points)} points...")
    for i, pt in enumerate(points, 1):
        module.add_point_world(pt)
        print(f"  Point {i} added: {pt}")
    
    # Generate curved MPR using the module
    print("\nGenerating curved MPR via module...")
    curved_mpr = module.generate_curved_mpr(
        num_samples=200,
        slice_width=100,
        slice_height=100
    )
    
    if curved_mpr:
        print(f"\n✓ Module generated curved MPR!")
        print(f"  Dimensions: {curved_mpr.GetDimensions()}")
        print(f"  Points used: {module.get_point_count()}")
    else:
        print("✗ Failed to generate curved MPR")
    
    return curved_mpr


def example_spline_visualization():
    """Example showing spline and tangent computation"""
    print("\n" + "=" * 60)
    print("Example 3: Spline and Tangent Visualization")
    print("=" * 60)
    
    volume = create_test_volume()
    
    control_points = [
        (20.0, 20.0, 20.0),
        (40.0, 50.0, 30.0),
        (60.0, 60.0, 50.0),
    ]
    
    print(f"\nControl points: {control_points}")
    
    generator = CurvedMPRGenerator(
        volume=volume,
        control_points=control_points,
        num_samples=10  # Fewer samples for visualization
    )
    
    print(f"\nSpline sampling:")
    print(f"  Num samples: {len(generator.spline_points)}")
    print(f"\nFirst 5 sampled points and tangents:")
    for i in range(min(5, len(generator.spline_points))):
        pos = generator.spline_points[i]
        tan = generator.tangents[i]
        print(f"  {i}: Pos=({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f}), "
              f"Tangent=({tan[0]:.3f}, {tan[1]:.3f}, {tan[2]:.3f})")


def example_orthonormal_frames():
    """Example showing orthonormal frame computation"""
    print("\n" + "=" * 60)
    print("Example 4: Orthonormal Frame Computation")
    print("=" * 60)
    
    volume = create_test_volume()
    
    control_points = [
        (25.0, 25.0, 25.0),
        (50.0, 50.0, 50.0),
        (75.0, 75.0, 75.0),
    ]
    
    generator = CurvedMPRGenerator(
        volume=volume,
        control_points=control_points,
        num_samples=5
    )
    
    print("\nOrthonormal frames at sample points:")
    for i in range(len(generator.tangents)):
        tangent = generator.tangents[i]
        T, N, B = generator._compute_orthonormal_frame(tangent)
        
        print(f"\nSample {i}:")
        print(f"  T (tangent):  ({T[0]:.3f}, {T[1]:.3f}, {T[2]:.3f})")
        print(f"  N (normal):   ({N[0]:.3f}, {N[1]:.3f}, {N[2]:.3f})")
        print(f"  B (binormal): ({B[0]:.3f}, {B[1]:.3f}, {B[2]:.3f})")
        
        # Verify orthonormality
        dot_TN = np.dot(T, N)
        dot_TB = np.dot(T, B)
        dot_NB = np.dot(N, B)
        
        print(f"  Orthogonality check:")
        print(f"    T·N = {dot_TN:.6f} (should be ~0)")
        print(f"    T·B = {dot_TB:.6f} (should be ~0)")
        print(f"    N·B = {dot_NB:.6f} (should be ~0)")


def example_performance_metrics():
    """Example showing performance characteristics"""
    print("\n" + "=" * 60)
    print("Example 5: Performance Metrics")
    print("=" * 60)
    
    import time
    
    volume = create_test_volume(dims=(150, 150, 150))
    
    control_points = [
        (20.0, 20.0, 20.0),
        (50.0, 60.0, 40.0),
        (80.0, 100.0, 70.0),
        (120.0, 130.0, 110.0),
    ]
    
    configs = [
        (50, 50, 50),
        (100, 80, 80),
        (200, 100, 100),
    ]
    
    print("\nTesting different configurations:")
    for num_samples, width, height in configs:
        print(f"\n  Config: {num_samples} samples, {width}x{height} slice")
        
        start = time.time()
        generator = CurvedMPRGenerator(
            volume=volume,
            control_points=control_points,
            num_samples=num_samples,
            slice_width=width,
            slice_height=height
        )
        curved_mpr = generator.generate()
        elapsed = time.time() - start
        
        dims = curved_mpr.GetDimensions()
        print(f"    Output: {dims[0]}x{dims[1]} pixels")
        print(f"    Time: {elapsed:.3f} seconds")
        print(f"    Rate: {num_samples/elapsed:.1f} slices/sec")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("Curved MPR Module - Step 4 Examples")
    print("Real Curved MPR Image Generation")
    print("=" * 60 + "\n")
    
    # Run examples
    example_basic_generator()
    example_module_integration()
    example_spline_visualization()
    example_orthonormal_frames()
    example_performance_metrics()
    
    print("\n" + "=" * 60)
    print("All Step 4 examples completed successfully! ✓")
    print("=" * 60 + "\n")

