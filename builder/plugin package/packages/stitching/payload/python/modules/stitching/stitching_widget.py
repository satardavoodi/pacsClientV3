"""
Stitching Widget — Multi-series selection and chain-stitching UI.

Main window for landmark-based 2-D radiograph stitching.  The user:

1. Selects N series from the patient's available series list.
2. Loads them.
3. For each adjacent pair, places matching landmarks (A/A', B/B', …).
4. Runs the chain-stitching pipeline.
5. Previews / exports the result.

Layout
------
Left sidebar (320 px) — series selection, pair selector, landmark controls,
                         action buttons, progress bar.
Centre splitter        — two ``_MiniViewer2D`` panels showing the active
                         pair's left and right images, plus a result viewer.

Author : AI Pacs Team
Created: 2026-02-20  (rewritten for multi-series support)
"""

from __future__ import annotations

import logging
import os
import tempfile
from collections import defaultdict
from typing import Dict, List, Optional

import numpy as np
import SimpleITK as sitk

try:
    import vtkmodules.all as vtk
except ImportError:
    import vtk

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from PacsClient.utils.theme_manager import get_theme_manager

from .landmark_store import LandmarkStore
from .landmark_interactor_style import LandmarkInteractorStyle, _PanZoomImageStyle
from .stitch_engine import compute_transform, compute_residuals

logger = logging.getLogger(__name__)


# ======================================================================
#  Dark style
# ======================================================================

def _build_app_stylesheet(t: dict) -> str:
    """Themed window stylesheet built from the V2 design tokens.

    Mirrors the previous hard-coded dark style 1:1 in structure (default
    buttons = accent, danger = red, success = green, checked = warning) so the
    layout/feel is unchanged but the window now tracks the active AI-PACS theme.
    """
    return f"""
QWidget {{
    background: {t['window_bg']};
    color: {t['text_primary']};
    font-family: 'Segoe UI', 'Roboto', sans-serif;
    font-size: 11px;
}}
QLabel#section_header {{
    font-size: 12px;
    font-weight: bold;
    color: {t['accent']};
    padding: 4px 0;
}}
QPushButton {{
    background: {t['accent']};
    color: {t['button_text']};
    border: 1px solid {t['accent']};
    border-radius: 6px;
    padding: 8px 12px;
    font-weight: bold;
}}
QPushButton:hover {{
    background: {t['accent_hover']};
    border-color: {t['accent_hover']};
}}
QPushButton:pressed {{
    background: {t['accent_pressed']};
}}
QPushButton:disabled {{
    background: {t['panel_alt_bg']};
    color: {t['text_muted']};
    border: 1px solid {t['border']};
}}
QPushButton:checked {{
    background: {t['warning']};
    border: 1px solid {t['warning']};
    color: {t['button_text']};
}}
QPushButton#btn_danger {{
    background: {t['danger']};
    border: 1px solid {t['danger']};
    color: {t['button_text']};
}}
QPushButton#btn_danger:hover {{
    background: {t['danger_hover']};
}}
QPushButton#btn_success {{
    background: {t['success']};
    border: 1px solid {t['success']};
    color: {t['button_text']};
}}
QPushButton#btn_success:hover {{
    background: {t['success_hover']};
}}
QComboBox {{
    background: {t['panel_alt_bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {t['text_primary']};
}}
QComboBox::drop-down {{ border: none; }}
QComboBox QAbstractItemView {{
    background: {t['panel_alt_bg']};
    color: {t['text_primary']};
    selection-background-color: {t['accent']};
}}
QListWidget {{
    background: {t['panel_deep_bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    color: {t['text_primary']};
}}
QListWidget::item {{
    padding: 4px 8px;
}}
QListWidget::item:selected {{
    background: {t['menu_active_bg']};
}}
QProgressBar {{
    background: {t['panel_deep_bg']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    text-align: center;
    color: {t['text_primary']};
    height: 22px;
}}
QProgressBar::chunk {{
    background: {t['accent']};
    border-radius: 5px;
}}
QFrame#separator {{
    background: {t['border']};
    max-height: 1px;
}}
"""


# ======================================================================
#  VTK 2-D viewer panel (minimal, embeddable)
# ======================================================================

