"""Physical tube support and angular CPR sampling, without clinical fixtures."""
import numpy as np
import vtkmodules.all as vtk
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_core import CurveMPRCore


def volume():
    image = vtk.vtkImageData()
    image.SetDimensions(41,41,41)
    image.SetOrigin(-20,-20,-20)
    image.GetPointData().SetScalars(numpy_to_vtk(np.full(41**3,400,dtype=np.int16),deep=True))
    return image


def test_original_tube_is_circular_symmetric_and_preserves_inside_scalars():
    image=volume()
    core=CurveMPRCore(image)
    core.add_control_point((-8,0,0))
    core.add_control_point((8,0,0))
    crop=core.generate_path_volume(physical_width=10)
    mask=core.tube_mask
    assert mask.GetExtent()==crop.GetExtent()
    assert mask.GetOrigin()==crop.GetOrigin()
    extent=mask.GetExtent()
    data=vtk_to_numpy(mask.GetPointData().GetScalars()).reshape(mask.GetDimensions()[::-1])
    z,y,x=np.meshgrid(np.arange(extent[4],extent[5]+1),np.arange(extent[2],extent[3]+1),np.arange(extent[0],extent[1]+1),indexing='ij')
    # Evaluate physical positions, independently of the crop's local index origin.
    origin = mask.GetOrigin()
    distance2=np.maximum(np.abs(x+origin[0])-8,0)**2+(y+origin[1])**2+(z+origin[2])**2
    np.testing.assert_array_equal(data!=0,distance2<=25)
    assert np.all(vtk_to_numpy(image.GetPointData().GetScalars())==400)


def test_straightened_volume_also_uses_circular_diameter():
    core=CurveMPRCore(volume())
    core.add_control_point((-8,0,0)); core.add_control_point((8,0,0))
    output=core.generate_straightened_volume(physical_width=10,step=1)
    data=vtk_to_numpy(core.tube_mask.GetPointData().GetScalars()).reshape(output.GetDimensions()[::-1])
    assert data[5,5,8]==255
    assert data[0,0,8]==0
    assert data[0,5,8]==255


def test_orbit_rotates_sampling_about_same_centerline_and_wraps():
    core=CurveMPRCore(volume(),reference_normal=(0,0,1))
    core.add_control_point((-8,0,0)); core.add_control_point((8,0,0))
    def points(angle):
        return vtk_to_numpy(core._sample_points(17,3,4,angle_degrees=angle).GetData()).reshape(3,17,3)
    zero,ninety,full=points(0),points(90),points(360)
    np.testing.assert_allclose(zero,full,atol=1e-6)
    np.testing.assert_allclose(zero[1],ninety[1],atol=1e-6)
    assert not np.allclose(zero[0],ninety[0])


