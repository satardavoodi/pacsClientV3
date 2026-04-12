"""Offline cloud operations: sync, export, import, server validation"""
# Auto-generated from home_ui.py — Phase 3 split



import traceback

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from ..offline_cloud_export_dialog import OfflineCloudExportDialog
from PacsClient.utils.db_manager import get_study_by_study_uid
from modules.network.socket_config import update_socket_server_settings, get_socket_server_settings
from modules.offline_cloud_server.service import export_studies_to_offline_cloud, get_all_offline_cloud_servers, list_offline_cloud_studies, record_offline_cloud_sync_event, sync_offline_cloud_study_preview_to_local, sync_offline_cloud_study_to_local, validate_offline_cloud_package

class _HPOfflineMixin:
    """Offline cloud operations: sync, export, import, server validation"""

    def _current_actor_identity(self) -> dict:
        auth_user = None
        try:
            host_window = getattr(self.mainwindow, "host_window", None)
            auth_user = getattr(host_window, "auth_user", None) if host_window is not None else None
        except Exception:
            auth_user = None
        return dict(auth_user or {})

    @staticmethod
    def _server_identity(server: dict | None) -> dict | None:
        if not isinstance(server, dict):
            return None
        return {
            "name": server.get("name"),
            "host": server.get("host") or server.get("folder_path"),
            "port": server.get("port"),
            "ae_title": server.get("ae_title"),
            "server_type": server.get("server_type"),
        }

    def _autosync_studies_to_offline_cloud(self, cloud_server, study_uids, *, show_errors: bool = False):
        """Best-effort sync of local study changes back into an Offline Cloud package."""
        try:
            if not cloud_server or cloud_server.get("server_type") != "offline_cloud":
                return
            study_uids = sorted({str(uid or "").strip() for uid in (study_uids or []) if str(uid or "").strip()})
            if not study_uids:
                return
            result = export_studies_to_offline_cloud(
                cloud_server,
                study_uids,
                actor=self._current_actor_identity(),
                source_server=None,
                operation="offline_update",
            )
            if show_errors and result.get("errors"):
                QMessageBox.warning(
                    self,
                    "Offline Cloud Sync",
                    "Some study changes could not be saved back to the Offline Cloud package:\n\n"
                    + "\n".join(result.get("errors", [])[:5]),
                )
        except Exception as exc:
            if show_errors:
                QMessageBox.warning(self, "Offline Cloud Sync", f"Could not save changes to Offline Cloud:\n{exc}")

    def _on_local_study_state_changed(self, study_uid: str):
        """Autosave local study-state changes when the active source is Offline Cloud."""
        server = self.data_access_panel_widget.get_server_selected()
        if not server or server.get("server_type") != "offline_cloud":
            return
        try:
            self._autosync_studies_to_offline_cloud(server, [study_uid], show_errors=False)
        except Exception:
            pass

    def _validate_offline_cloud_server_for_read(self, cloud_server: dict, *, action_label: str) -> dict | None:
        manifest = validate_offline_cloud_package(cloud_server.get("folder_path", ""))
        validation = manifest.get("validation") or {}

        if manifest.get("format") is None:
            QMessageBox.warning(
                self,
                "Offline Cloud Package",
                "The selected Offline Cloud folder does not have a valid root manifest.json yet.\n\n"
                "Open Settings -> Offline Cloud Server -> Package JSON... and rebuild or save the JSON file first.",
            )
            return None

        if not validation.get("database_present"):
            QMessageBox.warning(
                self,
                "Offline Cloud Package",
                "The selected Offline Cloud package is missing package.db, so it cannot be used for "
                f"{action_label}.",
            )
            return None

        if not validation.get("is_complete"):
            details = "\n".join((validation.get("missing_items") or [])[:8]) or "\n".join((validation.get("warnings") or [])[:8])
            QMessageBox.warning(
                self,
                "Offline Cloud Package",
                "The selected Offline Cloud package is incomplete and cannot be used safely for "
                f"{action_label}.\n\n{details}",
            )
            return None

        return manifest

    def _choose_offline_cloud_server(self, *, title: str = "Offline Sync", label: str = "Choose Offline Cloud Server:"):
        cloud_servers = get_all_offline_cloud_servers()
        if not cloud_servers:
            QMessageBox.warning(
                self,
                "No Offline Cloud Server",
                "Configure at least one Offline Cloud Server in Settings before syncing.",
            )
            return None

        if len(cloud_servers) == 1:
            return cloud_servers[0]

        from PySide6.QtWidgets import QInputDialog

        cloud_names = [str(server.get("name") or "") for server in cloud_servers]
        cloud_name, accepted = QInputDialog.getItem(
            self,
            title,
            label,
            cloud_names,
            0,
            False,
        )
        if not accepted or not cloud_name:
            return None
        return next((server for server in cloud_servers if server.get("name") == cloud_name), None)

    def _confirm_offline_cloud_export(self, selected_studies):
        cloud_servers = get_all_offline_cloud_servers()
        if not cloud_servers:
            QMessageBox.warning(
                self,
                "No Offline Cloud Server",
                "Configure at least one Offline Cloud Server in Settings before exporting.",
            )
            return None, []

        downloaded_studies = self.patient_table_widget.get_downloaded_selected_patient_data_list()
        selected_uids = self._normalize_study_uids(selected_studies)
        downloadable_uids = self._normalize_study_uids(downloaded_studies)
        skipped_count = max(0, len(selected_uids) - len(downloadable_uids))

        if not downloaded_studies:
            QMessageBox.warning(
                self,
                "No Downloaded Studies",
                "Offline Cloud export needs local study data first. Download or open the selected studies locally, then try again.",
            )
            return None, []

        dlg = OfflineCloudExportDialog(
            self,
            studies=downloaded_studies,
            cloud_servers=cloud_servers,
            skipped_count=skipped_count,
        )
        if dlg.exec() != OfflineCloudExportDialog.Accepted:
            return None, []
        return dlg.selected_server(), downloaded_studies

    def _export_selected_studies_to_offline_cloud(self, cloud_server, selected_studies):
        downloaded_lookup = {
            str(study.get("study_uid") or "").strip(): study
            for study in self.patient_table_widget.get_downloaded_selected_patient_data_list()
            if str(study.get("study_uid") or "").strip()
        }
        requested_uids = self._normalize_study_uids(selected_studies)
        downloaded_studies = [
            downloaded_lookup[study_uid]
            for study_uid in requested_uids
            if study_uid in downloaded_lookup
        ]
        study_uids = self._normalize_study_uids(downloaded_studies)
        if not study_uids:
            QMessageBox.warning(
                self,
                "No Downloaded Studies",
                "Offline Cloud export needs local study data first. Download or open the selected studies locally, then try again.",
            )
            return
        skipped_count = max(0, len(requested_uids) - len(study_uids))

        current_server = self.data_access_panel_widget.get_server_selected()
        source_server = None
        operation = "offline_update"
        if current_server and current_server.get("server_type") != "offline_cloud":
            source_server = self._server_identity(current_server)
            operation = "export_from_ai_pacs"

        export_result = self._run_background_job_with_progress(
            "Offline Cloud Export",
            f"Exporting {len(study_uids)} study{'ies' if len(study_uids) != 1 else ''} to {cloud_server.get('name', 'Offline Cloud Server')}...",
            export_studies_to_offline_cloud,
            cloud_server,
            study_uids,
            actor=self._current_actor_identity(),
            source_server=source_server,
            operation=operation,
        )

        if export_result.get("ok") and not export_result.get("errors"):
            message = (
                f"Exported {export_result.get('exported', 0)} studies.\n\n"
                f"Package studies available: {export_result.get('study_count', 0)}\n"
                f"Manifest: {export_result.get('manifest_path', '')}\n\n"
            )
            if skipped_count:
                message += f"Skipped not-yet-downloaded selections: {skipped_count}\n\n"
            message += "This folder can now be transferred manually or synced by an external tool."
            QMessageBox.information(
                self,
                "Offline Cloud Export",
                message,
            )
            return

        error_lines = "\n".join((export_result.get("errors") or [])[:5])
        QMessageBox.warning(
            self,
            "Offline Cloud Export",
            f"Exported {export_result.get('exported', 0)} studies with some issues.\n\n{error_lines}",
        )

    def _sync_local_study_to_ai_server(self, study_uid: str, ai_server: dict, actor: dict | None = None) -> dict:
        """Push locally stored workstation-side changes back to the active AI PACS server."""
        from modules.network.socket_config import get_socket_server_settings
        from modules.network.socket_report_status_service import VALID_STATUSES, get_report_status_service
        from modules.network.upload_download_attchments import upload_attachments_for_study
        from PacsClient.utils import get_attachments_uploaded, get_study_by_study_uid, set_visit_status

        socket_cfg = get_socket_server_settings()
        update_socket_server_settings(
            host=str(ai_server.get("host") or ""),
            port=int(socket_cfg.get("port") or socket_cfg.get("socket_port") or 50052),
        )

        study_row = get_study_by_study_uid(study_uid) or {}
        report_status = str(study_row.get("reportStatus") or "pending").strip() or "pending"
        if report_status not in VALID_STATUSES:
            report_status = "pending"

        attachment_state = str(get_attachments_uploaded(study_uid) or "")
        actor = dict(actor or {})
        actor_name = str(actor.get("full_name") or actor.get("username") or "").strip() or None
        actor_user_id = str(actor.get("user_id") or actor.get("id") or actor.get("username") or "").strip() or None
        upload_result = upload_attachments_for_study(
            study_uid=study_uid,
            attachments_uploaded=attachment_state,
            uploaded_by=actor_name,
            verbose=False,
        )

        report_service = get_report_status_service()
        status_response = report_service.update_report_status(
            study_uid=study_uid,
            new_status=report_status,
            user_id=actor_user_id,
            comment=f"Synced from Offline Cloud hub by {actor_name or 'offline user'}",
        )

        ok = status_response is not None and int(upload_result.get("failed", 0) or 0) == 0
        if ok:
            set_visit_status(study_uid, "synced")

        return {
            "ok": ok,
            "study_uid": study_uid,
            "uploaded": int(upload_result.get("success", 0) or 0),
            "failed_uploads": int(upload_result.get("failed", 0) or 0),
            "report_status": report_status,
            "status_synced": status_response is not None,
        }

    def _import_offline_cloud_studies_into_ai_server(self, cloud_server: dict, study_uids: list[str], ai_server: dict) -> dict:
        imported = 0
        synced = 0
        errors: list[str] = []
        synced_uids: list[str] = []
        actor = self._current_actor_identity()

        for study_uid in study_uids:
            try:
                import_result = sync_offline_cloud_study_to_local(
                    cloud_server,
                    study_uid,
                    actor=actor,
                )
                if not import_result.get("ok"):
                    errors.append(import_result.get("error") or f"{study_uid}: import failed")
                    continue
                imported += 1

                sync_result = self._sync_local_study_to_ai_server(study_uid, ai_server, actor=actor)
                if sync_result.get("ok"):
                    synced += 1
                    synced_uids.append(study_uid)
                else:
                    errors.append(
                        f"{study_uid}: workstation sync incomplete "
                        f"(uploads failed={sync_result.get('failed_uploads', 0)}, "
                        f"status synced={sync_result.get('status_synced', False)})"
                    )
            except Exception as exc:
                errors.append(f"{study_uid}: {exc}")

        try:
            record_offline_cloud_sync_event(
                cloud_server.get("folder_path", ""),
                event_type="import_to_ai_pacs",
                actor=actor,
                server=self._server_identity(ai_server),
                study_uids=study_uids,
                details={"imported": imported, "synced": synced, "errors": len(errors)},
            )
        except Exception:
            pass

        return {
            "ok": imported > 0,
            "imported": imported,
            "synced": synced,
            "synced_uids": synced_uids,
            "errors": errors,
        }

    def _on_offline_cloud_sync_requested(self, selected_studies):
        """Main hub action for Offline Cloud import/export."""
        try:
            current_server = self.data_access_panel_widget.get_server_selected()
            downloaded_studies = self.patient_table_widget.get_downloaded_selected_patient_data_list()

            if current_server and current_server.get("server_type") == "offline_cloud":
                self._export_selected_studies_to_offline_cloud(current_server, selected_studies)
                return

            if not current_server:
                cloud_server, export_studies = self._confirm_offline_cloud_export(selected_studies)
                if not cloud_server or not export_studies:
                    return
                self._export_selected_studies_to_offline_cloud(cloud_server, export_studies)
                return

            allow_export = bool(downloaded_studies)
            allow_import = current_server.get("server_type") == "ai_pacs"
            if not allow_export and not allow_import:
                QMessageBox.warning(
                    self,
                    "Offline Sync",
                    "Download the selected studies first before exporting them to an Offline Cloud Server folder.",
                )
                return

            mode = None
            if allow_export and not allow_import:
                mode = "Export to Offline Cloud"
            elif allow_import and not allow_export:
                mode = "Import from Offline Cloud to AI PACS"
            else:
                from PySide6.QtWidgets import QInputDialog

                mode, accepted = QInputDialog.getItem(
                    self,
                    "Offline Sync",
                    "Select manual hub action:",
                    [
                        "Export to Offline Cloud",
                        "Import from Offline Cloud to AI PACS",
                    ],
                    0,
                    False,
                )
                if not accepted or not mode:
                    return

            if mode == "Export to Offline Cloud":
                cloud_server, export_studies = self._confirm_offline_cloud_export(selected_studies)
                if not cloud_server or not export_studies:
                    return
                self._export_selected_studies_to_offline_cloud(cloud_server, export_studies)
                return

            cloud_server = self._choose_offline_cloud_server(
                title="Offline Sync",
                label="Choose which Offline Cloud Server folder should be read back into AI PACS:",
            )
            if not cloud_server:
                return

            study_uids = self._normalize_study_uids(selected_studies)
            if not study_uids:
                QMessageBox.warning(self, "Offline Sync", "Select at least one study to import from Offline Cloud.")
                return

            if not self._validate_offline_cloud_server_for_read(
                cloud_server,
                action_label="manual import back to AI PACS",
            ):
                return

            sync_result = self._run_background_job_with_progress(
                "Offline Cloud Import",
                f"Importing {len(study_uids)} study{'ies' if len(study_uids) != 1 else ''} from {cloud_server.get('name', 'Offline Cloud Server')} and syncing workstation data to {current_server.get('name', 'AI PACS')}...",
                self._import_offline_cloud_studies_into_ai_server,
                cloud_server,
                study_uids,
                current_server,
            )

            for study_uid in sync_result.get("synced_uids", []):
                try:
                    self.patient_table_widget.update_visited_status(study_uid, status='synced')
                except Exception:
                    pass

            if sync_result.get("ok") and not sync_result.get("errors"):
                QMessageBox.information(
                    self,
                    "Offline Cloud Import",
                    f"Imported {sync_result.get('imported', 0)} studies and synced {sync_result.get('synced', 0)} studies to {current_server.get('name', 'AI PACS')}.\n\n"
                    "This was a manual hub sync from the Offline Cloud folder back into the live server workflow.",
                )
                return

            QMessageBox.warning(
                self,
                "Offline Cloud Import",
                f"Imported {sync_result.get('imported', 0)} studies and synced {sync_result.get('synced', 0)} studies.\n\n"
                + "\n".join(sync_result.get("errors", [])[:6]),
            )

        except Exception as e:
            print(f"Offline Cloud sync error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Offline Cloud Sync", f"Failed to run Offline Cloud sync:\n{e}")

    def _on_offline_cloud_export_requested(self, selected_studies):
        """Backward-compatible path for explicit export-only calls."""
        try:
            server = self.data_access_panel_widget.get_server_selected()
            if not server or server.get("server_type") != "offline_cloud":
                QMessageBox.warning(
                    self,
                    "Offline Cloud Server Required",
                    "Select an Offline Cloud Server from the server dropdown before exporting.",
                )
                return
            self._export_selected_studies_to_offline_cloud(server, selected_studies)
        except Exception as e:
            print(f"Offline Cloud export error: {e}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Offline Cloud Export", f"Failed to export studies:\n{e}")
