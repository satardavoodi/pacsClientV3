"""Film preview widget for printing UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QPointF, QTimer, QEvent
from PySide6.QtGui import QPainter, QPixmap, QPen, QColor, QFont, QBrush, QMouseEvent
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem

from modules.printing.core.models import FilmLayout, FilmSize, ViewportState
from modules.printing.layout.grid import GridLayoutEngine, GridCell
from modules.printing.render.dicom_renderer import (
    load_dicom_as_pixmap,
    get_dicom_window_level,
    compute_scout_reference_lines,
)
from modules.printing.render.film_renderer import render_film, HEADER_HEIGHT_RATIO, HEADER_PADDING_IN
from modules.printing.ui.print_tools import PrintToolManager
from PacsClient.utils.theme_manager import get_theme_manager


@dataclass
class TileData:
    path: str
    viewport: ViewportState
    default_ww: Optional[float] = None
    default_wl: Optional[float] = None
    cell_px: tuple[int, int, int, int] | None = None
    is_scout: bool = False


class TileItem(QGraphicsPixmapItem):
    def __init__(self, tile_index: int, pixmap: QPixmap):
        super().__init__(pixmap)
        self.tile_index = tile_index
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            painter.save()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(59, 130, 246, 80))
            painter.drawRect(self.boundingRect())
            painter.restore()


class FilmPreviewWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme_manager = get_theme_manager()
        self._theme = self._theme_manager.current_theme()
        self._theme_manager.themeChanged.connect(self._on_theme_changed)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(self.renderHints() | QPainter.Antialiasing)
        self.setAlignment(Qt.AlignCenter)
        self.setDragMode(QGraphicsView.NoDrag)
        self._items: List[TileItem] = []
        self._tiles: List[TileData] = []
        self._film_size: FilmSize | None = None
        self._layout: FilmLayout | None = None
        self._overlay_info: Dict[str, str] | None = None
        self._paths: List[str] = []
        self._scout_path: str | None = None
        self._scout_item: QGraphicsPixmapItem | None = None
        self._scout_tile_index: int | None = None
        self._last_selected_index: int | None = None
        self._sync_mode = False
        self._ref_line_items: List = []  # Track reference line scene items for cleanup
        
        # Tool mode management (matching PACS viewer)
        self._tool_manager = PrintToolManager()
        
        # Mouse state tracking (matching PACS viewer)
        self._left_button_down = False
        self._right_button_down = False
        self._middle_button_down = False
        self._pan_active = False
        self._last_pos = QPointF()
        
        # Interaction sensitivity parameters (matching PACS viewer)
        self._pan_sensitivity = 0.003
        self._window_width_sensitivity = 1.5
        self._window_level_sensitivity = 1.3
        self._zoom_sensitivity = 0.005

        # Throttle rerenders to keep interactions smooth
        self._pending_tiles: List[TileData] = []
        self._rerender_timer = QTimer(self)
        self._rerender_timer.setSingleShot(True)
        self._rerender_timer.timeout.connect(self._flush_rerender)
        self._rerender_interval_ms = 16
        self.setStyleSheet(
            f"QGraphicsView {{ background-color: {self._theme['panel_deep_bg']}; border: 1px solid {self._theme['border']}; border-radius: 8px; }}"
        )

    def _on_theme_changed(self, theme: Dict[str, str]):
        self._theme = theme or self._theme_manager.current_theme()
        self.setStyleSheet(
            f"QGraphicsView {{ background-color: {self._theme['panel_deep_bg']}; border: 1px solid {self._theme['border']}; border-radius: 8px; }}"
        )
        if self._film_size and self._layout:
            self.set_tiles(self._film_size, self._layout, self._paths, self._overlay_info)

    def _should_reserve_scout_slot(self, total_cells: int) -> bool:
        # Keep historical scout/placeholder behavior for multi-cell layouts,
        # but do not reserve the only cell in 1x1 unless an actual scout exists.
        return bool(self._scout_path) or total_cells > 1

    def set_tiles(self, film_size: FilmSize, layout: FilmLayout, paths: List[str], overlay_info: Dict[str, str] | None = None):
        self._scene.clear()
        self._items = []
        self._tiles = []
        self._ref_line_items = []  # scene.clear() already removed them
        self._film_size = film_size
        self._layout = layout
        self._overlay_info = overlay_info
        self._paths = list(paths)
        self._scout_item = None
        self._scout_tile_index = None
        self._last_selected_index = None
        sequence_start = int((overlay_info or {}).get("sequence_start", 1) or 1)

        grid = GridLayoutEngine()
        preview_dpi = 110
        header_height_in = film_size.height_in * HEADER_HEIGHT_RATIO
        film_area_height_in = max(0.1, film_size.height_in - header_height_in)
        film_area = FilmSize(name=film_size.name, width_in=film_size.width_in, height_in=film_area_height_in)

        # ── Film background: defines the exact physical film shape ──
        film_w_px = int(film_size.width_in * preview_dpi)
        film_h_px = int(film_size.height_in * preview_dpi)
        bg_rect = QGraphicsRectItem(0, 0, film_w_px, film_h_px)
        bg_rect.setBrush(QBrush(QColor(self._theme["panel_bg"])))
        bg_rect.setPen(QPen(Qt.NoPen))
        bg_rect.setZValue(-100)  # behind everything
        bg_rect.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(bg_rect)

        cells = grid.compute_cells(film_area, layout)
        reserve_scout_slot = self._should_reserve_scout_slot(len(cells))
        start_cell_index = 1 if reserve_scout_slot else 0

        # Cell #1 is reserved for scout image or placeholder
        if reserve_scout_slot and cells:
            if self._scout_path:
                self._draw_scout_cell(cells[0], preview_dpi, header_height_in)
            else:
                self._draw_placeholder_cell(cells[0], preview_dpi, header_height_in)

        for cell_idx in range(start_cell_index, len(cells)):
            path_idx = cell_idx - start_cell_index
            if path_idx >= len(paths):
                break
            cell = cells[cell_idx]
            path = paths[path_idx]
            ww, wl = get_dicom_window_level(path)
            viewport = ViewportState(window_width=None, window_level=None, zoom=1.0, pan=(0.0, 0.0))
            tile = TileData(path=path, viewport=viewport, default_ww=ww, default_wl=wl)
            rendered = load_dicom_as_pixmap(path, viewport)
            if not rendered:
                continue
            x_in, y_in, w_in, h_in = grid.map_image_to_cell(cell, rendered.aspect)
            x_px = int(x_in * preview_dpi)
            y_px = int((y_in + header_height_in) * preview_dpi)
            w_px = int(w_in * preview_dpi)
            h_px = int(h_in * preview_dpi)
            scaled = rendered.pixmap.scaled(w_px, h_px)
            tile_index = len(self._tiles)
            item = TileItem(tile_index, scaled)
            item.setPos(x_px, y_px)
            item.setToolTip(path)
            self._scene.addItem(item)
            self._items.append(item)
            tile.cell_px = (x_px, y_px, w_px, h_px)
            self._tiles.append(tile)
            self._draw_tile_sequence_number(x_px, y_px, sequence_start + path_idx)

        self._draw_preview_header(overlay_info, preview_dpi, header_height_in)
        self._draw_preview_grid(film_area, layout, preview_dpi, y_offset_in=header_height_in)
        if self._scout_path:
            self._draw_scout_reference_lines(preview_dpi)

        if self._items:
            if not any(item.isSelected() for item in self._items):
                preferred = None
                for item in self._items:
                    tile = self._tiles[item.tile_index] if item.tile_index < len(self._tiles) else None
                    if tile and not tile.is_scout:
                        preferred = item
                        break
                (preferred or self._items[0]).setSelected(True)

        # Set scene rect to exact film dimensions so fitInView shows the
        # correct aspect ratio for each film size (A3, A4, 14×17, etc.)
        self._scene.setSceneRect(0, 0, film_w_px, film_h_px)
        self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def set_scout_path(self, scout_path: str | None) -> None:
        self._scout_path = scout_path
        if self._film_size and self._layout:
            self.set_tiles(self._film_size, self._layout, self._paths, self._overlay_info)

    def get_scout_path(self) -> str | None:
        return self._scout_path

    def _draw_preview_header(self, overlay_info: Dict[str, str] | None, dpi: int, header_height_in: float) -> None:
        t = self._theme
        if not overlay_info:
            overlay_info = {}
        patient_name = overlay_info.get("patient_name") or "Unknown Patient"
        patient_id = overlay_info.get("patient_id") or "Unknown ID"
        institution = overlay_info.get("institution") or "Unknown Institution"
        center_name = overlay_info.get("center_name") or institution
        right_line_1 = overlay_info.get("header_right_line_1") or ""
        right_line_2 = overlay_info.get("header_right_line_2") or ""

        # User-configurable font sizes (passed through overlay_info)
        fs_patient_name = int(overlay_info.get("font_patient_name", 24) or 24)
        fs_patient_id = int(overlay_info.get("font_patient_id", 18) or 18)
        fs_center_name = int(overlay_info.get("font_center_name", 42) or 42)
        fs_right_block = int(overlay_info.get("font_right_block", 18) or 18)

        x_px = int(HEADER_PADDING_IN * dpi)
        y_px = int(HEADER_PADDING_IN * dpi)
        header_height_px = int(header_height_in * dpi)
        width_px = int(self._film_size.width_in * dpi)

        # Left block (2 lines)
        left_name = QGraphicsTextItem(patient_name)
        left_name.setDefaultTextColor(QColor(t["text_primary"]))
        left_name_font = QFont()
        left_name_font.setPointSize(fs_patient_name)
        left_name_font.setBold(True)
        left_name.setFont(left_name_font)
        left_name.setPos(x_px, y_px)
        left_name.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(left_name)

        left_id = QGraphicsTextItem(f"ID: {patient_id}")
        left_id.setDefaultTextColor(QColor(t["text_secondary"]))
        left_id_font = QFont()
        left_id_font.setPointSize(fs_patient_id)
        left_id.setFont(left_id_font)
        left_id.setPos(x_px, y_px + left_name.boundingRect().height())
        left_id.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(left_id)

        # Center title (single centered line)
        center_item = QGraphicsTextItem(center_name)
        center_item.setDefaultTextColor(QColor(t["text_primary"]))
        center_font = QFont()
        center_font.setPointSize(fs_center_name)
        center_font.setBold(True)
        center_item.setFont(center_font)
        center_rect = center_item.boundingRect()
        center_item.setPos((width_px - center_rect.width()) / 2, (header_height_px - center_rect.height()) / 2)
        center_item.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(center_item)

        # Right block (2 lines)
        right1 = QGraphicsTextItem(right_line_1)
        right1.setDefaultTextColor(QColor(t["text_secondary"]))
        right_font = QFont()
        right_font.setPointSize(fs_right_block)
        right1.setFont(right_font)
        right1_rect = right1.boundingRect()
        right1.setPos(width_px - right1_rect.width() - x_px, y_px)
        right1.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(right1)

        right2 = QGraphicsTextItem(right_line_2)
        right2.setDefaultTextColor(QColor(t["text_muted"]))
        right2.setFont(right_font)
        right2_rect = right2.boundingRect()
        right2.setPos(width_px - right2_rect.width() - x_px, y_px + right1.boundingRect().height())
        right2.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(right2)

        separator_y = int(header_height_in * dpi)
        pen = QPen(QColor(t["border"]))
        self._scene.addLine(0, separator_y, int(self._film_size.width_in * dpi), separator_y, pen)

    def _draw_preview_grid(
        self,
        film_area: FilmSize,
        layout: FilmLayout,
        dpi: int,
        y_offset_in: float = 0.0,
    ) -> None:
        grid = GridLayoutEngine()
        cells = grid.compute_cells(film_area, layout)
        grid_line_px = int(grid.GRID_LINE_WIDTH_IN * dpi)
        if grid_line_px < 1:
            grid_line_px = 1

        width_px = int(film_area.width_in * dpi)
        height_px = int(film_area.height_in * dpi)
        y_offset_px = int(y_offset_in * dpi)

        cell_w = cells[0].width if cells else film_area.width_in
        cell_h = cells[0].height if cells else film_area.height_in
        line_in = grid.GRID_LINE_WIDTH_IN

        brush = QBrush(QColor(self._theme["border"]))
        no_pen = QPen(Qt.NoPen)

        # Vertical lines (including left/right borders)
        x_positions_in = [0.0]
        for col in range(1, layout.cols):
            x_positions_in.append(col * cell_w + (col - 1) * line_in)
        x_positions_in.append(max(0.0, film_area.width_in - line_in))

        for x_in in x_positions_in:
            x_px = int(x_in * dpi)
            self._scene.addRect(x_px, y_offset_px, grid_line_px, height_px, no_pen, brush)

        # Horizontal lines (including top/bottom borders)
        y_positions_in = [0.0]
        for row in range(1, layout.rows):
            y_positions_in.append(row * cell_h + (row - 1) * line_in)
        y_positions_in.append(max(0.0, film_area.height_in - line_in))

        for y_in in y_positions_in:
            y_px = int(y_in * dpi)
            self._scene.addRect(0, y_offset_px + y_px, width_px, grid_line_px, no_pen, brush)

    def _draw_scout_cell(self, cell: GridCell, dpi: int, header_height_in: float) -> None:
        if not self._scout_path:
            return
        ww, wl = get_dicom_window_level(self._scout_path)
        viewport = ViewportState(window_width=None, window_level=None, zoom=1.0, pan=(0.0, 0.0))
        rendered = load_dicom_as_pixmap(self._scout_path, viewport)
        if not rendered:
            self._draw_placeholder_cell(cell, dpi, header_height_in)
            return

        x_in, y_in, w_in, h_in = GridLayoutEngine().map_image_to_cell(cell, rendered.aspect)
        x_px = int(x_in * dpi)
        y_px = int((y_in + header_height_in) * dpi)
        w_px = int(w_in * dpi)
        h_px = int(h_in * dpi)
        scaled = rendered.pixmap.scaled(w_px, h_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        tile = TileData(path=self._scout_path, viewport=viewport, default_ww=ww, default_wl=wl, is_scout=True)
        tile_index = len(self._tiles)
        item = TileItem(tile_index, scaled)
        item.setPos(x_px, y_px)
        item.setToolTip(self._scout_path)
        self._scene.addItem(item)
        tile.cell_px = (x_px, y_px, w_px, h_px)
        self._tiles.append(tile)
        self._items.append(item)
        self._scout_item = item
        self._scout_tile_index = tile_index

    def _remove_ref_line_items(self) -> None:
        """Remove all tracked reference line items from scene."""
        for item in self._ref_line_items:
            try:
                self._scene.removeItem(item)
            except Exception:
                pass
        self._ref_line_items = []

    def _draw_scout_reference_lines(self, dpi: int) -> None:
        if not self._scout_path or not self._paths:
            return

        rows_s, cols_s, lines = compute_scout_reference_lines(self._scout_path, self._paths)
        if rows_s <= 0 or cols_s <= 0 or not lines:
            return

        if not self._film_size or not self._layout:
            return
        grid = GridLayoutEngine()
        header_height_in = self._film_size.height_in * HEADER_HEIGHT_RATIO
        film_area_height_in = max(0.1, self._film_size.height_in - header_height_in)
        film_area = FilmSize(name=self._film_size.name, width_in=self._film_size.width_in, height_in=film_area_height_in)
        cells = grid.compute_cells(film_area, self._layout)
        if not cells:
            return
        cell = cells[0]
        x_px = int(cell.x * dpi)
        y_px = int((cell.y + header_height_in) * dpi)
        w_px = int(cell.width * dpi)
        h_px = int(cell.height * dpi)

        # Create a clipping container at the scout cell bounds.
        # All reference line items are children of this rect, so Qt
        # automatically clips them to the scout cell area.
        clip_rect = QGraphicsRectItem(0, 0, w_px, h_px)
        clip_rect.setPos(x_px, y_px)
        clip_rect.setPen(QPen(Qt.NoPen))  # invisible border
        clip_rect.setBrush(QBrush(Qt.NoBrush))  # transparent fill
        clip_rect.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        clip_rect.setZValue(98)  # above images, below tile badges
        clip_rect.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(clip_rect)
        self._ref_line_items.append(clip_rect)

        # Get the scout tile's current viewport (zoom/pan) state
        scout_viewport = None
        if self._scout_tile_index is not None and self._scout_tile_index < len(self._tiles):
            scout_viewport = self._tiles[self._scout_tile_index].viewport

        zoom = max(scout_viewport.zoom, 1.0) if scout_viewport else 1.0
        pan_x, pan_y = scout_viewport.pan if scout_viewport else (0.0, 0.0)

        # Apply the same viewport transform that _apply_viewport uses on pixels:
        # The visible portion of the image is a crop of size (cols_s/zoom, rows_s/zoom)
        # centered at (center + pan_offset).
        crop_w = cols_s / zoom
        crop_h = rows_s / zoom
        center_x = cols_s / 2.0 + pan_x * crop_w / 2.0
        center_y = rows_s / 2.0 + pan_y * crop_h / 2.0
        crop_x0 = center_x - crop_w / 2.0
        crop_y0 = center_y - crop_h / 2.0

        # Scale from cropped DICOM pixel coords to screen cell coords
        scale_x = w_px / crop_w
        scale_y = h_px / crop_h

        pen = QPen(QColor(self._theme["warning"]))
        pen.setWidth(1)

        label_margin = 4  # pixels from edge

        # Reference line rules:
        # - Lines are positioned by true physical slice position
        # - Displayed numbers = visible slot index (1-based sequential)
        # - Only odd-numbered visible slots are rendered (1, 3, 5, 7, ...)
        # - All items are children of clip_rect so coordinates are relative to (0,0) = cell top-left
        for idx, (x0, y0, x1, y1) in enumerate(lines):
            visible_slot = idx + 1  # 1-based visible slot number
            if visible_slot % 2 == 0:
                continue  # Skip even-numbered slots

            # Transform from original DICOM pixel coords to local cell coords
            local_x0 = (x0 - crop_x0) * scale_x
            local_y0 = (y0 - crop_y0) * scale_y
            local_x1 = (x1 - crop_x0) * scale_x
            local_y1 = (y1 - crop_y0) * scale_y

            # Create line as child of clip_rect (auto-clipped)
            line_item = QGraphicsLineItem(local_x0, local_y0, local_x1, local_y1, clip_rect)
            line_item.setPen(pen)
            line_item.setZValue(1)

            # Create label as child of clip_rect (auto-clipped)
            label = str(visible_slot)
            text = QGraphicsTextItem(label, clip_rect)
            font = QFont()
            font.setPointSize(12)
            font.setBold(True)
            text.setFont(font)
            text.setDefaultTextColor(QColor(self._theme["warning"]))
            text.setAcceptedMouseButtons(Qt.NoButton)
            text.setZValue(2)

            # Position label at ~1/3 along the line (from start towards end)
            # so it stays inside the visible image area even when zoomed.
            text_rect = text.boundingRect()
            tw = text_rect.width()
            th = text_rect.height()

            anchor_x = local_x0 + (local_x1 - local_x0) / 3.0
            anchor_y = local_y0 + (local_y1 - local_y0) / 3.0

            # Offset slightly above the line so it doesn't overlap
            text_x = anchor_x - tw / 2.0
            text_y = anchor_y - th - 2

            # Clamp to stay within the clip rect (cell bounds)
            text_x = max(label_margin, min(text_x, w_px - tw - label_margin))
            text_y = max(label_margin, min(text_y, h_px - th - label_margin))

            text.setPos(text_x, text_y)

    def _draw_tile_sequence_number(self, x_px: int, y_px: int, number: int) -> None:
        badge = QGraphicsTextItem(str(number))
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        badge.setFont(font)
        badge.setDefaultTextColor(QColor(self._theme["warning"]))
        badge.setPos(x_px + 6, y_px + 4)
        badge.setAcceptedMouseButtons(Qt.NoButton)
        self._scene.addItem(badge)

    def _draw_placeholder_cell(self, cell: GridCell, dpi: int, header_height_in: float) -> None:
        x_px = int(cell.x * dpi)
        y_px = int((cell.y + header_height_in) * dpi)
        w_px = int(cell.width * dpi)
        h_px = int(cell.height * dpi)

        pen = QPen(QColor(self._theme["text_muted"]))
        pen.setStyle(Qt.DashLine)
        pen.setWidth(1)
        self._scene.addRect(x_px, y_px, w_px, h_px, pen)

        placeholder = QGraphicsTextItem("Placeholder")
        placeholder.setDefaultTextColor(QColor(self._theme["text_muted"]))
        font = QFont()
        font.setPointSize(12)
        font.setBold(True)
        placeholder.setFont(font)
        text_rect = placeholder.boundingRect()
        placeholder.setPos(
            x_px + (w_px - text_rect.width()) / 2,
            y_px + (h_px - text_rect.height()) / 2,
        )
        self._scene.addItem(placeholder)

    def set_left_drag_mode(self, mode: str):
        self._left_drag_mode = mode

    def set_sync_mode(self, enabled: bool):
        self._sync_mode = enabled

    def apply_viewport_override(self, ww: float, wl: float, zoom: float, pan: tuple[float, float]):
        tiles = self._target_tiles()
        for tile in tiles:
            tile.viewport = ViewportState(window_width=ww, window_level=wl, zoom=zoom, pan=pan)
        self._rerender_tiles(tiles)

    def delete_selected_tiles(self) -> List[str]:
        selected_items = [item for item in self._items if item.isSelected()]
        if not selected_items:
            return [tile.path for tile in self._tiles if not tile.is_scout]

        selected_indices = {item.tile_index for item in selected_items}
        if self._scout_tile_index is not None and self._scout_tile_index in selected_indices:
            self._scout_path = None
        self._tiles = [tile for idx, tile in enumerate(self._tiles) if idx not in selected_indices]
        remaining_paths = [tile.path for tile in self._tiles if not tile.is_scout]
        if self._film_size and self._layout:
            self.set_tiles(self._film_size, self._layout, remaining_paths, self._overlay_info)
        return remaining_paths

    def export_film_pixmap(self, dpi: int = 300) -> QPixmap | None:
        if not self._film_size or not self._layout:
            return None
        from modules.printing.render.dicom_renderer import load_dicom_as_pixmap
        
        rendered_images = []
        scout_info = None
        total_cells = self._layout.rows * self._layout.cols
        reserve_scout_slot = self._should_reserve_scout_slot(total_cells)
        start_cell_index = 1 if reserve_scout_slot else 0
        if self._scout_path:
            scout_render = load_dicom_as_pixmap(self._scout_path, None)
            if scout_render:
                rendered_images.append(scout_render)
                scout_info = (self._scout_path, [tile.path for tile in self._tiles if not tile.is_scout])
                start_cell_index = 0

        for tile in self._tiles:
            if tile.is_scout:
                continue
            rendered = load_dicom_as_pixmap(tile.path, tile.viewport)
            if rendered:
                rendered_images.append(rendered)
        
        pixmap = render_film(
            rendered_images,
            self._film_size,
            self._layout,
            dpi=dpi,
            overlay_info=self._overlay_info,
            start_cell_index=start_cell_index,
            scout_info=scout_info,
        )
        
        # Grid lines are already drawn by render_film
        return pixmap

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._scene.items():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def viewportEvent(self, event):
        """Intercept viewport events BEFORE QGraphicsScene processes them.
        
        QGraphicsView routes mouse events through viewportEvent -> scene.
        If we only override mousePressEvent, the scene's default handler
        processes selection first (because TileItem has ItemIsSelectable),
        and our mousePressEvent never fires. By intercepting here, we
        handle Ctrl/Shift selection ourselves and prevent the scene from
        overriding our logic.
        """
        etype = event.type()
        
        if etype == QEvent.MouseButtonPress and isinstance(event, QMouseEvent):
            btn = event.button()
            mods = event.modifiers()
            if btn == Qt.LeftButton:
                self._left_button_down = True
                self._last_pos = event.position()
                # Handle our custom selection BEFORE the scene does
                self._handle_selection_click(event)
                # Consume event so QGraphicsScene doesn't override our selection
                return True
            elif btn == Qt.RightButton:
                self._right_button_down = True
                self._last_pos = event.position()
            elif btn == Qt.MiddleButton:
                self._middle_button_down = True
                self._last_pos = event.position()
                
        elif etype == QEvent.MouseMove and isinstance(event, QMouseEvent):
            if self._left_button_down or self._right_button_down or self._middle_button_down:
                current_pos = event.position()
                delta_x = current_pos.x() - self._last_pos.x()
                delta_y = current_pos.y() - self._last_pos.y()
                
                if self._tool_manager.is_pan_mode():
                    self._apply_pan(delta_x, delta_y)
                elif self._tool_manager.is_zoom_mode():
                    self._apply_zoom(delta_y)
                elif self._tool_manager.is_window_level_mode():
                    self._apply_window_level(delta_x, delta_y)
                elif self._tool_manager.is_default_mode():
                    if self._left_button_down:
                        self._apply_window_level(delta_x, delta_y)
                    elif self._right_button_down:
                        self._apply_zoom(delta_y)
                    elif self._middle_button_down:
                        self._apply_pan(delta_x, delta_y)
                
                self._last_pos = current_pos
                return True  # consume so scene doesn't interfere

        elif etype == QEvent.MouseButtonRelease and isinstance(event, QMouseEvent):
            btn = event.button()
            if btn == Qt.LeftButton:
                self._left_button_down = False
            elif btn == Qt.RightButton:
                self._right_button_down = False
            elif btn == Qt.MiddleButton:
                self._middle_button_down = False
            if btn == Qt.LeftButton:
                return True  # consume left release too

        return super().viewportEvent(event)

    def mousePressEvent(self, event):
        """Handle mouse press events matching PACS viewer behavior."""
        # NOTE: For left-click, viewportEvent already handled selection
        # and returned True, so this is only reached for right/middle clicks
        # that are forwarded by super().viewportEvent().
        if event.button() == Qt.LeftButton:
            self._left_button_down = True
            self._last_pos = event.position()
        elif event.button() == Qt.RightButton:
            self._right_button_down = True
            self._last_pos = event.position()
        elif event.button() == Qt.MiddleButton:
            self._middle_button_down = True
            self._last_pos = event.position()
        
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """Handle mouse move events matching PACS viewer behavior."""
        if not (self._left_button_down or self._right_button_down or self._middle_button_down):
            super().mouseMoveEvent(event)
            return
        
        current_pos = event.position()
        delta_x = current_pos.x() - self._last_pos.x()
        delta_y = current_pos.y() - self._last_pos.y()
        
        # Tool mode: PAN
        if self._tool_manager.is_pan_mode():
            self._apply_pan(delta_x, delta_y)
        
        # Tool mode: ZOOM
        elif self._tool_manager.is_zoom_mode():
            self._apply_zoom(delta_y)
        
        # Tool mode: WINDOW_LEVEL
        elif self._tool_manager.is_window_level_mode():
            self._apply_window_level(delta_x, delta_y)
        
        # Default mode mappings:
        # Left drag  -> Window Level/Width
        # Right drag -> Zoom
        # Middle drag -> Pan
        elif self._tool_manager.is_default_mode():
            if self._left_button_down:
                self._apply_window_level(delta_x, delta_y)
            elif self._right_button_down:
                self._apply_zoom(delta_y)
            elif self._middle_button_down:
                self._apply_pan(delta_x, delta_y)
        
        self._last_pos = current_pos
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """Handle mouse release events."""
        if event.button() == Qt.LeftButton:
            self._left_button_down = False
        elif event.button() == Qt.RightButton:
            self._right_button_down = False
        elif event.button() == Qt.MiddleButton:
            self._middle_button_down = False
        
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        # Keep wheel zoom unless user explicitly requests change.
        self._apply_zoom(event.angleDelta().y())

    def _handle_selection_click(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        while item is not None and not isinstance(item, TileItem):
            item = item.parentItem()

        shift_pressed = bool(event.modifiers() & Qt.ShiftModifier)
        ctrl_pressed = bool(event.modifiers() & Qt.ControlModifier)

        if item is None:
            if not shift_pressed and not ctrl_pressed:
                for tile_item in self._items:
                    tile_item.setSelected(False)
            return

        clicked_index = item.tile_index
        was_selected = item.isSelected()

        if shift_pressed and self._last_selected_index is not None:
            start = min(self._last_selected_index, clicked_index)
            end = max(self._last_selected_index, clicked_index)
            for tile_item in self._items:
                tile_item.setSelected(start <= tile_item.tile_index <= end)
        else:
            if not ctrl_pressed:
                for tile_item in self._items:
                    tile_item.setSelected(False)
                item.setSelected(True)
            else:
                # Ctrl pressed: toggle the clicked item
                item.setSelected(not was_selected)

        self._last_selected_index = clicked_index

    def _target_tiles(self) -> List[TileData]:
        if self._sync_mode:
            return self._tiles
        selected_indices = {item.tile_index for item in self._items if item.isSelected()}
        if not selected_indices:
            # Default to first image when nothing is selected
            if self._items:
                for item in self._items:
                    tile = self._tiles[item.tile_index] if item.tile_index < len(self._tiles) else None
                    if tile:
                        item.setSelected(True)
                        selected_indices = {item.tile_index}
                        break
                if not selected_indices:
                    self._items[0].setSelected(True)
                    selected_indices = {self._items[0].tile_index}
        return [tile for idx, tile in enumerate(self._tiles) if idx in selected_indices]

    def set_tool_mode(self, tool_mode: str) -> None:
        """Set the current tool mode (matching PACS toolbar)."""
        self._tool_manager.set_tool(tool_mode)

    def get_tool_mode(self) -> str:
        """Get the current tool mode."""
        return self._tool_manager.get_tool()

    def _apply_window_level(self, dx: float, dy: float):
        """
        Apply window level/width adjustment (matching PACS viewer).
        
        Parameters:
        - dx: horizontal mouse movement (window width sensitivity: 1.5x)
        - dy: vertical mouse movement (window level sensitivity: 1.3x, inverted)
        
        This matches the PACS viewer behavior: dx changes width, dy (inverted) changes level/center.
        """
        tiles = self._target_tiles()
        for tile in tiles:
            ww = tile.viewport.window_width or tile.default_ww or 400.0
            wl = tile.viewport.window_level or tile.default_wl or 40.0
            
            # dx: window width adjustment (1.5x sensitivity, matching PACS)
            new_window_width = ww + dx * self._window_width_sensitivity
            new_window_width = max(1.0, new_window_width)
            
            # dy: window level adjustment (1.3x sensitivity, inverted to match PACS)
            # In PACS: moving mouse up decreases window level, down increases it
            new_window_level = wl - dy * self._window_level_sensitivity
            
            tile.viewport = ViewportState(
                window_width=new_window_width,
                window_level=new_window_level,
                zoom=tile.viewport.zoom,
                pan=tile.viewport.pan
            )
        self._rerender_tiles(tiles)

    def _apply_pan(self, dx: float, dy: float):
        """
        Apply pan adjustment (matching PACS viewer).
        
        Parameters:
        - dx: horizontal mouse movement
        - dy: vertical mouse movement
        
        Pan sensitivity adjusted based on zoom level.
        """
        tiles = self._target_tiles()
        for tile in tiles:
            pan_x, pan_y = tile.viewport.pan
            
            # Adjust pan sensitivity based on zoom level (matching PACS)
            pan_delta = self._pan_sensitivity
            if tile.viewport.zoom > 1.5:
                pan_delta = 0.004
            
            new_pan_x = pan_x - dx * pan_delta
            new_pan_y = pan_y - dy * pan_delta
            
            tile.viewport = ViewportState(
                window_width=tile.viewport.window_width,
                window_level=tile.viewport.window_level,
                zoom=tile.viewport.zoom,
                pan=(new_pan_x, new_pan_y)
            )
        self._rerender_tiles(tiles)

    def _apply_zoom(self, delta: float):
        """
        Apply zoom adjustment (matching PACS viewer).
        
        Parameters:
        - delta: vertical mouse movement or wheel delta
        
        Matching PACS behavior: positive delta zooms in, negative zooms out.
        Uses smooth zooming with sensitivity factor.
        """
        tiles = self._target_tiles()
        
        if delta == 0:
            return
        
        # Calculate zoom factor matching PACS behavior
        # zoom_sensitivity = 0.005 in PACS viewer
        if delta > 0:  # Zoom in (mouse up or positive wheel delta)
            zoom_factor = 1.0 + abs(delta) * self._zoom_sensitivity
        else:  # Zoom out (mouse down or negative wheel delta)
            zoom_factor = 1.0 / (1.0 + abs(delta) * self._zoom_sensitivity)
        
        for tile in tiles:
            new_zoom = tile.viewport.zoom * zoom_factor
            new_zoom = max(1.0, new_zoom)
            
            tile.viewport = ViewportState(
                window_width=tile.viewport.window_width,
                window_level=tile.viewport.window_level,
                zoom=new_zoom,
                pan=tile.viewport.pan
            )
        
        self._rerender_tiles(tiles)

    def _rerender_tiles(self, tiles: List[TileData]):
        if not tiles:
            return
        # Coalesce updates to avoid heavy rerenders on every mouse event
        self._pending_tiles = tiles
        if not self._rerender_timer.isActive():
            self._rerender_timer.start(self._rerender_interval_ms)

    def _flush_rerender(self):
        tiles = self._pending_tiles
        if not tiles:
            return
        self._pending_tiles = []
        preview_dpi = 110
        
        # If scout was panned/zoomed, redraw reference lines to track scout
        scout_adjusted = False
        for tile in tiles:
            if tile.is_scout:
                scout_adjusted = True
                break
        
        for tile in tiles:
            if not tile.cell_px:
                continue
            x_px, y_px, w_px, h_px = tile.cell_px
            rendered = load_dicom_as_pixmap(tile.path, tile.viewport)
            if not rendered:
                continue
            scaled = rendered.pixmap.scaled(w_px, h_px, Qt.KeepAspectRatio, Qt.FastTransformation)
            tile_index = self._tiles.index(tile)
            for item in self._items:
                if item.tile_index == tile_index:
                    item.setPixmap(scaled)
                    item.setPos(x_px, y_px)
                    break
        
        # Redraw scout reference lines after scout adjustment to keep them attached
        if scout_adjusted and self._scout_path:
            self._remove_ref_line_items()
            self._draw_scout_reference_lines(preview_dpi)
