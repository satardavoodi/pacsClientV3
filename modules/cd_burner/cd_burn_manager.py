"""
CD Burn Manager
Coordinates the entire CD burning process including:
- Downloading images (if needed)
- Creating DICOMDIR
- Copying Light Viewer
- Burning to CD/DVD
"""

import datetime
import os
import shutil
import tempfile
import logging
import json
from dataclasses import dataclass, field
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
from .dicom_prepare import DicomPreparer, FORMAT_ORIGINAL

logger = logging.getLogger(__name__)

# Disc label values treated as "build the label automatically".
_AUTO_LABEL_VALUES = {"", "auto", "[auto label]", "[auto]", "auto label"}


@dataclass
class BurnOptions:
    """Professional burn options (UI ↔ worker contract).

    Defaults reproduce the legacy behavior exactly, so callers that do not
    pass options keep the original pipeline.
    """

    anonymize: bool = False
    anonymize_seed: int = 1
    include_report: bool = False
    include_images: bool = False        # captured/exported JPEG/PNG files
    include_attachments: bool = False
    dicom_format: str = FORMAT_ORIGINAL
    write_speed_sectors: Optional[int] = None   # None → Auto
    finalize_disc: bool = True
    verify_after_burn: bool = False
    # Imaging-center identity stamped onto the media (manifest + START_HERE;
    # the portable viewer shows it as a header). Center info — included even
    # when patient anonymization is enabled.
    center_name: str = ""
    center_address: str = ""
    center_phone: str = ""

    def wants_extras(self) -> bool:
        return self.include_report or self.include_images or self.include_attachments

    def center_identity(self) -> Optional[Dict[str, str]]:
        if not (self.center_name or self.center_address or self.center_phone):
            return None
        return {
            "name": self.center_name.strip(),
            "address": self.center_address.strip(),
            "phone": self.center_phone.strip(),
        }


def is_auto_label(value: Optional[str]) -> bool:
    return (value or "").strip().lower() in _AUTO_LABEL_VALUES


