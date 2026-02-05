"""
PatientWidget - Refactored Version
==================================
This module contains a refactored version of the series loading and display logic.
Duplicate and overlapping methods have been consolidated into clean, unified methods.

Key Changes:
- Consolidated all series loading methods into `load_series()`
- Consolidated all display methods into `display_series_in_viewer()`
- Consolidated all viewer creation methods into `create_viewer_layout()`
- Removed duplicate method definitions
- Added proper error handling and logging
- Improved async/sync handling

Author: Refactored for better maintainability
"""

import asyncio
import gc
import logging
import threading
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QSlider

logger = logging.getLogger(__name__)


class SeriesLoaderMixin:
    """
    Mixin class containing all series loading logic.
    Consolidates multiple overlapping methods into unified interfaces.
    """

    # ============================================================================
    # UNIFIED SERIES LOADING - Single entry point for all loading operations
    # ============================================================================
    
    def load_series(
        self,
        series_number: int,
        study_path: str = None,
        async_mode: bool = False,
        on_complete: callable = None
    ) -> bool:
        """
        UNIFIED method to load a single series.
        This replaces: _load_single_series_on_demand, load_series_on_demand,
                       _load_first_series_sync, load_series_immediately
        
        Args:
            series_number: The series number to load
            study_path: Path to the study folder (optional, uses self.import_folder_path if None)
            async_mode: If True, loads in background thread
            on_complete: Callback function when loading completes (for async mode)
        
        Returns:
            bool: True if loaded successfully (sync mode) or task started (async mode)
        """
        try:
            # Check if already loaded
            series_key = f"series_{series_number}"
            if series_key in self.lst_series_name:
                logger.debug(f"Series {series_number} already loaded, skipping")
                if on_complete:
                    on_complete(True, series_number)
                return True

            # Resolve study path
            resolved_path = self._resolve_study_path(study_path)
            if not resolved_path:
                logger.error(f"Cannot resolve study path for series {series_number}")
                return False

            # Verify series folder exists
            series_folder = Path(resolved_path) / str(series_number)
            if not series_folder.exists():
                logger.error(f"Series folder not found: {series_folder}")
                return False

            # Check for DICOM files
            dicom_files = list(series_folder.glob("*.dcm")) + list(series_folder.glob("*.DCM"))
            if not dicom_files:
                logger.error(f"No DICOM files in {series_folder}")
                return False

            if async_mode:
                return self._load_series_async(series_number, resolved_path, on_complete)
            else:
                return self._load_series_sync(series_number, resolved_path)

        except Exception as e:
            logger.error(f"Error loading series {series_number}: {e}", exc_info=True)
            return False

    def _resolve_study_path(self, study_path: str = None) -> Optional[str]:
        """Resolve and validate the study path."""
        if study_path and Path(study_path).exists():
            return str(study_path)
        
        if self.import_folder_path and Path(self.import_folder_path).exists():
            path = Path(self.import_folder_path)
            # Check if current path is at study level (has series subfolders)
            series_folders = [d for d in path.iterdir() if d.is_dir() and d.name.isdigit()]
            if series_folders:
                return str(path)
            # Maybe we're inside a series folder, go up
            if path.name.isdigit() and path.parent.exists():
                return str(path.parent)
            return str(path)
        
        return None

    def _load_series_sync(self, series_number: int, study_path: str) -> bool:
        """Synchronous series loading implementation."""
        from PacsClient.pacs.patient_tab.utils.image_io import load_single_series_by_number
        
        start_time = time.time()
        logger.info(f"[LOAD] Loading series {series_number} from {study_path}")

        try:
            result = load_single_series_by_number(
                study_path=study_path,
                series_number=series_number,
                patient_pk=self.metadata_fixed.get('patient_pk'),
                study_pk=self.metadata_fixed.get('study_pk'),
                ordering_by_instances_number=self.ordering_by_instances_number,
            )

            if not result:
                return False

            # Process results
            for vtk_image_data, metadata, (patient_pk, study_pk) in result:
                self._process_loaded_series(vtk_image_data, metadata, patient_pk, study_pk)

            elapsed = time.time() - start_time
            logger.info(f"[LOAD] Series {series_number} loaded in {elapsed:.3f}s")
            return True

        except Exception as e:
            logger.error(f"[LOAD] Error loading series {series_number}: {e}", exc_info=True)
            return False

    def _load_series_async(self, series_number: int, study_path: str, on_complete: callable) -> bool:
        """Asynchronous series loading implementation."""
        def load_task():
            try:
                success = self._load_series_sync(series_number, study_path)
                if on_complete:
                    QTimer.singleShot(0, lambda: on_complete(success, series_number))
            except Exception as e:
                logger.error(f"Async load error: {e}")
                if on_complete:
                    QTimer.singleShot(0, lambda: on_complete(False, series_number))

        # Try asyncio first, fall back to threading
        try:
            loop = asyncio.get_running_loop()
            asyncio.create_task(asyncio.to_thread(load_task))
        except RuntimeError:
            thread = threading.Thread(target=load_task, daemon=True)
            thread.start()
        
        return True

    def _process_loaded_series(
        self,
        vtk_image_data,
        metadata: dict,
        patient_pk: int,
        study_pk: int
    ):
        """Process and store a loaded series."""
        # Update metadata_fixed if needed
        if not self.metadata_fixed or len(self.metadata_fixed) < 3:
            if metadata and 'instances' in metadata and metadata['instances']:
                first_instance_path = metadata['instances'][0].get('instance_path')
                if first_instance_path and Path(first_instance_path).exists():
                    from PacsClient.pacs.patient_tab.utils.utils import get_meta_fixed
                    self.metadata_fixed = get_meta_fixed(first_instance_path)
                    if patient_pk:
                        self.metadata_fixed['patient_pk'] = patient_pk
                    if study_pk:
                        self.metadata_fixed['study_pk'] = study_pk

        # Add to thumbnails list
        file_path = metadata['series'].get('thumbnail_path', '')
        new_data = {
            'vtk_image_data': vtk_image_data,
            'metadata': metadata,
            'file_path': file_path
        }
        self.add_new_data_to_lst_thumbnails_data(new_data)

        # Mark series as loaded
        series_number = metadata['series']['series_number']
        self.lst_series_name.add(f"series_{series_number}")
        
        # Update thumbnail manager
        if hasattr(self, 'thumbnail_manager'):
            self.thumbnail_manager.set_series_ready(str(series_number))

    # ============================================================================
    # UNIFIED FIRST SERIES LOADING - For initial display
    # ============================================================================
    
    def load_first_series(self, layout: Tuple[int, int] = (1, 1), async_mode: bool = True):
        """
        UNIFIED method to load the first available series.
        This replaces: lazy_load_first_series, lazy_load_first_series_progressive,
                       _load_first_series_sync (both definitions), _do_lazy_load_first_series
        
        Args:
            layout: Viewer layout as (rows, cols)
            async_mode: If True, loads asynchronously
        """
        if async_mode:
            try:
                loop = asyncio.get_running_loop()
                task = asyncio.create_task(self._load_first_series_impl(layout))
                self._background_tasks.add(task)
                task.add_done_callback(self._background_tasks.discard)
            except RuntimeError:
                # No event loop, use sync mode
                self._load_first_series_impl_sync(layout)
        else:
            self._load_first_series_impl_sync(layout)

    async def _load_first_series_impl(self, layout: Tuple[int, int]):
        """Async implementation of first series loading."""
        try:
            study_path = Path(self.import_folder_path) if self.import_folder_path else None
            if not study_path or not study_path.exists():
                logger.warning("No valid study path for first series loading")
                return

            # Find existing series folders
            existing_series = sorted(
                int(d.name) for d in study_path.iterdir()
                if d.is_dir() and d.name.isdigit() and self._has_dicom_files(d)
            )

            if not existing_series:
                # Wait for download if in progressive mode
                if self._progressive_display_enabled:
                    first_series = await self._wait_for_series_download(timeout=60)
                    if first_series:
                        existing_series = [first_series]

            if not existing_series:
                logger.warning("No series found to load")
                return

            # Load first series
            first_series_num = existing_series[0]
            success = await asyncio.to_thread(
                self._load_series_sync, first_series_num, str(study_path)
            )

            if success:
                # Create viewers and display
                self.create_viewer_layout(layout)
                self.display_series_in_viewer(first_series_num)
                QTimer.singleShot(200, self._hide_init_overlay)

        except Exception as e:
            logger.error(f"Error in first series loading: {e}", exc_info=True)

    def _load_first_series_impl_sync(self, layout: Tuple[int, int]):
        """Sync implementation of first series loading."""
        try:
            from PacsClient.pacs.patient_tab.utils import load_images

            for vtk_image_data, metadata, patient_info in load_images(
                self.import_folder_path,
                patient_pk=self.metadata_fixed.get('patient_pk'),
                study_pk=self.metadata_fixed.get('study_pk'),
                ordering_by_instances_number=self.ordering_by_instances_number
            ):
                QApplication.processEvents()
                
                self.check_and_add_meta_fixed(patient_info)
                
                file_path = metadata['series'].get('thumbnail_path', '')
                new_data = {
                    'vtk_image_data': vtk_image_data,
                    'metadata': metadata,
                    'file_path': file_path
                }
                self.add_new_data_to_lst_thumbnails_data(new_data)

                # Determine optimal layout
                optimal_layout = self.get_optimal_layout_for_series(metadata)
                
                # Create viewers
                self.create_viewer_layout(optimal_layout)
                
                # Mark as ready
                series_no = metadata['series']['series_number']
                self.thumbnail_manager.set_series_ready(str(series_no))
                
                if file_path and not self.logo_patient:
                    self.logo_patient = file_path
                    self.update_tab_manager()

                break  # Only load first series

        except Exception as e:
            logger.error(f"Error in sync first series loading: {e}", exc_info=True)

    def _has_dicom_files(self, folder: Path) -> bool:
        """Check if folder contains DICOM files."""
        return bool(next(folder.glob("*.dcm"), None) or next(folder.glob("*.DCM"), None))


