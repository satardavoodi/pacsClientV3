from abc import ABC, abstractmethod
import vtkmodules.all as vtk


class ToolAccess:
    # ============ TOOL CATEGORIES ============

    # Category 1: Basic Tools (Reset & Layout)
    ABSTRACT = 'abstract'
    RESET = 'reset'
    RESET_ALL = 'reset_all'

    # Category 2: Measurement Tools
    RULER = 'ruler'
    ANGLE = 'angle'
    TWO_LINE_ANGLE = 'two_line_angle'
    ARROW = 'arrow'

    # Category 3: Annotation Tools
    TEXT = 'text'
    ROI = 'roi'
    CIRCLE_ROI = 'circle_roi'
    ERASER = 'eraser'

    # Category 4: View Manipulation Tools
    ZOOM_TO_FIT = 'zoom_to_fit'
    ZOOM = 'zoom'
    WINDOW_LEVEL = 'window_level'
    PAN = 'pan'
    STACKED = 'stacked'

    # Category 5: Image Transform Tools
    ROTATION_LEFT = 'rotation_left'
    ROTATION_RIGHT = 'rotation_right'
    FLIP_HORIZONTAL = 'flip_horizontal'
    FLIP_VERTICAL = 'flip_vertical'

    # Category 6: Capture & Audio Tools
    CAPTURE = 'capture'
    MICROPHONE = 'microphone'
    AI_CHAT = "ai_chat"

    # Category 7: Advanced Visualization Tools
    MIP = "mip"  # 2D Maximum Intensity Projection
    MINIP = "minip"  # 2D Minimum Intensity Projection
    THICK_SLAB = "thick_slab"  # 2D Thick Slab MIP
    MPR = "mpr"  # Multi-planar reconstruction
    CURVED_MPR = "curved_mpr"  # Curved MPR
    TARGET = "target"  # Sync point/cursor mode

    # Category 8: Segmentation Tools
    SEGMENTATION = "segmentation"
    POLYGON_SEGMENTATION = "polygon_segmentation"
    RECTANGLE_SEGMENTATION = "rectangle_segmentation"

    # upload
    UPLOAD = 'upload'

class ToolObjectAbstract(ABC):
    """
        this class user for tools that they can register widgets (rule, angle,...) on the image
    """

    @abstractmethod
    def __init__(self):
        pass

    @abstractmethod
    def On(self):
        pass

    @abstractmethod
    def Off(self):
        pass

    @abstractmethod
    def get_widget(self):
        pass

    @abstractmethod
    def change_color(self, color):
        pass

    @abstractmethod
    def get_position_world(self):
        pass

    @abstractmethod
    def delete_widget(self, image_viewer):
        pass


class RulerObject(ToolObjectAbstract):
    def __init__(self, ruler_widget, default_color):
        self.ruler_widget = ruler_widget
        self.default_color = default_color

    def On(self):
        self.ruler_widget.On()

    def Off(self):
        self.ruler_widget.Off()

    def get_widget(self):
        return self.ruler_widget

    def change_color(self, color):
        repr = self.get_widget().GetRepresentation()
        repr.GetAxisProperty().SetColor(color)

    def get_position_world(self):
        # دریافت نقاط خط
        widget = self.get_widget()
        repr = widget.GetRepresentation()
        point1_world = [0, 0, 0]
        point2_world = [0, 0, 0]
        repr.GetPoint1WorldPosition(point1_world)
        repr.GetPoint2WorldPosition(point2_world)
        return point1_world, point2_world

    def delete_widget(self, image_viewer):
        self.Off()
        widget = self.get_widget()
        # self.image_viewer.GetMeasurements().RemoveItem(widget)
        del widget


