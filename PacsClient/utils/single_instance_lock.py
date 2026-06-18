"""
Single-instance application lock — robust QLocalServer + PID-lock-file guard.

PRIMARY mechanism — Qt ``QLocalServer`` (a named local socket; a *named pipe* on
Windows). Only one process can ``listen()`` on a given name, so this is an ATOMIC
single-instance guard with **no read-then-write race**: two simultaneous launches
both fail to connect, then both try to listen — the OS lets exactly one win. When
the owning process dies (normal exit OR crash) the OS releases the pipe, so there
is **never a permanently-stale lock**.

TAKEOVER policy (DEFAULT since 2026-06-05 — "new launch wins"): when a new launch
finds an existing instance, it does NOT ask the user and does NOT exit. It first
sends the running instance a SHUTDOWN message over the local socket (clean close:
DB checkpoint, subprocess termination, lock release), waits briefly, and if the
old instance is still alive (hung after hibernate / crash-leftover / an old build
that doesn't understand SHUTDOWN) it force-kills the old AIPacs process tree(s)
via psutil — including orphaned download workers/spares that re-exec ``main.py``.
Then the new launch acquires the lock and continues normally. Exactly one active
instance, always the newest one. Escape hatch: ``AIPACS_NO_TAKEOVER=1`` restores
the legacy behavior (raise the existing window via ACTIVATE and exit quietly).
Under pytest (``PYTEST_CURRENT_TEST`` set) takeover is disabled automatically so
tests can never kill the test runner or a developer's live session.

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
        sys.exit(0)                      # takeover failed/raced — other instance kept
    lock.set_activate_callback(raise_main_window)   # after the window exists
    ...
    lock.release()                       # on shutdown
"""

import os
import sys
import time
import hashlib
import getpass
import tempfile
import logging
from pathlib import Path
from typing import Optional, Callable


# Fast Windows process enumeration for the single-instance sweep (2026-06-18).
# On Windows, psutil's Process.name() is os.path.basename(self.exe()), so
# psutil.process_iter(["pid", "name"]) pays an OpenProcess + PEB read
# (cext.proc_exe) for EVERY process on the machine. Stack-confirmed ~9.5 s at
# startup for ~300 processes on a busy workstation — the 2026-06-08 "cheap name
# pre-filter" assumed name() was cheap (true on Linux, NOT on Windows). A
# Toolhelp32 snapshot returns the image basename for all processes in one cheap
# syscall (no per-process handle). Matching/kill logic is unchanged; this only
# makes the (pid, name) pre-filter cheap. Kill switch: AIPACS_FAST_PROC_SCAN=0
# restores the psutil-only enumeration.
_FAST_PROC_SCAN = (os.getenv("AIPACS_FAST_PROC_SCAN", "1") or "1").strip() != "0"


def _toolhelp_pid_names():
    """Yield (pid, image_basename) for every process via a Windows Toolhelp32
    snapshot — one cheap syscall, no per-process OpenProcess. Windows only;
    raises on any failure so the caller falls back to psutil."""
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    invalid = wintypes.HANDLE(-1).value
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == invalid:
        raise OSError("CreateToolhelp32Snapshot failed")
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            yield int(entry.th32ProcessID), str(entry.szExeFile)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)


def _iter_pid_name_cheap():
    """Yield (pid, image_basename) for every process as cheaply as the platform
    allows. Windows: Toolhelp snapshot (avoids psutil name()->exe() per process);
    otherwise / on any failure: psutil.process_iter(["pid", "name"])."""
    if _FAST_PROC_SCAN and os.name == "nt":
        try:
            for pid, name in _toolhelp_pid_names():
                yield pid, name
            return
        except Exception:
            pass  # fall through to the psutil enumeration
    try:
        import psutil
    except Exception:
        return
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            yield proc.pid, (proc.info.get("name") or "")
        except Exception:
            continue

logger = logging.getLogger(__name__)

# Message a second launch sends to the running instance to ask it to come forward.
_ACTIVATE_MSG = b"AIPACS_ACTIVATE"
# Message a new (takeover) launch sends to ask the running instance to close
# cleanly so the new launch can replace it. Old builds ignore unknown messages —
# they are covered by the force-kill fallback.
_SHUTDOWN_MSG = b"AIPACS_SHUTDOWN"

# How long a takeover waits for the old instance to exit cleanly before
# force-killing, and after force-kill for the pipe to be released.
_TAKEOVER_GRACEFUL_WAIT_S = 6.0
_TAKEOVER_POSTKILL_WAIT_S = 3.0


