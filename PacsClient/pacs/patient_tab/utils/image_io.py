import os
import gc
import math
import time
import warnings
import sys
import logging
import importlib.metadata as importlib_metadata
import numpy as np

import SimpleITK as sitk
import pydicom
import vtkmodules.all as vtk
from pathlib import Path
from . import utils
from .advanced_geometry_contract import (
    build_series_geometry_index,
    get_series_geometry_index,
    stamp_metadata_with_geometry_index,
)
from .image_filters import apply_filters

# import utils
sitk.ProcessObject.SetGlobalWarningDisplay(False)
sitk.ImageSeriesReader.SetGlobalWarningDisplay(False)
from natsort import natsorted
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, get_series_by_study_pk, \
    get_instances_by_series_pk, get_series_by_series_pk, find_series_pk, get_study_by_study_uid, \
    update_study_counts_by_uid, get_series_path_with_study_pk_and_series_number
from database.core import get_db_connection
from modules.viewer.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_PYDICOM_QT,
    BACKEND_VTK,
    resolve_viewer_backend,
)
from modules.viewer.fast.pydicom_lazy_volume import PyDicomLazyVolume
from modules.viewer.fast.lazy_volume_registry import get_loader
import gc
from .utils import find_series_folder_by_series_number
from PacsClient.utils.diagnostic_logging import now_ms, log_stage_timing

# Suppress noisy ResourceWarning from external libraries during GC
warnings.filterwarnings("ignore", category=ResourceWarning)

# Guard against Windows codepage print failures (e.g., cp1256) in debug logs.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(errors="replace")
except Exception:
    pass


logger = logging.getLogger(__name__)

# ── Phase 7: viewer-side resource probe (module-level throttle, max 1 per 5 s) ──
_VIEWER_RESOURCE_PROBE_LAST_T: float = 0.0


def _emit_viewer_resource_probe() -> None:
    """Throttled psutil probe for the main viewer process → viewer_diagnostics.log."""
    global _VIEWER_RESOURCE_PROBE_LAST_T
    import time as _time
    _now = _time.monotonic()
    if _now - _VIEWER_RESOURCE_PROBE_LAST_T < 5.0:
        return
    _VIEWER_RESOURCE_PROBE_LAST_T = _now
    try:
        import psutil
        proc = psutil.Process()
        rss_mb = proc.memory_info().rss / (1024.0 * 1024.0)
        available_ram_mb = psutil.virtual_memory().available / (1024.0 * 1024.0)
        subprocess_count = len(proc.children(recursive=True))
        thread_count = proc.num_threads()
        log_stage_timing(
            logger,
            component="viewer",
            function="image_io.load_single_series_by_number",
            stage="resource_probe",
            start_ms=now_ms(),
            process_rss_mb=f"{rss_mb:.2f}",
            available_ram_mb=f"{available_ram_mb:.2f}",
            subprocess_count=subprocess_count,
            thread_count=thread_count,
            viewer_mode="Shared",
            query_type="resource_probe",
            level=logging.WARNING,
            min_ms=0.0,
        )
    except Exception:
        return


def _is_itk_region_mismatch_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "requested region is (at least partially) outside the largest possible region" in msg
        or ("largest possible region" in msg and "requested region" in msg)
        or "input image information has changed" in msg
        # v2.2.3.3.8: ITK ImageSeriesReader raises "Size mismatch" when files
        # in a series have different dimensions (e.g., incomplete download
        # leaves a truncated/wrong-size file).  Without this check the
        # dominant-size filter in get_itk_image() never triggers, causing
        # 3-4 redundant full-read retries that block warmup workers for
        # 5-12 seconds per failing series.
        or "size mismatch" in msg
        or "does not match the required size" in msg
    )


def _select_dominant_size_dicom_files(dicom_names):
    """Keep only the dominant Rows×Columns cohort, preserving input order."""
    size_buckets = {}
    unknown_size_files = []

    for path_obj in dicom_names:
        path = str(path_obj)
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True, specific_tags=['Rows', 'Columns'])
            rows = int(getattr(ds, 'Rows', 0) or 0)
            cols = int(getattr(ds, 'Columns', 0) or 0)
            if rows > 0 and cols > 0:
                key = (rows, cols)
                if key not in size_buckets:
                    size_buckets[key] = []
                size_buckets[key].append(path)
            else:
                unknown_size_files.append(path)
        except Exception:
            unknown_size_files.append(path)

    if not size_buckets:
        return [str(p) for p in dicom_names], None, {}

    dominant_size, dominant_files = max(size_buckets.items(), key=lambda kv: len(kv[1]))
    if unknown_size_files:
        dominant_files = dominant_files + unknown_size_files

    skipped = {
        f"{size[0]}x{size[1]}": len(files)
        for size, files in size_buckets.items()
        if size != dominant_size
    }
    return dominant_files, dominant_size, skipped


def _execute_series_reader(dicom_names, use_gdcm: bool = False):
    reader = sitk.ImageSeriesReader()
    reader.MetaDataDictionaryArrayUpdateOff()
    reader.SetFileNames([str(p) for p in dicom_names])
    if use_gdcm:
        try:
            reader.SetImageIO("GDCMImageIO")
        except Exception:
            pass
    image = reader.Execute()
    del reader
    return image


def get_orientation(itk_image):
    orientation = utils.determine_orientation(itk_image)
    return orientation


def get_itk_image(dicom_names):
    """
    OPTIMIZED: Fast DICOM series reading with SimpleITK
    Uses parallel reading for large series
    """
    import time
    _start = time.time()
    
    file_names = [str(p) for p in dicom_names]

    # For large series (>50 files), use optimized reading strategy
    if len(file_names) > 50:
        try:
            itk_image = _execute_series_reader(file_names, use_gdcm=True)
            
            _elapsed = time.time() - _start
            print(f"         Parallel DICOM read: {len(file_names)} files in {_elapsed:.3f}s ({len(file_names)/_elapsed:.0f} fps)")
            
            return itk_image
            
        except Exception as e:
            if _is_itk_region_mismatch_error(e):
                fallback_files, dominant_size, skipped = _select_dominant_size_dicom_files(file_names)
                if fallback_files and len(fallback_files) < len(file_names):
                    print(
                        f"         WARN: Mixed-size DICOM series detected after parallel read; "
                        f"using dominant {dominant_size} with {len(fallback_files)} files, skipping {skipped}"
                    )
                    return _execute_series_reader(fallback_files, use_gdcm=False)
            print(f"         WARN: Parallel read failed ({e}), using standard method")
            # Fall back to standard method
    
    # Standard method for small series
    try:
        return _execute_series_reader(file_names, use_gdcm=False)
    except Exception as e:
        if _is_itk_region_mismatch_error(e):
            fallback_files, dominant_size, skipped = _select_dominant_size_dicom_files(file_names)
            if fallback_files and len(fallback_files) < len(file_names):
                print(
                    f"         WARN: Mixed-size DICOM series detected; "
                    f"using dominant {dominant_size} with {len(fallback_files)} files, skipping {skipped}"
                )
                if len(fallback_files) == 1:
                    return sitk.ReadImage(fallback_files[0])
                return _execute_series_reader(fallback_files, use_gdcm=False)
        raise


# ✅ NEW: Cache for series metadata to avoid redundant DB queries
_series_metadata_cache = {}
_series_geometry_index_cache = {}
_cache_max_size = 100  # Maximum number of cached series
_LAST_GC_TS = 0.0
_GC_INTERVAL_SEC = 120.0  # was 20s → 120s: gc.collect is stop-the-world and freezes ALL threads (UI included)
_DECODER_PREFLIGHT_LOGGED = False


def _geometry_index_cache_key(dicom_files) -> str:
    normalized = sorted(
        str(path or "").replace("\\", "/").lower()
        for path in (dicom_files or [])
        if str(path or "").strip()
    )
    return _compute_path_list_hash(normalized)


def _get_or_build_series_geometry_index(
    dicom_files,
    *,
    patient_code: str = "",
    study_uid: str = "",
    series_uid: str = "",
    series_number: str = "",
    source: str,
):
    cache_key = _geometry_index_cache_key(dicom_files)
    cached_payload = _series_geometry_index_cache.get(cache_key)
    geometry_index, cache_hit = build_series_geometry_index(
        [str(path) for path in (dicom_files or [])],
        patient_code=patient_code,
        study_uid_hint=study_uid,
        series_uid_hint=series_uid,
        series_number_hint=series_number,
        source=source,
        cache_payload=cached_payload,
    )
    if not cache_hit:
        if len(_series_geometry_index_cache) >= _cache_max_size:
            _series_geometry_index_cache.pop(next(iter(_series_geometry_index_cache)))
        _series_geometry_index_cache[cache_key] = geometry_index.to_dict()
    return geometry_index, cache_hit


def _list_unique_dicom_files(folder: Path) -> list:
    """Return unique DICOM files under folder (case-insensitive), naturally sorted."""
    try:
        # Single-pass scandir is cheaper than dual glob+materialize for large series folders.
        uniq = []
        seen = set()
        for entry in os.scandir(str(folder)):
            if not entry.is_file():
                continue
            name = entry.name
            if not name.lower().endswith('.dcm'):
                continue
            p = Path(entry.path)
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        return natsorted(uniq)
    except Exception:
        return []


def _count_dicom_files_fast(folder: Path) -> int:
    """Count DICOM files with os.scandir to avoid materializing full path lists."""
    try:
        count = 0
        for entry in os.scandir(str(folder)):
            if not entry.is_file():
                continue
            name = entry.name.lower()
            if name.endswith('.dcm'):
                count += 1
        return count
    except Exception:
        return 0


def _ensure_series_meta(metadata: dict) -> dict:
    if not isinstance(metadata, dict):
        return {}
    series_meta = metadata.get("series")
    if not isinstance(series_meta, dict):
        series_meta = {}
        metadata["series"] = series_meta
    return series_meta


def _annotate_backend_metadata(metadata: dict, backend: str, lazy_loader_key: str = "") -> None:
    series_meta = _ensure_series_meta(metadata)
    if not series_meta:
        return
    series_meta["viewer_backend"] = str(backend or BACKEND_VTK)
    if lazy_loader_key:
        series_meta["lazy_loader_key"] = str(lazy_loader_key)
        series_meta["viewer_backend_label"] = "PyDicom 2D"
    else:
        series_meta.pop("lazy_loader_key", None)
        series_meta.pop("viewer_backend_label", None)


def _validate_lazy_geometry(metadata: dict) -> tuple:
    try:
        instances = list((metadata or {}).get("instances", []) or [])
        if not instances:
            return False, "no_instances"

        # Validate a small sample (first + last) to avoid full scan overhead.
        sample = [instances[0]]
        if len(instances) > 1:
            sample.append(instances[-1])

        for inst in sample:
            iop = inst.get("image_orientation_patient")
            ipp = inst.get("image_position_patient")
            ps = inst.get("pixel_spacing")
            rows = int(inst.get("rows", 0) or 0)
            cols = int(inst.get("columns", 0) or 0)
            if iop is None or len(iop) < 6:
                return False, "missing_image_orientation_patient"
            if ipp is None or len(ipp) < 3:
                return False, "missing_image_position_patient"
            if ps is None or len(ps) < 2:
                return False, "missing_pixel_spacing"
            if rows <= 0 or cols <= 0:
                return False, "missing_rows_columns"
        return True, ""
    except Exception as e:
        return False, f"geometry_validation_error:{e}"


def _decode_dependency_hint() -> str:
    return (
        "Install runtime decoders: pydicom + pylibjpeg, pylibjpeg-libjpeg, "
        "pylibjpeg-openjpeg, pylibjpeg-rle (optional fallback: python-gdcm)."
    )


def _missing_decoder_packages() -> list:
    required = [
        "pydicom",
        "pylibjpeg",
        "pylibjpeg-libjpeg",
        "pylibjpeg-openjpeg",
        "pylibjpeg-rle",
    ]
    missing = []
    for pkg in required:
        try:
            importlib_metadata.version(pkg)
        except Exception:
            missing.append(pkg)
    return missing


def _safe_float(value, default=None):
    try:
        if value is None:
            return default
        if isinstance(value, (list, tuple)):
            if not value:
                return default
            value = value[0]
        return float(value)
    except Exception:
        return default


def _safe_float_list(value, min_len):
    try:
        seq = list(value)
        if len(seq) < int(min_len):
            return None
        return [float(seq[i]) for i in range(int(min_len))]
    except Exception:
        return None


def _direction_from_iop(iop):
    vals = _safe_float_list(iop, 6)
    if vals is None:
        return None
    row = np.asarray(vals[0:3], dtype=float)
    col = np.asarray(vals[3:6], dtype=float)
    row_n = float(np.linalg.norm(row))
    col_n = float(np.linalg.norm(col))
    if row_n <= 1e-9 or col_n <= 1e-9:
        return None
    row = row / row_n
    col = col / col_n
    normal = np.cross(row, col)
    normal_n = float(np.linalg.norm(normal))
    if normal_n <= 1e-9:
        return None
    normal = normal / normal_n
    # Legacy DB format from ITK: flatten row-major with axis columns
    # [row(IOP0-2), col(IOP3-5), normal].
    mat = np.array(
        [
            [row[0], col[0], normal[0]],
            [row[1], col[1], normal[1]],
            [row[2], col[2], normal[2]],
        ],
        dtype=float,
    )
    return [float(v) for v in mat.reshape(-1)]


def _slice_normal_from_iop(iop):
    """Return the unit slice normal for canonical geometry sorting.

    Convention: cross(row_dir, col_dir), matching FAST and canonical sort.
    Sync/reference-line geometry has its own independent convention.
    """
    vals = _safe_float_list(iop, 6)
    if vals is None:
        return None
    row = np.asarray(vals[0:3], dtype=float)
    col = np.asarray(vals[3:6], dtype=float)
    row_n = float(np.linalg.norm(row))
    col_n = float(np.linalg.norm(col))
    if row_n <= 1e-9 or col_n <= 1e-9:
        return None
    row = row / row_n
    col = col / col_n
    # Standard DICOM display convention: cross(row, col) = [0,0,+1] for axial
    # HFS (row=[1,0,0], col=[0,1,0]).  Ascending dot(IPP, normal) therefore
    # sorts Inferior→Superior for standard axial, matching the FAST pipeline
    # (lightweight_2d_pipeline._normal_from_iop), MPR, and pydicom backends.
    # The sync-geometry paths (dicom_sync_geometry.compute_slice_normal,
    # _pw_sync lines 909/1356) use cross(col,row) intentionally for a
    # different purpose; do NOT change those.
    normal = np.cross(row, col)
    normal_n = float(np.linalg.norm(normal))
    if normal_n <= 1e-9:
        return None
    return normal / normal_n


def _plane_from_normal(normal):
    """Classify a slice normal as AXIAL / SAGITTAL / CORONAL / OBLIQUE."""
    if normal is None:
        return "OBLIQUE", None, 0
    vec = np.asarray(normal, dtype=float)
    if vec.shape != (3,):
        return "OBLIQUE", None, 0
    abs_vec = np.abs(vec)
    dominant_axis = int(np.argmax(abs_vec))
    dominant_axis_sign = 1 if float(vec[dominant_axis]) >= 0.0 else -1
    # A plane is only treated as orthogonal if one axis dominates clearly.
    second_axis = int(np.argsort(abs_vec)[-2])
    if abs_vec[dominant_axis] < 0.75 or abs_vec[dominant_axis] - abs_vec[second_axis] < 0.15:
        return "OBLIQUE", dominant_axis, dominant_axis_sign
    return ["SAGITTAL", "CORONAL", "AXIAL"][dominant_axis], dominant_axis, dominant_axis_sign


def _axis_label(axis_index: int, positive: bool) -> str:
    if axis_index == 0:
        return "Left" if positive else "Right"
    if axis_index == 1:
        return "Posterior" if positive else "Anterior"
    return "Superior" if positive else "Inferior"


def _anatomical_label_from_ipp_delta(delta: np.ndarray) -> str:
    """Return a compact anatomical label from an IPP delta vector.

    The label uses the dominant axis; if a second axis is close in magnitude,
    both are included (e.g. "Superior/Left").
    """
    if delta is None:
        return "?"
    vec = np.asarray(delta, dtype=float)
    if vec.shape != (3,):
        return "?"
    abs_vec = np.abs(vec)
    if float(abs_vec.max()) <= 1e-9:
        return "Same"
    order = list(np.argsort(abs_vec)[::-1])
    labels = []
    top = abs_vec[order[0]]
    for axis_index in order:
        if abs_vec[axis_index] < 0.35 * top:
            break
        labels.append(_axis_label(int(axis_index), bool(vec[axis_index] > 0.0)))
        if len(labels) == 2:
            break
    return "/".join(labels) if labels else "?"


