import asyncio
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSlider, QWidget, QGroupBox, QVBoxLayout, QButtonGroup, QFrame

from PacsClient.pacs.patient_tab.ui import PatientWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer, TYPES_VIEWER, VerticalButton, has_subfolders
from modules.ai_imaging.ai_module_ui.toolbar import ToolBarManager
from .vtk_widget import AIVTKWidget
from PacsClient.utils import CallerTypes
from PacsClient.utils.config import SOURCE_PATH

import logging

logger = logging.getLogger(__name__)


class AIPatientWidget(PatientWidget):
    """
    AI Module Patient Widget - extends base PatientWidget with AI-specific functionality
    Removes all duplicated code and properly inherits from base class
    """
    
    def __init__(self, parent=None, study_uid: str = None, imaging_tab_ui=None):
        # Set up AI-specific properties
        self.type_viewer = None
        self.imaging_tab_ui = imaging_tab_ui
        
        # Determine import folder path based on study_uid
        sample_study = Path.cwd() / r'sample_files\sample dicom/2.16.840.1.113669.632.20.20250825.152409026.1.1'
        import_folder_path = sample_study

        logger.debug('[MG][INIT] ╔═══════════════════════════════════════')
        logger.debug(f'[MG][INIT] ║ AIPatientWidget.__init__ called')
        logger.debug(f'[MG][INIT] ║ study_uid: {study_uid}')

        try:
            if study_uid:
                study_path = SOURCE_PATH / study_uid  # source path
                if study_path.exists() and has_subfolders(study_path):  # really study existed
                    import_folder_path = study_path  # load a selected study
                    logger.debug(f'[MG][INIT] ║ ✓ Study path found: {study_path}')
        except Exception as e:
            logger.debug(f'[MG][INIT] ║ ❌ Error in override patient widget: {e}')
            import_folder_path = sample_study

        # ⚠️ IMPORTANT: Always start with 1×2 layout for mammography
        # If the series is not MG, we'll hide the second viewer later
        logger.debug(f'[MG][INIT] ║ Initializing with 1×2 layout (for mammography)')
        logger.debug(f'[MG][INIT] ╚═══════════════════════════════════════')
        
        # Initialize parent class with 1×2 layout
        super().__init__(parent, str(import_folder_path), size_init_viewers=(1, 2), caller=CallerTypes.IMPORT)
        self.ordering_by_instances_number = False

    def header_layout_ui(self):
        """Override to use AI-specific toolbar manager"""
        self.toolbar_manager = ToolBarManager(self)

    def get_optimal_layout_for_series(self, metadata: dict) -> tuple:
        """
        Override to return optimal layout for AI module analysis view
        For MG (mammography): 1x2 layout (1 row, 2 columns)
          - Left viewer: with AI boxes (your_viewer)
          - Right viewer: without boxes (fixed_viewer) to see original image
        For other modalities: 1x1 layout
        """
        modality = metadata.get('series', {}).get('modality', '').upper()
        logger.debug(f"[MG][LAYOUT] ╔═══════════════════════════════════════")
        logger.debug(f"[MG][LAYOUT] ║ get_optimal_layout_for_series called")
        logger.debug(f"[MG][LAYOUT] ║ modality: {modality}")
        
        if modality == 'MG':
            logger.debug(f"[MG][LAYOUT] ║ ✓ Returning 1×2 layout for mammography")
            logger.debug(f"[MG][LAYOUT] ║ Both viewers will be visible")
            logger.debug(f"[MG][LAYOUT] ╚═══════════════════════════════════════")
            self._ensure_both_viewers_visible()
            return (1, 2)
        else:
            logger.debug(f"[MG][LAYOUT] ║ Returning 1×1 layout for non-MG modality")
            logger.debug(f"[MG][LAYOUT] ║ Hiding second viewer")
            logger.debug(f"[MG][LAYOUT] ╚═══════════════════════════════════════")
            self._hide_second_viewer_if_exists()
            return (1, 1)

    def _ensure_both_viewers_visible(self):
        """Ensure both viewers are visible for MG modality"""
        try:
            if hasattr(self, 'lst_node_viewers') and len(self.lst_node_viewers) >= 2:
                logger.debug(f"[MG][LAYOUT] Making both viewers visible")
                for i, node in enumerate(self.lst_node_viewers[:2]):
                    if node and node.widget:
                        node.widget.setVisible(True)
                        logger.debug(f"[MG][LAYOUT] ✓ Viewer {i+1} visible")
        except Exception as e:
            logger.debug(f"[MG][LAYOUT] ❌ Error ensuring viewers visible: {e}")

    def _hide_second_viewer_if_exists(self):
        """Hide second viewer for non-MG modalities"""
        try:
            if hasattr(self, 'lst_node_viewers') and len(self.lst_node_viewers) >= 2:
                logger.debug(f"[MG][LAYOUT] Hiding second viewer (Original View)")
                second_node = self.lst_node_viewers[1]
                if second_node and second_node.widget:
                    second_node.widget.setVisible(False)
                    logger.debug(f"[MG][LAYOUT] ✓ Second viewer hidden")
        except Exception as e:
            logger.debug(f"[MG][LAYOUT] ❌ Error hiding second viewer: {e}")

    def _get_default_layout_from_config(self, modality: str = None) -> tuple:
        """
        Override default layout for AI imaging tab.
        We always start with 1×2 layout and hide/show viewers based on modality
        """
        # Always return 1×2 - we'll hide the second viewer if not needed
        logger.debug(f"[MG][LAYOUT] _get_default_layout_from_config: modality={modality}, returning (1, 2)")
        return (1, 2)

    def _get_requested_viewer_backend(self) -> str:
        """Always use Advanced (VTK) backend — Eagle Eye requires the VTK render pipeline."""
        from modules.viewer.viewer_backend_config import BACKEND_VTK
        return BACKEND_VTK

    def creator_vtk_widget(self):
        """Override to create AI-specific VTK widget"""
        height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
        return AIVTKWidget(height_viewer=height, patient_widget=self, type_viewer=self.type_viewer)

    def create_dummy_vtk_widget(self):
        """AI-specific lightweight placeholder using AIVTKWidget."""
        try:
            vtk_widget = self.creator_vtk_widget()
            if vtk_widget is None:
                raise RuntimeError("creator_vtk_widget returned None")

            if hasattr(vtk_widget, 'renderer'):
                vtk_widget.renderer.SetBackground(0.10, 0.10, 0.18)
                if hasattr(vtk_widget, 'render_window'):
                    vtk_widget.render_window.Render()

            if hasattr(vtk_widget, 'render_window'):
                vtk_widget.render_window.SetDesiredUpdateRate(0.001)

            vtk_widget._is_placeholder = True
            return vtk_widget
        except Exception as e:
            print(f"❌ Error creating AI placeholder VTK widget: {e}")
            return super().create_dummy_vtk_widget()

    def update_sidebar_ui(self, lst_boxes_object):
        """AI-specific method to update sidebar with box objects"""
        logger.debug(f"[MG][SIDEBAR] update_sidebar_ui called with {len(lst_boxes_object)} boxes")
        
        for idx, box_object in enumerate(lst_boxes_object):
            logger.debug(f"[MG][SIDEBAR] Box {idx}:")
            logger.debug(f"  - name: {box_object.box_name}")
            logger.debug(f"  - status: {box_object.status_abnormal}")
            logger.debug(f"  - classification_label: {box_object.classification_label}")
            logger.debug(f"  - classification type: {type(box_object.classification_label)}")
            
            # Create features text from classification
            features_text = ""
            if box_object.classification_label:
                if isinstance(box_object.classification_label, list):
                    features_text = "Classification:\n" + "\n".join(f"  • {item}" for item in box_object.classification_label)
                else:
                    features_text = f"Classification:\n  • {box_object.classification_label}"
                logger.debug(f"[MG][SIDEBAR] Generated features text: {features_text}")
            
            if self.imaging_tab_ui:
                logger.debug(f"[MG][SIDEBAR] Calling sidebar_upsert_item for box {idx}...")
                self.imaging_tab_ui.sidebar_upsert_item(
                    key=box_object.box_name, 
                    status=box_object.status_abnormal,
                    box_object=box_object, 
                    classification=box_object.classification_label,
                    features=features_text  # Add classification to features box
                )
                logger.debug(f"[MG][SIDEBAR] ✓ sidebar_upsert_item completed for box {idx}")
            else:
                logger.debug(f"[MG][SIDEBAR] ❌ imaging_tab_ui is None, cannot update sidebar")

    def sidebar_clear(self):
        """AI-specific method to clear sidebar"""
        import traceback
        stack = ''.join(traceback.format_stack()[-5:-1])  # Get last 4 stack frames
        logger.debug(f"[MG][SIDEBAR_CLEAR] ╔═══════════════════════════════════════")
        logger.debug(f"[MG][SIDEBAR_CLEAR] ║ sidebar_clear() called!")
        logger.debug(f"[MG][SIDEBAR_CLEAR] ║ Call stack:")
        logger.debug(stack)
        logger.debug(f"[MG][SIDEBAR_CLEAR] ╚═══════════════════════════════════════")
        if self.imaging_tab_ui:
            self.imaging_tab_ui.sidebar_clear()

    def create_some_viewers(self, count):
        """AI-specific method to create viewers with custom names"""
        logger.debug(f"[MG][LAYOUT] ╔═══════════════════════════════════════")
        logger.debug(f"[MG][LAYOUT] ║ create_some_viewers called with count={count}")
        
        index_series_show = 0  # create viewers that all of them show first series of thumbnails
        lst_names_viewer = [TYPES_VIEWER.your_viewer, TYPES_VIEWER.fixed_viewer]
        
        for i in range(count):
            self.type_viewer = lst_names_viewer[i]
            logger.debug(f"[MG][LAYOUT] ║ Creating viewer {i+1}/{count}: type={self.type_viewer}")
            new_node: NodeViewer = self.new_viewer(index_series_show)

            # replace default widget with groupbox widget (for add name viewer)
            main_layout = new_node.widget.layout()
            if main_layout:
                main_layout.setContentsMargins(0, 10, 0, 10)

                temp_groupbox = QGroupBox(lst_names_viewer[i])
                temp_groupbox.setLayout(main_layout)
                new_node.change_main_widget(temp_groupbox)
                logger.debug(f"[MG][LAYOUT] ║ ✓ Viewer {i+1} created: {lst_names_viewer[i]}")
        
        logger.debug(f"[MG][LAYOUT] ╚═══════════════════════════════════════")

    def manage_reference_line(self):
        """Override to disable reference lines for AI module"""
        pass  # turn off reference lines for AI

    def change_series_on_viewer(self, series_index, flag_change_selected_widget=True,
                                 target_viewer_id=None, **kwargs):
        """
        Override to sync both viewers when a series is dropped on one viewer.
        For MG: Both viewers show the same series - one with boxes, one without.
        """
        logger.debug(f"[MG][SERIES_CHANGE] ╔═══════════════════════════════════════")
        logger.debug(f"[MG][SERIES_CHANGE] ║ change_series_on_viewer called")
        logger.debug(f"[MG][SERIES_CHANGE] ║ series_index: {series_index}")
        logger.debug(f"[MG][SERIES_CHANGE] ║ target_viewer_id: {target_viewer_id}")
        
        # First, call parent to change the series on the target viewer
        result = super().change_series_on_viewer(series_index, flag_change_selected_widget, 
                                                   target_viewer_id, **kwargs)
        
        # For MG modality: sync the other viewer to show the same series
        try:
            if hasattr(self, 'lst_node_viewers') and len(self.lst_node_viewers) >= 2:
                # Check if the series is MG
                if series_index < len(self.lst_thumbnails_data):
                    series_metadata = self.lst_thumbnails_data[series_index]
                    modality = series_metadata.get('modality', '').upper()
                    
                    logger.debug(f"[MG][SERIES_CHANGE] ║ Series modality: {modality}")
                    
                    if modality == 'MG':
                        logger.debug(f"[MG][SERIES_CHANGE] ║ ✓ MG modality detected - syncing both viewers")
                        
                        # Load the same series on both viewers
                        for i, node in enumerate(self.lst_node_viewers[:2]):
                            if node and node.vtk_widget:
                                viewer_type = getattr(node.vtk_widget, 'type_viewer', 'Unknown')
                                logger.debug(f"[MG][SERIES_CHANGE] ║   Loading series {series_index} on viewer {i+1} ({viewer_type})")
                                
                                # Call the parent's method to load series on this specific viewer
                                super(AIPatientWidget, self).change_series_on_viewer(
                                    series_index, 
                                    flag_change_selected_widget=False,  # Don't change selection
                                    target_viewer_id=node.id_vtk_widget,
                                    **kwargs
                                )
                        
                        logger.debug(f"[MG][SERIES_CHANGE] ║ ✓ Both viewers synced to series {series_index}")
        except Exception as e:
            logger.debug(f"[MG][SERIES_CHANGE] ║ ❌ Error syncing viewers: {e}")
            import traceback
            traceback.print_exc()
        
        logger.debug(f"[MG][SERIES_CHANGE] ╚═══════════════════════════════════════")
        return result
