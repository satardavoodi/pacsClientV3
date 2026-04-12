"""Priority download: thumbnail-click priority, single series immediate download"""
# Auto-generated from home_ui.py — Phase 3 split



import asyncio
import traceback

from PySide6.QtCore import Qt, Signal, QTimer, QPropertyAnimation, QEasingCurve, QSize

from PacsClient.components import DicomGrpcClient
from PacsClient.utils import get_connection_database, get_all_patients, search_patients_local, find_patient_pk, find_study_pk, insert_patient, insert_study, insert_series, find_series_pk, find_study_pk_with_study_uid, CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from modules.network import dicom_service_pb2, dicom_service_pb2_grpc
from pathlib import Path

from .widget import PRIORITY_MANAGER_AVAILABLE


class _HPPriorityMixin:
    """Priority download: thumbnail-click priority, single series immediate download"""

    def _handle_priority_download_from_thumbnail(self, series_number, study_uid, widget=None):
        """
        Handle priority download request from thumbnail click - UNIFIED with Download Manager
        
        This method now properly coordinates with the Download Manager to avoid parallel downloads.
        When the study is already being downloaded by the Download Manager, it just updates priority.
        
        Args:
            series_number (str): Series number that was clicked
            study_uid (str): Study Instance UID
            widget (PatientWidget, optional): Patient widget. Will be found if not provided.
        """
        print(f"🔥 [PRIORITY] Thumbnail clicked: series={series_number}, study={study_uid}")
        
        try:
            from pathlib import Path
            from PacsClient.utils.config import SOURCE_PATH
            
            # Check if series is already downloaded locally
            output_dir = SOURCE_PATH / study_uid
            series_dir = output_dir / str(series_number)
            if series_dir.exists() and any(series_dir.glob("*.dcm")):
                print(f"✅ Series {series_number} already downloaded - loading immediately")
                # Find widget if not provided
                if widget is None:
                    widget = self._find_widget_by_study_uid(study_uid)
                if widget and hasattr(widget, 'load_series_immediately'):
                    # ✅ FIX: Skip load_series_immediately if the viewer is
                    # already displaying this series (avoids redundant disk
                    # reload + re-render after the direct change_series call
                    # that already happened from the thumbnail click).
                    vc = getattr(widget, 'viewer_controller', None)
                    already_shown = False
                    if vc is not None:
                        already_shown = (str(getattr(vc, '_last_switch_series', None)) == str(series_number))
                    if not already_shown:
                        QTimer.singleShot(100, lambda sn=series_number, od=str(series_dir):
                            widget.load_series_immediately(sn, od))
                    else:
                        print(f"⏭️ Series {series_number} already switched by direct click – skipping reload")
                        # Still ensure thumbnail border is updated
                        if hasattr(widget, 'thumbnail_manager') and widget.thumbnail_manager:
                            widget.thumbnail_manager.set_series_ready(str(series_number))
                            widget.thumbnail_manager.apply_border_states_new()
                return
            
            # ========== CRITICAL: Check if Download Manager is already handling this study ==========
            download_manager = self._get_or_create_download_manager_tab(activate_tab=False)
            study_being_downloaded = False

            if download_manager:
                # Check via state_store (the single source of truth for download state)
                if hasattr(download_manager, 'state_store'):
                    state = download_manager.state_store.get(study_uid)
                    if state and state.status.value in ("Downloading", "Pending", "Paused", "Validating"):
                        study_being_downloaded = True
                        print(f"📥 Study {study_uid[:50]} is already in Download Manager (status: {state.status.value})")
                elif hasattr(download_manager, 'study_downloads'):
                    for study_download in download_manager.study_downloads:
                        if study_download.study_uid == study_uid:
                            if study_download.status in ["Downloading", "Pending", "Paused"]:
                                study_being_downloaded = True
                                print(f"📥 Study {study_uid} is already in Download Manager (status: {study_download.status})")
                                break
                else:
                    print(f"⚠️ DownloadManagerWidget doesn't have 'state_store' or 'study_downloads', proceeding with new download")
            
            if study_being_downloaded:
                # Study is being handled by Download Manager — escalate this
                # series to CRITICAL so it downloads before the other series.
                print(f"🎯 Updating priority: series {series_number} to CRITICAL")
                
                # Use the Download Manager's set_viewed_series API to mark
                # this series as the one being actively viewed.  This updates
                # the state store and reorders series download priority.
                try:
                    if hasattr(download_manager, 'set_viewed_series'):
                        download_manager.set_viewed_series(study_uid, str(series_number))
                        print(f"✅ Download Manager notified: series {series_number} is now CRITICAL")
                    else:
                        print(f"⚠️ Download Manager does not have set_viewed_series method")
                except Exception as e:
                    print(f"⚠️ Error notifying download manager of viewed series: {e}")
                
                # Update UI to show this series is being prioritized
                if widget is None:
                    widget = self._find_widget_by_study_uid(study_uid)
                if widget and hasattr(widget, 'thumbnail_manager'):
                    widget.thumbnail_manager.start_series_download(str(series_number))
                    widget.thumbnail_manager.update_series_progress(
                        series_number=str(series_number),
                        progress_percent=0.0,
                        status_text="Prioritized..."
                    )
                
                # Don't start a parallel download - let Download Manager continue
                print(f"✅ Letting Download Manager handle the prioritized download")
                return
            
            # ========== Study is NOT in Download Manager - handle directly ==========
            print(f"📋 Study not in Download Manager - starting new prioritized download")
            
            # Find widget if not provided
            if widget is None:
                widget = self._find_widget_by_study_uid(study_uid)
                if widget is None:
                    print(f"⚠️ Widget not found for study {study_uid}")
                    # Try to create a new tab
                    try:
                        patient_info = {}
                        if hasattr(self, 'right_panel_widget') and hasattr(self.right_panel_widget, '_current_study_info'):
                            patient_info = self.right_panel_widget._current_study_info
                        else:
                            from PacsClient.utils.db_manager import get_patient_by_study_uid
                            patient_info = get_patient_by_study_uid(study_uid) or {}
                        
                        patient_id = patient_info.get('patient_id', 'N/A')
                        patient_name = patient_info.get('patient_name', 'N/A')
                        
                        widget = self.add_new_tab_widget(
                            patient_id=patient_id,
                            patient_name=patient_name,
                            folder_path=None,
                            caller=CallerTypes.SERVER,
                            study_uid=study_uid,
                            enable_progressive_mode=True
                        )
                        print(f"✅ New tab created for study {study_uid}")
                    except Exception as e:
                        print(f"❌ Failed to create new tab: {e}")
                        return
            
            if widget is None:
                print(f"❌ No widget available for priority download")
                return
            
            # Get series list
            series_list = self._get_series_list_for_study(widget, study_uid)
            study_info = None  # Initialize to None
            
            if not series_list:
                study_info = self.get_series_info_from_server(study_uid)
                if study_info:
                    series_list = study_info.get('series', [])
                if not series_list:
                    print(f"❌ Failed to fetch series list")
                    return
            
            # Get server connection
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                print(f"❌ No server selected")
                return
            
            # Create output directory
            output_dir.mkdir(parents=True, exist_ok=True)
            output_dir_str = str(output_dir)
            
            # ========== IMMEDIATE START via Download Manager ==========
            # This ensures all downloads go through the unified path with immediate response
            if download_manager:
                print(f"⚡ IMMEDIATE START: Adding study with CRITICAL priority")
                
                # === PROPERLY EXTRACT PATIENT INFO FROM MULTIPLE SOURCES ===
                # Priority: 1. widget attributes, 2. study_info from server, 3. database lookup
                dm_patient_id = ''
                dm_patient_name = ''
                dm_study_date = ''
                dm_study_time = ''
                dm_modality = ''
                dm_description = ''
                dm_patient_age = ''
                dm_patient_sex = ''
                dm_patient_birth_date = ''
                dm_body_part = ''
                
                # 1. Try widget attributes first
                if hasattr(widget, 'patient_id') and widget.patient_id:
                    dm_patient_id = widget.patient_id
                if hasattr(widget, 'patient_name') and widget.patient_name:
                    dm_patient_name = widget.patient_name
                
                # 2. If still missing, try study_info from server (already fetched above)
                if (not dm_patient_id or not dm_patient_name) and study_info:
                    dm_patient_id = dm_patient_id or study_info.get('patient_id', '')
                    dm_patient_name = dm_patient_name or study_info.get('patient_name', '')
                    dm_study_date = study_info.get('study_date', '')
                    dm_study_time = study_info.get('study_time', '')
                    dm_modality = study_info.get('modality', '')
                    dm_description = study_info.get('study_description', '')
                    dm_patient_age = study_info.get('age', '')
                    dm_patient_sex = study_info.get('sex', '')
                    dm_patient_birth_date = study_info.get('birth_date', '')
                    dm_body_part = study_info.get('body_part', '')
                
                # 2.5. If study_info wasn't fetched yet (series_list came from widget cache), fetch it now
                if (not dm_patient_id or not dm_patient_name) and not study_info:
                    study_info = self.get_series_info_from_server(study_uid)
                    if study_info:
                        dm_patient_id = dm_patient_id or study_info.get('patient_id', '')
                        dm_patient_name = dm_patient_name or study_info.get('patient_name', '')
                        dm_study_date = study_info.get('study_date', '')
                        dm_study_time = study_info.get('study_time', '')
                        dm_modality = study_info.get('modality', '')
                        dm_description = study_info.get('study_description', '')
                        dm_patient_age = study_info.get('age', '')
                        dm_patient_sex = study_info.get('sex', '')
                        dm_patient_birth_date = study_info.get('birth_date', '')
                        dm_body_part = study_info.get('body_part', '')
                
                # 3. If still missing, try database lookup
                if not dm_patient_id or not dm_patient_name:
                    try:
                        from PacsClient.utils.db_manager import get_patient_by_study_uid
                        db_info = get_patient_by_study_uid(study_uid)
                        if db_info:
                            dm_patient_id = dm_patient_id or db_info.get('patient_id', '')
                            dm_patient_name = dm_patient_name or db_info.get('patient_name', '')
                            dm_study_date = dm_study_date or db_info.get('study_date', '')
                            dm_study_time = dm_study_time or db_info.get('study_time', '')
                            dm_modality = dm_modality or db_info.get('modality', '')
                            dm_description = dm_description or db_info.get('study_description', '')
                            dm_patient_age = dm_patient_age or db_info.get('age', '')
                            dm_patient_sex = dm_patient_sex or db_info.get('sex', '')
                            dm_patient_birth_date = dm_patient_birth_date or db_info.get('birth_date', '')
                            dm_body_part = dm_body_part or db_info.get('body_part', '')
                    except Exception as e:
                        print(f"⚠️ Database lookup failed: {e}")
                
                # 4. Final validation - reject if still missing critical info
                if not dm_patient_id or not dm_patient_name:
                    print(f"❌ Cannot start download: Missing patient info (id={dm_patient_id}, name={dm_patient_name})")
                    return
                
                dm_study_data = {
                    'patient_id': dm_patient_id,
                    'patient_name': dm_patient_name,
                    'study_uid': study_uid,
                    'study_date': dm_study_date,
                    'modality': dm_modality,
                    'description': dm_description,
                    'series_count': len(series_list),
                    'images_count': sum(s.get('image_count', 0) for s in series_list),
                    # Complete patient information
                    'patient_age': dm_patient_age,
                    'patient_sex': dm_patient_sex,
                    'patient_birth_date': dm_patient_birth_date,
                    'study_time': dm_study_time,
                    'body_part': dm_body_part,
                    'series': series_list,  # Include series array
                }
                
                # ⚡ IMMEDIATE START - pauses all, starts this one right away
                download_manager.start_priority_download_immediately(
                    study_data=dm_study_data,
                    server_info=server,
                    priority="Critical"
                )
                
                # Notify priority manager about the clicked series
                if PRIORITY_MANAGER_AVAILABLE:
                    try:
                        priority_manager = get_download_priority_manager()
                        priority_manager.on_series_loaded_in_viewer(study_uid, str(series_number))
                    except Exception:
                        pass
                
                # Update thumbnail UI
                if hasattr(widget, 'thumbnail_manager'):
                    widget.thumbnail_manager.start_series_download(str(series_number))
                    widget.thumbnail_manager.update_series_progress(
                        series_number=str(series_number),
                        progress_percent=0.0,
                        status_text="Starting..."
                    )
                
                print(f"✅ Immediate priority download started for series {series_number}")
            else:
                # Fallback: direct download if Download Manager not available
                print(f"⚠️ Download Manager not available, using direct download")
                async def _priority_download_task():
                    try:
                        await self._download_single_series_with_priority(
                            widget=widget,
                            study_uid=study_uid,
                            series_list=series_list,
                            base_output_dir=output_dir_str,
                            server=server,
                            clicked_series=series_number
                        )
                    except Exception as e:
                        print(f"❌ Error in priority download: {e}")
                
                task = asyncio.create_task(_priority_download_task())
                self._background_tasks.add(task)
                task.add_done_callback(lambda t: self._background_tasks.discard(t))
            
        except Exception as e:
            print(f"❌ Error in priority download handler: {e}")
            import traceback
            traceback.print_exc()

    def _get_series_list_for_study(self, widget, study_uid):
        """Get series list from available sources with caching"""
        # بررسی کش اول
        cache_key = f"series_{study_uid}"
        cached_series = getattr(self, '_series_cache', {}).get(cache_key)
        if cached_series:
            print(f"✅ Using cached series list for study {study_uid}")
            return cached_series
        
        # اول از widget سری‌ها را از server_series_info می‌گیریم
        if hasattr(widget, 'server_series_info') and widget.server_series_info:
            print(f"📋 Found {len(widget.server_series_info)} series from widget.server_series_info")
            # کش کردن برای درخواست‌های بعدی
            if not hasattr(self, '_series_cache'):
                self._series_cache = {}
            self._series_cache[cache_key] = widget.server_series_info
            return widget.server_series_info
        
        # سپس از دیتابیس بررسی می‌کنیم
        print(f"🔍 Series list not found in widget, checking database...")
        try:
            from PacsClient.utils.db_manager import get_series_by_study_uid
            series_from_db = get_series_by_study_uid(study_uid)
            if series_from_db:
                print(f"📋 Found {len(series_from_db)} series from database")
                # تبدیل به فرمت استاندارد
                formatted_series = []
                for series in series_from_db:
                    formatted_series.append({
                        'series_uid': series.get('series_uid', ''),
                        'series_number': series.get('series_number', ''),
                        'series_description': series.get('series_description', ''),
                        'modality': series.get('modality', ''),
                        'image_count': series.get('image_count', 0),
                        'protocol_name': series.get('protocol_name', ''),
                        'body_part_examined': series.get('body_part_examined', ''),
                        'manufacturer': series.get('manufacturer', ''),
                        'institution_name': series.get('institution_name', '')
                    })
                # کش کردن برای درخواست‌های بعدی
                if not hasattr(self, '_series_cache'):
                    self._series_cache = {}
                self._series_cache[cache_key] = formatted_series
                return formatted_series
        except Exception as e:
            print(f"⚠️ Error fetching series from database: {e}")
        
        # در نهایت، به سرور متصل می‌شویم
        print(f"🌐 Series list not found in database, connecting to server...")
        try:
            server = self.data_access_panel_widget.get_server_selected()
            if not server:
                print(f"❌ No server selected for fetching series")
                return None
                
            from modules.network.grpc_client import DicomGrpcClient
            grpc_client = DicomGrpcClient(host=server['host'], port=50051)
            
            # دریافت اطلاعات study با metadata
            request = dicom_service_pb2.StudyThumbnailsRequest(
                study_instance_uid=study_uid,
                include_image_data=False,
                include_base64=False
            )
            response = grpc_client.stub.GetStudyThumbnails(request)
            grpc_client.close()
            
            # استخراج و فرمت‌بندی سری‌ها
            series_list = []
            for series in response.series_thumbnails:
                series_info = {
                    'series_uid': series.series_uid,
                    'series_number': series.series_number,
                    'series_description': series.series_description,
                    'modality': series.modality,
                    'image_count': series.image_count,
                    'protocol_name': getattr(series, 'protocol_name', ''),
                    'body_part_examined': getattr(series, 'body_part_examined', ''),
                    'manufacturer': getattr(series, 'manufacturer', ''),
                    'institution_name': getattr(series, 'institution_name', '')
                }
                series_list.append(series_info)
                
            print(f"📋 Retrieved {len(series_list)} series from server directly")
            
            # کش کردن برای درخواست‌های بعدی
            if not hasattr(self, '_series_cache'):
                self._series_cache = {}
            self._series_cache[cache_key] = series_list
            return series_list
            
        except Exception as e:
            print(f"❌ Error connecting to server to fetch series: {e}")
            return None

    def _test_priority_download(self):
        """Test priority download mechanism manually"""
        print(f"\n{'='*80}")
        print(f"🧪 MANUAL TEST: Priority download")
        print(f"{'='*80}\n")
        
        # Find current patient widget
        current_widget = self.tab_widget.currentWidget()
        if not current_widget or not hasattr(current_widget, 'study_uid'):
            print("❌ No patient widget found")
            return
        
        study_uid = current_widget.study_uid
        print(f"📁 Current study: {study_uid}")
        
        # Simulate click on series 3
        self._handle_priority_download_from_thumbnail("3", study_uid, current_widget)

    def _find_widget_by_study_uid(self, study_uid):
        """Find widget by study UID (delegates to tab service)."""
        return self.tab_service.find_widget_by_study_uid(study_uid)

    def _cleanup_priority_task(self, series_number):
        """Clean up completed priority task"""
        try:
            if hasattr(self, '_priority_tasks') and series_number in self._priority_tasks:
                del self._priority_tasks[series_number]
                print(f"✅ Cleaned up priority task for series {series_number}")
        except Exception as e:
            print(f"⚠️ Error cleaning up priority task: {e}")

    async def _download_single_series_immediately(self, widget, series_number, series_list, output_dir, server, study_uid):
        """Download a single series immediately with highest priority"""
        try:
            print(f"\n{'='*80}")
            print(f"⚡ IMMEDIATE DOWNLOAD INITIATED")
            print(f"🎯 Series: {series_number}")
            print(f"📁 Study: {study_uid}")
            print(f"🌐 Server: {server['host']}:50052")
            print(f"{'='*80}\n")
            
            # Find the specific series
            target_series = None
            for series in series_list:
                if str(series.get('series_number')) == str(series_number):
                    target_series = series
                    break
            
            if not target_series:
                print(f"❌ Series {series_number} not found in series list")
                return
            
            series_uid = target_series.get('series_uid', '')
            expected_count = target_series.get('image_count', 0)
            
            # Create series directory
            from pathlib import Path
            series_dir = Path(output_dir) / str(series_number)
            series_dir.mkdir(parents=True, exist_ok=True)
            
            # Check if already downloaded
            if series_dir.exists():
                dicom_files = list(series_dir.glob("*.dcm"))
                if dicom_files and (expected_count == 0 or len(dicom_files) >= expected_count):
                    print(f"✅ Series {series_number} already downloaded")
                    # Load immediately if already exists
                    if hasattr(widget, 'load_series_immediately'):
                        widget.load_series_immediately(series_number, str(series_dir))
                    return
            
            # Use simple SeriesDownloader for fastest download
            from modules.download_manager.download.series_downloader import SeriesDownloader
            
            downloader = SeriesDownloader(host=server['host'], port=50052)
            if downloader.connect():
                print(f"✅ Connected to server, downloading series {series_number}...")
                
                # Show progress in UI
                if hasattr(widget, 'thumbnail_manager'):
                    widget.thumbnail_manager.start_series_download(str(series_number))
                
                # Download with progress callback
                def progress_callback(event_type, series_num, progress, current=0, total=0):
                    try:
                        if event_type == 'series_progress' and hasattr(widget, 'thumbnail_manager'):
                            status_text = f"{current}/{total}" if total > 0 else ""
                            widget.thumbnail_manager.update_series_progress(
                                str(series_num), 
                                progress,
                                status_text
                            )
                            if progress % 25 == 0:
                                print(f"📊 Progress: Series {series_num} - {progress}% ({current}/{total})")
                        elif event_type == 'series_complete':
                            if hasattr(widget, 'thumbnail_manager'):
                                widget.thumbnail_manager.complete_series_download(str(series_num))
                    except Exception as e:
                        print(f"⚠️ Progress callback error: {e}")
                
                success = await asyncio.to_thread(
                    downloader.download_series,
                    series_uid,
                    str(series_dir),
                    progress_callback
                )
                
                downloader.disconnect()
                
                if success:
                    print(f"✅ Series {series_number} downloaded successfully!")
                    # Load immediately
                    if hasattr(widget, 'load_series_immediately'):
                        widget.load_series_immediately(series_number, str(series_dir))
                    elif hasattr(widget, 'load_single_series'):
                        widget.load_single_series(series_number)
                else:
                    print(f"❌ Failed to download series {series_number}")
            else:
                print(f"❌ Failed to connect to downloader")
                
        except Exception as e:
            print(f"❌ Error in immediate download: {e}")
            import traceback
            traceback.print_exc()

    async def _load_series_immediate(self, widget, series_number, series_dir):
        """Load series immediately after download"""
        try:
            print(f"🔄 Loading series {series_number} immediately...")
            
            # Find series index in thumbnails
            series_index = -1
            if hasattr(widget, 'thumbnails'):
                for i, thumb in enumerate(widget.thumbnails):
                    if str(thumb.get('series_number')) == str(series_number):
                        series_index = i
                        break
            
            if series_index >= 0:
                print(f"✅ Found series at index {series_index}, loading...")
                
                # Use the widget's load method
                if hasattr(widget, 'load_series_on_demand'):
                    # Small delay to ensure UI is ready
                    await asyncio.sleep(0.1)
                    widget.load_series_on_demand(series_index)
                elif hasattr(widget, 'change_series'):
                    widget.change_series(series_index)
                else:
                    print(f"⚠️ No load method found on widget")
                    
                print(f"✅ Series {series_number} loaded successfully!")
            else:
                print(f"⚠️ Series {series_number} not found in thumbnails list")
                
        except Exception as e:
            print(f"❌ Error loading series immediately: {e}")
            import traceback
            traceback.print_exc()

    def _cancel_background_downloads_for_series(self, study_uid, series_number):
        """Cancel any background downloads for the specified series"""
        try:
            print(f"🛑 Cancelling background downloads for series {series_number}...")
            
            # Cancel download tasks
            if hasattr(self, '_download_tasks'):
                cancelled = 0
                for task in list(self._download_tasks):
                    if task and not task.done():
                        try:
                            task.cancel()
                            cancelled += 1
                        except:
                            pass
                print(f"   Cancelled {cancelled} background download tasks")
                
            # Cancel any Zeta downloads for this series
            try:
                from modules.network.zeta_adapter import cancel_zeta_download
                cancel_zeta_download(study_uid)
                print(f"   Cancelled Zeta download")
            except:
                pass
                
        except Exception as e:
            print(f"⚠️ Error cancelling background downloads: {e}")

    async def _download_with_fast_downloader(self, *args, **kwargs):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        Uses missing SeriesDownloader module and bypasses Zeta state.
        All downloads must route through Zeta Download Manager.
        
        Raises NotImplementedError.
        """
        raise NotImplementedError(
            "Legacy _download_with_fast_downloader has been removed (used missing SeriesDownloader). "
            "Please use Zeta Download Manager instead."
        )

    async def _download_with_robust_downloader_fallback(self, *args, **kwargs):
        """
        DEPRECATED: This function has been removed as part of Phase 1 refactoring.
        Uses missing RobustSeriesDownloader module and bypasses Zeta state.
        All downloads must route through Zeta Download Manager.
        
        Raises NotImplementedError.
        """
        raise NotImplementedError(
            "Legacy _download_with_robust_downloader_fallback has been removed (used missing RobustSeriesDownloader). "
            "Please use Zeta Download Manager instead."
        )

    async def _download_single_series_with_priority(self, widget, study_uid, series_list, base_output_dir, server, clicked_series):
        """
        DEPRECATED: Legacy priority download for single series.
        Use Zeta Download Manager with priority system instead.
        """
        print(f"⚠️ DEPRECATED: _download_single_series_with_priority called for series {clicked_series}")
        print("💡 Use Zeta Download Manager for priority-based downloads")
        
        # Check if already downloaded
        try:
            from pathlib import Path
            series_dir = Path(base_output_dir) / str(clicked_series)
            if series_dir.exists():
                dicom_files = list(series_dir.glob("*.dcm"))
                if dicom_files:
                    print(f"✅ Series {clicked_series} already downloaded")
                    if hasattr(widget, 'load_series_immediately'):
                        QTimer.singleShot(100, lambda sn=clicked_series, od=str(series_dir):
                            widget.load_series_immediately(sn, od))
                    return
        except Exception as e:
            print(f"⚠️ Error checking series status: {e}")

    def _load_and_display_series_immediately(self, widget, series_number, series_dir):
        """
        Load and display a series immediately after priority download completes.
        """
        try:
            print(f"🔄 [IMMEDIATE DISPLAY] Loading series {series_number} from {series_dir}")
            
            # بررسی وجود فایل‌های DICOM
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            
            if not dicom_files:
                print(f"❌ No DICOM files found in {series_dir}")
                return
            
            # ارسال سیگنال به PatientWidget برای نمایش فوری
            if hasattr(widget, 'load_series_immediately'):
                # این متد باید سری را در ویوور نمایش دهد بدون دانلود مجدد
                widget.load_series_immediately(series_number, series_dir)
            else:
                print(f"⚠️ Widget doesn't have load_series_immediately method")
                
        except Exception as e:
            print(f"❌ Error in immediate display: {e}")
            import traceback
            traceback.print_exc()
