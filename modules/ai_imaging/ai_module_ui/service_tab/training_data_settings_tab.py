# -*- coding: utf-8 -*-
"""
Training Data Settings Tab — Separate tabs for BoneAge and Mammography backends.

Based on backend architectures:
- BoneAge: EVA-02 ViT (eva02_base_patch14_448), GenderFiLM conditioning, regression head
- Mammography: FCOS detection + XGBoost classification pipeline
"""

import os
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Optional, Dict, Any

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox,
    QLabel, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QPushButton, QFileDialog, QFormLayout, QCheckBox,
    QScrollArea, QFrame, QTextEdit, QMessageBox
)

from .feedback_collector import (
    collect_bone_age_labels, collect_mammography_labels,
    collect_detection_csv_labels, collect_all_training_data_summary,
    build_training_payload,
)

logger = logging.getLogger(__name__)


class _UiCallDispatcher(QObject):
    """Thread-safe UI dispatcher for callables."""

    invoke = Signal(object)

    def __init__(self):
        super().__init__()
        self.invoke.connect(self._run, Qt.QueuedConnection)

    def _run(self, fn):
        try:
            fn()
        except Exception as e:
            logger.debug(f"[TrainingUI] UI callback failed: {e}")


_UI_DISPATCHER = _UiCallDispatcher()


def _run_on_ui(fn):
    try:
        _UI_DISPATCHER.invoke.emit(fn)
    except Exception:
        try:
            fn()
        except Exception:
            pass

# ─────────────────────────────────────────────────────────────────────────────
# Default settings per backend (from actual backend code)
# ─────────────────────────────────────────────────────────────────────────────

BONE_AGE_DEFAULTS = {
    # Model architecture (from bone_age_twosteps_inference.py)
    "model_name": "eva02_base_patch14_448.mim_in22k_ft_in22k_in1k",
    "img_size": 448,
    "use_gender": True,
    "dropout_rate": 0.3,
    "drop_path_rate": 0.1,
    "max_age_months": 228.0,
    # Training hyperparameters
    "epochs": 100,
    "batch_size": 16,
    "learning_rate": 0.0001,
    "weight_decay": 0.01,
    "optimizer": "AdamW",
    "scheduler": "CosineAnnealing",
    "warmup_epochs": 5,
    # Data augmentation (from inference code preprocessing)
    "use_clahe": True,
    "strong_clahe": False,
    "crop_area_min_ratio": 0.30,
    "tta_steps": 6,
    "crop_pad_frac": 0.20,
    "use_flip_tta": True,
    # Data
    "target_min": 0.0,
    "target_max": 228.0,
    "mean_rgb": [0.2631, 0.2631, 0.2631],
    "std_rgb": [0.2243, 0.2243, 0.2243],
}

MAMMO_DEFAULTS = {
    # Detection model (FCOS from API.py)
    "detection_model": "FCOS",
    "detection_backbone": "ResNet50-FPN",
    "detection_threshold": 0.5,
    # Classification (XGBoost pipeline)
    "classifier": "XGBoost-Stacked",
    "xgb_n_estimators": 200,
    "xgb_max_depth": 6,
    "xgb_learning_rate": 0.1,
    # Training hyperparameters
    "epochs": 50,
    "batch_size": 8,
    "learning_rate": 0.001,
    "weight_decay": 0.0005,
    "optimizer": "SGD",
    "momentum": 0.9,
    # Data
    "img_size": 1024,
    "use_dual_view": True,
    "views": ["CC", "MLO"],
    # Pipeline stages
    "run_detection": True,
    "run_classification": True,
    "run_dual_view_matching": True,
}


PUBLIC_DETECTOR_BACKBONE_URLS = {
    "ResNet50-FPN": "https://download.pytorch.org/models/resnet50-0676ba61.pth",
    "ResNet101-FPN": "https://download.pytorch.org/models/resnet101-63fe2227.pth",
    "ResNeXt101-FPN": "https://download.pytorch.org/models/resnext101_32x8d-110c445d.pth",
    "EfficientNet-B4-BiFPN": "https://download.pytorch.org/models/efficientnet_b4_rwightman-23ab8bcd.pth",
}

PUBLIC_CLASSIFIER_MODEL_URLS = {
    # Tree-based classifier families usually do not have official universal pretrained
    # weights like CNN backbones. Keep blank by default (scratch/continue from local).
    "XGBoost-Stacked": "",
    "XGBoost-Single": "",
    "LightGBM": "",
    "RandomForest": "",
}

PUBLIC_BONEAGE_BACKBONE_URLS = {
    "eva02_base_patch14_448.mim_in22k_ft_in22k_in1k": "https://huggingface.co/timm/eva02_base_patch14_448.mim_in22k_ft_in22k_in1k/resolve/main/model.safetensors",
    "eva02_large_patch14_448.mim_in22k_ft_in22k_in1k": "https://huggingface.co/timm/eva02_large_patch14_448.mim_in22k_ft_in22k_in1k/resolve/main/model.safetensors",
    "eva02_small_patch14_336.mim_in22k_ft_in22k_in1k": "https://huggingface.co/timm/eva02_small_patch14_336.mim_in22k_ft_in22k_in1k/resolve/main/model.safetensors",
    "vit_base_patch16_384": "https://huggingface.co/timm/vit_base_patch16_384.augreg_in21k_ft_in1k/resolve/main/model.safetensors",
    "vit_large_patch16_384": "https://huggingface.co/timm/vit_large_patch16_384.augreg_in21k_ft_in1k/resolve/main/model.safetensors",
}


def _settings_file_path() -> Path:
    """Return the path to the training settings JSON file."""
    try:
        from aipacs_runtime import user_data_root
        return Path(user_data_root()) / "config" / "training_settings.json"
    except Exception:
        return Path(os.getcwd()) / "config" / "training_settings.json"


def _load_saved_settings() -> Dict[str, Any]:
    """Load previously saved settings from disk."""
    path = _settings_file_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load training settings: {e}")
    return {}


