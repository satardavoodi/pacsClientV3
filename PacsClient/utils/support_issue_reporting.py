"""Private, bounded issue delivery through the existing website identity client.

All entry points perform blocking work and must run outside the Qt GUI thread.
Raw logs require separate explicit consent. Outbox content is DPAPI sealed.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from .support_diagnostics import collect_log_evidence, collect_windows_events

_LOCK = threading.Lock()
MAX_PAYLOAD = 16 * 1024 * 1024


def _dpapi(data, protect):
    """User-bound Windows encryption through the OS API; no plaintext fallback."""
    import ctypes
    from ctypes import wintypes
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32.dll', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32.dll', use_last_error=True)
    function = crypt.CryptProtectData if protect else crypt.CryptUnprotectData
    function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR if protect else ctypes.c_void_p,
                         ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    if not function(ctypes.byref(source), 'AI-PACS support issue' if protect else None,
                    None, None, None, 1, ctypes.byref(output)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if output.size > MAX_PAYLOAD+8192:
            raise ValueError('Invalid protected issue size')
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def diagnostic_bundle(log_root, include_windows):
    from _project_root import PROJECT_ROOT
    logs = collect_log_evidence(log_root, source_root=PROJECT_ROOT)['sources']
    windows = collect_windows_events() if include_windows else {'state':'not_requested', 'events':[]}
    native = collect_native_evidence(log_root, PROJECT_ROOT)
    return {'schema_version':1, 'logs':logs, 'windows_state':windows['state'],
            'windows_events':windows.get('events', []), 'native_state':native['state'],
            'native_logs':native['logs']}


def collect_native_evidence(log_root, source_root):
    """Last seven days by mtime, at most three product-owned native log tails."""
    from .native_fault_log import discover_native_fault_logs, native_fault_log_pid
    from .support_diagnostics import MAX_BYTES, project_source_frames
    try:
        candidates = []
        cutoff = time.time()-7*24*3600
        for path in discover_native_fault_logs(log_root, max_files=256):
            if native_fault_log_pid(path) is None:
                continue  # Legacy shared logs have no verified filename ownership.
            stat = path.stat()
            if stat.st_mtime >= cutoff:
                candidates.append((stat.st_mtime, path))
        logs = []
        for modified, path in sorted(candidates, key=lambda value:value[0], reverse=True)[:3]:
            if path.is_symlink():
                raise ValueError('Invalid native source')
            with path.open('rb') as stream:
                size = os.fstat(stream.fileno()).st_size
                stream.seek(max(0, size-MAX_BYTES))
                data = stream.read(MAX_BYTES)
            if size > MAX_BYTES:
                data = data.partition(b'\n')[2]
            text = data.decode('utf-8', errors='replace')
            logs.append({'source':'native_fault_'+str(len(logs)+1),
                'modified_at':datetime.fromtimestamp(modified, timezone.utc).isoformat(),
                'bytes_read':len(data), 'truncated':size > MAX_BYTES,
                'signals':{'access_violation':text.lower().count('windows fatal exception: access violation'),
                           'fatal_python':text.count('Fatal Python error:'),
                           'hang_stack':len(re.findall(r'^Timeout \(', text, re.MULTILINE))},
                'frames':project_source_frames(text, source_root)})
        return {'state':'sampled' if logs else 'no_recent_sources', 'logs':logs}
    except (OSError, ValueError):
        return {'state':'unavailable', 'logs':[]}


class ProtectedOutbox:
    """One pending issue per account; no fallback to plaintext or adjacent keys."""
    def __init__(self, user, root=None):
        if root is None:
            from .data_paths import USER_DATA_ROOT
            root = USER_DATA_ROOT / 'support-outbox'
        self.path = Path(root) / (sha256(user.encode()).hexdigest()+'.dpapi')

    def load(self):
        if not self.path.exists():
            return None
        if self.path.is_symlink() or self.path.stat().st_size > MAX_PAYLOAD+8192:
            raise ValueError('Invalid pending issue')
        sealed = self.path.read_bytes()
        plain = _dpapi(sealed, False)
        return json.loads(plain)

    def save(self, value):
        plain = json.dumps(value, ensure_ascii=False).encode('utf-8')
        if len(plain) > MAX_PAYLOAD:
            raise ValueError('Issue is too large')
        sealed = _dpapi(plain, True)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or self.path.is_symlink():
            raise ValueError('Invalid outbox location')
        temporary = self.path.with_name(self.path.name+'.'+uuid4().hex+'.tmp')
        # Exclusive creation prevents following a planted temporary symlink.
        try:
            with temporary.open('xb') as stream:
                stream.write(sealed)
                stream.flush()
                import os
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def clear(self):
        self.path.unlink(missing_ok=True)


class HelpTicketArchive:
    """Worker-owned local package; audio is never added to the website payload."""
    def __init__(self, root=None):
        if root is None:
            from .data_paths import USER_DATA_ROOT
            root = USER_DATA_ROOT / 'help-ticket'
        self.root = Path(root)

    def prepare(self, payload, recordings=()):
        import base64
        from zipfile import ZipFile, ZIP_DEFLATED
        identifier = str(UUID(payload['client_issue_id']))
        stamp = datetime.now().astimezone().strftime('%Y-%m-%d_%H-%M-%S')
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('Invalid help ticket location')
        folder = self.root / (stamp + '_' + identifier)
        folder.mkdir()
        package = folder / 'ticket.zip'
        temporary = folder / 'ticket.zip.tmp'
        try:
            with ZipFile(temporary, 'x', ZIP_DEFLATED) as archive:
                archive.writestr('request.json', json.dumps(payload, ensure_ascii=False, indent=2))
                archive.writestr('description.txt', payload['description'])
                archive.writestr('diagnostics.json', json.dumps(payload['diagnostics'], indent=2))
                logs = payload.get('log_archive')
                if logs:
                    archive.writestr('logs.zip', base64.b64decode(logs['base64'], validate=True))
                for index, recording in enumerate(recordings):
                    if not isinstance(recording, bytes) or len(recording) > 24 * 1024 * 1024:
                        raise ValueError('Invalid ticket recording')
                    archive.writestr(f'voice-{index + 1}.wav', recording)
                archive.writestr('manifest.json', json.dumps({'schema_version':1,
                    'client_issue_id':identifier, 'created_at':datetime.now().astimezone().isoformat(),
                    'recordings':len(recordings), 'audio_delivery':'reviewed_website_package'}))
            with ZipFile(temporary) as archive:
                if archive.testzip() is not None:
                    raise ValueError('Help ticket package integrity check failed')
            temporary.replace(package)
            with (folder / 'package.json').open('x', encoding='utf-8') as stream:
                json.dump({'sha256':sha256(package.read_bytes()).hexdigest(),
                           'bytes':package.stat().st_size, 'client_issue_id':identifier}, stream)
        except Exception:
            temporary.unlink(missing_ok=True)
            (folder / 'package.json').unlink(missing_ok=True)
            package.unlink(missing_ok=True)
            folder.rmdir()
            raise
        return folder

    def receipt(self, identifier, result):
        identifier = str(UUID(identifier))
        for folder in self.root.glob('*_' + identifier):
            if folder.is_symlink():
                raise ValueError('Invalid help ticket location')
            temporary = folder / ('receipt-' + uuid4().hex + '.tmp')
            with temporary.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, indent=2)
            temporary.replace(folder / 'receipt.json')


def load_delivery_receipt(user, client):
    from .data_paths import USER_DATA_ROOT
    store = ProtectedOutbox(user, USER_DATA_ROOT / 'support-receipts')
    record = store.load()
    if not record or record.get('base_url') != client.base_url or record.get('identity_binding') != client.support_identity_binding:
        return None
    try:
        if datetime.fromisoformat(record['expires_at']) <= datetime.now(timezone.utc):
            return None
        receipt = record['receipt']
        UUID(receipt['issue_id'])
        return dict(receipt) if receipt.get('state') == 'received' else None
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


class IssueReporter:
    def __init__(self, user, client, store=None, log_root=None, archive_root=None, progress=None, receipt_store=None):
        parsed = urlsplit(client.base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Invalid support destination')
        if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ValueError('Support requires HTTPS')
        self.user, self.client = user, client
        self.identity_binding = client.support_identity_binding
        self.store = store if store is not None else ProtectedOutbox(user)
        if log_root is None:
            from .data_paths import LOGS_DIR
            log_root = LOGS_DIR
        self.log_root = log_root
        self.archive = HelpTicketArchive(archive_root)
        self.progress = progress
        self.receipt_store = receipt_store
        if receipt_store is None and isinstance(self.store, ProtectedOutbox):
            self.receipt_store = ProtectedOutbox(user, self.store.path.parent.parent / 'support-receipts')

    def last_receipt(self):
        """Only the same linked account and endpoint can see a persisted delivery result."""
        if self.receipt_store is None:
            return None
        record = self.receipt_store.load() if self.receipt_store is not None else None
        if not record or record.get('base_url') != self.client.base_url or record.get('identity_binding') != self.identity_binding:
            return None
        if datetime.fromisoformat(record['expires_at']) <= datetime.now(timezone.utc):
            return None
        receipt = record['receipt']
        UUID(receipt['issue_id'])
        return dict(receipt) if receipt.get('state') == 'received' else None


    def submit(self, description, category, include_windows, context, occurred_at=None, include_log_archive=False, recordings=()):
        if not isinstance(description, str) or not 5 <= len(description.strip()) <= 4000:
            raise ValueError('Describe the issue in 5 to 4000 characters')
        if category not in ('crash', 'hang', 'error', 'other') or type(include_windows) is not bool or type(include_log_archive) is not bool:
            raise ValueError('Invalid issue category')
        if context.get('pacs_user') != self.user:
            raise ValueError('Account changed')
        if set(context) - {'app_version','pacs_user','center_id','server_id'}:
            raise ValueError('Invalid support context')
        with _LOCK:
            if self.store.load():
                raise ValueError('Retry or discard the pending issue first')
            now = datetime.now(timezone.utc)
            incident = datetime.fromisoformat(occurred_at) if occurred_at else now
            if incident.tzinfo is None or incident > now:
                raise ValueError('Invalid incident time')
            payload = {'client_issue_id':str(uuid4()), 'category':category,
                'description':description.strip(), 'occurred_at':incident.isoformat(),
                'consent_version':'support-v1', 'context':dict(context),
                'diagnostics':diagnostic_bundle(self.log_root, include_windows)}
            if include_log_archive:
                from .support_log_archive import build_log_archive
                payload['log_archive'] = build_log_archive(self.log_root, now=now)
                payload['consent_version'] = 'support-raw-logs-v2'
            if len(recordings) > 10:
                raise ValueError('Too many ticket recordings')
            import base64
            payload['consent_version'] = 'support-package-v3'
            folder = self.archive.prepare(payload, recordings)
            package = (folder / 'ticket.zip').read_bytes()
            if len(package) > 8 * 1024 * 1024:
                raise ValueError('Help Ticket package exceeds 8 MiB; shorten the recording or reduce attachments')
            payload['ticket_package'] = {'base64':base64.b64encode(package).decode('ascii'),
                'sha256':sha256(package).hexdigest(), 'bytes':len(package)}
            self.store.save({'user':self.user, 'base_url':self.client.base_url,
                             'identity_binding':self.identity_binding,
                             'expires_at':(now+timedelta(days=7)).isoformat(), 'payload':payload})
            return self._send(payload)

    def retry(self):
        with _LOCK:
            record = self.store.load()
            if not record:
                raise ValueError('No pending issue')
            if (record['user'] != self.user or record['base_url'] != self.client.base_url
                    or record['identity_binding'] != self.client.support_identity_binding):
                raise ValueError('Pending issue belongs to another account or endpoint')
            if datetime.fromisoformat(record['expires_at']) <= datetime.now(timezone.utc):
                self.store.clear()
                raise ValueError('Pending issue expired; prepare a new issue')
            return self._send(record['payload'])

    def _request_receipt(self, payload):
        """Large JSON travels in bounded paired chunks, preserving immutable retry identity."""
        import base64
        from modules.Identity.providers.aipacs_web import AipacsWebError
        raw = json.dumps(payload, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        if len(raw) > MAX_PAYLOAD:
            raise ValueError('Support payload exceeds the transport bound')
        if len(raw) <= 49152:
            try:
                return self.client.request_json('POST', '/support/issues', json_body=payload,
                                                allow_redirects=False, timeout=90)
            except AipacsWebError as exc:
                if exc.status_code is not None:
                    raise
                capability = self.client.request_json('GET', '/support/issues/upload-capabilities',
                                                      allow_redirects=False, timeout=30)
                if (not isinstance(capability, dict) or capability.get('protocol') != 1
                        or not isinstance(capability.get('origin_ipv4'), str)):
                    raise exc
                return self.client.request_support_json('/support/issues', payload,
                        origin_ipv4=capability['origin_ipv4'], timeout=90)
        capabilities = self.client.request_json('GET', '/support/issues/upload-capabilities',
                                                allow_redirects=False, timeout=30)
        if not isinstance(capabilities, dict) or {k:v for k,v in capabilities.items() if k != 'origin_ipv4'} != {'protocol':1, 'chunk_bytes':49152, 'max_bytes':MAX_PAYLOAD}:
            raise ValueError('Unsupported support upload protocol')
        origin = capabilities.get('origin_ipv4')
        if origin is not None:
            import ipaddress
            if not isinstance(origin, str) or not ipaddress.IPv4Address(origin).is_global:
                raise ValueError('Invalid support upload origin')
        use_origin = False

        def post(target, body, timeout):
            nonlocal use_origin
            if use_origin:
                return self.client.request_support_json(target, body, origin_ipv4=origin, timeout=timeout)
            try:
                return self.client.request_json('POST', target, json_body=body,
                                                allow_redirects=False, timeout=timeout)
            except AipacsWebError as exc:
                if exc.status_code is not None or origin is None:
                    raise
                # Only a transport failure permits the paired site's advertised
                # same-host TLS origin. HTTP/auth/rejection errors never reroute.
                use_origin = True
                return self.client.request_support_json(target, body, origin_ipv4=origin, timeout=timeout)
        identifier = str(UUID(payload['client_issue_id']))
        path = '/support/issues/uploads/' + identifier
        digest = sha256(raw).hexdigest()
        count = (len(raw)+49151)//49152
        for position in range(count):
            chunk = {'sha256':digest, 'bytes':len(raw), 'count':count,
                     'data':base64.b64encode(raw[position*49152:(position+1)*49152]).decode('ascii')}
            result = post(path+'/chunks/'+str(position), chunk, 30)
            if result != {'state':'chunk_received', 'position':position}:
                raise ValueError('Unconfirmed support upload chunk')
            if self.progress:
                self.progress({'state':'running','completed_chunks':position+1,'total_chunks':count})
        return post(path+'/complete', {'sha256':digest}, 90)

    def _send(self, payload):
        try:
            receipt = self._request_receipt(payload)
            UUID(receipt['issue_id'])
            if receipt.get('state') != 'received' or receipt.get('client_issue_id') != payload['client_issue_id']:
                raise ValueError('Unconfirmed receipt')
        except Exception as exc:
            http_status = getattr(exc, 'status_code', None)
            if type(http_status) is not int or not 100 <= http_status <= 599:
                http_status = None
            code = {401:'WEBSITE_SESSION_EXPIRED', 403:'WEBSITE_PAIRING_REVOKED',
                    404:'SUPPORT_ENDPOINT_UNAVAILABLE', 409:'ISSUE_CONTENT_CONFLICT',
                    413:'ISSUE_REJECTED', 422:'ISSUE_REJECTED', 429:'RATE_LIMITED'}.get(
                        http_status, 'DELIVERY_UNCONFIRMED')
            result = {'state':'pending', 'error_code':code,
                    'http_status':http_status,
                    'failure_stage':'http_response' if http_status else 'transport_or_receipt',
                    'client_issue_id':payload['client_issue_id']}
            try:
                self.archive.receipt(payload['client_issue_id'], result)
            except (OSError, ValueError):
                result['archive_receipt_saved'] = False
            return result
        cleared = True
        try:
            self.store.clear()
        except OSError:
            cleared = False
        result = {'state':'received', 'issue_id':receipt['issue_id'], 'status':receipt.get('status', 'new'),
                'local_copy_cleared':cleared}
        if self.receipt_store is not None:
            try:
                self.receipt_store.save({'base_url':self.client.base_url, 'identity_binding':self.identity_binding,
                    'expires_at':(datetime.now(timezone.utc)+timedelta(days=90)).isoformat(), 'receipt':result})
            except (OSError, ValueError):
                result['delivery_history_saved'] = False
        try:
            self.archive.receipt(payload['client_issue_id'], result)
        except (OSError, ValueError):
            result['archive_receipt_saved'] = False
        return result
