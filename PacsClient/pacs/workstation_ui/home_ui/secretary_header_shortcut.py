"""Persistent header entry point for the existing global F12 popup."""
from pathlib import Path
import qtawesome as qta
from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QPen, QColor, QIcon
from PySide6.QtWidgets import QToolButton
from PacsClient.utils import IMAGES_LOGIN_PATH


def create_secretary_header_shortcut(parent):
    button = QToolButton(parent)
    button.setObjectName("SecretaryHeaderShortcut")
    button.setAccessibleName("Secretary EchoMind")
    button.setToolTip("Secretary EchoMind (F12)")
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedSize(70, 70)
    button.setIconSize(QSize(58, 58))
    button.setStyleSheet("QToolButton {background:transparent;border:1px solid #455b70;border-radius:8px;} QToolButton:hover {background:#203b50;border-color:#78cedf;}")
    pixmap = QPixmap(58, 58)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    circle = QRectF(2, 2, 54, 54)
    clip = QPainterPath()
    clip.addEllipse(circle)
    painter.setClipPath(clip)
    painter.fillRect(circle, QColor("#0c1923"))
    texture = QPixmap(str(Path(IMAGES_LOGIN_PATH) / "Echo-Mind2.png"))
    if not texture.isNull():
        painter.drawPixmap(2, 2, texture.scaled(54, 54, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
    painter.setClipping(False)
    painter.setPen(QPen(QColor("#78cedf"), 1.5))
    painter.drawEllipse(circle)
    painter.drawPixmap(19, 18, qta.icon("fa5s.user-tie", color="#a9e7f3").pixmap(20, 24))
    painter.end()
    button.setIcon(QIcon(pixmap))
    def toggle():
        from .secretary_popup import SecretaryPopup
        SecretaryPopup.toggle_for(button.window())
    button.clicked.connect(toggle)
    return button
