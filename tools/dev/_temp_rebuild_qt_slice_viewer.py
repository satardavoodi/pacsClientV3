"""
Reconstruction script for qt_slice_viewer.py
Adds tool support (tool modes, controller routing, hover, drag) to the base file.
Run once then delete.
"""
import os

TARGET = os.path.join(
    os.path.dirname(__file__), '..', '..', 'modules', 'viewer', 'fast', 'qt_slice_viewer.py'
)

with open(TARGET, encoding='utf-8') as f:
    content = f.read()

# ── Step 1: Add class constants after MAX_ZOOM ────────────────────────────

TOOL_CONSTANTS = '''
    # Tool modes (set by toolbar via bridge style)
    TOOL_NONE = ""
    TOOL_ZOOM = "zoom"
    TOOL_WINDOW_LEVEL = "window_level"
    TOOL_PAN = "pan"
    TOOL_STACKED = "stacked"
    # Measurement tool modes (dispatched to ToolController)
    TOOL_RULER = "ruler"
    TOOL_ANGLE = "angle"
    TOOL_TWO_LINE_ANGLE = "two_line_angle"
    TOOL_ROI_RECT = "roi_rect"
    TOOL_ROI_CIRCLE = "roi_circle"
    TOOL_ARROW = "arrow"
    TOOL_TEXT = "text"
    TOOL_ERASER = "eraser"
    _MEASUREMENT_TOOLS = frozenset({
        "ruler", "angle", "two_line_angle",
        "roi_rect", "roi_circle", "arrow", "text", "eraser",
    })
'''

assert '    MAX_ZOOM = 20.0\n\n    def __init__' in content, "anchor not found"
content = content.replace(
    '    MAX_ZOOM = 20.0\n\n    def __init__',
    '    MAX_ZOOM = 20.0\n' + TOOL_CONSTANTS + '\n    def __init__',
    1,
)

# ── Step 2: Expand __init__ — add extra state after _overlay_lines ────────

EXTRA_INIT = '''
        # View rotation / flip (needed by CoordinateResolver)
        self._rotation_angle: int = 0
        self._flip_h: bool = False
        self._flip_v: bool = False

        # Active tool mode (toolbar-selected)
        self._tool_mode: str = self.TOOL_NONE

        # Zoom-drag interaction state (left-button vertical drag when TOOL_ZOOM)
        self._zoom_dragging: bool = False
        self._zoom_start_pos: QPointF = QPointF()
        self._zoom_start_zoom: float = 1.0

        # Stacked-scroll interaction state (left-button vertical drag → slice scroll)
        self._stacked_dragging: bool = False
        self._stacked_last_y: float = 0.0
        self._stacked_accum: float = 0.0

        # Current displayed slice index (used by tool controller and coord resolver)
        self._current_slice_index: int = 0

        # Suppress tool annotation repaint during wheel scroll (perf)
        self._in_wheel_scroll: bool = False
        self._scroll_stop_timer = QTimer(self)
        self._scroll_stop_timer.setSingleShot(True)
        self._scroll_stop_timer.setInterval(200)
        self._scroll_stop_timer.timeout.connect(self._on_scroll_stopped)

        # Sync point mode (forwarded to parent VTKWidget for cross-viewer sync)
        self._sync_mode_active: bool = False

        # Measurement tool state
        self._tool_controller = None   # Optional[ToolController]
        self._coord_backend = None     # Optional backend for coord resolver'''

assert "        self._overlay_lines: list = []\n\n    # ── Public API" in content, "overlay_lines anchor not found"
content = content.replace(
    "        self._overlay_lines: list = []\n\n    # ── Public API",
    "        self._overlay_lines: list = []\n" + EXTRA_INIT + "\n\n    # ── Public API",
    1,
)

# ── Step 3: Add new public API after get_last_paint_ms ────────────────────

NEW_API = '''
    @property
    def tool_controller(self):
        return self._tool_controller

    @tool_controller.setter
    def tool_controller(self, ctrl):
        self._tool_controller = ctrl

    def set_tool_mode(self, mode: str) -> None:
        """Set the active tool mode (dispatches to ToolController)."""
        self._tool_mode = mode

    def get_tool_mode(self) -> str:
        return self._tool_mode

    def set_coord_backend(self, backend) -> None:
        """Set the backend used by CoordinateResolver for patient-space measurements."""
        self._coord_backend = backend

    def set_current_slice_index(self, idx: int) -> None:
        self._current_slice_index = idx

    def set_rotation(self, angle: int) -> None:
        self._rotation_angle = angle % 360
        self.update()

    def set_flip(self, flip_h: bool, flip_v: bool) -> None:
        self._flip_h = flip_h
        self._flip_v = flip_v
        self.update()

    def set_sync_mode(self, active: bool) -> None:
        self._sync_mode_active = active

'''

