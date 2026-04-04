from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)


class OfflineCloudServerDialog(QDialog):
    """Dialog for adding/editing an Offline Cloud Server folder binding."""

    def __init__(self, parent=None, server_data: dict | None = None):
        super().__init__(parent)
        self._result_data: dict | None = None
        self._initial = server_data or {}
        self._setup_ui()
        self._populate()
        self.setWindowTitle("Offline Cloud Server")
        self.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setMinimumWidth(560)

    def get_server_data(self) -> dict | None:
        return self._result_data

    def _setup_ui(self):
        self.setObjectName("OfflineCloudDialog")
        self.setStyleSheet(
            """
            QDialog#OfflineCloudDialog {
                background: #0b0d10;
                color: #e5e7eb;
            }
            QDialog#OfflineCloudDialog QLabel {
                color: #e5e7eb;
                font-size: 14px;
            }
            QDialog#OfflineCloudDialog QLineEdit {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 7px 10px;
                min-height: 34px;
            }
            QDialog#OfflineCloudDialog QPushButton {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 14px;
                font-weight: 600;
            }
            QDialog#OfflineCloudDialog QPushButton:hover {
                background: #252d3d;
                border-color: #3b82f6;
            }
            QDialog#OfflineCloudDialog QPushButton#primary {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #3b82f6, stop:1 #2563eb);
                color: #ffffff;
                border: 1px solid #2563eb;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(14)

        intro = QLabel(
            "Bind a manual exchange folder as an Offline Cloud Server package root. "
            "This folder can be moved by USB flash drive or synced by Dropbox, Google Drive, "
            "a network share, or any similar tool."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("Name:"), 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Offline Cloud Server Name")
        grid.addWidget(self.name_edit, 0, 1, 1, 2)

        grid.addWidget(QLabel("Folder:"), 1, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(r"C:\Shared\AIPacsOfflineCloud")
        grid.addWidget(self.folder_edit, 1, 1)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_folder)
        grid.addWidget(browse_btn, 1, 2)

        grid.addWidget(QLabel("Description:"), 2, 0)
        self.description_edit = QLineEdit()
        self.description_edit.setPlaceholderText("Optional note shown in Settings")
        grid.addWidget(self.description_edit, 2, 1, 1, 2)

        grid.setColumnStretch(1, 1)
        root.addLayout(grid)

        buttons = QHBoxLayout()
        buttons.addStretch()
        ok_btn = QPushButton("Save")
        ok_btn.setObjectName("primary")
        ok_btn.clicked.connect(self._on_accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(ok_btn)
        buttons.addWidget(cancel_btn)
        root.addLayout(buttons)

    def _populate(self):
        self.name_edit.setText(str(self._initial.get("name") or ""))
        self.folder_edit.setText(str(self._initial.get("folder_path") or ""))
        self.description_edit.setText(str(self._initial.get("description") or ""))

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Offline Cloud Folder",
            self.folder_edit.text().strip() or "",
        )
        if folder:
            self.folder_edit.setText(folder)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        folder_path = self.folder_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Name is required.")
            self.name_edit.setFocus()
            return
        if not folder_path:
            QMessageBox.warning(self, "Validation", "Folder path is required.")
            self.folder_edit.setFocus()
            return

        self._result_data = {
            "name": name,
            "folder_path": folder_path,
            "description": self.description_edit.text().strip(),
        }
        self.accept()
