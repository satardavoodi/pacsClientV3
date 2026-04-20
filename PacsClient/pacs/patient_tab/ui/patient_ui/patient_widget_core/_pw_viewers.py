"""
Viewer creation, layout, slider, VTK widget management.

Extracted from patient_widget.py during Phase 1 refactoring (v2.2.9.1).
This is a mixin class — do NOT instantiate directly.
"""

import json
import logging as _logging
import traceback
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QLabel, QProgressDialog, QSlider, QWidget
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer

# Redirect print() to logger to avoid synchronous console I/O on Windows.
_print_logger = _logging.getLogger(__name__)
def print(*args, **_kw):  # noqa: A001
    _print_logger.debug(' '.join(str(a) for a in args))


class _PWViewersMixin:
    """Viewer creation, layout, slider, VTK widget management."""

    def new_viewer(self, default_thumb_index=0):
        # Delegate to viewer controller
        return self.viewer_controller.new_viewer(default_thumb_index)

        # slider.setStyleSheet("""
        #     QSlider {
        #         background: rgba(0, 0, 0, 1);
        #         border-radius: 0px;
        #         border: none;
        #         padding-top: 50px;   /* فاصله داخل اسلایدر از بالا */
        #         padding-bottom: 50px;  /* فاصله داخل اسلایدر از پایین */
        #     }
        # """)
        pass
        
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
            container.setStyleSheet(self.viewer_controller._viewport_container_styles(active=False))
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
            
            # ✅ CRITICAL: Block signals during slider setup to prevent image number flickering
            slider.blockSignals(True)
            
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
        finally:
            # ✅ CRITICAL: Unblock signals after all slider configuration is complete
            slider.blockSignals(False)

        # Connect signals
        try:
            print("   🔗 Connecting slider signal...")
            self.on_slider_value_changed(vtk_widget, mid_slices)
            slider.valueChanged.connect(lambda val: self.on_slider_value_changed(vtk_widget, val))
            print("   ✅ Slider connected")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not connect slider signal: {e}")
            self.logger.warning(f"Warning connecting slider signal: {e}")

        # Set VTK widget methods
        try:
            print("   🔧 Setting VTK widget methods...")
            if hasattr(vtk_widget, 'set_method_change_series_on_drop'):
                vtk_widget.set_method_change_series_on_drop(self.change_series_on_viewer)
            if hasattr(vtk_widget, 'set_method_change_container_border'):
                vtk_widget.set_method_change_container_border(self.change_container_border)
            print("   ✅ Methods set")
        except Exception as e:
            print(f"   ⚠️ Warning: Could not set VTK widget methods: {e}")
            self.logger.warning(f"Warning setting VTK widget methods: {e}")
        
        print(f"🔨 [new_viewer] END - Successfully created viewer with ID {viewer_index}")
        print(f"{'='*80}\n")
        return new_node

    def _process_events_safe(self, label: str):
        """Process events only when safe, preventing nested calls and excessive processing
        
        ✅ FLICKER FIX: Now checks if updates are disabled before processing events
        """
        # Skip if UI updates are disabled (batch operation in progress)
        if not self.updatesEnabled():
            print(f"   ⏭️ Skipping processEvents ({label}) - updates disabled for batch operation")
            return
            
        self._critical_sections_running += 1
        if self._critical_sections_running <= 1:  # More conservative: only process if not nested at all
            try:
                print(f"   ⏳ Processing events {label}...")
                QApplication.processEvents()
                print(f"   ✅ Events processed")
            except Exception as e:
                print(f"   ❌ ERROR processing events: {e}")
        else:
            print(f"   ⏭️ Skipping processEvents ({label}) - nested call ({self._critical_sections_running})")
        self._critical_sections_running -= 1

    def _create_lightweight_vtk_placeholder(self):
        """Create a lightweight VTK widget that defers rendering until data is loaded
        
        ✅ FLICKER FIX: This creates a VTK widget with minimal initialization
        to avoid the black screen flicker while maintaining all required methods
        """
        try:
            height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
            vtk_widget = VTKWidget(height_viewer=height, patient_widget=self)
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

    def change_container_border(self, id_vtk_widget):
        # Delegate to viewer controller
        self.viewer_controller.change_container_border(id_vtk_widget)

    def creator_vtk_widget(self):
        try:
            height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
            return VTKWidget(height_viewer=height, patient_widget=self)
        except Exception as e:
            print(f"❌ Error in creator_vtk_widget: {e}")
            self.logger.error(f"Error in creator_vtk_widget: {e}", exc_info=True)
            return None

    def create_new_vtk_widget(self, default_thumb_index):
        """Create a new VTK widget with series data, with comprehensive error handling"""
        try:
            # Check if lst_thumbnails_data exists and has sufficient data
            if not hasattr(self, 'lst_thumbnails_data') or not self.lst_thumbnails_data or len(self.lst_thumbnails_data) <= default_thumb_index:
                print(f"⚠️ [create_new_vtk_widget] No thumbnail data at index {default_thumb_index}, using dummy")
                return self.create_dummy_vtk_widget()

            # Extract data safely
            try:
                thumbnail_item = self.lst_thumbnails_data[default_thumb_index]
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
                for i in range(len(self.lst_thumbnails_data)):
                    if i == default_thumb_index:
                        continue

                    try:
                        item = self.lst_thumbnails_data[i]
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
                        metadata_fixed=self.metadata_fixed if hasattr(self, 'metadata_fixed') else {})
                else:
                    vtk_widget.start_process_series(
                        vtk_image_data=vtk_widget_data, metadata=metadata, series_index=series_number,
                        id_vtk_widget=id_new_vtk_widget, metadata_fixed=self.metadata_fixed if hasattr(self, 'metadata_fixed') else {})
                        
                return vtk_widget
                
            except Exception as e:
                print(f"❌ [create_new_vtk_widget] Error processing series: {e}")
                self.logger.error(f"Error processing series: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()
                
        except Exception as e:
            print(f"❌ [create_new_vtk_widget] Unexpected error: {e}")
            self.logger.error(f"Unexpected error in create_new_vtk_widget: {e}", exc_info=True)
            return self.create_dummy_vtk_widget()

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        # Delegate to viewer controller
        self.viewer_controller.set_viewer_to_main_viewer(node_viewer)

    def _get_default_layout_from_config(self, modality: str = None) -> tuple[int, int]:
        """Read default layout from modality_grid.json based on modality (fallback to default then 1x2).
        
        Args:
            modality: Optional modality string (e.g., 'CT', 'MR'). If provided, tries to find
                     modality-specific layout first.
        
        Returns:
            tuple: (rows, cols) for viewer grid layout
        """
        return self.viewer_controller._get_default_layout_from_config(modality=modality)

    def reset_slider(self, vtk_widget: VTKWidget, slider: QSlider):
        """Delegate to viewer controller"""
        # This method is still needed as it's used by the viewer controller
        if not vtk_widget or not slider:
            return

        try:
            # ✅ CRITICAL: Block signals DURING the entire slider update to prevent image number flickering
            slider.blockSignals(True)

            vtk_widget.set_slider(slider)
            count_slices = vtk_widget.get_count_of_slices()
            qt_bridge_active = bool(getattr(vtk_widget, '_qt_bridge_active', False))
            mid_slices = 0  # Default to first slice for legacy/VTK path
            if qt_bridge_active and getattr(vtk_widget, 'image_viewer', None) is not None:
                try:
                    # FAST/Qt switch path already rendered the preferred slice.
                    # Reuse that slice instead of forcing a second render to 0.
                    mid_slices = max(0, int(vtk_widget.image_viewer.GetSlice()))
                except Exception:
                    mid_slices = 0
            last_slices = max(0, count_slices - 1)

            # ✅ Set range and value WHILE signals are blocked
            # NOTE: Do NOT return early for count_slices <= 1. The slider
            # must always have its range set so that stale max=0 from a
            # previous placeholder state is cleared.  Expensive per-slice
            # operations (on_slider_value_changed, apply_default_window_level)
            # are still skipped for single-slice series.
            if slider.minimum() != 0 or slider.maximum() != last_slices:
                slider.setRange(0, last_slices)
            if slider.value() != mid_slices:
                slider.setValue(mid_slices)

            # ✅ CRITICAL: Unblock signals AFTER all slider updates are complete
            slider.blockSignals(False)

            if count_slices <= 1:
                return

            # FAST/Qt bridge already applied window/level and rendered the
            # target slice inside switch_series/start_qt_viewer. Replaying the
            # slider callback here forces an immediate second set_slice() on the
            # UI thread (observed as a ~37ms tax in series-switch logs).
            if qt_bridge_active:
                return

            # ✅ Now manually trigger the value changed handler with the correct value
            # This ensures image number display is updated with the final value
            self.on_slider_value_changed(vtk_widget, mid_slices)

            if hasattr(vtk_widget, 'image_viewer') and vtk_widget.image_viewer is not None:
                vtk_widget.image_viewer.apply_default_window_level(mid_slices)
        except Exception as e:
            slider.blockSignals(False)
            print(f"⚠️ Error in reset_slider: {e}")

    def on_slider_value_changed(self, vtk_widget, value):
        """Optimized slider value change handler.

        v2.2.3.3.6: Removed the redundant _schedule_reference_line_update()
        call.  VTKWidget.set_slice() already calls it internally (added in
        v2.2.3.3.3).  The duplicate was harmless (throttle absorbed it) but
        added unnecessary hasattr / timer-check overhead per slider tick.
        """
        if vtk_widget and hasattr(vtk_widget, 'set_slice'):
            vtk_widget.set_slice(value)

    def _ensure_loading_dialog(self):
        if getattr(self, "_loading_dlg", None) is not None:
            return

        dlg = QProgressDialog("Processing...", None, 0, 0, self,
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
            parent_widget = getattr(self, "right_panel", None) or self
            g = parent_widget.frameGeometry()
            dlg.move(g.center() - dlg.rect().center())
        except Exception:
            pass

        self._loading_dlg = dlg
        self._loading_cnt = 0

    def _show_loading_msg(self, text="Applying layout..."):
        # COMMENTED OUT TO AVOID SHOWING LOADING MESSAGE TO USER
        # self._ensure_loading_dialog()
        # self._loading_cnt += 1
        # # یک متن دوستانه با ایموجی تک‌رنگ (روی تم تیره خوب دیده می‌شود)
        # pretty = f"⚙️  {text}\nThis may take a few seconds…"
        # self._loading_dlg.setLabelText(pretty)
        # self._loading_dlg.setRange(0, 0)  # حالت نامشخص (اسپینینگ)
        # self._loading_dlg.show()
        # self._loading_dlg.raise_()

        # center = QApplication.primaryScreen().availableGeometry().center()
        # self._loading_dlg.move(center - self._loading_dlg.rect().center())

        # QApplication.processEvents()
        pass  # Do nothing to avoid showing loading message to user

    def _hide_loading_msg(self):
        # COMMENTED OUT TO MATCH _show_loading_msg BEING DISABLED
        # if getattr(self, "_loading_dlg", None) is None:
        #     return
        # self._loading_cnt = max(0, self._loading_cnt - 1)
        # if self._loading_cnt == 0:
        #     self._loading_dlg.hide()
        #     QApplication.processEvents()
        pass  # Do nothing to match _show_loading_msg being disabled

    def apply_multi_viewer(self, numbers, modify_by_user=False):
        """
        Apply multi-viewer layout with optimized batch processing
        Reuses existing data and caches when possible
        """
        # Delegate to viewer controller
        self.viewer_controller.apply_multi_viewer(numbers, modify_by_user)

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

    def safe_reset_for_layout_switch(self, vtk_image_data=None, metadata=None):
        """
        Safe reset specifically for layout switches - preserves camera if possible
        """
        try:
            if self.image_viewer is None:
                # Fresh initialization needed
                if vtk_image_data and metadata:
                    self.start_process_series(vtk_image_data, metadata, 
                                            metadata['series']['series_number'],
                                            self.id_vtk_widget or 0, {})
                return
                
            # Reuse existing viewer with new data
            if vtk_image_data and metadata:
                self.image_viewer.reset_image_viewer(vtk_image_data, metadata)
                self.image_viewer.apply_default_window_level(self.image_viewer.GetSlice())
                self.last_series_show = metadata['series']['series_number']
                self.Render()
                
        except Exception as e:
            print(f"⚠️ Safe reset failed: {e}")
            # Fallback to full recreation
            self.cleanup_image_viewer()
            if vtk_image_data and metadata:
                self.start_process_series(vtk_image_data, metadata,
                                        metadata['series']['series_number'],
                                        self.id_vtk_widget or 0, {})

    def _create_viewers_batch(self, count: int):
        """
        Create multiple viewers efficiently in batch
        بیشتر سریع از single creation
        
        ✅ FLICKER FIX: Removed processEvents during batch creation
        """
        created = []
        try:
            # ✅ FLICKER FIX: Disable updates during batch
            self.setUpdatesEnabled(False)
            
            for i in range(count):
                # Skip event processing for internal batch operations
                viewer = self.new_viewer(i % max(1, len(self.lst_thumbnails_data)))
                created.append(viewer)
                # ✅ FLICKER FIX: No processEvents during batch - prevents flicker
            
            return created
        except Exception as e:
            print(f"❌ Error in batch viewer creation: {e}")
            traceback.print_exc()
            return created
        finally:
            # ✅ FLICKER FIX: Re-enable updates after batch
            self.setUpdatesEnabled(True)

    def create_some_viewers(self, count):
        # Delegate to viewer controller
        self.viewer_controller.create_some_viewers(count)

    def cleanup_all_viewers(self):
        """Delegate to viewer controller"""
        self.viewer_controller.cleanup_all_viewers()

    def init_matrix_viewers(self, numbers=None):
        if numbers is not None:
            # set default-interactorstyle when app started
            self.apply_multi_viewer(numbers)
            if self.viewer_controller.selected_widget:
                self.toolbar_manager.current_style = self.viewer_controller.selected_widget.style

        else:
            # create dummy image for show until image downloaded.
            dummy_vtk_widget = self.viewer_controller.create_dummy_vtk_widget()
            self.vtk_layout.addWidget(dummy_vtk_widget, 0, 0)

