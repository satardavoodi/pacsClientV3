"""Native Secretary admission uses ordinary human authority, never device pairing."""
from http.server import ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from modules.ai_imaging.eagle_eye_remote.server import handler
from modules.ai_imaging.eagle_eye_remote.user_access import UserDenied


def test_native_http_requires_human_grant_and_license_before_submission():
    calls = []
    grant = {'allowed': True, 'licensed': True}
    class Authority:
        store = SimpleNamespace(event=lambda *args: None)
        def verify(self, device, token):
            assert device is None
            if token != 'synthetic-session':
                raise UserDenied(401, 'USER_SESSION_REQUIRED')
            return {'principal': 'synthetic-principal'}
        def require(self, user, feature):
            assert feature == 'secretary'
            if not grant['allowed']:
                raise UserDenied(403, 'USER_PERMISSION_DENIED')
    native = SimpleNamespace(capabilities={'protocol': 1},
        status=lambda owner: {'available': False},
        submit=lambda owner, body, **kw: calls.append((owner, body, kw)) or {'state': 'queued'})
    http = ThreadingHTTPServer(('127.0.0.1', 0), handler(
        SimpleNamespace(), {}, user_authority=Authority(), native_secretary=native,
        license_guard=lambda: grant['licensed']))
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    def request(path, body=None, token='synthetic-session'):
        req = Request(f'http://127.0.0.1:{http.server_port}{path}',
            data=json.dumps(body).encode() if body is not None else None,
            headers={'X-Eagle-User-Session': token})
        try:
            with urlopen(req, timeout=2) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            return error.code, json.load(error)
    try:
        path = '/v1/secretary/remote/operations'
        assert request(path, {}, token='')[0] == 401
        grant['allowed'] = False
        assert request(path, {})[0] == 403
        grant['allowed'] = True
        grant['licensed'] = False
        assert request(path, {})[0] == 403
        assert calls == []
        grant['licensed'] = True
        assert request(path, {})[0] == 202
        assert calls[0][0] == 'synthetic-principal'
        assert request('/v1/secretary/remote/status') == (200, {'available': False})
    finally:
        http.shutdown()
        http.server_close()
        worker.join(3)
