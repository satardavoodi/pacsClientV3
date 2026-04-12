#!/usr/bin/env python
"""
Standalone visual debugger for FAST mode scroll.

Creates a real window with QtSliceViewer + Lightweight2DPipeline + QtViewerBridge
and wires scroll exactly as the production code does.  Scroll with the mouse wheel
to change slices.  Console prints diagnostic info at every step.

Usage:
    .venv\Scripts\python.exe tools/dev/_debug_fast_scroll.py
"""
import sys, os, time

# ── project root on path ──
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

# ── find a series directory with DICOM files ──
DICOM_BASE = os.path.join(ROOT, "user_data", "patients", "dicom")

def find_series_dir(min_files=20):
    for root, _dirs, files in os.walk(DICOM_BASE):
        dcm = [f for f in files if f.lower().endswith(".dcm")]
        if len(dcm) >= min_files:
            return root, len(dcm)
    return None, 0

series_dir, n_files = find_series_dir()
if series_dir is None:
    print("ERROR: No DICOM series with >=20 files found in", DICOM_BASE)
    sys.exit(1)

print(f"Using series dir: {series_dir}  ({n_files} files)")

# ── Qt app ──
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel, QSlider
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QWheelEvent

app = QApplication(sys.argv)

# ── Pipeline ──
from modules.viewer.fast.lightweight_2d_pipeline import Lightweight2DPipeline, PipelineConfig
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

config = PipelineConfig()
pipeline = Lightweight2DPipeline(config=config)
pipeline.open_series(series_dir)
n_slices = pipeline.slice_count
print(f"Pipeline opened: {n_slices} slices")

if n_slices == 0:
    print("ERROR: Pipeline found 0 slices")
    sys.exit(1)

# ── Main window ──
win = QMainWindow()
win.setWindowTitle(f"FAST Scroll Debug — {n_slices} slices")
win.resize(600, 600)

central = QWidget()
win.setCentralWidget(central)
layout = QVBoxLayout(central)
layout.setContentsMargins(0, 0, 0, 0)

status_label = QLabel("Slice: 0 / 0")
status_label.setStyleSheet("background: #222; color: #0f0; font-size: 16px; padding: 6px;")
layout.addWidget(status_label)

# ── Qt Viewer ──
viewer_container = QWidget()
layout.addWidget(viewer_container, stretch=1)

qt_viewer = QtSliceViewer(parent=viewer_container)

# ── Bridge ──
bridge = QtViewerBridge(
    qt_viewer=qt_viewer,
    pipeline=pipeline,
    metadata={},
    metadata_fixed={},
    vtk_widget=None,  # no VTK widget in this harness
)

# ── Slider (at bottom) ──
slider = QSlider(Qt.Orientation.Horizontal)
slider.setRange(0, max(0, n_slices - 1))
slider.setValue(n_slices // 2)
layout.addWidget(slider)

# ── State ──
current_slice = [n_slices // 2]
scroll_count = [0]

def update_status():
    status_label.setText(
        f"Slice: {current_slice[0]} / {n_slices - 1}   |   Scrolls: {scroll_count[0]}"
    )

def go_to_slice(idx):
    idx = max(0, min(n_slices - 1, idx))
    current_slice[0] = idx
    t0 = time.perf_counter()
    bridge.set_slice(idx)
    dt = (time.perf_counter() - t0) * 1000
    print(f"  => bridge.set_slice({idx}) took {dt:.1f}ms", flush=True)
    update_status()
    slider.blockSignals(True)
    slider.setValue(idx)
    slider.blockSignals(False)

# ── Wire scroll signal from QtSliceViewer ──
# This is the PRODUCTION signal path
def on_scroll_requested(delta):
    scroll_count[0] += 1
    new_idx = current_slice[0] + delta
    print(f"[SCROLL] delta={delta}  {current_slice[0]} -> {new_idx}  (scroll #{scroll_count[0]})", flush=True)
    go_to_slice(new_idx)

# Disconnect bridge's built-in handler (it tries to use vtk_widget.slider)
try:
    qt_viewer.slice_scroll_requested.disconnect(bridge._on_qt_scroll)
    print("Disconnected bridge._on_qt_scroll from signal")
except Exception:
    print("Note: bridge._on_qt_scroll was not connected")

# Connect our handler
qt_viewer.slice_scroll_requested.connect(on_scroll_requested)

# Also wire slider drag
def on_slider_changed(val):
    if val != current_slice[0]:
        print(f"[SLIDER] {current_slice[0]} -> {val}", flush=True)
        go_to_slice(val)

slider.valueChanged.connect(on_slider_changed)

# ── Layout the viewer inside its container ──
def resize_viewer():
    qt_viewer.setGeometry(viewer_container.rect())

viewer_container.resizeEvent = lambda e: resize_viewer()

# ── Initial render ──
mid = n_slices // 2
print(f"Rendering initial slice {mid}...")
go_to_slice(mid)
bridge.apply_default_window_level(mid)

# Force the viewer visible
qt_viewer.show()
qt_viewer.raise_()

print(f"\n{'='*60}")
print(f"READY — Scroll mouse wheel over the image to change slices.")
print(f"Watch this console for diagnostic output.")
print(f"{'='*60}\n")

win.show()

# ── Run event loop ──
sys.exit(app.exec())
