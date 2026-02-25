from __future__ import annotations
import os
import gc
import subprocess
import platform

import vtkmodules.all as vtk
import SimpleITK as sitk
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QMessageBox, QPushButton, QSizePolicy, QStyleOptionButton, QStyle
from vtkmodules.util import numpy_support
from PIL import Image
import numpy as np
from pathlib import Path
from PacsClient.utils.config import THUMBNAIL_PATH, ATTACHMENT_PATH, SOURCE_PATH
from PacsClient.utils import update_series_thumbnail_path, get_series_thumbnail_path
from datetime import datetime
import uuid
import json
from natsort import natsorted
from pydicom import config
from collections import defaultdict

from typing import Optional, Union

# config.enforce_valid_values = True
config.settings.reading_validation_mode = config.IGNORE  # مهم: پیش از dcmread

import pydicom

# import gc
# gc.set_debug(gc.DEBUG_UNCOLLECTABLE)
# gc.collect()
from PacsClient.utils import (insert_patient, insert_study, insert_series, insert_instance, \
                              find_patient_pk, find_study_pk, find_series_pk, find_instance_pk,
                              update_patient_missing_fields, update_study_missing_fields, update_series_missing_fields,
                              update_instance_missing_fields)

import warnings, ast
from pydicom.charset import python_encoding

# ثبت نگاشت کُدک برای ISO 2022 IR 159 (JIS X 0213)
try:
    ''.encode('iso2022_jp_3')  # اگر در پایتونِ شما موجود است، همین را بگیر
    python_encoding.setdefault('ISO 2022 IR 159', 'iso2022_jp_3')
except LookupError:
    # در برخی پلتفرم‌ها iso2022_jp_3 نیست؛ از ext استفاده کن
    python_encoding.setdefault('ISO 2022 IR 159', 'iso2022_jp_ext')

from contextlib import contextmanager


@contextmanager
def _suppress_pydicom_unknown_encoding():
    # فقط هشدار «Unknown encoding …» را بی‌اثر می‌کنیم تا dcmread بیفتد
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Unknown encoding .* - using default encoding instead",
            category=UserWarning
        )
        yield


def _safe_dcmread(path, **kwargs):
    # یک dcmread امن که هشدار charset را موقتاً خاموش می‌کند
    with _suppress_pydicom_unknown_encoding():
        return pydicom.dcmread(str(path), force=True, **kwargs)


def _sanitize_specific_character_set(ds):
    """اگر SpecificCharacterSet به‌صورت strِ شبیه لیست ذخیره شده، به list واقعی تبدیلش کن."""
    scs = ds.get('SpecificCharacterSet', None)
    if isinstance(scs, str) and scs.strip().startswith('[') and 'ISO' in scs:
        try:
            ds.SpecificCharacterSet = ast.literal_eval(scs)
        except Exception:
            ds.SpecificCharacterSet = ['ISO_IR 100']


def _maybe_fix_charset_inplace(in_path: str | os.PathLike) -> bool:
    """
    اگر فایل DICOM SpecificCharacterSet ناسالم (مثلاً "['ISO_IR 100','ISO 2022 IR 159']") داشت
    یا شامل 'ISO 2022 IR 159' بود، آن را به UTF-8 (ISO_IR 192) تبدیل و «روی همان فایل» بازنویسی می‌کند.
    True=فیکس شد، False=نیازی نبود یا نشد.
    """
    try:
        # 1) خواندن سبک‌وزن با suppression هشدار
        ds = _safe_dcmread(in_path, stop_before_pixels=True)

        # 2) تشخیص نیاز به فیکس
        needs_fix = False
        scs = ds.get('SpecificCharacterSet', None)

        # حالت 1: SCS به‌شکل رشته‌ی شبیه لیست ذخیره شده
        if isinstance(scs, str) and scs.strip().startswith('[') and 'ISO' in scs:
            needs_fix = True

        # حالت 2: شامل IR 159
        if isinstance(scs, (list, pydicom.multival.MultiValue, tuple)):
            if any(str(s).strip().upper() == 'ISO 2022 IR 159' for s in scs):
                needs_fix = True
        elif isinstance(scs, str) and 'ISO 2022 IR 159' in scs:
            needs_fix = True

        if not needs_fix:
            return False

        # 3) بارخوانی کامل با suppression هشدار
        ds = _safe_dcmread(in_path)
        _sanitize_specific_character_set(ds)  # اگر SCS رشته‌ای-لیستی بود → list واقعی

        # 4) استاندارد: از این به بعد UTF-8
        ds.SpecificCharacterSet = ['ISO_IR 192']

        # 5) متای لازم
        if not getattr(ds, "file_meta", None):
            ds.fix_meta_info()
        if not getattr(ds.file_meta, "TransferSyntaxUID", None):
            from pydicom.uid import ExplicitVRLittleEndian
            ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian  # فقط اگر خالی بود

        # 6) بازنویسی روی همان فایل
        ds.save_as(str(in_path), write_like_original=False)
        return True

    except Exception as e:
        print(f"⚠️ charset fix failed for {in_path}: {e}")
        return False


def get_orientation_label(direction_cosines: tuple):
    orientation = []  # default orientation (Right-Anterior-Superior)
    abs_of_orie = [abs(ele) for ele in direction_cosines]
    max_index = abs_of_orie.index(max(abs_of_orie))
    if max_index == 0:
        if direction_cosines[max_index] > 0:
            orientation.append('R')  # +x --> Right
        else:
            orientation.append('L')  # -x --> Left
    elif max_index == 1:
        if direction_cosines[max_index] > 0:
            orientation.append('A')  # +z --> Anterior
        else:
            orientation.append('P')  # -z --> Posterior
    elif max_index == 2:
        if direction_cosines[max_index] > 0:
            orientation.append('I')  # +y --> Inferior
        else:
            orientation.append('S')  # -y --> Superior

    return ''.join(orientation)


def determine_orientation(itk_image: sitk.Image):
    direction = itk_image.GetDirection()
    x_direction = direction[0], direction[3], direction[6]
    y_direction = direction[1], direction[4], direction[7]
    z_direction = direction[2], direction[5], direction[8]

    # Determine orientation for each axis
    x_orientation = get_orientation_label(x_direction)
    y_orientation = get_orientation_label(y_direction)
    z_orientation = get_orientation_label(z_direction)

    # Combine the orientation labels
    combined_orientation = x_orientation + y_orientation + z_orientation

    return combined_orientation


