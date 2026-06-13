"""Tests for tools/migration/refresh_decrypted_courses.py (E-Learning re-import).

Covers the pure helpers plus an end-to-end refresh against a fake DB and temp
source/runtime trees (no live dicom.db, no PySide6).
"""

import importlib.util
import json
import os
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_TOOL = REPO / "tools" / "migration" / "refresh_decrypted_courses.py"

_spec = importlib.util.spec_from_file_location("refresh_decrypted_courses", _TOOL)
rdc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rdc)


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
def test_kind_for_attachment_by_type():
    assert rdc.kind_for_attachment("Image", "a.jpg") == "image"
    assert rdc.kind_for_attachment("PowerPoint", "a.pptx") == "presentation"
    assert rdc.kind_for_attachment("Word", "a.docx") == "document"
    assert rdc.kind_for_attachment("PDF", "a.pdf") == "pdf"
    assert rdc.kind_for_attachment("Video", "a.mp4") == "video"
    assert rdc.kind_for_attachment("Dicoms", "x") == "dicom"
    assert rdc.kind_for_attachment("Quiz", "q") == "quiz"


def test_kind_for_attachment_ext_fallback():
    assert rdc.kind_for_attachment(None, "a.PNG") == "image"
    assert rdc.kind_for_attachment("", "clip.MOV") == "video"
    assert rdc.kind_for_attachment("", "notes.rtf") == "document"
    assert rdc.kind_for_attachment("", "mystery.xyz") == "other"


def test_content_type_for_kind():
    assert rdc.content_type_for_kind("image") == "image"
    assert rdc.content_type_for_kind("pdf") == "pdf"
    assert rdc.content_type_for_kind("video") == "video"
    assert rdc.content_type_for_kind("presentation") == "attachment"
    assert rdc.content_type_for_kind("document") == "attachment"
    assert rdc.content_type_for_kind("other") == "text"


def test_build_content_data_tags_and_fields():
    d = rdc.build_content_data("image", "Knee", r"C:\x\u.jpg", "u.jpg", "RID")
    assert d["origin"] == rdc.ORIGIN_TAG and d["run_id"] == "RID"
    assert d["path"].endswith("u.jpg") and d["caption"] == "Knee"
    p = rdc.build_content_data("presentation", "Deck", r"C:\x\d.pptx", "d.pptx", "RID")
    assert p["label"] == "Presentation"


def test_is_encrypted_placeholder():
    enc = {"name": "Encrypted originals (archived)",
           "text": "5 encrypted source file(s) (.IPcryp/.IPdcom) preserved",
           "path": "x/_originals"}
    assert rdc.is_encrypted_placeholder("text", enc) is True
    img = {"name": "Knee", "path": "u.jpg", "origin": "elearning_refresh"}
    assert rdc.is_encrypted_placeholder("image", img) is False
    assert rdc.is_encrypted_placeholder("text", {"name": "Notes", "text": "hi"}) is False


def test_parse_source_item():
    assert rdc.parse_source_item("...\nSource: Item-70 (migrated).") == "Item-70"
    assert rdc.parse_source_item("no marker here") is None
    assert rdc.parse_source_item(None) is None


def test_decide_copy(tmp_path):
    src = tmp_path / "s.bin"
    dst = tmp_path / "d.bin"
    src.write_bytes(b"hello")
    assert rdc.decide_copy(src, dst)[0] == "copy"          # missing
    dst.write_bytes(b"hello")
    assert rdc.decide_copy(src, dst)[0] == "skip"          # identical
    dst.write_bytes(b"different content here")
    os.utime(dst, (1, 1))                                   # make dst older
    os.utime(src, (10_000_000, 10_000_000))
    assert rdc.decide_copy(src, dst)[0] == "replace"       # differs, src newer
    os.utime(dst, (20_000_000, 20_000_000))                # dst newer
    assert rdc.decide_copy(src, dst)[0] == "skip"          # never clobber newer


def test_build_item_json_relative_only():
    res = [{"type": "image", "title": "T", "relativePath": "_originals/u.jpg"}]
    prot = [{"relativePath": "_originals/_legacy_encrypted/u.IPcryp", "reason": "encrypted-source"}]
    j = rdc.build_item_json("Item-70", res, prot, ["w1"], 70)
    assert j["resourceCount"] == 1 and j["itemId"] == 70
    assert j["resources"][0]["relativePath"].startswith("_originals/")
    assert j["protectedFiles"][0]["relativePath"].endswith(".IPcryp")
    assert j["warnings"] == ["w1"]


# --------------------------------------------------------------------------- #
# Fake DB + end-to-end refresh
# --------------------------------------------------------------------------- #
class FakeDB:
    def __init__(self):
        self.courses = [{"course_pk": 9, "course_name": "Knee MRI",
                         "course_description": "desc", "body_regions": '["MSK"]',
                         "modality": "MR"}]
        self.slides = {9: [{"slide_pk": 1, "course_fk": 9, "slide_order": 1,
                            "slide_title": "Case 1",
                            "slide_notes": "MR case.\nSource: Item-70 (migrated)."}]}
        self.content = {1: [{"content_pk": 100, "slide_fk": 1, "content_type": "text",
                             "content_order": 1,
                             "content_data": {"name": "Encrypted originals (archived)",
                                              "text": "1 encrypted source file (.IPcryp)",
                                              "path": "x/_originals"}}]}
        self.inserted = []
        self.deleted = []
        self._pk = 1000

    def get_all_courses(self):
        return self.courses

    def get_slides_for_course(self, pk):
        return self.slides.get(pk, [])

    def get_content_for_slide(self, slide_pk):
        return list(self.content.get(slide_pk, []))

    def insert_slide_content(self, slide_fk, content_type, content_order,
                             content_data, layout_position=None):
        self._pk += 1
        row = {"content_pk": self._pk, "slide_fk": slide_fk,
               "content_type": content_type, "content_order": content_order,
               "content_data": content_data}
        self.content.setdefault(slide_fk, []).append(row)
        self.inserted.append(row)
        return self._pk

    def delete_slide_content(self, content_pk):
        self.deleted.append(content_pk)
        for sk, rows in self.content.items():
            self.content[sk] = [r for r in rows if r["content_pk"] != content_pk]


