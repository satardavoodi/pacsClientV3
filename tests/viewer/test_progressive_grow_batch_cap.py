"""
Phase 3 — Progressive grow batch-cap tests (Fix A).

Root cause: ``scan_series_header_entries`` reads ALL new DICOM headers in a
single call, blocking the main thread for 400-500 ms when 100+ new files
have arrived since the last progressive-grow tick.

Fix A contract:
  • ``scan_series_header_entries`` accepts ``max_new_entries: Optional[int]``.
  • When set to *N*, at most *N* entries are returned even when more new
    files exist (the call truncates early so it returns in ≤ N × ~3 ms).
  • ``Lightweight2DPipeline.refresh_file_list`` passes
    ``max_new_entries = _MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK`` (≤ 64).
  • Source-order contract: the constant ``_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK``
    must be defined in ``lightweight_2d_pipeline.py`` and passed to the
    ``scan_series_header_entries`` call.

Fix B contract (details-panel drag-gate — tested in test_dm_rebuild_drag_skip.py):
  • See test_dm_rebuild_drag_skip.py::test_update_details_drag_gate_source_order
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers — path resolution
# ---------------------------------------------------------------------------

_SCAN_MODULE_PATH = (
    Path(__file__).parent.parent.parent
    / "modules" / "viewer" / "fast" / "dicom_header_scan.py"
)
_PIPELINE_MODULE_PATH = (
    Path(__file__).parent.parent.parent
    / "modules" / "viewer" / "fast" / "lightweight_2d_pipeline.py"
)
_PLUGIN_SCAN_PATH = (
    Path(__file__).parent.parent.parent
    / "builder" / "plugin package" / "packages" / "viewer"
    / "payload" / "python" / "modules" / "viewer" / "fast" / "dicom_header_scan.py"
)
_PLUGIN_PIPELINE_PATH = (
    Path(__file__).parent.parent.parent
    / "builder" / "plugin package" / "packages" / "viewer"
    / "payload" / "python" / "modules" / "viewer" / "fast" / "lightweight_2d_pipeline.py"
)


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# A1: scan_series_header_entries signature — max_new_entries parameter
# ---------------------------------------------------------------------------

def test_scan_entries_signature_has_max_new_entries_canonical():
    """A1-canonical: scan_series_header_entries must accept max_new_entries kwarg."""
    src = _src(_SCAN_MODULE_PATH)
    assert "max_new_entries" in src, (
        "[canonical] scan_series_header_entries is missing the max_new_entries "
        "parameter (Fix A).  Add max_new_entries: Optional[int] = None to the "
        "function signature so the caller can cap I/O per tick."
    )


def test_scan_entries_signature_has_max_new_entries_plugin():
    """A1-plugin: plugin mirror must also have max_new_entries."""
    if not _PLUGIN_SCAN_PATH.exists():
        import pytest; pytest.skip("plugin copy not present")
    src = _src(_PLUGIN_SCAN_PATH)
    assert "max_new_entries" in src, (
        "[plugin] scan_series_header_entries is missing max_new_entries "
        "— plugin copy must stay in parity with canonical."
    )


# ---------------------------------------------------------------------------
# A2: scan_series_header_entries behavioural — cap respected at runtime
# ---------------------------------------------------------------------------

def test_scan_entries_max_new_entries_limits_returned():
    """A2: When max_new_entries=3 and 6 new files exist, at most 3 are returned."""
    from modules.viewer.fast.dicom_header_scan import scan_series_header_entries

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(6):
            f = Path(tmpdir) / f"Instance_{i+1:04d}.dcm"
            f.write_bytes(b"")   # empty files — mocked read below

        # Patch pydicom.dcmread to return a minimal dataset so no real I/O.
        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset
        from pydicom.uid import ExplicitVRLittleEndian

        def _mock_read(path, **kwargs):
            ds = Dataset()
            ds.file_meta = FileMetaDataset()
            ds.is_implicit_VR = False
            ds.is_little_endian = True
            ds.Rows = 512
            ds.Columns = 512
            ds.BitsAllocated = 16
            ds.PixelRepresentation = 1
            ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            ds.InstanceNumber = 1
            return ds

        with patch.object(pydicom, "dcmread", side_effect=_mock_read):
            result = scan_series_header_entries(tmpdir, max_new_entries=3)

    assert len(result) <= 3, (
        f"scan_series_header_entries returned {len(result)} entries despite "
        f"max_new_entries=3.  The batch cap is not being enforced."
    )
    assert len(result) == 3, (
        f"Expected exactly 3 entries (the cap) but got {len(result)}."
    )


def test_scan_entries_no_cap_returns_all():
    """A2b: Without max_new_entries, all new files are returned."""
    from modules.viewer.fast.dicom_header_scan import scan_series_header_entries

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(4):
            f = Path(tmpdir) / f"Instance_{i+1:04d}.dcm"
            f.write_bytes(b"")

        import pydicom
        from pydicom.dataset import Dataset, FileMetaDataset

        def _mock_read(path, **kwargs):
            ds = Dataset()
            ds.Rows = 512; ds.Columns = 512; ds.BitsAllocated = 16
            ds.PixelRepresentation = 1; ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            return ds

        with patch.object(pydicom, "dcmread", side_effect=_mock_read):
            result = scan_series_header_entries(tmpdir)

    assert len(result) == 4, (
        f"Without max_new_entries, all 4 files should be returned (got {len(result)})."
    )


def test_scan_entries_cap_larger_than_file_count_returns_all():
    """A2c: max_new_entries > file count → all files returned (no truncation)."""
    from modules.viewer.fast.dicom_header_scan import scan_series_header_entries

    with tempfile.TemporaryDirectory() as tmpdir:
        for i in range(2):
            f = Path(tmpdir) / f"Instance_{i+1:04d}.dcm"
            f.write_bytes(b"")

        import pydicom
        from pydicom.dataset import Dataset

        def _mock_read(path, **kwargs):
            ds = Dataset()
            ds.Rows = 512; ds.Columns = 512; ds.BitsAllocated = 16
            ds.PixelRepresentation = 1; ds.SamplesPerPixel = 1
            ds.PhotometricInterpretation = "MONOCHROME2"
            return ds

        with patch.object(pydicom, "dcmread", side_effect=_mock_read):
            result = scan_series_header_entries(tmpdir, max_new_entries=100)

    assert len(result) == 2, (
        f"max_new_entries=100 with 2 files should return 2 (got {len(result)})."
    )


# ---------------------------------------------------------------------------
# A3: lightweight_2d_pipeline.py — constant + caller
# ---------------------------------------------------------------------------

def test_pipeline_defines_max_entries_constant_canonical():
    """A3-canonical: pipeline must define _MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK."""
    src = _src(_PIPELINE_MODULE_PATH)
    assert "_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK" in src, (
        "[canonical] lightweight_2d_pipeline.py is missing the constant "
        "_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK.  Add it (e.g. = 32) to cap "
        "progressive-grow I/O per tick to ≤ 96 ms."
    )


def test_pipeline_defines_max_entries_constant_plugin():
    """A3-plugin: plugin mirror must define the same constant."""
    if not _PLUGIN_PIPELINE_PATH.exists():
        import pytest; pytest.skip("plugin copy not present")
    src = _src(_PLUGIN_PIPELINE_PATH)
    assert "_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK" in src, (
        "[plugin] lightweight_2d_pipeline.py is missing _MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK."
    )


def test_pipeline_passes_max_entries_to_scan_canonical():
    """A3b-canonical: refresh_file_list must pass max_new_entries to scan_series_header_entries."""
    src = _src(_PIPELINE_MODULE_PATH)
    # Must contain the kwarg name at the call site (inside refresh_file_list)
    assert "max_new_entries=_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK" in src, (
        "[canonical] refresh_file_list does not pass "
        "max_new_entries=_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK to "
        "scan_series_header_entries.  Without this the batch cap has no effect."
    )


def test_pipeline_passes_max_entries_to_scan_plugin():
    """A3b-plugin: plugin mirror must also pass max_new_entries."""
    if not _PLUGIN_PIPELINE_PATH.exists():
        import pytest; pytest.skip("plugin copy not present")
    src = _src(_PLUGIN_PIPELINE_PATH)
    assert "max_new_entries=_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK" in src, (
        "[plugin] refresh_file_list does not pass max_new_entries."
    )


def test_pipeline_constant_value_is_safe():
    """A3c: _MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK default must be between 8 and 64."""
    src = _src(_PIPELINE_MODULE_PATH)
    import re
    # Match either literal assignment or _env_positive_int call with default value
    m = (
        re.search(r"_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK\s*[:=]+\s*(?:int\s*=\s*)?_env_positive_int\([^,]+,\s*(\d+)\)", src)
        or re.search(r"_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK\s*[:=]+\s*(?:int\s*=\s*)?(\d+)\b", src)
    )
    assert m, (
        "Could not find _MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK = <N> or "
        "_env_positive_int(..., <N>) in pipeline"
    )
    val = int(m.group(1))
    assert 8 <= val <= 64, (
        f"_MAX_PROGRESSIVE_GROW_ENTRIES_PER_TICK default = {val} is outside safe range "
        f"[8, 64].  At 3 ms/file: 8 = 24 ms min, 64 = 192 ms max.  "
        f"Recommended: 32 (96 ms cap)."
    )