# ──────────────────────────────────────────────────────────────────────────────
# Canonical instance-sort — v3.0.2 (2026-05-13)
#
# ROOT CAUSE (forensic 2026-05-13):
#   First-open during active download used filesystem/natsort filename order.
#   Reopen from DB used ORDER BY instance_number (DICOM header InstanceNumber).
#   Those two ordering authorities can be opposite or inconsistent.
#   Advanced reference lines / MPR then index into metadata['instances'] by
#   VTK slice index, so a mismatch between pixel volume order and metadata
#   order corrupts IOP/IPP lookups and makes reference lines wrong.
#
# FIX: one canonical function used by BOTH load paths, applied BEFORE the ITK
#   call so pixel data and metadata list are aligned from the start.
#
# SORTING PRIORITY (A > B):
#   A. IPP+IOP geometry  → slice_position = dot(IPP, cross(IOP_row, IOP_col))
#      Tie-breakers: InstanceNumber, SOPInstanceUID, file_path
#   B. InstanceNumber fallback (when <50% of instances have valid IPP/IOP)
#      Tie-breakers: SOPInstanceUID, natural file_path
#
# KNOWN LIMITATIONS (documented here, not silently suppressed):
#   - Multi-frame DICOM (single file, N frames): treated as a single instance;
#     caller must not pass multi-frame files to this function.
#   - Gantry tilt / non-parallel slices: IOP varies per slice; we still sort
#     by dot(IPP, mean_normal) which is a good-enough heuristic.  True
#     gantry-tilt stacks must be detected upstream and handled separately.
#   - Duplicate IPP (overlapping acquisitions): slice_position ties are broken
#     by InstanceNumber, then SOPInstanceUID.
#   - Localiser / scout images: these typically have different IOP from the main
#     stack; they are included in the sort but will sort out-of-sequence.  The
#     size-filter in get_itk_image already excludes different-sized scouts.
#   - Missing IOP/IPP (<50% coverage): falls back to InstanceNumber order.
# ──────────────────────────────────────────────────────────────────────────────

_CANONICAL_SORT_MIN_GEOMETRY_FRACTION = 0.5  # min fraction of instances needing valid IPP+IOP

# Forensic counter for each canonical_sort call
_CANONICAL_SORT_CALL_ID = 0


def _emit_canonical_sort_diagnostic(instances: list, mean_normal=None):
    """Emit [CANONICAL_SORT_INPUT_SAMPLE] diagnostic with instance metadata.
    
    Detects potential mixed-series or cache-collision issues.
    """
    try:
        logger = logging.getLogger("viewer")
        global _CANONICAL_SORT_CALL_ID
        _CANONICAL_SORT_CALL_ID += 1
        load_id = _CANONICAL_SORT_CALL_ID
        
        if not instances:
            return
        
        # Extract unique values across all instances
        series_uid_set = set()
        series_number_set = set()
        plane_histogram = {}
        sop_uid_set = set()
        
        for inst in instances:
            series_uid = str(inst.get("series_uid") or inst.get("SeriesInstanceUID") or "UNKNOWN")
            series_uid_set.add(series_uid)
            
            series_number = inst.get("series_number") or inst.get("SeriesNumber")
            series_number_set.add(series_number)
            
            sop_uid = str(inst.get("sop_uid") or inst.get("sop_instance_uid") or inst.get("SOPInstanceUID") or "")
            sop_uid_set.add(sop_uid)
            
            iop = inst.get("image_orientation_patient")
            if iop:
                try:
                    n = _slice_normal_from_iop(iop)
                    if n is not None:
                        plane_name, _, _ = _plane_from_normal(n)
                        plane_histogram[plane_name] = plane_histogram.get(plane_name, 0) + 1
                except Exception:
                    pass
        
        unique_series_uid_count = len(series_uid_set)
        unique_sop_count = len(sop_uid_set)
        
        # Check for mixed-series error
        if unique_series_uid_count > 1:
            logger.warning(
                f"[CANONICAL_SORT_MIXED_SERIES_ERROR] load_id={load_id} n={len(instances)} "
                f"unique_series_uid_count={unique_series_uid_count} series_uid_set={series_uid_set}",
                extra={"component": "viewer"}
            )
        
        # Check for plane mix error (multiple dominant planes)
        dominant_planes = [p for p in plane_histogram if plane_histogram.get(p, 0) > len(instances) * 0.1]
        if len(dominant_planes) > 1:
            logger.warning(
                f"[CANONICAL_SORT_PLANE_MIX_ERROR] load_id={load_id} n={len(instances)} "
                f"plane_histogram={plane_histogram}",
                extra={"component": "viewer"}
            )
        
        # Extract first 5 and last 5 instances
        first5 = instances[:5]
        last5 = instances[-5:] if len(instances) > 5 else []
        
        def format_inst_sample(inst):
            """Format a single instance for logging."""
            iop = inst.get("image_orientation_patient")
            normal = None
            plane_name = "UNKNOWN"
            if iop:
                try:
                    normal = _slice_normal_from_iop(iop)
                    if normal is not None:
                        plane_name, _, _ = _plane_from_normal(normal)
                except Exception:
                    pass
            
            path = str(inst.get("instance_path") or "")
            sop = str(inst.get("sop_uid") or inst.get("sop_instance_uid") or "")
            series_uid = str(inst.get("series_uid") or inst.get("SeriesInstanceUID") or "")
            inst_num = inst.get("instance_number") or inst.get("InstanceNumber") or 0
            ipp = inst.get("image_position_patient") or [0, 0, 0]
            
            return {
                "path": path[-40:] if len(path) > 40 else path,  # Truncate path
                "sop_uid": sop[-12:] if len(sop) > 12 else sop,  # Last 12 chars
                "series_uid": series_uid[-8:] if len(series_uid) > 8 else series_uid,
                "instance_number": inst_num,
                "ipp": f"[{ipp[0]:.2f},{ipp[1]:.2f},{ipp[2]:.2f}]",
                "iop": f"[{iop[0]:.2f},{iop[1]:.2f},{iop[2]:.2f}]" if iop else "NONE",
                "normal": f"[{normal[0]:.4f},{normal[1]:.4f},{normal[2]:.4f}]" if normal is not None else "NONE",
                "plane": plane_name
            }
        
        first5_formatted = [format_inst_sample(i) for i in first5]
        last5_formatted = [format_inst_sample(i) for i in last5]
        
        logger.warning(
            f"[CANONICAL_SORT_INPUT_SAMPLE] load_id={load_id} n={len(instances)} "
            f"unique_series_uid_count={unique_series_uid_count} unique_sop_count={unique_sop_count} "
            f"plane_histogram={plane_histogram} "
            f"first5={first5_formatted} last5={last5_formatted}",
            extra={"component": "viewer"}
        )
    except Exception as ex:
        pass  # Silently fail on diagnostic


def _slice_position(inst, normal: np.ndarray) -> float:
    """dot(IPP, normal) for one instance; returns NaN on failure."""
    ipp = inst.get("image_position_patient")
    if ipp is None or len(ipp) < 3:
        return float("nan")
    try:
        return float(np.dot(np.asarray(ipp, dtype=float), normal))
    except Exception:
        return float("nan")


def _canonical_sort_key_geometry(inst, normal: np.ndarray):
    """Sort key for geometry pass: (slice_position, instance_number, sop_uid, path)."""
    sp = _slice_position(inst, normal)
    if sp != sp:  # NaN — push to end
        sp = float("inf")
    num_raw = inst.get("instance_number") or inst.get("InstanceNumber")
    try:
        num = int(num_raw)
    except (TypeError, ValueError):
        num = 999_999
    sop = str(inst.get("sop_uid") or inst.get("sop_instance_uid") or "")
    path = str(inst.get("instance_path") or "")
    return (sp, num, sop, path)


def _canonical_sort_key_fallback(inst):
    """Sort key for fallback pass: (instance_number, sop_uid, natural_path_rank)."""
    num_raw = inst.get("instance_number") or inst.get("InstanceNumber")
    try:
        num = int(num_raw)
    except (TypeError, ValueError):
        num = 999_999
    sop = str(inst.get("sop_uid") or inst.get("sop_instance_uid") or "")
    # natsorted rank is O(N log N) here but N is typically small (≤2000).
    path = str(inst.get("instance_path") or "")
    return (num, sop, path)


def canonical_sort_instances(instances: list) -> tuple:
    """Return (sorted_instances, ordering_method_str).

    ordering_method_str is one of:
        'IPP_IOP_GEOMETRY'          — sorted by anatomical slice position
        'INSTANCE_NUMBER_FALLBACK'  — sorted by InstanceNumber (IPP/IOP missing)
        'FILE_PATH_FALLBACK'        — sorted by natsorted path (nothing numeric)
        'SINGLE_OR_EMPTY'           — ≤1 instance; no sort needed

    The input list is NOT modified; a new list is returned.

    Contract: every consumer that passes files to SimpleITK AND builds the
    per-slice metadata list MUST call this function and use the returned list
    as both the ITK file-name order AND the metadata instance order.
    """
    # Emit forensic diagnostic at entry
    _emit_canonical_sort_diagnostic(instances)
    
    if not isinstance(instances, list) or len(instances) <= 1:
        return list(instances), "SINGLE_OR_EMPTY"

    # ── 1. Collect valid IPP+IOP geometry ───────────────────────────────────
    normals = []
    for inst in instances:
        iop = inst.get("image_orientation_patient")
        if iop is None or len(iop) < 6:
            continue
        try:
            n = _slice_normal_from_iop(iop)
            if n is None:
                continue
            nn = float(np.linalg.norm(n))
            if nn > 1e-9:
                normals.append(n / nn)
        except Exception:
            pass

    geometry_fraction = len(normals) / len(instances)

    if geometry_fraction >= _CANONICAL_SORT_MIN_GEOMETRY_FRACTION:
        # ── 2A. Mean normal across all valid slices ──────────────────────────
        mean_normal = np.mean(normals, axis=0)
        norm_len = float(np.linalg.norm(mean_normal))
        if norm_len > 1e-9:
            mean_normal = mean_normal / norm_len
        else:
            mean_normal = normals[0]

        sorted_list = sorted(
            instances,
            key=lambda inst: _canonical_sort_key_geometry(inst, mean_normal),
        )
        return sorted_list, "IPP_IOP_GEOMETRY"

    # ── 2B. Fallback: InstanceNumber ─────────────────────────────────────────
    any_numeric = any(
        _canonical_sort_key_fallback(inst)[0] != 999_999
        for inst in instances
    )
    if any_numeric:
        sorted_list = sorted(instances, key=_canonical_sort_key_fallback)
        return sorted_list, "INSTANCE_NUMBER_FALLBACK"

    # ── 2C. Last resort: natural file-path order ─────────────────────────────
    def _natsort_key(inst):
        p = str(inst.get("instance_path") or "")
        return natsorted([p])[0]

    sorted_list = sorted(instances, key=lambda inst: str(inst.get("instance_path") or ""))
    # Re-sort with natsort for numeric-in-string awareness
    sorted_list = natsorted(instances, key=lambda inst: str(inst.get("instance_path") or ""))
    return sorted_list, "FILE_PATH_FALLBACK"


# ── Populate direction field (unchanged purpose, now called after canonical sort)
def _normalize_instances_geometry_order(instances):
    """Populate direction field on instances.  Sorting is now done by
    canonical_sort_instances() BEFORE this function; this function only
    ensures the direction field is populated for DB-stored direction data.
    """
    if not isinstance(instances, list) or len(instances) <= 1:
        return False

    for inst in instances:
        if inst.get("direction"):
            continue
        direction = _direction_from_iop(inst.get("image_orientation_patient"))
        if direction is not None:
            inst["direction"] = direction

    return False


def _normalize_metadata_instances(metadata):
    if not isinstance(metadata, dict):
        return False
    if get_series_geometry_index(metadata) is not None:
        metadata["_instances_geometry_sorted"] = True
        return False
    changed = _normalize_instances_geometry_order(metadata.get("instances"))
    try:
        series_meta = _ensure_series_meta(metadata)
        if isinstance(series_meta, dict):
            series_meta["instances_geometry_sorted"] = True
    except Exception:
        pass
    return changed


# ── Diagnostics ──────────────────────────────────────────────────────────────

def _read_dicom_header_audit(path: str) -> dict:
    try:
        ds = utils._safe_dcmread(str(path), stop_before_pixels=True)
        if ds is None:
            return {}
        iop = ds.get("ImageOrientationPatient", None)
        ipp = ds.get("ImagePositionPatient", None)
        ps = ds.get("PixelSpacing", None)
        return {
            "series_uid": str(ds.get("SeriesInstanceUID", "") or ""),
            "sop_uid": str(ds.get("SOPInstanceUID", "") or ""),
            "iop": tuple(float(v) for v in iop[:6]) if iop is not None and len(iop) >= 6 else None,
            "ipp": tuple(float(v) for v in ipp[:3]) if ipp is not None and len(ipp) >= 3 else None,
            "pixel_spacing": tuple(float(v) for v in ps[:2]) if ps is not None and len(ps) >= 2 else None,
            "slice_thickness": _safe_float(ds.get("SliceThickness", None)),
            "spacing_between_slices": _safe_float(ds.get("SpacingBetweenSlices", None)),
            "rows": int(ds.get("Rows", 0) or 0),
            "columns": int(ds.get("Columns", 0) or 0),
        }
    except Exception:
        return {}


def _format_vtk_direction_matrix(vtk_image_data):
    try:
        if not hasattr(vtk_image_data, "GetDirectionMatrix"):
            return None
        m = vtk_image_data.GetDirectionMatrix()
        if isinstance(m, vtk.vtkMatrix4x4):
            return tuple(tuple(float(m.GetElement(r, c)) for c in range(3)) for r in range(3))
        if isinstance(m, vtk.vtkMatrix3x3):
            return tuple(tuple(float(m.GetElement(r, c)) for c in range(3)) for r in range(3))
    except Exception:
        return None
    return None


