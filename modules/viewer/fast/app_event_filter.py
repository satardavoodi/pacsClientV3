"""
Qt Event Filter for application-level input instrumentation.

Instruments mouse, wheel, paint, and timer events at the QApplication level
to measure event delivery jitter and input dispatch latency.
"""

import time
from typing import Optional
from PySide6.QtCore import QObject, QEvent
from PySide6.QtGui import QMouseEvent, QWheelEvent

from modules.viewer.fast import event_loop_diagnostics

# Global reference to the filter instance (singleton)
_app_event_filter: Optional['AIPacsEventFilter'] = None


class AIPacsEventFilter(QObject):
    """Qt event filter for application-level event instrumentation."""
    
    def __init__(self):
        super().__init__()
        self._last_mouse_move_ms: Optional[float] = None
        self._last_wheel_ms: Optional[float] = None
        self._last_paint_ms: Optional[float] = None
        self._last_timer_ms: Optional[float] = None
        self._timer_event_counter: int = 0
    
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Called for every event in the application (G0 instrumentation)."""
        
        try:
            now_ms = time.perf_counter() * 1000.0
            
            # Instrument mouse move events
            if event.type() == QEvent.MouseMove:
                try:
                    me = event
                    if isinstance(me, QMouseEvent):
                        event_loop_diagnostics.record_event(
                            "MouseMove",
                            "app_filter",
                            x=me.position().x(),
                            y=me.position().y(),
                            widget_name=type(obj).__name__
                        )
                        self._last_mouse_move_ms = now_ms
                except Exception:
                    pass
            
            # Instrument wheel events
            elif event.type() == QEvent.Wheel:
                try:
                    we = event
                    if isinstance(we, QWheelEvent):
                        event_loop_diagnostics.record_event(
                            "Wheel",
                            "app_filter",
                            wheel_delta=we.angleDelta().y(),
                            widget_name=type(obj).__name__
                        )
                        self._last_wheel_ms = now_ms
                except Exception:
                    pass
            
            # Instrument paint events
            elif event.type() == QEvent.Paint:
                try:
                    event_loop_diagnostics.record_event(
                        "Paint",
                        "app_filter",
                        widget_name=type(obj).__name__
                    )
                    self._last_paint_ms = now_ms
                except Exception:
                    pass
            
            # Instrument timer events (heartbeat to detect starvation)
            elif event.type() == QEvent.Timer:
                try:
                    # Only record occasionally to avoid spam (every 100th timer event).
                    self._timer_event_counter += 1
                    if (self._timer_event_counter % 100) == 0:
                        event_loop_diagnostics.record_event(
                            "Timer",
                            "app_filter",
                            widget_name="QApplication"
                        )
                        self._last_timer_ms = now_ms
                except Exception:
                    pass
            
            # Instrument update/repaint requests
            elif event.type() == QEvent.UpdateRequest:
                try:
                    event_loop_diagnostics.record_event(
                        "UpdateRequest",
                        "app_filter",
                        widget_name=type(obj).__name__
                    )
                except Exception:
                    pass
        
        except Exception:
            # Silently fail — never crash the event filter
            pass
        
        # Always return False to allow event to propagate
        return False


def install_app_event_filter(qapp) -> None:
    """Install the event filter on the QApplication instance (G0 hook)."""
    global _app_event_filter
    try:
        if _app_event_filter is None:
            _app_event_filter = AIPacsEventFilter()
            qapp.installEventFilter(_app_event_filter)
    except Exception as e:
        import logging
        logging.debug(f"Failed to install app event filter: {e}")


def uninstall_app_event_filter(qapp) -> None:
    """Remove the event filter from QApplication."""
    global _app_event_filter
    try:
        if _app_event_filter is not None:
            qapp.removeEventFilter(_app_event_filter)
            _app_event_filter = None
    except Exception:
        pass