class AngleObject(ToolObjectAbstract):
    def __init__(self, angle_widget, default_color):
        self.angle_object = angle_widget
        self.default_color = default_color

    def On(self):
        self.angle_object.On()

    def Off(self):
        self.angle_object.Off()

    def get_widget(self):
        return self.angle_object

    def change_color(self, color):
        # change points color
        repr = self.get_widget().GetRepresentation()
        repr_points = repr.GetPoint1Representation()
        repr_points.GetProperty().SetColor(color)  # point A, B, C

        # change arc color
        repr_arc = repr.GetArc()
        repr_arc.GetProperty().SetColor(color)

        # change color lines 1,2
        repr.GetRay1().GetProperty().SetColor(color)
        repr.GetRay2().GetProperty().SetColor(color)

    def get_position_world(self):
        widget = self.get_widget()
        repr = widget.GetRepresentation()
        point1_world = [0, 0, 0]
        point2_world = [0, 0, 0]
        point3_world = [0, 0, 0]
        repr.GetPoint1WorldPosition(point1_world)
        repr.GetCenterWorldPosition(point2_world)
        repr.GetPoint2WorldPosition(point3_world)
        return point1_world, point2_world, point3_world

    def delete_widget(self, image_viewer):
        self.Off()
        widget = self.get_widget()
        # self.image_viewer.GetMeasurements().RemoveItem(widget)
        del widget


class TwoLineAngleObject(ToolObjectAbstract):
    """Object for two-line angle measurement"""
    
    def __init__(self, line1_actor, line2_actor, text_actor, point_actors, points, default_color):
        self.line1_widget = line1_actor  # Actually a widget, not actor
        self.line2_widget = line2_actor  # Actually a widget, not actor
        self.text_actor = text_actor
        self.point_actors = point_actors  # List of point actors (usually empty in new implementation)
        self.points = points  # List of 4 points
        self.default_color = default_color

    def On(self):
        if self.line1_widget:
            self.line1_widget.On()
        if self.line2_widget:
            self.line2_widget.On()
        if self.text_actor:
            self.text_actor.SetVisibility(True)
        for actor in self.point_actors:
            actor.SetVisibility(True)

    def Off(self):
        if self.line1_widget:
            self.line1_widget.Off()
        if self.line2_widget:
            self.line2_widget.Off()
        if self.text_actor:
            self.text_actor.SetVisibility(False)
        for actor in self.point_actors:
            actor.SetVisibility(False)

    def get_widget(self):
        return (self.line1_widget, self.line2_widget, self.text_actor, self.point_actors)

    def change_color(self, color):
        if self.line1_widget:
            rep = self.line1_widget.GetDistanceRepresentation()
            rep.GetAxisProperty().SetColor(color)
        if self.line2_widget:
            rep = self.line2_widget.GetDistanceRepresentation()
            rep.GetAxisProperty().SetColor(color)
        if self.text_actor:
            self.text_actor.GetTextProperty().SetColor(color)
        for actor in self.point_actors:
            if hasattr(actor, 'GetProperty'):
                actor.GetProperty().SetColor(color)
            elif hasattr(actor, 'GetTextProperty'):
                actor.GetTextProperty().SetColor(color)

    def get_position_world(self):
        return self.points

    def delete_widget(self, image_viewer):
        self.Off()
        if self.line1_widget:
            del self.line1_widget
        if self.line2_widget:
            del self.line2_widget
        if self.text_actor:
            image_viewer.renderer.RemoveActor(self.text_actor)
            del self.text_actor
        for actor in self.point_actors:
            image_viewer.renderer.RemoveActor(actor)
        self.point_actors.clear()


class TriangleObject(ToolObjectAbstract):
    def __init__(self, triangle_actor=None, triangle_points=None, triangle_tip=None, default_color=None):
        self.triangle_actor = triangle_actor
        self.triangle_points = triangle_points
        self.triangle_tip = triangle_tip
        self.default_color = default_color

    def On(self):
        self.triangle_actor.SetVisibility(True)

    def Off(self):
        self.triangle_actor.SetVisibility(False)

    def get_widget(self):
        return self.triangle_actor

    def change_color(self, color):
        self.triangle_actor.GetProperty().SetColor(color)

    def get_position_world(self):
        return self.triangle_points.GetBounds()

    def delete_widget(self, image_viewer):
        self.Off()
        triangle_actor = self.get_widget()
        image_viewer.renderer.RemoveActor(triangle_actor)
        del triangle_actor