def _takeover_enabled() -> bool:
    """New-launch-wins takeover is the build default; env/pytest can disable."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return False
    return os.environ.get("AIPACS_NO_TAKEOVER", "").strip().lower() not in (
        "1", "true", "yes",
    )


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

        Takeover mode (default): an existing instance is asked to shut down
        cleanly, force-killed if it does not, and THIS process becomes the one
        running instance — no dialog, no question. Returns False only if the
        takeover raced with an even newer launch (exit quietly) or every
        mechanism failed.

        Legacy mode (``AIPACS_NO_TAKEOVER=1`` or under pytest): returns False
        when another instance is running — the existing window has been asked
        to come to the foreground and the caller should exit.
        """
        takeover = _takeover_enabled()

        # 1) Is another instance already listening (i.e. actually alive)?
        if self._ping_existing_instance(message=None if takeover else _ACTIVATE_MSG):
            if not takeover:
                logger.warning(
                    "Another AIPacs instance is already running — raised it; this launch will exit."
                )
                if show_dialog:
                    self._show_already_running_message()
                return False
            # Takeover: new launch wins. Ask for a clean close first so the
            # old instance checkpoints the DB and terminates its download
            # subprocesses; escalate to force-kill if it lingers (hung after
            # hibernate, crashed half-dead, or an old build without the
            # SHUTDOWN handler).
            logger.warning(
                "Another AIPacs instance is running — taking over (new launch wins)."
            )
            self._request_existing_shutdown()
            if not self._wait_existing_gone(_TAKEOVER_GRACEFUL_WAIT_S):
                killed = self._force_close_other_instances()
                logger.warning(
                    "Old instance did not close gracefully — force-closed %d "
                    "AIPacs process tree(s).", killed,
                )
                self._wait_existing_gone(_TAKEOVER_POSTKILL_WAIT_S)
        elif takeover:
            # Nobody is listening, but hidden leftovers may still be running
            # (orphaned download workers / pre-warm spares whose parent died,
            # an instance hung before its server came up). Sweep them so they
            # cannot hold dicom.db, sockets, or ports against the new run.
            killed = self._force_close_other_instances()
            if killed:
                logger.warning(
                    "Startup sweep force-closed %d orphaned AIPacs process tree(s).",
                    killed,
                )

        # 2) Become the primary by listening on the server name (atomic).
        if self._start_server():
            self._lock_acquired = True
            self._write_lock_file()
            logger.info(
                "Acquired single-instance lock (PID %s, server %s)",
                self.current_pid, self._server_name,
            )
            return True

        # 3) Could not listen. In takeover mode the usual cause is a racing
        #    twin launch that won the pipe a moment ago — defer to it (it IS
        #    the newest instance) instead of starting a kill loop.
        if takeover and self._ping_existing_instance(message=_ACTIVATE_MSG):
            logger.warning(
                "Another launch won the single-instance race — exiting quietly."
            )
            return False

        # 4) QLocalServer unavailable/failed — fall back to the PID-file guard so a
        #    transient Qt error can neither hard-block startup nor allow a duplicate.
        logger.warning("QLocalServer unavailable; using PID-lock-file fallback guard.")
        return self._fallback_pid_guard(show_dialog and not takeover)

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
    def _ping_existing_instance(self, message: Optional[bytes] = _ACTIVATE_MSG) -> bool:
        """True if a live instance is listening.

        ``message=_ACTIVATE_MSG`` (default) also asks it to come forward;
        ``message=None`` is a quiet liveness probe (connect only) used by the
        takeover flow so the doomed old window is not raised first.
        """
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
                if message:
                    sock.write(message)
                    sock.flush()
                    sock.waitForBytesWritten(400)
                # Graceful close so any buffered message is actually delivered to
                # the running instance before the socket tears down. Do NOT abort()
                # here — a hard reset discards the in-flight message and the existing
                # instance would never receive it.
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

    # ── takeover machinery (new launch wins) ────────────────────────────────
    def _request_existing_shutdown(self) -> bool:
        """Ask the running instance to close cleanly. Best-effort."""
        return self._ping_existing_instance(message=_SHUTDOWN_MSG)

    def _wait_existing_gone(self, timeout_s: float) -> bool:
        """Poll (quietly) until no instance is listening. True when gone."""
        deadline = time.monotonic() + max(0.0, timeout_s)
        while time.monotonic() < deadline:
            if not self._ping_existing_instance(message=None):
                return True
            time.sleep(0.25)
        return not self._ping_existing_instance(message=None)

    @staticmethod
    def _proc_is_aipacs(name: str, exe: str, cmdline: list, cwd: str = "") -> bool:
        """Match AIPacs processes: frozen exes and python source/worker runs.

        Pure-function matching rules (unit-testable without psutil):
        - frozen: image name contains "aipacs" once spaces are squashed
          (covers ``aipacs.exe`` and ``AI PACS Viewer.exe``);
        - source/worker: a python process whose cmdline runs ``main.py`` AND
          whose script path / interpreter path / cwd points into an AIPacs
          tree ("ai-pacs"/"aipacs"). Workers re-exec a *relative* ``main.py``,
          so the venv interpreter path or cwd is the discriminator there.
          Plain ``python -m pytest`` or unrelated main.py projects never match.
        """
        n = (name or "").lower().replace(" ", "")
        if n.endswith(".exe") and "aipacs" in n:
            return True
        if "python" not in n:
            return False
        parts = [str(p) for p in (cmdline or [])]
        runs_main = any(p.lower().rstrip('"').endswith("main.py") for p in parts)
        if not runs_main:
            return False
        haystack = " ".join(parts).lower() + " " + (exe or "").lower() + " " + (cwd or "").lower()
        squashed = haystack.replace(" ", "")
        return ("ai-pacs" in squashed) or ("aipacs" in squashed)

    def _force_close_other_instances(self) -> int:
        """Force-kill every other AIPacs process tree. Returns trees killed.

        Kills only TOP-LEVEL candidates (a candidate whose parent is also a
        candidate dies with its parent's tree), never this process, never our
        ancestors or descendants. Other-user processes raise AccessDenied and
        are skipped silently.
        """
        try:
            import psutil
        except Exception:
            logger.warning("psutil unavailable — cannot sweep old instances.")
            return 0
        self_pid = os.getpid()
        protected = {self_pid}
        try:
            me = psutil.Process(self_pid)
            protected.update(a.pid for a in me.parents())
            protected.update(c.pid for c in me.children(recursive=True))
        except Exception:
            pass

        candidates = {}
        # PERF (2026-06-08): enumerate with ONLY the cheap "name" attribute first.
        # Asking psutil for "exe"/"cmdline"/"ppid" per process is a slow Windows
        # OpenProcess/PEB read — and "ppid" rebuilds the whole parent-map on every
        # call (O(n^2)).  Doing that for every process on a busy machine cost ~25 s
        # at startup, and this sweep runs on EVERY launch (the no-listener orphan
        # sweep, try_acquire step 4).  `_proc_is_aipacs` can only ever match a
        # process whose squashed name contains "aipacs" (frozen exe) or "python"
        # (source/worker run), so use the name as a cheap pre-filter and fetch the
        # expensive fields only for that handful.  Same matches, ~25 s -> <1 s.
        # Cheap (pid, name) enumeration first (Toolhelp on Windows; see
        # _iter_pid_name_cheap), name pre-filter, then the expensive exe/cmdline
        # only for the handful of aipacs/python candidates.
        for pid, name in _iter_pid_name_cheap():
            try:
                if pid in protected:
                    continue
                nm = (name or "").lower().replace(" ", "")
                if ("aipacs" not in nm) and ("python" not in nm):
                    continue  # cannot match _proc_is_aipacs — skip the slow fields
                try:
                    proc = psutil.Process(pid)
                except Exception:
                    continue
                try:
                    exe = proc.exe() or ""
                except Exception:
                    exe = ""
                try:
                    cmdline = proc.cmdline() or []
                except Exception:
                    cmdline = []
                cwd = ""
                # cwd lookup only when needed (relative "main.py" worker case)
                if any(str(p).lower().endswith("main.py") for p in cmdline):
                    try:
                        cwd = proc.cwd()
                    except Exception:
                        cwd = ""
                if self._proc_is_aipacs(name, exe, cmdline, cwd):
                    candidates[pid] = proc
            except Exception:
                continue

        killed = 0
        for pid, proc in candidates.items():
            try:
                if (proc.ppid() in candidates):
                    continue  # not top-level; dies with its parent's tree
                tree = [proc]
                try:
                    tree += proc.children(recursive=True)
                except Exception:
                    pass
                desc = f"PID {pid} ({(proc.name() or '?')})"
                for t in tree:
                    try:
                        t.terminate()
                    except Exception:
                        pass
                _, alive = psutil.wait_procs(tree, timeout=2.0)
                for t in alive:
                    try:
                        t.kill()
                    except Exception:
                        pass
                killed += 1
                logger.warning("Force-closed stale AIPacs instance %s "
                               "(+%d child process(es)).", desc, len(tree) - 1)
            except Exception as e:
                logger.debug("Could not close candidate PID %s: %s", pid, e)
        return killed

    def _initiate_shutdown(self) -> None:
        """Run on the OLD instance when a newer launch requests takeover."""
        logger.warning(
            "Received SHUTDOWN from a newer AIPacs launch — closing this instance."
        )
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                # Quit via the event loop so main.py's run-loop `finally`
                # performs the full clean shutdown (DB checkpoint, download-
                # subprocess termination, lock release, guarded hard-exit).
                QTimer.singleShot(0, app.quit)
                if os.environ.get("AIPACS_NO_HARD_EXIT", "") != "1":
                    # Failsafe: a modal dialog or stuck teardown must not
                    # block the takeover forever.
                    QTimer.singleShot(8000, lambda: os._exit(0))
                return
        except Exception:
            pass
        # Headless/no-QApplication context (cannot be a real user instance —
        # main.py creates QApplication before the lock): just release.
        self.release()

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
            if _SHUTDOWN_MSG in data:
                try:
                    conn.disconnectFromServer()
                except Exception:
                    pass
                self._initiate_shutdown()
                return
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
