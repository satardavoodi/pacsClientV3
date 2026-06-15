"""
DICOMDIR Builder Module
Creates standard DICOMDIR files from DICOM images using pydicom
"""

import warnings
from pathlib import Path
from typing import List, Optional, Callable
import logging

try:
    from pydicom import dcmread
    from pydicom.fileset import FileSet
    PYDICOM_AVAILABLE = True
except ImportError:
    PYDICOM_AVAILABLE = False
    print("⚠ pydicom not available - DICOMDIR creation will be limited")

logger = logging.getLogger(__name__)


# DICOMDIR directory records (pydicom's default record creators) require these
# elements to be PRESENT and NON-EMPTY (pydicom treats an empty Type-1 value
# as "missing"). Server images sometimes omit them, which makes FileSet.add()
# raise and silently drops the instance. We backfill safe, DICOM-valid
# defaults; UIDs and pixel data are never touched. Date/Time fields are filled
# from the image's own alternate date/time elements when available.
# (keyword, default_value)
_DICOMDIR_REQUIRED_FIELDS = (
    ("PatientID", "ANONYMOUS"),
    ("StudyID", "1"),
    ("AccessionNumber", "0"),
    ("Modality", "OT"),
    ("SeriesNumber", "1"),
    ("InstanceNumber", "1"),
)


def _first_value(ds, keywords, default):
    for keyword in keywords:
        value = ds.get(keyword, None)
        if value is not None and str(value).strip():
            return str(value)
    return default


def _is_blank(ds, keyword) -> bool:
    if keyword not in ds:
        return True
    value = ds.get(keyword, None)
    return value is None or str(value).strip() == ""


def _ensure_dicomdir_fields(ds) -> None:
    """Backfill DICOMDIR-required elements that are absent or empty.

    Only fills gaps — existing values (and all UIDs / pixel data) are left
    untouched, so this never alters real clinical content.
    """
    # Date/Time: prefer the image's own alternate date/time elements so the
    # directory record stays meaningful; placeholder only as a last resort.
    if _is_blank(ds, "StudyDate"):
        ds.StudyDate = _first_value(
            ds, ("SeriesDate", "ContentDate", "AcquisitionDate"), "19000101"
        )
    if _is_blank(ds, "StudyTime"):
        ds.StudyTime = _first_value(
            ds, ("SeriesTime", "ContentTime", "AcquisitionTime"), "000000"
        )
    # Patient name is Type-2 in the PATIENT record — empty is allowed, but the
    # element must exist.
    if "PatientName" not in ds:
        ds.PatientName = ""
    for keyword, default in _DICOMDIR_REQUIRED_FIELDS:
        if _is_blank(ds, keyword):
            try:
                setattr(ds, keyword, default)
            except Exception:
                logger.debug("Could not backfill DICOMDIR field %s", keyword)


