"""
Unified Logging for NewMPR2 and NewMPR
Provides identical log format for both viewers to enable line-by-line comparison.
"""

import vtk
import sys
from pathlib import Path
from datetime import datetime

# Global log file handle (set by initialize_log_file)
_log_file_handle = None
_log_file_path = None
_current_tag = None


def _ensure_log_file(tag="NEWMPR", dicom_dir=None, log_dir=None):
    """Lazy-initialize the log file if not already open."""
    global _log_file_handle, _log_file_path, _current_tag

    if _log_file_handle and _current_tag == tag:
        return

    initialize_log_file(tag=tag, dicom_dir=dicom_dir, log_dir=log_dir)


def initialize_log_file(tag="NEWMPR", dicom_dir=None, log_dir=None):
    """
    Initialize log file for geometry logging.
    Creates timestamped file and writes header.
    If file already open with same tag, returns early (no reopen).
    """
    global _log_file_handle, _log_file_path, _current_tag

    # If already open with same tag, don't reopen
    if _log_file_handle and _current_tag == tag:
        return _log_file_path

    # Close previous file if open
    if _log_file_handle:
        _log_file_handle.close()

    # Choose log directory
    if log_dir:
        log_dir = Path(log_dir)
    else:
        if tag == "NEWMPR2":
            # Slicer app logs live next to this file under logs/
            log_dir = Path(__file__).resolve().parent / "logs"
        else:
            # NewMPR (VTK viewer) fallback: NewMpr/logs
            log_dir = Path(__file__).resolve().parents[2] / "NewMpr" / "logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    _log_file_path = log_dir / f"{tag.lower()}_geometry_{timestamp}.txt"
    _log_file_handle = open(_log_file_path, 'w', encoding='utf-8')
    _current_tag = tag

    # Header
    _log_file_handle.write(f"{tag} Geometry Log\n")
    _log_file_handle.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    if dicom_dir:
        _log_file_handle.write(f"DICOM Directory: {dicom_dir}\n")
    _log_file_handle.write("=" * 80 + "\n\n")
    _log_file_handle.flush()

    print(f"[{tag}-LOG] File: {_log_file_path}", file=sys.stderr, flush=True)
    return _log_file_path


def close_log_file():
    """Close the log file if open."""
    global _log_file_handle, _log_file_path, _current_tag
    if _log_file_handle:
        _log_file_handle.flush()
        _log_file_handle.close()
        if _log_file_path:
            print(f"[LOG] Saved: {_log_file_path}", file=sys.stderr, flush=True)
        _log_file_handle = None
        _log_file_path = None
        _current_tag = None


def write_log(message):
    """Write to both stderr and log file."""
    print(message, file=sys.stderr, flush=True)
    if _log_file_handle:
        _log_file_handle.write(message + "\n")
        _log_file_handle.flush()


