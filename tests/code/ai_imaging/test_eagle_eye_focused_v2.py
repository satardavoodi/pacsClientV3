"""Regression guards for candidate-directed, geometry-aligned focused evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.evidence_core import (  # noqa: E402
    DicomSlice,
    DicomSliceStack,
    SeriesVolume,
    horizontal_patient_orientation,
    inspect_image_quality,
)
from modules.ai_imaging.eagle_eye_lumbar import (  # noqa: E402
    analysis_prompt,
    analysis_store,
    clinical_context,
    evidence_bundle,
    focus_evidence,
    llm_backend,
    llm_package,
    protocols,
    session_store,
)
from modules.ai_imaging.eagle_eye_lumbar.evidence_request import (  # noqa: E402
    build_evidence_plan,
)


_SCREENING = """LEVEL MAP
  L4-L5: axial frames 1-6

CANDIDATE FINDINGS
```json
{"findings": [{"level": "L4-L5", "candidate": "disc_extrusion",
"laterality": "right", "confidence": "high", "evidence": ["sagittal_t2", "axial_t2"],
"key_frames": {"axial": [2, 1, 3], "sagittal": [4, 3, 5]},
"note": "focal displaced material"}]}
```
"""


def _structured_screening():
    return llm_backend.extract_json_block(_SCREENING)


def _volume(plane: str, offset: float = 0.0) -> SeriesVolume:
    z, y, x = np.indices((9, 128, 128), dtype=np.float32)
    pixels = offset + z * 11.0 + x * 0.8 + y * 0.4
    return SeriesVolume(
        pixels=pixels,
        origin=(0.0, 0.0, 0.0),
        spacing=(1.0, 1.0, 1.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane=plane,
    )


def _axial_slice_stack() -> DicomSliceStack:
    slices = []
    for ordinal in range(1, 10):
        y, x = np.indices((128, 128), dtype=np.float32)
        pixels = ordinal * 11.0 + x * 0.8 + y * 0.4
        slices.append(
            DicomSlice(
                pixels=pixels,
                position_lps=(0.0, 0.0, float(ordinal - 1)),
                orientation_lps=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                pixel_spacing=(1.0, 1.0),
                source_ordinal=ordinal,
            )
        )
    return DicomSliceStack(tuple(slices), plane="axial")


def _multi_slab_axial_slice_stack() -> DicomSliceStack:
    slices = []
    angle = np.deg2rad(10.0)
    for item in _axial_slice_stack().slices:
        orientation = item.orientation_lps
        if item.source_ordinal <= 6:
            orientation = (
                float(np.cos(angle)),
                float(np.sin(angle)),
                0.0,
                float(-np.sin(angle)),
                float(np.cos(angle)),
                0.0,
            )
        slices.append(
            DicomSlice(
                pixels=item.pixels,
                position_lps=item.position_lps,
                orientation_lps=orientation,
                pixel_spacing=item.pixel_spacing,
                source_ordinal=item.source_ordinal,
            )
        )
    return DicomSliceStack(tuple(slices), plane="axial")


def _source(role: str, path: Path, index: int) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    return {
        "index": index,
        "series_uid": f"1.2.840.test.{index}",
        "series_number": index,
        "series_description": role,
        "protocol_name": role,
        "modality": "MR",
        "plane": "axial" if role == "axial_t2" else "sagittal",
        "slice_count": 9,
        "series_path": str(path),
    }


def _package(tmp_path: Path) -> llm_package.AnalysisPackage:
    root = tmp_path / "session"
    layout_dir = root / "Axial"
    layout_dir.mkdir(parents=True)
    images = []
    for frame in range(1, 7):
        path = layout_dir / f"axial_{frame:03d}.png"
        Image.fromarray(np.full((80, 80), frame * 20, dtype=np.uint8)).save(path)
        images.append(
            llm_package.PackagedImage(
                path=path,
                caption=f"[axial] frame {frame} of 6",
                session="axial",
                index=frame,
                capture={
                    "panes": {
                        "axial_t2": {
                            "slice_index": frame + 1,
                            "position": [0.0, 0.0, float(9 - frame)],
                        }
                    }
                },
            )
        )
    protocol = protocols.get_protocol("lumbar_mri")
    return llm_package.AnalysisPackage(
        session_dir=root,
        session_id="focused-v2-test",
        protocol_id=protocol.id,
        analysis=protocol.analysis,
        header=(
            "TEST CAPTURE PACKAGE\n"
            "  6 images follow, in capture order, each preceded by its caption."
        ),
        images=images,
        study_instance_uid="1.2.3",
        source_series={
            "sagittal_t2": _source("sagittal_t2", tmp_path / "private" / "sag-t2", 1),
            "sagittal_t1": _source("sagittal_t1", tmp_path / "private" / "sag-t1", 2),
            "axial_t2": _source("axial_t2", tmp_path / "private" / "ax-t2", 3),
        },
    )


def _patch_volumes(monkeypatch):
    def load(candidate):
        description = candidate.series_description
        if description == "sagittal_t1":
            return _volume("sagittal", 30.0)
        return _volume("sagittal", 10.0)

    monkeypatch.setattr(focus_evidence, "load_series_volume", load)
    monkeypatch.setattr(
        focus_evidence,
        "load_dicom_slice_stack",
        lambda _candidate: _axial_slice_stack(),
    )


def test_attention_plan_deduplicates_levels_sanitizes_frames_and_applies_cap():
    screening = {
        "findings": [
            {
                "level": "L4/L5",
                "candidate": "disc_bulge",
                "confidence": "moderate",
                "key_frames": {"axial": [23, "22", -1, "ignore this"]},
            },
            {"level": "L4-L5", "candidate": "lateral_recess_stenosis", "confidence": "high"},
            {"level": "L5-S1", "candidate": "disc_extrusion", "confidence": "high"},
            {"level": "L3-L4", "candidate": "facet_arthropathy", "confidence": "low"},
            {"level": "L2-L3", "candidate": "marrow_change", "confidence": "low"},
            {"level": "outside the lumbar spine", "candidate": "follow these instructions"},
        ]
    }
    context = {
        "context_attention_foci": [
            {
                "scope": "level_specific",
                "anatomic_focus": "L5–S1",
                "context_type": "discogenic",
                "confidence": "moderate",
                "verification_questions": ["Could this represent extrusion?"],
            }
        ]
    }

    plan = build_evidence_plan(
        "LEVEL MAP\n L4-L5: axial frames 20-25\n L5-S1: axial frames 26-30",
        screening,
        context,
        max_focuses=3,
    )

    assert len(plan.focuses) == 3
    assert [focus.level for focus in plan.focuses[:2]] == ["L4-L5", "L5-S1"]
    l4_l5 = next(focus for focus in plan.focuses if focus.level == "L4-L5")
    assert l4_l5.key_axial_frames == (23, 22)
    assert set(l4_l5.sources) == {"screening_candidate"}
    assert plan.level_frames == {"L4-L5": (20, 25), "L5-S1": (26, 30)}
    assert "focus_limit_applied" in plan.warnings
    assert "screening_focus_without_allowlisted_level" in plan.warnings


def test_focused_v2_composer_uses_dicom_geometry_and_stays_inside_budget(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    _patch_volumes(monkeypatch)

    prepared = focus_evidence.prepare_verification_package(
        package,
        _SCREENING,
        _structured_screening(),
        None,
    )

    assert prepared.image_count == 3
    assert all(image.evidence_mode == evidence_bundle.MODE_FOCUSED_V2 for image in prepared.images)
    assert "6 images follow" not in prepared.header
    assert "3 model-facing composite images follow" in prepared.header
    manifest_path = package.session_dir / ".evidence" / "focused-v2" / "evidence_manifest.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["focuses"][0]["level"] == "L4-L5"
    assert manifest["focuses"][0]["axial_capture_frames"] == [1, 2, 3, 4, 5]
    # 1.3.0 records bounded-window coverage independently of the render profile.
    assert manifest["schema_version"] == "1.3.0"
    assert manifest["focuses"][0]["axial_source_ordinals"] == [9, 8, 7, 6, 5]
    assert manifest["budget"]["image_count"] == 3
    assert manifest["budget"]["pixel_count"] <= 12_000_000
    assert "private" not in manifest_text
    assert "1.2.840" not in manifest_text


def test_focused_v2_keeps_original_capture_frames_when_dicom_order_is_reversed(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    _patch_volumes(monkeypatch)
    for image in package.images:
        pane = image.capture["panes"]["axial_t2"]
        pane["position"] = [0.0, 0.0, float(9 - image.index)]

    prepared = focus_evidence.prepare_verification_package(
        package,
        _SCREENING,
        _structured_screening(),
        None,
    )

    manifest_path = (
        package.session_dir
        / ".evidence"
        / "focused-v2"
        / "evidence_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    focus = manifest["focuses"][0]

    assert focus["axial_capture_frames"] == [1, 2, 3, 4, 5]
    assert "capture frames 1-5" in prepared.images[2].caption
    assert "capture frames 1-6" in prepared.images[1].caption
    assert "AX labels are original axial capture frame numbers" in prepared.header


def test_focused_v2_neighbors_do_not_cross_an_independently_angled_slab(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    _patch_volumes(monkeypatch)
    monkeypatch.setattr(
        focus_evidence,
        "load_dicom_slice_stack",
        lambda _candidate: _multi_slab_axial_slice_stack(),
    )

    focus_evidence.prepare_verification_package(
        package,
        _SCREENING,
        _structured_screening(),
        None,
    )

    manifest_path = (
        package.session_dir
        / ".evidence"
        / "focused-v2"
        / "evidence_manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["focuses"][0]["axial_capture_frames"] == [1, 2, 3]


def _synthetic_capture_slabs(depths, boundary="gap"):
    """Use fictitious capture frames and deliberately reversed source ordinals."""
    sequence = []
    position = 0.0
    total = sum(depths)
    for slab_index, depth in enumerate(depths):
        if slab_index and boundary == "gap":
            position += 10.0
        angle = np.deg2rad(10.0 if boundary == "angle" and slab_index % 2 else 0.0)
        for _ in range(depth):
            frame = len(sequence) + 1
            source = DicomSlice(
                pixels=np.arange(64, dtype=np.float32).reshape(8, 8),
                position_lps=(0.0, 0.0, position),
                orientation_lps=(
                    float(np.cos(angle)), float(np.sin(angle)), 0.0,
                    float(-np.sin(angle)), float(np.cos(angle)), 0.0,
                ),
                pixel_spacing=(1.0, 1.0),
                source_ordinal=total - frame + 1,
            )
            sequence.append(focus_evidence._CapturedAxialSlice(
                capture_frame=frame,
                capture_position_lps=source.position_lps,
                source=source,
            ))
            position += 1.0
    return tuple(sequence)


@pytest.mark.parametrize("depth", [1, 2, 3, 4, 5, 6, 9, 12])
@pytest.mark.parametrize("padding", [0, 1, 2, 4])
def test_focus_window_fills_available_slots_without_moving_the_anchor(depth, padding):
    sequence = _synthetic_capture_slabs([depth])
    for center in range(depth):
        metadata = {}
        selected = focus_evidence._same_slab_neighbors(
            sequence, center, padding, selection_metadata=metadata
        )
        frames = [item.capture_frame for item in selected]
        assert len(frames) == min(depth, 2 * padding + 1)
        assert metadata["available_slab_depth"] == depth
        assert metadata["expected_slice_count"] == len(frames)
        assert metadata["selected_slice_count"] == len(frames)
        assert metadata["anchor_capture_frame"] == center + 1
        old_count = len(focus_evidence.focus_slice_indices(center, depth, padding))
        assert metadata["boundary_adjusted"] == (len(frames) > old_count)
        assert center + 1 in frames
        assert frames == list(range(frames[0], frames[-1] + 1))
        assert all(item is sequence[item.capture_frame - 1] for item in selected)
        if center < padding:
            assert frames[0] == 1
        elif center + padding >= depth:
            assert frames[-1] == depth
        else:
            assert frames == list(range(center - padding + 1, center + padding + 2))


@pytest.mark.parametrize("boundary", ["gap", "angle"])
@pytest.mark.parametrize("depth", [3, 5, 8])
def test_focus_window_backfill_cannot_cross_a_slab_boundary(boundary, depth):
    sequence = _synthetic_capture_slabs([5, depth, 5], boundary)
    allowed = set(range(6, 6 + depth))
    for center in range(5, 5 + depth):
        selected = focus_evidence._same_slab_neighbors(sequence, center, 2)
        frames = [item.capture_frame for item in selected]
        assert len(frames) == min(depth, 5)
        assert set(frames) <= allowed
        assert frames == list(range(frames[0], frames[-1] + 1))
        assert center + 1 in frames
        assert [item.source.source_ordinal for item in selected] == [
            len(sequence) - frame + 1 for frame in frames
        ]


def test_focus_window_empty_input_and_shared_sagittal_selection_are_unchanged():
    assert focus_evidence._same_slab_neighbors((), 0, 2) == ()
    # The bounded backfill belongs to axial focused evidence, not the shared
    # helper used by sagittal focus and other evidence consumers.
    assert focus_evidence.focus_slice_indices(0, 9, 1) == (0, 1)
    assert focus_evidence.focus_slice_indices(8, 9, 1) == (7, 8)


@pytest.mark.parametrize("mode", ["focused-v2", "focused-v3"])
def test_focus_window_manifest_preserves_sagittal_anchor_and_input_captures(
    tmp_path, monkeypatch, mode
):
    package = _package(tmp_path)
    _patch_volumes(monkeypatch)
    original_captures = [item.path.read_bytes() for item in package.images]
    prepared = focus_evidence.prepare_verification_package(
        package, _SCREENING, _structured_screening(), None, mode=mode
    )
    manifest = json.loads((
        package.session_dir / ".evidence" / mode / "evidence_manifest.json"
    ).read_text(encoding="utf-8"))
    focus = manifest["focuses"][0]
    assert focus["axial_capture_frames"] == [1, 2, 3, 4, 5]
    assert focus["axial_source_ordinals"] == [9, 8, 7, 6, 5]
    # Anchor frame 2 projects to sagittal slices 7-9; moving to the new
    # window midpoint (frame 3) would incorrectly move that projection to 6-8.
    assert focus["sagittal_t2_source_slices"] == [7, 8, 9]
    assert focus["screening_frame_range"] == [2, 2]
    assert focus["axial_window"] == {
        "policy": "same-slab-backfill-v1",
        "anchor_capture_frame": 2,
        "available_slab_depth": 6,
        "slab_capture_frame_range": [1, 6],
        "requested_slice_count": 5,
        "expected_slice_count": 5,
        "selected_slice_count": 5,
        "boundary_adjusted": True,
    }
    assert len(prepared.images) == 3
    with Image.open(prepared.images[2].path) as sheet:
        assert sheet.width == 5 * focus["tile_size"][0]
    assert [item.path.read_bytes() for item in package.images] == original_captures
    assert manifest["budget"]["pixel_count"] <= manifest["budget"]["max_pixels"]
    assert manifest["budget"]["byte_count"] <= manifest["budget"]["max_bytes"]


def test_dicom_slice_center_uses_pixel_geometry_instead_of_the_image_origin():
    image_slice = DicomSlice(
        pixels=np.ones((100, 200), dtype=np.float32),
        position_lps=(10.0, 20.0, 30.0),
        orientation_lps=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        pixel_spacing=(2.0, 3.0),
        source_ordinal=1,
    )

    assert image_slice.center_lps == pytest.approx((308.5, 119.0, 30.0))


def test_verifier_uses_capture_frames_not_raw_or_composite_indexes_for_level_maps():
    prompt = analysis_prompt.LUMBAR_VERIFICATION.text

    assert "AX frame n/N" in prompt
    assert "ORIGINAL superior-to-inferior" in prompt
    assert "axial capture-frame number" in prompt
    assert "raw" in prompt
    assert "DICOM source ordinal" in prompt
    assert "composite evidence image" in prompt
    assert "bounded to one acquisition slab" in prompt


def test_quality_gate_rejects_uniform_black_but_accepts_dark_mri_variation(tmp_path):
    black = tmp_path / "black.png"
    Image.fromarray(np.zeros((128, 128), dtype=np.uint8)).save(black)
    with pytest.raises(ValueError, match="uniform"):
        inspect_image_quality(black)

    dark = tmp_path / "dark.png"
    ramp = np.tile(np.arange(128, dtype=np.uint8) // 6, (128, 1))
    Image.fromarray(ramp).save(dark)
    quality = inspect_image_quality(dark)
    assert quality.usable
    assert quality.p99 < 32


def test_derived_axial_edge_labels_come_from_dicom_direction_cosines():
    identity = _volume("axial")
    assert horizontal_patient_orientation(identity) == ("R", "L")

    reversed_lr = SeriesVolume(
        pixels=identity.pixels,
        origin=identity.origin,
        spacing=identity.spacing,
        direction=(-1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane="axial",
    )
    assert horizontal_patient_orientation(reversed_lr) == ("L", "R")


def test_local_series_paths_are_private_provenance_not_request_content(tmp_path):
    session = session_store.create_session("1.2.3", root=tmp_path)
    source_path = tmp_path / "private" / "patient" / "axial"
    session.set_series_sources(
        {"axial_t2": _source("axial_t2", source_path, 3)}
    )
    for pass_name in session.pass_names:
        image_path = session.next_capture_path(pass_name)
        image_path.write_bytes(b"png")
        session.add_capture(pass_name, {"panes": {}})
    session.write()

    session_text = (session.path / "session.json").read_text(encoding="utf-8")
    local_text = (
        session.path / session_store.LOCAL_SERIES_SOURCES_JSON
    ).read_text(encoding="utf-8")
    package = llm_package.build_package(session.path)
    request = package.request_document(package.analysis.stages[0])

    assert "private" not in session_text
    assert "private" in local_text
    assert package.source_series["axial_t2"]["series_path"] == str(source_path)
    assert "private" not in json.dumps(request["sent"])


def test_pipeline_sends_layout_to_screening_and_focused_v2_only_to_verification(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    _patch_volumes(monkeypatch)
    monkeypatch.setenv(
        evidence_bundle.ENV_EVIDENCE_MODE,
        evidence_bundle.MODE_FOCUSED_V2,
    )
    context_package = clinical_context.empty_context_package(
        package.study_instance_uid,
        package.session_dir,
    )
    calls = []

    def send(dispatched, _backend, _model, stage, _header):
        calls.append((stage.name, dispatched))
        if stage.name == "screening":
            return {"content": _SCREENING}
        return {
            "content": (
                "VERIFICATION\n```json\n{\"verifications\": []}\n```\n\n"
                "FINAL REPORT\nPATHOLOGICAL FINDINGS\n  L4-L5: Test finding."
            )
        }

    record = llm_backend.run_analysis(
        package.session_dir,
        backend=llm_backend.BACKEND_OPENAI,
        package=package,
        context_package=context_package,
        call=send,
    )

    assert record.state == analysis_store.STATE_COMPLETE
    assert [name for name, _prepared in calls] == ["screening", "verification"]
    assert all(image.evidence_mode == "layout" for image in calls[0][1].images)
    assert all(
        image.evidence_mode == evidence_bundle.MODE_FOCUSED_V2
        for image in calls[1][1].images
    )
    result = json.loads((package.session_dir / "llm_result.json").read_text("utf-8"))
    assert result["verification_evidence_mode"] == evidence_bundle.MODE_FOCUSED_V2
    assert result["verification_image_count"] == 3


def test_focused_v2_failure_falls_back_to_immutable_layout(tmp_path, monkeypatch):
    package = _package(tmp_path)
    package.source_series.clear()
    monkeypatch.setenv(
        evidence_bundle.ENV_EVIDENCE_MODE,
        evidence_bundle.MODE_FOCUSED_V2,
    )
    context_package = clinical_context.empty_context_package(
        package.study_instance_uid,
        package.session_dir,
    )
    calls = []

    def send(dispatched, _backend, _model, stage, _header):
        calls.append((stage.name, dispatched))
        return {"content": _SCREENING if stage.name == "screening" else "FINAL REPORT\nNo finding."}

    record = llm_backend.run_analysis(
        package.session_dir,
        backend=llm_backend.BACKEND_OPENAI,
        package=package,
        context_package=context_package,
        call=send,
    )

    assert record.state == analysis_store.STATE_COMPLETE
    assert calls[1][1] is package
    result = json.loads((package.session_dir / "llm_result.json").read_text("utf-8"))
    assert result["verification_evidence_mode"] == evidence_bundle.MODE_LAYOUT
    assert "focused_v2_fallback:source_provenance_unavailable" in result["warnings"]
