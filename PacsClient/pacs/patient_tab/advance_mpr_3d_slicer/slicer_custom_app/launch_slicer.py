#!/usr/bin/env python3
"""
NewMPR2Slicer Launcher Script

This script launches the custom 3D Slicer application (NewMPR2Slicer) with parameters
defined in the launch contract (see docs/launch_contract.md).

Usage:
    python launch_slicer.py --dicom-dir <path> [--layout <name>] [--patient-id <id>] [--study-id <id>]

The script will:
1. Validate input arguments per the launch contract
2. Locate the NewMPR2Slicer executable in the build directory
3. Launch it with the specified arguments
4. Optionally wait for the Slicer process to complete

See docs/launch_contract.md for the full specification.
"""

import argparse
import os
import sys
import subprocess
import tempfile
import atexit
from pathlib import Path
from typing import Optional, List
from datetime import datetime


# ============================================================
# Early Branding via .slicerrc.py
# ============================================================

# Content for the temporary .slicerrc.py file - DISABLED due to encoding issues
# The --python-script startup_script.py handles all branding now
SLICERRC_BRANDING_CONTENT = '# AI-PACS branding handled by startup_script.py\npass\n'

# Global variable to track temporary slicerrc file
_temp_slicerrc_path = None
_original_slicerrc_content = None
_original_slicerrc_existed = False


def setup_early_branding_slicerrc():
    """
    Create or modify the user's .slicerrc.py to apply branding during Slicer's
    early initialization phase.
    
    This runs BEFORE --python-script or --python-code, during Slicer's startup.
    
    Returns:
        Path to the user's home directory slicerrc file (for cleanup)
    """
    global _temp_slicerrc_path, _original_slicerrc_content, _original_slicerrc_existed
    
    home_dir = Path.home()
    slicerrc_path = home_dir / ".slicerrc.py"
    
    try:
        # Save original state
        if slicerrc_path.exists():
            _original_slicerrc_existed = True
            # Use utf-8-sig to handle BOM if present
            _original_slicerrc_content = slicerrc_path.read_text(encoding='utf-8-sig')
            
            # Check if already has our branding
            if "AI-PACS" in _original_slicerrc_content or "Ai-Pacs" in _original_slicerrc_content:
                print("[NewMPR2Slicer] .slicerrc.py already has branding")
                return slicerrc_path
            
            # Prepend our branding to existing content
            new_content = SLICERRC_BRANDING_CONTENT + "\n\n# Original slicerrc content below:\n" + _original_slicerrc_content
        else:
            _original_slicerrc_existed = False
            new_content = SLICERRC_BRANDING_CONTENT
        
        # Write the branding slicerrc WITHOUT BOM (pure utf-8)
        slicerrc_path.write_text(new_content, encoding='utf-8')
        _temp_slicerrc_path = slicerrc_path
        
        print(f"[NewMPR2Slicer] [OK] Created early branding .slicerrc.py at {slicerrc_path}")
        
        return slicerrc_path
        
    except Exception as e:
        print(f"[NewMPR2Slicer] Warning: Could not create .slicerrc.py: {e}")
        return None


def cleanup_early_branding_slicerrc():
    """
    Restore the original .slicerrc.py state after Slicer has launched.
    """
    global _temp_slicerrc_path, _original_slicerrc_content, _original_slicerrc_existed
    
    if _temp_slicerrc_path is None:
        return
    
    try:
        if _original_slicerrc_existed and _original_slicerrc_content is not None:
            # Restore original content
            _temp_slicerrc_path.write_text(_original_slicerrc_content, encoding='utf-8')
            print(f"[NewMPR2Slicer] [OK] Restored original .slicerrc.py")
        else:
            # Remove the file we created
            if _temp_slicerrc_path.exists():
                _temp_slicerrc_path.unlink()
                print(f"[NewMPR2Slicer] [OK] Removed temporary .slicerrc.py")
    except Exception as e:
        print(f"[NewMPR2Slicer] Warning: Could not cleanup .slicerrc.py: {e}")
    
    _temp_slicerrc_path = None
    _original_slicerrc_content = None
    _original_slicerrc_existed = False


# ============================================================
# Configuration - Matches launch_contract.md
# ============================================================

# Default layout when --layout is not specified
DEFAULT_LAYOUT = "mpr"

# Valid layout names (as defined in launch_contract.md)
VALID_LAYOUTS = {
    "mpr",          # Four-up view (default)
    "fourup",       # Alias for mpr
    "axial",        # Single axial view
    "sagittal",     # Single sagittal view
    "coronal",      # Single coronal view
    "threeD",       # Single 3D view
    "conventional", # Conventional Slicer layout
    "dualthreeD",   # Two 3D views
}


def _resolve_qt_bin_dir() -> Optional[Path]:
    """Resolve Qt bin directory from environment in a machine-independent way."""
    candidates = []

    # Direct bin dir overrides
    for env_key in ("AIPACS_QT_BIN", "QT_BIN_DIR"):
        value = os.getenv(env_key)
        if value:
            candidates.append(Path(value))

    # QTDIR usually points to Qt root (contains bin)
    qtdir = os.getenv("QTDIR")
    if qtdir:
        candidates.append(Path(qtdir) / "bin")

    # Qt5_DIR may point to .../lib/cmake/Qt5, convert back to bin
    qt5_dir = os.getenv("Qt5_DIR") or os.getenv("QT5_DIR")
    if qt5_dir:
        qt5_path = Path(qt5_dir)
        candidates.append(qt5_path.parent.parent / "bin")

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except Exception:
            resolved = candidate.expanduser()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            return resolved

    return None