def log_volume_geometry(tag, volume_node_or_data, ijk_to_ras, name="", node_id="", dicom_dir=None, log_dir=None):
    """Log volume geometry in standardized format."""
    _ensure_log_file(tag, dicom_dir, log_dir)

    write_log(f"[{tag}-VOLUME]")

    if name:
        write_log(f"  Name: {name}")
    if node_id:
        write_log(f"  ID: {node_id}")

    # Access image data
    if hasattr(volume_node_or_data, 'GetImageData'):
        image_data = volume_node_or_data.GetImageData()
        origin = volume_node_or_data.GetOrigin()
    else:
        image_data = volume_node_or_data
        origin = image_data.GetOrigin()

    dims = image_data.GetDimensions()
    spacing = image_data.GetSpacing()

    write_log(f"  Dimensions: ({dims[0]}, {dims[1]}, {dims[2]})")
    write_log(f"  Spacing: ({spacing[0]:.6f}, {spacing[1]:.6f}, {spacing[2]:.6f})")
    write_log(f"  Origin (RAS): ({origin[0]:.4f}, {origin[1]:.4f}, {origin[2]:.4f})")

    # Center
    center_ijk = [(dims[0] - 1) / 2.0, (dims[1] - 1) / 2.0, (dims[2] - 1) / 2.0, 1.0]
    center_ras = [0.0, 0.0, 0.0, 0.0]
    ijk_to_ras.MultiplyPoint(center_ijk, center_ras)
    write_log(f"  Center (RAS): ({center_ras[0]:.4f}, {center_ras[1]:.4f}, {center_ras[2]:.4f})")

    # DIAGNOSTIC: Extract and log volume direction vectors (I, J, K in RAS)
    # Helps understand axis orientations in oblique acquisitions
    def _normalize(col_idx):
        vec = [ijk_to_ras.GetElement(r, col_idx) for r in range(3)]
        mag = (sum(v*v for v in vec))**0.5
        return tuple(v/mag if mag>0 else v for v in vec)
    
    idir = _normalize(0)
    jdir = _normalize(1)
    kdir = _normalize(2)
    
    write_log(f"  Volume direction vectors (normalized):")
    write_log(f"    I_dir (RAS): ({idir[0]:8.5f}, {idir[1]:8.5f}, {idir[2]:8.5f})")
    write_log(f"    J_dir (RAS): ({jdir[0]:8.5f}, {jdir[1]:8.5f}, {jdir[2]:8.5f})")
    write_log(f"    K_dir (RAS): ({kdir[0]:8.5f}, {kdir[1]:8.5f}, {kdir[2]:8.5f})")

    # IJKToRAS
    write_log("  IJKToRAS:")
    for i in range(4):
        row = [f"{ijk_to_ras.GetElement(i, j):10.6f}" for j in range(4)]
        write_log(f"    r{i}: [{', '.join(row)}]")

    # RASToIJK
    ras_to_ijk = vtk.vtkMatrix4x4()
    ras_to_ijk.DeepCopy(ijk_to_ras)
    ras_to_ijk.Invert()
    write_log("  RASToIJK:")
    for i in range(4):
        row = [f"{ras_to_ijk.GetElement(i, j):10.6f}" for j in range(4)]
        write_log(f"    r{i}: [{', '.join(row)}]")

    write_log("")


def log_slice_geometry(tag, view_name, slice_to_ras, xy_to_ijk=None, slice_index=None, offset_mm=None,
                      fov=None, dimensions=None, xy_to_ras=None, xy_to_volume_ijk=None,
                      xy_to_reslice_ijk=None, dicom_dir=None, log_dir=None):
    """Log slice geometry in standardized format."""
    _ensure_log_file(tag, dicom_dir, log_dir)

    write_log(f"[{tag}-SLICE view={view_name}]")

    if slice_index is not None:
        write_log(f"  SliceIndex: {slice_index}")
    if offset_mm is not None:
        write_log(f"  Offset_mm: {offset_mm:.4f}")
    if fov is not None:
        write_log(f"  FOV_mm: ({fov[0]:.2f}, {fov[1]:.2f}, {fov[2]:.2f})")
    if dimensions is not None:
        write_log(f"  ViewDimensions_px: ({dimensions[0]}, {dimensions[1]}, {dimensions[2]})")

    # DIAGNOSTIC: Extract and log slice axes (x, y, z) from SliceToRAS
    def _vec(col_idx):
        return tuple(slice_to_ras.GetElement(r, col_idx) for r in range(3))
    
    xaxis = _vec(0)
    yaxis = _vec(1)
    zaxis = _vec(2)  # slice normal
    
    write_log("  Slice axes (from SliceToRAS):")
    write_log(f"    X-axis (RAS): ({xaxis[0]:8.5f}, {xaxis[1]:8.5f}, {xaxis[2]:8.5f})")
    write_log(f"    Y-axis (RAS): ({yaxis[0]:8.5f}, {yaxis[1]:8.5f}, {yaxis[2]:8.5f})")
    write_log(f"    Z-axis/Normal: ({zaxis[0]:8.5f}, {zaxis[1]:8.5f}, {zaxis[2]:8.5f})")

    # SliceToRAS
    write_log("  SliceToRAS:")
    for i in range(4):
        row = [f"{slice_to_ras.GetElement(i, j):10.6f}" for j in range(4)]
        write_log(f"    r{i}: [{', '.join(row)}]")

    # XYToRAS
    if xy_to_ras is not None:
        write_log("  XYToRAS:")
        for i in range(4):
            row = [f"{xy_to_ras.GetElement(i, j):10.6f}" for j in range(4)]
            write_log(f"    r{i}: [{', '.join(row)}]")

    # Normalize legacy input
    xy_to_volume_ijk = xy_to_volume_ijk or xy_to_ijk

    if xy_to_volume_ijk is not None:
        write_log("  XYToVolumeIJK:")
        for i in range(4):
            row = [f"{xy_to_volume_ijk.GetElement(i, j):10.6f}" for j in range(4)]
            write_log(f"    r{i}: [{', '.join(row)}]")

    if xy_to_reslice_ijk is not None:
        write_log("  XYToResliceIJK:")
        for i in range(4):
            row = [f"{xy_to_reslice_ijk.GetElement(i, j):10.6f}" for j in range(4)]
            write_log(f"    r{i}: [{', '.join(row)}]")

    write_log("")


