from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QInputDialog,
)

from PacsClient.pacs.education.case_of_day_database import (
    CaseOfDayEntry,
    add_body_part,
    copy_dicom_folder_to_case_storage,
    get_all_cases,
    insert_case,
    list_body_parts,
    search_cases,
)
from PacsClient.utils.config import EDUCATION_STORAGE_PATH


_COTD_PREFS_PATH = EDUCATION_STORAGE_PATH / "case_of_day_prefs.json"


def _load_prefs() -> Dict[str, Any]:
    try:
        if _COTD_PREFS_PATH.exists():
            data = json.loads(_COTD_PREFS_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def _save_prefs(data: Dict[str, Any]) -> None:
    try:
        _COTD_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _COTD_PREFS_PATH.write_text(json.dumps(data, ensure_ascii=True, indent=2), encoding="utf-8")
    except Exception:
        pass


class CaseOfDayEntryDialog(QDialog):
    saved = Signal(dict)  # emitted with inserted case payload

    def __init__(self, parent=None, prefill: Dict[str, Any] = None):
        super().__init__(parent)
        self.prefill = dict(prefill or {})
        self.setWindowTitle("Case of the Day")
        self.setMinimumWidth(720)
        # Two modes:
        # - source_folder: will be copied into Case-of-Day storage on Save.
        # - dicom_folder_path: already copied into Case-of-Day storage (Save writes DB only).
        self._dicom_source_folder: Optional[str] = self.prefill.get("source_folder")
        self._dicom_already_stored_folder: Optional[str] = self.prefill.get("dicom_folder_path")
        self._cleanup_on_cancel: bool = bool(self.prefill.get("cleanup_on_cancel"))
        self._copied_folder: Optional[str] = None
        self._saved_ok: bool = False
        self._build_ui()

    def reject(self) -> None:
        # If the patient-export flow pre-copied data into Case-of-Day storage and the user cancels,
        # delete the orphaned folder. Only do this when explicitly requested via prefill flag.
        try:
            if (not self._saved_ok) and self._cleanup_on_cancel and self._dicom_already_stored_folder:
                from pathlib import Path
                import shutil

                p = Path(self._dicom_already_stored_folder)
                if p.exists() and p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass
        super().reject()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        title = QLabel("Create Case of the Day")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f0f4f8;")
        root.addWidget(title)

        form_container = QFrame()
        form_container.setStyleSheet("QFrame { background-color: #111722; border: 1px solid #1f2a37; }")
        form_layout = QFormLayout(form_container)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setSpacing(10)

        field_style = """
            QLineEdit, QTextEdit, QComboBox {
                background-color: #0d1117;
                color: #e2e8f0;
                border: 1px solid #2a3442;
                border-radius: 2px;
                padding: 8px 10px;
                font-size: 10pt;
            }
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border: 1px solid #4d8aaf; }
        """

        prefs = _load_prefs()
        self.saved_by = QLineEdit()
        self.saved_by.setStyleSheet(field_style)
        self.saved_by.setPlaceholderText("e.g., Dr. Vahid")
        self.saved_by.setText(str(self.prefill.get("saved_by") or prefs.get("last_saved_by") or ""))
        form_layout.addRow("Saved By *", self.saved_by)

        self.modality = QComboBox()
        self.modality.setStyleSheet(field_style)
        self.modality.addItem("Select...", "")
        for item in ["CT", "MRI", "US", "X-Ray", "PET", "SPECT", "Mammography", "Fluoroscopy", "Other"]:
            self.modality.addItem(item, item)
        pre_mod = str(self.prefill.get("modality") or "")
        idx = self.modality.findData(pre_mod) if pre_mod else -1
        if idx >= 0:
            self.modality.setCurrentIndex(idx)
        form_layout.addRow("Modality *", self.modality)

        body_part_row = QWidget()
        body_part_layout = QHBoxLayout(body_part_row)
        body_part_layout.setContentsMargins(0, 0, 0, 0)
        body_part_layout.setSpacing(8)

        self.body_part = QComboBox()
        self.body_part.setStyleSheet(field_style)
        self.body_part.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._reload_body_parts()
        pre_body = str(self.prefill.get("body_part") or "")
        if pre_body:
            idx = self.body_part.findText(pre_body)
            if idx >= 0:
                self.body_part.setCurrentIndex(idx)
        body_part_layout.addWidget(self.body_part, 1)

        add_part = QPushButton("Add Body Part")
        add_part.setFixedWidth(140)
        add_part.setStyleSheet("""
            QPushButton {
                background-color: #1f4a67;
                color: #f0f4f8;
                border: 1px solid #2f6c90;
                border-radius: 2px;
                padding: 8px 10px;
                font-size: 9.5pt;
                font-weight: 600;
            }
            QPushButton:hover { background-color: #2d5f82; }
        """)
        add_part.clicked.connect(self._add_body_part)
        body_part_layout.addWidget(add_part)
        form_layout.addRow("Body Part *", body_part_row)

        self.anatomical_class = QLineEdit()
        self.anatomical_class.setStyleSheet(field_style)
        self.anatomical_class.setPlaceholderText("e.g., Neuro, MSK, Abdomen, Cardiac")
        self.anatomical_class.setText(str(self.prefill.get("anatomical_classification") or ""))
        form_layout.addRow("Anatomical Classification", self.anatomical_class)

        self.diagnosis = QLineEdit()
        self.diagnosis.setStyleSheet(field_style)
        self.diagnosis.setPlaceholderText("e.g., Acute appendicitis")
        self.diagnosis.setText(str(self.prefill.get("diagnosis") or ""))
        form_layout.addRow("Diagnosis *", self.diagnosis)

        self.protocol = QLineEdit()
        self.protocol.setStyleSheet(field_style)
        self.protocol.setPlaceholderText("e.g., With contrast, special sequence ...")
        self.protocol.setText(str(self.prefill.get("protocol_details") or ""))
        form_layout.addRow("Protocol Details", self.protocol)

        self.description = QTextEdit()
        self.description.setStyleSheet(field_style)
        self.description.setFixedHeight(90)
        self.description.setPlaceholderText("Case description...")
        self.description.setPlainText(str(self.prefill.get("description") or ""))
        form_layout.addRow("Description", self.description)

        self.ddx = QTextEdit()
        self.ddx.setStyleSheet(field_style)
        self.ddx.setFixedHeight(90)
        self.ddx.setPlaceholderText("Differential diagnosis...")
        self.ddx.setPlainText(str(self.prefill.get("differential_diagnosis") or ""))
        form_layout.addRow("Differential Diagnosis", self.ddx)

        folder_row = QWidget()
        folder_layout = QHBoxLayout(folder_row)
        folder_layout.setContentsMargins(0, 0, 0, 0)
        folder_layout.setSpacing(8)

        self.folder_label = QLineEdit()
        self.folder_label.setStyleSheet(field_style)
        self.folder_label.setReadOnly(True)
        self.folder_label.setPlaceholderText("No folder selected")
        if self._dicom_already_stored_folder:
            self.folder_label.setText(self._dicom_already_stored_folder)
        elif self._dicom_source_folder:
            self.folder_label.setText(self._dicom_source_folder)
        folder_layout.addWidget(self.folder_label, 1)

        pick_btn = QPushButton("Pick DICOM Folder")
        pick_btn.setFixedWidth(160)
        pick_btn.setStyleSheet(add_part.styleSheet())
        pick_btn.clicked.connect(self._pick_folder)
        folder_layout.addWidget(pick_btn)
        form_layout.addRow("DICOM Folder *", folder_row)

        root.addWidget(form_container)

        actions = QHBoxLayout()
        actions.addStretch()
        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(40)
        cancel.setFixedWidth(120)
        cancel.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #a8b2c0;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                font-size: 10pt;
            }
            QPushButton:hover { color: #d8e2ee; border-color: #4d7aa0; }
        """)
        cancel.clicked.connect(self.reject)
        actions.addWidget(cancel)

        save = QPushButton("Save Case")
        save.setFixedHeight(40)
        save.setFixedWidth(140)
        save.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 10pt;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        save.clicked.connect(self._save)
        actions.addWidget(save)
        root.addLayout(actions)

    def _reload_body_parts(self):
        self.body_part.clear()
        self.body_part.addItem("Select...", "")
        for value in list_body_parts():
            self.body_part.addItem(value, value)

    def _add_body_part(self):
        name, ok = QInputDialog.getText(self, "New Body Part", "Body part name:")
        if not ok or not name:
            return
        try:
            add_body_part(str(name).strip())
        except Exception as exc:
            QMessageBox.warning(self, "Add Failed", str(exc))
            return
        self._reload_body_parts()
        idx = self.body_part.findText(str(name).strip())
        if idx >= 0:
            self.body_part.setCurrentIndex(idx)

    def _pick_folder(self):
        selected = QFileDialog.getExistingDirectory(self, "Select DICOM Folder", "")
        if not selected:
            return
        self._dicom_source_folder = selected
        self._dicom_already_stored_folder = None
        self.folder_label.setText(selected)

    def _save(self):
        saved_by = self.saved_by.text().strip()
        modality = str(self.modality.currentData() or "").strip()
        body_part = str(self.body_part.currentData() or "").strip()
        diagnosis = self.diagnosis.text().strip()
        if not saved_by or not modality or not body_part or not diagnosis:
            QMessageBox.warning(self, "Missing Fields", "Saved By, Modality, Body Part, and Diagnosis are required.")
            return
        if not self._dicom_already_stored_folder and not self._dicom_source_folder:
            QMessageBox.warning(self, "Missing Folder", "Select a DICOM folder to import/export.")
            return

        copied_folder: str
        if self._dicom_already_stored_folder:
            copied_folder = str(self._dicom_already_stored_folder)
        else:
            try:
                copied_folder = copy_dicom_folder_to_case_storage(self._dicom_source_folder, case_hint=diagnosis)
                self._copied_folder = copied_folder
            except Exception as exc:
                QMessageBox.critical(self, "Copy Failed", f"Could not copy DICOM folder:\n{exc}")
                return

        try:
            case_pk = insert_case(
                saved_by=saved_by,
                modality=modality,
                body_part=body_part,
                diagnosis=diagnosis,
                anatomical_classification=self.anatomical_class.text().strip(),
                protocol_details=self.protocol.text().strip(),
                description=self.description.toPlainText().strip(),
                differential_diagnosis=self.ddx.toPlainText().strip(),
                dicom_folder_path=copied_folder,
                original_source_path=str(self.prefill.get("original_source_path") or self._dicom_source_folder or ""),
                source_type=str(self.prefill.get("source_type") or "manual"),
                patient_id=str(self.prefill.get("patient_id") or ""),
                study_uid=str(self.prefill.get("study_uid") or ""),
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", f"Could not save case metadata:\n{exc}")
            return

        prefs = _load_prefs()
        prefs["last_saved_by"] = saved_by
        _save_prefs(prefs)

        self._saved_ok = True
        self.saved.emit({"case_pk": case_pk, "dicom_folder_path": copied_folder})
        self.accept()


class CaseOfDayCard(QFrame):
    clicked = Signal(dict)

    def __init__(self, entry: CaseOfDayEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        self.setObjectName("CaseOfDayCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(320, 180)
        self.setStyleSheet("""
            QFrame#CaseOfDayCard {
                background-color: #111722;
                border: 1px solid #1f2a37;
                border-radius: 2px;
            }
            QFrame#CaseOfDayCard:hover {
                border-color: #2f6c90;
                background-color: #141c28;
            }
            QLabel { color: #d7dfeb; }
        """)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        top = QHBoxLayout()
        mod = QLabel(self.entry.modality)
        mod.setStyleSheet("color: #eef5fc; font-size: 10pt; font-weight: 700; padding: 2px 8px; background-color: #1f3f66;")
        top.addWidget(mod)
        top.addStretch()
        body = QLabel(self.entry.body_part)
        body.setStyleSheet("color: #cbd5e0; font-size: 9.5pt; padding: 2px 8px; background-color: #24384e;")
        top.addWidget(body)
        layout.addLayout(top)

        diag = QLabel(self.entry.diagnosis)
        diag.setStyleSheet("color: #f0f4f8; font-size: 11pt; font-weight: 700;")
        diag.setWordWrap(True)
        layout.addWidget(diag)

        saved_by = QLabel(f"Saved by: {self.entry.saved_by}")
        saved_by.setStyleSheet("color: #9bb0c6; font-size: 9.5pt;")
        layout.addWidget(saved_by)

        extra = QLabel(self.entry.anatomical_classification or "")
        extra.setStyleSheet("color: #95a7bb; font-size: 9pt;")
        extra.setWordWrap(True)
        layout.addWidget(extra)

        layout.addStretch(1)

    def mousePressEvent(self, event):
        self.clicked.emit({"case_pk": self.entry.case_pk})
        super().mousePressEvent(event)


class CaseOfDayPage(QWidget):
    case_opened = Signal(dict)  # payload includes case_pk
    case_created = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._selected_case: Optional[CaseOfDayEntry] = None
        self._current_modality: str = ""
        self._current_body_part: str = ""
        self._search_text: str = ""
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QFrame()
        left.setFixedWidth(380)
        left.setStyleSheet("QFrame { background-color: #0f1419; border-right: 1px solid #1e2530; }")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        title = QLabel("Case of the Day")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet("color: #f0f4f8;")
        left_layout.addWidget(title)

        create_btn = QPushButton("Import DICOM Folder")
        create_btn.setFixedHeight(42)
        create_btn.setStyleSheet("""
            QPushButton {
                background-color: #2d5a7b;
                color: #f0f4f8;
                border: 1px solid #3d7a9f;
                border-radius: 2px;
                font-size: 11pt;
                font-weight: 700;
            }
            QPushButton:hover { background-color: #3d7a9f; }
        """)
        create_btn.clicked.connect(self._create_case)
        left_layout.addWidget(create_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search cases...")
        self.search.setFixedHeight(42)
        self.search.setStyleSheet("""
            QLineEdit {
                background-color: #0d1117;
                color: #f0f4f8;
                border: 1px solid #3d5a80;
                border-radius: 2px;
                padding: 0 14px;
                font-size: 12pt;
            }
        """)
        self.search.textChanged.connect(self._on_search)
        left_layout.addWidget(self.search)

        self.modality_filter = QComboBox()
        self.modality_filter.setFixedHeight(40)
        self.modality_filter.setStyleSheet("QComboBox { background-color: #0d1117; color: #e2e8f0; border: 1px solid #2a3442; padding: 6px 10px; }")
        self.modality_filter.addItem("All Modalities", "")
        for item in ["CT", "MRI", "US", "X-Ray", "PET", "SPECT", "Mammography", "Fluoroscopy", "Other"]:
            self.modality_filter.addItem(item, item)
        self.modality_filter.currentIndexChanged.connect(self._on_filters)
        left_layout.addWidget(self.modality_filter)

        self.body_part_filter = QComboBox()
        self.body_part_filter.setFixedHeight(40)
        self.body_part_filter.setStyleSheet(self.modality_filter.styleSheet())
        self.body_part_filter.addItem("All Body Parts", "")
        self.body_part_filter.currentIndexChanged.connect(self._on_filters)
        left_layout.addWidget(self.body_part_filter)

        left_layout.addStretch(1)
        root.addWidget(left)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(16, 12, 16, 12)
        center_layout.setSpacing(8)

        self.results = QLabel("0 cases")
        self.results.setStyleSheet("color: #a8b2c0; font-size: 12pt;")
        center_layout.addWidget(self.results)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        self.grid_container = QWidget()
        self.grid = QGridLayout(self.grid_container)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.scroll.setWidget(self.grid_container)
        center_layout.addWidget(self.scroll, 1)

        root.addWidget(center, 1)

    def refresh(self):
        # refresh body part filter options
        current = self.body_part_filter.currentData()
        self.body_part_filter.blockSignals(True)
        self.body_part_filter.clear()
        self.body_part_filter.addItem("All Body Parts", "")
        for part in list_body_parts():
            self.body_part_filter.addItem(part, part)
        if current:
            idx = self.body_part_filter.findData(current)
            if idx >= 0:
                self.body_part_filter.setCurrentIndex(idx)
        self.body_part_filter.blockSignals(False)

        cases = search_cases(
            query=self._search_text,
            modality=str(self.modality_filter.currentData() or "") or None,
            body_part=str(self.body_part_filter.currentData() or "") or None,
        )
        self._render_cases(cases)

    def _render_cases(self, cases: List[CaseOfDayEntry]):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.results.setText(f"{len(cases)} case{'s' if len(cases) != 1 else ''}")
        if not cases:
            empty = QLabel("No cases yet")
            empty.setAlignment(Qt.AlignCenter)
            empty.setStyleSheet("color: #718096; font-size: 12pt;")
            self.grid.addWidget(empty, 0, 0)
            return

        cols = 3
        for idx, entry in enumerate(cases):
            card = CaseOfDayCard(entry)
            card.clicked.connect(self._open_case)
            self.grid.addWidget(card, idx // cols, idx % cols)

    def _on_search(self, text: str):
        self._search_text = str(text or "")
        self.refresh()

    def _on_filters(self, _):
        self.refresh()

    def _create_case(self):
        dlg = CaseOfDayEntryDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.case_created.emit()
            self.refresh()

    def _open_case(self, payload: Dict[str, Any]):
        self.case_opened.emit(payload)
