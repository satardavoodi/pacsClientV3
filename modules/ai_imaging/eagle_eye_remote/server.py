"""Bounded authenticated job service. Start explicitly on the Eagle Eye server."""
from concurrent.futures import ThreadPoolExecutor
import hmac
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
import sys
import threading
import time
import uuid


def public_user(user):
    """Project SQLite grants into the public JSON schema without altering authority."""
    result = dict(user)
    for field in ('enabled', 'echomind', 'imaging', 'crm', 'secretary'):
        value = user.get(field)
        result[field] = type(value) in (int, bool) and value == 1
    return result


class HumanOwnerSlots(dict):
    """Bounded lock stripes for verified principal owners; no anonymous growth."""
    def __init__(self, existing):
        super().__init__(existing)
        self.stripes = [threading.BoundedSemaphore(1) for _ in range(64)]

    def __contains__(self, key):
        return super().__contains__(key) or isinstance(key, str) and re.fullmatch(r'human:[a-f0-9]{64}', key) is not None

    def __missing__(self, key):
        if key not in self:
            raise KeyError(key)
        return self.stripes[int(key[6:14], 16) % len(self.stripes)]


class HumanCenterMemberships(dict):
    """Only request owners derived from this center's verified authority qualify."""
    def __init__(self, existing, center):
        super().__init__(existing)
        self.center = center
        self.lock = threading.Lock()

    def admit(self, key):
        with self.lock:
            if key not in self and len(self) >= 4096:
                raise BlockingIOError('Human center membership limit reached')
            self[key] = self.center

    def get(self, key, default=None):
        return super().get(key, default)

    def items(self):
        with self.lock:
            return tuple(super().items())


class HumanHTTPServer(ThreadingHTTPServer):
    """Select HTTP/TLS in bounded workers, never in the listener accept loop."""
    tls_context = None
    def __init__(self, *args, **kwargs):
        from .transport_diagnostics import Counters
        self.transport_diagnostics = Counters()
        self.connection_slots = threading.BoundedSemaphore(64)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.connection_slots.acquire(False):
            self.transport_diagnostics.increment('connection_capacity_refused')
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self.connection_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            request.settimeout(5)
            first = request.recv(1, socket.MSG_PEEK)
            if not first:
                self.transport_diagnostics.increment('peer_closed_before_preface')
                return
            if first == b'\x16':
                if self.tls_context is None:
                    self.transport_diagnostics.increment('tls_unavailable')
                    return
                try:
                    request = self.tls_context.wrap_socket(request, server_side=True)
                except (OSError, ssl.SSLError):
                    self.transport_diagnostics.increment('tls_handshake_failed')
                    return
            elif first not in b'GPHDOCT':
                self.transport_diagnostics.increment('invalid_preface')
                return
            self.transport_diagnostics.increment('handler_started')
            super().process_request_thread(request, client_address)
        except TimeoutError:
            self.transport_diagnostics.increment('first_byte_timeout')
        except (OSError, ssl.SSLError):
            self.transport_diagnostics.increment('first_byte_read_failed')
        finally:
            request.close()
            self.connection_slots.release()

from .contracts import MODULES, validate, fingerprint, digest
from .source import PacsSource, SourceLease
from .artifacts import publish
from .scheduling import Resources
from .reviews import RevisionConflict
from .admission import Admission, Quiesced, CompletionUncertain


class QueueFull(ValueError):
    """Bounded global or per-client admission limit."""


class UnconfiguredImageSource:
    """Reception-only installations have no implicit clinical image source."""
    available = False

    def stage(self, *args, **kwargs):
        raise ValueError('PACS image source is not configured.')


