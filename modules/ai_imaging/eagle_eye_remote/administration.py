"""Worker-only deployment administration; no model imports or listener creation."""
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit

from .settings import config_path

_WRITE_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _installed_settings_role():
    from aipacs_runtime import is_frozen, load_installation_profile
    return ('server' if load_installation_profile().get('distribution_edition') == 'eagle-eye'
            else 'standard') if is_frozen() else 'standard'


def settings_role():
    """UI role only; warm the installed fallback before QApplication startup."""
    return os.environ.get('AIPACS_EAGLE_EYE_ROLE') or _installed_settings_role()


def read_connection(path):
    path = Path(path)
    raw = path.read_bytes() if path.is_file() else None
    value = json.loads(raw.decode('utf-8-sig')) if raw is not None else {}
    if not isinstance(value, dict) or value.get('schema_version', 1) != 1:
        raise ValueError('Unsupported Eagle Eye configuration version.')
    return {'path': str(path), 'value': value,
            'revision': hashlib.sha256(raw).hexdigest() if raw is not None else None}


def validate_connection(value):
    url = value.get('url', '').strip().rstrip('/')
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('Use an HTTPS Eagle Eye address; HTTP is allowed only for loopback.')
    try:
        parsed.port
    except ValueError:
        raise ValueError('The server port is invalid.') from None
    for key in ('token_file', 'ca_file', 'client_certificate', 'client_private_key'):
        if value.get(key) and not Path(value[key]).is_absolute():
            raise ValueError('Credential and certificate files require absolute paths.')
    if bool(value.get('client_certificate')) != bool(value.get('client_private_key')):
        raise ValueError('Paired client certificate and private key must be configured together.')
    if value.get('client_certificate') and parsed.scheme != 'https':
        raise ValueError('Paired clients require HTTPS.')
    return {**value, 'url': url, 'schema_version': 1}


def save_connection(path, revision, changes):
    if set(changes) - {'url', 'token_file', 'ca_file', 'client_certificate', 'client_private_key'}:
        raise ValueError('Unsupported connection fields.')
    return _save(path, revision, lambda previous: validate_connection({**previous, **changes}))


def _save(path, revision, transform):
    path = Path(path)
    with _WRITE_LOCK:
        previous = read_connection(path)
        if previous['revision'] != revision:
            raise ValueError('Settings changed elsewhere. Reload before saving.')
        value = transform(previous['value'])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                             prefix=path.name + '.', suffix='.partial', delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(value, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return read_connection(path)


def save_resources(path, revision, resources, quota):
    from .scheduling import Resources
    Resources(resources)
    if type(quota) is not int or not 1 <= quota <= 16:
        raise ValueError('The per-client limit must be between 1 and 16.')
    saved = _save(path, revision, lambda previous: {**previous, 'resources': resources,
                                                   'max_jobs_per_client': quota})
    return {'revision': saved['revision']}


def save_source_options(path, revision, options):
    required = {'type', 'url', 'database', 'allowed_roots', 'job_root'}
    if not required <= set(options) or set(options) - required - {'dicom_port', 'socket_port'}:
        raise ValueError('Unsupported server source settings.')
    for key in ('dicom_port', 'socket_port'):
        if key in options and (type(options[key]) is not int or not 1 <= options[key] <= 65535):
            raise ValueError('PACS ports must be between 1 and 65535.')
    if options['type'] not in ('workstation-cache', 'pacs-storage'):
        raise ValueError('Unsupported PACS source mode.')
    roots = options['allowed_roots']
    if (not isinstance(roots, list) or not roots or len(roots) > 32
            or any(not Path(root).is_absolute() or not Path(root).is_dir() for root in roots)):
        raise ValueError('Select accessible absolute PACS storage roots.')
    if not Path(options['job_root']).is_absolute():
        raise ValueError('Job storage requires an absolute path.')
    if options['type'] == 'workstation-cache':
        database = Path(options['database'])
        if not database.is_absolute() or not database.is_file():
            raise ValueError('Select the existing server workstation database.')
    else:
        parsed = urlsplit(options['url'])
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError('Select the PACS metadata service address.')
        parsed.port
    def transform(previous):
        source = {**previous.get('pacs', {}), **{key: value for key, value in options.items() if key != 'job_root'}}
        return {**previous, 'pacs': source, 'job_root': options['job_root']}
    saved = _save(path, revision, transform)
    return {'revision': saved['revision']}


def save_listener_options(path, revision, options):
    """Validate off the GUI thread; save for an explicit service restart only."""
    import ipaddress
    import ssl
    if set(options) != {'host', 'port', 'certificate', 'private_key'}:
        raise ValueError('Unsupported listener settings.')
    try:
        address = ipaddress.ip_address(options['host'])
    except ValueError:
        raise ValueError('Use a local bind IP address, such as 127.0.0.1 or 0.0.0.0.') from None
    if address.version != 4:
        raise ValueError('The current service listener requires an IPv4 bind address.')
    if type(options['port']) is not int or not 1 <= options['port'] <= 65535:
        raise ValueError('The listening port must be between 1 and 65535.')
    certificate, key = options['certificate'], options['private_key']
    if bool(certificate) != bool(key) or (not address.is_loopback and not certificate):
        raise ValueError('Network listeners require a TLS certificate and private key.')
    if certificate:
        if any(not Path(p).is_absolute() or not Path(p).is_file() for p in (certificate, key)):
            raise ValueError('Select existing absolute certificate and private-key paths.')
        try:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certificate, key)
        except (OSError, ssl.SSLError):
            raise ValueError('The certificate and private key could not be loaded together.') from None
    def transform(previous):
        if not previous.get('service_managed') and (certificate or options['host'] != '127.0.0.1'):
            raise ValueError('Network hosting requires the independent Windows service.')
        if previous.get('client_ca_file') and not certificate:
            raise ValueError('TLS cannot be removed from a paired server.')
        return {**previous, **options}
    saved = _save(path, revision, transform)
    return {'revision': saved['revision']}


