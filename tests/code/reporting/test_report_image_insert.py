"""Insert a captured viewer image into the Medical Report Editor (2026-08-18).

REQUESTED FROM THE FLOOR: physicians capture key images in the Patient tab and
want them in the report, under the paragraph that describes the finding. The
Medical Report Editor (``ReportEditorDialog``, a Qt rich-text ``QTextEdit``)
had no way to insert one.

The load-bearing guards in here are the ROUND-TRIP ones. An inserted image has
to survive four separate stages, and each one has a way to silently eat it:

    toHtml()                     what _save_report emits
    prepare_report_html_for_server()   the INO upload normaliser
    setHtml()                    reopening the saved report
    QTextDocument.resource()     rendering and printing

``test_the_upload_normaliser_keeps_the_image`` is the one to never delete: the
normaliser already strips ``<style>``, ``<script>`` and document chrome, and it
is one ``_DIR_BLOCK_TAGS`` entry away from stripping ``<img>`` too. If that
happens, the physician sees the image locally, saves, and the copy the
referring doctor opens has no image — the worst possible failure mode, because
nothing looks wrong on the machine that wrote it.

``test_a_document_can_render_a_data_uri`` pins BEHAVIOUR, not mechanism. Qt
6.10.2 resolves data URIs natively, so ``install_data_uri_image_support`` is a
no-op there by design; on an older Qt it swaps in a subclass. The test must
pass either way — it asks "does an embedded image render", not "is the
subclass installed".
"""
from __future__ import annotations

import ast
import base64
import inspect
import os
import re
from pathlib import Path

import pytest

