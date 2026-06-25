# -*- coding: utf-8 -*-
"""Dental Imaging workspace (Milestone 1).

A dedicated dark, Romexis-style top-level WINDOW that receives the active series
(+ shared volume) and reconstructs static orthogonal previews:

  • left   — tools / object-browser placeholder
  • center — 2×2 grid: Axial / Coronal / Sagittal (static MPR previews) + 3D (next)
  • right  — adjust / panoramic / cross-section / annotation / nerve placeholders
  • footer — status line + bound-volume geometry

The three MPR cells render a windowed middle slice of the bound volume as a single
``QImage`` each — a STATIC reconstruction, NOT a VTK render window (so it can never
disturb the standard viewer / standard MPR and obeys the FAST rule). The dental
panoramic + cross-sections (which need the arch curve) and the 3D VRT are the next
milestone, built by reusing the standard-MPR pipeline (see README.md).

The whole workspace is a drop target for the app's series payload (the SAME MIME the
patient viewports accept); dropping a thumbnail re-resolves + reloads that exact
series via an injected resolver and re-renders the previews.
"""
from __future__ import annotations

import logging
import os
from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .context import DentalSeriesContext

logger = logging.getLogger(__name__)

_BG = "#0b0f14"
_PANEL = "#0f1620"
_BORDER = "#1f2a37"
_ACCENT = "#7c3aed"
_TEXT = "#e5edf5"
_MUTED = "#8aa0b2"

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
    lay.setContentsMargins(8, 8, 8, 8)
    lay.setSpacing(4)
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
    """Top-level pop-up for the professional Dental Imaging module."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent, Qt.Window)
        self._context: Optional[DentalSeriesContext] = None
        self._volume = None
        self._series_resolver: Optional[Callable[[int], tuple]] = None
        # per-plane full-res pixmaps, rescaled to their cell on resize
        self._plane_pixmaps: dict = {}
        # Arch picking (M2a, flag-gated default off). _arch_points: list of
        # {col,row,k,world}; _axial_geom: (dx,dy,k,origin,spacing,direction16).
        self._arch_enabled = os.environ.get("AIPACS_DENTAL_ARCH_PICK", "0") != "0"
        self._arch_pick_mode = False
        self._arch_points: list = []
        self._axial_geom = None
        # Geometry + stack navigation (P2). _vol = numpy (z,y,x); _plans[view] = the
        # orientation plan from the volume's DirectionMatrix (reuses the standard-MPR
        # contract); _slice_idx[view] = current slice along that view's through-axis.
        self._orient_enabled = os.environ.get("AIPACS_DENTAL_ORTHO_ORIENT", "1") != "0"
        self._nav_enabled = os.environ.get("AIPACS_DENTAL_STACK_NAV", "1") != "0"
        self._vol = None
        self._wl = None  # (lo, hi) window for the QImage mapping
        self._plans: dict = {}
        self._slice_idx: dict = {}
        self._view_sliders: dict = {}
        self._view_idx_labels: dict = {}
        # Embedded standard (Zeta) MPR VTK pipeline — the SAME proven viewer the toolbar
        # "MPR" button opens, so geometry/orientation/L-R/scroll/crosshairs are identical
        # to standard MPR (per the unified-MPR directive). Default ON; the static-QImage
        # ortho grid is the fallback (AIPACS_DENTAL_VTK_MPR=0).
        self._vtk_mpr_enabled = os.environ.get("AIPACS_DENTAL_VTK_MPR", "1") != "0"
        self._vtk_mpr = None
        self._center_host = None
        self._center_layout = None
        self._ortho_grid_widget = None

        self.setWindowTitle("Dental Imaging")
        self.resize(1180, 760)
        self.setMinimumSize(940, 620)
        self.setStyleSheet(f"QWidget {{ background:{_BG}; color:{_TEXT}; }}")
        self.setAcceptDrops(True)

        self._status_label: Optional[QLabel] = None
        self._title_series_label: Optional[QLabel] = None
        self._geometry_label: Optional[QLabel] = None
        self._cells: dict = {}  # plane -> content QLabel
        self._build_ui()

    def set_series_resolver(self, resolver: Optional[Callable[[int], tuple]]) -> None:
        self._series_resolver = resolver

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)
        root.addWidget(self._build_footer())

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {_ACCENT}, "
            f"stop:1 #5b21b6); border-radius:8px; }}"
        )
        lay = QHBoxLayout(header)
        lay.setContentsMargins(14, 10, 14, 10)
        title = QLabel("🦷  Dental Imaging")
        title.setStyleSheet(
            "QLabel { color:white; font-family:'Roboto','Segoe UI'; font-size:15px; "
            "font-weight:bold; background:transparent; }"
        )
        lay.addWidget(title)
        scaffold = QLabel("Milestone 1 · MPR previews")
        scaffold.setStyleSheet(
            "QLabel { color:rgba(255,255,255,0.85); font-size:10px; background:rgba(0,0,0,0.18); "
            "border-radius:8px; padding:2px 8px; }"
        )
        lay.addWidget(scaffold)
        lay.addStretch()
        self._title_series_label = QLabel("No series loaded")
        self._title_series_label.setStyleSheet(
            "QLabel { color:rgba(255,255,255,0.92); font-size:11px; background:transparent; }"
        )
        lay.addWidget(self._title_series_label)
        return header

    def _build_body(self) -> QWidget:
        body = QWidget()
        lay = QHBoxLayout(body)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        tools_sub = (
            "Dental arch — turn on “Pick Arch”, then click points along the arch on\n"
            "the Axial view. (Panoramic/cross-section reconstruction is the next step.)"
            if self._arch_enabled else
            "Load CBCT · Arch curve · Cross-section · Ruler · Nerve · Export\n"
            "(professional tools land in later milestones)"
        )
        left, _ = _cell("Tools", tools_sub)
        left.setFixedWidth(190)
        if self._arch_enabled:
            self._build_arch_controls(left)
        lay.addWidget(left)

        # Center host holds EITHER the embedded standard-MPR VTK viewer (default — correct
        # geometry) OR the static ortho grid (fallback / empty state); they are swapped.
        center_host = QWidget()
        center_layout = QVBoxLayout(center_host)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(0)
        self._center_host = center_host
        self._center_layout = center_layout

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        axial = self._ortho_cell("axial", "Axial")
        coronal = self._ortho_cell("coronal", "Coronal")
        sagittal = self._ortho_cell("sagittal", "Sagittal")
        threed, self._cells["3d"] = _cell("3D / Panoramic", "Volume rendering + panoramic\n(reconstruct from the dental arch — next milestone)")
        grid.addWidget(axial, 0, 0)
        grid.addWidget(coronal, 0, 1)
        grid.addWidget(sagittal, 1, 0)
        grid.addWidget(threed, 1, 1)
        self._ortho_grid_widget = grid_widget
        center_layout.addWidget(grid_widget, 1)
        lay.addWidget(center_host, 1)

        right, _ = _cell(
            "Object browser / Settings",
            "Adjust (W/L) · Panoramic · Cross sections · Annotation · Nerve canal\n"
            "(panels populate in later milestones)",
        )
        right.setFixedWidth(240)
        lay.addWidget(right)
        return body

    def _build_footer(self) -> QWidget:
        footer = QFrame()
        footer.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QHBoxLayout(footer)
        lay.setContentsMargins(12, 8, 12, 8)
        self._status_label = QLabel("Waiting for a series…")
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

    # --------------------------------------------------------------- data in
    def load_series(self, context: Optional[DentalSeriesContext], volume=None) -> None:
        """Receive a series + (optional) bound volume and reconstruct the previews.
        Replaces whatever was loaded before (on open AND on drop)."""
        self._context = context
        self._volume = volume
        self._plane_pixmaps = {}
        self._arch_points = []
        self._axial_geom = None
        self._vol = None
        self._plans = {}
        self._slice_idx = {}
        self._wl = None
        self._teardown_vtk_mpr()   # drop any prior embedded MPR before reloading

        if context is None or not context.is_loadable():
            self._set_title("No series loaded")
            self._set_status("No active series — open with a displayed series, or drag a thumbnail here.")
            self._set_geometry("")
            self._set_cell("axial", "No active series\n\nOpen with a series displayed,\nor drag a series thumbnail here.")
            self._set_cell("coronal", "")
            self._set_cell("sagittal", "")
            return

        self._set_title(context.summary())
        valid_volume = False
        if volume is not None:
            try:
                valid_volume = bool(volume.is_valid())
            except Exception:
                valid_volume = False

        if valid_volume:
            self._set_status(f"Reconstructing · {context.dicom_dir}")
            self._set_geometry(f"Volume bound (shared) · {volume.summary()}")
            built_vtk = self._build_vtk_mpr(volume, context) if self._vtk_mpr_enabled else False
            if not built_vtk:
                self._render_ortho_previews(volume)   # static-QImage fallback
            self._set_status(f"Active series ready · {context.dicom_dir}")
        else:
            self._set_status(f"Series selected · {context.dicom_dir}")
            self._set_geometry("No live volume bound — preview unavailable")
            self._set_cell("axial", "Series selected.\nVolume preview unavailable\n(try a series that is loaded in the viewer).")
            self._set_cell("coronal", "")
            self._set_cell("sagittal", "")

    # ------------------------------------------------- standard MPR VTK host
    def _build_vtk_mpr(self, volume, context) -> bool:
        """Embed the standard (Zeta) MPR viewer bound to the dental volume — the SAME
        construction the toolbar 'MPR' button uses (canonicalize + StandardMPRViewer),
        so geometry / orientation / L-R / scroll / crosshairs are IDENTICAL to standard
        MPR. Returns True on success (else the caller uses the static-QImage fallback)."""
        try:
            vid = getattr(volume, "image_data", None)
            if vid is None:
                return False
            ww = getattr(context, "window_width", None)
            wc = getattr(context, "window_level", None)
            # Canonicalize exactly like toggle_zeta_mpr (flag-gated; orientation-only).
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
            logger.info("[DENTAL] embedded standard MPR viewer (geometry reused)")
            return True
        except Exception:
            logger.exception("[DENTAL] standard MPR embed failed; using static previews")
            return False

    def _mount_vtk_mpr(self, viewer) -> None:
        """Swap the static ortho grid out and the embedded MPR viewer in."""
        if self._center_layout is None:
            return
        if self._ortho_grid_widget is not None:
            self._ortho_grid_widget.hide()
            self._center_layout.removeWidget(self._ortho_grid_widget)
        self._center_layout.addWidget(viewer, 1)
        viewer.show()

    def _teardown_vtk_mpr(self) -> None:
        """Cleanly finalize + remove the embedded MPR viewer (VTK render windows), then
        restore the static ortho grid. Guarded against already-deleted Qt objects (the
        same teardown-race class the central notify guard also catches)."""
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
                pass  # already-deleted C++ object during teardown — fine
            except Exception:
                logger.exception("[DENTAL] MPR remove failed")
        if self._center_layout is not None and self._ortho_grid_widget is not None:
            if self._center_layout.indexOf(self._ortho_grid_widget) < 0:
                self._center_layout.addWidget(self._ortho_grid_widget, 1)
            self._ortho_grid_widget.show()

    def closeEvent(self, event):
        """Finalize the embedded MPR (VTK) before the window closes."""
        try:
            self._teardown_vtk_mpr()
        except Exception:
            logger.exception("[DENTAL] closeEvent teardown failed")
        super().closeEvent(event)

    # --------------------------------------------------- ortho cells + nav (P2)
    def _ortho_cell(self, view: str, title: str):
        """Build an ortho cell: title + slice index + image + (nav) slider. The image
        label captures wheel-scroll (and, on axial, arch clicks) via the event filter."""
        from PySide6.QtWidgets import QSlider

        frame = QFrame()
        frame.setStyleSheet(
            f"QFrame {{ background:{_PANEL}; border:1px solid {_BORDER}; border-radius:8px; }}"
        )
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(4)
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
        content.installEventFilter(self)  # wheel scroll + (axial) arch clicks
        return frame

    # --------------------------------------------------------------- preview
    def _render_ortho_previews(self, volume) -> None:
        """Render axial / coronal / sagittal slices from the bound volume — correctly
        ORIENTED (radiological convention, derived from the volume's DirectionMatrix,
        reusing the standard-MPR geometry contract) and stack-navigable (slider + mouse
        wheel). Static QImages; no VTK render window. Fully guarded."""
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
                    # legacy (orientation-blind) plan: raw axis slices, no flips/labels
                    legacy = {"axial": 2, "coronal": 1, "sagittal": 0}[view]
                    rem = [a for a in (0, 1, 2) if a != legacy]
                    self._plans[view] = {"through": legacy, "h": rem[0], "v": rem[1],
                                         "flip_h": False, "flip_v": False, "labels": {}}
                through_n = 2 - self._plans[view]["through"]
                self._slice_idx[view] = self._vol.shape[through_n] // 2

            # Geometry for arch picking on the axial slice (index→world reuse). NOTE:
            # captured in raw orientation; arch picking (default-off) + the new oriented
            # display still need reconciliation (M2a is experimental).
            self._axial_geom = (
                dx, dy, dz // 2,
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
        return QPixmap.fromImage(qimg)  # copies buffer

    def _extract_oriented(self, view: str, idx: int):
        """Extract the 2-D slice for ``view`` at ``idx`` along its through-axis,
        transposed + flipped per the plan so display rows = +up, cols = +right."""
        import numpy as np

        plan = self._plans[view]
        through_n = 2 - plan["through"]
        h_n, v_n = 2 - plan["h"], 2 - plan["v"]
        sl = np.take(self._vol, int(idx), axis=through_n)        # 2-D
        rem_n = [a for a in (0, 1, 2) if a != through_n]          # ascending numpy axes
        row_pos = 0 if rem_n[0] == v_n else 1
        col_pos = 0 if rem_n[0] == h_n else 1
        img2d = np.transpose(sl, (row_pos, col_pos))             # rows=v, cols=h
        if plan["flip_v"]:
            img2d = img2d[::-1, :]
        if plan["flip_h"]:
            img2d = img2d[:, ::-1]
        return np.ascontiguousarray(img2d)

    def _render_view(self, view: str) -> None:
        """(Re)build the base pixmap for ``view`` at its current slice index, refresh
        the slider/index, then compose (scale + orientation labels + arch overlay)."""
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
        """Scale the base pixmap to the cell + draw orientation labels (and, for axial,
        the arch markers/spline). The single display path for every ortho view."""
        label = self._cells.get(view)
        base = (self._plane_pixmaps or {}).get(view)
        if label is None or base is None or base.isNull():
            return
        size = label.size()
        if size.width() <= 1 or size.height() <= 1:
            return
        scaled = base.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        from PySide6.QtGui import QColor, QFont, QPainter, QPen
        from PySide6.QtCore import QPointF

        pm = scaled.copy()
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.Antialiasing, True)
            w, h = pm.width(), pm.height()
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
            if view == "axial" and self._arch_points and self._axial_geom is not None:
                dx, dy = self._axial_geom[0], self._axial_geom[1]
                sx = w / dx if dx else 1.0
                sy = h / dy if dy else 1.0
                pts = [QPointF((p["col"] + 0.5) * sx, (p["row"] + 0.5) * sy) for p in self._arch_points]
                painter.setPen(QPen(QColor("#38bdf8"), 2))
                for i in range(1, len(pts)):
                    painter.drawLine(pts[i - 1], pts[i])
                painter.setPen(QPen(QColor("#f59e0b"), 2))
                for pt in pts:
                    painter.drawEllipse(pt, 4.0, 4.0)
        finally:
            painter.end()
        label.setPixmap(pm)

    def _on_slider(self, view: str, value: int) -> None:
        if self._vol is None:
            return
        self._slice_idx[view] = int(value)
        self._render_view(view)

    def _scroll_view(self, view: str, steps: int) -> None:
        """Mouse-wheel stack scroll: advance the slice index along the through-axis."""
        if self._vol is None or view not in self._plans:
            return
        through_n = 2 - self._plans[view]["through"]
        count = int(self._vol.shape[through_n])
        new_idx = max(0, min(count - 1, int(self._slice_idx.get(view, 0)) + int(steps)))
        if new_idx != self._slice_idx.get(view):
            self._slice_idx[view] = new_idx
            self._render_view(view)   # updates the slider + index too (kept in sync)

    def _rescale_planes(self) -> None:
        for view in ("axial", "coronal", "sagittal"):
            self._compose_view(view)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_planes()

    # --------------------------------------------------------------- helpers
    def _set_cell(self, plane: str, text: str) -> None:
        lbl = self._cells.get(plane)
        if lbl is not None:
            self._plane_pixmaps.pop(plane, None)
            lbl.setText(text)  # setText clears any pixmap

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

    # ----------------------------------------------------------- arch (M2a)
    def _build_arch_controls(self, frame) -> None:
        """Pick Arch / Undo / Clear buttons in the Tools cell (flag-gated)."""
        from PySide6.QtWidgets import QPushButton

        lay = frame.layout()
        style = (
            "QPushButton { font-size:11px; color:#e5edf5; padding:6px 8px;"
            " background:#1e293b; border:1px solid #334155; border-radius:6px; }"
            "QPushButton:hover { background:#334155; }"
            "QPushButton:checked { background:#0ea5e9; color:#0b1220; border-color:#38bdf8; }"
        )
        self._arch_pick_btn = QPushButton("Pick Arch")
        self._arch_pick_btn.setCheckable(True)
        self._arch_pick_btn.setStyleSheet(style)
        self._arch_pick_btn.clicked.connect(self._toggle_arch_pick)
        lay.addWidget(self._arch_pick_btn)
        for label, slot in (("Undo", self._undo_arch), ("Clear", self._clear_arch)):
            btn = QPushButton(label)
            btn.setStyleSheet(style)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

    def _toggle_arch_pick(self) -> None:
        if hasattr(self, "_arch_pick_btn"):
            self._arch_pick_mode = bool(self._arch_pick_btn.isChecked())
        else:
            self._arch_pick_mode = not self._arch_pick_mode
        if self._arch_pick_mode and self._axial_geom is None:
            self._set_status("Load a series first, then click arch points on the Axial view.")
            return
        self._set_status(
            "Arch picking ON — click points along the arch on the Axial view."
            if self._arch_pick_mode else f"Arch points: {len(self._arch_points)}"
        )

    def _undo_arch(self) -> None:
        if self._arch_points:
            self._arch_points.pop()
            self._composite_axial()
            self._set_status(f"Arch points: {len(self._arch_points)}")

    def _clear_arch(self) -> None:
        self._arch_points = []
        self._composite_axial()
        self._set_status("Arch cleared.")

    def get_arch_world_points(self):
        """World-space arch control points (input to the panoramic engine — M2b)."""
        return [p["world"] for p in self._arch_points]

    def _on_axial_click(self, cx: float, cy: float) -> None:
        from .core.arch_geometry import display_click_to_slice, slice_index_to_world

        label = self._cells.get("axial")
        if label is None or self._axial_geom is None:
            return
        dx, dy, k, origin, spacing, direction16 = self._axial_geom
        rc = display_click_to_slice(cx, cy, label.width(), label.height(), dx, dy)
        if rc is None:
            return  # click landed on the letterbox margin, not the image
        col, row = rc
        world = slice_index_to_world(col, row, k, origin, spacing, direction16)
        self._arch_points.append({"col": col, "row": row, "k": k, "world": world})
        self._composite_axial()
        self._set_status(f"Arch points: {len(self._arch_points)}")

    def _composite_axial(self) -> None:
        """Thin alias so the arch handlers (M2a) drive the unified display path. The
        axial scale + orientation labels + arch markers all live in _compose_view."""
        self._compose_view("axial")

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent

        etype = event.type()
        # Mouse-wheel stack scroll on any ortho cell (slider + index stay in sync).
        if self._nav_enabled and etype == QEvent.Wheel:
            for view in ("axial", "coronal", "sagittal"):
                if obj is self._cells.get(view):
                    try:
                        delta = event.angleDelta().y()
                        steps = 1 if delta < 0 else (-1 if delta > 0 else 0)
                        if steps:
                            self._scroll_view(view, steps)
                        return True  # consume — don't also scroll the outer layout
                    except Exception:
                        logger.exception("[DENTAL] wheel scroll failed")
                    break
        # Arch picking click on the axial cell (default-off, experimental M2a).
        if (self._arch_enabled and self._arch_pick_mode
                and obj is self._cells.get("axial")
                and etype == QEvent.MouseButtonPress):
            try:
                pos = event.position()
                self._on_axial_click(pos.x(), pos.y())
            except Exception:
                logger.exception("[DENTAL] arch click failed")
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
        # Immediate feedback — resolving + (possibly) building the volume can take a
        # moment for a non-active series.
        self._set_status(f"Loading dropped series {series_number}…")
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
        # Replace whatever was loaded with the dropped series (exact UID/metadata).
        self.load_series(context, volume)
