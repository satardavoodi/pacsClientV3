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
    router = (ROOT / "modules" / "ai_imaging" / "intelligent_analysis_router.py").read_text(
        encoding="utf-8"
    )
    assert "DXWristAnalysisController" in source
    assert "MammographyAnalysisController" in source
    assert "IntelligentAnalysisRouter" in source
    assert "def _on_intelligent_ai_analyze_clicked" not in source
    assert "self._dx_wrist.start()" in router
    assert "self._mammography.start()" in router


def test_mammography_payload_still_contains_images_boxes_and_csv():
    runner = MG_RUNNER.read_text(encoding="utf-8")
    builder = MG_BUILDER.read_text(encoding="utf-8")
    assert "MammographyAnalysisRunner" in runner
    assert "package.images" in runner
    assert "resolve_active_csv_paths" in runner
    assert "MammographyFinding" in builder
    assert "findings=tuple(findings)" in builder
    assert "structured detections" in builder


def test_dx_result_uses_the_same_echomind_report_transfer():
    controller = (DX_PACKAGE / "controller.py").read_text(encoding="utf-8")
    finish_start = controller.index("def _on_finished")
    finish_end = controller.index("def _on_failed", finish_start)
    finish = controller[finish_start:finish_end]
    assert "_review_findings" in finish
    assert "_handoff_to_echomind(reviewed)" in finish
    assert "_handoff_to_echomind" not in controller[controller.index("def start"):finish_start]


def test_ai_analysis_loading_status_hides_technical_worker_details():
    source = (DX_PACKAGE / "controller.py").read_text(encoding="utf-8")
    assert "_WAIT_MESSAGES" in source
    assert "setInterval(3000)" in source
    for technical in ("PNG images prepared", "sending to model API", "Preparing DX wrist images"):
        assert technical not in source
