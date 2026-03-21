"""
Single-instance application lock mechanism.

Ensures only one instance of AIPacs can run at a time by using a lock file
with process ID validation. If another instance is detected, the user is
prompted with options to kill it or cancel the new launch.

Usage:
    from PacsClient.utils.single_instance_lock import SingleInstanceLock
    
    lock = SingleInstanceLock()
    if not lock.try_acquire():
        # Another instance is running, user handled the choice
        sys.exit(0)
    
    # ... start app ...
    
    # Clean up on exit
    lock.release()
"""

import os
import sys
import psutil
import tempfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SingleInstanceLock:
    """
    Manages single-instance application locking using PID files.
    
    Works on both Windows and Unix systems. Validates that the process ID
    in the lock file is actually running before blocking a new instance.
    """
    
    LOCK_FILENAME = "aipacs_instance.lock"
    
    def __init__(self):
        """Initialize the single-instance lock manager."""
        self.lock_dir = Path(tempfile.gettempdir()) / "aipacs_locks"
        self.lock_file = self.lock_dir / self.LOCK_FILENAME
        self.current_pid = os.getpid()
        self._lock_acquired = False
        
        # Ensure lock directory exists
        self.lock_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_existing_pid(self) -> Optional[int]:
        """
        Read the PID from the lock file if it exists.
        
        Returns:
            The PID of the existing instance, or None if no valid lock file exists.
        """
        if not self.lock_file.exists():
            return None
        
        try:
            with open(self.lock_file, 'r') as f:
                pid_str = f.read().strip()
                return int(pid_str) if pid_str.isdigit() else None
        except (OSError, ValueError) as e:
            logger.debug(f"Could not read lock file: {e}")
            return None
    
    def _is_process_running(self, pid: int) -> bool:
        """
        Check if a process with the given PID is still running.
        
        Args:
            pid: Process ID to check
            
        Returns:
            True if the process exists, False otherwise.
        """
        try:
            # psutil.Process will raise NoSuchProcess if PID doesn't exist
            process = psutil.Process(pid)
            # Additional check: verify the process name contains "python" or "aipacs"
            # to avoid false positives with recycled PIDs
            name = process.name().lower()
            return "python" in name or "aipacs" in name
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            return False
    
    def _write_lock_file(self) -> bool:
        """
        Write the current process ID to the lock file.
        
        Returns:
            True if successful, False otherwise.
        """
        try:
            with open(self.lock_file, 'w') as f:
                f.write(str(self.current_pid))
            self._lock_acquired = True
            logger.info(f"Acquired instance lock (PID: {self.current_pid})")
            return True
        except OSError as e:
            logger.error(f"Failed to write lock file: {e}")
            return False
    
    def _kill_existing_process(self, pid: int) -> bool:
        """
        Attempt to kill an existing process with the given PID.
        
        Args:
            pid: Process ID to kill
            
        Returns:
            True if the process was successfully terminated, False otherwise.
        """
        try:
            process = psutil.Process(pid)
            logger.info(f"Terminating existing AIPacs instance (PID: {pid})")
            
            if sys.platform == 'win32':
                # On Windows, use SIGTERM which translates to TerminateProcess
                process.terminate()
            else:
                # On Unix, use SIGTERM
                process.terminate()
            
            # Wait up to 3 seconds for graceful termination
            try:
                process.wait(timeout=3)
                logger.info(f"Process {pid} terminated successfully")
                return True
            except psutil.TimeoutExpired:
                # If graceful termination timed out, force kill
                logger.warning(f"Process {pid} did not terminate gracefully, force killing")
                process.kill()
                process.wait(timeout=1)
                logger.info(f"Process {pid} force killed")
                return True
                
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            logger.warning(f"Could not kill process {pid}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error killing process {pid}: {e}")
            return False
    
    def try_acquire(self, show_dialog: bool = True) -> bool:
        """
        Attempt to acquire the instance lock.
        
        If another instance is detected, shows a user dialog (if show_dialog=True)
        asking whether to kill the existing instance or cancel.
        
        Args:
            show_dialog: If True, show a dialog for user interaction if conflict detected.
                        If False, silently fail.
        
        Returns:
            True if lock was successfully acquired, False if another instance is running.
        """
        existing_pid = self._get_existing_pid()
        
        if existing_pid is None:
            # No lock file, we can acquire it
            return self._write_lock_file()
        
        if not self._is_process_running(existing_pid):
            # Lock file exists but process is not running (stale lock)
            logger.info(f"Stale lock file detected (PID: {existing_pid}), removing")
            try:
                self.lock_file.unlink()
            except OSError:
                pass
            return self._write_lock_file()
        
        # Another instance IS running
        logger.warning(f"Another AIPacs instance is already running (PID: {existing_pid})")
        
        if show_dialog:
            from PySide6.QtWidgets import QMessageBox
            
            result = QMessageBox.warning(
                None,
                "AIPacs Already Running",
                f"Another instance of AIPacs is already running.\n\n"
                f"Would you like to close the existing instance and start a new one?\n\n"
                f"Existing PID: {existing_pid}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No  # Default to "No"
            )
            
            if result == QMessageBox.Yes:
                # User chose to kill the existing instance
                if self._kill_existing_process(existing_pid):
                    # Successfully killed, try to acquire lock
                    try:
                        self.lock_file.unlink()
                    except OSError:
                        pass
                    return self._write_lock_file()
                else:
                    # Failed to kill, show error
                    QMessageBox.critical(
                        None,
                        "Failed to Close Existing Instance",
                        f"Could not terminate the existing AIPacs instance (PID: {existing_pid}).\n\n"
                        f"Please close it manually and try again.",
                        QMessageBox.Ok
                    )
                    return False
            else:
                # User chose to cancel - bring focus to existing window if possible
                logger.info("User chose not to replace existing instance")
                try:
                    existing_process = psutil.Process(existing_pid)
                    if sys.platform == 'win32':
                        # Try to bring window to foreground on Windows
                        import subprocess
                        subprocess.run(
                            f'powershell -Command "Add-Type -AsDefinition @\\"'
                            f'using System;'
                            f'using System.Runtime.InteropServices;'
                            f'public class Win32 {{'
                            f'[DllImport(\\"user32.dll\\")] public static extern bool SetForegroundWindow(IntPtr hWnd);'
                            f'[DllImport(\\"user32.dll\\")] public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);'
                            f'}}'
                            f'\\"; '
                            f'$hWnd = [Win32]::FindWindow(\\\"Qt5QWindowOwnDCMarginWidget\\\", \\\"AIPacs\\\"); '
                            f'[Win32]::SetForegroundWindow($hWnd)"',
                            shell=True
                        )
                except Exception:
                    pass  # Silently fail if we can't bring window to focus
                return False
        
        return False
    
    def release(self):
        """
        Release the instance lock by deleting the lock file.
        
        Should be called during application shutdown.
        """
        if self._lock_acquired and self.lock_file.exists():
            try:
                self.lock_file.unlink()
                logger.info("Released instance lock")
                self._lock_acquired = False
            except OSError as e:
                logger.warning(f"Could not remove lock file: {e}")
    
    def __del__(self):
        """Ensure lock is released on object destruction."""
        self.release()
