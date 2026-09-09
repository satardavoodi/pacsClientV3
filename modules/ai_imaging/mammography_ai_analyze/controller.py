"""Thin Qt controller for the mammography analysis and physician handoff."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from PacsClient.utils.config import ATTACHMENT_PATH

from .analysis_runner import MammographyAnalysisRunner
from .source_snapshot import snapshot_mammography_source_hints

logger = logging.getLogger(__name__)


class MammographyAnalysisController(QObject):
    """Keep mammography request and review logic out of the imaging tab."""

    _WAIT_MESSAGES = (
        "Preparing mammography evidence...",
        "Reviewing all available views...",
        "Correlating AI detections...",
        "Still working...",
    )

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self._button = None
        self._runner = None
        self._state = "idle"
        self._wait_index = 0
        self._timer = QTimer(self)
        self._timer.setInterval(3000)
        self._timer.timeout.connect(self._next_wait_message)

    def bind_button(self, button: QPushButton) -> None:
        self._button = button
        button.clicked.connect(self.start)
        button.setVisible(getattr(self._owner, "eagle_eye_mode", "") == "mammography")

    def start(self) -> None:
        from PacsClient.pacs.patient_tab.utils import show_message

        if str(self._owner.detect_modality() or "").upper() != "MG":
            show_message("Intelligent AI Analyze is only available for mammography studies.")
            return
        if self._state == "analyzing":
            show_message("Mammography analysis is already in progress.")
            return
        if self._runner is not None:
            self._runner.detach()

        self._set_state("analyzing")
        local_source_hints = snapshot_mammography_source_hints(
            getattr(self._owner, "patient_widget", None)
        )
        runner = MammographyAnalysisRunner(
            study_uid=str(getattr(self._owner, "study_uid", "") or ""),
            attachments_root=ATTACHMENT_PATH,
            local_source_hints=local_source_hints,
            parent=self,
        )
        runner.progress.connect(self._on_progress)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        self._runner = runner
        if not runner.start():
            self._runner = None
            self._set_state("error", "Mammography analysis could not start")

    def teardown(self) -> None:
        self._timer.stop()
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.detach()

    def _on_progress(self, stage: str, message: str) -> None:
        if not self._timer.isActive():
            self._wait_index = 0
            self._timer.start()
        self._owner.set_processing_status(self._WAIT_MESSAGES[self._wait_index], active=True)

    def _next_wait_message(self) -> None:
        self._wait_index = (self._wait_index + 1) % len(self._WAIT_MESSAGES)
        self._owner.set_processing_status(self._WAIT_MESSAGES[self._wait_index], active=True)

    def _on_finished(self, findings: str) -> None:
        self._runner = None
        self._timer.stop()
        reviewed = self._review_findings(findings)
        if reviewed is None:
            self._set_state("idle", "Mammography analysis review cancelled")
            return
        try:
            self._handoff_to_echomind(reviewed)
        except Exception:
            logger.exception("[MAMMOGRAPHY-AI] EchoMind report handoff failed")
            self._set_state("error", "Analysis complete; EchoMind handoff failed")
            self._show_result_fallback(reviewed)
            return
        self._set_state("ready", "Mammography findings opened in EchoMind Report")

    def _on_failed(self, reason: str) -> None:
        from PacsClient.pacs.patient_tab.utils import show_message

        self._runner = None
        self._set_state("error", "Mammography analysis failed")
        show_message(f"Intelligent AI Analyze failed:\n{reason}")

    def _set_state(self, state: str, status: str = "") -> None:
        self._state = state
        busy = state == "analyzing"
        if not busy:
            self._timer.stop()
        if self._button is not None:
            self._button.setEnabled(not busy)
        if status:
            self._owner.set_processing_status(status, active=busy)
        elif busy:
            self._owner.set_processing_status(self._WAIT_MESSAGES[0], active=True)

    def _review_findings(self, findings: str) -> str | None:
        dialog = QDialog(self._owner)
        dialog.setWindowTitle("Mammography AI - Physician Review")
        dialog.setMinimumSize(680, 540)
        layout = QVBoxLayout(dialog)
        title = QLabel("Review and edit the AI-assisted findings before handoff.")
        title.setWordWrap(True)
        layout.addWidget(title)
        body = QPlainTextEdit(dialog)
        body.setFont(QFont("Consolas", 10))
        body.setPlainText(str(findings or ""))
        layout.addWidget(body, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = QPushButton("Cancel", dialog)
        confirm = QPushButton("Confirm and Open EchoMind Report", dialog)
        cancel.clicked.connect(dialog.reject)
        confirm.clicked.connect(dialog.accept)
        row.addWidget(cancel)
        row.addWidget(confirm)
        layout.addLayout(row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        reviewed = body.toPlainText().strip()
        return reviewed or None

    def _handoff_to_echomind(self, findings: str) -> None:
        patient_widget = getattr(self._owner, "patient_widget", None)
        opener = getattr(patient_widget, "ai_chat_layout_ui", None)
        if not callable(opener):
            raise RuntimeError("EchoMind is unavailable for this study.")
        window = opener()
        if window is None:
            raise RuntimeError("EchoMind could not be opened.")
        window._open_mode_page("Report")
        page = getattr(window, "_page", None)
        composer = getattr(page, "composer", None)
        append_text = getattr(composer, "append_text", None)
        if not callable(append_text):
            raise RuntimeError("The EchoMind report composer is unavailable.")
        append_text(findings)
        window.show()
        window.raise_()
        window.activateWindow()

    def _show_result_fallback(self, findings: str) -> None:
        dialog = QDialog(self._owner)
        dialog.setWindowTitle("Mammography AI - Findings")
        dialog.setMinimumSize(680, 540)
        layout = QVBoxLayout(dialog)
        body = QPlainTextEdit(dialog)
        body.setPlainText(findings)
        layout.addWidget(body, 1)
        close = QPushButton("Close", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
