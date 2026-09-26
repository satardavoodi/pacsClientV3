"""Prepare private loopback deployment files; do not launch or restart the UI."""
import json
from pathlib import Path
import secrets
import sys

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))


def prepare(directory, database, source_root):
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    token = directory / 'local.token'
    if not token.exists():
        with token.open('x', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(48))
    server = {'host': '127.0.0.1', 'port': 8042,
              'job_root': str(directory / 'jobs'),
              'clients': {'local-workstation': str(token)},
              'pacs': {'type': 'workstation-cache', 'database': str(Path(database).resolve()),
                       'allowed_roots': [str(Path(source_root).resolve())]}}
    client = {'url': 'http://127.0.0.1:8042', 'token_file': str(token),
              'token_env': 'AIPACS_EAGLE_EYE_LOCAL_TOKEN'}
    for name, value in (('server.json', server), ('client.json', client)):
        path = directory / name
        if not path.exists():
            with path.open('x', encoding='utf-8') as stream:
                json.dump(value, stream, indent=2)
    return directory


if __name__ == '__main__':
    from PacsClient.utils.data_paths import DATABASE_FILE, DICOM_IMAGES_DIR
    prepare(REPO / 'generated-files/eagle-eye/deployment', DATABASE_FILE, DICOM_IMAGES_DIR)
    print('Local Eagle Eye deployment prepared. Existing configuration was preserved.')
