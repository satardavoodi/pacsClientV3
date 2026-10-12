"""Deployment settings shared by the workstation and its owned Slicer viewer."""
import json
import os
from pathlib import Path
import sys


def config_path():
    if os.environ.get('AIPACS_EAGLE_EYE_CLIENT_CONFIG'):
        return Path(os.environ['AIPACS_EAGLE_EYE_CLIENT_CONFIG'])
    if getattr(sys, 'frozen', False):
        from aipacs_runtime import roaming_config_root
        return roaming_config_root() / 'eagle_eye_client.json'
    return Path(__file__).resolve().parents[3] / 'config/eagle_eye_client.json'


def ordinary_connection(value):
    """Normalize only ordinary Eagle profiles; remote Agent pairing is separate."""
    from urllib.parse import urlsplit, urlunsplit
    result = dict(value)
    url = result.get('url', '').strip().rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme == 'https':
        url = urlunsplit(('http', parsed.netloc, parsed.path, parsed.query, parsed.fragment))
    if url:
        result['url'] = url
    for key in ('token_file', 'ca_file', 'client_certificate', 'client_private_key'):
        result.pop(key, None)
    return result


def client_settings():
    # A deployment setting, not a test flag. No hardcoded credential or endpoint.
    source = config_path()
    if not source.is_file():
        return {}
    value = json.loads(source.read_text(encoding='utf-8-sig'))
    return ordinary_connection(value)


def remote_required():
    if os.environ.get('AIPACS_EAGLE_EYE_WORKER') == '1':
        return False
    if os.environ.get('AIPACS_EAGLE_EYE_ROLE') in ('standard', 'server'):
        return True
    if client_settings().get('url'):
        return True
    if os.environ.get('AIPACS_EAGLE_EYE_CLIENT_ONLY') == '1':
        return True
    if getattr(sys, 'frozen', False):
        from aipacs_runtime import load_installation_profile
        return load_installation_profile().get('distribution_edition') != 'eagle-eye'
    return False


def slicer_environment():
    """Pass only the configuration location and lightweight source root to Slicer."""
    value = str(config_path())
    return {'AIPACS_EAGLE_EYE_CLIENT_CONFIG': value,
            'AIPACS_EAGLE_EYE_ROLE': os.environ.get('AIPACS_EAGLE_EYE_ROLE', ''),
            'AIPACS_EAGLE_EYE_PACKAGE_ROOT': str(Path(__file__).resolve().parents[3]),
            'AIPACS_EAGLE_EYE_CLIENT_ONLY': '1' if remote_required() else '0'}
