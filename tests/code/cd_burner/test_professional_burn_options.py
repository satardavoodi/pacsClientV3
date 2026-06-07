"""Professional burn options: anonymization, format conversion, collectors,
auto label, verify comparator, and worker pipeline integration (headless)."""

import sys
import types

import numpy as np
import pytest
from pydicom import dcmread
from pydicom.uid import (
    ExplicitVRLittleEndian,
    JPEG2000,
    JPEG2000Lossless,
    RLELossless,
    generate_uid,
)

from modules.cd_burner.cd_burn_manager import (
    BurnOptions,
    CDBurnWorker,
    build_auto_label,
    is_auto_label,
)
from modules.cd_burner.cd_writer import compare_folder_trees
from modules.cd_burner.dicom_prepare import (
    FORMAT_JPEG2000,
    FORMAT_LOSSLESS,
    FORMAT_LOSSY,
    FORMAT_ORIGINAL,
    FORMAT_UNCOMPRESSED,
    DicomPreparer,
)
from modules.cd_burner import content_collectors

from .conftest import write_ct_slice


def _make_study(tmp_path, count=2, name="study", size=(16, 16)):
    study_uid, series_uid = generate_uid(), generate_uid()
    folder = tmp_path / name
    for n in range(1, count + 1):
        write_ct_slice(folder, series_uid, study_uid, n, size=size)
    return folder, study_uid, series_uid


# ---------------------------------------------------------------------------
# Anonymization
# ---------------------------------------------------------------------------

def test_anonymize_replaces_identity_and_remaps_uids(tmp_path):
    folder, study_uid, _series_uid = _make_study(tmp_path, count=2)
    out = tmp_path / "prep"

    preparer = DicomPreparer(anonymize=True, seed=7, dicom_format=FORMAT_ORIGINAL)
    result = preparer.prepare([str(folder)], str(out))

    assert result.total_files == 2
    assert result.skipped_files == 0

    prepared = sorted(out.rglob("*.dcm"))
    assert len(prepared) == 2

    new_study_uids = set()
    for path in prepared:
        ds = dcmread(str(path))
        assert str(ds.PatientName) == "ANONYMOUS^7"
        assert ds.PatientID == "ANON0007"
        assert ds.AccessionNumber == "ANON0007"
        assert str(getattr(ds, "ReferringPhysicianName", "")) == ""
        assert str(getattr(ds, "PatientBirthDate", "")) == ""
        # UIDs remapped away from the originals…
        assert ds.StudyInstanceUID != study_uid
        new_study_uids.add(str(ds.StudyInstanceUID))
        assert ds.file_meta.MediaStorageSOPInstanceUID == ds.SOPInstanceUID
        # …and pixels survive untouched
        assert ds.pixel_array.shape == (16, 16)
    # consistent remap: both files share ONE new study UID
    assert len(new_study_uids) == 1


def test_anonymize_keeps_clinical_tags(tmp_path):
    folder, *_ = _make_study(tmp_path, count=1)
    out = tmp_path / "prep"
    DicomPreparer(anonymize=True, seed=3).prepare([str(folder)], str(out))
    ds = dcmread(str(next(out.rglob("*.dcm"))))
    assert ds.Modality == "CT"
    assert ds.SeriesDescription  # kept
    assert ds.WindowCenter is not None


# ---------------------------------------------------------------------------
# Format conversion
# ---------------------------------------------------------------------------

def _prepare_single(tmp_path, dicom_format, size=(16, 16), **prep_kwargs):
    # NOTE: openjpeg's encoder uses 6 fixed DWT resolutions and rejects tiny
    # images — J2K tests use 64x64 (production images are far larger; smaller
    # ones fall back to original syntax with a warning by design).
    folder, *_ = _make_study(tmp_path, count=1, name=f"s_{dicom_format}", size=size)
    out = tmp_path / f"prep_{dicom_format}"
    preparer = DicomPreparer(dicom_format=dicom_format, **prep_kwargs)
    result = preparer.prepare([str(folder)], str(out))
    files = sorted(out.rglob("*.dcm"))
    return result, files, folder


def test_passthrough_when_original_and_no_anonymize(tmp_path):
    folder, *_ = _make_study(tmp_path, count=1)
    preparer = DicomPreparer(anonymize=False, dicom_format=FORMAT_ORIGINAL)
    result = preparer.prepare([str(folder)], str(tmp_path / "unused"))
    assert result.passthrough
    assert result.prepared_folders == [str(folder)]


def test_convert_to_rle_lossless_roundtrip(tmp_path):
    result, files, folder = _prepare_single(tmp_path, FORMAT_LOSSLESS)
    assert result.converted_files == 1 and result.fallback_files == 0
    original = dcmread(str(next(folder.rglob("*.dcm"))))
    converted = dcmread(str(files[0]))
    assert converted.file_meta.TransferSyntaxUID == RLELossless
    assert np.array_equal(converted.pixel_array, original.pixel_array)


