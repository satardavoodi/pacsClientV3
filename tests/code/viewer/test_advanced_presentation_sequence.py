"""Mixed MR/SC presentation frames retain native pixels and independent VOI."""
import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, SecondaryCaptureImageStorage


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch):
    from PacsClient.utils import data_paths
    from database.core import cleanup_connection_pools
    cleanup_connection_pools()
    monkeypatch.setattr(data_paths, 'DATABASE_FILE', tmp_path / 'unused-test.db')
    yield
    cleanup_connection_pools()
    assert not (tmp_path / 'unused-test.db').exists()


def write_frame(path, number, rgb=False, spatial=False, series_suffix=2):
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b'\0' * 128)
    values = dict(SOPClassUID=MRImageStorage if spatial else SecondaryCaptureImageStorage,
        SOPInstanceUID=f'1.2.826.0.1.3680043.10.999.5.{number}',
        StudyInstanceUID='1.2.826.0.1.3680043.10.999.1',
        SeriesInstanceUID=f'1.2.826.0.1.3680043.10.999.{series_suffix}',
        Modality='MR', SeriesNumber=1, InstanceNumber=number,
        Rows=4 if rgb else 8, Columns=6, SamplesPerPixel=3 if rgb else 1,
        PhotometricInterpretation='RGB' if rgb else 'MONOCHROME2',
        BitsAllocated=8 if rgb else 16, BitsStored=8 if rgb else 16,
        HighBit=7 if rgb else 15, PixelRepresentation=0,
        WindowWidth=100 + number, WindowCenter=50 + number)
    if spatial:
        values.update(ImageOrientationPatient=[1,0,0,0,1,0], ImagePositionPatient=[0,0,number], PixelSpacing=[1,1])
    if rgb: values['PlanarConfiguration'] = 0
    for k,v in values.items(): setattr(ds,k,v)
    pixels = np.arange(ds.Rows * ds.Columns * ds.SamplesPerPixel,
                       dtype=np.uint8 if rgb else np.uint16).reshape(
                           (ds.Rows,ds.Columns,3) if rgb else (ds.Rows,ds.Columns))
    ds.PixelData=pixels.tobytes()
    ds.is_little_endian=True
    ds.is_implicit_VR=False
    ds.save_as(path,write_like_original=False)
    return str(path),pixels


def test_mixed_frames_are_not_forced_into_a_spatial_volume(tmp_path, monkeypatch):
    from PacsClient.pacs.patient_tab.utils import image_io
    folder=tmp_path/'1'
    folder.mkdir()
    for n,rgb,spatial in [(1,False,False),(2,True,False),(3,False,True)]:
        write_frame(folder/f'{n}.dcm',n,rgb,spatial)
    # Filesystem-only worker route; no clinical DB access.
    monkeypatch.setattr(image_io, 'process_series_groups', lambda *a,**k: iter(()))
    result=list(image_io.load_single_series_by_number(tmp_path,1,allow_lazy_backend=False))
    assert len(result)==1, 'Advanced must retain the mixed presentation series'
    image,metadata,_=result[0]
    assert metadata['spatial_geometry_available'] is False
    assert len(metadata['_advanced_presentation_frames'])==3
    assert image.GetDimensions()[2]==1


def test_prepared_frames_preserve_native_dimensions_and_rgb(tmp_path):
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    from vtkmodules.util.numpy_support import vtk_to_numpy
    files=[];expected=[]
    for n,rgb in [(1,False),(2,True)]:
        path,pixels=write_frame(tmp_path/f'{n}.dcm',n,rgb)
        files.append(path);expected.append(pixels)
    image,meta=load_presentation_sequence(files,series_number=1)
    frames=meta['_advanced_presentation_frames']
    for frame,pixels in zip(frames,expected):
        got=vtk_to_numpy(frame.GetPointData().GetScalars()).reshape(pixels.shape)
        np.testing.assert_array_equal(got,pixels[::-1])
    assert [m['window_width'] for m in meta['instances']]==[101,102]
    assert image is frames[0]


