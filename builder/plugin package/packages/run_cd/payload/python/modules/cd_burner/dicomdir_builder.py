"""
DICOMDIR Builder Module
Creates standard DICOMDIR files from DICOM images using pydicom
"""

import os
import warnings
import shutil
import re
from pathlib import Path
from typing import List, Optional, Callable
import logging

try:
    from pydicom import dcmread
    from pydicom.fileset import FileSet
    from pydicom.uid import generate_uid
    PYDICOM_AVAILABLE = True
except ImportError:
    PYDICOM_AVAILABLE = False
    print("⚠ pydicom not available - DICOMDIR creation will be limited")

logger = logging.getLogger(__name__)


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
            for patient_key, patient_data in hierarchy.items():
                for study_uid, series_dict in patient_data['studies'].items():
                    for series_uid, series_data in series_dict.items():
                        for file_info in series_data['files']:
                            try:
                                ds = dcmread(str(file_info['path']))
                                fs.add(ds)
                                expected_sop_instance_uids.add(str(ds.SOPInstanceUID))
                            except Exception as e:
                                logger.warning(f"Could not add file to FileSet: {e}")
            
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
    
    def build_simple(self, dicom_folder: str, output_folder: str) -> bool:
        """
        Simple DICOMDIR creation from a single folder
        
        Args:
            dicom_folder: Path to folder containing DICOM files
            output_folder: Path where DICOMDIR will be created
        
        Returns:
            True if successful, False otherwise
        """
        return self.build_from_study_folders([dicom_folder], output_folder, copy_files=True)

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
    
    def _sanitize_name(self, name: str, max_length: int = 8) -> str:
        """Sanitize a name for file system compatibility (8.3 format)"""
        # Remove invalid characters
        sanitized = re.sub(r'[<>:"/\\|?*\s]', '_', name)
        # Truncate to max length
        return sanitized[:max_length].upper()
    
    def _sanitize_folder_name(self, name: str, max_length: int = 64) -> str:
        """Sanitize a folder name for file system compatibility"""
        # Remove invalid characters for Windows/Linux
        sanitized = re.sub(r'[<>:"/\\|?*]', '_', name)
        # Replace multiple underscores/spaces with single underscore
        sanitized = re.sub(r'[\s_]+', '_', sanitized)
        # Remove leading/trailing underscores
        sanitized = sanitized.strip('_')
        # Truncate to max length
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length]
        return sanitized if sanitized else 'UNKNOWN'
    
    def create_folder_structure(
        self,
        studies_data: List[dict],
        output_folder: str,
        light_viewer_path: Optional[str] = None
    ) -> bool:
        """
        Create complete CD folder structure without burning
        
        Args:
            studies_data: List of study information dicts with paths
            output_folder: Destination folder path
            light_viewer_path: Optional path to light viewer executable
        
        Returns:
            True if successful
        """
        try:
            output_path = Path(output_folder)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Collect study folders from studies_data
            study_folders = []
            for study in studies_data:
                study_path = study.get('study_path') or study.get('path')
                if study_path and Path(study_path).exists():
                    study_folders.append(study_path)
            
            if not study_folders:
                logger.error("No valid study folders found")
                return False
            
            # Build DICOMDIR
            success = self.build_from_study_folders(study_folders, output_folder)
            
            if not success:
                return False
            
            # Copy light viewer if provided
            if light_viewer_path and Path(light_viewer_path).exists():
                self._copy_light_viewer(light_viewer_path, output_folder)
            
            return True
            
        except Exception as e:
            logger.error(f"Error creating folder structure: {e}")
            return False
    
    def _copy_light_viewer(self, viewer_path: str, output_folder: str):
        """Copy light viewer to output folder root (next to DICOMDIR) with autorun.inf"""
        try:
            output_path = Path(output_folder)
            viewer_path_obj = Path(viewer_path)
            
            # Copy the viewer executable directly to root (next to DICOMDIR)
            dest_path = output_path / viewer_path_obj.name
            shutil.copy2(viewer_path, dest_path)
            
            # Copy any DLLs or dependencies in the same folder to root
            viewer_dir = viewer_path_obj.parent
            for item in viewer_dir.iterdir():
                if item.is_file() and item.suffix.lower() in ['.dll', '.ini', '.cfg', '.dat', '.xml']:
                    shutil.copy2(item, output_path / item.name)
            
            # Create autorun.inf
            autorun_content = f"""[autorun]
open={viewer_path_obj.name}
icon={viewer_path_obj.name},0
label=DICOM Viewer
action=Open DICOM Viewer

[Content]
MusicFiles=false
PictureFiles=false
VideoFiles=false
"""
            autorun_path = output_path / "autorun.inf"
            autorun_path.write_text(autorun_content, encoding='utf-8')
            
            logger.info(f"Light viewer copied to: {dest_path}")
            
        except Exception as e:
            logger.warning(f"Could not copy light viewer: {e}")


def check_pydicom_available() -> bool:
    """Check if pydicom is available for DICOMDIR creation"""
    return PYDICOM_AVAILABLE
