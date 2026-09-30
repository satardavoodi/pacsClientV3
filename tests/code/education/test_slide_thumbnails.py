"""Custom slide cover persistence, fallback and portable transfer."""
from pathlib import Path
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication
from tests.code.education.test_course_importer import temp_env
from tests.code.education.test_authoring_flow import builder
from modules.education import course_database as db
from modules.education.authoring_tasks import SlideThumbnailTask
from modules.education.authoring_thumbnails import slide_preview, item_preview


def test_custom_cover_survives_reopen_and_transfer_then_resets(temp_env, tmp_path):
    from modules.education.portable_transfer import export_package, import_package
    app = QApplication.instance() or QApplication([])
    course = db.insert_course("Synthetic cover course")
    slide = db.insert_slide(course, 1, "Text lesson")
    db.insert_slide_content(slide, "text", 1, {"text": "Synthetic note"})
    source = tmp_path / "cover.png"
    image = QImage(120, 80, QImage.Format_RGB32)
    image.fill(QColor("red")); image.save(str(source))
    task = SlideThumbnailTask(str(source), course, slide); task.run()
    assert not task.error
    reopened = db.get_slide_by_pk(slide)
    stored = Path(reopened["thumbnail_path"])
    assert stored != source and stored.is_file()
    source.unlink()
    assert slide_preview(reopened, []).pixelColor(0, 0).red() == 255
    archive = tmp_path / "cover.aipacs-edu"
    export_package(archive)
    import_package(archive)
    with db.get_db_connection() as conn:
        imported = conn.execute("SELECT thumbnail_path FROM slides WHERE slide_pk != ?", (slide,)).fetchone()[0]
    assert Path(imported).is_file() and imported != str(stored)
    reset = SlideThumbnailTask("", course, slide); reset.run()
    assert not reset.error and not db.get_slide_by_pk(slide)["thumbnail_path"]
    bad = SlideThumbnailTask(str(tmp_path / "missing.png"), course, slide); bad.run()
    assert bad.error and not db.get_slide_by_pk(slide)["thumbnail_path"]


def test_document_tiles_are_type_specific_and_missing_cover_falls_back(temp_env):
    app = QApplication.instance() or QApplication([])
    text = item_preview({"content_type": "text", "content_data": {"text": "Long note"}})
    ppt = item_preview({"content_type": "attachment", "content_data": {"path": "lesson.pptx"}})
    assert text != ppt
    assert slide_preview({"thumbnail_path": "missing-cover.png"}, [{"content_type": "text"}]) == text


def test_builder_choose_and_restore_cover(builder, tmp_path):
    from PySide6.QtTest import QTest
    import time
    page, _ = builder
    page._add_slide()
    slide = page._editing_slide_pk
    source = tmp_path / "cover.png"
    image = QImage(60, 40, QImage.Format_RGB32)
    image.fill(QColor("blue")); image.save(str(source))
    def wait():
        deadline = time.monotonic() + 5
        while page._slide_thumbnail_worker is not None and time.monotonic() < deadline:
            QTest.qWait(20)
        assert page._slide_thumbnail_worker is None
    page._start_slide_thumbnail(str(source)); wait()
    assert db.get_slide_by_pk(slide)["thumbnail_path"]
    assert page._editing_slide_pk == slide and page.isEnabled()
    page.slide_thumbnail_reset.click(); wait()
    assert not db.get_slide_by_pk(slide)["thumbnail_path"]


def test_existing_slide_schema_migrates_without_losing_content(temp_env):
    from database.core import init_database
    course = db.insert_course("Existing lesson")
    slide = db.insert_slide(course, 1, "Keep title", "Keep notes")
    with db.get_db_connection() as conn:
        conn.execute("ALTER TABLE slides DROP COLUMN thumbnail_path")
        conn.commit()
    init_database()
    init_database()
    restored = db.get_slide_by_pk(slide)
    assert restored["slide_title"] == "Keep title"
    assert restored["slide_notes"] == "Keep notes"
    assert restored["thumbnail_path"] is None
