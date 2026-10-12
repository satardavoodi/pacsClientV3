"""Two independent user gates: upstream identity and Eagle Eye grants.

Ordinary requests use verified human sessions. Passwords and upstream tokens never
enter the identity/audit database; opaque sessions live in this process only.
"""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import secrets
import sqlite3
import threading
import time

from .contracts import MODULES


class UserDenied(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code
        super().__init__(code)


def upstream_denial(error):
    """Separate temporary authority outages from rejected identity, without details."""
    if isinstance(error, UserDenied):
        return error
    import requests
    from .reception_identity import ReceptionIdentityUnavailable
    if isinstance(error, (requests.RequestException, ConnectionError, TimeoutError)) or (
            isinstance(error, ReceptionIdentityUnavailable) and error.status == 503):
        return UserDenied(503, 'UPSTREAM_IDENTITY_UNAVAILABLE')
    return UserDenied(401, 'UPSTREAM_AUTHENTICATION_FAILED')


def stable_identity(provider, value):
    if provider not in ('pacs', 'reception') or not isinstance(value, dict):
        raise UserDenied(401, 'UPSTREAM_IDENTITY_INVALID')
    subject = value.get('subject', value.get('id', value.get('_id')))
    username = value.get('username')
    if (type(subject) not in (str, int) or not str(subject).strip() or len(str(subject)) > 256
            or not isinstance(username, str) or not username.strip() or len(username) > 256
            or any(ord(c) < 32 for c in str(subject) + username)
            or value.get('is_active') is False):
        raise UserDenied(401, 'UPSTREAM_IDENTITY_INVALID')
    return dict(provider=provider, subject=str(subject), username=username)


class AccessStore:
    def __init__(self, path, center):
        self.path, self.center = Path(path), center
        if not self.path.is_absolute() or not isinstance(center, str) or not center:
            raise ValueError('Configure an absolute Eagle Eye access database and center.')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS scope (center TEXT PRIMARY KEY)')
            scope = db.execute('SELECT center FROM scope').fetchone()
            if scope and scope[0] != center:
                raise ValueError('The user access store belongs to another center.')
            db.execute('INSERT OR IGNORE INTO scope VALUES (?)', (center,))
            db.execute('''CREATE TABLE IF NOT EXISTS users (
                principal TEXT PRIMARY KEY, provider TEXT NOT NULL, subject TEXT NOT NULL,
                username TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
                echomind INTEGER NOT NULL DEFAULT 0, imaging INTEGER NOT NULL DEFAULT 0,
                crm INTEGER NOT NULL DEFAULT 0, secretary INTEGER NOT NULL DEFAULT 0,
                modules TEXT NOT NULL DEFAULT '[]')''')
            db.execute('''CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY, principal TEXT, device TEXT, operation TEXT NOT NULL,
                outcome TEXT NOT NULL, occurred_at REAL NOT NULL)''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    def identify(self, identity):
        identity = stable_identity(identity['provider'], identity)
        key = hashlib.sha256(json.dumps([self.center, identity['provider'], identity['subject']]).encode()).hexdigest()
        with closing(self.connect()) as db, db:
            db.execute('''INSERT INTO users(principal,provider,subject,username) VALUES (?,?,?,?)
                ON CONFLICT(principal) DO UPDATE SET username=excluded.username''',
                (key, identity['provider'], identity['subject'], identity['username']))
        return key

    def user(self, principal):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM users WHERE principal=?', (principal,)).fetchone()
        if row is None:
            raise UserDenied(403, 'EAGLE_USER_NOT_APPROVED')
        result = dict(row)
        result['modules'] = json.loads(result['modules'])
        return result

    def users(self):
        with closing(self.connect()) as db:
            return [dict(row, modules=json.loads(row['modules'])) for row in db.execute('SELECT * FROM users ORDER BY username,principal')]

    def grant(self, principal, changes, actor):
        allowed = {'enabled', 'echomind', 'imaging', 'crm', 'secretary', 'modules'}
        if set(changes) != allowed or any(type(changes[k]) is not bool for k in allowed - {'modules'}):
            raise ValueError('Supply the complete explicit user grant.')
        if (not isinstance(changes['modules'], list) or set(changes['modules']) - set(MODULES)
                or len(changes['modules']) != len(set(changes['modules']))):
            raise ValueError('Unknown or repeated imaging module.')
        with closing(self.connect()) as db, db:
            cursor = db.execute('''UPDATE users SET enabled=?,echomind=?,imaging=?,crm=?,secretary=?,modules=?
                WHERE principal=?''', tuple(changes[k] for k in ('enabled','echomind','imaging','crm','secretary')) +
                (json.dumps(changes['modules']), principal))
            if cursor.rowcount != 1:
                raise ValueError('Unknown upstream user.')
            db.execute('INSERT INTO events VALUES (?,?,?,?,?,?)',
                (secrets.token_hex(16), principal, actor, 'grant_changed', json.dumps(changes, sort_keys=True), time.time()))

    def event(self, principal, device, operation, outcome, request_id=None):
        # Only fixed operation labels and opaque IDs belong in this audit.
        if not operation or len(operation) > 128:
            raise ValueError('Invalid audit operation.')
        key = secrets.token_hex(16) if request_id is None else hashlib.sha256(
            json.dumps([principal, device, operation, request_id]).encode()).hexdigest()
        with closing(self.connect()) as db, db:
            db.execute('''INSERT INTO events VALUES (?,?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE
                SET outcome=CASE WHEN events.outcome IN ('succeeded','failed','cancelled','interrupted')
                THEN events.outcome ELSE excluded.outcome END''',
                       (key, principal, device, operation, outcome, time.time()))

    def audit(self, principal):
        with closing(self.connect()) as db:
            counts = [dict(row) for row in db.execute('''SELECT operation,outcome,COUNT(*) AS requests
                FROM events WHERE principal=? GROUP BY operation,outcome''', (principal,))]
            events = [dict(row) for row in db.execute('''SELECT device,operation,outcome,occurred_at
                FROM events WHERE principal=? ORDER BY occurred_at DESC LIMIT 100''', (principal,))]
        return {'counts': counts, 'events': events}


class UserAuthority:
    def __init__(self, store, providers):
        if set(providers) - {'pacs', 'reception'}:
            raise ValueError('Only PACS and Reception may authenticate remote users.')
        self.store, self.providers = store, providers
        self.lock = threading.Lock()
        self.sessions = {}
        self.attempts = {}
        self.slots = threading.BoundedSemaphore(4)

    def login(self, device, body, *, peer=None):
        if not isinstance(body, dict):
            raise UserDenied(401, 'UPSTREAM_CREDENTIALS_REQUIRED')
        password_mode = set(body) in ({'username', 'password'}, {'provider', 'username', 'password'})
        values = [body.get('username'), body.get('password')]
        if not password_mode or any(not isinstance(v, str) or not v or len(v) > 8192 for v in values):
            raise UserDenied(401, 'UPSTREAM_CREDENTIALS_REQUIRED')
        with self.lock:
            now = time.monotonic()
            bucket = peer if peer is not None else device
            self.attempts = {key:value for key,value in self.attempts.items() if now-value[1] <= 60}
            if bucket not in self.attempts and len(self.attempts) >= 4096:
                raise UserDenied(429, 'USER_LOGIN_RATE_LIMIT')
            count, start = self.attempts.get(bucket, (0, now))
            if now - start > 60:
                count, start = 0, now
            if count >= 10:
                raise UserDenied(429, 'USER_LOGIN_RATE_LIMIT')
            self.attempts[bucket] = (count + 1, start)
        if not self.slots.acquire(blocking=False):
            raise UserDenied(429, 'UPSTREAM_AUTH_BUSY')
        try:
            # Only the server chooses the credential authority. Local grant
            # denial happens after resolution and never tries another person.
            for provider in ('pacs', 'reception'):
                adapter = self.providers.get(provider)
                if adapter is None:
                    continue
                if getattr(adapter, 'available', True) is False:
                    raise UserDenied(503, 'UPSTREAM_IDENTITY_UNAVAILABLE')
                try:
                    token, identity = adapter.login(body['username'], body['password'])
                except Exception as error:
                    denial = error if isinstance(error, UserDenied) else upstream_denial(error)
                    if denial.status != 401:
                        raise denial from None
                    continue
                verified = adapter.verify(token)
                if stable_identity(provider, identity) != stable_identity(provider, verified):
                    raise UserDenied(401, 'UPSTREAM_IDENTITY_CHANGED')
                break
            else:
                raise UserDenied(401, 'UPSTREAM_AUTHENTICATION_FAILED')
            identity = stable_identity(provider, identity)
            principal = self.store.identify(identity)
            if not self.store.user(principal)['enabled']:
                self.store.event(principal, device, 'login', 'denied')
                raise UserDenied(403, 'EAGLE_USER_NOT_APPROVED')
            session = secrets.token_urlsafe(32)
            with self.lock:
                now = time.monotonic()
                self.sessions = {k:v for k,v in self.sessions.items() if v['expires'] > now}
                if len(self.sessions) >= 512:
                    raise UserDenied(429, 'USER_SESSION_LIMIT')
                self.sessions[hashlib.sha256(session.encode()).hexdigest()] = dict(
                    principal=principal, device=device, provider=provider, token=token,
                    identity=identity, expires=now + 3600)
            self.store.event(principal, device, 'login', 'succeeded')
            return {'user_session': session, 'expires_in': 3600, 'user': self.store.user(principal)}
        except UserDenied:
            raise
        except Exception as error:
            raise upstream_denial(error) from None
        finally:
            self.slots.release()

    def _transport_record(self, device, session):
        if not isinstance(session, str) or not 32 <= len(session) <= 256:
            raise UserDenied(401, 'USER_SESSION_REQUIRED')
        key = hashlib.sha256(session.encode()).hexdigest()
        with self.lock:
            value = dict(self.sessions.get(key, {}))
        if not value or (device is not None and value['device'] != device) or value['expires'] <= time.monotonic():
            raise UserDenied(401, 'USER_SESSION_REQUIRED')
        return value

    def verify_transport(self, device, session, feature):
        """Validate local session liveness; never authorize upstream business work."""
        value = self._transport_record(device, session)
        user = self.store.user(value['principal'])
        self.require(user, feature)
        return user

    def verify(self, device, session):
        if not isinstance(session, str) or not 32 <= len(session) <= 256:
            raise UserDenied(401, 'USER_SESSION_REQUIRED')
        key = hashlib.sha256(session.encode()).hexdigest()
        with self.lock:
            value = dict(self.sessions.get(key, {}))
        if not value or (device is not None and value['device'] != device) or value['expires'] <= time.monotonic():
            raise UserDenied(401, 'USER_SESSION_REQUIRED')
        if not self.slots.acquire(blocking=False):
            raise UserDenied(429, 'UPSTREAM_AUTH_BUSY')
        try:
            upstream = stable_identity(value['provider'], self.providers[value['provider']].verify(value['token']))
            if upstream != value['identity']:
                raise UserDenied(401, 'UPSTREAM_IDENTITY_CHANGED')
        except Exception as error:
            denial = upstream_denial(error)
            if denial.status == 401:
                with self.lock:
                    self.sessions.pop(key, None)
            raise denial from None
        finally:
            self.slots.release()
        user = self.store.user(value['principal'])
        if not user['enabled']:
            raise UserDenied(403, 'EAGLE_USER_DISABLED')
        return user

    def refresh(self, device, session):
        """Renew a live Secretary lease only after fresh upstream authorization."""
        self.verify_transport(device, session, 'secretary')
        key = hashlib.sha256(session.encode()).hexdigest()
        with self.lock:
            original = self.sessions.get(key)
        user = self.verify(device, session)
        self.require(user, 'secretary')
        with self.lock:
            current = self.sessions.get(key)
            if (current is not original or current is None
                    or current['expires'] <= time.monotonic()
                    or current['device'] != device):
                raise UserDenied(401, 'USER_SESSION_REQUIRED')
            # Recheck local revocation after the upstream call, before extension.
            user = self.store.user(current['principal'])
            self.require(user, 'secretary')
            current['expires'] = time.monotonic() + 3600
        return {'user_session': session, 'expires_in': 3600, 'user': user}

    def available_grants(self, principal):
        user = self.store.user(principal)
        if not user['enabled']:
            raise UserDenied(403, 'EAGLE_USER_DISABLED')
        return user

    def logout(self, device, session):
        key = hashlib.sha256(session.encode()).hexdigest()
        with self.lock:
            value = self.sessions.get(key)
            if value and (device is None or value['device'] == device):
                self.sessions.pop(key, None)
        if value and (device is None or value['device'] == device):
            self.store.event(value['principal'], device or 'human-session', 'logout', 'succeeded')

    def require(self, user, feature, module=None):
        if not user.get('enabled') or not user.get(feature):
            raise UserDenied(403, 'EAGLE_PERMISSION_DENIED')
        if feature == 'imaging' and module is not None and module not in user['modules']:
            raise UserDenied(403, 'EAGLE_MODULE_DENIED')


def create_authority(config):
    from .pacs_identity import PacsIdentity
    settings = config.get('user_access') or {}
    providers = {}
    configured = settings.get('providers')
    if configured is None:
        pacs = config.get('pacs') or {}
        configured = {'pacs': {k:pacs[k] for k in ('url','socket_port','ca_file') if k in pacs}} if pacs.get('url') else {}
    for name, value in configured.items():
        if name == 'pacs':
            providers[name] = PacsIdentity(value)
        elif name == 'reception':
            from .reception_identity import ReceptionIdentity
            providers[name] = ReceptionIdentity(value)
        else:
            raise ValueError('Unknown identity provider.')
    path = settings.get('database') or str(Path(config['job_root']).parent / 'user-access.sqlite3')
    return UserAuthority(AccessStore(path, config.get('center_id', 'configured-pacs')), providers)
