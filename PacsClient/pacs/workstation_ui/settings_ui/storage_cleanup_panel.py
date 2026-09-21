from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import Callable, Dict

from PySide6.QtCore import QCoreApplication, Signal, Qt, QThread, QObject, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QMessageBox,
    QProgressBar,
    QDialog,
    QRadioButton,
    QSpinBox,
    QButtonGroup,
    QGroupBox,
)

from PacsClient.utils.config import BASE_PATH
from modules.storage.local_storage_cleanup_manager import LocalStorageCleanupManager


_logger = logging.getLogger(__name__)


# A settings panel is transient: it may be destroyed while a long disk cleanup
# is still running.  Parentless QThreads retained here outlive that panel and
# cannot trigger Qt's fatal "QThread: Destroyed while thread is still running".
# The entry also retains the worker wrapper until QThread.finished.
_ACTIVE_STORAGE_JOBS: Dict[QThread, QObject] = {}
_STORAGE_SHUTDOWN_GUARD_INSTALLED = False


def _finish_storage_jobs_before_shutdown() -> None:
    """Let destructive work reach a consistent boundary before Qt teardown."""
    for thread in list(_ACTIVE_STORAGE_JOBS):
        try:
            if thread.isRunning():
                # `quit` is thread-safe and prevents a wait/queued-quit deadlock.
                thread.requestInterruption()
                thread.quit()
                thread.wait()
        except RuntimeError:
            continue


def _ensure_storage_shutdown_guard() -> None:
    global _STORAGE_SHUTDOWN_GUARD_INSTALLED
    if _STORAGE_SHUTDOWN_GUARD_INSTALLED:
        return
    app = QCoreApplication.instance()
    if app is not None:
        app.aboutToQuit.connect(_finish_storage_jobs_before_shutdown)
        _STORAGE_SHUTDOWN_GUARD_INSTALLED = True


def _retain_storage_job(thread: QThread, worker: QObject) -> None:
    _ensure_storage_shutdown_guard()
    _ACTIVE_STORAGE_JOBS[thread] = worker

    def _release() -> None:
        _ACTIVE_STORAGE_JOBS.pop(thread, None)
        try:
            worker.deleteLater()
        except RuntimeError:
            pass
        try:
            thread.deleteLater()
        except RuntimeError:
            pass

    thread.finished.connect(_release)


class _FolderUsageWorker(QObject):
    """Worker that computes folder-size breakdown off the main thread.

    Heavy `rglob("*") + stat()` over patient / education / cache / printing /
    offline-cloud roots used to run synchronously inside
    `StorageCleanupPanelWidget.__init__`, blocking the Qt event loop for
    hundreds of ms to multiple seconds (see G6/G9 stall analysis 2026-04-29).
    Moving it to a QThread keeps the settings panel construction snappy.
    """

    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, manager: LocalStorageCleanupManager, force_refresh: bool):
        super().__init__()
        self._manager = manager
        self._force_refresh = bool(force_refresh)

    @Slot()
    def run(self) -> None:
        try:
            drive_rows = self._manager.get_drive_usage_info()
            sizes = self._manager.get_folder_usage_breakdown(force_refresh=self._force_refresh)
            self.finished.emit(
                {
                    "drive_rows": list(drive_rows or []),
                    "folder_sizes": dict(sizes or {}),
                }
            )
        except Exception as exc:
            _logger.exception("[STORAGE_PANEL] folder usage worker failed: %s", exc)
            try:
                self.failed.emit(str(exc))
            except Exception:
                pass


class _CleanupWorker(QObject):
    """Runs one cleanup_manager call off the GUI thread.

    MEASURED (viewer_diagnostics.log 2026-08-22 10:04): a single "Clear patients"
    click blocked the Qt event loop for **183 seconds** — 181 of that session's
    514 sampled stall stacks were this one call, innermost in
    ``shutil._rmtree_unsafe`` (108) and ``_cleanup_patients_db`` (45). The
    manager methods are pure filesystem + DB with no Qt in them, and
    ``database/_pool.py`` keeps its connections in ``threading.local``, so they
    are safe on a worker — the same reasoning that already moved the folder-size
    scan here (``_FolderUsageWorker`` above).
    """

    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:
            _logger.exception("[STORAGE_PANEL] cleanup worker failed: %s", exc)
            try:
                self.failed.emit(str(exc))
            except Exception:
                pass
            return
        try:
            self.finished.emit(result)
        except Exception:
            pass


