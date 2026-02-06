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

    def _create_handle_widget(self, color):
        rep = vtk.vtkPointHandleRepresentation2D()
        rep.GetProperty().SetColor(color)
        rep.GetProperty().SetLineWidth(2)
        rep.SetHandleSize(10)

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
        pos = [0.0, 0.0, 0.0]
        if hasattr(rep, 'GetDisplayPosition'):
            rep.GetDisplayPosition(pos)
        return pos

    def _set_handle_world_position(self, handle, position):
        rep = handle.GetRepresentation()
        if hasattr(rep, 'SetWorldPosition'):
            rep.SetWorldPosition(position)

    def _on_handle_interaction(self, obj, event, calldata=None):
        if obj == self.center_handle:
            new_center = self._get_handle_world_position(self.center_handle)
            self.set_center(new_center)
        elif obj == self.radius_handle:
            new_pos = self._get_handle_world_position(self.radius_handle)
            self.set_radius(self._distance(self.center, new_pos))

        self._update_handles()
        if self._on_changed:
            self._on_changed()
        self.image_viewer.Render()

    def set_center(self, center):
        self.center = [float(center[0]), float(center[1]), float(center[2])]
        self.source.SetCenter(self.center)
        self.source.Update()

    def set_radius(self, radius):
        self.radius = max(0.0, float(radius))
        self.source.SetRadius(self.radius)
        self.source.Update()
        self._update_handles()

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
            radius_pos = [self.center[0] + (self.radius * 1.1), self.center[1], self.center[2]]
        self._set_handle_world_position(self.radius_handle, radius_pos)

    def is_handle_hit(self, display_x: float, display_y: float, tolerance_px: float = 8.0) -> bool:
        for handle in (self.center_handle, self.radius_handle):
            try:
                if hasattr(handle, 'GetEnabled') and not handle.GetEnabled():
                    continue
                pos = self._get_handle_display_position(handle)
                dx = float(display_x) - float(pos[0])
                dy = float(display_y) - float(pos[1])
                if (dx * dx + dy * dy) <= (tolerance_px * tolerance_px):
                    return True
            except Exception:
                continue
        return False


class RoiInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.color = (240, 230, 140)
        self.color = list(map(lambda x: x/255.0, self.color))

        self.active_widget = self.create_contour_widget()
        self.active_widget.Off()

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
            try:
                scalar_range = img.GetScalarRange()
            except Exception:
                scalar_range = None

            should_apply = (float(slope) != 1.0) or (float(intercept) != 0.0)
            if should_apply and scalar_range and scalar_range[0] >= 0:
                region_vals = region_vals * float(slope) + float(intercept)
        pixel_area_mm2 = spacing[0] * spacing[1]
        area_mm2 = region_vals.size * pixel_area_mm2
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

    def _is_over_handle(self, mouse_pos) -> bool:
        current_slice = self.image_viewer.GetSlice()
        if current_slice not in self.widgets_by_slice:
            return False

        for obj in self.widgets_by_slice[current_slice]:
            if not hasattr(obj, self.tool_access.CIRCLE_ROI):
                continue
            circle_widget = obj.get_widget()[0]
            if circle_widget.is_handle_hit(mouse_pos[0], mouse_pos[1]):
                return True

        return False

    def on_left_button_press(self, obj, event):
        if not self._drawing:
            mouse_pos = self.GetInteractor().GetEventPosition()
            if self._is_over_handle(mouse_pos):
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
        if self._drawing and self._center_world is not None:
            current_world = self.display_to_world(*self.GetInteractor().GetEventPosition())
            if current_world is None:
                return True
            radius = np.sqrt(
                (current_world[0] - self._center_world[0]) ** 2 +
                (current_world[1] - self._center_world[1]) ** 2 +
                (current_world[2] - self._center_world[2]) ** 2
            )
            self.active_widget.set_radius(radius)
            self.image_viewer.Render()
            return True

        return super().on_mouse_move(obj, event)

    def on_left_button_release(self, obj, event):
        if self._drawing:
            self._drawing = False

            dict_statistics = self._get_statistics_from_circle(self.active_widget.get_center(), self.active_widget.get_radius())
            if dict_statistics is not None:
                text_pos = self.get_pos_text()
                text_actor = self.create_text_actor(text_pos, dict_statistics)
                self.active_widget.set_text_actor(text_actor)
                text_object = TextActor2DObject(text_actor, default_color=self.color)
                self.image_viewer.renderer.AddActor2D(text_actor)

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
