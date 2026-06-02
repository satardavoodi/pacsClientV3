"""
Single-instance application lock — robust QLocalServer + PID-lock-file guard.

PRIMARY mechanism — Qt ``QLocalServer`` (a named local socket; a *named pipe* on
Windows). Only one process can ``listen()`` on a given name, so this is an ATOMIC
single-instance guard with **no read-then-write race**: two simultaneous launches
both fail to connect, then both try to listen — the OS lets exactly one win, and the
loser becomes a secondary that exits. When the owning process dies (normal exit OR
crash) the OS releases the pipe, so there is **never a permanently-stale lock**. A
second launch connects to the running instance and sends an ACTIVATE message, which
raises the existing window to the foreground; the second process then exits cleanly.

SECONDARY mechanism — a PID lock file (records the owner PID + server name for
diagnostics, and serves as a liveness fallback if QLocalServer is unavailable, e.g.
in a headless/test context). Validates that the recorded PID is actually alive (and
looks like an AIPacs process) before blocking, so a crashed run never blocks startup.

Works identically in a development/source run and a packaged/frozen build (the server
name is per-user and build-independent; QtNetwork ships with PySide6).

Usage:
    from PacsClient.utils.single_instance_lock import SingleInstanceLock

    lock = SingleInstanceLock()
    if not lock.try_acquire():
        sys.exit(0)                      # another instance is running — it was raised
    lock.set_activate_callback(raise_main_window)   # after the window exists
    ...
    lock.release()                       # on shutdown
"""

import os
import sys
import hashlib
import getpass
import tempfile
import logging
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# Message a second launch sends to the running instance to ask it to come forward.
_ACTIVATE_MSG = b"AIPACS_ACTIVATE"


def _server_name() -> str:
    """Per-user, build-independent QLocalServer name.

    Per-user so two different Windows users can each run their own instance, but a
    source run and a packaged run for the *same* user are mutually exclusive (both
    are "AIPacs"). Hashed so the name is pipe/filesystem-safe and bounded.
    """
    try:
        user = getpass.getuser()
    except Exception:
        user = "default"
    digest = hashlib.md5(f"AIPACS_SINGLE_INSTANCE::{user}".encode("utf-8")).hexdigest()
    return "AIPACS_SI_" + digest[:16]


