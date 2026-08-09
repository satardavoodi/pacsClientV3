"""Guard: the scanned reception sheet must not answer for the patient (2026-08-08).

A study's demographics are read ONCE per import, from whichever file the caller picked
first. When the study carries a scanned reception sheet, that sheet arrives as a `DOC`
series with no PatientSex and no PatientAge — and if it wins the pick, the patient row
is created blank and never revisited, because nothing reads the study again.

Measured on this installation before the fix:

    studies with no patient sex          2131 / 2191
    of those, studies with a DOC series   866
    patients.sex populated                  3%

while every CT slice in study 53516 carries `M` / `019Y`.
"""

import os
import sys

import pytest

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.normpath(os.path.join(_THIS, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

pydicom = pytest.importorskip("pydicom")
iu = pytest.importorskip("PacsClient.pacs.patient_tab.utils.utils")


def _instance(path, **tags):
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
def doc_and_ct(tmp_path):
    doc = _instance(str(tmp_path / "100000" / "i.dcm"),
                    Modality="DOC", SeriesDescription="Reception 53516")
    ct = _instance(str(tmp_path / "101" / "i.dcm"),
                   Modality="CT", PatientSex="M", PatientAge="019Y",
                   BodyPartExamined="CHEST")
    return doc, ct


def test_the_ct_wins_even_when_the_document_group_comes_first(doc_and_ct):
    doc, ct = doc_and_ct
    assert iu.pick_representative_instance([[doc], [ct]], doc) == ct


def test_order_does_not_matter(doc_and_ct):
    doc, ct = doc_and_ct
    assert iu.pick_representative_instance([[ct], [doc]], doc) == ct


def test_a_study_of_documents_only_behaves_exactly_as_before(doc_and_ct):
    """The fallback is what makes this safe to land: nothing changes for a study that
    has no image series."""
    doc, _ct = doc_and_ct
    assert iu.pick_representative_instance([[doc]], doc) == doc


def test_no_groups_falls_back(doc_and_ct):
    doc, _ct = doc_and_ct
    for empty in ([], None, [[]]):
        assert iu.pick_representative_instance(empty, doc) == doc


def test_an_unreadable_file_does_not_take_the_pick(tmp_path, doc_and_ct):
    _doc, ct = doc_and_ct
    junk = tmp_path / "junk" / "x.dcm"
    junk.parent.mkdir(parents=True, exist_ok=True)
    junk.write_bytes(b"not a dicom")
    assert iu.pick_representative_instance([[str(junk)], [ct]], ct) == ct


def test_a_series_with_no_modality_is_still_eligible(tmp_path, doc_and_ct):
    """Only series we are SURE are non-image are skipped. An untagged instance is not
    evidence of anything, and skipping it would change behaviour for real studies."""
    _doc, _ct = doc_and_ct
    plain = _instance(str(tmp_path / "900" / "i.dcm"), PatientSex="F")
    assert iu.pick_representative_instance([[plain]], "FALLBACK") == plain


def test_the_non_image_set_covers_the_known_offenders():
    for m in ("DOC", "SR", "PR", "KO"):
        assert m in iu._NON_IMAGE_MODALITIES


def test_the_importer_actually_uses_it():
    """The helper is worthless if process_series_groups still takes first_group[0][0]."""
    import io
    p = os.path.join(_ROOT, "PacsClient", "pacs", "patient_tab", "utils", "image_io.py")
    src = io.open(p, encoding="utf-8-sig").read()
    i = src.index("patient_pk_local = utils.get_or_create_patient(first_file)")
    assert "utils.pick_representative_instance(first_group, first_file)" in src[i - 700:i]
