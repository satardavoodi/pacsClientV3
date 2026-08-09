"""Guard: case metadata is read from the FILES, not only from the database rows.

WHY THIS EXISTS. Study 53516 opened with Sex, Age, Modality and Study description all
"not detected" and Region(s) reading `chest` for a scan whose own protocol name is
"04 Chest Abd Pelvis". Every one of those facts was sitting in the DICOM on disk. The
SQLite projection is what lost them — measured on this installation:

    patients.sex               3%      series.body_part_examined   7%
    patients.age              12%      series.protocol_name        0%
    studies.study_description 19%

and the mechanism for the demographics is specific and repeatable: the scanned
reception sheet is imported as a `DOC` series into the same study, its folder sorts
FIRST, and it carries no PatientSex. 866 studies here have a DOC series and a NULL
patient sex.

So the region gate cannot be built on those columns, and `read_dicom_facts` reads one
header per series to fill what the database lost. These tests pin the parts that are
easy to break quietly.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from modules.EchoMind import session_metadata as sm

pydicom = pytest.importorskip("pydicom")


def _write_instance(path, **tags):
    """A minimal readable DICOM. `read_dicom_facts` uses force=True, but writing real
    file meta keeps this valid for any reader."""
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.SOPClassUID = ds.file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = ds.file_meta.MediaStorageSOPInstanceUID
    for k, v in tags.items():
        setattr(ds, k, v)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        ds.save_as(path, enforce_file_format=True)      # pydicom >= 3
    except TypeError:                                    # pragma: no cover
        ds.save_as(path, write_like_original=False)      # pydicom 2.x
    return path


@pytest.fixture
def study_dir(tmp_path):
    """The exact shape of study 53516: a DOC reception scan whose folder sorts FIRST
    and carries no demographics, then CT series that carry all of them — including one
    tagged ABDOMEN, because a Chest/Abdomen/Pelvis protocol is one study."""
    root = tmp_path / "1.2.3.4"
    _write_instance(str(root / "100000" / "i.dcm"),
                    Modality="DOC", StudyDescription="Documents",
                    SeriesDescription="Reception 53516")
    for folder, bp in (("101", "CHEST"), ("202", "CHEST"), ("401", "ABDOMEN")):
        _write_instance(str(root / folder / "i.dcm"),
                        Modality="CT", PatientSex="M", PatientAge="019Y",
                        BodyPartExamined=bp, ProtocolName="04 Chest Abd Pelvis")
    return str(root)


# ── the bug that started this ────────────────────────────────────────────────

def test_the_reception_scan_does_not_answer_for_the_patient():
    """THE defect. The DOC series sorts first and has no PatientSex; if it is allowed
    to speak, the study reports no demographics even though every CT slice has them."""
    assert "DOC" in sm._NON_IMAGE_MODALITIES


def test_demographics_come_from_the_image_series(study_dir):
    facts = sm.read_dicom_facts(study_dir)
    assert facts.get("sex") == "M", "the DOC series answered instead of the CT"
    assert facts.get("age") == "019Y"


def test_every_body_part_in_the_study_is_collected(study_dir):
    """A Chest/Abdomen/Pelvis CT gated as `chest` alone silently deletes the abdominal
    reporting rules — the failure mode the whole gating design is built to avoid."""
    assert facts_bp(study_dir) == ["CHEST", "ABDOMEN"]


def facts_bp(study_dir):
    return sm.read_dicom_facts(study_dir).get("body_parts")


def test_protocol_name_is_captured_when_there_is_no_study_description(study_dir):
    facts = sm.read_dicom_facts(study_dir)
    assert facts.get("protocol_name") == "04 Chest Abd Pelvis"
    assert not facts.get("study_description"), (
        "the DOC series' 'Documents' leaked in as the study description"
    )


# ── it must never be able to stop a chat from opening ───────────────────────

def test_a_missing_study_yields_nothing_rather_than_raising():
    """This is not hypothetical: the first cut of read_dicom_facts referenced `os`
    without importing it, `populate_for_chat` swallowed the NameError, and the feature
    looked exactly like a study with no metadata."""
    assert sm.read_dicom_facts(None) == {}
    assert sm.read_dicom_facts("") == {}
    assert sm.read_dicom_facts(os.path.join(_ROOT, "no", "such", "study")) == {}


def test_an_empty_directory_yields_nothing(tmp_path):
    assert sm.read_dicom_facts(str(tmp_path)) == {}


def test_unreadable_files_are_skipped_not_fatal(tmp_path):
    d = tmp_path / "study" / "s1"
    d.mkdir(parents=True)
    (d / "junk.dcm").write_bytes(b"not a dicom at all")
    assert sm.read_dicom_facts(str(tmp_path / "study")) == {}


def test_the_series_scan_is_bounded(study_dir):
    """A pathological study must not stall chat creation."""
    assert sm.read_dicom_facts(study_dir, max_series=1) .get("sex") is None, (
        "max_series is not honoured — only the DOC series should have been read"
    )


# ── the database still wins when it actually has the value ──────────────────

def test_file_facts_only_fill_gaps_they_never_overrule_the_database():
    rec = sm.build_auto_from_context(
        patient={"patient_id": "1", "sex": "F", "age": "40Y"},
        study={"study_uid": "1.2", "study_description": "CT CHEST"},
        dicom_facts={"sex": "M", "age": "019Y", "study_description": "SOMETHING ELSE"},
    )
    assert rec["patient"]["sex"] == "F"
    assert rec["patient"]["age"] == "40Y"
    assert rec["studies"][0]["study_description"] == "CT CHEST"


def test_the_gap_is_filled_and_provenance_says_where_from():
    rec = sm.build_auto_from_context(
        patient={"patient_id": "1"},
        study={"study_uid": "1.2"},
        dicom_facts={"sex": "M", "age": "019Y", "protocol_name": "04 Chest Abd Pelvis"},
    )
    assert rec["patient"]["sex"] == "M"
    assert rec["provenance"]["patient.sex"]["source"] == "dicom_file"
    assert rec["studies"][0]["study_description"] == "04 Chest Abd Pelvis"
    p = rec["provenance"]["studies.0.study_description"]
    assert p["tag"] == "ProtocolName", "a protocol name must not masquerade as a study description"
    assert p["confidence"] == "medium"


def test_sex_is_still_never_inferred():
    """The report prompts forbid guessing sex because guessing produced wrong reports.
    Reading a tag is not inferring; absence must stay absence."""
    rec = sm.build_auto_from_context(
        patient={"patient_id": "1"}, study={"study_uid": "1.2"},
        dicom_facts={"age": "019Y"})
    assert rec["patient"]["sex"] == "unknown"
    assert rec["provenance"]["patient.sex"]["source"] == "none"


def test_regions_widen_from_the_files():
    rec = sm.build_auto_from_context(
        study={"study_uid": "1.2", "body_part": "CHEST"},
        dicom_facts={"body_parts": ["CHEST", "ABDOMEN"]})
    assert rec["case"]["regions"] == ["chest", "abdomen"]
    assert rec["case"]["multi_region"] is True


def test_build_auto_still_works_with_no_facts_at_all():
    rec = sm.build_auto_from_context(study={"study_uid": "1.2", "body_part": "CHEST"})
    assert rec["case"]["regions"] == ["chest"]


# ── the card side of the same problem ───────────────────────────────────────

def test_modality_falls_back_to_what_the_scanner_said():
    """`case.modality_selected` is the physician's CHOICE and is only set once he opens
    the Modalities picker. Reading only that reported "not detected" for a study whose
    modality was never in doubt."""
    from modules.EchoMind.viewer_chat.metadata_panel import FIELDS, _dig_first
    chain = next(f[1] for f in FIELDS if f[0] == "Modality")
    assert not isinstance(chain, str), "Modality has no fallback"
    assert "studies.0.modality" in chain

    rec = {"case": {}, "studies": [{"modality": "CT"}]}
    assert _dig_first(rec, chain) == "CT"
    rec["case"]["modality_selected"] = "MRI"
    assert _dig_first(rec, chain) == "MRI", "the physician's choice must win"


def test_dig_first_accepts_a_plain_string_path():
    from modules.EchoMind.viewer_chat.metadata_panel import _dig_first
    assert _dig_first({"a": {"b": "v"}}, "a.b") == "v"
    assert _dig_first({"a": {}}, "a.b") is None


# ── the reception service axis ───────────────────────────────────────────────

_SERVICES = [
    {"Service": "سی تی اسکن قفسه سینه با و بدون کنتراست", "Qty": 1, "ServiceGroup": "سی تی اسکن"},
    {"Service": "سی تی اسکن شکم و لگن با و بدون تزریق", "Qty": 1, "ServiceGroup": "سی تی اسکن"},
]


def test_the_service_text_reaches_the_card():
    rec = sm.build_auto_from_context(
        patient={"patient_id": "1"}, study={"study_uid": "1.2"},
        reception_services=_SERVICES)
    svc = rec["reception"]["service"]
    assert "قفسه سینه" in svc and "شکم و لگن" in svc, (
        "a study booked as two services must show both — the second one is the "
        "abdomen, and dropping it is how a region gate loses half the study"
    )
    assert rec["provenance"]["reception.service"]["source"] == "reception_api"


def test_the_raw_service_payload_is_kept_for_gating():
    """The card shows text; the gate will want the structured entries, including any
    service code reception starts sending."""
    rec = sm.build_auto_from_context(
        patient={"patient_id": "1"}, study={"study_uid": "1.2"},
        reception_services=_SERVICES)
    assert rec["reception"]["services"] == _SERVICES


def test_no_services_leaves_reception_empty_rather_than_blank_text():
    for empty in (None, [], [None, "junk"]):
        rec = sm.build_auto_from_context(
            patient={"patient_id": "1"}, study={"study_uid": "1.2"},
            reception_services=empty)
        assert not (rec.get("reception") or {}).get("service")
        assert "reception.service" not in rec["provenance"]


def test_a_service_entry_with_no_name_does_not_produce_an_empty_separator():
    rec = sm.build_auto_from_context(
        patient={"patient_id": "1"}, study={"study_uid": "1.2"},
        reception_services=[{"Qty": 1}, {"Service": "real one"}])
    assert rec["reception"]["service"] == "real one"


def test_the_service_field_is_hand_editable_when_nothing_was_cached():
    """Reception is not always reachable, and the physician knowing the service is
    better than nobody knowing it."""
    from modules.EchoMind.viewer_chat.metadata_panel import FIELDS
    label, auto_path, user_path, editable = next(f for f in FIELDS if f[0] == "Service")
    assert editable and user_path == "reception.service"
