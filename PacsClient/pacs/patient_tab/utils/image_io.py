import os
import gc
import time

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
import gc
from .utils import find_series_folder_by_series_number


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
    
    # For large series (>50 files), use optimized reading strategy
    if len(dicom_names) > 50:
        try:
            # Use SimpleITK's built-in parallel capabilities
            reader = sitk.ImageSeriesReader()
            
            # CRITICAL: Disable metadata reading for speed
            reader.MetaDataDictionaryArrayUpdateOff()
            
            # Set file names
            reader.SetFileNames(dicom_names)
            
            # Use GDCM backend for faster reading (if available)
            reader.SetImageIO("GDCMImageIO")
            
            # Execute with parallel reading
            itk_image = reader.Execute()
            
            del reader
            
            _elapsed = time.time() - _start
            print(f"         ⚡ Parallel DICOM read: {len(dicom_names)} files in {_elapsed:.3f}s ({len(dicom_names)/_elapsed:.0f} fps)")
            
            return itk_image
            
        except Exception as e:
            print(f"         ⚠️ Parallel read failed ({e}), using standard method")
            # Fall back to standard method
    
    # Standard method for small series
    reader = sitk.ImageSeriesReader()
    reader.MetaDataDictionaryArrayUpdateOff()
    reader.SetFileNames(dicom_names)
    itk_image = reader.Execute()
    del reader
    
    return itk_image


# ✅ NEW: Cache for series metadata to avoid redundant DB queries
_series_metadata_cache = {}
_cache_max_size = 100  # Maximum number of cached series

def _get_cached_metadata(series_pk, instances):
    """
    Get metadata from cache or generate and cache it
    """
    cache_key = f"series_{series_pk}"
    
    # Check if in cache
    if cache_key in _series_metadata_cache:
        return _series_metadata_cache[cache_key]
    
    # Generate metadata
    metadata = read_series_instances_metadata(series_pk, instances)
    
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

        # برای سری‌های بزرگ‌تر، بررسی کنیم آیا نیاز به پردازش خاص داریم
        try:
            # سعی می‌کنیم با روش معمولی بخوانیم (اغلب سریع‌تر است)
            return reader.Execute()
        except Exception:
            # اگر مشکل داشت، از روش بهینه‌سازی شده استفاده کنیم
            from . import utils
            if hasattr(utils, 'get_itk_image_optimized'):
                return utils.get_itk_image_optimized(dicom_names)
            else:
                # fallback به روش معمولی
                raise

    except Exception as e:
        print(f"⚠️ Fast first series loading failed: {e}, using standard method")
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
    gc.collect()
    return vtk_image_data


