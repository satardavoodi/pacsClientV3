# -*- coding: utf-8 -*-
"""Dental curved reconstruction adapter.

The professional Dental Imaging workspace must use the same geometry foundation as
the working Dental Curve MPR path, but it must not import that viewer/display layer
directly. This adapter is the narrow bridge: world-space arch points in, generated
VTK images out.
"""
from __future__ import annotations

from typing import Sequence, Tuple
import math
import os


WorldPoint = Tuple[float, float, float]


# Dual-arch / oblique panoramic (anterior-inclination fix) — DEFAULT ON for the
# professional Dental Imaging module. When a second (apical / root) arch is supplied,
# each panoramic column is sampled along the tooth long axis (crown->apex) instead of
# straight down, so forward-inclined anterior teeth keep BOTH crown and apex at a thin
# slab (no thickness-blur penalty). With no apical arch the result is single-arch and
# byte-identical. Kill switch AIPACS_DENTAL_DUAL_ARCH=0.
_DENTAL_DUAL_ARCH = os.environ.get("AIPACS_DENTAL_DUAL_ARCH", "1") != "0"


def _apical_origins_for(apical_world_points, count):
    """Per-column apex origins aligned to the crown frames (same Path3D/PlaneGenerator
    framer + count → column correspondence). Returns an (count, 3) numpy array, or None
    when dual-arch is off / no usable apical arch (=> single-arch panoramic)."""
    if not _DENTAL_DUAL_ARCH or not apical_world_points:
        return None
    apts = [tuple(float(v) for v in p[:3]) for p in apical_world_points]
    if len(apts) < 2:
        return None
    try:
        import numpy as np

        _apath, aframes = _path_frames(apts, count)
        if not aframes:
            return None
        return np.array([f[0] for f in aframes], dtype=float)
    except Exception:
        return None


def _path_length(points: Sequence[WorldPoint]) -> float:
    total = 0.0
    for i in range(1, len(points)):
        total += math.dist(points[i - 1], points[i])
    return total


def _reconstruction_params(image_data, world_points, cross_section_count: int):
    pts = [tuple(float(v) for v in p[:3]) for p in (world_points or [])]
    try:
        min_spacing = max(0.1, min(float(s) for s in image_data.GetSpacing()))
    except Exception:
        min_spacing = 0.5
    length_mm = max(_path_length(pts), min_spacing)
    try:
        density = max(0.75, min(2.5, float(os.environ.get("AIPACS_DENTAL_PANO_DENSITY", "1.05"))))
    except (TypeError, ValueError):
        density = 1.05
    try:
        max_positions = max(180, min(720, int(os.environ.get("AIPACS_DENTAL_PANO_MAX_POSITIONS", "360"))))
    except (TypeError, ValueError):
        max_positions = 360
    pano_positions = max(180, min(max_positions, int((length_mm / min_spacing) * density)))
    try:
        max_cross = max(9, min(64, int(os.environ.get("AIPACS_DENTAL_XSECTION_MAX", "48"))))
    except (TypeError, ValueError):
        max_cross = 48
    curved_slices = max(5, min(max_cross, int(cross_section_count)))
    return pts, min_spacing, pano_positions, curved_slices


def _frame_metadata(frames):
    out = []
    for origin, tangent, normal, binormal in frames or []:
        out.append({
            "origin": tuple(float(v) for v in origin[:3]),
            "tangent": tuple(float(v) for v in tangent[:3]),
            "normal": tuple(float(v) for v in normal[:3]),
            "binormal": tuple(float(v) for v in binormal[:3]),
        })
    return out


def _path_frames(world_points: Sequence[WorldPoint], count: int):
    pts = [tuple(float(v) for v in p[:3]) for p in (world_points or [])]
    if len(pts) < 2:
        return None, []
    from modules.mpr.zeta_mpr.curved_mpr import Path3D, PlaneGenerator

    path = Path3D(pts)
    frames = PlaneGenerator(path).generate_frames(max(2, int(count)))
    return path, frames


