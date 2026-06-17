"""Guards for the unstable-internet retry policy (2026-06-16).

Client logs (pc 2 baba, 11 days) showed a flaky connection burning the 3-retry
cap almost immediately, after which a study logged "exceeded max retries (3),
requires manual intervention" and got STUCK — the direct cause of "overnight
batch only partially downloaded". The fix raises the retry budget for
TEMPORARY/network failures (``MAX_RETRIES_TEMPORARY``) while PERMANENT failures
still fail fast, driven by ``classify_download_failure``.

These tests pin the classifier (the heart of the policy) and the budget
constants. ``constants.py`` imports only the stdlib, so we load it directly from
its file path — no Qt, no ``modules.download_manager`` package import (which has
a known order-dependent circular-import quirk).
"""

import importlib.util
from pathlib import Path

import pytest

# modules/download_manager/core/constants.py — five parents up from this test:
# tests/code/download_manager/<file> -> repo root.
_REPO = Path(__file__).resolve().parents[3]
_CONSTANTS = _REPO / "modules" / "download_manager" / "core" / "constants.py"


def _load_constants():
    if not _CONSTANTS.is_file():
        pytest.skip(f"constants.py not found at {_CONSTANTS}")
    spec = importlib.util.spec_from_file_location("_dm_constants_under_test", _CONSTANTS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_temporary_budget_is_higher_than_permanent():
    c = _load_constants()
    assert c.MAX_RETRIES_TEMPORARY > c.MAX_RETRIES
    assert c.MAX_RETRIES_TEMPORARY >= 10  # overnight flaky-connection headroom


@pytest.mark.parametrize("msg", [
    "timed out",
    "Socket connection lost, attempting to reconnect with backoff",
    "Response too large",
    "[WinError 10054] An existing connection was forcibly closed",
    "Download failed (no error message)",
    "Failed to fetch metadata",
    "Invalid response length header",
    "Get report status failed: No response",
    "",            # unknown / blank → default temporary (keep retrying)
    None,
])
def test_network_failures_classified_temporary(msg):
    c = _load_constants()
    assert c.classify_download_failure(msg) == "temporary"


@pytest.mark.parametrize("msg", [
    "Study not found: 404",
    "401 unauthorized",
    "decode error in pixel data",
    "disk full",
    "permission denied",
])
def test_server_permanent_failures_classified_permanent(msg):
    c = _load_constants()
    assert c.classify_download_failure(msg) == "permanent"


def test_permanent_signature_wins_over_temporary():
    # A message containing BOTH a permanent and a temporary token resolves to
    # permanent (explicit server rejection beats a network hint).
    c = _load_constants()
    assert c.classify_download_failure("404 not found (connection reset)") == "permanent"