from modules.ai_imaging.ai_module_ui.service_tab.widgets import report_capture_images as rci


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def qt_app():
    """A Qt application instance, offscreen. Reuses one if the session already
    made it, so this never fights the widget tests."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def study(tmp_path, monkeypatch):
    """A fake ATTACHMENT_PATH with one study folder. Returns (uid, folder)."""
    uid = "1.2.826.0.1.3680043.8.498.TEST"
    folder = tmp_path / uid
    folder.mkdir(parents=True)

    import PacsClient.utils.config as cfg
    monkeypatch.setattr(cfg, "ATTACHMENT_PATH", tmp_path, raising=False)
    return uid, folder


def _write_png(path: Path, w: int = 640, h: int = 480) -> Path:
    """A real PNG with enough detail that JPEG cannot trivially crush it."""
    from PySide6.QtGui import QImage, QPainter

    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(0xFF101820)
    painter = QPainter(img)
    try:
        for i in range(0, w, 5):
            painter.setPen(0xFF000000 | ((i * 5779) & 0xFFFFFF))
            painter.drawLine(i, 0, w - i, h)
    finally:
        painter.end()
    img.save(str(path), "PNG")
    return path


# ══════════════════════════════════════════════════════════════════════════
# Listing the study's captures
# ══════════════════════════════════════════════════════════════════════════

def test_captures_are_listed_for_the_study(study, qt_app):
    uid, folder = study
    _write_png(folder / "a.png")
    _write_png(folder / "b.jpg")

    names = {p.name for p in rci.list_captured_images(uid)}
    assert names == {"a.png", "b.jpg"}


def test_non_image_files_are_ignored(study, qt_app):
    uid, folder = study
    _write_png(folder / "capture.png")
    (folder / "notes.txt").write_text("not an image", encoding="utf-8")
    (folder / "voice.wav").write_bytes(b"RIFF")

    names = [p.name for p in rci.list_captured_images(uid)]
    assert names == ["capture.png"], "only images belong in an image picker"


def test_newest_capture_comes_first(study, qt_app):
    uid, folder = study
    older = _write_png(folder / "older.png")
    newer = _write_png(folder / "newer.png")
    os.utime(older, (1_600_000_000, 1_600_000_000))
    os.utime(newer, (1_700_000_000, 1_700_000_000))

    names = [p.name for p in rci.list_captured_images(uid)]
    assert names[0] == "newer.png", (
        "the image just captured is the one being inserted — it must be first"
    )


def test_a_study_with_no_captures_is_empty_not_an_error(study):
    uid, _folder = study
    assert rci.list_captured_images(uid) == []


def test_a_missing_study_folder_is_empty_not_an_error(study):
    assert rci.list_captured_images("no-such-study-uid") == []


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_a_blank_study_uid_lists_nothing(blank):
    assert rci.list_captured_images(blank) == []


def test_the_extension_set_matches_the_viewer_dropdown():
    """The report picker and the viewer's 'View Captured Images' dropdown must
    show the same files, or the physician sees one set in the viewer and a
    different set in the report. AST-read so this needs no Qt import."""
    src = Path(
        Path(inspect.getsourcefile(rci)).parents[5]
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_toolbar" / "attachments_dropdown.py"
    )
    assert src.is_file(), f"attachments_dropdown.py not found at {src}"

    tree = ast.parse(src.read_text(encoding="utf-8"))
    viewer_exts = None
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", "") == "IMAGE_EXTS":
            viewer_exts = ast.literal_eval(node.value)
        elif isinstance(node, ast.Assign) and any(
            getattr(t, "id", "") == "IMAGE_EXTS" for t in node.targets
        ):
            viewer_exts = ast.literal_eval(node.value)
    assert viewer_exts, "IMAGE_EXTS vanished from attachments_dropdown.py"
    assert tuple(rci.IMAGE_EXTS) == tuple(viewer_exts)


# ══════════════════════════════════════════════════════════════════════════
# Encoding — size is the operational risk, so most of the guards are here
# ══════════════════════════════════════════════════════════════════════════

def test_a_capture_encodes_to_an_embeddable_jpeg(tmp_path, qt_app):
    src = _write_png(tmp_path / "cap.png")
    out = rci.encode_capture_for_report(src)
    assert out is not None
    assert out.data_uri.startswith("data:image/jpeg;base64,")
    assert out.encoded_bytes > 0
    assert out.width > 0 and out.height > 0
    base64.b64decode(out.data_uri.split(",", 1)[1])   # must be valid base64


def test_a_large_capture_is_downscaled_to_the_width_cap(tmp_path, qt_app):
    src = _write_png(tmp_path / "big.png", w=2400, h=1350)
    out = rci.encode_capture_for_report(src)
    assert out is not None
    assert out.width == rci.DEFAULT_MAX_WIDTH
    assert out.height == pytest.approx(1350 * (rci.DEFAULT_MAX_WIDTH / 2400), abs=2), (
        "downscaling must preserve the aspect ratio"
    )


def test_a_small_capture_is_not_upscaled(tmp_path, qt_app):
    src = _write_png(tmp_path / "small.png", w=320, h=240)
    out = rci.encode_capture_for_report(src)
    assert out is not None
    assert out.width == 320, "a small key image must not be blown up"


def test_embedding_is_much_smaller_than_the_raw_capture(tmp_path, qt_app):
    src = _write_png(tmp_path / "big.png", w=1920, h=1080)
    raw = src.stat().st_size
    out = rci.encode_capture_for_report(src)
    assert out is not None
    assert out.encoded_bytes < raw, (
        "the whole point of re-encoding is to keep the report upload small"
    )


def test_the_width_cap_is_configurable(tmp_path, qt_app, monkeypatch):
    monkeypatch.setenv("AIPACS_REPORT_IMAGE_MAX_WIDTH", "400")
    src = _write_png(tmp_path / "cap.png", w=1600, h=900)
    out = rci.encode_capture_for_report(src)
    assert out is not None and out.width == 400


def test_a_garbled_env_override_falls_back_instead_of_raising(monkeypatch):
    monkeypatch.setenv("AIPACS_REPORT_IMAGE_MAX_WIDTH", "wide-please")
    monkeypatch.setenv("AIPACS_REPORT_IMAGE_QUALITY", "")
    assert rci.max_width() == rci.DEFAULT_MAX_WIDTH
    assert rci.jpeg_quality() == rci.DEFAULT_QUALITY


def test_an_unreadable_file_yields_none_not_an_exception(tmp_path, qt_app):
    bogus = tmp_path / "not-an-image.png"
    bogus.write_bytes(b"this is not a PNG")
    assert rci.encode_capture_for_report(bogus) is None


def test_a_missing_file_yields_none(tmp_path, qt_app):
    assert rci.encode_capture_for_report(tmp_path / "gone.png") is None


def test_an_impossible_byte_ceiling_refuses_rather_than_overshooting(tmp_path, qt_app):
    """A report that cannot be uploaded is worse than a refused insert."""
    src = _write_png(tmp_path / "big.png", w=1920, h=1080)
    out = rci.encode_capture_for_report(src, byte_ceiling=200)
    assert out is None, (
        "the encoder must refuse rather than embed something over the ceiling"
    )


def test_a_tight_ceiling_is_met_by_stepping_quality_down(tmp_path, qt_app):
    """Between 'fits easily' and 'impossible' the fallback ladder should work."""
    src = _write_png(tmp_path / "big.png", w=1920, h=1080)
    unbounded = rci.encode_capture_for_report(src, byte_ceiling=10_000_000)
    assert unbounded is not None
    ceiling = int(unbounded.encoded_bytes * 0.6)

    out = rci.encode_capture_for_report(src, byte_ceiling=ceiling)
    assert out is not None, "the ladder should have found a way under the ceiling"
    assert out.encoded_bytes <= ceiling


# ══════════════════════════════════════════════════════════════════════════
# Round-trip — the load-bearing guards
# ══════════════════════════════════════════════════════════════════════════

def _document_with_image(data_uri: str, width: int = 600, height: int = 338):
    from PySide6.QtGui import QTextCursor, QTextImageFormat

    doc = rci.make_data_uri_document()
    cursor = QTextCursor(doc)
    cursor.insertText("Findings: focal lesion in the right lobe.")
    cursor.insertBlock()
    fmt = QTextImageFormat()
    fmt.setName(data_uri)
    fmt.setWidth(width)
    fmt.setHeight(height)
    cursor.insertImage(fmt)
    return doc


@pytest.fixture
def inserted(tmp_path, qt_app):
    """An encoded capture already sitting in a document — the state right
    after the physician double-clicks a thumbnail."""
    src = _write_png(tmp_path / "cap.png", w=1200, h=800)
    encoded = rci.encode_capture_for_report(src)
    assert encoded is not None
    return encoded, _document_with_image(encoded.data_uri)


def test_the_image_survives_tohtml(inserted):
    encoded, doc = inserted
    html = doc.toHtml()
    assert "<img" in html
    assert "data:image/jpeg;base64," in html, (
        "the bytes must travel with the report — a file path would be a broken "
        "image on every other machine"
    )


def test_the_display_width_survives_tohtml(inserted):
    _encoded, doc = inserted
    html = doc.toHtml()
    match = re.search(r'<img[^>]*\bwidth="?(\d+)', html)
    assert match and int(match.group(1)) == 600, (
        "resizing is pointless if the size is not saved"
    )


def test_the_upload_normaliser_keeps_the_image(inserted):
    """THE load-bearing guard. The normaliser strips <style>/<script>/chrome;
    if <img> ever joins that list, the copy the referring doctor opens loses
    the key image while the local copy still shows it."""
    from PacsClient.utils.report_server_html import prepare_report_html_for_server

    _encoded, doc = inserted
    server_html = prepare_report_html_for_server(doc.toHtml())

    assert "<img" in server_html, "the upload normaliser stripped the image tag"
    assert "data:image/jpeg;base64," in server_html, (
        "the upload normaliser stripped the image data"
    )
    match = re.search(r'<img[^>]*\bwidth="?(\d+)', server_html)
    assert match and int(match.group(1)) == 600, (
        "the upload normaliser stripped the image size"
    )
    assert "focal lesion" in server_html, "the report text must survive too"


def test_the_image_survives_a_save_and_reopen_cycle(inserted):
    from PacsClient.utils.report_server_html import prepare_report_html_for_server

    encoded, doc = inserted
    saved = prepare_report_html_for_server(doc.toHtml())

    reopened = rci.make_data_uri_document()
    reopened.setHtml(saved)
    assert "data:image/jpeg;base64," in reopened.toHtml()


def test_a_document_can_render_a_data_uri(inserted):
    """Behaviour, not mechanism: on Qt 6.10 the stock document resolves data
    URIs and the subclass is a no-op; on an older Qt the subclass does it.
    Either way an embedded image must resolve to real pixels, or it prints
    blank and shows a broken box."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QImage, QPixmap, QTextDocument

    encoded, doc = inserted
    resource = doc.resource(QTextDocument.ResourceType.ImageResource,
                            QUrl(encoded.data_uri))
    if isinstance(resource, QPixmap):
        resource = resource.toImage()
    assert isinstance(resource, QImage) and not resource.isNull()
    assert resource.width() == encoded.width


