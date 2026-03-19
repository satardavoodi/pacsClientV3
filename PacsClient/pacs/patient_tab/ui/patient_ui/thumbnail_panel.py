"""
Thumbnail Panel Component
کامپوننت جداگانه برای مدیریت تامب‌نیل‌ها
"""

import os
import time
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
    QLabel, QScrollArea, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage

from PacsClient.pacs.patient_tab.utils import ThumbnailManager, create_attachment_folder, open_folder, \
    check_and_get_thumbnails, get_name_file_from_path
from modules.storage.thumbnail_store import ThumbnailStore, make_pixmap_from_bytes  # type: ignore
from PacsClient.utils.theme_manager import get_theme_manager


class ThumbnailPanel(QWidget):
    """
    کامپوننت جداگانه برای مدیریت تامب‌نیل‌ها
    """
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_widget = parent
        
        # Initialize thumbnail data
        self.lst_thumbnails_data = []
        self._series_index = {}  # map: series_key -> index in lst_thumbnails_data
        self.unique_elements_index = 0
        
        # Thumbnail management
        self.first_thumbnail_path = None
        self.thumbnail_manager = None
        self.thumb_grid = None
        self.thumb_count_label = None
        
        # Timer management
        self.thumbnail_timer = None
        self.cached_thumbnail_timer = None
        self.current_thumbnail_index = 0
        self.thumbnails_to_display = []
        
        # Theme support
        self.theme_manager = get_theme_manager()
        self._active_theme = self.theme_manager.current_theme()
        self.theme_manager.themeChanged.connect(self._on_theme_changed)
        
        # Initialize UI
        self.setup_ui()
        
    def setup_ui(self):
        """Setup the thumbnail panel UI"""
        self.setFixedWidth(216)  # Calculated for 180px thumbnails + margins + scrollbar
        
        # Main layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)
        
        # Enhanced header
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        
        # Title
        title_label = QLabel("Series Thumbnails")
        title_label.setStyleSheet(self._get_header_title_stylesheet())
        
        # Count indicator
        self.thumb_count_label = QLabel("0 series")
        self.thumb_count_label.setStyleSheet(self._get_header_count_stylesheet())
        
        header_layout.addWidget(title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.thumb_count_label)
        main_layout.addWidget(header_widget)

        # Scroll area
        thumb_scroll = QScrollArea()
        thumb_scroll.setWidgetResizable(True)
        thumb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        thumb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        
        thumb_scroll.setStyleSheet(self._get_scrollarea_stylesheet())

        # Content container
        thumb_container = QWidget()
        thumb_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
            }
        """)

        self.thumb_grid = QGridLayout(thumb_container)
        self.thumb_grid.setContentsMargins(8, 6, 14, 6)  # Left-aligned with proper spacing
        self.thumb_grid.setHorizontalSpacing(6)  # Reduced spacing for better fit
        self.thumb_grid.setVerticalSpacing(6)   # Reduced spacing for better fit
        self.thumb_grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)  # Align thumbnails to the left
        thumb_scroll.setWidget(thumb_container)
        main_layout.addWidget(thumb_scroll)
        
        # Initialize thumbnail manager
        self.thumbnail_manager = ThumbnailManager(self.change_series_on_viewer)
        
        # Set panel styling
        theme = self._active_theme
        self.setStyleSheet(f"""
            QWidget {{
                background: {theme.get('panel_bg', '#0f1419')};
                border: none;
                border-radius: 8px;
                margin: 0px;
                padding: 0px;
            }}
        """)
    
    def set_parent_widget(self, parent_widget):
        """Set the parent widget for callbacks"""
        self.parent_widget = parent_widget
        if self.thumbnail_manager:
            self.thumbnail_manager = ThumbnailManager(self.change_series_on_viewer)
    
    def change_series_on_viewer(self, series_index):
        """Callback for when a thumbnail is clicked"""
        if self.parent_widget and hasattr(self.parent_widget, 'change_series_on_viewer'):
            try:
                # Mark explicit user-intent click/double-click for controller policy decisions.
                action_id = f"thumb_click-{series_index}-{int(time.time() * 1000)}"
                self.parent_widget._pending_action_id = action_id
                self.parent_widget._pending_action_series = str(series_index)
            except Exception:
                pass
            self.parent_widget.change_series_on_viewer(series_index)
    
    def load_thumbnails_sync(self):
        """Load thumbnails synchronously when no event loop is available"""
        try:
            if not self.parent_widget:
                return
                
            print("🖼️ Loading thumbnails synchronously...")
            
            # Only clear if we don't already have thumbnails
            if not hasattr(self, 'lst_thumbnails_data') or not self.lst_thumbnails_data:
                self.lst_thumbnails_data = []
                self.clear_thumbnails()
            else:
                print("✅ Thumbnails already loaded, skipping clear")
                return
            
            # Get import folder path from parent
            import_folder_path = getattr(self.parent_widget, 'import_folder_path', None)
            if not import_folder_path:
                print("❌ No import folder path available")
                return
            
            # Load thumbnails from folder
            thumbnails = check_and_get_thumbnails(import_folder_path)
            if thumbnails:
                for thumbnail_file in thumbnails:
                    try:
                        # Create basic series info
                        series_name = get_name_file_from_path(thumbnail_file)
                        series_info = {
                            'series_number': series_name,
                            'modality': 'Unknown',
                            'series_description': f'Series {series_name}',
                            'image_count': 0,
                            'protocol_name': '',
                            'body_part_examined': ''
                        }
                        
                        self.lst_thumbnails_data.append(series_info)
                        
                        # Add to layout
                        self.add_thumbnail_to_thumbnail_layout(
                            thumb_index=len(self.lst_thumbnails_data) - 1,
                            file_path_thumbnail=thumbnail_file
                        )
                        
                    except Exception as e:
                        print(f"❌ Error loading thumbnail {thumbnail_file}: {e}")
                        continue
            
            print(f"✅ Loaded {len(self.lst_thumbnails_data)} thumbnails synchronously")
            
        except Exception as e:
            print(f"❌ Error loading thumbnails synchronously: {e}")
    
    def add_thumbnail_to_thumbnail_layout(self, thumb_index, file_path_thumbnail, metadata=None):
        """Add thumbnail to layout with series info"""
        if metadata:  # it means that we loaded vtk_image_data, metadata
            # add new thumbnails
            print('metadata series:', metadata['series'])
            if not metadata['series']['main_thumbnail']:
                print('Finish at first')
                return thumb_index  # we don't add new thumbnail

            series_name = str(metadata['series']['series_number'])
            print('series_name 1:', series_name)

        else:
            series_name = get_name_file_from_path(file_path_thumbnail)
            print('series_name 2:', series_name)


        if series_name in self.thumbnail_manager.lst_buttons_name:
            print('Finish at second if')
            return thumb_index  # we don't add new thumbnail

        print('file_path_thumbnail:', file_path_thumbnail)
        # ── ThumbnailStore fast path: probe in-memory cache before disk read ──
        # The download executor populates the store when thumbnails arrive from
        # the server.  A cache hit here means zero disk I/O on the main thread.
        pixmap = None
        try:
            study_uid = str(getattr(self.parent_widget, 'study_uid', '') or '')
            if study_uid:
                thumb_bytes = ThumbnailStore.instance().get_bytes(study_uid, series_name)
                if thumb_bytes:
                    pixmap = make_pixmap_from_bytes(thumb_bytes)
        except Exception:
            pixmap = None
        if pixmap is None or (hasattr(pixmap, 'isNull') and pixmap.isNull()):
            # Fallback: synchronous disk read (original behaviour).
            pixmap = QPixmap(file_path_thumbnail)
        
        # Extract series info from metadata or database
        series_info = None
        if metadata:
            series_info = {
                'series': {
                    'series_number': metadata['series'].get('series_number', series_name),
                    'modality': metadata['series'].get('modality', 'Unknown'),
                    'series_description': metadata['series'].get('series_description', ''),
                    'protocol_name': metadata['series'].get('protocol_name', ''),
                    'body_part_examined': metadata['series'].get('body_part_examined', '')
                },
                'series_number': metadata['series'].get('series_number', series_name),
                'image_count': len(metadata.get('instances', [])),
            }
        else:
            # For cached thumbnails, try to get series info from database
            print(f"🔍 DEBUG: Processing cached thumbnail for series {series_name}")
            try:
                cached_info = self.get_cached_series_metadata(series_name)
                print(f"🔍 DEBUG: Got cached_info from database: {cached_info}")
                if cached_info:  # If database lookup succeeds
                    series_info = {
                        'series': {
                            'series_number': cached_info.get('series_number', series_name),
                            'modality': cached_info.get('modality', 'Unknown'),
                            'series_description': cached_info.get('series_description', ''),
                            'protocol_name': cached_info.get('protocol_name', ''),
                            'body_part_examined': cached_info.get('body_part_examined', '')
                        },
                        'series_number': cached_info.get('series_number', series_name),
                        'image_count': cached_info.get('image_count', 0),
                    }
                else:
                    print(f"🔍 DEBUG: Database lookup failed, creating fallback info")
                    series_info = {
                        'series': {
                            'series_number': series_name,
                            'modality': 'Unknown',
                            'series_description': f'Series {series_name}',
                            'protocol_name': '',
                            'body_part_examined': ''
                        },
                        'series_number': series_name,
                        'image_count': 0,
                    }
            except Exception as e:
                print(f"Error getting cached series info: {str(e)}")
                # Fallback to basic info
                series_info = {
                    'series': {
                        'series_number': series_name,
                        'modality': 'Unknown', 
                        'series_description': f'Series {series_name}',
                        'protocol_name': '',
                        'body_part_examined': ''
                    },
                    'series_number': series_name,
                    'image_count': 0,
                }

        print('After if')
        # Determine if this is a new download (show progress) or existing (no progress)
        show_progress = metadata is not None and metadata.get('is_downloading', False)
        
        thumb_widget = self.thumbnail_manager.create_thumbnail_widget(
            pixmap=pixmap, 
            label_text=series_name, 
            sop_instance_uid='test uid', 
            thumbnail_index=thumb_index,
            series_info=series_info,
            show_progress=show_progress
        )

        print('thumb_widget:', thumb_widget)

        # Add to grid in single column layout
        self.thumb_grid.addWidget(thumb_widget, thumb_index, 0, 1, 1)
        
        # Update count label
        if hasattr(self, 'thumb_count_label'):
            self.thumb_count_label.setText(f"{thumb_index + 1} series")
        
        # Set first thumbnail for tab if this is the first one
        if thumb_index == 0 and not self.first_thumbnail_path:
            self.first_thumbnail_path = file_path_thumbnail
            print(f"🔍 DEBUG: Setting first_thumbnail_path = {file_path_thumbnail}")
            self.on_thumbnail_added(file_path_thumbnail)
        
        return thumb_index + 1
    
    def on_thumbnail_added(self, thumbnail_path):
        """Called when a new thumbnail is added"""
        print(f"🔍 DEBUG: on_thumbnail_added called with path: {thumbnail_path}")
        print(f"🔍 DEBUG: Current first_thumbnail_path: {self.first_thumbnail_path}")
        
        # Notify parent widget if available
        if self.parent_widget and hasattr(self.parent_widget, 'on_thumbnail_added'):
            self.parent_widget.on_thumbnail_added(thumbnail_path)
    
    def display_thumbnails_immediately(self, thumbnails_data):
        """
        Display thumbnails immediately from server response - one by one with loading
        اولین اولویت: نمایش فوری تامب‌نیل‌ها تک تک با loading
        OPTIMIZED: Faster initialization
        """
        try:
            # Clear existing thumbnails
            self.clear_thumbnails()
            
            # Show loading state (if available)
            if hasattr(self, 'show_thumbnail_loading'):
                self.show_thumbnail_loading(len(thumbnails_data))
            
            # Start progressive display immediately (no delay)
            self.display_thumbnails_progressively(thumbnails_data)
            
        except Exception as e:
            print(f"Error in display_thumbnails_immediately: {str(e)}")
    
    def display_thumbnails_progressively(self, thumbnails_data):
        """Display thumbnails one by one with a small delay for better UX"""
        try:
            # توقف timer قبلی اگر وجود دارد
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
            
            self.current_thumbnail_index = 0
            self.thumbnails_to_display = thumbnails_data
            
            # Update thumbnail count if available
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"Loading 0/{len(thumbnails_data)} series...")
            
            # Create a timer to display thumbnails progressively
            self.thumbnail_timer = QTimer()
            self.thumbnail_timer.timeout.connect(self.display_next_thumbnail_patient)
            self.thumbnail_timer.start(20)  # 20ms delay - much faster loading
            
        except Exception as e:
            print(f"Error in display_thumbnails_progressively: {str(e)}")
    
    def display_next_thumbnail_patient(self):
        """Display the next thumbnail(s) in the patient tab queue - OPTIMIZED: batch rendering"""
        try:
            # بررسی وجود timer و داده‌ها
            if not hasattr(self, 'thumbnail_timer') or not self.thumbnail_timer:
                return
                
            if not hasattr(self, 'thumbnails_to_display') or not self.thumbnails_to_display:
                return
            
            if self.current_thumbnail_index >= len(self.thumbnails_to_display):
                # All thumbnails displayed, stop the timer
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None
                
                # Update final count
                if hasattr(self, 'thumb_count_label'):
                    self.thumb_count_label.setText(f"{len(self.thumbnails_to_display)} series")
                return
            
            # OPTIMIZED: Process 3 thumbnails per tick for faster loading
            batch_size = 3
            start_idx = self.current_thumbnail_index
            end_idx = min(start_idx + batch_size, len(self.thumbnails_to_display))
            
            for idx in range(start_idx, end_idx):
                thumb_data = self.thumbnails_to_display[idx]
                
                try:
                    file_path = thumb_data.get('file_path')
                    if file_path and os.path.exists(file_path):
                        # بررسی اینکه آیا این تامب‌نیل قبلاً اضافه شده یا نه
                        if not self.is_thumbnail_already_added(file_path):
                            # Create standardized metadata for immediate display
                            from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
                            metadata = ThumbnailManager.create_standard_metadata(
                                series_number=thumb_data.get('series_number', f'Series {idx + 1}'),
                                modality=thumb_data.get('modality', 'Unknown'),
                                series_description=thumb_data.get('series_description', ''),
                                image_count=thumb_data.get('image_count', 1),
                                protocol_name=thumb_data.get('protocol_name', ''),
                                body_part_examined=thumb_data.get('body_part_examined', ''),
                                is_downloading=False  # Mark as completed download
                            )
                            
                            # Add thumbnail to layout
                            thumb_index = self.add_thumbnail_to_thumbnail_layout(
                                thumb_index=idx,
                                file_path_thumbnail=file_path,
                                metadata=metadata
                            )
                            
                            print(f"✅ Added thumbnail {idx + 1}/{len(self.thumbnails_to_display)}")
                        
                except Exception as e:
                    print(f"Error processing thumbnail {idx}: {str(e)}")
            
            self.current_thumbnail_index = end_idx
            
            # Update progress count
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"{self.current_thumbnail_index}/{len(self.thumbnails_to_display)} series")
            
        except Exception as e:
            print(f"Error in display_next_thumbnail_patient: {str(e)}")
            # Stop timer on error
            if hasattr(self, 'thumbnail_timer'):
                self.thumbnail_timer.stop()
    
    def is_thumbnail_already_added(self, file_path):
        """
        بررسی اینکه آیا تامب‌نیل قبلاً اضافه شده یا نه
        """
        try:
            if not hasattr(self, 'thumbnail_manager') or not self.thumbnail_manager:
                return False
            
            # بررسی در لیست دکمه‌های موجود
            for btn in self.thumbnail_manager.buttons:
                if hasattr(btn, 'file_path') and btn.file_path == file_path:
                    return True
                # بررسی در parent widget
                parent = btn.parentWidget()
                if parent and hasattr(parent, 'file_path') and parent.file_path == file_path:
                    return True
            
            return False
            
        except Exception as e:
            print(f"❌ Error checking thumbnail existence: {e}")
            return False
    
    def clear_thumbnails(self):
        """Clear existing thumbnails from the layout - OPTIMIZED for speed"""
        try:
            # توقف timerها
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None
            
            if hasattr(self, 'cached_thumbnail_timer') and self.cached_thumbnail_timer:
                self.cached_thumbnail_timer.stop()
                self.cached_thumbnail_timer.deleteLater()
                self.cached_thumbnail_timer = None
            
            # پاک کردن grid layout - OPTIMIZED: direct deletion
            if hasattr(self, 'thumb_grid') and self.thumb_grid:
                # Clear grid layout directly without QTimer delays
                for i in reversed(range(self.thumb_grid.count())):
                    child = self.thumb_grid.itemAt(i)
                    if child and child.widget():
                        widget = child.widget()
                        widget.setParent(None)
                        widget.deleteLater()
                
                # Clear thumbnail manager safely
                if hasattr(self, 'thumbnail_manager'):
                    # پاک کردن دکمه‌ها - direct deletion
                    for btn in self.thumbnail_manager.buttons[:]:
                        if btn.parent():
                            btn.setParent(None)
                            btn.deleteLater()
                    self.thumbnail_manager.buttons.clear()
                    self.thumbnail_manager.lst_buttons_name.clear()
                
                print("✅ Thumbnails cleared successfully")
                
        except Exception as e:
            print(f"⚠️ Error clearing thumbnails: {e}")
    
    def _safe_delete_widget(self, widget):
        """DEPRECATED: No longer needed - use direct deletion"""
        pass
    
    def get_cached_series_metadata(self, series_name):
        """Get cached series metadata from database"""
        try:
            if not self.parent_widget:
                return None
                
            # Try to get from parent widget's database
            if hasattr(self.parent_widget, 'get_cached_series_metadata'):
                return self.parent_widget.get_cached_series_metadata(series_name)
            
            return None
            
        except Exception as e:
            print(f"Error getting cached series metadata: {e}")
            return None
    
    def cleanup_timers(self):
        """
        پاکسازی همه timerها
        """
        try:
            # توقف و پاک کردن thumbnail timer
            if hasattr(self, 'thumbnail_timer') and self.thumbnail_timer:
                self.thumbnail_timer.stop()
                self.thumbnail_timer.deleteLater()
                self.thumbnail_timer = None
            
            # توقف و پاک کردن cached thumbnail timer
            if hasattr(self, 'cached_thumbnail_timer') and self.cached_thumbnail_timer:
                self.cached_thumbnail_timer.stop()
                self.cached_thumbnail_timer.deleteLater()
                self.cached_thumbnail_timer = None
            
            print("✅ All timers cleaned up")
            
        except Exception as e:
            print(f"❌ Error cleaning up timers: {e}")
    
    def load_thumbnails_from_cache(self, thumbnail_dir):
        """
        Load thumbnails from cached directory
        بارگذاری تامب‌نیل‌ها از کش
        """
        try:
            from pathlib import Path
            cache_path = Path(thumbnail_dir)
            
            if not cache_path.exists():
                print(f"Cache directory does not exist: {thumbnail_dir}")
                return
            
            # Find all image files in cache
            image_files = []
            for ext in ['.png']:
                image_files.extend(cache_path.glob(f'*{ext}'))
            
            if not image_files:
                print(f"No thumbnail images found in cache: {thumbnail_dir}")
                return
            
            # Clear existing thumbnails
            self.clear_thumbnails()
            
            # Sort files by name for consistent ordering
            image_files.sort(key=lambda x: x.name)
            
            # OPTIMIZED: Batch fetch all metadata at once
            series_names = [img.stem for img in image_files]
            all_metadata = self.get_batch_cached_series_metadata(series_names)
            
            # Prepare cached thumbnails data for progressive display with database metadata
            cached_thumbnails_data = []
            for image_file in image_files:
                # Extract series info from filename if possible
                series_name = image_file.stem
                
                # Get metadata from batch result
                series_metadata = all_metadata.get(series_name, {})
                
                cached_thumbnails_data.append({
                    'file_path': str(image_file),
                    'series_number': series_metadata.get('series_number', series_name),
                    'modality': series_metadata.get('modality', 'Unknown'),
                    'series_description': series_metadata.get('series_description', f'Series {series_name}'),
                    'image_count': series_metadata.get('image_count', 0),
                    'protocol_name': series_metadata.get('protocol_name', ''),
                    'body_part_examined': series_metadata.get('body_part_examined', ''),
                    'is_cached': True
                })
            
            # Display cached thumbnails progressively
            self.display_cached_thumbnails_progressively(cached_thumbnails_data)
            
        except Exception as e:
            print(f"Error in load_thumbnails_from_cache: {str(e)}")
    
    def get_cached_series_metadata(self, series_number):
        """Get series metadata from database for cached thumbnails"""
        try:
            if not self.parent_widget:
                return {}
                
            # Get study_uid from parent widget or extract from import_folder_path
            study_uid = None
            
            # First try to get from parent widget's study_uid
            if hasattr(self.parent_widget, 'study_uid') and self.parent_widget.study_uid:
                study_uid = self.parent_widget.study_uid
                print(f"🔍 DEBUG: Using parent study_uid = {study_uid}")
            # If not available, extract from import_folder_path
            elif hasattr(self.parent_widget, 'import_folder_path') and self.parent_widget.import_folder_path:
                from pathlib import Path
                study_uid = Path(self.parent_widget.import_folder_path).name
                print(f"🔍 DEBUG: Extracted study_uid from path = {study_uid}")
            
            if not study_uid:
                print(f"🔍 DEBUG: No study_uid available, returning empty dict")
                return {}
            
            # Import database functions
            from PacsClient.utils.db_manager import get_series_by_study_and_number
            
            # Get series metadata from database
            print(f"🔍 DEBUG: Querying database for study_uid={study_uid}, series_number={series_number}")
            series_data = get_series_by_study_and_number(study_uid, series_number)
            print(f"🔍 DEBUG: Database returned: {series_data}")
            
            if series_data:
                return {
                    'series_number': series_data.get('series_number', series_number),
                    'modality': series_data.get('modality', 'Unknown'),
                    'series_description': series_data.get('series_description', ''),
                    'image_count': series_data.get('image_count', 0),
                    'protocol_name': series_data.get('protocol_name', ''),
                    'body_part_examined': series_data.get('body_part_examined', ''),
                    'manufacturer': series_data.get('manufacturer', ''),
                    'institution_name': series_data.get('institution_name', '')
                }
            else:
                # Fallback if no database data found
                return {
                    'series_number': series_number,
                    'modality': 'Unknown',
                    'series_description': f'Series {series_number}',
                    'image_count': 0
                }
                
        except Exception as e:
            print(f"Error getting cached series metadata: {str(e)}")
            # Return fallback metadata
            return {
                'series_number': series_number,
                'modality': 'Unknown', 
                'series_description': f'Series {series_number}',
                'image_count': 0
            }
    
    def display_cached_thumbnails_progressively(self, cached_thumbnails_data):
        """Display cached thumbnails one by one with a small delay for better UX"""
        try:
            # توقف timer قبلی اگر وجود دارد
            if hasattr(self, 'cached_thumbnail_timer') and self.cached_thumbnail_timer:
                self.cached_thumbnail_timer.stop()
                self.cached_thumbnail_timer.deleteLater()
            
            self.current_cached_index = 0
            self.cached_thumbnails_to_display = cached_thumbnails_data
            
            # Update thumbnail count if available
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"Loading 0/{len(cached_thumbnails_data)} cached series...")
            
            # Create a timer to display cached thumbnails progressively
            self.cached_thumbnail_timer = QTimer()
            self.cached_thumbnail_timer.timeout.connect(self.display_next_cached_thumbnail)
            self.cached_thumbnail_timer.start(15)  # 15ms delay - much faster cached loading
            
        except Exception as e:
            print(f"Error in display_cached_thumbnails_progressively: {str(e)}")
    
    def display_next_cached_thumbnail(self):
        """Display the next cached thumbnail(s) in the queue - OPTIMIZED: batch rendering"""
        try:
            if self.current_cached_index >= len(self.cached_thumbnails_to_display):
                # All cached thumbnails displayed, stop the timer
                self.cached_thumbnail_timer.stop()
                # Update final count
                if hasattr(self, 'thumb_count_label'):
                    self.thumb_count_label.setText(f"{len(self.cached_thumbnails_to_display)} cached series")
                return
            
            # OPTIMIZED: Process 4 thumbnails per tick for even faster cached loading
            batch_size = 4
            start_idx = self.current_cached_index
            end_idx = min(start_idx + batch_size, len(self.cached_thumbnails_to_display))
            
            for idx in range(start_idx, end_idx):
                thumb_data = self.cached_thumbnails_to_display[idx]
                
                try:
                    file_path = thumb_data.get('file_path')
                    if file_path and os.path.exists(file_path):
                        # Create standardized metadata for cached images
                        from PacsClient.pacs.patient_tab.utils.thumbnail_manager import ThumbnailManager
                        metadata = ThumbnailManager.create_standard_metadata(
                            series_number=thumb_data.get('series_number', f'Series {idx + 1}'),
                            modality=thumb_data.get('modality', 'Cached'),
                            series_description=thumb_data.get('series_description', ''),
                            image_count=thumb_data.get('image_count', 1),
                            is_downloading=False  # Mark as existing/cached - no progress
                        )
                        
                        # Add to layout
                        thumb_index = self.add_thumbnail_to_thumbnail_layout(
                            thumb_index=idx,
                            file_path_thumbnail=file_path,
                            metadata=metadata
                        )
                        
                except Exception as e:
                    print(f"Error processing cached thumbnail {idx}: {str(e)}")
            
            self.current_cached_index = end_idx
            
            # Update progress count
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"{self.current_cached_index}/{len(self.cached_thumbnails_to_display)} cached series")
            
        except Exception as e:
            print(f"Error in display_next_cached_thumbnail: {str(e)}")
            # Stop timer on error
            if hasattr(self, 'cached_thumbnail_timer'):
                self.cached_thumbnail_timer.stop()
    
    def show_loading_indicator(self, message="Loading..."):
        """Show loading indicator with message"""
        try:
            # Update header status if available
            if hasattr(self, 'status_label'):
                self.status_label.setText(message)
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #f59e0b;
                        font-size: 12px;
                        padding: 2px 6px;
                        background: rgba(245, 158, 11, 0.1);
                        border: 1px solid rgba(245, 158, 11, 0.3);
                        border-radius: 4px;
                    }
                """)
            
            print(f"⏳ Loading: {message}")
            
        except Exception as e:
            print(f"Error showing loading indicator: {e}")
    
    def hide_loading_indicator(self):
        """Hide loading indicator"""
        try:
            # Clear status if available
            if hasattr(self, 'status_label'):
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet("""
                    QLabel {
                        color: #10b981;
                        font-size: 12px;
                        padding: 2px 6px;
                        background: rgba(16, 185, 129, 0.1);
                        border: 1px solid rgba(16, 185, 129, 0.3);
                        border-radius: 4px;
                    }
                """)
            
            print("✅ Loading complete")
            
        except Exception as e:
            print(f"Error hiding loading indicator: {e}")
    
    def show_thumbnail_loading(self, total_count):
        """Show thumbnail loading progress"""
        try:
            if hasattr(self, 'thumb_count_label'):
                self.thumb_count_label.setText(f"Loading 0/{total_count} series...")
            
            print(f"⏳ Loading {total_count} thumbnails...")
            
        except Exception as e:
            print(f"Error showing thumbnail loading: {e}")
    
    def update_thumbnails_display(self):
        """Update the thumbnails display"""
        try:
            if hasattr(self, 'thumb_grid') and self.thumb_grid:
                self.thumb_grid.update()
            
            print("✅ Thumbnails display updated")
            
        except Exception as e:
            print(f"Error updating thumbnails display: {e}")
    
    def get_thumbnail_count(self):
        """Get the current thumbnail count"""
        try:
            if hasattr(self, 'lst_thumbnails_data'):
                return len(self.lst_thumbnails_data)
            return 0
        except Exception as e:
            print(f"Error getting thumbnail count: {e}")
            return 0
    
    def get_first_thumbnail_path(self):
        """Get the first thumbnail path"""
        return getattr(self, 'first_thumbnail_path', None)
    
    def set_first_thumbnail_path(self, path):
        """Set the first thumbnail path"""
        self.first_thumbnail_path = path
    
    def get_thumbnails_data(self):
        """Get the thumbnails data list"""
        return getattr(self, 'lst_thumbnails_data', [])
    
    def set_thumbnails_data(self, data):
        """Set the thumbnails data list"""
        self.lst_thumbnails_data = data
    
    def get_batch_cached_series_metadata(self, series_numbers):
        """
        OPTIMIZED: Batch fetch metadata for multiple series at once
        """
        try:
            if not self.parent_widget or not series_numbers:
                return {}
            
            # Get study_uid from parent widget or extract from import_folder_path
            study_uid = None
            
            if hasattr(self.parent_widget, 'study_uid') and self.parent_widget.study_uid:
                study_uid = self.parent_widget.study_uid
            elif hasattr(self.parent_widget, 'import_folder_path') and self.parent_widget.import_folder_path:
                from pathlib import Path
                study_uid = Path(self.parent_widget.import_folder_path).name
            
            if not study_uid:
                return {}
            
            # Import database functions
            from PacsClient.utils.db_manager import get_series_by_study_uid
            
            # Get all series for this study in one query
            all_series = get_series_by_study_uid(study_uid)
            
            if not all_series:
                return {}
            
            # Build a lookup dictionary by series_number
            metadata_map = {}
            for series_data in all_series:
                series_num = str(series_data.get('series_number', ''))
                metadata_map[series_num] = {
                    'series_number': series_data.get('series_number', series_num),
                    'modality': series_data.get('modality', 'Unknown'),
                    'series_description': series_data.get('series_description', ''),
                    'image_count': series_data.get('image_count', 0),
                    'protocol_name': series_data.get('protocol_name', ''),
                    'body_part_examined': series_data.get('body_part_examined', ''),
                    'manufacturer': series_data.get('manufacturer', ''),
                    'institution_name': series_data.get('institution_name', '')
                }
            
            print(f"✅ Batch loaded metadata for {len(metadata_map)} series")
            return metadata_map
                
        except Exception as e:
            print(f"Error in batch metadata fetch: {str(e)}")
            return {}
    
    def __del__(self):
        """
        Destructor - پاکسازی منابع هنگام حذف widget
        """
        try:
            self.cleanup_timers()
        except:
            pass
