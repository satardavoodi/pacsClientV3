"""Guard for the tolerant socket-payload decode (client PC 'pc user 2 sanam', 2026-06-15).

Bug: the download socket client parsed responses with `json.loads(data.decode('utf-8'))`.
A non-UTF-8 byte in a name/description field (Persian / Western-European source data
encoded Windows-1256 / Latin-1) raised UnicodeDecodeError at _send_request_once and
aborted the WHOLE download (observed bytes 0xe7/0xf6/0xed/0xfb). Fix: decode tolerantly
(strict UTF-8 first, then replacement) so json.loads still succeeds and the download
proceeds. The same strict-decode existed in the patient-list/thumbnail client.
"""
import ast
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DM_CLIENT = REPO / "modules/download_manager/network/socket_client.py"
NET_CLIENT = REPO / "modules/network/socket_client.py"


def test_decode_helper_passes_valid_utf8_unchanged():
    from modules.download_manager.network.socket_client import _decode_socket_payload
    payload = json.dumps({"patient_name": "Müller", "ok": True}).encode("utf-8")
    out = _decode_socket_payload(payload)
    assert json.loads(out) == {"patient_name": "Müller", "ok": True}


def test_decode_helper_survives_non_utf8_bytes():
    from modules.download_manager.network.socket_client import _decode_socket_payload
    # Valid JSON with a raw Windows-1256/Latin-1 byte (0xe7) spliced into a string
    # value — strict utf-8 would raise here.
    raw = b'{"patient_name": "K\xe7AZAIE", "study_uid": "1.2.3"}'
    try:
        raw.decode("utf-8")
        raised = False
    except UnicodeDecodeError:
        raised = True
    assert raised, "test fixture must actually be non-UTF-8"
    out = _decode_socket_payload(raw)            # must not raise
    obj = json.loads(out)                          # must still parse
    assert obj["study_uid"] == "1.2.3"            # critical fields intact
    assert obj["patient_name"].startswith("K")    # name degraded but present


def test_decode_helper_handles_each_observed_byte():
    from modules.download_manager.network.socket_client import _decode_socket_payload
    for b in (b"\xe7", b"\xf6", b"\xed", b"\xfb"):
        raw = b'{"n": "x' + b + b'y", "u": "1"}'
        obj = json.loads(_decode_socket_payload(raw))
        assert obj["u"] == "1"


# ── both parse sites use the tolerant decode (no bare strict decode) ──────────

def _parse_site_is_tolerant(path, func_substr_required):
    src = path.read_text(encoding="utf-8")
    # The exact crashing form must no longer appear as a parse of the response.
    assert "json.loads(response_data.decode('utf-8'))" not in src, (
        f"{path.name} still has the strict-decode crash form"
    )
    assert func_substr_required in src


def test_dm_client_uses_tolerant_decode():
    _parse_site_is_tolerant(DM_CLIENT, "_decode_socket_payload(response_data)")


def test_net_client_uses_tolerant_decode():
    src = NET_CLIENT.read_text(encoding="utf-8")
    assert "json.loads(response_data.decode('utf-8'))" not in src
    assert "errors='replace'" in src


def test_broadcast_retry_cap_raised_and_configurable():
    """Bug B: GetSeriesImages failed with 'Too many broadcast messages' at a hard
    cap of 10. The cap is now configurable with a higher default (>=50) so a busy
    server's legitimate broadcast bursts don't fail the download."""
    from modules.download_manager.network import socket_client as sc
    assert sc._MAX_BROADCAST_RETRIES >= 50
    src = DM_CLIENT.read_text(encoding="utf-8")
    assert "max_broadcast_retries = _MAX_BROADCAST_RETRIES" in src
    assert "AIPACS_MAX_BROADCAST_RETRIES" in src
