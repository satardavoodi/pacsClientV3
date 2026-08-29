"""Regression guards for the post-ROI Legion Consult analysis pipeline."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate
from modules.ai_imaging.eagle_eye_lumbar import llm_backend
from modules.ai_imaging.eagle_eye_lumbar.llm_package import (
    AnalysisPackage,
    PackagedImage,
)
from modules.ai_imaging.legion_consult.evidence import (
    SeriesVolume,
    build_evidence_package,
    focus_slice_indices,
    load_evidence_package,
    overview_page_indices,
    project_patient_roi,
)
from modules.ai_imaging.legion_consult.models import AttentionAnchor, LegionConsultRequest
from modules.ai_imaging.legion_consult.prompts import (
    LEGION_ANALYSIS_PIPELINE,
    LEGION_SCREENING_PROMPT,
)
from modules.ai_imaging.legion_consult.series_selection import (
    build_selection_plan,
    series_key,
)


def test_screening_prompt_is_the_user_supplied_version():
    normalized = LEGION_SCREENING_PROMPT.replace("\r\n", "\n").strip()

    assert normalized.startswith("# RADIOLOGY LESION SCREENING — LLM 1")
    assert "# STEP 1 — VERIFY THE TARGET" in normalized
    assert "## 8. NEXT-STAGE FOCUS" in normalized
    assert "Do not assume an ROI is pathological." in normalized
    assert hashlib.sha256(normalized.encode("utf-8")).hexdigest() == (
        "b22a7a8ba1dff05a2477332d02c329396dfb2321722ce37d5965cadb8999dcc9"
    )


def test_pipeline_routes_screening_to_gemini_and_verification_to_gpt_56():
    stages = LEGION_ANALYSIS_PIPELINE.stages

    assert [stage.name for stage in stages] == ["screening", "verification"]
    assert stages[0].model_feature == "eagle_eye_screening"
    assert stages[0].model_default == "gemini-3.1-pro-preview"
    assert stages[1].model_feature == "eagle_eye"
    assert stages[1].model_default == "gpt-5.6-sol"


def test_focus_indices_use_five_slices_each_side_and_clip_to_stack():
    assert focus_slice_indices(center=12, depth=30, padding=5) == tuple(range(7, 18))
    assert focus_slice_indices(center=1, depth=8, padding=5) == tuple(range(0, 7))


def test_overview_pages_cover_every_slice_exactly_once():
    pages = overview_page_indices(depth=47, tiles_per_page=20)

    assert [len(page) for page in pages] == [20, 20, 7]
    assert tuple(index for page in pages for index in page) == tuple(range(47))


def test_patient_roi_projects_through_volume_geometry():
    volume = SeriesVolume(
        pixels=np.zeros((20, 80, 100), dtype=np.float32),
        origin=(10.0, 20.0, 30.0),
        spacing=(2.0, 3.0, 4.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane="axial",
    )
    corners = (
        (30.0, 50.0, 50.0),
        (54.0, 50.0, 50.0),
        (54.0, 86.0, 50.0),
        (30.0, 86.0, 50.0),
    )

    projection = project_patient_roi(volume, corners)

    assert projection.center_slice == 5
    assert projection.bounds == (10, 10, 22, 22)


def test_series_volume_rejects_non_three_dimensional_pixels():
    try:
        SeriesVolume(
            pixels=np.zeros((20, 20), dtype=np.float32),
            origin=(0.0, 0.0, 0.0),
            spacing=(1.0, 1.0, 1.0),
            direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
            plane="axial",
        )
    except ValueError as exc:
        assert "3D" in str(exc)
    else:
        raise AssertionError("A non-3D volume must be rejected.")


def test_workflow_starts_analysis_after_request_persistence():
    source = Path("modules/ai_imaging/legion_consult/workflow.py").read_text(
        encoding="utf-8"
    )
    callback = source.split("    def _on_request_saved", 1)[1]

    assert "_start_analysis" in callback
    assert "No images were sent to an AI provider" not in callback


def test_candidate_fixture_carries_a_local_series_path_only_for_local_loading():
    candidate = SeriesCandidate(
        index=1,
        series_uid="1.2.3",
        series_number=1,
        series_description="AX T2",
        modality="MR",
        plane="axial",
        slice_count=20,
        series_path="private-source-path",
    )

    assert candidate.series_path == "private-source-path"


def _candidate(number: int, description: str, path: str) -> SeriesCandidate:
    return SeriesCandidate(
        index=number,
        series_uid=f"1.2.840.private.{number}",
        series_number=number,
        series_description=description,
        modality="MR",
        plane="axial",
        slice_count=8,
        series_path=path,
    )


def test_evidence_package_covers_stacks_and_omits_source_paths_from_manifest(
    tmp_path, monkeypatch
):
    source = _candidate(1, "AX T2", "private/patient/source")
    t1 = _candidate(2, "AX T1", "private/patient/t1")
    plan = build_selection_plan(
        study_uid="private-study-uid",
        candidates=[source, t1],
        source=source,
        t1=t1,
        t2=source,
    )
    anchor = AttentionAnchor.from_rectangle(
        source_series_key=series_key(source),
        source_slice_index=3,
        diagonal_points=((10.0, 10.0), (20.0, 20.0)),
        image_to_patient=lambda x, y, z: (x, y, float(z)),
    )
    request = LegionConsultRequest.create(plan=plan, anchor=anchor)
    volume = SeriesVolume(
        pixels=np.arange(8 * 32 * 32, dtype=np.float32).reshape(8, 32, 32),
        origin=(0.0, 0.0, 0.0),
        spacing=(1.0, 1.0, 1.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane="axial",
    )
    monkeypatch.setattr(
        "modules.ai_imaging.legion_consult.evidence.load_series_volume",
        lambda candidate: volume,
    )

    package = build_evidence_package(request, [source, t1], tmp_path)
    manifest_text = (tmp_path / "evidence_manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    assert package.image_count == 18  # one complete overview + eight focus images per series
    assert [entry["slice_count"] for entry in manifest["series"]] == [8, 8]
    assert "private/patient" not in manifest_text
    assert "1.2.840.private" not in manifest_text
    assert all(image.path.is_file() for image in package.images)
    retry = load_evidence_package(tmp_path, study_uid="private-study-uid")
    assert retry.image_count == package.image_count
    request_doc = retry.request_document(
        LEGION_ANALYSIS_PIPELINE.stages[0], model="test", backend="test"
    )
    assert request_doc["patient"] == {"patient_id": "PID 0"}
    assert all("private" not in item["caption"] for item in request_doc["sent"]["images"])


def test_two_stage_backend_carries_screening_answer_and_skips_lumbar_preparation(
    tmp_path, monkeypatch
):
    image = tmp_path / "evidence.png"
    image.write_bytes(b"png-placeholder")
    package = AnalysisPackage(
        session_dir=tmp_path,
        session_id="legion-test",
        protocol_id=LEGION_ANALYSIS_PIPELINE.id,
        analysis=LEGION_ANALYSIS_PIPELINE,
        header="LEGION EVIDENCE",
        images=[PackagedImage(image, "ROI evidence", "focus", 1)],
    )
    monkeypatch.setattr(
        "modules.ai_imaging.eagle_eye_lumbar.llm_backend.evidence_bundle.prepare_package",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("Lumbar evidence preparation must be skipped")
        ),
    )
    calls = []

    def send(_package, _backend, model, stage, header):
        calls.append((model, stage.name, header))
        answer = "STEP ONE CANDIDATES" if stage.name == "screening" else "FINAL CONSULT"
        return {"content": answer, "usage": {"model": model}}

    record = llm_backend.run_analysis(
        tmp_path,
        backend=llm_backend.BACKEND_OPENAI,
        package=package,
        call=send,
        prepare_evidence=False,
    )

    assert record.has_result
    assert record.text == "FINAL CONSULT"
    assert [item[0] for item in calls] == ["gemini-3.1-pro-preview", "gpt-5.6-sol"]
    assert "STEP ONE CANDIDATES" in calls[1][2]