def compute_xy_to_ijk_slicer(slice_to_ras, ras_to_ijk, fov, dimensions, xyz_origin=(0, 0, 0)):
    """
    Compute XYToIJK matrix exactly as Slicer does.
    
    XYToIJK = RASToIJK * XYToRAS
    where XYToRAS = SliceToRAS * XYToSlice
    
    Args:
        slice_to_ras: vtkMatrix4x4 - slice orientation in RAS
        ras_to_ijk: vtkMatrix4x4 - RAS to IJK transform
        fov: (width, height, depth) field of view in mm
        dimensions: (cols, rows, slices) in pixels
        xyz_origin: (x, y, z) origin offset
        
    Returns:
        vtkMatrix4x4: XYToIJK transformation
    """
    # Build XYToSlice matrix (spacing and centering)
    xy_to_slice = vtk.vtkMatrix4x4()
    xy_to_slice.Identity()
    
    for i in range(3):
        if dimensions[i] > 0:
            spacing = fov[i] / dimensions[i]
            xy_to_slice.SetElement(i, i, spacing)
            xy_to_slice.SetElement(i, 3, -fov[i] / 2.0 + xyz_origin[i])
    
    xy_to_slice.SetElement(2, 3, 0.0)  # Z origin always 0
    
    # XYToRAS = SliceToRAS * XYToSlice
    xy_to_ras = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Multiply4x4(slice_to_ras, xy_to_slice, xy_to_ras)
    
    # XYToIJK = RASToIJK * XYToRAS
    xy_to_ijk = vtk.vtkMatrix4x4()
    vtk.vtkMatrix4x4.Multiply4x4(ras_to_ijk, xy_to_ras, xy_to_ijk)
    
    return xy_to_ijk