def load_settings():
    snapshot = read_connection(config_path())
    role = settings_role()
    snapshot['role'] = role
    server_path = os.environ.get('AIPACS_EAGLE_EYE_SERVER_CONFIG')
    if role == 'server' and server_path:
        server_snapshot = read_connection(server_path)
        server = server_snapshot['value']
        pacs = server.get('pacs', {})
        snapshot['server'] = {'host': server.get('host', '127.0.0.1'),
                              'port': server.get('port', 8042), 'job_root': server.get('job_root', ''),
                              'certificate': server.get('certificate', ''),
                              'private_key': server.get('private_key', ''),
                              'source_type': pacs.get('type', 'pacs-storage'),
                              'client_count': len(server.get('clients', {})),
                              'configuration_path': server_path, 'revision': server_snapshot['revision'],
                              'resources': server.get('resources', {}),
                              'source': {key: pacs.get(key, [] if key == 'allowed_roots' else '')
                                         for key in ('url', 'database', 'allowed_roots', 'dicom_port', 'socket_port')},
                              'pacs_account_saved': bool(pacs.get('credential_file')),
                              'max_jobs_per_client': server.get('max_jobs_per_client', 4)}
    return snapshot


def save_pacs_account(path, revision, url, username, password):
    """The secret never enters the JSON settings or a returned UI snapshot."""
    from .pacs_credentials import write_pacs_credentials, pacs_address
    url = pacs_address(url)
    def transform(previous):
        import uuid
        # A fresh file makes failure/stale-edit rollback leave the old account usable.
        credential = Path(path).resolve().parent / ('pacs-account-' + uuid.uuid4().hex + '.bin')
        write_pacs_credentials(credential, url, username, password)
        return {**previous, 'pacs': {**previous.get('pacs', {}), 'url': url,
                                    'credential_file': str(credential)}}
    saved = _save(path, revision, transform)
    return {'revision': saved['revision']}


def probe_pacs(path):
    """Read-only, patient-free PACS probe, executed by the settings worker."""
    from .source import PacsSource
    config = read_connection(path)['value']['pacs']
    source = PacsSource(config)
    endpoint = '/api/auth/verify' if config.get('credential_file') else '/api/health'
    response = None
    try:
        response = source.get(config['url'].rstrip('/') + endpoint)
        return {'authenticated': bool(config.get('credential_file'))}
    finally:
        if response is not None:
            response.close()
        source.session.close()


def probe_connection(value):
    from .client import Client
    response = Client(validate_connection(value)).json('/v1/capabilities')
    if (response.get('protocol') != 1 or response.get('input_mode') != 'pacs_references'
            or not isinstance(response.get('modules'), list)
            or any(not isinstance(item, str) for item in response['modules'])):
        raise ValueError('The endpoint is not a compatible Eagle Eye server.')
    return response


def recent_jobs(value):
    from .client import Client
    result = Client(validate_connection(value)).json('/v1/jobs')
    if not isinstance(result.get('jobs'), list) or len(result['jobs']) > 50:
        raise ValueError('Invalid job inventory.')
    return result['jobs']