def find_slicer_executable(prefer_custom: bool = True) -> Optional[Path]:
    """
    Locate the AIPacsAdvancedViewer.exe custom application LAUNCHER.
    
    IMPORTANT: This function ONLY accepts the custom AI-PACS Advanced Viewer.
    Stock Slicer.exe is NEVER used as a fallback.
    
    NOTE: The launcher executable (at the root of Slicer-build) should be used,
    NOT the direct executable in bin/Release. The launcher sets up proper DLL paths
    and Python environment using the LauncherSettings.ini file.
    
    If the custom app is not found, this function returns None and the caller
    must handle the error appropriately (show error message, exit with non-zero).
    
    Returns:
        Path to AIPacsAdvancedViewer.exe launcher, or None if not found (FATAL error)
    """
    # Get the directory containing this script
    script_dir = Path(__file__).parent.resolve()
    
    print(f"[AIPACS_LAUNCH] Searching for AIPacsAdvancedViewer.exe...")
    print(f"[AIPACS_LAUNCH] Script directory: {script_dir}")
    
    # ============================================================
    # PRIORITY 1: Launcher discovery (environment + local/sibling builds)
    # ============================================================
    candidate_launchers = []

    env_exe = os.getenv("AIPACS_ADVANCED_VIEWER_EXE")
    if env_exe:
        candidate_launchers.append(Path(env_exe))

    env_build = os.getenv("AIPACS_SLICER_BUILD_DIR")
    if env_build:
        candidate_launchers.append(Path(env_build) / "AIPacsAdvancedViewer.exe")

    candidate_launchers.extend([
        script_dir / "NewMPR2Slicer" / "build" / "AIPacsAdvancedViewer.exe",
        script_dir / "Slicer-build" / "AIPacsAdvancedViewer.exe",
        script_dir.parent / "Slicer-build" / "AIPacsAdvancedViewer.exe",
        Path.cwd() / "Slicer-build" / "AIPacsAdvancedViewer.exe",
    ])

    seen = set()
    for launcher in candidate_launchers:
        try:
            resolved = launcher.expanduser().resolve()
        except Exception:
            resolved = launcher.expanduser()

        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)

        if resolved.exists() and resolved.is_file():
            print(f"[AIPACS_LAUNCH] [OK] Found launcher: {resolved}")
            print(f"[AIPACS_LAUNCH] Selected executable: {resolved}")
            print(f"[AIPACS_LAUNCH] IsCustomApp: {resolved.name.lower().startswith('aipacsadvancedviewer')}")
            return resolved
    
    # ============================================================
    # FALLBACK: Direct executable (requires manual DLL setup)
    # ============================================================
    # NO FALLBACK TO STOCK SLICER - if custom app is not built, we fail loudly.
    
    # Possible locations for the built AI-PACS Advanced Viewer executable
    custom_app_paths = [
        # Direct executables (require DLLs to be in same folder or PATH)
        script_dir / "NewMPR2Slicer" / "build" / "bin" / "AIPacsAdvancedViewer.exe",
        script_dir / "NewMPR2Slicer" / "build" / "bin" / "Release" / "AIPacsAdvancedViewer.exe",
        script_dir / "NewMPR2Slicer" / "build" / "bin" / "Debug" / "AIPacsAdvancedViewer.exe",
        # Linux/macOS (no extension)
        script_dir / "NewMPR2Slicer" / "build" / "bin" / "AIPacsAdvancedViewer",
    ]
    
    for path in custom_app_paths:
        if path.exists() and path.is_file():
            print(f"[AIPACS_LAUNCH] [WARNING] Using direct executable (no launcher): {path}")
            print(f"[AIPACS_LAUNCH] [WARNING] DLLs must be in PATH or same directory")
            return path
    
    # If not found in predefined paths, search recursively in build directory
    build_dir = script_dir / "NewMPR2Slicer" / "build"
    if build_dir.exists():
        print(f"[AIPACS_LAUNCH] Searching build directory: {build_dir}")
        # Windows
        for exe_path in build_dir.rglob("AIPacsAdvancedViewer*.exe"):
            if exe_path.is_file():
                print(f"[AIPACS_LAUNCH] [OK] Found AIPacsAdvancedViewer (search): {exe_path}")
                return exe_path
        # Linux/macOS (no extension)
        for exe_path in build_dir.rglob("AIPacsAdvancedViewer"):
            if exe_path.is_file() and os.access(exe_path, os.X_OK):
                print(f"[AIPACS_LAUNCH] [OK] Found AIPacsAdvancedViewer (search): {exe_path}")
                return exe_path
    
    # ========================================================================
    # CUSTOM APP NOT FOUND - FATAL ERROR (NO FALLBACK TO STOCK SLICER)
    # ========================================================================
    expected_path = script_dir / 'NewMPR2Slicer' / 'build' / 'bin' / 'AIPacsAdvancedViewer.exe'
    error_file = script_dir / 'NewMPR2Slicer' / 'build' / 'bin' / 'AIPACS_LAUNCH_ERROR.txt'
    
    print("")
    print("[AIPACS_LAUNCH] " + "=" * 70)
    print("[AIPACS_LAUNCH] FATAL: AIPacsAdvancedViewer.exe NOT FOUND!")
    print("[AIPACS_LAUNCH] " + "=" * 70)
    print(f"[AIPACS_LAUNCH] Expected location:")
    print(f"[AIPACS_LAUNCH]   {expected_path}")
    print("[AIPACS_LAUNCH] ")
    print("[AIPACS_LAUNCH] The custom AI-PACS Advanced Viewer has NOT been built.")
    print("[AIPACS_LAUNCH] Stock Slicer.exe is NOT used as a fallback.")
    print("[AIPACS_LAUNCH] ")
    print("[AIPACS_LAUNCH] To build it, run these steps:")
    print("[AIPACS_LAUNCH]   1. Open Developer Command Prompt for VS 2022")
    print(f"[AIPACS_LAUNCH]   2. cd {script_dir / 'NewMPR2Slicer'}")
    print("[AIPACS_LAUNCH]   3. mkdir build && cd build")
    print("[AIPACS_LAUNCH]   4. cmake -G \"Visual Studio 17 2022\" -A x64 -DQt5_DIR=\"<path-to-Qt5-cmake-dir>\" ..")
    print("[AIPACS_LAUNCH]   5. cmake --build . --config Release")
    print("[AIPACS_LAUNCH] ")
    print("[AIPACS_LAUNCH] After build, verify:")
    print(f"[AIPACS_LAUNCH]   {expected_path} exists")
    print("[AIPACS_LAUNCH] " + "=" * 70)
    print("")
    
    # Create error file with instructions
    try:
        error_file.parent.mkdir(parents=True, exist_ok=True)
        error_file.write_text(f"""AIPACS_LAUNCH_ERROR
===================

AIPacsAdvancedViewer.exe NOT FOUND!

Expected location:
  {expected_path}

The custom AI-PACS Advanced Viewer has NOT been built.
Stock Slicer.exe is NOT used as a fallback.

To build it, run these steps:
  1. Open Developer Command Prompt for VS 2022
  2. cd {script_dir / 'NewMPR2Slicer'}
  3. mkdir build && cd build
    4. cmake -G "Visual Studio 17 2022" -A x64 -DQt5_DIR="<path-to-Qt5-cmake-dir>" ..
  5. cmake --build . --config Release

After build, verify:
  {expected_path} exists
""", encoding='utf-8')
        print(f"[AIPACS_LAUNCH] Error instructions written to: {error_file}")
    except Exception as e:
        print(f"[AIPACS_LAUNCH] Could not write error file: {e}")
    
    # Return None - caller must handle this as a fatal error
    return None


