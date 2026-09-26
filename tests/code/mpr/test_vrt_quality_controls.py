"""VRT-only presentation, immutable geometry and bounded lighting guards."""
from types import SimpleNamespace
import vtkmodules.all as vtk
from modules.mpr.zeta_mpr.mpr_viewer._mpr_views import _MprViewsMixin
from modules.mpr.zeta_mpr.mpr_viewer._mpr_vrt import _MprVrtMixin, configure_vrt_quality
from modules.mpr.zeta_mpr.preset_manager import PresetManager


def test_bone_preset_does_not_erase_low_gradient_interiors(tmp_path):
    prop = vtk.vtkVolumeProperty()
    host = SimpleNamespace(preset_manager=PresetManager(str(tmp_path)), scalar_range=(-1024, 3071),
                           viewers={}, _remember_vrt_threshold=lambda p: None)
    _MprViewsMixin._apply_volume_preset(host, prop, 'CT-Bone')
    assert prop.GetDisableGradientOpacity() == 1


def test_lighting_is_bounded_and_reversible():
    mapper, prop = vtk.vtkGPUVolumeRayCastMapper(), vtk.vtkVolumeProperty()
    prop.ShadeOn()
    configure_vrt_quality(mapper, prop, (.7, .7, 2), 'Detailed')
    assert mapper.GetVolumetricScatteringBlending() == .5
    assert mapper.GetSampleDistance() < .2
    configure_vrt_quality(mapper, prop, (.7, .7, 2), 'Detailed', interacting=True)
    assert mapper.GetVolumetricScatteringBlending() == 0
    configure_vrt_quality(mapper, prop, (.7, .7, 2), 'Detailed', heavy=True)
    assert mapper.GetVolumetricScatteringBlending() == 0
    assert prop.GetDisableGradientOpacity() == 1


def test_threshold_is_absolute_and_preserves_nodes_and_geometry():
    prop = vtk.vtkVolumeProperty()
    opacity = vtk.vtkPiecewiseFunction()
    opacity.AddPoint(100, 0, .3, .2)
    opacity.AddPoint(300, .8, .7, .4)
    color = vtk.vtkColorTransferFunction()
    color.AddRGBPoint(100, .2, .3, .4)
    color.AddRGBPoint(300, .8, .9, 1)
    prop.SetScalarOpacity(opacity)
    prop.SetColor(color)
    image = vtk.vtkImageData()
    image.SetOrigin(4, 5, 6)
    image.SetSpacing(.5, .7, 2)
    host = SimpleNamespace(viewers={'3d': {'property': prop}}, image_data=image,
                           _reset_vrt_rmb_state=lambda: None, _request_render=lambda v: None)
    _MprVrtMixin._remember_vrt_threshold(host, prop)
    for offset in (50, 100, 50):
        _MprVrtMixin._set_vrt_threshold(host, offset)
    assert prop.GetScalarOpacity().GetRange() == (150, 350)
    assert prop.GetRGBTransferFunction().GetRange() == (150, 350)
    _MprVrtMixin._set_vrt_threshold(host, 0)
    node = [0.] * 4
    prop.GetScalarOpacity().GetNodeValue(0, node)
    assert node == [100, 0, .3, .2]
    assert image.GetOrigin() == (4, 5, 6)
    assert image.GetSpacing() == (.5, .7, 2)