def _emit_advanced_vtk_orientation_audit_stage(
    series_number,
    *,
    stage: str,
    dicom_files_for_itk: list,
    metadata: dict | None = None,
    sitk_image: sitk.Image | None = None,
    vtk_image_data: vtk.vtkImageData | None = None,
):
    """Emit structured orientation-audit stage logs and stamp metadata with SITK audit."""
    try:
        files = [str(p) for p in (dicom_files_for_itk or []) if str(p)]
        first_hdr = _read_dicom_header_audit(files[0]) if files else {}
        last_hdr = _read_dicom_header_audit(files[-1]) if len(files) > 1 else first_hdr

        sitk_origin = sitk_spacing = sitk_direction = sitk_size = None
        if sitk_image is not None:
            try:
                sitk_origin = tuple(float(v) for v in sitk_image.GetOrigin())
                sitk_spacing = tuple(float(v) for v in sitk_image.GetSpacing())
                sitk_direction = tuple(float(v) for v in sitk_image.GetDirection())
                sitk_size = tuple(int(v) for v in sitk_image.GetSize())
            except Exception:
                pass

        vtk_origin = vtk_spacing = vtk_dims = vtk_extent = None
        vtk_direction_matrix = None
        vtk_direction_matrix_present = False
        vtk_direction_field_data_present = False
        if vtk_image_data is not None:
            try:
                vtk_origin = tuple(float(v) for v in vtk_image_data.GetOrigin())
                vtk_spacing = tuple(float(v) for v in vtk_image_data.GetSpacing())
                vtk_dims = tuple(int(v) for v in vtk_image_data.GetDimensions())
                vtk_extent = tuple(int(v) for v in vtk_image_data.GetExtent())
                vtk_direction_matrix = _format_vtk_direction_matrix(vtk_image_data)
                vtk_direction_matrix_present = vtk_direction_matrix is not None
                fd = vtk_image_data.GetFieldData()
                vtk_direction_field_data_present = bool(
                    fd is not None and fd.GetArray("DirectionMatrix") is not None
                )
            except Exception:
                pass

        if isinstance(metadata, dict):
            try:
                series_meta = metadata.get("series", {})
                if isinstance(series_meta, dict):
                    series_meta["_orientation_audit_sitk_origin"] = sitk_origin
                    series_meta["_orientation_audit_sitk_spacing"] = sitk_spacing
                    series_meta["_orientation_audit_sitk_direction"] = sitk_direction
                    series_meta["_orientation_audit_sitk_size"] = sitk_size
                    series_meta["_orientation_audit_first_sop_uid"] = first_hdr.get("sop_uid", "")
                    series_meta["_orientation_audit_last_sop_uid"] = last_hdr.get("sop_uid", "")
                    series_meta["_orientation_audit_first_ipp"] = first_hdr.get("ipp")
                    series_meta["_orientation_audit_last_ipp"] = last_hdr.get("ipp")
                    series_meta["_orientation_audit_vtk_origin"] = vtk_origin
                    series_meta["_orientation_audit_vtk_spacing"] = vtk_spacing
                    series_meta["_orientation_audit_vtk_dimensions"] = vtk_dims
                    series_meta["_orientation_audit_vtk_extent"] = vtk_extent
                    series_meta["_orientation_audit_vtk_direction_matrix"] = vtk_direction_matrix
                    series_meta["_orientation_audit_vtk_direction_matrix_present"] = vtk_direction_matrix_present
                    series_meta["_orientation_audit_vtk_direction_field_data_present"] = vtk_direction_field_data_present
            except Exception:
                pass

        logger.warning(
            "[ADVANCED_VTK_ORIENTATION_AUDIT] "
            "stage=%s series_uid=%s series_number=%s slice_index=%s "
            "iop_row=%s iop_col=%s iop_normal=%s "
            "sitk_origin=%s sitk_spacing=%s sitk_direction=%s sitk_size=%s "
            "input_file_first_sop_uid=%s input_file_last_sop_uid=%s "
            "input_file_first_ipp=%s input_file_last_ipp=%s "
            "vtk_origin=%s vtk_spacing=%s vtk_dimensions=%s vtk_extent=%s "
            "vtk_direction_matrix_present=%s vtk_direction_matrix=%s vtk_direction_field_data_present=%s",
            stage,
            first_hdr.get("series_uid", ""),
            str(series_number),
            -1,
            first_hdr.get("iop", None)[0:3] if first_hdr.get("iop", None) else None,
            first_hdr.get("iop", None)[3:6] if first_hdr.get("iop", None) else None,
            _slice_normal_from_iop(first_hdr.get("iop", None)).tolist() if first_hdr.get("iop", None) else None,
            sitk_origin,
            sitk_spacing,
            sitk_direction,
            sitk_size,
            first_hdr.get("sop_uid", ""),
            last_hdr.get("sop_uid", ""),
            first_hdr.get("ipp", None),
            last_hdr.get("ipp", None),
            vtk_origin,
            vtk_spacing,
            vtk_dims,
            vtk_extent,
            vtk_direction_matrix_present,
            vtk_direction_matrix,
            vtk_direction_field_data_present,
            extra={"component": "viewer"},
        )
    except Exception as exc:
        logger.debug("[ADVANCED_VTK_ORIENTATION_AUDIT] stage emit failed: %s", exc)

def _log_canonical_sort_diagnostics(
    series_number,
    load_source: str,
    instances: list,
    ordering_method: str,
    dicom_files_for_itk: list,
    mean_normal=None,
):
    """Emit structured [CANONICAL_SORT] diagnostic for every Advanced Viewer load.

    load_source:     'db_fast_path' | 'filesystem_fallback' | 'process_groups'
    ordering_method: one of the strings from canonical_sort_instances()
    dicom_files_for_itk: the final ordered list passed to get_itk_image()
    mean_normal:     the geometry normal used, or None for fallback sorts.

    Logs at WARNING level so it reaches viewer_diagnostics.log regardless of
    component threshold (per R23 structured-logging discipline).
    """
    try:
        n = len(instances)
        head = instances[:3]
        tail = instances[-3:] if n > 3 else []

        first_file = str(dicom_files_for_itk[0]) if dicom_files_for_itk else ""
        series_uid = modality = patient_position = image_type = None
        if first_file:
            try:
                first_dcm = utils._safe_dcmread(first_file, stop_before_pixels=True)
                if first_dcm is not None:
                    series_uid = str(first_dcm.get("SeriesInstanceUID", "") or "")
                    modality = str(first_dcm.get("Modality", "") or "")
                    patient_position = str(first_dcm.get("PatientPosition", "") or "")
                    image_type = first_dcm.get("ImageType", None)
                    if isinstance(image_type, (list, tuple)):
                        image_type = "\\".join(str(v) for v in image_type)
                    elif image_type is not None and not isinstance(image_type, str):
                        image_type = str(image_type)
            except Exception:
                pass

        def _fmt_inst(inst, idx):
            sp_val = ""
            if mean_normal is not None:
                _mn_arr = np.asarray(mean_normal, dtype=float)
                sp = _slice_position(inst, _mn_arr)
                sp_val = f"{sp:.4f}" if sp == sp else "nan"  # NaN-safe
            return (
                f"idx={idx} "
                f"path={str(inst.get('instance_path',''))!r} "
                f"sop={inst.get('sop_uid','')!r} "
                f"instance_number={inst.get('instance_number','?')} "
                f"ipp={inst.get('image_position_patient')} "
                f"slice_pos={sp_val}"
            )

        head_lines = [_fmt_inst(inst, i) for i, inst in enumerate(head)]
        tail_lines = [_fmt_inst(inst, n - len(tail) + i) for i, inst in enumerate(tail)]

        sort_normal = None
        plane = "OBLIQUE"
        dominant_axis = None
        dominant_axis_sign = None
        if mean_normal is not None:
            _mn_arr = np.asarray(mean_normal, dtype=float)
            _mn_len = float(np.linalg.norm(_mn_arr))
            if _mn_len > 1e-9:
                sort_normal = (_mn_arr / _mn_len)
                plane, dominant_axis, dominant_axis_sign = _plane_from_normal(sort_normal)
        if sort_normal is None and head:
            try:
                _first_iop = head[0].get("image_orientation_patient")
                sort_normal = _slice_normal_from_iop(_first_iop)
                if sort_normal is not None:
                    plane, dominant_axis, dominant_axis_sign = _plane_from_normal(sort_normal)
            except Exception:
                pass

        # ── Geometry availability counts ──────────────────────────────────────
        geom_available = sum(
            1 for inst in instances
            if inst.get("image_position_patient") is not None
            and inst.get("image_orientation_patient") is not None
        )
        geom_missing = n - geom_available

        # ── IOP normal consistency ────────────────────────────────────────────
        max_angle_deg = None
        inconsistent_iop = False
        all_normals = []
        for inst in instances:
            _iop_v = inst.get("image_orientation_patient")
            if _iop_v and len(_iop_v) >= 6:
                _nv = _slice_normal_from_iop(_iop_v)
                _nn = float(np.linalg.norm(_nv))
                if _nn > 1e-9:
                    all_normals.append(np.asarray(_nv, dtype=float) / _nn)
        if len(all_normals) >= 2 and mean_normal is not None:
            _mn_arr = np.asarray(mean_normal, dtype=float)
            _mnl = float(np.linalg.norm(_mn_arr))
            if _mnl > 1e-9:
                _mn_unit = _mn_arr / _mnl
                angles = []
                for _nv in all_normals:
                    _dot = float(np.clip(np.dot(_nv, _mn_unit), -1.0, 1.0))
                    angles.append(math.degrees(math.acos(_dot)))
                max_angle_deg = round(max(angles), 3)
                inconsistent_iop = max_angle_deg > 10.0  # >10° = mixed-IOP series

        first_ipp = None
        last_ipp = None
        if head:
            try:
                _first_pos = head[0].get("image_position_patient")
                if _first_pos is not None:
                    first_ipp = np.asarray(_first_pos, dtype=float)
            except Exception:
                first_ipp = None
            try:
                _last_pos = tail[-1].get("image_position_patient") if tail else head[-1].get("image_position_patient")
                if _last_pos is not None:
                    last_ipp = np.asarray(_last_pos, dtype=float)
            except Exception:
                last_ipp = None
        ipp_delta = None
        if first_ipp is not None and last_ipp is not None and first_ipp.shape == (3,) and last_ipp.shape == (3,):
            ipp_delta = last_ipp - first_ipp
        current_first_label = _anatomical_label_from_ipp_delta(ipp_delta) if ipp_delta is not None else "?"
        current_last_label = _anatomical_label_from_ipp_delta(-ipp_delta) if ipp_delta is not None else "?"
        expected_first_label = "?"
        expected_last_label = "?"
        if sort_normal is not None and dominant_axis is not None:
            expected_first_label = _axis_label(dominant_axis, bool(float(sort_normal[dominant_axis]) < 0.0))
            expected_last_label = _axis_label(dominant_axis, not bool(float(sort_normal[dominant_axis]) < 0.0))
        direction_match = (current_first_label == expected_first_label) if expected_first_label != "?" else None

        # ── Order disagreement checks ─────────────────────────────────────────
        meta_paths = [str(inst.get("instance_path") or "") for inst in instances]
        sitk_paths = [str(p) for p in (dicom_files_for_itk or [])]

        filename_order = natsorted(meta_paths)
        filename_disagrees = (filename_order != meta_paths) if len(meta_paths) > 1 else False

        try:
            num_order = sorted(
                range(n),
                key=lambda i: _canonical_sort_key_fallback(instances[i]),
            )
            instance_number_disagrees = (num_order != list(range(n))) if n > 1 else False
        except Exception:
            instance_number_disagrees = False

        # ── sitk ↔ metadata alignment check ──────────────────────────────────
        if sitk_paths and meta_paths and len(sitk_paths) == len(meta_paths):
            alignment_ok = all(
                str(mp).lower() == str(sp).lower()
                for mp, sp in zip(meta_paths, sitk_paths)
            )
        else:
            alignment_ok = None

        sort_direction_rule = "ascending dot(IPP, DICOM slice normal cross(row,col))"

        logger.warning(
            "[CANONICAL_SORT] series=%s series_uid=%s modality=%s patient_position=%s image_type=%s "
            "source=%s n=%d method=%s plane=%s dominant_axis=%s dominant_axis_sign=%s "
            "sort_direction_rule=%s normalized_sort_normal=%s "
            "first_slice_ipp=%s last_slice_ipp=%s first_slice_sop_uid=%s last_slice_sop_uid=%s "
            "first_slice_anatomical_label=%s last_slice_anatomical_label=%s expected_first_slice_anatomical_label=%s "
            "geometry_available_count=%d geometry_missing_count=%d "
            "current_order_matches_expected=%s "
            "normal=%s max_normal_angle_deviation_deg=%s inconsistent_iop_normals=%s "
            "filename_disagrees=%s instance_number_disagrees=%s alignment_ok=%s | "
            "HEAD: %s | TAIL: %s",
            series_number,
            series_uid,
            modality,
            patient_position,
            image_type,
            load_source,
            n,
            ordering_method,
            plane,
            dominant_axis,
            dominant_axis_sign,
            sort_direction_rule,
            ([round(float(v), 4) for v in sort_normal] if sort_normal is not None else None),
            ([round(float(v), 4) for v in first_ipp.tolist()] if first_ipp is not None else None),
            ([round(float(v), 4) for v in last_ipp.tolist()] if last_ipp is not None else None),
            str(head[0].get("sop_uid") or "") if head else "",
            str(tail[-1].get("sop_uid") or "") if tail else (str(head[-1].get("sop_uid") or "") if head else ""),
            current_first_label,
            current_last_label,
            expected_first_label,
            geom_available,
            geom_missing,
            direction_match,
            ([round(float(v), 4) for v in mean_normal] if mean_normal is not None else None),
            max_angle_deg,
            inconsistent_iop,
            filename_disagrees,
            instance_number_disagrees,
            alignment_ok,
            " ; ".join(head_lines),
            " ; ".join(tail_lines),
            extra={"component": "viewer"},
        )
    except Exception as _diag_exc:
        logger.debug("[CANONICAL_SORT] diagnostic emit failed: %s", _diag_exc)


def _validate_sitk_metadata_alignment(series_number, metadata: dict, dicom_files_for_itk: list):
    """Assert that metadata['instances'][i].instance_path == dicom_files_for_itk[i].

    Logs an ERROR if misaligned; never raises (caller must not crash).
    Returns True if aligned, False if not, None if check is not applicable.
    """
    try:
        instances = metadata.get("instances", [])
        if not instances or not dicom_files_for_itk:
            return None
        if len(instances) != len(dicom_files_for_itk):
            logger.error(
                "[CANONICAL_SORT] ALIGNMENT_MISMATCH series=%s "
                "len(metadata_instances)=%d != len(sitk_files)=%d",
                series_number, len(instances), len(dicom_files_for_itk),
                extra={"component": "viewer"},
            )
            return False
        mismatches = []
        for i, (inst, sitk_path) in enumerate(zip(instances, dicom_files_for_itk)):
            mp = str(inst.get("instance_path") or "").lower()
            sp = str(sitk_path).lower()
            if mp != sp:
                mismatches.append(i)
        if mismatches:
            logger.error(
                "[CANONICAL_SORT] ALIGNMENT_MISMATCH series=%s "
                "mismatched_indices=%s (first: meta=%r sitk=%r)",
                series_number,
                mismatches[:5],
                str(instances[mismatches[0]].get("instance_path") or ""),
                str(dicom_files_for_itk[mismatches[0]]),
                extra={"component": "viewer"},
            )
            return False
        return True
    except Exception as _ve:
        logger.debug("[CANONICAL_SORT] validation failed: %s", _ve)
        return None


def _compute_path_list_hash(paths: list) -> str:
    """Short SHA-256 (first 16 hex chars) of an ordered, case-folded path list.

    Used by _emit_volume_alignment_hash to produce stable, comparable digests.
    Paths are normalised to forward slashes + lower-case so Windows/POSIX agree.
    """
    import hashlib
    text = "\n".join(str(p).lower().replace("\\", "/") for p in paths)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _series_sort_normal(instances: list):
    """Return a unit mean normal for a list of instances, or None."""
    normals = []
    for inst in instances or []:
        iop = inst.get("image_orientation_patient")
        n = _slice_normal_from_iop(iop)
        if n is None:
            continue
        nn = float(np.linalg.norm(n))
        if nn > 1e-9:
            normals.append(np.asarray(n, dtype=float) / nn)
    if not normals:
        return None
    mean_n = np.mean(normals, axis=0)
    mean_len = float(np.linalg.norm(mean_n))
    if mean_len <= 1e-9:
        return None
    return mean_n / mean_len


def _edge_anatomical_labels(instances: list) -> tuple:
    """Return (first_label, last_label) from first/last IPP in the ordered list."""
    if not instances or len(instances) <= 1:
        return "?", "?"
    try:
        first_ipp = np.asarray(instances[0].get("image_position_patient"), dtype=float)
        last_ipp = np.asarray(instances[-1].get("image_position_patient"), dtype=float)
        if first_ipp.shape != (3,) or last_ipp.shape != (3,):
            return "?", "?"
        delta = last_ipp - first_ipp
        return _anatomical_label_from_ipp_delta(delta), _anatomical_label_from_ipp_delta(-delta)
    except Exception:
        return "?", "?"


def _get_display_convention_context(instances: list, series_meta: dict | None = None) -> tuple:
    """Best-effort extraction of display-convention context fields.

    Returns (series_uid, plane, body_part, laterality, patient_position).
    """
    series_uid = ""
    body_part = ""
    laterality = ""
    patient_position = ""

    if isinstance(series_meta, dict):
        body_part = str(series_meta.get("body_part_examined") or "")
        laterality = str(series_meta.get("laterality") or "")
        patient_position = str(series_meta.get("patient_position") or "")
        series_uid = str(series_meta.get("series_instance_uid") or "")

    # DICOM header fallback from first instance path for richer diagnostics.
    first_path = ""
    try:
        if instances:
            first_path = str(instances[0].get("instance_path") or "")
    except Exception:
        first_path = ""

    if first_path:
        try:
            ds = utils._safe_dcmread(first_path, stop_before_pixels=True)
            if ds is not None:
                if not series_uid:
                    series_uid = str(ds.get("SeriesInstanceUID", "") or "")
                if not body_part:
                    body_part = str(ds.get("BodyPartExamined", "") or "")
                if not laterality:
                    laterality = str(ds.get("Laterality", "") or "")
                if not patient_position:
                    patient_position = str(ds.get("PatientPosition", "") or "")
        except Exception:
            pass

    mean_n = _series_sort_normal(instances)
    plane, _, _ = _plane_from_normal(mean_n)
    return series_uid, plane, body_part, laterality, patient_position


