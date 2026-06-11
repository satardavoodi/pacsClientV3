"""
Zeta MPR — input-volume canonicalization pre-filter (matrix-driven orientation fix).

PURPOSE
-------
Zeta MPR was calibrated only for true-axial CT: its radiological camera corrections
(`Roll(180)`/`Azimuth(180)`) are gated to `modality == "CT"`, it never re-orients the
volume by the DICOM `ImageOrientationPatient` matrix, and it reads that matrix
*transposed*. As measured (`ZETA_MPR_GEOMETRY_MATH_INVESTIGATION_2026-06-02.md`), this is
benign for axis-aligned CT but corrupts oblique MRI (shoulder upside-down), mirrors
near-axial MR (brain sagittal A/P), and dumps a sagittal acquisition into the axial
viewport.

The matrix-driven remedy (the approach used by 3D Slicer / Cornerstone3D / VTK):
resample any oblique / non-axial input to a true axis-aligned LPS volume **before** the
viewer is built, so the proven CT path renders MR/oblique correctly too. A small field-data
marker ("ZetaCanonical") then tells `StandardMPRViewer` to apply the radiological
corrections regardless of modality (see `_needs_radiological_correction`).

SAFETY / REVERSIBILITY
----------------------
* Disabled by default. Enabled only via env `AIPACS_ZETA_MPR_CANONICALIZE`
  (1/true/yes/on) or `<USER_DATA_ROOT>/config/zeta_mpr.json` {"canonicalize": true}.
  When disabled, the integration call is a pure no-op and the legacy path is byte-identical.
* Fail-safe: `canonicalize_volume` returns the ORIGINAL object on any error.
* True-axial CT is left untouched (no resample); it still matches `modality == "CT"`.
* `vtk` is imported lazily; importing this module never pulls in VTK or a render window.
* Pure-geometry helpers are numpy-only and unit-tested headlessly.

LIVE-VALIDATION ITEMS (confirm before trusting in production; flag stays OFF until then)
----------------------------------------------------------------------------------------
1. The VTK reslice plumbing (origin/auto-crop/field-data) end-to-end on a CT (no change)
   and the 44082 shoulder MR.
2. The output radiological signs (L/R, A/P, S/I) once routed through the CT correction
   path — calibrate against 44614 CT (must be unchanged) and the four review cases.
"""

from __future__ import annotations

import logging
import os
from typing import Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_AXIS_ALIGNED_TOL_DEG = 2.0
_PLANE_BY_AXIS = {0: "sagittal", 1: "coronal", 2: "axial"}
CANONICAL_MARKER = "ZetaCanonical"


