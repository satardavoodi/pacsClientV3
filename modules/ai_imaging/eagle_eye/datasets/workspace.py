"""Dataset catalog, per-study enrollment and editable case lists inside Eagle Eye."""
from __future__ import annotations

from functools import partial
import uuid

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from .dialogs import CaseDialog, TemplateDialog
from .repository import DatasetError, DatasetRepository, load_study_context


class _Bus(QObject):
    done = Signal(str, object, str)


_bus = None


def _dispatcher():
    global _bus
    if _bus is None:
        _bus = _Bus(QApplication.instance())
    return _bus


class _Work(QRunnable):
    def __init__(self, bus, token, work):
        super().__init__()
        self.bus, self.token, self.work = bus, token, work

    def run(self):
        result, error = None, ""
        try:
            result = self.work()
        except DatasetError as exc:
            error = str(exc)
        except Exception:
            # Filesystem and database exceptions can contain sensitive paths/records.
            error = "The operation could not finish. Check local storage and try again."
        try:
            self.bus.done.emit(self.token, result, error)
        except RuntimeError:
            pass  # Application shutdown; the worker owns no widgets.


def _enroll(repository, dataset_id, uid, loader):
    return repository.add_case(dataset_id, loader(uid))


class DatasetWorkspace(QWidget):
    def __init__(self, study_uid=None, repository=None, context_loader=None, parent=None):
        super().__init__(parent)
        self.study_uid = study_uid
        self.repository = repository or DatasetRepository()
        self.context_loader = context_loader or load_study_context
        self.datasets = []
        self.cases = []
        self.selected_id = None
        self.pending = {}
        self.dialog = None
        self._refresh_pending = False
        self.bus = _dispatcher()
        self.bus.done.connect(self._done, Qt.QueuedConnection)
        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.new_button = QPushButton("New Dataset")
        self.edit_button = QPushButton("Edit Template")
        self.add_button = QPushButton("Add Current Study")
        self.refresh_button = QPushButton("Refresh Lists")
        for button in (self.new_button, self.edit_button, self.add_button, self.refresh_button):
            toolbar.addWidget(button)
        toolbar.addStretch()
        layout.addLayout(toolbar)
        self.status = QLabel("Choose a dataset, or create one from the lumbar template.")
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        split = QSplitter()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Modality / Anatomy / Dataset", "Cases"])
        self.tree.setMinimumWidth(270)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        split.addWidget(self.tree)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        self.title = QLabel("Saved cases")
        self.title.setTextFormat(Qt.PlainText)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a case by patient code, name or study date")
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Patient code", "Patient name", "Study date", "Form status", "Filled", "Template", "Saved"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(1, 170)
        self.open_button = QPushButton("Open Selected Case")
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.search)
        right_layout.addWidget(self.table, 1)
        right_layout.addWidget(self.open_button, alignment=Qt.AlignLeft)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)
        hint = QLabel("Each new case uses the dataset's current template. Existing cases keep their saved template version.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.new_button.clicked.connect(self.new_dataset)
        self.edit_button.clicked.connect(self.edit_template)
        self.add_button.clicked.connect(self.add_current_study)
        self.refresh_button.clicked.connect(self.refresh)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.search.textChanged.connect(self.filter_cases)
        self.table.itemSelectionChanged.connect(self._controls)
        self.table.cellDoubleClicked.connect(self.open_case)
        self.open_button.clicked.connect(self.open_case)
        self._controls()

    def _controls(self):
        busy = bool(self.pending)
        editing = self.dialog is not None
        self.new_button.setEnabled(not busy and not editing)
        self.edit_button.setEnabled(not busy and not editing and bool(self.selected_id))
        self.add_button.setEnabled(not busy and not editing and bool(self.selected_id and self.study_uid))
        self.open_button.setEnabled(not busy and not editing and self.table.currentRow() >= 0)
        self.refresh_button.setEnabled(not busy and not editing)
        self.tree.setEnabled(not busy and not editing)
        self.table.setEnabled(not busy and not editing)

    def _submit(self, work, callback):
        if self.pending:
            return
        token = uuid.uuid4().hex
        self.pending[token] = callback
        if self.dialog:
            self.dialog.set_busy(True)
        self.status.setText("Working...")
        self._controls()
        QThreadPool.globalInstance().start(_Work(self.bus, token, work))

    @Slot(str, object, str)
    def _done(self, token, result, error):
        callback = self.pending.pop(token, None)
        if callback is None:
            return  # Another workspace's job; closed widgets disconnect automatically.
        if self.dialog:
            self.dialog.set_busy(False)
        if error:
            self.status.setText(error)
            if self.dialog:
                self.dialog.error.setText(error)
        else:
            self.status.setText("Ready")
            callback(result)
        self._controls()
        if self._refresh_pending and not self.pending and self.dialog is None:
            self._refresh_pending = False
            self.refresh()

    def refresh(self):
        if self.pending or self.dialog:
            self._refresh_pending = True
            return
        self._refresh_pending = False
        self._submit(self.repository.list_datasets, self._show_datasets)

    def _show_datasets(self, datasets):
        self.datasets = datasets
        selected = self.selected_id
        self.tree.blockSignals(True)
        self.tree.clear()
        parents = {}
        chosen = None
        for dataset in datasets:
            template = dataset["template"]
            modality = template["modality"]
            if modality not in parents:
                parents[modality] = QTreeWidgetItem(self.tree, ["MRI" if modality == "MR" else modality])
            key = (modality, template["anatomy"])
            if key not in parents:
                parents[key] = QTreeWidgetItem(parents[modality], [template["anatomy"]])
            item = QTreeWidgetItem(parents[key], [template["name"], str(dataset["case_count"])])
            item.setData(0, Qt.UserRole, dataset["id"])
            if chosen is None or dataset["id"] == selected:
                chosen = item
        self.tree.expandAll()
        if chosen:
            self.tree.setCurrentItem(chosen)
        self.tree.blockSignals(False)
        self._selection_changed(chosen)

    def _selection_changed(self, item, previous=None):
        self.selected_id = item.data(0, Qt.UserRole) if item else None
        self.cases = []
        self.table.setRowCount(0)
        self._controls()
        if self.selected_id:
            self._submit(partial(self.repository.list_cases, self.selected_id), self._show_cases)
        else:
            self.title.setText("Choose a dataset to view its cases")

    def _show_cases(self, rows):
        self.cases = rows
        definition = next((r for r in self.datasets if r["id"] == self.selected_id), None)
        name = definition["template"]["name"] if definition else "Dataset"
        self.title.setText(f"{name} | {len(rows)} saved cases")
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [row["patient_id"], row["patient_name"], row["study_date"], row["status"],
                      f"{row['filled']}/{row['total']}", str(row["template_version"]), row["saved_utc"]]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row["id"])
                self.table.setItem(index, col, item)
        self.filter_cases()

    def filter_cases(self):
        text = self.search.text().strip().casefold()
        for index, row in enumerate(self.cases):
            self.table.setRowHidden(index, text not in " ".join(str(v) for v in row.values()).casefold())

    def _show_dialog(self, dialog):
        self.dialog = dialog
        dialog.finished.connect(self._dialog_closed)
        dialog.show()
        self._controls()

    def _dialog_closed(self):
        if self.dialog:
            self.dialog.deleteLater()
        self.dialog = None
        self._controls()
        self.refresh()

    def new_dataset(self):
        dialog = TemplateDialog(presets=self.datasets, parent=self)
        dialog.save_requested.connect(self._create_dataset)
        self._show_dialog(dialog)

    def _create_dataset(self, template):
        self._submit(partial(self.repository.create_dataset, template), self._template_saved)

    def edit_template(self):
        definition = next((r for r in self.datasets if r["id"] == self.selected_id), None)
        if definition is None:
            return
        dialog = TemplateDialog(definition=definition, parent=self)
        dialog.save_requested.connect(partial(self._update_dataset, definition["id"], definition["version"]))
        self._show_dialog(dialog)

    def _update_dataset(self, dataset_id, version, template):
        self._submit(partial(self.repository.update_dataset, dataset_id, template, version), self._template_saved)

    def _template_saved(self, definition):
        self.selected_id = definition["id"]
        self.dialog.dirty = False
        self.dialog.accept()

    def add_current_study(self):
        if self.selected_id and self.study_uid:
            self._submit(partial(_enroll, self.repository, self.selected_id, self.study_uid, self.context_loader),
                         self._open_document)

    def open_case(self, *args):
        row = self.table.currentRow()
        if row < 0 or self.table.isRowHidden(row):
            return
        self._submit(partial(self.repository.get_case, self.table.item(row, 0).data(Qt.UserRole)), self._open_document)

    def _open_document(self, document):
        dialog = CaseDialog(document, parent=self)
        dialog.save_requested.connect(self._save_case)
        self._show_dialog(dialog)

    def _save_case(self, values, status, reviewer):
        document = self.dialog.document
        self._submit(partial(self.repository.save_case, document["id"], values, status, reviewer,
                             document["revision"]), self._case_saved)

    def _case_saved(self, document):
        self.dialog.saved(document)
        self._refresh_pending = True
