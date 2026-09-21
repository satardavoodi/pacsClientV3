"""Open the study workspace first; execute functions only through its explicit action."""
from __future__ import annotations

import logging
from types import SimpleNamespace
import weakref

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QDialog, QVBoxLayout, QMessageBox, QTabWidget, QScrollArea, QInputDialog
from shiboken6 import isValid

from .background_analysis import BackgroundAnalysisDialog
from .eagle_eye_function_dialog import active_viewer_context
from . import eagle_eye_function_dialog
from .eagle_eye_function_catalog import FUNCTION_NATIVE_ANALYSIS, FUNCTION_LEGION_CONSULT, FUNCTION_BRAIN_LESIONS, FUNCTION_ALIGNMENT
from .eagle_eye_function_catalog import FUNCTION_TOTAL_SPINE

logger = logging.getLogger(__name__)


def open_eagle_eye_workspace(patient_widget):
    """Navigation only: never prompt, probe DICOM, or submit an analysis here."""
    internal_action = getattr(patient_widget, "_eagle_eye_function_action", None)
    if callable(internal_action):
        internal_action()
        return
    context = active_viewer_context(patient_widget)
    study_uid = context["study_uid"]
    opener = getattr(patient_widget, "method_add_new_tab", None)
    if not study_uid or not callable(opener):
        QMessageBox.information(patient_widget, "Eagle Eye", "Open a study before entering Eagle Eye.")
        return
    mode = context["eagle_eye_mode"]
    # Unclassified MRI retains the existing lumbar selection route. This only
    # chooses a workspace layout; the DICOM resolver still gates every run.
    if mode is None and context["modality"] == "MR":
        mode = "lumbar_mri"
    workspace = opener(open_ai_client_tab=True, study_uid=study_uid, eagle_eye_mode=mode)
    controller = getattr(workspace, "workspace_controller", None)
    if controller is not None:
        controller.bind_source(patient_widget, context)
    return workspace


