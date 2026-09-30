"""Portable media round trips with isolated databases and synthetic resources."""
import json
from pathlib import Path
import zipfile

import pytest

from tests.code.education.test_course_importer import temp_env
from modules.education import course_database as db
from modules.education import case_of_day_database as cases
from modules.education import portable_transfer as transfer


@pytest.fixture
def collection(temp_env, tmp_path, monkeypatch):
    import PacsClient.utils.config as config
    monkeypatch.setattr(config, "SOURCE_PATH", tmp_path / "source")
    monkeypatch.setattr(cases, "CASE_OF_DAY_STORAGE_PATH", tmp_path / "cases")
    course = db.insert_course("Synthetic downloaded lesson", is_downloaded=True, resource_type="Book")
    root = db._ensure_course_storage(course)
    media = root / "lesson.pdf"
    media.write_bytes(b"synthetic-pdf")
    (root / "archived-original.bin").write_bytes(b"original")
    slide = db.insert_slide(course, 2, "Synthetic slide", "Presenter notes")
    db.insert_slide_content(slide, "pdf", 1, {"path": str(media), "name": "Reading"})
    db.insert_slide_content(slide, "text", 2, {"text": "Retain\nline breaks"})
    package = tmp_path / "cases" / "case_synthetic"
    (package / "dicom" / "1").mkdir(parents=True)
    (package / "dicom" / "1" / "synthetic.dcm").write_bytes(b"synthetic-dicom")
    (package / "screenshots").mkdir()
    (package / "screenshots" / "image.png").write_bytes(b"synthetic-image")
    (package / "notes").mkdir()
    (package / "notes" / "teaching.txt").write_text("Teaching note", encoding="utf-8")
    with db.get_db_connection() as conn:
        conn.execute("INSERT INTO case_of_day_entries(diagnosis,dicom_folder_path,body_part) VALUES (?,?,?)",
                     ("Synthetic case", str(package / "dicom"), "Synthetic region"))
        conn.commit()
    return course, root, package