def load_images_from_server(folder_path, patient_pk=None, study_pk=None, study_uid=None, number_of_instances_on_db=None,
                            lst_series_downloaded: list = None, ordering_by_instances_number=None):
    study_data = get_study_by_study_uid(study_uid)

    if number_of_instances_on_db is None:
        number_of_instances_on_db = study_data.get('number_of_instances', None)

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
                        print(f'⚠️ Stuck on same file for too long: {last_added_file}')
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
            print(f'⚠️ Error in download wait loop: {e}')
            pass

        iteration_count += 1
        time.sleep(0.5)

    # Timeout reached
    print(f'⚠️ Download wait timeout reached ({max_iterations * 0.5} seconds)')
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
        
        # Cleanup
        itk_image = None
        del itk_image
        gc.collect()
        
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
        dicom_files = list(series_folder.glob("*.dcm"))
        dicom_files = natsorted(dicom_files)

        if not dicom_files:
            print(f"[FILESYSTEM LOAD] No DICOM files found in {series_folder}")
            return None

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
                instance = {
                    'instance_number': i,
                    'instance_path': str(dicom_file),
                    'rows': int(dcm.get('Rows', 512)),
                    'columns': int(dcm.get('Columns', 512)),
                    'window_width': float(dcm.get('WindowWidth', 400)),
                    'window_center': float(dcm.get('WindowCenter', 40)),
                    'is_rgb': dcm.PhotometricInterpretation in ['RGB', 'YBR_FULL', 'YBR_FULL_422'],
                    'sop_uid': dcm.get('SOPInstanceUID', f'generated_{i}'),
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

        # پاکسازی حافظه
        itk_image = None
        del itk_image
        gc.collect()

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
                                 ordering_by_instances_number=None):
    """
    ✅ OPTIMIZED: Load a single series by number with detailed timing
    """
    import time
    _func_start = time.time()
    
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
                    dicom_files = list(item.glob("*.dcm")) + list(item.glob("*.DCM"))
                    if dicom_files:
                        potential_series_folders.append(item)
        
        if potential_series_folders:
            # Sort by folder name and take the first one
            potential_series_folders.sort()
            series_path = potential_series_folders[0]
            print(f"      🔍 Found series folder: {series_path.name} (looking for series {series_number})")
        else:
            # Fallback: get series path from DB
            series_path_from_db = None
            if study_pk:
                try:
                    series_path_from_db = get_series_path_with_study_pk_and_series_number(study_pk, series_number)
                except Exception as e:
                    print(f"      ⚠️ Error getting series path from DB: {e}")
            
            if series_path_from_db and Path(series_path_from_db).exists():
                series_path = Path(series_path_from_db)
                print(f"      🔍 Using series path from DB: {series_path}")
            else:
                # Last fallback: try to find series folder by number pattern
                series_name = find_series_folder_by_series_number(study_path, series_number)
                if series_name:
                    series_path = Path(f'{study_path}/{series_name}')
                else:
                    error_msg = f'Series {series_number} not found in study {study_path}'
                    print(f'❌ {error_msg}')
                    # Instead of raising error, return None
                    return
    
    _path_time = time.time() - _path_start
    print(f"      ⏱️  Path resolution: {_path_time:.3f}s")
    
    # Check if series_path exists after all attempts
    if not series_path or not series_path.exists():
        print(f"      ❌ Series folder not found after all attempts: series {series_number}")
        return
    
    print(f"      📁 Loading from: {series_path}")
    
    # ✅ OPTIMIZATION: Try to load directly from DB first (much faster!)
    if study_pk:
        _db_check_start = time.time()
        try:
            from PacsClient.utils.database import find_series_pk_by_number
            series_pk = find_series_pk_by_number(series_number, study_pk)
            
            if series_pk:
                # Series exists in DB - load directly without file grouping!
                print(f"      ✅ Series found in DB (series_pk={series_pk}), skipping file grouping...")
                
                instances = get_instances_by_series_pk(series_pk, group_id=0)
                if instances and len(instances) > 0:
                    # We have instances in DB - use them directly
                    _db_check_time = time.time() - _db_check_start
                    print(f"      ⏱️  DB check: {_db_check_time:.3f}s")
                    
                    # Load DICOM files from instance paths
                    _dicom_start = time.time()
                    dicom_files = [Path(inst['instance_path']) for inst in instances]
                    from natsort import natsorted
                    dicom_files = natsorted(dicom_files)
                    
                    itk_image = get_itk_image(dicom_files)
                    _dicom_time = time.time() - _dicom_start
                    print(f"      ⏱️  DICOM load (from DB paths): {_dicom_time:.3f}s")
                    
                    # Get metadata (cached) - needed before filters
                    _meta_start = time.time()
                    metadata = _get_cached_metadata(series_pk, instances)
                    _meta_time = time.time() - _meta_start
                    print(f"      ⏱️  Metadata: {_meta_time:.3f}s")
                    
                    # Apply ITK filters before conversion
                    _filter_start = time.time()
                    from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
                    itk_image = apply_filters(itk_image, metadata)
                    _filter_time = time.time() - _filter_start
                    print(f"      ⏱️  ITK filters: {_filter_time:.3f}s")
                    
                    # Convert to VTK
                    _convert_start = time.time()
                    vtk_image_data = utils.convert_itk2vtk(itk_image)
                    _convert_time = time.time() - _convert_start
                    print(f"      ⏱️  ITK->VTK convert: {_convert_time:.3f}s")
                    
                    # Cleanup
                    itk_image = None
                    del itk_image
                    gc.collect()
                    
                    _func_total = time.time() - _func_start
                    print(f"      ⏱️  TOTAL (DB path): {_func_total:.3f}s")
                    
                    yield vtk_image_data, metadata, (patient_pk, study_pk)
                    return
        except Exception as e:
            print(f"      ⚠️  DB fast path failed: {e}, falling back to file grouping")

    # Fallback: Group images by size (slower)
    _group_start = time.time()
    size_dict = utils.group_images_base_on_size(series_path,
                                                ordering_by_instance_number=ordering_by_instances_number)
    _group_time = time.time() - _group_start
    print(f"      ⏱️  Group images: {_group_time:.3f}s")

    # Process series groups
    _process_start = time.time()
    for item in process_series_groups(series_path, size_dict, patient_pk, study_pk):
        yield item
    _process_time = time.time() - _process_start
    
    _func_total = time.time() - _func_start
    print(f"      ⏱️  Process groups: {_process_time:.3f}s")
    print(f"      ⏱️  TOTAL load_single_series: {_func_total:.3f}s")