def _save_settings(settings: Dict[str, Any]):
    """Save settings to disk."""
    path = _settings_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Failed to save training settings: {e}")


def _default_models_root() -> Path:
    """Return writable base directory for trained/user models."""
    try:
        from aipacs_runtime import user_data_root
        return Path(user_data_root()) / "models"
    except Exception:
        return Path(os.getcwd()) / "models"


def _default_patients_root() -> Path:
    """Return default user-data patients folder used for local DICOM storage."""
    try:
        from aipacs_runtime import user_data_root
        return Path(user_data_root()) / "patients"
    except Exception:
        return Path(os.getcwd()) / "user_data" / "patients"


def _normalize_mammo_img_size(raw_size: int) -> int:
    """Clamp/quantize detected DICOM size to the training spinbox constraints."""
    if raw_size <= 0:
        return 1024
    # UI supports 512..2048 with step 128.
    clamped = max(512, min(2048, raw_size))
    step = 128
    snapped = int(round(clamped / step) * step)
    return max(512, min(2048, snapped))


def _detect_mg_dicom_image_size(search_root: Path, max_scan_files: int = 300) -> Optional[int]:
    """Detect dominant MG DICOM image size from a folder tree.

    Returns the most frequent max(rows, cols) among MG DICOM files.
    """
    if not search_root or not search_root.exists() or not search_root.is_dir():
        return None

    try:
        import pydicom
    except Exception:
        return None

    size_counter: Counter[int] = Counter()
    scanned = 0

    for root, _, files in os.walk(str(search_root)):
        for name in files:
            low = name.lower()
            if not low.endswith((".dcm", ".dicom")):
                continue

            fpath = Path(root) / name
            try:
                ds = pydicom.dcmread(
                    str(fpath),
                    stop_before_pixels=True,
                    force=True,
                    specific_tags=["Rows", "Columns", "Modality"],
                )
                modality = str(getattr(ds, "Modality", "") or "").upper()
                if modality and modality != "MG":
                    continue

                rows = int(getattr(ds, "Rows", 0) or 0)
                cols = int(getattr(ds, "Columns", 0) or 0)
                if rows > 0 and cols > 0:
                    size_counter[max(rows, cols)] += 1
                    scanned += 1
            except Exception:
                continue

            if scanned >= max_scan_files:
                break
        if scanned >= max_scan_files:
            break

    if not size_counter:
        return None
    return size_counter.most_common(1)[0][0]


# ─────────────────────────────────────────────────────────────────────────────
# Styled Section Group
# ─────────────────────────────────────────────────────────────────────────────

