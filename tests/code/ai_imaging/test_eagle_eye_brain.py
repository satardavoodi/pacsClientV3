"""Synthetic-only brain contracts. No live DB, patient files or model downloads."""
import json
import threading
from pathlib import Path

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_brain.contracts import (
    BrainError, BrainPlan, geometry_voxel_volume, read_single_subject_csv, volume_rows,
)
from modules.ai_imaging.eagle_eye_brain.runtime import synthseg_command, validate_bundle


def test_report_long_parcel_name_does_not_overlap_volume_column():
    from PySide6.QtWidgets import QApplication, QTextEdit
    from PySide6.QtGui import QFontDatabase, QTextCursor, QFont
    from modules.ai_imaging.eagle_eye_brain.report import report_html
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/arial.ttf")
    row = {"structure": "ctx-rh-rostralanteriorcingulate", "volume_mm3": 1234.567,
           "volume_cm3": 1.235, "icv_percent": 0.123}
    # Many short initial names previously fixed a narrow first column in Qt's
    # table layout, allowing later long parcel names to overprint measurements.
    rows = [dict(row, structure="csf") for _ in range(30)] + [row]
    view = QTextEdit()
    view.setFont(QFont("Arial", 9))
    view.resize(640, 800)
    view.setHtml(report_html({"flair_status": "Not supplied", "posterior_rows": rows,
                             "binary_rows": [], "qc_scores": {}, "model_revision": "synthetic"}))
    view.show()
    app.processEvents()
    tables = view.document().rootFrame().childFrames()
    assert tables[0].format().headerRowCount() == 1, "Continued pages lose the volume units"
    cursor = view.document().find(row["structure"])
    cursor.setPosition(cursor.selectionEnd())
    end_x = view.cursorRect(cursor).x()
    cursor.movePosition(QTextCursor.NextBlock)
    start_x = view.cursorRect(cursor).x()
    view.close()
    assert end_x < start_x, "Anatomical label overlaps the numeric volume column"


@pytest.mark.parametrize("settings", [
    {"profile": "anything"}, {"threads": 0}, {"threads": 9}, {"threads": True},
    {"threads": 2.5}, {"exec": "print(1)"}, {"percentile": 99}, {"crop": 64}, [],
])
def test_planner_rejects_unbounded_or_invented_settings(settings):
    with pytest.raises(BrainError):
        BrainPlan.from_recommendation(settings)


def test_command_preserves_paths_and_forces_qc_without_fast_or_cropping(tmp_path):
    command = [str(x) for x in synthseg_command(tmp_path / "bundle with spaces", tmp_path, BrainPlan("robust"))]
    assert "--qc" in command and "--parc" in command and "--cpu" in command and "--robust" in command
    assert "--fast" not in command and "--crop" not in command
    assert str(tmp_path / "t1.nii.gz") == command[command.index("--i") + 1]


def test_csv_handles_upstream_windows_blank_lines_without_subject_leak(tmp_path):
    path = tmp_path / "vol.csv"
    path.write_bytes(b"subject,total intracranial,left hippocampus\r\r\nPRIVATE,1500000,3420\r\r\n")
    values = read_single_subject_csv(path)
    assert "PRIVATE" not in repr(values)
    row = volume_rows(values)[1]
    assert row["volume_cm3"] == 3.42
    assert row["icv_percent"] == pytest.approx(0.228)
    assert row["percentile"] is None and row["z_score"] is None


@pytest.mark.parametrize("text", [
    "subject,a\n", "subject,a\nx,1\ny,2\n", "subject,a,a\nx,1,2\n",
    "subject,a\nx,nan\n", "subject,a\nx,inf\n", "subject,a\nx,-1\n",
    "subject,a,b\nx,1\n",
])
def test_invalid_model_csv_rejected(tmp_path, text):
    path = tmp_path / "bad.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(BrainError):
        read_single_subject_csv(path)


@pytest.mark.parametrize("values", [{}, {"total intracranial": 0},
                                     {"total intracranial": 10, "hippocampus": 11}])
def test_invalid_icv_is_not_used_as_denominator(values):
    with pytest.raises(BrainError):
        volume_rows(values)