class SeriesDisplayMixin:
    """
    Mixin class containing all series display logic.
    Consolidates multiple overlapping display methods.
    """

    # ============================================================================
    # UNIFIED SERIES DISPLAY - Single entry point for all display operations
    # ============================================================================
    
    def display_series_in_viewer(
        self,
        series_number: int,
        viewer_index: int = 0,
        force_reload: bool = False
    ) -> bool:
        """
        UNIFIED method to display a series in a viewer.
        This replaces: display_series, change_series_on_viewer, _display_series_after_load,
                       _display_loaded_series, _display_first_series_in_viewer,
                       _perform_series_switch, _try_display_priority_series
        
        Args:
            series_number: The series number to display
            viewer_index: Which viewer to display in (default: 0)
            force_reload: Force reload even if already displayed
        
        Returns:
            bool: True if displayed successfully
        """
        try:
            series_key = str(series_number)
            
            # Get series data
            vtk_image_data, metadata, series_idx = self._get_series_data(series_number)
            
            if metadata is None:
                # Try to load the series first
                logger.info(f"Series {series_number} not in memory, loading...")
                if not self.load_series(series_number):
                    logger.warning(f"Failed to load series {series_number}")
                    return False
                vtk_image_data, metadata, series_idx = self._get_series_data(series_number)
                if metadata is None:
                    return False

            # Ensure viewers exist
            if not self.lst_nodes_viewer:
                logger.warning("No viewers available, creating default layout")
                self.create_viewer_layout((1, 1))

            # Get target viewer
            viewer_index = min(viewer_index, len(self.lst_nodes_viewer) - 1)
            viewer = self.lst_nodes_viewer[viewer_index]

            # Check for combined series (same name, different data)
            vtk_data_2, metadata_2 = self._find_paired_series(metadata)

            # Perform the switch
            success = False
            if hasattr(viewer, 'switch_series'):
                success = viewer.switch_series(
                    vtk_image_data,
                    metadata,
                    series_idx,
                    vtk_data_2,
                    metadata_2,
                    self.metadata_fixed
                )
            elif hasattr(viewer.vtk_widget, 'display_image'):
                viewer.vtk_widget.display_image(vtk_image_data, metadata)
                success = True

            if success:
                self._finalize_display(viewer, series_number)
                return True
            else:
                logger.error(f"Failed to display series {series_number}")
                return False

        except Exception as e:
            logger.error(f"Error displaying series {series_number}: {e}", exc_info=True)
            return False

    def _get_series_data(self, series_number: int) -> Tuple[Any, dict, int]:
        """Get series data from loaded thumbnails."""
        if not hasattr(self, 'lst_thumbnails_data'):
            self.lst_thumbnails_data = []
            
        for i, data in enumerate(self.lst_thumbnails_data):
            if str(data['metadata']['series']['series_number']) == str(series_number):
                return data['vtk_image_data'], data['metadata'], i
        return None, None, -1

    def _find_paired_series(self, metadata: dict) -> Tuple[Any, dict]:
        """Find paired series with same name but different data."""
        if not hasattr(self, 'lst_thumbnails_data'):
            return None, None
            
        series_name = metadata['series']['series_name']
        series_number = metadata['series']['series_number']
        
        for data in self.lst_thumbnails_data:
            if (data['metadata']['series']['series_name'] == series_name and
                data['metadata']['series']['series_number'] != series_number):
                return data['vtk_image_data'], data['metadata']
        return None, None

    def _finalize_display(self, viewer, series_number: int):
        """Finalize display after successful series switch."""
        # Set as main viewer if first viewer
        viewer_idx = self.lst_nodes_viewer.index(viewer) if viewer in self.lst_nodes_viewer else 0
        if viewer_idx == 0:
            self.set_viewer_to_main_viewer(viewer)

        # Reset slider
        if hasattr(viewer, 'slider') and viewer.slider:
            self.reset_slider(viewer.vtk_widget, viewer.slider)

        # Update thumbnail manager
        if hasattr(self, 'thumbnail_manager'):
            self.thumbnail_manager.set_series_ready(str(series_number))
            self.thumbnail_manager.apply_border_states_new()

        # Turn off tools and update UI
        if hasattr(self, 'toolbar_manager'):
            self.toolbar_manager.turn_off_all_tools()

        # Update corners
        if viewer.vtk_widget.image_viewer is not None:
            viewer.vtk_widget.image_viewer.update_corners_actors()

        # Render
        if hasattr(viewer.vtk_widget, 'GetRenderWindow'):
            viewer.vtk_widget.GetRenderWindow().Render()

        logger.info(f"Series {series_number} displayed successfully")


