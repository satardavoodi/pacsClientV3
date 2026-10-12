"""Process-local human sessions; no password persistence or inference replay."""
import threading
import time

_lock = threading.RLock()
_exchange_lock = threading.Lock()
_sessions = {}
_epoch = 0
_explicit_login = False
_parent_bridge = None
_login_credentials = None
_console_login_binding = None


def clear():
    global _epoch, _login_credentials, _console_login_binding
    with _lock:
        _login_credentials = None
        _console_login_binding = None
        revoked = [value.get('revocation') for value in _sessions.values()]
        _sessions.clear()
        _epoch += 1
    from .session_revocation import schedule
    for item in revoked:
        if item is not None:
            schedule(item)


def clear_if_current(generation):
    """A late rejected request cannot revoke a newer successful human login."""
    with _lock:
        if identity()[0] != generation:
            return False
        clear()
        return True


def install_parent_bridge(bridge):
    """Install the resident child's private IPC admission source."""
    global _parent_bridge
    _parent_bridge = bridge


def has_login_context():
    """Memory-only UI readiness hint; server admission/grants remain authoritative."""
    generation, _token = identity()
    with _lock:
        return bool(_login_credentials is not None and _login_credentials[0] == generation)


def _pacs_login_changed():
    global _explicit_login
    with _lock:
        _explicit_login = False
        clear()


def capture_login(username, password, *, token_generation=None, expected_generation=None,
                  expected_provider=None, expected_subject=None):
    """Called after ordinary successful login/token publication; memory only."""
    global _login_credentials, _explicit_login
    if (not isinstance(username, str) or not username or len(username) > 256
            or not isinstance(password, str) or not password or len(password) > 4096):
        return None
    if ((expected_provider is None) != (expected_subject is None)
            or expected_provider is not None and (expected_provider not in ('pacs','reception')
            or not isinstance(expected_subject,str) or not expected_subject.strip()
            or len(expected_subject)>256 or any(ord(c)<32 for c in expected_subject))):
        return None
    identity()  # Register account-change invalidation before retaining credentials.
    with _lock:
        if expected_generation is not None and identity()[0] != expected_generation:
            return None
        clear()
        generation, _token = identity()
        if token_generation is not None and generation[0] != token_generation:
            return None
        _login_credentials = ((generation, username, password) if expected_provider is None
                              else (generation, username, password, expected_provider, expected_subject))
        _explicit_login = False
    return generation


def invalidate_console_context(session_id):
    """Only the console that published the current context can revoke it."""
    with _lock:
        binding = _console_login_binding
        if (not isinstance(session_id,str) or binding is None
                or binding != (session_id, identity()[0])):
            return False
        clear()
        return True


class ConsoleLoginContext:
    """One bounded, memory-only attempt; no authentication or network work."""
    def __init__(self):
        self.pending = None

    def begin(self, username, password):
        from uuid import uuid4
        clear()
        operation = 'console:' + uuid4().hex
        self.pending = None
        if (isinstance(username,str) and 0<len(username)<=256
                and isinstance(password,str) and 0<len(password)<=4096):
            self.pending = (operation, identity()[0], username, password)
        return operation

    def is_current(self, operation):
        return self.pending is not None and self.pending[0] == operation

    def cancel(self):
        self.pending = None
        clear()

    def accept(self, operation, result, validate_console):
        global _console_login_binding
        if not self.is_current(operation):
            return False
        _, generation, username, password = self.pending
        self.pending = None
        if (identity()[0] != generation or not isinstance(result,dict)
                or not validate_console(result.get('session'))):
            return False
        user = result.get('user')
        if not isinstance(user,dict):
            return False
        provider = user.get('auth_source')
        if provider == 'eagle-eye-console':
            return True  # Local console admission never implies an AI identity.
        if provider not in ('pacs','reception') or user.get('provider') != provider:
            return False
        captured = capture_login(username,password,expected_generation=generation,
            expected_provider=provider,expected_subject=user.get('subject'))
        if captured is None:
            return False
        with _lock:
            if identity()[0] != captured:
                return False
            _console_login_binding = (result['session'],captured)
        return True


