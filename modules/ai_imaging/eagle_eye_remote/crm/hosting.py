"""Bounded authenticated proxy to an owned, loopback-only CRM worker."""
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import urllib.parse
import requests

from ..echomind.hosting import RequestFailed
from ..process_owner import ProcessJob


def route(method, path):
    parsed = urllib.parse.urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        raise ValueError('Invalid CRM route.')
    if parsed.query:
        query = urllib.parse.parse_qs(parsed.query, strict_parsing=True)
        if (method != 'GET' or parsed.path != '/v1/crm/progress'
                or len(parsed.query) > 256 or set(query) != {'conversationId'}
                or len(query['conversationId']) != 1):
            raise ValueError('Unsupported CRM query.')
    routes = {
        ('GET', '/v1/crm/health'): '/api/health',
        ('GET', '/v1/crm/modes'): '/api/modes',
        ('GET', '/v1/crm/tools'): '/api/tools',
        ('GET', '/v1/crm/progress'): '/api/agent/progress',
        ('POST', '/v1/crm/session'): '/api/session',
        ('POST', '/v1/crm/logout'): '/api/session/logout',
        ('POST', '/v1/crm/command'): '/api/agent/command',
    }
    if method == 'POST' and parsed.path.startswith('/v1/crm/conversations/'):
        action = parsed.path.rsplit('/', 1)[-1]
        if (action in {'list', 'create', 'get', 'update', 'delete', 'sync', 'analyses'}
                and parsed.path == '/v1/crm/conversations/' + action):
            return '/api/conversations/' + action
    target = routes.get((method, parsed.path))
    if target is None:
        raise ValueError('Unsupported CRM operation.')
    return target + ('?' + parsed.query if parsed.query else '')