class StorageCleanupPanelWidget(QWidget):
    """Reusable panel for storage insights + cleanup actions."""

    storageChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.cleanup_manager = LocalStorageCleanupManager()
        self.folder_size_labels: Dict[str, QLabel] = {}
        self.folder_comp_labels: Dict[str, QLabel] = {}
        self.cleanup_rows_layout: QVBoxLayout | None = None
        self.drive_usage_container: QVBoxLayout | None = None
        self.storage_summary_label: QLabel | None = None
        # Deferred folder-size refresh state (T1 fix 2026-04-29).
        self._folder_size_thread: QThread | None = None
        self._folder_size_worker: _FolderUsageWorker | None = None
        self._folder_size_pending: bool = False
        # Off-GUI-thread cleanup state (2026-08-22 — see _CleanupWorker).
        self._cleanup_thread: QThread | None = None
        self._cleanup_worker: _CleanupWorker | None = None
        self._cleanup_progress = None
        self._cleanup_callback_parent = None
        self._cleanup_done_callback: Callable | None = None
        self._cleanup_fail_callback: Callable | None = None
        self._cleanup_pending_result = None
        self._cleanup_pending_error: str | None = None
        self._activity_probe: Callable[[], list[str]] | None = None
        self._setup_ui()
        # Drive probing and folder sizes are both deferred; disconnected mapped
        # drives must never delay construction of the settings panel.
        self.refresh_storage_insights(force_refresh=True, defer_folder_sizes=True)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)  # Generous outer padding
        layout.setSpacing(20)  # Large vertical spacing between sections

        # Title with larger, bold font
        cleanup_title = QLabel("Local Storage & Database Cleanup")
        cleanup_title.setStyleSheet("font-weight: 700; font-size: 16px; color: #f3f4f6;")
        layout.addWidget(cleanup_title)

        # Description with readable font size
        cleanup_desc = QLabel(
            "Clearing a folder also cleans matching database records. "
            "Core app data (e.g., license and global configuration) is never deleted."
        )
        cleanup_desc.setWordWrap(True)
        # Archetype 2: explicit MinimumExpanding vertical policy so the
        # wrapped description can grow tall when the column narrows. See
        # docs/conventions/RESPONSIVE_UI_CONVENTION.md.
        try:
            from PySide6.QtWidgets import QSizePolicy as _QSP
            cleanup_desc.setSizePolicy(_QSP.Preferred, _QSP.MinimumExpanding)
        except Exception:  # pragma: no cover — defensive
            pass
        cleanup_desc.setStyleSheet(
            "color: #d1d5db; font-size: 14px; padding: 10px; "
            "background-color: #1f2937; border-radius: 6px; line-height: 1.6;"
        )
        layout.addWidget(cleanup_desc)

        layout.addSpacing(15)  # Extra space before drives section

        # Drives section with card-style grouping
        drives_card = QWidget()
        drives_card.setStyleSheet(
            "QWidget { background-color: #111827; border: 1px solid #374151; "
            "border-radius: 8px; padding: 15px; }"
        )
        drives_card_layout = QVBoxLayout(drives_card)
        drives_card_layout.setSpacing(12)
        
        drives_title = QLabel("Overall Computer / Drives Usage")
        drives_title.setStyleSheet("font-weight: 600; font-size: 15px; color: #f9fafb;")
        drives_card_layout.addWidget(drives_title)

        self.drive_usage_container = QVBoxLayout()
        self.drive_usage_container.setSpacing(12)  # More space between drives
        drives_card_layout.addLayout(self.drive_usage_container)
        
        layout.addWidget(drives_card)
        layout.addSpacing(15)  # Extra space before folders section

        # Folders section with card-style grouping
        folders_card = QWidget()
        folders_card.setStyleSheet(
            "QWidget { background-color: #111827; border: 1px solid #374151; "
            "border-radius: 8px; padding: 15px; }"
        )
        folders_card_layout = QVBoxLayout(folders_card)
        folders_card_layout.setSpacing(15)
        
        folders_title = QLabel("Per-Folder Storage Usage Breakdown")
        folders_title.setStyleSheet("font-weight: 600; font-size: 15px; color: #f9fafb;")
        folders_card_layout.addWidget(folders_title)

        refresh_row = QHBoxLayout()
        refresh_btn = QPushButton("🔄  Refresh Storage Info")
        refresh_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 10px 20px; min-height: 40px; "
            "background-color: #3b82f6; border: none; border-radius: 6px; font-weight: 600; } "
            "QPushButton:hover { background-color: #2563eb; }"
        )
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self._on_refresh_storage_info_clicked)
        refresh_row.addWidget(refresh_btn)

        consistency_btn = QPushButton("🩺  Check Consistency")
        consistency_btn.setStyleSheet(
            "QPushButton { font-size: 14px; padding: 10px 20px; min-height: 40px; "
            "background-color: #0d9488; border: none; border-radius: 6px; font-weight: 600; } "
            "QPushButton:hover { background-color: #0f766e; }"
        )
        consistency_btn.setToolTip(
            "Find DB/file mismatches (studies still marked downloaded but whose files "
            "are gone, dangling thumbnails) and optionally repair them so the "
            "green/downloaded status matches the actual local files."
        )
        consistency_btn.setCursor(Qt.PointingHandCursor)
        consistency_btn.clicked.connect(self._on_check_consistency_clicked)
        refresh_row.addWidget(consistency_btn)
        refresh_row.addStretch(1)
        folders_card_layout.addLayout(refresh_row)

        self.storage_summary_label = QLabel("")
        self.storage_summary_label.setStyleSheet(
            "color: #d1d5db; font-size: 14px; padding: 8px; "
            "background-color: #1f2937; border-radius: 4px;"
        )
        self.storage_summary_label.setWordWrap(True)
        folders_card_layout.addWidget(self.storage_summary_label)

        folders_card_layout.addSpacing(10)
        self.cleanup_rows_layout = QVBoxLayout()
        self.cleanup_rows_layout.setSpacing(12)
        folders_card_layout.addLayout(self.cleanup_rows_layout)
        self._rebuild_cleanup_rows()
        
        layout.addWidget(folders_card)
        layout.addStretch(1)

    def _rebuild_cleanup_rows(self):
        if self.cleanup_rows_layout is None:
            return

        while self.cleanup_rows_layout.count():
            item = self.cleanup_rows_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.folder_size_labels = {}
        self.folder_comp_labels = {}
        self._build_cleanup_rows(self.cleanup_rows_layout)

    def _build_cleanup_rows(self, parent_layout: QVBoxLayout):
        folder_map = self.cleanup_manager.get_folder_map()
        rows = [
            ("patients", "Patients Data Folder", "Clear Patients Data"),
            ("education", "Education Folder", "Clear Education"),
            ("cache", "Cache Folder", "Clear Cache"),
            ("printing", "Printing Folder", "Clear Printing"),
        ]
        offline_rows = []
        for key, paths in folder_map.items():
            if not key.startswith("offline_cloud::"):
                continue
            server_name = key.split("::", 1)[1].strip() or "Offline Cloud"
            offline_rows.append(
                (
                    key,
                    f"Offline Cloud Server: {server_name}",
                    "Clear Offline Cloud",
                    paths,
                )
            )

        ordered_rows = [
            (key, label_text, btn_text, folder_map.get(key, []))
            for key, label_text, btn_text in rows
        ] + sorted(offline_rows, key=lambda row: row[1].lower())

        for key, label_text, btn_text, paths in ordered_rows:
            # Each row gets its own card for visual separation
            row_card = QWidget()
            row_card.setStyleSheet(
                "QWidget { background-color: #1f2937; border: 1px solid #4b5563; "
                "border-radius: 6px; padding: 12px; }"
            )
            row_layout = QVBoxLayout(row_card)
            row_layout.setSpacing(10)
            
            # Top: Label and size
            top_row = QHBoxLayout()
            top_row.setSpacing(15)
            
            label = QLabel(label_text)
            label.setStyleSheet("font-size: 14px; font-weight: 600; color: #f9fafb;")
            label.setMinimumWidth(180)
            top_row.addWidget(label)
            
            size_label = QLabel("0 B")
            size_label.setMinimumWidth(100)
            size_label.setStyleSheet(
                "color: #10b981; font-weight: 700; font-size: 14px; "
                "padding: 4px 8px; background-color: #064e3b; border-radius: 4px;"
            )
            self.folder_size_labels[key] = size_label
            top_row.addWidget(size_label)
            
            comp_label = QLabel("0% of used disk")
            comp_label.setMinimumWidth(140)
            comp_label.setStyleSheet("color: #d1d5db; font-size: 14px;")
            self.folder_comp_labels[key] = comp_label
            top_row.addWidget(comp_label)
            
            top_row.addStretch(1)
            
            clear_btn = QPushButton(btn_text)
            clear_btn.setMinimumHeight(36)
            clear_btn.setMinimumWidth(180)
            clear_btn.setCursor(Qt.PointingHandCursor)
            clear_btn.setStyleSheet(
                "QPushButton { background-color: #1d4ed8; border: none; "
                "border-radius: 6px; font-size: 14px; font-weight: 600; "
                "padding: 8px 14px; color: white; } "
                "QPushButton:hover { background-color: #1e40af; }"
            )
            if key == "patients":
                clear_btn.clicked.connect(self._on_clear_patients_clicked)
            else:
                clear_btn.clicked.connect(partial(self._on_clear_category_clicked, category=key))
            top_row.addWidget(clear_btn)
            
            row_layout.addLayout(top_row)
            
            # Bottom: Path (smaller, secondary info)
            path_label = QLabel(" | ".join(str(p) for p in paths))
            path_label.setWordWrap(True)
            path_label.setStyleSheet(
                "color: #9ca3af; font-size: 14px; padding-left: 4px; font-style: italic;"
            )
            row_layout.addWidget(path_label)
            
            parent_layout.addWidget(row_card)

    def _on_clear_patients_clicked(self, _checked=False):
        self._show_patient_cleanup_dialog()

    def _on_clear_category_clicked(self, _checked=False, *, category: str):
        self._handle_cleanup_action(category)

    def _on_refresh_storage_info_clicked(self, _checked=False):
        self.refresh_storage_insights(force_refresh=True, defer_folder_sizes=True)

    def _handle_cleanup_action(self, category: str):
        title_map = {
            "patients": "Patients Data",
            "education": "Education",
            "cache": "Cache",
            "printing": "Printing",
        }
        is_offline_cloud = category.startswith("offline_cloud::")
        pretty = (
            f"Offline Cloud Server: {category.split('::', 1)[1].strip()}"
            if is_offline_cloud
            else title_map.get(category, category)
        )
        detail_line = (
            "This will remove the package payload, then refresh manifest.json so the Offline Cloud package stays valid but empty."
            if is_offline_cloud
            else "Core app data (license/config) will NOT be removed."
        )

        if not self._can_start_destructive_cleanup(self):
            return

        answer = QMessageBox.question(
            self,
            f"Confirm {pretty} Cleanup",
            (
                f"This will permanently clear local {pretty} folder data and related database entries.\n\n"
                f"{detail_line}\n\n"
                "Do you want to continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        try:
            if category == "patients":
                job = self.cleanup_manager.cleanup_patients_folder
            elif category == "education":
                job = self.cleanup_manager.cleanup_education_folder
            elif category == "cache":
                job = self.cleanup_manager.cleanup_cache_folder
            elif category == "printing":
                job = self.cleanup_manager.cleanup_printing_folder
            elif is_offline_cloud:
                job = partial(self.cleanup_manager.cleanup_offline_cloud_folder,
                              category.split("::", 1)[1].strip())
            else:
                raise ValueError(f"Unknown cleanup category: {category}")
        except Exception as e:
            QMessageBox.critical(self, "Cleanup Failed", f"Could not start cleanup:\n{e}")
            return

        # 2026-08-22: same GUI-thread freeze as the patient dialog (measured 183 s
        # on a patients clear) — every one of these categories is an rmtree + DB
        # delete. Run it on the worker with the busy dialog.
        self._run_cleanup_job(
            self, job,
            on_done=self._on_category_cleanup_finished,
            on_fail=self._on_category_cleanup_failed,
        )

    def _on_category_cleanup_finished(self, parent, result) -> None:
        self._close_cleanup_progress()
        try:
            _warn = ""
            if getattr(result, "warnings", None):
                _warn = "\n\n⚠ Warnings:\n- " + "\n- ".join(result.warnings)
            _ok = getattr(result, "success", True)
            QMessageBox.information(
                self,
                "Cleanup Completed" if _ok else "Cleanup Completed With Warnings",
                (
                    f"{result.message}\n\n"
                    f"Folders touched: {result.folders_touched}\n"
                    f"Files deleted: {result.files_deleted}\n"
                    f"DB rows affected: {result.db_rows_affected}"
                    f"{_warn}"
                ),
            )
            self.refresh_storage_insights(force_refresh=True, defer_folder_sizes=True)
            # NOTE: storageChanged is emitted so the rest of the app can refresh
            # patient-list download/green badges to match the now-cleared files.
            # (Disk is the source of truth for download status.)
            self.storageChanged.emit()
        except RuntimeError:
            return  # the panel was closed while the cleanup ran — benign
        except Exception:
            _logger.exception("[STORAGE_PANEL] post-cleanup refresh failed")

    def _on_category_cleanup_failed(self, parent, message: str) -> None:
        self._close_cleanup_progress()
        try:
            QMessageBox.critical(
                self,
                "Cleanup Failed",
                f"Could not complete cleanup:\n{message}",
            )
        except RuntimeError:
            pass

    def _on_check_consistency_clicked(self, _checked=False):
        """Validate DB/file consistency and offer a conservative repair.

        Surfaces the real bug class: a study whose DICOM files were cleared but the
        database still 'knows' it (so it can still show green/downloaded). Repair
        removes those stale DB records (disk is the source of truth) and clears
        dangling thumbnail pointers — it never deletes any files.
        """
        self._run_cleanup_job(
            self,
            self.cleanup_manager.validate_storage_consistency,
            on_done=self._on_consistency_report_ready,
            on_fail=self._on_consistency_job_failed,
            progress_text="Checking database and managed storage consistency…",
            progress_title="Storage Consistency",
        )

    def _on_consistency_report_ready(self, _parent, report: dict) -> None:
        self._close_cleanup_progress()

        counts = report.get("counts", {}) or {}
        n_missing = int(counts.get("db_studies_missing_files", 0))
        n_orphan = int(counts.get("orphan_disk_studies", 0))
        n_thumb = int(counts.get("thumbnails_missing_source", 0))
        repairable = n_missing + n_thumb

        if repairable == 0 and n_orphan == 0:
            QMessageBox.information(
                self, "Storage Consistency",
                f"No inconsistencies found.\n\nDB studies checked: {counts.get('db_studies', 0)}",
            )
            return

        body = (
            f"DB studies whose files are gone (stale downloaded status): {n_missing}\n"
            f"Disk study folders with no DB record: {n_orphan}\n"
            f"Thumbnails pointing at missing files: {n_thumb}\n\n"
        )
        if repairable > 0:
            ans = QMessageBox.question(
                self, "Storage Consistency",
                body + (
                    "Repair will remove the stale DB study records and clear dangling "
                    "thumbnail pointers so the downloaded/green status matches the actual "
                    "files on disk. It will NOT delete any files. Run repair now?"
                ),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                self._run_cleanup_job(
                    self,
                    partial(self.cleanup_manager.repair_storage_consistency, report),
                    on_done=self._on_consistency_repair_ready,
                    on_fail=self._on_consistency_job_failed,
                    progress_text="Repairing database references…",
                    progress_title="Storage Repair",
                )
        else:
            QMessageBox.information(
                self, "Storage Consistency",
                body + "(Orphan disk folders are only reported — they may be a not-yet-indexed import.)",
            )

    def _on_consistency_repair_ready(self, _parent, summary: dict) -> None:
        self._close_cleanup_progress()
        warn = (
            "\n\nWarnings:\n- " + "\n- ".join(summary.get("warnings", []))
            if summary.get("warnings")
            else ""
        )
        QMessageBox.information(
            self,
            "Repair Completed",
            f"Removed stale DB studies: {summary.get('removed_db_studies', 0)}\n"
            f"Cleared dangling thumbnails: {summary.get('nulled_thumbnails', 0)}{warn}",
        )
        self.refresh_storage_insights(force_refresh=True, defer_folder_sizes=True)
        self.storageChanged.emit()

    def set_activity_probe(self, probe: Callable[[], list[str]] | None) -> None:
        """Inject the app-owned download/import/viewer activity boundary."""
        self._activity_probe = probe

    def _can_start_destructive_cleanup(self, parent) -> bool:
        if self._activity_probe is None:
            return True
        try:
            reasons = [str(item) for item in (self._activity_probe() or []) if item]
        except Exception:
            _logger.exception("[STORAGE_PANEL] runtime activity probe failed")
            QMessageBox.warning(
                parent,
                "Cleanup Safety Check Failed",
                "AI-PACS could not verify that local storage is idle. Cleanup was not started.",
            )
            return False
        if not reasons:
            return True
        QMessageBox.warning(
            parent,
            "Local Storage Is In Use",
            "Cleanup was not started. Finish or close these activities first:\n\n- "
            + "\n- ".join(reasons),
        )
        return False

    def _on_consistency_job_failed(self, _parent, message: str) -> None:
        self._close_cleanup_progress()
        QMessageBox.critical(
            self,
            "Consistency Check Failed",
            f"Could not complete the consistency operation:\n{message}",
        )

    def _show_patient_cleanup_dialog(self):
        """Show dialog with patient cleanup filtering options."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Patient Data Cleanup Options")
        dialog.setModal(True)
        dialog.setMinimumWidth(650)  # Wider for comfortable reading
        dialog.setMinimumHeight(550)
        
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(25, 25, 25, 25)  # Generous padding
        layout.setSpacing(20)
        
        # Title
        title_label = QLabel("🗑️  Patient Data Cleanup")
        title_label.setStyleSheet("font-size: 18px; font-weight: 700; color: #f3f4f6;")
        layout.addWidget(title_label)
        
        info_label = QLabel(
            "Choose how to clean patient data. Age is based on when a study was "
            "imported to this computer; legacy rows fall back to download time and "
            "then acquisition date. Matching folders and database entries are removed permanently."
        )
        info_label.setWordWrap(True)
        info_label.setStyleSheet(
            "color: #d1d5db; font-size: 14px; padding: 12px; "
            "background-color: #1f2937; border-radius: 6px; line-height: 1.5;"
        )
        layout.addWidget(info_label)
        
        layout.addSpacing(10)
        
        # Strategy group with enhanced styling
        strategy_group = QGroupBox("Cleanup Strategy")
        strategy_group.setStyleSheet(
            "QGroupBox { font-size: 15px; font-weight: 600; color: #f9fafb; "
            "border: 2px solid #4b5563; border-radius: 8px; padding: 20px 15px 15px 15px; "
            "margin-top: 12px; } "
            "QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; "
            "padding: 4px 10px; background-color: #1f2937; border-radius: 4px; }"
        )
        strategy_layout = QVBoxLayout()
        strategy_layout.setSpacing(18)  # Large spacing between options
        
        radio_group = QButtonGroup(dialog)
        
        # Style for all radio buttons - LARGE and readable
        radio_style = (
            "QRadioButton { font-size: 14px; color: #e5e7eb; spacing: 10px; } "
            "QRadioButton::indicator { width: 20px; height: 20px; }"
        )
        
        # Style for all spinboxes - LARGE controls for 50+ users
        spinbox_style = (
            "QSpinBox { font-size: 15px; font-weight: 600; padding: 8px 12px; "
            "min-width: 120px; min-height: 36px; background-color: #374151; "
            "border: 2px solid #6b7280; border-radius: 6px; color: #f9fafb; } "
            "QSpinBox::up-button { width: 28px; border-left: 2px solid #6b7280; "
            "background-color: #4b5563; } "
            "QSpinBox::down-button { width: 28px; border-left: 2px solid #6b7280; "
            "background-color: #4b5563; } "
            "QSpinBox::up-arrow { width: 12px; height: 12px; } "
            "QSpinBox::down-arrow { width: 12px; height: 12px; }"
        )
        
        from Qss.numeric_controls import numeric_control_style
        spinbox_style += numeric_control_style()

        # Option 1: Clear all
        all_radio = QRadioButton("Clear ALL patient data (folders + database)")
        all_radio.setStyleSheet(radio_style)
        radio_group.addButton(all_radio, 0)
        strategy_layout.addWidget(all_radio)
        
        # Safe default: a bounded local-retention rule, never Clear ALL.
        recent_layout = QHBoxLayout()
        recent_layout.setSpacing(15)
        recent_radio = QRadioButton("Delete locally stored patients older than")
        recent_radio.setStyleSheet(radio_style)
        radio_group.addButton(recent_radio, 1)
        recent_spin = QSpinBox()
        recent_spin.setRange(1, 365)
        recent_spin.setValue(30)
        recent_spin.setSuffix(" days")
        recent_spin.setStyleSheet(spinbox_style)
        recent_spin.setEnabled(True)
        recent_radio.setChecked(True)
        recent_radio.toggled.connect(recent_spin.setEnabled)
        recent_layout.addWidget(recent_radio)
        recent_layout.addWidget(recent_spin)
        recent_layout.addStretch()
        strategy_layout.addLayout(recent_layout)
        
        # Option 3: Delete oldest count
        count_layout = QHBoxLayout()
        count_layout.setSpacing(15)
        count_radio = QRadioButton("Delete oldest")
        count_radio.setStyleSheet(radio_style)
        radio_group.addButton(count_radio, 2)
        count_spin = QSpinBox()
        count_spin.setRange(1, 10000)
        count_spin.setValue(50)
        count_spin.setSuffix(" patients")
        count_spin.setStyleSheet(spinbox_style)
        count_spin.setEnabled(False)
        count_radio.toggled.connect(count_spin.setEnabled)
        count_layout.addWidget(count_radio)
        count_layout.addWidget(count_spin)
        count_layout.addStretch()
        strategy_layout.addLayout(count_layout)
        
        strategy_group.setLayout(strategy_layout)
        layout.addWidget(strategy_group)
        
        layout.addSpacing(15)
        
        # Buttons - LARGE and clearly separated
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(15)
        
        preview_btn = QPushButton("👁️  Preview Count")
        preview_btn.setMinimumHeight(36)
        preview_btn.setMinimumWidth(160)
        preview_btn.setCursor(Qt.PointingHandCursor)
        preview_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 600; padding: 8px 14px; "
            "background-color: #3b82f6; border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #2563eb; }"
        )
        preview_btn.clicked.connect(
            lambda: self._preview_patient_cleanup(
                radio_group.checkedId(), recent_spin.value(), count_spin.value(), dialog
            )
        )
        
        execute_btn = QPushButton("⚠️  Execute Cleanup")
        execute_btn.setMinimumHeight(36)
        execute_btn.setMinimumWidth(180)
        execute_btn.setCursor(Qt.PointingHandCursor)
        execute_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 700; padding: 8px 14px; "
            "background-color: #1d4ed8; border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #1e40af; }"
        )
        execute_btn.clicked.connect(
            lambda: self._execute_patient_cleanup(
                radio_group.checkedId(), recent_spin.value(), count_spin.value(), dialog
            )
        )
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setMinimumHeight(36)
        cancel_btn.setMinimumWidth(120)
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.setStyleSheet(
            "QPushButton { font-size: 14px; font-weight: 600; padding: 8px 14px; "
            "background-color: #4b5563; border: none; border-radius: 6px; } "
            "QPushButton:hover { background-color: #6b7280; }"
        )
        cancel_btn.clicked.connect(dialog.reject)
        
        btn_layout.addWidget(preview_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(execute_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        
        dialog.exec()
    
    @staticmethod
    def _patient_cleanup_request(strategy_id: int, recent_days: int, count: int):
        if strategy_id == 0:
            return "all", 0
        if strategy_id == 1:
            return "older_than_days", int(recent_days)
        if strategy_id == 2:
            return "delete_oldest_count", int(count)
        raise ValueError(f"Unknown strategy ID: {strategy_id}")

    def _preview_patient_cleanup(
        self, strategy_id: int, recent_days: int, count: int, parent: QWidget
    ):
        """Build the preview off the GUI thread and show one consistent snapshot."""
        try:
            strategy, value = self._patient_cleanup_request(
                strategy_id, recent_days, count
            )
        except Exception as e:
            QMessageBox.warning(parent, "Preview Failed", f"Could not preview cleanup:\n{e}")
            return
        self._run_cleanup_job(
            parent,
            partial(self.cleanup_manager.build_patient_cleanup_preview, strategy, value),
            on_done=self._on_patient_preview_ready,
            on_fail=self._on_patient_preview_failed,
            progress_text="Calculating patients and reclaimable space…",
            progress_title="Cleanup Preview",
        )

    def _patient_preview_text(self, preview: dict) -> str:
        selected = int(preview.get("selected_patients", 0))
        total = int(preview.get("total_patients", 0))
        size = self.cleanup_manager.format_size(int(preview.get("estimated_bytes", 0)))
        unknown = int(preview.get("unknown_date_patients", 0))
        invalid = int(preview.get("invalid_paths", 0))
        lines = [
            f"Patients selected: {selected} of {total}",
            f"Estimated image data to reclaim: {size}",
        ]
        if unknown:
            lines.append(f"Patients kept because their local age is unknown: {unknown}")
        if invalid:
            lines.append(f"Unsafe or invalid study paths that will be skipped: {invalid}")
        return "\n".join(lines)

    def _on_patient_preview_ready(self, parent, preview: dict) -> None:
        self._close_cleanup_progress()
        QMessageBox.information(
            parent, "Preview Patient Cleanup", self._patient_preview_text(preview)
        )

    def _on_patient_preview_failed(self, parent, message: str) -> None:
        self._close_cleanup_progress()
        QMessageBox.warning(parent, "Preview Failed", f"Could not preview cleanup:\n{message}")
    
    def _execute_patient_cleanup(
        self, strategy_id: int, recent_days: int, count: int, parent: QDialog
    ):
        """Refresh the snapshot, then require confirmation of its exact scope."""
        try:
            strategy, value = self._patient_cleanup_request(
                strategy_id, recent_days, count
            )
        except Exception as e:
            QMessageBox.critical(parent, "Cleanup Failed", f"Could not start cleanup:\n{e}")
            return
        self._run_cleanup_job(
            parent,
            partial(self.cleanup_manager.build_patient_cleanup_preview, strategy, value),
            on_done=lambda dialog, preview: self._confirm_patient_cleanup(
                dialog, strategy, value, preview
            ),
            on_fail=self._on_patient_preview_failed,
            progress_text="Refreshing cleanup scope and reclaimable space…",
            progress_title="Cleanup Preview",
        )

    def _confirm_patient_cleanup(
        self, parent: QDialog, strategy: str, value: int, preview: dict
    ) -> None:
        self._close_cleanup_progress()
        selected = int(preview.get("selected_patients", 0))
        if selected <= 0:
            QMessageBox.information(parent, "Nothing to Clean", self._patient_preview_text(preview))
            return
        confirm = QMessageBox.question(
            parent,
            "Confirm Patient Cleanup",
            self._patient_preview_text(preview)
            + "\n\nThis permanently removes the selected local image data and database entries. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        if not self._can_start_destructive_cleanup(parent):
            return
        job = (
            self.cleanup_manager.cleanup_patients_folder
            if strategy == "all"
            else partial(
                self.cleanup_manager.cleanup_patients_folder_filtered,
                strategy=strategy,
                value=value,
            )
        )

        # 2026-08-22: this used to run on the GUI thread — a measured 183-second
        # freeze. It now runs on a worker behind a modal busy dialog, so the app
        # stays responsive and the user can see that something is happening.
        # AIPACS_STORAGE_CLEANUP_OFFTHREAD=0 restores the blocking call.
        self._run_cleanup_job(parent, job)

    @staticmethod
    def _cleanup_offthread_enabled() -> bool:
        import os as _os
        return (_os.getenv("AIPACS_STORAGE_CLEANUP_OFFTHREAD", "1") or "1").strip() != "0"

    def _run_cleanup_job(
        self,
        parent,
        job,
        on_done=None,
        on_fail=None,
        *,
        progress_text: str = "Cleaning up storage…",
        progress_title: str = "Cleanup",
    ) -> None:
        """Run *job* (a no-arg callable returning a CleanupResult) off the GUI
        thread, then report exactly as the synchronous version did.

        ``on_done(parent, result)`` / ``on_fail(parent, message)`` default to the
        patient-dialog reporters; the per-category rows pass their own so their
        message text (warnings block, no dialog accept) is unchanged.
        """
        on_done = on_done or self._on_cleanup_finished
        on_fail = on_fail or self._on_cleanup_failed
        if not self._cleanup_offthread_enabled():
            try:
                on_done(parent, job())
            except Exception as e:
                on_fail(parent, str(e))
            return
        if self._cleanup_thread is not None:
            QMessageBox.information(parent, "Cleanup In Progress",
                                    "A cleanup is already running. Please wait for it to finish.")
            return

        from PySide6.QtWidgets import QProgressDialog
        progress = QProgressDialog(progress_text, "", 0, 0, parent)
        progress.setWindowTitle(progress_title)
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)      # rmtree cannot be safely interrupted
        progress.setWindowFlag(Qt.WindowCloseButtonHint, False)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.show()
        self._cleanup_progress = progress

        # Never parent a long-running thread to this transient settings panel.
        # `_ACTIVE_STORAGE_JOBS` owns both wrappers until the thread has stopped.
        thread = QThread()
        worker = _CleanupWorker(job)
        _retain_storage_job(thread, worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # Bound QObject slots provide the receiver affinity that bare Python
        # lambdas do not. The old lambda connection executed in the worker and
        # could construct QMessageBox / refresh widgets from the wrong thread.
        worker.finished.connect(self._capture_cleanup_finished)
        worker.failed.connect(self._capture_cleanup_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_cleanup_thread_finished)
        self._cleanup_callback_parent = parent
        self._cleanup_done_callback = on_done
        self._cleanup_fail_callback = on_fail
        self._cleanup_thread = thread
        self._cleanup_worker = worker
        thread.start()

    @Slot(object)
    def _capture_cleanup_finished(self, result) -> None:
        self._cleanup_pending_result = result
        self._cleanup_pending_error = None

    @Slot(str)
    def _capture_cleanup_failed(self, message: str) -> None:
        self._cleanup_pending_result = None
        self._cleanup_pending_error = str(message)

    def _close_cleanup_progress(self) -> None:
        progress, self._cleanup_progress = self._cleanup_progress, None
        if progress is None:
            return
        try:
            progress.close()
            progress.deleteLater()
        except Exception:
            pass

    def _on_cleanup_thread_finished(self) -> None:
        thread, self._cleanup_thread = self._cleanup_thread, None
        worker, self._cleanup_worker = self._cleanup_worker, None
        parent = self._cleanup_callback_parent
        done_callback = self._cleanup_done_callback
        fail_callback = self._cleanup_fail_callback
        result = self._cleanup_pending_result
        error = self._cleanup_pending_error
        self._cleanup_callback_parent = None
        self._cleanup_done_callback = None
        self._cleanup_fail_callback = None
        self._cleanup_pending_result = None
        self._cleanup_pending_error = None
        if error is not None:
            if fail_callback is not None:
                fail_callback(parent, error)
        elif done_callback is not None:
            done_callback(parent, result)

    def _on_cleanup_finished(self, parent, result) -> None:
        self._close_cleanup_progress()
        try:
            warning_text = ""
            if getattr(result, "warnings", None):
                warning_text = "\n\nWarnings:\n- " + "\n- ".join(result.warnings)
            show_result = (
                QMessageBox.information
                if bool(getattr(result, "success", False))
                else QMessageBox.warning
            )
            show_result(
                parent,
                "Cleanup Completed" if result.success else "Cleanup Incomplete",
                (
                    f"{result.message}\n\n"
                    f"Folders touched: {result.folders_touched}\n"
                    f"Files deleted: {result.files_deleted}\n"
                    f"DB rows affected: {result.db_rows_affected}"
                    f"{warning_text}"
                ),
            )
            if result.success:
                parent.accept()
            self.refresh_storage_insights(force_refresh=True, defer_folder_sizes=True)
            if result.files_deleted or result.db_rows_affected:
                self.storageChanged.emit()
        except RuntimeError:
            return  # the dialog was closed while the cleanup ran — benign
        except Exception:
            _logger.exception("[STORAGE_PANEL] post-cleanup refresh failed")

    def _on_cleanup_failed(self, parent, message: str) -> None:
        self._close_cleanup_progress()
        try:
            QMessageBox.critical(parent, "Cleanup Failed",
                                 f"Could not complete cleanup:\n{message}")
        except RuntimeError:
            pass

    def refresh_storage_insights(self, force_refresh: bool = False, defer_folder_sizes: bool = False):
        if self.drive_usage_container is None:
            return

        if force_refresh:
            self._rebuild_cleanup_rows()

        if defer_folder_sizes:
            # Drive probing can block on disconnected removable/network drives,
            # so it travels with the folder walk on the same background worker.
            if not getattr(self, "_last_drive_rows", None):
                self._clear_drive_usage_widgets()
                self.drive_usage_container.addWidget(
                    QLabel("Calculating drive and managed-folder usage in the background…")
                )
            if self.storage_summary_label is not None:
                self.storage_summary_label.setText(
                    "Calculating managed folder sizes in the background…"
                )
            for label in self.folder_size_labels.values():
                label.setText("…")
            for label in self.folder_comp_labels.values():
                label.setText("…")
            self._kickoff_folder_sizes_refresh(force_refresh=force_refresh)
            return

        drive_rows = self.cleanup_manager.get_drive_usage_info()
        self._apply_drive_rows(drive_rows)
        folder_sizes = self.cleanup_manager.get_folder_usage_breakdown(force_refresh=force_refresh)
        self._apply_folder_sizes(folder_sizes)

    def _clear_drive_usage_widgets(self) -> None:
        while self.drive_usage_container.count():
            item = self.drive_usage_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _apply_drive_rows(self, drive_rows) -> None:
        self._clear_drive_usage_widgets()
        for row in drive_rows:
            used_pct = float(row.get("used_percent", 0.0))
            free_pct = 100.0 - used_pct
            
            # Low free space is a danger state, not an informational blue state.
            if free_pct < 20.0:
                bar_color = "#ef4444"  # red
            elif free_pct < 40.0:
                bar_color = "#f59e0b"  # amber/yellow
            else:
                bar_color = "#10b981"  # green
            
            drive_row = QVBoxLayout()
            drive_row.setSpacing(4)
            
            drive_label = QLabel(
                f"<b>{row.get('drive')}</b>  —  "
                f"Used: <b>{self.cleanup_manager.format_size(int(row.get('used', 0)))}</b> / "
                f"{self.cleanup_manager.format_size(int(row.get('total', 0)))}  "
                f"({used_pct:.1f}%)  —  "
                f"Free: <b>{self.cleanup_manager.format_size(int(row.get('free', 0)))}</b>"
            )
            drive_label.setStyleSheet(f"color: {bar_color}; font-size: 14px; font-weight: 600;")
            drive_row.addWidget(drive_label)
            
            progress_bar = QProgressBar()
            progress_bar.setRange(0, 100)
            progress_bar.setValue(int(used_pct))
            progress_bar.setTextVisible(False)
            progress_bar.setMinimumHeight(20)  # Archetype 5: floor, can grow with font
            progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    border: 2px solid #4b5563;
                    border-radius: 5px;
                    background-color: #1f2937;
                }}
                QProgressBar::chunk {{
                    background-color: {bar_color};
                    border-radius: 3px;
                }}
            """)
            drive_row.addWidget(progress_bar)
            
            drive_widget = QWidget()
            drive_widget.setLayout(drive_row)
            self.drive_usage_container.addWidget(drive_widget)

        # Stash drive_rows so the async folder-size completion can recompute the
        # used-disk anchor without re-querying disk usage.
        self._last_drive_rows = list(drive_rows)

    def _kickoff_folder_sizes_refresh(self, force_refresh: bool) -> None:
        """Run `get_folder_usage_breakdown` on a QThread; apply via signal.

        Coalesces concurrent requests: if a worker is already running, the
        latest force_refresh request is honored when the running worker
        finishes (handled in `_on_folder_sizes_ready`).
        """
        if self._folder_size_thread is not None:
            # A refresh is already in flight; remember that we want a follow-up
            # refresh once it lands so user-triggered refresh is never dropped.
            self._folder_size_pending = self._folder_size_pending or bool(force_refresh)
            return

        thread = QThread()
        worker = _FolderUsageWorker(self.cleanup_manager, force_refresh)
        _retain_storage_job(thread, worker)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_folder_sizes_ready)
        worker.failed.connect(self._on_folder_sizes_failed)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(self._on_folder_size_thread_finished)
        self._folder_size_thread = thread
        self._folder_size_worker = worker
        thread.start()

    @Slot(dict)
    def _on_folder_sizes_ready(self, payload: dict) -> None:
        try:
            if "folder_sizes" in payload:
                self._apply_drive_rows(payload.get("drive_rows", []))
                self._apply_folder_sizes(payload.get("folder_sizes", {}))
            else:  # compatibility with an older injected worker/test double
                self._apply_folder_sizes(payload)
        except Exception:
            _logger.exception("[STORAGE_PANEL] failed to apply folder sizes")

    @Slot(str)
    def _on_folder_sizes_failed(self, error_text: str) -> None:
        if self.storage_summary_label is not None:
            self.storage_summary_label.setText(
                f"Could not calculate folder sizes: {error_text}"
            )

    @Slot()
    def _on_folder_size_thread_finished(self) -> None:
        self._folder_size_thread = None
        self._folder_size_worker = None
        if self._folder_size_pending:
            self._folder_size_pending = False
            self._kickoff_folder_sizes_refresh(force_refresh=True)

    def _apply_folder_sizes(self, folder_sizes: dict) -> None:
        if self.drive_usage_container is None:
            return
        drive_rows = list(getattr(self, "_last_drive_rows", []) or [])
        folder_map = self.cleanup_manager.get_folder_map()

        total_managed = 0
        for key, value in (folder_sizes or {}).items():
            size_bytes = int(value or 0)
            total_managed += size_bytes
            if key in self.folder_size_labels:
                self.folder_size_labels[key].setText(self.cleanup_manager.format_size(size_bytes))
            if key in self.folder_comp_labels:
                roots = folder_map.get(key, []) or []
                anchors = {
                    str(Path(root).anchor or BASE_PATH.anchor).upper() for root in roots
                }
                if len(anchors) > 1:
                    self.folder_comp_labels[key].setText("stored across multiple drives")
                    continue
                category_anchor = next(iter(anchors), str(BASE_PATH.anchor).upper())
                category_drive_used = next(
                    (
                        int(row.get("used", 0))
                        for row in drive_rows
                        if str(row.get("drive", "")).upper().startswith(category_anchor)
                    ),
                    0,
                )
                ratio = (
                    size_bytes / category_drive_used * 100.0
                    if category_drive_used > 0
                    else 0.0
                )
                self.folder_comp_labels[key].setText(f"{ratio:.2f}% of used disk")

        if self.storage_summary_label is not None:
            self.storage_summary_label.setText(
                f"Managed folders total: {self.cleanup_manager.format_size(total_managed)}. "
                "Click Refresh to recalculate after cleanup."
            )