def _change_manifest(source, dest, edit, extra=None):
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(dest, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename == "manifest.json":
                manifest = json.loads(data)
                edit(manifest)
                data = json.dumps(manifest).encode()
            dst.writestr(info.filename, data)
        if extra:
            dst.writestr(extra, b"unsafe")


def test_round_trip_rebases_media_and_preserves_case_package(collection, tmp_path):
    course, root, case_root = collection
    archive = tmp_path / "transfer.aipacs-edu"
    result = transfer.export_package(archive)
    assert result == {"courses": 1, "cases": 1, "files": 5}
    # Original source paths disappear, as they would on a different computer.
    root.rename(root.with_name("unavailable"))
    case_root.rename(case_root.with_name("unavailable"))
    imported = transfer.import_package(archive)
    assert imported["courses"] == 1 and imported["cases"] == 1
    target = db.get_course_with_slides(max(c["course_pk"] for c in db.get_all_courses()))
    assert target["course_pk"] != course
    assert target["is_downloaded"] == 1
    assert target["resource_type"] == "Book"
    slide = target["slides"][0]
    assert slide["slide_order"] == 2 and slide["slide_notes"] == "Presenter notes"
    path = Path(slide["content"][0]["content_data"]["path"])
    assert path.read_bytes() == b"synthetic-pdf"
    assert (path.parent / "archived-original.bin").read_bytes() == b"original"
    assert slide["content"][1]["content_data"]["text"] == "Retain\nline breaks"
    imported_case = max(cases.get_all_cases(), key=lambda c: c.case_pk)
    folder = Path(imported_case.dicom_folder_path)
    assert (folder / "1" / "synthetic.dcm").read_bytes() == b"synthetic-dicom"
    assert (folder.parent / "screenshots" / "image.png").read_bytes() == b"synthetic-image"
    assert (folder.parent / "notes" / "teaching.txt").read_text() == "Teaching note"
    assert transfer.import_package(archive)["already_imported"]
    assert len(db.get_all_courses()) == 2 and len(cases.get_all_cases()) == 2


@pytest.mark.parametrize("attack", ["checksum", "path", "schema", "reference", "external"])
def test_invalid_package_leaves_no_rows_or_assets(collection, tmp_path, attack):
    from PacsClient.utils.data_paths import EDUCATION_DIR
    archive, bad = tmp_path / "ok.aipacs-edu", tmp_path / "bad.aipacs-edu"
    transfer.export_package(archive)
    def edit(m):
        if attack == "checksum":
            next(iter(m["files"].values()))["sha256"] = "0" * 64
        if attack == "schema":
            m["cases"][0]["unknown_column"] = "bad"
        if attack == "reference":
            m["courses"][0]["slides"][0]["content"][0]["content_data"]["path"] = {"$asset": "assets/missing"}
        if attack == "external":
            m["courses"][0]["slides"][0]["content"][0]["content_data"]["path"] = str(collection[1] / "lesson.pdf")
    _change_manifest(archive, bad, edit, "../escape.txt" if attack == "path" else None)
    with pytest.raises(transfer.TransferError):
        transfer.import_package(bad)
    assert len(db.get_all_courses()) == 1 and len(cases.get_all_cases()) == 1
    assert not list((Path(EDUCATION_DIR) / "transfers").iterdir())


def test_missing_source_does_not_replace_existing_export(collection, tmp_path):
    archive = tmp_path / "existing.aipacs-edu"
    archive.write_bytes(b"keep old backup")
    (collection[1] / "lesson.pdf").unlink()
    with pytest.raises(transfer.TransferError):
        transfer.export_package(archive)
    assert archive.read_bytes() == b"keep old backup"
    assert not list(tmp_path.glob(".education-*"))


def test_cancel_rolls_back_rows_and_staged_media(collection, tmp_path):
    from PacsClient.utils.data_paths import EDUCATION_DIR
    archive = tmp_path / "transfer.aipacs-edu"
    transfer.export_package(archive)
    cancelled = False
    def progress(message):
        nonlocal cancelled
        cancelled = True
    with pytest.raises(transfer.TransferCancelled):
        transfer.import_package(archive, progress=progress, cancel=lambda: cancelled)
    assert len(db.get_all_courses()) == 1
    assert not list((Path(EDUCATION_DIR) / "transfers").iterdir())


def test_dicom_reference_becomes_self_contained_folder(collection, tmp_path):
    source = tmp_path / "source" / "1.2.3" / "7"
    source.mkdir(parents=True)
    (source / "instance.dcm").write_bytes(b"synthetic-instance")
    slide = db.insert_slide(collection[0], 3, "Referenced study")
    db.insert_slide_content(slide, "dicom_series", 1, {"study_uid": "1.2.3", "series_number": 7})
    archive = tmp_path / "transfer.aipacs-edu"
    transfer.export_package(archive, include_cases=False)
    transfer.import_package(archive)
    item = db.get_course_with_slides(max(c["course_pk"] for c in db.get_all_courses()))["slides"][1]["content"][0]
    assert item["content_type"] == "dicom"
    assert item["content_data"]["series_number"] == 7
    assert (Path(item["content_data"]["path"]) / "7" / "instance.dcm").is_file()


def test_imported_collection_can_be_exported_again_without_losing_originals(collection, tmp_path):
    first, second = tmp_path / "first.aipacs-edu", tmp_path / "second.aipacs-edu"
    transfer.export_package(first)
    transfer.import_package(first)
    db.delete_course(collection[0])
    cases.delete_case(min(c.case_pk for c in cases.get_all_cases()))
    collection[1].rename(collection[1].with_name("unavailable"))
    collection[2].rename(collection[2].with_name("unavailable"))
    result = transfer.export_package(second)
    assert result["files"] == 5
    with zipfile.ZipFile(second) as archive:
        assert any(n.endswith("archived-original.bin") for n in archive.namelist())
    transfer.import_package(second)


def test_export_inside_external_media_tree_is_rejected(collection, tmp_path):
    folder = tmp_path / "external"
    folder.mkdir()
    (folder / "dummy.dcm").write_bytes(b"synthetic")
    slide = db.insert_slide(collection[0], 4, "External folder")
    db.insert_slide_content(slide, "dicom", 1, {"path": str(folder)})
    with pytest.raises(transfer.TransferError, match="outside"):
        transfer.export_package(folder / "recursive.aipacs-edu")
    assert not list(folder.glob("*.aipacs-edu"))


def test_import_into_clean_destination_database(collection, tmp_path, monkeypatch):
    import PacsClient.utils.data_paths as paths
    from database.core import init_database
    from tests.code.education.test_course_importer import _clear_pool
    archive = tmp_path / "move.aipacs-edu"
    transfer.export_package(archive)
    collection[1].rename(collection[1].with_name("offline"))
    collection[2].rename(collection[2].with_name("offline"))
    _clear_pool()
    with monkeypatch.context() as destination:
        destination.setattr(paths, "DATABASE_FILE", tmp_path / "second-computer.db")
        destination.setattr(paths, "EDUCATION_DIR", tmp_path / "second-computer-education")
        init_database()
        assert not db.get_all_courses()
        transfer.import_package(archive)
        course = db.get_course_with_slides(db.get_all_courses()[0]["course_pk"])
        media = Path(course["slides"][0]["content"][0]["content_data"]["path"])
        assert media.is_relative_to(paths.EDUCATION_DIR)
        assert media.read_bytes() == b"synthetic-pdf"
        assert len(cases.get_all_cases()) == 1
        _clear_pool()


def test_export_edit_permission_is_preserved_and_cannot_be_relaxed_by_reexport(collection, tmp_path):
    locked = tmp_path / "locked.aipacs-edu"
    transfer.export_package(locked, allow_editing=False)
    assert db.get_course_by_pk(collection[0])["is_editable"] == 1
    transfer.import_package(locked)
    pk = max(c["course_pk"] for c in db.get_all_courses())
    course = db.get_course_with_slides(pk)
    assert course["is_editable"] == 0
    slide = course["slides"][0]
    item = slide["content"][0]
    operations = [
        lambda: db.update_course(pk, name="Changed"),
        lambda: db.insert_slide(pk, 3, "New"),
        lambda: db.update_slide(slide["slide_pk"], title="Changed"),
        lambda: db.delete_slide(slide["slide_pk"]),
        lambda: db.reorder_slides(pk, [slide["slide_pk"]]),
        lambda: db.insert_slide_content(slide["slide_pk"], "text", 5, {"text": "New"}),
        lambda: db.update_slide_content(item["content_pk"], content_data={"text": "Changed"}),
        lambda: db.delete_slide_content(item["content_pk"]),
        lambda: db.reorder_slide_content(slide["slide_pk"], [i["content_pk"] for i in slide["content"]]),
    ]
    for operation in operations:
        with pytest.raises(PermissionError):
            operation()
    db.update_course(pk, is_my_course=True)
    exported_again = tmp_path / "again.aipacs-edu"
    transfer.export_package(exported_again, allow_editing=True)
    with zipfile.ZipFile(exported_again) as archive:
        exported = json.loads(archive.read("manifest.json"))["courses"]
    assert next(c for c in exported if c["course_pk"] == pk)["is_editable"] == 0


def test_default_export_and_legacy_package_remain_editable(collection, tmp_path):
    archive, legacy = tmp_path / "editable.aipacs-edu", tmp_path / "legacy.aipacs-edu"
    transfer.export_package(archive)
    def downgrade(manifest):
        manifest["version"] = 1
        for course in manifest["courses"]:
            course.pop("is_editable", None)
    _change_manifest(archive, legacy, downgrade)
    transfer.import_package(legacy)
    pk = max(c["course_pk"] for c in db.get_all_courses())
    assert db.get_course_by_pk(pk)["is_editable"] == 1
    db.update_course(pk, name="Edited downloaded lesson")
    assert db.get_course_by_pk(pk)["course_name"] == "Edited downloaded lesson"


def test_existing_database_migration_unlocks_downloaded_courses(collection):
    from database.core import init_database
    with db.get_db_connection() as conn:
        conn.execute("ALTER TABLE courses DROP COLUMN is_editable")
        conn.commit()
    init_database()
    course = db.get_course_by_pk(collection[0])
    assert course["is_downloaded"] == 1
    assert course["is_editable"] == 1
    db.update_course(collection[0], name="Edited existing download")
