import ast
import csv
import math
import json
import threading
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, QEvent, QObject, QEventLoop
from PySide6.QtGui import QStandardItemModel, QStandardItem, QMovie
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QComboBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QListView, QLineEdit, QMainWindow, QMessageBox, QPushButton,
    QRadioButton, QSizePolicy, QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QListWidget,
    QProgressBar
)

from . import AbstractTab
from . import AIPatientWidget
from PacsClient.utils.config import CLINICAL_CSV_PATH, ATTACHMENT_PATH
from modules.viewer.interactor_styles import ToolAccess
from PacsClient.pacs.patient_tab.utils import BoxManager, show_message
from PacsClient.utils.utils import load_mg_ai_runs
from modules.ai_imaging.ai_module_ui.csv_table import read_csv_table

# ------------------------------ Custom Events ------------------------------

class _BoneAgeLoadedEvent(QEvent):
    """رویداد سفارشی برای انتقال داده‌های بارگذاری شده از ترد پس‌زمینه به ترد اصلی"""
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())
    
    def __init__(self, data: dict):
        super().__init__(_BoneAgeLoadedEvent.EVENT_TYPE)
        self.data = data


# ------------------------------ Box helpers ------------------------------

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
    # نرمال‌سازی: همیشه list[list[float]]
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

    # پیدا کردن ردیف هدف (بهتره با dicom_full_path)
    target_idx = None
    if "dicom_full_path" in row.columns:
        key = str(row["dicom_full_path"].iloc[0])
        hit = df.index[df["dicom_full_path"] == key].tolist()
        if hit:
            target_idx = hit[0]
    if target_idx is None:
        raise ValueError("ردیف هدف پیدا نشد؛ dicom_full_path لازم است.")

    # تضمین ستون‌ها + dtype object
    for col in ("box", "new_box", "removed"):
        if col not in df.columns:
            df[col] = ""
        if getattr(df[col], "dtype", object) != object:
            df[col] = df[col].astype(object)

    # پارس ستون‌ها
    boxes = _parse_box_cell(df.at[target_idx, "box"])
    new_boxes = _parse_box_cell(df.at[target_idx, "new_box"])
    removed = _parse_box_cell(df.at[target_idx, "removed"])

    cand = [float(x) for x in corner_ijk_points]  # [x0,y0,x1,y1]

    in_box = _contains(boxes, cand)
    in_new = _contains(new_boxes, cand)
    in_rem = _contains(removed, cand)

    if status:  # True (Abnormal) --> اگر در box و new_box نبود، به new_box اضافه
        if not in_box and not in_new:
            _append_unique(new_boxes, cand)
            _remove_if_exists(removed, cand)  # حذف از removed در صورت وجود
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

    # نوشتن به CSV (به صورت رشته)
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

    def __init__(self, parent, study_uid: str):
        super().__init__(parent, study_uid)
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

        self.layout.addWidget(title)
        self.layout.addWidget(self.feature_label)
        self.layout.addWidget(self.feature_list)
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

            # نمایش اطلاعات bone age
            years = data.get("predicted_bone_age_years")
            months = data.get("predicted_bone_age_months")
            sex = data.get("sex")

            if years is not None:
                self.feature_list.addItem(f"Bone Age (Years): {years}")
            if months is not None:
                self.feature_list.addItem(f"Bone Age (Months): {months}")
            if sex:
                self.feature_list.addItem(f"Sex: {sex}")

        except Exception as e:
            print(f"[DXSidebar] failed to load bone age: {e}")


# ------------------------------ Multi-select Combo ------------------------------

class CheckComboBox(QComboBox):
    """QComboBox با آیتم‌های چک‌باکسی (multi-select) و نمایش خلاصه انتخاب‌ها در خطِ ویرایش."""
    selectionChanged = Signal(list)  # emits list[str] of selected texts

    def __init__(self, parent=None, placeholder="Select..."):
        super().__init__(parent)
        self.setModel(QStandardItemModel(self))
        self.setView(QListView(self))
        self.view().pressed.connect(self._on_item_pressed)

        # نمایش متن داخل خود کامبو (فقط خواندنی)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().setPlaceholderText(placeholder)
        self.setInsertPolicy(QComboBox.NoInsert)

        # تلاش برای باز نگه داشتن پاپ‌آپ هنگام تیک‌زدن‌های پیاپی
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


