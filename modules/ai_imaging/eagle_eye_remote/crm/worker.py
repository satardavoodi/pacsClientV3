"""Private CRM process. No public listener, independent service or provider route."""
import hmac
from http import HTTPStatus
import json
import os
from pathlib import Path
import sys


def main():
    config = json.loads(sys.stdin.readline())
    if config.get('operation') == 'connection_diagnostic':
        if set(config) != {'operation', 'config_dir'} or not Path(config['config_dir']).is_absolute():
            raise ValueError('Invalid CRM diagnostic request.')
        from .diagnostics import check
        print(json.dumps(check(Path(config['config_dir']))))
        return
    directory = Path(config['config_dir'])
    sys.path.insert(0, str(Path(__file__).parent / 'vendor'))
    os.environ['RECEPTION_CRM_CONFIG_DIR'] = str(directory)
    os.environ['CRM_EAGLE_CONFIG'] = config['ai_config_dir']
    os.environ['APPDATA'] = str(directory / 'profile')
    os.environ['RECEPTION_ENABLE_WRITES'] = '0'
    from reception_crm import permissions
    roles_path = directory / 'roles.json'
    roles = json.loads(roles_path.read_text(encoding='utf-8-sig'))
    if not isinstance(roles, dict) or not isinstance(roles.get('users'), dict) or not isinstance(roles.get('roles'), dict):
        raise ValueError('CRM requires an explicit valid roles policy.')
    # Hosted authority must never fall back to an unrelated standalone installation.
    permissions._candidate_roles_paths = lambda: (roles_path,)
    from reception_crm import operations, runtime
    vendor = Path(__file__).parent / 'vendor'
    runtime.bundle_dir = lambda: vendor
    operations._candidate_operations_paths = lambda: (
        directory / 'operations.json', vendor / 'config' / 'operations.json')
    from reception_crm.server.config import load_server_config, apply_to_environment
    settings = load_server_config(directory / 'server.json')
    raw_settings = json.loads((directory / 'server.json').read_text(encoding='utf-8-sig'))
    if (not isinstance(raw_settings, dict) or not raw_settings.get('center')
            or not Path(raw_settings.get('data_root', '')).is_absolute()
            or not raw_settings.get('session_secret') or settings.validate()):
        raise ValueError('CRM requires validated explicit private configuration.')
    apply_to_environment(settings)
    from .diagnostics import configure_local_mongo
    configure_local_mongo()
    os.environ.pop('RECEPTION_HTTP_API_TOKEN', None)
    os.environ['RECEPTION_ENABLE_WRITES'] = '0'
    from reception_crm.server.runner import configure_logging
    configure_logging(settings)
    from reception_crm import politeness
    politeness.apply()
    from reception_crm.adapters.http_api import HttpApiHandler
    from http.server import ThreadingHTTPServer

    from .delegation import CURRENT, HEADER, decode_subject, principal_for, install_policy
    from reception_crm.settings import resolve_center
    from reception_crm.core import identity
    from reception_crm.adapters.http_api import principal_dict
    install_policy()

    class Handler(HttpApiHandler):
        def authenticate(self):
            principal = CURRENT.get()
            if principal is None:
                self.unauthorized('An authenticated Eagle identity is required.')
            return principal

        def handle_session(self):
            principal = self.authenticate()
            if principal is None:
                return
            # A compatibility token is scoped by the outer host to device+subject.
            session = identity.issue(principal)
            self.respond_json({'ok': True, 'accessToken': session.token,
                'expiresAt': session.expires_at, 'sessionId': session.session_id,
                'principal': principal_dict(principal)})

        def _dispatch(self, method):
            if not self._allowed():
                return
            try:
                principal = principal_for(decode_subject(self.headers.get(HEADER, '')), resolve_center())
            except ValueError:
                # Health and mode catalog contain no patient data or tool execution.
                if self.path not in ('/api/health', '/api/modes'):
                    self.unauthorized('An authenticated Eagle identity is required.')
                    return
                principal = None
            marker = CURRENT.set(principal)
            try:
                method()
            finally:
                CURRENT.reset(marker)

        def _allowed(self):
            if not hmac.compare_digest(self.headers.get('X-Eagle-Internal', ''), config['token']):
                self.respond_json({'error': 'Internal worker authorization required'}, HTTPStatus.UNAUTHORIZED)
                return False
            return True

        def do_GET(self):
            self._dispatch(super().do_GET)

        def do_POST(self):
            self._dispatch(super().do_POST)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    ready = directory / 'worker-ready.json'
    temporary = ready.with_suffix('.partial')
    temporary.write_text(json.dumps({'pid': os.getpid(), 'port': server.server_port}))
    temporary.replace(ready)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        ready.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
