"""
CD Burn Manager
Coordinates the entire CD burning process including:
- Downloading images (if needed)
- Creating DICOMDIR
- Copying Light Viewer
- Burning to CD/DVD
"""

import os
import shutil
import tempfile
import logging
from pathlib import Path
from typing import List, Optional, Dict, Callable
from PySide6.QtCore import QObject, Signal, QThread

from .dicomdir_builder import DicomDirBuilder, check_pydicom_available
from .cd_writer import CDBurner, get_available_drives, check_imapi2_available

logger = logging.getLogger(__name__)


class CDBurnWorker(QThread):
    """Worker thread for CD burning operations"""
    
    progress = Signal(int, str)  # percent, message
    completed = Signal(bool, str)  # success, message
    stage_changed = Signal(str)  # current stage name
    
    def __init__(
        self,
        studies: List[dict],
        light_viewer_path: Optional[str] = None,
        disc_label: str = "DICOM_IMAGES",
        drive_id: Optional[str] = None,
        output_folder: Optional[str] = None,
        burn_to_disc: bool = True,
        parent=None
    ):
        super().__init__(parent)
        self.studies = studies
        self.light_viewer_path = light_viewer_path
        self.disc_label = disc_label
        self.drive_id = drive_id
        self.output_folder = output_folder
        self.burn_to_disc = burn_to_disc
        self._cancelled = False
    
    def cancel(self):
        """Cancel the operation"""
        self._cancelled = True
    
    def run(self):
        """Execute the CD burn process"""
        temp_dir = None
        
        try:
            # Create temp directory for staging
            if not self.output_folder:
                temp_dir = tempfile.mkdtemp(prefix="pacs_cd_burn_")
                staging_folder = temp_dir
            else:
                staging_folder = self.output_folder
                Path(staging_folder).mkdir(parents=True, exist_ok=True)
            
            self.progress.emit(0, "Starting CD preparation...")
            
            # Stage 1: Collect study paths
            self.stage_changed.emit("Collecting studies")
            self.progress.emit(5, "Collecting study information...")
            
            study_folders = self._collect_study_folders()
            
            if not study_folders:
                self.completed.emit(False, "No downloaded studies found. Please download the studies first.")
                return
            
            if self._cancelled:
                self.completed.emit(False, "Operation cancelled")
                return
            
            # Stage 2: Create DICOMDIR
            self.stage_changed.emit("Creating DICOMDIR")
            self.progress.emit(10, "Creating DICOMDIR structure...")
            
            dicomdir_builder = DicomDirBuilder()
            dicomdir_builder.set_progress_callback(
                lambda p, m: self.progress.emit(10 + int(p * 0.4), m)
            )
            
            success = dicomdir_builder.build_from_study_folders(
                study_folders, 
                staging_folder, 
                copy_files=True
            )
            
            if not success:
                self.completed.emit(False, "Failed to create DICOMDIR. Check if pydicom is installed.")
                return
            
            if self._cancelled:
                self.completed.emit(False, "Operation cancelled")
                return
            
            # Stage 3: Copy Light Viewer
            self.stage_changed.emit("Adding Light Viewer")
            self.progress.emit(50, "Adding Light Viewer...")
            
            if self.light_viewer_path and Path(self.light_viewer_path).exists():
                self._copy_light_viewer(staging_folder)
            
            if self._cancelled:
                self.completed.emit(False, "Operation cancelled")
                return
            
            # Stage 4: Burn to disc (if requested)
            if self.burn_to_disc:
                self.stage_changed.emit("Burning to disc")
                self.progress.emit(60, "Preparing to burn...")
                
                if not check_imapi2_available():
                    self.completed.emit(False, "CD burning not available. comtypes library not installed.")
                    return
                
                burner = CDBurner()
                burner.set_progress_callback(
                    lambda p, m: self.progress.emit(60 + int(p * 0.4), m)
                )
                
                if not burner.select_drive(self.drive_id):
                    self.completed.emit(False, "No CD/DVD drive available")
                    return
                
                success, message = burner.burn(staging_folder, self.disc_label)
                
                if success:
                    self.progress.emit(100, "CD burned successfully!")
                    self.completed.emit(True, "CD burned successfully!")
                else:
                    self.completed.emit(False, message)
            else:
                # Just create the folder structure
                self.progress.emit(100, f"CD folder prepared at: {staging_folder}")
                self.completed.emit(True, f"CD folder prepared successfully at:\n{staging_folder}")
            
        except Exception as e:
            logger.error(f"CD burn error: {e}")
            import traceback
            traceback.print_exc()
            self.completed.emit(False, f"Error: {str(e)}")
        
        finally:
            # Clean up temp directory only if burning was successful and we used temp
            # Keep it if user might want to use the files
            pass
    
    def _collect_study_folders(self) -> List[str]:
        """Collect paths to downloaded study folders"""
        study_folders = []
        
        for study in self.studies:
            # Try different ways to get the study path
            study_path = None
            study_uid = study.get('study_uid')
            
            # Method 1: Direct path from study data
            if 'study_path' in study and study['study_path']:
                study_path = study['study_path']
            
            # Method 2: Use get_study_source_path function
            if not study_path and study_uid:
                try:
                    from PacsClient.pacs.patient_tab.utils import get_study_source_path
                    study_path = get_study_source_path(study_uid)
                except Exception as e:
                    logger.warning(f"Could not get study path using get_study_source_path: {e}")
            
            # Method 3: Look in default SOURCE_PATH location
            if not study_path and study_uid:
                try:
                    from PacsClient.utils.config import SOURCE_PATH
                    possible_path = SOURCE_PATH / study_uid
                    if possible_path.exists():
                        study_path = str(possible_path)
                except Exception as e:
                    logger.warning(f"Could not check SOURCE_PATH: {e}")
            
            if study_path and Path(study_path).exists():
                # Check if there are actual DICOM files
                dcm_files = list(Path(study_path).rglob("*.dcm"))
                if dcm_files:
                    study_folders.append(study_path)
                    logger.info(f"Found study folder: {study_path} ({len(dcm_files)} files)")
                else:
                    logger.warning(f"No DICOM files in: {study_path}")
            else:
                logger.warning(f"Study path not found for study_uid: {study_uid}")
        
        return study_folders
    
    def _copy_light_viewer(self, staging_folder: str):
        """Copy light viewer to staging folder (root level, next to DICOMDIR)"""
        try:
            staging_path = Path(staging_folder)
            viewer_path = Path(self.light_viewer_path)
            
            # Copy the viewer executable directly to root (next to DICOMDIR)
            dest_path = staging_path / viewer_path.name
            shutil.copy2(self.light_viewer_path, dest_path)
            self.progress.emit(52, f"Copied viewer: {viewer_path.name}")
            
            # Copy any DLLs or dependencies in the same folder to root
            viewer_dir = viewer_path.parent
            for item in viewer_dir.iterdir():
                if item.is_file() and item.suffix.lower() in ['.dll', '.ini', '.cfg', '.dat', '.xml']:
                    shutil.copy2(item, staging_path / item.name)
            
            # Create autorun.inf
            autorun_content = f"""[autorun]
open={viewer_path.name}
icon={viewer_path.name},0
label=DICOM Viewer
action=Open DICOM Viewer

[Content]
MusicFiles=false
PictureFiles=false
VideoFiles=false
"""
            autorun_path = staging_path / "autorun.inf"
            autorun_path.write_text(autorun_content, encoding='utf-8')
            
            self.progress.emit(55, "Light Viewer added successfully")
            
        except Exception as e:
            logger.warning(f"Could not copy light viewer: {e}")
            self.progress.emit(55, f"Warning: Could not add Light Viewer - {e}")


