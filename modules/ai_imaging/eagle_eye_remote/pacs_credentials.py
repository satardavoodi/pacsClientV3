"""Machine-bound PACS credentials, with an explicit service-readable Windows ACL."""
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


def pacs_address(value):
    value = value.strip().rstrip('/')
    parsed = urlsplit(value)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.path
            or (parsed.scheme == 'http' and parsed.hostname not in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('Use an HTTPS PACS origin, or HTTP on loopback only.')
    parsed.port
    return value


def write_pacs_credentials(path, url, username, password):
    import win32crypt
    import win32security
    path = Path(path)
    if not path.is_absolute() or not username.strip() or not password:
        raise ValueError('An absolute credential file and PACS account are required.')
    value = {'url': pacs_address(url), 'username': username.strip(), 'password': password}
    # LOCAL_MACHINE permits the independent service account to decrypt after reboot.
    # The file ACL is therefore essential: Administrators/SYSTEM full, LocalService read.
    encrypted = win32crypt.CryptProtectData(json.dumps(value).encode('utf-8'),
                                            'AI-PACS PACS service account', None, None, None, 4)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;FR;;;LS)', 1)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            win32security.SetFileSecurity(str(temporary),
                win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
                descriptor)
            stream.write(encrypted)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def read_pacs_credentials(path, url):
    import win32crypt
    try:
        encrypted = Path(path).read_bytes()
        value = json.loads(win32crypt.CryptUnprotectData(encrypted, None, None, None, 0)[1])
        if value['url'] != pacs_address(url) or not value['username'] or not value['password']:
            raise ValueError()
        return {'username': value['username'], 'password': value['password']}
    except Exception:
        raise ValueError('PACS credentials are unavailable or belong to another endpoint. Save the account again.') from None
