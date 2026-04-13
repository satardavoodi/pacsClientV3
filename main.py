import sys
import os
import multiprocessing
import logging
import subprocess
import importlib.util
from pathlib import Path

from aipacs_runtime import (
    activate_optional_module_runtime,
    bootstrap_installer_selected_module_packages,
    build_graphics_runtime_patch,
    build_windows_graphics_environment,
    resolve_graphics_profile,
    save_runtime_profile,
)

# Required for multiprocessing.Process with PyInstaller frozen executables
# (spawn start-method on Windows): must be called before any other code.
multiprocessing.freeze_support()


def _extract_startup_import_folder() -> str | None:
    """Extract optional startup import folder from argv/env.

    Supported sources (priority order):
      1) --import-folder <path>
      2) AIPACS_IMPORT_FOLDER environment variable
    """
    folder_path = None

    if "--import-folder" in sys.argv:
        try:
            idx = sys.argv.index("--import-folder")
            if idx + 1 < len(sys.argv):
                folder_path = sys.argv[idx + 1]
                # Remove custom args so Qt/app internals don't see unknown switches.
                del sys.argv[idx:idx + 2]
            else:
                print("[STARTUP] '--import-folder' provided without a path; ignoring.")
        except Exception:
            pass

    if not folder_path:
        env_folder = os.environ.get("AIPACS_IMPORT_FOLDER", "").strip()
        if env_folder:
            folder_path = env_folder

    def _looks_like_media_root(candidate: str | None) -> bool:
        if not candidate:
            return False
        try:
            root = Path(candidate).expanduser()
            if not root.exists() or not root.is_dir():
                return False
            return any((root / marker).exists() for marker in ("DICOMDIR", "AIPACS_MEDIA_INFO.json", "START_HERE.txt"))
        except Exception:
            return False

    # Fallback 1: if launched from packaged viewer under MEDIA_ROOT\VIEWER\AiPacs.exe,
    # infer media root from executable path.
    if not folder_path and getattr(sys, "frozen", False):
        try:
            exe_parent = Path(sys.executable).resolve().parent
            if exe_parent.name.upper() == "VIEWER":
                parent_root = exe_parent.parent
                if _looks_like_media_root(str(parent_root)):
                    folder_path = str(parent_root)
        except Exception:
            pass

    # Fallback 2: use current working directory if it already looks like exported media root.
    if not folder_path:
        try:
            cwd = str(Path.cwd())
            if _looks_like_media_root(cwd):
                folder_path = cwd
        except Exception:
            pass

    if folder_path:
        print(f"[STARTUP] Requested import folder: {folder_path}")

    return folder_path


def _maybe_run_tests_and_exit() -> None:
    """Allow test execution via application entrypoint.

    Usage:
      python main.py --run-tests
      python main.py --run-tests tests/test_pydicom_backend_geometry.py -q
    """
    if "--run-tests" not in sys.argv:
        return

    arg_index = sys.argv.index("--run-tests")
    pytest_args = sys.argv[arg_index + 1:] or ["tests/test_pydicom_backend_geometry.py"]

    if importlib.util.find_spec("pytest") is None:
        print("[TEST] pytest is not installed.")
        print("[TEST] Install dev dependencies:")
        print("       python -m pip install -r requirements-dev.txt")
        sys.exit(2)

    cmd = [sys.executable, "-m", "pytest", *pytest_args]
    print(f"[TEST] Running: {' '.join(cmd)}")
    rc = subprocess.call(cmd)
    sys.exit(int(rc))


_maybe_run_tests_and_exit()
bootstrap_installer_selected_module_packages()
activate_optional_module_runtime()

# ============================================================================
# CRITICAL: Graphics/OpenGL Configuration MUST happen before any Qt/VTK imports
# ============================================================================
GRAPHICS_DLL_DIR_HANDLES = []