class ViewerLayoutMixin:
    """
    Mixin class containing all viewer layout/creation logic.
    Consolidates multiple overlapping viewer creation methods.
    """

    # ============================================================================
    # UNIFIED VIEWER LAYOUT - Single entry point for viewer creation
    # ============================================================================
    
    def create_viewer_layout(
        self,
        layout: Tuple[int, int],
        preserve_data: bool = True
    ):
        """
        UNIFIED method to create viewer layout.
        This replaces: _apply_multi_viewer_sync, _create_viewers_sync,
                       create_progressive_viewers, apply_multi_viewer
        
        Args:
            layout: Tuple of (rows, cols)
            preserve_data: If True, tries to preserve and redistribute existing data
        """
        try:
            rows, cols = int(layout[0]), int(layout[1])
            total_viewers = rows * cols
            
            logger.info(f"[LAYOUT] Creating {rows}x{cols} layout ({total_viewers} viewers)")

            # Cleanup existing viewers
            self.cleanup_all_viewers()
            self.lst_nodes_viewer.clear()
            QApplication.processEvents()

            # Create new viewers
            for i in range(total_viewers):
                try:
                    # Use existing data if available
                    data_index = i % len(self.lst_thumbnails_data) if self.lst_thumbnails_data else 0
                    node = self.new_viewer(data_index)
                except Exception as e:
                    logger.warning(f"Viewer {i} creation failed: {e}, using fallback")
                    node = self._create_fallback_viewer()
                    self.lst_nodes_viewer.append(node)
                
                # Allow UI to breathe
                if i % 2 == 0:
                    QApplication.processEvents()

            # Arrange in grid
            for idx, node in enumerate(self.lst_nodes_viewer):
                if idx >= total_viewers:
                    break
                row, col = divmod(idx, cols)
                self.vtk_layout.addWidget(node.widget, row, col)

            # Distribute series to viewers
            if preserve_data and self.lst_thumbnails_data:
                self._distribute_series_to_all_viewers()

            # Set first viewer as active
            if self.lst_nodes_viewer:
                self.change_container_border(0)

            logger.info(f"[LAYOUT] Completed {rows}x{cols} layout with {len(self.lst_nodes_viewer)} viewers")

        except Exception as e:
            logger.error(f"[LAYOUT] Error creating layout: {e}", exc_info=True)

    def _create_fallback_viewer(self):
        """Create a minimal fallback viewer when normal creation fails."""
        from PySide6.QtWidgets import QFrame, QGridLayout, QSlider
        from PacsClient.pacs.patient_tab.utils import NodeViewer
        
        layout = QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        
        vtk_widget = self.create_dummy_vtk_widget()
        slider = QSlider(Qt.Vertical, vtk_widget)
        slider.setInvertedAppearance(True)
        
        layout.addWidget(vtk_widget, 0, 0)
        layout.addWidget(slider, 0, 0, alignment=Qt.AlignRight)
        
        container = QFrame()
        container.setObjectName("ViewportContainer")
        container.setLayout(layout)
        container.setFrameStyle(QFrame.Box | QFrame.Plain)
        container.setLineWidth(2)
        
        return NodeViewer(container, vtk_widget, slider)

    def _distribute_series_to_all_viewers(self):
        """Distribute loaded series across all viewers."""
        if not self.lst_nodes_viewer or not self.lst_thumbnails_data:
            return

        displayed_series = set()
        
        for viewer_idx, node_viewer in enumerate(self.lst_nodes_viewer):
            # Skip viewers that already have content
            if (hasattr(node_viewer.vtk_widget, 'last_series_show') and 
                node_viewer.vtk_widget.last_series_show is not None):
                displayed_series.add(node_viewer.vtk_widget.last_series_show)
                continue

            # Find an undisplayed series
            series_to_show = None
            series_index = None
            
            for i, data in enumerate(self.lst_thumbnails_data):
                series_num = data['metadata']['series']['series_number']
                if series_num not in displayed_series:
                    series_to_show = data
                    series_index = i
                    displayed_series.add(series_num)
                    break

            # Fall back to cycling through series
            if series_to_show is None and self.lst_thumbnails_data:
                series_index = viewer_idx % len(self.lst_thumbnails_data)
                series_to_show = self.lst_thumbnails_data[series_index]

            if series_to_show:
                self._display_in_single_viewer(node_viewer, series_to_show, series_index, viewer_idx)

    def _display_in_single_viewer(self, node_viewer, series_data: dict, series_index: int, viewer_idx: int):
        """Display a series in a single viewer."""
        try:
            success = node_viewer.switch_series(
                series_data['vtk_image_data'],
                series_data['metadata'],
                series_index,
                metadata_fixed=self.metadata_fixed
            )

            if success:
                # Set first viewer as main
                if viewer_idx == 0:
                    self.set_viewer_to_main_viewer(node_viewer)

                # Reset slider
                if hasattr(node_viewer, 'slider'):
                    self.reset_slider(node_viewer.vtk_widget, node_viewer.slider)

                # Update UI
                if node_viewer.vtk_widget.image_viewer:
                    node_viewer.vtk_widget.image_viewer.update_corners_actors()

                # Hide loading
                if hasattr(node_viewer.vtk_widget, 'viewport_spinner'):
                    node_viewer.vtk_widget.viewport_spinner.hide_loading()

                # Render
                if node_viewer.vtk_widget.image_viewer:
                    node_viewer.vtk_widget.image_viewer.Render()

                logger.debug(f"Viewer {viewer_idx} populated with series {series_data['metadata']['series']['series_number']}")

        except Exception as e:
            logger.warning(f"Failed to display in viewer {viewer_idx}: {e}")