def test_bent_tube_matches_segment_distance_in_oblique_anisotropic_grid():
    image = volume()
    image.SetSpacing(.7, 1.2, 1.8)
    angle = np.deg2rad(31)
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0],
                         [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    image.SetDirectionMatrix(rotation.ravel())
    core = CurveMPRCore(image)
    for index in ((10, 15, 12), (20, 23, 17), (30, 17, 23)):
        point = [0., 0., 0.]
        image.TransformContinuousIndexToPhysicalPoint(index, point)
        core.add_control_point(point)
    output = core.generate_path_volume(physical_width=8)
    extent = output.GetExtent()
    indices = np.array(np.meshgrid(
        np.arange(extent[4], extent[5]+1), np.arange(extent[2], extent[3]+1),
        np.arange(extent[0], extent[1]+1), indexing='ij'))[::-1].reshape(3, -1).T
    positions = (indices * output.GetSpacing()) @ rotation.T + output.GetOrigin()
    distance2 = np.full(len(positions), np.inf)
    for start, end in zip(core.spline_points[:-1], core.spline_points[1:]):
        segment = end - start
        t = np.clip((positions-start) @ segment / np.dot(segment, segment), 0, 1)
        distance2 = np.minimum(distance2, np.sum((positions-start-t[:, None]*segment)**2, axis=1))
    actual = vtk_to_numpy(core.tube_mask.GetPointData().GetScalars()) != 0
    np.testing.assert_array_equal(actual, distance2 <= 16)


def test_gpu_mask_does_not_cut_off_nonzero_extent_crop():
    """A constant tube must retain its silhouette when GPU binary masking is enabled."""
    import subprocess
    import sys
    script = r"""
import numpy as np
import vtkmodules.all as v
from vtkmodules.util.numpy_support import numpy_to_vtk, vtk_to_numpy
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_core import CurveMPRCore
image = v.vtkImageData()
image.SetDimensions(81,81,81)
image.SetSpacing(.6,.7,1.3)
image.SetOrigin(-24,-28,-52)
image.GetPointData().SetScalars(numpy_to_vtk(np.full(81**3,400,dtype=np.int16),deep=True))
core = CurveMPRCore(image)
core.add_control_point((-12,0,0)); core.add_control_point((12,0,0))
output = core.generate_path_volume(20)
renderer = v.vtkRenderer()
window = v.vtkRenderWindow(); window.SetOffScreenRendering(1); window.SetSize(200,200); window.AddRenderer(renderer)
mapper = v.vtkGPUVolumeRayCastMapper(); mapper.SetInputData(output); mapper.SetMaskTypeToBinary()
mapper.SetSampleDistance(.2); mapper.AutoAdjustSampleDistancesOff()
prop = v.vtkVolumeProperty()
opacity = v.vtkPiecewiseFunction()
for x,y in [(-32768,0),(0,0),(100,1),(500,1)]: opacity.AddPoint(x,y)
prop.SetScalarOpacity(opacity)
color = v.vtkColorTransferFunction(); color.AddRGBPoint(-32768,1,1,1); color.AddRGBPoint(500,1,1,1)
prop.SetColor(color); prop.ShadeOff(); prop.SetInterpolationTypeToNearest()
actor = v.vtkVolume(); actor.SetMapper(mapper); actor.SetProperty(prop); renderer.AddVolume(actor)
try:
 for position,up in [((0,0,100),(0,1,0)),((0,100,0),(0,0,1)),((100,0,0),(0,0,1))]:
  camera = renderer.GetActiveCamera(); camera.SetPosition(position); camera.SetFocalPoint(0,0,0); camera.SetViewUp(up); camera.ParallelProjectionOn(); renderer.ResetCamera()
  counts=[]
  for mask in (None,core.tube_mask):
   mapper.SetMaskInput(mask); window.Render()
   capture=v.vtkWindowToImageFilter(); capture.SetInput(window); capture.ReadFrontBufferOff(); capture.Update()
   pixels=vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars())
   counts.append(np.count_nonzero(pixels[:,0]>100))
  assert counts[0]>1000,counts
  assert counts[1]>=.98*counts[0],counts
finally:
 actor.ReleaseGraphicsResources(window); window.Finalize()
"""
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert 'ERR|' not in result.stderr


def test_rebased_crop_retains_physical_voxels_after_decimation():
    image = vtk.vtkImageData()
    image.SetExtent(11,310, 21,31, 41,51)
    image.SetOrigin(12,-19,23)
    image.SetSpacing(.5,.8,1.2)
    image.SetDirectionMatrix(0,-1,0, 1,0,0, 0,0,1)
    z,y,x = np.mgrid[41:52,21:32,11:311]
    source = (x+10*y+100*z).astype(np.int16)
    image.GetPointData().SetScalars(numpy_to_vtk(source.ravel(),deep=True))
    core = CurveMPRCore(image)
    for index in ((15,26,46),(305,26,46)):
        point = [0.,0.,0.]
        image.TransformIndexToPhysicalPoint(index,point)
        core.add_control_point(point)
    output = core.generate_path_volume(4)
    assert output.GetExtent()[::2] == (0,0,0)
    assert output.GetSpacing()[0] == 1.0  # Bounded crop decimates the long axis.
    mask = vtk_to_numpy(core.tube_mask.GetPointData().GetScalars()) != 0
    actual = vtk_to_numpy(output.GetPointData().GetScalars())
    dims = output.GetDimensions()
    for flat in np.flatnonzero(mask)[::7]:
        iz, iy, ix = np.unravel_index(flat,dims[::-1])
        point, index = [0.]*3, [0.]*3
        output.TransformIndexToPhysicalPoint((int(ix),int(iy),int(iz)),point)
        image.TransformPhysicalPointToContinuousIndex(point,index)
        sx,sy,sz = np.rint(index).astype(int)
        assert actual[flat] == sx+10*sy+100*sz
    np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()),source.ravel())
    assert image.GetExtent() == (11,310,21,31,41,51)
