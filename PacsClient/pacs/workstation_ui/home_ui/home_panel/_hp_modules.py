"""Module launchers: DM, web browser, education, printing, NPR, CD burn, tabs"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio
import logging
import traceback

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from ..home_module_tabs import activate_or_create_module_tab
from ..home_widget_utils import is_widget_alive
from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.utils import get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from aipacs_runtime import is_module_enabled

from .widget import _ensure_patient_widget, _ensure_ai_main_window, PRIORITY_MANAGER_AVAILABLE

logger = logging.getLogger(__name__)

class _HPModulesMixin:
    """Module launchers: DM, web browser, education, printing, NPR, CD burn, tabs"""

    def set_mainwindow(self, MainWindow):
        self.mainwindow = MainWindow

    def open_download_manager(self):
        """Open download manager - switches to existing tab if available, otherwise creates new one - Uses Zeta with v1.0.6 UI"""
        print("[HomePanelWidget] open_download_manager called (Zeta Download Manager with v1.0.6 UI)")
        try:
            download_manager = self._get_or_create_download_manager_tab(activate_tab=True)
            if download_manager is None:
                print("[HomePanelWidget] Error: Download Manager widget not available")
                return

            print("[HomePanelWidget] Download Manager opened successfully (Zeta with v1.0.6 UI)")
        except Exception as e:
            print(f"[HomePanelWidget] Error opening download manager: {str(e)}")
            import traceback
            traceback.print_exc()

    def open_web_browser(self):
        """Open web browser in a new tab"""
        try:
            if not is_module_enabled("web_browser"):
                QMessageBox.information(self, "Web Browser Module",
                                        "The Web Browser module is not installed for this workstation.")
                return
            from modules.web_browser import WebBrowserWidget
            activate_or_create_module_tab(
                self.tab_widget, self.custom_tab_manager,
                tab_flag_key='is_web_browser_tab',
                widget_factory=WebBrowserWidget,
                add_tab_method_name='add_web_browser_tab',
                fallback_label='Web Browser',
            )
        except Exception as e:
            print(f"[HomePanelWidget] Error opening web browser: {e}")
            import traceback; traceback.print_exc()

    def open_education_module(self):
        """Open education module in a new tab"""
        try:
            from modules.education.education_module_redesigned import EducationModuleRedesigned
            activate_or_create_module_tab(
                self.tab_widget, self.custom_tab_manager,
                tab_flag_key='is_education_tab',
                widget_factory=lambda: EducationModuleRedesigned(
                    parent=self,
                    host_tab_widget=self.tab_widget,
                    host_custom_tab_manager=self.custom_tab_manager,
                    host_parent=self,
                ),
                add_tab_method_name='add_education_module_tab',
                fallback_label='Educational Module',
            )
        except Exception as e:
            print(f"[HomePanelWidget] Error opening education module: {e}")
            import traceback; traceback.print_exc()

    def open_printing_module(self):
        """Open printing module in a new tab"""
        try:
            if not is_module_enabled("printing"):
                QMessageBox.information(self, "Printing Module",
                                        "The Printing module is not installed for this workstation.")
                return

            selected_patients = []
            if hasattr(self, 'patient_table_widget') and hasattr(self.patient_table_widget, 'get_selected_patient_data_list'):
                selected_patients = self.patient_table_widget.get_selected_patient_data_list() or []

            if not selected_patients:
                QMessageBox.warning(self, "Printing", "Please select at least one patient in the list.")
                return

            # Printing is special: update existing tab with new patient selection
            from ..home_module_tabs import find_existing_module_tab
            existing_idx = find_existing_module_tab(self.tab_widget, self.custom_tab_manager, 'is_printing_tab')
            if existing_idx is not None:
                self.tab_widget.setCurrentIndex(existing_idx)
                tab_data = self.custom_tab_manager.patient_tabs.get(existing_idx, {})
                printing_widget = tab_data.get('widget')
                if printing_widget and hasattr(printing_widget, 'update_patients'):
                    printing_widget.update_patients(selected_patients)
                return

            from modules.printing.ui.printing_widget import PrintingWidget
            activate_or_create_module_tab(
                self.tab_widget, self.custom_tab_manager,
                tab_flag_key='is_printing_tab',
                widget_factory=lambda: PrintingWidget(
                    parent=self,
                    host_tab_widget=self.tab_widget,
                    host_custom_tab_manager=self.custom_tab_manager,
                    selected_patients=selected_patients,
                ),
                add_tab_method_name='add_printing_tab',
                fallback_label='Printing',
            )
        except Exception as e:
            print(f"[HomePanelWidget] Error opening printing module: {e}")
            import traceback; traceback.print_exc()
            try:
                QMessageBox.critical(self, "Printing", f"Failed to open Printing module:\n{e}")
            except Exception:
                pass

    def open_reception_data_tab(self):
        """Open Reception Data tab"""
        try:
            from modules.ai_imaging.ai_module_ui.service_tab import ReceptionDataTab
            activate_or_create_module_tab(
                self.tab_widget, self.custom_tab_manager,
                tab_flag_key='is_reception_data_tab',
                widget_factory=ReceptionDataTab,
                add_tab_method_name='add_reception_data_tab',
                fallback_label='Reception Data',
            )
        except Exception as e:
            print(f"[HomePanelWidget] Error opening Reception Data tab: {e}")
            import traceback; traceback.print_exc()

    def add_new_tab_widget(self, patient_id=None, patient_name=None, folder_path=None, open_ai_client_tab=False,
                        caller=None, study_uid=None, enable_progressive_mode=False, report_status='pending',
                        viewer_backend_override=None):

        if open_ai_client_tab is True:
            try:
                ai_client = _ensure_ai_main_window()(study_uid=study_uid)
                self.tab_widget.addTab(ai_client, "AI Analysis")
                self.tab_widget.setCurrentWidget(ai_client)
                return ai_client
            except Exception as e:
                print(f"Error opening AI client: {str(e)}")
                import traceback
                traceback.print_exc()
                return None
        else:
            patient_name = patient_name if patient_name is not None else 'N/A'

            # Prevent duplicate PatientWidget creation for the same study
            if study_uid:
                existing_widget = None
                
                # First check: Look in custom tab manager
                if self.custom_tab_manager:
                    existing_index = self.custom_tab_manager.find_tab_by_study_uid(study_uid)
                    if existing_index is not None and existing_index != -1:
                        try:
                            # Verify the widget is still valid before activating
                            widget_at_index = self.tab_widget.widget(existing_index)
                            if widget_at_index and hasattr(widget_at_index, 'study_uid'):
                                self.custom_tab_manager.set_tab_active(existing_index)
                                tab_info = self.custom_tab_manager.get_patient_tab_info(existing_index)
                                if tab_info:
                                    existing_widget = tab_info.get('widget')
                                if existing_widget:
                                    try:
                                        # Verify widget is not deleted
                                        _ = existing_widget.isVisible()
                                        existing_widget.update_tab_manager(
                                            patient_name=patient_name,
                                            patient_id=patient_id
                                        )
                                        return existing_widget
                                    except RuntimeError:
                                        # Widget was deleted, continue to create new
                                        print(f"⚠️ Cached widget for study {study_uid} was deleted, creating new one")
                                        existing_widget = None
                        except Exception as e:
                            print(f"⚠️ Error with custom tab manager: {e}")

                # Second check: Look in local cache dict_tabs_widget
                if existing_widget is None and study_uid in self.dict_tabs_widget:
                    cached_widget = self.dict_tabs_widget.get(study_uid)
                    if cached_widget:
                        if not is_widget_alive(cached_widget):
                            print(f"⚠️ Cached widget for study {study_uid} has been deleted, removing from cache")
                            del self.dict_tabs_widget[study_uid]
                        else:
                            idx = self.tab_widget.indexOf(cached_widget)
                            if idx != -1:
                                if self.custom_tab_manager:
                                    self.custom_tab_manager.set_tab_active(idx)
                                else:
                                    self.tab_widget.setCurrentIndex(idx)
                                return cached_widget
                            else:
                                print(f"⚠️ Widget for study {study_uid} not found in tabs, removing from cache")
                                del self.dict_tabs_widget[study_uid]

                # Third check: Scan all tabs for matching study_uid (fallback)
                if existing_widget is None and self.tab_widget:
                    for i in range(self.tab_widget.count()):
                        w = self.tab_widget.widget(i)
                        if hasattr(w, 'study_uid') and w.study_uid == study_uid:
                            if is_widget_alive(w):
                                self.dict_tabs_widget[study_uid] = w
                                try:
                                    if self.custom_tab_manager:
                                        self.custom_tab_manager.set_tab_active(i)
                                    else:
                                        self.tab_widget.setCurrentIndex(i)
                                except Exception as e:
                                    print(f"⚠️ Error switching to existing tab: {e}")
                                return w

            # Create new widget if not found or existing was invalid
            if not enable_progressive_mode and study_uid and caller == CallerTypes.SERVER:
                from PacsClient.pacs.patient_tab.utils import check_study_complete
                is_complete = check_study_complete(study_uid)
                enable_progressive_mode = not is_complete
            
            widget = _ensure_patient_widget()(
                import_folder_path=folder_path, 
                caller=caller, 
                study_uid=study_uid, 
                patient_id=patient_id,
                enable_progressive_mode=enable_progressive_mode,
                report_status=report_status,
                viewer_backend_override=viewer_backend_override,
            )
            widget.set_method_open_ai_module_tab(self.add_new_tab_widget)
            
            # Connect signals
            if hasattr(widget, 'thumbnail_manager') and widget.thumbnail_manager is not None:
                widget.thumbnail_manager.set_current_study_uid(study_uid)

                def on_priority_download_requested(series_number, study_uid_param):
                    print(f"🎯 [HomeUI] Priority download requested: series={series_number}, study={study_uid_param}")
                    self._handle_priority_download_from_thumbnail(series_number, study_uid_param, widget)

                widget.thumbnail_manager.priority_download_requested.connect(on_priority_download_requested)
                print(f"✅ Connected priority download signal for study {study_uid}")
                        
            if study_uid:
                download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
                if download_manager:
                    download_manager.download_completed.connect(
                        lambda completed_study_uid: widget.refresh_after_download(completed_study_uid)
                        if completed_study_uid == study_uid else None
                    )

            # Add to tab widget
            if self.custom_tab_manager:
                tab_index = self.custom_tab_manager.add_patient_tab(
                    patient_name=patient_name,
                    patient_id=patient_id or "N/A",
                    thumbnail_path=None,
                    widget=widget,
                    study_uid=study_uid,
                    activate=False
                )
                
                # Check if tab addition failed due to max patient tabs limit
                if tab_index == -1:
                    # Show error message
                    QMessageBox.warning(
                        self,
                        "Maximum Patient Tabs Reached",
                        f"You can only open a maximum of 3 patient tabs at once.\n\n"
                        f"Please close one of the existing patient tabs before opening a new one."
                    )
                    # Clean up the widget
                    widget.deleteLater()
                    return
                
                widget.set_tab_manager(self.custom_tab_manager)
                widget.update_tab_manager(patient_name=patient_name, patient_id=patient_id)
            else:
                tab_index = self.tab_widget.addTab(widget, patient_name)

            if study_uid:
                self.dict_tabs_widget[study_uid] = widget

            # Notify priority manager
            if study_uid and PRIORITY_MANAGER_AVAILABLE:
                try:
                    print(f"🏠 [HOME-UI] Calling on_patient_tab_opened for {patient_name}")
                    priority_manager = get_download_priority_manager()
                    priority_manager.on_patient_tab_opened(
                        study_uid=study_uid,
                        patient_id=patient_id or "",
                        patient_name=patient_name or ""
                    )
                    print(f"🏠 [HOME-UI] on_patient_tab_opened completed")
                except Exception as e:
                    print(f"🏠 [HOME-UI] ERROR in on_patient_tab_opened: {e}")
                    import traceback
                    traceback.print_exc()

            return widget

    def show_patient_info(self, row):
        """Show detailed patient information"""
        try:
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_date = patient_data['study_date']
            description = patient_data['description']
            modality = patient_data['modality']
            study_uid = patient_data['study_uid']

            info_text = f"""
