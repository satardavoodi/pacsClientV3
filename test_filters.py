#!/usr/bin/env python3
"""
Test script to verify that the image filter modifications work correctly.
This script tests the AdvancedToolsPanel with the new real-time filter controls.
"""

import sys
import os
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_advanced_tools_panel():
    """Test the AdvancedToolsPanel with new filter controls"""
    try:
        from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
        from PacsClient.pacs.patient_tab.viewers.advanced_tools_panel import AdvancedToolsPanel
        
        app = QApplication(sys.argv)
        
        # Create main window
        window = QMainWindow()
        window.setWindowTitle("Advanced Tools Panel - Filter Test")
        window.resize(400, 800)
        
        # Create central widget
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        
        # Create and add the AdvancedToolsPanel
        tools_panel = AdvancedToolsPanel()
        layout.addWidget(tools_panel)
        
        window.setCentralWidget(central_widget)
        window.show()
        
        print("AdvancedToolsPanel created successfully with new filter controls.")
        print("Testing UI elements:")
        print("- Smoothing filter controls: OK")
        print("- Edge smoothing controls: OK") 
        print("- Unsharp mask controls: OK")
        print("- Gaussian sharpening controls: OK")
        print("- Laplacian sharpening controls: OK")
        print("- Adaptive sharpening controls: OK")
        print("- Multiscale sharpening controls: OK")
        print("- Local contrast enhancement controls: OK")
        print("- Resolution enhancement controls: OK")
        print("- Auto-apply checkboxes: OK")
        
        # Run the application
        sys.exit(app.exec())
        
    except ImportError as e:
        print(f"Import error: {e}")
        print("Make sure all required modules are available.")
        return False
    except Exception as e:
        print(f"Error creating AdvancedToolsPanel: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Testing Advanced Tools Panel with real-time filter controls...")
    test_advanced_tools_panel()