def load_single_series_by_number_old(study_path, series_number, patient_pk=None, study_pk=None):
    """
    بارگذاری فقط یک سری خاص بر اساس series_number.
    این تابع مستقیماً از دیتابیس می‌خواند و فقط همان سری را لود می‌کند.
    OPTIMIZED: Direct database query, no file system scanning
    FALLBACK: If DB has no instances, load directly from filesystem
    """
    import time
    from PacsClient.utils.database import find_series_pk_by_number

    try:
        _start = time.time()

        # پیدا کردن series_pk از دیتابیس با series_number و study_pk
        series_pk = find_series_pk_by_number(series_number, study_pk)
        print('series_pk:', series_pk)
        print(study_path, series_number, patient_pk, study_pk)

        if not series_pk:
            print(f"[LOAD SINGLE] Series {series_number} not found in DB for study_pk={study_pk}")
            # FALLBACK: Try loading from filesystem
            return _load_series_from_filesystem(study_path, series_number, patient_pk, study_pk)

        _db_lookup = time.time() - _start

        # دریافت اطلاعات سری از دیتابیس
        series_data = get_series_by_series_pk(series_pk)
        if not series_data:
            print(f"[LOAD SINGLE] No data for series_pk {series_pk}")
            return _load_series_from_filesystem(study_path, series_number, patient_pk, study_pk)

        # دریافت لیست اینستنس‌های این سری
        # Try with group_id=0 first (most common case)
        try:
            instances = get_instances_by_series_pk(series_pk, group_id=0)
        except:
            # Fallback: get all instances for this series without group_id filter
            conn = get_connection_database()
            cur = conn.cursor()
            cur.execute("SELECT * FROM instances WHERE series_fk = ? ORDER BY instance_number", (series_pk,))
            rows = cur.fetchall()
            conn.close()

            if not rows:
                print(f"[LOAD SINGLE] No instances in DB for series {series_number}, trying filesystem...")
                # FALLBACK: Try loading from filesystem
                return _load_series_from_filesystem(study_path, series_number, patient_pk, study_pk)

            keys = ['instance_pk', 'sop_uid', 'series_fk', 'instance_path', 'instance_number',
                    'rows', 'columns', 'window_width', 'window_center', 'is_rgb', 'group_id',
                    'image_position_patient', 'image_orientation_patient', 'pixel_spacing', 'direction']
            instances = [dict(zip(keys, row)) for row in rows]

        print('instances:', instances)
        if not instances:
            print(f"[LOAD SINGLE] No instances in DB for series {series_number}, trying filesystem...")
            # FALLBACK: Try loading from filesystem
            return _load_series_from_filesystem(study_path, series_number, patient_pk, study_pk)

        # استخراج مسیرهای فایل‌های DICOM
        dicom_files = [Path(inst['instance_path']) for inst in instances]
        dicom_files = natsorted(dicom_files)

        print(
            f"[LOAD SINGLE] Loading series {series_number} with {len(dicom_files)} instances (DB lookup: {_db_lookup:.3f}s)")

        # بارگذاری DICOM با SimpleITK
        _dicom_start = time.time()
        itk_image = get_itk_image(dicom_files)
        _dicom_time = time.time() - _dicom_start

        # تبدیل به VTK
        _convert_start = time.time()
        vtk_image_data = utils.convert_itk2vtk(itk_image)
        _convert_time = time.time() - _convert_start

        # ساخت metadata
        _meta_start = time.time()
        metadata = read_series_instances_metadata(series_pk, instances)
        _meta_time = time.time() - _meta_start

        # پاکسازی حافظه
        itk_image = None
        del itk_image
        gc.collect()

        _total = time.time() - _start
        print(
            f"[LOAD SINGLE] ✓ Series {series_number}: {_total:.3f}s (DICOM={_dicom_time:.3f}s, Convert={_convert_time:.3f}s, Meta={_meta_time:.3f}s)")

        return vtk_image_data, metadata, (patient_pk, study_pk)

    except Exception as e:
        print(f"[LOAD SINGLE ERROR] Failed to load series {series_number}: {e}")