class ArrowObject(ToolObjectAbstract):
    def __init__(self, arrow_widget, triangle_object: TriangleObject, default_color):
        self.arrow_widget = arrow_widget
        self.triangle_object = triangle_object
        self.default_color = default_color

    def On(self):
        self.arrow_widget.On()
        self.triangle_object.On()

    def Off(self):
        self.arrow_widget.Off()
        self.triangle_object.Off()

    def get_widget(self):
        return self.arrow_widget, self.triangle_object

    def change_color(self, color):
        self.arrow_widget.GetRepresentation().GetLineProperty().SetColor(color)
        self.triangle_object.change_color(color)

    def get_position_world(self):
        # دریافت نقاط خط
        arrow_widget, triangle_actor = self.get_widget()
        repr = arrow_widget.GetRepresentation()
        point1_world = [0, 0, 0]
        point2_world = [0, 0, 0]
        repr.GetPoint1WorldPosition(point1_world)
        repr.GetPoint2WorldPosition(point2_world)

        # return (point1_world, point2_world), self.triangle_object.get_position_world()
        return point1_world, point2_world

    def delete_widget(self, image_viewer):
        self.Off()

        # delete arrow
        arrow_widget, triangle_object = self.get_widget()
        triangle_object.delete_widget(image_viewer)
        del triangle_object
        del arrow_widget


class TextObject(ToolObjectAbstract):
    def __init__(self, text_actor, default_color):
        self.text_actor = text_actor
        self.default_color = default_color

    def On(self):
        self.text_actor.SetVisibility(True)

    def Off(self):
        self.text_actor.SetVisibility(False)

    def get_widget(self):
        return self.text_actor

    def change_color(self, color):
        self.text_actor.GetProperty().SetColor(color)

    def get_position_world(self):
        x_min, x_max, y_min, y_max, z_min, z_max = self.text_actor.GetBounds()
        bottom_left = (x_min, y_min, z_min)
        bottom_right = (x_max, y_min, z_min)
        up_right = (x_max, y_max, z_min)
        up_left = (x_min, y_max, z_min)
        # return self.text_actor.GetPosition()
        return bottom_left, bottom_right, up_right, up_left

    def delete_widget(self, image_viewer):
        self.Off()
        text_actor = self.get_widget()
        image_viewer.renderer.RemoveActor(text_actor)
        del text_actor


class TextActor2DObject(ToolObjectAbstract):
    def __init__(self, text_actor, default_color):
        self.text_actor = text_actor
        self.default_color = default_color

    def On(self):
        self.text_actor.SetVisibility(True)

    def Off(self):
        self.text_actor.SetVisibility(False)

    def get_widget(self):
        return self.text_actor

    def change_color(self, color):
        if hasattr(self.text_actor, 'GetTextProperty'):
            self.text_actor.GetTextProperty().SetColor(color)
        elif hasattr(self.text_actor, 'GetProperty'):
            self.text_actor.GetProperty().SetColor(color)

    def get_position_world(self):
        return self.text_actor.GetPosition()

    def delete_widget(self, image_viewer):
        self.Off()
        text_actor = self.get_widget()
        try:
            image_viewer.renderer.RemoveActor2D(text_actor)
        except Exception:
            pass
        try:
            image_viewer.renderer.RemoveViewProp(text_actor)
        except Exception:
            image_viewer.renderer.RemoveActor(text_actor)
        del text_actor


