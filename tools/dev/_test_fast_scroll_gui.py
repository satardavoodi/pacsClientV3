"""
Interactive GUI test for FAST mode scroll.
Opens a real DICOM series with the exact same classes used in production
(Lightweight2DPipeline + QtSliceViewer + QtViewerBridge)
and lets you scroll with the mouse wheel.

ALSO tests: bare QtSliceViewer WITHOUT bridge (left panel) vs WITH bridge (right panel).
If left works but right doesn't → bridge problem.
If both fail → QtSliceViewer / pipeline problem.

Run:  .venv\Scripts\python.exe tools/dev/_test_fast_scroll_gui.py
"""

import sys, os, time

# Ensure project root on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLabel,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QWheelEvent

from modules.viewer.fast.lightweight_2d_pipeline import (
    Lightweight2DPipeline, PipelineConfig,
)
from modules.viewer.fast.qt_slice_viewer import QtSliceViewer

# ---------- find a real DICOM series ----------
DICOM_DIR = os.path.join(ROOT, "user_data", "patients", "dicom")

def find_series_with_slices(min_slices=20):
    for study in os.listdir(DICOM_DIR):
        study_path = os.path.join(DICOM_DIR, study)
        if not os.path.isdir(study_path):
            continue
        for series in os.listdir(study_path):
            series_path = os.path.join(study_path, series)
            if not os.path.isdir(series_path):
                continue
            dcm_files = [f for f in os.listdir(series_path) if f.endswith(".dcm")]
            if len(dcm_files) >= min_slices:
                return series_path, len(dcm_files)
    return None, 0

series_path, n_files = find_series_with_slices()
if series_path is None:
    print("ERROR: No DICOM series with >=20 slices found.")
    sys.exit(1)

print(f"Using series: {series_path}  ({n_files} files)")


# ---------- Panel A: bare QtSliceViewer (pipeline → set_image directly) ----------
class BarePanel(QWidget):
    """Tests pipeline + QtSliceViewer WITHOUT the bridge."""

    def __init__(self, series_path: str):
        super().__init__()
        self.pipeline = Lightweight2DPipeline(config=PipelineConfig())
        self.pipeline.open_series(series_path)
        self.n_slices = self.pipeline.slice_count
        self.current = self.n_slices // 2

        layout = QVBoxLayout(self)
        self.label = QLabel(f"BARE viewer  –  slices={self.n_slices}")
        layout.addWidget(self.label)

        self.viewer = QtSliceViewer()
        self.viewer.setMinimumSize(512, 512)
        layout.addWidget(self.viewer)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(0, self.n_slices - 1))
        self.slider.setValue(self.current)
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        self.info = QLabel("")
        layout.addWidget(self.info)

        # Show mid-slice
        self._render_slice(self.current)

    def _render_slice(self, idx):
        t0 = time.perf_counter()
        frame = self.pipeline.get_rendered_frame(idx)
        dt = (time.perf_counter() - t0) * 1000
        self.viewer.set_image(frame.qimage)
        q = frame.qimage
        self.info.setText(
            f"Slice {idx}/{self.n_slices-1}  "
            f"img={q.width()}x{q.height()}  null={q.isNull()}  "
            f"render={dt:.1f}ms"
        )
        self.current = idx

    def _on_slider(self, val):
        self._render_slice(val)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        step = -1 if delta > 0 else 1
        new_val = max(0, min(self.n_slices - 1, self.current + step))
        if new_val != self.current:
            self.slider.setValue(new_val)
        event.accept()


# ---------- Panel B: full bridge (matches production path) ----------
class BridgePanel(QWidget):
    """Tests pipeline + QtSliceViewer + QtViewerBridge (production path)."""

    def __init__(self, series_path: str):
        super().__init__()
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

        layout = QVBoxLayout(self)

        self.pipeline = Lightweight2DPipeline(config=PipelineConfig())
        self.pipeline.open_series(series_path)
        self.n_slices = self.pipeline.slice_count

        self.label = QLabel(f"BRIDGE viewer  –  slices={self.n_slices}")
        layout.addWidget(self.label)

        self.qt_viewer = QtSliceViewer()
        self.qt_viewer.setMinimumSize(512, 512)
        layout.addWidget(self.qt_viewer)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(0, self.n_slices - 1))
        mid = self.n_slices // 2
        self.slider.setValue(mid)
        layout.addWidget(self.slider)

        self.info = QLabel("")
        layout.addWidget(self.info)

        # Create bridge
        self.bridge = QtViewerBridge(
            qt_viewer=self.qt_viewer,
            pipeline=self.pipeline,
            metadata={},
            metadata_fixed={},
            vtk_widget=None,  # no VTK widget
        )
        self.current = mid

        # Connect slider → bridge.set_slice (same as production)
        self.slider.valueChanged.connect(self._on_slider)

        # Disconnect the bridge's own scroll handler to prevent conflicts
        # (we handle scroll ourselves below, matching the production path)
        try:
            self.qt_viewer.slice_scroll_requested.disconnect(self.bridge._on_qt_scroll)
        except Exception:
            pass

        # Show mid-slice
        self._render_via_bridge(mid)

    def _render_via_bridge(self, idx):
        t0 = time.perf_counter()
        self.bridge.set_slice(idx)
        dt = (time.perf_counter() - t0) * 1000
        self.current = idx
        self.info.setText(
            f"Slice {idx}/{self.n_slices-1}  "
            f"bridge._current={self.bridge._current_slice}  "
            f"render={dt:.1f}ms"
        )

    def _on_slider(self, val):
        self._render_via_bridge(val)

    def wheelEvent(self, event: QWheelEvent):
        delta = event.angleDelta().y()
        step = -1 if delta > 0 else 1
        new_val = max(0, min(self.n_slices - 1, self.current + step))
        if new_val != self.current:
            self.slider.setValue(new_val)
        event.accept()


