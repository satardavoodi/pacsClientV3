"""
Curved MPR Usage Example
Shows how to integrate Curved MPR functionality with MPR toolbar
"""
import logging
import sys
from typing import Optional

import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QMessageBox
)
from PySide6.QtCore import Qt

from .mpr_toolbar import MPRToolbar
from .curved_mpr_widget import CurvedMPRWidget, CurvedMPRDialog
from .curved_mpr import CurvedMPRGenerator

logger = logging.getLogger(__name__)


class CurvedMPRExample(QMainWindow):
    """
    Example application showing Curved MPR integration
    
    Features:
    - MPR toolbar with Curved MPR button
    - Interactive centerline definition
    - Curved MPR generation
    - Result visualization
    """
    
    def __init__(self):
        super().__init__()
        
        self.setWindowTitle("Curved MPR Example - PACS Client")
        self.setMinimumSize(1200, 800)
        
        # Load sample data
        self.image_data = self._load_sample_data()
        
        # Create UI
        self._create_ui()
        
        logger.info("Created Curved MPR example application")
    
    def _load_sample_data(self) -> vtk.vtkImageData:
        """
        Load sample 3D image data
        
        In production, this would load actual DICOM data
        For this example, we create synthetic data
        """
        # Create sample volume (sphere)
        sphere = vtk.vtkImageEllipsoidSource()
        sphere.SetWholeExtent(0, 127, 0, 127, 0, 127)
        sphere.SetCenter(64, 64, 64)
        sphere.SetRadius(40, 40, 40)
        sphere.SetInValue(200)
        sphere.SetOutValue(0)
        sphere.Update()
        
        image_data = sphere.GetOutput()
        image_data.SetSpacing(1.0, 1.0, 1.0)
        
        logger.info("Loaded sample image data")
        return image_data
    
    def _create_ui(self):
        """Create user interface"""
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        
        # Add MPR toolbar
        self.toolbar = MPRToolbar(self)
        self.addToolBar(self.toolbar)
        
        # Connect toolbar signals
        self.toolbar.curved_mpr_requested.connect(self._on_curved_mpr_requested)
        self.toolbar.action_triggered.connect(self._on_toolbar_action)
        
        # Create splitter for main content
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)
        
        # Left: 3D view (for point selection)
        self.vtk_widget = self._create_vtk_widget()
        splitter.addWidget(self.vtk_widget)
        
        # Right: Curved MPR controls (initially hidden)
        self.curved_mpr_widget = CurvedMPRWidget(self.image_data)
        self.curved_mpr_widget.curved_mpr_generated.connect(self._on_curved_mpr_generated)
        self.curved_mpr_widget.centerline_changed.connect(self._on_centerline_changed)
        self.curved_mpr_widget.hide()  # Hidden until tool is activated
        splitter.addWidget(self.curved_mpr_widget)
        
        # Set splitter sizes
        splitter.setSizes([800, 400])
        
        # Status bar
        self.statusBar().showMessage("Ready - Click 'MPR Tools > Curved MPR' to start")
    
    def _create_vtk_widget(self) -> QWidget:
        """
        Create VTK rendering widget
        
        In production, use QVTKRenderWindowInteractor
        This is a placeholder
        """
        widget = QWidget()
        widget.setMinimumSize(400, 400)
        widget.setStyleSheet("background-color: black;")
        
        # TODO: Implement actual VTK rendering with interaction
        # - Volume rendering of image_data
        # - Click to add centerline points
        # - Display centerline path
        
        return widget
    
    def _on_curved_mpr_requested(self):
        """Handle Curved MPR tool activation"""
        logger.info("Curved MPR tool activated")
        
        # Show curved MPR widget
        self.curved_mpr_widget.show()
        
        # Show instruction message
        QMessageBox.information(
            self,
            "Curved MPR Tool",
            "Curved MPR tool activated!\n\n"
            "Instructions:\n"
            "1. Click 'Add Point' button\n"
            "2. Click on the 3D view to define centerline points\n"
            "3. Adjust parameters on the right panel\n"
            "4. Click 'Generate Curved MPR'\n\n"
            "The curved MPR will straighten the structure along your defined path."
        )
        
        self.statusBar().showMessage("Curved MPR tool active - Define centerline points")
    
    def _on_toolbar_action(self, action: str, value):
        """Handle toolbar actions"""
        logger.info(f"Toolbar action: {action} = {value}")
        
        if action == "plane_changed":
            self.statusBar().showMessage(f"Switched to {value} plane")
        elif action == "mip":
            self.statusBar().showMessage("Maximum Intensity Projection (coming soon)")
        elif action == "minip":
            self.statusBar().showMessage("Minimum Intensity Projection (coming soon)")
        elif action == "volume_rendering":
            self.statusBar().showMessage("Volume Rendering (coming soon)")
    
    def _on_centerline_changed(self, points: list):
        """Handle centerline point changes"""
        logger.info(f"Centerline updated: {len(points)} points")
        
        # TODO: Update visualization
        # - Draw spheres at points
        # - Draw lines connecting points
        # - Update 3D view
        
        self.statusBar().showMessage(f"Centerline: {len(points)} points")
    
    def _on_curved_mpr_generated(self, curved_mpr: vtk.vtkImageData):
        """Handle curved MPR generation"""
        logger.info("Curved MPR generated")
        
        if curved_mpr is None:
            logger.error("Received null curved MPR")
            return
        
        dims = curved_mpr.GetDimensions()
        logger.info(f"Curved MPR dimensions: {dims}")
        
        # TODO: Display curved MPR
        # - Create new window or panel
        # - Show flattened image
        # - Add measurement tools
        
        self.statusBar().showMessage("Curved MPR generated successfully")
        
        # Show success message
        QMessageBox.information(
            self,
            "Success",
            f"Curved MPR generated!\n\n"
            f"Dimensions: {dims[0]} x {dims[1]} x {dims[2]}\n"
            f"You can now analyze the straightened structure."
        )