def _build_trees(tmp_path):
    """Source (decrypted) + runtime (encrypted leftovers) trees for course pk 9."""
    src = tmp_path / "src"
    run = tmp_path / "run"
    s_item = src / "Course-10" / "Item-70"
    s_item.mkdir(parents=True)
    (s_item / "u1.jpg").write_bytes(b"\xff\xd8\xff\xe0jpeg-bytes")
    (src / "Course-10" / "course.json").write_text(
        json.dumps({"schemaVersion": "1.2", "warnings": []}), encoding="utf-8")
    (s_item / "item.json").write_text(json.dumps({
        "schemaVersion": "1.2", "itemId": 70, "attachments": [
            {"attachType": "Image", "title": "Knee axial", "relativePath": "u1.jpg",
             "isEncrypted": False},
        ]}), encoding="utf-8")

    r_orig = run / "course_9" / "assets" / "Item-70" / "_originals"
    r_orig.mkdir(parents=True)
    (r_orig / "u1.IPcryp").write_bytes(b"encrypted-blob")
    # nested encrypted dicom config (must also be retired)
    nested = r_orig / "Dicom1" / "55"
    nested.mkdir(parents=True)
    (nested / "Config1.IPdcom").write_bytes(b"enc-dcm")
    # a real materialised DICOM study dir
    study = run / "course_9" / "assets" / "Item-70" / "study_1" / "1"
    study.mkdir(parents=True)
    (study / "img.dcm").write_bytes(b"DICM-ish")
    (run / "course_9" / "migration_manifest.json").write_text(
        json.dumps({"course_pk": 9, "source_folder": str(src / "Course-10")}),
        encoding="utf-8")
    return src, run


def test_refresh_end_to_end_apply(tmp_path):
    src, run = _build_trees(tmp_path)
    db = FakeDB()
    r = rdc.CourseRefresher(str(src), str(run), dry_run=False,
                            progress=lambda m: None, db=db)
    r.run()

    item_dir = run / "course_9" / "assets" / "Item-70"
    # decrypted file copied in
    assert (item_dir / "_originals" / "u1.jpg").is_file()
    # both encrypted files retired (top-level + nested), none left as primary
    assert not (item_dir / "_originals" / "u1.IPcryp").exists()
    assert (item_dir / "_originals" / "_legacy_encrypted" / "u1.IPcryp").is_file()
    assert (item_dir / "_originals" / "_legacy_encrypted" / "Dicom1" / "55"
            / "Config1.IPdcom").is_file()
    # item.json written with relative paths + protectedFiles
    ij = json.loads((item_dir / "item.json").read_text(encoding="utf-8"))
    paths = [x["relativePath"] for x in ij["resources"]]
    assert "_originals/u1.jpg" in paths
    assert any(p["relativePath"].endswith("u1.IPcryp") for p in ij["protectedFiles"])
    assert all(not v["relativePath"].endswith((".IPcryp", ".IPdcom"))
               for v in ij["resources"] if v["type"] != "dicom")
    # course.json written
    cj = json.loads((run / "course_9" / "course.json").read_text(encoding="utf-8"))
    assert cj["courseId"] == 9 and cj["numberOfItems"] == 1
    assert cj["resourceSummary"]["image"] == 1 and cj["resourceSummary"]["legacy"] == 2
    # DB: encrypted placeholder removed, image content inserted + tagged
    assert 100 in db.deleted
    assert any(r_["content_type"] == "image"
               and r_["content_data"].get("origin") == "elearning_refresh"
               for r_ in db.inserted)


def test_refresh_is_idempotent(tmp_path):
    src, run = _build_trees(tmp_path)
    db = FakeDB()
    rdc.CourseRefresher(str(src), str(run), dry_run=False, db=db).run()
    inserts_first = len(db.inserted)
    deletes_first = len(db.deleted)
    # second run: no duplicate image rows, decrypted file still single copy
    rdc.CourseRefresher(str(src), str(run), dry_run=False, db=db).run()
    image_rows = [r_ for r_ in db.content[1] if r_["content_type"] == "image"]
    assert len(image_rows) == 1, "re-run must not duplicate the image content row"
    assert len(db.inserted) == inserts_first + 1  # one insert, but prior one deleted
    assert len(db.deleted) > deletes_first        # prior refresh row was removed first


def test_dry_run_writes_nothing(tmp_path):
    src, run = _build_trees(tmp_path)
    db = FakeDB()
    rdc.CourseRefresher(str(src), str(run), dry_run=True, db=db).run()
    item_dir = run / "course_9" / "assets" / "Item-70"
    assert not (item_dir / "_originals" / "u1.jpg").exists()      # not copied
    assert (item_dir / "_originals" / "u1.IPcryp").exists()       # not retired
    assert not (item_dir / "item.json").exists()                  # not written
    assert not (run / "course_9" / "course.json").exists()
    assert db.inserted == [] and db.deleted == []
