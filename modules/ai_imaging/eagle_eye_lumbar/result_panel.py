"""The Eagle Eye analysis result window owned by the feature package.

NON-MODAL BY CONSTRUCTION
-------------------------
A radiologist reads a report while scrolling the images it describes, so this
window must never take the workstation hostage. It is a top-level ``QDialog``
shown with ``show()`` and ``setModal(False)`` - never ``exec()``, which would
spin a nested event loop and block every other window until dismissed.

CLOSING IT MUST NOT DESTROY ANYTHING
------------------------------------
The result lives in ``llm_result.txt`` beside the captures, so this window owns
nothing. Closing hides it; reopening re-reads from disk. That is also why
``WA_DeleteOnClose`` is deliberately NOT set: the panel is reused, and a
deleted-on-close widget with a live reference is the crash this codebase has
already paid for once.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
)

logger = logging.getLogger(__name__)

_BG = "#0f172a"
_FG = "#e2e8f0"
_MUTED = "#9ca3af"
_ACCENT = "#34d399"
_PRODUCT_MODEL_LABEL = "AI-PACS AI Lumbar Analysis"

_BUTTON_QSS = """
QPushButton {
    background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
    border-radius: 6px; padding: 6px 14px; font-weight: 600;
}
QPushButton:hover   { background: #273549; }
QPushButton:pressed { background: #16202f; }
QPushButton:disabled{ color: #64748b; border-color: #1e293b; }
"""


class EagleEyeResultPanel(QDialog):
    """Shows one stored Eagle Eye analysis. Reusable, hideable, reopenable."""

    reanalyzeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_dir: Path | None = None

        self.setWindowTitle("Eagle Eye - Analysis")
        # A real top-level window: it has a title bar, so it can be moved and
        # closed, and it does not sit inside the tab's layout.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.setMinimumSize(620, 480)
        self.resize(760, 620)
        self.setStyleSheet(f"QDialog {{ background: {_BG}; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)

        self.title_label = QLabel("Eagle Eye analysis")
        self.title_label.setStyleSheet(
            f"color: {_ACCENT}; font-size: 15px; font-weight: 700;")
        layout.addWidget(self.title_label)

        self.meta_label = QLabel("")
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet(f"color: {_MUTED}; font-size: 11px;")
        layout.addWidget(self.meta_label)

        self.body = QPlainTextEdit()
        self.body.setReadOnly(True)
        self.body.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.body.setFont(font)
        self.body.setStyleSheet(
            f"QPlainTextEdit {{ background: #111827; color: {_FG};"
            f" border: 1px solid #1f2937; border-radius: 8px; padding: 10px; }}")
        layout.addWidget(self.body, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)

        self.btn_copy = QPushButton("Copy")
        self.btn_copy.setStyleSheet(_BUTTON_QSS)
        self.btn_copy.clicked.connect(self._copy_to_clipboard)
        buttons.addWidget(self.btn_copy)

        self.btn_folder = QPushButton("Open session folder")
        self.btn_folder.setStyleSheet(_BUTTON_QSS)
        self.btn_folder.clicked.connect(self._open_folder)
        buttons.addWidget(self.btn_folder)

        buttons.addStretch(1)

        self.btn_reanalyze = QPushButton("Re-analyze")
        self.btn_reanalyze.setStyleSheet(_BUTTON_QSS)
        self.btn_reanalyze.setToolTip(
            "Send the SAME captured images to the model again. The screenshots "
            "are not recaptured.")
        self.btn_reanalyze.clicked.connect(self.reanalyzeRequested.emit)
        buttons.addWidget(self.btn_reanalyze)

        self.btn_close = QPushButton("Close")
        self.btn_close.setStyleSheet(_BUTTON_QSS)
        self.btn_close.clicked.connect(self.hide)
        buttons.addWidget(self.btn_close)

        layout.addLayout(buttons)

    # -- content -----------------------------------------------------------

    @property
    def session_dir(self):
        return self._session_dir

    def show_record(self, record) -> None:
        """Render a `analysis_store.AnalysisRecord` and bring the window up."""
        self._session_dir = Path(record.path)

        document = getattr(record, "document", {}) or {}
        bits = [f"session {self._session_dir.name}"]
        bits.append(f"model {_PRODUCT_MODEL_LABEL}")
        analysis_id = document.get("pipeline_id") or document.get("prompt_id")
        if analysis_id:
            label = f"prompt {analysis_id} v{record.prompt_version}"
            if record.stage_count > 1:
                label += f" ({record.stage_count} passes)"
            bits.append(label)
        if document.get("image_count"):
            bits.append(f"{document['image_count']} images")
        if record.completed_at:
            bits.append(record.completed_at)
        usage = document.get("usage") or {}
        if usage.get("total_tokens"):
            bits.append(f"{usage['total_tokens']} tokens")
        self.meta_label.setText("  ·  ".join(bits))

        if record.has_result:
            self.title_label.setText("Eagle Eye analysis - pathological findings")
            self.title_label.setStyleSheet(
                f"color: {_ACCENT}; font-size: 15px; font-weight: 700;")
            self.body.setPlainText(record.text)
        else:
            self.title_label.setText(f"Eagle Eye - {record.label}")
            self.title_label.setStyleSheet(
                "color: #f87171; font-size: 15px; font-weight: 700;")
            self.body.setPlainText(
                (record.error or "No result is stored for this session.")
                + "\n\nThe captured images are unaffected and are still on disk. "
                  "Re-analyze sends them again; it does not recapture the study.")

        self.btn_copy.setEnabled(record.has_result)
        self.present()

    def present(self) -> None:
        """Show/raise without stealing the window if it is already visible."""
        self.show()
        self.raise_()
        self.activateWindow()

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Reflect an in-flight request without blocking anything."""
        self.btn_reanalyze.setEnabled(not busy)
        if busy:
            self.title_label.setText("Eagle Eye - analyzing")
            self.title_label.setStyleSheet(
                "color: #fbbf24; font-size: 15px; font-weight: 700;")
            if message:
                self.body.setPlainText(message)

    # -- actions -----------------------------------------------------------

    def _copy_to_clipboard(self) -> None:
        try:
            QGuiApplication.clipboard().setText(self.body.toPlainText())
        except Exception as exc:
            logger.warning("[EAGLE-EYE-LLM] clipboard copy failed: %s", exc)

    def _open_folder(self) -> None:
        if not self._session_dir:
            return
        path = str(self._session_dir)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606 - a folder the app just wrote
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            logger.warning("[EAGLE-EYE-LLM] could not open %s: %s", path, exc)
