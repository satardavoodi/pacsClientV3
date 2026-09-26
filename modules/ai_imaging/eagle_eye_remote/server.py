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
import ssl
import subprocess
import sys
import threading
import time
import uuid

from .contracts import MODULES, validate, fingerprint, digest
from .source import PacsSource, SourceLease
from .artifacts import publish
from .scheduling import Resources
from .reviews import RevisionConflict


class QueueFull(ValueError):
    """Bounded global or per-client admission limit."""


def write_json(path, value):
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(value, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def run_worker(job, cancel):
    from .process_owner import ProcessJob
    environment = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_'))}
    environment.update(AIPACS_EAGLE_EYE_WORKER='1', QT_QPA_PLATFORM='offscreen', PYTHONNOUSERSITE='1')
    root = Path(__file__).resolve().parents[3]
    owner = ProcessJob()
    process = None
    try:
        with (job / 'worker.log').open('wb') as log:
            command = ([sys.executable, '--eagle-eye-worker', str(job)] if getattr(sys, 'frozen', False) else
                       [sys.executable, '-m', 'modules.ai_imaging.eagle_eye_remote.adapters', str(job)])
            process = subprocess.Popen(command,
                cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            owner.assign(process)
            deadline = time.monotonic() + 7200
            while process.poll() is None:
                if cancel.wait(.1) or time.monotonic() > deadline:
                    raise RuntimeError('Server analysis cancelled or timed out.')
            if process.returncode or cancel.is_set():
                raise RuntimeError('Server model execution failed.')
        return json.loads((job / 'worker-result.json').read_text(encoding='utf-8'))
    finally:
        owner.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)


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
        self.executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix='EagleEyeServer')
        # Source sessions are serialized; inference no longer prevents staging.
        self.retrieval = threading.BoundedSemaphore(1)
        self.slots = threading.BoundedSemaphore(16)
        self.jobs, self.cancelled, self.requests = {}, {}, {}
        try:
            for file in self.root.glob('*/state.json'):
                state = json.loads(file.read_text(encoding='utf-8'))
                if state['status'] not in ('succeeded', 'failed', 'cancelled', 'interrupted'):
                    state.update(status='interrupted', message='Server restarted before analysis completed. Submit a new analysis.')
                    write_json(file, state)
                self.jobs[file.parent.name] = state
                self.requests[(state['owner'], state['request_id'])] = file.parent.name
        except Exception:
            self.executor.shutdown(wait=True)
            self.directory_lease.close()
            raise

    def update(self, job_id, **values):
        with self.lock:
            self.jobs[job_id].update(values)
            write_json(self.root / job_id / 'state.json', self.jobs[job_id])

    def submit(self, owner, request):
        request = validate(request)
        key = (owner, request['request_id'])
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
            job_id = uuid.uuid4().hex
            job = self.root / job_id
            try:
                job.mkdir()
                write_json(job / 'request.json', request)
                self.jobs[job_id] = dict(job_id=job_id, owner=owner, request_id=request['request_id'],
                    fingerprint=signature, module=request['module'], study_uid=request['study_uid'],
                    created_at=time.time(), status='queued', parent_job_id=parent_job_id)
                self.requests[key] = job_id
                self.cancelled[job_id] = threading.Event()
                self.update(job_id)
                self.executor.submit(self.execute, job_id, request)
            except Exception:
                try:
                    if job_id in self.jobs:
                        self.update(job_id, status='failed', message='The server could not start this job.')
                finally:
                    self.cancelled.pop(job_id, None)
                    self.slots.release()
                raise
        return {'job_id': job_id}

    def execute(self, job_id, request):
        job, cancel = self.root / job_id, self.cancelled[job_id]
        source_lease = SourceLease()
        try:
            if cancel.is_set():
                raise RuntimeError('Cancelled.')
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
            if cancel.is_set():
                raise RuntimeError('Cancelled.')
            if any(digest(r['path']) != r['sha256'] for r in records):
                raise ValueError('Staged input changed during analysis.')
            receipt = publish(job, request, records, result)
            with self.lock:
                if cancel.is_set():
                    raise RuntimeError('Cancelled.')
                self.update(job_id, status='succeeded', **receipt)
        except Exception:
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
        try:
            self.executor.shutdown(wait=True)
            self.source.session.close() if hasattr(self.source, 'session') else None
        finally:
            self.directory_lease.close()


