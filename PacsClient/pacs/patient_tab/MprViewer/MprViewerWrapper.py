"""
MPR Viewer Wrapper - PySide6 compatible wrapper for MprViewer
This wrapper integrates MprViewer with the existing system by:
1. Converting vtk_image_data to MHD format (or using it directly)
2. Providing the same interface as StandardMPRViewer
3. Using PySide6 instead of PyQt5
"""
import logging
import os
import tempfile
import vtkmodules.all as vtk
from vtkmodules.util import numpy_support
import numpy as np
import SimpleITK as sitk
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QSlider, 
    QPushButton, QSpacerItem, QComboBox, QLabel, QFrame,
    QToolButton, QButtonGroup, QSizePolicy, QGridLayout
)
from PySide6.QtCore import Qt, QThread, QObject, Signal as PySideSignal, QSize
from PySide6.QtGui import QIcon, QFont, QCursor

# Window/Level Presets for CT
CT_PRESETS = {
    "Default": {"window": 400, "level": 40},
    "Lung": {"window": 1500, "level": -600},
    "Bone": {"window": 2000, "level": 500},
    "Brain": {"window": 80, "level": 40},
    "Soft Tissue": {"window": 400, "level": 40},
    "Liver": {"window": 150, "level": 30},
    "Mediastinum": {"window": 350, "level": 50},
    "Abdomen": {"window": 400, "level": 50},
    "Spine": {"window": 250, "level": 50},
}

from vtkmodules.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

# Initialize logger first
logger = logging.getLogger(__name__)

# Import MprViewer components
# Note: These use relative imports within the MprViewer package
import sys

# Add MprViewer directory to path for imports
# This is necessary because MprViewer modules use relative imports
mpr_viewer_dir = os.path.dirname(os.path.abspath(__file__))
if mpr_viewer_dir not in sys.path:
    sys.path.insert(0, mpr_viewer_dir)

try:
    from VtkBase import VtkBase
    from OrthoViewer import OrthoViewer
    from SegmentationViewer import SegmentationViewer
    from VolumeViewer import VolumeViewer
    from ViewersConnection import ViewersConnection
    from CommandSliceSelect import CommandSliceSelect
except ImportError as e:
    logging.error(f"Failed to import MprViewer components: {e}", exc_info=True)
    raise

logger = logging.getLogger(__name__)

# Slice orientation constants
SLICE_ORIENTATION_YZ = vtk.vtkResliceImageViewer.SLICE_ORIENTATION_YZ
SLICE_ORIENTATION_XZ = vtk.vtkResliceImageViewer.SLICE_ORIENTATION_XZ
SLICE_ORIENTATION_XY = vtk.vtkResliceImageViewer.SLICE_ORIENTATION_XY


class Worker(QObject):
    """Worker object for playing slices (runs in QThread)"""
    finished = PySideSignal()
    progress = PySideSignal(int)
    
    def __init__(self, slider: QSlider):
        super().__init__()
        self.slider = slider
        self._isRunning = True

    def play(self):
        """Play the worker"""
        import time
        if not self._isRunning:
            self._isRunning = True

        i = self.slider.value()
        slider_max = self.slider.maximum()
        while i <= slider_max:
            if self._isRunning:
                self.progress.emit(i)
                time.sleep(0.01)
            else:
                break
            
            i += 1

        self.slider.setValue(i)
        self.finished.emit()
    
    def pause(self):
        """Pause the worker"""
        self._isRunning = False


class QtViewer(QWidget):
    """Base Qt viewer widget (PySide6 version)"""
    
    def __init__(self):
        super().__init__()
        self.viewer = None
        
    def closeEvent(self, event):
        """Handle close event"""
        if self.viewer:
            self.viewer.Finalize()
        super().closeEvent(event)

    def _init_UI(self):
        """Initialize the UI"""
        self.mainLayout = QVBoxLayout()
        self.mainLayout.setContentsMargins(0, 0, 0, 0)
        self.mainLayout.setSpacing(0)
        
        self.topLayout = QHBoxLayout()
        self.topLayout.setContentsMargins(0, 0, 0, 0)
        self.topLayout.setSpacing(0)
        
        # Add viewer widget if it exists
        if self.viewer:
            # viewer is a VtkViewer which is a QVTKRenderWindowInteractor
            self.topLayout.addWidget(self.viewer)
        else:
            # Create placeholder if viewer not yet created
            from PySide6.QtWidgets import QLabel
            placeholder = QLabel("Viewer not initialized")
            placeholder.setStyleSheet("background-color: #2b2b2b; color: white;")
            self.topLayout.addWidget(placeholder)
        
        self.mainLayout.addLayout(self.topLayout)
        self.setLayout(self.mainLayout)
        
    def connect_signals(self):
        """Connect signals and slots"""
        pass

    def get_viewer(self):
        """Get the viewer"""
        return self.viewer
    
    def connect_on_data(self, path):
        """Connect to data"""
        if self.viewer:
            self.viewer.connect_on_data(path)
    
    def render(self):
        """Render the viewer"""
        if self.viewer:
            self.viewer.render()


