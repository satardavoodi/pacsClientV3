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
    CORE_COMPONENT_ID,
    RESPECT_DEV_MODULE_PROFILE_ENV,
    discover_module_packages,
    install_component_update,
    install_module_package,
    is_frozen,
    launch_core_update_installer,
    load_update_sources,
    module_installation_statuses,
    module_runtime_dir,
    modules_runtime_root,
    save_update_sources,
    set_module_enabled,
    summarize_available_updates,
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


class ModuleUpdateWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, component_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.component_id = component_id

    def run(self) -> None:
        try:
            result = install_component_update(self.component_id)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(result)


class CoreUpdateWorker(QThread):
    succeeded = Signal(str)
    failed = Signal(str)

    def run(self) -> None:
        try:
            path = launch_core_update_installer()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(str(path))


class InstallationModuleSettingsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._worker: ModuleInstallWorker | None = None
        self._update_worker: ModuleUpdateWorker | None = None
        self._core_update_worker: CoreUpdateWorker | None = None
        self._records: list[dict] = []
        self._update_records: list[dict] = []
        self._setup_ui()
        self.refresh_modules()
        self.refresh_updates()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        title = QLabel("Installation & Updates")
        title.setStyleSheet("font-size: 22px; font-weight: 800;")
        root.addWidget(title)

        intro = QLabel(
            "Install optional workstation modules from a package file, a folder of packages, "
            "or a direct URL. Packages selected during workstation setup are applied on first launch. "
            "This page also checks for newer core or module releases from a configured update source."
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
        summary_layout.addWidget(QLabel("3. Check the update source for newer core or module versions."), 2, 0)
        summary_layout.addWidget(QLabel("4. Run a test and restart the workstation if required."), 3, 0)
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

        update_box = QGroupBox("Update Source")
        update_layout = QVBoxLayout(update_box)

        self.update_source_label = QLabel("")
        self.update_source_label.setWordWrap(True)
        update_layout.addWidget(self.update_source_label)

        update_actions = QHBoxLayout()
        update_actions.setSpacing(8)

        self.check_updates_btn = QPushButton("Check Updates")
        self.check_updates_btn.clicked.connect(self.refresh_updates)
        update_actions.addWidget(self.check_updates_btn)

        self.set_update_folder_btn = QPushButton("Set Update Folder...")
        self.set_update_folder_btn.clicked.connect(self.set_update_folder)
        update_actions.addWidget(self.set_update_folder_btn)

        self.set_update_url_btn = QPushButton("Set Update URL...")
        self.set_update_url_btn.clicked.connect(self.set_update_url)
        update_actions.addWidget(self.set_update_url_btn)

        self.apply_update_btn = QPushButton("Apply Selected Update")
        self.apply_update_btn.clicked.connect(self.apply_selected_update)
        update_actions.addWidget(self.apply_update_btn)

        self.open_update_source_btn = QPushButton("Open Update Source")
        self.open_update_source_btn.clicked.connect(self.open_update_source)
        update_actions.addWidget(self.open_update_source_btn)

        update_actions.addStretch(1)
        update_layout.addLayout(update_actions)

        self.update_table = QTableWidget(0, 6, self)
        self.update_table.setHorizontalHeaderLabels(
            ["Component", "Current", "Available", "Status", "Delivery", "Artifact"]
        )
        self.update_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.update_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.update_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.update_table.verticalHeader().setVisible(False)
        self.update_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.update_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.update_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.update_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.update_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.update_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.update_table.setMinimumHeight(220)
        self.update_table.itemSelectionChanged.connect(self._sync_update_buttons)
        update_layout.addWidget(self.update_table)

        self.update_status_label = QLabel("")
        self.update_status_label.setWordWrap(True)
        update_layout.addWidget(self.update_status_label)

        root.addWidget(update_box)

    def _selected_record(self) -> dict | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._records):
            return None
        return self._records[row]

    def _selected_update_record(self) -> dict | None:
        row = self.update_table.currentRow()
        if row < 0 or row >= len(self._update_records):
            return None
        return self._update_records[row]

    def _sync_button_state(self) -> None:
        record = self._selected_record()
        if not record:
            self.toggle_btn.setText("Enable")
            return
        self.toggle_btn.setText("Disable" if record.get("enabled") else "Enable")

    def _sync_update_buttons(self) -> None:
        record = self._selected_update_record()
        if not record:
            self.apply_update_btn.setEnabled(False)
            return
        self.apply_update_btn.setEnabled(record.get("status") in {"update_available", "available", "not_installed"})

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

    def _set_update_busy(self, busy: bool, message: str = "") -> None:
        for button in (
            self.check_updates_btn,
            self.set_update_folder_btn,
            self.set_update_url_btn,
            self.apply_update_btn,
            self.open_update_source_btn,
        ):
            button.setEnabled(not busy)
        self.update_status_label.setText(message)

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
            "Optional modules are enabled per workstation. Setup-selected packages are applied automatically on first start. "
            "Restart after install or enable/disable changes."
        )

    def refresh_updates(self) -> None:
        sources = load_update_sources()
        active_source = next(
            (
                source
                for source in sources.get("sources", [])
                if isinstance(source, dict) and str(source.get("id") or "") == str(sources.get("active_source_id") or "")
            ),
            None,
        )
        if active_source is None:
            active_source = {"title": "Primary Update Source", "type": "file", "location": ""}
        source_title = str(active_source.get("title") or "Primary Update Source")
        source_type = str(active_source.get("type") or "file").strip().lower()
        source_location = str(active_source.get("location") or "").strip()
        self.update_source_label.setText(
            f"Active source: {source_title}\n"
            f"Type: {source_type or 'file'}\n"
            f"Location: {source_location or '(not configured)'}"
        )

        if not source_location:
            self._update_records = []
            self.update_table.setRowCount(0)
            self.update_status_label.setText(
                "No update source is configured yet. Set a local updates folder or a feed URL to check for newer releases."
            )
            self._sync_update_buttons()
            return

        try:
            summary = summarize_available_updates()
        except Exception as exc:
            self._update_records = []
            self.update_table.setRowCount(0)
            self.update_status_label.setText(f"Update check failed: {exc}")
            self._sync_update_buttons()
            return

        records = [summary["core"], *summary["components"]]
        self._update_records = records
        self.update_table.setRowCount(len(records))
        for row, record in enumerate(records):
            values = [
                str(record.get("title") or ""),
                str(record.get("current_version") or "-"),
                str(record.get("available_version") or "-"),
                str(record.get("status") or ""),
                str(record.get("delivery") or record.get("artifact_type") or ""),
                str(record.get("artifact_path") or "-"),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, record.get("component_id"))
                self.update_table.setItem(row, column, item)
        if records and self.update_table.currentRow() < 0:
            self.update_table.selectRow(0)

        if summary.get("has_updates"):
            self.update_status_label.setText(
                "Newer update content is available from the configured source. "
                "Core updates use the installer, while optional modules can be updated in place."
            )
        else:
            self.update_status_label.setText(
                "The configured source was checked successfully. Everything shown here is already up to date."
            )
        self._sync_update_buttons()

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

    def _start_module_update(self, component_id: str) -> None:
        if self._update_worker is not None and self._update_worker.isRunning():
            QMessageBox.information(self, "Installation Module", "A module update is already running.")
            return
        self._update_worker = ModuleUpdateWorker(component_id, parent=self)
        self._update_worker.succeeded.connect(self._on_module_update_succeeded)
        self._update_worker.failed.connect(self._on_module_update_failed)
        self._update_worker.finished.connect(self._on_module_update_finished)
        self._set_update_busy(True, f"Applying update for: {component_id}")
        self._update_worker.start()

    def _on_module_update_succeeded(self, record: dict) -> None:
        self.refresh_modules()
        self.refresh_updates()
        QMessageBox.information(
            self,
            "Installation Module",
            f"{record.get('title', 'Module')} updated successfully.\n\nRestart the workstation to load the updated module cleanly.",
        )

    def _on_module_update_failed(self, error: str) -> None:
        QMessageBox.critical(self, "Installation Module", error)

    def _on_module_update_finished(self) -> None:
        self._set_update_busy(False)
        self._update_worker = None

    def _start_core_update(self) -> None:
        if self._core_update_worker is not None and self._core_update_worker.isRunning():
            QMessageBox.information(self, "Installation Module", "The core update installer is already being prepared.")
            return
        self._core_update_worker = CoreUpdateWorker(parent=self)
        self._core_update_worker.succeeded.connect(self._on_core_update_succeeded)
        self._core_update_worker.failed.connect(self._on_core_update_failed)
        self._core_update_worker.finished.connect(self._on_core_update_finished)
        self._set_update_busy(True, "Preparing and launching the core installer update...")
        self._core_update_worker.start()

    def _on_core_update_succeeded(self, installer_path: str) -> None:
        QMessageBox.information(
            self,
            "Installation Module",
            "The core update installer was launched successfully.\n\n"
            f"Installer: {installer_path}\n\n"
            "Complete the installer wizard to update this workstation. Restart AIPacs after setup finishes.",
        )

    def _on_core_update_failed(self, error: str) -> None:
        QMessageBox.critical(self, "Installation Module", error)

    def _on_core_update_finished(self) -> None:
        self._set_update_busy(False)
        self._core_update_worker = None

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

    def set_update_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Update Folder")
        if not folder:
            return
        save_update_sources(
            {
                "active_source_id": "primary",
                "sources": [
                    {
                        "id": "primary",
                        "title": "Primary Update Source",
                        "type": "file",
                        "location": folder,
                        "channel": "stable",
                    }
                ],
            }
        )
        self.refresh_updates()

    def set_update_url(self) -> None:
        current = load_update_sources()
        current_location = ""
        for source in current.get("sources", []):
            if isinstance(source, dict) and str(source.get("id") or "") == str(current.get("active_source_id") or ""):
                current_location = str(source.get("location") or "")
                break
        url, ok = QInputDialog.getText(
            self,
            "Set Update URL",
            "Update feed URL or update folder URL:",
            text=current_location,
        )
        if not ok or not url.strip():
            return
        save_update_sources(
            {
                "active_source_id": "primary",
                "sources": [
                    {
                        "id": "primary",
                        "title": "Primary Update Source",
                        "type": "url",
                        "location": url.strip(),
                        "channel": "stable",
                    }
                ],
            }
        )
        self.refresh_updates()

    def apply_selected_update(self) -> None:
        record = self._selected_update_record()
        if not record:
            QMessageBox.information(self, "Installation Module", "Select an update row first.")
            return

        component_id = str(record.get("component_id") or "").strip()
        status = str(record.get("status") or "").strip()
        if status not in {"update_available", "available", "not_installed"}:
            QMessageBox.information(self, "Installation Module", "The selected component is already up to date.")
            return

        if component_id == CORE_COMPONENT_ID:
            self._start_core_update()
            return

        self._start_module_update(component_id)

    def open_update_source(self) -> None:
        source = load_update_sources()
        active_source = next(
            (
                item
                for item in source.get("sources", [])
                if isinstance(item, dict) and str(item.get("id") or "") == str(source.get("active_source_id") or "")
            ),
            None,
        )
        if active_source is None:
            QMessageBox.information(self, "Installation Module", "No update source is configured.")
            return

        location = str(active_source.get("location") or "").strip()
        if not location:
            QMessageBox.information(self, "Installation Module", "No update source is configured.")
            return

        if location.lower().startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(location))
            return

        target = location
        if os.path.isfile(target):
            target = os.path.dirname(target)
        if sys.platform == "win32":
            os.startfile(target)  # type: ignore[attr-defined]
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(target))

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
