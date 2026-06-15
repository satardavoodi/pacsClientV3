"""Guard the adaptive parallel DICOM header scan (patient 46370 slow-open fix, 2026-06-15).

A fully-downloaded 62-series study opened from a server search re-read every DICOM
header on the main thread (~69 ms/file on a slow/I-O-bound disk -> 30-100 s block).
`_read_header_stubs` now adaptively overlaps the per-file reads when the disk is
slow, while staying sequential on a fast SSD. The hard invariant: the result must be
IDENTICAL regardless of read mode/order, because slice ordering downstream depends on
the per-file index — never on completion order.

These tests monkeypatch the pure, thread-safe `_build_instance_header_stub` so they
don't need real DICOM files, and assert completeness + index-correctness +
mode-equivalence (sequential == forced-parallel == auto).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from PacsClient.pacs.patient_tab.utils import image_io


@pytest.fixture
def fake_stub(monkeypatch):
    """Deterministic stub: index + path, so order/index correctness is checkable."""
    def _stub(dicom_file, fallback_index):
        return {"instance_number": fallback_index, "instance_path": str(dicom_file)}
    monkeypatch.setattr(image_io, "_build_instance_header_stub", _stub)
    return _stub


def _files(n):
    return [Path(f"/virtual/series/{k:04d}.dcm") for k in range(1, n + 1)]


@pytest.mark.parametrize("mode", ["0", "force", "auto", "1", "off"])
def test_read_header_stubs_complete_and_index_correct(monkeypatch, fake_stub, mode):
    monkeypatch.setenv("AIPACS_HEADER_SCAN_PARALLEL", mode)
    files = _files(80)  # > _HEADER_SCAN_MIN_FILES so parallel can engage
    stubs = image_io._read_header_stubs(files)

    # Every file produced a stub, keyed by its 1-based index.
    assert set(stubs.keys()) == set(range(1, 81))
    # Each stub kept its own index + path — completion order must not matter.
    for i in range(1, 81):
        assert stubs[i]["instance_number"] == i
        assert stubs[i]["instance_path"] == str(files[i - 1])


def test_modes_produce_identical_results(monkeypatch, fake_stub):
    files = _files(64)
    results = {}
    for mode in ("0", "force", "auto"):
        monkeypatch.setenv("AIPACS_HEADER_SCAN_PARALLEL", mode)
        results[mode] = image_io._read_header_stubs(files)
    # Sequential, forced-parallel and auto must yield the SAME index->stub map.
    assert results["0"] == results["force"] == results["auto"]


def test_small_series_uses_sequential(monkeypatch, fake_stub):
    # Below the min-file threshold the result is still complete & correct.
    monkeypatch.setenv("AIPACS_HEADER_SCAN_PARALLEL", "auto")
    files = _files(5)
    stubs = image_io._read_header_stubs(files)
    assert [stubs[i]["instance_path"] for i in sorted(stubs)] == [str(f) for f in files]


def test_force_parallel_survives_a_failing_file(monkeypatch):
    # A file whose header read returns None is simply skipped (never crashes the
    # pool), and the rest are still read.
    def _stub(dicom_file, fallback_index):
        if fallback_index == 7:
            return None
        return {"instance_number": fallback_index, "instance_path": str(dicom_file)}
    monkeypatch.setattr(image_io, "_build_instance_header_stub", _stub)
    monkeypatch.setenv("AIPACS_HEADER_SCAN_PARALLEL", "force")
    files = _files(40)
    stubs = image_io._read_header_stubs(files)
    assert 7 not in stubs
    assert set(stubs.keys()) == set(range(1, 41)) - {7}


def test_ordering_invariant_after_build(monkeypatch, fake_stub):
    """End-to-end-ish: the index->stub map sorts back to original file order, which
    is what _build_metadata_headers_only relies on before geometry normalization."""
    monkeypatch.setenv("AIPACS_HEADER_SCAN_PARALLEL", "force")
    files = _files(50)
    stubs = image_io._read_header_stubs(files)
    ordered = [stubs[i] for i in sorted(stubs)]
    assert [s["instance_path"] for s in ordered] == [str(f) for f in files]
