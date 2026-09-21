"""Native template builder and version-bound case forms; no filesystem or API I/O."""
from __future__ import annotations

import copy
import uuid

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget, QHeaderView,
)

from .definitions import FIELD_TYPES, blank_template, form_fields, lumbar_template, validate_template, validate_values


class EditableDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dirty = False
        self.busy = False
        self.setWindowModality(Qt.WindowModal)

    def changed(self, *args):
        self.dirty = True

    def set_busy(self, busy):
        self.busy = busy
        self.setEnabled(not busy)

    def reject(self):
        if self.busy:
            return
        if self.dirty and QMessageBox.question(
                self, "Unsaved changes", "Discard the changes that have not been saved?",
                QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Cancel) != QMessageBox.Discard:
            return
        super().reject()


class TemplateDialog(EditableDialog):
    save_requested = Signal(dict)

    def __init__(self, definition=None, presets=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Dataset Template" if definition else "New Dataset")
        self.resize(1040, 720)
        layout = QVBoxLayout(self)
        self.bases = QComboBox()
        self.bases.addItem("Lumbar spine template", lumbar_template())
        self.bases.addItem("Blank template", blank_template())
        for row in presets:
            self.bases.addItem("Copy: " + row["template"]["name"], row["template"])
        if definition is None:
            layout.addWidget(QLabel("Start from a template, then add or remove the fields you need."))
            layout.addWidget(self.bases)
        else:
            self.bases.hide()
            message = QLabel("Changes apply to new cases. Existing cases keep their original template and answers.")
            message.setWordWrap(True)
            layout.addWidget(message)
        form = QFormLayout()
        self.name = QLineEdit()
        self.modality = QComboBox()
        for title, code in (("MRI", "MR"), ("CT", "CT"), ("Mammography", "MG"),
                            ("Radiography", "DX"), ("Computed Radiography", "CR"), ("Ultrasound", "US")):
            self.modality.addItem(title, code)
        self.anatomy = QLineEdit()
        self.regions = QLineEdit()
        self.regions.setPlaceholderText("L1-L2; L2-L3; L3-L4; L4-L5; L5-S1 (optional for case-only forms)")
        form.addRow("Dataset name", self.name)
        form.addRow("Modality", self.modality)
        form.addRow("Anatomical area", self.anatomy)
        form.addRow("Regions / levels", self.regions)
        layout.addLayout(form)
        self.fields = QTableWidget(0, 6)
        self.fields.setHorizontalHeaderLabels(["Field label", "Type", "Applies to", "Completion", "Choices (semicolon separated)", ""])
        self.fields.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.fields.setAlternatingRowColors(False)
        self.fields.verticalHeader().hide()
        self.fields.verticalHeader().setDefaultSectionSize(38)
        self.fields.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.fields.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        for col, width in ((1, 110), (2, 130), (3, 110), (5, 80)):
            self.fields.setColumnWidth(col, width)
        layout.addWidget(QLabel("Double-click a field label or its choices to edit them."))
        layout.addWidget(self.fields, 1)
        self.add_button = QPushButton("Add Field")
        self.add_button.clicked.connect(self.add_field)
        layout.addWidget(self.add_button, alignment=Qt.AlignLeft)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.bases.currentIndexChanged.connect(self._base_changed)
        for widget in (self.name, self.anatomy, self.regions):
            widget.textChanged.connect(self.changed)
        self.modality.currentIndexChanged.connect(self.changed)
        self.fields.itemChanged.connect(self.changed)
        self.load_template(definition["template"] if definition else lumbar_template())
        if definition and definition.get("case_count", 0):
            self.modality.setEnabled(False)
            self.anatomy.setReadOnly(True)

    def _base_changed(self):
        self.load_template(self.bases.currentData())
        self.dirty = True

    def load_template(self, template):
        self.name.setText(template["name"])
        index = self.modality.findData(template["modality"])
        if index < 0:
            self.modality.addItem(template["modality"], template["modality"])
            index = self.modality.count() - 1
        self.modality.setCurrentIndex(index)
        self.anatomy.setText(template["anatomy"])
        self.regions.setText("; ".join(template["regions"]))
        self.fields.setRowCount(0)
        for field in template["fields"]:
            self.add_field(field)
        self.dirty = False

    def add_field(self, field=None):
        if not isinstance(field, dict):
            field = {"id": "field_" + uuid.uuid4().hex, "label": "New field", "type": "text",
                     "scope": "case", "required": False, "options": []}
        row = self.fields.rowCount()
        self.fields.insertRow(row)
        label = QTableWidgetItem(field["label"])
        label.setData(Qt.UserRole, field["id"])
        self.fields.setItem(row, 0, label)
        kind = QComboBox()
        kind.addItems(FIELD_TYPES)
        kind.setCurrentText(field["type"])
        scope = QComboBox()
        scope.addItem("Once per case", "case")
        scope.addItem("Each region", "region")
        scope.setCurrentIndex(scope.findData(field["scope"]))
        required = QComboBox()
        required.addItem("Optional", False)
        required.addItem("Required", True)
        required.setCurrentIndex(1 if field["required"] else 0)
        self.fields.setCellWidget(row, 1, kind)
        self.fields.setCellWidget(row, 2, scope)
        self.fields.setCellWidget(row, 3, required)
        options = QTableWidgetItem("; ".join(field["options"]))
        self.fields.setItem(row, 4, options)
        remove = QPushButton("Remove")
        self.fields.setCellWidget(row, 5, remove)
        remove.clicked.connect(lambda checked=False, key=field["id"]: self.remove_field(key))
        kind.currentIndexChanged.connect(self.changed)
        scope.currentIndexChanged.connect(self.changed)
        required.currentIndexChanged.connect(self.changed)
        self.changed()

    def remove_field(self, key):
        for row in range(self.fields.rowCount()):
            if self.fields.item(row, 0).data(Qt.UserRole) == key:
                self.fields.removeRow(row)
                self.changed()
                break

    def template(self):
        fields = []
        for row in range(self.fields.rowCount()):
            fields.append({"id": self.fields.item(row, 0).data(Qt.UserRole),
                           "label": self.fields.item(row, 0).text(),
                           "type": self.fields.cellWidget(row, 1).currentText(),
                           "scope": self.fields.cellWidget(row, 2).currentData(),
                           "required": self.fields.cellWidget(row, 3).currentData(),
                           "options": [x.strip() for x in self.fields.item(row, 4).text().split(";") if x.strip()]})
        return validate_template({"name": self.name.text(), "modality": self.modality.currentData(),
                                  "anatomy": self.anatomy.text(),
                                  "regions": [x.strip() for x in self.regions.text().split(";") if x.strip()],
                                  "fields": fields})

    def submit(self):
        try:
            template = self.template()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        self.save_requested.emit(template)


class CaseDialog(EditableDialog):
    save_requested = Signal(dict, str, str)

    def __init__(self, document, parent=None):
        super().__init__(parent)
        # The clinician can consult Imaging Tools/Reception while this case stays identity-bound.
        self.setWindowModality(Qt.NonModal)
        self.document = copy.deepcopy(document)
        self.setWindowTitle("Dataset Case")
        self.resize(820, 740)
        layout = QVBoxLayout(self)
        heading = QLabel(f"{document['template']['name']} | Template {document['template_version']}\n"
                         f"{document['patient_id']} | {document['patient_name']} | {document['study_date']}")
        heading.setTextFormat(Qt.PlainText)
        heading.setWordWrap(True)
        layout.addWidget(heading)
        author_row = QFormLayout()
        self.author = QLineEdit(document["reviewer"])
        author_row.addRow("Form author", self.author)
        layout.addLayout(author_row)
        self.tabs = QTabWidget()
        self.inputs = {}
        template = document["template"]
        for region in ["case", *template["regions"]]:
            matching = [(key, field) for key, field in form_fields(template) if key.split("/")[0] == region]
            if not matching:
                continue
            container = QWidget()
            form = QFormLayout(container)
            form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
            for key, field in matching:
                value = document["values"].get(key)
                if field["type"] == "choice":
                    widget = QComboBox()
                    widget.addItem("Not entered", None)
                    for choice in field["options"]:
                        widget.addItem(choice, choice)
                    widget.setCurrentIndex(max(0, widget.findData(value)))
                    widget.currentIndexChanged.connect(self.changed)
                elif field["type"] == "multiline":
                    widget = QPlainTextEdit()
                    widget.setPlainText(value or "")
                    widget.setMaximumHeight(160)
                    widget.textChanged.connect(self.changed)
                else:
                    widget = QLineEdit("" if value is None else str(value))
                    if field["type"] == "number":
                        widget.setPlaceholderText("Number; leave empty if unknown")
                    widget.textChanged.connect(self.changed)
                widget.setObjectName("datasetField_" + key)
                widget.setAccessibleName(field["label"] + " - " + region)
                label = QLabel(field["label"] + (" *" if field["required"] else ""))
                label.setTextFormat(Qt.PlainText)
                form.addRow(label, widget)
                self.inputs[key] = (widget, field)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(container)
            self.tabs.addTab(scroll, "Case" if region == "case" else region)
        layout.addWidget(self.tabs, 1)
        self.notice = QLabel("An empty field means unknown. Form completion does not mark image evidence as reviewed.")
        self.notice.setWordWrap(True)
        layout.addWidget(self.notice)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setTextFormat(Qt.PlainText)
        layout.addWidget(self.error)
        actions = QHBoxLayout()
        self.draft_button = QPushButton("Save Draft")
        self.complete_button = QPushButton("Save Completed Form")
        close = QPushButton("Close")
        actions.addWidget(self.draft_button)
        actions.addWidget(self.complete_button)
        actions.addStretch()
        actions.addWidget(close)
        layout.addLayout(actions)
        self.draft_button.clicked.connect(lambda: self.submit("draft"))
        self.complete_button.clicked.connect(lambda: self.submit("complete"))
        close.clicked.connect(self.reject)
        self.author.textChanged.connect(self.changed)
        self.dirty = False

    def values(self):
        result = {}
        for key, (widget, field) in self.inputs.items():
            if isinstance(widget, QComboBox):
                value = widget.currentData()
            elif isinstance(widget, QPlainTextEdit):
                value = widget.toPlainText()
            else:
                value = widget.text()
                if field["type"] == "number" and value.strip():
                    try:
                        value = float(value)
                    except ValueError:
                        raise ValueError(f"Enter a number for {field['label']}.") from None
            if value not in (None, ""):
                result[key] = value
        return result

    def submit(self, status):
        try:
            values = validate_values(self.document["template"], self.values(), status == "complete")
            if status == "complete" and not self.author.text().strip():
                raise ValueError("Enter the form author's name before marking it complete.")
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.error.clear()
        self.save_requested.emit(values, status, self.author.text())

    def saved(self, document):
        self.document = copy.deepcopy(document)
        self.dirty = False
        self.error.setText("Saved as " + document["status"] + ".")
