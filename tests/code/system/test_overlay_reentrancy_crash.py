"""Guard the 2026-08-26 overlay re-entrancy crash (pid 217556, 13:40:25).

WHAT CRASHED
------------
`Windows fatal exception: access violation`, caught by the faulthandler in
`user_data/logs/native_fault.log`. Stack, bottom-up:

    main.notify -> _ui_apply -> _apply_loaded_series_data
      -> switch_series -> show_loading -> show_overlay
        -> QApplication.processEvents()        <-- RE-ENTERS the event loop
          -> main.notify -> _finish_on_ui
            -> _perform_series_switch_optimized -> switch_series
              -> show_loading -> show_overlay -> __init__  <-- QProgressBar(self), dies

`AiPacsLoadingOverlay.show_overlay` called `QApplication.processEvents()` TWICE
to "force the event loop to paint the overlay immediately". processEvents does
far more than paint: it dispatches QUEUED work, so a viewer-controller command
started a SECOND series switch on top of the first, and the nested overlay was
built against a viewport the outer switch was already tearing down.

app.log corroborates it: three `[VIEWER_SWITCH] switch_start` for series 7 inside
one second, and only ONE `phase_summary`. No `[SHUTDOWN-INITIATOR]` - the process
did not close, it died.

PRIOR ART, and why this guard is shaped as it is: the SAME race crashed the app on
2026-06-05 at the FADE site, and the fix there added a `shiboken6.isValid` liveness
check inside `hide_overlay._start_fade` (see `test_loading_overlay_liveness_guard.py`).
That treated one call site. The cause - re-entering the event loop mid-switch - was
never addressed, so the race simply moved to CONSTRUCTION.

THE THREE FIXES
---------------
A. `show_overlay` paints with `repaint()` (synchronous, no event-loop re-entry)
   instead of `processEvents()`.            AIPACS_OVERLAY_SYNC_PAINT=0
B. `switch_series` refuses a nested call.   AIPACS_SWITCH_REENTRANCY_GUARD=0
C. `AiPacsLoadingOverlay.__init__` refuses a destroyed anchor.
                                            AIPACS_OVERLAY_ANCHOR_GUARD=0

A is the cause. B and C are defence in depth: `processEvents()` is called from
many other places, so any of them reached during a switch could nest again.

Source pins are AST-bounded (never a character window), matching
`test_loading_overlay_liveness_guard.py`.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
OVERLAY = REPO / "PacsClient" / "components" / "loading_overlay.py"
CONTAINER = (REPO / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
             / "vtk_widget" / "qt_fast_container.py")


def _func_src(path: Path, name: str, cls: str | None = None) -> str:
    """Source of a function, optionally scoped to a class.

    The class scope is NOT optional in practice: `loading_overlay.py` defines
    three `__init__`s, and a bare ast.walk() returns `_LogoSpinner.__init__`
    first - a guard bound to the wrong one silently guards nothing.
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    scope: ast.AST = tree
    if cls is not None:
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == cls:
                scope = node
                break
        else:
            return ""
    for node in ast.walk(scope):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def _code_only(body: str) -> str:
    """Drop comment lines so prose quoting the old API cannot satisfy a guard."""
    return "\n".join(l for l in body.splitlines() if not l.strip().startswith("#"))


# ───────────────────────────────── A: the cause ──────────────────────────────

def test_show_overlay_does_not_unconditionally_reenter_the_event_loop():
    """The bug itself. FAILS pre-fix."""
    body = _code_only(_func_src(OVERLAY, "show_overlay"))
    assert body, "loading_overlay must define show_overlay"
    assert "overlay.repaint()" in body, (
        "show_overlay must paint synchronously with repaint(), not by re-entering "
        "the event loop"
    )
    assert "_overlay_sync_paint_enabled()" in body, (
        "the synchronous paint must be behind its kill switch"
    )


def test_processevents_survives_only_behind_the_kill_switch():
    """processEvents may remain ONLY as the disabled-by-default fallback."""
    body = _code_only(_func_src(OVERLAY, "show_overlay"))
    if "processEvents" not in body:
        return  # removed entirely - also acceptable
    i_guard = body.index("_overlay_sync_paint_enabled()")
    i_pe = body.index("processEvents")
    assert i_guard < i_pe, (
        "every processEvents() in show_overlay must sit inside the kill-switch "
        "else-branch, never on the default path"
    )


def test_sync_paint_kill_switch_defaults_on():
    body = _code_only(_func_src(OVERLAY, "_overlay_sync_paint_enabled"))
    assert 'os.getenv("AIPACS_OVERLAY_SYNC_PAINT", "1")' in body
    assert '!= "0"' in body


# ─────────────────────────── C: the dead-anchor guard ────────────────────────

def test_overlay_init_refuses_a_destroyed_anchor():
    """FAILS pre-fix. The crash site was __init__, which touched a dead anchor."""
    body = _code_only(_func_src(OVERLAY, "__init__", cls="AiPacsLoadingOverlay"))
    assert "_widget_is_alive(anchor)" in body, (
        "__init__ must verify the anchor before touching it"
    )
    assert "_overlay_anchor_guard_enabled()" in body


def test_anchor_guard_runs_before_anything_touches_the_anchor():
    """Ordering is the whole point - a check after super().__init__ is useless."""
    body = _code_only(_func_src(OVERLAY, "__init__", cls="AiPacsLoadingOverlay"))
    i_guard = body.index("_widget_is_alive(anchor)")
    for later in ("_anchor_has_native_render_window(anchor)",
                  "super().__init__(anchor)",
                  "anchor.installEventFilter"):
        assert i_guard < body.index(later), (
            f"the liveness check must precede {later}"
        )


