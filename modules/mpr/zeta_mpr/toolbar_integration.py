"""
Toolbar Integration for New MPR Zeta Module

This module contains the button integration code that should be added to toolbar_manager.py
to enable the NEW MPR ZETA button functionality.

Usage in toolbar_manager.py:
    1. Add to imports:
       from modules.mpr.zeta_mpr import (
           toggle_new_mpr_zeta,
           replace_selected_viewport_with_new_mpr_zeta
       )
    
    2. Add to __init__ method:
       self._new_mpr_zeta_active = False
    
    3. Add button to MPR dropdown menu:
       mpr_zeta_action = mpr_dropdown_menu.addAction("MPR ζ (Zeta)")
       mpr_zeta_action.setToolTip("Standard MPR viewer - old MPR implementation for comparison")
       mpr_zeta_action.triggered.connect(lambda: toggle_new_mpr_zeta(
           self, self.patient_widget.selected_widget
       ))
"""

import logging
import sys
import os
from PySide6.QtWidgets import QMessageBox, QSizePolicy, QWidget


def toggle_new_mpr_zeta(toolbar_manager, selected_widget=None):
    """
    Toggle New MPR Zeta (old Standard MPR) viewer - for comparison with newer implementations
    
    Args:
        toolbar_manager: The toolbar manager instance (self)
        selected_widget: The currently selected widget to replace (optional)
    """
    logger = logging.getLogger(__name__)

    print("=" * 80, file=sys.stderr, flush=True)
    print("TOGGLE NEW MPR ZETA (OLD STANDARD MPR) FUNCTION STARTED", file=sys.stderr, flush=True)

    if selected_widget is None:
        selected_widget = toolbar_manager.patient_widget.selected_widget
        print(f"Got selected_widget from patient_widget: {selected_widget}", file=sys.stderr, flush=True)

    print(f"selected_widget: {selected_widget}", file=sys.stderr, flush=True)
    print(f"selected_widget type: {type(selected_widget)}", file=sys.stderr, flush=True)
    print(f"tool_selected: {toolbar_manager.tool_selected}", file=sys.stderr, flush=True)
    print(f"tool_access.NEW_MPR_ZETA: {getattr(toolbar_manager.tool_access, 'NEW_MPR_ZETA', 'NOT FOUND')}", file=sys.stderr, flush=True)

    logger.info("=" * 80)
    logger.info("TOGGLE NEW MPR ZETA (OLD STANDARD MPR) CALLED")
    logger.info(f"selected_widget: {selected_widget}")
    logger.info(f"selected_widget type: {type(selected_widget)}")

    # Check if zeta MPR is already active (deactivate if so)
    if toolbar_manager.tool_selected is not None and hasattr(toolbar_manager, '_new_mpr_zeta_active') and toolbar_manager._new_mpr_zeta_active:
        logger.info("Deactivating New MPR Zeta (already active)")
        print("[DEACTIVATE] Closing New MPR Zeta and restoring original viewer...", file=sys.stderr, flush=True)
        toolbar_manager._new_mpr_zeta_active = False
        try:
            # Get the original widget that was hidden
            original_widget = selected_widget
            
            # Check if current selected_widget is the MPR widget
            if hasattr(selected_widget, '_original_widget'):
                # selected_widget IS the MPR widget, get original from back-reference
                original_widget = selected_widget._original_widget
                print(f"[DEACTIVATE] Using back-reference to original widget: {original_widget}", file=sys.stderr, flush=True)
            elif hasattr(selected_widget, '_new_mpr_zeta_widget'):
                # selected_widget is the original, MPR reference exists
                print("[DEACTIVATE] Using selected_widget as original (has _new_mpr_zeta_widget)", file=sys.stderr, flush=True)
                original_widget = selected_widget
            else:
                # Search for the hidden original widget in parent's children
                print("[DEACTIVATE] Searching parent's children for original widget...", file=sys.stderr, flush=True)
                if hasattr(selected_widget, 'parent') and selected_widget.parent():
                    for child in selected_widget.parent().findChildren(QWidget):
                        if hasattr(child, '_new_mpr_zeta_widget') and child._new_mpr_zeta_widget == selected_widget:
                            original_widget = child
                            print(f"[DEACTIVATE] Found original widget: {original_widget}", file=sys.stderr, flush=True)
                            break
            
            toolbar_manager._restore_selected_viewer(original_widget)
            print("[DEACTIVATE] Original viewer restored successfully", file=sys.stderr, flush=True)
        except Exception as e:
            logger.error(f"Error restoring viewer: {e}", exc_info=True)
            print(f"[DEACTIVATE] ERROR: {e}", file=sys.stderr, flush=True)
            import traceback
            traceback.print_exc(file=sys.stderr)
        toolbar_manager.tool_selected = None
        toolbar_manager.handle_buttons_checked()
        return

    logger.info("Activating New MPR Zeta (Old Standard MPR)")
    toolbar_manager.check_and_deactivate_tools()

    if selected_widget is None:
        print("ERROR: selected_widget is None!", file=sys.stderr, flush=True)
        logger.error("selected_widget is None! Cannot open New MPR Zeta viewer.")
        QMessageBox.warning(toolbar_manager.patient_widget, "New MPR Zeta Viewer", "Please select a viewer first.")
        return

    try:
        logger.info(f"Checking selected_widget attributes...")
        logger.info(f"hasattr(selected_widget, 'last_series_show'): {hasattr(selected_widget, 'last_series_show')}")

        if not hasattr(selected_widget, 'last_series_show'):
            logger.warning("No series loaded in selected viewport")
            QMessageBox.warning(toolbar_manager.patient_widget, "New MPR Zeta Viewer", "No series loaded in selected viewport.")
            return

        series_index = selected_widget.last_series_show
        logger.info(f"Series index: {series_index}")

        vtk_image_data = None
        dicom_directory = None
        window_width = None
        window_center = None
        logger.info(f"🔍 Searching in {len(toolbar_manager.patient_widget.lst_thumbnails_data)} thumbnail data entries...")

        for i in range(len(toolbar_manager.patient_widget.lst_thumbnails_data)):
            try:
                thumbnail_data = toolbar_manager.patient_widget.lst_thumbnails_data[i]
                metadata = thumbnail_data.get('metadata', {})
                series_metadata = metadata.get('series', {})
                series_num = int(series_metadata.get('series_number', -1))

                logger.info(f"   [{i}] series_number={series_num}, looking for {series_index}")

                if series_num == int(series_index):
                    vtk_image_data = thumbnail_data.get('vtk_image_data')
                    dicom_directory = series_metadata.get('series_path')
                    logger.info(f"   ✅ MATCH! series_path from metadata: {dicom_directory}")

                    instances = metadata.get('instances', [])
                    if instances and len(instances) > 0:
                        first_instance = instances[0]
                        if not dicom_directory:
                            first_instance_path = first_instance.get('instance_path')
                            if first_instance_path:
                                dicom_directory = os.path.dirname(first_instance_path)
                                logger.info(f"   ✅ Got directory from instance_path: {dicom_directory}")

                        window_width = first_instance.get('window_width')
                        window_center = first_instance.get('window_center')
                        logger.info(f"   ✅ Got W/L from instance: W={window_width}, C={window_center}")

                    logger.info(f"   🎯 Final DICOM directory: {dicom_directory}")
                    break
            except (KeyError, ValueError, TypeError) as e:
                logger.debug(f"   [ERROR] checking thumbnail data at index {i}: {e}")
                continue

        if vtk_image_data is None:
            logger.warning(f"No image data available for New MPR Zeta viewer (series_index: {series_index})")
            QMessageBox.warning(toolbar_manager.patient_widget, "New MPR Zeta Viewer", f"No image data available for series {series_index}.")
            return

        logger.info(f"vtk_image_data found: {vtk_image_data}")
        logger.info(f"vtk_image_data type: {type(vtk_image_data)}")
        if hasattr(vtk_image_data, 'GetDimensions'):
            logger.info(f"vtk_image_data dimensions: {vtk_image_data.GetDimensions()}")

        print("Calling replace_selected_viewport_with_new_mpr_zeta...", file=sys.stderr, flush=True)
        logger.info("Calling replace_selected_viewport_with_new_mpr_zeta...")
        logger.info(f"Passing dicom_directory: {dicom_directory}")
        logger.info(f"Passing W/L: W={window_width}, C={window_center}")
        
        replace_selected_viewport_with_new_mpr_zeta(
            toolbar_manager,
            selected_widget,
            vtk_image_data,
            dicom_directory,
            window_width,
            window_center,
        )
        print("replace_selected_viewport_with_new_mpr_zeta completed successfully", file=sys.stderr, flush=True)
        logger.info("replace_selected_viewport_with_new_mpr_zeta completed")

    except Exception as e:
        logger.error(f"Error opening New MPR Zeta viewer: {e}", exc_info=True)
        QMessageBox.critical(toolbar_manager.patient_widget, "New MPR Zeta Viewer Error", f"Error opening New MPR Zeta viewer:\n{str(e)}")
        import traceback
        traceback.print_exc()
        return

    toolbar_manager._new_mpr_zeta_active = True
    toolbar_manager.tool_selected = True  # Mark a tool as selected
    toolbar_manager.handle_buttons_checked()
    logger.info("New MPR Zeta toggle completed successfully")
    logger.info("=" * 80)