def test_decode_data_uri_rejects_junk_without_raising(qt_app):
    """This runs inside loadResource on every repaint — it must never throw."""
    for junk in ("", "not a uri", "data:image/png;base64,%%%%",
                 "data:text/plain;base64,aGk=", "http://example.com/x.png"):
        assert rci.decode_data_uri_image(junk) is None


def test_the_capability_probe_answers_without_raising(qt_app):
    assert rci.stock_qt_resolves_data_uris() in (True, False)


# ══════════════════════════════════════════════════════════════════════════
# Editor wiring — AST, so no dialog has to be constructed
# ══════════════════════════════════════════════════════════════════════════

def _editor_source() -> str:
    path = Path(inspect.getsourcefile(rci)).with_name("report_editor_dialog.py")
    assert path.is_file()
    return path.read_text(encoding="utf-8")


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


@pytest.fixture(scope="module")
def editor_tree():
    return ast.parse(_editor_source())


def test_the_toolbar_gains_an_insert_image_button(editor_tree):
    fn = _func(editor_tree, "_create_format_toolbar")
    assert fn is not None, "_create_format_toolbar vanished"
    assigned = {
        t.attr for node in ast.walk(fn) if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Attribute)
    }
    assert "btn_image" in assigned, (
        "the Insert Image button must be built in the format toolbar, next to "
        "Link / Table / Horizontal Line"
    )


