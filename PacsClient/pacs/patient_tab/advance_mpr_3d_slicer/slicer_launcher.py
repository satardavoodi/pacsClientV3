"""
AI-PACS Advanced Viewer Launcher Module

This module provides functionality to launch the AI-PACS Advanced Viewer
(custom 3D Slicer application) from within the main AI-PACS UI.

It follows the launch contract defined in:
  slicer_custom_app/docs/launch_contract.md

It handles:
- Locating the AIPacsAdvancedViewer.exe executable
- Launching Slicer in a background thread to keep UI responsive
- Passing parameters (dicom-dir, layout, patient-id, study-id, window-width, window-level)
- Error handling and user feedback
- Signal-based communication for process status
- Prewarming: Background Slicer process for instant startup
"""

import os
import sys
import subprocess
import threading
import json
import socket
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import QMessageBox, QFileDialog


# Default layout as per launch contract
DEFAULT_LAYOUT = "mpr"

# Default remote port for prewarmed Slicer communication
DEFAULT_REMOTE_PORT = 47891


def send_remote_command(payload: dict, host: str = "127.0.0.1", port: int = DEFAULT_REMOTE_PORT, timeout: float = 1.5) -> bool:
    """
    Send a JSON command to a running Advanced Viewer instance.

    Returns:
        True if the command was accepted, False otherwise.
    """
    try:
        data = (json.dumps(payload) + "\n").encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.sendall(data)

            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
                if b"\n" in response:
                    break

        if not response:
            return False

        try:
            response_json = json.loads(response.split(b"\n")[0].decode("utf-8"))
            return bool(response_json.get("ok"))
        except Exception:
            return False
    except Exception:
        return False


# =============================================================================
# SlicerPrewarmManager - Singleton for managing background Slicer instance
# =============================================================================