def convert_itk2vtk(itk_image: sitk.Image):
    """
    OPTIMIZED: Fast conversion from SimpleITK to VTK
    Now also extracts and stores direction matrix for proper MPR orientation
    """
    # 1) ساخت vtkImageData با ابعاد/اسپیسینگ/اوریجین
    x, y, z = itk_image.GetSize()
    vtk_image = vtk.vtkImageData()
    vtk_image.SetDimensions(x, y, z)
    vtk_image.SetSpacing(itk_image.GetSpacing())
    vtk_image.SetOrigin(itk_image.GetOrigin())
    
    # Extract Direction Matrix for proper MPR orientation
    direction = itk_image.GetDirection()
    
    # --- PIPELINE LOG: ITK input properties (lightweight) ---
    _itk_origin = itk_image.GetOrigin()
    _itk_spacing = itk_image.GetSpacing()
    _itk_size = itk_image.GetSize()
    print(
        f"[PIPELINE ITK→VTK] size=({_itk_size[0]},{_itk_size[1]},{_itk_size[2]}) "
        f"spacing=({_itk_spacing[0]:.3f},{_itk_spacing[1]:.3f},{_itk_spacing[2]:.3f})"
    )
    
    direction_matrix = vtk.vtkMatrix4x4()
    direction_matrix.Identity()
    
    for row in range(3):
        for col in range(3):
            direction_matrix.SetElement(row, col, direction[row * 3 + col])

    arr = sitk.GetArrayFromImage(itk_image)
    
    # FREE ITK image IMMEDIATELY after extracting numpy array.
    # This reduces peak memory by ~150 MB per series during conversion.
    # The caller still holds a reference but we explicitly break it here
    # since we no longer need the ITK data.
    del itk_image
    
    arr = arr[:, ::-1, :]  # Flip Y axis for VTK
    
    # Update direction matrix for Y-axis flip
    for col in range(3):
        direction_matrix.SetElement(1, col, -direction_matrix.GetElement(1, col))
    
    # Store direction matrix as field data
    direction_array = vtk.vtkDoubleArray()
    direction_array.SetName("DirectionMatrix")
    direction_array.SetNumberOfTuples(16)
    for i in range(4):
        for j in range(4):
            direction_array.SetValue(i * 4 + j, direction_matrix.GetElement(i, j))
    vtk_image.GetFieldData().AddArray(direction_array)
    
    # Also store the ORIGINAL ITK origin as field data
    # (needed for correct patient-space conversion after Y-flip)
    origin_array = vtk.vtkDoubleArray()
    origin_array.SetName("ITKOrigin")
    origin_array.SetNumberOfTuples(3)
    origin_array.SetValue(0, _itk_origin[0])
    origin_array.SetValue(1, _itk_origin[1])
    origin_array.SetValue(2, _itk_origin[2])
    vtk_image.GetFieldData().AddArray(origin_array)

    # Store original ITK spacing (before any display upsampling)
    spacing_arr = vtk.vtkDoubleArray()
    spacing_arr.SetName("ITKSpacing")
    spacing_arr.SetNumberOfTuples(3)
    spacing_arr.SetValue(0, _itk_spacing[0])
    spacing_arr.SetValue(1, _itk_spacing[1])
    spacing_arr.SetValue(2, _itk_spacing[2])
    vtk_image.GetFieldData().AddArray(spacing_arr)

    # Store original ITK dimensions (before any display upsampling)
    dims_arr = vtk.vtkDoubleArray()
    dims_arr.SetName("ITKDimensions")
    dims_arr.SetNumberOfTuples(3)
    dims_arr.SetValue(0, float(x))
    dims_arr.SetValue(1, float(y))
    dims_arr.SetValue(2, float(z))
    vtk_image.GetFieldData().AddArray(dims_arr)

    # OPTIMIZATION: Only copy if contiguous is required
    if not arr.flags['C_CONTIGUOUS']:
        arr = arr.copy()

    # 3) OPTIMIZATION: Direct conversion without deep copy when possible
    if arr.ndim == 4 and arr.shape[-1] == 3 and arr.dtype == np.uint8:
        vtk_arr = numpy_support.numpy_to_vtk(arr.reshape(-1, 3), deep=False,
                                             array_type=vtk.VTK_UNSIGNED_CHAR)
    else:
        # Use deep=False for faster conversion (VTK will manage memory)
        vtk_arr = numpy_support.numpy_to_vtk(arr.ravel(order='C'), deep=False)

    vtk_image.GetPointData().SetScalars(vtk_arr)
    
    # SAFETY: Keep a strong reference to the numpy array on the VTK object.
    # deep=False means VTK wraps the numpy buffer without copying. If Python
    # garbage-collects `arr`, VTK reads freed memory. This pin prevents that.
    vtk_image._numpy_backing_store = arr
    
    return vtk_image


def convert_itk2vtk_fast_first(itk_image: sitk.Image) -> tuple:
    """
    بهینه‌سازی شده برای اولین سری - تبدیل سریع ITK به VTK
    Now also properly stores direction matrix for MPR orientation
    """
    try:
        # بهینه‌سازی‌های سرعت برای اولین سری
        dims = itk_image.GetSize()
        spacing = itk_image.GetSpacing()
        origin = itk_image.GetOrigin()
        direction = itk_image.GetDirection()

        vtk_image_data = vtk.vtkImageData()
        vtk_image_data.SetDimensions(dims)
        vtk_image_data.SetSpacing(spacing)
        vtk_image_data.SetOrigin(origin)
        
        # Store direction matrix (same as convert_itk2vtk)
        direction_matrix = vtk.vtkMatrix4x4()
        direction_matrix.Identity()
        for row in range(3):
            for col in range(3):
                direction_matrix.SetElement(row, col, direction[row * 3 + col])

        # تبدیل سریع‌تر با کمترین overhead
        image_array = sitk.GetArrayFromImage(itk_image)

        # بررسی سریع RGB
        is_rgb = len(image_array.shape) == 4 and image_array.shape[-1] == 3
        
        # Apply Y-flip to match VTK conventions (same as convert_itk2vtk)
        image_array = image_array[:, ::-1, :]
        if not image_array.flags['C_CONTIGUOUS']:
            image_array = image_array.copy()
        
        # Update direction matrix to account for Y-flip
        # Negate ROW 1 (Y direction vector), not column 1
        for col in range(3):
            direction_matrix.SetElement(1, col, -direction_matrix.GetElement(1, col))
        
        # Store direction matrix as field data
        direction_array = vtk.vtkDoubleArray()
        direction_array.SetName("DirectionMatrix")
        direction_array.SetNumberOfTuples(16)
        for i in range(4):
            for j in range(4):
                direction_array.SetValue(i * 4 + j, direction_matrix.GetElement(i, j))
        vtk_image_data.GetFieldData().AddArray(direction_array)

        # Store original ITK origin
        origin_arr = vtk.vtkDoubleArray()
        origin_arr.SetName("ITKOrigin")
        origin_arr.SetNumberOfTuples(3)
        for idx_o in range(3):
            origin_arr.SetValue(idx_o, origin[idx_o])
        vtk_image_data.GetFieldData().AddArray(origin_arr)

        # Store original ITK spacing (before any display upsampling)
        spacing_arr = vtk.vtkDoubleArray()
        spacing_arr.SetName("ITKSpacing")
        spacing_arr.SetNumberOfTuples(3)
        for idx_s in range(3):
            spacing_arr.SetValue(idx_s, spacing[idx_s])
        vtk_image_data.GetFieldData().AddArray(spacing_arr)

        # Store original ITK dimensions (before any display upsampling)
        dims_arr_fd = vtk.vtkDoubleArray()
        dims_arr_fd.SetName("ITKDimensions")
        dims_arr_fd.SetNumberOfTuples(3)
        for idx_d in range(3):
            dims_arr_fd.SetValue(idx_d, float(dims[idx_d]))
        vtk_image_data.GetFieldData().AddArray(dims_arr_fd)

        if is_rgb:
            # RGB processing - optimized
            vtk_array = numpy_support.numpy_to_vtk(
                image_array.reshape(-1, 3),
                deep=False,  # shallow copy برای سرعت بیشتر
                array_type=vtk.VTK_UNSIGNED_CHAR
            )
        else:
            # Grayscale processing - optimized
            vtk_array = numpy_support.numpy_to_vtk(
                image_array.ravel(order='C'),
                deep=False,  # shallow copy برای سرعت بیشتر
                array_type=vtk.VTK_FLOAT
            )

        vtk_image_data.GetPointData().SetScalars(vtk_array)
        return vtk_image_data

    except Exception as e:
        print(f"⚠️ Fast ITK to VTK conversion failed: {e}, using standard method")
        # fallback به روش معمولی
        return convert_itk2vtk(itk_image)


def get_or_create_patient(file):
    meta_dicom = _safe_dcmread(file, stop_before_pixels=True)
    patient_id = str(meta_dicom.get("PatientID", "N/A"))

    patient_pk = find_patient_pk(patient_id)
    patient_name = str(meta_dicom.get("PatientName", "N/A"))
    patient_birthdate = str(meta_dicom.get("PatientBirthDate", "N/A"))
    patient_sex = str(meta_dicom.get("PatientSex", "N/A"))
    patient_age = str(meta_dicom.get("PatientAge", "N/A"))
    patient_weight = str(meta_dicom.get("PatientWeight", "N/A"))

    if patient_pk:
        # فقط فیلدهای خالی/NULL را با مقادیر جدید پر کن
        update_patient_missing_fields(
            patient_pk,
            patient_id=patient_id,
            name=patient_name,
            birth_date=patient_birthdate,
            sex=patient_sex,
            age=patient_age,
            patient_weight=patient_weight,
        )
        return patient_pk

    # add new patient to patient-table
    patient_pk = insert_patient(patient_id, patient_name, patient_birthdate, patient_sex, patient_age, patient_weight)
    return patient_pk


