"""One-off: prove a captured image SURVIVES the whole report round-trip.

The feature is only real if the image makes it all the way through:

    capture PNG on disk
      -> encode_capture_for_report            (downscale + JPEG + base64)
      -> QTextCursor.insertImage              (into the editor document)
      -> document.toHtml()                    (what _save_report emits)
      -> prepare_report_html_for_server()     (the INO upload normaliser)
      -> setHtml() into a FRESH document      (reopening the saved report)
      -> loadResource resolves the data URI   (renders / prints, not a broken box)

Every one of those steps has a way to silently eat an <img>. This runs them
for real, on a real PNG, and reports sizes so the upload-payload question is
answered with a number instead of a guess.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\report_image_roundtrip_2026_08_18.py
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QUrl                                  # noqa: E402
from PySide6.QtGui import (                                      # noqa: E402
    QGuiApplication, QImage, QPainter, QTextCursor, QTextImageFormat,
)

from modules.ai_imaging.ai_module_ui.service_tab.widgets.report_capture_images import (  # noqa: E402
    encode_capture_for_report, make_data_uri_document,
)
from PacsClient.utils.report_server_html import prepare_report_html_for_server  # noqa: E402

FAILURES: list[str] = []

# Written incrementally to a sibling file as well as stdout: a hard Qt abort
# mid-run would otherwise lose every line and leave nothing to diagnose.
_LOG_PATH = Path(__file__).with_name("_report_image_roundtrip_out.txt")
_LOG: list[str] = []


def say(msg: str = "") -> None:
    text = str(msg)
    _LOG.append(text)
    try:
        sys.__stdout__.write(text + "\n")
        sys.__stdout__.flush()
    except Exception:
        pass
    try:
        _LOG_PATH.write_text("\n".join(_LOG), encoding="utf-8")
    except OSError:
        pass


# Route every remaining print() in this script through `say`, so the whole
# transcript lands in the sibling .txt even if Qt aborts mid-run.
print = say  # noqa: A001 - deliberate, one-off diagnostic script


def check(label: str, ok: bool, detail: str = "") -> None:
    say(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")
    if not ok:
        FAILURES.append(label)


def _as_image(resource):
    """QTextDocument.resource() hands back a QImage OR a QPixmap depending on
    who resolved it. Normalise, and return None for 'not resolved'."""
    if resource is None:
        return None
    from PySide6.QtGui import QPixmap
    if isinstance(resource, QPixmap):
        resource = resource.toImage()
    if not isinstance(resource, QImage):
        return None
    return None if resource.isNull() else resource


def _qt_version() -> str:
    try:
        from PySide6.QtCore import qVersion
        return qVersion()
    except Exception:
        return "unknown"


def make_capture(path: Path, w: int = 1920, h: int = 1080) -> int:
    """A realistic full-HD 'screenshot' with enough detail to resist trivial
    compression (a flat fill would encode to a few hundred bytes and prove
    nothing about payload size)."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(0xFF101820)
    painter = QPainter(img)
    try:
        for i in range(0, w, 7):
            painter.setPen(0xFF000000 | ((i * 37) & 0xFFFFFF))
            painter.drawLine(i, 0, w - i, h)
    finally:
        painter.end()
    img.save(str(path), "PNG")
    return path.stat().st_size


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    _ = app

    with tempfile.TemporaryDirectory() as tmp:
        capture = Path(tmp) / "capture_all_layouts_1.png"
        raw_bytes = make_capture(capture)

        print("\n1. ENCODE")
        encoded = encode_capture_for_report(capture)
        check("a full-HD PNG capture encodes", encoded is not None)
        if encoded is None:
            return 1
        b64_len = len(encoded.data_uri)
        print(f"      source PNG      : {raw_bytes/1024:8.1f} KB  (1920x1080)")
        print(f"      encoded JPEG    : {encoded.encoded_bytes/1024:8.1f} KB  "
              f"({encoded.width}x{encoded.height})")
        print(f"      data URI in HTML: {b64_len/1024:8.1f} KB")
        check("downscaled to the width cap", encoded.width <= 1000,
              f"width={encoded.width}")
        check("payload is a sane upload size", b64_len < 700_000,
              f"{b64_len/1024:.0f} KB of JSON per image")
        check("smaller than the raw capture", encoded.encoded_bytes < raw_bytes,
              f"{raw_bytes/encoded.encoded_bytes:.1f}x reduction")

        print("\n2. INSERT + toHtml  (what _save_report emits)")
        doc = make_data_uri_document()
        cursor = QTextCursor(doc)
        cursor.insertText("Findings: focal lesion in the right lobe.")
        cursor.insertBlock()
        fmt = QTextImageFormat()
        fmt.setName(encoded.data_uri)
        fmt.setWidth(600)
        fmt.setHeight(round(600 * encoded.height / encoded.width))
        cursor.insertImage(fmt)

        html = doc.toHtml()
        check("toHtml emits an <img>", "<img" in html)
        check("the image bytes travel with the html",
              "data:image/jpeg;base64," in html)
        m = re.search(r'<img[^>]*\bwidth="?(\d+)', html)
        check("the width survives toHtml", m is not None and int(m.group(1)) == 600,
              f"width={m.group(1) if m else 'missing'}")

        print("\n3. SERVER NORMALISER  (prepare_report_html_for_server)")
        server_html = prepare_report_html_for_server(html)
        check("the <img> is not stripped on upload", "<img" in server_html)
        check("the data URI is not stripped on upload",
              "data:image/jpeg;base64," in server_html)
        m2 = re.search(r'<img[^>]*\bwidth="?(\d+)', server_html)
        check("the width is not stripped on upload",
              m2 is not None and int(m2.group(1)) == 600,
              f"width={m2.group(1) if m2 else 'missing'}")
        check("the text still survives too", "focal lesion" in server_html)

        print("\n4. REOPEN  (setHtml into a fresh document)")
        reopened = make_data_uri_document()
        reopened.setHtml(server_html)
        round_html = reopened.toHtml()
        check("the image is still there after a save+reopen cycle",
              "data:image/jpeg;base64," in round_html)

        resolved = _as_image(reopened.resource(2, QUrl(encoded.data_uri)))
        check("loadResource decodes the data URI (renders, not a broken box)",
              resolved is not None,
              f"{resolved.width()}x{resolved.height()}" if resolved else "null")

        say("\n5. STOCK DOCUMENT  (is the custom document actually load-bearing?)")
        from PySide6.QtGui import QTextDocument
        stock = QTextDocument()
        stock.setHtml(server_html)
        stock_img = _as_image(stock.resource(2, QUrl(encoded.data_uri)))
        if stock_img is None:
            say("      stock document -> BROKEN image. The DataUriTextDocument "
                "subclass is REQUIRED.")
        else:
            say(f"      stock document -> resolved {stock_img.width()}x"
                f"{stock_img.height()}. This Qt build handles data URIs "
                "natively; the subclass is belt-and-braces, not the mechanism.")
        say(f"      Qt runtime: {_qt_version()}")

    print("\n" + "=" * 68)
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}):")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("All round-trip checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
