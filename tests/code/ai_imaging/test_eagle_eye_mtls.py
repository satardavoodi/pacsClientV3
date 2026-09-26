import json, threading, urllib.request, urllib.error
from pathlib import Path
import pytest
from tests.code.ai_imaging.test_eagle_eye_remote import SyntheticSource, synthetic_runner
from modules.ai_imaging.eagle_eye_remote import client, server, source
def test_mtls_requires_certificate_bound_to_token_owner(tmp_path, monkeypatch):
    from datetime import datetime, timedelta, timezone
    import ipaddress
    import secrets
    import socket
    import ssl
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'Synthetic Eagle Eye test')])
    now = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .sign(key, hashes.SHA256()))
    cert_path, key_path, token_path = (tmp_path / name for name in ('fixture.pem', 'fixture.key', 'fixture.token'))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
    token_path.write_text(secrets.token_hex(32), encoding='utf-8')
    monkeypatch.delenv('EAGLE_TLS_FIXTURE_TOKEN', raising=False)
    monkeypatch.setattr(source, 'source_provider', lambda cfg: SyntheticSource())
    http, jobs = server.create_server(dict(host='127.0.0.1', port=0,
        job_root=str(tmp_path / 'server'), pacs={}, clients={'fixture': str(token_path)},
        certificate=str(cert_path), private_key=str(key_path),
        client_ca_file=str(cert_path), client_certificate_sha256={'fixture':certificate.fingerprint(hashes.SHA256()).hex()}))
    jobs.runner = synthetic_runner
    worker = threading.Thread(target=http.serve_forever, daemon=True)
    worker.start()
    cfg = dict(url=f'https://127.0.0.1:{http.server_port}', token_file=str(token_path),
               token_env='EAGLE_TLS_FIXTURE_TOKEN', ca_file=str(cert_path),
               client_certificate=str(cert_path), client_private_key=str(key_path))
    try:
        with pytest.raises((RuntimeError, ssl.SSLError)):
            client.Client({**cfg, 'client_certificate':'', 'client_private_key':''}).json('/v1/capabilities')
        # A peer that connects but never begins TLS must not block other clients.
        stalled_peer = socket.create_connection(('127.0.0.1', http.server_port), timeout=3)
        try:
            connection = client.Client(cfg)
            probe = urllib.request.Request(cfg['url'] + '/v1/capabilities',
                headers={'Authorization': 'Bearer ' + connection.token})
            with connection.opener.open(probe, timeout=2) as response:
                assert json.load(response)['protocol'] == 1
        finally:
            stalled_peer.close()
        assert client.Client(cfg).json('/v1/capabilities')['input_mode'] == 'pacs_references'
        # A trusted certificate belonging to another identity must not use this token.
        original_handler = http.RequestHandlerClass
        http.RequestHandlerClass = server.handler(jobs, {'fixture':token_path.read_text()}, {'fixture':'0'*64})
        with pytest.raises(RuntimeError):
            client.Client(cfg).json('/v1/capabilities')
        http.RequestHandlerClass = original_handler
        result = client.Client(cfg).analyze('bone-age', '1.2.3', {}, {}, tmp_path / 'client')
        assert Path(result['report']).read_bytes() == b'%PDF-1.4 synthetic'
        for invalid in ({**cfg, 'ca_file': ''},
                        {**cfg, 'url': f'https://localhost:{http.server_port}'}):
            invalid_client = client.Client(invalid)
            with pytest.raises(urllib.error.URLError) as failure:
                invalid_client.opener.open(invalid['url'] + '/v1/capabilities', timeout=3)
            assert isinstance(failure.value.reason, ssl.SSLCertVerificationError)
            with pytest.raises(RuntimeError, match='request failed'):
                invalid_client.json('/v1/capabilities')
    finally:
        http.shutdown()
        http.server_close()
        jobs.close()
        worker.join(timeout=3)