def test_widget_is_alive_is_conservative_without_shiboken(monkeypatch):
    """Behavioural. A missing shiboken6 must NOT be read as 'widget is dead'."""
    sys.path.insert(0, str(REPO))
    from PacsClient.components import loading_overlay as lo

    assert lo._widget_is_alive(None) is False

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def _no_shiboken(name, *a, **kw):
        if name == "shiboken6":
            raise ImportError("simulated")
        return real_import(name, *a, **kw)

    monkeypatch.setattr("builtins.__import__", _no_shiboken)
    assert lo._widget_is_alive(object()) is True, (
        "without shiboken6 the fallback must be 'alive' (old behaviour), never 'dead'"
    )


def test_widget_is_alive_follows_shiboken(monkeypatch):
    sys.path.insert(0, str(REPO))
    from PacsClient.components import loading_overlay as lo
    import shiboken6

    monkeypatch.setattr(shiboken6, "isValid", lambda w: False)
    assert lo._widget_is_alive(object()) is False
    monkeypatch.setattr(shiboken6, "isValid", lambda w: True)
    assert lo._widget_is_alive(object()) is True


# ────────────────────── B: the switch re-entrancy guard ──────────────────────

def test_switch_series_has_a_reentrancy_guard():
    body = _code_only(_func_src(CONTAINER, "switch_series"))
    assert body, "qt_fast_container must define switch_series"
    assert "_in_switch_series" in body
    assert 'AIPACS_SWITCH_REENTRANCY_GUARD' in body


def test_the_reentrancy_flag_is_cleared_in_a_finally():
    """A stuck flag would turn a crash into a permanently dead viewport."""
    src = CONTAINER.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "switch_series")
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
    assert tries, "switch_series must clear its flag in a finally block"
    cleared = any(
        "self._in_switch_series = False" in (ast.get_source_segment(src, stmt) or "")
        for t in tries for stmt in t.finalbody
    )
    assert cleared, "the finally block must set _in_switch_series = False"


def _stub_container():
    """A QtFastContainer with only what switch_series touches - no Qt widgets."""
    sys.path.insert(0, str(REPO))
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import (
        QtFastContainer,
    )
    # Bind the REAL method to a plain object. QtFastContainer is a QWidget
    # subclass, so object.__new__ is refused and a real instance would need a
    # QApplication and a live viewport - neither of which this guard is about.
    class _Stub:
        pass

    c = _Stub()
    c.switch_series = QtFastContainer.switch_series.__get__(c, _Stub)
    c._qt_bridge = type("B", (), {"metadata": {}})()
    c.viewport_spinner = None
    c.last_series_show = None
    c.get_count_of_slices = lambda: 0
    c.refresh_viewport_borders = lambda: None
    # the success path arms QTimer.singleShot(180, self._safe_hide_spinner)
    c._safe_hide_spinner = lambda: None
    return c


def _md(series_number="7"):
    return {"series": {"series_number": series_number, "series_path": "/x/7"},
            "instances": []}


def test_a_nested_switch_is_refused(monkeypatch):
    """BEHAVIOURAL - this is the crash, reproduced without Qt.

    The inner call is made from inside _start_qt_viewer, exactly as
    processEvents() used to dispatch one from inside show_overlay.
    """
    c = _stub_container()
    seen = {"inner": None, "flag_during": None}

    def _start(metadata, fixed):
        seen["flag_during"] = getattr(c, "_in_switch_series", False)
        seen["inner"] = c.switch_series(None, _md(), 0)

    c._start_qt_viewer = _start
    outer = c.switch_series(None, _md(), 0)

    assert seen["flag_during"] is True, "the flag must be set while a switch runs"
    assert seen["inner"] is False, "the NESTED switch must be refused"
    assert outer is True, "the OUTER switch must still complete normally"
    assert c._in_switch_series is False, "the flag must be cleared on exit"


def test_the_flag_clears_when_the_switch_raises():
    c = _stub_container()

    def _boom(metadata, fixed):
        raise RuntimeError("simulated viewer failure")

    c._start_qt_viewer = _boom
    assert c.switch_series(None, _md(), 0) is False
    assert c._in_switch_series is False, (
        "a failed switch must not leave the viewport permanently refusing switches"
    )
    # and a later switch still works
    c._start_qt_viewer = lambda metadata, fixed: None
    assert c.switch_series(None, _md(), 0) is True


def test_the_guard_can_be_disabled(monkeypatch):
    monkeypatch.setenv("AIPACS_SWITCH_REENTRANCY_GUARD", "0")
    c = _stub_container()
    depth = {"n": 0}

    def _start(metadata, fixed):
        depth["n"] += 1
        if depth["n"] < 2:
            c.switch_series(None, _md(), 0)

    c._start_qt_viewer = _start
    c.switch_series(None, _md(), 0)
    assert depth["n"] == 2, "with the kill switch off the nested call must proceed"


# ───────────────────────────── prior art must survive ────────────────────────

def test_the_2026_06_05_fade_liveness_guard_is_still_there():
    """This fix must not regress the earlier one at the fade site."""
    src = OVERLAY.read_text(encoding="utf-8")
    assert "shiboken6.isValid" in src
    assert "_start_fade" in src