def handler(jobs, credentials, certificate_pins=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = 'EagleEye/1'
        def log_message(self, *args):
            pass  # Do not emit paths, request bodies, tokens or clinical identities.

        def setup(self):
            super().setup()
            self.connection.settimeout(30)

        def reply(self, status, value):
            raw = json.dumps(value, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def dispatch(self):
            token = self.headers.get('Authorization', '').removeprefix('Bearer ')
            owner = next((name for name, value in credentials.items() if hmac.compare_digest(value, token)), None)
            if owner is None:
                return self.reply(401, {'error': 'Authorization required.'})
            if certificate_pins:
                certificate = self.connection.getpeercert(binary_form=True)
                pin = hashlib.sha256(certificate or b'').hexdigest()
                if not hmac.compare_digest(certificate_pins.get(owner, ''), pin):
                    return self.reply(403, {'error': 'Client pairing required.'})
            try:
                if self.command == 'GET' and self.path == '/v1/capabilities':
                    return self.reply(200, {'protocol': 1, 'modules': list(MODULES),
                        'input_mode': 'pacs_references', 'interactive_edits': True,
                        'lesion_acquisition_modes': ['3d', '2d'],
                        'spine_box_segmentation': True,
                        'correction_modules': ['alignment', 'total-spine', 'brain', 'brain-lesions'], 'correction_protocol': 1})
                if self.command == 'GET' and self.path == '/v1/jobs':
                    return self.reply(200, jobs.recent(owner))
                if self.command == 'POST':
                    length = int(self.headers.get('Content-Length', '0'))
                    from .contracts import MAX_REVIEW_REQUEST
                    if not 0 < length <= MAX_REVIEW_REQUEST or self.headers.get('Transfer-Encoding'):
                        raise ValueError('Invalid request size.')
                    body = json.loads(self.rfile.read(length))
                    if self.path == '/v1/jobs':
                        return self.reply(202, jobs.submit(owner, body))
                match = re.fullmatch(r'/v1/jobs/([a-f0-9]{32})(/cancel|/artifacts)?', self.path)
                if not match:
                    return self.reply(404, {'error': 'Unknown operation.'})
                job_id, operation = match.groups()
                state = jobs.get(owner, job_id)
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
                    self.end_headers()
                    with (jobs.root / job_id / 'artifacts.zip').open('rb') as stream:
                        shutil.copyfileobj(stream, self.wfile)
                    return
                self.reply(409, {'error': 'Completed artifacts are not available.'})
            except KeyError:
                self.reply(404, {'error': 'Analysis not found.'})
            except RevisionConflict:
                self.reply(409, {'error': 'A newer correction exists. Reload the latest result.'})
            except QueueFull:
                self.reply(429, {'error': 'Server or client job limit reached. Try again later.'})
            except (ValueError, TypeError):
                self.reply(400, {'error': 'Invalid analysis request.'})
            except (BrokenPipeError, ConnectionError):
                pass
            except Exception:
                self.reply(500, {'error': 'Analysis service failed.'})
        do_GET = dispatch
        do_POST = dispatch
    return Handler


def create_server(config):
    if getattr(sys, 'frozen', False):
        from aipacs_runtime import load_installation_profile
        if load_installation_profile().get('distribution_edition') != 'eagle-eye':
            raise ValueError('Only the Eagle Eye server edition can host models.')
    credentials = {}
    for name, token_file in config['clients'].items():
        value = Path(token_file).read_text(encoding='utf-8').strip()
        if len(value) < 32:
            raise ValueError('Server credentials must contain at least 32 characters.')
        credentials[name] = value
    if not credentials:
        raise ValueError('Configure at least one authorized client.')
    host = config.get('host', '127.0.0.1')
    pins = config.get('client_certificate_sha256') or {}
    if config.get('client_ca_file') or pins:
        if (not config.get('certificate') or not config.get('client_ca_file')
                or set(pins) != set(credentials)
                or any(not isinstance(p, str) or not re.fullmatch('[a-f0-9]{64}', p) for p in pins.values())):
            raise ValueError('Every authorized client requires a certificate fingerprint and trusted client CA.')
    if host not in ('127.0.0.1', 'localhost', '::1') and not config.get('certificate'):
        raise ValueError('A TLS certificate is required for a LAN listener.')
    from .source import source_provider
    jobs = None
    server = None
    try:
        # Reserve the listener before restart recovery touches durable job states.
        server = ThreadingHTTPServer((host, int(config.get('port', 8042))), BaseHTTPRequestHandler)
        server.daemon_threads = True
        if config.get('certificate'):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(config['certificate'], config['private_key'])
            if pins:
                context.load_verify_locations(cafile=config['client_ca_file'])
                context.verify_mode = ssl.CERT_REQUIRED
            # Complete TLS in the per-connection handler, under its read timeout.
            # An idle TLS peer must not block the listener's accept loop.
            server.socket = context.wrap_socket(server.socket, server_side=True,
                                                do_handshake_on_connect=False)
        jobs = Jobs(config['job_root'], source_provider(config['pacs']),
                    resources=config.get('resources'), max_jobs_per_client=config.get('max_jobs_per_client', 4))
        server.RequestHandlerClass = handler(jobs, credentials, pins)
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
        server.serve_forever()
    finally:
        server.server_close()
        jobs.close()