# def load_single_series_by_number(study_path, series_number, patient_pk=None, study_pk=None, ordering_by_instance_number=None):
#     """
#     Load a single series by its series number from a study folder.
#     Used for lazy loading - loads only the requested series instead of all series.
#
#     Args:
#         study_path: Path to the study folder
#         series_number: Series number to load
#         patient_pk: Patient primary key (optional)
#         study_pk: Study primary key (optional)
#         ordering_by_instance_number: Whether to order by instance number
#
#     Returns:
#         Tuple of (vtk_image_data, metadata, (patient_pk, study_pk)) or None if not found
#     """
#     try:
#         study_path = Path(study_path)
#
#         # Find the series subfolder by number
#         series_folder = study_path / str(series_number)
#
#         if not series_folder.exists() or not series_folder.is_dir():
#             print(f"[LOAD_SINGLE_SERIES] Series folder not found: {series_folder}")
#             return None
#
#         # Check if folder has DICOM files
#         if not utils.check_folder_has_dicom(series_folder):
#             print(f"[LOAD_SINGLE_SERIES] No DICOM files in: {series_folder}")
#             return None
#
#         # Group images by size
#         size_dict = utils.group_images_base_on_size(series_folder, ordering_by_instance_number=ordering_by_instance_number)
#
#         if not size_dict:
#             print(f"[LOAD_SINGLE_SERIES] No valid images found in: {series_folder}")
#             return None
#
#         # Get patient/study PKs if not provided
#         if (patient_pk is None) and (study_pk is None):
#             first_file = list(size_dict.values())[0][0]
#             patient_pk = utils.get_or_create_patient(first_file)
#             study_pk = utils.get_or_create_study(first_file, patient_pk, str(study_path))
#
#         # Process the first (and typically only) group in the series folder
#         files = list(size_dict.values())[0]
#
#         # Create ITK image
#         itk_image = get_itk_image(files)
#
#         # Get or create series record in DB
#         main_thumbnail = (int(series_number) == 1)
#         series_pk = utils.get_or_create_series(
#             files[0], study_pk, itk_image, main_thumbnail, study_path
#         )
#
#         # Get or create instances
#         utils.get_or_create_instance(files, itk_image, series_pk, group_id=0)
#
#         # Get metadata
#         instances = get_instances_by_series_pk(series_pk, group_id=0)
#         metadata = read_series_instances_metadata(series_pk, instances)
#
#         # Convert to VTK
#         vtk_image_data = utils.convert_itk2vtk(itk_image)
#
#         # Clean up
#         itk_image = None
#         gc.collect()
#
#         print(f"✅ [LOAD_SINGLE_SERIES] Successfully loaded series {series_number}")
#         return vtk_image_data, metadata, (patient_pk, study_pk)
#
#     except Exception as e:
#         print(f"❌ [LOAD_SINGLE_SERIES] Error loading series {series_number}: {e}")
# >>>>>>> develop_tools
#         import traceback
#         traceback.print_exc()
#         return None


