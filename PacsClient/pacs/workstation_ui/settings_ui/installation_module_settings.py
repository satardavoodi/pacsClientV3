from __future__ import annotations

import os
import sys

from PySide6.QtCore import QThread, Qt, Signal, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from aipacs_runtime import (
    RESPECT_DEV_MODULE_PROFILE_ENV,
    discover_module_packages,
    install_module_package,
    is_frozen,
    module_installation_statuses,
    module_runtime_dir,
    modules_runtime_root,
    set_module_enabled,
    validate_module_installation,
)


class ModuleInstallWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, source: str, expected_module_id: str | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.source = source
        self.expected_module_id = expected_module_id

    def run(self) -> None:
        try:
            result = install_module_package(self.source, expected_module_id=self.expected_module_id)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class InstallationModuleSettingsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: ModuleInstallWorker | None = None
        self._records: list[dict] = []
        self._setup_ui()
        self.refresh_modules()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Installation Module")
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        root.addWidget(title)

        intro = QLabel(
            "Install optional workstation modules from a package file, a folder of packages, "
            "or a direct URL. Module activation is stored per workstation and usually requires restart."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        if not is_frozen():
            dev_note = QLabel(
                "Developer note: source runs keep all modules visible unless "
                f"`{RESPECT_DEV_MODULE_PROFILE_ENV}=1` is set."
            )
            dev_note.setWordWrap(True)
            root.addWidget(dev_note)

        summary_box = QGroupBox("Package Workflow")
        summary_layout = QGridLayout(summary_box)
        summary_layout.addWidget(QLabel("1. Select a module row."), 0, 0)
        summary_layout.addWidget(QLabel("2. Install package from file, folder, or URL."), 1, 0)
        summary_layout.addWidget(QLabel("3. Run a test and restart the workstation if required."), 2, 0)
        root.addWidget(summary_box)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_modules)
        actions.addWidget(self.refresh_btn)

        self.install_file_btn = QPushButton("Install Package...")
        self.install_file_btn.clicked.connect(self.install_from_file)
        actions.addWidget(self.install_file_btn)

        self.install_folder_btn = QPushButton("Install From Folder...")
        self.install_folder_btn.clicked.connect(self.install_from_folder)
        actions.addWidget(self.install_folder_btn)

        self.install_url_btn = QPushButton("Install From URL...")
        self.install_url_btn.clicked.connect(self.install_from_url)
        actions.addWidget(self.install_url_btn)

        self.toggle_btn = QPushButton("Enable")
        self.toggle_btn.clicked.connect(self.toggle_selected_module)
        actions.addWidget(self.toggle_btn)

        self.test_btn = QPushButton("Test Module")
        self.test_btn.clicked.connect(self.test_selected_module)
        actions.addWidget(self.test_btn)

        self.open_runtime_btn = QPushButton("Open Runtime Folder")
        self.open_runtime_btn.clicked.connect(self.open_runtime_folder)
        actions.addWidget(self.open_runtime_btn)

        actions.addStretch(1)
        root.addLayout(actions)

        self.table = QTableWidget(0, 7, self)
        self.table.setHorizontalHeaderLabels(
            ["Module", "Tier", "Package", "Installed", "Enabled", "Version", "Source"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._sync_button_state)
        root.addWidget(self.table, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

    def _selected_record(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _sync_button_state(self) -> None:
        record = self._selected_record()
        if not record:
            self.toggle_btn.setText("Enable")
            return
        self.toggle_btn.setText("Disable" if record.get("enabled") else "Enable")

    def _set_busy(self, busy: bool, message: str = "") -> None:
        for button in (
            self.refresh_btn,
            self.install_file_btn,
            self.install_folder_btn,
            self.install_url_btn,
            self.toggle_btn,
            self.test_btn,
            self.open_runtime_btn,
        ):
            button.setEnabled(not busy)
        self.status_label.setText(message)

    def refresh_modules(self) -> None:
        self._records = module_installation_statuses()
        self.table.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            values = [
                str(record.get("title") or ""),
                str(record.get("tier") or ""),
                str(record.get("package_kind") or ""),
                "Yes" if record.get("installed") else "No",
                "Yes" if record.get("enabled") else "No",
                str(record.get("installed_version") or "-"),
                str(record.get("installed_from") or record.get("runtime_path") or "-"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, record.get("module_id"))
                self.table.setItem(row, column, item)
        if self._records and self.table.currentRow() < 0:
            self.table.selectRow(0)
        self._sync_button_state()
        self.status_label.setText(
            "Optional modules are enabled per workstation. Restart after install or enable/disable changes."
        )

    def _start_install(self, source: str, expected_module_id: str | None = None) -> None:
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "Installation Module", "A package install is already running.")
            return
        self._worker = ModuleInstallWorker(source, expected_module_id=expected_module_id, parent=self)
        self._worker.succeeded.connect(self._on_install_succeeded)
        self._worker.failed.connect(self._on_install_failed)
        self._worker.finished.connect(self._on_install_finished)
        self._set_busy(True, f"Installing package from: {source}")
        self._worker.start()

    def _on_install_succeeded(self, record: dict) -> None:
        self.refresh_modules()
        QMessageBox.information(
            self,
            "Installation Module",
            f"{record.get('title', 'Module')} installed successfully.\n\nRestart the workstation to load all UI hooks cleanly.",
        )

    def _on_install_failed(self, error: str) -> None:
        QMessageBox.critical(self, "Installation Module", error)

    def _on_install_finished(self) -> None:
        self._set_busy(False)
        self._worker = None

    def install_from_file(self) -> None:
        selected = self._selected_record()
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Module Package",
            "",
            "Module Packages (*.zip)",
        )
        if not path:
            return
        self._start_install(path, expected_module_id=selected.get("module_id") if selected else None)

    def install_from_folder(self) -> None:
        selected = self._selected_record()
        folder = QFileDialog.getExistingDirectory(self, "Select Package Folder")
        if not folder:
            return
        try:
            packages = discover_module_packages(folder)
        except Exception as exc:
            QMessageBox.critical(self, "Installation Module", str(exc))
            return
        if not packages:
            QMessageBox.information(self, "Installation Module", "No module packages were found in that folder.")
            return
        if len(packages) == 1:
            chosen = packages[0]
        else:
            labels = [
                f"{pkg.get('title', pkg.get('module_id'))}  [{pkg.get('module_id')}]  v{pkg.get('version', '-')}"
                for pkg in packages
            ]
            label, ok = QInputDialog.getItem(self, "Select Package", "Package", labels, 0, False)
            if not ok:
                return
            chosen = packages[labels.index(label)]
        self._start_install(
            str(chosen.get("source_path") or ""),
            expected_module_id=selected.get("module_id") if selected else None,
        )

    def install_from_url(self) -> None:
        selected = self._selected_record()
        url, ok = QInputDialog.getText(
            self,
            "Install From URL",
            "Direct URL to module package (.zip):",
        )
        if not ok or not url.strip():
            return
        self._start_install(url.strip(), expected_module_id=selected.get("module_id") if selected else None)

    def toggle_selected_module(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Installation Module", "Select a module first.")
            return
        try:
            set_module_enabled(str(record.get("module_id")), not bool(record.get("enabled")))
        except Exception as exc:
            QMessageBox.warning(self, "Installation Module", str(exc))
            return
        self.refresh_modules()
        QMessageBox.information(
            self,
            "Installation Module",
            "Module state saved.\n\nRestart the workstation to refresh the menu and Settings surface cleanly.",
        )

    def test_selected_module(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, "Installation Module", "Select a module first.")
            return
        result = validate_module_installation(str(record.get("module_id")))
        if result.get("ok"):
            QMessageBox.information(self, "Module Test", str(result.get("message") or "Module is ready."))
        else:
            QMessageBox.warning(self, "Module Test", str(result.get("message") or "Module test failed."))

    def open_runtime_folder(self) -> None:
        record = self._selected_record()
        target = module_runtime_dir(str(record.get("module_id"))) if record else modules_runtime_root()
        target.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
