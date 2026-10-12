"""Offline licensing service for Client and the independently managed server.

All callers must run storage/hardware operations off the Qt GUI thread. Signed
responses set an absolute expiry and are bound to the persisted request/base.
"""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

from .license_manager import LicenseManager as LegacyVerifier
from .legacy_proof import legacy_claim
from .protection import protect, unprotect
from .signed_license import (LicenseError, PRODUCTS, code_digest, decode_request,
                             decode_token, encode_request, normalize, parse_time,
                             timestamp, utc)
from .signing_trust import TRUSTED_KEYS

_LOCKS = {}
_LOCKS_LOCK = threading.Lock()




class RenewalLicenseManager:
    def __init__(self, *, directory=None, product='client', trusted_keys=None, clock=None):
        if product not in PRODUCTS:
            raise LicenseError('Unsupported license product.')
        self.product = product
        self.legacy = LegacyVerifier()
        self.directory = Path(directory) if directory is not None else self.legacy.app_data_dir
        self.license_path = self.directory / ('license.dat' if product == 'client' else 'server-license.dat')
        self.trusted_keys = TRUSTED_KEYS if trusted_keys is None else trusted_keys
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        with _LOCKS_LOCK:
            self.lock = _LOCKS.setdefault(str(self.license_path.resolve()).lower(), threading.RLock())

    @contextmanager
    def _exclusive(self):
        """Serialize the service and desktop across processes, including atomic saves."""
        with self.lock:
            self.directory.mkdir(parents=True, exist_ok=True)
            fd = os.open(self.license_path.with_suffix('.lock'), os.O_RDWR | os.O_CREAT, 0o600)
            acquired = False
            try:
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b'\0')
                deadline = time.monotonic() + 5
                while True:
                    try:
                        os.lseek(fd, 0, os.SEEK_SET)
                        if os.name == 'nt':
                            import msvcrt
                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        acquired = True
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise LicenseError('Another licensing operation is busy. Try again shortly.') from None
                        time.sleep(.05)
                yield
            finally:
                if acquired:
                    os.lseek(fd, 0, os.SEEK_SET)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read(self):
        if not self.license_path.exists():
            return {}
        raw = self.license_path.read_bytes()
        if len(raw) > 131072:
            raise LicenseError('Licensing storage is invalid.')
        try:
            if raw.startswith((b'DPAPI3\0', b'PLAIN3\0')):
                state = json.loads(unprotect(raw))
            else:
                state = json.loads(raw)  # Existing legacy JSON is read without migration side effects.
                if isinstance(state, dict) and (state.get('version') == 3 or
                        str(state.get('license_key', '')).startswith('AIP3.')):
                    raise ValueError
            if not isinstance(state, dict) or not isinstance(state.get('license_key', ''), str):
                raise ValueError
            if state.get('version') == 3:
                parse_time(state['last_seen'])
                if type(state.get('signed_revision')) is not int or state['signed_revision'] < 0:
                    raise ValueError
            elif state.get('version') is not None:
                raise ValueError
            return state
        except (ValueError, KeyError, TypeError, OSError):
            raise LicenseError('Licensing storage is corrupt or cannot be unlocked.') from None

    def _write(self, state):
        self.directory.mkdir(parents=True, exist_ok=True)
        raw = protect(json.dumps(state, sort_keys=True, allow_nan=False).encode('utf-8'),
                      machine=self.product == 'eagle-eye-server')
        temporary = self.license_path.with_name(self.license_path.name + '.' + uuid.uuid4().hex + '.partial')
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(raw)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.license_path)
        finally:
            temporary.unlink(missing_ok=True)

    def _time(self, state):
        now = utc(self.clock())
        if state.get('last_seen') and now + timedelta(minutes=5) < parse_time(state['last_seen']):
            raise LicenseError('The system clock moved backwards. Correct the clock before continuing.')
        return now

    def _claim(self, state):
        code = state.get('license_key', '')
        if not code:
            if state.get('signed_revision', 0):
                raise LicenseError('The signed license is missing. Contact support.')
            return None
        if code.startswith('AIP3.'):
            claim = decode_token(code, self.trusted_keys, hardware_id=self.get_hardware_id(), product=self.product)
            if state.get('signed_revision') != claim['revision']:
                raise LicenseError('Stored license revision does not match its signed entitlement.')
            return claim
        if state.get('signed_revision', 0) or self.product != 'client':
            raise LicenseError('A signed license is required for this product.')
        for hardware_id, _ in self.legacy._current_candidate_ids():
            try:
                return legacy_claim(code, hardware_id)
            except LicenseError:
                continue
        raise LicenseError('The existing license does not match this device.')

    def get_hardware_id(self):
        return self.legacy.get_hardware_id(log=False)

    def status(self):
        try:
            with self._exclusive():
                state = self._read()
                now = self._time(state)
                claim = self._claim(state)
                if claim is None:
                    return {'valid': False, 'product': self.product, 'days_remaining': 0,
                            'message': 'No license found. Generate an activation request.'}
                remaining = max(0, math.ceil((parse_time(claim['expires_at']) - now).total_seconds() / 86400))
                if not claim.get('legacy') and (not state.get('last_seen') or
                        now >= parse_time(state['last_seen']) + timedelta(hours=1)):
                    self._write({**state, 'last_seen': timestamp(now)})
                valid = parse_time(claim['expires_at']) > now
                return {**claim, 'valid': valid, 'days_remaining': remaining,
                        'message': f'License is valid. {remaining} days remaining' if valid else 'License has expired'}
        except (LicenseError, OSError):
            return {'valid': False, 'product': self.product, 'days_remaining': 0,
                    'message': 'License unavailable, invalid, or clock verification failed. Open Manage License.'}

    def check_license(self):
        status = self.status()
        return status['valid'], status['message']

    def generate_request(self):
        with self._exclusive():
            state = self._read()
            now = self._time(state)
            claim = self._claim(state)
            previous = state.get('license_key', '')
            hardware_id = self.get_hardware_id()
            pending = state.get('pending_request')
            if pending:
                request = decode_request(pending)
                if (request['previous_license'] == previous and request['hardware_id'] == hardware_id
                        and now - parse_time(request['created_at']) < timedelta(days=30)):
                    return pending
            request = encode_request({'version': 3, 'request_id': uuid.uuid4().hex,
                'hardware_id': hardware_id, 'product': self.product, 'created_at': timestamp(now),
                'previous_license': previous,
                'previous_hardware_id': claim['hardware_id'] if claim else hardware_id})
            self._write({**state, 'version': 3, 'license_key': previous,
                         'signed_revision': state.get('signed_revision', 0),
                         'last_seen': timestamp(now), 'pending_request': request})
            return request

    def _preview(self, code, state):
        now = self._time(state)
        code = normalize(code)
        claim = decode_token(code, self.trusted_keys, hardware_id=self.get_hardware_id(), product=self.product)
        if parse_time(claim['issued_at']) > now + timedelta(minutes=5):
            raise LicenseError('This license was issued in the future. Check the system clock.')
        if parse_time(claim['expires_at']) <= now:
            raise LicenseError('The received license has expired.')
        previous = self._claim(state)
        already = code == state.get('license_key')
        if not already:
            request = decode_request(state.get('pending_request', ''))
            if claim['request_id'] != request['request_id']:
                raise LicenseError('This response belongs to another request. Use the latest request sent to support.')
            if claim['previous_digest'] != code_digest(state.get('license_key', '')):
                raise LicenseError('The license changed after this request. Generate a new request.')
            revision = previous['revision'] if previous else 0
            if claim['revision'] != revision + 1:
                raise LicenseError('The received license revision is not the next revision.')
            if previous and not previous.get('legacy') and claim['license_id'] != previous['license_id']:
                raise LicenseError('The received license belongs to a different entitlement.')
            if previous and parse_time(claim['expires_at']) <= parse_time(previous['expires_at']):
                raise LicenseError('The received license does not extend the current expiry.')
        return {**claim, 'already_applied': already,
                'previous_expiry': previous['expires_at'] if previous else None,
                'days_remaining': max(0, math.ceil((parse_time(claim['expires_at']) - now).total_seconds() / 86400))}

    def preview(self, code):
        with self._exclusive():
            return self._preview(code, self._read())

    def save_license(self, code):
        try:
            with self._exclusive():
                state = self._read()
                code = normalize(code)
                if not code.startswith('AIP3.'):
                    # Preserve install-time legacy activation only, never legacy replacement/renewal.
                    if self.product != 'client' or state.get('license_key') or state.get('signed_revision', 0):
                        raise LicenseError('Renewals require a signed company response.')
                    candidates = self.legacy._current_candidate_ids()
                    valid = next((legacy_claim(code, mid) for mid, _ in candidates
                                  if self._matches_legacy(code, mid)), None)
                    if valid is None or parse_time(valid['expires_at']) <= self._time(state):
                        raise LicenseError('Invalid or expired legacy activation key.')
                    self._write({'version': 3, 'license_key': code, 'signed_revision': 0,
                                 'last_seen': timestamp(self.clock())})
                    return True, 'Legacy license activated. Use a signed response for future renewals.'
                preview = self._preview(code, state)
                if preview['already_applied']:
                    return True, 'This license is already applied. No additional credit was added.'
                self._write({'version': 3, 'license_key': code, 'signed_revision': preview['revision'],
                             'last_seen': timestamp(self.clock())})
                return True, f"License updated. {preview['days_remaining']} days remaining."
        except LicenseError as exc:
            return False, str(exc)
        except (OSError, ValueError, TypeError):
            return False, 'Could not save the license. The previous license was preserved.'

    @staticmethod
    def _matches_legacy(code, hardware_id):
        try:
            legacy_claim(code, hardware_id)
            return True
        except LicenseError:
            return False


def server_manager(config):
    """One explicit shared service store; never the interactive user's APPDATA."""
    directory = config.get('license_directory')
    if directory is None:
        directory = str(Path(config['job_root']).resolve().parent / 'licensing')
    if not isinstance(directory, str) or not Path(directory).is_absolute():
        raise LicenseError('The server licensing directory must be an absolute path.')
    return RenewalLicenseManager(directory=directory, product='eagle-eye-server')


def create_manager():
    from modules.ai_imaging.eagle_eye_remote.administration import settings_role
    if settings_role() == 'server':
        path = os.environ.get('AIPACS_EAGLE_EYE_SERVER_CONFIG')
        if not path or not Path(path).is_absolute():
            raise LicenseError('Launch with the Eagle Eye server deployment configuration to manage its license.')
        return server_manager(json.loads(Path(path).read_text(encoding='utf-8-sig')))
    return RenewalLicenseManager()