def test_the_resize_buttons_exist(editor_tree):
    fn = _func(editor_tree, "_create_format_toolbar")
    assigned = {
        t.attr for node in ast.walk(fn) if isinstance(node, ast.Assign)
        for t in node.targets if isinstance(t, ast.Attribute)
    }
    for name in ("btn_img_smaller", "btn_img_larger", "btn_img_fit"):
        assert name in assigned, f"{name} missing from the format toolbar"


def test_the_image_buttons_are_connected(editor_tree):
    """A button built but never connected is a dead control — and this is
    exactly the shape of bug the Text tool shipped with."""
    fn = _func(editor_tree, "_setup_connections")
    assert fn is not None
    src = ast.unparse(fn)
    assert "self.btn_image.clicked.connect" in src
    assert "_insert_captured_image" in src
    for name in ("btn_img_smaller", "btn_img_larger", "btn_img_fit"):
        assert f"self.{name}.clicked.connect" in src, f"{name} is a dead button"


def test_insert_goes_through_the_picker_and_the_encoder(editor_tree):
    fn = _func(editor_tree, "_insert_captured_image")
    assert fn is not None, "_insert_captured_image vanished"
    src = ast.unparse(fn)
    assert "pick_captured_image" in src, "the gallery must be what chooses the image"
    assert "encode_capture_for_report" in src, (
        "the raw capture must never be embedded unprocessed — that is what "
        "keeps the upload payload sane"
    )
    assert "insertImage" in src


def test_a_cancelled_picker_inserts_nothing(editor_tree):
    """Cancel must return before anything touches the document."""
    fn = _func(editor_tree, "_insert_captured_image")
    src_lines = ast.unparse(fn).splitlines()
    pick_line = next(i for i, l in enumerate(src_lines) if "pick_captured_image" in l)
    insert_line = next(i for i, l in enumerate(src_lines) if "insertImage" in l)
    guard_line = next(
        (i for i, l in enumerate(src_lines)
         if i > pick_line and l.strip().startswith("if not path")),
        None,
    )
    assert guard_line is not None, "no cancel guard after the picker"
    assert pick_line < guard_line < insert_line


def test_the_editor_installs_data_uri_support_before_content_loads(editor_tree):
    fn = _func(editor_tree, "_create_editor_area")
    assert fn is not None
    assert "install_data_uri_image_support" in ast.unparse(fn), (
        "the editor must set up image rendering when it builds the QTextEdit, "
        "not after content has already been parsed"
    )


