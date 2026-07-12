# -*- coding: utf-8 -*-
"""Guard: the Eagle Eye / AI-module training-settings folder scans must never
freeze the GUI thread.

Regression (2026-07-12, patient 49874): opening Eagle Eye constructed
AIMainWindow -> ModelTrainingTab -> TrainingDataSettingsTab ->
MammographySettingsWidget.__init__ -> _load_defaults ->
_auto_detect_and_apply_img_size -> _detect_mg_dicom_image_size(user_data/patients)
which os.walk'd + pydicom.dcmread'd the ENTIRE local DICOM store (53k files /
31.7 GB) ON THE GUI THREAD. Its 300-file cap only counted MG *hits*, so a store
of CT/MR/DX studies never tripped it. Measured: one 54.8 s main-thread stall
(the "app freeze"; the patient tab could not paint until it finished).

These tests pin the two properties of the fix:
  1. the scan is BOUNDED (files examined + wall-clock deadline)
  2. the scan does NOT run inline on the calling (GUI) thread

Pure/source-level: no PySide6 widget construction required.
"""

import importlib
import inspect
import os
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

MODULE = "modules.ai_imaging.ai_module_ui.service_tab.training_data_settings_tab"


def _load():
    mod = importlib.import_module(MODULE)
    return importlib.reload(mod)


def _write_fake_dicoms(root: Path, n: int, modality: str = "CT") -> None:
    """Write n minimal DICOM files (pydicom-readable) with the given modality."""
    pydicom = pytest.importorskip("pydicom")
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian

    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        ds = Dataset()
        ds.Modality = modality
        ds.Rows = 2048 if modality == "MG" else 512
        ds.Columns = 1024 if modality == "MG" else 512
        fm = FileMetaDataset()
        fm.TransferSyntaxUID = ExplicitVRLittleEndian
        fm.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1.2"
        fm.MediaStorageSOPInstanceUID = f"1.2.3.{i}"
        ds.file_meta = fm
        ds.is_little_endian = True
        ds.is_implicit_VR = False
        try:  # pydicom >= 3
            ds.save_as(str(root / f"IM{i:05d}.dcm"), enforce_file_format=False)
        except TypeError:  # pydicom 2.x
            ds.save_as(str(root / f"IM{i:05d}.dcm"), write_like_original=True)


# ---------------------------------------------------------------------------
# 1. Boundedness
# ---------------------------------------------------------------------------

def test_detect_stops_at_max_examined_files(tmp_path, monkeypatch):
    """A store with NO MG files must not read more than max_examined_files."""
    mod = _load()
    pydicom = pytest.importorskip("pydicom")

    _write_fake_dicoms(tmp_path / "patients" / "studyA", 40, modality="CT")

    reads = {"n": 0}
    real = pydicom.dcmread

    def counting_dcmread(*a, **kw):
        reads["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(pydicom, "dcmread", counting_dcmread)

    found = mod._detect_mg_dicom_image_size(
        tmp_path / "patients", max_examined_files=5, deadline_s=0.0
    )

    assert found is None  # no MG in the tree
    # The legacy bug: every one of the 40 non-MG files was read. Bounded now.
    assert reads["n"] <= 6, f"scan read {reads['n']} files despite max_examined_files=5"


def test_detect_stops_at_deadline(tmp_path, monkeypatch):
    """The wall-clock deadline must stop a long walk even with files left."""
    mod = _load()
    pydicom = pytest.importorskip("pydicom")

    _write_fake_dicoms(tmp_path / "patients" / "studyA", 30, modality="CT")

    real = pydicom.dcmread

    def slow_dcmread(*a, **kw):
        time.sleep(0.02)
        return real(*a, **kw)

    monkeypatch.setattr(pydicom, "dcmread", slow_dcmread)

    t0 = time.monotonic()
    mod._detect_mg_dicom_image_size(
        tmp_path / "patients", max_examined_files=0, deadline_s=0.1
    )
    elapsed = time.monotonic() - t0

    assert elapsed < 1.0, f"scan ran {elapsed:.2f}s despite a 0.1s deadline"


def test_detect_still_finds_mg_size(tmp_path):
    """Clinical behaviour preserved: an MG study is still detected."""
    mod = _load()
    pytest.importorskip("pydicom")

    _write_fake_dicoms(tmp_path / "patients" / "mg", 3, modality="MG")

    found = mod._detect_mg_dicom_image_size(
        tmp_path / "patients", max_examined_files=2000, deadline_s=5.0
    )
    assert found == 2048
    assert mod._normalize_mammo_img_size(found) == 2048


# ---------------------------------------------------------------------------
# 2. Off the GUI thread
# ---------------------------------------------------------------------------

def test_scan_runs_off_calling_thread_by_default(monkeypatch):
    """_run_scan_off_thread must not execute work() on the caller's thread."""
    monkeypatch.delenv("AIPACS_AI_TRAINING_SCAN_ASYNC", raising=False)
    mod = _load()
    assert mod._TRAINING_SCAN_ASYNC is True, "async scan must be DEFAULT ON"

    caller = threading.get_ident()
    seen = {}
    done = threading.Event()

    def work():
        seen["thread"] = threading.get_ident()
        done.set()
        return 42

    mod._run_scan_off_thread(work, lambda r: None, label="test")
    assert done.wait(5.0), "background scan never ran"
    assert seen["thread"] != caller, "scan ran INLINE on the calling (GUI) thread"


def test_kill_switch_restores_inline_scan(monkeypatch):
    """AIPACS_AI_TRAINING_SCAN_ASYNC=0 restores the legacy inline path."""
    monkeypatch.setenv("AIPACS_AI_TRAINING_SCAN_ASYNC", "0")
    mod = _load()
    try:
        assert mod._TRAINING_SCAN_ASYNC is False
        assert mod._scan_limits() == (0, 0.0)  # legacy: unbounded

        caller = threading.get_ident()
        seen = {}
        mod._run_scan_off_thread(
            lambda: seen.setdefault("thread", threading.get_ident()),
            lambda r: None,
            label="legacy",
        )
        assert seen["thread"] == caller
    finally:
        monkeypatch.delenv("AIPACS_AI_TRAINING_SCAN_ASYNC", raising=False)
        _load()


# ---------------------------------------------------------------------------
# 3. Source pins — the constructor path must not scan synchronously
# ---------------------------------------------------------------------------

def test_auto_detect_dispatches_off_thread():
    mod = _load()
    src = inspect.getsource(mod.MammographySettingsWidget._auto_detect_and_apply_img_size)
    assert "_run_scan_off_thread" in src, (
        "_auto_detect_and_apply_img_size must dispatch the scan off the GUI thread"
    )
    # The blocking call must not sit directly in the method body any more.
    assert "found = _detect_mg_dicom_image_size(root)" not in src


def test_file_count_dispatches_off_thread():
    mod = _load()
    for cls in (mod.MammographySettingsWidget, mod.BoneAgeSettingsWidget):
        src = inspect.getsource(cls._update_file_count)
        assert "_run_scan_off_thread" in src, f"{cls.__name__}._update_file_count blocks the GUI thread"
        assert "os.walk" not in src


def test_scan_limits_are_bounded_by_default(monkeypatch):
    monkeypatch.delenv("AIPACS_AI_TRAINING_SCAN_ASYNC", raising=False)
    mod = _load()
    max_examined, deadline = mod._scan_limits()
    assert max_examined > 0, "default scan must cap files examined"
    assert deadline > 0, "default scan must have a wall-clock deadline"
