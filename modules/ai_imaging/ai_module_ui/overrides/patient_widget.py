import asyncio
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSlider, QWidget, QGroupBox, QVBoxLayout, QButtonGroup, QFrame

from PacsClient.pacs.patient_tab.ui import PatientWidget
from PacsClient.pacs.patient_tab.utils import NodeViewer, TYPES_VIEWER, VerticalButton, has_subfolders
from modules.ai_imaging.ai_module_ui.toolbar import ToolBarManager
from .vtk_widget import AIVTKWidget
from PacsClient.utils import CallerTypes
from PacsClient.utils.config import SOURCE_PATH
from modules.viewer.viewer_backend_config import BACKEND_VTK

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
        
        # Initialize parent class with 1×2 layout.
        # Eagle Eye REQUIRES the VTK / Advanced render pipeline (AI boxes,
        # overlays, segmentation). Force the VTK backend for this widget via
        # viewer_backend_override so it loads in Advanced mode even when the
        # global 2D viewer is set to FAST. The ViewerController honours this
        # per-widget override (see _vc_backend._get_requested_viewer_backend).
        super().__init__(parent, str(import_folder_path), size_init_viewers=(1, 2),
                         caller=CallerTypes.IMPORT, viewer_backend_override=BACKEND_VTK)
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
                                vtk_widget=None, slider=None, allow_paired=True, **kwargs):
        """
        Override to mirror a series onto both viewers for mammography.

        For MG the left viewer shows AI boxes and the right viewer the
        original image, so a series loaded on one viewer is synced to the
        other.

        The signature mirrors the base change_series_on_viewer exactly. An
        earlier version declared a non-existent target_viewer_id parameter
        and forwarded it positionally into the base vtk_widget slot; on a
        drag-and-drop (which passes vtk_widget= as a keyword) that raised
        TypeError, the drop silently failed and the viewer stayed stuck on
        its loading spinner.

        CRASH-HARDENING (Eagle Eye drag-drop, native fault 0x8001010d):
        The previous implementation ran the mirror super().change_series_on_viewer
        call SYNCHRONOUSLY immediately after the primary switch. On a drag-drop
        this stacked two full VTK series loads (with paint/render events) into
        the same event-loop turn, while the Windows OLE drop's COM context was
        still settling — observed as a fatal RPC_E_CANTCALLOUT_ININPUTSYNCCALL
        crash in `user_data/logs/native_fault.log`. The mirror call is now
        deferred via QTimer.singleShot(0) so it runs on the next event-loop
        iteration, after the primary switch's paint/render and the OLE drop
        context have fully released. Each step is also individually guarded so
        a failure on the mirror viewer can never propagate back into the drop
        completion path on the primary viewer.
        """
        # Tolerate a legacy target_viewer_id keyword but never forward it.
        kwargs.pop('target_viewer_id', None)

        result = super().change_series_on_viewer(
            series_index, flag_change_selected_widget, vtk_widget, slider, allow_paired,
        )

        # For MG, mirror the same series onto the other viewer — DEFERRED.
        try:
            if hasattr(self, 'lst_node_viewers') and len(self.lst_node_viewers) >= 2:
                if 0 <= series_index < len(self.lst_thumbnails_data):
                    modality = str(
                        self.lst_thumbnails_data[series_index].get('modality', '')
                    ).upper()
                    if modality == 'MG':
                        self._schedule_mg_mirror(
                            series_index=series_index,
                            primary_vtk_widget=vtk_widget,
                            allow_paired=allow_paired,
                        )
        except Exception as e:
            logger.warning(f"[MG] viewer sync after series change failed: {e}")

        return result

    def _schedule_mg_mirror(self, *, series_index, primary_vtk_widget, allow_paired):
        """Mirror MG series load onto every other viewer, on a later event tick.

        Runs on a 0-ms QTimer so the primary switch's VTK paint/render and the
        OLE drag-drop's COM context have fully released before we kick the
        second heavy series load. See change_series_on_viewer docstring for
        the crash-hardening context.
        """
        def _do_mirror():
            try:
                node_list = list(getattr(self, 'lst_node_viewers', []) or [])[:2]
            except Exception:
                return
            for node in node_list:
                try:
                    node_widget = getattr(node, 'vtk_widget', None)
                except Exception:
                    node_widget = None
                if node_widget is None or node_widget is primary_vtk_widget:
                    continue
                try:
                    # Cheap shiboken liveness probe — guards against the
                    # mirror viewer being torn down between schedule and fire.
                    _ = node_widget.objectName()
                except Exception:
                    continue
                try:
                    super(AIPatientWidget, self).change_series_on_viewer(
                        series_index,
                        flag_change_selected_widget=False,
                        vtk_widget=node_widget,
                        slider=getattr(node, 'slider', None),
                        allow_paired=allow_paired,
                    )
                except Exception as mirror_err:
                    logger.warning(
                        "[MG] mirror series=%s onto secondary viewer failed: %s",
                        series_index, mirror_err,
                    )

        try:
            QTimer.singleShot(0, _do_mirror)
        except Exception as sched_err:
            # If scheduling itself fails, fall back to a synchronous mirror
            # rather than silently skipping it — preserves prior behavior.
            logger.warning("[MG] mirror scheduling failed (%s); running inline", sched_err)
            try:
                _do_mirror()
            except Exception:
                pass