class SlicerPrewarmManager(QObject):
    """
    Singleton manager for the prewarmed AI-PACS Advanced Viewer.
    
    NOTE: Full Slicer prewarm is DISABLED because Slicer always shows a window
    briefly even with SW_HIDE. Instead, we only preload the launcher Python
    modules in the background, which speeds up the first launch without any
    visible window.
    
    The full Slicer process is started only when the user clicks the button.
    
    Usage:
        prewarm = SlicerPrewarmManager.instance()
        prewarm.start_after_delay(30)  # Preload modules after 30 seconds
        
        # On application exit:
        prewarm.terminate()
    """
    
    _instance: "SlicerPrewarmManager | None" = None
    
    # Signals
    prewarm_started = Signal()
    prewarm_terminated = Signal()
    prewarm_error = Signal(str)
    
    @classmethod
    def instance(cls) -> "SlicerPrewarmManager":
        """Get the singleton instance of SlicerPrewarmManager."""
        if cls._instance is None:
            print("[AIPACS_PREWARM] Creating singleton instance")
            cls._instance = SlicerPrewarmManager()
        else:
            print("[AIPACS_PREWARM] Returning existing singleton instance")
        return cls._instance
    
    def __init__(self, parent: QObject | None = None) -> None:
        # Prevent multiple instantiations
        if SlicerPrewarmManager._instance is not None:
            raise RuntimeError("Use SlicerPrewarmManager.instance() instead of direct instantiation")
        
        super().__init__(parent)
        self._process: subprocess.Popen | None = None
        self._remote_port: int | None = None
        self._launch_in_progress: bool = False
        self._prewarm_started: bool = False
        self._modules_preloaded: bool = False  # Track if modules are preloaded
        self._cached_exe: Path | None = None  # Cached path to AIPacsAdvancedViewer.exe
        self._start_timer: QTimer | None = None
        self._lock_file_path: str = os.path.join(
            os.environ.get('TEMP', os.environ.get('TMP', '/tmp')),
            "aipacs_viewer_standby.lock"
        )
        
        print("[AIPACS_PREWARM] SlicerPrewarmManager initialized")
    
    def _cleanup_stale_lock_file(self) -> None:
        """Clean up stale lock file from a crashed previous session."""
        try:
            if os.path.exists(self._lock_file_path):
                with open(self._lock_file_path, 'r') as f:
                    old_pid = f.read().strip()
                
                # Check if the PID is still running
                import subprocess as sp
                result = sp.run(
                    ['tasklist', '/FI', f'PID eq {old_pid}', '/NH'],
                    capture_output=True,
                    text=True,
                    creationflags=sp.CREATE_NO_WINDOW
                )
                
                if old_pid not in result.stdout:
                    # Process not running, remove stale lock
                    os.remove(self._lock_file_path)
                    print(f"[AIPACS_PREWARM] Removed stale lock file (PID {old_pid} not running)")
                else:
                    print(f"[AIPACS_PREWARM] Lock file exists and PID {old_pid} is running")
        except Exception as e:
            print(f"[AIPACS_PREWARM] Error checking lock file: {e}")
    
    def start_after_delay(self, delay_seconds: int = 30) -> None:
        """
        Start the module preloading after a delay.
        
        This is called once after the main UI is ready. The delay allows
        the main application to fully initialize before doing background work.
        
        NOTE: Full Slicer prewarm is DISABLED - we only preload Python modules.
        
        Args:
            delay_seconds: Seconds to wait before starting preload (default: 30)
        """
        print(f"[AIPACS_PREWARM] start_after_delay({delay_seconds}) called")
        
        # STRICT GUARD: If prewarm has ever been scheduled, do not schedule again
        if self._prewarm_started:
            print("[AIPACS_PREWARM] Preload already scheduled, skipping")
            return
        
        # SET FLAG IMMEDIATELY before scheduling timer (prevents race conditions)
        self._prewarm_started = True
        print(f"[AIPACS_PREWARM] Scheduling module preload in {delay_seconds} seconds")
        
        # Use QTimer.singleShot for delayed start
        QTimer.singleShot(delay_seconds * 1000, self._preload_modules)
    
    def _preload_modules(self) -> None:
        """
        Preload Python modules used by the Slicer launcher.
        
        This speeds up the first launch by importing heavy modules in advance,
        WITHOUT starting Slicer itself (which would show a window).
        
        Also caches the executable path so launch is faster.
        """
        if self._modules_preloaded:
            print("[AIPACS_PREWARM] Modules already preloaded")
            return
        
        print("[AIPACS_PREWARM] Preloading launcher modules...")
        
        try:
            # Preload the launch_slicer module (imports pathlib, subprocess, etc.)
            from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_custom_app import launch_slicer
            
            # Cache the Slicer executable path for faster launch
            exe = launch_slicer.find_slicer_executable()
            if exe:
                self._cached_exe = exe
                print(f"[AIPACS_PREWARM] Slicer executable cached: {exe}")
            
            self._modules_preloaded = True
            print("[AIPACS_PREWARM] [OK] Modules preloaded successfully")
            self.prewarm_started.emit()
            
        except Exception as e:
            print(f"[AIPACS_PREWARM] Module preload error: {e}")
            self.prewarm_error.emit(str(e))
    
    def _start_prewarm_now(self) -> None:
        """
        DISABLED: This used to start the full Slicer process in standby mode.
        
        Now we only preload modules - see _preload_modules().
        The full Slicer process is started only when user clicks the button.
        """
        # Full Slicer prewarm is disabled - just preload modules
        self._preload_modules()
    
    def is_running(self) -> bool:
        """
        Check if a prewarmed Slicer process is currently running.
        
        NOTE: Full Slicer prewarm is DISABLED. This now always returns False
        since we only preload modules, not run a background Slicer process.
        
        Returns:
            Always False (no standby process runs)
        """
        # Full Slicer prewarm is disabled - no process runs
        return False
    
    def modules_preloaded(self) -> bool:
        """
        Check if Python modules have been preloaded.
        
        Returns:
            True if modules were preloaded, False otherwise
        """
        return self._modules_preloaded
    
    def is_ready(self) -> bool:
        """
        Check if the prewarm is ready.
        
        NOTE: Full Slicer prewarm is DISABLED. This now checks if modules
        were preloaded instead of checking socket connectivity.
        
        Returns:
            True if modules preloaded, False otherwise
        """
        return self._modules_preloaded
    
    def send_remote_command(self, payload: dict) -> bool:
        """
        Send a command to the prewarmed Slicer instance.
        
        NOTE: Full Slicer prewarm is DISABLED. This always returns False
        so the caller will use normal launch instead.
        
        Args:
            payload: Dictionary containing the command (ignored)
        
        Returns:
            Always False (no standby process to send commands to)
        """
        # Full Slicer prewarm is disabled - no process to send commands to
        print("[AIPACS_PREWARM] send_remote_command() - prewarm disabled, returning False")
        return False
    
    def terminate(self) -> None:
        """
        Reset prewarm state.
        
        NOTE: Full Slicer prewarm is DISABLED. No process needs to be terminated.
        This just resets internal flags.
        """
        print("[AIPACS_PREWARM] terminate() called - resetting state")
        
        # Reset all flags to clean state
        self._prewarm_started = False
        self._modules_preloaded = False
        self._process = None
        self._remote_port = None
        self._launch_in_progress = False
        
        print("[AIPACS_PREWARM] terminate() completed")
        self.prewarm_terminated.emit()