class DicomDirBuilder:
    """
    Builds standard DICOMDIR structure from DICOM files
    
    The DICOMDIR file is the standard way to index DICOM files on removable media
    like CDs/DVDs. It allows DICOM viewers to quickly find and navigate studies.
    """
    
    def __init__(self):
        self.progress_callback: Optional[Callable[[int, str], None]] = None
    
    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """Set a callback function for progress updates"""
        self.progress_callback = callback
    
    def _report_progress(self, percent: int, message: str):
        """Report progress through callback"""
        if self.progress_callback:
            self.progress_callback(percent, message)
        print(f"[{percent}%] {message}")
    
    def build_from_study_folders(
        self, 
        study_folders: List[str], 
        output_folder: str,
        copy_files: bool = True,
        fileset_id: Optional[str] = None,
    ) -> bool:
        """
        Build DICOMDIR from multiple study folders
        
        Args:
            study_folders: List of paths to study folders containing DICOM files
            output_folder: Path where DICOMDIR and organized files will be created
            copy_files: If True, copies files to output_folder in proper structure
        
        Returns:
            True if successful, False otherwise
        """
        if not PYDICOM_AVAILABLE:
            logger.error("pydicom is not installed. Cannot create DICOMDIR.")
            return False
        
        try:
            self._report_progress(0, "Initializing DICOMDIR creation...")
            
            # Create output folder
            output_path = Path(output_folder)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Collect all DICOM files
            all_dicom_files = []
            for study_folder in study_folders:
                study_path = Path(study_folder)
                if study_path.exists():
                    dicom_files = self._find_dicom_files(study_path)
                    all_dicom_files.extend(dicom_files)
            
            if not all_dicom_files:
                self._report_progress(100, "No DICOM files found")
                logger.warning("No DICOM files found in the specified folders")
                return False
            
            self._report_progress(10, f"Found {len(all_dicom_files)} DICOM files")
            
            # Create FileSet for DICOMDIR
            fs = FileSet()
            if fileset_id:
                fs.ID = fileset_id
            
            # Organize and copy files
            total_files = len(all_dicom_files)
            processed = 0
            
            # Track patient/study/series hierarchy for proper folder structure
            # patient_key -> {'name': str, 'id': str, 'studies': {study_uid -> {series_uid -> [files]}}}
            hierarchy = {}
            
            self._report_progress(15, "Analyzing DICOM files...")
            
            for dcm_path in all_dicom_files:
                try:
                    ds = dcmread(str(dcm_path), stop_before_pixels=True)
                    
                    patient_id = str(getattr(ds, 'PatientID', 'UNKNOWN'))
                    patient_name = str(getattr(ds, 'PatientName', 'UNKNOWN'))
                    study_uid = str(getattr(ds, 'StudyInstanceUID', 'UNKNOWN'))
                    series_uid = str(getattr(ds, 'SeriesInstanceUID', 'UNKNOWN'))
                    series_num = str(getattr(ds, 'SeriesNumber', '1'))
                    instance_num = str(getattr(ds, 'InstanceNumber', processed))
                    
                    # Create patient key
                    patient_key = f"{patient_name}_{patient_id}"
                    
                    # Build hierarchy
                    if patient_key not in hierarchy:
                        hierarchy[patient_key] = {
                            'name': patient_name,
                            'id': patient_id,
                            'studies': {}
                        }
                    if study_uid not in hierarchy[patient_key]['studies']:
                        hierarchy[patient_key]['studies'][study_uid] = {}
                    if series_uid not in hierarchy[patient_key]['studies'][study_uid]:
                        hierarchy[patient_key]['studies'][study_uid][series_uid] = {
                            'series_num': series_num,
                            'files': []
                        }
                    
                    hierarchy[patient_key]['studies'][study_uid][series_uid]['files'].append({
                        'path': dcm_path,
                        'instance': instance_num,
                        'dataset': ds
                    })
                    
                except Exception as e:
                    logger.warning(f"Error reading {dcm_path}: {e}")
                    continue
                
                processed += 1
                if processed % 50 == 0:
                    progress = 15 + int((processed / total_files) * 35)
                    self._report_progress(progress, f"Analyzed {processed}/{total_files} files")
            
            self._report_progress(50, "Adding files to DICOMDIR...")

            # Add all DICOM files to FileSet
            # pydicom's FileSet.write() will create the proper folder structure and DICOMDIR
            expected_sop_instance_uids = set()
            add_failures = []
            for patient_key, patient_data in hierarchy.items():
                for study_uid, series_dict in patient_data['studies'].items():
                    for series_uid, series_data in series_dict.items():
                        for file_info in series_data['files']:
                            try:
                                ds = dcmread(str(file_info['path']))
                                # pydicom's default DICOMDIR record creators require
                                # certain elements (e.g. StudyDate/StudyTime/StudyID/
                                # AccessionNumber for the STUDY record). Server images
                                # sometimes omit them — backfill safe defaults so the
                                # instance is not silently dropped from the disc.
                                _ensure_dicomdir_fields(ds)
                                fs.add(ds)
                                expected_sop_instance_uids.add(str(ds.SOPInstanceUID))
                            except Exception as e:
                                logger.warning(f"Could not add file to FileSet: {e}")
                                add_failures.append((str(file_info['path']), str(e)))

            # A File-set with ZERO instances is a silent failure: it writes a
            # 0-image DICOMDIR that used to "pass" validation (empty == empty)
            # and produced a disc with no images. Fail loudly instead.
            if not expected_sop_instance_uids:
                detail = add_failures[0][1] if add_failures else "no addable DICOM instances"
                logger.error("DICOMDIR build added 0 instances: %s", detail)
                self._report_progress(100, "No DICOM images could be added to DICOMDIR")
                return False
            if add_failures:
                logger.warning(
                    "DICOMDIR: %d of %d instance(s) could not be added",
                    len(add_failures), len(add_failures) + len(expected_sop_instance_uids),
                )

            self._report_progress(75, "Writing DICOMDIR and copying files...")
            
            # Write the FileSet - this creates DICOMDIR and copies files to standard structure
            # pydicom creates: PT000000/ST000000/SE000000/IM000001 format
            # This is the standard DICOMDIR format that all DICOM viewers understand
            # Remove any pre-existing DICOMDIR so pydicom does not try to load it
            # (loading an existing DICOMDIR triggers the deprecated DicomDir class in
            # pydicom v3, which is raised as an exception under -W error environments).
            _existing = output_path / "DICOMDIR"
            if _existing.exists():
                _existing.unlink()

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                fs.write(output_path)

            self._report_progress(90, "Validating generated DICOMDIR...")
            if not self._validate_output_fileset(output_path, expected_sop_instance_uids):
                logger.error("Generated DICOMDIR validation failed")
                return False
            
            logger.info(f"DICOMDIR created with standard folder structure")
            
            self._report_progress(100, "DICOMDIR created successfully")
            logger.info(f"DICOMDIR created at: {output_path / 'DICOMDIR'}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error building DICOMDIR: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _find_dicom_files(self, study_path: Path) -> List[Path]:
        """Return DICOM files under `study_path`.

        Prefer common DICOM suffixes and fall back to extension-less files if no
        matches are found.
        """
        matches = []
        for suffix in ("*.dcm", "*.dicom"):
            matches.extend(study_path.rglob(suffix))

        if matches:
            return matches

        fallback_matches: List[Path] = []
        for candidate in study_path.rglob("*"):
            if not candidate.is_file() or candidate.suffix:
                continue

            try:
                dcmread(str(candidate), stop_before_pixels=True)
                fallback_matches.append(candidate)
            except Exception:
                continue

        return fallback_matches

    def _validate_output_fileset(self, output_path: Path, expected_uids: set[str]) -> bool:
        """Validate that the generated DICOMDIR exists and references all instances."""
        try:
            dicomdir_path = output_path / "DICOMDIR"
            if not dicomdir_path.exists():
                logger.error("DICOMDIR file was not created")
                return False

            # A 0-instance File-set must never validate as success — that is
            # exactly the empty-disc bug (empty expected == empty actual).
            if not expected_uids:
                logger.error("DICOMDIR validation: no instances were added")
                return False

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                validation_fs = FileSet(str(dicomdir_path))
            actual_uids = {str(instance.SOPInstanceUID) for instance in validation_fs}

            if actual_uids != expected_uids:
                missing = len(expected_uids - actual_uids)
                extra = len(actual_uids - expected_uids)
                logger.error(
                    "DICOMDIR validation mismatch: missing=%s extra=%s expected=%s actual=%s",
                    missing,
                    extra,
                    len(expected_uids),
                    len(actual_uids),
                )
                return False

            for instance in validation_fs:
                instance_path = Path(str(instance.path))
                if not instance_path.exists():
                    logger.error("Referenced file missing from generated File-set: %s", instance_path)
                    return False

            return True
        except Exception as exc:
            logger.error(f"Error validating generated File-set: {exc}")
            return False


def check_pydicom_available() -> bool:
    """Check if pydicom is available for DICOMDIR creation"""
    return PYDICOM_AVAILABLE