def get_or_create_study(file, patient_pk, study_path):
    # اگر برای این patient یک study ثبت‌شده دارید، آپدیتِ مقادیر خالی انجام شود
    study_pk = find_study_pk(patient_pk)
    meta_dicom = _safe_dcmread(file, stop_before_pixels=True)
    study_uid = str(meta_dicom.get("StudyInstanceUID", "N/A"))

    study_date = meta_dicom.get("StudyDate", None)
    if study_date:
        try:
            date_obj = datetime.strptime(study_date, "%Y%m%d")
            study_date = date_obj.strftime("%Y/%m/%d")
        except:
            study_date = str(study_date)

    study_time = str(meta_dicom.get("StudyTime", "N/A"))
    study_description = str(meta_dicom.get("StudyDescription", "N/A"))
    institution_name = str(meta_dicom.get("InstitutionName", "N/A"))
    modality = meta_dicom.get('Modality', 'N/A')
    bodypart = str(meta_dicom.get("BodyPartExamined", "N/A"))

    if study_pk:
        update_study_missing_fields(
            study_pk,
            study_uid=study_uid,
            study_date=study_date,
            study_time=study_time,
            study_description=study_description,
            institution_name=institution_name,
            modality=modality,
            body_part=bodypart,
            study_path=str(study_path),
        )
        return study_pk

    study_pk = insert_study(study_uid, patient_pk, study_date, study_time, study_description, institution_name,
                            modality, bodypart, 0, 0, study_path)
    return study_pk


def get_or_create_series(file, study_pk, itk_image, main_thumbnail, series_path):
    meta_dicom = _safe_dcmread(file, stop_before_pixels=True)
    series_uid = str(meta_dicom.get("SeriesInstanceUID", "N/A"))
    series_pk = find_series_pk(series_uid)

    series_name = Path(file).parent.name
    series_number = str(meta_dicom.get("SeriesNumber", "N/A"))
    thk = str(meta_dicom.get("SliceThickness", "N/A"))
    series_description = meta_dicom.get("SeriesDescription", "N/A")
    orientation = determine_orientation(itk_image)
    modality = meta_dicom.get('Modality', 'N/A')

    if series_pk:
        update_series_missing_fields(
            series_pk,
            series_uid=series_uid,
            series_name=series_name,
            series_number=series_number,
            series_thk=thk,
            series_description=series_description if isinstance(series_description, str) else str(series_description),
            orientation=orientation,
            modality=modality,
            main_thumbnail=bool(main_thumbnail),
            series_path=str(series_path),
        )
        return series_pk

    return insert_series(series_uid=series_uid, study_fk=study_pk, series_name=series_name, series_number=series_number,
                         series_thk=thk, series_description=series_description, orientation=orientation,
                         modality=modality, main_thumbnail=main_thumbnail, thumbnail_path=None,
                         series_path=str(series_path))


def get_quickly_series_info(path):
    """This method used for add thumbnails when we haven't read series (Import series)"""
    try:
        p = Path(path)
        exts = {'.dcm', '.dicom'}
        f = next(p.iterdir()) if p.is_dir() else p

        if p.is_dir():
            found = False
            for d in p.iterdir():
                if d.is_dir():
                    try:
                        first = next(d.iterdir())
                    except StopIteration:
                        continue
                    if first.is_file() and first.suffix.lower() in exts:
                        f = first
                        found = True
                        break
                elif d.is_file() and d.suffix.lower() in exts:
                    f = d
                    found = True
                    break
            if not found:
                return None

        if f.is_file() and f.suffix.lower() not in exts:
            return None

        meta_dicom = _safe_dcmread(str(f), stop_before_pixels=True)
        if meta_dicom is None:
            return None

        series_name = p.name if p.is_dir() else p.parent.name
        series_number = str(meta_dicom.get("SeriesNumber", "N/A"))
        series_description = meta_dicom.get("SeriesDescription", "N/A")
        modality = meta_dicom.get('Modality', 'N/A')
        study_uid = str(meta_dicom.get("StudyInstanceUID", "N/A"))

        image_count = 0
        try:
            series_folder = p if p.is_dir() else p.parent
            image_count = len([f for f in series_folder.glob('*.dcm') if f.is_file()])
        except Exception:
            pass

        return {
            'series_name': series_name,
            'series_number': series_number,
            'series_description': series_description,
            'modality': modality,
            'study_uid': study_uid,
            'image_count': image_count
        }
    except Exception:
        return None


def get_or_create_instance(files, itk_image: sitk.Image, series_pk, group_id):
    """
    OPTIMIZED: Use bulk operations instead of individual queries for each instance
    """
    # Step 1: Collect all SOP UIDs to check which ones already exist
    sop_uids = []
    file_to_sop = {}

    for file in files:
        meta_dicom = _safe_dcmread(file, stop_before_pixels=True)
        sop_uid = str(meta_dicom.get("SOPInstanceUID", "N/A"))
        sop_uids.append(sop_uid)
        file_to_sop[file] = (sop_uid, meta_dicom)

    # Step 2: Bulk check which instances already exist
    from PacsClient.utils.database import find_instances_by_sop_uids
    existing_instances = find_instances_by_sop_uids(sop_uids)
    existing_sop_set = {inst['sop_uid'] for inst in existing_instances} if existing_instances else set()

    # Step 3: Prepare data for bulk insert and update
    instances_to_insert = []
    instances_to_update = []

    direction = itk_image.GetDirection()
    direction_json = json.dumps(list(direction)) if direction else None

    def _to_json(x):
        return json.dumps(list(x)) if x is not None else None

    for file in files:
        sop_uid, meta_dicom = file_to_sop[file]

        # Extract metadata
        instance_number = meta_dicom.get("InstanceNumber", None)
        try:
            instance_number = int(instance_number) if instance_number is not None else None
        except:
            instance_number = None

        rows = meta_dicom.get("Rows", None)
        columns = meta_dicom.get("Columns", None)
        rows = int(rows) if rows is not None else None
        columns = int(columns) if columns is not None else None

        window_center = meta_dicom.get('WindowCenter', None)
        window_width = meta_dicom.get('WindowWidth', None)
        if isinstance(window_center, pydicom.multival.MultiValue):
            window_center = float(window_center[0])
        elif window_center is not None:
            window_center = float(window_center)

        if isinstance(window_width, pydicom.multival.MultiValue):
            window_width = float(window_width[0])
        elif window_width is not None:
            window_width = float(window_width)

        is_rgb = (meta_dicom.get("PhotometricInterpretation", "MONOCHROME2") == "RGB")

        image_position_patient = _to_json(meta_dicom.get('ImagePositionPatient', None))
        image_orientation_patient = _to_json(meta_dicom.get('ImageOrientationPatient', None))
        pixel_spacing = _to_json(meta_dicom.get('PixelSpacing', None))

        # ✅ IMPROVED: Better fallback defaults for medical imaging
        # Use None instead of 8-bit defaults - let viewer auto-calculate from pixel data
        # Old defaults (127.5/255) were causing black images for CT scans
        if window_width is None:
            # Try to determine modality for better defaults
            modality = meta_dicom.get('Modality', None)
            if modality == 'CT':
                window_width = 400  # CT soft tissue
            else:
                window_width = None  # Let viewer auto-calculate
        
        if window_center is None:
            modality = meta_dicom.get('Modality', None)
            if modality == 'CT':
                window_center = 40  # CT soft tissue
            else:
                window_center = None  # Let viewer auto-calculate

        instance_data = {
            'sop_uid': sop_uid,
            'series_fk': series_pk,
            'instance_path': file,
            'instance_number': instance_number,
            'rows': rows,
            'columns': columns,
            'window_width': window_width,
            'window_center': window_center,
            'is_rgb': is_rgb,
            'group_id': group_id,
            'image_position_patient': image_position_patient,
            'image_orientation_patient': image_orientation_patient,
            'pixel_spacing': pixel_spacing,
            'direction': direction_json
        }

        if sop_uid in existing_sop_set:
            instances_to_update.append(instance_data)
        else:
            instances_to_insert.append(instance_data)

    # Step 4: Bulk insert and update
    if instances_to_insert:
        from PacsClient.utils.database import bulk_insert_instances
        bulk_insert_instances(instances_to_insert)

    if instances_to_update:
        from PacsClient.utils.database import bulk_update_instances
        bulk_update_instances(instances_to_update)


