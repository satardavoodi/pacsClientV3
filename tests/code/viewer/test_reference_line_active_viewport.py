"""The ACTIVE viewport must not carry a reference line (2026-08-16).

REPORTED FROM THE FLOOR, on an imported cervical-spine MR (I10027433471):
a 2-up layout with SAG T1 TSE left and AX T2 TSE CHARNIERE right (the active
series) showed a yellow line in BOTH viewports — including the active one.

That was the shipped `_manage_reference_line_all_pairs` behaviour working as
designed: "draw, on EVERY viewport, one reference line per OTHER viewport".
Geometrically defensible, but wrong for reading: the active series is the
SOURCE — the reader is scrolling it — and it should stay clean, with the line
drawn only on the series being cross-referenced. That is the localizer
convention and it is what the legacy single-source path already implemented.

So `AIPACS_REFERENCE_LINES_ALL_PAIRS` now defaults OFF. Nothing was deleted:
`=1` restores bidirectional lines and `_manage_reference_line_all_pairs` keeps
its own tests (`test_reference_lines_all_pairs.py`).

The load-bearing guard in here is `test_the_active_overlay_is_actively_cleared`.
"Skip the source" is not enough — a viewport that was drawn on while inactive
must have its overlay CLEARED the moment it becomes active, or the stale line
stays on screen and the bug looks unfixed.
"""
from __future__ import annotations

import pytest


# ── Minimal fakes — no Qt, no VTK ────────────────────────────────────────────

class _FakeVtkImageData:
    def __init__(self, rows, cols):
        self._dims = (int(cols), int(rows), 1)

    def GetDimensions(self):
        return self._dims

    def GetSpacing(self):
        return (1.0, 1.0, 1.0)

    def GetOrigin(self):
        return (0.0, 0.0, 0.0)


class _FakeQtViewer:
    def __init__(self):
        self.lines = None
        self.cleared = 0

    def set_overlay_lines(self, lines):
        self.lines = list(lines)

    def clear_overlay_lines(self):
        self.cleared += 1
        self.lines = []


class _FakeImageViewer:
    IS_QT_BRIDGE = True          # take the Qt overlay path, as the FAST viewer does

    def __init__(self, instances, slice_index, rows=64, cols=64):
        self._instances = instances
        self._slice = int(slice_index)
        self.vtk_image_data = _FakeVtkImageData(rows, cols)
        self.qt_viewer = _FakeQtViewer()
        self.metadata = {"series": {"series_uid": "u"}}

    def GetSlice(self):
        return self._slice


class _FakeWidget:
    def __init__(self, iv, name):
        self.image_viewer = iv
        self.name = name
        self.updates = 0

    def update(self):
        self.updates += 1


class _FakeNode:
    def __init__(self, widget):
        self.vtk_widget = widget


def _plane_instances(iop, ipp0, normal, n=8, step=2.0, rows=64, cols=64):
    out = []
    for k in range(n):
        ipp = [ipp0[i] + k * step * normal[i] for i in range(3)]
        out.append({
            "instance_number": k + 1,
            "instance_path": "f.dcm",
            "image_orientation_patient": list(iop),
            "image_position_patient": ipp,
            "pixel_spacing": [1.0, 1.0],
            "rows": rows, "columns": cols,
        })
    return out


AX = (1, 0, 0, 0, 1, 0)       # axial    → normal +Z
SAG = (0, 1, 0, 0, 0, -1)     # sagittal → normal ~X
COR = (1, 0, 0, 0, 0, -1)     # coronal  → normal ~Y


def _mixin():
    pytest.importorskip("PySide6")
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_sync import (
        _PWSyncMixin,
    )
    return _PWSyncMixin


def _host(*, viewports="sag_ax"):
    """`sag_ax` reproduces the reported 2-up layout; `three` adds a coronal."""
    Mixin = _mixin()

    class _Host(Mixin):
        def __init__(self):
            sg = _FakeImageViewer(_plane_instances(SAG, [-8.0, -32.0, 32.0], (1, 0, 0)), 4)
            ax = _FakeImageViewer(_plane_instances(AX, [-32.0, -32.0, -8.0], (0, 0, 1)), 4)
            self.w_sg = _FakeWidget(sg, "sagittal")
            self.w_ax = _FakeWidget(ax, "axial")
            nodes = [_FakeNode(self.w_sg), _FakeNode(self.w_ax)]
            self.w_cr = None
            if viewports == "three":
                cr = _FakeImageViewer(_plane_instances(COR, [-32.0, -8.0, 32.0], (0, 1, 0)), 4)
                self.w_cr = _FakeWidget(cr, "coronal")
                nodes.append(_FakeNode(self.w_cr))
            self.lst_nodes_viewer = nodes
            # The reported case: the AXIAL is the active series.
            self.selected_widget = self.w_ax

        def _geometry_instances_for_viewer(self, iv, **kw):
            return iv._instances

    return _Host()


