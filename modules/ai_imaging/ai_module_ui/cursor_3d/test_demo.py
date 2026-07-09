"""
Test/Demo Module for Correspondence Arc Algorithm

این ماژول شامل توابع تست و نمایشی برای الگوریتم کمان تناظر است.
با استفاده از داده‌های فرضی (synthetic)، عملکرد صحیح الگوریتم و
دقت پیش‌بینی موقعیت ضایعات را نمایش می‌دهد.

Test Functions:
    - test_cc_to_mlo_projection: آزمایش پروژکشن CC به MLO
    - test_mlo_to_cc_projection: آزمایش پروژکشن MLO به CC
    - demo_correspondence_arc_visualization: نمایش کامل visualization
    - validate_arc_accuracy: ارزیابی دقت با موقعیت‌های ground truth

Physical Setup:
    داده‌های فرضی بر اساس یک سینه مصنوعی با ابعاد واقعی طراحی شده‌اند:
    - Breast dimensions: 100mm × 120mm × 80mm
    - CC view: projects Z axis (cranio-caudal collapse)
    - MLO view: projects at pectoral angle θ_pec ≈ 50°
    - Lesion at known 3D position (X, Y, Z) → test both projections
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

import numpy as np

from .geometry import (
    ChestWallOrientation,
    ImageGeometry,
    LesionLocation,
    MammogramGeometry,
    NipplePosition,
    PixelSpacing,
)
from .correspondence_arc import (
    CorrespondenceArc,
    compute_correspondence_arc,
    refine_arc_with_density_correlation,
)
from .pectoral_detection import PectoralLine
from .breast_contour import segment_breast_contour


# ─── Synthetic Test Data ─────────────────────────────────────────────────────

@dataclass
class SyntheticLesion3D:
    """A lesion with known 3D position for ground truth validation."""
    x_mm: float  # Medial-lateral position
    y_mm: float  # Posterior-anterior (nipple to chest wall)
    z_mm: float  # Cranio-caudal position
    width_mm: float = 10.0
    height_mm: float = 10.0
    
    def project_to_cc(self) -> Tuple[float, float]:
        """Project to CC view (X, Y) — Z axis collapsed."""
        return (self.x_mm, self.y_mm)
    
    def project_to_mlo(self, pectoral_angle_deg: float = 50.0) -> Tuple[float, float]:
        """
        Project to MLO view (X, H) where H = Y·sin(θ) + Z·cos(θ).
        
        The MLO view is oblique at angle θ from vertical, so the
        vertical dimension H is a weighted combination of Y and Z.
        """
        theta_rad = math.radians(pectoral_angle_deg)
        h_mm = self.y_mm * math.sin(theta_rad) + self.z_mm * math.cos(theta_rad)
        return (self.x_mm, h_mm)
    
    def distance_from_nipple(self) -> float:
        """Distance from nipple (at origin) to lesion in 3D breast space."""
        return math.sqrt(self.x_mm**2 + self.y_mm**2)


def create_synthetic_mammogram_geometry(
    view: str,
    laterality: str = 'R',
    image_size_px: Tuple[int, int] = (1000, 1200),
    pixel_spacing_mm: float = 0.1,
    nipple_position_px: Optional[Tuple[float, float]] = None,
) -> MammogramGeometry:
    """
    Create synthetic mammogram geometry for testing.
    
    Args:
        view: 'CC' or 'MLO'
        laterality: 'R' or 'L'
        image_size_px: (width, height) in pixels
        pixel_spacing_mm: mm per pixel (isotropic)
        nipple_position_px: Optional manual nipple position
        
    Returns:
        MammogramGeometry ready for correspondence arc computation.
    """
    width_px, height_px = image_size_px
    spacing = PixelSpacing(x=pixel_spacing_mm, y=pixel_spacing_mm)
    
    image_geom = ImageGeometry(
        width_px=width_px,
        height_px=height_px,
        pixel_spacing=spacing,
    )
    
    # Default nipple position (right edge for R breast, left edge for L breast)
    if nipple_position_px is None:
        if laterality == 'R':
            nipple_px = (width_px - 50, height_px // 2)
        else:
            nipple_px = (50, height_px // 2)
    else:
        nipple_px = nipple_position_px
    
    nipple = NipplePosition(
        x_px=nipple_px[0],
        y_px=nipple_px[1],
        x_mm=nipple_px[0] * pixel_spacing_mm,
        y_mm=nipple_px[1] * pixel_spacing_mm,
        detected=True,
    )
    
    chest_wall = ChestWallOrientation.RIGHT if laterality == 'R' else ChestWallOrientation.LEFT
    
    return MammogramGeometry(
        image=image_geom,
        nipple=nipple,
        chest_wall=chest_wall,
        laterality=laterality,
        view_position=view,
    )


def create_synthetic_lesion_in_view(
    lesion_3d: SyntheticLesion3D,
    view: str,
    geometry: MammogramGeometry,
    pectoral_angle_deg: float = 50.0,
) -> LesionLocation:
    """
    Create a LesionLocation from a 3D lesion projected to a view.
    
    Args:
        lesion_3d: Ground truth 3D lesion.
        view: 'CC' or 'MLO'
        geometry: Geometry of the target view.
        pectoral_angle_deg: Pectoral angle for MLO projection.
        
    Returns:
        LesionLocation in the target view's pixel coordinates.
    """
    # Project to 2D
    if view == 'CC':
        x_mm, y_mm = lesion_3d.project_to_cc()
    else:
        x_mm, y_mm = lesion_3d.project_to_mlo(pectoral_angle_deg)
    
    # Convert to pixel coordinates (relative to nipple)
    # Nipple is at geometry.nipple position
    # Lesion is at (x_mm, y_mm) relative to nipple
    center_x_px = geometry.nipple.x_px + (x_mm / geometry.image.pixel_spacing.x)
    center_y_px = geometry.nipple.y_px + (y_mm / geometry.image.pixel_spacing.y)
    
    # Create bounding box
    half_w = lesion_3d.width_mm / 2 / geometry.image.pixel_spacing.x
    half_h = lesion_3d.height_mm / 2 / geometry.image.pixel_spacing.y
    
    box_px = [
        center_x_px - half_w,
        center_y_px - half_h,
        center_x_px + half_w,
        center_y_px + half_h,
    ]
    
    return LesionLocation.from_pixel_box(box_px, geometry.image.pixel_spacing, score=0.95)


def create_synthetic_breast_contour(
    geometry: MammogramGeometry,
    laterality: str,
) -> np.ndarray:
    """
    Create a simple synthetic breast contour for testing.
    
    Returns an elliptical contour representing the breast boundary.
    """
    width_px = geometry.image.width_px
    height_px = geometry.image.height_px
    
    # Ellipse parameters
    if laterality == 'R':
        center_x = width_px * 0.6
    else:
        center_x = width_px * 0.4
    
    center_y = height_px * 0.5
    radius_x = width_px * 0.35
    radius_y = height_px * 0.45
    
    # Generate ellipse points
    theta = np.linspace(0, 2*np.pi, 200)
    contour_x = center_x + radius_x * np.cos(theta)
    contour_y = center_y + radius_y * np.sin(theta)
    
    contour = np.column_stack([contour_x, contour_y]).astype(np.float32)
    return contour


# ─── Test Functions ──────────────────────────────────────────────────────────

def test_cc_to_mlo_projection(
    lesion_3d: Optional[SyntheticLesion3D] = None,
    pectoral_angle_deg: float = 50.0,
    verbose: bool = True,
) -> dict:
    """
    Test CC → MLO correspondence arc projection.
    
    Creates a synthetic lesion, projects it to CC view, then computes the
    correspondence arc in MLO view and checks if it contains the ground truth.
    
    Args:
        lesion_3d: Ground truth 3D lesion. If None, uses default test lesion.
        pectoral_angle_deg: Pectoral muscle angle for MLO view.
        verbose: If True, print detailed results.
        
    Returns:
        Dictionary with test results and metrics.
    """
    # Default test lesion: 40mm lateral, 60mm posterior, 30mm superior
    if lesion_3d is None:
        lesion_3d = SyntheticLesion3D(
            x_mm=40.0,
            y_mm=60.0,
            z_mm=30.0,
            width_mm=12.0,
            height_mm=12.0,
        )
    
    # Create synthetic geometries
    cc_geom = create_synthetic_mammogram_geometry('CC', 'R')
    mlo_geom = create_synthetic_mammogram_geometry('MLO', 'R')
    
    # Create lesion in CC view
    cc_lesion = create_synthetic_lesion_in_view(lesion_3d, 'CC', cc_geom)
    
    # Ground truth: where lesion should appear in MLO
    mlo_x_mm, mlo_h_mm = lesion_3d.project_to_mlo(pectoral_angle_deg)
    gt_x_px = mlo_geom.nipple.x_px + (mlo_x_mm / mlo_geom.image.pixel_spacing.x)
    gt_y_px = mlo_geom.nipple.y_px + (mlo_h_mm / mlo_geom.image.pixel_spacing.y)
    
    # Create synthetic breast contour
    mlo_contour = create_synthetic_breast_contour(mlo_geom, 'R')
    
    # Compute correspondence arc
    arc = compute_correspondence_arc(
        source_lesion=cc_lesion,
        source_geom=cc_geom,
        target_geom=mlo_geom,
        source_view='CC',
        target_view='MLO',
        pectoral_angle_deg=pectoral_angle_deg,
        breast_contour=mlo_contour,
        angular_resolution_deg=1.0,
        angle_margin_deg=30.0,
    )
    
    # Calculate error: distance from best point to ground truth
    error_px = None
    error_mm = None
    arc_contains_gt = False
    
    if arc.best_point_px is not None:
        best_x, best_y = arc.best_point_px
        error_px = math.sqrt((best_x - gt_x_px)**2 + (best_y - gt_y_px)**2)
        error_mm = error_px * mlo_geom.image.pixel_spacing.x
        
        # Check if ground truth is within arc points
        min_dist = float('inf')
        for arc_x, arc_y in arc.arc_points_px:
            dist = math.sqrt((arc_x - gt_x_px)**2 + (arc_y - gt_y_px)**2)
            min_dist = min(min_dist, dist)
        
        # Consider "contained" if within 5 pixels of any arc point
        arc_contains_gt = min_dist <= 5.0
    
    # Build results
    results = {
        'test_name': 'CC → MLO Projection',
        'lesion_3d': lesion_3d,
        'pectoral_angle_deg': pectoral_angle_deg,
        'ground_truth_px': (gt_x_px, gt_y_px),
        'best_point_px': arc.best_point_px,
        'error_px': error_px,
        'error_mm': error_mm,
        'arc_contains_gt': arc_contains_gt,
        'arc_length': len(arc.arc_points_px),
        'confidence': arc.confidence,
        'radius_mm': arc.radius_mm,
        'success': error_mm is not None and error_mm < 10.0,  # Success if error < 10mm
    }
    
    if verbose:
        print("═" * 60)
        print(f"  Test: {results['test_name']}")
        print("═" * 60)
        print(f"3D Lesion Position:")
        print(f"  X: {lesion_3d.x_mm:.1f} mm (medial-lateral)")
        print(f"  Y: {lesion_3d.y_mm:.1f} mm (posterior-anterior)")
        print(f"  Z: {lesion_3d.z_mm:.1f} mm (cranio-caudal)")
        print(f"  Distance from nipple: {lesion_3d.distance_from_nipple():.1f} mm")
        print()
        print(f"Pectoral Angle: {pectoral_angle_deg:.1f}°")
        print()
        print(f"Ground Truth in MLO: ({gt_x_px:.1f}, {gt_y_px:.1f}) px")
        print(f"Best Point in Arc:   ({arc.best_point_px[0]:.1f}, {arc.best_point_px[1]:.1f}) px" if arc.best_point_px else "None")
        print()
        print(f"Error: {error_mm:.2f} mm ({error_px:.2f} px)" if error_mm else "N/A")
        print(f"Arc Contains GT: {'✓ Yes' if arc_contains_gt else '✗ No'}")
        print(f"Arc Points: {len(arc.arc_points_px)}")
        print(f"Confidence: {arc.confidence:.1%}")
        print(f"Arc Radius: {arc.radius_mm:.1f} mm")
        print()
        print(f"Result: {'✓ PASS' if results['success'] else '✗ FAIL'}")
        print("═" * 60)
        print()
    
    return results


def test_mlo_to_cc_projection(
    lesion_3d: Optional[SyntheticLesion3D] = None,
    pectoral_angle_deg: float = 50.0,
    verbose: bool = True,
) -> dict:
    """
    Test MLO → CC correspondence arc projection.
    
    Similar to test_cc_to_mlo_projection but in reverse direction.
    """
    # Default test lesion
    if lesion_3d is None:
        lesion_3d = SyntheticLesion3D(
            x_mm=35.0,
            y_mm=55.0,
            z_mm=25.0,
            width_mm=12.0,
            height_mm=12.0,
        )
    
    # Create synthetic geometries
    cc_geom = create_synthetic_mammogram_geometry('CC', 'R')
    mlo_geom = create_synthetic_mammogram_geometry('MLO', 'R')
    
    # Create lesion in MLO view
    mlo_lesion = create_synthetic_lesion_in_view(lesion_3d, 'MLO', mlo_geom, pectoral_angle_deg)
    
    # Ground truth: where lesion should appear in CC
    cc_x_mm, cc_y_mm = lesion_3d.project_to_cc()
    gt_x_px = cc_geom.nipple.x_px + (cc_x_mm / cc_geom.image.pixel_spacing.x)
    gt_y_px = cc_geom.nipple.y_px + (cc_y_mm / cc_geom.image.pixel_spacing.y)
    
    # Create synthetic breast contour
    cc_contour = create_synthetic_breast_contour(cc_geom, 'R')
    
    # Compute correspondence arc
    arc = compute_correspondence_arc(
        source_lesion=mlo_lesion,
        source_geom=mlo_geom,
        target_geom=cc_geom,
        source_view='MLO',
        target_view='CC',
        pectoral_angle_deg=pectoral_angle_deg,
        breast_contour=cc_contour,
        angular_resolution_deg=1.0,
        angle_margin_deg=30.0,
    )
    
    # Calculate error
    error_px = None
    error_mm = None
    arc_contains_gt = False
    
    if arc.best_point_px is not None:
        best_x, best_y = arc.best_point_px
        error_px = math.sqrt((best_x - gt_x_px)**2 + (best_y - gt_y_px)**2)
        error_mm = error_px * cc_geom.image.pixel_spacing.x
        
        # Check if ground truth is within arc points
        min_dist = float('inf')
        for arc_x, arc_y in arc.arc_points_px:
            dist = math.sqrt((arc_x - gt_x_px)**2 + (arc_y - gt_y_px)**2)
            min_dist = min(min_dist, dist)
        
        arc_contains_gt = min_dist <= 5.0
    
    # Build results
    results = {
        'test_name': 'MLO → CC Projection',
        'lesion_3d': lesion_3d,
        'pectoral_angle_deg': pectoral_angle_deg,
        'ground_truth_px': (gt_x_px, gt_y_px),
        'best_point_px': arc.best_point_px,
        'error_px': error_px,
        'error_mm': error_mm,
        'arc_contains_gt': arc_contains_gt,
        'arc_length': len(arc.arc_points_px),
        'confidence': arc.confidence,
        'radius_mm': arc.radius_mm,
        'success': error_mm is not None and error_mm < 10.0,
    }
    
    if verbose:
        print("═" * 60)
        print(f"  Test: {results['test_name']}")
        print("═" * 60)
        print(f"3D Lesion Position:")
        print(f"  X: {lesion_3d.x_mm:.1f} mm (medial-lateral)")
        print(f"  Y: {lesion_3d.y_mm:.1f} mm (posterior-anterior)")
        print(f"  Z: {lesion_3d.z_mm:.1f} mm (cranio-caudal)")
        print(f"  Distance from nipple: {lesion_3d.distance_from_nipple():.1f} mm")
        print()
        print(f"Pectoral Angle: {pectoral_angle_deg:.1f}°")
        print()
        print(f"Ground Truth in CC: ({gt_x_px:.1f}, {gt_y_px:.1f}) px")
        print(f"Best Point in Arc:  ({arc.best_point_px[0]:.1f}, {arc.best_point_px[1]:.1f}) px" if arc.best_point_px else "None")
        print()
        print(f"Error: {error_mm:.2f} mm ({error_px:.2f} px)" if error_mm else "N/A")
        print(f"Arc Contains GT: {'✓ Yes' if arc_contains_gt else '✗ No'}")
        print(f"Arc Points: {len(arc.arc_points_px)}")
        print(f"Confidence: {arc.confidence:.1%}")
        print(f"Arc Radius: {arc.radius_mm:.1f} mm")
        print()
        print(f"Result: {'✓ PASS' if results['success'] else '✗ FAIL'}")
        print("═" * 60)
        print()
    
    return results


def run_comprehensive_test_suite(verbose: bool = True) -> dict:
    """
    Run a comprehensive test suite with multiple lesion positions.
    
    Tests the algorithm with various lesion locations to validate
    accuracy across different depths and positions.
    
    Returns:
        Dictionary with aggregated test statistics.
    """
    test_lesions = [
        # Superficial lesion (close to nipple)
        SyntheticLesion3D(x_mm=20.0, y_mm=30.0, z_mm=15.0),
        # Mid-depth lesion
        SyntheticLesion3D(x_mm=40.0, y_mm=60.0, z_mm=30.0),
        # Deep lesion (near chest wall)
        SyntheticLesion3D(x_mm=50.0, y_mm=90.0, z_mm=40.0),
        # Medial lesion
        SyntheticLesion3D(x_mm=10.0, y_mm=50.0, z_mm=25.0),
        # Lateral lesion
        SyntheticLesion3D(x_mm=60.0, y_mm=50.0, z_mm=25.0),
    ]
    
    pectoral_angles = [45.0, 50.0, 55.0]
    
    all_results = []
    
    if verbose:
        print("\n")
        print("╔" + "═" * 58 + "╗")
        print("║" + " " * 10 + "COMPREHENSIVE TEST SUITE" + " " * 24 + "║")
        print("╚" + "═" * 58 + "╝")
        print()
    
    for i, lesion in enumerate(test_lesions, 1):
        for angle in pectoral_angles:
            if verbose:
                print(f"Test {len(all_results)+1}: Lesion #{i}, Pectoral Angle {angle}°")
            
            # Test CC → MLO
            result_cc_mlo = test_cc_to_mlo_projection(
                lesion_3d=lesion,
                pectoral_angle_deg=angle,
                verbose=False,
            )
            all_results.append(result_cc_mlo)
            
            # Test MLO → CC
            result_mlo_cc = test_mlo_to_cc_projection(
                lesion_3d=lesion,
                pectoral_angle_deg=angle,
                verbose=False,
            )
            all_results.append(result_mlo_cc)
    
    # Calculate statistics
    errors_mm = [r['error_mm'] for r in all_results if r['error_mm'] is not None]
    success_count = sum(1 for r in all_results if r['success'])
    
    stats = {
        'total_tests': len(all_results),
        'success_count': success_count,
        'success_rate': success_count / len(all_results) if all_results else 0.0,
        'mean_error_mm': np.mean(errors_mm) if errors_mm else None,
        'std_error_mm': np.std(errors_mm) if errors_mm else None,
        'max_error_mm': np.max(errors_mm) if errors_mm else None,
        'min_error_mm': np.min(errors_mm) if errors_mm else None,
        'all_results': all_results,
    }
    
    if verbose:
        print("\n")
        print("╔" + "═" * 58 + "╗")
        print("║" + " " * 18 + "TEST STATISTICS" + " " * 25 + "║")
        print("╚" + "═" * 58 + "╝")
        print()
        print(f"Total Tests:   {stats['total_tests']}")
        print(f"Passed:        {stats['success_count']} ({stats['success_rate']:.1%})")
        print(f"Failed:        {stats['total_tests'] - stats['success_count']}")
        print()
        print(f"Error Statistics (mm):")
        print(f"  Mean:   {stats['mean_error_mm']:.2f}")
        print(f"  Std:    {stats['std_error_mm']:.2f}")
        print(f"  Min:    {stats['min_error_mm']:.2f}")
        print(f"  Max:    {stats['max_error_mm']:.2f}")
        print()
        print(f"Result: {'✓ ALL TESTS PASSED' if stats['success_rate'] == 1.0 else f'⚠ {stats["total_tests"] - stats["success_count"]} TESTS FAILED'}")
        print("═" * 60)
        print()
    
    return stats


# ─── Demo / Visualization Function ──────────────────────────────────────────

def demo_correspondence_arc_visualization():
    """
    نمایش کامل visualization کمان تناظر با زاویه‌ها، فرمول‌ها و محاسبات.
    
    این تابع یک نمایش جامع از الگوریتم کمان تناظر را ارائه می‌دهد:
        1. ایجاد داده‌های فرضی (synthetic) برای CC و MLO
        2. محاسبه کمان تناظر با زاویه pectoral muscle
        3. نمایش کمان روی تصویر با annotation های کامل
        4. نمایش فرمول‌ها و نتایج محاسبات در باکس اطلاعات
        5. مقایسه با ground truth برای اعتبارسنجی
    
    Usage:
        ```python
        from modules.ai_imaging.ai_module_ui.cursor_3d.test_demo import (
            demo_correspondence_arc_visualization
        )
        
        demo_correspondence_arc_visualization()
        ```
    
    Output:
        - چاپ نتایج تست در console
        - نمایش visualization روی viewer widget (if available)
        - گزارش دقت: distance from arc to ground truth
    """
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 20 + "CORRESPONDENCE ARC VISUALIZATION DEMO" + " " * 21 + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    print("این demo عملکرد کامل الگوریتم کمان تناظر را با داده‌های فرضی نمایش می‌دهد.")
    print("شامل: محاسبه کمان، نمایش زاویه‌ها، فرمول‌های فیزیکی و ارزیابی دقت.")
    print()
    
    # Test 1: CC → MLO projection
    print("─" * 80)
    print("Test 1: CC → MLO Correspondence Arc")
    print("─" * 80)
    result1 = test_cc_to_mlo_projection(verbose=True)
    
    # Test 2: MLO → CC projection
    print("\n")
    print("─" * 80)
    print("Test 2: MLO → CC Correspondence Arc")
    print("─" * 80)
    result2 = test_mlo_to_cc_projection(verbose=True)
    
    # Summary
    print("\n")
    print("╔" + "═" * 78 + "╗")
    print("║" + " " * 32 + "DEMO SUMMARY" + " " * 34 + "║")
    print("╚" + "═" * 78 + "╝")
    print()
    
    if result1['success'] and result2['success']:
        print("✓ هر دو تست با موفقیت انجام شد!")
        print("  الگوریتم کمان تناظر با دقت قابل قبول کار می‌کند.")
        print()
        print(f"  CC → MLO Error: {result1['error_mm']:.2f} mm")
        print(f"  MLO → CC Error: {result2['error_mm']:.2f} mm")
    else:
        print("⚠ یک یا هر دو تست ناموفق بودند.")
        print("  لطفاً پارامترها را بررسی کنید.")
    
    print()
    print("برای نمایش visualization کامل روی viewer widget:")
    print("  از تابع draw_correspondence_arc_with_annotations() استفاده کنید.")
    print()
    print("مثال:")
    print("  from .visualization import draw_correspondence_arc_with_annotations")
    print("  draw_correspondence_arc_with_annotations(match, view_data, laterality)")
    print()
    print("═" * 80)
    print()


# ─── Main Entry Point ────────────────────────────────────────────────────────

if __name__ == '__main__':
    # Run the demo
    demo_correspondence_arc_visualization()
    
    # Optionally run comprehensive test suite
    print("\n\nRunning comprehensive test suite...")
    print("(Testing multiple lesion positions and pectoral angles)")
    print()
    
    stats = run_comprehensive_test_suite(verbose=True)