class _SectionGroup(QGroupBox):
    """A styled group box for sections."""

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                font-size: 13px;
                border: 1px solid #3a3a4a;
                border-radius: 6px;
                margin-top: 12px;
                padding-top: 18px;
                background-color: #1e1e2e;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
                color: #89b4fa;
            }
        """)


# ─────────────────────────────────────────────────────────────────────────────
# BoneAge Settings Tab
# ─────────────────────────────────────────────────────────────────────────────

class BoneAgeSettingsWidget(QWidget):
    """Settings panel for BoneAge model training."""

    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_defaults()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Header ──
        header = QLabel("🦴 BoneAge Training Configuration")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #a6e3a1; padding: 8px 0;")
        layout.addWidget(header)

        desc = QLabel(
            "EVA-02 Vision Transformer with GenderFiLM conditioning.\n"
            "Backbone: eva02_base_patch14_448 | Task: Bone age regression (0–228 months)"
        )
        desc.setStyleSheet("color: #a6adc8; font-size: 11px; padding-bottom: 8px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Model Architecture ──
        arch_group = _SectionGroup("Model Architecture")
        arch_form = QFormLayout(arch_group)
        arch_form.setSpacing(8)

        self.cmb_backbone = QComboBox()
        self.cmb_backbone.addItems([
            "eva02_base_patch14_448.mim_in22k_ft_in22k_in1k",
            "eva02_large_patch14_448.mim_in22k_ft_in22k_in1k",
            "eva02_small_patch14_336.mim_in22k_ft_in22k_in1k",
            "vit_base_patch16_384",
            "vit_large_patch16_384",
        ])
        arch_form.addRow("Backbone:", self.cmb_backbone)

        self.spn_img_size = QSpinBox()
        self.spn_img_size.setRange(224, 768)
        self.spn_img_size.setSingleStep(32)
        self.spn_img_size.setValue(448)
        arch_form.addRow("Image Size:", self.spn_img_size)

        self.chk_use_gender = QCheckBox("Enable GenderFiLM conditioning")
        self.chk_use_gender.setChecked(True)
        arch_form.addRow("Gender:", self.chk_use_gender)

        self.spn_dropout = QDoubleSpinBox()
        self.spn_dropout.setRange(0.0, 0.8)
        self.spn_dropout.setSingleStep(0.05)
        self.spn_dropout.setValue(0.3)
        arch_form.addRow("Dropout Rate:", self.spn_dropout)

        self.spn_drop_path = QDoubleSpinBox()
        self.spn_drop_path.setRange(0.0, 0.5)
        self.spn_drop_path.setSingleStep(0.05)
        self.spn_drop_path.setValue(0.1)
        arch_form.addRow("Drop Path Rate:", self.spn_drop_path)

        layout.addWidget(arch_group)

        # ── Training Hyperparameters ──
        train_group = _SectionGroup("Training Hyperparameters")
        train_form = QFormLayout(train_group)
        train_form.setSpacing(8)

        self.spn_epochs = QSpinBox()
        self.spn_epochs.setRange(1, 1000)
        self.spn_epochs.setValue(100)
        train_form.addRow("Epochs:", self.spn_epochs)

        self.spn_batch = QSpinBox()
        self.spn_batch.setRange(1, 256)
        self.spn_batch.setValue(16)
        train_form.addRow("Batch Size:", self.spn_batch)

        self.spn_lr = QDoubleSpinBox()
        self.spn_lr.setRange(0.000001, 1.0)
        self.spn_lr.setDecimals(6)
        self.spn_lr.setSingleStep(0.0001)
        self.spn_lr.setValue(0.0001)
        train_form.addRow("Learning Rate:", self.spn_lr)

        self.spn_weight_decay = QDoubleSpinBox()
        self.spn_weight_decay.setRange(0.0, 1.0)
        self.spn_weight_decay.setDecimals(5)
        self.spn_weight_decay.setSingleStep(0.001)
        self.spn_weight_decay.setValue(0.01)
        train_form.addRow("Weight Decay:", self.spn_weight_decay)

        self.cmb_scheduler = QComboBox()
        self.cmb_scheduler.addItems(["CosineAnnealing", "StepLR", "OneCycleLR", "ReduceOnPlateau"])
        train_form.addRow("LR Scheduler:", self.cmb_scheduler)

        self.spn_warmup = QSpinBox()
        self.spn_warmup.setRange(0, 50)
        self.spn_warmup.setValue(5)
        train_form.addRow("Warmup Epochs:", self.spn_warmup)

        layout.addWidget(train_group)

        # ── Data & Augmentation ──
        data_group = _SectionGroup("Data & Augmentation")
        data_form = QFormLayout(data_group)
        data_form.setSpacing(8)

        self.chk_clahe = QCheckBox("Apply CLAHE preprocessing")
        self.chk_clahe.setChecked(True)
        data_form.addRow("CLAHE:", self.chk_clahe)

        self.chk_strong_clahe = QCheckBox("Strong CLAHE (higher clip limit)")
        self.chk_strong_clahe.setChecked(False)
        data_form.addRow("", self.chk_strong_clahe)

        self.spn_crop_min = QDoubleSpinBox()
        self.spn_crop_min.setRange(0.1, 1.0)
        self.spn_crop_min.setSingleStep(0.05)
        self.spn_crop_min.setValue(0.30)
        data_form.addRow("Crop Area Min Ratio:", self.spn_crop_min)

        self.spn_crop_pad = QDoubleSpinBox()
        self.spn_crop_pad.setRange(0.0, 0.5)
        self.spn_crop_pad.setSingleStep(0.05)
        self.spn_crop_pad.setValue(0.20)
        data_form.addRow("Crop Pad Fraction:", self.spn_crop_pad)

        self.spn_tta = QSpinBox()
        self.spn_tta.setRange(1, 20)
        self.spn_tta.setValue(6)
        data_form.addRow("TTA Steps:", self.spn_tta)

        self.chk_flip_tta = QCheckBox("Flip + Rotation TTA")
        self.chk_flip_tta.setChecked(True)
        data_form.addRow("TTA Augment:", self.chk_flip_tta)

        self.spn_target_max = QDoubleSpinBox()
        self.spn_target_max.setRange(100.0, 300.0)
        self.spn_target_max.setValue(228.0)
        data_form.addRow("Max Age (months):", self.spn_target_max)

        layout.addWidget(data_group)

        # ── Data Path ──
        path_group = _SectionGroup("Training Data Path")
        path_layout = QVBoxLayout(path_group)

        path_row = QHBoxLayout()
        self.txt_data_path = QLineEdit()
        self.txt_data_path.setPlaceholderText("Select training data folder...")
        self.txt_data_path.setReadOnly(True)
        path_row.addWidget(self.txt_data_path)

        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(btn_browse)
        path_layout.addLayout(path_row)

        self.lbl_file_count = QLabel("No folder selected")
        self.lbl_file_count.setStyleSheet("color: #a6adc8; font-size: 11px;")
        path_layout.addWidget(self.lbl_file_count)

        layout.addWidget(path_group)

        # ── Model Save / Selection ──
        model_group = _SectionGroup("Model Save & Selection")
        model_form = QFormLayout(model_group)
        model_form.setSpacing(8)

        self.cmb_model_source = QComboBox()
        self.cmb_model_source.addItem("AI Pacs Model", "iran_nobat")
        self.cmb_model_source.addItem("Scratch", "scratch")
        model_form.addRow("Training Init:", self.cmb_model_source)

        self.txt_pretrained_model_url = QLineEdit()
        self.txt_pretrained_model_url.setPlaceholderText("Public pretrained backbone URL...")
        model_form.addRow("Backbone URL:", self.txt_pretrained_model_url)

        self.lbl_url_hint = QLabel(
            "URLs are public model links only (no private server links)."
        )
        self.lbl_url_hint.setStyleSheet("color: #a6adc8; font-size: 11px;")
        model_form.addRow("", self.lbl_url_hint)

        save_row = QHBoxLayout()
        self.txt_model_output_dir = QLineEdit()
        self.txt_model_output_dir.setPlaceholderText("Select folder for saving trained model...")
        self.txt_model_output_dir.setReadOnly(True)
        save_row.addWidget(self.txt_model_output_dir)
        self.btn_browse_output_dir = QPushButton("Browse")
        self.btn_browse_output_dir.setFixedWidth(80)
        self.btn_browse_output_dir.clicked.connect(self._on_browse_output_dir)
        save_row.addWidget(self.btn_browse_output_dir)
        model_form.addRow("Save Model To:", save_row)

        layout.addWidget(model_group)

        layout.addStretch()
        scroll.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _load_defaults(self):
        saved = _load_saved_settings().get("bone_age", {})
        if saved.get("backbone"):
            idx = self.cmb_backbone.findText(saved["backbone"])
            if idx >= 0:
                self.cmb_backbone.setCurrentIndex(idx)
        if saved.get("img_size"):
            self.spn_img_size.setValue(saved["img_size"])
        if saved.get("epochs"):
            self.spn_epochs.setValue(saved["epochs"])
        if saved.get("batch_size"):
            self.spn_batch.setValue(saved["batch_size"])
        if saved.get("learning_rate"):
            self.spn_lr.setValue(saved["learning_rate"])
        if saved.get("data_path"):
            self.txt_data_path.setText(saved["data_path"])
            self._update_file_count(saved["data_path"])

        default_out = _default_models_root() / "bone_age"
        self.txt_model_output_dir.setText(str(saved.get("model_output_dir") or default_out))
        src = str(saved.get("model_source") or "iran_nobat")
        idx = self.cmb_model_source.findData(src)
        self.cmb_model_source.setCurrentIndex(idx if idx >= 0 else 0)

        saved_model_url = str(saved.get("pretrained_model_url") or "").strip()
        if saved_model_url:
            self.txt_pretrained_model_url.setText(saved_model_url)
        else:
            self.txt_pretrained_model_url.setText(
                PUBLIC_BONEAGE_BACKBONE_URLS.get(self.cmb_backbone.currentText(), "")
            )

        self.cmb_backbone.currentTextChanged.connect(self._on_boneage_backbone_changed)

    def _on_browse(self):
        try:
            from aipacs_runtime import user_data_root
            start_dir = str(user_data_root())
        except Exception:
            start_dir = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(self, "Select BoneAge Training Data", start_dir)
        if folder:
            self.txt_data_path.setText(folder)
            self._update_file_count(folder)
            self.settings_changed.emit()

    def _on_browse_output_dir(self):
        start_dir = str(_default_models_root() / "bone_age")
        folder = QFileDialog.getExistingDirectory(self, "Select Model Output Directory", start_dir)
        if folder:
            self.txt_model_output_dir.setText(folder)
            self.settings_changed.emit()

    def _update_file_count(self, folder: str):
        if not folder or not os.path.isdir(folder):
            self.lbl_file_count.setText("Invalid folder")
            return
        count = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".dcm", ".dicom", ".tiff")):
                    count += 1
        self.lbl_file_count.setText(f"📁 {count} image files found")

    def _on_boneage_backbone_changed(self, backbone: str):
        cur = self.txt_pretrained_model_url.text().strip()
        known_values = set(v for v in PUBLIC_BONEAGE_BACKBONE_URLS.values() if v)
        if (not cur) or (cur in known_values):
            self.txt_pretrained_model_url.setText(PUBLIC_BONEAGE_BACKBONE_URLS.get(backbone, ""))

    def get_settings(self) -> Dict[str, Any]:
        """Return current BoneAge settings as dict."""
        return {
            "backend": "bone_age",
            "backbone": self.cmb_backbone.currentText(),
            "img_size": self.spn_img_size.value(),
            "use_gender": self.chk_use_gender.isChecked(),
            "dropout_rate": self.spn_dropout.value(),
            "drop_path_rate": self.spn_drop_path.value(),
            "epochs": self.spn_epochs.value(),
            "batch_size": self.spn_batch.value(),
            "learning_rate": self.spn_lr.value(),
            "weight_decay": self.spn_weight_decay.value(),
            "scheduler": self.cmb_scheduler.currentText(),
            "warmup_epochs": self.spn_warmup.value(),
            "use_clahe": self.chk_clahe.isChecked(),
            "strong_clahe": self.chk_strong_clahe.isChecked(),
            "crop_area_min_ratio": self.spn_crop_min.value(),
            "crop_pad_frac": self.spn_crop_pad.value(),
            "tta_steps": self.spn_tta.value(),
            "use_flip_tta": self.chk_flip_tta.isChecked(),
            "target_max": self.spn_target_max.value(),
            "data_path": self.txt_data_path.text(),
            "model_source": self.cmb_model_source.currentData(),
            "pretrained_model_url": self.txt_pretrained_model_url.text().strip(),
            "model_output_dir": self.txt_model_output_dir.text().strip(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Mammography Settings Tab
# ─────────────────────────────────────────────────────────────────────────────

class MammographySettingsWidget(QWidget):
    """Settings panel for Mammography model training."""

    settings_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()
        self._load_defaults()

    def _build_ui(self):
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setSpacing(16)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Header ──
        header = QLabel("🩻 Mammography Training Configuration")
        header.setStyleSheet("font-size: 16px; font-weight: bold; color: #89b4fa; padding: 8px 0;")
        layout.addWidget(header)

        desc = QLabel(
            "FCOS Detection + XGBoost Classification pipeline.\n"
            "Detection: ResNet50-FPN backbone | Classification: Stacked XGBoost ensemble"
        )
        desc.setStyleSheet("color: #a6adc8; font-size: 11px; padding-bottom: 8px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # ── Detection Model ──
        det_group = _SectionGroup("Detection Model (FCOS)")
        det_form = QFormLayout(det_group)
        det_form.setSpacing(8)

        self.cmb_det_backbone = QComboBox()
        self.cmb_det_backbone.addItems([
            "ResNet50-FPN",
            "ResNet101-FPN",
            "ResNeXt101-FPN",
            "EfficientNet-B4-BiFPN",
        ])
        det_form.addRow("Backbone:", self.cmb_det_backbone)

        self.spn_det_threshold = QDoubleSpinBox()
        self.spn_det_threshold.setRange(0.1, 0.99)
        self.spn_det_threshold.setSingleStep(0.05)
        self.spn_det_threshold.setValue(0.5)
        det_form.addRow("Detection Threshold:", self.spn_det_threshold)

        self.spn_det_img_size = QSpinBox()
        self.spn_det_img_size.setRange(512, 2048)
        self.spn_det_img_size.setSingleStep(128)
        self.spn_det_img_size.setValue(1024)
        det_form.addRow("Image Size:", self.spn_det_img_size)

        self.spn_det_epochs = QSpinBox()
        self.spn_det_epochs.setRange(1, 500)
        self.spn_det_epochs.setValue(50)
        det_form.addRow("Epochs:", self.spn_det_epochs)

        self.spn_det_batch = QSpinBox()
        self.spn_det_batch.setRange(1, 64)
        self.spn_det_batch.setValue(8)
        det_form.addRow("Batch Size:", self.spn_det_batch)

        self.spn_det_lr = QDoubleSpinBox()
        self.spn_det_lr.setRange(0.000001, 1.0)
        self.spn_det_lr.setDecimals(6)
        self.spn_det_lr.setSingleStep(0.0001)
        self.spn_det_lr.setValue(0.001)
        det_form.addRow("Learning Rate:", self.spn_det_lr)

        self.spn_det_wd = QDoubleSpinBox()
        self.spn_det_wd.setRange(0.0, 1.0)
        self.spn_det_wd.setDecimals(5)
        self.spn_det_wd.setSingleStep(0.0001)
        self.spn_det_wd.setValue(0.0005)
        det_form.addRow("Weight Decay:", self.spn_det_wd)

        self.spn_det_momentum = QDoubleSpinBox()
        self.spn_det_momentum.setRange(0.0, 0.99)
        self.spn_det_momentum.setSingleStep(0.05)
        self.spn_det_momentum.setValue(0.9)
        det_form.addRow("Momentum:", self.spn_det_momentum)

        layout.addWidget(det_group)

        # ── Classification (XGBoost) ──
        cls_group = _SectionGroup("Classification (XGBoost Pipeline)")
        cls_form = QFormLayout(cls_group)
        cls_form.setSpacing(8)

        self.cmb_cls_model = QComboBox()
        self.cmb_cls_model.addItems([
            "XGBoost-Stacked",
            "XGBoost-Single",
            "LightGBM",
            "RandomForest",
        ])
        cls_form.addRow("Classifier:", self.cmb_cls_model)

        self.spn_n_estimators = QSpinBox()
        self.spn_n_estimators.setRange(10, 2000)
        self.spn_n_estimators.setSingleStep(50)
        self.spn_n_estimators.setValue(200)
        cls_form.addRow("N Estimators:", self.spn_n_estimators)

        self.spn_max_depth = QSpinBox()
        self.spn_max_depth.setRange(2, 20)
        self.spn_max_depth.setValue(6)
        cls_form.addRow("Max Depth:", self.spn_max_depth)

        self.spn_xgb_lr = QDoubleSpinBox()
        self.spn_xgb_lr.setRange(0.001, 1.0)
        self.spn_xgb_lr.setDecimals(4)
        self.spn_xgb_lr.setSingleStep(0.01)
        self.spn_xgb_lr.setValue(0.1)
        cls_form.addRow("Learning Rate:", self.spn_xgb_lr)

        self.spn_subsample = QDoubleSpinBox()
        self.spn_subsample.setRange(0.3, 1.0)
        self.spn_subsample.setSingleStep(0.05)
        self.spn_subsample.setValue(0.8)
        cls_form.addRow("Subsample:", self.spn_subsample)

        self.spn_colsample = QDoubleSpinBox()
        self.spn_colsample.setRange(0.3, 1.0)
        self.spn_colsample.setSingleStep(0.05)
        self.spn_colsample.setValue(0.8)
        cls_form.addRow("Col Sample:", self.spn_colsample)

        layout.addWidget(cls_group)

        # ── Pipeline Options ──
        pipe_group = _SectionGroup("Pipeline Stages")
        pipe_form = QFormLayout(pipe_group)
        pipe_form.setSpacing(8)

        self.chk_run_detection = QCheckBox("Run FCOS detection")
        self.chk_run_detection.setChecked(True)
        pipe_form.addRow("Detection:", self.chk_run_detection)

        self.chk_run_classification = QCheckBox("Run XGBoost classification")
        self.chk_run_classification.setChecked(True)
        pipe_form.addRow("Classification:", self.chk_run_classification)

        self.chk_dual_view = QCheckBox("Dual-view matching (CC ↔ MLO)")
        self.chk_dual_view.setChecked(True)
        pipe_form.addRow("Dual-View:", self.chk_dual_view)

        self.cmb_views = QComboBox()
        self.cmb_views.addItems(["CC + MLO (Both)", "CC Only", "MLO Only"])
        pipe_form.addRow("Views:", self.cmb_views)

        layout.addWidget(pipe_group)

        # ── Model Save / Selection ──
        model_group = _SectionGroup("Model Save & Selection")
        model_form = QFormLayout(model_group)
        model_form.setSpacing(8)

        self.cmb_model_source = QComboBox()
        self.cmb_model_source.addItem("AI Pacs Model", "iran_nobat")
        self.cmb_model_source.addItem("Scratch", "scratch")
        model_form.addRow("Training Init:", self.cmb_model_source)

        self.txt_detector_pretrained_url = QLineEdit()
        self.txt_detector_pretrained_url.setPlaceholderText("Public detector backbone URL...")
        model_form.addRow("Detector URL:", self.txt_detector_pretrained_url)

        self.txt_classifier_pretrained_url = QLineEdit()
        self.txt_classifier_pretrained_url.setPlaceholderText("Public classifier init URL (optional)...")
        model_form.addRow("Classifier URL:", self.txt_classifier_pretrained_url)

        self.lbl_url_hint = QLabel(
            "URLs are public model links only (no private server links)."
        )
        self.lbl_url_hint.setStyleSheet("color: #a6adc8; font-size: 11px;")
        model_form.addRow("", self.lbl_url_hint)

        save_row = QHBoxLayout()
        self.txt_model_output_dir = QLineEdit()
        self.txt_model_output_dir.setPlaceholderText("Select folder for saving trained model...")
        self.txt_model_output_dir.setReadOnly(True)
        save_row.addWidget(self.txt_model_output_dir)
        self.btn_browse_output_dir = QPushButton("Browse")
        self.btn_browse_output_dir.setFixedWidth(80)
        self.btn_browse_output_dir.clicked.connect(self._on_browse_output_dir)
        save_row.addWidget(self.btn_browse_output_dir)
        model_form.addRow("Save Model To:", save_row)

        layout.addWidget(model_group)

        # ── Data Path ──
        path_group = _SectionGroup("Training Data Path")
        path_layout = QVBoxLayout(path_group)

        path_row = QHBoxLayout()
        self.txt_data_path = QLineEdit()
        self.txt_data_path.setPlaceholderText("Select mammography training data folder...")
        self.txt_data_path.setReadOnly(True)
        path_row.addWidget(self.txt_data_path)

        btn_browse = QPushButton("Browse")
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._on_browse)
        path_row.addWidget(btn_browse)
        path_layout.addLayout(path_row)

        self.lbl_file_count = QLabel("No folder selected")
        self.lbl_file_count.setStyleSheet("color: #a6adc8; font-size: 11px;")
        path_layout.addWidget(self.lbl_file_count)

        self.lbl_detected_size = QLabel("Auto image size: waiting for MG DICOM scan")
        self.lbl_detected_size.setStyleSheet("color: #89b4fa; font-size: 11px;")
        path_layout.addWidget(self.lbl_detected_size)

        layout.addWidget(path_group)

        layout.addStretch()
        scroll.setWidget(container)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _load_defaults(self):
        saved = _load_saved_settings().get("mammography", {})
        if saved.get("det_backbone"):
            idx = self.cmb_det_backbone.findText(saved["det_backbone"])
            if idx >= 0:
                self.cmb_det_backbone.setCurrentIndex(idx)
        if saved.get("det_img_size"):
            self.spn_det_img_size.setValue(saved["det_img_size"])
        if saved.get("det_epochs"):
            self.spn_det_epochs.setValue(saved["det_epochs"])
        if saved.get("det_batch_size"):
            self.spn_det_batch.setValue(saved["det_batch_size"])
        if saved.get("det_lr"):
            self.spn_det_lr.setValue(saved["det_lr"])
        path_for_detection = ""
        if saved.get("data_path"):
            self.txt_data_path.setText(saved["data_path"])
            self._update_file_count(saved["data_path"])
            path_for_detection = str(saved["data_path"])

        default_out = _default_models_root() / "mammography"
        self.txt_model_output_dir.setText(str(saved.get("model_output_dir") or default_out))
        src = str(saved.get("model_source") or "iran_nobat")
        idx = self.cmb_model_source.findData(src)
        self.cmb_model_source.setCurrentIndex(idx if idx >= 0 else 0)

        saved_det_url = str(saved.get("pretrained_detector_url") or "").strip()
        saved_cls_url = str(saved.get("pretrained_classifier_url") or "").strip()
        if saved_det_url:
            self.txt_detector_pretrained_url.setText(saved_det_url)
        else:
            self.txt_detector_pretrained_url.setText(
                PUBLIC_DETECTOR_BACKBONE_URLS.get(self.cmb_det_backbone.currentText(), "")
            )
        if saved_cls_url:
            self.txt_classifier_pretrained_url.setText(saved_cls_url)
        else:
            self.txt_classifier_pretrained_url.setText(
                PUBLIC_CLASSIFIER_MODEL_URLS.get(self.cmb_cls_model.currentText(), "")
            )

        self.cmb_det_backbone.currentTextChanged.connect(self._on_detector_backbone_changed)
        self.cmb_cls_model.currentTextChanged.connect(self._on_classifier_model_changed)

        self._auto_detect_and_apply_img_size(path_for_detection)

    def _on_browse(self):
        try:
            from aipacs_runtime import user_data_root
            start_dir = str(user_data_root())
        except Exception:
            start_dir = os.path.expanduser("~")

        folder = QFileDialog.getExistingDirectory(self, "Select Mammography Training Data", start_dir)
        if folder:
            self.txt_data_path.setText(folder)
            self._update_file_count(folder)
            self._auto_detect_and_apply_img_size(folder)
            self.settings_changed.emit()

    def _on_browse_output_dir(self):
        start_dir = str(_default_models_root() / "mammography")
        folder = QFileDialog.getExistingDirectory(self, "Select Model Output Directory", start_dir)
        if folder:
            self.txt_model_output_dir.setText(folder)
            self.settings_changed.emit()

    def _update_file_count(self, folder: str):
        if not folder or not os.path.isdir(folder):
            self.lbl_file_count.setText("Invalid folder")
            return
        count = 0
        for root, _, files in os.walk(folder):
            for f in files:
                if f.lower().endswith((".png", ".jpg", ".jpeg", ".dcm", ".dicom", ".tiff")):
                    count += 1
        self.lbl_file_count.setText(f"📁 {count} image files found")

    def _on_detector_backbone_changed(self, backbone: str):
        cur = self.txt_detector_pretrained_url.text().strip()
        known_values = set(v for v in PUBLIC_DETECTOR_BACKBONE_URLS.values() if v)
        if (not cur) or (cur in known_values):
            self.txt_detector_pretrained_url.setText(PUBLIC_DETECTOR_BACKBONE_URLS.get(backbone, ""))

    def _on_classifier_model_changed(self, cls_model: str):
        cur = self.txt_classifier_pretrained_url.text().strip()
        known_values = set(v for v in PUBLIC_CLASSIFIER_MODEL_URLS.values() if v)
        if (not cur) or (cur in known_values):
            self.txt_classifier_pretrained_url.setText(PUBLIC_CLASSIFIER_MODEL_URLS.get(cls_model, ""))

    def _auto_detect_and_apply_img_size(self, preferred_folder: str = ""):
        """Auto-detect MG DICOM image size from user data and apply to det image size."""
        search_roots = []
        if preferred_folder:
            search_roots.append(Path(preferred_folder))
        search_roots.append(_default_patients_root())

        seen = set()
        detected_raw = None
        source_root = None
        for root in search_roots:
            key = str(root.resolve()) if root.exists() else str(root)
            if key in seen:
                continue
            seen.add(key)

            found = _detect_mg_dicom_image_size(root)
            if found:
                detected_raw = found
                source_root = root
                break

        if detected_raw:
            detected = _normalize_mammo_img_size(detected_raw)
            self.spn_det_img_size.setValue(detected)
            self.lbl_detected_size.setText(
                f"Auto image size: {detected} (detected {detected_raw}px from {source_root})"
            )
            return

        self.lbl_detected_size.setText(
            "Auto image size: no MG DICOM found (keeping current value)"
        )

    def get_settings(self) -> Dict[str, Any]:
        """Return current Mammography settings as dict."""
        return {
            "backend": "mammography",
            "det_backbone": self.cmb_det_backbone.currentText(),
            "det_threshold": self.spn_det_threshold.value(),
            "det_img_size": self.spn_det_img_size.value(),
            "det_epochs": self.spn_det_epochs.value(),
            "det_batch_size": self.spn_det_batch.value(),
            "det_lr": self.spn_det_lr.value(),
            "det_weight_decay": self.spn_det_wd.value(),
            "det_momentum": self.spn_det_momentum.value(),
            "cls_model": self.cmb_cls_model.currentText(),
            "cls_n_estimators": self.spn_n_estimators.value(),
            "cls_max_depth": self.spn_max_depth.value(),
            "cls_learning_rate": self.spn_xgb_lr.value(),
            "cls_subsample": self.spn_subsample.value(),
            "cls_colsample": self.spn_colsample.value(),
            "run_detection": self.chk_run_detection.isChecked(),
            "run_classification": self.chk_run_classification.isChecked(),
            "use_dual_view": self.chk_dual_view.isChecked(),
            "views": self.cmb_views.currentText(),
            "data_path": self.txt_data_path.text(),
            "model_source": self.cmb_model_source.currentData(),
            "pretrained_detector_url": self.txt_detector_pretrained_url.text().strip(),
            "pretrained_classifier_url": self.txt_classifier_pretrained_url.text().strip(),
            "model_output_dir": self.txt_model_output_dir.text().strip(),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Main Training Data Settings Tab (combines both backends)
# ─────────────────────────────────────────────────────────────────────────────

class TrainingDataSettingsTab(QWidget):
    """
    Main training data settings widget with tabbed interface:
      - Tab 1: BoneAge (EVA-02 ViT)
      - Tab 2: Mammography (FCOS + XGBoost)
    """

    training_requested = Signal(dict)  # emitted when user clicks Train

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(8, 8, 8, 8)

        # ── Title Bar ──
        title_bar = QHBoxLayout()
        title = QLabel("⚙️ Training Data Settings")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #cdd6f4;")
        title_bar.addWidget(title)
        title_bar.addStretch()

        self.btn_save = QPushButton("💾 Save Settings")
        self.btn_save.setFixedHeight(32)
        self.btn_save.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #45475a; }
        """)
        self.btn_save.clicked.connect(self._on_save)
        title_bar.addWidget(self.btn_save)

        self.btn_reset = QPushButton("🔄 Reset Defaults")
        self.btn_reset.setFixedHeight(32)
        self.btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border: 1px solid #45475a;
                border-radius: 4px;
                padding: 4px 16px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #45475a; }
        """)
        self.btn_reset.clicked.connect(self._on_reset)
        title_bar.addWidget(self.btn_reset)

        layout.addLayout(title_bar)

        # ── Tabs ──
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #313244;
                border-radius: 4px;
                background-color: #181825;
            }
            QTabBar::tab {
                background-color: #1e1e2e;
                color: #a6adc8;
                border: 1px solid #313244;
                padding: 8px 24px;
                margin-right: 2px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background-color: #313244;
                color: #cdd6f4;
                border-bottom-color: #313244;
            }
            QTabBar::tab:hover {
                background-color: #45475a;
                color: #cdd6f4;
            }
        """)

        self.bone_age_tab = BoneAgeSettingsWidget()
        self.mammo_tab = MammographySettingsWidget()

        self.tabs.addTab(self.bone_age_tab, "🦴  Bone Age")
        self.tabs.addTab(self.mammo_tab, "🩻  Mammography")

        layout.addWidget(self.tabs)

        # ── Action Bar ──
        action_bar = QHBoxLayout()
        action_bar.addStretch()

        self.btn_collect = QPushButton("📋 Collect Labels")
        self.btn_collect.setFixedHeight(40)
        self.btn_collect.setFixedWidth(180)
        self.btn_collect.setToolTip(
            "Scan all confirmed/rejected labels from the Imaging Tools tab\n"
            "and show how many training samples are available."
        )
        self.btn_collect.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #74c7ec; }
            QPushButton:pressed { background-color: #89dceb; }
        """)
        self.btn_collect.clicked.connect(self._on_collect_labels)
        action_bar.addWidget(self.btn_collect)

        self.btn_train = QPushButton("🚀 Start Training")
        self.btn_train.setFixedHeight(40)
        self.btn_train.setFixedWidth(200)
        self.btn_train.setStyleSheet("""
            QPushButton {
                background-color: #a6e3a1;
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #94e2d5; }
            QPushButton:pressed { background-color: #89dceb; }
        """)
        self.btn_train.clicked.connect(self._on_train)
        action_bar.addWidget(self.btn_train)

        action_bar.addStretch()
        layout.addLayout(action_bar)

        # ── Status / Log ──
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(120)
        self.txt_log.setStyleSheet("""
            QTextEdit {
                background-color: #11111b;
                color: #a6adc8;
                border: 1px solid #313244;
                border-radius: 4px;
                font-family: Consolas, monospace;
                font-size: 11px;
            }
        """)
        self.txt_log.setPlaceholderText("Training log output will appear here...")
        layout.addWidget(self.txt_log)

    def _on_save(self):
        """Save current settings to disk."""
        settings = {
            "bone_age": self.bone_age_tab.get_settings(),
            "mammography": self.mammo_tab.get_settings(),
        }
        _save_settings(settings)
        self._log("✅ Settings saved successfully.")

    def _on_reset(self):
        """Reset to default values (reload UI)."""
        reply = QMessageBox.question(
            self, "Reset Settings",
            "Reset all training settings to defaults?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            # Re-create tab widgets
            self.tabs.removeTab(1)
            self.tabs.removeTab(0)
            self.bone_age_tab = BoneAgeSettingsWidget()
            self.mammo_tab = MammographySettingsWidget()
            self.tabs.addTab(self.bone_age_tab, "🦴  Bone Age")
            self.tabs.addTab(self.mammo_tab, "🩻  Mammography")
            self._log("🔄 Settings reset to defaults.")

    def _on_collect_labels(self):
        """Collect labeled feedback data from imaging tab CSVs and show summary."""
        import threading

        def _do_collect():
            try:
                summary = collect_all_training_data_summary()
                ba = summary["bone_age"]
                mg = summary["mammography_feedback"]
                det = summary["mammography_detection"]
                self._log("─── Collected Labels Summary ───")
                self._log(f"🦴 BoneAge: {ba['total']} labeled (confirmed={ba['confirmed']}, corrected={ba['corrected']})")
                self._log(f"🩻 MG Feedback: {mg['total']} entries (positive={mg['positive']}, negative={mg['negative']})")
                self._log(f"📦 MG Detection CSV: {det['total']} images (positive={det['positive']}, negative={det['negative']})")
                total = ba['total'] + mg['total'] + det['total']
                if total == 0:
                    self._log("⚠️ No labeled data found. Use the Imaging Tools tab to confirm/reject AI predictions first.")
                else:
                    self._log(f"✅ Total {total} labeled entries ready for training.")
                self._log("────────────────────────────────")
            except Exception as e:
                self._log(f"❌ Label collection failed: {e}")

        thread = threading.Thread(target=_do_collect, daemon=True)
        thread.start()

    def _on_train(self):
        """Gather settings from current tab, collect labels, and start local training."""
        current_idx = self.tabs.currentIndex()
        if current_idx == 0:
            settings = self.bone_age_tab.get_settings()
        else:
            settings = self.mammo_tab.get_settings()

        # Validate: either data_path OR we have collected feedback labels
        data_path = settings.get("data_path", "")
        backend = settings.get("backend", "bone_age")

        # Collect labeled data from feedback CSVs
        if backend == "bone_age":
            labeled = collect_bone_age_labels()
        else:
            labeled_fb = collect_mammography_labels()
            labeled_det = collect_detection_csv_labels()
            labeled = labeled_fb + labeled_det

        has_labels = len(labeled) > 0
        has_data_path = data_path and os.path.isdir(data_path)

        if not has_labels and not has_data_path:
            QMessageBox.warning(
                self, "No Training Data",
                "No labeled data found.\n\n"
                "Either:\n"
                "1. Use the Imaging Tools tab to confirm/reject AI predictions (labels will be collected automatically), or\n"
                "2. Select a training data folder with prepared images."
            )
            return

        self._log(f"🚀 Starting training [{backend}]...")
        if has_labels:
            self._log(f"   Collected labels: {len(labeled)} entries from user feedback")
        if has_data_path:
            self._log(f"   Data folder: {data_path}")
        self._log(f"   Training init: {settings.get('model_source', 'iran_nobat')}")

        # Build full training payload with labels
        payload = build_training_payload(backend, settings)

        # Emit signal for external handler
        self.training_requested.emit(settings)

        # Save training data locally as backup
        self._save_training_data_locally(settings, payload)

        # ── Actually run training ──
        self._start_local_training(labeled, settings, backend)

    def _save_training_data_locally(self, settings: Dict[str, Any], payload: Optional[Dict[str, Any]] = None):
        """Save the collected training data + settings locally as a JSON file
        so it can be used later when the backend supports /train."""
        import json
        from datetime import datetime

        try:
            output_dir = settings.get("model_output_dir", "")
            if not output_dir:
                output_dir = str(_default_models_root() / settings.get("backend", "unknown"))

            os.makedirs(output_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join(output_dir, f"training_data_{timestamp}.json")

            data_to_save = payload if payload else {"settings": settings}
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False, default=str)

            self._log(f"💾 Training data saved: {out_path}")
        except Exception as e:
            self._log(f"❌ Failed to save training data locally: {e}")

    def _start_local_training(self, labeled: list, settings: Dict[str, Any], backend: str):
        """Launch actual training in a background thread."""
        from .local_training_runner import run_training_async

        self._log("⏳ Training started in background...")
        self.btn_train.setEnabled(False)
        self.btn_train.setText("Training...")

        def _on_progress(pct: int, msg: str):
            _run_on_ui(lambda: self._log(f"   [{pct}%] {msg}"))

        def _on_complete(result: Dict[str, Any]):
            def _finish():
                self.btn_train.setEnabled(True)
                self.btn_train.setText("Start Training")
                status = result.get("status", "unknown")
                if status == "completed":
                    acc = result.get("accuracy", 0)
                    model_path = result.get("model_path", "")
                    det_model_path = result.get("detection_model_path", "")
                    cls_model_path = result.get("classification_model_path", "")
                    self._log(f"✅ Training completed successfully!")
                    self._log(f"   Accuracy: {acc:.1%}")
                    self._log(f"   Samples: {result.get('samples_loaded', 0)} "
                              f"(+{result.get('positives', 0)} / -{result.get('negatives', 0)})")
                    self._log(f"   Backbone: {result.get('backbone', settings.get('det_backbone', '-'))}")
                    self._log(f"   Training init: {result.get('model_source', settings.get('model_source', '-'))}")
                    self._log(
                        "   Init artifacts: "
                        f"detector={'ok' if result.get('detector_init_ready') else 'missing'}, "
                        f"classifier={'ok' if result.get('classifier_init_ready') else 'missing'}"
                    )
                    if result.get("detector_init_path"):
                        self._log(f"   Detector init model: {result.get('detector_init_path')}")
                    if result.get("classifier_init_path"):
                        self._log(f"   Classifier init model: {result.get('classifier_init_path')}")
                    if det_model_path:
                        self._log(f"   Detection model saved: {det_model_path}")
                    if cls_model_path:
                        self._log(f"   Classification model saved: {cls_model_path}")
                    if model_path and model_path != cls_model_path:
                        self._log(f"   Model saved: {model_path}")
                else:
                    error = result.get("error", "Unknown error")
                    self._log(f"❌ Training failed: {error}")
            _run_on_ui(_finish)

        run_training_async(labeled, settings, _on_progress, _on_complete)

    def _log(self, msg: str):
        """Append message to log widget via thread-safe queued dispatch."""
        _run_on_ui(lambda: self.txt_log.append(msg))

    def get_all_settings(self) -> Dict[str, Any]:
        """Return all settings for both backends."""
        return {
            "bone_age": self.bone_age_tab.get_settings(),
            "mammography": self.mammo_tab.get_settings(),
        }
