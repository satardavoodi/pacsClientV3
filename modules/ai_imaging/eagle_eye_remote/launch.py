"""Explicit workstation roles and an owned local analysis listener, before Qt."""
import argparse
import atexit
import json
import os
from pathlib import Path
import threading


class HostedService:
    def __init__(self, config):
        from .server import create_server
        self.server, self.jobs = create_server(config)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       name='EagleEyeListener', daemon=True)
        self.closed = False
        self.thread.start()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.server.shutdown()
        self.server.server_close()
        self.jobs.close()
        self.thread.join(timeout=5)


def configure(argv):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--eagle-eye-mode', choices=('standard', 'server'))
    parser.add_argument('--eagle-eye-config', type=Path)
    args, remaining = parser.parse_known_args(argv[1:])
    if not args.eagle_eye_mode:
        if args.eagle_eye_config:
            raise ValueError('Select an Eagle Eye launch mode with the configuration.')
        return None
    if args.eagle_eye_config is None:
        raise ValueError('Supply an Eagle Eye deployment configuration.')
    path = args.eagle_eye_config.resolve()
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    service = None
    if args.eagle_eye_mode == 'server':
        server_config_path = str(path)
        # Desktop-hosted phase 1 uses loopback. Standalone serve supports LAN TLS.
        if not config.get('service_managed', False) and (
                config.get('host', '127.0.0.1') != '127.0.0.1' or config.get('certificate')):
            raise ValueError('Desktop hosting requires loopback; use the standalone TLS service for LAN hosting.')
        clients = config['clients']
        client_id = config.get('local_client')
        if client_id is None and len(clients) == 1:
            client_id = next(iter(clients))
        if client_id not in clients:
            raise ValueError('Select a configured local client identity.')
        if not config.get('service_managed', False):
            service = HostedService(config)
        try:
            port = service.server.server_port if service is not None else int(config.get('port', 8042))
            # The service certificate must include the loopback IP in its SANs.
            scheme = 'https' if config.get('certificate') else 'http'
            bind_host = config.get('host', '127.0.0.1')
            local_host = '127.0.0.1' if bind_host == '0.0.0.0' else bind_host
            if ':' in local_host:
                local_host = f'[{"::1" if local_host == "::" else local_host}]'
            client = {'url': f'{scheme}://{local_host}:{port}',
                      'token_file': str(Path(clients[client_id]).resolve()),
                      'token_env': 'AIPACS_EAGLE_EYE_LOCAL_TOKEN'}
            if config.get('certificate'):
                client['ca_file'] = config.get('ca_file') or config['certificate']
            if config.get('client_ca_file'):
                client.update(config.get('local_client_tls') or {})
            path = Path(config['job_root']).resolve() / 'desktop-client.json'
            temporary = path.with_suffix('.partial')
            temporary.write_text(json.dumps(client, indent=2), encoding='utf-8')
            temporary.replace(path)
            if service is not None:
                atexit.register(service.close)
        except Exception:
            if service is not None:
                service.close()
            raise
    else:
        from .client import Client
        Client(config)  # Validate endpoint and credentials before interactive startup.
    os.environ['AIPACS_EAGLE_EYE_ROLE'] = args.eagle_eye_mode
    if args.eagle_eye_mode == 'server':
        os.environ['AIPACS_EAGLE_EYE_SERVER_CONFIG'] = server_config_path
    else:
        os.environ.pop('AIPACS_EAGLE_EYE_SERVER_CONFIG', None)
    os.environ['AIPACS_EAGLE_EYE_CLIENT_CONFIG'] = str(path)
    os.environ.pop('AIPACS_EAGLE_EYE_WORKER', None)
    argv[:] = [argv[0], *remaining]
    return service
