"""Non-modal result and retry panel for Legion Consult."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)


logger = logging.getLogger(__name__)
_BUTTON_QSS = """
QPushButton {
    background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
    border-radius: 6px; padding: 6px 14px; font-weight: 600;
}
QPushButton:hover { background: #273549; }
QPushButton:disabled { color: #64748b; border-color: #1e293b; }
"""


def _text_view() -> QPlainTextEdit:
    view = QPlainTextEdit()
    view.setReadOnly(True)
    view.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
    font = QFont("Consolas")
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    view.setFont(font)
    view.setStyleSheet(
        "QPlainTextEdit { background: #111827; color: #e2e8f0; "
        "border: 1px solid #1f2937; border-radius: 8px; padding: 10px; }"
    )
    return view


class LegionConsultResultPanel(QDialog):
    """Show final consultation and the preserved first-stage screening."""

    reanalyzeRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._session_dir: Path | None = None
        self.setWindowTitle("Legion Consult")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.setMinimumSize(700, 520)
        self.resize(860, 700)
        self.setStyleSheet("QDialog { background: #0f172a; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        self.title_label = QLabel("Legion Consult")
        self.title_label.setStyleSheet(
            "color: #34d399; font-size: 15px; font-weight: 700;"
        )
        layout.addWidget(self.title_label)
        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color: #9ca3af; font-size: 11px;")
        layout.addWidget(self.meta_label)

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabWidget { color: #e2e8f0; }")
        self.consultation = _text_view()
        self.screening = _text_view()
        self.tabs.addTab(self.consultation, "Final consultation")
        self.tabs.addTab(self.screening, "Step 1 screening")
        layout.addWidget(self.tabs, 1)

        buttons = QHBoxLayout()
        self.btn_copy = QPushButton("Copy current tab")
        self.btn_folder = QPushButton("Open session folder")
        self.btn_reanalyze = QPushButton("Re-analyze")
        self.btn_close = QPushButton("Close")
        for button in (
            self.btn_copy,
            self.btn_folder,
            self.btn_reanalyze,
            self.btn_close,
        ):
            button.setStyleSheet(_BUTTON_QSS)
        self.btn_copy.clicked.connect(self._copy_current)
        self.btn_folder.clicked.connect(self._open_folder)
        self.btn_reanalyze.clicked.connect(self.reanalyzeRequested.emit)
        self.btn_close.clicked.connect(self.hide)
        buttons.addWidget(self.btn_copy)
        buttons.addWidget(self.btn_folder)
        buttons.addStretch(1)
        buttons.addWidget(self.btn_reanalyze)
        buttons.addWidget(self.btn_close)
        layout.addLayout(buttons)

    def set_busy(self, message: str) -> None:
        self.title_label.setText("Legion Consult — analyzing")
        self.title_label.setStyleSheet(
            "color: #fbbf24; font-size: 15px; font-weight: 700;"
        )
        self.consultation.setPlainText(message)
        self.btn_reanalyze.setEnabled(False)
        self.present()

    def set_stage(self, number: int, total: int, name: str) -> None:
        labels = {
            "screening": "Step 1: lesion screening with Gemini",
            "verification": "Step 2: high-specificity consultation with GPT-5.6",
        }
        self.set_busy(labels.get(name, f"Analysis stage {number} of {total}: {name}"))

    def show_record(self, record) -> None:
        self._session_dir = Path(record.path)
        document = getattr(record, "document", {}) or {}
        models = [str(value) for value in document.get("stage_models") or ()]
        self.meta_label.setText(
            "  ·  ".join(
                value
                for value in (
                    f"session {self._session_dir.name}",
                    f"models {' → '.join(models)}" if models else "",
                    f"{document.get('image_count')} evidence images"
                    if document.get("image_count")
                    else "",
                    str(getattr(record, "completed_at", "") or ""),
                )
                if value
            )
        )
        self.consultation.setPlainText(str(getattr(record, "text", "") or ""))
        try:
            screening = (self._session_dir / "llm_stage1_response.txt").read_text(
                encoding="utf-8"
            )
        except (OSError, ValueError):
            screening = "The Step 1 response is not available."
        self.screening.setPlainText(screening)
        self.title_label.setText("Legion Consult — completed")
        self.title_label.setStyleSheet(
            "color: #34d399; font-size: 15px; font-weight: 700;"
        )
        self.btn_reanalyze.setEnabled(True)
        self.tabs.setCurrentIndex(0)
        self.present()

    def show_failure(self, session_dir: str | Path, message: str) -> None:
        self._session_dir = Path(session_dir)
        self.title_label.setText("Legion Consult — analysis failed")
        self.title_label.setStyleSheet(
            "color: #f87171; font-size: 15px; font-weight: 700;"
        )
        self.consultation.setPlainText(
            f"{message}\n\nThe saved ROI remains available. Any successfully prepared "
            "derived evidence will be reused. Re-analyze does not require drawing "
            "the ROI again."
        )
        self.btn_reanalyze.setEnabled(True)
        self.tabs.setCurrentIndex(0)
        self.present()

    def present(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _current_view(self) -> QPlainTextEdit:
        widget = self.tabs.currentWidget()
        return widget if isinstance(widget, QPlainTextEdit) else self.consultation

    def _copy_current(self) -> None:
        QGuiApplication.clipboard().setText(self._current_view().toPlainText())

    def _open_folder(self) -> None:
        if self._session_dir is None:
            return
        path = str(self._session_dir)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            logger.warning(
                "[LEGION-CONSULT] event=open_folder_failed error=%s",
                exc.__class__.__name__,
            )
