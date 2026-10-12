"""Persistent Lumbar analysis page for the Eagle Eye study workspace."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .stage_audit_panel import EagleEyeStageAuditWidget


class LumbarAnalysisResultPage(QWidget):
    """Show the final text and its exact immutable stage cards in one tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._session_dir: Path | None = None
        self.setObjectName("eagleEyeLumbarResultPage")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        heading_row = QHBoxLayout()
        self.heading = QLabel("Eagle Eye Result")
        self.heading.setStyleSheet(
            "color:#34d399; font-size:18px; font-weight:700;"
        )
        heading_row.addWidget(self.heading)
        heading_row.addStretch(1)
        self.copy_button = QPushButton("Copy report")
        self.copy_button.clicked.connect(self._copy_report)
        heading_row.addWidget(self.copy_button)
        self.folder_button = QPushButton("Open analysis folder")
        self.folder_button.clicked.connect(self._open_folder)
        heading_row.addWidget(self.folder_button)
        outer.addLayout(heading_row)

        self.metadata = QLabel("")
        self.metadata.setWordWrap(True)
        self.metadata.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.metadata.setStyleSheet("color:#9ca3af;")
        outer.addWidget(self.metadata)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        report_host = QWidget(splitter)
        report_layout = QVBoxLayout(report_host)
        report_layout.setContentsMargins(0, 0, 0, 0)
        report_title = QLabel("Final analysis")
        report_title.setStyleSheet("color:#dcecff; font-size:14px; font-weight:700;")
        report_layout.addWidget(report_title)
        self.report = QPlainTextEdit(report_host)
        self.report.setObjectName("eagleEyeFinalReport")
        self.report.setReadOnly(True)
        self.report.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        font = QFont("Consolas")
        font.setStyleHint(QFont.StyleHint.Monospace)
        font.setPointSize(10)
        self.report.setFont(font)
        self.report.setStyleSheet(
            "QPlainTextEdit { background:#111827; color:#e2e8f0; "
            "border:1px solid #334155; border-radius:6px; padding:10px; }"
        )
        report_layout.addWidget(self.report, 1)
        splitter.addWidget(report_host)

        self.stage_gallery = EagleEyeStageAuditWidget(splitter)
        splitter.addWidget(self.stage_gallery)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([520, 820])
        outer.addWidget(splitter, 1)

    def show_record(self, record) -> None:
        self._session_dir = Path(record.path)
        document = dict(getattr(record, "document", {}) or {})
        self.heading.setText(
            "Eagle Eye Result - Review Required"
            if document.get("review_required") else "Eagle Eye Result"
        )
        bits = ["AI-PACS AI Lumbar Analysis"]
        version = str(document.get("pipeline_version") or "").strip()
        if version:
            bits.append(f"Pipeline {version}")
        completed = str(document.get("completed_at") or "").strip()
        if completed:
            bits.append(completed)
        tokens = (document.get("usage") or {}).get("total_tokens")
        if tokens:
            bits.append(f"{tokens} tokens")
        self.metadata.setText("  ·  ".join(bits))
        self.report.setPlainText(record.text if record.has_result else record.error)
        self.copy_button.setEnabled(record.has_result)
        self.folder_button.setEnabled(self._session_dir.is_dir())
        self.stage_gallery.load_session(self._session_dir)

    def _copy_report(self) -> None:
        QGuiApplication.clipboard().setText(self.report.toPlainText())

    def _open_folder(self) -> None:
        if self._session_dir is None or not self._session_dir.is_dir():
            return
        path = str(self._session_dir)
        if sys.platform.startswith("win"):
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
