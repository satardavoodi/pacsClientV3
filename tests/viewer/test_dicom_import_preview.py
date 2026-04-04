import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, SecondaryCaptureImageStorage, generate_uid

from PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog import (
    filter_scan_result_for_selection,
    import_scanned_dicom_studies,
    scan_dicom_import_folder,
)


def _write_test_dicom(
    path: Path,
    *,
    patient_id: str,
    patient_name: str,
    study_uid: str,
    series_uid: str,
    series_number: int,
    instance_number: int,
    study_date: str = "20260315",
    study_time: str = "104512",
    study_description: str = "Import Preview Study",
    series_description: str = "Preview Series",
) -> None:
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = SecondaryCaptureImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.ImplementationClassUID = generate_uid()

    ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = int(series_number)
    ds.SeriesDescription = series_description
    ds.StudyDescription = study_description
    ds.StudyDate = study_date
    ds.StudyTime = study_time
    ds.InstanceNumber = int(instance_number)
    ds.SOPInstanceUID = generate_uid()
    ds.Modality = "CT"
    ds.Rows = 2
    ds.Columns = 2
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelRepresentation = 0
    ds.BitsStored = 16
    ds.BitsAllocated = 16
    ds.HighBit = 15
    ds.PixelData = b"\0\0" * 4
    ds.save_as(str(path), write_like_original=False)


def test_scan_dicom_import_folder_groups_files_by_study_and_series(tmp_path):
    root = tmp_path / "incoming"
    root.mkdir()

    study_uid = generate_uid()
    series_one_uid = generate_uid()
    series_two_uid = generate_uid()

    _write_test_dicom(
        root / "series-1-image-1.dcm",
        patient_id="P100",
        patient_name="Alpha^Patient",
        study_uid=study_uid,
        series_uid=series_one_uid,
        series_number=1,
        instance_number=1,
        series_description="Axial 1",
    )
    _write_test_dicom(
        root / "series-1-image-2.dcm",
        patient_id="P100",
        patient_name="Alpha^Patient",
        study_uid=study_uid,
        series_uid=series_one_uid,
        series_number=1,
        instance_number=2,
        series_description="Axial 1",
    )
    _write_test_dicom(
        root / "series-2-image-1.dcm",
        patient_id="P100",
        patient_name="Alpha^Patient",
        study_uid=study_uid,
        series_uid=series_two_uid,
        series_number=2,
        instance_number=1,
        series_description="Coronal 2",
    )

    scan_result = scan_dicom_import_folder(root)

    assert scan_result["dicom_file_count"] == 3
    assert scan_result["patient_count"] == 1
    assert scan_result["study_count"] == 1
    assert scan_result["series_count"] == 2
    assert scan_result["primary_study_uid"] == study_uid
    business_warnings = [w for w in scan_result["warnings"] if not w.startswith("Detected decoders")]
    assert business_warnings == []

    study_info = scan_result["studies"][0]
    assert study_info["patient_id"] == "P100"
    assert study_info["patient_name"] == "Alpha^Patient"
    assert study_info["study_date"] == "20260315"
    assert study_info["study_time"] == "104512"
    assert [series["image_count"] for series in study_info["series"]] == [2, 1]


def test_scan_dicom_import_folder_warns_for_multiple_patients_and_studies(tmp_path):
    root = tmp_path / "mixed-import"
    root.mkdir()

    _write_test_dicom(
        root / "patient-a.dcm",
        patient_id="P100",
        patient_name="Alpha^Patient",
        study_uid=generate_uid(),
        series_uid=generate_uid(),
        series_number=1,
        instance_number=1,
    )
    _write_test_dicom(
        root / "patient-b.dcm",
        patient_id="P200",
        patient_name="Bravo^Patient",
        study_uid=generate_uid(),
        series_uid=generate_uid(),
        series_number=1,
        instance_number=1,
    )

    scan_result = scan_dicom_import_folder(root)

    assert scan_result["patient_count"] == 2
    assert scan_result["study_count"] == 2
    business_warnings = [w for w in scan_result["warnings"] if not w.startswith("Detected decoders")]
    assert len(business_warnings) == 2
    assert any("2 patients" in w for w in business_warnings)
    assert any("2 studies" in w for w in business_warnings)


