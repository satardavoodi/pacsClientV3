"""UI and integration guards for the Legion Consult launcher slice."""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QWidget

from modules.ai_imaging.eagle_eye_function_dialog import EagleEyeFunctionDialog
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate
from modules.ai_imaging.legion_consult.dialogs import SeriesSelectionDialog
from modules.ai_imaging.legion_consult.workflow import (
    LegionConsultCoordinator,
    _find_source_candidate,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _series(number: int, description: str, *, te: float, tr: float) -> SeriesCandidate:
    return SeriesCandidate(
        index=number,
        series_uid=f"1.2.840.{number}",
        series_number=number,
        series_description=description,
        modality="MR",
        plane="axial",
        slice_count=24,
        echo_time=te,
        repetition_time=tr,
    )


def test_function_picker_disables_legion_outside_mri(qapp):
    dialog = EagleEyeFunctionDialog("MG")
    try:
        assert dialog.list.count() == 2
        native = dialog.list.item(0)
        legion = dialog.list.item(1)
        assert native.flags() & Qt.ItemIsEnabled
        assert not (legion.flags() & Qt.ItemIsEnabled)
        assert "Legion Consult" in legion.text()
    finally:
        dialog.close()


def test_series_dialog_defaults_required_roles_and_reports_deduplicated_cost(qapp):
    source_t2 = _series(10, "AX T2", te=100, tr=4000)
    t1 = _series(11, "AX T1", te=10, tr=500)
    dialog = SeriesSelectionDialog(
        study_uid="study-1",
        candidates=[source_t2, t1],
        source=source_t2,
    )
    try:
        assert dialog.t1_combo.currentData() is t1
        assert dialog.t2_combo.currentData() is source_t2
        assert "2 series" in dialog.estimate.text()
        assert "48 images" in dialog.estimate.text()
        assert dialog.buttons.button(QDialogButtonBox.Ok).isEnabled()
    finally:
        dialog.close()


def test_source_resolution_prefers_series_uid_over_series_number():
    first = _series(10, "AX T2 A", te=100, tr=4000)
    second = _series(10, "AX T2 B", te=100, tr=4000)
    second.series_uid = "1.2.840.source"

    assert _find_source_candidate(
        [first, second],
        series_uid="1.2.840.source",
        series_number="10",
    ) is second


def test_disarming_the_owned_roi_returns_the_coordinator_to_idle(qapp, monkeypatch):
    patient_widget = QWidget()
    coordinator = LegionConsultCoordinator(patient_widget)
    warnings = []
    monkeypatch.setattr(coordinator, "_warning", warnings.append)
    coordinator._plan = object()
    coordinator._roi_callback = lambda: None
    coordinator._context = {
        "image_viewer": SimpleNamespace(
            qt_viewer=SimpleNamespace(_tool_completed_cb=None)
        )
    }

    coordinator._poll_roi_arm()

    assert coordinator._plan is None
    assert coordinator._roi_callback is None
    assert warnings == [
        "Legion Consult ROI setup was canceled before the rectangle was completed."
    ]
    patient_widget.close()


def test_toolbar_routes_eagle_eye_click_through_function_picker():
    source = Path(
        "PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py"
    ).read_text(encoding="utf-8")
    handler = source.split("    def _on_ai_analysis_clicked(self):", 1)[1].split(
        "    def _on_upload_menu_clicked", 1
    )[0]

    assert "choose_eagle_eye_function" in handler
    assert "LegionConsultCoordinator" in handler
    assert handler.index("choose_eagle_eye_function") < handler.index(
        "_trigger_eagle_eye_analysis_pipeline"
    )


def test_retry_retains_source_candidates_when_evidence_preparation_failed(
    qapp, monkeypatch, tmp_path
):
    patient_widget = QWidget()
    coordinator = LegionConsultCoordinator(patient_widget)
    request = object()
    candidates = (object(), object())
    request_path = tmp_path / "request.json"
    coordinator._current_request = request
    coordinator._current_request_path = request_path
    coordinator._current_candidates = candidates
    calls = []
    monkeypatch.setattr(
        coordinator,
        "_start_analysis",
        lambda saved_request, session_dir, saved_candidates=(): calls.append(
            (saved_request, session_dir, saved_candidates)
        ),
    )

    coordinator._reanalyze()

    assert calls == [(request, tmp_path, candidates)]
    patient_widget.close()