def test_the_study_uid_uses_the_same_keys_as_the_history_lookup(editor_tree):
    """If these two disagree, the picker lists another study's captures."""
    resolver = _func(editor_tree, "_report_study_uid")
    history = _func(editor_tree, "_start_previous_exams_lookup")
    assert resolver is not None and history is not None
    for key in ("studyUID", "study_uid"):
        assert key in ast.unparse(resolver)
        assert key in ast.unparse(history)


def test_the_picker_module_exposes_the_helper():
    from modules.ai_imaging.ai_module_ui.service_tab.widgets import (
        report_image_picker_dialog as picker,
    )
    assert callable(picker.pick_captured_image)
    assert hasattr(picker, "CapturedImagePickerDialog")


# ══════════════════════════════════════════════════════════════════════════
# Resize — BEHAVIOURAL, on real Qt objects
#
# These exist because the AST guards above did not catch a real bug: the first
# implementation probed for the image with a REVERSED selection, so
# `charFormat()` read the character on the far side of the range, every resize
# button silently did nothing, and every structural guard still passed. A
# source-shape assertion cannot see "the width never changed".
#
# The dialog's methods are bound to a lightweight stand-in rather than a real
# ReportEditorDialog: constructing the dialog pulls in qtawesome, which cannot
# resolve the Windows fonts directory under pytest here (the same environment
# gap that quarantines test_field_icon_chip). The logic under test is the
# same; only the chrome is skipped.
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def editor_stub(qt_app, tmp_path):
    """A stand-in carrying the real QTextEdit + buttons, with the dialog's
    real image methods bound to it."""
    import types
    from types import SimpleNamespace
    from PySide6.QtWidgets import QTextEdit, QToolButton
    from modules.ai_imaging.ai_module_ui.service_tab.widgets.report_editor_dialog import (
        ReportEditorDialog,
    )

    edit = QTextEdit()
    edit.resize(700, 500)
    stub = SimpleNamespace(
        text_edit=edit,
        btn_img_smaller=QToolButton(),
        btn_img_larger=QToolButton(),
        btn_img_fit=QToolButton(),
        patient_data={"studyUID": "1.2.3"},
    )
    for name in (
        "_image_format_at_cursor", "_update_image_buttons", "_apply_image_width",
        "_scale_image_at_cursor", "_fit_image_at_cursor", "_fitted_width",
        "_report_study_uid",
    ):
        setattr(stub, name, types.MethodType(getattr(ReportEditorDialog, name), stub))
    return stub


def _place_image(stub, uri: str, width: int = 400, height: int = 300) -> int:
    """Insert an image and leave the cursor just after it — exactly where it
    ends up after a real insert."""
    from PySide6.QtGui import QTextCursor, QTextImageFormat

    cursor = stub.text_edit.textCursor()
    cursor.insertText("Findings: ")
    fmt = QTextImageFormat()
    fmt.setName(uri)
    fmt.setWidth(width)
    fmt.setHeight(height)
    cursor.insertImage(fmt)
    position = cursor.position()
    cursor.insertText(" trailing text")
    cursor.setPosition(position)
    stub.text_edit.setTextCursor(cursor)
    return position


@pytest.fixture
def uri(tmp_path, qt_app):
    encoded = rci.encode_capture_for_report(_write_png(tmp_path / "c.png", 400, 300))
    assert encoded is not None
    return encoded.data_uri


def test_an_image_is_found_when_the_cursor_sits_just_after_it(editor_stub, uri):
    """THE pin on the reversed-selection bug. This is where the cursor lands
    after an insert, so if it fails here the resize buttons are dead."""
    _place_image(editor_stub, uri)
    _cursor, fmt = editor_stub._image_format_at_cursor()
    assert fmt is not None, "the image right before the cursor was not found"
    assert fmt.width() == 400


def test_an_image_is_found_when_the_cursor_sits_just_before_it(editor_stub, uri):
    position = _place_image(editor_stub, uri)
    cursor = editor_stub.text_edit.textCursor()
    cursor.setPosition(position - 1)
    editor_stub.text_edit.setTextCursor(cursor)
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt is not None and fmt.width() == 400


