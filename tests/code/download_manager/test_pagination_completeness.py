"""Guards for the batch-pagination completeness fix (2026-06-19, data loss).

Live finding: Normal batch>1 mode silently dropped the TAIL of a series — patient
47221 series 202 wrote 40/52 files to disk (missing the contiguous instances 41-52)
at batch=10, reproducibly, while batch=1 wrote 52/52. The viewer still showed "52/52".

Root cause: the server pages by ``batch_index = batch_start // batch_size``
(``download_batch``), which only tiles a series correctly when ``batch_size`` stays
CONSTANT. Adaptive mid-series GROWTH changes ``batch_size`` while ``batch_start``
advances additively, so ``batch_index`` can repeat / stick at 0 — re-fetching the
series head (duplicates) and never requesting the tail.

Fix (flag-gated, default on):
  1. ``_PAGINATION_SAFE`` (AIPACS_DOWNLOAD_PAGINATION_SAFE) disables mid-series batch
     GROWTH so the index tiling stays exact. The first-image prime (size 1 → full) and
     the byte-cap halve are alignment-safe and remain.
  2. A post-download completeness guard compares the on-disk unique count against the
     server's expected_count, fills any gap with correctly-tiled batch requests
     (batch_index k at a constant size), and logs ``[SERIES_COMPLETE]`` /
     ``[INCOMPLETE_SERIES]`` — so a series can never silently report N/N with fewer
     files.
  3. A ``[BATCH_TRACE]`` WARNING per batch makes the batch_index sequence observable.

These tests pin the wiring (a refactor can't silently drop it) + plugin-mirror parity.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SRC_PATH = _REPO_ROOT / "modules/download_manager/network/socket_client.py"
_SRC = _SRC_PATH.read_text(encoding="utf-8")


# ---- flags -----------------------------------------------------------------

def test_pagination_safe_flag_default_on_with_kill_switch():
    assert 'AIPACS_DOWNLOAD_PAGINATION_SAFE", "1"' in _SRC  # default on
    assert "_PAGINATION_SAFE = " in _SRC


def test_batch_trace_flag_default_on_with_kill_switch():
    assert 'AIPACS_DOWNLOAD_BATCH_TRACE", "1"' in _SRC
    assert "_BATCH_TRACE = " in _SRC


# ---- core fix: growth disabled while paging-safe ---------------------------

def test_growth_gate_requires_pagination_unsafe():
    # The adaptive-growth branch must be guarded by `and not _PAGINATION_SAFE`, so
    # batch_size stays constant within a series and batch_index = batch_start//size
    # tiles the series exactly. Pin the two conditions appearing consecutively in the
    # growth `elif` (immune to leading-whitespace changes).
    assert "and not _PAGINATION_SAFE" in _SRC
    assert re.search(r"self\._batch_growth_enabled\s+and not _PAGINATION_SAFE", _SRC), \
        "growth branch not gated by pagination-safe"


def test_server_still_pages_by_batch_index_over_size():
    # The mechanism we are protecting against: batch_index reconstructed from
    # batch_start // batch_size. If this disappears the fix rationale changed.
    assert "batch_index = batch_start // batch_size" in _SRC


# ---- completeness guard + gap fill -----------------------------------------

def test_completeness_guard_present():
    assert "[INCOMPLETE_SERIES]" in _SRC
    assert "[SERIES_COMPLETE]" in _SRC
    # compares on-disk scan against expected_count
    assert "_scan_existing_files(output_dir)" in _SRC
    assert "< expected_count" in _SRC


def test_gap_fill_uses_constant_tiling():
    # The gap-fill must request batch_index k at a CONSTANT fill size (start = k*size),
    # which is the only correct tiling for an index-paged server.
    assert "_fill_size" in _SRC
    assert "_bi * _fill_size" in _SRC
    # gap-fill reuses the atomic write (.part -> os.replace) and dedups on existing files
    assert "os.replace(_tmp, _fp)" in _SRC


def test_gap_fill_respects_force_single():
    # Poor-mode / force-single series must fill at size 1 (never re-batch them).
    assert "1 if _force_single else" in _SRC


# ---- per-batch trace -------------------------------------------------------

def test_batch_trace_logged_with_index_and_has_more():
    assert "[BATCH_TRACE]" in _SRC
    # the trace (a multi-line format string) must expose the index, size and has_more
    # so a stuck/repeating index is visible at runtime
    window = _SRC[_SRC.index("[BATCH_TRACE]"):][:500]
    assert "batch_index=" in window
    assert "has_more=" in window


# ---- plugin-mirror parity --------------------------------------------------

def test_plugin_mirror_carries_the_fix():
    mir = (
        _REPO_ROOT
        / "builder/plugin package/packages/download_manager/payload/python"
        / "modules/download_manager/network/socket_client.py"
    )
    if not mir.exists():
        pytest.skip("download_manager plugin mirror not present")
    t = mir.read_text(encoding="utf-8")
    assert "and not _PAGINATION_SAFE" in t
    assert "[INCOMPLETE_SERIES]" in t
    assert "[BATCH_TRACE]" in t
