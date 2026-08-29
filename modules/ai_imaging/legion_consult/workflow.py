"""Qt coordinator for the complete Legion Consult workflow."""

from __future__ import annotations

import logging
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QMessageBox, QProgressDialog

from modules.ai_imaging.eagle_eye_function_dialog import active_viewer_context
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate

from .dialogs import SeriesSelectionDialog
from .models import AttentionAnchor, LegionConsultRequest, SeriesSelectionPlan
from .result_panel import LegionConsultResultPanel
from .runner import LegionAnalysisRunner
from .session_store import save_configured_request


logger = logging.getLogger(__name__)
_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="legion-consult")


def _probe_series_snapshot(
    study_uid: str,
    primary_study_uid: str,
    import_folder_path: str,
) -> list[SeriesCandidate]:
    """Probe one snapshotted study path without touching a Qt object."""
    from modules.ai_imaging.eagle_eye_lumbar.series_probe import probe_study_series

    study_path = None
    if study_uid:
        try:
            from PacsClient.utils.config import SOURCE_PATH

            candidate = Path(SOURCE_PATH) / study_uid
            if candidate.is_dir():
                study_path = candidate
        except (ImportError, OSError, TypeError):
            study_path = None
    if study_path is None and import_folder_path and (
        not primary_study_uid or primary_study_uid == study_uid
    ):
        candidate = Path(import_folder_path)
        if candidate.is_dir():
            study_path = candidate
    return probe_study_series(study_path)


def _find_source_candidate(
    candidates: list[SeriesCandidate],
    *,
    series_uid: str,
    series_number: str,
) -> SeriesCandidate | None:
    if series_uid:
        for candidate in candidates:
            if candidate.series_uid == series_uid:
                return candidate
    if series_number:
        matches = [
            candidate
            for candidate in candidates
            if str(candidate.series_number).strip() == str(series_number).strip()
        ]
        if len(matches) == 1:
            return matches[0]
    return None


