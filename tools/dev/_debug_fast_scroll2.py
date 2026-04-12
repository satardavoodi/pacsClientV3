"""
Non-interactive FAST scroll chain test.

Creates real Qt viewer + pipeline + bridge, programmatically simulates
scrolling, and checks at every stage whether the image actually changes.

Usage:
    .venv\\Scripts\\python.exe tools/dev/_debug_fast_scroll2.py
"""
import sys, os, time, hashlib

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# Find DICOM series
DICOM_BASE = os.path.join(ROOT, "user_data", "patients", "dicom")
series_dir = None
for root, _dirs, files in os.walk(DICOM_BASE):
    dcm = [f for f in files if f.lower().endswith(".dcm")]
    if len(dcm) >= 20:
        series_dir = root
        n_files = len(dcm)
        break

if series_dir is None:
    print("ERROR: No DICOM series found")
    sys.exit(1)

print(f"Series: {series_dir}  ({n_files} files)")

# Must create QApplication before any Qt widgets
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QWheelEvent, QImage

app = QApplication.instance() or QApplication(sys.argv)

from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

print("\n=== TEST 1: Pipeline renders different images per slice ===")
config = PipelineConfig()
pipeline = Lightweight2DPipeline(config=config)
pipeline.open_series(series_dir)
n_slices = pipeline.slice_count
print(f"  Slices: {n_slices}")

