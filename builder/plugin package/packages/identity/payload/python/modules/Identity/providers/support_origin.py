"""Same-host verified TLS transport for a paired website's support upload origin.

Never changes DNS, the website URL, credentials, AI routing or proxy policy.
Only an authenticated support capability can supply the public origin address.
"""
import ipaddress
from urllib.parse import urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter


class SupportOriginAdapter(HTTPAdapter):
    def __init__(self, hostname, address):
        if hostname != 'ai-pacs.com' or not isinstance(address, str):
            raise ValueError('Unsupported support origin')
        address = ipaddress.IPv4Address(address)
        if not address.is_global:
            raise ValueError('Support origin must be a public IPv4 address')
        self.hostname = hostname
        self.address = str(address)
        super().__init__(max_retries=0)

    def get_connection_with_tls_context(self, request, verify, proxies=None, cert=None):
        parsed = urlsplit(request.url)
        if parsed.scheme != 'https' or parsed.hostname != self.hostname or parsed.port not in (None, 443):
            raise ValueError('Unsupported support destination')
        if verify is not True or proxies:
            raise ValueError('Support origin requires normal verified direct HTTPS')
        clone = request.copy()
        clone.url = urlunsplit(('https', self.address, parsed.path, parsed.query, ''))
        pool = super().get_connection_with_tls_context(clone, verify, {}, cert)
        pool.assert_hostname = self.hostname
        pool.conn_kw['server_hostname'] = self.hostname
        request.headers['Host'] = self.hostname
        return pool

    def get_connection(self, url, proxies=None):
        """Requests 2.31 compatibility, which the runtime requirements still allow."""
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != self.hostname or parsed.port not in (None, 443) or proxies:
            raise ValueError('Unsupported support destination or proxy policy')
        address_url = urlunsplit(('https', self.address, parsed.path, parsed.query, ''))
        pool = super().get_connection(address_url, {})
        pool.assert_hostname = self.hostname
        pool.conn_kw['server_hostname'] = self.hostname
        return pool

    def add_headers(self, request, **kwargs):
        if urlsplit(request.url).hostname != self.hostname:
            raise ValueError('Unsupported support destination')
        request.headers['Host'] = self.hostname


def support_origin_session(source, base_url, address):
    parsed = urlsplit(base_url)
    if (parsed.scheme != 'https' or parsed.hostname != 'ai-pacs.com'
            or parsed.port not in (None, 443) or parsed.username or parsed.password
            or parsed.path.rstrip('/') != '/consult-form' or parsed.query or parsed.fragment):
        raise ValueError('Unsupported support destination')
    adapter = SupportOriginAdapter(parsed.hostname, address)
    if source.verify is not True or source.proxies or (source.trust_env and requests.utils.get_environ_proxies(base_url)):
        adapter.close()
        raise ValueError('Support origin cannot bypass configured proxy or TLS policy')
    target = requests.Session()
    target.trust_env = source.trust_env
    target.cert = source.cert
    target.headers.update(source.headers)
    target.cookies.update(source.cookies)
    target.mount('https://ai-pacs.com/', adapter)
    return target
