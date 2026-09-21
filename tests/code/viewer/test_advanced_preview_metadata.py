"""Preview metadata must describe the exact decoded file sequence, not DB order."""
import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage
from vtkmodules.util.numpy_support import vtk_to_numpy


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    from PacsClient.utils import data_paths
    from database.core import cleanup_connection_pools
    cleanup_connection_pools()
    monkeypatch.setattr(data_paths, "DATABASE_FILE", tmp_path / "unused-test.db")
    yield
    cleanup_connection_pools()
    assert not (tmp_path / "unused-test.db").exists()


@pytest.fixture
def preview_files(tmp_path):
    folder = tmp_path / "1"
    folder.mkdir()
    files = []
    for index, number in enumerate((3, 1, 2)):
        path = folder / f"{index}.dcm"
        meta = FileMetaDataset()
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        for key, value in dict(
            SOPClassUID=MRImageStorage,
            SOPInstanceUID=f"1.2.826.0.1.3680043.10.999.5.{number}",
            StudyInstanceUID="1.2.826.0.1.3680043.10.999.1",
            SeriesInstanceUID="1.2.826.0.1.3680043.10.999.2",
            Modality="MR", SeriesNumber=1, InstanceNumber=number,
            Rows=8, Columns=10, SamplesPerPixel=1, PhotometricInterpretation="MONOCHROME2",
            BitsAllocated=16, BitsStored=16, HighBit=15, PixelRepresentation=0,
            ImageOrientationPatient=[1, 0, 0, 0, 1, 0],
            ImagePositionPatient=[0, 0, index * 2], PixelSpacing=[1, 1], SliceThickness=2,
        ).items():
            setattr(ds, key, value)
        ds.PixelData = np.full((8, 10), number, dtype=np.uint16).tobytes()
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        ds.save_as(path, write_like_original=False)
        files.append(path)
    return tmp_path, files


@pytest.mark.parametrize("db_route", [False, True])
def test_preview_metadata_matches_pixels_and_sop_order(preview_files, monkeypatch, db_route):
    from PacsClient.pacs.patient_tab.utils import image_io
    from PacsClient.utils import database
    root, files = preview_files
    monkeypatch.setattr(image_io, "_list_unique_dicom_files", lambda _: files)
    monkeypatch.setattr(database, "find_series_pk_by_number", lambda *a: 1)
    monkeypatch.setattr(image_io, "get_series_by_series_pk", lambda *a: {"series_number": "1"})
    monkeypatch.setattr(image_io, "get_instances_by_series_pk", lambda *a, **k: [
        {"instance_number": n, "instance_path": str(files[(1, 2, 0)[n-1]])}
        for n in (1, 2, 3)])
    monkeypatch.setattr(image_io, "_backfill_instance_orientation", lambda *a: None)
    image, metadata, _, total = image_io.load_series_preview(root, 1, study_pk=1 if db_route else None, max_files=2)
    instances = metadata["instances"]
    pixels = vtk_to_numpy(image.GetPointData().GetScalars()).reshape(2, 8, 10)
    assert len(instances) == image.GetDimensions()[2] == 2
    full, _ = image_io._get_or_build_series_geometry_index(list(map(str, files)), source='test_preview_order')
    expected = full.display_instances_order[:2]
    assert [x["instance_number"] for x in instances] == [int(p[0, 0]) for p in pixels] == [x.instance_number for x in expected]
    assert [x["instance_path"] for x in instances] == [x.instance_path for x in expected]
    assert [x["sop_uid"] for x in instances] == [x.sop_uid for x in expected]
    assert total == metadata["preview_total_instances"] == 3
    assert len(metadata['series_geometry_index']['display_instances_order']) == 2


