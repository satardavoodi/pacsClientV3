"""
License Generator GUI
رابط گرافیکی تولید لایسنس برای مدیران
"""
import sys
import os

# اضافه کردن مسیر پروژه
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QSpinBox, QMessageBox,
    QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QClipboard

from modules.LicenseGenerator.license_manager import LicenseManager


class LicenseGeneratorWindow(QMainWindow):
    """پنجره تولید لایسنس"""
    
    def __init__(self):
        super().__init__()
        self.license_manager = LicenseManager()
        self.setup_ui()
        
    def setup_ui(self):
        """Setup user interface"""
        self.setWindowTitle("AIPacs License Generator - Management Tool")
        self.setMinimumWidth(700)
        self.setMinimumHeight(600)
        
        # تنظیم RTL
        self.setLayoutDirection(Qt.RightToLeft)
        
        # Widget اصلی
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Layout اصلی
        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(30, 30, 30, 30)
        
        # عنوان
        title_label = QLabel("ابزار تولید لایسنس AIPacs")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        subtitle = QLabel("برای مدیران سیستم")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet("color: #666666; font-size: 12px;")
        main_layout.addWidget(subtitle)
        
        # جداکننده
        line1 = QFrame()
        line1.setFrameShape(QFrame.HLine)
        line1.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line1)
        
        # بخش ورودی سریال
        serial_group = QVBoxLayout()
        
        serial_label = QLabel("سریال سیستم مشتری:")
        serial_font = QFont()
        serial_font.setPointSize(11)
        serial_font.setBold(True)
        serial_label.setFont(serial_font)
        serial_group.addWidget(serial_label)
        
        serial_help = QLabel("سریال 32 کاراکتری که از مشتری دریافت کرده‌اید را وارد کنید")
        serial_help.setStyleSheet("color: #666666; font-size: 11px;")
        serial_group.addWidget(serial_help)
        
        self.serial_input = QLineEdit()
        self.serial_input.setPlaceholderText("ABCD-EFGH-IJKL-MNOP-QRST-UVWX-YZ12-3456")
        self.serial_input.setStyleSheet("""
            QLineEdit {
                border: 2px solid #cccccc;
                border-radius: 6px;
                padding: 12px;
                font-size: 13px;
                font-family: 'Courier New', monospace;
                background-color: white;
            }
            QLineEdit:focus {
                border: 2px solid #2196F3;
            }
        """)
        serial_group.addWidget(self.serial_input)
        
        main_layout.addLayout(serial_group)
        
        # بخش تعداد روزها
        days_group = QVBoxLayout()
        
        days_label = QLabel("تعداد روزهای اعتبار:")
        days_label.setFont(serial_font)
        days_group.addWidget(days_label)
        
        days_layout = QHBoxLayout()
        
        self.days_spinbox = QSpinBox()
        self.days_spinbox.setMinimum(1)
        self.days_spinbox.setMaximum(3650)  # حداکثر 10 سال
        self.days_spinbox.setValue(365)
        self.days_spinbox.setSuffix(" روز")
        self.days_spinbox.setStyleSheet("""
            QSpinBox {
                border: 2px solid #cccccc;
                border-radius: 6px;
                padding: 10px;
                font-size: 13px;
                background-color: white;
            }
            QSpinBox:focus {
                border: 2px solid #2196F3;
            }
        """)
        days_layout.addWidget(self.days_spinbox)
        
        # دکمه‌های پیش‌فرض
        preset_30 = QPushButton("30 روز")
        preset_90 = QPushButton("90 روز")
        preset_180 = QPushButton("180 روز")
        preset_365 = QPushButton("1 سال")
        preset_730 = QPushButton("2 سال")
        
        for btn in [preset_30, preset_90, preset_180, preset_365, preset_730]:
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #f0f0f0;
                    border: 1px solid #cccccc;
                    border-radius: 4px;
                    padding: 8px 12px;
                    font-size: 11px;
                }
                QPushButton:hover {
                    background-color: #e0e0e0;
                }
            """)
        
        preset_30.clicked.connect(lambda: self.days_spinbox.setValue(30))
        preset_90.clicked.connect(lambda: self.days_spinbox.setValue(90))
        preset_180.clicked.connect(lambda: self.days_spinbox.setValue(180))
        preset_365.clicked.connect(lambda: self.days_spinbox.setValue(365))
        preset_730.clicked.connect(lambda: self.days_spinbox.setValue(730))
        
        days_layout.addWidget(preset_30)
        days_layout.addWidget(preset_90)
        days_layout.addWidget(preset_180)
        days_layout.addWidget(preset_365)
        days_layout.addWidget(preset_730)
        days_layout.addStretch()
        
        days_group.addLayout(days_layout)
        main_layout.addLayout(days_group)
        
        # دکمه تولید
        generate_btn = QPushButton("⚡ تولید کلید لایسنس")
        generate_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 15px;
                font-size: 15px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        generate_btn.clicked.connect(self.generate_license)
        main_layout.addWidget(generate_btn)
        
        # جداکننده
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setFrameShadow(QFrame.Sunken)
        main_layout.addWidget(line2)
        
        # بخش نمایش نتیجه
        result_label = QLabel("کلید لایسنس تولید شده:")
        result_label.setFont(serial_font)
        main_layout.addWidget(result_label)
        
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(100)
        self.result_text.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 2px solid #28a745;
                border-radius: 6px;
                padding: 15px;
                font-family: 'Courier New', monospace;
                font-size: 14px;
                color: #28a745;
                font-weight: bold;
            }
        """)
        main_layout.addWidget(self.result_text)
        
        # دکمه کپی
        copy_btn = QPushButton("📋 کپی کلید لایسنس")
        copy_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #0b7dda;
            }
            QPushButton:pressed {
                background-color: #0a6bc5;
            }
        """)
        copy_btn.clicked.connect(self.copy_license)
        main_layout.addWidget(copy_btn)
        
        # فاصله
        main_layout.addStretch()
        
        # اطلاعات تکمیلی
        info_text = QLabel(
            "⚠️ توجه: کلید لایسنس تولید شده فقط برای سیستمی که سریال آن وارد شده است معتبر است."
        )
        info_text.setWordWrap(True)
        info_text.setStyleSheet("""
            QLabel {
                background-color: #fff3cd;
                border: 1px solid #ffc107;
                border-radius: 6px;
                padding: 12px;
                color: #856404;
                font-size: 11px;
            }
        """)
        main_layout.addWidget(info_text)
        
        # استایل کلی
        self.setStyleSheet("""
            QMainWindow {
                background-color: white;
            }
            QLabel {
                color: #333333;
            }
        """)
        
        central_widget.setLayout(main_layout)
    
    def generate_license(self):
        """تولید کلید لایسنس"""
        # دریافت سریال
        serial = self.serial_input.text().strip().replace('-', '').upper()
        
        if not serial:
            QMessageBox.warning(
                self,
                "Error",
                "Please enter the system serial.",
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
        
        # دریافت تعداد روزها
        days = self.days_spinbox.value()
        
        # تولید لایسنس
        try:
            license_key = self.license_manager.generate_license_key(serial, days)
            formatted_key = self.license_manager.format_license_key(license_key)
            
            # اعتبارسنجی
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
                    f"License validation error:\n{message}",
                    QMessageBox.Ok
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"License generation error:\n{str(e)}",
                QMessageBox.Ok
            )
    
    def copy_license(self):
        """کپی کردن کلید لایسنس"""
        license_text = self.result_text.toPlainText().strip()
        
        if not license_text:
            QMessageBox.warning(
                self,
                "Error",
                "You must generate a license key first.",
                QMessageBox.Ok
            )
            return
        
        clipboard = QApplication.clipboard()
        clipboard.setText(license_text)
        
        QMessageBox.information(
            self,
            "Copied",
            "License key copied successfully.\nYou can send it to the customer.",
            QMessageBox.Ok
        )


def main():
    """تابع اصلی"""
    app = QApplication(sys.argv)
    
    # تنظیم فونت
    app.setFont(QFont("Segoe UI", 10))
    
    window = LicenseGeneratorWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
