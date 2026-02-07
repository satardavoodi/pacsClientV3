import sys
import os

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
from PacsClient import AppHandler
from PacsClient.utils.font_manager import load_fonts, setup_font_rendering
from PacsClient.utils import LicenseManager, LicenseDialog
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

import os

# os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
#     "--disable-gpu --in-process-gpu --disable-gpu-compositing "
#     "--disable-features=VizDisplayCompositor,UseSkiaRenderer "
#     "--use-angle=d3d11 --ignore-gpu-blocklist"
# )

if sys.platform == 'win32':
    # Use software rendering for maximum compatibility
    os.environ["QT_OPENGL"] = "software"
    os.environ["QSG_RHI_BACKEND"] = "software"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu --in-process-gpu --disable-gpu-compositing --enable-media-stream"

if __name__ == "__main__":
    # Set working directory to _internal for PyInstaller builds
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller executable
        os.chdir(sys._MEIPASS)
    
    # Set Qt attributes BEFORE creating QApplication
    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)  # Compatible with software rendering
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)  # Better performance for detached tabs
    
    app = QApplication(sys.argv)

    # Get the absolute path to the icon
    # icon_path = os.path.join(os.path.dirname(__file__), "PacsClient", "login", "images", "favicon.ico")
    icon_path = str(IMAGES_LOGIN_PATH / "favicon.ico")

    # Set application icon for taskbar and window
    app.setWindowIcon(QIcon(icon_path))

    # Set application properties for Windows taskbar
    app.setApplicationName("AIPacs")
    # app.setApplicationDisplayName("AIPacs - Professional Medical Imaging Suite")
    app.setApplicationDisplayName("AIPacs")
    app.setApplicationVersion("1.0.7")
    app.setOrganizationName("AIPacs")

    # Setup font rendering for better quality
    setup_font_rendering()

    # Load Roboto fonts
    load_fonts()
    
    # Set global stylesheet for dialogs and message boxes (dark theme)
    app.setStyleSheet("""
        QMessageBox {
            background-color: #1a202c;
        }
        QMessageBox QLabel {
            color: #e2e8f0;
            font-size: 13px;
        }
        QMessageBox QPushButton {
            background-color: #3182ce;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px 20px;
            font-size: 13px;
            min-width: 80px;
        }
        QMessageBox QPushButton:hover {
            background-color: #2c5aa0;
        }
        QMessageBox QPushButton:pressed {
            background-color: #1e4a8a;
        }
        QInputDialog {
            background-color: #1a202c;
        }
        QInputDialog QLabel {
            color: #e2e8f0;
            font-size: 13px;
        }
        QInputDialog QLineEdit {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 8px;
            font-size: 13px;
        }
        QInputDialog QPushButton {
            background-color: #3182ce;
            color: #ffffff;
            border: none;
            border-radius: 6px;
            padding: 8px 20px;
            font-size: 13px;
            min-width: 80px;
        }
        QInputDialog QPushButton:hover {
            background-color: #2c5aa0;
        }
        QFileDialog {
            background-color: #1a202c;
        }
        QFileDialog QLabel {
            color: #e2e8f0;
        }
        QFileDialog QLineEdit {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 6px;
        }
        QFileDialog QTreeView, QFileDialog QListView {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
        }
        QFileDialog QTreeView::item:selected, QFileDialog QListView::item:selected {
            background-color: #3182ce;
        }
        QFileDialog QPushButton {
            background-color: #3182ce;
            color: #ffffff;
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
            min-width: 70px;
        }
        QFileDialog QPushButton:hover {
            background-color: #2c5aa0;
        }
        QFileDialog QComboBox {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 6px;
        }
        QFileDialog QComboBox QAbstractItemView {
            background-color: #2d3748;
            color: #e2e8f0;
            selection-background-color: #3182ce;
        }
        QColorDialog {
            background-color: #1a202c;
        }
        QColorDialog QLabel {
            color: #e2e8f0;
        }
        QColorDialog QPushButton {
            background-color: #3182ce;
            color: #ffffff;
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
        }
        QColorDialog QLineEdit {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 4px;
        }
        QFontDialog {
            background-color: #1a202c;
        }
        QFontDialog QLabel {
            color: #e2e8f0;
        }
        QFontDialog QLineEdit {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 4px;
        }
        QFontDialog QListView {
            background-color: #2d3748;
            color: #e2e8f0;
            border: 1px solid #4a5568;
        }
        QFontDialog QPushButton {
            background-color: #3182ce;
            color: #ffffff;
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
        }
        QProgressDialog {
            background-color: #1a202c;
        }
        QProgressDialog QLabel {
            color: #e2e8f0;
            font-size: 13px;
        }
        QProgressDialog QProgressBar {
            background-color: #2d3748;
            border: none;
            border-radius: 4px;
            text-align: center;
            color: #e2e8f0;
        }
        QProgressDialog QProgressBar::chunk {
            background-color: #3182ce;
            border-radius: 4px;
        }
        QProgressDialog QPushButton {
            background-color: #4a5568;
            color: #e2e8f0;
            border: none;
            border-radius: 4px;
            padding: 6px 16px;
        }
        QProgressDialog QPushButton:hover {
            background-color: #374151;
        }
        QToolTip {
            background-color: #1a202c;
            color: #e2e8f0;
            border: 1px solid #4a5568;
            border-radius: 4px;
            padding: 4px 8px;
        }
        
        /* Remove default focus outlines globally */
        *:focus {
            outline: none;
        }
        QWidget:focus {
            outline: none;
        }
        QPushButton:focus {
            outline: none;
        }
        QLineEdit:focus {
            outline: none;
        }
        QComboBox:focus {
            outline: none;
        }
        QCheckBox:focus {
            outline: none;
        }
        QRadioButton:focus {
            outline: none;
        }
        QSpinBox:focus {
            outline: none;
        }
        QDoubleSpinBox:focus {
            outline: none;
        }
        QTextEdit:focus {
            outline: none;
        }
        QPlainTextEdit:focus {
            outline: none;
        }
        QListView:focus {
            outline: none;
        }
        QTreeView:focus {
            outline: none;
        }
        QTableView:focus {
            outline: none;
        }
        QTableWidget:focus {
            outline: none;
        }
        QSlider:focus {
            outline: none;
        }
        QScrollBar:focus {
            outline: none;
        }
        QTabBar:focus {
            outline: none;
        }
        QTabBar::tab:focus {
            outline: none;
        }
        QGroupBox:focus {
            outline: none;
        }
    """)
    
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

    # === CRITICAL: Application-level cleanup handler ===
    # Ensures all download state is cleared on app shutdown
    # This runs even if individual widget closeEvents aren't called
    def cleanup_on_quit():
        """Clean up all download state when application is about to quit"""
        try:
            print("🧹 Application shutting down - preserving download history...")

            # Stop any active download workers before closing event loop
            try:
                from PacsClient.components import zeta_adapter
                worker_pool = getattr(zeta_adapter, "_zeta_worker_pool", None)
                if worker_pool:
                    worker_pool.stop_all()
                dm_widget = getattr(zeta_adapter, "_zeta_download_manager_widget", None)
                if dm_widget and hasattr(dm_widget, "worker_pool"):
                    dm_widget.worker_pool.stop_all()
            except Exception as e:
                print(f"⚠️ Error stopping download workers: {e}")

            # IMPORTANT: DO NOT clear database download progress records!
            # They need to persist across app restarts so users don't re-download completed studies
            # from PacsClient.utils.database import clear_all_download_progress
            # cleared = clear_all_download_progress()
            # if cleared > 0:
            #     print(f"   ✅ Cleared {cleared} database progress records")
            print("   ℹ️  Database history preserved (for 'Already Downloaded' checks)")

            # Clear UI persistence file so Download Manager list is empty on restart
            # (Database still remembers what was downloaded for checking)
            import sys
            from pathlib import Path

            # Get persistence file path (same logic as in download_manager_ui.py)
            if sys.platform == "win32":
                import os
                appdata_path = os.getenv('LOCALAPPDATA')
                if appdata_path:
                    persistence_file = Path(appdata_path) / 'AIPACS' / 'DownloadManager' / 'download_manager_state.json'
                else:
                    persistence_file = Path.home() / 'AppData' / 'Local' / 'AIPACS' / 'DownloadManager' / 'download_manager_state.json'
            elif sys.platform == "darwin":
                persistence_file = Path.home() / 'Library' / 'Application Support' / 'AIPACS' / 'DownloadManager' / 'download_manager_state.json'
            else:
                import os
                config_dir = os.getenv('XDG_CONFIG_HOME', Path.home() / '.config')
                persistence_file = Path(config_dir) / 'aipacs' / 'download_manager' / 'download_manager_state.json'

            if persistence_file.exists():
                persistence_file.unlink()
                print(f"   ✅ Cleared UI list (Download Manager will be empty on restart)")

            # Note: We also preserve progress files for resumable downloads
            # These allow incomplete downloads to resume from where they left off
            # try:
            #     from PacsClient.utils.config import SOURCE_PATH
            #     progress_dir = SOURCE_PATH / '.progress'
            #     if progress_dir.exists():
            #         for progress_file in progress_dir.glob('*.json'):
            #             try:
            #                 progress_file.unlink()
            #             except:
            #                 pass
            #         print(f"   ✅ Cleared progress files from {progress_dir}")
            # except Exception as e:
            #     print(f"   ⚠️ Could not clear progress files: {e}")

            print("✅ Shutdown complete:")
            print("   - Database history preserved (for 'Already Downloaded' checks)")
            print("   - UI list cleared (Download Manager will be empty on restart)")

        except Exception as e:
            print(f"⚠️ Error during shutdown cleanup: {e}")
        finally:
            # Only request stop here; final close happens after loop.run_forever()
            try:
                if loop.is_running():
                    loop.stop()
            except Exception as e:
                print(f"⚠️ Error stopping event loop: {e}")

    # Connect cleanup handler to aboutToQuit signal
    app.aboutToQuit.connect(cleanup_on_quit)
    # === END cleanup handler ===

    window = AppHandler()
    window.show()
    # sys.exit(app.exec())
    with loop:
        try:
            loop.run_forever()
        finally:
            # Ensure the loop is closed when exiting
            if not loop.is_closed():
                loop.close()
                print("✅ Event loop closed")