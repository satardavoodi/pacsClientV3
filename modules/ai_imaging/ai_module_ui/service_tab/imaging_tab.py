import ast
import csv
import math
import json
import os
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, QEvent, QObject, QEventLoop
from PySide6.QtGui import QStandardItemModel, QStandardItem, QMovie
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QListView, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QListWidget,
    QProgressBar, QDialog, QDialogButtonBox, QFormLayout, QScrollArea
)

from . import AbstractTab
from . import AIPatientWidget
from PacsClient.utils.config import CLINICAL_CSV_PATH, ATTACHMENT_PATH
from modules.viewer.interactor_styles import ToolAccess
from PacsClient.pacs.patient_tab.utils import BoxManager, show_message
from PacsClient.utils.utils import load_mg_ai_runs
from modules.ai_imaging.ai_module_ui.csv_table import read_csv_table
from modules.ai_imaging.ai_module_ui.feedback_schema import write_mg_feedback_csv, load_feedback_row, upsert_bone_age_feedback_csv
from modules.ai_imaging.ai_module_ui.mg_csv_schema import infer_mg_csv_contract, normalize_mg_action

# ------------------------------ Custom Events ------------------------------

class _BoneAgeLoadedEvent(QEvent):
    """Ø±ÙˆÛŒØ¯Ø§Ø¯ Ø³ÙØ§Ø±Ø´ÛŒ Ø¨Ø±Ø§ÛŒ Ø§Ù†ØªÙ‚Ø§Ù„ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø´Ø¯Ù‡ Ø§Ø² ØªØ±Ø¯ Ù¾Ø³â€ŒØ²Ù…ÛŒÙ†Ù‡ Ø¨Ù‡ ØªØ±Ø¯ Ø§ØµÙ„ÛŒ"""
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())
    
    def __init__(self, data: dict):
        super().__init__(_BoneAgeLoadedEvent.EVENT_TYPE)
        self.data = data


# ------------------------------ Box helpers ------------------------------

def _read_dicom_pixel_geometry(dicom_path: str) -> dict:
    """
    Read actual image dimensions and pixel spacing from a DICOM file.
    Returns dict with 'img_width', 'img_height', 'pixel_spacing_x', 'pixel_spacing_y'.
    All measurements should use these values instead of hardcoded defaults.
    """
    result = {'img_width': None, 'img_height': None,
              'pixel_spacing_x': None, 'pixel_spacing_y': None}
    if not dicom_path or not os.path.isfile(str(dicom_path)):
        return result
    try:
        import pydicom
        ds = pydicom.dcmread(str(dicom_path), stop_before_pixels=True, force=True)
        cols = getattr(ds, 'Columns', None)
        rows = getattr(ds, 'Rows', None)
        if cols is not None:
            result['img_width'] = int(cols)
        if rows is not None:
            result['img_height'] = int(rows)
        # ImagerPixelSpacing is more accurate for mammography (detector spacing)
        # PixelSpacing is the fallback
        spacing = getattr(ds, 'ImagerPixelSpacing', None) or getattr(ds, 'PixelSpacing', None)
        if spacing is not None and len(spacing) >= 2:
            result['pixel_spacing_y'] = float(spacing[0])  # row spacing
            result['pixel_spacing_x'] = float(spacing[1])  # col spacing
    except Exception:
        pass
    return result


def _parse_box_cell(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return []
    if isinstance(val, list):
        return val
    s = str(val).strip()
    if not s:
        return []
    try:
        data = ast.literal_eval(s)
    except Exception:
        return []
    # Ù†Ø±Ù…Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ: Ù‡Ù…ÛŒØ´Ù‡ list[list[float]]
    if isinstance(data, (list, tuple)) and len(data) == 4:
        return [list(map(float, data))]
    if isinstance(data, (list, tuple)) and all(isinstance(x, (list, tuple)) and len(x) == 4 for x in data):
        return [list(map(float, x)) for x in data]
    return []


def _same_box(a, b, tol=1e-4):
    return all(math.isclose(float(a[i]), float(b[i]), abs_tol=tol) for i in range(4))


def _contains(boxes, cand, tol=1e-4):
    return any(_same_box(bb, cand, tol) for bb in boxes)


def _append_unique(boxes, cand, tol=1e-4):
    if not _contains(boxes, cand, tol):
        boxes.append([float(c) for c in cand])


def _remove_if_exists(boxes, cand, tol=1e-4):
    idx = None
    for i, bb in enumerate(boxes):
        if _same_box(bb, cand, tol):
            idx = i
            break
    if idx is not None:
        boxes.pop(idx)
        return True
    return False


def update_csv(csv_path: str, row, *, status: bool, corner_ijk_points):
    df = read_csv_table(csv_path)

    # Ù¾ÛŒØ¯Ø§ Ú©Ø±Ø¯Ù† Ø±Ø¯ÛŒÙ Ù‡Ø¯Ù (Ø¨Ù‡ØªØ±Ù‡ Ø¨Ø§ dicom_full_path)
    target_idx = None
    if "dicom_full_path" in row.columns:
        key = str(row["dicom_full_path"].iloc[0])
        hit = df.index[df["dicom_full_path"] == key].tolist()
        if hit:
            target_idx = hit[0]
    if target_idx is None:
        raise ValueError("Ø±Ø¯ÛŒÙ Ù‡Ø¯Ù Ù¾ÛŒØ¯Ø§ Ù†Ø´Ø¯Ø› dicom_full_path Ù„Ø§Ø²Ù… Ø§Ø³Øª.")

    # ØªØ¶Ù…ÛŒÙ† Ø³ØªÙˆÙ†â€ŒÙ‡Ø§ + dtype object
    for col in ("box", "new_box", "removed"):
        if col not in df.columns:
            df[col] = ""
        if getattr(df[col], "dtype", object) != object:
            df[col] = df[col].astype(object)

    # Ù¾Ø§Ø±Ø³ Ø³ØªÙˆÙ†â€ŒÙ‡Ø§
    boxes = _parse_box_cell(df.at[target_idx, "box"])
    new_boxes = _parse_box_cell(df.at[target_idx, "new_box"])
    removed = _parse_box_cell(df.at[target_idx, "removed"])

    cand = [float(x) for x in corner_ijk_points]  # [x0,y0,x1,y1]

    in_box = _contains(boxes, cand)
    in_new = _contains(new_boxes, cand)
    in_rem = _contains(removed, cand)

    if status:  # True (Abnormal) --> Ø§Ú¯Ø± Ø¯Ø± box Ùˆ new_box Ù†Ø¨ÙˆØ¯ØŒ Ø¨Ù‡ new_box Ø§Ø¶Ø§ÙÙ‡
        if not in_box and not in_new:
            _append_unique(new_boxes, cand)
            _remove_if_exists(removed, cand)  # Ø­Ø°Ù Ø§Ø² removed Ø¯Ø± ØµÙˆØ±Øª ÙˆØ¬ÙˆØ¯
    else:
        # False (Normal)
        if in_new:
            _remove_if_exists(new_boxes, cand)
        elif in_box:
            if not in_rem:
                _append_unique(removed, cand)
            _remove_if_exists(new_boxes, cand)
        else:
            pass

    # Ù†ÙˆØ´ØªÙ† Ø¨Ù‡ CSV (Ø¨Ù‡ ØµÙˆØ±Øª Ø±Ø´ØªÙ‡)
    df.at[target_idx, "new_box"] = str(new_boxes) if new_boxes else ""
    df.at[target_idx, "removed"] = str(removed) if removed else ""

    df.to_csv(csv_path, index=False)
    return df.loc[[target_idx], ["dicom_full_path", "box", "new_box", "removed"]]


# ------------------------------ Base Sidebar ------------------------------

class BaseSidebar(QWidget):
    """
    Base class for modality-specific sidebars.
    """

    def __init__(self, parent, study_uid: str):
        super().__init__(parent)
        self.study_uid = study_uid
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

    def build_ui(self):
        raise NotImplementedError

    def load_data(self):
        pass

    def clear(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.setParent(None)


class MGSidebar(BaseSidebar):
    """
    Sidebar for Mammography (MG) modality.
    """

    def __init__(self, parent, study_uid: str, imaging_tab):
        super().__init__(parent, study_uid)
        self.imaging_tab = imaging_tab
        self.build_ui()

    def build_ui(self):
        self.imaging_tab._build_mg_sidebar_ui(self.layout)

    def load_data(self):
        pass


class DXSidebar(BaseSidebar):
    """
    Sidebar for DX (Bone Age) modality.
    """

    def __init__(self, parent, study_uid: str, imaging_tab=None):
        super().__init__(parent, study_uid)
        self.imaging_tab = imaging_tab
        self.build_ui()
        self.load_data()

    def build_ui(self):
        """
        Build DX sidebar UI (Bone Age).
        """
        title = QLabel("Bone Age Analysis")
        title.setStyleSheet("font-weight: bold;")

        self.feature_label = QLabel("Features")
        self.feature_list = QListWidget()

        self.corrected_years_label = QLabel("Corrected Bone Age Years")
        self.corrected_years_edit = QLineEdit()
        self.corrected_years_edit.setPlaceholderText("e.g. 13.5")

        self.corrected_months_label = QLabel("Corrected Bone Age Months")
        self.corrected_months_edit = QLineEdit()
        self.corrected_months_edit.setPlaceholderText("e.g. 162")

        self.corrected_sex_label = QLabel("Corrected Sex")
        self.corrected_sex_combo = QComboBox()
        self.corrected_sex_combo.addItems(["", "male", "female"])

        self.validation_label = QLabel("Validation Status")
        self.validation_combo = QComboBox()
        self.validation_combo.addItems(["pending_review", "confirmed", "corrected", "excluded"])

        self.reviewer_label = QLabel("Reviewer")
        self.reviewer_edit = QLineEdit()
        self.reviewer_edit.setPlaceholderText("Reviewer ID")
        if self.imaging_tab is not None:
            self.reviewer_edit.setText(self.imaging_tab._default_reviewer_id())

        self.notes_label = QLabel("Correction Notes")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        self.save_review_btn = QPushButton("Save Review")
        self.save_review_btn.clicked.connect(self._save_review)

        self.layout.addWidget(title)
        self.layout.addWidget(self.feature_label)
        self.layout.addWidget(self.feature_list)
        self.layout.addWidget(self.corrected_years_label)
        self.layout.addWidget(self.corrected_years_edit)
        self.layout.addWidget(self.corrected_months_label)
        self.layout.addWidget(self.corrected_months_edit)
        self.layout.addWidget(self.corrected_sex_label)
        self.layout.addWidget(self.corrected_sex_combo)
        self.layout.addWidget(self.validation_label)
        self.layout.addWidget(self.validation_combo)
        self.layout.addWidget(self.reviewer_label)
        self.layout.addWidget(self.reviewer_edit)
        self.layout.addWidget(self.notes_label)
        self.layout.addWidget(self.notes_edit)
        self.layout.addWidget(self.save_review_btn)
        self.layout.addStretch()

    def load_data(self):
        """
        Load bone age features from bone_age.json if exists.
        """
        bone_json = ATTACHMENT_PATH / self.study_uid / "bone_age.json"
        if not bone_json.exists():
            return

        try:
            with open(bone_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.feature_list.clear()

            # Ù†Ù…Ø§ÛŒØ´ Ø§Ø·Ù„Ø§Ø¹Ø§Øª bone age
            years = data.get("bone_age_years")
            if years is None:
                years = data.get("predicted_bone_age_years")

            months = data.get("bone_age_months")
            if months is None:
                months = data.get("predicted_bone_age_months")

            sex = data.get("sex")

            if years is not None:
                self.feature_list.addItem(f"Bone Age (Years): {years}")
            if months is not None:
                self.feature_list.addItem(f"Bone Age (Months): {months}")
            if sex:
                self.feature_list.addItem(f"Sex: {sex}")

            feedback_path = ATTACHMENT_PATH / self.study_uid / "bone_age_feedback.csv"
            feedback_row = load_feedback_row(feedback_path, "case_id", self.study_uid)
            if feedback_row:
                self.corrected_years_edit.setText(str(feedback_row.get("corrected_bone_age_years") or ""))
                self.corrected_months_edit.setText(str(feedback_row.get("corrected_bone_age_months") or ""))
                corrected_sex = str(feedback_row.get("corrected_sex") or "")
                idx = self.corrected_sex_combo.findText(corrected_sex)
                self.corrected_sex_combo.setCurrentIndex(idx if idx >= 0 else 0)
                validation_status = str(feedback_row.get("validation_status") or "pending_review")
                idx = self.validation_combo.findText(validation_status)
                self.validation_combo.setCurrentIndex(idx if idx >= 0 else 0)
                self.reviewer_edit.setText(str(feedback_row.get("reviewer_id") or self.reviewer_edit.text() or ""))
                self.notes_edit.setPlainText(str(feedback_row.get("correction_notes") or ""))

        except Exception as e:
            print(f"[DXSidebar] failed to load bone age: {e}")

    def _save_review(self):
        try:
            bone_json = ATTACHMENT_PATH / self.study_uid / "bone_age.json"
            result_data = {}
            if bone_json.exists():
                with open(bone_json, "r", encoding="utf-8") as f:
                    result_data = json.load(f)

            corrected_data = {
                "bone_age_years": self.corrected_years_edit.text().strip(),
                "bone_age_months": self.corrected_months_edit.text().strip(),
                "sex": self.corrected_sex_combo.currentText().strip(),
            }
            review_metadata = {
                "validation_status": self.validation_combo.currentText().strip() or "pending_review",
                "reviewer_id": self.reviewer_edit.text().strip(),
                "correction_notes": self.notes_edit.toPlainText().strip(),
                "export_status": "local_only",
                "server_sync_status": "not_synced",
            }
            upsert_bone_age_feedback_csv(
                self.study_uid,
                ATTACHMENT_PATH / self.study_uid,
                {},
                result_data,
                corrected_data=corrected_data,
                review_metadata=review_metadata,
            )
            show_message("Bone age review saved")
        except Exception as e:
            show_message(f"Failed to save bone age review: {e}")


# ------------------------------ Multi-select Combo ------------------------------

class CheckComboBox(QComboBox):
    """QComboBox Ø¨Ø§ Ø¢ÛŒØªÙ…â€ŒÙ‡Ø§ÛŒ Ú†Ú©â€ŒØ¨Ø§Ú©Ø³ÛŒ (multi-select) Ùˆ Ù†Ù…Ø§ÛŒØ´ Ø®Ù„Ø§ØµÙ‡ Ø§Ù†ØªØ®Ø§Ø¨â€ŒÙ‡Ø§ Ø¯Ø± Ø®Ø·Ù ÙˆÛŒØ±Ø§ÛŒØ´."""
    selectionChanged = Signal(list)  # emits list[str] of selected texts

    def __init__(self, parent=None, placeholder="Select..."):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))
        self.setView(QListView(self))
        self.view().pressed.connect(self._on_item_pressed)

        # Ù†Ù…Ø§ÛŒØ´ Ù…ØªÙ† Ø¯Ø§Ø®Ù„ Ø®ÙˆØ¯ Ú©Ø§Ù…Ø¨Ùˆ (ÙÙ‚Ø· Ø®ÙˆØ§Ù†Ø¯Ù†ÛŒ)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(placeholder)
        self.setInsertPolicy(QComboBox.NoInsert)

        # ØªÙ„Ø§Ø´ Ø¨Ø±Ø§ÛŒ Ø¨Ø§Ø² Ù†Ú¯Ù‡ Ø¯Ø§Ø´ØªÙ† Ù¾Ø§Ù¾â€ŒØ¢Ù¾ Ù‡Ù†Ú¯Ø§Ù… ØªÛŒÚ©â€ŒØ²Ø¯Ù†â€ŒÙ‡Ø§ÛŒ Ù¾ÛŒØ§Ù¾ÛŒ
        self._keep_open = True

    # --- API ---
    def addItemsCheckable(self, items, checked: list[str] = None):
        m: QStandardItemModel = self.model()
        m.clear()
        checked = set(checked or [])
        for text in items:
            it = QStandardItem(text)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            it.setData(Qt.Checked if text in checked else Qt.Unchecked, Qt.CheckStateRole)
            m.appendRow(it)
        self._update_display()

    def checkedItems(self) -> list[str]:
        m: QStandardItemModel = self.model()
        out = []
        for i in range(m.rowCount()):
            it = m.item(i)
            if it and it.checkState() == Qt.Checked:
                out.append(it.text())
        return out

    def setCheckedItems(self, items: list[str]):
        want = set(items or [])
        m: QStandardItemModel = self.model()
        for i in range(m.rowCount()):
            it = m.item(i)
            if it:
                it.setCheckState(Qt.Checked if it.text() in want else Qt.Unchecked)
        self._update_display()
        self.selectionChanged.emit(self.checkedItems())

    # --- Internals ---
    def _on_item_pressed(self, index):
        it: QStandardItem = self.model().itemFromIndex(index)
        if it:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)
            self._update_display()
            self.selectionChanged.emit(self.checkedItems())

    def _update_display(self):
        sel = self.checkedItems()
        if not sel:
            self.lineEdit().clear()
            return
        text = ", ".join(sel)
        if len(text) > 40:
            text = f"{len(sel)} selected"
        self.lineEdit().setText(text)


