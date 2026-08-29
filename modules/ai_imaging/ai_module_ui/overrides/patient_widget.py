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
from modules.viewer.viewer_backend_config import BACKEND_PYDICOM_QT, BACKEND_VTK

import logging

logger = logging.getLogger(__name__)


def _normalize_eagle_eye_mode(mode):
    """Delegates to the shared authority (modules.ai_imaging.eagle_eye_modes)."""
    from modules.ai_imaging.eagle_eye_modes import normalize_eagle_eye_mode as _normalize
    return _normalize(mode)


# Lumbar MRI Eagle Eye: three panes, left to right, always in this order.
# The pane labels come from the capture pipeline's own slot vocabulary, so the
# caption a reader sees on screen and the slot name written into every manifest
# can never drift apart.
from modules.ai_imaging.eagle_eye_lumbar.constants import SLOT_LABELS, SLOT_ORDER

LUMBAR_LAYOUT = (1, 3)
LUMBAR_VIEWER_NAMES = tuple(SLOT_LABELS[slot] for slot in SLOT_ORDER)


def resolve_thumb_lat_view(thumb: dict) -> tuple:
    """
    Resolve (laterality, view_position) for a series thumbnail from the most
    reliable source, NOT from series order or viewer position.

    Order of authority (first non-empty wins):
      1. series metadata (already parsed from DICOM at load time), then
      2. the DICOM tags on the series' first instance file
         (ImageLaterality / Laterality, ViewPosition) — the ground truth.

    Returns uppercased single-letter laterality ('R'/'L') and view ('CC'/'MLO'/…),
    or ('', '') when neither source can determine it. Never raises.

    Bug #2 (2026-07-14): auto-pairing previously read ONLY series metadata; when a
    center's DICOM populated the tags but the metadata parse left them blank, the
    CC/MLO auto-pair silently failed. The DICOM fallback closes that gap without
    touching the shared loader.
    """
    lat, vp = "", ""
    try:
        smeta = (thumb.get("metadata", {}) or {}).get("series", {}) or {}
        lat = str(smeta.get("laterality", "") or "").upper().strip()
        vp = str(smeta.get("view_position", "") or "").upper().strip()
    except Exception:
        smeta = {}

    if lat and vp:
        return lat[:1], vp

    # Fall back to the DICOM tags on the first instance.
    try:
        instances = (thumb.get("metadata", {}) or {}).get("instances", []) or []
        inst_path = ""
        if instances and isinstance(instances[0], dict):
            inst_path = str(instances[0].get("instance_path", "") or "")
        if inst_path and Path(inst_path).is_file():
            import pydicom
            ds = pydicom.dcmread(inst_path, stop_before_pixels=True, force=True)
            if not lat:
                lat = str(getattr(ds, "ImageLaterality", None)
                          or getattr(ds, "Laterality", None) or "").upper().strip()
            if not vp:
                vp = str(getattr(ds, "ViewPosition", None) or "").upper().strip()
    except Exception as exc:
        logger.debug(f"[MG][VIEW-ID] DICOM fallback failed: {exc}")

    return (lat[:1] if lat else ""), vp


