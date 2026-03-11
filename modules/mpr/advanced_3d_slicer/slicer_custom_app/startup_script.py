"""
NewMPR2Slicer Startup Script

This script runs after 3D Slicer is fully initialized via --python-script argument.
It configures Slicer to act as an advanced MPR viewer for NewMPR2, NOT as a generic
3D Slicer application.

Configuration is read from ENVIRONMENT VARIABLES (set by launch_slicer.py):
  NEWMPR2_DICOM_DIR: Path to DICOM directory (required for auto-load)
  NEWMPR2_LAYOUT: Layout name (default: 'mpr')
  NEWMPR2_PATIENT_ID: Patient ID for display
  NEWMPR2_STUDY_ID: Study ID for display
  NEWMPR2_WINDOW_WIDTH: Window width (contrast)
  NEWMPR2_WINDOW_LEVEL: Window level (brightness)
  NEWMPR2_SERIES_UID: Series UID for primary volume
  NEWMPR2_AUTO_CENTER: Whether to auto-center ('1' or '0')

Key behaviors:
  1. Bypass Welcome/DICOM browser - user should NOT see stock Slicer UI
  2. Auto-load DICOM from NEWMPR2_DICOM_DIR
  3. Set MPR layout and configure views
  4. Activate NewMPR2MPR module (if available)
  5. Set window title to "AI-PACS Advanced Viewer v0.1"

Usage:
  Slicer.exe --no-splash --python-script startup_script.py
  (with environment variables set by launch_slicer.py)
"""

import os
import sys
import json
import socket
import threading
from pathlib import Path

# ============================================================
# IMMEDIATE DIAGNOSTIC OUTPUT - Print as soon as script loads
# ============================================================
print("")
print("=" * 70)
print("[AIPACS_STARTUP_EARLY] startup_script.py LOADED AND EXECUTING")
print("=" * 70)
sys.stdout.flush()  # Ensure output is printed immediately
sys.stderr.flush()

# ============================================================
# Slicer imports - only available when running inside Slicer
# ============================================================
try:
    import slicer
    from slicer import app, util
    RUNNING_IN_SLICER = True
    print("[AIPACS_STARTUP_EARLY] Slicer imports successful")
except ImportError as import_error:
    print("[AIPACS_STARTUP_EARLY] ERROR: This script must be run inside 3D Slicer!")
    print(f"[AIPACS_STARTUP_EARLY] Import error: {import_error}")
    print("[AIPACS_STARTUP_EARLY] Usage: Slicer.exe --python-script startup_script.py")
    RUNNING_IN_SLICER = False
    sys.exit(1)

# ------------------------------------------------------------
# Make orientation logger AND unified logging available inside Slicer
# ------------------------------------------------------------
try:
    utils_dir = Path(__file__).resolve().parents[1] / "utils"
    sys.path.append(str(utils_dir))
    from orientation_logger import (
        start_run as orientation_start_run,
        log_dicom_metadata as orientation_log_dicom,
        log_volume_node as orientation_log_volume_node,
        log_volume_geometry as orientation_log_volume_geometry,
        log_slice_nodes as orientation_log_slice_nodes,
    )
    import vtk  # needed for matrix containers
    _ORIENT_LOG_AVAILABLE = True
except Exception as e:
    print(f"[AIPACS_STARTUP_EARLY] Warning: orientation logger unavailable: {e}")
    _ORIENT_LOG_AVAILABLE = False

# Add unified logging for comparison with NewMPR
try:
    script_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(script_dir))
    from unified_logging import (
        log_volume_geometry,
        log_slice_geometry,
        compute_xy_to_ijk_slicer,
        compute_and_log_dicom_slice_geometry,
        log_camera_geometry,
    )
    _UNIFIED_LOG_AVAILABLE = True
    print("[AIPACS_STARTUP_EARLY] Unified logging available")
except Exception as e:
    print(f"[AIPACS_STARTUP_EARLY] Warning: unified logging unavailable: {e}")
    _UNIFIED_LOG_AVAILABLE = False

print("[AIPACS_STARTUP_EARLY] Slicer environment detected - continuing with setup")
print("=" * 70)
sys.stdout.flush()

# ============================================================
# Window Geometry Configuration
# ============================================================

def configure_main_window_geometry():
    """
    Configure NewMPR2Slicer main window to ~70% of desktop, centered.
    
    This ensures the window appears as a modal-like popup rather
    than a full-screen IDE-like application, matching the main AI-PACS UI style.
    """
    try:
        import qt
        
        mw = slicer.util.mainWindow()
        if not mw:
            print("[AIPACS_STARTUP] Warning: Main window not found for geometry configuration")
            return
        
        # Ensure we are not maximized / full screen
        mw.showNormal()
        
        # Get the screen's available geometry (excludes taskbar)
        screen = qt.QApplication.primaryScreen
        if screen:
            desktop = screen.availableGeometry()
        else:
            # Fallback for older Qt
            desktop = qt.QApplication.desktop().availableGeometry()
        
        # Calculate ~70% of desktop size
        width = int(desktop.width * 0.7)
        height = int(desktop.height * 0.7)
        
        # Center the window on screen
        x = desktop.x + (desktop.width - width) // 2
        y = desktop.y + (desktop.height - height) // 2
        
        # Apply geometry
        mw.setGeometry(x, y, width, height)
        
        print(f"[AIPACS_STARTUP] [OK] Window geometry: {width}x{height} at ({x},{y}) - 70% centered")
        
    except Exception as e:
        print(f"[AIPACS_STARTUP] Warning: Could not configure window geometry: {e}")


