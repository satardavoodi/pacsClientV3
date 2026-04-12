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
import json
from pathlib import Path
from typing import List, Optional, Dict, Callable, Any
from PySide6.QtCore import QObject, Signal, QThread

from .dicomdir_builder import DicomDirBuilder, check_pydicom_available
from pydicom import dcmread
from .cd_writer import (
    CDBurner,
    get_available_drives,
    check_imapi2_available,
    normalize_fileset_label,
    normalize_volume_label,
)

logger = logging.getLogger(__name__)


def inspect_viewer_portability(viewer_path: Optional[str]) -> Dict[str, Any]:
    """Inspect a configured viewer path for cross-PC portability risks."""
    result: Dict[str, Any] = {
        "ok": True,
        "severity": "info",
        "warnings": [],
        "details": [],
        "bundle_mode": "none",
    }

    if not viewer_path:
        result["details"].append("No viewer configured")
        return result

    path = Path(viewer_path)
    if not path.exists():
        result["ok"] = False
        result["severity"] = "error"
        result["warnings"].append("Configured viewer file does not exist")
        return result

    if path.suffix.lower() != ".exe":
        result["ok"] = False
        result["severity"] = "error"
        result["warnings"].append("Configured viewer is not a Windows executable (.exe)")
        return result

    name_lower = path.name.lower()
    suspicious_tokens = ("setup", "install", "updater", "update", "bootstrap", "msi")
    if any(token in name_lower for token in suspicious_tokens):
        result["warnings"].append(
            "Viewer executable name looks like an installer/updater rather than a portable viewer"
        )

    parent = path.parent
    sibling_exes = [p for p in parent.glob("*.exe") if p.is_file()]
    dependency_files = []
    dependency_patterns = ("*.dll", "*.json", "*.ini", "*.cfg", "*.xml", "*.pak", "*.dat")
    for pattern in dependency_patterns:
        dependency_files.extend([p for p in parent.glob(pattern) if p.is_file()])
    subdirs = [p for p in parent.iterdir() if p.is_dir()]

    if subdirs or dependency_files:
        result["bundle_mode"] = "portable_bundle"
    else:
        result["bundle_mode"] = "single_exe"
        result["warnings"].append(
            "Viewer looks like a single EXE without nearby portable bundle files; compatibility may depend on the target PC"
        )

    if len(sibling_exes) > 8:
        result["warnings"].append("Viewer folder contains many executables; make sure the selected EXE is the portable launcher")

    result["details"].append(f"Executable: {path.name}")
    result["details"].append(f"Bundle mode: {result['bundle_mode']}")
    result["details"].append(f"Sibling executables: {len(sibling_exes)}")
    result["details"].append(f"Nearby dependency files: {len(dependency_files)}")
    result["details"].append(f"Subfolders copied with viewer: {len(subdirs)}")

    if result["warnings"]:
        result["severity"] = "warning" if result["ok"] else "error"

    return result


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
        cleanup_temp_dir = False
        
        try:
            # Create temp directory for staging
            if not self.output_folder:
                temp_dir = tempfile.mkdtemp(prefix="pacs_cd_burn_")
                staging_folder = temp_dir
            else:
                staging_folder = self.output_folder
                Path(staging_folder).mkdir(parents=True, exist_ok=True)

            normalized_label = normalize_fileset_label(self.disc_label)
            volume_label = normalize_volume_label(self.disc_label, default=normalized_label)
            
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
                copy_files=True,
                fileset_id=normalized_label,
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
            else:
                self._write_portable_support_files(staging_folder, normalized_label, volume_label)

            self.progress.emit(56, "Verifying portable media layout...")
            verification = self._verify_staging_output(staging_folder)
            if not verification["ok"]:
                self.completed.emit(
                    False,
                    "Prepared media verification failed:\n\n- " + "\n- ".join(verification["issues"]),
                )
                return

            if verification["warnings"]:
                for warning in verification["warnings"]:
                    logger.warning("Portable media warning: %s", warning)
            
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

                media_info = burner.get_media_info()
                if media_info.get('present'):
                    required_mb = self._calculate_folder_size_mb(staging_folder)
                    free_mb = float(media_info.get('free_mb') or 0)
                    media_type = media_info.get('type', 'Unknown')
                    safety_margin_mb = 16
                    self.progress.emit(
                        58,
                        f"Media detected: {media_type} | Required: {required_mb:.1f} MB | Free: {free_mb:.1f} MB",
                    )
                    if free_mb and required_mb + safety_margin_mb > free_mb:
                        self.completed.emit(
                            False,
                            (
                                f"Not enough free space on media.\n\n"
                                f"Required: {required_mb:.1f} MB\n"
                                f"Free: {free_mb:.1f} MB\n"
                                f"Safety margin: {safety_margin_mb} MB"
                            ),
                        )
                        return
                
                success, message = burner.burn(staging_folder, volume_label)
                
                if success:
                    cleanup_temp_dir = temp_dir is not None
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
            if cleanup_temp_dir and temp_dir:
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as exc:
                    logger.warning(f"Could not clean up temp directory '{temp_dir}': {exc}")

    def _verify_staging_output(self, staging_folder: str) -> Dict[str, Any]:
        """Validate that the prepared media contains the expected portable files."""
        staging_path = Path(staging_folder)
        issues: List[str] = []
        warnings: List[str] = []

        required_files = [
            "DICOMDIR",
            "START_HERE.txt",
            "RUN_VIEWER.cmd",
            "OPEN_DICOM_FOLDER.cmd",
            "AIPACS_MEDIA_INFO.json",
            "autorun.inf",
        ]
        for filename in required_files:
            path = staging_path / filename
            if not path.exists():
                issues.append(f"Missing required export file: {filename}")

        dicomdir_path = staging_path / "DICOMDIR"
        if dicomdir_path.exists() and dicomdir_path.stat().st_size == 0:
            issues.append("DICOMDIR exists but is empty")

        manifest_path = staging_path / "AIPACS_MEDIA_INFO.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as exc:
                issues.append(f"Could not read AIPACS_MEDIA_INFO.json: {exc}")
                manifest = None

            if manifest:
                if manifest.get("dicomdir") != "DICOMDIR":
                    issues.append("Media manifest does not point to the root DICOMDIR")

                viewer_launcher = manifest.get("viewer_launcher")
                if manifest.get("viewer_included"):
                    if not viewer_launcher:
                        issues.append("Manifest says viewer is included but no viewer launcher path is recorded")
                    elif not (staging_path / Path(viewer_launcher)).exists():
                        issues.append(f"Viewer launcher is missing from export: {viewer_launcher}")
                elif (staging_path / "VIEWER").exists():
                    warnings.append("VIEWER folder exists but manifest says no portable viewer is included")

        else:
            manifest = None

        cmd_path = staging_path / "RUN_VIEWER.cmd"
        if cmd_path.exists():
            launch_script = cmd_path.read_text(encoding="utf-8")
            if "No portable viewer was included" not in launch_script and "start \"\"" not in launch_script:
                issues.append("RUN_VIEWER.cmd does not contain a portable viewer launch command")

        return {"ok": not issues, "issues": issues, "warnings": warnings, "manifest": manifest}

    def _coerce_study_path(self, value: Any) -> Optional[str]:
        """Normalize helper return values to a filesystem path string."""
        if value is None:
            return None

        if isinstance(value, (list, tuple)):
            value = value[0] if value else None

        if isinstance(value, Path):
            return str(value)

        if isinstance(value, str):
            return value

        return None

    def _has_dicom_files(self, study_path: str) -> bool:
        path = Path(study_path)
        for suffix in ("*.dcm", "*.dicom"):
            if any(path.rglob(suffix)):
                return True

        for candidate in path.rglob("*"):
            if not candidate.is_file() or candidate.suffix:
                continue

            try:
                dcmread(str(candidate), stop_before_pixels=True)
                return True
            except Exception:
                continue

        return False

    def _calculate_folder_size_mb(self, folder_path: str) -> float:
        total_size = 0
        for item in Path(folder_path).rglob("*"):
            if item.is_file():
                try:
                    total_size += item.stat().st_size
                except OSError:
                    continue

        return total_size / (1024 * 1024)
    
    def _collect_study_folders(self) -> List[str]:
        """Collect paths to downloaded study folders"""
        study_folders = []
        
        for study in self.studies:
            # Try different ways to get the study path
            study_path = None
            study_uid = study.get('study_uid')
            
            # Method 1: Direct path from study data
            if 'study_path' in study and study['study_path']:
                study_path = self._coerce_study_path(study['study_path'])
            
            # Method 2: Use get_study_source_path function
            if not study_path and study_uid:
                try:
                    from PacsClient.pacs.patient_tab.utils import get_study_source_path
                    study_path = self._coerce_study_path(get_study_source_path(study_uid))
                except Exception as e:
                    logger.warning(f"Could not get study path using get_study_source_path: {e}")
            
            # Method 3: Look in default SOURCE_PATH location
            if not study_path and study_uid:
                try:
                    from PacsClient.utils.config import SOURCE_PATH
                    possible_path = SOURCE_PATH / study_uid
                    if possible_path.exists():
                        study_path = self._coerce_study_path(possible_path)
                except Exception as e:
                    logger.warning(f"Could not check SOURCE_PATH: {e}")
            
            if study_path and Path(study_path).exists():
                # Check if there are actual DICOM files
                if self._has_dicom_files(study_path):
                    study_folders.append(study_path)
                    logger.info(f"Found study folder: {study_path}")
                else:
                    logger.warning(f"No DICOM files in: {study_path}")
            else:
                logger.warning(f"Study path not found for study_uid: {study_uid}")
        
        return study_folders
    
    def _copy_light_viewer(self, staging_folder: str):
        """Copy a portable viewer bundle and create launch helpers."""
        try:
            staging_path = Path(staging_folder)
            viewer_path = Path(self.light_viewer_path)
            viewer_dir = viewer_path.parent
            viewer_bundle_dir = staging_path / "VIEWER"

            if viewer_bundle_dir.exists():
                shutil.rmtree(viewer_bundle_dir, ignore_errors=True)

            ignore_names = shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                "*.log",
                "*.tmp",
                "*.bak",
                "Thumbs.db",
                "desktop.ini",
            )
            shutil.copytree(viewer_dir, viewer_bundle_dir, dirs_exist_ok=True, ignore=ignore_names)
            self.progress.emit(52, f"Copied viewer bundle: {viewer_dir.name}")

            relative_exe = Path("VIEWER") / viewer_path.name
            self._write_portable_support_files(
                staging_folder,
                normalize_fileset_label(self.disc_label),
                normalize_volume_label(self.disc_label, default=normalize_fileset_label(self.disc_label)),
                viewer_launcher_relative_path=relative_exe,
                viewer_display_name=viewer_path.stem,
            )

            self.progress.emit(55, "Light Viewer added successfully")
            
        except Exception as e:
            logger.warning(f"Could not copy light viewer: {e}")
            self.progress.emit(55, f"Warning: Could not add Light Viewer - {e}")
            self._write_portable_support_files(
                staging_folder,
                normalize_fileset_label(self.disc_label),
                normalize_volume_label(self.disc_label, default=normalize_fileset_label(self.disc_label)),
            )

    def _write_portable_support_files(
        self,
        staging_folder: str,
        fileset_label: str,
        volume_label: str,
        viewer_launcher_relative_path: Optional[Path] = None,
        viewer_display_name: Optional[str] = None,
    ):
        """Write helper files that improve portability on other Windows PCs."""
        staging_path = Path(staging_folder)
        viewer_display_name = viewer_display_name or "DICOM Viewer"
        viewer_rel = viewer_launcher_relative_path.as_posix() if viewer_launcher_relative_path else None
        viewer_cmd_rel = viewer_rel.replace("/", "\\") if viewer_rel else None

        launch_cmd = staging_path / "RUN_VIEWER.cmd"
        if viewer_cmd_rel:
            launch_cmd.write_text(
                "@echo off\n"
                "setlocal\n"
                "cd /d %~dp0\n"
                "set \"AIPACS_IMPORT_FOLDER=%~dp0\"\n"
                f"if not exist \"{viewer_cmd_rel}\" (\n"
                "  echo Viewer executable was not found.\n"
                "  pause\n"
                "  exit /b 1\n"
                ")\n"
                f"start \"\" \"%~dp0{viewer_cmd_rel}\" --import-folder \"%~dp0\"\n"
                "exit /b 0\n",
                encoding="utf-8",
            )
        else:
            launch_cmd.write_text(
                "@echo off\n"
                "echo No portable viewer was included on this media.\n"
                "echo Please open the DICOM files with any DICOM viewer and use DICOMDIR if supported.\n"
                "pause\n",
                encoding="utf-8",
            )

        open_images_cmd = staging_path / "OPEN_DICOM_FOLDER.cmd"
        open_images_cmd.write_text(
            "@echo off\n"
            "cd /d %~dp0\n"
            "start \"\" explorer.exe \"%~dp0\"\n",
            encoding="utf-8",
        )

        readme_path = staging_path / "START_HERE.txt"
        readme_lines = [
            "AIPacs DICOM media",
            "==================",
            "",
            f"Volume label: {volume_label}",
            f"DICOM File-set ID: {fileset_label}",
            "",
            "How to use this disc/folder on another Windows PC:",
            "1. Insert the disc or open the copied export folder.",
            "2. If a portable viewer is included, run RUN_VIEWER.cmd.",
            "3. If Windows warns about security, choose Run anyway only if this media is trusted.",
            "4. If the included viewer does not start on that PC, install or use any DICOM viewer and open the DICOMDIR file from the media root.",
            "",
            "Compatibility notes:",
            "- AutoRun is not guaranteed on modern Windows versions, so launch RUN_VIEWER.cmd manually.",
            "- The included viewer should be a portable Windows viewer bundle for best compatibility.",
            "- For the broadest compatibility, keep file names and media label unchanged after export.",
            "",
            "Media contents:",
            "- DICOMDIR at the media root",
            "- Standard DICOM patient/study/series/image files",
            "- OPEN_DICOM_FOLDER.cmd to browse the media root quickly",
        ]
        if viewer_rel:
            readme_lines.extend([
                f"- Portable viewer bundle: {viewer_rel}",
                f"- Launcher: RUN_VIEWER.cmd ({viewer_display_name})",
            ])
        else:
            readme_lines.append("- No portable viewer bundle was included")
        readme_lines.append("")
        readme_path.write_text("\n".join(readme_lines), encoding="utf-8")

        manifest_path = staging_path / "AIPACS_MEDIA_INFO.json"
        manifest = {
            "fileset_id": fileset_label,
            "volume_label": volume_label,
            "viewer_included": bool(viewer_rel),
            "viewer_launcher": viewer_rel,
            "viewer_display_name": viewer_display_name if viewer_rel else None,
            "dicomdir": "DICOMDIR",
            "portable_launchers": ["RUN_VIEWER.cmd", "OPEN_DICOM_FOLDER.cmd"],
            "generated_by": "AIPacs CD Burner",
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        autorun_path = staging_path / "autorun.inf"
        if viewer_cmd_rel:
            autorun_content = (
                "[autorun]\n"
                f"open={viewer_cmd_rel} --import-folder .\n"
                f"shellexecute={viewer_cmd_rel} --import-folder .\n"
                f"icon={viewer_cmd_rel},0\n"
                f"label={volume_label}\n"
                f"action=Open {viewer_display_name}\n\n"
                "[Content]\n"
                "MusicFiles=false\n"
                "PictureFiles=false\n"
                "VideoFiles=false\n"
            )
        else:
            autorun_content = (
                "[autorun]\n"
                "open=OPEN_DICOM_FOLDER.cmd\n"
                "icon=OPEN_DICOM_FOLDER.cmd\n"
                f"label={volume_label}\n"
                "action=Open DICOM media\n\n"
                "[Content]\n"
                "MusicFiles=false\n"
                "PictureFiles=false\n"
                "VideoFiles=false\n"
            )
        autorun_path.write_text(autorun_content, encoding="utf-8")


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

    @staticmethod
    def inspect_viewer_portability(viewer_path: Optional[str]) -> Dict[str, Any]:
        return inspect_viewer_portability(viewer_path)
    
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

            study_path = self.worker._coerce_study_path(study_path) if self.worker else self._coerce_manager_path(study_path)
            
            if study_path and Path(study_path).exists():
                for f in Path(study_path).rglob("*"):
                    if f.is_file():
                        total_size += f.stat().st_size
        
        return total_size // (1024 * 1024)  # Convert to MB

    @staticmethod
    def _coerce_manager_path(value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str):
            return value
        return None
