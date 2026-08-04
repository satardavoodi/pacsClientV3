"""Visual check for the field trailing-icon buttons (2026-08-04).

Builds the REAL field widgets (LoginComboField / LoginLineField / LoginDateField)
at both field heights in use - 36 on the Home page, 40 on login/settings - with
AIPACS_FIELD_ICON_CHIP off (legacy rail) and on (rounded chip), and writes a
side-by-side PNG next to this file.

Run it after any change to `_configure_icon_rail_button` / `_icon_rail_btn_qss`
in `PacsClient/utils/login_form_styles.py`; those two helpers decide the look of
every trailing icon button in the app, so a change there is never local:

    .venv\\Scripts\\python.exe tests\\bench\\render_field_chips.py

Inspection tool, not a pytest gate - the assertions live in
`tests/code/ui_services/test_field_icon_chip.py`.
"""
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QPainter, QPixmap, QColor, QFont       # noqa: E402
from PySide6.QtWidgets import (                                  # noqa: E402
    QApplication, QWidget, QVBoxLayout, QLabel,
)

app = QApplication.instance() or QApplication([])

from PacsClient.utils import login_form_styles as LFS            # noqa: E402
from PacsClient.utils.theme_manager import get_theme_manager     # noqa: E402

THEME = get_theme_manager().current_theme()
FIELD_H = 36
PANEL = THEME.get("panel_bg", "#0f1419")


def build_panel(title: str, field_h: int = FIELD_H) -> QWidget:
    """One column holding every field type that carries a trailing icon."""
    box = QWidget()
    box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    box.setStyleSheet(f"background: {PANEL};")
    box.setFixedWidth(300)
    lay = QVBoxLayout(box)
    lay.setContentsMargins(14, 12, 14, 14)
    lay.setSpacing(10)

    cap = QLabel(title)
    f = QFont("Roboto", 11)
    f.setBold(True)
    cap.setFont(f)
    cap.setStyleSheet(
        f"color: {THEME.get('text_primary', '#f8fafc')}; background: transparent;")
    lay.addWidget(cap)

    server = LFS.LoginComboField(field_h=field_h)
    server.addItem("razi", "razi")
    server.apply_theme(THEME, font_pt=12, field_h=field_h)
    lay.addWidget(server)

    pid = LFS.LoginLineField(field_h=field_h, trailing_icon="fa5s.sliders-h",
                             trailing_tooltip="Advanced search")
    pid.setPlaceholderText("Patient ID (e.g., 12345)")
    pid.apply_theme(THEME, font_pt=12, field_h=field_h)
    lay.addWidget(pid)

    pname = LFS.LoginLineField(field_h=field_h, trailing_icon="fa5s.user",
                               trailing_tooltip="Patient name", trailing_action=False)
    pname.setPlaceholderText("Patient Name (e.g., John Doe)")
    pname.apply_theme(THEME, font_pt=12, field_h=field_h)
    lay.addWidget(pname)

    preset = LFS.LoginComboField(field_h=field_h)
    preset.addItem("Custom Date", "custom")
    preset.apply_theme(THEME, font_pt=12, field_h=field_h)
    lay.addWidget(preset)

    for _ in range(2):
        d = LFS.LoginDateField(field_h=field_h)
        d.setDisplayFormat("yyyy-MM-dd")
        d.apply_theme(THEME, font_pt=12, field_h=field_h)
        lay.addWidget(d)

    lay.addStretch(1)
    box.adjustSize()
    box.setFixedHeight(box.sizeHint().height())
    return box


def grab(title: str, chip: bool, field_h: int = FIELD_H) -> QPixmap:
    os.environ["AIPACS_FIELD_ICON_CHIP"] = "1" if chip else "0"
    w = build_panel(title, field_h)
    w.show()
    app.processEvents()
    pm = w.grab()
    w.hide()
    return pm


def main() -> int:
    cols = [
        grab("BEFORE  home h=36", chip=False, field_h=36),
        grab("AFTER  home h=36", chip=True, field_h=36),
        grab("AFTER  login h=40", chip=True, field_h=40),
    ]

    gap = 16
    h = max(c.height() for c in cols)
    canvas = QPixmap(sum(c.width() for c in cols) + gap * (len(cols) + 1), h + gap * 2)
    canvas.fill(QColor("#0b0f16"))
    p = QPainter(canvas)
    x = gap
    for c in cols:
        p.drawPixmap(x, gap, c)
        x += c.width() + gap
    p.end()

    # 2x so the corner radius is actually legible in a screenshot
    canvas = canvas.scaled(canvas.width() * 2, canvas.height() * 2,
                           Qt.AspectRatioMode.KeepAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    out = Path(__file__).with_name("field_chip_before_after.png")
    canvas.save(str(out))
    print(f"WROTE {out}  ({canvas.width()}x{canvas.height()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
