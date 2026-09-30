"""Scoped camera lighting for viewing a surface from inside its lumen."""
import vtk


def configure_lumen_display(display, brightness=55):
    """Apply an explicit interior material, also when restoring older scenes."""
    ambient = max(0.2, min(0.8, float(brightness) / 100.0))
    display.SetSelected(False)
    display.SetScalarVisibility(False)
    display.SetColor(0.94, 0.76, 0.64)
    display.SetBackfaceColorHSVOffset(0, 0, 0)
    display.SetBackfaceCulling(False)
    display.SetFrontfaceCulling(False)
    display.SetLighting(True)
    display.SetAmbient(ambient)
    display.SetDiffuse(0.45)
    display.SetSpecular(0.08)
    display.SetPower(18)
    display.SetOpacity(1.0)


class FlyThroughLight:
    def __init__(self, renderer):
        self.renderer = renderer
        self.two_sided = renderer.GetTwoSidedLighting()
        self.follow_camera = renderer.GetLightFollowCamera()
        collection = renderer.GetLights()
        self.previous = [(collection.GetItemAsObject(i), collection.GetItemAsObject(i).GetSwitch())
                         for i in range(collection.GetNumberOfItems())]
        for light, enabled in self.previous:
            light.SwitchOff()
        self.light = vtk.vtkLight()
        self.light.SetLightTypeToHeadlight()
        self.light.SetIntensity(0.9)
        self.light.SetColor(1.0, 0.97, 0.93)
        self.light.SwitchOn()
        renderer.AddLight(self.light)
        renderer.TwoSidedLightingOn()
        renderer.LightFollowCameraOn()

    def restore(self):
        if self.renderer is None:
            return
        self.renderer.RemoveLight(self.light)
        for light, enabled in self.previous:
            light.SetSwitch(enabled)
        self.renderer.SetTwoSidedLighting(self.two_sided)
        self.renderer.SetLightFollowCamera(self.follow_camera)
        self.renderer = None