assert "        return self._last_paint_ms\n\n    # ── Qt Event Handlers" in content, "get_last_paint_ms anchor not found"
content = content.replace(
    "        return self._last_paint_ms\n\n    # ── Qt Event Handlers",
    "        return self._last_paint_ms\n" + NEW_API + "\n    # ── Qt Event Handlers",
    1,
)

# ── Step 4: Expand paintEvent to include tool annotations ─────────────────

assert "            if self._show_annotations:\n                self._paint_annotations(painter)\n\n        finally:" in content, "paintEvent anchor not found"
content = content.replace(
    "            if self._show_annotations:\n                self._paint_annotations(painter)\n\n        finally:",
    "            if self._show_annotations:\n                self._paint_annotations(painter)\n"
    "            if self._tool_controller is not None and not self._in_wheel_scroll:\n"
    "                self._paint_tool_annotations(painter)\n\n        finally:",
    1,
)

# ── Step 5: Replace mousePressEvent with full version ─────────────────────

OLD_PRESS = '''    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Right button: Window/Level adjustment
        if event.button() == Qt.MouseButton.RightButton:
            self._wl_dragging = True
            self._wl_start_pos = pos
            self._wl_start_window = self._current_window
            self._wl_start_level = self._current_level
            event.accept()
            return

        # Middle button or Ctrl+Left: Pan
        if event.button() == Qt.MouseButton.MiddleButton or (
            event.button() == Qt.MouseButton.LeftButton and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._pan_dragging = True
            self._pan_start_pos = pos
            self._pan_start_offset = QPointF(self._pan_offset)
            event.accept()
            return

        super().mousePressEvent(event)'''

NEW_PRESS = '''    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Right button: Window/Level adjustment (always)
        if event.button() == Qt.MouseButton.RightButton:
            self._wl_dragging = True
            self._wl_start_pos = pos
            self._wl_start_window = self._current_window
            self._wl_start_level = self._current_level
            event.accept()
            return

        # Middle button: Pan (always)
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_dragging = True
            self._pan_start_pos = pos
            self._pan_start_offset = QPointF(self._pan_offset)
            event.accept()
            return

        # Left button: behavior depends on tool mode
        if event.button() == Qt.MouseButton.LeftButton:
            # Sync point mode: forward to parent VTKWidget
            if self._sync_mode_active:
                p = self.parent()
                if p is not None:
                    p.mousePressEvent(event)
                return

            # Ctrl+Left always → pan
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                self._pan_dragging = True
                self._pan_start_pos = pos
                self._pan_start_offset = QPointF(self._pan_offset)
                event.accept()
                return

            if self._tool_mode == self.TOOL_ZOOM:
                self._zoom_dragging = True
                self._zoom_start_pos = pos
                self._zoom_start_zoom = self._zoom
                event.accept()
                return

            if self._tool_mode == self.TOOL_WINDOW_LEVEL:
                self._wl_dragging = True
                self._wl_start_pos = pos
                self._wl_start_window = self._current_window
                self._wl_start_level = self._current_level
                event.accept()
                return

            if self._tool_mode == self.TOOL_PAN:
                self._pan_dragging = True
                self._pan_start_pos = pos
                self._pan_start_offset = QPointF(self._pan_offset)
                event.accept()
                return

            if self._tool_mode == self.TOOL_STACKED:
                self._stacked_dragging = True
                self._stacked_last_y = pos.y()
                self._stacked_accum = 0.0
                event.accept()
                return

            # Measurement tools: route to ToolController
            if self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
                from modules.viewer.tools.coord_resolver import CoordinateResolver
                cr = CoordinateResolver(self, self._coord_backend)
                ix, iy = cr.widget_to_image(pos.x(), pos.y())
                if self._tool_controller.on_mouse_press(ix, iy, self._current_slice_index, cr):
                    self.update()
                    event.accept()
                    return

        super().mousePressEvent(event)'''

assert OLD_PRESS in content, "mousePressEvent anchor not found"
content = content.replace(OLD_PRESS, NEW_PRESS, 1)

# ── Step 6: Replace mouseMoveEvent with full version ─────────────────────