class AIPatientWidget(PatientWidget):
    """
    AI Module Patient Widget - extends base PatientWidget with AI-specific functionality
    Removes all duplicated code and properly inherits from base class
    """
    
    def __init__(self, parent=None, study_uid: str = None, imaging_tab_ui=None, eagle_eye_mode=None):
        # Set up AI-specific properties
        self.type_viewer = None
        self.imaging_tab_ui = imaging_tab_ui
        self.eagle_eye_mode = _normalize_eagle_eye_mode(eagle_eye_mode)
        
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

        if self.eagle_eye_mode == "bone_age":
            initial_layout = (1, 1)
        elif self.eagle_eye_mode == "lumbar_mri":
            initial_layout = LUMBAR_LAYOUT
        else:
            initial_layout = (1, 2)
        logger.debug(f'[MG][INIT] ║ Initializing with layout {initial_layout} for mode={self.eagle_eye_mode}')
        logger.debug(f'[MG][INIT] ╚═══════════════════════════════════════')
        
        # Initialize parent class with 1×2 layout.
        # Eagle Eye REQUIRES the VTK / Advanced render pipeline (AI boxes,
        # overlays, segmentation). Force the VTK backend for this widget via
        # viewer_backend_override so it loads in Advanced mode even when the
        # global 2D viewer is set to FAST. The ViewerController honours this
        # per-widget override (see _vc_backend._get_requested_viewer_backend).
        backend_override = BACKEND_PYDICOM_QT if self.eagle_eye_mode == "bone_age" else BACKEND_VTK
        super().__init__(parent, str(import_folder_path), size_init_viewers=initial_layout,
                         caller=CallerTypes.IMPORT, viewer_backend_override=backend_override)
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
        
        if self.eagle_eye_mode == "bone_age":
            logger.debug(f"[MG][LAYOUT] ║ Forced Bone Age mode, returning 1×1")
            self._hide_second_viewer_if_exists()
            return (1, 1)

        if self.eagle_eye_mode == "lumbar_mri":
            # The lumbar layout is fixed at Sag T2 | Sag T1 | Ax T2 and is never
            # re-derived from whichever series happens to load first: the three
            # panes ARE the capture frame.
            logger.debug(f"[MG][LAYOUT] ║ Lumbar MRI mode, returning {LUMBAR_LAYOUT}")
            self._ensure_lumbar_viewers_visible()
            return LUMBAR_LAYOUT

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

    def _ensure_lumbar_viewers_visible(self):
        """Keep all three lumbar panes visible - every capture needs all three."""
        try:
            nodes = list(getattr(self, 'lst_nodes_viewer', []) or [])[:3]
            for i, node in enumerate(nodes):
                if node and getattr(node, 'widget', None):
                    node.widget.setVisible(True)
                    logger.debug(f"[LUMBAR][LAYOUT] ✓ Viewer {i + 1} visible")
        except Exception as e:
            logger.debug(f"[LUMBAR][LAYOUT] ❌ Error ensuring lumbar viewers visible: {e}")

    def _ensure_both_viewers_visible(self):
        """Ensure both viewers are visible for MG modality"""
        try:
            if hasattr(self, 'lst_nodes_viewer') and len(self.lst_nodes_viewer) >= 2:
                logger.debug(f"[MG][LAYOUT] Making both viewers visible")
                for i, node in enumerate(self.lst_nodes_viewer[:2]):
                    if node and node.widget:
                        node.widget.setVisible(True)
                        logger.debug(f"[MG][LAYOUT] ✓ Viewer {i+1} visible")
        except Exception as e:
            logger.debug(f"[MG][LAYOUT] ❌ Error ensuring viewers visible: {e}")

    def _hide_second_viewer_if_exists(self):
        """Hide second viewer for non-MG modalities"""
        try:
            if hasattr(self, 'lst_nodes_viewer') and len(self.lst_nodes_viewer) >= 2:
                logger.debug(f"[MG][LAYOUT] Hiding second viewer (Original View)")
                second_node = self.lst_nodes_viewer[1]
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
        if self.eagle_eye_mode == "bone_age":
            logger.debug(f"[MG][LAYOUT] _get_default_layout_from_config: mode=bone_age, returning (1, 1)")
            return (1, 1)
        if self.eagle_eye_mode == "lumbar_mri":
            logger.debug(f"[MG][LAYOUT] _get_default_layout_from_config: mode=lumbar_mri, returning {LUMBAR_LAYOUT}")
            return LUMBAR_LAYOUT
        logger.debug(f"[MG][LAYOUT] _get_default_layout_from_config: modality={modality}, returning (1, 2)")
        return (1, 2)

    def creator_vtk_widget(self):
        """Override to create AI-specific VTK widget"""
        if self.eagle_eye_mode == "bone_age":
            return super().creator_vtk_widget()
        height = self.sidebar.height() if hasattr(self, 'sidebar') and self.sidebar else 480
        return AIVTKWidget(height_viewer=height, patient_widget=self, type_viewer=self.type_viewer)

    def create_dummy_vtk_widget(self):
        """AI-specific lightweight placeholder using AIVTKWidget."""
        if self.eagle_eye_mode == "bone_age":
            return super().create_dummy_vtk_widget()
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
                    features=features_text,  # Add classification to features box
                    mammography_fields={
                        "finding_uid": getattr(box_object, "finding_uid", None),
                        "source_row_key": getattr(box_object, "source_row_key", None),
                        "source_row_index": getattr(box_object, "source_row_index", None),
                        "source_box_index": getattr(box_object, "source_box_index", None),
                        "source_kind": getattr(box_object, "source_kind", None),
                    },
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
        if self.eagle_eye_mode == "lumbar_mri":
            lst_names_viewer = list(LUMBAR_VIEWER_NAMES)
        else:
            lst_names_viewer = [TYPES_VIEWER.your_viewer, TYPES_VIEWER.fixed_viewer]

        # Never index past the name list: an unexpected count used to raise
        # IndexError here and leave the layout half-built.
        while len(lst_names_viewer) < count:
            lst_names_viewer.append(f"Viewer {len(lst_names_viewer) + 1}")

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

    def manage_reference_line(self, repaint=True):
        """Reference lines: off for MG/bone-age, ON (all-pairs) for lumbar MRI.

        Mammography and bone age are single-plane studies where a cross-reference
        line means nothing and only clutters the AI overlays - that is why this
        override existed. Lumbar MRI is the opposite case: the whole point of the
        3-panel capture is that each frame carries its own spatial context, so the
        sagittal plane must be drawn on the axial pane and the axial plane on both
        sagittal panes.

        All-pairs is used deliberately rather than the legacy single-source path,
        because during a sweep there is no "clicked" viewport driving the lines -
        the controller moves the panes programmatically. Calling the base
        implementation directly (instead of flipping AIPACS_REFERENCE_LINES_ALL_PAIRS)
        keeps this scoped to the Eagle Eye widget: the main viewer's reference-line
        behaviour is untouched.

        The signature now matches the base method. The old zero-argument version
        silently swallowed the ``repaint`` keyword the throttle passes, which meant
        any future caller would have raised TypeError instead of no-opping.
        """
        if self.eagle_eye_mode != "lumbar_mri":
            return  # turn off reference lines for AI (MG / bone age)
        try:
            self._manage_reference_line_all_pairs(repaint=repaint)
        except Exception as exc:
            logger.debug(f"[LUMBAR][REFLINE] reference line pass failed: {exc}")

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
            if self.eagle_eye_mode in ("bone_age", "lumbar_mri"):
                # Lumbar MRI assigns a DIFFERENT series to each of its three
                # panes on purpose; mirroring would immediately overwrite two of
                # them with the third.
                return result
            modality = ''
            if hasattr(self, 'lst_nodes_viewer') and len(self.lst_nodes_viewer) >= 2:
                if 0 <= series_index < len(self.lst_thumbnails_data):
                    modality = str(
                        self.lst_thumbnails_data[series_index]
                        .get('metadata', {})
                        .get('series', {})
                        .get('modality', '')
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
        """Auto-pair CC/MLO: when user loads R-CC, find and load R-MLO on other viewer.

        If user drops R-CC on one viewer, this finds the R-MLO series in the
        available thumbnails and loads it on the other viewer (and vice versa).
        If no complementary view is found, mirrors the same series (legacy).
        """
        def _do_mirror():
            try:
                node_list = list(getattr(self, 'lst_nodes_viewer', []) or [])[:2]
            except Exception:
                return

            # Determine the laterality/view of the dropped series — from DICOM-backed
            # identity, never from series order (bug #2).
            dropped_lat = ''
            dropped_vp = ''
            if 0 <= series_index < len(self.lst_thumbnails_data):
                dropped_lat, dropped_vp = resolve_thumb_lat_view(
                    self.lst_thumbnails_data[series_index]
                )

            # Find the complementary view index
            complement_index = None
            if dropped_lat and dropped_vp in ('CC', 'MLO'):
                target_vp = 'MLO' if dropped_vp == 'CC' else 'CC'
                for idx, thumb in enumerate(self.lst_thumbnails_data):
                    if idx == series_index:
                        continue
                    t_lat, t_vp = resolve_thumb_lat_view(thumb)
                    if t_lat == dropped_lat and t_vp == target_vp:
                        complement_index = idx
                        break

            mirror_index = complement_index if complement_index is not None else series_index

            for node in node_list:
                try:
                    node_widget = getattr(node, 'vtk_widget', None)
                except Exception:
                    node_widget = None
                if node_widget is None or node_widget is primary_vtk_widget:
                    continue
                try:
                    _ = node_widget.objectName()
                except Exception:
                    continue
                try:
                    super(AIPatientWidget, self).change_series_on_viewer(
                        mirror_index,
                        flag_change_selected_widget=False,
                        vtk_widget=node_widget,
                        slider=getattr(node, 'slider', None),
                        allow_paired=allow_paired,
                    )
                    if complement_index is not None:
                        logger.info(
                            "[MG][AUTO-PAIR] %s-%s dropped → loaded %s-%s on other viewer",
                            dropped_lat, dropped_vp, dropped_lat, target_vp,
                        )
                except Exception as mirror_err:
                    logger.warning(
                        "[MG] mirror series=%s onto secondary viewer failed: %s",
                        mirror_index, mirror_err,
                    )

        try:
            QTimer.singleShot(0, _do_mirror)
        except Exception as sched_err:
            logger.warning("[MG] mirror scheduling failed (%s); running inline", sched_err)
            try:
                _do_mirror()
            except Exception:
                pass
