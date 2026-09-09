"""Synthetic guards for report-level conflicts, independent of diagnosis."""
import pytest

from modules.ai_imaging.eagle_eye_lumbar import (
    analysis_store, clinical_context, evidence_request, llm_backend,
)
from test_eagle_eye_focused_v3 import _package


SCREEN = "LEVEL MAP\n  T12-L1: axial frames 1-2\n  L1-L2: axial frames 3-4\n  L2-L3: axial frames 5-6\n"
SHIFTED = "LEVEL MAP\n  T11-T12: axial frames 1-2\n  T12-L1: axial frames 3-4\n  L1-L2: axial frames 5-6\n"


def test_uniform_shift_is_a_conflict_even_with_same_slab_count_and_order():
    audit = evidence_request.audit_level_maps(SCREEN, SHIFTED, [(1, 2), (3, 4), (5, 6)])
    assert audit["status"] == "conflict"
    assert audit["uniform_level_offset"] == -1
    assert len(audit["slabs"]) == 3
    assert audit["slabs"][-1] == {
        "slab_id": "axial:5-6", "frames": [5, 6],
        "screening_level": "L2-L3", "verification_level": "L1-L2",
    }


def test_equal_maps_are_consistent_not_anatomically_verified():
    audit = evidence_request.audit_level_maps(SCREEN, SCREEN, [(1, 2), (3, 4), (5, 6)])
    assert audit["status"] == "consistent"
    assert audit["anatomical_numbering_verified"] is False


@pytest.mark.parametrize("report", [
    "", SCREEN.replace("L2-L3: axial frames 5-6", "L2-L3: axial frames 5-9"),
    SCREEN.replace("L2-L3: axial frames 5-6", "L2-L3: axial frames 6-5"),
    SCREEN.replace("L1-L2: axial frames 3-4", "L1-L2: axial frames 2-4"),
    SCREEN + "  L2-L3: axial frames 5-6\n",
    SCREEN.replace("  L2-L3: axial frames 5-6\n", ""),
    SCREEN.replace("T12-L1: axial frames 1-2", "T12-L1: axial frames 0-2"),
])
def test_missing_duplicate_or_invalid_map_requires_review(report):
    assert evidence_request.audit_level_maps(SCREEN, report, [(1, 2), (3, 4), (5, 6)])["status"] != "consistent"


def test_agreeing_models_cannot_override_measured_slab_boundaries():
    assert evidence_request.audit_level_maps(SCREEN, SCREEN, [(1, 3), (4, 6)])["status"] == "conflict"


def test_no_map_is_explicitly_unavailable():
    assert evidence_request.audit_level_maps("", "")["status"] == "unavailable"


@pytest.mark.parametrize("extra", [
    "  L3-L4: axial frames unknown\n", "  L3-L4: axial frames -1-7\n",
    "  L3-L4: axial frames 7-8 or 9\n", "  L3-L4: axial frames 7-\n",
])
def test_unparsed_extra_assignment_cannot_hide_behind_agreeing_rows(extra):
    audit = evidence_request.audit_level_maps(SCREEN, SCREEN + extra)
    assert audit["status"] == "conflict"
    assert "verification_unparsed_assignment" in audit["issues"]


def test_truncated_audit_input_is_not_declared_consistent():
    audit = evidence_request.audit_level_maps(SCREEN, SCREEN + " " * 200_000)
    assert audit["status"] == "conflict"
    assert "verification_input_limit_exceeded" in audit["issues"]


def test_review_state_is_visible_in_the_panel_and_copyable_body(tmp_path):
    from PySide6.QtWidgets import QApplication
    from modules.ai_imaging.eagle_eye_lumbar.result_panel import EagleEyeResultPanel
    app = QApplication.instance() or QApplication([])
    assert isinstance(app, QApplication)
    record = analysis_store.AnalysisRecord(
        analysis_store.STATE_COMPLETE, tmp_path, text="REVIEW REQUIRED\nSynthetic report.",
        document={"review_required": True},
    )
    panel = EagleEyeResultPanel()
    panel.present = lambda: None
    try:
        panel.show_record(record)
        assert "review required" in panel.title_label.text()
        assert "#fbbf24" in panel.title_label.styleSheet()
        assert panel.body.toPlainText() == record.text
        assert panel.btn_copy.isEnabled()
    finally:
        panel.close()
        panel.deleteLater()


def test_pipeline_retains_raw_answer_but_marks_displayed_report_for_review(tmp_path, monkeypatch, configured_direct_eagle_models):
    monkeypatch.setenv("AIPACS_EAGLE_EYE_EVIDENCE_MODE", "layout")
    monkeypatch.setenv("AIPACS_EAGLE_EYE_ALLOW_LEGACY_EVIDENCE", "1")
    package = _package(tmp_path)
    context = clinical_context.empty_context_package(package.study_instance_uid, package.session_dir)
    raw = "FINAL REPORT\n" + SHIFTED + "\nPATHOLOGICAL FINDINGS\n  L1-L2: Synthetic focal finding."

    def send(dispatched, backend, model, stage, header):
        return {"content": SCREEN + '\n```json\n{"findings": []}\n```' if stage.name == "screening" else raw}

    record = llm_backend.run_analysis(package.session_dir, package=package,
        context_package=context, backend=llm_backend.BACKEND_OPENAI, call=send)
    assert record.state == analysis_store.STATE_COMPLETE
    assert record.document["review_required"] is True
    assert record.document["level_assignment_audit"]["uniform_level_offset"] == -1
    assert "review" in record.label.lower()
    assert record.text.startswith("REVIEW REQUIRED")
    assert "axial:5-6" in record.text
    assert "L1-L2: Synthetic focal finding." in record.text
    assert (package.session_dir / "llm_stage3_response.txt").read_text(encoding="utf-8") == raw
    reopened = analysis_store.read_record(package.session_dir)
    assert reopened.has_result and "review" in reopened.label.lower()


def test_benchmark_shift_diagnostic_does_not_relabel_claims(tmp_path):
    from tools.eagle_eye_bench.bench import score_session
    root = tmp_path / "synthetic-session"
    root.mkdir()
    (root / "llm_stage1_response.txt").write_text(SCREEN, encoding="utf-8")
    (root / "llm_result.txt").write_text(SHIFTED + "\nPATHOLOGICAL FINDINGS\n  L1-L2: Disc extrusion.\n", encoding="utf-8")
    ref = {"case_id": "synthetic", "levels": {"L2-L3": {"disc": {"morphology": "extrusion"}}}}
    score = score_session(root, ref)
    assert score.as_dict()["level_assignment_audit"]["uniform_level_offset"] == -1
    assert next(c for c in score.claims if c.kind == "morphology").outcome != "hit"
