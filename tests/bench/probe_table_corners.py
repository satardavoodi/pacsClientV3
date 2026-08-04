"""Objective probe: is the patient table's frame corner actually rounded?

Renders the table widget itself onto a purple canvas via QWidget.render(), so the
table's rect is known exactly. A ROUNDED corner leaves purple showing in the
corner block; a SQUARE one covers it. No eyeballing, no layout guesswork.
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

PAGE_RGB = (109, 40, 217)
PAD = 20


def probe(rounded: bool, v2: bool):
    os.environ["AIPACS_TABLE_ROUNDED"] = "1" if rounded else "0"
    from PacsClient.utils import v2_style
    v2_style.home_is_v2 = lambda: v2
    from PacsClient.pacs.workstation_ui.home_ui import patient_table_widget as ptw

    t = ptw.PatientTableWidget()
    t._apply_theme()
    for i in range(4):
        t.add_patient_data(patient_id=f"P{i}", patient_name=f"N{i}",
                           study_date="20260801", modality="CT",
                           study_uid=f"1.2.3.{i}", is_downloaded=True)
    tbl = t.results_table
    # HYPOTHESIS: QHeaderView's `:last` pseudo-state is assigned by section index
    # including HIDDEN sections. The last three columns (study_uid, order,
    # imported_on) are hidden, so no VISIBLE section ever gets `:last` and the
    # top-right radius never applies. Unhide them and the corner should round.
    if os.environ.get("PROBE_UNHIDE") == "1":
        for c in range(tbl.columnCount()):
            tbl.setColumnHidden(c, False)
    tbl.horizontalHeader().setStretchLastSection(True)
    tbl.resize(900, 220)
    t.resize(920, 300)
    app.processEvents()

    w, h = tbl.width(), tbl.height()
    pm = QPixmap(w + PAD * 2, h + PAD * 2)
    pm.fill(QColor(*PAGE_RGB))
    p = QPainter(pm)
    # DrawChildren ONLY: the default also includes DrawWindowBackground, which
    # fills the widget's SQUARE rect with the palette brush before the stylesheet
    # paints — that would hide any rounding and make this probe meaningless.
    from PySide6.QtGui import QRegion
    from PySide6.QtWidgets import QWidget as _QW
    tbl.render(p, QPoint(PAD, PAD), QRegion(), _QW.RenderFlag.DrawChildren)
    p.end()
    img = pm.toImage()

    corners = {
        "top-left":     (PAD,             PAD,          1,  1),
        "top-right":    (PAD + w - 1,     PAD,         -1,  1),
        "bottom-left":  (PAD,             PAD + h - 1,  1, -1),
        "bottom-right": (PAD + w - 1,     PAD + h - 1, -1, -1),
    }
    out = {}
    for name, (cx, cy, dx, dy) in corners.items():
        hits = 0
        for i in range(4):
            for j in range(4):
                c = img.pixelColor(cx + dx * i, cy + dy * j)
                if (c.red(), c.green(), c.blue()) == PAGE_RGB:
                    hits += 1
        out[name] = hits
    return out, pm


for v2 in (True, False):
    tag = "V2 (what the user runs)" if v2 else "V1"
    print(f"\n########  {tag}  ########")
    for label, rounded in (("square (ROUNDED=0)", False), ("rounded (default)", True)):
        res, pm = probe(rounded, v2)
        print(f"  {label:<20} page-colour px per 4x4 corner block (16 = fully rounded, 0 = square)")
        for k, v in res.items():
            print(f"      {k:<14} {v:2d}/16")
        if rounded:
            pm.save(str(Path(__file__).with_name(f"corner_{'v2' if v2 else 'v1'}.png")))
