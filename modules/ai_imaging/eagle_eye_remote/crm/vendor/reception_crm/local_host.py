"""Where the reception software lives, from this machine's point of view.

This agent is designed to be installed **on the reception server itself**, so
the practice API is always on this same box. That is a deployment guarantee,
not a user preference, and the host is therefore resolved internally rather
than exposed as an editable field: nobody should be able to point a clinic's
agent at some other clinic's reception server. Only the **port** is
configurable, because that genuinely varies between installations.

Why this is not simply ``127.0.0.1``
------------------------------------
Measured on the Razi reception server (2026-08-13), from the machine itself
with the proxy bypassed:

    http://127.0.0.1:8080/api/auth/login       -> 404 Not Found
    http://localhost:8080/api/auth/login       -> 404 Not Found
    http://<the machine's own LAN IP>:8080/... -> 401 Unauthorized  (route exists)
    http://127.0.0.1:8080/api/personnel        -> 200, data, no credential sent

The vendor's ``server-interface`` does not serve the auth route on loopback,
though it happily serves *data* there with no credential at all. So pointing
this agent at ``127.0.0.1`` produces the worst possible outcome: reads appear
to work while ``login()`` raises, no session can ever be minted, and the mobile
app can sign nobody in — a failure that looks like a mobile bug.

The machine's own LAN address is still completely local: a route lookup on the
server resolves it on its own interface with an empty next hop, so the traffic
is delivered internally and never reaches the router. It is "localhost" in
every sense that matters here, and unlike loopback it works.

Resolution order
----------------
1. ``RECEPTION_LOCAL_HOST`` — an escape hatch for development, where the agent
   runs on a workstation rather than on the reception server. It is deliberately
   NOT a settings-file field: production installs must not carry a foreign host.
2. Each non-loopback IPv4 address of this machine, probed against the practice
   API and accepted only if the auth route actually exists there.
3. ``127.0.0.1`` as a last resort, so a misconfigured box still starts and logs
   a clear reason rather than crashing at import time.
"""

from __future__ import annotations

import ipaddress
import logging
import os
import socket
import urllib.error
import urllib.request

LOG = logging.getLogger("reception_crm.local_host")

ENV_OVERRIDE = "RECEPTION_LOCAL_HOST"
LOOPBACK = "127.0.0.1"
PROBE_PATH = "/api/auth/login"
PROBE_TIMEOUT_SECONDS = 3

# A GET against a POST-only route answers 405; a route that is not served at all
# answers 404. Either way nothing is submitted, so the probe cannot create a
# failed-login record or trip an account lockout.
_ROUTE_ABSENT = 404

_cache: dict[int, str] = {}


def local_ipv4_addresses() -> list[str]:
    """Every non-loopback, non-link-local IPv4 address of this machine.

    The address the OS would use to reach the default gateway is placed first:
    on a multi-homed server that is the one the practice API is most likely to
    be reachable on, and trying it first keeps the common case to one probe.
    """
    addresses: list[str] = []

    primary = _primary_ipv4()
    if primary:
        addresses.append(primary)

    try:
        _, _, resolved = socket.gethostbyname_ex(socket.gethostname())
    except OSError:
        resolved = []

    for candidate in resolved:
        if candidate in addresses:
            continue
        try:
            parsed = ipaddress.IPv4Address(candidate)
        except ipaddress.AddressValueError:
            continue
        if parsed.is_loopback or parsed.is_link_local:
            continue
        addresses.append(candidate)

    return addresses


def _primary_ipv4() -> str:
    """The source address the OS would pick for outbound traffic.

    A UDP socket is *connected* but never sent on, so this performs no network
    I/O and works on a machine with no internet access.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))
        return str(probe.getsockname()[0])
    except OSError:
        return ""
    finally:
        probe.close()


def _auth_route_exists(host: str, port: int) -> bool:
    url = f"http://{host}:{port}{PROBE_PATH}"
    request = urllib.request.Request(url, method="GET")
    # An explicit empty-proxy opener: a system proxy would answer for the
    # practice API and make every candidate look identical.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=PROBE_TIMEOUT_SECONDS) as response:
            return int(response.status) != _ROUTE_ABSENT
    except urllib.error.HTTPError as exc:
        # 401 / 403 / 405 / 400 all mean the route is there and answering.
        return int(exc.code) != _ROUTE_ABSENT
    except (urllib.error.URLError, OSError, ValueError):
        return False


def resolve_reception_host(port: int, *, refresh: bool = False) -> str:
    """The address of the reception software as seen from this machine.

    Cached per port for the life of the process: this is a property of where
    the service is installed, and re-probing on every upstream call would add a
    round trip to every request for no benefit.
    """
    override = (os.getenv(ENV_OVERRIDE) or "").strip()
    if override:
        return override

    if not refresh and port in _cache:
        return _cache[port]

    for candidate in local_ipv4_addresses():
        if _auth_route_exists(candidate, port):
            LOG.info("reception software resolved on this machine at %s:%s", candidate, port)
            _cache[port] = candidate
            return candidate

    LOG.warning(
        "no local address answered %s on port %s; falling back to %s. If the practice API "
        "is running, note that it may not serve the auth route on loopback, in which case "
        "per-user sessions cannot be minted.",
        PROBE_PATH,
        port,
        LOOPBACK,
    )
    _cache[port] = LOOPBACK
    return LOOPBACK


def reset_cache() -> None:
    """Test seam."""
    _cache.clear()
