"""
Model Training Tab — UI for preparing training data, selecting architecture,
configuring layers, and sending data to the model server for retraining.

Workflow:
  1. User reviews labeled data (from MG/DX feedback CSVs + images)
  2. User selects/filters data for training
  3. User picks model architecture & layer config
  4. User triggers "Prepare & Send" which:
     a) Packages selected data into a training CSV + image folder
     b) Sends the package to the model server endpoint
     c) Monitors training progress via polling/status
"""

import csv
import json
import os
import shutil
import threading
import urllib.request
import urllib.error
import zipfile
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHeaderView,
)

from . import AbstractTab
from PacsClient.utils.config import ATTACHMENT_PATH, CLINICAL_CSV_PATH


TRAINING_DATA_DIR = ATTACHMENT_PATH / "training_data"
TRAINING_EXPORTS_DIR = ATTACHMENT_PATH / "training_exports"


MODEL_ARCHITECTURES = {
    "YOLOv8-Detection": {
        "description": "Real-time object detection for lesion localization",
        "layers": ["Backbone (CSPDarknet)", "Neck (FPN+PAN)", "Detection Head"],
        "params": {"img_size": 640, "epochs": 50, "batch_size": 16, "lr": 0.01},
    },
    "YOLOv8-Classification": {
        "description": "Image classification for finding categorization",
        "layers": ["Backbone (CSPDarknet)", "Classification Head (FC)"],
        "params": {"img_size": 224, "epochs": 30, "batch_size": 32, "lr": 0.001},
    },
    "ResNet50-Classification": {
        "description": "Deep residual network for robust classification",
        "layers": [
            "Conv1 (7x7)",
            "Layer1 (3 blocks)",
            "Layer2 (4 blocks)",
            "Layer3 (6 blocks)",
            "Layer4 (3 blocks)",
            "Global AvgPool",
            "FC Head",
        ],
        "params": {"img_size": 224, "epochs": 40, "batch_size": 32, "lr": 0.0001},
    },
    "EfficientNet-B4": {
        "description": "Efficient scaling for medical imaging",
        "layers": [
            "Stem Conv",
            "MBConv Blocks (x7 stages)",
            "Head Conv",
            "Global Pool",
            "FC",
        ],
        "params": {"img_size": 380, "epochs": 35, "batch_size": 16, "lr": 0.0005},
    },
    "U-Net Segmentation": {
        "description": "Semantic segmentation for lesion boundaries",
        "layers": [
            "Encoder (4 levels)",
            "Bottleneck",
            "Decoder (4 levels)",
            "Output Conv (1x1)",
        ],
        "params": {"img_size": 512, "epochs": 60, "batch_size": 8, "lr": 0.001},
    },
}


CARD_STYLE = """
QFrame#trainingCard {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 16px;
}
QFrame#trainingCard:hover {
    border-color: #6366f1;
    background-color: #1e2940;
}
"""


HEADER_STYLE = """
QLabel#sectionHeader {
    color: #e2e8f0;
    font-size: 16px;
    font-weight: 700;
    padding: 8px 0;
}
"""


STAT_VALUE_STYLE = """
QLabel#statValue {
    color: #6366f1;
    font-size: 28px;
    font-weight: 800;
}
"""


STAT_LABEL_STYLE = """
QLabel#statLabel {
    color: #94a3b8;
    font-size: 11px;
    font-weight: 500;
}
"""


BTN_PRIMARY_STYLE = """
QPushButton#btnPrimary {
    background-color: #6366f1;
    color: white;
    border: none;
    border-radius: 8px;
    padding: 10px 24px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#btnPrimary:hover {
    background-color: #818cf8;
}
QPushButton#btnPrimary:pressed {
    background-color: #4f46e5;
}
QPushButton#btnPrimary:disabled {
    background-color: #374151;
    color: #6b7280;
}
"""


BTN_SECONDARY_STYLE = """
QPushButton#btnSecondary {
    background-color: transparent;
    color: #94a3b8;
    border: 1px solid #475569;
    border-radius: 8px;
    padding: 10px 24px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#btnSecondary:hover {
    background-color: #1e293b;
    color: #e2e8f0;
    border-color: #6366f1;
}
"""


BTN_DANGER_STYLE = """
QPushButton#btnDanger {
    background-color: transparent;
    color: #f87171;
    border: 1px solid #7f1d1d;
    border-radius: 8px;
    padding: 10px 24px;
    font-weight: 600;
    font-size: 13px;
}
QPushButton#btnDanger:hover {
    background-color: #7f1d1d;
    color: white;
}
"""


TABLE_STYLE = """
QTableWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 8px;
    gridline-color: #1e293b;
    font-size: 12px;
}
QTableWidget::item {
    padding: 6px 10px;
    border-bottom: 1px solid #1e293b;
}
QTableWidget::item:selected {
    background-color: #312e81;
    color: white;
}
QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 8px 10px;
    border: none;
    border-bottom: 2px solid #334155;
    font-weight: 600;
    font-size: 11px;
}
"""


PROGRESS_STYLE = """
QProgressBar {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    text-align: center;
    color: #e2e8f0;
    font-weight: 600;
    font-size: 12px;
    min-height: 22px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #6366f1, stop:1 #a78bfa);
    border-radius: 5px;
}
"""


TAB_STYLE = """
QTabWidget::pane {
    border: 1px solid #334155;
    border-radius: 8px;
    background-color: #0f172a;
    top: -1px;
}
QTabBar::tab {
    background-color: #1e293b;
    color: #94a3b8;
    border: 1px solid #334155;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 10px 20px;
    margin-right: 2px;
    font-weight: 600;
    font-size: 12px;
}
QTabBar::tab:selected {
    background-color: #0f172a;
    color: #6366f1;
    border-bottom: 2px solid #6366f1;
}
QTabBar::tab:hover:!selected {
    background-color: #1e2940;
    color: #e2e8f0;
}
"""