class LegionConsultCoordinator(QObject):
    """Configure series and ROI, then coordinate evidence and analysis."""

    def __init__(self, patient_widget: Any):
        super().__init__(patient_widget)
        self._patient_widget = patient_widget
        self._future: Future | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(60)
        self._poll_timer.timeout.connect(self._poll_future)
        self._roi_timer = QTimer(self)
        self._roi_timer.setInterval(250)
        self._roi_timer.timeout.connect(self._poll_roi_arm)
        self._progress: QProgressDialog | None = None
        self._completion: Callable[[Any], None] | None = None
        self._context: dict[str, Any] = {}
        self._plan: SeriesSelectionPlan | None = None
        self._candidates: tuple[SeriesCandidate, ...] = ()
        self._existing_roi_ids: set[int] = set()
        self._roi_callback: Callable[[], None] | None = None
        self._analysis_runner: LegionAnalysisRunner | None = None
        self._result_panel: LegionConsultResultPanel | None = None
        self._current_request: LegionConsultRequest | None = None
        self._current_request_path: Path | None = None
        self._current_candidates: tuple[SeriesCandidate, ...] = ()

    @property
    def busy(self) -> bool:
        return (
            self._future is not None
            or self._plan is not None
            or bool(self._analysis_runner and self._analysis_runner.running)
        )

    def start(self) -> bool:
        """Begin non-blocking study probing for the selected Fast MRI viewer."""
        if self.busy:
            QMessageBox.information(
                self._patient_widget,
                "Legion Consult",
                "A Legion Consult setup is already in progress.",
            )
            return False

        context = active_viewer_context(self._patient_widget)
        if context["modality"] != "MR":
            self._warning("Legion Consult is currently available for MRI studies only.")
            return False
        vtk_widget = context.get("vtk_widget")
        image_viewer = context.get("image_viewer")
        qt_viewer = getattr(image_viewer, "qt_viewer", None)
        if not bool(getattr(vtk_widget, "_qt_bridge_active", False)) or qt_viewer is None:
            self._warning(
                "Legion Consult ROI setup is currently available in Fast Viewer only. "
                "Open the MRI series in Fast Viewer and try again."
            )
            return False
        if not context["study_uid"] or not (context["series_uid"] or context["series_number"]):
            self._warning("The active MRI series identity could not be resolved.")
            return False

        self._context = context
        primary_uid = str(getattr(self._patient_widget, "study_uid", "") or "")
        import_path = str(getattr(self._patient_widget, "import_folder_path", "") or "")
        self._show_progress("Reading MRI series headers...")
        self._completion = self._on_probe_finished
        self._future = _WORKERS.submit(
            _probe_series_snapshot,
            context["study_uid"],
            primary_uid,
            import_path,
        )
        self._poll_timer.start()
        return True

    def _show_progress(self, text: str) -> None:
        if self._progress is not None:
            self._progress.close()
        progress = QProgressDialog(text, "Cancel", 0, 0, self._patient_widget)
        progress.setWindowTitle("Legion Consult")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.canceled.connect(self.cancel)
        progress.show()
        self._progress = progress

    def cancel(self) -> None:
        """Ignore any outstanding result and return to idle state."""
        future = self._future
        self._future = None
        self._completion = None
        self._poll_timer.stop()
        if future is not None:
            future.cancel()
        self._close_progress()
        self._reset()

    def _poll_future(self) -> None:
        future = self._future
        if future is None or not future.done():
            return
        self._poll_timer.stop()
        self._future = None
        completion = self._completion
        self._completion = None
        try:
            result = future.result()
        except Exception as exc:
            logger.error("Legion Consult background operation failed: %s", type(exc).__name__)
            self._close_progress()
            self._reset()
            self._warning("Legion Consult could not complete the local setup operation.")
            return
        self._close_progress()
        if completion is not None:
            completion(result)

    def _on_probe_finished(self, candidates: list[SeriesCandidate]) -> None:
        self._candidates = tuple(candidates)
        source = _find_source_candidate(
            candidates,
            series_uid=self._context["series_uid"],
            series_number=self._context["series_number"],
        )
        if source is None:
            self._reset()
            self._warning(
                "The active source series could not be matched to the local MRI study. "
                "Reload the series and try again."
            )
            return
        dialog = SeriesSelectionDialog(
            study_uid=self._context["study_uid"],
            candidates=candidates,
            source=source,
            parent=self._patient_widget,
        )
        plan = dialog.selection_plan()
        if plan is None:
            self._reset()
            return
        self._plan = plan
        self._arm_roi()

    def _arm_roi(self) -> None:
        if not self._active_source_is_unchanged():
            self._reset()
            self._warning("The active series changed during setup. Please start Legion Consult again.")
            return
        image_viewer = self._context["image_viewer"]
        qt_viewer = getattr(image_viewer, "qt_viewer", None)
        controller = getattr(qt_viewer, "tool_controller", None)
        store = getattr(controller, "_store", None)
        if qt_viewer is None or controller is None or store is None:
            self._reset()
            self._warning("The Fast Viewer ROI tool is not available for this series.")
            return

        self._existing_roi_ids = self._roi_ids(store)
        toolbar = getattr(self._patient_widget, "toolbar_manager", None)
        selected = self._context["selected_widget"]
        if toolbar is None:
            self._reset()
            self._warning("The ROI toolbar is not available.")
            return

        QMessageBox.information(
            self._patient_widget,
            "Legion Consult — Mark the Finding",
            "Draw one rectangular ROI around the suspicious finding on the active source series. "
            "The ROI is a location hint; it is not a manual volume segmentation.",
        )
        if toolbar.tool_selected == toolbar.tool_access.ROI:
            toolbar.check_and_deactivate_tools()
        toolbar.toggle_roi(selected)
        normal_completion = getattr(qt_viewer, "_tool_completed_cb", None)
        if normal_completion is None:
            self._reset()
            self._warning("The rectangular ROI tool could not be activated.")
            return

        def complete_roi() -> None:
            try:
                self._roi_timer.stop()
                self._roi_callback = None
                normal_completion()
                self._on_roi_completed(qt_viewer, store)
            except Exception as exc:
                logger.error(
                    "[LEGION-CONSULT] event=roi_callback_failed error=%s",
                    exc.__class__.__name__,
                )
                self._close_progress()
                self._reset()
                self._warning(
                    "Legion Consult could not process the completed ROI. "
                    "Please draw the rectangle again."
                )

        self._roi_callback = complete_roi
        qt_viewer._tool_completed_cb = complete_roi
        self._roi_timer.start()

    def _poll_roi_arm(self) -> None:
        """Return to idle if another toolbar action disarms the owned ROI."""
        callback = self._roi_callback
        image_viewer = self._context.get("image_viewer")
        qt_viewer = getattr(image_viewer, "qt_viewer", None)
        if callback is None or qt_viewer is None:
            self._roi_timer.stop()
            return
        if getattr(qt_viewer, "_tool_completed_cb", None) is callback:
            return
        self._reset()
        self._warning("Legion Consult ROI setup was canceled before the rectangle was completed.")

    @staticmethod
    def _roi_ids(store: Any) -> set[int]:
        from modules.viewer.tools.models import ROIRectModel

        annotations = getattr(store, "_annotations", {})
        return {
            id(model)
            for models in annotations.values()
            for model in models
            if isinstance(model, ROIRectModel)
        }

    def _on_roi_completed(self, qt_viewer: Any, store: Any) -> None:
        from modules.viewer.tools.coord_resolver import CoordinateResolver
        from modules.viewer.tools.models import ROIRectModel

        if self._plan is None or not self._active_source_is_unchanged():
            self._reset()
            self._warning("The active series changed before the ROI was completed.")
            return
        annotations = getattr(store, "_annotations", {})
        new_rois = [
            model
            for models in annotations.values()
            for model in models
            if isinstance(model, ROIRectModel)
            and id(model) not in self._existing_roi_ids
            and model.is_complete
        ]
        if not new_rois:
            self._reset()
            self._warning("A completed rectangular ROI was not found.")
            return
        roi = max(new_rois, key=lambda model: model.created_at)
        logger.info("[LEGION-CONSULT] event=roi_completed")
        try:
            resolver = CoordinateResolver(qt_viewer, getattr(qt_viewer, "_coord_backend", None))
            anchor = AttentionAnchor.from_rectangle(
                source_series_key=self._plan.source_series_key,
                source_slice_index=roi.slice_index,
                diagonal_points=roi.points_image,
                image_to_patient=resolver.image_to_patient,
            )
            request = LegionConsultRequest.create(plan=self._plan, anchor=anchor)
        except (RuntimeError, TypeError, ValueError):
            self._reset()
            self._warning("The ROI could not be mapped to DICOM patient coordinates.")
            return

        self._show_progress("Saving the local Legion Consult setup...")
        self._completion = lambda path: self._on_request_saved(request, path)
        self._future = _WORKERS.submit(save_configured_request, request)
        self._poll_timer.start()

    def _on_request_saved(self, request: LegionConsultRequest, path: Path) -> None:
        self._patient_widget._legion_consult_request = request
        self._patient_widget._legion_consult_request_path = path
        candidates = self._candidates
        logger.info(
            "[LEGION-CONSULT] event=request_saved session=%s series=%d",
            request.session_id,
            len(request.selection.selected_series_keys),
        )
        self._reset()
        self._start_analysis(request, path.parent, candidates)

    def _ensure_result_panel(self) -> LegionConsultResultPanel:
        panel = self._result_panel
        if panel is None:
            panel = LegionConsultResultPanel(self._patient_widget)
            panel.reanalyzeRequested.connect(self._reanalyze)
            self._result_panel = panel
        return panel

    def _start_analysis(
        self,
        request: LegionConsultRequest,
        session_dir: Path,
        candidates: tuple[SeriesCandidate, ...] = (),
    ) -> None:
        if self._analysis_runner is not None and self._analysis_runner.running:
            self._warning("A Legion Consult analysis is already in progress.")
            return
        self._current_request = request
        self._current_request_path = session_dir / "request.json"
        if candidates:
            self._current_candidates = tuple(candidates)
        panel = self._ensure_result_panel()
        panel.set_busy(
            "Preparing complete-stack overview images and ROI-focused evidence. "
            "The workstation remains available while analysis runs."
        )
        runner = LegionAnalysisRunner(
            session_dir=session_dir,
            request=request,
            candidates=candidates,
            parent=None,
        )
        runner.stage.connect(panel.set_stage)
        runner.finished.connect(self._on_analysis_finished)
        runner.failed.connect(self._on_analysis_failed)
        self._analysis_runner = runner
        if not runner.start():
            self._analysis_runner = None

    def _on_analysis_finished(self, record: Any) -> None:
        self._analysis_runner = None
        self._ensure_result_panel().show_record(record)

    def _on_analysis_failed(self, message: str) -> None:
        runner = self._analysis_runner
        self._analysis_runner = None
        session_dir = (
            runner.session_dir
            if runner is not None
            else Path(self._current_request_path or Path.cwd()).parent
        )
        self._ensure_result_panel().show_failure(session_dir, message)

    def _reanalyze(self) -> None:
        request = self._current_request
        path = self._current_request_path
        if request is None or path is None:
            self._warning("The saved Legion Consult request is unavailable for retry.")
            return
        self._start_analysis(request, path.parent, self._current_candidates)

    def _active_source_is_unchanged(self) -> bool:
        current = active_viewer_context(self._patient_widget)
        if current["study_uid"] != self._context.get("study_uid"):
            return False
        expected_uid = self._context.get("series_uid")
        if expected_uid:
            return current["series_uid"] == expected_uid
        return current["series_number"] == self._context.get("series_number")

    def _close_progress(self) -> None:
        progress = self._progress
        self._progress = None
        if progress is not None:
            try:
                progress.canceled.disconnect(self.cancel)
            except (RuntimeError, TypeError):
                pass
            progress.close()
            progress.deleteLater()

    def _reset(self) -> None:
        self._roi_timer.stop()
        callback = self._roi_callback
        image_viewer = self._context.get("image_viewer")
        qt_viewer = getattr(image_viewer, "qt_viewer", None)
        owns_roi = (
            callback is not None
            and qt_viewer is not None
            and getattr(qt_viewer, "_tool_completed_cb", None) is callback
        )
        if owns_roi:
            qt_viewer._tool_completed_cb = None
            toolbar = getattr(self._patient_widget, "toolbar_manager", None)
            if (
                toolbar is not None
                and toolbar.tool_selected == toolbar.tool_access.ROI
            ):
                toolbar.check_and_deactivate_tools()
        self._roi_callback = None
        self._plan = None
        self._candidates = ()
        self._existing_roi_ids.clear()
        self._context = {}

    def _warning(self, message: str) -> None:
        QMessageBox.warning(self._patient_widget, "Legion Consult", message)
