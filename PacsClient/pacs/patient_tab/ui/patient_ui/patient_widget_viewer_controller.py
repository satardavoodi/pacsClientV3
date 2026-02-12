"""
Viewer Controller Module
Encapsulates all viewer-related responsibilities for PatientWidget
"""

import asyncio
import gc
import time
import os
from PySide6.QtWidgets import QWidget, QVBoxLayout
from pathlib import Path
import numpy as np
import vtk
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QHBoxLayout, QSlider, QLabel, QScrollArea, QGridLayout, QToolBar, QPushButton, \
    QButtonGroup, QStackedWidget, QSizePolicy, QFrame, QGroupBox, QMessageBox, QListWidget, QListWidgetItem, QSplitter, \
    QGraphicsOpacityEffect, QProgressDialog, QWidget
from PySide6.QtGui import QPixmap, QColor
import contextlib
import json
import pydicom
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor

from PacsClient.pacs.patient_tab.utils import load_images, save_image_as_png, delete_widgets_in_layout, NodeViewer, \
    get_count_dicom_files_exist, load_images_from_server, VerticalButton
from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
from PacsClient.utils import get_patient_by_patient_pk, get_studies_by_patient_pk, CallerTypes
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget import VTKWidget, grow_vtk_inplace
from PacsClient.pacs.patient_tab.ui.widgets import ViewportSpinner
from PacsClient.pacs.patient_tab.zeta_sync import (
    SyncManager,
    SyncContext,
    SyncMode,
    SyncTarget,
    map_ijk_between_vtk_images,
    build_ijk_to_world_matrix,
    world_to_ijk,
    ijk_to_world,
    is_ijk_in_bounds,
    log_image_orientation,
)
from PacsClient.zeta_download_manager.core.enums import DownloadPriority
from PacsClient.utils.config import SOCKET_CONFIG_PATH

GRID_CONFIG_PATH = Path(SOCKET_CONFIG_PATH) / "modality_grid.json"
import logging