def log_reslice_output_geometry(tag, view_name, reslice_output_image, xy_to_ijk, fov_mm, 
                               view_dims_px, dicom_dir=None, log_dir=None):
    """
    Log the reslice output geometry (Convention B).
    
    Reslice produces a 2D image with specific spacing, origin, and extent.
    This logs those values for verification.
    
    Args:
        tag: "NEWMPR" or "NEWMPR2"
        view_name: "axial", "sagittal", "coronal"
        reslice_output_image: vtkImageData from reslice filter
        xy_to_ijk: vtkMatrix4x4 (XYToIJK transformation used)
        fov_mm: (fov_x, fov_y, fov_z) in mm
        view_dims_px: (dim_x, dim_y, dim_z) in pixels
    """
    _ensure_log_file(tag, dicom_dir, log_dir)
    
    write_log(f"[{tag}-RESLICE-OUTPUT view={view_name}]")
    
    if reslice_output_image is None:
        write_log("  ERROR: reslice_output_image is None")
        write_log("")
        return
    
    # Get geometry from vtkImageData
    extent = reslice_output_image.GetExtent()
    spacing = reslice_output_image.GetSpacing()
    origin = reslice_output_image.GetOrigin()
    dimensions = reslice_output_image.GetDimensions()
    
    write_log(f"  OutputExtent: {extent}")
    write_log(f"  OutputDimensions: {dimensions}")
    write_log(f"  OutputSpacing_mm: ({spacing[0]:.6f}, {spacing[1]:.6f}, {spacing[2]:.6f})")
    write_log(f"  OutputOrigin_mm: ({origin[0]:.6f}, {origin[1]:.6f}, {origin[2]:.6f})")
    
    # Expected values (Convention B)
    expected_spacing_x = fov_mm[0] / view_dims_px[0]
    expected_spacing_y = fov_mm[1] / view_dims_px[1]
    expected_origin_x = -fov_mm[0] / 2.0
    expected_origin_y = -fov_mm[1] / 2.0
    
    write_log(f"  Expected_Spacing_mm: ({expected_spacing_x:.6f}, {expected_spacing_y:.6f}, {fov_mm[2]:.6f})")
    write_log(f"  Expected_Origin_mm: ({expected_origin_x:.6f}, {expected_origin_y:.6f}, 0.0)")
    
    # Error checks
    spacing_err_x = abs(spacing[0] - expected_spacing_x)
    spacing_err_y = abs(spacing[1] - expected_spacing_y)
    origin_err_x = abs(origin[0] - expected_origin_x)
    origin_err_y = abs(origin[1] - expected_origin_y)
    
    write_log(f"  Spacing_error_mm: X={spacing_err_x:.6f}, Y={spacing_err_y:.6f}")
    write_log(f"  Origin_error_mm: X={origin_err_x:.6f}, Y={origin_err_y:.6f}")
    
    # Get scalar data stats
    scalars = reslice_output_image.GetPointData().GetScalars()
    if scalars and scalars.GetNumberOfTuples() > 0:
        data_range = scalars.GetRange()
        write_log(f"  Scalar_range: [{data_range[0]:.1f}, {data_range[1]:.1f}]")
        write_log(f"  Number_of_voxels: {scalars.GetNumberOfTuples()}")
        write_log(f"  Expected_voxel_count: {view_dims_px[0] * view_dims_px[1]}")
    else:
        write_log("  WARNING: No scalars in reslice output")
    
    # Log XYToIJK for reference
    write_log("  XYToIJK (reslice axes):")
    for i in range(4):
        row = [f"{xy_to_ijk.GetElement(i, j):10.6f}" for j in range(4)]
        write_log(f"    r{i}: [{', '.join(row)}]")
    
    write_log("")