def write_json(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def run_worker(job, cancel):
    from aipacs_runtime import is_frozen
    from .process_owner import ProcessJob
    from .worker_output import WorkerOutput
    environment = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_'))}
    environment.update(AIPACS_EAGLE_EYE_WORKER='1', QT_QPA_PLATFORM='offscreen', PYTHONNOUSERSITE='1')
    root = Path(__file__).resolve().parents[3]
    owner = ProcessJob()
    process = None
    output = WorkerOutput(job / 'worker.log')
    try:
        command = ([sys.executable, '--eagle-eye-worker', str(job)] if is_frozen() else
                   [sys.executable, '-m', 'modules.ai_imaging.eagle_eye_remote.adapters', str(job)])
        process = subprocess.Popen(command,
            cwd=root, env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        owner.assign(process)
        output.start(process.stdout)
        deadline = time.monotonic() + 7200
        while process.poll() is None:
            if cancel.wait(.1) or time.monotonic() > deadline or output.failed.is_set():
                raise RuntimeError('Server analysis cancelled, timed out or could not retain its log.')
        if process.returncode or cancel.is_set():
            raise RuntimeError('Server model execution failed.')
        return json.loads((job / 'worker-result.json').read_text(encoding='utf-8'))
    finally:
        cleanup_failure = None
        try:
            owner.close()
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=15)
        except Exception:
            cleanup_failure = CompletionUncertain('Owned model cleanup did not prove completion.')
        try:
            output.finish()
        except Exception as error:
            if cleanup_failure is None:
                cleanup_failure = error
        finally:
            if (process is not None and process.stdout is not None
                    and (output.thread is None or not output.thread.is_alive())):
                process.stdout.close()
        if cleanup_failure is not None:
            raise cleanup_failure from None


class Jobs:
    def __init__(self, root, source, runner=run_worker, *, resources=None, max_jobs_per_client=4):
        self.resources = Resources(resources)
        if type(max_jobs_per_client) is not int or not 1 <= max_jobs_per_client <= 16:
            raise ValueError('The per-client job limit must be between 1 and 16.')
        self.max_jobs_per_client = max_jobs_per_client
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        from .ownership import DirectoryLease
        self.directory_lease = DirectoryLease(self.root)
        self.source, self.runner = source, runner
        self.lock = threading.RLock()
        self.closed = False
        self.admission = Admission()
        self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix='EagleEyeServer')
        # Source sessions are serialized; inference no longer prevents staging.
        self.retrieval = threading.BoundedSemaphore(1)
        self.slots = threading.BoundedSemaphore(16)
        self.jobs, self.cancelled, self.requests = {}, {}, {}
        self.case_events = None
        try:
            for file in self.root.glob('*/state.json'):
                state = json.loads(file.read_text(encoding='utf-8'))
                if state['status'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                    state.update(status='interrupted', message='Server restarted before analysis completed. Submit a new analysis.')
                    write_json(file, state)
                self.jobs[file.parent.name] = state
                key = ((state['owner'], state['principal'], state['request_id']) if state.get('principal')
                       else (state['owner'], state['request_id']))
                self.requests[key] = file.parent.name
        except Exception:
            self.executor.shutdown(wait=True)
            self.directory_lease.close()
            raise

    def update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)
            write_json(self.root / job_id / 'state.json', self.jobs[job_id])
            state = self.jobs[job_id]
            authority = getattr(self, 'user_authority', None)
            if authority and state.get('principal'):
                authority.store.event(state['principal'], state['owner'], 'imaging.' + state['module'],
                                      state['status'], state['request_id'])
            if self.case_events is not None:
                self.case_events.publish(self.jobs[job_id]['study_uid'], 'eagle_eye')

    def submit(self, owner, request, *, principal=None):
        request = validate(request)
        key = (owner, principal, request['request_id']) if principal else (owner, request['request_id'])
        signature = fingerprint(request)
        with self.lock:
            if self.closed:
                raise QueueFull('The server is stopping. Submit after it restarts.')
            if key in self.requests:
                state = self.jobs[self.requests[key]]
                if state['fingerprint'] != signature:
                    raise ValueError('Request identity was reused with different inputs.')
                return {'job_id': state['job_id']}
            from .reviews import check_parent
            parent_job_id = check_parent(self, owner, request)
            if not self.slots.acquire(blocking=False):
                raise QueueFull('Server queue is full. Try again later.')
            active = sum(state['owner'] == owner and state['status'] not in
                         ('succeeded', 'failed', 'cancelled', 'interrupted') for state in self.jobs.values())
            if active >= self.max_jobs_per_client:
                self.slots.release()
                raise QueueFull('This client has reached its active job limit. Try again later.')
            try:
                work = self.admission.begin('model')
            except Quiesced:
                self.slots.release()
                raise
            job_id = uuid.uuid4().hex
            job = self.root / job_id
            try:
                job.mkdir()
                write_json(job / 'request.json', request)
                self.jobs[job_id] = dict(job_id=job_id, owner=owner, request_id=request['request_id'],
                    fingerprint=signature, module=request['module'], study_uid=request['study_uid'],
                    created_at=time.time(), status='queued', parent_job_id=parent_job_id)
                if principal:
                    self.jobs[job_id]['principal'] = principal
                self.requests[key] = job_id
                self.cancelled[job_id] = threading.Event()
                self.update(job_id)
                future = self.executor.submit(self.execute, job_id, request)
                future.add_done_callback(lambda completed: work.finish(
                    uncertain=completed.cancelled() or completed.exception() is not None))
            except Exception:
                try:
                    if job_id in self.jobs:
                        self.update(job_id, status='failed', message='The server could not start this job.')
                finally:
                    self.cancelled.pop(job_id, None)
                    self.slots.release()
                    work.finish()
                raise
        return {'job_id': job_id}

    def execute(self, job_id, request):
        job, cancel = self.root / job_id, self.cancelled[job_id]
        source_lease = SourceLease()
        try:
            if cancel.is_set():
                raise RuntimeError('Cancelled.')
            state = self.jobs[job_id]
            authority = getattr(self, 'user_authority', None)
            if authority and state.get('principal'):
                authority.require(authority.available_grants(state['principal']), 'imaging', state['module'])
            while not self.retrieval.acquire(timeout=.1):
                if cancel.is_set():
                    raise RuntimeError('Cancelled.')
            try:
                if cancel.is_set():
                    raise RuntimeError('Cancelled.')
                self.update(job_id, status='retrieving')
                if request['parameters'].get('correction', {}).get('parent_job_id'):
                    from .reviews import stage_parent
                    records = stage_parent(self.root, request['parameters']['correction']['parent_job_id'], job / 'sources', lease=source_lease)
                    if request['module'] == 'total-spine':
                        known = {r['sop_uid'] for r in records}
                        extra = {k: v for k, v in request['series'].items() if v['sop_uid'] not in known}
                        if extra:
                            additional = dict(request, series=extra)
                            destination = job / 'sources' / 'additional'
                            if isinstance(self.source, PacsSource):
                                records.extend(self.source.stage(additional, destination, cancel, lease=source_lease))
                            else:
                                records.extend(self.source.stage(additional, destination, cancel))
                elif isinstance(self.source, PacsSource):
                    records = self.source.stage(request, job / 'sources', cancel, lease=source_lease)
                else:
                    records = self.source.stage(request, job / 'sources', cancel)
            finally:
                self.retrieval.release()
            write_json(job / 'sources.json', records)
            if cancel.is_set():
                raise RuntimeError('Cancelled.')
            self.update(job_id, status='waiting_for_resources')
            with self.resources.lease(request['module'], cancel):
                self.update(job_id, status='running')
                result = self.runner(job, cancel)
                from .usage import result_tokens
                self.update(job_id, token_accounting=result_tokens(result))
            if cancel.is_set():
                raise RuntimeError('Cancelled.')
            if any(digest(r['path']) != r['sha256'] for r in records):
                raise ValueError('Staged input changed during analysis.')
            receipt = publish(job, request, records, result)
            with self.lock:
                if cancel.is_set():
                    raise RuntimeError('Cancelled.')
                self.update(job_id, status='succeeded', **receipt)
        except Exception as error:
            if isinstance(error, CompletionUncertain):
                self.admission.poison()
            (job / 'artifacts.zip').unlink(missing_ok=True)
            self.update(job_id, status='cancelled' if cancel.is_set() else 'failed',
                message='Analysis cancelled.' if cancel.is_set() else
                        'Server analysis failed. Check PACS access, selected inputs and model readiness; no completed result was published.')
        finally:
            source_lease.close()
            self.slots.release()
            with self.lock:
                self.cancelled.pop(job_id, None)

    def get(self, owner, job_id):
        with self.lock:
            state = self.jobs.get(job_id)
            if state is None or state['owner'] != owner:
                raise KeyError('Analysis not found.')
            return {k: v for k, v in state.items() if k not in ('owner', 'fingerprint', 'request_id')}

    def cancel(self, owner, job_id):
        with self.lock:
            state = self.get(owner, job_id)
            if state['status'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                self.cancelled[job_id].set()
        return {'cancellation_requested': True}

    def recent(self, owner):
        with self.lock:
            states = sorted((state for state in self.jobs.values() if state['owner'] == owner),
                            key=lambda state: state.get('created_at', 0), reverse=True)[:50]
            return {'jobs': [self.get(owner, state['job_id']) for state in states]}

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            for event in self.cancelled.values():
                event.set()
        crm = getattr(self, 'crm', None)
        native_pipe = getattr(self, 'native_secretary_pipe', None)
        if native_pipe:
            native_pipe.close()
        native_secretary = getattr(self, 'native_secretary', None)
        if native_secretary:
            native_secretary.close()
        barrier_stop = getattr(self, 'installation_barrier_stop', None)
        if barrier_stop:
            barrier_stop.set()
        if crm:
            crm.close()
        bridge = getattr(self, 'case_bridge', None)
        if bridge:
            bridge.stop()
        if self.case_events:
            self.case_events.close()
        try:
            self.executor.shutdown(wait=True)
            self.source.session.close() if hasattr(self.source, 'session') else None
        finally:
            self.directory_lease.close()


def handler(jobs, credentials, certificate_pins=None, *, echomind=None, secretary=None, cases=None, license_guard=None, crm=None, user_authority=None, speech=None, deployment_identity=None, native_secretary=None):
    admission = getattr(jobs, 'admission', None)
    if admission is None:
        admission = jobs.admission = Admission()
    for host in (echomind, getattr(secretary, 'echo', None), crm):
        if host is not None and hasattr(host, 'clients') and not isinstance(host.clients, HumanOwnerSlots):
            host.clients = HumanOwnerSlots(host.clients)
    if cases is not None:
        cases.memberships = HumanCenterMemberships(cases.memberships, cases.center)
    lumbar_capabilities = None
    if echomind is not None and callable(getattr(echomind, 'process_lumbar_vision', None)):
        from .lumbar_vision import capabilities as lumbar_vision_capabilities
        lumbar_capabilities = lumbar_vision_capabilities()
    class Handler(BaseHTTPRequestHandler):
        server_version = 'EagleEye/1'
        def log_message(self, *args):
            pass  # Do not emit paths, request bodies, tokens or clinical identities.

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def reply(self, status, value):
            try:
                self.finish_audit(
                    'accepted' if status == 202 else 'succeeded' if status < 400 else 'failed'
                )
            except Exception:
                status, value = 503, {'error':'AUDIT_STORAGE_UNAVAILABLE','code':'AUDIT_STORAGE_UNAVAILABLE'}
            raw = json.dumps(value, allow_nan=False).encode()
            counters = getattr(self.server, 'transport_diagnostics', None)
            route_class = {'/v1/auth/session':'auth_session', '/v1/auth/me':'auth_me',
                           '/v1/capabilities':'public_capabilities'}.get(self.path, 'other')
            try:
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.close_connection = True
                self.end_headers()
                self.wfile.write(raw)
                if counters:
                    counters.increment('response_completed', route_class)
            except OSError:
                if counters:
                    counters.increment('response_write_failed', route_class)
                raise

        def dispatch(self):
            self._user_audit = None
            try:
                with admission.begin('http'):
                    return self._dispatch()
            except Quiesced:
                # Consume only a bounded body so Windows can deliver the refusal.
                self.close_connection = True
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if 0 < length <= 24 * 1024 * 1024 and not self.headers.get('Transfer-Encoding'):
                        self.rfile.read(length)
                    return self.reply(503, {'error':'SERVER_QUIESCED', 'code':'SERVER_QUIESCED'})
                except (OSError, ValueError):
                    return
            except TimeoutError:
                counters = getattr(self.server, 'transport_diagnostics', None)
                if counters:
                    counters.increment('request_body_timeout')
                raise
            except Exception:
                counters = getattr(self.server, 'transport_diagnostics', None)
                if counters:
                    counters.increment('handler_unexpected_failure')
                raise

        def _dispatch(self):
            self._user = None
            self._user_audit = None
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            owner = next((name for name, value in credentials.items() if hmac.compare_digest(value, token)), None)
            if token and owner is None:
                return self.reply(401, {'error': 'Authorization required.'})
            self._paired_owner = owner
            if owner is not None and certificate_pins:
                certificate = self.connection.getpeercert(binary_form=True) if isinstance(self.connection, ssl.SSLSocket) else None
                pin = hashlib.sha256(certificate or b'').hexdigest()
                if not hmac.compare_digest(certificate_pins.get(owner, ''), pin):
                    return self.reply(403, {'error': 'Client pairing required.'})
            try:
                from .user_access import UserDenied
                if owner is not None and cases is not None and cases.memberships.get(owner) != cases.center:
                    raise PermissionError('Center access denied.')
                if self.path.startswith('/v1/auth/'):
                    if user_authority is None:
                        raise UserDenied(503, 'USER_AUTHENTICATION_UNAVAILABLE')
                    if self.command == 'POST':
                        size = int(self.headers.get('Content-Length', '0'))
                        if not 0 < size <= 32768 or self.headers.get('Transfer-Encoding'):
                            raise ValueError('Invalid authentication request size.')
                        body = json.loads(self.rfile.read(size))
                        if self.path == '/v1/auth/session':
                            result = user_authority.login(owner or 'ordinary', body, peer=self.client_address[0])
                            return self.reply(200, {**result, 'user':public_user(result['user'])})
                        if self.path == '/v1/auth/session/refresh' and body == {}:
                            result = user_authority.refresh(owner or 'ordinary', self.headers.get('X-Eagle-User-Session', ''))
                            return self.reply(200, {**result, 'user':public_user(result['user'])})
                        if self.path == '/v1/auth/logout' and body == {}:
                            user_authority.logout(owner, self.headers.get('X-Eagle-User-Session', ''))
                            return self.reply(200, {'logged_out': True})
                    if self.command == 'GET' and self.path == '/v1/auth/me':
                        user = self.human(owner)
                        return self.reply(200, {'user':public_user(user)})
                    return self.reply(404, {'error':'Unknown authentication operation.'})
                if self.path != '/v1/capabilities':
                    self._user = self.human(owner)
                    owner = 'human:' + hashlib.sha256(self._user['principal'].encode()).hexdigest()
                    if cases is not None:
                        if user_authority.store.center != cases.center:
                            raise PermissionError('Human authority belongs to another center.')
                        cases.memberships.admit(owner)
                if (cases is not None and (self.path.startswith('/v1/jobs') or self.path == '/v1/usage')
                        and cases.memberships.get(owner) != cases.center):
                    raise PermissionError('Case access denied.')
                if self.command == 'GET' and self.path == '/v1/capabilities':
                    public_deployment = ({key: value for key, value in deployment_identity.items()
                        if key in {'qualified', 'mode', 'release_id', 'version', 'edition'}}
                        if isinstance(deployment_identity, dict) else None)
                    return self.reply(200, {'protocol': 1, 'deployment': public_deployment, 'modules': list(MODULES) if getattr(getattr(jobs, 'source', None), 'available', True) else [],
                        'speech': speech.capabilities if speech else None,
                        'user_auth': {'version': 1, 'required': True,
                            'providers': list(user_authority.providers) if user_authority else [],
                            'session_header': 'X-Eagle-User-Session'},
                        'echomind': echomind.capabilities if echomind else None,
                        'lumbar_vision': lumbar_capabilities,
                        'secretary': secretary.capabilities if secretary else None,
                        'secretary_remote': native_secretary.capabilities if native_secretary else None,
                        'crm': crm.capabilities if crm else None,
                        'request_language': {'protocol': 1,
                            'preference_field': 'language_preference',
                            'supported_preferences': ['fa', 'en'],
                            'workflows': (['secretary'] if secretary else []) + (['crm'] if crm else [])},
                        'case_realtime': {'version': 1, 'transport': 'authenticated-long-poll',
                            'shared_center_reads': True} if cases else None,
                        'input_mode': 'pacs_references', 'interactive_edits': True,
                        'lesion_acquisition_modes': ['3d', '2d'],
                        'lesion_multisequence_review': True,
                        'spine_box_segmentation': True,
                        'bone_age_demographic_confirmation': 1,
                        'marrow_multisequence_protocol': 2,
                        'correction_modules': ['alignment', 'total-spine', 'brain', 'brain-lesions', 'lumbar-marrow'], 'correction_protocol': 1})
                if self.path.startswith('/v1/secretary/remote/'):
                    from .secretary_remote import RemoteError, canonical_uuid
                    user_authority.require(self._user, 'secretary')
                    if native_secretary is None:
                        return self.reply(503, {'error':'NATIVE_RUNTIME_UNAVAILABLE',
                                                'code':'NATIVE_RUNTIME_UNAVAILABLE'})
                    principal = self._user['principal']
                    prefix = '/v1/secretary/remote/'
                    route = self.path[len(prefix):]
                    try:
                        if self.command == 'GET':
                            if route == 'status':
                                return self.reply(200, native_secretary.status(principal))
                            if route == 'sessions':
                                return self.reply(200, native_secretary.sessions(principal))
                            if route.startswith('sessions/'):
                                identity = canonical_uuid(route[len('sessions/'):])
                                return self.reply(200, native_secretary.session(principal, identity))
                            if route.startswith('operations/'):
                                identity = canonical_uuid(route[len('operations/'):])
                                return self.reply(200, native_secretary.operation(principal, identity))
                        elif self.command == 'POST' and route in ('sessions', 'operations'):
                            length = int(self.headers.get('Content-Length', '0'))
                            if not 0 < length <= 128 * 1024 or self.headers.get('Transfer-Encoding'):
                                raise ValueError('Invalid remote Secretary request size.')
                            body = json.loads(self.rfile.read(length))
                            if license_guard is None or not license_guard():
                                return self.reply(403, {'error':'Eagle Eye Server license is unavailable.'})
                            self.audit_request(owner, 'secretary.native', body)
                            return self.reply(202, native_secretary.submit(
                                principal, body, new_session=route == 'sessions'))
                        return self.reply(404, {'error':'Unknown remote Secretary operation.'})
                    except RemoteError as exc:
                        return self.reply(exc.status, {'error':exc.code, 'code':exc.code})
                    except (ConnectionError, OSError):
                        return self.reply(503, {'error':'NATIVE_RUNTIME_UNAVAILABLE',
                                                'code':'NATIVE_RUNTIME_UNAVAILABLE'})
                if self.path.startswith('/v1/crm/'):
                    if crm is None:
                        return self.reply(503, {'error': 'CRM is not configured on this server.'})
                    from .echomind.hosting import RequestFailed
                    body = None
                    if self.command == 'POST':
                        length = int(self.headers.get('Content-Length', '0'))
                        if not 0 < length <= 2 * 1024 * 1024 or self.headers.get('Transfer-Encoding'):
                            raise ValueError('Invalid CRM request size.')
                        body = json.loads(self.rfile.read(length))
                        self._user = self.human(owner)
                        if self.path == '/v1/crm/command' and (license_guard is None or not license_guard()):
                            return self.reply(403, {'error': 'Eagle Eye Server license is unavailable.'})
                    if cases is not None and cases.memberships.get(owner) != cases.center:
                        raise PermissionError('CRM center access denied.')
                    user_authority.require(self._user, 'crm')
                    self.audit_request(owner, 'crm', body)
                    try:
                        status, result = crm.process_request(owner, self.command, self.path, body,
                            self.headers.get('X-CRM-Session', ''), principal=self._user['principal'])
                    except RequestFailed as exc:
                        return self.reply(exc.status, {'error': str(exc)})
                    except Exception:
                        # The CRM host converts known failures only after owned
                        # worker cleanup. An escaping error cannot certify idle.
                        admission.poison()
                        raise
                    return self.reply(status, result)
                if self.command == 'GET' and self.path == '/v1/usage':
                    return self.reply(200, {'version':2,'scope':'this_user',
                        **user_authority.store.audit(self._user['principal'])})
                if self.command == 'GET' and self.path == '/v1/jobs':
                    user_authority.require(self._user, 'imaging')
                    value = jobs.recent(owner)
                    value['jobs'] = [row for row in value['jobs'] if row.get('module') in self._user['modules']]
                    return self.reply(200, value)
                if self.command == 'POST':
                    length = int(self.headers.get('Content-Length', '0'))
                    from .contracts import MAX_REVIEW_REQUEST
                    limit = (32 * 1024 if self.path == '/v1/secretary/assets' else
                             12 * 1024 * 1024 if self.path in ('/v1/secretary/plan', '/v1/speech/transcribe') else
                             MAX_REVIEW_REQUEST if self.path == '/v1/imaging/lumbar-vision' else
                             2 * 1024 * 1024 if self.path == '/v1/echomind/process' else MAX_REVIEW_REQUEST)
                    if self.path.startswith('/v1/cases/'):
                        limit = 4096
                    if not 0 < length <= limit or self.headers.get('Transfer-Encoding'):
                        raise ValueError('Invalid request size.')
                    body = json.loads(self.rfile.read(length))
                    self._user = self.human(owner)
                    if self.path == '/v1/speech/transcribe':
                        feature = body.get('feature') if isinstance(body, dict) else None
                        if feature not in ('echomind', 'secretary', 'crm'):
                            raise ValueError('Invalid speech feature.')
                        user_authority.require(self._user, feature)
                        self.audit_request(owner, 'speech.' + feature, body)
                    elif self.path == '/v1/jobs':
                        module = body.get('module') if isinstance(body, dict) else None
                        if module not in MODULES:
                            raise ValueError('Unknown imaging module.')
                        user_authority.require(self._user, 'imaging', module)
                        self.audit_request(owner, 'imaging.' + module, body)
                    elif self.path == '/v1/imaging/lumbar-vision':
                        user_authority.require(self._user, 'imaging', 'lumbar')
                        self.audit_request(owner, 'imaging.lumbar-vision', body)
                    elif self.path == '/v1/echomind/process':
                        user_authority.require(self._user, 'echomind')
                        self.audit_request(owner, 'echomind', body)
                    elif self.path.startswith('/v1/secretary/'):
                        user_authority.require(self._user, 'secretary')
                        self.audit_request(owner, 'secretary', body)
                    # Consume the bounded body before refusing admission: Windows
                    # can reset a socket closed with unread POST bytes and lose the
                    # error response. Never execute new paid work without authority.
                    # Existing jobs, cancellation and history/result reads survive expiry.
                    if self.path in ('/v1/jobs', '/v1/imaging/lumbar-vision', '/v1/echomind/process', '/v1/secretary/plan', '/v1/secretary/assets', '/v1/speech/transcribe'):
                        if license_guard is None or not license_guard():
                            return self.reply(403, {'error': 'Eagle Eye Server license is unavailable or expired. Contact the server administrator.'})
                    if self.path.startswith('/v1/cases/'):
                        if cases is None:
                            return self.reply(503, {'error': 'Case synchronization is unavailable.'})
                        if not self._user['echomind'] and not self._user['imaging']:
                            raise UserDenied(403, 'EAGLE_PERMISSION_DENIED')
                        if not isinstance(body, dict):
                            raise ValueError('Invalid case request.')
                        operation = self.path.removeprefix('/v1/cases/')
                        fields = {'snapshot': {'case', 'offset'}, 'events': {'case', 'cursor'},
                            'text': {'case', 'request_id'}, 'job': {'case', 'job_id'},
                            'artifacts': {'case', 'job_id'}}
                        if operation not in fields or set(body) - fields[operation] or 'case' not in body:
                            raise ValueError('Invalid case operation.')
                        reference = body['case']
                        if operation == 'snapshot':
                            value = cases.snapshot(owner, reference, offset=body.get('offset', 0))
                            for key in ('jobs', 'eagle_eye'):
                                value[key] = [row for row in value[key] if self._user['imaging'] and row['module'] in self._user['modules']]
                            if not self._user['echomind']:
                                value['echomind'] = []
                                value['more_echomind'] = False
                            return self.reply(200, value)
                        if operation == 'events':
                            value = cases.wait(owner, reference, body.get('cursor'))
                            self._user = self.human(owner)
                            if self._paired_owner is not None and not hmac.compare_digest(credentials.get(self._paired_owner, ''), token):
                                return self.reply(401, {'error': 'Authorization required.'})
                            return self.reply(200, value)
                        if operation == 'text':
                            user_authority.require(self._user, 'echomind')
                            return self.reply(200, cases.text(owner, reference, body.get('request_id')))
                        state, request = cases.job(owner, reference, body.get('job_id'))
                        user_authority.require(self._user, 'imaging', state.get('module'))
                        if operation == 'job':
                            return self.reply(200, {'state': state, 'request': request})
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/zip')
                        self.send_header('Content-Length', str(state['artifact_bytes']))
                        self.send_header('Cache-Control', 'no-store')
                        self.send_header('Connection', 'close')
                        self.close_connection = True
                        self.end_headers()
                        with (jobs.root / state['job_id'] / 'artifacts.zip').open('rb') as stream:
                            shutil.copyfileobj(stream, self.wfile)
                        return
                    if self.path == '/v1/speech/transcribe':
                        if speech is None:
                            return self.reply(503, {'error': 'Speech service is unavailable.'})
                        from .echomind.hosting import RequestFailed
                        try:
                            return self.reply(200, speech.process(body))
                        except RequestFailed as exc:
                            return self.reply(exc.status, {'error': str(exc)})
                    if self.path == '/v1/secretary/assets':
                        if secretary is None:
                            return self.reply(503, {'error':'Secretary is unavailable.'})
                        from .echomind.hosting import RequestFailed
                        try:
                            return self.reply(200, secretary.process_asset(owner, body))
                        except RequestFailed as exc:
                            return self.reply(exc.status, {'error':str(exc)})
                    if self.path == '/v1/secretary/plan':
                        if secretary is None:
                            return self.reply(503, {'error': 'Secretary is not configured on this Eagle Eye server.'})
                        from .echomind.hosting import RequestFailed
                        try:
                            return self.reply(200, secretary.process(owner, body))
                        except RequestFailed as exc:
                            from .secretary_errors import envelope
                            return self.reply(exc.status, envelope(exc))
                    if self.path == '/v1/echomind/process':
                        if echomind is None:
                            return self.reply(503, {'error': 'EchoMind is not configured on this Eagle Eye server.'})
                        from .echomind.hosting import RequestFailed
                        try:
                            return self.reply(200, echomind.process(owner, body))
                        except RequestFailed as exc:
                            return self.reply(exc.status, {'error': str(exc)})
                    if self.path == '/v1/imaging/lumbar-vision':
                        if echomind is None:
                            return self.reply(503, {'error': 'Lumbar vision is not configured on this Eagle Eye server.'})
                        from .echomind.hosting import RequestFailed
                        try:
                            return self.reply(200, echomind.process_lumbar_vision(owner, body))
                        except RequestFailed as exc:
                            return self.reply(exc.status, {'error': str(exc)})
                    if self.path == '/v1/jobs':
                        if not getattr(getattr(jobs, 'source', None), 'available', True):
                            return self.reply(503, {'error': 'PACS_IMAGE_SOURCE_UNAVAILABLE'})
                        if cases is not None:
                            cases.verify_study(owner, validate(body)['study_uid'])
                        return self.reply(202, jobs.submit(owner, body, principal=self._user['principal']))
                match = re.fullmatch(r'/v1/jobs/([a-f0-9]{32})(/cancel|/artifacts)?', self.path)
                if not match:
                    return self.reply(404, {'error': 'Unknown operation.'})
                job_id, operation = match.groups()
                state = jobs.get(owner, job_id)
                user_authority.require(self._user, 'imaging', state.get('module'))
                if operation == '/cancel' and self.command == 'POST':
                    return self.reply(200, jobs.cancel(owner, job_id))
                if self.command != 'GET':
                    return self.reply(405, {'error': 'Unsupported operation.'})
                if operation is None:
                    return self.reply(200, state)
                if operation == '/artifacts' and state['status'] == 'succeeded':
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/zip')
                    self.send_header('Content-Length', str(state['artifact_bytes']))
                    self.send_header('Cache-Control', 'no-store')
                    self.send_header('Connection', 'close')
                    self.close_connection = True
                    self.end_headers()
                    with (jobs.root / job_id / 'artifacts.zip').open('rb') as stream:
                        shutil.copyfileobj(stream, self.wfile)
                    return
                self.reply(409, {'error': 'Completed artifacts are not available.'})
            except UserDenied as exc:
                if self._user and user_authority:
                    operation = ('imaging' if self.path.startswith('/v1/jobs') or self.path.startswith('/v1/imaging/') else
                                 'crm' if self.path.startswith('/v1/crm/') else
                                 'secretary' if self.path.startswith('/v1/secretary/') else
                                 'echomind' if self.path.startswith('/v1/echomind/') else 'access')
                    user_authority.store.event(self._user['principal'], owner, operation, 'denied')
                self.reply(exc.status, {'error':exc.code, 'code':exc.code})
            except KeyError:
                self.reply(404, {'error': 'Analysis not found.'})
            except PermissionError:
                self.reply(403, {'error': 'Case access denied.'})
            except BlockingIOError:
                self.reply(429, {'error': 'Case event reader limit reached.'})
            except RevisionConflict:
                self.reply(409, {'error': 'A newer correction exists. Reload the latest result.'})
            except QueueFull:
                self.reply(429, {'error': 'Server or client job limit reached. Try again later.'})
            except Quiesced:
                self.reply(503, {'error':'SERVER_QUIESCED', 'code':'SERVER_QUIESCED'})
            except (ValueError, TypeError):
                self.reply(400, {'error': 'Invalid analysis request.'})
            except (BrokenPipeError, ConnectionError):
                try:
                    self.finish_audit('interrupted')
                except Exception:
                    admission.poison()
            except Exception:
                self.reply(500, {'error': 'Analysis service failed.'})
        do_GET = dispatch
        do_POST = dispatch

        def human(self, owner):
            from .user_access import UserDenied
            if user_authority is None:
                raise UserDenied(401, 'USER_SESSION_REQUIRED')
            return user_authority.verify(getattr(self, '_paired_owner', owner), self.headers.get('X-Eagle-User-Session', ''))

        def audit_request(self, owner, operation, body):
            rid = body.get('request_id') if isinstance(body, dict) else None
            if not isinstance(rid, str) or len(rid) > 128:
                rid = uuid.uuid4().hex
            self._user_audit = (self._user['principal'], owner, operation, rid)
            # Reserve a durable audit event before any AI/provider work starts.
            user_authority.store.event(self._user['principal'], owner, operation, 'admitted', rid)

        def finish_audit(self, outcome):
            audit = getattr(self, '_user_audit', None)
            if audit and user_authority:
                principal, device, operation, rid = audit
                user_authority.store.event(principal, device, operation, outcome, rid)
    return Handler


def create_server(config):
    from aipacs_runtime import is_frozen
    from .release_package import runtime_identity
    deployment_identity = runtime_identity()  # Capture once; never reread after an in-place update.
    if is_frozen():
        from aipacs_runtime import load_installation_profile
        if load_installation_profile().get('distribution_edition') != 'eagle-eye':
            raise ValueError('Only the Eagle Eye server edition can host models.')
    credentials = {}
    for name, token_file in config.get('clients', {}).items():
        value = Path(token_file).read_text(encoding='utf-8').strip()
        if len(value) < 32:
            raise ValueError('Server credentials must contain at least 32 characters.')
        credentials[name] = value
    host = config.get('host', '127.0.0.1')
    pins = config.get('client_certificate_sha256') or {}
    if config.get('client_ca_file') or pins:
        if (not config.get('certificate') or not config.get('client_ca_file')
                or set(pins) != set(credentials)
                or any(not isinstance(p, str) or not re.fullmatch('[a-f0-9]{64}', p) for p in pins.values())):
            raise ValueError('Every authorized client requires a certificate fingerprint and trusted client CA.')
    from .source import source_provider
    from modules.LicenseGenerator.renewal import server_manager
    licensing = server_manager(config)
    jobs = None
    server = None
    try:
        # Reserve the listener before restart recovery touches durable job states.
        server = HumanHTTPServer((host, int(config.get('port', 8002))), BaseHTTPRequestHandler)
        server.daemon_threads = True
        if config.get('certificate'):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(config['certificate'], config['private_key'])
            if pins:
                context.load_verify_locations(cafile=config['client_ca_file'])
                context.verify_mode = ssl.CERT_OPTIONAL
            server.tls_context = context
        from .user_access import create_authority
        authority = create_authority(config)
        pacs_config = config.get('pacs') or {}
        jobs = Jobs(config['job_root'], source_provider(pacs_config) if pacs_config else UnconfiguredImageSource(),
                    resources=config.get('resources'), max_jobs_per_client=config.get('max_jobs_per_client', 4))
        jobs.user_authority = authority
        server.admission = jobs.admission
        from .startup_barrier import StartupBarrier, current_scm_pid, trusted_config_path
        barrier_config_path = trusted_config_path(config)
        barrier = None
        if barrier_config_path is not None:
            barrier = StartupBarrier.from_config(config, jobs.admission, deployment_identity,
                scm_pid=current_scm_pid(barrier_config_path), core_root=Path(sys.executable).parent)
        jobs.installation_barrier = barrier
        jobs.installation_barrier_stop = threading.Event()
        def start_installation_barrier():
            if barrier is not None:
                barrier.publish_ready()
                threading.Thread(target=barrier.watch, args=(jobs.installation_barrier_stop,),
                    name='EagleEyeInstallationBarrier', daemon=True).start()
        jobs.start_installation_barrier = start_installation_barrier
        echomind = None
        secretary = None
        if config.get('echomind'):
            from .echomind.hosting import EchoMind
            echomind = EchoMind(config['echomind'], credentials)
            from .secretary.service import Secretary
            secretary = Secretary(config.get('secretary', {}), echomind)
        from .case_realtime import CaseService
        center = config.get('center_id', 'configured-pacs')
        memberships = config.get('client_centers', {owner: center for owner in credentials})
        if not isinstance(memberships, dict) or set(memberships) != set(credentials):
            raise ValueError('Every paired client requires a server-owned center membership.')
        cases = CaseService(jobs, echomind.history if echomind else None, memberships, center)
        scope = {'center': center, 'pacs': hashlib.sha256(json.dumps({
            k: pacs_config.get(k) for k in ('url', 'type', 'database')},
            sort_keys=True).encode()).hexdigest()}
        scope_file = jobs.root / 'case-scope.json'
        if scope_file.exists() and json.loads(scope_file.read_text(encoding='utf-8')) != scope:
            raise ValueError('The case store belongs to another center or PACS source.')
        write_json(scope_file, scope)
        if echomind:
            echomind.history.directory.mkdir(parents=True, exist_ok=True)
            history_scope = echomind.history.directory / 'case-scope.json'
            try:
                with history_scope.open('x', encoding='utf-8') as output:
                    json.dump(scope, output)
                    output.flush()
                    os.fsync(output.fileno())
            except FileExistsError:
                if json.loads(history_scope.read_text(encoding='utf-8')) != scope:
                    raise ValueError('EchoMind history belongs to another center or PACS source.')
        jobs.case_events = cases.events
        if echomind:
            echomind.case_events = cases.events
            echomind.verify_case = cases.verify_study
        if pacs_config:
            from .pacs_case_bridge import PacsCaseBridge
            bridge = PacsCaseBridge(cases, pacs_config)
            jobs.case_bridge = bridge
            bridge.start()
        crm = None
        if config.get('crm'):
            from .crm.hosting import CRM
            crm = CRM(config['crm'], echomind, credentials)
            jobs.crm = crm
        from .speech import Speech
        speech = Speech(echomind.directory) if echomind else None
        from .secretary_remote import NativeRemote
        native_secretary = jobs.native_secretary = NativeRemote(jobs.admission)
        def start_native_secretary():
            if os.name != 'nt' or getattr(jobs, 'native_secretary_pipe', None):
                return
            from .secretary_pipe import NativePipeHost
            def authenticate_native_session(token):
                user = authority.verify(None, token)
                authority.require(user, 'secretary')
                return user['principal']
            def validate_native_transport(token):
                return authority.verify_transport(None, token, 'secretary')['principal']
            pipe = NativePipeHost(native_secretary, authenticate_native_session,
                validate_transport_session=validate_native_transport)
            try:
                pipe.start()
            except Exception:
                # Native unavailability must not interrupt other clinical routes.
                pipe.close()
            else:
                jobs.native_secretary_pipe = pipe
                server.transport_diagnostics.set_native_pipe_provider(pipe.diagnostics)
        jobs.start_native_secretary = start_native_secretary
        server.RequestHandlerClass = handler(jobs, credentials, pins, echomind=echomind,
                                            secretary=secretary, cases=cases,
                                            license_guard=lambda: licensing.check_license()[0], crm=crm, speech=speech,
                                            user_authority=authority, deployment_identity=deployment_identity,
                                            native_secretary=native_secretary)
        return server, jobs
    except Exception:
        if server is not None:
            server.server_close()
        if jobs is not None:
            jobs.close()
        raise


def serve(config):
    server, jobs = create_server(config)
    try:
        jobs.start_installation_barrier()
        jobs.start_native_secretary()
        server.serve_forever()
    finally:
        server.server_close()
        jobs.close()
