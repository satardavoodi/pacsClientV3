"""Regression guards for the 2026-09-05 large-folder import crash.

The failing live session combined two unsafe boundaries: imported DICOM
registration walked thousands of files on the Qt thread, then layout creation
called ``QApplication.processEvents()`` while the viewport tree was only
partially constructed.  These guards keep the registration work on the
existing import worker boundary and keep layout construction atomic.
"""
from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import hashlib
import inspect
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from PacsClient.pacs.patient_tab.ui.patient_ui import _vc_layout
from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_import
from PacsClient.pacs.workstation_ui.home_ui.home_panel import _hp_study_save


def _function_node(module, name: str) -> ast.FunctionDef:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} was not found")


def _attribute_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == name
    ]


def test_import_registration_is_dispatched_through_background_boundary():
    method = _function_node(_hp_import, "_import_folder_with_preview_impl")

    assert not _attribute_calls(method, "save_complete_study_info"), (
        "large-folder registration must not synchronously scan DICOM files on "
        "the Qt import/UI path"
    )
    background_calls = _attribute_calls(method, "_run_background_job_with_progress")
    assert any(
        len(call.args) >= 3
        and isinstance(call.args[2], ast.Attribute)
        and call.args[2].attr == "_register_imported_studies"
        for call in background_calls
    ), "import registration must use the existing managed worker/progress boundary"


def test_registration_helper_preserves_per_study_results_and_inputs():
    calls = []

    def save_complete_study_info(**kwargs):
        calls.append(kwargs)
        return kwargs["study_uid"] != "study-b"

    owner = SimpleNamespace(save_complete_study_info=save_complete_study_info)
    studies = [
        {"study_uid": "study-a", "patient_id": "patient-1", "series": []},
        {"study_uid": "study-b", "patient_id": "patient-1", "series": []},
    ]
    before = [dict(study) for study in studies]

    failed = _hp_import._HPImportMixin._register_imported_studies(owner, studies)

    assert failed == ["study-b"]
    assert calls == [
        {
            "study_uid": "study-a",
            "patient_id": "patient-1",
            "study_info": studies[0],
        },
        {
            "study_uid": "study-b",
            "patient_id": "patient-1",
            "study_info": studies[1],
        },
    ]
    assert studies == before, "registration orchestration must not rewrite import identity"


def test_registration_worker_preserves_dicom_bytes_and_writes_isolated_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Exercise the real registration path without touching clinical storage."""
    from database import _pool, dicom_db
    from PacsClient.utils import data_paths
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    db_path = tmp_path / "dicom.db"
    storage_root = tmp_path / "storage"
    study_uid = generate_uid()
    series_uid = generate_uid()
    sop_uid = generate_uid()
    series_dir = storage_root / study_uid / "1"
    series_dir.mkdir(parents=True)
    dcm_path = series_dir / "1.dcm"

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.4"
    file_meta.MediaStorageSOPInstanceUID = sop_uid
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    dataset = Dataset()
    dataset.file_meta = file_meta
    dataset.SOPClassUID = file_meta.MediaStorageSOPClassUID
    dataset.SOPInstanceUID = sop_uid
    dataset.InstanceNumber = 1
    dataset.Rows = 2
    dataset.Columns = 2
    dataset.BitsAllocated = 16
    dataset.BitsStored = 12
    dataset.HighBit = 11
    dataset.PixelRepresentation = 0
    dataset.SamplesPerPixel = 1
    dataset.PhotometricInterpretation = "MONOCHROME2"
    dataset.PixelData = b"\x00\x01" * 4
    try:
        dataset.save_as(str(dcm_path), enforce_file_format=True)
    except TypeError:  # pydicom < 3.x
        dataset.save_as(str(dcm_path), write_like_original=False)
    before_hash = hashlib.sha256(dcm_path.read_bytes()).digest()

    _pool.cleanup_connection_pools()
    monkeypatch.setattr(data_paths, "DATABASE_FILE", db_path, raising=False)
    monkeypatch.setattr(_hp_study_save, "SOURCE_PATH", storage_root)
    dicom_db.init_database()

    main_thread_id = threading.get_ident()
    observed_thread_ids = []
    owner = SimpleNamespace()

    def save_complete_study_info(**kwargs):
        observed_thread_ids.append(threading.get_ident())
        return _hp_study_save._HPStudySaveMixin.save_complete_study_info(owner, **kwargs)

    owner.save_complete_study_info = save_complete_study_info
    owner.get_series_info_from_server = lambda *_args, **_kwargs: pytest.fail(
        "a local imported-study registration must not access the server"
    )
    study = {
        "study_uid": study_uid,
        "patient_id": "test-patient",
        "patient_name": "Test^Patient",
        "study_date": "20260905",
        "study_time": "120000",
        "study_description": "Synthetic",
        "count_of_series": 1,
        "series": [
            {
                "series_uid": series_uid,
                "series_number": "1",
                "series_path_name": "1",
                "series_description": "Synthetic",
                "modality": "MR",
                "image_count": 1,
            }
        ],
    }

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            failed = executor.submit(
                _hp_import._HPImportMixin._register_imported_studies,
                owner,
                [study],
            ).result(timeout=10)

        assert failed == []
        assert observed_thread_ids and observed_thread_ids[0] != main_thread_id
        assert hashlib.sha256(dcm_path.read_bytes()).digest() == before_hash

        with sqlite3.connect(db_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM patients").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM studies").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM series").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM instances").fetchone()[0] == 1
    finally:
        _pool.cleanup_connection_pools()


def test_layout_construction_never_pumps_the_qt_event_loop():
    method = _function_node(_vc_layout, "apply_multi_viewer")
    forbidden = [
        call
        for call in ast.walk(method)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "processEvents"
    ]

    assert not forbidden, (
        "processEvents re-enters queued viewer/overlay work while the layout "
        "tree is only partially constructed"
    )