OLD_MOVE = '''    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Window/Level drag
        if self._wl_dragging:
            dx = pos.x() - self._wl_start_pos.x()
            dy = pos.y() - self._wl_start_pos.y()

            # Sensitivity scaled to image data range
            sensitivity = max(1.0, self._current_window / 500.0)
            new_window = max(1.0, self._wl_start_window + dx * sensitivity)
            new_level = self._wl_start_level - dy * sensitivity

            self._current_window = new_window
            self._current_level = new_level
            self.window_level_changed.emit(new_window, new_level)
            event.accept()
            return

        # Pan drag
        if self._pan_dragging:
            delta = pos - self._pan_start_pos
            self._pan_offset = self._pan_start_offset + delta
            self.update()
            event.accept()
            return

        # Track mouse position in image coords
        img_x, img_y = self.widget_to_image_coords(pos.x(), pos.y())
        self.mouse_moved.emit(img_x, img_y)

        super().mouseMoveEvent(event)'''

NEW_MOVE = '''    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()

        # Sync point mode: forward left-drag to parent VTKWidget
        if self._sync_mode_active and (event.buttons() & Qt.MouseButton.LeftButton):
            p = self.parent()
            if p is not None:
                p.mouseMoveEvent(event)
            return

        # Annotation drag — runs before all other left-button handlers
        if (
            self._tool_controller is not None
            and self._tool_controller.is_dragging
            and (event.buttons() & Qt.MouseButton.LeftButton)
        ):
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(pos.x(), pos.y())
            self._tool_controller.on_mouse_move(ix, iy, self._current_slice_index)
            self.update()
            event.accept()
            return

        # Window/Level drag
        if self._wl_dragging:
            dx = pos.x() - self._wl_start_pos.x()
            dy = pos.y() - self._wl_start_pos.y()
            sensitivity = max(1.0, self._current_window / 500.0)
            new_window = max(1.0, self._wl_start_window + dx * sensitivity)
            new_level = self._wl_start_level - dy * sensitivity
            self._current_window = new_window
            self._current_level = new_level
            self.window_level_changed.emit(new_window, new_level)
            event.accept()
            return

        # Pan drag
        if self._pan_dragging:
            delta = pos - self._pan_start_pos
            self._pan_offset = self._pan_start_offset + delta
            self.update()
            event.accept()
            return

        # Zoom drag
        if self._zoom_dragging:
            dy = pos.y() - self._zoom_start_pos.y()
            factor = 1.0 + (-dy) * 0.005
            new_zoom = max(self.MIN_ZOOM, min(self.MAX_ZOOM, self._zoom_start_zoom * factor))
            self._zoom = new_zoom
            self.zoom_changed.emit(self._zoom)
            self.update()
            event.accept()
            return

        # Stacked scroll drag (vertical movement → slice scroll)
        if self._stacked_dragging:
            dy = pos.y() - self._stacked_last_y
            self._stacked_last_y = pos.y()
            self._stacked_accum += dy
            while self._stacked_accum >= 10.0:
                self._stacked_accum -= 10.0
                self.slice_scroll_requested.emit(1)
            while self._stacked_accum <= -10.0:
                self._stacked_accum += 10.0
                self.slice_scroll_requested.emit(-1)
            event.accept()
            return

        # Measurement tool move: update preview
        if self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(pos.x(), pos.y())
            if self._tool_controller.on_mouse_move(ix, iy, self._current_slice_index):
                self.update()
                self.mouse_moved.emit(ix, iy)
                event.accept()
                return

        # Track mouse position in image coords
        img_x, img_y = self.widget_to_image_coords(pos.x(), pos.y())
        self.mouse_moved.emit(img_x, img_y)

        # Hover detection — update cursor when over annotations
        if self._tool_controller is not None and not self._wl_dragging and not self._pan_dragging:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(pos.x(), pos.y())
            threshold = 12.0 / max(self._zoom, 0.1)
            if self._tool_controller.on_hover(ix, iy, self._current_slice_index, threshold):
                self.update()
            cur_shape = self._tool_controller.get_hover_cursor_shape()
            if cur_shape == "move":
                self.setCursor(Qt.CursorShape.SizeAllCursor)
            elif cur_shape == "handle":
                self.setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.unsetCursor()

        super().mouseMoveEvent(event)'''

assert OLD_MOVE in content, "mouseMoveEvent anchor not found"
content = content.replace(OLD_MOVE, NEW_MOVE, 1)

# ── Step 7: Replace mouseReleaseEvent with full version ──────────────────

