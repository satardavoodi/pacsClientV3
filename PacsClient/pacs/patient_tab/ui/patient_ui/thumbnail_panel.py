"""
Thumbnail Panel Component
کامپوننت جداگانه برای مدیریت تامب‌نیل‌ها
"""

import logging
import os
import time
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
    QLabel, QScrollArea, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage

from PacsClient.pacs.patient_tab.utils import ThumbnailBatchRunner, ThumbnailManager, ThumbnailImageSourceService, ThumbnailProjectionService, create_attachment_folder, open_folder, \
    check_and_get_thumbnails, get_name_file_from_path
from PacsClient.utils.theme_manager import get_theme_manager


logger = logging.getLogger(__name__)


def print(*args, **_kw):  # noqa: A001
    """Route legacy debug prints to logger to avoid stdout blocking in hot paths."""
    logger.debug(' '.join(str(a) for a in args))


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
        self._thumbnail_series_names = set()
        self._thumbnail_file_paths = set()
        self.unique_elements_index = 0
        
        # Thumbnail management
        self.first_thumbnail_path = None
        self.thumbnail_manager = None
        self.thumbnail_image_source_service = ThumbnailImageSourceService()
        self.thumbnail_projection_service = ThumbnailProjectionService()
        self.thumb_grid = None
        self.thumb_count_label = None
        
        # Timer management
        self.thumbnail_runner = ThumbnailBatchRunner(self, interval_ms=20, batch_size=3)
        self.cached_thumbnail_runner = ThumbnailBatchRunner(self, interval_ms=15, batch_size=4)
        self.thumbnail_timer = self.thumbnail_runner.timer
        self.cached_thumbnail_timer = self.cached_thumbnail_runner.timer
        self.current_thumbnail_index = 0
        self.current_cached_index = 0
        self._last_progressive_batch_index = 0
        self._last_cached_batch_index = 0
        self.thumbnails_to_display = []
        self.cached_thumbnails_to_display = []
        
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
        # V2 parallel design (opt-in, default OFF): use the real theme accent
        # (fixes the off-palette purple fallback). No-op unless viewer == v2.
        try:
            from PacsClient.utils.v2_style import apply_thumbnail_header_v2
            apply_thumbnail_header_v2(title_label)
        except Exception:
            pass

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
    
    def _get_header_title_stylesheet(self):
        """Get themed header title stylesheet"""
        theme = self._active_theme
        # Fallback aligned with Blue baseline (#3182ce / #2c5282) so a stray
        # theme miss doesn't surface a violet button in any of the seven themes.
        accent = theme.get('accent', '#3182ce')
        accent_pressed = theme.get('accent_pressed', '#2c5282')
        
        return f"""
            QLabel {{
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: #f7fafc;
                padding: 6px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {accent_pressed});
                border: 1px solid {accent};
                border-radius: 8px;
            }}
        """
    
    def _get_header_count_stylesheet(self):
        """Get themed count label stylesheet"""
        theme = self._active_theme
        text_secondary = theme.get('text_secondary', '#a0aec0')
        
        return f"""
            QLabel {{
                font-size: 10px;
                font-family: 'Roboto', sans-serif;
                color: {text_secondary};
                padding: 4px 6px;
                background: rgba(160, 174, 192, 0.1);
                border: 1px solid rgba(160, 174, 192, 0.2);
                border-radius: 8px;
            }}
        """
    
    def _get_scrollarea_stylesheet(self):
        """Get themed scrollarea stylesheet"""
        theme = self._active_theme
        panel_bg = theme.get('panel_bg', '#0f1419')
        accent = theme.get('accent', '#4a5568')
        accent_hover = theme.get('accent_hover', '#718096')
        
        return f"""
            QScrollArea {{
                border: none;
                border-radius: 8px;
                background: {panel_bg};
            }}
            QScrollBar:vertical {{
                border: none;
                background: {panel_bg};
                width: 14px;
                border-radius: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent}, stop:1 {accent_hover});
                border-radius: 8px;
                min-height: 30px;
                margin: 2px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 {accent_hover}, stop:1 #a0aec0);
            }}
        """
    
    def _on_theme_changed(self, theme):
        """Handle theme changes"""
        self._active_theme = theme
        self._apply_theme()
    
    def _apply_theme(self):
        """Apply theme colors to all UI elements"""
        try:
            theme = self._active_theme
            
            # Update all header stylesheets
            header_widgets = self.findChildren(QLabel)
            for widget in header_widgets:
                if "Series Thumbnails" in widget.text():
                    widget.setStyleSheet(self._get_header_title_stylesheet())
                    # V2 (opt-in, default OFF): keep the accent header after re-apply.
                    try:
                        from PacsClient.utils.v2_style import apply_thumbnail_header_v2
                        apply_thumbnail_header_v2(widget)
                    except Exception:
                        pass
                elif "series" in widget.text().lower():
                    widget.setStyleSheet(self._get_header_count_stylesheet())
            
            # Update scroll area
            scroll_area = self.findChildren(QScrollArea)
            if scroll_area:
                scroll_area[0].setStyleSheet(self._get_scrollarea_stylesheet())
            
            # Update panel background
            panel_bg = theme.get('panel_bg', '#0f1419')
            self.setStyleSheet(f"""
                QWidget {{
                    background: {panel_bg};
                    border: none;
                    border-radius: 8px;
                    margin: 0px;
                    padding: 0px;
                }}
            """)
        except Exception as e:
            print(f"Error applying theme to thumbnail panel: {e}")
    
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


        if self._is_series_already_added(series_name):
            print('Finish at second if')
            return thumb_index  # we don't add new thumbnail

        print('file_path_thumbnail:', file_path_thumbnail)
        pixmap = self.thumbnail_image_source_service.load_pixmap(
            self.parent_widget,
            series_name,
            file_path_thumbnail,
        )
        
        # Extract series info from metadata or database
        series_info = None
        if metadata:
            series_info = self.thumbnail_projection_service.build_series_info_from_loaded_metadata(
                metadata,
                fallback_series_number=series_name,
            )
        else:
            # For cached thumbnails, try to get series info from database
            print(f"🔍 DEBUG: Processing cached thumbnail for series {series_name}")
            try:
                cached_info = self.get_cached_series_metadata(series_name)
                print(f"🔍 DEBUG: Got cached_info from database: {cached_info}")
                if cached_info:  # If database lookup succeeds
                    series_info = cached_info
                else:
                    print(f"🔍 DEBUG: Database lookup failed, creating fallback info")
                    series_info = self.thumbnail_projection_service.get_cached_series_info(
                        self.parent_widget,
                        series_name,
                    )
            except Exception as e:
                print(f"Error getting cached series info: {str(e)}")
                # Fallback to basic info
                series_info = self.thumbnail_projection_service.get_cached_series_info(
                    self.parent_widget,
                    series_name,
                )

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
        self._register_thumbnail_identity(series_name, file_path_thumbnail, thumb_index)
        logger.info("[THUMB_READY] series=%s index=%d", series_name, thumb_index)
        
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
            self.thumbnails_to_display = thumbnails_data
            self._last_progressive_batch_index = 0
            self.thumbnail_runner.start(
                thumbnails_data,
                on_item=self._process_progressive_thumbnail_item,
                on_progress=self._on_progressive_runner_progress,
                on_finished=self._on_progressive_runner_finished,
                on_error=self._on_progressive_runner_error,
            )
            
        except Exception as e:
            print(f"Error in display_thumbnails_progressively: {str(e)}")
    
    def display_next_thumbnail_patient(self):
        """Backward-compatible wrapper; scheduling is now owned by ThumbnailBatchRunner."""
        self.thumbnail_runner._tick()

    def _process_progressive_thumbnail_item(self, idx, thumb_data):
        file_path = thumb_data.get('file_path')
        if file_path and os.path.exists(file_path):
            if not self.is_thumbnail_already_added(file_path):
                metadata = self.thumbnail_projection_service.create_standard_metadata(
                    series_number=thumb_data.get('series_number', f'Series {idx + 1}'),
                    modality=thumb_data.get('modality', 'Unknown'),
                    series_description=thumb_data.get('series_description', ''),
                    image_count=thumb_data.get('image_count', 1),
                    protocol_name=thumb_data.get('protocol_name', ''),
                    body_part_examined=thumb_data.get('body_part_examined', ''),
                    is_downloading=False,
                )
                self.add_thumbnail_to_thumbnail_layout(
                    thumb_index=idx,
                    file_path_thumbnail=file_path,
                    metadata=metadata,
                )

    def _on_progressive_runner_progress(self, current, total):
        self.current_thumbnail_index = current
        flushed = max(0, current - self._last_progressive_batch_index)
        self._last_progressive_batch_index = current
        logger.info("[THUMB_BATCH_FLUSH] flushed=%d total=%d", flushed, total)
        if hasattr(self, 'thumb_count_label'):
            self.thumb_count_label.setText(f"{current}/{total} series")

    def _on_progressive_runner_finished(self, total):
        if hasattr(self, 'thumb_count_label'):
            self.thumb_count_label.setText(f"{total} series")

    def _on_progressive_runner_error(self, exc):
        print(f"Error in display_next_thumbnail_patient: {exc}")
    
    def is_thumbnail_already_added(self, file_path):
        """
        بررسی اینکه آیا تامب‌نیل قبلاً اضافه شده یا نه
        """
        try:
            normalized = self._normalize_thumbnail_file_path(file_path)
            if normalized and normalized in self._thumbnail_file_paths:
                return True

            if not hasattr(self, 'thumbnail_manager') or not self.thumbnail_manager:
                return False
            return False
            
        except Exception as e:
            print(f"❌ Error checking thumbnail existence: {e}")
            return False

    @staticmethod
    def _normalize_thumbnail_file_path(file_path):
        try:
            return str(Path(file_path)) if file_path else ""
        except Exception:
            return str(file_path or "")

    def _is_series_already_added(self, series_name):
        try:
            series_key = str(series_name)
            if series_key in self._thumbnail_series_names:
                return True
            if hasattr(self, 'thumbnail_manager') and self.thumbnail_manager:
                return series_key in self.thumbnail_manager.lst_buttons_name
            return False
        except Exception:
            return False

    def _register_thumbnail_identity(self, series_name, file_path_thumbnail, thumb_index):
        try:
            series_key = str(series_name)
            self._thumbnail_series_names.add(series_key)
            self._series_index[series_key] = thumb_index

            normalized_file_path = self._normalize_thumbnail_file_path(file_path_thumbnail)
            if normalized_file_path:
                self._thumbnail_file_paths.add(normalized_file_path)
        except Exception:
            pass
    
    def clear_thumbnails(self):
        """Clear existing thumbnails from the layout - OPTIMIZED for speed"""
        try:
            # توقف timerها
            if hasattr(self, 'thumbnail_runner') and self.thumbnail_runner:
                self.thumbnail_runner.stop()
            
            if hasattr(self, 'cached_thumbnail_runner') and self.cached_thumbnail_runner:
                self.cached_thumbnail_runner.stop()
            
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

                self._series_index.clear()
                self._thumbnail_series_names.clear()
                self._thumbnail_file_paths.clear()
                
                print("✅ Thumbnails cleared successfully")
                
        except Exception as e:
            print(f"⚠️ Error clearing thumbnails: {e}")
    
    def _safe_delete_widget(self, widget):
        """DEPRECATED: No longer needed - use direct deletion"""
        pass
    
    def get_cached_series_metadata(self, series_number):
        """Get cached series info via the thumbnail projection service."""
        try:
            return self.thumbnail_projection_service.get_cached_series_info(
                self.parent_widget,
                str(series_number),
            )
        except Exception as e:
            print(f"Error getting cached series metadata: {e}")
            return self.thumbnail_projection_service.get_cached_series_info(
                None,
                str(series_number),
            )
    
    def cleanup_timers(self):
        """
        پاکسازی همه timerها
        """
        try:
            # Disconnect from the app-lifetime ThemeManager so the closed tab's
            # thumbnail panel does not stay pinned as a live signal receiver.
            try:
                if getattr(self, 'theme_manager', None) is not None:
                    self.theme_manager.themeChanged.disconnect(self._on_theme_changed)
            except (TypeError, RuntimeError):
                pass
            # توقف و پاک کردن thumbnail timer
            if hasattr(self, 'thumbnail_runner') and self.thumbnail_runner:
                self.thumbnail_runner.stop()
            
            # توقف و پاک کردن cached thumbnail timer
            if hasattr(self, 'cached_thumbnail_runner') and self.cached_thumbnail_runner:
                self.cached_thumbnail_runner.stop()
            
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
            
            # OPTIMIZED: Build cached projection payloads in one helper call
            cached_thumbnails_data = self.thumbnail_projection_service.build_cached_thumbnail_entries(
                self.parent_widget,
                image_files,
            )
            
            # Display cached thumbnails progressively
            self.display_cached_thumbnails_progressively(cached_thumbnails_data)
            
        except Exception as e:
            print(f"Error in load_thumbnails_from_cache: {str(e)}")
    
    def display_cached_thumbnails_progressively(self, cached_thumbnails_data):
        """Display cached thumbnails one by one with a small delay for better UX"""
        try:
            self.cached_thumbnails_to_display = cached_thumbnails_data
            self._last_cached_batch_index = 0
            self.cached_thumbnail_runner.start(
                cached_thumbnails_data,
                on_item=self._process_cached_thumbnail_item,
                on_progress=self._on_cached_runner_progress,
                on_finished=self._on_cached_runner_finished,
                on_error=self._on_cached_runner_error,
            )
            
        except Exception as e:
            print(f"Error in display_cached_thumbnails_progressively: {str(e)}")
    
    def display_next_cached_thumbnail(self):
        """Backward-compatible wrapper; scheduling is now owned by ThumbnailBatchRunner."""
        self.cached_thumbnail_runner._tick()

    def _process_cached_thumbnail_item(self, idx, thumb_data):
        file_path = thumb_data.get('file_path')
        if file_path and os.path.exists(file_path):
            metadata = self.thumbnail_projection_service.create_standard_metadata(
                series_number=thumb_data.get('series_number', f'Series {idx + 1}'),
                modality=thumb_data.get('modality', 'Cached'),
                series_description=thumb_data.get('series_description', ''),
                image_count=thumb_data.get('image_count', 1),
                is_downloading=False,
            )
            self.add_thumbnail_to_thumbnail_layout(
                thumb_index=idx,
                file_path_thumbnail=file_path,
                metadata=metadata,
            )

    def _on_cached_runner_progress(self, current, total):
        self.current_cached_index = current
        flushed = max(0, current - self._last_cached_batch_index)
        self._last_cached_batch_index = current
        logger.info("[THUMB_BATCH_FLUSH] cached flushed=%d total=%d", flushed, total)
        if hasattr(self, 'thumb_count_label'):
            self.thumb_count_label.setText(f"{current}/{total} cached series")

    def _on_cached_runner_finished(self, total):
        if hasattr(self, 'thumb_count_label'):
            self.thumb_count_label.setText(f"{total} cached series")

    def _on_cached_runner_error(self, exc):
        print(f"Error in display_next_cached_thumbnail: {exc}")
    
    def show_loading_indicator(self, message="Loading..."):
        """Show loading indicator with message — themed via warning token."""
        try:
            # Update header status if available
            if hasattr(self, 'status_label'):
                self.status_label.setText(message)
                self.status_label.setStyleSheet(self._build_status_pill_style("warning"))

            print(f"⏳ Loading: {message}")

        except Exception as e:
            print(f"Error showing loading indicator: {e}")

    def hide_loading_indicator(self):
        """Hide loading indicator — themed via success token."""
        try:
            # Clear status if available
            if hasattr(self, 'status_label'):
                self.status_label.setText("Ready")
                self.status_label.setStyleSheet(self._build_status_pill_style("success"))

            print("✅ Loading complete")

        except Exception as e:
            print(f"Error hiding loading indicator: {e}")

    def _build_status_pill_style(self, semantic_key: str) -> str:
        """Stylesheet for the thumbnail-panel header status pill.

        `semantic_key` is one of "warning" / "success" / "danger" — the
        corresponding theme token drives BOTH the text color and the
        rgba glow + border ring, so the pill stays visually coherent
        across all seven themes (Yellow's olive success vs Dark Red's
        pink success, etc.).
        """
        try:
            from PacsClient.utils.theme_manager import get_theme_manager
            from PySide6.QtGui import QColor as _QColor
            theme = get_theme_manager().current_theme()
            hex_color = theme.get(semantic_key, "#f59e0b")
            qc = _QColor(hex_color)
            if not qc.isValid():
                qc = _QColor("#f59e0b")
            r, g, b = qc.red(), qc.green(), qc.blue()
            return (
                f"QLabel {{ color: {hex_color}; font-size: 12px; "
                f"padding: 2px 6px; "
                f"background: rgba({r}, {g}, {b}, 0.10); "
                f"border: 1px solid rgba({r}, {g}, {b}, 0.30); "
                f"border-radius: 4px; }}"
            )
        except Exception:
            # Fallback — matches the original hard-coded look so the UI
            # never falls back to "no style at all".
            fallback_hex = "#f59e0b" if semantic_key == "warning" else "#10b981"
            return (
                f"QLabel {{ color: {fallback_hex}; font-size: 12px; "
                f"padding: 2px 6px; background: rgba(245, 158, 11, 0.1); "
                f"border: 1px solid rgba(245, 158, 11, 0.3); border-radius: 4px; }}"
            )
    
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
            metadata_map = self.thumbnail_projection_service.get_batch_cached_series_metadata(
                self.parent_widget,
                series_numbers,
            )
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
