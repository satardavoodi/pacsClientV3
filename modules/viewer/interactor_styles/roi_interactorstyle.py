import vtkmodules.all as vtk
from . import AbstractInteractorStyle
from .tools_object_manager import TextObject, RoiObject, CircleRoiObject, TextActor2DObject
from vtkmodules.util import numpy_support as nps
import numpy as np


class ContourWidget(vtk.vtkContourWidget):
    """
    Customized version of vtkContourWidget.
    Some default behavior has been removed in favor of more user-friendliness.
    """

    def __init__(self, image_viewer, color):
        super(ContourWidget, self).__init__()

        self.repr: vtk.vtkOrientedGlyphContourRepresentation = vtk.vtkOrientedGlyphContourRepresentation()
        self.repr.GetLinesProperty().SetLineWidth(2)
        # self.repr.GetLinesProperty().SetColor(1.0, 0.1, 0.0)  # set polygon line color.
        self.repr.GetLinesProperty().SetColor(color)  # set polygon line color.

        self.SetRepresentation(self.repr)
        self.SetInteractor(image_viewer.image_interactor)  # get interactor from image_viewer
        self.SetModeToPolygon()

        interpolator = vtk.vtkLinearContourLineInterpolator()
        self.repr.SetLineInterpolator(interpolator)

        ###
        placer = vtk.vtkImageActorPointPlacer()
        placer.SetImageActor(image_viewer.GetImageActor())  # get actor from image_viewer
        self.repr.SetPointPlacer(placer)
        ###

        self.closed = False
        self.ClosedForFirstTimeEvent = vtk.vtkCommand.UserEvent + 1
        self.AddObserver(vtk.vtkCommand.EndInteractionEvent, self.OnEndInteraction)
        self.__text_actor = None

    def OnEndInteraction(self, obj, event, calldata=None):
        # print(f'OnEndInteraction')
        if obj.repr.GetClosedLoop() and not self.closed:
            self.closed = True
            self.InvokeEvent(self.ClosedForFirstTimeEvent)
            # Change color of the polygon to red once closed

    def SetModeToPolygon(self):
        # print(f'SetModeToPolygon')
        self.FollowCursorOn()
        self.ContinuousDrawOff()
        self.SetAllowNodePicking(False)

    def set_text_actor(self, text_actor):
        self.__text_actor = text_actor

    def get_text_actor(self):
        return self.__text_actor


