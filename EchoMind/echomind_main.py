from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_repo_on_path() -> Path:
    root = Path(__file__).resolve().parents[1]
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    # Remove the EchoMind script directory so sibling modules are
    # resolved through the *package* (enabling relative imports).
    echo_dir = str(Path(__file__).resolve().parent)
    while echo_dir in sys.path:
        sys.path.remove(echo_dir)
    return root


def _configure_qt_env() -> None:
    if sys.platform == "win32":
        os.environ.setdefault("QT_OPENGL", "software")
        os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")
        chromium_flags = (
            "--disable-gpu --in-process-gpu --disable-gpu-compositing --enable-media-stream "
            "--disable-features=VizDisplayCompositor,UseSkiaRenderer"
        )
        if not getattr(sys, "frozen", False):
            os.environ.setdefault("QTWEBENGINE_DISABLE_GPU", "1")
            chromium_flags += " --use-angle=swiftshader"
        os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", chromium_flags)
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
        os.environ.setdefault("QMLSCENE_DEVICE", "softwarecontext")
        os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")


def main() -> int:
    root = _ensure_repo_on_path()
    _configure_qt_env()

    if getattr(sys, "frozen", False):
        os.chdir(sys._MEIPASS)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    QApplication.setAttribute(Qt.AA_UseSoftwareOpenGL, True)
    QApplication.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)

    app = QApplication(sys.argv)
    app.setApplicationName("EchoMind")
    app.setApplicationDisplayName("EchoMind")
    app.setApplicationVersion("1.0.0")
    app.setOrganizationName("EchoMind")

    try:
        from PacsClient.utils.font_manager import load_fonts

        load_fonts()
    except Exception:
        pass

    try:
        from PacsClient.utils import config as pc_config

        qss_candidates = [
            pc_config.BASE_PATH / "Qss" / "main.qss",
            pc_config.BASE_PATH / "Qss" / "defaultStyle.qss",
            pc_config.BASE_PATH / "Qss" / "style.qss",
        ]
        for qss_path in qss_candidates:
            if qss_path.exists():
                app.setStyleSheet(qss_path.read_text(encoding="utf-8"))
                break
    except Exception:
        pass

    # Ensure dialogs use a readable gray theme even when no QSS is loaded.
    message_box_style = """
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
    """
    app.setStyleSheet((app.styleSheet() or "") + "\n" + message_box_style)

    try:
        from PacsClient.utils import IMAGES_LOGIN_PATH
        icon_candidates = [
            IMAGES_LOGIN_PATH / "ai_pacs_logo.svg",
            IMAGES_LOGIN_PATH / "aiLogo.png",
            IMAGES_LOGIN_PATH / "favicon.ico",
        ]
        for icon_path in icon_candidates:
            if os.path.exists(icon_path):
                app.setWindowIcon(QIcon(str(icon_path)))
                break
    except Exception:
        pass

    from EchoMind.ai_chat_viewer import AIChatViewer

    viewer = AIChatViewer()
    viewer.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
