import os
import gc
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
from .image_filters import apply_filters

# import utils
sitk.ProcessObject.SetGlobalWarningDisplay(False)
sitk.ImageSeriesReader.SetGlobalWarningDisplay(False)
from natsort import natsorted
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, get_series_by_study_pk, \
    get_instances_by_series_pk, get_series_by_series_pk, find_series_pk, get_study_by_study_uid, \
    update_study_counts_by_uid, get_connection_database, get_series_path_with_study_pk_and_series_number
from PacsClient.utils.viewer_backend_config import (
    BACKEND_PYDICOM,
    BACKEND_VTK,
    resolve_viewer_backend,
)
from PacsClient.pacs.patient_tab.viewers.backends.pydicom_lazy_volume import PyDicomLazyVolume
from PacsClient.pacs.patient_tab.viewers.backends.lazy_volume_registry import get_loader
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
_cache_max_size = 100  # Maximum number of cached series
_LAST_GC_TS = 0.0
_GC_INTERVAL_SEC = 120.0  # was 20s → 120s: gc.collect is stop-the-world and freezes ALL threads (UI included)
_DECODER_PREFLIGHT_LOGGED = False


def _list_unique_dicom_files(folder: Path) -> list:
    """Return unique DICOM files under folder (case-insensitive), naturally sorted."""
    raw = list(folder.glob("*.dcm")) + list(folder.glob("*.DCM"))
    uniq = []
    seen = set()
    for p in raw:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    return natsorted(uniq)


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


def _normalize_instances_geometry_order(instances):
    if not isinstance(instances, list) or len(instances) <= 1:
        return False

    ref_iop = None
    for inst in instances:
        ref_iop = _safe_float_list(inst.get("image_orientation_patient"), 6)
        if ref_iop is not None:
            break
    if ref_iop is None:
        return False

    row = np.asarray(ref_iop[0:3], dtype=float)
    col = np.asarray(ref_iop[3:6], dtype=float)
    normal = np.cross(row, col)
    normal_n = float(np.linalg.norm(normal))
    if normal_n <= 1e-9:
        return False
    normal = normal / normal_n

    decorated = []
    for original_idx, inst in enumerate(instances):
        ipp = _safe_float_list(inst.get("image_position_patient"), 3)
        if ipp is None:
            return False
        proj = float(np.dot(np.asarray(ipp, dtype=float), normal))
        decorated.append((proj, original_idx, inst))

    sorted_instances = [inst for _, _, inst in sorted(decorated, key=lambda item: (item[0], item[1]))]
    changed = any(sorted_instances[i] is not instances[i] for i in range(len(instances)))
    if changed:
        instances[:] = sorted_instances

    # Keep DB-compatible direction payload populated for downstream consumers.
    for inst in instances:
        if inst.get("direction"):
            continue
        direction = _direction_from_iop(inst.get("image_orientation_patient"))
        if direction is not None:
            inst["direction"] = direction

    return changed