Patient Information:
━━━━━━━━━━━━━━━━━━━━━━━
Patient ID: {patient_id}
Patient Name: {patient_name}
Study Date: {study_date}
Description: {description}
Modality: {modality}
Study UID: {study_uid}
━━━━━━━━━━━━━━━━━━━━━━━
            """.strip()

            QMessageBox.information(self, "Patient Information", info_text)

        except Exception as e:
            print(f"Error in show_patient_info: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error showing patient info: {str(e)}")

    def _trace_action_start(self, action_type: str, context: dict = None) -> str:
        """Create a deterministic action marker and return action_id."""
        try:
            from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
            return VTKWidget.register_action_start(action_type, context=context or {})
        except Exception:
            return ""

    def _trace_action_done(self, action_id: str, phase: str, extra: dict = None):
        """Close an action marker (used for early-exit paths with no viewer switch)."""
        try:
            if not action_id:
                return
            from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
            VTKWidget.register_action_done(action_id, phase=phase, extra=extra or {})
        except Exception:
            pass

    def _attach_action_to_widget(self, widget, action_id: str, series_number: str = None):
        """Attach a pending action id to patient widget and its viewers for completion in switch_series."""
        try:
            if not widget or not action_id:
                return

            setattr(widget, '_pending_action_id', action_id)
            if series_number is not None:
                setattr(widget, '_pending_action_series', str(series_number))

            viewer_controller = getattr(widget, 'viewer_controller', None)
            if not viewer_controller:
                return

            selected_widget = getattr(viewer_controller, 'selected_widget', None)
            if selected_widget is not None:
                selected_widget._pending_action_id = action_id
                if series_number is not None:
                    selected_widget._pending_action_series = str(series_number)
            else:
                # Fallback: attach only to first viewport (avoid broadcasting to all viewers)
                nodes = getattr(viewer_controller, 'lst_nodes_viewer', []) or []
                if nodes:
                    vtk_w = getattr(nodes[0], 'vtk_widget', None)
                    if vtk_w is not None:
                        vtk_w._pending_action_id = action_id
                        if series_number is not None:
                            vtk_w._pending_action_series = str(series_number)
        except Exception:
            pass

    async def on_plus_button_clicked(self, row):
        """Handler for '+' button to retrieve patient thumbnail images"""
        try:
            # Get patient data from PatientTableWidget
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if not patient_data:
                raise Exception("Patient data not found")

            patient_id = patient_data['patient_id']
            patient_name = patient_data['patient_name']
            study_uid = patient_data['study_uid']

            # Loading dialog is already shown in _safe_on_plus_button_clicked
            # No need to show it again here

            patient_info = {
                "PatientID": patient_id,
                "PatientName": patient_name,
                "StudyInstanceUID": study_uid
            }

            logger.debug("on_plus_button_clicked: starting study thumbnail display")
            await self.show_patient_studies(patient_info)

        except Exception as e:
            print(f"Error in on_plus_button_clicked: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error displaying images: {str(e)}")

        finally:
            self.hide_loading()

    async def _safe_on_plus_button_clicked(self, row):
        """Safe wrapper for on_plus_button_clicked with proper error handling"""
        try:
            # Show loading dialog immediately
            patient_data = self.patient_table_widget.get_patient_data_by_row(row)
            if patient_data:
                self.show_loading("Loading Thumbnails", f"Loading thumbnails for {patient_data['patient_name']}...")

            await self.on_plus_button_clicked(row)
        except Exception as e:
            print(f"Error in _safe_on_plus_button_clicked: {str(e)}")

            # Handle different types of errors gracefully
            error_message = "Error retrieving information from server"
            if "UNAVAILABLE" in str(e) or "connection" in str(e).lower():
                error_message = "Server is unavailable. Please check your network connection."
            elif "timeout" in str(e).lower():
                error_message = "Server connection timed out. Please try again."

            # Hide loading dialog first
            self.hide_loading()

    def _on_zeta_npr_requested(self, selected_studies, set_current_tab=True):
        """
        Handle Zeta Download button click - uses main Download Manager tab
        Updated to use the same Download Manager tab as the sidebar button
        """
        print('🚀 [Zeta NPR] Button clicked - opening in Download Manager tab')
        try:
            # Check if server is selected
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                QMessageBox.warning(self, "Server Not Selected",
                                    "Please select a PACS server first.")
                return
            if server.get("server_type") == "offline_cloud":
                QMessageBox.information(
                    self,
                    "Offline Cloud Server",
                    "The selected server is an Offline Cloud Server. Download Manager is only available for online AI PACS servers.",
                )
                return
            
            print(f"🚀 [Zeta NPR] Server selected - {server}")
            
            # Get or create the main Download Manager tab (same as sidebar button)
            download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
            
            if not download_manager:
                QMessageBox.critical(self, "Error", "Failed to open Download Manager")
                return
            
            # Switch to download manager tab if requested
            if set_current_tab:
                for i in range(self.tab_widget.count()):
                    if self.tab_widget.widget(i) == download_manager:
                        self.tab_widget.setCurrentIndex(i)
                        break
            
            # Enhance selected_studies with series information if not present
            for study in selected_studies:
                if 'series' not in study or not study.get('series'):
                    try:
                        study_uid = study.get('study_uid')
                        patient_id = study.get('patient_id')
                        if study_uid:
                            study_info = self._get_or_fetch_series_info(study_uid, patient_id)
                            if study_info:
                                study['series'] = study_info.get('series', [])
                                study['series_count'] = study_info.get('count_of_series', len(study.get('series', [])))
                                if study.get('series'):
                                    study['images_count'] = sum(s.get('image_count', 0) for s in study['series'])
                                print(f"🚀 [Zeta NPR] Fetched {len(study.get('series', []))} series")
                    except Exception as e:
                        print(f"⚠️ [Zeta NPR] Could not fetch series info: {e}")
            
            # Add studies to download manager
            print(f"[Zeta NPR] Adding {len(selected_studies)} studies to manager")
            download_manager.add_downloads(selected_studies, start_immediately=True)
            print(f"[Zeta NPR] Studies added and downloads started automatically")
            # Throttle all ZetaBoost warmup workers globally while any download runs.
            try:
                from modules.zeta_boost.engine import set_global_download_active
                set_global_download_active(True)
                print("[GlobalDL] set_global_download_active=True")
            except Exception:
                pass

            if len(selected_studies) > 0:
                print(f"[Zeta NPR] ✅ Added {len(selected_studies)} studies to queue")
                # UI feedback - downloads will appear in Download Manager tab
            else:
                print(f"[Zeta NPR] ⚠️ No new studies added (may already be in queue)")

        except Exception as e:
            print(f"❌ Error in Zeta Download: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in Zeta Download: {str(e)}")

    def _on_cd_burn_requested(self, selected_studies):
        """Handle CD burn request from patient table"""
        print('💿 CD burn requested')
        try:
            if not is_module_enabled("run_cd"):
                QMessageBox.information(
                    self,
                    "Run CD Module",
                    "The Run CD module is not installed for this workstation.",
                )
                return

            if not selected_studies:
                QMessageBox.warning(self, "No Studies Selected",
                                    "Please select at least one study for CD burning.")
                return
            
            # Import CD burn dialog
            from modules.cd_burner.cd_burn_dialog import CDBurnDialog
            
            dialog = CDBurnDialog(selected_studies, self)
            dialog.exec()
            
        except ImportError as e:
            print(f"Error importing CD burn dialog: {str(e)}")
            QMessageBox.critical(self, "Error", 
                               "CD burn module is not available.\n\n"
                               "Please make sure pydicom and comtypes libraries are installed.")
        except Exception as e:
            print(f"Error in _on_cd_burn_requested: {str(e)}")
            import traceback
            traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Error in CD burn request: {str(e)}")

    def get_patient_study(self, study_uid):
        """Get patient study details (delegates to service)."""
        return self.db_service.get_patient_study(study_uid)

    def save_study_details(self, dataset):
        """Save study details from pydicom Dataset (delegates to service)."""
        self.db_service.save_study_details(dataset)

    def _create_loading_feed(self, message="Loading medical images..."):
        """No-op: loading feed disabled by request."""
        return

    def _update_loading_feed(self, message="Loading..."):
        """No-op: loading feed disabled by request."""
        return

    def _hide_loading_feed(self):
        """No-op: loading feed disabled by request."""
        return

    def _reset_thumbnails_event(self):
        import asyncio
        self._thumbs_event = asyncio.Event()

    def _signal_thumbnails_ready(self):
        # called when thumbnails are rendered on UI
        try:
            if getattr(self, "_thumbs_event", None) and not self._thumbs_event.is_set():
                self._thumbs_event.set()
        except Exception as _:
            pass