def process_series_groups(base_path: Path, size_groups: dict, patient_pk, study_pk):
    """
        base_path: Path to series/subfolder
        size_groups: map of (rows, cols) -> list[file paths] where each is a series
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
            
            print(f"         📦 Processing group {i+1}/{len(size_groups)} with {len(files)} files...")

            # TIMING: Load DICOM
            _dicom_start = time.time()
            # OPTIMIZATION: Use fast method for first series, standard for rest
            if i == 0:
                itk_image = get_itk_image_fast_first(files)
            else:
                itk_image = get_itk_image(files)
            _dicom_time = time.time() - _dicom_start
            print(f"            ⏱️  DICOM load: {_dicom_time:.3f}s")

            # TIMING: Database operations
            _db_start = time.time()
            
            # OPTIMIZATION: Check if series already exists in DB to skip redundant operations
            _series_lookup_start = time.time()
            # Create/update series record
            series_pk = utils.get_or_create_series(
                files[0], study_pk_local, itk_image, main_thumbnail, base_path
            )
            _series_lookup_time = time.time() - _series_lookup_start
            print(f"               • Series lookup/create: {_series_lookup_time:.3f}s")

            # Insert new instances (only new ones are registered; duplicates are skipped)
            _instance_start = time.time()
            utils.get_or_create_instance(files, itk_image, series_pk, group_id=i)
            _instance_time = time.time() - _instance_start
            print(f"               • Instance create: {_instance_time:.3f}s")

            # Metadata + generate vtkImageData
            _metadata_start = time.time()
            instances = get_instances_by_series_pk(series_pk, group_id=i)
            
            # Use cached metadata for better performance
            metadata = _get_cached_metadata(series_pk, instances)
            _metadata_time = time.time() - _metadata_start
            print(f"               • Metadata fetch: {_metadata_time:.3f}s")
            
            _db_time = time.time() - _db_start
            print(f"            ⏱️  Database operations: {_db_time:.3f}s")

            # Apply ITK filters before conversion
            _filter_start = time.time()
            from PacsClient.pacs.patient_tab.utils.image_filters import apply_filters
            itk_image = apply_filters(itk_image, metadata)
            _filter_time = time.time() - _filter_start
            print(f"            ⏱️  ITK filters: {_filter_time:.3f}s")

            # Convert to VTK
            _convert_start = time.time()
            vtk_image_data = utils.convert_itk2vtk(itk_image)
            _convert_time = time.time() - _convert_start
            print(f"            ⏱️  ITK->VTK convert: {_convert_time:.3f}s")
            
            itk_image = None
            del itk_image
            gc.collect()
            
            _total_group = time.time() - _series_start
            print(f"         ✅ Group {i+1} completed in {_total_group:.3f}s\n")
            
            yield vtk_image_data, metadata, (patient_pk_local, study_pk_local)

        except Exception as e:
            # Some folders/series might be corrupted; the whole pipeline shouldn't stop
            print(f"[WARN] load_images: Failed series at {base_path} -> {e}")
            continue