class QtOrthoViewer(QtViewer):
    """Orthogonal viewer widget (PySide6 version)"""
    
    def __init__(self, vtkBaseClass, orientation, label: str = "Orthogonal Viewer"):
        super().__init__()
        
        self.orientation = orientation
        self.status = False
        self.label = label
        
        # Render Viewer - create first
        self.viewer = OrthoViewer(vtkBaseClass, self.orientation, self.label)
        
        # Initialize the UI - after viewer is created
        self._init_UI()
        
        # Thread
        self.thread = None
        self.worker = None
        
        # Slider
        self.slider = QSlider(Qt.Vertical)
        self.slider.setSingleStep(1)
        self.slider.setValue(0)
        self.slider.setEnabled(False)
        if hasattr(vtkBaseClass, 'commandSliceSelect'):
            vtkBaseClass.commandSliceSelect.sliders[self.orientation] = self.slider
        
        # Buttons
        self.buttonsLayout = QHBoxLayout()
        
        self.prevBtn = QPushButton()
        # Note: Icon paths may need to be adjusted
        # self.prevBtn.setIcon(QIcon("./assets/decrease.svg"))
        self.prevBtn.setText("◄")
        self.prevBtn.setStyleSheet("font-size:15px; border-radius: 6px;border: 1px solid rgba(27, 31, 35, 0.15);padding: 5px 15px; background: black")
        self.prevBtn.setDisabled(True)
        
        self.playBtn = QPushButton()
        # self.playBtn.setIcon(QIcon("./assets/play.ico"))
        self.playBtn.setText("▶")
        self.playBtn.setStyleSheet("font-size:15px; border-radius: 6px;border: 1px solid rgba(27, 31, 35, 0.15);padding: 5px 15px;")
        self.playBtn.setDisabled(True)
        
        self.nextBtn = QPushButton()
        # self.nextBtn.setIcon(QIcon("./assets/increase.svg"))
        self.nextBtn.setText("►")
        self.nextBtn.setStyleSheet("font-size:15px; border-radius: 6px;border: 1px solid rgba(27, 31, 35, 0.15);padding: 5px 15px; background: black")
        self.nextBtn.setDisabled(True)
        
        self.buttonsLayout.addSpacerItem(QSpacerItem(80, 10))
        self.buttonsLayout.addWidget(self.prevBtn, 4)
        self.buttonsLayout.addWidget(self.playBtn, 5)
        self.buttonsLayout.addWidget(self.nextBtn, 4)
        self.buttonsLayout.addSpacerItem(QSpacerItem(80, 10))
        
        # Set up the layouts
        self.topLayout.addWidget(self.slider)
        self.mainLayout.addLayout(self.buttonsLayout)
        
        # Connect signals and slots
        self.connect_signals()
    
    def connect_signals(self):
        """Connect signals and slots"""
        super().connect_signals()  # Call parent method
        self.slider.valueChanged.connect(self.update_slice)
        self.prevBtn.clicked.connect(lambda: self.next_prev_btn(self.slider.value() - 10))
        self.playBtn.clicked.connect(self.play_pause_btn)
        self.nextBtn.clicked.connect(lambda: self.next_prev_btn(self.slider.value() + 10))
    
    def update_slice(self, slice_index):
        """Update slice"""
        if self.viewer:
            self.viewer.set_slice(slice_index)
    
    def connect_on_data(self, path):
        """Connect on data"""
        super().connect_on_data(path)
        
        # Settings of the button
        self.prevBtn.setEnabled(True)
        self.playBtn.setEnabled(True)
        self.nextBtn.setEnabled(True)
        
        # Settings of the slider
        self.slider.setEnabled(True)
        if self.viewer:
            self.slider.setMinimum(self.viewer.min_slice)
            self.slider.setMaximum(self.viewer.max_slice)
            self.slider.setValue((self.slider.maximum() + self.slider.minimum()) // 2)
    
    def next_prev_btn(self, slice_index):
        """Next/Previous button function"""
        if slice_index < self.slider.minimum():
            slice_index = self.slider.minimum()
        elif slice_index > self.slider.maximum():
            slice_index = self.slider.maximum()
            
        self.slider.setValue(slice_index)
        if self.viewer:
            self.viewer.set_slice(slice_index)
    
    def play_slices(self):
        """Play slices"""
        self.thread = QThread()
        self.worker = Worker(self.slider)
        self.status = True
        
        # Play Button icon
        self.playBtn.setText("⏸")
        
        # Move worker to the thread
        self.worker.moveToThread(self.thread)
        
        # Connect signals and slots
        self.thread.started.connect(self.worker.play)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.progress.connect(self.update_slice)
        
        # Start the thread
        self.thread.start()
        self.slider.setHidden(True)
        self.thread.finished.connect(lambda: self.slider.setHidden(False))
        self.thread.finished.connect(self.pause_slices)
    
    def pause_slices(self):
        """Pause slices"""
        self.playBtn.setText("▶")
        if self.worker:
            self.worker.pause()
        self.status = False
    
    def play_pause_btn(self):
        """Play/Pause button function"""
        if self.status == False:
            self.play_slices()
        else:
            self.pause_slices()


class QtSegmentationViewer(QtViewer):
    """Segmentation viewer widget (PySide6 version)"""
    
    def __init__(self, vtkBaseClass, label: str = "Segmentation Viewer"):
        super().__init__()
        
        self.label = label
        
        # Render Viewer
        self.viewer = SegmentationViewer(vtkBaseClass, self.label)
        
        # Initialize the UI
        self._init_UI()
        
        # Connect signals and slots
        self.connect_signals()
    
    def _init_UI(self):
        """Initialize the UI"""
        super()._init_UI()
        self.mainLayout.addItem(QSpacerItem(10, 20))


class QtVolumeViewer(QtViewer):
    """3D Volume Rendering viewer widget (PySide6 version)"""
    
    def __init__(self, vtkBaseClass, label: str = "3D Volume"):
        super().__init__()
        
        self.label = label
        
        # Render Viewer - using VolumeViewer for 3D rendering
        self.viewer = VolumeViewer(vtkBaseClass, self.label)
        
        # Initialize the UI
        self._init_UI()
        
        # Connect signals and slots
        self.connect_signals()
    
    def _init_UI(self):
        """Initialize the UI with preset controls"""
        super()._init_UI()
        
        # Add preset selector
        self.presetLayout = QHBoxLayout()
        self.presetLayout.setContentsMargins(5, 5, 5, 5)
        
        self.presetLabel = QLabel("Preset:")
        self.presetLabel.setStyleSheet("color: white; font-size: 10px;")
        self.presetLayout.addWidget(self.presetLabel)
        
        self.presetCombo = QComboBox()
        self.presetCombo.addItems(["ct_chest_color", "ct_bone", "ct_soft", "ct_lung", "ct_vessel", "mip"])
        self.presetCombo.setStyleSheet("""
            QComboBox {
                background-color: #3c3c3c;
                color: white;
                border: 1px solid #555;
                padding: 3px;
                font-size: 10px;
            }
        """)
        self.presetCombo.currentTextChanged.connect(self._on_preset_changed)
        self.presetLayout.addWidget(self.presetCombo)
        
        self.presetLayout.addStretch()
        self.mainLayout.addLayout(self.presetLayout)
    
    def _on_preset_changed(self, preset_name):
        """Handle preset change"""
        if self.viewer:
            self.viewer.set_preset(preset_name)


def convert_dicom_series_to_mhd(dicom_directory, output_path=None):
    """
    Convert DICOM series to MHD format using SimpleITK
    This preserves the direction matrix correctly!
    
    Args:
        dicom_directory: Path to directory containing DICOM files
        output_path: Optional output path for MHD file
        
    Returns:
        Path to the created MHD file
    """
    if output_path is None:
        temp_dir = tempfile.gettempdir()
        import time
        timestamp = int(time.time())
        output_path = os.path.join(temp_dir, f"temp_dicom_{timestamp}.mhd")
    
    try:
        logger.info(f"Converting DICOM series from: {dicom_directory}")
        
        # Read DICOM series
        reader = sitk.ImageSeriesReader()
        dicom_names = reader.GetGDCMSeriesFileNames(dicom_directory)
        
        if len(dicom_names) == 0:
            raise ValueError(f"No DICOM files found in {dicom_directory}")
        
        logger.info(f"Found {len(dicom_names)} DICOM files")
        
        reader.SetFileNames(dicom_names)
        image = reader.Execute()
        
        # Log image properties
        logger.info(f"Image size: {image.GetSize()}")
        logger.info(f"Image spacing: {image.GetSpacing()}")
        logger.info(f"Image origin: {image.GetOrigin()}")
        logger.info(f"Image direction: {image.GetDirection()}")
        
        # Write to MHD format
        sitk.WriteImage(image, output_path, True)
        
        if not os.path.exists(output_path):
            raise IOError(f"MHD file was not created: {output_path}")
        
        logger.info(f"Successfully converted DICOM to MHD: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error converting DICOM to MHD: {e}", exc_info=True)
        raise


def vtk_image_data_to_mhd(vtk_image_data, output_path=None):
    """
    Convert vtk_image_data to MHD file - handling direction matrix carefully
    (Fallback method if DICOM path is not available)
    
    Args:
        vtk_image_data: VTK image data object
        output_path: Optional output path for MHD file
        
    Returns:
        Path to the created MHD file
    """
    if output_path is None:
        temp_dir = tempfile.gettempdir()
        import time
        timestamp = int(time.time())
        output_path = os.path.join(temp_dir, f"temp_vtk_{timestamp}.mhd")
    
    try:
        dims = vtk_image_data.GetDimensions()
        spacing = vtk_image_data.GetSpacing()
        origin = vtk_image_data.GetOrigin()
        
        # Get direction matrix from field data if available
        direction_matrix = None
        if vtk_image_data.GetFieldData().GetArray('DirectionMatrix'):
            direction_array = vtk_image_data.GetFieldData().GetArray('DirectionMatrix')
            direction_matrix = [direction_array.GetValue(i) for i in range(9)]
            logger.info(f"Found DirectionMatrix: {direction_matrix}")
            
            # Check if direction matrix is valid (determinant != 0)
            import numpy as np
            dir_mat_3x3 = np.array(direction_matrix).reshape(3, 3)
            det = np.linalg.det(dir_mat_3x3)
            logger.info(f"Direction matrix determinant: {det}")
            
            if abs(det) < 0.001:  # Invalid direction matrix
                logger.warning(f"Invalid direction matrix (det={det}), using identity instead")
                direction_matrix = None
        
        if direction_matrix is None:
            logger.info("Using identity direction matrix")
            direction_matrix = [1, 0, 0, 0, 1, 0, 0, 0, 1]
        
        logger.info(f"Converting vtk_image_data to MHD: dims={dims}, spacing={spacing}, origin={origin}")
        logger.info(f"Direction: {direction_matrix}")
        
        # Get scalar data
        scalars = vtk_image_data.GetPointData().GetScalars()
        if scalars is None:
            raise ValueError("No scalar data in vtkImageData")
        
        # Convert to numpy array
        np_array = numpy_support.vtk_to_numpy(scalars)
        
        # Reshape - VTK uses Fortran order (X varies fastest)
        # SimpleITK expects (Z, Y, X) from GetImageFromArray
        np_array = np_array.reshape(dims[2], dims[1], dims[0], order='F')
        
        # Create SimpleITK image
        sitk_image = sitk.GetImageFromArray(np_array)
        sitk_image.SetSpacing(spacing)
        sitk_image.SetOrigin(origin)
        
        # Only set direction if it's valid
        try:
            sitk_image.SetDirection(direction_matrix)
            logger.info("Direction matrix set successfully")
        except Exception as dir_error:
            logger.warning(f"Could not set direction matrix: {dir_error}, using identity")
        
        # Write to MHD
        sitk.WriteImage(sitk_image, output_path, True)
        
        logger.info(f"Successfully converted using SimpleITK: {output_path}")
        return output_path
        
    except Exception as e:
        logger.error(f"Error converting vtk_image_data to MHD: {e}", exc_info=True)
        raise


class MprViewerWrapper(QWidget):
    """
    Wrapper class that integrates MprViewer with the existing system
    Provides the same interface as StandardMPRViewer
    """
    
    def __init__(self, vtk_image_data=None, dicom_directory=None, parent=None, window_width=None, window_center=None):
        """
        Initialize MPR Viewer Wrapper
        
        Args:
            vtk_image_data: VTK image data object (fallback if dicom_directory not provided)
            dicom_directory: Path to DICOM series directory (preferred - preserves orientation!)
            parent: Parent widget (REQUIRED to avoid popup window)
            window_width: Window width for display (optional)
            window_center: Window center for display (optional)
        """
        super().__init__(parent)  # Set parent first to avoid popup
        
        # Set window flags to ensure it's embedded, not a separate window
        self.setWindowFlags(Qt.Widget)
        
        logger.info("=" * 80)
        logger.info("MPR VIEWER WRAPPER INITIALIZATION STARTED")
        logger.info(f"vtk_image_data: {vtk_image_data}")
        logger.info(f"dicom_directory: {dicom_directory}")
        logger.info(f"window_width: {window_width}, window_center: {window_center}")
        logger.info(f"Parent: {parent}")
        logger.info("=" * 80)
        
        self.vtk_image_data = vtk_image_data
        self.dicom_directory = dicom_directory
        self.mhd_path = None
        self.window_width = window_width
        self.window_center = window_center
        
        # Convert to MHD format
        try:
            if dicom_directory and os.path.isdir(dicom_directory):
                # Preferred method: directly from DICOM (preserves orientation!)
                logger.info(f"✅ Using DICOM directory method: {dicom_directory}")
                self.mhd_path = convert_dicom_series_to_mhd(dicom_directory)
                logger.info(f"✅ MHD file created from DICOM: {self.mhd_path}")
            elif vtk_image_data:
                # Fallback: from vtkImageData
                logger.info("⚠️ Using vtkImageData fallback method...")
                self.mhd_path = vtk_image_data_to_mhd(vtk_image_data)
                logger.info(f"✅ MHD file created from vtkImageData: {self.mhd_path}")
            else:
                raise ValueError("Either dicom_directory or vtk_image_data must be provided")
        except Exception as e:
            logger.error(f"Failed to create MHD file: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            error_msg = f"Failed to initialize MPR Viewer:\n{str(e)}"
            QMessageBox.critical(None, "MPR Viewer Error", error_msg)
            raise
        
        # Create VtkBase
        try:
            logger.info("Creating VtkBase...")
            self.vtkBaseClass = VtkBase()
            logger.info("Connecting VtkBase to MHD file...")
            self.vtkBaseClass.connect_on_data(self.mhd_path)
            logger.info("VtkBase connected successfully")
        except Exception as e:
            logger.error(f"Failed to create/connect VtkBase: {e}", exc_info=True)
            raise
        
        # Create viewers
        try:
            logger.info("Creating orthogonal viewers...")
            self.QtSagittalOrthoViewer = QtOrthoViewer(
                self.vtkBaseClass, SLICE_ORIENTATION_YZ, "Sagittal Plane - YZ"
            )
            self.QtCoronalOrthoViewer = QtOrthoViewer(
                self.vtkBaseClass, SLICE_ORIENTATION_XZ, "Coronal Plane - XZ"
            )
            self.QtAxialOrthoViewer = QtOrthoViewer(
                self.vtkBaseClass, SLICE_ORIENTATION_XY, "Axial Plane - XY"
            )
            self.QtVolumeViewer = QtVolumeViewer(
                self.vtkBaseClass, label="3D Volume"
            )
            logger.info("All viewers created successfully")
        except Exception as e:
            logger.error(f"Failed to create viewers: {e}", exc_info=True)
            raise
        
        # Create viewers connection
        try:
            logger.info("Creating viewers connection...")
            self.ViewersConnection = ViewersConnection(self.vtkBaseClass)
            self.ViewersConnection.add_orthogonal_viewer(self.QtSagittalOrthoViewer.get_viewer())
            self.ViewersConnection.add_orthogonal_viewer(self.QtCoronalOrthoViewer.get_viewer())
            self.ViewersConnection.add_orthogonal_viewer(self.QtAxialOrthoViewer.get_viewer())
            self.ViewersConnection.add_segmentation_viewer(self.QtVolumeViewer.get_viewer())
            self.ViewersConnection.connect_on_data()
            logger.info("Viewers connection established")
        except Exception as e:
            logger.error(f"Failed to create viewers connection: {e}", exc_info=True)
            raise
        
        # Enable sliders and buttons by calling connect_on_data for each viewer
        try:
            logger.info("Enabling sliders and buttons...")
            self.QtSagittalOrthoViewer.connect_on_data(self.mhd_path)
            self.QtCoronalOrthoViewer.connect_on_data(self.mhd_path)
            self.QtAxialOrthoViewer.connect_on_data(self.mhd_path)
            self.QtVolumeViewer.connect_on_data(self.mhd_path)
            logger.info("Sliders and buttons enabled")
        except Exception as e:
            logger.error(f"Failed to enable sliders: {e}", exc_info=True)
        
        # Apply window/level if provided
        if self.window_width is not None and self.window_center is not None:
            try:
                logger.info(f"Applying DICOM window/level: W={self.window_width}, C={self.window_center}")
                # Use the new method that converts DICOM HU to internal 0-255 range
                self.vtkBaseClass.set_window_level(self.window_width, self.window_center)
                
                # Re-render all viewers
                self.QtSagittalOrthoViewer.render()
                self.QtCoronalOrthoViewer.render()
                self.QtAxialOrthoViewer.render()
                self.QtSegmentationViewer.render()
                logger.info("Window/level applied successfully")
            except Exception as e:
                logger.error(f"Failed to apply window/level: {e}", exc_info=True)
        
        # Set up the main layout
        try:
            logger.info("Setting up UI layout...")
            self._setup_ui()
            logger.info("UI layout setup complete")
        except Exception as e:
            logger.error(f"Failed to setup UI: {e}", exc_info=True)
            raise
        
        logger.info("MPR Viewer Wrapper created successfully!")
        logger.info("=" * 80)
    
    def _setup_ui(self):
        """Setup the UI layout - Clean 2x2 grid layout"""
        import sys
        print("=" * 80, file=sys.stderr, flush=True)
        print("_setup_ui() CALLED", file=sys.stderr, flush=True)
        
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        print("Main layout created", file=sys.stderr, flush=True)
        
        # Simple dark theme - no internal toolbar, use main toolbar
        self.setStyleSheet("""
            QWidget { background-color: #000000; }
            QComboBox {
                background-color: #1a1a1a;
                color: #ffffff;
                border: 1px solid #333333;
                border-radius: 3px;
                padding: 3px 6px;
                min-width: 90px;
                font-size: 11px;
            }
            QComboBox:hover { border: 1px solid #0078d4; }
            QComboBox::drop-down { border: none; width: 18px; }
            QComboBox::down-arrow {
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 5px solid #666666;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: #1a1a1a;
                color: #ffffff;
                selection-background-color: #0078d4;
                border: 1px solid #333333;
            }
            QLabel { color: #666666; font-size: 10px; }
            #PresetBar {
                background-color: #0a0a0a;
                border-bottom: 1px solid #1a1a1a;
                max-height: 26px;
                min-height: 26px;
            }
        """)
        
        # Simple preset bar only - tools come from main toolbar
        preset_bar = QFrame()
        preset_bar.setObjectName("PresetBar")
        preset_layout = QHBoxLayout(preset_bar)
        preset_layout.setContentsMargins(6, 2, 6, 2)
        preset_layout.setSpacing(6)
        
        # Preset dropdown
        preset_label = QLabel("W/L:")
        preset_layout.addWidget(preset_label)
        
        self.preset_combo = QComboBox()
        for preset_name in CT_PRESETS.keys():
            self.preset_combo.addItem(preset_name)
        self.preset_combo.currentTextChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        
        self.wl_label = QLabel("")
        self._update_wl_label()
        preset_layout.addWidget(self.wl_label)
        
        preset_layout.addStretch()
        main_layout.addWidget(preset_bar)
        
        # Create views container with grid layout
        views_container = QWidget()
        views_container.setObjectName("ViewsContainer")
        views_layout = QGridLayout(views_container)
        views_layout.setContentsMargins(1, 1, 1, 1)
        views_layout.setSpacing(1)
        
        # Arrange views in 2x2 grid:
        # Top-left: Axial, Top-right: Coronal
        # Bottom-left: 3D, Bottom-right: Sagittal
        print("Adding viewers to grid layout...", file=sys.stderr, flush=True)
        logger.info("Adding viewers to grid layout...")
        
        views_layout.addWidget(self.QtAxialOrthoViewer, 0, 0)
        views_layout.addWidget(self.QtCoronalOrthoViewer, 0, 1)
        views_layout.addWidget(self.QtVolumeViewer, 1, 0)
        views_layout.addWidget(self.QtSagittalOrthoViewer, 1, 1)
        
        print("All viewers added to grid layout", file=sys.stderr, flush=True)
        logger.info("All viewers added to grid layout")
        
        # Set equal column and row stretch
        views_layout.setColumnStretch(0, 1)
        views_layout.setColumnStretch(1, 1)
        views_layout.setRowStretch(0, 1)
        views_layout.setRowStretch(1, 1)
        
        main_layout.addWidget(views_container, 1)  # stretch factor 1
        print("Views container added to main layout", file=sys.stderr, flush=True)
        
        # Ensure all viewers are visible
        self.QtAxialOrthoViewer.setVisible(True)
        self.QtCoronalOrthoViewer.setVisible(True)
        self.QtSagittalOrthoViewer.setVisible(True)
        self.QtVolumeViewer.setVisible(True)
        views_container.setVisible(True)
        self.setVisible(True)
        
        # Initialize and render all viewers with proper camera reset
        self._initialize_viewers()
        
        # Store camera states for zoom preservation
        self._camera_states = {}
        
        print("UI layout setup complete - 2x2 grid", file=sys.stderr, flush=True)
        logger.info("UI layout setup complete - 2x2 grid")
    
    # =========================================================================
    # INTERFACE FOR MAIN TOOLBAR - Called by toolbar_manager
    # =========================================================================
    
    def activate_ruler(self):
        """Activate ruler measurement tool - called by main toolbar"""
        logger.info("MPR: Activating ruler tool...")
        self._deactivate_all_tools()
        
        if not hasattr(self, '_ruler_widgets'):
            self._ruler_widgets = []
        
        self._ruler_mode_active = True
        
        # Add observer for slice change to hide rulers
        self._add_slice_change_observers()
        
        viewers = [
            ('axial', self.QtAxialOrthoViewer),
            ('coronal', self.QtCoronalOrthoViewer),
            ('sagittal', self.QtSagittalOrthoViewer)
        ]
        
        for viewer_name, qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                try:
                    interactor = qt_viewer.viewer.GetRenderWindow().GetInteractor()
                    if interactor:
                        # Lower resliceCursorWidget priority
                        if hasattr(qt_viewer.viewer, 'resliceCursorWidget'):
                            qt_viewer.viewer.resliceCursorWidget.SetPriority(0.0)
                        
                        # Create ruler widget
                        widget = self._create_ruler_widget(interactor, viewer_name)
                        self._ruler_widgets.append((viewer_name, widget))
                        
                        qt_viewer.viewer.GetRenderWindow().Render()
                        
                except Exception as e:
                    logger.warning(f"Failed to create ruler widget: {e}")
    
    def _create_ruler_widget(self, interactor, viewer_name):
        """Create a ruler widget for a specific viewer"""
        widget = vtk.vtkDistanceWidget()
        
        # Use 2D representation - works in screen coordinates
        rep = vtk.vtkDistanceRepresentation2D()
        rep.GetAxisProperty().SetColor(0, 1, 0)
        rep.GetAxisProperty().SetLineWidth(2)
        rep.SetLabelFormat("%.1f mm")
        
        # Get the axis and set font properties
        axis = rep.GetAxis()
        axis.GetTitleTextProperty().SetFontSize(14)
        axis.GetTitleTextProperty().SetColor(0, 1, 0)
        
        widget.SetRepresentation(rep)
        widget.SetInteractor(interactor)
        widget.SetPriority(1.0)
        
        # Store current slice with widget
        viewer_map = {
            'axial': self.QtAxialOrthoViewer,
            'coronal': self.QtCoronalOrthoViewer,
            'sagittal': self.QtSagittalOrthoViewer
        }
        qt_viewer = viewer_map.get(viewer_name)
        if qt_viewer and hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
            if hasattr(qt_viewer.viewer, 'resliceCursor'):
                center = qt_viewer.viewer.resliceCursor.GetCenter()
                # Store the slice position where this ruler was created
                widget._slice_position = center[qt_viewer.viewer.orientation]
                widget._viewer_name = viewer_name
                widget._viewer_orientation = qt_viewer.viewer.orientation
        
        # Add observer to track when ruler is placed
        widget.AddObserver(vtk.vtkCommand.EndInteractionEvent, 
                          lambda obj, evt: self._on_ruler_placed(obj, viewer_name))
        
        widget.EnabledOn()
        return widget
    
    def _on_ruler_placed(self, widget, viewer_name):
        """Called when a ruler is placed - create new widget for next measurement"""
        if not getattr(self, '_ruler_mode_active', False):
            return
            
        logger.info(f"Ruler placed on {viewer_name}")
        
        # Get the viewer
        viewer_map = {
            'axial': self.QtAxialOrthoViewer,
            'coronal': self.QtCoronalOrthoViewer,
            'sagittal': self.QtSagittalOrthoViewer
        }
        
        qt_viewer = viewer_map.get(viewer_name)
        if qt_viewer and hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
            interactor = qt_viewer.viewer.GetRenderWindow().GetInteractor()
            if interactor:
                # Create new widget for next measurement
                new_widget = self._create_ruler_widget(interactor, viewer_name)
                self._ruler_widgets.append((viewer_name, new_widget))
    
    def activate_angle(self):
        """Activate angle measurement tool - called by main toolbar"""
        logger.info("MPR: Activating angle tool...")
        self._deactivate_all_tools()
        
        if not hasattr(self, '_angle_widgets'):
            self._angle_widgets = []
        
        self._angle_mode_active = True
        
        # Add observer for slice change to hide angles
        self._add_slice_change_observers()
        
        viewers = [
            ('axial', self.QtAxialOrthoViewer),
            ('coronal', self.QtCoronalOrthoViewer),
            ('sagittal', self.QtSagittalOrthoViewer)
        ]
        
        for viewer_name, qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                try:
                    interactor = qt_viewer.viewer.GetRenderWindow().GetInteractor()
                    if interactor:
                        # Lower resliceCursorWidget priority
                        if hasattr(qt_viewer.viewer, 'resliceCursorWidget'):
                            qt_viewer.viewer.resliceCursorWidget.SetPriority(0.0)
                        
                        # Create angle widget
                        widget = self._create_angle_widget(interactor, viewer_name)
                        self._angle_widgets.append((viewer_name, widget))
                        
                        qt_viewer.viewer.GetRenderWindow().Render()
                        
                except Exception as e:
                    logger.warning(f"Failed to create angle widget: {e}")
    
    def _create_angle_widget(self, interactor, viewer_name):
        """Create an angle widget for a specific viewer"""
        widget = vtk.vtkAngleWidget()
        
        # Use 2D representation
        rep = vtk.vtkAngleRepresentation2D()
        rep.GetRay1().GetProperty().SetColor(1, 1, 0)
        rep.GetRay2().GetProperty().SetColor(1, 1, 0)
        rep.GetArc().GetProperty().SetColor(1, 1, 0)
        
        widget.SetRepresentation(rep)
        widget.SetInteractor(interactor)
        widget.SetPriority(1.0)
        
        # Store current slice with widget
        viewer_map = {
            'axial': self.QtAxialOrthoViewer,
            'coronal': self.QtCoronalOrthoViewer,
            'sagittal': self.QtSagittalOrthoViewer
        }
        qt_viewer = viewer_map.get(viewer_name)
        if qt_viewer and hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
            if hasattr(qt_viewer.viewer, 'resliceCursor'):
                center = qt_viewer.viewer.resliceCursor.GetCenter()
                # Store the slice position where this angle was created
                widget._slice_position = center[qt_viewer.viewer.orientation]
                widget._viewer_name = viewer_name
                widget._viewer_orientation = qt_viewer.viewer.orientation
        
        # Add observer to track when angle is placed
        widget.AddObserver(vtk.vtkCommand.EndInteractionEvent, 
                          lambda obj, evt: self._on_angle_placed(obj, viewer_name))
        
        widget.EnabledOn()
        return widget
    
    def _on_angle_placed(self, widget, viewer_name):
        """Called when an angle is placed - create new widget for next measurement"""
        if not getattr(self, '_angle_mode_active', False):
            return
            
        logger.info(f"Angle placed on {viewer_name}")
        
        # Get the viewer
        viewer_map = {
            'axial': self.QtAxialOrthoViewer,
            'coronal': self.QtCoronalOrthoViewer,
            'sagittal': self.QtSagittalOrthoViewer
        }
        
        qt_viewer = viewer_map.get(viewer_name)
        if qt_viewer and hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
            interactor = qt_viewer.viewer.GetRenderWindow().GetInteractor()
            if interactor:
                # Create new widget for next measurement
                new_widget = self._create_angle_widget(interactor, viewer_name)
                self._angle_widgets.append((viewer_name, new_widget))
    
    def _add_slice_change_observers(self):
        """Add observers to detect slice changes and hide measurements"""
        if hasattr(self, '_slice_observers_added') and self._slice_observers_added:
            return
        
        self._slice_observers_added = True
        
        viewers = [
            self.QtAxialOrthoViewer,
            self.QtCoronalOrthoViewer,
            self.QtSagittalOrthoViewer
        ]
        
        for qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                if hasattr(qt_viewer.viewer, 'resliceCursorWidget'):
                    # Add observer for reslice changes
                    qt_viewer.viewer.resliceCursorWidget.AddObserver(
                        vtk.vtkResliceCursorWidget.ResliceAxesChangedEvent,
                        self._on_slice_changed
                    )
    
    def _on_slice_changed(self, obj, event):
        """Called when slice changes - update visibility of measurement widgets based on slice position"""
        logger.debug("Slice changed event triggered")
        
        # Force render all viewers to ensure crosshair updates properly
        try:
            self.QtAxialOrthoViewer.viewer.GetRenderWindow().Render()
            self.QtCoronalOrthoViewer.viewer.GetRenderWindow().Render()
            self.QtSagittalOrthoViewer.viewer.GetRenderWindow().Render()
        except:
            pass
        
        # Update visibility for ruler widgets
        if hasattr(self, '_ruler_widgets'):
            for item in self._ruler_widgets:
                try:
                    if isinstance(item, tuple):
                        viewer_name, widget = item
                        self._update_widget_visibility(widget, viewer_name)
                except:
                    pass
        
        # Update visibility for angle widgets
        if hasattr(self, '_angle_widgets'):
            for item in self._angle_widgets:
                try:
                    if isinstance(item, tuple):
                        viewer_name, widget = item
                        self._update_widget_visibility(widget, viewer_name)
                except:
                    pass
    
    def _update_widget_visibility(self, widget, viewer_name):
        """Update widget visibility based on current slice position"""
        if not hasattr(widget, '_slice_position'):
            # Widget doesn't have slice info, keep it visible
            return
        
        viewer_map = {
            'axial': self.QtAxialOrthoViewer,
            'coronal': self.QtCoronalOrthoViewer,
            'sagittal': self.QtSagittalOrthoViewer
        }
        
        qt_viewer = viewer_map.get(viewer_name)
        if qt_viewer and hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
            if hasattr(qt_viewer.viewer, 'resliceCursor'):
                center = qt_viewer.viewer.resliceCursor.GetCenter()
                current_slice_pos = center[widget._viewer_orientation]
                
                # Check if widget is on current slice (with small tolerance)
                tolerance = 1.0  # 1mm tolerance
                distance = abs(current_slice_pos - widget._slice_position)
                
                logger.debug(f"Widget on {viewer_name}: stored={widget._slice_position:.2f}, current={current_slice_pos:.2f}, distance={distance:.2f}")
                
                if distance < tolerance:
                    # Same slice - show widget
                    if not widget.GetEnabled():
                        logger.info(f"Showing widget on {viewer_name} (slice match)")
                        widget.EnabledOn()
                        qt_viewer.viewer.GetRenderWindow().Render()
                else:
                    # Different slice - hide widget
                    if widget.GetEnabled():
                        logger.info(f"Hiding widget on {viewer_name} (slice mismatch)")
                        widget.EnabledOff()
                        qt_viewer.viewer.GetRenderWindow().Render()
    
    def _create_new_ruler_widgets(self):
        """Create new ruler widgets after slice change"""
        if not hasattr(self, '_ruler_widgets'):
            self._ruler_widgets = []
        
        viewers = [
            ('axial', self.QtAxialOrthoViewer),
            ('coronal', self.QtCoronalOrthoViewer),
            ('sagittal', self.QtSagittalOrthoViewer)
        ]
        
        for viewer_name, qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                try:
                    interactor = qt_viewer.viewer.GetRenderWindow().GetInteractor()
                    if interactor:
                        widget = self._create_ruler_widget(interactor, viewer_name)
                        self._ruler_widgets.append((viewer_name, widget))
                except Exception as e:
                    logger.warning(f"Failed to create ruler widget: {e}")
    
    def _create_new_angle_widgets(self):
        """Create new angle widgets after slice change"""
        if not hasattr(self, '_angle_widgets'):
            self._angle_widgets = []
        
        viewers = [
            ('axial', self.QtAxialOrthoViewer),
            ('coronal', self.QtCoronalOrthoViewer),
            ('sagittal', self.QtSagittalOrthoViewer)
        ]
        
        for viewer_name, qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                try:
                    interactor = qt_viewer.viewer.GetRenderWindow().GetInteractor()
                    if interactor:
                        widget = self._create_angle_widget(interactor, viewer_name)
                        self._angle_widgets.append((viewer_name, widget))
                except Exception as e:
                    logger.warning(f"Failed to create angle widget: {e}")
    
    def deactivate_tool(self):
        """Deactivate current tool - called by main toolbar"""
        logger.info("MPR: Deactivating tools...")
        self._deactivate_all_tools()
    
    def _deactivate_all_tools(self):
        """Deactivate all measurement widgets and restore crosshair"""
        # Disable active modes
        self._ruler_mode_active = False
        self._angle_mode_active = False
        
        # Clear ruler widgets
        if hasattr(self, '_ruler_widgets'):
            for item in self._ruler_widgets:
                try:
                    if isinstance(item, tuple):
                        _, widget = item
                        widget.EnabledOff()
                    else:
                        item.EnabledOff()
                except:
                    pass
            self._ruler_widgets = []
        
        # Clear angle widgets
        if hasattr(self, '_angle_widgets'):
            for item in self._angle_widgets:
                try:
                    if isinstance(item, tuple):
                        _, widget = item
                        widget.EnabledOff()
                    else:
                        item.EnabledOff()
                except:
                    pass
            self._angle_widgets = []
        
        # Restore resliceCursorWidget priority
        viewers = [
            self.QtAxialOrthoViewer,
            self.QtCoronalOrthoViewer,
            self.QtSagittalOrthoViewer
        ]
        for qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                # Restore normal priority for resliceCursorWidget
                if hasattr(qt_viewer.viewer, 'resliceCursorWidget'):
                    qt_viewer.viewer.resliceCursorWidget.SetPriority(0.5)
                qt_viewer.viewer.GetRenderWindow().Render()
    
    def clear_measurements(self):
        """Clear all measurements - called by main toolbar"""
        logger.info("MPR: Clearing all measurements...")
        self._deactivate_all_tools()
    
    def get_interactor(self):
        """Get the interactor of the axial viewer for toolbar compatibility"""
        if hasattr(self.QtAxialOrthoViewer, 'viewer') and self.QtAxialOrthoViewer.viewer:
            return self.QtAxialOrthoViewer.viewer.GetRenderWindow().GetInteractor()
        return None
    
    def get_renderer(self):
        """Get the renderer of the axial viewer for toolbar compatibility"""
        if hasattr(self.QtAxialOrthoViewer, 'viewer') and self.QtAxialOrthoViewer.viewer:
            return self.QtAxialOrthoViewer.viewer.renderer
        return None

    def _reset_all_views(self):
        """Reset all views to default camera position"""
        logger.info("Resetting all views...")
        try:
            viewers = [
                self.QtAxialOrthoViewer,
                self.QtCoronalOrthoViewer,
                self.QtSagittalOrthoViewer,
                self.QtSegmentationViewer
            ]
            
            for qt_viewer in viewers:
                if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                    qt_viewer.viewer.renderer.ResetCamera()
                    qt_viewer.viewer.render()
            
            logger.info("All views reset successfully")
        except Exception as e:
            logger.error(f"Failed to reset views: {e}", exc_info=True)
    
    def _initialize_viewers(self):
        """Initialize and render all viewers with proper camera setup"""
        try:
            logger.info("Initializing all viewers...")
            viewers = [
                (self.QtAxialOrthoViewer, "Axial"),
                (self.QtCoronalOrthoViewer, "Coronal"),
                (self.QtSagittalOrthoViewer, "Sagittal"),
                (self.QtSegmentationViewer, "3D")
            ]
            
            for qt_viewer, name in viewers:
                if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                    qt_viewer.viewer.Initialize()
                    # Reset camera to show full image (important for proper zoom)
                    qt_viewer.viewer.renderer.ResetCamera()
                    qt_viewer.viewer.GetRenderWindow().Render()
                    logger.info(f"{name} viewer initialized with camera reset")
            
            # Set trackball style for 3D viewer
            if hasattr(self.QtSegmentationViewer, 'viewer') and self.QtSegmentationViewer.viewer:
                interactor = self.QtSegmentationViewer.viewer.GetRenderWindow().GetInteractor()
                if interactor:
                    style = vtk.vtkInteractorStyleTrackballCamera()
                    interactor.SetInteractorStyle(style)
            
            logger.info("All viewers initialized successfully")
        except Exception as e:
            logger.warning(f"Error initializing viewers: {e}", exc_info=True)
    
    def _save_camera_state(self, viewer_name, renderer):
        """Save camera state for a viewer"""
        if renderer:
            camera = renderer.GetActiveCamera()
            if camera:
                self._camera_states[viewer_name] = {
                    'position': camera.GetPosition(),
                    'focal_point': camera.GetFocalPoint(),
                    'view_up': camera.GetViewUp(),
                    'parallel_scale': camera.GetParallelScale(),
                    'clipping_range': camera.GetClippingRange()
                }
    
    def _restore_camera_state(self, viewer_name, renderer):
        """Restore camera state for a viewer"""
        if viewer_name in self._camera_states and renderer:
            state = self._camera_states[viewer_name]
            camera = renderer.GetActiveCamera()
            if camera:
                camera.SetPosition(state['position'])
                camera.SetFocalPoint(state['focal_point'])
                camera.SetViewUp(state['view_up'])
                camera.SetParallelScale(state['parallel_scale'])
                camera.SetClippingRange(state['clipping_range'])
    
    def save_all_camera_states(self):
        """Save camera states for all viewers"""
        viewers = [
            ('axial', self.QtAxialOrthoViewer),
            ('coronal', self.QtCoronalOrthoViewer),
            ('sagittal', self.QtSagittalOrthoViewer),
            ('3d', self.QtSegmentationViewer)
        ]
        for name, qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                self._save_camera_state(name, qt_viewer.viewer.renderer)
    
    def restore_all_camera_states(self):
        """Restore camera states for all viewers and re-render"""
        viewers = [
            ('axial', self.QtAxialOrthoViewer),
            ('coronal', self.QtCoronalOrthoViewer),
            ('sagittal', self.QtSagittalOrthoViewer),
            ('3d', self.QtSegmentationViewer)
        ]
        for name, qt_viewer in viewers:
            if hasattr(qt_viewer, 'viewer') and qt_viewer.viewer:
                self._restore_camera_state(name, qt_viewer.viewer.renderer)
                qt_viewer.viewer.render()
    
    def _update_wl_label(self):
        """Update the window/level display label"""
        if hasattr(self, 'wl_label') and self.wl_label:
            w = self.window_width if self.window_width else "Auto"
            c = self.window_center if self.window_center else "Auto"
            self.wl_label.setText(f"W: {w}  |  L: {c}")
    
    def _on_preset_changed(self, preset_name):
        """Handle preset selection change"""
        if preset_name not in CT_PRESETS:
            return
        
        preset = CT_PRESETS[preset_name]
        self.window_width = preset["window"]
        self.window_center = preset["level"]
        
        logger.info(f"Preset changed to: {preset_name} (W={self.window_width}, C={self.window_center})")
        
        # Apply new window/level
        try:
            self.vtkBaseClass.set_window_level(self.window_width, self.window_center)
            
            # Re-render all viewers
            self.QtSagittalOrthoViewer.render()
            self.QtCoronalOrthoViewer.render()
            self.QtAxialOrthoViewer.render()
            self.QtSegmentationViewer.render()
            
            # Update label
            self._update_wl_label()
            
            logger.info(f"Preset {preset_name} applied successfully")
        except Exception as e:
            logger.error(f"Failed to apply preset {preset_name}: {e}", exc_info=True)
    
    def set_window_level(self, window_width, window_center):
        """Public method to set window/level from outside"""
        self.window_width = window_width
        self.window_center = window_center
        
        try:
            self.vtkBaseClass.set_window_level(window_width, window_center)
            
            # Re-render all viewers
            self.QtSagittalOrthoViewer.render()
            self.QtCoronalOrthoViewer.render()
            self.QtAxialOrthoViewer.render()
            self.QtSegmentationViewer.render()
            
            # Update label
            self._update_wl_label()
        except Exception as e:
            logger.error(f"Failed to set window/level: {e}", exc_info=True)

    def cleanup(self):
        """
        Properly cleanup all VTK viewers and resources.
        MUST be called before deleteLater() to prevent crashes in frozen (exe) builds.
        VTK's QVTKRenderWindowInteractor must be Finalized before Qt destroys the widget.
        """
        logger.info("MprViewerWrapper.cleanup() called - Finalizing VTK viewers...")
        
        # Flag to track if cleanup was already done
        if getattr(self, '_cleanup_done', False):
            logger.info("Cleanup already done, skipping...")
            return
        self._cleanup_done = True
        
        # Cleanup order is important:
        # 1. First, disable any interactors to prevent callbacks during cleanup
        # 2. Then finalize viewers (this releases OpenGL resources)
        # 3. Finally cleanup any temporary files
        
        try:
            # Cleanup ViewersConnection first (removes observers)
            if hasattr(self, 'ViewersConnection') and self.ViewersConnection:
                try:
                    # ViewersConnection may have cleanup or simply setting to None
                    self.ViewersConnection = None
                    logger.info("ViewersConnection cleaned up")
                except Exception as e:
                    logger.warning(f"Error cleaning up ViewersConnection: {e}")
            
            # Cleanup each viewer - must call Finalize() on the underlying VtkViewer
            viewers_to_cleanup = [
                ('QtSagittalOrthoViewer', 'Sagittal'),
                ('QtCoronalOrthoViewer', 'Coronal'),
                ('QtAxialOrthoViewer', 'Axial'),
                ('QtSegmentationViewer', 'Segmentation'),
            ]
            
            for viewer_attr, viewer_name in viewers_to_cleanup:
                try:
                    if hasattr(self, viewer_attr):
                        qt_viewer = getattr(self, viewer_attr)
                        if qt_viewer:
                            # Get the underlying VtkViewer (which is QVTKRenderWindowInteractor)
                            vtk_viewer = qt_viewer.get_viewer() if hasattr(qt_viewer, 'get_viewer') else None
                            
                            if vtk_viewer:
                                # Finalize the render window interactor
                                try:
                                    render_window = vtk_viewer.GetRenderWindow()
                                    if render_window:
                                        # Remove all renderers first
                                        renderers = render_window.GetRenderers()
                                        if renderers:
                                            renderers.InitTraversal()
                                            renderer = renderers.GetNextItem()
                                            while renderer:
                                                render_window.RemoveRenderer(renderer)
                                                renderer = renderers.GetNextItem()
                                        render_window.Finalize()
                                except Exception as e:
                                    logger.warning(f"Error finalizing render window for {viewer_name}: {e}")
                                
                                # Finalize the interactor
                                try:
                                    vtk_viewer.Finalize()
                                    logger.info(f"{viewer_name} viewer Finalized")
                                except Exception as e:
                                    logger.warning(f"Error finalizing {viewer_name} viewer: {e}")
                            
                            # Hide and prepare for deletion
                            qt_viewer.hide()
                            setattr(self, viewer_attr, None)
                except Exception as e:
                    logger.warning(f"Error cleaning up {viewer_name} viewer: {e}")
            
            # Cleanup VtkBase
            if hasattr(self, 'vtkBaseClass') and self.vtkBaseClass:
                try:
                    self.vtkBaseClass = None
                    logger.info("VtkBase cleaned up")
                except Exception as e:
                    logger.warning(f"Error cleaning up VtkBase: {e}")
            
            logger.info("MprViewerWrapper.cleanup() completed successfully")
            
        except Exception as e:
            logger.error(f"Error during MprViewerWrapper cleanup: {e}", exc_info=True)

    def closeEvent(self, event):
        """Handle close event - cleanup VTK viewers and temporary MHD file"""
        logger.info("MprViewerWrapper.closeEvent() called")
        
        # First cleanup VTK viewers (CRITICAL - must be done before Qt destroys the widget)
        self.cleanup()
        
        # Clean up temporary MHD file
        if hasattr(self, 'mhd_path') and self.mhd_path and os.path.exists(self.mhd_path):
            try:
                raw_path = self.mhd_path.replace('.mhd', '.raw')
                if os.path.exists(raw_path):
                    os.remove(raw_path)
                os.remove(self.mhd_path)
                logger.info(f"Cleaned up temporary MHD file: {self.mhd_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")
        
        super().closeEvent(event)