def neutralize_slice_node_colors():
    """
    Neutralize the MRML slice node colors to remove red/green/yellow bars.
    
    Instead of the default Slicer colors (red for axial, yellow for sagittal,
    green for coronal), we set all slice views to a dark gray color that
    matches the main AI-PACS application theme.
    
    This uses the proper Slicer API:
      1. sliceWidget.setSliceViewColor(QColor) - sets both MRML node and triggers controller update
      2. Direct palette manipulation on barWidget for text/button styling
    
    Based on Slicer source code analysis:
    - qMRMLSliceControllerWidget::setSliceViewColor() calls sliceNode->SetLayoutColor()
    - qMRMLSliceControllerWidgetPrivate::setColor() sets gradient palette on BarWidget
    - The slider spinbox has hardcoded black text in C++, override with palette
    
    Color Palette (matching main AI-PACS app from _variables.scss):
    - Background: #21272a (RGB 33, 39, 42)
    - Accent: #fba43b (orange)
    - Text: #fefefe (white)
    """
    try:
        import qt
        
        lm = slicer.app.layoutManager()
        if not lm:
            print("[AIPACS_STARTUP] Warning: Layout manager not available for slice color neutralization")
            return
        
        # AI-PACS main background color from _variables.scss
        # #21272a in RGB = (33, 39, 42) normalized = (0.129, 0.153, 0.165)
        neutral_qcolor = qt.QColor(33, 39, 42)  # Dark gray matching main AI-PACS theme
        
        for name in ("Red", "Yellow", "Green"):
            sliceWidget = lm.sliceWidget(name)
            if not sliceWidget:
                print(f"[AIPACS_STARTUP] Warning: {name} slice widget not found")
                continue
            
            # Method 1: Use the proper API to set slice view color
            # In PythonQt, this is a property setter: sliceViewColor = color
            try:
                sliceWidget.sliceViewColor = neutral_qcolor
                print(f"[AIPACS_STARTUP] [OK] {name}: sliceViewColor property set")
            except Exception as e:
                print(f"[AIPACS_STARTUP] Warning: {name} sliceViewColor failed: {e}")
                # Fallback to direct MRML node manipulation
                try:
                    sliceNode = sliceWidget.mrmlSliceNode()
                    if sliceNode:
                        sliceNode.SetLayoutColor(neutral_qcolor.redF(), neutral_qcolor.greenF(), neutral_qcolor.blueF())
                        print(f"[AIPACS_STARTUP] [OK] {name}: SetLayoutColor fallback applied")
                except Exception as e2:
                    print(f"[AIPACS_STARTUP] Warning: {name} SetLayoutColor also failed: {e2}")
            
            # Method 2: Style the slice controller bar elements for light text on dark background
            controller = sliceWidget.sliceController()
            if controller:
                try:
                    # Get the bar widget (the visible colored bar)
                    barWidget = controller.barWidget()
                    if barWidget:
                        # Apply a palette with white text matching AI-PACS theme (#fefefe)
                        palette = barWidget.palette()
                        palette.setColor(qt.QPalette.WindowText, qt.QColor(254, 254, 254))  # White text matching AI-PACS
                        palette.setColor(qt.QPalette.Text, qt.QColor(254, 254, 254))
                        palette.setColor(qt.QPalette.ButtonText, qt.QColor(254, 254, 254))
                        barWidget.setPalette(palette)
                        print(f"[AIPACS_STARTUP] [OK] {name}: Bar palette updated for white text")
                    
                    # Style the view label for visibility on dark background
                    viewLabel = controller.viewLabel()
                    if viewLabel:
                        # Force white text on the view label (#fefefe)
                        labelPalette = viewLabel.palette()
                        labelPalette.setColor(qt.QPalette.WindowText, qt.QColor(254, 254, 254))
                        labelPalette.setColor(qt.QPalette.Text, qt.QColor(254, 254, 254))
                        viewLabel.setPalette(labelPalette)
                        print(f"[AIPACS_STARTUP] [OK] {name}: View label styled")
                    
                except Exception as bar_e:
                    print(f"[AIPACS_STARTUP] Warning: {name} bar styling failed: {bar_e}")
            
            # Method 3: Also update the 3D view label color (for the fourth quadrant in 4-up)
            try:
                threeDWidget = lm.threeDWidget(0)
                if threeDWidget:
                    threeDViewNode = threeDWidget.mrmlViewNode
                    if threeDViewNode:
                        # Set the 3D view layout color to match
                        threeDViewNode.SetLayoutColor(neutral_qcolor.redF(), neutral_qcolor.greenF(), neutral_qcolor.blueF())
                        print("[AIPACS_STARTUP] [OK] 3D view layout color neutralized")
            except Exception as e3d:
                pass  # 3D view styling is optional
        
        # Force refresh of all slice views to apply changes
        try:
            for sliceViewName in lm.sliceViewNames():
                sliceLogic = lm.sliceWidget(sliceViewName).sliceLogic
                if sliceLogic:
                    sliceNode = sliceLogic.GetSliceNode()
                    if sliceNode:
                        sliceNode.Modified()  # Trigger update
        except Exception as refresh_e:
            print(f"[AIPACS_STARTUP] Warning: Slice refresh failed: {refresh_e}")
        
        print("[AIPACS_STARTUP] [OK] All slice views neutralized with dark theme")
        
    except Exception as e:
        print(f"[AIPACS_STARTUP] Warning: Could not neutralize slice colors: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# Immediate Branding (called as early as possible)
# ============================================================

def remove_panel_logo():
    """
    Remove the large logo from PanelDockWidget title bar.
    
    =========================================================================
    DEPRECATED (2026-01-06):
    =========================================================================
    This function is now DEPRECATED. Logo removal is now handled by C++
    in qNewMPR2SlicerAppMainWindow.cxx::setupUi().
    
    The C++ code now creates an empty QWidget with height 0 as the title bar
    widget, instead of the large LogoFull.png image.
    
    This function is kept for backwards compatibility but will return True
    immediately without doing anything.
    =========================================================================
    """
    print("[NewMPR2] remove_panel_logo() called but logo is removed by C++")
    return True  # Logo is already removed by C++


def apply_immediate_branding():
    """
    Apply branding to window title and application identity IMMEDIATELY.
    
    This function is called as soon as the script loads (before any delay),
    to minimize the time the user sees "3D Slicer" in the title bar.
    
    =========================================================================
    UPDATE (2026-01-06):
    =========================================================================
    Logo removal is now handled by C++ in qNewMPR2SlicerAppMainWindow.cxx.
    The title bar widget is set to an empty QWidget with height 0 in C++.
    
    This function now only handles:
    - Setting Qt application properties
    - Setting window title
    =========================================================================
    """
    try:
        import qt
        
        # ==============================================================
        # Logo removal is now done in C++ - skip Python-side removal
        # The C++ code in qNewMPR2SlicerAppMainWindow.cxx now creates
        # an empty title bar widget instead of the large LogoFull.png
        # ==============================================================
        print("[NewMPR2] [OK] Logo already removed by C++ (no Python action needed)")
        
        # Set Qt application properties
        qt.QCoreApplication.setApplicationName("AI-PACS Advanced Viewer")
        qt.QCoreApplication.setOrganizationName("AI-PACS")
        qt.QCoreApplication.setOrganizationDomain("ai-pacs.local")
        # Note: setApplicationDisplayName may not exist in all Qt versions
        try:
            qt.QCoreApplication.setApplicationDisplayName("AI-PACS Advanced Viewer v0.1")
        except AttributeError:
            pass
        print("[NewMPR2] [OK] Application identity set (immediate)")
        
        # Set main window title immediately
        mw = slicer.util.mainWindow()
        if mw:
            mw.setWindowTitle("AI-PACS Advanced Viewer v0.1")
            print("[NewMPR2] [OK] Window title set (immediate)")
        
    except Exception as e:
        print(f"[NewMPR2] Warning: Immediate branding failed: {e}")


def suppress_welcome_module_early():
    """
    Suppress Welcome module selection as early as possible.
    
    =========================================================================
    UPDATED (2026-01-07 - STABLE BUILD):
    =========================================================================
    This function is now a NO-OP. Module selection is handled by C++ in
    setupUi() BEFORE the window is shown. C++ sets NewMPR2MPR as the home
    module and explicitly selects it.
    
    NO Python selectModule() calls should be made.
    =========================================================================
    """
    # NO-OP: Module selection handled by C++
    print("[AIPACS_UI_PY] UI: Module selection handled by C++ (no changes)")
    pass


# ============================================================
# Layout Mapping (matches launch_contract.md)
# ============================================================

LAYOUT_MAP = {
    "mpr": 500,      # SlicerLayoutFourUpView - actual ID
    "fourup": 500,   # SlicerLayoutFourUpView
    "axial": 6,      # SlicerLayoutOneUpRedSliceView
    "sagittal": 7,   # SlicerLayoutOneUpYellowSliceView
    "coronal": 8,    # SlicerLayoutOneUpGreenSliceView
    "threed": 4,     # SlicerLayoutOneUp3DView
    "conventional": 2,  # SlicerLayoutConventionalView
    "dualthreed": 15,   # SlicerLayoutDual3DView
}

# Fallback using vtkMRML constants if available
if RUNNING_IN_SLICER:
    try:
        LAYOUT_MAP = {
            "mpr": slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView,
            "fourup": slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView,
            "axial": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView,
            "sagittal": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpYellowSliceView,
            "coronal": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpGreenSliceView,
            "threed": slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView,
            "conventional": slicer.vtkMRMLLayoutNode.SlicerLayoutConventionalView,
            "dualthreed": slicer.vtkMRMLLayoutNode.SlicerLayoutDual3DView,
        }
    except Exception:
        pass  # Use hardcoded IDs as fallback

DEFAULT_LAYOUT = "mpr"

# ============================================================
# Remote Command Server (Advanced Analysis series switching)
# ============================================================

REMOTE_HOST = "127.0.0.1"
REMOTE_PORT = int(os.environ.get("NEWMPR2_REMOTE_PORT", "47891"))
_REMOTE_SERVER_STARTED = False


def _handle_remote_load(payload: dict) -> None:
    try:
        dicom_dir = payload.get("dicom_dir")
        layout = payload.get("layout") or DEFAULT_LAYOUT
        series_uid = payload.get("series_uid")
        window_width = payload.get("window_width")
        window_level = payload.get("window_level")
        patient_id = payload.get("patient_id")
        study_id = payload.get("study_id")

        args = {
            "dicom_dir": dicom_dir,
            "layout": layout,
            "series_uid": series_uid,
            "window_width": window_width,
            "window_level": window_level,
            "patient_id": patient_id,
            "study_id": study_id,
            "auto_center": True
        }

        primary_volume = None
        if dicom_dir:
            primary_volume = load_dicom_folder(dicom_dir, series_uid=series_uid)

        configure_views(layout, primary_volume, args)
        apply_window_level_if_present(primary_volume, args)
        store_patient_info(patient_id, study_id, window_width, window_level, series_uid)
        set_window_title(patient_id, study_id)
        print("[AIPACS_REMOTE] Remote series load completed")
    except Exception as e:
        print(f"[AIPACS_REMOTE] Error handling remote load: {e}")


def _schedule_remote_load(payload: dict) -> None:
    try:
        import qt
        qt.QTimer.singleShot(0, lambda: _handle_remote_load(payload))
    except Exception as e:
        print(f"[AIPACS_REMOTE] Failed to schedule remote load: {e}")


def _remote_server_loop() -> None:
    try:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((REMOTE_HOST, REMOTE_PORT))
        server.listen(5)
        print(f"[AIPACS_REMOTE] Listening on {REMOTE_HOST}:{REMOTE_PORT}")
    except Exception as e:
        print(f"[AIPACS_REMOTE] Failed to start server: {e}")
        return

    while True:
        try:
            conn, _addr = server.accept()
            with conn:
                data = b""
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    if b"\n" in data:
                        break

                response = {"ok": False, "message": "invalid"}
                if data:
                    try:
                        payload = json.loads(data.split(b"\n")[0].decode("utf-8"))
                        command = payload.get("command")
                        if command in ("load_dicom", "load_series"):
                            _schedule_remote_load(payload)
                            response = {"ok": True, "message": "scheduled"}
                        else:
                            response = {"ok": False, "message": "unknown_command"}
                    except Exception as parse_error:
                        response = {"ok": False, "message": f"parse_error: {parse_error}"}

                conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        except Exception as loop_error:
            print(f"[AIPACS_REMOTE] Server loop error: {loop_error}")


def start_remote_command_server() -> None:
    global _REMOTE_SERVER_STARTED
    if _REMOTE_SERVER_STARTED:
        return

    _REMOTE_SERVER_STARTED = True
    thread = threading.Thread(target=_remote_server_loop, daemon=True)
    thread.start()


# ============================================================
# Argument Parsing (from environment variables)
# ============================================================

def parse_newmpr2_args():
    """
    Parse NewMPR2-specific configuration from environment variables.
    
    These are set by launch_slicer.py via get_slicer_env() before launching.
    
    Returns:
        dict with parsed arguments
    """
    print("[NewMPR2] Parsing configuration from environment variables...")
    
    args = {
        "dicom_dir": os.environ.get("NEWMPR2_DICOM_DIR"),
        "layout": os.environ.get("NEWMPR2_LAYOUT", DEFAULT_LAYOUT).lower(),
        "patient_id": os.environ.get("NEWMPR2_PATIENT_ID"),
        "study_id": os.environ.get("NEWMPR2_STUDY_ID"),
        "window_width": None,
        "window_level": None,
        "series_uid": os.environ.get("NEWMPR2_SERIES_UID"),
        "auto_center": os.environ.get("NEWMPR2_AUTO_CENTER", "1") == "1",
    }
    
    # Parse numeric values
    ww = os.environ.get("NEWMPR2_WINDOW_WIDTH")
    if ww:
        try:
            args["window_width"] = float(ww)
        except ValueError:
            print(f"[NewMPR2] Warning: Invalid NEWMPR2_WINDOW_WIDTH: {ww}")
    
    wl = os.environ.get("NEWMPR2_WINDOW_LEVEL")
    if wl:
        try:
            args["window_level"] = float(wl)
        except ValueError:
            print(f"[NewMPR2] Warning: Invalid NEWMPR2_WINDOW_LEVEL: {wl}")
    
    # =========================================================================
    # [AIPACS_LINK_DST] PHASE 3: DESTINATION SIDE LOGGING
    # Log configuration parsed from environment variables
    # =========================================================================
    print("[AIPACS_LINK_DST] =================================================")
    print("[AIPACS_LINK_DST] Parsed env configuration in startup_script.py:")
    print(f"[AIPACS_LINK_DST]   dicom_dir   = {args['dicom_dir']}")
    print(f"[AIPACS_LINK_DST]   series_uid  = {args['series_uid']}")
    print(f"[AIPACS_LINK_DST]   layout      = {args['layout']}")
    print(f"[AIPACS_LINK_DST]   ww/wl       = {args['window_width']}/{args['window_level']}")
    print(f"[AIPACS_LINK_DST]   patient_id  = {args['patient_id']}")
    print(f"[AIPACS_LINK_DST]   study_id    = {args['study_id']}")
    print(f"[AIPACS_LINK_DST]   auto_center = {args['auto_center']}")
    print("[AIPACS_LINK_DST] =================================================")
    sys.stdout.flush()
    
    return args


# ============================================================
# DICOM Loading (using DICOMLib.DICOMUtils)
# ============================================================

def load_dicom_folder(dicom_dir, series_uid=None):
    """
    Load DICOM data from the specified directory.
    
    This uses Slicer's proper DICOM import mechanism:
    1. Import DICOM files into Slicer's DICOM database
    2. Load the series as a volume node
    
    Args:
        dicom_dir: Path to DICOM directory (should be series-specific folder)
        series_uid: Optional Series Instance UID for verification
        
    Returns:
        Primary volume node, or None if failed
    """
    if not dicom_dir:
        print("[NewMPR2] No dicom_dir specified, skip loading")
        return None
    
    dicom_path = os.path.abspath(dicom_dir)
    
    # =========================================================================
    # [AIPACS_DICOM] Log DICOM loading parameters
    # =========================================================================
    print("[AIPACS_DICOM] ========================================")
    print(f"[AIPACS_DICOM] dicom_dir = {dicom_path}")
    print(f"[AIPACS_DICOM] requested series_uid = {series_uid}")
    print(f"[AIPACS_DICOM] directory exists = {os.path.exists(dicom_path)}")
    
    if not os.path.exists(dicom_path):
        print(f"[AIPACS_DICOM] [FAIL] DICOM directory does not exist!")
        print("[AIPACS_DICOM] ========================================")
        return None
    
    # =========================================================================
    # STRATEGY 1: Use DICOMUtils for proper DICOM loading
    # This is the correct way to load DICOM in Slicer
    # =========================================================================
    try:
        from DICOMLib import DICOMUtils
        
        print("[AIPACS_DICOM] Using DICOMUtils for proper DICOM import...")
        
        # Import DICOM files into Slicer's DICOM database
        with DICOMUtils.TemporaryDICOMDatabase() as db:
            DICOMUtils.importDicom(dicom_path, db)
            patient_uids = db.patients()
            
            if not patient_uids:
                print("[NewMPR2] No patients found in DICOM database after import")
                # Fall back to direct loading
                return _load_dicom_direct(dicom_path)
            
            print(f"[NewMPR2] Found {len(patient_uids)} patient(s) in imported DICOM")
            
            # Load the first available series as volume
            loaded_node_ids = DICOMUtils.loadPatientByUID(patient_uids[0])
            
            if loaded_node_ids:
                print(f"[NewMPR2] Loaded {len(loaded_node_ids)} node(s) from DICOM")
                # Get the first volume node
                for node_id in loaded_node_ids:
                    node = slicer.mrmlScene.GetNodeByID(node_id)
                    if node and node.IsA("vtkMRMLScalarVolumeNode"):
                        print(f"[AIPACS_DICOM] [OK] Loaded volume node: {node.GetName()} (id={node.GetID()})")
                        print("[AIPACS_DICOM] ========================================")
                        _log_orientation_baseline(node)
                        return node
            
            print("[NewMPR2] No volume nodes loaded via DICOMUtils, trying fallback...")
            
    except ImportError as ie:
        print(f"[NewMPR2] DICOMLib not available: {ie}, trying alternative method...")
    except Exception as e:
        print(f"[NewMPR2] DICOMUtils loading failed: {e}")
        import traceback
        traceback.print_exc()
    
    # =========================================================================
    # STRATEGY 2: Use slicer.util.loadVolume on individual files
    # =========================================================================
    return _load_dicom_direct(dicom_path)


def _log_orientation_baseline(volume_node):
    """Write orientation/geometry baseline for NewMPR2 to the shared log."""
    if not _ORIENT_LOG_AVAILABLE:
        return
    try:
        # Resolve instance UID(s) and series UID
        instance_uid = None
        series_uid = None
        if hasattr(volume_node, 'GetAttribute'):
            instance_uids_attr = volume_node.GetAttribute("DICOM.instanceUIDs") or ""
            if instance_uids_attr:
                instance_uid = instance_uids_attr.split()[0]
            series_uid = volume_node.GetAttribute("DICOM.SeriesInstanceUID") or None

        if not series_uid and instance_uid and hasattr(slicer, 'dicomDatabase') and slicer.dicomDatabase:
            series_uid = slicer.dicomDatabase.instanceValue(instance_uid, "0020,000E") or None

        orientation_start_run(series_uid)

        # DICOM metadata via Slicer DICOM DB if available
        meta = {}
        if instance_uid and hasattr(slicer, 'dicomDatabase') and slicer.dicomDatabase and slicer.dicomDatabase.isOpen:
            db = slicer.dicomDatabase
            meta["ImageOrientationPatient"] = db.instanceValue(instance_uid, "0020,0037")
            meta["ImagePositionPatient"] = db.instanceValue(instance_uid, "0020,0032")
            meta["PatientPosition"] = db.instanceValue(instance_uid, "0018,5100")
            meta["PixelSpacing"] = db.instanceValue(instance_uid, "0028,0030")
            meta["SliceThickness"] = db.instanceValue(instance_uid, "0018,0050")
            meta["SeriesInstanceUID"] = series_uid
        orientation_log_dicom(meta)

        # Volume geometry
        ijk_to_ras = vtk.vtkMatrix4x4()
        ras_to_ijk = vtk.vtkMatrix4x4()
        try:
            volume_node.GetIJKToRASMatrix(ijk_to_ras)
            volume_node.GetRASToIJKMatrix(ras_to_ijk)
        except Exception:
            pass

        orientation_attrs = None
        if hasattr(volume_node, 'GetOrientationString'):
            try:
                orientation_attrs = volume_node.GetOrientationString()
            except Exception:
                orientation_attrs = None

        orientation_log_volume_node("NEW_MPR2", volume_node, ijk_to_ras, ras_to_ijk, orientation_attrs)

    except Exception as e:
        print(f"[AIPACS_DICOM] Warning: could not log orientation baseline: {e}")


def _load_dicom_direct(dicom_path):
    """
    Load DICOM by directly loading files with slicer.util.loadVolume.
    
    This is a fallback when DICOMUtils is not available or fails.
    """
    try:
        print(f"[NewMPR2] Trying direct DICOM loading from: {dicom_path}")
        
        # Find DICOM files in the folder
        dicom_files = []
        for root, dirs, files in os.walk(dicom_path):
            for f in files:
                filepath = os.path.join(root, f)
                # Skip obvious non-DICOM files
                ext = os.path.splitext(f)[1].lower()
                if ext not in ('.txt', '.xml', '.json', '.html', '.log', '.ini', '.cfg', '.py', '.md'):
                    dicom_files.append(filepath)
        
        if not dicom_files:
            print(f"[NewMPR2] No potential DICOM files found in {dicom_path}")
            return None
        
        # Sort to get consistent ordering (first slice)
        dicom_files.sort()
        print(f"[AIPACS_DICOM] found {len(dicom_files)} candidate files")
        
        # Try loading the first file - Slicer should load the series
        first_file = dicom_files[0]
        print(f"[NewMPR2] Attempting to load: {os.path.basename(first_file)}")
        
        try:
            volume_node = slicer.util.loadVolume(first_file)
            if volume_node and hasattr(volume_node, 'GetName'):
                print(f"[AIPACS_DICOM] [OK] Loaded volume node: {volume_node.GetName()} (id={volume_node.GetID()})")
                print(f"[AIPACS_DICOM] using loader: slicer.util.loadVolume (direct)")
                print("[AIPACS_DICOM] ========================================")
                _log_orientation_baseline(volume_node)
                return volume_node
        except Exception as lv_error:
            print(f"[NewMPR2] loadVolume failed on first file: {lv_error}")
        
        # Try a few more files in case the first one is not a valid DICOM
        for i, fpath in enumerate(dicom_files[1:5]):  # Try up to 5 files
            try:
                print(f"[NewMPR2] Trying file {i+2}: {os.path.basename(fpath)}")
                volume_node = slicer.util.loadVolume(fpath)
                if volume_node and hasattr(volume_node, 'GetName'):
                    print(f"[NewMPR2] [OK] Loaded volume: {volume_node.GetName()}")
                    _log_orientation_baseline(volume_node)
                    return volume_node
            except Exception:
                continue
        
        print("[NewMPR2] [FAIL] Could not load any DICOM file as volume")
        return None
        
    except Exception as e:
        print(f"[NewMPR2] Direct DICOM load failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def _load_dicom_from_files(dicom_path):
    """
    DEPRECATED: Use _load_dicom_direct instead.
    Kept for backwards compatibility.
    """
    return _load_dicom_direct(dicom_path)


# ============================================================
# Layout Configuration
# ============================================================

def set_layout(layout_name):
    """
    Set the Slicer layout based on the layout name.
    
    Args:
        layout_name: Layout name from launch_contract.md
    """
    layout_lower = layout_name.lower()
    
    if layout_lower not in LAYOUT_MAP:
        print(f"[NewMPR2] Warning: Unknown layout '{layout_name}', using '{DEFAULT_LAYOUT}'")
        layout_lower = DEFAULT_LAYOUT
    
    layout_id = LAYOUT_MAP[layout_lower]
    
    print(f"[NewMPR2] Setting layout: {layout_name} (ID: {layout_id})")
    
    try:
        layout_manager = slicer.app.layoutManager()
        layout_manager.setLayout(layout_id)
        print(f"[NewMPR2] [OK] Layout set to: {layout_name}")
    except Exception as e:
        print(f"[NewMPR2] Error setting layout: {e}")


def configure_views(layout_name, primary_volume, args):
    """
    Configure slice views after loading a volume.
    
    Sets the primary volume as background in all slice views,
    fits the slices to show the full volume, and enables crosshair linking.
    
    Args:
        layout_name: The layout name (for setting 4-up if MPR)
        primary_volume: The loaded primary volume node
        args: Parsed arguments dict with auto_center, window_width, window_level
    """
    try:
        lm = slicer.app.layoutManager()
        
        # Force MPR/4-up layout if primary volume exists
        if primary_volume:
            lm.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
            print("[AIPACS_STARTUP] [OK] Layout set to 4-up view")
            
            # Log selected volume with series_uid for debugging
            series_uid = args.get("series_uid") if args else None
            print(f"[AIPACS_STARTUP] Selected volume from series_uid: {series_uid} => {primary_volume.GetName()}")
        
        # Set the volume as background in all slice views
        if primary_volume:
            print(f"[AIPACS_STARTUP] Volume ID: {primary_volume.GetID()}")
            slice_view_names = lm.sliceViewNames()
            print(f"[AIPACS_STARTUP] Slice view names: {list(slice_view_names)}")
            
            for viewName in slice_view_names:
                sliceWidget = lm.sliceWidget(viewName)
                if sliceWidget:
                    # Get composite node through sliceLogic for reliable access
                    sliceLogic = sliceWidget.sliceLogic()
                    if sliceLogic:
                        compNode = sliceLogic.GetSliceCompositeNode()
                        if compNode:
                            compNode.SetBackgroundVolumeID(primary_volume.GetID())
                            print(f"[AIPACS_STARTUP]   {viewName}: BackgroundVolumeID set to {primary_volume.GetID()}")
                        else:
                            print(f"[AIPACS_STARTUP]   {viewName}: WARNING - GetSliceCompositeNode() returned None")
                    else:
                        print(f"[AIPACS_STARTUP]   {viewName}: WARNING - sliceLogic() returned None")
                else:
                    print(f"[AIPACS_STARTUP]   {viewName}: WARNING - sliceWidget returned None")
            print(f"[AIPACS_STARTUP] [OK] Volume '{primary_volume.GetName()}' set as background in all slice views")
            
            # Also set as active volume in selection node
            app_logic = slicer.app.applicationLogic()
            selection_node = app_logic.GetSelectionNode()
            selection_node.SetActiveVolumeID(primary_volume.GetID())
            app_logic.PropagateVolumeSelection()
            
            # =====================================================================
            # [AIPACS_DICOM] Verify slice composite node assignments
            # Log which volume ID is set as background in each slice view
            # =====================================================================
            print("[AIPACS_DICOM] Verifying slice composite node assignments:")
            for viewName in lm.sliceViewNames():
                sliceWidget = lm.sliceWidget(viewName)
                if sliceWidget:
                    sliceLogic = sliceWidget.sliceLogic()
                    if sliceLogic:
                        compNode = sliceLogic.GetSliceCompositeNode()
                        if compNode:
                            bg_id = compNode.GetBackgroundVolumeID()
                            fg_id = compNode.GetForegroundVolumeID()
                            print(f"[AIPACS_DICOM]   {viewName}: background={bg_id}, foreground={fg_id}")
                        else:
                            print(f"[AIPACS_DICOM]   {viewName}: No composite node")
            print("[AIPACS_DICOM] ========================================")
            sys.stdout.flush()
        else:
            # No volume loaded - log warning
            series_uid = args.get("series_uid") if args else None
            if series_uid:
                print(f"[AIPACS_STARTUP] WARNING: No volume loaded for series_uid: {series_uid}")
            else:
                print("[AIPACS_STARTUP] WARNING: No volume loaded (no series_uid provided)")
        
        # Fit slices to background (center and zoom to fit)
        for viewName in lm.sliceViewNames():
            sliceWidget = lm.sliceWidget(viewName)
            if sliceWidget:
                sliceLogic = sliceWidget.sliceLogic()
                if sliceLogic:
                    sliceLogic.FitSliceToAll()
        print("[AIPACS_STARTUP] [OK] Slices fitted to volume")
        
        # Also reset all slice views for good measure
        auto_center = args.get("auto_center", True) if args else True
        if auto_center:
            slicer.util.resetSliceViews()
            print("[AIPACS_STARTUP] [OK] Slice views reset and centered")

        # Geometry logging for volume and slice nodes (delayed to ensure initialization)
        #
        # Slicer ground-truth pipeline (what we mirror in NewMPR):
        #   1) Volume loading: slicer.util.loadVolume / DICOMUtils creates a vtkMRMLScalarVolumeNode.
        #      - IJKToRAS encodes DICOM orientation (ImageOrientationPatient) + spacing + origin, already in RAS.
        #   2) Slice views: the layout manager owns vtkMRMLSliceNodes (Red/Yellow/Green) that drive the slice logics.
        #      - sliceNode.GetSliceToRAS(): orientation + position. Axes come from vtkMRMLSliceNode::UpdateMatrices:
        #          axial:    x=-I_dir, y=-J_dir, z=+K_dir
        #          sagittal: x=+J_dir, y=-K_dir, z=+I_dir
        #          coronal:  x=-I_dir, y=-K_dir, z=-J_dir
        #        The origin term is volume center plus offset_mm along z (slice normal).
        #      - sliceNode.GetFieldOfView(): result of SliceLogic::FitSliceToAll (projects volume bounds into slice axes).
        #      - sliceNode.GetDimensions(): current viewport pixel size of the slice view widget.
        #      - sliceNode.GetXYToRAS(): SliceToRAS * XYToSlice, with XYToSlice spacing = FOV/Dimensions and centered at 0.
        #   3) XYToIJK = RASToIJK * XYToRAS (no extra flips or scaling).
        # We log exactly these matrices as the reference for NewMPR.
        def _log_geometry_delayed():
            if primary_volume:
                try:
                    # Use unified logging for comparison with NewMPR
                    if _UNIFIED_LOG_AVAILABLE:
                        ijk_to_ras = vtk.vtkMatrix4x4()
                        primary_volume.GetIJKToRASMatrix(ijk_to_ras)
                        
                        log_volume_geometry(
                            "NEWMPR2",
                            primary_volume,
                            ijk_to_ras,
                            name=primary_volume.GetName(),
                            node_id=primary_volume.GetID()
                        )
                        
                        # Get RASToIJK for slice computation
                        ras_to_ijk = vtk.vtkMatrix4x4()
                        primary_volume.GetRASToIJKMatrix(ras_to_ijk)
                        
                        # Log slice geometry for each view
                        # Map to same names as NewMPR for direct comparison
                        lm_delayed = slicer.app.layoutManager()
                        view_mapping = [
                            ("Red", "axial"),
                            ("Yellow", "sagittal"),
                            ("Green", "coronal")
                        ]
                        
                        for slicer_view_name, unified_view_name in view_mapping:
                            sliceWidget = lm_delayed.sliceWidget(slicer_view_name)
                            if sliceWidget:
                                slice_node = sliceWidget.mrmlSliceNode()
                                if slice_node:
                                    # Get SliceToRAS - no argument version
                                    slice_to_ras = vtk.vtkMatrix4x4()
                                    slice_to_ras.DeepCopy(slice_node.GetSliceToRAS())
                                    
                                    # Get XYToRAS - no argument version
                                    xy_to_ras = vtk.vtkMatrix4x4()
                                    xy_to_ras.DeepCopy(slice_node.GetXYToRAS())
                                    
                                    # Compute XYToIJK = RASToIJK × XYToRAS
                                    xy_to_ijk = vtk.vtkMatrix4x4()
                                    vtk.vtkMatrix4x4.Multiply4x4(ras_to_ijk, xy_to_ras, xy_to_ijk)
                                    
                                    # Get slice offset
                                    offset_mm = slice_node.GetSliceOffset()
                                    
                                    # Get FOV and dimensions
                                    fov = slice_node.GetFieldOfView()  # Returns tuple (x, y, z)
                                    dims = slice_node.GetDimensions()  # Returns tuple (x, y, z)
                                    
                                    log_slice_geometry(
                                        "NEWMPR2",
                                        unified_view_name,  # Use "axial", "sagittal", "coronal" for comparison
                                        slice_to_ras,
                                        xy_to_ijk,
                                        slice_index=None,
                                        offset_mm=offset_mm,
                                        fov=fov,
                                        dimensions=dims,
                                        xy_to_ras=xy_to_ras
                                    )
                                    
                                    # Log synthetic DICOM geometry for this slice
                                    compute_and_log_dicom_slice_geometry(
                                        tag="NEWMPR2",
                                        view_name=unified_view_name,
                                        slice_to_ras=slice_to_ras,
                                        xy_to_ras=xy_to_ras,
                                        ijk_to_ras=ijk_to_ras,
                                        ras_to_ijk=ras_to_ijk,
                                        fov_mm=fov,
                                        view_dims_px=dims
                                    )

                                    # Log camera geometry/centering for this view
                                    try:
                                        renderer = None
                                        camera = None
                                        try:
                                            render_window = sliceWidget.sliceView().renderWindow()
                                            if render_window:
                                                renderer = render_window.GetRenderers().GetFirstRenderer()
                                            if renderer:
                                                camera = renderer.GetActiveCamera()
                                        except Exception:
                                            renderer = None
                                            camera = None

                                        if renderer and camera:
                                            log_camera_geometry(
                                                tag="NEWMPR2",
                                                view_name=unified_view_name,
                                                camera=camera,
                                                renderer=renderer,
                                                xy_to_ras=xy_to_ras,
                                                ijk_to_ras=ijk_to_ras,
                                                ras_to_ijk=ras_to_ijk,
                                                view_dims_px=dims
                                            )
                                        else:
                                            write_log(f"[NEWMPR2-CAMERA view={unified_view_name}] WARNING: Renderer or camera unavailable")
                                            write_log("")
                                    except Exception as cam_err:
                                        write_log(f"[NEWMPR2-CAMERA view={unified_view_name}] ERROR: {cam_err}")
                                        write_log("")
                        
                        print("[AIPACS_STARTUP] [OK] Unified geometry logging completed")
                    
                    # Also log with orientation_logger if available (old format)
                    if _ORIENT_LOG_AVAILABLE:
                        orientation_log_volume_geometry(
                            "NEWMPR2",
                            primary_volume,
                            dicom_dir=args.get("dicom_dir") if args else None,
                            series_uid=args.get("series_uid") if args else None,
                        )

                        lm_delayed = slicer.app.layoutManager()
                        slice_nodes = []
                        for viewName in ["Red", "Yellow", "Green"]:
                            sliceWidget = lm_delayed.sliceWidget(viewName)
                            slice_node = None
                            if sliceWidget:
                                slice_node = sliceWidget.mrmlSliceNode()
                            slice_nodes.append((viewName, slice_node))

                        orientation_log_slice_nodes("NEWMPR2", slice_nodes)
                        print("[AIPACS_STARTUP] [OK] Legacy orientation logging completed")
                        
                except Exception as geom_err:
                    print(f"[AIPACS_STARTUP] Warning: geometry logging failed: {geom_err}")
                    import traceback
                    traceback.print_exc()

        # Delay logging by 500ms to ensure slice views are fully initialized
        try:
            import qt
            qt.QTimer.singleShot(500, _log_geometry_delayed)
        except Exception:
            # Fallback: log immediately if QTimer unavailable
            _log_geometry_delayed()

        
        # Enable 3D cursor (crosshair) with AI-PACS defaults
        try:
            crosshair_node = slicer.util.getNode("Crosshair")
            if crosshair_node:
                # Crosshair mode constants from vtkMRMLCrosshairNode.h:
                # ShowSmallIntersection = 6 (small basic + intersection)
                SHOW_SMALL_INTERSECTION = 6
                # Crosshair behavior: OffsetJumpSlice = 1 (jump slices - offset)
                OFFSET_JUMP_SLICE = 1
                
                crosshair_node.SetCrosshairMode(SHOW_SMALL_INTERSECTION)
                crosshair_node.SetCrosshairBehavior(OFFSET_JUMP_SLICE)
                crosshair_node.SetCrosshairColor(1.0, 0.0, 0.0)  # Red
                print("[AIPACS_CURSOR] 3D cursor line color set to red")
                print("[AIPACS_STARTUP] [OK] 3D cursor enabled (jump=offset, style=small+intersection, color=red)")
        except Exception as e:
            print(f"[AIPACS_STARTUP] Warning: Could not configure 3D cursor: {e}")
            
    except Exception as e:
        print(f"[AIPACS_STARTUP] Error configuring views: {e}")
        import traceback
        traceback.print_exc()


def apply_window_level_if_present(volume_node, args):
    """
    Apply window/level (contrast/brightness) to a volume's display node.
    
    This synchronizes the viewing state from the main NewMPR2 application.
    
    Args:
        volume_node: The volume node to apply settings to
        args: Parsed arguments dict with window_width and window_level
    """
    if volume_node is None:
        return
    
    window_width = args.get("window_width") if args else None
    window_level = args.get("window_level") if args else None
    
    # Skip if no window/level specified
    if window_width is None and window_level is None:
        print("[NewMPR2] No window/level specified, using defaults")
        return
    
    try:
        # Get the volume's display node
        display_node = volume_node.GetDisplayNode()
        if display_node is None:
            display_node = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScalarVolumeDisplayNode"
            )
            volume_node.SetAndObserveDisplayNodeID(display_node.GetID())
        
        # Get current values to report changes
        current_window = display_node.GetWindow()
        current_level = display_node.GetLevel()
        
        # Apply new values
        if window_width is not None:
            display_node.SetWindow(window_width)
            print(f"[NewMPR2] Window Width: {current_window} -> {window_width}")
        
        if window_level is not None:
            display_node.SetLevel(window_level)
            print(f"[NewMPR2] Window Level: {current_level} -> {window_level}")
        
        # Disable auto window/level so our values stick
        display_node.AutoWindowLevelOff()
        
        print(f"[NewMPR2] [OK] Window/Level synchronized from main application")
        
    except Exception as e:
        print(f"[NewMPR2] Error applying window/level: {e}")


def set_window_title(patient_id=None, study_id=None):
    """
    Update the window title with patient/study info.
    
    Args:
        patient_id: Optional patient ID
        study_id: Optional study ID
    """
    try:
        title = "AI-PACS Advanced Viewer v0.1"
        
        if patient_id or study_id:
            info_parts = []
            if patient_id:
                info_parts.append(f"Patient: {patient_id}")
            if study_id:
                info_parts.append(f"Study: {study_id}")
            title = f"{title} | {' | '.join(info_parts)}"
        
        main_window = slicer.util.mainWindow()
        if main_window:
            main_window.setWindowTitle(title)
            print(f"[NewMPR2Slicer] Window title set: {title}")
            
    except Exception as e:
        print(f"[NewMPR2Slicer] Error setting window title: {e}")


def store_patient_info(patient_id=None, study_id=None, window_width=None, window_level=None, series_uid=None):
    """
    Store patient/study info and viewing state in a MRML parameter node for modules to access.
    
    The NewMPR2MPR module reads this info to display in its UI.
    
    Args:
        patient_id: Optional patient ID from --patient-id
        study_id: Optional study ID from --study-id
        window_width: Optional window width from --window-width
        window_level: Optional window level from --window-level
        series_uid: Optional series UID from --series-uid
    """
    try:
        # Create or find the NewMPR2MPR parameter node
        parameterNode = None
        nodes = slicer.util.getNodesByClass("vtkMRMLScriptedModuleNode")
        for node in nodes:
            if node.GetAttribute("ModuleName") == "NewMPR2MPR":
                parameterNode = node
                break
        
        if not parameterNode:
            parameterNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLScriptedModuleNode"
            )
            parameterNode.SetAttribute("ModuleName", "NewMPR2MPR")
            parameterNode.SetName("NewMPR2MPRParameters")
        
        # Store the values
        if patient_id:
            parameterNode.SetParameter("PatientID", patient_id)
            print(f"[NewMPR2Slicer] Stored PatientID: {patient_id}")
        if study_id:
            parameterNode.SetParameter("StudyID", study_id)
            print(f"[NewMPR2Slicer] Stored StudyID: {study_id}")
        if window_width is not None:
            parameterNode.SetParameter("WindowWidth", str(window_width))
            print(f"[NewMPR2Slicer] Stored WindowWidth: {window_width}")
        if window_level is not None:
            parameterNode.SetParameter("WindowLevel", str(window_level))
            print(f"[NewMPR2Slicer] Stored WindowLevel: {window_level}")
        if series_uid:
            parameterNode.SetParameter("SeriesUID", series_uid)
            print(f"[NewMPR2Slicer] Stored SeriesUID: {series_uid}")
            
    except Exception as e:
        print(f"[NewMPR2Slicer] Error storing patient info: {e}")


