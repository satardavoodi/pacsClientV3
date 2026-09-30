"""Temporary loopback EchoMind candidate probe; no PACS, model or GUI startup."""
import argparse
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--quick', action='store_true')
    args = parser.parse_args()
    from modules.ai_imaging.eagle_eye_remote.server import handler
    from modules.ai_imaging.eagle_eye_remote.echomind.hosting import EchoMind
    from modules.ai_imaging.eagle_eye_remote.client import Client
    from tools.eagle_eye.probe_echomind import run
    config = json.loads(args.server_config.read_text(encoding='utf-8-sig'))
    token = secrets.token_hex(32)
    class NoModels:
        def recent(self, owner):
            return []
    http = ThreadingHTTPServer(('127.0.0.1', 0), handler(NoModels(), {'synthetic': token},
        echomind=EchoMind(config['echomind'], ['synthetic'])))
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        # The token stays in memory; no credential file or environment setting is changed.
        connection = Client.__new__(Client)
        connection.url = f'http://127.0.0.1:{http.server_port}'
        connection.token = token
        import urllib.request
        from modules.ai_imaging.eagle_eye_remote.client import NoRedirect
        connection.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        result = run(connection, quick=args.quick)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
        return 0 if result['passed'] else 1
    finally:
        http.shutdown()
        http.server_close()
        thread.join(3)


if __name__ == '__main__':
    raise SystemExit(main())