def test_convert_to_jpeg2000_lossless_roundtrip(tmp_path):
    result, files, folder = _prepare_single(tmp_path, FORMAT_JPEG2000, size=(64, 64))
    assert result.converted_files == 1 and result.fallback_files == 0
    original = dcmread(str(next(folder.rglob("*.dcm"))))
    converted = dcmread(str(files[0]))
    assert converted.file_meta.TransferSyntaxUID == JPEG2000Lossless
    assert np.array_equal(converted.pixel_array, original.pixel_array)


def test_convert_to_lossy_marks_compression(tmp_path):
    result, files, _folder = _prepare_single(tmp_path, FORMAT_LOSSY, size=(64, 64))
    assert result.converted_files == 1
    converted = dcmread(str(files[0]))
    assert converted.file_meta.TransferSyntaxUID == JPEG2000
    assert converted.LossyImageCompression == "01"
    assert converted.pixel_array.shape == (64, 64)  # decodes


def test_compressed_source_to_uncompressed(tmp_path):
    folder, study_uid, series_uid = _make_study(tmp_path, count=1, name="rle_src")
    # Re-compress the source file to RLE first
    src = next(folder.rglob("*.dcm"))
    ds = dcmread(str(src))
    ds.compress(RLELossless)
    ds.save_as(str(src), write_like_original=False)

    out = tmp_path / "prep_unc"
    result = DicomPreparer(dicom_format=FORMAT_UNCOMPRESSED).prepare([str(folder)], str(out))
    assert result.converted_files == 1
    converted = dcmread(str(next(out.rglob("*.dcm"))))
    assert converted.file_meta.TransferSyntaxUID == ExplicitVRLittleEndian
    assert converted.pixel_array.shape == (16, 16)


def test_conversion_failure_falls_back_to_original(tmp_path, monkeypatch):
    folder, *_ = _make_study(tmp_path, count=1, name="fb")
    out = tmp_path / "prep_fb"
    preparer = DicomPreparer(dicom_format=FORMAT_LOSSLESS)
    monkeypatch.setattr(
        preparer, "_transcode",
        lambda ds: (_ for _ in ()).throw(RuntimeError("encoder boom")),
    )
    result = preparer.prepare([str(folder)], str(out))
    assert result.fallback_files == 1
    assert result.total_files == 1  # file still exported in original form
    ds = dcmread(str(next(out.rglob("*.dcm"))))
    assert ds.pixel_array.shape == (16, 16)


def test_anonymize_failure_excludes_file(tmp_path, monkeypatch):
    folder, *_ = _make_study(tmp_path, count=1, name="anonfail")
    out = tmp_path / "prep_af"
    preparer = DicomPreparer(anonymize=True)
    monkeypatch.setattr(
        preparer, "_anonymize",
        lambda ds: (_ for _ in ()).throw(RuntimeError("anon boom")),
    )
    result = preparer.prepare([str(folder)], str(out))
    assert result.total_files == 0
    assert result.skipped_files == 1
    assert not list(out.rglob("*.dcm"))  # nothing identified leaked


# ---------------------------------------------------------------------------
# Auto label
# ---------------------------------------------------------------------------

def test_is_auto_label_values():
    assert is_auto_label("")
    assert is_auto_label("  ")
    assert is_auto_label("[Auto Label]")
    assert is_auto_label("AUTO")
    assert not is_auto_label("PATIENT_CD")


def test_build_auto_label_patient_and_anon():
    label = build_auto_label(patient_name="BARAHOYI^SOMAYEH", study_date="20260101")
    assert label.startswith("BARAHOYI 20260101")
    assert len(label) <= 32

    anon = build_auto_label(patient_name="X", anonymized=True, seed=12)
    assert anon.startswith("ANON0012")
    assert "X" not in anon.split()[0]


# ---------------------------------------------------------------------------
# Burn-image filesystem choice (regression guard for the 8.3-mangling bug)
# ---------------------------------------------------------------------------

def test_burn_image_always_includes_joliet():
    """ISO9660-only (=1) mangles long names to DOS 8.3 (_internal → _INTER~1)
    which breaks the bundled PyInstaller viewer on other PCs. Every media
    type must produce ISO9660 + Joliet (=3). See pipeline doc §10."""
    from modules.cd_burner.cd_writer import filesystems_for_media

    for media_type in (None, 0, 1, 2, 3, 5, 8, 15):
        assert filesystems_for_media(media_type) == 3


# ---------------------------------------------------------------------------
# Verify comparator
# ---------------------------------------------------------------------------

def test_compare_folder_trees_matches_and_detects(tmp_path):
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    (src / "sub").mkdir(parents=True)
    (src / "a.bin").write_bytes(b"A" * 1000)
    (src / "sub" / "b.bin").write_bytes(b"B" * 500)
    import shutil

    shutil.copytree(src, dst)

    ok, message, details = compare_folder_trees(str(src), str(dst))
    assert ok and details["verified"] == 2

    # Case-folded names still match (ISO9660 tolerance)
    (dst / "a.bin").rename(dst / "A.BIN")
    ok, *_ = compare_folder_trees(str(src), str(dst))
    assert ok

    # Tampered content (same size) → hash mismatch
    (dst / "sub" / "b.bin").write_bytes(b"B" * 499 + b"X")
    ok, message, details = compare_folder_trees(str(src), str(dst))
    assert not ok and details["hash_mismatch"] == ["sub/b.bin"]

    # Missing file
    (dst / "sub" / "b.bin").unlink()
    ok, _message, details = compare_folder_trees(str(src), str(dst))
    assert not ok and details["missing"] == ["sub/b.bin"]