class RoiObject(ToolObjectAbstract):
    def __init__(self, roi_widget, text_object: TextObject, default_color):
        self.roi_widget = roi_widget
        self.text_object = text_object
        self.default_color = default_color

    def On(self):
        self.roi_widget.On()
        self.text_object.On()

    def Off(self):
        self.roi_widget.Off()
        self.text_object.Off()

    def get_widget(self):
        return self.roi_widget, self.text_object

    def change_color(self, color):
        self.roi_widget.repr.GetLinesProperty().SetColor(color)
        self.text_object.change_color(color)

    def get_position_world(self):
        """
        لیست نقاط ابتدا و انتهای هر خط را به صورت [(p0,p1), (p1,p2), ..., (pn,p0)] می‌دهد
        هر زوج یک خط روی کانتور است.
        """
        roi_widget, text_object = self.get_widget()

        num_nodes = roi_widget.repr.GetNumberOfNodes()
        points = []
        for i in range(num_nodes):
            pos = [0.0, 0.0, 0.0]
            roi_widget.repr.GetNthNodeWorldPosition(i, pos)
            points.append(tuple(pos))

        line_pairs = []
        for i in range(num_nodes):
            start = points[i]
            end = points[(i + 1) % num_nodes]  # به آخرین رأس رسیدی، به اولی وصل می‌شود
            line_pairs.append((start, end))
        return line_pairs

    def delete_widget(self, image_viewer):
        self.Off()

        # delete arrow
        roi_widget, text_object = self.get_widget()
        text_object.delete_widget(image_viewer)
        del text_object
        del roi_widget

        # arrow_actor = self.get_widget()
        # image_viewer.renderer.RemoveActor(arrow_actor)
        # del arrow_actor


class CircleRoiObject(ToolObjectAbstract):
    def __init__(self, circle_widget, text_object: TextObject, default_color):
        self.circle_widget = circle_widget
        self.text_object = text_object
        self.default_color = default_color

    def On(self):
        if self.circle_widget:
            self.circle_widget.On()
        self.text_object.On()

    def Off(self):
        if self.circle_widget:
            self.circle_widget.Off()
        self.text_object.Off()

    def get_widget(self):
        return self.circle_widget, self.text_object

    def change_color(self, color):
        try:
            if hasattr(self.circle_widget, 'set_color'):
                self.circle_widget.set_color(color)
            else:
                repr_obj = self.circle_widget.GetRepresentation()
                if hasattr(repr_obj, 'GetEllipseProperty'):
                    repr_obj.GetEllipseProperty().SetColor(color)
                elif hasattr(repr_obj, 'GetProperty'):
                    repr_obj.GetProperty().SetColor(color)
        except Exception:
            pass
        self.text_object.change_color(color)

    def _get_polydata(self):
        try:
            if self.circle_widget and hasattr(self.circle_widget, 'get_polydata'):
                return self.circle_widget.get_polydata()
            repr_obj = self.circle_widget.GetRepresentation() if self.circle_widget else None
            poly = vtk.vtkPolyData()
            if repr_obj and hasattr(repr_obj, 'GetPolyData'):
                repr_obj.GetPolyData(poly)
                return poly
            if self.circle_widget and hasattr(self.circle_widget, 'GetPolyData'):
                self.circle_widget.GetPolyData(poly)
                return poly
        except Exception:
            return None
        return None

    def get_position_world(self):
        """
        Return circle edges as line segment pairs, similar to ROI polygon.
        """
        poly = self._get_polydata()
        if poly is None or poly.GetNumberOfPoints() < 2:
            return []

        points = [poly.GetPoint(i) for i in range(poly.GetNumberOfPoints())]
        line_pairs = []
        for i in range(len(points)):
            start = points[i]
            end = points[(i + 1) % len(points)]
            line_pairs.append((start, end))
        return line_pairs

    def delete_widget(self, image_viewer):
        self.Off()
        circle_widget, text_object = self.get_widget()
        text_object.delete_widget(image_viewer)
        del text_object
        if circle_widget is not None:
            if hasattr(circle_widget, 'cleanup'):
                circle_widget.cleanup()
            del circle_widget


class PolygonSegmentationObject(ToolObjectAbstract):
    def __init__(self, polygon_widget):
        self.polygon_widget = polygon_widget

    def On(self):
        self.polygon_widget.On()

    def Off(self):
        self.polygon_widget.Off()

    def get_widget(self):
        return self.polygon_widget

    def change_color(self, color):
        pass

    def get_position_world(self):
        pass

    def delete_widget(self, image_viewer):
        pass