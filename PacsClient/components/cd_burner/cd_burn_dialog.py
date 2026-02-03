"""
CD Burn Dialog
User interface for burning DICOM studies to CD/DVD
"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
                               QProgressBar, QComboBox, QLineEdit, QGroupBox, QFormLayout,
                               QMessageBox, QFileDialog, QCheckBox, QTextEdit, QFrame)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap
import qtawesome as qta
from typing import List, Optional
import os
from pathlib import Path

from .cd_burn_manager import CDBurnManager, get_available_drives, check_imapi2_available
from .dicomdir_builder import check_pydicom_available
from PacsClient.pacs.workstation_ui.settings_ui.lightviewer_settings import LightViewerSettingsWidget

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
        self.setMinimumSize(600, 550)
        self.setModal(True)
        
        # Set window icon
        if CD_ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(CD_ICON_PATH)))
        
        self.setup_ui()
        self.check_prerequisites()
        self.connect_signals()
    
    def _check_download_status(self):
        """Check which studies are downloaded and which are not"""
        from pathlib import Path
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
                except:
                    pass
            
            # Check if study has DICOM files
            has_files = False
            if study_path and Path(study_path).exists():
                dcm_files = list(Path(study_path).rglob("*.dcm"))
                has_files = len(dcm_files) > 0
            
            if has_files:
                downloaded.append(study)
            else:
                not_downloaded.append(study)
        
        return downloaded, not_downloaded
    
    def setup_ui(self):
        """Setup the dialog UI"""
        # Apply dark theme
        self.setStyleSheet("""
            QDialog {
                background-color: #1a202c;
                color: #e2e8f0;
            }
            QGroupBox {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 8px;
                padding: 15px;
                margin-top: 10px;
                font-weight: bold;
                color: #e2e8f0;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QLabel {
                color: #e2e8f0;
            }
            QLineEdit, QComboBox {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 8px;
                min-height: 20px;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #3182ce;
            }
            QCheckBox {
                color: #e2e8f0;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
            }
            QProgressBar {
                border: 1px solid #4a5568;
                border-radius: 4px;
                background-color: #2d3748;
                text-align: center;
                color: #e2e8f0;
                min-height: 24px;
            }
            QProgressBar::chunk {
                background-color: #3182ce;
                border-radius: 3px;
            }
            QPushButton {
                background-color: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
            QPushButton:pressed {
                background-color: #1e4a8a;
            }
            QPushButton:disabled {
                background-color: #4a5568;
                color: #6b7280;
            }
            QTextEdit {
                background-color: #0f172a;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)
        
        main_layout = QVBoxLayout()
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Title with icon
        title_layout = QHBoxLayout()
        title_icon = QLabel()
        if CD_ICON_PATH.exists():
            title_icon.setPixmap(QPixmap(str(CD_ICON_PATH)).scaled(32, 32, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            title_icon.setPixmap(qta.icon('fa5s.compact-disc', color='#6366f1').pixmap(32, 32))
        title_label = QLabel("Write Studies to CD/DVD")
        title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #e2e8f0;")
        title_layout.addWidget(title_icon)
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        main_layout.addLayout(title_layout)
        
        # Studies info
        studies_group = QGroupBox("Selected Studies")
        studies_layout = QVBoxLayout()
        
        study_count = len(self.studies)
        downloaded_count = len(self.downloaded_studies)
        not_downloaded_count = len(self.not_downloaded_studies)
        
        # Show status summary
        if not_downloaded_count > 0:
            studies_info = QLabel(
                f"{study_count} studies selected\n"
                f"✓ {downloaded_count} downloaded (ready for CD)\n"
                f"⚠ {not_downloaded_count} not downloaded"
            )
            studies_info.setStyleSheet("font-size: 13px; color: #f59e0b;")
        else:
            studies_info = QLabel(f"✓ {downloaded_count} studies ready for CD burning")
            studies_info.setStyleSheet("font-size: 13px; color: #48bb78;")
        studies_layout.addWidget(studies_info)
        
        # Warning for not downloaded studies
        if not_downloaded_count > 0:
            warning_label = QLabel(
                "⚠ Studies not downloaded will be skipped.\n"
                "Please download them first if you want to include them."
            )
            warning_label.setStyleSheet("font-size: 11px; color: #f59e0b; padding: 5px; background: rgba(245, 158, 11, 0.1); border-radius: 4px;")
            warning_label.setWordWrap(True)
            studies_layout.addWidget(warning_label)
        
        # List first few studies
        study_list_text = ""
        for i, study in enumerate(self.downloaded_studies[:5]):
            patient_name = study.get('patient_name', 'Unknown')
            modality = study.get('modality', '')
            study_list_text += f"✓ {patient_name} - {modality}\n"
        if downloaded_count > 5:
            study_list_text += f"... and {downloaded_count - 5} more downloaded"
        
        if study_list_text:
            study_list_label = QLabel(study_list_text.strip())
            study_list_label.setStyleSheet("font-size: 12px; color: #cbd5e0; padding: 5px;")
            studies_layout.addWidget(study_list_label)
        
        # Estimate size (only for downloaded studies)
        size_estimate = self.burn_manager.get_studies_size_estimate(self.downloaded_studies)
        size_label = QLabel(f"Estimated size: {size_estimate} MB")
        size_label.setStyleSheet("font-size: 12px; color: #a0aec0;")
        studies_layout.addWidget(size_label)
        
        studies_group.setLayout(studies_layout)
        main_layout.addWidget(studies_group)
        
        # CD/DVD Settings
        cd_group = QGroupBox("CD/DVD Settings")
        cd_layout = QFormLayout()
        cd_layout.setSpacing(12)
        
        # Drive selection
        self.drive_combo = QComboBox()
        self.drive_combo.addItem("Select CD/DVD drive...")
        drives = get_available_drives()
        for drive in drives:
            drive_text = f"{drive['letter']} - {drive['name']}" if drive.get('letter') else drive['name']
            self.drive_combo.addItem(drive_text, drive['id'])
        cd_layout.addRow("Drive:", self.drive_combo)
        
        # Disc label
        disc_label = LightViewerSettingsWidget.get_disc_label()
        self.disc_label_edit = QLineEdit(disc_label)
        self.disc_label_edit.setMaxLength(32)
        self.disc_label_edit.setPlaceholderText("DICOM_IMAGES")
        cd_layout.addRow("Disc Label:", self.disc_label_edit)
        
        # Include light viewer checkbox
        light_viewer_path = LightViewerSettingsWidget.get_light_viewer_path()
        self.include_viewer_cb = QCheckBox("Include DICOM Light Viewer")
        self.include_viewer_cb.setChecked(bool(light_viewer_path))
        if not light_viewer_path:
            self.include_viewer_cb.setEnabled(False)
            self.include_viewer_cb.setToolTip("Configure Light Viewer in Settings first")
        else:
            self.include_viewer_cb.setToolTip(f"Will include: {os.path.basename(light_viewer_path)}")
        cd_layout.addRow("", self.include_viewer_cb)
        
        cd_group.setLayout(cd_layout)
        main_layout.addWidget(cd_group)
        
        # Status/Prerequisites
        self.status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()
        
        self.pydicom_status = QLabel()
        self.imapi_status = QLabel()
        self.drive_status = QLabel()
        
        status_layout.addWidget(self.pydicom_status)
        status_layout.addWidget(self.imapi_status)
        status_layout.addWidget(self.drive_status)
        
        self.status_group.setLayout(status_layout)
        main_layout.addWidget(self.status_group)
        
        # Progress section (initially hidden)
        self.progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        
        self.stage_label = QLabel("Ready")
        self.stage_label.setStyleSheet("font-size: 13px; font-weight: bold; color: #60a5fa;")
        progress_layout.addWidget(self.stage_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        
        self.progress_message = QLabel("")
        self.progress_message.setStyleSheet("font-size: 12px; color: #a0aec0;")
        progress_layout.addWidget(self.progress_message)
        
        # Log output
        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumHeight(100)
        self.log_output.setVisible(False)
        progress_layout.addWidget(self.log_output)
        
        self.progress_group.setLayout(progress_layout)
        main_layout.addWidget(self.progress_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        # Prepare folder button (alternative to burning)
        self.prepare_btn = QPushButton("Prepare Folder Only")
        self.prepare_btn.setToolTip("Create CD folder structure without burning\n(Use to copy to USB or burn later)")
        self.prepare_btn.clicked.connect(self.prepare_folder)
        self.prepare_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
            }
            QPushButton:hover {
                background-color: #6b7280;
            }
            QPushButton:disabled {
                background-color: #374151;
                color: #6b7280;
            }
        """)
        button_layout.addWidget(self.prepare_btn)
        
        # Burn button
        self.burn_btn = QPushButton(qta.icon('fa5s.fire', color='white'), " Burn to CD/DVD")
        self.burn_btn.clicked.connect(self.start_burn)
        self.burn_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: white;
                padding: 10px 25px;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
            QPushButton:disabled {
                background-color: #4a5568;
            }
        """)
        button_layout.addWidget(self.burn_btn)
        
        # Cancel button
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_or_close)
        button_layout.addWidget(self.cancel_btn)
        
        main_layout.addLayout(button_layout)
        
        self.setLayout(main_layout)
    
    def check_prerequisites(self):
        """Check if all prerequisites are met"""
        all_ok = True
        
        # Check pydicom
        if check_pydicom_available():
            self.pydicom_status.setText("✓ DICOMDIR creation: Available")
            self.pydicom_status.setStyleSheet("color: #48bb78;")
        else:
            self.pydicom_status.setText("✗ DICOMDIR creation: pydicom not installed")
            self.pydicom_status.setStyleSheet("color: #f56565;")
            all_ok = False
        
        # Check IMAPI2
        if check_imapi2_available():
            self.imapi_status.setText("✓ CD burning: Available")
            self.imapi_status.setStyleSheet("color: #48bb78;")
        else:
            self.imapi_status.setText("✗ CD burning: comtypes not installed or Windows only")
            self.imapi_status.setStyleSheet("color: #f56565;")
            # Don't fail - user can still prepare folder
        
        # Check drives
        drives = get_available_drives()
        if drives:
            self.drive_status.setText(f"✓ CD/DVD drives: {len(drives)} found")
            self.drive_status.setStyleSheet("color: #48bb78;")
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
    
    def _start_auto_download(self, action: str, folder: str = None):
        """Start automatic download of not downloaded studies via home_ui"""
        if not self.not_downloaded_studies:
            return False
        
        # Ask user if they want to download
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
        
        # Start download via home_ui and close this dialog
        try:
            home_ui = self.parent()
            if hasattr(home_ui, '_on_download_requested'):
                # Use home_ui's download method
                home_ui._on_download_requested(self.not_downloaded_studies, set_current_tab=True)
                
                QMessageBox.information(
                    self,
                    "Download Started",
                    f"Download of {len(self.not_downloaded_studies)} studies has started.\n\n"
                    "After download completes, click CD Burn button again."
                )
                
                # Close this dialog
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
    
    def start_burn(self):
        """Start the CD burning process"""
        if self.is_burning:
            return
        
        # Check if there are downloaded studies
        if len(self.downloaded_studies) == 0:
            # Try to auto-download
            if len(self.not_downloaded_studies) > 0:
                self._start_auto_download('burn')
                return  # Dialog will close and download will start
            
            QMessageBox.warning(
                self, 
                "No Downloaded Studies", 
                "No downloaded studies found.\n\n"
                "Please download the images first, then try CD burning again."
            )
            return
        
        # Validate drive selection
        if self.drive_combo.currentIndex() == 0:
            QMessageBox.warning(self, "Drive Not Selected", 
                               "Please select a CD/DVD drive first.")
            return
        
        self._execute_burn()
    
    def _execute_burn(self):
        """Execute the actual burn operation"""
        # Get settings
        drive_id = self.drive_combo.currentData()
        disc_label = self.disc_label_edit.text() or "DICOM_IMAGES"
        light_viewer_path = None
        
        if self.include_viewer_cb.isChecked():
            light_viewer_path = LightViewerSettingsWidget.get_light_viewer_path()
        
        # Confirm
        reply = QMessageBox.question(
            self,
            "Confirm Burn",
            f"Ready to burn {len(self.downloaded_studies)} downloaded studies to CD/DVD.\n\n"
            f"Disc Label: {disc_label}\n"
            f"Light Viewer: {'Yes' if light_viewer_path else 'No'}\n\n"
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
        
        # Start burn with downloaded studies only
        self.burn_manager.prepare_and_burn(
            studies=self.downloaded_studies,
            light_viewer_path=light_viewer_path,
            disc_label=disc_label,
            drive_id=drive_id,
            burn_to_disc=True
        )
    
    def prepare_folder(self):
        """Prepare CD folder structure without burning"""
        if self.is_burning:
            return
        
        # Check if there are downloaded studies
        if len(self.downloaded_studies) == 0:
            # Try to auto-download
            if len(self.not_downloaded_studies) > 0:
                self._start_auto_download('prepare')
                return  # Dialog will close and download will start
            
            QMessageBox.warning(
                self, 
                "No Downloaded Studies", 
                "No downloaded studies found.\n\n"
                "Please download the images first, then try preparing folder again."
            )
            return
        
        # Ask for output folder
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
        
        disc_label = self.disc_label_edit.text() or "DICOM_IMAGES"
        light_viewer_path = None
        
        if self.include_viewer_cb.isChecked():
            light_viewer_path = LightViewerSettingsWidget.get_light_viewer_path()
        
        self.is_burning = True
        self.burn_btn.setEnabled(False)
        self.prepare_btn.setEnabled(False)
        self.cancel_btn.setText("Cancel")
        self.log_output.setVisible(True)
        
        # Start preparation with downloaded studies only
        self.burn_manager.prepare_folder(
            studies=self.downloaded_studies,
            output_folder=folder,
            light_viewer_path=light_viewer_path,
            disc_label=disc_label
        )
    
    def on_progress(self, percent: int, message: str):
        """Handle progress updates"""
        self.progress_bar.setValue(percent)
        self.progress_message.setText(message)
        self.log_output.append(f"[{percent}%] {message}")
        
        # Scroll to bottom
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
            
            QMessageBox.information(self, "Success", message)
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
