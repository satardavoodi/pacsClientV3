"""Asynchronous, session-owned Slicer runtimes. No Qt/VTK imports in this module."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import uuid

LOGGER = logging.getLogger(__name__)
MAX_MESSAGE = 65536


class OperationRejected(RuntimeError):
    """A definitive rejection must not destroy the user's current viewer scene."""


def resident_enabled():
    return os.environ.get("AIPACS_SLICER_RESIDENT", "1").lower() not in {"0", "false", "off"}


class LocalRuntime:
    def __init__(self, role, *, executable=None, diagnostic_log=None):
        self.role = role
        self.executable = executable
        self.process = None
        self.job = None
        self.root = None
        self.connection = None
        self.token = secrets.token_hex(32)
        self.diagnostic_log = diagnostic_log
        self._log = None

    def start(self):
        from .slicer_custom_app import launch_slicer
        from .owned_process import ProcessJob
        from aipacs_runtime import advanced_mpr_runtime_root, is_frozen
        exe = Path(self.executable) if self.executable else launch_slicer.find_slicer_executable()
        if exe is None or not exe.is_file():
            raise RuntimeError("Advanced Analysis runtime is unavailable")
        if is_frozen():
            runtime_python = advanced_mpr_runtime_root() / "python/modules/mpr/advanced_3d_slicer"
            module_path = runtime_python / "slicer_modules"
            startup_script = runtime_python / "slicer_custom_app/startup_script.py"
        else:
            module_path = Path(__file__).parent / "slicer_modules"
            startup_script = Path(launch_slicer.__file__).with_name("startup_script.py")
        if not (module_path / "AIPacsBackgroundRuntime.py").is_file():
            raise RuntimeError("Advanced Analysis background window guard is unavailable")
        if self.role == "viewer" and (
            not startup_script.is_file() or not startup_script.with_name("presentation.py").is_file()
        ):
            raise RuntimeError("Advanced Analysis presentation is incomplete")
        root = Path(tempfile.mkdtemp(prefix="aipacs-resident-"))
        self.root = root
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("PYTHON", "NEWMPR2_", "QT_"))}
        bundle = exe.parent / "offline_lumbar"
        if not bundle.exists():
            for ancestor in Path(__file__).resolve().parents:
                if (ancestor / ".git").exists():
                    bundle = ancestor / "generated-files/offline-lumbar/bundle"
                    break
        env.update(AIPACS_RESIDENT_ROOT=str(root), AIPACS_RESIDENT_TOKEN=self.token,
                   AIPACS_RESIDENT_ROLE=self.role, AIPACS_OFFLINE_LUMBAR_ROOT=str(bundle),
                   AIPACS_RESIDENT_PARENT=str(os.getpid()),
                   AIPACS_RESIDENT_STARTUP=str(startup_script))
        from modules.ai_imaging.eagle_eye_remote.settings import slicer_environment
        env.update(slicer_environment())
        command = [str(exe), "--no-splash", "--launcher-no-splash", "--disable-settings",
                   "--ignore-slicerrc", "--launcher-ignore-user-additional-settings",
                   "--additional-module-path", str(module_path)]
        if self.role == "analysis":
            command.append("--no-main-window")
        self.job = ProcessJob()
        try:
            if self.diagnostic_log:
                self._log = Path(self.diagnostic_log).open("w", encoding="utf-8")
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            self.process = subprocess.Popen(command, cwd=root, env=env, startupinfo=startup,
                                            stdout=self._log or subprocess.DEVNULL,
                                            stderr=self._log or subprocess.DEVNULL,
                                            creationflags=subprocess.CREATE_NO_WINDOW |
                                            subprocess.BELOW_NORMAL_PRIORITY_CLASS)
            self.job.assign(self.process)
        except Exception:
            if self.process is not None and self.process.poll() is None:
                self.process.kill()
            self.close()
            raise

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def ready(self):
        if not self.alive():
            raise RuntimeError("Advanced Analysis exited before becoming ready")
        path = self.root / "ready.json"
        if not path.exists():
            return False
        connection = json.loads(path.read_text(encoding="utf-8"))
        if connection.get("role") != self.role or connection.get("protocol") != 1:
            raise RuntimeError("Unexpected runtime readiness contract")
        self.connection = connection
        response = self.exchange({"operation": "ping"})
        return response.get("ready") is True and response.get("role") == self.role

    def exchange(self, message):
        request = dict(message, token=self.token)
        data = (json.dumps(request) + "\n").encode()
        if len(data) > MAX_MESSAGE:
            raise ValueError("Advanced Analysis request is too large")
        with socket.create_connection(("127.0.0.1", self.connection["port"]), timeout=2) as stream:
            stream.sendall(data)
            response = bytearray()
            while b"\n" not in response:
                part = stream.recv(min(4096, MAX_MESSAGE + 1 - len(response)))
                if not part:
                    raise ConnectionError("Runtime returned an incomplete response")
                response.extend(part)
                if len(response) > MAX_MESSAGE:
                    raise ValueError("Runtime response is too large")
        result = json.loads(response.split(b"\n", 1)[0])
        if not result.get("ok"):
            raise OperationRejected(result.get("error", "Runtime rejected request"))
        return result

    def command(self, operation, parameters, stop, timeout):
        request_id = uuid.uuid4().hex
        self.exchange({"operation": "submit", "id": request_id,
                       "command": operation, "parameters": parameters})
        deadline = time.monotonic() + timeout
        while not stop.wait(0.05):
            if not self.alive():
                raise RuntimeError("Advanced Analysis process exited")
            result = self.exchange({"operation": "result", "id": request_id})
            if result["state"] == "succeeded":
                return result["result"]
            if result["state"] == "failed":
                raise OperationRejected(result.get("error", "Advanced Analysis command failed"))
            if time.monotonic() >= deadline:
                # A viewer may contain unsaved work: keep it available for manual recovery.
                if self.role == "analysis":
                    self.close()
                raise TimeoutError("Advanced Analysis command timed out")
        raise RuntimeError("Advanced Analysis is stopping")

    def close(self):
        if self.job:
            self.job.close()
        if self.process:
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                LOGGER.error("Owned Advanced Analysis process did not stop within cleanup deadline")
        if self.root:
            (self.root / "ready.json").unlink(missing_ok=True)
        self.connection = None
        if self._log:
            self._log.close()


