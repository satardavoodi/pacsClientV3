"""
Automated FAST-scroll diagnostic.
Opens a real DICOM series and programmatically scrolls, checking if the
QtSliceViewer pixmap actually changes between slices.

Tests 3 configurations:
  A) Bare pipeline + QtSliceViewer (no bridge)
  B) Pipeline + Bridge + QtSliceViewer
  C) QVTKRenderWindowInteractor parent + Bridge + QtSliceViewer (production layout)

Run:  .venv\Scripts\python.exe tools/dev/_auto_scroll_test.py
"""
import sys, os, time
os.environ["QT_QPA_PLATFORM"] = "offscreen"  # headless

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap

app = QApplication(sys.argv)

from modules.viewer.fast.lightweight_2d_pipeline import (
    Lightweight2DPipeline, PipelineConfig,
)
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer
from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

# -- find DICOM series --
DICOM_DIR = os.path.join(ROOT, "user_data", "patients", "dicom")

def find_series(min_slices=20):
    for study in os.listdir(DICOM_DIR):
        sp = os.path.join(DICOM_DIR, study)
        if not os.path.isdir(sp):
            continue
        for series in os.listdir(sp):
            ssp = os.path.join(sp, series)
            if not os.path.isdir(ssp):
                continue
            n = len([f for f in os.listdir(ssp) if f.endswith('.dcm')])
            if n >= min_slices:
                return ssp, n
    return None, 0

series_path, n_files = find_series()
assert series_path, "No DICOM series found"
print(f"Series: {series_path} ({n_files} files)\n")


def pixmap_checksum(viewer):
    """Get a content hash of the viewer's current pixmap."""
    pix = viewer._pixmap
    if pix is None or pix.isNull():
        return "NULL"
    img = pix.toImage()
    # Sample some pixel values as a quick checksum
    w, h = img.width(), img.height()
    vals = []
    for y_frac in [0.25, 0.5, 0.75]:
        for x_frac in [0.25, 0.5, 0.75]:
            vals.append(img.pixel(int(w * x_frac), int(h * y_frac)))
    return hash(tuple(vals))


def test_bare():
    """Test A: pipeline → set_image directly (no bridge)."""
    print("=" * 60)
    print("TEST A: bare pipeline + QtSliceViewer (no bridge)")
    print("=" * 60)
    
    pipeline = Lightweight2DPipeline(config=PipelineConfig())
    pipeline.open_series(series_path)
    n = pipeline.slice_count
    print(f"  Slices: {n}")
    
    viewer = QtSliceViewer()
    viewer.resize(512, 512)
    viewer.show()
    
    checksums = []
    test_indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
    for idx in test_indices:
        frame = pipeline.get_rendered_frame(idx)
        viewer.set_image(frame.qimage)
        app.processEvents()  # force repaint
        cs = pixmap_checksum(viewer)
        checksums.append(cs)
        print(f"  Slice {idx:4d}: qimg={frame.qimage.width()}x{frame.qimage.height()} null={frame.qimage.isNull()} checksum={cs}")
    
    unique = len(set(checksums))
    ok = unique == len(checksums)
    print(f"  Result: {unique}/{len(checksums)} unique checksums → {'PASS' if ok else 'FAIL'}")
    viewer.hide()
    return ok


def test_bridge():
    """Test B: pipeline + bridge + QtSliceViewer."""
    print("\n" + "=" * 60)
    print("TEST B: pipeline + QtViewerBridge + QtSliceViewer")
    print("=" * 60)
    
    pipeline = Lightweight2DPipeline(config=PipelineConfig())
    pipeline.open_series(series_path)
    n = pipeline.slice_count
    print(f"  Slices: {n}")
    
    viewer = QtSliceViewer()
    viewer.resize(512, 512)
    viewer.show()
    
    bridge = QtViewerBridge(
        qt_viewer=viewer,
        pipeline=pipeline,
        metadata={},
        metadata_fixed={},
        vtk_widget=None,
    )
    
    checksums = []
    test_indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
    for idx in test_indices:
        bridge.set_slice(idx)
        app.processEvents()
        cs = pixmap_checksum(viewer)
        checksums.append(cs)
        print(f"  Slice {idx:4d}: bridge.current={bridge._current_slice} checksum={cs}")
    
    unique = len(set(checksums))
    ok = unique == len(checksums)
    print(f"  Result: {unique}/{len(checksums)} unique checksums → {'PASS' if ok else 'FAIL'}")
    viewer.hide()
    return ok


def test_vtk_parent():
    """Test C: QVTKRenderWindowInteractor as parent (production layout)."""
    print("\n" + "=" * 60)
    print("TEST C: QVTKRenderWindowInteractor + bridge (production layout)")
    print("=" * 60)
    
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
    
    # Container
    container = QWidget()
    container.resize(512, 512)
    
    # VTK render widget (same as VTKWidget base class)
    vtk_rw = QVTKRenderWindowInteractor(container)
    vtk_rw.setGeometry(container.rect())
    
    # Pipeline
    pipeline = Lightweight2DPipeline(config=PipelineConfig())
    pipeline.open_series(series_path)
    n = pipeline.slice_count
    print(f"  Slices: {n}")
    
    # QtSliceViewer as child of VTK widget (EXACTLY like production)
    viewer = QtSliceViewer(parent=vtk_rw)
    viewer.setGeometry(vtk_rw.rect())
    viewer.show()
    viewer.raise_()
    
    # Bridge  
    bridge = QtViewerBridge(
        qt_viewer=viewer,
        pipeline=pipeline,
        metadata={},
        metadata_fixed={},
        vtk_widget=None,
    )
    
    container.show()
    app.processEvents()
    
    print(f"  VTK widget visible: {vtk_rw.isVisible()}")
    print(f"  Qt viewer visible: {viewer.isVisible()}")
    print(f"  Qt viewer size: {viewer.width()}x{viewer.height()}")
    print(f"  Qt viewer parent: {type(viewer.parent()).__name__}")
    
    checksums = []
    test_indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
    for idx in test_indices:
        bridge.set_slice(idx)
        app.processEvents()  # critical: process paint events
        cs = pixmap_checksum(viewer)
        checksums.append(cs)
        print(f"  Slice {idx:4d}: checksum={cs} pixmap_null={viewer._pixmap is None or viewer._pixmap.isNull()}")
    
    unique = len(set(checksums))
    ok = unique == len(checksums)
    print(f"  Result: {unique}/{len(checksums)} unique checksums → {'PASS' if ok else 'FAIL'}")
    
    container.hide()
    return ok


