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

        self.n_clicks = 0
        self.is_active = False

        self.triangle_object = TriangleObject(default_color=self.color)
        self.active_widget = self.create_widget()
        self.active_widget.Off()

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

    def on_left_button_press(self, obj, event):
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

        else:

            self.active_widget.On()
            self.set_widget_repr(self.active_widget)

            # set parameters on triangle (actor, points, tip)
            self.triangle_object.triangle_tip = world_pos
            self.triangle_object.triangle_actor, self.triangle_object.triangle_points = self.create_triangle_actor(tip=world_pos, tail=world_pos, size=1)
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

        if self.n_clicks != 1:
            return

        # we run on_mouse_move if we are drawing arrow
        display_pos = self.GetInteractor().GetEventPosition()
        world_pos = self.display_to_world(display_pos[0], display_pos[1])

        # if line arrow has created:
        line_rep = self.active_widget.GetLineRepresentation()
        if line_rep:
            # update triangle base on new pos mouse
            self.update_triangle_points(self.triangle_object.triangle_points, self.triangle_object.triangle_tip, world_pos, size=4)
            line_rep.SetPoint2WorldPosition(world_pos)
            self.image_viewer.Render()

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
