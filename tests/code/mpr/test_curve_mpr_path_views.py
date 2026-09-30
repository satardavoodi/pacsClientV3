"""Path-local CPR presentation; synthetic data only."""
import numpy as np
import vtkmodules.all as vtk
from vtkmodules.util.numpy_support import numpy_to_vtk
from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_core import CurveMPRCore
from vtkmodules.util.numpy_support import vtk_to_numpy
import pytest


def test_vrt_neighborhood_is_radial_not_a_bounding_box():
    image = vtk.vtkImageData()
    image.SetDimensions(31, 31, 31)
    image.SetOrigin(-15, -15, -15)
    image.GetPointData().SetScalars(numpy_to_vtk(np.full(31**3, 100, dtype=np.float32), deep=True))
    core = CurveMPRCore(image)
    core.add_control_point((-8, 0, 0))
    core.add_control_point((8, 0, 0))
    output = core.generate_path_volume(10)
    def value(point):
        return output.GetPointData().GetScalars().GetTuple1(output.FindPoint(point))
    assert value((0, 4, 0)) == 100
    assert value((0, -4, 0)) == 100
    assert value((0, 4, 4)) < -30000
    assert image.GetScalarRange() == (100, 100)


def test_worker_rotates_sampling_about_path_and_preserves_centerline():
    from modules.mpr.zeta_mpr.CurveMPR.curve_mpr_ui import _Reconstruction
    image = vtk.vtkImageData()
    image.SetDimensions(31, 31, 31)
    image.SetOrigin(-15, -15, -15)
    z, y, x = np.mgrid[-15:16, -15:16, -15:16]
    image.GetPointData().SetScalars(numpy_to_vtk((y + 10*z).astype(np.float32).ravel(), deep=True))
    results = []
    for angle in (0, 90, 360):
        job = _Reconstruction(1, image, [np.array([-8.,0,0]), np.array([8.,0,0])],
                              physical_width=6, angle_degrees=angle)
        job.signals.finished.connect(lambda revision, images, error: results.append((images, error)))
        job.run()
    assert all(error is None for images, error in results)
    arrays = [vtk_to_numpy(images[0].GetPointData().GetScalars()) for images, error in results]
    assert not np.allclose(arrays[0], arrays[1])
    np.testing.assert_allclose(arrays[0], arrays[2], atol=1e-5)


def test_path_volume_crops_physical_neighborhood_without_mutating_source():
    image = vtk.vtkImageData()
    image.SetDimensions(101, 101, 101)
    image.SetOrigin(-50, -50, -50)
    image.GetPointData().SetScalars(numpy_to_vtk(np.zeros(101**3, dtype=np.int16), deep=True))
    core = CurveMPRCore(image)
    core.add_control_point((-5, 0, 0))
    core.add_control_point((5, 0, 0))
    output = core.generate_path_volume(physical_width=10)
    assert output.GetBounds() == (-10, 10, -5, 5, -5, 5)
    assert image.GetBounds() == (-50, 50, -50, 50, -50, 50)
    core.clear_points()
    assert core.generate_path_volume() is None


@pytest.mark.parametrize('normal,tangent', [((0,0,1),(1,0,0)), ((1,0,0),(0,1,0)), ((0,1,0),(1,0,0))])
def test_two_longitudinal_planes_share_whole_curve_and_are_perpendicular(normal, tangent):
    core = CurveMPRCore(vtk.vtkImageData(), reference_normal=normal)
    core.add_control_point(-5 * np.asarray(tangent))
    core.add_control_point(5 * np.asarray(tangent))
    first = vtk_to_numpy(core._sample_points(11, 3, 4, angle_degrees=0).GetData()).reshape(3, 11, 3)
    second = vtk_to_numpy(core._sample_points(11, 3, 4, angle_degrees=90).GetData()).reshape(3, 11, 3)
    np.testing.assert_allclose(first[1], second[1], atol=1e-6)
    np.testing.assert_allclose(first[1, -1] - first[1, 0], 10*np.asarray(tangent))
    a, b = first[2]-first[1], second[2]-second[1]
    np.testing.assert_allclose((a*b).sum(axis=1), 0, atol=1e-6)
    np.testing.assert_allclose(a[0]/2, normal, atol=1e-6)


def test_path_crop_respects_oblique_native_direction_and_anisotropic_spacing():
    image = vtk.vtkImageData()
    image.SetDimensions(41, 41, 41)
    image.SetSpacing(.5, 1, 2)
    image.SetDirectionMatrix(0,-1,0, 1,0,0, 0,0,1)
    image.GetPointData().SetScalars(numpy_to_vtk(np.zeros(41**3, dtype=np.int16), deep=True))
    core = CurveMPRCore(image)
    core.add_control_point((-20, 8, 40))
    core.add_control_point((-20, 12, 40))
    output = core.generate_path_volume(physical_width=4)
    np.testing.assert_allclose(output.GetBounds(), (-22,-18,6,14,38,42))
    assert output.GetSpacing() == (.5, 1, 2)