def test_filter_scan_result_for_selection_keeps_only_selected_studies_and_series(tmp_path):
    root = tmp_path / "selection-source"
    root.mkdir()

    study_one_uid = generate_uid()
    study_two_uid = generate_uid()
    study_one_series_a = generate_uid()
    study_one_series_b = generate_uid()
    study_two_series = generate_uid()

    _write_test_dicom(
        root / "study-one-a.dcm",
        patient_id="P100",
        patient_name="Alpha^Patient",
        study_uid=study_one_uid,
        series_uid=study_one_series_a,
        series_number=1,
        instance_number=1,
    )
    _write_test_dicom(
        root / "study-one-b.dcm",
        patient_id="P100",
        patient_name="Alpha^Patient",
        study_uid=study_one_uid,
        series_uid=study_one_series_b,
        series_number=2,
        instance_number=1,
    )
    _write_test_dicom(
        root / "study-two-a.dcm",
        patient_id="P200",
        patient_name="Bravo^Patient",
        study_uid=study_two_uid,
        series_uid=study_two_series,
        series_number=1,
        instance_number=1,
    )

    scan_result = scan_dicom_import_folder(root)
    filtered_result = filter_scan_result_for_selection(
        scan_result,
        {
            study_one_uid: {study_one_series_b},
        },
        {study_one_uid},
    )

    assert filtered_result["study_count"] == 1
    assert filtered_result["series_count"] == 1
    assert filtered_result["dicom_file_count"] == 1
    assert filtered_result["patient_count"] == 1
    assert filtered_result["primary_study_uid"] == study_one_uid
    assert filtered_result["studies"][0]["study_uid"] == study_one_uid
    assert filtered_result["studies"][0]["series"][0]["series_uid"] == study_one_series_b


def test_import_scanned_dicom_studies_copies_files_into_managed_study_structure(tmp_path):
    source_root = tmp_path / "source"
    source_root.mkdir()

    study_uid = generate_uid()
    duplicate_series_number = 5
    first_series_uid = generate_uid()
    second_series_uid = generate_uid()

    _write_test_dicom(
        source_root / "first-series-1.dcm",
        patient_id="P300",
        patient_name="Charlie^Patient",
        study_uid=study_uid,
        series_uid=first_series_uid,
        series_number=duplicate_series_number,
        instance_number=1,
        series_description="First duplicate series",
    )
    _write_test_dicom(
        source_root / "second-series-1.dcm",
        patient_id="P300",
        patient_name="Charlie^Patient",
        study_uid=study_uid,
        series_uid=second_series_uid,
        series_number=duplicate_series_number,
        instance_number=1,
        series_description="Second duplicate series",
    )

    scan_result = scan_dicom_import_folder(source_root)
    import_root = tmp_path / "managed-storage"

    import_result = import_scanned_dicom_studies(scan_result, import_root)

    assert import_result["copied_files"] == 2
    assert import_result["skipped_files"] == 0
    assert import_result["errors"] == []
    assert import_result["primary_study"]["study_uid"] == study_uid

    imported_study = import_result["studies"][0]
    series_path_names = [series["series_path_name"] for series in imported_study["series"]]

    assert len(series_path_names) == 2
    assert len(set(series_path_names)) == 2

    study_output_dir = import_root / study_uid
    assert study_output_dir.exists()

    copied_files = []
    for series_path_name in series_path_names:
        series_dir = study_output_dir / series_path_name
        assert series_dir.exists()
        copied_files.extend(series_dir.glob("*.dcm"))

    assert len(copied_files) == 2
