"""Guards for image-sourced viewport overlay identity (2026-07-19).

THE CLINICAL DEFECT THIS PROTECTS AGAINST
-----------------------------------------
The four-corner overlay used to read patient/study identity from a tab-level
``metadata_fixed`` dict sourced from the local DB ``patients`` row, keyed by
``patient_id`` — which is UNIQUE. Two different people accidentally sent under
one Patient ID therefore collapsed to a single DB row, and the overlay painted
the SAME (first-imported) name on BOTH patients' images. The fix reads the
identity tags from the DISPLAYED series' own first-instance DICOM header, so the
overlay matches the pixels on screen regardless of DB inconsistencies.

The decisive test here (`test_two_series_same_db_row_show_their_own_identity`)
reproduces that exact scenario with real synthetic DICOM and asserts each
image's own identity wins.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")

from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

from PacsClient.utils import overlay_identity_source as ois
from PacsClient.utils.overlay_metadata import build_overlay_metadata


# ---------------------------------------------------------------------------
# Synthetic DICOM
# ---------------------------------------------------------------------------


def _write_instance(path: Path, **tags):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = tags.get("StudyInstanceUID", generate_uid())
    ds.SeriesInstanceUID = tags.get("SeriesInstanceUID", generate_uid())

    ds.PatientName = tags.get("PatientName", "DOE^JOHN")
    ds.PatientID = tags.get("PatientID", "PID1")
    ds.PatientSex = tags.get("PatientSex", "M")
    ds.PatientAge = tags.get("PatientAge", "045Y")
    ds.StudyDate = tags.get("StudyDate", "20260718")
    ds.StudyTime = tags.get("StudyTime", "101010")
    ds.InstitutionName = tags.get("InstitutionName", "Alizadeh Imaging")
    ds.SeriesDescription = tags.get("SeriesDescription", "AX T2")
    ds.Modality = tags.get("Modality", "MR")

    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)
    return path


@pytest.fixture(autouse=True)
def _clear_reader_cache():
    ois.clear_cache()
    yield
    ois.clear_cache()


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def test_reads_identity_tags_from_header(tmp_path):
    p = _write_instance(tmp_path / "s" / "IM0.dcm", PatientName="SMITH^ANNA", PatientID="X9")
    tags = ois.read_identity_tags(p)
    assert tags["patient_name"] == "SMITH^ANNA"
    assert tags["patient_id"] == "X9"
    assert tags["institution_name"] == "Alizadeh Imaging"
    assert tags["study_date"] == "20260718"
    assert tags["study_time"] == "101010"
    assert tags["patient_sex"] == "M"
    assert tags["patient_age"] == "045Y"


def test_missing_tag_maps_to_empty_string(tmp_path):
    # A file with no InstitutionName -> "" (which the trunk treats as missing).
    p = tmp_path / "s" / "IM0.dcm"
    _write_instance(p, InstitutionName="")
    tags = ois.read_identity_tags(p)
    assert tags["institution_name"] == ""


def test_empty_or_bad_path_returns_empty_dict(tmp_path):
    assert ois.read_identity_tags("") == {}
    assert ois.read_identity_tags(None) == {}
    assert ois.read_identity_tags(str(tmp_path / "does_not_exist.dcm")) == {}


def test_read_is_cached_by_path(tmp_path):
    p = _write_instance(tmp_path / "s" / "IM0.dcm", PatientName="A^B")
    ois.read_identity_tags(p)
    assert str(p) in ois._cache


def test_cache_is_invalidated_on_mtime_change(tmp_path):
    """A file rewritten in place (e.g. by the demographic-tag editor) must be
    re-read, not served a stale cached identity."""
    p = _write_instance(tmp_path / "s" / "IM0.dcm", PatientName="OLD^NAME")
    assert ois.read_identity_tags(p)["patient_name"] == "OLD^NAME"

    import os
    _write_instance(p, PatientName="NEW^NAME")
    os.utime(p, (p.stat().st_atime + 5, p.stat().st_mtime + 5))  # force a newer mtime

    assert ois.read_identity_tags(p)["patient_name"] == "NEW^NAME"


def test_read_series_identity_from_instances_uses_first_instance(tmp_path):
    p = _write_instance(tmp_path / "s" / "IM0.dcm", PatientName="FIRST^ONE")
    instances = [{"instance_path": str(p)}, {"instance_path": "ignored"}]
    tags = ois.read_series_identity_from_instances(instances)
    assert tags["patient_name"] == "FIRST^ONE"
    assert ois.read_series_identity_from_instances([]) == {}
    assert ois.read_series_identity_from_instances(None) == {}


def test_reader_never_raises_on_garbage_file(tmp_path):
    """Must never raise, and must never invent a value. pydicom(force=True)
    parses garbage into an EMPTY dataset rather than raising, so the reader
    returns all-empty values — which the trunk treats as missing and fills from
    the DB. Either an empty dict or an all-empty dict is acceptable; a non-empty
    value would be the dangerous outcome."""
    junk = tmp_path / "s" / "junk.dcm"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"not a dicom file at all")
    result = ois.read_identity_tags(junk)  # must not raise
    assert all(v == "" for v in result.values()), (
        f"garbage file produced a non-empty value: {result}"
    )


# ---------------------------------------------------------------------------
# THE decisive safety scenario: two patients, one Patient ID
# ---------------------------------------------------------------------------


def test_two_series_same_db_row_show_their_own_identity(tmp_path):
    """Two different patients sent under ONE Patient ID. The DB row (metadata_
    fixed) carries only the FIRST patient's name. Each image must still show its
    OWN name because the DICOM header is the authority."""
    alice = _write_instance(
        tmp_path / "a" / "IM0.dcm", PatientName="ALICE^A", PatientID="DUP1",
        InstitutionName="Clinic A",
    )
    bob = _write_instance(
        tmp_path / "b" / "IM0.dcm", PatientName="BOB^B", PatientID="DUP1",
        InstitutionName="Clinic B",
    )

    # The single DB row both studies resolve to (first import won).
    db_row = {"patient_name": "ALICE^A", "patient_id": "DUP1", "institution_name": "Clinic A"}

    def overlay_for(first_instance_path):
        image_tags = ois.read_series_identity_from_instances(
            [{"instance_path": str(first_instance_path)}]
        )
        return build_overlay_metadata(dicom=image_tags, db=db_row, name_pref="english")

    a = overlay_for(alice)
    b = overlay_for(bob)

    assert a["patient_name"] == "ALICE A"
    assert b["patient_name"] == "BOB B", (
        "Bob's image showed the DB row's name (Alice) — the exact reported bug"
    )
    assert b["institution_name"] == "Clinic B"


def test_image_wins_but_db_fills_a_genuinely_absent_tag(tmp_path):
    """Chosen policy: image wins; fall back to DB only when the image lacks the
    tag; NA only when both are empty."""
    p = _write_instance(
        tmp_path / "s" / "IM0.dcm", PatientName="CARL^C", InstitutionName="",
    )
    db_row = {"patient_name": "WRONG^NAME", "institution_name": "DB Hospital"}
    image_tags = ois.read_series_identity_from_instances([{"instance_path": str(p)}])
    overlay = build_overlay_metadata(dicom=image_tags, db=db_row, name_pref="english")

    assert overlay["patient_name"] == "CARL C"          # image wins over DB
    assert overlay["institution_name"] == "DB Hospital"  # image blank -> DB fills


def test_na_only_when_both_image_and_db_missing(tmp_path):
    p = _write_instance(tmp_path / "s" / "IM0.dcm", InstitutionName="")
    image_tags = ois.read_series_identity_from_instances([{"instance_path": str(p)}])
    overlay = build_overlay_metadata(dicom=image_tags, db={}, name_pref="english")
    assert overlay["institution_name"] == "NA"


# ---------------------------------------------------------------------------
# Wiring source-pins (the flag + the correct slot assignment)
# ---------------------------------------------------------------------------


def _src(rel: str) -> str:
    root = Path(__file__).resolve().parents[3]
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


def test_fast_bridge_feeds_image_tags_as_dicom_source():
    src = _src("modules/viewer/fast/qt_viewer_bridge.py")
    assert "_OVERLAY_IMAGE_IDENTITY" in src
    assert "AIPACS_OVERLAY_IMAGE_IDENTITY" in src
    # default ON: unset env -> '1' -> != '0' -> True
    assert "os.getenv('AIPACS_OVERLAY_IMAGE_IDENTITY', '1')" in src
    # the block must feed image tags to dicom= and the DB copy to db=
    block = src.split("if _OVERLAY_IMAGE_IDENTITY:", 1)[1].split("elif _CANONICAL_OVERLAY_METADATA:", 1)[0]
    assert "read_series_identity_from_instances" in block
    assert "dicom=image_tags" in block
    assert "db=fixed" in block


def test_advanced_viewer_has_image_identity_helper_and_uses_it():
    src = _src("modules/viewer/advanced/viewer_2d.py")
    assert "_OVERLAY_IMAGE_IDENTITY" in src
    assert "def _overlay_identity" in src
    # top-left identity must read from the helper, not straight from metadata_fixed
    tl = src.split("def load_top_left_actors", 1)[1][:900]
    assert "_overlay_identity()" in tl
    assert "_ident['patient_name']" in tl
    # bottom-right institution too
    br = src.split("def load_bottom_right_actors", 1)[1][:700]
    assert "_overlay_identity()" in br


def test_advanced_helper_feeds_image_tags_as_dicom_source():
    src = _src("modules/viewer/advanced/viewer_2d.py")
    block = src.split("def _overlay_identity", 1)[1].split("def _update_corners_actors_impl", 1)[0]
    assert "read_series_identity_from_instances" in block
    assert "dicom=image_tags" in block
    assert "db=(self.metadata_fixed or {})" in block
    assert "missing=\"N/A\"" in block  # keep this viewer's N/A sentinel


def test_flag_default_on_in_both_viewers():
    for rel in ("modules/viewer/fast/qt_viewer_bridge.py",
                "modules/viewer/advanced/viewer_2d.py"):
        src = _src(rel)
        assert "os.getenv('AIPACS_OVERLAY_IMAGE_IDENTITY', '1')" in src
        assert ".strip() != '0'" in src


def test_reader_scope_is_identity_only_not_geometry_or_series_identity():
    """The reader must not capture series identity (SeriesInstanceUID / number),
    geometry, or slice ordering — those are owned downstream."""
    src = _src("PacsClient/utils/overlay_identity_source.py")
    tag_block = src.split("_IDENTITY_TAGS", 1)[1].split("}", 1)[0]
    for forbidden in ("SeriesInstanceUID", "SeriesNumber", "ImagePositionPatient",
                      "ImageOrientationPatient", "InstanceNumber"):
        assert forbidden not in tag_block
