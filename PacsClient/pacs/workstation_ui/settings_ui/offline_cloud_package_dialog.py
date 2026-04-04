import json
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from modules.offline_cloud_server.service import (
    MANIFEST_NAME,
    rebuild_offline_cloud_manifest,
    validate_offline_cloud_package,
    write_offline_cloud_manifest,
)


class OfflineCloudPackageDialog(QDialog):
    """Inspect and maintain the root manifest.json for an Offline Cloud package."""

    def __init__(self, parent=None, server_data: dict | None = None):
        super().__init__(parent)
        self._server = dict(server_data or {})
        self._setup_ui()
        self.refresh_view()
        self.setWindowTitle("Offline Cloud Package")
        self.setWindowIcon(QIcon("PacsClient/login/images/favicon.ico"))
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(980, 760)

    def _setup_ui(self):
        self.setObjectName("OfflineCloudPackageDialog")
        self.setStyleSheet(
            """
            QDialog#OfflineCloudPackageDialog {
                background: #0b0d10;
                color: #e5e7eb;
            }
            QLabel {
                color: #e5e7eb;
            }
            QLabel#title {
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#muted {
                color: #94a3b8;
                font-size: 12px;
            }
            QPlainTextEdit {
                background: #0f1319;
                color: #e5e7eb;
                border: 1px solid #1e2530;
                border-radius: 8px;
                padding: 8px;
                font-family: Consolas;
                font-size: 12px;
            }
            QPushButton {
                background: #1b2230;
                color: #e5e7eb;
                border: 1px solid #2b313b;
                border-radius: 8px;
                padding: 8px 14px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #252d3d;
                border-color: #3b82f6;
            }
            QPushButton#primary {
                background: #2563eb;
                border-color: #2563eb;
                color: white;
            }
            QPushButton#danger {
                background: #991b1b;
                border-color: #991b1b;
                color: white;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel("Offline Cloud Package Manifest")
        title.setObjectName("title")
        root.addWidget(title)

        subtitle = QLabel(
            "This root manifest.json is read first. It defines package identity, transfer health, "
            "load order, and the timeline used for manual hub sync between Offline Cloud and AI PACS."
        )
        subtitle.setObjectName("muted")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(12)
        self.summary_grid.setVerticalSpacing(6)
        self._summary_labels: dict[str, QLabel] = {}
        rows = [
            ("Package", "package_id"),
            ("Status", "package_status"),
            ("Origin", "origin_server"),
            ("Hub User", "hub_user"),
            ("Imported By", "last_imported_by"),
            ("Applied By", "last_applied_by"),
            ("Patients", "patient_count"),
            ("Studies", "study_count"),
            ("Folders", "folder_count"),
            ("Updated", "updated_at"),
        ]
        for row, (label_text, key) in enumerate(rows):
            label = QLabel(label_text + ":")
            label.setObjectName("muted")
            value = QLabel("-")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._summary_labels[key] = value
            self.summary_grid.addWidget(label, row, 0)
            self.summary_grid.addWidget(value, row, 1)
        root.addLayout(self.summary_grid)

        panels = QHBoxLayout()
        panels.setSpacing(12)

        self.load_info = QPlainTextEdit()
        self.load_info.setReadOnly(True)
        self.load_info.setPlaceholderText("Package load plan and validation appear here.")
        panels.addWidget(self.load_info, 1)

        self.timeline_info = QPlainTextEdit()
        self.timeline_info.setReadOnly(True)
        self.timeline_info.setPlaceholderText("Package timeline appears here.")
        panels.addWidget(self.timeline_info, 1)

        root.addLayout(panels, 1)

        json_label = QLabel("manifest.json")
        json_label.setObjectName("muted")
        root.addWidget(json_label)

        self.json_editor = QPlainTextEdit()
        self.json_editor.setPlaceholderText("{\n  \"format\": \"aipacs-offline-cloud\"\n}")
        root.addWidget(self.json_editor, 2)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)

        reload_btn = QPushButton("Reload")
        reload_btn.clicked.connect(self.refresh_view)
        validate_btn = QPushButton("Validate")
        validate_btn.clicked.connect(self._validate_only)
        rebuild_btn = QPushButton("Rebuild JSON")
        rebuild_btn.setObjectName("primary")
        rebuild_btn.clicked.connect(self._rebuild_json)
        save_btn = QPushButton("Save JSON")
        save_btn.setObjectName("primary")
        save_btn.clicked.connect(self._save_json)
        open_btn = QPushButton("Open Folder")
        open_btn.clicked.connect(self._open_folder)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)

        for btn in (reload_btn, validate_btn, rebuild_btn, save_btn, open_btn):
            buttons.addWidget(btn)
        buttons.addStretch()
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    def refresh_view(self):
        folder_path = str(self._server.get("folder_path") or "").strip()
        manifest = validate_offline_cloud_package(folder_path)
        self._populate_summary(manifest)
        self.load_info.setPlainText(self._build_load_text(manifest))
        self.timeline_info.setPlainText(self._build_timeline_text(manifest))
        self.json_editor.setPlainText(self._read_raw_manifest_text(folder_path, manifest))

    def _validate_only(self):
        self.refresh_view()
        manifest = validate_offline_cloud_package(str(self._server.get("folder_path") or "").strip())
        validation = manifest.get("validation") or {}
        if validation.get("is_complete"):
            QMessageBox.information(self, "Offline Cloud Package", "The package looks complete and ready.")
            return
        details = "\n".join(validation.get("missing_items") or []) or "\n".join(validation.get("warnings") or [])
        QMessageBox.warning(
            self,
            "Offline Cloud Package",
            "The package is not complete yet.\n\n" + (details or "Check the manifest details."),
        )

    def _rebuild_json(self):
        folder_path = str(self._server.get("folder_path") or "").strip()
        rebuild_offline_cloud_manifest(folder_path, actor=None, source_server=None, changed_studies=None, operation="rebuild_manifest")
        self.refresh_view()
        QMessageBox.information(
            self,
            "Offline Cloud Package",
            "manifest.json was rebuilt from the package database and folder structure.",
        )

    def _save_json(self):
        folder_path = str(self._server.get("folder_path") or "").strip()
        raw_text = self.json_editor.toPlainText().strip()
        if not raw_text:
            QMessageBox.warning(self, "Offline Cloud Package", "The JSON editor is empty.")
            return
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            QMessageBox.warning(self, "Offline Cloud Package", f"JSON is invalid:\n{exc}")
            return
        if not isinstance(payload, dict):
            QMessageBox.warning(self, "Offline Cloud Package", "The root JSON value must be an object.")
            return
        manifest = write_offline_cloud_manifest(folder_path, payload)
        self._populate_summary(manifest)
        self.load_info.setPlainText(self._build_load_text(manifest))
        self.timeline_info.setPlainText(self._build_timeline_text(manifest))
        self.json_editor.setPlainText(self._read_raw_manifest_text(folder_path, manifest))
        QMessageBox.information(self, "Offline Cloud Package", "manifest.json was saved.")

    def _open_folder(self):
        folder_path = str(self._server.get("folder_path") or "").strip()
        if not folder_path:
            return
        try:
            os.makedirs(folder_path, exist_ok=True)
            os.startfile(folder_path)
        except Exception as exc:
            QMessageBox.warning(self, "Offline Cloud Package", f"Could not open folder:\n{exc}")

    def _populate_summary(self, manifest: dict):
        values = {
            "package_id": str(manifest.get("package_id") or "-"),
            "package_status": self._format_status(manifest),
            "origin_server": self._format_server(manifest.get("origin_server")),
            "hub_user": self._format_actor(manifest.get("hub_user")),
            "last_imported_by": self._format_actor(manifest.get("last_imported_by")),
            "last_applied_by": self._format_actor(manifest.get("last_applied_by")),
            "patient_count": str(manifest.get("patient_count") or 0),
            "study_count": str(manifest.get("study_count") or 0),
            "folder_count": str(manifest.get("folder_count") or 0),
            "updated_at": str(manifest.get("updated_at") or manifest.get("validated_at") or "-"),
        }
        for key, value in values.items():
            self._summary_labels[key].setText(value)

    def _build_load_text(self, manifest: dict) -> str:
        validation = manifest.get("validation") or {}
        items = manifest.get("items_to_load") or {}
        folder_summary = manifest.get("folder_summary") or {}
        lines = [
            f"Load order: {', '.join(items.get('load_order') or [])}",
            f"Required files: {', '.join(items.get('required_files') or [])}",
            f"Required folders: {', '.join(items.get('required_folders') or [])}",
            f"Module tables: {', '.join(items.get('module_tables') or []) or '-'}",
            f"Study UIDs indexed: {len(items.get('study_uids') or [])}",
            "",
            f"Folder roots present: {folder_summary.get('package_roots', 0)}",
            f"DICOM study folders: {folder_summary.get('dicom_study_folders', 0)}",
            f"Attachment study folders: {folder_summary.get('attachment_study_folders', 0)}",
            f"Thumbnail study folders: {folder_summary.get('thumbnail_study_folders', 0)}",
            "",
            f"Validation status: {validation.get('status') or '-'}",
            f"Complete: {'Yes' if validation.get('is_complete') else 'No'}",
        ]
        missing_items = validation.get("missing_items") or []
        warnings = validation.get("warnings") or []
        if missing_items:
            lines.extend(["", "Missing items:"])
            lines.extend(f"- {item}" for item in missing_items[:20])
        if warnings:
            lines.extend(["", "Warnings:"])
            lines.extend(f"- {item}" for item in warnings[:20])
        return "\n".join(lines)

    def _build_timeline_text(self, manifest: dict) -> str:
        timeline = manifest.get("timeline") or manifest.get("sync_events") or []
        if not timeline:
            return "No timeline events yet."
        lines = []
        for event in reversed(list(timeline)[-20:]):
            if not isinstance(event, dict):
                continue
            actor = self._format_actor(event.get("actor"))
            study_count = len(event.get("study_uids") or [])
            details = event.get("details") or {}
            detail_text = ", ".join(f"{key}={value}" for key, value in details.items()) or "-"
            lines.append(
                f"{event.get('at') or '-'} | {event.get('event_type') or 'sync'} | "
                f"actor={actor} | studies={study_count} | details={detail_text}"
            )
        return "\n".join(lines) or "No timeline events yet."

    def _read_raw_manifest_text(self, folder_path: str, manifest: dict) -> str:
        manifest_path = os.path.join(folder_path, MANIFEST_NAME)
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as fh:
                    return fh.read()
            except OSError:
                pass
        return json.dumps(manifest, indent=2, ensure_ascii=False)

    @staticmethod
    def _format_actor(actor: dict | None) -> str:
        if not isinstance(actor, dict):
            return "-"
        name = str(actor.get("full_name") or actor.get("username") or actor.get("user_id") or "").strip()
        role = str(actor.get("role") or "").strip()
        if name and role:
            return f"{name} ({role})"
        return name or "-"

    @staticmethod
    def _format_server(server: dict | None) -> str:
        if not isinstance(server, dict):
            return "-"
        name = str(server.get("name") or "").strip()
        host = str(server.get("host") or "").strip()
        return " / ".join(part for part in (name, host) if part) or "-"

    @staticmethod
    def _format_status(manifest: dict) -> str:
        validation = manifest.get("validation") or {}
        status = str(manifest.get("package_status") or validation.get("status") or "-")
        transfer = str(manifest.get("transfer_status") or "-")
        return f"{status} ({transfer})"