class CircleRoiWidget:
    """
    Custom circle ROI widget built from vtkRegularPolygonSource + handle widgets.
    Provides movable and resizable circle on a 2D slice without vtkEllipseWidget.
    """

    def __init__(self, image_viewer, color, sides=64):
        self.image_viewer = image_viewer
        self.renderer = image_viewer.renderer
        self.interactor = image_viewer.image_interactor
        self.color = color
        self.sides = sides

        self.center = [0.0, 0.0, 0.0]
        self.radius = 1.0
        self._radius_direction = [1.0, 0.0, 0.0]
        self._radius_smoothing = 0.25

        self._point_placer = None
        try:
            if hasattr(self.image_viewer, 'GetImageActor'):
                placer = vtk.vtkImageActorPointPlacer()
                placer.SetImageActor(self.image_viewer.GetImageActor())
                self._point_placer = placer
        except Exception:
            self._point_placer = None

        self.source = vtk.vtkRegularPolygonSource()
        self.source.SetNumberOfSides(self.sides)
        self.source.SetCenter(self.center)
        self.source.SetRadius(self.radius)
        self.source.SetNormal(0.0, 0.0, 1.0)
        self.source.Update()

        self.mapper = vtk.vtkPolyDataMapper()
        self.mapper.SetInputConnection(self.source.GetOutputPort())

        self.actor = vtk.vtkActor()
        self.actor.SetMapper(self.mapper)
        self.actor.GetProperty().SetRepresentationToWireframe()
        self.actor.GetProperty().SetLineWidth(2)
        self.actor.GetProperty().SetColor(self.color)
        self.renderer.AddActor(self.actor)

        self.center_handle = self._create_handle_widget(self.color)
        self.radius_handle = self._create_handle_widget(self.color)
        self._set_handle_enabled(self.center_handle, False)
        self._set_handle_enabled(self.radius_handle, False)

        self._on_changed = None
        self.__text_actor = None

        self._update_handles()

    def _distance(self, a, b):
        return float(np.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2))

    def _normalize(self, vec, eps: float = 1e-6):
        length = float(np.sqrt((vec[0] ** 2) + (vec[1] ** 2) + (vec[2] ** 2)))
        if length <= eps:
            return None
        return [vec[0] / length, vec[1] / length, vec[2] / length]

    def _smooth_radius(self, target_radius: float) -> float:
        return float(self.radius + (target_radius - self.radius) * float(self._radius_smoothing))

    def _world_from_display_on_center(self, display_pos, center_world):
        try:
            renderer = self.renderer
            renderer.SetWorldPoint(center_world[0], center_world[1], center_world[2], 1.0)
            renderer.WorldToDisplay()
            ref_display = renderer.GetDisplayPoint()
            renderer.SetDisplayPoint(float(display_pos[0]), float(display_pos[1]), float(ref_display[2]))
            renderer.DisplayToWorld()
            world = renderer.GetWorldPoint()
            if world and world[3] != 0:
                return [world[0] / world[3], world[1] / world[3], world[2] / world[3]]
        except Exception:
            return None
        return None

    def _create_handle_widget(self, color):
        rep = vtk.vtkPointHandleRepresentation2D()
        rep.GetProperty().SetColor(color)
        rep.GetProperty().SetLineWidth(2)
        rep.SetHandleSize(10)
        if self._point_placer is not None:
            try:
                rep.SetPointPlacer(self._point_placer)
            except Exception:
                pass

        handle = vtk.vtkHandleWidget()
        handle.SetInteractor(self.interactor)
        handle.SetRepresentation(rep)
        handle.AddObserver(vtk.vtkCommand.InteractionEvent, self._on_handle_interaction)
        return handle

    def _set_handle_enabled(self, handle, enabled: bool):
        if hasattr(handle, 'EnabledOn') and enabled:
            handle.EnabledOn()
        elif hasattr(handle, 'EnabledOff') and not enabled:
            handle.EnabledOff()
        elif hasattr(handle, 'On') and enabled:
            handle.On()
        elif hasattr(handle, 'Off') and not enabled:
            handle.Off()

    def _get_handle_world_position(self, handle):
        rep = handle.GetRepresentation()
        pos = [0.0, 0.0, 0.0]
        if hasattr(rep, 'GetWorldPosition'):
            rep.GetWorldPosition(pos)
        return pos

    def _get_handle_display_position(self, handle):
        rep = handle.GetRepresentation()
        if hasattr(rep, 'GetDisplayPosition'):
            try:
                return list(rep.GetDisplayPosition())
            except TypeError:
                pos = [0.0, 0.0, 0.0]
                rep.GetDisplayPosition(pos)
                return pos
        return [0.0, 0.0, 0.0]

    def _set_handle_world_position(self, handle, position):
        rep = handle.GetRepresentation()
        if hasattr(rep, 'SetWorldPosition'):
            rep.SetWorldPosition(position)

    def _on_handle_interaction(self, obj, event, calldata=None):
        if obj == self.center_handle:
            display_pos = self._get_handle_display_position(self.center_handle)
            new_center = self._world_from_display_on_center(display_pos, self.center) or \
                self._get_handle_world_position(self.center_handle)
            self.set_center(new_center)
        elif obj == self.radius_handle:
            display_pos = self._get_handle_display_position(self.radius_handle)
            new_pos = self._world_from_display_on_center(display_pos, self.center) or \
                self._get_handle_world_position(self.radius_handle)
            self.set_radius_from_world_position(new_pos, smooth=True)

        self._update_handles()
        self.image_viewer.Render()

    def set_center(self, center):
        self.center = [float(center[0]), float(center[1]), float(center[2])]
        self.source.SetCenter(self.center)
        self.source.Update()
        if self._on_changed:
            self._on_changed()

    def set_radius(self, radius):
        try:
            spacing = self.image_viewer.vtk_image_data.GetSpacing()
            min_spacing = float(min(spacing)) if spacing else 0.0
            collapse_threshold = max(0.0, min_spacing * 0.02)
        except Exception:
            collapse_threshold = 0.0

        radius_val = max(0.0, float(radius))
        if collapse_threshold > 0.0 and radius_val <= collapse_threshold:
            radius_val = 0.0

        self.radius = radius_val
        self.source.SetRadius(self.radius)
        self.source.Update()
        self.actor.SetVisibility(self.radius > 0.0)
        self._update_handles()
        if self._on_changed:
            self._on_changed()

    def set_radius_from_world_position(self, world_position, smooth: bool = False):
        vec = [
            float(world_position[0]) - float(self.center[0]),
            float(world_position[1]) - float(self.center[1]),
            float(world_position[2]) - float(self.center[2]),
        ]
        target_radius = self._distance(self.center, world_position)
        direction = self._normalize(vec)
        if direction is not None:
            self._radius_direction = direction
        if smooth:
            target_radius = self._smooth_radius(target_radius)
        self.set_radius(target_radius)

    def set_on_changed(self, callback):
        self._on_changed = callback

    def set_color(self, color):
        self.color = color
        self.actor.GetProperty().SetColor(color)
        try:
            self.center_handle.GetRepresentation().GetProperty().SetColor(color)
            self.radius_handle.GetRepresentation().GetProperty().SetColor(color)
        except Exception:
            pass

    def On(self):
        self.actor.SetVisibility(True)
        self._set_handle_enabled(self.center_handle, True)
        self._set_handle_enabled(self.radius_handle, True)

    def Off(self):
        self.actor.SetVisibility(False)
        self._set_handle_enabled(self.center_handle, False)
        self._set_handle_enabled(self.radius_handle, False)

    def set_handles_enabled(self, enabled: bool):
        self._set_handle_enabled(self.center_handle, enabled)
        self._set_handle_enabled(self.radius_handle, enabled)

    def get_polydata(self):
        return self.source.GetOutput()

    def get_center(self):
        return list(self.center)

    def get_radius(self):
        return float(self.radius)

    def set_text_actor(self, text_actor):
        self.__text_actor = text_actor

    def get_text_actor(self):
        return self.__text_actor

    def cleanup(self):
        try:
            if self.renderer and self.actor:
                self.renderer.RemoveActor(self.actor)
        except Exception:
            pass
        try:
            self._set_handle_enabled(self.center_handle, False)
            self._set_handle_enabled(self.radius_handle, False)
        except Exception:
            pass

    def _update_handles(self):
        self._set_handle_world_position(self.center_handle, self.center)
        if self.radius <= 0.0:
            radius_pos = [self.center[0], self.center[1], self.center[2]]
        else:
            radius_pos = [
                self.center[0] + (self.radius * self._radius_direction[0]),
                self.center[1] + (self.radius * self._radius_direction[1]),
                self.center[2] + (self.radius * self._radius_direction[2]),
            ]
        self._set_handle_world_position(self.radius_handle, radius_pos)

    def is_handle_hit(self, display_x: float, display_y: float, tolerance_px: float = 8.0) -> bool:
        return self.get_handle_hit_type(display_x, display_y, tolerance_px) is not None

    def get_handle_hit_type(self, display_x: float, display_y: float, tolerance_px: float = 8.0) -> str | None:
        handle_map = (
            (self.center_handle, 'center'),
            (self.radius_handle, 'radius'),
        )
        for handle, handle_name in handle_map:
            try:
                if hasattr(handle, 'GetEnabled') and not handle.GetEnabled():
                    continue
                pos = self._get_handle_display_position(handle)
                dx = float(display_x) - float(pos[0])
                dy = float(display_y) - float(pos[1])
                if (dx * dx + dy * dy) <= (tolerance_px * tolerance_px):
                    return handle_name
            except Exception:
                continue
        return None


class RoiInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.color = (240, 230, 140)
        self.color = list(map(lambda x: x/255.0, self.color))

        self.active_widget = self.create_contour_widget()
        self.active_widget.Off()
        self._dragging_obj = None
        self._drag_start_world = None
        self._drag_start_nodes = None
        self._hover_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1

    def get_statistics(self, obj: ContourWidget):
        spacing = self.image_viewer.vtk_image_data.GetSpacing()
        # slope = self.image_viewer.metadata['meta_fixed']['rescale_slope']
        # intercept = self.image_viewer.metadata['meta_fixed']['rescale_intercept']

        # get polydata
        polydata = obj.repr.GetContourRepresentationAsPolyData()

        # create mask from polydata
        stencil = vtk.vtkPolyDataToImageStencil()
        stencil.SetInputData(polydata)
        stencil.SetOutputSpacing(self.image_viewer.vtk_image_data.GetSpacing())
        stencil.SetOutputOrigin(self.image_viewer.vtk_image_data.GetOrigin())
        stencil.SetOutputWholeExtent(self.image_viewer.vtk_image_data.GetExtent())
        stencil.Update()

        # calculate statistics
        image_stencil = vtk.vtkImageStencil()
        image_stencil.SetInputData(self.image_viewer.vtk_image_data)
        image_stencil.SetStencilConnection(stencil.GetOutputPort())
        image_stencil.ReverseStencilOff()
        image_stencil.SetBackgroundValue(0)
        # image_stencil.UpdateExtent(self.image_viewer.vtk_image_data.GetExtent())
        image_stencil.Update()

        arr = nps.vtk_to_numpy(image_stencil.GetOutput().GetPointData().GetScalars())
        region = arr[arr > 0]  # region = just section in region

        # scaled_region = region * slope + intercept
        scaled_region = region
        if scaled_region.size > 0:

            # area
            pixel_area_mm2 = spacing[0] * spacing[1]
            area_mm2 = scaled_region.size * pixel_area_mm2
            area_cm2 = area_mm2 / 100.0

            mean = np.mean(scaled_region)
            std = np.std(scaled_region)
            _min = np.min(scaled_region)
            _max = np.max(scaled_region)
            _sum = np.sum(scaled_region)

            dict_statistics = {'mean': mean, 'std': std, 'min': _min, 'max': _max, 'sum': _sum, 'area': area_cm2}
            return dict_statistics

    def get_pos_text(self, obj: ContourWidget):
        num_nodes = obj.repr.GetNumberOfNodes()
        point_min_pos = [0.0, float('inf'), 0.0]

        for i in range(num_nodes):
            pos = [0.0, 0.0, 0.0]
            obj.repr.GetNthNodeWorldPosition(i, pos)
            if pos[1] < point_min_pos[1]:

                point_min_pos[0] = pos[0]
                point_min_pos[1] = pos[1]
                point_min_pos[2] = pos[2]

        point_min_pos[1] -= 10
        return point_min_pos

    def create_contour_widget(self):
        widget = ContourWidget(self.image_viewer, self.color)
        widget.AddObserver(widget.ClosedForFirstTimeEvent, self.on_contour_closed)
        widget.AddObserver(vtk.vtkCommand.StartInteractionEvent, self.on_interaction_start)
        widget.AddObserver(vtk.vtkCommand.InteractionEvent, self.on_interaction)
        widget.On()
        return widget

    def on_contour_closed(self, obj: ContourWidget, event, calldata=None):
        # print('on_contour_closed')
        # تعداد نقاط کانتور را دریافت می‌کنیم
        # num_nodes = obj.repr.GetNumberOfNodes()
        # # برای هر نقطه، مختصات دنیای آن را دریافت و چاپ می‌کنیم
        # for i in range(num_nodes):
        #     pos = [0.0, 0.0, 0.0]  # برای ذخیره مختصات
        #     obj.repr.GetNthNodeWorldPosition(i, pos)
        #     print(f"Node {i} position: {pos[:2]}")
        # # سایر عملیات مورد نیاز پس از بسته شدن کانتور

        dict_statistics = self.get_statistics(obj)
        text_pos = self.get_pos_text(obj)

        # create roi object
        text_actor = self.create_text_actor(text_pos, dict_statistics)
        self.active_widget.set_text_actor(text_actor)
        text_object = TextObject(text_actor, default_color=self.color)
        self.image_viewer.renderer.AddActor(text_actor)

        roi_object = RoiObject(self.active_widget, text_object, default_color=self.color)
        self.add_object_to_store_widgets(roi_object, self.tool_access.ROI)

        # reset widget
        self.active_widget = self.create_contour_widget()
        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.Render()
        self.auto_deactivate_tool()

    def on_interaction(self, obj: ContourWidget, event, calldata=None):
        # self.active_widget.OnEndInteraction(obj, event)

        text_actor: vtk.vtkFollower = obj.get_text_actor()
        if text_actor:  # if click on widget that exist as before
            # update text-actor pos
            text_pos = self.get_pos_text(obj)
            text_actor.SetPosition(text_pos)

            # update text on text-actor
            dict_statistics = self.get_statistics(obj)
            self.update_text_actor(text_actor, dict_statistics)

    def on_interaction_start(self, obj: ContourWidget, event, calldata=None):
        # print(f'on_interaction_start')
        self.emit_interaction()
        # self.image_viewer.GetMeasurements().AddItem(obj)

    def _set_cursor(self, cursor_type):
        if hasattr(self.image_viewer.image_interactor, 'SetCursor'):
            self.image_viewer.image_interactor.SetCursor(cursor_type)

    def _find_drag_target(self, mouse_pos):
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return None

        closest_obj = None
        min_distance = self._drag_hit_distance_px

        for obj in self.widgets_by_slice[current_slice]:
            if not hasattr(obj, self.tool_access.ROI):
                continue

            line_pairs = obj.get_position_world()
            for start_point, end_point in line_pairs:
                start_display = self.world_to_display(start_point)
                end_display = self.world_to_display(end_point)
                if not start_display or not end_display:
                    continue

                distance, t = self.point_to_line_distance_and_t(mouse_pos, start_display, end_display)
                if distance <= min_distance and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                    min_distance = distance
                    closest_obj = obj
                    break

        if closest_obj is None:
            return None
        return closest_obj

    def _capture_roi_nodes(self, roi_widget):
        nodes = []
        try:
            num_nodes = roi_widget.repr.GetNumberOfNodes()
            for i in range(num_nodes):
                pos = [0.0, 0.0, 0.0]
                roi_widget.repr.GetNthNodeWorldPosition(i, pos)
                nodes.append(list(pos))
        except Exception:
            pass
        return nodes

    def on_left_button_press(self, obj, event):
        mouse_pos = self.GetInteractor().GetEventPosition()
        drag_target = self._find_drag_target(mouse_pos)
        if drag_target is not None:
            roi_widget, _text_obj = drag_target.get_widget()
            self._dragging_obj = drag_target
            self._drag_start_world = self.display_to_world(mouse_pos[0], mouse_pos[1])
            self._drag_start_nodes = self._capture_roi_nodes(roi_widget)
            self._set_cursor(vtk.VTK_CURSOR_HAND)
            return True

        return super().on_left_button_press(obj, event)

    def on_mouse_move(self, obj, event):
        flag_active = super().on_mouse_move(obj, event)
        if flag_active:
            return True

        if self._dragging_obj is not None and self._drag_start_nodes is not None:
            current_pos = self.GetInteractor().GetEventPosition()
            current_world = self.display_to_world(current_pos[0], current_pos[1])
            if current_world is None or self._drag_start_world is None:
                return True

            dx = current_world[0] - self._drag_start_world[0]
            dy = current_world[1] - self._drag_start_world[1]
            dz = current_world[2] - self._drag_start_world[2]

            roi_widget, _text_obj = self._dragging_obj.get_widget()
            for i, node in enumerate(self._drag_start_nodes):
                new_pos = [node[0] + dx, node[1] + dy, node[2] + dz]
                try:
                    roi_widget.repr.SetNthNodeWorldPosition(i, new_pos)
                except Exception:
                    pass

            self.on_interaction(roi_widget, None)
            self.image_viewer.renderer.ResetCameraClippingRange()
            self.image_viewer.Render()
            return True

        hover_target = self._find_drag_target(self.GetInteractor().GetEventPosition())
        if hover_target is not None:
            if self._hover_obj != hover_target:
                self._hover_obj = hover_target
                self._set_cursor(vtk.VTK_CURSOR_HAND)
        else:
            if self._hover_obj is not None:
                self._hover_obj = None
                self._set_cursor(vtk.VTK_CURSOR_ARROW)

        return False

    def on_left_button_release(self, obj, event):
        if self._dragging_obj is not None:
            self._dragging_obj = None
            self._drag_start_world = None
            self._drag_start_nodes = None
            self._set_cursor(vtk.VTK_CURSOR_ARROW)
            return True

        return super().on_left_button_release(obj, event)

    def activate(self, tool=None):
        self.active_widget.On()

    def deactivate(self, tool=None):
        self.active_widget.Off()

    def create_text_actor(self, world_position, dict_statistics: dict):
        _mean = dict_statistics['mean']
        _std = dict_statistics['std']
        _min = dict_statistics['min']
        _max = dict_statistics['max']
        _sum = dict_statistics['sum']
        _area = dict_statistics['area']
        text = (
            f"Mean: {_mean:.2f} US, Std: {_std:.2f} US\n"
            f"Min: {_min:.0f} US, Max: {_max:.0f} US\n"
            f"Sum: {_sum:.0f} US\n"
            f"Area: {_area:.2f} cm * cm"
        )

        text_source = vtk.vtkVectorText()
        text_source.SetText(text)

        # Extrude the text to make it 3D
        text_extrude = vtk.vtkLinearExtrusionFilter()
        text_extrude.SetInputConnection(text_source.GetOutputPort())
        text_extrude.SetExtrusionTypeToNormalExtrusion()
        text_extrude.SetVector(0, 0, 1)
        text_extrude.SetScaleFactor(1)

        # Mapper and actor
        text_mapper = vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_extrude.GetOutputPort())

        text_actor = vtk.vtkFollower()
        text_actor.SetMapper(text_mapper)
        text_actor.SetScale(3, 3, 3)
        text_actor.SetPosition(world_position)
        text_actor.GetProperty().SetColor(self.color)

        return text_actor

    def update_text_actor(self, text_actor, dict_statistics):
        """
        متن داخل text_actor را با مقادیر جدید dict_statistics بروزرسانی می‌کند.
        """
        _mean = dict_statistics['mean']
        _std = dict_statistics['std']
        _min = dict_statistics['min']
        _max = dict_statistics['max']
        _sum = dict_statistics['sum']
        _area = dict_statistics['area']
        text = (
            f"Mean: {_mean:.2f} US, Std: {_std:.2f} US\n"
            f"Min: {_min:.0f} US, Max: {_max:.0f} US\n"
            f"Sum: {_sum:.0f} US\n"
            f"Area: {_area:.2f} cm * cm"
        )

        # به روزرسانی متن text_source
        # فرض بر این است که اولین inputConnection، vtkVectorText است
        # باید به vtkVectorText که داخل pipeline است دسترسی پیدا کنیم
        text_extrude = text_actor.GetMapper().GetInputConnection(0, 0).GetProducer()
        text_source = text_extrude.GetInputConnection(0, 0).GetProducer()

        # حالا متن را آپدیت کن
        text_source.SetText(text)
        text_source.Modified()
        text_extrude.Update()
        text_actor.GetMapper().Update()
        text_actor.Modified()


class CircleRoiInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.color = (240, 230, 140)
        self.color = list(map(lambda x: x/255.0, self.color))

        self.active_widget = self._create_circle_widget()
        self.active_widget.Off()
        self._drawing = False
        self._center_world = None
        self._drag_mode = None  # 'move' | 'resize'
        self._drag_start_world = None
        self._drag_start_center = None
        self._drag_start_radius = None
        self._active_circle_obj = None
        self._hover_circle_obj = None
        self._drag_hit_distance_px = 10
        self._drag_edge_ratio = 0.1

    def _create_circle_widget(self):
        widget = CircleRoiWidget(self.image_viewer, self.color)
        return widget

    def _get_statistics_from_circle(self, center_world, radius_mm: float):
        if center_world is None or radius_mm <= 0:
            return None

        img = self.image_viewer.vtk_image_data
        spacing = img.GetSpacing()
        dims = img.GetDimensions()

        if not hasattr(self.image_viewer, 'world_to_ijk'):
            return None

        center_ijk = self.image_viewer.world_to_ijk(
            center_world[0], center_world[1], center_world[2],
            y_flip=True, clamp=True, as_int=False
        )

        if center_ijk is None:
            return None

        k = int(round(center_ijk[2]))
        if k < 0 or k >= dims[2]:
            return None

        radius_px_x = radius_mm / spacing[0]
        radius_px_y = radius_mm / spacing[1]
        if radius_px_x <= 0 or radius_px_y <= 0:
            return None

        i0 = int(max(0, np.floor(center_ijk[0] - radius_px_x)))
        i1 = int(min(dims[0] - 1, np.ceil(center_ijk[0] + radius_px_x)))
        j0 = int(max(0, np.floor(center_ijk[1] - radius_px_y)))
        j1 = int(min(dims[1] - 1, np.ceil(center_ijk[1] + radius_px_y)))

        scalars = img.GetPointData().GetScalars()
        if scalars is None:
            return None

        arr = nps.vtk_to_numpy(scalars)
        arr = arr.reshape(dims[2], dims[1], dims[0])

        region_vals = []
        for j in range(j0, j1 + 1):
            dy = (j - center_ijk[1]) / radius_px_y
            dy2 = dy * dy
            for i in range(i0, i1 + 1):
                dx = (i - center_ijk[0]) / radius_px_x
                if dx * dx + dy2 <= 1.0:
                    region_vals.append(arr[k, j, i])

        if len(region_vals) == 0:
            return None

        region_vals = np.array(region_vals)

        slope, intercept = self._get_rescale_params()
        if slope is not None and intercept is not None:
            should_apply = (float(slope) != 1.0) or (float(intercept) != 0.0)
            if should_apply:
                region_vals = region_vals * float(slope) + float(intercept)
        area_mm2 = float(np.pi) * (float(radius_mm) ** 2)
        area_cm2 = area_mm2 / 100.0

        dict_statistics = {
            'mean': float(np.mean(region_vals)),
            'std': float(np.std(region_vals)),
            'min': float(np.min(region_vals)),
            'max': float(np.max(region_vals)),
            'sum': float(np.sum(region_vals)),
            'area': float(area_cm2)
        }
        return dict_statistics

    def _get_rescale_params(self) -> tuple[float | None, float | None]:
        viewer = self.image_viewer
        if hasattr(viewer, '_rescale_slope') and hasattr(viewer, '_rescale_intercept'):
            return viewer._rescale_slope, viewer._rescale_intercept

        slope = None
        intercept = None

        try:
            meta_fixed = getattr(viewer, 'metadata_fixed', None) or {}
            slope = meta_fixed.get('rescale_slope', None)
            intercept = meta_fixed.get('rescale_intercept', None)
        except Exception:
            slope = None
            intercept = None

        if slope is None or intercept is None:
            try:
                current_slice = viewer.GetSlice()
                instances = viewer.metadata.get('instances', []) if hasattr(viewer, 'metadata') else []
                if 0 <= current_slice < len(instances):
                    inst_meta = instances[current_slice]
                    slope = inst_meta.get('rescale_slope', slope)
                    intercept = inst_meta.get('rescale_intercept', intercept)
            except Exception:
                pass

        if slope is None or intercept is None:
            try:
                current_slice = viewer.GetSlice()
                instances = viewer.metadata.get('instances', []) if hasattr(viewer, 'metadata') else []
                instance_path = None
                if 0 <= current_slice < len(instances):
                    instance_path = instances[current_slice].get('instance_path')
                if instance_path:
                    import pydicom
                    ds = pydicom.dcmread(str(instance_path), stop_before_pixels=True, force=True)
                    slope = ds.get('RescaleSlope', slope)
                    intercept = ds.get('RescaleIntercept', intercept)
            except Exception:
                pass

        try:
            slope = float(slope) if slope is not None else 1.0
        except Exception:
            slope = 1.0
        try:
            intercept = float(intercept) if intercept is not None else 0.0
        except Exception:
            intercept = 0.0

        viewer._rescale_slope = slope
        viewer._rescale_intercept = intercept
        return slope, intercept

    def get_pos_text(self):
        render_size = self.image_viewer.renderer.GetSize()
        x = 12
        y = 12
        if render_size and len(render_size) >= 2:
            y = max(12, render_size[1] - 24 - 90)
        return x, y

    def _update_widget_text(self, widget: CircleRoiWidget):
        text_actor: vtk.vtkFollower = widget.get_text_actor()
        if not text_actor:
            return

        text_pos = self.get_pos_text()
        if hasattr(text_actor, 'SetDisplayPosition'):
            text_actor.SetDisplayPosition(text_pos[0], text_pos[1])

        dict_statistics = self._get_statistics_from_circle(widget.get_center(), widget.get_radius())
        if dict_statistics:
            self.update_text_actor(text_actor, dict_statistics, widget.get_radius())

    def _get_handle_hit(self, mouse_pos):
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return None

        for obj in self.widgets_by_slice[current_slice]:
            if not hasattr(obj, self.tool_access.CIRCLE_ROI):
                continue
            circle_widget = obj.get_widget()[0]
            hit_type = circle_widget.get_handle_hit_type(mouse_pos[0], mouse_pos[1])
            if hit_type:
                return obj, hit_type

        return None

    def _get_edge_hit(self, mouse_pos):
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return None

        closest_obj = None
        min_distance = self._drag_hit_distance_px

        for obj in self.widgets_by_slice[current_slice]:
            if not hasattr(obj, self.tool_access.CIRCLE_ROI):
                continue
            line_pairs = obj.get_position_world()
            for start_point, end_point in line_pairs:
                start_display = self.world_to_display(start_point)
                end_display = self.world_to_display(end_point)
                if not start_display or not end_display:
                    continue

                distance, t = self.point_to_line_distance_and_t(mouse_pos, start_display, end_display)
                if distance <= min_distance and self.is_middle_segment_hit(t, self._drag_edge_ratio):
                    min_distance = distance
                    closest_obj = obj
                    break

        return closest_obj

    def on_left_button_press(self, obj, event):
        if not self._drawing:
            mouse_pos = self.GetInteractor().GetEventPosition()
            handle_hit = self._get_handle_hit(mouse_pos)
            if handle_hit:
                circle_obj, hit_type = handle_hit
                circle_widget, _text_obj = circle_obj.get_widget()
                self._active_circle_obj = circle_obj
                self._drag_mode = 'move' if hit_type == 'center' else 'resize'
                self._drag_start_world = self.display_to_world(*mouse_pos)
                self._drag_start_center = circle_widget.get_center()
                self._drag_start_radius = circle_widget.get_radius()
                return

            edge_hit = self._get_edge_hit(mouse_pos)
            if edge_hit:
                circle_widget, _text_obj = edge_hit.get_widget()
                self._active_circle_obj = edge_hit
                self._drag_mode = 'move'
                self._drag_start_world = self.display_to_world(*mouse_pos)
                self._drag_start_center = circle_widget.get_center()
                self._drag_start_radius = circle_widget.get_radius()
                return

            self._center_world = self.display_to_world(*mouse_pos)
            if self._center_world is None:
                return
            self.active_widget.set_center(self._center_world)
            self.active_widget.set_radius(1.0)
            self.active_widget.On()
            self._drawing = True
            self.image_viewer.Render()
            return

        super().on_left_button_press(obj, event)

    def on_mouse_move(self, obj, event):
        if not self._drag_mode and not self._drawing:
            mouse_pos = self.GetInteractor().GetEventPosition()
            hover_hit = self._get_edge_hit(mouse_pos)
            if hover_hit is not None:
                if self._hover_circle_obj != hover_hit:
                    self._hover_circle_obj = hover_hit
                    if hasattr(self.image_viewer.image_interactor, 'SetCursor'):
                        self.image_viewer.image_interactor.SetCursor(vtk.VTK_CURSOR_HAND)
            else:
                if self._hover_circle_obj is not None:
                    self._hover_circle_obj = None
                    if hasattr(self.image_viewer.image_interactor, 'SetCursor'):
                        self.image_viewer.image_interactor.SetCursor(vtk.VTK_CURSOR_ARROW)

        if self._drag_mode and self._active_circle_obj:
            display_pos = self.GetInteractor().GetEventPosition()
            circle_widget, _text_obj = self._active_circle_obj.get_widget()
            if self._drag_mode == 'move':
                current_world = circle_widget._world_from_display_on_center(display_pos, self._drag_start_center) or \
                    self.display_to_world(*display_pos)
                if current_world is not None and self._drag_start_world is not None:
                    dx = current_world[0] - self._drag_start_world[0]
                    dy = current_world[1] - self._drag_start_world[1]
                    dz = current_world[2] - self._drag_start_world[2]
                    new_center = [
                        self._drag_start_center[0] + dx,
                        self._drag_start_center[1] + dy,
                        self._drag_start_center[2] + dz,
                    ]
                    circle_widget.set_center(new_center)
                    self._update_widget_text(circle_widget)
                    self.image_viewer.Render()
                    return True
            elif self._drag_mode == 'resize':
                current_world = circle_widget._world_from_display_on_center(display_pos, circle_widget.get_center()) or \
                    self.display_to_world(*display_pos)
                if current_world is not None:
                    circle_widget.set_radius_from_world_position(current_world, smooth=False)
                    self._update_widget_text(circle_widget)
                    self.image_viewer.Render()
                    return True

        if self._drawing and self._center_world is not None:
            display_pos = self.GetInteractor().GetEventPosition()
            current_world = self.active_widget._world_from_display_on_center(display_pos, self._center_world) or \
                self.display_to_world(*display_pos)
            if current_world is None:
                return True
            self.active_widget.set_radius_from_world_position(current_world, smooth=False)
            self.image_viewer.Render()
            return True

        return super().on_mouse_move(obj, event)

    def on_left_button_release(self, obj, event):
        if self._drag_mode:
            self._drag_mode = None
            self._active_circle_obj = None
            self._drag_start_world = None
            self._drag_start_center = None
            self._drag_start_radius = None
            if hasattr(self.image_viewer.image_interactor, 'SetCursor'):
                self.image_viewer.image_interactor.SetCursor(vtk.VTK_CURSOR_ARROW)
            return
        if self._drawing:
            self._drawing = False

            dict_statistics = self._get_statistics_from_circle(self.active_widget.get_center(), self.active_widget.get_radius())
            if dict_statistics is not None:
                text_pos = self.get_pos_text()
                text_actor = self.create_text_actor(text_pos, dict_statistics)
                self.active_widget.set_text_actor(text_actor)
                text_object = TextActor2DObject(text_actor, default_color=self.color)
                self.image_viewer.renderer.AddViewProp(text_actor)

                roi_object = CircleRoiObject(self.active_widget, text_object, default_color=self.color)
                self.add_object_to_store_widgets(roi_object, self.tool_access.CIRCLE_ROI)

                finalized_widget = self.active_widget
                finalized_widget.set_on_changed(lambda w=finalized_widget: self._update_widget_text(w))
                finalized_widget.set_handles_enabled(True)

                self.image_viewer.renderer.ResetCameraClippingRange()
                self.image_viewer.Render()

                self.update_slice()

            self.active_widget = self._create_circle_widget()
            self.active_widget.Off()
            self._center_world = None
            self.auto_deactivate_tool()
            return

        super().on_left_button_release(obj, event)

    def activate(self, tool=None):
        self._drawing = False
        self.active_widget.Off()

    def deactivate(self, tool=None):
        self.active_widget.Off()

    def create_text_actor(self, world_position, dict_statistics: dict):
        _mean = dict_statistics['mean']
        _min = dict_statistics['min']
        _max = dict_statistics['max']
        _area = dict_statistics['area']

        radius = self.active_widget.get_radius()
        perimeter = 2.0 * np.pi * radius

        text = (
            f"Mean: {_mean:.2f} HU\n"
            f"Min: {_min:.0f} HU, Max: {_max:.0f} HU\n"
            f"Perimeter: {perimeter:.2f} mm\n"
            f"Area: {_area:.2f} cm * cm"
        )

        text_actor = vtk.vtkTextActor()
        text_actor.SetInput(text)
        text_actor.GetTextProperty().SetColor(self.color)
        text_actor.GetTextProperty().SetFontSize(14)
        text_actor.GetTextProperty().SetFontFamilyToArial()
        text_actor.GetTextProperty().SetJustificationToLeft()
        text_actor.GetTextProperty().SetVerticalJustificationToTop()
        text_actor.SetDisplayPosition(int(world_position[0]), int(world_position[1]))

        return text_actor

    def update_text_actor(self, text_actor, dict_statistics, radius_mm: float | None = None):
        _mean = dict_statistics['mean']
        _min = dict_statistics['min']
        _max = dict_statistics['max']
        _area = dict_statistics['area']

        radius = radius_mm if radius_mm is not None else 0.0
        perimeter = 2.0 * np.pi * radius

        text = (
            f"Mean: {_mean:.2f} HU\n"
            f"Min: {_min:.0f} HU, Max: {_max:.0f} HU\n"
            f"Perimeter: {perimeter:.2f} mm\n"
            f"Area: {_area:.2f} cm * cm"
        )

        if hasattr(text_actor, 'SetInput'):
            text_actor.SetInput(text)
        text_actor.Modified()