def compute_and_log_dicom_slice_geometry(tag, view_name, slice_to_ras, xy_to_ras, 
                                        ijk_to_ras, ras_to_ijk, fov_mm, view_dims_px,
                                        dicom_dir=None, log_dir=None):
    """
    Compute and log synthetic DICOM-style geometry for an MPR slice.
    
    This extracts the in-plane row/column directions, pixel spacing, and slice normal
    from the XYToRAS matrix, converts to DICOM LPS convention, and logs them.
    
    Args:
        tag: "NEWMPR" or "NEWMPR2"
        view_name: "axial", "sagittal", "coronal" (or "Red", "Yellow", "Green")
        slice_to_ras: vtkMatrix4x4 - slice orientation (SliceToRAS)
        xy_to_ras: vtkMatrix4x4 - pixel-to-world transform (XYToRAS)
        ijk_to_ras: vtkMatrix4x4 - volume IJKToRAS
        ras_to_ijk: vtkMatrix4x4 - volume RASToIJK
        fov_mm: (fov_x, fov_y, fov_z) field of view
        view_dims_px: (dim_x, dim_y, dim_z) viewport dimensions
    """
    _ensure_log_file(tag, dicom_dir, log_dir)
    
    # 1. Compute world positions of pixel corners using XYToRAS
    def transform_point(matrix, x, y, z):
        pt_in = [x, y, z, 1.0]
        pt_out = [0.0, 0.0, 0.0, 0.0]
        matrix.MultiplyPoint(pt_in, pt_out)
        return pt_out[:3]
    
    p00_ras = transform_point(xy_to_ras, 0, 0, 0)  # Origin
    p10_ras = transform_point(xy_to_ras, 1, 0, 0)  # One pixel in X (row) direction
    p01_ras = transform_point(xy_to_ras, 0, 1, 0)  # One pixel in Y (column) direction
    
    # 2. Compute row and column direction vectors in RAS
    import math
    
    def vec_subtract(a, b):
        return [a[i] - b[i] for i in range(3)]
    
    def vec_length(v):
        return math.sqrt(sum(x*x for x in v))
    
    def vec_normalize(v):
        length = vec_length(v)
        if length > 0:
            return [x / length for x in v]
        return v
    
    def vec_cross(a, b):
        return [
            a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0]
        ]
    
    row_vec_ras = vec_subtract(p10_ras, p00_ras)
    col_vec_ras = vec_subtract(p01_ras, p00_ras)
    
    row_spacing = vec_length(row_vec_ras)
    col_spacing = vec_length(col_vec_ras)
    
    row_dir_ras = vec_normalize(row_vec_ras)
    col_dir_ras = vec_normalize(col_vec_ras)
    
    # 3. Compute slice normal from cross product
    normal_ras_computed = vec_normalize(vec_cross(row_dir_ras, col_dir_ras))
    
    # Also get normal from SliceToRAS column 2 for verification
    normal_ras_from_slice = [slice_to_ras.GetElement(i, 2) for i in range(3)]
    normal_ras_from_slice = vec_normalize(normal_ras_from_slice)
    
    # 4. Convert to LPS (DICOM convention): RAS→LPS = diag(-1, -1, 1)
    def ras_to_lps(v):
        return [-v[0], -v[1], v[2]]
    
    row_dir_lps = ras_to_lps(row_dir_ras)
    col_dir_lps = ras_to_lps(col_dir_ras)
    normal_lps_computed = ras_to_lps(normal_ras_computed)
    normal_lps_from_slice = ras_to_lps(normal_ras_from_slice)
    p00_lps = ras_to_lps(p00_ras)
    
    # 5. Build DICOM ImageOrientationPatient (6 values: row dir, then col dir)
    iop_lps = row_dir_lps + col_dir_lps
    
    # 6. Log everything
    write_log(f"[{tag}-SLICE-DICOM view={view_name}]")
    write_log(f"  RowDir_RAS: ({row_dir_ras[0]:9.6f}, {row_dir_ras[1]:9.6f}, {row_dir_ras[2]:9.6f})")
    write_log(f"  ColDir_RAS: ({col_dir_ras[0]:9.6f}, {col_dir_ras[1]:9.6f}, {col_dir_ras[2]:9.6f})")
    write_log(f"  Normal_RAS (computed): ({normal_ras_computed[0]:9.6f}, {normal_ras_computed[1]:9.6f}, {normal_ras_computed[2]:9.6f})")
    write_log(f"  Normal_RAS (SliceToRAS): ({normal_ras_from_slice[0]:9.6f}, {normal_ras_from_slice[1]:9.6f}, {normal_ras_from_slice[2]:9.6f})")
    write_log(f"  RowDir_LPS: ({row_dir_lps[0]:9.6f}, {row_dir_lps[1]:9.6f}, {row_dir_lps[2]:9.6f})")
    write_log(f"  ColDir_LPS: ({col_dir_lps[0]:9.6f}, {col_dir_lps[1]:9.6f}, {col_dir_lps[2]:9.6f})")
    write_log(f"  Normal_LPS (computed): ({normal_lps_computed[0]:9.6f}, {normal_lps_computed[1]:9.6f}, {normal_lps_computed[2]:9.6f})")
    write_log(f"  Normal_LPS (SliceToRAS): ({normal_lps_from_slice[0]:9.6f}, {normal_lps_from_slice[1]:9.6f}, {normal_lps_from_slice[2]:9.6f})")
    write_log(f"  ImageOrientationPatient(LPS): [{iop_lps[0]:.6f}, {iop_lps[1]:.6f}, {iop_lps[2]:.6f}, {iop_lps[3]:.6f}, {iop_lps[4]:.6f}, {iop_lps[5]:.6f}]")
    write_log(f"  ImagePositionPatient(LPS): ({p00_lps[0]:.4f}, {p00_lps[1]:.4f}, {p00_lps[2]:.4f})")
    write_log(f"  PixelSpacing: ({row_spacing:.6f}, {col_spacing:.6f})")
    
    # Optional: effective slice thickness (spacing along normal)
    # Compute world distance between z=0 and z=1 in slice coordinates
    p00z0 = transform_point(xy_to_ras, 0, 0, 0)
    p00z1 = transform_point(xy_to_ras, 0, 0, 1)
    slice_thickness = vec_length(vec_subtract(p00z1, p00z0))
    write_log(f"  EffectiveSliceThickness: {slice_thickness:.6f}")
    
    write_log("")


