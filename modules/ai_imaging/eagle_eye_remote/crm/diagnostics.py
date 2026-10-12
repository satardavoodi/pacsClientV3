"""Isolated bounded CRM connection checks; never exports credentials or records."""
import json
import os
from pathlib import Path
import subprocess
import sys
MONGO_URI = 'mongodb://127.0.0.1:27017/'

def configure_local_mongo():
    os.environ['RECEPTION_MONGO_URI'] = MONGO_URI
    os.environ['RECEPTION_MONGO_ENABLED'] = '1'

def folder_status(path):
    try:
        root = Path(path)
        if not root.is_dir():
            return 'MISSING_FOLDER'
        with os.scandir(root) as entries:
            next(entries, None)
        return 'OK'
    except PermissionError:
        return 'ACCESS_DENIED'
    except OSError:
        return 'FOLDER_UNAVAILABLE'

def api_result(status, body):
    if status in (400, 401, 403):
        return 'AUTH_REJECTED'
    return 'OK' if status == 200 and isinstance(body, dict) and isinstance(body.get('token'), str) and body['token'] else 'API_INVALID_RESPONSE'

def check(directory):
    vendor = Path(__file__).parent / 'vendor'
    sys.path.insert(0, str(vendor))
    os.environ['RECEPTION_CRM_CONFIG_DIR'] = str(directory)
    from reception_crm.server.config import load_server_config
    settings = load_server_config(Path(directory) / 'server.json')
    configure_local_mongo()
    import requests
    api = 'AUTH_NOT_CONFIGURED'
    if settings.reception.configured:
        try:
            with requests.Session() as session:
                session.trust_env = False
                with session.post(f'http://{settings.host}:{settings.reception.port}/api/auth/login', json={'username': settings.reception.username, 'password': settings.reception.password}, timeout=(2, 3), allow_redirects=False, stream=True) as response:
                    raw = bytearray()
                    for chunk in response.iter_content(1024):
                        raw.extend(chunk)
                        if len(raw) > 65536:
                            raise ValueError()
                    body = json.loads(raw)
                    api = api_result(response.status_code, body)
        except requests.RequestException:
            api = 'API_UNREACHABLE'
        except (ValueError, TypeError):
            api = 'API_INVALID_RESPONSE'
    mongo = 'MONGO_UNAVAILABLE'
    try:
        from pymongo import MongoClient
        with MongoClient(MONGO_URI, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000, socketTimeoutMS=2000, maxPoolSize=1) as client:
            client.admin.command('ping')
        mongo = 'OK'
    except Exception:
        pass
    roots = [('data_root', settings.data_root)] + [(f'reception_folder_{i + 1}', p) for i, p in enumerate(settings.reception.file_roots[:16])]
    return {'diagnostic': True, 'api': {'status': api, 'port': settings.reception.port}, 'mongo': {'status': mongo, 'host': '127.0.0.1', 'port': 27017}, 'folders': [{'name': name, 'path': str(path)[:1024], 'status': folder_status(path)} for name, path in roots]}

def run(directory):
    try:
        from aipacs_runtime import is_frozen
        command = [sys.executable, '--eagle-eye-crm-worker', 'stdin'] if is_frozen() else [sys.executable, '-m', 'modules.ai_imaging.eagle_eye_remote.crm.worker']
        payload = json.dumps({'operation': 'connection_diagnostic', 'config_dir': str(directory)}) + '\n'
        env = {key: value for key, value in os.environ.items() if not key.startswith(('PYTHON', 'QT_', 'INO_', 'RECEPTION_'))}
        env['PYTHONNOUSERSITE'] = '1'
        result = subprocess.run(command, input=payload, capture_output=True, text=True, timeout=18, env=env, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or len(result.stdout) > 16384:
            raise ValueError()
        value = json.loads(result.stdout)
        if value.get('diagnostic') is not True:
            raise ValueError()
        return value
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {'diagnostic': True, 'api': {'status': 'CHECK_UNAVAILABLE'}, 'mongo': {'status': 'CHECK_UNAVAILABLE'}, 'folders': []}
if __name__ == '__main__':
    try:
        print(json.dumps(check(Path(sys.argv[1]))))
    except Exception:
        raise SystemExit(1)
