"""
AIPacs License Generator
Professional license management tool for administrators
"""
import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QSpinBox, QMessageBox,
    QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QClipboard, QIcon

from license_manager import LicenseManager


class LicenseGeneratorWindow(QMainWindow):
    """License Generator Main Window"""
    
    def __init__(self):
        super().__init__()
        self.license_manager = LicenseManager()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup user interface"""
        self.setWindowTitle("AIPacs License Generator - Admin Tool")
        self.setMinimumWidth(800)
        self.setMinimumHeight(700)
        
        # Set LTR for English
        self.setLayoutDirection(Qt.LeftToRight)
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setSpacing(25)
        main_layout.setContentsMargins(40, 40, 40, 40)
        
        # Title
        title_label = QLabel("AIPacs License Generator")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        subtitle = QLabel("Administrative License Management Tool")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle_font = QFont()
        subtitle_font.setPointSize(11)
        subtitle.setFont(subtitle_font)
        main_layout.addWidget(subtitle)
        
        # Separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line1)
        
        main_layout.addSpacing(10)
        
        # Customer Serial Section
        serial_group = QVBoxLayout()
        
        serial_label = QLabel("Customer System Serial")
        serial_font = QFont()
        serial_font.setPointSize(13)
        serial_font.setBold(True)
        serial_label.setFont(serial_font)
        serial_group.addWidget(serial_label)
        
        serial_help = QLabel("Enter the 32-character serial number received from customer")
        serial_help_font = QFont()
        serial_help_font.setPointSize(10)
        serial_help.setFont(serial_help_font)
        serial_group.addWidget(serial_help)
        
        self.serial_input = QLineEdit()
        self.serial_input.setPlaceholderText("ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ12-3456")
        self.serial_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #4a5568;
                border-radius: 6px;
                padding: 14px;
                font-size: 14px;
                font-family: 'Courier New', monospace;
                background-color: #2d3748;
                color: #e2e8f0;
            }
            QLineEdit:focus {
                border: 2px solid #3b82f6;
                background-color: #374151;
            }
        """)
        serial_group.addWidget(self.serial_input)
        
        main_layout.addLayout(serial_group)
        
        main_layout.addSpacing(10)
        
        # Validity Duration Section
        days_group = QVBoxLayout()
        
        days_label = QLabel("License Validity Period")
        days_label.setFont(serial_font)
        days_group.addWidget(days_label)
        
        days_layout = QHBoxLayout()
        days_layout.setSpacing(10)
        
        self.days_spinbox = QSpinBox()
        self.days_spinbox.setMinimum(1)
        self.days_spinbox.setMaximum(3650)  # Max 10 years
        self.days_spinbox.setValue(365)
        self.days_spinbox.setSuffix(" days")
        self.days_spinbox.setStyleSheet("""
            QSpinBox {
                border: 1px solid #4a5568;
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                background-color: #2d3748;
                color: #e2e8f0;
                min-width: 150px;
            }
            QSpinBox:focus {
                border: 2px solid #3b82f6;
                background-color: #374151;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #374151;
                border: none;
                width: 20px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #4a5568;
            }
        """)
        days_layout.addWidget(self.days_spinbox)
        
        # Preset buttons
        preset_30 = self._create_preset_button("30 Days", 30)
        preset_90 = self._create_preset_button("90 Days", 90)
        preset_180 = self._create_preset_button("180 Days", 180)
        preset_365 = self._create_preset_button("1 Year", 365)
        preset_730 = self._create_preset_button("2 Years", 730)
        
        days_layout.addWidget(preset_30)
        days_layout.addWidget(preset_90)
        days_layout.addWidget(preset_180)
        days_layout.addWidget(preset_365)
        days_layout.addWidget(preset_730)
        days_layout.addStretch()
        
        days_group.addLayout(days_layout)
        main_layout.addLayout(days_group)
        
        main_layout.addSpacing(10)
        
        # Generate button
        generate_btn = QPushButton("⚡ Generate License Key")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 16px;
                font-size: 16px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        generate_btn.clicked.connect(self.generate_license)
        main_layout.addWidget(generate_btn)
        
        main_layout.addSpacing(10)
        
        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line2)
        
        main_layout.addSpacing(10)
        
        # Result Section
        result_label = QLabel("Generated License Key")
        result_label.setFont(serial_font)
        main_layout.addWidget(result_label)
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(100)
        self.result_text.setStyleSheet("""
            QTextEdit {
                background-color: #064e3b;
                border: 2px solid #10b981;
                border-radius: 6px;
                padding: 15px;
                font-family: 'Courier New', monospace;
                font-size: 15px;
                color: #10b981;
                font-weight: bold;
            }
        """)
        main_layout.addWidget(self.result_text)
        
        # Copy button
        copy_btn = QPushButton("📋 Copy License Key")
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
        """)
        copy_btn.clicked.connect(self.copy_license)
        main_layout.addWidget(copy_btn)
        
        # Stretch
        main_layout.addStretch()
        
        # Warning info
        info_text = QLabel(
            "⚠️ Important: The generated license key is only valid for the system "
            "with the serial number entered above."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("""
            QLabel {
                background-color: #78350f;
                border: 1px solid #f59e0b;
                border-radius: 6px;
                padding: 14px;
                color: #fbbf24;
                font-size: 11px;
            }
        """)
        main_layout.addWidget(info_text)
        
        # Apply global dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a202c;
            }
            QLabel {
                color: #e2e8f0;
            }
            QFrame[frameShape="4"] {
                color: #4a5568;
            }
        """)
        
        central_widget.setLayout(main_layout)
    
    def _create_preset_button(self, text: str, days: int) -> QPushButton:
        """Create preset duration button"""
        btn = QPushButton(text)
        btn.setStyleSheet("""
            QPushButton {
                background-color: #374151;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 4px;
                padding: 10px 14px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #4a5568;
                border-color: #6b7280;
            }
            QPushButton:pressed {
                background-color: #1f2937;
            }
        """)
        btn.clicked.connect(lambda: self.days_spinbox.setValue(days))
        return btn
    
    def generate_license(self):
        """Generate license key"""
        # Get serial
        serial = self.serial_input.text().strip().replace('-', '').upper()
        
        if not serial:
            QMessageBox.warning(
                self,
                "Error",
                "Please enter the system serial number.",
                QMessageBox.Ok
            )
            return
        
        if len(serial) != 32:
            QMessageBox.warning(
                self,
                "Error",
                f"System serial must be 32 characters.\nCurrent length: {len(serial)} characters",
                QMessageBox.Ok
            )
            return
        
        # Get number of days
        days = self.days_spinbox.value()
        
        # Generate license
        try:
            license_key = self.license_manager.generate_license_key(serial, days)
            formatted_key = self.license_manager.format_license_key(license_key)
            
            # Validate
            is_valid, message = self.license_manager.validate_license(license_key, serial)
            
            if is_valid:
                self.result_text.setPlainText(formatted_key)
                
                QMessageBox.information(
                    self,
                    "Success",
                    f"License key generated successfully!\n\n{message}",
                    QMessageBox.Ok
                )
            else:
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Error validating license:\n{message}",
                    QMessageBox.Ok
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Error generating license:\n{str(e)}",
                QMessageBox.Ok
            )
    
    def copy_license(self):
        """Copy license key to clipboard"""
        license_text = self.result_text.toPlainText().strip()
        
        if not license_text:
            QMessageBox.warning(
                self,
                "Error",
                "Please generate a license key first.",
                QMessageBox.Ok
            )
            return
        
        clipboard = QApplication.clipboard()
        clipboard.setText(license_text)
        
        QMessageBox.information(
            self,
            "Copied",
            "License key has been copied to clipboard.\nYou can now send it to the customer.",
            QMessageBox.Ok
        )


def main():
    """Main function"""
    app = QApplication(sys.argv)
    
    # Set application properties
    app.setApplicationName("AIPacs License Generator")
    app.setApplicationDisplayName("AIPacs License Generator")
    app.setApplicationVersion("1.0.0")
    
    # Set font
    app.setFont(QFont("Segoe UI", 10))
    
    window = LicenseGeneratorWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