def activate_mpr_module():
    """
    Activate the NewMPR2MPR module.
    
    =========================================================================
    UPDATED (2026-01-07 - STABLE BUILD):
    =========================================================================
    Module selection is now handled by C++ in setupUi() BEFORE the window
    is shown. This function now only logs confirmation that the module
    should already be active.
    
    We DO NOT call selectModule() from Python because:
    1. C++ already sets Modules/HomeModule to "NewMPR2MPR" in QSettings
    2. C++ explicitly calls selectModule("NewMPR2MPR") in setupUi()
    3. Calling it again from Python would cause unnecessary UI updates
    =========================================================================
    """
    module_name = "NewMPR2MPR"
    
    try:
        moduleManager = slicer.app.moduleManager()
        if moduleManager is None:
            print("[AIPACS_UI_PY] Warning: moduleManager is None")
            return
        
        # Check if module is loaded
        is_loaded = False
        if hasattr(moduleManager, "isModuleLoaded"):
            is_loaded = bool(moduleManager.isModuleLoaded(module_name))
        else:
            is_loaded = moduleManager.module(module_name) is not None
        
        if is_loaded:
            print(f"[AIPACS_UI_PY] [OK] Module '{module_name}' is loaded")
            print(f"[AIPACS_UI_PY] Module selection handled by C++ (no Python selectModule call)")
        else:
            print(f"[AIPACS_UI_PY] Warning: Module '{module_name}' is not loaded")
            print("[AIPACS_UI_PY] This is expected if the module hasn't been built yet.")
                    
    except Exception as e:
        print(f"[AIPACS_UI_PY] Warning: Could not check module status: {e}")


