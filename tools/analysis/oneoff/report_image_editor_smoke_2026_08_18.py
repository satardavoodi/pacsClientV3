import os, sys, traceback
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
out = Path(__file__).with_name("_smoke_editor_out.txt")
lines = []


def log(m):
    lines.append(str(m))
    out.write_text("\n".join(lines), encoding="utf-8")


try:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    log("qapp ok")

    from modules.ai_imaging.ai_module_ui.service_tab.widgets.report_editor_dialog import (
        ReportEditorDialog,
    )
    log("editor module imported")

    # The REAL shape reception_data_tab passes: a reception record with no
    # StudyInstanceUID. This is what made the picker say "not linked to a
    # study" on the floor, so the smoke test must use it, not a synthetic
    # dict that already carries a study UID.
    dlg = ReportEditorDialog(
        {"content": "<p>hello</p>", "status": "pending"},
        {
            "_id": "68a1f0c0deadbeef",
            "receptionId": "54800",
            "nationalCode": "0046922229",
            "patient": {"Name": "porya mazaheri", "NationalID": "0046922229"},
        },
    )
    log("dialog constructed")

    for name in ("btn_image", "btn_img_smaller", "btn_img_larger", "btn_img_fit"):
        log(f"  {name}: exists={hasattr(dlg, name)} "
            f"enabled={getattr(dlg, name).isEnabled() if hasattr(dlg, name) else 'n/a'}")

    log(f"explicit study uid : {dlg._report_study_uid()!r}   (empty = the bug)")
    resolved = dlg._report_study_uids()
    log(f"resolved studies   : {resolved}")
    try:
        from modules.ai_imaging.ai_module_ui.service_tab.widgets.report_capture_images import (
            list_captured_images_for_studies,
        )
        found = list_captured_images_for_studies(resolved)
        log(f"captures the picker would show: {len(found)}")
        for uid, p in found:
            log(f"   {p.name}  study …{uid[-14:]}")
    except Exception as exc:
        log(f"   capture listing failed: {exc}")
    log(f"fitted width for 5000px: {dlg._fitted_width(5000)}")
    log(f"image at cursor: {dlg._image_format_at_cursor()[1]}")
    log(f"document type: {type(dlg.text_edit.document()).__name__}")
    log(f"toHtml length: {len(dlg.text_edit.toHtml())}")

    # Insert an image programmatically the same way the handler does, then
    # exercise the resize path.
    from PySide6.QtGui import QImage, QTextImageFormat
    import base64
    from PySide6.QtCore import QBuffer, QIODevice
    img = QImage(400, 300, QImage.Format.Format_RGB32)
    img.fill(0xFF3366AA)
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG", 88)
    uri = "data:image/jpeg;base64," + base64.b64encode(bytes(buf.data())).decode()
    buf.close()

    cur = dlg.text_edit.textCursor()
    fmt = QTextImageFormat()
    fmt.setName(uri)
    fmt.setWidth(400)
    fmt.setHeight(300)
    cur.insertImage(fmt)
    dlg.text_edit.setTextCursor(cur)
    log("image inserted")

    dlg._update_image_buttons()
    log(f"  after insert -> smaller enabled: {dlg.btn_img_smaller.isEnabled()}")

    c, f = dlg._image_format_at_cursor()
    log(f"  detected image width: {f.width() if f else None}")
    dlg._scale_image_at_cursor(1 / 1.1)
    c2, f2 = dlg._image_format_at_cursor()
    log(f"  after smaller       : {f2.width() if f2 else None}")
    dlg._scale_image_at_cursor(1.1)
    c3, f3 = dlg._image_format_at_cursor()
    log(f"  after larger        : {f3.width() if f3 else None}")
    dlg._fit_image_at_cursor()
    c4, f4 = dlg._image_format_at_cursor()
    log(f"  after fit           : {f4.width() if f4 else None}")
    log(f"  aspect kept         : {round(f4.height()/f4.width(), 3)} (source 0.75)")

    html = dlg.text_edit.toHtml()
    log(f"toHtml keeps the image: {'data:image/jpeg;base64,' in html}")
    log("DONE")
except Exception:
    log("EXC:\n" + traceback.format_exc())
