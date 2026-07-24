"""Guards for Offline-Service MANAGEMENT — patient-level delete (P1, 2026-07-21).

Builds a REAL offline package via the export engine (with a DICOMDIR), then
exercises `remove_patients_from_offline_cloud` / `remove_studies_from_offline_
cloud` and asserts the whole package stays consistent:

  * DB rows (studies/series/instances) for the removed patient are gone
  * the orphan patient row is pruned
  * the on-disk dicom/attachments/thumbnails folders are gone
  * unrelated patients are untouched
  * the DICOMDIR is rebuilt to match what remains
  * the manifest study/patient counts match the DB
  * validation reports a complete package
  * the operation is recoverable (a trash backup exists) and rolls back on failure

Runs against isolated temp storage (patches the module path globals, like the
existing offline_cloud_server suite).
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from pathlib import Path

import pytest

pydicom = pytest.importorskip("pydicom")
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

import PacsClient.utils.offline_cloud as oc


# ---------------------------------------------------------------------------
# Synthetic package builder
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE patients (patient_pk INTEGER PRIMARY KEY, patient_id TEXT UNIQUE NOT NULL, patient_name TEXT);
CREATE TABLE studies (study_pk INTEGER PRIMARY KEY, patient_fk INTEGER, study_uid TEXT UNIQUE NOT NULL,
    study_path TEXT, attachments_uploaded TEXT, filming_folder_path TEXT, study_date TEXT, study_time TEXT,
    study_description TEXT, modality TEXT, body_part TEXT, number_of_series INTEGER, number_of_instances INTEGER,
    reportStatus TEXT, visit_status TEXT);
CREATE TABLE series (series_pk INTEGER PRIMARY KEY, study_fk INTEGER, series_uid TEXT UNIQUE NOT NULL,
    series_number INTEGER, thumbnail_path TEXT, series_path TEXT);
CREATE TABLE instances (instance_pk INTEGER PRIMARY KEY, series_fk INTEGER, sop_uid TEXT UNIQUE NOT NULL,
    instance_number INTEGER, instance_path TEXT);
CREATE TABLE download_progress (progress_pk INTEGER PRIMARY KEY, study_uid TEXT UNIQUE NOT NULL, status TEXT);
CREATE TABLE ai_sessions (sid TEXT PRIMARY KEY, study_uid TEXT NOT NULL, title TEXT);
CREATE TABLE ai_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, sid TEXT, role TEXT, content TEXT, created_at INTEGER, ts INTEGER);
CREATE TABLE ai_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, study_uid TEXT, sid TEXT, msg_id INTEGER, created_at INTEGER, report_text TEXT);
CREATE TABLE ai_last_session (study_uid TEXT PRIMARY KEY, sid TEXT);
CREATE TABLE ai_reception_reports (id INTEGER PRIMARY KEY AUTOINCREMENT, study_uid TEXT, patient_id TEXT, created_at INTEGER);
"""


def _write_dicom(path: Path, study_uid, series_uid, patient_id, patient_name):
    meta = FileMetaDataset()
    sop = generate_uid()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    meta.MediaStorageSOPInstanceUID = sop
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.7"
    ds.SOPInstanceUID = sop
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    ds.Modality = "OT"
    ds.SeriesNumber = 1
    ds.InstanceNumber = 1
    ds.StudyID = "1"
    ds.AccessionNumber = "0"
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)
    return sop