class SimpleCurvedMPRExample:
    """
    Simple example showing basic Curved MPR usage
    No GUI - just API demonstration
    """
    
    @staticmethod
    def example_basic_usage():
        """Basic usage example"""
        print("=== Basic Curved MPR Usage ===\n")
        
        # 1. Load image data (placeholder)
        print("1. Loading image data...")
        image_data = vtk.vtkImageData()
        # In reality: load from DICOM, NIfTI, etc.
        
        # 2. Define centerline manually
        print("2. Defining centerline...")
        centerline_points = [
            (100, 100, 50),
            (110, 105, 55),
            (120, 110, 60),
            (130, 120, 65),
            (140, 130, 70),
            (150, 140, 75),
        ]
        
        # 3. Create generator
        print("3. Creating Curved MPR generator...")
        generator = CurvedMPRGenerator(image_data)
        generator.set_centerline(centerline_points)
        
        # 4. Generate curved MPR
        print("4. Generating curved MPR...")
        curved_mpr = generator.generate_curved_mpr(
            slice_width=50.0,
            slice_height=50.0,
            num_slices=100
        )
        
        print(f"✓ Generated curved MPR: {curved_mpr.GetDimensions()}")
        print("\nDone!")
    
    @staticmethod
    def example_with_vmtk():
        """Example using VMTK for automatic centerline extraction"""
        print("=== Curved MPR with VMTK ===\n")
        
        try:
            from vmtk import vmtkscripts
        except ImportError:
            print("⚠ VMTK not installed. Install with: pip install vmtk")
            return
        
        # 1. Load image
        print("1. Loading image data...")
        image_data = vtk.vtkImageData()
        
        # 2. Extract surface
        print("2. Extracting vessel surface...")
        surface_extractor = vmtkscripts.vmtkMarchingCubes()
        surface_extractor.Image = image_data
        surface_extractor.Level = 100.0  # Threshold
        surface_extractor.Execute()
        
        # 3. Compute centerlines
        print("3. Computing centerlines...")
        centerline_computer = vmtkscripts.vmtkCenterlines()
        centerline_computer.Surface = surface_extractor.Surface
        centerline_computer.SeedSelectorName = 'pointlist'
        centerline_computer.SourcePoints = [(100, 100, 50)]
        centerline_computer.TargetPoints = [(150, 150, 80)]
        centerline_computer.Execute()
        
        # 4. Extract points
        print("4. Extracting centerline points...")
        centerlines = centerline_computer.Centerlines
        points = []
        radii = []
        
        for i in range(centerlines.GetNumberOfPoints()):
            point = centerlines.GetPoint(i)
            points.append(point)
            
            radius_array = centerlines.GetPointData().GetArray('MaximumInscribedSphereRadius')
            if radius_array:
                radius = radius_array.GetValue(i)
                radii.append(radius)
        
        print(f"✓ Extracted {len(points)} centerline points")
        print(f"✓ Average radius: {sum(radii)/len(radii):.2f}mm")
        
        # 5. Generate curved MPR
        print("5. Generating curved MPR...")
        generator = CurvedMPRGenerator(image_data)
        generator.set_centerline(points)
        
        # Use automatic width based on vessel radius
        max_radius = max(radii)
        curved_mpr = generator.generate_curved_mpr(
            slice_width=4.0 * max_radius,
            slice_height=4.0 * max_radius,
            num_slices=len(points)
        )
        
        print(f"✓ Generated curved MPR: {curved_mpr.GetDimensions()}")
        print("\nDone!")
    
    @staticmethod
    def example_interactive():
        """Example of interactive curved MPR"""
        print("=== Interactive Curved MPR ===\n")
        
        # This requires a GUI - show conceptual code
        print("Conceptual code for interactive usage:")
        print("""
        from .curved_mpr import InteractiveCurvedMPR
        
        # Setup
        renderer = vtk.vtkRenderer()
        interactive_mpr = InteractiveCurvedMPR(image_data, renderer)
        
        # User clicks to add points
        def on_click(x, y, z):
            interactive_mpr.add_path_point((x, y, z))
        
        # Generate when ready
        curved_mpr = interactive_mpr.generate_curved_mpr()
        """)


def main():
    """Run example application"""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run simple examples
    print("\n" + "="*60)
    SimpleCurvedMPRExample.example_basic_usage()
    print("\n" + "="*60)
    
    # Run GUI example
    app = QApplication(sys.argv)
    
    window = CurvedMPRExample()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