class _MiniViewer2D(QFrame):
    """Lightweight VTK 2-D image viewer with camera-based Y-flip.

    The camera ``ViewUp`` is set to ``(0, -1, 0)`` so that DICOM images
    appear right-side-up while preserving physical coordinate consistency
    for landmark picking.
    """

    def __init__(self, title: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = get_theme_manager().current_theme()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Title bar
        self._title_label: QLabel | None = None
        if title:
            self._title_label = QLabel(title)
            self._title_label.setAlignment(Qt.AlignCenter)
            layout.addWidget(self._title_label)

        # VTK widget — the image viewport stays BLACK (medical-imaging
        # standard); only the surrounding chrome is themed.
        self.vtk_widget = QVTKRenderWindowInteractor(self)
        self.vtk_widget.setStyleSheet("border: none; background: black;")
        layout.addWidget(self.vtk_widget)
        self.apply_theme(self._theme)

        # Renderer (layer 0 — image)
        self.renderer = vtk.vtkRenderer()
        self.renderer.SetBackground(0, 0, 0)
        rw = self.vtk_widget.GetRenderWindow()
        rw.SetNumberOfLayers(2)
        self.renderer.SetLayer(0)
        rw.AddRenderer(self.renderer)

        # Overlay renderer (layer 1 — landmarks / labels, always on top)
        self.overlay_renderer = vtk.vtkRenderer()
        self.overlay_renderer.SetLayer(1)
        self.overlay_renderer.InteractiveOff()
        rw.AddRenderer(self.overlay_renderer)

        # Image display pipeline (populated on load)
        self.vtk_image_data: vtk.vtkImageData | None = None
        self._image_actor: vtk.vtkImageActor | None = None

        # Interactor
        self.image_interactor = self.vtk_widget.GetRenderWindow().GetInteractor()

        # Default LMB=Pan, RMB=W/L, Scroll=Zoom style (created once, reused)
        self._default_style = _PanZoomImageStyle()
        self.image_interactor.SetInteractorStyle(self._default_style)

        # Cached pickers (avoid re-creating on every click)
        self._cell_picker = vtk.vtkCellPicker()
        self._cell_picker.SetTolerance(0.005)
        self._world_picker = vtk.vtkWorldPointPicker()

    def set_title(self, text: str) -> None:
        if self._title_label:
            self._title_label.setText(text)

    def apply_theme(self, theme: dict | None = None) -> None:
        """Theme the viewer chrome (frame border + title bar). The image
        viewport itself stays black."""
        t = theme or get_theme_manager().current_theme()
        self._theme = t
        self.setStyleSheet(f"background: #000; border: 1px solid {t['border']};")
        if self._title_label is not None:
            self._title_label.setStyleSheet(
                f"background: {t['panel_bg']}; color: {t['accent']}; "
                f"font-weight: bold; padding: 4px; border: none; font-size: 11px;"
            )

    # ------------------------------------------------------------------
    #  Image loading
    # ------------------------------------------------------------------

    def load_sitk_image(self, img: sitk.Image) -> None:
        """Display a 2-D ``sitk.Image`` (right-side-up via camera flip)."""
        arr = sitk.GetArrayFromImage(img)  # shape (H, W) or (1, H, W)
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]

        h, w = arr.shape
        vtk_img = vtk.vtkImageData()
        vtk_img.SetDimensions(w, h, 1)
        vtk_img.SetSpacing(img.GetSpacing()[0], img.GetSpacing()[1], 1.0)
        origin = img.GetOrigin()
        vtk_img.SetOrigin(origin[0], origin[1], 0.0)
        vtk_img.AllocateScalars(vtk.VTK_FLOAT, 1)

        from vtkmodules.util.numpy_support import numpy_to_vtk
        flat = arr.astype(np.float32).ravel()
        vtk_arr = numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_FLOAT)
        vtk_img.GetPointData().SetScalars(vtk_arr)

        self._set_vtk_image(vtk_img, arr)

    def load_vtk_image(self, vtk_img: vtk.vtkImageData) -> None:
        """Display a ``vtkImageData`` directly."""
        from vtkmodules.util.numpy_support import vtk_to_numpy
        scalars = vtk_img.GetPointData().GetScalars()
        arr = vtk_to_numpy(scalars).reshape(
            vtk_img.GetDimensions()[1], vtk_img.GetDimensions()[0]
        )
        self._set_vtk_image(vtk_img, arr)

    def _set_vtk_image(self, vtk_img: vtk.vtkImageData, arr: np.ndarray) -> None:
        """Internal: wire up or update the VTK display pipeline."""
        self.vtk_image_data = vtk_img

        # Auto window / level
        vmin, vmax = float(arr.min()), float(arr.max())
        window = vmax - vmin if vmax > vmin else 1.0
        level = (vmax + vmin) / 2.0

        if self._image_actor is None:
            # First load — build pipeline
            self._image_actor = vtk.vtkImageActor()
            self._image_actor.GetMapper().SetInputData(vtk_img)
            self._image_actor.GetProperty().SetColorWindow(window)
            self._image_actor.GetProperty().SetColorLevel(level)
            self._image_actor.InterpolateOn()
            self.renderer.AddActor(self._image_actor)
        else:
            # Update existing pipeline
            self._image_actor.GetMapper().SetInputData(vtk_img)
            self._image_actor.GetProperty().SetColorWindow(window)
            self._image_actor.GetProperty().SetColorLevel(level)

        self.renderer.ResetCamera()

        # ── Y-FLIP FIX: flip camera so images appear right-side-up ──
        # DICOM images have origin at top-left; VTK renders Y-up so
        # without this the image appears upside-down.
        camera = self.renderer.GetActiveCamera()
        camera.SetViewUp(0, -1, 0)
        self.renderer.ResetCamera()

        # Extend far clipping plane so overlay markers at Z > 0 are visible
        clip_near, clip_far = camera.GetClippingRange()
        camera.SetClippingRange(max(clip_near, 0.001), max(clip_far, 10.0))

        # Sync the overlay renderer's camera so markers track the image
        self.overlay_renderer.SetActiveCamera(camera)

        self.force_render_now()

    # ------------------------------------------------------------------
    #  Picking (for landmark placement)
    # ------------------------------------------------------------------

    def pick_world_point(self, display_x: int, display_y: int):
        """Pick a world-space point from display coordinates."""
        if self.vtk_image_data is None:
            return None

        # Method 1: vtkCellPicker (cached)
        if self._cell_picker.Pick(display_x, display_y, 0, self.renderer):
            if self._cell_picker.GetCellId() >= 0:
                picked = self._cell_picker.GetPickPosition()
                if picked != (0.0, 0.0, 0.0):
                    return tuple(picked)

        # Method 2: vtkWorldPointPicker (cached)
        if self._world_picker.Pick(display_x, display_y, 0, self.renderer):
            picked = self._world_picker.GetPickPosition()
            if picked != (0.0, 0.0, 0.0):
                return tuple(picked)

        # Method 3: coordinate conversion
        coord = vtk.vtkCoordinate()
        coord.SetCoordinateSystemToDisplay()
        coord.SetValue(display_x, display_y, 0)
        world_2d = coord.GetComputedWorldValue(self.renderer)
        return (world_2d[0], world_2d[1], 0.0)

    # ------------------------------------------------------------------
    #  Render helper
    # ------------------------------------------------------------------

    def force_render_now(self) -> None:
        try:
            rw = self.vtk_widget.GetRenderWindow()
            if rw:
                rw.Render()
        except Exception:
            pass

    def Render(self) -> None:
        self.force_render_now()

    # ------------------------------------------------------------------
    #  Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Release VTK resources."""
        try:
            if self._image_actor and self.renderer:
                self.renderer.RemoveActor(self._image_actor)
            if self.vtk_widget:
                rw = self.vtk_widget.GetRenderWindow()
                if rw and hasattr(self, "overlay_renderer"):
                    rw.RemoveRenderer(self.overlay_renderer)
                if rw:
                    rw.Finalize()
                self.image_interactor.TerminateApp()
        except Exception:
            pass


# ======================================================================
#  Singleton accessor
# ======================================================================

_stitching_widget_instance: Optional["StitchingWidget"] = None


def get_stitching_widget(parent_widget: QWidget | None = None) -> "StitchingWidget":
    """Return the singleton ``StitchingWidget`` (create on first call)."""
    global _stitching_widget_instance
    if _stitching_widget_instance is None or not _stitching_widget_instance.isVisible():
        _stitching_widget_instance = StitchingWidget(parent_widget)
    return _stitching_widget_instance


# ======================================================================
#  Main Widget
# ======================================================================