def test_plain_text_reports_no_image(editor_stub):
    editor_stub.text_edit.setPlainText("no pictures here")
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt is None


def test_making_an_image_smaller_actually_changes_its_width(editor_stub, uri):
    """The bug the AST guards missed: buttons wired, handler called, width
    unchanged."""
    _place_image(editor_stub, uri)
    editor_stub._scale_image_at_cursor(1 / 1.1)
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt is not None
    assert fmt.width() < 400, f"width did not shrink (still {fmt.width()})"


def test_making_an_image_larger_actually_changes_its_width(editor_stub, uri):
    _place_image(editor_stub, uri, width=200, height=150)
    editor_stub._scale_image_at_cursor(1.1)
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt is not None and fmt.width() > 200


def test_resizing_preserves_the_aspect_ratio(editor_stub, uri):
    _place_image(editor_stub, uri, width=400, height=300)
    editor_stub._scale_image_at_cursor(1 / 1.1)
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt.height() / fmt.width() == pytest.approx(0.75, abs=0.01), (
        "a squashed key image is worse than one that is the wrong size"
    )


def test_repeated_shrinking_keeps_shrinking(editor_stub, uri):
    """One step working is not enough — the format has to be re-read each time."""
    _place_image(editor_stub, uri)
    widths = []
    for _ in range(3):
        editor_stub._scale_image_at_cursor(1 / 1.1)
        _c, fmt = editor_stub._image_format_at_cursor()
        widths.append(fmt.width())
    assert widths == sorted(widths, reverse=True) and widths[0] != widths[-1], widths


def test_an_image_cannot_be_shrunk_into_nothing(editor_stub, uri):
    _place_image(editor_stub, uri)
    for _ in range(60):
        editor_stub._scale_image_at_cursor(1 / 1.1)
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt is not None and fmt.width() >= 60, (
        "an image scaled to nothing is unrecoverable — the user cannot click it"
    )


def test_fit_to_width_uses_the_editor_width(editor_stub, uri):
    _place_image(editor_stub, uri, width=100, height=75)
    editor_stub._fit_image_at_cursor()
    _c, fmt = editor_stub._image_format_at_cursor()
    assert fmt is not None
    assert fmt.width() == editor_stub._fitted_width(10_000)
    assert fmt.width() > 100


def test_a_new_image_is_never_wider_than_the_page(editor_stub):
    """A capture wider than the editor would force a horizontal scrollbar and
    print cropped."""
    fitted = editor_stub._fitted_width(5000)
    viewport = editor_stub.text_edit.viewport().width()
    assert fitted <= viewport, f"{fitted} > viewport {viewport}"


def test_the_resize_buttons_track_the_cursor(editor_stub, uri):
    editor_stub.text_edit.setPlainText("just text")
    editor_stub._update_image_buttons()
    assert not editor_stub.btn_img_smaller.isEnabled(), (
        "resize buttons must not look available when there is nothing to resize"
    )

    editor_stub.text_edit.clear()
    _place_image(editor_stub, uri)
    editor_stub._update_image_buttons()
    assert editor_stub.btn_img_smaller.isEnabled()
    assert editor_stub.btn_img_larger.isEnabled()
    assert editor_stub.btn_img_fit.isEnabled()


def test_resizing_with_no_image_is_a_no_op(editor_stub):
    editor_stub.text_edit.setPlainText("no pictures here")
    before = editor_stub.text_edit.toHtml()
    editor_stub._scale_image_at_cursor(1.1)
    editor_stub._fit_image_at_cursor()
    assert editor_stub.text_edit.toHtml() == before


def test_the_resized_width_is_what_gets_saved(editor_stub, uri):
    """Resizing is pointless unless the new size survives toHtml and upload."""
    from PacsClient.utils.report_server_html import prepare_report_html_for_server

    _place_image(editor_stub, uri)
    editor_stub._fit_image_at_cursor()
    _c, fmt = editor_stub._image_format_at_cursor()
    expected = int(fmt.width())

    saved = prepare_report_html_for_server(editor_stub.text_edit.toHtml())
    match = re.search(r'<img[^>]*\bwidth="?(\d+)', saved)
    assert match and int(match.group(1)) == expected, (
        f"saved width {match.group(1) if match else None} != on-screen {expected}"
    )


