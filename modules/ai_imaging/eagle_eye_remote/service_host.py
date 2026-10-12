"""Independent Windows service supervision; no workstation or Qt initialization.

The SCM process owns a headless child and its descendants in a Windows Job Object.
The child cannot open its listener until ownership has been established. Shutdown
is cooperative first, then bounded by terminating only that owned process tree.
"""
import json
import queue
import re
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


SERVICE_NAME = 'AIPacsEagleEye'
READY = 'EAGLE_EYE_LISTENER_READY_V1'
TRANSITION = 'EAGLE_EYE_TRANSITION_V1 '
ADMISSION_READY = 'EAGLE_EYE_ADMISSION_READY_V1'
HEALTH_READY = 'EAGLE_EYE_HEALTH_READY_V1'
PROGRESS = 'EAGLE_EYE_LOOP_PROGRESS_V1'
DIAGNOSTICS = 'EAGLE_EYE_TRANSPORT_DIAGNOSTICS_V1 '


def diagnostic_command(line, counters):
    """Read-only owning-parent request; transition commands stay separate."""
    if len(line.encode('utf-8')) > 512:
        raise ValueError('Invalid private diagnostic command.')
    value = json.loads(line)
    if (not isinstance(value, dict) or set(value) != {'protocol', 'operation', 'request_id'}
            or type(value['protocol']) is not int or value['protocol'] != 1
            or value['operation'] != 'transport_diagnostics'
            or not isinstance(value['request_id'], str)
            or re.fullmatch('[a-f0-9]{32}', value['request_id']) is None):
        raise ValueError('Invalid private diagnostic command.')
    return {'protocol':1, 'request_id':value['request_id'], 'snapshot':counters.snapshot()}


def transition_command(line, admission, stop):
    """Owning-parent pipe only; no HTTP endpoint and no arbitrary payload echo."""
    from .admission import budget
    if len(line.encode('utf-8')) > 512:
        raise ValueError('Invalid private transition command.')
    value = json.loads(line)
    if (not isinstance(value, dict) or set(value) != {'protocol','operation','request_id','timeout'}
            or type(value['protocol']) is not int or value['protocol'] != 1
            or value['operation'] != 'stop_when_idle'
            or not isinstance(value['request_id'], str)
            or re.fullmatch('[a-f0-9]{32}', value['request_id']) is None):
        raise ValueError('Invalid private transition command.')
    timeout = budget(value['timeout'])
    # A first-install barrier already holds certain zero-work admission closed.
    # Commit still rechecks that state atomically against a concurrent release.
    held = admission.snapshot()['state'] == 'quiesced'
    committed = (held or admission.drain(timeout)) and admission.commit(stop.set)
    return {'protocol':1, 'request_id':value['request_id'],
            'result':'committed' if committed else 'aborted', **admission.snapshot()}


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
    if config.get('license_directory'):
        paths.append(config['license_directory'])
    if config.get('echomind'):
        paths.append(config['echomind'].get('config_dir'))
    paths.extend(pacs.get('allowed_roots', []))
    paths.extend(m.get('server_root') for m in pacs.get('path_mappings', []))
    if any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths):
        raise ValueError('Service storage and credential paths must be absolute.')
    return config


def child_command(config_path):
    path = Path(config_path)
    if not path.is_absolute():
        raise ValueError('The service configuration must use an absolute path.')
    from aipacs_runtime import is_frozen
    if is_frozen():
        return [sys.executable, '--eagle-eye-service-child', str(path)]
    return [sys.executable, '-m', 'modules.ai_imaging.eagle_eye_remote.service_host', str(path)]


def await_private_receipt(control, emergency_stop, warning):
    """Retain uncertain cooperative work unless an explicit SCM stop arrives."""
    next_warning = time.monotonic() + 125
    while not emergency_stop.is_set():
        if control.wait(1):
            return
        if time.monotonic() >= next_warning:
            warning('Private drain completion remains unknown; retaining owned resources.')
            next_warning = time.monotonic() + 125


