"""
Stitch Engine — SimpleITK landmark-based 2D registration for radiograph stitching.

Provides stateless helper functions that:
1. Load a DICOM series and extract a single 2D slice as a ``sitk.Image``.
2. Compute a 2D rigid / similarity / affine transform from landmark pairs
   using ``LandmarkBasedTransformInitializerFilter``.
3. Resample the *moving* image into the *fixed* image coordinate space.

All operations work in **physical (mm) space** — never raw pixel indices.

Author : AI Pacs Team
Created: 2026-02-20
"""

from __future__ import annotations

import os
from typing import List, Literal

import SimpleITK as sitk


# ======================================================================
#  DICOM loading helpers
# ======================================================================

def load_series_as_2d(
    dicom_dir: str,
    slice_index: int | None = None,
) -> sitk.Image:
    """Read a DICOM series and return a single 2D ``sitk.Image``.

    Parameters
    ----------
    dicom_dir:
        Folder containing ``*.dcm`` files for **one** series.
    slice_index:
        Which slice to extract (0-based).  ``None`` → middle slice.
        For a single-frame series the parameter is ignored.

    Returns
    -------
    sitk.Image
        2-D image with correct ``Origin``, ``Spacing``, ``Direction``.
    """
    if not os.path.isdir(dicom_dir):
        raise FileNotFoundError(f"DICOM directory not found: {dicom_dir}")

    reader = sitk.ImageSeriesReader()
    reader.MetaDataDictionaryArrayUpdateOff()
    dicom_names = reader.GetGDCMSeriesFileNames(dicom_dir)
    if not dicom_names:
        raise RuntimeError(f"No DICOM files found in {dicom_dir}")

    reader.SetFileNames(dicom_names)
    volume = reader.Execute()  # may be 2-D or 3-D

    ndim = volume.GetDimension()
    size = volume.GetSize()

    if ndim == 2 or (ndim == 3 and size[2] == 1):
        # Already 2-D or single-slice 3-D — squeeze to 2-D
        if ndim == 3:
            volume = volume[:, :, 0]
        return volume

    # Multi-slice 3-D → extract requested slice
    z = size[2]
    if slice_index is None:
        slice_index = z // 2
    slice_index = max(0, min(slice_index, z - 1))

    extractor = sitk.ExtractImageFilter()
    extractor.SetSize([size[0], size[1], 0])
    extractor.SetIndex([0, 0, slice_index])
    extractor.SetDirectionCollapseToSubmatrix()
    img_2d = extractor.Execute(volume)

    del volume
    return img_2d


# ======================================================================
#  Transform computation
# ======================================================================

_TRANSFORM_MAP = {
    "rigid":      lambda: sitk.Euler2DTransform(),
    "similarity": lambda: sitk.Similarity2DTransform(),
    "affine":     lambda: sitk.AffineTransform(2),
}

_MIN_PAIRS = {
    "rigid":      4,
    "similarity": 4,
    "affine":     4,
}


def compute_transform(
    fixed_flat: List[float],
    moving_flat: List[float],
    transform_type: Literal["rigid", "similarity", "affine"] = "affine",
) -> sitk.Transform:
    """Compute a 2-D transform from corresponding landmark lists.

    Parameters
    ----------
    fixed_flat / moving_flat:
        Flattened ``[x0, y0, x1, y1, …]`` lists in **physical** coords.
    transform_type:
        ``"rigid"`` (Euler2D), ``"similarity"`` (Similarity2D), or
        ``"affine"`` (Affine2D).

    Returns
    -------
    sitk.Transform
    """
    ttype = transform_type.lower()
    if ttype not in _TRANSFORM_MAP:
        raise ValueError(
            f"Unknown transform type '{transform_type}'. "
            f"Choose from: {list(_TRANSFORM_MAP)}"
        )

    n_pairs = len(fixed_flat) // 2
    min_req = _MIN_PAIRS[ttype]
    if n_pairs < min_req:
        raise ValueError(
            f"Transform '{ttype}' requires at least {min_req} pairs, "
            f"got {n_pairs}"
        )
    if len(fixed_flat) != len(moving_flat):
        raise ValueError("Fixed and moving landmark counts differ")

    initializer = sitk.LandmarkBasedTransformInitializerFilter()
    initializer.SetFixedLandmarks(fixed_flat)
    initializer.SetMovingLandmarks(moving_flat)

    seed_transform = _TRANSFORM_MAP[ttype]()
    return initializer.Execute(seed_transform)


# ======================================================================
#  Resampling
# ======================================================================

def resample_moving(
    moving_img: sitk.Image,
    fixed_img: sitk.Image,
    transform: sitk.Transform,
    default_value: float = 0.0,
) -> sitk.Image:
    """Resample *moving_img* into *fixed_img* coordinate space.

    The returned image has the same grid geometry (origin, spacing,
    size, direction) as *fixed_img*.
    """
    return sitk.Resample(
        moving_img,
        fixed_img,
        transform,
        sitk.sitkLinear,
        default_value,
        moving_img.GetPixelID(),
    )


# ======================================================================
#  Residual / accuracy helpers
# ======================================================================

def compute_residuals(
    fixed_flat: List[float],
    moving_flat: List[float],
    transform: sitk.Transform,
) -> List[float]:
    """Compute per-landmark residual errors (mm) after transformation.

    The transform is in SimpleITK "pull" convention:
        ``T(fixed_pt) → moving_pt``

    For each landmark pair *(f, m)* the residual is::

        ‖ T(f) − m ‖₂

    Parameters
    ----------
    fixed_flat / moving_flat:
        ``[x0, y0, x1, y1, …]`` in physical coords.
    transform:
        The transform returned by ``compute_transform``.

    Returns
    -------
    List of per-landmark distances in mm.
    """
    n = len(fixed_flat) // 2
    residuals: List[float] = []
    for i in range(n):
        fx, fy = fixed_flat[i * 2], fixed_flat[i * 2 + 1]
        mx, my = moving_flat[i * 2], moving_flat[i * 2 + 1]
        tx, ty = transform.TransformPoint((fx, fy))
        dx, dy = tx - mx, ty - my
        residuals.append((dx * dx + dy * dy) ** 0.5)
    return residuals