def get_meta_fixed(file):
    """
        these are parameters that are fixed on all of slices
    """
    series_name = Path(file).parent.name
    meta_dicom = _safe_dcmread(file, stop_before_pixels=True)

    patient_id = str(meta_dicom.get("PatientID", "N/A"))
    patient_name = str(meta_dicom.get("PatientName", "N/A"))
    patient_birthdate = str(meta_dicom.get("PatientBirthDate", "N/A"))
    patient_sex = str(meta_dicom.get("PatientSex", "N/A"))
    patient_age = str(meta_dicom.get("PatientAge", "N/A"))
    patient_weight = str(meta_dicom.get("PatientWeight", "N/A"))

    # add new patient to patient-table
    # patient_pk = insert_patient(patient_id, patient_name, patient_birthdate, patient_sex, patient_age, patient_weight)
    ##############################################################################################

    study_uid = str(meta_dicom.get("StudyInstanceUID", "N/A"))
    study_date = meta_dicom.get("StudyDate", None)
    if study_date:
        try:
            date_obj = datetime.strptime(study_date, "%Y%m%d")
            study_date = date_obj.strftime("%Y/%m/%d")
        except:
            study_date = str(study_date)
    study_time = str(meta_dicom.get("StudyTime", "N/A"))
    study_description = str(meta_dicom.get("StudyDescription", "N/A"))
    hospital_name = str(meta_dicom.get("InstitutionName", "N/A"))
    institution_name = hospital_name
    modality = meta_dicom.get('Modality', 'N/A')
    bodypart = str(meta_dicom.get("BodyPartExamined", "N/A"))

    # insert_study(study_uid, patient_pk, study_date, study_time, study_description, institution_name, modality,
    #              bodypart, 0, 0)
    ##############################################################################################

    # description
    series_desc = meta_dicom.get("SeriesDescription", "N/A")

    meta_fixed = {
        'series_name': series_name,
        'patient_name': patient_name,
        'patient_id': patient_id,
        'patient_sex': patient_sex,
        'patient_age': patient_age,
        'patient_birthdate': patient_birthdate,
        'patient_weight': patient_weight,
        'hospital_name': hospital_name,
        'institution_name': institution_name,  # Same as hospital_name, but some code expects this field
        'series_desc': series_desc,
        'modality': modality,
        'study_uid': study_uid,
        'study_date': study_date if study_date else "N/A",
        'study_time': study_time,
        'study_description': study_description,
        'bodypart': bodypart,
    }

    return meta_fixed


def get_meta_changeable(file):
    """
        these are parameters that are changeable base on slice
    """
    meta_dicom = _safe_dcmread(file)

    window_center = meta_dicom.get('WindowCenter', 127)
    window_width = meta_dicom.get('WindowWidth', 255)

    if isinstance(window_center, pydicom.multival.MultiValue):
        window_center = float(window_center[0])
    else:
        window_center = float(window_center)

    if isinstance(window_width, pydicom.multival.MultiValue):
        window_width = float(window_width[0])
    else:
        window_width = float(window_width)

    metadata = {'window_center': window_center,
                'window_width': window_width}

    ####################################################
    # series data and convert to right format
    # study_date = meta_dicom.get("StudyDate", "N/A")

    # series time and convert to right format
    series_time = meta_dicom.get("SeriesTime", None)
    if series_time:
        try:
            seconds_in_day = float(series_time) % 86400  # 86400 = 24*60*60
            h, rem = divmod(seconds_in_day, 3600)
            m, s = divmod(rem, 60)
            series_time = f"{int(h):02}:{int(m):02}:{int(s):02}"
        except:
            series_time = str(series_time)

    # # description
    # series_desc = meta_dicom.get("SeriesDescription", "N/A")

    # THK
    thk = str(meta_dicom.get("SliceThickness", "N/A"))
    rows = str(meta_dicom.get("Rows", None))
    columns = str(meta_dicom.get("Columns", None))

    # check image RGB
    is_rgb = meta_dicom.get("PhotometricInterpretation", "MONOCHROME2") == "RGB"
    meta_information = {'study_date': str('study_date'), 'series_time': str(series_time), 'series_thk': thk,
                        'series_size': f'{rows}x{columns}', 'is_rgb': is_rgb,

                        }

    return metadata, meta_information


#         instance_number = int(meta_dicom.get("InstanceNumber", "N/A"))
# def group_images_base_on_size(subfolder, ordering_by_instance_number = True):
#     size_dict = {}
#     dicom_names = sitk.ImageSeriesReader().GetGDCMSeriesFileNames(str(subfolder))
#     for file in dicom_names:
#         # try:
#         meta_dicom = pydicom.dcmread(file, force=True, stop_before_pixels=True)
#         rows = meta_dicom.get("Rows", None)
#         columns = meta_dicom.get("Columns", None)
#         if rows and columns:
#             size = (rows, columns)
#             if size not in size_dict:
#                 size_dict[size] = []
#             size_dict[size].append(file)
#         # except Exception as e:
#         #     print(f"Error reading DICOM file {file}: {e}")
#         #     continue
#     if ordering_by_instance_number:
#         for size in list(size_dict.keys()):
#             size_dict[size].sort(key=lambda t: t[0])
#             size_dict[size] = [f for _, f in size_dict[size]]
#     return size_dict


def group_images_base_on_size(subfolder, ordering_by_instance_number: bool = False):
    from collections import defaultdict
    size_dict = defaultdict(list)
    dicom_names = sitk.ImageSeriesReader().GetGDCMSeriesFileNames(str(subfolder))

    for file in dicom_names:
        # درجا، اگر لازم است فیکس کن
        _maybe_fix_charset_inplace(file)

        # حالا هدر را امن بخوان
        try:
            ds = _safe_dcmread(
                file,
                stop_before_pixels=True,
                specific_tags=['Rows', 'Columns', 'InstanceNumber']
            )
        except Exception:
            continue

        rows = getattr(ds, 'Rows', None)
        cols = getattr(ds, 'Columns', None)
        if not rows or not cols:
            continue

        size = (int(rows), int(cols))
        if ordering_by_instance_number:
            inst = getattr(ds, 'InstanceNumber', None)
            try:
                inst_num = int(inst)
            except Exception:
                inst_num = 10 ** 9
            size_dict[size].append((inst_num, file))
        else:
            size_dict[size].append(file)

    if ordering_by_instance_number:
        for size in list(size_dict.keys()):
            size_dict[size].sort(key=lambda t: t[0])
            size_dict[size] = [f for _, f in size_dict[size]]

    return dict(size_dict)


def get_itk_image_optimized(files):
    """
    بهینه‌سازی شده برای سری‌های بزرگ با استفاده از پردازش موازی
    - بهبود یافته برای handle کردن تصاویر با origin و spacing متفاوت
    """
    try:
        if len(files) == 1:
            return sitk.ReadImage(str(files[0]))

        # Delegate to the stable loader path in image_io, which now handles
        # mixed-size ITK region mismatch deterministically.
        from .image_io import get_itk_image
        return get_itk_image(files)

    except Exception as e:
        print(f"Error in get_itk_image_optimized: {e}")
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames([str(f) for f in files])
        return reader.Execute()


def create_random_string():
    return uuid.uuid4()


def create_attachment_folder(folder_name):
    # file = Path(file)
    # file_name = file.name
    # file_parent_name = file.parent.name
    # folder_path = ATTACHMENT_PATH / str(file_parent_name)

    folder_path = ATTACHMENT_PATH / str(folder_name)

    # if folder attachment hasn't exists, 'll create it.
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    return str(folder_path)


def open_folder(folder_path):
    # if not os.path.isdir(folder_path):
    #     print('2222222222')
    #     return
    # file_path = Path(folder_path)
    # file_parent_name = file_path.parent.name
    # folder_path = ATTACHMENT_PATH / str(file_parent_name)

    folder_path = ATTACHMENT_PATH / str(folder_path)
    if not os.path.isdir(folder_path):
        return

    if platform.system() == "Windows":
        os.startfile(folder_path)
    elif platform.system() == "Darwin":  # macOS
        subprocess.run(["open", folder_path])
    else:  # Linux
        subprocess.run(["xdg-open", folder_path])


def count_subfolders_with_dicom(folder_path: str | Path) -> int:
    """
    تعداد زیرپوشه‌های مستقیمِ folder_path که حداقل یک فایل DICOM (.dcm/.dicom) دارند.
    """
    exts = {'.dcm', '.dicom'}
    root = Path(folder_path)
    if not root.is_dir():
        return 0

    count = 0
    for sub in root.iterdir():
        if sub.is_dir():
            # آیا این زیرپوشه دست‌کم یک فایل با پسوند مجاز دارد؟
            if any(p.is_file() and p.suffix.lower() in exts for p in sub.rglob('*')):
                count += 1
    return count


