"""Support-only origin retry retains TLS, identity and existing proxy policy."""
import pytest
import requests


def test_origin_pool_retains_domain_sni_certificate_and_host():
    from modules.Identity.providers.support_origin import SupportOriginAdapter
    adapter = SupportOriginAdapter('ai-pacs.com', '46.202.158.216')
    request = requests.Request('POST', 'https://ai-pacs.com/consult-form/api/v1/support/issues').prepare()
    pool = adapter.get_connection_with_tls_context(request, True, {})
    assert pool.host == '46.202.158.216'
    assert pool.assert_hostname == 'ai-pacs.com'
    assert pool.conn_kw['server_hostname'] == 'ai-pacs.com'
    assert request.url.startswith('https://ai-pacs.com/')
    assert request.headers['Host'] == 'ai-pacs.com'
    adapter.close()


def test_legacy_requests_pool_also_retains_domain_certificate_and_host():
    from modules.Identity.providers.support_origin import SupportOriginAdapter
    adapter = SupportOriginAdapter('ai-pacs.com', '46.202.158.216')
    request = requests.Request('POST','https://ai-pacs.com/consult-form/api/v1/support/issues').prepare()
    pool = adapter.get_connection(request.url, {})
    adapter.add_headers(request)
    assert pool.host == '46.202.158.216'
    assert pool.assert_hostname == pool.conn_kw['server_hostname'] == 'ai-pacs.com'
    assert request.headers['Host'] == 'ai-pacs.com'
    adapter.close()


@pytest.mark.parametrize('address', ['127.0.0.1', '192.168.1.1', '169.254.169.254', '::1', 'example.com'])
def test_origin_rejects_nonpublic_ipv4(address):
    from modules.Identity.providers.support_origin import support_origin_session
    with pytest.raises(ValueError):
        support_origin_session(requests.Session(), 'https://ai-pacs.com/consult-form', address)


def test_origin_rejects_proxy_tls_override_or_another_destination():
    from modules.Identity.providers.support_origin import support_origin_session
    source = requests.Session()
    source.trust_env = False
    for change in ('proxy', 'verify', 'destination'):
        source.proxies = {'https':'http://synthetic.invalid:8080'} if change == 'proxy' else {}
        source.verify = change != 'verify'
        url = 'https://other.invalid/consult-form' if change == 'destination' else 'https://ai-pacs.com/consult-form'
        with pytest.raises(ValueError):
            support_origin_session(source, url, '46.202.158.216')


def test_origin_api_cannot_route_unrelated_calls_or_bypass_redirect_policy(monkeypatch):
    from modules.Identity.providers.aipacs_web import AipacsWebClient
    monkeypatch.setattr('modules.Identity.thread_guard.assert_off_gui_thread', lambda *args:None)
    client = AipacsWebClient('https://ai-pacs.com/consult-form', token='synthetic-token')
    for path in ('/me', '/chat/messages', '/support/issues/upload-capabilities', '/support/issues/../me'):
        with pytest.raises(ValueError):
            client.request_support_json(path, {}, origin_ipv4='46.202.158.216')