# =============================================================================
# SlicerLauncherWorker - Thread for launching Slicer
# =============================================================================

class SlicerLauncherWorker(QThread):
    """
    Worker thread for launching Slicer without blocking the main UI.
    
    Signals:
        started_signal: Emitted when Slicer process starts
        finished_signal: Emitted when Slicer process completes (with exit code)
        error_signal: Emitted if an error occurs (with error message)
    """
    started_signal = Signal()
    finished_signal = Signal(int)  # exit code
    error_signal = Signal(str)  # error message
    
    def __init__(
        self, 
        dicom_dir: str, 
        layout: str = DEFAULT_LAYOUT,
        patient_id: Optional[str] = None,
        study_id: Optional[str] = None,
        window_width: Optional[float] = None,
        window_level: Optional[float] = None,
        series_uid: Optional[str] = None,
        slicer_exe: Optional[Path] = None,
        software_rendering: bool = False,  # Default to False to use NVIDIA GPU
        viewport_x: Optional[int] = None,
        viewport_y: Optional[int] = None,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None,
        remote_payload: Optional[dict] = None,
    ):
        super().__init__()
        self.dicom_dir = dicom_dir
        self.layout = layout
        self.patient_id = patient_id
        self.software_rendering = software_rendering
        self.study_id = study_id
        self.window_width = window_width
        self.window_level = window_level
        self.series_uid = series_uid
        self.slicer_exe = slicer_exe
        self.viewport_x = viewport_x
        self.viewport_y = viewport_y
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self._remote_payload = remote_payload
        self._process: Optional[subprocess.Popen] = None
    
    def run(self):
        """Execute the Slicer launch in a separate thread."""
        try:
            # ── Try sending a remote command to an already-running instance ──
            # This is done here (worker thread) instead of the main thread so
            # the UI event loop is never blocked by the socket timeout.
            if self._remote_payload:
                try:
                    if send_remote_command(self._remote_payload):
                        print("[AIPACS_LAUNCH] Remote command accepted by running viewer (from worker)")
                        self.finished_signal.emit(0)
                        return
                except Exception as e:
                    print(f"[AIPACS_LAUNCH] Remote command failed: {e}")

            # Import the launcher module (should already be preloaded for speed)
            from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_custom_app.launch_slicer import launch_slicer
            
            # =====================================================================
            # [AIPACS_LINK_SRC] Log config received by worker thread
            # =====================================================================
            print("[AIPACS_LINK_SRC] SlicerLauncherWorker.run() - Config received:")
            print(f"[AIPACS_LINK_SRC]   dicom_dir = {self.dicom_dir}")
            print(f"[AIPACS_LINK_SRC]   series_uid = {self.series_uid}")
            print(f"[AIPACS_LINK_SRC]   layout = {self.layout}")
            print(f"[AIPACS_LINK_SRC]   window_width = {self.window_width}")
            print(f"[AIPACS_LINK_SRC]   window_level = {self.window_level}")
            print(f"[AIPACS_LINK_SRC]   patient_id = {self.patient_id}")
            print(f"[AIPACS_LINK_SRC]   study_id = {self.study_id}")
            print(f"[AIPACS_LINK_SRC]   viewport_x = {self.viewport_x}")
            print(f"[AIPACS_LINK_SRC]   viewport_y = {self.viewport_y}")
            print(f"[AIPACS_LINK_SRC]   viewport_width = {self.viewport_width}")
            print(f"[AIPACS_LINK_SRC]   viewport_height = {self.viewport_height}")
            
            # Use cached executable from prewarm manager (faster than searching again)
            exe = self.slicer_exe
            if exe is None:
                prewarm = SlicerPrewarmManager.instance()
                exe = prewarm._cached_exe  # Use cached path if available
                if exe is None:
                    # Fall back to search (only if not cached)
                    from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_custom_app.launch_slicer import find_slicer_executable
                    exe = find_slicer_executable()
            
            if exe is None or not exe.exists():
                # Custom app not found - FATAL error
                self.error_signal.emit(
                    "AIPacsAdvancedViewer.exe not found!\n\n"
                    "The custom AI-PACS Advanced Viewer has not been built."
                )
                return
            
            # FAST validation: Just check directory exists
            # Skip slow recursive DICOM scan - we trust the folder from viewport
            dicom_path = Path(self.dicom_dir).resolve()
            if not dicom_path.exists() or not dicom_path.is_dir():
                self.error_signal.emit(f"DICOM directory not found:\n{dicom_path}")
                return
            
            self.started_signal.emit()
            
            # Launch Slicer with contract parameters
            exit_code = launch_slicer(
                dicom_dir=str(dicom_path),
                layout=self.layout,
                patient_id=self.patient_id,
                study_id=self.study_id,
                window_width=self.window_width,
                window_level=self.window_level,
                series_uid=self.series_uid,
                slicer_exe=exe,
                software_rendering=self.software_rendering,
                viewport_x=self.viewport_x,
                viewport_y=self.viewport_y,
                viewport_width=self.viewport_width,
                viewport_height=self.viewport_height,
                wait=True
            )
            
            self.finished_signal.emit(exit_code)
            
        except Exception as e:
            self.error_signal.emit(f"Failed to launch Slicer:\n{str(e)}")