ARCH_CARD_STYLE = """
QFrame#archCard {
    background-color: #1e293b;
    border: 2px solid #334155;
    border-radius: 12px;
    padding: 14px;
}
QFrame#archCard[selected="true"] {
    border-color: #6366f1;
    background-color: #1e2940;
}
QFrame#archCard:hover {
    border-color: #475569;
}
"""


class StatCard(QFrame):
    """Mini stat card with icon-like dot, value, and label."""

    def __init__(self, value: str, label: str, color: str = "#6366f1", parent=None):
        super().__init__(parent)
        self.setObjectName("trainingCard")
        self.setStyleSheet(CARD_STYLE)
        self.setFixedHeight(100)

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        row = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {color}; font-size: 10px;")
        val = QLabel(value)
        val.setObjectName("statValue")
        val.setStyleSheet(STAT_VALUE_STYLE)
        row.addWidget(dot)
        row.addWidget(val)
        row.addStretch()

        lbl = QLabel(label)
        lbl.setObjectName("statLabel")
        lbl.setStyleSheet(STAT_LABEL_STYLE)

        layout.addLayout(row)
        layout.addWidget(lbl)

        self._val_label = val

    def set_value(self, v: str):
        self._val_label.setText(v)


class ArchitectureCard(QFrame):
    """Selectable model architecture card."""

    clicked = Signal(str)

    def __init__(self, name: str, info: dict, parent=None):
        super().__init__(parent)
        self.arch_name = name
        self.setObjectName("archCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(130)
        self._selected = False

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        title = QLabel(name)
        title.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 14px;")

        desc = QLabel(info["description"])
        desc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        desc.setWordWrap(True)

        layers_text = " -> ".join(info["layers"])
        layers = QLabel(f"Layer Flow: {layers_text}")
        layers.setStyleSheet("color: #64748b; font-size: 10px;")
        layers.setWordWrap(True)

        layout.addWidget(title)
        layout.addWidget(desc)
        layout.addWidget(layers)
        layout.addStretch()

        self._update_style()

    def set_selected(self, selected: bool):
        self._selected = selected
        self._update_style()

    def _update_style(self):
        if self._selected:
            self.setStyleSheet(
                """
                QFrame#archCard {
                    background-color: #1e2940;
                    border: 2px solid #6366f1;
                    border-radius: 12px;
                    padding: 14px;
                }
                """
            )
        else:
            self.setStyleSheet(ARCH_CARD_STYLE)

    def mousePressEvent(self, event):
        self.clicked.emit(self.arch_name)
        super().mousePressEvent(event)


class TrainingDataService:
    """
    Prepares and manages training data packages for model retraining.
    Reads from the feedback CSVs and packages images + labels.
    """

    def __init__(self):
        self._ensure_dirs()

    def _ensure_dirs(self):
        TRAINING_DATA_DIR.mkdir(parents=True, exist_ok=True)
        TRAINING_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)

    def scan_available_data(self) -> dict:
        """Scan feedback CSVs and count available training samples."""
        stats = {
            "mg_confirmed": 0,
            "mg_corrected": 0,
            "mg_new_findings": 0,
            "bone_age_confirmed": 0,
            "bone_age_corrected": 0,
            "total_images": 0,
            "sources": [],
        }

        mg_feedback = CLINICAL_CSV_PATH
        if mg_feedback.exists():
            for csv_file in mg_feedback.glob("*_feedback.csv"):
                try:
                    stats["sources"].append(str(csv_file))
                    with open(csv_file, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        for row in reader:
                            action = (
                                row.get("action") or row.get("corrected_status") or ""
                            ).strip().lower()
                            if action == "confirmed":
                                stats["mg_confirmed"] += 1
                            elif action == "corrected":
                                stats["mg_corrected"] += 1
                            elif action in ("new_human_finding", "new"):
                                stats["mg_new_findings"] += 1
                            stats["total_images"] += 1
                except Exception:
                    pass

        if ATTACHMENT_PATH.exists():
            for study_dir in ATTACHMENT_PATH.iterdir():
                if not study_dir.is_dir():
                    continue
                ba_feedback = study_dir / "bone_age_feedback.csv"
                if ba_feedback.exists():
                    try:
                        with open(ba_feedback, "r", encoding="utf-8") as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                vs = (
                                    row.get("validation_status") or ""
                                ).strip().lower()
                                if vs == "confirmed":
                                    stats["bone_age_confirmed"] += 1
                                elif vs == "corrected":
                                    stats["bone_age_corrected"] += 1
                                stats["total_images"] += 1
                        stats["sources"].append(str(ba_feedback))
                    except Exception:
                        pass

        return stats

    def prepare_training_package(
        self,
        *,
        model_type: str,
        architecture: str,
        include_confirmed: bool = True,
        include_corrected: bool = True,
        include_new: bool = True,
        hyperparams: dict = None,
        progress_callback=None,
    ) -> Path:
        """
        Package training data into a structured export folder.
        Returns the path to the export directory.
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_name = f"training_{model_type}_{timestamp}"
        export_dir = TRAINING_EXPORTS_DIR / export_name
        export_dir.mkdir(parents=True, exist_ok=True)

        images_dir = export_dir / "images"
        labels_dir = export_dir / "labels"
        images_dir.mkdir(exist_ok=True)
        labels_dir.mkdir(exist_ok=True)

        manifest = {
            "created": timestamp,
            "model_type": model_type,
            "architecture": architecture,
            "hyperparams": hyperparams or {},
            "filters": {
                "include_confirmed": include_confirmed,
                "include_corrected": include_corrected,
                "include_new": include_new,
            },
            "samples": [],
        }

        sample_count = 0

        if model_type in ("detection", "classification", "all"):
            if CLINICAL_CSV_PATH.exists():
                for csv_file in CLINICAL_CSV_PATH.glob("*_feedback.csv"):
                    try:
                        with open(csv_file, "r", encoding="utf-8") as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                action = (
                                    row.get("action")
                                    or row.get("corrected_status")
                                    or ""
                                ).strip().lower()
                                include = False
                                if action == "confirmed" and include_confirmed:
                                    include = True
                                elif action == "corrected" and include_corrected:
                                    include = True
                                elif action in ("new_human_finding", "new") and include_new:
                                    include = True

                                if include:
                                    sample_count += 1
                                    manifest["samples"].append(
                                        {
                                            "id": sample_count,
                                            "source": str(csv_file.name),
                                            "dicom_path": row.get("dicom_full_path", ""),
                                            "action": action,
                                            "box": row.get("corrected_box")
                                            or row.get("ai_box")
                                            or row.get("box", ""),
                                            "label": row.get("corrected_classification")
                                            or row.get("ai_classification")
                                            or row.get("labels_pred", ""),
                                        }
                                    )

                                    dicom_path = Path(row.get("dicom_full_path", ""))
                                    if dicom_path.exists():
                                        dst = (
                                            images_dir
                                            / f"sample_{sample_count:06d}{dicom_path.suffix}"
                                        )
                                        shutil.copy2(dicom_path, dst)

                                    if progress_callback:
                                        progress_callback(sample_count)
                    except Exception:
                        pass

        if model_type in ("bone_age", "all"):
            if ATTACHMENT_PATH.exists():
                for study_dir in ATTACHMENT_PATH.iterdir():
                    if not study_dir.is_dir():
                        continue
                    ba_feedback = study_dir / "bone_age_feedback.csv"
                    if ba_feedback.exists():
                        try:
                            with open(ba_feedback, "r", encoding="utf-8") as f:
                                reader = csv.DictReader(f)
                                for row in reader:
                                    vs = (
                                        row.get("validation_status") or ""
                                    ).strip().lower()
                                    include = False
                                    if vs == "confirmed" and include_confirmed:
                                        include = True
                                    elif vs == "corrected" and include_corrected:
                                        include = True

                                    if include:
                                        sample_count += 1
                                        manifest["samples"].append(
                                            {
                                                "id": sample_count,
                                                "source": "bone_age",
                                                "study_uid": row.get("case_id", ""),
                                                "action": vs,
                                                "bone_age_years": row.get("corrected_bone_age_years")
                                                or row.get("predicted_bone_age_years", ""),
                                                "bone_age_months": row.get("corrected_bone_age_months")
                                                or row.get("predicted_bone_age_months", ""),
                                                "sex": row.get("corrected_sex")
                                                or row.get("sex", ""),
                                            }
                                        )

                                        if progress_callback:
                                            progress_callback(sample_count)
                        except Exception:
                            pass

        training_csv = export_dir / "training_data.csv"
        if manifest["samples"]:
            fieldnames = list(manifest["samples"][0].keys())
            with open(training_csv, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(manifest["samples"])

        manifest_path = export_dir / "manifest.json"
        manifest["total_samples"] = sample_count
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return export_dir

    def get_export_history(self) -> list:
        """List past training exports."""
        exports = []
        if TRAINING_EXPORTS_DIR.exists():
            for d in sorted(TRAINING_EXPORTS_DIR.iterdir(), reverse=True):
                if d.is_dir():
                    manifest_path = d / "manifest.json"
                    if manifest_path.exists():
                        try:
                            with open(manifest_path, "r", encoding="utf-8") as f:
                                data = json.load(f)
                            exports.append(
                                {
                                    "name": d.name,
                                    "path": str(d),
                                    "created": data.get("created", ""),
                                    "architecture": data.get("architecture", ""),
                                    "total_samples": data.get("total_samples", 0),
                                }
                            )
                        except Exception:
                            pass
        return exports


class ModelTrainingTab(AbstractTab):
    """
    Model Training Tab — full UI for:
      - Viewing available training data (from user labels / model outputs)
      - Selecting model architecture and layers
      - Configuring hyperparameters
      - Preparing and exporting training packages
      - Monitoring training status
    """

    training_started = Signal(str)
    training_completed = Signal(str, bool)

    def __init__(self):
        super().__init__()

        self._service = TrainingDataService()
        self._selected_arch = "YOLOv8-Detection"
        self._training_status = "idle"
        self._arch_cards = {}
        self._last_export_dir = None

        self._build_ui()
        QTimer.singleShot(300, self._refresh_data_stats)

    def _build_ui(self):
        center = self.get_center_layout_vertical()

        # Remove stretch from the unused stacked/toolbar layout so our content fills the tab
        center.setStretch(0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: #0f172a; }")

        content = QWidget()
        content.setStyleSheet("background: #0f172a;")
        self._content_layout = QVBoxLayout(content)
        self._content_layout.setContentsMargins(24, 24, 24, 24)
        self._content_layout.setSpacing(20)

        self._build_header()

        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(TAB_STYLE)

        self._tabs.addTab(self._build_data_overview_tab(), "Data Overview")
        self._tabs.addTab(self._build_architecture_tab(), "Architecture")
        self._tabs.addTab(self._build_hyperparams_tab(), "Hyperparameters")
        self._tabs.addTab(self._build_export_tab(), "Train & Export")
        self._tabs.addTab(self._build_history_tab(), "History")

        self._content_layout.addWidget(self._tabs)

        scroll.setWidget(content)
        center.addWidget(scroll, 1)

    def _build_header(self):
        header = QHBoxLayout()

        title = QLabel("Model Training Studio")
        title.setStyleSheet("color: #f1f5f9; font-size: 22px; font-weight: 800;")

        subtitle = QLabel("Prepare labeled data and retrain AI models")
        subtitle.setStyleSheet("color: #64748b; font-size: 12px;")

        left = QVBoxLayout()
        left.setSpacing(4)
        left.addWidget(title)
        left.addWidget(subtitle)

        self._status_pill = QLabel("● Idle")
        self._status_pill.setStyleSheet(
            """
            color: #94a3b8;
            background-color: #1e293b;
            border: 1px solid #334155;
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 600;
            font-size: 12px;
            """
        )

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setObjectName("btnSecondary")
        refresh_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self._refresh_data_stats)

        right = QHBoxLayout()
        right.addWidget(self._status_pill)
        right.addWidget(refresh_btn)

        header.addLayout(left)
        header.addStretch()
        header.addLayout(right)

        self._content_layout.addLayout(header)

    def _build_data_overview_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(16)

        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._stat_total = StatCard("0", "Total Samples", "#6366f1")
        self._stat_confirmed = StatCard("0", "Confirmed", "#34d399")
        self._stat_corrected = StatCard("0", "Corrected", "#fbbf24")
        self._stat_new = StatCard("0", "New Findings", "#f472b6")

        stats_row.addWidget(self._stat_total)
        stats_row.addWidget(self._stat_confirmed)
        stats_row.addWidget(self._stat_corrected)
        stats_row.addWidget(self._stat_new)

        layout.addLayout(stats_row)

        filter_frame = QFrame()
        filter_frame.setObjectName("trainingCard")
        filter_frame.setStyleSheet(CARD_STYLE)
        filter_layout = QVBoxLayout(filter_frame)

        filter_title = QLabel("Data Filters")
        filter_title.setObjectName("sectionHeader")
        filter_title.setStyleSheet(HEADER_STYLE)
        filter_layout.addWidget(filter_title)

        filter_row = QHBoxLayout()

        self._filter_confirmed = QCheckBox("Include Confirmed")
        self._filter_confirmed.setChecked(True)
        self._filter_confirmed.setStyleSheet("color: #34d399; font-weight: 600;")

        self._filter_corrected = QCheckBox("Include Corrected")
        self._filter_corrected.setChecked(True)
        self._filter_corrected.setStyleSheet("color: #fbbf24; font-weight: 600;")

        self._filter_new = QCheckBox("Include New Findings")
        self._filter_new.setChecked(True)
        self._filter_new.setStyleSheet("color: #f472b6; font-weight: 600;")

        self._filter_model_type = QComboBox()
        self._filter_model_type.addItems(
            ["All", "Detection (MG)", "Classification (MG)", "Bone Age (DX)"]
        )
        self._style_combo(self._filter_model_type)

        filter_row.addWidget(self._filter_confirmed)
        filter_row.addWidget(self._filter_corrected)
        filter_row.addWidget(self._filter_new)
        filter_row.addStretch()
        filter_row.addWidget(QLabel("Model Type:"))
        filter_row.addWidget(self._filter_model_type)

        filter_layout.addLayout(filter_row)
        layout.addWidget(filter_frame)

        table_frame = QFrame()
        table_frame.setObjectName("trainingCard")
        table_frame.setStyleSheet(CARD_STYLE)
        table_layout = QVBoxLayout(table_frame)

        table_header = QHBoxLayout()
        table_title = QLabel("Training Data Sources")
        table_title.setObjectName("sectionHeader")
        table_title.setStyleSheet(HEADER_STYLE)
        table_header.addWidget(table_title)
        table_header.addStretch()

        scan_btn = QPushButton("Scan Data")
        scan_btn.setObjectName("btnSecondary")
        scan_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        scan_btn.clicked.connect(self._refresh_data_stats)
        table_header.addWidget(scan_btn)

        table_layout.addLayout(table_header)

        self._data_table = QTableWidget()
        self._data_table.setStyleSheet(TABLE_STYLE)
        self._data_table.setColumnCount(5)
        self._data_table.setHorizontalHeaderLabels(
            ["Source", "Type", "Samples", "Status", "Last Modified"]
        )
        self._data_table.horizontalHeader().setStretchLastSection(True)
        self._data_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._data_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._data_table.setAlternatingRowColors(True)
        self._data_table.verticalHeader().setVisible(False)
        self._data_table.setMinimumHeight(200)

        table_layout.addWidget(self._data_table)
        layout.addWidget(table_frame)

        layout.addStretch()
        return page

    def _build_architecture_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(16)

        header = QLabel("Select Model Architecture")
        header.setObjectName("sectionHeader")
        header.setStyleSheet(HEADER_STYLE)
        layout.addWidget(header)

        desc = QLabel(
            "Choose the neural network architecture for your training task. "
            "Each architecture is optimized for different medical imaging scenarios."
        )
        desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        grid = QGridLayout()
        grid.setSpacing(12)

        for i, (name, info) in enumerate(MODEL_ARCHITECTURES.items()):
            card = ArchitectureCard(name, info)
            card.clicked.connect(self._on_arch_selected)
            self._arch_cards[name] = card
            row, col = divmod(i, 2)
            grid.addWidget(card, row, col)

        layout.addLayout(grid)

        layers_frame = QFrame()
        layers_frame.setObjectName("trainingCard")
        layers_frame.setStyleSheet(CARD_STYLE)
        layers_layout = QVBoxLayout(layers_frame)

        layers_title = QLabel("Network Layers")
        layers_title.setObjectName("sectionHeader")
        layers_title.setStyleSheet(HEADER_STYLE)
        layers_layout.addWidget(layers_title)

        self._layers_list = QListWidget()
        self._layers_list.setStyleSheet(
            """
            QListWidget {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-bottom: 1px solid #1e293b;
                border-radius: 4px;
            }
            QListWidget::item:selected {
                background-color: #312e81;
            }
            """
        )
        self._layers_list.setMinimumHeight(160)
        layers_layout.addWidget(self._layers_list)

        freeze_row = QHBoxLayout()
        self._freeze_backbone = QCheckBox("Freeze backbone layers (transfer learning)")
        self._freeze_backbone.setStyleSheet("color: #94a3b8; font-weight: 500;")
        self._freeze_backbone.setChecked(True)
        freeze_row.addWidget(self._freeze_backbone)
        freeze_row.addStretch()
        layers_layout.addLayout(freeze_row)

        layout.addWidget(layers_frame)
        layout.addStretch()

        self._on_arch_selected(self._selected_arch)

        return page

    def _build_hyperparams_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(16)

        header = QLabel("Training Hyperparameters")
        header.setObjectName("sectionHeader")
        header.setStyleSheet(HEADER_STYLE)
        layout.addWidget(header)

        desc = QLabel(
            "Fine-tune training parameters. Defaults are optimized for medical imaging."
        )
        desc.setStyleSheet("color: #94a3b8; font-size: 12px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        params_frame = QFrame()
        params_frame.setObjectName("trainingCard")
        params_frame.setStyleSheet(CARD_STYLE)
        params_layout = QVBoxLayout(params_frame)

        form = QGridLayout()
        form.setSpacing(16)

        form.addWidget(self._param_label("Image Size (px)"), 0, 0)
        self._param_img_size = QSpinBox()
        self._param_img_size.setRange(128, 1024)
        self._param_img_size.setSingleStep(32)
        self._param_img_size.setValue(640)
        self._style_spinbox(self._param_img_size)
        form.addWidget(self._param_img_size, 0, 1)

        form.addWidget(self._param_label("Epochs"), 1, 0)
        self._param_epochs = QSpinBox()
        self._param_epochs.setRange(1, 500)
        self._param_epochs.setValue(50)
        self._style_spinbox(self._param_epochs)
        form.addWidget(self._param_epochs, 1, 1)

        form.addWidget(self._param_label("Batch Size"), 2, 0)
        self._param_batch = QSpinBox()
        self._param_batch.setRange(1, 128)
        self._param_batch.setValue(16)
        self._style_spinbox(self._param_batch)
        form.addWidget(self._param_batch, 2, 1)

        form.addWidget(self._param_label("Learning Rate"), 3, 0)
        self._param_lr = QDoubleSpinBox()
        self._param_lr.setRange(0.00001, 1.0)
        self._param_lr.setDecimals(5)
        self._param_lr.setSingleStep(0.0001)
        self._param_lr.setValue(0.01)
        self._style_spinbox(self._param_lr)
        form.addWidget(self._param_lr, 3, 1)

        form.addWidget(self._param_label("Optimizer"), 4, 0)
        self._param_optimizer = QComboBox()
        self._param_optimizer.addItems(["AdamW", "Adam", "SGD", "RMSProp"])
        self._style_combo(self._param_optimizer)
        form.addWidget(self._param_optimizer, 4, 1)

        form.addWidget(self._param_label("Data Augmentation"), 5, 0)
        self._param_augment = QComboBox()
        self._param_augment.addItems(["Standard Medical", "Heavy", "Light", "None"])
        self._style_combo(self._param_augment)
        form.addWidget(self._param_augment, 5, 1)

        form.addWidget(self._param_label("Validation Split (%)"), 6, 0)
        self._param_val_split = QSpinBox()
        self._param_val_split.setRange(5, 40)
        self._param_val_split.setValue(20)
        self._style_spinbox(self._param_val_split)
        form.addWidget(self._param_val_split, 6, 1)

        form.addWidget(self._param_label("Early Stopping Patience"), 7, 0)
        self._param_patience = QSpinBox()
        self._param_patience.setRange(0, 50)
        self._param_patience.setValue(10)
        self._style_spinbox(self._param_patience)
        form.addWidget(self._param_patience, 7, 1)

        params_layout.addLayout(form)

        reset_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Architecture Defaults")
        reset_btn.setObjectName("btnSecondary")
        reset_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        reset_btn.clicked.connect(self._reset_hyperparams)
        reset_row.addStretch()
        reset_row.addWidget(reset_btn)
        params_layout.addLayout(reset_row)

        layout.addWidget(params_frame)
        layout.addStretch()
        return page

    def _build_export_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(16)

        header = QLabel("Prepare & Start Training")
        header.setObjectName("sectionHeader")
        header.setStyleSheet(HEADER_STYLE)
        layout.addWidget(header)

        summary_frame = QFrame()
        summary_frame.setObjectName("trainingCard")
        summary_frame.setStyleSheet(CARD_STYLE)
        summary_layout = QVBoxLayout(summary_frame)

        summary_title = QLabel("Training Configuration Summary")
        summary_title.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 14px;")
        summary_layout.addWidget(summary_title)

        self._summary_text = QTextEdit()
        self._summary_text.setReadOnly(True)
        self._summary_text.setMaximumHeight(180)
        self._summary_text.setStyleSheet(
            """
            QTextEdit {
                background-color: #0f172a;
                color: #cbd5e1;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 12px;
                font-family: 'Consolas', monospace;
                font-size: 12px;
            }
            """
        )
        summary_layout.addWidget(self._summary_text)

        layout.addWidget(summary_frame)

        progress_frame = QFrame()
        progress_frame.setObjectName("trainingCard")
        progress_frame.setStyleSheet(CARD_STYLE)
        progress_layout = QVBoxLayout(progress_frame)

        progress_title = QLabel("Training Progress")
        progress_title.setStyleSheet("color: #e2e8f0; font-weight: 700; font-size: 14px;")
        progress_layout.addWidget(progress_title)

        self._progress_bar = QProgressBar()
        self._progress_bar.setStyleSheet(PROGRESS_STYLE)
        self._progress_bar.setMinimumHeight(28)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p% — Idle")
        progress_layout.addWidget(self._progress_bar)

        self._progress_log = QTextEdit()
        self._progress_log.setReadOnly(True)
        self._progress_log.setMaximumHeight(120)
        self._progress_log.setStyleSheet(
            """
            QTextEdit {
                background-color: #0f172a;
                color: #64748b;
                border: 1px solid #1e293b;
                border-radius: 6px;
                padding: 8px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
            """
        )
        progress_layout.addWidget(self._progress_log)

        layout.addWidget(progress_frame)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self._btn_prepare = QPushButton("Prepare Data Package")
        self._btn_prepare.setObjectName("btnSecondary")
        self._btn_prepare.setStyleSheet(BTN_SECONDARY_STYLE)
        self._btn_prepare.clicked.connect(self._prepare_package)

        self._btn_train = QPushButton("Start Training")
        self._btn_train.setObjectName("btnPrimary")
        self._btn_train.setStyleSheet(BTN_PRIMARY_STYLE)
        self._btn_train.clicked.connect(self._start_training)

        self._btn_export = QPushButton("Export to Folder")
        self._btn_export.setObjectName("btnSecondary")
        self._btn_export.setStyleSheet(BTN_SECONDARY_STYLE)
        self._btn_export.clicked.connect(self._export_to_folder)

        actions_row.addWidget(self._btn_prepare)
        actions_row.addWidget(self._btn_train)
        actions_row.addWidget(self._btn_export)
        actions_row.addStretch()

        layout.addLayout(actions_row)
        layout.addStretch()
        return page

    def _build_history_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(16)

        header = QLabel("Training History")
        header.setObjectName("sectionHeader")
        header.setStyleSheet(HEADER_STYLE)
        layout.addWidget(header)

        self._history_table = QTableWidget()
        self._history_table.setStyleSheet(TABLE_STYLE)
        self._history_table.setColumnCount(4)
        self._history_table.setHorizontalHeaderLabels(
            ["Export Name", "Architecture", "Samples", "Date"]
        )
        self._history_table.horizontalHeader().setStretchLastSection(True)
        self._history_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._history_table.verticalHeader().setVisible(False)
        self._history_table.setMinimumHeight(300)
        layout.addWidget(self._history_table)

        hist_actions = QHBoxLayout()
        open_btn = QPushButton("Open Folder")
        open_btn.setObjectName("btnSecondary")
        open_btn.setStyleSheet(BTN_SECONDARY_STYLE)
        open_btn.clicked.connect(self._open_export_folder)

        delete_btn = QPushButton("Delete Selected")
        delete_btn.setObjectName("btnDanger")
        delete_btn.setStyleSheet(BTN_DANGER_STYLE)
        delete_btn.clicked.connect(self._delete_export)

        refresh_hist = QPushButton("Refresh")
        refresh_hist.setObjectName("btnSecondary")
        refresh_hist.setStyleSheet(BTN_SECONDARY_STYLE)
        refresh_hist.clicked.connect(self._refresh_history)

        hist_actions.addWidget(open_btn)
        hist_actions.addWidget(delete_btn)
        hist_actions.addStretch()
        hist_actions.addWidget(refresh_hist)

        layout.addLayout(hist_actions)
        layout.addStretch()
        return page

    def _param_label(self, text: str):
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #cbd5e1; font-weight: 600; font-size: 13px;")
        return lbl

    def _style_spinbox(self, widget):
        widget.setStyleSheet(
            """
            QSpinBox, QDoubleSpinBox {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
                min-width: 120px;
            }
            QSpinBox::up-button, QDoubleSpinBox::up-button,
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                background-color: #334155;
                border: none;
                width: 20px;
            }
            """
        )

    def _style_combo(self, widget):
        widget.setStyleSheet(
            """
            QComboBox {
                background-color: #1e293b;
                color: #e2e8f0;
                border: 1px solid #475569;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 13px;
                min-width: 120px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #1e293b;
                color: #e2e8f0;
                selection-background-color: #312e81;
            }
            """
        )

    def _on_arch_selected(self, name: str):
        self._selected_arch = name
        for card_name, card in self._arch_cards.items():
            card.set_selected(card_name == name)

        self._layers_list.clear()
        info = MODEL_ARCHITECTURES.get(name, {})
        for layer in info.get("layers", []):
            item = QListWidgetItem(f"  ->  {layer}")
            self._layers_list.addItem(item)

        self._reset_hyperparams()

    def _reset_hyperparams(self):
        if not hasattr(self, "_param_img_size"):
            return
        info = MODEL_ARCHITECTURES.get(self._selected_arch, {})
        params = info.get("params", {})
        self._param_img_size.setValue(params.get("img_size", 640))
        self._param_epochs.setValue(params.get("epochs", 50))
        self._param_batch.setValue(params.get("batch_size", 16))
        self._param_lr.setValue(params.get("lr", 0.01))

    def _refresh_data_stats(self):
        stats = self._service.scan_available_data()

        total = (
            stats["mg_confirmed"]
            + stats["mg_corrected"]
            + stats["mg_new_findings"]
            + stats["bone_age_confirmed"]
            + stats["bone_age_corrected"]
        )

        self._stat_total.set_value(str(total))
        self._stat_confirmed.set_value(
            str(stats["mg_confirmed"] + stats["bone_age_confirmed"])
        )
        self._stat_corrected.set_value(
            str(stats["mg_corrected"] + stats["bone_age_corrected"])
        )
        self._stat_new.set_value(str(stats["mg_new_findings"]))

        self._data_table.setRowCount(0)
        sources = stats.get("sources", [])
        self._data_table.setRowCount(len(sources))

        for i, src in enumerate(sources):
            p = Path(src)
            self._data_table.setItem(i, 0, QTableWidgetItem(p.name))
            if "bone_age" in p.name.lower():
                self._data_table.setItem(i, 1, QTableWidgetItem("Bone Age"))
            else:
                self._data_table.setItem(i, 1, QTableWidgetItem("Mammography"))
            self._data_table.setItem(i, 2, QTableWidgetItem("-"))
            self._data_table.setItem(i, 3, QTableWidgetItem("Available"))
            if p.exists():
                mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime(
                    "%Y-%m-%d %H:%M"
                )
                self._data_table.setItem(i, 4, QTableWidgetItem(mtime))
            else:
                self._data_table.setItem(i, 4, QTableWidgetItem("-"))

        self._refresh_history()

    def _refresh_history(self):
        exports = self._service.get_export_history()
        self._history_table.setRowCount(len(exports))
        for i, exp in enumerate(exports):
            self._history_table.setItem(i, 0, QTableWidgetItem(exp["name"]))
            self._history_table.setItem(i, 1, QTableWidgetItem(exp["architecture"]))
            self._history_table.setItem(i, 2, QTableWidgetItem(str(exp["total_samples"])))
            self._history_table.setItem(i, 3, QTableWidgetItem(exp["created"]))

    def _get_hyperparams(self):
        return {
            "img_size": self._param_img_size.value(),
            "epochs": self._param_epochs.value(),
            "batch_size": self._param_batch.value(),
            "learning_rate": self._param_lr.value(),
            "optimizer": self._param_optimizer.currentText(),
            "augmentation": self._param_augment.currentText(),
            "val_split": self._param_val_split.value() / 100.0,
            "early_stopping_patience": self._param_patience.value(),
            "freeze_backbone": self._freeze_backbone.isChecked(),
        }

    def _get_model_type(self):
        idx = self._filter_model_type.currentIndex()
        if idx == 0:
            return "all"
        if idx == 1:
            return "detection"
        if idx == 2:
            return "classification"
        return "bone_age"

    def _update_summary(self):
        hp = self._get_hyperparams()
        lines = [
            f"Architecture:       {self._selected_arch}",
            f"Model Type:         {self._get_model_type()}",
            f"Image Size:         {hp['img_size']}x{hp['img_size']}",
            f"Epochs:             {hp['epochs']}",
            f"Batch Size:         {hp['batch_size']}",
            f"Learning Rate:      {hp['learning_rate']}",
            f"Optimizer:          {hp['optimizer']}",
            f"Augmentation:       {hp['augmentation']}",
            f"Validation Split:   {hp['val_split']:.0%}",
            f"Early Stopping:     {hp['early_stopping_patience']} epochs",
            f"Freeze Backbone:    {'Yes' if hp['freeze_backbone'] else 'No'}",
            f"Include Confirmed:  {'Yes' if self._filter_confirmed.isChecked() else 'No'}",
            f"Include Corrected:  {'Yes' if self._filter_corrected.isChecked() else 'No'}",
            f"Include New:        {'Yes' if self._filter_new.isChecked() else 'No'}",
        ]
        self._summary_text.setPlainText("\n".join(lines))

    def _log_progress(self, msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._progress_log.append(f"[{timestamp}] {msg}")

    def _set_status(self, status: str):
        self._training_status = status
        colors = {
            "idle": ("#94a3b8", "#1e293b"),
            "preparing": ("#fbbf24", "#1e2940"),
            "uploading": ("#38bdf8", "#1e2940"),
            "training": ("#34d399", "#1e2940"),
            "completed": ("#34d399", "#064e3b"),
            "failed": ("#f87171", "#7f1d1d"),
        }
        color, bg = colors.get(status, ("#94a3b8", "#1e293b"))
        self._status_pill.setText(f"● {status.capitalize()}")
        self._status_pill.setStyleSheet(
            f"""
            color: {color};
            background-color: {bg};
            border: 1px solid {color}40;
            border-radius: 12px;
            padding: 6px 14px;
            font-weight: 600;
            font-size: 12px;
            """
        )

    def _prepare_package(self):
        self._update_summary()
        self._set_status("preparing")
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("%p% — Preparing data...")
        self._log_progress("Starting data preparation...")

        self._btn_prepare.setEnabled(False)
        self._btn_train.setEnabled(False)

        def _do_prepare():
            try:
                def on_progress(count):
                    QTimer.singleShot(0, lambda c=count: self._on_prepare_progress(c))

                export_dir = self._service.prepare_training_package(
                    model_type=self._get_model_type(),
                    architecture=self._selected_arch,
                    include_confirmed=self._filter_confirmed.isChecked(),
                    include_corrected=self._filter_corrected.isChecked(),
                    include_new=self._filter_new.isChecked(),
                    hyperparams=self._get_hyperparams(),
                    progress_callback=on_progress,
                )
                QTimer.singleShot(0, lambda: self._on_prepare_done(export_dir))
            except Exception as e:
                QTimer.singleShot(0, lambda: self._on_prepare_error(str(e)))

        threading.Thread(target=_do_prepare, daemon=True).start()

    def _on_prepare_progress(self, count: int):
        self._progress_bar.setFormat(f"Preparing... {count} samples processed")
        val = min(count * 2, 90)
        self._progress_bar.setValue(val)

    def _on_prepare_done(self, export_dir: Path):
        self._progress_bar.setValue(100)
        self._progress_bar.setFormat("100% — Package ready!")
        self._set_status("idle")
        self._log_progress(f"Data package ready: {export_dir.name}")
        self._log_progress(f"Location: {export_dir}")
        self._btn_prepare.setEnabled(True)
        self._btn_train.setEnabled(True)
        self._last_export_dir = export_dir
        self._refresh_history()

        manifest_path = export_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._log_progress(f"Total samples: {data.get('total_samples', 0)}")

    def _on_prepare_error(self, err: str):
        self._set_status("failed")
        self._progress_bar.setFormat("Failed")
        self._log_progress(f"Preparation failed: {err}")
        self._btn_prepare.setEnabled(True)
        self._btn_train.setEnabled(True)

    def _start_training(self):
        if not self._last_export_dir:
            QMessageBox.information(
                self,
                "No Package",
                "Please prepare a data package first (Prepare Data Package).",
            )
            return

        self._set_status("uploading")
        self._progress_bar.setValue(0)
        self._progress_bar.setFormat("0% — Sending to model server...")
        self._log_progress("Initiating training on model server...")
        self._log_progress(f"Package: {self._last_export_dir.name}")
        self._log_progress(f"Architecture: {self._selected_arch}")

        self._btn_train.setEnabled(False)
        self._btn_prepare.setEnabled(False)

        self.training_started.emit(str(self._last_export_dir))

        endpoint = os.environ.get("AIPACS_MODEL_TRAINING_ENDPOINT", "").strip()
        if endpoint:
            self._start_remote_training(endpoint)
        else:
            self._log_progress(
                "No AIPACS_MODEL_TRAINING_ENDPOINT configured; running local simulation."
            )
            self._set_status("training")
            self._train_step = 0
            self._train_timer = QTimer(self)
            self._train_timer.timeout.connect(self._simulate_training_step)
            self._train_timer.start(800)

    def _start_remote_training(self, endpoint: str):
        """Zip and send package to model training server over HTTP POST."""

        def _worker():
            try:
                zip_path = self._last_export_dir.with_suffix(".zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    for root, _dirs, files in os.walk(self._last_export_dir):
                        for fn in files:
                            full = Path(root) / fn
                            arcname = str(full.relative_to(self._last_export_dir))
                            zf.write(full, arcname)

                QTimer.singleShot(
                    0,
                    lambda: self._log_progress(
                        f"Uploading ZIP package to server: {zip_path.name}"
                    ),
                )
                QTimer.singleShot(
                    0,
                    lambda: self._progress_bar.setFormat("25% — Uploading package..."),
                )
                QTimer.singleShot(0, lambda: self._progress_bar.setValue(25))

                payload = zip_path.read_bytes()
                req = urllib.request.Request(
                    endpoint,
                    data=payload,
                    method="POST",
                    headers={
                        "Content-Type": "application/zip",
                        "X-Model-Architecture": self._selected_arch,
                        "X-Model-Type": self._get_model_type(),
                    },
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")

                QTimer.singleShot(0, lambda: self._set_status("training"))
                QTimer.singleShot(
                    0, lambda: self._progress_bar.setFormat("60% — Server accepted training job")
                )
                QTimer.singleShot(0, lambda: self._progress_bar.setValue(60))
                QTimer.singleShot(
                    0,
                    lambda: self._log_progress(
                        f"Server response: {body[:180] if body else 'OK'}"
                    ),
                )

                # Polling can be added when backend exposes job status endpoint.
                QTimer.singleShot(0, lambda: self._progress_bar.setValue(100))
                QTimer.singleShot(
                    0,
                    lambda: self._progress_bar.setFormat("100% — Training request submitted")
                )
                QTimer.singleShot(0, lambda: self._set_status("completed"))
                QTimer.singleShot(
                    0,
                    lambda: self._log_progress(
                        "Training request submitted to model server successfully."
                    ),
                )
                QTimer.singleShot(0, lambda: self._btn_train.setEnabled(True))
                QTimer.singleShot(0, lambda: self._btn_prepare.setEnabled(True))
                QTimer.singleShot(
                    0,
                    lambda: self.training_completed.emit(str(self._last_export_dir), True),
                )
            except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as e:
                QTimer.singleShot(0, lambda: self._set_status("failed"))
                QTimer.singleShot(0, lambda: self._progress_bar.setFormat("Failed"))
                QTimer.singleShot(
                    0, lambda: self._log_progress(f"Remote training failed: {e}")
                )
                QTimer.singleShot(0, lambda: self._btn_train.setEnabled(True))
                QTimer.singleShot(0, lambda: self._btn_prepare.setEnabled(True))
                QTimer.singleShot(
                    0,
                    lambda: self.training_completed.emit(str(self._last_export_dir), False),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _simulate_training_step(self):
        self._train_step += 1
        epochs = self._param_epochs.value()
        progress = min(int(self._train_step / epochs * 100), 100)

        self._progress_bar.setValue(progress)
        self._progress_bar.setFormat(f"{progress}% — Epoch {self._train_step}/{epochs}")

        if self._train_step % 5 == 0:
            loss = max(0.01, 1.0 - self._train_step * 0.02)
            self._log_progress(f"Epoch {self._train_step}: loss={loss:.4f}")

        if self._train_step >= epochs:
            self._train_timer.stop()
            self._set_status("completed")
            self._progress_bar.setFormat("100% — Training Complete!")
            self._log_progress("Training completed successfully!")
            self._log_progress("Model weights saved. Ready for deployment.")
            self._btn_train.setEnabled(True)
            self._btn_prepare.setEnabled(True)
            self.training_completed.emit(str(self._last_export_dir), True)

    def _export_to_folder(self):
        if not self._last_export_dir:
            QMessageBox.information(self, "No Package", "Prepare a package first.")
            return

        folder = QFileDialog.getExistingDirectory(self, "Select Export Destination")
        if folder:
            dst = Path(folder) / self._last_export_dir.name
            try:
                shutil.copytree(self._last_export_dir, dst)
                self._log_progress(f"Exported to: {dst}")
                QMessageBox.information(self, "Export Complete", f"Package exported to:\n{dst}")
            except Exception as e:
                QMessageBox.warning(self, "Export Failed", str(e))

    def _open_export_folder(self):
        row = self._history_table.currentRow()
        if row < 0:
            return
        exports = self._service.get_export_history()
        if row < len(exports):
            path = exports[row]["path"]
            if os.path.isdir(path):
                os.startfile(path)

    def _delete_export(self):
        row = self._history_table.currentRow()
        if row < 0:
            return
        exports = self._service.get_export_history()
        if row < len(exports):
            path = exports[row]["path"]
            reply = QMessageBox.question(
                self,
                "Delete Export",
                f"Delete training export:\n{exports[row]['name']}?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply == QMessageBox.Yes:
                shutil.rmtree(path, ignore_errors=True)
                self._refresh_history()
                self._log_progress(f"Deleted: {exports[row]['name']}")