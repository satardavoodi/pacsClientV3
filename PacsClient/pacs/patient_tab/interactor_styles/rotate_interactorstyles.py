import vtkmodules.all as vtk
from . import AbstractInteractorStyle


class RotateInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer

    def rotation_left(self):
        # self.image_viewer
        camera = self.image_viewer.renderer.GetActiveCamera()
        camera.Roll(90)

    def rotation_right(self):
        camera = self.image_viewer.renderer.GetActiveCamera()
        camera.Roll(-90)

    def flip_horizontal(self):
        camera = self.image_viewer.renderer.GetActiveCamera()
        camera.Azimuth(180)
        # self.flip_horizontal_image(image_actor=self.image_actor)

    def flip_vertical(self):
        camera = self.image_viewer.renderer.GetActiveCamera()
        camera.Roll(180)

    def activate(self, direction):
        if direction == self.tool_access.ROTATION_LEFT:
            self.rotation_left()

        elif direction == self.tool_access.ROTATION_RIGHT:
            self.rotation_right()

        elif direction == self.tool_access.FLIP_HORIZONTAL:
            self.flip_horizontal()

        elif direction == self.tool_access.FLIP_VERTICAL:
            self.flip_vertical()

        # self.image_viewer.renderer.ResetCamera()
        self.image_viewer.renderer.ResetCameraClippingRange()
        self.image_viewer.Render()

    def flip_horizontal_image(self, image_actor):
        center = image_actor.GetCenter()

        # print('flipped:', self.image_viewer.flag_flipped)

        transform = vtk.vtkTransform()
        transform.PostMultiply()  # ترتیب: ترنسفورم‌ها به‌ترتیب اعمال شوند

        # ۱. انتقال به مبدا (مرکز تصویر)
        transform.Translate(-center[0], -center[1], -center[2])
        # ۲. flip افقی حول محور X
        transform.Scale(-1, 1, 1)
        # ۳. برگشت به مکان اولیه
        transform.Translate(center[0], center[1], center[2])

        # flip نشده: ترنسفورم را اضافه کن
        if not self.image_viewer.flag_flipped:

            image_actor.SetUserTransform(transform)

            lst_actors = self.image_viewer.renderer.GetActors()
            for actor in lst_actors:
                actor.SetUserTransform(transform)

            self.image_viewer.flag_flipped = True


        # اگر قبلاً flipped بوده، به حالت اولیه برگردان
        else:
            self.image_actor.SetUserTransform(None)

            lst_actors = self.image_viewer.renderer.GetActors()
            for actor in lst_actors:
                actor.SetUserTransform(None)

            self.image_viewer.flag_flipped = False

        # صحنه را دوباره رندر کن
        self.image_viewer.Render()

    def new_flip_actor(self, image_actor):
        center = image_actor.GetCenter()

        transform = vtk.vtkTransform()
        transform.PostMultiply()

        transform.Translate(-center[0], -center[1], -center[2])
        transform.Scale(-1, 1, 1)
        transform.Translate(center[0], center[1], center[2])

        lst_actors = self.image_viewer.renderer.GetActors()
        for actor in lst_actors:
            actor.SetUserTransform(transform)

        self.image_viewer.Render()
