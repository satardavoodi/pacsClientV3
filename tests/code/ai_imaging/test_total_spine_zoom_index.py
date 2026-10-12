"""Synthetic scene-index guards for zoomable reader correction targets."""
import pytest
from test_eagle_eye_total_spine import qapp


@pytest.mark.parametrize('kind', ['endplate', 'region'])
@pytest.mark.parametrize('operation', ['scale', 'transform', 'fit'])
def test_zoom_hit_shape_agrees_with_scene_index(qapp, kind, operation):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QTransform
    from modules.ai_imaging.eagle_eye_total_spine.widget import SpineCanvas
    from modules.ai_imaging.eagle_eye_total_spine.editing import (
        EditableSegment, SegmentEndpoint, CandidateBody)

    canvas = SpineCanvas()
    canvas.resize(600, 800)
    canvas.setSceneRect(0, 0, 500, 1000)
    canvas.scene().setBspTreeDepth(8)
    if kind == 'endplate':
        handles = [SegmentEndpoint('L4', key, point, '#ffffff', canvas)
                   for key, point in [('superior_left', (100, 100)),
                                      ('superior_right', (200, 100))]]
        item = EditableSegment('L4', 'superior', handles, '#ffffff', canvas)
    else:
        handles = []
        item = CandidateBody(0, [[100, 100], [200, 100], [100, 200], [200, 200]],
                             canvas, region=True)
    canvas.scene().addItem(item)
    canvas.show()
    qapp.processEvents()
    # Force the spatial index to record the original bounds before zooming.
    assert item in canvas.scene().items(QPointF(150, 100))
    if operation == 'scale':
        canvas.scale(.1, .1)
    elif operation == 'transform':
        canvas.setTransform(QTransform.fromScale(.1, .1))
    else:
        canvas.fitInView(QRectF(0, 0, 5000, 10000), Qt.KeepAspectRatio)
    offset = (5 if kind == 'endplate' else 4) / abs(canvas.transform().m11())
    point = QPointF(150, 100 + offset)
    assert item.shape().contains(point)
    assert item in canvas.scene().items(point), 'Zoom left stale item bounds in the scene index'
    # Zooming back must also shrink the hit target correctly.
    canvas.resetTransform()
    qapp.processEvents()
    assert not item.shape().contains(point)
    assert item not in canvas.scene().items(point)
    canvas.scene().removeItem(item)
    canvas.close()


def test_wheel_tooltip_and_rebuilt_items_survive_collection(qapp):
    import gc
    from PySide6.QtCore import QPoint, QPointF, QEvent, Qt
    from PySide6.QtGui import QWheelEvent, QHelpEvent
    from PySide6.QtWidgets import QApplication
    from test_eagle_eye_total_spine import view
    from modules.ai_imaging.eagle_eye_total_spine.widget import ProjectionEditor

    editor = ProjectionEditor('coronal')
    editor.resize(1400, 850)
    editor.show()
    data = view()
    editor.accept_image(data['image'])
    editor.points = data['points']
    editor.curves = data['curves']
    canvas = editor.canvas
    for iteration in range(40):
        canvas.set_points(editor.points)
        editor.recalculate()
        canvas.fit()
        qapp.processEvents()
        position = canvas.mapFromScene(QPointF(240, 150))
        global_position = canvas.viewport().mapToGlobal(position)
        for delta in (-120, 120):
            wheel = QWheelEvent(QPointF(position), QPointF(global_position), QPoint(),
                                QPoint(0, delta), Qt.NoButton, Qt.NoModifier,
                                Qt.NoScrollPhase, False)
            QApplication.sendEvent(canvas.viewport(), wheel)
            QApplication.sendEvent(canvas.viewport(), QHelpEvent(
                QEvent.ToolTip, position, global_position))
            gc.collect()
            qapp.processEvents()
        assert canvas.scene().items()
    editor.clear_image()
    qapp.processEvents()
    assert not canvas.scene().items()
    editor.close()


@pytest.mark.parametrize('kind', ['endplate', 'region'])
def test_item_bounds_do_not_change_when_only_the_view_transform_changes(qapp, kind):
    from PySide6.QtWidgets import QGraphicsView
    from modules.ai_imaging.eagle_eye_total_spine.widget import SpineCanvas
    from modules.ai_imaging.eagle_eye_total_spine.editing import (
        EditableSegment, SegmentEndpoint, CandidateBody)
    canvas = SpineCanvas()
    handles = [SegmentEndpoint('L4', key, point, '#ffffff', canvas)
               for key, point in [('superior_left', (100, 100)),
                                  ('superior_right', (200, 100))]]
    item = (EditableSegment('L4', 'superior', handles, '#ffffff', canvas)
            if kind == 'endplate' else CandidateBody(
                0, [[100, 100], [200, 100], [100, 200], [200, 200]], canvas, region=True))
    canvas.scene().addItem(item)
    bounds = item.boundingRect()
    shape = item.shape()
    # C++ view operations cannot implicitly mutate scene-local item geometry.
    # The canvas must explicitly notify Qt before adjusting a hit target.
    QGraphicsView.scale(canvas, .1, .1)
    assert item.boundingRect() == bounds
    assert item.shape() == shape
    canvas.scene().removeItem(item)
    canvas.close()