class ViewerController:
    """
    Encapsulates all viewer-related responsibilities for PatientWidget
    """
    
    def __init__(self, parent_widget):
        self.parent_widget = parent_widget
        self.logger = logging.getLogger(f"{__name__}.ViewerController")
        
        # Viewer-related attributes
        self.lst_nodes_viewer = []
        self.selected_widget = None
        self.slider = None
        
        # Viewer creation protection
        self._max_viewers_per_session = 25
        self._viewer_creation_throttle = 0
        self._last_gc_time = 0
        
        # Memory pools
        self._metadata_pool = {}
        self._layout_pool = []
        
        # Viewer state
        self._first_series_displayed = False
        self._is_initializing = True
        
        # ===== OPTIMIZED PERFORMANCE CACHES =====
        # Series lookup index: series_number -> (vtk_data, metadata, index)
        self._series_cache = {}
        self._series_name_cache = {}
        
        # OPTIMIZATION: O(1) series number to list index lookup
        self._series_number_to_index = {}
        
        # OPTIMIZATION: Paired series mapping for fast grouped series lookup
        self._paired_series_map = {}  # series_name -> [series_numbers]
        
        # OPTIMIZATION: Fast metadata access without nested dict lookups
        self._metadata_flat_cache = {}  # series_number -> flattened metadata dict
        
        # OPTIMIZATION: Recently accessed series for quick re-access
        self._hot_series_cache = {}  # Most recently accessed (limited size)
        
        # OPTIMIZATION: Pre-load adjacent series in background
        self._preload_queue = []
        self._preload_thread = None
        
        self._viewer_batch_queue = []
        
        # Performance optimization flags
        self._critical_sections_running = 0
        self._render_batch_pending = False
        self._pending_thumbnail_updates = []
        self._image_cache_max_size = 10

    # ===== OPTIMIZATION HELPER METHODS: FAST SERIES LOOKUP =====
    
    def _rebuild_series_index(self):
        """Rebuild fast lookup indices from lst_thumbnails_data (called once on data change)"""
        try:
            self._series_number_to_index.clear()
            self._paired_series_map.clear()
            self._metadata_flat_cache.clear()
            
            if not hasattr(self.parent_widget, 'lst_thumbnails_data'):
                return
            
            for idx, item in enumerate(self.parent_widget.lst_thumbnails_data):
                if not isinstance(item, dict):
                    continue
                metadata = item.get('metadata', {})
                series_info = metadata.get('series', {})
                series_number = str(series_info.get('series_number', ''))
                series_name = str(series_info.get('series_name', ''))
                
                if series_number:
                    # Fast index: series_number -> list index
                    self._series_number_to_index[series_number] = idx
                    
                    # Flat metadata cache for quick access without nested lookups
                    self._metadata_flat_cache[series_number] = {
                        'series_number': series_number,
                        'series_name': series_name,
                        'series_path': series_info.get('series_path', ''),
                        'instances': metadata.get('instances', []),
                    }
                    
                    # Paired series map: series_name -> list of numbers
                    if series_name:
                        if series_name not in self._paired_series_map:
                            self._paired_series_map[series_name] = []
                        if series_number not in self._paired_series_map[series_name]:
                            self._paired_series_map[series_name].append(series_number)
        except Exception as e:
            self.logger.debug(f"Error rebuilding series index: {e}")

    def _get_series_by_number_fast(self, series_number: str) -> tuple:
        """
        ⚡ Fast O(1) series lookup using index.
        Returns: (vtk_image_data, metadata, index) or (None, None, -1)
        """
        series_str = str(series_number)
        
        # 1. Check hot cache first (most recent access)
        if series_str in self._hot_series_cache:
            return self._hot_series_cache[series_str]
        
        # 2. Check main cache
        if series_str in self._series_cache:
            result = self._series_cache[series_str]
            self._hot_series_cache[series_str] = result
            return result
        
        # 3. Check index for fallback
        if series_str in self._series_number_to_index:
            idx = self._series_number_to_index[series_str]
            if idx < len(self.parent_widget.lst_thumbnails_data):
                item = self.parent_widget.lst_thumbnails_data[idx]
                vtk_data = item.get('vtk_image_data')
                meta = item.get('metadata')
                result = (vtk_data, meta, idx)
                self._series_cache[series_str] = result
                if len(self._hot_series_cache) > 3:  # Keep hot cache small
                    self._hot_series_cache.pop(next(iter(self._hot_series_cache)))
                self._hot_series_cache[series_str] = result
                return result
        
        return None, None, -1

    def _get_paired_series_fast(self, series_name: str, exclude_number: str = None) -> list:
        """
        ⚡ Get all paired series (same name, different data) in O(1) time.
        Returns list of (vtk_data, metadata, series_number) tuples
        """
        try:
            if series_name not in self._paired_series_map:
                return []
            
            exclude_number = str(exclude_number) if exclude_number else None
            results = []
            
            for series_num in self._paired_series_map[series_name]:
                if exclude_number and series_num == exclude_number:
                    continue
                
                vtk_data, metadata, _ = self._get_series_by_number_fast(series_num)
                if vtk_data is not None and metadata is not None:
                    results.append((vtk_data, metadata, series_num))
            
            return results
        except Exception as e:
            self.logger.debug(f"Error getting paired series: {e}")
            return []
    
    def init_matrix_viewers(self, numbers=None):
        """Initialize matrix of viewers based on layout"""
        if numbers is not None:
            # set default-interactorstyle when app started
            self.apply_multi_viewer(numbers)
            if self.selected_widget:
                self.parent_widget.toolbar_manager.current_style = self.selected_widget.style
        else:
            # create dummy image for show until image downloaded.
            dummy_vtk_widget = self.create_dummy_vtk_widget()
            self.parent_widget.vtk_layout.addWidget(dummy_vtk_widget, 0, 0)

    def apply_multi_viewer(self, numbers, modify_by_user=False):
        """
        Apply multi-viewer layout with optimized batch processing
        Reuses existing data and caches when possible
        """
        try:
            rows, cols = int(numbers[0]), int(numbers[1])
            required_count = rows * cols
            current_count = len(self.lst_nodes_viewer)
            current_data_count = len(self.parent_widget.lst_thumbnails_data)

            print(f"🔧 [LAYOUT] Applying {rows}x{cols} layout (need {required_count} viewers, have {current_count})")

            # ✅ FLICKER FIX: Disable updates during batch viewer creation
            self.parent_widget.setUpdatesEnabled(False)
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(False)

            # 1. Cleanup existing viewers but preserve data
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            print("   ✅ cleanup_all_viewers completed")  # No processEvents here

            # 2. Create viewers with existing data assignments
            displayed_series_indices = set()

            for i in range(required_count):
                # Determine which series to show in this viewer
                series_to_show = 0  # Default to first

                # If we have enough data, distribute them
                if current_data_count > 0:
                    # Cycle through available series if more viewers than series
                    series_to_show = i % current_data_count

                try:
                    node = self.new_viewer(series_to_show)

                    # If we have data, display it immediately
                    if current_data_count > 0 and i < current_data_count:
                        data = self.parent_widget.lst_thumbnails_data[i]
                        if hasattr(node.vtk_widget, 'switch_series'):
                            # Only create, don't switch yet - will do in batch below
                            pass

                except Exception as e:
                    print(f"   ⚠️ Error creating viewer {i}: {e}")
                    # Create fallback viewer
                    node = self._create_fallback_viewer()
                    self.lst_nodes_viewer.append(node)

            # 3. Arrange in grid
            for i, node in enumerate(self.lst_nodes_viewer):
                if i >= required_count:
                    break
                row, col = divmod(i, cols)
                self.parent_widget.vtk_layout.addWidget(node.widget, row, col)

            # 4. Distribute series to viewers
            self._distribute_series_to_viewers()

            # 5. Set first viewer as active
            if self.lst_nodes_viewer:
                self.change_container_border(0)

            if modify_by_user:
                QTimer.singleShot(500, self._hide_loading_msg)

            print(f"✅ [LAYOUT] Applied {rows}x{cols} layout with {len(self.lst_nodes_viewer)} viewers")

        except Exception as e:
            print(f"❌ [LAYOUT] Error: {e}")
            import traceback
            traceback.print_exc()
            if modify_by_user:
                self._hide_loading_msg()
        finally:
            # ✅ FLICKER FIX: Re-enable updates after batch creation
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(True)
            self.parent_widget.setUpdatesEnabled(True)
            # Single repaint after all changes
            self.parent_widget.update()

    def new_viewer(self, default_thumb_index=0):
        print(f"\n{'='*80}")
        print(f"🔨 [new_viewer] START - thumb_index={default_thumb_index}")
        self.logger.info(f"Creating new viewer with thumb index {default_thumb_index}")

        # Count existing viewers - if too many, be more aggressive with cleanup
        viewer_count = len(self.lst_nodes_viewer)

        # Hard limit protection
        if viewer_count >= self._max_viewers_per_session:
            print(f"   ⚠️ PROTECTION: Reached max viewers limit ({viewer_count}/{self._max_viewers_per_session})")
            print("   ⚠️ Creating lightweight placeholder viewer instead")
            try:
                return self._create_fallback_viewer()
            except Exception as e:
                print(f"   ❌ Even fallback failed: {e}")
                self.logger.error(f"Max viewers exceeded and fallback failed: {e}", exc_info=True)
                raise

        # Aggressive cleanup for high viewer counts
        if viewer_count > 15:
            print(f"   ⚠️ WARNING: Already have {viewer_count} viewers - running aggressive cleanup")
            # ⚡ OPTIMIZATION: Removed sleep(0.02) - gc.collect() is fast enough
            gc.collect()  # Force garbage collection immediately

        # Periodic cleanup
        import time
        current_time = time.time()
        if current_time - self._last_gc_time > 2.0 and viewer_count > 5:  # Every 2 seconds
            print(f"   🧹 [Periodic GC] Cleaning up ({viewer_count} viewers)")
            gc.collect()
            self._last_gc_time = current_time

        vtk_widget = None
        slider = None

        try:
            # ✅ FLICKER FIX: Removed processEvents - batching UI updates instead
            # processEvents was causing thumbnail loading to interrupt viewer creation

            print("   📐 Creating grid layout...")
            try:
                layout = QGridLayout()
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                print("   ✅ Grid layout created")
            except Exception as le:
                print(f"   ⚠️ Layout creation warning: {le}")
                raise RuntimeError(f"Failed to create grid layout: {le}")

            # Check if we have thumbnail data
            print("   🔍 Checking thumbnail data...")
            try:
                has_data = (hasattr(self.parent_widget, 'lst_thumbnails_data') and
                           self.parent_widget.lst_thumbnails_data and
                           len(self.parent_widget.lst_thumbnails_data) > 0)
            except Exception as ce:
                print(f"   ⚠️ Data check warning: {ce}")
                has_data = False

            if not has_data:
                print("   📦 No thumbnail data, creating lightweight VTK widget...")
                try:
                    # ✅ FLICKER FIX: Use lightweight VTK widget with deferred rendering
                    vtk_widget = self._create_lightweight_vtk_placeholder()
                    if vtk_widget is None:
                        raise RuntimeError("_create_lightweight_vtk_placeholder returned None")
                    print("   ✅ Lightweight VTK widget created")
                except Exception as dwe:
                    print(f"   ❌ Lightweight VTK widget creation failed: {dwe}")
                    raise
            else:
                print(f"   ✅ Thumbnail data exists ({len(self.parent_widget.lst_thumbnails_data)} items)")
                print("   🎨 Creating new VTK widget...")
                try:
                    vtk_widget = self.create_new_vtk_widget(default_thumb_index)
                    if vtk_widget is None:
                        print("   ⚠️ create_new_vtk_widget returned None, using lightweight fallback")
                        vtk_widget = self._create_lightweight_vtk_placeholder()
                        if vtk_widget is None:
                            raise RuntimeError("Both create_new_vtk_widget and _create_lightweight_vtk_placeholder failed")
                    print("   ✅ VTK widget created")
                except Exception as vwe:
                    print(f"   ❌ VTK widget creation failed: {vwe}")
                    raise

            # Validate vtk_widget
            if vtk_widget is None:
                raise RuntimeError("vtk_widget is None after creation")

            if not isinstance(vtk_widget, QWidget):
                raise RuntimeError(f"vtk_widget is not a QWidget, got {type(vtk_widget)}")

            print("   📊 Creating slider...")
            try:
                slider = QSlider(Qt.Vertical, vtk_widget)
                if slider is None:
                    raise RuntimeError("QSlider constructor returned None")
                slider.setInvertedAppearance(True)
                slider.setMaximumWidth(12)
                print("   ✅ Slider created")
            except Exception as se:
                print(f"   ❌ Slider creation failed: {se}")
                raise RuntimeError(f"Failed to create slider: {se}")

        except Exception as e:
            print(f"   ❌ ERROR in new_viewer setup: {e}")
            self.logger.error(f"Error in new_viewer setup: {e}", exc_info=True)

            # Try to return fallback viewer
            try:
                print("   🔄 Attempting fallback viewer creation...")
                fallback = self._create_fallback_viewer()
                if fallback:
                    print("   ✅ Fallback viewer created successfully")
                    return fallback
            except Exception as fe:
                print(f"   ❌ Fallback viewer also failed: {fe}")

            raise

        # Configure slider styling
        try:
            slider.setStyleSheet("""
                QSlider {
                    background: rgba(0, 0, 0, 1);
                    border-radius: 0px;
                    border: none;
                    padding-top: 50px;
                    padding-bottom: 50px;
                }
                QSlider::groove:vertical {
                    background: #90caf9;
                    width: 6px;
                    border-radius: 3px;
                }
                QSlider::handle:vertical {
                    background: #90caf9;
                    border: none;
                    width: 0;
                    height: 0;
                    border-radius: 0;
                    margin: 0;
                }
                QSlider::handle:vertical:hover {
                    background: #5d99c6;
                }
                QSlider::sub-page:vertical {
                    background: #90caf9;
                    border-radius: 3px;
                }
                QSlider::add-page:vertical {
                    background: rgba(0,0,0,0.5);
                    border-radius: 3px;
                }
            """)
            print("   ✅ Slider styling applied")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not apply slider styling: {e}")

        try:
            print("   📍 Adding widgets to layout...")
            layout.addWidget(vtk_widget, 0, 0)
            layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight)
            print("   ✅ Widgets added to layout")
        except Exception as e:
            print(f"   ❌ ERROR adding widgets to layout: {e}")
            self.logger.error(f"Error adding widgets to layout: {e}", exc_info=True)
            raise

        # Use QFrame instead of QWidget - QFrame is designed for borders!
        try:
            print("   🖼️ Creating container frame...")
            container = QFrame()
            container.setObjectName("ViewportContainer")
            container.setLayout(layout)
            container.setFrameStyle(QFrame.Box | QFrame.Plain)
            container.setLineWidth(2)  # Smaller border for inactive
            container.setProperty("active", False)
            container.setStyleSheet("""
                QFrame#ViewportContainer {
                    border: 2px solid #9ca3af;
                    border-radius: 2px;
                    background-color: transparent;
                }
            """)
            print("   ✅ Container created")
        except Exception as e:
            print(f"   ❌ ERROR creating container: {e}")
            self.logger.error(f"Error creating container: {e}", exc_info=True)
            raise

        # Create NodeViewer
        try:
            print("   🔗 Creating NodeViewer...")
            new_node = NodeViewer(container, vtk_widget, slider)
            if new_node is None:
                raise RuntimeError("NodeViewer creation returned None")
            print("   ✅ NodeViewer created")
        except Exception as e:
            print(f"   ❌ ERROR creating NodeViewer: {e}")
            self.logger.error(f"Error creating NodeViewer: {e}", exc_info=True)
            raise

        # Set viewer ID and configure
        try:
            print("   🆔 Setting viewer ID...")
            viewer_index = len(self.lst_nodes_viewer)

            # Safely set ID attribute
            if hasattr(vtk_widget, '__dict__'):
                vtk_widget.id_vtk_widget = viewer_index
            else:
                setattr(vtk_widget, 'id_vtk_widget', viewer_index)
            print(f"   ✅ Viewer ID set to {viewer_index}")

            print("   📝 Appending to lst_nodes_viewer...")
            self.lst_nodes_viewer.append(new_node)
            print("   ✅ Appended")
        except Exception as e:
            print(f"   ❌ ERROR setting viewer ID: {e}")
            self.logger.error(f"Error setting viewer ID: {e}", exc_info=True)
            raise

        # Configure slider
        try:
            print("   🎚️ Configuring slider...")

            # Check if methods exist
            if not hasattr(vtk_widget, 'set_slider'):
                print("   ⚠️ VTK widget doesn't have set_slider yet (placeholder mode)")
                # For placeholder widgets, just set slider to default values
                slider.setMinimum(0)
                slider.setMaximum(0)
                slider.setValue(0)
                print("   ✅ Slider configured in placeholder mode (0 slices)")
            else:
                vtk_widget.set_slider(slider)

                if not hasattr(vtk_widget, 'get_count_of_slices'):
                    raise AttributeError("VTK widget doesn't have get_count_of_slices method")

                count_slices = vtk_widget.get_count_of_slices()
                mid_slices = 0
                last_slices = max(0, count_slices - 1)

                slider.setMinimum(0)
                slider.setMaximum(last_slices)
                slider.setValue(mid_slices)
                print(f"   ✅ Slider configured (slices: {count_slices}, current: {mid_slices})")
        except Exception as e:
            print(f"   ❌ ERROR configuring slider: {e}")
            # Don't raise - allow viewer creation to continue
            # Just set slider to defaults
            slider.setMinimum(0)
            slider.setMaximum(0)
            slider.setValue(0)
            print("   ⚠️ Slider set to default values after error")

        # Connect signals
        try:
            print("   🔗 Connecting slider signal...")
            self.parent_widget.on_slider_value_changed(vtk_widget, mid_slices)
            slider.valueChanged.connect(lambda val: self.parent_widget.on_slider_value_changed(vtk_widget, val))
            print("   ✅ Slider connected")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not connect slider signal: {e}")
            self.logger.warning(f"Warning connecting slider signal: {e}")

        # Set VTK widget methods
        try:
            print("   🔧 Setting VTK widget methods...")
            if hasattr(vtk_widget, 'set_method_change_series_on_drop'):
                vtk_widget.set_method_change_series_on_drop(self.parent_widget.change_series_on_viewer)
            if hasattr(vtk_widget, 'set_method_change_container_border'):
                vtk_widget.set_method_change_container_border(self.change_container_border)
            print("   ✅ Methods set")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not set VTK widget methods: {e}")
            self.logger.warning(f"Warning setting VTK widget methods: {e}")

        print(f"🔨 [new_viewer] END - Successfully created viewer with ID {viewer_index}")
        print(f"{'='*80}\n")
        return new_node

    def _create_lightweight_vtk_placeholder(self):
        """Create a lightweight VTK widget that defers rendering until data is loaded"""
        try:
            height = self.parent_widget.sidebar.height() if hasattr(self.parent_widget, 'sidebar') and self.parent_widget.sidebar else 480
            vtk_widget = VTKWidget(height_viewer=height)

            if vtk_widget is None:
                raise RuntimeError("VTKWidget constructor returned None")

            # ✅ CRITICAL: Set solid background FIRST to prevent any flash
            if hasattr(vtk_widget, 'renderer'):
                vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)  # #1a1a2e in RGB
                # Force immediate render of background
                if hasattr(vtk_widget, 'render_window'):
                    vtk_widget.render_window.Render()

            # Minimize rendering updates until real data is loaded
            if hasattr(vtk_widget, 'render_window'):
                vtk_widget.render_window.SetDesiredUpdateRate(0.001)  # Very low update rate

            # Add a flag to indicate this is a placeholder
            vtk_widget._is_placeholder = True

            return vtk_widget
        except Exception as e:
            print(f"❌ Error creating lightweight VTK widget: {e}")
            self.logger.error(f"Error creating lightweight VTK widget: {e}", exc_info=True)
            return None

    def create_dummy_vtk_widget(self):
        """Legacy method - redirects to lightweight placeholder"""
        return self._create_lightweight_vtk_placeholder()

    def create_new_vtk_widget(self, default_thumb_index):
        """Create a new VTK widget with series data, with comprehensive error handling"""
        try:
            # Check if lst_thumbnails_data exists and has sufficient data
            if not hasattr(self.parent_widget, 'lst_thumbnails_data') or not self.parent_widget.lst_thumbnails_data or len(self.parent_widget.lst_thumbnails_data) <= default_thumb_index:
                print(f"⚠️ [create_new_vtk_widget] No thumbnail data at index {default_thumb_index}, using dummy")
                return self.create_dummy_vtk_widget()

            # Extract data safely
            try:
                thumbnail_item = self.parent_widget.lst_thumbnails_data[default_thumb_index]
                if not isinstance(thumbnail_item, dict) or 'vtk_image_data' not in thumbnail_item or 'metadata' not in thumbnail_item:
                    raise ValueError(f"Invalid thumbnail data structure at index {default_thumb_index}")

                vtk_widget_data = thumbnail_item['vtk_image_data']
                metadata = thumbnail_item['metadata']

                if vtk_widget_data is None or metadata is None:
                    raise ValueError("VTK data or metadata is None")

            except (IndexError, KeyError, TypeError) as e:
                print(f"⚠️ [create_new_vtk_widget] Error extracting thumbnail data: {e}")
                return self.create_dummy_vtk_widget()

            # Extract metadata safely
            try:
                series_name = metadata.get('series', {}).get('series_name', 'Unknown')
                series_number = metadata.get('series', {}).get('series_number', 0)
            except (AttributeError, TypeError) as e:
                print(f"⚠️ [create_new_vtk_widget] Error extracting series info: {e}")
                series_name = 'Unknown'
                series_number = 0

            # Create VTK widget
            try:
                vtk_widget = self.creator_vtk_widget()
                if vtk_widget is None:
                    raise RuntimeError("creator_vtk_widget returned None")
            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error creating VTK widget: {e}")
                self.logger.error(f"Error creating VTK widget: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

            # Look for combined series
            id_new_vtk_widget = len(self.lst_nodes_viewer)
            flag_open_combine_viewer = False
            vtk_widget_data_2 = None
            metadata_2 = None

            try:
                for i in range(len(self.parent_widget.lst_thumbnails_data)):
                    if i == default_thumb_index:
                        continue

                    try:
                        item = self.parent_widget.lst_thumbnails_data[i]
                        series_name_2 = item.get('metadata', {}).get('series', {}).get('series_name', '')

                        if series_name_2 == series_name:
                            flag_open_combine_viewer = True
                            vtk_widget_data_2 = item.get('vtk_image_data')
                            metadata_2 = item.get('metadata')
                            break
                    except (AttributeError, TypeError, IndexError):
                        continue
            except Exception as e:
                print(f"⚠️ [create_new_vtk_widget] Warning during combined series check: {e}")

            print(f'[create_new_vtk_widget] Series: {series_name}, Number: {series_number}, Combined: {flag_open_combine_viewer}')

            # Process series
            try:
                if flag_open_combine_viewer and vtk_widget_data_2 is not None and metadata_2 is not None:
                    vtk_widget.start_process_combine_series(
                        vtk_widget_data, metadata, vtk_widget_data_2, metadata_2, series_number, id_new_vtk_widget,
                        metadata_fixed=self.parent_widget.metadata_fixed if hasattr(self.parent_widget, 'metadata_fixed') else {})
                else:
                    vtk_widget.start_process_series(
                        vtk_image_data=vtk_widget_data, metadata=metadata, series_index=series_number,
                        id_vtk_widget=id_new_vtk_widget, metadata_fixed=self.parent_widget.metadata_fixed if hasattr(self.parent_widget, 'metadata_fixed') else {})

                return vtk_widget

            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error processing series: {e}")
                self.logger.error(f"Error processing series: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

        except Exception as e:
            print(f"❌ [create_new_vtk_widget] Unexpected error: {e}")
            self.logger.error(f"Unexpected error in create_new_vtk_widget: {e}", exc_info=True)
            return self.create_dummy_vtk_widget()

    def creator_vtk_widget(self):
        try:
            height = self.parent_widget.sidebar.height() if hasattr(self.parent_widget, 'sidebar') and self.parent_widget.sidebar else 480
            return VTKWidget(height_viewer=height)
        except Exception as e:
            print(f"❌ Error in creator_vtk_widget: {e}")
            self.logger.error(f"Error in creator_vtk_widget: {e}", exc_info=True)
            return None

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        if self.selected_widget == node_viewer.vtk_widget:
            # print('we clicked on the main viewer')
            return False

        # save tool activated
        tool_activated_method = self.parent_widget.toolbar_manager.get_tool_activated_method()

        # print(f'tool selected before: {self.parent_widget.toolbar_manager.tool_selected},, tool_activated_method before off:', tool_activated_method)
        self.parent_widget.toolbar_manager.check_and_deactivate_tools()
        # print(f'tool selected after: {self.parent_widget.toolbar_manager.tool_selected},,,,,, tool_activated_method after off:', self.parent_widget.toolbar_manager.get_tool_activated_method())

        # set new vtk_widget to main vtk_widget
        self.selected_widget: VTKWidget = node_viewer.vtk_widget
        self.slider = node_viewer.slider

        # print('************************************************')
        if tool_activated_method:
            # apply activated tool on new vtk_widget
            self.parent_widget.toolbar_manager.tool_selected = None
            tool_activated_method(self.selected_widget)

    def change_container_border(self, id_vtk_widget):
        # TODO: at first we must check last viewer selected. if the last viewed selected and id_vtk_widget are the
        #  same, skip the for (return)
        node_viewer_selected = self.lst_nodes_viewer[id_vtk_widget]
        for node_viewer in self.lst_nodes_viewer:
            node_viewer: NodeViewer

            if node_viewer_selected.widget == node_viewer.widget:
                # Active viewport - same size border, just different color (blue)
                node_viewer_selected.widget.setProperty("active", True)
                node_viewer_selected.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
                node_viewer_selected.widget.setLineWidth(2)  # Same as inactive
                node_viewer_selected.widget.setStyleSheet("""
                    QFrame#ViewportContainer {
                        border: 2px solid #60a5fa;
                        border-radius: 2px;
                        background-color: transparent;
                    }
                """)
                self.set_viewer_to_main_viewer(node_viewer_selected)

            else:
                # Inactive viewport - same size border, different color (gray)
                node_viewer.widget.setProperty("active", False)
                node_viewer.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
                node_viewer.widget.setLineWidth(2)  # Same as active
                node_viewer.widget.setStyleSheet("""
                    QFrame#ViewportContainer {
                        border: 2px solid #9ca3af;
                        border-radius: 2px;
                        background-color: transparent;
                    }
                """)

        self.parent_widget.manage_reference_line()

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                vtk_widget: VTKWidget = None, slider: QSlider = None):
        """
        ⚡ OPTIMIZED: Switch series with O(1) lookup and minimal overhead.
        
        Performance improvements:
        - Uses hash-based series cache instead of linear search
        - Eliminates redundant metadata extraction
        - Fast paired series detection with index
        - Removes artificial delays
        """
        try:
            series_number = str(series_index)
            
            # Initialize parent structures once
            if not hasattr(self.parent_widget, 'lst_thumbnails_data'):
                self.parent_widget.lst_thumbnails_data = []

            # ✅ ENSURE VIEWERS EXIST (fail-fast check)
            if not self.lst_nodes_viewer:
                try:
                    self.apply_multi_viewer((1, 1), modify_by_user=False)
                except Exception as e:
                    self.logger.error(f"Failed to create default viewers: {e}")
                    return

            # ⚡ FAST PATH: O(1) series lookup with caching
            vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
            
            # If not cached, search and cache (only one pass)
            if metadata is None:
                # Linear search only if not in any cache (happens once per series)
                for i, data in enumerate(self.parent_widget.lst_thumbnails_data):
                    if str(data.get('metadata', {}).get('series', {}).get('series_number')) == series_number:
                        vtk_image_data = data['vtk_image_data']
                        metadata = data['metadata']
                        series_idx = i
                        # Cache immediately for next access
                        self._series_cache[series_number] = (vtk_image_data, metadata, series_idx)
                        break
            
            # If still not found, try loading from disk
            if metadata is None:
                study_path = self._get_correct_study_path()
                if not self._load_single_series_on_demand(int(series_number), study_path):
                    self._trigger_download_if_needed(series_number)
                    return
                # After loading, retrieve from cache again
                vtk_image_data, metadata, series_idx = self._get_series_by_number_fast(series_number)
                if metadata is None:
                    return

            # ⚡ FAST WIDGET SETUP: Reuse existing or get from cache
            if flag_change_selected_widget:
                if self.selected_widget is None and self.lst_nodes_viewer:
                    self.set_viewer_to_main_viewer(self.lst_nodes_viewer[0])
                
                vtk_widget = self.selected_widget
                slider = getattr(self.parent_widget, 'slider', None) or (
                    self.lst_nodes_viewer[0].slider if self.lst_nodes_viewer else None
                )
            
            # ⚡ FINAL VALIDATION
            if vtk_widget is None or slider is None:
                return

            # ⚡ PERFORM SWITCH WITH OPTIMIZED PAIRED SERIES LOOKUP
            self._perform_series_switch_optimized(vtk_widget, metadata, vtk_image_data, series_idx, slider)

        except Exception as e:
            self.logger.error(f"Error switching series: {e}", exc_info=True)

    def _get_correct_study_path(self) -> str:
        """Get the correct study path, ensuring it's not pointing to a series subfolder"""
        from pathlib import Path

        if not self.parent_widget.import_folder_path:
            return None

        path = Path(self.parent_widget.import_folder_path)

        # If current path has numeric subfolders that are series, we're at study level
        # If current path is numeric and exists inside another folder, go up
        if path.name.isdigit() and path.parent.exists():
            # Check if parent has other series folders
            parent = path.parent
            series_folders = [d for d in parent.iterdir() if d.is_dir() and d.name.isdigit()]
            if len(series_folders) > 1:
                return str(parent)

        return str(path)

    def _perform_series_switch_optimized(self, vtk_widget, metadata, vtk_image_data, series_idx, slider):
        """
        ⚡ OPTIMIZED: Perform series switch with O(1) paired series lookup.
        
        Performance improvements:
        - Fast paired series detection using index
        - No redundant list iterations
        - Direct metadata access without nesting lookups
        """
        try:
            series_number = str(metadata.get('series', {}).get('series_number', ''))
            series_name = str(metadata.get('series', {}).get('series_name', ''))
            
            # ⚡ FAST PAIRED SERIES LOOKUP: O(1) instead of linear search
            vtk_widget_data_2 = None
            metadata_2 = None
            
            if series_name in self._paired_series_map:
                # Find first paired series that's not the current one
                paired_list = self._paired_series_map[series_name]
                for paired_num in paired_list:
                    if str(paired_num) != series_number:
                        vtk_data, meta, _ = self._get_series_by_number_fast(str(paired_num))
                        if vtk_data is not None and meta is not None:
                            vtk_widget_data_2 = vtk_data
                            metadata_2 = meta
                            break
            
            # ⚡ PERFORM SWITCH (no delay, no blocking)
            if hasattr(vtk_widget, 'switch_series'):
                flag_switch = vtk_widget.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    vtk_widget_data_2,
                    metadata_2,
                    self.parent_widget.metadata_fixed
                )
                
                if flag_switch:
                    # Quick slider configuration
                    self.parent_widget.reset_slider(vtk_widget, slider)
                    self.parent_widget.toolbar_manager.turn_off_all_tools()
                    
                    # Update UI elements
                    if hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer:
                        vtk_widget.image_viewer.update_corners_actors()
        
        except Exception as e:
            self.logger.error(f"Error in series switch: {e}", exc_info=True)

    def _perform_series_switch(self, vtk_widget, metadata, vtk_image_data, series_idx, slider):
        """Legacy method - redirects to optimized version"""
        self._perform_series_switch_optimized(vtk_widget, metadata, vtk_image_data, series_idx, slider)

    def _show_loading_spinner(self, message="Loading..."):
        """نمایش spinner در viewport فعلی"""
        try:
            if hasattr(self.parent_widget, 'selected_widget') and self.parent_widget.selected_widget:
                spinner = getattr(self.parent_widget.selected_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.show_loading(message)
        except Exception:
            pass

    def _hide_loading_spinner(self):
        """مخفی کردن spinner در viewport فعلی"""
        try:
            if hasattr(self.parent_widget, 'selected_widget') and self.parent_widget.selected_widget:
                spinner = getattr(self.parent_widget.selected_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.hide_loading()
        except Exception:
            pass

    def _show_viewer_loading_all(self):
        """Show loading spinner on all viewers."""
        try:
            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                spinner = getattr(vtk_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.show_loading("Loading...")
        except Exception:
            pass

    def _hide_viewer_loading_all(self):
        """Hide loading spinner on all viewers."""
        try:
            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                spinner = getattr(vtk_widget, 'viewport_spinner', None)
                if spinner:
                    spinner.hide_loading()
        except Exception:
            pass

    def _display_first_series_in_viewer(self):
        """Display the first available series in all viewers."""
        try:
            if not self.parent_widget.lst_thumbnails_data:
                return False
            series_number = str(self.parent_widget.lst_thumbnails_data[0]['metadata']['series']['series_number'])
            if self._display_first_series_in_all_viewers(series_number):
                self._mark_first_series_displayed()
                return True
            return False
        except Exception:
            return False

    def _mark_first_series_displayed(self):
        """Finalize first-series display: hide overlays and notify Home UI."""
        if self._first_series_displayed:
            return
        self._first_series_displayed = True
        self._hide_viewer_loading_all()
        self.parent_widget._hide_init_overlay()
        try:
            self.parent_widget.loading_complete.emit()
        except Exception:
            pass

    def _display_first_series_in_all_viewers(self, series_number: str) -> bool:
        """Display the first downloaded series in all viewers."""
        try:
            series_number = self.parent_widget.resolve_series_key(series_number)
            vtk_image_data = None
            metadata = None

            for data in self.parent_widget.lst_thumbnails_data:
                if str(data.get('metadata', {}).get('series', {}).get('series_number')) == str(series_number):
                    vtk_image_data = data.get('vtk_image_data')
                    metadata = data.get('metadata')
                    break

            if vtk_image_data is None or metadata is None:
                return False

            if self.lst_nodes_viewer and self.selected_widget is None:
                first_node = self.lst_nodes_viewer[0]
                self.selected_widget = getattr(first_node, 'vtk_widget', None)
                self.parent_widget.slider = getattr(first_node, 'slider', None)

            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                slider = getattr(node, 'slider', None)
                if vtk_widget is None:
                    continue
                self._display_loaded_series(
                    series_number=series_number,
                    vtk_image_data=vtk_image_data,
                    metadata=metadata,
                    flag_change_selected_widget=False,
                    vtk_widget=vtk_widget,
                    slider=slider
                )

            self._mark_first_series_displayed()
            return True
        except Exception as e:
            self.logger.debug(f"Error displaying first series: {e}")
            return False

    def _display_loaded_series(self, series_number, vtk_image_data, metadata,
                               flag_change_selected_widget, vtk_widget, slider):
        """
        ⚡ OPTIMIZED: Display series with O(1) paired series lookup.
        
        Performance improvements:
        - Fast paired series detection using index
        - No redundant list iterations
        - Caching-aware lookups
        """
        try:
            # Quick setup
            if flag_change_selected_widget and self.selected_widget is None:
                if self.lst_nodes_viewer:
                    self.selected_widget = self.lst_nodes_viewer[0].vtk_widget
                    self.parent_widget.slider = self.lst_nodes_viewer[0].slider
                else:
                    return

            # ⚡ FAST PAIRED SERIES LOOKUP: O(1)
            vtk_widget_data_2 = None
            metadata_2 = None
            
            series_name = str(metadata.get('series', {}).get('series_name', ''))
            if series_name in self._paired_series_map:
                paired_list = self._paired_series_map[series_name]
                for paired_num in paired_list:
                    if str(paired_num) != str(series_number):
                        vtk_data, meta, _ = self._get_series_by_number_fast(str(paired_num))
                        if vtk_data is not None and meta is not None:
                            vtk_widget_data_2 = vtk_data
                            metadata_2 = meta
                            break

            # Perform switch
            target_widget = self.selected_widget if flag_change_selected_widget else vtk_widget
            target_slider = self.parent_widget.slider if flag_change_selected_widget else slider
            
            if hasattr(target_widget, 'switch_series'):
                flag_switch = target_widget.switch_series(
                    vtk_image_data, metadata, series_number,
                    vtk_widget_data_2, metadata_2,
                    self.parent_widget.metadata_fixed
                )
                
                if flag_switch:
                    self.parent_widget.reset_slider(target_widget, target_slider)
                    self.parent_widget.toolbar_manager.turn_off_all_tools()
                    if hasattr(self.selected_widget, 'resizeEvent'):
                        self.selected_widget.resizeEvent(None)
                    if hasattr(target_widget, 'image_viewer') and target_widget.image_viewer:
                        target_widget.image_viewer.update_corners_actors()
        
        except Exception as e:
            self.logger.debug(f"Error displaying series: {e}")

    def _distribute_series_to_viewers(self):
        """بهینه‌سازی توزیع سری‌ها به viewers"""
        if not self.parent_widget.lst_thumbnails_data or not self.lst_nodes_viewer:
            return

        # استفاده از batch processing برای بهتر شدن performance
        try:
            for i, node in enumerate(self.lst_nodes_viewer):
                series_index = i % len(self.parent_widget.lst_thumbnails_data)
                # Pre-cache series metadata
                if series_index < len(self.parent_widget.lst_thumbnails_data):
                    data = self.parent_widget.lst_thumbnails_data[series_index]
                    series_num = str(data['metadata']['series']['series_number'])
                    # Warm up cache
                    if series_num not in self._series_cache:
                        self._series_cache[series_num] = (
                            data['vtk_image_data'],
                            data['metadata'],
                            series_index
                        )
        except Exception as e:
            print(f"⚠️ Error pre-caching series: {e}")

    def _create_fallback_viewer(self):
        """Create dummy viewer for missing data - with full error handling"""
        try:
            from PacsClient.pacs.patient_tab.utils import NodeViewer

            print("   📝 [Fallback] Creating layout...")
            layout = QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)

            print("   🖼️ [Fallback] Creating container...")
            container = QFrame()
            container.setLayout(layout)

            print("   🎨 [Fallback] Creating dummy VTK widget...")
            vtk_widget = self.create_dummy_vtk_widget()
            if vtk_widget is None:
                raise RuntimeError("create_dummy_vtk_widget failed")

            print("    📊 [Fallback] Creating slider...")
            slider = QSlider(Qt.Vertical)

            print("   🔗 [Fallback] Creating NodeViewer...")
            node = NodeViewer(container, vtk_widget, slider)
            if node is None:
                raise RuntimeError("NodeViewer creation failed")

            print("   ✅ [Fallback] Fallback viewer created successfully")
            return node

        except Exception as e:
            print(f"   ❌ [Fallback] Error creating fallback viewer: {e}")
            self.logger.error(f"Fallback viewer creation failed: {e}", exc_info=True)
            return None

    def create_some_viewers(self, count):
        last_viewer_index = 0
        for i in range(count):
            try:
                # it's means we have series at enough
                self.new_viewer(i)
                last_viewer_index = i
            except:
                # we don't have series at enough. so we create from last series until row * col
                self.new_viewer(last_viewer_index)

    def cleanup_all_viewers(self):
        """تمیز‌کردن بهینهٔ viewers و resources"""
        try:
            # Clean up VTK layout
            if hasattr(self.parent_widget, 'vtk_layout'):
                try:
                    delete_widgets_in_layout(self.parent_widget.vtk_layout)
                except:
                    pass

            # Clean up viewer nodes efficiently
            if hasattr(self, 'lst_nodes_viewer'):
                for node in list(self.lst_nodes_viewer):  # Use list() to avoid modification during iteration
                    try:
                        node: NodeViewer
                        # CRITICAL: Check if vtk_widget attribute exists before accessing
                        if hasattr(node, 'vtk_widget'):
                            vtk_widget: VTKWidget = node.vtk_widget
                            if hasattr(vtk_widget, 'cleanup_image_viewer'):
                                try:
                                    vtk_widget.cleanup_image_viewer()
                                except:
                                    pass

                        # Safe deletion
                        for attr in ('vtk_widget', 'widget', 'slider'):
                            try:
                                if hasattr(node, attr):
                                    delattr(node, attr)
                            except:
                                pass
                    except Exception as e:
                        self.logger.debug(f"Error cleaning up viewer node: {e}")

            # Clear caches to free memory - اما با احتیاط
            if hasattr(self, '_series_cache'):
                self._series_cache.clear()
            if hasattr(self, '_series_name_cache'):
                self._series_name_cache.clear()
            if hasattr(self, '_viewer_batch_queue'):
                self._viewer_batch_queue.clear()

            self._render_batch_pending = False

            print("✅ cleanup_all_viewers completed")
        except Exception as e:
            self.logger.error(f"Error in cleanup_all_viewers: {e}")

    def _any_viewer_empty(self) -> bool:
        """Return True if any viewer has not been initialized with image data."""
        try:
            if not self.lst_nodes_viewer:
                return True
            for node in self.lst_nodes_viewer:
                vtk_widget = getattr(node, 'vtk_widget', None)
                if vtk_widget is None:
                    return True
                if getattr(vtk_widget, 'image_viewer', None) is None:
                    return True
                try:
                    if vtk_widget.get_count_of_slices() == 0:
                        return True
                except Exception:
                    return True
            return False
        except Exception:
            return True

    def _load_single_series_on_demand(self, series_number: int, study_path: str = None) -> bool:
        """
        Load a single series with correct path resolution
        """
        import time
        from pathlib import Path

        try:
            _start = time.time()

            # ✅ FIX: Use provided study_path or correctly determine it
            if study_path is None:
                # Try parent widget's import folder first
                if self.parent_widget.import_folder_path and Path(self.parent_widget.import_folder_path).exists():
                    # Ensure we're using the study root folder, not a series subfolder
                    study_path_obj = Path(self.parent_widget.import_folder_path)
                    # If current path points to a series folder (has DICOM parent), go up
                    if (study_path_obj / str(series_number)).exists():
                        pass  # Already at study level
                    else:
                        # Check if current path is inside a series folder
                        parent = study_path_obj.parent
                        if parent.exists() and (parent / str(series_number)).exists():
                            study_path_obj = parent
                    study_path = str(study_path_obj)
                else:
                    print(f"❌ No valid study path found")
                    return False

            print(f"📂 [LOAD] Loading series {series_number} from {study_path}")

            # Verify series folder exists
            series_folder = Path(study_path) / str(series_number)
            if not series_folder.exists():
                print(f"❌ Series folder not found: {series_folder}")
                return False

            # Check for DICOM files
            dicom_files = list(series_folder.glob("*.dcm")) + list(series_folder.glob("*.DCM"))
            if not dicom_files:
                print(f"❌ No DICOM files in {series_folder}")
                return False

            # Load series with correct path
            result = load_single_series_by_number(
                study_path=study_path,  # ✅ Pass correct study path, not series path
                series_number=series_number,
                patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                ordering_by_instances_number=self.parent_widget.ordering_by_instances_number,
            )

            if not result:
                return False

            # Process results
            for item in result:
                vtk_image_data, metadata, (patient_pk, study_pk) = item

                # Populate metadata_fixed if needed
                if not self.parent_widget.metadata_fixed or len(self.parent_widget.metadata_fixed) < 3:
                    if metadata and 'instances' in metadata and metadata['instances']:
                        first_instance_path = metadata['instances'][0].get('instance_path')
                        if first_instance_path and Path(first_instance_path).exists():
                            from PacsClient.pacs.patient_tab.utils.utils import get_meta_fixed
                            self.parent_widget.metadata_fixed = get_meta_fixed(first_instance_path)
                            if patient_pk:
                                self.parent_widget.metadata_fixed['patient_pk'] = patient_pk
                            if study_pk:
                                self.parent_widget.metadata_fixed['study_pk'] = study_pk

                # Add to thumbnails list
                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {
                    'vtk_image_data': vtk_image_data,
                    'metadata': metadata,
                    'file_path': file_path
                }
                self.parent_widget.add_new_data_to_lst_thumbnails_data(new_data)

                # Update study path if needed
                if metadata.get('series', {}).get('series_path'):
                    correct_path = Path(metadata['series']['series_path']).parent
                    if str(correct_path) != self.parent_widget.import_folder_path:
                        self.parent_widget.import_folder_path = str(correct_path)
                        print(f"   🔄 Updated study path to: {correct_path}")

            _elapsed = time.time() - _start
            print(f"✅ [LOAD] Series {series_number} loaded in {_elapsed:.3f}s")
            return True

        except Exception as e:
            print(f"❌ [LOAD] Error loading series {series_number}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _trigger_download_if_needed(self, series_number: str):
        """Trigger server download if series not available locally"""
        try:
            series_number = self.parent_widget.resolve_series_key(series_number)
            # Check if we have server info
            if hasattr(self.parent_widget, '_server_series_info') and self.parent_widget._server_series_info:
                if series_number in self.parent_widget._server_series_info:
                    print(f"   📥 Triggering server download for series {series_number}")
                    # Emit signal or call download method
                    if hasattr(self.parent_widget, 'series_downloaded'):
                        self.parent_widget.series_downloaded.emit(series_number)
                    return
            print(f"   ℹ️ No server info available for download")
        except Exception as e:
            print(f"   ⚠️ Error triggering download: {e}")

    def load_series_on_demand(self, series_number: str):
        """
        Load a series on demand with simple queue-based coordination
        Avoids async lock conflicts by using non-blocking async calls
        """
        try:
            # Check if widget is still valid
            try:
                if not self.parent_widget.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            series_number_str = self.parent_widget.resolve_series_key(series_number)

            # Avoid duplicate loads
            if series_number_str in getattr(self.parent_widget, '_pending_series_loads', set()):
                self.logger.debug(f"Series {series_number_str} already queued for loading")
                return

            # Check if already loaded
            series_key = f"series_{series_number_str}"
            if series_key in self.parent_widget.lst_series_name:
                self.logger.debug(f"Series {series_number_str} already loaded, skipping")
                return

            # Mark as pending
            if not hasattr(self.parent_widget, '_pending_series_loads'):
                self.parent_widget._pending_series_loads = set()
            self.parent_widget._pending_series_loads.add(series_number_str)

            # Try async loading if event loop available
            try:
                loop = asyncio.get_running_loop()

                # Store the event loop reference for cleanup
                self.parent_widget._event_loop = loop

                async def _safe_async_load():
                    """Load series asynchronously without locks"""
                    try:
                        # Yield immediately to prevent blocking
                        await asyncio.sleep(0)

                        # Load and display the series
                        await self._async_load_and_display_series(series_number_str)

                    except asyncio.CancelledError:
                        self.logger.debug(f"Load cancelled for series {series_number_str}")
                    except RuntimeError as e:
                        if "deleted" not in str(e).lower():
                            self.logger.warning(f"Runtime error loading series {series_number_str}: {e}")
                    except Exception as e:
                        self.logger.error(f"Error loading series {series_number_str}: {e}", exc_info=True)
                    finally:
                        # Remove from pending set
                        if hasattr(self.parent_widget, '_pending_series_loads'):
                            self.parent_widget._pending_series_loads.discard(series_number_str)

                # Create task - no locks, just schedule it
                task = asyncio.create_task(_safe_async_load())
                self.parent_widget._background_tasks.add(task)

                # Cleanup on completion
                def cleanup_task(t):
                    try:
                        self.parent_widget._background_tasks.discard(t)
                    except:
                        pass  # Ignore errors during cleanup

                task.add_done_callback(cleanup_task)

            except RuntimeError:
                # No event loop - use thread-based loading
                self.logger.debug(f"No event loop, loading series {series_number_str} in thread")

                def _thread_load():
                    try:
                        # Load synchronously in thread
                        self._load_single_series_on_demand(int(series_number_str))
                    except Exception as e:
                        self.logger.error(f"Error loading series in thread: {e}", exc_info=True)
                    finally:
                        if hasattr(self.parent_widget, '_pending_series_loads'):
                            self.parent_widget._pending_series_loads.discard(series_number_str)

                thread = threading.Thread(target=_thread_load, daemon=True, name=f"SeriesLoad-{series_number_str}")
                thread.start()

        except Exception as e:
            self.logger.error(f"Error in load_series_on_demand: {e}", exc_info=True)
            if hasattr(self.parent_widget, '_pending_series_loads'):
                self.parent_widget._pending_series_loads.discard(series_number_str)

    async def _async_load_and_display_series(self, series_number: str):
        """
        ⚡ OPTIMIZED: Async series loading without unnecessary sleeps.
        
        Performance improvements:
        - Removed artificial asyncio.sleep(0) calls
        - Direct async thread execution
        - Immediate result handling
        """
        try:
            # Validate widget state (no sleep delay)
            try:
                if not self.parent_widget.isVisible():
                    return
            except RuntimeError:
                return  # Widget was deleted

            # Parse series identifier (no sleep delay)
            try:
                series_int = int(series_number)
            except ValueError:
                # Search for series by UID in loaded data
                for idx, thumb_data in enumerate(self.parent_widget.lst_thumbnails_data):
                    series_uid = thumb_data.get('metadata', {}).get('series', {}).get('series_uid', '')
                    if series_uid == series_number:
                        series_int = idx + 1
                        break
                else:
                    self.logger.warning(f"Series {series_number} not found")
                    return

            # ⚡ OPTIMIZED: Use executor immediately without sleep
            try:
                success = await asyncio.to_thread(
                    self._load_single_series_on_demand,
                    series_int
                )
            except AttributeError:
                # Fallback for Python < 3.9
                loop = asyncio.get_event_loop()
                success = await loop.run_in_executor(
                    None,
                    self._load_single_series_on_demand,
                    series_int
                )

            if success:
                # Mark as ready immediately
                self._display_series_after_load(str(series_number))
        
        except asyncio.CancelledError:
            self.logger.debug(f"Load cancelled for series {series_number}")
            raise
        except Exception as e:
            self.logger.error(f"Error loading series {series_number}: {e}", exc_info=True)

    def _display_series_after_load(self, series_number: str):
        """
        Mark series ready; for the first downloaded series, display it in all viewers
        and hide loading.
        """
        try:
            # Validate widget state
            if not self.parent_widget.isVisible():
                return

            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(series_number):
                    self._mark_first_series_displayed()
                    return

            # Mark as ready in thumbnail manager
            if hasattr(self.parent_widget, 'thumbnail_manager') and self.parent_widget.thumbnail_manager:
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_number))
                self.parent_widget.thumbnail_manager.apply_border_states_new()
                self.logger.debug(f"Series {series_number} marked as ready")
        except RuntimeError as e:
            if "deleted" not in str(e).lower():
                self.logger.error(f"Runtime error in _display_series_after_load: {e}")
        except Exception as e:
            self.logger.error(f"Error in _display_series_after_load: {e}", exc_info=True)
            traceback.print_exc()

    def _ensure_loading_dialog(self):
        if getattr(self.parent_widget, "_loading_dlg", None) is not None:
            return

        dlg = QProgressDialog("Processing...", None, 0, 0, self.parent_widget,
                              flags=Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.MSWindowsFixedSizeDialogHint)
        dlg.setWindowTitle("Please wait")
        dlg.setWindowModality(Qt.NonModal)  # فقط پیام؛ UI قفل نشه
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setCancelButton(None)
        dlg.setMinimumDuration(0)
        dlg.resize(420, 120)

        # 🎨 استایل تیره و مینیمال
        dlg.setStyleSheet("""
            QProgressDialog {
                background: #0b1220;
                border: 1px solid #223046;
                border-radius: 12px;
                color: #e5e7eb;
            }
            QProgressDialog QLabel {
                color: #e5e7eb;
                font-family: 'Segoe UI', 'Roboto';
                font-size: 14px;
                font-weight: 600;
                padding: 10px 14px;
                border: none;
                background: transparent;
            }
            /* ProgressBar مارکوی نرمِ نامشخص */
            QProgressBar {
                border: 1px solid #2b3b55;
                border-radius: 8px;
                background: #0f172a;
                height: 14px;
                text-align: center;
                color: #94a3b8;
                padding: 0px;
                margin: 0 14px 14px 14px;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                             stop:0 #38bdf8, stop:1 #60a5fa);
            }
        """)

        # جای‌گذاری وسطِ پنل مرکزی اگر موجود بود
        try:
            parent_widget = getattr(self.parent_widget, "right_panel", None) or self.parent_widget
            g = parent_widget.frameGeometry()
            dlg.move(g.center() - dlg.rect().center())
        except Exception:
            pass

        self.parent_widget._loading_dlg = dlg
        self.parent_widget._loading_cnt = 0

    def _show_loading_msg(self, text="Applying layout..."):
        # COMMENTED OUT TO AVOID SHOWING LOADING MESSAGE TO USER
        # self._ensure_loading_dialog()
        # self.parent_widget._loading_cnt += 1
        # # یک متن دوستانه با ایموجی تک‌رنگ (روی تم تیره خوب دیده می‌شود)
        # pretty = f"⚙️  {text}\nThis may take a few seconds…"
        # self.parent_widget._loading_dlg.setLabelText(pretty)
        # self.parent_widget._loading_dlg.setRange(0, 0)  # حالت نامشخص (اسپینینگ)
        # self.parent_widget._loading_dlg.show()
        # self.parent_widget._loading_dlg.raise_()

        # center = QApplication.primaryScreen().availableGeometry().center()
        # self.parent_widget._loading_dlg.move(center - self.parent_widget._loading_dlg.rect().center())

        # QApplication.processEvents()
        pass  # Do nothing to avoid showing loading message to user

    def _hide_loading_msg(self):
        # COMMENTED OUT TO MATCH _show_loading_msg BEING DISABLED
        # if getattr(self.parent_widget, "_loading_dlg", None) is None:
        #     return
        # self.parent_widget._loading_cnt = max(0, self.parent_widget._loading_cnt - 1)
        # if self.parent_widget._loading_cnt == 0:
        #     self.parent_widget._loading_dlg.hide()
        #     QApplication.processEvents()
        pass  # Do nothing to match _show_loading_msg being disabled

    def _get_default_layout_from_config(self) -> tuple[int, int]:
        """Read default layout from modality_grid.json (fallback 1x2)."""
        try:
            if GRID_CONFIG_PATH.exists():
                with open(GRID_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                default_cfg = data.get('default') or data.get('DEFAULT')
                if isinstance(default_cfg, dict):
                    rows = int(default_cfg.get('rows', 1))
                    cols = int(default_cfg.get('cols', 2))
                    return (rows, cols)
        except Exception:
            pass
        return (1, 2)

    def _load_first_series_sync(self, size_init_viewers):
        """Load first series synchronously when no event loop is available"""
        try:
            from PacsClient.pacs.patient_tab.utils import load_images

            print("📂 [SYNC_LOAD] Loading first series synchronously...") # لاگ اضافه شده

            first_series_loaded = False
            for vtk_image_data, metadata, patient_info in load_images(
                    self.parent_widget.import_folder_path,
                    patient_pk=self.parent_widget.metadata_fixed.get('patient_pk', None),
                    study_pk=self.parent_widget.metadata_fixed.get('study_pk', None),
                    ordering_by_instances_number=self.parent_widget.ordering_by_instances_number
            ):
                # ✅ FLICKER FIX: Only process events if not in initialization batch
                if self.parent_widget.updatesEnabled():
                    from PySide6.QtWidgets import QApplication
                    QApplication.processEvents()

                self.parent_widget.check_and_add_meta_fixed(patient_info)

                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {'vtk_image_data': vtk_image_data, 'metadata': metadata, 'file_path': file_path}

                self.parent_widget.add_new_data_to_lst_thumbnails_data(new_data)

                if not first_series_loaded:
                    optimal_layout = self.parent_widget.get_optimal_layout_for_series(metadata)
                    print(f"✅ [SYNC_LOAD] Determined optimal layout: {optimal_layout}") # لاگ اضافه شده

                    # ⚡ OPTIMIZATION: Removed processEvents() - use batch update instead
                    # Use synchronous viewer creation
                    self._apply_multi_viewer_sync(optimal_layout) # این تابع ویوورها را تنظیم می کند

                    first_series_loaded = True
                    self._hide_loading_spinner()

                    series_no = metadata['series']['series_number']
                    if (not self._first_series_displayed) or self._any_viewer_empty():
                        self._display_first_series_in_all_viewers(str(series_no))
                    self.parent_widget.thumbnail_manager.set_series_ready(str(series_no))

                    if file_path and not self.parent_widget.logo_patient:
                        self.parent_widget.logo_patient = file_path
                        self.parent_widget.update_tab_manager()

                    print(f"✅ [SYNC_LOAD] First series loaded: {series_no}. Breaking loop.") # لاگ اضافه شده
                    break  # فقط اولین سری را بارگذاری کن

        except Exception as e:
            print(f"❌ [SYNC_LOAD] Error loading first series sync: {e}") # لاگ اضافه شده
            import traceback
            traceback.print_exc()

    def _apply_multi_viewer_sync(self, numbers):
        """⚡ Optimized: Synchronous viewer layout without processEvents delays"""
        try:
            number_of_row, number_of_column = int(numbers[0]), int(numbers[1])

            # Cleanup old viewers
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()

            # Create new viewers
            count = number_of_row * number_of_column
            self.create_some_viewers(count)

            # Apply layout
            if (number_of_row, number_of_column) == (1, 1) and len(self.lst_nodes_viewer) > 0:
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.parent_widget.change_container_border(0)
            elif (number_of_row, number_of_column) == (2, 1) and len(self.lst_nodes_viewer) >= 2:
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 1, 0)
                self.parent_widget.change_container_border(0)
            elif (number_of_row, number_of_column) == (1, 2) and len(self.lst_nodes_viewer) >= 2:
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[0].widget, 0, 0)
                self.parent_widget.vtk_layout.addWidget(self.lst_nodes_viewer[1].widget, 0, 1)
                self.parent_widget.change_container_border(0)

            # ⚡ OPTIMIZATION: Removed processEvents() call - introduces unwanted delay

        except Exception as e:
            print(f"❌ Error applying viewer layout sync: {e}")
            import traceback
            traceback.print_exc()

    def load_first_series_only(self, folder_path, series_number):
        """
        Load only the first series when it's downloaded
        بارگذاری فقط اولین سری وقتی دانلود شد

        This method is called by home_ui when the first series download completes.

        Args:
            folder_path: Path to the study folder
            series_number: The series number that was downloaded
        """
        try:
            print(f"🎯 load_first_series_only called: series {series_number}")

            # Update folder path if needed
            if folder_path and folder_path != self.parent_widget.import_folder_path:
                self.parent_widget.import_folder_path = folder_path

            # Check if we already have this series loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded")
                return

            # Load the series
            try:
                success = self._load_single_series_on_demand(int(series_number))

                if success:
                    self.parent_widget.lst_series_name.add(series_key)
                    print(f"✅ Series {series_number} loaded successfully")

                    # Display in viewer if it's the first series
                    if len(self.parent_widget.lst_series_name) == 1:
                        self._display_first_series_in_viewer()

                        # Hide any loading spinner
                        self._hide_loading_spinner()
                else:
                    print(f"⚠️ Failed to load series {series_number}")

            except Exception as load_error:
                print(f"❌ Error loading series {series_number}: {load_error}")

        except Exception as e:
            print(f"❌ Error in load_first_series_only: {e}")
            import traceback
            traceback.print_exc()

    def load_series_immediately(self, series_number: str, series_dir: str):
        """
        Load a series immediately after download and display it automatically.

        Args:
            series_number: Can be either a simple series number (e.g., "1", "2")
                          or a Series Instance UID (e.g., "1.3.12.2.1107...")
            series_dir: Directory containing the series DICOM files
        """
        try:
            print(f"{'='*80}")
            print(f"📥 [PRIORITY LOAD] Loading series {series_number} (auto-display)")
            print(f"📁 Directory: {series_dir}")
            print(f"{'='*80}")

            # Update folder path if needed
            if series_dir and series_dir != self.parent_widget.import_folder_path:
                self.parent_widget.import_folder_path = series_dir

            # Check DICOM files
            from pathlib import Path
            series_path = Path(series_dir)
            dicom_files = list(series_path.glob("*.dcm"))
            if not dicom_files:
                print(f"❌ No DICOM files found in {series_dir}")
                return

            # Skip if already loaded
            series_key = f"series_{series_number}"
            if series_key in self.parent_widget.lst_series_name:
                print(f"⏭️ Series {series_number} already loaded")
                return

            # ✅ FIX: Handle both series numbers and Series Instance UIDs
            try:
                series_int = int(series_number)
            except ValueError:
                # Not a simple number - extract series number from directory name
                # Directory name should be the actual series number
                try:
                    series_int = int(series_path.name)
                    print(f"   🔍 Extracted series number {series_int} from directory name")
                except ValueError:
                    print(f"❌ Cannot determine series number from UID {series_number} or directory {series_path.name}")
                    return

            # Load the series
            success = self._load_single_series_on_demand(series_int)
            if not success:
                print(f"❌ Failed to load series {series_int}")
                return

            # Auto-display in viewers
            if (not self._first_series_displayed) or self._any_viewer_empty():
                if self._display_first_series_in_all_viewers(str(series_int)):
                    self._mark_first_series_displayed()
            else:
                self.parent_widget.change_series_on_viewer(series_int, flag_change_selected_widget=True)

            # Mark as ready
            if hasattr(self.parent_widget, 'thumbnail_manager'):
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_number))
                self.parent_widget.thumbnail_manager.apply_border_states_new()

            print(f"✅ Series {series_int} loaded and displayed.")
        except Exception as e:
            print(f"❌ CRITICAL ERROR in load_series_immediately: {e}")
            import traceback
            traceback.print_exc()

    def _trigger_priority_display(self, series_key):
        """Trigger first-series display only; later series stay ready until user clicks."""
        try:
            series_key = self.parent_widget.resolve_series_key(series_key)

            # Only auto-display the very first series
            if not self._first_series_displayed:
                self.load_series_on_demand(series_key)
                return

            # For subsequent series, just mark ready (no auto-switch)
            if hasattr(self.parent_widget, 'thumbnail_manager') and self.parent_widget.thumbnail_manager:
                self.parent_widget.thumbnail_manager.set_series_ready(str(series_key))
                self.parent_widget.thumbnail_manager.apply_border_states_new()
        except Exception as e:
            print(f"? Error triggering priority display: {e}")

    def _distribute_series_to_viewers(self):
        """
        ⚡ OPTIMIZED: Distribute series to viewers with efficient tracking.
        
        Improvements:
        - Uses set-based deduplication instead of nested loops
        - Single pass through viewers
        - O(n) instead of O(n²)
        """
        if not self.parent_widget.lst_thumbnails_data or not self.lst_nodes_viewer:
            return

        try:
            # Track which series are already displayed (O(1) lookup)
            displayed_series = set()
            series_queue = list(range(len(self.parent_widget.lst_thumbnails_data)))
            
            for viewer_idx, node_viewer in enumerate(self.lst_nodes_viewer):
                # Check if viewer already has data
                if hasattr(node_viewer.vtk_widget, 'last_series_show') and node_viewer.vtk_widget.last_series_show is not None:
                    displayed_series.add(node_viewer.vtk_widget.last_series_show)
                    continue
                
                # ⚡ FAST: Find first undisplayed series
                series_idx = None
                for idx in series_queue:
                    if idx not in displayed_series:
                        series_idx = idx
                        break
                
                if series_idx is None and series_queue:
                    series_idx = series_queue[0]  # Reuse first if all claimed
                
                if series_idx is not None:
                    series_data = self.parent_widget.lst_thumbnails_data[series_idx]
                    series_num = series_data['metadata']['series']['series_number']
                    displayed_series.add(series_num)
                    
                    # Display without redundant checks
                    if hasattr(node_viewer, 'vtk_widget'):
                        flag_switch = node_viewer.vtk_widget.switch_series(
                            series_data['vtk_image_data'],
                            series_data['metadata'],
                            series_idx,
                            metadata_fixed=self.parent_widget.metadata_fixed
                        )
                        
                        if flag_switch and viewer_idx == 0:
                            self.set_viewer_to_main_viewer(node_viewer)
                        
                        if flag_switch and hasattr(node_viewer, 'slider'):
                            self.parent_widget.reset_slider(node_viewer.vtk_widget, node_viewer.slider)
                            if node_viewer.vtk_widget.image_viewer:
                                node_viewer.vtk_widget.image_viewer.update_corners_actors()
        
        except Exception as e:
            self.logger.error(f"Error distributing series: {e}", exc_info=True)
            print(f"❌ [DISTRIBUTE] Error distributing series to viewers: {e}")
            import traceback
            traceback.print_exc()

        # Hide loading spinner
        if hasattr(node_viewer.vtk_widget, 'viewport_spinner'):
            node_viewer.vtk_widget.viewport_spinner.hide_loading()

        # Update UI
        node_viewer.vtk_widget.show()
        node_viewer.vtk_widget.update()
        node_viewer.widget.show()
        node_viewer.widget.update()

        if node_viewer.vtk_widget.image_viewer:
            node_viewer.vtk_widget.image_viewer.Render()
            node_viewer.vtk_widget.render_window.Render()
            node_viewer.vtk_widget.GetRenderWindow().Render()

        print(f"   ✅ Viewer {viewer_idx} populated successfully")