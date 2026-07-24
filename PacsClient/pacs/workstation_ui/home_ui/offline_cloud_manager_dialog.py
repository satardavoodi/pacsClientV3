"""Offline-package MANAGER dialog — edit/delete patients already in a package.

The second Offline Service workflow (the first is add/export). Lists the
patients stored in an Offline Cloud package, lets the user multi-select and
DELETE them (patient-level: all their studies + files + DB rows + DICOMDIR +
manifest, atomically and recoverably), and reports the post-operation package
validation.

All package mutation goes through the engine primitives in
``PacsClient.utils.offline_cloud`` (``list_offline_cloud_patients`` /
``remove_patients_from_offline_cloud``) — this dialog never touches the DB,
files or DICOMDIR directly. The delete runs on a worker thread so a large
package never freezes the UI.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

logger = logging.getLogger(__name__)


class _DeleteWorker(QThread):
    done = Signal(object)   # result dict
    failed = Signal(str)

    def __init__(self, server, patient_ids, actor, parent=None):
        super().__init__(parent)
        self._server = server
        self._patient_ids = list(patient_ids)
        self._actor = actor

    def run(self):
        try:
            from PacsClient.utils.offline_cloud import remove_patients_from_offline_cloud
            res = remove_patients_from_offline_cloud(
                self._server, self._patient_ids, actor=self._actor)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[OFFLINE-MANAGE] delete worker crashed")
            self.failed.emit(str(exc))
            return
        self.done.emit(res)


class OfflineCloudManagerDialog(QDialog):
    """Manage patients inside an Offline Cloud package."""

    _COLS = ["Patient ID", "Patient Name", "Studies", "Images", "Modalities", "Latest Date"]

    def __init__(self, parent=None, servers=None, actor=None):
        super().__init__(parent)
        self._servers = [s for s in (servers or []) if isinstance(s, dict) and s.get("folder_path")]
        self._actor = actor
        self._worker = None
        self._patients = []   # current list rows

        self.setWindowTitle("Manage Offline Service Patients")
        self.setModal(True)
        self.resize(920, 600)
        self._build_ui()
        if self._servers:
            self._reload()
        else:
            self._status.setText(
                "No Offline Cloud Server folder is configured. Add one in "
                "Settings ▸ Offline Cloud Server first.")
            self._delete_btn.setEnabled(False)

    # -- UI ----------------------------------------------------------------

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        root.addWidget(QLabel("<b>Edit or Delete Existing Offline Patients</b>"))

        top = QHBoxLayout()
        top.addWidget(QLabel("Package:"))
        self._server_combo = QComboBox()
        for s in self._servers:
            self._server_combo.addItem(f"{s.get('name','?')}  ({s.get('folder_path','')})", s)
        self._server_combo.currentIndexChanged.connect(lambda _i: self._reload())
        top.addWidget(self._server_combo, 1)
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self._reload)
        top.addWidget(self._refresh_btn)
        root.addLayout(top)

        self._table = QTableWidget(0, len(self._COLS))
        self._table.setHorizontalHeaderLabels(self._COLS)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.itemSelectionChanged.connect(self._update_delete_enabled)
        root.addWidget(self._table, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        buttons = QHBoxLayout()
        self._delete_btn = QPushButton("Delete Selected Patient(s)")
        self._delete_btn.setStyleSheet("QPushButton{background:#c0392b;color:white;padding:7px 14px;"
                                       "border-radius:5px;font-weight:bold;} QPushButton:disabled{background:#7f5551;}")
        self._delete_btn.clicked.connect(self._on_delete)
        self._delete_btn.setEnabled(False)
        buttons.addWidget(self._delete_btn)
        buttons.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.reject)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    # -- data --------------------------------------------------------------

    def _current_server(self):
        if not self._servers:
            return None
        idx = self._server_combo.currentIndex()
        return self._server_combo.itemData(idx) if idx >= 0 else self._servers[0]

    def _reload(self):
        server = self._current_server()
        if not server:
            return
        try:
            from PacsClient.utils.offline_cloud import list_offline_cloud_patients
            self._patients = list_offline_cloud_patients(server)
        except Exception:
            logger.exception("[OFFLINE-MANAGE] list failed")
            self._patients = []

        self._table.setRowCount(0)
        for row in self._patients:
            r = self._table.rowCount()
            self._table.insertRow(r)
            vals = [
                row.get("patient_id", ""),
                row.get("patient_name", ""),
                str(row.get("study_count", 0)),
                str(row.get("image_count", 0)),
                ", ".join(row.get("modalities", []) or []),
                row.get("latest_study_date", ""),
            ]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.get("patient_id"))
                self._table.setItem(r, c, item)

        n = len(self._patients)
        self._status.setText(f"{n} patient(s) in this package." if n else
                             "This package contains no patients.")
        self._update_delete_enabled()

    def _selected_patient_ids(self):
        ids = []
        for idx in self._table.selectionModel().selectedRows():
            item = self._table.item(idx.row(), 0)
            pid = item.data(Qt.ItemDataRole.UserRole) if item else None
            pid = str(pid or (item.text() if item else "")).strip()
            if pid and pid not in ids:
                ids.append(pid)
        return ids

    def _update_delete_enabled(self):
        busy = self._worker is not None and self._worker.isRunning()
        self._delete_btn.setEnabled(bool(self._selected_patient_ids()) and not busy)

    # -- delete ------------------------------------------------------------

    def _on_delete(self):
        server = self._current_server()
        patient_ids = self._selected_patient_ids()
        if not server or not patient_ids:
            return
        total_studies = sum(
            int(r.get("study_count", 0)) for r in self._patients
            if r.get("patient_id") in patient_ids)
        confirm = QMessageBox.warning(
            self, "Delete from Offline Service",
            f"Permanently remove {len(patient_ids)} patient(s) "
            f"({total_studies} stud{'y' if total_studies == 1 else 'ies'}) from this "
            f"offline package?\n\nTheir DICOM files, folders and database records will be "
            f"removed and the DICOMDIR rebuilt. A recoverable backup is kept in the "
            f"package's .trash folder.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        self._set_busy(True)
        self._status.setText("Deleting… do not close the application.")
        self._worker = _DeleteWorker(server, patient_ids, self._actor, self)
        self._worker.done.connect(self._on_delete_done)
        self._worker.failed.connect(self._on_delete_failed)
        self._worker.start()

    def _on_delete_failed(self, message):
        self._set_busy(False)
        QMessageBox.critical(self, "Delete failed", message)
        self._reload()

    def _on_delete_done(self, result):
        self._set_busy(False)
        if not isinstance(result, dict) or not result.get("ok"):
            errs = "; ".join((result or {}).get("errors", []) or ["Unknown error."])
            rolled = " The package was rolled back to its previous state." if (result or {}).get("rolled_back") else ""
            QMessageBox.critical(self, "Delete did not complete", errs + rolled)
            self._reload()
            return
        removed_p = len(result.get("removed_patient_ids", []))
        removed_s = result.get("removed", 0)
        validation = result.get("validation") or {}
        ok = validation.get("is_complete", True)
        QMessageBox.information(
            self, "Deleted",
            f"Removed {removed_p} patient(s) and {removed_s} stud"
            f"{'y' if removed_s == 1 else 'ies'} from the package.\n"
            f"Package validation: {'complete' if ok else 'needs attention'}.\n"
            f"A backup was kept at:\n{result.get('trash_dir','')}",
        )
        self._reload()

    def _set_busy(self, busy):
        self._refresh_btn.setEnabled(not busy)
        self._server_combo.setEnabled(not busy)
        self._table.setEnabled(not busy)
        self._delete_btn.setEnabled(not busy and bool(self._selected_patient_ids()))

    def closeEvent(self, event):
        w = self._worker
        if w is not None and w.isRunning():
            QMessageBox.information(
                self, "Please wait",
                "A delete is still in progress; this window will close when it finishes.")
            event.ignore()
            return
        super().closeEvent(event)
