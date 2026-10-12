"""Local Server-role administration for the shared private Brain configuration."""
import os
from pathlib import Path
from .administration import settings_role, read_connection, _save
from .echomind import runtime
from .brain_connection import summary
from .brain_profiles import CUSTOM_FIELDS

def directory():
    if settings_role() != 'server':
        raise ValueError('Eagle AI Brain administration requires the local Server role.')
    config = read_connection(os.environ['AIPACS_EAGLE_EYE_SERVER_CONFIG'])['value']
    root = Path(config.get('echomind', {}).get('config_dir', ''))
    if not root.is_absolute() or not (root / 'settings.json').is_file():
        raise ValueError('Configure the private server EchoMind directory first.')
    return root

def snapshot():
    root = directory()
    current = read_connection(root / 'settings.json')
    return {'revision': current['revision'], 'authenticated': bool(current['value'].get('openai_api_key') if current['value'].get('brain_server')=='custom' else current['value'].get('api_key')),
            'usage': summary(Path(current['value'].get('brain_usage_dir') or root), current['value'].get('brain_server','server_1')),
            'selected':current['value'].get('brain_server','server_1'),
            'profiles': {'server_1':{'label':'LLM G','ready':True}, 'server_2':{'label':'LLM A','ready':False}, 'server_3':{'label':'LLM V','ready':False}, 'custom':{'label':'Custom API','ready':bool(current['value'].get('openai_api_key'))}},
            'custom': {key:current['value'].get(key,'') for key in CUSTOM_FIELDS},
            'custom_key_saved':bool(current['value'].get('openai_api_key')),
            'proxy': proxy_settings(current['value'])}

def authenticate(revision, code):
    root = directory()
    if not isinstance(code, str) or not code.strip() or len(code) > 512:
        raise ValueError('Enter a valid Eagle AI Brain center access code.')
    code = code.strip()
    with runtime.configuration(root), runtime.request_context({'api_key': code, 'llm_backend': 'company'}):
        try:
            runtime.company_identity()
        except Exception:
            raise ValueError('Eagle AI Brain center access code could not be verified.') from None
    _save(root / 'settings.json', revision, lambda old: {**old, 'api_key': code, 'llm_backend': 'company'})
    return snapshot()


def test_connection():
    """Explicit operator probe; use the same authority, identity and usage ledger."""
    selected=snapshot().get('selected','server_1')
    if selected in ('server_2','server_3'):
        import socket
        settings=read_connection(directory()/'settings.json')['value']
        endpoint=settings.get('brain_routes',{}).get(selected,{})
        value=snapshot()
        value.update(connection_ok=False,transport_only=True,endpoint_configured=False)
        host,port=endpoint.get('host'),endpoint.get('port')
        if proxy_settings(settings)['connection_type'] == 'socks5':
            value['proxy_probe_unavailable'] = True
            return value
        if isinstance(host,str) and type(port) is int and 1<=port<=65535:
            value['endpoint_configured']=True
            try:
                with socket.create_connection((host,port),timeout=3):value['connection_ok']=True
            except OSError:pass
        return value
    from .echomind.core.llm_client import test_active_backend_connection
    from .brain_connection import source
    with source('other'), runtime.configuration(directory()), runtime.request_context({'llm_backend': 'company'}):
        result = test_active_backend_connection(timeout=15)
    value = snapshot()
    value['connection_ok'] = bool(result.get('ok'))
    return value


def save_profile(revision, selected, custom):
    from .brain_profiles import PROFILES, CUSTOM_FIELDS
    if selected not in PROFILES or set(custom)-set(CUSTOM_FIELDS)-{'openai_api_key'}:
        raise ValueError('Invalid Brain profile settings.')
    if any(not isinstance(value,str) or len(value)>32000 for value in custom.values()):
        raise ValueError('Invalid Custom API field.')
    changes={key:value.strip() for key,value in custom.items() if key!='openai_api_key' or value.strip()}
    if any(('\n' in value or '\r' in value) for key,value in changes.items() if not key.startswith('prompt_')):
        raise ValueError('Connection fields must be single-line values.')
    if selected=='custom':
        from urllib.parse import urlsplit
        address=urlsplit(changes.get('openai_base_url',''))
        if address.scheme!='https' or not address.hostname or address.username or address.password or address.query or address.fragment:
            raise ValueError('Custom API requires an HTTPS base URL.')
    _save(directory()/'settings.json',revision,lambda old:{**old,**changes,'brain_server':selected})
    return snapshot()


def proxy_settings(settings):
    selected = settings.get('connection_type', 'direct')
    port = settings.get('proxy_port', 2080)
    if selected not in ('direct', 'socks5') or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid shared Brain proxy settings.')
    return {'connection_type': selected, 'proxy_port': port}


def save_proxy(revision, options):
    if not isinstance(options, dict) or set(options) != {'connection_type', 'proxy_port'}:
        raise ValueError('Invalid shared Brain proxy fields.')
    changes = proxy_settings(options)
    _save(directory() / 'settings.json', revision, lambda old: {**old, **changes})
    return snapshot()