def test_regular_spatial_mr_keeps_existing_volume_route(tmp_path):
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    path,_=write_frame(tmp_path/'1.dcm',1,spatial=True)
    assert load_presentation_sequence([path],series_number=1) is None


def test_dx_without_patient_geometry_retains_pixels_voi_and_detector_spacing(tmp_path):
    import pydicom
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    path, pixels = write_frame(tmp_path/'dx.dcm', 1)
    ds = pydicom.dcmread(path)
    ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.1.1'
    ds.Modality = 'DX'
    ds.ImagerPixelSpacing = [0.2, 0.1]
    ds.PresentationLUTShape = 'IDENTITY'
    ds.PixelIntensityRelationshipSign = -1
    ds.save_as(path, write_like_original=False)
    result = load_presentation_sequence([path], series_number=1)
    assert result is not None, 'DX presentation does not require CT/MR patient geometry'
    image, metadata = result
    assert image.GetDimensions() == (6, 8, 1)
    assert image.GetSpacing() == (0.1, 0.2, 1.0)
    np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()).reshape(pixels.shape), pixels[::-1])
    assert metadata['series']['modality'] == 'DX'
    assert metadata['spatial_geometry_available'] is False
    instance = metadata['instances'][0]
    assert instance['pixel_spacing'] is None
    assert instance['spacing_calibration'] == 'detector'
    assert (instance['window_width'], instance['window_center']) == (101, 51)


def test_mixed_identities_cannot_be_published(tmp_path):
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    a,_=write_frame(tmp_path/'1.dcm',1)
    b,_=write_frame(tmp_path/'2.dcm',2,series_suffix=9)
    with pytest.raises(ValueError): load_presentation_sequence([a,b],series_number=1)


@pytest.mark.parametrize('calibration, suffix', [('detector', 'mm (detector)'), ('uncalibrated', 'px'), ('image_plane', 'mm')])
def test_dx_ruler_labels_measurement_plane(calibration, suffix):
    import vtk
    from types import SimpleNamespace
    from modules.viewer.interactor_styles.ruler_interactorstyle import RulerInteractorStyle
    viewer = SimpleNamespace(metadata={'_advanced_presentation_frames': (object(),),
        'instances': [{'spacing_calibration': calibration}]}, GetSlice=lambda: 0)
    style = SimpleNamespace(image_viewer=viewer)
    widget = vtk.vtkDistanceWidget()
    widget.CreateDefaultRepresentation()
    RulerInteractorStyle.set_widget_repr(style, widget, (0, 1, 0), '%-#6.3g mm')
    assert widget.GetRepresentation().GetLabelFormat() == '%-#6.3g ' + suffix


def test_large_dx_worker_route_renders_full_resolution(tmp_path, monkeypatch):
    import pydicom
    import vtk
    from types import SimpleNamespace
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from PacsClient.pacs.patient_tab.utils import image_io
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    folder = tmp_path/'1'
    folder.mkdir()
    path, _ = write_frame(folder/'large.dcm', 1)
    ds = pydicom.dcmread(path)
    ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.1.1'
    ds.Modality = 'DX'
    ds.Rows, ds.Columns = 6869, 4528
    ds.ImagerPixelSpacing = [0.1, 0.1]
    ds.WindowWidth, ds.WindowCenter = 4096, 2048
    pixels = np.broadcast_to(np.linspace(0, 4095, ds.Columns, dtype=np.uint16), (ds.Rows, ds.Columns))
    ds.PixelData = pixels.tobytes()
    ds.save_as(path, write_like_original=False)
    del ds
    monkeypatch.setattr(image_io, 'process_series_groups', lambda *a, **k: iter(()))
    results = list(image_io.load_single_series_by_number(tmp_path, 1, allow_lazy_backend=False))
    assert len(results) == 1
    image, metadata, _ = results[0]
    assert image.GetDimensions() == (4528, 6869, 1)
    np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()).reshape(pixels.shape), pixels)
    window = vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(400, 400)
    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    errors = []
    window.AddObserver(vtk.vtkCommand.ErrorEvent, lambda *args: errors.append('render error'))
    try:
        viewer = ImageViewer2D(window, interactor, 400, image, metadata, {}, False,
                              SimpleNamespace(_active_backend='vtk_simpleitk'))
        viewer.set_slice(0)
        viewer.color_mapper.Update()
        assert viewer.color_mapper.GetOutput().GetDimensions() == (4528, 6869, 1)
        capture = vtk.vtkWindowToImageFilter()
        capture.SetInput(window)
        capture.ReadFrontBufferOff()
        capture.Update()
        rendered = vtk_to_numpy(capture.GetOutput().GetPointData().GetScalars()).reshape(400, 400, -1)
        # Sample inside the image, away from text and borders: actual gradient pixels.
        assert np.ptp(rendered[190:210, 150:250, 0]) > 40
        assert not errors
    finally:
        window.Finalize()


@pytest.mark.parametrize('modality', ['MR', 'DOC'])
def test_native_viewer_scrolls_all_frames_and_returns_to_spatial_volume(tmp_path, modality):
    from types import SimpleNamespace
    import vtk
    from modules.viewer.advanced.viewer_2d import ImageViewer2D
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    files=[write_frame(tmp_path/f'{n}.dcm',n,rgb=(n==2))[0] for n in (1,2,3)]
    if modality == 'DOC':
        import pydicom
        for path in files:
            ds = pydicom.dcmread(path)
            ds.Modality = modality
            ds.save_as(path, write_like_original=False)
    image,meta=load_presentation_sequence(files,series_number=1)
    window=vtk.vtkRenderWindow()
    window.SetOffScreenRendering(1)
    window.SetSize(500,500)
    interactor=vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(window)
    viewer=ImageViewer2D(window,interactor,500,image,meta,{},False,SimpleNamespace(_active_backend='vtk_simpleitk'))
    try:
        assert viewer.get_count_of_slices()==3
        assert viewer.grow_input_image_inplace(image,meta) is False
        for index in (2,1,0,1,2):
            viewer.set_slice(index)
            assert viewer.GetSlice()==index
            assert viewer.vtk_image_data.GetDimensions()==meta['_advanced_presentation_frames'][index].GetDimensions()
            if index==1:
                assert viewer.get_window_level()==(255.0,127.5)
                viewer.color_mapper.Update()
                from vtkmodules.util.numpy_support import vtk_to_numpy
                rgb=vtk_to_numpy(meta['_advanced_presentation_frames'][index].GetPointData().GetScalars())
                mapped=vtk_to_numpy(viewer.color_mapper.GetOutput().GetPointData().GetScalars())
                np.testing.assert_array_equal(mapped[:,:3],rgb)
            else:
                assert viewer.get_window_level()==(101.0+index,51.0+index)
        volume=vtk.vtkImageData()
        viewer.flag_set_custom_window_level=True
        viewer.color_mapper.SetWindow(700)
        viewer.color_mapper.SetLevel(200)
        viewer.set_slice(1)
        assert viewer.get_window_level()==(255.0,127.5)
        viewer.set_slice(0)
        assert viewer.get_window_level()==(700.0,200.0)
        volume.SetDimensions(6,8,4)
        volume.AllocateScalars(vtk.VTK_UNSIGNED_SHORT,1)
        viewer.reset_image_viewer(volume,{'series':{'series_uid':'synthetic-other','modality':'MR'},'instances':[{}]*4})
        assert viewer.get_count_of_slices()==4
        viewer.set_slice(2)
        assert viewer.GetSlice()==2
        viewer.reset_image_viewer(image,meta)
        viewer.set_slice(1)
        assert viewer.get_count_of_slices()==3
        assert viewer.GetSlice()==1
        assert viewer.get_window_level()==(255.0,127.5)
    finally:
        window.Finalize()


@pytest.mark.parametrize('series_number', [100000, 7])
def test_document_sc_worker_admission_uses_object_type_not_series_number(tmp_path, monkeypatch, series_number):
    import pydicom
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from PacsClient.pacs.patient_tab.utils import image_io, image_filters
    folder = tmp_path/str(series_number)
    folder.mkdir()
    paths, expected = [], []
    for number in (1, 2):
        path, pixels = write_frame(folder/f'{number}.dcm', number, rgb=True)
        ds = pydicom.dcmread(path)
        ds.Modality = 'DOC'
        ds.SeriesNumber = series_number
        ds.save_as(path, write_like_original=False)
        paths.append(path)
        expected.append(pixels)
    def forbidden(*args, **kwargs):
        pytest.fail('Document pages must not enter spatial grouping or image enhancement')
    monkeypatch.setattr(image_io, 'process_series_groups', forbidden)
    monkeypatch.setattr(image_filters, 'apply_filters', forbidden)
    results = list(image_io.load_single_series_by_number(tmp_path, series_number, allow_lazy_backend=False))
    assert len(results) == 1
    image, metadata, _ = results[0]
    assert metadata['series']['modality'] == 'DOC'
    assert metadata['spatial_geometry_available'] is False
    assert len(metadata['instances']) == 2
    assert image is metadata['_advanced_presentation_frames'][0]
    for frame, pixels in zip(metadata['_advanced_presentation_frames'], expected):
        np.testing.assert_array_equal(vtk_to_numpy(frame.GetPointData().GetScalars()).reshape(pixels.shape), pixels[::-1])


def test_document_label_does_not_admit_encapsulated_pdf(tmp_path):
    import pydicom
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    path, _ = write_frame(tmp_path/'pdf.dcm', 1)
    ds = pydicom.dcmread(path)
    ds.Modality = 'DOC'
    ds.SOPClassUID = '1.2.840.10008.5.1.4.1.1.104.1'
    ds.save_as(path, write_like_original=False)
    assert load_presentation_sequence([path], series_number=100000) is None


def test_document_budget_accounts_for_rgb_bytes_and_decode_workspace(tmp_path, monkeypatch):
    import pydicom
    from PacsClient.pacs.patient_tab.utils import advanced_presentation as p
    files = []
    for number in range(1, 8):
        path, _ = write_frame(tmp_path/f'{number}.dcm', number, rgb=True)
        ds = pydicom.dcmread(path)
        ds.Modality = 'DOC'
        ds.save_as(path, write_like_original=False)
        files.append(path)
    # Seven retained byte-RGB pages plus four largest-page scratch buffers fit.
    page_bytes = 4 * 6 * 3
    monkeypatch.setattr(p, 'MAX_BYTES', page_bytes * 11)
    image, metadata = p.load_presentation_sequence(files, series_number=100000)
    assert len(metadata[p.FRAME_KEY]) == 7
    assert image.GetScalarSize() == 1
    monkeypatch.setattr(p, 'MAX_BYTES', page_bytes * 11 - 1)
    monkeypatch.setattr(p.sitk, 'ReadImage', lambda *_: pytest.fail('Decoded over budget'))
    with pytest.raises(ValueError, match='memory limit'):
        p.load_presentation_sequence(files, series_number=100000)


def test_sequence_cache_and_mpr_contract(tmp_path):
    import copy
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    from PacsClient.pacs.patient_tab.utils.advanced_payload_integrity import advanced_payload_matches_frames
    from PacsClient.pacs.patient_tab.ui.patient_ui._vc_cache import _VCCacheMixin
    from PacsClient.pacs.patient_tab.ui.patient_ui.patient_toolbar.toolbar_manager import ToolbarManager
    paths=[write_frame(tmp_path/f'{n}.dcm',n,rgb=n==2)[0] for n in (3,1,2)]
    image,meta=load_presentation_sequence(paths,series_number=1)
    assert [i['instance_number'] for i in meta['instances']]==[1,2,3]
    assert advanced_payload_matches_frames(image,meta)
    clone=copy.deepcopy(meta)
    assert clone['_advanced_presentation_frames'] is meta['_advanced_presentation_frames']
    assert advanced_payload_matches_frames(image,clone)
    state=SimpleNamespace(_get_series_expected_slices=lambda _:3,_emit_mpr_launch_route=Mock())
    assert not _VCCacheMixin._is_full_volume_cache_candidate(state,'1',image,meta)
    output,route=ToolbarManager._resolve_mpr_volume_for_route(state,series_data={'vtk_image_data':image,'metadata':meta},series_number='1',mpr_path='orthogonal')
    assert output is None
    assert route['reason']=='nonspatial_frame_sequence'
    clone['instances'].pop()
    assert not advanced_payload_matches_frames(image,clone)


def test_mixed_preview_defers_to_atomic_frame_preparation(tmp_path):
    from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview
    folder=tmp_path/'1';folder.mkdir()
    write_frame(folder/'1.dcm',1)
    write_frame(folder/'2.dcm',2,rgb=True)
    assert load_series_preview(tmp_path,1,max_files=8) is None


def test_preparation_budget_is_checked_before_decode(tmp_path,monkeypatch):
    from PacsClient.pacs.patient_tab.utils import advanced_presentation as p
    path,_=write_frame(tmp_path/'1.dcm',1)
    monkeypatch.setattr(p,'MAX_BYTES',1)
    monkeypatch.setattr(p.sitk,'ReadImage',lambda *_:pytest.fail('decoded over budget'))
    with pytest.raises(ValueError,match='memory limit'):
        p.load_presentation_sequence([path],series_number=1)


def test_graphic_overlays_keep_source_pixels_and_respect_origin(tmp_path):
    import pydicom
    from vtkmodules.util.numpy_support import vtk_to_numpy
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    path,source=write_frame(tmp_path/'1.dcm',1,rgb=True)
    ds=pydicom.dcmread(path)
    ds.add_new((0x6000,0x0010),'US',2)
    ds.add_new((0x6000,0x0011),'US',2)
    ds.add_new((0x6000,0x0040),'CS','G')
    ds.add_new((0x6000,0x0050),'SS',[2,3])
    ds.add_new((0x6000,0x0100),'US',1)
    ds.add_new((0x6000,0x0102),'US',0)
    ds.add_new((0x6000,0x3000),'OW',bytes([9,0]))
    ds.save_as(path,write_like_original=False)
    image,meta=load_presentation_sequence([path],series_number=1)
    np.testing.assert_array_equal(vtk_to_numpy(image.GetPointData().GetScalars()).reshape(source.shape),source[::-1])
    overlay=meta['_advanced_presentation_overlays'][0]
    rgba=vtk_to_numpy(overlay.GetPointData().GetScalars()).reshape(4,6,4)[::-1]
    assert np.count_nonzero(rgba[:,:,3])==2
    assert tuple(rgba[1,2])==(0,255,0,255)
    assert tuple(rgba[2,3])==(0,255,0,255)


def test_same_series_new_frame_tuple_is_not_skipped(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PacsClient.pacs.patient_tab.utils.advanced_presentation import load_presentation_sequence
    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series import _VWSeriesMixin
    image,meta=load_presentation_sequence([write_frame(tmp_path/'1.dcm',1)[0]],series_number=1)
    old=dict(meta)
    old['_advanced_presentation_frames']=tuple([image])

    class ReachedSwitch(Exception):
        pass

    class State(SimpleNamespace):
        def __setattr__(self,name,value):
            if name=='_camera_restore_generation':
                raise ReachedSwitch
            super().__setattr__(name,value)

    state=State(image_viewer=SimpleNamespace(metadata=old,vtk_image_data=image),
                _bind_backend_from_metadata=Mock(),_emit_advanced_series_bind=Mock(),
                _dbg_fast_state=Mock(),_lazy_loader=None)
    with pytest.raises(ReachedSwitch):
        _VWSeriesMixin.switch_series(state,image,meta,0)
