#!/usr/bin/env python
# -*- coding: utf-8 -*-

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QFrame, QSpinBox, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
import qtawesome as qta
from .socket_config import get_socket_config
from PacsClient.utils import IMAGES_LOGIN_PATH


class ServerSettingsDialog(QDialog):
    """Dialog for configuring Socket server settings"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = get_socket_config()
        self.setup_ui()
        self.load_settings()
    
    def setup_ui(self):
        """Setup UI"""
        self.setWindowTitle("Server Settings")
        self.setWindowIcon(QIcon(str(IMAGES_LOGIN_PATH / "favicon.ico")))
        self.setMinimumWidth(500)
        self.setModal(True)
        
        # Modern styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #0a0e13, stop:0.3 #0f1419, stop:0.7 #141a21, stop:1 #0a0e13);
            }
            
            QLabel {
                color: #cbd5e1;
                font-size: 13px;
                font-weight: 600;
            }
            
            QLabel#TitleLabel {
                color: #f8fafc;
                font-size: 20px;
                font-weight: 700;
                margin-bottom: 10px;
            }
            
            QLabel#DescLabel {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 400;
                margin-bottom: 20px;
            }
            
            QLineEdit, QSpinBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e293b, stop:1 #0f172a);
                color: #f1f5f9;
                border: 2px solid #334155;
                border-radius: 8px;
                padding: 9px 12px;
                font-size: 13px;
                min-height: 34px;
                font-weight: 500;
            }
            
            QLineEdit:focus, QSpinBox:focus {
                border: 2px solid #3b82f6;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1e3a8a, stop:1 #1e293b);
            }
            
            QLineEdit:hover, QSpinBox:hover {
                border: 2px solid #475569;
            }
            
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: none;
                border-radius: 8px;
                padding: 10px 20px;
                font-weight: 700;
                font-size: 14px;
                min-height: 36px;
            }
            
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2563eb, stop:1 #1d4ed8);
            }
            
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #1d4ed8, stop:1 #1e40af);
            }
            
            QPushButton#CancelButton {
                background: transparent;
                color: #cbd5e1;
                border: 2px solid #475569;
            }
            
            QPushButton#CancelButton:hover {
                border-color: #64748b;
                color: #f1f5f9;
                background: rgba(71, 85, 105, 0.1);
            }
            
            QPushButton#TestButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #10b981, stop:1 #059669);
            }
            
            QPushButton#TestButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #059669, stop:1 #047857);
            }
            
            QFrame#ContentFrame {
                background: rgba(30, 41, 59, 0.5);
                border: 1px solid #334155;
                border-radius: 10px;
                padding: 20px;
            }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("Socket Server Settings")
        title_label.setObjectName("TitleLabel")
        layout.addWidget(title_label)
        
        # Description
        desc_label = QLabel("Configure connection settings for the PACS Socket server")
        desc_label.setObjectName("DescLabel")
        layout.addWidget(desc_label)
        
        # Content frame
        content_frame = QFrame()
        content_frame.setObjectName("ContentFrame")
        content_layout = QVBoxLayout(content_frame)
        content_layout.setSpacing(16)
        
        # Host field
        host_label = QLabel("Server Host:")
        self.host_input = QLineEdit()
        self.host_input.setPlaceholderText("e.g., localhost or 192.168.1.100")
        content_layout.addWidget(host_label)
        content_layout.addWidget(self.host_input)
        
        # Port field
        port_label = QLabel("Server Port:")
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(50052)
        content_layout.addWidget(port_label)
        content_layout.addWidget(self.port_input)
        
        # Timeout field
        timeout_label = QLabel("Connection Timeout (seconds):")
        self.timeout_input = QSpinBox()
        self.timeout_input.setRange(1, 300)
        self.timeout_input.setValue(30)
        content_layout.addWidget(timeout_label)
        content_layout.addWidget(self.timeout_input)
        
        layout.addWidget(content_frame)
        
        # Buttons
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        self.test_button = QPushButton("Test Connection")
        self.test_button.setObjectName("TestButton")
        self.test_button.setIcon(qta.icon('fa5s.plug', color='white'))
        self.test_button.clicked.connect(self.test_connection)
        
        self.save_button = QPushButton("Save")
        self.save_button.setIcon(qta.icon('fa5s.save', color='white'))
        self.save_button.clicked.connect(self.save_settings)
        
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("CancelButton")
        self.cancel_button.setIcon(qta.icon('fa5s.times', color='#cbd5e1'))
        self.cancel_button.clicked.connect(self.reject)
        
        buttons_layout.addWidget(self.test_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.cancel_button)
        buttons_layout.addWidget(self.save_button)
        
        layout.addLayout(buttons_layout)
    
    def load_settings(self):
        """Load current settings"""
        self.host_input.setText(self.config.get_socket_host())
        self.port_input.setValue(self.config.get_socket_port())
        self.timeout_input.setValue(self.config.get_connection_timeout())
    
    def save_settings(self):
        """Save settings"""
        host = self.host_input.text().strip()
        port = self.port_input.value()
        timeout = self.timeout_input.value()
        
        if not host:
            QMessageBox.warning(self, "Invalid Input", "Please enter a server host.")
            return
        
        # Update config
        self.config.set("socket_host", host)
        self.config.set("socket_port", port)
        self.config.set("connection_timeout", timeout)
        self.config.save_config()
        
        # QMessageBox.information(
        #     self, 
        #     "Success", 
        #     f"Server settings saved successfully.\n\nHost: {host}\nPort: {port}\nTimeout: {timeout}s"
        # )
        # self.accept()
    
    def test_connection(self):
        """Test connection to server"""
        from PacsClient.zeta_download_manager.network.socket_client import SocketDicomClient
        
        host = self.host_input.text().strip()
        port = self.port_input.value()
        timeout = self.timeout_input.value()
        
        if not host:
            QMessageBox.warning(self, "Invalid Input", "Please enter a server host.")
            return
        
        # Disable button during test
        self.test_button.setEnabled(False)
        self.test_button.setText("Testing...")
        
        # Test connection
        try:
            client = SocketDicomClient(host=host, port=port, timeout=timeout)
            if client.connect():
                client.disconnect()
                QMessageBox.information(
                    self, 
                    "Connection Successful", 
                    f"Successfully connected to server!\n\nHost: {host}\nPort: {port}"
                )
            else:
                QMessageBox.critical(
                    self, 
                    "Connection Failed", 
                    f"Could not connect to server.\n\nHost: {host}\nPort: {port}\n\nPlease check your settings and try again."
                )
        except Exception as e:
            QMessageBox.critical(
                self, 
                "Connection Error", 
                f"Error connecting to server:\n\n{str(e)}"
            )
        finally:
            self.test_button.setEnabled(True)
            self.test_button.setText("Test Connection")