class Supervisor:
    """One owned server process with readiness acknowledgement and a stop budget."""

    def __init__(self, config_path, *, start_timeout=60, stop_timeout=20,
                 command=None, owner_factory=None, health_timeout=60):
        from .admission import budget
        self.health_timeout = budget(health_timeout)
        self.command = command if command is not None else child_command(config_path)
        self.config_path = config_path
        self.custom_command = command is not None
        self.start_timeout, self.stop_timeout = start_timeout, stop_timeout
        self.owner_factory = owner_factory
        self.process = None
        self.owner = None
        self.reader = None
        self.stop_sender = None
        self.ready = threading.Event()
        self.admission_ready = threading.Event()
        self.transitions = queue.Queue(maxsize=8)
        self.diagnostics = queue.Queue(maxsize=8)
        self.control_lock = threading.Lock()
        self.transition_requested = threading.Event()
        self.health_ready = threading.Event()
        self.certified_idle = threading.Event()
        self.health_recovery_requested = threading.Event()
        self.last_progress = time.monotonic()
        self.next_health_probe = 0

    def _read_status(self):
        # Drain bounded lines; never copy clinical output or credentials into SCM logs.
        try:
            while line := self.process.stdout.readline(4097):
                if not line.endswith('\n'):
                    while line and not line.endswith('\n'):
                        line = self.process.stdout.readline(4097)
                    continue
                if line.startswith(DIAGNOSTICS):
                    try:
                        from .transport_diagnostics import valid_snapshot
                        value = json.loads(line[len(DIAGNOSTICS):])
                        if (len(line.encode('utf-8')) <= 4096 and isinstance(value, dict)
                                and set(value) == {'protocol','request_id','snapshot'}
                                and type(value['protocol']) is int and value['protocol'] == 1
                                and isinstance(value['request_id'], str)
                                and re.fullmatch('[a-f0-9]{32}', value['request_id'])
                                and valid_snapshot(value['snapshot'])):
                            self.diagnostics.put_nowait(value)
                    except (ValueError, TypeError, queue.Full):
                        pass
                    continue
                if len(line.encode('utf-8')) > 512:
                    continue
                if line.strip() == READY:
                    self.ready.set()
                elif line.strip() == ADMISSION_READY:
                    self.admission_ready.set()
                elif line.strip() in (HEALTH_READY, PROGRESS):
                    self.last_progress = time.monotonic()
                    if line.strip() == HEALTH_READY:
                        self.health_ready.set()
                elif line.startswith(TRANSITION):
                    try:
                        value = json.loads(line[len(TRANSITION):])
                        if (isinstance(value, dict) and type(value.get('protocol')) is int and value.get('protocol') == 1
                                and value.get('result') in ('committed','aborted')
                                and re.fullmatch('[a-f0-9]{32}', value.get('request_id',''))):
                            self.transitions.put_nowait(value)
                    except (ValueError, TypeError, queue.Full):
                        pass
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

    def run(self, stop, report, *, before_close=None):
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
                    if (self.transition_requested.is_set() and self.process.returncode == 0
                            and not self.health_recovery_requested.is_set()):
                        return True
                    raise RuntimeError('Eagle Eye service child exited unexpectedly.')
                self.check_health()
            return self.stop(report)
        finally:
            if before_close is not None and not stop.is_set():
                before_close()
            self.close()

    def check_health(self):
        """Recover a stalled loop only with a fresh closed/zero-work certificate.

        A missing heartbeat is never proof of idle. Busy, poisoned or unreachable
        control stays alive for inspection; there is no stale-counter kill path.
        """
        now = time.monotonic()
        if (self.transition_requested.is_set() or not self.health_ready.is_set() or now < self.next_health_probe
                or now - self.last_progress <= self.health_timeout):
            return
        import logging
        self.next_health_probe = now + self.health_timeout
        try:
            if self.safe_transition(min(self.stop_timeout, 20), health_recovery=True):
                raise RuntimeError('Stalled Eagle Eye loop drained; service recovery required.')
            if self.transition_requested.is_set():
                return  # Another private owner won arbitration; do not claim it.
            self.health_recovery_requested.clear()
        except (TimeoutError, RuntimeError):
            if self.health_recovery_requested.is_set() and self.certified_idle.is_set():
                # Admission is permanently closed and every accepted operation
                # has completed. Only this owned, certified-empty tree may close.
                raise RuntimeError('Stalled Eagle Eye loop certified idle; service recovery required.') from None
        logging.getLogger('EagleEyeServiceLifecycle').warning(
            'Listener progress unavailable; accepted work could not certify safe recovery. No forced restart.')

    def stop(self, report):
        report('stopping')
        # SCM stop is the explicitly authorized emergency path. A full private
        # pipe must not prevent its owned Job from closing after the budget.
        process = self.process
        def notify():
            try:
                process.stdin.write('stop\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
        self.stop_sender = threading.Thread(target=notify, name='EagleEyeEmergencyStop', daemon=True)
        self.stop_sender.start()
        deadline = time.monotonic() + self.stop_timeout
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                self.process.wait(timeout=min(.2, max(.001, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                report('stopping')
        # False means the service had to terminate unfinished owned work.
        return self.process.poll() == 0

    def safe_transition(self, timeout=20, *, health_recovery=False):
        """Private owning-process API. Timeout never invokes stop/kill/close.

        External SCM stop remains an emergency path, not this transition API.
        A missing acknowledgement is indeterminate and requires inspection.
        """
        from uuid import uuid4
        from .admission import budget
        timeout = budget(timeout)
        lock_deadline = time.monotonic() + timeout
        if not self.control_lock.acquire(timeout=timeout):
            raise TimeoutError('Private transition control is busy; do not force stop.')
        try:
            if self.transition_requested.is_set():
                if health_recovery:
                    return False  # Never reclassify a private or uncertain owner.
                raise RuntimeError('An existing private transition requires completion review.')
            timeout = lock_deadline - time.monotonic()
            if timeout <= 0:
                raise TimeoutError('Private transition deadline expired; do not force stop.')
            if (self.process is None or self.process.poll() is not None
                    or not self.ready.is_set() or not self.admission_ready.is_set()):
                raise RuntimeError('No ready owned child can certify a transition.')
            rid = uuid4().hex
            self.certified_idle.clear()
            if health_recovery:
                self.health_recovery_requested.set()
            else:
                self.health_recovery_requested.clear()
            self.transition_requested.set()
            try:
                self.process.stdin.write(json.dumps({'protocol':1, 'operation':'stop_when_idle',
                    'request_id':rid, 'timeout':timeout}, separators=(',',':')) + '\n')
                self.process.stdin.flush()
                deadline = time.monotonic() + timeout + 2
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Private transition acknowledgement is unavailable; do not force stop.')
                    try:
                        result = self.transitions.get(timeout=remaining)
                    except queue.Empty:
                        raise TimeoutError('Private transition acknowledgement is unavailable; do not force stop.') from None
                    if result['request_id'] == rid:
                        if result['result'] == 'aborted':
                            self.transition_requested.clear()
                            return False
                        if (result.get('state') != 'closed' or type(result.get('inflight')) is not int or result.get('inflight') != 0
                                or result.get('completion_uncertain') is not False):
                            raise RuntimeError('Private transition receipt does not certify zero work.')
                        self.certified_idle.set()
                        try:
                            code = self.process.wait(timeout=self.stop_timeout)
                        except subprocess.TimeoutExpired:
                            raise TimeoutError('Cooperative close is incomplete; do not force stop.') from None
                        if code != 0:
                            raise RuntimeError('Owned child did not complete cooperative close.')
                        return True
            except TimeoutError:
                raise
            except (OSError, ValueError):
                # A lost pipe is not evidence of a successful drain.
                raise RuntimeError('Private transition control is unavailable; inspect owned state.') from None
        finally:
            self.control_lock.release()

    def transport_diagnostics(self, timeout=2):
        """Bounded read-only private request; never drains or stops the child."""
        from uuid import uuid4
        if type(timeout) not in (int, float) or not 0 < timeout <= 5:
            raise ValueError('Invalid private diagnostic timeout.')
        deadline = time.monotonic() + timeout
        if not self.control_lock.acquire(timeout=timeout):
            raise TimeoutError('Private diagnostic control is busy.')
        try:
            if self.process is None or self.process.poll() is not None or not self.ready.is_set():
                raise RuntimeError('No ready owned child can provide diagnostics.')
            rid = uuid4().hex
            self.process.stdin.write(json.dumps({'protocol':1,'operation':'transport_diagnostics',
                                                 'request_id':rid}, separators=(',',':')) + '\n')
            self.process.stdin.flush()
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Private diagnostic acknowledgement is unavailable.')
                try:
                    result = self.diagnostics.get(timeout=remaining)
                except queue.Empty:
                    raise TimeoutError('Private diagnostic acknowledgement is unavailable.') from None
                if result['request_id'] == rid:
                    return result['snapshot']
        except TimeoutError:
            raise
        except (OSError, ValueError):
            raise RuntimeError('Private diagnostic control is unavailable.') from None
        finally:
            self.control_lock.release()

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
                if stream is self.process.stdin and self.stop_sender is not None and self.stop_sender.is_alive():
                    # Closing a buffered stream held by a blocked writer would
                    # reacquire its lock. Host exit releases this old handle.
                    continue
                if stream is self.process.stdout and self.reader is not None and self.reader.is_alive():
                    continue
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
        while True:
            line = sys.stdin.readline(513)
            if line in ('', 'stop\n'):
                stop.set()  # Legacy emergency/parent-loss behavior, not a safe transition.
                return
            try:
                envelope = json.loads(line)
                if isinstance(envelope, dict) and envelope.get('operation') == 'transport_diagnostics':
                    result = diagnostic_command(line, server.transport_diagnostics)
                    frame = DIAGNOSTICS + json.dumps(result, separators=(',',':')) + '\n'
                    if len(frame.encode('utf-8')) > 4096:
                        raise ValueError('Private diagnostic frame exceeds its budget.')
                    print(frame, end='', flush=True)
                    continue
                result = transition_command(line, jobs.admission, stop)
            except (ValueError, RuntimeError):
                result = {'protocol':1, 'result':'invalid'}
            print(TRANSITION + json.dumps(result, separators=(',',':')), flush=True)
            if stop.is_set():
                return

    threading.Thread(target=control, name='EagleEyeServiceControl', daemon=True).start()
    # A bounded request loop avoids shutdown()/serve_forever() start races.
    server.timeout = .2
    try:
        jobs.start_installation_barrier()
        jobs.start_native_secretary()
        print(ADMISSION_READY, flush=True)
        print(HEALTH_READY, flush=True)
        print(READY, flush=True)
        next_progress = time.monotonic()
        while not stop.is_set():
            server.handle_request()
            if time.monotonic() >= next_progress:
                print(PROGRESS, flush=True)
                next_progress = time.monotonic() + 5
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
            self.private_control = None

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

        def SvcOther(self, control):
            if self.private_control is not None:
                self.private_control.handle_control(control)

        def SvcOtherEx(self, control, event_type, data):
            self.SvcOther(control)
            return 0

        def SvcRun(self):
            # ServiceFramework's default SvcRun reports RUNNING too early.
            states = {'starting': win32service.SERVICE_START_PENDING,
                      'running': win32service.SERVICE_RUNNING,
                      'stopping': win32service.SERVICE_STOP_PENDING}

            def report(state):
                self.report(states[state])

            try:
                logger.info('supervisor starting')
                from .service_control import ServiceControlHost, live_identity
                supervisor = Supervisor(config_path)

                def cooperative_transition(remaining):
                    # Reserve acknowledgment, child exit and receipt persistence.
                    reserved = supervisor.stop_timeout + 4
                    if remaining <= reserved:
                        return False
                    return supervisor.safe_transition(remaining - reserved)

                self.private_control = ServiceControlHost(config_path,
                    lambda: live_identity(config_path), cooperative_transition,
                    supervisor.transport_diagnostics)

                def wait_private_receipt():
                    # Normal callback lifetime is bounded by the private deadline.
                    # An abnormal hung callback is unknown: retain service/Job for
                    # inspection instead of closing beneath accepted native work.
                    await_private_receipt(self.private_control, self.stop_requested, logger.warning)

                graceful = supervisor.run(self.stop_requested, report,
                    before_close=wait_private_receipt)
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
