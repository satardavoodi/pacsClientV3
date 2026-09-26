"""Mouse affordances for native radiograph correction, without patient data."""
import pytest
from PySide6.QtCore import Qt, QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from modules.ai_imaging.eagle_eye_alignment.widget import AlignmentCanvas, LandmarkItem
from modules.ai_imaging.eagle_eye_total_spine.editing import SegmentEndpoint

@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])

@pytest.mark.parametrize('kind', [LandmarkItem, SegmentEndpoint])
def test_handle_exposes_drag_target_without_moving(app, kind):
    view = AlignmentCanvas()
    item = kind('R', 'hip', [50, 60], '#38bdf8', view)
    view.scene().addItem(item)
    assert item.acceptHoverEvents()
    assert item.cursor().shape() == Qt.OpenHandCursor
    assert item.shape().contains(QPointF(7, 0))
    assert item.pos() == QPointF(50, 60)
    view.close()

def test_placement_cursor_and_mode_change_restore_pan(app):
    view = AlignmentCanvas()
    view.manual_target = ('R', 'hip')
    assert view.viewport().cursor().shape() == Qt.CrossCursor
    view.manual_target = None
    assert view.manual_target is None
    assert view.viewport().cursor().shape() == Qt.OpenHandCursor
    view.close()

@pytest.mark.parametrize('kind', [LandmarkItem, SegmentEndpoint])
@pytest.mark.parametrize('placement', [False, True])
def test_held_handle_uses_move_cursor_until_release(app, kind, placement):
    view = AlignmentCanvas()
    view.resize(300, 300)
    view.scene().setSceneRect(0, 0, 200, 200)
    if placement:
        view.manual_target = ('R', 'hip')
    item = kind('R', 'hip', [50, 60], '#38bdf8', view)
    view.scene().addItem(item)
    view.show()
    app.processEvents()
    start = view.mapFromScene(item.pos())
    changes = []
    view.pointChanged.connect(lambda *args: changes.append(args))
    try:
        QTest.mouseMove(view.viewport(), start)
        QTest.mousePress(view.viewport(), Qt.LeftButton, pos=start)
        assert view.scene().mouseGrabberItem() is item
        assert item.cursor().shape() == Qt.SizeAllCursor
        assert view.viewport().cursor().shape() == Qt.SizeAllCursor
        end = view.mapFromScene(QPointF(70, 80))
        QTest.mouseMove(view.viewport(), end)
        assert view.viewport().cursor().shape() == Qt.SizeAllCursor
        QTest.mouseRelease(view.viewport(), Qt.LeftButton, pos=end)
        assert item.pos() == QPointF(70, 80)
        assert item.cursor().shape() == Qt.OpenHandCursor
        assert view.viewport().cursor().shape() == Qt.OpenHandCursor
        assert len(changes) == 1
    finally:
        view.close()
