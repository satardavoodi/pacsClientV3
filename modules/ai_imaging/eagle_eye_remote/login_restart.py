"""OS-authorized, fixed-service recovery after one successful Server GUI login.

This intentionally may cancel accepted Eagle work. It never replays requests,
changes SCM configuration, grants rights, or terminates an arbitrary process.
"""
import os
from pathlib import Path
import subprocess
import threading
import time

_ENTRY_LOCK = threading.Lock()
_ENTRY_CONSUMED = set()


class LoginRestart:
    def __init__(self, adapter):
        self.adapter = adapter
        self._consumed = set()
        self._lock = threading.Lock()

    def run(self, operation):
        if not isinstance(operation, str) or not operation:
            raise ValueError("A successful login operation is required")
        with self._lock:
            if operation in self._consumed:
                raise RuntimeError("This login recovery was already consumed")
            self._consumed.add(operation)
            old = self.adapter.inspect()
            if not old.get("owned"):
                raise RuntimeError("The fixed Eagle service is not the reviewed target")
            deadline = time.monotonic() + 90
            self.adapter.stop()
            self.adapter.wait_stopped(deadline)
            self.adapter.start()
            self.adapter.wait_ready(deadline)
            current = self.adapter.inspect()
            if (not current.get("owned") or not current.get("running")
                    or current.get("generation") == old.get("generation")):
                raise RuntimeError("A new owned Eagle service generation was not verified")
            return {"generation": current["generation"], "service_restarted": True}


class WindowsService:
    def __init__(self, config_path):
        import win32service as scm
        from .service_host import SERVICE_NAME, service_config
        from .secretary_native_connector import read_source_target
        from .service_admin import service_command
        from aipacs_runtime import is_frozen
        self.scm = scm
        self.config_path = str(Path(config_path).resolve())
        if service_config(self.config_path).get("service_managed") is not True:
            raise ValueError("Only the managed Eagle service can recover")
        self.source = Path(__file__).resolve().parents[3]
        self.target = None if is_frozen() else read_source_target(self.config_path, self.source)
        self.expected = (service_command(self.config_path) if self.target is None else
            subprocess.list2cmdline([self.target["runtime_executable"],
                str(self.source / "tools/eagle_eye/windows_service.py"), self.config_path]))
        self.manager = scm.OpenSCManager(None, None, scm.SC_MANAGER_CONNECT)
        self.handle = None
        try:
            self.handle = scm.OpenService(self.manager, SERVICE_NAME,
                scm.SERVICE_QUERY_CONFIG | scm.SERVICE_QUERY_STATUS | scm.SERVICE_START | scm.SERVICE_STOP)
        except Exception:
            scm.CloseServiceHandle(self.manager)
            raise

    def close(self):
        self.scm.CloseServiceHandle(self.handle)
        self.scm.CloseServiceHandle(self.manager)

    def inspect(self):
        import psutil
        from .secretary_native_connector import read_source_target
        c = self.scm.QueryServiceConfig(self.handle)
        s = self.scm.QueryServiceStatusEx(self.handle)
        owned = c[3] == self.expected and c[7].casefold() == "nt authority\\localservice"
        if self.target is not None:
            owned = owned and read_source_target(self.config_path, self.source) == self.target
        pid = s["ProcessId"]
        return {"owned":owned,"running":s["CurrentState"] == self.scm.SERVICE_RUNNING,
                "generation":(pid, psutil.Process(pid).create_time()) if pid else None}

    def stop(self):
        if not self.inspect()["owned"]:
            raise RuntimeError("Eagle ownership changed before stop")
        if self.scm.QueryServiceStatusEx(self.handle)["CurrentState"] != self.scm.SERVICE_STOPPED:
            self.scm.ControlService(self.handle, self.scm.SERVICE_CONTROL_STOP)

    def _wait(self, wanted, deadline):
        while time.monotonic() < deadline:
            if self.scm.QueryServiceStatusEx(self.handle)["CurrentState"] == wanted:
                return
            time.sleep(.1)
        raise TimeoutError("The owned Eagle service did not complete recovery")

    def wait_stopped(self, deadline): self._wait(self.scm.SERVICE_STOPPED, deadline)

    def start(self):
        if not self.inspect()["owned"]:
            raise RuntimeError("Eagle ownership changed before start")
        self.scm.StartService(self.handle, None)

    def wait_ready(self, deadline): self._wait(self.scm.SERVICE_RUNNING, deadline)


def recover_after_login(operation):
    """Worker entry; invocation is guarded by accepted console login in the GUI."""
    adapter = None
    try:
        with _ENTRY_LOCK:
            if not isinstance(operation, str) or not operation or operation in _ENTRY_CONSUMED:
                raise ValueError("The login recovery operation was already consumed")
            _ENTRY_CONSUMED.add(operation)
        if os.environ.get("AIPACS_EAGLE_EYE_ROLE") != "server":
            raise ValueError("Only the Server console can invoke this workflow")
        adapter = WindowsService(os.environ["AIPACS_EAGLE_EYE_SERVER_CONFIG"])
        return LoginRestart(adapter).run(operation)
    except Exception:
        return {"service_restarted": False, "error_code": "EAGLE_LOGIN_RECOVERY_FAILED"}
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass  # Handle cleanup cannot schedule a second recovery or stale GUI callback.
