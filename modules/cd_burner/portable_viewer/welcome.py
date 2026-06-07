"""Branded welcome page shown before the CD viewer opens (Persian, RTL).

Iran Nobat / AI-PACS product packaging: company statement, web links and a
prominent «مشاهده تصاویر» button that proceeds to the DICOM viewer. The
imaging-center identity from the media manifest is displayed when present.

Self-contained: PySide6 only; the logo ships in ``assets/aipacs_logo.png``
next to this module (works identically in dev and in the frozen bundle).
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

COMPANY_STATEMENT_FA = (
    "شرکت ایران نوبت، نماینده انحصاری کمپانی AI-PACS اروپا در زمینه "
    "مدیریت تصاویر پزشکی، نوبت‌دهی، نرم‌افزارهای پذیرش مطب، "
    "مدیریت کلینیک‌ها و پاراکلینیک‌ها می‌باشد."
)

# Web links shown on the welcome page. Product-specific links can be
# appended here when provided (label, url).
COMPANY_LINKS = (
    ("irannobat.ir", "https://irannobat.ir"),
    ("ino724.com", "https://ino724.com"),
)

_QSS = """
QWidget#welcomeRoot {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #0d1320, stop:0.5 #101a2e, stop:1 #0b101c);
}
/* The viewer's global QSS paints every QWidget #14181d — make labels on
   this page transparent so the gradient/card colors show through. */
QWidget#welcomeRoot QLabel { background: transparent; }
QLabel#brandTitle { color: #e8eef7; font-size: 34px; font-weight: 800; }
QLabel#brandSub   { color: #7fa3d4; font-size: 15px; font-weight: 600; letter-spacing: 1px; }
QFrame#card {
    background-color: rgba(23, 33, 51, 0.92);
    border: 1px solid #2b3b58;
    border-radius: 16px;
}
QLabel#statement  { color: #e2e8f0; font-size: 17px; line-height: 1.8; }
QLabel#centerInfo { color: #93c5fd; font-size: 14px; font-weight: 600; }
QPushButton#linkBtn {
    background: transparent; color: #60a5fa; border: none;
    font-size: 15px; font-weight: 600; text-decoration: underline; padding: 4px 10px;
}
QPushButton#linkBtn:hover { color: #93c5fd; }
QPushButton#openBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #3b82f6, stop:1 #2563eb);
    color: white; border: 1px solid #1d4ed8; border-radius: 12px;
    padding: 14px 44px; font-size: 19px; font-weight: 800;
}
QPushButton#openBtn:hover  { background-color: #2563eb; }
QPushButton#openBtn:pressed { background-color: #1e40af; }
QLabel#openSub { color: #9aa6b2; font-size: 12px; }
"""


def _logo_pixmap() -> Optional[QPixmap]:
    path = Path(__file__).resolve().parent / "assets" / "aipacs_logo.png"
    if path.is_file():
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            return pixmap
    return None


class WelcomePage(QWidget):
    """Full-window branded landing page. Emits ``proceed`` to open the viewer."""

    proceed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("welcomeRoot")
        self.setStyleSheet(_QSS)
        self.setLayoutDirection(Qt.RightToLeft)  # Persian-first page

        root = QVBoxLayout(self)
        root.setContentsMargins(40, 28, 40, 28)
        root.setSpacing(14)
        root.addStretch(1)

        # --- Brand header (logo + names) ---
        header = QVBoxLayout()
        header.setSpacing(6)
        logo = _logo_pixmap()
        if logo is not None:
            logo_label = QLabel()
            logo_label.setPixmap(
                logo.scaledToHeight(96, Qt.SmoothTransformation)
            )
            logo_label.setAlignment(Qt.AlignCenter)
            header.addWidget(logo_label, alignment=Qt.AlignCenter)
        title = QLabel("AI-PACS")
        title.setObjectName("brandTitle")
        title.setAlignment(Qt.AlignCenter)
        header.addWidget(title)
        subtitle = QLabel("ایران نوبت  ·  IRAN NOBAT  ·  INO724")
        subtitle.setObjectName("brandSub")
        subtitle.setAlignment(Qt.AlignCenter)
        header.addWidget(subtitle)
        root.addLayout(header)

        # --- Statement card ---
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(34, 26, 34, 26)
        card_layout.setSpacing(16)

        self.statement_label = QLabel(COMPANY_STATEMENT_FA)
        self.statement_label.setObjectName("statement")
        self.statement_label.setWordWrap(True)
        self.statement_label.setAlignment(Qt.AlignCenter)
        font = QFont(self.statement_label.font())
        font.setFamilies(["IRANSans", "Vazirmatn", "Segoe UI", "Tahoma"])
        self.statement_label.setFont(font)
        card_layout.addWidget(self.statement_label)

        self.center_label = QLabel("")
        self.center_label.setObjectName("centerInfo")
        self.center_label.setWordWrap(True)
        self.center_label.setAlignment(Qt.AlignCenter)
        self.center_label.setVisible(False)
        card_layout.addWidget(self.center_label)

        # --- Links row ---
        links_row = QHBoxLayout()
        links_row.addStretch(1)
        self.link_buttons = []
        for label, url in COMPANY_LINKS:
            button = QPushButton(label)
            button.setObjectName("linkBtn")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, u=url: QDesktopServices.openUrl(QUrl(u)))
            links_row.addWidget(button)
            self.link_buttons.append(button)
        links_row.addStretch(1)
        card_layout.addLayout(links_row)

        root.addWidget(card)

        # --- Open viewer button ---
        self.open_button = QPushButton("مشاهده تصاویر")
        self.open_button.setObjectName("openBtn")
        self.open_button.setCursor(Qt.PointingHandCursor)
        self.open_button.setDefault(True)
        self.open_button.clicked.connect(self.proceed.emit)
        root.addWidget(self.open_button, alignment=Qt.AlignCenter)

        open_sub = QLabel("Open Viewer")
        open_sub.setObjectName("openSub")
        open_sub.setAlignment(Qt.AlignCenter)
        root.addWidget(open_sub)

        root.addStretch(2)

    # -- API -------------------------------------------------------------

    def set_center_identity(self, center: Optional[Dict[str, str]]):
        """Show the burning center's identity (from the media manifest)."""
        center = center or {}
        parts = []
        if center.get("name"):
            parts.append(str(center["name"]))
        if center.get("address"):
            parts.append(str(center["address"]))
        if center.get("phone"):
            parts.append(f"☎ {center['phone']}")
        if parts:
            self.center_label.setText("  ·  ".join(parts))
            self.center_label.setVisible(True)
        else:
            self.center_label.clear()
            self.center_label.setVisible(False)

    def keyPressEvent(self, event):  # noqa: N802 — Qt override
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.proceed.emit()
        else:
            super().keyPressEvent(event)