# ══════════════════════════════════════════════════════════════════════════
# Resolving WHICH study a report covers
#
# REPORTED FROM THE FLOOR after the first cut shipped: the button opened and
# said "This report is not linked to a study" for reception 54800, a patient
# who plainly had a capture. Cause: a report opened from the Reception Data
# tab carries a RECEPTION record — receptionId, nationalCode, a patient
# sub-dict — and NO StudyInstanceUID, while captures on disk are keyed by
# study UID. Asking `patient_data['studyUID']` was always going to be empty.
#
# The fallback joins patients.patient_id -> patient_pk -> studies.patient_fk.
# `patient_fk` is a foreign key to patient_pk, NOT the DICOM PatientID, so a
# direct `studies.patient_fk = '54800'` lookup silently returns nothing —
# which is exactly the shape of bug that would reintroduce this.
# ══════════════════════════════════════════════════════════════════════════

RECEPTION = {
    "_id": "68a1f0c0deadbeef",
    "receptionId": "54800",
    "nationalCode": "0046922229",
    "patient": {"Name": "porya mazaheri", "NationalID": "0046922229"},
    "status": "pending",
}


def test_a_reception_record_really_has_no_study_uid():
    """Pins the premise. If receptions ever start carrying a study UID this
    test fails and the fallback can be reconsidered."""
    assert not RECEPTION.get("studyUID")
    assert not RECEPTION.get("study_uid")


def test_the_reception_id_is_offered_before_the_national_code():
    """Precedence matters: a national code is not a DICOM PatientID, and
    trying it first risks matching an unrelated patient row."""
    ids = rci.candidate_patient_ids(RECEPTION)
    assert ids[0] == "54800"
    assert "0046922229" in ids
    assert ids.index("54800") < ids.index("0046922229")


def test_an_explicit_study_uid_short_circuits_the_lookup(monkeypatch):
    """A caller that knows its study must never pay for a DB query."""
    def _boom(_pid):
        raise AssertionError("the DB must not be consulted when studyUID is known")

    monkeypatch.setattr(rci, "study_uids_for_patient_id", _boom)
    assert rci.resolve_study_uids({"studyUID": "1.2.3.EXPLICIT"}) == ["1.2.3.EXPLICIT"]
    assert rci.resolve_study_uids({"study_uid": "1.2.3.SNAKE"}) == ["1.2.3.SNAKE"]


def test_a_reception_resolves_through_the_patient_id(monkeypatch):
    calls = []

    def _fake(pid):
        calls.append(pid)
        return ["1.2.840.STUDY"] if pid == "54800" else []

    monkeypatch.setattr(rci, "study_uids_for_patient_id", _fake)
    assert rci.resolve_study_uids(RECEPTION) == ["1.2.840.STUDY"]
    assert calls[0] == "54800", "the reception id must be tried first"


def test_resolution_stops_at_the_first_identifier_that_matches(monkeypatch):
    """Unioning every match would mix a second patient's key images into the
    report — a clinical error, not a cosmetic one."""
    def _fake(pid):
        return {"54800": ["A"], "0046922229": ["B"]}.get(pid, [])

    monkeypatch.setattr(rci, "study_uids_for_patient_id", _fake)
    assert rci.resolve_study_uids(RECEPTION) == ["A"], "must not also include 'B'"


def test_an_unmatched_reception_resolves_to_nothing(monkeypatch):
    monkeypatch.setattr(rci, "study_uids_for_patient_id", lambda _pid: [])
    assert rci.resolve_study_uids(RECEPTION) == []


def test_the_db_fallback_has_a_kill_switch(monkeypatch):
    monkeypatch.setenv("AIPACS_REPORT_IMAGE_DB_LOOKUP", "0")
    monkeypatch.setattr(
        rci, "study_uids_for_patient_id",
        lambda _pid: (_ for _ in ()).throw(AssertionError("lookup ran anyway")),
    )
    assert rci.resolve_study_uids(RECEPTION) == []


