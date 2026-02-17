"""
Zeta MPR — Diagnostic Validator & Visual Markers
=================================================

This module provides:

1. **Mathematical validation** of camera state, handedness, normals.
2. **Visual corner markers** (L/R/A/P/S/I) drawn in each 2D view.
3. **Invariant checks** that fire on every oblique update and log
   violations immediately.
4. **Snapshot logging** for before/after comparison.

Usage:
    In StandardMPRViewer.__init__, after _setup_ui:

        from .mpr_diagnostic_validator import MPRDiagnosticValidator
        self._diag = MPRDiagnosticValidator(self)
        self._diag.capture_baseline()        # after _capture_baseline_camera_state
        self._diag.install_corner_markers()  # visual L/R/A/P/S/I

    In _set_oblique_camera, at the end:

        if hasattr(self, '_diag'):
            self._diag.validate_after_oblique(target_view, oblique_normal)

    In _reset_all_to_orthogonal, at the end:

        if hasattr(self, '_diag'):
            self._diag.validate_after_reset()

Enable verbose output:
    Set environment variable ZETA_MPR_DIAG=1

Version: 2026-02-17
"""

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Feature flag ────────────────────────────────────────────────────────
DIAG_ENABLED = os.environ.get("ZETA_MPR_DIAG", "0") == "1"
DIAG_VERBOSE = os.environ.get("ZETA_MPR_DIAG_VERBOSE", "0") == "1"

# Always-on threshold: violations above these trigger a WARNING log even
# when ZETA_MPR_DIAG is not set.
_ANGLE_WARN_DEG      = 5.0     # normal mismatch threshold
_DISTANCE_WARN_MM    = 2.0     # focal vs crosshair center distance
_HANDEDNESS_WARN     = True    # det sign flip


# ═══════════════════════════════════════════════════════════════════════
# 1.  Data Classes — typed snapshots of camera / validation state
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class CameraSnapshot:
    """Immutable record of one view's camera state."""
    view_name: str
    position: np.ndarray          # camera position
    focal_point: np.ndarray       # focal point
    view_up: np.ndarray           # view up vector
    direction: np.ndarray         # normalised (focal-pos)
    distance: float               # |pos-focal|
    parallel_scale: float
    right_vector: np.ndarray      # cross(direction, view_up) normalised
    det_sign: float               # sign of det([right, up, dir])

    @staticmethod
    def from_camera(view_name, camera) -> "CameraSnapshot":
        pos   = np.array(camera.GetPosition(),  dtype=float)
        focal = np.array(camera.GetFocalPoint(), dtype=float)
        up    = np.array(camera.GetViewUp(),     dtype=float)

        d = focal - pos
        dist = float(np.linalg.norm(d))
        direction = d / dist if dist > 1e-8 else np.array([0., 0., -1.])

        right = np.cross(direction, up)
        rm = np.linalg.norm(right)
        if rm > 1e-8:
            right /= rm

        det = float(np.dot(right, np.cross(up, direction)))

        return CameraSnapshot(
            view_name=view_name,
            position=pos, focal_point=focal, view_up=up,
            direction=direction, distance=dist,
            parallel_scale=camera.GetParallelScale(),
            right_vector=right, det_sign=np.sign(det),
        )


@dataclass
class ValidationResult:
    """One validation check result."""
    check_name: str
    view_name: str
    passed: bool
    value: float                  # measured quantity
    threshold: float              # pass/fail limit
    message: str = ""


@dataclass
class FrameReport:
    """Full diagnostic report for one oblique update."""
    trigger: str                  # what caused the update
    crosshair_angles_deg: Dict[str, float] = field(default_factory=dict)
    crosshair_center: Optional[np.ndarray] = None
    camera_snapshots: Dict[str, CameraSnapshot] = field(default_factory=dict)
    validations: List[ValidationResult] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(v.passed for v in self.validations)

    def summary(self) -> str:
        fails = [v for v in self.validations if not v.passed]
        if not fails:
            return f"[MPR_DIAG] {self.trigger}: ALL PASSED ({len(self.validations)} checks)"
        lines = [f"[MPR_DIAG] {self.trigger}: {len(fails)}/{len(self.validations)} FAILED"]
        for v in fails:
            lines.append(f"  FAIL {v.view_name}.{v.check_name}: "
                         f"val={v.value:.4f} thr={v.threshold:.4f} — {v.message}")
        return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════
