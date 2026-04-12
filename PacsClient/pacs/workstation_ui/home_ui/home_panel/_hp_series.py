"""Series info, thumbnails, right panel display"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio
import time
import threading
import traceback

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize
from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QGroupBox, QPushButton, QGridLayout, QLineEdit, QTableWidget, QAbstractItemView, QHeaderView, QCheckBox, QScrollArea, QToolButton, QTableWidgetItem, QMessageBox, QApplication, QProgressDialog, QTabWidget, QLabel, QFileDialog, QProgressBar, QStatusBar, QSplitter, QDialog, QGraphicsDropShadowEffect, QSizePolicy, QWidget

from PacsClient.pacs.patient_tab.utils import save_thumbnail_with_bytes, save_series_json, check_study_exists, get_all_series_thumbnail_from_study_folder, load_json_as_dict, get_study_source_path, get_name_file_from_path, check_study_complete, validate_thumbnail_files, clear_study_cache, get_count_dicom_files_exist, save_image_as_png
from PacsClient.utils import get_connection_database, get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from PacsClient.utils.config import THUMBNAIL_PATH

from .widget import SourceOfPatientLoad

class _HPSeriesMixin:
    """Series info, thumbnails, right panel display"""

    def _on_patient_single_clicked(self, patient_id, patient_name, study_uid):
        """Handle patient single-click event - Show detailed series information"""
        try:
            _t0 = time.perf_counter()
            # Show loading dialog immediately
            self.show_loading("Loading Series Info", f"Retrieving information for {patient_name}...")
            
            # v2.2.9.2 — deferred task creation (50 ms) to mitigate asyncio
            # reentrancy with Python 3.13 strict enforcement.  Also adds a
            # 5 s safety timeout to hide the loading dialog if the task fails
            # to run (qasync reentrancy can silently kill pending tasks).
            self._series_info_loading_active = True
            QTimer.singleShot(50, lambda: self._schedule_series_info_load(
                patient_id, patient_name, study_uid))
            QTimer.singleShot(5000, self._series_info_loading_timeout)
            print(f"[PROFILE] single-click: scheduled series info load for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            
        except Exception as e:
            print(f"Error in _on_patient_single_clicked: {str(e)}")
            self.hide_loading()
            QMessageBox.critical(self, "Error", f"Error displaying series information: {str(e)}")

    def _schedule_series_info_load(self, patient_id, patient_name, study_uid):
        """v2.2.9.2 — create async task with reentrancy fallback."""
        try:
            task = asyncio.create_task(
                self._load_and_display_series_info_async(
                    patient_id, patient_name, study_uid))
            def _on_done(t):
                self._series_info_loading_active = False
            task.add_done_callback(_on_done)
        except RuntimeError:
            # No running loop — run in thread with main-thread dispatch
            self._series_info_loading_active = False
            self.hide_loading()

    def _series_info_loading_timeout(self):
        """v2.2.9.2 — safety timeout for stuck series info loading."""
        if getattr(self, '_series_info_loading_active', False):
            self._series_info_loading_active = False
            print("[WARNING] Series info load timed out (possible asyncio reentrancy)")
            self.hide_loading()

    async def _load_and_display_series_info_async(self, patient_id, patient_name, study_uid):
        """Async wrapper for _load_and_display_series_info"""
        try:
            await self._load_and_display_series_info(patient_id, patient_name, study_uid)
        except Exception as e:
            print(f"Error in _load_and_display_series_info_async: {str(e)}")
            self.hide_loading()

    async def _load_and_display_series_info(self, patient_id, patient_name, study_uid):
        """Load and display detailed series information in right panel - Optimized for speed"""
        try:
            _t0 = time.perf_counter()

            # First check if we have complete series info in database
            if check_study_complete(study_uid) or self.source_of_patient_load == SourceOfPatientLoad.DB:
                _t_db = time.perf_counter()

                # Get series info from database
                from PacsClient.utils.db_manager import find_study_pk_with_study_uid, get_series_by_study_pk

                study_pk = find_study_pk_with_study_uid(study_uid)
                if study_pk:
                    series_list = get_series_by_study_pk(study_pk)
                    if series_list:
                        # Convert database format to expected format
                        study_info = {
                            'study_uid': study_uid,
                            'patient_id': patient_id,
                            'patient_name': patient_name,
                            'study_date': '',  # Will be filled from database if needed
                            'study_description': f'Study {study_uid[:8]}...',
                            'count_of_series': len(series_list),
                            'thumbnails_available': True,
                            'series': []
                        }

                        for series in series_list:
                            series_info = {
                                'series_uid': series.get('series_uid', ''),
                                'series_number': series.get('series_number', ''),
                                'series_description': series.get('series_description', ''),
                                'modality': series.get('modality', ''),
                                'image_count': series.get('image_count', 0),
                                'protocol_name': series.get('protocol_name', ''),
                                'body_part_examined': series.get('body_part_examined', ''),
                                'manufacturer': series.get('manufacturer', ''),
                                'institution_name': series.get('institution_name', '')
                            }
                            study_info['series'].append(series_info)

                        self._display_series_info_in_right_panel(study_info)
                        print(f"[PROFILE] single-click: DB series info loaded for {study_uid} in {(time.perf_counter() - _t_db)*1000:.1f}ms")

                        # Load thumbnails from cache for downloaded studies (local, no regeneration)
                        await self._load_thumbnails_for_downloaded_study(study_uid, series_list)
                        print(f"[PROFILE] single-click: thumbnails loaded for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
                        return

            # Server request only if not cached

            # Get detailed series information from server
            study_info = self._get_or_fetch_series_info(study_uid, patient_id)

            print('study_info:', study_info)
            if study_info:
                # Display series information in right panel
                self._display_series_info_in_right_panel(study_info)

                # Also save to database for future use (pass study_info to avoid double fetch)
                success = self.save_complete_study_info(study_uid, patient_id, study_info=study_info)
                if success:
                    # Clear cache to ensure fresh data
                    clear_study_cache(study_uid)
                print(f"[PROFILE] single-click: server series info loaded for {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            else:
                QMessageBox.information(self, "No Information",
                                        f"No detailed series information available for study: {study_uid}")

        except Exception as e:
            print(f"Error in _load_and_display_series_info: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error retrieving series information: {str(e)}")
        finally:
            self.hide_loading()

    async def _load_thumbnails_for_downloaded_study(self, study_uid, series_list):
        """
        Load and display thumbnails for a downloaded study from database/cache
        OPTIMIZED: Fast loading with minimal blocking
        """
        try:
            _t0 = time.perf_counter()
            from PacsClient.pacs.patient_tab.utils.utils import THUMBNAIL_PATH
            from pathlib import Path
            
            thumbnail_dir = THUMBNAIL_PATH / study_uid
            
            if not thumbnail_dir.exists():
                print(f"[WARNING] No thumbnail cache found for study {study_uid}")
                return
            
            # Get all thumbnail files once (faster than repeated lookups)
            thumbnail_files = {f.stem: str(f) for f in thumbnail_dir.glob('*.jpg')}
            thumbnail_files.update({f.stem: str(f) for f in thumbnail_dir.glob('*.png')})
            
            if not thumbnail_files:
                print(f"[WARNING] No thumbnail images found in {thumbnail_dir}")
                return
            
            # Build thumbnails list from series info and cached files
            thumbnails = []
            
            for series in series_list:
                series_number = str(series.get('series_number', ''))
                series_uid = series.get('series_uid', '')
                
                # Try to find thumbnail by series_number
                thumb_file_path = None
                
                # Direct match by series number
                if series_number in thumbnail_files:
                    thumb_file_path = thumbnail_files[series_number]
                # Try with leading zeros (001, 01, etc)
                elif series_number.lstrip('0') in thumbnail_files:
                    thumb_file_path = thumbnail_files[series_number.lstrip('0')]
                
                # If not found, skip this series
                if not thumb_file_path:
                    continue
                
                thumbnails.append({
                    'file_path': thumb_file_path,
                    'series_uid': series_uid,
                    'series_number': series_number,
                    'series_description': series.get('series_description', ''),
                    'modality': series.get('modality', ''),
                    'image_count': series.get('image_count', 0)
                })
            
            # Display thumbnails if found
            if thumbnails and hasattr(self, 'right_panel_widget'):
                # Use await to yield control and prevent blocking
                await asyncio.sleep(0)
                # Show immediately for downloaded studies (no progressive delay)
                self.right_panel_widget.display_thumbnails(thumbnails, progressive=False)
                print(f"[OK] Displayed {len(thumbnails)} cached thumbnails for study {study_uid}")
                print(f"[PROFILE] thumbnails cache display: {study_uid} in {(time.perf_counter() - _t0)*1000:.1f}ms")
            
        except Exception as e:
            print(f"[ERROR] Error loading thumbnails for downloaded study: {str(e)}")
            import traceback
            traceback.print_exc()

    def _get_or_fetch_series_info(self, study_uid, patient_id):
        """
        Get series info from cache or fetch from server.

        This reduces repeated network calls across download requests and
        patient open flows in the same session.
        """
        if not study_uid:
            return None

        cached = self._series_info_cache.get(study_uid)
        if cached:
            return cached

        study_info = self.get_series_info_from_server(study_uid, patient_id)
        if study_info:
            self._series_info_cache[study_uid] = study_info
        return study_info

    def get_series_statistics_from_list(self, series_list):
        """Get statistics from series list"""
        try:
            if not series_list:
                return None

            total_series = len(series_list)
            total_images = sum(s.get('image_count', 0) for s in series_list)

            # Count modalities
            modalities = {}
            for series in series_list:
                modality = series.get('modality', 'Unknown')
                modalities[modality] = modalities.get(modality, 0) + 1

            # Calculate average
            average_images = total_images / total_series if total_series > 0 else 0

            return {
                'total_series': total_series,
                'total_images': total_images,
                'modalities': modalities,
                'average_images_per_series': round(average_images, 2)
            }

        except Exception as e:
            print(f"Error in get_series_statistics_from_list: {str(e)}")
            return None

    def _display_series_info_in_right_panel(self, study_info):
        """Display series information in the right panel using the new component"""
        try:

            # Use the new right panel widget
            self.right_panel_widget.display_series_info(study_info)


        except Exception as e:
            print(f"Error in _display_series_info_in_right_panel: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error displaying series information: {str(e)}")

    async def download_and_open_tab(self, dicom_downloader, study_uid, output_dir):
        # self.show_loading("Downloading", "Retrieving DICOM files...")
        try:
            # Create a simple progress callback for this download
            def simple_progress_callback(event_type, series_number, progress_percent):
                """Simple progress callback for download_and_open_tab"""
                pass  # Progress handled silently

            await asyncio.to_thread(
                dicom_downloader.download_study_dicom_files_streaming,
                study_uid, output_dir, 0, simple_progress_callback
            )
            print('finished downloading:', output_dir)
        except Exception as e:
            # QMessageBox.critical(self, "Error", f"Error downloading: {str(e)}")
            print('error in downloading..:', e)

    async def _download_series_on_demand(self, widget, study_uid, series_list, base_output_dir, server, clicked_series=None):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        All downloads must now route through Zeta Download Manager via _get_or_create_download_manager_tab().
        
        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy _download_series_on_demand has been removed. "
            "Please use Zeta Download Manager via _get_or_create_download_manager_tab().add_downloads() instead."
        )

    async def _download_series_fallback(self, widget, study_uid, series_list, base_output_dir, server):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        All downloads must now route through Zeta Download Manager.
        
        Raises NotImplementedError to force use of Zeta Download Manager.
        """
        raise NotImplementedError(
            "Legacy _download_series_fallback has been removed. "
            "Please use Zeta Download Manager via _get_or_create_download_manager_tab().add_downloads() instead."
        )

    def display_thumbnails(self, thumbnails):
        """Display received thumbnail images using the new right panel component"""
        try:
            # Use the new right panel widget
            self.right_panel_widget.display_thumbnails(thumbnails)
        except Exception as e:
            print(f"Error displaying thumbnails: {str(e)}")
            raise
        finally:
            # after UI lays out thumbnails in the next event loop tick, mark as ready
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._signal_thumbnails_ready)

    def save_thumbnail(self, series_thumbnails: dict):
        # print('thuuuuuuuu:', series_thumbnails)
        study_uid = series_thumbnails.get('study_uid')

        all_series_data: dict = series_thumbnails.get('thumbnails')
        for i in range(len(all_series_data)):
            series = all_series_data[i]

            series_uid = series.get('series_uid')

            series_number = series.get('series_number')
            series_description = series.get('series_description')
            modality = series.get('modality')
            image_count = series.get('image_count')

            file_path = save_thumbnail_with_bytes(study_uid, series_number, series.get('thumbnail_data'))
            all_series_data[i]['file_path'] = file_path

            # save series data on json file
            # save_series_json(study_uid, series_uid=series_uid, series_number=series_number,
            #                  series_description=series_description, modality=modality, image_count=image_count,
            #                  file_path=file_path)

        series_thumbnails['thumbnails'] = all_series_data

        return series_thumbnails

    def _on_thumbnail_requested(self, row):
        """Handle thumbnail request from PatientTableWidget"""
        # Use QTimer to defer the async call to avoid RuntimeWarning
        QTimer.singleShot(0, lambda: self._start_thumbnail_task(row))

    def _start_thumbnail_task(self, row):
        """Start thumbnail task safely"""
        try:
            # Cancel any existing task
            if hasattr(self, '_current_thumbnail_task') and self._current_thumbnail_task:
                try:
                    if not self._current_thumbnail_task.done():
                        self._current_thumbnail_task.cancel()
                except:
                    pass

            # Create and store the task to prevent RuntimeWarning
            self._current_thumbnail_task = asyncio.create_task(self._safe_on_plus_button_clicked(row))
            # Add done callback to handle cleanup
            self._current_thumbnail_task.add_done_callback(self._thumbnail_task_cleanup)
        except Exception as e:
            print(f"Error in thumbnail task cleanup: {str(e)}")

    def _thumbnail_task_cleanup(self, task):
        """Clean up completed thumbnail task"""
        try:
            if task.exception():
                self._current_thumbnail_task = None
        except Exception as e:
            print(f"Error in thumbnail task cleanup: {str(e)}")

    def _on_thumbnail_clicked(self, series_number):
        """Handle thumbnail click"""

    def _on_right_panel_thumbnail_clicked(self, series_number):
        """Handle thumbnail click - prioritize this series for download"""
        action_id = self._trace_action_start(
            "thumbnail_click",
            context={'series_number': str(series_number)}
        )
        print(f"\n{'='*80}")
        print(f"🎯 [HIGH PRIORITY] User clicked series {series_number} - IMMEDIATE DOWNLOAD REQUEST")
        print(f"{'='*80}\n")
        
        # بررسی کنید که آیا این متد اصلاً فراخوانی می‌شود
        print(f"📢 DEBUG: _on_right_panel_thumbnail_clicked CALLED with series: {series_number}")
        
            
        # Immediate debug logging
        print(f"📊 Checking right panel state...")
        if not hasattr(self, 'right_panel_widget'):
            print(f"❌ Right panel widget not available")
            return
        
        # Get current study information
        study_info = getattr(self.right_panel_widget, '_current_study_info', None)
        if not study_info or 'series' not in study_info:
            print(f"❌ No study info available or no series list")
            return
        
        series_list = study_info['series']
        study_uid = study_info.get('study_uid', 'unknown')
        print(f"✅ Found study: {study_uid}")
        print(f"✅ Available series: {[s.get('series_number', '?') for s in series_list]}")
        
        # Find the widget for this study
        widget = self._find_widget_by_study_uid(study_uid)
        if not widget:
            self._trace_action_done(action_id, phase='thumbnail_widget_not_found', extra={'study_uid': str(study_uid)})
            print(f"❌ Widget not found for study {study_uid}")
            return
        
        print(f"✅ Widget found: {type(widget).__name__}")
        self._attach_action_to_widget(widget, action_id, series_number=str(series_number))
        
        # Get server connection
        server = self.data_access_panel_widget.get_server_selected()
        if not server:
            self._trace_action_done(action_id, phase='thumbnail_no_server', extra={'study_uid': str(study_uid)})
            print(f"❌ No server selected")
            return
        
        # Start IMMEDIATE priority download
        output_dir = str(SOURCE_PATH / study_uid)
        print(f"🎯 Starting IMMEDIATE download for series {series_number}...")
        
        # Create and start immediate download task
        task = asyncio.create_task(
            self._download_single_series_immediate(
                widget=widget,
                study_uid=study_uid,
                series_list=series_list,
                base_output_dir=output_dir,
                server=server,
                target_series=series_number
            )
        )
        
        # Store task reference
        if not hasattr(self, '_priority_tasks'):
            self._priority_tasks = {}
        self._priority_tasks[series_number] = task
        
        # Add cleanup callback
        task.add_done_callback(lambda t: self._cleanup_priority_task(series_number))

    def _on_right_panel_series_clicked(self, series_number):
        """Handle series click from right panel"""
