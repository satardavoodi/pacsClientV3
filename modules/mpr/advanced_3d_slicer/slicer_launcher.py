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
- Prewarming: Reuse a hidden background Slicer process for faster opening
"""

import os
import sys
import subprocess
import threading
import time
import json
import socket
import logging
from pathlib import Path
from typing import Optional, Callable

from PySide6.QtCore import QObject, Signal, QThread, QTimer
from PySide6.QtWidgets import QMessageBox, QFileDialog


# Default layout as per launch contract
DEFAULT_LAYOUT = "mpr"

# Default remote port for prewarmed Slicer communication
DEFAULT_REMOTE_PORT = 47891

logger = logging.getLogger(__name__)


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
    """Compatibility facade for the independently owned resident service.

    Scheduling and status are cheap; executable discovery, sockets and process
    startup run in the service worker. Imports alone never count as readiness.
    """
    _instance = None
    prewarm_started = Signal()
    prewarm_terminated = Signal()
    prewarm_error = Signal(str)

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cached_exe = None
        self._modules_preloaded = False
        self._prewarm_started = False
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.timeout.connect(self._start_prewarm_now)

    def start_after_delay(self, delay_seconds=0):
        if not self._prewarm_started:
            self._prewarm_started = True
            self._start_timer.start(max(0, int(delay_seconds * 1000)))

    def _start_prewarm_now(self):
        from .resident_service import get_service, resident_enabled
        if not resident_enabled():
            return
        def complete(future):
            try:
                future.result()
                self._modules_preloaded = True
                self.prewarm_started.emit()
            except Exception as exc:
                self.prewarm_error.emit(type(exc).__name__)
        try:
            get_service().warmup().add_done_callback(complete)
        except Exception as exc:
            self.prewarm_error.emit(type(exc).__name__)

    def _preload_modules(self):
        self._start_prewarm_now()

    def is_running(self):
        from .resident_service import get_service
        try:
            return get_service().state in {"starting", "ready", "uncertain"}
        except RuntimeError:
            return False

    def modules_preloaded(self):
        return self._modules_preloaded

    def is_ready(self):
        from .resident_service import get_service
        try:
            return get_service().state == "ready"
        except RuntimeError:
            return False

    def send_remote_command(self, payload):
        """Return a Future; completion means executed, not merely scheduled."""
        from .resident_service import get_service
        return get_service().request("load_dicom", payload)

    def terminate(self):
        from .resident_service import stop_services
        self._start_timer.stop()
        stop_services()
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
    
    @staticmethod
    def _find_latest_log() -> Optional[Path]:
        """Return the path of the most-recently modified Advanced MPR log file, or None."""
        try:
            from modules.mpr.advanced_3d_slicer.slicer_custom_app.launch_slicer import _resolve_user_writable_launch_dir
            log_dir = _resolve_user_writable_launch_dir()
            log_files = list(log_dir.glob("*.log")) + list(log_dir.glob("*.txt"))
            if not log_files:
                return None
            return max(log_files, key=lambda p: p.stat().st_mtime)
        except Exception:
            return None

    @staticmethod
    def _validate_runtime_startup_script(runtime_root: Path) -> Optional[str]:
        """Validate the installed startup script signature for launch compatibility.

        Installed-only regressions can happen when a stale Advanced MPR runtime payload
        remains in modules_runtime while the workstation launcher code has been updated.
        In that state Slicer may open in a generic four-up/fourth-box flow instead of the
        intended Advanced MPR startup path.
        """
        required_markers = (
            "_REMOTE_SERVER_STARTED",
            "NEWMPR2_REMOTE_PORT",
            "start_remote_command_server",
        )

        # Canonical module path (mirrors launch_slicer.py first candidate).
        source_module_script = (
            Path(__file__).resolve().parent
            / "slicer_custom_app"
            / "startup_script.py"
        )
        # Legacy runtime path used by older Slicer bundles.
        legacy_runtime_script = runtime_root / "bin" / "Python" / "startup_script.py"
        # Canonical plugin Python path used by current optional-module packaging.
        plugin_python_script = (
            runtime_root
            / "python"
            / "modules"
            / "mpr"
            / "advanced_3d_slicer"
            / "slicer_custom_app"
            / "startup_script.py"
        )

        candidate_scripts = [source_module_script, legacy_runtime_script, plugin_python_script]
        existing_scripts = [script for script in candidate_scripts if script.exists()]
        if not existing_scripts:
            return (
                "The Advanced MPR runtime is missing startup_script.py.\n\n"
                "Try re-installing the module:\n"
                "  Settings -> Installation -> Advanced MPR -> Re-install\n\n"
                "Checked paths:\n"
                + "\n".join(str(path) for path in candidate_scripts)
            )

        marker_failures: list[tuple[Path, list[str]]] = []
        read_failures: list[tuple[Path, Exception]] = []

        for startup_script in existing_scripts:
            try:
                startup_text = startup_script.read_text(encoding="utf-8", errors="ignore")
            except Exception as exc:
                read_failures.append((startup_script, exc))
                continue

            missing = [marker for marker in required_markers if marker not in startup_text]
            if not missing:
                return None
            marker_failures.append((startup_script, missing))

        if read_failures and not marker_failures:
            first_path, first_exc = read_failures[0]
            return (
                "The Advanced MPR startup script could not be read.\n\n"
                "Try re-installing the module:\n"
                "  Settings -> Installation -> Advanced MPR -> Re-install\n\n"
                f"File:\n{first_path}\n\n"
                f"Read error: {first_exc}"
            )

        details = []
        for script_path, missing_markers in marker_failures:
            details.append(f"{script_path} -> missing: {', '.join(missing_markers)}")

        return (
            "The installed Advanced MPR runtime is outdated and incompatible with this workstation build.\n\n"
            "Symptom: launch may fail or fall back to unexpected behavior instead of Advanced MPR mode.\n\n"
            "Fix:\n"
            "  Settings -> Installation -> Advanced MPR -> Re-install\n\n"
            "Startup script compatibility failures:\n"
            + "\n".join(details)
        )

    @staticmethod
    def _check_runtime_installed() -> Optional[str]:
        """
        Verify that the Advanced MPR runtime is installed in the user runtime directory.

        Returns:
            None  — runtime is present and healthy.
            str   — human-readable problem description (actionable, shown directly in dialog).
        """
        try:
            from aipacs_runtime import advanced_mpr_runtime_root
            runtime_root = advanced_mpr_runtime_root()
            exe_path = runtime_root / "AIPacsAdvancedViewer.exe"
            if not runtime_root.exists():
                return (
                    "The Advanced MPR module is not installed yet.\n\n"
                    "To install it:\n"
                    "  Settings → Installation → Advanced MPR → Install\n\n"
                    f"Expected runtime folder:\n{runtime_root}"
                )
            if not exe_path.exists():
                return (
                    "The Advanced MPR runtime is present but incomplete\n"
                    "(AIPacsAdvancedViewer.exe not found).\n\n"
                    "Try re-installing the module:\n"
                    "  Settings → Installation → Advanced MPR → Re-install\n\n"
                    f"Runtime folder:\n{runtime_root}"
                )

            startup_problem = SlicerLauncherWorker._validate_runtime_startup_script(runtime_root)
            if startup_problem:
                return startup_problem
        except Exception as exc:
            # If we cannot even resolve the path, let the normal search continue.
            print(f"[AIPACS_LAUNCH] _check_runtime_installed: {exc}")
        return None

    @staticmethod
    def _wait_until_launch_ready(
        proc: subprocess.Popen,
        startup_log: Optional[Path],
        *,
        marker: str = "STARTUP SEQUENCE COMPLETED SUCCESSFULLY",
        timeout_s: float = 90.0,
        fallback_stable_s: float = 8.0,
        poll_s: float = 0.25,
    ) -> tuple[bool, str]:
        """Wait until runtime startup is truly ready.

        The startup marker is required. Process lifetime or log output alone
        cannot establish readiness. fallback_stable_s is retained for callers.
        """
        start_t = time.monotonic()
        deadline = start_t + max(1.0, float(timeout_s))

        while time.monotonic() < deadline:
            rc = proc.poll()
            if rc is not None:
                return False, f"process exited before ready (exit_code={rc})"

            if startup_log is not None:
                try:
                    if startup_log.exists():
                        text = startup_log.read_text(encoding="utf-8", errors="ignore")
                        if marker in text:
                            return True, "startup_marker"
                except Exception:
                    pass

            time.sleep(max(0.05, float(poll_s)))

        rc = proc.poll()
        if rc is not None:
            return False, f"process exited before ready (exit_code={rc})"
        return False, "startup_timeout_without_ready_marker"

    def run(self):
        """Execute the Slicer launch in a separate thread."""
        try:
            from .resident_service import get_service, resident_enabled
            if resident_enabled() and self._remote_payload:
                # Join an in-flight warmup; never race it with another launch.
                service = get_service()
                service.request("load_dicom", self._remote_payload).result(timeout=245)
                self.started_signal.emit()
                self.finished_signal.emit(service.wait_until_closed())
                return
            logger.info(
                "[AIPACS_LAUNCH] worker_start dicom_dir=%s layout=%s study_id=%s series_uid=%s",
                self.dicom_dir,
                self.layout,
                self.study_id,
                self.series_uid,
            )

            # ── Try sending a remote command to an already-running instance ──
            # This is done here (worker thread) instead of the main thread so
            # the UI event loop is never blocked by the socket timeout.
            if self._remote_payload:
                try:
                    if send_remote_command(self._remote_payload):
                        print("[AIPACS_LAUNCH] Remote command accepted by running viewer (from worker)")
                        self.started_signal.emit()
                        self.finished_signal.emit(0)
                        return
                except Exception as e:
                    print(f"[AIPACS_LAUNCH] Remote command failed: {e}")

            # ── Pre-launch readiness check ────────────────────────────────────
            problem = self._check_runtime_installed()
            if problem:
                print(f"[AIPACS_LAUNCH] Runtime readiness check failed: {problem}")
                logger.error("[AIPACS_LAUNCH] runtime_readiness_failed: %s", problem)
                self.error_signal.emit(problem)
                return

            # Import the launcher module (should already be preloaded for speed)
            from modules.mpr.advanced_3d_slicer.slicer_custom_app.launch_slicer import launch_slicer
            
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
                    from modules.mpr.advanced_3d_slicer.slicer_custom_app.launch_slicer import find_slicer_executable
                    exe = find_slicer_executable()
            
            if exe is None or not exe.exists():
                # Custom app not found - FATAL error
                logger.error("[AIPACS_LAUNCH] executable_not_found resolved_exe=%s", exe)
                self.error_signal.emit(
                    "AIPacsAdvancedViewer.exe not found!\n\n"
                    "The custom AI-PACS Advanced Viewer has not been built."
                )
                return
            
            # FAST validation: Just check directory exists
            # Skip slow recursive DICOM scan - we trust the folder from viewport
            dicom_path = Path(self.dicom_dir).resolve()
            if not dicom_path.exists() or not dicom_path.is_dir():
                logger.error("[AIPACS_LAUNCH] dicom_dir_not_found path=%s", dicom_path)
                self.error_signal.emit(f"DICOM directory not found:\n{dicom_path}")
                return

            logger.info("[AIPACS_LAUNCH] launch_begin exe=%s dicom_dir=%s", exe, dicom_path)

            # Launch in detached mode, then wait for a concrete startup-ready signal.
            launch_result = launch_slicer(
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
                wait=False,
                return_process_handle=True,
            )

            if not isinstance(launch_result, tuple) or len(launch_result) != 2:
                self.error_signal.emit("Failed to launch AI Advanced Analysis process.")
                return

            proc, startup_log = launch_result
            ready_ok, ready_reason = self._wait_until_launch_ready(proc, startup_log)
            if not ready_ok:
                logger.error("[AIPACS_LAUNCH] launch_not_ready: %s", ready_reason)
                self.error_signal.emit(
                    "AI Advanced Analysis failed to start correctly.\n\n"
                    f"Reason: {ready_reason}"
                )
                return

            logger.info(
                "[AIPACS_LAUNCH] launch_ready pid=%s criterion=%s",
                getattr(proc, "pid", "?"),
                ready_reason,
            )
            self.started_signal.emit()

            exit_code = proc.wait()
            try:
                log_handle = getattr(proc, "_aipacs_log_handle", None)
                if log_handle is not None:
                    log_handle.close()
            except Exception:
                pass

            self.finished_signal.emit(exit_code)
            logger.info("[AIPACS_LAUNCH] launch_finished exit_code=%s", exit_code)
            
        except Exception as e:
            logger.exception("[AIPACS_LAUNCH] worker_exception")
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
        logger.info(
            "[AIPACS_LAUNCH] ui_launch_request is_running=%s dicom_dir=%s layout=%s study_id=%s series_uid=%s",
            self._is_running,
            dicom_dir,
            layout,
            study_id,
            series_uid,
        )

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
            logger.warning("[AIPACS_LAUNCH] ui_launch_blocked_already_running")
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
        from modules.mpr.advanced_3d_slicer.slicer_launcher import SlicerPrewarmManager
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
        logger.info("[AIPACS_LAUNCH] signal_started")
    
    def _on_finished(self, exit_code: int):
        """Handle Slicer process finished."""
        self._is_running = False
        self.slicer_finished.emit(exit_code)
        print(f"[SlicerLauncher] NewMPR2Slicer closed with exit code: {exit_code}")
        logger.info("[AIPACS_LAUNCH] signal_finished exit_code=%s", exit_code)

        if exit_code != 0:
            latest_log = SlicerLauncherWorker._find_latest_log()
            log_hint = (
                f"\n\nLog file:\n{latest_log}"
                if latest_log
                else ""
            )
            QMessageBox.warning(
                self.parent_widget,
                "Ai-Pacs Viewer Closed",
                f"Ai-Pacs NewMPR2 Viewer closed with exit code: {exit_code}\n"
                f"This may indicate an error occurred.{log_hint}"
            )
    
    def _on_error(self, error_msg: str):
        """Handle errors during Slicer launch."""
        self._is_running = False
        self.slicer_error.emit(error_msg)
        print(f"[SlicerLauncher] Error: {error_msg}")
        logger.error("[AIPACS_LAUNCH] signal_error %s", error_msg)
        
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
    """Stop only resident runtimes owned by this session; never kill by name."""
    from .resident_service import stop_services
    stop_services()
