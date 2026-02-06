import vtk
import numpy as np
from . import AbstractInteractorStyle
from .tools_object_manager import ToolObjectAbstract


class EraserInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        """
        Initialize the RulerInteractorStyle for handling ruler interactions.
        """
        # super().__init__()
        super().__init__(image_viewer)
        self.image_viewer = image_viewer

        self.hover_obj = None
        self.interactor_name = self.tool_access.ERASER

    def on_left_button_press(self, obj, event):
        mouse_pos = self.GetInteractor().GetEventPosition()
        obj = self.find_widget_at_position(mouse_pos)
        current_slice = self.image_viewer.GetSlice()
        self.delete_widget(obj, current_slice)

    def find_widget_at_position(self, mouse_pos):
        try:
            current_slice = self.image_viewer.GetSlice()

            # just check widget on current slice
            if current_slice not in self.widgets_by_slice:
                return None

            # بررسی فاصله از هر خط
            min_distance = 10  # حداکثر فاصله قابل قبول (پیکسل)
            # closest_widget = None
            closest_object = None

            for obj in self.widgets_by_slice[current_slice]:
                obj: ToolObjectAbstract
                if hasattr(obj, self.tool_access.RULER):
                    # دریافت نقاط خط
                    point1_world, point2_world = obj.get_position_world()

                    # تبدیل به مختصات نمایش
                    point1_display = self.world_to_display(point1_world)
                    point2_display = self.world_to_display(point2_world)

                    # محاسبه فاصله از خط
                    distance = self.point_to_line_distance(mouse_pos, point1_display, point2_display)

                    if distance < min_distance:
                        min_distance = distance
                        closest_object = obj

                elif hasattr(obj, self.tool_access.ANGLE):
                    pointA_world, pointB_world, pointC_world = obj.get_position_world()
                    # تبدیل به مختصات نمایش
                    pointA_display = self.world_to_display(pointA_world)
                    pointB_display = self.world_to_display(pointB_world)
                    pointC_display = self.world_to_display(pointC_world)

                    distance_AB = self.point_to_line_distance(mouse_pos, pointA_display, pointB_display)
                    distance_BC = self.point_to_line_distance(mouse_pos, pointB_display, pointC_display)

                    if distance_AB < min_distance:
                       min_distance = distance_AB
                       closest_object = obj

                    elif distance_BC < min_distance:
                        min_distance = distance_BC
                        closest_object = obj

                elif hasattr(obj, self.tool_access.ARROW):
                    arrow_pos = obj.get_position_world()
                    pointA_arrow = self.world_to_display(arrow_pos[0])
                    pointB_arrow = self.world_to_display(arrow_pos[1])

                    distance_AB = self.point_to_line_distance(mouse_pos, pointA_arrow, pointB_arrow)
                    if distance_AB < min_distance:
                       min_distance = distance_AB
                       closest_object = obj

                elif hasattr(obj, self.tool_access.TEXT):
                    bottom_left, bottom_right, up_right, up_left = obj.get_position_world()

                    bottom_left_display = self.world_to_display(bottom_left)
                    bottom_right_display = self.world_to_display(bottom_right)
                    up_right_display = self.world_to_display(up_right)
                    up_left_display = self.world_to_display(up_left)

                    distance_bottom_line = self.point_to_line_distance(mouse_pos, bottom_left_display, bottom_right_display)
                    distance_up_line = self.point_to_line_distance(mouse_pos, up_left_display, up_right_display)

                    if distance_bottom_line < min_distance * 3:
                       min_distance = distance_bottom_line
                       closest_object = obj

                    elif distance_up_line < min_distance * 3:
                        min_distance = distance_up_line
                        closest_object = obj

                elif hasattr(obj, self.tool_access.ROI):
                    line_pairs = obj.get_position_world()

                    for start_point, end_point in line_pairs:
                        start_point_display = self.world_to_display(start_point)
                        end_point_display = self.world_to_display(end_point)

                        distance = self.point_to_line_distance(mouse_pos, start_point_display, end_point_display)

                        if distance < min_distance:
                            min_distance = distance
                            closest_object = obj
                            break

                elif hasattr(obj, self.tool_access.CIRCLE_ROI):
                    line_pairs = obj.get_position_world()

                    for start_point, end_point in line_pairs:
                        start_point_display = self.world_to_display(start_point)
                        end_point_display = self.world_to_display(end_point)

                        distance = self.point_to_line_distance(mouse_pos, start_point_display, end_point_display)

                        if distance < min_distance:
                            min_distance = distance
                            closest_object = obj
                            break

            return closest_object

        except Exception as e:
            print(f"Error finding widget at position: {e}")
            return None

    def point_to_line_distance(self, point, line_start, line_end):
        """
        محاسبه فاصله یک نقطه از خط
        """
        try:
            # تبدیل به آرایه numpy
            p = np.array([point[0], point[1]])
            s = np.array([line_start[0], line_start[1]])
            e = np.array([line_end[0], line_end[1]])

            # طول خط
            line_length = np.linalg.norm(e - s)

            if line_length == 0:
                # اگر طول خط صفر باشد، فاصله از نقطه شروع را برمی‌گرداند
                return np.linalg.norm(p - s)

            # محاسبه فاصله
            t = np.maximum(0, np.minimum(1, np.dot(p - s, e - s) / (line_length * line_length)))
            projection = s + t * (e - s)
            distance = np.linalg.norm(p - projection)

            return distance

        except Exception as e:
            print(f"Error calculating distance: {e}")
            return float('inf')  # مقدار بی‌نهایت به معنای عدم انتخاب

    def on_mouse_move(self, obj, event):
        """
        Handle mouse movement events.
        """
        # Only handle events if the ruler tool is active
        flag_active_eraser = super(EraserInteractorStyle, self).on_mouse_move(obj, event)
        if flag_active_eraser:
            return True

        # بررسی حالت hover روی خط‌ها
        mouse_pos = self.GetInteractor().GetEventPosition()
        obj = self.find_widget_at_position(mouse_pos)

        # print('obj:', obj)

        # اگر خط جدیدی پیدا شد، نشانگر ماوس را تغییر دهید
        if obj != self.hover_obj:
            if self.hover_obj:
                # بازگرداندن رنگ خط قبلی
                self.hover_obj.change_color(self.hover_obj.default_color)
            self.hover_obj = obj
            if obj:
                # تغییر رنگ خط جدید
                obj.change_color((1, 0, 0))

            self.image_viewer.Render()
            return True


        '''
                # بررسی حالت hover روی خط‌ها
        mouse_pos = self.GetInteractor().GetEventPosition()
        widget = self.find_widget_at_position(mouse_pos)

        # اگر خط جدیدی پیدا شد، نشانگر ماوس را تغییر دهید
        if widget != self.hover_widget:
            if self.hover_widget:
                # بازگرداندن رنگ خط قبلی
                repr = self.hover_widget.GetRepresentation()
                repr.GetAxisProperty().SetColor(0.1, 0.5, 1.0)

            self.hover_widget = widget

            if widget:
                # تغییر رنگ خط جدید
                repr = widget.GetRepresentation()
                repr.GetAxisProperty().SetColor(1, 0, 0)  # قرمز

        return True
        
        '''