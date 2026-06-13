"""
Tests for modules.education.course_importer (EducationCourseImporter).

Uses an isolated temp DB (patching PacsClient.utils.data_paths.DATABASE_FILE and
clearing the database._pool connection pool -- the project's required DB-isolation
pattern) plus a temp education asset store, and synthetic DICOM fixtures.

Run:
    python -m pytest tests/code/education/test_course_importer.py -q -p no:debugging
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _write_dicom(path: Path, *, study_uid: str, series_uid: str, series_number: int,
                 modality: str = "MR", study_desc: str = "KNEE",
                 series_desc: str = "T2", body_part: str = "KNEE") -> None:
    import pydicom  # noqa: F401
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    ds = Dataset()
    ds.PatientName = "TEST^PATIENT"
    ds.PatientID = "TID"
    ds.Modality = modality
    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SeriesNumber = series_number
    ds.StudyDescription = study_desc
    ds.SeriesDescription = series_desc
    ds.BodyPartExamined = body_part
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.4"   # MR Image Storage
    ds.SOPInstanceUID = generate_uid()
    fm = FileMetaDataset()
    fm.MediaStorageSOPClassUID = ds.SOPClassUID
    fm.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
    fm.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta = fm
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.save_as(str(path), write_like_original=False)


def _clear_pool():
    import database._pool as db_pool
    try:
        with db_pool._pool_lock:
            for conns in list(db_pool._connection_pool.values()):
                for c in conns:
                    try:
                        c.close()
                    except Exception:
                        pass
            db_pool._connection_pool.clear()
    except Exception:
        pass


@pytest.fixture
def temp_env(tmp_path, monkeypatch):
    """Redirect the DB + education store to temp; init schema; verify isolation."""
    import PacsClient.utils.data_paths as data_paths
    import PacsClient.utils.config as config

    db = tmp_path / "db" / "test_dicom.db"
    db.parent.mkdir(parents=True)
    edu = tmp_path / "edu"
    courses = edu / "courses"
    logs = tmp_path / "logs"
    courses.mkdir(parents=True)
    logs.mkdir(parents=True)

    monkeypatch.setattr(data_paths, "DATABASE_FILE", db, raising=False)
    monkeypatch.setattr(data_paths, "EDUCATION_DIR", edu, raising=False)
    monkeypatch.setattr(data_paths, "LOGS_DIR", logs, raising=False)
    monkeypatch.setattr(config, "EDUCATION_STORAGE_PATH", courses, raising=False)

    _clear_pool()
    from database.core import init_database, get_db_connection
    init_database()

    # Fail loudly if isolation didn't take -- never touch the production DB.
    with get_db_connection() as conn:
        actual = conn.execute("PRAGMA database_list").fetchall()[0][2]
    assert os.path.abspath(actual or "") == os.path.abspath(str(db)), \
        f"DB isolation failed: connected to {actual!r}"

    yield {"db": db, "courses": courses, "edu": edu}
    _clear_pool()


@pytest.fixture
def learn_root(tmp_path):
    """A minimal PooyanPacs-style Learn root: 1 course, 2 items."""
    root = tmp_path / "Learn"
    c = root / "Course-99"
    c.mkdir(parents=True)
    (c / "course.json").write_text(json.dumps({
        "schemaVersion": "1.1", "courseId": 99, "courseName": "Course-99",
        "courseTitle": "Course-99", "courseDescription": "",
        "items": [
            {"itemId": 1, "itemName": "Item-1", "itemTitle": "Item-1",
             "relativePath": "Item-1", "description": ""},
            {"itemId": 2, "itemName": "Item-2", "itemTitle": "Item-2",
             "relativePath": "Item-2", "description": ""},
        ],
    }), encoding="utf-8")

    # Item-1: a DICOM study (2 series, SR-style folders) + cache preview +
    # a loose image + an encrypted original.
    it1 = c / "Item-1"
    it1.mkdir()
    (it1 / "item.json").write_text(json.dumps({
        "schemaVersion": "1.1", "itemId": 1, "itemTitle": "Item-1",
        "metadata": {"modality": None, "anatomicalRegion": None, "tags": []},
    }), encoding="utf-8")
    suid = "1.2.3.99"
    base = it1 / "Dicom1" / "PID" / suid
    _write_dicom(base / "SR03" / "a.dcm", study_uid=suid, series_uid="1.2.3.99.3", series_number=3)
    _write_dicom(base / "SR03" / "b.dcm", study_uid=suid, series_uid="1.2.3.99.3", series_number=3)
    _write_dicom(base / "SR04" / "c.dcm", study_uid=suid, series_uid="1.2.3.99.4", series_number=4)
    (base / "CacheFile").mkdir(parents=True, exist_ok=True)
    (base / "CacheFile" / "SR01.jpg").write_bytes(b"\xff\xd8\xff\xe0preview")
    (it1 / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    (it1 / "secret.IPcryp").write_bytes(b"encryptedblob")

    # Item-2: empty (must still become a slide with a placeholder).
    it2 = c / "Item-2"
    it2.mkdir()
    (it2 / "item.json").write_text(json.dumps({
        "schemaVersion": "1.1", "itemId": 2, "itemTitle": "Item-2", "metadata": {},
    }), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------
def test_full_import_creates_course_slides_resources(temp_env, learn_root):
    from modules.education.course_importer import EducationCourseImporter, ImportConfig
    from modules.education.course_database import (
        get_all_courses, get_slides_for_course, get_content_for_slide)

    overrides = {"Course-99": {
        "title": "Knee MRI Test Course", "description": "Curated description.",
        "objectives": ["Understand knee MR anatomy"], "keywords": ["MRI", "Knee"],
        "ai": True}}
    results = EducationCourseImporter(ImportConfig(overrides=overrides)).import_learn_root(str(learn_root))

    assert len(results) == 1
    r = results[0]
    assert r.course_pk is not None
    assert r.errors == []

    courses = get_all_courses()
    assert len(courses) == 1
    course = courses[0]
    assert course["course_name"] == "Knee MRI Test Course"
    assert course["content_origin"] == "migrated_pooyanpacs"
    # Fully-populated course (name/description/modality/body) -> NOT flagged.
    # AI-drafted text no longer forces a "Needs Fix" badge.
    assert not course["needs_attention"]
    assert "MRI" in course["tags"]

    slides = get_slides_for_course(course["course_pk"])
    assert len(slides) == 2
    assert sorted(s["slide_order"] for s in slides) == [1, 2]

    # The DICOM resource must be in the viewer's <study>/<numeric series>/ layout.
    dicom_paths = []
    n_text = 0
    for s in slides:
        for ct in get_content_for_slide(s["slide_pk"]):
            if ct["content_type"] == "dicom":
                dicom_paths.append(ct["content_data"]["path"])
            if ct["content_type"] == "text":
                n_text += 1
    assert len(dicom_paths) == 1
    sp = Path(dicom_paths[0])
    assert sp.exists()
    series_dirs = {d.name for d in sp.iterdir() if d.is_dir() and d.name.isdigit()}
    assert series_dirs == {"3", "4"}
    assert len(list(sp.rglob("*.dcm"))) == 3        # all instances preserved
    assert n_text >= 1                              # empty item placeholder + enc note


def test_originals_and_thumbnail_preserved(temp_env, learn_root):
    from modules.education.course_importer import EducationCourseImporter, ImportConfig
    from modules.education.course_database import get_all_courses

    EducationCourseImporter(ImportConfig()).import_learn_root(str(learn_root))
    course = get_all_courses()[0]
    course_root = temp_env["courses"] / f"course_{course['course_pk']}"
    originals = course_root / "assets" / "Item-1" / "_originals"

    assert (originals / "figure.png").exists()          # loose image preserved
    assert (originals / "secret.IPcryp").exists()        # encrypted original preserved
    assert any(originals.rglob("SR01.jpg"))              # cache preview preserved
    assert course["thumbnail_path"] and Path(course["thumbnail_path"]).exists()


def test_dry_run_writes_nothing(temp_env, learn_root):
    from modules.education.course_importer import EducationCourseImporter, ImportConfig
    from modules.education.course_database import get_all_courses

    results = EducationCourseImporter(ImportConfig(dry_run=True)).import_learn_root(str(learn_root))
    assert get_all_courses() == []
    assert results[0].course_pk is None
    assert not any(temp_env["courses"].glob("course_*"))
    # facts are still computed in a dry run
    assert results[0].dicom_studies == 1


def test_idempotent_reimport_skips(temp_env, learn_root):
    from modules.education.course_importer import EducationCourseImporter, ImportConfig
    from modules.education.course_database import get_all_courses

    EducationCourseImporter(ImportConfig()).import_learn_root(str(learn_root))
    second = EducationCourseImporter(ImportConfig()).import_learn_root(str(learn_root))
    assert len(get_all_courses()) == 1          # not duplicated
    assert second[0].skipped is True


def test_scan_groups_series_by_number(temp_env, learn_root):
    from modules.education.course_importer import scan_item_dicom
    studies = scan_item_dicom(learn_root / "Course-99" / "Item-1")
    assert len(studies) == 1
    st = studies[0]
    assert set(st.series.keys()) == {3, 4}
    assert st.instance_count == 3
    assert st.modality == "MR"


def test_text_and_resource_helpers():
    from modules.education.course_importer import (
        _clean_text, _smart_title, EducationCourseImporter)
    assert _clean_text("UPPER EXTRIMITY^RT . SHOULDER").lower().startswith("upper extremity")
    assert "Extremity" in _smart_title("upper extrimity")
    assert EducationCourseImporter._kind_for_ext(".png") == "image"
    assert EducationCourseImporter._kind_for_ext(".pdf") == "pdf"
    assert EducationCourseImporter._kind_for_ext(".mp4") == "video"
    assert EducationCourseImporter._kind_for_ext(".mov") == "video"
    assert EducationCourseImporter._kind_for_ext(".pptx") == "presentation"
    assert EducationCourseImporter._kind_for_ext(".zip") == "archive"
    assert EducationCourseImporter._kind_for_ext(".ipcryp") == "encrypted"


def test_anatomy_title_normalization():
    from modules.education.course_importer import _normalize_anatomy_title
    # Spelling + laterality lifted to a suffix; scanner noise tokens dropped.
    assert _normalize_anatomy_title("Lower Exteimiti FOOT LT -K") == "Lower Extremity Foot (Left)"
    assert _normalize_anatomy_title("UPPER EXTRIMITY^RT . SHOULDER") == "Upper Extremity Shoulder (Right)"
    assert "Ankle" in _normalize_anatomy_title("Ankel&foot K")


def test_duplicate_titles_disambiguated():
    from modules.education.course_importer import EducationCourseImporter
    scanned = [{"enr": {"title": "MR - Ankle"}}, {"enr": {"title": "MR - Ankle"}},
               {"enr": {"title": "MR - Foot"}}]
    EducationCourseImporter._disambiguate_titles(scanned)
    titles = [s["enr"]["title"] for s in scanned]
    assert titles == ["MR - Ankle - Case 1", "MR - Ankle - Case 2", "MR - Foot"]


def test_objectives_have_no_placeholders():
    from modules.education.course_importer import _objectives_for
    for text in _objectives_for("", ""):
        assert "IMAGING" not in text and "imaged region" not in text
    joined = " ".join(_objectives_for("MR", "ANKLE"))
    assert "Ankle" in joined and "MR" in joined


def test_content_for_routes_by_type(tmp_path):
    from modules.education.course_importer import EducationCourseImporter
    f = tmp_path / "lecture.pptx"
    f.write_bytes(b"x")
    res = {"kind": "presentation", "path": f, "name": "lecture", "ext": ".pptx", "size": 1}
    # Presentations route to the viewport's external-open "attachment" renderer.
    ctype, data = EducationCourseImporter._content_for("presentation", res, f)
    assert ctype == "attachment"
    assert data["path"] == str(f)
    # Images stay images.
    img = tmp_path / "fig.png"
    img.write_bytes(b"x")
    res_img = {"kind": "image", "path": img, "name": "fig", "ext": ".png", "size": 1}
    assert EducationCourseImporter._content_for("image", res_img, img)[0] == "image"
    # MP4 / video routes to the video renderer.
    vid = tmp_path / "clip.mp4"
    vid.write_bytes(b"x")
    res_vid = {"kind": "video", "path": vid, "name": "clip", "ext": ".mp4", "size": 1}
    assert EducationCourseImporter._content_for("video", res_vid, vid)[0] == "video"
