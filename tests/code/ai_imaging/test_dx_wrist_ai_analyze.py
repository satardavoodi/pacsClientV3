"""Regression guards for the isolated DX wrist intelligent analysis path."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DX_PACKAGE = ROOT / "modules" / "ai_imaging" / "dx_wrist_ai_analyze"
IMAGING_TAB = ROOT / "modules" / "ai_imaging" / "ai_module_ui" / "service_tab" / "imaging_tab.py"
MG_RUNNER = ROOT / "modules" / "ai_imaging" / "mammography_ai_analyze" / "analysis_runner.py"
MG_BUILDER = ROOT / "modules" / "ai_imaging" / "mammography_ai_analyze" / "package_builder.py"


def test_dx_wrist_package_is_separate_from_mammography_and_native_inference():
    source = "\n".join(path.read_text(encoding="utf-8") for path in DX_PACKAGE.glob("*.py"))
    assert "mammography_ai_analyze" not in source
    assert "bone_age_twosteps_inference" not in source
    assert "EagleEyeImageAnalysis" in source


def test_dx_wrist_package_requires_png_conversion_and_explains_bone_age():
    builder = (DX_PACKAGE / "package_builder.py").read_text(encoding="utf-8")
    prompt = (DX_PACKAGE / "analysis_prompt.py").read_text(encoding="utf-8")
    assert "_dicom_to_png" in builder
    assert "wrist_{index:03d}.png" in builder
    assert "BONE AGE ESTIMATE" in prompt
    assert "REASONING" in prompt
    assert "PATHOLOGICAL FINDINGS" in prompt
    assert '"hand"' in builder


def test_intelligent_analyze_routes_dx_to_new_runner_and_keeps_mg_runner():
    source = IMAGING_TAB.read_text(encoding="utf-8")
    dx_branch = source.index('if modality == "DX":')
    mg_import = source.index("from modules.ai_imaging.mammography_ai_analyze")
    dx_import = source.index("from modules.ai_imaging.dx_wrist_ai_analyze")
    mg_runner = source.index("mg_ai_runner.MammographyAnalysisRunner")
    dx_runner = source.index("dx_wrist_ai_runner.DXWristAnalysisRunner")
    assert dx_import > mg_import
    assert dx_branch < dx_runner
    assert mg_runner > dx_branch
    handler_start = source.index("def _on_intelligent_ai_analyze_clicked")
    handler_end = source.index("def _start_dx_wrist_ai_analysis", handler_start)
    assert 'if modality not in {"MG", "DX"}:' in source[handler_start:handler_end]
    assert handler_end > handler_start


def test_mammography_payload_still_contains_images_boxes_and_csv():
    runner = MG_RUNNER.read_text(encoding="utf-8")
    builder = MG_BUILDER.read_text(encoding="utf-8")
    assert "MammographyAnalysisRunner" in runner
    assert "package.images" in runner
    assert "package.csv_data" in runner
    assert "csv_data=csv_data" in builder
    assert "boxes=boxes" in builder
    assert "STRUCTURED AI DETECTION RESULTS (CSV)" in runner


def test_dx_result_uses_the_same_echomind_report_transfer():
    source = IMAGING_TAB.read_text(encoding="utf-8")
    finish_start = source.index("def _on_ai_analyze_finished")
    finish_end = source.index("def _on_ai_analyze_failed", finish_start)
    finish = source[finish_start:finish_end]
    assert "_show_editable_findings_dialog" in finish
    assert "_transfer_findings_to_echomind(edited, mode='report')" in finish
    assert "_transfer_findings_to_echomind" not in (
        source[source.index("def _start_dx_wrist_ai_analysis"):finish_start]
    )


def test_ai_analysis_loading_status_hides_technical_worker_details():
    source = IMAGING_TAB.read_text(encoding="utf-8")
    progress_start = source.index("def _on_ai_analyze_progress")
    progress_end = source.index("def _start_ai_analyze_wait_messages", progress_start)
    progress = source[progress_start:progress_end]
    assert "set_processing_status" not in progress
    assert "set_processing_status(f\"Intelligent AI Analyze: {message}\"" not in source
    assert "_AI_ANALYZE_WAIT_MESSAGES" in source
    assert "setInterval(3000)" in source
    for technical in ("PNG images prepared", "sending to model API", "Preparing DX wrist images"):
        assert technical not in source