def get_startup_script_path() -> Optional[Path]:
    """
    Get the absolute path to startup_script.py.
    
    Returns:
        Path to the startup script, or None if not found
    """
    script_dir = Path(__file__).parent.resolve()
    startup_script = script_dir / "startup_script.py"
    
    if startup_script.exists():
        print(f"[NewMPR2Slicer] [OK] Startup script found: {startup_script}")
        return startup_script
    else:
        print(f"[NewMPR2Slicer] [FAIL] ERROR: Startup script NOT found at: {startup_script}")
        return None


def validate_layout(layout: str) -> str:
    """
    Validate and normalize the layout name.
    
    Args:
        layout: The layout name to validate
        
    Returns:
        Validated layout name (lowercase), or DEFAULT_LAYOUT if invalid
    """
    layout_lower = layout.lower()
    if layout_lower in VALID_LAYOUTS:
        return layout_lower
    
    # Special case: case-insensitive matching
    for valid in VALID_LAYOUTS:
        if valid.lower() == layout_lower:
            return valid
    
    print(f"Warning: Unrecognized layout '{layout}', using default '{DEFAULT_LAYOUT}'", 
          file=sys.stderr)
    return DEFAULT_LAYOUT


def build_slicer_command(
    slicer_exe: Path,
    dicom_dir: Path,
    layout: str,
    patient_id: Optional[str] = None,
    study_id: Optional[str] = None,
    window_width: Optional[float] = None,
    window_level: Optional[float] = None,
    series_uid: Optional[str] = None,
    no_splash: bool = False,
    auto_center: bool = True,
    software_rendering: bool = False,
) -> List[str]:
    """
    Build the command line for launching NewMPR2Slicer with our startup script.
    
    IMPORTANT: This ALWAYS includes --python-script pointing to startup_script.py
    which handles:
      - Loading DICOM data from the specified directory
      - Setting the MPR layout
      - Bypassing Welcome/DICOM browser
      - Activating the NewMPR2MPR module
    
    Parameters are passed via environment variables (set separately via get_slicer_env())
    since standard Slicer doesn't forward custom command-line args to Python scripts.
    
    Args:
        slicer_exe: Path to the Slicer executable (custom or stock)
        dicom_dir: Path to the DICOM directory
        layout: Layout name (validated)
        patient_id: Optional patient ID
        study_id: Optional study ID
        window_width: Optional window width (contrast) for slice viewers
        window_level: Optional window level (brightness) for slice viewers
        series_uid: Optional Series Instance UID for primary volume
        no_splash: Whether to skip the splash screen
        auto_center: Whether to auto-center slices
        software_rendering: Whether to use software rendering
        
    Returns:
        List of command-line arguments
    """
    cmd = [str(slicer_exe)]
    
    # Always skip splash screens for faster startup (both application and launcher)
    cmd.append("--no-splash")
    cmd.append("--launcher-no-splash")
    
    # Add testing mode to reduce GPU requirements
    if software_rendering:
        cmd.append("--testing")
        print("[NewMPR2Slicer] Added --testing flag for reduced GPU requirements")
    
    # =========================================================================
    # IMMEDIATE BRANDING: Use --python-code to apply branding AS EARLY AS POSSIBLE
    # This runs before --python-script and sets the window title immediately
    # NOTE: Must be a simple one-liner that works on a single line (no try/if/def)
    # =========================================================================
    # Branding code that:
    # 1. Sets window title immediately
    # 2. Schedules MULTIPLE logo removal attempts with different delays
    #    to ensure the logo is removed once the UI is fully built
    # Note: Logo is set as PanelDockWidget.setTitleBarWidget(logoLabel) in C++
    #       We must replace it with an empty widget
    # Using simple lambdas for each timer callback
    immediate_branding_code = (
        'import qt,slicer;'
        'qt.QCoreApplication.setApplicationName("AI-PACS Advanced Viewer");'
        'qt.QCoreApplication.setOrganizationName("AI-PACS");'
        '[mw.setWindowTitle("AI-PACS Advanced Viewer v0.1") for mw in [slicer.util.mainWindow()] if mw];'
        '_rl=lambda:(lambda pd,w=qt.QWidget():[w.setFixedHeight(0),pd.setTitleBarWidget(w)] if pd else None)(slicer.util.findChild(slicer.util.mainWindow(),"PanelDockWidget"));'
        '[qt.QTimer.singleShot(t,_rl) for t in [50,100,200,500,1000]]'
    )
    cmd.append("--python-code")
    cmd.append(immediate_branding_code)
    
    # Get the startup script path
    startup_script = get_startup_script_path()
    if startup_script is None:
        print("[NewMPR2Slicer] [FAIL] CRITICAL: startup_script.py not found!")
        print("[NewMPR2Slicer] [FAIL] Integration will NOT work correctly without it.")
        print("[NewMPR2Slicer] [FAIL] User will see stock Slicer Welcome page instead of MPR viewer.")
        # Still launch, but warn heavily
    else:
        # Add --python-script to run our startup script after Slicer initializes
        cmd.append("--python-script")
        cmd.append(str(startup_script))
    
    # Log the full command for debugging
    print(f"[NewMPR2Slicer] ========================================")
    print(f"[NewMPR2Slicer] Command line built:")
    print(f"[NewMPR2Slicer]   Executable: {slicer_exe}")
    print(f"[NewMPR2Slicer]   Full command: {' '.join(cmd)}")
    print(f"[NewMPR2Slicer] ========================================")
    
    return cmd