def test_oblique_reflected_affine_uses_determinant():
    affine = np.array([[0, -2, 0, 19], [-0.8, 0, 0, -4], [0, 0, 1.5, 8], [0, 0, 0, 1]])
    assert geometry_voxel_volume(affine) == pytest.approx(2.4)
    affine[3, 0] = 1
    with pytest.raises(BrainError):
        geometry_voxel_volume(affine)


def test_incomplete_bundle_fails_closed(tmp_path):
    with pytest.raises(BrainError, match="bundle"):
        validate_bundle(tmp_path)


def test_nifti_preparation_preserves_geometry_and_discards_metadata(tmp_path):
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain.images import read_volume
    image = sitk.GetImageFromArray(np.arange(120, dtype=np.float32).reshape(4, 5, 6))
    image.SetSpacing((0.8, 1.0, 1.2))
    image.SetOrigin((10, -2, 7))
    image.SetDirection((0, -1, 0, 1, 0, 0, 0, 0, 1))
    image.SetMetaData("descrip", "PRIVATE")
    path = tmp_path / "input.nii.gz"
    sitk.WriteImage(image, str(path))
    clean = read_volume(path)
    assert clean.GetSpacing() == pytest.approx(image.GetSpacing())
    assert clean.GetOrigin() == pytest.approx(image.GetOrigin())
    assert clean.GetDirection() == pytest.approx(image.GetDirection())
    assert not clean.GetMetaDataKeys()
    assert np.array_equal(sitk.GetArrayFromImage(clean), sitk.GetArrayFromImage(image))


def test_invalid_image_is_rejected():
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain.images import validate_image
    with pytest.raises(BrainError):
        validate_image(sitk.Image([8, 8, 8], sitk.sitkFloat32))


def test_report_escapes_names_and_does_not_claim_percentiles():
    from modules.ai_imaging.eagle_eye_brain.report import report_html
    row = {"structure": "<script>", "volume_mm3": 1234, "volume_cm3": 1.234}
    html = report_html({"flair_status": "Not supplied", "posterior_rows": [row], "binary_rows": [row],
                        "qc_scores": {}, "model_revision": "synthetic"})
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "Percentiles and Z-scores are unavailable" in html
    assert "Research / review required" in html


def test_ui_is_lazy_and_existing_tabs_remain_available():
    import ast
    path = Path(__file__).resolve().parents[3] / "modules/ai_imaging/ai_module_ui/ai_mainwindow.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AiMainWindow")
    lazy = next(node for node in owner.body if isinstance(node, ast.FunctionDef) and node.name == "_ensure_lazy_tab")
    assert "BrainVolumetryWidget" not in ast.unparse(lazy)
    from modules.ai_imaging.eagle_eye_workspace import EagleEyeWorkspaceController
    import inspect
    assert "BrainVolumetryWidget" in inspect.getsource(EagleEyeWorkspaceController.open_brain)
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            assert "eagle_eye_brain" not in ast.unparse(node)


def test_precancelled_job_does_not_probe_or_create_artifacts(tmp_path):
    from modules.ai_imaging.eagle_eye_brain.service import run_analysis
    event = threading.Event()
    event.set()
    with pytest.raises(BrainError, match="cancelled"):
        run_analysis("missing.nii", None, tmp_path, cancel=event)
    assert not list(tmp_path.iterdir())