class MGFindingEditorDialog(QDialog):
    def __init__(
            self,
            parent=None,
            *,
            title="Mammography Finding",
            contract=None,
            ai_values=None,
            corrected_values=None,
            box_points=None,
            action="corrected",
            validation_status="pending",
            reviewer_id="",
            notes="",
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 620)
        self.contract = contract or infer_mg_csv_contract()
        self.ai_values = ai_values or {}
        self.corrected_values = corrected_values or {}
        self.box_points = box_points
        self._mandatory_inputs = {}
        self._optional_inputs = {}

        root = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)

        body_layout.addWidget(QLabel("Mandatory CSV / Retraining Fields"))
        mandatory_form = QFormLayout()
        body_layout.addLayout(mandatory_form)

        for spec in self.contract.get("mandatory", []):
            ai_value = self._value_for_spec(spec)
            if spec.automatic or not spec.editable:
                widget = QLineEdit(str(ai_value or ""))
                widget.setReadOnly(True)
            else:
                widget = QLineEdit(str(self.corrected_values.get(spec.name) or ai_value or ""))
            mandatory_form.addRow(QLabel(spec.label), widget)
            self._mandatory_inputs[spec.name] = (spec, widget)

        body_layout.addWidget(QLabel("Automatic Fields"))
        automatic_form = QFormLayout()
        body_layout.addLayout(automatic_form)
        for spec in self.contract.get("automatic", []):
            widget = QLineEdit(str(self._value_for_spec(spec) or ""))
            widget.setReadOnly(True)
            automatic_form.addRow(QLabel(spec.label), widget)

        body_layout.addWidget(QLabel("Optional Review / Documentation Fields"))
        optional_form = QFormLayout()
        body_layout.addLayout(optional_form)
        for spec in self.contract.get("optional", []):
            widget = QLineEdit(str(self.corrected_values.get(spec.name) or self.ai_values.get(spec.name) or ""))
            optional_form.addRow(QLabel(spec.label), widget)
            self._optional_inputs[spec.name] = (spec, widget)

        body_layout.addWidget(QLabel("Validation"))
        validation_form = QFormLayout()
        body_layout.addLayout(validation_form)
        self.action_combo = QComboBox()
        self.action_combo.addItems(["confirmed", "rejected", "corrected", "new_human_finding"])
        self._set_combo_text(self.action_combo, normalize_mg_action(action))
        self.validation_combo = QComboBox()
        self.validation_combo.addItems(["pending", "confirmed", "rejected", "corrected", "new_human_finding", "excluded"])
        self._set_combo_text(self.validation_combo, normalize_mg_action(validation_status) if validation_status else normalize_mg_action(action))
        self.reviewer_edit = QLineEdit(str(reviewer_id or ""))
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlainText(str(notes or ""))
        validation_form.addRow(QLabel("Action"), self.action_combo)
        validation_form.addRow(QLabel("Validation Status"), self.validation_combo)
        validation_form.addRow(QLabel("Reviewer"), self.reviewer_edit)
        validation_form.addRow(QLabel("Notes"), self.notes_edit)

        scroll.setWidget(body)
        root.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _value_for_spec(self, spec):
        if spec.name in ("box", "new_box") and self.box_points:
            return str([float(v) for v in self.box_points])
        if spec.name in ("xmin", "ymin", "xmax", "ymax") and self.box_points:
            idx = {"xmin": 0, "ymin": 1, "xmax": 2, "ymax": 3}[spec.name]
            return str(float(self.box_points[idx]))
        return self.ai_values.get(spec.name, "")

    def _set_combo_text(self, combo, value):
        idx = combo.findText(str(value or ""))
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _accept_if_valid(self):
        missing = []
        for _name, (spec, widget) in self._mandatory_inputs.items():
            value = widget.text().strip()
            if spec.required and not spec.automatic and spec.editable and not value:
                missing.append(spec.label)
        if missing:
            QMessageBox.warning(self, "Missing Mandatory Fields", "Please fill: " + ", ".join(missing))
            return
        self.accept()

    def result_data(self):
        mandatory_values = {
            name: widget.text().strip()
            for name, (_spec, widget) in self._mandatory_inputs.items()
        }
        optional_values = {
            name: widget.text().strip()
            for name, (_spec, widget) in self._optional_inputs.items()
        }
        action = self.action_combo.currentText().strip()
        return {
            "mandatory": mandatory_values,
            "optional": optional_values,
            "action": action,
            "validation_status": self.validation_combo.currentText().strip() or action,
            "reviewer_id": self.reviewer_edit.text().strip(),
            "correction_notes": self.notes_edit.toPlainText().strip(),
        }


# ------------------------------ Main Tab ------------------------------

def normalize_eagle_eye_mode(mode):
    value = str(mode or "").strip().lower()
    if value in ("mg", "mammo", "mammography", "breast"):
        return "mammography"
    if value in ("dx", "bone", "bone_age", "bone-age", "boneage"):
        return "bone_age"
    return None