class SlicerLauncher(QObject):
    """
    High-level interface for launching NewMPR2Slicer from the UI.
    
    Follows the launch contract defined in:
      slicer_custom_app/docs/launch_contract.md
    
    Usage:
        launcher = SlicerLauncher(parent_widget)
        launcher.launch_with_dicom("/path/to/dicom/folder")
        # or with specific layout
        launcher.launch_with_dicom("/path/to/dicom/folder", layout="axial")
        # or with patient info
        launcher.launch_with_dicom("/path/to/folder", patient_id="PAT001", study_id="STU001")
        # or use folder dialog
        launcher.launch_with_folder_dialog()
    """
    
    # Signals for UI feedback
    slicer_started = Signal()
    slicer_finished = Signal(int)
    slicer_error = Signal(str)
    
    def __init__(self, parent_widget=None):
        super().__init__(parent_widget)
        self.parent_widget = parent_widget
        self._worker: Optional[SlicerLauncherWorker] = None
        self._is_running = False
    
    @property
    def is_running(self) -> bool:
        """Check if Slicer is currently running."""
        return self._is_running
    
    def launch_with_dicom(
        self, 
        dicom_dir: str,
        layout: str = DEFAULT_LAYOUT,
        patient_id: Optional[str] = None,
        study_id: Optional[str] = None,
        window_width: Optional[float] = None,
        window_level: Optional[float] = None,
        series_uid: Optional[str] = None,
        viewport_x: Optional[int] = None,
        viewport_y: Optional[int] = None,
        viewport_width: Optional[int] = None,
        viewport_height: Optional[int] = None
    ) -> bool:
        """
        Launch Slicer with the specified DICOM directory and parameters.
        
        Follows the launch contract defined in docs/launch_contract.md.
        
        Args:
            dicom_dir: Path to the DICOM directory
            layout: Layout to display (default: 'mpr'). Options: mpr, fourup, 
                    axial, sagittal, coronal, threeD, conventional, dualthreeD
            patient_id: Optional patient ID for display
            study_id: Optional study ID for display
            window_width: Optional window width (contrast) for slice viewers
            window_level: Optional window level (brightness) for slice viewers
            series_uid: Optional Series Instance UID to identify the primary volume
            viewport_x: Optional VOR (main PACS viewer) X position on screen
            viewport_y: Optional VOR (main PACS viewer) Y position on screen
            viewport_width: Optional VOR (main PACS viewer) width for sizing
            viewport_height: Optional VOR (main PACS viewer) height for sizing
            
        Returns:
            True if launch was initiated, False if already running
        """
        print(f"[AIPACS_LAUNCH] SlicerLauncher.launch_with_dicom() called, _is_running={self._is_running}")

        # Build remote payload – the worker thread will try sending this
        # to an already-running Slicer instance BEFORE falling back to a
        # fresh launch.  This keeps the main/UI thread completely free.
        remote_payload = {
            "command": "load_dicom",
            "dicom_dir": dicom_dir,
            "layout": layout,
            "patient_id": patient_id,
            "study_id": study_id,
            "window_width": window_width,
            "window_level": window_level,
            "series_uid": series_uid,
            "viewport_x": viewport_x,
            "viewport_y": viewport_y,
            "viewport_width": viewport_width,
            "viewport_height": viewport_height
        }

        if self._is_running:
            print("[AIPACS_LAUNCH] BLOCKED - Already running, showing message")
            QMessageBox.information(
                self.parent_widget,
                "Ai-Pacs Viewer Running",
                "Ai-Pacs NewMPR2 Viewer is already running.\n"
                "Please close it before opening another instance."
            )
            return False
        
        # CRITICAL: Set running flag IMMEDIATELY to prevent race conditions
        self._is_running = True
        print("[AIPACS_LAUNCH] Set _is_running = True (immediate)")
        
        # Get cached executable path from prewarm manager
        from PacsClient.pacs.patient_tab.advance_mpr_3d_slicer.slicer_launcher import SlicerPrewarmManager
        prewarm_mgr = SlicerPrewarmManager.instance()
        
        # Create and start worker thread (remote command check happens inside)
        self._worker = SlicerLauncherWorker(
            dicom_dir=dicom_dir,
            layout=layout,
            patient_id=patient_id,
            study_id=study_id,
            window_width=window_width,
            window_level=window_level,
            series_uid=series_uid,
            slicer_exe=prewarm_mgr._cached_exe,
            viewport_x=viewport_x,
            viewport_y=viewport_y,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            remote_payload=remote_payload,
        )
        self._worker.started_signal.connect(self._on_started)
        self._worker.finished_signal.connect(self._on_finished)
        self._worker.error_signal.connect(self._on_error)
        
        self._worker.start()
        print("[AIPACS_LAUNCH] Worker thread started")
        return True
    
    def launch_with_folder_dialog(
        self,
        layout: str = DEFAULT_LAYOUT
    ) -> bool:
        """
        Show a folder selection dialog and launch Slicer with the selected folder.
        
        Args:
            layout: Layout to display (default: 'mpr')
        
        Returns:
            True if launch was initiated, False if cancelled or already running
        """
        if self._is_running:
            QMessageBox.information(
                self.parent_widget,
                "Ai-Pacs Viewer Running",
                "Ai-Pacs NewMPR2 Viewer is already running.\n"
                "Please close it before opening another instance."
            )
            return False
        
        # Show folder selection dialog
        folder = QFileDialog.getExistingDirectory(
            self.parent_widget,
            "Select DICOM Directory",
            "",
            QFileDialog.ShowDirsOnly | QFileDialog.DontResolveSymlinks
        )
        
        if not folder:
            return False  # User cancelled
        
        return self.launch_with_dicom(folder, layout=layout)
    
    def _on_started(self):
        """Handle Slicer process started."""
        self._is_running = True
        self.slicer_started.emit()
        print("[SlicerLauncher] NewMPR2Slicer started successfully")
    
    def _on_finished(self, exit_code: int):
        """Handle Slicer process finished."""
        self._is_running = False
        self.slicer_finished.emit(exit_code)
        print(f"[SlicerLauncher] NewMPR2Slicer closed with exit code: {exit_code}")
        
        if exit_code != 0:
            QMessageBox.warning(
                self.parent_widget,
                "Ai-Pacs Viewer Closed",
                f"Ai-Pacs NewMPR2 Viewer closed with exit code: {exit_code}\n"
                "This may indicate an error occurred."
            )
    
    def _on_error(self, error_msg: str):
        """Handle errors during Slicer launch."""
        self._is_running = False
        self.slicer_error.emit(error_msg)
        print(f"[SlicerLauncher] Error: {error_msg}")
        
        QMessageBox.critical(
            self.parent_widget,
            "Ai-Pacs Viewer Error",
            error_msg
        )


