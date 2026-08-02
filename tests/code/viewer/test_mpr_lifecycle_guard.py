"""MPR/VTK lifecycle guards (2026-08-01).

Covers the three defects found by the lifecycle audit:

1. **Re-entrancy** — `toggle_zeta_mpr` had NO guard, so a second activation while an
   open was in flight built a SECOND full pipeline (second volume, second worker set,
   second render window) on top of the first. The modal progress dialogs block *mouse*
   input during their own phases, but they pump the event loop and the open is also
   reachable programmatically (EchoMind command bus / agent control).

2. **Post-close stale callbacks** — the deferred render + throttled interaction
   callbacks were guarded only by `view_name in self.viewers`, which starts protecting
   only after `viewers.clear()` at the very END of teardown. During teardown a queued
   callback still found live entries but a render window whose graphics resources were
   already released — a native use-after-free no Python try/except can catch.

3. **Teardown completeness** — OPT-47 released the GPU + the volume but left the actor
   dicts, pane containers, the widget->view map, the toolbar styles, the cross-module
   activate callback and the interaction timer alive, so repeated open/close grew host
   memory and kept the patient tab reachable from a "closed" viewer.

These tests are source-pinned where the real object needs VTK/Qt (the ordering and
wiring facts), and behavioural for the pure state machine.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
LAYOUT = REPO / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_layout.py"
ORIENT = REPO / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_orientation.py"
WIDGET = REPO / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "widget.py"
TOOLBAR = (
    REPO
    / "PacsClient"
    / "pacs"
    / "patient_tab"
    / "ui"
    / "patient_ui"
    / "patient_toolbar"
    / "toolbar_manager.py"
)


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _func_source(path: Path, name: str) -> str:
    """Return the source of a top-level-or-method function by name."""
    tree = ast.parse(_src(path))
    lines = _src(path).splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} not found in {path.name}")


# ---------------------------------------------------------------------------
# 1. Re-entrancy guard on toggle_zeta_mpr
# ---------------------------------------------------------------------------


def test_toggle_zeta_mpr_has_a_reentrancy_guard():
    """A second open while one is in flight must be refused, not run."""
    src = _func_source(TOOLBAR, "toggle_zeta_mpr")
    assert "_mpr_open_in_progress" in src, "no re-entrancy flag on the MPR open path"
    # The guard must RETURN, not merely log.
    guard = re.search(
        r"if\s+_guard_on\s+and\s+getattr\(\s*self,\s*[\"']_mpr_open_in_progress[\"']"
        r".*?\n(?:.*\n)*?\s*return\b",
        src,
    )
    assert guard, "the re-entrancy check does not return early"


def test_reentrancy_guard_is_released_in_a_finally():
    """A stuck flag would kill the MPR button for the session — worse than the duplicate."""
    src = _func_source(TOOLBAR, "toggle_zeta_mpr")
    assert re.search(
        r"finally:\s*\n(?:\s*#.*\n)*\s*if\s+_guard_on:\s*\n\s*self\._mpr_open_in_progress\s*=\s*False",
        src,
    ), "the guard is not cleared in a finally"


def test_reentrancy_guard_does_not_block_closing():
    """Toggle-OFF must always work, even if the flag were somehow stuck."""
    src = _func_source(TOOLBAR, "toggle_zeta_mpr")
    close_idx = src.index("MPR CLOSE")
    guard_idx = src.index("_mpr_open_in_progress")
    assert close_idx < guard_idx, (
        "the re-entrancy guard is placed before the close branch — a stuck flag "
        "would make MPR impossible to close"
    )


def test_reentrancy_guard_has_a_kill_switch():
    src = _func_source(TOOLBAR, "toggle_zeta_mpr")
    assert "AIPACS_MPR_LIFECYCLE_GUARD" in src
    assert '"AIPACS_MPR_LIFECYCLE_GUARD", "1"' in src, "the guard must default ON"


# ---------------------------------------------------------------------------
# 2. Post-close no-op guard
# ---------------------------------------------------------------------------


def test_mpr_is_closed_helper_exists_and_defaults_false():
    """`_mpr_is_closed` must be tolerant of an object that never set the flag."""
    src = _func_source(ORIENT, "_mpr_is_closed")
    assert 'getattr(self, "_mpr_closed", False)' in src, (
        "the helper must default to False so a partially-constructed viewer is not "
        "treated as closed"
    )
    # Behavioural check on the pure logic.
    ns: dict = {}
    exec(compile(src.strip(), "<_mpr_is_closed>", "exec"), ns)
    fn = ns["_mpr_is_closed"]

    class _Bare:
        pass

    assert fn(_Bare()) is False

    class _Open:
        _mpr_closed = False

    assert fn(_Open()) is False

    class _Closed:
        _mpr_closed = True

    assert fn(_Closed()) is True


@pytest.mark.parametrize(
    "fname",
    [
        "_request_render",
        "_execute_pending_renders",
        "_render_immediately",
        "_apply_interaction_update",
        "_request_interaction_update",
    ],
)
def test_every_deferred_entry_point_bails_when_closed(fname):
    """Each queued/deferred MPR operation must no-op once cleanup() has begun."""
    src = _func_source(ORIENT, fname)
    assert re.search(r"if\s+self\._mpr_is_closed\(\):\s*\n\s*return", src), (
        f"{fname} does not bail when the viewer is closed — a callback queued before "
        f"cleanup() can still reach VTK during teardown"
    )


def test_the_closed_check_is_the_first_statement_of_each_entry_point():
    """Bailing AFTER touching state defeats the purpose."""
    for fname in ("_request_render", "_execute_pending_renders", "_render_immediately"):
        src = _func_source(ORIENT, fname)
        body = [
            ln.strip()
            for ln in src.splitlines()[1:]
            if ln.strip() and not ln.strip().startswith(("#", '"""', "'''"))
        ]
        # skip a docstring line that closes on its own line
        body = [ln for ln in body if not ln.endswith('"""') or ln.count('"""') == 2]
        assert body[0].startswith("if self._mpr_is_closed()"), (
            f"{fname}: the closed-check is not the first executable statement "
            f"(found {body[0]!r})"
        )


