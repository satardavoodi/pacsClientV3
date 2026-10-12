"""Host-provisioned Server console identity, separate from PACS and pairing.

No default password, automatic account creation or authentication fallback.
Only a salted verifier is stored, protected with DPAPI and directory ACLs.
"""
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import threading
import time

from modules.LicenseGenerator.protection import protect, unprotect

_LOCK = threading.Lock()
_FAILURES = {}
_SESSIONS = {}
ITERATIONS = 600_000


def store_path():
    from .administration import settings_role
    if settings_role() != 'server':
        raise ValueError('Server console authentication requires the Server role.')
    base = Path(os.environ.get('ProgramData') or 'C:/ProgramData')
    return base / 'AI-PACS' / 'EagleEyeServer' / 'security' / 'administrator.bin'


def provision(path, username, password):
    """Explicit installer/operator action; refuse to replace an existing identity.

    The operator must provision owner/SYSTEM-only directory ACLs before calling.
    """
    path = Path(path)
    if not path.is_absolute() or not path.parent.is_dir():
        raise ValueError('Provision the protected absolute security directory first.')
    if not username.strip() or len(password) < 12:
        raise ValueError('An account name and a password of at least 12 characters are required.')
    salt = secrets.token_bytes(32)
    verifier = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
    record = {'version': 1, 'username': username, 'role': 'superadmin',
              'salt': salt.hex(), 'verifier': verifier.hex(), 'iterations': ITERATIONS}
    data = protect(json.dumps(record).encode(), machine=False)
    with path.open('xb') as output:
        output.write(data)
    if os.name != 'nt':
        path.chmod(0o600)


def authenticate(username, password, *, path=None):
    """Run in a worker. Fail closed; bounded attempts are per console process."""
    path = Path(path) if path is not None else store_path()
    key = str(path.resolve())
    with _LOCK:
        count, until = _FAILURES.get(key, (0, 0))
        if time.monotonic() < until:
            return None
        try:
            record = json.loads(unprotect(path.read_bytes()))
            if record['version'] != 1 or record['role'] != 'superadmin' or record['iterations'] != ITERATIONS:
                raise ValueError('Unsupported identity.')
            salt = bytes.fromhex(record['salt'])
            expected = bytes.fromhex(record['verifier'])
            if len(salt) != 32 or len(expected) != 32:
                raise ValueError('Invalid verifier.')
            actual = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, ITERATIONS)
            valid = hmac.compare_digest(actual, expected) and hmac.compare_digest(
                username.casefold().encode(), record['username'].casefold().encode())
        except (OSError, ValueError, KeyError, TypeError):
            valid = False
        if not valid:
            count += 1
            _FAILURES[key] = (count, time.monotonic() + (60 if count >= 5 else 1))
            return None
        _FAILURES.pop(key, None)
        session = secrets.token_urlsafe(32)
        user = {'username': record['username'], 'full_name': record['username'], 'role': 'superadmin',
                'auth_source': 'eagle-eye-console'}
        _SESSIONS[session] = (time.monotonic() + 8 * 3600, user)
        return {'session': session, 'user': dict(user)}


def valid_session(session):
    with _LOCK:
        expires, _ = _SESSIONS.get(session, (0, None))
        return expires > time.monotonic()


def _upstream_administrator(username, password):
    """PACS first, then Reception after an explicit credential rejection only."""
    from .pacs_identity import PacsIdentity
    from .reception_identity import ReceptionIdentity
    from .user_access import upstream_denial
    config_path = Path(os.environ['AIPACS_EAGLE_EYE_SERVER_CONFIG'])
    if not config_path.is_absolute():
        raise ValueError('Select an absolute Server configuration.')
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    providers = (config.get('user_access') or {}).get('providers')
    providers = providers if providers is not None else {'pacs': config.get('pacs')}
    if providers.get('pacs'):
        try:
            return PacsIdentity(providers['pacs']).login_console(username, password)
        except Exception as error:
            # An authenticated non-admin and an unavailable authority do not
            # permit switching identities to gain console privileges.
            if upstream_denial(error).status != 401:
                raise
    if providers.get('reception'):
        return ReceptionIdentity(providers['reception']).login_console(username, password)
    raise PermissionError('No administrator authority accepted this login.')


def authenticate_console(username, password):
    """Worker-only console admission; never create a remote AI user session."""
    result = authenticate(username, password)
    if result:
        return result
    key = 'upstream-console'
    with _LOCK:
        count, until = _FAILURES.get(key, (0, 0))
        if time.monotonic() < until:
            return None
    try:
        identity = _upstream_administrator(username, password)
    except Exception:
        with _LOCK:
            count += 1
            _FAILURES[key] = (count, time.monotonic() + (60 if count >= 5 else 1))
        return None
    user = dict(identity, full_name=identity['username'], role='admin',
                auth_source=identity['provider'])
    session = secrets.token_urlsafe(32)
    with _LOCK:
        _FAILURES.pop(key, None)
        _SESSIONS[session] = (time.monotonic() + 8 * 3600, user)
    return {'session': session, 'user': user}


def invalidate_session(session):
    with _LOCK:
        _SESSIONS.pop(session, None)
    from .user_session import invalidate_console_context
    invalidate_console_context(session)
