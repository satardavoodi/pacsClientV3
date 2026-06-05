"""Guards for the large-radiology batch-stall fixes (2026-06-05).

Production complaint: large X-ray/radiology batches "get stuck", especially on
slow networks. Root causes pinned here:

  1. O(n²) ``bytes += chunk`` accumulation in the response-body recv loop —
     replaced with ``bytearray.extend`` (amortized linear).
  2. No byte-based batch budget — a count-based batch of huge frames could
     reach hundreds of MB (JSON+base64 peak ≈ 3× payload in RAM). Added a
     per-series soft cap that halves subsequent batches, applied AFTER the
     advance so alignment with the server's batch_index mapping is preserved.
  3. XA / RF / DR missing from the forced single-instance-batch modalities.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from modules.download_manager.network.socket_client import (  # noqa: E402
    _BATCH_BYTES_SOFT_CAP,
    _SERIES_FORCE_BATCH_ONE_MODALITIES,
    _should_force_single_instance_batches,
)

_SRC = (
    _REPO_ROOT / "modules/download_manager/network/socket_client.py"
).read_text(encoding="utf-8")


class _FakeSeries:
    def __init__(self, modality="", series_description=""):
        self.modality = modality
        self.series_description = series_description


# ── 1. linear accumulation ────────────────────────────────────────────────
def test_body_recv_uses_bytearray_extend():
    assert "response_data = bytearray()" in _SRC
    assert "response_data.extend(chunk)" in _SRC
    # the quadratic pattern must not come back
    assert "response_data += chunk" not in _SRC


def test_bytearray_accumulation_is_fast_at_scale():
    # 100 MB in 64 KB chunks: linear time (well under a second).
    chunk = b"x" * 65536
    n = (100 * 1024 * 1024) // len(chunk)
    t0 = time.perf_counter()
    buf = bytearray()
    for _ in range(n):
        buf.extend(chunk)
    elapsed = time.perf_counter() - t0
    assert len(buf) == n * len(chunk)
    assert elapsed < 2.0, f"bytearray accumulation unexpectedly slow: {elapsed:.2f}s"


# ── 2. byte-budget soft cap ───────────────────────────────────────────────
def test_soft_cap_constant_sane():
    assert 16 * 1024 * 1024 <= _BATCH_BYTES_SOFT_CAP <= 256 * 1024 * 1024


def test_soft_cap_halves_after_advance():
    # payload estimate computed where instances are extracted…
    i_est = _SRC.index("_batch_payload_bytes = sum(")
    # …and the halving sits AFTER the loop's batch_start advance
    # (alignment-safe). Exact-indent anchor: the loop-body advance, not the
    # resume-scan's "verified_batch_start += batch_size".
    i_advance = _SRC.index("\n            batch_start += batch_size")
    i_cap = _SRC.index("_batch_payload_bytes > _BATCH_BYTES_SOFT_CAP")
    assert i_est < i_advance < i_cap
    cap_block = _SRC[i_cap:i_cap + 700]
    assert "batch_size = max(min_batch_size, batch_size // 2)" in cap_block
    # per-series only: the cap must NOT write the global adaptive size
    assert "_global_adaptive_batch_size" not in cap_block


# ── 3. forced single-image batches for large-frame radiology ──────────────
def test_xray_family_forces_single_instance_batches():
    for modality in ("XA", "RF", "DR", "DX", "CR", "MG", "PX"):
        assert modality in _SERIES_FORCE_BATCH_ONE_MODALITIES, modality
        assert _should_force_single_instance_batches(_FakeSeries(modality)) is True


def test_ct_mr_never_forced_single():
    for modality in ("CT", "MR", "MRI"):
        assert _should_force_single_instance_batches(_FakeSeries(modality)) is False
    # CT angio description must not trip the keyword path (modality wins)
    assert _should_force_single_instance_batches(
        _FakeSeries("CT", "CTA HEAD ANGIO X-RAY PROTOCOL")
    ) is False
