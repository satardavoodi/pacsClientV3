"""IMP-2 — header-only DICOM reads during import registration.

Live evidence 2026-08-05 (pid 193888): after the MRI GA T import copy,
``save_complete_study_info`` re-read all 384 imported files IN FULL (pixel
data included) on the GUI thread to extract six header tags — a 10.6 s
MAIN_THREAD_STALL (20:37:04→20:37:14) whose F11 samples sat in pydicom's
``fp = open(fp, 'rb')`` for ~8 consecutive seconds.

Pins:
  * the header-only read returns a record IDENTICAL to the legacy full
    read (same tags, same defaults, same WW/WC multi-value handling);
  * flag ON passes stop_before_pixels + the exact specific_tags list;
  * kill switch AIPACS_IMPORT_HEADER_ONLY_READS=0 restores the plain
    full-read call;
  * defaults survive (missing InstanceNumber → idx+1, missing WW/WC →
    None) in BOTH modes;
  * save_complete_study_info uses the helper and re-attaches series_fk
    (source pin) with no stray full dcmread left behind.
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pydicom = pytest.importorskip("pydicom")

from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_study_save as hp


def _write_dcm(path, *, instance_number=7, rows=4, cols=5, ww=350.0, wc=50.0,
               multi=False, omit_instance_number=False):
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"  # MR Image Storage
    fm.MediaStorageSOPInstanceUID = generate_uid()
    fm.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = fm.MediaStorageSOPClassUID
    ds.SOPInstanceUID = fm.MediaStorageSOPInstanceUID
    ds.PatientID = "P1"
    ds.PatientName = "T^T"
    ds.Modality = "MR"
    if not omit_instance_number:
        ds.InstanceNumber = instance_number
    ds.Rows = rows
    ds.Columns = cols
    if ww is not None:
        ds.WindowWidth = [ww, ww * 2] if multi else ww
        ds.WindowCenter = [wc, wc * 2] if multi else wc
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.PixelData = b"\x00\x01" * (rows * cols)
    try:
        ds.save_as(str(path), enforce_file_format=True)
    except TypeError:  # pydicom < 3.x
        ds.save_as(str(path), write_like_original=False)
    return ds


# ── equivalence: header-only == legacy full read ─────────────────────────
def test_header_only_record_matches_legacy_full_read(tmp_path, monkeypatch):
    p = tmp_path / "a.dcm"
    ds = _write_dcm(p)

    monkeypatch.delenv("AIPACS_IMPORT_HEADER_ONLY_READS", raising=False)
    fast = hp._read_instance_record_for_import(p, 3)
    monkeypatch.setenv("AIPACS_IMPORT_HEADER_ONLY_READS", "0")
    legacy = hp._read_instance_record_for_import(p, 3)

    assert fast == legacy
    assert fast["sop_uid"] == str(ds.SOPInstanceUID)
    assert fast["instance_number"] == 7
    assert fast["rows"] == 4 and fast["columns"] == 5
    assert fast["window_width"] == 350.0
    assert fast["window_center"] == 50.0
    assert fast["instance_path"] == str(p)
    assert "series_fk" not in fast, "caller attaches series_fk"


def test_multivalue_wwwc_takes_first_value_in_both_modes(tmp_path, monkeypatch):
    p = tmp_path / "m.dcm"
    _write_dcm(p, ww=400.0, wc=40.0, multi=True)

    monkeypatch.delenv("AIPACS_IMPORT_HEADER_ONLY_READS", raising=False)
    fast = hp._read_instance_record_for_import(p, 0)
    monkeypatch.setenv("AIPACS_IMPORT_HEADER_ONLY_READS", "0")
    legacy = hp._read_instance_record_for_import(p, 0)

    assert fast == legacy
    assert fast["window_width"] == 400.0
    assert fast["window_center"] == 40.0


def test_missing_wwwc_gives_none_in_both_modes(tmp_path, monkeypatch):
    p = tmp_path / "n.dcm"
    _write_dcm(p, ww=None, wc=None)

    monkeypatch.delenv("AIPACS_IMPORT_HEADER_ONLY_READS", raising=False)
    fast = hp._read_instance_record_for_import(p, 0)
    monkeypatch.setenv("AIPACS_IMPORT_HEADER_ONLY_READS", "0")
    legacy = hp._read_instance_record_for_import(p, 0)

    assert fast == legacy
    assert fast["window_width"] is None and fast["window_center"] is None


def test_missing_instance_number_defaults_to_idx_plus_1(tmp_path, monkeypatch):
    p = tmp_path / "d.dcm"
    _write_dcm(p, omit_instance_number=True)

    monkeypatch.delenv("AIPACS_IMPORT_HEADER_ONLY_READS", raising=False)
    fast = hp._read_instance_record_for_import(p, 9)
    monkeypatch.setenv("AIPACS_IMPORT_HEADER_ONLY_READS", "0")
    legacy = hp._read_instance_record_for_import(p, 9)

    assert fast == legacy
    assert fast["instance_number"] == 10


# ── read-size mechanics ──────────────────────────────────────────────────
def test_header_only_passes_stop_before_pixels_and_tags(tmp_path, monkeypatch):
    p = tmp_path / "s.dcm"
    _write_dcm(p)

    seen = {"kwargs": None}
    real = pydicom.dcmread

    def spy(*args, **kwargs):
        seen["kwargs"] = kwargs
        return real(*args, **kwargs)

    monkeypatch.setattr(pydicom, "dcmread", spy)
    monkeypatch.delenv("AIPACS_IMPORT_HEADER_ONLY_READS", raising=False)
    hp._read_instance_record_for_import(p, 0)

    kw = seen["kwargs"]
    assert kw is not None, "dcmread was not called through pydicom.dcmread"
    assert kw.get("stop_before_pixels") is True
    assert list(kw.get("specific_tags") or []) == list(hp._IMPORT_INSTANCE_TAGS)


def test_kill_switch_restores_plain_full_read(tmp_path, monkeypatch):
    p = tmp_path / "k.dcm"
    _write_dcm(p)

    seen = {"kwargs": None, "called": 0}
    real = pydicom.dcmread

    def spy(*args, **kwargs):
        seen["kwargs"] = kwargs
        seen["called"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(pydicom, "dcmread", spy)
    monkeypatch.setenv("AIPACS_IMPORT_HEADER_ONLY_READS", "0")
    hp._read_instance_record_for_import(p, 0)

    assert seen["called"] == 1
    assert seen["kwargs"] == {}, "legacy path must be the plain dcmread(path) call"


@pytest.mark.parametrize("val,expected", [
    (None, True), ("", True), ("1", True), ("true", True), ("junk", True),
    ("0", False), ("false", False), ("no", False), ("off", False), (" OFF ", False),
])
def test_flag_parsing(monkeypatch, val, expected):
    if val is None:
        monkeypatch.delenv("AIPACS_IMPORT_HEADER_ONLY_READS", raising=False)
    else:
        monkeypatch.setenv("AIPACS_IMPORT_HEADER_ONLY_READS", val)
    assert hp._import_header_only_reads_enabled() is expected


# ── wiring pin ───────────────────────────────────────────────────────────
def test_save_complete_study_info_uses_helper_and_attaches_series_fk():
    src = inspect.getsource(hp)
    body = src.split("def save_complete_study_info", 1)[1]
    assert "_read_instance_record_for_import(dcm_file, idx)" in body
    assert "record['series_fk'] = series_pk" in body
    assert "dcmread(str(dcm_file))" not in body, (
        "a stray full dcmread survived in save_complete_study_info"
    )
    tags = set(hp._IMPORT_INSTANCE_TAGS)
    assert tags == {"SOPInstanceUID", "InstanceNumber", "Rows", "Columns",
                    "WindowWidth", "WindowCenter"}
