"""Self-signed TLS identity for the gateway (cert-pinning support).

The workstation generates a long-lived self-signed certificate once and reuses
it. Its SHA-256 fingerprint travels inside the pairing QR so the phone can
**pin** the certificate — the phone trusts exactly this cert and nothing else,
which is the right model for a self-signed LAN/relay endpoint (no public CA
needed, no user "accept the risk" prompt).

Uses the ``cryptography`` library (already a project dependency). Cert + key are
written to the roaming gateway data dir (never the shipped repo). Regenerated
automatically if missing/unreadable. Import-light: ``cryptography`` is imported
lazily inside the functions so a disabled gateway never pays for it.
"""
from __future__ import annotations

import datetime
import ipaddress
import logging
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

CERT_FILENAME = "gateway_cert.pem"
KEY_FILENAME = "gateway_key.pem"


def _material_dir() -> Path:
    from .config_store import gateway_data_dir

    return gateway_data_dir()


def cert_key_paths(data_dir: Optional[Path] = None) -> Tuple[Path, Path]:
    d = Path(data_dir) if data_dir is not None else _material_dir()
    return d / CERT_FILENAME, d / KEY_FILENAME


def ensure_identity(
    san_hosts: Optional[List[str]] = None,
    data_dir: Optional[Path] = None,
    regenerate: bool = False,
) -> Tuple[Path, Path, str]:
    """Ensure a cert+key exist; return ``(cert_path, key_path, fingerprint)``.

    ``fingerprint`` is ``"sha256:AA:BB:.."`` (upper hex, colon-separated) — the
    exact string placed in the QR for pinning. ``san_hosts`` adds Subject
    Alternative Names (the LAN IPs / hostname) so the cert matches whatever
    address the phone dials.
    """
    cert_path, key_path = cert_key_paths(data_dir)
    if not regenerate and cert_path.exists() and key_path.exists():
        try:
            fp = fingerprint_of(cert_path)
            # Reuse ONLY if the existing cert already covers every requested
            # SAN. A multi-homed box can gain an address later (e.g. a VPN
            # tunnel comes up); serving a cert that omits the address the phone
            # dials makes strict TLS clients reject the connection, so in that
            # case we regenerate rather than silently reuse.
            if fp and _covers_sans(cert_path, san_hosts or []):
                return cert_path, key_path, fp
        except Exception:
            pass  # fall through to regenerate a broken pair

    cert_pem, key_pem, fp = _generate(san_hosts or [])
    try:
        cert_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key_pem)
        cert_path.write_bytes(cert_pem)
        try:
            # Best-effort: restrict key permissions where the OS honours it.
            import os
            import stat

            os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("[AGENT_GATEWAY] could not persist TLS material: %s", exc)
    return cert_path, key_path, fp


def _generate(san_hosts: List[str]) -> Tuple[bytes, bytes, str]:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "AI-PACS Agent Gateway")]
    )

    san: List[x509.GeneralName] = [x509.DNSName("localhost")]
    for host in san_hosts:
        host = str(host or "").strip()
        if not host:
            continue
        try:
            san.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            san.append(x509.DNSName(host))
    try:
        san.append(x509.IPAddress(ipaddress.ip_address("127.0.0.1")))
    except ValueError:
        pass

    now = datetime.datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=3650))  # 10 years
        .add_extension(x509.SubjectAlternativeName(san), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
    fp = _fingerprint_from_cert(cert)
    return cert_pem, key_pem, fp


def _fingerprint_from_cert(cert) -> str:
    from cryptography.hazmat.primitives import hashes

    digest = cert.fingerprint(hashes.SHA256())
    hexstr = digest.hex().upper()
    pairs = ":".join(hexstr[i:i + 2] for i in range(0, len(hexstr), 2))
    return f"sha256:{pairs}"


def cert_san_values(cert_path: Path) -> List[str]:
    """Every SAN entry (DNS names + IP addresses as strings) in a PEM cert."""
    from cryptography import x509

    out: List[str] = []
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
        san = cert.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
        out.extend(str(v) for v in san.get_values_for_type(x509.DNSName))
        out.extend(str(v) for v in san.get_values_for_type(x509.IPAddress))
    except Exception as exc:  # pragma: no cover - malformed/absent extension
        logger.debug("SAN read failed for %s: %s", cert_path, exc)
    return out


def _covers_sans(cert_path: Path, required: List[str]) -> bool:
    """True when the cert's SAN list already contains every required host."""
    wanted = {str(h).strip() for h in (required or []) if str(h).strip()}
    if not wanted:
        return True
    have = set(cert_san_values(cert_path))
    return wanted.issubset(have)


def fingerprint_of(cert_path: Path) -> str:
    """SHA-256 fingerprint of an on-disk PEM cert (``sha256:AA:BB:..``)."""
    from cryptography import x509

    data = Path(cert_path).read_bytes()
    cert = x509.load_pem_x509_certificate(data)
    return _fingerprint_from_cert(cert)


def build_ssl_context(cert_path: Path, key_path: Path):
    """A server-side ``ssl.SSLContext`` loaded with the gateway cert+key."""
    import ssl

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


__all__ = [
    "ensure_identity",
    "cert_key_paths",
    "fingerprint_of",
    "cert_san_values",
    "build_ssl_context",
    "CERT_FILENAME",
    "KEY_FILENAME",
]