def identity():
    try:
        from modules.network.socket_token_manager import get_socket_token_manager
    except ModuleNotFoundError as exc:
        if exc.name not in ('modules', 'modules.network', 'modules.network.socket_token_manager'):
            raise
        # A standalone viewer has no human session until an explicit IPC handoff exists.
        return (0, _epoch), None
    manager = get_socket_token_manager()
    manager.on_identity_change(_pacs_login_changed)
    generation, token = manager.identity_snapshot()
    with _lock:
        return (generation, _epoch), token


def _key(client, generation):
    return (client.url, client.token, getattr(client, '_profile_key', None), generation)


def _confirmed(value, provider):
    human = value.get('user') if isinstance(value, dict) else None
    opaque = value.get('user_session') if isinstance(value, dict) else None
    lifetime = value.get('expires_in') if isinstance(value, dict) else None
    if (not isinstance(opaque, str) or not 32 <= len(opaque) <= 256
            or any(ord(c) < 33 or ord(c) > 126 for c in opaque)
            or type(lifetime) is not int or not 0 < lifetime <= 3600
            or not isinstance(human, dict) or human.get('provider') not in ('pacs', 'reception')
            or (provider is not None and human.get('provider') != provider)
            or not isinstance(human.get('principal'), str) or not human['principal']):
        raise ValueError('Invalid Eagle Eye human session response.')
    return dict(session=opaque, principal=human['principal'],
                provider=human['provider'], deadline=time.monotonic() + max(0, lifetime - 5))


def confirmed_admission(client):
    """Pure in-memory GUI admission check; returns no credential material."""
    from .client import ServerHTTPError
    generation, _token = identity()
    with _lock:
        cached = _sessions.get(_key(client, generation))
        if (getattr(client, '_human_generation', None) != generation or cached is None
                or cached['deadline'] <= time.monotonic()):
            raise ServerHTTPError(401, 'The human sign-in changed or expired. Sign in again.',
                                  error_code='USER_SESSION_CHANGED')
        return dict(generation=generation, provider=cached['provider'], principal=cached['principal'])


def authenticate(client, provider, username, password):
    """Legacy worker compatibility; provider resolution belongs to the server."""
    global _explicit_login
    if _parent_bridge is not None:
        from .client import ServerHTTPError
        raise ServerHTTPError(401, 'Sign in through the parent AI-PACS application.')
    with _exchange_lock:
        with _lock:
            clear()
            _explicit_login = True
            generation, _token = identity()
        value = client.json('/v1/auth/session', dict(username=username, password=password))
        require_generation(generation)
        cached = _confirmed(value, None)
        cached['revocation'] = (client.url, client.opener, '', cached['session'])
        with _lock:
            require_generation(generation)
            client._human_generation = generation
            _sessions[_key(client, generation)] = cached
    return value['user']


def require_generation(generation):
    from .client import ServerHTTPError
    if isinstance(generation, tuple) and generation[0] == 'parent':
        if _parent_bridge is None:
            raise ServerHTTPError(401, 'The parent human session is unavailable.')
        _parent_bridge.validate(generation[1])
        return
    if identity()[0] != generation:
        raise ServerHTTPError(401, 'The signed-in user changed. Sign in again before continuing.',
                              error_code='USER_SESSION_CHANGED')


