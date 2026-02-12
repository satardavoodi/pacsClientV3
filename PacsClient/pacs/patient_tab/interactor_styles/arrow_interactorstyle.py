import math
import numpy as np
import vtkmodules.all as vtk
from . import AbstractInteractorStyle
from .tools_object_manager import ArrowObject, TriangleObject


class ArrowInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer
        self.color = (0, 0.9, 0)
        self.arrow_head_size_px = 42
        self.arrow_head_width_ratio = 0.45

        self.n_clicks = 0
        self.is_active = False

        self.triangle_object = TriangleObject(default_color=self.color)
        self.active_widget = self.create_widget()
        self.active_widget.Off()

        self._dragging_obj = None
        self._drag_start_world = None
        self._drag_start_points = None
        self._hover_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1

        self.interactor_name = self.tool_access.ARROW

    def set_widget_repr(self, active_widget):
        line_rep = vtk.vtkLineRepresentation()
        line_rep.GetLineProperty().SetLineWidth(4)
        line_rep.GetLineProperty().SetColor(self.color)

        # set hide point 1 line of arrow
        line_rep.GetPoint1Representation().GetProperty().SetOpacity(0)
        active_widget.SetRepresentation(line_rep)

    def create_widget(self):
        line_widget = vtk.vtkLineWidget2()
        # line_rep = vtk.vtkLineRepresentation()

        line_widget.SetInteractor(self.image_viewer.image_interactor)
        line_widget.AddObserver(vtk.vtkCommand.EndInteractionEvent, self.on_left_button_press)
        # line_widget.AddObserver(vtk.vtkCommand.EndInteractionEvent, self.on_line_widget_end_interaction)
        # line_widget.AddObserver(vtk.vtkCommand.InteractionEvent, self.on_line_widget_interaction)

        line_widget.SetProcessEvents(False)
        return line_widget

    #
    # def on_line_widget_interaction(self, obj, event):
    #     # در هر لحظه‌ی تغییر، این تابع اجرا می‌شود
    #     # update Triangle base on mouse
    #     # display_pos = self.GetInteractor().GetEventPosition()
    #     # world_pos = self.display_to_world(display_pos[0], display_pos[1])
    #     # self.update_triangle_points(self.triangle_points, self.triangle_tip, tail=world_pos, size=4)
    #     print("Line is being drawn or dragged...")
    #
    #
    # def on_line_widget_end_interaction(self, obj, event):
    #     # اینجا خط "فیکس" شده و user کلیک دوم را زده است
    #     print("Line placed or moved!")

    def activate(self, tool=None):
        self.is_active = True
        # print("Arrow Widget tool activated")

    def deactivate(self, tool=None):
        self.is_active = False
        # print("Arrow Widget tool deactivated")

    def _set_cursor(self, cursor_type):
        if hasattr(self.image_viewer.image_interactor, 'SetCursor'):
            self.image_viewer.image_interactor.SetCursor(cursor_type)

    def _find_drag_target(self, mouse_pos):
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return None

        closest_obj = None
        closest_points = None
        min_distance = self._drag_hit_distance_px

        for obj in self.widgets_by_slice[current_slice]:
            if not hasattr(obj, self.tool_access.ARROW):
                continue

            point1_world, point2_world = obj.get_position_world()
            point1_display = self.world_to_display(point1_world)
            point2_display = self.world_to_display(point2_world)
            if not point1_display or not point2_display:
                continue

            distance, t = self.point_to_line_distance_and_t(mouse_pos, point1_display, point2_display)
            if distance <= min_distance and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                min_distance = distance
                closest_obj = obj
                closest_points = (point1_world, point2_world)

        if closest_obj is None:
            return None
        return closest_obj, closest_points

    def on_left_button_press(self, obj, event):
        if self.n_clicks == 0:
            mouse_pos = self.GetInteractor().GetEventPosition()
            drag_target = self._find_drag_target(mouse_pos)
            if drag_target is not None:
                obj_to_drag, points = drag_target
                self._dragging_obj = obj_to_drag
                self._drag_start_points = points
                self._drag_start_world = self.display_to_world(mouse_pos[0], mouse_pos[1])
                self._set_cursor(vtk.VTK_CURSOR_HAND)
                return

        if not self.is_active:
            return

        display_pos = self.GetInteractor().GetEventPosition()
        world_pos = self.display_to_world(display_pos[0], display_pos[1])

        self.n_clicks += 1
        if self.n_clicks == 2:
            self.n_clicks = 0

            # hide second point of line
            self.active_widget.GetLineRepresentation().GetPoint2Representation().GetProperty().SetOpacity(0)

            # create arrow object
            arrow_object = ArrowObject(self.active_widget, self.triangle_object, default_color=self.color)
            self.add_object_to_store_widgets(arrow_object, self.tool_access.ARROW)

            # reset actors and widgets arrow
            self.triangle_object = TriangleObject(default_color=self.color)
            self.active_widget = self.create_widget()
            self.is_active = False
            self.auto_deactivate_tool()
            return

        else:

            self.active_widget.On()
            self.set_widget_repr(self.active_widget)

            # set parameters on triangle (actor, points, tip)
            self.triangle_object.triangle_tip = world_pos
            self.triangle_object.triangle_actor, self.triangle_object.triangle_points = self.create_triangle_actor(
                tip=world_pos,
                tail=world_pos,
                size=None,
                width_ratio=None
            )
            self.image_viewer.renderer.AddActor(self.triangle_object.triangle_actor)

            line_rep = self.active_widget.GetLineRepresentation()
            line_rep.SetPoint1WorldPosition(world_pos)
            line_rep.SetPoint2WorldPosition(world_pos)

            self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.Render()

    def on_mouse_move(self, obj, event):
        # Only handle events if the ruler tool is active
        flag_active_arrow = super().on_mouse_move(obj, event)
        if flag_active_arrow:
            return True

        if self._dragging_obj is not None and self._drag_start_points is not None:
            current_pos = self.GetInteractor().GetEventPosition()
            current_world = self.display_to_world(current_pos[0], current_pos[1])
            if current_world is None or self._drag_start_world is None:
                return True

            dx = current_world[0] - self._drag_start_world[0]
            dy = current_world[1] - self._drag_start_world[1]
            dz = current_world[2] - self._drag_start_world[2]

            p1_start, p2_start = self._drag_start_points
            new_p1 = [p1_start[0] + dx, p1_start[1] + dy, p1_start[2] + dz]
            new_p2 = [p2_start[0] + dx, p2_start[1] + dy, p2_start[2] + dz]

            arrow_widget, triangle_object = self._dragging_obj.get_widget()
            repr_obj = arrow_widget.GetRepresentation()
            if hasattr(repr_obj, 'SetPoint1WorldPosition'):
                repr_obj.SetPoint1WorldPosition(new_p1)
            if hasattr(repr_obj, 'SetPoint2WorldPosition'):
                repr_obj.SetPoint2WorldPosition(new_p2)

            triangle_object.triangle_tip = new_p1
            self.update_triangle_points(
                triangle_object.triangle_points,
                new_p1,
                new_p2,
                size=None,
                width_ratio=None
            )

            self.image_viewer.renderer.ResetCameraClippingRange()
            self.image_viewer.Render()
            return True

        if self.n_clicks != 1:
            if self.n_clicks == 0:
                hover_target = self._find_drag_target(self.GetInteractor().GetEventPosition())
                if hover_target is not None:
                    if self._hover_obj != hover_target[0]:
                        self._hover_obj = hover_target[0]
                        self._set_cursor(vtk.VTK_CURSOR_HAND)
                else:
                    if self._hover_obj is not None:
                        self._hover_obj = None
                        self._set_cursor(vtk.VTK_CURSOR_ARROW)
            return

        # we run on_mouse_move if we are drawing arrow
        display_pos = self.GetInteractor().GetEventPosition()
        world_pos = self.display_to_world(display_pos[0], display_pos[1])

        # if line arrow has created:
        line_rep = self.active_widget.GetLineRepresentation()
        if line_rep:
            # update triangle base on new pos mouse
            self.update_triangle_points(
                self.triangle_object.triangle_points,
                self.triangle_object.triangle_tip,
                world_pos,
                size=None,
                width_ratio=None
            )
            line_rep.SetPoint2WorldPosition(world_pos)
            self.image_viewer.Render()

    def on_left_button_release(self, obj, event):
        if self._dragging_obj is not None:
            self._dragging_obj = None
            self._drag_start_world = None
            self._drag_start_points = None
            self._set_cursor(vtk.VTK_CURSOR_ARROW)
            return

    def create_triangle_actor(self, tip, tail, size=8, width_ratio=0.5, color=(1, 1, 0)):
        """
        tip: راس مثلث (نوک سر فلش)
        tail: نقطه دوم خط (جهت خط)
        size: طول مثلث (از نوک تا وسط قاعده)
        width_ratio: نسبت عرض قاعده به طول (عدد کوچکتر = باریک‌تر)
        color: رنگ مثلث
        """

        tip = np.array(tip, dtype=float)
        tail = np.array(tail, dtype=float)
        direction = tail - tip
        norm = np.linalg.norm(direction)
        if norm == 0:
            direction = np.array([1, 0, 0])
        else:
            direction = direction / norm

        if size is None:
            size = self.world_length_from_pixels(tip, self.arrow_head_size_px, axis='x')
            if size <= 0:
                size = 1.0
        if width_ratio is None:
            width_ratio = self.arrow_head_width_ratio

        # مرکز قاعده (در امتداد خط، size فاصله از نوک)
        base_center = tip + direction * size

        # بردار عمود بر خط (در صفحه خط - معمولاً فرض XY)
        # اگر خط تقریباً موازی Z است، بردار عمود را با Y یا X بگیر
        up = np.array([0, 0, 1])
        perp = np.cross(direction, up)
        if np.linalg.norm(perp) < 1e-3:
            up = np.array([0, 1, 0])
            perp = np.cross(direction, up)
        perp = perp / np.linalg.norm(perp)

        # نقاط دو سر قاعده مثلث
        width = size * width_ratio
        base1 = base_center + perp * width
        base2 = base_center - perp * width

        # تعریف مثلث
        points = vtk.vtkPoints()
        points.InsertNextPoint(*tip)  # رأس (نوک پیکان)
        points.InsertNextPoint(*base1)  # گوشه اول قاعده
        points.InsertNextPoint(*base2)  # گوشه دوم قاعده
        triangle = vtk.vtkTriangle()
        triangle.GetPointIds().SetId(0, 0)
        triangle.GetPointIds().SetId(1, 1)
        triangle.GetPointIds().SetId(2, 2)
        triangles = vtk.vtkCellArray()
        triangles.InsertNextCell(triangle)
        poly = vtk.vtkPolyData()
        poly.SetPoints(points)
        poly.SetPolys(triangles)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(self.color)
        actor.GetProperty().SetOpacity(1)
        return actor, points

    def update_triangle_points(self, points, tip, tail, size=8, width_ratio=0.5):
        """
        points: شیء vtkPoints مربوط به مثلث (polydata)
        tip: مختصات نوک فلش (رأس مثلث)
        tail: انتهای خط (جهت فلش)
        size: طول فلش (پیش‌فرض 8)
        width_ratio: نسبت عرض به طول قاعده فلش (پیش‌فرض 0.5)
        """
        tip = np.array(tip, dtype=float)
        tail = np.array(tail, dtype=float)
        direction = tail - tip
        norm = np.linalg.norm(direction)
        if norm == 0:
            direction = np.array([1, 0, 0])
        else:
            direction = direction / norm

        if size is None:
            size = self.world_length_from_pixels(tip, self.arrow_head_size_px, axis='x')
            if size <= 0:
                size = 1.0
        if width_ratio is None:
            width_ratio = self.arrow_head_width_ratio

        # مرکز قاعده مثلث
        base_center = tip + direction * size

        # بردار عمود بر خط
        up = np.array([0, 0, 1])
        perp = np.cross(direction, up)
        if np.linalg.norm(perp) < 1e-3:
            up = np.array([0, 1, 0])
            perp = np.cross(direction, up)
        perp = perp / np.linalg.norm(perp)

        width = size * width_ratio
        base1 = base_center + perp * width
        base2 = base_center - perp * width

        # بروزرسانی نقاط مثلث
        points.SetPoint(0, *tip)
        points.SetPoint(1, *base1)
        points.SetPoint(2, *base2)
        points.Modified()