OLD_RELEASE = '''    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._wl_dragging:
            self._wl_dragging = False
            event.accept()
            return
        if (event.button() == Qt.MouseButton.MiddleButton or event.button() == Qt.MouseButton.LeftButton) and self._pan_dragging:
            self._pan_dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)'''

NEW_RELEASE = '''    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        # Sync point mode: forward left-release to parent VTKWidget
        if self._sync_mode_active and event.button() == Qt.MouseButton.LeftButton:
            p = self.parent()
            if p is not None:
                p.mouseReleaseEvent(event)
            return

        if event.button() == Qt.MouseButton.RightButton and self._wl_dragging:
            self._wl_dragging = False
            event.accept()
            return
        if (event.button() == Qt.MouseButton.MiddleButton or event.button() == Qt.MouseButton.LeftButton) and self._pan_dragging:
            self._pan_dragging = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._zoom_dragging:
            self._zoom_dragging = False
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._stacked_dragging:
            self._stacked_dragging = False
            event.accept()
            return
        # Finalize annotation drag
        if event.button() == Qt.MouseButton.LeftButton and self._tool_controller is not None and self._tool_controller.is_dragging:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(event.position().x(), event.position().y())
            self._tool_controller.on_mouse_release(ix, iy, self._current_slice_index)
            self.update()
            event.accept()
            return
        # Measurement tool release (end placement step)
        if event.button() == Qt.MouseButton.LeftButton and self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
            from modules.viewer.tools.coord_resolver import CoordinateResolver
            cr = CoordinateResolver(self, self._coord_backend)
            ix, iy = cr.widget_to_image(event.position().x(), event.position().y())
            if self._tool_controller.on_mouse_release(ix, iy, self._current_slice_index):
                self.update()
                event.accept()
                return
        super().mouseReleaseEvent(event)'''

assert OLD_RELEASE in content, "mouseReleaseEvent anchor not found"
content = content.replace(OLD_RELEASE, NEW_RELEASE, 1)

# ── Step 8: Modify wheelEvent to use scroll stop timer ───────────────────

assert "            # Slice scroll\n            slices_delta = -1 if delta > 0 else 1\n            self.slice_scroll_requested.emit(slices_delta)" in content, "wheelEvent anchor not found"
content = content.replace(
    "            # Slice scroll\n            slices_delta = -1 if delta > 0 else 1\n            self.slice_scroll_requested.emit(slices_delta)",
    "            # Slice scroll\n            self._in_wheel_scroll = True\n            self._scroll_stop_timer.start()\n            slices_delta = -1 if delta > 0 else 1\n            self.slice_scroll_requested.emit(slices_delta)",
    1,
)

# ── Step 9: Add new methods at end of file ────────────────────────────────

END_METHODS = '''
    def _on_scroll_stopped(self) -> None:
        """Called 200ms after last wheel event — re-enable tool annotations."""
        self._in_wheel_scroll = False
        self.update()

    def keyPressEvent(self, event) -> None:
        """Route Escape/Delete to ToolController when active."""
        if self._tool_controller is not None and self._tool_mode in self._MEASUREMENT_TOOLS:
            from PySide6.QtCore import Qt as QtCore_Qt
            key = event.key()
            key_str = None
            if key == QtCore_Qt.Key.Key_Escape:
                key_str = "Escape"
            elif key == QtCore_Qt.Key.Key_Delete:
                key_str = "Delete"
            if key_str and self._tool_controller.on_key_press(key_str):
                self.update()
                event.accept()
                return
        super().keyPressEvent(event)

    def _paint_tool_annotations(self, painter: QPainter) -> None:
        """Render measurement tool overlays via ToolController."""
        if self._tool_controller is None:
            return
        from modules.viewer.tools.coord_resolver import CoordinateResolver
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        cr = CoordinateResolver(self, self._coord_backend)
        self._tool_controller.render(painter, self._current_slice_index, cr)
        painter.restore()
'''

content = content.rstrip('\n') + '\n' + END_METHODS

# ── Write ─────────────────────────────────────────────────────────────────

with open(TARGET, 'w', encoding='utf-8') as f:
    f.write(content)

print("Done. Lines:", content.count('\n'))
print("Checking methods:")
for kw in ['_MEASUREMENT_TOOLS', 'is_dragging', '_on_scroll_stopped', 'keyPressEvent', '_paint_tool_annotations', 'set_tool_mode', 'on_hover']:
    found = kw in content
    print(f"  {kw}: {'OK' if found else 'MISSING'}")