def test_report_pdf_renders_as_a_real_page(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtPdf import QPdfDocument
    from PySide6.QtCore import QSize
    from modules.ai_imaging.eagle_eye_brain.report import report_html, write_pdf
    app = QApplication.instance() or QApplication([])
    # Windows' offscreen platform has no system font discovery. Production uses
    # the Windows platform; explicitly provision a font in this synthetic test.
    if not QFontDatabase.families():
        assert QFontDatabase.addApplicationFont("C:/Windows/Fonts/arial.ttf") >= 0
    row = {"structure": "left hippocampus", "volume_mm3": 1234, "volume_cm3": 1.234, "icv_percent": 0.12}
    html = report_html({"flair_status": "Not supplied", "posterior_rows": [row], "binary_rows": [row],
                        "qc_scores": {"hippocampus": 0.8}, "model_revision": "synthetic"})
    path = tmp_path / "report.pdf"
    write_pdf(html, path)
    document = QPdfDocument()
    assert document.load(str(path)) == QPdfDocument.Error.None_
    assert document.pageCount() >= 1
    assert not document.render(0, QSize(595, 842)).isNull()
    assert "hippocampus" in document.getAllText(0).text()
    document.close()


def test_widget_validation_does_not_start_worker_or_read_files():
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_brain.widget import BrainVolumetryWidget
    app = QApplication.instance() or QApplication([])
    widget = BrainVolumetryWidget()
    widget._start()
    assert widget._future is None
    assert "confirm" in widget.status.text()
    widget._executor.shutdown(wait=False, cancel_futures=True)
    widget.deleteLater()
    app.processEvents()


def test_multipage_pdf_retains_table_headers(tmp_path):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtPdf import QPdfDocument
    from modules.ai_imaging.eagle_eye_brain.report import report_html, write_pdf
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/arial.ttf")
    rows = [{"structure": f"parcel-{index:03d}-rostralanteriorcingulate",
             "volume_mm3": 12345.678, "volume_cm3": 12.346, "icv_percent": 0.823}
            for index in range(150)]
    html = report_html({"flair_status": "Not supplied", "posterior_rows": rows,
                        "binary_rows": [], "qc_scores": {}, "model_revision": "synthetic"})
    path = tmp_path / "multipage.pdf"
    write_pdf(html, path)
    doc = QPdfDocument()
    assert doc.load(str(path)) == QPdfDocument.Error.None_
    assert doc.pageCount() >= 3
    for index in range(doc.pageCount()):
        text = doc.getAllText(index).text()
        if "parcel-" in text:
            # QPdfDocument may split bold glyphs as 'm m 3' on Windows.
            assert "Structure" in text and "mm3" in ''.join(text.split()), "Continued table lost its column headers"
    doc.close()


@pytest.mark.parametrize("report_fails", [False, True])
def test_pipeline_publishes_completion_only_after_artifacts(monkeypatch, tmp_path, report_fails):
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain import service, report
    source = tmp_path / "input.nii.gz"
    sitk.WriteImage(sitk.GetImageFromArray(np.arange(120, dtype=np.float32).reshape(4, 5, 6)), str(source))
    bundle = tmp_path / "bundle"
    labels = bundle / "SynthSeg/data/labels_classes_priors"
    labels.mkdir(parents=True)
    (bundle / "manifest.json").write_text('{"format_version": 1}')
    for kind, suffix in (("segmentation", "_2.0"), ("parcellation", "")):
        np.save(labels / f"synthseg_{kind}_labels{suffix}.npy", np.array([0, 17]))
        np.save(labels / f"synthseg_{kind}_names{suffix}.npy", np.array(["background", "left hippocampus"]))
    monkeypatch.setattr(service, "validate_bundle", lambda root: {"revision": "synthetic"})
    def inference(command, directory, cancel):
        (directory / "posterior.csv").write_text("subject,total intracranial,left hippocampus\nt1,1500000,3420\n")
        (directory / "qc.csv").write_text("subject,hippocampus\nt1,0.8\n")
    monkeypatch.setattr(service, "run_process", inference)
    monkeypatch.setattr(service, "run_slicer", lambda directory, cancel: {"rows": [], "slicer_revision": "synthetic"})
    monkeypatch.setattr(report, "write_pdf", lambda *args: None)
    if report_fails:
        def fail(*args):
            raise RuntimeError("Synthetic report failure")
        monkeypatch.setattr(report, "report_html", fail)
        with pytest.raises(RuntimeError):
            service.run_analysis(source, None, tmp_path / "jobs", bundle=bundle)
        job = next((tmp_path / "jobs").iterdir())
        assert (job / "FAILED").is_file()
        assert not (job / "result.json").exists()
    else:
        result = service.run_analysis(source, None, tmp_path / "jobs", bundle=bundle)
        job = Path(result["artifact_directory"])
        assert (job / "result.json").is_file() and (job / "volumes.csv").is_file()
        assert result["status"] == "review_required"
        assert result["posterior_rows"][1]["percentile"] is None


@pytest.mark.parametrize("case", ["valid", "gap", "ct", "2d", "t2_as_t1", "flair_as_t1", "valid_flair", "t1_as_flair"])
def test_classic_dicom_protocol_and_slice_geometry(tmp_path, case):
    from pydicom.dataset import FileDataset, FileMetaDataset
    from pydicom.uid import generate_uid, ExplicitVRLittleEndian, MRImageStorage, CTImageStorage
    from modules.ai_imaging.eagle_eye_brain.images import read_volume
    study, series, frame = generate_uid(), generate_uid(), generate_uid()
    for index in range(4):
        sop = generate_uid()
        storage = CTImageStorage if case == "ct" else MRImageStorage
        meta = FileMetaDataset()
        meta.MediaStorageSOPClassUID = storage
        meta.MediaStorageSOPInstanceUID = sop
        meta.TransferSyntaxUID = ExplicitVRLittleEndian
        path = tmp_path / f"{index}.dcm"
        ds = FileDataset(str(path), {}, file_meta=meta, preamble=b"\0" * 128)
        ds.SOPClassUID, ds.SOPInstanceUID = storage, sop
        ds.StudyInstanceUID, ds.SeriesInstanceUID, ds.FrameOfReferenceUID = study, series, frame
        ds.PatientName, ds.PatientID = "Synthetic^Brain", "SYNTHETIC"
        ds.Modality = "CT" if case == "ct" else "MR"
        ds.MRAcquisitionType = "2D" if case == "2d" else "3D"
        if case in ("t2_as_t1", "flair_as_t1"):
            ds.SeriesDescription = "t2_space_sag" if case == "t2_as_t1" else "t2_space_flair_sag"
        if case in ("valid_flair", "t1_as_flair"):
            ds.SeriesDescription = "t2_space_flair_sag" if case == "valid_flair" else "t1_mprage_sag"
        ds.Rows, ds.Columns = 5, 6
        ds.ImagePositionPatient = [0, 0, index + (1 if case == "gap" and index == 3 else 0)]
        ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
        ds.PixelSpacing, ds.SliceThickness = [1, 1], 1
        ds.SamplesPerPixel, ds.PhotometricInterpretation = 1, "MONOCHROME2"
        ds.BitsAllocated, ds.BitsStored, ds.HighBit, ds.PixelRepresentation = 16, 16, 15, 0
        ds.PixelData = (np.arange(30, dtype=np.uint16).reshape(5, 6) + index).tobytes()
        ds.is_little_endian, ds.is_implicit_VR = True, False
        ds.save_as(path, write_like_original=False)
    role = "flair" if case in ("valid_flair", "t1_as_flair") else "t1"
    if case in ("valid", "valid_flair"):
        clean = read_volume(tmp_path, expected_protocol=role)
        assert clean.GetSize() == (6, 5, 4)
        assert not clean.GetMetaDataKeys()
    else:
        with pytest.raises(BrainError):
            read_volume(tmp_path, expected_protocol=role)


def test_flair_registration_preserves_fixed_geometry_on_identical_phantom():
    import SimpleITK as sitk
    from modules.ai_imaging.eagle_eye_brain.images import register_flair
    z, y, x = np.mgrid[:32, :32, :32]
    phantom = (100 * np.exp(-((x - 13)**2 + (y - 15)**2 + (z - 18)**2) / 70)
               + 40 * np.exp(-((x - 23)**2 + (y - 8)**2 + (z - 9)**2) / 15)).astype(np.float32)
    fixed = sitk.GetImageFromArray(phantom)
    fixed.SetOrigin((12, -4, 8))
    aligned, transform = register_flair(fixed, fixed, threading.Event())
    assert aligned.GetSize() == fixed.GetSize()
    assert aligned.GetOrigin() == fixed.GetOrigin()
    assert aligned.GetDirection() == fixed.GetDirection()
    center = fixed.TransformIndexToPhysicalPoint((16, 16, 16))
    assert np.linalg.norm(np.asarray(transform.TransformPoint(center)) - center) < 0.5
