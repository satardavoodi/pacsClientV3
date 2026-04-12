"""
Definitive test: Does VTKWidget.wheelEvent get called by Qt dispatch?

This test creates a REAL VTKWidget instance (the actual split class)
and sends a wheel event to verify the full dispatch chain works.
"""
import sys
import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QPointF, QPoint, Qt
from PySide6.QtGui import QWheelEvent

app = QApplication.instance() or QApplication(sys.argv)

# Import the REAL VTKWidget used at runtime
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget

print(f"VTKWidget class: {VTKWidget}")
print(f"VTKWidget.__module__: {VTKWidget.__module__}")
print(f"VTKWidget MRO:")
for i, cls in enumerate(VTKWidget.__mro__):
    has_wheel = "wheelEvent" in cls.__dict__
    print(f"  [{i}] {cls.__module__}.{cls.__qualname__}" + (" [wheelEvent]" if has_wheel else ""))

print()

# Create a REAL VTKWidget
w = VTKWidget(parent=None, height_viewer=480, patient_widget=None)
print(f"Instance type: {type(w)}")
print(f"Instance class wheelEvent: {type(w).wheelEvent}")
print(f"'wheelEvent' in type(w).__dict__: {'wheelEvent' in type(w).__dict__}")

# Patch to detect call
_original_wheel = w.__class__.wheelEvent
_mixin_called = [False]
_widget_called = [False]

# Check if the INSTANCE or the CLASS method is called
class WheelTracker:
    pass

tracker = WheelTracker()
tracker.widget_event_called = False
tracker.mixin_wheel_called = False

# Override event() at instance level
_orig_event = w.event
def _traced_event(evt):
    if evt.type() == 31:  # Wheel
        tracker.widget_event_called = True
        print(f"  [TRACE] VTKWidget.event() received Wheel event")
    return _orig_event(evt)
w.event = _traced_event

# Send wheel event
evt = QWheelEvent(
    QPointF(50, 50), QPointF(50, 50),
    QPoint(0, 0), QPoint(0, 120),
    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False
)
print("\nSending wheelEvent via QApplication.sendEvent()...")
result = QApplication.sendEvent(w, evt)
print(f"  sendEvent returned: {result}")
print(f"  event() received Wheel: {tracker.widget_event_called}")

# Also check direct call
print("\nDirect call to w.wheelEvent()...")
evt2 = QWheelEvent(
    QPointF(50, 50), QPointF(50, 50),
    QPoint(0, 0), QPoint(0, 120),
    Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False
)
w.wheelEvent(evt2)

# Check if the spinner is blocking
print(f"\n=== Spinner state ===")
sp = w.viewport_spinner
print(f"  spinner object: {sp}")
print(f"  spinner.spinner: {sp.spinner}")
if sp.spinner:
    print(f"  spinner visible: {sp.spinner.isVisible()}")
    print(f"  spinner parent: {sp.spinner.parent()}")
    print(f"  spinner geometry: {sp.spinner.geometry()}")
else:
    print("  (No spinner widget created yet)")

# Check widget visibility state
print(f"\n=== Widget state ===")
print(f"  isVisible: {w.isVisible()}")
print(f"  isEnabled: {w.isEnabled()}")
print(f"  updatesEnabled: {w.updatesEnabled()}")
print(f"  focusPolicy: {w.focusPolicy()}")
print(f"  acceptDrops: {w.acceptDrops()}")

# Check for any event filters
print(f"\n=== Event filters ===")
# There's no public API to list event filters, but we can check known ones
print(f"  spinner has eventFilter for parent: {sp.spinner is not None}")

app.quit()
print("\n=== TEST COMPLETE ===")
