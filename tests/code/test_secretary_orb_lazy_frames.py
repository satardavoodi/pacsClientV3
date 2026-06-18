"""Guards for the lazy Secretary-orb frame build (2026-06-18 perceived-latency work).

The orb pre-renders 72 active + 48 error animation frames. Building them
synchronously on the first home-page paint blocked the GUI thread ~3.5 s every
launch. Under ``AIPACS_ORB_LAZY_FRAMES`` (default on) only the inactive + first
active/error frame are built up front and the rest stream in via the chunked
``_build_more_frames`` idle builder. The orb is inactive at startup, so the
active/error frames aren't needed yet. These tests pin:
  - lazy: first paint builds a tiny set, then the builder fills to 72/48;
  - legacy (flag off): byte-for-byte the original synchronous build (72/48);
  - consumers use ``len(_active_frames)`` so a growing list stays in range.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


@pytest.fixture(scope="module")
def _app():
    try:
        from PySide6.QtWidgets import QApplication
    except Exception as exc:  # pragma: no cover - minimal env
        pytest.skip(f"PySide6 unavailable: {exc}")
    app = QApplication.instance() or QApplication([])
    yield app


def _make(app):
    try:
        from PacsClient.pacs.workstation_ui.home_ui import secretary_button_widget as sbw
    except Exception as exc:  # heavy EchoMind deps absent in minimal shards
        pytest.skip(f"secretary_button_widget import unavailable: {exc}")
    w = sbw.SecretaryOrbButton()
    w.resize(248, 248)
    return sbw, w


def test_lazy_first_paint_is_small_then_streams_to_full(_app, monkeypatch):
    sbw, w = _make(_app)
    monkeypatch.setattr(sbw, "_ORB_LAZY_FRAMES", True)
    w._cached_side = -1
    w._rebuild_frames()

    # First paint built only the inactive + first active + first error frame.
    assert not w._inactive_frame.isNull()
    assert len(w._active_frames) == 1
    assert len(w._error_frames) == 1

    # Pump the chunked idle builder to completion.
    for _ in range(500):
        if (w._lazy_active_done >= w._ACTIVE_FRAME_COUNT
                and w._lazy_error_done >= w._ERROR_FRAME_COUNT):
            break
        w._build_more_frames()

    assert w._ACTIVE_FRAME_COUNT == 72 and w._ERROR_FRAME_COUNT == 48
    assert len(w._active_frames) == 72
    assert len(w._error_frames) == 48
    assert all(not f.isNull() for f in w._active_frames)


def test_legacy_flag_off_builds_all_synchronously(_app, monkeypatch):
    sbw, w = _make(_app)
    monkeypatch.setattr(sbw, "_ORB_LAZY_FRAMES", False)
    w._cached_side = -1
    w._rebuild_frames()
    # Byte-identical to the original behavior: everything built up front.
    assert len(w._active_frames) == 72
    assert len(w._error_frames) == 48


def test_frame_index_stays_in_range_while_list_grows(_app, monkeypatch):
    # paintEvent/_advance_frame index into _active_frames; a growing list must
    # never let _frame_index fall out of range.
    sbw, w = _make(_app)
    monkeypatch.setattr(sbw, "_ORB_LAZY_FRAMES", True)
    w._cached_side = -1
    w._rebuild_frames()
    w._active = True
    for _ in range(30):
        w._advance_frame()  # uses % len(_active_frames)
        assert 0 <= w._frame_index < len(w._active_frames)
        w._build_more_frames()