# ============================================================
# Main Startup Logic
# ============================================================

def bypass_welcome_and_dicom_browser():
    """
    Bypass the Welcome module and DICOM browser so user sees only the MPR viewer.
    
    =========================================================================
    UPDATED (2026-01-07 - STABLE BUILD):
    =========================================================================
    Module selection is now handled by C++ BEFORE the window is shown.
    C++ sets NewMPR2MPR as home module and explicitly selects it.
    
    This function now only:
    1. Disables persistent DICOM browser
    2. Closes any auto-opened DICOM dialogs
    
    NO Python selectModule() calls are made.
    =========================================================================
    """
    try:
        print("[AIPACS_UI_PY] Disabling DICOM browser auto-open...")
        
        # --- 1. Disable persistent DICOM browser ---
        try:
            settings = slicer.app.settings()
            settings.setValue("DICOM/BrowserPersistentVisible", False)
            settings.setValue("DICOM/AutoLoadPreferredOrder", False)
            print("[AIPACS_UI_PY] [OK] Disabled persistent DICOM browser")
        except Exception as e:
            print(f"[AIPACS_UI_PY] Warning: Could not update DICOM settings: {e}")
        
        # --- 2. Close DICOM browser if it auto-opened ---
        try:
            main_window = slicer.util.mainWindow()
            if main_window:
                # Find and close any DICOM browser dialogs/widgets
                for widget in main_window.findChildren(slicer.qt.QDialog):
                    widget_name = widget.objectName if hasattr(widget, 'objectName') else ''
                    if 'dicom' in widget_name.lower() or 'DICOM' in str(type(widget)):
                        widget.close()
                        print(f"[AIPACS_UI_PY] [OK] Closed DICOM dialog: {widget_name}")
        except Exception as e:
            print(f"[AIPACS_UI_PY] Warning: Could not close DICOM browser: {e}")
        
        # --- 3. Module selection handled by C++ ---
        # NO selectModule() calls from Python. C++ handles this.
        print("[AIPACS_UI_PY] [OK] Module selection handled by C++ (no Python selectModule)")
        
    except Exception as e:
        print(f"[AIPACS_UI_PY] Warning: bypass_welcome_and_dicom_browser failed: {e}")


