import sys
import os
import multiprocessing   # freeze_support() required for subprocess spawn in PyInstaller builds

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
from PacsClient.utils.scroll_style import get_scroll_area_style
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
from PacsClient.utils.disk_alert_service import DiskUsageAlertService

import os

# os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
#     "--disable-gpu --in-process-gpu --disable-gpu-compositing "
#     "--disable-features=VizDisplayCompositor,UseSkiaRenderer "
#     "--use-angle=d3d11 --ignore-gpu-blocklist"
# )

if sys.platform == "win32":
    # Use software rendering for maximum compatibility
    os.environ["QT_OPENGL"] = "software"
    os.environ["QT_QUICK_BACKEND"] = "software"
    chromium_flags = "--disable-gpu --in-process-gpu --disable-gpu-compositing --enable-media-stream"
    if not getattr(sys, "frozen", False):
        os.environ["QTWEBENGINE_DISABLE_GPU"] = "1"
        chromium_flags += " --use-angle=swiftshader"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = chromium_flags


if __name__ == "__main__":
    # multiprocessing.freeze_support() MUST be the very first call inside
    # if __name__ == '__main__' when the app is frozen with PyInstaller.
    # Without it, every download subprocess spawn would re-run the full
    # application startup, creating an infinite process loop.
    multiprocessing.freeze_support()

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
    app.setApplicationVersion("2.2.2")
    app.setOrganizationName("AIPacs")

    # Setup font rendering for better quality
    setup_font_rendering()

    # Load Roboto fonts
    load_fonts()
    
    # Set global stylesheet for dialogs and message boxes (gray theme)
    app.setStyleSheet("""
        QMessageBox {
            background-color: #2b2f33;
        }
        QMessageBox QLabel {
            color: #f0f3f6;
            font-size: 13px;
        }
        QMessageBox QPushButton {
            background-color: #3a4148;
            color: #f7f9fb;
            border: 1px solid #1f2226;
            border-radius: 6px;
            padding: 6px 18px;
            font-size: 13px;
            min-width: 90px;
        }
        QMessageBox QPushButton:hover {
            background-color: #485057;
        }
        QMessageBox QPushButton:pressed {
            background-color: #343b41;
        }
        QInputDialog {
            background-color: #2b2f33;
        }
        QInputDialog QLabel {
            color: #f0f3f6;
            font-size: 13px;
        }
        QInputDialog QLineEdit {
            background-color: #3a4148;
            color: #f7f9fb;
            border: 1px solid #1f2226;
            border-radius: 4px;
            padding: 6px 8px;
            font-size: 13px;
        }
        QInputDialog QPushButton {
            background-color: #3a4148;
            color: #f7f9fb;
            border: 1px solid #1f2226;
            border-radius: 6px;
            padding: 6px 18px;
            font-size: 13px;
            min-width: 90px;
        }
        QInputDialog QPushButton:hover {
            background-color: #485057;
        }
        QInputDialog QPushButton:pressed {
            background-color: #343b41;
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
    app.setStyleSheet(app.styleSheet() + get_scroll_area_style())
    
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

    window = AppHandler()
    window.show()

    # Global disk usage alert checks (modular service)
    app._disk_alert_service = DiskUsageAlertService(
        parent_widget=window,
        threshold_percent=90.0,
        interval_ms=5 * 60 * 1000,
    )
    app._disk_alert_service.start(initial_delay_ms=2000)

    # sys.exit(app.exec())
    with loop:
        loop.run_forever()