def test_closed_viewer_does_no_interaction_work_at_all():
    """Behavioural: exec the REAL `_apply_interaction_update` against a recorder.
    Closed => zero calls; open => the normal call set. This is the test that would
    catch someone 'simplifying' the guard away."""
    import logging

    src = _src(ORIENT)
    start = src.index("def _apply_interaction_update")
    end = src.index("\n    def ", start + 1)
    block = "    " + src[start:end].rstrip() + "\n"
    ns = {"logger": logging.getLogger("test")}
    exec(compile("class _H:\n" + block, "<apply>", "exec"), ns)  # noqa: S102
    holder = ns["_H"]

    class _Rec:
        def __init__(self, closed):
            self.closed = closed
            self.calls = []

        def _mpr_is_closed(self):
            return self.closed

        def _update_all_crosshairs(self):
            self.calls.append("crosshairs")

        def _update_slice_positions(self):
            self.calls.append("slice_positions")

        def _synchronize_oblique_views(self):
            self.calls.append("oblique")

        def _update_slice_info_texts(self):
            self.calls.append("text")

        def _mpr_perf_note(self, op, ms):
            self.calls.append("perf")

    closed = _Rec(True)
    holder._apply_interaction_update(closed, "move")
    assert closed.calls == [], (
        f"a CLOSED viewer still did interaction work: {closed.calls} — this is the "
        f"stale-callback / use-after-free path"
    )

    live = _Rec(False)
    holder._apply_interaction_update(live, "move")
    assert "crosshairs" in live.calls and "slice_positions" in live.calls, (
        "the guard broke the normal (open) interaction path"
    )