def session(client):
    from .client import ServerHTTPError
    if _parent_bridge is not None:
        return _parent_bridge.session(client)
    generation, _token = identity()
    key = _key(client, generation)
    with _lock:
        cached = _sessions.get(key)
        explicit = _explicit_login
        credentials = _login_credentials
    if (credentials is None or explicit) and (cached is None or cached['deadline'] <= time.monotonic()):
        raise ServerHTTPError(401, 'Sign in to PACS or Reception before using Eagle Eye.',
                              error_code='USER_SIGN_IN_REQUIRED')
    bound = getattr(client, '_human_generation', generation)
    require_generation(bound)
    client._human_generation = generation
    # Never hold the cache lock during network I/O or login/logout invalidation.
    with _exchange_lock:
        with _lock:
            cached = _sessions.get(key)
        if cached is None or cached['deadline'] <= time.monotonic():
            require_generation(generation)
            if credentials is None or explicit:
                raise ServerHTTPError(401, 'Sign in to PACS or Reception before using Eagle Eye.',
                                      error_code='USER_SIGN_IN_REQUIRED')
            require_generation(credentials[0])
            body = dict(username=credentials[1], password=credentials[2])
            value = client.json('/v1/auth/session', body)
            require_generation(generation)
            cached = _confirmed(value, None)
            if credentials is not None and len(credentials)>3 and credentials[3] is not None:
                human = value.get('user',{})
                if human.get('provider') != credentials[3] or human.get('subject') != credentials[4]:
                    raise ServerHTTPError(401, 'The authenticated identity differs from the current Server sign-in.',
                                          error_code='USER_IDENTITY_CHANGED')
            cached['revocation'] = (client.url, client.opener, '', cached['session'])
            with _lock:
                require_generation(generation)
                _sessions[key] = cached
    require_generation(generation)
    return cached['session'], cached['principal'], generation


def require_native_session(client, opaque, generation):
    """Check an existing native lease in memory; never create or renew one."""
    from .client import ServerHTTPError
    require_generation(generation)
    with _lock:
        cached = _sessions.get(_key(client, generation))
        if (getattr(client, '_human_generation', None) != generation or cached is None
                or cached['session'] != opaque or cached['deadline'] <= time.monotonic()):
            raise ServerHTTPError(401, 'The native human session changed or expired.',
                                  error_code='USER_SESSION_CHANGED')
        return cached


def invalidate_native_session(client, opaque, generation):
    """A late denied refresh must never clear a newer human login."""
    with _lock:
        require_native_session(client, opaque, generation)
        clear()


def renew_native(client, opaque, principal, generation, *, is_current=None):
    """Single-flight worker renewal; transient failure preserves the old deadline."""
    from .client import ServerHTTPError
    import urllib.error
    if is_current is not None and not is_current():
        return False
    cached = require_native_session(client, opaque, generation)
    if cached['principal'] != principal:
        raise ServerHTTPError(401, 'The native human identity changed.')
    now = time.monotonic()
    if cached['deadline'] - now > 300 or cached.get('renew_after', 0) > now:
        return False
    if not _exchange_lock.acquire(blocking=False):
        return False
    try:
        with _lock:
            if require_native_session(client, opaque, generation) is not cached:
                raise ServerHTTPError(401, 'The native human session changed.')
            started = time.monotonic()
            if cached['deadline'] - started > 300 or cached.get('renew_after', 0) > started:
                return False
            cached['renew_after'] = started + 60
        try:
            if is_current is not None and not is_current():
                return False
            result = client.refresh_human_session(opaque, generation)
        except ServerHTTPError as error:
            if error.status not in (429, 503):
                raise
            return False
        except (OSError, urllib.error.URLError):
            return False
        renewed = _confirmed(result, cached['provider'])
        if renewed['session'] != opaque or renewed['principal'] != principal:
            raise ServerHTTPError(401, 'The refreshed native human identity changed.')
        require_generation(generation)
        with _lock:
            if is_current is not None and not is_current():
                return False
            if require_native_session(client, opaque, generation) is not cached:
                raise ServerHTTPError(401, 'The native human session changed during renewal.')
            # Base the lease on request start, never inflate it by response latency.
            cached['deadline'] = min(renewed['deadline'], started + 3595)
            cached.pop('renew_after', None)
        return True
    finally:
        _exchange_lock.release()


class BoundResponse:
    """Discard content if account changes while a response is in flight."""
    def __init__(self, response, generation, check_profile):
        self.response, self.generation = response, generation
        self.check_profile = check_profile

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.response.close()

    def read(self, *args):
        require_generation(self.generation)
        self.check_profile()
        value = self.response.read(*args)
        require_generation(self.generation)
        self.check_profile()
        return value

    def __getattr__(self, name):
        return getattr(self.response, name)
