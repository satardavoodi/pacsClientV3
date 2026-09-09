"""Thin Qt controller for DX wrist analysis and physician handoff."""

from __future__ import annotations

import logging
from pathlib import Path

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

from .analysis_runner import DXWristAnalysisRunner

logger = logging.getLogger(__name__)


class DXWristAnalysisController(QObject):
    """Keep DX wrist request and review logic outside the imaging tab."""

    _WAIT_MESSAGES = (
        "Preparing wrist radiographs...",
        "Reviewing the available views...",
        "Estimating skeletal maturity...",
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

    def bind_button(self, button: QPushButton, *, connect: bool = True) -> None:
        self._button = button
        if connect:
            button.clicked.connect(self.start)
        button.setVisible(getattr(self._owner, "eagle_eye_mode", "") == "bone_age")

    def start(self) -> None:
        from PacsClient.pacs.patient_tab.utils import show_message

        if str(self._owner.detect_modality() or "").upper() != "DX":
            show_message("DX wrist analysis is only available for bone-age studies.")
            return
        if self._state == "analyzing":
            show_message("DX wrist analysis is already in progress.")
            return
        if self._runner is not None:
            self._runner.detach()

        source_dir = self._current_source_dir()
        study_uid = str(getattr(self._owner, "study_uid", "") or "").strip()
        if not study_uid or not source_dir:
            show_message("The DX wrist DICOM source could not be resolved.")
            return

        self._set_state("analyzing")
        output_dir = ATTACHMENT_PATH / study_uid / "dx_wrist_ai_analyze"
        runner = DXWristAnalysisRunner(
            study_uid=study_uid,
            source_dir=source_dir,
            output_dir=str(output_dir),
            parent=self,
        )
        runner.progress.connect(self._on_progress)
        runner.finished.connect(self._on_finished)
        runner.failed.connect(self._on_failed)
        self._runner = runner
        if not runner.start():
            self._runner = None
            self._set_state("error", "DX wrist analysis could not start")

    def teardown(self) -> None:
        self._timer.stop()
        runner, self._runner = self._runner, None
        if runner is not None:
            runner.detach()

    def _current_source_dir(self) -> str:
        patient_widget = getattr(self._owner, "patient_widget", None)
        selected = getattr(patient_widget, "selected_widget", None)
        vtk_widget = getattr(selected, "vtk_widget", selected)
        image_viewer = getattr(vtk_widget, "image_viewer", None)
        metadata = getattr(image_viewer, "metadata", None)
        series = metadata.get("series", {}) if isinstance(metadata, dict) else {}
        source = series.get("series_path") or getattr(
            patient_widget, "import_folder_path", ""
        )
        return str(source or "").strip()

    def _on_progress(self, _stage: str, _message: str) -> None:
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
            self._set_state("idle", "DX wrist analysis review cancelled")
            return
        try:
            self._handoff_to_echomind(reviewed)
        except Exception:
            logger.exception("[DX_WRIST_AI] EchoMind report handoff failed")
            self._set_state("error", "Analysis complete; EchoMind handoff failed")
            self._show_result_fallback(reviewed)
            return
        self._set_state("ready", "DX wrist findings opened in EchoMind Report")

    def _on_failed(self, reason: str) -> None:
        from PacsClient.pacs.patient_tab.utils import show_message

        self._runner = None
        self._set_state("error", "DX wrist analysis failed")
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
        dialog.setWindowTitle("DX Wrist AI - Physician Review")
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
        dialog.setWindowTitle("DX Wrist AI - Findings")
        dialog.setMinimumSize(680, 540)
        layout = QVBoxLayout(dialog)
        body = QPlainTextEdit(dialog)
        body.setPlainText(findings)
        layout.addWidget(body, 1)
        close = QPushButton("Close", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()
