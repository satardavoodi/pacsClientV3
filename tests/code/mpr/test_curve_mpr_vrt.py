"""Synthetic non-dental CPR volume and toolbar restoration guards."""
import ast
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import vtkmodules.all as vtk
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from PySide6.QtWidgets import QApplication, QWidget, QGridLayout
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_core import CurveMPRCore


def toolbar_method(name):
    path = Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py')
    tree = ast.parse(path.read_text(encoding='utf-8'))
    method = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), ns)
    return ns[name]


def test_curve_toggle_restores_original_and_clears_crosslink():
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    layout = QGridLayout(parent)
    original, curve = QWidget(parent), QWidget(parent)
    original._curve_mpr_widget = curve
    original._mpr_grid_position = (0, 0, 1, 1)
    curve._original_widget = original
    calls = []
    curve.cleanup = lambda: calls.append('cleanup')
    layout.addWidget(curve, 0, 0)
    toolbar_method('_restore_selected_viewer')(SimpleNamespace(), original)
    assert calls == ['cleanup']
    assert not hasattr(original, '_curve_mpr_widget')
    assert layout.indexOf(curve) == -1
    assert layout.itemAtPosition(0, 0).widget() is original
    parent.close()


def test_straightened_volume_retains_physical_spacing_and_centerline():
    image = vtk.vtkImageData()
    image.SetDimensions(41, 41, 41)
    image.SetOrigin(-20, -20, -20)
    z, y, x = np.mgrid[-20:21, -20:21, -20:21]
    image.GetPointData().SetScalars(numpy_to_vtk((x + 10*y + 100*z).astype(np.float32).ravel(), deep=True))
    core = CurveMPRCore(image)
    core.add_control_point((-10, 0, 0))
    core.add_control_point((10, 0, 0))
    output = core.generate_straightened_volume(physical_width=4, step=1)
    assert output.GetDimensions() == (21, 5, 5)
    assert output.GetSpacing() == (1, 1, 1)
    assert output.GetOrigin() == (0, -2, -2)
    values = vtk_to_numpy(output.GetPointData().GetScalars()).reshape(5, 5, 21)
    np.testing.assert_allclose(values[2, 2], np.arange(-10, 11), atol=1e-5)
    # For this line the unchanged transport frame is N=-Y, B=-Z.
    assert values[0, 2, 0] == 190
    assert values[0, 0, 0] < -30000  # Outside the circular tube.
    assert image.GetOrigin() == (-20, -20, -20)


def test_straightened_volume_cancels_before_allocating():
    from threading import Event
    event = Event()
    event.set()
    core = CurveMPRCore(vtk.vtkImageData())
    core.add_control_point((0, 0, 0))
    core.add_control_point((10000, 0, 0))
    assert core.generate_straightened_volume(cancelled=event) is None


def test_bent_path_center_samples_and_outside_air():
    image = vtk.vtkImageData()
    image.SetDimensions(31, 31, 31)
    image.SetOrigin(-15, -15, -15)
    z, y, x = np.mgrid[-15:16, -15:16, -15:16]
    image.GetPointData().SetScalars(numpy_to_vtk((x + 10*y + 100*z).astype(np.float32).ravel(), deep=True))
    core = CurveMPRCore(image)
    for point in [(-8, -3, -1), (0, 5, 2), (8, -2, 0)]:
        core.add_control_point(point)
    output = core.generate_straightened_volume(physical_width=4, step=1)
    width = output.GetDimensions()[0]
    targets = np.linspace(0, core.total_length, width)
    points = np.asarray(core.spline_points)
    expected = sum(scale * np.interp(targets, core.arc_lengths, points[:, axis])
                   for axis, scale in enumerate((1, 10, 100)))
    pixels = vtk_to_numpy(output.GetPointData().GetScalars()).reshape(5, 5, width)
    np.testing.assert_allclose(pixels[2, 2], expected, atol=1e-4)
    core.clear_points()
    core.add_control_point((100, 0, 0))
    core.add_control_point((105, 0, 0))
    outside = core.generate_straightened_volume(physical_width=4, step=1)
    assert np.all(vtk_to_numpy(outside.GetPointData().GetScalars()) <= -1024)


def test_curve_host_is_discovered_for_patient_tab_cleanup():
    from modules.mpr.zeta_mpr.mpr_viewer._mpr_lifecycle import find_mpr_viewers
    curve = SimpleNamespace(_mpr_closed=False, cleanup=lambda: None)
    assert find_mpr_viewers(SimpleNamespace(_curve_mpr_widget=curve)) == [curve]


def test_active_menu_state_tracks_session_close_and_reopen():
    resolve = toolbar_method('_active_new_curve_mpr')
    curve = SimpleNamespace(_mpr_closed=False)
    original = SimpleNamespace(_curve_mpr_widget=curve)
    host = SimpleNamespace(patient_widget=SimpleNamespace(selected_widget=original, lst_nodes_viewer=[]))
    assert resolve(host) == (original, curve)
    curve._mpr_closed = True
    assert resolve(host) == (None, None)
    original._curve_mpr_widget = SimpleNamespace(_mpr_closed=False)
    assert resolve(host)[1] is original._curve_mpr_widget


