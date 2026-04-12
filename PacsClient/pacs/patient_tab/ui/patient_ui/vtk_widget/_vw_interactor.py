"""
Interactor style and sync-point mixin for VTKWidget.
set_new_interactorstyle, sync point methods, mouse event overrides.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QCursor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication
from modules.viewer.interactor_styles import AbstractInteractorStyle
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_globals import (
    _SYNC_MOVE_THROTTLE_MS,
)
import vtkmodules.all as vtk

logger = logging.getLogger(__name__)


class _QtBridgeStyle:
    """Functional interactor style bridge for Qt viewer mode.

    Routes toolbar tool commands (activate/deactivate/zoom_to_fit/rotate/flip)
    to the QtSliceViewer widget, which handles all rendering via QPainter.
    """
    widgets_by_slice: dict = {}
    slider = None

    _STYLE_TO_TOOL = None  # lazily built: maps interactor style class → ToolAccess constant

    def __init__(self, vtk_widget=None, requested_style_cls=None):
        self._vtk_widget = vtk_widget
        self._active_tool = None
        self._requested_style_cls = requested_style_cls

    @property
    def _qt_viewer(self):
        w = self._vtk_widget
        if w is None:
            return None
        return getattr(w, '_qt_viewer_widget', None)

    def _get_tool_access(self):
        try:
            from modules.viewer.interactor_styles.tools_object_manager import ToolAccess
            return ToolAccess
        except Exception:
            return None

    @classmethod
    def _build_style_map(cls):
        """Build lazy mapping from interactor style classes to ToolAccess constants."""
        try:
            from modules.viewer.interactor_styles import (
                RulerInteractorStyle, AngleInteractorStyle,
                TwoLineAngleInteractorStyle, ArrowInteractorStyle,
                TextInteractorStyle, EraserInteractorStyle,
                RoiInteractorStyle, CircleRoiInteractorStyle,
            )
            from modules.viewer.interactor_styles.tools_object_manager import ToolAccess as _TA
            cls._STYLE_TO_TOOL = {
                RulerInteractorStyle: _TA.RULER,
                AngleInteractorStyle: _TA.ANGLE,
                TwoLineAngleInteractorStyle: _TA.TWO_LINE_ANGLE,
                ArrowInteractorStyle: _TA.ARROW,
                TextInteractorStyle: _TA.TEXT,
                EraserInteractorStyle: _TA.ERASER,
                RoiInteractorStyle: _TA.ROI,
                CircleRoiInteractorStyle: _TA.CIRCLE_ROI,
            }
        except Exception:
            cls._STYLE_TO_TOOL = {}

    def activate(self, tool=None):
        ta = self._get_tool_access()
        qv = self._qt_viewer
        if qv is None:
            return

        # Auto-resolve tool from requested style class when toolbar calls activate() with no argument
        if tool is None and self._requested_style_cls is not None:
            if _QtBridgeStyle._STYLE_TO_TOOL is None:
                _QtBridgeStyle._build_style_map()
            tool = _QtBridgeStyle._STYLE_TO_TOOL.get(self._requested_style_cls)

        self._active_tool = tool

        # View-manipulation tools: set QtSliceViewer mouse mode
        if ta is not None:
            if tool == ta.ZOOM:
                qv.set_tool_mode(qv.TOOL_ZOOM)
            elif tool == ta.WINDOW_LEVEL:
                qv.set_tool_mode(qv.TOOL_WINDOW_LEVEL)
                # Mark that user explicitly chose W/L
                iv = getattr(self._vtk_widget, 'image_viewer', None)
                if iv is not None:
                    iv.flag_set_custom_window_level = True
            elif tool == ta.PAN:
                qv.set_tool_mode(qv.TOOL_PAN)
            elif tool == ta.STACKED:
                qv.set_tool_mode(qv.TOOL_STACKED)
            # One-shot transform tools
            elif tool == ta.ROTATION_LEFT:
                qv.rotate_left()
            elif tool == ta.ROTATION_RIGHT:
                qv.rotate_right()
            elif tool == ta.FLIP_HORIZONTAL:
                qv.flip_horizontal()
            elif tool == ta.FLIP_VERTICAL:
                qv.flip_vertical()
            elif tool == ta.CAPTURE:
                self._capture_qt()
            # Measurement tools: route to ToolController via QtSliceViewer
            elif tool in (ta.RULER, ta.ANGLE, ta.TWO_LINE_ANGLE,
                          ta.ARROW, ta.TEXT, ta.ROI, ta.CIRCLE_ROI, ta.ERASER):
                self._activate_measurement_tool(qv, tool, ta)
            else:
                # Unrecognised tool — clear mode
                qv.set_tool_mode(qv.TOOL_NONE)
        else:
            qv.set_tool_mode(qv.TOOL_NONE)

        self._apply_cursor_for_tool(qv, tool, ta)

    def _apply_cursor_for_tool(self, qv, tool, ta):
        """Set an appropriate cursor on the Qt viewer for the active tool."""
        from PySide6.QtCore import Qt as _Qt
        if ta is None or tool is None:
            qv.setCursor(_Qt.CursorShape.ArrowCursor)
            return
        _MEASUREMENT_SET = {ta.RULER, ta.ANGLE, ta.TWO_LINE_ANGLE, ta.ARROW, ta.TEXT, ta.ROI, ta.CIRCLE_ROI}
        if tool in _MEASUREMENT_SET:
            qv.setCursor(_Qt.CursorShape.CrossCursor)
        elif tool == ta.ERASER:
            qv.setCursor(_Qt.CursorShape.PointingHandCursor)
        elif tool == ta.PAN:
            qv.setCursor(_Qt.CursorShape.OpenHandCursor)
        elif tool == ta.ZOOM:
            qv.setCursor(_Qt.CursorShape.SizeBDiagCursor)
        elif tool == ta.WINDOW_LEVEL:
            qv.setCursor(_Qt.CursorShape.SizeVerCursor)
        else:
            qv.setCursor(_Qt.CursorShape.ArrowCursor)

    def deactivate(self, *a, **kw):
        qv = self._qt_viewer
        if qv is not None:
            qv.set_tool_mode(qv.TOOL_NONE)
            qv.setCursor(Qt.CursorShape.ArrowCursor)
            # Also deactivate ToolController if present
            if qv.tool_controller is not None:
                qv.tool_controller.deactivate()
        self._active_tool = None

    _TOOL_MODE_MAP = None  # lazily built

    def _activate_measurement_tool(self, qv, tool, ta):
        """Route a toolbar measurement tool to ToolController."""
        if self._TOOL_MODE_MAP is None:
            _QtBridgeStyle._TOOL_MODE_MAP = {
                ta.RULER: (qv.TOOL_RULER, "RULER"),
                ta.ANGLE: (qv.TOOL_ANGLE, "ANGLE"),
                ta.TWO_LINE_ANGLE: (qv.TOOL_TWO_LINE_ANGLE, "TWO_LINE_ANGLE"),
                ta.ARROW: (qv.TOOL_ARROW, "ARROW"),
                ta.TEXT: (qv.TOOL_TEXT, "TEXT"),
                ta.ROI: (qv.TOOL_ROI_RECT, "ROI_RECT"),
                ta.CIRCLE_ROI: (qv.TOOL_ROI_CIRCLE, "ROI_CIRCLE"),
                ta.ERASER: (qv.TOOL_ERASER, "ERASER"),
            }

        entry = self._TOOL_MODE_MAP.get(tool)
        if entry is None:
            qv.set_tool_mode(qv.TOOL_NONE)
            return

        mode_str, tool_type_name = entry
        qv.set_tool_mode(mode_str)

        # Activate ToolController if present
        ctrl = qv.tool_controller
        if ctrl is not None:
            try:
                from modules.viewer.tools.enums import ToolType
                tt = getattr(ToolType, tool_type_name, None)
                if tt is not None:
                    ctrl.activate(tt)
            except Exception:
                pass

    def zoom_to_fit(self):
        qv = self._qt_viewer
        if qv is not None:
            qv.zoom_to_fit()

    def On(self): pass
    def Off(self): pass
    def reset_events(self, *a, **kw):
        self.deactivate()

    def delete_all_widgets(self, *a, **kw): pass
    def check_status(self, *a, **kw): pass

    def _capture_qt(self):
        """Capture screenshot of the Qt viewer."""
        qv = self._qt_viewer
        if qv is None:
            return
        try:
            from PacsClient.pacs.patient_tab.utils import create_attachment_folder, create_random_string
            pixmap = qv.grab()
            iv = getattr(self._vtk_widget, 'image_viewer', None)
            study_uid = None
            if iv is not None and hasattr(iv, 'metadata_fixed') and iv.metadata_fixed:
                study_uid = iv.metadata_fixed.get('study_uid')
            if not study_uid:
                import random
                study_uid = str(random.randint(10000, 100000))
            folder_path = create_attachment_folder(study_uid)
            random_name = create_random_string()
            file_path = f'{folder_path}/{random_name}.png'
            pixmap.save(file_path, 'PNG')
            logger.info("Screenshot saved: %s", file_path)
        except Exception as e:
            logger.error("Failed to capture screenshot: %s", e)


class _VWInteractorMixin:
    """Interactor style management, sync-point mouse tracking."""
    """Auto-split mixin — see widget_viewer.py for history."""

    def _get_active_style(self):
        """Return the currently active interactor style if available."""
        style = getattr(self, "current_style", None)
        if style is None:
            try:
                style = self.interactor.GetInteractorStyle()
            except Exception:
                style = None
        return style

    def _force_release_pointer_states(
        self,
        clear_left: bool = False,
        clear_right: bool = False,
        clear_middle: bool = False,
        reason: str = "",
    ) -> None:
        """Qt-level fail-safe to keep style button flags consistent."""
        style = self._get_active_style()
        if style is None:
            return

        changed = False
        try:
            if clear_left and getattr(style, "left_button_down", False):
                style.left_button_down = False
                changed = True
            if clear_right and getattr(style, "right_button_down", False):
                style.right_button_down = False
                changed = True
            if clear_middle and getattr(style, "middle_button_down", False):
                style.middle_button_down = False
                changed = True
        except Exception:
            return

        if not changed:
            return

        try:
            any_down = bool(
                getattr(style, "left_button_down", False)
                or getattr(style, "right_button_down", False)
                or getattr(style, "middle_button_down", False)
            )
            if not any_down:
                try:
                    style.last_pos = None
                except Exception:
                    pass
                try:
                    if getattr(style, "pan_active", False):
                        style.turn_off_pan()
                except Exception:
                    try:
                        style.pan_active = False
                    except Exception:
                        pass
        except Exception:
            pass

        # If stack interaction was pending, ensure it cannot remain armed forever.
        try:
            if (
                getattr(self, "_pending_scroll_source", None) == "stack_drag"
                and self._pending_wheel_slice is None
            ):
                self._in_stack_scroll = False
                self._in_fast_slice_interaction = bool(self._in_wheel_scroll or self._in_stack_scroll)
        except Exception:
            pass

        logger.debug(
            "[pointer-failsafe] released states reason=%s left=%s right=%s middle=%s",
            str(reason),
            bool(getattr(style, "left_button_down", False)),
            bool(getattr(style, "right_button_down", False)),
            bool(getattr(style, "middle_button_down", False)),
        )

    def mousePressEvent(self, event):
        # Qt bridge mode: handle sync point via Qt mouse events
        if self._qt_bridge_active:
            if (self._sync_enabled and self.image_viewer is not None
                    and event.button() == Qt.MouseButton.LeftButton):
                pos = event.position()
                world_pos = self.image_viewer.pick_world_point(pos.x(), pos.y())
                if world_pos is not None:
                    self._sync_dragging = True
                    self._apply_sync_point(world_pos)
                    event.accept()
                    return
            # Forward to QtSliceViewer for W/L, pan, etc.
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Qt bridge mode: don't route to VTK (would trigger OpenGL render)
        if self._qt_bridge_active:
            if self._sync_enabled and self._sync_dragging and self.image_viewer is not None:
                now = time.time() * 1000.0
                if (now - self._sync_last_move_time) >= _SYNC_MOVE_THROTTLE_MS:
                    self._sync_last_move_time = now
                    pos = event.position()
                    world_pos = self.image_viewer.pick_world_point(pos.x(), pos.y())
                    if world_pos is not None:
                        self._apply_sync_point(world_pos)
            event.accept()
            return
        # If Qt reports no button pressed but style still thinks a button is down,
        # force-release stale states (can happen after UI stalls).
        try:
            if int(event.buttons()) == int(Qt.MouseButton.NoButton):
                self._force_release_pointer_states(
                    clear_left=True,
                    clear_right=True,
                    clear_middle=True,
                    reason="mouse_move_no_buttons",
                )
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # Qt bridge mode: don't route to VTK (would trigger OpenGL render)
        if self._qt_bridge_active:
            if self._sync_enabled and event.button() == Qt.MouseButton.LeftButton:
                self._sync_dragging = False
            event.accept()
            return
        super().mouseReleaseEvent(event)
        try:
            btn = int(event.button())
            no_buttons = int(event.buttons()) == int(Qt.MouseButton.NoButton)
            self._force_release_pointer_states(
                clear_left=bool(btn == int(Qt.MouseButton.LeftButton) or no_buttons),
                clear_right=bool(btn == int(Qt.MouseButton.RightButton) or no_buttons),
                clear_middle=bool(btn == int(Qt.MouseButton.MiddleButton) or no_buttons),
                reason="mouse_release",
            )
        except Exception:
            pass

    def leaveEvent(self, event):
        try:
            self._force_release_pointer_states(
                clear_left=True,
                clear_right=True,
                clear_middle=True,
                reason="leave_event",
            )
        except Exception:
            pass
        if self._qt_bridge_active:
            return
        super().leaveEvent(event)

    def set_new_interactorstyle(self, style):
        # Qt bridge mode: route tool commands to Qt viewer
        if self._qt_bridge_active:
            if self.image_viewer is None:
                # Bridge not fully ready yet — store for replay after _start_qt_viewer completes
                self._pending_tool_style_cls = style
                logger.debug("[interactor] Qt bridge pending, stored tool: %s", style.__name__ if hasattr(style, '__name__') else style)
                return
            logger.debug("[interactor] VTK tool %s → Qt bridge", style.__name__ if hasattr(style, '__name__') else style)
            self.current_style = _QtBridgeStyle(vtk_widget=self, requested_style_cls=style)
            self.current_style.activate()
            return

        # VTK mode: image_viewer must be initialized
        if self.image_viewer is None:
            logger.debug("Cannot set interactor style - viewer not yet initialized")
            return

        self._freeze_render_window()
        _saved_camera_state = self._capture_camera_state()
        try:
            if _saved_camera_state is not None and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(_saved_camera_state, duration_ms=350)
        except Exception:
            pass

        interactorstyle: AbstractInteractorStyle = style(self.image_viewer)

        # load widgets on new interactor style
        interactorstyle = self.set_widgets_on_new_interactorstyle(interactorstyle)

        # replace new interactor style
        self.interactor.SetInteractorStyle(interactorstyle)
        interactorstyle.signal_emitter.interactionOccurred.connect(self.change_container_border)

        self.current_style = interactorstyle

        self._restore_camera_state(_saved_camera_state)
        self._schedule_camera_restore(_saved_camera_state)

        self.image_viewer.Render()

    def restore_default_interactorstyle(self):
        if self.image_viewer is None:
            return
        if self._qt_bridge_active:
            self.current_style = _QtBridgeStyle(vtk_widget=self)
            # Reset tool mode on the Qt viewer
            qv = getattr(self, '_qt_viewer_widget', None)
            if qv is not None:
                qv.set_tool_mode(qv.TOOL_NONE)
            return

        self._freeze_render_window()
        _saved_camera_state = self._capture_camera_state()
        try:
            if _saved_camera_state is not None and hasattr(self.image_viewer, "lock_camera_state"):
                self.image_viewer.lock_camera_state(_saved_camera_state, duration_ms=350)
        except Exception:
            pass
            
        default_interactorstyle = self.style

        # load widgets on new interactor style
        default_interactorstyle = self.set_widgets_on_new_interactorstyle(default_interactorstyle)

        self.interactor.SetInteractorStyle(default_interactorstyle)
        self.current_style = default_interactorstyle
        self.current_style.reset_events()  # reset events to default events
        self._ensure_interactor_style_enabled()

        self._restore_camera_state(_saved_camera_state)
        self._schedule_camera_restore(_saved_camera_state)
        self.image_viewer.Render()

    def _ensure_interactor_style_enabled(self):
        try:
            if getattr(self, 'current_style', None) is not None and hasattr(self.current_style, 'On'):
                self.current_style.On()
        except Exception:
            pass

    def set_widgets_on_new_interactorstyle(self, new_interactorstyle: AbstractInteractorStyle):
        # Check if current_style exists (for progressive download dummy viewers)
        if self.current_style is not None and hasattr(self.current_style, 'widgets_by_slice'):
            for slice_index in self.current_style.widgets_by_slice.keys():
                new_interactorstyle.widgets_by_slice[slice_index] = self.current_style.widgets_by_slice[slice_index]

            # set slider form before interactorstyle
            if hasattr(self.current_style, 'slider'):
                new_interactorstyle.set_slider_from_ui(self.current_style.slider)
            elif hasattr(self, 'slider') and self.slider is not None:
                new_interactorstyle.set_slider_from_ui(self.slider)
        
        return new_interactorstyle

    def get_sync_viewer_id(self):
        if self._sync_viewer_id:
            return self._sync_viewer_id
        if self.id_vtk_widget is not None:
            return f"viewer_{self.id_vtk_widget}"
        return f"viewer_{id(self)}"

    def enable_sync_point(self, sync_manager, viewer_id=None):
        if self.image_viewer is None:
            return

        self._sync_manager = sync_manager
        self._sync_viewer_id = viewer_id or self.get_sync_viewer_id()
        self._sync_enabled = True
        logger.info(
            "[SYNC-ENABLE] viewer=%s  backend=%s",
            self._sync_viewer_id,
            "Qt-bridge" if self._qt_bridge_active else "VTK-interactor",
        )

        # Qt bridge mode: use Qt mouse events instead of VTK observers
        if self._qt_bridge_active:
            self._set_target_cursor(True)
            qv = getattr(self, '_qt_viewer_widget', None)
            if qv is not None:
                qv._sync_mode_active = True
            return

        if self._sync_prev_style is None:
            self._sync_prev_style = self.interactor.GetInteractorStyle()

        if self._sync_style is None:
            self._sync_style = self._create_sync_interactor_style()

        self.interactor.SetInteractorStyle(self._sync_style)
        self._set_target_cursor(True)

        if self._sync_observer_ids:
            return

        self._sync_observer_ids.append(
            self.interactor.AddObserver('LeftButtonPressEvent', self._on_sync_left_press)
        )
        self._sync_observer_ids.append(
            self.interactor.AddObserver('MouseMoveEvent', self._on_sync_mouse_move)
        )
        self._sync_observer_ids.append(
            self.interactor.AddObserver('LeftButtonReleaseEvent', self._on_sync_left_release)
        )

    def disable_sync_point(self):
        self._sync_enabled = False
        self._sync_dragging = False

        # Qt bridge mode: just clean up cursor and overlays
        if self._qt_bridge_active:
            if self.image_viewer is not None:
                self.image_viewer.hide_sync_point()
            self._set_target_cursor(False)
            self._sync_manager = None
            qv = getattr(self, '_qt_viewer_widget', None)
            if qv is not None:
                qv._sync_mode_active = False
            return

        for obs_id in self._sync_observer_ids:
            try:
                self.interactor.RemoveObserver(obs_id)
            except Exception:
                pass
        self._sync_observer_ids = []

        if self.image_viewer is not None:
            self.image_viewer.hide_sync_point()

        self._set_target_cursor(False)

        if self._sync_prev_style is not None:
            try:
                self.interactor.SetInteractorStyle(self._sync_prev_style)
            except Exception:
                pass
            self._sync_prev_style = None

        self._sync_manager = None

    def _set_target_cursor(self, enabled: bool):
        try:
            if not enabled:
                self.unsetCursor()
                return

            if self._target_cursor is None:
                size = 16
                pixmap = QPixmap(size, size)
                pixmap.fill(Qt.transparent)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setBrush(QColor(220, 38, 38))
                painter.setPen(QColor(220, 38, 38))
                radius = 4
                center = size // 2
                painter.drawEllipse(center - radius, center - radius, radius * 2, radius * 2)
                painter.end()
                self._target_cursor = QCursor(pixmap, center, center)

            self.setCursor(self._target_cursor)
        except Exception:
            pass

    def _create_sync_interactor_style(self):
        widget = self

        class SyncPointInteractorStyle(vtk.vtkInteractorStyleUser):
            def OnLeftButtonDown(self):
                widget._on_sync_left_press(self, None)

            def OnMouseMove(self):
                widget._on_sync_mouse_move(self, None)

            def OnLeftButtonUp(self):
                widget._on_sync_left_release(self, None)

        style = SyncPointInteractorStyle()
        try:
            style.SetInteractor(self.interactor)
        except Exception:
            pass
        return style

    def _on_sync_left_press(self, obj, event):
        if not self._sync_enabled or self.image_viewer is None:
            return

        display_x, display_y = self.interactor.GetEventPosition()
        world_pos = self.image_viewer.pick_world_point(display_x, display_y)
        if world_pos is None:
            return

        self._sync_dragging = True
        self._apply_sync_point(world_pos)
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _on_sync_mouse_move(self, obj, event):
        if not self._sync_enabled or not self._sync_dragging or self.image_viewer is None:
            return

        # Throttle: skip if too soon since last processing
        now = time.time() * 1000.0
        if (now - self._sync_last_move_time) < _SYNC_MOVE_THROTTLE_MS:
            return
        self._sync_last_move_time = now

        display_x, display_y = self.interactor.GetEventPosition()
        world_pos = self.image_viewer.pick_world_point(display_x, display_y)
        if world_pos is None:
            return

        self._apply_sync_point(world_pos)
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _on_sync_left_release(self, obj, event):
        if not self._sync_enabled:
            return
        self._sync_dragging = False
        try:
            self.interactor.SetAbortFlag(1)
        except Exception:
            pass

    def _apply_sync_point(self, world_pos):
        if self.image_viewer is None:
            return

        orient = self.image_viewer.GetSliceOrientation()
        cur_slice = self.image_viewer.GetSlice()
        logger.info(
            "[SYNC-SOURCE] viewer=%s  orient=%d  slice=%d  world_pos=(%.4f, %.4f, %.4f)",
            self._sync_viewer_id, orient, cur_slice,
            world_pos[0], world_pos[1], world_pos[2],
        )

        self.image_viewer.set_sync_point(world_pos, adjust_slice=False)

        if self._sync_manager is not None:
            self._sync_manager.set_active_point(world_pos)
            self._sync_manager.notify_cursor_moved(self._sync_viewer_id, world_pos)

    def apply_sync_point_from_manager(self, world_pos, adjust_slice=True):
        if self.image_viewer is None:
            return
        self.image_viewer.set_sync_point(world_pos, adjust_slice=adjust_slice)