def load_custom_stylesheet():
    """
    Load the custom AI-PACS stylesheet from the branding folder.
    
    =========================================================================
    DEPRECATED (2026-01-06):
    =========================================================================
    This function is now DEPRECATED. The QSS stylesheet is now:
    1. Embedded in the app resources (App.qrc -> Styles/AIPacsTheme.qss)
    2. Loaded by C++ in Main.cxx BEFORE the window is shown
    
    This eliminates the "light to dark flash" that occurred when Python
    applied the QSS after the window was already visible.
    
    This function is kept for backwards compatibility but will return early
    without doing anything. The QSS is already applied by C++.
    =========================================================================
    """
    print("[AIPACS_UI_PY] load_custom_stylesheet() called but stylesheet is handled by C++")
    print("[AIPACS_UI_PY] QSS is embedded in app resources and loaded before window show")
    return True  # Return success - stylesheet is already applied by C++


def run_startup():
    """
    Main startup function that configures Slicer for NewMPR2.
    
    This is the entry point called after Slicer is fully initialized.
    Reads configuration from environment variables and configures Slicer
    to act as an advanced MPR viewer.
    
    =========================================================================
    ARCHITECTURE NOTE (v1.1.1 - 2026-01-07):
    =========================================================================
    ALL UI THEMING AND LAYOUT IS HANDLED BY C++ BEFORE WINDOW IS SHOWN.
    
    This function handles ONLY DATA LOGIC:
    - Loading the correct DICOM series
    - Setting up MPR layout and views
    - Applying window/level from parameters
    - Activating NewMPR2MPR module
    - Setting window title with patient info
    
    CRITICAL: NO UI MANIPULATION IS DONE HERE.
    - NO toolbar hiding/moving
    - NO window resize
    - NO slice color changes
    - NO QTimer delayed UI calls
    
    This ensures ZERO flash between first frame and final state.
    =========================================================================
    """
    try:
        print("[AIPACS_UI_PY] ========================================")
        print("[AIPACS_UI_PY] Starting NewMPR2 Runtime Configuration")
        print("[AIPACS_UI_PY] DATA-ONLY MODE (no UI manipulation)")
        print("[AIPACS_UI_PY] ========================================")
        
        # Parse arguments from environment variables
        args = parse_newmpr2_args()
        
        # Log incoming args
        print("[AIPACS_UI_PY] Incoming configuration:")
        for key, value in args.items():
            print(f"[AIPACS_UI_PY]   {key}: {value}")
        
        # --- STEP 1: Load DICOM series ---
        primary_volume = None
        if args.get("dicom_dir"):
            print(f"[AIPACS_UI_PY] Loading DICOM from: {args['dicom_dir']}")
            print(f"[AIPACS_UI_PY] Series UID to load: {args.get('series_uid', 'NOT SPECIFIED')}")
            try:
                primary_volume = load_dicom_folder(
                    args["dicom_dir"],
                    series_uid=args.get("series_uid")
                )
                if primary_volume:
                    print(f"[AIPACS_UI_PY] [OK] Primary volume loaded: {primary_volume.GetName()}")
                    print(f"[AIPACS_UI_PY]   Volume ID: {primary_volume.GetID()}")
                    print(f"[AIPACS_UI_PY]   Volume Class: {primary_volume.GetClassName()}")
                else:
                    print("[AIPACS_UI_PY] [FAIL] No volume loaded from DICOM folder")
            except Exception as e:
                print(f"[AIPACS_UI_PY] [FAIL] DICOM loading failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("[AIPACS_UI_PY] No DICOM directory specified, opening empty viewer")
        
        # --- STEP 2: Configure views (set layout, background volume, fit slices) ---
        try:
            configure_views(args.get("layout", "mpr"), primary_volume, args)
            print("[AIPACS_UI_PY] [OK] Views configured")
        except Exception as e:
            print(f"[AIPACS_UI_PY] Warning: View configuration failed: {e}")
        
        # --- STEP 3: Apply window/level if present ---
        try:
            apply_window_level_if_present(primary_volume, args)
        except Exception as e:
            print(f"[AIPACS_UI_PY] Warning: Window/level application failed: {e}")
        
        # --- STEP 4: Activate NewMPR2MPR module ---
        try:
            activate_mpr_module()
        except Exception as e:
            print(f"[AIPACS_UI_PY] Warning: Could not activate MPR module: {e}")
        
        # --- STEP 5: Set window title ---
        try:
            set_window_title(
                patient_id=args.get("patient_id"),
                study_id=args.get("study_id")
            )
            print("[AIPACS_UI_PY] [OK] Window title set")
        except Exception as e:
            print(f"[AIPACS_UI_PY] Warning: Could not set window title: {e}")
        
        # =====================================================================
        # NO UI MANIPULATION BELOW THIS POINT
        # =====================================================================
        # The following are INTENTIONALLY SKIPPED to prevent flash:
        # - customize_ui_for_advanced_viewer() -> C++ handles toolbars
        # - neutralize_slice_node_colors() -> Accept default colors (no flash)
        # - configure_main_window_geometry() -> C++ handles via env vars
        # - QTimer delayed calls -> Cause flash, not needed
        # =====================================================================
        
        print("")
        print("[AIPACS_UI_PY] " + "=" * 60)
        print("[AIPACS_UI_PY] STARTUP SEQUENCE COMPLETED SUCCESSFULLY")
        print("[AIPACS_UI_PY] (Data-only mode, no UI manipulation)")
        print("[AIPACS_UI_PY] " + "=" * 60)
        print("")
        
    except Exception as e:
        print("")
        print("[AIPACS_UI_PY] " + "=" * 60)
        print(f"[AIPACS_UI_PY] STARTUP FAILED: {e}")
        print("[AIPACS_UI_PY] " + "=" * 60)
        import traceback
        traceback.print_exc()
        print("")


def _customize_module_toolbar_for_aipacs(main_window):
    """
    AI-PACS Customization: Style the Modules toolbar for a modern AI-PACS look.
    
    Visual styling only, does not change any behavior.
    
    Changes:
    - Taller toolbar (min-height 40px)
    - Larger, clearer fonts for "Modules:" label
    - Modern combo-box styling (padding, border radius)
    - Consistent AI-PACS dark theme colors
    """
    import qt
    
    print("[AIPACS_UI] === Customizing Module Toolbar ===")
    
    # Find the module selector toolbar (ModuleSelectorToolBar or similar)
    module_tb = None
    
    # Try known names first
    for tb_name in ["ModuleSelectorToolBar", "ModuleToolBar", "FavoriteModulesToolBar"]:
        module_tb = main_window.findChild(qt.QToolBar, tb_name)
        if module_tb:
            print(f"[AIPACS_UI] Found module toolbar: {tb_name}")
            break
    
    # Fallback: search for toolbar containing module selector combo
    if not module_tb:
        for tb in main_window.findChildren(qt.QToolBar):
            combo = tb.findChild(qt.QComboBox)
            if combo:
                # Check if this looks like a module selector
                if combo.count() > 10:  # Module selector has many modules
                    module_tb = tb
                    print(f"[AIPACS_UI] Found module toolbar via combo search: {tb.objectName}")
                    break
    
    if not module_tb:
        print("[AIPACS_UI] Module toolbar not found - skipping customization")
        return False
    
    try:
        # Set recognizable object name for QSS targeting
        module_tb.setObjectName("AIPacsModuleToolbar")
        module_tb.setProperty("class", "aipacs-module-toolbar")
        
        # Make the toolbar taller and add padding
        module_tb.setMinimumHeight(44)
        module_tb.setIconSize(qt.QSize(24, 24))
        module_tb.setContentsMargins(8, 4, 8, 4)
        
        # Adjust layout spacing if possible
        if module_tb.layout():
            module_tb.layout().setSpacing(8)
        
        print("[AIPACS_UI] [OK] Module toolbar sized and styled")
        
        # Find and style the "Modules:" label
        labels = module_tb.findChildren(qt.QLabel)
        module_label = None
        for label in labels:
            text = label.text if hasattr(label, 'text') else ""
            if callable(text):
                text = text()
            if "module" in text.lower() or text == "":
                module_label = label
                break
        
        if module_label:
            module_label.setObjectName("AIPacsModuleLabel")
            module_label.setProperty("class", "aipacs-module-label")
            # Keep original text but ensure visibility
            if not module_label.text:
                module_label.setText("Modules")
            print(f"[AIPACS_UI] [OK] Styled module label: '{module_label.text}'")
        else:
            print("[AIPACS_UI] Module label not found in toolbar")
        
        # Find and style the module combo box
        combo = module_tb.findChild(qt.QComboBox)
        if combo:
            combo.setObjectName("AIPacsModuleCombo")
            combo.setProperty("class", "aipacs-module-combo")
            combo.setMinimumHeight(30)
            combo.setMinimumWidth(200)
            print("[AIPACS_UI] [OK] Styled module combo box")
        else:
            print("[AIPACS_UI] Module combo box not found")
        
        # Style any tool buttons in the toolbar
        for btn in module_tb.findChildren(qt.QToolButton):
            btn.setProperty("class", "aipacs-module-toolbar-button")
        
        print("[AIPACS_UI] [OK] Module toolbar customization complete")
        return True
        
    except Exception as e:
        print(f"[AIPACS_UI] Error customizing module toolbar: {e}")
        import traceback
        traceback.print_exc()
        return False


def _hide_crosshair_selection_toolbar(main_window):
    """
    Hide the Crosshair Selection toolbar from the top toolbar area.
    
    The 3D cursor controls are now in the NewMPR2MPR side panel ("3D Cursor" section),
    so we hide the top toolbar to avoid duplicate controls.
    
    Also removes/disables its action from the toolbar visibility menu.
    """
    import qt
    
    print("[AIPACS_UI] === Hiding Crosshair Selection toolbar ===")
    
    # Find the ViewersToolBar / Crosshair Selection toolbar
    crosshair_toolbar = None
    crosshair_action = None
    
    for tb in main_window.findChildren(qt.QToolBar):
        tb_name = tb.objectName if hasattr(tb, 'objectName') else ""
        if callable(tb_name):
            tb_name = tb_name()
        tb_title = tb.windowTitle if hasattr(tb, 'windowTitle') else ""
        if callable(tb_title):
            tb_title = tb_title()
        
        # Check for Crosshair Selection or ViewersToolBar
        if "crosshair" in tb_title.lower() or "crosshair" in tb_name.lower() or \
           "viewers" in tb_name.lower():
            crosshair_toolbar = tb
            print(f"[AIPACS_UI] Found Crosshair toolbar: {tb_name} - '{tb_title}'")
            break
    
    if crosshair_toolbar:
        # Hide the toolbar
        crosshair_toolbar.setVisible(False)
        print(f"[AIPACS_UI] [OK] Hidden Crosshair Selection toolbar")
        
        # Remove the toolbar from main window
        main_window.removeToolBar(crosshair_toolbar)
        print(f"[AIPACS_UI] [OK] Removed Crosshair Selection toolbar from main window")
        
        # Try to find and disable its toggle action
        tb_name = crosshair_toolbar.objectName()
        action_name = f"{tb_name}ToggleViewAction"
        crosshair_action = main_window.findChild(qt.QAction, action_name)
        if crosshair_action:
            crosshair_action.setEnabled(False)
            crosshair_action.setVisible(False)
            print(f"[AIPACS_UI] [OK] Disabled toolbar toggle action: {action_name}")
    else:
        print("[AIPACS_UI] Crosshair Selection toolbar not found")


def _hide_add_data_section(main_window):
    """
    Hide the 'Add Data' collapsible section above 'Help & Acknowledgement'.
    
    In AI-PACS Advanced Viewer, we do not allow import/export from this panel.
    The user should use the main AI-PACS application for data management.
    
    This searches in:
    1. PanelDockWidget (main module panel)
    2. All QScrollArea children
    3. Any ctkCollapsibleButton with "Add Data" or "IO" or "Load" text
    """
    import qt
    
    print("[AIPACS_UI] === Hiding Add Data section in module panel ===")
    
    # Find any dock widget that might contain the module panel
    module_panel = None
    for dock_name in ["PanelDockWidget", "ModulePanelDockWidget", "ModulePanel"]:
        module_panel = main_window.findChild(qt.QDockWidget, dock_name)
        if module_panel:
            print(f"[AIPACS_UI] Found module panel dock: {dock_name}")
            break
    
    if not module_panel:
        # Try to find any dock with "panel" or "module" in name
        for dock in main_window.findChildren(qt.QDockWidget):
            dock_name = dock.objectName() if hasattr(dock, 'objectName') else ""
            if "panel" in dock_name.lower() or "module" in dock_name.lower():
                module_panel = dock
                print(f"[AIPACS_UI] Using fallback module panel dock: {dock_name}")
                break
    
    if not module_panel:
        print("[AIPACS_UI] Module panel dock not found - listing all docks:")
        for dock in main_window.findChildren(qt.QDockWidget):
            print(f"[AIPACS_UI]   Dock: {dock.objectName()}")
        return
    
    # Try to find ctkCollapsibleButton widgets
    try:
        import ctk
        
        found_add_data = False
        
        # Search for collapsible buttons with Add Data / IO / Load text
        # Search in module_panel and all its children recursively
        all_collapsibles = module_panel.findChildren(ctk.ctkCollapsibleButton)
        print(f"[AIPACS_UI] Found {len(all_collapsibles)} ctkCollapsibleButton(s)")
        
        for cb in all_collapsibles:
            cb_text = cb.text if hasattr(cb, 'text') else ""
            if callable(cb_text):
                cb_text = cb_text()
            cb_text_lower = cb_text.lower() if cb_text else ""
            
            print(f"[AIPACS_UI] Checking collapsible: '{cb_text}'")
            
            # Check if this is the Add Data section (various possible names)
            # NOTE: Avoid short keywords like "io" that can match unintended words (e.g. "selection")
            # Use exact matches or longer, more specific keywords
            add_data_keywords = ["add data", "load data", "import data", "data io", "dicom", "sample data"]
            is_add_data_section = any(keyword in cb_text_lower for keyword in add_data_keywords)
            
            # Skip our own Crossline Selection section
            if "crossline" in cb_text_lower:
                print(f"[AIPACS_UI] Skipping Crossline Selection section (protected)")
                continue
            
            if is_add_data_section:
                cb.setVisible(False)
                cb.hide()
                # Also try to remove from layout
                parent = cb.parentWidget()
                if parent and parent.layout():
                    parent.layout().removeWidget(cb)
                found_add_data = True
                print(f"[AIPACS_UI] [OK] Hidden Add Data collapsible: '{cb_text}'")
        
        # Also search in the main window directly
        if not found_add_data:
            all_main_collapsibles = main_window.findChildren(ctk.ctkCollapsibleButton)
            print(f"[AIPACS_UI] Searching {len(all_main_collapsibles)} collapsibles in main window")
            
            for cb in all_main_collapsibles:
                cb_text = cb.text if hasattr(cb, 'text') else ""
                if callable(cb_text):
                    cb_text = cb_text()
                cb_text_lower = cb_text.lower() if cb_text else ""
                
                if any(keyword in cb_text_lower for keyword in ["add data", "load data"]):
                    cb.setVisible(False)
                    cb.hide()
                    found_add_data = True
                    print(f"[AIPACS_UI] [OK] Hidden Add Data from main window: '{cb_text}'")
        
        if not found_add_data:
            print("[AIPACS_UI] 'Add Data' collapsible not found - may not exist in this module")
            
    except ImportError:
        print("[AIPACS_UI] ctk module not available - cannot search for collapsible buttons")
    except Exception as e:
        print(f"[AIPACS_UI] Error searching for Add Data section: {e}")
        import traceback
        traceback.print_exc()


def customize_ui_for_advanced_viewer():
    """
    Customize the Slicer UI to look like an advanced NewMPR2 viewer.
    
    =========================================================================
    STABLE BUILD (2026-01-07):
    =========================================================================
    ALL UI CUSTOMIZATION IS NOW HANDLED IN C++ BEFORE WINDOW IS SHOWN:
    
    - qNewMPR2SlicerAppMainWindow.cxx:
      - Sets window size from env vars (NEWMPR2_VIEWPORT_WIDTH/HEIGHT)
      - Centers window on screen
      - Hides status bar
      - Keeps ModuleSelectorToolBar visible, hides all other toolbars
      - Sets empty title bar (no logo)
      - Sets default module to NewMPR2MPR
      - Sets default layout to FourUpView
    
    - Main.cxx:
      - Loads AIPacsTheme.qss dark theme
      - Applies dark palette via qAppStyle
    
    This function is now a NO-OP to ensure:
    - No flash between first frame and final state
    - No toolbar relocation or visibility changes from Python
    - No QTimer delayed UI manipulation
    
    Python is DATA-ONLY: Load DICOM, set WL, configure views.
    =========================================================================
    """
    print("[AIPACS_UI_PY] UI: All customization handled by C++ (no changes)")
    print("[AIPACS_UI_PY] UI: Theme, toolbars, layout, geometry -> C++")
    print("[AIPACS_UI_PY] UI: This function is now a NO-OP")


# ============================================================
# Entry Point - Called when Slicer runs this script via --python-script
# ============================================================

def main():
    """
    Main entry point for the startup script.
    
    This function is called after Slicer is fully initialized.
    
    =========================================================================
    ARCHITECTURE NOTE (2026-01-06):
    =========================================================================
    UI theming, logo removal, and dark theme are now handled in C++/QSS:
    - qAppStyle.cxx: Dark palette matching NewMPR2Slicer.qss colors
    - Main.cxx: Loads embedded AIPacsTheme.qss before window show
    - qNewMPR2SlicerAppMainWindow.cxx: Empty title bar (no logo)
    
    Python is now only responsible for RUNTIME LOGIC:
    - Reading launch parameters from environment variables
    - Loading the correct DICOM series
    - Configuring MPR layout and views
    - Setting window/level from parameters
    - Activating NewMPR2MPR module
    - Setting window title with patient info
    =========================================================================
    """
    print("[AIPACS_UI_PY] ========================================")
    print("[AIPACS_UI_PY] startup_script.py main() called")
    print("[AIPACS_UI_PY] UI theme and logo handled by C++/QSS")
    print("[AIPACS_UI_PY] Python handles runtime data logic only")
    print("[AIPACS_UI_PY] ========================================")
    
    # --- NOTE: Theming is now handled in C++ ---
    # The following calls are no longer needed because:
    # - load_custom_stylesheet(): QSS is embedded in app resources and loaded in Main.cxx
    # - apply_immediate_branding(): App name/title set in Main.cxx, logo removed in setupUi
    # - remove_panel_logo(): Logo is no longer added in C++ (empty title bar widget)
    
    # --- IMMEDIATE: Suppress Welcome module early ---
    # This is still needed because Welcome module selection is a Slicer default behavior
    try:
        suppress_welcome_module_early()
    except Exception as e:
        print(f"[AIPACS_UI_PY] Warning: suppress_welcome_module_early() failed: {e}")
    
    # --- DELAYED: Full startup configuration (DICOM loading, layout, etc.) ---
    # Reduced delay since no UI styling is needed anymore
    try:
        import qt
        try:
            start_remote_command_server()
        except Exception as server_error:
            print(f"[AIPACS_REMOTE] Warning: Could not start remote server: {server_error}")

        print("[AIPACS_UI_PY] Scheduling run_startup() in 300ms via QTimer...")
        sys.stdout.flush()
        sys.stderr.flush()
        qt.QTimer.singleShot(300, run_startup)
        print("[AIPACS_UI_PY] [OK] Scheduled run_startup() in 300ms")
        sys.stdout.flush()
    except Exception as e:
        print(f"[AIPACS_UI_PY] [FAIL] Error scheduling startup with QTimer: {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
        # Fallback: try running directly (might cause issues)
        try:
            print("[AIPACS_UI_PY] Attempting fallback: running startup directly...")
            sys.stdout.flush()
            run_startup()
        except Exception as e2:
            print(f"[AIPACS_UI_PY] [FAIL] Direct run_startup() also failed: {e2}")
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()


# ============================================================
# Script execution when loaded by Slicer
# ============================================================

if RUNNING_IN_SLICER:
    # When loaded via --python-script, __name__ is "__main__" or sometimes just the module
    print("")
    print("[AIPACS_STARTUP] " + "=" * 60)
    print("[AIPACS_STARTUP] startup_script.py EXECUTED INSIDE SLICER")
    print("[AIPACS_STARTUP] " + "=" * 60)
    print(f"[AIPACS_STARTUP] __name__ = {__name__}")
    print(f"[AIPACS_STARTUP] dicom_dir = {os.environ.get('NEWMPR2_DICOM_DIR', 'NOT SET')}")
    print(f"[AIPACS_STARTUP] layout = {os.environ.get('NEWMPR2_LAYOUT', 'NOT SET')}")
    print(f"[AIPACS_STARTUP] window_width = {os.environ.get('NEWMPR2_WINDOW_WIDTH', 'NOT SET')}")
    print(f"[AIPACS_STARTUP] window_level = {os.environ.get('NEWMPR2_WINDOW_LEVEL', 'NOT SET')}")
    print(f"[AIPACS_STARTUP] series_uid = {os.environ.get('NEWMPR2_SERIES_UID', 'NOT SET')}")
    print("[AIPACS_STARTUP] " + "=" * 60)
    print("")
    sys.stdout.flush()
    sys.stderr.flush()
    
    # Call main() to start the configuration process
    try:
        main()
    except Exception as e:
        print(f"[AIPACS_STARTUP] FATAL ERROR in main(): {e}")
        import traceback
        traceback.print_exc()
        sys.stdout.flush()
        sys.stderr.flush()
else:
    print("")
    print("[AIPACS_STARTUP] " + "=" * 60)
    print("[AIPACS_STARTUP] NOT running inside Slicer - script not executed")
    print("[AIPACS_STARTUP] " + "=" * 60)
    print("[AIPACS_STARTUP] To use this script:")
    print("[AIPACS_STARTUP]   Slicer.exe --no-splash --python-script startup_script.py")
    print("[AIPACS_STARTUP] " + "=" * 60)
    print("")
    sys.stdout.flush()
    sys.stderr.flush()
