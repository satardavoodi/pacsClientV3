"""Per-series export selection for the Offline Cloud package (2026-07-30).

Only the CHECKED series must reach the package: the ``series`` / ``instances``
rows in package.db, the copied ``patients/dicom/<uid>/`` folders, and the
DICOMDIR must all agree with each other and with the user's selection, while
``patients/dicom/<uid>`` stays importable by AI-PACS.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import warnings
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.fileset import FileSet
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

import PacsClient.utils.offline_cloud as oc

CT_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.2"


# --------------------------------------------------------------------- fixtures

@contextmanager
def _env():
    root = Path(tempfile.mkdtemp(prefix="series_sel_"))
    local = root / "local"
    dicom_dir = local / "patients" / "dicom"
    att_dir = local / "patients" / "attachments"
    thumb_dir = local / "patients" / "thumbnails"
    for p in (dicom_dir, att_dir, thumb_dir):
        p.mkdir(parents=True, exist_ok=True)
    package_root = root / "package"
    package_root.mkdir(parents=True, exist_ok=True)

    saved = (oc.DATABASE_FILE, oc.DICOM_IMAGES_DIR, oc.ATTACHMENTS_DIR, oc.THUMBNAILS_DIR)
    oc.DATABASE_FILE = local / "dicom.db"
    oc.DICOM_IMAGES_DIR = dicom_dir
    oc.ATTACHMENTS_DIR = att_dir
    oc.THUMBNAILS_DIR = thumb_dir
    _create_schema(oc.DATABASE_FILE)
    try:
        yield {
            "root": root,
            "dicom_dir": dicom_dir,
            "package_root": package_root,
            "server": {"name": "QA", "folder_path": str(package_root), "server_type": "offline_cloud"},
        }
    finally:
        oc.DATABASE_FILE, oc.DICOM_IMAGES_DIR, oc.ATTACHMENTS_DIR, oc.THUMBNAILS_DIR = saved
        shutil.rmtree(root, ignore_errors=True)


def _conn(db: Path) -> sqlite3.Connection:
    c = sqlite3.connect(str(db))
    c.row_factory = sqlite3.Row
    return c


def _create_schema(db: Path) -> None:
    with _conn(db) as c:
        c.executescript(
            """
            CREATE TABLE patients (patient_pk INTEGER PRIMARY KEY, patient_id TEXT UNIQUE NOT NULL, patient_name TEXT);
            CREATE TABLE studies (
                study_pk INTEGER PRIMARY KEY, patient_fk INTEGER, study_uid TEXT UNIQUE NOT NULL,
                study_path TEXT, attachments_uploaded TEXT, filming_folder_path TEXT,
                study_date TEXT, study_time TEXT, study_description TEXT,
                modality TEXT, body_part TEXT, number_of_series INTEGER, number_of_instances INTEGER,
                reportStatus TEXT, visit_status TEXT);
            CREATE TABLE series (
                series_pk INTEGER PRIMARY KEY, study_fk INTEGER, series_uid TEXT UNIQUE NOT NULL,
                series_number INTEGER, thumbnail_path TEXT, series_path TEXT);
            CREATE TABLE instances (
                instance_pk INTEGER PRIMARY KEY, series_fk INTEGER, sop_uid TEXT UNIQUE NOT NULL,
                instance_number INTEGER, instance_path TEXT);
            """
        )
        c.commit()


def _write_ct(folder: Path, *, study_uid, series_uid, series_number, instance_number,
              patient_id="P1", patient_name="DOE^JOHN") -> str:
    sop_uid = generate_uid()
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = CT_SOP_CLASS
    fm.MediaStorageSOPInstanceUID = sop_uid
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = fm
    ds.SOPClassUID = CT_SOP_CLASS
    ds.SOPInstanceUID = sop_uid
    ds.PatientName = patient_name
    ds.PatientID = patient_id
    ds.StudyDate = "20260101"
    ds.StudyTime = "120000"
    ds.StudyID = "1"
    ds.AccessionNumber = "ACC1"
    ds.Modality = "CT"
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.InstanceNumber = instance_number
    arr = np.full((8, 8), 100, dtype=np.uint16)
    ds.Rows, ds.Columns = 8, 8
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 16
    ds.BitsStored = 12
    ds.HighBit = 11
    ds.PixelRepresentation = 0
    ds.PixelData = arr.tobytes()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"IM{instance_number:04d}.dcm"
    ds.save_as(str(path), write_like_original=False)
    return sop_uid


def _seed(env) -> dict:
    """One study, series 2 (2 images) + series 3 (1 image). Folders named by number."""
    study_uid = generate_uid()
    s2_uid, s3_uid = generate_uid(), generate_uid()
    root = env["dicom_dir"] / study_uid
    sop = {"2": [], "3": []}
    sop["2"].append(_write_ct(root / "2", study_uid=study_uid, series_uid=s2_uid, series_number=2, instance_number=1))
    sop["2"].append(_write_ct(root / "2", study_uid=study_uid, series_uid=s2_uid, series_number=2, instance_number=2))
    sop["3"].append(_write_ct(root / "3", study_uid=study_uid, series_uid=s3_uid, series_number=3, instance_number=1))

    with _conn(oc.DATABASE_FILE) as c:
        c.execute("INSERT INTO patients (patient_pk, patient_id, patient_name) VALUES (1,'P1','DOE^JOHN')")
        c.execute(
            "INSERT INTO studies (study_pk, patient_fk, study_uid, study_path, modality, number_of_series, number_of_instances) "
            "VALUES (1,1,?,?,?,2,3)", (study_uid, str(root), "CT"))
        c.execute("INSERT INTO series (series_pk, study_fk, series_uid, series_number, series_path) VALUES (1,1,?,2,?)",
                  (s2_uid, str(root / "2")))
        c.execute("INSERT INTO series (series_pk, study_fk, series_uid, series_number, series_path) VALUES (2,1,?,3,?)",
                  (s3_uid, str(root / "3")))
        c.execute("INSERT INTO instances (instance_pk, series_fk, sop_uid, instance_number, instance_path) VALUES (1,1,?,1,'x')", (sop["2"][0],))
        c.execute("INSERT INTO instances (instance_pk, series_fk, sop_uid, instance_number, instance_path) VALUES (2,1,?,2,'x')", (sop["2"][1],))
        c.execute("INSERT INTO instances (instance_pk, series_fk, sop_uid, instance_number, instance_path) VALUES (3,2,?,1,'x')", (sop["3"][0],))
        c.commit()
    return {"study_uid": study_uid, "sop": sop}


def _pkg_series_numbers(env) -> set:
    db = env["package_root"] / "package.db"
    with _conn(db) as c:
        return {str(r["series_number"]) for r in c.execute("SELECT series_number FROM series")}


def _pkg_instance_sops(env) -> set:
    db = env["package_root"] / "package.db"
    with _conn(db) as c:
        return {r["sop_uid"] for r in c.execute("SELECT sop_uid FROM instances")}


def _pkg_dicom_dirs(env, study_uid) -> set:
    d = env["package_root"] / "patients" / "dicom" / study_uid
    return {p.name for p in d.iterdir() if p.is_dir()} if d.exists() else set()


# ------------------------------------------------------------------------ tests

def test_selecting_one_series_excludes_the_other_everywhere():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        result = oc.export_studies_to_offline_cloud(
            env["server"], [uid], include_dicomdir=True,
            series_selection={uid: {"2"}},
        )
        assert result["ok"] is True
        assert not result["errors"]
        # package.db: only series 2 + its 2 instances
        assert _pkg_series_numbers(env) == {"2"}
        assert _pkg_instance_sops(env) == set(seeded["sop"]["2"])
        # on disk: folder 2 kept, folder 3 gone
        assert _pkg_dicom_dirs(env, uid) == {"2"}
        # AI-PACS payload still present and importable by exact UID
        assert (env["package_root"] / "patients" / "dicom" / uid / "2").is_dir()


def test_dicomdir_reflects_only_the_selected_series():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        oc.export_studies_to_offline_cloud(
            env["server"], [uid], include_dicomdir=True,
            series_selection={uid: {"2"}},
        )
        # Find the study's DICOMDIR under DICOM/<Patient>/<StudyUID>/
        dicomdir_paths = list((env["package_root"] / "DICOM").rglob("DICOMDIR"))
        assert dicomdir_paths, "a DICOMDIR should exist for the exported study"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            fs = FileSet(str(dicomdir_paths[0]))
        sops = {inst.SOPInstanceUID for inst in fs}
        assert sops == set(seeded["sop"]["2"])  # exactly series 2's instances


def test_none_selection_exports_every_series():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        oc.export_studies_to_offline_cloud(env["server"], [uid], include_dicomdir=True, series_selection=None)
        assert _pkg_series_numbers(env) == {"2", "3"}
        assert _pkg_dicom_dirs(env, uid) == {"2", "3"}
        assert _pkg_instance_sops(env) == set(seeded["sop"]["2"]) | set(seeded["sop"]["3"])


def test_normalization_matches_leading_zero_and_int():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        # selection given with odd forms should still match series 2 and 3
        oc.export_studies_to_offline_cloud(
            env["server"], [uid], include_dicomdir=False,
            series_selection={uid: {"02", 3}},
        )
        assert _pkg_series_numbers(env) == {"2", "3"}


def test_reexport_with_fewer_series_drops_the_removed_folder():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        # First: full export (both series present).
        oc.export_studies_to_offline_cloud(env["server"], [uid], include_dicomdir=True, series_selection=None)
        assert _pkg_dicom_dirs(env, uid) == {"2", "3"}
        # Then: re-export with only series 2 → series 3 must disappear.
        oc.export_studies_to_offline_cloud(env["server"], [uid], include_dicomdir=True, series_selection={uid: {"2"}})
        assert _pkg_dicom_dirs(env, uid) == {"2"}
        assert _pkg_series_numbers(env) == {"2"}
        # DICOMDIR must no longer reference series 3.
        dicomdir_paths = list((env["package_root"] / "DICOM").rglob("DICOMDIR"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            fs = FileSet(str(dicomdir_paths[0]))
        assert {inst.SOPInstanceUID for inst in fs} == set(seeded["sop"]["2"])


def test_kill_switch_disables_the_filter(monkeypatch):
    monkeypatch.setenv("AIPACS_EXPORT_SERIES_SELECTION", "0")
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        # Even though we ask for only series 2, the disabled flag exports all.
        oc.export_studies_to_offline_cloud(env["server"], [uid], include_dicomdir=False, series_selection={uid: {"2"}})
        assert _pkg_series_numbers(env) == {"2", "3"}


def test_series_summary_counts_are_returned():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        result = oc.export_studies_to_offline_cloud(
            env["server"], [uid], include_dicomdir=False, series_selection={uid: {"2"}})
        summaries = result.get("series_summaries")
        assert summaries and summaries[0]["study_uid"] == uid
        assert summaries[0]["series_kept"] == 1
        assert summaries[0]["series_skipped"] == 1
        assert summaries[0]["instances"] == 2


def test_study_absent_from_map_keeps_all_series():
    with _env() as env:
        seeded = _seed(env)
        uid = seeded["study_uid"]
        # Map references a DIFFERENT study → this study is unfiltered.
        oc.export_studies_to_offline_cloud(
            env["server"], [uid], include_dicomdir=False, series_selection={"other-uid": {"9"}})
        assert _pkg_series_numbers(env) == {"2", "3"}