def replace_selected_viewport_with_new_mpr_zeta(toolbar_manager, selected_widget, vtk_image_data, dicom_directory=None, window_width=None, window_center=None):
    """
    Replace the selected viewport with New MPR Zeta (old Standard MPR) viewer
    
    Args:
        toolbar_manager: The toolbar manager instance
        selected_widget: The widget to replace
        vtk_image_data: The VTK image data to display
        dicom_directory: Optional DICOM directory path
        window_width: Optional window width setting
        window_center: Optional window center setting
    """
    logger = logging.getLogger(__name__)

    print("=" * 80, file=sys.stderr, flush=True)
    print("replace_selected_viewport_with_new_mpr_zeta CALLED", file=sys.stderr, flush=True)
    print(f"selected_widget: {selected_widget}", file=sys.stderr, flush=True)
    print(f"vtk_image_data: {vtk_image_data}", file=sys.stderr, flush=True)
    print(f"dicom_directory (passed): {dicom_directory}", file=sys.stderr, flush=True)
    print(f"window_width (passed): {window_width}", file=sys.stderr, flush=True)
    print(f"window_center (passed): {window_center}", file=sys.stderr, flush=True)

    series_index = selected_widget.last_series_show
    print(f"   Series index from widget: {series_index}", file=sys.stderr, flush=True)
    print(f"🎯 Final dicom_directory: {dicom_directory}", file=sys.stderr, flush=True)
    logger.info(f"   Using W/L: W={window_width}, C={window_center}")

    print("Importing StandardMPRViewer from zeta mpr module...", file=sys.stderr, flush=True)
    try:
        # Import from the zeta mpr module
        from modules.mpr.zeta_mpr import StandardMPRViewer
        print("StandardMPRViewer imported successfully from zeta_mpr module", file=sys.stderr, flush=True)
    except Exception as import_error:
        print(f"ERROR importing StandardMPRViewer: {import_error}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise

    print("Getting parent widget...", file=sys.stderr, flush=True)
    parent_widget = selected_widget.parent()
    print(f"parent_widget: {parent_widget}", file=sys.stderr, flush=True)
    print(f"parent_widget size: {parent_widget.size()}", file=sys.stderr, flush=True)

    print("Getting parent layout...", file=sys.stderr, flush=True)
    parent_layout = parent_widget.layout()
    print(f"parent_layout: {parent_layout}", file=sys.stderr, flush=True)

    # CRITICAL: Remove the original widget from layout AND hide it
    print("[NEW MPR ZETA] Removing original widget from layout...", file=sys.stderr, flush=True)
    parent_layout.removeWidget(selected_widget)
    selected_widget.setVisible(False)
    selected_widget.hide()
    # Don't delete - keep reference for restoration later
    print("[NEW MPR ZETA] Original widget removed from layout and hidden", file=sys.stderr, flush=True)

    print("Creating StandardMPRViewer...", file=sys.stderr, flush=True)
    try:
        new_mpr_zeta_widget = StandardMPRViewer(
            vtk_image_data=vtk_image_data,
            parent=parent_widget,
        )
        print("StandardMPRViewer created successfully", file=sys.stderr, flush=True)
    except Exception as e:
        print(f"ERROR creating StandardMPRViewer: {e}", file=sys.stderr, flush=True)
        import traceback
        traceback.print_exc(file=sys.stderr)
        raise

    # Set size policies BEFORE adding to layout
    print("[NEW MPR ZETA] Setting size policies...", file=sys.stderr, flush=True)
    new_mpr_zeta_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    parent_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    print(f"[NEW MPR ZETA] new_mpr_zeta_widget size policy: H={new_mpr_zeta_widget.sizePolicy().horizontalPolicy()}, V={new_mpr_zeta_widget.sizePolicy().verticalPolicy()}", file=sys.stderr, flush=True)
    print(f"[NEW MPR ZETA] parent_widget size policy: H={parent_widget.sizePolicy().horizontalPolicy()}, V={parent_widget.sizePolicy().verticalPolicy()}", file=sys.stderr, flush=True)

    print("Adding New MPR Zeta widget to grid at position (0, 0)...", file=sys.stderr, flush=True)
    print(f"new_mpr_zeta_widget parent before addWidget: {new_mpr_zeta_widget.parent()}", file=sys.stderr, flush=True)
    print(f"new_mpr_zeta_widget isVisible before addWidget: {new_mpr_zeta_widget.isVisible()}", file=sys.stderr, flush=True)

    # Add to layout at (0, 0)
    row = 0
    col = 0
    parent_layout.addWidget(new_mpr_zeta_widget, row, col)
    print("New MPR Zeta widget added to layout", file=sys.stderr, flush=True)

    # Configure layout stretching to give all space to this cell
    print(f"[NEW MPR ZETA] Setting row/column stretch for ({row}, {col})...", file=sys.stderr, flush=True)
    parent_layout.setRowStretch(row, 1)
    parent_layout.setColumnStretch(col, 1)
    
    # Activate layout and update geometry
    print("[NEW MPR ZETA] Activating layout and updating geometry...", file=sys.stderr, flush=True)
    parent_layout.activate()
    parent_widget.updateGeometry()
    parent_widget.repaint()

    print(f"new_mpr_zeta_widget parent after addWidget: {new_mpr_zeta_widget.parent()}", file=sys.stderr, flush=True)
    print(f"new_mpr_zeta_widget size after addWidget: {new_mpr_zeta_widget.size()}", file=sys.stderr, flush=True)
    print(f"new_mpr_zeta_widget isVisible after addWidget: {new_mpr_zeta_widget.isVisible()}", file=sys.stderr, flush=True)

    # Explicitly show the widget and raise it to top of z-order
    print("[NEW MPR ZETA] Calling show() on new_mpr_zeta_widget...", file=sys.stderr, flush=True)
    new_mpr_zeta_widget.show()
    new_mpr_zeta_widget.raise_()  # Raise to top of widget stack
    new_mpr_zeta_widget.update()
    parent_widget.update()
    
    # Force the widget to take focus and be visible
    new_mpr_zeta_widget.setFocus()
    print(f"[NEW MPR ZETA] After show(): size = {new_mpr_zeta_widget.size()}, visible = {new_mpr_zeta_widget.isVisible()}", file=sys.stderr, flush=True)
    print(f"[NEW MPR ZETA] Widget geometry: {new_mpr_zeta_widget.geometry()}", file=sys.stderr, flush=True)

    # Store references for restoration
    selected_widget._new_mpr_zeta_widget = new_mpr_zeta_widget
    selected_widget._original_visible = True
    new_mpr_zeta_widget._original_widget = selected_widget  # Back-reference to original
    
    print(f"[NEW MPR ZETA] Stored references: selected_widget._new_mpr_zeta_widget = {new_mpr_zeta_widget}", file=sys.stderr, flush=True)
    print(f"[NEW MPR ZETA] Stored references: new_mpr_zeta_widget._original_widget = {selected_widget}", file=sys.stderr, flush=True)

    # Update patient_widget's selected_widget to point to MPR for tool routing
    print("[NEW MPR ZETA] Updating patient_widget.selected_widget to new MPR Zeta widget...", file=sys.stderr, flush=True)
    toolbar_manager.patient_widget.selected_widget = new_mpr_zeta_widget
    logger.info(f"[NEW MPR ZETA] Updated patient_widget.selected_widget to {new_mpr_zeta_widget}")

    logger.info("New MPR Zeta viewer replaced viewport at grid position (0, 0)")
    print("New MPR Zeta viewer replaced viewport at grid position (0, 0)", file=sys.stderr, flush=True)
    print("replace_selected_viewport_with_new_mpr_zeta completed successfully", file=sys.stderr, flush=True)