@pytest.fixture()
def package(monkeypatch, tmp_path):
    """A built offline package with 2 patients (P1: 1 study, P2: 2 studies)."""
    local = tmp_path / "local"
    dicom_dir = local / "patients" / "dicom"
    att_dir = local / "patients" / "attachments"
    thumb_dir = local / "patients" / "thumbnails"
    for d in (dicom_dir, att_dir, thumb_dir):
        d.mkdir(parents=True, exist_ok=True)
    local_db = local / "dicom.db"

    monkeypatch.setattr(oc, "DATABASE_FILE", local_db)
    monkeypatch.setattr(oc, "DICOM_IMAGES_DIR", dicom_dir)
    monkeypatch.setattr(oc, "ATTACHMENTS_DIR", att_dir)
    monkeypatch.setattr(oc, "THUMBNAILS_DIR", thumb_dir)

    conn = sqlite3.connect(str(local_db))
    conn.executescript(_SCHEMA)

    patients = [("P1", "ALPHA^ONE"), ("P2", "BETA^TWO")]
    study_uids: dict[str, list[str]] = {"P1": [], "P2": []}
    ppk = 0
    spk = 0
    sepk = 0
    ipk = 0
    for pid, pname in patients:
        ppk += 1
        conn.execute("INSERT INTO patients(patient_pk,patient_id,patient_name) VALUES(?,?,?)", (ppk, pid, pname))
        n_studies = 1 if pid == "P1" else 2
        for si in range(n_studies):
            spk += 1
            study_uid = generate_uid()
            study_uids[pid].append(study_uid)
            conn.execute(
                "INSERT INTO studies(study_pk,patient_fk,study_uid,study_path,study_date,modality,"
                "number_of_series,number_of_instances) VALUES(?,?,?,?,?,?,?,?)",
                (spk, ppk, study_uid, str(dicom_dir / study_uid), "20260101", "OT", 1, 2),
            )
            sepk += 1
            series_uid = generate_uid()
            conn.execute(
                "INSERT INTO series(series_pk,study_fk,series_uid,series_number,series_path) VALUES(?,?,?,?,?)",
                (sepk, spk, series_uid, 1, str(dicom_dir / study_uid / "1")),
            )
            for inst in range(2):
                p = dicom_dir / study_uid / "1" / f"IM{inst}.dcm"
                sop = _write_dicom(p, study_uid, series_uid, pid, pname)
                ipk += 1
                conn.execute(
                    "INSERT INTO instances(instance_pk,series_fk,sop_uid,instance_number,instance_path) VALUES(?,?,?,?,?)",
                    (ipk, sepk, sop, inst, str(p)),
                )
            # an attachment + thumbnail so all three trees exist
            (att_dir / study_uid).mkdir(parents=True, exist_ok=True)
            (att_dir / study_uid / "note.txt").write_text("x", encoding="utf-8")
            (thumb_dir / study_uid).mkdir(parents=True, exist_ok=True)
            (thumb_dir / study_uid / "t.png").write_bytes(b"PNG")
    conn.commit()
    conn.close()

    package_root = tmp_path / "package"
    server = {"name": "QA", "folder_path": str(package_root), "server_type": "offline_cloud"}
    all_uids = study_uids["P1"] + study_uids["P2"]
    res = oc.export_studies_to_offline_cloud(server, all_uids, include_dicomdir=True)
    assert res["ok"], res
    return {"server": server, "root": package_root, "paths": oc.package_paths(package_root),
            "study_uids": study_uids}


def _db_study_uids(paths):
    with sqlite3.connect(str(paths["database"])) as c:
        return {r[0] for r in c.execute("SELECT study_uid FROM studies")}


def _db_patient_ids(paths):
    with sqlite3.connect(str(paths["database"])) as c:
        return {r[0] for r in c.execute("SELECT patient_id FROM patients")}


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_patients_summarizes_the_package(package):
    rows = oc.list_offline_cloud_patients(package["server"])
    by_id = {r["patient_id"]: r for r in rows}
    assert set(by_id) == {"P1", "P2"}
    assert by_id["P1"]["study_count"] == 1
    assert by_id["P2"]["study_count"] == 2
    assert by_id["P2"]["image_count"] == 4       # 2 studies * 2 instances
    assert len(by_id["P2"]["study_uids"]) == 2


# ---------------------------------------------------------------------------
# Delete — the core safety scenario
# ---------------------------------------------------------------------------


def test_delete_one_patient_removes_all_their_data_and_keeps_the_rest(package):
    paths = package["paths"]
    p2_uids = package["study_uids"]["P2"]
    p1_uids = package["study_uids"]["P1"]

    res = oc.remove_patients_from_offline_cloud(package["server"], ["P2"])
    assert res["ok"], res
    assert set(res["removed_study_uids"]) == set(p2_uids)
    assert "P2" in res["removed_patient_ids"]

    # DB: P2 and its studies gone; P1 intact
    assert _db_study_uids(paths) == set(p1_uids)
    assert _db_patient_ids(paths) == {"P1"}

    # on-disk folders: P2 studies gone in all three trees; P1 present
    for uid in p2_uids:
        for key in ("dicom", "attachments", "thumbnails"):
            assert not (paths[key] / uid).exists(), f"{key}/{uid} should be deleted"
    for uid in p1_uids:
        assert (paths["dicom"] / uid).exists()

    # manifest reflects reality
    manifest = oc.read_offline_cloud_manifest(paths["root"])
    assert manifest["study_count"] == 1
    assert {s["study_uid"] for s in manifest["studies"]} == set(p1_uids)

    # package still validates as complete, and a recoverable backup exists
    is_complete, _ = oc._package_validation(paths["root"])
    assert is_complete
    assert Path(res["trash_dir"]).exists()
    assert (Path(res["trash_dir"]) / "package.db").exists()


