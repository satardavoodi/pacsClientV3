"""Reference lines are BIDIRECTIONAL — every viewport is source AND target (2026-08-03).

The legacy engine took ONE source (`self.selected_widget`) and drew its plane on
every other viewport. Selection is CLICK-only (`qt_slice_viewer.mousePressEvent` →
`change_container_border`); wheel-scrolling never changes it. So only the
last-clicked viewport ever broadcast: axial→sagittal/coronal worked, while
sagittal→axial and coronal→anything never appeared.

`_manage_reference_line_all_pairs` draws, on every viewport, one line per OTHER
viewport, so Axial↔Sagittal↔Coronal all update when any of them changes slice.
Flag `AIPACS_REFERENCE_LINES_ALL_PAIRS` (default on) keeps the legacy path.
"""
import math

import numpy as np
import pytest


# ── Minimal fakes: enough surface for the engine, no Qt/VTK ────────────────

class _FakeVtkImageData:
    def __init__(self, rows, cols, sx=1.0, sy=1.0):
        self._dims = (int(cols), int(rows), 1)
        self._sp = (float(sx), float(sy), 1.0)

    def GetDimensions(self):
        return self._dims

    def GetSpacing(self):
        return self._sp

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
    """Qt-bridge-flavoured viewer: IS_QT_BRIDGE so the engine takes the Qt path."""
    IS_QT_BRIDGE = True

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
    """n instances stepping along `normal`, all sharing orientation `iop`."""
    out = []
    for k in range(n):
        ipp = [ipp0[i] + k * step * normal[i] for i in range(3)]
        out.append({
            "instance_number": 1,          # multi-frame: identical for every frame
            "instance_path": "f.dcm",
            "image_orientation_patient": list(iop),
            "image_position_patient": ipp,
            "pixel_spacing": [1.0, 1.0],
            "rows": rows, "columns": cols,
        })
    return out


AX = (1, 0, 0, 0, 1, 0)      # axial   → normal +Z
SAG = (0, 1, 0, 0, 0, -1)    # sagittal→ normal ~X
COR = (1, 0, 0, 0, 0, -1)    # coronal → normal ~Y


def _mixin():
    pytest.importorskip("PySide6")
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_sync import (
        _PWSyncMixin,
    )
    return _PWSyncMixin


def _harness(monkeypatch):
    """Three orthogonal viewports centred on a common volume."""
    Mixin = _mixin()

    class _Host(Mixin):
        def __init__(self):
            ax = _FakeImageViewer(_plane_instances(AX, [-32.0, -32.0, -8.0], (0, 0, 1)), 4)
            sg = _FakeImageViewer(_plane_instances(SAG, [-8.0, -32.0, 32.0], (1, 0, 0)), 4)
            cr = _FakeImageViewer(_plane_instances(COR, [-32.0, -8.0, 32.0], (0, 1, 0)), 4)
            self.w_ax = _FakeWidget(ax, "axial")
            self.w_sg = _FakeWidget(sg, "sagittal")
            self.w_cr = _FakeWidget(cr, "coronal")
            self.lst_nodes_viewer = [_FakeNode(self.w_ax), _FakeNode(self.w_sg), _FakeNode(self.w_cr)]
            # Selection stays on AXIAL for the whole test — this is the point:
            # the other two must still broadcast without ever being clicked.
            self.selected_widget = self.w_ax

        def _geometry_instances_for_viewer(self, iv, **kw):
            return iv._instances

    return _Host()


def test_every_viewport_gets_lines_from_the_other_two(monkeypatch):
    host = _harness(monkeypatch)
    host._manage_reference_line_all_pairs(repaint=False)
    for w in (host.w_ax, host.w_sg, host.w_cr):
        lines = w.image_viewer.qt_viewer.lines
        assert lines, f"{w.name} got NO reference line"
        assert len(lines) == 2, (
            f"{w.name} should show one line per OTHER viewport, got {len(lines)}"
        )


def test_the_never_selected_viewports_still_broadcast(monkeypatch):
    """The regression: selection never leaves axial, yet sagittal+coronal planes
    must still appear on the other views."""
    host = _harness(monkeypatch)
    assert host.selected_widget is host.w_ax
    host._manage_reference_line_all_pairs(repaint=False)
    # axial is the SELECTED one — under the legacy engine it was the only source
    # and was always cleared. Now it receives sagittal's and coronal's planes.
    assert len(host.w_ax.image_viewer.qt_viewer.lines) == 2


def test_a_viewport_never_draws_its_own_plane_on_itself(monkeypatch):
    host = _harness(monkeypatch)
    host._manage_reference_line_all_pairs(repaint=False)
    # 3 viewports → each shows exactly the OTHER 2, never 3
    for w in (host.w_ax, host.w_sg, host.w_cr):
        assert len(w.image_viewer.qt_viewer.lines) == 2