class StitchingWidget(QWidget):
    """Top-level window for multi-series landmark-based 2-D stitching."""

    # ------------------------------------------------------------------
    #  Signals (for patient_widget integration)
    # ------------------------------------------------------------------
    stitching_started = Signal()
    stitching_finished = Signal(int)       # exit_code (0 = ok)
    stitching_error = Signal(str)

    # ------------------------------------------------------------------
    #  Construction
    # ------------------------------------------------------------------
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("AI Pacs – Stitching")
        self.setMinimumSize(1200, 700)
        self.resize(1500, 850)

        # ── Theme ─────────────────────────────────────────────────────
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)

        # ── Data state ────────────────────────────────────────────────
        self._available_series: List[dict] = []
        self._selected_series: List[dict] = []  # ordered chain
        self._loaded_images: Dict[str, sitk.Image] = {}  # series_number → sitk
        self._stitched_sitk: sitk.Image | None = None
        self._worker = None
        self._preview_worker = None               # fast low-res preview thread
        self._temp_dirs: List[str] = []          # temp DICOM dirs (cleanup)
        self._virtual_images: Dict[str, sitk.Image] = {}  # sn → in-memory image

        # ── Landmark / pick state ─────────────────────────────────────
        self._landmark_store = LandmarkStore(self)
        self._active_pair_idx: int = 0
        self._pick_mode_active: bool = False
        self._left_interactor: LandmarkInteractorStyle | None = None
        self._right_interactor: LandmarkInteractorStyle | None = None
        self._reposition_mode: bool = False
        self._reposition_lm_idx: int = -1

        self._build_ui()
        self._connect_signals()
        self._apply_theme_styles()

    # ==================================================================
    #  Theme
    # ==================================================================

    def _on_theme_changed(self, theme) -> None:
        self._theme = theme or self.theme_manager.current_theme()
        self._apply_theme_styles()

    def _apply_theme_styles(self) -> None:
        """Single place that paints the window from V2 tokens (re-run on every
        live theme change)."""
        t = self._theme
        self.setStyleSheet(_build_app_stylesheet(t))
        self._lbl_loaded_info.setStyleSheet(f"color: {t['info']}; font-style: italic;")
        self._lbl_pick_status.setStyleSheet(f"color: {t['warning']}; font-style: italic;")
        self._lbl_compute_hint.setStyleSheet(
            f"color: {t['warning']}; font-size: 10px; padding: 2px 4px;"
        )
        self._style_accuracy("info")
        for viewer in (self._left_viewer, self._right_viewer):
            viewer.apply_theme(t)

    def _style_accuracy(self, kind: str) -> None:
        """Colour the residual/accuracy label by semantic state."""
        t = self._theme
        color = {
            "info": t["info"], "success": t["success"], "danger": t["danger"],
        }.get(kind, t["info"])
        self._lbl_accuracy.setStyleSheet(
            f"color: {color}; font-size: 10px; padding: 4px;"
        )

    # ==================================================================
    #  UI construction
    # ==================================================================

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        outer_splitter = QSplitter(Qt.Horizontal, self)

        # ── Left: Controls ────────────────────────────────────────────
        ctrl = QWidget(self)
        ctrl.setMinimumWidth(280)
        ctrl.setMaximumWidth(340)
        cl = QVBoxLayout(ctrl)
        cl.setContentsMargins(10, 10, 10, 10)
        cl.setSpacing(6)

        # -- Title
        title = QLabel("Stitching Controls")
        title.setObjectName("section_header")
        title.setAlignment(Qt.AlignCenter)
        cl.addWidget(title)
        cl.addWidget(self._separator())

        # -- Series Selection
        cl.addWidget(QLabel("Available Series (check to select):"))
        self._series_list_widget = QListWidget()
        self._series_list_widget.setMaximumHeight(160)
        self._series_list_widget.setSelectionMode(QListWidget.NoSelection)
        cl.addWidget(self._series_list_widget)

        self._btn_load_selected = QPushButton("Load Selected Series")
        self._btn_load_selected.setCursor(Qt.PointingHandCursor)
        cl.addWidget(self._btn_load_selected)

        self._lbl_loaded_info = QLabel("")
        cl.addWidget(self._lbl_loaded_info)

        cl.addWidget(self._separator())

        # -- Active Pair
        cl.addWidget(QLabel("Active Pair (for landmarks):"))
        self._combo_active_pair = QComboBox()
        cl.addWidget(self._combo_active_pair)

        cl.addWidget(self._separator())

        # -- Transform type
        cl.addWidget(QLabel("Transform type:"))
        self._combo_transform = QComboBox()
        self._combo_transform.addItems(["Similarity", "Rigid", "Affine"])
        cl.addWidget(self._combo_transform)

        cl.addWidget(self._separator())

        # -- Landmark controls
        lm_header = QLabel("Landmarks")
        lm_header.setObjectName("section_header")
        cl.addWidget(lm_header)

        self._btn_place_pair = QPushButton("Place Landmark Pair")
        self._btn_place_pair.setCursor(Qt.PointingHandCursor)
        self._btn_place_pair.setCheckable(True)
        cl.addWidget(self._btn_place_pair)

        self._lbl_pick_status = QLabel("")
        self._lbl_pick_status.setAlignment(Qt.AlignCenter)
        cl.addWidget(self._lbl_pick_status)

        self._landmark_list = QListWidget()
        self._landmark_list.setMaximumHeight(160)
        cl.addWidget(self._landmark_list)

        btn_row = QHBoxLayout()
        self._btn_remove_lm = QPushButton("Remove")
        self._btn_remove_lm.setObjectName("btn_danger")
        self._btn_remove_lm.setCursor(Qt.PointingHandCursor)
        btn_row.addWidget(self._btn_remove_lm)
        self._btn_clear_lm = QPushButton("Clear All")
        self._btn_clear_lm.setObjectName("btn_danger")
        self._btn_clear_lm.setCursor(Qt.PointingHandCursor)
        btn_row.addWidget(self._btn_clear_lm)
        cl.addLayout(btn_row)

        cl.addWidget(self._separator())

        # -- Action buttons
        self._btn_quick_preview = QPushButton("Quick Preview (fast)")
        self._btn_quick_preview.setCursor(Qt.PointingHandCursor)
        self._btn_quick_preview.setEnabled(False)
        self._btn_quick_preview.setToolTip(
            "Fast low-resolution alignment preview from the current landmarks\n"
            "(no full blend) — check the fit before running Compute Stitching."
        )
        cl.addWidget(self._btn_quick_preview)

        self._btn_compute = QPushButton("Compute Stitching")
        self._btn_compute.setCursor(Qt.PointingHandCursor)
        self._btn_compute.setEnabled(False)
        cl.addWidget(self._btn_compute)

        # Tells the user *why* Compute is disabled (how many pairs are missing).
        self._lbl_compute_hint = QLabel("")
        self._lbl_compute_hint.setWordWrap(True)
        cl.addWidget(self._lbl_compute_hint)

        self._btn_preview = QPushButton("Preview Result")
        self._btn_preview.setObjectName("btn_success")
        self._btn_preview.setCursor(Qt.PointingHandCursor)
        self._btn_preview.setEnabled(False)
        cl.addWidget(self._btn_preview)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%p%  %v / 100")
        cl.addWidget(self._progress)

        cl.addWidget(self._separator())

        self._btn_export = QPushButton("Export as DICOM")
        self._btn_export.setObjectName("btn_success")
        self._btn_export.setCursor(Qt.PointingHandCursor)
        self._btn_export.setEnabled(False)
        cl.addWidget(self._btn_export)

        cl.addWidget(self._separator())

        # -- Iterative / multi-stage stitching
        self._btn_use_result = QPushButton("Use Result for Next Stitch")
        self._btn_use_result.setCursor(Qt.PointingHandCursor)
        self._btn_use_result.setEnabled(False)
        self._btn_use_result.setToolTip(
            "Save the stitched result as DICOM and add it to the\n"
            "series list so you can stitch it with the next image."
        )
        cl.addWidget(self._btn_use_result)

        # -- Accuracy info
        self._lbl_accuracy = QLabel("")
        self._lbl_accuracy.setWordWrap(True)
        cl.addWidget(self._lbl_accuracy)

        cl.addStretch()

        outer_splitter.addWidget(ctrl)

        # ── Right: Viewer area ────────────────────────────────────────
        viewer_splitter = QSplitter(Qt.Horizontal, self)

        self._left_viewer = _MiniViewer2D("Left Image", self)
        viewer_splitter.addWidget(self._left_viewer)

        self._right_viewer = _MiniViewer2D("Right Image / Result", self)
        viewer_splitter.addWidget(self._right_viewer)

        viewer_splitter.setStretchFactor(0, 1)
        viewer_splitter.setStretchFactor(1, 1)

        outer_splitter.addWidget(viewer_splitter)

        outer_splitter.setStretchFactor(0, 0)
        outer_splitter.setStretchFactor(1, 1)

        root.addWidget(outer_splitter)

    # ------------------------------------------------------------------
    #  Signal wiring
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        self._btn_load_selected.clicked.connect(self._on_load_selected)
        self._combo_active_pair.currentIndexChanged.connect(self._on_pair_changed)
        self._btn_place_pair.toggled.connect(self._on_toggle_pick_mode)
        self._btn_remove_lm.clicked.connect(self._on_remove_landmark)
        self._btn_clear_lm.clicked.connect(self._on_clear_landmarks)
        self._btn_quick_preview.clicked.connect(self._on_quick_preview)
        self._btn_compute.clicked.connect(self._on_compute)
        self._btn_preview.clicked.connect(self._on_preview)
        self._btn_export.clicked.connect(self._on_export)
        self._btn_use_result.clicked.connect(self._on_use_result_for_next_stitch)
        self._landmark_store.landmarks_changed.connect(self._refresh_landmark_ui)
        self._landmark_list.currentRowChanged.connect(self._on_landmark_selected)

    # ==================================================================
    #  Public entry point (called from patient_widget)
    # ==================================================================

    def launch_with_series(
        self,
        available_series: List[dict] | None = None,
        dicom_dir: str | None = None,
        series_uid: str | None = None,
        **kwargs,
    ) -> None:
        """Show the stitching window.

        Parameters
        ----------
        available_series : list of series dicts from patient_widget.
            Each dict has keys: series_number, series_path,
            series_description, series_uid, …
        dicom_dir : fallback single DICOM directory (legacy).
        """
        # Populate series list
        if available_series:
            self._available_series = list(available_series)
        elif dicom_dir:
            self._available_series = [
                {
                    "series_number": os.path.basename(dicom_dir),
                    "series_path": dicom_dir,
                    "series_description": os.path.basename(dicom_dir),
                    "series_uid": series_uid or "",
                }
            ]
        else:
            self._available_series = []

        self._populate_series_list()

        # Reset state
        self._loaded_images.clear()
        self._selected_series.clear()
        self._landmark_store.clear_all()
        self._stitched_sitk = None
        self._virtual_images.clear()
        self._btn_preview.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._btn_compute.setEnabled(False)
        self._btn_use_result.setEnabled(False)
        self._lbl_accuracy.setText("")
        self._progress.setValue(0)
        self._combo_active_pair.clear()

        self.stitching_started.emit()
        self.show()
        self.raise_()
        self.activateWindow()
        logger.info("Launched with %d available series", len(self._available_series))

    # ==================================================================
    #  Series selection
    # ==================================================================

    def _populate_series_list(self) -> None:
        """Fill the QListWidget with checkable series items."""
        self._series_list_widget.clear()
        for entry in self._available_series:
            sn = entry.get("series_number", "?")
            desc = entry.get("series_description") or ""
            text = f"Series {sn}"
            if desc:
                text += f"  –  {desc}"
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, entry)
            self._series_list_widget.addItem(item)

    def _on_load_selected(self) -> None:
        """Load the checked series and prepare pair selectors."""
        checked: List[dict] = []
        for row in range(self._series_list_widget.count()):
            item = self._series_list_widget.item(row)
            if item.checkState() == Qt.Checked:
                entry = item.data(Qt.UserRole)
                if entry:
                    checked.append(entry)

        if len(checked) < 2:
            QMessageBox.warning(
                self, "Not Enough Series",
                "Please select at least 2 series to stitch."
            )
            return

        # Sort by series_number for consistent chain order
        def _sn(e):
            try:
                return int(e.get("series_number", 0))
            except (TypeError, ValueError):
                return 0

        checked.sort(key=_sn)
        self._selected_series = checked
        self._loaded_images.clear()
        self._landmark_store.clear_all()
        # Clear leftover visual markers from any previous round
        self._clear_visual_markers()

        # Load each series
        try:
            from .stitch_engine import load_series_as_2d

            for entry in checked:
                sn = str(entry["series_number"])
                # Check if this is a virtual (in-memory) stitched result
                if sn in self._virtual_images:
                    self._loaded_images[sn] = self._virtual_images[sn]
                    logger.debug("Loaded virtual series %s from memory", sn)
                    continue
                spath = entry.get("series_path")
                if not spath or not os.path.isdir(spath):
                    QMessageBox.warning(
                        self, "Missing Directory",
                        f"Series {entry.get('series_number')} path not found:\n{spath}"
                    )
                    return
                img = load_series_as_2d(spath)
                self._loaded_images[sn] = img
                logger.debug("Loaded series %s: %s", sn, img.GetSize())

        except Exception as exc:
            QMessageBox.critical(self, "Load Error", f"Failed to load series:\n{exc}")
            return

        n = len(checked)
        self._lbl_loaded_info.setText(f"{n} series loaded  →  {n - 1} pair(s)")

        # Populate pair combo
        self._combo_active_pair.blockSignals(True)
        self._combo_active_pair.clear()
        for i in range(n - 1):
            sn_left = checked[i].get("series_number", "?")
            sn_right = checked[i + 1].get("series_number", "?")
            self._combo_active_pair.addItem(
                f"Series {sn_left}  ↔  Series {sn_right}"
            )
        self._combo_active_pair.blockSignals(False)
        self._active_pair_idx = 0
        self._combo_active_pair.setCurrentIndex(0)

        # Show first pair
        self._show_pair_images(0)
        self._update_compute_button()

    # ==================================================================
    #  Pair navigation
    # ==================================================================

    def _on_pair_changed(self, index: int) -> None:
        if index < 0:
            return
        # Deactivate pick mode when switching pairs
        self._btn_place_pair.setChecked(False)
        self._active_pair_idx = index
        self._show_pair_images(index)
        self._refresh_landmark_ui()

    def _show_pair_images(self, pair_idx: int) -> None:
        """Display the two images for the given adjacent pair."""
        if pair_idx < 0 or pair_idx >= len(self._selected_series) - 1:
            return

        left_entry = self._selected_series[pair_idx]
        right_entry = self._selected_series[pair_idx + 1]

        left_sn = str(left_entry["series_number"])
        right_sn = str(right_entry["series_number"])

        left_img = self._loaded_images.get(left_sn)
        right_img = self._loaded_images.get(right_sn)

        if left_img:
            self._left_viewer.set_title(f"Series {left_sn}  (left)")
            self._left_viewer.load_sitk_image(left_img)

        if right_img:
            self._right_viewer.set_title(f"Series {right_sn}  (right)")
            self._right_viewer.load_sitk_image(right_img)

        # (Re-)create landmark interactors for the new pair
        self._setup_interactors_for_pair(pair_idx)
        # Re-plot existing landmarks
        self._replot_all_markers()

    def _setup_interactors_for_pair(self, pair_idx: int) -> None:
        """Create fresh LandmarkInteractorStyle objects for the viewers.

        **Important**: old interactor marker actors are cleared first to
        prevent orphaned VTK actors persisting in the overlay renderer.
        """
        # ── Clear old interactors' markers before replacing them ──────
        if self._left_interactor is not None:
            self._left_interactor.clear_markers()
        if self._right_interactor is not None:
            self._right_interactor.clear_markers()

        # Build label function based on current pair set
        def _left_label_fn(idx: int) -> str:
            return LandmarkStore.index_to_label(idx)

        def _right_label_fn(idx: int) -> str:
            return f"{LandmarkStore.index_to_label(idx)}'"

        self._left_interactor = LandmarkInteractorStyle(
            self._left_viewer, role="fixed", label_fn=_left_label_fn,
        )
        self._left_interactor.point_picked.connect(self._on_point_picked)
        self._left_interactor.set_enabled(False)
        # Install immediately so LMB=Pan works before pick mode is toggled
        self._left_viewer.image_interactor.SetInteractorStyle(
            self._left_interactor
        )

        self._right_interactor = LandmarkInteractorStyle(
            self._right_viewer, role="moving", label_fn=_right_label_fn,
        )
        self._right_interactor.point_picked.connect(self._on_point_picked)
        self._right_interactor.set_enabled(False)
        self._right_viewer.image_interactor.SetInteractorStyle(
            self._right_interactor
        )

    # ==================================================================
    #  Landmark pick mode
    # ==================================================================

    def _on_toggle_pick_mode(self, active: bool) -> None:
        # Cancel reposition mode when entering/leaving pick mode
        self._reposition_mode = False
        self._reposition_lm_idx = -1

        self._pick_mode_active = active
        if active:
            # Deselect any selected landmark in the list
            self._landmark_list.blockSignals(True)
            self._landmark_list.clearSelection()
            self._landmark_list.setCurrentRow(-1)
            self._landmark_list.blockSignals(False)

            self._lbl_pick_status.setText(
                f"Click {LandmarkStore.index_to_label(self._landmark_store.landmark_count(self._active_pair_idx))} "
                "on the LEFT image…"
            )
            if self._left_interactor:
                self._left_interactor.set_enabled(True)
                self._left_viewer.image_interactor.SetInteractorStyle(
                    self._left_interactor
                )
            if self._right_interactor:
                self._right_interactor.set_enabled(False)
            # Reset marker colours (remove any reposition highlights)
            if self._left_interactor:
                self._left_interactor.reset_marker_colours()
            if self._right_interactor:
                self._right_interactor.reset_marker_colours()
        else:
            self._lbl_pick_status.setText("")
            if self._left_interactor:
                self._left_interactor.set_enabled(False)
            if self._right_interactor:
                self._right_interactor.set_enabled(False)

    def _on_point_picked(self, role: str, x: float, y: float) -> None:
        """Handle a landmark point picked from either viewer."""
        ps = self._active_pair_idx

        # ── Reposition mode — update existing landmark ────────────────
        if self._reposition_mode and self._reposition_lm_idx >= 0:
            lm_idx = self._reposition_lm_idx
            if role == "fixed":
                self._landmark_store.set_left_point(ps, lm_idx, (x, y))
            elif role == "moving":
                self._landmark_store.set_right_point(ps, lm_idx, (x, y))
            self._replot_all_markers()
            # Re-highlight the landmark being repositioned
            if self._left_interactor:
                self._left_interactor.highlight_markers({lm_idx})
            if self._right_interactor:
                self._right_interactor.highlight_markers({lm_idx})
            self._compute_live_residuals()
            return

        # ── Normal new-landmark mode ─────────────────────────────
        if role == "fixed":
            # Left point placed → now wait for the right point
            lm_idx = self._landmark_store.add_left_point(ps, (x, y))
            label = LandmarkStore.index_to_label(lm_idx)
            self._lbl_pick_status.setText(
                f"Click {label}' on the RIGHT image…"
            )
            if self._left_interactor:
                self._left_interactor.set_enabled(False)
            if self._right_interactor:
                self._right_interactor.set_enabled(True)
                self._right_viewer.image_interactor.SetInteractorStyle(
                    self._right_interactor
                )

        elif role == "moving":
            # Right point — complete the pair
            pending = self._landmark_store.pending_index(ps)
            if pending is not None:
                self._landmark_store.set_right_point(ps, pending, (x, y))

            # Cycle back to left for the next pair if still in pick mode
            if self._pick_mode_active:
                next_idx = self._landmark_store.landmark_count(ps)
                next_label = LandmarkStore.index_to_label(next_idx)
                self._lbl_pick_status.setText(
                    f"Click {next_label} on the LEFT image…"
                )
                if self._left_interactor:
                    self._left_interactor.set_enabled(True)
                    self._left_viewer.image_interactor.SetInteractorStyle(
                        self._left_interactor
                    )
                if self._right_interactor:
                    self._right_interactor.set_enabled(False)

    # ==================================================================
    #  Landmark list management
    # ==================================================================

    def _refresh_landmark_ui(self) -> None:
        """Rebuild the landmark QListWidget for the active pair set."""
        # Block signals to prevent re-entering _on_landmark_selected
        # when the list is rebuilt (clear triggers currentRowChanged).
        self._landmark_list.blockSignals(True)
        self._landmark_list.clear()
        ps = self._active_pair_idx
        for i, (left, right) in enumerate(self._landmark_store.get_pairs(ps)):
            lbl_l, lbl_r = LandmarkStore.pair_label(i)
            if right is None:
                text = f"{lbl_l}: ({left[0]:.1f}, {left[1]:.1f}) → {lbl_r}: (pending…)"
            else:
                text = (
                    f"{lbl_l}: ({left[0]:.1f}, {left[1]:.1f})  ↔  "
                    f"{lbl_r}: ({right[0]:.1f}, {right[1]:.1f})"
                )
            self._landmark_list.addItem(QListWidgetItem(text))

        # Preserve selection when in reposition mode
        if self._reposition_mode and 0 <= self._reposition_lm_idx < self._landmark_list.count():
            self._landmark_list.setCurrentRow(self._reposition_lm_idx)
        self._landmark_list.blockSignals(False)

        self._update_compute_button()

    def _update_compute_button(self) -> None:
        """Enable Compute/Quick-Preview when every boundary has enough pairs,
        and otherwise tell the user exactly how many more are needed."""
        min_req = 4  # All transforms require at least 4 landmarks for accuracy
        if not self._selected_series or len(self._selected_series) < 2:
            self._btn_compute.setEnabled(False)
            self._btn_quick_preview.setEnabled(False)
            self._lbl_compute_hint.setText("")
            return

        n_pairs = len(self._selected_series) - 1
        shortfalls = [
            (ps, min_req - self._landmark_store.complete_count(ps))
            for ps in range(n_pairs)
            if self._landmark_store.complete_count(ps) < min_req
        ]
        all_ok = not shortfalls

        self._btn_compute.setEnabled(all_ok)
        self._btn_quick_preview.setEnabled(all_ok)
        if all_ok:
            self._lbl_compute_hint.setText("")
        else:
            parts = ", ".join(f"pair {ps + 1}: {need} more" for ps, need in shortfalls)
            self._lbl_compute_hint.setText(
                f"Place {min_req} complete landmark pairs per boundary to enable "
                f"Compute  ({parts})."
            )

    def _on_remove_landmark(self) -> None:
        row = self._landmark_list.currentRow()
        if row >= 0:
            self._landmark_store.remove_landmark(self._active_pair_idx, row)
            self._replot_all_markers()

    def _on_clear_landmarks(self) -> None:
        self._landmark_store.clear_pair_set(self._active_pair_idx)
        self._clear_visual_markers()

    def _clear_visual_markers(self) -> None:
        if self._left_interactor:
            self._left_interactor.clear_markers()
        if self._right_interactor:
            self._right_interactor.clear_markers()

    def _replot_all_markers(self) -> None:
        """Clear and re-draw all landmarks for the active pair set."""
        self._clear_visual_markers()

        if self._left_interactor:
            self._left_interactor.reset_index(0)
        if self._right_interactor:
            self._right_interactor.reset_index(0)

        ps = self._active_pair_idx
        for left, right in self._landmark_store.get_pairs(ps):
            if left is not None and self._left_interactor:
                self._left_interactor._add_marker((left[0], left[1], 0.01))
                self._left_interactor._point_index += 1
            if right is not None and self._right_interactor:
                self._right_interactor._add_marker((right[0], right[1], 0.01))
                self._right_interactor._point_index += 1

    # ==================================================================
    #  Landmark selection & repositioning
    # ==================================================================

    def _on_landmark_selected(self, row: int) -> None:
        """Enter reposition mode for the selected landmark."""
        if row < 0:
            # Deselection — exit reposition mode
            self._reposition_mode = False
            self._reposition_lm_idx = -1
            self._lbl_pick_status.setText("")
            if self._left_interactor:
                self._left_interactor.reset_marker_colours()
            if self._right_interactor:
                self._right_interactor.reset_marker_colours()
            return

        # Cancel new-landmark mode if active
        if self._pick_mode_active:
            self._btn_place_pair.blockSignals(True)
            self._btn_place_pair.setChecked(False)
            self._btn_place_pair.blockSignals(False)
            self._pick_mode_active = False

        # Enter reposition mode
        self._reposition_mode = True
        self._reposition_lm_idx = row

        lbl_l, lbl_r = LandmarkStore.pair_label(row)
        self._lbl_pick_status.setText(
            f"Click to reposition {lbl_l} on LEFT or {lbl_r} on RIGHT"
        )

        # Enable both interactors for repositioning
        if self._left_interactor:
            self._left_interactor.set_enabled(True)
            self._left_viewer.image_interactor.SetInteractorStyle(
                self._left_interactor
            )
        if self._right_interactor:
            self._right_interactor.set_enabled(True)
            self._right_viewer.image_interactor.SetInteractorStyle(
                self._right_interactor
            )

        # Highlight the selected landmark on both viewers
        self._replot_all_markers()
        if self._left_interactor:
            self._left_interactor.highlight_markers({row})
        if self._right_interactor:
            self._right_interactor.highlight_markers({row})

    def _compute_live_residuals(self) -> None:
        """Compute and display residuals for the active pair set in real time."""
        ps = self._active_pair_idx
        left_flat = self._landmark_store.get_left_flat(ps)
        right_flat = self._landmark_store.get_right_flat(ps)

        n_pairs = len(left_flat) // 2
        if n_pairs < 4:
            remaining = 4 - n_pairs
            self._lbl_accuracy.setText(
                f"Need {remaining} more complete pair(s) to compute residuals"
            )
            self._style_accuracy("info")
            return

        try:
            ttype = self._combo_transform.currentText().lower()
            transform = compute_transform(left_flat, right_flat, ttype)
            residuals = compute_residuals(left_flat, right_flat, transform)

            lines = []
            any_warning = False
            for i, r in enumerate(residuals):
                lbl_l, lbl_r = LandmarkStore.pair_label(i)
                tag = " \u26a0 EXCEEDS 4 mm" if r > 4.0 else ""
                if r > 4.0:
                    any_warning = True
                lines.append(f"{lbl_l}\u2013{lbl_r}: {r:.2f} mm{tag}")

            max_r = max(residuals) if residuals else 0
            mean_r = sum(residuals) / len(residuals) if residuals else 0
            header = f"max={max_r:.2f} mm, mean={mean_r:.2f} mm"
            info_text = f"Live Residuals ({header}):\n" + "\n".join(lines)
            self._lbl_accuracy.setText(info_text)

            self._style_accuracy("danger" if any_warning else "success")
        except Exception as exc:
            self._lbl_accuracy.setText(f"Residual error: {exc}")
            self._style_accuracy("danger")

    # ==================================================================
    #  Compute & Preview
    # ==================================================================

    def _on_compute(self) -> None:
        """Run the N-series chain-stitching pipeline."""
        if self._any_worker_running():
            QMessageBox.warning(self, "Busy", "A stitching operation is already running.")
            return

        self._btn_place_pair.setChecked(False)
        # Reset highlight state from any prior run
        if self._left_interactor:
            self._left_interactor.reset_marker_colours()
        if self._right_interactor:
            self._right_interactor.reset_marker_colours()
        self._lbl_accuracy.setText("")

        series_dirs = []
        preloaded: List[Optional[sitk.Image]] = []
        for entry in self._selected_series:
            series_dirs.append(entry["series_path"])
            # Reuse the already-loaded image (and the high-fidelity in-memory
            # stitched result for virtual series) so the worker does not read
            # the series from disk a second time / lose float precision.
            sn = str(entry.get("series_number", ""))
            preloaded.append(self._loaded_images.get(sn))

        from .stitch_worker import StitchWorker  # deferred to avoid circular

        self._worker = StitchWorker(
            series_dirs=series_dirs,
            landmark_store=self._landmark_store,
            transform_type=self._combo_transform.currentText().lower(),
            parent=self,
            preloaded_images=preloaded,
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.completed.connect(self._on_worker_completed)
        self._worker.error.connect(self._on_worker_error)
        self._worker.residuals_report.connect(self._on_residuals_report)
        # Release the QThread once it finishes so repeated stitches don't leak
        # parented workers (each kept a reference to its loaded images).
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

        self._btn_compute.setEnabled(False)
        self._progress.setValue(0)

    def _on_worker_progress(self, status: str, fraction: float) -> None:
        pct = int(fraction * 100)
        self._progress.setValue(pct)
        self._progress.setFormat(f"{status}  {pct}%")

    def _on_worker_completed(self, stitched_img) -> None:
        self._stitched_sitk = stitched_img
        self._progress.setValue(100)
        self._progress.setFormat("Stitching complete  100%")
        self._btn_compute.setEnabled(True)
        self._btn_preview.setEnabled(True)
        self._btn_export.setEnabled(True)
        self._btn_use_result.setEnabled(True)
        logger.info("Chain stitching complete - preview ready")

    def _on_worker_error(self, msg: str) -> None:
        self._progress.setValue(0)
        self._progress.setFormat("Error")
        self._btn_compute.setEnabled(True)
        QMessageBox.critical(self, "Stitching Error", msg)
        self.stitching_error.emit(msg)

    def _on_worker_finished(self) -> None:
        """Release the finished worker (avoids leaking parented QThreads)."""
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    # ------------------------------------------------------------------
    #  Quick low-resolution alignment preview (fast feather, no full blend)
    # ------------------------------------------------------------------

    def _on_quick_preview(self) -> None:
        if self._any_worker_running():
            QMessageBox.warning(self, "Busy", "An operation is already running.")
            return

        series_dirs = []
        preloaded: List[Optional[sitk.Image]] = []
        for entry in self._selected_series:
            series_dirs.append(entry["series_path"])
            preloaded.append(self._loaded_images.get(str(entry.get("series_number", ""))))

        from .stitch_worker import StitchWorker

        self._preview_worker = StitchWorker(
            series_dirs=series_dirs,
            landmark_store=self._landmark_store,
            transform_type=self._combo_transform.currentText().lower(),
            parent=self,
            preloaded_images=preloaded,
            preview=True,
        )
        self._preview_worker.progress.connect(self._on_worker_progress)
        self._preview_worker.completed.connect(self._on_preview_completed)
        self._preview_worker.error.connect(self._on_worker_error)
        self._preview_worker.finished.connect(self._on_preview_worker_finished)
        self._btn_quick_preview.setEnabled(False)
        self._btn_compute.setEnabled(False)
        self._progress.setValue(0)
        self._preview_worker.start()

    def _on_preview_completed(self, img) -> None:
        """Display the low-res alignment preview WITHOUT changing the real
        result state (no export / use-for-next enabled)."""
        if self._right_interactor:
            self._right_interactor.clear_markers()
        self._right_viewer.set_title("Quick Preview (low-res)")
        self._right_viewer.load_sitk_image(img)
        self._progress.setValue(100)
        self._progress.setFormat("Quick preview ready  100%")
        self._update_compute_button()  # re-enable Compute / Quick Preview
        logger.debug("Quick preview displayed")

    def _on_preview_worker_finished(self) -> None:
        worker = self._preview_worker
        self._preview_worker = None
        if worker is not None:
            worker.deleteLater()

    def _any_worker_running(self) -> bool:
        return bool(
            (self._worker and self._worker.isRunning())
            or (self._preview_worker and self._preview_worker.isRunning())
        )

    def _on_preview(self) -> None:
        if self._stitched_sitk is None:
            return
        # Clear any landmark markers from the right viewer so the
        # preview shows *only* the patient image — no labels/crosshairs.
        if self._right_interactor:
            self._right_interactor.clear_markers()
        self._right_viewer.set_title("Stitched Result")
        self._right_viewer.load_sitk_image(self._stitched_sitk)
        logger.debug("Preview displayed")

    # ==================================================================
    #  Accuracy / residuals — per-landmark report & confirmation dialog
    # ==================================================================

    def _on_residuals_report(self, report: list) -> None:
        """Display per-landmark residual errors and, if any exceed 4 mm,
        show a detailed confirmation dialog that names the exact landmark
        pair, highlights it in red on the viewers, and lets the user
        choose to re-adjust, add more pairs, or continue anyway.

        Parameters
        ----------
        report : list of dicts with keys:
            pair_set, lm_index, label_left, label_right,
            residual_mm, exceeds
        """
        if not report:
            return

        # ── Build info text and collect bad entries ───────────────────
        bad_entries = [e for e in report if e["exceeds"]]
        any_warning = len(bad_entries) > 0

        # Group by pair_set for summary
        by_pair: dict = defaultdict(list)
        for e in report:
            by_pair[e["pair_set"]].append(e)

        summary_lines = []
        for ps in sorted(by_pair):
            entries = by_pair[ps]
            details = []
            for e in entries:
                lbl = f"{e['label_left']}–{e['label_right']}"
                tag = " ⚠ EXCEEDS 4 mm" if e["exceeds"] else ""
                details.append(f"  {lbl}: {e['residual_mm']:.2f} mm{tag}")
            ps_resids = [e["residual_mm"] for e in entries]
            ps_max = max(ps_resids)
            ps_mean = sum(ps_resids) / len(ps_resids)
            header_tag = " — EXCEEDS 4 mm" if ps_max > 4.0 else ""
            summary_lines.append(
                f"Pair set {ps}: max={ps_max:.2f} mm, "
                f"mean={ps_mean:.2f} mm{header_tag}"
            )
            summary_lines.extend(details)

        info_text = "Residuals:\n" + "\n".join(summary_lines)
        self._lbl_accuracy.setText(info_text)

        if not any_warning:
            # All within tolerance — worker continues automatically
            self._style_accuracy("success")
            return

        # ── Highlight bad landmarks on the active pair viewers ────────
        self._style_accuracy("danger")
        bad_by_ps: dict[int, set] = defaultdict(set)
        for e in bad_entries:
            bad_by_ps[e["pair_set"]].add(e["lm_index"])

        active_ps = self._active_pair_idx
        if active_ps in bad_by_ps:
            bad_indices = bad_by_ps[active_ps]
            if self._left_interactor:
                self._left_interactor.highlight_markers(bad_indices)
            if self._right_interactor:
                self._right_interactor.highlight_markers(bad_indices)
        else:
            # If the active pair has no errors, switch to the first pair
            # that does, show its images, and highlight.
            first_bad_ps = min(bad_by_ps)
            self._combo_active_pair.setCurrentIndex(first_bad_ps)
            # _on_pair_changed will re-show images and re-plot markers
            QTimer.singleShot(200, lambda: self._highlight_bad_pair(
                first_bad_ps, bad_by_ps[first_bad_ps]
            ))

        # ── Build detailed per-landmark warning messages ──────────────
        detail_lines = []
        for e in bad_entries:
            lbl = f"{e['label_left']}–{e['label_right']}"
            detail_lines.append(
                f"• {lbl}:  The computed transformed position of point "
                f"{e['label_left']} does not sufficiently match point "
                f"{e['label_right']}.\n"
                f"   Residual error: {e['residual_mm']:.2f} mm "
                f"(exceeds 4 mm threshold)"
            )

        dialog_text = (
            "Accuracy Warning — AIPacs\n\n"
            "One or more landmark pairs have a residual error exceeding "
            "4 mm.\n\n"
            "For limb-length measurement the maximum acceptable error is "
            "approximately 3–4 mm.\n\n"
            + "\n\n".join(detail_lines)
            + "\n\n"
            "Do you confirm that these points are truly corresponding "
            "anatomical landmarks?\n\n"
            "Choose an action:"
        )

        # ── Show 3-button confirmation dialog ─────────────────────────
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Accuracy Warning — AIPacs")
        msg_box.setIcon(QMessageBox.Warning)
        msg_box.setText(dialog_text)

        btn_readjust = msg_box.addButton(
            "Re-adjust landmarks", QMessageBox.RejectRole
        )
        btn_add_more = msg_box.addButton(
            "Add more landmark pairs", QMessageBox.DestructiveRole
        )
        btn_continue = msg_box.addButton(
            "Continue anyway", QMessageBox.AcceptRole
        )

        msg_box.setDefaultButton(btn_readjust)
        msg_box.exec()

        clicked = msg_box.clickedButton()

        if clicked == btn_continue:
            # User accepts the risk — tell the worker to proceed
            logger.info("User chose: Continue anyway")
            if self._worker:
                self._worker.confirm_continue()
        elif clicked == btn_add_more:
            # Abort stitching, switch to pick mode
            logger.info("User chose: Add more landmark pairs")
            if self._worker:
                self._worker.reject_continue()
            self._btn_place_pair.setChecked(True)
        else:
            # Re-adjust (default) — abort stitching, user will move/re-place
            logger.info("User chose: Re-adjust landmarks")
            if self._worker:
                self._worker.reject_continue()

    def _highlight_bad_pair(self, ps: int, bad_indices: set) -> None:
        """Highlight specific landmark markers after pair switch.

        Called via QTimer.singleShot to let the pair viewer finish
        rendering first.
        """
        if self._left_interactor:
            self._left_interactor.highlight_markers(bad_indices)
        if self._right_interactor:
            self._right_interactor.highlight_markers(bad_indices)

    # ==================================================================
    #  Iterative / multi-stage stitching
    # ==================================================================

    def _on_use_result_for_next_stitch(self) -> None:
        """Save stitched result as DICOM and add it back to the series list.

        This enables the multi-stage workflow required for full limb-length
        stitching: stitch A+B → result₁, then stitch result₁+C → result₂, …
        """
        if self._stitched_sitk is None:
            QMessageBox.warning(self, "No Result", "Run stitching first.")
            return

        # Create a temp directory and export
        temp_dir = tempfile.mkdtemp(prefix="AI_Stitch_stage_")
        self._temp_dirs.append(temp_dir)

        try:
            self._export_as_dicom(temp_dir)
        except Exception as exc:
            QMessageBox.critical(
                self, "Export Error",
                f"Failed to save intermediate DICOM:\n{exc}",
            )
            return

        # Assign a virtual series number
        existing_nums = set()
        for entry in self._available_series:
            try:
                existing_nums.add(int(entry.get("series_number", 0)))
            except (TypeError, ValueError):
                pass
        new_sn = str(max(existing_nums, default=0) + 900)  # 900+ range

        # Keep the high-fidelity sitk Image in memory (avoids uint16
        # round-trip loss for the next stitch)
        self._virtual_images[new_sn] = self._stitched_sitk

        new_entry = {
            "series_number": new_sn,
            "series_path": temp_dir,
            "series_description": "Stitched Result",
            "series_uid": "",
        }
        self._available_series.append(new_entry)
        self._populate_series_list()

        # Clear visual markers BEFORE clearing interactor references
        self._clear_visual_markers()

        # Reset stitch state for next round
        self._loaded_images.clear()
        self._selected_series.clear()
        self._landmark_store.clear_all()
        self._left_interactor = None
        self._right_interactor = None
        self._stitched_sitk = None
        self._reposition_mode = False
        self._reposition_lm_idx = -1
        self._btn_preview.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._btn_use_result.setEnabled(False)
        self._btn_compute.setEnabled(False)
        self._combo_active_pair.clear()
        self._lbl_accuracy.setText("")
        self._progress.setValue(0)

        QMessageBox.information(
            self,
            "Result Added",
            f"Stitched result saved as Series {new_sn} "
            f"(Stitched Result).\n\n"
            "Select it together with the next series to continue "
            "multi-stage stitching.",
        )
        logger.info("Stitched result added as series %s", new_sn)

    # ==================================================================
    #  DICOM Export
    # ==================================================================

    def _on_export(self) -> None:
        if self._stitched_sitk is None:
            QMessageBox.warning(self, "No Result", "Run stitching first.")
            return

        first_path = (self._selected_series[0].get("series_path") or "") if self._selected_series else ""
        save_dir = QFileDialog.getExistingDirectory(
            self, "Select Output Folder", first_path,
        )
        if not save_dir:
            return

        try:
            self._export_as_dicom(save_dir)
            QMessageBox.information(
                self, "Export Complete",
                f"Stitched DICOM saved to:\n{save_dir}",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export Error", str(exc))

    def _export_as_dicom(self, output_dir: str) -> str:
        """Write the stitched image as a DICOM Secondary Capture file.

        Includes spatial metadata (PixelSpacing, ImagePositionPatient,
        ImageOrientationPatient) so the file can be re-loaded for
        iterative multi-stage stitching with correct geometry.
        """
        import pydicom
        from pydicom.dataset import FileDataset, FileMetaDataset
        from pydicom.uid import generate_uid, ExplicitVRLittleEndian
        import datetime

        arr = sitk.GetArrayFromImage(self._stitched_sitk)
        if arr.ndim == 3 and arr.shape[0] == 1:
            arr = arr[0]

        arr = arr.astype(np.float64)
        vmin, vmax = float(arr.min()), float(arr.max())
        if vmax > vmin:
            arr = (arr - vmin) / (vmax - vmin) * 65535.0
            arr = arr.astype(np.uint16)
        else:
            # Constant / blank result — emit a clean zero frame instead of
            # casting raw (possibly out-of-range) floats to uint16.
            arr = np.zeros_like(arr, dtype=np.uint16)
        rows, cols = arr.shape

        file_meta = FileMetaDataset()
        file_meta.MediaStorageSOPClassUID = pydicom.uid.SecondaryCaptureImageStorage
        file_meta.MediaStorageSOPInstanceUID = generate_uid()
        file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

        now = datetime.datetime.now()
        fname = f"AI-Stitch-{now.strftime('%Y%m%d%H%M%S')}.dcm"
        filepath = os.path.join(output_dir, fname)

        ds = FileDataset(filepath, {}, file_meta=file_meta, preamble=b"\x00" * 128)
        ds.SOPClassUID = pydicom.uid.SecondaryCaptureImageStorage
        ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID
        ds.StudyInstanceUID = generate_uid()
        ds.SeriesInstanceUID = generate_uid()
        ds.FrameOfReferenceUID = generate_uid()
        ds.Modality = "OT"
        ds.SeriesDescription = f"AI-Stitch-{now.strftime('%H%M%S')}"
        ds.Manufacturer = "AI Pacs"
        ds.ContentDate = now.strftime("%Y%m%d")
        ds.ContentTime = now.strftime("%H%M%S.%f")
        ds.Rows = rows
        ds.Columns = cols
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 0
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.PixelData = arr.tobytes()

        # ── Spatial metadata (critical for measurement accuracy) ──────
        sp = self._stitched_sitk.GetSpacing()
        origin = self._stitched_sitk.GetOrigin()

        # DICOM PixelSpacing is [row_spacing, col_spacing] = [sy, sx]
        ds.PixelSpacing = [f"{sp[1]:.6f}", f"{sp[0]:.6f}"]
        # ImagePositionPatient — physical position of (0,0) pixel
        ds.ImagePositionPatient = [
            f"{origin[0]:.6f}", f"{origin[1]:.6f}", "0.000000",
        ]
        # Standard axial orientation
        ds.ImageOrientationPatient = [
            "1.000000", "0.000000", "0.000000",
            "0.000000", "1.000000", "0.000000",
        ]

        ds.save_as(filepath)
        logger.info("DICOM exported: %s", filepath)
        return filepath

    # ==================================================================
    #  Window lifecycle
    # ==================================================================

    def closeEvent(self, event) -> None:
        for worker in (self._worker, self._preview_worker):
            if worker and worker.isRunning():
                worker.cancel()
                worker.wait(3000)
        self._left_viewer.cleanup()
        self._right_viewer.cleanup()

        # Clean up temp DICOM directories from multi-stage workflow
        import shutil
        for d in self._temp_dirs:
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass
        self._temp_dirs.clear()

        self.stitching_finished.emit(0)
        super().closeEvent(event)

    # ==================================================================
    #  Helpers
    # ==================================================================

    @staticmethod
    def _separator() -> QFrame:
        sep = QFrame()
        sep.setObjectName("separator")
        sep.setFrameShape(QFrame.HLine)
        sep.setFixedHeight(1)
        return sep
