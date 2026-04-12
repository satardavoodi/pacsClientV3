"""
Standalone VTK interactor style classes for Zeta MPR.

These are NOT mixins — they are independent VTK interactor-style subclasses
that reference the MPR viewer through ``self.parent``.

Classes
-------
MPRToolbarInteractorStyle
    Routes 2-D toolbar tools (zoom, W/L, pan, stack, eraser) into MPR views.
VRTInteractorStyle
    Handles mouse interaction for the 3-D VRT viewport (rotate, pan, zoom,
    RMB‑drag appearance, RMB‑click preset menu).
"""

import logging
import vtkmodules.all as vtk

from modules.viewer.interactor_styles.tools_object_manager import ToolAccess

logger = logging.getLogger(__name__)


class MPRToolbarInteractorStyle(vtk.vtkInteractorStyleImage):
    """
    Interactor style for Zeta MPR that mirrors the 2D toolbar behaviors
    (zoom, window/level, pan, stack) using left-drag.
    """
    def __init__(self, mpr_viewer, view_name):
        super().__init__()
        self.parent = mpr_viewer
        self.view_name = view_name
        self.tool_access = ToolAccess()
        self.active_tool = None
        self.left_button_down = False
        self.pan_active = False
        self.last_pos = None

        self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)
        self.AddObserver("LeftButtonReleaseEvent", self.on_left_button_release)
        self.AddObserver("MouseMoveEvent", self.on_mouse_move)
        self.AddObserver("MouseWheelForwardEvent", self.on_mouse_wheel_forward)
        self.AddObserver("MouseWheelBackwardEvent", self.on_mouse_wheel_backward)

    def set_active_tool(self, tool_name):
        # Reset transient states when tool changes
        if self.pan_active:
            try:
                super().OnMiddleButtonUp()
            except Exception:
                pass
        self.pan_active = False
        self.left_button_down = False
        self.last_pos = None
        self.active_tool = tool_name

    def _get_axis_index(self):
        if self.view_name == 'axial':
            return 2
        if self.view_name == 'sagittal':
            return 0
        return 1  # coronal

    def _get_basic_slice_change(self, max_slice):
        if max_slice <= 25:
            return 10
        if max_slice <= 50:
            return 8
        if max_slice <= 75:
            return 7
        return 5

    def _move_along_stack(self, delta_mm):
        scroll_dir = self.parent._get_scroll_direction(self.view_name)
        self.parent.current_position[0] += scroll_dir[0] * delta_mm
        self.parent.current_position[1] += scroll_dir[1] * delta_mm
        self.parent.current_position[2] += scroll_dir[2] * delta_mm

        self.parent._clamp_current_position()
        self.parent._update_all_crosshairs()
        self.parent._update_slice_positions()
        self.parent._synchronize_oblique_views()
        self.parent._update_slice_info_texts()
        self.parent._update_coordinates_label()
        self.parent._render_immediately(self.view_name)

    def on_left_button_press(self, obj, event):
        self.parent._set_active_view(self.view_name)
        if self.active_tool == self.tool_access.ERASER:
            self.parent.delete_measurement_at(self.view_name, self.GetInteractor().GetEventPosition())
            return

        self.left_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()

        if self.active_tool == self.tool_access.PAN:
            self.pan_active = True
            super().OnMiddleButtonDown()

    def on_left_button_release(self, obj, event):
        self.left_button_down = False
        self.last_pos = None

        if self.pan_active:
            self.pan_active = False
            try:
                super().OnMiddleButtonUp()
            except Exception:
                pass

    def on_mouse_move(self, obj, event):
        if not self.left_button_down or self.last_pos is None:
            return

        if self.active_tool == self.tool_access.ZOOM:
            self._change_zoom()
        elif self.active_tool == self.tool_access.WINDOW_LEVEL:
            self._change_window_level()
        elif self.active_tool == self.tool_access.PAN:
            if self.pan_active:
                super().OnMouseMove()
        elif self.active_tool == self.tool_access.STACKED:
            self._change_stack()

    def on_mouse_wheel_forward(self, obj, event):
        # Keep wheel scrolling consistent with crosshair style
        self.parent._set_active_view(self.view_name)
        self._move_along_stack(delta_mm=2.0)

    def on_mouse_wheel_backward(self, obj, event):
        self.parent._set_active_view(self.view_name)
        self._move_along_stack(delta_mm=-2.0)

    def _change_zoom(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        renderer = self.parent.viewers[self.view_name]['renderer']
        camera = renderer.GetActiveCamera()

        zoom_factor = 1.0
        zoom_sensitivity = 0.005

        if dy > 0:
            zoom_factor = 1 + abs(dy) * zoom_sensitivity
        elif dy < 0:
            zoom_factor = 1 / (1 + abs(dy) * zoom_sensitivity)

        camera.Zoom(zoom_factor)
        self.parent._request_render(self.view_name)
        self.last_pos = current_pos

    def _change_window_level(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dx = current_pos[0] - self.last_pos[0]
        dy = current_pos[1] - self.last_pos[1]

        actor = self.parent.viewers[self.view_name]['actor']
        window = actor.GetProperty().GetColorWindow()
        level = actor.GetProperty().GetColorLevel()

        dy = -dy  # invert dy for window width
        new_window_center = level + (dy * 1.3)
        new_window_width = window + (dx * 1.5)

        self.parent._apply_window_level(new_window_width, new_window_center)
        self.last_pos = current_pos

    def _change_stack(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        axis_index = self._get_axis_index()
        max_slice = self.parent.dims[axis_index]
        if max_slice <= 1:
            return

        basic_slice_change = self._get_basic_slice_change(max_slice)
        if abs(dy) < basic_slice_change:
            return

        step_slices = round(dy / basic_slice_change)
        if step_slices == 0:
            return

        # Match 2D behavior: dragging down goes "backward"
        spacing_mm = self.parent.spacing[axis_index]
        delta_mm = -step_slices * spacing_mm
        self._move_along_stack(delta_mm)
        self.last_pos = current_pos


class VRTInteractorStyle(vtk.vtkInteractorStyleTrackballCamera):
    """
    Custom interactor style for VRT (3D) viewport.
    LMB drag = rotate
    RMB click (no drag) = preset context menu
    RMB drag = adjust brightness/contrast (appearance)
    LMB + RMB drag = pan
    MMB drag = dolly (zoom)
    Mouse wheel = zoom in/out
    """
    def __init__(self, mpr_viewer, vtk_widget):
        super().__init__()
        self.parent = mpr_viewer
        self.widget = vtk_widget
        self.lmb_down = False
        self.rmb_down = False
        self.mmb_down = False
        self.pan_active = False
        self.rmb_dragging = False
        self.rmb_start_pos = None
        self.drag_threshold = 6

    def reset_interaction_state(self):
        self.lmb_down = False
        self.rmb_down = False
        self.mmb_down = False
        self.pan_active = False
        self.rmb_dragging = False
        self.rmb_start_pos = None
        try:
            state = self.GetState()
            if state == self.VTKIS_ROTATE:
                self.EndRotate()
            elif state == self.VTKIS_PAN:
                self.EndPan()
            elif state == self.VTKIS_DOLLY:
                self.EndDolly()
        except Exception:
            pass

    def _start_pan(self):
        if self.pan_active:
            return
        self.pan_active = True
        self.rmb_dragging = True
        try:
            if self.GetState() == self.VTKIS_ROTATE:
                self.EndRotate()
        except Exception:
            pass
        self.StartPan()

    def _end_pan(self):
        if not self.pan_active:
            return
        self.pan_active = False
        self.EndPan()

    def OnLeftButtonDown(self):
        self.parent._set_active_view('3d')
        self.lmb_down = True
        if self.rmb_down:
            self._start_pan()
            return
        super().OnLeftButtonDown()

    def OnLeftButtonUp(self):
        self.lmb_down = False
        if self.pan_active and self.rmb_down:
            self._end_pan()
            # After pan, remain ready for RMB drag
            self.rmb_start_pos = self.GetInteractor().GetEventPosition()
            self.rmb_dragging = False
            return
        if self.pan_active:
            self._end_pan()
            return
        super().OnLeftButtonUp()

    def OnRightButtonDown(self):
        self.parent._set_active_view('3d')
        self.rmb_down = True
        self.rmb_dragging = False
        self.rmb_start_pos = self.GetInteractor().GetEventPosition()
        self.parent._capture_vrt_baseline()

        if self.lmb_down:
            self._start_pan()
        # Do not call super - we fully override RMB

    def OnRightButtonUp(self):
        if self.pan_active:
            self._end_pan()
            if self.lmb_down:
                self.StartRotate()

        if not self.rmb_dragging and not self.pan_active and not self.lmb_down:
            self.parent._show_vrt_preset_menu_from_interactor(self.widget)

        self.rmb_down = False
        self.rmb_dragging = False
        self.rmb_start_pos = None
        self.parent._reset_vrt_rmb_state()

    def OnMiddleButtonDown(self):
        self.parent._set_active_view('3d')
        self.mmb_down = True
        self.StartDolly()

    def OnMiddleButtonUp(self):
        self.mmb_down = False
        self.EndDolly()

    def OnMouseWheelForward(self):
        """Mouse wheel scroll up → zoom in."""
        self.parent._set_active_view('3d')
        camera = self.GetCurrentRenderer().GetActiveCamera() if self.GetCurrentRenderer() else None
        if camera:
            camera.Dolly(1.1)
            if self.GetCurrentRenderer():
                self.GetCurrentRenderer().ResetCameraClippingRange()
                self.GetCurrentRenderer().GetRenderWindow().Render()

    def OnMouseWheelBackward(self):
        """Mouse wheel scroll down → zoom out."""
        self.parent._set_active_view('3d')
        camera = self.GetCurrentRenderer().GetActiveCamera() if self.GetCurrentRenderer() else None
        if camera:
            camera.Dolly(0.9)
            if self.GetCurrentRenderer():
                self.GetCurrentRenderer().ResetCameraClippingRange()
                self.GetCurrentRenderer().GetRenderWindow().Render()

    def OnMouseMove(self):
        if self.pan_active:
            super().OnMouseMove()
            return

        if self.mmb_down:
            super().OnMouseMove()
            return

        if self.rmb_down and not self.pan_active:
            if self.rmb_start_pos is None:
                self.rmb_start_pos = self.GetInteractor().GetEventPosition()
                return
            pos = self.GetInteractor().GetEventPosition()
            dx = pos[0] - self.rmb_start_pos[0]
            dy = pos[1] - self.rmb_start_pos[1]
            if not self.rmb_dragging:
                if abs(dx) >= self.drag_threshold or abs(dy) >= self.drag_threshold:
                    self.rmb_dragging = True
            if self.rmb_dragging:
                self.parent._apply_vrt_appearance_delta(dx, dy)
            return

        if self.lmb_down:
            super().OnMouseMove()
            return

        super().OnMouseMove()
