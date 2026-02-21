from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QProgressBar,
    QDialog,
    QRadioButton,
    QSpinBox,
    QButtonGroup,
    QGroupBox,
)

from PacsClient.utils.config import BASE_PATH
from PacsClient.utils.local_storage_cleanup_manager import LocalStorageCleanupManager


class StorageCleanupPanelWidget(QWidget):
    """Reusable panel for storage insights + cleanup actions."""

    storageChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cleanup_manager = LocalStorageCleanupManager()
        self.folder_size_labels: Dict[str, QLabel] = {}
        self.folder_comp_labels: Dict[str, QLabel] = {}
        self.drive_usage_container: QVBoxLayout | None = None
        self.storage_summary_label: QLabel | None = None
        self._setup_ui()
        self.refresh_storage_insights(force_refresh=True)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)  # Generous outer padding
        layout.setSpacing(20)  # Large vertical spacing between sections

        # Title with larger, bold font
        cleanup_title = QLabel("Local Storage & Database Cleanup")
        cleanup_title.setStyleSheet("font-weight: 700; font-size: 16px; color: #f3f4f6;")
        layout.addWidget(cleanup_title)

        # Description with readable font size
        cleanup_desc = QLabel(
            "Clearing a folder also cleans matching database records. "
            "Core app data (e.g., license and global configuration) is never deleted."
        )
        cleanup_desc.setWordWrap(True)
        cleanup_desc.setStyleSheet(
            "color: #d1d5db; font-size: 14px; padding: 10px; "
            "background-color: #1f2937; border-radius: 6px; line-height: 1.6;"
        )
        layout.addWidget(cleanup_desc)

        layout.addSpacing(15)  # Extra space before drives section

        # Drives section with card-style grouping
        drives_card = QWidget()
        drives_card.setStyleSheet(
            "QWidget { background-color: #111827; border: 1px solid #374151; "
            "border-radius: 8px; padding: 15px; }"
        )
        drives_card_layout = QVBoxLayout(drives_card)
        drives_card_layout.setSpacing(12)
        
        drives_title = QLabel("Overall Computer / Drives Usage")
        drives_title.setStyleSheet("font-weight: 600; font-size: 15px; color: #f9fafb;")
        drives_card_layout.addWidget(drives_title)

        self.drive_usage_container = QVBoxLayout()
        self.drive_usage_container.setSpacing(12)  # More space between drives
        drives_card_layout.addLayout(self.drive_usage_container)
        
        layout.addWidget(drives_card)
        layout.addSpacing(15)  # Extra space before folders section

        # Folders section with card-style grouping
        folders_card = QWidget()
        folders_card.setStyleSheet(
            "QWidget { background-color: #111827; border: 1px solid #374151; "
            "border-radius: 8px; padding: 15px; }"
        )
        folders_card_layout = QVBoxLayout(folders_card)
        folders_card_layout.setSpacing(15)
        
        folders_title = QLabel("Per-Folder Storage Usage Breakdown")
        folders_title.setStyleSheet("font-weight: 600; font-size: 15px; color: #f9fafb;")
        folders_card_layout.addWidget(folders_title)

        refresh_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄  Refresh Storage Info")
        refresh_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 10px 20px; min-height: 40px; "
            "background-color: #3b82f6; border: none; border-radius: 6px; font-weight: 600; } "
            "QPushButton:hover { background-color: #2563eb; }"
        )
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(lambda: self.refresh_storage_insights(force_refresh=True))
        refresh_row.addWidget(refresh_btn)
        refresh_row.addStretch(1)
        folders_card_layout.addLayout(refresh_row)

        self.storage_summary_label = QLabel("")
        self.storage_summary_label.setStyleSheet(
            "color: #d1d5db; font-size: 14px; padding: 8px; "
            "background-color: #1f2937; border-radius: 4px;"
        )
        self.storage_summary_label.setWordWrap(True)
        folders_card_layout.addWidget(self.storage_summary_label)

        folders_card_layout.addSpacing(10)
        self._build_cleanup_rows(folders_card_layout)
        
        layout.addWidget(folders_card)
        layout.addStretch(1)

    def _build_cleanup_rows(self, parent_layout: QVBoxLayout):
        folder_map = self.cleanup_manager.get_folder_map()
        rows = [
            ("patients", "Patients Data Folder", "Clear Patients Data"),
            ("education", "Education Folder", "Clear Education"),
            ("cache", "Cache Folder", "Clear Cache"),
            ("printing", "Printing Folder", "Clear Printing"),
        ]

        for key, label_text, btn_text in rows:
            # Each row gets its own card for visual separation
            row_card = QWidget()
            row_card.setStyleSheet(
                "QWidget { background-color: #1f2937; border: 1px solid #4b5563; "
                "border-radius: 6px; padding: 12px; }"
            )
            row_layout = QVBoxLayout(row_card)
            row_layout.setSpacing(10)
            
            # Top: Label and size
            top_row = QHBoxLayout()
            top_row.setSpacing(15)
            
            label = QLabel(label_text)
            label.setStyleSheet("font-size: 14px; font-weight: 600; color: #f9fafb;")
            label.setMinimumWidth(180)
            top_row.addWidget(label)
            
            size_label = QLabel("0 B")
            size_label.setMinimumWidth(100)
            size_label.setStyleSheet(
                "color: #10b981; font-weight: 700; font-size: 14px; "
                "padding: 4px 8px; background-color: #064e3b; border-radius: 4px;"
            )
            self.folder_size_labels[key] = size_label
            top_row.addWidget(size_label)
            
            comp_label = QLabel("0% of used disk")
            comp_label.setMinimumWidth(140)
            comp_label.setStyleSheet("color: #d1d5db; font-size: 14px;")
            self.folder_comp_labels[key] = comp_label
            top_row.addWidget(comp_label)
            
            top_row.addStretch(1)
            
            clear_btn = QPushButton(btn_text)
            clear_btn.setMinimumHeight(36)
            clear_btn.setMinimumWidth(180)
            clear_btn.setCursor(Qt.PointingHandCursor)
            clear_btn.setStyleSheet(
                "QPushButton { background-color: #1d4ed8; border: none; "
                "border-radius: 6px; font-size: 14px; font-weight: 600; "
                "padding: 8px 14px; color: white; } "
                "QPushButton:hover { background-color: #1e40af; }"
            )
            if key == "patients":
                clear_btn.clicked.connect(lambda _, k=key: self._show_patient_cleanup_dialog())
            else:
                clear_btn.clicked.connect(lambda _, k=key: self._handle_cleanup_action(k))
            top_row.addWidget(clear_btn)
            
            row_layout.addLayout(top_row)
            
            # Bottom: Path (smaller, secondary info)
            paths = folder_map.get(key, [])
            path_label = QLabel(" | ".join(str(p) for p in paths))
            path_label.setWordWrap(True)
            path_label.setStyleSheet(
                "color: #9ca3af; font-size: 14px; padding-left: 4px; font-style: italic;"
            )
            row_layout.addWidget(path_label)
            
            parent_layout.addWidget(row_card)

    def _handle_cleanup_action(self, category: str):
        title_map = {
            "patients": "Patients Data",
            "education": "Education",
            "cache": "Cache",
            "printing": "Printing",
        }
        pretty = title_map.get(category, category)

        answer = QMessageBox.question(
            self,
            f"Confirm {pretty} Cleanup",
            (
                f"This will permanently clear local {pretty} folder data and related database entries.\n\n"
                "Core app data (license/config) will NOT be removed.\n\n"
                "Do you want to continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            if category == "patients":
                result = self.cleanup_manager.cleanup_patients_folder()
            elif category == "education":
                result = self.cleanup_manager.cleanup_education_folder()
            elif category == "cache":
                result = self.cleanup_manager.cleanup_cache_folder()
            elif category == "printing":
                result = self.cleanup_manager.cleanup_printing_folder()
            else:
                raise ValueError(f"Unknown cleanup category: {category}")

            QMessageBox.information(
                self,
                "Cleanup Completed",
                (
                    f"{result.message}\n\n"
                    f"Folders touched: {result.folders_touched}\n"
                    f"Files deleted: {result.files_deleted}\n"
                    f"DB rows affected: {result.db_rows_affected}"
                ),
            )
            self.refresh_storage_insights(force_refresh=True)
            self.storageChanged.emit()
        except Exception as e:
            QMessageBox.critical(
                self,
                "Cleanup Failed",
                f"Could not complete cleanup:\n{e}",
            )

    def _show_patient_cleanup_dialog(self):
        """Show dialog with patient cleanup filtering options."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Patient Data Cleanup Options")
        dialog.setModal(True)
        dialog.setMinimumWidth(650)  # Wider for comfortable reading
        dialog.setMinimumHeight(550)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(25, 25, 25, 25)  # Generous padding
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("🗑️  Patient Data Cleanup")
        title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #f3f4f6;")
        layout.addWidget(title_label)
        
        info_label = QLabel(
            "Choose how to clean patient data. This will permanently remove matching folders and database entries."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "color: #d1d5db; font-size: 14px; padding: 12px; "
            "background-color: #1f2937; border-radius: 6px; line-height: 1.5;"
        )
        layout.addWidget(info_label)
        
        layout.addSpacing(10)
        
        # Strategy group with enhanced styling
        strategy_group = QGroupBox("Cleanup Strategy")
        strategy_group.setStyleSheet(
            "QGroupBox { font-size: 15px; font-weight: 600; color: #f9fafb; "
            "border: 2px solid #4b5563; border-radius: 8px; padding: 20px 15px 15px 15px; "
            "margin-top: 12px; } "
            "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; "
            "padding: 4px 10px; background-color: #1f2937; border-radius: 4px; }"
        )
        strategy_layout = QVBoxLayout()
        strategy_layout.setSpacing(18)  # Large spacing between options
        
        radio_group = QButtonGroup(dialog)
        
        # Style for all radio buttons - LARGE and readable
        radio_style = (
            "QRadioButton { font-size: 14px; color: #e5e7eb; spacing: 10px; } "
            "QRadioButton::indicator { width: 20px; height: 20px; }"
        )
        
        # Style for all spinboxes - LARGE controls for 50+ users
        spinbox_style = (
            "QSpinBox { font-size: 15px; font-weight: 600; padding: 8px 12px; "
            "min-width: 120px; min-height: 36px; background-color: #374151; "
            "border: 2px solid #6b7280; border-radius: 6px; color: #f9fafb; } "
            "QSpinBox::up-button { width: 28px; border-left: 2px solid #6b7280; "
            "background-color: #4b5563; } "
            "QSpinBox::down-button { width: 28px; border-left: 2px solid #6b7280; "
            "background-color: #4b5563; } "
            "QSpinBox::up-arrow { width: 12px; height: 12px; } "
            "QSpinBox::down-arrow { width: 12px; height: 12px; }"
        )
        
        # Option 1: Clear all
        all_radio = QRadioButton("Clear ALL patient data (folders + database)")
        all_radio.setStyleSheet(radio_style)
        all_radio.setChecked(True)
        radio_group.addButton(all_radio, 0)
        strategy_layout.addWidget(all_radio)
        
        # Option 2: Keep recent days
        recent_layout = QHBoxLayout()
        recent_layout.setSpacing(15)
        recent_radio = QRadioButton("Keep only patients from last")
        recent_radio.setStyleSheet(radio_style)
        radio_group.addButton(recent_radio, 1)
        recent_spin = QSpinBox()
        recent_spin.setRange(1, 365)
        recent_spin.setValue(30)
        recent_spin.setSuffix(" days")
        recent_spin.setStyleSheet(spinbox_style)
        recent_spin.setEnabled(False)
        recent_radio.toggled.connect(recent_spin.setEnabled)
        recent_layout.addWidget(recent_radio)
        recent_layout.addWidget(recent_spin)
        recent_layout.addStretch()
        strategy_layout.addLayout(recent_layout)
        
        # Option 3: Delete older than
        older_layout = QHBoxLayout()
        older_layout.setSpacing(15)
        older_radio = QRadioButton("Delete patients older than")
        older_radio.setStyleSheet(radio_style)
        radio_group.addButton(older_radio, 2)
        older_spin = QSpinBox()
        older_spin.setRange(1, 365)
        older_spin.setValue(90)
        older_spin.setSuffix(" days")
        older_spin.setStyleSheet(spinbox_style)
        older_spin.setEnabled(False)
        older_radio.toggled.connect(older_spin.setEnabled)
        older_layout.addWidget(older_radio)
        older_layout.addWidget(older_spin)
        older_layout.addStretch()
        strategy_layout.addLayout(older_layout)
        
        # Option 4: Delete oldest count
        count_layout = QHBoxLayout()
        count_layout.setSpacing(15)
        count_radio = QRadioButton("Delete oldest")
        count_radio.setStyleSheet(radio_style)
        radio_group.addButton(count_radio, 3)
        count_spin = QSpinBox()
        count_spin.setRange(1, 10000)
        count_spin.setValue(50)
        count_spin.setSuffix(" patients")
        count_spin.setStyleSheet(spinbox_style)
        count_spin.setEnabled(False)
        count_radio.toggled.connect(count_spin.setEnabled)
        count_layout.addWidget(count_radio)
        count_layout.addWidget(count_spin)
        count_layout.addStretch()
        strategy_layout.addLayout(count_layout)
        
        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)
        
        layout.addSpacing(15)
        
        # Buttons - LARGE and clearly separated
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        preview_btn = QPushButton("👁️  Preview Count")
        preview_btn.setMinimumHeight(36)
        preview_btn.setMinimumWidth(160)
        preview_btn.setCursor(Qt.PointingHandCursor)
        preview_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 600; padding: 8px 14px; "
            "background-color: #3b82f6; border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #2563eb; }"
        )
        preview_btn.clicked.connect(
            lambda: self._preview_patient_cleanup(
                radio_group.checkedId(), recent_spin.value(), older_spin.value(), count_spin.value(), dialog
            )
        )
        
        execute_btn = QPushButton("⚠️  Execute Cleanup")
        execute_btn.setMinimumHeight(36)
        execute_btn.setMinimumWidth(180)
        execute_btn.setCursor(Qt.PointingHandCursor)
        execute_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 700; padding: 8px 14px; "
            "background-color: #1d4ed8; border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #1e40af; }"
        )
        execute_btn.clicked.connect(
            lambda: self._execute_patient_cleanup(
                radio_group.checkedId(), recent_spin.value(), older_spin.value(), count_spin.value(), dialog
            )
        )
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(36)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 600; padding: 8px 14px; "
            "background-color: #4b5563; border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #6b7280; }"
        )
        cancel_btn.clicked.connect(dialog.reject)
        
        btn_layout.addWidget(preview_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(execute_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    def _preview_patient_cleanup(self, strategy_id: int, recent_days: int, older_days: int, count: int, parent: QWidget):
        """Preview how many patients will be deleted."""
        try:
            if strategy_id == 0:
                total = self.cleanup_manager.get_total_patient_count()
                msg = f"This will delete ALL {total} patients."
            elif strategy_id == 1:
                matching = self.cleanup_manager.count_patients_to_delete(strategy="keep_recent_days", value=recent_days)
                total = self.cleanup_manager.get_total_patient_count()
                kept = total - matching
                msg = f"This will delete {matching} patients (keeping {kept} from last {recent_days} days)."
            elif strategy_id == 2:
                matching = self.cleanup_manager.count_patients_to_delete(strategy="older_than_days", value=older_days)
                msg = f"This will delete {matching} patients older than {older_days} days."
            elif strategy_id == 3:
                total = self.cleanup_manager.get_total_patient_count()
                actual_count = min(count, total)
                msg = f"This will delete the oldest {actual_count} patients (of {total} total)."
            else:
                msg = "Unknown strategy."
            
            QMessageBox.information(parent, "Preview Patient Cleanup", msg)
        except Exception as e:
            QMessageBox.warning(parent, "Preview Failed", f"Could not preview cleanup:\n{e}")
    
    def _execute_patient_cleanup(self, strategy_id: int, recent_days: int, older_days: int, count: int, parent: QDialog):
        """Execute filtered patient cleanup based on chosen strategy."""
        confirm = QMessageBox.question(
            parent,
            "Confirm Patient Cleanup",
            "This will permanently delete patient folders and database entries.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        
        try:
            if strategy_id == 0:
                result = self.cleanup_manager.cleanup_patients_folder()
            elif strategy_id == 1:
                result = self.cleanup_manager.cleanup_patients_folder_filtered(strategy="keep_recent_days", value=recent_days)
            elif strategy_id == 2:
                result = self.cleanup_manager.cleanup_patients_folder_filtered(strategy="older_than_days", value=older_days)
            elif strategy_id == 3:
                result = self.cleanup_manager.cleanup_patients_folder_filtered(strategy="delete_oldest_count", value=count)
            else:
                raise ValueError(f"Unknown strategy ID: {strategy_id}")
            
            QMessageBox.information(
                parent,
                "Cleanup Completed",
                (
                    f"{result.message}\n\n"
                    f"Folders touched: {result.folders_touched}\n"
                    f"Files deleted: {result.files_deleted}\n"
                    f"DB rows affected: {result.db_rows_affected}"
                ),
            )
            parent.accept()
            self.refresh_storage_insights(force_refresh=True)
            self.storageChanged.emit()
        except Exception as e:
            QMessageBox.critical(parent, "Cleanup Failed", f"Could not complete cleanup:\n{e}")

    def refresh_storage_insights(self, force_refresh: bool = False):
        if self.drive_usage_container is None:
            return

        while self.drive_usage_container.count():
            item = self.drive_usage_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        drive_rows = self.cleanup_manager.get_drive_usage_info()
        for row in drive_rows:
            used_pct = float(row.get("used_percent", 0.0))
            free_pct = 100.0 - used_pct
            
            # Color logic: blue if <20% free, yellow if 20-40% free, green if >40% free
            if free_pct < 20.0:
                bar_color = "#60a5fa"  # blue
            elif free_pct < 40.0:
                bar_color = "#f59e0b"  # amber/yellow
            else:
                bar_color = "#10b981"  # green
            
            drive_row = QVBoxLayout()
            drive_row.setSpacing(4)
            
            drive_label = QLabel(
                f"<b>{row.get('drive')}</b>  —  "
                f"Used: <b>{self.cleanup_manager.format_size(int(row.get('used', 0)))}</b> / "
                f"{self.cleanup_manager.format_size(int(row.get('total', 0)))}  "
                f"({used_pct:.1f}%)  —  "
                f"Free: <b>{self.cleanup_manager.format_size(int(row.get('free', 0)))}</b>"
            )
            drive_label.setStyleSheet(f"color: {bar_color}; font-size: 14px; font-weight: 600;")
            drive_row.addWidget(drive_label)
            
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(int(used_pct))
            progress_bar.setTextVisible(False)
            progress_bar.setFixedHeight(20)  # Taller for better visibility
            progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 2px solid #4b5563;
                    border-radius: 5px;
                    background-color: #1f2937;
                }}
                QProgressBar::chunk {{
                    background-color: {bar_color};
                    border-radius: 3px;
                }}
            """)
            drive_row.addWidget(progress_bar)
            
            drive_widget = QWidget()
            drive_widget.setLayout(drive_row)
            self.drive_usage_container.addWidget(drive_widget)

        folder_sizes = self.cleanup_manager.get_folder_usage_breakdown(force_refresh=force_refresh)
        current_drive_anchor = str(BASE_PATH.anchor or "").upper()
        current_drive_used = 0
        for row in drive_rows:
            if str(row.get("drive", "")).upper().startswith(current_drive_anchor):
                current_drive_used = int(row.get("used", 0))
                break
        if current_drive_used <= 0 and drive_rows:
            current_drive_used = int(drive_rows[0].get("used", 0))

        total_managed = 0
        for key, value in folder_sizes.items():
            size_bytes = int(value or 0)
            total_managed += size_bytes
            if key in self.folder_size_labels:
                self.folder_size_labels[key].setText(self.cleanup_manager.format_size(size_bytes))
            if key in self.folder_comp_labels:
                ratio = (size_bytes / current_drive_used * 100.0) if current_drive_used > 0 else 0.0
                self.folder_comp_labels[key].setText(f"{ratio:.2f}% of used disk")

        if self.storage_summary_label is not None:
            self.storage_summary_label.setText(
                f"Managed folders total: {self.cleanup_manager.format_size(total_managed)}. "
                "Click Refresh to recalculate after cleanup."
            )