# 2.  Mathematical Invariant Checks
# ═══════════════════════════════════════════════════════════════════════

def _angle_between(a: np.ndarray, b: np.ndarray) -> float:
    """Angle in degrees between two vectors."""
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    return math.degrees(math.acos(abs(dot)))


def _signed_angle(a: np.ndarray, b: np.ndarray) -> float:
    """Signed angle (degrees) using dot; positive = same hemisphere."""
    return math.degrees(math.acos(float(np.clip(np.dot(a, b), -1.0, 1.0))))


class InvariantChecker:
    """All mathematical invariant checks live here."""

    # ── Check 1: Handedness preservation ──────────────────────────────
    @staticmethod
    def check_handedness(baseline: CameraSnapshot,
                         current: CameraSnapshot) -> ValidationResult:
        """
        The determinant sign of the camera basis (right, up, direction)
        must be the same as the baseline.  A sign flip means the image
        is mirrored.

        Math:  det_sign = sign( right . (up x direction) )
        """
        same = (baseline.det_sign * current.det_sign) >= 0
        return ValidationResult(
            check_name="handedness",
            view_name=current.view_name,
            passed=same,
            value=current.det_sign,
            threshold=baseline.det_sign,
            message="" if same else
                f"Handedness FLIPPED: baseline={baseline.det_sign:+.0f} "
                f"current={current.det_sign:+.0f} → image mirrored"
        )

    # ── Check 2: Normal hemisphere consistency ────────────────────────
    @staticmethod
    def check_normal_hemisphere(baseline: CameraSnapshot,
                                current: CameraSnapshot) -> ValidationResult:
        """
        The current camera viewing direction must be in the same
        hemisphere as the baseline direction.  A flip means the camera
        jumped to the opposite side of the volume.

        Math:  dot(current_dir, baseline_dir) > 0
        """
        dot = float(np.dot(current.direction, baseline.direction))
        passed = dot > 0
        return ValidationResult(
            check_name="normal_hemisphere",
            view_name=current.view_name,
            passed=passed,
            value=dot,
            threshold=0.0,
            message="" if passed else
                f"Camera direction FLIPPED hemisphere: dot={dot:.4f}"
        )

    # ── Check 3: View-up orthogonality ────────────────────────────────
    @staticmethod
    def check_viewup_orthogonality(snap: CameraSnapshot) -> ValidationResult:
        """
        view_up must be perpendicular to viewing direction.
        dot(view_up, direction) should be ~0.

        A large value means VTK's re-orthogonalisation failed or
        view-up was set incorrectly.
        """
        dot = abs(float(np.dot(snap.view_up, snap.direction)))
        passed = dot < 0.05  # ~3 degrees
        return ValidationResult(
            check_name="viewup_ortho",
            view_name=snap.view_name,
            passed=passed,
            value=math.degrees(math.asin(min(dot, 1.0))),
            threshold=3.0,
            message="" if passed else
                f"View-up NOT orthogonal to direction: |dot|={dot:.4f} "
                f"({math.degrees(math.asin(min(dot, 1.0))):.1f}°)"
        )

    # ── Check 4: View-up stability ────────────────────────────────────
    @staticmethod
    def check_viewup_stability(baseline: CameraSnapshot,
                               current: CameraSnapshot,
                               max_angle_deg: float = 90.0) -> ValidationResult:
        """
        View-up should not rotate more than max_angle_deg from baseline.
        A 180° rotation means the image is upside-down.

        We use the *absolute* angle (ignoring sign) because view-up
        should stay roughly pointed in the same direction.
        """
        angle = _angle_between(baseline.view_up, current.view_up)
        passed = angle < max_angle_deg
        return ValidationResult(
            check_name="viewup_stability",
            view_name=current.view_name,
            passed=passed,
            value=angle,
            threshold=max_angle_deg,
            message="" if passed else
                f"View-up drifted {angle:.1f}° from baseline (limit {max_angle_deg}°)"
        )

    # ── Check 5: Focal point = crosshair center (oblique mode) ────────
    @staticmethod
    def check_focal_at_crosshair(snap: CameraSnapshot,
                                  crosshair_center: np.ndarray,
                                  max_dist_mm: float = 2.0) -> ValidationResult:
        """
        In oblique mode the focal point should be exactly at the
        crosshair center.  Any drift means reconstruction lines and
        slice positions are desynchronised.
        """
        dist = float(np.linalg.norm(snap.focal_point - crosshair_center))
        passed = dist < max_dist_mm
        return ValidationResult(
            check_name="focal_at_crosshair",
            view_name=snap.view_name,
            passed=passed,
            value=dist,
            threshold=max_dist_mm,
            message="" if passed else
                f"Focal point {dist:.2f} mm from crosshair center"
        )

    # ── Check 6: Camera distance stability ────────────────────────────
    @staticmethod
    def check_distance_stable(baseline: CameraSnapshot,
                              current: CameraSnapshot,
                              tolerance_pct: float = 5.0) -> ValidationResult:
        """
        Camera distance from focal point should stay close to baseline.
        Large drift means zoom or position corruption.
        """
        pct = abs(current.distance - baseline.distance) / max(baseline.distance, 1.0) * 100
        passed = pct < tolerance_pct
        return ValidationResult(
            check_name="distance_stable",
            view_name=current.view_name,
            passed=passed,
            value=pct,
            threshold=tolerance_pct,
            message="" if passed else
                f"Camera distance drifted {pct:.1f}% "
                f"(baseline={baseline.distance:.1f} current={current.distance:.1f})"
        )

    # ── Check 7: Right/left vector consistency ────────────────────────
    @staticmethod
    def check_right_vector_consistency(baseline: CameraSnapshot,
                                       current: CameraSnapshot,
                                       max_angle_deg: float = 120.0) -> ValidationResult:
        """
        The camera's right vector (cross(direction, view_up)) should not
        flip.  A 180° rotation means left-right are swapped.
        """
        angle = _angle_between(baseline.right_vector, current.right_vector)
        passed = angle < max_angle_deg
        return ValidationResult(
            check_name="right_vector",
            view_name=current.view_name,
            passed=passed,
            value=angle,
            threshold=max_angle_deg,
            message="" if passed else
                f"Right vector rotated {angle:.1f}° from baseline — possible L/R swap"
        )

    # ── Check 8: Parallel scale preservation ──────────────────────────
    @staticmethod
    def check_parallel_scale(baseline: CameraSnapshot,
                             current: CameraSnapshot,
                             tolerance_pct: float = 1.0) -> ValidationResult:
        """Parallel scale (zoom) must not change during oblique updates."""
        pct = abs(current.parallel_scale - baseline.parallel_scale) / max(baseline.parallel_scale, 1.0) * 100
        passed = pct < tolerance_pct
        return ValidationResult(
            check_name="parallel_scale",
            view_name=current.view_name,
            passed=passed,
            value=pct,
            threshold=tolerance_pct,
            message="" if passed else
                f"ParallelScale changed {pct:.1f}% — unexpected zoom"
        )

    # ── Check 9: Slice plane contains crosshair center ────────────────
    @staticmethod
    def check_plane_containment(snap: CameraSnapshot,
                                crosshair_center: np.ndarray,
                                max_dist_mm: float = 0.5) -> ValidationResult:
        """
        The crosshair centre must lie ON the displayed slice plane.
        Plane equation: dot(point - focal, direction) = 0.

        A non-zero distance means the plane is offset from the
        intended position.
        """
        dist = abs(float(np.dot(crosshair_center - snap.focal_point, snap.direction)))
        passed = dist < max_dist_mm
        return ValidationResult(
            check_name="plane_containment",
            view_name=snap.view_name,
            passed=passed,
            value=dist,
            threshold=max_dist_mm,
            message="" if passed else
                f"Crosshair centre is {dist:.3f} mm off the slice plane"
        )

    # ── Check 10: Mutual orthogonality of 3 view normals ─────────────
    @staticmethod
    def check_mutual_orthogonality(snapshots: Dict[str, CameraSnapshot],
                                   max_deviation_deg: float = 5.0) -> List[ValidationResult]:
        """
        The three viewing directions (axial, sagittal, coronal) should
        be mutually orthogonal.  For standard orientation dot ≈ 0 for
        each pair.  For oblique, the angles change but should still form
        a ~90° triplet if only one view is rotated.
        """
        results = []
        pairs = [('axial', 'sagittal'), ('axial', 'coronal'), ('sagittal', 'coronal')]
        for a, b in pairs:
            if a not in snapshots or b not in snapshots:
                continue
            dot = abs(float(np.dot(snapshots[a].direction, snapshots[b].direction)))
            angle_from_90 = abs(90.0 - math.degrees(math.acos(min(dot, 1.0))))
            passed = angle_from_90 < max_deviation_deg
            results.append(ValidationResult(
                check_name=f"ortho_{a[:3]}_{b[:3]}",
                view_name=f"{a}-{b}",
                passed=passed,
                value=angle_from_90,
                threshold=max_deviation_deg,
                message="" if passed else
                    f"{a}/{b} normals deviate {angle_from_90:.1f}° from 90°"
            ))
        return results