def apply_advanced_display_convention(
    canonical_instances: list,
    plane: str,
    patient_position: str,
    body_part: str,
    laterality: str,
    series_uid: str = "",
):
    """Apply Advanced-viewer display convention to the shared ordered list.

    This layer runs after canonical geometry sorting and before both
    SimpleITK file-name construction and metadata/reference-line finalization.
    The returned list must be treated as the single source of truth.
    """
    ordered = list(canonical_instances or [])
    if len(ordered) <= 1:
        return ordered

    plane_upper = str(plane or "").strip().upper()
    body_upper = str(body_part or "").strip().upper()
    laterality_upper = str(laterality or "").strip().upper()

    applied_reverse = False
    reason = "none"

    if plane_upper == "AXIAL":
        # PACS viewing convention in this workstation: start from superior side.
        applied_reverse = True
        if any(k in body_upper for k in ("KNEE", "JOINT", "EXTREM", "ANKLE", "ELBOW", "WRIST", "SHOULDER", "HIP")):
            reason = "axial_extremity_proximal_first"
        else:
            reason = "axial_superior_first"
    elif plane_upper == "SAGITTAL":
        # Clinical display convention target: right-to-left (lateral-to-medial).
        applied_reverse = True
        if laterality_upper:
            reason = f"sagittal_right_to_left_laterality={laterality_upper}"
        else:
            reason = "sagittal_right_to_left"
    elif plane_upper == "CORONAL":
        applied_reverse = False
        reason = "coronal_observe_only"
    else:
        applied_reverse = False
        reason = f"{(plane_upper or 'OBLIQUE').lower()}_no_override"

    display_instances = list(reversed(ordered)) if applied_reverse else ordered

    canonical_first_label, canonical_last_label = _edge_anatomical_labels(ordered)
    display_first_label, display_last_label = _edge_anatomical_labels(display_instances)
    canonical_order_hash = _compute_path_list_hash(
        [str(inst.get("instance_path") or "") for inst in ordered]
    )
    display_order_hash = _compute_path_list_hash(
        [str(inst.get("instance_path") or "") for inst in display_instances]
    )
    canonical_first_sop_uid = str(ordered[0].get("sop_uid") or "") if ordered else ""
    canonical_last_sop_uid = str(ordered[-1].get("sop_uid") or "") if ordered else ""
    display_first_sop_uid = str(display_instances[0].get("sop_uid") or "") if display_instances else ""
    display_last_sop_uid = str(display_instances[-1].get("sop_uid") or "") if display_instances else ""

    logger.warning(
        "[ADVANCED_DISPLAY_CONVENTION] series_uid=%s plane=%s body_part=%s laterality=%s "
        "patient_position=%s canonical_order_hash=%s canonical_first_sop_uid=%s canonical_last_sop_uid=%s "
        "canonical_first_label=%s canonical_last_label=%s "
        "display_first_sop_uid=%s display_last_sop_uid=%s "
        "display_first_label=%s display_last_label=%s applied_reverse=%s reason=%s "
        "display_order_hash=%s",
        series_uid,
        plane_upper or "OBLIQUE",
        body_part,
        laterality,
        patient_position,
        canonical_order_hash,
        canonical_first_sop_uid,
        canonical_last_sop_uid,
        canonical_first_label,
        canonical_last_label,
        display_first_sop_uid,
        display_last_sop_uid,
        display_first_label,
        display_last_label,
        applied_reverse,
        reason,
        display_order_hash,
        extra={"component": "viewer"},
    )

    return display_instances


def _mark_advanced_display_order_contract(metadata: dict, canonical_instances: list):
    """Temporary diagnostics: stamp finalized Advanced display-order contract on metadata."""
    try:
        if not isinstance(metadata, dict):
            return
        display_instances = metadata.get("instances") or []
        canonical_paths = [str(inst.get("instance_path") or "") for inst in (canonical_instances or [])]
        display_paths = [str(inst.get("instance_path") or "") for inst in display_instances]
        metadata["instances_order_contract"] = "ADVANCED_DISPLAY_ORDER"
        metadata["display_order_hash"] = _compute_path_list_hash(display_paths)
        metadata["canonical_order_hash"] = _compute_path_list_hash(canonical_paths)
        metadata["display_convention_applied"] = True
    except Exception:
        pass


def _emit_advanced_metadata_mutation(
    metadata: dict,
    before_instances: list,
    after_instances: list,
    *,
    caller: str,
    reason: str,
):
    """Temporary forensic probe: metadata instances mutation before/after snapshot."""
    try:
        if not isinstance(metadata, dict):
            return
        b = before_instances if isinstance(before_instances, list) else []
        a = after_instances if isinstance(after_instances, list) else []
        before_hash = _compute_path_list_hash([str(inst.get("instance_path") or "") for inst in b if isinstance(inst, dict)])
        after_hash = _compute_path_list_hash([str(inst.get("instance_path") or "") for inst in a if isinstance(inst, dict)])
        b_first = str((b[0].get("instance_path") if b and isinstance(b[0], dict) else "") or "")
        b_last = str((b[-1].get("instance_path") if b and isinstance(b[-1], dict) else "") or "")
        a_first = str((a[0].get("instance_path") if a and isinstance(a[0], dict) else "") or "")
        a_last = str((a[-1].get("instance_path") if a and isinstance(a[-1], dict) else "") or "")

        logger.warning(
            "[ADVANCED_METADATA_MUTATION] caller=%s reason=%s before_hash=%s after_hash=%s "
            "before_first_path=%s after_first_path=%s before_last_path=%s after_last_path=%s "
            "object_id_metadata=%s object_id_instances=%s",
            str(caller or "unknown"),
            str(reason or "unknown"),
            before_hash,
            after_hash,
            b_first,
            a_first,
            b_last,
            a_last,
            int(id(metadata)),
            int(id(a)),
            extra={"component": "viewer"},
        )

        if (
            str(metadata.get("instances_order_contract") or "").startswith("ADVANCED_")
            and before_hash != after_hash
        ):
            logger.warning(
                "[ORDER_CONTRACT_MUTATION] caller=%s reason=%s contract=%s before_hash=%s after_hash=%s "
                "canonical_order_hash=%s display_order_hash=%s object_id_metadata=%s object_id_instances=%s",
                str(caller or "unknown"),
                str(reason or "unknown"),
                str(metadata.get("instances_order_contract") or ""),
                before_hash,
                after_hash,
                str(metadata.get("canonical_order_hash") or ""),
                str(metadata.get("display_order_hash") or ""),
                int(id(metadata)),
                int(id(a)),
                extra={"component": "viewer"},
            )
    except Exception:
        pass


def _emit_volume_alignment_hash(
    series_number,
    metadata: dict,
    dicom_files_for_itk: list,
):
    """Emit [ADVANCED_VOLUME_ALIGNMENT] structured log.

    Compares three ordered path sequences that must all agree for correct
    pixel↔metadata↔reference-line alignment:

      sitk_file_order_hash      — canonical file list passed to get_itk_image()
      metadata_order_hash       — metadata['instances'][i].instance_path order
    reference_metadata_order_hash — reference-line metadata order used by
                          Advanced mapping. This now follows the
                          shared finalized metadata list.

    all_equal=True means every hash matches → the three views are aligned.
    Logs at WARNING so it reaches viewer_diagnostics.log (component=viewer).
    """
    try:
        instances = metadata.get("instances", [])
        meta_paths = [str(inst.get("instance_path") or "") for inst in instances]
        sitk_paths = [str(p) for p in (dicom_files_for_itk or [])]

        # Reference-line view now uses the same finalized ordered list.
        ref_paths = list(meta_paths)

        sitk_hash = _compute_path_list_hash(sitk_paths)
        meta_hash = _compute_path_list_hash(meta_paths)
        ref_hash = _compute_path_list_hash(ref_paths)
        all_equal = (sitk_hash == meta_hash == ref_hash)

        if not all_equal:
            logger.warning(
                "[ADVANCED_VOLUME_ALIGNMENT] MISALIGNED series=%s "
                "sitk_file_order_hash=%s metadata_order_hash=%s "
                "reference_metadata_order_hash=%s all_equal=False "
                "n_sitk=%d n_meta=%d n_ref=%d",
                series_number,
                sitk_hash, meta_hash, ref_hash,
                len(sitk_paths), len(meta_paths), len(ref_paths),
                extra={"component": "viewer"},
            )
        else:
            logger.warning(
                "[ADVANCED_VOLUME_ALIGNMENT] series=%s "
                "sitk_file_order_hash=%s metadata_order_hash=%s "
                "reference_metadata_order_hash=%s all_equal=True "
                "n=%d",
                series_number,
                sitk_hash, meta_hash, ref_hash,
                len(meta_paths),
                extra={"component": "viewer"},
            )
        return all_equal
    except Exception as _e:
        logger.debug("[ADVANCED_VOLUME_ALIGNMENT] emit failed: %s", _e)
        return None


def _build_instance_header_stub(dicom_file: Path, fallback_index: int):
    try:
        dcm = utils._safe_dcmread(str(dicom_file), stop_before_pixels=True)
        if dcm is None:
            return None

        ww = dcm.get("WindowWidth", None)
        wc = dcm.get("WindowCenter", None)
        iop = dcm.get("ImageOrientationPatient", None)
        ipp = dcm.get("ImagePositionPatient", None)
        ps = dcm.get("PixelSpacing", None)

        return {
            "instance_number": int(dcm.get("InstanceNumber", fallback_index) or fallback_index),
            "instance_path": str(dicom_file),
            "rows": int(dcm.get("Rows", 0) or 0),
            "columns": int(dcm.get("Columns", 0) or 0),
            "window_width": _safe_float(ww),
            "window_center": _safe_float(wc),
            "is_rgb": str(dcm.get("PhotometricInterpretation", "")).upper() in {"RGB", "YBR_FULL", "YBR_FULL_422"},
            "sop_uid": str(dcm.get("SOPInstanceUID", "")),
            "image_orientation_patient": [float(v) for v in iop] if iop is not None else None,
            "image_position_patient": [float(v) for v in ipp] if ipp is not None else None,
            "pixel_spacing": [float(v) for v in ps] if ps is not None else None,
            "slice_thickness": _safe_float(dcm.get("SliceThickness", None)),
            "spacing_between_slices": _safe_float(dcm.get("SpacingBetweenSlices", None)),
            "rescale_slope": _safe_float(dcm.get("RescaleSlope", None), 1.0),
            "rescale_intercept": _safe_float(dcm.get("RescaleIntercept", None), 0.0),
            "bits_allocated": int(dcm.get("BitsAllocated", 16) or 16),
            "pixel_representation": int(dcm.get("PixelRepresentation", 1) or 1),
        }
    except Exception:
        return None


def _reconcile_db_instances_with_disk(series_path: Path, instances):
    """Return disk-ordered instances, filling only missing files from headers.

    The pydicom_qt metadata-only fast path should not pay for a full header-only
    rebuild when the DB is merely a few instances behind the filesystem during an
    active download. Keep existing DB metadata for known files and read headers
    only for the missing on-disk files.
    """
    if not isinstance(instances, list) or not instances:
        return None, False

    # Fast path for pydicom_qt metadata loads: if the DB already has the same
    # number of instances as the on-disk series, keep the DB ordering and skip
    # the heavier full directory listing + path-resolution merge work.
    # Metadata in the DB is already ordered by instance_number.
    try:
        disk_count = _count_dicom_files_fast(series_path)
        if (
            disk_count > 0
            and disk_count == len(instances)
            and all(inst.get("instance_path") for inst in instances)
        ):
            return list(instances), False
    except Exception:
        pass

    dicom_files = _list_unique_dicom_files(series_path)
    if not dicom_files:
        return list(instances), False

    instance_by_path = {}
    for inst in instances:
        path_value = inst.get("instance_path")
        if not path_value:
            continue
        try:
            instance_by_path[str(Path(path_value).resolve()).lower()] = inst
        except Exception:
            instance_by_path[str(path_value).lower()] = inst

    merged = []
    changed = False
    for idx, dicom_file in enumerate(dicom_files, 1):
        key = str(dicom_file.resolve()).lower()
        inst = instance_by_path.get(key)
        if inst is None:
            inst = _build_instance_header_stub(dicom_file, idx)
            if inst is None:
                continue
            changed = True
        merged.append(inst)

    if len(merged) != len(instances):
        changed = True
    return merged, changed


def _metadata_needs_geometry_backfill(metadata) -> bool:
    ok, _reason = _validate_lazy_geometry(metadata)
    return not ok


def _build_metadata_headers_only(series_path: Path, series_number):
    dicom_files = _list_unique_dicom_files(series_path)
    if not dicom_files:
        return None

    instances = []
    first_dcm = None
    for i, dicom_file in enumerate(dicom_files, 1):
        try:
            dcm = utils._safe_dcmread(str(dicom_file), stop_before_pixels=True)
            if dcm is None:
                continue
            if first_dcm is None:
                first_dcm = dcm
            stub = _build_instance_header_stub(dicom_file, i)
            if stub is not None:
                instances.append(stub)
        except Exception:
            continue

    if not instances:
        return None

    _normalize_instances_geometry_order(instances)

    if first_dcm is None:
        return None

    metadata = {
        "series": {
            "series_number": str(series_number),
            "series_name": str(series_number),
            "series_description": first_dcm.get("SeriesDescription", f"Series {series_number}"),
            "series_thk": str(first_dcm.get("SliceThickness", "1.0")),
            "modality": first_dcm.get("Modality", "CT"),
            "protocol_name": first_dcm.get("ProtocolName", ""),
            "body_part_examined": first_dcm.get("BodyPartExamined", ""),
            "series_path": str(series_path),
            "main_thumbnail": True,
        },
        "instances": instances,
    }
    return metadata


def _build_lazy_volume_for_metadata(series_path: Path, metadata: dict):
    if not isinstance(metadata, dict):
        return None, metadata
    series_meta = _ensure_series_meta(metadata)
    if not series_meta:
        return None, metadata

    existing_key = str(series_meta.get("lazy_loader_key", "") or "").strip()
    if existing_key:
        existing_loader = get_loader(existing_key)
        if existing_loader is not None:
            _annotate_backend_metadata(metadata, BACKEND_PYDICOM, existing_key)
            return getattr(existing_loader, "vtk_image_data", None), metadata

    try:
        _normalize_metadata_instances(metadata)
        lazy_volume = PyDicomLazyVolume.from_series(str(series_path), metadata=metadata)
        loader_key = lazy_volume.register()
        _annotate_backend_metadata(metadata, BACKEND_PYDICOM, loader_key)
        try:
            series_number = str((series_meta or {}).get("series_number", "-"))
            slice_count = int(getattr(lazy_volume, "slice_count", 0) or 0)
            instance_count = int(len(metadata.get("instances", []) or []))
            logger.info(
                "viewer-backend stage=open_series_bind backend=%s series=%s slices=%d instances=%d loader_key=%s",
                BACKEND_PYDICOM,
                series_number,
                slice_count,
                instance_count,
                loader_key,
                extra={
                    "component": "viewer",
                    "function": "image_io._build_lazy_volume_for_metadata",
                    "stage": "open_series_bind",
                },
            )
        except Exception:
            pass
        return lazy_volume.vtk_image_data, metadata
    except Exception as e:
        logger.warning("Lazy backend creation failed for %s: %s", series_path, e)
        _annotate_backend_metadata(metadata, BACKEND_VTK, "")
        return None, metadata


def _maybe_collect_gc(force: bool = False):
    """Avoid frequent gc.collect() in hot paths; run very rarely.
    
    gc.collect() is a STOP-THE-WORLD operation that freezes ALL Python
    threads including the UI thread. During image loading (which runs in
    background threads), calling gc.collect() causes the user to perceive
    micro-freezes in the viewer. We increase the interval drastically and
    only force-collect on explicit cleanup paths (tab close).
    """
    global _LAST_GC_TS
    now = time.time()
    if force or (now - _LAST_GC_TS) >= _GC_INTERVAL_SEC:
        gc.collect(generation=0)  # generation=0 is MUCH faster than full gc.collect()
        _LAST_GC_TS = now


