"""The MPR layout must not move while the deferred / on-demand 3D VRT builds (2026-08-01).

THE REPORT
----------
On a large series the 3D VRT is not auto-built (OPT-48 #4) — the 3D cell shows a
clickable "3D view (click to render)" placeholder. Clicking it made the whole MPR
appear to collapse, shift left and re-proportion until the 3D finished loading.

A HYPOTHESIS THAT WAS TESTED AND DISPROVED — do not re-litigate it
-----------------------------------------------------------------
The obvious explanation was a grid reflow: the 2x2 `views_layout` has NO stretch
factors (a grep for `setRowStretch`/`setColumnStretch` across the package returns
nothing), and `_build_deferred_3d_view` removed the placeholder BEFORE building
while `_create_3d_view` only adds its container as its very LAST statement — so
cell (0,1) really is empty for the entire multi-second build.

It is measurably NOT the cause. `test_an_empty_3d_cell_does_not_move_the_other_panes`
drives a real `QGridLayout` at four host sizes, with and without the panes'
400x400 QVTK size hints, and the other three panes move by **exactly 0 px** in
every case — because all four panes are `Expanding`, so extra space is divided
evenly no matter what occupies each cell. A stretch pin was written, measured to
be a no-op, and removed.

WHAT IS LEFT, AND WHAT THESE TESTS PIN
--------------------------------------
The build blocks the GUI thread for ~9 s on a 672-slice CT (measured, OPT-48) and
cannot be off-threaded — VTK GL context creation is GUI-thread-only. An
unresponsive window past ~5 s is what Windows replaces with a DWM ghost, and a
stretched/offset ghost bitmap is what a "collapsed, shifted" MPR looks like.

So the changes here are PRESENTATION, and the tests say so:
- the placeholder holds its cell for the whole build (the 3D viewport shows its
  own loading state instead of going black and empty);
- the swap is repaint-suppressed and `activate()`d while painting is off;
- the blocking build is deferred off the click handler so the loading state paints;
- a modal busy dialog is painted BEFORE the freeze so the wait has an explicit
  owner and stray clicks land on it.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QGridLayout, QSizePolicy, QWidget

REPO = Path(__file__).resolve().parents[3]
VIEWS = REPO / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py"


@pytest.fixture(scope="module")
def _app():
    app = QApplication.instance() or QApplication([])
    yield app


def _src() -> str:
    return VIEWS.read_text(encoding="utf-8", errors="replace")


def _func_source(name: str) -> str:
    tree = ast.parse(_src())
    lines = _src().splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} not found in {VIEWS.name}")


# ---------------------------------------------------------------------------
# 1. BEHAVIOURAL: the grid is NOT the cause (the disproof, kept as evidence)
# ---------------------------------------------------------------------------


class _FakeVtkPane(QWidget):
    """Same layout contract as QVTKRenderWindowInteractor: fixed 400x400 sizeHint
    and an Expanding policy."""

    def sizeHint(self):  # noqa: D102
        from PySide6.QtCore import QSize

        return QSize(400, 400)


def _make_mpr_like_grid(host_w, host_h, with_vtk_hints):
    host = QWidget()
    host.resize(host_w, host_h)
    grid = QGridLayout(host)
    grid.setContentsMargins(2, 2, 2, 2)
    grid.setSpacing(2)
    panes = {}
    for name, (r, c) in {"axial": (0, 0), "sagittal": (1, 0), "coronal": (1, 1)}.items():
        frame = QWidget()
        inner = __import__("PySide6.QtWidgets", fromlist=["QVBoxLayout"]).QVBoxLayout(frame)
        inner.setContentsMargins(0, 0, 0, 0)
        child = _FakeVtkPane() if with_vtk_hints else QWidget()
        child.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        inner.addWidget(child)
        grid.addWidget(frame, r, c)
        panes[name] = frame
    placeholder = QWidget()
    placeholder.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    grid.addWidget(placeholder, 0, 1)
    panes["three_d"] = placeholder
    host.show()
    grid.activate()
    return host, grid, panes


@pytest.mark.parametrize("host_size", [(1400, 900), (900, 650), (700, 500), (520, 420)])
@pytest.mark.parametrize("with_vtk_hints", [False, True])
def test_an_empty_3d_cell_does_not_move_the_other_panes(_app, host_size, with_vtk_hints):
    """THE DISPROOF. Removing the 3D pane — exactly what the deferred build did for
    the whole multi-second window — leaves the other three panes bit-identical at
    every host size, with and without the 400x400 QVTK size hints.

    This is why no stretch pin was added: all four panes are Expanding, so the
    extra space divides evenly regardless of what occupies each cell. If a future
    reader is tempted to 'fix' a moving MPR layout with stretch factors, this test
    is the reason not to.
    """
    host, grid, panes = _make_mpr_like_grid(*host_size, with_vtk_hints=with_vtk_hints)
    before = {n: panes[n].geometry() for n in ("axial", "sagittal", "coronal")}

    grid.removeWidget(panes["three_d"])
    panes["three_d"].setParent(None)
    grid.activate()

    for name in ("axial", "sagittal", "coronal"):
        assert panes[name].geometry() == before[name], (
            f"{name} moved while the 3D cell was empty at host {host_size} "
            f"(vtk_hints={with_vtk_hints}): {before[name]} -> {panes[name].geometry()}. "
            f"If this now fails, the grid DOES reflow and the layout hypothesis "
            f"should be re-opened."
        )
    host.deleteLater()


def test_no_stretch_pin_was_added_and_the_reason_is_recorded():
    """A stretch pin was written, measured to be a no-op, and removed. Keep the
    note so the same dead end is not re-explored."""
    src = _src()
    assert "setRowStretch" not in src and "setColumnStretch" not in src, (
        "a stretch pin was re-added — it was measured to change nothing (see the "
        "parametrised disproof above); if you need it, prove it moves pixels first"
    )
    assert "the cause is the blocked GUI thread, not the layout" in src, (
        "the note explaining why there is no stretch pin was removed"
    )


# ---------------------------------------------------------------------------
# 3. Build-then-swap ordering — the cell is never empty
# ---------------------------------------------------------------------------


def test_the_placeholder_is_removed_AFTER_the_3d_view_is_built():
    """This ordering IS the fix: `_create_3d_view` only adds its container as its
    last statement, so removing the placeholder first left the cell empty for the
    whole (multi-second) build."""
    src = _func_source("_build_deferred_3d_view")
    build = src.index("self._create_3d_view(layout, 0, 1)")
    remove = src.index("layout.removeWidget(placeholder)")
    assert build < remove, (
        "the placeholder is still removed BEFORE the 3D pane is built — cell (0,1) "
        "will be empty for the entire build and the layout will collapse into it"
    )


def test_create_3d_view_still_adds_its_container_last():
    """The premise of the previous test. If `_create_3d_view` ever starts adding
    its container EARLY, the ordering above stops mattering and this guard should
    be revisited rather than silently passing."""
    src = _func_source("_create_3d_view")
    add = src.index("layout.addWidget(container, row, col)")
    for expensive in ("QVTKRenderWindowInteractor(container)", "vtk_widget.Initialize()"):
        assert src.index(expensive) < add, (
            f"{expensive} now runs AFTER the container is added — re-derive the "
            f"deferred-build ordering guard"
        )


def test_the_swap_suppresses_repaints_and_activates_while_paint_is_off():
    """`updateGeometry()` alone only POSTS a layout request, so the repaint can
    land before the layout runs — the project's sidebar bug. Use `activate()`."""
    src = _func_source("_build_deferred_3d_view")
    off = src.index("setUpdatesEnabled(False)")
    act = src.index("layout.activate()")
    on = src.index("setUpdatesEnabled(True)")
    assert off < act < on, (
        "the layout must be activated while painting is still disabled "
        f"(off={off}, activate={act}, on={on})"
    )


