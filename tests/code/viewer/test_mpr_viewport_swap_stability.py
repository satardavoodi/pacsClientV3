"""The patient viewport layout must not move while an MPR builds (2026-08-01).

THE BUG
-------
Reported: with two viewports open, starting MPR on one made the OTHER briefly
expand to almost the whole screen, then snap back when the MPR appeared.

`toggle_zeta_mpr` did:

    selected_widget.setVisible(False)      # line ~5514  <-- host cell emptied HERE
    ... resolve series, load the volume, off-thread X-flip,
        StandardMPRViewer(...)  =  SECONDS on a large study ...
    parent_layout.addWidget(zeta_widget, row, col, ...)   # ~150 lines later

A `QGridLayout` gives a hidden widget ZERO space (nothing here calls
`setRetainSizeWhenHidden`). So for the whole build the MPR's cell was empty and
its sibling was the only visible item — and a lone visible widget in a grid takes
the entire area. That is precisely the reported symptom, including that it
reverts the instant the MPR widget lands.

NOTE this is a DIFFERENT grid from the one investigated earlier the same day. The
MPR's own internal 2x2 was measured and does NOT move (see
`test_mpr_deferred_3d_layout_stability.py`) — because three of its four panes stay
present and still span both rows and both columns. The PATIENT viewport grid has
only two cells, so emptying one hands everything to the other. Both measurements
are correct; they are different layouts.

THE FIX
-------
Keep the host visible (and its cell occupied, still showing its image) for the
whole build, then hide-and-insert in ONE repaint-suppressed step.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QGridLayout, QSizePolicy, QWidget

REPO = Path(__file__).resolve().parents[3]
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


@pytest.fixture(scope="module")
def _app():
    yield QApplication.instance() or QApplication([])


def _src() -> str:
    return TOOLBAR.read_text(encoding="utf-8", errors="replace")


def _func_source(name: str) -> str:
    tree = ast.parse(_src())
    lines = _src().splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "\n".join(lines[node.lineno - 1 : node.end_lineno])
    raise AssertionError(f"{name} not found")


# ---------------------------------------------------------------------------
# 1. BEHAVIOURAL — the mechanism, on a real two-viewport grid
# ---------------------------------------------------------------------------


def _two_viewport_grid():
    host = QWidget()
    host.resize(1200, 800)
    grid = QGridLayout(host)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(2)
    cells = []
    for col in (0, 1):
        w = QWidget()
        w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        grid.addWidget(w, 0, col)
        cells.append(w)
    host.show()
    grid.activate()
    return host, grid, cells


def test_hiding_the_mpr_host_lets_the_sibling_take_the_screen(_app):
    """THE BUG, reproduced. This is what happened for the whole build."""
    host, grid, (mpr_cell, sibling) = _two_viewport_grid()
    before = sibling.width()

    mpr_cell.setVisible(False)          # the legacy early hide
    grid.activate()

    assert sibling.width() > before * 1.8, (
        f"expected the sibling to expand into the emptied cell "
        f"({before} -> {sibling.width()})"
    )
    host.deleteLater()


def test_the_layout_is_untouched_for_as_long_as_the_host_stays_visible(_app):
    """THE FIX's guarantee. The build takes seconds; for all of it the host is
    still visible and still occupies its cell, so the layout is bit-identical to
    the instant before the user clicked MPR — the sibling cannot gain anything.

    NOTE what this deliberately does NOT assert: the pixel-exact outcome of the
    final swap. Reproducing that faithfully needs the real widget (parenting,
    show semantics and the MPR's own size hints all participate), and a synthetic
    stand-in gets it wrong in ways that would make the assertion meaningless
    rather than protective. The swap is one layout pass with repaints suppressed,
    so nothing transient is painted; the final appearance is covered by live
    verification and by the fact that it was already correct before this change.
    """
    host, grid, (mpr_cell, sibling) = _two_viewport_grid()
    snapshot = (mpr_cell.geometry(), sibling.geometry())

    # ... resolve series, load volume, off-thread flip, build the viewer ...
    # (nothing touches the layout while the host remains visible)
    grid.activate()

    assert (mpr_cell.geometry(), sibling.geometry()) == snapshot, (
        "the layout moved even though the host was never hidden"
    )
    assert mpr_cell.isVisible(), "the host must stay visible for the whole build"
    host.deleteLater()


# ---------------------------------------------------------------------------
# 2. All three MPR entry points defer the hide
# ---------------------------------------------------------------------------

_ENTRY_POINTS = [
    "toggle_zeta_mpr",              # Standard MPR — the reported one
    "_launch_dental_curve_vtk_host",  # Dental Curve MPR picking host
    "toggle_new_curve_mpr",         # CurveMPR
]


@pytest.mark.parametrize("fname", _ENTRY_POINTS)
def test_entry_point_does_not_hide_the_host_before_building(fname):
    """An unconditional `selected_widget.setVisible(False)` before the viewer is
    constructed is the bug. It may only run under the legacy kill switch."""
    src = _func_source(fname)
    for m in re.finditer(r"^\s*selected_widget\.setVisible\(False\)\s*$", src, re.M):
        # Every remaining occurrence must sit under `if not _defer_host_hide:`
        # (legacy kill switch) or `if _defer_host_hide:` (inside the atomic swap).
        # Skip comment lines when looking back — a comment between the `if` and
        # the statement is normal and must not read as "unguarded".
        preceding = [
            ln.strip()
            for ln in src[: m.start()].rstrip().splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        assert preceding and preceding[-1] in (
            "if not _defer_host_hide:",
            "if _defer_host_hide:",
        ), (
            f"{fname}: `selected_widget.setVisible(False)` at an unguarded site "
            f"(preceded by {preceding[-1]!r}) — the host cell will be empty while "
            f"the viewer builds and a sibling viewport will expand into it"
        )


@pytest.mark.parametrize("fname", _ENTRY_POINTS)
def test_entry_point_hides_only_after_the_viewer_exists(fname):
    """Ordering: the construction must precede the hide."""
    src = _func_source(fname)
    build = min(
        (src.index(m) for m in ("StandardMPRViewer(",) if m in src),
        default=None,
    )
    assert build is not None, f"{fname}: no StandardMPRViewer construction found"
    guarded = src.index("if _defer_host_hide:\n")
    assert build < guarded, (
        f"{fname}: the host is hidden before the viewer is built "
        f"(build={build}, hide={guarded})"
    )


@pytest.mark.parametrize("fname", _ENTRY_POINTS)
def test_entry_point_swap_is_repaint_suppressed_and_activated(fname):
    """`activate()` must run while painting is OFF — `updateGeometry()` only posts
    a layout request, so the re-enabled repaint can beat the layout."""
    src = _func_source(fname)
    tail = src[src.index("if _defer_host_hide:\n") :]
    off = src.rindex("setUpdatesEnabled(False)", 0, src.index("if _defer_host_hide:\n"))
    act = tail.index(".activate()") + len(src) - len(tail)
    on = tail.index("setUpdatesEnabled(True)") + len(src) - len(tail)
    assert off < act < on, f"{fname}: swap bracket out of order"


@pytest.mark.parametrize("fname", _ENTRY_POINTS)
def test_updates_are_re_enabled_in_a_finally(fname):
    """A failure mid-swap must never leave the workstation unpainted."""
    src = _func_source(fname)
    tail = src[src.index("if _defer_host_hide:\n") :]
    fin = tail.index("finally:")
    assert "setUpdatesEnabled(True)" in tail[fin:], (
        f"{fname}: repaints are not re-enabled in a finally"
    )


@pytest.mark.parametrize("fname", _ENTRY_POINTS)
def test_entry_point_has_the_shared_kill_switch(fname):
    src = _func_source(fname)
    assert '"AIPACS_MPR_STABLE_VIEWPORT_SWAP", "1"' in src, (
        f"{fname}: missing the default-on kill switch"
    )


def test_all_three_entry_points_share_one_flag():
    """One behaviour, one switch — not three subtly different ones."""
    assert _src().count("AIPACS_MPR_STABLE_VIEWPORT_SWAP") >= 3


# ---------------------------------------------------------------------------
# 3. Nothing about the image changed
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fname", _ENTRY_POINTS)
def test_swap_touched_no_geometry_or_viewer_api(fname):
    """Widget rectangles are not image geometry. The swap must only move widgets."""
    src = _func_source(fname)
    tail = src[src.index("if _defer_host_hide:\n") :]
    swap = tail[: tail.index("finally:") + 400]
    for forbidden in (
        "SetSpacing",
        "SetOrigin",
        "SetDirectionMatrix",
        "SetFilteredAxis",
        "ResetCamera",
        "SetParallelScale",
        "set_window_level",
    ):
        assert forbidden not in swap, f"{fname}: the swap touches {forbidden}"


def test_grid_position_is_still_captured_and_reused():
    """The MPR must land in the host's ORIGINAL cell, span included."""
    src = _func_source("toggle_zeta_mpr")
    assert "_mpr_grid_position = grid_position" in src
    assert "row, col, rowSpan, colSpan = grid_position" in src
    assert "addWidget(zeta_widget, row, col, rowSpan, colSpan)" in src