def _backfill_instance_orientation(instances):
    """Backfill NULL IOP/IPP in instances by reading DICOM headers.

    When instances were inserted during initial download without IOP/IPP
    (e.g. server-side metadata push without header extraction), reference-line
    computation breaks because manage_reference_line() silently skips NULL IOP.

    This reads only the DICOM header (no pixel data) for each instance
    where IOP or IPP is missing, populates the metadata dict in-place,
    and updates the DB so the fix is persisted once per series.

    Returns True if any values were backfilled.
    """
    import json as _json

    needs_backfill = any(
        inst.get('image_orientation_patient') is None or inst.get('image_position_patient') is None
        for inst in instances
    )
    if not needs_backfill:
        return False

    backfilled = 0
    for inst in instances:
        iop = inst.get('image_orientation_patient')
        ipp = inst.get('image_position_patient')
        if iop is not None and ipp is not None:
            continue  # already populated

        fpath = inst.get('instance_path')
        if not fpath or not Path(fpath).exists():
            continue

        try:
            ds = pydicom.dcmread(str(fpath), stop_before_pixels=True, force=True)

            if iop is None:
                raw_iop = ds.get('ImageOrientationPatient', None)
                if raw_iop is not None:
                    inst['image_orientation_patient'] = [float(v) for v in raw_iop]
                    iop = inst['image_orientation_patient']

            if ipp is None:
                raw_ipp = ds.get('ImagePositionPatient', None)
                if raw_ipp is not None:
                    inst['image_position_patient'] = [float(v) for v in raw_ipp]
                    ipp = inst['image_position_patient']

            if inst.get('pixel_spacing') is None:
                raw_ps = ds.get('PixelSpacing', None)
                if raw_ps is not None:
                    inst['pixel_spacing'] = [float(v) for v in raw_ps]
            if inst.get('direction') is None:
                _dir = _direction_from_iop(inst.get('image_orientation_patient'))
                if _dir is not None:
                    inst['direction'] = _dir

            # Persist to DB so this only runs once per series
            inst_pk = inst.get('instance_pk')
            if inst_pk is not None and (iop is not None or ipp is not None):
                try:
                    with get_db_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            """UPDATE instances
                               SET image_orientation_patient = COALESCE(image_orientation_patient, ?),
                                   image_position_patient    = COALESCE(image_position_patient, ?),
                                   pixel_spacing             = COALESCE(pixel_spacing, ?),
                                   direction                 = COALESCE(direction, ?)
                               WHERE instance_pk = ?""",
                            (
                                _json.dumps(inst['image_orientation_patient']) if inst.get('image_orientation_patient') else None,
                                _json.dumps(inst['image_position_patient']) if inst.get('image_position_patient') else None,
                                _json.dumps(inst['pixel_spacing']) if inst.get('pixel_spacing') else None,
                                _json.dumps(inst['direction']) if inst.get('direction') else None,
                                inst_pk,
                            ),
                        )
                        conn.commit()
                except Exception as _db_err:
                    print(f"      WARN: backfill DB update failed for pk={inst_pk}: {_db_err}")

            backfilled += 1
        except Exception as _e:
            print(f"      WARN: backfill read failed for {fpath}: {_e}")

    if backfilled:
        _normalize_instances_geometry_order(instances)
        print(f"      🔧 [BACKFILL] populated IOP/IPP for {backfilled}/{len(instances)} instances")

    return backfilled > 0


def _get_instances_from_best_group(series_pk: int):
    """
    Return instances from the best-populated group for a series.

    Why: some studies store instances under group_id != 0. If we only query
    group 0, we incorrectly fall back to expensive filesystem regrouping.
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT group_id, COUNT(*) AS cnt
                FROM instances
                WHERE series_fk = ?
                GROUP BY group_id
                ORDER BY cnt DESC, group_id ASC
                """,
                (int(series_pk),)
            )
            rows = cur.fetchall() or []

        for group_id, cnt in rows:
            if int(cnt or 0) <= 0:
                continue
            try:
                gid = int(group_id or 0)
            except Exception:
                gid = 0
            instances = get_instances_by_series_pk(series_pk, gid) or []
            if instances:
                return gid, instances
    except Exception:
        pass

    return None, []

def _get_cached_metadata(series_pk, instances):
    """
    Get metadata from cache or generate and cache it
    """
    # Include instance count in the key so that a partial download (fewer DB
    # records) does not return a stale full-series cache entry from a previous
    # complete load.  Without this, a mixed-size or partial series could get a
    # stale N_db=20 metadata when only 8 files were actually loaded, causing
    # get_count_of_slices() to return 20 and the slider to over-run the VTK Z.
    cache_key = f"series_{series_pk}_n{len(instances)}"
    
    # Check if in cache
    if cache_key in _series_metadata_cache:
        cached = _series_metadata_cache[cache_key]
        if get_series_geometry_index(cached) is None:
            _normalize_metadata_instances(cached)
        logger.info(
            "FAST:meta_cache source=hit key=%s series_pk=%s cache_size=%d",
            cache_key, series_pk, len(_series_metadata_cache),
        )
        return cached
    
    # Generate metadata
    logger.info(
        "FAST:meta_cache source=miss key=%s series_pk=%s cache_size=%d",
        cache_key, series_pk, len(_series_metadata_cache),
    )
    metadata = read_series_instances_metadata(series_pk, instances)
    if get_series_geometry_index(metadata) is None:
        _normalize_metadata_instances(metadata)
    
    # Cache it (with size limit)
    if len(_series_metadata_cache) >= _cache_max_size:
        # Remove oldest entry (simple FIFO)
        _series_metadata_cache.pop(next(iter(_series_metadata_cache)))
    
    _series_metadata_cache[cache_key] = metadata
    return metadata


def get_itk_image_fast_first(dicom_names):
    """
    بهینه‌سازی شده برای اولین سری - سرعت بالا با کمترین overhead
    """
    try:
        # برای اولین سری، از سریع‌ترین روش استفاده می‌کنیم
        reader = sitk.ImageSeriesReader()

        # بهینه‌سازی‌های سرعت برای اولین سری
        reader.SetFileNames(dicom_names)

        # اگر فقط یک فایل داریم، مستقیماً بخوانیم
        if len(dicom_names) == 1:
            return sitk.ReadImage(dicom_names[0])

        # برای سری‌های کوچک (کمتر از 10 فایل)، روش معمولی سریع‌تر است
        if len(dicom_names) < 10:
            return reader.Execute()

        # برای سری‌های بزرگ‌تر، همان مسیر استاندارد پایدار را استفاده می‌کنیم
        return get_itk_image(dicom_names)

    except Exception as e:
        print(f"WARN: Fast first series loading failed: {e}, using standard method")
        # fallback به روش معمولی
        return get_itk_image(dicom_names)


def read_series_instances_metadata(series_pk, instances):
    metadata = {
        'series': {},
        'instances': [],
    }

    # add series info to metadata
    series_data = get_series_by_series_pk(series_pk)
    metadata['series'].update(series_data)

    # add instances to metadata
    for instance in instances:  # for each-dicom in series
        metadata['instances'].append(instance)

    return metadata


def read_segment_nifti(file):
    file = Path(file)
    itk_image = sitk.ReadImage(file)
    # metadata = {}
    # metadata["header"] = {k: itk_image.GetMetaData(k) for k in itk_image.GetMetaDataKeys()}  # for image information
    # metadata["origin"] = itk_image.GetOrigin()
    # metadata["spacing"] = itk_image.GetSpacing()
    # metadata["direction"] = itk_image.GetDirection()
    # metadata["file"] = [file]
    # metadata["format"] = "nifti"
    vtk_image_data = utils.convert_itk2vtk(itk_image)

    itk_image = None
    return vtk_image_data


def load_images_from_server(folder_path, patient_pk=None, study_pk=None, study_uid=None, number_of_instances_on_db=None,
                            lst_series_downloaded: list = None, ordering_by_instances_number=None):
    study_data = get_study_by_study_uid(study_uid)

    # ✅ FIX: Add null check for study_data
    if number_of_instances_on_db is None:
        if study_data and isinstance(study_data, dict):
            number_of_instances_on_db = study_data.get('number_of_instances', None)
        else:
            print(f"WARN [load_images_from_server] study_data is None or invalid for study_uid: {study_uid}")
            number_of_instances_on_db = None

    # print('number_of_instances_on_db!!!!!!', number_of_instances_on_db)

    # count_of_series_downloaded = utils.count_subfolders_with_dicom(folder_path)
    # series_updating = None

    # while True:
    #     series_has_dicom = utils.list_subfolders_with_dicom(folder_path)
    # if len(series_has_dicom) == len(series_read) + 1:  # downloading...
    #     series_updating = [sub for sub in series_has_dicom if sub not in series_read]
    #     continue

    # if len(series_downloaded) > len(series_read) + 1:
    #     series_downloaded = natsorted([sub for sub in series_downloaded if sub not in series_read])
    # print('vvvvvvvvvvv: ', folder_path)

    """
        - series updating: this series is that we are waiting for finish downloading.
        - series downloading: this series is that we are downloading its.
        (if series updating is different from series downloading, it means download of series updating finished.)
    """

    series_updating = None
    max_iterations = 600  # 5 minutes max (600 * 0.5 sec = 300 sec)
    iteration_count = 0
    last_checked_file = None
    same_file_count = 0

    while iteration_count < max_iterations:
        try:
            last_added_file = utils.last_added_file(folder_path)
            if last_added_file:
                # Detect if stuck on same file
                if last_checked_file == last_added_file:
                    same_file_count += 1
                    if same_file_count > 20:  # Same file for 10 seconds (20 * 0.5)
                        print(f'WARN: Stuck on same file for too long: {last_added_file}')
                        # Check if download is actually complete
                        if number_of_instances_on_db:
                            number_of_instances_on_source = utils.get_count_dicom_files_exist(folder_path)
                            if number_of_instances_on_source >= number_of_instances_on_db:
                                print('Download finished (timeout check).')
                                return load_images(series_updating if series_updating else last_added_file.parent,
                                                   patient_pk, study_pk), lst_series_downloaded, True
                        # If not complete, break out of loop to avoid infinite wait
                        print('Breaking out of download wait loop - download may be incomplete')
                        break
                else:
                    same_file_count = 0
                    last_checked_file = last_added_file

                if iteration_count % 20 == 0:  # Log every 10 seconds
                    print(f'Waiting for download... checked file: {last_added_file.name}')

                series_downloading = last_added_file.parent

                if series_updating is None:
                    series_updating = series_downloading

                lst_subs_have_dicom = utils.list_subfolders_with_dicom(folder_path)  # lst downloaded series
                if series_downloading in lst_subs_have_dicom:
                    lst_subs_have_dicom.remove(series_downloading)  # remove downloading series form downloaded series
                # remove series activated on patient_widget
                lst_subs_have_dicom = [s for s in lst_subs_have_dicom if s not in lst_series_downloaded]

                if len(lst_subs_have_dicom) > 0:
                    series_updating = lst_subs_have_dicom[0]
                    lst_series_downloaded.append(series_updating)
                    return load_images(series_updating, patient_pk, study_pk,
                                       ordering_by_instances_number=ordering_by_instances_number), lst_series_downloaded, False

                elif number_of_instances_on_db:
                    number_of_instances_on_source = utils.get_count_dicom_files_exist(folder_path)
                    if number_of_instances_on_source >= number_of_instances_on_db:  # check download ended.
                        print('Download finished.')
                        return load_images(series_updating, patient_pk, study_pk), lst_series_downloaded, True

        except Exception as e:
            print(f'WARN: Error in download wait loop: {e}')
            pass

        iteration_count += 1
        time.sleep(0.5)

    # Timeout reached
    print(f'WARN: Download wait timeout reached ({max_iterations * 0.5} seconds)')
    if series_updating:
        return load_images(series_updating, patient_pk, study_pk), lst_series_downloaded, True
    return None, lst_series_downloaded, False


def load_images(folder_path, patient_pk=None, study_pk=None, ordering_by_instances_number=None):
    """
    اسکن فولدرِ مطالعه و ساخت/به‌روزرسانی سری‌ها.
    بهینه‌سازی: قبل از ساخت itk_image، سری UID را از اولین فایل هر سری می‌خوانیم و اگر
    سری از قبل در DB بود و شمار اینستنس‌های ثبت‌شده >= تعداد فایل‌های فعلی بود، از ساخت itk_image صرف‌نظر می‌کنیم.
    """
    # print('runn:', folder_path, patient_pk, study_pk)

    # --- حالت Import از فولدر ---
    if folder_path:
        folder_path = Path(folder_path)
        subfolders = natsorted(p for p in folder_path.iterdir() if p.is_dir())  # ساب‌فولدرها

        flag_read_root = True
        if subfolders:
            for sub in subfolders:
                try:
                    size_dict = utils.group_images_base_on_size(sub,
                                                                ordering_by_instance_number=ordering_by_instances_number)
                    # در هر ساب‌فولدر سری‌ها را پردازش کن
                    for item in process_series_groups(sub, size_dict, patient_pk, study_pk):
                        yield item
                except Exception as e:
                    print(f"[WARN] load_images: subfolder {sub} skipped -> {e}")

        # اگر ساب‌فولدرِ معتبر نبود یا نیاز است ریشه را هم بخوانیم
        if (not subfolders) or (flag_read_root is True):
            try:
                size_dict_root = utils.group_images_base_on_size(folder_path,
                                                                 ordering_by_instance_number=ordering_by_instances_number)
                for item in process_series_groups(folder_path, size_dict_root, patient_pk, study_pk):
                    yield item
            except Exception as e:
                # print(f'error in loading file {folder_path}: {e}')
                pass


def load_vtk_from_dicom_paths(dicom_paths):
    """
    Load VTK image data directly from a list of DICOM file paths.
    Used for MG layout where we need to load specific instances.
    
    Args:
        dicom_paths: List of DICOM file paths (strings)
        
    Returns:
        vtk_image_data or None if loading fails
    """
    import time
    
    if not dicom_paths:
        print("[LOAD_VTK] No DICOM paths provided")
        return None
    
    try:
        _start = time.time()
        series_number_for_audit = "unknown"
        
        # Convert to strings if they're Path objects
        dicom_files = [str(p) for p in dicom_paths]
        dicom_files = natsorted(dicom_files)
        
        print(f"[LOAD_VTK] Loading {len(dicom_files)} DICOM file(s)")
        
        # Load DICOM with SimpleITK
        _dicom_start = time.time()
        itk_image = get_itk_image(dicom_files)
        try:
            _emit_advanced_vtk_orientation_audit_stage(
                series_number_for_audit,
                stage="sitk_read_filesystem",
                dicom_files_for_itk=[str(p) for p in dicom_files],
                sitk_image=itk_image,
            )
        except Exception:
            pass
        _dicom_time = time.time() - _dicom_start
        
        # Convert to VTK
        _convert_start = time.time()
        vtk_image_data = utils.convert_itk2vtk(itk_image)
        try:
            _emit_advanced_vtk_orientation_audit_stage(
                series_number_for_audit,
                stage="vtk_convert_filesystem",
                dicom_files_for_itk=[str(p) for p in dicom_files],
                metadata=None,
                vtk_image_data=vtk_image_data,
            )
        except Exception:
            pass
        _convert_time = time.time() - _convert_start
        
        # Cleanup - do NOT call gc.collect(), it freezes UI thread
        itk_image = None
        
        _total = time.time() - _start
        print(f"[LOAD_VTK] ✓ Loaded in {_total:.3f}s (DICOM={_dicom_time:.3f}s, Convert={_convert_time:.3f}s)")
        
        return vtk_image_data
        
    except Exception as e:
        print(f"[LOAD_VTK ERROR] Failed to load from paths: {e}")
        import traceback
        traceback.print_exc()
        return None