def list_subfolders_with_dicom(folder_path: str | Path, names_only: bool = True) -> list:
    """
    برمی‌گرداند لیست زیرپوشه‌های مستقیمِ folder_path که دست‌کم یک فایل DICOM (.dcm/.dicom) دارند.
    اگر names_only=True باشد فقط نام پوشه‌ها را می‌دهد؛ در غیر این صورت Path کامل برمی‌گرداند.
    """
    exts = {'.dcm', '.dicom'}
    root = Path(folder_path)
    if not root.is_dir():
        return []

    result: list = []
    for sub in root.iterdir():
        if sub.is_dir():
            # آیا هر جایی داخل این زیرپوشه حداقل یک DICOM وجود دارد؟
            has_dicom = any(p.is_file() and p.suffix.lower() in exts for p in sub.rglob('*'))
            if has_dicom:
                # result.append(sub.name if names_only else sub)
                result.append(sub)

    return result


def last_added_file(root: str | Path) -> Path | None:
    exts = {'.dcm', '.dicom'}

    root = Path(root)
    exts = {e.lower() for e in (exts or [])}
    files = (p for p in root.rglob('*') if p.is_file())
    if exts:
        files = (p for p in files if p.suffix.lower() in exts)
    try:
        return max(files, key=lambda p: p.stat().st_mtime)
    except ValueError:
        return None


def get_count_dicom_files_exist(folder_path) -> int:
    exts = {'.dcm', '.dicom'}
    # print('folder:', folder_path)

    series_info = get_quickly_series_info(folder_path)
    study_uid = series_info['study_uid']
    study_source = SOURCE_PATH / study_uid

    if study_source.exists():
        return sum(1 for p in study_source.rglob('*') if p.is_file() and p.suffix.lower() in exts)


def flip_image_y(img):
    f = vtk.vtkImageFlip()
    f.SetInputData(img)
    f.SetFilteredAxis(1)  # 0=X, 1=Y, 2=Z
    f.Update()
    out = vtk.vtkImageData()
    out.DeepCopy(f.GetOutput())  # مستقل از فیلتر
    return out


def save_image_as_png(vtk_image_data, metadata, metadata_fixed, file):
    vtk_image_data = flip_image_y(vtk_image_data)

    study_uid = metadata_fixed['study_uid']
    series_pk = metadata['series']['series_pk']

    series_number = metadata['series']['series_number']

    thumbnails_dir = THUMBNAIL_PATH / study_uid
    thumbnails_dir.mkdir(parents=True, exist_ok=True)
    file_path = thumbnails_dir / f'{series_number}.png'

    if file_path.exists():
        file_path = str(file_path)

        if get_series_thumbnail_path(series_pk) is None:
            update_series_thumbnail_path(series_pk, file_path)
        return file_path

    file_path = str(file_path)

    def apply_window_level(pixel_array, window_width, window_level):
        """
        Apply window level on numpy array with safe bounds
        """
        # Handle invalid window/level values
        if window_width is None or window_width <= 0:
            # Auto window/level
            window_level = float(np.median(pixel_array))
            window_width = float(np.percentile(pixel_array, 95) - np.percentile(pixel_array, 5))
            if window_width <= 0:
                window_width = float(pixel_array.max() - pixel_array.min())

        if window_level is None:
            window_level = float(np.median(pixel_array))

        lower = window_level - 0.5 - (window_width - 1) / 2
        upper = window_level - 0.5 + (window_width - 1) / 2

        clipped = np.clip(pixel_array, lower, upper)

        # Avoid division by zero
        range_val = upper - lower
        if range_val > 0:
            normalized = ((clipped - lower) / range_val) * 255.0
        else:
            normalized = np.zeros_like(clipped)

        return normalized.astype(np.uint8)

    dims = vtk_image_data.GetDimensions()
    vtk_array = vtk_image_data.GetPointData().GetScalars()
    np_data = numpy_support.vtk_to_numpy(vtk_array)

    is_rgb = metadata['instances'][-1]['is_rgb']
    if is_rgb:
        # Reshape RGB data to (z, y, x, 3)
        np_data = np_data.reshape(dims[2], dims[1], dims[0], 3)
        slice_index = dims[2] // 2  # Select middle slice
        slice_2d = np_data[slice_index, :, :, :].astype(np.uint8)
        wl_slice = slice_2d
    else:

        # reshape to (z, y, x)
        np_data = np_data.reshape(dims[2], dims[1], dims[0])

        slice_index = dims[2] // 2  # select mid slice
        slice_2d = np_data[slice_index, :, :]

        # Get window/level from metadata with fallback
        try:
            # Ensure slice_index is within bounds
            if slice_index < len(metadata['instances']):
                instance_metadata = metadata['instances'][slice_index]
            else:
                # Use first instance if slice_index is out of bounds
                instance_metadata = metadata['instances'][0]

            window_width = instance_metadata.get('window_width')
            window_center = instance_metadata.get('window_center')

            # Validate window/level values
            if window_width is not None:
                window_width = float(window_width)
            if window_center is not None:
                window_center = float(window_center)

        except (IndexError, KeyError, TypeError, ValueError) as e:
            print(f"[WARNING] Could not get window/level from metadata: {e}, using auto window/level")
            window_width = None
            window_center = None

        # set window level (will auto-calculate if None)
        wl_slice = apply_window_level(slice_2d, window_width, window_center)

    # convert to PIL and save
    img = Image.fromarray(wl_slice)
    update_series_thumbnail_path(series_pk, file_path)

    img.save(file_path)
    return file_path


def save_image_as_png_fast_first(vtk_image_data, metadata, metadata_fixed, file):
    """
    بهینه‌سازی شده برای اولین سری - تولید سریع thumbnail
    """
    try:
        series_pk = metadata['series']['series_pk']

        # Try to get study_uid from metadata_fixed first, then from metadata
        study_uid = None
        if metadata_fixed and 'study_uid' in metadata_fixed:
            study_uid = metadata_fixed['study_uid']
        elif 'study' in metadata and 'study_uid' in metadata['study']:
            study_uid = metadata['study']['study_uid']
        else:
            # Extract from file path as fallback
            from pathlib import Path
            study_uid = Path(file).parent.parent.name if file else "unknown"

        thumbnails_dir = THUMBNAIL_PATH / study_uid
        if not thumbnails_dir.exists():
            thumbnails_dir.mkdir(parents=True, exist_ok=True)

        file_path = thumbnails_dir / f"{str(series_pk)}.png"

        if file_path.exists():
            update_series_thumbnail_path(series_pk, file_path)
            return str(file_path)

        def apply_window_level_fast(pixel_array, window_width, window_level):
            """Apply window/level with safe bounds and auto-calculation"""
            # Handle invalid window/level values
            if window_width is None or window_width <= 0:
                # Auto window/level
                window_level = float(np.median(pixel_array))
                window_width = float(np.percentile(pixel_array, 95) - np.percentile(pixel_array, 5))
                if window_width <= 0:
                    window_width = float(pixel_array.max() - pixel_array.min())

            if window_level is None:
                window_level = float(np.median(pixel_array))

            lower = window_level - 0.5 - (window_width - 1) / 2
            upper = window_level - 0.5 + (window_width - 1) / 2

            clipped = np.clip(pixel_array, lower, upper)

            # Avoid division by zero
            range_val = upper - lower
            if range_val > 0:
                normalized = ((clipped - lower) / range_val) * 255.0
            else:
                normalized = np.zeros_like(clipped)

            return normalized.astype(np.uint8)

        dims = vtk_image_data.GetDimensions()
        vtk_array = vtk_image_data.GetPointData().GetScalars()

        np_data = numpy_support.vtk_to_numpy(vtk_array)

        is_rgb = metadata['instances'][-1]['is_rgb']

        if is_rgb:
            np_data = np_data.reshape(dims[2], dims[1], dims[0], 3)
            slice_index = dims[2] // 2
            wl_slice = np_data[slice_index, :, :, :]
        else:
            np_data = np_data.reshape(dims[2], dims[1], dims[0])
            slice_index = dims[2] // 2
            slice_2d = np_data[slice_index, :, :]

            # Get window/level from metadata with fallback
            try:
                # Ensure slice_index is within bounds
                if slice_index < len(metadata['instances']):
                    instance_metadata = metadata['instances'][slice_index]
                else:
                    instance_metadata = metadata['instances'][0]

                window_width = instance_metadata.get('window_width')
                window_center = instance_metadata.get('window_center')

                # Validate window/level values
                if window_width is not None:
                    window_width = float(window_width)
                if window_center is not None:
                    window_center = float(window_center)

            except (IndexError, KeyError, TypeError, ValueError):
                # Use auto window/level
                window_width = None
                window_center = None

            wl_slice = apply_window_level_fast(slice_2d, window_width, window_center)

            # تبدیل سریع به PIL و ذخیره
        img = Image.fromarray(wl_slice)
        update_series_thumbnail_path(series_pk, file_path)

        # ذخیره با کیفیت بهینه برای سرعت
        img.save(file_path, optimize=True)
        return str(file_path)

    except Exception as e:
        print(f"⚠️ Fast thumbnail generation failed: {e}, using standard method")
        # fallback به روش معمولی
        return save_image_as_png(vtk_image_data, metadata, metadata_fixed, file)


