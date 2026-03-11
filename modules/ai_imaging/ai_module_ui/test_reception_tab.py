"""
Test script for Reception Data Tab

Run this to test the ReceptionDataTab standalone.
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow
from service_tab import ReceptionDataTab


def main():
    """Test the Reception Data Tab."""
    app = QApplication(sys.argv)
    
    # Create main window
    window = QMainWindow()
    window.setWindowTitle("Test - Reception Data Tab")
    window.setGeometry(100, 100, 1000, 700)
    
    # Create and set the tab as central widget
    reception_tab = ReceptionDataTab()
    window.setCentralWidget(reception_tab)
    
    # Show window
    window.show()
    
    print("Reception Data Tab loaded successfully!")
    print("Try entering Reception ID: 10321")
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

