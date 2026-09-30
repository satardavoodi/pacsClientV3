"""Local Education transfer UI. Filesystem and database work stays on a worker."""
from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QCheckBox,
    QFileDialog, QProgressBar,
)

from modules.education.portable_transfer import (
    export_package, import_package, TransferError,
)


class TransferWorker(QThread):
    progress = Signal(str)

    def __init__(self, operation, path, options, parent=None):
        super().__init__(parent)
        self.operation, self.path, self.options = operation, path, options
        self.result = None
        self.error = ""

    def run(self):
        try:
            action = export_package if self.operation == "export" else import_package
            self.result = action(self.path, progress=self.progress.emit,
                                 cancel=self.isInterruptionRequested, **self.options)
        except TransferError as exc:
            self.error = str(exc)
        except Exception:
            self.error = "Transfer failed. Check available disk space, file access and the package, then try again."


class EducationTransferDialog(QDialog):
    imported = Signal()

    def __init__(self, parent=None, *, mode=None):
        super().__init__(parent)
        self.worker = None
        self.setWindowTitle("Transfer Education")
        self.resize(580, 320)
        layout = QVBoxLayout(self)
        description = QLabel(
            "Move your saved Education content to another computer. Export one package, "
            "then choose Import Package on the other computer.\n\n"
            "Includes course slides, downloaded books and videos, DICOM and other media, "
            "and Case of the Day attachments and recordings. Save current edits first.")
        description.setWordWrap(True)
        layout.addWidget(description)
        self.courses = QCheckBox("All local courses and downloaded learning resources")
        self.cases = QCheckBox("All local Cases of the Day")
        self.courses.setChecked(True)
        self.cases.setChecked(True)
        layout.addWidget(self.courses)
        layout.addWidget(self.cases)
        self.allow_editing = QCheckBox("Allow editing exported courses and learning resources")
        self.allow_editing.setChecked(True)
        self.allow_editing.setToolTip("Uncheck to make the exported copy read-only. Existing read-only restrictions are retained.")
        layout.addWidget(self.allow_editing)
        privacy = QLabel("Private transfer: original files and patient information are retained. "
                         "The package is not encrypted or anonymized. Keep it on trusted storage.")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        row = QHBoxLayout()
        self.export_button = QPushButton("Export Package...")
        self.import_button = QPushButton("Import Package...")
        self.export_button.clicked.connect(self._export)
        self.import_button.clicked.connect(self._import)
        row.addWidget(self.export_button)
        row.addWidget(self.import_button)
        layout.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        self.status = QLabel("Import adds content without replacing existing courses or cases.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.close_button = QPushButton("Close")
        self.close_button.clicked.connect(self.reject)
        layout.addWidget(self.close_button)
        if mode == "export":
            self.setWindowTitle("Export Education")
            self.import_button.hide()
        elif mode == "import":
            self.setWindowTitle("Import Education")
            self.export_button.hide()
            self.courses.hide()
            self.cases.hide()
            self.allow_editing.hide()

    def _export(self):
        if not self.courses.isChecked() and not self.cases.isChecked():
            self.status.setText("Select at least one category to export.")
            return
        chooser = QFileDialog(self, "Export Education")
        chooser.setAcceptMode(QFileDialog.AcceptSave)
        chooser.setNameFilter("Education Package (*.aipacs-edu)")
        chooser.setDefaultSuffix("aipacs-edu")
        chooser.selectFile("education.aipacs-edu")
        if chooser.exec() == QDialog.Accepted:
            path = chooser.selectedFiles()[0]
            self._start("export", path, dict(include_courses=self.courses.isChecked(), include_cases=self.cases.isChecked(), allow_editing=self.allow_editing.isChecked()))

    def _import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import Education", "", "Education Package (*.aipacs-edu)")
        if path:
            self._start("import", path, {})

    def _start(self, operation, path, options):
        if self.worker is not None:
            return
        for widget in (self.export_button, self.import_button, self.courses, self.cases, self.allow_editing):
            widget.setEnabled(False)
        self.close_button.setText("Cancel Transfer")
        self.progress.setRange(0, 0)
        self.progress.setVisible(True)
        self.status.setText("Preparing saved content...")
        self.worker = TransferWorker(operation, path, options, self)
        self.worker.progress.connect(self.status.setText)
        self.worker.finished.connect(self._finished)
        self.worker.start()

    def _finished(self):
        worker = self.worker
        self.worker = None
        self.progress.setVisible(False)
        for widget in (self.export_button, self.import_button, self.courses, self.cases, self.allow_editing):
            widget.setEnabled(True)
        self.close_button.setText("Close")
        if worker.error:
            self.status.setText(worker.error)
        elif worker.result.get("already_imported"):
            self.status.setText("This package was already imported. No duplicate content was added.")
        else:
            result = worker.result
            self.status.setText(f"{worker.operation.title()} complete: {result['courses']} courses/resources, "
                                f"{result['cases']} cases, {result['files']} files.")
            if worker.operation == "import":
                self.imported.emit()
        worker.deleteLater()

    def reject(self):
        if self.worker is not None:
            self.worker.requestInterruption()
            self.status.setText("Cancelling safely...")
            return
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self.reject()
            event.ignore()
        else:
            super().closeEvent(event)
