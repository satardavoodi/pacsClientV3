from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QInputDialog,
)

from modules.education.case_of_day_database import (
    CaseOfDayEntry,
    add_body_part,
    case_of_day_events,
    copy_dicom_folder_to_case_storage,
    extract_dicom_metadata,
    get_all_cases,
    insert_case,
    list_body_parts,
    load_reception_payload_for_patient,
    search_cases,
    write_case_package_metadata,
)
from PacsClient.utils.config import EDUCATION_STORAGE_PATH
from PacsClient.utils.theme_manager import get_theme_manager


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
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
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

        # Auto-fill from DICOM tags when a folder is already known (patient
        # toolbar export path, or pre-picked folder). The caller's explicit
        # prefill values WIN — we only fill blanks. This is best-effort: if
        # pydicom isn't available or no readable file is found, we silently
        # fall back to whatever the caller passed.
        try:
            self._auto_extract_dicom_metadata()
        except Exception:
            pass

        self._build_ui()

    def _auto_extract_dicom_metadata(self):
        """Read DICOM tags from the prefilled folder and merge them into
        ``self.prefill`` for any field the caller didn't already supply.

        Extracted: modality, body_part, patient_id, patient_name,
        study_uid, study_description, study_date.
        """
        folder_candidate = (
            self.prefill.get("dicom_folder_path")
            or self.prefill.get("source_folder")
            or self.prefill.get("original_source_path")
            or ""
        )
        if not folder_candidate:
            return
        extracted = extract_dicom_metadata(str(folder_candidate)) or {}
        for key, value in extracted.items():
            if not self.prefill.get(key):
                self.prefill[key] = value

    def _on_theme_changed(self, theme: Dict[str, Any]):
        self._theme = theme or self.theme_manager.current_theme()
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

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _clear_layout(self, layout):
        """Recursively clear a Qt layout. Safe to call on rebuild (theme switch)."""
        while layout.count():
            item = layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                self._clear_layout(sub)

    def _field_style(self):
        t = self._theme
        return f"""
            QLineEdit, QTextEdit, QComboBox {{
                background-color: {t['panel_deep_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                padding: 9px 11px;
                font-size: 10.5pt;
                selection-background-color: {t['accent']};
            }}
            QLineEdit:focus, QTextEdit:focus, QComboBox:focus {{
                border: 1px solid {t['accent']};
            }}
            QLineEdit:read-only {{
                color: {t['text_secondary']};
            }}
            QComboBox::drop-down {{
                border: none; width: 26px;
            }}
        """

    def _label_widget(self, text: str, required: bool = False) -> QLabel:
        """Plain bold label with an optional red asterisk for required fields."""
        t = self._theme
        suffix = (
            f"  <span style='color:{t.get('danger', '#e15858')};'>*</span>"
            if required else ""
        )
        label = QLabel(f"<span style='color:{t['text_primary']}; font-weight:600;'>{text}</span>{suffix}")
        # IMPORTANT: force a flat label — strip any inherited border/pill styling.
        label.setStyleSheet(
            "QLabel { background: transparent; border: none; padding: 0; font-size: 10.5pt; }"
        )
        label.setTextFormat(Qt.RichText)
        return label

    def _section_header(self, text: str) -> QWidget:
        """Section header with a subtle accent rule beneath."""
        t = self._theme
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 6)
        layout.setSpacing(6)
        title = QLabel(text.upper())
        title.setStyleSheet(
            f"QLabel {{ color: {t['text_secondary']}; "
            f"background: transparent; border: none; "
            f"font-size: 9pt; font-weight: 700; letter-spacing: 1.5px; }}"
        )
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {t['border']}; border: none;")
        layout.addWidget(title)
        layout.addWidget(rule)
        return container

    def _add_field_row(self, body_layout, label_text: str, widget: QWidget, required: bool = False):
        """Add a (label, field) row stacked vertically into body_layout."""
        body_layout.addWidget(self._label_widget(label_text, required=required))
        body_layout.addWidget(widget)

    def _patient_ref_card(self, *, patient_id: str, patient_name: str,
                          study_description: str, study_date: str,
                          study_uid: str) -> QFrame:
        """Read-only summary card showing whatever DICOM patient/study context
        we auto-extracted. Only non-empty fields are rendered. Save logic
        already carries these values forward to the DB without needing inputs."""
        t = self._theme
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background-color: {t['panel_bg']}; "
            f"border: 1px solid {t['border']}; border-radius: 6px; }}"
            f"QLabel {{ background: transparent; border: none; }}"
        )
        outer = QVBoxLayout(card)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(6)

        def _row(label_text: str, value_text: str):
            if not value_text:
                return
            row = QHBoxLayout()
            row.setSpacing(8)
            row.setContentsMargins(0, 0, 0, 0)
            key = QLabel(label_text)
            key.setFixedWidth(140)
            key.setStyleSheet(
                f"color: {t.get('text_muted', t['text_secondary'])}; "
                f"font-size: 10pt; font-weight: 600;"
            )
            val = QLabel(value_text)
            val.setStyleSheet(f"color: {t['text_primary']}; font-size: 10.5pt;")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(key)
            row.addWidget(val, 1)
            outer.addLayout(row)

        # Format study date as YYYY-MM-DD if it looks like DICOM YYYYMMDD.
        formatted_date = study_date
        if len(study_date) == 8 and study_date.isdigit():
            formatted_date = f"{study_date[0:4]}-{study_date[4:6]}-{study_date[6:8]}"

        _row("Patient Name:", patient_name)
        _row("Patient ID:", patient_id)
        _row("Study Date:", formatted_date)
        _row("Study Description:", study_description)
        if study_uid:
            # Show only the trailing portion of the UID — full UID is too noisy
            # to display by default. Tooltip keeps the full value.
            trimmed = study_uid if len(study_uid) <= 36 else "…" + study_uid[-36:]
            row = QHBoxLayout()
            row.setSpacing(8)
            key = QLabel("Study UID:")
            key.setFixedWidth(140)
            key.setStyleSheet(
                f"color: {t.get('text_muted', t['text_secondary'])}; "
                f"font-size: 10pt; font-weight: 600;"
            )
            val = QLabel(trimmed)
            val.setStyleSheet(f"color: {t['text_secondary']}; font-size: 9.5pt;")
            val.setToolTip(study_uid)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            row.addWidget(key)
            row.addWidget(val, 1)
            outer.addLayout(row)

        return card

    # ------------------------------------------------------------------
    # UI build
    # ------------------------------------------------------------------
    def _build_ui(self):
        t = self._theme
        self.setMinimumWidth(820)
        self.setMinimumHeight(740)
        self.setStyleSheet(f"QDialog {{ background-color: {t['panel_deep_bg']}; }}")

        existing_layout = self.layout()
        if existing_layout is None:
            root = QVBoxLayout(self)
        else:
            self._clear_layout(existing_layout)
            root = existing_layout
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---------- Header bar ----------
        header = QFrame()
        header.setStyleSheet(
            f"QFrame {{ background-color: {t['panel_bg']}; "
            f"border: none; border-bottom: 1px solid {t['border']}; }}"
        )
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(28, 20, 28, 18)
        header_layout.setSpacing(4)

        title = QLabel("Create Case of the Day")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet(
            f"color: {t['text_primary']}; background: transparent; border: none;"
        )
        header_layout.addWidget(title)

        subtitle = QLabel("Record a teaching case from DICOM imagery and clinical notes.")
        subtitle.setStyleSheet(
            f"color: {t.get('text_muted', t['text_secondary'])}; "
            f"font-size: 10.5pt; background: transparent; border: none;"
        )
        header_layout.addWidget(subtitle)
        root.addWidget(header)

        # ---------- Scrollable body ----------
        body_scroll = QScrollArea()
        body_scroll.setWidgetResizable(True)
        body_scroll.setFrameShape(QFrame.NoFrame)
        body_scroll.setStyleSheet(
            f"QScrollArea {{ background-color: {t['panel_deep_bg']}; border: none; }}"
        )
        body_container = QWidget()
        body_container.setStyleSheet(
            f"QWidget {{ background-color: {t['panel_deep_bg']}; }}"
        )
        body_layout = QVBoxLayout(body_container)
        body_layout.setContentsMargins(28, 20, 28, 20)
        body_layout.setSpacing(14)

        field_style = self._field_style()
        prefs = _load_prefs()

        # ---------- Section: Patient Reference (auto-filled from DICOM) ----------
        # Only render this section when we have at least one piece of patient
        # context — typically present when invoked from the patient toolbar.
        patient_id_val = str(self.prefill.get("patient_id") or "").strip()
        patient_name_val = str(self.prefill.get("patient_name") or "").strip()
        study_desc_val = str(self.prefill.get("study_description") or "").strip()
        study_date_val = str(self.prefill.get("study_date") or "").strip()
        study_uid_val = str(self.prefill.get("study_uid") or "").strip()
        if any([patient_id_val, patient_name_val, study_desc_val, study_date_val, study_uid_val]):
            body_layout.addWidget(self._section_header("Patient Reference (auto-filled from DICOM)"))
            ref_card = self._patient_ref_card(
                patient_id=patient_id_val,
                patient_name=patient_name_val,
                study_description=study_desc_val,
                study_date=study_date_val,
                study_uid=study_uid_val,
            )
            body_layout.addWidget(ref_card)
            # Hold the values for the save call — they don't need editable fields.
            self._prefill_patient_id = patient_id_val
            self._prefill_patient_name = patient_name_val
            self._prefill_study_uid = study_uid_val
            self._prefill_study_description = study_desc_val
            self._prefill_study_date = study_date_val
            body_layout.addSpacing(4)
        else:
            self._prefill_patient_id = ""
            self._prefill_patient_name = ""
            self._prefill_study_uid = ""
            self._prefill_study_description = ""
            self._prefill_study_date = ""

        # ---------- Section: Identity ----------
        # All optional — Saved By and Modality. Diagnosis is the only required
        # field in the whole dialog and lives further down.
        body_layout.addWidget(self._section_header("Identity"))

        identity_grid = QGridLayout()
        identity_grid.setHorizontalSpacing(18)
        identity_grid.setVerticalSpacing(6)
        identity_grid.setContentsMargins(0, 0, 0, 0)

        self.saved_by = QLineEdit()
        self.saved_by.setStyleSheet(field_style)
        self.saved_by.setPlaceholderText("e.g., Dr. Vahid (optional)")
        self.saved_by.setText(str(self.prefill.get("saved_by") or prefs.get("last_saved_by") or ""))

        self.modality = QComboBox()
        self.modality.setStyleSheet(field_style)
        self.modality.addItem("Unspecified", "")
        for item in ["CT", "MRI", "US", "X-Ray", "PET", "SPECT", "Mammography", "Fluoroscopy", "Other"]:
            self.modality.addItem(item, item)
        pre_mod = str(self.prefill.get("modality") or "")
        if pre_mod:
            idx = self.modality.findData(pre_mod)
            if idx < 0:
                # Modality value came from DICOM but isn't in our curated list — add it.
                self.modality.addItem(pre_mod, pre_mod)
                idx = self.modality.count() - 1
            self.modality.setCurrentIndex(idx)

        identity_grid.addWidget(self._label_widget("Saved By"), 0, 0)
        identity_grid.addWidget(self._label_widget("Modality"), 0, 1)
        identity_grid.addWidget(self.saved_by, 1, 0)
        identity_grid.addWidget(self.modality, 1, 1)
        identity_grid.setColumnStretch(0, 1)
        identity_grid.setColumnStretch(1, 1)
        body_layout.addLayout(identity_grid)

        body_layout.addSpacing(4)

        # ---------- Section: Anatomy ----------
        body_layout.addWidget(self._section_header("Anatomy"))

        anatomy_row = QHBoxLayout()
        anatomy_row.setSpacing(8)
        anatomy_row.setContentsMargins(0, 0, 0, 0)

        # Body Part is editable: users can pick from the curated list OR type
        # a new value. Anything new gets added to the lookup on save (see
        # insert_case in case_of_day_database.py).
        self.body_part = QComboBox()
        self.body_part.setEditable(True)
        self.body_part.setInsertPolicy(QComboBox.NoInsert)
        self.body_part.setStyleSheet(field_style)
        self.body_part.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.body_part.lineEdit().setPlaceholderText("Type to add or pick from list (optional)")
        self._reload_body_parts()
        pre_body = str(self.prefill.get("body_part") or "")
        if pre_body:
            idx = self.body_part.findText(pre_body)
            if idx >= 0:
                self.body_part.setCurrentIndex(idx)
            else:
                # DICOM tag returned a value we don't have catalogued yet — just
                # populate the edit field; it'll be added on save.
                self.body_part.setEditText(pre_body)
        else:
            self.body_part.setCurrentIndex(0)  # "Select..." placeholder row
        anatomy_row.addWidget(self.body_part, 1)

        add_part = QPushButton("+ Add Body Part")
        add_part.setFixedHeight(38)
        add_part.setFixedWidth(150)
        add_part.setCursor(Qt.PointingHandCursor)
        secondary_btn_style = f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_secondary']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                padding: 6px 12px;
                font-size: 10pt;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {t['text_primary']};
                border-color: {t['accent_hover']};
                background-color: rgba(61, 122, 159, 0.10);
            }}
        """
        add_part.setStyleSheet(secondary_btn_style)
        add_part.clicked.connect(self._add_body_part)
        anatomy_row.addWidget(add_part)

        body_layout.addWidget(self._label_widget("Body Part", required=True))
        body_layout.addLayout(anatomy_row)

        self.anatomical_class = QLineEdit()
        self.anatomical_class.setStyleSheet(field_style)
        self.anatomical_class.setPlaceholderText("e.g., Neuro, MSK, Abdomen, Cardiac")
        self.anatomical_class.setText(str(self.prefill.get("anatomical_classification") or ""))
        self._add_field_row(body_layout, "Anatomical Classification", self.anatomical_class)

        body_layout.addSpacing(4)

        # ---------- Section: Clinical Findings ----------
        body_layout.addWidget(self._section_header("Clinical Findings"))

        self.diagnosis = QLineEdit()
        self.diagnosis.setStyleSheet(field_style)
        self.diagnosis.setPlaceholderText("e.g., Acute appendicitis")
        self.diagnosis.setText(str(self.prefill.get("diagnosis") or ""))
        self._add_field_row(body_layout, "Diagnosis", self.diagnosis, required=True)

        self.protocol = QLineEdit()
        self.protocol.setStyleSheet(field_style)
        self.protocol.setPlaceholderText("e.g., With contrast, special sequence ...")
        self.protocol.setText(str(self.prefill.get("protocol_details") or ""))
        self._add_field_row(body_layout, "Protocol Details", self.protocol)

        body_layout.addSpacing(4)

        # ---------- Section: Notes ----------
        body_layout.addWidget(self._section_header("Notes"))

        self.description = QTextEdit()
        self.description.setStyleSheet(field_style)
        self.description.setFixedHeight(96)
        self.description.setPlaceholderText("Case description and key teaching points...")
        self.description.setPlainText(str(self.prefill.get("description") or ""))
        self._add_field_row(body_layout, "Description", self.description)

        self.ddx = QTextEdit()
        self.ddx.setStyleSheet(field_style)
        self.ddx.setFixedHeight(96)
        self.ddx.setPlaceholderText("Differential diagnosis (one entry per line is fine)...")
        self.ddx.setPlainText(str(self.prefill.get("differential_diagnosis") or ""))
        self._add_field_row(body_layout, "Differential Diagnosis", self.ddx)

        body_layout.addSpacing(4)

        # ---------- Section: Source DICOM ----------
        body_layout.addWidget(self._section_header("Source DICOM"))

        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.setSpacing(8)

        self.folder_label = QLineEdit()
        self.folder_label.setStyleSheet(field_style)
        self.folder_label.setReadOnly(True)
        self.folder_label.setPlaceholderText("No folder selected")
        initial_path = (
            self._dicom_already_stored_folder
            or self._dicom_source_folder
            or ""
        )
        if initial_path:
            self.folder_label.setText(initial_path)
            self.folder_label.setToolTip(initial_path)
            # Show the tail of the path (the case folder name) by default.
            self.folder_label.setCursorPosition(len(initial_path))
        folder_row.addWidget(self.folder_label, 1)

        pick_btn = QPushButton("Pick DICOM Folder")
        pick_btn.setFixedHeight(38)
        pick_btn.setFixedWidth(170)
        pick_btn.setCursor(Qt.PointingHandCursor)
        pick_btn.setStyleSheet(secondary_btn_style)
        pick_btn.clicked.connect(self._pick_folder)
        folder_row.addWidget(pick_btn)

        body_layout.addWidget(self._label_widget("DICOM Folder"))
        body_layout.addLayout(folder_row)

        hint = QLabel(
            "Optional. If selected, the folder is copied into Case-of-Day storage on save "
            "and Modality / Body Part / Patient details will be auto-filled from the DICOM tags. "
            "Leave empty to save a notes-only case."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"QLabel {{ color: {t.get('text_muted', t['text_secondary'])}; "
            f"font-size: 9.5pt; background: transparent; border: none; padding-top: 4px; }}"
        )
        body_layout.addWidget(hint)

        body_layout.addStretch(1)
        body_scroll.setWidget(body_container)
        root.addWidget(body_scroll, 1)

        # ---------- Footer ----------
        footer = QFrame()
        footer.setStyleSheet(
            f"QFrame {{ background-color: {t['panel_bg']}; "
            f"border: none; border-top: 1px solid {t['border']}; }}"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(28, 14, 28, 14)
        footer_layout.setSpacing(10)

        required_hint = QLabel(
            f"<span style='color:{t.get('danger', '#e15858')};'>*</span> "
            f"<span style='color:{t.get('text_muted', t['text_secondary'])};'>Only Diagnosis is required. "
            f"Everything else is optional.</span>"
        )
        required_hint.setTextFormat(Qt.RichText)
        required_hint.setStyleSheet(
            "QLabel { background: transparent; border: none; font-size: 10pt; }"
        )
        footer_layout.addWidget(required_hint)
        footer_layout.addStretch(1)

        cancel = QPushButton("Cancel")
        cancel.setFixedHeight(40)
        cancel.setFixedWidth(120)
        cancel.setCursor(Qt.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_secondary']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                font-size: 10.5pt;
            }}
            QPushButton:hover {{
                color: {t['text_primary']};
                border-color: {t['accent_hover']};
            }}
        """)
        cancel.clicked.connect(self.reject)
        footer_layout.addWidget(cancel)

        save = QPushButton("Save Case")
        save.setFixedHeight(40)
        save.setFixedWidth(160)
        save.setCursor(Qt.PointingHandCursor)
        save.setDefault(True)
        save.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: {t['button_text']};
                border: 1px solid {t['accent']};
                border-radius: 4px;
                font-size: 10.5pt;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        """)
        save.clicked.connect(self._save)
        footer_layout.addWidget(save)

        root.addWidget(footer)

    def _reload_body_parts(self):
        # Remember whatever the user has currently typed/picked so it survives
        # the rebuild — this matters when _add_body_part triggers a reload.
        current_text = ""
        try:
            current_text = self.body_part.currentText().strip()
        except Exception:
            current_text = ""

        self.body_part.clear()
        self.body_part.addItem("Select...", "")
        for value in list_body_parts():
            self.body_part.addItem(value, value)

        if current_text and current_text.lower() not in {"select...", "select", ""}:
            idx = self.body_part.findText(current_text)
            if idx >= 0:
                self.body_part.setCurrentIndex(idx)
            else:
                self.body_part.setEditText(current_text)

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
        self.folder_label.setToolTip(selected)
        # Show the trailing folder name (the meaningful part for the user).
        self.folder_label.setCursorPosition(len(selected))

        # If the user picked a folder manually, see if we can fish out more
        # DICOM metadata (Modality, BodyPartExamined, PatientName/ID, etc.)
        # and pre-populate any currently-empty input. This makes the manual
        # "Import DICOM Folder" path nearly as effortless as the patient-export
        # path.
        try:
            extracted = extract_dicom_metadata(selected) or {}
        except Exception:
            extracted = {}

        if extracted:
            # Modality
            mod = extracted.get("modality") or ""
            if mod and not (self.modality.currentData() or "").strip():
                idx = self.modality.findData(mod)
                if idx < 0:
                    self.modality.addItem(mod, mod)
                    idx = self.modality.count() - 1
                self.modality.setCurrentIndex(idx)
            # Body part
            bp = extracted.get("body_part") or ""
            if bp and not self.body_part.currentText().strip():
                idx = self.body_part.findText(bp)
                if idx >= 0:
                    self.body_part.setCurrentIndex(idx)
                else:
                    self.body_part.setEditText(bp)
            # Latch patient/study refs even if the dialog didn't render the
            # Patient Reference card (because they were unknown at open).
            for key in ("patient_id", "patient_name", "study_uid",
                        "study_description", "study_date"):
                value = (extracted.get(key) or "").strip()
                if value:
                    attr = f"_prefill_{key}"
                    if not getattr(self, attr, ""):
                        setattr(self, attr, value)
                    # Also stuff into prefill so a future reopen sees it.
                    self.prefill.setdefault(key, value)

    def _save(self):
        diagnosis = self.diagnosis.text().strip()
        if not diagnosis:
            QMessageBox.warning(
                self,
                "Diagnosis Required",
                "Please enter at least a diagnosis. All other fields are optional.",
            )
            self.diagnosis.setFocus()
            return

        saved_by = self.saved_by.text().strip()
        modality = str(self.modality.currentData() or "").strip()
        # currentText() works for editable combo boxes (manual entry); fall
        # back to currentData() for safety when nothing was typed.
        body_part = str(self.body_part.currentText() or self.body_part.currentData() or "").strip()
        # Strip out the "Select..." placeholder if the user never picked anything.
        if body_part.lower() in {"select...", "select"}:
            body_part = ""

        # DICOM folder is now optional. If we have one (either already-copied
        # from the patient-export flow or picked manually), use it; otherwise
        # the case is saved as a notes-only entry, which is still useful for
        # teaching boards and search.
        copied_folder: str = ""
        if self._dicom_already_stored_folder:
            copied_folder = str(self._dicom_already_stored_folder)
        elif self._dicom_source_folder:
            try:
                copied_folder = copy_dicom_folder_to_case_storage(
                    self._dicom_source_folder, case_hint=diagnosis
                )
                self._copied_folder = copied_folder
            except Exception as exc:
                QMessageBox.critical(
                    self, "Copy Failed", f"Could not copy DICOM folder:\n{exc}"
                )
                return

        patient_id_val = getattr(self, "_prefill_patient_id", "") or str(self.prefill.get("patient_id") or "")
        patient_name_val = getattr(self, "_prefill_patient_name", "") or str(self.prefill.get("patient_name") or "")
        study_uid_val = getattr(self, "_prefill_study_uid", "") or str(self.prefill.get("study_uid") or "")
        study_desc_val = getattr(self, "_prefill_study_description", "") or str(self.prefill.get("study_description") or "")
        study_date_val = getattr(self, "_prefill_study_date", "") or str(self.prefill.get("study_date") or "")

        try:
            case_pk = insert_case(
                diagnosis=diagnosis,
                saved_by=saved_by,
                modality=modality,
                body_part=body_part,
                anatomical_classification=self.anatomical_class.text().strip(),
                protocol_details=self.protocol.text().strip(),
                description=self.description.toPlainText().strip(),
                differential_diagnosis=self.ddx.toPlainText().strip(),
                dicom_folder_path=copied_folder,
                original_source_path=str(self.prefill.get("original_source_path") or self._dicom_source_folder or ""),
                source_type=str(self.prefill.get("source_type") or "manual"),
                patient_id=patient_id_val,
                patient_name=patient_name_val,
                study_uid=study_uid_val,
                study_description=study_desc_val,
                study_date=study_date_val,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Save Failed", f"Could not save case metadata:\n{exc}")
            return

        # Persist the rich case-package sidecars next to the DICOM folder. The
        # DB row remains the source of truth — sidecar writes are best-effort
        # and do not interrupt the save flow if they fail.
        try:
            metadata_blob: Dict[str, Any] = {
                "diagnosis": diagnosis,
                "saved_by": saved_by,
                "modality": modality,
                "body_part": body_part,
                "anatomical_classification": self.anatomical_class.text().strip(),
                "protocol_details": self.protocol.text().strip(),
                "description": self.description.toPlainText().strip(),
                "differential_diagnosis": self.ddx.toPlainText().strip(),
                "patient_id": patient_id_val,
                "patient_name": patient_name_val,
                "study_uid": study_uid_val,
                "study_description": study_desc_val,
                "study_date": study_date_val,
                "source_type": str(self.prefill.get("source_type") or "manual"),
                "original_source_path": str(
                    self.prefill.get("original_source_path") or self._dicom_source_folder or ""
                ),
            }
            reception_payload = None
            # Reception payload pre-supplied by the caller wins; otherwise look
            # up cached reception data for this patient.
            cached = self.prefill.get("reception_payload")
            if isinstance(cached, dict) and cached:
                reception_payload = cached
            elif patient_id_val:
                reception_payload = load_reception_payload_for_patient(patient_id_val)

            write_case_package_metadata(
                dicom_folder_path=copied_folder,
                case_pk=case_pk,
                metadata=metadata_blob,
                reception_payload=reception_payload,
            )
        except Exception as exc:
            # Don't abort the save — just log to stdout for diagnostics.
            print(f"[CaseOfDay] sidecar write failed: {exc}")

        # Only remember "Saved By" preference if the user actually typed one.
        if saved_by:
            prefs = _load_prefs()
            prefs["last_saved_by"] = saved_by
            _save_prefs(prefs)

        self._saved_ok = True
        payload = {"case_pk": case_pk, "dicom_folder_path": copied_folder}
        self.saved.emit(payload)

        # Broadcast a global event so the Education tab, the patient list
        # Status column, and the viewer toolbar badge can all refresh —
        # regardless of which surface triggered the save.
        try:
            hub = case_of_day_events()
            if hub is not None:
                hub.saved.emit({
                    "study_uid": study_uid_val,
                    "patient_id": patient_id_val,
                    "case_pk": case_pk,
                })
        except Exception:
            pass

        self.accept()


# Color-coded modality pill colors. Mirrors PACS conventions so users can
# scan the grid and find the modality they want at a glance.
_MODALITY_COLORS: Dict[str, str] = {
    "CT": "#3b82f6",          # blue
    "MR": "#8b5cf6",          # violet
    "MRI": "#8b5cf6",         # violet
    "US": "#10b981",          # green
    "X-RAY": "#f59e0b",       # amber
    "XR": "#f59e0b",          # amber
    "CR": "#f59e0b",          # amber
    "DX": "#f59e0b",          # amber
    "PET": "#ec4899",         # pink
    "SPECT": "#06b6d4",       # cyan
    "MAMMOGRAPHY": "#a855f7", # purple
    "MG": "#a855f7",          # purple
    "FLUOROSCOPY": "#eab308", # yellow
    "NM": "#14b8a6",          # teal
    "PT": "#ec4899",          # pink
    "XA": "#f97316",          # orange
}


def _modality_color(modality: str) -> str:
    """Return a stable accent color for a given modality string, falling
    back to a neutral PACS-blue when the modality is unknown."""
    key = str(modality or "").strip().upper()
    return _MODALITY_COLORS.get(key, "#3b82f6")


def _format_relative_time(timestamp_str: str) -> str:
    """Render an ISO/SQL timestamp as a friendly relative string
    (e.g. "5 minutes ago", "yesterday", "May 14"). Returns "" on failure."""
    if not timestamp_str:
        return ""
    try:
        from datetime import datetime, timezone
        # SQLite CURRENT_TIMESTAMP returns 'YYYY-MM-DD HH:MM:SS' in UTC.
        text = str(timestamp_str).strip().replace("T", " ")
        if "." in text:
            text = text.split(".")[0]
        if text.endswith("Z"):
            text = text[:-1]
        try:
            ts = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            ts = datetime.strptime(text, "%Y-%m-%d")
        now = datetime.utcnow()
        delta = now - ts
        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            mins = seconds // 60
            return f"{mins} minute{'s' if mins != 1 else ''} ago"
        if seconds < 86400:
            hrs = seconds // 3600
            return f"{hrs} hour{'s' if hrs != 1 else ''} ago"
        if seconds < 172800:
            return "yesterday"
        if seconds < 7 * 86400:
            days = seconds // 86400
            return f"{days} days ago"
        # Older: show abbreviated date
        return ts.strftime("%b %d")
    except Exception:
        return ""


class CaseOfDayCard(QFrame):
    """Card for one Case of the Day entry.

    Layout (top → bottom):

    * **Hero / cover region** (110 px tall) — color-tinted background based
      on modality, with a giant modality letter as a placeholder. Modality
      and body-part pills float over the hero on opposite corners.
    * **Body** — diagnosis (largest, bold), patient name·ID, study date /
      saved-by metadata, anatomical classification.
    * **Footer** — relative timestamp ("2 hours ago") on the left, an
      "Open ▸" affordance on the right that becomes a hover-driven button.

    The whole card is clickable (existing behavior preserved) — the footer
    button is decorative and bubbles up the same click signal.
    """

    clicked = Signal(dict)

    def __init__(self, entry: CaseOfDayEntry, parent=None):
        super().__init__(parent)
        self.entry = entry
        t = get_theme_manager().current_theme()
        self.setObjectName("CaseOfDayCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(320, 290)
        self._mod_color = _modality_color(self.entry.modality)
        self.setStyleSheet(f"""
            QFrame#CaseOfDayCard {{
                background-color: {t['panel_bg']};
                border: 1px solid {t['border']};
                border-radius: 8px;
            }}
            QFrame#CaseOfDayCard:hover {{
                border-color: {self._mod_color};
                background-color: {t['panel_alt_bg']};
            }}
            QLabel {{ color: {t['text_secondary']}; background: transparent; border: none; }}
        """)
        self._build()

    def _build(self):
        t = get_theme_manager().current_theme()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---------------- Hero region (modality-tinted) ----------------
        hero = QFrame()
        hero.setFixedHeight(110)
        # Tinted band: 22% opacity of the modality color over the card bg.
        hero.setStyleSheet(
            f"QFrame {{ background-color: {self._mod_color}38; "
            f"border-top-left-radius: 8px; border-top-right-radius: 8px; }}"
        )
        hero_layout = QGridLayout(hero)
        hero_layout.setContentsMargins(12, 10, 12, 10)
        hero_layout.setSpacing(0)

        # Big modality glyph in the centre — acts as a visual stand-in for
        # the (future) DICOM thumbnail. Single letter keeps it tidy.
        modality_text = (self.entry.modality or "").strip().upper() or "—"
        glyph = QLabel(modality_text[:3])
        glyph_font = QFont()
        glyph_font.setPointSize(28)
        glyph_font.setWeight(QFont.DemiBold)
        glyph.setFont(glyph_font)
        glyph.setAlignment(Qt.AlignCenter)
        glyph.setStyleSheet(
            f"QLabel {{ color: {self._mod_color}; background: transparent; "
            f"border: none; letter-spacing: 2px; }}"
        )
        hero_layout.addWidget(glyph, 0, 0, 1, 2, alignment=Qt.AlignCenter)

        # Modality pill (top-left)
        if (self.entry.modality or "").strip():
            mod_pill = QLabel(self.entry.modality)
            mod_pill.setStyleSheet(
                f"QLabel {{ color: white; background-color: {self._mod_color}; "
                f"font-size: 9pt; font-weight: 700; "
                f"padding: 2px 9px; border-radius: 10px; }}"
            )
            hero_layout.addWidget(mod_pill, 0, 0, alignment=Qt.AlignTop | Qt.AlignLeft)

        # Body-part pill (top-right)
        body_part = (self.entry.body_part or "").strip()
        if body_part:
            body_pill = QLabel(body_part)
            body_pill.setStyleSheet(
                f"QLabel {{ color: {t['text_primary']}; background-color: {t['panel_deep_bg']}; "
                f"font-size: 9pt; font-weight: 600; "
                f"padding: 2px 9px; border-radius: 10px; "
                f"border: 1px solid {t['border']}; }}"
            )
            hero_layout.addWidget(body_pill, 0, 1, alignment=Qt.AlignTop | Qt.AlignRight)

        outer.addWidget(hero)

        # ---------------- Body content ----------------
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(14, 12, 14, 10)
        body_layout.setSpacing(6)

        # Diagnosis headline
        diagnosis_text = (self.entry.diagnosis or "").strip() or "(no diagnosis)"
        diag = QLabel(diagnosis_text)
        diag_font = QFont()
        diag_font.setPointSize(11)
        diag_font.setWeight(QFont.DemiBold)
        diag.setFont(diag_font)
        diag.setStyleSheet(f"QLabel {{ color: {t['text_primary']}; }}")
        diag.setWordWrap(True)
        diag.setMaximumHeight(46)  # ~2 lines, then elide visually via wrap
        body_layout.addWidget(diag)

        # Patient reference (name · ID)
        patient_ref = ""
        if (self.entry.patient_name or "").strip():
            display_name = self.entry.patient_name.replace("^", " ").strip()
            patient_ref = display_name
            if (self.entry.patient_id or "").strip():
                patient_ref += f"  ·  {self.entry.patient_id.strip()}"
        elif (self.entry.patient_id or "").strip():
            patient_ref = self.entry.patient_id.strip()
        if patient_ref:
            patient_label = QLabel(patient_ref)
            patient_label.setStyleSheet(
                f"QLabel {{ color: {t['text_secondary']}; font-size: 9.5pt; }}"
            )
            patient_label.setWordWrap(False)
            body_layout.addWidget(patient_label)

        # Study date + saved-by stacked into one muted line
        meta_bits = []
        study_date = (self.entry.study_date or "").strip()
        if study_date:
            if len(study_date) == 8 and study_date.isdigit():
                study_date = f"{study_date[0:4]}-{study_date[4:6]}-{study_date[6:8]}"
            meta_bits.append(f"Study {study_date}")
        if (self.entry.saved_by or "").strip():
            meta_bits.append(f"by {self.entry.saved_by.strip()}")
        if meta_bits:
            meta = QLabel("  ·  ".join(meta_bits))
            meta.setStyleSheet(
                f"QLabel {{ color: {t.get('text_muted', t['text_secondary'])}; font-size: 9pt; }}"
            )
            body_layout.addWidget(meta)

        # Anatomical classification (italic, secondary)
        extra_text = (self.entry.anatomical_classification or "").strip()
        if extra_text:
            extra = QLabel(extra_text)
            extra.setStyleSheet(
                f"QLabel {{ color: {t.get('text_muted', t['text_secondary'])}; "
                f"font-size: 9pt; font-style: italic; }}"
            )
            extra.setWordWrap(True)
            body_layout.addWidget(extra)

        body_layout.addStretch(1)
        outer.addWidget(body, 1)

        # ---------------- Footer (relative time + Open hint) ----------------
        footer = QFrame()
        footer.setStyleSheet(
            f"QFrame {{ background-color: transparent; "
            f"border-top: 1px solid {t['border']}; }}"
        )
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(14, 8, 14, 8)

        rel_time = _format_relative_time(self.entry.updated_at or self.entry.created_at)
        if rel_time:
            time_label = QLabel(rel_time)
            time_label.setStyleSheet(
                f"QLabel {{ color: {t.get('text_muted', t['text_secondary'])}; "
                f"font-size: 9pt; }}"
            )
            footer_layout.addWidget(time_label)

        footer_layout.addStretch(1)

        open_hint = QLabel("Open ›")
        open_hint.setStyleSheet(
            f"QLabel {{ color: {self._mod_color}; font-size: 9.5pt; font-weight: 700; }}"
        )
        footer_layout.addWidget(open_hint)

        outer.addWidget(footer)

    def mousePressEvent(self, event):
        self.clicked.emit({"case_pk": self.entry.case_pk})
        super().mousePressEvent(event)


class CaseOfDayPage(QWidget):
    case_opened = Signal(dict)  # payload includes case_pk
    case_created = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        self._selected_case: Optional[CaseOfDayEntry] = None
        self._current_modality: str = ""
        self._current_body_part: str = ""
        self._search_text: str = ""
        self._build_ui()
        self.refresh()

    def _on_theme_changed(self, theme: Dict[str, Any]):
        self._theme = theme or self.theme_manager.current_theme()
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        while self.layout() is not None and self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        t = self._theme
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        left = QFrame()
        left.setFixedWidth(380)
        left.setStyleSheet(f"QFrame {{ background-color: {t['panel_deep_bg']}; border-right: 1px solid {t['border']}; }}")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(18, 18, 18, 18)
        left_layout.setSpacing(12)

        title = QLabel("Case of the Day")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {t['text_primary']};")
        left_layout.addWidget(title)

        self.create_btn = QPushButton("Import DICOM Folder")
        self.create_btn.setFixedHeight(42)
        self.create_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: {t['button_text']};
                border: 1px solid {t['accent']};
                border-radius: 2px;
                font-size: 11pt;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        """)
        self.create_btn.clicked.connect(self._create_case)
        left_layout.addWidget(self.create_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by patient, modality, body part, diagnosis, notes...")
        self.search.setFixedHeight(42)
        self.search.setStyleSheet(f"""
            QLineEdit {{
                background-color: {t['panel_bg']};
                color: {t['text_primary']};
                border: 1px solid {t['border']};
                border-radius: 2px;
                padding: 0 14px;
                font-size: 12pt;
            }}
        """)
        self.search.textChanged.connect(self._on_search)
        left_layout.addWidget(self.search)

        self.modality_filter = QComboBox()
        self.modality_filter.setFixedHeight(40)
        self.modality_filter.setStyleSheet(
            f"QComboBox {{ background-color: {t['panel_bg']}; color: {t['text_primary']}; border: 1px solid {t['border']}; padding: 6px 10px; }}"
        )
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

        # Header row: case count on the left + section label on the right.
        # Gives the empty / sparse states a more populated, finished look.
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        self.results = QLabel("0 cases")
        self.results.setStyleSheet(
            f"color: {t['text_primary']}; font-size: 14pt; font-weight: 600;"
        )
        header_row.addWidget(self.results)
        header_row.addStretch(1)
        header_hint = QLabel("Click any case to open it in the viewer")
        header_hint.setStyleSheet(
            f"color: {t.get('text_muted', t['text_secondary'])}; "
            f"font-size: 9.5pt; font-style: italic;"
        )
        header_row.addWidget(header_hint)
        center_layout.addLayout(header_row)

        # Slim accent separator under the count.
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {t['border']}; border: none;")
        center_layout.addWidget(sep)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { border: none; background-color: transparent; }")
        self.grid_container = QWidget()
        self.grid = QGridLayout(self.grid_container)
        self.grid.setContentsMargins(4, 12, 4, 12)
        self.grid.setHorizontalSpacing(18)
        self.grid.setVerticalSpacing(18)
        # Anchor cards to the top-left so a single card doesn't float in the
        # middle of the panel. Cells expand to the card size; empty cells
        # don't reserve space.
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
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
            t = self._theme
            # Richer empty state: title + body copy + visual icon. Helps users
            # discover the two paths to save a case (toolbar export or
            # manual import from this page).
            empty_box = QFrame()
            empty_box.setStyleSheet("background: transparent; border: none;")
            empty_layout = QVBoxLayout(empty_box)
            empty_layout.setContentsMargins(40, 60, 40, 60)
            empty_layout.setSpacing(8)
            empty_layout.setAlignment(Qt.AlignCenter)

            icon = QLabel("📖")
            icon.setAlignment(Qt.AlignCenter)
            icon.setStyleSheet("font-size: 48pt; background: transparent;")
            empty_layout.addWidget(icon)

            title = QLabel("No saved cases yet")
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet(
                f"color: {t['text_primary']}; font-size: 16pt; "
                f"font-weight: 600; background: transparent;"
            )
            empty_layout.addWidget(title)

            hint = QLabel(
                "Save the current study as a Case of the Day from any patient's viewer "
                "toolbar (graduation-cap icon), or use the Import DICOM Folder button "
                "on the left to add one manually."
            )
            hint.setAlignment(Qt.AlignCenter)
            hint.setWordWrap(True)
            hint.setMaximumWidth(540)
            hint.setStyleSheet(
                f"color: {t.get('text_muted', t['text_secondary'])}; "
                f"font-size: 10.5pt; background: transparent; line-height: 1.6;"
            )
            empty_layout.addWidget(hint, alignment=Qt.AlignCenter)

            self.grid.addWidget(empty_box, 0, 0, 1, 3, alignment=Qt.AlignCenter)
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


# ---------------------------------------------------------------------------
# Top-level Case of the Day tab — wraps `CaseOfDayPage` with a Local | Server
# segmented header. Server section is a stub right now and lights up only when
# a future server feed is wired in (gated by a feature flag from the server).
# ---------------------------------------------------------------------------

class CaseOfDayLocalServerPage(QWidget):
    """Top-level Education tab content for Case of the Day.

    Layout: a thin segmented header at the top (Local / Server) over a
    ``QStackedWidget`` body. Re-emits the inner ``case_opened`` /
    ``case_created`` signals so the outer Education module can react to them
    exactly like it did when the CaseOfDayPage lived inside My Courses.
    """

    case_opened = Signal(dict)
    case_created = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_manager = get_theme_manager()
        self._theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        self._current_section = "local"
        self._build_ui()

        # Subscribe to the global Case-of-Day saved signal. When ANY part of
        # the app saves a case (toolbar, manual entry, server sync...), this
        # tab refreshes its list immediately — so the user doesn't have to
        # leave and come back to see new entries.
        try:
            hub = case_of_day_events()
            if hub is not None:
                hub.saved.connect(self._on_external_save)
        except Exception:
            pass

    def _on_external_save(self, _payload: Dict[str, Any]):
        """Triggered when ``case_of_day_events().saved`` fires from anywhere."""
        try:
            self.local_page.refresh()
        except Exception:
            pass

    def showEvent(self, event):
        """Refresh the local case list every time the tab becomes visible.

        QTabWidget keeps inactive tabs hidden but alive, so the page is
        re-shown rather than re-constructed when the user clicks the tab.
        Calling refresh on every show guarantees that a case saved from the
        patient toolbar in between two visits to this tab shows up the next
        time the user opens it, even if the signal-based path missed it.
        """
        try:
            self.local_page.refresh()
        except Exception:
            pass
        super().showEvent(event)

    def _on_theme_changed(self, theme: Dict[str, Any]):
        self._theme = theme or self.theme_manager.current_theme()
        # Lazy refresh: just restyle the toggle pills; the inner pages handle
        # their own theme rebuild via the theme manager signal.
        self._apply_toggle_styles()

    def _build_ui(self):
        t = self._theme
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header with segmented Local / Server toggle.
        header = QFrame()
        header.setFixedHeight(54)
        header.setStyleSheet(
            f"QFrame {{ background-color: {t['panel_bg']}; "
            f"border-bottom: 1px solid {t['border']}; }}"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 10, 20, 10)
        header_layout.setSpacing(8)

        self.local_btn = QPushButton("Local")
        self.server_btn = QPushButton("Server")
        for btn in (self.local_btn, self.server_btn):
            btn.setFixedHeight(32)
            btn.setMinimumWidth(110)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setCheckable(True)

        self.local_btn.clicked.connect(lambda: self._switch_section("local"))
        self.server_btn.clicked.connect(lambda: self._switch_section("server"))
        header_layout.addWidget(self.local_btn)
        header_layout.addWidget(self.server_btn)
        header_layout.addStretch(1)

        section_hint = QLabel(
            "Saved cases live under user_data/education/Case of the Day/"
        )
        section_hint.setStyleSheet(
            f"color: {t.get('text_muted', t['text_secondary'])}; font-size: 9.5pt;"
        )
        header_layout.addWidget(section_hint)

        root.addWidget(header)

        # Stacked body: index 0 = Local, index 1 = Server.
        self.stack = QStackedWidget()

        self.local_page = CaseOfDayPage(self)
        # Bubble the inner signals up.
        self.local_page.case_opened.connect(self.case_opened.emit)
        self.local_page.case_created.connect(self.case_created.emit)
        self.stack.addWidget(self.local_page)

        self.server_page = self._build_server_placeholder()
        self.stack.addWidget(self.server_page)

        root.addWidget(self.stack, 1)

        self._apply_toggle_styles()
        self._switch_section("local")

    def _apply_toggle_styles(self):
        t = self._theme
        active = f"""
            QPushButton {{
                background-color: {t['accent']};
                color: {t['button_text']};
                border: 1px solid {t['accent']};
                border-radius: 4px;
                font-size: 10.5pt;
                font-weight: 700;
                padding: 0 14px;
            }}
        """
        inactive = f"""
            QPushButton {{
                background-color: transparent;
                color: {t['text_secondary']};
                border: 1px solid {t['border']};
                border-radius: 4px;
                font-size: 10.5pt;
                font-weight: 600;
                padding: 0 14px;
            }}
            QPushButton:hover {{
                color: {t['text_primary']};
                border-color: {t['accent_hover']};
            }}
        """
        is_local = (self._current_section == "local")
        self.local_btn.setStyleSheet(active if is_local else inactive)
        self.server_btn.setStyleSheet(active if not is_local else inactive)
        self.local_btn.setChecked(is_local)
        self.server_btn.setChecked(not is_local)

    def _switch_section(self, section: str):
        self._current_section = "server" if section == "server" else "local"
        self._apply_toggle_styles()
        self.stack.setCurrentIndex(1 if self._current_section == "server" else 0)
        # Refresh local cases when returning to that section so anything saved
        # via the toolbar in the meantime shows up immediately.
        if self._current_section == "local":
            try:
                self.local_page.refresh()
            except Exception:
                pass

    def _build_server_placeholder(self) -> QWidget:
        t = self._theme
        page = QWidget()
        page.setStyleSheet(f"background-color: {t['panel_deep_bg']};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(14)
        layout.addStretch(1)

        title = QLabel("Server Case of the Day")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.DemiBold)
        title.setFont(title_font)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(f"color: {t['text_primary']}; background: transparent; border: none;")
        layout.addWidget(title)

        body = QLabel(
            "The connected server has not published any Case of the Day entries, "
            "or your account does not yet have permission to view them.\n\n"
            "When a server-side Case-of-Day feed is enabled, shared cases will "
            "appear here automatically. For now, use the Local section to save "
            "and review your own cases."
        )
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        body.setStyleSheet(
            f"color: {t.get('text_muted', t['text_secondary'])}; "
            f"font-size: 11pt; background: transparent; border: none;"
        )
        layout.addWidget(body)

        switch_back = QPushButton("Go to Local Cases")
        switch_back.setCursor(Qt.PointingHandCursor)
        switch_back.setFixedHeight(36)
        switch_back.setFixedWidth(180)
        switch_back.setStyleSheet(f"""
            QPushButton {{
                background-color: {t['accent']};
                color: {t['button_text']};
                border: 1px solid {t['accent']};
                border-radius: 4px;
                font-size: 10.5pt;
                font-weight: 700;
            }}
            QPushButton:hover {{ background-color: {t['accent_hover']}; }}
        """)
        switch_back.clicked.connect(lambda: self._switch_section("local"))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(switch_back)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addStretch(2)
        return page

    # Convenience methods so the outer page can poke us.
    def refresh(self):
        try:
            self.local_page.refresh()
        except Exception:
            pass