def test_scroll_signal_chain():
    """Test D: Simulates the ACTUAL scroll signal chain used in production.
    QtSliceViewer.wheelEvent → slice_scroll_requested → bridge._on_qt_scroll → ???
    """
    print("\n" + "=" * 60)
    print("TEST D: Scroll signal chain (production signal flow)")
    print("=" * 60)
    
    from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
    from unittest.mock import MagicMock
    from PySide6.QtWidgets import QSlider
    
    # Simulate VTKWidget structure
    container = QWidget()
    container.resize(512, 512)
    
    vtk_rw = QVTKRenderWindowInteractor(container)
    vtk_rw.setGeometry(container.rect())
    
    pipeline = Lightweight2DPipeline(config=PipelineConfig())
    pipeline.open_series(series_path)
    n = pipeline.slice_count
    print(f"  Slices: {n}")
    
    viewer = QtSliceViewer(parent=vtk_rw)
    viewer.setGeometry(vtk_rw.rect())
    viewer.show()
    viewer.raise_()
    
    # Create a slider (like production)
    slider = QSlider(Qt.Orientation.Vertical, container)
    slider.setRange(0, n - 1)
    mid = n // 2
    slider.setValue(mid)
    
    # Mock vtk_widget with slider attribute
    mock_vtk = MagicMock()
    mock_vtk.slider = slider
    mock_vtk._qt_bridge_active = True
    mock_vtk._on_slice_changed_cb = None
    mock_vtk._in_wheel_scroll = False
    mock_vtk._last_lock_sync_ms = 0.0
    
    bridge = QtViewerBridge(
        qt_viewer=viewer,
        pipeline=pipeline,
        metadata={},
        metadata_fixed={},
        vtk_widget=mock_vtk,
    )
    
    container.show()
    app.processEvents()
    
    # Initial render
    bridge.set_slice(mid)
    app.processEvents()
    cs_initial = pixmap_checksum(viewer)
    print(f"  Initial slice {mid}: checksum={cs_initial}")
    
    # Now simulate scrolling via the signal chain
    # In production: QtSliceViewer.wheelEvent → slice_scroll_requested → bridge._on_qt_scroll
    
    print(f"\n  Simulating 5 scroll-down events via bridge._on_qt_scroll(+1):")
    checksums = [cs_initial]
    for i in range(5):
        bridge._on_qt_scroll(1)  # scroll down
        app.processEvents()
        cs = pixmap_checksum(viewer)
        checksums.append(cs)
        print(f"    After scroll {i+1}: bridge.current={bridge._current_slice} slider={slider.value()} checksum={cs}")
    
    unique = len(set(checksums))
    print(f"  Result: {unique}/{len(checksums)} unique checksums → {'PASS' if unique > 1 else 'FAIL'}")
    
    # Also test: what does set_slice_index do to the pipeline state?
    print(f"\n  Pipeline state check:")
    print(f"    pipeline._current_index = {pipeline._current_index}")
    print(f"    pipeline.slice_count = {pipeline.slice_count}")
    print(f"    bridge._current_slice = {bridge._current_slice}")
    print(f"    bridge._slice_count = {bridge._slice_count}")
    
    # Check if pipeline frames are actually different
    print(f"\n  Direct pipeline frame check (bypassing bridge):")
    frames_same = True
    prev_cs = None
    for idx in [mid, mid+1, mid+2]:
        frame = pipeline.get_rendered_frame(idx)
        img = frame.qimage
        w, h = img.width(), img.height()
        vals = []
        for y_frac in [0.25, 0.5, 0.75]:
            for x_frac in [0.25, 0.5, 0.75]:
                vals.append(img.pixel(int(w * x_frac), int(h * y_frac)))
        cs = hash(tuple(vals))
        if prev_cs is not None and cs != prev_cs:
            frames_same = False
        prev_cs = cs
        print(f"    Slice {idx}: frame_checksum={cs}")
    
    print(f"  Pipeline frames identical: {frames_same}")
    
    container.hide()
    return unique > 1


# -- Run all tests --
results = {}
results["A: Bare"] = test_bare()
results["B: Bridge"] = test_bridge()
results["C: VTK+Bridge"] = test_vtk_parent()
results["D: Signal chain"] = test_scroll_signal_chain()

print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
for name, ok in results.items():
    status = "✓ PASS" if ok else "✗ FAIL"
    print(f"  {status}  {name}")

all_pass = all(results.values())
print(f"\nOverall: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")

if all_pass:
    print("\n>>> All rendering tests pass. The bug is likely in VTKWidget integration")
    print("    (signal connections, VTK render overwriting Qt viewer, or widget lifecycle)")
else:
    print("\n>>> Fix the failing test(s) above first.")

sys.exit(0 if all_pass else 1)