# ------------------------------ Main Tab ------------------------------

class ImagingToolsTab(AbstractTab):
    # Signal emitted when tab is fully loaded and rendered
    fully_loaded = Signal()
    
    def __init__(self, study_uid: Optional[str] = None):
        super().__init__()
        self.tool_access = ToolAccess()
        self.study_uid = study_uid
        self._sidebar_store: dict[str, dict] = {}
        self.vtk_initialized = False
        self.current_sidebar = None
        self.mg_runs_loaded = False  # فلگ جدید برای مدیریت بارگذاری MG runs

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
            imaging_tab_ui=self
        )
        self.patient_widget_layout.addWidget(self.patient_widget)

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
        """حذف دکمه‌های غیرضروری از patient_widget"""
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
        """اجرای عملیات سنگین پس از نمایش UI اولیه"""
        # Patient widget is already visible, just finalize setup
        QTimer.singleShot(100, self._finalize_loading)
        
    def _finalize_loading(self):
        """Complete the loading process and emit ready signal."""
        # Process pending events to ensure full render
        QApplication.processEvents()
        QApplication.processEvents()
        
        # فعال‌سازی tab پیش‌فرض (فقط button style، بدون switch برای جلوگیری از لودینگ دوباره)
        if hasattr(self.patient_widget, 'btn_ai_module'):
            self.patient_widget.btn_ai_module.setChecked(True)
            # Don't call switch_right_panel here - it's already called and causes double loading
        
        # بارگذاری سایدبار
        QTimer.singleShot(150, self.left_sidebar_layout_ui)
        
        # بارگذاری داده‌های bone age
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

        self.mg_runs_label = QLabel("AI Results")
        self.mg_runs_combo = QComboBox()

        # -------- Apply
        self.apply_btn = QPushButton("Apply")

        # پایه‌ی classification (اگر بعداً override شد مشکلی نیست)
        base_classes = [
            "No Finding",
            "Mass",
            "Suspicious Calcification",
            "Focal Asymmetry",
        ]
        self.class_combo.addItemsCheckable(base_classes)
        self.class_combo.setCheckedItems([])
        self.apply_btn.clicked.connect(self._on_apply_clicked)

    def _load_mg_runs_into_dropdown(self):
        """بارگذاری داده‌های MG به صورت امن"""
        if not self.mg_runs_combo:
            return
            
        self.mg_runs_combo.blockSignals(True)
        self.mg_runs_combo.clear()

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
                
            self.mg_runs_loaded = True
        except Exception as e:
            print(f"Error loading MG runs: {e}")
            self.mg_runs_loaded = False
        finally:
            self.mg_runs_combo.blockSignals(False)

    def _load_bone_age_feature_if_exists(self):
        """
        بارگذاری داده‌های bone age به صورت غیرهمزمان
        """
        if not self.study_uid:
            QTimer.singleShot(0, lambda: self._update_bone_age_ui({}))
            return

        json_path = ATTACHMENT_PATH / self.study_uid / "bone_age.json"
        
        # تنظیم حالت لودینگ در UI
        if hasattr(self, "feature_view") and self.feature_view is not None:
            self.feature_view.setPlaceholderText("Loading bone age data...")
            self.feature_view.clear()
            self.feature_view.setEnabled(False)
        
        # اجرای بارگذاری در ترد جداگانه
        threading.Thread(
            target=self._load_bone_json_async,
            args=(json_path,),
            daemon=True
        ).start()

    def _load_bone_json_async(self, json_path: Path):
        """بارگذاری فایل JSON در ترد پس‌زمینه"""
        try:
            data = {}
            if json_path.exists():
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception as e:
            print(f"[DX] Failed to load bone_age.json: {e}")
            data = {"error": str(e)}
        
        # انتقال داده به ترد اصلی از طریق رویداد سفارشی
        QApplication.postEvent(self, _BoneAgeLoadedEvent(data))

    def customEvent(self, event: QEvent):
        """پردازش رویدادهای سفارشی"""
        if event.type() == _BoneAgeLoadedEvent.EVENT_TYPE:
            self._handle_bone_age_loaded(event)
            event.accept()
        else:
            super().customEvent(event)

    def _handle_bone_age_loaded(self, event: _BoneAgeLoadedEvent):
        """پردازش داده‌های bone age دریافت شده"""
        self._update_bone_age_ui(event.data)

    def _update_bone_age_ui(self, data: dict):
        """به‌روزرسانی UI با داده‌های bone age"""
        if not hasattr(self, "feature_view") or self.feature_view is None:
            return
            
        self.feature_view.setEnabled(True)
        
        if "error" in data:
            self.feature_view.setPlainText(f"Error loading bone age data:\n{data['error']}")
            return
            
        lines = []
        if sex := data.get("sex"):
            lines.append(f"Sex: {sex}")
            
        if age_years_val := data.get("predicted_bone_age_years"):
            try:
                # تبدیل سن اعشاری به سال + ماه با رُند به بالا
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
        """پردازش تغییر در انتخاب MG runs با مدیریت خطا"""
        if index < 0 or index >= self.mg_runs_combo.count():
            return
            
        data = self.mg_runs_combo.itemData(index)
        if not data or len(data) < 2:
            return

        det_csv, cls_csv = data[:2]  # فقط دو مقدار اول را در نظر بگیر

        try:
            # تأیید وجود اجزای لازم
            if not hasattr(self, 'patient_widget') or not self.patient_widget:
                print("[_on_mg_run_changed] Patient widget not available")
                return
                
            if not hasattr(self.patient_widget, 'selected_widget') or not self.patient_widget.selected_widget:
                print("[_on_mg_run_changed] No selected widget")
                return
                
            selected_widget = self.patient_widget.selected_widget
            if not hasattr(selected_widget, 'vtk_widget') or not selected_widget.vtk_widget:
                print("[_on_mg_run_changed] No vtk_widget")
                return
                
            vtk_widget = selected_widget.vtk_widget
            
            # import به صورت محلی برای جلوگیری از cyclic dependency
            from modules.viewer.interactor_styles.ai_chat_interactorstyle import AIChatInteractorStyle
            
            if not hasattr(vtk_widget, 'current_style') or not vtk_widget.current_style:
                print("[_on_mg_run_changed] No current_style")
                return
                
            interactor: AIChatInteractorStyle = vtk_widget.current_style
            
            # به‌روزرسانی manifest
            interactor._save_mg_manifest(self.study_uid, det_csv, cls_csv)

            # باز کردن ماژول AI
            interactor.open_ai_module()
            
        except Exception as e:
            error_msg = f"Error in MG run change: {str(e)}"
            print(error_msg)
            # نمایش پیام خطا به کاربر
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Error", error_msg)
            
    def _build_mg_sidebar_ui(self, layout: QVBoxLayout):
        """
        Build MG sidebar UI using pre-initialized widgets.
        """
        # پاک کردن layout قبلی
        while layout.count():
            child = layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        layout.addWidget(self.detail_box_label)
        layout.addWidget(self.lst_boxes_combo)

        layout.addWidget(self.status_label)
        layout.addWidget(self.status_group)

        layout.addWidget(self.classification_label)
        layout.addWidget(self.class_combo)

        layout.addWidget(self.feature_label)
        layout.addWidget(self.feature_view)

        # 🔽 MG AI runs dropdown
        layout.addWidget(self.mg_runs_label)
        layout.addWidget(self.mg_runs_combo)

        layout.addWidget(self.apply_btn)
        layout.addStretch()

    def detect_modality(self) -> str:
        """
        Detect modality based on available AI results.
        """
        study_uid = self.study_uid

        # DX if bone age result exists
        bone_json = ATTACHMENT_PATH / study_uid / "bone_age.json"
        if bone_json.exists():
            return "DX"

        # MG default
        return "MG"

    # ---------- Home row ----------
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
        # پاک کردن سایدبار قبلی
        if self.current_sidebar:
            self.current_sidebar.setParent(None)
            self.current_sidebar.deleteLater()
            self.current_sidebar = None

        modality = self.detect_modality()

        if modality == "DX":
            self.current_sidebar = DXSidebar(
                parent=self.left_sidebar_widget,
                study_uid=self.study_uid
            )
        else:
            # MG (default)
            self.current_sidebar = MGSidebar(
                parent=self.left_sidebar_widget,
                study_uid=self.study_uid,
                imaging_tab=self
            )
            
            # مدیریت امن سیگنال‌ها
            try:
                # رفع اتصالات قبلی (اگر وجود داشته باشد)
                if hasattr(self.mg_runs_combo, '_mg_signal_connected') and self.mg_runs_combo._mg_signal_connected:
                    self.mg_runs_combo.currentIndexChanged.disconnect(self._on_mg_run_changed)
                    self.mg_runs_combo._mg_signal_connected = False
            except (TypeError, RuntimeError, AttributeError) as e:
                # هیچ اتصالی وجود ندارد یا widget نامعتبر است
                print(f"Info: No previous connection to disconnect: {e}")
            
            # اتصال سیگنال جدید
            try:
                self.mg_runs_combo.currentIndexChanged.connect(self._on_mg_run_changed)
                self.mg_runs_combo._mg_signal_connected = True
            except (RuntimeError, TypeError) as e:
                print(f"Error connecting signal: {e}")
                self.mg_runs_combo._mg_signal_connected = False
            
            # بارگذاری داده‌های MG اگر قبلاً بارگذاری نشده باشد
            if not self.mg_runs_loaded:
                QTimer.singleShot(50, self._load_mg_runs_into_dropdown)
        
        # پاک کردن layout قبلی
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
        if not box_object:
            show_message("Box object not found.")
            return
        corner_ijk_points = box_object.ijk_points

        print('status:', status)
        print('corner_ijk_points:', corner_ijk_points)
        update_csv(csv_path=csv_path, row=row, status=status, corner_ijk_points=corner_ijk_points)
        show_message('updated')

    # ---------- Helpers ----------
    def _normalize_status(self, value):
        """ورودی‌های مختلف را به 0/1 تبدیل می‌کند: 1=abnormal, 0=normal"""
        if isinstance(value, str):
            v = value.strip().lower()
            return 1 if v in ("abnormal", "abn", "1", "true", "yes", "y") else 0
        if isinstance(value, bool):
            return 1 if value else 0
        if isinstance(value, (int, float)):
            return 1 if int(value) != 0 else 0
        return 0

    def _on_class_selection_changed(self, items: list[str]):
        """با تغییر انتخابِ کلاس‌ها، استور فعلی به‌روزرسانی می‌شود."""
        key = self.lst_boxes_combo.currentText().strip()
        if not key:
            return
        entry = self._sidebar_store.get(key, {})
        entry["classification"] = list(items)  # ذخیره به صورت لیست
        self._sidebar_store[key] = entry

    # ---------- Sidebar Store API ----------
    def sidebar_upsert_item(
            self, *,
            key: str,
            status=None,
            classification: list[str] | None = None,
            features=None,
            select: bool = True,
            box_object: BoxManager = None
    ):
        """
        Add / update MG sidebar item.
        DX modality ignores this method.
        """

        # 🚫 DX isolation
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
            entry["classification"] = [str(c).strip() for c in classification if str(c).strip()]

        if features is not None:
            if isinstance(features, (list, tuple)):
                entry["features"] = "\n".join(str(x) for x in features)
            else:
                entry["features"] = str(features)

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

        # 🚫 DX isolation
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

        # 🚫 DX isolation
        if self.detect_modality() == "DX":
            return

        self.rb_normal.setChecked(True)
        self.rb_abnormal.setChecked(False)

        self.lst_boxes_combo.clear()

        base_items = ["No Finding", "Mass", "Suspicious Calcification", "Focal Asymmetry"]
        self.class_combo.addItemsCheckable(base_items)
        self.class_combo.setCheckedItems([])

        self.feature_view.clear()

        if reset_items:
            self._sidebar_store.clear()

    def _on_apply_clicked(self):
        """
        Apply MG changes to active CSV.
        """

        #  DX isolation
        if self.detect_modality() == "DX":
            return

        if not self.patient_widget:
            return

        # فرض: active CSV توسط vtk_widget تعیین می‌شود
        try:
            if not hasattr(self.patient_widget, 'lst_nodes_viewer') or not self.patient_widget.lst_nodes_viewer:
                show_message("No viewer available.")
                return
                
            vtk_widget = self.patient_widget.lst_nodes_viewer[0].vtk_widget
            if not hasattr(vtk_widget, 'csv_details_path') or not hasattr(vtk_widget, 'current_row'):
                show_message("CSV details not available in viewer.")
                return
                
            csv_path = vtk_widget.csv_details_path
            row = vtk_widget.current_row
        except Exception as e:
            show_message(f"CSV active not found: {str(e)}")
            return

        self.update_csv(csv_path, row)
