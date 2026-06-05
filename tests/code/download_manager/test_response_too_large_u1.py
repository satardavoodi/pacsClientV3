"""U1 guard — "Response too large" must reach the adaptive-batch logic (2026-06-05).

Production evidence (other-PC frozen-build logs): 16 series failures with
"Response too large". Root cause in source: ``send_request`` swallowed the
``NetworkError`` raised at the >500MB length check and returned ``None``, so
``download_series`` only ever saw ``'No response'`` and its halving branch
(``"Response too large" in str(error_msg)``) was dead code.

Contract pinned here:
  1. ``send_request`` converts the too-large NetworkError into a structured
     error dict for the ``GetSeriesImages`` endpoint only (other endpoints
     keep the None-on-error contract).
  2. ``download_series`` halves the batch on that error AND, at minimum batch
     size, performs bounded same-size retries (stream-desync recovery) before
     failing with the real reason.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SRC = (
    _REPO_ROOT / "modules/download_manager/network/socket_client.py"
).read_text(encoding="utf-8")


def test_send_request_surfaces_too_large_for_batch_endpoint():
    # The structured-error return exists, is scoped to GetSeriesImages, and
    # sits inside the generic exception handler (after the raise site).
    i_raise = _SRC.index('raise NetworkError(f"Response too large')
    m = re.search(
        r"if endpoint == 'GetSeriesImages' and \"Response too large\" in str\(e\):"
        r"\s*\n\s*return \{'status': 'error', 'error': str\(e\), 'message': str\(e\)\}",
        _SRC,
    )
    assert m is not None, "structured too-large error return missing"
    assert m.start() > i_raise, "error conversion must follow the raise site"


def test_raise_site_still_drops_socket_first():
    # The desync recovery depends on the socket being dropped before the
    # raise — keep close+None+connected=False ahead of the NetworkError.
    i_raise = _SRC.index('raise NetworkError(f"Response too large')
    window = _SRC[max(0, i_raise - 600):i_raise]
    assert "self.socket = None" in window
    assert "self.connected = False" in window


def test_download_series_halves_then_retries_at_min_batch():
    # Halving branch is no longer gated away at min batch size: the
    # outer check is on the message alone, with the size check nested.
    i_outer = _SRC.index('if "Response too large" in str(error_msg):')
    i_halve = _SRC.index("batch_size = max(min_batch_size, batch_size // 2)")
    i_min_retry = _SRC.index("if too_large_retries < _TOO_LARGE_MIN_BATCH_RETRIES:")
    assert i_outer < i_halve < i_min_retry
    # Bounded budget exists and resets on a successful batch.
    assert "_TOO_LARGE_MIN_BATCH_RETRIES = 2" in _SRC
    i_reset = _SRC.index(
        "too_large_retries = 0",
        _SRC.index("# Successful batch"),
    )
    assert i_reset > i_min_retry, "reset must live on the success path"


def test_min_batch_retry_continues_not_returns():
    # The desync retry must loop (continue), not abort the series.
    block_start = _SRC.index("if too_large_retries < _TOO_LARGE_MIN_BATCH_RETRIES:")
    block = _SRC[block_start:block_start + 700]
    assert "continue" in block.split("# Exhausted")[0]
