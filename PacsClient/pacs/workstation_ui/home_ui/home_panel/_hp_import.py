"""Import pipeline: folder import with preview, auto-import from startup"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from ..import_preview_dialog import DicomImportPreviewDialog, import_scanned_dicom_studies, scan_dicom_import_folder
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.pacs.patient_tab.utils.image_io import load_series_preview
from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.config import THUMBNAIL_PATH
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM
from pathlib import Path

from .widget import SourceOfPatientLoad

class _HPImportMixin:
    """Import pipeline: folder import with preview, auto-import from startup"""

    def _run_background_job_with_progress(self, title: str, label_text: str, task, *args, **kwargs):
        """Run *task* in a background thread with a modal progress dialog.

        Uses a ``QEventLoop`` + ``QTimer`` callback instead of the old
        ``processEvents + time.sleep`` poll loop.  The Qt event loop stays
        responsive because the inner event loop processes events normally
        while waiting for the future to complete.
        """
        from PySide6.QtCore import QEventLoop, QTimer

        progress = QProgressDialog(label_text, None, 0, 0, self)
        progress.setWindowTitle(title)
        progress.setWindowModality(Qt.WindowModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.setMinimumWidth(560)
        progress.setStyleSheet(
            """
            QProgressDialog {
                background: #0b1118;
                color: #eef5ff;
            }
            QProgressDialog QLabel {
                color: #eef5ff;
                font-size: 14px;
                font-weight: 600;
                min-width: 460px;
                padding: 10px 6px 4px 6px;
            }
            QProgressBar {
                min-height: 16px;
                border-radius: 8px;
                border: 1px solid #26405d;
                background: #101b28;
                text-align: center;
            }
            QProgressBar::chunk {
                border-radius: 7px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4d9dff, stop:1 #2d6ee8);
            }
            """
        )
        progress.show()

        future = self.thread_pool.submit(task, *args, **kwargs)
        loop = QEventLoop()
        # IMPORTANT (import-hang fix 2026-06-06): wait on the MAIN thread.
        # The previous pattern — future.add_done_callback(lambda: QTimer.
        # singleShot(0, loop.quit)) — is broken: the done-callback executes in
        # the POOL WORKER thread, and a QTimer created there never fires
        # (worker threads have no Qt event loop), so loop.quit() was never
        # delivered and the progress dialog spun forever ("import never
        # ends"); every further click nested another stuck QEventLoop.
        # A poll timer owned by the main thread is immune by construction.
        poll = QTimer(progress)
        poll.setInterval(50)
        poll.timeout.connect(lambda: None if not future.done() else loop.quit())
        poll.start()
        try:
            if not future.done():
                loop.exec()
        finally:
            poll.stop()

        progress.close()
        progress.deleteLater()
        return future.result()

    def _refresh_local_patient_list_after_import(self):
        self.source_of_patient_load = SourceOfPatientLoad.DB

        tabs = getattr(self.data_access_panel_widget, "tabs", None)
        if tabs is not None and tabs.currentIndex() != 0:
            tabs.setCurrentIndex(0)
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        if loop.is_running():
            loop.create_task(self.search_patients_from_local_async())

    def _prepare_imported_study_for_fast_open(self, study_info: dict) -> int:
        study_uid = str(study_info.get("study_uid") or "").strip()
        patient_id = str(study_info.get("patient_id") or "").strip()
        if not study_uid or not patient_id:
            return 0

        patient_pk = find_patient_pk(patient_id)
        study_pk = find_study_pk_with_study_uid(study_uid)
        study_path = SOURCE_PATH / study_uid
        thumbnail_root = THUMBNAIL_PATH / study_uid
        thumbnail_root.mkdir(parents=True, exist_ok=True)

        metadata_fixed = {
            "study_uid": study_uid,
            "patient_pk": patient_pk,
            "study_pk": study_pk,
        }

        generated_count = 0
        for series in study_info.get("series", []) or []:
            series_number = str(series.get("series_number") or "").strip()
            series_uid = str(series.get("series_uid") or "").strip()
            if not series_number or not series_uid:
                continue

            thumbnail_path = thumbnail_root / f"{series_number}.png"
            if thumbnail_path.exists():
                continue

            try:
                preview = load_series_preview(
                    study_path=str(study_path),
                    series_number=series_number,
                    patient_pk=patient_pk,
                    study_pk=study_pk,
                )
            except Exception as e:
                print(
                    f"[FAST_PREP] Skipping preview for series {series_number} "
                    f"(study={study_uid}) due to load error: {e}"
                )
                continue
            if not preview:
                continue

            vtk_image_data, metadata, _patient_info, _total_files = preview
            series_pk = find_series_pk(series_uid)
            if not series_pk:
                continue

            metadata.setdefault("series", {})
            metadata["series"]["series_pk"] = series_pk
            metadata["series"]["series_number"] = series_number

            try:
                save_image_as_png(
                    vtk_image_data=vtk_image_data,
                    metadata=metadata,
                    metadata_fixed=metadata_fixed,
                    file=str(study_path),
                )
                generated_count += 1
            except Exception as e:
                print(
                    f"[FAST_PREP] Skipping thumbnail for series {series_number} "
                    f"(study={study_uid}) due to save error: {e}"
                )
                continue

        clear_study_cache(study_uid)
        return generated_count

    def _prepare_imported_studies_for_fast_open(self, studies: list) -> int:
        """Prepare EVERY imported study for the fast viewer (thumbnails + series
        records), in the given order (primary first).

        Bug fix (2026-06-15): the import previously prepared ONLY the primary
        study, so any additional study in a multi-study folder opened with an
        empty "0 series" sidebar (its per-series thumbnails were never built and
        the sidebar is thumbnail-driven). Preparing each study here keeps every
        imported study viewable. Per-study failures are isolated so one bad study
        never blocks the rest.
        """
        total = 0
        for study in studies or []:
            try:
                total += int(self._prepare_imported_study_for_fast_open(study) or 0)
            except Exception as e:
                print(
                    f"[FAST_PREP] study preparation failed "
                    f"(study={(study or {}).get('study_uid')}): {e}"
                )
        return total

    def _studies_to_prepare_for_fast_open(self, imported_studies, primary_study, failed_studies):
        """Build the prepare list: every successfully-saved study, primary first."""
        ordered = []
        primary_uid = primary_study.get("study_uid") if primary_study else None
        if primary_study and primary_uid not in failed_studies:
            ordered.append(primary_study)
        for study in imported_studies or []:
            su = study.get("study_uid")
            if su in failed_studies or su == primary_uid:
                continue
            ordered.append(study)
        return ordered

    def _open_imported_primary_study(self, study_info: dict):
        study_uid = study_info.get("study_uid")
        if not study_uid:
            return

        target_path = str(SOURCE_PATH / study_uid)
        self.data_access_panel_widget.folder_path_label.setText(target_path)
        self.add_new_tab_widget(
            patient_id=study_info.get("patient_id") or None,
            patient_name=study_info.get("patient_name") or "Imported Study",
            folder_path=target_path,
            caller=CallerTypes.IMPORT,
            study_uid=study_uid,
            enable_progressive_mode=True,
            viewer_backend_override=BACKEND_PYDICOM,
        )

    def _import_folder_with_preview(self, folder_path: str):
        # Re-entrancy guard: a second Select Folder click while an import
        # flow is in progress must not nest another scan/import loop.
        if getattr(self, "_import_flow_active", False):
            QMessageBox.information(
                self,
                "Import In Progress",
                "An import is already running. Please wait for it to finish.",
            )
            return
        self._import_flow_active = True
        try:
            self._import_folder_with_preview_impl(folder_path)
        finally:
            self._import_flow_active = False

    def _import_folder_with_preview_impl(self, folder_path: str):
        try:
            scan_result = self._run_background_job_with_progress(
                "Scan DICOM Folder",
                "Reading DICOM headers from the selected folder...",
                scan_dicom_import_folder,
                folder_path,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Import Scan Failed",
                f"AI-PACS could not read the selected folder.\n\n{exc}",
            )
            return

        if not scan_result.get("dicom_file_count"):
            QMessageBox.information(
                self,
                "No DICOM Files Found",
                "No readable DICOM files were found in the selected folder.",
            )
            return

        preview_dialog = DicomImportPreviewDialog(scan_result, self)
        if preview_dialog.exec() != QDialog.Accepted:
            return

        selected_scan_result = preview_dialog.selected_scan_result()
        if not selected_scan_result.get("series_count"):
            QMessageBox.warning(
                self,
                "Nothing Selected",
                "Select at least one study and one series before importing into AI-PACS.",
            )
            return

        try:
            import_result = self._run_background_job_with_progress(
                "Import DICOM Folder",
                "Copying DICOM files into AI-PACS storage...",
                import_scanned_dicom_studies,
                selected_scan_result,
                SOURCE_PATH,
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Import Failed",
                f"AI-PACS could not copy the selected DICOM files.\n\n{exc}",
            )
            return

        imported_studies = import_result.get("studies", []) or []
        if not imported_studies:
            QMessageBox.warning(
                self,
                "Import Failed",
                "The selected folder was scanned, but no studies were imported into AI-PACS.",
            )
            return

        failed_studies = []
        for study in imported_studies:
            saved = self.save_complete_study_info(
                study_uid=study.get("study_uid", ""),
                patient_id=study.get("patient_id"),
                study_info=study,
            )
            if not saved:
                failed_studies.append(study.get("study_uid", "Unknown Study"))

        primary_study = import_result.get("primary_study")
        # Prepare EVERY successfully-saved study for the fast viewer (primary first),
        # not just the primary — otherwise the other studies in a multi-study folder
        # open with an empty "0 series" sidebar (their thumbnails were never built).
        studies_to_prepare = self._studies_to_prepare_for_fast_open(
            imported_studies, primary_study, failed_studies
        )
        if studies_to_prepare:
            try:
                self._run_background_job_with_progress(
                    "Prepare Fast Viewer",
                    "Creating thumbnails and preparing the fast viewer...",
                    self._prepare_imported_studies_for_fast_open,
                    studies_to_prepare,
                )
            except Exception as exc:
                warning_messages = [
                    "The studies were imported, but fast-viewer preparation failed:",
                    str(exc),
                ]
                QMessageBox.warning(
                    self,
                    "Fast Viewer Preparation Warning",
                    "\n".join(warning_messages),
                )

        self._refresh_local_patient_list_after_import()

        if primary_study and primary_study.get("study_uid") not in failed_studies:
            self._open_imported_primary_study(primary_study)

        warning_messages = []
        if import_result.get("errors"):
            preview_errors = import_result["errors"][:5]
            warning_messages.append("Some files could not be copied:")
            warning_messages.extend(preview_errors)
            if len(import_result["errors"]) > 5:
                warning_messages.append(
                    f"... and {len(import_result['errors']) - 5} more file issues."
                )

        if failed_studies:
            warning_messages.append("")
            warning_messages.append("Some studies could not be saved to the local database:")
            warning_messages.extend(failed_studies[:5])
            if len(failed_studies) > 5:
                warning_messages.append(f"... and {len(failed_studies) - 5} more studies.")

        if warning_messages:
            QMessageBox.warning(
                self,
                "Import Completed With Warnings",
                "\n".join(message for message in warning_messages if message is not None),
            )

    def auto_import_folder_from_startup(self, folder_path: str) -> bool:
        """Import a DICOM folder non-interactively and open the primary study.

        Used for portable CD media where viewer launch should auto-show images.
        """
        startup_folder = Path(str(folder_path or "")).expanduser()
        if not startup_folder.exists() or not startup_folder.is_dir():
            QMessageBox.warning(
                self,
                "Startup Import",
                f"Startup import folder does not exist:\n{startup_folder}",
            )
            return False

        try:
            scan_result = self._run_background_job_with_progress(
                "Startup DICOM Scan",
                "Scanning media for DICOM files...",
                scan_dicom_import_folder,
                str(startup_folder),
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Startup Import",
                f"Could not scan startup folder:\n{exc}",
            )
            return False

        if not scan_result.get("dicom_file_count"):
            QMessageBox.information(
                self,
                "Startup Import",
                "No readable DICOM files were found in the startup folder.",
            )
            return False

        try:
            import_result = self._run_background_job_with_progress(
                "Startup DICOM Import",
                "Importing DICOM files into local storage...",
                import_scanned_dicom_studies,
                scan_result,
                SOURCE_PATH,
            )
        except Exception as exc:
            QMessageBox.warning(
                self,
                "Startup Import",
                f"Could not import startup DICOM files:\n{exc}",
            )
            return False

        imported_studies = import_result.get("studies", []) or []
        if not imported_studies:
            QMessageBox.warning(
                self,
                "Startup Import",
                "DICOM files were detected but no studies were imported.",
            )
            return False

        failed_studies = []
        for study in imported_studies:
            saved = self.save_complete_study_info(
                study_uid=study.get("study_uid", ""),
                patient_id=study.get("patient_id"),
                study_info=study,
            )
            if not saved:
                failed_studies.append(study.get("study_uid", "Unknown Study"))

        primary_study = import_result.get("primary_study")
        # Prepare every saved study (primary first), not just the primary, so no
        # imported study opens with an empty "0 series" sidebar.
        studies_to_prepare = self._studies_to_prepare_for_fast_open(
            imported_studies, primary_study, failed_studies
        )
        if studies_to_prepare:
            try:
                self._run_background_job_with_progress(
                    "Startup Fast Viewer Prep",
                    "Preparing thumbnails for fast opening...",
                    self._prepare_imported_studies_for_fast_open,
                    studies_to_prepare,
                )
            except Exception as exc:
                print(f"[STARTUP_IMPORT] Fast viewer preparation warning: {exc}")

        self._refresh_local_patient_list_after_import()

        if primary_study and primary_study.get("study_uid") not in failed_studies:
            self._open_imported_primary_study(primary_study)

        if failed_studies:
            QMessageBox.warning(
                self,
                "Startup Import",
                "Some studies were imported but could not be saved to the local database:\n"
                + "\n".join(failed_studies[:5]),
            )

        return True