# ---------- Panel C: VTKWidget integration (closest to production) ----------
class VTKIntegrationPanel(QWidget):
    """Tests VTKWidget (QVTKRenderWindowInteractor) with Qt bridge on top.
    This is the exact same layout as production."""

    def __init__(self, series_path: str):
        super().__init__()
        from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
        from modules.viewer.fast.qt_viewer_bridge import QtViewerBridge

        layout = QVBoxLayout(self)
        self.label = QLabel("VTK+BRIDGE (production layout)")
        layout.addWidget(self.label)

        # Create the QVTKRenderWindowInteractor (same as VTKWidget base class)
        self.vtk_rw = QVTKRenderWindowInteractor(self)
        self.vtk_rw.setMinimumSize(512, 512)
        layout.addWidget(self.vtk_rw)

        # Pipeline
        self.pipeline = Lightweight2DPipeline(config=PipelineConfig())
        self.pipeline.open_series(series_path)
        self.n_slices = self.pipeline.slice_count

        # Create QtSliceViewer as CHILD of the VTK render widget (production layout)
        self.qt_viewer = QtSliceViewer(parent=self.vtk_rw)
        self.qt_viewer.setGeometry(self.vtk_rw.rect())
        self.qt_viewer.show()
        self.qt_viewer.raise_()

        # Create bridge
        self.bridge = QtViewerBridge(
            qt_viewer=self.qt_viewer,
            pipeline=self.pipeline,
            metadata={},
            metadata_fixed={},
            vtk_widget=None,
        )

        # Slider
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, max(0, self.n_slices - 1))
        mid = self.n_slices // 2
        self.slider.setValue(mid)
        self.slider.valueChanged.connect(self._on_slider)
        layout.addWidget(self.slider)

        self.info = QLabel("")
        layout.addWidget(self.info)

        self.current = mid

        # Disconnect bridge's internal scroll to avoid conflict
        try:
            self.qt_viewer.slice_scroll_requested.disconnect(self.bridge._on_qt_scroll)
        except Exception:
            pass

        # Connect our own scroll handler
        self.qt_viewer.slice_scroll_requested.connect(self._on_qt_scroll)

        # Render initial
        self._render(mid)

    def _render(self, idx):
        t0 = time.perf_counter()
        self.bridge.set_slice(idx)
        dt = (time.perf_counter() - t0) * 1000
        self.current = idx
        self.info.setText(
            f"Slice {idx}/{self.n_slices-1}  render={dt:.1f}ms  "
            f"qt_vis={self.qt_viewer.isVisible()}  "
            f"qt_size={self.qt_viewer.width()}x{self.qt_viewer.height()}"
        )

    def _on_slider(self, val):
        self._render(val)

    def _on_qt_scroll(self, delta):
        new_val = max(0, min(self.n_slices - 1, self.current + delta))
        if new_val != self.current:
            self.slider.blockSignals(True)
            self.slider.setValue(new_val)
            self.slider.blockSignals(False)
            self._render(new_val)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep qt_viewer sized to VTK widget (same as production)
        if hasattr(self, 'qt_viewer') and hasattr(self, 'vtk_rw'):
            self.qt_viewer.setGeometry(self.vtk_rw.rect())


# ---------- main ----------
def main():
    app = QApplication(sys.argv)

    win = QWidget()
    win.setWindowTitle("FAST Scroll Debug — Bare | Bridge | VTK+Bridge")
    win.resize(1600, 700)

    layout = QHBoxLayout(win)

    # Panel A: Bare (no bridge)
    panel_a = BarePanel(series_path)
    layout.addWidget(panel_a)

    # Panel B: With bridge
    panel_b = BridgePanel(series_path)
    layout.addWidget(panel_b)

    # Panel C: VTK + bridge (production-like)
    panel_c = VTKIntegrationPanel(series_path)
    layout.addWidget(panel_c)

    win.show()
    print("\n=== Window shown. Scroll on each panel to test. Close window to exit. ===\n")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
