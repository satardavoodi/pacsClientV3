"""Guards for B6 — oversized-single-instance fast-fail (2026-06-21, staged default-off).

A "Response too large" at a single-instance batch is the server's hard payload cap on
one oversized instance: deterministic, so the inner exponential-backoff retry (plus the
coordinator's series re-attempts) just burns minutes before the series fails anyway
(observed ~8 min on a 558 MB instance). A genuine stream-DESYNC still recovers on ONE
fresh-socket reconnect, so the fix allows exactly one quick reconnect then fails fast —
ONLY for single-instance (batch_size<=1) "Response too large"; normal multi-image
batches and every other error keep the full R27/R28 backoff-retry.

These are source-pin guards (the loop needs a live socket/server to exercise), matching
the style of test_first_image_prime.py. Default-off ⇒ production is byte-identical.
"""
from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC = (
    _REPO_ROOT / "modules/download_manager/network/socket_client.py"
).read_text(encoding="utf-8")


def test_fastfail_flag_defaults_off():
    # Staged: production stays byte-identical (full backoff-retry) until
    # AIPACS_FASTFAIL_OVERSIZE=1 is set and live-validated.
    assert 'AIPACS_FASTFAIL_OVERSIZE", "0"' in _SRC          # default OFF
    assert "_FASTFAIL_OVERSIZE = (os.getenv(" in _SRC


def test_fastfail_scoped_to_single_instance_too_large():
    # Must only engage for single-instance (batch_size<=1) "Response too large" —
    # never for normal multi-image batches or other errors.
    assert 'batch_size <= 1 and "Response too large" in str(e)' in _SRC


def test_fastfail_preserves_one_desync_reconnect():
    # Exactly one quick fresh-socket reconnect (stream-desync recovery) before
    # failing fast — not zero (would break desync recovery), not many (the bug).
    assert "_oversize_seen += 1" in _SRC
    assert "_oversize_seen >= 2" in _SRC
    assert "self.connect_with_retry(max_retries=3)" in _SRC


def test_fastfail_guarded_by_flag_so_legacy_path_intact():
    # The fast-fail block is gated by the flag; the legacy R27/R28 backoff-retry
    # ("Exponential backoff with jitter") remains present for the default path.
    assert "if _FASTFAIL_OVERSIZE and batch_size <= 1" in _SRC
    assert "Exponential backoff with jitter" in _SRC
