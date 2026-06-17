"""Guards for the first-image prime (2026-06-17, slow/unstable-link drag-drop).

Production complaint: on a very slow / frequently-dropping link a drag-dropped
series shows NOTHING until the whole first ~10-image batch clears (first-batch
time is dominated by the socket timeout, not transfer), so the user assumes it is
stuck and re-drags — thrashing the single download slot. The fix fetches the
FIRST batch of a freshly-viewed series as a single image so the progressive feed
paints one slice in one round-trip, then restores the full adaptive batch size so
bulk transfer speed is unchanged. Default on; kill switch AIPACS_FIRST_IMAGE_PRIME=0.

These tests pin the pure prime/restore decision AND that it is actually wired into
``download_series`` with the post-first-batch restore (so the helper can't pass
while being dead code). ``socket_client`` pulls heavy deps, so the helper import is
guarded with a skip for minimal environments (matching test_batch_growth.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SRC = (
    _REPO_ROOT / "modules/download_manager/network/socket_client.py"
).read_text(encoding="utf-8")


def _prime():
    try:
        from modules.download_manager.network.socket_client import _first_image_prime_size
    except Exception as exc:  # heavy deps absent in this shard
        pytest.skip(f"socket_client import unavailable: {exc}")
    return _first_image_prime_size


# ---- pure decision -------------------------------------------------------

def test_fresh_series_primes_to_one_and_remembers_restore():
    prime = _prime()
    # Nothing on disk, multi-image batch, not force-single, enabled → fetch slice 1
    # as a size-1 batch and remember the original adaptive size to restore.
    assert prime(True, 0, 10, False) == (1, 10)


def test_disabled_flag_no_prime():
    prime = _prime()
    # Kill switch (AIPACS_FIRST_IMAGE_PRIME=0): byte-identical legacy behavior.
    assert prime(False, 0, 10, False) == (10, None)


def test_resume_no_prime():
    prime = _prime()
    # skipped_count>0 means a resume — the R19b leading-batch skip must be
    # unaffected, so the prime never engages.
    assert prime(True, 5, 10, False) == (10, None)


def test_force_single_modality_no_prime():
    prime = _prime()
    # Modalities already at one image per batch (DX/CR/MG/XA/RF/...) — nothing to
    # prime; pass the size through unchanged with no restore bookkeeping.
    assert prime(True, 0, 1, True) == (1, None)


def test_batch_already_one_no_prime():
    prime = _prime()
    # Adaptive size is already 1 → no benefit and nothing to restore.
    assert prime(True, 0, 1, False) == (1, None)


def test_restore_echoes_the_full_adaptive_size():
    prime = _prime()
    # The restore size is exactly whatever adaptive size came in (e.g. a grown 20).
    first, restore = prime(True, 0, 20, False)
    assert first == 1 and restore == 20


# ---- wiring into download_series (catches a refactor that drops the wiring) --

def test_flag_defaults_on_with_zero_kill_switch():
    assert 'AIPACS_FIRST_IMAGE_PRIME", "1"' in _SRC  # default on; "=0" disables


def test_helper_is_consumed_not_dead_code():
    assert "batch_size, _prime_restore_size = _first_image_prime_size(" in _SRC


def test_full_size_restored_after_first_batch():
    # The size is restored once batch_idx 0 has been written, so the remainder of
    # the series downloads at the full adaptive size (bulk speed unchanged).
    assert "_prime_restore_size is not None and batch_idx == 1" in _SRC
    assert "batch_size = _prime_restore_size" in _SRC
