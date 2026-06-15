"""
CD/DVD Writer Module
Provides CD/DVD burning functionality using Windows IMAPI2 API
"""

import logging
import re
from pathlib import Path
from typing import List, Optional, Callable, Dict, Tuple
import platform

logger = logging.getLogger(__name__)


def normalize_fileset_label(label: Optional[str], default: str = "DICOM") -> str:
    """Return a DICOM File-set ID safe label.

    DICOM PS3.10 File-set IDs are limited to 16 characters and should use
    uppercase letters, digits and underscore for maximum interoperability.
    """
    value = (label or "").strip().upper()
    value = re.sub(r"[^A-Z0-9_]", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    value = value[:16].strip("_")

    return value or default


def normalize_volume_label(label: Optional[str], default: str = "DICOM") -> str:
    """Return a media volume label safe for broad Windows compatibility."""
    value = (label or "").strip().upper()
    value = re.sub(r"[^A-Z0-9_\- ]", "_", value)
    value = re.sub(r"\s+", " ", value).strip(" _-")
    value = value[:32].strip(" _-")

    return value or default

# Check if we're on Windows and can use IMAPI2
IMAPI2_AVAILABLE = False
if platform.system() == 'Windows':
    try:
        import comtypes
        import comtypes.client
        IMAPI2_AVAILABLE = True
    except ImportError:
        logger.warning("comtypes not installed - CD burning will not be available")
        IMAPI2_AVAILABLE = False


def filesystems_for_media(media_type: Optional[int]) -> int:
    """FileSystemsToCreate for the burn image: ISO9660 + Joliet (= 3), ALWAYS.

    ISO9660-only (= 1) was used for CD media until 2026-06-06 and broke the
    bundled portable viewer on other PCs: IMAPI mangles every non-8.3 name
    to DOS form (``_internal`` → ``_INTER~1``, ``AIPacsLiteViewer.exe`` →
    ``AIPACS~1.EXE``), so the PyInstaller bootloader cannot find its
    ``_internal`` runtime → "Failed to start embedded python interpreter!".
    Reproduced and fix-verified via mounted test ISOs (see
    tools/analysis/oneoff/Make-TestIso.ps1 and the pipeline doc §10).

    The DICOM layout (DICOMDIR + PT000000/ST000000/SE000000/IM000001) is
    8.3-safe by design, so legacy DICOM readers still resolve the ISO9660
    layer correctly while Joliet preserves real names for the viewer.
    """
    return 3


def get_available_drives() -> List[Dict[str, str]]:
    """
    Get list of available CD/DVD drives
    
    Returns:
        List of dicts with 'id', 'name', 'letter' and 'type' keys
    """
    drives = []
    
    # Try IMAPI2 first (most accurate on Windows)
    if IMAPI2_AVAILABLE:
        try:
            import comtypes.client
            
            # Create DiscMaster2 object
            disc_master = comtypes.client.CreateObject("IMAPI2.MsftDiscMaster2")
            
            for i in range(disc_master.Count):
                recorder_id = disc_master.Item(i)
                
                # Create recorder to get info
                recorder = comtypes.client.CreateObject("IMAPI2.MsftDiscRecorder2")
                recorder.InitializeDiscRecorder(recorder_id)
                
                # Get drive info
                vendor = recorder.VendorId or ""
                product = recorder.ProductId or ""
                drive_letter = ""
                
                # Get volume paths (drive letters)
                try:
                    volume_paths = recorder.VolumePathNames
                    if volume_paths:
                        drive_letter = volume_paths[0]
                except:
                    pass
                
                drives.append({
                    'id': recorder_id,
                    'name': f"{vendor} {product}".strip() or f"CD/DVD Drive {i+1}",
                    'letter': drive_letter,
                    'type': 'cd_dvd'
                })
                
        except Exception as e:
            logger.error(f"Error getting CD/DVD drives via IMAPI2: {e}")
    
    # Fallback: Try WMI to detect CD/DVD drives
    if not drives and platform.system() == 'Windows':
        try:
            import subprocess
            # Use WMIC to get CD/DVD drives
            result = subprocess.run(
                ['wmic', 'cdrom', 'get', 'Drive,Name', '/format:csv'],
                capture_output=True, text=True, timeout=10
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines[1:]:  # Skip header
                    parts = line.strip().split(',')
                    if len(parts) >= 3 and parts[1]:  # parts[0] is Node, parts[1] is Drive, parts[2] is Name
                        drive_letter = parts[1]
                        drive_name = parts[2] if len(parts) > 2 else f"CD/DVD Drive"
                        drives.append({
                            'id': drive_letter,
                            'name': drive_name,
                            'letter': drive_letter,
                            'type': 'cd_dvd'
                        })
        except Exception as e:
            logger.warning(f"Error getting drives via WMI: {e}")
    
    # Second fallback: Check common drive letters
    if not drives and platform.system() == 'Windows':
        try:
            import ctypes
            import string
            
            # Get all drive letters
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            
            for i, letter in enumerate(string.ascii_uppercase):
                if bitmask & (1 << i):
                    drive_path = f"{letter}:\\"
                    # Check if it's a CD-ROM drive (type 5)
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                    if drive_type == 5:  # DRIVE_CDROM
                        drives.append({
                            'id': f"{letter}:",
                            'name': f"CD/DVD Drive ({letter}:)",
                            'letter': f"{letter}:",
                            'type': 'cd_dvd'
                        })
        except Exception as e:
            logger.warning(f"Error detecting drives via GetLogicalDrives: {e}")
    
    return drives


class CDBurner:
    """
    CD/DVD burner using Windows IMAPI2
    
    This class provides functionality to burn files and folders to CD/DVD
    using the Windows Image Mastering API version 2 (IMAPI2).
    """
    
    def __init__(self):
        self.progress_callback: Optional[Callable[[int, str], None]] = None
        self.recorder = None
        self.recorder_id = None
        self._cancelled = False
    
    def set_progress_callback(self, callback: Callable[[int, str], None]):
        """Set a callback function for progress updates"""
        self.progress_callback = callback
    
    def _report_progress(self, percent: int, message: str):
        """Report progress through callback"""
        if self.progress_callback:
            self.progress_callback(percent, message)
        print(f"[CD Burn {percent}%] {message}")
    
    def cancel(self):
        """Cancel the current burn operation"""
        self._cancelled = True
    
    def is_available(self) -> bool:
        """Check if CD burning is available on this system"""
        return IMAPI2_AVAILABLE and len(get_available_drives()) > 0
    
    def select_drive(self, drive_id: str = None) -> bool:
        """
        Select a CD/DVD drive for burning
        
        Args:
            drive_id: ID of the drive to use, or None to use first available
        
        Returns:
            True if drive selected successfully
        """
        if not IMAPI2_AVAILABLE:
            logger.error("IMAPI2 not available")
            return False
        
        try:
            import comtypes.client
            
            drives = get_available_drives()
            if not drives:
                logger.error("No CD/DVD drives found")
                return False
            
            # Use specified drive or first available
            if drive_id:
                self.recorder_id = drive_id
            else:
                self.recorder_id = drives[0]['id']
            
            # Create and initialize recorder
            self.recorder = comtypes.client.CreateObject("IMAPI2.MsftDiscRecorder2")
            self.recorder.InitializeDiscRecorder(self.recorder_id)
            
            logger.info(f"Selected drive: {self.recorder_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error selecting drive: {e}")
            return False
    
    def get_supported_write_speeds(self) -> List[Dict[str, object]]:
        """Query the supported write speeds for the current recorder/media.

        Returns a list of {'sectors_per_second': int, 'label': str}, fastest
        first. Empty list when speeds cannot be determined (UI shows 'Auto').
        """
        speeds: List[Dict[str, object]] = []
        if not IMAPI2_AVAILABLE or not self.recorder:
            return speeds
        try:
            import comtypes.client

            disc_format = comtypes.client.CreateObject("IMAPI2.MsftDiscFormat2Data")
            disc_format.Recorder = self.recorder

            try:
                media_type = disc_format.CurrentPhysicalMediaType
            except Exception:
                media_type = 0
            # 1x base in sectors/second by media family
            if media_type in (1, 2, 3):            # CD
                base = 75.0
            elif media_type in (14, 15, 16):       # Blu-ray
                base = 2196.0
            else:                                   # DVD families / unknown
                base = 676.0

            raw = disc_format.SupportedWriteSpeeds
            values = sorted({int(v) for v in raw if int(v) > 0}, reverse=True)
            for sectors in values:
                factor = sectors / base
                mb_s = sectors * 2048 / 1_000_000
                speeds.append({
                    "sectors_per_second": sectors,
                    "label": f"{factor:.0f}x ({mb_s:.1f} MB/s)",
                })
        except Exception as e:
            logger.warning(f"Could not query write speeds: {e}")
        return speeds

    def burn(
        self,
        source_folder: str,
        disc_label: str = "DICOM",
        eject_after: bool = True,
        write_speed_sectors: Optional[int] = None,
        finalize: bool = True,
    ) -> Tuple[bool, str]:
        """
        Burn a folder to CD/DVD

        Args:
            source_folder: Path to folder containing files to burn
            disc_label: Label for the disc (max 32 characters)
            eject_after: Whether to eject the disc after burning
            write_speed_sectors: Requested write speed (sectors/second) or
                None for the drive default ("Auto").
            finalize: Close the disc after writing (no further sessions).

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not IMAPI2_AVAILABLE:
            return False, "CD burning not available - comtypes not installed"
        
        if not self.recorder:
            if not self.select_drive():
                return False, "No CD/DVD drive available"
        
        self._cancelled = False
        
        try:
            import comtypes.client
            
            source_path = Path(source_folder)
            if not source_path.exists():
                return False, f"Source folder does not exist: {source_folder}"

            normalized_label = normalize_fileset_label(disc_label)
            volume_label = normalize_volume_label(disc_label, default=normalized_label)
            
            self._report_progress(0, "Preparing disc...")
            
            # Create disc format object
            disc_format = comtypes.client.CreateObject("IMAPI2.MsftDiscFormat2Data")
            
            # Check if media is present and writable
            if not disc_format.IsRecorderSupported(self.recorder):
                return False, "Recorder not supported for data burning"
            
            disc_format.Recorder = self.recorder
            disc_format.ClientName = "PacsClient CD Burner"
            
            if not disc_format.IsCurrentMediaSupported(self.recorder):
                return False, "Current media not supported. Please insert a blank CD/DVD."
            
            self._report_progress(5, "Creating file system image...")
            
            # Create file system image
            file_system = comtypes.client.CreateObject("IMAPI2FS.MsftFileSystemImage")
            
            # Set file system properties
            file_system.VolumeName = volume_label

            media_type = None
            try:
                media_type = disc_format.CurrentPhysicalMediaType
            except Exception:
                media_type = None

            file_system.FileSystemsToCreate = filesystems_for_media(media_type)
            try:
                disc_format.ForceMediaToBeClosed = bool(finalize)
            except Exception:
                pass

            # Requested write speed (None → drive default / Auto)
            if write_speed_sectors:
                try:
                    disc_format.SetWriteSpeed(int(write_speed_sectors), False)
                    self._report_progress(4, f"Write speed set: {write_speed_sectors} sectors/s")
                except Exception as e:
                    logger.warning(f"Could not set write speed ({e}); using drive default")
            
            # Import existing session if not blank
            try:
                if not disc_format.MediaHeuristicallyBlank:
                    file_system.MultisessionInterfaces = disc_format.MultisessionInterfaces
                    file_system.ImportFileSystem()
            except:
                pass  # Blank disc, nothing to import
            
            self._report_progress(10, "Adding files to image...")
            
            # Add files from source folder
            root = file_system.Root
            
            try:
                root.AddTree(str(source_path), False)
            except Exception as e:
                return False, f"Error adding files: {e}"
            
            if self._cancelled:
                return False, "Operation cancelled by user"
            
            self._report_progress(40, "Creating disc image...")
            
            # Create the result image
            result_image = file_system.CreateResultImage()
            image_stream = result_image.ImageStream
            
            if self._cancelled:
                return False, "Operation cancelled by user"
            
            self._report_progress(50, "Burning to disc...")
            
            # Set up progress event handler
            # Note: IMAPI2 event handling with comtypes is complex
            # For simplicity, we'll use a polling approach or simple progress estimation
            
            try:
                # Perform the burn
                disc_format.Write(image_stream)
                
            except Exception as e:
                error_msg = str(e)
                if "0xC0AA0205" in error_msg:
                    return False, "No disc in drive. Please insert a blank CD/DVD."
                elif "0xC0AA020F" in error_msg:
                    return False, "Disc is not writable. Please insert a blank CD/DVD."
                else:
                    return False, f"Burn failed: {error_msg}"
            
            self._report_progress(95, "Finalizing...")
            
            # Eject if requested
            if eject_after:
                try:
                    self.recorder.EjectMedia()
                    self._report_progress(100, "Burn complete! Disc ejected.")
                except:
                    self._report_progress(100, "Burn complete!")
            else:
                self._report_progress(100, "Burn complete!")
            
            return True, "Disc burned successfully"
            
        except Exception as e:
            logger.error(f"Error during burn: {e}")
            import traceback
            traceback.print_exc()
            return False, f"Burn failed: {str(e)}"
    
    def get_media_info(self) -> Dict[str, any]:
        """
        Get information about the currently inserted media
        
        Returns:
            Dict with media information
        """
        info = {
            'present': False,
            'blank': False,
            'type': 'Unknown',
            'capacity_mb': 0,
            'used_mb': 0,
            'free_mb': 0
        }
        
        if not IMAPI2_AVAILABLE or not self.recorder:
            return info
        
        try:
            import comtypes.client
            
            disc_format = comtypes.client.CreateObject("IMAPI2.MsftDiscFormat2Data")
            disc_format.Recorder = self.recorder
            
            info['present'] = True
            
            try:
                info['blank'] = disc_format.MediaHeuristicallyBlank
            except:
                info['blank'] = False
            
            # Get media type
            try:
                media_type = disc_format.CurrentPhysicalMediaType
                media_types = {
                    0: "Unknown",
                    1: "CD-ROM",
                    2: "CD-R",
                    3: "CD-RW",
                    4: "DVD-ROM",
                    5: "DVD-R",
                    6: "DVD-RAM",
                    7: "DVD+RW",
                    8: "DVD+R",
                    9: "DVD+R DL",
                    10: "DVD-RW",
                    11: "HD-DVD-ROM",
                    12: "HD-DVD-R",
                    13: "HD-DVD-RAM",
                    14: "BD-ROM",
                    15: "BD-R",
                    16: "BD-RE"
                }
                info['type'] = media_types.get(media_type, f"Type {media_type}")
            except:
                pass
            
            # Get capacity info
            try:
                total_sectors = disc_format.TotalSectorsOnMedia
                free_sectors = disc_format.FreeSectorsOnMedia
                sector_size = 2048  # Standard sector size
                
                info['capacity_mb'] = (total_sectors * sector_size) / (1024 * 1024)
                info['free_mb'] = (free_sectors * sector_size) / (1024 * 1024)
                info['used_mb'] = info['capacity_mb'] - info['free_mb']
            except:
                pass
            
        except Exception as e:
            logger.warning(f"Error getting media info: {e}")
            info['present'] = False
        
        return info
    
    def get_drive_letter(self) -> Optional[str]:
        """Mounted path of the selected recorder (e.g. 'F:\\'), if any."""
        if not self.recorder:
            return None
        try:
            paths = self.recorder.VolumePathNames
            if paths:
                letter = str(paths[0])
                return letter if letter.endswith("\\") else letter + "\\"
        except Exception as e:
            logger.warning(f"Could not read drive letter: {e}")
        return None

    def verify_disc(
        self,
        staging_folder: str,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        compute_hash: bool = True,
        mount_timeout_s: int = 90,
    ) -> Tuple[bool, str, Dict[str, object]]:
        """Verify the written disc against the staging folder.

        Waits for the disc to remount, then compares every staged file by
        existence, size and (optionally) SHA-256. Returns (ok, message,
        details) where details lists any mismatches.
        """
        drive = self.get_drive_letter()
        if not drive:
            return False, "Cannot verify: no mounted drive letter for the recorder", {}

        # Wait for the freshly written disc to become readable.
        import time

        deadline = time.monotonic() + mount_timeout_s
        root = Path(drive)
        while time.monotonic() < deadline:
            if self._cancelled:
                return False, "Verification cancelled", {}
            try:
                if root.exists() and any(root.iterdir()):
                    break
            except OSError:
                pass
            if progress_callback:
                progress_callback(0, "Waiting for the disc to remount…")
            time.sleep(3)
        else:
            return False, f"Disc did not become readable within {mount_timeout_s}s", {}

        return compare_folder_trees(
            staging_folder,
            str(root),
            progress_callback=progress_callback,
            compute_hash=compute_hash,
            cancel_check=lambda: self._cancelled,
        )

    def eject(self) -> bool:
        """Eject the disc"""
        if self.recorder:
            try:
                self.recorder.EjectMedia()
                return True
            except Exception as e:
                logger.warning(f"Error ejecting: {e}")
        return False
    
    def close(self) -> bool:
        """Close the disc tray"""
        if self.recorder:
            try:
                self.recorder.CloseTray()
                return True
            except Exception as e:
                logger.warning(f"Error closing tray: {e}")
        return False


def compare_folder_trees(
    source_root: str,
    target_root: str,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    compute_hash: bool = True,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[bool, str, Dict[str, object]]:
    """Compare every file under ``source_root`` against ``target_root``.

    Pure filesystem comparison (headless-testable): existence, size and
    optional SHA-256 per file. Name lookup is case-insensitive to tolerate
    ISO9660 case folding. Extra files on the target are ignored.
    """
    import hashlib

    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _index_tree(root: Path) -> Dict[str, Path]:
        index = {}
        for item in root.rglob("*"):
            if item.is_file():
                index[str(item.relative_to(root)).replace("\\", "/").lower()] = item
        return index

    source = Path(source_root)
    target = Path(target_root)
    source_files = [p for p in source.rglob("*") if p.is_file()]
    target_index = _index_tree(target)

    missing: List[str] = []
    size_mismatch: List[str] = []
    hash_mismatch: List[str] = []
    verified = 0
    total = len(source_files)

    for n, item in enumerate(source_files):
        if cancel_check and cancel_check():
            return False, "Verification cancelled", {}
        rel = str(item.relative_to(source)).replace("\\", "/")
        if progress_callback and total:
            progress_callback(int(n * 100 / total), f"Verifying {n + 1}/{total}: {item.name}")

        counterpart = target_index.get(rel.lower())
        if counterpart is None:
            missing.append(rel)
            continue
        try:
            if counterpart.stat().st_size != item.stat().st_size:
                size_mismatch.append(rel)
                continue
            if compute_hash and _sha256(item) != _sha256(counterpart):
                hash_mismatch.append(rel)
                continue
        except OSError as exc:
            size_mismatch.append(f"{rel} (read error: {exc})")
            continue
        verified += 1

    details: Dict[str, object] = {
        "total": total,
        "verified": verified,
        "missing": missing,
        "size_mismatch": size_mismatch,
        "hash_mismatch": hash_mismatch,
        "hashed": compute_hash,
    }
    ok = not missing and not size_mismatch and not hash_mismatch and total > 0
    if ok:
        message = f"Verification PASSED: {verified}/{total} files match" + (
            " (SHA-256)" if compute_hash else " (size)"
        )
    else:
        problems = []
        if missing:
            problems.append(f"{len(missing)} missing")
        if size_mismatch:
            problems.append(f"{len(size_mismatch)} size mismatch")
        if hash_mismatch:
            problems.append(f"{len(hash_mismatch)} checksum mismatch")
        if total == 0:
            problems.append("no source files")
        message = "Verification FAILED: " + ", ".join(problems)
    return ok, message, details


def check_imapi2_available() -> bool:
    """Check if IMAPI2 is available for CD burning"""
    return IMAPI2_AVAILABLE
