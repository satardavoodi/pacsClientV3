"""Worker-only reference/revision client; transfers derived artifacts and labels."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from .contracts import validate, digest
from .settings import client_settings

MAX_ARTIFACT_BYTES = 512 * 1024**2


class AnalysisFailed(RuntimeError):
    """The server confirmed a terminal unsuccessful state; retry may use a new job."""


class DetachedAnalysis(RuntimeError):
    """Observation failed; the durable handle can reconcile the original request."""
    def __init__(self, handle_path):
        super().__init__('The analysis connection was interrupted. The server job was not cancelled. '
                         'Reconnect to retrieve its status and results.')
        self.handle_path = Path(handle_path)


def save_handle(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.partial')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('Unexpected analysis server redirect.')


class Client:
    def __init__(self, settings=None):
        cfg = client_settings() if settings is None else settings
        self.url = str(cfg.get('url', '')).rstrip('/')
        parsed = urllib.parse.urlsplit(self.url)
        if (parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or (parsed.scheme == 'http' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'))):
            raise ValueError('Configure an HTTPS Eagle Eye server address in Eagle Eye connection settings.')
        self.token = os.environ.get(cfg.get('token_env', 'AIPACS_EAGLE_EYE_TOKEN'), '')
        if not self.token and cfg.get('token_file'):
            self.token = Path(cfg['token_file']).read_text(encoding='utf-8').strip()
        if len(self.token) < 32:
            raise ValueError('Configure the Eagle Eye server access token.')
        context = ssl.create_default_context(cafile=cfg.get('ca_file') or None)
        certificate, key = cfg.get('client_certificate'), cfg.get('client_private_key')
        if bool(certificate) != bool(key):
            raise ValueError('Configure both the client certificate and private key.')
        if certificate:
            if parsed.scheme != 'https':
                raise ValueError('Paired clients require HTTPS.')
            context.load_cert_chain(certificate, key)
        self.opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))

    def open(self, path, body=None, method=None):
        raw = None if body is None else json.dumps(body, allow_nan=False).encode()
        req = urllib.request.Request(self.url + path, data=raw, method=method,
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'})
        try:
            return self.opener.open(req, timeout=30)
        except urllib.error.HTTPError as exc:
            status = exc.code
            exc.close()
            if status == 429:
                raise RuntimeError('The Eagle Eye server or this client has reached its job limit. Try again later.') from None
            if status == 409 and path == '/v1/jobs':
                raise ValueError('A newer server correction exists. Reload its result before submitting changes.') from None
            if (status in (400, 403, 404) and path == '/v1/jobs' and isinstance(body, dict)
                    and 'correction' in body.get('parameters', {})):
                raise ValueError('The server rejected this analysis or correction. Verify its source and access.') from None
            raise RuntimeError('Eagle Eye server request failed. Check the connection and server job status.') from None
        except (urllib.error.URLError, OSError):
            raise RuntimeError('Eagle Eye server request failed. Check the connection and server job status.') from None

    def json(self, path, body=None, method=None):
        with self.open(path, body, method) as response:
            raw = response.read(2 * 1024**2 + 1)
        if len(raw) > 2 * 1024**2:
            raise ValueError('Server response exceeds the limit.')
        return json.loads(raw)

    def analyze(self, module, study_uid, series, parameters, destination, *, cancel=None, progress=None, timeout=7500):
        request = validate(dict(protocol=1, request_id=uuid.uuid4().hex, module=module,
                                study_uid=study_uid, series=series, parameters=parameters))
        if cancel is not None and cancel.is_set():
            raise RuntimeError('Analysis cancelled.')
        directory = Path(destination).resolve() / '.eagle-eye-jobs'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (request['request_id'] + '.json')
        handle = {'version': 1, 'server': self.url,
                  'credential_binding': hashlib.sha256(self.token.encode()).hexdigest(),
                  'request': request, 'job_id': None}
        save_handle(path, handle)  # Before POST: a lost acknowledgement is reconcilable.
        return self._observe(handle, path, destination, cancel=cancel, progress=progress, timeout=timeout)

    def resume(self, handle_path, destination, *, cancel=None, progress=None, timeout=7500):
        path = Path(handle_path).resolve()
        from .contracts import MAX_REVIEW_REQUEST
        with path.open('r', encoding='utf-8') as stream:
            raw = stream.read(MAX_REVIEW_REQUEST + 65537)
        if len(raw) > MAX_REVIEW_REQUEST + 65536:
            raise ValueError('Invalid saved analysis handle.')
        handle = json.loads(raw)
        if (handle.get('version') != 1 or handle.get('server') != self.url or
                handle.get('credential_binding') != hashlib.sha256(self.token.encode()).hexdigest()):
            raise ValueError('Saved analysis belongs to another server or credential.')
        handle['request'] = validate(handle['request'])
        return self._observe(handle, path, destination, cancel=cancel, progress=progress, timeout=timeout)

    def _observe(self, handle, handle_path, destination, *, cancel=None, progress=None, timeout=7500):
        cancel = cancel or threading.Event()
        progress = progress or (lambda message: None)
        request = handle['request']
        study_uid, module = request['study_uid'], request['module']
        if cancel.is_set():
            raise RuntimeError('Analysis cancelled.')
        try:
            # Repeating the same owner/request ID reconciles an uncertain POST.
            job = self.json('/v1/jobs', request)
        except RuntimeError:
            raise DetachedAnalysis(handle_path) from None
        job_id = job.get('job_id', '')
        if len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
            raise ValueError('Invalid server job identity.')
        if handle.get('job_id') not in (None, job_id):
            raise ValueError('Server changed the saved analysis identity.')
        handle['job_id'] = job_id
        save_handle(handle_path, handle)
        endpoint = '/v1/jobs/' + job_id
        deadline = time.monotonic() + timeout
        completed = False
        try:
            while True:
                if cancel.is_set():
                    raise RuntimeError('Analysis cancelled.')
                if time.monotonic() >= deadline:
                    raise DetachedAnalysis(handle_path)
                try:
                    state = self.json(endpoint)
                except RuntimeError:
                    raise DetachedAnalysis(handle_path) from None
                if state.get('study_uid') != study_uid or state.get('module') != module:
                    raise ValueError('Server result belongs to a different analysis.')
                status = state.get('status')
                if status == 'succeeded':
                    break
                if status in ('failed', 'cancelled', 'interrupted'):
                    raise AnalysisFailed(state.get('message', 'Server analysis did not complete.'))
                progress('Server is retrieving images from PACS' if status == 'retrieving' else
                         'Waiting for server resources' if status == 'waiting_for_resources' else
                         'Waiting for the server' if status == 'queued' else 'Server is analyzing the study')
                cancel.wait(.4)
            progress('Receiving analysis results')
            parent = Path(destination).resolve()
            parent.mkdir(parents=True, exist_ok=True)
            target = parent / ('remote-' + job_id)
            if target.exists():
                raise ValueError('Result directory already exists.')
            temporary = parent / ('download-' + uuid.uuid4().hex)
            temporary.mkdir()
            try:
                archive = temporary / 'artifacts.zip'
                with self.open(endpoint + '/artifacts') as response, archive.open('wb') as output:
                    size = 0
                    while True:
                        if cancel.is_set():
                            raise RuntimeError('Analysis cancelled.')
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        size += len(block)
                        if size > MAX_ARTIFACT_BYTES:
                            raise ValueError('Analysis artifacts exceed the limit.')
                        output.write(block)
                if size != state['artifact_bytes'] or digest(archive) != state['artifact_sha256']:
                    raise ValueError('Downloaded analysis artifacts are incomplete or changed.')
                result = unpack(archive, temporary / 'result', request)
                if cancel.is_set():
                    raise RuntimeError('Analysis cancelled.')
                (temporary / 'result').rename(target)
                result = relocate(result, target)
                result['artifact_directory'] = str(target)
                (target / 'result.json').write_text(json.dumps(result, allow_nan=False), encoding='utf-8')
                completed = True
                return result
            except (OSError, RuntimeError):
                if cancel.is_set():
                    raise
                raise DetachedAnalysis(handle_path) from None
            finally:
                shutil.rmtree(temporary)
        finally:
            if not completed and cancel.is_set():
                try:
                    self.json(endpoint + '/cancel', {}, 'POST')
                except Exception:
                    pass


def unpack(archive, target, request):
    target = Path(target).resolve()
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        names = [item.filename for item in members]
        if (len(members) > 512 or 'envelope.json' not in names
                or len({name.casefold() for name in names}) != len(names) or
                sum(item.file_size for item in members) > MAX_ARTIFACT_BYTES):
            raise ValueError('Invalid artifact inventory.')
        for item in members:
            path = PurePosixPath(item.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in item.filename or ':' in item.filename
                    or any(part.endswith(('.', ' ')) or _reserved_name(part) for part in path.parts)
                    or item.is_dir() or ((item.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError('Unsafe artifact path.')
        envelope = json.loads(package.read('envelope.json'))
        if any(envelope.get(k) != request[k] for k in ('protocol', 'module', 'study_uid', 'request_id')):
            raise ValueError('Downloaded result identity mismatch.')
        hashes = envelope['files']
        if set(names) != set(hashes) | {'envelope.json'}:
            raise ValueError('Unexpected artifact files.')
        target.mkdir()
        for name, expected in hashes.items():
            dest = target / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            with package.open(name) as source, dest.open('wb') as output:
                shutil.copyfileobj(source, output)
            if digest(dest) != expected:
                raise ValueError('Artifact checksum mismatch.')
        return envelope['result']


def _reserved_name(name):
    stem = name.split('.')[0].upper()
    return stem in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(10)), *(f'LPT{i}' for i in range(10))}


def relocate(value, directory):
    if isinstance(value, dict):
        if set(value) == {'artifact'}:
            relative = PurePosixPath(value['artifact'])
            if relative.is_absolute() or '..' in relative.parts or ':' in str(relative) or '\\' in str(relative):
                raise ValueError('Unsafe result reference.')
            return str(directory / str(relative))
        return {k: relocate(v, directory) for k, v in value.items()}
    if isinstance(value, list):
        return [relocate(v, directory) for v in value]
    return value
