"""Editor for a patient's / study's demographic DICOM tags.

Opened from the main-page patient right-click menu ▸ "Edit patient / study
info". Presents the current values read from the DICOM on disk, lets the user
correct them, and applies the change to every image of every study on the row.

The heavy work (reading and rewriting potentially thousands of instances) runs
on a worker thread — see ``_DemographicEditWorker``. The GUI thread only ever
builds the dialog and consumes signals. Nothing in this file touches DICOM
files directly; it delegates to the pure
``PacsClient.utils.dicom_demographics_edit`` module.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from PacsClient.utils import dicom_demographics_edit as dde

logger = logging.getLogger(__name__)


class _DemographicEditWorker(QThread):
    """Runs the on-disk edit off the GUI thread."""

    progress = Signal(int, int, str)  # done, total, study_uid
    finished_ok = Signal(object)  # EditResult
    failed = Signal(str)

    def __init__(self, studies, values, parent=None):
        super().__init__(parent)
        self._studies = list(studies)
        self._values = dict(values)

    def run(self):
        try:
            result = dde.apply_demographic_edit(
                self._studies,
                self._values,
                progress=lambda d, t, u: self.progress.emit(d, t, u),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            logger.exception("[DICOM-EDIT] worker failed")
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)


class PatientEditDialog(QDialog):
    """Modal editor for the demographic tags of one patient's studies."""

    #: Emitted after a successful edit so the home panel can refresh the table
    #: and sync the local DB: (patient_id_before, applied_values, study_uids).
    editApplied = Signal(str, dict, list)

    def __init__(
        self,
        patient_id: str,
        patient_name: str,
        study_uids: Sequence[str],
        parent: Optional[QWidget] = None,
        source_path: Optional[Path] = None,
    ):
        super().__init__(parent)
        self._patient_id_before = str(patient_id or "").strip()
        self._study_uids = [str(u or "").strip() for u in study_uids if str(u or "").strip()]
        self._studies: List[Tuple[str, Path]] = dde.resolve_study_dirs(
            self._study_uids, source_path
        )
        self._worker: Optional[_DemographicEditWorker] = None
        self._editors: Dict[str, QLineEdit] = {}
        self._original: Dict[str, str] = {}

        self.setWindowTitle("Edit patient / study information")
        self.setModal(True)
        self.setMinimumWidth(560)

        self._build_ui(patient_name)
        self._load_current_values()

    # -- construction ------------------------------------------------------

    def _build_ui(self, patient_name: str):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        header = QLabel(
            f"<b>{patient_name or '(no name)'}</b> &nbsp;·&nbsp; "
            f"ID {self._patient_id_before or '—'} &nbsp;·&nbsp; "
            f"{len(self._studies)} stud{'y' if len(self._studies) == 1 else 'ies'}"
        )
        header.setTextFormat(Qt.RichText)
        root.addWidget(header)

        patient_box = QGroupBox("Patient — applies to every study on this row")
        patient_form = QFormLayout(patient_box)
        patient_form.setSpacing(8)
        for key, (_kw, label, _vr) in dde.PATIENT_FIELDS.items():
            patient_form.addRow(label + ":", self._make_editor(key))
        root.addWidget(patient_box)

        study_box = QGroupBox("Study")
        study_form = QFormLayout(study_box)
        study_form.setSpacing(8)
        for key, (_kw, label, _vr) in dde.STUDY_FIELDS.items():
            study_form.addRow(label + ":", self._make_editor(key))
        root.addWidget(study_box)

        self._editors["study_date"].setPlaceholderText("YYYYMMDD, e.g. 20260718")
        self._editors["study_time"].setPlaceholderText("HHMMSS, e.g. 143000")
        self._editors["patient_age"].setPlaceholderText("nnnD/W/M/Y, e.g. 045Y")

        if len(self._studies) > 1:
            note = QLabel(
                "⚠ This row has more than one study. The study fields below are "
                "applied to <b>all</b> of them — leave a field untouched to keep "
                "each study's own value."
            )
            note.setWordWrap(True)
            note.setTextFormat(Qt.RichText)
            root.addWidget(note)

        if not dde.server_push_supported():
            try:
                from database.patient_overrides import patient_overrides_enabled
                _alias_on = patient_overrides_enabled()
            except Exception:
                _alias_on = False
            _scope_msg = (
                "This change is written to the DICOM files and database on "
                "<b>this workstation only</b> — the server has no endpoint for "
                "updating demographics, so the reception / RIS server stays the "
                "<b>system of record</b> for patient identity and keeps the "
                "original ID. To correct it everywhere (reception, billing, "
                "other workstations), have <b>reception fix it at admission</b>."
            )
            if _alias_on:
                _scope_msg += (
                    " This workstation will keep <b>showing</b> your corrected "
                    "Patient ID in the list; server actions (assignment, "
                    "reports) still use the original ID underneath."
                )
            else:
                _scope_msg += (
                    " After “Refresh / Sync from server” the list shows the "
                    "server's original value again."
                )
            scope = QLabel(_scope_msg)
            scope.setWordWrap(True)
            scope.setTextFormat(Qt.RichText)
            scope.setStyleSheet("color:#d69e2e;")
            root.addWidget(scope)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        root.addWidget(line)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        self._progress.setTextVisible(True)
        root.addWidget(self._progress)

        buttons = QHBoxLayout()
        self._revert_btn = QPushButton("Reset fields")
        self._revert_btn.clicked.connect(self._reset_fields)
        buttons.addWidget(self._revert_btn)
        buttons.addStretch(1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel, self
        )
        self._buttons.button(QDialogButtonBox.Save).setText("Apply to all images")
        self._buttons.accepted.connect(self._on_apply)
        self._buttons.rejected.connect(self.reject)
        buttons.addWidget(self._buttons)
        root.addLayout(buttons)

    def _make_editor(self, key: str) -> QLineEdit:
        editor = QLineEdit()
        editor.setClearButtonEnabled(True)
        self._editors[key] = editor
        return editor

    # -- values ------------------------------------------------------------

    def _load_current_values(self):
        """Read the current tags from the first study that has files on disk."""
        values: Dict[str, str] = {}
        found_files = False
        for _uid, study_dir in self._studies:
            values = dde.read_demographics(study_dir)
            if values:
                found_files = True
                break

        if not found_files:
            values = {k: "" for k in dde.EDITABLE_FIELDS}
            values["patient_id"] = self._patient_id_before
            self._status.setText(
                "No DICOM files were found on disk for this patient. Download "
                "the study first — there is nothing to edit yet."
            )
            self._buttons.button(QDialogButtonBox.Save).setEnabled(False)
        else:
            total = sum(dde.count_study_files(d) for _u, d in self._studies)
            self._status.setText(
                f"{total} image(s) on disk will be updated. Originals are "
                f"backed up first, and DICOM identifiers "
                f"(Study/Series/SOP UID) are never changed."
            )

        self._original = dict(values)
        self._reset_fields()

    def _reset_fields(self):
        for key, editor in self._editors.items():
            editor.setText(self._original.get(key, ""))

    def _changed_values(self) -> Dict[str, str]:
        """Only the fields the user actually altered."""
        changed: Dict[str, str] = {}
        for key, editor in self._editors.items():
            new = dde.normalize_value(key, editor.text())
            old = dde.normalize_value(key, self._original.get(key, ""))
            if new != old:
                changed[key] = new
        return changed

    # -- apply -------------------------------------------------------------

    def _on_apply(self):
        changed = self._changed_values()
        if not changed:
            QMessageBox.information(self, "Nothing to do", "No fields were changed.")
            return

        problems = dde.validate_edit(changed)
        if problems:
            QMessageBox.warning(self, "Invalid value", "\n".join(problems))
            return

        total = sum(dde.count_study_files(d) for _u, d in self._studies)
        lines = [
            f"{dde.EDITABLE_FIELDS[k][1]}:  "
            f"{self._original.get(k) or '(empty)'}  →  {v or '(empty)'}"
            for k, v in changed.items()
        ]
        confirm = QMessageBox.question(
            self,
            "Apply to all images?",
            f"The following will be written to {total} image(s) across "
            f"{len(self._studies)} stud{'y' if len(self._studies) == 1 else 'ies'}:"
            "\n\n" + "\n".join(lines) + "\n\n"
            "Originals are backed up first and DICOM identifiers are preserved.\n"
            "Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        self._set_busy(True)
        self._progress.setRange(0, max(1, total))
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._status.setText("Writing… do not close the application.")

        self._done_files = 0
        self._worker = _DemographicEditWorker(self._studies, changed, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int, study_uid: str):
        self._progress.setValue(min(self._progress.maximum(), self._progress.value() + 1))

    def _on_failed(self, message: str):
        self._set_busy(False)
        self._progress.setVisible(False)
        self._status.setText("")
        QMessageBox.critical(self, "Edit failed", message)

    def _on_finished(self, result):
        self._set_busy(False)
        self._progress.setVisible(False)

        if not result.ok:
            detail = result.summary()
            backups = [s.backup_dir for s in result.studies if s.backup_dir]
            if backups:
                detail += f"\n\nOriginals are preserved in:\n" + "\n".join(backups)
            QMessageBox.critical(self, "Edit did not complete", detail)
            self._status.setText("")
            return

        note = result.summary()
        if result.server_push_note:
            note += "\n\n" + result.server_push_note

        try:
            self.editApplied.emit(
                self._patient_id_before,
                dict(result.applied_values),
                list(self._study_uids),
            )
        except Exception:
            logger.exception("[DICOM-EDIT] editApplied handler raised")

        QMessageBox.information(self, "Changes applied", note)
        self.accept()

    def _set_busy(self, busy: bool):
        self._buttons.setEnabled(not busy)
        self._revert_btn.setEnabled(not busy)
        for editor in self._editors.values():
            editor.setReadOnly(busy)

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event):
        worker = self._worker
        if worker is not None and worker.isRunning():
            # A half-written study must never be left behind: block the close
            # until the worker finishes its current study (which either
            # completes or rolls itself back from the backup).
            QMessageBox.information(
                self,
                "Please wait",
                "The images are still being updated. This window will close "
                "when the operation finishes.",
            )
            event.ignore()
            return
        super().closeEvent(event)