def save_thumbnail_with_bytes(study_uid, file_name, thumbnail_bytes, overwrite=True):
    """
    Save thumbnail from bytes data

    Args:
        study_uid: Study UID
        file_name: File name (series number)
        thumbnail_bytes: PNG bytes data
        overwrite: If True, overwrite existing file (default: True for correct window/level)

    Returns:
        Path to saved file
    """
    thumbnails_dir = THUMBNAIL_PATH / study_uid
    thumbnails_dir.mkdir(parents=True, exist_ok=True)

    file_path = thumbnails_dir / f'{file_name}.png'

    # Always overwrite by default to ensure fresh thumbnails with correct window/level
    if not overwrite and file_path.exists():
        return file_path

    file_path_str = str(file_path)
    with open(file_path_str, "wb") as f:
        f.write(thumbnail_bytes)

    return file_path_str


def save_series_json(study_uid, **kwargs):
    file_name = kwargs['series_number']

    thumbnails_dir = THUMBNAIL_PATH / study_uid
    file_path = thumbnails_dir / f'{file_name}.json'
    if file_path.exists():
        return file_path

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(kwargs, f, indent=4, ensure_ascii=False)


# Add a simple cache for study existence checks with TTL and size limits
_study_cache = {}
_thumbnail_cache = {}
_cache_ttl = {}  # Time-to-live for cache entries
_cache_timestamps = {}  # Timestamps for cache entries
MAX_CACHE_SIZE = 1000  # Maximum number of cache entries
CACHE_TTL_SECONDS = 300  # 5 minutes TTL


def get_all_series_thumbnail_from_study_folder(study_uid):
    """
    Optimized thumbnail loading with cache and TTL
    """
    import time

    # Check cache first with TTL
    if study_uid in _thumbnail_cache:
        if is_cache_valid(study_uid):
            print(f"📋 Cache hit for study {study_uid}")
            return _thumbnail_cache[study_uid]
        else:
            # Cache expired, remove it
            remove_from_cache(study_uid)

    # Load from disk
    thumbnails_dir = THUMBNAIL_PATH / study_uid
    thumbnails = get_image_files(thumbnails_dir)

    # Cache the result with timestamp
    cache_thumbnail_data(study_uid, thumbnails)
    return thumbnails


def is_cache_valid(study_uid):
    """
    بررسی اعتبار کش بر اساس TTL
    """
    import time

    if study_uid not in _cache_timestamps:
        return False

    current_time = time.time()
    cache_time = _cache_timestamps[study_uid]

    return (current_time - cache_time) < CACHE_TTL_SECONDS


def cache_thumbnail_data(study_uid, thumbnails):
    """
    ذخیره داده‌های تامب‌نیل در کش با مدیریت اندازه
    """
    import time

    # مدیریت اندازه کش
    if len(_thumbnail_cache) >= MAX_CACHE_SIZE:
        cleanup_old_cache_entries()

    # ذخیره داده‌ها
    _thumbnail_cache[study_uid] = thumbnails
    _cache_timestamps[study_uid] = time.time()

    print(f"💾 Cached thumbnail data for study {study_uid}")


def remove_from_cache(study_uid):
    """
    حذف داده‌ها از کش
    """
    _thumbnail_cache.pop(study_uid, None)
    _cache_timestamps.pop(study_uid, None)
    _study_cache.pop(study_uid, None)
    _cache_ttl.pop(study_uid, None)

    print(f"🗑️ Removed study {study_uid} from cache")