hashes = {}
for idx in [0, n_slices // 4, n_slices // 2, 3 * n_slices // 4, n_slices - 1]:
    frame = pipeline.get_rendered_frame(idx)
    if frame.qimage is None or frame.qimage.isNull():
        print(f"  Slice {idx}: NULL IMAGE")
        continue
    bits = frame.qimage.bits()
    if bits is None:
        # Try constBits
        bits = frame.qimage.constBits()
    if bits is None:
        print(f"  Slice {idx}: Cannot access bits")
        continue
    # Calculate hash by converting bytes
    data = bytes(bits)
    h = hashlib.md5(data).hexdigest()[:12]
    hashes[idx] = h
    print(f"  Slice {idx}: {frame.width}x{frame.height} hash={h}")

unique_hashes = set(hashes.values())
if len(unique_hashes) > 1:
    print(f"  PASS: {len(unique_hashes)} unique images")
else:
    print(f"  FAIL: All slices produce identical image!")

print("\n=== TEST 2: QtSliceViewer + Bridge creation ===")
parent_widget = QWidget()
parent_widget.resize(512, 512)

qt_viewer = QtSliceViewer(parent=parent_widget)
qt_viewer.setGeometry(0, 0, 512, 512)
qt_viewer.show()

bridge = QtViewerBridge(
    qt_viewer=qt_viewer,
    pipeline=pipeline,
    metadata={},
    metadata_fixed={},
    vtk_widget=None,
)

print(f"  Bridge created: slices={bridge.get_count_of_slices()}")
print(f"  QtViewer visible={qt_viewer.isVisible()} size={qt_viewer.width()}x{qt_viewer.height()}")

print("\n=== TEST 3: bridge.set_slice changes the displayed image ===")
pixmap_hashes = {}
for idx in [0, n_slices // 2, n_slices - 1]:
    bridge.set_slice(idx)
    app.processEvents()  # Let Qt process the update()
    
    pix = qt_viewer._pixmap
    if pix is None or pix.isNull():
        print(f"  Slice {idx}: PIXMAP IS NULL")
        continue
    
    # Convert pixmap to image for hash
    img = pix.toImage()
    bits = bytes(img.constBits())
    h = hashlib.md5(bits).hexdigest()[:12]
    pixmap_hashes[idx] = h
    print(f"  Slice {idx}: pixmap {pix.width()}x{pix.height()} hash={h}")

unique_pix = set(pixmap_hashes.values())
if len(unique_pix) > 1:
    print(f"  PASS: {len(unique_pix)} unique pixmaps")
else:
    print(f"  FAIL: All slices produce identical pixmap!")

print("\n=== TEST 4: Simulated wheel scroll ===")
# Simulate the exact production path:
# QtSliceViewer.wheelEvent → slice_scroll_requested signal → handler → bridge.set_slice

# Disconnect bridge's built-in _on_qt_scroll if connected
try:
    qt_viewer.slice_scroll_requested.disconnect(bridge._on_qt_scroll)
except Exception:
    pass

scroll_received = []

def test_scroll_handler(delta):
    scroll_received.append(delta)

qt_viewer.slice_scroll_requested.connect(test_scroll_handler)

# Start at middle
mid = n_slices // 2
bridge.set_slice(mid)
app.processEvents()

# Simulate 5 wheel-down events
print(f"  Starting at slice {mid}, sending 5 wheel-down events...")
from PySide6.QtCore import QPoint
for i in range(5):
    # angleDelta.y() = -120 means scroll down = next slice
    evt = QWheelEvent(
        QPointF(256, 256),       # pos
        QPointF(256, 256),       # globalPos
        QPoint(0, 0),            # pixelDelta
        QPoint(0, -120),         # angleDelta (negative = scroll down)
        Qt.MouseButton.NoButton, # buttons
        Qt.KeyboardModifier.NoModifier,  # modifiers
        Qt.ScrollPhase.NoScrollPhase,
        False,                   # inverted
    )
    qt_viewer.wheelEvent(evt)
    app.processEvents()

print(f"  scroll_received signals: {scroll_received}")
print(f"  Expected: 5 signals with delta=1 (scroll down)")

if len(scroll_received) == 5:
    print(f"  PASS: All 5 scroll signals received")
else:
    print(f"  FAIL: Expected 5 signals, got {len(scroll_received)}")

print("\n=== TEST 5: Full production chain - scroll updates image ===")
# Now wire the scroll signal to actually render via bridge
try:
    qt_viewer.slice_scroll_requested.disconnect(test_scroll_handler)
except Exception:
    pass

current_idx = [mid]
render_calls = []

def production_scroll_handler(delta):
    new_idx = max(0, min(n_slices - 1, current_idx[0] + delta))
    old_idx = current_idx[0]
    current_idx[0] = new_idx
    bridge.set_slice(new_idx)
    # Check what pixmap we have now
    pix = qt_viewer._pixmap
    h = "null"
    if pix and not pix.isNull():
        img = pix.toImage()
        data = bytes(img.constBits())
        h = hashlib.md5(data).hexdigest()[:12]
    render_calls.append((old_idx, new_idx, h))
    print(f"    scroll delta={delta}: slice {old_idx}->{new_idx} pixmap_hash={h}")

qt_viewer.slice_scroll_requested.connect(production_scroll_handler)

# Reset to middle
bridge.set_slice(mid)
current_idx[0] = mid
app.processEvents()

# Get baseline pixmap hash
pix0 = qt_viewer._pixmap
baseline_h = "null"
if pix0 and not pix0.isNull():
    baseline_h = hashlib.md5(bytes(pix0.toImage().constBits())).hexdigest()[:12]
print(f"  Baseline slice {mid}: hash={baseline_h}")

# Send 3 scroll-down events
for i in range(3):
    evt = QWheelEvent(
        QPointF(256, 256), QPointF(256, 256),
        QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    qt_viewer.wheelEvent(evt)
    app.processEvents()

all_hashes = [baseline_h] + [r[2] for r in render_calls]
unique = set(all_hashes)
print(f"  All hashes: {all_hashes}")
if len(unique) > 1:
    print(f"  PASS: Image changes across scrolls ({len(unique)} unique)")
else:
    print(f"  FAIL: Image stays the same across scrolls!")

print("\n=== TEST 6: Full chain WITH VTKWidget (mock slider) ===")
# This emulates what happens in the actual app more closely
from PySide6.QtWidgets import QSlider

# Create a mock vtk_widget-like object
class MockVTKWidget:
    def __init__(self):
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, n_slices - 1)
        self.slider.setValue(mid)
        self._qt_bridge_active = True
        self._on_slice_changed_cb = None
        self.image_viewer = None
        self._in_wheel_scroll = False
        self._in_stack_scroll = False
        self._last_lock_sync_ms = 0.0

mock_vtk = MockVTKWidget()

# Create fresh pipeline/bridge/viewer for this test
pipeline2 = Lightweight2DPipeline(config=PipelineConfig())
pipeline2.open_series(series_dir)

parent2 = QWidget()
parent2.resize(512, 512)
qt_viewer2 = QtSliceViewer(parent=parent2)
qt_viewer2.setGeometry(0, 0, 512, 512)
qt_viewer2.show()

bridge2 = QtViewerBridge(
    qt_viewer=qt_viewer2,
    pipeline=pipeline2,
    metadata={},
    metadata_fixed={},
    vtk_widget=mock_vtk,
)
mock_vtk.image_viewer = bridge2

# Wire slider.valueChanged like PatientWidget does
def on_slider_value_changed(val):
    print(f"    [on_slider_value_changed] val={val} qt_bridge={mock_vtk._qt_bridge_active}")
    # This is what PatientWidget.on_slider_value_changed does:
    bridge2.set_slice(val)

mock_vtk.slider.valueChanged.connect(on_slider_value_changed)

# Initial render
bridge2.set_slice(mid)
bridge2.apply_default_window_level(mid)
app.processEvents()

pix_base = qt_viewer2._pixmap
base_h2 = "null"
if pix_base and not pix_base.isNull():
    base_h2 = hashlib.md5(bytes(pix_base.toImage().constBits())).hexdigest()[:12]
print(f"  Baseline slice {mid}: hash={base_h2}")
print(f"  Slider value: {mock_vtk.slider.value()}")

# Now simulate scroll via the PRODUCTION signal chain
print(f"  Scrolling 3 times via wheelEvent (production chain)...")
scroll_results2 = []
for i in range(3):
    evt = QWheelEvent(
        QPointF(256, 256), QPointF(256, 256),
        QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    qt_viewer2.wheelEvent(evt)
    app.processEvents()
    
    pix = qt_viewer2._pixmap
    h = "null"
    if pix and not pix.isNull():
        h = hashlib.md5(bytes(pix.toImage().constBits())).hexdigest()[:12]
    sv = mock_vtk.slider.value()
    scroll_results2.append((sv, h))
    print(f"    After scroll {i+1}: slider={sv} hash={h}")

all_h2 = [base_h2] + [r[1] for r in scroll_results2]
unique2 = set(all_h2)
if len(unique2) > 1:
    print(f"  PASS: Image changes ({len(unique2)} unique)")
else:
    print(f"  FAIL: Image stays the same!")

print(f"\n{'='*60}")
print("TEST SUMMARY")
print(f"{'='*60}")
print("If all tests PASS here but scroll is broken in the app,")
print("the problem is in the VTKWidget/PatientWidget wiring layer,")
print("not in the rendering pipeline or Qt viewer itself.")