# Global singleton launcher instance
_slicer_launcher_instance: Optional[SlicerLauncher] = None


def get_slicer_launcher(parent_widget=None) -> SlicerLauncher:
    """
    Get or create a SlicerLauncher singleton instance.
    
    Uses a singleton pattern to ensure running state is tracked properly
    and prevent double-launching.
    
    Args:
        parent_widget: The parent widget for dialogs
        
    Returns:
        SlicerLauncher singleton instance
    """
    from shiboken6 import isValid

    global _slicer_launcher_instance

    # Recreate if missing or underlying QObject was deleted (e.g., parent widget closed)
    if _slicer_launcher_instance is None or not isValid(_slicer_launcher_instance):
        _slicer_launcher_instance = SlicerLauncher(None)

    # Keep a weak reference to parent widget for dialogs, but DO NOT parent the QObject
    # to avoid accidental deletion when the UI is destroyed/rebuilt.
    if parent_widget is not None:
        _slicer_launcher_instance.parent_widget = parent_widget

    return _slicer_launcher_instance


def get_prewarm_manager() -> SlicerPrewarmManager:
    """
    Get the singleton SlicerPrewarmManager instance.
    
    This is a convenience function to get the prewarm manager.
    
    Returns:
        SlicerPrewarmManager singleton instance
    """
    return SlicerPrewarmManager.instance()