class BatchLoaderMixin:
    """
    Mixin for batch/parallel loading operations.
    """

    def load_multiple_series(
        self,
        series_numbers: List[int],
        max_concurrent: int = 4,
        on_progress: callable = None,
        on_complete: callable = None
    ):
        """
        Load multiple series in parallel.
        
        Args:
            series_numbers: List of series numbers to load
            max_concurrent: Maximum concurrent loads
            on_progress: Callback(loaded_count, total_count) for progress
            on_complete: Callback(success_count, failed_count) when done
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        # Filter already loaded
        to_load = [sn for sn in series_numbers 
                   if f"series_{sn}" not in self.lst_series_name]
        
        if not to_load:
            if on_complete:
                on_complete(0, 0)
            return

        logger.info(f"[BATCH] Loading {len(to_load)} series (max {max_concurrent} concurrent)")
        
        loaded = 0
        failed = 0
        
        with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
            futures = {
                executor.submit(self.load_series, sn): sn 
                for sn in to_load
            }
            
            for i, future in enumerate(as_completed(futures), 1):
                series_num = futures[future]
                try:
                    if future.result():
                        loaded += 1
                    else:
                        failed += 1
                except Exception:
                    failed += 1
                
                if on_progress:
                    QTimer.singleShot(0, lambda l=loaded+failed, t=len(to_load): on_progress(l, t))

        logger.info(f"[BATCH] Complete: {loaded} loaded, {failed} failed")
        
        if on_complete:
            QTimer.singleShot(0, lambda: on_complete(loaded, failed))


# ============================================================================
# INTEGRATION - How to use these mixins in PatientWidget
# ============================================================================

"""
To integrate these mixins into PatientWidget:

1. Add the mixins to the class inheritance:

   class PatientWidget(QWidget, SeriesLoaderMixin, SeriesDisplayMixin, 
                       ViewerLayoutMixin, BatchLoaderMixin):
       ...

2. Remove the following duplicate/redundant methods from PatientWidget:
   - _load_first_series_sync (both definitions at lines 570 and 760)
   - load_series_immediately (both definitions at lines 833 and 990)
   - lazy_load_first_series
   - lazy_load_first_series_progressive
   - _do_lazy_load_first_series
   - _load_single_series_on_demand
   - load_series_on_demand
   - _async_load_and_display_series
   - _do_load_and_display_series
   - _do_load_series
   - _load_and_display_series_async
   - display_series (old version)
   - change_series_on_viewer (replace with display_series_in_viewer)
   - _display_series_after_load
   - _display_loaded_series
   - _display_first_series_in_viewer
   - _perform_series_switch
   - _try_display_priority_series
   - _apply_multi_viewer_sync
   - _create_viewers_sync
   - create_progressive_viewers
   - apply_multi_viewer

3. Update calls in the codebase:
   - load_series_immediately(sn, dir) → load_series(sn, dir)
   - change_series_on_viewer(sn) → display_series_in_viewer(sn)
   - _apply_multi_viewer_sync((r,c)) → create_viewer_layout((r,c))
   - etc.

4. The thumbnail_manager.change_series_on_viewer should call:
   self.display_series_in_viewer(series_number)
"""