def _normalize_metadata_instances(metadata):
    if not isinstance(metadata, dict):
        return False
    changed = _normalize_instances_geometry_order(metadata.get("instances"))
    try:
        series_meta = _ensure_series_meta(metadata)
        if isinstance(series_meta, dict):
            series_meta["instances_geometry_sorted"] = True
    except Exception:
        pass
    return changed


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

            ww = dcm.get("WindowWidth", None)
            wc = dcm.get("WindowCenter", None)
            iop = dcm.get("ImageOrientationPatient", None)
            ipp = dcm.get("ImagePositionPatient", None)
            ps = dcm.get("PixelSpacing", None)

            instances.append(
                {
                    "instance_number": int(dcm.get("InstanceNumber", i) or i),
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
            )
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
                    conn = get_connection_database()
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
        conn = get_connection_database()
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
        conn.close()

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
    cache_key = f"series_{series_pk}"
    
    # Check if in cache
    if cache_key in _series_metadata_cache:
        cached = _series_metadata_cache[cache_key]
        _normalize_metadata_instances(cached)
        return cached
    
    # Generate metadata
    metadata = read_series_instances_metadata(series_pk, instances)
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
        
        # Convert to strings if they're Path objects
        dicom_files = [str(p) for p in dicom_paths]
        dicom_files = natsorted(dicom_files)
        
        print(f"[LOAD_VTK] Loading {len(dicom_files)} DICOM file(s)")
        
        # Load DICOM with SimpleITK
        _dicom_start = time.time()
        itk_image = get_itk_image(dicom_files)
        _dicom_time = time.time() - _dicom_start
        
        # Convert to VTK
        _convert_start = time.time()
        vtk_image_data = utils.convert_itk2vtk(itk_image)
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

        # بارگذاری DICOM با SimpleITK
        _dicom_start = time.time()
        itk_image = get_itk_image(dicom_files)
        _dicom_time = time.time() - _dicom_start

        # تبدیل به VTK
        _convert_start = time.time()
        vtk_image_data = utils.convert_itk2vtk(itk_image)
        _convert_time = time.time() - _convert_start

        # ساخت metadata from DICOM files
        _meta_start = time.time()

        # Create instances list from DICOM files for metadata
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

                instance = {
                    'instance_number': i,
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
                }
                instances.append(instance)
            except Exception as e:
                print(f"[FILESYSTEM LOAD] Error reading DICOM metadata from {dicom_file}: {e}")
                continue

        if not instances:
            print(f"[FILESYSTEM LOAD] Could not read metadata from any DICOM file")
            return None

        # Build basic metadata structure
        first_dcm = utils._safe_dcmread(dicom_files[0], stop_before_pixels=True)

        metadata = {
            'series': {
                'series_number': str(series_number),
                'series_name': str(series_number),
                'series_description': first_dcm.get('SeriesDescription', f'Series {series_number}'),
                'series_thk': str(first_dcm.get('SliceThickness', '1.0')),
                'modality': first_dcm.get('Modality', 'CT'),
                'protocol_name': first_dcm.get('ProtocolName', ''),
                'body_part_examined': first_dcm.get('BodyPartExamined', ''),
                'orientation': first_dcm.get('ImageOrientationPatient', [1, 0, 0, 0, 1, 0]),
                'main_thumbnail': True,
            },
            'instances': instances,
        }

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
    
    if not series_path.exists():
        # Try alternative naming patterns
        study_path_obj = Path(study_path)
        
        # Look for series folder with the series number in the name
        potential_series_folders = []
        for item in study_path_obj.iterdir():
            if item.is_dir():
                # Check if directory name contains the series number
                if str(series_number) in item.name:
                    # Check if it has DICOM files
                    dicom_files = _list_unique_dicom_files(item)
                    if dicom_files:
                        potential_series_folders.append(item)
        
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
                print(f"      Using series path from DB: {series_path}")
            else:
                # Last fallback: try to find series folder by number pattern
                series_name = find_series_folder_by_series_number(study_path, series_number)
                if series_name:
                    series_path = Path(f'{study_path}/{series_name}')
                else:
                    error_msg = f'Series {series_number} not found in study {study_path}'
                    print(f'ERROR: {error_msg}')
                    # Instead of raising error, return None
                    return
    
    _path_time = time.time() - _path_start
    print(f"      Path resolution: {_path_time:.3f}s")
    logger.info(
        "viewer-data stage=path_resolution duration_ms=%.2f",
        _path_time * 1000.0,
        extra={"component": "viewer", "function": "image_io.load_single_series_by_number", "stage": "path_resolution"},
    )
    
    # Check if series_path exists after all attempts
    if not series_path or not series_path.exists():
        print(f"      ERROR: Series folder not found after all attempts: series {series_number}")
        return
    
    print(f"      Loading from: {series_path}")
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
                    
                    # Load DICOM files from instance paths
                    _dicom_start = time.time()
                    # DB query is already ordered by instance_number; avoid extra filesystem sorting.
                    dicom_files = [str(inst.get('instance_path')) for inst in instances if inst.get('instance_path')]

                    # v2.2.3.3.8: Quick size pre-check — sample first and last
                    # file headers (~2ms) to detect incomplete-download size
                    # mismatch BEFORE attempting the expensive ITK read.
                    # Without this, get_itk_image() reads ALL files from disk
                    # before discovering the mismatch, wasting 2-5 seconds.
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
                            pass  # pre-check failed, proceed normally

                    itk_image = get_itk_image(dicom_files)
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

                    # Backfill NULL IOP/IPP from DICOM headers (fixes
                    # reference-line failure for series imported without
                    # per-instance orientation metadata).
                    try:
                        if _backfill_instance_orientation(metadata.get('instances', [])):
                            # Invalidate metadata cache so next load uses corrected data
                            _cache_key = f"series_{series_pk}"
                            _series_metadata_cache.pop(_cache_key, None)
                    except Exception as _bf_err:
                        print(f"      WARN: IOP/IPP backfill error: {_bf_err}")
                    try:
                        _normalize_metadata_instances(metadata)
                    except Exception:
                        pass

                    # Apply ITK filters before conversion
                    _filter_start = time.time()
                    from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
                    itk_image = apply_filters(itk_image, metadata, max_itk_threads=max_itk_threads)
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
    except Exception:
        itk_image = get_itk_image([str(p) for p in preview_files])

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
            itk_image = apply_filters(itk_image, metadata, max_itk_threads=max_itk_threads)
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
