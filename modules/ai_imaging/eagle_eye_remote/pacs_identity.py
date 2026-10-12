"""PACS upstream authentication using loopback socket Login and verified HTTP identity."""
import json
import socket
import struct
import time
import urllib.parse
import uuid
import requests

from .user_access import UserDenied, stable_identity


class PacsIdentity:
    def __init__(self, config):
        url = config.get('url')
        if not isinstance(url, str) or any(ord(c) < 33 for c in url):
            raise ValueError('Configure a valid PACS identity origin.')
        self.url = url.rstrip('/')
        origin = urllib.parse.urlsplit(self.url)
        if (origin.scheme not in ('http', 'https') or origin.hostname not in ('127.0.0.1','localhost','::1')
                or origin.username or origin.password or origin.path or origin.query or origin.fragment
                or origin.port == 0):
            raise ValueError('PACS user authentication requires a configured same-host origin.')
        self.host = origin.hostname
        self.port = int(config.get('socket_port', 50052))
        if not 1 <= self.port <= 65535:
            raise ValueError('Invalid PACS socket port.')
        self.ca = config.get('ca_file') or True

    def _verified_user(self, token):
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(self.url + '/api/auth/verify',
                headers={'Authorization': 'Bearer ' + token}, timeout=(3,5),
                allow_redirects=False, stream=True, verify=self.ca)
            try:
                raw = response.raw.read(65537, decode_content=True)
                if response.status_code != 200 or len(raw) > 65536:
                    raise UserDenied(401, 'PACS_IDENTITY_REJECTED')
                value = json.loads(raw)
                if value.get('success') is not True:
                    raise UserDenied(401, 'PACS_IDENTITY_REJECTED')
                stable_identity('pacs', value.get('user'))
                return value['user']
            finally:
                response.close()

    def verify(self, token):
        return stable_identity('pacs', self._verified_user(token))

    def login_console(self, username, password):
        token, identity = self.login(username, password)
        user = self._verified_user(token)
        if (stable_identity('pacs', user) != identity
                or user.get('role') not in ('admin', 'system_admin')):
            raise UserDenied(403, 'CONSOLE_ADMIN_REQUIRED')
        return identity

    def login(self, username, password):
        payload = json.dumps({'endpoint':'Login', 'request_id':uuid.uuid4().hex,
                              'params':{'username':username, 'password':password}}).encode()
        deadline = time.monotonic() + 8
        with socket.create_connection((self.host, self.port), timeout=3) as connection:
            connection.sendall(struct.pack('!I', len(payload)) + payload)
            def read_exact(count):
                data = bytearray()
                while len(data) < count:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise UserDenied(503, 'PACS_IDENTITY_TIMEOUT')
                    connection.settimeout(remaining)
                    part = connection.recv(count-len(data))
                    if not part:
                        raise UserDenied(401, 'PACS_IDENTITY_REJECTED')
                    data.extend(part)
                return bytes(data)
            for _ in range(12):
                length = struct.unpack('!I', read_exact(4))[0]
                if not 0 < length <= 65536:
                    raise UserDenied(401, 'PACS_IDENTITY_REJECTED')
                reply = json.loads(read_exact(length))
                if reply.get('type') == 'broadcast':
                    continue
                if reply.get('status') != 'success' and reply.get('success') is not True:
                    raise UserDenied(401, 'PACS_IDENTITY_REJECTED')
                data = reply.get('data') or {}
                token = reply.get('token') or data.get('token')
                if not isinstance(token, str) or not 1 <= len(token) <= 8192:
                    raise UserDenied(401, 'PACS_IDENTITY_REJECTED')
                # HTTP verification, not reply username or unverified JWT decoding,
                # is authoritative even when socket Login delegates to RIS.
                return token, self.verify(token)
        raise UserDenied(401, 'PACS_IDENTITY_REJECTED')

    def roster(self, token):
        with requests.Session() as session:
            session.trust_env = False
            response = session.get(self.url + '/api/users', headers={'Authorization':'Bearer '+token},
                                   timeout=(3,5), allow_redirects=False, stream=True, verify=self.ca)
            try:
                raw = response.raw.read(2 * 1024 * 1024 + 1, decode_content=True)
                if response.status_code != 200 or len(raw) > 2 * 1024 * 1024:
                    raise UserDenied(403,'PACS_ROSTER_DENIED')
                result = json.loads(raw)
                if result.get('success') is not True or not isinstance(result.get('users'),list) or len(result['users']) > 5000:
                    raise UserDenied(403,'PACS_ROSTER_DENIED')
                return [stable_identity('pacs', user) for user in result['users'] if user.get('is_active') is not False]
            finally:
                response.close()
