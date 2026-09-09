"""Non-modal gallery for the immutable images used at each Eagle Eye stage."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .stage_audit import StageAuditImage, StageAuditSection, build_stage_audit

logger = logging.getLogger(__name__)

_BG = "#0f172a"
_PANEL = "#111827"
_FG = "#e2e8f0"
_MUTED = "#9ca3af"
_ACCENT = "#34d399"


class _StagePage(QWidget):
    def __init__(self, section: StageAuditSection, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._section = section

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        summary = QLabel(f"Status: {section.status}\n{section.summary}")
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary.setStyleSheet(f"color: {_MUTED}; padding: 4px;")
        layout.addWidget(summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list_widget = QListWidget()
        self.list_widget.setMinimumWidth(260)
        self.list_widget.setStyleSheet(
            f"QListWidget {{ background: {_PANEL}; color: {_FG}; border: 1px solid #334155; }}"
            "QListWidget::item { padding: 8px; }"
            "QListWidget::item:selected { background: #1e3a5f; }"
        )
        splitter.addWidget(self.list_widget)

        preview_host = QWidget()
        preview_layout = QVBoxLayout(preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setStyleSheet(f"color: {_FG}; padding: 6px;")
        preview_layout.addWidget(self.details)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setStyleSheet("QScrollArea { background: #05070b; border: 1px solid #334155; }")
        self.preview = QLabel("No stored image is available for this stage.")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet(f"color: {_MUTED}; background: #05070b;")
        self.scroll.setWidget(self.preview)
        preview_layout.addWidget(self.scroll, 1)
        splitter.addWidget(preview_host)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

        for image in section.images:
            item = QListWidgetItem(image.label)
            item.setData(Qt.ItemDataRole.UserRole, image)
            item.setToolTip(image.details or str(image.path.name))
            self.list_widget.addItem(item)
        self.list_widget.currentItemChanged.connect(self._show_current)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _show_current(self, current, _previous=None) -> None:
        image = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if not isinstance(image, StageAuditImage):
            return
        self.details.setText(image.details or image.label)
        pixmap = QPixmap(str(image.path))
        if pixmap.isNull():
            self._pixmap = QPixmap()
            self.preview.setPixmap(QPixmap())
            self.preview.setText("The stored image could not be decoded.")
            return
        self._pixmap = pixmap
        self.preview.setText("")
        self._fit_preview()

    def _fit_preview(self) -> None:
        if self._pixmap.isNull():
            return
        viewport = self.scroll.viewport().size()
        target = viewport.boundedTo(self._pixmap.size())
        if target.width() < 32 or target.height() < 32:
            return
        scaled = self._pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview.setPixmap(scaled)
        self.preview.resize(scaled.size())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._fit_preview()


class EagleEyeStageAuditPanel(QDialog):
    """Show exact stored image inputs and gates without touching live viewers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_dir: Path | None = None
        self.setWindowTitle("Eagle Eye - Stage Images")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.setMinimumSize(900, 640)
        self.resize(1200, 800)
        self.setStyleSheet(f"QDialog {{ background: {_BG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 10)
        self.title = QLabel("Eagle Eye stage-by-stage image audit")
        self.title.setStyleSheet(f"color: {_ACCENT}; font-size: 15px; font-weight: 700;")
        layout.addWidget(self.title)
        self.subtitle = QLabel(
            "These are immutable stored artifacts. Opening this window does not recapture the study."
        )
        self.subtitle.setStyleSheet(f"color: {_MUTED};")
        layout.addWidget(self.subtitle)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(f"QTabWidget {{ color: {_FG}; }}")
        layout.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.hide)
        buttons.addWidget(close_button)
        layout.addLayout(buttons)

    @property
    def session_dir(self) -> Path | None:
        return self._session_dir

    def show_session(self, session_dir: str | Path) -> None:
        self._session_dir = Path(session_dir)
        self.tabs.clear()
        try:
            audit = build_stage_audit(self._session_dir)
            for section in audit.sections:
                page = _StagePage(section, self.tabs)
                label = section.title
                if section.status in {"truncated", "unavailable", "not run"}:
                    label += " !"
                self.tabs.addTab(page, label)
        except Exception as exc:
            logger.warning("[EAGLE-EYE-AUDIT] could not build stage gallery: %s", exc)
            failure = QLabel("Stage images could not be loaded from this session.")
            failure.setStyleSheet(f"color: {_FG}; padding: 20px;")
            self.tabs.addTab(failure, "Unavailable")
        self.show()
        self.raise_()
        self.activateWindow()
