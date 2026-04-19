"""Search & table population: local/server search, patient table delegates"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio
import logging

_logger = logging.getLogger(__name__)

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

import qtawesome as qta

from ..home_search_service import HomeSearchService
from PacsClient.components import DicomGrpcClient
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from modules.offline_cloud_server.service import export_studies_to_offline_cloud, get_all_offline_cloud_servers, list_offline_cloud_studies, record_offline_cloud_sync_event, sync_offline_cloud_study_preview_to_local, sync_offline_cloud_study_to_local, validate_offline_cloud_package

from .widget import SourceOfPatientLoad

class _HPSearchMixin:
    """Search & table population: local/server search, patient table delegates"""

    def perform_default_search(self):
        """Perform default search with today's date when page loads"""
        try:
            # Check Socket connection status first
            self.check_socket_connection_status()

            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if server:
                asyncio.create_task(self.search_patients_from_server_async())
        except Exception as e:
            print(f"Error in default search: {str(e)}")

    def _on_server_tab_changed(self, index):
        """Auto-trigger search when the user switches tabs in Server Selection."""
        tab_name = self.data_access_panel_widget.tabs.tabText(index).lower()
        if tab_name == 'local':
            self.patient_list_function_identifier('local')

    def patient_list_function_identifier(self, tab_selected: str):
        tab_selected = tab_selected.lower()

        # قبل از شروع هر سرچ، اگر تسک قبلی فعاله کنسلش کن
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        # Set searching state and update UI
        self.patient_search_widget.set_searching_state(True)
        self._cancel_search_requested = False

        if tab_selected == 'local':
            self.source_of_patient_load = SourceOfPatientLoad.DB
            # قبلاً sync بود؛ حالا async و قابل لغو:
            self._search_task = asyncio.create_task(self.search_patients_from_local_async())

        elif tab_selected == 'server':
            self.source_of_patient_load = SourceOfPatientLoad.SERVER
            self._search_task = asyncio.create_task(self.search_patients_from_server_async())

        elif tab_selected == 'import':
            self.source_of_patient_load = SourceOfPatientLoad.IMPORT
            pass

    def cancel_search(self):
        """Cancel the current search operation"""
        print(f"\n[CANCEL_SEARCH] 🛑 Cancel search requested by user")
        self._cancel_search_requested = True
        
        # Cancel the current search task if it exists
        if self._search_task and not self._search_task.done():
            self._search_task.cancel()
            print(f"[CANCEL_SEARCH] ✅ Search task cancelled")
        
        # Reset UI state
        self.patient_search_widget.set_searching_state(False)
        
        # Hide loading indicators
        self.hide_loading()
        self.search_progress.setVisible(False)
        
        # Reset connection indicator
        self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#6b7280').pixmap(12, 12))
        self.connection_indicator.setText(" Search Cancelled")
        self.connection_indicator.setStyleSheet("""
            QLabel { font-size: 14px; color: #6b7280; padding: 4px 8px;
                     background: rgba(107,114,128,.1); border:1px solid rgba(107,114,128,.3); border-radius:8px; }
        """)
        
        print(f"[CANCEL_SEARCH] ✅ UI state reset")

    async def search_patients_from_local_async(self):
        """Search local database — delegated to search service."""
        await self.search_service.search_local()

    async def search_patients_from_server_async(self):
        """Search remote PACS via Socket — delegated to search service."""
        await self.search_service.search_server()

    def _convert_search_data_to_socket_params(self, search_data):
        """Convert UI search data to Socket API parameters (delegates to service)."""
        return HomeSearchService._convert_search_data_to_socket_params(search_data)

    def _add_socket_patient_to_table(self, patient):
        """
        Add Socket patient data to the patient table

        Args:
            patient (dict): Patient data from Socket API
        """
        try:
            # Extract patient information
            patient_id = patient.get('patient_id', 'N/A')
            patient_name = patient.get('patient_name', 'N/A')
            study_uid = patient.get('latest_study_uid', 'N/A')
            study_date = patient.get('latest_study_date', 'N/A')
            if study_date != 'N/A' and len(study_date) == 8:  # Format: YYYYMMDD
                try:
                    # Convert YYYYMMDD to YYYY/MM/DD
                    study_date = f"{study_date[:4]}/{study_date[4:6]}/{study_date[6:8]}"
                except:
                    pass
            study_description = patient.get('latest_study_description', 'N/A')
            modality = ', '.join(patient.get('modalities', []))
            
            # Extract study time
            study_time = patient.get('latest_study_time', 'N/A')
            
            # Extract body part - سرور body_parts را به صورت array ارسال می‌کند
            body_parts = patient.get('body_parts', [])
            if isinstance(body_parts, list) and len(body_parts) > 0:
                # اگر array است، با کاما join کن
                body_part = ', '.join(str(bp) for bp in body_parts if bp)
            else:
                # اگر array نیست یا خالی است، از فیلد قدیمی استفاده کن
                body_part = patient.get('body_part_examined', 'N/A')
                if not body_part or body_part == 'N/A':
                    body_part = 'N/A'
            
            # Extract patient age
            age = patient.get('patient_age', 'N/A')

            # Create description from available data
            description_parts = []
            if study_description and study_description != 'N/A':
                description_parts.append(study_description)

            total_studies = patient.get('total_studies', 0)
            if total_studies > 0:
                description_parts.append(f"Studies: {total_studies}")

            total_series = patient.get('count_of_series', 0)
            if total_series > 0:
                description_parts.append(f"Series: {total_series}")

            total_instances = patient.get('count_of_instances', 0)
            if total_instances > 0:
                description_parts.append(f"Images: {total_instances}")

            description = ' | '.join(description_parts) if description_parts else 'No description available'

            # Extract report status if available (check multiple possible field names)
            report_status = (
                patient.get('latest_study_report_status') or 
                patient.get('reportStatus') or 
                patient.get('report_status') or 
                'pending'
            )
            # Validate status
            valid_statuses = ['pending', 'awaiting_physician_approval', 
                            'awaiting_secretary_approval', 'awaiting_approval',
                            'physician_approved', 'secretary_approved', 
                            'completed', 'archived']
            if not report_status or report_status not in valid_statuses:
                report_status = 'pending'
            
            # Add to table with all fields including body_part, study_time, age, and report_status
            self.add_data2patient_list_table(
                patient_id=patient_id,
                patient_name=patient_name,
                study_date=study_date,
                study_time=study_time,
                body_part=body_part,
                age=age,
                description=description,
                modality=modality,
                study_uid=study_uid,
                series_count=total_series,
                images_count=total_instances,
                report_status=report_status
            )

        except Exception as e:
            print(f"Error adding Socket patient to table: {e}")

    def _save_socket_patient_to_db(self, patient):
        """Save Socket patient data to local database (delegates to service)."""
        self.db_service.save_socket_patient_to_db(patient)

    def save_patient_and_study_on_db(self, dataset):
        """Persist patient + study from a pydicom Dataset (delegates to service)."""
        self.db_service.save_patient_and_study_on_db(dataset)

    def add_data2patient_list_table(self, **kwargs):
        '''
            add data to patient list (patient_table_widget) for show
        '''
        # Check download status from database
        study_uid = kwargs.get('study_uid')
        if study_uid:
            try:
                from PacsClient.pacs.patient_tab.utils.utils import get_study_download_status

                try:
                    # Check if is_downloaded is already set
                    is_downloaded = kwargs.get('is_downloaded')
                    if is_downloaded is not None:
                        # Convert bool to status string for backwards compatibility
                        kwargs['download_status'] = 'complete' if is_downloaded else 'not_downloaded'
                    else:
                        # Get expected series count from kwargs (from server response)
                        expected_series = kwargs.get('series_count') or kwargs.get('count_of_series') or 0
                        # Get detailed download status
                        download_status = get_study_download_status(study_uid, expected_series if expected_series > 0 else None)
                        kwargs['download_status'] = download_status
                        kwargs['is_downloaded'] = (download_status == 'complete')
                except Exception as ex:
                    print(f"[WARN] Error in download status check: {ex}")
                    kwargs['download_status'] = 'not_downloaded'
                    kwargs['is_downloaded'] = False
            except Exception as e:
                print(f"Error checking download status: {e}")
                kwargs['download_status'] = 'not_downloaded'
                kwargs['is_downloaded'] = False

        # Set default values for other status fields
        kwargs.setdefault('has_voice', False)
        kwargs.setdefault('is_reported', False)

        self.patient_table_widget.add_patient_data(**kwargs)

    def center_align_table_column(self, table_widget, column_index):
        """
        تنظیم وسط‌چین برای تمام سلول‌های یک ستون خاص

        Args:
            table_widget: جدول مورد نظر (QTableWidget)
            column_index: ایندکس ستون (از 0 شروع می‌شود)
        """
        if not table_widget or column_index < 0:
            return

        row_count = table_widget.rowCount()

        for row in range(row_count):
            item = table_widget.item(row, column_index)
            if item:
                item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)

            # اگر ویجت داخل سلول است (مثل چک‌باکس)
            widget = table_widget.cellWidget(row, column_index)
            if widget:
                from PySide6.QtWidgets import QHBoxLayout, QWidget, QCheckBox
                from PacsClient.utils.custom_checkbox import CustomCheckbox

                # اگر QCheckBox یا CustomCheckbox است
                if isinstance(widget, (QCheckBox, CustomCheckbox)):
                    # استفاده از استایل برای وسط‌چین کردن indicator چک‌باکس
                    widget.setStyleSheet("""
                        QCheckBox {
                            spacing: 0px;
                            margin: 0px;
                            padding: 0px;
                        }
                        QCheckBox::indicator {
                            subcontrol-position: center center;
                            subcontrol-origin: padding;
                            margin: 0px;
                            padding: 0px;
                        }
                    """)
                    # تنظیم alignment خود ویجت
                    widget.setAlignment(Qt.AlignCenter)
                else:
                    # برای سایر ویجت‌ها، استفاده از layout
                    parent = widget.parentWidget()
                    if not isinstance(parent, QWidget) or parent.layout() is None:
                        container = QWidget()
                        layout = QHBoxLayout(container)
                        layout.addWidget(widget)
                        layout.setAlignment(Qt.AlignCenter)
                        layout.setContentsMargins(0, 0, 0, 0)
                        table_widget.setCellWidget(row, column_index, container)

    def _update_results_count(self):
        """Update the results count label"""
        # This method is now handled by PatientTableWidget
        pass

    def cancel_current_search(self):
        """علامت لغو را ست می‌کند، تسک فعال را کنسل و UI را جمع می‌کند."""
        self._cancel_search_requested = True
        try:
            if self._search_task and not self._search_task.done():
                self._search_task.cancel()
        except Exception:
            pass

        # بروزرسانی وضعیت
        try:
            self.search_progress.setVisible(False)
            self.connection_indicator.setPixmap(qta.icon('fa5s.circle', color='#f59e0b').pixmap(12, 12))
            self.connection_indicator.setText(" Socket Search Cancelled")
            self.connection_indicator.setStyleSheet("""
                QLabel { font-size: 14px; color: #f59e0b; padding: 4px 8px;
                         background: rgba(245,158,11,.1); border:1px solid rgba(245,158,11,.3); border-radius:8px; }
            """)
        except Exception:
            pass

        # بستن دیالوگ لودینگ
        self.hide_loading()

    def _on_cancel_search_clicked(self):
        # جلوگیری از چندبار کلیک
        if hasattr(self, 'loading_cancel_btn') and self.loading_cancel_btn:
            self.loading_cancel_btn.setDisabled(True)
            self.loading_cancel_btn.setText("Cancelling...")
        self.cancel_current_search()

    def _animate_dots(self):
        """Animate the loading dots"""
        if not hasattr(self, 'dot_timer'):
            self.dot_timer = QTimer()
            self.dot_timer.timeout.connect(self._update_dots)
            self.dot_index = 0

        self.dot_timer.start(500)  # Update every 500ms

    def _update_dots(self):
        """Update dot animation"""
        if hasattr(self, 'status_dots') and self.status_dots:
            # Reset all dots
            for dot in self.status_dots:
                dot.setPixmap(qta.icon('fa5s.circle', color='rgba(59, 130, 246, 0.4)').pixmap(12, 12))

            # Highlight current dot
            if self.dot_index < len(self.status_dots):
                self.status_dots[self.dot_index].setPixmap(qta.icon('fa5s.circle', color='#3b82f6').pixmap(12, 12))

            self.dot_index = (self.dot_index + 1) % len(self.status_dots)

    async def show_patient_studies(self, patient_info):
        """Display patient studies asynchronously - Optimized for speed"""
        try:
            study_uid = patient_info['StudyInstanceUID']
            patient_id = patient_info['PatientID']
            if hasattr(self, '_log_open_trace'):
                self._log_open_trace(study_uid, 'right_panel_begin', patient_id=patient_id)

            if self.source_of_patient_load == SourceOfPatientLoad.OFFLINE_CLOUD:
                server = self.data_access_panel_widget.get_server_selected()
                if not server or server.get("server_type") != "offline_cloud":
                    return

                sync_result = await asyncio.to_thread(
                    sync_offline_cloud_study_preview_to_local,
                    server,
                    study_uid,
                )
                if not sync_result.get("ok"):
                    QMessageBox.warning(
                        self,
                        "Offline Cloud",
                        sync_result.get("error") or "Could not read the offline cloud package.",
                    )
                    return

                thumbnails = {'thumbnails': []}
                all_series_thumbnails = get_all_series_thumbnail_from_study_folder(study_uid)
                for series_path in all_series_thumbnails:
                    series_number = get_name_file_from_path(series_path)
                    series_info = self.get_series_info_from_database(study_uid, series_number)
                    thumbnails['thumbnails'].append(
                        {
                            'file_path': series_path,
                            'series_number': series_number,
                            'modality': series_info.get('modality', 'Unknown'),
                            'series_description': series_info.get('series_description', f'Series {series_number}'),
                            'image_count': series_info.get('image_count', 0),
                            'protocol_name': series_info.get('protocol_name', ''),
                            'body_part_examined': series_info.get('body_part_examined', ''),
                        }
                    )
                self.display_thumbnails(thumbnails.get('thumbnails', []))
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_offline_cloud_display', thumbnail_count=len(thumbnails.get('thumbnails', [])))
                return

            # Fast check for cached thumbnails
            if check_study_complete(study_uid) or self.source_of_patient_load == SourceOfPatientLoad.DB:
                # Quick load from cache
                thumbnails = {'thumbnails': []}
                all_series_thumbnails = get_all_series_thumbnail_from_study_folder(study_uid)

                for series_path in all_series_thumbnails:
                    series_number = get_name_file_from_path(series_path)
                    # Quick database lookup
                    series_info = self.get_series_info_from_database(study_uid, series_number)

                    data = {
                        'file_path': series_path,
                        'series_number': series_number,
                        'modality': series_info.get('modality', 'Unknown'),
                        'series_description': series_info.get('series_description', f'Series {series_number}'),
                        'image_count': series_info.get('image_count', 0),
                        'protocol_name': series_info.get('protocol_name', ''),
                        'body_part_examined': series_info.get('body_part_examined', '')
                    }
                    thumbnails['thumbnails'].append(data)

                # Display cached thumbnails with spinner for consistency
                self.display_thumbnails(thumbnails.get('thumbnails', []))
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_cache_hit', thumbnail_count=len(thumbnails.get('thumbnails', [])))
                return

            # Server request only if not cached
            thumbnails = None

            try:
                from modules.viewer.fast.ui_throttle import should_defer_noncritical_open_network

                if should_defer_noncritical_open_network(
                    first_series_visible=self._is_first_series_visible_for_study(study_uid)
                ):
                    self._defer_patient_studies_refresh(patient_info)
                    _logger.info(
                        "[FAST-OPEN-GATE] deferred right-panel remote thumbnails study=%s until first series visible",
                        study_uid,
                    )
                    return
            except Exception:
                pass

            try:
                server = self.data_access_panel_widget.get_server_selected()
                if not server:
                    QMessageBox.warning(self, "Server Error", "No PACS server selected. Please select a server first.")
                    return

                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_grpc_start', host=server.get('host'))
                grpc_client = DicomGrpcClient(host=server['host'], port=50051)
                thumbnails = grpc_client.get_thumbnails(patient_id, study_uid)
                grpc_client.close()

                if thumbnails:
                    thumbnails = self.save_thumbnail(thumbnails)

                    if thumbnails and 'thumbnails' in thumbnails:
                        self.save_series_info_to_database(study_uid, thumbnails['thumbnails'])
                        # Clear cache to ensure fresh data
                        clear_study_cache(study_uid)
                        if hasattr(self, '_log_open_trace'):
                            self._log_open_trace(study_uid, 'right_panel_grpc_done', thumbnail_count=len(thumbnails['thumbnails']))
                else:
                    if hasattr(self, '_log_open_trace'):
                        self._log_open_trace(study_uid, 'right_panel_grpc_empty')
                    QMessageBox.information(self, "No Thumbnails", "No thumbnails available for this study.")

            except Exception as grpc_error:
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_grpc_error', level='error', error=str(grpc_error))
                print(f"gRPC Error: {str(grpc_error)}")
                QMessageBox.warning(self, "Connection Error",
                                    f"Failed to connect to PACS server for thumbnails:\n{str(grpc_error)}\n\nPlease check server configuration.")
                thumbnails = None

            if thumbnails:
                self.display_thumbnails(thumbnails.get('thumbnails', []))
                if hasattr(self, '_log_open_trace'):
                    self._log_open_trace(study_uid, 'right_panel_display_done', thumbnail_count=len(thumbnails.get('thumbnails', [])))

        except Exception as e:
            if 'study_uid' in locals() and hasattr(self, '_log_open_trace'):
                self._log_open_trace(study_uid, 'right_panel_error', level='error', error=str(e))
            print(f"Error in show_patient_studies: {str(e)}")
            raise

    def get_search_data(self):
        """Get search data from PatientSearchWidget"""
        return self.patient_search_widget.get_search_data()

    def clear_search_fields(self):
        """Clear all search fields"""
        self.patient_search_widget.clear_search_fields()

    def set_search_data(self, data):
        """Set search field values"""
        self.patient_search_widget.set_search_data(data)

    def has_search_criteria(self):
        """Check if any search criteria has been entered"""
        return self.patient_search_widget.has_search_criteria()

    def get_search_summary(self):
        """Get a summary of the current search criteria"""
        return self.patient_search_widget.get_search_summary()

    def validate_search_data(self):
        """Validate the search data for common format issues"""
        return self.patient_search_widget.validate_search_data()

    def clear_patient_table(self):
        """Clear all data from the patient table"""
        self.patient_table_widget.clear_table()

    def get_selected_patient_data(self):
        """Get data from the currently selected row in the patient table"""
        return self.patient_table_widget.get_selected_patient_data()

    def get_patient_data_by_row(self, row):
        """Get patient data from a specific row in the patient table"""
        return self.patient_table_widget.get_patient_data_by_row(row)

    def get_all_patient_data(self):
        """Get all patient data from the table"""
        return self.patient_table_widget.get_all_patient_data()

    def search_in_patient_table(self, search_text, column_index=None):
        """Search for text in the patient table"""
        return self.patient_table_widget.search_in_table(search_text, column_index)

    def highlight_patient_rows(self, row_indices):
        """Highlight specific rows in the patient table"""
        self.patient_table_widget.highlight_rows(row_indices)

    def get_patient_table_row_count(self):
        """Get the number of rows in the patient table"""
        return self.patient_table_widget.get_row_count()