def build_auto_label(
    patient_name: str = "",
    study_date: str = "",
    anonymized: bool = False,
    seed: int = 1,
) -> str:
    """Auto disc label: patient (or anonym ID) + study date + today."""
    if anonymized:
        subject = f"ANON{int(seed):04d}"
    else:
        # Family-name component only, keeps labels short and useful.
        subject = str(patient_name or "").split("^")[0].strip() or "PATIENT"
    today = datetime.date.today().strftime("%Y%m%d")
    parts = [subject]
    study_date = str(study_date or "").strip()
    if study_date and study_date != today:
        parts.append(study_date)
    parts.append(today)
    return normalize_volume_label(" ".join(parts), default="DICOM")


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
        parent=None,
        viewer_display_name: Optional[str] = None,
        options: Optional[BurnOptions] = None,
    ):
        super().__init__(parent)
        self.studies = studies
        self.light_viewer_path = light_viewer_path
        self.disc_label = disc_label
        self.drive_id = drive_id
        self.output_folder = output_folder
        self.burn_to_disc = burn_to_disc
        self.viewer_display_name = viewer_display_name
        self.options = options or BurnOptions()
        self._cancelled = False
        self._preparer: Optional[DicomPreparer] = None
        self._burner: Optional[CDBurner] = None
    
    def cancel(self):
        """Cancel the operation"""
        self._cancelled = True
        if self._preparer is not None:
            self._preparer.cancel()
        if self._burner is not None:
            self._burner.cancel()

    def _resolve_labels(self, study_folders: List[str]):
        """Resolve (fileset_label, volume_label), honoring auto-label mode."""
        label = self.disc_label
        if is_auto_label(label):
            patient_name, study_date = "", ""
            try:
                for folder in study_folders:
                    for candidate in Path(folder).rglob("*"):
                        if not candidate.is_file():
                            continue
                        try:
                            ds = dcmread(str(candidate), stop_before_pixels=True)
                        except Exception:
                            continue
                        patient_name = str(getattr(ds, "PatientName", "") or "")
                        study_date = str(getattr(ds, "StudyDate", "") or "")
                        raise StopIteration
            except StopIteration:
                pass
            except Exception as exc:
                logger.warning("Auto-label header read failed: %s", exc)
            label = build_auto_label(
                patient_name=patient_name,
                study_date=study_date,
                anonymized=self.options.anonymize,
                seed=self.options.anonymize_seed,
            )
            self.progress.emit(4, f"Auto disc label: {label}")
        normalized_label = normalize_fileset_label(label)
        volume_label = normalize_volume_label(label, default=normalized_label)
        return normalized_label, volume_label

    def _collect_extras(self, staging_folder: str):
        """Optional content: reports / captured images / attachments."""
        opts = self.options
        if not opts.wants_extras():
            return

        if opts.anonymize:
            self.progress.emit(
                57,
                "Reports/images/attachments skipped: anonymization is enabled "
                "(they contain identifying data).",
            )
            return

        from . import content_collectors as collectors

        jobs = []
        if opts.include_report:
            jobs.append(("Reports", collectors.collect_reports))
        if opts.include_images:
            jobs.append(("Captured images", collectors.collect_images))
        if opts.include_attachments:
            jobs.append(("Attachments", collectors.collect_attachments))

        for name, collector in jobs:
            if self._cancelled:
                return
            try:
                result = collector(self.studies, staging_folder)
                if result.count:
                    self.progress.emit(58, f"{name}: {result.count} file(s) added")
                for warning in result.warnings:
                    self.progress.emit(58, f"{name}: {warning}")
                    logger.info("CD extras (%s): %s", name, warning)
            except Exception as exc:
                logger.warning("CD extras collector %s failed: %s", name, exc)
                self.progress.emit(58, f"{name}: failed ({exc})")

    def run(self):
        """Execute the CD burn process"""
        temp_dir = None
        prep_dir = None
        cleanup_temp_dir = False

        try:
            opts = self.options

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
            self.progress.emit(2, "Collecting study information...")

            study_folders = self._collect_study_folders()

            if not study_folders:
                self.completed.emit(False, "No downloaded studies found. Please download the studies first.")
                return

            if self._cancelled:
                self.completed.emit(False, "Operation cancelled")
                return

            normalized_label, volume_label = self._resolve_labels(study_folders)

            # Stage 2: Prepare DICOM (anonymization / format conversion)
            dicom_source_folders = study_folders
            self._preparer = DicomPreparer(
                anonymize=opts.anonymize,
                seed=opts.anonymize_seed,
                dicom_format=opts.dicom_format,
                progress_callback=lambda p, m: self.progress.emit(5 + int(p * 0.23), m),
            )
            if self._preparer.needs_processing:
                self.stage_changed.emit("Preparing DICOM files")
                self.progress.emit(5, "Anonymizing / converting DICOM files...")
                prep_dir = tempfile.mkdtemp(prefix="pacs_cd_prep_")
                prep_result = self._preparer.prepare(study_folders, prep_dir)

                for warning in prep_result.warnings[:20]:
                    self.progress.emit(28, f"Prepare: {warning}")
                    logger.warning("CD prepare: %s", warning)

                if self._cancelled:
                    self.completed.emit(False, "Operation cancelled")
                    return
                if prep_result.total_files == 0:
                    self.completed.emit(
                        False,
                        "DICOM preparation produced no files.\n\n- "
                        + "\n- ".join(prep_result.warnings[:10]),
                    )
                    return
                dicom_source_folders = prep_result.prepared_folders
                summary = f"Prepared {prep_result.total_files} files"
                if prep_result.converted_files:
                    summary += f", converted {prep_result.converted_files}"
                if prep_result.fallback_files:
                    summary += f", kept original syntax for {prep_result.fallback_files}"
                if prep_result.skipped_files:
                    summary += f", excluded {prep_result.skipped_files}"
                self.progress.emit(28, summary)

            # Stage 3: Create DICOMDIR
            self.stage_changed.emit("Creating DICOMDIR")
            self.progress.emit(28, "Creating DICOMDIR structure...")

            dicomdir_builder = DicomDirBuilder()
            dicomdir_builder.set_progress_callback(
                lambda p, m: self.progress.emit(28 + int(p * 0.22), m)
            )

            success = dicomdir_builder.build_from_study_folders(
                dicom_source_folders,
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

            # Stage 4: Copy Light Viewer
            self.stage_changed.emit("Adding Light Viewer")
            self.progress.emit(50, "Adding Light Viewer...")

            if self.light_viewer_path and Path(self.light_viewer_path).exists():
                self._copy_light_viewer(staging_folder)
            else:
                self._write_portable_support_files(staging_folder, normalized_label, volume_label)

            # Stage 5: Optional content (reports / images / attachments)
            if opts.wants_extras():
                self.stage_changed.emit("Adding reports & attachments")
                self.progress.emit(56, "Collecting optional content...")
                self._collect_extras(staging_folder)

            self.progress.emit(60, "Verifying portable media layout...")
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

            # Stage 6: Burn to disc (if requested)
            if self.burn_to_disc:
                self.stage_changed.emit("Burning to disc")
                self.progress.emit(62, "Preparing to burn...")

                if not check_imapi2_available():
                    self.completed.emit(False, "CD burning not available. comtypes library not installed.")
                    return

                burner = CDBurner()
                self._burner = burner
                burn_span = 28 if opts.verify_after_burn else 38
                burner.set_progress_callback(
                    lambda p, m: self.progress.emit(62 + int(p * burn_span / 100), m)
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
                        62,
                        f"Media detected: {media_type} | Required: {required_mb:.1f} MB | Free: {free_mb:.1f} MB",
                    )
                    if free_mb and required_mb + safety_margin_mb > free_mb:
                        self.completed.emit(
                            False,
                            (
                                f"Not enough free space on media.\n\n"
                                f"Required: {required_mb:.1f} MB\n"
                                f"Free: {free_mb:.1f} MB\n"
                                f"Safety margin: {safety_margin_mb} MB\n\n"
                                f"Reduce the selection or use higher-capacity media."
                            ),
                        )
                        return

                success, message = burner.burn(
                    staging_folder,
                    volume_label,
                    eject_after=not opts.verify_after_burn,
                    write_speed_sectors=opts.write_speed_sectors,
                    finalize=opts.finalize_disc,
                )

                if not success:
                    self.completed.emit(False, message)
                    return

                final_message = "CD burned successfully!"

                # Stage 7: Verify written disc (optional)
                if opts.verify_after_burn:
                    self.stage_changed.emit("Verifying disc")
                    self.progress.emit(90, "Verifying written disc...")
                    ok, verify_message, details = burner.verify_disc(
                        staging_folder,
                        progress_callback=lambda p, m: self.progress.emit(90 + int(p * 0.09), m),
                    )
                    try:
                        burner.eject()
                    except Exception:
                        pass
                    if not ok:
                        mismatches = []
                        for key in ("missing", "size_mismatch", "hash_mismatch"):
                            mismatches.extend(details.get(key, [])[:5])
                        detail_text = ("\n\nExamples:\n- " + "\n- ".join(mismatches)) if mismatches else ""
                        self.completed.emit(False, f"Burn finished but {verify_message}{detail_text}")
                        return
                    final_message = f"CD burned and verified successfully!\n{verify_message}"

                cleanup_temp_dir = temp_dir is not None
                self.progress.emit(100, final_message)
                self.completed.emit(True, final_message)
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
            # Prepared (anonymized/converted) intermediates are always removed.
            if prep_dir:
                shutil.rmtree(prep_dir, ignore_errors=True)
            # Clean up temp staging only after a successful burn.
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

        # Viewer-bundle completeness: a PyInstaller-layout viewer (VIEWER/
        # _internal) must carry its runtime — an incomplete copy means the
        # viewer fails on every other PC (2026-06-07 incident), so the burn
        # must fail loudly here instead.
        viewer_internal = staging_path / "VIEWER" / "_internal"
        if viewer_internal.is_dir():
            critical = (
                "python313.dll",
                "base_library.zip",
                "VCRUNTIME140.dll",
                Path("PySide6") / "plugins" / "platforms" / "qwindows.dll",
            )
            for rel in critical:
                if not (viewer_internal / rel).is_file():
                    issues.append(f"Viewer bundle incomplete on media: _internal\\{rel} missing")

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
        """Copy a portable viewer (bundle or single exe) and create launch helpers."""
        try:
            staging_path = Path(staging_folder)
            viewer_path = Path(self.light_viewer_path)
            viewer_dir = viewer_path.parent
            viewer_bundle_dir = staging_path / "VIEWER"

            if viewer_bundle_dir.exists():
                shutil.rmtree(viewer_bundle_dir, ignore_errors=True)

            # Single bare exe (e.g. user-picked file in Downloads): copy ONLY the
            # exe — copying its whole parent folder would drag unrelated files
            # onto the disc. Portable bundles (exe + DLLs/resources, like the
            # AI-PACS Lite Viewer dist) are copied as a tree.
            analysis = inspect_viewer_portability(str(viewer_path))
            bundle_mode = analysis.get("bundle_mode", "portable_bundle")

            if bundle_mode == "single_exe":
                viewer_bundle_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(viewer_path, viewer_bundle_dir / viewer_path.name)
                self.progress.emit(52, f"Copied viewer executable: {viewer_path.name}")
            else:
                ignore_names = shutil.ignore_patterns(
                    "__pycache__",
                    "*.pyc",
                    "*.pyo",
                    "*.log",
                    "*.tmp",
                    "*.bak",
                    # Never ship junk archives that may sit next to the viewer
                    # exe (e.g. legacy lightViewer.rar) — they bloat every disc.
                    # *.zip MUST NOT be excluded: PyInstaller's runtime lives in
                    # _internal\base_library.zip — excluding it bricks the
                    # viewer on every PC (caught by the staging guard 2026-06-07).
                    "*.rar",
                    "*.7z",
                    "Thumbs.db",
                    "desktop.ini",
                )
                shutil.copytree(viewer_dir, viewer_bundle_dir, dirs_exist_ok=True, ignore=ignore_names)
                self.progress.emit(52, f"Copied viewer bundle: {viewer_dir.name}")

            viewer_display_name = self.viewer_display_name or viewer_path.stem

            relative_exe = Path("VIEWER") / viewer_path.name
            self._write_portable_support_files(
                staging_folder,
                normalize_fileset_label(self.disc_label),
                normalize_volume_label(self.disc_label, default=normalize_fileset_label(self.disc_label)),
                viewer_launcher_relative_path=relative_exe,
                viewer_display_name=viewer_display_name,
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
        center = self.options.center_identity()

        launch_cmd = staging_path / "RUN_VIEWER.cmd"
        if viewer_cmd_rel:
            # The bundled viewer is 64-bit (Qt 6 has no 32-bit build). On a
            # genuine 32-bit Windows PC the exe cannot start, so detect that
            # and degrade gracefully — a clear message + open the DICOM
            # folder so DICOMDIR can be used with any installed viewer —
            # instead of a cryptic "not a valid Win32 application" error.
            launch_cmd.write_text(
                "@echo off\n"
                "setlocal\n"
                "cd /d %~dp0\n"
                "set \"AIPACS_IMPORT_FOLDER=%~dp0\"\n"
                "if /I \"%PROCESSOR_ARCHITECTURE%\"==\"x86\" if not defined PROCESSOR_ARCHITEW6432 (\n"
                "  echo.\n"
                "  echo The bundled AI-PACS viewer requires 64-bit Windows.\n"
                "  echo This computer is running 32-bit Windows.\n"
                "  echo.\n"
                "  echo Opening the DICOM folder instead. Open the DICOMDIR file\n"
                "  echo with any DICOM viewer to see the images.\n"
                "  echo.\n"
                "  start \"\" explorer.exe \"%~dp0\"\n"
                "  pause\n"
                "  exit /b 0\n"
                ")\n"
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
        ]
        if center:
            if center.get("name"):
                readme_lines.append(f"Created by: {center['name']}")
            if center.get("address"):
                readme_lines.append(f"Address: {center['address']}")
            if center.get("phone"):
                readme_lines.append(f"Phone: {center['phone']}")
            readme_lines.append("")
        readme_lines += [
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
            "- The bundled viewer runs on 64-bit Windows (Windows 7 SP1 through 11).",
            "  On a 32-bit Windows PC, RUN_VIEWER.cmd opens the DICOM folder so you",
            "  can open DICOMDIR with any installed DICOM viewer instead.",
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
        if center:
            manifest["center"] = center  # portable viewer shows this header
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

        autorun_path = staging_path / "autorun.inf"
        if viewer_cmd_rel:
            # AutoRun goes through RUN_VIEWER.cmd (not the exe directly) so the
            # 32-bit-Windows guard + folder fallback runs even on autorun.
            autorun_content = (
                "[autorun]\n"
                "open=RUN_VIEWER.cmd\n"
                "shellexecute=RUN_VIEWER.cmd\n"
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

    def get_write_speeds(self, drive_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Supported write speeds for a drive (empty → UI shows Auto only)."""
        try:
            burner = CDBurner()
            if not burner.select_drive(drive_id):
                return []
            return burner.get_supported_write_speeds()
        except Exception as exc:
            logger.warning("Write speed query failed: %s", exc)
            return []

    def get_media_info(self, drive_id: Optional[str] = None) -> Dict[str, Any]:
        """Inserted media info for a drive (present/type/capacity/free)."""
        try:
            burner = CDBurner()
            if not burner.select_drive(drive_id):
                return {'present': False}
            return burner.get_media_info()
        except Exception as exc:
            logger.warning("Media info query failed: %s", exc)
            return {'present': False}
    
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
        burn_to_disc: bool = True,
        viewer_display_name: Optional[str] = None,
        options: Optional[BurnOptions] = None,
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
            burn_to_disc=burn_to_disc,
            viewer_display_name=viewer_display_name,
            options=options,
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
        disc_label: str = "DICOM_IMAGES",
        viewer_display_name: Optional[str] = None,
        options: Optional[BurnOptions] = None,
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
            burn_to_disc=False,
            viewer_display_name=viewer_display_name,
            options=options,
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