def test_unreadable_preview_header_defers_to_full_loader(preview_files, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import image_io
    root, files = preview_files
    monkeypatch.setattr(image_io, "_list_unique_dicom_files", lambda _: files)
    original = image_io._build_instance_header_stub
    monkeypatch.setattr(image_io, "_build_instance_header_stub", lambda p, i: None if p == files[1] else original(p, i))
    assert image_io.load_series_preview(root, 1, max_files=2) is None


def test_single_slice_keeps_actual_instance_number(preview_files):
    from PacsClient.pacs.patient_tab.utils import image_io
    root, _ = preview_files
    image, metadata, _, _ = image_io.load_series_preview(root, 1, max_files=1)
    assert image.GetDimensions()[2] == len(metadata["instances"]) == 1
    full, _ = image_io._get_or_build_series_geometry_index(list(map(str, preview_files[1])), source='test_single_preview')
    assert metadata["instances"][0]["instance_number"] == full.display_instances_order[0].instance_number


def test_worker_window_metadata_does_not_reopen_dicom_during_scroll(preview_files, monkeypatch):
    from types import SimpleNamespace
    import pydicom
    from PacsClient.pacs.patient_tab.utils import image_io
    from modules.viewer.advanced import viewer_2d
    root, files = preview_files
    for path in files:
        ds = pydicom.dcmread(path)
        ds.WindowWidth, ds.WindowCenter = 400, 40
        ds.save_as(path, write_like_original=False)
    _, metadata, _, _ = image_io.load_series_preview(root, 1, max_files=2)
    viewer = SimpleNamespace(metadata=metadata)
    def disk_read(*args, **kwargs):
        pytest.fail('Scroll reopened a DICOM already read on the worker')
    monkeypatch.setattr(viewer_2d, 'resolve_cornerstone_like_window_level_from_dicom', disk_read)
    for instance in metadata['instances']:
        assert viewer_2d.ImageViewer2D._read_window_level_from_dicom_cornerstone(viewer, instance) == (400.0, 40.0, 'dicom_tag')


def test_older_cached_metadata_resolves_header_only_once(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from modules.viewer.advanced import viewer_2d
    resolve = Mock(return_value=(400.0, 40.0, 'dicom_tag'))
    monkeypatch.setattr(viewer_2d, 'resolve_cornerstone_like_window_level_from_dicom', resolve)
    viewer = SimpleNamespace(metadata={'series': {'modality': 'CT'}})
    instance = {'instance_path': 'synthetic.dcm'}
    for _ in range(3):
        assert viewer_2d.ImageViewer2D._read_window_level_from_dicom_cornerstone(viewer, instance) == (400.0, 40.0, 'dicom_tag')
    assert resolve.call_count == 1


@pytest.mark.parametrize('backend, base, dy, expected', [
    ('vtk_simpleitk', 100, 120, 76), ('vtk_simpleitk', 2, 120, 0),
    ('vtk_simpleitk', 390, -120, 391), ('pydicom', 100, 120, 94)])
def test_large_advanced_drag_keeps_distance_and_clamps_endpoints(backend, base, dy, expected):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from modules.viewer.interactor_styles.abstract_interactorstyle import AbstractInteractorStyle
    widget = SimpleNamespace(_active_backend=backend, queue_interactive_slice_target=Mock())
    viewer = SimpleNamespace(vtk_widget=widget, get_count_of_slices=lambda: 392,
                             get_display_slice=lambda: base)
    style = SimpleNamespace(image_viewer=viewer, last_pos=(0, 0), slider=None,
                            GetInteractor=lambda: SimpleNamespace(GetEventPosition=lambda: (0, dy)))
    AbstractInteractorStyle.change_quickly_slices(style)
    assert widget.queue_interactive_slice_target.call_args.kwargs['slice_index'] == expected


def test_native_preview_to_full_keeps_display_sop_direction(preview_files, monkeypatch):
    from types import SimpleNamespace
    import vtk
    from PacsClient.pacs.patient_tab.utils import image_io
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    root, files = preview_files
    image, metadata, _, _ = image_io.load_series_preview(root, 1, max_files=2)
    index, _ = image_io._get_or_build_series_geometry_index(list(map(str, files)), source='native_preview_guard')
    full_image = image_io.utils.convert_itk2vtk(image_io.get_itk_image(index.dicom_files_for_itk))
    full_metadata = {'series': {'series_number': '1', 'modality': 'MR'}}
    image_io._apply_geometry_index_metadata(full_metadata, index)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(300, 300)
    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    try:
        viewer = ImageViewer2D(window, interactor, 300, image, metadata, {}, False,
                              SimpleNamespace(_active_backend='vtk_simpleitk'))
        renders = []
        observer = window.AddObserver(vtk.vtkCommand.StartEvent, lambda *_: renders.append(1))
        def captured_pixels():
            capture = vtk.vtkWindowToImageFilter()
            capture.SetInput(window)
            capture.ReadFrontBufferOff()
            capture.ShouldRerenderOff()
            capture.Update()
            return vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).copy()
        for incoming_image, incoming_metadata in [(image, metadata), (full_image, full_metadata)]:
            viewer.reset_image_viewer(incoming_image, incoming_metadata)
            camera_scale = viewer.renderer.GetActiveCamera().GetParallelScale()
            for target in (0, 1):
                renders.clear()
                viewer.set_slice(target)
                raw_index = viewer.GetSlice()
                assert viewer.metadata['instances'][raw_index]['sop_uid'] == index.sop_uid_by_display_index[target]
                assert len(renders) == 1, 'Each slice update should produce one complete render'
                actual_pixels = captured_pixels()
                viewer.vtk_widget._active_backend = 'legacy_test'
                viewer.set_slice(1 - target)
                viewer.set_slice(target)
                np.testing.assert_array_equal(actual_pixels, captured_pixels())
                assert viewer.renderer.GetActiveCamera().GetParallelScale() == camera_scale
                viewer.vtk_widget._active_backend = 'vtk_simpleitk'
        # A preparation error must not leave a callback attached to later renders.
        original = viewer._prepare_slice_visuals
        def fail_preparation(*args):
            raise RuntimeError('synthetic preparation failure')
        monkeypatch.setattr(viewer, '_prepare_slice_visuals', fail_preparation)
        with pytest.raises(RuntimeError, match='synthetic preparation failure'):
            viewer._set_slice_impl(0)
        monkeypatch.setattr(viewer, '_prepare_slice_visuals', original)
        renders.clear()
        viewer.set_slice(1, fast_interaction=True, force_annotations=True)
        assert len(renders) == 1
        window.RemoveObserver(observer)
    finally:
        window.Finalize()


@pytest.mark.parametrize("reason", ["multiframe", "decoded_count"])
def test_unsupported_frame_mapping_is_not_published(preview_files, monkeypatch, reason):
    from PacsClient.pacs.patient_tab.utils import image_io
    root, _ = preview_files
    if reason == "multiframe":
        original = image_io._build_instance_header_stub
        def multiframe(p, i):
            return dict(original(p, i), number_of_frames=2)
        monkeypatch.setattr(image_io, "_build_instance_header_stub", multiframe)
    else:
        import vtkmodules.all as vtk
        image = vtk.vtkImageData()
        image.SetDimensions(10, 8, 3)
        monkeypatch.setattr(image_io.utils, "convert_itk2vtk", lambda _: image)
    assert image_io.load_series_preview(root, 1, max_files=2) is None
