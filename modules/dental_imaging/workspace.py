# -*- coding: utf-8 -*-
"""Professional Dental Imaging workspace.

This is the Advanced Analysis CBCT workspace, separate from the lightweight 2D
Dental Curve MPR viewer. It follows the dental workflow shape used by mature CBCT
workstations: load CBCT, inspect the axial arch plane, define/refine a panoramic
curve, review a panoramic reconstruction, then inspect perpendicular cross-sections
with dental planning tools nearby.

The volume/geometry source remains the shared ``DentalVolume`` handle. This module
does not build a new geometry pipeline; it reads the existing VTK image data and
renders static QImage previews for the dental layout. The optional standard MPR embed
is kept behind ``AIPACS_DENTAL_VTK_MPR`` for troubleshooting, but the default UI is a
dedicated dental workspace rather than a simple MPR window.
"""
from __future__ import annotations

import logging
import math
import os
import time
from typing import Callable, Optional

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .context import DentalSeriesContext

logger = logging.getLogger(__name__)

_BG = "#0b0f14"
_PANEL = "#101923"
_PANEL_2 = "#0a1118"
_BORDER = "#233244"
_ACCENT = "#22c1dc"
_ACCENT_2 = "#7c3aed"
_TEXT = "#e5edf5"
_MUTED = "#8aa0b2"
_MAX_CROSS_SECTIONS_PER_PAGE = 16
# Pixels of vertical LEFT-drag per slice step when the mouse function is "Stack".
_STACK_DRAG_PX = 6.0

# The app's internal series-drag payload (series NUMBER as UTF-8). Matched against
# _vw_globals._SERIES_DROP_MIME at runtime; this is the correct fallback value.
_SERIES_DROP_MIME_FALLBACK = "application/x-aipacs-series-number"


def _cell(title: str, subtitle: str = ""):
    """A dark labelled cell. Returns (frame, content_label)."""
    frame = QFrame()
    frame.setStyleSheet(
        f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
    )
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(6, 6, 6, 6)
    lay.setSpacing(3)
    t = QLabel(title)
    t.setStyleSheet(
        f"QLabel {{ color:{_TEXT}; font-family:'Roboto','Segoe UI'; font-size:12px; "
        f"font-weight:600; background:transparent; border:none; }}"
    )
    lay.addWidget(t)
    content = QLabel(subtitle)
    content.setAlignment(Qt.AlignCenter)
    content.setWordWrap(True)
    content.setStyleSheet(
        f"QLabel {{ color:{_MUTED}; font-family:'Roboto','Segoe UI'; font-size:10px; "
        f"background:#05080c; border:none; border-radius:4px; }}"
    )
    lay.addWidget(content, 1)
    return frame, content