def _lines(widget):
    return widget.image_viewer.qt_viewer.lines or []


# ── the reported case ────────────────────────────────────────────────────────

def test_two_up_layout_draws_exactly_one_line(monkeypatch):
    """SAG + AX, axial active. Before the fix this produced a line in BOTH."""
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    host.manage_reference_line(repaint=False)

    assert not _lines(host.w_ax), (
        "the ACTIVE viewport must stay clean — it is the source, not a target"
    )
    assert _lines(host.w_sg), "the inactive viewport lost its reference line"
    total = len(_lines(host.w_ax)) + len(_lines(host.w_sg))
    assert total == 1, f"a 2-up layout must show exactly one line, got {total}"


def test_the_inactive_viewport_gets_one_line_per_source_only(monkeypatch):
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    host.manage_reference_line(repaint=False)
    assert len(_lines(host.w_sg)) == 1


def test_three_up_still_leaves_the_active_one_clean(monkeypatch):
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host(viewports="three")
    host.manage_reference_line(repaint=False)
    assert not _lines(host.w_ax), "active viewport carried a line in a 3-up layout"
    assert _lines(host.w_sg) and _lines(host.w_cr)


# ── the load-bearing one ─────────────────────────────────────────────────────

def test_the_active_overlay_is_actively_cleared(monkeypatch):
    """A line drawn while a viewport was INACTIVE must vanish when it becomes
    active. Skipping the source silently would leave the stale line painted and
    the bug would look unfixed."""
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()

    # sagittal is active first -> the axial is a target and gets a line
    host.selected_widget = host.w_sg
    host.manage_reference_line(repaint=False)
    assert _lines(host.w_ax), "precondition failed: the axial never got a line"

    # now the user clicks the axial
    host.selected_widget = host.w_ax
    before = host.w_ax.image_viewer.qt_viewer.cleared
    host.manage_reference_line(repaint=False)

    assert not _lines(host.w_ax), "STALE line left on the newly-active viewport"
    assert host.w_ax.image_viewer.qt_viewer.cleared > before, (
        "the source overlay must be cleared explicitly, not merely skipped"
    )


def test_switching_the_active_viewport_moves_the_line(monkeypatch):
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    host.manage_reference_line(repaint=False)
    assert _lines(host.w_sg) and not _lines(host.w_ax)

    host.selected_widget = host.w_sg
    host.manage_reference_line(repaint=False)
    assert _lines(host.w_ax) and not _lines(host.w_sg), \
        "the clean viewport must follow the selection"


# ── the way back ─────────────────────────────────────────────────────────────

def test_env_flag_restores_the_line_on_the_active_viewport(monkeypatch):
    """End-to-end through the public entry point, not just the flag helper."""
    monkeypatch.setenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", "1")
    host = _host()
    host.manage_reference_line(repaint=False)
    assert _lines(host.w_ax), "the kill switch no longer restores bidirectional lines"
    assert _lines(host.w_sg)


@pytest.mark.parametrize("val", ["0", "", "false", "no", "off", "2", "01"])
def test_anything_but_an_explicit_yes_keeps_the_active_one_clean(monkeypatch, val):
    monkeypatch.setenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", val)
    host = _host()
    host.manage_reference_line(repaint=False)
    assert not _lines(host.w_ax)


# ── things that must not have broken ─────────────────────────────────────────

def test_single_viewport_layout_draws_nothing(monkeypatch):
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    host.lst_nodes_viewer = host.lst_nodes_viewer[:1]
    host.selected_widget = host.w_sg
    host.manage_reference_line(repaint=False)
    assert not _lines(host.w_sg)


def test_no_selection_is_survivable(monkeypatch):
    """`selected_widget` can be None between tab switches — must not raise."""
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    host.selected_widget = None
    host.manage_reference_line(repaint=False)   # must not raise


def test_repaint_true_updates_the_target_widgets(monkeypatch):
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    host.manage_reference_line(repaint=True)
    assert host.w_sg.updates >= 1


def test_a_target_without_geometry_is_cleared_not_crashed(monkeypatch):
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _host()
    for inst in host.w_sg.image_viewer._instances:
        inst["image_orientation_patient"] = None
    host.manage_reference_line(repaint=False)
    assert not _lines(host.w_sg)
    assert host.w_sg.image_viewer.qt_viewer.cleared >= 1