def terminate_all_slicer_processes() -> None:
    """
    Terminate all AI-PACS Advanced Viewer (Slicer) processes.
    
    This should be called when the main application is closing to ensure
    no orphaned Slicer processes are left running.
    
    Terminates:
    1. The prewarm/standby process (if running)
    2. Any viewer processes spawned by the current app session
    """
    print("[AIPACS_CLEANUP] Terminating all Slicer processes...")
    
    # 1. Terminate prewarm manager
    try:
        prewarm = SlicerPrewarmManager.instance()
        if prewarm.is_running():
            print("[AIPACS_CLEANUP] Terminating prewarm process...")
            prewarm.terminate()
    except Exception as e:
        print(f"[AIPACS_CLEANUP] Error terminating prewarm: {e}")
    
    # 2. Kill any AIPacsAdvancedViewer.exe processes started by this session
    # We use taskkill on Windows to ensure cleanup
    try:
        if sys.platform == 'win32':
            import subprocess as sp
            # Kill by process name - will kill all instances
            result = sp.run(
                ['taskkill', '/F', '/IM', 'AIPacsAdvancedViewer.exe'],
                capture_output=True,
                text=True,
                creationflags=sp.CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                print("[AIPACS_CLEANUP] Killed AIPacsAdvancedViewer.exe processes")
            else:
                # No processes found is also OK
                print("[AIPACS_CLEANUP] No AIPacsAdvancedViewer.exe processes to kill")
    except Exception as e:
        print(f"[AIPACS_CLEANUP] Error killing viewer processes: {e}")
    
    # 3. Clean up lock file
    try:
        lock_path = os.path.join(
            os.environ.get('TEMP', os.environ.get('TMP', '/tmp')),
            "aipacs_viewer_standby.lock"
        )
        if os.path.exists(lock_path):
            os.remove(lock_path)
            print(f"[AIPACS_CLEANUP] Removed lock file: {lock_path}")
    except Exception as e:
        print(f"[AIPACS_CLEANUP] Error removing lock file: {e}")
    
    print("[AIPACS_CLEANUP] Cleanup complete")