class EagleEyeWorkspaceController(QObject):
    """Own the function picker, native run adapter, and persistent Brain popup."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self._modality_future = None
        self._modality_executor = None
        self._modality_timer = QTimer(self)
        self._modality_timer.setInterval(100)
        self._modality_timer.timeout.connect(self._modality_ready)
        self._disposed = False
        self._native_style = None
        self._choosing = False
        self._brain_dialog = None
        self._brain_widget = None
        self._lesion_dialog = None
        self._lesion_widget = None
        self._alignment_dialog = None
        self._alignment_widget = None
        self._total_spine_dialog = None
        self._total_spine_widget = None
        self._analysis_sessions = {}
        self._session_keys = {}
        self._source_ref = None
        self._source_identity = None
        self._source_modality = {
            "mammography": "MG", "bone_age": "DX", "lumbar_mri": "MR", "brain_mri": "MR",
        }.get(window.eagle_eye_mode, "")
        # The workstation removes tabs with deleteLater(), without closeEvent.
        # Parent destruction is still early enough to detach child QThreads.
        window.destroyed.connect(self.teardown)

    def teardown(self):
        self._disposed = True
        self._modality_timer.stop()
        if self._modality_executor:
            self._modality_executor.shutdown(wait=False, cancel_futures=True)
        tab = self.window.imaging_tab
        for name in ("_eagle_eye_workflow", "_mammography_analysis", "_dx_wrist_analysis"):
            controller = getattr(tab, name, None)
            if controller is not None:
                controller.teardown()
        if self._brain_widget is not None:
            self._brain_widget._cancel.set()
        if self._lesion_widget is not None:
            self._lesion_widget._cancel.set()
        if self._alignment_widget is not None:
            self._alignment_widget.teardown()
        if self._total_spine_widget is not None:
            self._total_spine_widget.teardown()
        current = [getattr(self, '_' + name + '_widget')
                   for name in ('brain', 'lesion', 'alignment', 'total_spine')]
        for _, widget in self._analysis_sessions.values():
            if widget not in current:
                if hasattr(widget, 'teardown'):
                    widget.teardown()
                else:
                    widget._cancel.set()

    def bind_source(self, patient_widget, context):
        # Legion remains a source-owned Fast Viewer workflow. No VTK widget,
        # interactor or mutable viewer data is handed between render domains.
        self._source_ref = weakref.ref(patient_widget)
        self._source_identity = (context["study_uid"], context["series_uid"], context["series_number"])
        self._source_modality = context["modality"]

    def choose_function(self):
        if self._choosing:
            return
        self._choosing = True
        try:
            mode = self.window.eagle_eye_mode
            modality = self._source_modality
            # Entry can precede the first loaded series. Resolve the current
            # workspace selection at click time, without reading DICOM on Qt.
            patient = getattr(self.window.imaging_tab, "patient_widget", None)
            context = active_viewer_context(patient) if patient is not None else {}
            logger.info(
                "Eagle Eye selection: patient_type=%s selected_type=%s viewer_type=%s "
                "series_identity=%s study_matches=%s modality=%r mode=%r",
                type(patient).__name__, type(context.get("selected_widget")).__name__,
                type(context.get("image_viewer")).__name__, bool(context.get("series_uid")),
                context.get("study_uid") == str(self.window._study_uid),
                context.get("modality"), context.get("eagle_eye_mode"),
            )
            # Advanced viewer metadata may omit SeriesInstanceUID while still
            # identifying the loaded study and modality. This selects a form;
            # each analysis retains its own series selection/identity checks.
            if context.get("image_viewer") is not None and context.get("modality"):
                if context.get("study_uid") != str(self.window._study_uid):
                    self._message("Select a series from this Eagle Eye study before choosing an analysis.")
                    return
                modality = context.get("modality", "")
                mode = context.get("eagle_eye_mode")
                self.window.eagle_eye_mode = mode
                self.window.imaging_tab.eagle_eye_mode = mode
            if not modality:
                self._resolve_study_modality()
                return
            choice = eagle_eye_function_dialog.choose_eagle_eye_function(modality, parent=self.window, mode=mode)
            if choice == FUNCTION_LEGION_CONSULT:
                self._start_legion()
            elif choice == FUNCTION_ALIGNMENT and modality in ('DX', 'CR'):
                self.open_alignment()
            elif choice == FUNCTION_TOTAL_SPINE and modality in ('DX', 'CR'):
                self.open_total_spine()
            elif choice == FUNCTION_BRAIN_LESIONS and mode == 'brain_mri':
                self.open_lesions()
            elif choice == FUNCTION_NATIVE_ANALYSIS:
                if mode == "brain_mri":
                    self.open_brain()
                else:
                    self._start_native(modality)
        except Exception:
            logger.exception("Eagle Eye function could not start")
            self._message("The selected function could not start. Please reopen the study and try again.")
        finally:
            self._choosing = False

    def selected_series_uid(self):
        """Prefer the loaded workspace viewport; retain the immutable entry selection."""
        patient = getattr(self.window.imaging_tab, 'patient_widget', None)
        context = active_viewer_context(patient) if patient is not None else {}
        if context.get('image_viewer') is not None:
            if context.get('study_uid') != str(self.window._study_uid):
                return ''
            return context.get('series_uid', '')
        identity = self._source_identity
        return identity[1] if identity and identity[0] == str(self.window._study_uid) else ''

    def _select_analysis_session(self, name):
        """Keep reader edits with their input series when Function is used again."""
        uid = self.selected_series_uid()
        previous = self._session_keys.get(name)
        widget = getattr(self, '_' + name + '_widget')
        if widget is not None and previous == uid:
            return
        if widget is not None:
            dialog = getattr(self, '_' + name + '_dialog')
            self._analysis_sessions[(name, previous)] = (dialog, widget)
            # Dismiss pending input selectors; immutable-input computation continues.
            dialog.close()
        dialog, widget = self._analysis_sessions.get((name, uid), (None, None))
        setattr(self, '_' + name + '_dialog', dialog)
        setattr(self, '_' + name + '_widget', widget)
        self._session_keys[name] = uid

    def _resolve_study_modality(self):
        if self._modality_future is not None or self._disposed:
            return
        from concurrent.futures import ThreadPoolExecutor
        from PacsClient.utils.db_manager import get_series_by_study_uid
        if self._modality_executor is None:
            self._modality_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='eagle-eye-catalog')
        self._modality_future = self._modality_executor.submit(get_series_by_study_uid, str(self.window._study_uid))
        button = getattr(self.window, 'function_button', None)
        if button:
            button.setEnabled(False); button.setText('Reading study functions...')
        self._modality_timer.start()

    def _modality_ready(self):
        future = self._modality_future
        if future is None or not future.done() or self._disposed:
            return
        self._modality_future = None; self._modality_timer.stop()
        button = getattr(self.window, 'function_button', None)
        if button:
            button.setEnabled(True); button.setText('Choose Function')
        try:
            modalities = sorted({str(row.get('modality') or '').strip().upper() for row in future.result()} - {''})
        except Exception:
            self._message('Study image types could not be read. Please retry Choose Function.')
            return
        if not modalities:
            self._message('No study image types are available yet. Wait for the study catalog and retry.')
            return
        if len(modalities) == 1:
            selected = modalities[0]
        else:
            selected, accepted = QInputDialog.getItem(self.window, 'Choose Function', 'Study image type', modalities, 0, False)
            if not accepted:
                return
        self._source_modality = selected
        self.choose_function()

    def _start_native(self, modality):
        from modules.viewer.interactor_styles.ai_chat_interactorstyle import AIChatInteractorStyle

        tab = self.window.imaging_tab
        patient = tab.patient_widget
        workflow = tab._eagle_eye_workflow
        if modality == "MR" and workflow.busy:
            self._message("A lumbar analysis is already running in this workspace.")
            return
        style = self._native_style
        if style is not None and style._ai_worker_busy():
            self._message("An analysis is already running in this workspace.")
            return
        context = active_viewer_context(patient)
        if context["study_uid"] and context["study_uid"] != str(self.window._study_uid):
            self._message("Select an image from this workspace's study before running analysis.")
            return
        viewer = context["image_viewer"]
        if viewer is None or context["vtk_widget"] is None:
            self._message("Load a series in the Eagle Eye viewer before running analysis.")
            return
        fixed = getattr(viewer, "metadata_fixed", None)
        if not isinstance(fixed, dict):
            fixed = getattr(patient, "metadata_fixed", {})
        fixed = dict(fixed) if isinstance(fixed, dict) else {}
        fixed.update(study_uid=str(self.window._study_uid), modality=modality)
        proxy = SimpleNamespace(metadata_fixed=fixed, metadata=getattr(viewer, "metadata", {}),
                                vtk_widget=context["vtk_widget"])
        if style is None:
            style = AIChatInteractorStyle(proxy)
            self._native_style = style
            owner_ref = weakref.ref(self)
            def completed():
                owner = owner_ref()
                if owner is not None and isValid(owner) and isValid(owner.window):
                    owner._native_ready()
            style._workspace_open_callback = completed
        style.image_viewer = proxy
        style.check_status(patient)

    def _native_ready(self):
        tab = self.window.imaging_tab
        if self.window.eagle_eye_mode == "lumbar_mri":
            from .eagle_eye_lumbar import session_request
            target = getattr(tab.patient_widget, "_preferred_eagle_eye_study_uid", None)
            if target != str(self.window._study_uid):
                session_request.take(str(target or ""))
                self._message("Open the selected study in its own Eagle Eye workspace before analysis.")
                return
            tab._eagle_eye_workflow.start_capture()
        elif self.window.eagle_eye_mode == "bone_age":
            tab._load_bone_age_feature_if_exists(activate=True)
        else:
            self.window.refresh_ai_results()

    def open_brain(self):
        """Keep the viewer on screen while the Brain tools live in an owned popup."""
        self._select_analysis_session('brain')
        if self._brain_dialog is None:
            from .eagle_eye_brain.widget import BrainVolumetryWidget
            dialog = BackgroundAnalysisDialog(self.window)
            dialog.setWindowTitle("Eagle Eye Brain")
            dialog.resize(900, 760)
            layout = QVBoxLayout(dialog)
            widget = BrainVolumetryWidget(dialog, study_uid=self.window._study_uid)
            widget.preferred_series_uid = self.selected_series_uid()
            widget.start_after_inputs = True
            scroll = QScrollArea(dialog)
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            layout.addWidget(scroll)
            self._brain_dialog, self._brain_widget = dialog, widget
            # Keep computation alive when the popup is dismissed; pending input
            # selection is cancelled by the dialog to avoid stealing focus.
            dialog.bind_analysis(widget)
        self._brain_dialog.show()
        self._brain_dialog.raise_()
        self._brain_dialog.activateWindow()
        if self._brain_widget._future is None and self._brain_widget._result is None:
            self._brain_widget.start_study_segmentation()

    def open_alignment(self):
        """A study-owned review popup with independent pixels and computation."""
        self._select_analysis_session('alignment')
        if self._alignment_dialog is None:
            from .eagle_eye_alignment.widget import AlignmentWidget
            dialog = BackgroundAnalysisDialog(self.window)
            dialog.setWindowTitle('Eagle Eye Alignment View')
            dialog.resize(1250, 880)
            layout = QVBoxLayout(dialog)
            widget = AlignmentWidget(dialog, study_uid=self.window._study_uid)
            widget.preferred_series_uid = self.selected_series_uid()
            layout.addWidget(widget)
            self._alignment_dialog, self._alignment_widget = dialog, widget
            dialog.bind_analysis(widget)
        self._alignment_dialog.show()
        self._alignment_dialog.raise_()
        self._alignment_dialog.activateWindow()
        if self._alignment_widget.image is None and self._alignment_widget._future is None:
            self._alignment_widget.scan_study()

    def open_total_spine(self):
        """Prepare proposals before adding the study-owned review tab."""
        if not str(self.window._study_uid or '').strip():
            self._message('Open a study before using Total Spine Alignment.')
            return
        tabs = getattr(self.window, 'tab_widget', None)
        self._select_analysis_session('total_spine')
        if self._total_spine_widget is None:
            from .eagle_eye_total_spine.widget import TotalSpineWidget
            dialog = BackgroundAnalysisDialog(self.window)
            dialog.setWindowTitle('Total Spine Alignment | Prepare analysis')
            dialog.resize(1000, 800)
            widget = TotalSpineWidget(dialog, study_uid=self.window._study_uid)
            QVBoxLayout(dialog).addWidget(widget)
            dialog.bind_analysis(widget)
            self._total_spine_dialog, self._total_spine_widget = dialog, widget
            widget.resultsReady.connect(lambda: self._show_spine_results(widget, dialog))
            selected_uid = self.selected_series_uid()
            if selected_uid:
                widget.begin_automatic(series_uid=selected_uid)
            else:
                widget.begin_automatic()
        widget = self._total_spine_widget
        if isinstance(tabs, QTabWidget) and tabs.indexOf(widget) >= 0:
            tabs.setCurrentWidget(widget)
        else:
            self._total_spine_dialog.show()
            self._total_spine_dialog.raise_()
            self._total_spine_dialog.activateWindow()

    def _show_spine_results(self, widget=None, dialog=None):
        if self._disposed:
            return
        widget = widget if widget is not None else self._total_spine_widget
        dialog = dialog if dialog is not None else self._total_spine_dialog
        tabs = getattr(self.window, 'tab_widget', None)
        if isinstance(tabs, QTabWidget):
            if tabs.indexOf(widget) < 0:
                dialog.layout().removeWidget(widget)
                tabs.addTab(widget, 'Total Spine Alignment')
            dialog.hide()
            if widget is self._total_spine_widget:
                tabs.setCurrentWidget(widget)
        else:
            dialog.setWindowTitle('Total Spine Alignment | Review results')

    def open_lesions(self):
        self._select_analysis_session('lesion')
        if self._lesion_dialog is None:
            from .eagle_eye_brain.lesion_widget import BrainLesionWidget
            dialog = BackgroundAnalysisDialog(self.window)
            dialog.setWindowTitle('Eagle Eye | White-matter lesions')
            dialog.resize(900, 680)
            layout = QVBoxLayout(dialog)
            widget = BrainLesionWidget(dialog, study_uid=self.window._study_uid)
            widget.preferred_series_uid = self.selected_series_uid()
            widget.start_after_inputs = True
            scroll = QScrollArea(dialog)
            scroll.setWidgetResizable(True)
            scroll.setWidget(widget)
            layout.addWidget(scroll)
            self._lesion_dialog, self._lesion_widget = dialog, widget
            dialog.bind_analysis(widget)
        self._lesion_dialog.show()
        self._lesion_dialog.raise_()
        self._lesion_dialog.activateWindow()
        if self._lesion_widget._future is None and self._lesion_widget._result is None:
            self._lesion_widget.start_study_segmentation()

    def _start_legion(self):
        source = self._source_ref() if self._source_ref else None
        if source is None or not isValid(source):
            self._message("Open Eagle Eye from the MRI Fast Viewer to use Legion Consult.")
            return
        context = active_viewer_context(source)
        if (context["study_uid"], context["series_uid"], context["series_number"]) != self._source_identity:
            self._message("The source MRI selection changed. Reopen Eagle Eye from the intended series.")
            return
        from .legion_consult.workflow import LegionConsultCoordinator
        coordinator = getattr(source, "_legion_consult_coordinator", None)
        if coordinator is None:
            coordinator = LegionConsultCoordinator(source)
            source._legion_consult_coordinator = coordinator
        # ROI placement belongs to the original Fast Viewer, as before.
        parent = source.parentWidget()
        while parent is not None:
            if isinstance(parent, QTabWidget) and parent.indexOf(source) >= 0:
                parent.setCurrentWidget(source)
                break
            parent = parent.parentWidget()
        coordinator.start()

    def _message(self, text):
        QMessageBox.information(self.window, "Eagle Eye", text)
