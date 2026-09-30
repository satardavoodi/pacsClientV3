"""Exercise the real panel callback without importing the Slicer GUI runtime."""
import ast
from pathlib import Path
from types import SimpleNamespace


def callback(name, namespace):
    source = Path("modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/workspace.py")
    tree = ast.parse(source.read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), "exec"), namespace)
    return namespace[name]


def test_place_endpoints_keeps_line_class_instead_of_creating_fiducials():
    state = {}
    selection = SimpleNamespace(
        SetReferenceActivePlaceNodeClassName=lambda value: state.update(node_class=value),
        SetActivePlaceNodeID=lambda value: state.update(node_id=value))
    interaction = SimpleNamespace(Place=1,
        SetPlaceModePersistence=lambda value: state.update(persistent=value),
        SetCurrentInteractionMode=lambda value: state.update(mode=value))
    seeds = SimpleNamespace(RemoveAllControlPoints=lambda: state.update(count=0),
                            GetID=lambda: "owned-line", GetClassName=lambda: "vtkMRMLMarkupsLineNode",
                            CreateDefaultDisplayNodes=lambda: None)
    # This is the documented native StartPlaceMode behavior, even after SetActiveListID.
    logic = SimpleNamespace(
        SetActiveListID=lambda node: state.update(node_class=node.GetClassName(), node_id=node.GetID()),
        StartPlaceMode=lambda persistent: state.update(node_class="vtkMRMLMarkupsFiducialNode"))
    slicer = SimpleNamespace(modules=SimpleNamespace(markups=SimpleNamespace(logic=lambda: logic)),
        app=SimpleNamespace(applicationLogic=lambda: SimpleNamespace(
            GetSelectionNode=lambda: selection, GetInteractionNode=lambda: interaction)))
    widget = SimpleNamespace(parameter=SimpleNamespace(GetNodeReference=lambda role: seeds),
        status=SimpleNamespace(text=""), editor=SimpleNamespace(setActiveEffectByName=lambda value: None),
        updateRouteStatus=lambda *args: None)
    callback("placeEndpoints", {"slicer": slicer})(widget)
    assert state["node_class"] == "vtkMRMLMarkupsLineNode"
    assert state["node_id"] == "owned-line"
    assert state["persistent"] == 1 and state["mode"] == 1


def test_route_counter_uses_defined_points_not_preview_positions():
    count = [0]
    node = SimpleNamespace(GetNumberOfDefinedControlPoints=lambda: count[0])
    widget = SimpleNamespace(parameter=SimpleNamespace(GetNodeReference=lambda role: node),
                             routeStatus=SimpleNamespace(text=""))
    update = callback("updateRouteStatus", {})
    for value in (0, 1, 2):
        count[0] = value
        update(widget)
        assert f"{value} / 2" in widget.routeStatus.text
        assert ("Ready to compute" in widget.routeStatus.text) == (value == 2)


def test_restored_bronchoscopy_reapplies_interior_material():
    import numpy as np
    material = {}
    display = SimpleNamespace(**{name: (lambda *value, key=name: material.update({key: value}))
        for name in ("SetAmbient", "SetDiffuse", "SetColor", "SetSelected", "SetScalarVisibility",
                     "SetBackfaceColorHSVOffset", "SetBackfaceCulling", "SetFrontfaceCulling",
                     "SetLighting", "SetSpecular", "SetPower", "SetOpacity")})
    nodes = {"path": object(), "measurements": SimpleNamespace(GetNumberOfRows=lambda: 2),
             "surface": SimpleNamespace(GetPolyData=lambda: object(), GetDisplayNode=lambda: display)}
    widget = SimpleNamespace(mode="bronchoscopy", parameter=SimpleNamespace(
        GetParameter=lambda key: "true", GetNodeReference=lambda key: nodes[key]),
        position=SimpleNamespace(setRange=lambda *args: None),
        wallBrightness=SimpleNamespace(value=55))
    namespace = {"np": np, "slicer": SimpleNamespace(util=SimpleNamespace(
        arrayFromMarkupsControlPoints=lambda *args, **kwargs: np.array([[0,0,0],[0,0,1]]),
        arrayFromTableColumn=lambda *args: np.array([0.,1.]))),
        "path_frames": lambda points: (points.copy(), points.copy())}
    import importlib.util
    spec = importlib.util.spec_from_file_location("material_probe",
        Path("modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/lighting.py"))
    lighting = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lighting)
    if hasattr(lighting, "configure_lumen_display"):
        namespace["configure_lumen_display"] = lighting.configure_lumen_display
    callback("restoreResult", namespace)(widget)
    assert material.get("SetAmbient", (0,))[0] >= .5
    assert material["SetBackfaceColorHSVOffset"] == (0, 0, 0)
    assert material["SetScalarVisibility"] == (False,)