def configure_graphics_fallback():
    """
    Configure comprehensive graphics fallback for maximum compatibility.
    
    This prevents VTK/OpenGL crashes on systems with:
    - Missing or outdated GPU drivers
    - Incompatible OpenGL versions
    - No dedicated GPU (integrated graphics only)
    - Remote desktop / virtual machine environments
    
    Exit codes for critical failures:
    - 1: Graphics subsystem initialization failed (fatal)
    """
    profile = resolve_graphics_profile()
    if sys.platform != "win32":
        return profile

    frozen = getattr(sys, "frozen", False)
    use_gpu = bool(profile.get("use_gpu", False))
    graphics_env = build_windows_graphics_environment(profile, frozen=frozen)

    for key in graphics_env.get("clear_env", []):
        os.environ.pop(key, None)
    for key, value in (graphics_env.get("env") or {}).items():
        os.environ[key] = value

    path_prefixes = list(graphics_env.get("path_prefixes") or [])
    if path_prefixes:
        current_path = os.environ.get("PATH", "")
        current_parts = [part for part in current_path.split(os.pathsep) if part]
        seen_parts = {part.lower() for part in current_parts}
        merged_parts = []
        for prefix in path_prefixes:
            if prefix.lower() in seen_parts:
                continue
            merged_parts.append(prefix)
            seen_parts.add(prefix.lower())
        merged_parts.extend(current_parts)
        os.environ["PATH"] = os.pathsep.join(merged_parts)
        if hasattr(os, "add_dll_directory"):
            for prefix in path_prefixes:
                try:
                    GRAPHICS_DLL_DIR_HANDLES.append(os.add_dll_directory(prefix))
                except Exception:
                    pass

    # ========================================================================
    # Logging (minimal, before logging subsystem fully initialized)
    # ========================================================================
    
    print(f"[GRAPHICS] Mode: {'FROZEN' if frozen else 'DEVELOPMENT'}")
    try:
        save_runtime_profile(build_graphics_runtime_patch(profile))
    except Exception:
        pass

    print(f"[GRAPHICS] Mode: {'GPU' if use_gpu else 'SOFTWARE_OPENGL'}")
    print(f"[GRAPHICS] Execution mode: {profile.get('execution_mode', '')}")
    print(f"[GRAPHICS] QT_OPENGL: {os.environ.get('QT_OPENGL', '')}")
    print(f"[GRAPHICS] ANGLE_DEFAULT_PLATFORM: {os.environ.get('ANGLE_DEFAULT_PLATFORM', '')}")
    print(f"[GRAPHICS] GPU requested: {profile.get('requested_gpu', False)}")
    print(f"[GRAPHICS] GPU detected: {profile.get('detected_gpu', False)}")
    if profile.get("device_name"):
        print(f"[GRAPHICS] GPU device: {profile['device_name']}")
    software = profile.get("software_rendering") or {}
    if not use_gpu:
        print(f"[GRAPHICS] Software renderer status: {software.get('status', '')}")
        if software.get("qt_opengl_dll"):
            print(f"[GRAPHICS] Qt software OpenGL DLL: {software['qt_opengl_dll']}")
        if software.get("vtk_osmesa_dll"):
            print(f"[GRAPHICS] VTK OSMesa DLL: {software['vtk_osmesa_dll']}")
        if graphics_env.get("warning"):
            print(f"[GRAPHICS] Warning: {graphics_env['warning']}")
        if graphics_env.get("viewer_backend_override"):
            print(f"[GRAPHICS] Safe viewer backend override: {graphics_env['viewer_backend_override']}")
    return profile

# Configure graphics BEFORE any Qt/VTK imports
GRAPHICS_PROFILE = configure_graphics_fallback()

# Fix Windows console encoding for emoji support
if sys.platform == 'win32':
    try:
        import codecs

        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'ignore')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'ignore')
    except:
        pass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from PySide6.QtGui import QIcon
from PacsClient.app_handler import AppHandler
from PacsClient.utils.font_manager import load_fonts, setup_font_rendering
from PacsClient.utils.single_instance_lock import SingleInstanceLock
from modules.LicenseGenerator.license_manager import LicenseManager
from modules.LicenseGenerator.license_dialog import LicenseDialog
from PacsClient.utils.scroll_style import get_scroll_area_style
from PacsClient.utils.theme_manager import get_theme_manager
import vtkmodules.vtkCommonCore as vtkCommonCore

vtkCommonCore.vtkObject.GlobalWarningDisplayOff()
from qasync import QEventLoop
import asyncio

# qtawesome will be initialized after QApplication is created
# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     window = AppHandler()
#     window.show()
#     sys.exit(app.exec())
from PacsClient.utils import IMAGES_LOGIN_PATH
from modules.storage.disk_alert_service import DiskUsageAlertService
from PacsClient.utils.diagnostic_logging import configure_diagnostic_logging

# Graphics configuration has been moved to configure_graphics_fallback() function
# at the top of this file (before any Qt/VTK imports) for maximum compatibility

