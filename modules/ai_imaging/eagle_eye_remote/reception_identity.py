"""Reception identity via its source-verified AdminUser token authority."""
from collections.abc import Mapping
import json
import re
import time
from urllib.parse import urlsplit
import requests


class ReceptionIdentityUnavailable(RuntimeError):
    """Sanitized failure without upstream bodies, tokens or credentials."""
    code = 'RECEPTION_IDENTITY_UNAVAILABLE'
    status = 503

    def __init__(self, *, unauthorized=False):
        self.status = 401 if unauthorized else 503
        self.code = 'RECEPTION_AUTH_REJECTED' if unauthorized else 'RECEPTION_IDENTITY_UNAVAILABLE'
        super().__init__('Reception authentication was rejected.' if unauthorized
                         else 'Reception identity verification is unavailable.')


class ReceptionIdentity:
    """One configured origin, fixed source-backed routes, no authority fallback."""

    provider = 'reception'
    available = False
    max_response_bytes = 65536

    def __init__(self, config):
        if not isinstance(config, Mapping):
            raise ValueError('Reception identity configuration must be a mapping.')
        self.available = False
        if config.get('protocol') != 'ino-admin-user-v1':
            return
        origin = config.get('base_url', '')
        if not isinstance(origin, str):
            raise ValueError('Configure a Reception origin.')
        try:
            parsed = urlsplit(origin)
            port = parsed.port
        except ValueError:
            raise ValueError('Configure a valid Reception origin.') from None
        if (parsed.scheme not in ('http', 'https')
                or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')
                or any(ord(c) < 33 for c in origin) or port == 0):
            raise ValueError('Configure a Reception origin without credentials or paths.')
        timeout = config.get('timeout', 8)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 1 <= timeout <= 15:
            raise ValueError('Reception identity timeout must be between 1 and 15 seconds.')
        if any(k in config for k in ('verify_path', 'login_path', 'fallback')):
            raise ValueError('Reception identity routes and authority are fixed.')
        self.origin = origin.rstrip('/')
        self.timeout = timeout
        self.available = True

    def _request(self, method, path, *, body=None, token=None, roster=False):
        if not self.available:
            raise ReceptionIdentityUnavailable()
        headers = {'Accept': 'application/json'}
        if token is not None:
            headers['Authorization'] = 'Bearer ' + token
        try:
            with requests.Session() as session:
                session.trust_env = False
                deadline = time.monotonic() + self.timeout
                with session.request(method, self.origin + path, json=body, headers=headers,
                                     allow_redirects=False, timeout=(min(3, self.timeout), self.timeout),
                                     stream=True, verify=True) as response:
                    if response.status_code in (400, 401, 403, 404):
                        raise ReceptionIdentityUnavailable(unauthorized=True)
                    if response.status_code != 200:
                        raise ReceptionIdentityUnavailable()
                    raw = bytearray()
                    for chunk in response.iter_content(chunk_size=1024):
                        raw.extend(chunk)
                        if len(raw) > (2 * 1024 * 1024 if roster else self.max_response_bytes) or time.monotonic() > deadline:
                            raise ReceptionIdentityUnavailable()
                    data = json.loads(raw)
                    if roster:
                        if not isinstance(data, list) or len(data) > 5000:
                            raise ReceptionIdentityUnavailable()
                        return data
                    if not isinstance(data, dict) or data.get('success') is not True:
                        raise ReceptionIdentityUnavailable(unauthorized=True)
                    return data
        except (requests.RequestException, ValueError, UnicodeError):
            raise ReceptionIdentityUnavailable() from None

    @staticmethod
    def _identity(data):
        user = data.get('user')
        if not isinstance(user, dict):
            raise ReceptionIdentityUnavailable()
        subject, username = user.get('id'), user.get('username')
        if (not isinstance(subject, str) or not re.fullmatch(r'[0-9a-fA-F]{24}', subject)
                or subject == '0' * 24 or not isinstance(username, str)
                or not username.strip() or len(username) > 256
                or any(ord(c) < 32 for c in username)):
            raise ReceptionIdentityUnavailable()
        return {'subject': subject.lower(), 'username': username, 'provider': 'reception'}

    @staticmethod
    def _token(token):
        if (not isinstance(token, str) or not token or len(token) > 16384
                or any(ord(c) < 33 or ord(c) > 126 for c in token)):
            raise ReceptionIdentityUnavailable(unauthorized=True)
        return token

    def login(self, username, password):
        return self._login(username, password)

    def login_console(self, username, password):
        _, identity = self._login(username, password, console=True)
        return identity

    def _login(self, username, password, *, console=False):
        """Authenticate once, then resolve identity through the token verifier."""
        if not self.available:
            raise ReceptionIdentityUnavailable()
        if (not isinstance(username, str) or not username.strip() or len(username) > 256
                or any(ord(c) < 32 for c in username) or not isinstance(password, str)
                or not password or len(password) > 4096):
            raise ReceptionIdentityUnavailable(unauthorized=True)
        data = self._request('POST', '/api/AdminUser/getToken',
                             body={'username': username, 'password': password})
        token = self._token(data.get('token'))
        identity = self.verify(token)
        if self._identity(data) != identity:
            raise ReceptionIdentityUnavailable()
        # The fresh password-validated login projects the authoritative Admin
        # flag; verify-token independently confirms the same stable identity.
        if console and data.get('user', {}).get('admin') is not True:
            raise ReceptionIdentityUnavailable(unauthorized=True)
        return token, identity

    def verify(self, upstream_token):
        """Upstream verifies the signature and resolves the actual database user."""
        if not self.available:
            raise ReceptionIdentityUnavailable()
        return self._identity(self._request('GET', '/api/AdminUser/verify-token',
                                            token=self._token(upstream_token)))

    def roster(self, token):
        """Project stable identities only; never persist upstream private fields."""
        rows = self._request('GET', '/api/AdminUser/getCenterUsers',
                             token=self._token(token), roster=True)
        result = []
        for row in rows:
            if not isinstance(row, dict):
                raise ReceptionIdentityUnavailable()
            if row.get('Deactive') is True:
                continue
            result.append(self._identity({'user': {
                'id': row.get('_id'), 'username': row.get('User')}}))
        return result