def test_widget_initializes_the_flag_to_false():
    src = _src(WIDGET)
    assert re.search(r"self\._mpr_closed\s*=\s*False", src), (
        "_mpr_closed must be initialized in __init__ so a live viewer is never "
        "mistaken for a closed one"
    )


# ---------------------------------------------------------------------------
# 3. Teardown completeness + ordering
# ---------------------------------------------------------------------------


def test_cleanup_sets_closed_flag_first():
    """STEP 1 of the contract: stop accepting new operations BEFORE releasing anything."""
    src = _func_source(LAYOUT, "cleanup")
    body = [ln.strip() for ln in src.splitlines()[1:] if ln.strip()]
    executable = [
        ln
        for ln in body
        if not ln.startswith("#") and not ln.startswith('"""') and not ln.startswith("'''")
    ]
    assert executable[0] == "self._mpr_closed = True", (
        f"cleanup() must set _mpr_closed first (found {executable[0]!r}); otherwise a "
        f"callback can fire between the first VTK release and the flag"
    )


def test_closed_flag_is_set_before_any_vtk_release():
    src = _func_source(LAYOUT, "cleanup")
    flag = src.index("self._mpr_closed = True")
    for marker in ("ReleaseGraphicsResources", "Finalize()", "RemoveAllViewProps", "SetInputData(None)"):
        assert flag < src.index(marker), f"_mpr_closed is set after {marker}"


@pytest.mark.parametrize(
    "attr",
    [
        "text_actors",
        "crosshair_actors",
        "_view_containers",
        "_vtk_widget_to_view",
        "_toolbar_styles",
        "_render_pending",
    ],
)
def test_cleanup_clears_the_containers_that_used_to_leak(attr):
    """Each of these was assigned once and never cleared → memory growth across
    repeated open/close, because a Qt widget keeps its whole parent chain alive."""
    src = _func_source(LAYOUT, "cleanup")
    assert f'"{attr}"' in src, f"cleanup() does not clear {attr}"


@pytest.mark.parametrize("attr", ["_viewport_activate_cb", "_diag"])
def test_cleanup_drops_the_cross_module_references(attr):
    """The activate callback closes over the ToolbarManager and the host cell — a
    'closed' MPR must not keep the patient tab reachable."""
    src = _func_source(LAYOUT, "cleanup")
    assert f'"{attr}"' in src, f"cleanup() does not drop {attr}"


def test_cleanup_stops_the_interaction_timer():
    """The one timer the OPT-47 teardown missed. It fires _apply_interaction_update,
    which walks self.viewers and renders — a stale callback into a finalized window."""
    src = _func_source(LAYOUT, "cleanup")
    assert "_interaction_timer" in src, "cleanup() never stops the interaction timer"


def test_cleanup_disconnects_and_drops_the_timers():
    """Stopping is not enough: a later _request_render could restart a stopped timer
    against a dead widget."""
    src = _func_source(LAYOUT, "cleanup")
    tail = src[src.index("_interaction_timer") :]
    assert ".stop()" in tail
    assert "timeout.disconnect()" in tail, "timers are stopped but not disconnected"
    assert "setattr(self, _tname, None)" in tail, "timer references are not dropped"


def test_teardown_still_releases_gpu_before_finalize():
    """Regression pin for OPT-47 — the ordering that made the GPU release effective.
    ReleaseGraphicsResources needs a VALID GL context, so it must precede Finalize()."""
    src = _func_source(LAYOUT, "cleanup")
    assert src.index("ReleaseGraphicsResources") < src.index("_w.Finalize()"), (
        "ReleaseGraphicsResources must run BEFORE Finalize() or the GPU memory is "
        "never actually reclaimed (OPT-47)"
    )