# ---------------------------------------------------------------------------
# Content collectors
# ---------------------------------------------------------------------------

def test_collect_images_and_attachments_split(tmp_path, monkeypatch):
    study_uid = "1.2.3.4.5"
    attach_root = tmp_path / "attachments"
    study_dir = attach_root / study_uid
    study_dir.mkdir(parents=True)
    (study_dir / "capture1.png").write_bytes(b"PNG")
    (study_dir / "photo.jpg").write_bytes(b"JPG")
    (study_dir / "doc.pdf").write_bytes(b"PDF")
    (study_dir / "voice.mp3").write_bytes(b"MP3")

    import PacsClient.utils.config as config_module

    monkeypatch.setattr(config_module, "ATTACHMENT_PATH", attach_root, raising=False)

    studies = [{"study_uid": study_uid, "patient_id": "P1"}]
    dest = tmp_path / "media"

    images = content_collectors.collect_images(studies, str(dest))
    assert images.count == 2
    assert all("JPEG" in f for f in images.files)

    attachments = content_collectors.collect_attachments(studies, str(dest))
    assert attachments.count == 2
    assert all("ATTACHMENTS" in f for f in attachments.files)


def test_collect_reports_via_stubbed_db(tmp_path, monkeypatch):
    stub = types.ModuleType("database.ai_reception_db")

    def ai_get_reception_reports(patient_id=None, study_uid=None, status=None, limit=None):
        if study_uid == "S1":
            return [{"id": 11, "patient_id": "P1", "html_content": "<p>Liver normal.</p>"}]
        return []

    stub.ai_get_reception_reports = ai_get_reception_reports
    monkeypatch.setitem(sys.modules, "database.ai_reception_db", stub)

    dest = tmp_path / "media"
    result = content_collectors.collect_reports(
        [{"study_uid": "S1", "patient_id": "P1"}], str(dest)
    )
    assert result.count == 1
    html = (dest / "REPORTS" / "P1" / "report_11.html").read_text(encoding="utf-8")
    assert "Liver normal" in html
    assert "<html" in html.lower()  # wrapped into a full document


def test_collect_reports_subsystem_missing(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "database.ai_reception_db", None)
    result = content_collectors.collect_reports([{"study_uid": "S1"}], str(tmp_path))
    assert result.count == 0
    assert result.warnings


# ---------------------------------------------------------------------------
# Worker pipeline integration (headless, no disc)
# ---------------------------------------------------------------------------

def test_worker_prepare_folder_with_anonymize_and_uncompressed(tmp_path):
    folder, study_uid, _ = _make_study(tmp_path, count=2, name="wstudy")
    staging = tmp_path / "out"

    worker = CDBurnWorker(
        studies=[{
            "study_uid": study_uid,
            "study_path": str(folder),
            "patient_name": "TEST^PATIENT",
            "patient_id": "PID-CD-001",
        }],
        disc_label="",  # auto label
        output_folder=str(staging),
        burn_to_disc=False,
        options=BurnOptions(
            anonymize=True,
            anonymize_seed=42,
            dicom_format=FORMAT_UNCOMPRESSED,
        ),
    )

    outcomes = []
    worker.completed.connect(lambda ok, message: outcomes.append((ok, message)))
    worker.run()  # synchronous

    assert outcomes and outcomes[0][0], f"pipeline failed: {outcomes}"
    assert (staging / "DICOMDIR").exists()
    assert (staging / "START_HERE.txt").exists()

    # Every exported DICOM is anonymized
    from pydicom.fileset import FileSet
    import warnings as _warnings

    with _warnings.catch_warnings():
        _warnings.simplefilter("ignore", DeprecationWarning)
        fs = FileSet(str(staging / "DICOMDIR"))
    instances = list(fs)
    assert len(instances) == 2
    for instance in instances:
        ds = dcmread(str(instance.path))
        assert str(ds.PatientName) == "ANONYMOUS^42"
        assert ds.StudyInstanceUID != study_uid


def test_worker_legacy_call_still_works(tmp_path):
    """No options passed → legacy behavior (original pipeline)."""
    folder, study_uid, _ = _make_study(tmp_path, count=1, name="legacy")
    staging = tmp_path / "legacy_out"

    worker = CDBurnWorker(
        studies=[{"study_uid": study_uid, "study_path": str(folder), "patient_name": "X"}],
        disc_label="PATIENT_CD",
        output_folder=str(staging),
        burn_to_disc=False,
    )
    outcomes = []
    worker.completed.connect(lambda ok, message: outcomes.append((ok, message)))
    worker.run()

    assert outcomes and outcomes[0][0]
    ds = dcmread(str(next((staging).rglob("IM*"))), stop_before_pixels=True)
    assert str(ds.PatientName) == "TEST^PATIENT"  # untouched
