"""Guards for measurement-label readability (2026-06-06).

Pins:
  1. FAST renderer: the shared offset-label helper exists, paints (offset
     text + dotted connector), and is used by ruler / angle / two-line angle.
  2. Label placement constants live in tools.styles (single source of truth).
  3. VTK paths (Advanced 2D ruler/angle, MPR ruler/angle) set the label
     title text property to the measurement color + shadow — the VTK default
     was WHITE, unreadable over bright anatomy.
"""
import inspect
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from modules.viewer.tools import styles  # noqa: E402
from modules.viewer.tools.renderers.qpainter import QPainterToolRenderer  # noqa: E402


def test_label_placement_constants_exist():
    assert styles.LABEL_OFFSET_PX >= 16          # visibly off the line
    assert 0 < styles.LABEL_CONNECTOR_ALPHA < 255  # subtle, not opaque
    assert styles.LABEL_CONNECTOR_GAP_PX >= 2
    assert styles.RULER_COLOR == (0, 230, 0)     # measurement green


def test_offset_label_helper_paints_text_and_connector():
    from PySide6.QtGui import QGuiApplication, QColor, QFont, QImage, QPainter

    _ = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(220, 220, QImage.Format_RGB32)
    img.fill(0xFF000000)

    renderer = QPainterToolRenderer()
    renderer.begin_frame()
    painter = QPainter(img)
    painter.setFont(QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE))
    renderer._draw_offset_label(
        painter, QColor(*styles.RULER_COLOR), "4.0 mm",
        110.0, 110.0, 0.0, -1.0, styles.LABEL_OFFSET_PX,
    )
    painter.end()

    # Some pixels must now be non-black (text + connector painted)
    painted = sum(
        1
        for x in range(0, 220, 3)
        for y in range(0, 220, 3)
        if img.pixel(x, y) != 0xFF000000
    )
    assert painted > 10


def test_nearby_labels_do_not_overlap_within_a_frame():
    """Two measurements anchored at the same point must produce two
    NON-INTERSECTING label rects (collision avoidance steps the second
    label further out) — and begin_frame resets the map."""
    from PySide6.QtGui import QGuiApplication, QColor, QFont, QImage, QPainter

    _ = QGuiApplication.instance() or QGuiApplication([])
    img = QImage(420, 420, QImage.Format_RGB32)
    img.fill(0xFF000000)

    renderer = QPainterToolRenderer()
    renderer.begin_frame()
    painter = QPainter(img)
    painter.setFont(QFont(styles.LABEL_FONT_FAMILY, styles.LABEL_FONT_SIZE))
    color = QColor(*styles.RULER_COLOR)
    renderer._draw_offset_label(painter, color, "41.3 mm", 210.0, 210.0, 0.0, -1.0, styles.LABEL_OFFSET_PX)
    renderer._draw_offset_label(painter, color, "35.4 mm", 210.0, 210.0, 0.0, -1.0, styles.LABEL_OFFSET_PX)
    painter.end()

    rects = renderer._placed_label_rects
    assert len(rects) == 2
    assert not rects[0].intersects(rects[1]), (
        f"labels overlap: {rects[0]} vs {rects[1]}"
    )

    # New frame: map resets so labels don't keep climbing across repaints
    renderer.begin_frame()
    assert renderer._placed_label_rects == []


def test_controller_resets_label_map_each_render_pass():
    import inspect as _inspect
    from modules.viewer.tools.controller import ToolController

    src = _inspect.getsource(ToolController.render)
    assert "begin_frame" in src, "controller must reset the label collision map per pass"


def test_fast_renderers_route_labels_through_offset_helper():
    for method in ('_render_ruler', '_render_angle', '_render_two_line_angle'):
        src = inspect.getsource(getattr(QPainterToolRenderer, method))
        assert '_draw_offset_label' in src, f"{method} must use the offset label"


@pytest.mark.parametrize("module_path, attr_chain", [
    ("modules.viewer.interactor_styles.ruler_interactorstyle", "RulerInteractorStyle.set_widget_repr"),
    ("modules.viewer.interactor_styles.angle_interactorstyle", "AngleInteractorStyle.set_widget_repr"),
])
def test_advanced_vtk_labels_green_with_shadow(module_path, attr_chain):
    import importlib

    mod = importlib.import_module(module_path)
    cls_name, meth_name = attr_chain.split(".")
    src = inspect.getsource(getattr(getattr(mod, cls_name), meth_name))
    assert "GetTitleTextProperty" in src
    assert "SetShadow(1)" in src
    assert "SetColor" in src


def test_mpr_measurement_labels_green_with_shadow():
    from modules.mpr.zeta_mpr.mpr_measurement_tools import MPRMeasurementTools

    for meth in ('_activate_ruler_on_view', '_activate_angle_on_view'):
        src = inspect.getsource(getattr(MPRMeasurementTools, meth))
        assert "GetTitleTextProperty" in src, meth
        assert "SetShadow(1)" in src, meth
        assert "tool_color" in src, meth
