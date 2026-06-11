# -*- coding: utf-8 -*-
"""One-off: verify Qt editor toHtml() -> server export keeps Persian RTL.

Simulates the ReportEditorDialog save (QTextDocument serialization) and runs
the server exporter on it — the exact Path-2 (View/Edit Report) pipeline.
Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\check_qt_roundtrip_bidi.py
"""
import io
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PySide6.QtGui import QTextDocument  # noqa: E402

from PacsClient.utils.report_server_html import (  # noqa: E402
    LRM,
    prepare_report_html_for_server,
)

doc = QTextDocument()
doc.setHtml(
    "<p>گزارش MRI ستون فقرات: اندازه 25*45mm طبیعی است.</p>"
    "<p>Patient name: John. CT scan normal.</p>"
    "<p><span style='color:#aa0000;'>یافته مهم</span></p>"
)
qt_html = doc.toHtml()
out = prepare_report_html_for_server(qt_html)

print("root:", out[: out.index(">") + 1])
for p in re.findall(r"<p[^>]*>", out):
    print("P:", p[:130])
print("LRM in 25*45:", ("25" + LRM + "*45mm") in out)
print("color kept:", "aa0000" in out)
print("no chrome:", not any(t in out.lower() for t in ("<html", "<head", "<style", "<body")))
