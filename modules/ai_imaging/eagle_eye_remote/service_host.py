"""Independent Windows service supervision; no workstation or Qt initialization.

The SCM process owns a headless child and its descendants in a Windows Job Object.
The child cannot open its listener until ownership has been established. Shutdown
is cooperative first, then bounded by terminating only that owned process tree.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


SERVICE_NAME = 'AIPacsEagleEye'
READY = 'EAGLE_EYE_LISTENER_READY_V1'


def service_config(path):
    """Reject working-directory dependent paths in unattended deployments."""
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('The service configuration must use an absolute path.')
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    paths = [config.get('job_root'), *config.get('clients', {}).values()]
    paths.extend(config[k] for k in ('certificate', 'private_key', 'client_ca_file', 'ca_file') if config.get(k))
    paths.extend((config.get('local_client_tls') or {}).values())
    pacs = config.get('pacs', {})
    paths.extend(pacs[k] for k in ('database', 'ca_file', 'credential_file') if pacs.get(k))
    if config.get('slicer_executable'):
        paths.append(config['slicer_executable'])
    paths.extend(pacs.get('allowed_roots', []))
    paths.extend(m.get('server_root') for m in pacs.get('path_mappings', []))
    if any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
        raise ValueError('Service storage and credential paths must be absolute.')
    return config


def child_command(config_path):
    path = Path(config_path)
    if not path.is_absolute():
        raise ValueError('The service configuration must use an absolute path.')
    if getattr(sys, 'frozen', False):
        return [sys.executable, '--eagle-eye-service-child', str(path)]
    return [sys.executable, '-m', 'modules.ai_imaging.eagle_eye_remote.service_host', str(path)]


class Supervisor:
    """One owned server process with readiness acknowledgement and a stop budget."""

    def __init__(self, config_path, *, start_timeout=60, stop_timeout=20,
                 command=None, owner_factory=None):
        self.command = command if command is not None else child_command(config_path)
        self.config_path = config_path
        self.custom_command = command is not None
        self.start_timeout, self.stop_timeout = start_timeout, stop_timeout
        self.owner_factory = owner_factory
        self.process = None
        self.owner = None
        self.reader = None
        self.ready = threading.Event()

    def _read_status(self):
        # Drain bounded lines; never copy clinical output or credentials into SCM logs.
        try:
            while line := self.process.stdout.readline(256):
                if line.strip() == READY:
                    self.ready.set()
        except (OSError, ValueError):
            pass

    def start(self):
        if self.owner_factory is None:
            from .process_owner import ProcessJob
            self.owner_factory = ProcessJob
        self.owner = self.owner_factory()
        environment = {k: v for k, v in os.environ.items()
                       if not k.startswith(('PYTHON', 'QT_', 'AIPACS_EAGLE_EYE_'))}
        environment['PYTHONNOUSERSITE'] = '1'
        if not self.custom_command:
            config = service_config(self.config_path)
            if config.get('slicer_executable'):
                environment['AIPACS_ADVANCED_VIEWER_EXE'] = config['slicer_executable']
            for key in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
                environment[key] = str(config.get('worker_threads', 2))
        try:
            self.process = subprocess.Popen(self.command,
                cwd=Path(__file__).resolve().parents[3], env=environment,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', errors='replace', bufsize=1,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.owner.assign(self.process)
            self.reader = threading.Thread(target=self._read_status,
                                           name='EagleEyeServiceStatus', daemon=True)
            self.reader.start()
            self.process.stdin.write('start\n')
            self.process.stdin.flush()
        except BaseException:
            self.close()
            raise

    def run(self, stop, report):
        """Report only lifecycle states; heavy model readiness is a separate gate."""
        try:
            report('starting')
            self.start()
            deadline = time.monotonic() + self.start_timeout
            while not self.ready.is_set():
                if stop.wait(.1):
                    return self.stop(report)
                if self.process.poll() is not None:
                    raise RuntimeError('Eagle Eye service child failed during startup.')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Eagle Eye service startup timed out.')
                report('starting')
            if stop.is_set():
                return self.stop(report)
            if self.process.poll() is not None:
                raise RuntimeError('Eagle Eye service child exited during startup.')
            report('running')
            while not stop.wait(.2):
                if self.process.poll() is not None:
                    raise RuntimeError('Eagle Eye service child exited unexpectedly.')
            return self.stop(report)
        finally:
            self.close()

    def stop(self, report):
        report('stopping')
        try:
            self.process.stdin.write('stop\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            pass
        deadline = time.monotonic() + self.stop_timeout
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                self.process.wait(timeout=min(.2, max(.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                report('stopping')
        # False means the service had to terminate unfinished owned work.
        return self.process.poll() == 0

    def close(self):
        if self.owner is not None:
            self.owner.close()
            self.owner = None
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            if self.reader is not None:
                self.reader.join(timeout=2)
            for stream in (self.process.stdin, self.process.stdout):
                stream.close()


def serve_child(config_path):
    """Private pipe protocol; EOF requests stop if the parent disappears."""
    if sys.stdin.readline(32) != 'start\n':
        raise ValueError('The server child requires an owning service host.')
    # Initialize the native NumPy/DICOM runtime on the main thread before any
    # request/control threads start. First import from retrieval workers can
    # stall Windows DLL initialization and prevent new HTTP threads starting.
    # Import failures must fail startup, never advertise listener readiness.
    import pydicom  # noqa: F401

    from .server import create_server
    server, jobs = create_server(service_config(config_path))
    stop = threading.Event()

    def control():
        sys.stdin.readline(32)
        stop.set()

    threading.Thread(target=control, name='EagleEyeServiceControl', daemon=True).start()
    # A bounded request loop avoids shutdown()/serve_forever() start races.
    server.timeout = .2
    try:
        print(READY, flush=True)
        while not stop.is_set():
            server.handle_request()
    finally:
        server.server_close()
        jobs.close()


def run_windows_service(config_path):
    """Called only by SCM through the explicit server-edition command."""
    if os.name != 'nt':
        raise RuntimeError('The Eagle Eye Windows service requires Windows.')
    import servicemanager
    import win32service
    import win32serviceutil
    import logging
    from logging.handlers import RotatingFileHandler
    log_path = Path(config_path).parent.parent / 'logs' / 'service-lifecycle.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger('EagleEyeServiceLifecycle')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    sink = RotatingFileHandler(log_path, maxBytes=1024 * 1024, backupCount=3, encoding='utf-8')
    sink.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    logger.addHandler(sink)
    logger.info('dispatcher starting')

    class EagleEyeService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = 'AI-PACS Eagle Eye Server'
        _svc_description_ = 'Owns Eagle Eye analysis workers and authenticated result delivery.'

        def __init__(self, args):
            logger.info('service initialization')
            super().__init__(args)
            self.stop_requested = threading.Event()
            self.status_lock = threading.RLock()
            self.current_status = win32service.SERVICE_START_PENDING

        def report(self, state):
            with self.status_lock:
                if self.stop_requested.is_set():
                    state = win32service.SERVICE_STOP_PENDING
                self.current_status = state
                self.ReportServiceStatus(state, waitHint=30000)

        def SvcStop(self):
            with self.status_lock:
                self.stop_requested.set()
                self.report(win32service.SERVICE_STOP_PENDING)

        def SvcInterrogate(self):
            # The base class assumes RUNNING even while startup/stop is pending.
            with self.status_lock:
                self.report(self.current_status)

        def SvcShutdown(self):
            self.SvcStop()

        def SvcRun(self):
            # ServiceFramework's default SvcRun reports RUNNING too early.
            states = {'starting': win32service.SERVICE_START_PENDING,
                      'running': win32service.SERVICE_RUNNING,
                      'stopping': win32service.SERVICE_STOP_PENDING}

            def report(state):
                self.report(states[state])

            try:
                logger.info('supervisor starting')
                graceful = Supervisor(config_path).run(self.stop_requested, report)
                if not graceful:
                    servicemanager.LogWarningMsg('Eagle Eye stopped unfinished owned work after its shutdown budget.')
            except Exception as error:
                import traceback
                frames = [(Path(frame.filename).name, frame.lineno)
                          for frame in traceback.extract_tb(error.__traceback__)]
                logger.error('failure type=%s winerror=%s frames=%s',
                             type(error).__name__, getattr(error, 'winerror', None), frames)
                servicemanager.LogErrorMsg('Eagle Eye service failed. Check its configuration and qualified runtime.')
                # pywin32's C dispatcher reports STOPPED/nonzero on an exception.
                # Do not report STOPPED ourselves and let its later success overwrite it.
                raise RuntimeError('Eagle Eye service supervision failed.') from None
            self.report(win32service.SERVICE_STOP_PENDING)

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(EagleEyeService)
    servicemanager.StartServiceCtrlDispatcher()


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Supply one absolute service configuration path.')
    serve_child(sys.argv[1])
