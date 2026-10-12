"""Late settle work must not render a closed series or retired bridge."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge


def bridge(*, retired=False, count=1):
    frame = SimpleNamespace(qimage=None, window_width=100, window_center=50,
                            decode_ms=0, filter_ms=0, wl_ms=0)
    pipeline = SimpleNamespace(slice_count=count, set_fast_interaction=Mock(),
        get_rendered_frame=Mock(side_effect=IndexError('No series loaded') if not count else None,
                                return_value=frame))
    return SimpleNamespace(_retired=retired, pipeline=pipeline, _current_slice=0,
        qt_viewer=Mock(), _force_present_pending_on_settle=Mock(),
        _set_thumbnail_scroll_active=Mock(), _resume_booster=Mock(),
        _update_annotations=Mock(), _stack_scheduler=Mock(),
        _fast_clock_enabled=Mock(return_value=True), end_fast_interaction=Mock())


@pytest.mark.parametrize('retired,count', [(False, 0), (True, 0), (True, 1)])
def test_end_interaction_rejects_inactive_owner_before_any_work(retired, count):
    state = bridge(retired=retired, count=count)
    QtViewerBridge.end_fast_interaction(state)
    state.pipeline.get_rendered_frame.assert_not_called()
    state._force_present_pending_on_settle.assert_not_called()
    state._resume_booster.assert_not_called()
    state.qt_viewer.set_image.assert_not_called()


@pytest.mark.parametrize('retired,count', [(False, 0), (True, 1)])
def test_queued_settle_cannot_resume_retired_series(retired, count):
    state = bridge(retired=retired, count=count)
    QtViewerBridge._on_interaction_settled(state)
    state.end_fast_interaction.assert_not_called()
    state._force_present_pending_on_settle.assert_not_called()


def test_live_interaction_still_presents_exact_final_slice():
    state = bridge()
    QtViewerBridge.end_fast_interaction(state)
    state.pipeline.get_rendered_frame.assert_called_once_with(0)
    state.qt_viewer.set_image.assert_called_once()
    state._update_annotations.assert_called_once_with(0, 100, 50)


def test_cleanup_retires_admission_before_pipeline_shutdown():
    state = bridge()
    state._interaction_settle_timer = Mock()
    state._fast_render_clock_timer = Mock()
    state.pipeline.shutdown = Mock(side_effect=lambda: QtViewerBridge._on_interaction_settled(state))
    QtViewerBridge.cleanup(state)
    state.end_fast_interaction.assert_not_called()
    state.pipeline.get_rendered_frame.assert_not_called()
    state._interaction_settle_timer.stop.assert_called_once()


def test_queued_qt_callback_after_cleanup_cannot_render_replacement():
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    state = bridge()
    QTimer.singleShot(0, lambda: QtViewerBridge._on_interaction_settled(state))
    QtViewerBridge.cleanup(state)
    # A shared pipeline becoming nonempty again must not revive an old bridge.
    state.pipeline.slice_count = 3
    app.processEvents()
    state.end_fast_interaction.assert_not_called()
    state.pipeline.get_rendered_frame.assert_not_called()