def test_flythrough_lights_interior_despite_dim_external_scene_lights():
    import numpy as np
    import vtk
    from vtk.util.numpy_support import vtk_to_numpy
    renderer = vtk.vtkRenderer()
    renderer.AutomaticLightCreationOff()
    renderer.TwoSidedLightingOff()
    external = vtk.vtkLight()
    external.SetLightTypeToSceneLight()
    external.SetIntensity(0.05)
    external.SetPosition(0, 0, -50)
    external.SetFocalPoint(0, 0, 0)
    renderer.AddLight(external)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(80, 80)
    window.AddRenderer(renderer)
    sphere = vtk.vtkSphereSource()
    sphere.SetRadius(10)
    sphere.SetThetaResolution(48)
    sphere.SetPhiResolution(48)
    mapper = vtk.vtkPolyDataMapper()
    mapper.SetInputConnection(sphere.GetOutputPort())
    actor = vtk.vtkActor()
    actor.SetMapper(mapper)
    actor.GetProperty().SetColor(.9, .68, .55)
    renderer.AddActor(actor)
    camera = renderer.GetActiveCamera()
    cameraNode = SimpleNamespace(GetCamera=lambda: camera, GetID=lambda: "synthetic-camera")
    view = SimpleNamespace(scheduleRender=lambda: None, renderWindow=lambda: window, renderer=lambda: renderer)
    layout = SimpleNamespace(sliceViewNames=lambda: [], threeDViewCount=1,
        threeDWidget=lambda index: SimpleNamespace(mrmlViewNode=lambda: None, threeDView=lambda: view))
    slicer = SimpleNamespace(app=SimpleNamespace(layoutManager=lambda: layout),
        modules=SimpleNamespace(cameras=SimpleNamespace(logic=lambda: SimpleNamespace(
            GetViewActiveCameraNode=lambda node: cameraNode))))
    widget = SimpleNamespace(result={"points": np.array([[0,0,0]]), "tangents": np.array([[0,0,1]]),
        "ups": np.array([[0,1,0]]), "area": np.array([1.]), "diameter": np.array([1.]), "distance": np.array([0.])},
        measurement=SimpleNamespace(text=""), mode="bronchoscopy", camera_backup=None,
        reverse=SimpleNamespace(checked=False), angle=SimpleNamespace(value=90), flyLight=None)
    namespace = {"np": np, "vtk": vtk, "slicer": slicer}
    import importlib.util
    spec = importlib.util.spec_from_file_location("lumen_lighting_probe",
        Path("modules/mpr/advanced_3d_slicer/slicer_modules/aipacs_lumen/lighting.py"))
    lighting = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lighting)
    namespace["FlyThroughLight"] = lighting.FlyThroughLight
    try:
        callback("navigate", namespace)(widget, 0)
        window.Render()
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.Update()
        assert vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).mean() > 45
        widget.flyLight.restore()
        assert not renderer.GetTwoSidedLighting()
        assert renderer.GetLights().GetNumberOfItems() == 1
        assert external.GetSwitch()
    finally:
        window.Finalize()
