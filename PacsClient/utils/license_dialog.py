"""
License Dialog
License Activation Window
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QLineEdit, QPushButton, QTextEdit, QMessageBox,
    QFrame
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QClipboard
from .license_manager import LicenseManager
from PySide6.QtWidgets import QApplication

class LicenseDialog(QDialog):
    """License Activation Dialog"""
    
    license_activated = Signal()  # Signal for successful activation
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.license_manager = LicenseManager()
        self.setup_ui()
        self.load_hardware_id()
        
    def setup_ui(self):
        """Setup user interface"""
        self.setWindowTitle("License Activation - AIPacs")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        
        # Set LTR for English
        self.setLayoutDirection(Qt.LeftToRight)
        
        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setSpacing(25)
        main_layout.setContentsMargins(40, 40, 40, 40)
        
        # Title
        title_label = QLabel("AIPacs License Activation")
        title_font = QFont()
        title_font.setPointSize(20)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # Subtitle
        subtitle_label = QLabel("Professional Medical Imaging Suite")
        subtitle_font = QFont()
        subtitle_font.setPointSize(10)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(subtitle_label)
        
        # Info text
        info_label = QLabel(
            "To activate the application, please send your system serial to our support team\n"
            "and enter the license key you receive below."
        )
        info_label.setWordWrap(True)
        info_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(info_label)
        
        # Spacing
        main_layout.addSpacing(10)
        
        # Separator
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line1)
        
        main_layout.addSpacing(10)
        
        # System Serial Section
        serial_group = QVBoxLayout()
        
        serial_title = QLabel("System Serial Number")
        serial_title_font = QFont()
        serial_title_font.setPointSize(12)
        serial_title_font.setBold(True)
        serial_title.setFont(serial_title_font)
        serial_group.addWidget(serial_title)
        
        # Serial display
        self.serial_text = QTextEdit()
        self.serial_text.setReadOnly(True)
        self.serial_text.setMaximumHeight(70)
        self.serial_text.setStyleSheet("""
            QTextEdit {
                background-color: #2d3748;
                border: 1px solid #4a5568;
                border-radius: 6px;
                padding: 12px;
                font-family: 'Courier New', monospace;
                font-size: 13px;
                color: #e2e8f0;
            }
        """)
        serial_group.addWidget(self.serial_text)
        
        # Copy serial button
        copy_serial_btn = QPushButton("📋  Copy Serial Number")
        copy_serial_btn.setStyleSheet("""
            QPushButton {
                background-color: #10b981;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px 20px;
                font-size: 13px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #059669;
            }
            QPushButton:pressed {
                background-color: #047857;
            }
        """)
        copy_serial_btn.clicked.connect(self.copy_serial)
        serial_group.addWidget(copy_serial_btn)
        
        main_layout.addLayout(serial_group)
        
        main_layout.addSpacing(10)
        
        # Separator
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line2)
        
        main_layout.addSpacing(10)
        
        # License Key Section
        license_group = QVBoxLayout()
        
        license_title = QLabel("License Key")
        license_title_font = QFont()
        license_title_font.setPointSize(12)
        license_title_font.setBold(True)
        license_title.setFont(license_title_font)
        license_group.addWidget(license_title)
        
        license_info = QLabel("Please enter the license key you received:")
        license_group.addWidget(license_info)
        
        # License input
        self.license_input = QLineEdit()
        self.license_input.setPlaceholderText("Example: 20261231-ABCD-EFGH-IJKL-MNOP-QRST-UVWX")
        self.license_input.setStyleSheet("""
            QLineEdit {
                border: 1px solid #4a5568;
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                background-color: #2d3748;
                color: #e2e8f0;
            }
            QLineEdit:focus {
                border: 2px solid #3b82f6;
                background-color: #374151;
            }
        """)
        license_group.addWidget(self.license_input)
        
        main_layout.addLayout(license_group)
        
        # Spacing
        main_layout.addStretch()
        
        # Action buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)
        
        # Activate button
        activate_btn = QPushButton("✓  Activate License")
        activate_btn.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 14px 28px;
                font-size: 14px;
                font-weight: bold;
                min-width: 160px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
        """)
        activate_btn.clicked.connect(self.activate_license)
        buttons_layout.addWidget(activate_btn)
        
        # Exit button
        exit_btn = QPushButton("Exit Application")
        exit_btn.setStyleSheet("""
            QPushButton {
                background-color: #4a5568;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 14px 28px;
                font-size: 14px;
                font-weight: bold;
                min-width: 160px;
            }
            QPushButton:hover {
                background-color: #374151;
            }
            QPushButton:pressed {
                background-color: #1f2937;
            }
        """)
        exit_btn.clicked.connect(self.reject_and_exit)
        buttons_layout.addWidget(exit_btn)
        
        main_layout.addLayout(buttons_layout)
        
        # Apply global dark theme style
        self.setStyleSheet("""
            QDialog {
                background-color: #1a202c;
            }
            QLabel {
                color: #e2e8f0;
            }
            QFrame[frameShape="4"] {
                color: #4a5568;
            }
        """)
        
        self.setLayout(main_layout)
    
    def load_hardware_id(self):
        """Load and display system serial"""
        hardware_id = self.license_manager.get_hardware_id()
        formatted_id = self.license_manager.format_hardware_id(hardware_id)
        self.serial_text.setPlainText(formatted_id)
    
    def copy_serial(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.serial_text.toPlainText())

        QMessageBox.information(
            self,
            "Copied Successfully",
            "System serial number has been copied to clipboard.\nYou can now send it to our support team.",
            QMessageBox.Ok
        )
        
    def activate_license(self):
        """Activate license"""
        license_key = self.license_input.text().strip()
        
        if not license_key:
            QMessageBox.warning(
                self,
                "Error",
                "Please enter the license key.",
                QMessageBox.Ok
            )
            return
        
        # Save and validate license
        success, message = self.license_manager.save_license(license_key)
        
        if success:
            QMessageBox.information(
                self,
                "Success",
                message,
                QMessageBox.Ok
            )
            self.license_activated.emit()
            self.accept()
        else:
            QMessageBox.critical(
                self,
                "Error",
                message,
                QMessageBox.Ok
            )
    
    def reject_and_exit(self):
        """Reject and exit application"""
        reply = QMessageBox.question(
            self,
            "Exit Application",
            "Are you sure you want to exit?\n"
            "A valid license is required to use this application.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            self.reject()