def test_updates_are_re_enabled_in_a_finally():
    """A failure mid-build must never leave the MPR frozen with painting off."""
    src = _func_source("_build_deferred_3d_view")
    tail = src[src.index("finally:") :]
    assert "setUpdatesEnabled(True)" in tail, (
        "repaints are not re-enabled in a finally — an exception during the 3D "
        "build would leave the whole MPR unpainted"
    )


def test_build_is_still_teardown_safe():
    """Regression pin for the L1 deferred-3D teardown guard."""
    src = _func_source("_build_deferred_3d_view")
    assert "_deferred_3d_pending" in src
    assert "except RuntimeError" in src, (
        "the deleted-C++-object teardown race guard was dropped"
    )


def test_stable_swap_has_a_default_on_kill_switch():
    fn = _func_source("mpr_deferred_3d_stable_swap_enabled")
    assert '"AIPACS_MPR_DEFERRED_3D_STABLE_SWAP", "1"' in fn


# ---------------------------------------------------------------------------
# 3b. The freeze gets an explicit owner
# ---------------------------------------------------------------------------


def test_a_modal_busy_dialog_is_painted_before_the_blocking_build():
    """The build blocks the GUI thread for ~9 s and cannot be off-threaded. The
    dialog must be shown AND processed before `_create_3d_view`, or the user sees
    a ghosted/frozen workstation instead of an attributed wait."""
    src = _func_source("_build_deferred_3d_view")
    show = src.index("_busy.show()")
    pump = src.index("processEvents()")
    build = src.index("self._create_3d_view(layout, 0, 1)")
    assert show < pump < build, (
        "the busy dialog must be shown and painted BEFORE the blocking build "
        f"(show={show}, processEvents={pump}, build={build})"
    )


