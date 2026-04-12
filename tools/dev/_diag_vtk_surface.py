"""
Diagnostic: Verify QtSliceViewer can paint on top of VTKWidget.
Run: .venv\Scripts\python.exe tools/dev/_diag_vtk_surface.py

This creates a REAL VTKWidget (QVTKRenderWindowInteractor) and overlays
a QtSliceViewer child widget, mirroring the exact real-app setup.

Pass = you see a RED rectangle with text "QtSliceViewer VISIBLE"
Fail = you see a black/white/garbage background (VTK surface overwriting)

Press Escape or close the window to exit.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

os.environ.setdefault("QT_API", "pyside6")

from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QColor, QPainter, QFont

app = QApplication.instance() or QApplication(sys.argv)

# ── Step 1: Create QVTKRenderWindowInteractor (real VTK widget) ──
print("[DIAG] Creating QVTKRenderWindowInteractor...", flush=True)
try:
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
    vtk_widget = QVTKRenderWindowInteractor()
    print(f"[DIAG] VTK widget created: {vtk_widget.width()}x{vtk_widget.height()}", flush=True)
    print(f"[DIAG] WA_PaintOnScreen = {vtk_widget.testAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)}", flush=True)
    rw = vtk_widget.GetRenderWindow()
    print(f"[DIAG] VTK render_window size = {rw.GetSize()}", flush=True)
except Exception as e:
    print(f"[DIAG] VTK widget creation failed: {e}", flush=True)
    sys.exit(1)

# ── Step 2: Create QtSliceViewer as child (exactly like real app) ──
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

qt_viewer = QtSliceViewer(parent=vtk_widget)
print(f"[DIAG] QtSliceViewer created as child of VTK widget", flush=True)

# Create a test image (RED with text)
test_img = QImage(512, 512, QImage.Format.Format_RGB32)
test_img.fill(QColor(180, 30, 30))
p = QPainter(test_img)
p.setPen(QColor(255, 255, 255))
p.setFont(QFont("Arial", 24, QFont.Weight.Bold))
p.drawText(test_img.rect(), Qt.AlignmentFlag.AlignCenter, "QtSliceViewer VISIBLE\n\nIf you see this,\nthe fix is working!")
p.end()

# ── Step 3: Show WITHOUT the fix (should fail) ──
print("\n[DIAG] === TEST 1: WITHOUT fix (VTK surface covers child) ===", flush=True)
vtk_widget.setWindowTitle("TEST 1: WITHOUT FIX - Should see black/garbage")
vtk_widget.resize(600, 500)
qt_viewer.setGeometry(vtk_widget.rect())
qt_viewer.set_image(test_img)
qt_viewer.show()
qt_viewer.raise_()
vtk_widget.show()
print(f"[DIAG] VTK WA_PaintOnScreen = {vtk_widget.testAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)}", flush=True)
print(f"[DIAG] VTK rw.GetSize() = {rw.GetSize()}", flush=True)
print(f"[DIAG] QtViewer visible={qt_viewer.isVisible()} geom={qt_viewer.geometry().width()}x{qt_viewer.geometry().height()}", flush=True)

# Process events to let it paint
app.processEvents()
import time; time.sleep(1)
app.processEvents()

# ── Step 4: Apply the fix ──
print("\n[DIAG] === Applying fix: hide VTK render window + clear WA_PaintOnScreen ===", flush=True)
vtk_widget.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, False)
rw.SetSize(0, 0)
try:
    rw.SetShowWindow(False)
except:
    pass

# Re-show qt_viewer
qt_viewer.setGeometry(vtk_widget.rect())
qt_viewer.set_image(test_img)
qt_viewer.show()
qt_viewer.raise_()
vtk_widget.setWindowTitle("TEST 2: WITH FIX - Should see RED with text")
vtk_widget.update()
qt_viewer.update()

print(f"[DIAG] After fix:", flush=True)
print(f"  WA_PaintOnScreen = {vtk_widget.testAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)}", flush=True)
print(f"  VTK rw.GetSize() = {rw.GetSize()}", flush=True)
print(f"  QtViewer visible={qt_viewer.isVisible()} geom={qt_viewer.geometry().width()}x{qt_viewer.geometry().height()}", flush=True)

# ── Step 5: Test scroll ──
print("\n[DIAG] === Testing scroll (changing image) ===", flush=True)
for i in range(3):
    color = QColor(30 + i*60, 180 - i*50, 30 + i*40)
    img = QImage(512, 512, QImage.Format.Format_RGB32)
    img.fill(color)
    p = QPainter(img)
    p.setPen(QColor(255, 255, 255))
    p.setFont(QFont("Arial", 24, QFont.Weight.Bold))
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, f"Slice {i+1}/3\n\nScroll is working!")
    p.end()
    qt_viewer.set_image(img)
    app.processEvents()
    time.sleep(0.3)
    app.processEvents()
    print(f"[DIAG] Rendered slice {i+1} - pixmap_null={qt_viewer._pixmap is None or qt_viewer._pixmap.isNull()}", flush=True)

print("\n[DIAG] === DONE. Window should show colored image with text. ===", flush=True)
print("[DIAG] Close the window or press Ctrl+C to exit.", flush=True)

# Keep window open
try:
    app.exec()
except:
    pass