def _load_series_from_filesystem(study_path, series_number, patient_pk=None, study_pk=None):
    """
    FALLBACK: Load series directly from filesystem when DB doesn't have instances
    """
    import time
    from pathlib import Path

    try:
        _start = time.time()

        # Build path to series folder
        study_path = Path(study_path)
        series_folder = study_path / str(series_number)

        if not series_folder.exists():
            print(f"[FILESYSTEM LOAD] Series folder not found: {series_folder}")
            return None

        # Get all DICOM files in the series folder
        dicom_files = _list_unique_dicom_files(series_folder)

        if not dicom_files:
            print(f"[FILESYSTEM LOAD] No DICOM files found in {series_folder}")
            return None

        # Filter mixed-size series (SimpleITK fails if sizes differ)
        try:
            size_dict = utils.group_images_base_on_size(series_folder, ordering_by_instance_number=False)
            if size_dict:
                if len(size_dict) > 1:
                    largest_size, largest_files = max(size_dict.items(), key=lambda kv: len(kv[1]))
                    other_counts = {f"{k[0]}x{k[1]}": len(v) for k, v in size_dict.items() if k != largest_size}
                    dicom_files = natsorted([Path(f) for f in largest_files])
                    print(
                        f"[FILESYSTEM LOAD] Size mismatch detected; using {largest_size} with {len(dicom_files)} files, skipping {other_counts}"
                    )
                else:
                    only_files = next(iter(size_dict.values()))
                    dicom_files = natsorted([Path(f) for f in only_files])
        except Exception as e:
            print(f"[FILESYSTEM LOAD] WARN: size grouping failed, using all files: {e}")

        print(f"[FILESYSTEM LOAD] Loading series {series_number} from filesystem with {len(dicom_files)} files")

        # ── Build instances list from DICOM headers BEFORE loading ITK ──────
        # We need IPP/IOP to canonical-sort, so read headers first (cheap),
        # then call get_itk_image in the canonical order.
        _meta_start = time.time()
        instances = []
        for i, dicom_file in enumerate(dicom_files):
            try:
                dcm = utils._safe_dcmread(dicom_file, stop_before_pixels=True)
                
                # ✅ IMPROVED: Better window/level extraction with None fallback
                window_width = dcm.get('WindowWidth', None)
                window_center = dcm.get('WindowCenter', None)
                
                # Handle MultiValue DICOM tags
                if window_width is not None:
                    if hasattr(window_width, '__iter__') and not isinstance(window_width, str):
                        window_width = float(window_width[0])
                    else:
                        window_width = float(window_width)
                
                if window_center is not None:
                    if hasattr(window_center, '__iter__') and not isinstance(window_center, str):
                        window_center = float(window_center[0])
                    else:
                        window_center = float(window_center)
                
                # If missing, try modality-based defaults (CT gets 400/40, others get None for auto-calc)
                if window_width is None or window_center is None:
                    modality = dcm.get('Modality', None)
                    if modality == 'CT':
                        window_width = window_width if window_width is not None else 400
                        window_center = window_center if window_center is not None else 40
                
                # Extract orientation/position/spacing so reference-line
                # code never raises KeyError on filesystem-loaded series.
                try:
                    raw_iop = dcm.get('ImageOrientationPatient', None)
                    _iop = [float(v) for v in raw_iop] if raw_iop is not None else None
                except Exception:
                    _iop = None
                try:
                    raw_ipp = dcm.get('ImagePositionPatient', None)
                    _ipp = [float(v) for v in raw_ipp] if raw_ipp is not None else None
                except Exception:
                    _ipp = None
                try:
                    raw_ps = dcm.get('PixelSpacing', None)
                    _ps = [float(v) for v in raw_ps] if raw_ps is not None else None
                except Exception:
                    _ps = None

                # Read actual DICOM InstanceNumber (NOT loop index)
                _inst_num_raw = dcm.get('InstanceNumber', None)
                try:
                    _inst_num = int(_inst_num_raw) if _inst_num_raw is not None else i
                except (TypeError, ValueError):
                    _inst_num = i

                instance = {
                    'instance_number': _inst_num,
                    'instance_path': str(dicom_file),
                    'rows': int(dcm.get('Rows', 512)),
                    'columns': int(dcm.get('Columns', 512)),
                    'window_width': window_width,
                    'window_center': window_center,
                    'is_rgb': dcm.PhotometricInterpretation in ['RGB', 'YBR_FULL', 'YBR_FULL_422'],
                    'sop_uid': dcm.get('SOPInstanceUID', f'generated_{i}'),
                    'image_orientation_patient': _iop,
                    'image_position_patient': _ipp,
                    'pixel_spacing': _ps,
                    'slice_thickness': _safe_float(dcm.get('SliceThickness', None)),
                    'spacing_between_slices': _safe_float(dcm.get('SpacingBetweenSlices', None)),
                    'rescale_slope': _safe_float(dcm.get('RescaleSlope', None), 1.0),
                    'rescale_intercept': _safe_float(dcm.get('RescaleIntercept', None), 0.0),
                    'bits_allocated': int(dcm.get('BitsAllocated', 16) or 16),
                    'pixel_representation': int(dcm.get('PixelRepresentation', 1) or 1),
                }
                instances.append(instance)
            except Exception as e:
                print(f"[FILESYSTEM LOAD] Error reading DICOM metadata from {dicom_file}: {e}")
                continue

        if not instances:
            print(f"[FILESYSTEM LOAD] Could not read metadata from any DICOM file")
            return None

        geometry_index, _geometry_cache_hit = _get_or_build_series_geometry_index(
            [str(path) for path in dicom_files],
            patient_code=str(patient_pk or ""),
            series_number=str(series_number),
            source="fresh_files",
        )
        instances = geometry_index.display_instances_metadata()
        dicom_files = [Path(path) for path in geometry_index.dicom_files_for_itk]

        _meta_time = time.time() - _meta_start

        # ── Load DICOM with SimpleITK in canonical order ──────────────────────
        _dicom_start = time.time()
        itk_image = get_itk_image(dicom_files)
        _dicom_time = time.time() - _dicom_start

        # ── Alignment validation ──────────────────────────────────────────────
        try:
            _tmp_meta = {"instances": instances}
            _validate_sitk_metadata_alignment(
                series_number, _tmp_meta, [str(p) for p in dicom_files]
            )
        except Exception:
            pass

        # ── Volume alignment hash (Item 5 diagnostics) ───────────────────────
        try:
            _tmp_meta_hash = {"instances": instances}
            _emit_volume_alignment_hash(
                series_number, _tmp_meta_hash, [str(p) for p in dicom_files]
            )
        except Exception:
            pass

        # تبدیل به VTK
        _convert_start = time.time()
        vtk_image_data = utils.convert_itk2vtk(itk_image)
        _convert_time = time.time() - _convert_start

        # Build basic metadata structure
        first_dcm = utils._safe_dcmread(dicom_files[0], stop_before_pixels=True)

        metadata = {
            'series': {
                'series_number': str(series_number),
                'series_name': str(series_number),
                'series_description': first_dcm.get('SeriesDescription', f'Series {series_number}'),
                'series_thk': str(first_dcm.get('SliceThickness', '1.0')),
                'modality': geometry_index.modality or first_dcm.get('Modality', 'CT'),
                'protocol_name': first_dcm.get('ProtocolName', ''),
                'body_part_examined': geometry_index.body_part or first_dcm.get('BodyPartExamined', ''),
                'orientation': first_dcm.get('ImageOrientationPatient', [1, 0, 0, 0, 1, 0]),
                'series_instance_uid': geometry_index.series_uid,
                'study_instance_uid': geometry_index.study_uid,
                'patient_position': geometry_index.patient_position,
                'laterality': geometry_index.laterality,
                'geometry_plane': geometry_index.plane,
                'main_thumbnail': True,
            },
            'instances': instances,
        }
        stamp_metadata_with_geometry_index(metadata, geometry_index)

        _meta_time = time.time() - _meta_start

        # Cleanup - do NOT call gc.collect(), it freezes threads
        itk_image = None

        _total = time.time() - _start
        print(
            f"[FILESYSTEM LOAD] ✓ Series {series_number}: {_total:.3f}s (DICOM={_dicom_time:.3f}s, Convert={_convert_time:.3f}s, Meta={_meta_time:.3f}s)")

        return vtk_image_data, metadata, (patient_pk, study_pk)

    except Exception as e:
        print(f"[FILESYSTEM LOAD ERROR] Failed to load series {series_number}: {e}")
        import traceback
        traceback.print_exc()
        return None


def _has_direct_dicom_files(path: Path) -> bool:
    """True when *path* contains DICOM files directly (not only in subfolders)."""
    try:
        if not path or not path.exists() or not path.is_dir():
            return False
        for pattern in ("*.dcm", "*.DCM", "*.dicom", "*.DICOM"):
            if next(path.glob(pattern), None):
                return True
    except Exception:
        return False
    return False


def _study_root_matches_series_number(study_path: Path, series_number) -> bool:
    """Support flat imported studies where the selected folder is the series folder."""
    if not _has_direct_dicom_files(study_path):
        return False
    try:
        info = utils.get_quickly_series_info(study_path)
    except Exception:
        return False
    if not info:
        return False
    return str(info.get("series_number", "")).strip() == str(series_number).strip()


