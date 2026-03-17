import vtkmodules.all as vtk
from PySide6.QtWidgets import QInputDialog
from . import AbstractInteractorStyle
from .tools_object_manager import TextObject


class TextInteractorStyle(AbstractInteractorStyle):
    """
    Adds a 3D text label to the scene that follows the camera.
    """

    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer

        self.text_actor = None
        self.is_active = False
        self.color = (0.7, 0.3, 0.3)
        self.text_size_px = 16
        self.interactor_name = self.tool_access.TEXT


    def activate(self, tool=None):
        """
        Add the 3D text to the scene.
        """
        if not self.is_active:
            self.is_active = True
            # self.add_3d_text()
            # print("3D text activated")
            self.image_viewer.Render()

    def deactivate(self, tool=None):
        """
        Remove the 3D text from the scene.
        """
        if self.is_active:
            self.is_active = False
            # if self.text_actor:
            #     self.image_viewer.renderer.RemoveActor(self.text_actor)
            # print("3D text deactivated")
            self.image_viewer.Render()

    def add_3d_text(self):
        """
        Create a 3D text follower and add it to the renderer.
        """
        text_source = vtk.vtkVectorText()
        text_source.SetText("Hello World")  # متن فارسی ممکن است نیاز به روش دیگر داشته باشد

        # Extrude the text to make it 3D
        text_extrude = vtk.vtkLinearExtrusionFilter()
        text_extrude.SetInputConnection(text_source.GetOutputPort())
        text_extrude.SetExtrusionTypeToNormalExtrusion()
        text_extrude.SetVector(0, 0, 1)
        text_extrude.SetScaleFactor(1)

        # Mapper and actor
        text_mapper = vtk.vtkPolyDataMapper()
        text_mapper.SetInputConnection(text_extrude.GetOutputPort())

        self.text_actor = vtk.vtkFollower()
        self.text_actor.SetMapper(text_mapper)
        self.text_actor.SetScale(5, 5, 5)
        self.text_actor.SetPosition(0, 0, 0)
        self.text_actor.GetProperty().SetColor(self.color)  # Yellow

        # Make text follow camera
        camera = self.image_viewer.renderer.GetActiveCamera()
        self.text_actor.SetCamera(camera)

        self.image_viewer.renderer.AddActor(self.text_actor)

    def on_left_button_press(self, obj, event):
        text, ok = QInputDialog.getText(None, "Enter Text", "Text:")

        display_position = self.GetInteractor().GetEventPosition()
        world_position = self.display_to_world(display_position[0], display_position[1])

        text_actor = self.create_text_actor(text, world_position)
        self.image_viewer.renderer.AddActor(text_actor)

        # create text object
        text_object = TextObject(text_actor, default_color=self.color)
        self.add_object_to_store_widgets(text_object, self.tool_access.TEXT)

        # set text on clipping camera
        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.Render()
        self.is_active = False
        self.auto_deactivate_tool()

    def create_text_actor(self, text, world_position):
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
        text_actor.SetPosition(world_position)
        text_actor.GetProperty().SetColor(self.color)

        try:
            text_actor.GetMapper().Update()
            bounds = text_actor.GetBounds()
            if bounds is not None:
                height = bounds[3] - bounds[2]
                if height > 0:
                    target_world_height = self.world_length_from_pixels(world_position, self.text_size_px, axis='y')
                    if target_world_height > 0:
                        scale = float(target_world_height) / float(height)
                        text_actor.SetScale(scale, scale, scale)
        except Exception:
            text_actor.SetScale(5, 5, 5)

        # Make text follow camera
        # camera = self.image_viewer.renderer.GetActiveCamera()
        # text_actor.SetCamera(camera)
        # text_actor.Modified()


        return text_actor








