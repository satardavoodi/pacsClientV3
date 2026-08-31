"""Synthetic guards for additive, patient-space bilateral sagittal evidence."""

from dataclasses import replace
import json

import numpy as np
import pytest

from modules.ai_imaging.eagle_eye_lumbar import evidence_bundle, focus_evidence
from modules.ai_imaging.evidence_core import EvidenceBudget, SeriesVolume
from test_eagle_eye_focused_v3 import _package, _SCREENING, _axial_slice_stack


MODE = "focused-v3-parasagittal"


def _sagittal_volume(reverse=False, depth=11, spacing=5.0, angle=0.0):
    z, y, x = np.indices((depth, 160, 160), dtype=np.float32)
    theta = np.deg2rad(angle)
    sign = 1.0 if reverse else -1.0
    direction = np.array([
        [-np.sin(theta), 0.0, sign * np.cos(theta)],
        [np.cos(theta), 0.0, sign * np.sin(theta)],
        [0.0, -1.0, 0.0],
    ])
    anchor = np.array([63.5, 63.5, 6.0])
    origin = anchor - direction @ np.array([80.0, 80.0, (depth // 2) * spacing])
    return SeriesVolume(
        pixels=z * 11 + x * 0.8 + y * 0.4, origin=tuple(origin),
        spacing=(1.0, 1.0, spacing), direction=tuple(direction.flat), plane="sagittal",
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("angle", [0.0, 10.0])
def test_parasagittal_selection_uses_lps_not_index_order(reverse, angle):
    volume = _sagittal_volume(reverse=reverse, angle=angle)
    samples, metadata = focus_evidence._parasagittal_samples(volume, (63.5, 63.5, 6.0))
    offsets = [sample["offset_mm"] for sample in samples]
    assert len(samples) == 7
    assert offsets == sorted(offsets)
    assert offsets[0] < -10 and offsets[-1] > 10
    assert any(sample["reference"] for sample in samples)
    assert metadata["bilateral_coverage"] is True
    for sample in samples:
        patient = volume.continuous_index_to_patient(sample["projection"])
        assert patient[0] - 63.5 == pytest.approx(sample["offset_mm"], abs=0.01)
    indices = [sample["source_slice"] for sample in samples]
    assert indices == sorted(indices, reverse=not reverse)


def test_parasagittal_short_volume_deduplicates_and_marks_partial_coverage():
    volume = _sagittal_volume(depth=1)
    samples, metadata = focus_evidence._parasagittal_samples(volume, (63.5, 63.5, 6.0))
    assert len(samples) == 1
    assert samples[0]["reference"]
    assert metadata["bilateral_coverage"] is False
    assert metadata["unavailable_target_offsets_mm"]


@pytest.mark.parametrize("point", [(float("nan"), 0, 0), (10000, 0, 0)])
def test_parasagittal_invalid_reference_is_rejected(point):
    with pytest.raises(focus_evidence.EvidenceError):
        focus_evidence._parasagittal_samples(_sagittal_volume(), point)


def _prepare(tmp_path, monkeypatch, mode, budget=EvidenceBudget(), side="right"):
    monkeypatch.setattr(focus_evidence, "load_series_volume", lambda _: _sagittal_volume())
    monkeypatch.setattr(focus_evidence, "load_dicom_slice_stack", lambda _: _axial_slice_stack())
    package = _package(tmp_path)
    structured = json.loads(_SCREENING.split("```json")[1].split("```")[0])
    structured["findings"][0]["laterality"] = side
    result = focus_evidence.prepare_verification_package(
        package, _SCREENING, structured, None, mode=mode, budget=budget,
    )
    manifest = json.loads((package.session_dir / ".evidence" / mode /
                           "evidence_manifest.json").read_text(encoding="utf-8"))
    return result, manifest


def test_parasagittal_mode_preserves_every_baseline_image(tmp_path, monkeypatch):
    baseline, _ = _prepare(tmp_path / "base", monkeypatch, "focused-v3")
    result, manifest = _prepare(tmp_path / "extra", monkeypatch, MODE)
    assert len(result.images) == len(baseline.images) + 1
    for old, new in zip(baseline.images, result.images):
        assert old.path.read_bytes() == new.path.read_bytes()
        assert old.caption == new.caption
    record = manifest["parasagittal_supplements"][0]
    assert record["status"] == "included"
    assert record["selection"]["bilateral_coverage"] is True
    assert record["selection"]["reference_source_slice"] == 6
    assert record["tile_count"] <= 7
    assert manifest["budget"]["image_count"] == len(result.images)


def test_parasagittal_mode_does_not_trust_screening_side(tmp_path, monkeypatch):
    left, _ = _prepare(tmp_path / "left", monkeypatch, MODE, side="left")
    right, _ = _prepare(tmp_path / "right", monkeypatch, MODE, side="right")
    assert left.images[-1].path.read_bytes() == right.images[-1].path.read_bytes()


@pytest.mark.parametrize("limit", ["max_images", "max_pixels", "max_bytes"])
def test_parasagittal_budget_shortfall_retains_baseline(tmp_path, monkeypatch, limit):
    baseline, base_manifest = _prepare(tmp_path / "base", monkeypatch, "focused-v3")
    usage_key = {"max_images": "image_count", "max_pixels": "pixel_count", "max_bytes": "byte_count"}[limit]
    budget = replace(EvidenceBudget(), **{limit: base_manifest["budget"][usage_key]})
    result, manifest = _prepare(tmp_path / "limited", monkeypatch, MODE, budget=budget)
    assert [p.path.read_bytes() for p in result.images] == [p.path.read_bytes() for p in baseline.images]
    assert manifest["parasagittal_supplements"][0]["status"] == "budget_excluded"
    assert manifest["warnings"]


def test_parasagittal_mode_is_an_explicit_verification_only_choice(monkeypatch):
    monkeypatch.delenv(evidence_bundle.ENV_EVIDENCE_MODE, raising=False)
    assert evidence_bundle.resolve_mode() == "layout"
    monkeypatch.setenv(evidence_bundle.ENV_EVIDENCE_MODE, MODE)
    assert evidence_bundle.resolve_mode() == MODE
    assert MODE in evidence_bundle.VERIFICATION_ONLY_MODES
    package = object()
    assert evidence_bundle.prepare_package(package, MODE) is package


def test_parasagittal_render_failure_retains_baseline(tmp_path, monkeypatch):
    baseline, _ = _prepare(tmp_path / "base", monkeypatch, "focused-v3")

    def fail(*args):
        raise focus_evidence.EvidenceError("Synthetic render failure")

    monkeypatch.setattr(focus_evidence, "_parasagittal_image", fail)
    result, manifest = _prepare(tmp_path / "failure", monkeypatch, MODE)
    assert [p.path.read_bytes() for p in result.images] == [p.path.read_bytes() for p in baseline.images]
    assert manifest["parasagittal_supplements"][0]["status"] == "unavailable"
    assert any(w.startswith("parasagittal_unavailable:") for w in manifest["warnings"])


def test_parasagittal_missing_bilateral_coverage_is_visible(tmp_path, monkeypatch):
    original = focus_evidence._parasagittal_samples

    def coarse_samples(volume, point):
        samples, metadata = original(volume, point)
        metadata["bilateral_coverage"] = False
        metadata["unavailable_target_offsets_mm"] = []
        return [sample for sample in samples if sample["reference"]], metadata

    monkeypatch.setattr(focus_evidence, "_parasagittal_samples", coarse_samples)
    _, manifest = _prepare(tmp_path, monkeypatch, MODE)
    assert any(w.startswith("parasagittal_partial_coverage:") for w in manifest["warnings"])


def test_parasagittal_without_foci_keeps_broad_overviews(tmp_path, monkeypatch):
    monkeypatch.setattr(focus_evidence, "load_series_volume", lambda _: _sagittal_volume())
    monkeypatch.setattr(focus_evidence, "load_dicom_slice_stack", lambda _: _axial_slice_stack())
    package = _package(tmp_path)
    result = focus_evidence.prepare_verification_package(package, "", {}, None, mode=MODE)
    manifest = json.loads((package.session_dir / ".evidence" / MODE /
                           "evidence_manifest.json").read_text(encoding="utf-8"))
    assert len(result.images) == 2
    assert manifest["parasagittal_supplements"] == []


@pytest.mark.parametrize("supplement_failure", [False, True])
def test_pipeline_dispatches_supplements_only_to_verification(tmp_path, monkeypatch, supplement_failure):
    from modules.ai_imaging.eagle_eye_lumbar import analysis_store, clinical_context, llm_backend

    monkeypatch.setattr(focus_evidence, "load_series_volume", lambda _: _sagittal_volume())
    monkeypatch.setattr(focus_evidence, "load_dicom_slice_stack", lambda _: _axial_slice_stack())
    if supplement_failure:
        def fail(*args):
            raise focus_evidence.EvidenceError("Synthetic render failure")
        monkeypatch.setattr(focus_evidence, "_parasagittal_image", fail)
    monkeypatch.setenv(evidence_bundle.ENV_EVIDENCE_MODE, MODE)
    package = _package(tmp_path)
    context = clinical_context.empty_context_package(package.study_instance_uid, package.session_dir)
    calls = []

    def send(dispatched, backend, model, stage, header):
        calls.append((stage.name, dispatched))
        return {"content": _SCREENING if stage.name == "screening" else "FINAL REPORT\nTest report."}

    result = llm_backend.run_analysis(
        package.session_dir, backend=llm_backend.BACKEND_OPENAI,
        package=package, context_package=context, call=send,
    )
    assert result.state == analysis_store.STATE_COMPLETE
    assert [name for name, _ in calls] == ["screening", "verification"]
    assert all(image.evidence_mode == "layout" for image in calls[0][1].images)
    assert all(image.evidence_mode == MODE for image in calls[1][1].images)
    assert len(calls[1][1].images) == (3 if supplement_failure else 4)
