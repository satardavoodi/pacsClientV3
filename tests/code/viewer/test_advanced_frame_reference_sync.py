"""Frame-plane reference and sync do not require a reconstructed volume."""
from types import SimpleNamespace
import numpy as np
import vtk
import pytest
from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core._pw_sync import _PWSyncMixin


def viewer(positions, iop=(1, 0, 0, 0, 1, 0), index=0):
    images = []
    instances = []
    for k, pos in enumerate(positions):
        image = vtk.vtkImageData(); image.SetDimensions(10, 10, 1); image.SetSpacing(1, 1, 1)
        images.append(image)
        instances.append(dict(instance_number=k+1, frame_index=k, image_position_patient=pos,
            image_orientation_patient=iop, pixel_spacing=(1, 1), rows=10, columns=10))
    metadata = dict(series=dict(viewer_backend='vtk_simpleitk', study_instance_uid='study', frame_of_reference_uid='frame'),
        instances=instances, spatial_geometry_available=False, frame_geometry_available=True,
        instances_order_contract='ADVANCED_PRESENTATION_FRAME_ORDER', _advanced_presentation_frames=tuple(images))
    return SimpleNamespace(metadata=metadata, vtk_image_data=images[index], GetSlice=lambda:index,
        renderer=vtk.vtkRenderer(), IS_QT_BRIDGE=False)


def test_frame_metadata_order_is_not_sorted_by_position():
    v = viewer([(0, 0, 8), (0, 0, 3), (0, 0, 0)], index=1)
    assert _PWSyncMixin._geometry_instances_for_viewer(v, caller='test') == v.metadata['instances']


def test_sync_uses_current_source_frame_and_nearest_target_frame():
    source = viewer([(0, 0, 0), (0, 0, 4)], index=1)
    target = viewer([(0, 0, 5), (0, 0, 2), (0, 0, 0)])
    result = _PWSyncMixin._map_sync_dicom(source, target, (3, 6, 0))
    assert result is not None
    mapped, ijk, outside, reason = result
    assert not outside
    assert ijk[2] == 0  # physical Z=5, not source/native Z=0
    np.testing.assert_allclose(mapped, (3, 6, 0))


def test_sync_selects_last_frame_despite_native_depth_one():
    source = viewer([(0, 0, 4)])
    target = viewer([(0, 0, 0), (0, 0, 2), (0, 0, 4)])
    result = _PWSyncMixin._map_sync_dicom(source, target, (3, 6, 0))
    assert result[1][2] == 2


def test_reference_actors_stay_on_native_plane_for_later_frames():
    ax = viewer([(0, 0, 2), (0, 0, 4)], index=1)
    sag = viewer([(2, 0, 0), (4, 0, 0)], iop=(0, 1, 0, 0, 0, 1), index=1)
    widgets = [SimpleNamespace(image_viewer=v, update=lambda:None) for v in (ax, sag)]
    class Host(_PWSyncMixin): pass
    host = Host(); host.lst_nodes_viewer = [SimpleNamespace(vtk_widget=w) for w in widgets]
    host._manage_reference_line_all_pairs(repaint=False)
    for v in (ax, sag):
        actors = v.renderer.GetActors(); actors.InitTraversal()
        actor = actors.GetNextActor()
        assert actor is not None and actor.GetVisibility()
        actor.GetMapper().Update()
        assert actor.GetMapper().GetInput().GetBounds()[4:] == (0., 0.)


def test_sync_uses_nonzero_current_source_frame():
    source = viewer([(0, 0, 0), (0, 0, 4)], index=1)
    target = viewer([(0, 0, 0), (0, 0, 2), (0, 0, 4)])
    assert _PWSyncMixin._map_sync_dicom(source, target, (3, 6, 0))[1][2] == 2


@pytest.mark.parametrize('reverse', [False, True])
def test_orthogonal_sync_in_both_directions(reverse):
    axial = viewer([(0, 0, 0), (0, 0, 4)], index=1)
    sagittal = viewer([(0, 0, 0), (4, 0, 0)], iop=(0, 1, 0, 0, 0, 1), index=1)
    source, target = (sagittal, axial) if reverse else (axial, sagittal)
    # Native x=4, y=5 corresponds to in-plane row/column=4,4.
    result = _PWSyncMixin._map_sync_dicom(source, target, (4, 5, 0))
    assert result[0] is not None and result[1][2] == 1
    np.testing.assert_allclose(result[0], (4, 5, 1))


def test_incompatible_frame_of_reference_is_rejected():
    a, b = viewer([(0, 0, 0)]), viewer([(0, 0, 0)])
    b.metadata['series']['frame_of_reference_uid'] = 'different'
    assert _PWSyncMixin._map_sync_dicom(a, b, (3, 6, 0))[0] is None


def test_outside_stack_does_not_clamp_to_wrong_frame():
    source = viewer([(0, 0, 100)])
    target = viewer([(0, 0, 0), (0, 0, 2), (0, 0, 4)])
    assert _PWSyncMixin._map_sync_dicom(source, target, (3, 6, 0))[0] is None


def test_sync_token_selects_frame_but_marker_stays_on_visible_image():
    from modules.viewer.advanced.presentation_frames import apply_sync_point
    v = viewer([(0, 0, 0), (0, 0, 2), (0, 0, 4)])
    v._index = 0; v.GetSlice = lambda:v._index
    v.set_slice = lambda index:setattr(v, '_index', index)
    v._ensure_sync_point_actor = lambda:None
    v._sync_point_source = vtk.vtkSphereSource(); v._sync_point_actor = vtk.vtkActor()
    v.Render = lambda:None
    v.hide_sync_point = lambda:pytest.fail('valid geometry was rejected')
    assert apply_sync_point(v, (3, 6, 2), True)
    assert v.GetSlice() == 2
    assert v._sync_point_source.GetCenter() == (3., 6., 0.)


def test_default_reference_path_draws_on_current_native_plane(monkeypatch):
    ax = viewer([(0, 0, 2), (0, 0, 4)], index=1)
    sag = viewer([(2, 0, 0), (4, 0, 0)], iop=(0, 1, 0, 0, 0, 1), index=1)
    widgets = [SimpleNamespace(image_viewer=v, update=lambda:None) for v in (ax, sag)]
    class Host(_PWSyncMixin): pass
    host = Host(); host.lst_nodes_viewer = [SimpleNamespace(vtk_widget=w) for w in widgets]
    host.selected_widget = widgets[0]
    monkeypatch.setenv('AIPACS_REFERENCE_LINES_ALL_PAIRS', '0')
    host.manage_reference_line(repaint=False)
    actors = sag.renderer.GetActors(); actors.InitTraversal(); actor = actors.GetNextActor()
    assert actor is not None and actor.GetVisibility()
    actor.GetMapper().Update()
    assert actor.GetMapper().GetInput().GetBounds()[4:] == (0., 0.)


def test_oblique_anisotropic_mapping_preserves_inplane_coordinates():
    iop = (.8, .6, 0, -.6, .8, 0)
    source = viewer([(10, 20, 4)], iop=iop)
    target = viewer([(10, 20, 0), (10, 20, 4)], iop=iop)
    for v in (source, target):
        for image in v.metadata['_advanced_presentation_frames']:
            image.SetSpacing(.7, 1.3, 1)
    mapped = _PWSyncMixin._map_sync_dicom(source, target, (2.1, 7.8, 0))
    np.testing.assert_allclose(mapped[0], (2.1, 7.8, 1), atol=1e-6)