if __name__ == "__main__":
    # Set working directory to _internal for PyInstaller builds
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        os.chdir(sys._MEIPASS)

    # Load environment variables from .env file if present (for production logging control)
    try:
        from dotenv import load_dotenv
        from pathlib import Path
        # Try loading from installation directory (for production)
        install_dir = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path.cwd()
        env_file = install_dir / '.env'
        if env_file.exists():
            load_dotenv(dotenv_path=env_file, override=True)
            print(f"[CONFIG] Loaded environment from: {env_file}")
        # Also try config/production_logging.env
        config_env = install_dir / 'config' / 'production_logging.env'
        if config_env.exists():
            load_dotenv(dotenv_path=config_env, override=False)  # Don't override .env if it exists
            print(f"[CONFIG] Loaded production logging config: {config_env}")
    except Exception as e:
        print(f"[CONFIG] Could not load .env file: {e}")

    configure_diagnostic_logging(process_role="main", force=True)
    logging.getLogger(__name__).info("Application bootstrap started", extra={"component": "ui"})

    # â”€â”€ H5a: Global exception hook (v2.2.9.3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Captures the FULL Python traceback for any unhandled exception before
    # Qt intercepts it with the generic "Qt has caught an exception" message.
    # Without this, the throwing file/line is permanently lost.
    _original_excepthook = sys.excepthook

    def _aipacs_excepthook(exc_type, exc_value, exc_tb):
        _crash_logger = logging.getLogger("aipacs.crash")
        try:
            import traceback
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            _crash_logger.critical(
                "UNHANDLED EXCEPTION (will propagate to Qt):\n%s",
                "".join(tb_lines),
                extra={"component": "crash"},
            )
        except Exception:
            pass
        # Chain to original hook (prints to stderr)
        if _original_excepthook is not None and _original_excepthook is not _aipacs_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _aipacs_excepthook
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # Migrate data from old flat layout to user_data/ (safe to call multiple times)
    try:
        from PacsClient.utils.data_paths import migrate_legacy_data
        migrate_legacy_data()
    except Exception as _mig_exc:
        logging.getLogger(__name__).warning("Legacy data migration skipped: %s", _mig_exc)
    
    # Set Qt attributes BEFORE creating QApplication
    if GRAPHICS_PROFILE.get("use_gpu", False):
        QApplication.setAttribute(Qt.AA_UseDesktopOpenGL, True)
    else:
        QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)  # Better performance for detached tabs
    
    # â”€â”€ H8/H9: QApplication.notify() override (v2.2.9.3) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # PySide6/Shiboken swallows exceptions at the C++ boundary before
    # sys.excepthook can fire.  Overriding notify() captures the FULL
    # Python traceback for ANY exception thrown during Qt event dispatch
    # (QTimer callbacks, signal slots, paint events, etc.).
    class _AIPacsApplication(QApplication):
        def notify(self, receiver, event):
            try:
                return super().notify(receiver, event)
            except Exception:
                _crash_logger = logging.getLogger("aipacs.crash")
                try:
                    import traceback as _tb_mod
                    _crash_logger.critical(
                        "EXCEPTION in Qt event dispatch (receiver=%s, event_type=%s):\n%s",
                        type(receiver).__name__,
                        int(event.type()) if event else "?",
                        _tb_mod.format_exc(),
                        extra={"component": "crash"},
                    )
                except Exception:
                    pass
                # [H10-SNAPSHOT] Compact state dump at crash time
                try:
                    _snap_parts = []
                    for _tlw in QApplication.topLevelWidgets():
                        _pw = None
                        # Walk widget tree to find PatientWidget
                        if hasattr(_tlw, 'findChildren'):
                            for _child in _tlw.findChildren(type(_tlw).__mro__[0].__class__):
                                if type(_child).__name__ == 'PatientWidget':
                                    _pw = _child
                                    break
                        if _pw is None and type(_tlw).__name__ == 'PatientWidget':
                            _pw = _tlw
                        if _pw is None:
                            continue
                        # Extract viewer state from first active viewer
                        _v_series = '?'
                        _prog_mode = '?'
                        _backend = '?'
                        _gen_id = '?'
                        _req_gen = '?'
                        for _node in getattr(_pw, 'lst_nodes_viewer', []) or []:
                            _vw = getattr(_node, 'vtk_widget', None)
                            if _vw is None:
                                continue
                            try:
                                _v_series = str(getattr(getattr(_vw, 'image_viewer', None), 'metadata', {}).get('series', {}).get('series_number', '?'))
                                _prog_mode = getattr(_vw, '_progressive_mode', '?')
                                _backend = getattr(_vw, '_active_backend', '?')
                                _gen_id = getattr(_vw, '_series_generation_id', '?')
                                _req_gen = getattr(_vw, '_lazy_requested_generation', '?')
                            except Exception:
                                pass
                            break  # first viewer only
                        _dm_active = getattr(_pw, '_h10_dm_active_series', '?')
                        _prog_keys = list(getattr(_pw, '_progressive_series', {}).keys())
                        _done_keys = list(getattr(_pw, '_progressive_display_done', set()))
                        _completed = list(getattr(_pw, '_series_download_completed', set()))
                        _crash_logger.critical(
                            "[H10-SNAPSHOT] viewer_series=%s dm_active=%s prog_keys=%s "
                            "done=%s completed=%s prog_mode=%s backend=%s gen_id=%s req_gen=%s",
                            _v_series, _dm_active, _prog_keys,
                            _done_keys, _completed, _prog_mode, _backend, _gen_id, _req_gen,
                            extra={"component": "crash"},
                        )
                        _snap_parts.append(True)
                        break  # first PatientWidget only
                except Exception:
                    pass
                raise
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    startup_import_folder = _extract_startup_import_folder()

    app = _AIPacsApplication(sys.argv)

    # ========================================================================
    # SINGLE-INSTANCE LOCK: Ensure only one AIPacs instance can run at a time
    # ========================================================================
    instance_lock = SingleInstanceLock()
    if not instance_lock.try_acquire(show_dialog=True):
        # Another instance is running, user was prompted with dialog
        # Lock.try_acquire() handles the user interaction and graceful exit
        logging.getLogger(__name__).info("Application initialization canceled - another instance running")
        sys.exit(0)

    # Get the absolute path to the icon
    # icon_path = os.path.join(os.path.dirname(__file__), "PacsClient", "login", "images", "favicon.ico")
    icon_path = str(IMAGES_LOGIN_PATH / "favicon.ico")

    # Set application icon for taskbar and window
    app.setWindowIcon(QIcon(icon_path))

    # Set application properties for Windows taskbar
    app.setApplicationName("AIPacs")
    # app.setApplicationDisplayName("AIPacs - Professional Medical Imaging Suite")
    app.setApplicationDisplayName("AIPacs")
    app.setApplicationVersion("2.3.3")
    app.setOrganizationName("AIPacs")

    # Setup font rendering for better quality
    setup_font_rendering()

    # Load Roboto fonts
    load_fonts()
    theme_manager = get_theme_manager()

    def _apply_application_theme(theme=None):
        themed_stylesheet = theme_manager.build_application_stylesheet(theme) + get_scroll_area_style()
        app.setStyleSheet(themed_stylesheet)

    _apply_application_theme(theme_manager.current_theme())
    theme_manager.themeChanged.connect(_apply_application_theme)
    
    # Initialize qtawesome fonts (required for icons in PyInstaller builds)
    try:
        import qtawesome as qta
        # Force qtawesome to load its fonts by creating a test icon
        # This ensures icons work properly in PyInstaller builds
        _ = qta.icon('fa5s.home')  # This triggers font loading
    except Exception as e:
        print(f"Warning: Could not initialize qtawesome fonts: {e}")

    # Check license
    license_manager = LicenseManager()
    is_licensed, message = license_manager.check_license()
    
    if not is_licensed:
        # Show license activation dialog
        license_dialog = LicenseDialog()
        
        # If user closed the window or chose to exit, close the application
        result = license_dialog.exec()
        if result != QDialog.Accepted:
            sys.exit(0)
        
        # Re-check license
        is_licensed, message = license_manager.check_license()
        if not is_licensed:
            QMessageBox.critical(
                None,
                "License Error",
                "No valid license found. Application will close.",
                QMessageBox.Ok
            )
            sys.exit(0)
    
    # Integrate asyncio with Qt event loop
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = AppHandler(startup_import_folder=startup_import_folder)
    window.show()

    # â”€â”€ Diagnostic mode (AIPACS_DIAG_MODE=1) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if os.environ.get("AIPACS_DIAG_MODE") == "1":
        try:
            from diagnostic_hooks import hook_manager as _hm
            _hm.attach_to_app(window)
        except Exception as _diag_exc:
            import logging as _log
            _log.getLogger(__name__).warning(
                "DiagHooks: attach_to_app failed: %s", _diag_exc
            )
    # â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    # Global disk usage alert checks (modular service)
    app._disk_alert_service = DiskUsageAlertService(
        parent_widget=window,
        threshold_percent=90.0,
        interval_ms=5 * 60 * 1000,
    )
    app._disk_alert_service.start(initial_delay_ms=2000)

    # Store lock on app for cleanup on exit
    app._instance_lock = instance_lock

    # sys.exit(app.exec())
    try:
        with loop:
            loop.run_forever()
    finally:
        # Clean up single-instance lock on shutdown
        instance_lock.release()
        logging.getLogger(__name__).info("Application shutdown: instance lock released")
