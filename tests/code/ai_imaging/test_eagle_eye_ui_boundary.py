"""Architecture guards for the Eagle Eye workflow/UI boundary."""

from __future__ import annotations

import ast
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from modules.ai_imaging.eagle_eye_lumbar.analysis_store import (
    AnalysisRecord,
    STATE_COMPLETE,
)
from modules.ai_imaging.eagle_eye_lumbar.protocols import get_protocol
from modules.ai_imaging.eagle_eye_lumbar.result_panel import EagleEyeResultPanel
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate
from modules.ai_imaging.eagle_eye_lumbar.workflow_coordinator import (
    EagleEyeWorkflowCoordinator,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
TAB_PATH = (
    REPO_ROOT
    / "modules"
    / "ai_imaging"
    / "ai_module_ui"
    / "service_tab"
    / "imaging_tab.py"
)
COORDINATOR_PATH = (
    REPO_ROOT
    / "modules"
    / "ai_imaging"
    / "eagle_eye_lumbar"
    / "workflow_coordinator.py"
)
RESULT_PANEL_PATH = COORDINATOR_PATH.with_name("result_panel.py")
INTERACTOR_PATH = (
    REPO_ROOT
    / "modules"
    / "viewer"
    / "interactor_styles"
    / "ai_chat_interactorstyle.py"
)


def _class_methods(path: Path, class_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    class_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == class_name
    )
    return {
        node.name
        for node in class_node.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_imaging_tab_delegates_the_eagle_eye_workflow_to_the_feature_package():
    """The large UI controller must not regain feature workflow methods."""
    assert COORDINATOR_PATH.is_file(), "the Eagle Eye coordinator is missing"
    assert RESULT_PANEL_PATH.is_file(), "the feature-owned result panel is missing"

    tab_source = TAB_PATH.read_text(encoding="utf-8")
    tab_methods = _class_methods(TAB_PATH, "ImagingToolsTab")
    workflow_methods = {
        "_start_lumbar_capture_session",
        "_launch_lumbar_controller",
        "_apply_resolved_mapping",
        "_on_lumbar_progress",
        "_on_lumbar_finished",
        "_on_lumbar_failed",
        "_eagle_eye_result_panel",
        "_eagle_eye_record",
        "_refresh_eagle_eye_button",
        "_start_eagle_eye_analysis",
        "_reanalyze_eagle_eye",
        "_on_eagle_eye_stage",
        "_on_eagle_eye_analysis_finished",
        "_on_eagle_eye_analysis_failed",
        "_open_eagle_eye_result",
        "_teardown_eagle_eye_analysis",
    }

    assert workflow_methods.isdisjoint(tab_methods)
    assert "EagleEyeWorkflowCoordinator" in tab_source
    assert "self._eagle_eye_workflow.start_capture" in tab_source
    assert "self._eagle_eye_workflow.open_result" in tab_source
    assert "self._eagle_eye_workflow.teardown" in tab_source
    for feature_internal in (
        "session_request",
        "classify_lumbar_series",
        "LumbarCaptureController",
        "EagleEyeAnalysisRunner",
        "analysis_store",
        "EagleEyeResultPanel",
    ):
        assert feature_internal not in tab_source
    assert not (
        TAB_PATH.parent / "eagle_eye_result_panel.py"
    ).exists(), "the feature panel must not live in the general UI package"


def test_coordinator_owns_capture_analysis_result_and_teardown_lifecycles():
    source = COORDINATOR_PATH.read_text(encoding="utf-8")
    methods = _class_methods(COORDINATOR_PATH, "EagleEyeWorkflowCoordinator")

    assert "ai_module_ui" not in source
    assert {
        "start_capture",
        "_launch_capture_controller",
        "_apply_resolved_mapping",
        "_on_capture_finished",
        "start_analysis",
        "_on_analysis_finished",
        "open_result",
        "teardown",
    } <= methods


def test_original_patient_context_crosses_the_existing_one_shot_handoff():
    interactor_source = INTERACTOR_PATH.read_text(encoding="utf-8-sig")
    coordinator_source = COORDINATOR_PATH.read_text(encoding="utf-8-sig")

    assert "session_request.with_study_context(" in interactor_source
    assert "candidates=resolution.candidates" in interactor_source
    assert "self._launch_capture_controller(selection, request)" in coordinator_source
    assert "handoff_context=(request or {}).get(\"study_context\")" in coordinator_source


class _Host(QObject):
    study_uid = "test-study"

    def __init__(self):
        super().__init__()
        self.statuses = []

    def set_processing_status(self, text, active=True):
        self.statuses.append((text, active))


def test_coordinator_reapplies_the_preflight_mapping_by_series_identity():
    host = _Host()
    coordinator = EagleEyeWorkflowCoordinator(host)
    protocol = get_protocol("lumbar_mri")
    candidates = [
        SeriesCandidate(
            index=index,
            series_uid=f"1.2.840.{index}",
            series_number=index,
            series_description=f"Series {index}",
        )
        for index, _slot in enumerate(protocol.slot_keys, start=1)
    ]
    request = {
        "protocol": {"id": protocol.id},
        "slot_series": {
            slot: {
                "series_uid": candidate.series_uid,
                "series_number": candidate.series_number,
                "series_description": candidate.series_description,
                "assigned_by": "user",
                "confidence": "high",
            }
            for slot, candidate in zip(protocol.slot_keys, candidates)
        },
    }

    selection = coordinator._apply_resolved_mapping(request, candidates)

    assert selection is not None
    for slot, candidate in zip(protocol.slot_keys, candidates):
        assert selection.candidate_for(slot) is candidate
        assert selection[slot].manual is True


def test_result_panel_uses_product_model_name_without_provider_identifiers(tmp_path):
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    record = AnalysisRecord(
        STATE_COMPLETE,
        tmp_path / "synthetic-session",
        text="PATHOLOGICAL FINDINGS\n  Synthetic finding.",
        document={
            "model": (
                "gemini-screening -> gemini-context -> "
                "gpt-verification-provider-id"
            ),
            "pipeline_id": "lumbar_pathology",
            "pipeline_version": "4.1.0",
            "stage_count": 3,
            "image_count": 34,
            "completed_at": "2026-08-29T20:23:24+00:00",
            "usage": {"total_tokens": 127813},
        },
    )
    panel = EagleEyeResultPanel()
    panel.present = lambda: None

    panel.show_record(record)
    metadata = panel.meta_label.text()

    assert "model AI-PACS AI Lumbar Analysis" in metadata
    assert "gemini" not in metadata.lower()
    assert "gpt" not in metadata.lower()
    assert "provider-id" not in metadata.lower()
    assert "prompt lumbar_pathology v4.1.0 (3 passes)" in metadata
    assert "34 images" in metadata
    assert "2026-08-29T20:23:24+00:00" in metadata
    assert "127813 tokens" in metadata
    panel.close()
    panel.deleteLater()


def test_coordinator_teardown_aborts_capture_and_detaches_analysis():
    events = []

    class Capture:
        def abort(self, reason):
            events.append(("abort", reason))

    class Runner:
        def detach(self):
            events.append(("detach", None))

    class Panel:
        def close(self):
            events.append(("close", None))

        def deleteLater(self):
            events.append(("delete", None))

    coordinator = EagleEyeWorkflowCoordinator(_Host())
    coordinator._capture_controller = Capture()
    coordinator._analysis_runner = Runner()
    coordinator._result_panel = Panel()

    coordinator.teardown()

    assert [name for name, _value in events] == ["abort", "detach", "close", "delete"]
    assert coordinator._capture_controller is None
    assert coordinator._analysis_runner is None
    assert coordinator._result_panel is None
