"""
Viewer layout mixin for ViewerController.
Multi-viewer grid creation, vtk-widget factory, layout application.
"""
from __future__ import annotations
import copy
from functools import partial
import os
import threading
import time
import gc
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel,
    QSizePolicy, QFrame, QApplication, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget
from PacsClient.pacs.patient_tab.ui.patient_ui._slice_tick_slider import SliceTickSlider
from PacsClient.utils.series_pairing import can_pair_series_names
from PacsClient.pacs.patient_tab.utils import NodeViewer
from modules.viewer.viewer_backend_config import BACKEND_VTK, BACKEND_PYDICOM, BACKEND_PYDICOM_QT
import logging

logger = logging.getLogger(__name__)


class _VCLayoutMixin:
    """Auto-split mixin — see patient_widget_viewer_controller.py for history."""

    @staticmethod
    def _viewport_container_styles(active: bool, previous: bool = False) -> str:
        """Border + tint for the per-viewport container frame.

        Study origin drives the color: a viewport showing a PREVIOUS exam (a prior
        study of the same real person) gets a RED border (solid when active, dim
        when inactive); the current/main exam keeps the default BLUE accent border
        (theme `accent`, default sky-blue). This mirrors the series-thumbnail
        origin coloring so a prior study reads as red in the viewport too.

        Imported lazily so this static method doesn't pay the
        theme-manager import cost on module load.
        """
        if previous:
            # Previous-exam viewport — red (active solid, inactive dim).
            if active:
                return """
                    QFrame#ViewportContainer {
                        border: 2px solid #ef4444;
                        border-radius: 4px;
                        background-color: rgba(239, 68, 68, 0.10);
                    }
                """
            return """
                QFrame#ViewportContainer {
                    border: 2px solid rgba(239, 68, 68, 0.55);
                    border-radius: 4px;
                    background-color: rgba(239, 68, 68, 0.04);
                }
            """
        try:
            from PacsClient.utils.theme_manager import get_theme_manager
            from PySide6.QtGui import QColor as _QColor
            theme = get_theme_manager().current_theme()
            accent_hex = theme.get("accent", "#60a5fa")
            qc = _QColor(accent_hex)
            if not qc.isValid():
                qc = _QColor("#60a5fa")
            r, g, b = qc.red(), qc.green(), qc.blue()
            active_tint = f"rgba({r}, {g}, {b}, 0.08)"
        except Exception:
            accent_hex = "#60a5fa"
            active_tint = "rgba(96, 165, 250, 0.08)"

        if active:
            return f"""
                QFrame#ViewportContainer {{
                    border: 2px solid {accent_hex};
                    border-radius: 4px;
                    background-color: {active_tint};
                }}
            """
        return """
            QFrame#ViewportContainer {
                border: 2px solid rgba(156, 163, 175, 0.72);
                border-radius: 4px;
                background-color: rgba(15, 23, 42, 0.03);
            }
        """

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

            self._current_layout = (rows, cols)

            logger.debug(f"ًں”§ [LAYOUT] Applying {rows}x{cols} layout (need {required_count} viewers, have {current_count})")

            # âœ… FLICKER FIX: Disable updates during batch viewer creation
            self.parent_widget.setUpdatesEnabled(False)
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(False)

            # 1. Cleanup existing viewers but preserve data
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            print("   âœ… cleanup_all_viewers completed")  # No processEvents here

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
                    logger.error(f"   âڑ ï¸ڈ Error creating viewer {i}: {e}")
                    # Create fallback viewer
                    node = self._create_fallback_viewer()
                    # _create_fallback_viewer doesn't append; add it here
                    if node is not None:
                        self.lst_nodes_viewer.append(node)

                if node is None:
                    logger.debug(f"   âڑ ï¸ڈ Viewer {i} is None after creation/fallback, skipping slot")
                    continue

                # NOTE: new_viewer() already appends to lst_nodes_viewer internally.
                # Do NOT append again here — double-append causes duplicate entries
                # that open as orphan popup windows (they never get parented via addWidget).

                # v2.2.3.2.7: Yield to Qt event loop between viewer creations.
                # On software OpenGL each VTK widget creation takes 5-15s.
                # Without this yield, scroll events and timers starve for
                # the entire creation loop (10-60s for 2-4 viewers).
                # setUpdatesEnabled(False) is still active so no flicker.
                if i < required_count - 1:
                    try:
                        from PySide6.QtWidgets import QApplication
                        QApplication.processEvents()
                    except Exception:
                        pass

            # 3. Arrange in grid
            for i, node in enumerate(self.lst_nodes_viewer):
                if i >= required_count:
                    break
                if node is None or getattr(node, 'widget', None) is None:
                    logger.debug(f"   âڑ ï¸ڈ Layout skip: node[{i}] is invalid")
                    continue
                row, col = divmod(i, cols)
                self.parent_widget.vtk_layout.addWidget(node.widget, row, col)

            # 4. Distribute series to viewers
            self._distribute_series_to_viewers()

            # 5. Set first viewer as active
            if self.lst_nodes_viewer:
                self.change_container_border(0)

            if modify_by_user:
                QTimer.singleShot(500, self._hide_loading_msg)

            logger.debug(f"âœ… [LAYOUT] Applied {rows}x{cols} layout with {len(self.lst_nodes_viewer)} viewers")

        except Exception as e:
            logger.error(f"â‌Œ [LAYOUT] Error: {e}")
            import traceback
            traceback.print_exc()
            if modify_by_user:
                self._hide_loading_msg()
        finally:
            # âœ… FLICKER FIX: Re-enable updates after batch creation
            if hasattr(self.parent_widget, 'center_widget') and self.parent_widget.center_widget:
                self.parent_widget.center_widget.setUpdatesEnabled(True)
            self.parent_widget.setUpdatesEnabled(True)
            # Single repaint after all changes
            self.parent_widget.update()

    def new_viewer(self, default_thumb_index=0):
        logger.debug(f"\n{'='*80}")
        logger.debug(f"ًں”¨ [new_viewer] START - thumb_index={default_thumb_index}")
        self.logger.info(f"Creating new viewer with thumb index {default_thumb_index}")

        # Count existing viewers - if too many, be more aggressive with cleanup
        viewer_count = len(self.lst_nodes_viewer)

        # Hard limit protection
        if viewer_count >= self._max_viewers_per_session:
            logger.debug(f"   âڑ ï¸ڈ PROTECTION: Reached max viewers limit ({viewer_count}/{self._max_viewers_per_session})")
            logger.debug("   âڑ ï¸ڈ Creating lightweight placeholder viewer instead")
            try:
                return self._create_fallback_viewer()
            except Exception as e:
                logger.error(f"   â‌Œ Even fallback failed: {e}")
                self.logger.error(f"Max viewers exceeded and fallback failed: {e}", exc_info=True)
                raise

        # Aggressive cleanup for high viewer counts
        if viewer_count > 15:
            logger.warning(f"   âڑ ï¸ڈ WARNING: Already have {viewer_count} viewers - running lightweight cleanup")
            # REMOVED: gc.collect() was stop-the-world on UI thread causing user-visible freezes
            gc.collect(generation=0)  # generation=0 only: fast, collects young objects

        # Periodic cleanup
        import time
        current_time = time.time()
        if current_time - self._last_gc_time > 10.0 and viewer_count > 5:  # Every 10 seconds (was 2s)
            logger.debug(f"   ًں§¹ [Periodic GC] Cleaning up ({viewer_count} viewers)")
            gc.collect(generation=0)  # generation=0 only for minimal UI impact
            self._last_gc_time = current_time

        vtk_widget = None
        slider = None

        try:
            # âœ… FLICKER FIX: Removed processEvents - batching UI updates instead
            # processEvents was causing thumbnail loading to interrupt viewer creation

            logger.debug("   ًں“گ Creating grid layout...")
            try:
                layout = QGridLayout()
                # IMPORTANT: keep at (0, 0, 0, 0). A previous attempt at
                # (2, 2, 2, 2) — to reserve space for the QFrame's accent
                # border — caused the VTK render window to render at its
                # un-shrunk size while being positioned 2 px inset, so the
                # DICOM image and bottom overlay text overflowed past the
                # container's bottom border. The border-visibility problem
                # is resolved instead by VP-fix-1 (FAST viewer
                # `margin_bottom = 16`) and VP-fix-2 (VTK viewer
                # `bottom = 0.04`), which keep overlay text comfortably
                # inside the viewport without shrinking the widget itself.
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)
                logger.debug("   âœ… Grid layout created")
            except Exception as le:
                logger.warning(f"   âڑ ï¸ڈ Layout creation warning: {le}")
                raise RuntimeError(f"Failed to create grid layout: {le}")

            # Check if we have thumbnail data
            logger.debug("   ًں”چ Checking thumbnail data...")
            try:
                has_data = (hasattr(self.parent_widget, 'lst_thumbnails_data') and
                           self.parent_widget.lst_thumbnails_data and
                           len(self.parent_widget.lst_thumbnails_data) > 0)
            except Exception as ce:
                logger.warning(f"   âڑ ï¸ڈ Data check warning: {ce}")
                has_data = False

            if not has_data:
                logger.debug("   ًں“¦ No thumbnail data, creating lightweight VTK widget...")
                try:
                    # âœ… FLICKER FIX: Use lightweight VTK widget with deferred rendering
                    vtk_widget = self._create_lightweight_vtk_placeholder()
                    if vtk_widget is None:
                        raise RuntimeError("_create_lightweight_vtk_placeholder returned None")
                    logger.debug("   âœ… Lightweight VTK widget created")
                except Exception as dwe:
                    logger.error(f"   â‌Œ Lightweight VTK widget creation failed: {dwe}")
                    raise
            else:
                logger.debug(f"   âœ… Thumbnail data exists ({len(self.parent_widget.lst_thumbnails_data)} items)")
                logger.debug("   ًںژ¨ Creating new VTK widget...")
                try:
                    vtk_widget = self.create_new_vtk_widget(default_thumb_index)
                    if vtk_widget is None:
                        logger.debug("   âڑ ï¸ڈ create_new_vtk_widget returned None, using lightweight fallback")
                        vtk_widget = self._create_lightweight_vtk_placeholder()
                        if vtk_widget is None:
                            raise RuntimeError("Both create_new_vtk_widget and _create_lightweight_vtk_placeholder failed")
                    logger.debug("   âœ… VTK widget created")
                except Exception as vwe:
                    logger.error(f"   â‌Œ VTK widget creation failed: {vwe}")
                    raise

            # Validate vtk_widget
            if vtk_widget is None:
                raise RuntimeError("vtk_widget is None after creation")

            # Ensure toolbar context is available for tool auto-deactivation
            if getattr(vtk_widget, 'patient_widget', None) is None:
                vtk_widget.patient_widget = self.parent_widget

            if not isinstance(vtk_widget, QWidget):
                raise RuntimeError(f"vtk_widget is not a QWidget, got {type(vtk_widget)}")

            logger.debug("   ًں“ٹ Creating slider...")
            try:
                slider = SliceTickSlider(Qt.Vertical, vtk_widget)
                if slider is None:
                    raise RuntimeError("QSlider constructor returned None")
                slider.setInvertedAppearance(True)
                slider.setMaximumWidth(12)
                logger.debug("   âœ… Slider created")
            except Exception as se:
                logger.error(f"   â‌Œ Slider creation failed: {se}")
                raise RuntimeError(f"Failed to create slider: {se}")

        except Exception as e:
            logger.error(f"   â‌Œ ERROR in new_viewer setup: {e}")
            self.logger.error(f"Error in new_viewer setup: {e}", exc_info=True)

            # Try to return fallback viewer
            try:
                logger.debug("   ًں”„ Attempting fallback viewer creation...")
                fallback = self._create_fallback_viewer()
                if fallback:
                    logger.debug("   âœ… Fallback viewer created successfully")
                    return fallback
            except Exception as fe:
                logger.error(f"   â‌Œ Fallback viewer also failed: {fe}")

            raise

        # Configure slider styling - Chrome-style minimalist scrollbar
        try:
            slider.setStyleSheet("""
                QSlider {
                    background: transparent;
                    border: none;
                    padding-top: 8px;
                    padding-bottom: 8px;
                    padding-left: 0px;
                    padding-right: 0px;
                    min-width: 10px;
                    max-width: 10px;
                }
                /* ظ†ظˆط§ط± ط¹ظ…ظˆط¯غŒ (track) - ط³ط¨ع© Chrome */
                QSlider::groove:vertical {
                    background: rgba(0, 0, 0, 0.1);
                    width: 10px;
                    border-radius: 5px;
                    margin: 0px 0px;
                    border: none;
                }
                /* ط¯ط³طھظ‡ (thumb) - ظ…ط³طھط·غŒظ„غŒ ط¨ط§ ع¯ظˆط´ظ‡ ع¯ط±ط¯ ظ…ط«ظ„ Chrome */
                QSlider::handle:vertical {
                    background: rgba(128, 128, 128, 0.5);
                    width: 10px;
                    min-height: 40px;
                    border-radius: 5px;
                    margin: 0px 0px;
                    border: none;
                }
                /* ط­ط§ظ„طھ hover - طھغŒط±ظ‡â€Œطھط± ظ…غŒâ€Œط´ظˆط¯ */
                QSlider::handle:vertical:hover {
                    background: rgba(128, 128, 128, 0.7);
                }
                /* ط­ط§ظ„طھ ظپط´ط±ط¯ظ‡ ط´ط¯ظ† - ط®غŒظ„غŒ طھغŒط±ظ‡ */
                QSlider::handle:vertical:pressed {
                    background: rgba(96, 96, 96, 0.9);
                }
                /* ظ‚ط³ظ…طھ ط¨ط§ظ„ط§غŒ thumb - ط´ظپط§ظپ */
                QSlider::sub-page:vertical {
                    background: transparent;
                    border: none;
                }
                /* ظ‚ط³ظ…طھ ظ¾ط§غŒغŒظ† thumb - ط´ظپط§ظپ */
                QSlider::add-page:vertical {
                    background: transparent;
                    border: none;
                }
            """)
            
            # Force visibility and z-order
            slider.setVisible(True)
            slider.setAttribute(Qt.WA_TranslucentBackground, True)
            
            logger.debug("   âœ… Chrome-style scrollbar applied")
        except Exception as e:
            logger.warning(f"   âڑ ï¸ڈ Warning: Could not apply slider styling: {e}")

        try:
            logger.debug("   ًں“چ Adding widgets to layout...")
            # Add VTK widget to layout
            layout.addWidget(vtk_widget, 0, 0)
            
            logger.debug("   âœ… VTK widget added to layout")
        except Exception as e:
            logger.error(f"   â‌Œ ERROR adding vtk widget to layout: {e}")
            self.logger.error(f"Error adding widgets to layout: {e}", exc_info=True)
            raise

        # Use QFrame instead of QWidget - QFrame is designed for borders!
        try:
            logger.debug("   ًں–¼ï¸ڈ Creating container frame...")
            container = QFrame()
            container.setObjectName("ViewportContainer")
            container.setLayout(layout)
            container.setFrameStyle(QFrame.Box | QFrame.Plain)
            container.setLineWidth(2)  # Smaller border for inactive
            container.setProperty("active", False)
            container.setStyleSheet(self._viewport_container_styles(active=False))
            logger.debug("   âœ… Container created")
            
            # CRITICAL: Add slider as DIRECT CHILD of VTK widget (not container)
            # This ensures slider is ALWAYS on top of the image
            logger.debug("   ًں“چ Adding Chrome-style slider overlay on VTK widget...")
            slider.setParent(vtk_widget)
            slider.setGeometry(
                vtk_widget.width() - 15,  # 15px from right edge (Chrome-style)
                5,  # 5px from top
                10,  # width (Chrome-style - 10px)
                vtk_widget.height() - 10  # height minus margins
            )
            
            # Force slider to be on top of everything with maximum z-order
            slider.raise_()
            slider.setVisible(True)
            slider.show()
            slider.update()
            
            # Connect resize event to reposition slider on VTK widget
            def reposition_slider():
                if slider and vtk_widget:
                    try:
                        slider.setGeometry(
                            vtk_widget.width() - 15,  # Chrome-style positioning
                            5,
                            10,
                            vtk_widget.height() - 10
                        )
                        slider.raise_()
                        slider.update()
                    except RuntimeError:
                        pass  # Widget might be deleted
            
            # Store original resizeEvent of VTK widget
            if hasattr(vtk_widget, 'resizeEvent'):
                original_vtk_resize = vtk_widget.resizeEvent
                def new_vtk_resize_event(event):
                    original_vtk_resize(event)
                    reposition_slider()
                vtk_widget.resizeEvent = new_vtk_resize_event
            
            logger.debug("   âœ… Thin slider added as OVERLAY directly on VTK widget (ALWAYS on top)")
            
        except Exception as e:
            logger.error(f"   â‌Œ ERROR creating container: {e}")
            self.logger.error(f"Error creating container: {e}", exc_info=True)
            raise

        # Create NodeViewer
        try:
            logger.debug("   ًں”— Creating NodeViewer...")
            new_node = NodeViewer(container, vtk_widget, slider)
            if new_node is None:
                raise RuntimeError("NodeViewer creation returned None")
            logger.debug("   âœ… NodeViewer created")
        except Exception as e:
            logger.error(f"   â‌Œ ERROR creating NodeViewer: {e}")
            self.logger.error(f"Error creating NodeViewer: {e}", exc_info=True)
            raise

        # Set viewer ID and configure
        try:
            logger.debug("   ًں†” Setting viewer ID...")
            viewer_index = len(self.lst_nodes_viewer)

            # Safely set ID attribute
            if hasattr(vtk_widget, '__dict__'):
                vtk_widget.id_vtk_widget = viewer_index
            else:
                setattr(vtk_widget, 'id_vtk_widget', viewer_index)
            logger.debug(f"   âœ… Viewer ID set to {viewer_index}")

            logger.debug("   ًں“‌ Appending to lst_nodes_viewer...")
            self.lst_nodes_viewer.append(new_node)
            logger.debug("   âœ… Appended")
        except Exception as e:
            logger.error(f"   â‌Œ ERROR setting viewer ID: {e}")
            self.logger.error(f"Error setting viewer ID: {e}", exc_info=True)
            raise

        # Configure slider
        # NOTE: mid_slices MUST be initialised before the try block so the
        # connect block below can always reference it, even if an exception is
        # thrown inside the try before the assignment is reached.
        mid_slices = 0
        try:
            logger.debug("   ًںژڑï¸ڈ Configuring slider...")

            # FORCE SLIDER VISIBILITY - critical for always showing slider
            slider.setOrientation(Qt.Vertical)
            slider.setInvertedAppearance(True)
            slider.setInvertedControls(True)
            slider.setTickPosition(QSlider.NoTicks)  # ticks painted by SliceTickSlider
            slider.setTickInterval(0)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            slider.setTracking(True)
            slider.setFocusPolicy(Qt.StrongFocus)
            slider.setMouseTracking(True)
            slider.setVisible(True)
            slider.show()
            slider.setEnabled(True)

            # âœ… CRITICAL: Block signals during slider setup to prevent image number flickering
            slider.blockSignals(True)

            # Check if methods exist
            if not hasattr(vtk_widget, 'set_slider'):
                logger.debug("   âڑ ï¸ڈ VTK widget doesn't have set_slider yet (placeholder mode)")
                # For placeholder widgets, just set slider to default values
                slider.setMinimum(0)
                slider.setMaximum(0)
                slider.setValue(0)
                logger.debug("   âœ… Slider configured in placeholder mode (0 slices) - VISIBLE")
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
                logger.debug(f"   âœ… Slider configured (slices: {count_slices}, current: {mid_slices}) - VISIBLE")
        except Exception as e:
            logger.error(f"   â‌Œ ERROR configuring slider: {e}")
            # Don't raise - allow viewer creation to continue
            # Just set slider to defaults
            slider.setMinimum(0)
            slider.setMaximum(0)
            slider.setValue(0)
            logger.error("   âڑ ï¸ڈ Slider set to default values after error")
        finally:
            # âœ… CRITICAL: Unblock signals after all slider configuration is complete
            slider.blockSignals(False)

        # Connect signals
        try:
            logger.debug("   ًں”— Connecting slider signal...")
            self.parent_widget.on_slider_value_changed(vtk_widget, mid_slices)
            slider.valueChanged.connect(partial(self.parent_widget.on_slider_value_changed, vtk_widget))
            logger.debug("   âœ… Slider connected")
            # Slider thumb-drag fast path: FAST-mode only, gated by AIPACS_SLIDER_FAST_DRAG=1.
            # When enabled, sliderMoved routes through the full protected-drag pipeline
            # (surrogate frames, render clock, GC suppression, FAST_DRAG_KPI).
            # sliderPressed begins the session; sliderReleased ends it and arms the settle timer.
            import os as _os_sfp
            if _os_sfp.getenv('AIPACS_SLIDER_FAST_DRAG', '0') == '1':
                try:
                    from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import (
                        QtFastContainer,
                    )
                    if isinstance(vtk_widget, QtFastContainer):
                        vtk_widget._slider_thumb_drag_active = False

                        def _sb_pressed(vw=vtk_widget):
                            vw._slider_thumb_drag_active = True
                            vw.begin_slider_drag_session()

                        def _sb_moved(val, vw=vtk_widget):
                            vw.set_slice_during_drag(val)

                        def _sb_released(vw=vtk_widget):
                            vw._slider_thumb_drag_active = False
                            vw.end_slider_drag_session()

                        slider.sliderPressed.connect(_sb_pressed)
                        slider.sliderMoved.connect(_sb_moved)
                        slider.sliderReleased.connect(_sb_released)
                except Exception:
                    pass  # Kill-switch block failure never breaks the standard valueChanged path
        except Exception as e:
            logger.warning(f"   âڑ ï¸ڈ Warning: Could not connect slider signal: {e}")
            self.logger.warning(f"Warning connecting slider signal: {e}")

        # Set VTK widget methods
        try:
            logger.debug("   ًں”§ Setting VTK widget methods...")
            if hasattr(vtk_widget, 'set_method_change_series_on_drop'):
                vtk_widget.set_method_change_series_on_drop(self.parent_widget.change_series_on_viewer)
            if hasattr(vtk_widget, 'set_method_change_container_border'):
                vtk_widget.set_method_change_container_border(self.change_container_border)
            if hasattr(vtk_widget, 'set_method_refresh_viewport_borders'):
                vtk_widget.set_method_refresh_viewport_borders(self.refresh_viewport_borders)
            logger.debug("   âœ… Methods set")
        except Exception as e:
            logger.warning(f"   âڑ ï¸ڈ Warning: Could not set VTK widget methods: {e}")
            self.logger.warning(f"Warning setting VTK widget methods: {e}")

        logger.debug(f"ًں”¨ [new_viewer] END - Successfully created viewer with ID {viewer_index}")
        logger.debug(f"{'='*80}\n")
        return new_node

    def _create_lightweight_vtk_placeholder(self):
        """Create a lightweight viewer placeholder that defers rendering until data is loaded"""
        try:
            # Use parent_widget's create_dummy_vtk_widget if available (supports AIVTKWidget override)
            if hasattr(self.parent_widget, 'create_dummy_vtk_widget'):
                return self.parent_widget.create_dummy_vtk_widget()
            
            # Fallback: decide widget type by backend (mirrors _pw_viewers.py logic)
            height = self.parent_widget.sidebar.height() if hasattr(self.parent_widget, 'sidebar') and self.parent_widget.sidebar else 480
            requested_backend = (
                self._get_requested_viewer_backend()
                if hasattr(self, '_get_requested_viewer_backend')
                else None
            )
            if requested_backend == BACKEND_PYDICOM_QT:
                from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer
                container = QtFastContainer(height_viewer=height, patient_widget=self.parent_widget)
                container._is_placeholder = True
                return container

            vtk_widget = VTKWidget(height_viewer=height, patient_widget=self.parent_widget)

            if vtk_widget is None:
                raise RuntimeError("VTKWidget constructor returned None")

            # ✅ CRITICAL: Set solid background FIRST to prevent any flash
            if hasattr(vtk_widget, 'renderer'):
                vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)  # #1a1a2e in RGB
                # ❌ FLICKER FIX: DO NOT call Render() here - it causes initial flash
                # The background will be set when the widget is first shown

            # Minimize rendering updates until real data is loaded
            if hasattr(vtk_widget, 'render_window'):
                vtk_widget.render_window.SetDesiredUpdateRate(0.001)  # Very low update rate

            # Add a flag to indicate this is a placeholder
            vtk_widget._is_placeholder = True

            return vtk_widget
        except Exception as e:
            logger.error(f"❌ Error creating lightweight VTK widget: {e}")
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
                logger.debug(f"âڑ ï¸ڈ [create_new_vtk_widget] No thumbnail data at index {default_thumb_index}, using dummy")
                return self.create_dummy_vtk_widget()

            # Extract data safely
            try:
                thumbnail_item = self.parent_widget.lst_thumbnails_data[default_thumb_index]
                if not isinstance(thumbnail_item, dict) or 'vtk_image_data' not in thumbnail_item or 'metadata' not in thumbnail_item:
                    raise ValueError(f"Invalid thumbnail data structure at index {default_thumb_index}")

                vtk_widget_data = thumbnail_item['vtk_image_data']
                metadata = copy.deepcopy(thumbnail_item['metadata'])

                if vtk_widget_data is None or metadata is None:
                    raise ValueError("VTK data or metadata is None")

            except (IndexError, KeyError, TypeError) as e:
                logger.error(f"âڑ ï¸ڈ [create_new_vtk_widget] Error extracting thumbnail data: {e}")
                return self.create_dummy_vtk_widget()

            # Extract metadata safely
            try:
                series_name = metadata.get('series', {}).get('series_name', 'Unknown')
                series_number = metadata.get('series', {}).get('series_number', 0)
            except (AttributeError, TypeError) as e:
                logger.error(f"âڑ ï¸ڈ [create_new_vtk_widget] Error extracting series info: {e}")
                series_name = 'Unknown'
                series_number = 0

            requested_backend = self._get_requested_viewer_backend()
            try:
                if self._needs_backend_rebuild(metadata, requested_backend):
                    print(
                        f"[BACKEND_RELOAD_INIT] series={series_number} rebuilding payload for backend={requested_backend}"
                    )
                    if str(series_number).isdigit():
                        self._load_single_series_on_demand(
                            int(series_number),
                            study_path=self._get_correct_study_path(),
                            target_vtk_widget=None,
                            allow_paired=False,
                            expected_token=None,
                            viewer_backend=requested_backend,
                            force_reload=(requested_backend == BACKEND_PYDICOM),
                        )
                        rebuilt_vtk, rebuilt_meta, rebuilt_idx = self._get_series_by_number_fast(str(series_number))
                        if rebuilt_vtk is not None and isinstance(rebuilt_meta, dict):
                            vtk_widget_data = rebuilt_vtk
                            metadata = copy.deepcopy(rebuilt_meta)
                            default_thumb_index = int(rebuilt_idx) if int(rebuilt_idx) >= 0 else default_thumb_index
            except Exception as e:
                logger.error(f"âڑ ï¸ڈ [create_new_vtk_widget] backend rebuild check failed: {e}")

            # IMPORTANT: last_series_show must always store thumbnail/list index
            # (NOT series_number) so per-viewport state comparisons remain consistent.
            series_idx = default_thumb_index

            # Create VTK widget
            try:
                vtk_widget = self.creator_vtk_widget()
                if vtk_widget is None:
                    raise RuntimeError("creator_vtk_widget returned None")
            except Exception as e:
                logger.error(f"â‌Œ [create_new_vtk_widget] Error creating VTK widget: {e}")
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

                        # MG-PAIR-1: the bare `==` matched None==None and
                        # 'None'=='None', combining CC into the MLO viewport for
                        # studies whose series rows have a NULL series_name.
                        if can_pair_series_names(series_name, series_name_2):
                            flag_open_combine_viewer = True
                            vtk_widget_data_2 = item.get('vtk_image_data')
                            metadata_2 = copy.deepcopy(item.get('metadata'))
                            break
                    except (AttributeError, TypeError, IndexError):
                        continue
            except Exception as e:
                logger.warning(f"âڑ ï¸ڈ [create_new_vtk_widget] Warning during combined series check: {e}")

            logger.debug(f'[create_new_vtk_widget] Series: {series_name}, Number: {series_number}, Combined: {flag_open_combine_viewer}')

            # Process series
            try:
                if flag_open_combine_viewer and vtk_widget_data_2 is not None and metadata_2 is not None:
                    vtk_widget.start_process_combine_series(
                        vtk_widget_data, metadata, vtk_widget_data_2, metadata_2, series_idx, id_new_vtk_widget,
                        metadata_fixed=self.parent_widget.metadata_fixed if hasattr(self.parent_widget, 'metadata_fixed') else {})
                else:
                    vtk_widget.start_process_series(
                        vtk_image_data=vtk_widget_data, metadata=metadata, series_index=series_idx,
                        id_vtk_widget=id_new_vtk_widget, metadata_fixed=self.parent_widget.metadata_fixed if hasattr(self.parent_widget, 'metadata_fixed') else {})

                return vtk_widget

            except Exception as e:
                logger.error(f"â‌Œ [create_new_vtk_widget] Error processing series: {e}")
                self.logger.error(f"Error processing series: {e}", exc_info=True)
                return self.create_dummy_vtk_widget()

        except Exception as e:
            logger.error(f"â‌Œ [create_new_vtk_widget] Unexpected error: {e}")
            self.logger.error(f"Unexpected error in create_new_vtk_widget: {e}", exc_info=True)
            return self.create_dummy_vtk_widget()

    def creator_vtk_widget(self):
        try:
            # Use parent_widget's creator method if available (supports AIVTKWidget override)
            if hasattr(self.parent_widget, 'creator_vtk_widget'):
                return self.parent_widget.creator_vtk_widget()
            # Fallback: decide widget type by backend (mirrors _pw_viewers.py logic)
            height = self.parent_widget.sidebar.height() if hasattr(self.parent_widget, 'sidebar') and self.parent_widget.sidebar else 480
            requested_backend = (
                self._get_requested_viewer_backend()
                if hasattr(self, '_get_requested_viewer_backend')
                else None
            )
            if requested_backend == BACKEND_PYDICOM_QT:
                from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.qt_fast_container import QtFastContainer
                return QtFastContainer(height_viewer=height, patient_widget=self.parent_widget)
            return VTKWidget(height_viewer=height, patient_widget=self.parent_widget)
        except Exception as e:
            logger.error(f"❌ Error in creator_vtk_widget: {e}")
            self.logger.error(f"Error in creator_vtk_widget: {e}", exc_info=True)
            return None

    def set_viewer_to_main_viewer(self, node_viewer: NodeViewer):
        if self.selected_widget == node_viewer.vtk_widget:
            return False

        tb = self.parent_widget.toolbar_manager

        # ── MPR is a PER-VIEWPORT mode, not a transient tool ──────────────────
        # Merely changing the ACTIVE viewport (clicking — or drag-dropping a
        # series — onto another cell) must NOT tear MPR down on its host cell and
        # must NOT re-open MPR on the newly-active cell. Only the explicit MPR
        # button (toggle_zeta_mpr) or a layout change may end MPR.
        #
        # Root cause of "drop on viewport 2 exits viewport 1's MPR": this method
        # runs check_and_deactivate_tools() BELOW *before* `selected_widget` is
        # reassigned, so its MPR guard still sees the MPR-hosting cell as the
        # selection and calls toggle_zeta_mpr(), which scans every node and closes
        # whichever cell hosts MPR. So when MPR is the active mode we just move the
        # active selection and leave MPR (and tool_selected) completely intact.
        _preserve_mpr = (
            os.getenv("AIPACS_MPR_PRESERVE_ON_VIEWPORT_CHANGE", "1") or "1"
        ).strip() != "0"
        _tool_is_mpr = False
        try:
            _tool_is_mpr = (
                getattr(tb, "tool_selected", None) is not None
                and tb.tool_selected == tb.tool_access.MPR
            )
        except Exception:
            _tool_is_mpr = False

        if _preserve_mpr and _tool_is_mpr:
            logger.info(
                "[MPR-PRESERVE] active-viewport change old_viewer=%s new_viewer=%s "
                "— MPR kept intact (no teardown, no re-apply)",
                getattr(self.selected_widget, "id_vtk_widget", "?"),
                getattr(node_viewer.vtk_widget, "id_vtk_widget", "?"),
            )
            self.selected_widget: VTKWidget = node_viewer.vtk_widget
            self.slider = node_viewer.slider
            return

        # ── Sync Image (TARGET) is viewport-CLICK driven, not active-layout bound ──
        # Clicking Sync Image on a NON-active viewport must (a) make that viewport
        # active and (b) drop the sync point there on the SAME click — without the
        # tool deactivating. The generic path below runs check_and_deactivate_tools()
        # (which turns Sync OFF) and does NOT re-apply TARGET (get_tool_activated_method
        # has no TARGET branch), so the click only switched the active cell and disabled
        # sync — forcing the user to click Sync Image a second time once the cell was
        # active. Like MPR, Sync is a CROSS-viewport mode (the click-to-target pipeline
        # is registered on every viewer), so we just move the active selection and leave
        # the sync pipeline + tool_selected intact. The in-flight FAST mouse press then
        # still sees `_sync_mode_active` True and lands the target on the clicked
        # viewport, which syncs to the others.
        # Kill switch: AIPACS_SYNC_PRESERVE_ON_VIEWPORT_CHANGE=0 restores legacy behavior.
        _preserve_sync = (
            os.getenv("AIPACS_SYNC_PRESERVE_ON_VIEWPORT_CHANGE", "1") or "1"
        ).strip() != "0"
        _tool_is_sync = False
        try:
            _tool_is_sync = (
                getattr(tb, "tool_selected", None) is not None
                and tb.tool_selected == tb.tool_access.TARGET
            )
        except Exception:
            _tool_is_sync = False

        if _preserve_sync and _tool_is_sync:
            logger.info(
                "[SYNC-PRESERVE] active-viewport change old_viewer=%s new_viewer=%s "
                "— Sync Image kept active (no teardown); target lands on the clicked viewport",
                getattr(self.selected_widget, "id_vtk_widget", "?"),
                getattr(node_viewer.vtk_widget, "id_vtk_widget", "?"),
            )
            self.selected_widget: VTKWidget = node_viewer.vtk_widget
            self.slider = node_viewer.slider
            return

        # save tool activated
        tool_activated_method = tb.get_tool_activated_method()

        tb.check_and_deactivate_tools()

        # set new vtk_widget to main vtk_widget
        self.selected_widget: VTKWidget = node_viewer.vtk_widget
        self.slider = node_viewer.slider

        if tool_activated_method:
            # apply activated tool on new vtk_widget
            tb.tool_selected = None
            tool_activated_method(self.selected_widget)

    def change_container_border(self, id_vtk_widget):
        node_viewer_selected = self.lst_nodes_viewer[id_vtk_widget]
        for node_viewer in self.lst_nodes_viewer:
            node_viewer: NodeViewer

            is_active = (node_viewer_selected.widget == node_viewer.widget)
            # Origin: a viewport showing a PREVIOUS exam gets a red border; the
            # current/main exam keeps the default blue accent. Pass the NODE — the
            # origin stamp / series metadata live on node.vtk_widget (the FAST
            # container), while node.widget is the bordered frame we style.
            is_prev = self._node_is_previous_exam(node_viewer)
            node_viewer.widget.setProperty("active", is_active)
            node_viewer.widget.setFrameStyle(QFrame.Box | QFrame.Plain)
            node_viewer.widget.setLineWidth(2)  # Same in both states
            node_viewer.widget.setStyleSheet(
                self._viewport_container_styles(active=is_active, previous=is_prev))
            if is_active:
                self.set_viewer_to_main_viewer(node_viewer_selected)

        self.parent_widget.manage_reference_line()

    def refresh_viewport_borders(self) -> None:
        """Re-apply every viewport's border by (active-state, study-origin) WITHOUT
        changing the active selection. Lets a freshly-loaded previous-exam series
        turn its viewport red immediately even when the load did not change the
        selected viewport (e.g. a drag-and-drop). Best-effort; never raises."""
        try:
            for node_viewer in self.lst_nodes_viewer:
                w = getattr(node_viewer, 'widget', None)
                if w is None:
                    continue
                try:
                    is_active = bool(w.property("active"))
                    # Read origin from the NODE (node.vtk_widget holds the stamp /
                    # series metadata); style node.widget (the bordered frame).
                    is_prev = self._node_is_previous_exam(node_viewer)
                    w.setStyleSheet(
                        self._viewport_container_styles(active=is_active, previous=is_prev))
                except Exception:
                    continue
        except Exception:
            pass

    def _node_current_study_uid(self, widget) -> str:
        """Best-effort study_uid of the series currently shown in a viewport.

        The FAST qt-bridge metadata's series dict does not reliably carry
        ``study_uid``, so the authoritative resolution is the DISPLAYED series
        number (an offset key for a multi-study / previous-exam series) looked up
        against the parent widget's ``_server_series_info`` (whose offset-keyed
        entries carry ``study_uid``), with the canonical-identity resolver and the
        series_path parent as fallbacks. '' when unknown."""
        try:
            md = None
            br = getattr(widget, '_qt_bridge', None)
            if br is not None:
                md = getattr(br, 'metadata', None)
            if not isinstance(md, dict):
                md = getattr(widget, 'metadata', None)
            series = md.get('series', {}) if isinstance(md, dict) else {}

            # 1) direct study_uid on the metadata (rarely present)
            su = str((series or {}).get('study_uid') or '').strip()
            if su:
                return su

            pw = getattr(self, 'parent_widget', None)
            snum = str((series or {}).get('series_number') or '').strip()

            # 2) resolve the displayed series number against the offset-keyed
            #    server map (multi-study / previous-exam entries carry study_uid)
            if snum and pw is not None:
                ssi = getattr(pw, '_server_series_info', None) or {}
                entry = ssi.get(snum)
                if not isinstance(entry, dict):
                    entry = ssi.get(str(snum))
                if isinstance(entry, dict):
                    su = str(entry.get('study_uid') or '').strip()
                    if su:
                        return su

            # 3) canonical-identity resolver (handles offset keys)
            if snum:
                try:
                    rid = self._resolve_canonical_series_identity(snum)
                    if rid and rid[0]:
                        return str(rid[0]).strip()
                except Exception:
                    pass

            # 4) parse series_path: {SOURCE}/{study_uid}/{series_number}
            sp = str((series or {}).get('series_path') or '').strip()
            if sp:
                from pathlib import Path
                return Path(sp).parent.name
        except Exception:
            pass
        return ''

    def _series_is_previous_exam(self, series_number) -> bool:
        """True when the series being loaded (by its number / offset key) belongs
        to a sanctioned PREVIOUS exam. Resolves the number against the offset-keyed
        server map (carries study_uid), then the canonical-identity resolver.
        Used to STAMP a viewport's origin at load time (the authoritative signal,
        independent of paint-time metadata)."""
        try:
            pw = getattr(self, 'parent_widget', None)
            checker = getattr(pw, '_is_sanctioned_previous_exam', None)
            if not callable(checker):
                return False
            snum = str(series_number or '').strip()
            if not snum:
                return False
            su = ''
            ssi = getattr(pw, '_server_series_info', None) or {}
            entry = ssi.get(snum)
            if not isinstance(entry, dict):
                entry = ssi.get(str(snum))
            if isinstance(entry, dict):
                su = str(entry.get('study_uid') or '').strip()
            if not su:
                try:
                    rid = self._resolve_canonical_series_identity(snum)
                    if rid and rid[0]:
                        su = str(rid[0]).strip()
                except Exception:
                    pass
            return bool(su) and bool(checker(su))
        except Exception:
            return False

    def _node_is_previous_exam(self, node_or_widget) -> bool:
        """True when the viewport shows a sanctioned PREVIOUS-exam series.

        Accepts a NodeViewer OR a widget. The origin stamp (``_origin_is_previous``,
        set by change_series_on_viewer) and the series metadata live on the actual
        viewer widget — a NodeViewer exposes it as ``.vtk_widget`` while ``.widget``
        is only the bordered frame — so resolve that first. Prefers the stamp;
        falls back to resolving the displayed series' study_uid (legacy/VTK paths
        that don't stamp)."""
        try:
            # Resolve the actual viewer widget (FAST container) that carries the
            # stamp / qt-bridge metadata. A NodeViewer has .vtk_widget; a bare
            # widget is used as-is.
            vw = getattr(node_or_widget, 'vtk_widget', None) or node_or_widget
            flag = getattr(vw, '_origin_is_previous', None)
            if flag is not None:
                return bool(flag)
            pw = getattr(self, 'parent_widget', None)
            checker = getattr(pw, '_is_sanctioned_previous_exam', None)
            if not callable(checker):
                return False
            su = self._node_current_study_uid(vw)
            return bool(su) and bool(checker(su))
        except Exception:
            return False