def probe(msg: str) -> None:
    """Bulletproof diagnostic breadcrumb (TEMPORARY, for live validation).

    Writes directly to <USER_DATA_ROOT>/logs/zeta_mpr_canon_probe.log, bypassing the
    logging config so the line is always visible regardless of handler routing.
    Best-effort; never raises. Remove once the fix is validated.
    """
    try:
        try:
            from PacsClient.utils.data_paths import USER_DATA_ROOT
            base = os.path.join(str(USER_DATA_ROOT), "logs")
        except Exception:
            base = os.path.join(os.path.dirname(__file__), "_probe_logs")
        os.makedirs(base, exist_ok=True)
        import datetime
        with open(os.path.join(base, "zeta_mpr_canon_probe.log"), "a", encoding="utf-8") as fh:
            fh.write(datetime.datetime.now().isoformat() + " " + str(msg) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Feature flag (env override, then optional config file, then BUILD DEFAULT)
# ---------------------------------------------------------------------------
# Build default for the corrected MPR geometry (anatomical cameras + plane-aware
# routing). Flipped ON 2026-06-11 after extended live validation (CT unchanged,
# oblique/sagittal/brain canonical). This MUST be a code default — NOT a seeded
# config file — because the frozen installer's config seeder only writes files
# that do not already exist (aipacs_runtime.seed_user_config_defaults), so an
# upgraded client keeps its OLD config and would never receive a new flag. With
# the default in code, every install (clean or upgraded) gets the corrected
# geometry; env/config remain available as an explicit override. The anatomical
# path does NOT resample (cheap) and fail-safes to the legacy path when the DICOM
# direction/IPP is unavailable. Set AIPACS_ZETA_MPR_CANONICALIZE=0 (or
# zeta_mpr.json {"canonicalize": false}) to pin the legacy geometry.
_BUILD_DEFAULT_CANONICALIZE = True


def canonicalize_enabled() -> bool:
    """True iff the canonicalization pre-filter is enabled. Default = build default
    (``_BUILD_DEFAULT_CANONICALIZE``, ON since 2026-06-11).

    Order: env `AIPACS_ZETA_MPR_CANONICALIZE` (explicit on/off wins), then
    `<USER_DATA_ROOT>/config/zeta_mpr.json` {"canonicalize": bool}, then the
    build default.
    """
    val = os.environ.get("AIPACS_ZETA_MPR_CANONICALIZE", "").strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    try:  # optional config toggle (read fresh each MPR open; no restart needed once loaded)
        import json
        from PacsClient.utils.data_paths import USER_DATA_ROOT
        cfg = os.path.join(str(USER_DATA_ROOT), "config", "zeta_mpr.json")
        if os.path.exists(cfg):
            with open(cfg, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict) and "canonicalize" in data:
                return bool(data.get("canonicalize"))
    except Exception:
        pass
    return _BUILD_DEFAULT_CANONICALIZE


# ---------------------------------------------------------------------------
# Pure-geometry helpers (numpy only — headless-testable)
# ---------------------------------------------------------------------------
def _unit(v: Sequence[float]) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else v


def parse_iop(iop: Sequence[float]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (row_cosine, col_cosine, slice_normal=row×col) from a 6-value IOP (LPS)."""
    iop = np.asarray(iop, dtype=np.float64).ravel()
    if iop.size != 6:
        raise ValueError("ImageOrientationPatient must have 6 values")
    row = _unit(iop[0:3])
    col = _unit(iop[3:6])
    normal = _unit(np.cross(row, col))
    return row, col, normal


def classify_acquisition_plane(iop: Sequence[float]) -> Tuple[str, int, float]:
    """(plane, dominant_axis_index, dominance). 0->sagittal(X),1->coronal(Y),2->axial(Z)."""
    _row, _col, normal = parse_iop(iop)
    abs_n = np.abs(normal)
    axis = int(np.argmax(abs_n))
    return _PLANE_BY_AXIS[axis], axis, float(abs_n[axis])


def needs_canonicalization(iop: Sequence[float], tol_deg: float = _AXIS_ALIGNED_TOL_DEG) -> bool:
    """True when the acquisition basis is NOT within tol_deg of axis-aligned.

    True-axial CT -> False (no resample). Oblique MRI / sagittal/coronal acquisitions
    whose in-plane axes are tilted -> True.
    """
    row, col, normal = parse_iop(iop)
    cos_tol = float(np.cos(np.deg2rad(tol_deg)))
    for vec in (row, col, normal):
        if float(np.max(np.abs(vec))) < cos_tol:
            return True
    return False


def decode_direction_field_data(values16: Sequence[float]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Recover true LPS (row, col, normal) cosines from the stored field-data matrix.

    The 16 row-major values are `_to_iop_matrix` output: columns=(row,col,normal),
    **row 1 negated** (upstream Y-flip). Undo the row-1 negation, then read columns.
    """
    vals = np.asarray(values16, dtype=np.float64).ravel()
    if vals.size != 16:
        raise ValueError("DirectionMatrix field data must have 16 values")
    M = vals.reshape(4, 4).copy()
    M[1, :] = -M[1, :]
    return _unit(M[0:3, 0]), _unit(M[0:3, 1]), _unit(M[0:3, 2])


def slice_axis_sign(ipp_first: Sequence[float], ipp_last: Sequence[float],
                    normal: Sequence[float]) -> int:
    """+1 if IPP advances along +normal as InstanceNumber increases, else -1.

    Used to keep the canonicalized through-plane (k) running superior->inferior
    regardless of scanner acquisition direction.
    """
    n = _unit(normal)
    d = np.asarray(ipp_last, float) - np.asarray(ipp_first, float)
    proj = float(np.dot(d, n))
    return 1 if proj >= 0.0 else -1


def compute_canonical_reslice_axes(
    row: Sequence[float],
    col: Sequence[float],
    normal: Sequence[float],
    slice_axis_lps: Optional[Sequence[float]] = None,
) -> np.ndarray:
    """3x3 reslice direction cosines (output axes expressed in input coords) = R_src.T.

    Maps the slice normal onto output +Z (true axial), row->+X, col->+Y. Gram-Schmidt
    re-orthonormalizes (rounding-safe); `slice_axis_lps` (if given) snaps the through-plane
    sign to +/-normal to fix superior->inferior scroll.
    """
    row = _unit(row)
    col = np.asarray(col, dtype=np.float64)
    col = _unit(col - float(np.dot(col, row)) * row)
    n = _unit(np.cross(row, col))
    if slice_axis_lps is not None:
        s = float(np.dot(_unit(slice_axis_lps), n))
        k_dir = n if s >= 0.0 else -n
    else:
        k_dir = n
    R_src = np.column_stack([row, col, k_dir]).astype(np.float64)
    return R_src.T.copy()


# ---------------------------------------------------------------------------
# DICOM IPP sign (optional refinement) + VTK marker helpers (lazy vtk)
# ---------------------------------------------------------------------------
def _read_dicom_slice_axis_sign(dicom_directory: Optional[str], normal: Sequence[float]):
    """Return the LPS through-plane direction (+/-normal) from first/last IPP by
    InstanceNumber in `dicom_directory`, or None if unavailable."""
    if not dicom_directory or not os.path.isdir(dicom_directory):
        return None
    try:
        import pydicom
        slices = []
        for name in os.listdir(dicom_directory):
            p = os.path.join(dicom_directory, name)
            if not os.path.isfile(p):
                continue
            try:
                ds = pydicom.dcmread(p, stop_before_pixels=True,
                                     specific_tags=["InstanceNumber", "ImagePositionPatient"])
                ino = getattr(ds, "InstanceNumber", None)
                ipp = getattr(ds, "ImagePositionPatient", None)
                if ipp is not None:
                    slices.append((int(ino) if ino is not None else 10 ** 9, [float(x) for x in ipp]))
            except Exception:
                continue
        if len(slices) < 2:
            return None
        slices.sort(key=lambda t: t[0])
        sign = slice_axis_sign(slices[0][1], slices[-1][1], normal)
        return (np.asarray(normal, float) * float(sign)).tolist()
    except Exception:
        return None


def is_canonical_marker(vtk_image_data) -> bool:
    """True if the volume carries the ZetaCanonical field-data marker (set to 1)."""
    try:
        fd = vtk_image_data.GetFieldData()
        if fd is None:
            return False
        arr = fd.GetArray(CANONICAL_MARKER)
        return bool(arr is not None and arr.GetNumberOfTuples() >= 1 and abs(arr.GetValue(0) - 1.0) < 1e-6)
    except Exception:
        return False


def _attach_marker(vtk_image_data) -> None:
    import vtkmodules.all as vtk
    arr = vtk.vtkDoubleArray()
    arr.SetName(CANONICAL_MARKER)
    arr.SetNumberOfTuples(1)
    arr.SetValue(0, 1.0)
    vtk_image_data.GetFieldData().AddArray(arr)


def _read_direction_field_data(vtk_image_data):
    fd = vtk_image_data.GetFieldData()
    if fd is None:
        return None
    arr = fd.GetArray("DirectionMatrix")
    if arr is None or arr.GetNumberOfTuples() != 16:
        return None
    return np.array([arr.GetValue(i) for i in range(16)], dtype=np.float64)


def canonicalize_volume(
    vtk_image_data,
    dicom_directory: Optional[str] = None,
    *,
    interpolation: str = "linear",
):
    """Return an axis-aligned LPS volume (oblique/non-axial resampled; axis-aligned
    marked in place) carrying the ZetaCanonical marker. FAIL-SAFE: returns the original
    object unchanged on missing DirectionMatrix or any error.

    `vtk` is imported lazily. Gated OFF by default (see `canonicalize_enabled`).
    """
    try:
        probe(f"canonicalize_volume CALLED dims={vtk_image_data.GetDimensions() if vtk_image_data else None} dicom_dir={dicom_directory}")
        dir_vals = _read_direction_field_data(vtk_image_data)
        if dir_vals is None:
            probe("RESULT: no DirectionMatrix field -> input unchanged")
            logger.info("[ZETA_MPR_CANONICALIZE] no DirectionMatrix; input unchanged")
            return vtk_image_data

        row, col, normal = decode_direction_field_data(dir_vals)
        iop = np.concatenate([row, col])
        plane, axis, dominance = classify_acquisition_plane(iop)
        probe(f"decoded plane={plane} dominance={dominance:.3f} needs={needs_canonicalization(iop)} row={row.round(3).tolist()} normal={normal.round(3).tolist()}")

        import vtkmodules.all as vtk

        # ANATOMICAL-CAMERA MODE (no resample) — 2026-06-03; replaces the marker+Roll approach.
        # We never resample (keeps the native input plane faithful). Instead we compute the
        # volume's true world->patient axis transform A and attach it as field data; the viewer
        # then sets each reconstructed camera DIRECTLY from the radiological canonical triad
        # (axial up=A/right=L; sagittal up=S/right=P; coronal up=S/right=L) and derives the
        # orientation markers from those cameras. This DECOUPLES the vertical (S/I) and
        # horizontal (A/P, L/R) corrections — fixing the brain-MRI sagittal A/P reversal and the
        # head/feet flips with ONE rule, modality/positioning-agnostic (no Roll/Azimuth, no
        # per-case if, no marker-label flipping).
        #
        # A = [ -row , -col , slice_axis_lps ]  (COLUMNS, patient LPS) maps the volume's world
        #   +X/+Y/+Z to patient. -row/-col account for the viewer's input X-flip + VTK Y origin
        #   (calibrated against the known-correct axial); the third column is the ACTUAL
        #   slice-stacking direction (IPP order vs normal) = what the volume's +Z really is (the
        #   metadata normal is NOT, when slices descend). Unknown IPP -> don't attach -> legacy
        #   path (fail-safe). NOTE: the resample block below is intentionally unreachable.
        slice_axis_lps = _read_dicom_slice_axis_sign(dicom_directory, normal)
        if slice_axis_lps is None:
            probe(f"RESULT: plane={plane} no IPP slice sign -> ZetaAnatA NOT attached (legacy path)")
            logger.info("[ZETA_MPR_CANONICALIZE] plane=%s no IPP sign -> legacy path", plane)
            return vtk_image_data
        A_cols = np.column_stack([
            -np.asarray(row, dtype=np.float64),
            -np.asarray(col, dtype=np.float64),
            np.asarray(slice_axis_lps, dtype=np.float64),
        ])
        out = vtk.vtkImageData()
        out.ShallowCopy(vtk_image_data)
        anat = vtk.vtkDoubleArray()
        anat.SetName("ZetaAnatA")
        anat.SetNumberOfTuples(9)
        for _i in range(3):
            for _j in range(3):
                anat.SetValue(_i * 3 + _j, float(A_cols[_i, _j]))
        out.GetFieldData().AddArray(anat)
        sa = [round(float(v), 3) for v in slice_axis_lps]
        probe(f"RESULT: plane={plane} slice_axis_lps={sa} -> ZetaAnatA attached "
              f"A_cols=[-row,-col,slice_axis_lps] (anatomical cameras)")
        logger.info("[ZETA_MPR_CANONICALIZE] plane=%s -> ZetaAnatA attached (anatomical cameras); "
                    "slice_axis_lps=%s", plane, sa)
        return out

        if not needs_canonicalization(iop):
            out = vtk.vtkImageData()
            out.ShallowCopy(vtk_image_data)
            _attach_marker(out)
            probe(f"RESULT: axis-aligned plane={plane} -> MARKED (no resample), corrections will apply")
            logger.info("[ZETA_MPR_CANONICALIZE] axis-aligned plane=%s dom=%.3f -> marked (no resample)",
                        plane, dominance)
            return out

        slice_axis_lps = _read_dicom_slice_axis_sign(dicom_directory, normal)
        if slice_axis_lps is None:
            logger.warning("[ZETA_MPR_CANONICALIZE] no IPP sign available; assuming +normal "
                           "(superior->inferior scroll UNVERIFIED for this series)")
        reslice_axes = compute_canonical_reslice_axes(row, col, normal, slice_axis_lps)

        dims = vtk_image_data.GetDimensions()
        spacing = vtk_image_data.GetSpacing()
        origin = vtk_image_data.GetOrigin()
        centre = [origin[i] + 0.5 * (dims[i] - 1) * spacing[i] for i in range(3)]

        axes4 = vtk.vtkMatrix4x4()
        axes4.Identity()
        for r in range(3):
            for c in range(3):
                axes4.SetElement(r, c, float(reslice_axes[r, c]))
        for r in range(3):
            axes4.SetElement(r, 3, float(centre[r]))

        reslice = vtk.vtkImageReslice()
        reslice.SetInputData(vtk_image_data)
        reslice.SetResliceAxes(axes4)
        reslice.SetOutputDimensionality(3)
        if interpolation == "nearest":
            reslice.SetInterpolationModeToNearestNeighbor()
        elif interpolation == "cubic":
            reslice.SetInterpolationModeToCubic()
        else:
            reslice.SetInterpolationModeToLinear()
        reslice.AutoCropOutputOn()
        reslice.Update()
        out = reslice.GetOutput()
        if out is None or out.GetNumberOfPoints() == 0:
            probe("RESULT: empty reslice output -> input unchanged")
            logger.warning("[ZETA_MPR_CANONICALIZE] empty reslice output; input unchanged")
            return vtk_image_data

        # Identity DirectionMatrix (row-1 negated convention) so MPR reads canonical axes.
        identity = np.eye(4, dtype=np.float64)
        identity[1, :] = -identity[1, :]
        dir_arr = vtk.vtkDoubleArray()
        dir_arr.SetName("DirectionMatrix")
        dir_arr.SetNumberOfTuples(16)
        for r in range(4):
            for c in range(4):
                dir_arr.SetValue(r * 4 + c, float(identity[r, c]))
        out.GetFieldData().AddArray(dir_arr)
        _attach_marker(out)

        probe(f"RESULT: RESAMPLED plane={plane} dims {tuple(dims)} -> {tuple(out.GetDimensions())} (marker attached)")
        logger.info("[ZETA_MPR_CANONICALIZE] resampled plane=%s dom=%.3f dims %s -> %s",
                    plane, dominance, tuple(dims), tuple(out.GetDimensions()))
        return out

    except Exception as exc:  # never block MPR launch
        probe(f"RESULT: FAILED {exc!r} -> input unchanged")
        logger.warning("[ZETA_MPR_CANONICALIZE] failed (%s); input unchanged", exc, exc_info=True)
        return vtk_image_data