# ═══════════════════════════════════════════════════════════════════════
# 3.  Volume Corner Reference Points
# ═══════════════════════════════════════════════════════════════════════

def compute_volume_corners(image_data) -> Dict[str, np.ndarray]:
    """
    Compute the 8 corners of the VTK image volume in world coordinates.
    Returns a dict keyed by descriptive name:
        'origin', 'x_max', 'y_max', 'z_max',
        'xy_max', 'xz_max', 'yz_max', 'xyz_max'
    """
    bounds = image_data.GetBounds()
    x0, x1, y0, y1, z0, z1 = bounds

    return {
        'origin':  np.array([x0, y0, z0]),
        'x_max':   np.array([x1, y0, z0]),
        'y_max':   np.array([x0, y1, z0]),
        'z_max':   np.array([x0, y0, z1]),
        'xy_max':  np.array([x1, y1, z0]),
        'xz_max':  np.array([x1, y0, z1]),
        'yz_max':  np.array([x0, y1, z1]),
        'xyz_max': np.array([x1, y1, z1]),
    }


def expected_corner_labels(direction_matrix) -> Dict[str, Dict[str, str]]:
    """
    Given the (doubly-compensated) direction matrix, predict what
    anatomical labels each volume corner should have.

    Returns per-view dicts of edge labels:
        { 'axial': {'left': 'R', 'right': 'L', 'top': 'A', 'bottom': 'P'}, ... }

    This allows us to verify that visual markers match expectations.
    """
    # Extract column directions of the compensation matrix
    col0 = np.array([direction_matrix.GetElement(0, 0),
                     direction_matrix.GetElement(1, 0),
                     direction_matrix.GetElement(2, 0)])
    col1 = np.array([direction_matrix.GetElement(0, 1),
                     direction_matrix.GetElement(1, 1),
                     direction_matrix.GetElement(2, 1)])
    col2 = np.array([direction_matrix.GetElement(0, 2),
                     direction_matrix.GetElement(1, 2),
                     direction_matrix.GetElement(2, 2)])

    def dominant_label(vec):
        """Map a direction vector to the nearest anatomical label."""
        # LPS convention after our compensations
        labels_pos = {0: 'L', 1: 'P', 2: 'S'}
        labels_neg = {0: 'R', 1: 'A', 2: 'I'}
        axis = int(np.argmax(np.abs(vec)))
        return labels_pos[axis] if vec[axis] > 0 else labels_neg[axis]

    # For each view, determine what increasing X/Y in the *display*
    # corresponds to anatomically.  This is approximate—the actual
    # mapping depends on Roll/Azimuth corrections too.
    return {
        'axial': {
            'left_edge':   dominant_label(-col0),  # decreasing X
            'right_edge':  dominant_label(col0),   # increasing X
            'top_edge':    dominant_label(col1),   # increasing Y
            'bottom_edge': dominant_label(-col1),
        },
        'sagittal': {
            'left_edge':   dominant_label(-col1),
            'right_edge':  dominant_label(col1),
            'top_edge':    dominant_label(col2),
            'bottom_edge': dominant_label(-col2),
        },
        'coronal': {
            'left_edge':   dominant_label(-col0),
            'right_edge':  dominant_label(col0),
            'top_edge':    dominant_label(col2),
            'bottom_edge': dominant_label(-col2),
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# 4.  Visual Corner Markers — VTK actors for L/R/A/P/S/I
# ═══════════════════════════════════════════════════════════════════════

try:
    import vtkmodules.all as vtk
    _HAS_VTK = True
except ImportError:
    _HAS_VTK = False


def _make_text_actor(label: str, font_size: int = 14,
                     color: Tuple[float, float, float] = (1.0, 1.0, 0.0)):
    """Create a corner/edge text annotation (2D overlay)."""
    actor = vtk.vtkTextActor()
    actor.SetInput(label)
    prop = actor.GetTextProperty()
    prop.SetFontSize(font_size)
    prop.SetColor(*color)
    prop.SetBold(True)
    prop.SetShadow(True)
    prop.SetFontFamilyToArial()
    return actor


def create_corner_marker_actors(labels: Dict[str, str]) -> Dict[str, "vtk.vtkTextActor"]:
    """
    Create 4 text actors for one view: left, right, top, bottom.

    *labels* keys: 'left_edge', 'right_edge', 'top_edge', 'bottom_edge'
    values: single-letter anatomical labels (L/R/A/P/S/I).

    Positions are set in normalised viewport coordinates.
    """
    actors = {}
    positions = {
        'left_edge':   (0.02, 0.48),   # left centre
        'right_edge':  (0.95, 0.48),   # right centre
        'top_edge':    (0.48, 0.95),   # top centre
        'bottom_edge': (0.48, 0.03),   # bottom centre
    }
    for key, (x, y) in positions.items():
        text = labels.get(key, "?")
        actor = _make_text_actor(text, font_size=16, color=(1.0, 1.0, 0.0))
        actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
        actor.GetPositionCoordinate().SetValue(x, y)
        actors[key] = actor
    return actors


def create_diag_overlay_actor(line: str = "",
                              position: Tuple[float, float] = (0.02, 0.02),
                              font_size: int = 11,
                              color: Tuple[float, float, float] = (0.5, 1.0, 0.5)):
    """Small text actor in a corner for live diagnostic output."""
    actor = vtk.vtkTextActor()
    actor.SetInput(line)
    prop = actor.GetTextProperty()
    prop.SetFontSize(font_size)
    prop.SetColor(*color)
    prop.SetFontFamilyToCourier()
    prop.SetShadow(True)
    actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    actor.GetPositionCoordinate().SetValue(*position)
    return actor


# ═══════════════════════════════════════════════════════════════════════
# 5.  Volume Corner Spheres — 3D reference points visible in every view
# ═══════════════════════════════════════════════════════════════════════

def create_corner_sphere_actors(image_data,
                                radius_mm: float = 3.0,
                                color: Tuple[float, float, float] = (1.0, 0.0, 0.0)):
    """
    Place a small sphere actor at each of the 8 volume corners.
    These appear in all 2D views and in the 3D view as reference.

    Returns list of vtkActor.
    """
    corners = compute_volume_corners(image_data)
    actors = []
    colors = {
        'origin':  (1.0, 0.0, 0.0),   # RED = origin (min X, min Y, min Z)
        'x_max':   (0.0, 1.0, 0.0),   # GREEN = max X
        'y_max':   (0.0, 0.0, 1.0),   # BLUE = max Y
        'z_max':   (1.0, 1.0, 0.0),   # YELLOW = max Z
        'xy_max':  (1.0, 0.0, 1.0),
        'xz_max':  (0.0, 1.0, 1.0),
        'yz_max':  (1.0, 0.5, 0.0),
        'xyz_max': (1.0, 1.0, 1.0),   # WHITE = max all
    }
    for name, pos in corners.items():
        source = vtk.vtkSphereSource()
        source.SetCenter(pos.tolist())
        source.SetRadius(radius_mm)
        source.SetThetaResolution(12)
        source.SetPhiResolution(12)
        source.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(source.GetOutput())

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*colors.get(name, color))
        actor.GetProperty().SetOpacity(0.7)
        actors.append((name, actor))
    return actors


# ═══════════════════════════════════════════════════════════════════════
# 6.  The Main Validator Class
# ═══════════════════════════════════════════════════════════════════════

class MPRDiagnosticValidator:
    """
    Attach to a StandardMPRViewer instance.

    Provides:
        capture_baseline()          — store reference camera state
        validate_after_oblique()    — full invariant check
        validate_after_reset()      — verify return to orthogonal
        install_corner_markers()    — add L/R/A/P/S/I labels
        install_diag_overlays()     — add live metric text
        log_full_snapshot()         — dump everything to logger
        get_last_report()           — get the last FrameReport
    """

    def __init__(self, mpr_viewer, auto_validate: bool = True):
        self._viewer = mpr_viewer
        self._auto_validate = auto_validate
        self._baselines: Dict[str, CameraSnapshot] = {}
        self._last_report: Optional[FrameReport] = None
        self._corner_marker_actors: Dict[str, Dict[str, object]] = {}
        self._diag_overlay_actors: Dict[str, object] = {}
        self._diag_text_actors: Dict[str, object] = {}
        self._corner_sphere_actors: List = []
        self._frame_count = 0
        self._violation_count = 0

        # Invariant checker
        self._checker = InvariantChecker()

        logger.info("[MPR_DIAG] Validator initialised. "
                    "ZETA_MPR_DIAG=%s ZETA_MPR_DIAG_VERBOSE=%s",
                    DIAG_ENABLED, DIAG_VERBOSE)

    # ── Baseline capture ──────────────────────────────────────────────
    def capture_baseline(self):
        """Snapshot baseline camera state from all 2D views."""
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self._viewer.viewers:
                continue
            camera = self._viewer.viewers[view_name]['renderer'].GetActiveCamera()
            self._baselines[view_name] = CameraSnapshot.from_camera(view_name, camera)

        if DIAG_ENABLED:
            for vn, snap in self._baselines.items():
                logger.info(
                    "[MPR_DIAG] BASELINE %s: dir=[%.3f,%.3f,%.3f] "
                    "up=[%.3f,%.3f,%.3f] right=[%.3f,%.3f,%.3f] "
                    "det=%+.0f dist=%.1f scale=%.1f",
                    vn,
                    *snap.direction, *snap.view_up, *snap.right_vector,
                    snap.det_sign, snap.distance, snap.parallel_scale
                )

    # ── Current snapshot helper ───────────────────────────────────────
    def _current_snapshot(self, view_name: str) -> Optional[CameraSnapshot]:
        if view_name not in self._viewer.viewers:
            return None
        camera = self._viewer.viewers[view_name]['renderer'].GetActiveCamera()
        return CameraSnapshot.from_camera(view_name, camera)

    def _all_current_snapshots(self) -> Dict[str, CameraSnapshot]:
        snaps = {}
        for vn in ['axial', 'sagittal', 'coronal']:
            s = self._current_snapshot(vn)
            if s:
                snaps[vn] = s
        return snaps

    # ── Primary validation entry points ───────────────────────────────

    def validate_after_oblique(self, target_view: str,
                               oblique_normal: object = None) -> FrameReport:
        """
        Run all invariant checks after an oblique camera update.
        Returns FrameReport with pass/fail for each check.
        """
        self._frame_count += 1
        report = FrameReport(
            trigger=f"oblique:{target_view}",
            crosshair_angles_deg={
                k: math.degrees(v)
                for k, v in self._viewer.crosshair_angles.items()
            },
            crosshair_center=np.array(self._viewer.current_position, dtype=float),
        )

        # Snapshot all cameras
        report.camera_snapshots = self._all_current_snapshots()

        # Run checks on the target view
        snap = report.camera_snapshots.get(target_view)
        baseline = self._baselines.get(target_view)

        if snap and baseline:
            report.validations.extend([
                self._checker.check_handedness(baseline, snap),
                self._checker.check_normal_hemisphere(baseline, snap),
                self._checker.check_viewup_orthogonality(snap),
                self._checker.check_viewup_stability(baseline, snap),
                self._checker.check_focal_at_crosshair(
                    snap, report.crosshair_center),
                self._checker.check_distance_stable(baseline, snap),
                self._checker.check_right_vector_consistency(baseline, snap),
                self._checker.check_parallel_scale(baseline, snap),
                self._checker.check_plane_containment(
                    snap, report.crosshair_center),
            ])

        # Run mutual-orthogonality across all views
        report.validations.extend(
            self._checker.check_mutual_orthogonality(report.camera_snapshots)
        )

        # Log results
        self._log_report(report)
        self._last_report = report

        # Update live overlays
        if self._diag_text_actors:
            self._update_diag_overlays(report)

        return report

    def validate_after_reset(self) -> FrameReport:
        """Validate that reset returned to clean orthogonal state."""
        report = FrameReport(trigger="reset")
        report.camera_snapshots = self._all_current_snapshots()
        report.crosshair_center = np.array(self._viewer.current_position, dtype=float)
        report.crosshair_angles_deg = {
            k: math.degrees(v)
            for k, v in self._viewer.crosshair_angles.items()
        }

        for vn, snap in report.camera_snapshots.items():
            baseline = self._baselines.get(vn)
            if not baseline:
                continue

            # After reset, direction should match baseline closely
            angle = _signed_angle(snap.direction, baseline.direction)
            report.validations.append(ValidationResult(
                check_name="reset_direction",
                view_name=vn,
                passed=angle < 2.0,
                value=angle,
                threshold=2.0,
                message="" if angle < 2.0 else
                    f"Direction after reset is {angle:.1f}° from baseline"
            ))

            report.validations.append(
                self._checker.check_handedness(baseline, snap))
            report.validations.append(
                self._checker.check_viewup_orthogonality(snap))

        self._log_report(report)
        self._last_report = report
        return report

    def validate_all_views_now(self, trigger: str = "manual") -> FrameReport:
        """Run full validation on all views (can be called at any time)."""
        report = FrameReport(
            trigger=trigger,
            crosshair_angles_deg={
                k: math.degrees(v)
                for k, v in self._viewer.crosshair_angles.items()
            },
            crosshair_center=np.array(self._viewer.current_position, dtype=float),
        )
        report.camera_snapshots = self._all_current_snapshots()

        for vn, snap in report.camera_snapshots.items():
            baseline = self._baselines.get(vn)
            if not baseline:
                continue
            report.validations.extend([
                self._checker.check_handedness(baseline, snap),
                self._checker.check_normal_hemisphere(baseline, snap),
                self._checker.check_viewup_orthogonality(snap),
                self._checker.check_viewup_stability(baseline, snap),
                self._checker.check_focal_at_crosshair(snap, report.crosshair_center),
                self._checker.check_distance_stable(baseline, snap),
                self._checker.check_right_vector_consistency(baseline, snap),
                self._checker.check_parallel_scale(baseline, snap),
                self._checker.check_plane_containment(snap, report.crosshair_center),
            ])
        report.validations.extend(
            self._checker.check_mutual_orthogonality(report.camera_snapshots)
        )
        self._log_report(report)
        self._last_report = report
        return report

    # ── Logging ───────────────────────────────────────────────────────
    def _log_report(self, report: FrameReport):
        fails = [v for v in report.validations if not v.passed]
        if fails:
            self._violation_count += len(fails)
            # Always log failures as WARNING
            logger.warning(report.summary())
            if DIAG_VERBOSE:
                self._log_verbose_snapshot(report)
        elif DIAG_ENABLED:
            # Log passes only when diag is on
            logger.info(report.summary())

    def _log_verbose_snapshot(self, report: FrameReport):
        """Detailed dump for debugging."""
        lines = [
            f"[MPR_DIAG] === VERBOSE SNAPSHOT frame={self._frame_count} ===",
            f"  trigger: {report.trigger}",
            f"  angles:  {report.crosshair_angles_deg}",
            f"  center:  {report.crosshair_center}",
        ]
        for vn, snap in report.camera_snapshots.items():
            lines.append(
                f"  {vn}: pos=[{snap.position[0]:.1f},{snap.position[1]:.1f},{snap.position[2]:.1f}] "
                f"focal=[{snap.focal_point[0]:.1f},{snap.focal_point[1]:.1f},{snap.focal_point[2]:.1f}] "
                f"dir=[{snap.direction[0]:.4f},{snap.direction[1]:.4f},{snap.direction[2]:.4f}] "
                f"up=[{snap.view_up[0]:.4f},{snap.view_up[1]:.4f},{snap.view_up[2]:.4f}] "
                f"right=[{snap.right_vector[0]:.4f},{snap.right_vector[1]:.4f},{snap.right_vector[2]:.4f}] "
                f"det={snap.det_sign:+.0f} dist={snap.distance:.1f}"
            )
        for v in report.validations:
            status = "PASS" if v.passed else "FAIL"
            lines.append(f"  [{status}] {v.view_name}.{v.check_name}: "
                         f"val={v.value:.4f} thr={v.threshold:.4f} {v.message}")
        logger.info("\n".join(lines))

    def log_full_snapshot(self, label: str = "snapshot"):
        """Manual full dump (callable from console/debugger)."""
        report = self.validate_all_views_now(trigger=label)
        self._log_verbose_snapshot(report)
        return report

    # ── Visual markers ────────────────────────────────────────────────
    def install_corner_markers(self):
        """
        Add L/R/A/P/S/I annotation labels to each 2D view.
        Based on the doubly-compensated direction matrix.
        """
        if not _HAS_VTK:
            return

        labels = expected_corner_labels(self._viewer.direction_matrix)
        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self._viewer.viewers:
                continue
            renderer = self._viewer.viewers[view_name]['renderer']
            view_labels = labels.get(view_name, {})
            actors = create_corner_marker_actors(view_labels)
            for key, actor in actors.items():
                renderer.AddActor2D(actor)
            self._corner_marker_actors[view_name] = actors

        logger.info("[MPR_DIAG] Corner markers installed: %s", list(labels.keys()))

    def remove_corner_markers(self):
        """Remove all corner marker actors."""
        for view_name, actors in self._corner_marker_actors.items():
            if view_name in self._viewer.viewers:
                renderer = self._viewer.viewers[view_name]['renderer']
                for actor in actors.values():
                    renderer.RemoveActor2D(actor)
        self._corner_marker_actors.clear()

    def install_corner_spheres(self, radius_mm: float = 3.0):
        """
        Add colored spheres at all 8 volume corners.
        These are visible in both 2D (where the slice intersects them)
        and 3D views.
        """
        if not _HAS_VTK:
            return

        sphere_actors = create_corner_sphere_actors(
            self._viewer.image_data, radius_mm=radius_mm)

        for view_name in ['axial', 'sagittal', 'coronal', '3d']:
            if view_name not in self._viewer.viewers:
                continue
            renderer = self._viewer.viewers[view_name]['renderer']
            for name, actor in sphere_actors:
                renderer.AddActor(actor)

        self._corner_sphere_actors = sphere_actors
        logger.info("[MPR_DIAG] Corner spheres installed (%d)", len(sphere_actors))

    def install_diag_overlays(self):
        """
        Add live diagnostic text overlays to each 2D view.
        Shows: det sign, normal angle vs baseline, focal-center dist.
        """
        if not _HAS_VTK:
            return

        for view_name in ['axial', 'sagittal', 'coronal']:
            if view_name not in self._viewer.viewers:
                continue
            renderer = self._viewer.viewers[view_name]['renderer']
            actor = create_diag_overlay_actor(
                line=f"[DIAG] {view_name}",
                position=(0.02, 0.02),
                font_size=10,
                color=(0.4, 1.0, 0.4),
            )
            renderer.AddActor2D(actor)
            self._diag_text_actors[view_name] = actor

        logger.info("[MPR_DIAG] Diagnostic overlays installed")

    def _update_diag_overlays(self, report: FrameReport):
        """Update the live text based on latest validation results."""
        for view_name, actor in self._diag_text_actors.items():
            snap = report.camera_snapshots.get(view_name)
            baseline = self._baselines.get(view_name)
            if not snap or not baseline:
                continue

            angle_deg = report.crosshair_angles_deg.get(view_name, 0.0)
            normal_angle = _signed_angle(snap.direction, baseline.direction)
            focal_dist = float(np.linalg.norm(
                snap.focal_point - report.crosshair_center))
            det = snap.det_sign

            # Check for failures
            view_fails = [v for v in report.validations
                         if not v.passed and v.view_name == view_name]
            status = "OK" if not view_fails else f"FAIL({len(view_fails)})"

            text = (
                f"det={det:+.0f} n_err={normal_angle:.1f}° "
                f"f_off={focal_dist:.2f}mm\n"
                f"ang={angle_deg:.1f}° {status}"
            )
            actor.SetInput(text)

    # ── Report access ─────────────────────────────────────────────────
    def get_last_report(self) -> Optional[FrameReport]:
        return self._last_report

    @property
    def total_violations(self) -> int:
        return self._violation_count

    @property
    def frame_count(self) -> int:
        return self._frame_count