@pytest.mark.parametrize("junk", [None, "", 42, [], {"patient": None}])
def test_resolution_never_raises_on_junk(junk, monkeypatch):
    monkeypatch.setattr(rci, "study_uids_for_patient_id", lambda _pid: [])
    assert rci.resolve_study_uids(junk) == []


def test_a_broken_database_yields_no_studies_instead_of_raising(monkeypatch):
    """Called from a toolbar click — a locked DB must not raise into the GUI."""
    import database._pool as pool

    def _boom():
        raise RuntimeError("database is locked")

    monkeypatch.setattr(pool, "get_db_connection", _boom, raising=False)
    assert rci.study_uids_for_patient_id("54800") == []


def test_a_blank_patient_id_never_queries():
    assert rci.study_uids_for_patient_id("") == []
    assert rci.study_uids_for_patient_id("   ") == []
    assert rci.study_uids_for_patient_id(None) == []


def test_the_join_goes_through_the_patients_table():
    """`studies.patient_fk` is a FK to `patients.patient_pk`, not the DICOM
    PatientID. A query that compares patient_fk to the id string returns
    nothing at all — which is precisely how this feature shipped broken."""
    source = inspect.getsource(rci.study_uids_for_patient_id)
    assert "JOIN patients" in source
    assert "p.patient_pk = s.patient_fk" in source
    assert "p.patient_id" in source, "the id must be compared on the patients row"


# ── Listing across several studies ──────────────────────────────────────────

def test_captures_are_gathered_across_studies(tmp_path, monkeypatch, qt_app):
    import PacsClient.utils.config as cfg
    monkeypatch.setattr(cfg, "ATTACHMENT_PATH", tmp_path, raising=False)

    (tmp_path / "STUDY_A").mkdir()
    (tmp_path / "STUDY_B").mkdir()
    a = _write_png(tmp_path / "STUDY_A" / "a.png")
    b = _write_png(tmp_path / "STUDY_B" / "b.png")
    os.utime(a, (1_600_000_000, 1_600_000_000))
    os.utime(b, (1_700_000_000, 1_700_000_000))

    entries = rci.list_captured_images_for_studies(["STUDY_A", "STUDY_B"])
    assert [p.name for _uid, p in entries] == ["b.png", "a.png"], (
        "newest first across ALL studies, not grouped by study"
    )
    assert {uid for uid, _p in entries} == {"STUDY_A", "STUDY_B"}
    assert entries[0][0] == "STUDY_B", "each entry must carry its own study uid"


def test_a_repeated_study_uid_is_not_listed_twice(study, qt_app):
    uid, folder = study
    _write_png(folder / "one.png")
    entries = rci.list_captured_images_for_studies([uid, uid, " ", None])
    assert len(entries) == 1


def test_no_studies_lists_nothing():
    assert rci.list_captured_images_for_studies([]) == []
    assert rci.list_captured_images_for_studies(None) == []


# ── The editor must use the resolver, not the bare key ──────────────────────

def test_the_editor_resolves_studies_instead_of_reading_one_key(editor_tree):
    """The regression guard for the floor report. If `_insert_captured_image`
    goes back to `_report_study_uid()` (singular), every reception-opened
    report says "not linked to a study" again."""
    fn = _func(editor_tree, "_insert_captured_image")
    assert fn is not None
    src = ast.unparse(fn)
    assert "_report_study_uids" in src, (
        "insert must go through the plural resolver, which falls back to the "
        "local DICOM DB when the reception carries no study UID"
    )


def test_the_plural_resolver_delegates_to_resolve_study_uids(editor_tree):
    fn = _func(editor_tree, "_report_study_uids")
    assert fn is not None, "_report_study_uids vanished"
    assert "resolve_study_uids" in ast.unparse(fn)


def test_the_picker_accepts_several_studies(qt_app):
    """A patient can legitimately have more than one study with captures."""
    from modules.ai_imaging.ai_module_ui.service_tab.widgets import (
        report_image_picker_dialog as picker,
    )
    dialog = picker.CapturedImagePickerDialog(["A", "B"])
    assert dialog.study_uids == ["A", "B"]

    single = picker.CapturedImagePickerDialog("ONLY")
    assert single.study_uids == ["ONLY"], "a bare string must still work"

    empty = picker.CapturedImagePickerDialog([])
    assert empty.study_uids == []