class DentalImagingWorkspace(QWidget):
    """Top-level professional CBCT/dental planning workspace."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Window)
        self._context: Optional[DentalSeriesContext] = None
        self._volume = None
        self._series_resolver: Optional[Callable[[int], tuple]] = None

        self._plane_pixmaps: dict = {}
        self._arch_enabled = os.environ.get("AIPACS_DENTAL_ARCH_PICK", "1") != "0"
        self._arch_pick_mode = False
        self._arch_points: list = []
        # Dual-arch (apical / root) picking for the oblique panoramic (default ON via
        # AIPACS_DENTAL_DUAL_ARCH). Picks route to the active arch; the panoramic tilts
        # each column crown->apex when both arches exist. Empty apical => single-arch.
        self._apical_arch_points: list = []
        self._active_arch = "crown"          # "crown" | "apical"
        self._dual_arch_enabled = os.environ.get("AIPACS_DENTAL_DUAL_ARCH", "1") != "0"
        self._axial_geom = None
        self._orient_enabled = os.environ.get("AIPACS_DENTAL_ORTHO_ORIENT", "1") != "0"
        self._nav_enabled = os.environ.get("AIPACS_DENTAL_STACK_NAV", "1") != "0"
        self._vtk_mpr_enabled = os.environ.get("AIPACS_DENTAL_VTK_MPR", "0") != "0"

        self._vol = None                 # numpy volume, shape (z, y, x)
        self._wl = None                  # (lo, hi) for QImage mapping
        self._wl_user_adjusted = False
        self._plans: dict = {}
        self._slice_idx: dict = {}
        self._view_sliders: dict = {}
        self._view_idx_labels: dict = {}
        self._default_arch_points: list = []
        self._last_curved_volume = None
        self._last_panoramic_image = None
        self._last_curved_array = None
        self._last_cross_frames: list = []
        self._last_recon_key = None
        self._last_cross_key = None
        self._last_pano_key = None
        self._cross_section_count = int(os.environ.get("AIPACS_DENTAL_XSECTION_COUNT", "18") or "18")
        try:
            configured_page_size = int(os.environ.get("AIPACS_DENTAL_XSECTION_PAGE_SIZE", str(_MAX_CROSS_SECTIONS_PER_PAGE)) or str(_MAX_CROSS_SECTIONS_PER_PAGE))
        except (TypeError, ValueError):
            configured_page_size = _MAX_CROSS_SECTIONS_PER_PAGE
        self._cross_page_size = max(1, min(_MAX_CROSS_SECTIONS_PER_PAGE, configured_page_size))
        self._cross_page = 0
        self._cross_total_pages = 1
        self._cross_visible_sections: list = []
        self._cross_all_sample_indices: list = []
        self._selected_cross_section = None
        self._sync_index = None
        self._sync_world = None
        self._sync_source = ""
        self._sync_pano_xy = None
        self._sync_cross_local = None
        self._active_cross_tool = "sync"
        self._cross_annotations: dict = {}
        self._pending_ruler_point = None
        self._dragging_cross_sync = False
        self._annotations: list = []
        self._annotation_id_counter = 0
        self._annotation_tool = "sync"
        self._annotation_visibility_mode = "slice_based"
        self._annotations_visible = True
        # View-sync overlay toggles (Planning panel "View Sync" section).
        self._show_pano_reference = True
        self._show_cross_position = True
        self._pending_annotation = None
        self._view_transforms: dict = {}
        # Selectable LEFT-drag mouse function (Planning panel "Mouse function" row):
        # stack (scroll slices) / pan / zoom / wl. Right-drag=WL, middle=zoom,
        # left+right=pan stay fixed; a plain click still does sync selection.
        self._mouse_mode = "stack"
        self._mouse_mode_buttons: dict = {}
        # Mandibular (inferior alveolar) nerve canal — bilateral editable trace.
        from .core.nerve_canal import NerveCanalStore
        self._nerve_store = NerveCanalStore()
        self._nerve_side = "left"
        self._nerve_mode = "off"          # off | trace | edit
        self._nerve_show = True
        self._nerve_drag = None           # (side, control_index, view) while editing
        self._nerve_pick_mm = 6.0
        self._nerve_side_buttons: dict = {}
        self._arch_show = True             # right-click the arch to hide/show it
        self._mouse_drag = {
            "plane": None,
            "button": None,
            "last": None,
            "press": None,
            "moved": False,
            "left": False,
            "right": False,
            "middle": False,
        }
        self._auto_recon_enabled = os.environ.get("AIPACS_DENTAL_AUTO_RECON", "0") != "0"

        self._vtk_mpr = None
        self._center_host = None
        self._center_layout = None
        self._dental_grid_widget = None

        self._status_label: Optional[QLabel] = None
        self._title_series_label: Optional[QLabel] = None
        self._geometry_label: Optional[QLabel] = None
        self._cells: dict = {}
        self._cell_frames: dict = {}
        self._cross_prev_btn = None
        self._cross_next_btn = None
        self._cross_page_label = None
        self._tool_buttons: dict = {}

        self.setWindowTitle("Dental Imaging - AIPacs")
        self.resize(1280, 820)
        self.setMinimumSize(1040, 680)
        self.setStyleSheet(f"QWidget {{ background:{_BG}; color:{_TEXT}; }}")
        self.setAcceptDrops(True)
        self._build_ui()

    def set_series_resolver(self, resolver: Optional[Callable[[int], tuple]]) -> None:
        self._series_resolver = resolver

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(5)
        root.addWidget(self._build_header())
        root.addWidget(self._build_main_toolbar())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, "
            f"stop:0 #1d4ed8, stop:0.52 {_ACCENT_2}, stop:1 #0f766e); border-radius:8px; }}"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(12, 8, 12, 8)
        title = QLabel("Dental Imaging")
        title.setStyleSheet(
            "QLabel { color:white; font-family:'Roboto','Segoe UI'; font-size:16px; "
            "font-weight:bold; background:transparent; }"
        )
        lay.addWidget(title)
        mode = QLabel("CBCT Panoramic / Cross Sections / Planning")
        mode.setStyleSheet(
            "QLabel { color:rgba(255,255,255,0.88); font-size:10px; background:rgba(0,0,0,0.18); "
            "border-radius:8px; padding:2px 8px; }"
        )
        lay.addWidget(mode)
        lay.addStretch()
        self._title_series_label = QLabel("No series loaded")
        self._title_series_label.setStyleSheet(
            "QLabel { color:rgba(255,255,255,0.92); font-size:11px; background:transparent; }"
        )
        lay.addWidget(self._title_series_label)
        return header

    def _build_main_toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(6, 5, 6, 5)
        lay.setSpacing(5)
        for text, slot in (
            ("Arch", self._toggle_arch_pick),
            ("Generate", self._regenerate_dental_recon),
            ("Implant", self._tool_placeholder),
            ("Canal", self._tool_placeholder),
            ("Snapshot", self._tool_placeholder),
        ):
            btn = QToolButton()
            btn.setText(text)
            btn.setToolTip(text)
            btn.setCheckable(text in ("Arch", "Ruler", "Annot"))
            btn.clicked.connect(slot)
            btn.setStyleSheet(
                "QToolButton { color:#e5edf5; background:#162232; border:1px solid #2b3b50; "
                "border-radius:6px; padding:5px 10px; font-size:11px; }"
                "QToolButton:hover { background:#213248; }"
                "QToolButton:checked { background:#0891b2; color:#061018; border-color:#22d3ee; }"
            )
            if text == "Arch":
                self._arch_pick_btn = btn
            lay.addWidget(btn)
        self._ruler_btn = QToolButton()
        self._ruler_btn.setText("Ruler")
        self._ruler_btn.setToolTip("Distance measurement")
        self._ruler_btn.setCheckable(True)
        self._ruler_btn.clicked.connect(lambda *_args: self._set_annotation_tool("distance"))
        self._ruler_btn.setStyleSheet(
            "QToolButton { color:#e5edf5; background:#162232; border:1px solid #2b3b50; "
            "border-radius:6px; padding:5px 10px; font-size:11px; }"
            "QToolButton:hover { background:#213248; }"
            "QToolButton:checked { background:#0891b2; color:#061018; border-color:#22d3ee; }"
        )
        self._tool_buttons["distance"] = self._ruler_btn
        lay.addWidget(self._ruler_btn)
        measure_menu_btn = QToolButton()
        measure_menu_btn.setText("...")
        measure_menu_btn.setToolTip("Measurement and annotation tools")
        measure_menu_btn.setPopupMode(QToolButton.InstantPopup)
        measure_menu_btn.setStyleSheet(
            "QToolButton { color:#e5edf5; background:#162232; border:1px solid #2b3b50; "
            "border-radius:6px; padding:5px 8px; font-size:11px; }"
            "QToolButton:hover { background:#213248; border-color:#22c1dc; }"
        )
        measure_menu = QMenu(measure_menu_btn)
        for label, tool in (
            ("Ruler / Distance", "distance"),
            ("Angle", "angle"),
            ("Density / HU probe", "density"),
            ("Text note", "text"),
            ("Dental marker", "marker"),
        ):
            action = QAction(label, measure_menu)
            action.triggered.connect(lambda _checked=False, t=tool: self._set_annotation_tool(t))
            measure_menu.addAction(action)
        measure_menu.addSeparator()
        for label, mode in (
            ("Slice-based visibility", "slice_based"),
            ("Pin new annotations", "pinned"),
            ("Hidden new annotations", "hidden"),
        ):
            action = QAction(label, measure_menu)
            action.triggered.connect(lambda _checked=False, m=mode: self._set_annotation_visibility_mode(m))
            measure_menu.addAction(action)
        hide_action = QAction("No-show / hide annotations", measure_menu)
        hide_action.triggered.connect(lambda *_args: self._toggle_annotations_visible())
        measure_menu.addAction(hide_action)
        measure_menu_btn.setMenu(measure_menu)
        lay.addWidget(measure_menu_btn)
        annot_btn = QToolButton()
        annot_btn.setText("Annot")
        annot_btn.setToolTip("Text note annotation")
        annot_btn.setCheckable(True)
        annot_btn.clicked.connect(lambda *_args: self._set_annotation_tool("text"))
        annot_btn.setStyleSheet(self._ruler_btn.styleSheet())
        self._tool_buttons["text"] = annot_btn
        lay.addWidget(annot_btn)
        lay.addSpacing(10)
        lay.addWidget(QLabel("WL"))
        self._wl_combo = QComboBox()
        self._wl_combo.addItems(["CBCT Bone", "Soft tissue", "Endodontic", "Implant"])
        self._wl_combo.currentTextChanged.connect(self._apply_wl_preset)
        self._wl_combo.setStyleSheet(
            "QComboBox { color:#e5edf5; background:#0a1118; border:1px solid #2b3b50; "
            "border-radius:6px; padding:4px 8px; min-width:110px; }"
        )
        lay.addWidget(self._wl_combo)
        lay.addSpacing(8)
        self._layer_apply_btn = QToolButton()
        self._layer_apply_btn.setText("Layer")
        self._layer_apply_btn.setToolTip("Apply Layer as cross-section piece count")
        self._layer_apply_btn.clicked.connect(self._apply_layer_count)
        self._layer_apply_btn.setStyleSheet(
            "QToolButton { color:#e5edf5; background:#162232; border:1px solid #2b3b50; "
            "border-radius:6px; padding:4px 8px; font-size:11px; }"
            "QToolButton:hover { background:#213248; border-color:#22c1dc; }"
        )
        lay.addWidget(self._layer_apply_btn)
        self._layer_slider = QSlider(Qt.Horizontal)
        self._layer_slider.setMinimum(5)
        self._layer_slider.setMaximum(48)
        self._layer_slider.setValue(max(5, min(48, int(self._cross_section_count))))
        self._layer_slider.setFixedWidth(110)
        self._layer_slider.valueChanged.connect(self._on_layer_changed)
        self._layer_slider.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:#253244;border-radius:2px;}"
            "QSlider::handle:horizontal{width:12px;background:#22c1dc;border-radius:6px;margin:-5px 0;}"
        )
        lay.addWidget(self._layer_slider)
        self._layer_label = QLabel(f"{int(self._layer_slider.value())} pcs")
        self._layer_label.setStyleSheet("color:#9fe8ff; font-size:11px;")
        lay.addWidget(self._layer_label)
        lay.addSpacing(8)
        self._cross_prev_btn = QToolButton()
        self._cross_prev_btn.setText("<")
        self._cross_prev_btn.setToolTip("Previous cross-section page")
        self._cross_prev_btn.clicked.connect(lambda: self._change_cross_page(-1))
        self._cross_next_btn = QToolButton()
        self._cross_next_btn.setText(">")
        self._cross_next_btn.setToolTip("Next cross-section page")
        self._cross_next_btn.clicked.connect(lambda: self._change_cross_page(1))
        self._cross_page_label = QLabel("Page 1/1")
        self._cross_page_label.setStyleSheet("color:#9fe8ff; font-size:11px;")
        for btn in (self._cross_prev_btn, self._cross_next_btn):
            btn.setEnabled(False)
            btn.setFixedWidth(26)
            btn.setStyleSheet(
                "QToolButton { color:#e5edf5; background:#162232; border:1px solid #2b3b50; "
                "border-radius:6px; padding:4px 6px; font-size:11px; }"
                "QToolButton:hover { background:#213248; }"
                "QToolButton:disabled { color:#516174; background:#101923; border-color:#1d2a38; }"
            )
            lay.addWidget(btn)
        lay.addWidget(self._cross_page_label)
        lay.addStretch()
        return bar

    def _build_body(self) -> QWidget:
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self._build_tools_panel())

        center_host = QWidget()
        center_layout = QVBoxLayout(center_host)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self._center_host = center_host
        self._center_layout = center_layout
        self._dental_grid_widget = self._build_dental_grid()
        center_layout.addWidget(self._dental_grid_widget, 1)
        lay.addWidget(center_host, 1)

        lay.addWidget(self._build_planning_panel())
        return body

    def _build_tools_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(188)
        panel.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        title = QLabel("Dental Workflow")
        title.setStyleSheet("font-size:13px; font-weight:700; color:#9fe8ff; background:transparent; border:none;")
        lay.addWidget(title)
        for text in (
            "1  Load CBCT volume",
            "2  Inspect axial arch plane",
            "3  Pick or refine dental arch",
            "4  Review panoramic reconstruction",
            "5  Inspect cross-sectional slices",
            "6  Plan implants / trace canal",
        ):
            lbl = QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#b8c7d8; font-size:11px; background:transparent; border:none;")
            lay.addWidget(lbl)
        lay.addSpacing(8)
        if self._arch_enabled:
            self._build_arch_controls(panel)
        lay.addStretch()
        return panel

    def _build_dental_grid(self) -> QWidget:
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(5)
        grid.setVerticalSpacing(5)

        pano, self._cells["panoramic"] = _cell(
            "Panoramic Reconstruction",
            "Load a CBCT series to build the panoramic preview.",
        )
        self._cell_frames["panoramic"] = pano
        self._cells["panoramic"].setCursor(Qt.CrossCursor)
        self._cells["panoramic"].installEventFilter(self)
        pano.setCursor(Qt.CrossCursor)
        pano.installEventFilter(self)
        for child in pano.findChildren(QLabel):
            child.setCursor(Qt.CrossCursor)
            child.installEventFilter(self)
        pano.setMinimumHeight(430)

        axial = self._ortho_cell("axial", "Axial - Arch Curve")
        cross, self._cells["crosssection"] = _cell(
            "Cross Sections",
            "Perpendicular dental slices appear after the volume loads.",
        )
        self._cell_frames["crosssection"] = cross
        self._cells["crosssection"].setCursor(Qt.PointingHandCursor)
        self._cells["crosssection"].setMouseTracking(True)
        self._cells["crosssection"].installEventFilter(self)
        cross.setCursor(Qt.PointingHandCursor)
        cross.setMouseTracking(True)
        cross.installEventFilter(self)
        for child in cross.findChildren(QLabel):
            child.setCursor(Qt.PointingHandCursor)
            child.setMouseTracking(True)
            child.installEventFilter(self)
        cross.setMinimumHeight(430)

        support = QWidget()
        # Coronal + Sagittal side by side (was stacked vertically). These recon views are
        # tall (superior-inferior), so a wide-short stacked cell letterboxed them with
        # black bars; side-by-side gives each the FULL cell height → larger, less waste.
        support_lay = QHBoxLayout(support)
        support_lay.setContentsMargins(0, 0, 0, 0)
        support_lay.setSpacing(5)
        support_lay.addWidget(self._ortho_cell("coronal", "Coronal"), 1)
        support_lay.addWidget(self._ortho_cell("sagittal", "Sagittal"), 1)
        threed, self._cells["3d"] = _cell(
            "3D / Objects",
            "Implants, nerve canal and segmentation objects will appear here.",
        )
        self._cell_frames["3d"] = threed
        threed.setMinimumHeight(0)
        for panel in (pano, cross, axial, threed, support):
            panel.setMinimumWidth(0)
            panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        for key in ("panoramic", "crosssection", "axial", "coronal", "sagittal", "3d"):
            cell = self._cells.get(key)
            if cell is not None:
                cell.setMinimumSize(0, 0)
                cell.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)

        lower_left = QWidget()
        lower_left.setMinimumWidth(0)
        lower_left.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        lower_left_lay = QHBoxLayout(lower_left)
        lower_left_lay.setContentsMargins(0, 0, 0, 0)
        lower_left_lay.setSpacing(5)
        lower_left_lay.addWidget(axial, 1)
        lower_left_lay.addWidget(threed, 1)
        lower_left_lay.setStretch(0, 1)
        lower_left_lay.setStretch(1, 1)

        grid.addWidget(pano, 0, 0, 1, 2)
        grid.addWidget(cross, 0, 2)
        grid.addWidget(lower_left, 1, 0, 1, 2)
        grid.addWidget(support, 1, 2)
        grid.setColumnMinimumWidth(0, 0)
        grid.setColumnMinimumWidth(1, 0)
        grid.setColumnMinimumWidth(2, 0)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 2)
        grid.setRowMinimumHeight(1, 0)
        grid.setRowStretch(0, 7)
        grid.setRowStretch(1, 5)
        return grid_widget

    def _build_planning_panel(self) -> QWidget:
        panel = QFrame()
        panel.setFixedWidth(232)
        panel.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        title = QLabel("Planning / Objects")
        title.setStyleSheet("font-size:13px; font-weight:700; color:#9fe8ff; background:transparent; border:none;")
        lay.addWidget(title)

        # Mouse function selector — chooses what a LEFT-drag does on any view (right-drag
        # stays Window/Level, middle = zoom, left+right = pan, wheel = stack scroll).
        mf_head = QLabel("Mouse function")
        mf_head.setStyleSheet("color:#e5edf5; font-size:12px; font-weight:700; background:transparent; border:none;")
        lay.addWidget(mf_head)
        mf_row = QHBoxLayout()
        mf_row.setContentsMargins(0, 0, 0, 0)
        mf_row.setSpacing(4)
        for mlabel, mode in (("Stack", "stack"), ("Pan", "pan"), ("Zoom", "zoom"), ("WW/WL", "wl")):
            mbtn = QPushButton(mlabel)
            mbtn.setCheckable(True)
            mbtn.setChecked(mode == self._mouse_mode)
            mbtn.clicked.connect(lambda _checked=False, m=mode: self._set_mouse_mode(m))
            mbtn.setStyleSheet(
                "QPushButton { color:#b8c7d8; background:#0a1118; border:1px solid #203044; "
                "border-radius:6px; padding:5px 4px; font-size:11px; }"
                "QPushButton:hover { background:#142236; border-color:#22c1dc; }"
                "QPushButton:checked { background:#0891b2; color:#061018; border-color:#22d3ee; }"
            )
            self._mouse_mode_buttons[mode] = mbtn
            mf_row.addWidget(mbtn)
        lay.addLayout(mf_row)

        # Each row is wired to its real function. Measurements activate the existing
        # annotation tools (distance/angle) + the new density/HU probe; View Sync rows
        # toggle real overlays; features without a backend yet give honest feedback.
        planning_actions = {
            "Distance": lambda: self._set_annotation_tool("distance"),
            "Angle": lambda: self._set_annotation_tool("angle"),
            "Density probe": lambda: self._set_annotation_tool("density"),
            "Trace mandibular canal": self._toggle_nerve_trace,
            "Edit control points": self._toggle_nerve_edit,
            "Show on slices": self._toggle_nerve_show,
            "Panoramic reference line": lambda: self._toggle_sync_overlay("pano_reference"),
            "Cross-section position": lambda: self._toggle_sync_overlay("cross_position"),
            "Linked WL": self._relink_window_level,
        }
        self._planning_buttons = {}
        for section, rows in (
            ("Measurements", ("Distance", "Angle", "Density probe")),
            ("Implant Planning", ("Implant library", "Crown axis", "Sleeve / guide")),
            ("Nerve Canal", ("Trace mandibular canal", "Edit control points", "Show on slices")),
            ("View Sync", ("Panoramic reference line", "Cross-section position", "Linked WL")),
        ):
            head = QLabel(section)
            head.setStyleSheet("color:#e5edf5; font-size:12px; font-weight:700; background:transparent; border:none;")
            lay.addWidget(head)
            for row in rows:
                btn = QPushButton(row)
                handler = planning_actions.get(row)
                if handler is not None:
                    btn.clicked.connect(lambda _checked=False, h=handler: h())
                else:
                    btn.clicked.connect(lambda _checked=False, name=row: self._planning_feature_pending(name))
                btn.setStyleSheet(
                    "QPushButton { text-align:left; color:#b8c7d8; background:#0a1118; "
                    "border:1px solid #203044; border-radius:6px; padding:6px 8px; font-size:11px; }"
                    "QPushButton:hover { background:#142236; border-color:#22c1dc; }"
                )
                self._planning_buttons[row] = btn
                lay.addWidget(btn)
            if section == "Nerve Canal":
                self._build_nerve_controls(lay)
        lay.addStretch()
        return panel

    def _build_nerve_controls(self, lay) -> None:
        """Side (L/R) + Undo/Clear row for the mandibular canal trace."""
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        checkable = (
            "QPushButton { color:#b8c7d8; background:#0a1118; border:1px solid #203044; "
            "border-radius:6px; padding:5px 4px; font-size:11px; }"
            "QPushButton:hover { background:#142236; border-color:#22c1dc; }"
            "QPushButton:checked { background:#0891b2; color:#061018; border-color:#22d3ee; }"
        )
        plain = (
            "QPushButton { color:#b8c7d8; background:#0a1118; border:1px solid #203044; "
            "border-radius:6px; padding:5px 4px; font-size:11px; }"
            "QPushButton:hover { background:#142236; border-color:#22c1dc; }"
        )
        for slabel, side in (("Left", "left"), ("Right", "right")):
            sb = QPushButton(slabel)
            sb.setCheckable(True)
            sb.setChecked(side == self._nerve_side)
            sb.clicked.connect(lambda _checked=False, s=side: self._set_nerve_side(s))
            sb.setStyleSheet(checkable)
            self._nerve_side_buttons[side] = sb
            row.addWidget(sb)
        for blabel, slot in (("Undo", self._nerve_undo), ("Clear", self._nerve_clear)):
            b = QPushButton(blabel)
            b.clicked.connect(lambda _checked=False, h=slot: h())
            b.setStyleSheet(plain)
            row.addWidget(b)
        lay.addLayout(row)

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(8, 5, 8, 5)
        self._status_label = QLabel("Waiting for a series...")
        self._status_label.setStyleSheet(
            f"QLabel {{ color:{_MUTED}; font-family:'Roboto','Segoe UI'; font-size:11px; "
            f"background:transparent; border:none; }}"
        )
        lay.addWidget(self._status_label)
        lay.addStretch()
        self._geometry_label = QLabel("")
        self._geometry_label.setStyleSheet(
            f"QLabel {{ color:{_TEXT}; font-family:'Roboto','Segoe UI'; font-size:11px; "
            f"background:transparent; border:none; }}"
        )
        lay.addWidget(self._geometry_label)
        return footer

    def _reset_sync_state(self) -> None:
        self._cross_page = 0
        self._cross_total_pages = 1
        self._cross_visible_sections = []
        self._cross_all_sample_indices = []
        self._selected_cross_section = None
        self._sync_index = None
        self._sync_world = None
        self._sync_source = ""
        self._sync_pano_xy = None
        self._sync_cross_local = None
        self._pending_ruler_point = None
        self._dragging_cross_sync = False
        self._cross_annotations = {}
        self._update_cross_page_controls()

    # --------------------------------------------------------------- data in
    def load_series(self, context: Optional[DentalSeriesContext], volume=None) -> None:
        """Receive a series + bound volume and reconstruct the dental workspace."""
        self._context = context
        self._volume = volume
        self._plane_pixmaps = {}
        self._arch_points = []
        self._apical_arch_points = []
        self._active_arch = "crown"
        self._default_arch_points = []
        self._axial_geom = None
        self._vol = None
        self._plans = {}
        self._slice_idx = {}
        self._wl = None
        self._wl_user_adjusted = False
        self._last_curved_volume = None
        self._last_panoramic_image = None
        self._last_curved_array = None
        self._last_cross_frames = []
        self._last_recon_key = None
        self._last_cross_key = None
        self._last_pano_key = None
        self._reset_sync_state()
        self._annotations = []
        self._pending_annotation = None
        self._nerve_store.clear_all()   # canal indices/world are volume-specific
        self._nerve_mode = "off"
        self._nerve_drag = None
        self._teardown_vtk_mpr()

        if context is None or not context.is_loadable():
            self._set_title("No series loaded")
            self._set_status("No active series - open with a displayed series, or drag a series thumbnail here.")
            self._set_geometry("")
            for key, text in (
                ("panoramic", "No active series\n\nDrag a CBCT thumbnail here."),
                ("axial", "No active series\n\nOpen with a series displayed,\nor drag a series thumbnail here."),
                ("crosssection", ""),
                ("coronal", ""),
                ("sagittal", ""),
                ("3d", ""),
            ):
                self._set_cell(key, text)
            return

        self._set_title(context.summary())
        valid_volume = False
        if volume is not None:
            try:
                valid_volume = bool(volume.is_valid())
            except Exception:
                valid_volume = False

        if not valid_volume:
            self._set_status(f"Series selected · {context.dicom_dir}")
            self._set_geometry("No live scalar volume bound - preview unavailable")
            self._set_cell("panoramic", "Series selected.\nScalar volume preview unavailable.")
            self._set_cell("axial", "Series selected.\nVolume preview unavailable.")
            self._set_cell("crosssection", "")
            return

        self._set_status(f"Building dental CBCT workspace · {context.dicom_dir}")
        self._set_geometry(f"Volume bound (shared) · {volume.summary()}")
        built_vtk = self._build_vtk_mpr(volume, context) if self._vtk_mpr_enabled else False
        if not built_vtk:
            self._render_ortho_previews(volume)
            if self._auto_recon_enabled:
                self._regenerate_dental_recon()
            else:
                self._set_cell("panoramic", "Pick or refine the arch, then click Generate.")
                self._set_cell("crosssection", "Cross sections appear after Generate.")
        self._set_status(f"Active CBCT ready · {context.dicom_dir}")

    # ------------------------------------------------- optional standard MPR host
    def _build_vtk_mpr(self, volume, context) -> bool:
        """Optional troubleshooting embed of the standard MPR viewer.

        The professional dental layout is the default. This remains available through
        ``AIPACS_DENTAL_VTK_MPR=1`` to verify geometry against the standard MPR
        pipeline without mixing the simple Dental Curve MPR viewer into this module.
        """
        try:
            vid = getattr(volume, "image_data", None)
            if vid is None:
                return False
            ww = getattr(context, "window_width", None)
            wc = getattr(context, "window_level", None)
            try:
                from modules.mpr.zeta_mpr._mpr_canonicalize import (
                    canonicalize_enabled, canonicalize_volume,
                )
                if canonicalize_enabled() and getattr(context, "dicom_dir", None):
                    vid = canonicalize_volume(vid, str(context.dicom_dir))
            except Exception:
                logger.debug("[DENTAL] canonicalize skipped", exc_info=True)
            from modules.mpr.zeta_mpr.mpr_viewer.widget import StandardMPRViewer
            viewer = StandardMPRViewer(
                vtk_image_data=vid, parent=self,
                window_width=ww, window_center=wc,
            )
            self._mount_vtk_mpr(viewer)
            self._vtk_mpr = viewer
            return True
        except Exception:
            logger.exception("[DENTAL] standard MPR embed failed; using dental workspace")
            return False

    def _mount_vtk_mpr(self, viewer) -> None:
        if self._center_layout is None:
            return
        if self._dental_grid_widget is not None:
            self._dental_grid_widget.hide()
            self._center_layout.removeWidget(self._dental_grid_widget)
        self._center_layout.addWidget(viewer, 1)
        viewer.show()

    def _teardown_vtk_mpr(self) -> None:
        viewer = self._vtk_mpr
        self._vtk_mpr = None
        if viewer is not None:
            try:
                if hasattr(viewer, "cleanup"):
                    viewer.cleanup()
            except Exception:
                logger.exception("[DENTAL] MPR cleanup failed")
            try:
                if self._center_layout is not None:
                    self._center_layout.removeWidget(viewer)
                viewer.hide()
                viewer.setParent(None)
                viewer.deleteLater()
            except RuntimeError:
                pass
            except Exception:
                logger.exception("[DENTAL] MPR remove failed")
        if self._center_layout is not None and self._dental_grid_widget is not None:
            if self._center_layout.indexOf(self._dental_grid_widget) < 0:
                self._center_layout.addWidget(self._dental_grid_widget, 1)
            self._dental_grid_widget.show()

    def closeEvent(self, event):
        try:
            self._teardown_vtk_mpr()
        except Exception:
            logger.exception("[DENTAL] closeEvent teardown failed")
        super().closeEvent(event)

    # --------------------------------------------------- ortho cells + nav
    def _ortho_cell(self, view: str, title: str):
        """Build a stack-navigable ortho cell; ``installEventFilter(self)`` enables
        mouse-wheel slice navigation and axial arch picking."""
        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
        self._cell_frames[view] = frame
        header = QHBoxLayout()
        t = QLabel(title)
        t.setStyleSheet(
            f"QLabel {{ color:{_TEXT}; font-family:'Roboto','Segoe UI'; font-size:12px; "
            f"font-weight:600; background:transparent; border:none; }}"
        )
        header.addWidget(t)
        header.addStretch()
        idx_label = QLabel("")
        idx_label.setStyleSheet(
            "QLabel { color:#38bdf8; font-size:11px; font-weight:600; background:transparent; border:none; }"
        )
        header.addWidget(idx_label)
        lay.addLayout(header)
        content = QLabel("Drop a series, or open with one active" if view == "axial" else "")
        content.setAlignment(Qt.AlignCenter)
        content.setWordWrap(True)
        content.setStyleSheet(
            f"QLabel {{ color:{_MUTED}; font-family:'Roboto','Segoe UI'; font-size:10px; "
            f"background:#05080c; border:none; border-radius:4px; }}"
        )
        content.setCursor(Qt.CrossCursor)
        lay.addWidget(content, 1)
        self._cells[view] = content
        self._view_idx_labels[view] = idx_label
        if self._nav_enabled:
            slider = QSlider(Qt.Horizontal)
            slider.setEnabled(False)
            slider.setStyleSheet(
                "QSlider::groove:horizontal{height:4px;background:#1f2a37;border-radius:2px;}"
                "QSlider::handle:horizontal{width:12px;background:#38bdf8;border-radius:6px;margin:-5px 0;}"
            )
            slider.valueChanged.connect(lambda val, v=view: self._on_slider(v, val))
            self._view_sliders[view] = slider
            lay.addWidget(slider)
        content.installEventFilter(self)
        return frame

    # --------------------------------------------------------------- preview
    def _render_ortho_previews(self, volume) -> None:
        """Render axial / coronal / sagittal slices from the bound volume.

        Slices are oriented from the volume's DirectionMatrix via
        ``from .core.ortho_orientation import plan_view`` and remain static QImages
        using ``Format_Grayscale8``. This keeps the dental workspace independent of
        VTK render-window lifetime while preserving the same geometry contract.
        """
        try:
            import numpy as np
            from vtkmodules.util import numpy_support
            from .core.ortho_orientation import plan_view

            img = volume.image_data
            dx, dy, dz = volume.dimensions
            scalars = img.GetPointData().GetScalars()
            self._vol = numpy_support.vtk_to_numpy(scalars).reshape(dz, dy, dx)

            sub = self._vol[::4, ::4, ::4]
            lo = float(np.percentile(sub, 1.0))
            hi = float(np.percentile(sub, 99.0))
            if hi - lo < 1e-6:
                lo, hi = float(self._vol.min()), float(self._vol.max())
            self._wl = (lo, hi)

            direction16 = list(volume.direction_matrix)
            self._plans = {}
            self._slice_idx = {}
            for view in ("axial", "coronal", "sagittal"):
                if self._orient_enabled:
                    self._plans[view] = plan_view(direction16, view)
                else:
                    legacy = {"axial": 2, "coronal": 1, "sagittal": 0}[view]
                    rem = [a for a in (0, 1, 2) if a != legacy]
                    self._plans[view] = {"through": legacy, "h": rem[0], "v": rem[1],
                                         "flip_h": False, "flip_v": False, "labels": {}}
                through_n = 2 - self._plans[view]["through"]
                self._slice_idx[view] = self._vol.shape[through_n] // 2

            # NOTE: element [2] is the FULL z DIMENSION (dz), not the middle slice.
            # _vtk_world_to_volume_index unpacks (dx, dy, dz) and uses them as the
            # per-axis clamp limits `min(limit-1, idx)`. Storing dz//2 here clamped the
            # k (depth) index to [0, dz//2-1], so panoramic/cross-section selections
            # could never move the axial through-slice past the middle — desyncing the
            # panoramic+cross group from the axial/sagittal/coronal group. Keep it dz.
            self._axial_geom = (
                dx, dy, dz,
                tuple(volume.origin), tuple(volume.spacing), direction16,
            )
            for view in ("axial", "coronal", "sagittal"):
                lbl = self._cells.get(view)
                if lbl is not None:
                    lbl.setText("")
                self._render_view(view)
        except Exception:
            logger.exception("[DENTAL] ortho preview render failed")
            self._set_cell("axial", "Preview unavailable.")

    def _to_qpix(self, plane2d):
        """Window a 2-D numpy slice (using self._wl) into a grayscale QPixmap."""
        import numpy as np
        from PySide6.QtGui import QImage, QPixmap

        lo, hi = self._wl or (float(plane2d.min()), float(plane2d.max()))
        a = np.ascontiguousarray(plane2d.astype(np.float32))
        norm = np.clip((a - lo) / max(hi - lo, 1e-6), 0.0, 1.0)
        buf = np.ascontiguousarray((norm * 255.0).astype(np.uint8))
        h, w = buf.shape
        qimg = QImage(buf.data, w, h, w, QImage.Format_Grayscale8)
        return QPixmap.fromImage(qimg)

    def _extract_oriented(self, view: str, idx: int):
        """Extract the 2-D slice for ``view`` at ``idx`` along its through-axis."""
        import numpy as np

        plan = self._plans[view]
        through_n = 2 - plan["through"]
        h_n, v_n = 2 - plan["h"], 2 - plan["v"]
        sl = np.take(self._vol, int(idx), axis=through_n)
        rem_n = [a for a in (0, 1, 2) if a != through_n]
        row_pos = 0 if rem_n[0] == v_n else 1
        col_pos = 0 if rem_n[0] == h_n else 1
        img2d = np.transpose(sl, (row_pos, col_pos))
        if plan["flip_v"]:
            img2d = img2d[::-1, :]
        if plan["flip_h"]:
            img2d = img2d[:, ::-1]
        img2d = self._apply_standard_mpr_static_camera_correction(view, img2d)
        return np.ascontiguousarray(img2d)

    def _apply_standard_mpr_static_camera_correction(self, view: str, img2d):
        """Match standard MPR's CT camera display correction for static previews.

        Standard MPR renders sagittal/coronal through camera-facing VTK slices and
        applies CT-specific camera corrections there. Dental Imaging uses static
        ``QImage`` rasters, so apply the equivalent display-only vertical correction
        after the DirectionMatrix slice extraction. This does not alter geometry,
        spacing, indices, or world-coordinate mapping.
        """
        if view in ("coronal", "sagittal"):
            return img2d[::-1, :]
        return img2d

    def _display_row_to_pre_camera_row(self, view: str, row: float, disp_h: int) -> float:
        if view in ("coronal", "sagittal"):
            return float(disp_h - 1) - float(row)
        return float(row)

    def _pre_camera_row_to_display_row(self, view: str, row: float, disp_h: int) -> float:
        if view in ("coronal", "sagittal"):
            return float(disp_h - 1) - float(row)
        return float(row)

    def _render_view(self, view: str) -> None:
        if self._vol is None or view not in self._plans:
            return
        through_n = 2 - self._plans[view]["through"]
        count = int(self._vol.shape[through_n])
        idx = int(self._slice_idx.get(view, count // 2))
        idx = max(0, min(count - 1, idx))
        self._slice_idx[view] = idx
        try:
            self._plane_pixmaps[view] = self._to_qpix(self._extract_oriented(view, idx))
        except Exception:
            logger.exception("[DENTAL] render view %s failed", view)
            return
        self._update_nav_widgets(view, idx, count)
        self._compose_view(view)

    def _update_nav_widgets(self, view: str, idx: int, count: int) -> None:
        lbl = self._view_idx_labels.get(view)
        if lbl is not None:
            lbl.setText(f"{idx + 1} / {count}")
        slider = self._view_sliders.get(view)
        if slider is not None:
            slider.blockSignals(True)
            slider.setEnabled(count > 1)
            slider.setMinimum(0)
            slider.setMaximum(max(0, count - 1))
            slider.setValue(idx)
            slider.blockSignals(False)

    def _compose_view(self, view: str) -> None:
        label = self._cells.get(view)
        base = (self._plane_pixmaps or {}).get(view)
        if label is None or base is None or base.isNull():
            return
        size = label.size()
        if size.width() <= 1 or size.height() <= 1:
            return
        from PySide6.QtCore import QPointF, QRectF
        from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap

        pm = QPixmap(size)
        pm.fill(Qt.black)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            scale, off_x, off_y, img_w, img_h = self._view_scale_offset(
                view, pm.width(), pm.height(), base.width(), base.height()
            )
            painter.drawPixmap(
                QRectF(float(off_x), float(off_y), float(img_w), float(img_h)),
                base,
                QRectF(0.0, 0.0, float(base.width()), float(base.height())),
            )
            painter.save()
            painter.translate(float(off_x), float(off_y))
            w, h = float(img_w), float(img_h)
            plan = self._plans.get(view) or {}
            labels = plan.get("labels") or {}
            if labels and self._orient_enabled:
                painter.setPen(QPen(QColor("#9fe8ff")))
                f = QFont("Roboto", 9, QFont.Bold)
                painter.setFont(f)
                fm = painter.fontMetrics()

                def _draw(text, x, y):
                    painter.drawText(int(x - fm.horizontalAdvance(text) / 2), int(y), text)

                _draw(labels.get("top", ""), w / 2, fm.ascent() + 2)
                _draw(labels.get("bottom", ""), w / 2, h - 3)
                painter.drawText(3, int(h / 2 + fm.ascent() / 2), labels.get("left", ""))
                rt = labels.get("right", "")
                painter.drawText(int(w - 3 - fm.horizontalAdvance(rt)), int(h / 2 + fm.ascent() / 2), rt)
            if view == "axial" and self._axial_geom is not None:
                disp_w, disp_h = self._display_dims("axial")
                sx = w / disp_w if disp_w else 1.0
                sy = h / disp_h if disp_h else 1.0
                if self._arch_show:
                    pts = [
                        QPointF((p[0] + 0.5) * sx, (p[1] + 0.5) * sy)
                        for p in self._arch_display_points()
                    ]
                    painter.setPen(QPen(QColor("#22d3ee"), 2))
                    for i in range(1, len(pts)):
                        painter.drawLine(pts[i - 1], pts[i])
                    painter.setPen(QPen(QColor("#f59e0b"), 2))
                    for pt in pts:
                        painter.drawEllipse(pt, 4.0, 4.0)
                    # Apical (root) arch overlay — dual-arch oblique panoramic. Drawn in
                    # magenta so it reads distinctly from the cyan crown arch.
                    apts = [
                        QPointF((p[0] + 0.5) * sx, (p[1] + 0.5) * sy)
                        for p in self._apical_display_points()
                    ]
                    if apts:
                        painter.setPen(QPen(QColor("#f472b6"), 2))
                        for i in range(1, len(apts)):
                            painter.drawLine(apts[i - 1], apts[i])
                        painter.setPen(QPen(QColor("#ec4899"), 2))
                        for pt in apts:
                            painter.drawEllipse(pt, 3.6, 3.6)
                self._draw_axial_reference_line(painter, sx, sy, w, h)
            self._draw_ortho_sync_overlay(painter, view, w, h)
            self._draw_nerve_overlay(painter, view, w, h)
            disp_w, disp_h = self._display_dims(view)
            if disp_w > 0 and disp_h > 0:
                self._draw_annotations_for_plane(painter, view, w / disp_w, h / disp_h)
            painter.restore()
        finally:
            painter.end()
        label.setPixmap(pm)

    def _draw_ortho_sync_overlay(self, painter, view: str, w: int, h: int) -> None:
        if self._sync_index is None or view not in self._plans or not self._show_cross_position:
            return
        mapped = self._volume_index_to_display(view, self._sync_index)
        if mapped is None:
            return
        disp_w, disp_h = self._display_dims(view)
        if disp_w <= 0 or disp_h <= 0:
            return
        x = (mapped[0] + 0.5) * (w / disp_w)
        y = (mapped[1] + 0.5) * (h / disp_h)
        from PySide6.QtGui import QColor, QPen

        painter.setPen(QPen(QColor(34, 211, 238, 120), 1))
        painter.drawLine(int(x), 0, int(x), int(h))
        painter.drawLine(0, int(y), int(w), int(y))
        self._draw_sync_dot(painter, x, y, radius=2.8)

    def _draw_axial_reference_line(self, painter, sx: float, sy: float, w: int, h: int) -> None:
        if self._selected_cross_section is None or not self._show_cross_position:
            return
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        pos = self._arch_position_for_section(int(self._selected_cross_section), total)
        if pos is None:
            return
        x, y, tx, ty = pos["display"]
        nx, ny = -ty, tx
        length = max(w, h)
        from PySide6.QtGui import QColor, QPen

        x1 = int((x - nx * length) * sx)
        y1 = int((y - ny * length) * sy)
        x2 = int((x + nx * length) * sx)
        y2 = int((y + ny * length) * sy)
        painter.setPen(QPen(QColor(3, 19, 26, 170), 3))
        painter.drawLine(
            x1,
            y1,
            x2,
            y2,
        )
        painter.setPen(QPen(QColor(250, 204, 21, 210), 1))
        painter.drawLine(x1, y1, x2, y2)

    def _on_slider(self, view: str, value: int) -> None:
        if self._vol is None:
            return
        self._slice_idx[view] = int(value)
        self._render_view(view)
        if view == "axial":
            if self._auto_recon_enabled:
                self._regenerate_dental_recon()
            else:
                self._set_cell("panoramic", "Axial slice changed - click Generate to rebuild.")
                self._set_cell("crosssection", "Cross sections appear after Generate.")

    def _scroll_view(self, view: str, steps: int) -> None:
        if self._vol is None or view not in self._plans:
            return
        through_n = 2 - self._plans[view]["through"]
        count = int(self._vol.shape[through_n])
        new_idx = max(0, min(count - 1, int(self._slice_idx.get(view, 0)) + int(steps)))
        if new_idx != self._slice_idx.get(view):
            self._slice_idx[view] = new_idx
            self._render_view(view)

    # ------------------------------------------------------- dental recon views
    def _seed_default_arch(self) -> None:
        if self._axial_geom is None:
            return
        disp_w, disp_h = self._display_dims("axial")
        if disp_w <= 0 or disp_h <= 0:
            return
        pts = []
        steps = 13
        for i in range(steps):
            t = -1.0 + (2.0 * i / max(steps - 1, 1))
            col = (0.16 + 0.68 * (i / max(steps - 1, 1))) * disp_w
            row = (0.62 - 0.22 * (1.0 - t * t)) * disp_h
            idx = self._display_to_volume_index("axial", col, row)
            if idx is None:
                continue
            pts.append({
                "col": float(col),
                "row": float(row),
                "index": idx,
                "world": self._volume_index_to_vtk_world(idx),
                "patient_world": self._volume_index_to_patient_world(idx),
            })
        self._default_arch_points = pts

    def _display_dims(self, view: str):
        if self._vol is None or view not in self._plans:
            return 0, 0
        plan = self._plans[view]
        dims_vtk = (self._vol.shape[2], self._vol.shape[1], self._vol.shape[0])
        return int(dims_vtk[plan["h"]]), int(dims_vtk[plan["v"]])

    def _display_to_volume_index(self, view: str, col: float, row: float):
        """Displayed oriented slice pixel -> raw VTK image index (i, j, k)."""
        if self._vol is None or view not in self._plans:
            return None
        plan = self._plans[view]
        dims_vtk = (self._vol.shape[2], self._vol.shape[1], self._vol.shape[0])
        disp_w, disp_h = self._display_dims(view)
        if disp_w <= 0 or disp_h <= 0:
            return None
        c = max(0, min(disp_w - 1, int(round(float(col)))))
        r = max(0, min(disp_h - 1, int(round(float(row)))))
        r = int(round(self._display_row_to_pre_camera_row(view, r, disp_h)))
        h_idx = (disp_w - 1 - c) if plan.get("flip_h") else c
        v_idx = (disp_h - 1 - r) if plan.get("flip_v") else r
        through_n = 2 - plan["through"]
        through_count = int(self._vol.shape[through_n])
        t_idx = max(0, min(through_count - 1, int(self._slice_idx.get(view, through_count // 2))))
        out = [0, 0, 0]
        out[plan["h"]] = int(h_idx)
        out[plan["v"]] = int(v_idx)
        out[plan["through"]] = int(t_idx)
        return tuple(max(0, min(dims_vtk[a] - 1, out[a])) for a in (0, 1, 2))

    def _volume_index_to_display(self, view: str, index):
        """Raw VTK image index (i, j, k) -> displayed oriented slice pixel."""
        if self._vol is None or view not in self._plans or index is None:
            return None
        plan = self._plans[view]
        disp_w, disp_h = self._display_dims(view)
        h_idx = float(index[plan["h"]])
        v_idx = float(index[plan["v"]])
        col = (disp_w - 1 - h_idx) if plan.get("flip_h") else h_idx
        row = (disp_h - 1 - v_idx) if plan.get("flip_v") else v_idx
        row = self._pre_camera_row_to_display_row(view, row, disp_h)
        return float(col), float(row)

    def _vtk_world_to_volume_index(self, world):
        if self._axial_geom is None or world is None:
            return None
        dx, dy, dz, origin, spacing, _direction16 = self._axial_geom
        out = []
        for a, limit in enumerate((dx, dy, dz)):
            sp = float(spacing[a]) or 1.0
            idx = int(round((float(world[a]) - float(origin[a])) / sp))
            out.append(max(0, min(int(limit) - 1, idx)))
        return tuple(out)

    def _volume_index_to_patient_world(self, index):
        from .core.arch_geometry import slice_index_to_world

        if self._axial_geom is None:
            return (0.0, 0.0, 0.0)
        _dx, _dy, _k, origin, spacing, direction16 = self._axial_geom
        return slice_index_to_world(index[0], index[1], index[2], origin, spacing, direction16)

    def _volume_index_to_vtk_world(self, index):
        """Raw VTK image index -> VTK physical coordinate.

        The working Dental Curve MPR obtains points from the VTK renderer/picker.
        That is the coordinate frame consumed by the curved-reslice engine. It is NOT the
        DICOM LPS patient coordinate computed from ``DirectionMatrix`` field data.
        """
        if self._axial_geom is None:
            return (0.0, 0.0, 0.0)
        _dx, _dy, _k, origin, spacing, _direction16 = self._axial_geom
        return (
            float(origin[0]) + float(index[0]) * float(spacing[0]),
            float(origin[1]) + float(index[1]) * float(spacing[1]),
            float(origin[2]) + float(index[2]) * float(spacing[2]),
        )

    def _arch_items(self):
        return self._arch_points

    def _arch_display_points(self):
        pts = []
        for item in self._arch_items():
            if "index" in item:
                mapped = self._volume_index_to_display("axial", item.get("index"))
                if mapped is not None:
                    pts.append(mapped)
                    continue
            pts.append((float(item.get("col", 0.0)), float(item.get("row", 0.0))))
        return pts

    def _apical_display_points(self):
        """Axial display points of the apical (root) arch (dual-arch overlay)."""
        pts = []
        for item in getattr(self, "_apical_arch_points", []) or []:
            if "index" in item:
                mapped = self._volume_index_to_display("axial", item.get("index"))
                if mapped is not None:
                    pts.append(mapped)
                    continue
            pts.append((float(item.get("col", 0.0)), float(item.get("row", 0.0))))
        return pts

    def _arch_world_points(self):
        return [tuple(p["world"]) for p in self._arch_items() if "world" in p]

    def _resample_polyline(self, points, count: int):
        if not points:
            return []
        if len(points) == 1:
            return [(points[0][0], points[0][1], 1.0, 0.0)] * max(1, count)
        d = [0.0]
        for i in range(1, len(points)):
            d.append(d[-1] + math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
        total = max(d[-1], 1.0)
        out = []
        j = 0
        for n in range(max(1, count)):
            target = total * n / max(count - 1, 1)
            while j < len(d) - 2 and d[j + 1] < target:
                j += 1
            span = max(d[j + 1] - d[j], 1e-6)
            f = (target - d[j]) / span
            x = points[j][0] + (points[j + 1][0] - points[j][0]) * f
            y = points[j][1] + (points[j + 1][1] - points[j][1]) * f
            tx = points[j + 1][0] - points[j][0]
            ty = points[j + 1][1] - points[j][1]
            length = max(math.hypot(tx, ty), 1e-6)
            out.append((x, y, tx / length, ty / length))
        return out

    def _resample_world_polyline(self, points, count: int):
        if not points:
            return []
        if len(points) == 1:
            return [tuple(points[0])] * max(1, count)
        d = [0.0]
        for i in range(1, len(points)):
            d.append(d[-1] + math.dist(points[i - 1], points[i]))
        total = max(d[-1], 1e-6)
        out = []
        j = 0
        for n in range(max(1, count)):
            target = total * n / max(count - 1, 1)
            while j < len(d) - 2 and d[j + 1] < target:
                j += 1
            span = max(d[j + 1] - d[j], 1e-6)
            f = (target - d[j]) / span
            out.append(tuple(float(points[j][a]) + (float(points[j + 1][a]) - float(points[j][a])) * f for a in range(3)))
        return out

    def _desired_cross_section_count(self, curved_depth: Optional[int] = None) -> int:
        base = int(self._cross_section_count)
        limit = int(curved_depth) if curved_depth is not None else 48
        return max(1, min(int(limit), min(48, base)))

    def _arch_position_for_section(self, section: int, total: int):
        total = max(1, int(total))
        section = max(0, min(total - 1, int(section)))
        frame = self._frame_for_section(section, total)
        if frame:
            origin = frame.get("origin")
            tangent = frame.get("tangent")
            idx = self._vtk_world_to_volume_index(origin) if origin is not None else None
            mapped = self._volume_index_to_display("axial", idx) if idx is not None else None
            if idx is not None and mapped is not None:
                tv = self._display_tangent_for_world_vector("axial", tangent) or (1.0, 0.0)
                return {
                    "section": section,
                    "total": total,
                    "display": (float(mapped[0]), float(mapped[1]), float(tv[0]), float(tv[1])),
                    "world": tuple(float(v) for v in origin[:3]),
                    "index": idx,
                    "fraction": section / max(total - 1, 1),
                }
        display_pts = self._resample_polyline(self._arch_display_points(), total)
        world_pts = self._resample_world_polyline(self._arch_world_points(), total)
        if not display_pts or not world_pts:
            return None
        dpt = display_pts[min(section, len(display_pts) - 1)]
        world = world_pts[min(section, len(world_pts) - 1)]
        idx = self._vtk_world_to_volume_index(world)
        return {
            "section": section,
            "total": total,
            "display": dpt,
            "world": world,
            "index": idx,
            "fraction": section / max(total - 1, 1),
        }

    def _nearest_arch_section_from_display(self, col: float, row: float, total: int) -> int:
        samples = self._section_display_samples(max(1, total))
        if not samples:
            return 0
        return min(
            range(len(samples)),
            key=lambda i: math.hypot(float(samples[i][0]) - float(col), float(samples[i][1]) - float(row)),
        )

    def _frame_index_for_section(self, section: int, total: Optional[int] = None) -> Optional[int]:
        if not self._last_cross_frames:
            return None
        section = max(0, int(section))
        if self._cross_all_sample_indices and section < len(self._cross_all_sample_indices):
            return max(0, min(len(self._last_cross_frames) - 1, int(self._cross_all_sample_indices[section])))
        total = int(total) if total is not None else len(self._last_cross_frames)
        if total > 1:
            frame_idx = int(round((section / max(total - 1, 1)) * (len(self._last_cross_frames) - 1)))
        else:
            frame_idx = section
        return max(0, min(len(self._last_cross_frames) - 1, frame_idx))

    def _frame_for_section(self, section: int, total: Optional[int] = None):
        frame_idx = self._frame_index_for_section(section, total)
        if frame_idx is None:
            return None
        return self._last_cross_frames[frame_idx]

    def _section_path_fraction(self, section: int, total: Optional[int] = None) -> float:
        total = int(total) if total is not None else (len(self._cross_all_sample_indices) or self._desired_cross_section_count())
        frame_idx = self._frame_index_for_section(section, total)
        if frame_idx is not None and len(self._last_cross_frames) > 1:
            return max(0.0, min(1.0, float(frame_idx) / float(len(self._last_cross_frames) - 1)))
        return max(0.0, min(1.0, float(section) / max(total - 1, 1)))

    def _pano_display_y_to_source_fraction(self, py: float, height_px: float) -> float:
        display_frac = max(0.0, min(1.0, float(py) / max(1.0, float(height_px) - 1.0)))
        return 1.0 - display_frac

    def _pano_source_fraction_to_display_y(self, src_ly: float, height_px: float) -> float:
        return (1.0 - max(0.0, min(1.0, float(src_ly)))) * max(0.0, float(height_px) - 1.0)

    def _display_tangent_for_world_vector(self, view: str, vector) -> Optional[tuple]:
        if self._axial_geom is None or view not in self._plans or vector is None:
            return None
        _dx, _dy, _dz, _origin, spacing, _direction16 = self._axial_geom
        plan = self._plans[view]
        try:
            h = float(vector[plan["h"]]) / (float(spacing[plan["h"]]) or 1.0)
            v = float(vector[plan["v"]]) / (float(spacing[plan["v"]]) or 1.0)
        except Exception:
            return None
        if plan.get("flip_h"):
            h = -h
        if plan.get("flip_v"):
            v = -v
        if view in ("coronal", "sagittal"):
            v = -v
        length = math.hypot(h, v)
        if length < 1e-6:
            return None
        return h / length, v / length

    def _section_display_samples(self, total: int):
        total = max(1, int(total))
        samples = []
        if self._last_cross_frames:
            for section in range(total):
                frame = self._frame_for_section(section, total)
                origin = frame.get("origin") if frame else None
                tangent = frame.get("tangent") if frame else None
                idx = self._vtk_world_to_volume_index(origin) if origin is not None else None
                mapped = self._volume_index_to_display("axial", idx) if idx is not None else None
                if mapped is None:
                    continue
                tv = self._display_tangent_for_world_vector("axial", tangent) or (1.0, 0.0)
                samples.append((float(mapped[0]), float(mapped[1]), float(tv[0]), float(tv[1])))
            if samples:
                return samples
        return self._resample_polyline(self._arch_display_points(), total)

    def _set_sync_index(self, index, *, source: str = "", section: Optional[int] = None, pano_xy=None, cross_local=None) -> None:
        if index is None:
            return
        self._sync_index = tuple(int(v) for v in index)
        self._sync_world = self._volume_index_to_vtk_world(self._sync_index)
        self._sync_source = source
        self._sync_pano_xy = pano_xy
        self._sync_cross_local = cross_local
        if section is None and self._plans.get("axial"):
            axial_pt = self._volume_index_to_display("axial", self._sync_index)
            if axial_pt is not None:
                total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
                section = self._nearest_arch_section_from_display(axial_pt[0], axial_pt[1], total)
        if section is not None:
            self._selected_cross_section = int(section)
            page_size = max(1, int(self._cross_page_size))
            self._cross_page = max(0, min(self._cross_total_pages - 1, int(section) // page_size))
        for view in ("axial", "coronal", "sagittal"):
            plan = self._plans.get(view)
            if plan:
                self._slice_idx[view] = int(self._sync_index[plan["through"]])
                self._render_view(view)
        if self._last_panoramic_image is not None:
            self._compose_recon_cell("panoramic")
        if self._last_curved_volume is not None:
            self._render_cross_sections_preview()
        self._set_status(f"Sync point set from {source or 'view'}")

    def _set_sync_from_arch_section(self, section: int, *, source: str = "", pano_xy=None, cross_local=None) -> None:
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        pos = self._arch_position_for_section(section, total)
        if pos is None or pos.get("index") is None:
            return
        self._set_sync_index(
            pos["index"],
            source=source,
            section=pos["section"],
            pano_xy=pano_xy,
            cross_local=cross_local,
        )

    def _panoramic_world_index(self, section: int, py: float):
        frame = self._frame_for_section(section, len(self._cross_all_sample_indices) or self._desired_cross_section_count())
        if not frame:
            return None, None
        origin = frame.get("origin")
        binormal = frame.get("binormal")
        if origin is None or binormal is None:
            return None, None
        pano = self._last_panoramic_image
        pix = self._plane_pixmaps.get("panoramic")
        if pano is None or pix is None or pix.isNull():
            return None, None
        try:
            dims = pano.GetDimensions()
            spacing = pano.GetSpacing()
        except Exception:
            dims = (int(pix.width()), int(pix.height()), 1)
            spacing = (1.0, 1.0, 1.0)
        src_ly = self._pano_display_y_to_source_fraction(float(py), float(pix.height()))
        height_mm = max(1.0, (max(1, int(dims[1])) - 1) * float(spacing[1]))
        off_y = (src_ly - 0.5) * height_mm
        world = (
            float(origin[0]) + float(binormal[0]) * off_y,
            float(origin[1]) + float(binormal[1]) * off_y,
            float(origin[2]) + float(binormal[2]) * off_y,
        )
        return world, self._vtk_world_to_volume_index(world)

    def _apply_panoramic_selection(self, section: int, py: float, *, pano_xy=None, source: str = "panoramic") -> None:
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        pos = self._arch_position_for_section(section, total)
        if pos is None or pos.get("index") is None:
            return
        section = int(pos["section"])
        moved_world, moved_index = self._panoramic_world_index(section, py)
        self._selected_cross_section = section
        self._sync_index = tuple(int(v) for v in (moved_index or pos["index"]))
        self._sync_world = tuple(moved_world or pos["world"])
        self._sync_source = source
        self._sync_pano_xy = pano_xy
        pix = self._plane_pixmaps.get("panoramic")
        ly = 0.5
        if pix is not None and not pix.isNull():
            ly = self._pano_display_y_to_source_fraction(float(py), float(pix.height()))
        self._sync_cross_local = (section, 0.5, ly)
        page_size = max(1, int(self._cross_page_size))
        self._cross_page = max(0, min(self._cross_total_pages - 1, section // page_size))
        logger.info(
            "[DENTAL-SYNC] source=panoramic section=%s frame=%s pano_xy=%s cross_local=%s index=%s world=%s",
            section,
            self._frame_index_for_section(section, total),
            self._sync_pano_xy,
            self._sync_cross_local,
            self._sync_index,
            tuple(round(float(v), 3) for v in self._sync_world),
        )
        for view in ("axial", "coronal", "sagittal"):
            plan = self._plans.get(view)
            if plan:
                self._slice_idx[view] = int(self._sync_index[plan["through"]])
                self._render_view(view)
        if self._last_curved_volume is not None:
            self._render_cross_sections_preview()
        if self._last_panoramic_image is not None:
            self._compose_recon_cell("panoramic")
        self._set_status("Sync point set from panoramic")

    def _activate_section_without_rerender(self, section: int, *, source: str = "") -> None:
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        pos = self._arch_position_for_section(section, total)
        if pos is None or pos.get("index") is None:
            return
        self._selected_cross_section = int(pos["section"])
        self._sync_index = tuple(int(v) for v in pos["index"])
        self._sync_world = tuple(pos["world"])
        self._sync_source = source
        self._sync_pano_xy = None
        self._sync_cross_local = (int(pos["section"]), 0.5, 0.5)

    def _regenerate_dental_recon(self, *_args) -> None:
        if self._vol is None or self._volume is None:
            return
        try:
            if hasattr(self, "_layer_label"):
                self._layer_label.setText(f"{int(self._cross_section_count)} pcs")
            self._reset_sync_state()
            self._ensure_curved_volume()
            self._render_cross_sections_preview()
            try:
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
            except Exception:
                pass
            self._render_panoramic_preview()
            self._compose_view("axial")
        except Exception:
            logger.exception("[DENTAL] dental reconstruction failed")

    def _slab_mm(self) -> float:
        try:
            slab_px = max(1, int(os.environ.get("AIPACS_DENTAL_SLAB_PX", "8") or "8"))
        except (TypeError, ValueError):
            slab_px = 8
        spacing = getattr(self._volume, "spacing", (1.0, 1.0, 1.0))
        return max(1.0, slab_px * min(float(s) for s in spacing))

    def _recon_key(self, *, include_layer: bool = True):
        img = getattr(self._volume, "image_data", None)
        pts = tuple(tuple(round(float(v), 3) for v in p[:3]) for p in self._arch_world_points())
        apts = tuple(tuple(round(float(v), 3) for v in p[:3]) for p in self._apical_world_points())
        key = (
            id(img),
            pts,
            apts,
            int(self._desired_cross_section_count()),
            int(os.environ.get("AIPACS_DENTAL_XSECTION_MAX", "48") or "48"),
        )
        if include_layer:
            key += (round(float(self._slab_mm()), 3), os.environ.get("AIPACS_CURVED_MPR_PROJECTION", "weighted"))
        return key

    def _ensure_curved_volume(self) -> bool:
        pts = self._arch_world_points()
        if len(pts) < 2:
            self._last_curved_volume = None
            self._last_curved_array = None
            self._last_cross_frames = []
            self._last_cross_key = None
            self._set_cell("crosssection", "Pick at least two arch points for cross sections.")
            return False
        key = self._recon_key(include_layer=False)
        if self._last_curved_volume is not None and self._last_curved_array is not None and self._last_cross_key == key:
            return True
        try:
            # ``build_curved_reconstruction`` remains available as the legacy
            # combined adapter; Dental Imaging uses the split fast path here so
            # cross-sections can appear before the panoramic image finishes.
            from .core.curved_reconstruction import build_curved_volume

            curved_img, frames = build_curved_volume(
                self._volume.image_data,
                pts,
                cross_section_count=self._desired_cross_section_count(),
                cross_section_size_mm=80.0,
            )
            self._last_curved_volume = curved_img
            self._last_curved_array = self._vtk_image_to_volume(curved_img) if curved_img is not None else None
            self._last_cross_frames = list(frames or [])
            self._last_cross_key = key
            return self._last_curved_array is not None
        except Exception:
            logger.exception("[DENTAL] VTK cross-section reconstruction failed")
            self._set_cell("crosssection", "Cross-section reconstruction unavailable.")
            self._last_curved_volume = None
            self._last_curved_array = None
            self._last_cross_frames = []
            self._last_cross_key = None
            return False

    def _render_panoramic_preview(self) -> None:
        pts = self._arch_world_points()
        if len(pts) < 2:
            self._last_panoramic_image = None
            self._last_pano_key = None
            self._set_cell("panoramic", "Define an arch curve on the axial view.")
            return
        try:
            from .core.curved_reconstruction import build_panoramic_image

            key = self._recon_key(include_layer=True)
            if self._last_panoramic_image is None or self._last_pano_key != key:
                self._last_panoramic_image = build_panoramic_image(
                    self._volume.image_data,
                    pts,
                    slab_thickness_mm=self._slab_mm(),
                    cross_section_count=self._desired_cross_section_count(),
                    projection_type=os.environ.get("AIPACS_CURVED_MPR_PROJECTION", "weighted"),
                    panoramic_height_mm=80.0,
                    apical_world_points=self._apical_world_points(),
                )
                self._last_pano_key = key
            pix = self._to_qpix_auto(
                self._vtk_xy_plane_to_qt_display(
                    self._vtk_image_to_plane(self._last_panoramic_image),
                    roll_180=False,
                )
            )
            self._set_pixmap_cell("panoramic", pix)
        except Exception:
            logger.exception("[DENTAL] VTK panoramic reconstruction failed")
            self._set_cell("panoramic", "Panoramic reconstruction unavailable.")

    def _render_cross_sections_preview(self) -> None:
        import numpy as np

        pts = self._arch_world_points()
        if len(pts) < 2:
            self._set_cell("crosssection", "Pick at least two arch points for cross sections.")
            return
        if not self._ensure_curved_volume():
            self._set_cell("crosssection", "Cross-section reconstruction unavailable.")
            return
        arr = self._last_curved_array
        if arr is None or arr.ndim != 3 or arr.shape[0] <= 0:
            self._set_cell("crosssection", "Cross-section reconstruction unavailable.")
            return
        count = self._desired_cross_section_count(int(arr.shape[0]))
        sample_idx = np.linspace(0, arr.shape[0] - 1, count).astype(int)
        self._cross_all_sample_indices = [int(v) for v in sample_idx]
        page_size = max(1, min(_MAX_CROSS_SECTIONS_PER_PAGE, int(self._cross_page_size)))
        self._cross_page_size = page_size
        self._cross_total_pages = max(1, int(math.ceil(len(sample_idx) / page_size)))
        self._cross_page = max(0, min(self._cross_page, self._cross_total_pages - 1))
        start = self._cross_page * page_size
        end = min(len(sample_idx), start + page_size)
        visible_indices = sample_idx[start:end]
        gap = 3
        sep_value = float(np.percentile(arr, 3.0))
        strips = []
        for idx in visible_indices:
            strips.append(
                self._vtk_xy_plane_to_qt_display(arr[int(idx), :, :], roll_180=True)
            )
        montage, placements = self._build_cross_section_montage(strips, sep_value, gap=gap)
        self._cross_visible_sections = []
        for local_i, placement in enumerate(placements):
            global_section = start + local_i
            self._cross_visible_sections.append({
                "section": global_section,
                "sample_index": int(visible_indices[local_i]),
                "rect": placement,
            })
        visible_section_numbers = {int(item["section"]) for item in self._cross_visible_sections}
        if self._cross_visible_sections and self._selected_cross_section not in visible_section_numbers:
            middle = self._cross_visible_sections[len(self._cross_visible_sections) // 2]
            self._activate_section_without_rerender(int(middle["section"]), source="cross-section page")
        pix = self._to_qpix_auto(montage)
        self._set_pixmap_cell("crosssection", pix)
        self._compose_recon_cell("panoramic")
        for view in ("axial", "coronal", "sagittal"):
            self._compose_view(view)
        self._update_cross_page_controls()

    def _build_cross_section_montage(self, strips, sep_value: float, *, gap: int = 3):
        """Pack cross-sections into a panel-aware montage to avoid empty space."""
        import math
        import numpy as np

        if not strips:
            return np.zeros((1, 1), dtype=np.float32), []
        count = len(strips)
        base_h = max(int(s.shape[0]) for s in strips)
        base_w = max(int(s.shape[1]) for s in strips)
        if count >= 30:
            preferred_cols = 6
        elif count >= 20:
            preferred_cols = 5
        elif count >= 12:
            preferred_cols = 4
        else:
            preferred_cols = 3 if count >= 5 else min(count, 3)
        cell = self._cells.get("crosssection")
        if cell is not None and cell.width() > 1 and cell.height() > 1:
            aspect = float(cell.width()) / max(1.0, float(cell.height()))
            if aspect > 1.35 and count >= 8:
                preferred_cols = min(count, max(preferred_cols, 4))
            elif aspect < 0.72 and count >= 6:
                preferred_cols = max(3, min(preferred_cols, 4))
        cols = max(1, min(count, preferred_cols))
        rows = int(math.ceil(count / cols))
        height = rows * base_h + gap * (rows - 1)
        width = cols * base_w + gap * (cols - 1)
        montage = np.full((height, width), sep_value, dtype=np.float32)
        placements = []
        for n, strip in enumerate(strips):
            r = n // cols
            c = n % cols
            h, w = strip.shape
            yoff = r * (base_h + gap) + max(0, (base_h - h) // 2)
            xoff = c * (base_w + gap) + max(0, (base_w - w) // 2)
            montage[yoff:yoff + h, xoff:xoff + w] = strip
            placements.append((int(xoff), int(yoff), int(w), int(h)))
        return montage, placements

    def _invalidate_recon(self, message: str) -> None:
        self._last_panoramic_image = None
        self._last_curved_volume = None
        self._last_curved_array = None
        self._last_cross_frames = []
        self._last_recon_key = None
        self._last_cross_key = None
        self._last_pano_key = None
        self._reset_sync_state()
        self._set_cell("panoramic", message)
        self._set_cell("crosssection", "Cross sections appear after Generate.")

    def _render_cached_recon_pixmaps(self) -> None:
        if self._last_panoramic_image is not None:
            pix = self._to_qpix_auto(
                self._vtk_xy_plane_to_qt_display(
                    self._vtk_image_to_plane(self._last_panoramic_image),
                    roll_180=False,
                )
            )
            self._set_pixmap_cell("panoramic", pix)
        if self._last_curved_volume is not None:
            self._render_cross_sections_preview()

    def _vtk_xy_plane_to_qt_display(self, plane2d, *, roll_180: bool = False):
        """Convert a VTK XY image plane to the Qt raster display convention.

        VTK's XY image viewer path displays image Y upward, while ``QImage`` row 0
        is screen-top.  The 2D Dental Curve viewer also rolls cross-section cameras
        by 180 degrees.  Apply the equivalent display-only flips here so Advanced
        Dental matches that proven VTK viewer path without changing reslice
        geometry, spacing, or world coordinates.
        """
        if plane2d is None:
            return None
        import numpy as np

        arr = np.asarray(plane2d)
        if roll_180:
            # VTK XY display flip + the 2D Dental Curve cross-section Roll(-180).
            return np.ascontiguousarray(arr[:, ::-1])
        return np.ascontiguousarray(arr[::-1, :])

    def _vtk_image_to_volume(self, vtk_image):
        if vtk_image is None:
            return None
        try:
            import numpy as np
            from vtkmodules.util import numpy_support

            dims = vtk_image.GetDimensions()
            scalars = vtk_image.GetPointData().GetScalars()
            if scalars is None:
                return None
            arr = numpy_support.vtk_to_numpy(scalars)
            return np.asarray(arr).reshape(int(dims[2]), int(dims[1]), int(dims[0]))
        except Exception:
            logger.exception("[DENTAL] vtk image conversion failed")
            return None

    def _vtk_image_to_plane(self, vtk_image):
        arr = self._vtk_image_to_volume(vtk_image)
        if arr is None:
            return None
        if arr.shape[0] == 1:
            return arr[0, :, :]
        return arr[arr.shape[0] // 2, :, :]

    def _to_qpix_auto(self, plane2d):
        import numpy as np

        if plane2d is None:
            return self._to_qpix(np.zeros((1, 1), dtype=np.float32))
        if self._wl_user_adjusted and self._wl is not None:
            return self._to_qpix(plane2d)
        sub = plane2d[:: max(1, plane2d.shape[0] // 256), :: max(1, plane2d.shape[1] // 256)]
        lo = float(np.percentile(sub, 1.0))
        hi = float(np.percentile(sub, 99.0))
        old = self._wl
        self._wl = (lo, float(max(hi, lo + 1.0)))
        try:
            return self._to_qpix(plane2d)
        finally:
            self._wl = old

    # --------------------------------------------------------------- helpers
    def _view_transform(self, plane: str) -> dict:
        return self._view_transforms.setdefault(plane, {"zoom": 1.0, "pan": [0.0, 0.0]})

    def _view_scale_offset(self, plane: str, label_w: float, label_h: float, content_w: float, content_h: float):
        if label_w <= 0 or label_h <= 0 or content_w <= 0 or content_h <= 0:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        tr = self._view_transform(plane)
        base_scale = min(float(label_w) / float(content_w), float(label_h) / float(content_h))
        scale = max(0.02, min(40.0, base_scale * float(tr.get("zoom", 1.0))))
        disp_w = float(content_w) * scale
        disp_h = float(content_h) * scale
        pan = tr.get("pan", [0.0, 0.0])
        off_x = (float(label_w) - disp_w) / 2.0 + float(pan[0])
        off_y = (float(label_h) - disp_h) / 2.0 + float(pan[1])
        return scale, off_x, off_y, disp_w, disp_h

    def _label_click_to_content(
        self,
        plane: str,
        cx: float,
        cy: float,
        content_w: int,
        content_h: int,
        *,
        clamp: bool = False,
    ):
        label = self._cells.get(plane)
        if label is None or content_w <= 0 or content_h <= 0:
            return None
        scale, off_x, off_y, disp_w, disp_h = self._view_scale_offset(
            plane, label.width(), label.height(), content_w, content_h
        )
        if scale <= 0:
            return None
        x = float(cx) - off_x
        y = float(cy) - off_y
        if not clamp and (x < 0 or y < 0 or x >= disp_w or y >= disp_h):
            return None
        x = max(0.0, min(max(0.0, disp_w - 1.0), x))
        y = max(0.0, min(max(0.0, disp_h - 1.0), y))
        col = int(max(0, min(int(content_w) - 1, int(x / scale))))
        row = int(max(0, min(int(content_h) - 1, int(y / scale))))
        return col, row

    def _reset_view_transform(self, plane: Optional[str] = None) -> None:
        if plane is None:
            self._view_transforms = {}
        else:
            self._view_transforms.pop(plane, None)

    def _set_pixmap_cell(self, plane: str, pixmap) -> None:
        lbl = self._cells.get(plane)
        if lbl is None:
            return
        self._plane_pixmaps[plane] = pixmap
        if plane in ("panoramic", "crosssection"):
            self._compose_recon_cell(plane)
            return
        size = lbl.size()
        if size.width() > 1 and size.height() > 1:
            lbl.setPixmap(pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            lbl.setPixmap(pixmap)

    def _rescale_planes(self) -> None:
        for view in ("axial", "coronal", "sagittal"):
            self._compose_view(view)
        for view in ("panoramic", "crosssection"):
            self._compose_recon_cell(view)

    def _compose_recon_cell(self, plane: str) -> None:
        label = self._cells.get(plane)
        base = self._plane_pixmaps.get(plane)
        if label is None or base is None or base.isNull():
            return
        size = label.size()
        if size.width() <= 1 or size.height() <= 1:
            label.setPixmap(base)
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

        pm = QPixmap(size)
        pm.fill(Qt.black)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
            scale, off_x, off_y, img_w, img_h = self._view_scale_offset(
                plane, pm.width(), pm.height(), base.width(), base.height()
            )
            painter.drawPixmap(
                QRectF(float(off_x), float(off_y), float(img_w), float(img_h)),
                base,
                QRectF(0.0, 0.0, float(base.width()), float(base.height())),
            )
            painter.save()
            painter.translate(float(off_x), float(off_y))
            sx = float(img_w) / max(1, base.width())
            sy = float(img_h) / max(1, base.height())
            if plane == "panoramic":
                self._draw_panoramic_overlays(painter, sx, sy, base.width(), base.height())
            elif plane == "crosssection":
                self._draw_cross_section_overlays(painter, sx, sy)
            painter.restore()
        finally:
            painter.end()
        label.setPixmap(pm)

    def _draw_sync_dot(self, painter, x: float, y: float, radius: float = 3.0) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QBrush, QPen

        painter.setPen(QPen(QColor(3, 19, 26, 180), 2))
        painter.setBrush(QBrush(QColor(255, 255, 255, 180)))
        painter.drawEllipse(QPointF(float(x), float(y)), float(radius + 1.2), float(radius + 1.2))
        painter.setPen(QPen(QColor("#03131a"), 1))
        painter.setBrush(QBrush(QColor("#22d3ee")))
        painter.drawEllipse(QPointF(float(x), float(y)), float(radius), float(radius))
        painter.setBrush(Qt.NoBrush)

    def _draw_annotation_item(self, painter, annotation_type: str, points: list, label: str = "") -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QBrush, QFont, QPainter, QPen

        if not points:
            return
        pts = [(float(p[0]), float(p[1])) for p in points]
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QPen(QColor(3, 19, 26, 210), 4))
        if annotation_type in ("distance", "angle") and len(pts) >= 2:
            for i in range(1, len(pts)):
                painter.drawLine(int(pts[i - 1][0]), int(pts[i - 1][1]), int(pts[i][0]), int(pts[i][1]))
        painter.setPen(QPen(QColor("#22d3ee"), 1))
        if annotation_type in ("distance", "angle") and len(pts) >= 2:
            for i in range(1, len(pts)):
                painter.drawLine(int(pts[i - 1][0]), int(pts[i - 1][1]), int(pts[i][0]), int(pts[i][1]))
        painter.setBrush(QBrush(QColor(250, 204, 21, 225)))
        for x, y in pts:
            painter.setPen(QPen(QColor(3, 19, 26, 210), 2))
            painter.drawEllipse(QPointF(x, y), 3.4, 3.4)
            painter.setPen(QPen(QColor("#facc15"), 1))
            painter.drawEllipse(QPointF(x, y), 2.2, 2.2)
        painter.setBrush(Qt.NoBrush)
        if annotation_type in ("text", "marker", "density"):
            x, y = pts[-1]
            painter.setPen(QPen(QColor("#facc15"), 2))
            painter.drawLine(int(x - 6), int(y), int(x + 6), int(y))
            painter.drawLine(int(x), int(y - 6), int(x), int(y + 6))
        text = str(label or "")
        if text:
            x, y = pts[-1]
            painter.setFont(QFont("Roboto", 8, QFont.Bold))
            painter.setPen(QPen(QColor(3, 19, 26, 230), 3))
            painter.drawText(int(x + 7), int(y - 7), text)
            painter.setPen(QPen(QColor("#e5edf5"), 1))
            painter.drawText(int(x + 7), int(y - 7), text)

    def _draw_annotations_for_plane(self, painter, layout_id: str, sx: float, sy: float) -> None:
        for item in self._annotations:
            if not self._annotation_visible_on(item, layout_id):
                continue
            pts = []
            for p in item.get("geometry_coordinates", []):
                pts.append((float(p.get("x", 0.0)) * sx, float(p.get("y", 0.0)) * sy))
            label = self._annotation_display_label(item)
            self._draw_annotation_item(painter, item.get("annotation_type", "marker"), pts, label)
        if self._pending_annotation and self._pending_annotation.get("layout_id") == layout_id:
            pts = [
                (float(p.get("x", 0.0)) * sx, float(p.get("y", 0.0)) * sy)
                for p in self._pending_annotation.get("points", [])
            ]
            self._draw_annotation_item(painter, self._pending_annotation.get("tool", "marker"), pts, "")

    def _draw_panoramic_overlays(self, painter, sx: float, sy: float, src_w: int, src_h: int) -> None:
        from PySide6.QtGui import QColor, QPen

        section = self._selected_cross_section
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        if section is None and self._sync_index is not None:
            axial_pt = self._volume_index_to_display("axial", self._sync_index)
            if axial_pt is not None:
                section = self._nearest_arch_section_from_display(axial_pt[0], axial_pt[1], total)
        if section is not None and self._show_pano_reference:
            x = self._section_path_fraction(int(section), total) * max(0, src_w - 1) * sx
            painter.setPen(QPen(QColor(3, 19, 26, 170), 3))
            painter.drawLine(int(x), 0, int(x), int(src_h * sy))
            painter.setPen(QPen(QColor(250, 204, 21, 220), 1))
            painter.drawLine(int(x), 0, int(x), int(src_h * sy))
            y = (self._sync_pano_xy[1] if self._sync_pano_xy else src_h * 0.5) * sy
            self._draw_sync_dot(painter, x, y, radius=3.2)
        self._draw_annotations_for_plane(painter, "panoramic", sx, sy)

    def _draw_annotations_for_cross_section_item(self, painter, section: int, x: float, y: float, w: float, h: float, sx: float, sy: float) -> None:
        def mapped(point):
            return ((x + float(point.get("x", 0.5)) * w) * sx, (y + float(point.get("y", 0.5)) * h) * sy)

        for item in self._annotations:
            if not self._annotation_visible_on(item, "crosssection", section=section):
                continue
            pts = []
            for p in item.get("geometry_coordinates", []):
                if item.get("visibility_mode") != "pinned" and int(p.get("section", section)) != int(section):
                    continue
                pts.append(mapped(p))
            if not pts and item.get("visibility_mode") == "pinned":
                pts = [mapped(p) for p in item.get("geometry_coordinates", [])]
            label = self._annotation_display_label(item)
            self._draw_annotation_item(painter, item.get("annotation_type", "marker"), pts, label)
        if self._pending_annotation and self._pending_annotation.get("layout_id") == "crosssection":
            pts = []
            for p in self._pending_annotation.get("points", []):
                if int(p.get("section", section)) == int(section):
                    pts.append(mapped(p))
            self._draw_annotation_item(painter, self._pending_annotation.get("tool", "marker"), pts, "")

    def _draw_cross_section_overlays(self, painter, sx: float, sy: float) -> None:
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QColor, QBrush, QFont, QPen

        selected = self._selected_cross_section
        painter.setFont(QFont("Roboto", 8, QFont.Bold))
        for item in self._cross_visible_sections:
            x, y, w, h = item["rect"]
            section = int(item["section"])
            rx, ry, rw, rh = int(x * sx), int(y * sy), int(w * sx), int(h * sy)
            painter.setPen(QPen(QColor(148, 163, 184, 95), 1))
            painter.drawRect(rx, ry, rw, rh)
            painter.setPen(QPen(QColor(159, 232, 255, 210), 1))
            painter.drawText(rx + 4, ry + 12, str(section + 1))
            if selected is not None and section == int(selected):
                painter.setPen(QPen(QColor(3, 19, 26, 190), 3))
                painter.drawRect(rx, ry, rw, rh)
                painter.setPen(QPen(QColor(250, 204, 21, 230), 2))
                painter.drawRect(rx, ry, rw, rh)
                lx, ly = 0.5, 0.5
                if self._sync_cross_local and int(self._sync_cross_local[0]) == section:
                    lx, ly = float(self._sync_cross_local[1]), float(self._sync_cross_local[2])
                self._draw_sync_dot(painter, (x + lx * w) * sx, (y + ly * h) * sy, radius=3.2)
            ann = self._cross_annotations.get(section, [])
            for obj in ann:
                if obj.get("kind") == "ruler":
                    p1 = obj.get("p1", (0.0, 0.0))
                    p2 = obj.get("p2", (0.0, 0.0))
                    x1, y1 = (x + float(p1[0]) * w) * sx, (y + float(p1[1]) * h) * sy
                    x2, y2 = (x + float(p2[0]) * w) * sx, (y + float(p2[1]) * h) * sy
                    painter.setPen(QPen(QColor(3, 19, 26, 190), 3))
                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                    painter.setPen(QPen(QColor(34, 211, 238, 230), 1))
                    painter.drawLine(int(x1), int(y1), int(x2), int(y2))
                    self._draw_sync_dot(painter, x1, y1, radius=2.2)
                    self._draw_sync_dot(painter, x2, y2, radius=2.2)
                elif obj.get("kind") == "annot":
                    p = obj.get("p", (0.5, 0.5))
                    px, py = (x + float(p[0]) * w) * sx, (y + float(p[1]) * h) * sy
                    painter.setPen(QPen(QColor(3, 19, 26, 190), 2))
                    painter.setBrush(QBrush(QColor(250, 204, 21, 210)))
                    painter.drawEllipse(QPointF(float(px), float(py)), 3.2, 3.2)
                    painter.setBrush(Qt.NoBrush)
            if self._pending_ruler_point and int(self._pending_ruler_point[0]) == section:
                p = self._pending_ruler_point[1]
                px, py = (x + float(p[0]) * w) * sx, (y + float(p[1]) * h) * sy
                painter.setPen(QPen(QColor(34, 211, 238, 220), 1))
                painter.drawEllipse(QPointF(float(px), float(py)), 4.0, 4.0)
            self._draw_annotations_for_cross_section_item(painter, section, x, y, w, h, sx, sy)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_planes()
        QTimer.singleShot(0, self._rescale_planes)

    def _set_cell(self, plane: str, text: str) -> None:
        lbl = self._cells.get(plane)
        if lbl is not None:
            self._plane_pixmaps.pop(plane, None)
            lbl.setText(text)

    def _set_title(self, text: str) -> None:
        if self._title_series_label is not None:
            self._title_series_label.setText(text)

    def _set_status(self, text: str) -> None:
        if self._status_label is not None:
            self._status_label.setText(text)

    def _set_geometry(self, text: str) -> None:
        if self._geometry_label is not None:
            self._geometry_label.setText(text)

    @property
    def context(self) -> Optional[DentalSeriesContext]:
        return self._context

    # ----------------------------------------------------------- annotations
    def _set_annotation_tool(self, tool: str) -> None:
        requested = str(tool or "sync")
        if requested == "sync" or requested == self._annotation_tool:
            self._set_default_mouse_mode()
            self._set_status("Default mouse interaction")
            return
        self._annotation_tool = requested
        self._active_cross_tool = "sync"
        self._pending_annotation = None
        self._pending_ruler_point = None
        for name, btn in self._tool_buttons.items():
            try:
                btn.blockSignals(True)
                btn.setChecked(name == self._annotation_tool)
                btn.blockSignals(False)
            except Exception:
                pass
        labels = {
            "sync": "Sync",
            "distance": "Ruler / Distance",
            "angle": "Angle",
            "density": "Density / HU probe",
            "text": "Text note",
            "marker": "Dental marker",
        }
        self._set_status(f"Annotation tool: {labels.get(self._annotation_tool, self._annotation_tool)}")

    def _set_annotation_visibility_mode(self, mode: str) -> None:
        mode = mode if mode in ("slice_based", "pinned", "hidden") else "slice_based"
        self._annotation_visibility_mode = mode
        self._set_status(f"New annotation visibility: {mode.replace('_', ' ')}")

    def _toggle_annotations_visible(self) -> None:
        self._annotations_visible = not bool(self._annotations_visible)
        self._redraw_annotation_views()
        self._set_status("Annotations visible" if self._annotations_visible else "Annotations hidden")

    def set_annotation_visibility(self, annotation_id: int, mode: str) -> bool:
        mode = mode if mode in ("slice_based", "pinned", "hidden") else "slice_based"
        for item in self._annotations:
            if int(item.get("annotation_id", -1)) == int(annotation_id):
                item["visibility_mode"] = mode
                item["updated_at"] = time.time()
                self._redraw_annotation_views()
                return True
        return False

    def pin_annotation(self, annotation_id: int) -> bool:
        return self.set_annotation_visibility(annotation_id, "pinned")

    def hide_annotation(self, annotation_id: int) -> bool:
        return self.set_annotation_visibility(annotation_id, "hidden")

    def show_annotation_on_slice(self, annotation_id: int) -> bool:
        return self.set_annotation_visibility(annotation_id, "slice_based")

    def _current_slice_for_layout(self, layout_id: str, section=None):
        if layout_id in ("axial", "coronal", "sagittal"):
            return int(self._slice_idx.get(layout_id, 0))
        if layout_id == "crosssection":
            return int(section if section is not None else (self._selected_cross_section or 0))
        return 0

    def _new_annotation(
        self,
        layout_id: str,
        annotation_type: str,
        points: list,
        *,
        section=None,
        text_label: str = "",
    ) -> dict:
        self._annotation_id_counter += 1
        now = time.time()
        item = {
            "annotation_id": self._annotation_id_counter,
            "annotation_type": annotation_type,
            "layout_id": layout_id,
            "view_type": layout_id,
            "slice_index": self._current_slice_for_layout(layout_id, section),
            "geometry_coordinates": list(points),
            "visibility_mode": self._annotation_visibility_mode,
            "created_at": now,
            "updated_at": now,
            "style": {"color": "#22d3ee", "accent": "#facc15"},
            "text_label": text_label,
            "measurement_value": self._measurement_text(layout_id, annotation_type, points),
        }
        self._annotations.append(item)
        return item

    def _annotation_visible_on(self, item: dict, layout_id: str, *, section=None) -> bool:
        if not self._annotations_visible:
            return False
        if item.get("layout_id") != layout_id:
            return False
        mode = item.get("visibility_mode", "slice_based")
        if mode == "hidden":
            return False
        if mode == "pinned":
            return True
        return int(item.get("slice_index", 0)) == self._current_slice_for_layout(layout_id, section)

    def _measurement_text(self, layout_id: str, annotation_type: str, points: list) -> str:
        if annotation_type == "distance" and len(points) >= 2:
            mm = self._distance_mm(layout_id, points[0], points[1])
            return f"{mm:.1f} mm" if mm is not None else "Distance"
        if annotation_type == "angle" and len(points) >= 3:
            deg = self._angle_degrees(layout_id, points[0], points[1], points[2])
            return f"{deg:.1f} deg" if deg is not None else "Angle"
        if annotation_type == "density" and len(points) >= 1:
            hu = self._density_value_at(layout_id, points[0])
            return f"{hu:.0f} HU" if hu is not None else "Density"
        return ""

    def _annotation_index_for_point(self, layout_id: str, point: dict):
        """Resolve an annotation click point on any view to a raw volume index (i,j,k)."""
        if layout_id in ("axial", "coronal", "sagittal"):
            return self._display_to_volume_index(layout_id, point.get("x", 0.0), point.get("y", 0.0))
        if layout_id == "crosssection":
            _w, idx = self._cross_section_world_index(
                int(point.get("section", 0)), float(point.get("x", 0.5)), float(point.get("y", 0.5))
            )
            return idx
        if layout_id == "panoramic":
            pix = self._plane_pixmaps.get("panoramic")
            if pix is not None and not pix.isNull():
                total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
                section = int(round((float(point.get("x", 0.0)) / max(1, pix.width() - 1)) * max(total - 1, 0)))
                _w, idx = self._panoramic_world_index(section, float(point.get("y", 0.0)))
                return idx
        return None

    def _density_value_at(self, layout_id: str, point: dict):
        """Sample the CBCT gray value (HU probe) at an annotation point's voxel."""
        idx = self._annotation_index_for_point(layout_id, point)
        if idx is None or self._vol is None:
            return None
        try:
            i, j, k = int(idx[0]), int(idx[1]), int(idx[2])
            if (0 <= k < self._vol.shape[0]
                    and 0 <= j < self._vol.shape[1]
                    and 0 <= i < self._vol.shape[2]):
                return float(self._vol[k, j, i])
        except Exception:
            return None
        return None

    def _point_world_for_annotation(self, layout_id: str, point: dict):
        if layout_id in ("axial", "coronal", "sagittal"):
            idx = self._display_to_volume_index(layout_id, point.get("x", 0.0), point.get("y", 0.0))
            return self._volume_index_to_vtk_world(idx) if idx is not None else None
        if layout_id == "crosssection":
            world, _idx = self._cross_section_world_index(
                int(point.get("section", 0)), float(point.get("x", 0.5)), float(point.get("y", 0.5))
            )
            return world
        if layout_id == "panoramic":
            pano = self._last_panoramic_image
            if pano is not None:
                spacing = pano.GetSpacing()
                return (
                    float(point.get("x", 0.0)) * float(spacing[0]),
                    float(point.get("y", 0.0)) * float(spacing[1]),
                    0.0,
                )
        return None

    def _distance_mm(self, layout_id: str, p1: dict, p2: dict):
        w1 = self._point_world_for_annotation(layout_id, p1)
        w2 = self._point_world_for_annotation(layout_id, p2)
        if w1 is None or w2 is None:
            return None
        return math.dist(w1, w2)

    def _angle_degrees(self, layout_id: str, p1: dict, p2: dict, p3: dict):
        w1 = self._point_world_for_annotation(layout_id, p1)
        w2 = self._point_world_for_annotation(layout_id, p2)
        w3 = self._point_world_for_annotation(layout_id, p3)
        if w1 is None or w2 is None or w3 is None:
            return None
        v1 = [float(w1[i]) - float(w2[i]) for i in range(3)]
        v2 = [float(w3[i]) - float(w2[i]) for i in range(3)]
        n1 = math.sqrt(sum(v * v for v in v1))
        n2 = math.sqrt(sum(v * v for v in v2))
        if n1 <= 1e-6 or n2 <= 1e-6:
            return None
        dot = max(-1.0, min(1.0, sum(v1[i] * v2[i] for i in range(3)) / (n1 * n2)))
        return math.degrees(math.acos(dot))

    def _annotation_point_from_click(self, layout_id: str, cx: float, cy: float):
        if layout_id in ("axial", "coronal", "sagittal"):
            label = self._cells.get(layout_id)
            if label is None:
                return None
            disp_w, disp_h = self._display_dims(layout_id)
            rc = self._label_click_to_content(layout_id, cx, cy, disp_w, disp_h)
            if rc is None:
                return None
            return {"x": float(rc[0]), "y": float(rc[1])}, None
        if layout_id == "panoramic":
            rc = self._pixmap_source_click("panoramic", cx, cy, clamp=True)
            if rc is None:
                return None
            return {"x": float(rc[0]), "y": float(rc[1])}, None
        if layout_id == "crosssection":
            hit = self._cross_section_hit(cx, cy)
            if hit is None:
                return None
            section, lx, ly = hit
            return {"section": int(section), "x": float(lx), "y": float(ly)}, int(section)
        return None

    def _handle_annotation_click(self, layout_id: str, cx: float, cy: float) -> bool:
        if self._annotation_tool == "sync":
            return False
        resolved = self._annotation_point_from_click(layout_id, cx, cy)
        if resolved is None:
            return False
        point, section = resolved
        if layout_id == "crosssection":
            self._apply_cross_section_selection(section, point["x"], point["y"], source="annotation", update_status=False)
        needed = {"distance": 2, "angle": 3, "text": 1, "marker": 1, "density": 1}.get(self._annotation_tool, 1)
        if self._pending_annotation is None or self._pending_annotation.get("layout_id") != layout_id:
            self._pending_annotation = {"layout_id": layout_id, "tool": self._annotation_tool, "points": []}
        if self._pending_annotation.get("tool") != self._annotation_tool:
            self._pending_annotation = {"layout_id": layout_id, "tool": self._annotation_tool, "points": []}
        self._pending_annotation["points"].append(point)
        if len(self._pending_annotation["points"]) >= needed:
            text_label = "Note" if self._annotation_tool == "text" else ("Marker" if self._annotation_tool == "marker" else "")
            item = self._new_annotation(
                layout_id,
                self._annotation_tool,
                self._pending_annotation["points"][:needed],
                section=section,
                text_label=text_label,
            )
            self._pending_annotation = None
            self._set_status(f"Added {item['annotation_type']} annotation")
            self._set_default_mouse_mode()
        else:
            self._set_status(f"{self._annotation_tool}: point {len(self._pending_annotation['points'])}/{needed}")
        self._redraw_annotation_views()
        return True

    def _redraw_annotation_views(self) -> None:
        for view in ("axial", "coronal", "sagittal"):
            self._compose_view(view)
        for view in ("panoramic", "crosssection"):
            self._compose_recon_cell(view)

    # ------------------------------------------- annotation right-click menu
    def _annotation_display_label(self, item) -> str:
        """Combine a custom label with the measured value for display."""
        name = str(item.get("text_label") or "").strip()
        value = str(item.get("measurement_value") or "").strip()
        if name and value:
            return f"{name}: {value}"
        return name or value

    @staticmethod
    def _seg_dist_2d(p, a, b) -> float:
        ax, ay = float(a[0]), float(a[1])
        bx, by = float(b[0]), float(b[1])
        px, py = float(p[0]), float(p[1])
        abx, aby = bx - ax, by - ay
        denom = abx * abx + aby * aby
        t = 0.0 if denom <= 1e-9 else max(0.0, min(1.0, ((px - ax) * abx + (py - ay) * aby) / denom))
        return math.hypot(px - (ax + abx * t), py - (ay + aby * t))

    def _min_dist_point_to_polyline(self, pt, pts) -> Optional[float]:
        if not pts:
            return None
        if len(pts) == 1:
            return math.hypot(float(pt[0]) - float(pts[0][0]), float(pt[1]) - float(pts[0][1]))
        return min(self._seg_dist_2d(pt, pts[i - 1], pts[i]) for i in range(1, len(pts)))

    def _annotation_hit_test(self, layout_id: str, cx: float, cy: float):
        """Return the nearest VISIBLE annotation on ``layout_id`` under the click, or None."""
        resolved = self._annotation_point_from_click(layout_id, cx, cy)
        if resolved is None:
            return None
        point, section = resolved
        cross = layout_id == "crosssection"
        click = (float(point.get("x", 0.5 if cross else 0.0)), float(point.get("y", 0.5 if cross else 0.0)))
        thresh = 0.06 if cross else 12.0
        best, best_d = None, thresh
        for item in self._annotations:
            if item.get("layout_id") != layout_id:
                continue
            if not self._annotation_visible_on(item, layout_id, section=section):
                continue
            pts = []
            for p in item.get("geometry_coordinates", []):
                if cross and int(p.get("section", -1)) != int(section if section is not None else -2):
                    continue
                pts.append((float(p.get("x", 0.0)), float(p.get("y", 0.0))))
            d = self._min_dist_point_to_polyline(click, pts)
            if d is not None and d <= best_d:
                best, best_d = item, d
        return best

    def _overlay_line_hit_test(self, plane: str, cx: float, cy: float):
        """Detect a right-click on the arch curve or a nerve canal line -> (kind, side)."""
        resolved = self._annotation_point_from_click(plane, cx, cy)
        if resolved is None:
            return None
        point, _section = resolved
        click = (float(point.get("x", 0.0)), float(point.get("y", 0.0)))
        thresh = 12.0
        if plane == "axial" and getattr(self, "_arch_show", True):
            arch = [(float(p[0]), float(p[1])) for p in self._arch_display_points()]
            d = self._min_dist_point_to_polyline(click, arch)
            if d is not None and d <= thresh:
                return ("arch", None)
        if self._nerve_show and plane in self._plans:
            for side in ("left", "right"):
                pts = self._nerve_store.points(side)
                if not pts:
                    continue
                samples = (self._nerve_store.resampled_world(side, max(2, len(pts) * 8))
                           if len(pts) >= 2 else [pts[0]["world"]])
                disp = []
                for wpt in samples:
                    d = self._volume_index_to_display(plane, self._vtk_world_to_volume_index(wpt))
                    if d is not None:
                        disp.append((d[0], d[1]))
                dd = self._min_dist_point_to_polyline(click, disp)
                if dd is not None and dd <= thresh:
                    return ("nerve", side)
        return None

    def _maybe_show_overlay_context_menu(self, plane: str, cx: float, cy: float, event) -> bool:
        try:
            gp = event.globalPosition().toPoint()
        except Exception:
            try:
                gp = event.globalPos()
            except Exception:
                return False
        item = self._annotation_hit_test(plane, cx, cy)
        if item is not None:
            self._show_annotation_context_menu(item, gp)
            return True
        line = self._overlay_line_hit_test(plane, cx, cy)
        if line is not None:
            self._show_line_context_menu(line[0], line[1], gp)
            return True
        return False

    def _set_annotation_vis(self, annotation_id: int, mode: str) -> None:
        self.set_annotation_visibility(annotation_id, mode)
        msg = {"pinned": "pinned - visible on all slices", "hidden": "hidden",
               "slice_based": "shown on its own slice only"}.get(mode, mode)
        self._set_status(f"Annotation {msg}")

    def _show_annotation_context_menu(self, item, gp) -> None:
        from PySide6.QtWidgets import QMenu

        aid = int(item.get("annotation_id", -1))
        mode = item.get("visibility_mode", "slice_based")
        name = self._annotation_display_label(item) or item.get("annotation_type", "annotation")
        menu = QMenu(self)
        header = menu.addAction(f"[{item.get('annotation_type', '')}] {name}")
        header.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Rename / label...", lambda: self._rename_annotation(item))
        pin = menu.addAction("Pin - visible on all slices", lambda: self._set_annotation_vis(aid, "pinned"))
        pin.setCheckable(True)
        pin.setChecked(mode == "pinned")
        unpin = menu.addAction("Unpin - this slice only", lambda: self._set_annotation_vis(aid, "slice_based"))
        unpin.setCheckable(True)
        unpin.setChecked(mode == "slice_based")
        hide = menu.addAction("Hide", lambda: self._set_annotation_vis(aid, "hidden"))
        hide.setCheckable(True)
        hide.setChecked(mode == "hidden")
        menu.addSeparator()
        menu.addAction("Delete", lambda: self._delete_annotation(item))
        menu.exec(gp)

    def _rename_annotation(self, item) -> None:
        from PySide6.QtWidgets import QInputDialog

        current = str(item.get("text_label") or "")
        text, ok = QInputDialog.getText(self, "Rename annotation", "Label:", text=current)
        if not ok:
            return
        item["text_label"] = str(text or "").strip()
        item["updated_at"] = time.time()
        self._redraw_annotation_views()
        self._set_status(
            f"Annotation labelled '{item['text_label']}'" if item["text_label"] else "Annotation label cleared"
        )

    def _delete_annotation(self, item) -> None:
        try:
            self._annotations = [a for a in self._annotations if a is not item]
        except Exception:
            pass
        self._redraw_annotation_views()
        self._set_status("Annotation deleted")

    def _set_arch_show(self, show: bool) -> None:
        self._arch_show = bool(show)
        self._compose_view("axial")
        self._set_status("Dental arch " + ("shown" if self._arch_show else "hidden"))

    def _show_line_context_menu(self, kind: str, side, gp) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        if kind == "arch":
            header = menu.addAction("Dental arch curve")
            header.setEnabled(False)
            menu.addSeparator()
            act = menu.addAction("Show on axial", lambda: self._set_arch_show(not self._arch_show))
            act.setCheckable(True)
            act.setChecked(getattr(self, "_arch_show", True))
        else:
            header = menu.addAction(f"{str(side).title()} nerve canal")
            header.setEnabled(False)
            menu.addSeparator()
            act = menu.addAction("Show on slices", self._toggle_nerve_show)
            act.setCheckable(True)
            act.setChecked(self._nerve_show)
            menu.addAction("Clear this canal", lambda: (self._set_nerve_side(side), self._nerve_clear()))
        menu.exec(gp)

    def _in_drawing_mode(self) -> bool:
        """True while a point-creating tool is active — canal trace/edit, arch pick,
        or a multi-point annotation. In these modes right-click must NOT add a point."""
        if getattr(self, "_nerve_mode", "off") != "off":
            return True
        if getattr(self, "_arch_enabled", False) and getattr(self, "_arch_pick_mode", False):
            return True
        if getattr(self, "_annotation_tool", "sync") not in ("sync", "", None):
            return True
        return False

    def _show_drawing_context_menu(self, plane, cx: float, cy: float, event) -> None:
        """Right-click menu while drawing (no annotation/line was hit): delete the
        point/annotation, clear the line/canal, and show/hide — never add a point."""
        from PySide6.QtWidgets import QMenu

        try:
            gp = event.globalPosition().toPoint()
        except Exception:
            try:
                gp = event.globalPos()
            except Exception:
                return
        menu = QMenu(self)
        if getattr(self, "_nerve_mode", "off") != "off":
            side = self._nerve_side
            header = menu.addAction(f"{str(side).title()} nerve canal")
            header.setEnabled(False)
            menu.addSeparator()
            if plane is not None:
                menu.addAction(
                    "Delete point under cursor",
                    lambda: self._nerve_delete_nearest(plane, float(cx), float(cy)),
                )
            menu.addAction("Delete last point", self._nerve_undo)
            menu.addAction("Clear this canal", self._nerve_clear)
            menu.addSeparator()
            show = menu.addAction("Show on slices", self._toggle_nerve_show)
            show.setCheckable(True)
            show.setChecked(bool(self._nerve_show))
        elif getattr(self, "_arch_enabled", False) and getattr(self, "_arch_pick_mode", False):
            header = menu.addAction("Dental arch curve")
            header.setEnabled(False)
            menu.addSeparator()
            menu.addAction("Delete last point", self._undo_arch)
            menu.addAction("Clear arch", self._clear_arch)
            menu.addSeparator()
            show = menu.addAction("Show on axial", lambda: self._set_arch_show(not self._arch_show))
            show.setCheckable(True)
            show.setChecked(getattr(self, "_arch_show", True))
        else:
            tool = getattr(self, "_annotation_tool", "sync")
            header = menu.addAction(f"{tool} measurement")
            header.setEnabled(False)
            menu.addSeparator()
            if getattr(self, "_pending_annotation", None):
                menu.addAction("Cancel current measurement", self._cancel_pending_annotation)
            menu.addAction("Finish - back to mouse", self._set_default_mouse_mode)
        try:
            if not menu.isEmpty():
                menu.exec(gp)
        except Exception:
            menu.exec(gp)

    def _cancel_pending_annotation(self) -> None:
        self._pending_annotation = None
        self._pending_ruler_point = None
        self._redraw_annotation_views()
        self._set_status("Measurement cancelled")

    def _apply_wl_preset(self, preset: str) -> None:
        if self._vol is None:
            return
        import numpy as np

        sub = self._vol[::4, ::4, ::4]
        if preset == "Soft tissue":
            lo, hi = np.percentile(sub, 5.0), np.percentile(sub, 95.0)
        elif preset == "Endodontic":
            lo, hi = np.percentile(sub, 20.0), np.percentile(sub, 99.6)
        elif preset == "Implant":
            lo, hi = np.percentile(sub, 10.0), np.percentile(sub, 99.8)
        else:
            lo, hi = np.percentile(sub, 1.0), np.percentile(sub, 99.0)
        self._wl = (float(lo), float(max(hi, lo + 1.0)))
        self._wl_user_adjusted = True
        for view in ("axial", "coronal", "sagittal"):
            self._render_view(view)
        if self._last_panoramic_image is not None or self._last_curved_volume is not None:
            self._render_cached_recon_pixmaps()

    def _on_layer_changed(self, value: int) -> None:
        if hasattr(self, "_layer_label"):
            self._layer_label.setText(f"{int(value)} pcs")
        self._set_status(f"Layer count set to {int(value)} - click Layer to rebuild cross sections.")

    def _clear_reconstruction_cache(self) -> None:
        self._last_panoramic_image = None
        self._last_curved_volume = None
        self._last_curved_array = None
        self._last_cross_frames = []
        self._last_recon_key = None
        self._last_cross_key = None
        self._last_pano_key = None

    def _apply_layer_count(self, *_args) -> None:
        count = max(1, min(48, int(self._layer_slider.value())))
        self._cross_section_count = count
        self._cross_page_size = min(_MAX_CROSS_SECTIONS_PER_PAGE, count)
        if hasattr(self, "_layer_label"):
            self._layer_label.setText(f"{count} pcs")
        self._cross_page = 0
        self._clear_reconstruction_cache()
        if self._vol is None or self._volume is None:
            self._update_cross_page_controls()
            self._set_status(
                f"Layer count set to {count}. Pages show up to {_MAX_CROSS_SECTIONS_PER_PAGE} cross sections."
            )
            return
        self._set_status(f"Rebuilding {count} cross sections...")
        self._regenerate_dental_recon()
        self._set_status(
            f"Layer applied - {count} cross sections generated, {_MAX_CROSS_SECTIONS_PER_PAGE} per page."
        )

    def _update_cross_page_controls(self) -> None:
        total = max(1, int(self._cross_total_pages))
        self._cross_page = max(0, min(int(self._cross_page), total - 1))
        if self._cross_page_label is not None:
            self._cross_page_label.setText(f"Page {self._cross_page + 1}/{total}")
        if self._cross_prev_btn is not None:
            self._cross_prev_btn.setEnabled(total > 1 and self._cross_page > 0)
        if self._cross_next_btn is not None:
            self._cross_next_btn.setEnabled(total > 1 and self._cross_page < total - 1)

    def _change_cross_page(self, delta: int) -> None:
        total = max(1, int(self._cross_total_pages))
        new_page = max(0, min(total - 1, int(self._cross_page) + int(delta)))
        if new_page == self._cross_page:
            return
        self._cross_page = new_page
        self._render_cross_sections_preview()
        self._set_status(f"Cross-section page {self._cross_page + 1} / {total}")

    def _set_cross_tool(self, tool: str) -> None:
        tool = str(tool or "sync")
        mapped = {"ruler": "distance", "annot": "text"}.get(tool, tool)
        self._active_cross_tool = "sync"
        self._pending_ruler_point = None
        self._set_annotation_tool(mapped)

    def _tool_placeholder(self, *_args) -> None:
        self._set_status("Tool placeholder selected - planning object UI is ready for implementation.")

    def _toggle_sync_overlay(self, which: str) -> None:
        """View-Sync panel: toggle a reference/position overlay across all views."""
        if which == "pano_reference":
            self._show_pano_reference = not bool(self._show_pano_reference)
            self._set_status("Panoramic reference line " + ("on" if self._show_pano_reference else "off"))
        elif which == "cross_position":
            self._show_cross_position = not bool(self._show_cross_position)
            self._set_status("Cross-section position markers " + ("on" if self._show_cross_position else "off"))
        else:
            return
        self._redraw_annotation_views()

    def _relink_window_level(self, *_args) -> None:
        """View-Sync panel 'Linked WL': Window/Level is one shared value applied to every
        view, so it is already linked — re-apply the current preset to refresh them all."""
        if self._vol is None:
            self._set_status("Load a series first.")
            return
        preset = self._wl_combo.currentText() if getattr(self, "_wl_combo", None) is not None else "CBCT Bone"
        self._apply_wl_preset(preset)
        self._set_status("Window/Level linked across all views")

    def _planning_feature_pending(self, name: str) -> None:
        """Honest feedback for Planning rows that have no backend yet (implant)."""
        self._set_status(f"{name}: planned feature - not yet available in this build.")

    # ----------------------------------------------------- nerve canal (IAN)
    def _nerve_world_index_for(self, view: str, cx: float, cy: float):
        """Resolve a click on any view to (world, index, section) for the canal."""
        resolved = self._annotation_point_from_click(view, cx, cy)
        if resolved is None:
            return None, None, None
        point, section = resolved
        idx = self._annotation_index_for_point(view, point)
        if idx is None:
            return None, None, None
        return self._volume_index_to_vtk_world(idx), idx, section

    def _handle_nerve_press(self, view: str, cx: float, cy: float) -> bool:
        world, idx, section = self._nerve_world_index_for(view, cx, cy)
        if world is None:
            return False
        side = self._nerve_side
        if self._nerve_mode == "trace":
            self._nerve_store.add_point(side, {"world": world, "index": idx, "view": view, "section": section})
            self._nerve_show = True
            self._redraw_annotation_views()
            self._set_status(
                f"{side.title()} canal: {self._nerve_store.count(side)} points "
                f"({self._nerve_store.length_mm(side):.1f} mm)"
            )
            return True
        if self._nerve_mode == "edit":
            ci = self._nerve_store.nearest_control(side, world, max_dist=self._nerve_pick_mm)
            if ci is not None:
                self._nerve_drag = (side, ci, view)
                self._set_status(f"Editing {side} canal point {ci + 1} - drag to move")
                return True
        return False

    def _handle_nerve_move(self, obj, event) -> bool:
        if not self._nerve_drag:
            return False
        side, ci, view = self._nerve_drag
        pos = self._event_pos_for_cell(obj, event, view)
        if pos is None:
            return True
        world, idx, _section = self._nerve_world_index_for(view, float(pos[0]), float(pos[1]))
        if world is not None:
            self._nerve_store.move_control(side, ci, {"world": world, "index": idx, "view": view})
            self._redraw_annotation_views()
        return True

    def _draw_nerve_overlay(self, painter, view: str, w: int, h: int) -> None:
        if not self._nerve_show or view not in self._plans or self._vol is None:
            return
        disp_w, disp_h = self._display_dims(view)
        if disp_w <= 0 or disp_h <= 0:
            return
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QBrush, QColor, QPen

        sx, sy = w / disp_w, h / disp_h
        colors = {"left": QColor("#f472b6"), "right": QColor("#34d399")}
        for side in ("left", "right"):
            pts = self._nerve_store.points(side)
            if not pts:
                continue
            col = colors[side]
            # smooth path -> projected display polyline
            if len(pts) >= 2:
                samples = self._nerve_store.resampled_world(side, max(2, len(pts) * 8))
            else:
                samples = [pts[0]["world"]]
            disp = []
            for wpt in samples:
                d = self._volume_index_to_display(view, self._vtk_world_to_volume_index(wpt))
                if d is not None:
                    disp.append(QPointF((d[0] + 0.5) * sx, (d[1] + 0.5) * sy))
            painter.setPen(QPen(QColor(3, 19, 26, 200), 4))
            for i in range(1, len(disp)):
                painter.drawLine(disp[i - 1], disp[i])
            painter.setPen(QPen(col, 2))
            for i in range(1, len(disp)):
                painter.drawLine(disp[i - 1], disp[i])
            # control points
            painter.setBrush(QBrush(col))
            for p in pts:
                d = self._volume_index_to_display(view, p.get("index"))
                if d is not None:
                    c = QPointF((d[0] + 0.5) * sx, (d[1] + 0.5) * sy)
                    painter.setPen(QPen(QColor(3, 19, 26, 210), 2))
                    painter.drawEllipse(c, 3.4, 3.4)
            painter.setBrush(Qt.NoBrush)

    def _toggle_nerve_trace(self, *_args) -> None:
        self._nerve_mode = "off" if self._nerve_mode == "trace" else "trace"
        self._nerve_drag = None
        if self._nerve_mode == "trace":
            self._nerve_show = True
            self._set_default_mouse_mode()
            self._set_status(f"Trace {self._nerve_side} mandibular canal - click along the canal (axial recommended)")
        else:
            self._set_status("Nerve trace off")
        self._update_nerve_buttons()
        self._redraw_annotation_views()

    def _toggle_nerve_edit(self, *_args) -> None:
        self._nerve_mode = "off" if self._nerve_mode == "edit" else "edit"
        self._nerve_drag = None
        if self._nerve_mode == "edit":
            self._nerve_show = True
            self._set_default_mouse_mode()
            self._set_status(f"Edit {self._nerve_side} canal - drag a control point to move it")
        else:
            self._set_status("Nerve edit off")
        self._update_nerve_buttons()
        self._redraw_annotation_views()

    def _toggle_nerve_show(self, *_args) -> None:
        self._nerve_show = not bool(self._nerve_show)
        self._set_status("Nerve canal " + ("shown on slices" if self._nerve_show else "hidden"))
        self._redraw_annotation_views()

    def _set_nerve_side(self, side: str) -> None:
        self._nerve_side = side if side in ("left", "right") else "left"
        self._update_nerve_buttons()
        length = self._nerve_store.length_mm(self._nerve_side)
        self._set_status(f"Active canal: {self._nerve_side} ({self._nerve_store.count(self._nerve_side)} pts, {length:.1f} mm)")

    def _nerve_undo(self, *_args) -> None:
        if self._nerve_store.undo(self._nerve_side):
            self._redraw_annotation_views()
            self._set_status(f"{self._nerve_side.title()} canal: {self._nerve_store.count(self._nerve_side)} points")
        else:
            self._set_status(f"{self._nerve_side.title()} canal is empty")

    def _nerve_clear(self, *_args) -> None:
        self._nerve_store.clear(self._nerve_side)
        self._redraw_annotation_views()
        self._set_status(f"{self._nerve_side.title()} canal cleared")

    def _nerve_delete_nearest(self, view: str, cx: float, cy: float) -> None:
        """Delete the canal control point nearest the (right-clicked) cursor."""
        world, _idx, _section = self._nerve_world_index_for(view, cx, cy)
        if world is None:
            self._set_status("No canal point under the cursor")
            return
        side = self._nerve_side
        ci = self._nerve_store.nearest_control(side, world, max_dist=self._nerve_pick_mm)
        if ci is not None and self._nerve_store.remove_control(side, ci):
            self._redraw_annotation_views()
            self._set_status(
                f"Deleted {side} canal point {ci + 1} "
                f"({self._nerve_store.count(side)} left)"
            )
        else:
            self._set_status("No canal point near the cursor")

    def _update_nerve_buttons(self) -> None:
        for side, btn in getattr(self, "_nerve_side_buttons", {}).items():
            try:
                btn.blockSignals(True)
                btn.setChecked(side == self._nerve_side)
                btn.blockSignals(False)
            except Exception:
                pass

    # ----------------------------------------------------------- arch
    def _build_arch_controls(self, frame) -> None:
        """Pick Arch / Undo / Clear buttons in the Tools cell."""
        lay = frame.layout()
        style = (
            "QPushButton { font-size:11px; color:#e5edf5; padding:6px 8px;"
            " background:#1e293b; border:1px solid #334155; border-radius:6px; }"
            "QPushButton:hover { background:#334155; }"
            "QPushButton:checked { background:#0ea5e9; color:#0b1220; border-color:#38bdf8; }"
        )
        controls = [("Pick Arch", self._toggle_arch_pick, True)]
        # Apical (root) arch toggle — dual-arch oblique panoramic (default ON).
        if getattr(self, "_dual_arch_enabled", True):
            controls.append(("Apical Arch", self._toggle_apical_arch, True))
        controls += [
            ("Undo Arch Point", self._undo_arch, False),
            ("Clear Arch", self._clear_arch, False),
            ("Rebuild Panoramic", self._regenerate_dental_recon, False),
        ]
        for label, slot, checkable in controls:
            btn = QPushButton(label)
            btn.setCheckable(checkable)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            lay.addWidget(btn)
            if label == "Pick Arch":
                self._arch_pick_side_btn = btn
            elif label == "Apical Arch":
                self._apical_arch_btn = btn

    def _toggle_arch_pick(self, *_args) -> None:
        if not self._arch_enabled:
            return
        sender = self.sender()
        if sender is not None and hasattr(sender, "isChecked"):
            self._arch_pick_mode = bool(sender.isChecked())
        else:
            self._arch_pick_mode = not self._arch_pick_mode
        for btn_name in ("_arch_pick_btn", "_arch_pick_side_btn"):
            btn = getattr(self, btn_name, None)
            if btn is not None and hasattr(btn, "setChecked"):
                try:
                    btn.blockSignals(True)
                    btn.setChecked(self._arch_pick_mode)
                    btn.blockSignals(False)
                except Exception:
                    pass
        if self._arch_pick_mode and self._axial_geom is None:
            self._set_status("Load a CBCT series first, then click arch points on the axial view.")
            return
        self._set_status(
            "Arch picking ON - click points along the dental arch on the axial view."
            if self._arch_pick_mode else f"Arch points: {len(self._arch_points)}"
        )

    def _toggle_apical_arch(self, *_args) -> None:
        """Route arch picks to the crown or the apical (root) arch.

        Checked = new points go to the APICAL arch (traced along the root apices on a
        more apical axial slice); unchecked = the CROWN arch. Both feed the oblique
        panoramic (crown->apex per column). Requires 'Pick Arch' to be on to add points.
        """
        sender = self.sender()
        if sender is not None and hasattr(sender, "isChecked"):
            self._active_arch = "apical" if sender.isChecked() else "crown"
        else:
            self._active_arch = "crown" if self._active_arch == "apical" else "apical"
        if self._active_arch == "apical" and not self._arch_pick_mode:
            self._set_status("Apical arch active - turn ON 'Pick Arch', scroll to the root-apex "
                             "level, then click the apices.")
        else:
            n = len(self._apical_arch_points if self._active_arch == "apical" else self._arch_points)
            self._set_status(f"{self._active_arch.title()} arch active - {n} points.")

    def _active_arch_list(self) -> list:
        return self._apical_arch_points if getattr(self, "_active_arch", "crown") == "apical" else self._arch_points

    def _undo_arch(self, *_args) -> None:
        target = self._active_arch_list()
        if target:
            target.pop()
            self._compose_view("axial")
            self._invalidate_recon("Arch point removed - click Generate to rebuild.")
            self._set_status(f"{self._active_arch.title()} arch: {len(target)} points - click Generate to rebuild.")

    def _clear_arch(self, *_args) -> None:
        if getattr(self, "_active_arch", "crown") == "apical":
            self._apical_arch_points = []
        else:
            self._arch_points = []
        self._compose_view("axial")
        self._invalidate_recon("Arch reset - click Generate to rebuild.")
        self._set_status(f"{self._active_arch.title()} arch reset.")

    def get_arch_world_points(self):
        return [p["world"] for p in self._arch_points]

    def get_apical_world_points(self):
        return [p["world"] for p in self._apical_arch_points]

    def _apical_world_points(self):
        return [tuple(p["world"]) for p in self._apical_arch_points if "world" in p]

    def _on_axial_click(self, cx: float, cy: float) -> None:
        from .core.arch_geometry import display_click_to_slice, slice_index_to_world

        label = self._cells.get("axial")
        if label is None or self._axial_geom is None:
            return
        disp_w, disp_h = self._display_dims("axial")
        rc = self._label_click_to_content("axial", cx, cy, disp_w, disp_h)
        if rc is None:
            return
        col, row = rc
        index = self._display_to_volume_index("axial", col, row)
        if index is None:
            return
        # Keep the reference import above source-pinned to the pure geometry helper;
        # patient_world records the DICOM/LPS coordinate, while world records the
        # VTK physical point consumed by the same reslice engine as Dental Curve MPR.
        _ = slice_index_to_world
        world = self._volume_index_to_vtk_world(index)
        target = self._active_arch_list()
        target.append({
            "col": float(col),
            "row": float(row),
            "index": index,
            "world": world,
            "patient_world": self._volume_index_to_patient_world(index),
        })
        self._composite_axial()
        # An apical-arch change must also invalidate the panoramic cache (it is not part
        # of the crown-only _recon_key gather); crown picks are covered by the key.
        if getattr(self, "_active_arch", "crown") == "apical":
            self._last_panoramic_image = None
            self._last_pano_key = None
        arch_name = "Apical" if self._active_arch == "apical" else "Crown"
        self._set_status(f"{arch_name} arch: {len(target)} points - click Generate to rebuild panoramic/cross sections.")

    def _composite_axial(self) -> None:
        self._compose_view("axial")

    def _pixmap_source_click(self, plane: str, cx: float, cy: float, *, clamp: bool = False):
        label = self._cells.get(plane)
        pix = self._plane_pixmaps.get(plane)
        if label is None or pix is None or pix.isNull():
            return None
        return self._label_click_to_content(plane, cx, cy, pix.width(), pix.height(), clamp=clamp)

    def _on_ortho_sync_click(self, view: str, cx: float, cy: float) -> None:
        from .core.arch_geometry import display_click_to_slice

        label = self._cells.get(view)
        if label is None or view not in self._plans:
            return
        disp_w, disp_h = self._display_dims(view)
        rc = self._label_click_to_content(view, cx, cy, disp_w, disp_h)
        if rc is None:
            return
        index = self._display_to_volume_index(view, rc[0], rc[1])
        if index is None:
            return
        section = None
        if view == "axial":
            total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
            section = self._nearest_arch_section_from_display(rc[0], rc[1], total)
        self._set_sync_index(index, source=view, section=section)

    def _on_panoramic_click(self, cx: float, cy: float) -> None:
        rc = self._pixmap_source_click("panoramic", cx, cy)
        pix = self._plane_pixmaps.get("panoramic")
        if rc is None or pix is None:
            return
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        section = int(round((float(rc[0]) / max(1, pix.width() - 1)) * max(total - 1, 0)))
        self._apply_panoramic_selection(
            section,
            float(rc[1]),
            source="panoramic",
            pano_xy=(float(rc[0]), float(rc[1])),
        )

    def _cross_section_hit(self, cx: float, cy: float):
        rc = self._pixmap_source_click("crosssection", cx, cy, clamp=True)
        if rc is None:
            return
        x_click, y_click = float(rc[0]), float(rc[1])
        hit_pad = 4.0
        for item in self._cross_visible_sections:
            x, y, w, h = item["rect"]
            if x - hit_pad <= x_click <= x + w + hit_pad and y - hit_pad <= y_click <= y + h + hit_pad:
                lx = (x_click - x) / max(1.0, float(w))
                ly = (y_click - y) / max(1.0, float(h))
                lx = max(0.0, min(1.0, lx))
                ly = max(0.0, min(1.0, ly))
                return int(item["section"]), lx, ly
        if self._cross_visible_sections:
            nearest = min(
                self._cross_visible_sections,
                key=lambda item: math.hypot(
                    x_click - (item["rect"][0] + item["rect"][2] * 0.5),
                    y_click - (item["rect"][1] + item["rect"][3] * 0.5),
                ),
            )
            return int(nearest["section"]), 0.5, 0.5
        return None

    def _cross_section_world_index(self, section: int, lx: float, ly: float):
        if not self._last_cross_frames:
            return None, None
        section = max(0, int(section))
        frame = self._frame_for_section(
            section,
            len(self._cross_all_sample_indices) or self._desired_cross_section_count(),
        )
        if not frame:
            return None, None
        origin = frame.get("origin")
        normal = frame.get("normal")
        binormal = frame.get("binormal")
        if origin is None or normal is None or binormal is None:
            return None, None
        dims = None
        spacing = (1.0, 1.0, 1.0)
        if self._last_curved_volume is not None:
            try:
                dims = self._last_curved_volume.GetDimensions()
                spacing = self._last_curved_volume.GetSpacing()
            except Exception:
                dims = None
        if dims is None and self._last_curved_array is not None:
            dims = (int(self._last_curved_array.shape[2]), int(self._last_curved_array.shape[1]), int(self._last_curved_array.shape[0]))
        if dims is None:
            dims = (128, 128, len(self._last_cross_frames))
        # Cross-section display uses the same horizontal display correction as the
        # 2D Dental Curve viewer. Convert display-local X back to reslice-source X.
        src_lx = 1.0 - max(0.0, min(1.0, float(lx)))
        src_ly = max(0.0, min(1.0, float(ly)))
        width_mm = max(1.0, (max(1, int(dims[0])) - 1) * float(spacing[0]))
        height_mm = max(1.0, (max(1, int(dims[1])) - 1) * float(spacing[1]))
        off_x = (src_lx - 0.5) * width_mm
        off_y = (src_ly - 0.5) * height_mm
        world = (
            float(origin[0]) + float(normal[0]) * off_x + float(binormal[0]) * off_y,
            float(origin[1]) + float(normal[1]) * off_x + float(binormal[1]) * off_y,
            float(origin[2]) + float(normal[2]) * off_x + float(binormal[2]) * off_y,
        )
        return world, self._vtk_world_to_volume_index(world)

    def _apply_cross_section_selection(
        self,
        section: int,
        lx: float,
        ly: float,
        *,
        source: str = "cross-section",
        update_status: bool = True,
    ) -> bool:
        total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
        pos = self._arch_position_for_section(section, total)
        if pos is None or pos.get("index") is None:
            return False
        section = int(pos["section"])
        lx = max(0.0, min(1.0, float(lx)))
        ly = max(0.0, min(1.0, float(ly)))
        moved_world, moved_index = self._cross_section_world_index(section, lx, ly)
        self._selected_cross_section = section
        self._sync_index = tuple(int(v) for v in (moved_index or pos["index"]))
        self._sync_world = tuple(moved_world or pos["world"])
        self._sync_source = source
        pano = self._plane_pixmaps.get("panoramic")
        if pano is not None and not pano.isNull():
            px = self._section_path_fraction(section, total) * max(0, pano.width() - 1)
            py = self._pano_source_fraction_to_display_y(ly, pano.height())
            self._sync_pano_xy = (px, py)
        else:
            self._sync_pano_xy = None
        self._sync_cross_local = (section, lx, ly)
        logger.info(
            "[DENTAL-SYNC] source=%s section=%s frame=%s pano_xy=%s cross_local=%s index=%s world=%s",
            source,
            section,
            self._frame_index_for_section(section, total),
            self._sync_pano_xy,
            self._sync_cross_local,
            self._sync_index,
            tuple(round(float(v), 3) for v in self._sync_world),
        )
        self._compose_recon_cell("crosssection")
        self._compose_recon_cell("panoramic")
        for view in ("axial", "coronal", "sagittal"):
            plan = self._plans.get(view)
            if plan:
                self._slice_idx[view] = int(self._sync_index[plan["through"]])
                self._render_view(view)
        if update_status:
            self._set_status(f"Selected cross-section {section + 1}")
        return True

    def _select_cross_section_at(self, cx: float, cy: float, *, dragging: bool = False) -> bool:
        hit = self._cross_section_hit(cx, cy)
        if hit is None:
            return False
        section, lx, ly = hit
        if not dragging and self._active_cross_tool == "ruler":
            if self._pending_ruler_point is None or int(self._pending_ruler_point[0]) != section:
                self._pending_ruler_point = (section, (lx, ly))
                self._apply_cross_section_selection(section, lx, ly, source="ruler start", update_status=False)
                self._set_status(f"Ruler start set on cross-section {section + 1}")
            else:
                p1 = self._pending_ruler_point[1]
                self._cross_annotations.setdefault(section, []).append({"kind": "ruler", "p1": p1, "p2": (lx, ly)})
                self._pending_ruler_point = None
                self._apply_cross_section_selection(section, lx, ly, source="ruler end", update_status=False)
                self._set_status(f"Ruler added on cross-section {section + 1}")
            self._compose_recon_cell("crosssection")
            return True
        if not dragging and self._active_cross_tool == "annot":
            self._cross_annotations.setdefault(section, []).append({"kind": "annot", "p": (lx, ly)})
            self._apply_cross_section_selection(section, lx, ly, source="annotation", update_status=False)
            self._set_status(f"Annotation added on cross-section {section + 1}")
            self._compose_recon_cell("crosssection")
            return True
        return self._apply_cross_section_selection(
            section,
            lx,
            ly,
            source="cross-section",
            update_status=not dragging,
        )

    def _on_cross_section_click(self, cx: float, cy: float) -> None:
        self._select_cross_section_at(cx, cy, dragging=False)

    def _event_pos_for_cell(self, obj, event, plane: str):
        label = self._cells.get(plane)
        if label is None:
            return None
        try:
            pos = event.position()
        except AttributeError:
            pos = event.pos()
        if obj is label:
            return float(pos.x()), float(pos.y())
        frame = self._cell_frames.get(plane)
        try:
            owns_obj = bool(frame is not None and (obj is frame or frame.isAncestorOf(obj)))
        except Exception:
            owns_obj = obj is frame
        if owns_obj:
            try:
                from PySide6.QtCore import QPoint

                mapped = label.mapFrom(
                    obj,
                    QPoint(int(round(float(pos.x()))), int(round(float(pos.y())))),
                )
                return float(mapped.x()), float(mapped.y())
            except Exception:
                logger.debug("[DENTAL] frame-to-label event mapping failed", exc_info=True)
                return None
        return None

    def _event_plane_pos(self, obj, event):
        for view in ("axial", "coronal", "sagittal"):
            if obj is self._cells.get(view):
                try:
                    pos = event.position()
                except AttributeError:
                    pos = event.pos()
                return view, (float(pos.x()), float(pos.y()))
        for plane in ("panoramic", "crosssection"):
            pos = self._event_pos_for_cell(obj, event, plane)
            if pos is not None:
                return plane, pos
        return None, None

    def _set_mouse_mode(self, mode: str) -> None:
        """Select what a LEFT-drag does on any view: stack / pan / zoom / wl."""
        mode = mode if mode in ("stack", "pan", "zoom", "wl") else "stack"
        self._mouse_mode = mode
        for m, btn in getattr(self, "_mouse_mode_buttons", {}).items():
            try:
                btn.blockSignals(True)
                btn.setChecked(m == mode)
                btn.blockSignals(False)
            except Exception:
                pass
        # Choosing a mouse function exits any active annotation tool (so the drag runs
        # the mouse function, not point placement); a plain click still does sync select.
        if self._annotation_tool != "sync":
            self._set_default_mouse_mode()
        labels = {"stack": "Stack (scroll)", "pan": "Pan", "zoom": "Zoom", "wl": "Window / Level"}
        self._set_status(f"Mouse function: {labels.get(mode, mode)}")

    def _set_default_mouse_mode(self) -> None:
        self._annotation_tool = "sync"
        self._active_cross_tool = "sync"
        self._pending_annotation = None
        self._pending_ruler_point = None
        self._mouse_drag = self._blank_mouse_drag()
        for btn in self._tool_buttons.values():
            try:
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)
            except Exception:
                pass

    def _blank_mouse_drag(self) -> dict:
        return {
            "plane": None,
            "button": None,
            "last": None,
            "press": None,
            "moved": False,
            "left": False,
            "right": False,
            "middle": False,
        }

    def _apply_window_level_drag(self, dx: float, dy: float, *, adjust_width: bool = True) -> None:
        if self._wl is None:
            if self._vol is not None:
                try:
                    import numpy as np
                    sub = self._vol[::4, ::4, ::4]
                    self._wl = (float(np.percentile(sub, 1.0)), float(np.percentile(sub, 99.0)))
                except Exception:
                    self._wl = (0.0, 255.0)
            else:
                self._wl = (0.0, 255.0)
        lo, hi = self._wl
        window = max(1.0, float(hi) - float(lo))
        level = (float(hi) + float(lo)) / 2.0
        # Same interaction constants as the standard 2D viewer.
        new_window = max(1.0, window + float(dx) * 1.5) if adjust_width else window
        new_level = level + (-float(dy)) * 1.3
        self._wl = (new_level - new_window / 2.0, new_level + new_window / 2.0)
        self._wl_user_adjusted = True
        for view in ("axial", "coronal", "sagittal"):
            self._render_view(view)
        if self._last_panoramic_image is not None or self._last_curved_volume is not None:
            self._render_cached_recon_pixmaps()

    def _apply_pan_drag(self, plane: str, dx: float, dy: float) -> None:
        tr = self._view_transform(plane)
        tr["pan"][0] = float(tr["pan"][0]) + float(dx)
        tr["pan"][1] = float(tr["pan"][1]) + float(dy)
        self._redraw_plane(plane)

    def _apply_zoom_drag(self, plane: str, dy: float) -> None:
        tr = self._view_transform(plane)
        if float(dy) < 0:
            factor = 1.0 + abs(float(dy)) * 0.005
        elif float(dy) > 0:
            factor = 1.0 / (1.0 + abs(float(dy)) * 0.005)
        else:
            factor = 1.0
        tr["zoom"] = max(0.05, min(40.0, float(tr.get("zoom", 1.0)) * factor))
        self._redraw_plane(plane)

    def _redraw_plane(self, plane: str) -> None:
        if plane in ("axial", "coronal", "sagittal"):
            self._compose_view(plane)
        elif plane in ("panoramic", "crosssection"):
            self._compose_recon_cell(plane)

    def _default_wheel_scroll(self, plane: str, delta_y: int) -> bool:
        if delta_y == 0:
            return True
        step = 1 if delta_y < 0 else -1
        if plane in ("axial", "coronal", "sagittal"):
            self._scroll_view(plane, step)
            return True
        if plane in ("panoramic", "crosssection"):
            total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
            if total <= 0:
                return True
            section = int(self._selected_cross_section if self._selected_cross_section is not None else 0)
            section = max(0, min(total - 1, section + step))
            self._set_sync_from_arch_section(section, source=f"{plane} wheel")
            return True
        return False

    def _handle_default_mouse_move(self, obj, event) -> bool:
        plane = self._mouse_drag.get("plane")
        last = self._mouse_drag.get("last")
        if not plane or last is None:
            return False
        _plane, pos = self._event_plane_pos(obj, event)
        if _plane != plane or pos is None:
            return False
        x, y = float(pos[0]), float(pos[1])
        dx, dy = x - float(last[0]), y - float(last[1])
        if abs(dx) + abs(dy) >= 2.0:
            self._mouse_drag["moved"] = True
        self._mouse_drag["last"] = (x, y)
        buttons = event.buttons()
        if (buttons & Qt.LeftButton) and (buttons & Qt.RightButton):
            self._apply_pan_drag(plane, dx, dy)
            return True
        if buttons & Qt.MiddleButton:
            self._apply_zoom_drag(plane, dy)
            return True
        if buttons & Qt.RightButton:
            self._apply_window_level_drag(dx, dy)
            return True
        if buttons & Qt.LeftButton:
            mode = getattr(self, "_mouse_mode", "wl")
            if mode == "pan":
                self._apply_pan_drag(plane, dx, dy)
            elif mode == "zoom":
                self._apply_zoom_drag(plane, dy)
            elif mode == "stack":
                self._apply_stack_drag(plane, dy)
            else:  # "wl"
                self._apply_window_level_drag(dx, dy)
            return True
        return False

    def _apply_stack_drag(self, plane: str, dy: float) -> None:
        """LEFT-drag stack scroll (mouse function = Stack): accumulate vertical motion
        and step slices; dragging down advances. Works on ortho + panoramic/cross."""
        accum = float(self._mouse_drag.get("stack_accum", 0.0)) + float(dy)
        step = 0
        while accum >= _STACK_DRAG_PX:
            step += 1
            accum -= _STACK_DRAG_PX
        while accum <= -_STACK_DRAG_PX:
            step -= 1
            accum += _STACK_DRAG_PX
        self._mouse_drag["stack_accum"] = accum
        if step == 0:
            return
        if plane in ("axial", "coronal", "sagittal"):
            self._scroll_view(plane, step)
        elif plane in ("panoramic", "crosssection"):
            total = len(self._cross_all_sample_indices) or self._desired_cross_section_count()
            if total > 0:
                section = int(self._selected_cross_section if self._selected_cross_section is not None else 0)
                section = max(0, min(total - 1, section + step))
                self._set_sync_from_arch_section(section, source=f"{plane} drag")

    def _finish_default_mouse_interaction(self, obj, event) -> bool:
        plane = self._mouse_drag.get("plane")
        press = self._mouse_drag.get("press")
        moved = bool(self._mouse_drag.get("moved"))
        try:
            remaining_buttons = event.buttons()
        except Exception:
            remaining_buttons = Qt.NoButton
        if remaining_buttons & (Qt.LeftButton | Qt.RightButton | Qt.MiddleButton):
            try:
                _plane, pos = self._event_plane_pos(obj, event)
                if _plane == plane and pos is not None:
                    self._mouse_drag["last"] = (float(pos[0]), float(pos[1]))
            except Exception:
                pass
            self._mouse_drag["left"] = bool(remaining_buttons & Qt.LeftButton)
            self._mouse_drag["right"] = bool(remaining_buttons & Qt.RightButton)
            self._mouse_drag["middle"] = bool(remaining_buttons & Qt.MiddleButton)
            return bool(plane)
        self._mouse_drag = self._blank_mouse_drag()
        if not plane or moved or press is None:
            return bool(plane)
        # A click without drag keeps the previous sync/select behavior.
        if plane in ("axial", "coronal", "sagittal"):
            self._on_ortho_sync_click(plane, press[0], press[1])
            return True
        if plane == "panoramic":
            self._on_panoramic_click(press[0], press[1])
            return True
        if plane == "crosssection":
            self._on_cross_section_click(press[0], press[1])
            return True
        return False

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent

        etype = event.type()
        if self._nav_enabled and etype == QEvent.Wheel:
            try:
                plane, _pos = self._event_plane_pos(obj, event)
                if plane:
                    self._default_wheel_scroll(plane, event.angleDelta().y())
                    return True
            except Exception:
                logger.exception("[DENTAL] wheel scroll failed")
        # RIGHT-CLICK never creates a point. It only opens a context menu: the
        # annotation/line menu when it lands on one, otherwise (while a drawing tool
        # is active) the point/line/measurement actions. In plain sync/select mode
        # with no hit it falls through so the right-drag Window/Level still works.
        if etype == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
            try:
                plane, pos = self._event_plane_pos(obj, event)
                if plane is not None and pos is not None:
                    if self._maybe_show_overlay_context_menu(
                        plane, float(pos[0]), float(pos[1]), event
                    ):
                        return True
                    if self._in_drawing_mode():
                        self._show_drawing_context_menu(
                            plane, float(pos[0]), float(pos[1]), event
                        )
                        return True
                elif self._in_drawing_mode():
                    # right-click outside any cell while drawing: still no new point
                    self._show_drawing_context_menu(None, 0.0, 0.0, event)
                    return True
            except Exception:
                logger.exception("[DENTAL] right-click menu failed")
        # LEFT-CLICK only for point creation (arch pick).
        if (self._arch_enabled and self._arch_pick_mode
                and obj is self._cells.get("axial")
                and etype == QEvent.MouseButtonPress
                and event.button() == Qt.LeftButton):
            try:
                pos = event.position()
                self._on_axial_click(pos.x(), pos.y())
            except Exception:
                logger.exception("[DENTAL] arch click failed")
            return True
        # LEFT-CLICK only for canal point creation / control-point grab.
        if (etype == QEvent.MouseButtonPress and event.button() == Qt.LeftButton
                and self._nerve_mode != "off"):
            try:
                plane, pos = self._event_plane_pos(obj, event)
                if plane is not None and pos is not None and self._handle_nerve_press(
                    plane, float(pos[0]), float(pos[1])
                ):
                    return True
            except Exception:
                logger.exception("[DENTAL] nerve press failed")
        if etype == QEvent.MouseMove and self._nerve_drag:
            try:
                if self._handle_nerve_move(obj, event):
                    return True
            except Exception:
                logger.exception("[DENTAL] nerve drag failed")
        if etype == QEvent.MouseButtonRelease and self._nerve_drag:
            self._nerve_drag = None
            return True
        if etype == QEvent.MouseButtonPress:
            try:
                plane, pos = self._event_plane_pos(obj, event)
                # (Right-click was already handled above: it never reaches here in a
                # drawing mode, and in sync mode it falls through to the WL right-drag.)
                if plane is not None and pos is not None and self._annotation_tool == "sync":
                    buttons = event.buttons()
                    self._mouse_drag = {
                        "plane": plane,
                        "button": event.button(),
                        "last": (float(pos[0]), float(pos[1])),
                        "press": (float(pos[0]), float(pos[1])),
                        "moved": False,
                        "left": bool(buttons & Qt.LeftButton),
                        "right": bool(buttons & Qt.RightButton),
                        "middle": bool(buttons & Qt.MiddleButton),
                    }
                    return True
                # Annotation point creation is LEFT-CLICK only (right-click opened the
                # menu above; any other button is swallowed without adding a point).
                is_left = event.button() == Qt.LeftButton
                for view in ("axial", "coronal", "sagittal"):
                    if obj is self._cells.get(view):
                        pos = event.position()
                        if self._annotation_tool != "sync":
                            if is_left:
                                self._handle_annotation_click(view, pos.x(), pos.y())
                            return True
                        self._on_ortho_sync_click(view, pos.x(), pos.y())
                        return True
                pos = self._event_pos_for_cell(obj, event, "panoramic")
                if pos is not None:
                    if self._annotation_tool != "sync":
                        if is_left:
                            self._handle_annotation_click("panoramic", pos[0], pos[1])
                        return True
                    self._on_panoramic_click(pos[0], pos[1])
                    return True
                pos = self._event_pos_for_cell(obj, event, "crosssection")
                if pos is not None:
                    if self._annotation_tool != "sync":
                        if is_left:
                            self._handle_annotation_click("crosssection", pos[0], pos[1])
                        self._dragging_cross_sync = False
                        return True
                    self._on_cross_section_click(pos[0], pos[1])
                    self._dragging_cross_sync = self._active_cross_tool == "sync"
                    return True
            except Exception:
                logger.exception("[DENTAL] sync click failed")
        if etype == QEvent.MouseMove and self._annotation_tool == "sync" and self._mouse_drag.get("plane"):
            try:
                if self._handle_default_mouse_move(obj, event):
                    return True
            except Exception:
                logger.exception("[DENTAL] default mouse drag failed")
        if etype == QEvent.MouseButtonRelease and self._mouse_drag.get("plane"):
            try:
                return self._finish_default_mouse_interaction(obj, event)
            except Exception:
                logger.exception("[DENTAL] default mouse release failed")
                self._mouse_drag = self._blank_mouse_drag()
                return True
        if etype == QEvent.MouseMove and self._dragging_cross_sync:
            try:
                pos = self._event_pos_for_cell(obj, event, "crosssection")
                if pos is not None:
                    self._select_cross_section_at(pos[0], pos[1], dragging=True)
                    return True
            except Exception:
                logger.exception("[DENTAL] cross-section sync drag failed")
        if etype == QEvent.MouseButtonRelease and (
            obj is self._cells.get("crosssection") or obj is self._cell_frames.get("crosssection")
        ):
            self._dragging_cross_sync = False
        return super().eventFilter(obj, event)

    # --------------------------------------------------------------- drag/drop
    def _series_drop_mime(self) -> str:
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
                _SERIES_DROP_MIME,
            )
            return _SERIES_DROP_MIME
        except Exception:
            return _SERIES_DROP_MIME_FALLBACK

    def _dropped_series_number(self, mime) -> Optional[int]:
        if mime is None:
            return None
        fmt = self._series_drop_mime()
        try:
            if mime.hasFormat(fmt):
                raw = bytes(mime.data(fmt)).decode("utf-8", "ignore").strip()
                if raw and raw.lstrip("-").isdigit():
                    return int(raw)
            if mime.hasText():
                text = str(mime.text() or "").strip()
                if text and text.lstrip("-").isdigit():
                    return int(text)
        except Exception:
            return None
        return None

    def _payload_supported(self, mime) -> bool:
        return self._dropped_series_number(mime) is not None

    def dragEnterEvent(self, event):
        if self._payload_supported(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._payload_supported(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        series_number = self._dropped_series_number(event.mimeData())
        logger.info("[DENTAL] dropEvent series=%s resolver=%s", series_number,
                    self._series_resolver is not None)
        if series_number is None:
            event.ignore()
            return
        event.acceptProposedAction()
        if self._series_resolver is None:
            self._set_status("Dropped series received, but no resolver is connected.")
            return
        self._set_status(f"Loading dropped CBCT series {series_number}...")
        try:
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()
        except Exception:
            pass
        try:
            context, volume = self._series_resolver(int(series_number))
        except Exception:
            logger.exception("[DENTAL] resolver failed for dropped series %s", series_number)
            context, volume = None, None
        self.load_series(context, volume)
