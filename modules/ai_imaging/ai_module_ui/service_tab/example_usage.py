"""
Example usage of Reception Data Tab

This file demonstrates how to use the ReceptionDataTab in your application.
"""

import sys
from PySide6.QtWidgets import QApplication, QMainWindow, QTabWidget, QVBoxLayout, QWidget
from reception_data_tab import ReceptionDataTab


class ExampleMainWindow(QMainWindow):
    """Example main window showing how to integrate ReceptionDataTab."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Reception Data Tab - Example")
        self.setGeometry(100, 100, 1200, 800)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create layout
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Create tab widget
        self.tab_widget = QTabWidget()
        
        # Add Reception Data Tab
        self.reception_tab = ReceptionDataTab()
        self.tab_widget.addTab(self.reception_tab, "Reception Data")
        
        # You can also connect to signals if needed
        self.reception_tab.service.data_received.connect(self.on_data_received)
        self.reception_tab.service.error_occurred.connect(self.on_error_occurred)
        
        # Add tab widget to layout
        layout.addWidget(self.tab_widget)
        
        # Apply dark theme
        self.apply_dark_theme()
    
    def on_data_received(self, data: dict):
        """
        Handle data received event.
        
        Args:
            data: The received patient data
        """
        print("Data received!")
        print(f"Success: {data.get('success')}")
        if data.get('data'):
            patient_info = data['data'][0]
            print(f"Patient: {patient_info.get('patient', {}).get('Name', 'N/A')}")
            print(f"Reception ID: {patient_info.get('receptionId', 'N/A')}")
    
    def on_error_occurred(self, error_message: str):
        """
        Handle error event.
        
        Args:
            error_message: The error message
        """
        print(f"Error occurred: {error_message}")
    
    def apply_dark_theme(self):
        """Apply a dark theme to the entire application."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1e1e1e;
            }
            QTabWidget::pane {
                border: 1px solid #444;
                background-color: #1e1e1e;
            }
            QTabBar::tab {
                background-color: #2b2b2b;
                color: white;
                padding: 10px 20px;
                border: 1px solid #444;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background-color: #1e1e1e;
                border-bottom: 2px solid #2196f3;
            }
            QTabBar::tab:hover {
                background-color: #353535;
            }
        """)


def main():
    """Main function to run the example."""
    app = QApplication(sys.argv)
    
    # Set application-wide font
    from PySide6.QtGui import QFont
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Create and show main window
    window = ExampleMainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