def test_the_busy_dialog_cannot_be_cancelled_or_left_behind():
    src = _func_source("_build_deferred_3d_view")
    assert "setCancelButton(None)" in src, (
        "a cancel button implies the VTK build can be interrupted — it cannot"
    )
    tail = src[src.index("finally:") :]
    assert "_busy.close()" in tail, (
        "the modal is not closed in the finally — a failed build would leave the "
        "workstation behind a dialog it cannot dismiss"
    )


def test_busy_dialog_has_a_default_on_kill_switch():
    fn = _func_source("mpr_deferred_3d_progress_enabled")
    assert '"AIPACS_MPR_DEFERRED_3D_PROGRESS", "1"' in fn


# ---------------------------------------------------------------------------
# 4. The click handler
# ---------------------------------------------------------------------------


def test_click_defers_the_blocking_build_so_the_loading_state_paints():
    src = _func_source("_install_deferred_3d_placeholder")
    handler = src[src.index("def _on_placeholder_click") :]
    assert "QTimer.singleShot(0, _self._build_deferred_3d_view)" in handler, (
        "the click still calls the multi-second build inline — the 'Rendering 3D…' "
        "state cannot paint and the user's only feedback is a frozen window"
    )
    assert "_self._build_deferred_3d_view()" not in handler.replace(
        "QTimer.singleShot(0, _self._build_deferred_3d_view)", ""
    ), "the build is also still invoked inline"


def test_click_refuses_a_second_activation_while_building():
    src = _func_source("_install_deferred_3d_placeholder")
    handler = src[src.index("def _on_placeholder_click") :]
    assert re.search(
        r"if not getattr\(_self, '_deferred_3d_pending', False\):\s*\n\s*return", handler
    ), "a second click during the build is not refused"


def test_click_shows_a_loading_state():
    src = _func_source("_install_deferred_3d_placeholder")
    handler = src[src.index("def _on_placeholder_click") :]
    assert "Rendering 3D" in handler
    assert "WaitCursor" in handler


# ---------------------------------------------------------------------------
# 5. On-demand threshold unchanged, and geometry safety
# ---------------------------------------------------------------------------


def test_on_demand_threshold_is_unchanged():
    """This work is layout-only — the 200-slice on-demand decision must not move."""
    fn = _func_source("_vrt_on_demand_slice_threshold")
    assert '"AIPACS_MPR_VRT_ON_DEMAND_SLICES", "200"' in fn
    assert "return value if value > 0 else 200" in fn


def test_layout_stability_work_touched_no_geometry_api():
    """Standing constraint: no regression in geometry / radiological convention.
    Widget rectangles are not image geometry — none of these may appear."""
    targets = [
        _func_source("_build_deferred_3d_view"),
        _func_source("mpr_deferred_3d_stable_swap_enabled"),
        _func_source("mpr_deferred_3d_progress_enabled"),
        _func_source("_install_deferred_3d_placeholder"),
    ]
    for src in targets:
        for forbidden in (
            "SetSpacing",
            "SetOrigin",
            "SetDirectionMatrix",
            "SetFilteredAxis",
            "SetResampleToScreenPixels",
            "SetParallelScale",
            "SetViewUp",
            "SetFocalPoint",
            "ResetCamera",
        ):
            assert forbidden not in src, (
                f"the layout-stability work touches {forbidden} — it must change "
                f"only how widget rectangles are apportioned"
            )
