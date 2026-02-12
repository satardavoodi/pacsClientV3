"""Film preview widget for printing UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QPainter, QPixmap, QPen, QColor, QFont, QBrush
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QGraphicsPixmapItem, QGraphicsTextItem, QGraphicsItem

from printing.core.models import FilmLayout, FilmSize, ViewportState
from printing.layout.grid import GridLayoutEngine, GridCell
from printing.render.dicom_renderer import load_dicom_as_pixmap, get_dicom_window_level
from printing.render.film_renderer import render_film, HEADER_HEIGHT_RATIO, HEADER_PADDING_IN
from printing.ui.print_tools import PrintToolManager


@dataclass
class TileData:
    path: str
    viewport: ViewportState
    default_ww: Optional[float] = None
    default_wl: Optional[float] = None
    cell_px: tuple[int, int, int, int] | None = None


class TileItem(QGraphicsPixmapItem):
    def __init__(self, tile_index: int, pixmap: QPixmap):
        super().__init__(pixmap)
        self.tile_index = tile_index
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsFocusable)

    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)


class FilmPreviewWidget(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
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
        self._sync_mode = False
        
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

    def set_tiles(self, film_size: FilmSize, layout: FilmLayout, paths: List[str], overlay_info: Dict[str, str] | None = None):
        self._scene.clear()
        self._items = []
        self._tiles = []
        self._film_size = film_size
        self._layout = layout
        self._overlay_info = overlay_info

        grid = GridLayoutEngine()
        preview_dpi = 110
        header_height_in = film_size.height_in * HEADER_HEIGHT_RATIO
        film_area_height_in = max(0.1, film_size.height_in - header_height_in)
        film_area = FilmSize(name=film_size.name, width_in=film_size.width_in, height_in=film_area_height_in)
        cells = grid.compute_cells(film_area, layout)

        # Cell #1 is reserved for placeholder (no series image)
        if cells:
            self._draw_placeholder_cell(cells[0], preview_dpi, header_height_in)

        for cell_idx in range(1, len(cells)):
            path_idx = cell_idx - 1
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

        self._draw_preview_header(overlay_info, preview_dpi, header_height_in)
        self._draw_preview_grid(film_area, layout, preview_dpi, y_offset_in=header_height_in)

        if self._items:
            # Ensure a deterministic default selection (first non-scout image)
            if not any(item.isSelected() for item in self._items):
                for item in self._items:
                    tile = self._tiles[item.tile_index] if item.tile_index < len(self._tiles) else None
                    if tile and not tile.is_scout:
                        item.setSelected(True)
                        break
                if not any(item.isSelected() for item in self._items):
                    self._items[0].setSelected(True)
            self._scene.setSceneRect(self._scene.itemsBoundingRect())
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def _draw_preview_header(self, overlay_info: Dict[str, str] | None, dpi: int, header_height_in: float) -> None:
        if not overlay_info:
            overlay_info = {}
        patient_name = overlay_info.get("patient_name") or "Unknown Patient"
        patient_id = overlay_info.get("patient_id") or "Unknown ID"
        institution = overlay_info.get("institution") or "Unknown Institution"

        x_px = int(HEADER_PADDING_IN * dpi)
        y_px = int(HEADER_PADDING_IN * dpi)

        name_item = QGraphicsTextItem(patient_name)
        name_item.setDefaultTextColor(QColor(240, 240, 240))
        name_font = QFont()
        name_font.setPointSize(16)
        name_font.setBold(True)
        name_item.setFont(name_font)
        name_item.setPos(x_px, y_px)
        self._scene.addItem(name_item)

        info_item = QGraphicsTextItem(f"Patient ID: {patient_id}\nInstitution: {institution}")
        info_item.setDefaultTextColor(QColor(220, 220, 220))
        info_font = QFont()
        info_font.setPointSize(11)
        info_item.setFont(info_font)
        info_item.setPos(x_px, y_px + int(0.28 * dpi))
        self._scene.addItem(info_item)

        separator_y = int(header_height_in * dpi)
        pen = QPen(QColor(255, 255, 255))
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

        brush = QBrush(QColor(255, 255, 255))
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

    def _draw_placeholder_cell(self, cell: GridCell, dpi: int, header_height_in: float) -> None:
        x_px = int(cell.x * dpi)
        y_px = int((cell.y + header_height_in) * dpi)
        w_px = int(cell.width * dpi)
        h_px = int(cell.height * dpi)

        pen = QPen(QColor(120, 120, 120))
        pen.setStyle(Qt.DashLine)
        pen.setWidth(1)
        self._scene.addRect(x_px, y_px, w_px, h_px, pen)

        placeholder = QGraphicsTextItem("Placeholder")
        placeholder.setDefaultTextColor(QColor(160, 160, 160))
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
            return [tile.path for tile in self._tiles]

        selected_indices = {item.tile_index for item in selected_items}
        self._tiles = [tile for idx, tile in enumerate(self._tiles) if idx not in selected_indices]
        remaining_paths = [tile.path for tile in self._tiles]
        if self._film_size and self._layout:
            self.set_tiles(self._film_size, self._layout, remaining_paths, self._overlay_info)
        return remaining_paths

    def export_film_pixmap(self, dpi: int = 300) -> QPixmap | None:
        if not self._film_size or not self._layout:
            return None
        from printing.render.dicom_renderer import load_dicom_as_pixmap
        from printing.render.film_renderer import _draw_grid_lines
        
        rendered_images = []
        for tile in self._tiles:
            rendered = load_dicom_as_pixmap(tile.path, tile.viewport)
            if rendered:
                rendered_images.append(rendered)
        
        pixmap = render_film(
            rendered_images,
            self._film_size,
            self._layout,
            dpi=dpi,
            overlay_info=self._overlay_info,
            start_cell_index=1,
        )
        
        # Grid lines are already drawn by render_film
        return pixmap

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._scene.items():
            self.fitInView(self._scene.sceneRect(), Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        """Handle mouse press events matching PACS viewer behavior."""
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