def sample_centerline_frames(world_points: Sequence[WorldPoint], count: int):
    """Return geometry frames along the same curved-MPR centerline.

    This is metadata only: it reuses the zeta MPR ``Path3D`` and
    ``PlaneGenerator`` classes, but does not reslice image data. Dental Imaging
    uses these frames to map a cross-section click back into VTK world/index
    coordinates for shared sync/reference-line behavior.
    """
    _path, frames = _path_frames(world_points, count)
    return _frame_metadata(frames)


def _generate_panoramic_uncropped(
    image_data,
    frames,
    path_length: float,
    *,
    slice_thickness_mm: float,
    slice_height_mm: float,
    projection_type: str,
    apical_origins=None,
):
    """Dental-specific panoramic builder that preserves the full path axis.

    The shared zeta generator auto-crops reconstructed images for display. That is
    fine for its own viewer, but Dental Imaging uses panorama columns and
    cross-section slices as geometry indices. Cropping the path axis breaks that
    contract, so this adapter keeps every generated frame/column.
    """
    import numpy as np
    import vtkmodules.all as vtk
    from vtkmodules.util import numpy_support
    from modules.mpr.zeta_mpr.curved_mpr import ResliceEngine

    spacing = image_data.GetSpacing()
    output_spacing = min(float(spacing[0]), float(spacing[1]), float(spacing[2]))
    num_positions = len(frames)
    thickness_pixels = int(np.ceil(float(slice_thickness_mm) / output_spacing))
    height_pixels = int(np.ceil(float(slice_height_mm) / output_spacing))
    if thickness_pixels % 2 == 1:
        thickness_pixels += 1
    if height_pixels % 2 == 1:
        height_pixels += 1

    engine = ResliceEngine(image_data)
    straightened = np.zeros((num_positions, height_pixels, thickness_pixels), dtype=np.float32)

    # Dual-arch / oblique: when an aligned apical arch is supplied, tilt each column's
    # vertical (Binormal) sampling axis crown->apex (compute_oblique_slice_axes keeps the
    # basis orthonormal + the arch tangent fixed, so along-arch geometry/measurements are
    # unchanged). No apical arch => legacy vertical sampling (byte-identical).
    use_oblique = (
        bool(_DENTAL_DUAL_ARCH)
        and apical_origins is not None
        and len(apical_origins) >= num_positions
    )
    _oblique = None
    if use_oblique:
        try:
            from modules.mpr.zeta_mpr.curved_mpr import compute_oblique_slice_axes as _oblique
        except Exception:
            _oblique = None
            use_oblique = False

    for i, (origin, tangent, normal, binormal) in enumerate(frames):
        eff_normal, eff_binormal = normal, binormal
        if use_oblique:
            tilt_vec = np.asarray(apical_origins[i], dtype=float) - np.asarray(origin, dtype=float)
            eff_normal, eff_binormal = _oblique(tangent, normal, binormal, tilt_vec)
        straightened[i, :, :] = engine._extract_orthogonal_slice_for_panoramic(
            origin,
            tangent,
            eff_normal,
            eff_binormal,
            thickness_pixels,
            height_pixels,
            output_spacing,
        )

    projection_type = projection_type or "weighted"
    if projection_type == "mean":
        panoramic = np.mean(straightened, axis=2)
    elif projection_type == "max":
        panoramic = np.max(straightened, axis=2)
    elif projection_type == "weighted":
        n = straightened.shape[2]
        if n <= 1:
            panoramic = straightened[:, :, 0]
        else:
            center = (n - 1) / 2.0
            idx = np.arange(n, dtype=np.float32)
            sigma = max(1.0, n / 4.0)
            weights = np.exp(-0.5 * ((idx - center) / sigma) ** 2).astype(np.float32)
            weights /= float(weights.sum())
            panoramic = np.tensordot(straightened, weights, axes=([2], [0]))
    else:
        raise ValueError(f"Unknown projection type: {projection_type}")

    panoramic = np.flip(panoramic, axis=1)
    try:
        from modules.mpr.zeta_mpr.curved_mpr import _apply_panoramic_unsharp

        panoramic = _apply_panoramic_unsharp(panoramic)
    except Exception:
        pass

    output = vtk.vtkImageData()
    output.SetDimensions(num_positions, height_pixels, 1)
    spacing_x = float(path_length) / max(num_positions - 1, 1)
    output.SetSpacing(spacing_x, output_spacing, 1.0)
    output.SetOrigin(0, 0, 0)
    vtk_array = numpy_support.numpy_to_vtk(panoramic.T.flatten(), deep=True)
    vtk_array.SetNumberOfComponents(1)
    output.GetPointData().SetScalars(vtk_array)
    return output