def cleanup_old_cache_entries():
    """
    پاکسازی کش‌های قدیمی
    """
    import time

    current_time = time.time()
    expired_keys = []

    # پیدا کردن کلیدهای منقضی شده
    for study_uid, timestamp in _cache_timestamps.items():
        if (current_time - timestamp) > CACHE_TTL_SECONDS:
            expired_keys.append(study_uid)

    # حذف کلیدهای منقضی شده
    for key in expired_keys:
        remove_from_cache(key)

    # اگر هنوز کش پر است، قدیمی‌ترین‌ها را حذف کن
    if len(_thumbnail_cache) >= MAX_CACHE_SIZE:
        sorted_by_time = sorted(_cache_timestamps.items(), key=lambda x: x[1])
        keys_to_remove = [key for key, _ in sorted_by_time[:MAX_CACHE_SIZE // 2]]

        for key in keys_to_remove:
            remove_from_cache(key)

    print(f"🧹 Cache cleanup completed. Current size: {len(_thumbnail_cache)}")


def get_cache_stats():
    """
    دریافت آمار کش
    """
    import time

    current_time = time.time()
    valid_entries = 0
    expired_entries = 0

    for study_uid, timestamp in _cache_timestamps.items():
        if (current_time - timestamp) < CACHE_TTL_SECONDS:
            valid_entries += 1
        else:
            expired_entries += 1

    return {
        'total_entries': len(_thumbnail_cache),
        'valid_entries': valid_entries,
        'expired_entries': expired_entries,
        'cache_size_mb': estimate_cache_size_mb(),
        'oldest_entry': min(_cache_timestamps.values()) if _cache_timestamps else 0,
        'newest_entry': max(_cache_timestamps.values()) if _cache_timestamps else 0
    }


def estimate_cache_size_mb():
    """
    تخمین اندازه کش به مگابایت
    """
    import sys

    total_size = 0
    for study_uid, thumbnails in _thumbnail_cache.items():
        total_size += sys.getsizeof(thumbnails)
        total_size += sys.getsizeof(study_uid)

    return total_size / (1024 * 1024)  # Convert to MB


def load_json_as_dict(json_path):
    # def load_json_as_dict(study_uid, file_name):
    #     thumbnails_dir = THUMBNAIL_PATH / study_uid
    #     json_path = thumbnails_dir / f'{file_name}.json'

    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data


def clear_study_cache(study_uid=None):
    """
    Clear cache for a specific study or all studies
    """
    global _study_cache, _thumbnail_cache

    if study_uid:
        _study_cache.pop(study_uid, None)
        _thumbnail_cache.pop(study_uid, None)
    else:
        _study_cache.clear()
        _thumbnail_cache.clear()


def check_study_exists(study_uid):
    study_dir = THUMBNAIL_PATH / study_uid
    if study_dir.exists():
        return True
    return False


def get_expected_series_count_from_server(study_uid):
    """
    Get expected series count for a study from server
    
    Args:
        study_uid: Study UID
    
    Returns:
        int: Expected series count, or None if failed
    """
    try:
        from PacsClient.components.socket_client import PatientListSocketClient
        
        client = PatientListSocketClient()
        client.connect()
        
        # Get study info from server
        response = client.send_request("GetStudyInfo", {"study_instance_uid": study_uid})
        
        if response and response.get('status') == 'success':
            data = response.get('data', {})
            # سرور ممکن است count_of_series یا total_series برگرداند
            count_of_series = data.get('count_of_series') or data.get('total_series', 0)
            client.disconnect()
            return count_of_series if count_of_series > 0 else None
        else:
            client.disconnect()
            return None
            
    except Exception as e:
        # Silently fail - this is just for optimization
        return None


def check_study_complete(study_uid, expected_series_count=None):
    """
    Check if study download is complete (FAST - no server calls)
    
    Args:
        study_uid: Study UID
        expected_series_count: Expected number of series. If None, will try to get from LOCAL database.
    
    Returns:
        bool: True if study download is complete
    """
    try:
        from PacsClient.utils.db_manager import get_study_by_study_uid
        from PacsClient.utils.config import SOURCE_PATH
        
        study_path = SOURCE_PATH / study_uid
        
        # Quick check: if folder doesn't exist, not complete
        if not study_path.exists():
            return False
        
        # Count actual series folders
        series_folders = count_subfolders_with_dicom(study_path)
        
        if series_folders == 0:
            return False
        
        # Get expected count from LOCAL database only (no server calls)
        if expected_series_count is None or expected_series_count <= 0:
            study_data = get_study_by_study_uid(study_uid)
            if study_data:
                expected_series_count = study_data.get('number_of_series', 0)
        
        # If we have expected count, compare
        if expected_series_count is not None and expected_series_count > 0:
            return series_folders >= expected_series_count
        
        # No expected count - if has some series, assume complete
        return series_folders > 0

    except Exception:
        return False


def get_study_download_status(study_uid, expected_series_count=None):
    """
    Get detailed download status for a study (FAST - no server calls)
    
    Returns:
        str: 'complete', 'partial', or 'not_downloaded'
    """
    try:
        from PacsClient.utils.db_manager import get_study_by_study_uid
        from PacsClient.utils.config import SOURCE_PATH
        
        study_path = SOURCE_PATH / study_uid
        
        # Quick check: if folder doesn't exist, not downloaded
        if not study_path.exists():
            return 'not_downloaded'
        
        # Count series folders with DICOM files
        series_folders = count_subfolders_with_dicom(study_path)
        
        if series_folders == 0:
            return 'not_downloaded'
        
        # Try to get expected count from LOCAL database only (no server calls)
        if expected_series_count is None or expected_series_count <= 0:
            study_data = get_study_by_study_uid(study_uid)
            if study_data:
                expected_series_count = study_data.get('number_of_series', 0)
        
        # If we have expected count from DB, compare
        if expected_series_count is not None and expected_series_count > 0:
            if series_folders >= expected_series_count:
                return 'complete'
            else:
                return 'partial'
        else:
            # No expected count - if has some series, assume complete
            return 'complete' if series_folders > 0 else 'not_downloaded'
    
    except Exception:
        return 'not_downloaded'


def validate_thumbnail_files(study_uid):
    """
    بررسی سریع اعتبار فایل‌های thumbnail
    """
    # Use the optimized check_study_exists
    if not check_study_exists(study_uid):
        return False, "Study directory not found or no thumbnails"

    return True, "Thumbnails found"


def has_subfolders(folder_path: str | Path) -> bool:
    folder = Path(folder_path)
    # # هرگاه آیتمی که پوشه باشد پیدا شود، تابع any مقدار True را برمی‌گرداند
    # return any(item.is_dir() for item in folder.iterdir())
    return any(folder.iterdir())


def check_folder_has_dicom(folder_path: str | Path) -> bool:
    exts = {'.dcm', '.dicom'}

    """
    اگر پوشهٔ داده‌شده «مستقیماً» فایل DICOM با پسوندهای EXTS داشته باشد → False
    اگر نداشته باشد → True
    توجه: زیرپوشه‌ها بررسی نمی‌شوند.
    """
    if not os.path.isdir(folder_path):
        return False  # ورودی معتبر نیست

    for name in os.listdir(folder_path):
        p = os.path.join(folder_path, name)
        if os.path.isfile(p):
            _, ext = os.path.splitext(name)
            if ext.lower() in exts:
                return True
    return False


def get_study_source_path(study_uid):
    study_source_dir = SOURCE_PATH / study_uid

    if not study_source_dir.exists():
        study_source_dir.mkdir(parents=True, exist_ok=True)

    have_subfolders = any(study_source_dir.iterdir())  # if folder is not empty -> return True
    return study_source_dir, have_subfolders


def check_series_study_exist(study_uid, series_name):
    series_dir = SOURCE_PATH / study_uid / series_name
    if not series_dir.exists():
        series_dir.mkdir(parents=True, exist_ok=True)
    return str(series_dir)


def delete_widgets_in_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()

        # اگر ویجت باشد، آن را حذف کن
        if widget is not None:
            widget.setParent(None)

        # اگر layout باشد، آن را بازگشتی پاک کن
        elif item.layout() is not None:
            delete_layout(item.layout())


def delete_layout(layout):
    """حذف layout و ویجت‌های داخل آن"""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()

        # اگر ویجت باشد، آن را از والد خود جدا کن
        if widget is not None:
            widget.setParent(None)
        # اگر این آیتم یک layout باشد، باز هم به طور بازگشتی تابع را فراخوانی می‌کنیم
        elif item.layout() is not None:
            delete_layout(item.layout())  # حذف زیر layout ها
    # QWidget().setLayout(layout)


def get_image_files(folder_path):
    """
    Optimized image file discovery
    """
    exts = {".png"}
    # Use listdir instead of rglob for better performance
    try:
        files = [p for p in folder_path.iterdir()
                 if p.is_file() and p.suffix.lower() in exts]
        return natsorted(files)
    except Exception:
        return []


# def check_and_get_thumbnails(folder_path):
#     """
#     بررسی وجود تامب‌نیل‌ها و بازگرداندن آنها
#     اگر تامب‌نیل‌ها وجود نداشته باشند، None برمی‌گرداند
#     """
#     folder_path = Path(folder_path)
#     study_uid = folder_path.name
#
#     file = THUMBNAIL_PATH / study_uid
#     if check_study_exists(file):
#         thumbnails = get_image_files(file)
#         print(f"🔍 Found {len(thumbnails) if thumbnails else 0} cached thumbnails for study {study_uid}")
#         return thumbnails
#     else:
#         print(f"⚠️ No thumbnails found for study {study_uid}")
#         return None

def check_and_get_thumbnails(folder_path, study_uid=None):
    if study_uid is None:
        series_info = get_quickly_series_info(folder_path)
        if series_info is None or 'study_uid' not in series_info:
            return []
        study_uid = series_info['study_uid']

    file = THUMBNAIL_PATH / study_uid

    if check_study_exists(file):
        return get_image_files(file)

    return []


def should_trigger_auto_download(study_uid):
    """
    بررسی اینکه آیا باید دانلود خودکار شروع شود
    """
    # بررسی وجود تامب‌نیل‌ها
    thumbnails_exist = check_study_exists(study_uid)

    # بررسی وجود فایل‌های DICOM
    source_dir = get_study_source_path(study_uid)[0]
    dicom_files_exist = os.path.exists(source_dir) and len(os.listdir(source_dir)) > 0

    # اگر تامب‌نیل‌ها وجود نداشته باشند، دانلود خودکار شروع شود
    should_download = not thumbnails_exist

    print(f"🔍 Auto-download check for {study_uid}:")
    print(f"   - Thumbnails exist: {thumbnails_exist}")
    print(f"   - DICOM files exist: {dicom_files_exist}")
    print(f"   - Should trigger download: {should_download}")

    return should_download


def get_name_file_from_path(file_path):
    file_path = Path(file_path)
    # return file_path.name
    return file_path.stem


class DicomTagsActors:
    def __init__(self):
        # image information
        self.im_slice_actor = None
        self.im_study_date_actor = None
        self.im_series_time_actor = None
        self.im_series_name_actor = None
        self.im_series_desc_actor = None

        # patient information
        self.p_name_actor = None
        self.p_id_actor = None
        self.p_age_actor = None
        self.p_sex_actor = None

        # image information
        self.im_series_thk_actor = None
        self.im_series_size_actor = None
        self.im_series_window_level = None
        self.im_scale_zoom_actor = None

        # hospital information
        self.im_hospital_name_actor = None

    def change_actor_text(self, actor, text):
        # v2.2.3.0.7: VTK vtkTextActor.SetInput() unconditionally calls Modified()
        # even when the text string is identical.  On WARP/software-OpenGL this
        # forces VTK to re-rasterize every text actor on every scroll frame —
        # including 6-7 actors whose content never changes while scrolling
        # (study date, series name, slice thickness, size, etc.).
        # Guard: compare the current input string before calling SetInput().
        try:
            if actor.GetInput() == str(text):
                return
        except Exception:
            pass
        actor.SetInput(text)

    def all_actors(self):
        """برگرداندن تمام actorها به‌صورت یک لیست"""
        return [
            self.im_slice_actor,
            self.im_study_date_actor,
            self.im_series_time_actor,
            self.im_series_name_actor,
            self.im_series_desc_actor,

            self.p_name_actor,
            self.p_id_actor,
            self.p_age_actor,
            self.p_sex_actor,

            self.im_series_thk_actor,
            self.im_series_size_actor,
            self.im_series_window_level,
            self.im_scale_zoom_actor,

            self.im_hospital_name_actor,
        ]


class BoxManager:
    def __init__(self, box_name: str, box_name_actor: vtk.vtkActor, box_actor: vtk.vtkActor, ijk_points=None,
                 status_abnormal=0, classification_label=''):
        self.box_name = box_name
        self.box_name_actor = box_name_actor
        self.box_actor = box_actor
        self.status_abnormal = status_abnormal
        self.ijk_points = ijk_points
        self.classification_label = classification_label


class TYPES_VIEWER:
    your_viewer = 'Segmented View'
    fixed_viewer = 'Original View'


def show_message(text_message, title="AI Analyze"):
    # Create a message box to show error message
    msg = QMessageBox()
    # msg.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
    # msg.setIcon(QMessageBox.Critical)
    msg.setWindowTitle(title)
    msg.setText(text_message)
    msg.exec()


class VerticalButton_b(QPushButton):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.save()
        painter.translate(self.width(), 0)
        painter.rotate(90)
        painter.drawText(0, 0, self.height(), self.width(),
                         Qt.AlignmentFlag.AlignCenter, self.text())
        painter.restore()


class VerticalButton(QPushButton):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pad = 12  # پدینگ عمودی (بعد از چرخش متن عمودی)
        # اجازه بده اندازه‌اش با فضا تطبیق بدهد:
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        # برای جلوگیری از فشردگی بیش از حد یک حداقل ارتفاع معقول بگذار:
        self.setMinimumHeight(40)

    def sizeHint(self):
        fm = self.fontMetrics()
        # متنِ افقی قبل از چرخش: طولش معادل ارتفاع لازم پس از چرخش است
        h_needed = fm.horizontalAdvance(self.text()) + 2 * self._pad
        # عرض دکمه همان عرض ویجت (ستونی) است؛ یک مقدار پیش‌فرض می‌دهیم
        w_default = 40
        return QSize(w_default, h_needed)

    def minimumSizeHint(self):
        # حداقل ارتفاع بر اساس کوتاه‌ترین متن (یا آستانه)
        fm = self.fontMetrics()
        h_min = max(fm.height() + 2 * self._pad, 40)
        return QSize(24, h_min)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # # پس‌زمینه/استایل پیش‌فرض Qt را هم اعمال کن (اختیاری):
        # # اگر با stylesheet کار می‌کنی، می‌توانی این بخش را حذف کنی:
        # opt = QStyleOptionButton()
        # opt.initFrom(self)
        # opt.text = ""  # متن را خودمان می‌کشیم
        # self.style().drawControl(QStyle.CE_PushButton, opt, painter, self)

        # مساحت قابل‌نقاشی برای متن
        rect = self.rect()

        # متن را ۹۰ درجه بچرخان
        painter.save()
        painter.translate(rect.width(), 0)
        painter.rotate(90)

        # حالا فضای در دسترس برای متن: عرض = ارتفاع ویجت، ارتفاع = عرض ویجت
        avail_w = rect.height()
        avail_h = rect.width()

        # اگر متن جا نشد، elide کن تا تداخل پیش نیاید
        fm = painter.fontMetrics()
        text_to_draw = fm.elidedText(self.text(), Qt.TextElideMode.ElideRight, avail_w - 2 * self._pad)

        painter.drawText(
            self._pad, 0,
            avail_w - 2 * self._pad, avail_h,
            Qt.AlignmentFlag.AlignCenter,
            text_to_draw
        )
        painter.restore()


def count_study_series_instances(folder_study: str) -> tuple[int, int]:
    """
    خروجی: (series_count, instance_count)
    - اگر pydicom موجود باشد، سری‌ها بر اساس SeriesInstanceUID شمرده می‌شوند (دقیق).
    - در صورت نبود pydicom، هر پوشهٔ حاوی DICOM یک سری فرض می‌شود (ساده).
    """
    EXTS = {'.dcm', '.dicom'}

    if not os.path.isdir(folder_study):
        return 0, 0

    # تلاش برای دقت بیشتر با pydicom
    try:
        use_pydicom = True
    except Exception:
        use_pydicom = False

    series_ids = set()
    instance_count = 0

    for root, _, files in os.walk(folder_study):
        # اگر pydicom نداریم، فقط چک کنیم آیا این فولدر DICOM دارد یا نه
        if not use_pydicom:
            has_dicom_here = False

        for name in files:
            _, ext = os.path.splitext(name)
            if ext.lower() not in EXTS:
                continue

            instance_count += 1
            fpath = os.path.join(root, name)

            if use_pydicom:
                # خواندن سبک‌وزن بدون پیکسل‌ها
                try:
                    ds = _safe_dcmread(fpath, stop_before_pixels=True, specific_tags=['SeriesInstanceUID'])
                    sid = getattr(ds, 'SeriesInstanceUID', None)
                    if sid:
                        series_ids.add(str(sid))
                    else:
                        # اگر سری UID نبود، fallback: مسیر پوشه را سری در نظر بگیر
                        series_ids.add(root)
                except Exception:
                    # در صورت خطا در خواندن، fallback
                    series_ids.add(root)
            else:
                has_dicom_here = True

        if not use_pydicom and has_dicom_here:
            # هر پوشهٔ دارای DICOM را یک سری در نظر بگیر
            series_ids.add(root)

    return len(series_ids), instance_count


def find_series_folder_by_series_number(
    study_path: Union[str, Path],
    target_series_number: Union[int, str],
    *,
    return_full_path: bool = False,
) -> Optional[str]:
    """
    بین پوشه‌های داخل study_path جستجو می‌کند. از هر پوشه اولین فایل DICOM را می‌خوانَد
    و اگر SeriesNumber آن با series_number هدف یکی بود، اسم همان پوشه را برمی‌گرداند.

    پارامترها
    ----------
    study_path : str | Path
        مسیر پوشه‌ی مطالعه (شامل زیرپوشه‌های سری).
    target_series_number : int | str
        شماره‌ی سری هدف برای تطبیق با DICOM metadata (Tag: (0020,0011) SeriesNumber).
    return_full_path : bool
        اگر True باشد، به‌جای اسم پوشه، مسیر کامل پوشه را برمی‌گرداند.

    خروجی
    -----
    str | None
        اسم پوشه‌ی سری (یا مسیر کامل در صورت return_full_path=True)؛ اگر پیدا نشد None.
    """
    def _to_int(x) -> Optional[int]:
        try:
            # بعضی سیستم‌ها SeriesNumber را به صورت رشته/float می‌نویسند
            return int(str(x).strip().split('.')[0])
        except Exception:
            return None

    target = _to_int(target_series_number)
    if target is None:
        return None

    study_dir = Path(study_path)
    if not study_dir.exists() or not study_dir.is_dir():
        return None

    # فقط پوشه‌ها: هر پوشه را یک سری در نظر می‌گیریم
    for series_dir in sorted([d for d in study_dir.iterdir() if d.is_dir()]):
        # یک فایل کاندید برای DICOM پیدا کن (اولویت .dcm؛ در غیر اینصورت هر فایلی را امتحان می‌کنیم)
        files = sorted(series_dir.iterdir())
        if not files:
            continue

        candidate = None
        # اول دنبال پسوندهای رایج
        for f in files:
            if f.is_file() and f.suffix.lower() in {".dcm", ".dicom"}:
                candidate = f
                break
        # اگر نبود، هر فایلی را امتحان کن
        if candidate is None:
            for f in files:
                if f.is_file():
                    candidate = f
                    break

        if candidate is None:
            continue

        # سریع و ایمن بخوان (بدون پیکسل‌ها)
        try:
            ds = pydicom.dcmread(str(candidate), stop_before_pixels=True, force=True)
        except Exception:
            # ممکنه فایل DICOM نباشه؛ بریم پوشه بعدی
            continue

        # SeriesNumber را استخراج و نرمال کنیم
        sn = None
        if hasattr(ds, "SeriesNumber"):
            sn = _to_int(ds.SeriesNumber)
        else:
            # گاهی در Private tags یا به شکل رشته‌ای ذخیره شده؛ تلاش اضافه:
            sn = _to_int(ds.get((0x0020, 0x0011), None))

        if sn is not None and sn == target:
            return str(series_dir if return_full_path else series_dir.name)

    return None