def log_camera_geometry(tag, view_name, camera, renderer, xy_to_ras, ijk_to_ras, ras_to_ijk, view_dims_px,
                        dicom_dir=None, log_dir=None):
    """
    Log camera and centering diagnostics in a unified format for both viewers.

    This captures camera parameters, slice center vs focal point offsets, and the
    projected slice center location. All math (row/col dirs, spacing, normals) is
    derived from XYToRAS to ensure parity between NewMPR and NewMPR2.
    """
    _ensure_log_file(tag, dicom_dir, log_dir)

    import math

    # Safeguards
    if camera is None or renderer is None or xy_to_ras is None:
        write_log(f"[{tag}-CAMERA view={view_name}] WARNING: Missing camera/renderer/XYToRAS")
        write_log("")
        return

    # Extract camera parameters
    try:
        parallel_projection = camera.GetParallelProjection()
        parallel_scale = camera.GetParallelScale()
        view_angle = camera.GetViewAngle()
        position_ras = camera.GetPosition()
        focal_point_ras = camera.GetFocalPoint()
        view_up_ras = camera.GetViewUp()
        clipping_range = camera.GetClippingRange()
        
        # NEW: WindowCenter and ViewShear (crucial for display centering)
        window_center = camera.GetWindowCenter()
        view_shear = [0.0, 0.0, 1.0]
        try:
            camera.GetViewShear(view_shear)
        except:
            view_shear = [0.0, 0.0, 1.0]
    except Exception as e:
        write_log(f"[{tag}-CAMERA view={view_name}] ERROR reading camera: {e}")
        write_log("")
        return

    # Renderer / viewport info
    try:
        viewport = renderer.GetViewport()
    except Exception:
        viewport = (0.0, 0.0, 1.0, 1.0)

    # View dimensions (pixels)
    width = view_dims_px[0] if view_dims_px and len(view_dims_px) > 0 else 0
    height = view_dims_px[1] if view_dims_px and len(view_dims_px) > 1 else 0
    cx = (width - 1) / 2.0 if width else 0.0
    cy = (height - 1) / 2.0 if height else 0.0

    # Helper math utilities
    def transform_point(matrix, x, y, z):
        pt_in = [x, y, z, 1.0]
        pt_out = [0.0, 0.0, 0.0, 0.0]
        matrix.MultiplyPoint(pt_in, pt_out)
        return pt_out[:3]

    def vec_subtract(a, b):
        return [a[i] - b[i] for i in range(3)]

    def vec_length(v):
        return math.sqrt(sum(x*x for x in v))

    def vec_normalize(v):
        length = vec_length(v)
        if length > 0:
            return [x / length for x in v]
        return [0.0, 0.0, 0.0]

    def vec_dot(a, b):
        return sum(a[i]*b[i] for i in range(3))

    def vec_cross(a, b):
        return [
            a[1]*b[2] - a[2]*b[1],
            a[2]*b[0] - a[0]*b[2],
            a[0]*b[1] - a[1]*b[0]
        ]

    # Slice corner and center in RAS
    p00_ras = transform_point(xy_to_ras, 0, 0, 0)
    p10_ras = transform_point(xy_to_ras, 1, 0, 0)
    p01_ras = transform_point(xy_to_ras, 0, 1, 0)
    p_center_ras = transform_point(xy_to_ras, cx, cy, 0)

    row_vec_ras = vec_subtract(p10_ras, p00_ras)
    col_vec_ras = vec_subtract(p01_ras, p00_ras)

    row_spacing = vec_length(row_vec_ras)
    col_spacing = vec_length(col_vec_ras)

    row_dir_ras = vec_normalize(row_vec_ras)
    col_dir_ras = vec_normalize(col_vec_ras)
    normal_ras = vec_normalize(vec_cross(row_dir_ras, col_dir_ras))

    # Offsets between camera focal point and slice center
    delta_center = vec_subtract(focal_point_ras, p_center_ras)
    center_offset_mm = vec_length(delta_center)
    offset_row = vec_dot(delta_center, row_dir_ras)
    offset_col = vec_dot(delta_center, col_dir_ras)
    offset_norm = vec_dot(delta_center, normal_ras)

    # Project slice center to display coordinates (best effort)
    center_display_px = None
    try:
        renderer.SetWorldPoint(p_center_ras[0], p_center_ras[1], p_center_ras[2], 1.0)
        renderer.WorldToDisplay()
        dp = renderer.GetDisplayPoint()
        center_display_px = (dp[0], dp[1])
    except Exception:
        center_display_px = None

    # Log block
    write_log(f"[{tag}-CAMERA view={view_name}]")
    write_log(f"  ParallelProjection: {parallel_projection}")
    write_log(f"  ParallelScale: {parallel_scale:.6f}")
    write_log(f"  ViewAngle_deg: {view_angle:.6f}")
    write_log(f"  WindowCenter: ({window_center[0]:.6f}, {window_center[1]:.6f})")
    write_log(f"  ViewShear: ({view_shear[0]:.6f}, {view_shear[1]:.6f}, {view_shear[2]:.6f})")
    write_log(f"  Position_RAS: ({position_ras[0]:.6f}, {position_ras[1]:.6f}, {position_ras[2]:.6f})")
    write_log(f"  FocalPoint_RAS: ({focal_point_ras[0]:.6f}, {focal_point_ras[1]:.6f}, {focal_point_ras[2]:.6f})")
    write_log(f"  ViewUp_RAS: ({view_up_ras[0]:.6f}, {view_up_ras[1]:.6f}, {view_up_ras[2]:.6f})")
    write_log(f"  ClippingRange_mm: ({clipping_range[0]:.6f}, {clipping_range[1]:.6f})")
    write_log(f"  Viewport_norm: ({viewport[0]:.3f}, {viewport[1]:.3f}, {viewport[2]:.3f}, {viewport[3]:.3f})")
    write_log(f"  ViewDims_px: ({width}, {height})")
    write_log(f"  DisplayCenter_px (expected): ({cx:.3f}, {cy:.3f})")
    write_log(f"  SliceCenter_RAS: ({p_center_ras[0]:.6f}, {p_center_ras[1]:.6f}, {p_center_ras[2]:.6f})")
    write_log(f"  Corner00_RAS: ({p00_ras[0]:.6f}, {p00_ras[1]:.6f}, {p00_ras[2]:.6f})")
    write_log(f"  Corner10_RAS: ({p10_ras[0]:.6f}, {p10_ras[1]:.6f}, {p10_ras[2]:.6f})")
    write_log(f"  Corner01_RAS: ({p01_ras[0]:.6f}, {p01_ras[1]:.6f}, {p01_ras[2]:.6f})")
    write_log(f"  RowDir_RAS: ({row_dir_ras[0]:.6f}, {row_dir_ras[1]:.6f}, {row_dir_ras[2]:.6f})")
    write_log(f"  ColDir_RAS: ({col_dir_ras[0]:.6f}, {col_dir_ras[1]:.6f}, {col_dir_ras[2]:.6f})")
    write_log(f"  Normal_RAS: ({normal_ras[0]:.6f}, {normal_ras[1]:.6f}, {normal_ras[2]:.6f})")
    write_log(f"  PixelSpacing_mm: ({row_spacing:.6f}, {col_spacing:.6f})")
    write_log(f"  Focal_vs_SliceCenter_offset_mm: {center_offset_mm:.6f}")
    write_log(f"  FocalOffset_along_row_mm: {offset_row:.6f}")
    write_log(f"  FocalOffset_along_col_mm: {offset_col:.6f}")
    write_log(f"  FocalOffset_along_normal_mm: {offset_norm:.6f}")
    if center_display_px is not None:
        write_log(f"  CenterDisplay_px (projected): ({center_display_px[0]:.3f}, {center_display_px[1]:.3f})")
    write_log("")
    
    # NEW: Sanity check - verify world-to-display mapping
    write_log(f"[{tag}-CAMERA-CHECK view={view_name}]")
    try:
        renderer.SetWorldPoint(p_center_ras[0], p_center_ras[1], p_center_ras[2], 1.0)
        renderer.WorldToDisplay()
        display_pt = renderer.GetDisplayPoint()
        write_log(f"  SliceCenter_Display_px: ({display_pt[0]:.3f}, {display_pt[1]:.3f})")
        write_log(f"  Expected: (~{cx:.1f}, ~{cy:.1f})")
        write_log(f"  Delta: ({display_pt[0] - cx:.3f}, {display_pt[1] - cy:.3f})")
    except Exception as e:
        write_log(f"  ERROR in world-to-display check: {e}")
    write_log("")