def build_curved_volume(
    image_data,
    world_points: Sequence[WorldPoint],
    *,
    cross_section_count: int,
    cross_section_size_mm: float = 80.0,
):
    """Generate only the perpendicular cross-section volume plus frame metadata."""
    pts, _min_spacing, _pano_positions, curved_slices = _reconstruction_params(
        image_data, world_points, cross_section_count
    )
    if image_data is None or len(pts) < 2:
        return None, []

    from modules.mpr.zeta_mpr.curved_mpr import ResliceEngine

    _path, frames = _path_frames(pts, curved_slices)
    curved = ResliceEngine(image_data).reslice_along_path(
        frames,
        slice_size=float(max(10.0, cross_section_size_mm)),
    )
    return curved, _frame_metadata(frames)


def build_panoramic_image(
    image_data,
    world_points: Sequence[WorldPoint],
    *,
    slab_thickness_mm: float,
    projection_type: str = "weighted",
    panoramic_height_mm: float = 80.0,
    cross_section_count: int = 18,
    apical_world_points=None,
):
    """Generate only the panoramic reconstruction.

    ``apical_world_points`` (optional) is a second arch traced along the root apices;
    when supplied and AIPACS_DENTAL_DUAL_ARCH is on, the panoramic is reconstructed
    obliquely (crown->apex per column). None => legacy single-arch panoramic.
    """
    pts, _min_spacing, pano_positions, _curved_slices = _reconstruction_params(
        image_data, world_points, cross_section_count
    )
    if image_data is None or len(pts) < 2:
        return None

    path, frames = _path_frames(pts, pano_positions)
    apical_origins = _apical_origins_for(apical_world_points, pano_positions)
    return _generate_panoramic_uncropped(
        image_data,
        frames,
        float(getattr(path, "total_length", _path_length(pts))),
        slice_thickness_mm=float(max(1.0, slab_thickness_mm)),
        slice_height_mm=float(max(10.0, panoramic_height_mm)),
        projection_type=projection_type or "weighted",
        apical_origins=apical_origins,
    )


def build_curved_reconstruction(
    image_data,
    world_points: Sequence[WorldPoint],
    *,
    slab_thickness_mm: float,
    cross_section_count: int,
    projection_type: str = "weighted",
    panoramic_height_mm: float = 80.0,
    cross_section_size_mm: float = 80.0,
    apical_world_points=None,
):
    """Generate panoramic + curved cross-section volume from world-space arch points.

    This reuses ``modules.mpr.zeta_mpr.curved_mpr.CurvedMPRGenerator``, which is the
    same engine used by the working Dental Curve MPR. The caller owns display layout;
    this adapter only returns geometry-correct VTK image data. ``apical_world_points``
    (optional) enables the dual-arch oblique panoramic (see ``build_panoramic_image``).
    """
    pts, _min_spacing, pano_positions, curved_slices = _reconstruction_params(
        image_data, world_points, cross_section_count
    )
    if image_data is None or len(pts) < 2:
        return None, None

    from modules.mpr.zeta_mpr.curved_mpr import ResliceEngine

    pano_path, pano_frames = _path_frames(pts, pano_positions)
    apical_origins = _apical_origins_for(apical_world_points, pano_positions)
    panoramic = _generate_panoramic_uncropped(
        image_data,
        pano_frames,
        float(getattr(pano_path, "total_length", _path_length(pts))),
        slice_thickness_mm=float(max(1.0, slab_thickness_mm)),
        slice_height_mm=float(max(10.0, panoramic_height_mm)),
        projection_type=projection_type or "weighted",
        apical_origins=apical_origins,
    )
    _cross_path, cross_frames = _path_frames(pts, curved_slices)
    curved = ResliceEngine(image_data).reslice_along_path(
        cross_frames,
        slice_size=float(max(10.0, cross_section_size_mm)),
    )
    return panoramic, curved
