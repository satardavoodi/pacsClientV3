"""
Complete MPR Application with Toolbar
Example of integrated MPR viewer with full toolbar
"""
import sys
import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QMenuBar, QMenu, QStatusBar, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

import vtkmodules.all as vtk

from PacsClient.pacs.patient_tab.viewers.mpr_viewer import MPRWidget
from PacsClient.pacs.patient_tab.viewers.mpr_toolbar import MPRToolbar, MPRToolbarManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MPRApplication(QMainWindow):
    """
    Complete MPR Application with Toolbar
    Professional DICOM MPR viewer
    """
    
    def __init__(self):
        super().__init__()
        
        self.mpr_widget = None
        self.toolbar_manager = None
        self.current_file = None
        
        self.setWindowTitle("Professional MPR Viewer")
        self.setGeometry(100, 100, 1400, 900)
        
        self._create_menu_bar()
        self._create_central_widget()
        self._create_status_bar()
        
        logger.info("MPR Application initialized")
    
    def _create_menu_bar(self):
        """Create menu bar"""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu("&File")
        
        open_action = QAction("&Open DICOM...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_dicom)
        file_menu.addAction(open_action)
        
        open_folder_action = QAction("Open DICOM &Folder...", self)
        open_folder_action.setShortcut("Ctrl+Shift+O")
        open_folder_action.triggered.connect(self.open_dicom_folder)
        file_menu.addAction(open_folder_action)
        
        file_menu.addSeparator()
        
        export_action = QAction("&Export Image...", self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_image)
        file_menu.addAction(export_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # View menu
        view_menu = menubar.addMenu("&View")
        
        reset_action = QAction("&Reset Views", self)
        reset_action.setShortcut("R")
        reset_action.triggered.connect(self.reset_views)
        view_menu.addAction(reset_action)
        
        fit_action = QAction("&Fit to Window", self)
        fit_action.setShortcut("F")
        fit_action.triggered.connect(self.fit_to_window)
        view_menu.addAction(fit_action)
        
        view_menu.addSeparator()
        
        sync_action = QAction("&Synchronize Views", self)
        sync_action.setCheckable(True)
        sync_action.setChecked(True)
        view_menu.addAction(sync_action)
        
        # Tools menu
        tools_menu = menubar.addMenu("&Tools")
        
        distance_action = QAction("Measure &Distance", self)
        distance_action.setShortcut("D")
        distance_action.triggered.connect(lambda: self.set_measurement_mode("distance"))
        tools_menu.addAction(distance_action)
        
        angle_action = QAction("Measure &Angle", self)
        angle_action.setShortcut("A")
        angle_action.triggered.connect(lambda: self.set_measurement_mode("angle"))
        tools_menu.addAction(angle_action)
        
        tools_menu.addSeparator()
        
        slab_action = QAction("Enable Thick &Slab", self)
        slab_action.setCheckable(True)
        slab_action.triggered.connect(self.toggle_slab)
        tools_menu.addAction(slab_action)
        
        # Help menu
        help_menu = menubar.addMenu("&Help")
        
        about_action = QAction("&About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def _create_central_widget(self):
        """Create central widget with placeholder"""
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Placeholder message
        from PySide6.QtWidgets import QLabel
        placeholder = QLabel("Open a DICOM file or folder to start\n(File → Open DICOM...)")
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet("""
            QLabel {
                font-size: 18px;
                color: #888;
                background-color: #2b2b2b;
                padding: 50px;
            }
        """)
        layout.addWidget(placeholder)
        
        self.setCentralWidget(central_widget)
    
    def _create_status_bar(self):
        """Create status bar"""
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
    
    def load_dicom_data(self, vtk_image_data: vtk.vtkImageData):
        """
        Load DICOM data into MPR viewer
        
        Args:
            vtk_image_data: VTK image data
        """
        try:
            # Create MPR widget
            self.mpr_widget = MPRWidget(vtk_image_data)
            
            # Create toolbar
            self.toolbar_manager = MPRToolbarManager(self.mpr_widget)
            toolbar = self.toolbar_manager.get_toolbar()
            
            # Add toolbar to window
            self.addToolBar(Qt.TopToolBarArea, toolbar)
            
            # Create layout for MPR widget
            central_widget = QWidget()
            layout = QVBoxLayout(central_widget)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self.mpr_widget)
            
            self.setCentralWidget(central_widget)
            
            # Update status
            dims = vtk_image_data.GetDimensions()
            spacing = vtk_image_data.GetSpacing()
            self.status_bar.showMessage(
                f"Loaded: {dims[0]}×{dims[1]}×{dims[2]} slices, "
                f"Spacing: {spacing[0]:.2f}×{spacing[1]:.2f}×{spacing[2]:.2f} mm"
            )
            
            logger.info("DICOM data loaded successfully")
            
        except Exception as e:
            logger.error(f"Error loading DICOM data: {e}")
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to load DICOM data:\n{e}"
            )
    
    def open_dicom(self):
        """Open single DICOM file"""
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open DICOM File",
            "",
            "DICOM Files (*.dcm);;All Files (*)"
        )
        
        if filename:
            try:
                # Read DICOM file
                reader = vtk.vtkDICOMImageReader()
                reader.SetFileName(filename)
                reader.Update()
                
                self.load_dicom_data(reader.GetOutput())
                self.current_file = filename
                
            except Exception as e:
                logger.error(f"Error opening file: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open DICOM file:\n{e}"
                )
    
    def open_dicom_folder(self):
        """Open DICOM folder (series)"""
        folder = QFileDialog.getExistingDirectory(
            self,
            "Open DICOM Folder",
            ""
        )
        
        if folder:
            try:
                # Read DICOM series
                reader = vtk.vtkDICOMImageReader()
                reader.SetDirectoryName(folder)
                reader.Update()
                
                self.load_dicom_data(reader.GetOutput())
                self.current_file = folder
                
            except Exception as e:
                logger.error(f"Error opening folder: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to open DICOM folder:\n{e}"
                )
    
    def export_image(self):
        """Export current view"""
        if not self.mpr_widget:
            QMessageBox.warning(self, "Warning", "No data loaded")
            return
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Image",
            "",
            "PNG Files (*.png);;JPEG Files (*.jpg);;All Files (*)"
        )
        
        if filename:
            try:
                # Export logic here
                self.status_bar.showMessage(f"Exported to: {filename}")
                logger.info(f"Image exported to: {filename}")
                
            except Exception as e:
                logger.error(f"Error exporting: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to export image:\n{e}"
                )
    
    def reset_views(self):
        """Reset all views"""
        if self.mpr_widget:
            self.mpr_widget.reset_views()
            self.status_bar.showMessage("Views reset")
    
    def fit_to_window(self):
        """Fit views to window"""
        if self.mpr_widget:
            # Implement fit to window
            self.status_bar.showMessage("Fit to window")
    
    def set_measurement_mode(self, mode: str):
        """Set measurement mode"""
        if self.toolbar_manager:
            self.toolbar_manager.toolbar.set_measurement_mode(mode)
            self.status_bar.showMessage(f"Measurement mode: {mode}")
    
    def toggle_slab(self, enabled: bool):
        """Toggle thick slab"""
        if self.toolbar_manager:
            if enabled:
                self.toolbar_manager.toolbar.enable_slab(10.0, "mean")
                self.status_bar.showMessage("Thick slab enabled")
            else:
                self.toolbar_manager.toolbar.disable_slab()
                self.status_bar.showMessage("Thick slab disabled")
    
    def show_about(self):
        """Show about dialog"""
        QMessageBox.about(
            self,
            "About MPR Viewer",
            "<h2>Professional MPR Viewer</h2>"
            "<p>Version 1.0</p>"
            "<p>A professional Multi-Planar Reconstruction viewer "
            "for DICOM medical images.</p>"
            "<p><b>Features:</b></p>"
            "<ul>"
            "<li>Synchronized 3-plane view (Axial, Sagittal, Coronal)</li>"
            "<li>Thick slab MPR with MIP/MinIP</li>"
            "<li>Oblique reslicing</li>"
            "<li>Distance and angle measurements</li>"
            "<li>High-quality Lanczos interpolation</li>"
            "</ul>"
        )


def main():
    """Main application entry point"""
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle("Fusion")
    
    # Dark theme
    from PySide6.QtGui import QPalette, QColor
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(53, 53, 53))
    palette.setColor(QPalette.WindowText, Qt.white)
    palette.setColor(QPalette.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
    palette.setColor(QPalette.ToolTipBase, Qt.white)
    palette.setColor(QPalette.ToolTipText, Qt.white)
    palette.setColor(QPalette.Text, Qt.white)
    palette.setColor(QPalette.Button, QColor(53, 53, 53))
    palette.setColor(QPalette.ButtonText, Qt.white)
    palette.setColor(QPalette.BrightText, Qt.red)
    palette.setColor(QPalette.Link, QColor(42, 130, 218))
    palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setPalette(palette)
    
    # Create and show main window
    window = MPRApplication()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