def load_single_series_by_number(study_path, series_number, patient_pk=None, study_pk=None,
                                 ordering_by_instances_number=None, skip_fs_validation=False,
                                 max_itk_threads=None, max_pydicom_workers=None,
                                 viewer_backend=None, allow_lazy_backend: bool = True):
    """
    ✅ OPTIMIZED: Load a single series by number with detailed timing

    v2.2.3.2.4: Added *max_pydicom_workers* — forwarded to
    process_series_groups → get_or_create_instance so the viewer process
    can limit GIL contention from pydicom ThreadPool during Mode B.
    """
    import time
    _func_start = time.time()
    t_total = now_ms()
    
    # Path resolution
    _path_start = time.time()
    series_path = Path(f'{study_path}/{series_number}')
    _path_scan_mode = "direct_path"
    _path_scan_ms = 0.0
    _path_scan_candidates = 0
    _path_scan_probes = 0
    _path_scan_matches = 0
    
    if not series_path.exists():
        # Try alternative naming patterns
        study_path_obj = Path(study_path)
        _path_scan_mode = "fallback_resolution"

        if _study_root_matches_series_number(study_path_obj, series_number):
            series_path = study_path_obj
            _path_scan_mode = "study_root_match"
        else:
            # Look for series folder with the series number in the name
            _scan_start = time.time()
            potential_series_folders = []
            _candidate_dirs = 0
            _dicom_probe_calls = 0
            _path_scan_mode = "folder_scan"
            for item in study_path_obj.iterdir():
                if item.is_dir():
                    _candidate_dirs += 1
                    # Check if directory name contains the series number
                    if str(series_number) in item.name:
                        # Probe with a fast count instead of listing all DICOM files.
                        _dicom_probe_calls += 1
                        if _count_dicom_files_fast(item) > 0:
                            potential_series_folders.append(item)

            _scan_time = time.time() - _scan_start
            _path_scan_ms = _scan_time * 1000.0
            _path_scan_candidates = _candidate_dirs
            _path_scan_probes = _dicom_probe_calls
            _path_scan_matches = len(potential_series_folders)

            if potential_series_folders:
                # Sort by folder name and take the first one
                potential_series_folders.sort()
                series_path = potential_series_folders[0]
                print(f"      Found series folder: {series_path.name} (looking for series {series_number})")
            else:
                # Fallback: get series path from DB
                series_path_from_db = None
                if study_pk:
                    try:
                        series_path_from_db = get_series_path_with_study_pk_and_series_number(study_pk, series_number)
                    except Exception as e:
                        print(f"      WARN: Error getting series path from DB: {e}")

                if series_path_from_db and Path(series_path_from_db).exists():
                    series_path = Path(series_path_from_db)
                    _path_scan_mode = "db_series_path"
                    print(f"      Using series path from DB: {series_path}")
                else:
                    # Last fallback: try to find series folder by number pattern
                    series_name = find_series_folder_by_series_number(study_path, series_number)
                    if series_name:
                        series_path = Path(f'{study_path}/{series_name}')
                        _path_scan_mode = "series_name_fallback"
                    else:
                        logger.info(
                            "viewer-data stage=path_scan duration_ms=%.2f candidates=%d probes=%d matches=%d mode=%s",
                            _path_scan_ms,
                            _path_scan_candidates,
                            _path_scan_probes,
                            _path_scan_matches,
                            "not_found",
                            extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "path_scan"},
                        )
                        error_msg = f'Series {series_number} not found in study {study_path}'
                        print(f'ERROR: {error_msg}')
                        # Instead of raising error, return None
                        return

    logger.info(
        "viewer-data stage=path_scan duration_ms=%.2f candidates=%d probes=%d matches=%d mode=%s",
        _path_scan_ms,
        _path_scan_candidates,
        _path_scan_probes,
        _path_scan_matches,
        _path_scan_mode,
        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "path_scan"},
    )
    
    _path_time = time.time() - _path_start
    print(f"      Path resolution: {_path_time:.3f}s")
    logger.info(
        "viewer-data stage=path_resolution duration_ms=%.2f",
        _path_time * 1000.0,
        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "path_resolution"},
    )
    
    # Check if series_path exists after all attempts
    _emit_viewer_resource_probe()

    # Check if series_path exists after all attempts
    if not series_path or not series_path.exists():
        print(f"      ERROR: Series folder not found after all attempts: series {series_number}")
        return

    print(f"      Loading from: {series_path}")

    # ─── FAST EARLY EXIT: pydicom_qt skips the entire ITK + SimpleITK pipeline ────
    # When Qt viewer backend is active, Lightweight2DPipeline decodes slices
    # on demand from the raw DICOM files — VTK image data is never used for
    # rendering.  Running apply_filters() + convert_itk2vtk() (6-9s on MR)
    # was a complete waste of CPU.  We build metadata only and yield a minimal
    # stub vtkImageData so downstream cache-key checks (vtk is not None) keep
    # working without changes.  Fixed in v2.3.1.
    if allow_lazy_backend and viewer_backend == BACKEND_PYDICOM_QT:
        _qt_meta = None
        # v2.3.7: fine-grained sub-stage timing to pinpoint the 4s cold-open
        # slowdown seen in log 96 (load_single_series_total=4022+4389ms).
        _qt_substage_ms = {}
        if study_pk:
            try:
                from PacsClient.utils.database import find_series_pk_by_number
                _t_db = now_ms()
                _qt_series_pk = find_series_pk_by_number(series_number, study_pk)
                if _qt_series_pk:
                    _qt_instances = get_instances_by_series_pk(_qt_series_pk, group_id=0)
                    if not _qt_instances:
                        _, _qt_instances = _get_instances_from_best_group(_qt_series_pk)
                    _qt_substage_ms['db_lookup'] = now_ms() - _t_db
                    if _qt_instances:
                        _t_meta = now_ms()
                        _qt_meta = _get_cached_metadata(_qt_series_pk, _qt_instances)
                        _qt_substage_ms['cached_metadata'] = now_ms() - _t_meta
                        _t_recon = now_ms()
                        _qt_instances_merged, _qt_instances_changed = _reconcile_db_instances_with_disk(
                            series_path, _qt_meta.get('instances', [])
                        )
                        _qt_substage_ms['reconcile_disk'] = now_ms() - _t_recon
                        if _qt_instances_merged:
                            if _qt_instances_changed:
                                _qt_meta = {
                                    **_qt_meta,
                                    'series': dict((_qt_meta.get('series') or {})),
                                    'instances': _qt_instances_merged,
                                }
                            _ensure_series_meta(_qt_meta)['image_count'] = len(_qt_instances_merged)
                        if _metadata_needs_geometry_backfill(_qt_meta):
                            _t_backfill = now_ms()
                            try:
                                _backfill_instance_orientation(_qt_meta.get('instances', []))
                            except Exception:
                                pass
                            _qt_substage_ms['backfill_orientation'] = now_ms() - _t_backfill
                        _t_norm = now_ms()
                        try:
                            _normalize_metadata_instances(_qt_meta)
                        except Exception:
                            pass
                        _qt_substage_ms['normalize'] = now_ms() - _t_norm
            except Exception as _qt_err:
                logger.warning(
                    "pydicom_qt fast-path DB metadata failed (%s); falling back to ITK pipeline",
                    _qt_err,
                )
        if _qt_meta is None:
            _t_hdr = now_ms()
            try:
                _qt_meta = _build_metadata_headers_only(series_path, series_number)
                try:
                    _normalize_metadata_instances(_qt_meta)
                except Exception:
                    pass
            except Exception as _hdr_err:
                logger.warning(
                    "pydicom_qt fast-path header-only metadata failed (%s); falling back to ITK pipeline",
                    _hdr_err,
                )
            _qt_substage_ms['headers_only_build'] = now_ms() - _t_hdr
        if _qt_meta and _qt_meta.get('instances'):
            _ensure_series_meta(_qt_meta).setdefault('series_path', str(series_path))
            _annotate_backend_metadata(_qt_meta, BACKEND_PYDICOM_QT, '')
            # Minimal stub vtkImageData — correct dimensions for logging; never rendered.
            try:
                _qt_first = (_qt_meta.get('instances') or [{}])[0]
                _qt_rows = int(_qt_first.get('rows') or 1) or 1
                _qt_cols = int(_qt_first.get('columns') or 1) or 1
                _qt_n = len(_qt_meta.get('instances', []))
                _qt_stub = vtk.vtkImageData()
                _qt_stub.SetDimensions(_qt_cols, _qt_rows, _qt_n)
                _qt_stub.AllocateScalars(vtk.VTK_SHORT, 1)
            except Exception:
                _qt_stub = None
            # v2.3.7: emit sub-stage breakdown so we can see where the 4s goes
            if _qt_substage_ms:
                try:
                    _qt_parts = " ".join(f"{k}={v:.0f}ms" for k, v in _qt_substage_ms.items())
                    logger.info("[FAST_LOAD_BREAKDOWN] series=%s %s", series_number, _qt_parts)
                except Exception:
                    pass
            log_stage_timing(
                logger,
                component="viewer",
                function="image_io.load_single_series_by_number",
                stage="load_single_series_total",
                start_ms=t_total,
                source="pydicom_qt_fast",
            )
            # ── FAST geometry mismatch diagnostic ──────────────────────────
            # FAST pipeline renders slices in instance_number order.
            # Reference-line / sync code needs IPP geometry order.
            # Log when the two orderings differ so we know FAST sync
            # is working from a reordered metadata copy.
            try:
                _fast_insts = _qt_meta.get("instances") or []
                if len(_fast_insts) >= 2:
                    _geo_normals = []
                    for _fi in _fast_insts:
                        _fi_iop = _fi.get("image_orientation_patient")
                        if _fi_iop and len(_fi_iop) >= 6:
                            _fr = np.asarray(_fi_iop[0:3], dtype=float)
                            _fc = np.asarray(_fi_iop[3:6], dtype=float)
                            _fn = np.cross(_fr, _fc)
                            _fnl = float(np.linalg.norm(_fn))
                            if _fnl > 1e-9:
                                _geo_normals.append(_fn / _fnl)
                    if len(_geo_normals) >= 2:
                        _mean_n = np.asarray(_geo_normals).mean(axis=0)
                        _mean_nl = float(np.linalg.norm(_mean_n))
                        if _mean_nl > 1e-9:
                            _mean_n = _mean_n / _mean_nl
                            _ipp_keys = []
                            for _fi in _fast_insts:
                                _fi_ipp = _fi.get("image_position_patient")
                                if _fi_ipp and len(_fi_ipp) >= 3:
                                    _ipp_keys.append(float(np.dot(_fi_ipp, _mean_n)))
                                else:
                                    _ipp_keys.append(None)
                            _ipp_valid = [k for k in _ipp_keys if k is not None]
                            if len(_ipp_valid) == len(_fast_insts):
                                _ipp_sorted_idx = sorted(range(len(_ipp_keys)), key=lambda i: _ipp_keys[i])
                                _orig_idx = list(range(len(_fast_insts)))
                                if _ipp_sorted_idx != _orig_idx:
                                    # First slice that differs
                                    _first_diff = next(
                                        (i for i, (a, b) in enumerate(zip(_ipp_sorted_idx, _orig_idx)) if a != b), 0
                                    )
                                    logger.info(
                                        "[FAST_GEOMETRY_ORDER_MISMATCH] series=%s slices=%d "
                                        "instance_number_order != ipp_geometry_order "
                                        "first_diff_idx=%d normal=[%.3f,%.3f,%.3f] "
                                        "sync_will_use_reordered_copy=True",
                                        series_number, len(_fast_insts), _first_diff,
                                        float(_mean_n[0]), float(_mean_n[1]), float(_mean_n[2]),
                                        extra={"component": "viewer"},
                                    )
                                else:
                                    logger.debug(
                                        "[FAST_GEOMETRY_ORDER_MISMATCH] series=%s slices=%d "
                                        "instance_number_order == ipp_geometry_order (no mismatch)",
                                        series_number, len(_fast_insts),
                                        extra={"component": "viewer"},
                                    )
            except Exception:
                pass
            print(
                f"      [pydicom_qt] Metadata-only path: ITK+VTK pipeline skipped "
                f"(slices={len(_qt_meta.get('instances', []))})"
            )
            yield _qt_stub, _qt_meta, (patient_pk, study_pk)
            return
        logger.warning(
            "pydicom_qt fast-path produced no instances for series %s; "
            "falling back to ITK pipeline",
            series_number,
        )
    # ─────────────────────────────────────────────────────────────────────────────

    selected_backend = BACKEND_VTK if not allow_lazy_backend else viewer_backend
    resolution = resolve_viewer_backend(metadata=None, settings=selected_backend)
    active_backend = str(resolution.get("backend", BACKEND_VTK))

    # Lazy PyDicom path: header/metadata only + on-demand slice decode.
    if active_backend == BACKEND_PYDICOM:
        global _DECODER_PREFLIGHT_LOGGED
        if not _DECODER_PREFLIGHT_LOGGED:
            _DECODER_PREFLIGHT_LOGGED = True
            missing_pkgs = _missing_decoder_packages()
            if missing_pkgs:
                logger.warning(
                    "PyDicom decoder preflight missing packages: %s. %s",
                    ", ".join(missing_pkgs),
                    _decode_dependency_hint(),
                )
        _lazy_start = time.time()
        try:
            lazy_metadata = None
            if study_pk:
                from PacsClient.utils.database import find_series_pk_by_number

                series_pk = find_series_pk_by_number(series_number, study_pk)
                if series_pk:
                    instances = get_instances_by_series_pk(series_pk, group_id=0) or []
                    if not instances:
                        _gid, instances = _get_instances_from_best_group(series_pk)
                    if instances:
                        # Validate DB completeness against disk — same check
                        # as the VTK/ITK path.  Without this the lazy backend
                        # opens with a partial instance list when the DB hasn't
                        # caught up to the actual files on disk.
                        try:
                            _on_disk = _list_unique_dicom_files(series_path)
                            _disk_count = len(_on_disk)
                            _db_count = len(instances)
                            if _disk_count > 1 and _db_count < _disk_count:
                                logger.info(
                                    "pydicom-lazy: DB instances incomplete for series %s "
                                    "(db=%d disk=%d) -> using disk scan for metadata",
                                    series_number, _db_count, _disk_count,
                                )
                                instances = None  # fall through to disk scan
                        except Exception:
                            pass
                    if instances:
                        lazy_metadata = _get_cached_metadata(series_pk, instances)

            if lazy_metadata is None:
                lazy_metadata = _build_metadata_headers_only(series_path, series_number)

            if lazy_metadata and lazy_metadata.get("instances"):
                try:
                    _backfill_instance_orientation(lazy_metadata.get("instances", []))
                except Exception:
                    pass
                try:
                    _normalize_metadata_instances(lazy_metadata)
                except Exception:
                    pass
                _ensure_series_meta(lazy_metadata).setdefault("series_path", str(series_path))
                geom_ok, geom_reason = _validate_lazy_geometry(lazy_metadata)
                if not geom_ok:
                    logger.warning(
                        "PyDicom lazy disabled for series %s due to incomplete geometry (%s); fallback to VTK",
                        series_number,
                        geom_reason,
                    )
                    _annotate_backend_metadata(lazy_metadata, BACKEND_VTK, "")
                else:
                    vtk_lazy, lazy_metadata = _build_lazy_volume_for_metadata(series_path, lazy_metadata)
                    if vtk_lazy is not None:
                        _lazy_ms = (time.time() - _lazy_start) * 1000.0
                        try:
                            _ensure_series_meta(lazy_metadata)["pydicom_lazy_build_ms"] = float(_lazy_ms)
                        except Exception:
                            pass
                        logger.info(
                            "viewer-data stage=pydicom_lazy_build duration_ms=%.2f",
                            _lazy_ms,
                            extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "pydicom_lazy_build"},
                        )
                        log_stage_timing(
                            logger,
                            component="viewer",
                            function="image_io.load_single_series_by_number",
                            stage="load_single_series_total",
                            start_ms=t_total,
                            source="pydicom_lazy",
                        )
                        yield vtk_lazy, lazy_metadata, (patient_pk, study_pk)
                        return
        except Exception as e:
            logger.warning(
                "PyDicom lazy path failed for series %s: %s. %s Falling back to VTK.",
                series_number,
                e,
                _decode_dependency_hint(),
            )
    
    # ✅ OPTIMIZATION: Try to load directly from DB first (much faster!)
    if study_pk:
        _db_check_start = time.time()
        try:
            from PacsClient.utils.database import find_series_pk_by_number
            series_pk = find_series_pk_by_number(series_number, study_pk)
            
            if series_pk:
                # Series exists in DB - load directly without file grouping!
                print(f"      Series found in DB (series_pk={series_pk}), skipping file grouping...")
                
                instances = get_instances_by_series_pk(series_pk, group_id=0)
                selected_group_id = 0
                if not instances:
                    selected_group_id, instances = _get_instances_from_best_group(series_pk)
                    if instances:
                        print(
                            f"      DB group fallback: using group_id={selected_group_id} "
                            f"with {len(instances)} instances"
                        )
                if not instances:
                    print(
                        f"      INFO: series_pk={series_pk} found in DB but no instance records "
                        f"(download subprocess hasn't written them yet) → filesystem fallback"
                    )
                if instances and len(instances) > 0:
                    # Validate DB instance completeness against filesystem to avoid
                    # partial-stack bug (e.g., only first image loaded).
                    # skip_fs_validation=True: warmup/background callers trust DB
                    # paths — if wrong, ITK reader fails gracefully.  Skipping
                    # the glob + per-file exists() saves 0.1–0.5s per series
                    # under disk contention.
                    if not skip_fs_validation:
                        try:
                            on_disk = _list_unique_dicom_files(series_path)
                            # Windows is case-insensitive; avoid double-counting same files.
                            on_disk_unique = {str(p).lower() for p in on_disk}
                            on_disk_count = len(on_disk_unique)
                        except Exception:
                            on_disk_count = 0

                        db_count = len(instances)
                        missing_paths = 0
                        try:
                            for inst in instances:
                                p = inst.get('instance_path')
                                if not p or not Path(p).exists():
                                    missing_paths += 1
                        except Exception:
                            missing_paths = 0

                        db_incomplete = (
                            (on_disk_count > 1 and db_count < on_disk_count) or
                            (on_disk_count > 1 and db_count <= 1) or
                            (missing_paths > 0)
                        )

                        if db_incomplete:
                            print(
                                f"      WARN: DB instances incomplete for series {series_number}: "
                                f"db={db_count}, disk={on_disk_count}, missing_paths={missing_paths} -> "
                                f"fallback to filesystem full load"
                            )
                            fs_result = _load_series_from_filesystem(study_path, series_number, patient_pk, study_pk)
                            if fs_result:
                                fs_vtk, fs_meta, fs_patient_info = fs_result
                                _annotate_backend_metadata(fs_meta, BACKEND_VTK, "")
                                yield fs_vtk, fs_meta, fs_patient_info
                                return

                    # We have instances in DB - use them directly
                    _db_check_time = time.time() - _db_check_start
                    print(f"      DB check: {_db_check_time:.3f}s")
                    logger.info(
                        "db-query stage=find_series_pk_and_instances duration_ms=%.2f query_type=viewer_read",
                        _db_check_time * 1000.0,
                        extra={"component": "db", "function": "image_io.load_single_series_by_number", "stage": "viewer_db_read"},
                    )
                    
                    # Get metadata (cached) - needed before filters
                    _meta_start = time.time()
                    metadata = _get_cached_metadata(series_pk, instances)
                    _meta_time = time.time() - _meta_start
                    print(f"      Metadata: {_meta_time:.3f}s")
                    logger.info(
                        "viewer-data stage=metadata_build duration_ms=%.2f",
                        _meta_time * 1000.0,
                        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "metadata_build"},
                    )

                    geometry_source_files = [
                        str(inst.get("instance_path"))
                        for inst in (metadata.get("instances", []) or instances)
                        if inst.get("instance_path")
                    ]
                    geometry_index, _geometry_cache_hit = _get_or_build_series_geometry_index(
                        geometry_source_files,
                        patient_code=str(patient_pk or ""),
                        study_uid=str((metadata.get("series", {}) or {}).get("study_instance_uid") or ""),
                        series_uid=str((metadata.get("series", {}) or {}).get("series_instance_uid") or ""),
                        series_number=str(series_number),
                        source="db",
                    )
                    stamp_metadata_with_geometry_index(metadata, geometry_index)
                    _series_meta = metadata.get("series") if isinstance(metadata, dict) else {}
                    if isinstance(_series_meta, dict):
                        _series_meta["series_instance_uid"] = geometry_index.series_uid
                        _series_meta["study_instance_uid"] = geometry_index.study_uid
                        _series_meta["body_part_examined"] = geometry_index.body_part or _series_meta.get("body_part_examined", "")
                        _series_meta["patient_position"] = geometry_index.patient_position
                        _series_meta["laterality"] = geometry_index.laterality
                        _series_meta["geometry_plane"] = geometry_index.plane
                        if geometry_index.modality:
                            _series_meta["modality"] = geometry_index.modality

                    # Final shared ordered list used by SimpleITK + metadata + sync index mapping.
                    dicom_files = list(geometry_index.dicom_files_for_itk)

                    # v2.2.3.3.8: Quick size pre-check — sample first and last
                    # file headers (~2ms) to detect incomplete-download size
                    # mismatch BEFORE attempting the expensive ITK read.
                    if len(dicom_files) >= 2:
                        try:
                            _ds_first = pydicom.dcmread(dicom_files[0], stop_before_pixels=True, force=True, specific_tags=['Rows', 'Columns'])
                            _ds_last = pydicom.dcmread(dicom_files[-1], stop_before_pixels=True, force=True, specific_tags=['Rows', 'Columns'])
                            _r0 = int(getattr(_ds_first, 'Rows', 0) or 0)
                            _c0 = int(getattr(_ds_first, 'Columns', 0) or 0)
                            _r1 = int(getattr(_ds_last, 'Rows', 0) or 0)
                            _c1 = int(getattr(_ds_last, 'Columns', 0) or 0)
                            if _r0 > 0 and _c0 > 0 and _r1 > 0 and _c1 > 0 and (_r0, _c0) != (_r1, _c1):
                                print(
                                    f"      WARN: Size pre-check mismatch: first={_r0}x{_c0} last={_r1}x{_c1}"
                                    f" → pre-filtering {len(dicom_files)} files by dominant size"
                                )
                                dicom_files, _dom_size, _dom_skipped = _select_dominant_size_dicom_files(dicom_files)
                                if _dom_size:
                                    print(f"      Pre-filtered to {len(dicom_files)} files of {_dom_size}, skipped {_dom_skipped}")
                        except Exception:
                            pass

                    # ── Clip metadata['instances'] to match surviving dicom_files ──
                    # If the size pre-filter removed mixed-dimension slices,
                    # dicom_files is now shorter than metadata['instances'].  The
                    # yielded (vtk, meta) pair must be aligned or get_count_of_slices
                    # on the viewer will return meta_count > vtk_z, causing the
                    # K-flip slider to map lower display positions to out-of-range
                    # raw_k values → frozen image for the bottom half of the stack.
                    try:
                        _meta_insts = metadata.get('instances') or []
                        if len(dicom_files) != len(_meta_insts):
                            logger.warning(
                                "[PARTIAL_STACK_CLIP] series=%s meta_instances=%d dicom_files=%d "
                                "— clipping metadata to match loaded files",
                                series_number, len(_meta_insts), len(dicom_files),
                                extra={"component": "viewer"},
                            )
                            _surviving = {str(p).lower() for p in dicom_files}
                            _clipped = [
                                inst for inst in _meta_insts
                                if str(inst.get('instance_path', '')).lower() in _surviving
                            ]
                            if len(_clipped) == len(dicom_files):
                                metadata['instances'] = _clipped
                            else:
                                # Path matching incomplete — truncate by index as fallback
                                metadata['instances'] = _meta_insts[:len(dicom_files)]
                    except Exception:
                        pass

                    # ── Alignment validation ─────────────────────────────────
                    try:
                        _validate_sitk_metadata_alignment(
                            series_number, metadata, dicom_files
                        )
                    except Exception:
                        pass

                    # ── Volume alignment hash (Item 5 diagnostics) ───────────
                    try:
                        _emit_volume_alignment_hash(
                            series_number, metadata, dicom_files
                        )
                    except Exception:
                        pass

                    metadata["_instances_geometry_sorted"] = True

                    # Load DICOM files from the final shared order.
                    _dicom_start = time.time()
                    itk_image = get_itk_image(dicom_files)
                    _emit_advanced_vtk_orientation_audit_stage(
                        series_number,
                        stage="sitk_read_db",
                        dicom_files_for_itk=dicom_files,
                        metadata=metadata,
                        sitk_image=itk_image,
                    )
                    _dicom_time = time.time() - _dicom_start
                    print(f"      DICOM load (from DB paths): {_dicom_time:.3f}s")
                    logger.info(
                        "viewer-data stage=disk_read duration_ms=%.2f source=db_paths",
                        _dicom_time * 1000.0,
                        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "disk_read"},
                    )

                    # ── CPU yield: brief pause for UI responsiveness ──
                    # v2.2.3.2.3: Reduced from 50ms→5ms.  DL_WARMUP now runs in
                    # a subprocess so this path is only hit by interactive loads
                    # (Mode A) and first-series display (Mode B).  5ms is enough
                    # for one Qt event loop iteration without adding 100ms to
                    # perceived series load time.
                    time.sleep(0.005)

                    # Apply ITK filters before conversion
                    _filter_start = time.time()
                    from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
                    try:
                        itk_image = apply_filters(itk_image, metadata, max_itk_threads=max_itk_threads)
                    except Exception as filter_exc:
                        logger.warning(
                            "viewer-data stage=itk_filter_chain_fallback reason=%s modality=%s series=%s",
                            filter_exc,
                            str((metadata.get("series", {}) or {}).get("modality", "") or ""),
                            str((metadata.get("series", {}) or {}).get("series_number", "") or ""),
                            extra={
                                "component": "viewer",
                                "function": "image_io.load_single_series_by_number",
                                "stage": "itk_filter_chain_fallback",
                            },
                        )
                    _filter_time = time.time() - _filter_start
                    print(f"      ITK filters: {_filter_time:.3f}s")
                    logger.info(
                        "viewer-data stage=itk_filter_chain duration_ms=%.2f",
                        _filter_time * 1000.0,
                        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "itk_filter_chain"},
                    )

                    # ── CPU yield: brief pause for UI responsiveness ──
                    # v2.2.3.2.3: Reduced from 50ms→5ms (see note above).
                    time.sleep(0.005)
                    
                    # Convert to VTK
                    _convert_start = time.time()
                    vtk_image_data = utils.convert_itk2vtk(itk_image)
                    _emit_advanced_vtk_orientation_audit_stage(
                        series_number,
                        stage="vtk_convert_db",
                        dicom_files_for_itk=dicom_files,
                        metadata=metadata,
                        vtk_image_data=vtk_image_data,
                    )
                    _convert_time = time.time() - _convert_start
                    print(f"      ITK->VTK convert: {_convert_time:.3f}s")
                    logger.info(
                        "viewer-data stage=itk_to_vtk_convert duration_ms=%.2f",
                        _convert_time * 1000.0,
                        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "itk_to_vtk"},
                    )
                    
                    # Cleanup - do NOT call gc.collect() here, it freezes UI thread
                    itk_image = None
                    del itk_image
                    # _maybe_collect_gc removed: convert_itk2vtk now frees ITK early
                    
                    _func_total = time.time() - _func_start
                    print(f"      TOTAL (DB path): {_func_total:.3f}s")
                    log_stage_timing(
                        logger,
                        component="viewer",
                        function="image_io.load_single_series_by_number",
                        stage="load_single_series_total",
                        start_ms=t_total,
                        source="db_path",
                    )
                    _annotate_backend_metadata(metadata, BACKEND_VTK, "")
                    yield vtk_image_data, metadata, (patient_pk, study_pk)
                    return
        except Exception as e:
            print(f"      WARN: DB fast path failed: {e}, falling back to file grouping")

    # Fallback: enumerate + size-group before attempting any ITK read.
    # v2.2.3.3.8: Previously used a single-entry size_dict without real size
    # grouping, so mixed-size series (from incomplete downloads) caused the
    # expensive get_itk_image → retry → re-raise cascade to run 3-4 times
    # (5-12 seconds per failing series).  Now we use group_images_base_on_size
    # to pre-filter, matching _load_series_from_filesystem behaviour.
    _group_start = time.time()
    size_dict = {}
    try:
        size_dict = utils.group_images_base_on_size(series_path, ordering_by_instance_number=False)
    except Exception:
        pass
    if not size_dict:
        # Fallback if group_images_base_on_size fails/returns empty
        dicom_files = _list_unique_dicom_files(series_path)
        if dicom_files:
            size_dict = {("single_series", len(dicom_files)): dicom_files}
    _group_time = time.time() - _group_start
    print(f"      Group images: {_group_time:.3f}s")
    logger.info(
        "viewer-data stage=group_images duration_ms=%.2f",
        _group_time * 1000.0,
        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "group_images"},
    )

    if not size_dict:
        print(f"      ERROR: No DICOM files found for series {series_number}")
        return

    # Process series groups
    _process_start = time.time()
    for item in process_series_groups(series_path, size_dict, patient_pk, study_pk,
                                      max_itk_threads=max_itk_threads,
                                      max_pydicom_workers=max_pydicom_workers):
        try:
            vtk_image_data, metadata, patient_info = item
        except Exception:
            continue
        _annotate_backend_metadata(metadata, BACKEND_VTK, "")
        yield vtk_image_data, metadata, patient_info
    _process_time = time.time() - _process_start
    
    _func_total = time.time() - _func_start
    print(f"      Process groups: {_process_time:.3f}s")
    print(f"      TOTAL load_single_series: {_func_total:.3f}s")
    logger.info(
        "viewer-data stage=process_groups duration_ms=%.2f",
        _process_time * 1000.0,
        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "process_groups"},
    )
    log_stage_timing(
        logger,
        component="viewer",
        function="image_io.load_single_series_by_number",
        stage="load_single_series_total",
        start_ms=t_total,
        source="filesystem_path",
    )