def get_slicer_env(
    dicom_dir: Path,
    layout: str,
    patient_id: Optional[str] = None,
    study_id: Optional[str] = None,
    window_width: Optional[float] = None,
    window_level: Optional[float] = None,
    series_uid: Optional[str] = None,
    auto_center: bool = True,
    slicer_exe: Optional[Path] = None,
    viewport_x: Optional[int] = None,
    viewport_y: Optional[int] = None,
    viewport_width: Optional[int] = None,
    viewport_height: Optional[int] = None,
) -> dict:
    """
    Build environment variables to pass parameters to the startup script.
    
    Standard Slicer doesn't pass custom command-line args to Python scripts,
    so we use environment variables instead.
    
    Returns:
        dict of environment variables to set
    """
    env = os.environ.copy()
    
    # Add Slicer bin directory to PATH for DLL loading
    if slicer_exe:
        bin_dir = slicer_exe.parent
        lib_dir = bin_dir.parent.parent / "lib"  # build/lib
        qt_bin = _resolve_qt_bin_dir()

        # Prepend our directories to PATH
        path_additions = [str(bin_dir), str(lib_dir)]
        if qt_bin:
            path_additions.append(str(qt_bin))
        current_path = env.get("PATH", "")
        env["PATH"] = ";".join(path_additions) + ";" + current_path
        print(f"[AIPACS_LAUNCH] Added to PATH: {bin_dir}")
    
    # Core parameters
    env["NEWMPR2_DICOM_DIR"] = str(dicom_dir)
    env["NEWMPR2_LAYOUT"] = layout
    env["NEWMPR2_AUTO_CENTER"] = "1" if auto_center else "0"
    
    # Optional parameters
    if patient_id:
        env["NEWMPR2_PATIENT_ID"] = patient_id
    if study_id:
        env["NEWMPR2_STUDY_ID"] = study_id
    if window_width is not None:
        env["NEWMPR2_WINDOW_WIDTH"] = str(window_width)
    if window_level is not None:
        env["NEWMPR2_WINDOW_LEVEL"] = str(window_level)
    if series_uid:
        env["NEWMPR2_SERIES_UID"] = series_uid
    
    # VOR (main PACS viewer) geometry for initial window positioning
    if viewport_x is not None:
        env["NEWMPR2_VOR_X"] = str(viewport_x)
    if viewport_y is not None:
        env["NEWMPR2_VOR_Y"] = str(viewport_y)
    if viewport_width is not None:
        env["NEWMPR2_VOR_WIDTH"] = str(viewport_width)
    if viewport_height is not None:
        env["NEWMPR2_VOR_HEIGHT"] = str(viewport_height)
    
    # Set VTK/OpenGL options to help with driver issues
    # This can help on systems with problematic GPU drivers
    # env["VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN"] = "0"  # Don't use offscreen by default
    # env["VTK_RENDERER_USE_OPENGL"] = "1"  # Ensure OpenGL is used
    
    return env