def test_multi_patient_delete_in_one_operation(package):
    paths = package["paths"]
    res = oc.remove_patients_from_offline_cloud(package["server"], ["P1", "P2"])
    assert res["ok"], res
    # everything gone → empty but VALID package
    assert _db_study_uids(paths) == set()
    assert _db_patient_ids(paths) == set()
    is_complete, _ = oc._package_validation(paths["root"])
    assert is_complete
    # the interchange DICOM tree is cleared for an empty package
    assert not (paths["root"] / "DICOM").exists() or oc._count_files(paths["root"] / "DICOM") == 0


def test_delete_single_study_leaves_sibling_study_of_same_patient(package):
    paths = package["paths"]
    p2_uids = package["study_uids"]["P2"]
    # remove only ONE of P2's two studies
    res = oc.remove_studies_from_offline_cloud(package["server"], [p2_uids[0]])
    assert res["ok"], res
    remaining = _db_study_uids(paths)
    assert p2_uids[0] not in remaining
    assert p2_uids[1] in remaining          # sibling kept
    assert "P2" in _db_patient_ids(paths)   # patient NOT pruned (still has a study)
    assert p2_uids[0] not in res["removed_patient_ids"]  # P2 not removed


def test_no_orphan_folders_or_rows_after_delete(package):
    paths = package["paths"]
    oc.remove_patients_from_offline_cloud(package["server"], ["P2"])
    # every dicom study folder must have a matching DB row (files->DB direction)
    db_uids = _db_study_uids(paths)
    for child in (paths["dicom"]).iterdir():
        if child.is_dir():
            assert child.name in db_uids, f"orphan folder {child.name}"
    # and every DB study must have files (DB->files direction)
    for uid in db_uids:
        assert oc._count_files(paths["dicom"] / uid) > 0


# ---------------------------------------------------------------------------
# Recoverability / rollback
# ---------------------------------------------------------------------------


def test_failed_delete_rolls_back_completely(package, monkeypatch):
    paths = package["paths"]
    before_studies = _db_study_uids(paths)
    before_patients = _db_patient_ids(paths)
    p2_uids = package["study_uids"]["P2"]

    # Force the rebuild step to fail AFTER rows/folders were removed.
    monkeypatch.setattr(oc, "build_offline_cloud_dicomdir",
                        lambda *a, **k: {"ok": False, "error": "injected failure"})

    res = oc.remove_patients_from_offline_cloud(package["server"], ["P2"])
    assert not res["ok"]
    assert res.get("rolled_back")

    # everything restored: rows AND folders
    assert _db_study_uids(paths) == before_studies
    assert _db_patient_ids(paths) == before_patients
    for uid in p2_uids:
        assert (paths["dicom"] / uid).exists(), "rolled-back folder should be restored"


def test_empty_selection_is_rejected(package):
    assert oc.remove_patients_from_offline_cloud(package["server"], [])["ok"] is False
    assert oc.remove_studies_from_offline_cloud(package["server"], ["   "])["ok"] is False


def test_unknown_patient_is_a_safe_noop(package):
    paths = package["paths"]
    before = _db_study_uids(paths)
    res = oc.remove_patients_from_offline_cloud(package["server"], ["DOES_NOT_EXIST"])
    assert res["ok"] is False           # nothing to remove
    assert _db_study_uids(paths) == before  # package untouched


# ---------------------------------------------------------------------------
# UI wiring source-pins (the "manage existing" workflow is reachable)
# ---------------------------------------------------------------------------


def _src(rel: str) -> str:
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    return (root / rel).read_text(encoding="utf-8", errors="ignore")


def test_manage_workflow_is_wired_into_the_offline_sync_button():
    table = _src("PacsClient/pacs/workstation_ui/home_ui/patient_table_widget.py")
    assert "offlineCloudManageRequested = Signal()" in table
    # no selection routes to manage; a selection offers add-vs-manage
    assert "offlineCloudManageRequested.emit()" in table
    assert "Edit or Delete Existing Offline Patients" in table

    layout = _src("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_layout.py")
    assert "offlineCloudManageRequested.connect(self._on_offline_cloud_manage_requested)" in layout

    offline = _src("PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_offline.py")
    assert "def _on_offline_cloud_manage_requested" in offline
    assert "OfflineCloudManagerDialog" in offline


def test_manager_dialog_uses_the_engine_primitives_only():
    dlg = _src("PacsClient/pacs/workstation_ui/home_ui/offline_cloud_manager_dialog.py")
    assert "list_offline_cloud_patients" in dlg
    assert "remove_patients_from_offline_cloud" in dlg
    assert "QThread" in dlg              # delete runs off the GUI thread
    # the dialog must not touch the DB / files / DICOMDIR itself
    for forbidden in ("sqlite3", "build_offline_cloud_dicomdir", "shutil"):
        assert forbidden not in dlg, f"dialog must delegate, not call {forbidden}"