class CDBurnManager(QObject):
    """
    Manager class for CD burning operations
    
    Signals:
        progress(int, str): Emits progress percentage and message
        completed(bool, str): Emits completion status and message
        stage_changed(str): Emits when moving to new stage
    """
    
    progress = Signal(int, str)
    completed = Signal(bool, str)
    stage_changed = Signal(str)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker: Optional[CDBurnWorker] = None
    
    def get_available_drives(self) -> List[Dict[str, str]]:
        """Get list of available CD/DVD drives"""
        return get_available_drives()
    
    def is_burning_available(self) -> bool:
        """Check if CD burning is available"""
        return check_imapi2_available() and len(get_available_drives()) > 0
    
    def is_dicomdir_available(self) -> bool:
        """Check if DICOMDIR creation is available"""
        return check_pydicom_available()
    
    def prepare_and_burn(
        self,
        studies: List[dict],
        light_viewer_path: Optional[str] = None,
        disc_label: str = "DICOM_IMAGES",
        drive_id: Optional[str] = None,
        burn_to_disc: bool = True
    ):
        """
        Prepare and burn studies to CD
        
        Args:
            studies: List of study data dictionaries
            light_viewer_path: Path to Light Viewer executable
            disc_label: Label for the disc
            drive_id: ID of the drive to use (None for first available)
            burn_to_disc: If True, burn to disc. If False, just prepare folder
        """
        if self.worker and self.worker.isRunning():
            logger.warning("A burn operation is already in progress")
            return
        
        self.worker = CDBurnWorker(
            studies=studies,
            light_viewer_path=light_viewer_path,
            disc_label=disc_label,
            drive_id=drive_id,
            burn_to_disc=burn_to_disc
        )
        
        # Connect signals
        self.worker.progress.connect(self.progress.emit)
        self.worker.completed.connect(self._on_completed)
        self.worker.stage_changed.connect(self.stage_changed.emit)
        
        # Start the worker
        self.worker.start()
    
    def prepare_folder(
        self,
        studies: List[dict],
        output_folder: str,
        light_viewer_path: Optional[str] = None,
        disc_label: str = "DICOM_IMAGES"
    ):
        """
        Prepare CD folder structure without burning
        
        Args:
            studies: List of study data dictionaries
            output_folder: Path where to create the CD folder structure
            light_viewer_path: Path to Light Viewer executable
            disc_label: Label for the disc (used in DICOMDIR)
        """
        if self.worker and self.worker.isRunning():
            logger.warning("An operation is already in progress")
            return
        
        self.worker = CDBurnWorker(
            studies=studies,
            light_viewer_path=light_viewer_path,
            disc_label=disc_label,
            output_folder=output_folder,
            burn_to_disc=False
        )
        
        # Connect signals
        self.worker.progress.connect(self.progress.emit)
        self.worker.completed.connect(self._on_completed)
        self.worker.stage_changed.connect(self.stage_changed.emit)
        
        # Start the worker
        self.worker.start()
    
    def cancel(self):
        """Cancel the current operation"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
    
    def _on_completed(self, success: bool, message: str):
        """Handle completion"""
        self.worker = None
        self.completed.emit(success, message)
    
    def get_studies_size_estimate(self, studies: List[dict]) -> int:
        """
        Estimate total size of studies in MB
        
        Args:
            studies: List of study data dictionaries
        
        Returns:
            Estimated size in MB
        """
        total_size = 0
        
        for study in studies:
            study_path = study.get('study_path')
            if not study_path:
                if 'study_uid' in study:
                    from PacsClient.utils.config import SOURCE_PATH
                    study_path = str(SOURCE_PATH / study['study_uid'])
            
            if study_path and Path(study_path).exists():
                for f in Path(study_path).rglob("*"):
                    if f.is_file():
                        total_size += f.stat().st_size
        
        return total_size // (1024 * 1024)  # Convert to MB
