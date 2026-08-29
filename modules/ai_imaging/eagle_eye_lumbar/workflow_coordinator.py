"""Qt-side coordinator for the Eagle Eye capture and analysis workflow.

The imaging tab owns widgets and displays status. This coordinator owns the
feature lifecycle: series resolution, capture, analysis, result presentation,
and safe teardown. Keeping that boundary here prevents the general-purpose tab
controller from accumulating protocol-specific workflow logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject


class EagleEyeWorkflowCoordinator(QObject):
    """Coordinate one Eagle Eye workflow for an imaging tab host."""

    _STAGE_TEXT = {
        "screening": "Eagle Eye is analyzing the lumbar MRI",
        "parallel_screening_context": (
            "Eagle Eye is screening the MRI and reading clinical context in parallel"
        ),
        "verification": "Eagle Eye is verifying the findings",
    }

    def __init__(self, host: Any):
        super().__init__(host)
        self._host = host
        self._capture_controller = None
        self._selection = None
        self._analysis_runner = None
        self._result_panel = None
        self._session_dir = None

    def start_capture(self) -> None:
        """Resolve the required series and start the configured capture passes."""
        if self._capture_controller is not None:
            print("[LUMBAR] capture already running; ignoring re-entry")
            return

        try:
            from . import session_request
            from .series_classifier import classify_lumbar_series
            from .series_probe import build_candidates_for_widget
        except Exception as exc:
            self._set_status(f"Eagle Eye lumbar module unavailable: {exc}", active=False)
            return

        try:
            candidates = build_candidates_for_widget(self._host.patient_widget)
        except Exception as exc:
            print(f"[LUMBAR] series probe failed: {exc}")
            self._set_status(f"Lumbar series probe failed: {exc}", active=False)
            return

        request = session_request.take(str(self._host.study_uid or ""))
        selection = self._apply_resolved_mapping(request, candidates) if request else None

        if selection is None:
            try:
                selection = classify_lumbar_series(candidates)
                print("[LUMBAR] no stashed resolution; classified in-tab")
            except Exception as exc:
                print(f"[LUMBAR] series detection failed: {exc}")
                self._set_status(f"Lumbar series detection failed: {exc}", active=False)
                return

        self._selection = selection
        for slot, resolved in selection.slots.items():
            print(
                f"[LUMBAR] {slot}: resolved={resolved.chosen is not None} "
                f"score={resolved.score:.1f} "
                f"confidence={resolved.confidence}"
            )

        unresolved = [
            slot for slot in selection.slots if selection.candidate_for(slot) is None
        ]
        if unresolved:
            self._set_status(
                "Eagle Eye could not identify: " + ", ".join(unresolved),
                active=False,
            )
            return

        self._launch_capture_controller(selection, request)

    def _launch_capture_controller(self, selection: Any, request: Any = None) -> None:
        """Start capture after every protocol role has a real series."""
        try:
            from .capture_controller import LumbarCaptureController, build_study_context
        except Exception as exc:
            self._set_status(f"Eagle Eye capture unavailable: {exc}", active=False)
            return

        for slot_key in selection.slots:
            print(f"[LUMBAR] {slot_key}: series resolved for capture")

        controller = LumbarCaptureController(
            patient_widget=self._host.patient_widget,
            selection=selection,
            capture_widget=self._host.patient_widget_container,
            study_context=build_study_context(
                self._host.patient_widget,
                selection,
                handoff_context=(request or {}).get("study_context"),
            ),
            parent=self,
        )
        self._capture_controller = controller
        controller.progress.connect(self._on_capture_progress)
        controller.finished.connect(self._on_capture_finished)
        controller.failed.connect(self._on_capture_failed)

        if selection.uncertain_slots:
            print(f"[LUMBAR] uncertain slots: {selection.uncertain_slots}")

        if not controller.start():
            self._capture_controller = None

    def _apply_resolved_mapping(self, request: dict, candidates: list) -> Any:
        """Rebuild the exact series mapping validated before the tab opened."""
        try:
            from .protocols import get_protocol
            from .series_classifier import LumbarSelection
        except Exception as exc:
            print(f"[LUMBAR] cannot apply resolved mapping: {exc}")
            return None

        protocol = get_protocol(str(request.get("protocol", {}).get("id") or ""))
        slot_series = request.get("slot_series") or {}
        if protocol is None or not slot_series:
            print("[LUMBAR] stashed resolution is incomplete; falling back to classification")
            return None

        by_uid = {
            candidate.series_uid: candidate
            for candidate in candidates
            if candidate.series_uid
        }
        by_number = {}
        for candidate in candidates:
            by_number.setdefault(str(candidate.series_number), candidate)

        selection = LumbarSelection(protocol)
        for slot_key in protocol.slot_keys:
            wanted = slot_series.get(slot_key) or {}
            candidate = by_uid.get(str(wanted.get("series_uid") or "")) or by_number.get(
                str(wanted.get("series_number") or "")
            )
            if candidate is None:
                print(
                    f"[LUMBAR] resolved series for {slot_key} is not in this study "
                    "layout; re-classifying instead"
                )
                return None
            selection.assign_manually(slot_key, candidate)
            slot = selection[slot_key]
            slot.manual = wanted.get("assigned_by") == "user"
            slot.confidence = wanted.get("confidence") or slot.confidence
            slot.reasons = [
                "resolved before the layout opened "
                f"({wanted.get('assigned_by', 'automatic')}, "
                f"{wanted.get('confidence', 'unknown')} confidence)"
            ]

        print("[LUMBAR] applied the resolution validated before the layout opened")
        return selection

    def _on_capture_progress(self, message: str, done: int, total: int) -> None:
        text = f"{message} ({done}/{total})" if total else message
        self._set_status(text, active=True)

    def _on_capture_finished(self, session: Any) -> None:
        self._capture_controller = None
        try:
            sagittal_count = session.capture_count("sagittal")
            axial_count = session.capture_count("axial")
            self._set_status(
                "Eagle Eye session saved: "
                f"{sagittal_count} sagittal + {axial_count} axial frames",
                active=False,
            )
            print("[LUMBAR] capture session written successfully")
        except Exception:
            self._set_status("Eagle Eye session saved", active=False)

        try:
            self._session_dir = Path(session.path)
        except Exception:
            self._session_dir = None
            return
        self.start_analysis()

    def _on_capture_failed(self, reason: str) -> None:
        self._capture_controller = None
        self._set_status(f"Eagle Eye capture failed: {reason}", active=False)

    def start_analysis(self, force: bool = False) -> None:
        """Analyze the captured session without blocking the GUI thread."""
        if not self._session_dir:
            return
        if self._analysis_runner is not None and self._analysis_runner.running:
            print("[EAGLE-EYE-LLM] a run is already in flight; ignoring re-entry")
            return

        record = self._record()
        if not force and record is not None and record.has_result:
            self._refresh_result_button()
            self.open_result()
            return

        try:
            from .llm_runner import EagleEyeAnalysisRunner
        except Exception as exc:
            self._set_status(f"Eagle Eye analysis unavailable: {exc}", active=False)
            return

        runner = EagleEyeAnalysisRunner(self._session_dir, parent=self)
        runner.stage.connect(self._on_analysis_stage)
        runner.finished.connect(self._on_analysis_finished)
        runner.failed.connect(self._on_analysis_failed)
        self._analysis_runner = runner

        message = "Eagle Eye is analyzing the lumbar MRI..."
        self._set_status(message, active=True)
        panel = self._result_panel
        if panel is not None and panel.isVisible():
            panel.set_busy(True, message)

        if not runner.start():
            self._analysis_runner = None
        self._refresh_result_button()

    def _on_analysis_stage(self, number: int, total: int, name: str) -> None:
        label = self._STAGE_TEXT.get(name, "Eagle Eye is working")
        if name == "parallel_screening_context":
            message = f"{label} - Stages 1-2/{total}..."
        else:
            message = f"{label} - Stage {number}/{total}..." if total > 1 else f"{label}..."
        self._set_status(message, active=True)
        panel = self._result_panel
        if panel is not None and panel.isVisible():
            panel.set_busy(True, message)

    def _on_analysis_finished(self, record: Any) -> None:
        self._analysis_runner = None
        self._set_status("Eagle Eye analysis complete", active=False)
        self._refresh_result_button()
        panel = self._get_result_panel()
        if panel is not None:
            panel.set_busy(False)
            panel.show_record(record)

    def _on_analysis_failed(self, reason: str) -> None:
        self._analysis_runner = None
        self._set_status(
            f"Eagle Eye analysis failed: {reason} - the captured images are saved",
            active=False,
        )
        self._refresh_result_button()
        panel = self._result_panel
        if panel is not None and panel.isVisible():
            panel.set_busy(False)
            record = self._record()
            if record is not None:
                panel.show_record(record)

    def open_result(self) -> None:
        """Present stored state without sending the study again."""
        record = self._record()
        if record is None:
            return
        panel = self._get_result_panel()
        if panel is None:
            return
        if record.in_flight:
            panel.set_busy(True, "Eagle Eye is analyzing the lumbar MRI...")
            panel.present()
            return
        panel.set_busy(False)
        panel.show_record(record)

    def teardown(self) -> None:
        """Detach in-flight work before the host's child widgets are destroyed."""
        controller = self._capture_controller
        self._capture_controller = None
        if controller is not None:
            try:
                controller.abort("the Eagle Eye tab was closed")
            except Exception:
                pass

        runner = self._analysis_runner
        self._analysis_runner = None
        if runner is not None:
            try:
                runner.detach()
            except Exception:
                pass

        panel = self._result_panel
        self._result_panel = None
        if panel is not None:
            try:
                panel.close()
                panel.deleteLater()
            except Exception:
                pass

    def _record(self) -> Any:
        if not self._session_dir:
            return None
        try:
            from . import analysis_store

            return analysis_store.read_record(self._session_dir)
        except Exception as exc:
            print(f"[EAGLE-EYE-LLM] could not read the analysis state: {exc}")
            return None

    def _get_result_panel(self) -> Any:
        if self._result_panel is None:
            try:
                from .result_panel import EagleEyeResultPanel
            except Exception as exc:
                print(f"[EAGLE-EYE-LLM] result panel unavailable: {exc}")
                return None
            panel = EagleEyeResultPanel(parent=self._host)
            panel.reanalyzeRequested.connect(self._reanalyze)
            self._result_panel = panel
        return self._result_panel

    def _reanalyze(self) -> None:
        self.start_analysis(force=True)

    def _refresh_result_button(self) -> None:
        button = getattr(self._host, "eagle_eye_result_btn", None)
        if button is None:
            return
        record = self._record()
        if record is None or record.state == "not_analyzed":
            button.hide()
            return
        button.setText(
            "View Eagle Eye Result" if record.has_result else "Eagle Eye Analysis Details"
        )
        button.show()

    def _set_status(self, text: str, *, active: bool) -> None:
        self._host.set_processing_status(text, active=active)
