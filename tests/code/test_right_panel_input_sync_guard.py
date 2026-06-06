"""Guards for the 0x8001010d input-synchronous crash fix (2026-06-06).

Production crash (installed build, D:\\AIPacs logs, 14:18:59 double-click):
the deferred right-panel rebuild ran while the double-click's SendMessage
dispatch was still on the native stack; creating ThumbnailWidget (its
QPropertyAnimation at thumbnail_manager.py:53) fired an outgoing UIA/COM
call, which Windows forbids inside an input-synchronous call → fatal
RPC_E_WRONGTHREAD (0x8001010d) → process death.

Contract pinned here:
  1. `_inside_input_synchronous_dispatch()` exists, fail-open, and returns a
     bool on this platform.
  2. Both thumbnail renderers defer (re-post) instead of building widgets
     when the gate reports input-sync — bounded, generation-safe.
  3. The progressive per-tick builder skips its tick under the gate.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

_SRC = (
    _REPO_ROOT / "PacsClient/pacs/workstation_ui/home_ui/right_panel_widget.py"
).read_text(encoding="utf-8")


def test_helper_is_failopen_bool():
    import importlib

    mod = importlib.import_module(
        "PacsClient.pacs.workstation_ui.home_ui.right_panel_widget"
    )
    val = mod._inside_input_synchronous_dispatch()
    assert isinstance(val, bool)
    # in a pytest process with no pending SendMessage this must be False
    assert val is False


def test_immediate_renderer_defers_under_gate():
    i_fn = _SRC.index("def display_thumbnails_immediately")
    block = _SRC[i_fn:i_fn + 1600]
    i_gate = block.index("_inside_input_synchronous_dispatch()")
    i_repost = block.index("QTimer.singleShot(")
    i_build = block.index("ThumbnailManager")
    assert i_gate < i_repost < i_build  # gate → re-post BEFORE any widget work
    assert "_input_sync_defer_count" in block  # bounded
    # the stale-generation check stays FIRST (re-posts must stay idempotent)
    assert block.index("self._display_generation") < i_gate


def test_progressive_renderer_defers_under_gate():
    i_fn = _SRC.index("def display_thumbnails_progressively")
    block = _SRC[i_fn:i_fn + 1600]
    assert "_inside_input_synchronous_dispatch()" in block
    assert "_input_sync_defer_count" in block
    assert block.index("_inside_input_synchronous_dispatch()") < block.index("ThumbnailManager")


def test_progressive_tick_skips_under_gate():
    i_fn = _SRC.index("def display_next_thumbnail")
    block = _SRC[i_fn:i_fn + 900]
    i_gate = block.index("_inside_input_synchronous_dispatch()")
    # tick-skip happens after the stale-generation cancel, before any build
    assert block.index("_cancel_thumbnail_timer()") < i_gate


def test_helper_uses_insendmessage_and_fails_open():
    i_fn = _SRC.index("def _inside_input_synchronous_dispatch")
    block = _SRC[i_fn:i_fn + 1200]
    assert "InSendMessageEx" in block
    assert "except Exception" in block and "return False" in block