def test_lines_move_when_a_viewport_changes_slice(monkeypatch):
    host = _harness(monkeypatch)
    host._manage_reference_line_all_pairs(repaint=False)
    before = list(host.w_sg.image_viewer.qt_viewer.lines)
    # scroll the AXIAL viewport (no click, no selection change)
    host.w_ax.image_viewer._slice = 7
    host._manage_reference_line_all_pairs(repaint=False)
    after = list(host.w_sg.image_viewer.qt_viewer.lines)
    assert before != after, "sagittal's line did not follow the axial slice change"


def test_scrolling_a_non_selected_viewport_moves_the_line_elsewhere(monkeypatch):
    """Sagittal → axial/coronal: the direction that was previously dead."""
    host = _harness(monkeypatch)
    host._manage_reference_line_all_pairs(repaint=False)
    before_ax = list(host.w_ax.image_viewer.qt_viewer.lines)
    before_cr = list(host.w_cr.image_viewer.qt_viewer.lines)
    host.w_sg.image_viewer._slice = 7          # scroll SAGITTAL only
    host._manage_reference_line_all_pairs(repaint=False)
    assert list(host.w_ax.image_viewer.qt_viewer.lines) != before_ax, \
        "axial did not react to a sagittal slice change"
    assert list(host.w_cr.image_viewer.qt_viewer.lines) != before_cr, \
        "coronal did not react to a sagittal slice change"


def test_single_viewport_draws_nothing(monkeypatch):
    host = _harness(monkeypatch)
    host.lst_nodes_viewer = [_FakeNode(host.w_ax)]
    host._manage_reference_line_all_pairs(repaint=False)
    assert not host.w_ax.image_viewer.qt_viewer.lines


def test_target_without_geometry_is_cleared_not_crashed(monkeypatch):
    host = _harness(monkeypatch)
    for inst in host.w_cr.image_viewer._instances:
        inst["image_orientation_patient"] = None
        inst["image_position_patient"] = None
    host._manage_reference_line_all_pairs(repaint=False)
    assert host.w_cr.image_viewer.qt_viewer.cleared >= 1
    # the other two still work, and now see only ONE usable other plane each
    assert host.w_ax.image_viewer.qt_viewer.lines
    assert host.w_sg.image_viewer.qt_viewer.lines


def test_repaint_updates_every_widget(monkeypatch):
    host = _harness(monkeypatch)
    host._manage_reference_line_all_pairs(repaint=True)
    for w in (host.w_ax, host.w_sg, host.w_cr):
        assert w.updates >= 1


def test_flag_off_uses_legacy_single_source(monkeypatch):
    Mixin = _mixin()
    monkeypatch.setenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", "0")
    host = _harness(monkeypatch)
    assert host._rl_all_pairs_enabled() is False


def test_all_pairs_is_OFF_by_default(monkeypatch):
    """2026-08-16: the default flipped to the legacy single-source path.

    All-pairs put a reference line on the ACTIVE viewport too, which reads as
    wrong on the floor — the active series is the source and should stay clean.
    This test previously asserted the opposite; it is re-pointed rather than
    deleted so the flag's default stays pinned in both directions.
    See docs/reports/REFERENCE_LINE_ACTIVE_VIEWPORT_2026-08-16.md.
    """
    monkeypatch.delenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", raising=False)
    host = _harness(monkeypatch)
    assert host._rl_all_pairs_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on", "ON", " 1 "])
def test_all_pairs_can_be_switched_back_on(monkeypatch, val):
    monkeypatch.setenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", val)
    host = _harness(monkeypatch)
    assert host._rl_all_pairs_enabled() is True


def test_round_robin_targets_include_every_viewport(monkeypatch):
    """With all-pairs ON the selected widget is also a target — excluding it
    would leave its own lines unpainted."""
    monkeypatch.setenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", "1")
    host = _harness(monkeypatch)
    targets = host._rl_get_target_widgets()
    assert len(targets) == 3
    assert host.selected_widget in targets


def test_legacy_round_robin_still_excludes_the_source(monkeypatch):
    monkeypatch.setenv("AIPACS_REFERENCE_LINES_ALL_PAIRS", "0")
    host = _harness(monkeypatch)
    targets = host._rl_get_target_widgets()
    assert host.selected_widget not in targets
    assert len(targets) == 2


def test_sort_skips_rebuild_when_already_ordered():
    """Multi-frame instances all share one instance_number + path, so the sort can
    never reorder them — it must not allocate a new list per tick."""
    Mixin = _mixin()
    instances = _plane_instances(AX, [0.0, 0.0, 0.0], (0, 0, 1), n=64)
    out = Mixin._sort_instances_by_instance_number(instances)
    assert out is instances, "already-ordered list should be returned as-is"


def test_sort_still_orders_a_shuffled_list():
    Mixin = _mixin()
    insts = [
        {"instance_number": 3, "instance_path": "c"},
        {"instance_number": 1, "instance_path": "a"},
        {"instance_number": 2, "instance_path": "b"},
    ]
    out = Mixin._sort_instances_by_instance_number(insts)
    assert [i["instance_number"] for i in out] == [1, 2, 3]