def load_series_preview(study_path, series_number, patient_pk=None, study_pk=None, max_files: int = 1):
    """
    Load a lightweight preview (first slice) for a series to enable instant display.
    Returns (vtk_image_data, metadata, (patient_pk, study_pk), total_files) or None.
    """
    import time
    _start = time.time()

    series_path = Path(f'{study_path}/{series_number}')

    if not series_path.exists():
        study_path_obj = Path(study_path)
        potential_series_folders = []
        for item in study_path_obj.iterdir():
            if item.is_dir() and str(series_number) in item.name:
                dicom_files = _list_unique_dicom_files(item)
                if dicom_files:
                    potential_series_folders.append(item)
        if potential_series_folders:
            potential_series_folders.sort()
            series_path = potential_series_folders[0]
        else:
            series_name = find_series_folder_by_series_number(study_path, series_number)
            if series_name:
                series_path = Path(f'{study_path}/{series_name}')
            else:
                return None

    if not series_path.exists():
        return None

    dicom_files = _list_unique_dicom_files(series_path)
    if not dicom_files:
        return None
    total_files = len(dicom_files)
    preview_files = dicom_files[: max(1, int(max_files or 1))]

    try:
        if len(preview_files) == 1:
            itk_image = sitk.ReadImage(str(preview_files[0]))
        else:
            itk_image = get_itk_image_fast_first([str(p) for p in preview_files])
    except Exception as e_first:
        try:
            itk_image = get_itk_image([str(p) for p in preview_files])
        except Exception as e_fallback:
            print(
                f"[PREVIEW] Failed to load series {series_number} preview from {series_path}: "
                f"primary={e_first}; fallback={e_fallback}"
            )
            return None

    vtk_image_data = utils.convert_itk2vtk(itk_image)

    series_meta = None
    instances = []
    if study_pk:
        try:
            from PacsClient.utils.database import find_series_pk_by_number
            series_pk = find_series_pk_by_number(series_number, study_pk)
            if series_pk:
                series_meta = get_series_by_series_pk(series_pk)
                instances_full = get_instances_by_series_pk(series_pk, group_id=0) or []
                instances = instances_full[: len(preview_files)]
                # Backfill NULL IOP/IPP for preview (same fix as full load path)
                try:
                    _backfill_instance_orientation(instances)
                except Exception:
                    pass
        except Exception:
            series_meta = None

    if not instances:
        try:
            first_dcm = utils._safe_dcmread(preview_files[0], stop_before_pixels=True)
            _iop_raw = first_dcm.get('ImageOrientationPatient', None)
            _ipp_raw = first_dcm.get('ImagePositionPatient', None)
            _ps_raw = first_dcm.get('PixelSpacing', None)
            instances = [
                {
                    'instance_number': 1,
                    'instance_path': str(preview_files[0]),
                    'rows': int(first_dcm.get('Rows', 512)),
                    'columns': int(first_dcm.get('Columns', 512)),
                    'window_width': first_dcm.get('WindowWidth', None),
                    'window_center': first_dcm.get('WindowCenter', None),
                    'is_rgb': first_dcm.get('PhotometricInterpretation', '') in ['RGB', 'YBR_FULL', 'YBR_FULL_422'],
                    'image_orientation_patient': [float(v) for v in _iop_raw] if _iop_raw is not None else None,
                    'image_position_patient': [float(v) for v in _ipp_raw] if _ipp_raw is not None else None,
                    'pixel_spacing': [float(v) for v in _ps_raw] if _ps_raw is not None else None,
                }
            ]
            if not series_meta:
                series_meta = {
                    'series_number': str(series_number),
                    'series_name': str(series_number),
                    'series_description': first_dcm.get('SeriesDescription', f'Series {series_number}'),
                    'series_thk': str(first_dcm.get('SliceThickness', '1.0')),
                    'modality': first_dcm.get('Modality', 'CT'),
                    'protocol_name': first_dcm.get('ProtocolName', ''),
                    'body_part_examined': first_dcm.get('BodyPartExamined', ''),
                    'main_thumbnail': True,
                }
        except Exception:
            pass

    metadata = {
        'series': series_meta or {'series_number': str(series_number), 'series_name': str(series_number)},
        'instances': instances or [],
        'preview_only': True,
        'preview_total_instances': total_files,
    }
    _annotate_backend_metadata(metadata, BACKEND_VTK, "")

    itk_image = None

    _elapsed = time.time() - _start
    print(f"      Preview load: series {series_number} with {len(preview_files)}/{total_files} files in {_elapsed:.3f}s")

    return vtk_image_data, metadata, (patient_pk, study_pk), total_files

def process_series_groups(base_path: Path, size_groups: dict, patient_pk, study_pk,
                          max_itk_threads=None, max_pydicom_workers=None):
    """
        base_path: Path to series/subfolder
        size_groups: map of (rows, cols) -> list[file paths] where each is a series
        max_itk_threads: optional cap on ITK thread count (None = use default).
        max_pydicom_workers: optional cap on pydicom header-read ThreadPool workers
            (None = use default of 8).  v2.2.3.2.4: viewer-process callers
            pass 2 to reduce GIL contention during first-series Mode B loads.
    """
    # TIMING: Import time module
    import time
    
    # Fix: Check if size_groups is empty
    if not size_groups:
        print(f"[WARN] process_series_groups: No images found in {base_path}, skipping")
        return
    
    # If we don't have patient/study, create from first file of first series
    if (patient_pk is None) and (study_pk is None):
        # Fix: Check data existence before accessing
        if not size_groups or len(size_groups.values()) == 0:
            print(f"[WARN] No size groups available to create patient/study")
            return
            
        first_group = list(size_groups.values())
        if not first_group or len(first_group[0]) == 0:
            print(f"[WARN] First group is empty, cannot create patient/study")
            return
            
        first_file = first_group[0][0]
        patient_pk_local = utils.get_or_create_patient(first_file)

        study_path = base_path
        base_path_is_series = utils.check_folder_has_dicom(study_path)
        if base_path_is_series:
            study_path = str(study_path.parent)  # select study (series's parent)
        study_pk_local = utils.get_or_create_study(first_file, patient_pk_local, study_path)

        study_data = get_studies_by_patient_pk(patient_pk_local)
        study_uid = study_data['study_uid']
        if (study_data['number_of_series'] == 0) or (study_data['number_of_instances'] == 0):
            count_of_series, count_of_instances = utils.count_study_series_instances(study_path)
            update_study_counts_by_uid(study_uid=study_uid,
                                       number_of_series=count_of_series, number_of_instances=count_of_instances)

    else:
        patient_pk_local, study_pk_local = patient_pk, study_pk

    for i, files in enumerate(size_groups.values()):  # each "files" is a series
        try:
            _series_start = time.time()
            main_thumbnail = (i == 0)
            
            print(f"         Processing group {i+1}/{len(size_groups)} with {len(files)} files...")

            # TIMING: Load DICOM
            _dicom_start = time.time()
            # OPTIMIZATION: Use fast method for first series, standard for rest
            if i == 0:
                itk_image = get_itk_image_fast_first(files)
            else:
                itk_image = get_itk_image(files)
            _dicom_time = time.time() - _dicom_start
            print(f"            DICOM load: {_dicom_time:.3f}s")

            # TIMING: Database operations
            _db_start = time.time()
            
            # OPTIMIZATION: Check if series already exists in DB to skip redundant operations
            _series_lookup_start = time.time()
            # Create/update series record
            series_pk = utils.get_or_create_series(
                files[0], study_pk_local, itk_image, main_thumbnail, str(base_path)
            )
            _series_lookup_time = time.time() - _series_lookup_start
            print(f"               - Series lookup/create: {_series_lookup_time:.3f}s")

            # Insert new instances (only new ones are registered; duplicates are skipped)
            _instance_start = time.time()
            utils.get_or_create_instance(files, itk_image, series_pk, group_id=i,
                                         max_workers=max_pydicom_workers)
            _instance_time = time.time() - _instance_start
            print(f"               - Instance create: {_instance_time:.3f}s")

            # Metadata + generate vtkImageData
            _metadata_start = time.time()
            instances = get_instances_by_series_pk(series_pk, group_id=i)
            
            # Use cached metadata for better performance
            metadata = _get_cached_metadata(series_pk, instances)
            _metadata_time = time.time() - _metadata_start
            print(f"               - Metadata fetch: {_metadata_time:.3f}s")
            
            _db_time = time.time() - _db_start
            print(f"            Database operations: {_db_time:.3f}s")

            # ── CPU yield: let UI/download threads breathe after DB + DICOM I/O ──
            # v2.2.3.2.4: Reduced 50ms→5ms.  DL_WARMUP runs in a subprocess
            # now; long yields just slow first-series display.
            time.sleep(0.005)

            # Apply ITK filters before conversion
            _filter_start = time.time()
            from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
            try:
                itk_image = apply_filters(itk_image, metadata, max_itk_threads=max_itk_threads)
            except Exception as filter_exc:
                logger.warning(
                    "viewer-data stage=itk_filter_chain_fallback reason=%s modality=%s series=%s",
                    filter_exc,
                    str((metadata.get("series", {}) or {}).get("modality", "") or ""),
                    str((metadata.get("series", {}) or {}).get("series_number", "") or ""),
                    extra={
                        "component": "viewer",
                        "function": "image_io.load_images",
                        "stage": "itk_filter_chain_fallback",
                    },
                )
            _filter_time = time.time() - _filter_start
            print(f"            ITK filters: {_filter_time:.3f}s")

            # ── CPU yield: let UI/download threads breathe after ITK filters ──
            # v2.2.3.2.4: Reduced 50ms→5ms (see above note).
            time.sleep(0.005)

            # Convert to VTK
            _convert_start = time.time()
            vtk_image_data = utils.convert_itk2vtk(itk_image)
            _convert_time = time.time() - _convert_start
            print(f"            ITK->VTK convert: {_convert_time:.3f}s")
            
            itk_image = None
            del itk_image

            _total_group = time.time() - _series_start
            print(f"         Group {i+1} completed in {_total_group:.3f}s\n")
            
            yield vtk_image_data, metadata, (patient_pk_local, study_pk_local)

        except Exception as e:
            # Some folders/series might be corrupted; the whole pipeline shouldn't stop
            print(f"[WARN] load_images: Failed series at {base_path} -> {e}")
            continue
