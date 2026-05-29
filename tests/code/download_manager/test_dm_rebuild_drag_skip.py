"""P2.3 — DM rebuild drag-skip ordering contract tests.

Root cause (2026-05-07):
  _refresh_table_order() called _try_inplace_table_update() BEFORE checking
  is_protected_drag_active().  _try_inplace_table_update() does cellWidget() +
  setValue() Qt calls for every download row.  With the 400 ms
  _fire_deferred_rebuild_after_hidden perpetual timer, this produces Qt widget
  work every ~400 ms during drag, creating a stall pattern perfectly matching
  the observed event_p95_ms ≈ 320–570 ms (handler_p95_ms was only 2–6 ms,
  confirming the stall is inter-event, not in the handler itself).

Fix:
  Move the drag_active check to before _try_inplace_table_update so that
  during active drag NO widget reads or writes occur in _refresh_table_order.

Tests (source-contract layer):
  L1 — drag check appears in source BEFORE _try_inplace_table_update call
  L2 — plugin-package mirror has the same ordering

Tests (behavioral layer):
  L3 — during drag, _try_inplace_table_update is NOT called
  L4 — during drag, a deferred rebuild is scheduled via defer_drag
  L5 — when drag ends, _fire_deferred_rebuild_after_drag triggers a rebuild
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from modules.download_manager.ui.widget import _dm_details


# ── helpers ──────────────────────────────────────────────────────────────────

_CANONICAL = Path(_dm_details.__file__)
_PLUGIN = Path(
    "builder/plugin package/packages/download_manager/payload/python/"
    "modules/download_manager/ui/widget/_dm_details.py"
)


def _method_body(src: str, method: str) -> str:
    m = re.search(
        rf"def {method}\(self.*?\):.*?(?=\n    def |\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert m is not None, f"method {method!r} not found in source"
    return m.group(0)


def _pos(body: str, pattern: str) -> int:
    """Return position of pattern in body, raising AssertionError if absent."""
    idx = body.find(pattern)
    assert idx != -1, f"Pattern not found in method body: {pattern!r}"
    return idx


# ── L1/L2 source-ordering contracts ──────────────────────────────────────────

def _assert_drag_before_inplace(src: str, label: str) -> None:
    body = _method_body(src, "_refresh_table_order")
    pos_drag = _pos(body, "is_protected_drag_active")
    pos_inplace = _pos(body, "self._try_inplace_table_update(")
    assert pos_drag < pos_inplace, (
        f"[{label}] is_protected_drag_active() check (pos {pos_drag}) must appear "
        f"BEFORE _try_inplace_table_update (pos {pos_inplace}) in "
        f"_refresh_table_order.  "
        f"Qt widget writes in _try_inplace_table_update compete with drag "
        f"event processing, causing event_p95_ms ≈ 400 ms stalls (P2.3 fix)."
    )


def _assert_hidden_before_inplace(src: str, label: str) -> None:
    body = _method_body(src, "_refresh_table_order")
    pos_hidden = _pos(body, "if not self.isVisible():")
    pos_inplace = _pos(body, "self._try_inplace_table_update(")
    assert pos_hidden < pos_inplace, (
        f"[{label}] hidden-tab deferral gate (pos {pos_hidden}) must appear "
        f"BEFORE _try_inplace_table_update (pos {pos_inplace}) in "
        f"_refresh_table_order.  "
        f"When hidden, in-place widget updates are pure control-plane cost "
        f"and should be skipped (Phase 2 hidden gating hardening)."
    )


def test_drag_check_before_inplace_update_canonical():
    """L1: canonical _dm_details.py — drag check must precede in-place update."""
    _assert_drag_before_inplace(_CANONICAL.read_text(encoding="utf-8"), "canonical")


def test_drag_check_before_inplace_update_plugin():
    """L2: plugin-package mirror — same ordering invariant."""
    _assert_drag_before_inplace(_PLUGIN.read_text(encoding="utf-8"), "plugin")


def test_hidden_check_before_inplace_update_canonical():
    """L2b: canonical _dm_details.py — hidden gate must precede in-place update."""
    _assert_hidden_before_inplace(_CANONICAL.read_text(encoding="utf-8"), "canonical")


def test_hidden_check_before_inplace_update_plugin():
    """L2c: plugin-package mirror — hidden gate ordering invariant."""
    _assert_hidden_before_inplace(_PLUGIN.read_text(encoding="utf-8"), "plugin")


# ── L3/L4/L5 behavioral contracts via a minimal stub ─────────────────────────
#
# We build the absolute minimum stub for _DMDetailsMixin so the method can run
# without a real Qt application.  The stub:
#   - has a fake download_table that answers rowCount() = 1
#   - has a state_store that returns [] so get_all_downloads is cheap
#   - tracks whether _try_inplace_table_update was called
#   - tracks whether QTimer.singleShot was called (deferred rebuild)


def _make_stub(drag_active: bool, visible: bool = False):
    """Return a minimal stub object for _DMDetailsMixin._refresh_table_order."""

    table = MagicMock()
    table.rowCount.return_value = 1

    stub = SimpleNamespace(
        download_table=table,
        state_store=SimpleNamespace(get_all_downloads=lambda: []),
        _priority_group_widgets={},
        download_rows={},
        _table_structure_key=None,
        _refresh_table_order_in_progress=False,
        _suppressing_selection_signals=False,
        _dm_rebuild_depth=0,
        _rebuild_hidden_pending=False,
        _rebuild_defer_pending=False,
        _inplace_called=False,
        _timers=[],
    )

    # Bind the real method from the mixin so we test production code.
    from modules.download_manager.ui.widget._dm_details import _DMDetailsMixin

    # helpers used inside the method
    stub._compute_table_structure_key = lambda downloads: ()
    stub._dm_rebuild_caller_frame = lambda: "test"
    stub._fire_deferred_rebuild_after_drag = lambda: None
    stub._fire_deferred_rebuild_after_hidden = lambda: None

    original_inplace = _DMDetailsMixin._try_inplace_table_update

    def _tracked_inplace(self, downloads, key):
        self._inplace_called = True
        return False  # always signal "needs full rebuild"

    stub._try_inplace_table_update = lambda d, k: _tracked_inplace(stub, d, k)

    stub.isVisible = lambda: visible

    def _bound_refresh():
        # Patch Qt and drag imports
        timers_fired = stub._timers
        with (
            patch(
                "modules.download_manager.ui.widget._dm_details.QTimer"
            ) as mock_qt,
            patch(
                "modules.viewer.fast.ui_throttle.is_protected_drag_active",
                return_value=drag_active,
            ),
        ):
            mock_qt.singleShot.side_effect = lambda ms, cb: timers_fired.append(
                (ms, cb)
            )
            # Call the real method bound to stub
            _DMDetailsMixin._refresh_table_order(stub)

    return stub, _bound_refresh


def test_inplace_not_called_during_drag():
    """L3: _try_inplace_table_update must NOT be called when drag is active."""
    stub, run = _make_stub(drag_active=True, visible=True)
    run()
    assert not stub._inplace_called, (
        "_try_inplace_table_update was called during drag — this does Qt widget "
        "work and causes event_p95_ms stalls (P2.3 regression)."
    )


def test_deferred_rebuild_scheduled_during_drag():
    """L4: a deferred rebuild must be scheduled when drag is active."""
    stub, run = _make_stub(drag_active=True, visible=True)
    run()
    assert stub._rebuild_defer_pending, (
        "_rebuild_defer_pending should be True after drag-active deferral"
    )
    assert stub._timers, "No QTimer.singleShot was called — deferred rebuild not scheduled"
    delay_ms, _ = stub._timers[0]
    assert delay_ms <= 500, f"Deferred rebuild delay should be ≤500ms, got {delay_ms}ms"


def test_no_deferred_during_drag_when_already_pending():
    """L4b: should not schedule a second timer if defer is already pending."""
    stub, run = _make_stub(drag_active=True, visible=True)
    stub._rebuild_defer_pending = True  # already scheduled
    run()
    assert not stub._timers, "Should not schedule a second timer if one is already pending"


def test_inplace_not_called_when_hidden():
    """L6: when DM is hidden, in-place updates should be skipped and hidden defer used."""
    stub, run = _make_stub(drag_active=False, visible=False)
    run()
    assert not stub._inplace_called, "_try_inplace_table_update should not run when hidden"
    assert stub._rebuild_hidden_pending, "Hidden rebuild deferral should be scheduled"
    assert stub._timers, "Expected deferred hidden rebuild timer"
    delay_ms, _ = stub._timers[0]
    assert delay_ms <= 500, f"Hidden deferred rebuild delay should be <=500ms, got {delay_ms}ms"


# ── Fix B: details-panel drag gate ──────────────────────────────────────────
# Root cause 2 (pid=8420, 09:31:36, gap=432ms):
#   _fire_coalesced_rebuild → _refresh_table_order → _select_study_row →
#   _update_details_panel → _update_series_breakdown_from_task →
#   counts_label.setStyleSheet(...)
#
# _update_series_breakdown_from_task deletes all existing series widgets then
# recreates QFrame/QVBoxLayout/QHBoxLayout/QProgressBar + 2 QLabels per series
# with setStyleSheet() calls.  This fires on every full rebuild (~100 ms timer).
# Fix B: skip _update_series_breakdown_from_task while drag is active.

_DETAILS_CANONICAL = Path(_dm_details.__file__)
_DETAILS_PLUGIN = Path(
    "builder/plugin package/packages/download_manager/payload/python/"
    "modules/download_manager/ui/widget/_dm_details.py"
)


def _details_src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_update_details_drag_gate_source_order_canonical():
    """B1-canonical: _update_details_panel must check drag before series breakdown call.

    _update_series_breakdown_from_task does heavy Qt widget recreation on every
    call.  The drag check must appear BEFORE the _update_series_breakdown_from_task
    call inside _update_details_panel so widget rebuilds are suppressed during drag.
    """
    src = _details_src(_DETAILS_CANONICAL)
    body = _method_body(src, "_update_details_panel")
    # Both tokens must appear inside the method body
    assert "is_protected_drag_active" in body, (
        "[canonical] _update_details_panel does not call is_protected_drag_active(). "
        "Fix B requires checking is_protected_drag_active() before the "
        "_update_series_breakdown_from_task call to skip heavy Qt widget work during drag."
    )
    assert "self._update_series_breakdown_from_task" in body, (
        "[canonical] self._update_series_breakdown_from_task call not found inside "
        "_update_details_panel — check method body regex."
    )
    pos_drag = body.find("is_protected_drag_active")
    pos_breakdown = body.find("self._update_series_breakdown_from_task")
    assert pos_drag < pos_breakdown, (
        f"[canonical] is_protected_drag_active() (pos={pos_drag}) must appear "
        f"BEFORE self._update_series_breakdown_from_task (pos={pos_breakdown}) in "
        f"_update_details_panel. The drag gate comes first, widget rebuild second."
    )


def test_update_details_drag_gate_source_order_plugin():
    """B1-plugin: plugin mirror must have the same ordering."""
    if not _DETAILS_PLUGIN.exists():
        pytest.skip("plugin copy not present")
    src = _details_src(_DETAILS_PLUGIN)
    body = _method_body(src, "_update_details_panel")
    assert "is_protected_drag_active" in body, (
        "[plugin] _update_details_panel is missing is_protected_drag_active() check."
    )
    pos_drag = body.find("is_protected_drag_active")
    pos_breakdown = body.find("self._update_series_breakdown_from_task")
    assert pos_drag < pos_breakdown, (
        "[plugin] drag gate must appear before self._update_series_breakdown_from_task."
    )


# ── Fix E: _fire_deferred_rebuild_after_drag 1500ms backoff ──────────────────
# Root cause (pid=39504): _fire_deferred_rebuild_after_drag clears
# _rebuild_defer_pending and immediately re-enters _refresh_table_order().
# If drag is still active, _refresh_table_order() schedules ANOTHER 250 ms
# timer, creating a 4 Hz self-perpetuating storm during drag (190 firings
# per 79-second window observed in logs).  Fix: check drag state BEFORE
# clearing the flag; if still active, re-arm at 1500 ms (keepalive period)
# without touching the flag.


def _fire_deferred_rebuild_source_body(path: Path) -> str:
    src = path.read_text(encoding="utf-8")
    return _method_body(src, "_fire_deferred_rebuild_after_drag")


def test_fire_deferred_rebuild_has_drag_backoff_canonical():
    """E1-canonical: _fire_deferred_rebuild_after_drag must check drag before clearing flag."""
    body = _fire_deferred_rebuild_source_body(_CANONICAL)
    assert "is_protected_drag_active" in body, (
        "[canonical] _fire_deferred_rebuild_after_drag does not call "
        "is_protected_drag_active(). Fix-E requires checking drag state to "
        "prevent the 4 Hz 250-ms self-perpetuating rebuild storm during drag."
    )
    # The backoff timer must exist (singleShot inside the method)
    assert "singleShot" in body, (
        "[canonical] _fire_deferred_rebuild_after_drag has no QTimer.singleShot — "
        "the 1500 ms backoff timer is missing."
    )
    # _rebuild_defer_pending = False must come AFTER the drag check
    pos_drag = body.find("is_protected_drag_active")
    pos_clear = body.find("_rebuild_defer_pending = False")
    assert pos_clear > pos_drag, (
        f"[canonical] _rebuild_defer_pending = False (pos={pos_clear}) must appear "
        f"AFTER is_protected_drag_active() check (pos={pos_drag}). During drag, "
        f"the flag must remain True so concurrent callers don't stack more timers."
    )


def test_fire_deferred_rebuild_has_drag_backoff_plugin():
    """E1-plugin: plugin mirror must have the same backoff logic."""
    body = _fire_deferred_rebuild_source_body(_PLUGIN)
    assert "is_protected_drag_active" in body, (
        "[plugin] _fire_deferred_rebuild_after_drag is missing is_protected_drag_active() check."
    )
    pos_drag = body.find("is_protected_drag_active")
    pos_clear = body.find("_rebuild_defer_pending = False")
    assert pos_clear > pos_drag, (
        "[plugin] _rebuild_defer_pending = False must appear after drag check."
    )


def test_fire_deferred_rebuild_backoff_interval_is_1500ms_canonical():
    """E2-canonical: the backoff interval must be >= 1000ms (matches drag keepalive)."""
    body = _fire_deferred_rebuild_source_body(_CANONICAL)
    # Extract all singleShot(...) intervals
    intervals = [int(m.group(1)) for m in re.finditer(r"singleShot\((\d+)", body)]
    assert any(ms >= 1000 for ms in intervals), (
        f"[canonical] No QTimer.singleShot interval >= 1000 ms found in "
        f"_fire_deferred_rebuild_after_drag (found: {intervals}). "
        f"The backoff must be at least 1000 ms to cover the drag keepalive window "
        f"and prevent the 4 Hz polling storm."
    )


def test_fire_deferred_rebuild_backoff_interval_is_1500ms_plugin():
    """E2-plugin: plugin mirror has the same >= 1000ms backoff."""
    body = _fire_deferred_rebuild_source_body(_PLUGIN)
    intervals = [int(m.group(1)) for m in re.finditer(r"singleShot\((\d+)", body)]
    assert any(ms >= 1000 for ms in intervals), (
        f"[plugin] No singleShot interval >= 1000 ms in _fire_deferred_rebuild_after_drag "
        f"(found: {intervals})."
    )


# ── Fix F: hidden-tab deferred rebuild backoff ──────────────────────────────


def test_fire_deferred_hidden_has_visibility_backoff_canonical():
    """F1-canonical: hidden callback must check visibility before clearing pending."""
    src = _CANONICAL.read_text(encoding="utf-8")
    body = _method_body(src, "_fire_deferred_rebuild_after_hidden")
    assert "if not self.isVisible()" in body, (
        "[canonical] _fire_deferred_rebuild_after_hidden is missing hidden-state "
        "check. Fix-F requires backoff while DM stays hidden."
    )
    pos_hidden = body.find("if not self.isVisible()")
    pos_clear = body.find("_rebuild_hidden_pending = False")
    assert pos_clear > pos_hidden, (
        "[canonical] _rebuild_hidden_pending must be cleared only after visibility "
        "check passes (visible state)."
    )
    intervals = [int(m.group(1)) for m in re.finditer(r"singleShot\((\d+)", body)]
    assert any(ms >= 1000 for ms in intervals), (
        f"[canonical] No hidden-callback backoff interval >= 1000 ms found "
        f"(found: {intervals})."
    )


def test_fire_deferred_hidden_has_visibility_backoff_plugin():
    """F1-plugin: plugin mirror must keep the same hidden backoff policy."""
    src = _PLUGIN.read_text(encoding="utf-8")
    body = _method_body(src, "_fire_deferred_rebuild_after_hidden")
    assert "if not self.isVisible()" in body, (
        "[plugin] _fire_deferred_rebuild_after_hidden missing hidden-state check."
    )
    pos_hidden = body.find("if not self.isVisible()")
    pos_clear = body.find("_rebuild_hidden_pending = False")
    assert pos_clear > pos_hidden, (
        "[plugin] _rebuild_hidden_pending clear must come after visibility check."
    )
    intervals = [int(m.group(1)) for m in re.finditer(r"singleShot\((\d+)", body)]
    assert any(ms >= 1000 for ms in intervals), (
        f"[plugin] No hidden-callback backoff interval >= 1000 ms found "
        f"(found: {intervals})."
    )