def test_teardown_still_clears_viewers_and_volume():
    """Regression pin for OPT-47 — the reference-cycle break and volume release."""
    src = _func_source(LAYOUT, "cleanup")
    assert "self.viewers.clear()" in src
    assert "self.image_data = None" in src


def test_new_teardown_steps_are_inside_the_full_teardown_kill_switch():
    """AIPACS_MPR_FULL_TEARDOWN=0 must still restore the legacy Finalize()-only path."""
    src = _func_source(LAYOUT, "cleanup")
    guard = src.index("if _full_teardown:", src.index("self.viewers.clear()") - 600)
    for marker in ("text_actors", "_interaction_timer", "_viewport_activate_cb"):
        assert src.index(marker) > guard, (
            f"{marker} cleanup is outside the _full_teardown kill switch"
        )


def test_cleanup_never_raises_out():
    """Every step is individually guarded — a teardown race must not escape cleanup()."""
    src = _func_source(LAYOUT, "cleanup")
    tail = src[src.index("LIFECYCLE COMPLETION") :]
    # every loop body in the new section wraps its work
    assert tail.count("try:") >= 4
    assert tail.count("except Exception:") >= 4


# ---------------------------------------------------------------------------
# 4. Worker lifecycle — "no worker remains active after MPR has been closed"
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fname", ["_load_vtk_paths_responsive", "_prepare_mpr_flip_offthread"])
def test_mpr_workers_are_joined_before_the_open_returns(fname):
    """Both helpers create a QThread behind a modal dialog. They must JOIN it, so by
    construction no MPR worker can outlive the open (let alone the close)."""
    src = _func_source(TOOLBAR, fname)
    assert "worker.start()" in src
    assert "worker.wait()" in src, (
        f"{fname} starts a QThread it never joins — a worker could outlive the MPR "
        f"widget and touch a destroyed object"
    )
    assert src.index("worker.start()") < src.index("worker.wait()")


def test_mpr_workers_do_not_touch_qt_or_vtk_widgets():
    """A worker may build the volume; it must never reach a render window/widget."""
    src = _func_source(TOOLBAR, "_load_vtk_paths_responsive")
    run_body = src[src.index("def run(") : src.index("worker = _VtkLoadWorker()")]
    for forbidden in ("GetRenderWindow", "Render()", "setParent", "show()", "self.patient_widget"):
        assert forbidden not in run_body, (
            f"the load worker touches {forbidden!r} off the GUI thread"
        )


# ---------------------------------------------------------------------------
# 5. Geometry safety — this work must not move a single voxel
# ---------------------------------------------------------------------------


def test_lifecycle_work_changed_no_geometry_api():
    """Standing constraint: no regression in geometry / radiological convention.
    The lifecycle changes are teardown + guards only, so none of the geometry-setting
    calls may appear in the code they added."""
    cleanup_src = _func_source(LAYOUT, "cleanup")
    new_section = cleanup_src[cleanup_src.index("LIFECYCLE COMPLETION") :]
    for forbidden in (
        "SetSpacing",
        "SetOrigin",
        "SetDirectionMatrix",
        "SetFilteredAxis",
        "SetResampleToScreenPixels",
        "SetParallelScale",
        "SetViewUp",
        "SetFocalPoint",
        "SetPosition",
        "ResetCamera",
    ):
        assert forbidden not in new_section, (
            f"the lifecycle teardown touches {forbidden} — this work must not change "
            f"geometry or camera state"
        )


def test_closed_guards_added_no_geometry_calls():
    for fname in (
        "_request_render",
        "_execute_pending_renders",
        "_render_immediately",
        "_apply_interaction_update",
        "_request_interaction_update",
    ):
        src = _func_source(ORIENT, fname)
        assert "SetSpacing" not in src and "SetOrigin" not in src
        assert "ResetCamera" not in src, (
            f"{fname} contains ResetCamera — the scroll/render path must never reset "
            f"the camera (jitter regression guard, 2026-08-01)"
        )