def test_toggle_restores_selection_when_curve_had_focus():
    original = SimpleNamespace()
    curve = SimpleNamespace(_original_widget=original, _curve_reconstruction=object(), _mpr_closed=False)
    host = SimpleNamespace(patient_widget=SimpleNamespace(selected_widget=curve, lst_nodes_viewer=[]),
                           _restore_selected_viewer=lambda original: None, handle_buttons_checked=lambda: None)
    host._active_new_curve_mpr = lambda: toolbar_method('_active_new_curve_mpr')(host)
    toolbar_method('toggle_new_curve_mpr')(host)
    assert host.patient_widget.selected_widget is original
    assert host.tool_selected is None


def test_menu_check_uses_active_curve_session():
    # Popup assembly is structural; session resolution is exercised above.
    path = Path('PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py')
    source = path.read_text(encoding='utf-8')
    assert 'new_curve_mpr_btn.setChecked(self._active_new_curve_mpr()[1] is not None)' in source


def test_vrt_modes_render_and_release_in_isolated_process():
    """Real GPU rendering with Qt controls, without a Windows native QVTK handle."""
    import subprocess
    import sys
    code = '''
import time
import numpy as np
import vtkmodules.all as v
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from PySide6.QtWidgets import QApplication, QWidget
import modules.mpr.zeta_mpr.CurveMPR.curve_mpr_ui as ui
class OffscreenPane(QWidget):
 def __init__(self, parent=None):
  super().__init__(parent)
  self.window=v.vtkRenderWindow(); self.window.SetOffScreenRendering(1); self.window.SetSize(128,128)
  self.interactor=v.vtkRenderWindowInteractor(); self.interactor.SetRenderWindow(self.window)
 def GetRenderWindow(self): return self.window
 def SetInteractorStyle(self, style): self.interactor.SetInteractorStyle(style)
 def Initialize(self): pass
 def Finalize(self): self.window.Finalize()
ui.QVTKRenderWindowInteractor=OffscreenPane
app=QApplication([])
image=v.vtkImageData(); image.SetDimensions(41,41,41); image.SetOrigin(-20,-20,-20)
z,y,x=np.mgrid[-20:21,-20:21,-20:21]
values=np.where(y*y+z*z<9,400,-1000).astype(np.float32)
image.GetPointData().SetScalars(numpy_to_vtk(values.ravel(),deep=True))
w=ui.CurveMPRWidget(image)
def foreground():
 w._vrt_render_timer.stop(); w._render_volume()
 capture=v.vtkWindowToImageFilter(); capture.SetInput(w.vtkWidget_mip.GetRenderWindow()); capture.ReadFrontBufferOff(); capture.Update()
 assert capture.GetOutput().GetScalarRange()[1]>80
assert w.volume_mapper.GetInput() is None
assert not w.volume_actor.GetVisibility()
assert w.volume_preset.findData('CT-Lung-Airways') >= 0
w.volume_width.setValue(10)
w.add_point((-10,0,0)); w.add_point((10,0,0))
deadline=time.monotonic()+20
while w._job is not None and time.monotonic()<deadline:
 app.processEvents(); time.sleep(.01)
assert w._path_volume is not None
assert w.volume_mapper.GetInput() is w._path_volume
assert w._path_volume.GetBounds()==(-15,15,-5,5,-5,5)
assert w.volume_mapper.GetVolumetricScatteringBlending()==.5
from modules.mpr.zeta_mpr.mpr_viewer._interactor_styles import VRTInteractorStyle
assert isinstance(w.volume_style,VRTInteractorStyle)
foreground()
image_before=w.image_actor_curved.GetInput()
assert w.ren_curved.GetActiveCamera().GetViewUp()[0]<-.99
assert w.volume_mapper.GetMaskInput() is w._volume_mask
volume_before=w._path_volume
mask_before=w._volume_mask
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent, QMouseEvent
def mouse(kind, x, y, button, buttons):
 event=QMouseEvent(kind,QPointF(x,w.vtkWidget_mip.height()-1-y),QPointF(x,y),button,buttons,Qt.NoModifier)
 QApplication.sendEvent(w.vtkWidget_mip,event)
camera=w.ren_mip.GetActiveCamera()
position_before=camera.GetPosition()
ambient_before=w.volume_property.GetAmbient()
opacity_before=w.volume_property.GetScalarOpacity().GetValue(400)
mouse(QEvent.MouseButtonPress,40,40,Qt.RightButton,Qt.RightButton)
mouse(QEvent.MouseMove,70,60,Qt.NoButton,Qt.RightButton)
mouse(QEvent.MouseButtonRelease,70,60,Qt.RightButton,Qt.NoButton)
assert w.volume_property.GetAmbient()!=ambient_before
assert w.volume_property.GetScalarOpacity().GetValue(400)!=opacity_before
assert camera.GetPosition()==position_before
scale_before=camera.GetParallelScale()
mouse(QEvent.MouseButtonPress,40,40,Qt.MiddleButton,Qt.MiddleButton)
mouse(QEvent.MouseMove,40,70,Qt.NoButton,Qt.MiddleButton)
mouse(QEvent.MouseButtonRelease,40,70,Qt.MiddleButton,Qt.NoButton)
assert camera.GetParallelScale()!=scale_before
mouse(QEvent.MouseButtonPress,40,40,Qt.LeftButton,Qt.LeftButton)
mouse(QEvent.MouseMove,60,60,Qt.NoButton,Qt.LeftButton)
mouse(QEvent.MouseButtonRelease,60,60,Qt.LeftButton,Qt.NoButton)
assert camera.GetPosition()!=position_before
wheel=QWheelEvent(QPointF(20,20),QPointF(20,20),QPoint(),QPoint(0,120),Qt.NoButton,Qt.NoModifier,Qt.NoScrollPhase,False)
assert w.eventFilter(w.vtkWidget_curved,wheel)
assert w._orbit_angle==5
deadline=time.monotonic()+20
while w._job is not None and time.monotonic()<deadline:
 app.processEvents(); time.sleep(.01)
assert w._job is None
assert w._path_volume is volume_before and w._volume_mask is mask_before
assert w._image_rotations['curved']==0
image_before=w.image_actor_curved.GetInput()
w._rotate_image('curved',90)
assert w.image_actor_curved.GetInput() is image_before
assert abs(w.ren_curved.GetActiveCamera().GetViewUp()[1])>.99
w._fit_image('curved')
assert abs(w.ren_curved.GetActiveCamera().GetViewUp()[1])>.99
w.volume_mode.setCurrentText('Straightened VRT')
deadline=time.monotonic()+20
while w._job is not None and time.monotonic()<deadline:
 app.processEvents(); time.sleep(.01)
assert w._job is None
assert w._straightened_volume is not None
assert w.volume_mapper.GetInput() is w._straightened_volume
foreground()
w.volume_preset.setCurrentIndex(2)
assert w.volume_property.GetDisableGradientOpacity()
w.volume_mode.setCurrentText('Curved MIP')
deadline=time.monotonic()+20
while w._job is not None and time.monotonic()<deadline:
 app.processEvents(); time.sleep(.01)
assert not w.volume_actor.GetVisibility()
assert w.image_actor_mip.GetVisibility()
w.volume_mode.setCurrentText('Path VRT')
deadline=time.monotonic()+20
while w._job is not None and time.monotonic()<deadline:
 app.processEvents(); time.sleep(.01)
assert w.volume_mapper.GetInput() is w._path_volume
assert w._path_volume.GetBounds()==(-15,15,-5,5,-5,5)
w.clear_points()
assert w._straightened_volume is None
w.cleanup()
assert not w._vrt_render_timer.isActive()
assert w.volume_mapper.GetInput() is None
assert w.volume_mapper.GetMaskInput() is None
from PySide6.QtCore import QThreadPool
assert QThreadPool.globalInstance().waitForDone(10000)
# Real image-slice picking on all source planes, including a missed click.
from types import SimpleNamespace
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_interactor import CurveMPRInteractorStyle
window=v.vtkRenderWindow(); window.SetOffScreenRendering(1); window.SetSize(128,128)
renderer=v.vtkRenderer(); window.AddRenderer(renderer)
mapper=v.vtkImageResliceMapper(); mapper.SetInputData(image); mapper.SliceFacesCameraOn(); mapper.SliceAtFocalPointOn()
actor=v.vtkImageSlice(); actor.SetMapper(mapper); renderer.AddViewProp(actor)
interactor=v.vtkRenderWindowInteractor(); interactor.SetRenderWindow(window)
style=v.vtkInteractorStyleImage(); interactor.SetInteractorStyle(style)
for name,position,up in [('axial',(0,0,100),(0,1,0)),('sagittal',(100,0,0),(0,0,1)),('coronal',(0,100,0),(0,0,1))]:
 camera=renderer.GetActiveCamera(); camera.SetPosition(position); camera.SetFocalPoint(0,0,0); camera.SetViewUp(up); camera.ParallelProjectionOn(); renderer.ResetCamera(); window.Render()
 picks=[]
 collector=SimpleNamespace(_closed=False,_source_view=name,add_point=lambda point:picks.append(point))
 viewer=SimpleNamespace(viewers={name:{'renderer':renderer,'actor':actor}})
 helper=CurveMPRInteractorStyle(viewer,collector,view_name=name)
 interactor.SetEventInformation(64,64); helper.on_left_button_press(style,'LeftButtonPressEvent')
 assert len(picks)==1
 assert np.linalg.norm(picks[0])<1e-4
 interactor.SetEventInformation(-100,-100); helper.on_left_button_press(style,'LeftButtonPressEvent')
 assert len(picks)==1
actor.ReleaseGraphicsResources(window); window.Finalize()
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert 'ERR|' not in result.stderr, result.stderr
