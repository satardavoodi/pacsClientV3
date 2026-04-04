from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class OfflineCloudExportDialog(QDialog):
    """Preview selected local studies and choose the target Offline Cloud server."""

    def __init__(
        self,
        parent=None,
        *,
        studies: list[dict] | None = None,
        cloud_servers: list[dict] | None = None,
        skipped_count: int = 0,
    ):
        super().__init__(parent)
        self._studies = list(studies or [])
        self._cloud_servers = list(cloud_servers or [])
        self._selected_server: dict | None = None
        self._skipped_count = max(0, int(skipped_count or 0))

        self._setup_ui()
        self._populate()

        self.setWindowTitle("Offline Cloud Export")
        self.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(1040, 700)

    def selected_server(self) -> dict | None:
        return self._selected_server

    def _setup_ui(self):
        self.setObjectName("OfflineCloudExportDialog")
        self.setStyleSheet(
            """
            QDialog#OfflineCloudExportDialog {
                background: #091018;
                color: #e8eef8;
            }
            QFrame#HeroCard {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #132033, stop:0.6 #0d1726, stop:1 #0a1320);
                border: 1px solid #27405f;
                border-radius: 22px;
            }
            QFrame#SummaryCard, QFrame#SelectCard, QFrame#TableCard, QFrame#FooterCard {
                background: #0f1824;
                border: 1px solid #233346;
                border-radius: 18px;
            }
            QLabel {
                color: #e8eef8;
            }
            QLabel#HeroEyebrow {
                color: #8fb7ff;
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 0.08em;
            }
            QLabel#HeroTitle {
                color: #f8fbff;
                font-size: 28px;
                font-weight: 800;
            }
            QLabel#HeroBody {
                color: #bdd0e7;
                font-size: 14px;
                line-height: 1.45;
            }
            QLabel#SectionTitle {
                color: #f8fbff;
                font-size: 17px;
                font-weight: 700;
            }
            QLabel#SectionHint {
                color: #8ea3ba;
                font-size: 13px;
            }
            QFrame#MetricChip {
                background: #121f2e;
                border: 1px solid #2b425d;
                border-radius: 16px;
            }
            QLabel#MetricValue {
                color: #f8fbff;
                font-size: 22px;
                font-weight: 800;
            }
            QLabel#MetricLabel {
                color: #95a9c0;
                font-size: 12px;
                font-weight: 600;
            }
            QLabel#ServerPath {
                background: #101c2a;
                border: 1px solid #26384d;
                border-radius: 12px;
                color: #c6d5e6;
                padding: 10px 12px;
                font-size: 12px;
            }
            QComboBox {
                background: #132131;
                color: #eff6ff;
                border: 1px solid #2c4460;
                border-radius: 12px;
                padding: 9px 12px;
                min-height: 42px;
                font-size: 14px;
                font-weight: 600;
            }
            QComboBox:hover, QComboBox:focus {
                border-color: #66a4ff;
            }
            QTableWidget {
                background: #0c141f;
                color: #edf4ff;
                border: 1px solid #223245;
                border-radius: 14px;
                gridline-color: #1a2533;
                alternate-background-color: #101926;
                selection-background-color: #204a7a;
                selection-color: #ffffff;
                font-size: 13px;
            }
            QTableWidget::item {
                padding: 8px 10px;
                border-bottom: 1px solid #162332;
            }
            QHeaderView::section {
                background: #121d2a;
                color: #cfe0f3;
                padding: 10px 10px;
                border: none;
                border-right: 1px solid #1c2c3e;
                border-bottom: 1px solid #1f3246;
                font-size: 12px;
                font-weight: 700;
            }
            QPushButton {
                background: #162333;
                color: #e8eef8;
                border: 1px solid #294059;
                border-radius: 12px;
                padding: 10px 18px;
                min-height: 42px;
                font-size: 14px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #1d2e43;
                border-color: #4d7db4;
            }
            QPushButton#PrimaryButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #4f9cff, stop:1 #2e6fe8);
                color: #ffffff;
                border: 1px solid #4f9cff;
            }
            QPushButton#PrimaryButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #74b3ff, stop:1 #447fe8);
                border-color: #74b3ff;
            }
            QPushButton#SecondaryButton {
                background: #121d2a;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        hero = QFrame()
        hero.setObjectName("HeroCard")
        hero_layout = QVBoxLayout(hero)
        hero_layout.setContentsMargins(22, 20, 22, 20)
        hero_layout.setSpacing(10)

        eyebrow = QLabel("OFFLINE CLOUD PACKAGE")
        eyebrow.setObjectName("HeroEyebrow")
        hero_layout.addWidget(eyebrow)

        title = QLabel("Export Local Studies to Offline Cloud")
        title.setObjectName("HeroTitle")
        hero_layout.addWidget(title)

        subtitle = QLabel(
            "Review the downloaded studies, choose the destination Offline Cloud server, "
            "and package the images plus workstation data into a transfer-ready folder."
        )
        subtitle.setObjectName("HeroBody")
        subtitle.setWordWrap(True)
        hero_layout.addWidget(subtitle)
        root.addWidget(hero)

        summary_card = QFrame()
        summary_card.setObjectName("SummaryCard")
        summary_layout = QVBoxLayout(summary_card)
        summary_layout.setContentsMargins(18, 16, 18, 16)
        summary_layout.setSpacing(12)

        summary_title = QLabel("Selection Summary")
        summary_title.setObjectName("SectionTitle")
        summary_layout.addWidget(summary_title)

        summary_grid = QGridLayout()
        summary_grid.setHorizontalSpacing(12)
        summary_grid.setVerticalSpacing(12)

        self._study_count_label = QLabel("0")
        self._patient_count_label = QLabel("0")
        self._image_count_label = QLabel("0")
        self._skipped_count_label = QLabel(str(self._skipped_count))

        summary_grid.addWidget(self._build_metric_chip("Studies", self._study_count_label), 0, 0)
        summary_grid.addWidget(self._build_metric_chip("Patients", self._patient_count_label), 0, 1)
        summary_grid.addWidget(self._build_metric_chip("Images", self._image_count_label), 0, 2)
        summary_grid.addWidget(self._build_metric_chip("Skipped", self._skipped_count_label), 0, 3)
        summary_layout.addLayout(summary_grid)
        root.addWidget(summary_card)

        select_card = QFrame()
        select_card.setObjectName("SelectCard")
        select_layout = QVBoxLayout(select_card)
        select_layout.setContentsMargins(18, 16, 18, 16)
        select_layout.setSpacing(10)

        select_title = QLabel("Destination Offline Cloud Server")
        select_title.setObjectName("SectionTitle")
        select_layout.addWidget(select_title)

        select_hint = QLabel(
            "Choose the folder-backed server that should receive this package. "
            "The package manifest will be updated after export completes."
        )
        select_hint.setObjectName("SectionHint")
        select_hint.setWordWrap(True)
        select_layout.addWidget(select_hint)

        self.server_combo = QComboBox()
        self.server_combo.currentIndexChanged.connect(self._update_server_details)
        select_layout.addWidget(self.server_combo)

        self.server_path_label = QLabel("Folder path will appear here after you choose a destination.")
        self.server_path_label.setObjectName("ServerPath")
        self.server_path_label.setWordWrap(True)
        select_layout.addWidget(self.server_path_label)
        root.addWidget(select_card)

        table_card = QFrame()
        table_card.setObjectName("TableCard")
        table_layout = QVBoxLayout(table_card)
        table_layout.setContentsMargins(18, 16, 18, 16)
        table_layout.setSpacing(12)

        table_title = QLabel("Studies Ready for Export")
        table_title.setObjectName("SectionTitle")
        table_layout.addWidget(table_title)

        table_hint = QLabel(
            "Only locally available studies are included here. Series and image totals are shown so you can confirm the package before exporting."
        )
        table_hint.setObjectName("SectionHint")
        table_hint.setWordWrap(True)
        table_layout.addWidget(table_hint)

        self.study_table = QTableWidget()
        self.study_table.setColumnCount(6)
        self.study_table.setHorizontalHeaderLabels(
            ["Patient ID", "Patient Name", "Study UID", "Modality", "Series", "Images"]
        )
        self.study_table.verticalHeader().setVisible(False)
        self.study_table.setShowGrid(False)
        self.study_table.setWordWrap(False)
        self.study_table.setAlternatingRowColors(True)
        self.study_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.study_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.study_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.study_table.setFocusPolicy(Qt.NoFocus)
        self.study_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.study_table.verticalHeader().setDefaultSectionSize(42)
        table_layout.addWidget(self.study_table, 1)
        root.addWidget(table_card, 1)

        footer_card = QFrame()
        footer_card.setObjectName("FooterCard")
        footer_layout = QHBoxLayout(footer_card)
        footer_layout.setContentsMargins(18, 14, 18, 14)
        footer_layout.setSpacing(12)

        footer_note = QLabel(
            "Export copies DICOM, attachments, thumbnails, and related package metadata into the selected Offline Cloud folder."
        )
        footer_note.setObjectName("SectionHint")
        footer_note.setWordWrap(True)
        footer_layout.addWidget(footer_note, 1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName("SecondaryButton")
        cancel_btn.clicked.connect(self.reject)

        export_btn = QPushButton("Start Export")
        export_btn.setObjectName("PrimaryButton")
        export_btn.clicked.connect(self._accept_export)

        footer_layout.addWidget(cancel_btn)
        footer_layout.addWidget(export_btn)
        root.addWidget(footer_card)

    def _build_metric_chip(self, label_text: str, value_label: QLabel) -> QFrame:
        chip = QFrame()
        chip.setObjectName("MetricChip")
        chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(chip)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(3)

        value_label.setObjectName("MetricValue")
        caption = QLabel(label_text)
        caption.setObjectName("MetricLabel")

        layout.addWidget(value_label)
        layout.addWidget(caption)
        return chip

    def _populate(self):
        for server in self._cloud_servers:
            self.server_combo.addItem(str(server.get("name") or ""), server)

        self.study_table.setRowCount(len(self._studies))

        patient_ids = set()
        total_images = 0

        for row, study in enumerate(self._studies):
            patient_id = str(study.get("patient_id") or "")
            if patient_id:
                patient_ids.add(patient_id)

            image_count = int(study.get("images_count") or study.get("number_of_instances") or 0)
            total_images += image_count

            values = [
                patient_id,
                str(study.get("patient_name") or ""),
                str(study.get("study_uid") or ""),
                str(study.get("modality") or ""),
                str(study.get("series_count") or study.get("number_of_series") or 0),
                str(image_count),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col >= 4:
                    item.setTextAlignment(Qt.AlignCenter)
                self.study_table.setItem(row, col, item)

        self._study_count_label.setText(str(len(self._studies)))
        self._patient_count_label.setText(str(len(patient_ids)))
        self._image_count_label.setText(str(total_images))
        self._skipped_count_label.setText(str(self._skipped_count))

        header = self.study_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)

        if self.server_combo.count() > 0:
            self._update_server_details()

    def _update_server_details(self):
        server = self.server_combo.currentData()
        folder_path = str((server or {}).get("folder_path") or "").strip()
        if folder_path:
            self.server_path_label.setText(folder_path)
            return
        self.server_path_label.setText("Folder path will appear here after you choose a destination.")

    def _accept_export(self):
        if not self._studies:
            QMessageBox.warning(self, "Offline Cloud Export", "There are no downloaded studies to export.")
            return
        if self.server_combo.currentIndex() < 0:
            QMessageBox.warning(self, "Offline Cloud Export", "Choose an Offline Cloud Server first.")
            return

        self._selected_server = self.server_combo.currentData()
        if not self._selected_server:
            QMessageBox.warning(self, "Offline Cloud Export", "The selected Offline Cloud Server is invalid.")
            return

        self.accept()
