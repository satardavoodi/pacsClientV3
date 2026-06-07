"""
CD Burn Dialog
Professional Write-to-CD/DVD dialog: privacy, content, DICOM format,
disc settings (drive/speed/label/capacity), finalize & verify options.
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QProgressBar, QComboBox, QLineEdit, QGroupBox, QFormLayout,
                               QMessageBox, QFileDialog, QCheckBox, QTextEdit, QFrame,
                               QRadioButton, QButtonGroup, QSpinBox, QScrollArea, QWidget,
                               QGridLayout)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap
import qtawesome as qta
from typing import List, Optional
import os
from pathlib import Path

from .cd_burn_manager import (
    BurnOptions,
    CDBurnManager,
    get_available_drives,
    check_imapi2_available,
)
from .center_identity import load_center_identity, save_center_identity
from .dicom_prepare import (
    FORMAT_CHOICES,
    FORMAT_LOSSY,
    FORMAT_ORIGINAL,
)
from .dicomdir_builder import check_pydicom_available


def _get_light_viewer_widget():
    """Lazy import to avoid circular dependency with settings_ui package."""
    from PacsClient.pacs.workstation_ui.settings_ui.lightviewer_settings import LightViewerSettingsWidget
    return LightViewerSettingsWidget


def _fallback_viewer_selection() -> dict:
    """Viewer resolution that works even without the settings package
    (e.g. plugin-only deployments): default AI-PACS viewer or nothing."""
    try:
        from .viewer_locator import resolve_default_viewer

        info = resolve_default_viewer()
        if info:
            return {
                'mode': 'default',
                'path': info['path'],
                'display_name': info['display_name'],
                'kind': info['kind'],
            }
    except Exception:
        pass
    return {'mode': 'default', 'path': None, 'display_name': 'No viewer', 'kind': 'none'}


# CD icon path
CD_ICON_PATH = Path(__file__).parent / "assets" / "cd_icon.png"


class CDBurnDialog(QDialog):
    """Dialog for burning DICOM studies to CD/DVD"""

    def __init__(self, studies: List[dict], parent=None):
        super().__init__(parent)
        self.studies = studies
        self.burn_manager = CDBurnManager()
        self.is_burning = False

        # Check which studies are downloaded
        self.downloaded_studies, self.not_downloaded_studies = self._check_download_status()

        self.setWindowTitle("Write to CD/DVD")
        self.setMinimumSize(680, 560)
        self.resize(720, 780)
        self.setModal(True)

        # Set window icon
        if CD_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(CD_ICON_PATH)))

        self.setup_ui()
        self.check_prerequisites()
        self.connect_signals()
        self._refresh_media_status()

    # ------------------------------------------------------------------ data --

    def _resolve_viewer_selection(self) -> dict:
        """Resolve which viewer to bundle (Settings mode: default vs custom)."""
        try:
            return _get_light_viewer_widget().get_viewer_selection()
        except Exception as e:
            print(f"Viewer selection via settings failed, using fallback: {e}")
            return _fallback_viewer_selection()

    def _check_download_status(self):
        """Check which studies are downloaded and which are not"""
        downloaded = []
        not_downloaded = []

        for study in self.studies:
            study_path = study.get('study_path')
            study_uid = study.get('study_uid')

            # Try to find study path
            if not study_path and study_uid:
                try:
                    from PacsClient.utils.config import SOURCE_PATH
                    possible_path = SOURCE_PATH / study_uid
                    if possible_path.exists():
                        study_path = str(possible_path)
                        study['study_path'] = study_path
                except Exception:
                    pass

            # Check if study has DICOM files
            has_files = False
            if study_path and Path(study_path).exists():
                has_files = self._has_dicom_files(Path(study_path))

            if has_files:
                downloaded.append(study)
            else:
                not_downloaded.append(study)

        return downloaded, not_downloaded

    def _has_dicom_files(self, study_path: Path) -> bool:
        for suffix in ("*.dcm", "*.dicom"):
            if any(study_path.rglob(suffix)):
                return True

        for candidate in study_path.rglob("*"):
            if not candidate.is_file() or candidate.suffix:
                continue

            try:
                from pydicom import dcmread
                dcmread(str(candidate), stop_before_pixels=True)
                return True
            except Exception:
                continue

        return False

    # -------------------------------------------------------------------- UI --

    def setup_ui(self):
        """Setup the dialog UI"""
        self.setStyleSheet("""
            QDialog {
                background-color: #1a202c;
                color: #e2e8f0;
            }
            QScrollArea { background: transparent; border: none; }
            QGroupBox {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 8px;
                padding: 12px;
                margin-top: 10px;
                font-weight: bold;
                color: #e2e8f0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLabel { color: #e2e8f0; }
            QLineEdit, QComboBox, QSpinBox {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 6px;
                min-height: 18px;
            }
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus {
                border: 1px solid #3182ce;
            }
            QCheckBox { color: #e2e8f0; spacing: 8px; }
            QCheckBox::indicator { width: 17px; height: 17px; }
            QCheckBox:disabled { color: #718096; }
            QRadioButton { color: #e2e8f0; spacing: 7px; padding: 2px 0; }
            QRadioButton::indicator {
                width: 15px; height: 15px; border-radius: 8px;
                border: 2px solid #64748b; background-color: #1b2230;
            }
            QRadioButton::indicator:hover { border-color: #93c5fd; }
            QRadioButton::indicator:checked {
                border: 2px solid #3b82f6;
                background-color: qradialgradient(
                    cx: 0.5, cy: 0.5, radius: 0.55, fx: 0.5, fy: 0.5,
                    stop: 0 #60a5fa, stop: 0.55 #3b82f6, stop: 0.62 #1b2230, stop: 1 #1b2230);
            }
            QProgressBar {
                border: 1px solid #4a5568;
                border-radius: 4px;
                background-color: #2d3748;
                text-align: center;
                color: #e2e8f0;
                min-height: 22px;
            }
            QProgressBar::chunk { background-color: #3182ce; border-radius: 3px; }
            QPushButton {
                background-color: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 9px 18px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #2c5aa0; }
            QPushButton:pressed { background-color: #1e4a8a; }
            QPushButton:disabled { background-color: #4a5568; color: #6b7280; }
            QTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)

        content_layout = QVBoxLayout()
        content_layout.setSpacing(10)
        content_layout.setContentsMargins(14, 12, 14, 12)

        # ---- Title ----
        title_layout = QHBoxLayout()
        title_icon = QLabel()
        if CD_ICON_PATH.exists():
            title_icon.setPixmap(QPixmap(str(CD_ICON_PATH)).scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            title_icon.setPixmap(qta.icon('fa5s.compact-disc', color='#6366f1').pixmap(30, 30))
        title_label = QLabel("Write Studies to CD/DVD")
        title_label.setStyleSheet("font-size: 19px; font-weight: bold; color: #e2e8f0;")
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        content_layout.addLayout(title_layout)

        # ---- Selected studies ----
        studies_group = QGroupBox("Selected Studies")
        studies_layout = QVBoxLayout()
        studies_layout.setSpacing(4)

        study_count = len(self.studies)
        downloaded_count = len(self.downloaded_studies)
        not_downloaded_count = len(self.not_downloaded_studies)

        if not_downloaded_count > 0:
            studies_info = QLabel(
                f"{study_count} studies selected — ✓ {downloaded_count} ready, "
                f"⚠ {not_downloaded_count} not downloaded (will be skipped)"
            )
            studies_info.setStyleSheet("font-size: 12px; color: #f59e0b;")
        else:
            studies_info = QLabel(f"✓ {downloaded_count} studies ready for CD burning")
            studies_info.setStyleSheet("font-size: 12px; color: #48bb78;")
        studies_info.setWordWrap(True)
        studies_layout.addWidget(studies_info)

        study_list_text = ""
        for study in self.downloaded_studies[:4]:
            patient_name = study.get('patient_name', 'Unknown')
            modality = study.get('modality', '')
            study_list_text += f"✓ {patient_name} - {modality}\n"
        if downloaded_count > 4:
            study_list_text += f"… and {downloaded_count - 4} more"
        if study_list_text:
            study_list_label = QLabel(study_list_text.strip())
            study_list_label.setStyleSheet("font-size: 12px; color: #cbd5e0; padding: 2px;")
            studies_layout.addWidget(study_list_label)

        self._size_estimate_mb = self.burn_manager.get_studies_size_estimate(self.downloaded_studies)
        size_label = QLabel(f"Estimated DICOM size: {self._size_estimate_mb} MB")
        size_label.setStyleSheet("font-size: 12px; color: #a0aec0;")
        studies_layout.addWidget(size_label)

        studies_group.setLayout(studies_layout)
        content_layout.addWidget(studies_group)

        # ---- Imaging center identity (persisted per system) ----
        center_group = QGroupBox("Imaging Center")
        center_layout = QFormLayout()
        center_layout.setSpacing(6)
        saved_identity = load_center_identity()
        self.center_name_edit = QLineEdit(saved_identity.get("center_name", ""))
        self.center_name_edit.setPlaceholderText("e.g. Alizadeh Imaging Center")
        self.center_address_edit = QLineEdit(saved_identity.get("center_address", ""))
        self.center_address_edit.setPlaceholderText("Street, city")
        self.center_phone_edit = QLineEdit(saved_identity.get("center_phone", ""))
        self.center_phone_edit.setPlaceholderText("e.g. +98 ...")
        center_layout.addRow("Center name:", self.center_name_edit)
        center_layout.addRow("Address:", self.center_address_edit)
        center_layout.addRow("Phone:", self.center_phone_edit)
        center_note = QLabel(
            "Shown at the top of the CD viewer and in START_HERE.txt. "
            "Saved on this system and reused for future CDs."
        )
        center_note.setWordWrap(True)
        center_note.setStyleSheet("font-size: 11px; color: #a0aec0;")
        center_layout.addRow("", center_note)
        center_group.setLayout(center_layout)
        content_layout.addWidget(center_group)

        # ---- Patient privacy ----
        privacy_group = QGroupBox("Patient Privacy")
        privacy_layout = QHBoxLayout()
        privacy_layout.setSpacing(10)

        self.anonymize_cb = QCheckBox("Anonymize patient data")
        self.anonymize_cb.setToolTip(
            "Replace patient name/ID and remove identifying DICOM tags before writing.\n"
            "UIDs are remapped consistently. Reports/attachments are excluded\n"
            "automatically because they contain identifying data."
        )
        self.anonymize_cb.toggled.connect(self._on_anonymize_toggled)
        privacy_layout.addWidget(self.anonymize_cb)

        privacy_layout.addSpacing(10)
        seed_label = QLabel("Seed:")
        seed_label.setStyleSheet("color: #a0aec0;")
        privacy_layout.addWidget(seed_label)
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(1, 99999)
        self.seed_spin.setValue(1)
        self.seed_spin.setEnabled(False)
        self.seed_spin.setToolTip("Pseudonym number: patient becomes ANONYMOUS^<seed> / ANON<seed>")
        privacy_layout.addWidget(self.seed_spin)
        privacy_layout.addStretch()

        privacy_group.setLayout(privacy_layout)
        content_layout.addWidget(privacy_group)

        # ---- Content ----
        content_group = QGroupBox("Content")
        content_grid = QGridLayout()
        content_grid.setHorizontalSpacing(18)
        content_grid.setVerticalSpacing(6)

        self.include_report_cb = QCheckBox("Include report")
        self.include_report_cb.setToolTip("Adds the patient's reports (HTML) under REPORTS\\")
        self.include_images_cb = QCheckBox("Include JPEG images")
        self.include_images_cb.setToolTip("Adds captured/exported images under JPEG\\")
        self.include_attachments_cb = QCheckBox("Include attachments")
        self.include_attachments_cb.setToolTip("Adds patient attachments (documents, media) under ATTACHMENTS\\")

        # Viewer checkbox (default AI-PACS viewer or custom, per Settings)
        self.viewer_selection = self._resolve_viewer_selection()
        viewer_path = self.viewer_selection.get('path')
        viewer_name = self.viewer_selection.get('display_name') or "DICOM Viewer"
        if viewer_path:
            self.include_viewer_cb = QCheckBox(f"Include viewer: {viewer_name}")
            self.include_viewer_cb.setChecked(True)
            analysis = self.burn_manager.inspect_viewer_portability(viewer_path)
            tooltip_lines = [f"Will include: {os.path.basename(viewer_path)}"]
            tooltip_lines.extend(analysis.get("details", []))
            if analysis.get("warnings"):
                tooltip_lines.append("Warnings:")
                tooltip_lines.extend(f"- {warning}" for warning in analysis["warnings"])
            self.include_viewer_cb.setToolTip("\n".join(tooltip_lines))
        else:
            self.include_viewer_cb = QCheckBox("Include DICOM viewer (none available)")
            self.include_viewer_cb.setChecked(False)
            self.include_viewer_cb.setEnabled(False)
            self.include_viewer_cb.setToolTip(
                "No viewer available.\n"
                "Settings → Light Viewer: use the default AI-PACS portable viewer\n"
                "(build it with tools\\build\\build_lite_viewer.bat) or select a custom .exe."
            )

        content_grid.addWidget(self.include_report_cb, 0, 0)
        content_grid.addWidget(self.include_images_cb, 0, 1)
        content_grid.addWidget(self.include_attachments_cb, 1, 0)
        content_grid.addWidget(self.include_viewer_cb, 1, 1)
        content_group.setLayout(content_grid)
        content_layout.addWidget(content_group)

        # ---- DICOM format ----
        format_group = QGroupBox("DICOM Format")
        format_grid = QGridLayout()
        format_grid.setHorizontalSpacing(16)
        format_grid.setVerticalSpacing(4)
        self.format_buttons = QButtonGroup(self)
        self._format_radio_by_value = {}
        for index, (value, label) in enumerate(FORMAT_CHOICES):
            radio = QRadioButton(label)
            if value == FORMAT_LOSSY:
                radio.setToolTip("JPEG 2000 lossy (~10:1). Marks images as lossy-compressed.")
            self.format_buttons.addButton(radio)
            self._format_radio_by_value[value] = radio
            format_grid.addWidget(radio, index // 3, index % 3)
        self._format_radio_by_value[FORMAT_ORIGINAL].setChecked(True)
        format_group.setLayout(format_grid)
        content_layout.addWidget(format_group)

        # ---- Disc settings ----
        cd_group = QGroupBox("Disc Settings")
        cd_layout = QFormLayout()
        cd_layout.setSpacing(8)

        drive_row = QHBoxLayout()
        self.drive_combo = QComboBox()
        self._populate_drives()
        self.drive_combo.currentIndexChanged.connect(self._on_drive_changed)
        drive_row.addWidget(self.drive_combo, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Re-detect drives, media capacity and write speeds")
        self.refresh_btn.clicked.connect(self._on_refresh_clicked)
        self.refresh_btn.setStyleSheet("QPushButton { padding: 6px 12px; background-color: #4a5568; }"
                                       "QPushButton:hover { background-color: #6b7280; }")
        drive_row.addWidget(self.refresh_btn)
        cd_layout.addRow("Drive:", drive_row)

        self.speed_combo = QComboBox()
        self.speed_combo.addItem("Auto (recommended)", None)
        cd_layout.addRow("Write speed:", self.speed_combo)

        try:
            saved_label = _get_light_viewer_widget().get_disc_label()
        except Exception:
            saved_label = "DICOM_IMAGES"
        self.disc_label_edit = QLineEdit()
        self.disc_label_edit.setMaxLength(32)
        self.disc_label_edit.setPlaceholderText("[Auto Label]  (leave empty: patient + date)")
        if saved_label and saved_label != "DICOM_IMAGES":
            self.disc_label_edit.setText(saved_label)
        self.disc_label_edit.setToolTip(
            "Leave empty for an automatic label (patient or anonym ID + study date + today)."
        )
        cd_layout.addRow("Disc label:", self.disc_label_edit)

        self.capacity_label = QLabel("Media: checking…")
        self.capacity_label.setWordWrap(True)
        self.capacity_label.setStyleSheet("font-size: 12px; color: #a0aec0;")
        cd_layout.addRow("Capacity:", self.capacity_label)

        cd_group.setLayout(cd_layout)
        content_layout.addWidget(cd_group)

        # ---- Burn options ----
        burn_opts_group = QGroupBox("Burn Options")
        burn_opts_layout = QHBoxLayout()
        burn_opts_layout.setSpacing(18)
        self.finalize_cb = QCheckBox("Finalize disc")
        self.finalize_cb.setChecked(True)
        self.finalize_cb.setToolTip("Close the disc after writing — no further sessions can be added.\n"
                                    "Recommended for patient CDs.")
        self.verify_cb = QCheckBox("Verify after burn")
        self.verify_cb.setToolTip("Re-read the disc after writing and compare size + SHA-256 of every file.")
        burn_opts_layout.addWidget(self.finalize_cb)
        burn_opts_layout.addWidget(self.verify_cb)
        burn_opts_layout.addStretch()
        burn_opts_group.setLayout(burn_opts_layout)
        content_layout.addWidget(burn_opts_group)

        # ---- Status / prerequisites ----
        self.status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        status_layout.setSpacing(2)
        self.pydicom_status = QLabel()
        self.imapi_status = QLabel()
        self.drive_status = QLabel()
        status_layout.addWidget(self.pydicom_status)
        status_layout.addWidget(self.imapi_status)
        status_layout.addWidget(self.drive_status)
        self.status_group.setLayout(status_layout)
        content_layout.addWidget(self.status_group)

        # ---- Progress ----
        self.progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(4)
        self.stage_label = QLabel("Ready")
        self.stage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #60a5fa;")
        progress_layout.addWidget(self.stage_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        self.progress_message = QLabel("")
        self.progress_message.setWordWrap(True)
        self.progress_message.setStyleSheet("font-size: 12px; color: #a0aec0;")
        progress_layout.addWidget(self.progress_message)
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(110)
        self.log_output.setVisible(False)
        progress_layout.addWidget(self.log_output)
        self.progress_group.setLayout(progress_layout)
        content_layout.addWidget(self.progress_group)

        content_layout.addStretch()

        # Scrollable body (short displays must reach every option)
        body = QWidget()
        body.setLayout(content_layout)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(body)

        # ---- Action buttons (fixed at the bottom, outside the scroll) ----
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(14, 6, 14, 12)
        button_layout.addStretch()

        self.prepare_btn = QPushButton("Prepare Folder Only")
        self.prepare_btn.setToolTip("Create CD folder structure without burning\n(Use to copy to USB or burn later)")
        self.prepare_btn.clicked.connect(self.prepare_folder)
        self.prepare_btn.setStyleSheet("""
            QPushButton { background-color: #4a5568; color: white; }
            QPushButton:hover { background-color: #6b7280; }
            QPushButton:disabled { background-color: #374151; color: #6b7280; }
        """)
        button_layout.addWidget(self.prepare_btn)

        self.burn_btn = QPushButton(qta.icon('fa5s.fire', color='white'), " Burn to CD/DVD")
        self.burn_btn.clicked.connect(self.start_burn)
        self.burn_btn.setStyleSheet("""
            QPushButton { background-color: #dc2626; color: white; padding: 9px 22px; }
            QPushButton:hover { background-color: #b91c1c; }
            QPushButton:disabled { background-color: #4a5568; }
        """)
        button_layout.addWidget(self.burn_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_or_close)
        button_layout.addWidget(self.cancel_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addLayout(button_layout)

    # ------------------------------------------------------------- UI logic --

    def _populate_drives(self):
        self.drive_combo.blockSignals(True)
        self.drive_combo.clear()
        self.drive_combo.addItem("Select CD/DVD drive...", None)
        drives = get_available_drives()
        for drive in drives:
            drive_text = f"{drive['letter']} - {drive['name']}" if drive.get('letter') else drive['name']
            self.drive_combo.addItem(drive_text, drive['id'])
        if len(drives) == 1:
            self.drive_combo.setCurrentIndex(1)
        self.drive_combo.blockSignals(False)

    def _on_anonymize_toggled(self, checked: bool):
        self.seed_spin.setEnabled(checked)
        for cb in (self.include_report_cb, self.include_images_cb, self.include_attachments_cb):
            if checked:
                cb.setChecked(False)
            cb.setEnabled(not checked)
        if checked:
            tip = "Disabled: anonymization is enabled (this content identifies the patient)."
            self.include_report_cb.setToolTip(tip)
            self.include_images_cb.setToolTip(tip)
            self.include_attachments_cb.setToolTip(tip)
        else:
            self.include_report_cb.setToolTip("Adds the patient's reports (HTML) under REPORTS\\")
            self.include_images_cb.setToolTip("Adds captured/exported images under JPEG\\")
            self.include_attachments_cb.setToolTip("Adds patient attachments (documents, media) under ATTACHMENTS\\")

    def _on_refresh_clicked(self):
        self._populate_drives()
        self.check_prerequisites()
        self._refresh_media_status()

    def _on_drive_changed(self, _index: int):
        self._refresh_media_status()

    def _selected_drive_id(self):
        return self.drive_combo.currentData()

    def _refresh_media_status(self):
        """Update write-speed list and the capacity line for the selected drive."""
        drive_id = self._selected_drive_id()

        # Write speeds
        current_speed = self.speed_combo.currentData()
        self.speed_combo.blockSignals(True)
        self.speed_combo.clear()
        self.speed_combo.addItem("Auto (recommended)", None)
        if drive_id is not None:
            try:
                for speed in self.burn_manager.get_write_speeds(drive_id):
                    self.speed_combo.addItem(speed["label"], speed["sectors_per_second"])
            except Exception:
                pass
        if current_speed is not None:
            index = self.speed_combo.findData(current_speed)
            if index >= 0:
                self.speed_combo.setCurrentIndex(index)
        self.speed_combo.blockSignals(False)

        # Capacity line
        if drive_id is None:
            self.capacity_label.setText("Select a drive to check the inserted media.")
            self.capacity_label.setStyleSheet("font-size: 12px; color: #a0aec0;")
            return

        info = {}
        try:
            info = self.burn_manager.get_media_info(drive_id)
        except Exception:
            info = {}

        required_mb = float(self._size_estimate_mb or 0)
        viewer_path = self.viewer_selection.get('path')
        if viewer_path and self.include_viewer_cb.isChecked():
            try:
                bundle_root = Path(viewer_path).parent
                viewer_mb = sum(f.stat().st_size for f in bundle_root.rglob("*") if f.is_file()) / (1024 * 1024)
                required_mb += viewer_mb
            except Exception:
                required_mb += 70  # conservative bundle estimate
        required_mb *= 1.08  # DICOMDIR / filesystem overhead

        if not info.get('present'):
            self.capacity_label.setText(
                f"Required: ~{required_mb:.0f} MB · No media detected — insert a blank CD/DVD and press Refresh."
            )
            self.capacity_label.setStyleSheet("font-size: 12px; color: #f59e0b;")
            return

        free_mb = float(info.get('free_mb') or 0)
        media_type = info.get('type', 'Unknown')
        if free_mb and required_mb + 16 > free_mb:
            self.capacity_label.setText(
                f"✗ {media_type}: {free_mb:.0f} MB free — required ~{required_mb:.0f} MB. DATA DOES NOT FIT."
            )
            self.capacity_label.setStyleSheet("font-size: 12px; color: #f56565; font-weight: bold;")
        else:
            self.capacity_label.setText(
                f"✓ {media_type}: {free_mb:.0f} MB free — required ~{required_mb:.0f} MB (fits)."
            )
            self.capacity_label.setStyleSheet("font-size: 12px; color: #48bb78;")

    def _selected_format(self) -> str:
        for value, radio in self._format_radio_by_value.items():
            if radio.isChecked():
                return value
        return FORMAT_ORIGINAL

    def _build_options(self) -> BurnOptions:
        # Persist the center identity the moment it is used ("enter once,
        # reuse forever") — also picks up edits made for this burn.
        name = self.center_name_edit.text().strip()
        address = self.center_address_edit.text().strip()
        phone = self.center_phone_edit.text().strip()
        save_center_identity(name, address, phone)

        return BurnOptions(
            anonymize=self.anonymize_cb.isChecked(),
            anonymize_seed=int(self.seed_spin.value()),
            include_report=self.include_report_cb.isChecked(),
            include_images=self.include_images_cb.isChecked(),
            include_attachments=self.include_attachments_cb.isChecked(),
            dicom_format=self._selected_format(),
            write_speed_sectors=self.speed_combo.currentData(),
            finalize_disc=self.finalize_cb.isChecked(),
            verify_after_burn=self.verify_cb.isChecked(),
            center_name=name,
            center_address=address,
            center_phone=phone,
        )

    def _options_summary(self, options: BurnOptions, viewer_name: Optional[str]) -> str:
        format_label = dict(FORMAT_CHOICES).get(options.dicom_format, options.dicom_format)
        lines = [
            f"Format: {format_label}",
            f"Anonymize: {'Yes (seed %d)' % options.anonymize_seed if options.anonymize else 'No'}",
            f"Viewer: {viewer_name or 'None'}",
            f"Report: {'Yes' if options.include_report else 'No'} · "
            f"JPEG: {'Yes' if options.include_images else 'No'} · "
            f"Attachments: {'Yes' if options.include_attachments else 'No'}",
            f"Finalize: {'Yes' if options.finalize_disc else 'No'} · "
            f"Verify: {'Yes' if options.verify_after_burn else 'No'}",
        ]
        speed = self.speed_combo.currentText()
        lines.append(f"Write speed: {speed}")
        label_text = self.disc_label_edit.text().strip()
        lines.append(f"Disc label: {label_text or '[Auto Label]'}")
        return "\n".join(lines)

    # ----------------------------------------------------------- prerequisites --

    def check_prerequisites(self):
        """Check if all prerequisites are met"""
        all_ok = True

        if check_pydicom_available():
            self.pydicom_status.setText("✓ DICOMDIR creation: Available")
            self.pydicom_status.setStyleSheet("color: #48bb78;")
        else:
            self.pydicom_status.setText("✗ DICOMDIR creation: pydicom not installed")
            self.pydicom_status.setStyleSheet("color: #f56565;")
            all_ok = False

        if check_imapi2_available():
            self.imapi_status.setText("✓ CD burning: Available")
            self.imapi_status.setStyleSheet("color: #48bb78;")
        else:
            self.imapi_status.setText("✗ CD burning: comtypes not installed or Windows only")
            self.imapi_status.setStyleSheet("color: #f56565;")

        drives = get_available_drives()
        if drives:
            self.drive_status.setText(f"✓ CD/DVD drives: {len(drives)} found")
            self.drive_status.setStyleSheet("color: #48bb78;")
            self.burn_btn.setEnabled(True)
        else:
            self.drive_status.setText("✗ CD/DVD drives: No drives detected")
            self.drive_status.setStyleSheet("color: #f59e0b;")
            self.burn_btn.setEnabled(False)

        return all_ok

    def connect_signals(self):
        """Connect burn manager signals"""
        self.burn_manager.progress.connect(self.on_progress)
        self.burn_manager.completed.connect(self.on_completed)
        self.burn_manager.stage_changed.connect(self.on_stage_changed)

    # ----------------------------------------------------------- auto download --

    def _start_auto_download(self, action: str, folder: str = None):
        """Start automatic download of not downloaded studies via home_ui"""
        if not self.not_downloaded_studies:
            return False

        reply = QMessageBox.question(
            self,
            "Download Images",
            f"{len(self.not_downloaded_studies)} studies are not downloaded yet.\n\n"
            "Do you want to download them now?\n"
            "After download completes, click CD Burn again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes
        )

        if reply != QMessageBox.Yes:
            return False

        try:
            home_ui = self.parent()
            if hasattr(home_ui, '_on_download_requested'):
                home_ui._on_download_requested(self.not_downloaded_studies, set_current_tab=True)

                QMessageBox.information(
                    self,
                    "Download Started",
                    f"Download of {len(self.not_downloaded_studies)} studies has started.\n\n"
                    "After download completes, click CD Burn button again."
                )
                self.accept()
                return True
            else:
                QMessageBox.warning(
                    self,
                    "Error",
                    "Unable to start download.\n"
                    "Please download images from the patient list."
                )
                return False

        except Exception as e:
            print(f"Error starting auto download: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error starting download: {str(e)}")

        return False

    # ------------------------------------------------------------------ burn --

    def start_burn(self):
        """Start the CD burning process"""
        if self.is_burning:
            return

        if len(self.downloaded_studies) == 0:
            if len(self.not_downloaded_studies) > 0:
                self._start_auto_download('burn')
                return

            QMessageBox.warning(
                self,
                "No Downloaded Studies",
                "No downloaded studies found.\n\n"
                "Please download the images first, then try CD burning again."
            )
            return

        if self.drive_combo.currentData() is None:
            QMessageBox.warning(self, "Drive Not Selected",
                                "Please select a CD/DVD drive first.")
            return

        self._execute_burn()

    def _execute_burn(self):
        """Execute the actual burn operation"""
        drive_id = self.drive_combo.currentData()
        disc_label = self.disc_label_edit.text().strip()  # empty → auto label
        options = self._build_options()

        light_viewer_path = None
        viewer_display_name = None
        if self.include_viewer_cb.isChecked():
            selection = self._resolve_viewer_selection()
            light_viewer_path = selection.get('path')
            viewer_display_name = selection.get('display_name')

        viewer_warning_text = ""
        if light_viewer_path:
            analysis = self.burn_manager.inspect_viewer_portability(light_viewer_path)
            if analysis.get("warnings"):
                viewer_warning_text = "\nViewer portability warnings:\n- " + "\n- ".join(analysis["warnings"])

        reply = QMessageBox.question(
            self,
            "Confirm Burn",
            f"Ready to burn {len(self.downloaded_studies)} downloaded studies to CD/DVD.\n\n"
            f"{self._options_summary(options, viewer_display_name if light_viewer_path else None)}\n\n"
            f"{self._get_viewer_launch_summary(light_viewer_path)}\n"
            f"{viewer_warning_text}\n"
            "Make sure a blank CD/DVD is inserted and click Yes to continue.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply != QMessageBox.Yes:
            self.burn_btn.setEnabled(True)
            self.prepare_btn.setEnabled(True)
            self.cancel_btn.setText("Close")
            return

        self.is_burning = True
        self.burn_btn.setEnabled(False)
        self.prepare_btn.setEnabled(False)
        self.cancel_btn.setText("Cancel Burn")
        self.log_output.setVisible(True)
        self.log_output.append(f"[options]\n{self._options_summary(options, viewer_display_name)}")

        self.burn_manager.prepare_and_burn(
            studies=self.downloaded_studies,
            light_viewer_path=light_viewer_path,
            disc_label=disc_label,
            drive_id=drive_id,
            burn_to_disc=True,
            viewer_display_name=viewer_display_name,
            options=options,
        )

    def prepare_folder(self):
        """Prepare CD folder structure without burning"""
        if self.is_burning:
            return

        if len(self.downloaded_studies) == 0:
            if len(self.not_downloaded_studies) > 0:
                self._start_auto_download('prepare')
                return

            QMessageBox.warning(
                self,
                "No Downloaded Studies",
                "No downloaded studies found.\n\n"
                "Please download the images first, then try preparing folder again."
            )
            return

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder for CD Structure",
            "",
            QFileDialog.ShowDirsOnly
        )

        if not folder:
            return

        self._execute_prepare(folder)

    def _execute_prepare(self, folder: str):
        """Execute the actual prepare folder operation"""
        if not folder:
            self.burn_btn.setEnabled(True)
            self.prepare_btn.setEnabled(True)
            self.cancel_btn.setText("Close")
            return

        disc_label = self.disc_label_edit.text().strip()  # empty → auto label
        options = self._build_options()

        light_viewer_path = None
        viewer_display_name = None
        if self.include_viewer_cb.isChecked():
            selection = self._resolve_viewer_selection()
            light_viewer_path = selection.get('path')
            viewer_display_name = selection.get('display_name')

        self.log_output.append(f"[info] {self._get_viewer_launch_summary(light_viewer_path)}")
        self.log_output.append(f"[options]\n{self._options_summary(options, viewer_display_name)}")

        if light_viewer_path:
            analysis = self.burn_manager.inspect_viewer_portability(light_viewer_path)
            if analysis.get("warnings"):
                self.log_output.append("[info] Viewer portability warnings:")
                for warning in analysis["warnings"]:
                    self.log_output.append(f"[info] - {warning}")

        self.is_burning = True
        self.burn_btn.setEnabled(False)
        self.prepare_btn.setEnabled(False)
        self.cancel_btn.setText("Cancel")
        self.log_output.setVisible(True)

        self.burn_manager.prepare_folder(
            studies=self.downloaded_studies,
            output_folder=folder,
            light_viewer_path=light_viewer_path,
            disc_label=disc_label,
            viewer_display_name=viewer_display_name,
            options=options,
        )

    def _get_viewer_launch_summary(self, light_viewer_path: Optional[str]) -> str:
        """Return a user-facing summary of the expected media launch target."""
        if light_viewer_path and Path(light_viewer_path).exists():
            viewer_name = Path(light_viewer_path).name
            return (
                f"Media launch target: VIEWER\\{viewer_name} "
                "(AutoPlay/autorun when allowed; RUN_VIEWER.cmd as fallback)"
            )

        return "Media launch target: OPEN_DICOM_FOLDER.cmd (no bundled viewer)"

    # -------------------------------------------------------------- progress --

    def on_progress(self, percent: int, message: str):
        """Handle progress updates"""
        self.progress_bar.setValue(percent)
        self.progress_message.setText(message)
        self.log_output.append(f"[{percent}%] {message}")

        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def on_stage_changed(self, stage: str):
        """Handle stage changes"""
        self.stage_label.setText(f"Stage: {stage}")

    def on_completed(self, success: bool, message: str):
        """Handle completion"""
        self.is_burning = False
        self.cancel_btn.setText("Close")

        if success:
            self.stage_label.setText("Completed!")
            self.stage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #48bb78;")
            self.progress_bar.setValue(100)

            success_message = message
            if "prepared" in message.lower() or "burned" in message.lower():
                success_message += (
                    "\n\nOn another PC, start with `START_HERE.txt` or `RUN_VIEWER.cmd`. "
                    "If the bundled viewer cannot run on that machine, open `DICOMDIR` with any DICOM viewer."
                )

            QMessageBox.information(self, "Success", success_message)
        else:
            self.stage_label.setText("Failed")
            self.stage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #f56565;")
            self.burn_btn.setEnabled(True)
            self.prepare_btn.setEnabled(True)

            QMessageBox.critical(self, "Error", message)

    def cancel_or_close(self):
        """Cancel operation or close dialog"""
        if self.is_burning:
            reply = QMessageBox.question(
                self,
                "Cancel Operation",
                "Are you sure you want to cancel the current operation?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.burn_manager.cancel()
                self.is_burning = False
                self.burn_btn.setEnabled(True)
                self.prepare_btn.setEnabled(True)
                self.cancel_btn.setText("Close")
        else:
            self.accept()

    def closeEvent(self, event):
        """Handle close event"""
        if self.is_burning:
            reply = QMessageBox.question(
                self,
                "Operation in Progress",
                "A burn operation is in progress. Cancel it?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply == QMessageBox.Yes:
                self.burn_manager.cancel()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