class ResidentService:
    """One bounded serial worker per role; methods return Futures immediately."""
    def __init__(self, role="viewer", *, backend_factory=None, startup_timeout=120):
        if role not in {"viewer", "analysis"}:
            raise ValueError("Unsupported runtime role")
        self.role = role
        self._factory = backend_factory or (lambda: LocalRuntime(role))
        self._runtime = None
        self._stop = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="Slicer-" + role)
        self._slots = threading.BoundedSemaphore(4)
        self._state = "stopped"
        self._startup_timeout = startup_timeout
        self._warm_future = None
        self._lock = threading.Lock()

    @property
    def state(self):
        return self._state

    def _ensure_ready(self):
        if self._stop.is_set():
            raise RuntimeError("Advanced Analysis service is stopped")
        if self._runtime and self._runtime.alive() and self._state == "ready":
            return self._runtime
        if self._runtime and self._runtime.alive() and self._state == "uncertain":
            raise RuntimeError("Advanced Analysis did not confirm completion; close its preserved window before retrying")
        if self._runtime:
            self._runtime.close()
        self._state = "starting"
        runtime = self._factory()
        self._runtime = runtime
        started = time.monotonic()
        try:
            runtime.start()
            while not self._stop.is_set():
                if runtime.ready():
                    self._state = "ready"
                    LOGGER.info("Advanced Analysis %s ready in %.3f seconds", self.role, time.monotonic() - started)
                    return runtime
                if time.monotonic() - started > self._startup_timeout:
                    raise TimeoutError("Advanced Analysis startup timed out")
                self._stop.wait(0.05)
            raise RuntimeError("Advanced Analysis startup cancelled")
        except Exception:
            self._state = "failed" if not self._stop.is_set() else "stopped"
            runtime.close()
            raise

    def _submit(self, function):
        if self._stop.is_set() or not self._slots.acquire(blocking=False):
            raise RuntimeError("Advanced Analysis service is stopped or its queue is full")
        try:
            future = self._executor.submit(function)
        except Exception:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        return future

    def warmup(self):
        with self._lock:
            if self._warm_future is None or self._warm_future.done():
                self._warm_future = self._submit(lambda: self._ensure_ready().connection)
            return self._warm_future

    def request(self, operation, parameters=None, *, timeout=120):
        def execute():
            runtime = self._ensure_ready()
            try:
                return runtime.command(operation, parameters or {}, self._stop, timeout)
            except OperationRejected:
                raise
            except Exception:
                if self.role == "viewer" and runtime.alive():
                    self._state = "uncertain"
                else:
                    self._state = "failed"
                    runtime.close()
                raise
        return self._submit(execute)

    def analyze_snapshot(self, array_kji, affine_ras, *, algorithm="vertebrae_mr", lower=None, upper=None, source_reference=None):
        if self.role != "analysis":
            raise ValueError("AI jobs require a separate analysis runtime")
        import numpy as np
        # The caller owns snapshot creation. Require the documented immutable trunk
        # contract so no large copy or file staging occurs on the calling Qt thread.
        if not isinstance(array_kji, np.ndarray) or array_kji.flags.writeable:
            raise ValueError("Supply a read-only NumPy snapshot owned by the caller")
        array = array_kji
        affine = np.asarray(affine_ras, dtype=float).copy()
        if (array.ndim != 3 or not array.size or array.dtype.kind not in "iuf"
                or array.size > 256 * 1024 * 1024 or array.nbytes > 1024**3 or affine.shape != (4, 4)):
            raise ValueError("Invalid snapshot dimensions")
        if algorithm not in {"threshold", "vertebrae_mr"}:
            raise ValueError("Unsupported analysis algorithm")
        def execute():
            from modules.ai_imaging.eagle_eye_remote.settings import remote_required
            if algorithm == 'vertebrae_mr' and remote_required():
                if not source_reference:
                    raise ValueError('Remote AI requires the selected DICOM study and series references.')
                from modules.ai_imaging.eagle_eye_remote.client import Client
                from PacsClient.utils.data_paths import AI_DIR
                result = Client().analyze('lumbar', source_reference['study_uid'],
                    {'primary': source_reference['primary']}, {}, Path(AI_DIR) / 'eagle_eye', cancel=self._stop)
                if result['shape_kji'] != list(array.shape) or not np.allclose(result['affine_ras'], affine, atol=1e-4):
                    raise ValueError('Server mask geometry differs from the selected source.')
                return result
            runtime = self._ensure_ready()
            job_id = uuid.uuid4().hex
            directory = runtime.root / "jobs" / job_id
            directory.mkdir(parents=True)
            try:
                np.save(directory / "input.npy", array, allow_pickle=False)
                (directory / "input.json").write_text(json.dumps({"affine_ras": affine.tolist()}), encoding="utf-8")
                return runtime.command("analyze", {"job_id": job_id, "algorithm": algorithm,
                                                    "lower": lower, "upper": upper}, self._stop, 1800)
            finally:
                (directory / "input.npy").unlink(missing_ok=True)
        return self._submit(execute)

    def wait_until_closed(self):
        """Blocking launcher-worker wait; never call from the Qt GUI or role executor."""
        runtime = self._runtime
        if runtime is None:
            return 0
        while not self._stop.wait(0.2) and runtime.alive():
            pass
        if self._runtime is runtime and self._state == "ready":
            self._state = "stopped"
        if runtime.process is not None:
            return runtime.process.poll() or 0
        return 0

    def stop(self):
        self._stop.set()
        self._state = "stopped"
        self._executor.shutdown(wait=False, cancel_futures=True)
        def close():
            if self._runtime:
                self._runtime.close()
        threading.Thread(target=close, name="Slicer-owned-cleanup", daemon=True).start()


_SERVICES = {}
_SERVICES_LOCK = threading.Lock()
_SHUTTING_DOWN = False


def get_service(role="viewer"):
    with _SERVICES_LOCK:
        if _SHUTTING_DOWN:
            raise RuntimeError("Advanced Analysis is shutting down")
        if role not in _SERVICES:
            _SERVICES[role] = ResidentService(role)
        return _SERVICES[role]


def stop_services():
    global _SHUTTING_DOWN
    with _SERVICES_LOCK:
        _SHUTTING_DOWN = True
        for service in _SERVICES.values():
            service.stop()
