"""
Real DICOM Scroll Test — uses the actual Lightweight2DPipeline + QtSliceViewer
with real DICOM files, parented inside a QVTKRenderWindowInteractor.

This reproduces the exact same widget hierarchy as the real app:
  QVTKRenderWindowInteractor (VTKWidget parent)
    └── QtSliceViewer (child, painted via QPainter)

Run:  .venv\\Scripts\\python.exe tools/dev/_test_real_dicom_scroll.py

What to look for:
  - If you see DICOM images and can scroll → fix is working
  - If you see a black screen → VTK surface is covering the child
  - Console output traces every step
"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
os.environ.setdefault("QT_API", "pyside6")
# Force software GL so we match the real FAST-mode environment
os.environ.setdefault("QT_OPENGL", "software")

from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel, QSlider
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

app = QApplication.instance() or QApplication(sys.argv)

# ── Find a series with .dcm files ──
DICOM_BASE = Path(r"c:\AI-Pacs codes\aipacs-pydicom2d\user_data\patients\dicom")
series_path = None
for study_dir in sorted(DICOM_BASE.iterdir()):
    if not study_dir.is_dir():
        continue
    for ser_dir in sorted(study_dir.iterdir()):
        if not ser_dir.is_dir():
            continue
        dcm_count = sum(1 for f in ser_dir.iterdir() if f.suffix.lower() == ".dcm")
        if dcm_count >= 10:
            series_path = ser_dir
            print(f"[TEST] Using series: {ser_dir} ({dcm_count} .dcm files)")
            break
    if series_path:
        break

if not series_path:
    print("[TEST] ERROR: No series with >=10 .dcm files found!")
    sys.exit(1)

# ── Create the pipeline (same as real app) ──
from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

config = PipelineConfig()
pipeline = Lightweight2DPipeline(config=config)
pipeline.open_series(str(series_path))
n_slices = pipeline.slice_count
print(f"[TEST] Pipeline opened: {n_slices} slices")

if n_slices == 0:
    print("[TEST] ERROR: Pipeline has 0 slices!")
    sys.exit(1)

# ── Test 1: Standalone QtSliceViewer (no VTK parent) ──
print("\n[TEST] === TEST 1: Standalone QtSliceViewer (no VTK parent) ===")
standalone = QtSliceViewer()
standalone.setWindowTitle(f"TEST 1: Standalone - {n_slices} slices")
standalone.resize(600, 500)

# Render mid slice
mid = n_slices // 2
ww, wc = pipeline.get_default_window_level(mid)
pipeline.set_window_level(ww, wc)
frame = pipeline.get_rendered_frame(mid)
standalone.set_image(frame.qimage)
standalone.show()
app.processEvents()
print(f"[TEST] Standalone: rendered slice {mid}, qimage_null={frame.qimage.isNull()}, vis={standalone.isVisible()}")

# Test scroll
for i in range(5):
    idx = mid + i
    if idx >= n_slices:
        break
    frame = pipeline.get_rendered_frame(idx)
    standalone.set_image(frame.qimage)
    app.processEvents()
print(f"[TEST] Standalone scroll: OK (5 slices rendered)")

# ── Test 2: QtSliceViewer as child of QVTKRenderWindowInteractor ──
print("\n[TEST] === TEST 2: QtSliceViewer as child of VTK widget (SAME AS REAL APP) ===")
try:
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
    vtk_parent = QVTKRenderWindowInteractor()
    print(f"[TEST] VTK widget created")
    print(f"[TEST]   WA_PaintOnScreen = {vtk_parent.testAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)}")
    print(f"[TEST]   WA_OpaquePaintEvent = {vtk_parent.testAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)}")
    rw = vtk_parent.GetRenderWindow()
    print(f"[TEST]   VTK render_window.GetSize() = {rw.GetSize()}")
except Exception as e:
    print(f"[TEST] VTK widget creation failed: {e}")
    sys.exit(1)

# Create QtSliceViewer as child (exactly like _create_qt_viewer_bridge)
qt_viewer = QtSliceViewer(parent=vtk_parent)
vtk_parent.resize(600, 500)
qt_viewer.setGeometry(vtk_parent.rect())

# === BEFORE FIX: Try to render ===
print("\n[TEST] --- Before fix (VTK surface active) ---")
frame = pipeline.get_rendered_frame(mid)
qt_viewer.set_image(frame.qimage)
qt_viewer.show()
qt_viewer.raise_()
vtk_parent.setWindowTitle("TEST 2a: BEFORE fix - likely black/broken")
vtk_parent.show()
app.processEvents()
time.sleep(0.5)
app.processEvents()

# Check if QPainter works
print(f"[TEST]   qt_viewer visible={qt_viewer.isVisible()}")
print(f"[TEST]   qt_viewer size={qt_viewer.width()}x{qt_viewer.height()}")
print(f"[TEST]   VTK rw.GetSize() = {rw.GetSize()}")

# === APPLY FIX: Hide VTK render window ===
print("\n[TEST] --- Applying fix: hide VTK native surface ---")
vtk_parent.setAttribute(Qt.WidgetAttribute.WA_PaintOnScreen, False)
rw.SetSize(0, 0)
if hasattr(rw, 'SetShowWindow'):
    rw.SetShowWindow(False)

# Must re-create qt_viewer as a standalone window (not child of VTK)
# because WA_PaintOnScreen poisons the entire widget tree
qt_viewer.hide()
qt_viewer.setParent(None)
qt_viewer.deleteLater()

print(f"[TEST]   WA_PaintOnScreen now = {vtk_parent.testAttribute(Qt.WidgetAttribute.WA_PaintOnScreen)}")
print(f"[TEST]   VTK rw.GetSize() now = {rw.GetSize()}")

# Try re-creating as child after WA_PaintOnScreen is cleared
qt_viewer2 = QtSliceViewer(parent=vtk_parent)
qt_viewer2.setGeometry(vtk_parent.rect())
frame = pipeline.get_rendered_frame(mid)
qt_viewer2.set_image(frame.qimage)
qt_viewer2.show()
qt_viewer2.raise_()
vtk_parent.setWindowTitle(f"TEST 2b: AFTER fix - {n_slices} slices - scroll me!")
vtk_parent.update()
app.processEvents()
time.sleep(0.3)
app.processEvents()
print(f"[TEST]   qt_viewer2 visible={qt_viewer2.isVisible()} size={qt_viewer2.width()}x{qt_viewer2.height()}")

# === TEST SCROLL ===
print("\n[TEST] --- Testing scroll (10 slices) ---")
ok = 0
for i in range(10):
    idx = mid + i
    if idx >= n_slices:
        idx = n_slices - 1 - i
    frame = pipeline.get_rendered_frame(idx)
    qt_viewer2.set_image(frame.qimage)
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    ok += 1
print(f"[TEST] Scroll test: {ok}/10 slices rendered")

# === TEST 3: Use a plain QWidget as parent instead ===
print("\n[TEST] === TEST 3: QtSliceViewer as child of plain QWidget ===")
plain_parent = QWidget()
plain_parent.resize(600, 500)
plain_parent.setWindowTitle(f"TEST 3: Plain QWidget parent - {n_slices} slices")
qt_viewer3 = QtSliceViewer(parent=plain_parent)
qt_viewer3.setGeometry(plain_parent.rect())
frame = pipeline.get_rendered_frame(mid)
qt_viewer3.set_image(frame.qimage)
qt_viewer3.show()
plain_parent.show()
app.processEvents()
time.sleep(0.3)
app.processEvents()
print(f"[TEST]   qt_viewer3 visible={qt_viewer3.isVisible()} size={qt_viewer3.width()}x{qt_viewer3.height()}")

# Scroll test
ok = 0
for i in range(10):
    idx = mid + i
    if idx >= n_slices:
        idx = n_slices - 1 - i
    frame = pipeline.get_rendered_frame(idx)
    qt_viewer3.set_image(frame.qimage)
    app.processEvents()
    time.sleep(0.05)
    app.processEvents()
    ok += 1
print(f"[TEST] Scroll test: {ok}/10 slices rendered")

# === Summary ===
print("\n" + "="*60)
print("[TEST] SUMMARY")
print("="*60)
print("  TEST 1 (Standalone): Should show DICOM image")
print("  TEST 2a (VTK child, before fix): Likely BLACK/broken")
print("  TEST 2b (VTK child, after fix): Should show DICOM image")  
print("  TEST 3 (Plain QWidget child): Should show DICOM image")
print()
print("  Look at the windows and report which ones show images!")
print("  Close windows or Ctrl+C to exit.")
print("="*60)

try:
    app.exec()
except KeyboardInterrupt:
    pass