class SingleInstanceLock:
    """Ensures only one AIPacs instance runs; raises the existing one on re-launch."""

    LOCK_FILENAME = "aipacs_instance.lock"

    def __init__(self):
        self._server_name = _server_name()
        self._server = None                      # QLocalServer when we are primary
        self._activate_callback: Optional[Callable[[], None]] = None
        self._lock_acquired = False
        self.current_pid = os.getpid()
        self.lock_dir = Path(tempfile.gettempdir()) / "aipacs_locks"
        self.lock_file = self.lock_dir / self.LOCK_FILENAME
        try:
            self.lock_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.debug("Could not create lock dir: %s", e)

    # ── public API ──────────────────────────────────────────────────────────
    def try_acquire(self, show_dialog: bool = True) -> bool:
        """Acquire single-instance ownership.

        Returns True if THIS process becomes the one running instance. Returns False
        if another instance is already running — in which case the existing window
        has been asked to come to the foreground and the caller should exit.
        """
        # 1) Is another instance already listening (i.e. actually alive)?
        if self._ping_existing_instance():
            logger.warning(
                "Another AIPacs instance is already running — raised it; this launch will exit."
            )
            if show_dialog:
                self._show_already_running_message()
            return False

        # 2) Become the primary by listening on the server name (atomic).
        if self._start_server():
            self._lock_acquired = True
            self._write_lock_file()
            logger.info(
                "Acquired single-instance lock (PID %s, server %s)",
                self.current_pid, self._server_name,
            )
            return True

        # 3) QLocalServer unavailable/failed — fall back to the PID-file guard so a
        #    transient Qt error can neither hard-block startup nor allow a duplicate.
        logger.warning("QLocalServer unavailable; using PID-lock-file fallback guard.")
        return self._fallback_pid_guard(show_dialog)

    def set_activate_callback(self, cb: Callable[[], None]) -> None:
        """Register the action (e.g. raise + focus the main window) to run when a
        second launch asks this instance to come to the foreground."""
        self._activate_callback = cb

    def release(self) -> None:
        """Release the server + lock file on shutdown. Idempotent."""
        try:
            if self._server is not None:
                try:
                    self._server.close()
                except Exception:
                    pass
                try:
                    from PySide6.QtNetwork import QLocalServer
                    QLocalServer.removeServer(self._server_name)
                except Exception:
                    pass
                self._server = None
        finally:
            self._remove_lock_file()
            if self._lock_acquired:
                logger.info("Released single-instance lock (PID %s)", self.current_pid)
            self._lock_acquired = False

    # ── QLocalServer / QLocalSocket (primary mechanism) ──────────────────────
    def _ping_existing_instance(self) -> bool:
        """True if a live instance is listening (and was asked to activate)."""
        try:
            from PySide6.QtNetwork import QLocalSocket
        except Exception:
            return False
        sock = QLocalSocket()
        try:
            sock.connectToServer(self._server_name)
            if not sock.waitForConnected(400):
                return False
            try:
                sock.write(_ACTIVATE_MSG)
                sock.flush()
                sock.waitForBytesWritten(400)
                # Graceful close so the buffered ACTIVATE is actually delivered to
                # the running instance before the socket tears down. Do NOT abort()
                # here — a hard reset discards the in-flight message and the existing
                # window would never come to the foreground.
                sock.disconnectFromServer()
                try:
                    if sock.state() != QLocalSocket.LocalSocketState.UnconnectedState:
                        sock.waitForDisconnected(400)
                except Exception:
                    pass
            except Exception:
                pass
            return True
        except Exception:
            return False

    def _start_server(self) -> bool:
        """Listen on the server name. Returns False if another process owns it."""
        try:
            from PySide6.QtNetwork import QLocalServer
        except Exception:
            return False
        # Clear any stale pipe/socket left by a crashed owner. Safe: we already
        # verified above that nobody is currently listening.
        try:
            QLocalServer.removeServer(self._server_name)
        except Exception:
            pass
        server = QLocalServer()
        try:
            server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        except Exception:
            pass
        if not server.listen(self._server_name):
            return False
        try:
            server.newConnection.connect(self._on_new_connection)
        except Exception:
            pass
        self._server = server
        return True

    def _on_new_connection(self) -> None:
        """A second launch connected — read its message and activate our window."""
        try:
            conn = self._server.nextPendingConnection()
            if conn is None:
                return
            try:
                conn.waitForReadyRead(300)
                data = bytes(conn.readAll())
            except Exception:
                data = b""
            if _ACTIVATE_MSG in data:
                cb = self._activate_callback
                if cb is not None:
                    try:
                        cb()
                    except Exception as e:
                        logger.warning("Single-instance activate callback failed: %s", e)
            try:
                conn.disconnectFromServer()
            except Exception:
                pass
        except Exception as e:
            logger.debug("newConnection handler error: %s", e)

    def _show_already_running_message(self) -> None:
        """Brief, non-fatal notice on the second launch before it exits."""
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            if QApplication.instance() is None:
                return
            QMessageBox.information(
                None,
                "AIPacs Already Running",
                "AIPacs is already running.\n\n"
                "The existing window has been brought to the front.",
                QMessageBox.Ok,
            )
        except Exception:
            pass

    # ── PID lock file (secondary: diagnostics + fallback) ────────────────────
    def _write_lock_file(self) -> bool:
        try:
            with open(self.lock_file, "w", encoding="utf-8") as f:
                f.write(f"{self.current_pid}\n{self._server_name}\n")
            return True
        except OSError as e:
            logger.debug("Could not write lock file: %s", e)
            return False

    def _remove_lock_file(self) -> None:
        try:
            if self.lock_file.exists():
                # Only remove a lock file we own (matches our PID) to avoid deleting
                # another instance's file in a fallback edge case.
                pid = self._read_pid()
                if pid is None or pid == self.current_pid:
                    self.lock_file.unlink()
        except OSError as e:
            logger.debug("Could not remove lock file: %s", e)

    def _read_pid(self) -> Optional[int]:
        try:
            if not self.lock_file.exists():
                return None
            with open(self.lock_file, "r", encoding="utf-8") as f:
                first = f.readline().strip()
            return int(first) if first.isdigit() else None
        except (OSError, ValueError):
            return None

    def _is_pid_alive(self, pid: int) -> bool:
        """True if pid is alive AND looks like an AIPacs process (guards recycled PIDs)."""
        try:
            import psutil
            proc = psutil.Process(pid)
            name = (proc.name() or "").lower()
            return ("python" in name) or ("aipacs" in name)
        except Exception:
            return False

    def _fallback_pid_guard(self, show_dialog: bool) -> bool:
        existing = self._read_pid()
        if existing is None:
            return self._write_lock_file()
        if not self._is_pid_alive(existing):
            logger.info("Stale lock file (PID %s not alive) — reclaiming.", existing)
            try:
                self.lock_file.unlink()
            except OSError:
                pass
            return self._write_lock_file()
        # A live instance exists but we have no IPC channel to raise it.
        logger.warning("Another AIPacs instance is running (PID %s, fallback guard).", existing)
        if show_dialog:
            self._show_already_running_message()
        return False

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass
