import asyncio
from types import SimpleNamespace
from pathlib import Path

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from PacsClient.pacs.patient_tab.ui.patient_ui import patient_widget as patient_widget_mod
from PacsClient.pacs.patient_tab.utils import image_io as image_io_mod


def _write_test_dicom(path: Path, *, study_uid: str, series_uid: str, series_number: int) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientName = "Test^Patient"
    ds.PatientID = "P123"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = int(series_number)
    ds.InstanceNumber = 1
    ds.Modality = "CT"
    ds.SeriesDescription = "Import Regression"
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.BitsStored = 16
    ds.BitsAllocated = 16
    ds.HighBit = 15
    ds.PixelSpacing = [1.0, 1.0]
    ds.ImagePositionPatient = [0.0, 0.0, 0.0]
    ds.ImageOrientationPatient = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
    ds.SliceThickness = 1.0
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    ds.PixelData = b"\0\0" * 4
    ds.save_as(str(path), write_like_original=False)


def _make_flat_study(tmp_path: Path, *, series_number: int = 1) -> Path:
    root = tmp_path / "flat-study"
    root.mkdir()
    study_uid = generate_uid()
    series_uid = generate_uid()
    _write_test_dicom(
        root / "1.dcm",
        study_uid=study_uid,
        series_uid=series_uid,
        series_number=series_number,
    )
    return root


def _make_non_numeric_series_study(tmp_path: Path, *, series_number: int = 7) -> Path:
    root = tmp_path / "study"
    series_dir = root / "Series-Alpha"
    series_dir.mkdir(parents=True)
    study_uid = generate_uid()
    series_uid = generate_uid()
    _write_test_dicom(
        series_dir / "1.dcm",
        study_uid=study_uid,
        series_uid=series_uid,
        series_number=series_number,
    )
    return root


class _SignalProbe:
    def __init__(self) -> None:
        self.values = []

    def emit(self, value) -> None:
        self.values.append(value)


def _build_widget(import_folder_path: str):
    widget = patient_widget_mod.PatientWidget.__new__(patient_widget_mod.PatientWidget)
    widget._first_series_displayed = False
    widget.import_folder_path = import_folder_path
    widget.series_downloaded = _SignalProbe()
    widget.isVisible = lambda: True
    return widget


def test_load_single_series_by_number_supports_flat_import_root(tmp_path, monkeypatch):
    root = _make_flat_study(tmp_path)
    captured = {}

    def _fake_group_images_base_on_size(path, ordering_by_instance_number=False):
        captured["group_path"] = Path(path)
        return {(2, 2): [str(root / "1.dcm")]}

    def _fake_process_series_groups(base_path, size_groups, patient_pk, study_pk,
                                    max_itk_threads=None, max_pydicom_workers=None):
        captured["base_path"] = Path(base_path)
        yield "vtk", {"series": {"series_number": "1", "series_path": str(base_path)}, "instances": []}, (
            patient_pk,
            study_pk,
        )

    monkeypatch.setattr(image_io_mod.utils, "group_images_base_on_size", _fake_group_images_base_on_size)
    monkeypatch.setattr(image_io_mod, "process_series_groups", _fake_process_series_groups)

    result = list(
        image_io_mod.load_single_series_by_number(
            str(root),
            1,
            allow_lazy_backend=False,
        )
    )

    assert captured["group_path"] == root
    assert captured["base_path"] == root
    assert result[-1][1]["series"]["series_number"] == "1"


def test_check_and_load_local_first_series_emits_for_flat_import_root(tmp_path):
    root = _make_flat_study(tmp_path)
    widget = _build_widget(str(root))

    patient_widget_mod.PatientWidget._check_and_load_local_first_series(widget)

    assert widget.series_downloaded.values == ["1"]


def test_check_and_load_local_first_series_emits_for_non_numeric_series_folder(tmp_path):
    root = _make_non_numeric_series_study(tmp_path)
    widget = _build_widget(str(root))

    patient_widget_mod.PatientWidget._check_and_load_local_first_series(widget)

    assert widget.series_downloaded.values == ["7"]


def test_get_correct_study_path_keeps_flat_import_root(tmp_path):
    root = _make_flat_study(tmp_path)
    widget = _build_widget(str(root))

    resolved = patient_widget_mod.PatientWidget._get_correct_study_path(widget)

    assert resolved == str(root)


def test_pipeline_manager_import_supports_sync_logo_check(tmp_path, monkeypatch):
    root = _make_flat_study(tmp_path)
    stored_data = []

    widget = patient_widget_mod.PatientWidget.__new__(patient_widget_mod.PatientWidget)
    widget.import_folder_path = str(root)
    widget.metadata_fixed = {}
    widget.ordering_by_instances_number = True
    widget._event_loop = None
    widget.logo_patient = None
    widget.viewer_controller = SimpleNamespace(lst_nodes_viewer=[], selected_widget=None)
    widget._first_series_displayed = False
    widget.check_and_add_meta_fixed = lambda patient_info: None
    widget.add_thumbnail_to_thumbnail_layout = lambda **kwargs: 1
    widget.add_new_data_to_lst_thumbnails_data = lambda new_data: stored_data.append(new_data)
    widget.get_optimal_layout_for_series = lambda metadata: (1, 1)
    widget.init_matrix_viewers = lambda layout: None
    widget._hide_loading_spinner = lambda: None
    widget._any_viewer_empty = lambda: True
    widget._display_first_series_in_all_viewers = lambda series_number: True
    widget.isVisible = lambda: True
    widget.check_logo_patient = lambda file_path: None

    def _fake_load_images(folder_path, patient_pk=None, study_pk=None, ordering_by_instances_number=None):
        yield "vtk", {"series": {"series_path": str(root), "series_number": "1"}, "instances": []}, {}

    monkeypatch.setattr(patient_widget_mod, "load_images", _fake_load_images)
    monkeypatch.setattr(
        patient_widget_mod,
        "save_image_as_png",
        lambda vtk_image_data, metadata, metadata_fixed, file: str(root / "thumb.png"),
    )

    asyncio.run(
        patient_widget_mod.PatientWidget.pipeline_manager_import(
            widget,
            thumb_index=0,
            size_init_viewers=(1, 1),
        )
    )

    assert len(stored_data) == 1