class CRM:
    def __init__(self, config, echo, clients):
        count = config.get('max_requests', 1)
        if type(count) is not int or count != 1:
            raise ValueError('The first CRM migration uses one bounded request at a time.')
        self.directory = Path(config.get('config_dir', ''))
        if not self.directory.is_absolute() or not (self.directory / 'server.json').is_file():
            raise ValueError('Configure the private CRM directory with server.json and roles.json.')
        if not (self.directory / 'roles.json').is_file() or echo is None:
            raise ValueError('CRM requires a roles policy and the Eagle Eye AI gateway.')
        self.config, self.echo = dict(config), echo
        self.slots = threading.BoundedSemaphore(count)
        self.clients = {owner: threading.BoundedSemaphore(1) for owner in clients}
        self.lock = threading.Lock()
        self.process = self.process_job = None
        self.worker_process = None
        self.url = None
        self.internal_token = secrets.token_urlsafe(48)
        self.sessions = {}
        self.closed = False
        self.capabilities = {'version': 1, 'source_version': '1.32.6',
                             'read_only': True, 'user_session_required': True,
                             'server_owned_prompts': True, 'isolated_worker': True}

    def _start(self):
        from aipacs_runtime import is_frozen
        with self.lock:
            if self.closed:
                raise RequestFailed(503, 'CRM is stopping.')
            if self.process and self.process.poll() is None:
                return
            if self.process_job:
                self._stop_owned()
            self.sessions.clear()
            ready = self.directory / 'worker-ready.json'
            ready.unlink(missing_ok=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith(('PYTHON', 'QT_', 'INO_', 'RECEPTION_'))}
            env['PYTHONNOUSERSITE'] = '1'
            owner = ProcessJob()
            try:
                command = ([sys.executable, '--eagle-eye-crm-worker', 'stdin'] if is_frozen()
                           else [sys.executable, '-m', 'modules.ai_imaging.eagle_eye_remote.crm.worker'])
                process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[4],
                    env=env, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), text=True, encoding='utf-8')
                owner.assign(process)
                process.stdin.write(json.dumps({'config_dir': str(self.directory),
                    'ai_config_dir': str(self.echo.directory), 'token': self.internal_token}) + '\n')
                process.stdin.close()
                import time
                deadline = time.monotonic() + 20
                while not ready.is_file():
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RequestFailed(503, 'CRM worker could not start. Check private configuration.')
                    time.sleep(.05)
                record = json.loads(ready.read_text())
                if type(record.get('pid')) is not int or type(record.get('port')) is not int or not 1 <= record['port'] <= 65535:
                    raise RequestFailed(503, 'CRM worker readiness could not be verified.')
                if record['pid'] != process.pid:
                    # Windows virtualenv launchers redirect to a child interpreter.
                    import psutil
                    if process.pid not in [p.pid for p in psutil.Process(record['pid']).parents()]:
                        raise RequestFailed(503, 'CRM worker process ownership could not be verified.')
                    import ctypes
                    from ctypes import wintypes
                    from types import SimpleNamespace
                    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
                    kernel.OpenProcess.restype = wintypes.HANDLE
                    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                    handle = kernel.OpenProcess(0x0101, False, record['pid'])
                    if not handle:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        owner.assign(SimpleNamespace(_handle=handle))
                    finally:
                        kernel.CloseHandle(handle)
                self.process, self.process_job = process, owner
                import psutil
                self.worker_process = psutil.Process(record['pid'])
                self.url = 'http://127.0.0.1:' + str(record['port'])
            except Exception:
                owner.close()
                if 'process' in locals():
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                raise

    def process_request(self, owner, method, path, body, session='', *, principal=None):
        target = route(method, path)
        if owner not in self.clients:
            raise RequestFailed(403, 'CRM client access denied.')
        if target not in {'/api/health', '/api/modes'} and not principal:
            raise RequestFailed(401, 'An authenticated human is required for CRM.')
        binding = (owner, principal)
        login = method == 'POST' and target == '/api/session'
        from .delegation import encode_subject, HEADER
        delegated_subject = encode_subject(principal) if principal else ''
        if login:
            body = {}  # Personal Reception credentials never cross the hosted boundary.
        if target == '/api/session/logout':
            body = {}  # Only the host-checked header token may be revoked.
        public = target in {'/api/session', '/api/health', '/api/modes'}
        if not public and session:
            with self.lock:
                if self.sessions.get(hashlib.sha256(session.encode()).hexdigest()) != binding:
                    raise RequestFailed(401, 'A CRM session bound to this Eagle user and device is required.')
        if not self.clients[owner].acquire(False):
            raise RequestFailed(429, 'CRM is busy for this client.')
        acquired = self.slots.acquire(False)
        ai = target == '/api/agent/command'
        ai_acquired = False
        try:
            if not acquired:
                raise RequestFailed(429, 'CRM server is busy.')
            if ai:
                ai_acquired = self.echo.slots.acquire(False)
                if not ai_acquired:
                    raise RequestFailed(429, 'The server AI gateway is busy.')
                if not isinstance(body, dict) or body.get('mode', 'report') not in {'report', 'analysis'}:
                    raise RequestFailed(422, 'Hosted CRM currently supports read-only Report and Analysis.')
            self._start()
            if not public and session:
                with self.lock:
                    if self.sessions.get(hashlib.sha256(session.encode()).hexdigest()) != binding:
                        raise RequestFailed(401, 'CRM restarted. Request a new CRM session with your Eagle identity.')
            with requests.Session() as http:
                http.trust_env = False
                response = http.request(method, self.url + target, json=body if method == 'POST' else None,
                    headers={'X-Eagle-Internal': self.internal_token, HEADER: delegated_subject,
                             'Authorization': 'Bearer ' + session},
                    timeout=(3, 180), allow_redirects=False, stream=True)
                with response:
                    raw = response.raw.read(8 * 1024 * 1024 + 1)
                    if len(raw) > 8 * 1024 * 1024:
                        raise RequestFailed(502, 'CRM response exceeds the transport budget.')
                    result = json.loads(raw)
                    if target == '/api/health':
                        result = {k: result[k] for k in ('status', 'version', 'tool_count',
                                  'llm_configured', 'writes_enabled') if k in result}
                    if target == '/api/modes':
                        result['modes'] = [m for m in result.get('modes', [])
                                           if m.get('id') in {'report', 'analysis'}]
                    if login and response.status_code == 200 and result.get('accessToken'):
                        with self.lock:
                            if len(self.sessions) >= 512:
                                self.sessions.pop(next(iter(self.sessions)))
                            self.sessions[hashlib.sha256(result['accessToken'].encode()).hexdigest()] = binding
                    if target == '/api/session/logout':
                        with self.lock:
                            self.sessions.pop(hashlib.sha256(session.encode()).hexdigest(), None)
                    return response.status_code, result
        except RequestFailed:
            raise
        except Exception:
            # A lost response must not leave hidden work consuming a released slot.
            with self.lock:
                self._stop_owned()
                self.sessions.clear()
            raise RequestFailed(503, 'CRM request did not complete. Do not retry automatically.') from None
        finally:
            if ai_acquired:
                self.echo.slots.release()
            if acquired:
                self.slots.release()
            self.clients[owner].release()

    def _stop_owned(self):
        if self.process_job:
            self.process_job.close()
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=10)
        if self.worker_process:
            import psutil
            try:
                self.worker_process.wait(timeout=10)
            except psutil.NoSuchProcess:
                pass
            self.worker_process = None

    def close(self):
        with self.lock:
            self.closed = True
            self._stop_owned()
            self.sessions.clear()
