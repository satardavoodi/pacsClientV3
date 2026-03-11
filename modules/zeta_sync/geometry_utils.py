from __future__ import annotations

import logging
from typing import Optional, Tuple

import numpy as np
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


def _direction_matrix_from_field_data(image: vtk.vtkImageData) -> Optional[np.ndarray]:
    """Return 3x3 direction from field-data array 'DirectionMatrix' if present."""
    try:
        field_data = image.GetFieldData()
        if field_data is None:
            return None
        direction_array = field_data.GetArray("DirectionMatrix")
        if direction_array is None or direction_array.GetNumberOfTuples() < 16:
            return None
        matrix = np.zeros((3, 3), dtype=float)
        for row in range(3):
            for col in range(3):
                matrix[row, col] = float(direction_array.GetValue(row * 4 + col))
        return matrix
    except Exception:
        return None


def _is_identity_matrix(mat: np.ndarray, tol: float = 1e-6) -> bool:
    try:
        return np.allclose(mat, np.eye(3, dtype=float), atol=tol)
    except Exception:
        return False


def _direction_matrix_from_vtk(image: vtk.vtkImageData) -> Optional[np.ndarray]:
    try:
        if hasattr(image, "GetDirectionMatrix"):
            m = image.GetDirectionMatrix()
            if isinstance(m, vtk.vtkMatrix4x4):
                return np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)], dtype=float)
            if isinstance(m, vtk.vtkMatrix3x3):
                return np.array([[m.GetElement(r, c) for c in range(3)] for r in range(3)], dtype=float)
    except Exception:
        return None
    return None


def _direction_matrix_from_image(image: vtk.vtkImageData) -> np.ndarray:
    """Return 3x3 direction matrix; fall back to identity."""
    mat_vtk = _direction_matrix_from_vtk(image)
    mat_field = _direction_matrix_from_field_data(image)

    if mat_vtk is None:
        if mat_field is not None:
            return mat_field
        return np.eye(3, dtype=float)

    if mat_field is not None:
        if _is_identity_matrix(mat_vtk) and not _is_identity_matrix(mat_field):
            return mat_field

    return mat_vtk


def _direction_matrices_match(image: vtk.vtkImageData, tol: float = 1e-6) -> bool:
    """Return True if VTK direction matrix matches field-data matrix (if present)."""
    mat_vtk = _direction_matrix_from_vtk(image)
    mat_field = _direction_matrix_from_field_data(image)
    if mat_field is None:
        return True
    if mat_vtk is None:
        return False
    try:
        return np.allclose(mat_vtk, mat_field, atol=tol)
    except Exception:
        return False


def _origin_spacing(image: vtk.vtkImageData) -> Tuple[np.ndarray, np.ndarray]:
    origin = np.array(image.GetOrigin(), dtype=float)
    spacing = np.array(image.GetSpacing(), dtype=float)
    return origin, spacing


def build_ijk_to_world_matrix(image: vtk.vtkImageData) -> np.ndarray:
    """
    Returns a 4x4 affine matrix M such that:
        [x, y, z, 1]^T = M @ [i, j, k, 1]^T
    using origin, spacing, and (if available) direction matrix.
    """
    origin, spacing = _origin_spacing(image)
    direction = _direction_matrix_from_image(image)

    scale = np.diag(spacing)
    A = direction @ scale

    M = np.eye(4, dtype=float)
    M[:3, :3] = A
    M[:3, 3] = origin
    return M


def world_to_ijk(image: vtk.vtkImageData, world_pos: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """World → IJK (continuous)."""
    xw, yw, zw = float(world_pos[0]), float(world_pos[1]), float(world_pos[2])
    try:
        if hasattr(image, "TransformPhysicalPointToContinuousIndex") and _direction_matrices_match(image):
            ijk = image.TransformPhysicalPointToContinuousIndex((xw, yw, zw))
            return float(ijk[0]), float(ijk[1]), float(ijk[2])
    except Exception:
        pass

    try:
        M = build_ijk_to_world_matrix(image)
        M_inv = np.linalg.inv(M)
        world_h = np.array([xw, yw, zw, 1.0], dtype=float)
        ijk_h = M_inv @ world_h
        return float(ijk_h[0]), float(ijk_h[1]), float(ijk_h[2])
    except Exception:
        origin, spacing = _origin_spacing(image)
        i = (xw - origin[0]) / spacing[0]
        j = (yw - origin[1]) / spacing[1]
        k = (zw - origin[2]) / spacing[2]
        return float(i), float(j), float(k)


def ijk_to_world(image: vtk.vtkImageData, ijk: Tuple[float, float, float]) -> Tuple[float, float, float]:
    """IJK → World using origin, spacing, and direction."""
    try:
        M = build_ijk_to_world_matrix(image)
        ijk_h = np.array([float(ijk[0]), float(ijk[1]), float(ijk[2]), 1.0], dtype=float)
        world_h = M @ ijk_h
        return float(world_h[0]), float(world_h[1]), float(world_h[2])
    except Exception:
        origin, spacing = _origin_spacing(image)
        direction = _direction_matrix_from_image(image)
        idx = np.array([float(ijk[0]) * spacing[0], float(ijk[1]) * spacing[1], float(ijk[2]) * spacing[2]], dtype=float)
        world = origin + direction.dot(idx)
        return float(world[0]), float(world[1]), float(world[2])


def map_ijk_between_vtk_images(
    imageA: vtk.vtkImageData,
    ijkA: Tuple[float, float, float],
    imageB: vtk.vtkImageData,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float], Tuple[int, int, int]]:
    """
    Map voxel index ijkA from imageA to corresponding voxel index in imageB
    using full 4x4 affine transforms.
    """
    M_A = build_ijk_to_world_matrix(imageA)
    M_B = build_ijk_to_world_matrix(imageB)
    M_B_inv = np.linalg.inv(M_B)

    ijkA_h = np.array([float(ijkA[0]), float(ijkA[1]), float(ijkA[2]), 1.0], dtype=float)

    worldA_h = M_A @ ijkA_h
    worldA = worldA_h[:3]

    ijkB_h = M_B_inv @ np.array([worldA[0], worldA[1], worldA[2], 1.0], dtype=float)
    ijkB_float = ijkB_h[:3]
    ijkB_int = np.round(ijkB_float).astype(int)

    return (
        (float(worldA[0]), float(worldA[1]), float(worldA[2])),
        (float(ijkB_float[0]), float(ijkB_float[1]), float(ijkB_float[2])),
        (int(ijkB_int[0]), int(ijkB_int[1]), int(ijkB_int[2])),
    )


def is_ijk_in_bounds(image: vtk.vtkImageData, ijk: Tuple[int, int, int]) -> bool:
    dims = image.GetDimensions()
    return (
        0 <= ijk[0] < dims[0]
        and 0 <= ijk[1] < dims[1]
        and 0 <= ijk[2] < dims[2]
    )


def log_image_orientation(label: str, image: vtk.vtkImageData, orientation: Optional[Tuple[float, ...]] = None) -> None:
    try:
        dir_mat = _direction_matrix_from_image(image)
        if orientation is not None:
            logger.debug("[%s] ImageOrientationPatient=%s", label, orientation)
        logger.debug("[%s] DirectionMatrix=%s", label, dir_mat)
    except Exception:
        return