class ImagingToolsTab(AbstractTab):
    # Signal emitted when tab is fully loaded and rendered
    fully_loaded = Signal()
    
    def __init__(self, study_uid: Optional[str] = None, eagle_eye_mode: Optional[str] = None):
        super().__init__()
        self.tool_access = ToolAccess()
        self.study_uid = study_uid
        self.eagle_eye_mode = normalize_eagle_eye_mode(eagle_eye_mode)
        self._sidebar_store: dict[str, dict] = {}
        self.vtk_initialized = False
        self.current_sidebar = None
        self.mg_runs_loaded = False  # ÙÙ„Ú¯ Ø¬Ø¯ÛŒØ¯ Ø¨Ø±Ø§ÛŒ Ù…Ø¯ÛŒØ±ÛŒØª Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ MG runs

        # ---- init MG widgets FIRST (important)
        self._init_mg_widgets()

        # ---- base layouts
        self.add_section('Home', self.home_layout())
        self.add_section('Segment', self.segment_layout())

        self.vertical_layout: QVBoxLayout = self.get_center_layout_vertical()
        self.left_sidebar_root_layout: QVBoxLayout = self.get_sidebar_layout()

        # ---- processing indicator (top-right of imaging tab)
        self._init_processing_indicator()

        # ---- sidebar container widget
        self.left_sidebar_widget = QWidget()
        self.left_sidebar_layout = QVBoxLayout(self.left_sidebar_widget)
        self.left_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        self.left_sidebar_root_layout.addWidget(self.left_sidebar_widget)

        # ---- Create patient widget directly (no loading placeholder)
        self.patient_widget_container = QWidget()
        self.patient_widget_layout = QVBoxLayout(self.patient_widget_container)
        self.patient_widget_layout.setContentsMargins(0, 0, 0, 0)

        # Create patient widget
        self.patient_widget = AIPatientWidget(
            study_uid=study_uid,
            imaging_tab_ui=self,
            eagle_eye_mode=self.eagle_eye_mode,
        )
        self.patient_widget_layout.addWidget(self.patient_widget)

        # ---- viewer toolbar (screenshot / copy / save-as / zoom) ----
        self.viewer_toolbar = self._build_viewer_toolbar()
        self.vertical_layout.addWidget(self.viewer_toolbar)

        self.vertical_layout.addWidget(self.patient_widget_container, stretch=5)

        # Remove unnecessary buttons
        self._remove_patient_widget_buttons()

        # Delay UI setup
        QTimer.singleShot(100, self._post_init_setup)

    def _init_processing_indicator(self):
        self.processing_widget = QWidget()
        processing_layout = QHBoxLayout(self.processing_widget)
        processing_layout.setContentsMargins(0, 0, 0, 0)
        processing_layout.addStretch()

        self.processing_label = QLabel("Processing: Idle")
        self.processing_label.setStyleSheet("color: #9ca3af; font-weight: 600;")

        self.processing_bar = QProgressBar()
        self.processing_bar.setFixedWidth(140)
        self.processing_bar.setFixedHeight(8)
        self.processing_bar.setTextVisible(False)
        self.processing_bar.setRange(0, 1)
        self.processing_bar.setValue(1)
        self.processing_bar.hide()

        processing_layout.addWidget(self.processing_label)
        processing_layout.addWidget(self.processing_bar)

        self.vertical_layout.addWidget(self.processing_widget)

    def set_processing_status(self, text: str, active: bool = True):
        if not hasattr(self, "processing_label"):
            return

        if text:
            self.processing_label.setText(text)

        if active:
            self.processing_label.setStyleSheet("color: #34d399; font-weight: 600;")
            self.processing_bar.setRange(0, 0)
            self.processing_bar.show()
        else:
            self.processing_label.setStyleSheet("color: #9ca3af; font-weight: 600;")
            self.processing_bar.setRange(0, 1)
            self.processing_bar.setValue(1)
            self.processing_bar.hide()

    def _remove_patient_widget_buttons(self):
        """Ø­Ø°Ù Ø¯Ú©Ù…Ù‡â€ŒÙ‡Ø§ÛŒ ØºÛŒØ±Ø¶Ø±ÙˆØ±ÛŒ Ø§Ø² patient_widget"""
        if hasattr(self.patient_widget, 'btn_series'):
            self.patient_widget.sidebar.layout().removeWidget(self.patient_widget.btn_series)
            self.patient_widget.btn_series.setParent(None)
            self.patient_widget.btn_series.deleteLater()

        if hasattr(self.patient_widget, 'btn_reception'):
            self.patient_widget.sidebar.layout().removeWidget(self.patient_widget.btn_reception)
            self.patient_widget.btn_reception.setParent(None)
            self.patient_widget.btn_reception.deleteLater()

        if hasattr(self.patient_widget, 'btn_ai_chat'):
            self.patient_widget.sidebar.layout().removeWidget(self.patient_widget.btn_ai_chat)
            self.patient_widget.btn_ai_chat.setParent(None)
            self.patient_widget.btn_ai_chat.deleteLater()

        # Remove empty sidebar container if exists
        if hasattr(self.patient_widget, 'sidebar') and self.patient_widget.sidebar:
            if self.patient_widget.sidebar.layout().count() == 0:
                self.patient_widget.container_layout.removeWidget(self.patient_widget.sidebar)
                self.patient_widget.sidebar.setParent(None)
                self.patient_widget.sidebar.deleteLater()
                self.patient_widget.container_layout.setSpacing(0)
                self.patient_widget.container_layout.setContentsMargins(0, 0, 0, 0)

    def _post_init_setup(self):
        """Ø§Ø¬Ø±Ø§ÛŒ Ø¹Ù…Ù„ÛŒØ§Øª Ø³Ù†Ú¯ÛŒÙ† Ù¾Ø³ Ø§Ø² Ù†Ù…Ø§ÛŒØ´ UI Ø§ÙˆÙ„ÛŒÙ‡"""
        # Patient widget is already visible, just finalize setup
        QTimer.singleShot(100, self._finalize_loading)
        
    def _finalize_loading(self):
        """Complete the loading process and emit ready signal."""
        # Process pending events to ensure full render
        QApplication.processEvents()
        QApplication.processEvents()
        
        # ÙØ¹Ø§Ù„â€ŒØ³Ø§Ø²ÛŒ tab Ù¾ÛŒØ´â€ŒÙØ±Ø¶ (ÙÙ‚Ø· button styleØŒ Ø¨Ø¯ÙˆÙ† switch Ø¨Ø±Ø§ÛŒ Ø¬Ù„ÙˆÚ¯ÛŒØ±ÛŒ Ø§Ø² Ù„ÙˆØ¯ÛŒÙ†Ú¯ Ø¯ÙˆØ¨Ø§Ø±Ù‡)
        if hasattr(self.patient_widget, 'btn_ai_module'):
            self.patient_widget.btn_ai_module.setChecked(True)
            # Don't call switch_right_panel here - it's already called and causes double loading
        
        # Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø³Ø§ÛŒØ¯Ø¨Ø§Ø±
        QTimer.singleShot(150, self.left_sidebar_layout_ui)
        
        # Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ bone age
        QTimer.singleShot(200, self._load_bone_age_feature_if_exists)

        # Ensure the AI patient widget is treated as active in this window
        try:
            self.patient_widget.on_tab_activated()
        except Exception:
            pass

        # Emit signal immediately - tab is visible and ready for user
        self.fully_loaded.emit()
        print("[ImagingToolsTab] Tab visible, emitting fully_loaded signal")
        
        # Load MG runs in background (after loading overlay is removed)
        if self.detect_modality() == "MG":
            QTimer.singleShot(100, self._load_mg_runs_into_dropdown)

    def _init_mg_widgets(self):
        """
        Initialize all MG sidebar widgets that are used across the class.
        This MUST be called before left_sidebar_layout_ui().
        """

        # -------- Detail Boxes
        self.detail_box_label = QLabel("Detail Boxes")
        self.lst_boxes_combo = QComboBox()
        self.lst_boxes_combo.currentIndexChanged.connect(
            lambda _: self.sidebar_load_current()
        )
        self.lst_boxes_combo.activated.connect(
            lambda _: self._open_mg_finding_editor("corrected")
        )
        self.finding_status_display = QLabel("Status: Pending")
        self.finding_summary_label = QLabel("")
        self.finding_summary_label.setWordWrap(True)

        # -------- Status
        self.status_label = QLabel("Status")
        self.rb_normal = QRadioButton("Normal")
        self.rb_abnormal = QRadioButton("Abnormal")
        self.rb_normal.setChecked(True)

        self.status_group = QWidget()
        status_layout = QHBoxLayout(self.status_group)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(self.rb_normal)
        status_layout.addWidget(self.rb_abnormal)

        # -------- Classification
        self.classification_label = QLabel("Classification")
        self.class_combo = CheckComboBox(placeholder="Select classification...")
        self.class_combo.selectionChanged.connect(
            self._on_class_selection_changed
        )

        # -------- Features
        self.feature_label = QLabel("Features")
        self.feature_view = QTextEdit()
        self.feature_view.setPlaceholderText("features selection")
        self.feature_view.setReadOnly(False)

        self.validation_label = QLabel("Validation Status")
        self.validation_combo = QComboBox()
        self.validation_combo.addItems(["pending_review", "confirmed", "corrected", "excluded"])

        self.reviewer_label = QLabel("Reviewer")
        self.reviewer_edit = QLineEdit()
        self.reviewer_edit.setPlaceholderText("Reviewer ID")
        self.reviewer_edit.setText(self._default_reviewer_id())

        self.notes_label = QLabel("Correction Notes")
        self.notes_edit = QTextEdit()
        self.notes_edit.setPlaceholderText("Optional notes")

        self.laterality_label = QLabel("Laterality")
        self.laterality_combo = QComboBox()
        self.laterality_combo.addItems(["", "Left", "Right", "Bilateral", "Unknown"])

        self.view_label = QLabel("View")
        self.view_combo = QComboBox()
        self.view_combo.addItems(["", "CC", "MLO", "ML", "LM", "XCCL", "XCCM", "Other"])

        self.lesion_type_label = QLabel("Lesion Type")
        self.lesion_type_combo = QComboBox()
        self.lesion_type_combo.addItems([
            "",
            "No Finding",
            "Mass",
            "Suspicious Calcification",
            "Focal Asymmetry",
            "Architectural Distortion",
            "Other",
        ])

        self.location_label = QLabel("Location")
        self.location_edit = QLineEdit()
        self.location_edit.setPlaceholderText("Free-text location")

        self.quadrant_label = QLabel("Quadrant")
        self.quadrant_combo = QComboBox()
        self.quadrant_combo.addItems(["", "UOQ", "UIQ", "LOQ", "LIQ", "Central", "Retroareolar", "Axillary Tail"])

        self.clock_label = QLabel("Clock Position")
        self.clock_edit = QLineEdit()
        self.clock_edit.setPlaceholderText("e.g. 2 o'clock")

        self.depth_label = QLabel("Depth")
        self.depth_combo = QComboBox()
        self.depth_combo.addItems(["", "Anterior", "Middle", "Posterior"])

        self.birads_label = QLabel("BI-RADS")
        self.birads_combo = QComboBox()
        self.birads_combo.addItems(["", "0", "1", "2", "3", "4A", "4B", "4C", "5", "6"])

        self.confidence_label = QLabel("Human Confidence")
        self.confidence_edit = QLineEdit()
        self.confidence_edit.setPlaceholderText("0.00 - 1.00")

        self.human_action_label = QLabel("Human Action")
        self.human_action_combo = QComboBox()
        self.human_action_combo.addItems(["update", "confirm", "correct", "remove", "new_finding"])

        self.mg_runs_label = QLabel("AI Results")
        self.mg_runs_combo = QComboBox()

        # -------- Apply
        self.apply_btn = QPushButton("Apply")
        self.new_finding_btn = QPushButton("New Finding")
        self.save_finding_btn = QPushButton("Save Finding")
        self.confirm_finding_btn = QPushButton("Confirm")
        self.reject_finding_btn = QPushButton("Reject")
        self.edit_finding_btn = QPushButton("Correct / Edit")

        # Ù¾Ø§ÛŒÙ‡â€ŒÛŒ classification (Ø§Ú¯Ø± Ø¨Ø¹Ø¯Ø§Ù‹ override Ø´Ø¯ Ù…Ø´Ú©Ù„ÛŒ Ù†ÛŒØ³Øª)
        base_classes = [
            "No Finding",
            "Mass",
            "Suspicious Calcification",
            "Focal Asymmetry",
        ]
        self.class_combo.addItemsCheckable(base_classes)
        self.class_combo.setCheckedItems([])
        self.apply_btn.clicked.connect(self._on_apply_clicked)
        self.new_finding_btn.clicked.connect(self._on_new_mg_finding_clicked)
        self.save_finding_btn.clicked.connect(self._on_save_mg_finding_clicked)
        self.confirm_finding_btn.clicked.connect(lambda: self._open_mg_finding_editor("confirmed"))
        self.reject_finding_btn.clicked.connect(lambda: self._open_mg_finding_editor("rejected"))
        self.edit_finding_btn.clicked.connect(lambda: self._open_mg_finding_editor("corrected"))

    def _load_mg_runs_into_dropdown(self):
        """Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ MG Ø¨Ù‡ ØµÙˆØ±Øª Ø§Ù…Ù†"""
        if not self.mg_runs_combo:
            return
            
        self.mg_runs_combo.blockSignals(True)
        self.mg_runs_combo.clear()
        selected_index_to_apply = -1

        try:
            data = load_mg_ai_runs(self.study_uid, ATTACHMENT_PATH)
            if not data:
                self.mg_runs_combo.blockSignals(False)
                return

            active = data.get("active", {})
            available = data.get("available", [])

            active_key = (
                active.get("detection"),
                active.get("classification")
            )

            active_index = -1

            for idx, run in enumerate(available):
                det = run.get("detection")
                cls = run.get("classification")

                thr_label = run.get("threshold_label")
                thr = run.get("threshold")

                if thr_label:
                    label = f"Threshold {thr_label}"
                elif thr is not None:
                    label = f"Threshold {thr:.2f}"
                else:
                    label = det

                self.mg_runs_combo.addItem(label, (det, cls))

                if (det, cls) == active_key:
                    active_index = idx

            if active_index >= 0:
                self.mg_runs_combo.setCurrentIndex(active_index)
                selected_index_to_apply = active_index
                
            self.mg_runs_loaded = True
        except Exception as e:
            print(f"Error loading MG runs: {e}")
            self.mg_runs_loaded = False
        finally:
            self.mg_runs_combo.blockSignals(False)

        if selected_index_to_apply >= 0:
            QTimer.singleShot(0, lambda idx=selected_index_to_apply: self._on_mg_run_changed(idx))

    def _save_mg_manifest_selection(self, det_csv: str, cls_csv: str | None) -> None:
        """Persist selected MG run as active in manifest."""
        try:
            if not self.study_uid or not det_csv:
                return

            base_dir = ATTACHMENT_PATH / self.study_uid
            base_dir.mkdir(parents=True, exist_ok=True)
            manifest_path = base_dir / "mg_ai_manifest.json"

            manifest = {"available": [], "active": {}}
            if manifest_path.exists():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    if isinstance(loaded, dict):
                        manifest.update(loaded)
                except Exception:
                    pass

            available = list(manifest.get("available", []) or [])
            new_entry = {
                "detection": det_csv,
                "classification": cls_csv,
            }
            if not any(
                e.get("detection") == det_csv and e.get("classification") == cls_csv
                for e in available
                if isinstance(e, dict)
            ):
                available.append(new_entry)

            manifest["available"] = available
            manifest["active"] = new_entry

            tmp_path = manifest_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, manifest_path)
        except Exception as e:
            print(f"[MG] Failed to persist manifest selection: {e}")

    def _apply_mg_run_to_selected_viewer(self, det_csv: str, cls_csv: str | None) -> None:
        """Apply the selected MG run to the current AI viewer immediately."""
        if not det_csv:
            return

        if not hasattr(self, 'patient_widget') or not self.patient_widget:
            return
        selected_widget = getattr(self.patient_widget, 'selected_widget', None)
        if selected_widget is None:
            return

        vtk_widget = selected_widget

        det_path = Path(det_csv)
        if not det_path.is_absolute():
            det_path = ATTACHMENT_PATH / self.study_uid / det_csv

        cls_path = None
        if cls_csv:
            cls_path = Path(cls_csv)
            if not cls_path.is_absolute():
                cls_path = ATTACHMENT_PATH / self.study_uid / cls_csv

        if hasattr(vtk_widget, 'csv_details_path'):
            vtk_widget.csv_details_path = det_path
        if hasattr(vtk_widget, 'csv_classification'):
            vtk_widget.csv_classification = cls_path

        if hasattr(vtk_widget, '_csv_cache') and isinstance(vtk_widget._csv_cache, dict):
            vtk_widget._csv_cache.clear()
        if hasattr(vtk_widget, '_series_ai_cache') and isinstance(vtk_widget._series_ai_cache, dict):
            vtk_widget._series_ai_cache.clear()

        if hasattr(vtk_widget, '_schedule_manager_ai_safe'):
            vtk_widget._schedule_manager_ai_safe(reason="mg_run_changed")

    def _load_bone_age_feature_if_exists(self):
        """
        Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ bone age Ø¨Ù‡ ØµÙˆØ±Øª ØºÛŒØ±Ù‡Ù…Ø²Ù…Ø§Ù†
        """
        if not self.study_uid:
            QTimer.singleShot(0, lambda: self._update_bone_age_ui({}))
            return

        json_path = ATTACHMENT_PATH / self.study_uid / "bone_age.json"
        
        # ØªÙ†Ø¸ÛŒÙ… Ø­Ø§Ù„Øª Ù„ÙˆØ¯ÛŒÙ†Ú¯ Ø¯Ø± UI
        if hasattr(self, "feature_view") and self.feature_view is not None:
            self.feature_view.setPlaceholderText("Loading bone age data...")
            self.feature_view.clear()
            self.feature_view.setEnabled(False)
        
        # Ø§Ø¬Ø±Ø§ÛŒ Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø¯Ø± ØªØ±Ø¯ Ø¬Ø¯Ø§Ú¯Ø§Ù†Ù‡
        threading.Thread(
            target=self._load_bone_json_async,
            args=(json_path,),
            daemon=True
        ).start()

    def _load_bone_json_async(self, json_path: Path):
        """Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ ÙØ§ÛŒÙ„ JSON Ø¯Ø± ØªØ±Ø¯ Ù¾Ø³â€ŒØ²Ù…ÛŒÙ†Ù‡"""
        try:
            data = {}
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            print(f"[DX] Failed to load bone_age.json: {e}")
            data = {"error": str(e)}
        
        # Ø§Ù†ØªÙ‚Ø§Ù„ Ø¯Ø§Ø¯Ù‡ Ø¨Ù‡ ØªØ±Ø¯ Ø§ØµÙ„ÛŒ Ø§Ø² Ø·Ø±ÛŒÙ‚ Ø±ÙˆÛŒØ¯Ø§Ø¯ Ø³ÙØ§Ø±Ø´ÛŒ
        QApplication.postEvent(self, _BoneAgeLoadedEvent(data))

    def customEvent(self, event: QEvent):
        """Ù¾Ø±Ø¯Ø§Ø²Ø´ Ø±ÙˆÛŒØ¯Ø§Ø¯Ù‡Ø§ÛŒ Ø³ÙØ§Ø±Ø´ÛŒ"""
        if event.type() == _BoneAgeLoadedEvent.EVENT_TYPE:
            self._handle_bone_age_loaded(event)
            event.accept()
        else:
            super().customEvent(event)

    def _handle_bone_age_loaded(self, event: _BoneAgeLoadedEvent):
        """Ù¾Ø±Ø¯Ø§Ø²Ø´ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ bone age Ø¯Ø±ÛŒØ§ÙØª Ø´Ø¯Ù‡"""
        self._update_bone_age_ui(event.data)

    def _update_bone_age_ui(self, data: dict):
        """Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ UI Ø¨Ø§ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ bone age"""
        if not hasattr(self, "feature_view") or self.feature_view is None:
            return
            
        self.feature_view.setEnabled(True)
        
        if "error" in data:
            self.feature_view.setPlainText(f"Error loading bone age data:\n{data['error']}")
            return
            
        lines = []
        if sex := data.get("sex"):
            lines.append(f"Sex: {sex}")
            
        age_years_val = data.get("bone_age_years")
        if age_years_val is None:
            age_years_val = data.get("predicted_bone_age_years")

        if age_years_val is not None:
            try:
                # ØªØ¨Ø¯ÛŒÙ„ Ø³Ù† Ø§Ø¹Ø´Ø§Ø±ÛŒ Ø¨Ù‡ Ø³Ø§Ù„ + Ù…Ø§Ù‡ Ø¨Ø§ Ø±ÙÙ†Ø¯ Ø¨Ù‡ Ø¨Ø§Ù„Ø§
                y = int(age_years_val)
                fractional = float(age_years_val) - y
                months_float = fractional * 12.0
                months = int(months_float)
                if months_float - months > 1e-8:
                    months += 1
                if months == 12:
                    y += 1
                    months = 0
                    
                if months > 0:
                    years_text = f"Bone age: {y} years {months} months"
                else:
                    years_text = f"Bone age: {y} years"
                lines.append(years_text)
            except (TypeError, ValueError):
                pass
        
        text = "\n".join(lines) if lines else ""
        if text:
            self.feature_view.setPlainText(text)
        else:
            self.feature_view.setPlaceholderText("No bone age data available")

    def _on_mg_run_changed(self, index: int):
        """Ù¾Ø±Ø¯Ø§Ø²Ø´ ØªØºÛŒÛŒØ± Ø¯Ø± Ø§Ù†ØªØ®Ø§Ø¨ MG runs Ø¨Ø§ Ù…Ø¯ÛŒØ±ÛŒØª Ø®Ø·Ø§"""
        if index < 0 or index >= self.mg_runs_combo.count():
            return
            
        data = self.mg_runs_combo.itemData(index)
        if not data or len(data) < 2:
            return

        det_csv, cls_csv = data[:2]  # ÙÙ‚Ø· Ø¯Ùˆ Ù…Ù‚Ø¯Ø§Ø± Ø§ÙˆÙ„ Ø±Ø§ Ø¯Ø± Ù†Ø¸Ø± Ø¨Ú¯ÛŒØ±

        try:
            self._save_mg_manifest_selection(det_csv, cls_csv)
            self._apply_mg_run_to_selected_viewer(det_csv, cls_csv)
        except Exception as e:
            error_msg = f"Error in MG run change: {str(e)}"
            print(error_msg)
            # Ù†Ù…Ø§ÛŒØ´ Ù¾ÛŒØ§Ù… Ø®Ø·Ø§ Ø¨Ù‡ Ú©Ø§Ø±Ø¨Ø±
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", error_msg)
            
    def _build_mg_sidebar_ui(self, layout: QVBoxLayout):
        """
        Build MG sidebar UI using pre-initialized widgets.
        """
        # Ù¾Ø§Ú© Ú©Ø±Ø¯Ù† layout Ù‚Ø¨Ù„ÛŒ
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        layout.addWidget(self.detail_box_label)
        layout.addWidget(self.lst_boxes_combo)

        # Ø®Ù„Ø§ØµÙ‡/ÙˆØ¶Ø¹ÛŒØª ÙØ§ÛŒÙ†Ø¯ÛŒÙ†Ú¯ Ø§Ù†ØªØ®Ø§Ø¨â€ŒØ´Ø¯Ù‡
        layout.addWidget(self.finding_status_display)
        layout.addWidget(self.finding_summary_label)

        # ÙÛŒÙ„Ø¯Ù‡Ø§ÛŒ Ú©Ù„Ø§Ø³ÛŒÚ© Ù¾Ù†Ù„ MG (Ø³Ù…Øª Ú†Ù¾) â€” Ù†Ø¨Ø§ÛŒØ¯ Ø­Ø°Ù Ø´ÙˆÙ†Ø¯
        layout.addWidget(self.status_label)
        layout.addWidget(self.status_group)

        layout.addWidget(self.classification_label)
        layout.addWidget(self.class_combo)

        layout.addWidget(self.feature_label)
        layout.addWidget(self.feature_view)

        layout.addWidget(self.validation_label)
        layout.addWidget(self.validation_combo)

        layout.addWidget(self.reviewer_label)
        layout.addWidget(self.reviewer_edit)

        layout.addWidget(self.notes_label)
        layout.addWidget(self.notes_edit)

        # Ø§Ú©Ø´Ù†â€ŒÙ‡Ø§ÛŒ Ø¬Ø¯ÛŒØ¯ finding
        layout.addWidget(self.confirm_finding_btn)
        layout.addWidget(self.reject_finding_btn)
        layout.addWidget(self.edit_finding_btn)
        layout.addWidget(self.new_finding_btn)

        # ðŸ”½ MG AI runs dropdown
        layout.addWidget(self.mg_runs_label)
        layout.addWidget(self.mg_runs_combo)

        # Apply Ú©Ù„Ø§Ø³ÛŒÚ© Ø±Ø§ Ù‡Ù… Ù†Ú¯Ù‡ Ù…ÛŒâ€ŒØ¯Ø§Ø±ÛŒÙ… ØªØ§ UX Ù‚Ø¨Ù„ÛŒ Ø­ÙØ¸ Ø´ÙˆØ¯
        layout.addWidget(self.apply_btn)

        layout.addStretch()

    def detect_modality(self) -> str:
        """
        Detect modality based on available AI results.
        """
        if self.eagle_eye_mode == "bone_age":
            return "DX"
        if self.eagle_eye_mode == "mammography":
            return "MG"

        study_uid = self.study_uid

        # DX if bone age result exists
        bone_json = ATTACHMENT_PATH / study_uid / "bone_age.json"
        if bone_json.exists():
            return "DX"

        # MG default
        return "MG"

    # ---------- Home row ----------
    # ---------- Viewer toolbar (screenshot / copy / save-as / zoom) ----------
    def _build_viewer_toolbar(self):
        """Slim always-visible toolbar above the Eagle Eye viewer.

        Reuses the app-wide capture pipeline (modules.viewer.viewport_capture â†’
        study attachment folder, same gallery as the main viewer) and the
        standard image_viewer zoom APIs. Colors use the Eagle Eye palette hex
        values so AiMainWindow's theme retint maps them to the live theme.
        """
        bar = QWidget()
        bar.setObjectName("eagleViewerToolbar")
        bar.setStyleSheet("""
            QWidget#eagleViewerToolbar {
                background: #1a202c;
                border: 1px solid #2d3748;
                border-radius: 6px;
            }
            QWidget#eagleViewerToolbar QPushButton {
                background: #1a202c;
                color: #f7fafc;
                border: 1px solid #2d3748;
                border-radius: 4px;
                padding: 4px 10px;
                font-size: 12px;
            }
            QWidget#eagleViewerToolbar QPushButton:hover {
                background: #2d3748;
            }
            QWidget#eagleViewerToolbar QPushButton:pressed {
                background: #0f1419;
            }
            QWidget#eagleViewerToolbar QLabel {
                color: #6b7280;
                font-size: 11px;
            }
        """)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)

        try:
            import qtawesome as qta
            _icon = lambda name: qta.icon(name, color='#9ca3af')
        except Exception:
            _icon = lambda name: None

        def _add_btn(text, icon_name, tooltip, slot):
            btn = QPushButton(text)
            icon = _icon(icon_name)
            if icon is not None:
                btn.setIcon(icon)
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
            return btn

        _add_btn('Screenshot', 'fa5s.camera',
                 'Capture the visible viewer (saved to study attachments)',
                 self._eagle_screenshot)
        _add_btn('Copy', 'fa5s.copy',
                 'Copy the visible viewer image to the clipboard',
                 self._eagle_copy_image)
        _add_btn('Save Asâ€¦', 'fa5s.save',
                 'Save the visible viewer image to a file',
                 self._eagle_save_image_as)

        sep = QLabel('|')
        layout.addWidget(sep)

        _add_btn('Zoom In', 'fa5s.search-plus', 'Zoom in (selected viewer)',
                 lambda: self._eagle_zoom(1.25))
        _add_btn('Zoom Out', 'fa5s.search-minus', 'Zoom out (selected viewer)',
                 lambda: self._eagle_zoom(0.8))
        _add_btn('Fit', 'fa5s.expand', 'Zoom to fit (selected viewer)',
                 self._eagle_zoom_fit)

        sep2 = QLabel('|')
        layout.addWidget(sep2)

        self._dual_view_btn = _add_btn(
            '3D Cursor', 'fa5s.columns',
            'Correlate lesion positions between CC and MLO views using 3D cursor (mm-based)',
            self._on_3d_cursor_clicked
        )
        self._mg_ruler_btn = _add_btn(
            'Ruler', 'fa5s.ruler',
            'Enable distance measurement ruler on the selected mammography viewer',
            self._on_mg_ruler_clicked
        )

        layout.addStretch()
        return bar

    def _get_active_eagle_image_viewer(self):
        """Resolve the image_viewer of the currently selected Eagle Eye pane."""
        pw = getattr(self, 'patient_widget', None)
        if pw is None:
            return None
        candidates = []
        sel = getattr(pw, 'selected_widget', None)
        if sel is not None:
            candidates.append(getattr(sel, 'vtk_widget', sel))
        try:
            for node in list(getattr(pw, 'lst_nodes_viewer', []) or []):
                w = getattr(node, 'vtk_widget', None)
                if w is not None:
                    candidates.append(w)
        except Exception:
            pass
        for widget in candidates:
            iv = getattr(widget, 'image_viewer', None)
            if iv is not None:
                return iv
        return None

    def _eagle_grab_pixmap(self):
        """Grab the visible Eagle Eye viewer area (panes + AI box overlays)."""
        try:
            from modules.viewer.viewport_capture import grab_widget_pixmap
            target = getattr(self, 'patient_widget_container', None)
            if target is None:
                return None
            try:
                target.repaint()
            except Exception:
                pass
            return grab_widget_pixmap(target)
        except Exception as e:
            print(f"[EagleEye] grab failed: {e}")
            return None

    def _eagle_screenshot(self):
        """Capture the visible viewer into the study's attachment folder."""
        try:
            from modules.viewer.viewport_capture import save_pixmap_to_attachments
            pixmap = self._eagle_grab_pixmap()
            path = save_pixmap_to_attachments(pixmap, self.study_uid)
            if path:
                self.set_processing_status(f"Screenshot saved: {Path(path).name}", active=False)
            else:
                QMessageBox.warning(self, "Capture Failed", "Could not capture the viewer image.")
        except Exception as e:
            QMessageBox.warning(self, "Capture Failed", f"Could not capture the viewer image.\n{e}")

    def _eagle_copy_image(self):
        """Copy the visible viewer image to the clipboard."""
        pixmap = self._eagle_grab_pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.warning(self, "Copy Failed", "Could not capture the viewer image.")
            return
        QApplication.clipboard().setPixmap(pixmap)
        self.set_processing_status("Image copied to clipboard", active=False)

    def _eagle_save_image_as(self):
        """Save the visible viewer image to a user-chosen file."""
        pixmap = self._eagle_grab_pixmap()
        if pixmap is None or pixmap.isNull():
            QMessageBox.warning(self, "Save Failed", "Could not capture the viewer image.")
            return
        from datetime import datetime
        default_name = f"eagleeye_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Image As", default_name, "PNG Image (*.png);;JPEG Image (*.jpg)"
        )
        if not file_path:
            return
        if pixmap.save(file_path):
            self.set_processing_status(f"Image saved: {Path(file_path).name}", active=False)
        else:
            QMessageBox.warning(self, "Save Failed", "Could not write the image file.")

    def _eagle_zoom(self, factor):
        """Discrete zoom on the selected pane (parallel-projection scale)."""
        iv = self._get_active_eagle_image_viewer()
        if iv is None:
            return
        try:
            camera = iv.renderer.GetActiveCamera()
            scale = camera.GetParallelScale()
            if scale > 0 and factor > 0:
                camera.SetParallelScale(scale / float(factor))
                iv.image_render_window.Render()
        except Exception as e:
            print(f"[EagleEye] zoom failed: {e}")

    def _eagle_zoom_fit(self):
        """Zoom-to-fit on the selected pane (existing image_viewer API)."""
        iv = self._get_active_eagle_image_viewer()
        if iv is None:
            return
        try:
            iv.zoom_to_fit()
        except Exception as e:
            print(f"[EagleEye] zoom_to_fit failed: {e}")

    # ---------- 3D Cursor (CC/MLO Correlation) ----------

    def _on_3d_cursor_clicked(self):
        """
        Run 3D Cursor correlation between CC and MLO views.

        New flow (v2):
            1. User clicks "3D Cursor" button.
            2. An instruction dialog appears asking user to click nipple on view 1.
            3. User clicks nipple on view 1.
            4. Dialog asks for nipple on view 2.
            5. User clicks nipple on view 2.
            6. Correlation runs with user-selected nipple positions.
        """
        if self.detect_modality() != "MG":
            show_message("3D Cursor is only available for Mammography (MG) modality.")
            return

        # Start the manual nipple picking flow
        from modules.ai_imaging.ai_module_ui.cursor_3d.nipple_picker import NipplePickerController

        self._nipple_picker = NipplePickerController(self)
        self._nipple_picker.start(callback=self._on_nipples_picked)

    def _on_mg_ruler_clicked(self):
        """Toggle ruler measurement tool on the selected viewer in MG mode."""
        if self.detect_modality() != "MG":
            show_message("Ruler is only available for Mammography (MG) modality.")
            return

        pw = getattr(self, 'patient_widget', None)
        if pw is None:
            show_message("Viewer is not ready.")
            return

        selected = getattr(pw, 'selected_widget', None)
        if selected is None:
            # Fallback: pick any viewer (prefer non-fixed, but accept any).
            nodes = getattr(pw, 'lst_nodes_viewer', None) or []
            for node in nodes:
                vtk_w = getattr(node, 'vtk_widget', None)
                if vtk_w is not None:
                    selected = vtk_w
                    break

        if selected is None:
            show_message("No active viewer found for ruler.")
            return

        try:
            pw.toolbar_manager.activate_tool(selected, self.tool_access.RULER)
            self.set_processing_status("Ruler toggled", active=False)
        except Exception as e:
            print(f"[ImagingToolsTab] Failed to toggle ruler: {e}")
            show_message("Failed to toggle ruler tool.")

    def _on_nipples_picked(self, nipple1, nipple2):
        """Called when user has selected both nipple points."""
        print(f"[3D-Cursor] Nipples picked: "
              f"{nipple1.view_key}=({nipple1.x_px:.1f},{nipple1.y_px:.1f}), "
              f"{nipple2.view_key}=({nipple2.x_px:.1f},{nipple2.y_px:.1f})")

        self.set_processing_status("Running 3D Cursor Analysis...", active=True)
        QApplication.processEvents()

        try:
            self._run_3d_cursor_analysis_with_nipples(nipple1, nipple2)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message(f"3D Cursor failed: {e}")

    def _run_3d_cursor_analysis_with_nipples(self, nipple1, nipple2):
        """Execute 3D cursor correlation with user-provided nipple positions."""
        from modules.ai_imaging.ai_module_ui.cursor_3d import CursorCorrelator3D
        from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
            draw_3d_cursor_results,
            format_3d_cursor_summary,
        )

        # Build a mapping from vtk_widget to manual nipple position
        manual_nipples = {}  # vtk_widget -> (x_px, y_px)
        if nipple1 and nipple1.vtk_widget:
            manual_nipples[id(nipple1.vtk_widget)] = (nipple1.x_px, nipple1.y_px)
        if nipple2 and nipple2.vtk_widget:
            manual_nipples[id(nipple2.vtk_widget)] = (nipple2.x_px, nipple2.y_px)

        if len(manual_nipples) != 2:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message("دو نقطه nipple باید روی دو ویویر متفاوت انتخاب شوند.")
            return

        # Collect view data from viewer widgets
        view_data_list = self._collect_views_for_3d_cursor()

        if not view_data_list:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message(
                "No view data available for 3D Cursor.\n"
                "Ensure AI detection has been run and both CC/MLO views are loaded."
            )
            return

        # Inject manual nipple positions into ViewData
        for vd in view_data_list:
            widget_id = id(vd.vtk_widget) if vd.vtk_widget else None
            if widget_id and widget_id in manual_nipples:
                vd.manual_nipple_px = manual_nipples[widget_id]

        # Keep only the two selected views (the ones user clicked).
        selected_views = []
        for vd in view_data_list:
            widget_id = id(vd.vtk_widget) if vd.vtk_widget else None
            if widget_id and widget_id in manual_nipples:
                selected_views.append(vd)

        # Filter selected views with valid pixel spacing
        valid_views = [v for v in selected_views
                       if v.pixel_spacing_x and v.pixel_spacing_x > 0
                       and v.pixel_spacing_y and v.pixel_spacing_y > 0]

        if not valid_views:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message("DICOM Pixel Spacing metadata is missing for all views.")
            return

        if len(valid_views) != 2:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message("3D Cursor نیاز به دو ویوی معتبر (CC و MLO) با Pixel Spacing دارد.")
            return

        lats = {str(v.laterality or '').upper() for v in valid_views}
        vps = {str(v.view_position or '').upper() for v in valid_views}
        if len(lats) != 1 or vps != {'CC', 'MLO'}:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message(
                "دو ویوی انتخاب‌شده باید از یک طرف (R یا L) و شامل CC و MLO باشند.\n"
                "لطفاً ابتدا CC/MLO یک laterality را بارگذاری کنید."
            )
            return

        missing_manual = [f"{v.laterality}-{v.view_position}" for v in valid_views if v.manual_nipple_px is None]
        if missing_manual:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message(f"نقطه nipple برای ویوهای زیر ثبت نشده: {', '.join(missing_manual)}")
            return

        # Run correlator
        correlator = CursorCorrelator3D()
        result = correlator.correlate(valid_views)

        if result.total_cursors == 0:
            self.set_processing_status("3D Cursor Complete", active=False)
            show_message(
                "No 3D cursor correlations found.\n"
                "Ensure both CC and MLO views have detected lesions."
            )
            return

        # Display text summary
        summary_text = format_3d_cursor_summary(result)
        self.feature_view.setPlainText(summary_text)

        # Draw projected boxes/rulers on the same selected views only
        views_by_key = {f"{v.laterality}_{v.view_position}": v for v in valid_views}
        try:
            draw_3d_cursor_results(result, views_by_key)
        except Exception as e:
            print(f"[3D-Cursor] Drawing failed (non-critical): {e}")

        self.set_processing_status("3D Cursor Complete", active=False)
        QMessageBox.information(self, "3D Cursor - CC/MLO Correlation", summary_text)

    def _run_3d_cursor_analysis(self):
        """Execute the 3D cursor correlation using mm-based geometry."""
        from modules.ai_imaging.ai_module_ui.cursor_3d import CursorCorrelator3D
        from modules.ai_imaging.ai_module_ui.cursor_3d.visualization import (
            draw_3d_cursor_results,
            format_3d_cursor_summary,
        )

        # Collect view data from viewer widgets or CSV fallback
        view_data_list = self._collect_views_for_3d_cursor()

        if not view_data_list:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message(
                "No view data available for 3D Cursor.\n"
                "Ensure AI detection has been run and both CC/MLO views are loaded.\n"
                "DICOM Pixel Spacing metadata is required for mm-based analysis."
            )
            return

        # Filter views that have valid pixel spacing (required for mm-based computation)
        valid_views = [v for v in view_data_list
                       if v.pixel_spacing_x and v.pixel_spacing_x > 0
                       and v.pixel_spacing_y and v.pixel_spacing_y > 0]

        if not valid_views:
            self.set_processing_status("3D Cursor Failed", active=False)
            show_message(
                "DICOM Pixel Spacing metadata is missing for all views.\n"
                "3D Cursor requires physical measurements (mm) and cannot operate "
                "without Pixel Spacing.\n\n"
                "This is resolution-independent - all calculations use millimeters."
            )
            return

        # Run correlator
        correlator = CursorCorrelator3D()
        result = correlator.correlate(valid_views)

        if result.total_cursors == 0:
            self.set_processing_status("3D Cursor Complete", active=False)
            show_message(
                "No 3D cursor correlations found.\n"
                "Ensure both CC and MLO views have detected lesions, "
                "or at least one view has a lesion and the other view is available."
            )
            return

        # Display text summary
        summary_text = format_3d_cursor_summary(result)
        self.feature_view.setPlainText(summary_text)

        # Draw projected boxes on viewer widgets
        views_by_key = {f"{v.laterality}_{v.view_position}": v for v in valid_views}
        try:
            draw_3d_cursor_results(result, views_by_key)
        except Exception as e:
            print(f"[3D-Cursor] Drawing failed (non-critical): {e}")

        self.set_processing_status("3D Cursor Complete", active=False)
        QMessageBox.information(self, "3D Cursor - CC/MLO Correlation", summary_text)

    def _collect_views_for_3d_cursor(self) -> list:
        """
        Collect view data from viewer widgets or CSV fallback.
        Returns a list of ViewData objects for the correlator.
        """
        views = self._collect_views_from_widgets()
        if not views:
            views = self._collect_views_from_csv_fallback()
        return views

    def _collect_views_from_widgets(self) -> list:
        """Collect ViewData from active viewer widgets."""
        data = []
        pw = getattr(self, 'patient_widget', None)
        if pw is None:
            return data

        vtk_widgets = []
        nodes = getattr(pw, 'lst_nodes_viewer', None) or []
        for node in nodes:
            w = getattr(node, 'vtk_widget', None)
            if w is not None:
                vtk_widgets.append(w)
        node_viewers = getattr(pw, 'lst_node_viewers', None) or []
        for node in node_viewers:
            w = getattr(node, 'widget', None)
            if w is not None and w not in vtk_widgets:
                vtk_widgets.append(w)

        for vtk_widget in vtk_widgets:
            vd = self._extract_view_data_from_widget(vtk_widget)
            if vd is not None:
                data.append(vd)

        return data

    def _extract_view_data_from_widget(self, vtk_widget) -> 'Optional[object]':
        """Extract ViewData from a single vtk_widget."""
        from modules.ai_imaging.ai_module_ui.cursor_3d.correlator import ViewData

        laterality = ''
        view_position = ''
        dicom_path = ''

        # Read from image_viewer metadata
        try:
            iv = getattr(vtk_widget, 'image_viewer', None)
            if iv:
                meta = getattr(iv, 'metadata', {}) or {}
                series_meta = meta.get('series', {})
                laterality = str(series_meta.get('laterality', '') or '').upper()
                view_position = str(series_meta.get('view_position', '') or '').upper()
                instances = meta.get('instances', [])
                if instances and isinstance(instances, list):
                    inst = instances[0]
                    if isinstance(inst, dict):
                        dicom_path = str(inst.get('instance_path', '') or '')
        except Exception:
            pass

        # Read boxes from CSV
        boxes = []
        scores = []
        csv_path = getattr(vtk_widget, 'csv_details_path', None)
        if csv_path and os.path.isfile(str(csv_path)):
            try:
                df = read_csv_table(str(csv_path))
                all_rows = []
                if hasattr(vtk_widget, 'get_series_ai_data_from_df'):
                    series_data = vtk_widget.get_series_ai_data_from_df(df, check_all_rows=True)
                    if series_data is not None:
                        if isinstance(series_data, list):
                            for tbl in series_data:
                                if hasattr(tbl, 'rows'):
                                    all_rows.extend(tbl.rows)
                        elif hasattr(series_data, 'rows') and series_data.rows:
                            all_rows = series_data.rows
                    if not all_rows:
                        series_data_single = vtk_widget.get_series_ai_data_from_df(df, check_all_rows=False)
                        if series_data_single is not None:
                            if isinstance(series_data_single, list):
                                for tbl in series_data_single:
                                    if hasattr(tbl, 'rows'):
                                        all_rows.extend(tbl.rows)
                            elif hasattr(series_data_single, 'rows') and series_data_single.rows:
                                all_rows = series_data_single.rows

                for row_data in all_rows:
                    if not dicom_path:
                        dicom_path = str(row_data.get('dicom_full_path', '') or '')
                    box_val = row_data.get('box', '')
                    parsed_boxes = _parse_box_cell(box_val)
                    score_val = row_data.get('score', '0.5')
                    try:
                        score_f = float(score_val) if score_val else 0.5
                    except (ValueError, TypeError):
                        score_f = 0.5
                    for b in parsed_boxes:
                        boxes.append(b)
                        scores.append(score_f)
                    new_box_val = row_data.get('new_box', '')
                    for b in _parse_box_cell(new_box_val):
                        boxes.append(b)
                        scores.append(0.5)
            except Exception:
                pass

        # Read laterality/view from DICOM if not available from metadata
        if (not laterality or not view_position) and dicom_path and os.path.isfile(str(dicom_path)):
            try:
                import pydicom
                ds = pydicom.dcmread(str(dicom_path), stop_before_pixels=True, force=True)
                if not laterality:
                    lat_val = getattr(ds, 'ImageLaterality', None) or getattr(ds, 'Laterality', None) or ''
                    laterality = str(lat_val).upper().strip()
                if not view_position:
                    vp_val = getattr(ds, 'ViewPosition', None) or ''
                    view_position = str(vp_val).upper().strip()
            except Exception:
                pass

        if not laterality or not view_position:
            return None

        # Read pixel spacing and dimensions
        geom = _read_dicom_pixel_geometry(dicom_path)
        # Fallback: try VTK image data
        if geom['img_width'] is None or geom['img_height'] is None:
            try:
                iv = getattr(vtk_widget, 'image_viewer', None)
                if iv and getattr(iv, 'vtk_image_data', None):
                    dims = iv.vtk_image_data.GetDimensions()
                    if geom['img_width'] is None and dims[0] > 1:
                        geom['img_width'] = int(dims[0])
                    if geom['img_height'] is None and dims[1] > 1:
                        geom['img_height'] = int(dims[1])
                    if geom['pixel_spacing_x'] is None:
                        sp = iv.vtk_image_data.GetSpacing()
                        if sp[0] > 0:
                            geom['pixel_spacing_x'] = float(sp[0])
                        if sp[1] > 0:
                            geom['pixel_spacing_y'] = float(sp[1])
            except Exception:
                pass

        return ViewData(
            laterality=laterality,
            view_position=view_position,
            dicom_path=dicom_path,
            boxes_px=boxes,
            scores=scores,
            img_width=geom['img_width'],
            img_height=geom['img_height'],
            pixel_spacing_x=geom['pixel_spacing_x'],
            pixel_spacing_y=geom['pixel_spacing_y'],
            vtk_widget=vtk_widget,
        )

    def _collect_views_from_csv_fallback(self) -> list:
        """Collect ViewData directly from detection CSV (no viewer widgets)."""
        from modules.ai_imaging.ai_module_ui.cursor_3d.correlator import ViewData

        data = []
        csv_path = self._find_detection_csv_path()
        if not csv_path:
            return data

        try:
            df = read_csv_table(csv_path)
        except Exception:
            return data

        for row in df.rows:
            dicom_path = str(row.get('dicom_full_path', '') or '')
            laterality = str(row.get('laterality', '') or '').upper().strip()
            view_position = str(row.get('view_position', '') or '').upper().strip()

            if (not laterality or not view_position) and dicom_path and os.path.isfile(dicom_path):
                try:
                    import pydicom
                    ds = pydicom.dcmread(dicom_path, stop_before_pixels=True, force=True)
                    if not laterality:
                        lat_val = getattr(ds, 'ImageLaterality', None) or getattr(ds, 'Laterality', None) or ''
                        laterality = str(lat_val).upper().strip()
                    if not view_position:
                        vp_val = getattr(ds, 'ViewPosition', None) or ''
                        view_position = str(vp_val).upper().strip()
                except Exception:
                    continue

            if not laterality or not view_position:
                continue

            boxes = []
            scores = []
            for b in _parse_box_cell(row.get('box', '')):
                boxes.append(b)
                score_val = row.get('score', '0.5')
                try:
                    scores.append(float(score_val) if score_val else 0.5)
                except (ValueError, TypeError):
                    scores.append(0.5)

            geom = _read_dicom_pixel_geometry(dicom_path)

            data.append(ViewData(
                laterality=laterality,
                view_position=view_position,
                dicom_path=dicom_path,
                boxes_px=boxes,
                scores=scores,
                img_width=geom['img_width'],
                img_height=geom['img_height'],
                pixel_spacing_x=geom['pixel_spacing_x'],
                pixel_spacing_y=geom['pixel_spacing_y'],
                vtk_widget=None,
            ))

        return data

    def _find_detection_csv_path(self) -> Optional[str]:
        """Find the AI detection CSV path from available sources."""
        pw = getattr(self, 'patient_widget', None)
        if pw:
            nodes = getattr(pw, 'lst_nodes_viewer', None) or []
            for node in nodes:
                w = getattr(node, 'vtk_widget', None)
                if w and getattr(w, 'csv_details_path', None):
                    p = str(w.csv_details_path)
                    if os.path.isfile(p):
                        return p
            node_viewers = getattr(pw, 'lst_node_viewers', None) or []
            for node in node_viewers:
                w = getattr(node, 'widget', None)
                if w and getattr(w, 'csv_details_path', None):
                    p = str(w.csv_details_path)
                    if os.path.isfile(p):
                        return p

        if self.study_uid:
            try:
                from PacsClient.utils.utils import load_mg_ai_manifest
                det_csv, _ = load_mg_ai_manifest(
                    study_uid=self.study_uid,
                    attachments_path=ATTACHMENT_PATH,
                )
                if det_csv and os.path.isfile(str(det_csv)):
                    return str(det_csv)
            except Exception:
                pass

            default = ATTACHMENT_PATH / self.study_uid / 'updated_csv_with_boxes.csv'
            if default.exists():
                return str(default)

        return None

    def home_layout(self):
        layout = QHBoxLayout()

        import_btn = QPushButton('Import Folder')
        import_btn.clicked.connect(self.toggle_import_folder)
        layout.addWidget(import_btn)

        export_file_btn = QPushButton('Export File')
        layout.addWidget(export_file_btn)

        save_workstation_btn = QPushButton('Save Workstation')
        layout.addWidget(save_workstation_btn)

        return layout

    def toggle_import_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select DICOM Folder", "")
        if folder:
            print('folder is:', folder)

    # ---------- Segment row ----------
    def segment_layout(self):
        layout = QHBoxLayout()
        polygon_btn = QPushButton('Polygon')
        polygon_btn.setCheckable(True)
        polygon_btn.clicked.connect(lambda: self.toggle_tool(self.tool_access.POLYGON_SEGMENTATION))
        layout.addWidget(polygon_btn)
        return layout

    def toggle_tool(self, tool_name):
        if hasattr(self.patient_widget, 'lst_nodes_viewer') and self.patient_widget.lst_nodes_viewer:
            main_vtk_widget = self.patient_widget.lst_nodes_viewer[0].vtk_widget
            self.patient_widget.toolbar_manager.activate_tool(main_vtk_widget, tool_name)

    # ---------- Left sidebar ----------
    def left_sidebar_layout_ui(self):
        """
        Initialize modality-specific sidebar with safe signal handling.
        """
        # Ù¾Ø§Ú© Ú©Ø±Ø¯Ù† Ø³Ø§ÛŒØ¯Ø¨Ø§Ø± Ù‚Ø¨Ù„ÛŒ
        if self.current_sidebar:
            self.current_sidebar.setParent(None)
            self.current_sidebar.deleteLater()
            self.current_sidebar = None

        modality = self.detect_modality()

        if modality == "DX":
            self.current_sidebar = DXSidebar(
                parent=self.left_sidebar_widget,
                study_uid=self.study_uid,
                imaging_tab=self
            )
        else:
            # MG (default)
            self.current_sidebar = MGSidebar(
                parent=self.left_sidebar_widget,
                study_uid=self.study_uid,
                imaging_tab=self
            )
            
            # Ù…Ø¯ÛŒØ±ÛŒØª Ø§Ù…Ù† Ø³ÛŒÚ¯Ù†Ø§Ù„â€ŒÙ‡Ø§
            try:
                # Ø±ÙØ¹ Ø§ØªØµØ§Ù„Ø§Øª Ù‚Ø¨Ù„ÛŒ (Ø§Ú¯Ø± ÙˆØ¬ÙˆØ¯ Ø¯Ø§Ø´ØªÙ‡ Ø¨Ø§Ø´Ø¯)
                if hasattr(self.mg_runs_combo, '_mg_signal_connected') and self.mg_runs_combo._mg_signal_connected:
                    self.mg_runs_combo.currentIndexChanged.disconnect(self._on_mg_run_changed)
                    self.mg_runs_combo._mg_signal_connected = False
            except (TypeError, RuntimeError, AttributeError) as e:
                # Ù‡ÛŒÚ† Ø§ØªØµØ§Ù„ÛŒ ÙˆØ¬ÙˆØ¯ Ù†Ø¯Ø§Ø±Ø¯ ÛŒØ§ widget Ù†Ø§Ù…Ø¹ØªØ¨Ø± Ø§Ø³Øª
                print(f"Info: No previous connection to disconnect: {e}")
            
            # Ø§ØªØµØ§Ù„ Ø³ÛŒÚ¯Ù†Ø§Ù„ Ø¬Ø¯ÛŒØ¯
            try:
                self.mg_runs_combo.currentIndexChanged.connect(self._on_mg_run_changed)
                self.mg_runs_combo._mg_signal_connected = True
            except (RuntimeError, TypeError) as e:
                print(f"Error connecting signal: {e}")
                self.mg_runs_combo._mg_signal_connected = False
            
            # Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ø¯Ø§Ø¯Ù‡â€ŒÙ‡Ø§ÛŒ MG Ø§Ú¯Ø± Ù‚Ø¨Ù„Ø§Ù‹ Ø¨Ø§Ø±Ú¯Ø°Ø§Ø±ÛŒ Ù†Ø´Ø¯Ù‡ Ø¨Ø§Ø´Ø¯
            if not self.mg_runs_loaded:
                QTimer.singleShot(50, self._load_mg_runs_into_dropdown)
        
        # Ù¾Ø§Ú© Ú©Ø±Ø¯Ù† layout Ù‚Ø¨Ù„ÛŒ
        while self.left_sidebar_layout.count():
            child = self.left_sidebar_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.left_sidebar_layout.addWidget(self.current_sidebar)

    # ---------- CSV update ----------
    def update_csv(self, csv_path, row):
        print('csv_path:', csv_path)
        print('series:', row)

        key = self.lst_boxes_combo.currentText().strip()
        if not key or key not in self._sidebar_store:
            show_message("Please select a box.")
            return

        data_selected = self._sidebar_store[key]
        status = self.rb_abnormal.isChecked()
        box_object: BoxManager = data_selected.get('box_object', None)
        if box_object:
            corner_ijk_points = box_object.ijk_points
        else:
            csv_box = data_selected.get('csv_box', None)
            if isinstance(csv_box, (list, tuple)) and len(csv_box) == 4:
                corner_ijk_points = [float(v) for v in csv_box]
            else:
                show_message("Box object not found.")
                return

        print('status:', status)
        print('corner_ijk_points:', corner_ijk_points)
        update_csv(csv_path=csv_path, row=row, status=status, corner_ijk_points=corner_ijk_points)

        try:
            row_data = row.rows[0] if hasattr(row, 'rows') and row.rows else {}
            corrected_status = "abnormal" if status else "normal"
            corrected_classification = data_selected.get('classification', [])
            mammography_fields = self._collect_mg_review_fields()
            data_selected.update(mammography_fields)
            review_metadata = {
                'validation_status': self.validation_combo.currentText().strip() or 'reviewed',
                'reviewer_id': self.reviewer_edit.text().strip(),
                'correction_notes': self.notes_edit.toPlainText().strip(),
                'export_status': 'local_only',
                'server_sync_status': 'not_synced',
            }
            write_mg_feedback_csv(
                self.study_uid,
                ATTACHMENT_PATH / self.study_uid,
                str(csv_path),
                row_data,
                selected_box=corner_ijk_points,
                corrected_status=corrected_status,
                corrected_classification=corrected_classification,
                review_metadata=review_metadata,
                mammography_fields=mammography_fields,
            )
        except Exception as e:
            print(f"[MG] failed to save feedback CSV: {e}")

        show_message('updated')

    # ---------- Helpers ----------
    def _normalize_status(self, value):
        """ÙˆØ±ÙˆØ¯ÛŒâ€ŒÙ‡Ø§ÛŒ Ù…Ø®ØªÙ„Ù Ø±Ø§ Ø¨Ù‡ 0/1 ØªØ¨Ø¯ÛŒÙ„ Ù…ÛŒâ€ŒÚ©Ù†Ø¯: 1=abnormal, 0=normal"""
        if isinstance(value, str):
            v = value.strip().lower()
            return 1 if v in ("abnormal", "abn", "1", "true", "yes", "y") else 0
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if int(value) != 0 else 0
        return 0

    def _on_class_selection_changed(self, items: list[str]):
        """Ø¨Ø§ ØªØºÛŒÛŒØ± Ø§Ù†ØªØ®Ø§Ø¨Ù Ú©Ù„Ø§Ø³â€ŒÙ‡Ø§ØŒ Ø§Ø³ØªÙˆØ± ÙØ¹Ù„ÛŒ Ø¨Ù‡â€ŒØ±ÙˆØ²Ø±Ø³Ø§Ù†ÛŒ Ù…ÛŒâ€ŒØ´ÙˆØ¯."""
        key = self.lst_boxes_combo.currentText().strip()
        if not key:
            return
        entry = self._sidebar_store.get(key, {})
        entry["classification"] = list(items)  # Ø°Ø®ÛŒØ±Ù‡ Ø¨Ù‡ ØµÙˆØ±Øª Ù„ÛŒØ³Øª
        self._sidebar_store[key] = entry

    def _combo_set_text(self, combo: QComboBox, value: str):
        value = str(value or "")
        idx = combo.findText(value)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _collect_mg_review_fields(self) -> dict:
        key = self.lst_boxes_combo.currentText().strip()
        entry = self._sidebar_store.get(key, {}) if key else {}
        finding_uid = entry.get("finding_uid") or key
        return {
            "finding_uid": finding_uid,
            "laterality": self.laterality_combo.currentText().strip(),
            "view": self.view_combo.currentText().strip(),
            "lesion_type": self.lesion_type_combo.currentText().strip(),
            "location": self.location_edit.text().strip(),
            "quadrant": self.quadrant_combo.currentText().strip(),
            "clock_position": self.clock_edit.text().strip(),
            "depth": self.depth_combo.currentText().strip(),
            "birads_category": self.birads_combo.currentText().strip(),
            "confidence": self.confidence_edit.text().strip(),
            "human_action": self.human_action_combo.currentText().strip() or "update",
        }

    def _load_mg_review_fields(self, entry: dict | None):
        entry = entry or {}
        self._combo_set_text(self.laterality_combo, entry.get("laterality", ""))
        self._combo_set_text(self.view_combo, entry.get("view", ""))
        self._combo_set_text(self.lesion_type_combo, entry.get("lesion_type", ""))
        self.location_edit.setText(str(entry.get("location", "") or ""))
        self._combo_set_text(self.quadrant_combo, entry.get("quadrant", ""))
        self.clock_edit.setText(str(entry.get("clock_position", "") or ""))
        self._combo_set_text(self.depth_combo, entry.get("depth", ""))
        self._combo_set_text(self.birads_combo, entry.get("birads_category", ""))
        self.confidence_edit.setText(str(entry.get("confidence", "") or ""))
        self._combo_set_text(self.human_action_combo, entry.get("human_action", "update"))

    def _current_mg_box_points(self):
        key = self.lst_boxes_combo.currentText().strip()
        if not key or key not in self._sidebar_store:
            return None
        data_selected = self._sidebar_store[key]
        box_object: BoxManager = data_selected.get('box_object', None)
        if box_object:
            return box_object.ijk_points
        csv_box = data_selected.get('csv_box', None)
        if isinstance(csv_box, (list, tuple)) and len(csv_box) == 4:
            return [float(v) for v in csv_box]
        return None

    def _on_new_mg_finding_clicked(self):
        if self.detect_modality() == "DX":
            return
        selected_widget = getattr(self.patient_widget, "selected_widget", None)
        if selected_widget is None and getattr(self.patient_widget, "lst_nodes_viewer", None):
            selected_widget = getattr(self.patient_widget.lst_nodes_viewer[0], "vtk_widget", None)
            try:
                self.patient_widget.set_viewer_to_main_viewer(self.patient_widget.lst_nodes_viewer[0])
            except Exception:
                pass
        if selected_widget is None:
            show_message("Open a mammography image before creating a new finding.")
            return

        self._pending_mg_new_finding = True
        self.finding_status_display.setText("Status: Draw new finding polygon")
        self.finding_summary_label.setText("Place four polygon points on the image.")

        try:
            self.patient_widget.toolbar_manager.turn_off_all_tools()
            self.patient_widget.toolbar_manager.activate_tool(selected_widget, self.tool_access.POLYGON_SEGMENTATION)
            style = getattr(selected_widget, "current_style", None)
            if style is not None:
                style.on_polygon_finished = self._on_mg_new_polygon_finished
        except Exception as e:
            self._pending_mg_new_finding = False
            show_message(f"Could not activate polygon tool: {e}")

    def _bbox_from_polygon_ijk(self, ijk_points):
        points = list(ijk_points or [])
        if len(points) >= 2 and all(
            abs(float(points[-1][d]) - float(points[0][d])) < 1e-6
            for d in range(min(3, len(points[0]), len(points[-1])))
        ):
            points = points[:-1]
        if len(points) != 4:
            return None
        xs = [float(p[0]) for p in points]
        ys = [float(p[1]) for p in points]
        return [min(xs), min(ys), max(xs), max(ys)]

    def _next_human_finding_number(self):
        max_seen = 0
        for key in self._sidebar_store:
            text = str(key or "")
            if text.startswith("Human Finding "):
                try:
                    max_seen = max(max_seen, int(text.rsplit(" ", 1)[-1]))
                except Exception:
                    pass
        return max_seen + 1

    def _on_mg_new_polygon_finished(self, pts_world, ijk_points, contour_widget):
        if not getattr(self, "_pending_mg_new_finding", False):
            return False
        bbox = self._bbox_from_polygon_ijk(ijk_points)
        if bbox is None:
            show_message("New mammography finding requires exactly four polygon points.")
            return True

        self._pending_mg_new_finding = False
        count = self._next_human_finding_number()
        key = f"Human Finding {count}"
        finding_uid = f"{self.study_uid}:human:{count}"

        try:
            csv_path, row = self._resolve_active_mg_csv_and_row()
            row_data = row.rows[0] if hasattr(row, 'rows') and row.rows else {}
            source_row_key = row_data.get("dicom_full_path", "")
        except Exception:
            source_row_key = ""

        self.sidebar_upsert_item(
            key=key,
            status=1,
            classification=[],
            features="",
            select=True,
            box_object=None,
            csv_box=bbox,
            mammography_fields={
                "finding_uid": finding_uid,
                "human_action": "new_finding",
                "source_kind": "human_polygon",
                "source_row_key": source_row_key,
                "source_box_index": count - 1,
                "polygon_ijk_points": [list(p) for p in ijk_points],
                "polygon_world_points": [list(p) for p in pts_world],
            },
        )
        self.rb_abnormal.setChecked(True)
        self._combo_set_text(self.human_action_combo, "new_finding")
        QTimer.singleShot(0, lambda: self._open_mg_finding_editor("new_human_finding"))
        return True

    def _active_mg_classification_columns(self):
        try:
            selected = getattr(self.patient_widget, 'selected_widget', None)
            vtk_widget = getattr(selected, 'vtk_widget', selected)
            cls_path = getattr(vtk_widget, 'csv_classification', None)
            if not cls_path or not hasattr(vtk_widget, 'load_csv'):
                return []
            df_cls = vtk_widget.load_csv(cls_path)
            return list(getattr(df_cls, 'columns', []) or []) if df_cls is not None else []
        except Exception:
            return []

    def _open_mg_finding_editor(self, action: str):
        if self.detect_modality() == "DX":
            return
        key = self.lst_boxes_combo.currentText().strip()
        if not key or key not in self._sidebar_store:
            show_message("Please select a finding.")
            return

        entry = self._sidebar_store.get(key, {})
        box_points = self._current_mg_box_points()
        normalized_action = normalize_mg_action(action)
        if normalized_action == "new_human_finding" and not box_points:
            show_message("Draw or select a new box before saving a new finding.")
            return

        try:
            csv_path, row = self._resolve_active_mg_csv_and_row()
            row_data = row.rows[0] if hasattr(row, 'rows') and row.rows else {}
            detection_columns = list(getattr(row, 'columns', []) or row_data.keys())
        except Exception:
            csv_path = ""
            row = None
            row_data = {}
            detection_columns = []

        ai_values = dict(row_data)
        classification = entry.get("classification")
        if isinstance(classification, list):
            ai_values["labels_pred"] = "|".join(str(v) for v in classification if str(v).strip())
        elif classification:
            ai_values["labels_pred"] = str(classification)
        ai_values.setdefault("box", str(box_points or entry.get("csv_box") or ""))

        contract = infer_mg_csv_contract(
            detection_columns=detection_columns,
            classification_columns=self._active_mg_classification_columns(),
        )
        dialog = MGFindingEditorDialog(
            self,
            title=f"{key} - {normalized_action.replace('_', ' ').title()}",
            contract=contract,
            ai_values=ai_values,
            corrected_values=entry,
            box_points=box_points,
            action=normalized_action,
            validation_status=entry.get("validation_status") or normalized_action,
            reviewer_id=entry.get("reviewer_id") or self._default_reviewer_id(),
            notes=entry.get("correction_notes", ""),
        )
        if dialog.exec() != QDialog.Accepted:
            return

        data = dialog.result_data()
        self._save_mg_editor_result(
            key=key,
            action=data["action"],
            dialog_data=data,
            csv_path=csv_path,
            row=row,
            row_data=row_data,
            box_points=box_points,
        )

    def _save_mg_editor_result(self, *, key, action, dialog_data, csv_path, row, row_data, box_points):
        normalized_action = normalize_mg_action(action)
        entry = self._sidebar_store.get(key, {})
        mandatory = dict(dialog_data.get("mandatory") or {})
        optional = dict(dialog_data.get("optional") or {})

        label_value = mandatory.get("labels_pred") or optional.get("lesion_type") or ""
        corrected_classification = [label_value] if label_value else entry.get("classification", [])
        corrected_status = "normal" if normalized_action == "rejected" else "abnormal"

        mammography_fields = {
            **optional,
            "finding_uid": entry.get("finding_uid") or f"{self.study_uid}:{key}",
            "human_action": normalized_action,
            "source_kind": entry.get("source_kind"),
            "source_row_key": entry.get("source_row_key"),
            "source_row_index": entry.get("source_row_index"),
            "source_box_index": entry.get("source_box_index"),
            "polygon_ijk_points": entry.get("polygon_ijk_points"),
            "polygon_world_points": entry.get("polygon_world_points"),
        }
        review_metadata = {
            "validation_status": dialog_data.get("validation_status") or normalized_action,
            "reviewer_id": dialog_data.get("reviewer_id") or "",
            "correction_notes": dialog_data.get("correction_notes") or "",
            "export_status": "local_only",
            "server_sync_status": "not_synced",
        }

        if row is not None and csv_path and box_points and normalized_action in ("rejected", "new_human_finding"):
            try:
                update_csv(
                    csv_path=csv_path,
                    row=row,
                    status=(normalized_action != "rejected"),
                    corner_ijk_points=box_points,
                )
            except Exception as e:
                print(f"[MG] detection CSV update skipped: {e}")

        try:
            write_mg_feedback_csv(
                self.study_uid,
                ATTACHMENT_PATH / self.study_uid,
                str(csv_path or ""),
                row_data or {},
                selected_box=box_points,
                corrected_status=corrected_status,
                corrected_classification=corrected_classification,
                review_metadata=review_metadata,
                mammography_fields=mammography_fields,
            )
        except Exception as e:
            show_message(f"Failed to save mammography correction: {e}")
            return

        entry.update(optional)
        entry.update({
            "classification": corrected_classification,
            "validation_status": review_metadata["validation_status"],
            "reviewer_id": review_metadata["reviewer_id"],
            "correction_notes": review_metadata["correction_notes"],
            "human_action": normalized_action,
            "status": 0 if normalized_action == "rejected" else 1,
        })
        self._sidebar_store[key] = entry
        self.sidebar_load_current()
        show_message("Mammography finding saved")

    def _resolve_active_mg_csv_and_row(self):
        selected = getattr(self.patient_widget, 'selected_widget', None)
        vtk_widget = getattr(selected, 'vtk_widget', selected)

        if vtk_widget is None and hasattr(self.patient_widget, 'lst_nodes_viewer') and self.patient_widget.lst_nodes_viewer:
            first_node = self.patient_widget.lst_nodes_viewer[0]
            vtk_widget = getattr(first_node, 'vtk_widget', None)

        if vtk_widget is None:
            raise ValueError("No viewer available.")

        csv_path = getattr(vtk_widget, 'csv_details_path', None)
        if not csv_path:
            det_csv = None
            cls_csv = None

            try:
                if getattr(self, 'mg_runs_combo', None) is not None:
                    run_data = self.mg_runs_combo.currentData()
                    if isinstance(run_data, tuple) and len(run_data) >= 1:
                        det_csv = run_data[0]
                        cls_csv = run_data[1] if len(run_data) > 1 else None
            except Exception:
                pass

            if not det_csv:
                try:
                    run_info = load_mg_ai_runs(self.study_uid, ATTACHMENT_PATH) or {}
                    active = run_info.get("active", {}) if isinstance(run_info, dict) else {}
                    det_csv = active.get("detection") if isinstance(active, dict) else None
                    cls_csv = active.get("classification") if isinstance(active, dict) else None
                except Exception:
                    pass

            if det_csv:
                det_path = Path(det_csv)
                if not det_path.is_absolute():
                    det_path = ATTACHMENT_PATH / self.study_uid / det_csv

                cls_path = None
                if cls_csv:
                    cls_path = Path(cls_csv)
                    if not cls_path.is_absolute():
                        cls_path = ATTACHMENT_PATH / self.study_uid / cls_csv

                try:
                    if hasattr(vtk_widget, 'csv_details_path'):
                        vtk_widget.csv_details_path = det_path
                    if hasattr(vtk_widget, 'csv_classification'):
                        vtk_widget.csv_classification = cls_path
                    if hasattr(vtk_widget, '_csv_cache') and isinstance(vtk_widget._csv_cache, dict):
                        vtk_widget._csv_cache.clear()
                    if hasattr(vtk_widget, '_series_ai_cache') and isinstance(vtk_widget._series_ai_cache, dict):
                        vtk_widget._series_ai_cache.clear()
                except Exception:
                    pass

                csv_path = det_path

        if not csv_path:
            raise ValueError("CSV details not available in viewer.")

        if not hasattr(vtk_widget, 'load_csv') or not hasattr(vtk_widget, 'get_series_ai_data_from_df'):
            raise ValueError("Viewer does not support CSV apply.")

        df = vtk_widget.load_csv(csv_path)
        if df is None:
            raise ValueError("CSV file could not be loaded.")

        row = vtk_widget.get_series_ai_data_from_df(df)
        if row is None:
            raise ValueError("Current series row not found in CSV.")
        return csv_path, row

    def _on_save_mg_finding_clicked(self):
        if self.detect_modality() == "DX":
            return
        key = self.lst_boxes_combo.currentText().strip()
        if not key or key not in self._sidebar_store:
            show_message("Please select or create a finding.")
            return

        mammography_fields = self._collect_mg_review_fields()
        self._sidebar_store[key].update(mammography_fields)
        corner_ijk_points = self._current_mg_box_points()

        try:
            csv_path, row = self._resolve_active_mg_csv_and_row()
            row_data = row.rows[0] if hasattr(row, 'rows') and row.rows else {}
        except Exception:
            csv_path = ""
            row_data = {}

        corrected_status = "abnormal" if self.rb_abnormal.isChecked() else "normal"
        corrected_classification = self.class_combo.checkedItems()
        review_metadata = {
            'validation_status': self.validation_combo.currentText().strip() or 'reviewed',
            'reviewer_id': self.reviewer_edit.text().strip(),
            'correction_notes': self.notes_edit.toPlainText().strip(),
            'export_status': 'local_only',
            'server_sync_status': 'not_synced',
        }
        try:
            write_mg_feedback_csv(
                self.study_uid,
                ATTACHMENT_PATH / self.study_uid,
                str(csv_path),
                row_data,
                selected_box=corner_ijk_points,
                corrected_status=corrected_status,
                corrected_classification=corrected_classification,
                review_metadata=review_metadata,
                mammography_fields=mammography_fields,
            )
            show_message("Mammography finding saved")
        except Exception as e:
            show_message(f"Failed to save mammography finding: {e}")

    # ---------- Sidebar Store API ----------
    def sidebar_upsert_item(
            self, *,
            key: str,
            status=None,
            classification: list[str] | None = None,
            features=None,
            select: bool = True,
            box_object: BoxManager = None,
            csv_box: list[float] | None = None,
            mammography_fields: dict | None = None,
    ):
        """
        Add / update MG sidebar item.
        DX modality ignores this method.
        """

        # ðŸš« DX isolation
        if self.detect_modality() == "DX":
            return

        key = (key or "").strip()
        if not key:
            return

        if self.lst_boxes_combo.findText(key, Qt.MatchExactly) < 0:
            self.lst_boxes_combo.addItem(key)

        entry = self._sidebar_store.get(key, {})

        if status is not None:
            entry["status"] = self._normalize_status(status)

        if classification is not None:
            # A classification may arrive as a list or as a single bare string;
            # normalize both to a clean list of non-empty strings.
            if isinstance(classification, str):
                entry["classification"] = (
                    [classification.strip()] if classification.strip() else []
                )
            elif isinstance(classification, (list, tuple)):
                entry["classification"] = [
                    str(c).strip() for c in classification if str(c).strip()
                ]
            else:
                entry["classification"] = []

        if features is not None:
            if isinstance(features, (list, tuple)):
                entry["features"] = "\n".join(str(x) for x in features)
            else:
                entry["features"] = str(features)

        if csv_box is not None:
            try:
                if isinstance(csv_box, (list, tuple)) and len(csv_box) == 4:
                    entry["csv_box"] = [float(v) for v in csv_box]
            except Exception:
                pass

        if mammography_fields:
            entry.update({k: v for k, v in mammography_fields.items() if v is not None})

        entry.setdefault("validation_status", "pending_review")
        entry.setdefault("reviewer_id", self._default_reviewer_id())
        entry.setdefault("correction_notes", "")
        entry.setdefault("human_action", "update")

        entry["box_object"] = box_object
        self._sidebar_store[key] = entry

        if select:
            self.lst_boxes_combo.setCurrentText(key)
            self.sidebar_load_current()

    def sidebar_load_current(self):
        """
        Load current sidebar state.
        For DX modality, this method must do nothing.
        """

        # ðŸš« DX isolation
        if self.detect_modality() == "DX":
            return

        key = self.lst_boxes_combo.currentText().strip()
        entry = self._sidebar_store.get(key, None)

        # defaults
        status_val = 0
        cls_list: list[str] = []
        features_text = ""

        if entry:
            status_val = self._normalize_status(entry.get("status", 0))

            cls_raw = entry.get("classification", [])
            if isinstance(cls_raw, list):
                cls_list = [str(x).strip() for x in cls_raw if str(x).strip()]
            elif isinstance(cls_raw, str) and cls_raw.strip():
                cls_list = [cls_raw.strip()]

            features_text = entry.get("features", "")

            validation_status = str(entry.get("validation_status", "pending_review") or "pending_review")
            idx = self.validation_combo.findText(validation_status)
            self.validation_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.reviewer_edit.setText(str(entry.get("reviewer_id") or self._default_reviewer_id() or ""))
            self.notes_edit.setPlainText(str(entry.get("correction_notes") or ""))
            self._load_mg_review_fields(entry)
            validation_text = str(entry.get("validation_status") or entry.get("human_action") or "pending")
            self.finding_status_display.setText(f"Status: {validation_text}")
            summary_parts = []
            if cls_list:
                summary_parts.append("AI/Label: " + ", ".join(cls_list))
            if entry.get("csv_box"):
                summary_parts.append("Box: " + str(entry.get("csv_box")))
            if entry.get("human_action"):
                summary_parts.append("Action: " + str(entry.get("human_action")))
            self.finding_summary_label.setText("\n".join(summary_parts))
        else:
            idx = self.validation_combo.findText("pending_review")
            self.validation_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.reviewer_edit.setText(self._default_reviewer_id())
            self.notes_edit.clear()
            self._load_mg_review_fields({})
            self.finding_status_display.setText("Status: Pending")
            self.finding_summary_label.clear()

        # Status
        if status_val == 1:
            self.rb_abnormal.setChecked(True)
        else:
            self.rb_normal.setChecked(True)

        # Classification
        base_items = ["No Finding", "Mass", "Suspicious Calcification", "Focal Asymmetry"]
        self.class_combo.addItemsCheckable(base_items)
        self.class_combo.setCheckedItems(cls_list)

        # Features
        self.feature_view.setPlainText(features_text)

    def sidebar_clear(self, reset_items: bool = True):
        """
        Clear MG sidebar.
        DX modality ignores this method.
        """

        # ðŸš« DX isolation
        if self.detect_modality() == "DX":
            return

        self.rb_normal.setChecked(True)
        self.rb_abnormal.setChecked(False)

        self.lst_boxes_combo.clear()

        base_items = ["No Finding", "Mass", "Suspicious Calcification", "Focal Asymmetry"]
        self.class_combo.addItemsCheckable(base_items)
        self.class_combo.setCheckedItems([])

        self.feature_view.clear()
        idx = self.validation_combo.findText("pending_review")
        self.validation_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.reviewer_edit.setText(self._default_reviewer_id())
        self.notes_edit.clear()
        self._load_mg_review_fields({})
        self.finding_status_display.setText("Status: Pending")
        self.finding_summary_label.clear()

        if reset_items:
            self._sidebar_store.clear()

    def _default_reviewer_id(self) -> str:
        try:
            auth_user = getattr(self.window(), 'auth_user', None)
            if isinstance(auth_user, dict):
                return str(auth_user.get('username') or auth_user.get('full_name') or '').strip()
        except Exception:
            pass
        return ""

    def _on_apply_clicked(self):
        """
        Apply MG changes to active CSV.
        """

        #  DX isolation
        if self.detect_modality() == "DX":
            return

        if not self.patient_widget:
            return

        # Resolve active CSV and row from the currently selected AI viewer.
        try:
            selected = getattr(self.patient_widget, 'selected_widget', None)
            vtk_widget = getattr(selected, 'vtk_widget', selected)

            if vtk_widget is None and hasattr(self.patient_widget, 'lst_nodes_viewer') and self.patient_widget.lst_nodes_viewer:
                first_node = self.patient_widget.lst_nodes_viewer[0]
                vtk_widget = getattr(first_node, 'vtk_widget', None)

            if vtk_widget is None:
                show_message("No viewer available.")
                return

            csv_path = getattr(vtk_widget, 'csv_details_path', None)
            if not csv_path:
                # Fallback: recover active CSV from MG run selection/manifest and apply it to the current viewer.
                det_csv = None
                cls_csv = None

                try:
                    if getattr(self, 'mg_runs_combo', None) is not None:
                        run_data = self.mg_runs_combo.currentData()
                        if isinstance(run_data, tuple) and len(run_data) >= 1:
                            det_csv = run_data[0]
                            cls_csv = run_data[1] if len(run_data) > 1 else None
                except Exception:
                    pass

                if not det_csv:
                    try:
                        run_info = load_mg_ai_runs(self.study_uid, ATTACHMENT_PATH) or {}
                        active = run_info.get("active", {}) if isinstance(run_info, dict) else {}
                        det_csv = active.get("detection") if isinstance(active, dict) else None
                        cls_csv = active.get("classification") if isinstance(active, dict) else None
                    except Exception:
                        pass

                if det_csv:
                    det_path = Path(det_csv)
                    if not det_path.is_absolute():
                        det_path = ATTACHMENT_PATH / self.study_uid / det_csv

                    cls_path = None
                    if cls_csv:
                        cls_path = Path(cls_csv)
                        if not cls_path.is_absolute():
                            cls_path = ATTACHMENT_PATH / self.study_uid / cls_csv

                    try:
                        if hasattr(vtk_widget, 'csv_details_path'):
                            vtk_widget.csv_details_path = det_path
                        if hasattr(vtk_widget, 'csv_classification'):
                            vtk_widget.csv_classification = cls_path
                        if hasattr(vtk_widget, '_csv_cache') and isinstance(vtk_widget._csv_cache, dict):
                            vtk_widget._csv_cache.clear()
                        if hasattr(vtk_widget, '_series_ai_cache') and isinstance(vtk_widget._series_ai_cache, dict):
                            vtk_widget._series_ai_cache.clear()
                    except Exception:
                        pass

                    csv_path = det_path

            if not csv_path:
                show_message("CSV details not available in viewer.")
                return

            if not hasattr(vtk_widget, 'load_csv') or not hasattr(vtk_widget, 'get_series_ai_data_from_df'):
                show_message("Viewer does not support CSV apply.")
                return

            df = vtk_widget.load_csv(csv_path)
            if df is None:
                show_message("CSV file could not be loaded.")
                return

            row = vtk_widget.get_series_ai_data_from_df(df)
            if row is None:
                show_message("Current series row not found in CSV.")
                return
        except Exception as e:
            show_message(f"CSV active not found: {str(e)}")
            return

        self.update_csv(csv_path, row)
