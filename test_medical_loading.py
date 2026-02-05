#!/usr/bin/env python3
"""
Test script to demonstrate the medical loading overlay functionality
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton
from PySide6.QtCore import QTimer
from PacsClient.pacs.patient_tab.ui.widgets.medical_loading_overlay import MedicalLoadingOverlay


class TestMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Medical Loading Overlay Test")
        self.setGeometry(100, 100, 800, 600)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create layout
        layout = QVBoxLayout(central_widget)
        
        # Add a button to trigger loading
        self.load_button = QPushButton("Simulate Loading")
        self.load_button.clicked.connect(self.simulate_loading)
        layout.addWidget(self.load_button)
        
        # Add a button to show/hide loading
        self.toggle_button = QPushButton("Toggle Loading Screen")
        self.toggle_button.clicked.connect(self.toggle_loading)
        layout.addWidget(self.toggle_button)
        
        # Create the medical loading overlay
        self.loading_overlay = MedicalLoadingOverlay(self)
        
    def simulate_loading(self):
        """Simulate a loading process"""
        self.loading_overlay.show_loading()
        
        # Simulate some work with a timer
        QTimer.singleShot(3000, self.loading_overlay.hide_loading)
        
    def toggle_loading(self):
        """Toggle the loading screen"""
        if self.loading_overlay.isVisible():
            self.loading_overlay.hide_loading()
        else:
            self.loading_overlay.show_loading()


def main():
    app = QApplication(sys.argv)
    
    window = TestMainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()