def launch_slicer(
    dicom_dir: str,
    layout: str = DEFAULT_LAYOUT,
    patient_id: Optional[str] = None,
    study_id: Optional[str] = None,
    window_width: Optional[float] = None,
    window_level: Optional[float] = None,
    series_uid: Optional[str] = None,
    slicer_exe: Optional[Path] = None,
    no_splash: bool = False,
    auto_center: bool = True,
    wait: bool = True,
    software_rendering: bool = False,
    viewport_x: Optional[int] = None,
    viewport_y: Optional[int] = None,
    viewport_width: Optional[int] = None,
    viewport_height: Optional[int] = None,
) -> int:
    """
    Launch 3D Slicer with our startup script and configuration.
    
    Parameters are passed via environment variables since standard Slicer
    doesn't forward custom command-line args to Python scripts.
    
    Args:
        dicom_dir: Path to the DICOM directory to open
        layout: Layout name (default: 'mpr')
        patient_id: Optional patient ID for display
        study_id: Optional study ID for display
        window_width: Optional window width (contrast) for slice viewers
        window_level: Optional window level (brightness) for slice viewers
        series_uid: Optional Series Instance UID for primary volume selection
        slicer_exe: Optional path to the Slicer executable (auto-detected if not provided)
        no_splash: Skip splash screen
        auto_center: Auto-center slices (default: True)
        wait: If True, wait for the process to complete
        software_rendering: If True, use software rendering (Mesa) instead of GPU
        
    Returns:
        Process exit code (0 for success), or non-zero on error
    """
    # Validate DICOM directory
    dicom_path = Path(dicom_dir).resolve()
    if not dicom_path.exists():
        print(f"Error: DICOM directory does not exist: {dicom_path}", file=sys.stderr)
        return 1
    
    if not dicom_path.is_dir():
        print(f"Error: Path is not a directory: {dicom_path}", file=sys.stderr)
        return 1
    
    # Validate layout
    validated_layout = validate_layout(layout)
    
    # Find or validate executable - MUST be AIPacsAdvancedViewer.exe (no fallback)
    if slicer_exe is None:
        slicer_exe = find_slicer_executable()
    
    if slicer_exe is None or not slicer_exe.exists():
        # FATAL: Custom app not found - do NOT proceed
        print("")
        print("[AIPACS_LAUNCH] " + "=" * 70, file=sys.stderr)
        print("[AIPACS_LAUNCH] FATAL: Cannot launch - AIPacsAdvancedViewer.exe not found!", file=sys.stderr)
        print("[AIPACS_LAUNCH] " + "=" * 70, file=sys.stderr)
        print("[AIPACS_LAUNCH] The custom app must be built before using Advanced Viewer.", file=sys.stderr)
        print("[AIPACS_LAUNCH] See the build instructions above.", file=sys.stderr)
        print("[AIPACS_LAUNCH] Stock Slicer.exe is NOT used as a fallback.", file=sys.stderr)
        print("[AIPACS_LAUNCH] " + "=" * 70, file=sys.stderr)
        print("")
        return 127  # Exit code 127 = command not found
    
    # Build command line (uses --python-script for our startup script)
    cmd = build_slicer_command(
        slicer_exe=slicer_exe,
        dicom_dir=dicom_path,
        layout=validated_layout,
        patient_id=patient_id,
        study_id=study_id,
        window_width=window_width,
        window_level=window_level,
        series_uid=series_uid,
        no_splash=no_splash,
        auto_center=auto_center,
        software_rendering=software_rendering,
    )
    
    # Build environment variables to pass parameters to startup script
    env = get_slicer_env(
        dicom_dir=dicom_path,
        layout=validated_layout,
        patient_id=patient_id,
        study_id=study_id,
        window_width=window_width,
        window_level=window_level,
        series_uid=series_uid,
        auto_center=auto_center,
        slicer_exe=slicer_exe,
        viewport_x=viewport_x,
        viewport_y=viewport_y,
        viewport_width=viewport_width,
        viewport_height=viewport_height,
    )
    
    # If software rendering is requested, set environment variables
    if software_rendering:
        print("[NewMPR2Slicer] Using software rendering (Mesa) - GPU rendering disabled")
        # Force Mesa software rendering
        env["MESA_GL_VERSION_OVERRIDE"] = "3.3"
        env["LIBGL_ALWAYS_SOFTWARE"] = "1"
        env["GALLIUM_DRIVER"] = "llvmpipe"
        # Qt software rendering
        env["QT_OPENGL"] = "software"
        env["QT_QUICK_BACKEND"] = "software"
        # Disable VTK GPU features
        env["VTK_DEFAULT_OPENGL_WINDOW"] = "vtkOSOpenGLRenderWindow"
        # Force ANGLE for Qt (uses DirectX instead of OpenGL on Windows)
        env["QT_OPENGL_DLL"] = "opengl32sw"
        # Disable hardware acceleration hints
        env["LIBGL_ALWAYS_INDIRECT"] = "1"
        # VTK specific software rendering
        env["VTK_OPENGL_FORCE_SOFTPIPE"] = "1"
    else:
        # Force using high-performance GPU (NVIDIA over Intel integrated)
        # This helps on systems with hybrid graphics
        print("[NewMPR2Slicer] Forcing high-performance GPU (NVIDIA/AMD over Intel)")
        env["SHIM_MCCOMPAT"] = "0x800000001"  # Force discrete GPU on Optimus/AMD systems
        env["QT_OPENGL"] = "desktop"  # Use desktop OpenGL, not ANGLE or software
        # Prefer NVIDIA GPU
        env["OPTIMUS_PERFORMANCE_MODE"] = "1"
        env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
        env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
    
    # =========================================================================
    # [AIPACS_LINK_DST] PHASE 2: ENV VAR LOGGING
    # Log environment variables being sent to AIPacsAdvancedViewer.exe
    # =========================================================================
    print("")
    print("[AIPACS_LINK_DST] =================================================")
    print("[AIPACS_LINK_DST] ENV VARS SENT TO AIPacsAdvancedViewer.exe:")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_DICOM_DIR = {env.get('NEWMPR2_DICOM_DIR')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_SERIES_UID = {env.get('NEWMPR2_SERIES_UID')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_LAYOUT = {env.get('NEWMPR2_LAYOUT')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_WINDOW_WIDTH = {env.get('NEWMPR2_WINDOW_WIDTH')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_WINDOW_LEVEL = {env.get('NEWMPR2_WINDOW_LEVEL')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_PATIENT_ID = {env.get('NEWMPR2_PATIENT_ID')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_STUDY_ID = {env.get('NEWMPR2_STUDY_ID')}")
    print(f"[AIPACS_LINK_DST]   NEWMPR2_AUTO_CENTER = {env.get('NEWMPR2_AUTO_CENTER')}")
    print(f"[AIPACS_LINK_DST]   VOR geometry from PACS: x={env.get('NEWMPR2_VOR_X')}, y={env.get('NEWMPR2_VOR_Y')}, w={env.get('NEWMPR2_VOR_WIDTH')}, h={env.get('NEWMPR2_VOR_HEIGHT')}")
    print("[AIPACS_LINK_DST] Executable: {}".format(slicer_exe))
    print("[AIPACS_LINK_DST] Args: {}".format(' '.join(cmd)))
    print("[AIPACS_LINK_DST] =================================================")
    print("")
    
    # =========================================================================
    # Setup early branding via .slicerrc.py (runs during Slicer's init phase)
    # DISABLED: Causes BOM encoding issues on Windows
    # =========================================================================
    # setup_early_branding_slicerrc()
    
    try:
        # Create log file with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        log_file = log_dir / f"newmpr2_geometry_{timestamp}.txt"
        
        print(f"[AIPACS_LAUNCH] Logging to: {log_file}")
        
        # On Windows, use CREATE_NEW_CONSOLE to fully detach from parent's OpenGL context
        # This fixes "GLEW could not be initialized: Missing GL version" when parent uses VTK
        creation_flags = 0
        if sys.platform == 'win32':
            creation_flags = subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP
            print("[AIPACS_LAUNCH] Using CREATE_NEW_CONSOLE for GPU context isolation")
        
        if wait:
            # Run and wait for completion, passing env vars
            # Redirect stderr to log file to capture geometry logs
            with open(log_file, 'w', encoding='utf-8') as f:
                # Write header
                f.write(f"NewMPR2 Geometry Log\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"DICOM Directory: {dicom_path}\n")
                f.write(f"Series UID: {series_uid}\n")
                f.write("=" * 80 + "\n\n")
                f.flush()
                
                print(f"[AIPACS_LAUNCH] subprocess.run() - waiting for exit...")
                result = subprocess.run(
                    cmd, 
                    cwd=str(slicer_exe.parent), 
                    env=env, 
                    creationflags=creation_flags,
                    stderr=f,  # Capture stderr (geometry logs) to file
                    stdout=subprocess.PIPE  # Suppress stdout to console
                )
            
            # Also print log location to console
            print(f"[AIPACS_LAUNCH] Geometry log saved to: {log_file}")
            
            # Cleanup slicerrc after Slicer closes
            cleanup_early_branding_slicerrc()
            return result.returncode
            # Also print log location to console
            print(f"[AIPACS_LAUNCH] Geometry log saved to: {log_file}")
            
            # Cleanup slicerrc after Slicer closes
            cleanup_early_branding_slicerrc()
            return result.returncode
        else:
            # Start process without waiting, passing env vars
            # Use fully detached process to avoid inheriting OpenGL state
            # Also redirect to log file
            with open(log_file, 'w', encoding='utf-8') as f:
                # Write header
                f.write(f"NewMPR2 Geometry Log (Background Mode)\n")
                f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"DICOM Directory: {dicom_path}\n")
                f.write(f"Series UID: {series_uid}\n")
                f.write("=" * 80 + "\n\n")
                f.write("Note: Logs are captured asynchronously. Check this file after Slicer initializes.\n\n")
                f.flush()
            
            # Launch with stderr redirected
            log_handle = open(log_file, 'a', encoding='utf-8')
            subprocess.Popen(
                cmd, 
                cwd=str(slicer_exe.parent), 
                env=env,
                creationflags=creation_flags,
                start_new_session=True if sys.platform != 'win32' else False,
                stderr=log_handle,
                stdout=subprocess.PIPE
            )
            print(f"3D Slicer started in background (detached).")
            print(f"[AIPACS_LAUNCH] Geometry log will be saved to: {log_file}")
            # Schedule cleanup after a delay (give Slicer time to read the file)
            import threading
            def delayed_cleanup():
                import time
                time.sleep(10)  # Wait 10 seconds for Slicer to fully start
                cleanup_early_branding_slicerrc()
            cleanup_thread = threading.Thread(target=delayed_cleanup, daemon=True)
            cleanup_thread.start()
            return 0
    except FileNotFoundError:
        cleanup_early_branding_slicerrc()
        print(f"Error: Could not execute: {slicer_exe}", file=sys.stderr)
        return 1
    except Exception as e:
        cleanup_early_branding_slicerrc()
        print(f"Error launching Slicer: {e}", file=sys.stderr)
        return 1


# ============================================================
# Standby/Prewarm Mode - Launch Slicer in background, wait for remote commands
# ============================================================

# Python code that runs inside Slicer to set up the standby mode command listener
# This keeps Slicer HIDDEN until data is loaded, so user never sees "3D Slicer" title
STANDBY_SLICER_CODE = '''#!/usr/bin/env python
# AI-PACS Advanced Viewer Standby Mode Script
# This script runs inside Slicer to keep it hidden until data is loaded

import socket
import json
import threading
import os
import tempfile
import atexit
import qt
import slicer

# ===== BRANDING CONSTANTS =====
BRAND_TITLE = "AI-PACS Advanced Viewer v0.1"

# ===== HIDE WINDOW IMMEDIATELY - BEFORE ANYTHING ELSE =====
# This MUST run first to prevent window from flashing
_standby_state = {"hidden": False, "attempts": 0, "should_exit": False}

def _hide_window_immediately():
    """Hide the main window as soon as it exists. Called repeatedly until successful."""
    _standby_state["attempts"] += 1
    
    if _standby_state["hidden"] or _standby_state["should_exit"]:
        return
    
    try:
        mw = slicer.util.mainWindow()
        if mw:
            # HIDE immediately - this prevents the window from showing
            mw.hide()
            mw.setWindowTitle(BRAND_TITLE + " (Standby)")
            _standby_state["hidden"] = True
            print("[AIPACS_STANDBY] Window hidden immediately")
            return
    except:
        pass
    
    # Keep trying until window is found and hidden (max 5 seconds)
    if _standby_state["attempts"] < 500:
        qt.QTimer.singleShot(10, _hide_window_immediately)

# Start hiding attempts IMMEDIATELY (before lock check, before anything)
qt.QTimer.singleShot(0, _hide_window_immediately)
qt.QTimer.singleShot(5, _hide_window_immediately)
qt.QTimer.singleShot(10, _hide_window_immediately)
qt.QTimer.singleShot(20, _hide_window_immediately)
qt.QTimer.singleShot(50, _hide_window_immediately)
qt.QTimer.singleShot(100, _hide_window_immediately)

# ===== STANDBY LOCK FILE - Prevent multiple standby instances =====
def _get_standby_lock_path():
    """Get path to the standby lock file (one per machine/user)."""
    return os.path.join(tempfile.gettempdir(), "aipacs_viewer_standby.lock")

def _is_pid_running(pid):
    """Check if a process with given PID is running (Windows-compatible)."""
    try:
        pid = int(pid)
        # On Windows, use tasklist to check if PID exists
        import subprocess
        result = subprocess.run(
            ['tasklist', '/FI', f'PID eq {pid}', '/NH'],
            capture_output=True,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return str(pid) in result.stdout
    except:
        # If check fails, assume process is running (safer)
        return True

def _cleanup_standby_lock():
    """Remove the standby lock file on exit."""
    lock_path = _get_standby_lock_path()
    if os.path.exists(lock_path):
        try:
            os.remove(lock_path)
            print("[AIPACS_STANDBY] Removed standby lock:", lock_path)
        except Exception as e:
            print("[AIPACS_STANDBY] Failed to remove standby lock:", e)

def _check_and_create_standby_lock():
    """Check if another standby is running. If so, exit immediately."""
    lock_path = _get_standby_lock_path()
    if os.path.exists(lock_path):
        try:
            with open(lock_path, 'r') as f:
                old_pid = f.read().strip()
            print(f"[AIPACS_STANDBY] Lock file exists with PID={old_pid}")
            
            # Check if the old process is still running
            if old_pid and _is_pid_running(old_pid):
                print("[AIPACS_STANDBY] Prevented second standby instance - another is running")
                _standby_state["should_exit"] = True
                qt.QTimer.singleShot(100, lambda: slicer.util.exit(0))
                return False
            else:
                # Stale lock file - process crashed, remove it
                print(f"[AIPACS_STANDBY] Stale lock file (PID {old_pid} not running), removing...")
                try:
                    os.remove(lock_path)
                except:
                    pass
        except Exception as e:
            print(f"[AIPACS_STANDBY] Error reading lock file: {e}, will try to create new lock")
    
    # Create the lock file
    try:
        with open(lock_path, 'w') as f:
            f.write(str(os.getpid()))
        print("[AIPACS_STANDBY] Created standby lock:", lock_path)
        atexit.register(_cleanup_standby_lock)
        return True
    except Exception as e:
        print(f"[AIPACS_STANDBY] Failed to create lock file: {e}")
        return True

# ===== CHECK LOCK =====
_lock_ok = _check_and_create_standby_lock()

if _lock_ok:
    # ===== IMMEDIATE BRANDING =====
    qt.QCoreApplication.setApplicationName("AIPacsAdvancedViewer")
    qt.QCoreApplication.setOrganizationName("AI-PACS")
    qt.QCoreApplication.setOrganizationDomain("ai-pacs.local")
    qt.QCoreApplication.setApplicationDisplayName(BRAND_TITLE)

# ===== COMMAND LISTENER CLASS =====
class StandbyCommandListener:
    """
    Listens for remote commands on a TCP socket and executes them in Slicer.
    
    Key feature: Slicer window stays HIDDEN until a "load" command is received.
    This completely eliminates the "3D Slicer" title flash because:
    1. Window is hidden immediately at startup
    2. Branding is applied while hidden
    3. Only after branding is complete, window is shown with data
    """
    
    def __init__(self, port):
        self.port = port
        self.running = False
        self.thread = None
        self.sock = None
        
    def start(self):
        """Start the listener in a background thread."""
        self.running = True
        self.thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.thread.start()
        print(f"[AIPACS_STANDBY] Command listener started on port {self.port}")
        
    def stop(self):
        """Stop the listener."""
        self.running = False
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
        print("[AIPACS_STANDBY] Command listener stopped")
        
    def _listen_loop(self):
        """Main listening loop - runs in background thread."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind(('localhost', self.port))
            self.sock.listen(1)
            self.sock.settimeout(1.0)  # Allow checking self.running periodically
            
            while self.running:
                try:
                    conn, addr = self.sock.accept()
                    data = conn.recv(65536)  # Large buffer for JSON payload
                    if data:
                        try:
                            payload = json.loads(data.decode('utf-8'))
                            # Schedule execution in Qt main thread
                            qt.QTimer.singleShot(0, lambda p=payload: self._handle_command(p))
                            conn.sendall(b'{"status": "ok"}')
                        except json.JSONDecodeError as e:
                            conn.sendall(f'{{"status": "error", "message": "{str(e)}"}}'.encode())
                    conn.close()
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[AIPACS_STANDBY] Socket error: {e}")
        except Exception as e:
            print(f"[AIPACS_STANDBY] Listener error: {e}")
            
    def _handle_command(self, payload):
        """Handle a command payload in the Qt main thread."""
        try:
            action = payload.get("action", "")
            print(f"[AIPACS_STANDBY] Handling command: {action}")
            
            if action == "load":
                print("[AIPACS_STANDBY] LOAD command accepted, showing window and loading data")
                self._load_dicom(payload)
            elif action == "close":
                slicer.util.exit()
            elif action == "ping":
                print("[AIPACS_STANDBY] Ping received")
            else:
                print(f"[AIPACS_STANDBY] Unknown action: {action}")
                
        except Exception as e:
            print(f"[AIPACS_STANDBY] Error handling command: {e}")
            
    def _load_dicom(self, payload):
        """Load DICOM data from the specified directory and then SHOW the window."""
        dicom_dir = payload.get("dicom_dir")
        if not dicom_dir:
            print("[AIPACS_STANDBY] No dicom_dir in payload")
            return
            
        print(f"[AIPACS_STANDBY] Loading DICOM from: {dicom_dir}")
        
        # Get patient info for title
        patient_id = payload.get("patient_id", "")
        
        # Import DICOM
        try:
            from DICOMLib import DICOMUtils
            loadedNodeIDs = DICOMUtils.loadDICOMDirectory(dicom_dir)
            if loadedNodeIDs:
                print(f"[AIPACS_STANDBY] Loaded {len(loadedNodeIDs)} nodes")
                
                # Apply window/level if provided
                window_width = payload.get("window_width")
                window_level = payload.get("window_level")
                if window_width is not None and window_level is not None:
                    for nodeID in loadedNodeIDs:
                        node = slicer.mrmlScene.GetNodeByID(nodeID)
                        if node and node.IsA("vtkMRMLScalarVolumeNode"):
                            displayNode = node.GetDisplayNode()
                            if displayNode:
                                displayNode.SetAutoWindowLevel(False)
                                displayNode.SetWindowLevel(window_width, window_level)
                                
                # Set layout if provided
                layout = payload.get("layout", "mpr")
                layoutManager = slicer.app.layoutManager()
                if layout == "mpr" or layout == "fourup":
                    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
                elif layout == "axial":
                    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView)
                elif layout == "sagittal":
                    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpYellowSliceView)
                elif layout == "coronal":
                    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpGreenSliceView)
                elif layout == "threeD":
                    layoutManager.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutOneUp3DView)
            
            # ===== CRITICAL: Apply branding BEFORE showing window =====
            mw = slicer.util.mainWindow()
            if mw:
                # Build title with patient ID
                if patient_id:
                    title = f"{BRAND_TITLE} | Patient: {patient_id}"
                else:
                    title = BRAND_TITLE
                    
                # Apply branding while still hidden
                mw.setWindowTitle(title)
                
                # Hide logo completely
                try:
                    logo = slicer.util.findChild(mw, "LogoLabel")
                    if logo:
                        logo.visible = False
                        logo.hide()
                except: pass
                
                # Force Qt to process the title change
                qt.QCoreApplication.processEvents()
                
                # NOW show the window - user will only see branded title
                print(f"[AIPACS_STANDBY] Showing window with title: {title}")
                mw.show()
                mw.showMaximized()
                mw.raise_()
                mw.activateWindow()
                
                # Double-check branding after show (belt and suspenders)
                qt.QTimer.singleShot(50, lambda: self._ensure_branding(title))
                    
        except Exception as e:
            print(f"[AIPACS_STANDBY] Error loading DICOM: {e}")
            import traceback
            traceback.print_exc()
            
    def _ensure_branding(self, title):
        """Ensure branding is still applied after window is shown."""
        try:
            mw = slicer.util.mainWindow()
            if mw:
                if mw.windowTitle() != title:
                    mw.setWindowTitle(title)
                # Keep logo hidden
                try:
                    logo = slicer.util.findChild(mw, "LogoLabel")
                    if logo and logo.visible:
                        logo.visible = False
                except: pass
        except: pass

# Start the command listener with the configured port
_standby_listener = StandbyCommandListener({remote_port})
_standby_listener.start()

# Register cleanup on Slicer exit
import atexit
atexit.register(_standby_listener.stop)

print("[AIPACS_STANDBY] Slicer is now in standby mode, waiting for remote commands")
'''


def launch_slicer_standby(
    remote_port: int = 47891,
    slicer_exe: Optional[Path] = None
) -> int:
    """
    Launch Slicer in standby (prewarm) mode.
    
    In standby mode, Slicer starts but doesn't load any data. It waits for
    remote commands over a TCP socket. This allows instant startup when the
    user clicks the Advanced 3D Viewer button.
    
    Args:
        remote_port: TCP port for the remote command listener (default: 47891)
        slicer_exe: Optional path to Slicer executable (auto-detected if None)
        
    Returns:
        Exit code (0 = success)
    """
    print("[launch_slicer] ========================================")
    print("[launch_slicer] Standby mode enabled")
    print(f"[launch_slicer] Using remote port: {remote_port}")
    print("[launch_slicer] ========================================")
    
    # Find executable if not provided
    exe = slicer_exe or find_slicer_executable()
    
    if exe is None:
        print("[launch_slicer] [FAIL] Slicer executable not found", file=sys.stderr)
        return 1
    
    if not exe.exists():
        print(f"[launch_slicer] [FAIL] Slicer executable does not exist: {exe}", file=sys.stderr)
        return 1
    
    print(f"[launch_slicer] Using executable: {exe}")
    
    # Set up early branding
    setup_early_branding_slicerrc()
    
    # Write the standby script to a temporary file
    # This avoids issues with embedding complex Python code in command line
    standby_script_content = STANDBY_SLICER_CODE.replace("{remote_port}", str(remote_port))
    
    # Create a temporary Python script file
    import tempfile
    temp_script = tempfile.NamedTemporaryFile(
        mode='w',
        suffix='_standby.py',
        prefix='newmpr2_',
        delete=False,
        encoding='utf-8'
    )
    temp_script.write(standby_script_content)
    temp_script.close()
    temp_script_path = temp_script.name
    
    print(f"[launch_slicer] Created temp standby script: {temp_script_path}")
    
    # Build the command - use --python-script instead of --python-code
    # Window is started hidden via Windows STARTUPINFO (SW_HIDE)
    cmd: List[str] = [
        str(exe),
        "--no-splash",
        "--python-script", temp_script_path
    ]
    
    print(f"[launch_slicer] Final Slicer command: {' '.join(cmd)}")
    
    # Set up environment for GPU isolation
    # Also export the remote port so the standby script can use it
    env = os.environ.copy()
    env["NEWMPR2_REMOTE_PORT"] = str(remote_port)
    env["NEWMPR2_STANDBY_MODE"] = "1"
    
    # Add Slicer bin directory to PATH for DLL loading
    bin_dir = exe.parent
    lib_dir = bin_dir.parent.parent / "lib"  # build/lib
    qt_bin = _resolve_qt_bin_dir()
    path_additions = [str(bin_dir), str(lib_dir)]
    if qt_bin:
        path_additions.append(str(qt_bin))
    current_path = env.get("PATH", "")
    env["PATH"] = ";".join(path_additions) + ";" + current_path
    print(f"[launch_slicer] Added to PATH: {bin_dir}")
    
    print(f"[launch_slicer] Environment: NEWMPR2_REMOTE_PORT={remote_port}, NEWMPR2_STANDBY_MODE=1")
    
    try:
        creation_flags = 0
        startupinfo = None
        
        if sys.platform == 'win32':
            # CREATE_NEW_PROCESS_GROUP for proper termination
            creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP
            
            # Use STARTUPINFO to start the window hidden (SW_HIDE = 0)
            # This prevents the window from flashing when Slicer starts
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            print("[launch_slicer] Using SW_HIDE to start window hidden")
        
        print("[launch_slicer] Starting Slicer subprocess...")
        
        # Run Slicer and wait - the standby mode keeps running until terminated
        # The window starts hidden due to startupinfo, and stays hidden via Python script
        result = subprocess.run(
            cmd, 
            cwd=str(exe.parent), 
            env=env, 
            creationflags=creation_flags,
            startupinfo=startupinfo
        )
        
        print(f"[launch_slicer] Slicer exited with code: {result.returncode}")
        
        # Cleanup
        cleanup_early_branding_slicerrc()
        try:
            os.unlink(temp_script_path)
            print(f"[launch_slicer] Cleaned up temp script: {temp_script_path}")
        except:
            pass
        return result.returncode
        
    except Exception as e:
        print(f"[launch_slicer] [FAIL] Exception: {e}")
        cleanup_early_branding_slicerrc()
        try:
            os.unlink(temp_script_path)
        except:
            pass
        print(f"[AIPACS_STANDBY] [FAIL] Error: {e}", file=sys.stderr)
        return 1


def main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(
        description="Launch NewMPR2Slicer with DICOM data (see docs/launch_contract.md)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Layout Options:
  mpr (default)  - Four-up view: Axial, Sagittal, Coronal, and 3D
  fourup         - Alias for mpr
  axial          - Single axial (Red) slice view
  sagittal       - Single sagittal (Yellow) slice view
  coronal        - Single coronal (Green) slice view
  threeD         - Single 3D view only
  conventional   - Conventional Slicer layout
  dualthreeD     - Two 3D views side by side

Examples:
  # Basic usage with default MPR layout
  python launch_slicer.py --dicom-dir "C:/DICOM/Study123"
  
  # Specify a different layout
  python launch_slicer.py --dicom-dir "C:/DICOM/Study123" --layout axial
  
  # With patient/study IDs
  python launch_slicer.py --dicom-dir "C:/DICOM/Study123" --patient-id PAT001 --study-id STU001
  
  # With window/level synchronization
  python launch_slicer.py --dicom-dir "C:/DICOM/Study123" --window-width 400 --window-level 40
  
  # Full state synchronization
  python launch_slicer.py --dicom-dir "C:/DICOM/Study123" --patient-id PAT001 \\
      --window-width 400 --window-level 40 --series-uid "1.2.840.12345"
  
  # Launch in background (don't wait)
  python launch_slicer.py --dicom-dir "C:/DICOM/Study123" --no-wait

See docs/launch_contract.md for the full specification.
        """
    )
    
    # Required arguments (except in standby mode)
    parser.add_argument(
        "--dicom-dir",
        required=False,  # Not required in standby mode - validated later
        help="Path to the DICOM directory to open in Slicer (required except in standby mode)"
    )
    
    # Optional arguments (as per contract)
    parser.add_argument(
        "--layout",
        default=DEFAULT_LAYOUT,
        help=f"Layout to display (default: {DEFAULT_LAYOUT}). See --help for options."
    )
    
    parser.add_argument(
        "--patient-id",
        default=None,
        help="Optional patient ID for display/metadata"
    )
    
    parser.add_argument(
        "--study-id",
        default=None,
        help="Optional study ID for display/metadata"
    )
    
    # Viewing state synchronization arguments
    parser.add_argument(
        "--window-width",
        type=float,
        default=None,
        help="Window width (contrast) to apply to slice viewers. Syncs viewing state from main app."
    )
    
    parser.add_argument(
        "--window-level",
        type=float,
        default=None,
        help="Window level/center (brightness) to apply to slice viewers. Syncs viewing state from main app."
    )
    
    parser.add_argument(
        "--series-uid",
        default=None,
        help="Series Instance UID to identify the primary volume when multiple series exist."
    )
    
    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Skip the splash screen for faster startup"
    )
    
    parser.add_argument(
        "--no-auto-center",
        action="store_true",
        help="Don't auto-center slices after loading"
    )
    
    # Process management
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Don't wait for Slicer to close (launch in background)"
    )
    
    parser.add_argument(
        "--executable",
        type=Path,
        help="Path to the Slicer executable (auto-detected if not specified)"
    )
    
    # Standby/Prewarm mode arguments
    parser.add_argument(
        "--standby",
        action="store_true",
        help="Launch in standby (prewarm) mode - Slicer starts but waits for remote commands"
    )
    
    parser.add_argument(
        "--remote-port",
        type=int,
        default=47891,
        help="TCP port for remote command listener in standby mode (default: 47891)"
    )
    
    args = parser.parse_args()
    
    # Handle standby mode (doesn't need --dicom-dir)
    if args.standby:
        exit_code = launch_slicer_standby(
            remote_port=args.remote_port,
            slicer_exe=args.executable
        )
        sys.exit(exit_code)
    
    # Validate --dicom-dir is provided for normal launch
    if not args.dicom_dir:
        parser.error("--dicom-dir is required (except in --standby mode)")
    
    exit_code = launch_slicer(
        dicom_dir=args.dicom_dir,
        layout=args.layout,
        patient_id=args.patient_id,
        study_id=args.study_id,
        window_width=args.window_width,
        window_level=args.window_level,
        series_uid=args.series_uid,
        slicer_exe=args.executable,
        no_splash=args.no_splash,
        auto_center=not args.no_auto_center,
        wait=not args.no_wait,
    )
    
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
