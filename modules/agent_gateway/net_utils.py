"""Networking helpers — local address discovery for the pairing QR.

Pure stdlib (psutil is used opportunistically when present). Best-effort: returns
every plausible address a client could dial, so the phone can try them in order.
Never raises.

WHY THIS IS NOT JUST `gethostbyname`
------------------------------------
A clinical PACS box is routinely multi-homed: several static IPs on one NIC (one
per modality subnet) PLUS tunnel/VPN adapters (WireGuard/OpenVPN). The original
implementation enumerated addresses via ``socket.getaddrinfo(hostname)``, which on
Windows returns only the addresses registered for the host name — it SILENTLY
OMITS WireGuard/VPN tunnel adapters. On the reference workstation that hid
``192.168.24.41`` (the WireGuard address), which is precisely the address a
REMOTE phone must dial. The QR therefore advertised ten unreachable LAN IPs and
the app reported "out of local network".

So: enumerate per-adapter via ``psutil.net_if_addrs()`` when available (it sees
every adapter, tunnels included) and fall back to the hostname method only if
psutil is missing.
"""
from __future__ import annotations

import logging
import socket
from typing import List, Optional

logger = logging.getLogger(__name__)


def _is_usable_ipv4(ip: str) -> bool:
    """Reject loopback, link-local (APIPA) and empty/garbage addresses."""
    ip = (ip or "").strip()
    if not ip or ip.count(".") != 3:
        return False
    if ip.startswith("127.") or ip.startswith("169.254."):
        return False
    if ip in ("0.0.0.0", "255.255.255.255"):
        return False
    return True


def primary_lan_ip() -> str:
    """The IPv4 this host uses toward the default route.

    Classic "connect a UDP socket and read back the local endpoint" trick — no
    packet is sent. Falls back to ``127.0.0.1``.
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            if s is not None:
                s.close()
        except Exception:
            pass


def _psutil_ipv4() -> List[str]:
    """Every IPv4 on every adapter (tunnels included), or [] if psutil absent."""
    out: List[str] = []
    try:
        import psutil  # optional dependency; already used elsewhere in the app

        for _iface, addrs in (psutil.net_if_addrs() or {}).items():
            for a in addrs:
                if getattr(a, "family", None) == socket.AF_INET:
                    ip = getattr(a, "address", "")
                    if _is_usable_ipv4(ip) and ip not in out:
                        out.append(ip)
    except Exception as exc:  # pragma: no cover - psutil optional
        logger.debug("psutil address enumeration failed: %s", exc)
    return out


def _hostname_ipv4() -> List[str]:
    """Legacy fallback: addresses registered for this host name."""
    out: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if _is_usable_ipv4(ip) and ip not in out:
                out.append(ip)
    except Exception:
        pass
    return out


def all_lan_ipv4(advertise_host: Optional[str] = None) -> List[str]:
    """All dialable IPv4 addresses for this host, best candidate first.

    Ordering (this is what the pairing QR advertises, and the phone tries in
    order, so it matters):

    1. ``advertise_host`` when the operator pinned one in Settings ▸ Agent —
       always first, even if it is not locally detected (it may be a public
       hostname / DDNS name / relay address).
    2. The default-route address (:func:`primary_lan_ip`).
    3. Everything else discovered, de-duplicated.

    Never raises; always returns at least one entry.
    """
    ordered: List[str] = []

    pinned = (advertise_host or "").strip()
    if pinned:
        ordered.append(pinned)

    primary = primary_lan_ip()
    if _is_usable_ipv4(primary) and primary not in ordered:
        ordered.append(primary)

    discovered = _psutil_ipv4() or _hostname_ipv4()
    for ip in discovered:
        if ip not in ordered:
            ordered.append(ip)

    if not ordered:
        ordered.append(primary or "127.0.0.1")
    return ordered


def detected_ipv4() -> List[str]:
    """Every detected local IPv4 (for the Settings picker). No pinned entry."""
    primary = primary_lan_ip()
    out: List[str] = []
    if _is_usable_ipv4(primary):
        out.append(primary)
    for ip in (_psutil_ipv4() or _hostname_ipv4()):
        if ip not in out:
            out.append(ip)
    return out


def resolve_bind_host(bind_scope: str) -> str:
    """Map a config ``bind_scope`` to an actual bind address."""
    scope = str(bind_scope or "lan").strip().lower()
    if scope in ("loopback", "local", "127", "127.0.0.1"):
        return "127.0.0.1"
    return "0.0.0.0"  # all interfaces (LAN + tunnel reachable)


__all__ = [
    "primary_lan_ip",
    "all_lan_ipv4",
    "detected_ipv4",
    "resolve_bind_host",
]
