import vtkmodules.all as vtk
from . import AbstractInteractorStyle
from .tools_object_manager import TextObject, RoiObject
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
