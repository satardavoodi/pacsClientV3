"""Guard: de-duplicated + tag-scoped header scan in ``_build_metadata_headers_only``.

Fix A (2026-06-08): the FAST ``pydicom_qt`` load fell back to a scan of every
DICOM header when DB metadata was unavailable (server-opened studies), costing
~712 ms for 303 files / ~1424 ms for 428.

The first attempt parallelized the scan with a thread pool, but a live re-measure
(patient 45557, series 202, 476 files) + a micro-benchmark proved pydicom header
*parsing* is GIL-bound, so the pool ran ~2x SLOWER than sequential (479 ms ->
922 ms).  The pool was reverted.  The two speedups that actually help are kept:
  * ONE header read per file (the old loop did a throwaway second read per file
    just to capture series-level metadata), and
  * ``specific_tags`` so each read parses only the ~16 fields the stub needs
    (479 ms -> 395 ms).

These guards lock in the behavioural invariants that must survive the change:
  1. Slice ordering is by 1-based index, stable regardless of read timing.
  2. Each instance header is read exactly once (no double read).
  3. The series-level header is read exactly once total (not once per file).
  4. The per-instance read is scoped with ``specific_tags`` covering every field
     the stub emits.
  5. Empty / all-unreadable series still return ``None``.
"""
import importlib
import time

import pytest


@pytest.fixture
def image_io():
    return importlib.import_module("PacsClient.pacs.patient_tab.utils.image_io")


class _DcmStub(dict):
    """Minimal pydicom-dataset-like object exposing ``.get``."""

    def get(self, key, default=None):
        return dict.get(self, key, default)


def test_scan_preserves_order_and_dedups(image_io, monkeypatch):
    files = [f"/fake/series/IM{n:04d}.dcm" for n in range(1, 51)]
    monkeypatch.setattr(image_io, "_list_unique_dicom_files", lambda p: list(files))

    stub_calls = []

    def fake_stub(dicom_file, idx):
        # Tiny jitter; order must still come out by index regardless of timing.
        time.sleep(0.001 if idx % 3 == 0 else 0.0)
        stub_calls.append((str(dicom_file), idx))
        return {
            "instance_number": idx,
            "instance_path": str(dicom_file),
            "image_orientation_patient": None,
        }

    monkeypatch.setattr(image_io, "_build_instance_header_stub", fake_stub)

    safe_calls = []

    def fake_safe_dcmread(path, stop_before_pixels=True):
        safe_calls.append(str(path))
        return _DcmStub({"SeriesDescription": "S", "Modality": "CT"})

    monkeypatch.setattr(image_io.utils, "_safe_dcmread", fake_safe_dcmread)

    meta = image_io._build_metadata_headers_only(image_io.Path("/fake/series"), "202")

    assert meta is not None
    insts = meta["instances"]
    # (1) strict index order, all present, despite shuffled completion timing
    assert [i["instance_number"] for i in insts] == list(range(1, 51))
    # (2) one stub read per file, not two
    assert len(stub_calls) == 50
    # (3) series-level header read exactly once (old code re-read every file)
    assert len(safe_calls) == 1
    # series-level read targets the first instance's file
    assert safe_calls[0] == insts[0]["instance_path"]


def test_skipped_unreadable_files_do_not_shift_order(image_io, monkeypatch):
    files = [f"/fake/series/IM{n:04d}.dcm" for n in range(1, 11)]
    monkeypatch.setattr(image_io, "_list_unique_dicom_files", lambda p: list(files))

    def fake_stub(dicom_file, idx):
        # Files 3 and 7 are unreadable -> stub returns None (as real code does).
        if idx in (3, 7):
            return None
        return {"instance_number": idx, "instance_path": str(dicom_file),
                "image_orientation_patient": None}

    monkeypatch.setattr(image_io, "_build_instance_header_stub", fake_stub)
    monkeypatch.setattr(image_io.utils, "_safe_dcmread",
                        lambda p, stop_before_pixels=True: _DcmStub({"Modality": "CT"}))

    meta = image_io._build_metadata_headers_only(image_io.Path("/fake/series"), "9")
    nums = [i["instance_number"] for i in meta["instances"]]
    # surviving instances keep ascending index order; the two bad files dropped
    assert nums == [1, 2, 4, 5, 6, 8, 9, 10]


def test_tiny_series_sequential_path(image_io, monkeypatch):
    files = ["/f/IM1.dcm", "/f/IM2.dcm"]
    monkeypatch.setattr(image_io, "_list_unique_dicom_files", lambda p: list(files))
    monkeypatch.setattr(
        image_io, "_build_instance_header_stub",
        lambda f, i: {"instance_number": i, "instance_path": str(f),
                      "image_orientation_patient": None},
    )
    monkeypatch.setattr(image_io.utils, "_safe_dcmread",
                        lambda p, stop_before_pixels=True: _DcmStub({"Modality": "CT"}))
    meta = image_io._build_metadata_headers_only(image_io.Path("/f"), "5")
    assert [i["instance_number"] for i in meta["instances"]] == [1, 2]


def test_empty_series_returns_none(image_io, monkeypatch):
    monkeypatch.setattr(image_io, "_list_unique_dicom_files", lambda p: [])
    assert image_io._build_metadata_headers_only(image_io.Path("/x"), "1") is None


def test_all_unreadable_returns_none(image_io, monkeypatch):
    monkeypatch.setattr(image_io, "_list_unique_dicom_files",
                        lambda p: ["/f/a.dcm", "/f/b.dcm", "/f/c.dcm"])
    monkeypatch.setattr(image_io, "_build_instance_header_stub", lambda f, i: None)
    assert image_io._build_metadata_headers_only(image_io.Path("/f"), "1") is None


def test_stub_reads_with_specific_tags(image_io, monkeypatch):
    """The per-instance read must scope to ``_HEADER_STUB_TAGS`` (the GIL-bound
    parse cost is what specific_tags trims)."""
    seen = {}

    def fake_safe_dcmread(path, stop_before_pixels=True, specific_tags=None):
        seen["specific_tags"] = specific_tags
        seen["stop_before_pixels"] = stop_before_pixels
        return _DcmStub({"InstanceNumber": 7, "Rows": 512, "Columns": 512})

    monkeypatch.setattr(image_io.utils, "_safe_dcmread", fake_safe_dcmread)
    stub = image_io._build_instance_header_stub(image_io.Path("/f/IM1.dcm"), 1)
    assert stub is not None
    assert seen["stop_before_pixels"] is True
    assert seen["specific_tags"] is image_io._HEADER_STUB_TAGS


def test_header_stub_tag_list_covers_geometry_fields(image_io):
    """Ordering/rendering depend on these — guard against the list being
    truncated so a needed tag silently parses as None."""
    required = {
        "InstanceNumber", "ImageOrientationPatient", "ImagePositionPatient",
        "PixelSpacing", "Rows", "Columns", "RescaleSlope", "RescaleIntercept",
        "BitsAllocated", "PixelRepresentation", "WindowWidth", "WindowCenter",
    }
    assert required.issubset(set(image_io._HEADER_STUB_TAGS))
