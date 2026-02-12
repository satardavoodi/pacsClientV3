import numpy as np
import vtkmodules.all as vtk
from vtkmodules.all import vtkInteractorStyleImage
from PySide6.QtCore import QObject, Signal
from .tools_object_manager import ToolAccess
from PacsClient.pacs.patient_tab.viewers.viewer_2d import ImageViewer2D
from .tools_object_manager import ToolObjectAbstract

class InteractionSignal(QObject):
    interactionOccurred = Signal()


class AbstractInteractorStyle(vtkInteractorStyleImage):

    def __init__(self, image_viewer: ImageViewer2D):
        super(AbstractInteractorStyle, self).__init__()
        self.image_viewer: ImageViewer2D = image_viewer
        self.signal_emitter: InteractionSignal = InteractionSignal()  # signal for interaction

        # left click
        self.AddObserver("LeftButtonPressEvent", self.on_left_button_press)
        self.AddObserver("LeftButtonReleaseEvent", self.on_left_button_release)

        # right click
        self.AddObserver("RightButtonPressEvent", self.on_right_button_press)
        self.AddObserver("RightButtonReleaseEvent", self.on_right_button_release)

        # middle mouse click
        self.AddObserver("MiddleButtonPressEvent", self.on_middle_button_press)
        self.AddObserver("MiddleButtonReleaseEvent", self.on_middle_button_release)

        # moving mouse
        self.AddObserver("MouseMoveEvent", self.on_mouse_move)

        self.left_button_down = False
        self.right_button_down = False
        self.middle_button_down = False
        self.pan_active = False
        self.last_pos = None
        self.slider = None
        self.tool_access = ToolAccess()
        self.color = (1, 0, 1)
        self.interactor_name = self.tool_access.ABSTRACT
        
        # Use shared widgets storage from image_viewer if available (for Curved MPR)
        # Otherwise create local storage (for regular viewers)
        if hasattr(image_viewer, 'widgets_by_slice'):
            # Curved MPR: use shared storage that persists across style changes
            self.widgets_by_slice = image_viewer.widgets_by_slice
        else:
            # Regular viewer: use local storage
            self.widgets_by_slice = {}

        # ── Drag-to-move annotation state ──
        self._dragging_obj = None
        self._drag_type = None       # e.g. 'ruler', 'arrow', 'angle', ...
        self._drag_start_world = None
        self._drag_start_data = None  # type-specific snapshot of positions
        self._hover_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1
        self.arrow_head_size_px = 42
        self.arrow_head_width_ratio = 0.45


    def reset_events(self):
        self.left_button_down = False
        self.right_button_down = False
        self.middle_button_down = False
        self.pan_active = False
        self.last_pos = None

    def _set_cursor(self, cursor_type):
        """Set the VTK cursor type."""
        try:
            if hasattr(self.image_viewer, 'image_interactor'):
                interactor = self.image_viewer.image_interactor
                if hasattr(interactor, 'SetCursor'):
                    interactor.SetCursor(cursor_type)
        except Exception:
            pass

    def update_slice(self):
        """
        Update the visibility of measurements when the slice changes.
        """
        current_slice = self.image_viewer.GetSlice()
        total_widgets = sum(len(w) for w in self.widgets_by_slice.values())
        
        if total_widgets > 0:
            # Only log if there are widgets to manage
            visible_count = len(self.widgets_by_slice.get(current_slice, set()))
            hidden_count = total_widgets - visible_count
            print(f"[WIDGET VISIBILITY] Slice {current_slice}: Showing {visible_count}, Hiding {hidden_count}")

        # Show/hide widgets based on slice
        for slice, widgets in self.widgets_by_slice.items():
            if slice == current_slice:
                for widget in widgets:
                    widget.On()
            else:
                for widget in widgets:
                    widget.Off()

        # Render to update the display
        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.renderer.Render()

    def delete_widget(self, obj: ToolObjectAbstract, selected_slice: int):
        if obj:
            obj.delete_widget(self.image_viewer)
            self.widgets_by_slice[selected_slice].remove(obj)
            self.image_viewer.Render()
            del obj

    def delete_all_widgets(self):
        for slice in self.widgets_by_slice.keys():
            while True:
                try:
                    widget = next(iter(self.widgets_by_slice[slice]))
                    self.delete_widget(widget, slice)

                except Exception as e:
                    break  # all widgets on slice deleted and don't have any widget on slice
        self.image_viewer.update_corners_actors(update_just_zoom=True)

    def emit_interaction(self):
        self.signal_emitter.interactionOccurred.emit()

    def on_left_button_press(self, obj, event):
        mouse_pos = self.GetInteractor().GetEventPosition()

        # ── Check if the click is on an existing annotation (drag start) ──
        drag_result = self._find_any_drag_target(mouse_pos)
        if drag_result is not None:
            drag_obj, drag_type, start_data = drag_result
            self._dragging_obj = drag_obj
            self._drag_type = drag_type
            self._drag_start_data = start_data
            self._drag_start_world = self.display_to_world(mouse_pos[0], mouse_pos[1])
            self._set_cursor(vtk.VTK_CURSOR_HAND)
            self.emit_interaction()
            return

        self.left_button_down = True
        self.last_pos = mouse_pos
        self.check_left_right_pan_start()
        self.emit_interaction()  # send signal for interaction

    def on_left_button_release(self, obj, event):
        # ── Finish active drag ──
        if self._dragging_obj is not None:
            # For TWO_LINE_ANGLE: persist the new positions into obj.points
            if self._drag_type == self.tool_access.TWO_LINE_ANGLE:
                try:
                    line1_w, line2_w, _ta, _pa = self._dragging_obj.get_widget()
                    p1 = [0, 0, 0]; p2 = [0, 0, 0]; p3 = [0, 0, 0]; p4 = [0, 0, 0]
                    if line1_w:
                        r1 = line1_w.GetDistanceRepresentation()
                        r1.GetPoint1WorldPosition(p1)
                        r1.GetPoint2WorldPosition(p2)
                    if line2_w:
                        r2 = line2_w.GetDistanceRepresentation()
                        r2.GetPoint1WorldPosition(p3)
                        r2.GetPoint2WorldPosition(p4)
                    self._dragging_obj.points = [list(p1), list(p2), list(p3), list(p4)]
                except Exception:
                    pass

            self._dragging_obj = None
            self._drag_type = None
            self._drag_start_world = None
            self._drag_start_data = None
            self._set_cursor(vtk.VTK_CURSOR_ARROW)
            return

        self.left_button_down = False
        self.last_pos = None
        self.check_left_right_pan_end()
        # self.emit_interaction()  # send signal for interaction

    ###################################################################

    def on_right_button_press(self, obj, event):
        self.image_viewer.flag_set_custom_window_level = True  # default window width/center are inactive.

        self.right_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()
        self.check_left_right_pan_start()
        self.emit_interaction()  # send signal for interaction

    def on_right_button_release(self, obj, event):
        self.right_button_down = False
        self.last_pos = None
        self.check_left_right_pan_end()
        # self.emit_interaction()  # send signal for interaction

    ###################################################################
    def on_middle_button_press(self, obj, event):
        self.middle_button_down = True
        self.last_pos = self.GetInteractor().GetEventPosition()
        self.emit_interaction()  # send signal for interaction

    def on_middle_button_release(self, obj, event):
        self.middle_button_down = False
        self.last_pos = None
        # self.emit_interaction()  # send signal for interaction

    ####################################################################
    def on_mouse_move(self, obj, event):
        # ── Active drag: move annotation ──
        if self._dragging_obj is not None and self._drag_start_data is not None:
            current_pos = self.GetInteractor().GetEventPosition()
            current_world = self.display_to_world(current_pos[0], current_pos[1])
            if current_world is not None and self._drag_start_world is not None:
                dx = current_world[0] - self._drag_start_world[0]
                dy = current_world[1] - self._drag_start_world[1]
                dz = current_world[2] - self._drag_start_world[2]
                self._apply_drag_delta(dx, dy, dz)
            return True

        if self.pan_active:  # if left and right click pressed
            super().OnMouseMove()
            # self.emit_interaction()  # send signal for interaction
            return True

        elif self.left_button_down:
            try:
                self.change_quickly_slices()
                # self.emit_interaction()  # send signal for interaction
                return True
            except:
                return False


        elif self.right_button_down:  # if right-click hold: change window level
            self.change_window_level()
            # self.emit_interaction()  # send signal for interaction
            return True

        elif self.middle_button_down:  # if middle button hold: zoom in/out
            self.change_zoom()
            # self.emit_interaction()  # send signal for interaction
            return True

        # ── Hover cursor: show hand when over a draggable annotation ──
        mouse_pos = self.GetInteractor().GetEventPosition()
        hover_result = self._find_any_drag_target(mouse_pos)
        if hover_result is not None:
            if self._hover_obj != hover_result[0]:
                self._hover_obj = hover_result[0]
                self._set_cursor(vtk.VTK_CURSOR_HAND)
        else:
            if self._hover_obj is not None:
                self._hover_obj = None
                self._set_cursor(vtk.VTK_CURSOR_ARROW)

        # no option chosen
        return False

    def check_left_right_pan_start(self):
        if self.left_button_down and self.right_button_down:
            # start pan
            self.turn_on_pan()

    def turn_on_pan(self):
        self.pan_active = True
        super().OnMiddleButtonDown()

    def check_left_right_pan_end(self):
        # release pan
        if self.pan_active:
            self.left_button_down = False
            self.right_button_down = False
            self.turn_off_pan()

    def turn_off_pan(self):
        self.pan_active = False
        super().OnMiddleButtonUp()

    def change_quickly_slices(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        max_slice = self.image_viewer.get_count_of_slices()
        if max_slice <= 25:
            basic_slice_change = 10
        elif 25 < max_slice <= 50:
            basic_slice_change = 8
        elif 50 < max_slice <= 75:
            basic_slice_change = 7
        else:
            basic_slice_change = 5  # each 5 pixel on window

        if abs(dy) >= basic_slice_change:  # Slice change criteria
            # step = 1 if dy > 0 else -1 if dy < 0 else 0  # determine increase/decrease slice
            step = round(dy / basic_slice_change)  # determine increase/decrease slice

            next_slice = self.image_viewer.GetSlice() + self.image_viewer.skip_slices - step

            if 0 <= next_slice < max_slice:  # if slice valid
                if hasattr(self, 'slider') and self.slider is not None:
                    self.slider.setValue(next_slice)
                else:
                    try:
                        vtk_widget = getattr(self.image_viewer, 'vtk_widget', None)
                        if vtk_widget is not None and hasattr(vtk_widget, 'set_slice'):
                            vtk_widget.set_slice(next_slice)
                        else:
                            self.image_viewer.set_slice(next_slice)
                    except Exception:
                        return

            self.image_viewer.Render()
            self.last_pos = current_pos

    def change_window_level(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dx = current_pos[0] - self.last_pos[0]
        dy = current_pos[1] - self.last_pos[1]

        window, level = self.image_viewer.get_window_level()
        # print('current_pos:', current_pos, 'dy:', dy, 'dx:', dx)

        # Check if modality is MG (Mammography) for increased sensitivity
        modality = 'UNKNOWN'
        try:
            if hasattr(self.image_viewer, 'metadata') and self.image_viewer.metadata:
                modality = self.image_viewer.metadata.get('series', {}).get('modality', 'UNKNOWN')
        except:
            pass
        
        # MG images need 10x sensitivity due to their large dynamic range
        sensitivity_multiplier = 10.0 if modality == 'MG' else 1.0

        # invert dy for invert change window width
        # if you down your mouse, window width increases
        dy = -dy
        new_y = dy * 1.3 * sensitivity_multiplier
        new_window_center = level + new_y  # level

        # 1.5 is correlation
        new_x = dx * 1.5 * sensitivity_multiplier
        new_window_width = window + new_x

        self.image_viewer.set_window_level(new_window_width, new_window_center)
        self.image_viewer.Render()

        self.last_pos = current_pos

    def change_zoom(self):
        current_pos = self.GetInteractor().GetEventPosition()
        dy = current_pos[1] - self.last_pos[1]

        camera = self.image_viewer.GetRenderer().GetActiveCamera()
        zoom_factor = 1.0
        zoom_sensitivity = 0.005  # sensitive zoom

        if dy > 0:  # mouse moves up -> zoom in
            zoom_factor = 1 + abs(dy) * zoom_sensitivity
        elif dy < 0:  # mouse moves down -> zoom out
            zoom_factor = 1 / (1 + abs(dy) * zoom_sensitivity)

        camera.Zoom(zoom_factor)
        self.image_viewer.update_corners_actors(update_just_zoom=True)
        self.image_viewer.Render()

        self.last_pos = current_pos

    def set_slider_from_ui(self, slider):
        self.slider = slider

    def world_to_display(self, world_point):
        try:
            renderer = self.image_viewer.GetRenderer()
            coordinate = vtk.vtkCoordinate()
            coordinate.SetCoordinateSystemToWorld()
            coordinate.SetValue(world_point)
            display_point = coordinate.GetComputedDisplayValue(renderer)
            return display_point[0], display_point[1]
        except Exception as e:
            print(f"Error in world_to_display: {e}")
            return None

    def point_to_line_distance_and_t(self, point, line_start, line_end):
        """
        Compute 2D distance from a point to a line segment and its projection t in [0,1].
        point/line_* are display coordinates (x, y).
        """
        try:
            px, py = float(point[0]), float(point[1])
            x1, y1 = float(line_start[0]), float(line_start[1])
            x2, y2 = float(line_end[0]), float(line_end[1])

            dx = x2 - x1
            dy = y2 - y1
            length_sq = dx * dx + dy * dy
            if length_sq <= 0.0:
                dist = ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
                return dist, 0.0

            t = ((px - x1) * dx + (py - y1) * dy) / length_sq
            if t < 0.0:
                t = 0.0
            elif t > 1.0:
                t = 1.0

            proj_x = x1 + t * dx
            proj_y = y1 + t * dy
            dist = ((px - proj_x) ** 2 + (py - proj_y) ** 2) ** 0.5
            return dist, t
        except Exception:
            return float('inf'), 0.0

    def is_middle_segment_hit(self, t, edge_ratio: float = 0.1) -> bool:
        """Return True if projection t is within the middle portion of a segment."""
        return edge_ratio <= t <= (1.0 - edge_ratio)

    # ──────────────────────────────────────────────────────────────────
    #  Unified drag-to-move helpers (work on ANY annotation type)
    # ──────────────────────────────────────────────────────────────────

    def _find_any_drag_target(self, mouse_pos):
        """
        Search ALL annotation types on the current slice for a drag hit.
        Returns ``(obj, drag_type, start_data)`` or ``None``.
        """
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return None

        best_obj = None
        best_type = None
        best_data = None
        best_dist = self._drag_hit_distance_px

        for obj in self.widgets_by_slice[current_slice]:

            # ── RULER ──
            if hasattr(obj, self.tool_access.RULER):
                p1, p2 = obj.get_position_world()
                d1 = self.world_to_display(p1)
                d2 = self.world_to_display(p2)
                if d1 and d2:
                    dist, t = self.point_to_line_distance_and_t(mouse_pos, d1, d2)
                    if dist <= best_dist and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                        best_dist, best_obj = dist, obj
                        best_type = self.tool_access.RULER
                        best_data = (list(p1), list(p2))

            # ── ARROW ──
            elif hasattr(obj, self.tool_access.ARROW):
                p1, p2 = obj.get_position_world()
                d1 = self.world_to_display(p1)
                d2 = self.world_to_display(p2)
                if d1 and d2:
                    dist, t = self.point_to_line_distance_and_t(mouse_pos, d1, d2)
                    if dist <= best_dist and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                        best_dist, best_obj = dist, obj
                        best_type = self.tool_access.ARROW
                        best_data = (list(p1), list(p2))

            # ── ANGLE (3-point) ──
            elif hasattr(obj, self.tool_access.ANGLE):
                pA, pB, pC = obj.get_position_world()
                dA = self.world_to_display(pA)
                dB = self.world_to_display(pB)
                dC = self.world_to_display(pC)
                if dA and dB and dC:
                    dist_ab, t_ab = self.point_to_line_distance_and_t(mouse_pos, dA, dB)
                    dist_bc, t_bc = self.point_to_line_distance_and_t(mouse_pos, dB, dC)
                    if dist_ab <= best_dist and self.is_middle_segment_hit(t_ab, self._drag_edge_ratio):
                        best_dist, best_obj = dist_ab, obj
                        best_type = self.tool_access.ANGLE
                        best_data = (list(pA), list(pB), list(pC))
                    elif dist_bc <= best_dist and self.is_middle_segment_hit(t_bc, self._drag_edge_ratio):
                        best_dist, best_obj = dist_bc, obj
                        best_type = self.tool_access.ANGLE
                        best_data = (list(pA), list(pB), list(pC))

            # ── TWO-LINE ANGLE ──
            elif hasattr(obj, self.tool_access.TWO_LINE_ANGLE):
                points = obj.get_position_world()
                if points and len(points) >= 4:
                    p1, p2, p3, p4 = points[0], points[1], points[2], points[3]
                    d1 = self.world_to_display(p1)
                    d2 = self.world_to_display(p2)
                    d3 = self.world_to_display(p3)
                    d4 = self.world_to_display(p4)
                    if d1 and d2 and d3 and d4:
                        dist1, t1 = self.point_to_line_distance_and_t(mouse_pos, d1, d2)
                        dist2, t2 = self.point_to_line_distance_and_t(mouse_pos, d3, d4)
                        if dist1 <= best_dist and self.is_middle_segment_hit(t1, self._drag_edge_ratio):
                            best_dist, best_obj = dist1, obj
                            best_type = self.tool_access.TWO_LINE_ANGLE
                            best_data = [list(p1), list(p2), list(p3), list(p4)]
                        elif dist2 <= best_dist and self.is_middle_segment_hit(t2, self._drag_edge_ratio):
                            best_dist, best_obj = dist2, obj
                            best_type = self.tool_access.TWO_LINE_ANGLE
                            best_data = [list(p1), list(p2), list(p3), list(p4)]

            # ── ROI (polygon) ──
            elif hasattr(obj, self.tool_access.ROI):
                line_pairs = obj.get_position_world()
                for start_pt, end_pt in line_pairs:
                    sd = self.world_to_display(start_pt)
                    ed = self.world_to_display(end_pt)
                    if sd and ed:
                        dist, t = self.point_to_line_distance_and_t(mouse_pos, sd, ed)
                        if dist <= best_dist and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                            best_dist, best_obj = dist, obj
                            best_type = self.tool_access.ROI
                            # capture all node world positions
                            roi_widget, _text_obj = obj.get_widget()
                            nodes = []
                            try:
                                num = roi_widget.repr.GetNumberOfNodes()
                                for i in range(num):
                                    pos = [0.0, 0.0, 0.0]
                                    roi_widget.repr.GetNthNodeWorldPosition(i, pos)
                                    nodes.append(list(pos))
                            except Exception:
                                pass
                            best_data = nodes
                            break  # one edge hit is enough

            # ── CIRCLE ROI ──
            elif hasattr(obj, self.tool_access.CIRCLE_ROI):
                line_pairs = obj.get_position_world()
                for start_pt, end_pt in line_pairs:
                    sd = self.world_to_display(start_pt)
                    ed = self.world_to_display(end_pt)
                    if sd and ed:
                        dist, t = self.point_to_line_distance_and_t(mouse_pos, sd, ed)
                        if dist <= best_dist and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                            best_dist, best_obj = dist, obj
                            best_type = self.tool_access.CIRCLE_ROI
                            circle_widget, _text_obj = obj.get_widget()
                            best_data = list(circle_widget.get_center())
                            break

        if best_obj is None:
            return None
        return best_obj, best_type, best_data

    def _apply_drag_delta(self, dx, dy, dz):
        """Move the currently dragged annotation by a world-space delta."""
        obj = self._dragging_obj
        dtype = self._drag_type
        data = self._drag_start_data

        if dtype == self.tool_access.RULER:
            p1, p2 = data
            new_p1 = [p1[0] + dx, p1[1] + dy, p1[2] + dz]
            new_p2 = [p2[0] + dx, p2[1] + dy, p2[2] + dz]
            widget = obj.get_widget()
            rep = widget.GetRepresentation()
            rep.SetPoint1WorldPosition(new_p1)
            rep.SetPoint2WorldPosition(new_p2)

        elif dtype == self.tool_access.ARROW:
            p1, p2 = data
            new_p1 = [p1[0] + dx, p1[1] + dy, p1[2] + dz]
            new_p2 = [p2[0] + dx, p2[1] + dy, p2[2] + dz]
            arrow_widget, triangle_object = obj.get_widget()
            rep = arrow_widget.GetRepresentation()
            rep.SetPoint1WorldPosition(new_p1)
            rep.SetPoint2WorldPosition(new_p2)
            triangle_object.triangle_tip = new_p1
            self._update_arrow_triangle(
                triangle_object.triangle_points, new_p1, new_p2
            )

        elif dtype == self.tool_access.ANGLE:
            pA, pB, pC = data
            new_pA = [pA[0] + dx, pA[1] + dy, pA[2] + dz]
            new_pB = [pB[0] + dx, pB[1] + dy, pB[2] + dz]
            new_pC = [pC[0] + dx, pC[1] + dy, pC[2] + dz]
            widget = obj.get_widget()
            rep = widget.GetRepresentation()
            rep.SetPoint1WorldPosition(new_pA)
            rep.SetCenterWorldPosition(new_pB)
            rep.SetPoint2WorldPosition(new_pC)

        elif dtype == self.tool_access.TWO_LINE_ANGLE:
            p1, p2, p3, p4 = data[0], data[1], data[2], data[3]
            new_p1 = [p1[0] + dx, p1[1] + dy, p1[2] + dz]
            new_p2 = [p2[0] + dx, p2[1] + dy, p2[2] + dz]
            new_p3 = [p3[0] + dx, p3[1] + dy, p3[2] + dz]
            new_p4 = [p4[0] + dx, p4[1] + dy, p4[2] + dz]
            line1_w, line2_w, text_actor, _pa = obj.get_widget()
            if line1_w:
                r1 = line1_w.GetDistanceRepresentation()
                r1.SetPoint1WorldPosition(new_p1)
                r1.SetPoint2WorldPosition(new_p2)
            if line2_w:
                r2 = line2_w.GetDistanceRepresentation()
                r2.SetPoint1WorldPosition(new_p3)
                r2.SetPoint2WorldPosition(new_p4)
            if text_actor is not None:
                mid = [
                    (new_p1[0] + new_p2[0] + new_p3[0] + new_p4[0]) / 4.0,
                    (new_p1[1] + new_p2[1] + new_p3[1] + new_p4[1]) / 4.0,
                    (new_p1[2] + new_p2[2] + new_p3[2] + new_p4[2]) / 4.0,
                ]
                dp = self.world_to_display(mid)
                if dp:
                    text_actor.SetPosition(dp[0], dp[1])

        elif dtype == self.tool_access.ROI:
            nodes = data  # list of [x,y,z]
            roi_widget, text_obj = obj.get_widget()
            for i, node in enumerate(nodes):
                new_pos = [node[0] + dx, node[1] + dy, node[2] + dz]
                try:
                    roi_widget.repr.SetNthNodeWorldPosition(i, new_pos)
                except Exception:
                    pass
            # move text actor
            if text_obj:
                text_actor = text_obj.get_widget()
                if text_actor and hasattr(text_actor, 'SetPosition'):
                    new_nodes = [[n[0] + dx, n[1] + dy, n[2] + dz] for n in nodes]
                    min_y_node = min(new_nodes, key=lambda p: p[1])
                    text_actor.SetPosition(min_y_node[0], min_y_node[1] - 10, min_y_node[2])

        elif dtype == self.tool_access.CIRCLE_ROI:
            center = data
            new_center = [center[0] + dx, center[1] + dy, center[2] + dz]
            circle_widget, _text_obj = obj.get_widget()
            circle_widget.set_center(new_center)

        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.Render()

    def _update_arrow_triangle(self, points, tip, tail):
        """Recompute arrow-head triangle vertices after a drag move."""
        try:
            tip = np.array(tip, dtype=float)
            tail = np.array(tail, dtype=float)
            direction = tail - tip
            norm = np.linalg.norm(direction)
            if norm == 0:
                direction = np.array([1, 0, 0])
            else:
                direction = direction / norm

            size = self.world_length_from_pixels(tip, self.arrow_head_size_px, axis='x')
            if size <= 0:
                size = 1.0
            width_ratio = self.arrow_head_width_ratio

            base_center = tip + direction * size
            up = np.array([0, 0, 1])
            perp = np.cross(direction, up)
            if np.linalg.norm(perp) < 1e-3:
                up = np.array([0, 1, 0])
                perp = np.cross(direction, up)
            perp = perp / np.linalg.norm(perp)

            width = size * width_ratio
            base1 = base_center + perp * width
            base2 = base_center - perp * width

            points.SetPoint(0, *tip)
            points.SetPoint(1, *base1)
            points.SetPoint(2, *base2)
            points.Modified()
        except Exception as e:
            print(f"[DRAG] Error updating arrow triangle: {e}")

    def display_to_world(self, x, y):
        # z_phys = self.image_viewer.GetSlice() * self.image_viewer.get_count_of_slices()
        z_phys = self.image_viewer.get_count_of_slices()
        c = vtk.vtkCoordinate()
        c.SetCoordinateSystemToDisplay()
        c.SetValue(x, y, 0)
        w = c.GetComputedWorldValue(self.image_viewer.renderer)
        # return w[0], w[1], z_phys
        return w[0], w[1], w[2]

    def world_length_from_pixels(self, world_point, pixel_length: float, axis: str = 'x') -> float:
        """
        Convert a pixel length at a given world point into world units.

        Args:
            world_point: Reference world point (x, y, z)
            pixel_length: Length in pixels
            axis: 'x' or 'y' for display axis shift
        """
        try:
            renderer = self.image_viewer.renderer
            renderer.SetWorldPoint(world_point[0], world_point[1], world_point[2], 1.0)
            renderer.WorldToDisplay()
            d0 = renderer.GetDisplayPoint()

            if axis == 'y':
                d1 = (d0[0], d0[1] + float(pixel_length), d0[2])
            else:
                d1 = (d0[0] + float(pixel_length), d0[1], d0[2])

            renderer.SetDisplayPoint(d1[0], d1[1], d1[2])
            renderer.DisplayToWorld()
            w1 = renderer.GetWorldPoint()
            if w1 and w1[3] != 0:
                w1 = (w1[0] / w1[3], w1[1] / w1[3], w1[2] / w1[3])
                dx = w1[0] - world_point[0]
                dy = w1[1] - world_point[1]
                dz = w1[2] - world_point[2]
                return float((dx * dx + dy * dy + dz * dz) ** 0.5)
        except Exception:
            pass
        return 0.0

    def add_object_to_store_widgets(self, obj, obj_name):
        current_slice = self.image_viewer.GetSlice()
        
        if current_slice not in self.widgets_by_slice:
            self.widgets_by_slice[current_slice] = set()

        self.widgets_by_slice[current_slice].add(obj)
        total_widgets = sum(len(w) for w in self.widgets_by_slice.values())
        print(f"[ADD WIDGET] {obj_name} added to slice {current_slice} (Total: {total_widgets} widgets)")
        setattr(obj, obj_name, current_slice)

    def auto_deactivate_tool(self):
        """
        Return to default interactor style and clear toolbar selection.
        Called from VTK observer callbacks when a one-shot tool completes.
        """
        try:
            vtk_widget = getattr(self.image_viewer, 'vtk_widget', None)
            if vtk_widget is None:
                return

            # --- 1. Clear toolbar state immediately ---
            patient_widget = getattr(vtk_widget, 'patient_widget', None)
            toolbar = None
            if patient_widget is not None and hasattr(patient_widget, 'toolbar_manager'):
                toolbar = patient_widget.toolbar_manager
                toolbar.tool_selected = None

            # --- 2. Restore default interactor style (all VTK work) ---
            try:
                vtk_widget.restore_default_interactorstyle()
            except Exception as e:
                pass
            try:
                if hasattr(vtk_widget, 'current_style') and hasattr(vtk_widget.current_style, 'update_slice'):
                    vtk_widget.current_style.update_slice()
            except Exception:
                pass

            # --- 3. Update toolbar buttons ---
            if toolbar is not None:
                try:
                    toolbar.handle_buttons_checked()
                except Exception:
                    pass

                # Force Qt to process the repaint events RIGHT NOW
                try:
                    from PySide6.QtWidgets import QApplication
                    app = QApplication.instance()
                    if app:
                        app.processEvents()
                except Exception:
                    pass

                # Safety net: deferred callbacks
                try:
                    from PySide6.QtCore import QTimer
                    QTimer.singleShot(50, toolbar.handle_buttons_checked)
                    QTimer.singleShot(200, toolbar.handle_buttons_checked)
                except Exception:
                    pass
        except Exception:
            pass
    
    def activate(self, tool=None):
        """
        Base activate method for toolbar compatibility.
        Subclasses can override this for specific activation behavior.
        
        Args:
            tool: Optional tool identifier
        """
        pass
    
    def deactivate(self, tool=None):
        """
        Base deactivate method for toolbar compatibility.
        Subclasses can override this for specific deactivation behavior.
        
        Args:
            tool: Optional tool identifier
        """
        pass