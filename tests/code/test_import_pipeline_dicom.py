"""Import-pipeline validation: compressed DICOM end-to-end (2026-06-06).

Validates the Home-Page Import workflow per the review:
  scan (detection + metadata + compatibility report) → import (copy or
  decompress-on-import) → stored files usable WITHOUT runtime codecs →
  metadata preserved → multi-study / large-series / non-image handling.

Uses pydicom's bundled test data so real JPEG 2000 / RLE / JPEG-lossless
encodings are exercised (files marked skip when a given sample or codec
isn't available in the environment).
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

pydicom = pytest.importorskip("pydicom")
np = pytest.importorskip("numpy")
pytest.importorskip("PySide6.QtWidgets")  # import_preview_dialog imports Qt

from PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog import (  # noqa: E402
    _decompress_file_to_destination,
    _detect_decoder_capabilities,
    _import_decompression_enabled,
    _is_transfer_syntax_supported,
    import_scanned_dicom_studies,
    scan_dicom_import_folder,
)

_SRC = (
    _REPO_ROOT
    / "PacsClient/pacs/workstation_ui/home_ui/import_preview_dialog.py"
).read_text(encoding="utf-8")


def _testdata(name: str):
    """Bundled pydicom sample path or None (external/missing → skip)."""
    try:
        from pydicom.data import get_testdata_file
        p = get_testdata_file(name)
        return Path(p) if p and Path(p).exists() else None
    except Exception:
        return None


_UNCOMPRESSED = _testdata("CT_small.dcm")
_RLE = _testdata("MR_small_RLE.dcm")
_J2K = _testdata("US1_J2KR.dcm") or _testdata("JPEG2000.dcm")
_JPEG_LOSSLESS = _testdata("JPGLosslessP14SV1_1s_1f_8b.dcm")
_NON_IMAGE = _testdata("rtplan.dcm")

_CAPS = _detect_decoder_capabilities()


def _make_folder(tmp_path: Path, files: list[Path]) -> Path:
    src_dir = tmp_path / "incoming"
    src_dir.mkdir(parents=True, exist_ok=True)
    for i, f in enumerate(files):
        shutil.copy2(f, src_dir / f"f{i}_{f.name}")
    return src_dir


def _all_imported_files(out_dir: Path) -> list[Path]:
    return [p for p in out_dir.rglob("*.dcm") if p.is_file()]


# ── 1. scan: detection, metadata, multi-study, compatibility report ───────
@pytest.mark.skipif(_UNCOMPRESSED is None or _RLE is None,
                    reason="pydicom test data unavailable")
def test_scan_detects_studies_metadata_and_compression(tmp_path):
    files = [f for f in (_UNCOMPRESSED, _RLE, _J2K, _NON_IMAGE) if f]
    src_dir = _make_folder(tmp_path, files)
    scan = scan_dicom_import_folder(src_dir)

    assert scan["dicom_file_count"] == len(files)
    # CT_small and MR_small_RLE are different studies → multi-study folder
    assert scan["study_count"] >= 2
    assert scan["compressed_dicom_file_count"] >= 1  # RLE (+J2K if present)
    assert any("studies" in w or "patients" in w for w in scan["warnings"])

    report = scan["compatibility_report"]
    assert report["transfer_syntax_count"] >= 2
    # with pylibjpeg-rle installed, RLE must be classified as supported
    if _CAPS.get("pylibjpeg_rle"):
        assert all(
            e["uid"] != "1.2.840.10008.1.2.5"
            for e in report["unsupported_transfer_syntaxes"]
        )
    # metadata extraction
    study = scan["studies"][0]
    assert study["patient_id"] and study["study_uid"]
    series = study["series"][0]
    assert series["modality"] and series["files"]
    assert "transfer_syntax_uids" in series


# ── 2. import: decompress-on-import (RLE / J2K / JPEG-lossless) ────────────
def _roundtrip_one(tmp_path, sample: Path, cap_key: str):
    if sample is None:
        pytest.skip("sample not bundled")
    if not _CAPS.get(cap_key):
        pytest.skip(f"decoder {cap_key} not installed")
    src_dir = _make_folder(tmp_path, [sample])
    out_dir = tmp_path / "storage"
    scan = scan_dicom_import_folder(src_dir)
    result = import_scanned_dicom_studies(scan, out_dir)

    assert not result["errors"]
    assert result["converted_files"] == 1, result
    stored = _all_imported_files(out_dir)
    assert len(stored) == 1

    original = pydicom.dcmread(str(sample), force=True)
    converted = pydicom.dcmread(str(stored[0]), force=True)

    # now uncompressed → decodes with NO codec plugins (numpy handler only)
    assert converted.file_meta.TransferSyntaxUID.is_compressed is False
    # pixels identical to a reference decode of the original
    assert np.array_equal(original.pixel_array, converted.pixel_array)
    # metadata preserved
    for tag in ("PatientID", "StudyInstanceUID", "SeriesInstanceUID",
                "SOPInstanceUID", "Modality", "Rows", "Columns"):
        assert getattr(converted, tag, None) == getattr(original, tag, None), tag


def test_import_converts_rle(tmp_path):
    _roundtrip_one(tmp_path, _RLE, "pylibjpeg_rle")


def test_import_converts_jpeg2000(tmp_path):
    _roundtrip_one(tmp_path, _J2K, "pylibjpeg_openjpeg")


def test_import_converts_synthesized_jpeg2000(tmp_path):
    """Full J2K coverage even when pydicom's J2K sample isn't bundled:
    encode CT_small's pixels to a real JPEG 2000 lossless codestream via
    pylibjpeg-openjpeg, import it, and verify lossless round-trip."""
    if _UNCOMPRESSED is None:
        pytest.skip("pydicom test data unavailable")
    if not _CAPS.get("pylibjpeg_openjpeg"):
        pytest.skip("pylibjpeg-openjpeg not installed")
    try:
        from openjpeg import encode as oj_encode
    except Exception:
        pytest.skip("openjpeg encode API unavailable")
    from pydicom.encaps import encapsulate
    from pydicom.uid import JPEG2000Lossless, generate_uid

    ds = pydicom.dcmread(str(_UNCOMPRESSED))
    arr = ds.pixel_array
    try:
        codestream = oj_encode(arr, photometric_interpretation=2)  # monochrome
    except TypeError:
        try:
            codestream = oj_encode(arr)
        except Exception:
            pytest.skip("openjpeg encode signature mismatch in this version")
    except Exception:
        pytest.skip("openjpeg encode failed in this environment")

    ds.PixelData = encapsulate([bytes(codestream)])
    ds.file_meta.TransferSyntaxUID = JPEG2000Lossless
    ds["PixelData"].is_undefined_length = True
    ds.SOPInstanceUID = generate_uid()
    src_dir = tmp_path / "incoming"
    src_dir.mkdir()
    j2k_path = src_dir / "ct_j2k.dcm"
    ds.save_as(str(j2k_path))

    out_dir = tmp_path / "storage"
    scan = scan_dicom_import_folder(src_dir)
    assert scan["compressed_dicom_file_count"] == 1
    result = import_scanned_dicom_studies(scan, out_dir)
    assert result["converted_files"] == 1, result

    converted = pydicom.dcmread(str(_all_imported_files(out_dir)[0]))
    assert converted.file_meta.TransferSyntaxUID.is_compressed is False
    assert np.array_equal(converted.pixel_array, arr)  # lossless round-trip


def test_import_converts_jpeg_lossless(tmp_path):
    _roundtrip_one(tmp_path, _JPEG_LOSSLESS, "pylibjpeg_libjpeg")


# ── 3. fallbacks: kill-switch, undecodable syntax, decode failure ─────────
@pytest.mark.skipif(_RLE is None, reason="pydicom test data unavailable")
def test_kill_switch_stores_original_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("AIPACS_IMPORT_DECOMPRESS", "0")
    assert _import_decompression_enabled() is False
    src_dir = _make_folder(tmp_path, [_RLE])
    out_dir = tmp_path / "storage"
    result = import_scanned_dicom_studies(scan_dicom_import_folder(src_dir), out_dir)
    assert result["converted_files"] == 0
    stored = _all_imported_files(out_dir)[0]
    assert stored.read_bytes() == _RLE.read_bytes()  # byte-identical copy


@pytest.mark.skipif(_RLE is None, reason="pydicom test data unavailable")
def test_decode_failure_falls_back_to_copy(tmp_path, monkeypatch):
    import PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog as mod

    monkeypatch.setattr(
        mod, "_decompress_file_to_destination",
        lambda src, dest: (False, "simulated codec failure"),
    )
    src_dir = _make_folder(tmp_path, [_RLE])
    out_dir = tmp_path / "storage"
    result = mod.import_scanned_dicom_studies(
        mod.scan_dicom_import_folder(src_dir), out_dir)
    assert result["converted_files"] == 0
    assert result["conversion_warnings"]          # surfaced, not silent
    assert not result["errors"]                   # NOT a hard failure
    assert len(_all_imported_files(out_dir)) == 1  # original still imported


def test_unsupported_syntax_classified_against_empty_caps():
    ok, _ = _is_transfer_syntax_supported("1.2.840.10008.1.2.4.90", {})
    assert ok is False  # J2K with no decoders → flagged, import copies as-is
    ok2, _ = _is_transfer_syntax_supported("1.2.840.10008.1.2.1", {})
    assert ok2 is True  # uncompressed always fine


# ── 4. uncompressed pass-through + non-image + large series ───────────────
@pytest.mark.skipif(_UNCOMPRESSED is None, reason="pydicom test data unavailable")
def test_uncompressed_files_copied_untouched(tmp_path):
    src_dir = _make_folder(tmp_path, [_UNCOMPRESSED])
    out_dir = tmp_path / "storage"
    result = import_scanned_dicom_studies(scan_dicom_import_folder(src_dir), out_dir)
    assert result["converted_files"] == 0 and result["copied_files"] == 1
    stored = _all_imported_files(out_dir)[0]
    assert stored.read_bytes() == _UNCOMPRESSED.read_bytes()


@pytest.mark.skipif(_NON_IMAGE is None, reason="pydicom test data unavailable")
def test_non_image_dicom_imported_as_copy(tmp_path):
    src_dir = _make_folder(tmp_path, [_NON_IMAGE])
    out_dir = tmp_path / "storage"
    scan = scan_dicom_import_folder(src_dir)
    assert scan["dicom_file_count"] == 1  # detected (has core UIDs)
    result = import_scanned_dicom_studies(scan, out_dir)
    assert not result["errors"]
    assert result["converted_files"] == 0  # no PixelData → copy as-is
    assert len(_all_imported_files(out_dir)) == 1


@pytest.mark.skipif(_UNCOMPRESSED is None, reason="pydicom test data unavailable")
def test_large_series_import_ordering(tmp_path):
    # synthesize a 40-instance series from CT_small
    src_dir = tmp_path / "incoming"
    src_dir.mkdir()
    base = pydicom.dcmread(str(_UNCOMPRESSED))
    from pydicom.uid import generate_uid
    for i in range(1, 41):
        ds = pydicom.dcmread(str(_UNCOMPRESSED))
        ds.SOPInstanceUID = generate_uid()
        ds.InstanceNumber = i
        ds.save_as(str(src_dir / f"img_{i:03d}.dcm"))
    del base
    out_dir = tmp_path / "storage"
    scan = scan_dicom_import_folder(src_dir)
    assert scan["dicom_file_count"] == 40
    result = import_scanned_dicom_studies(scan, out_dir)
    stored = sorted(_all_imported_files(out_dir))
    assert len(stored) == 40 and not result["errors"]
    # instance-ordered destination names (prefix = InstanceNumber)
    assert stored[0].name.startswith("00001_")
    assert stored[-1].name.startswith("00040_")


# ── 5. cloud-placeholder hang protection (2026-06-06 Dropbox incident) ────
def test_placeholder_attr_detection():
    from PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog import (
        _is_cloud_placeholder_attrs,
    )
    assert _is_cloud_placeholder_attrs(0x0200 | 0x0400) is True      # Dropbox sparse+reparse
    assert _is_cloud_placeholder_attrs(0x1000) is True               # OFFLINE
    assert _is_cloud_placeholder_attrs(0x400000) is True             # RECALL_ON_DATA_ACCESS
    assert _is_cloud_placeholder_attrs(0x40000) is True              # RECALL_ON_OPEN
    assert _is_cloud_placeholder_attrs(0x0020) is False              # plain Archive
    assert _is_cloud_placeholder_attrs(0x0200) is False              # sparse alone
    assert _is_cloud_placeholder_attrs("garbage") is False           # fail-open


@pytest.mark.skipif(_UNCOMPRESSED is None, reason="pydicom test data unavailable")
def test_scan_warns_on_cloud_placeholders(tmp_path, monkeypatch):
    import PacsClient.pacs.workstation_ui.home_ui.import_preview_dialog as mod

    monkeypatch.setattr(mod, "_is_cloud_placeholder", lambda p: True)
    src_dir = _make_folder(tmp_path, [_UNCOMPRESSED])
    scan = mod.scan_dicom_import_folder(src_dir)
    assert scan["cloud_placeholder_count"] == 1
    assert any("placeholder" in w.lower() for w in scan["warnings"])
    assert any("available offline" in w.lower() for w in scan["warnings"])


def test_scan_and_import_log_start_end():
    # the silent-pipeline gap: scan/copy must log start + done with counts
    for marker in ("[IMPORT_SCAN] start", "[IMPORT_SCAN] done",
                   "[IMPORT_SCAN] progress",
                   "[IMPORT_COPY] start", "[IMPORT_COPY] done"):
        assert marker in _SRC, marker


def test_picker_defaults_away_from_internal_storage():
    layout_src = (
        _REPO_ROOT
        / "PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py"
    ).read_text(encoding="utf-8")
    i = layout_src.index("def select_folder")
    block = layout_src[i:i + 1800]
    # never default into the internal store (code usage, not the comment)
    assert "Path(SOURCE_PATH)" not in block
    assert "last_import_dir" in block          # remember the user's folder
    assert "Path.home()" in block              # sane fallback


# ── 6. source contracts ───────────────────────────────────────────────────
def test_conversion_is_atomic_and_failsafe_in_source():
    i = _SRC.index("def _decompress_file_to_destination")
    block = _SRC[i:i + 2200]
    assert "os.replace(" in block            # atomic publish
    assert ".part" in block                  # temp file, never partial dest
    assert "except Exception" in block and "return False" in block
    # import loop: conversion failure → copy2 fallback, warning surfaced
    j = _SRC.index("decompress_enabled and bool(file_info.get(\"is_compressed\"))")
    loop = _SRC[j:j + 1200]
    assert "shutil.copy2(src, dest)" in loop
    assert "conversion_warnings.append" in loop
