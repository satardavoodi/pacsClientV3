"""Guards for focused-v3: the same slices, with the pixels spent on the spine.

V2 letterboxes the whole acquired field into a 256 px tile, which puts a 200 mm
lumbar axial at 0.78 mm/px and a 300 mm sagittal at 1.17 - so the 1-3 mm
base-versus-dome difference that separates a bulge from a protrusion is one to
three pixels. V3 crops each tile to a physical box around the spine first.

These guards exist so that improvement cannot be silently undone, and so V2
stays byte-identical while both modes are being compared.
"""

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
)
from modules.ai_imaging.eagle_eye_lumbar import (  # noqa: E402
    evidence_bundle,
    focus_evidence,
    llm_package,
    protocols,
)

V2 = evidence_bundle.MODE_FOCUSED_V2
V3 = evidence_bundle.MODE_FOCUSED_V3

_SCREENING = """LEVEL MAP
  L4-L5: axial frames 1-6

CANDIDATE FINDINGS
```json
{"findings": [{"level": "L4-L5", "candidate": "disc_extrusion",
"laterality": "right", "confidence": "high", "evidence": ["sagittal_t2", "axial_t2"],
"key_frames": {"axial": [3, 2, 4], "sagittal": [4]},
"note": "focal displaced material"}]}
```
"""


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
        slices.append(
            DicomSlice(
                pixels=ordinal * 11.0 + x * 0.8 + y * 0.4,
                position_lps=(0.0, 0.0, float(ordinal - 1)),
                orientation_lps=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                pixel_spacing=(1.0, 1.0),
                source_ordinal=ordinal,
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
        session_id="focused-v3-test",
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


@pytest.fixture()
def patched_volumes(monkeypatch):
    def load(candidate):
        if candidate.series_description == "sagittal_t1":
            return _volume("sagittal", 30.0)
        return _volume("sagittal", 10.0)

    monkeypatch.setattr(focus_evidence, "load_series_volume", load)
    monkeypatch.setattr(
        focus_evidence, "load_dicom_slice_stack", lambda _c: _axial_slice_stack()
    )


def _manifest(session_dir: Path, mode: str) -> dict:
    path = session_dir / ".evidence" / mode / focus_evidence.MANIFEST_NAME
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ profile --

def test_the_mode_selects_the_render_profile_and_nothing_else():
    v2 = focus_evidence._RenderProfile.for_mode(V2)
    v3 = focus_evidence._RenderProfile.for_mode(V3)
    assert v2.crop_to_spine is False
    assert v2.focus_tile == focus_evidence.TILE_SIZE
    assert v3.crop_to_spine is True
    assert v3.focus_tile == focus_evidence.FOCUS_TILE_SIZE_V3
    assert v3.focus_tile[0] > v2.focus_tile[0]
    # An unknown mode must fall back to V2 rather than crop by accident.
    assert focus_evidence._RenderProfile.for_mode("nonsense").mode == V2


def test_evidence_bundle_accepts_v3_and_leaves_the_package_for_verification():
    assert V3 in evidence_bundle.SUPPORTED_MODES
    assert V3 in evidence_bundle.VERIFICATION_ONLY_MODES
    package = object()
    assert evidence_bundle.prepare_package(package, mode=V3) is package


# --------------------------------------------------------------------- crop --

def test_the_crop_box_stays_inside_the_image_and_keeps_a_usable_minimum():
    box = focus_evidence._clamped_box(100, 100, 5.0, 5.0, 80, 80)
    assert box == (0, 0, 80, 80)
    box = focus_evidence._clamped_box(100, 100, 95.0, 95.0, 80, 80)
    assert box == (20, 20, 100, 100)
    # A request larger than the image degrades to the whole image - and the
    # image wins over the readable minimum, which would otherwise push the box
    # outside a slice smaller than MIN_ROI_PIXELS.
    assert focus_evidence._clamped_box(40, 40, 20.0, 20.0, 900, 900) == (0, 0, 40, 40)
    assert focus_evidence._clamped_box(20, 20, 10.0, 10.0, 4, 4) == (0, 0, 20, 20)
    # A tiny request never collapses below a readable tile.
    left, top, right, bottom = focus_evidence._clamped_box(200, 200, 100.0, 100.0, 2, 2)
    assert right - left >= focus_evidence.MIN_ROI_PIXELS
    assert bottom - top >= focus_evidence.MIN_ROI_PIXELS


@pytest.mark.parametrize("posterior_is_down, expect_below_centre", [(True, True), (False, False)])
def test_the_axial_crop_biases_posteriorly_using_the_direction_cosines(
    posterior_is_down, expect_below_centre
):
    """Bias must follow patient space, not an assumed array orientation."""
    column = (0.0, 1.0, 0.0) if posterior_is_down else (0.0, -1.0, 0.0)
    image_slice = DicomSlice(
        pixels=np.random.default_rng(0).random((500, 640)).astype(np.float32),
        position_lps=(0.0, 0.0, 0.0),
        orientation_lps=(1.0, 0.0, 0.0, *column),
        pixel_spacing=(0.3125, 0.3125),
        source_ordinal=1,
    )
    array = np.asarray(image_slice.pixels)
    cropped, box, spacing = focus_evidence._axial_roi(array, image_slice)
    centre_of_box = (box[1] + box[3]) / 2.0
    if expect_below_centre:
        assert centre_of_box > array.shape[0] / 2.0
    else:
        assert centre_of_box < array.shape[0] / 2.0
    # The box is the requested physical size, in pixels.
    assert cropped.shape[1] == pytest.approx(
        focus_evidence.AXIAL_ROI_MM[0] / 0.3125, abs=1)
    assert cropped.shape[0] == pytest.approx(
        focus_evidence.AXIAL_ROI_MM[1] / 0.3125, abs=1)
    assert spacing == (0.3125, 0.3125)


def test_the_crop_is_what_buys_the_resolution_back():
    """The real numbers from the 2026-08-30 case: 640x500 at 0.3125 mm/px."""
    whole_field = focus_evidence._effective_mm_per_pixel(
        (0, 0, 640, 500), (0.3125, 0.3125), focus_evidence.TILE_SIZE)
    assert whole_field == (0.7812, 0.7812)

    cropped = focus_evidence._effective_mm_per_pixel(
        (166, 82, 473, 415), (0.3125, 0.3125), focus_evidence.FOCUS_TILE_SIZE_V3)
    assert cropped == (0.3125, 0.3125)          # native - fit_grayscale never upscales
    assert cropped[0] < whole_field[0] / 2.0    # and better than twice as sharp


def test_a_sagittal_crop_centres_on_the_projected_point():
    volume = _volume("sagittal")
    array = np.asarray(volume.pixels[4])
    _cropped, box, spacing = focus_evidence._sagittal_roi(
        array, volume, (30.0, 90.0, 4.0), (40.0, 40.0))
    assert spacing == (1.0, 1.0)
    assert (box[0] + box[2]) / 2.0 == pytest.approx(30.0, abs=1.0)
    assert (box[1] + box[3]) / 2.0 == pytest.approx(90.0, abs=1.0)


# ---------------------------------------------------------------- end to end --

def test_v3_writes_its_own_evidence_folder_with_larger_audited_tiles(
    tmp_path, patched_volumes
):
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), _SCREENING,
        json.loads(_SCREENING.split("```json")[1].split("```")[0]),
        None, mode=V3,
    )
    session_dir = package.images[0].path.parents[2]
    assert (session_dir / ".evidence" / V3).is_dir()
    assert all(item.evidence_mode == V3 for item in package.images)

    manifest = _manifest(session_dir, V3)
    assert manifest["evidence_mode"] == V3
    profile = manifest["render_profile"]
    assert profile["crop_to_spine"] is True
    assert profile["focus_tile"] == list(focus_evidence.FOCUS_TILE_SIZE_V3)
    assert profile["axial_roi_mm"] == list(focus_evidence.AXIAL_ROI_MM)
    # The sagittal overview crop is tall and narrow; a square tile would let
    # the height set the scale and give the crop back almost nothing.
    assert profile["sagittal_overview_tile"] == list(
        focus_evidence.SAGITTAL_OVERVIEW_TILE_V3)
    assert profile["sagittal_overview_tile"][1] > profile["sagittal_overview_tile"][0]

    focus = manifest["focuses"][0]
    assert focus["tile_size"] == list(focus_evidence.FOCUS_TILE_SIZE_V3)
    # Every tile records the crop used and what one tile pixel is worth, so a
    # bad centre or a silent downscale is auditable after the fact.
    for tile in focus["sampling"]["axial"]:
        assert len(tile["crop_box"]) == 4
        assert len(tile["mm_per_pixel"]) == 2
    assert focus["sampling"]["sagittal"]
    assert manifest["overview_sampling"]["axial_overview"]


def test_the_v3_header_tells_the_model_the_field_was_cropped(tmp_path, patched_volumes):
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), _SCREENING,
        json.loads(_SCREENING.split("```json")[1].split("```")[0]),
        None, mode=V3,
    )
    assert "FOCUSED V3" in package.header
    assert "cropped to a fixed physical box" in package.header
    assert "not assessable" in package.header


def test_v2_is_untouched_by_the_v3_work(tmp_path, patched_volumes):
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), _SCREENING,
        json.loads(_SCREENING.split("```json")[1].split("```")[0]),
        None, mode=V2,
    )
    session_dir = package.images[0].path.parents[2]
    assert (session_dir / ".evidence" / V2).is_dir()
    assert not (session_dir / ".evidence" / V3).exists()
    assert all(item.evidence_mode == V2 for item in package.images)
    assert "FOCUSED V2" in package.header
    assert "cropped to a fixed physical box" not in package.header

    manifest = _manifest(session_dir, V2)
    assert manifest["render_profile"]["crop_to_spine"] is False
    assert manifest["render_profile"]["axial_roi_mm"] is None
    assert manifest["focuses"][0]["tile_size"] == list(focus_evidence.TILE_SIZE)

    sheet = Image.open(session_dir / ".evidence" / V2 / "sagittal_overview.png")
    assert sheet.width % focus_evidence.TILE_SIZE[0] == 0


def test_v3_is_available_only_through_the_engineering_rollback_gate(monkeypatch):
    monkeypatch.delenv(evidence_bundle.ENV_EVIDENCE_MODE, raising=False)
    monkeypatch.delenv(evidence_bundle.ENV_ALLOW_LEGACY_EVIDENCE, raising=False)
    assert evidence_bundle.resolve_mode() == evidence_bundle.MODE_FOCUSED_V5_LEVEL_CARDS
    monkeypatch.setenv(evidence_bundle.ENV_EVIDENCE_MODE, V3)
    assert evidence_bundle.resolve_mode() == evidence_bundle.MODE_FOCUSED_V5_LEVEL_CARDS
    monkeypatch.setenv(evidence_bundle.ENV_ALLOW_LEGACY_EVIDENCE, "1")
    assert evidence_bundle.resolve_mode() == V3


def test_level_card_mode_sends_one_self_contained_card_per_focus(
    tmp_path, patched_volumes
):
    """The diagnostic reader must not reconstruct a level from global sheets."""
    structured = {
        "schema_version": "2.3.0",
        "findings": [
            {
                "attention_id": "attention-07",
                "structure": "disc",
                "assessment": "abnormal",
                "level": "L4-L5",
                "laterality": "central",
                "confidence": "high",
                "visual_salience": "marked",
                "within_study_priority": "dominant",
                "slice_persistence": "three_or_more_adjacent_slices",
                "locations": [],
                "key_frames": {"axial": [3], "sagittal": []},
                "geometry": {"status": "verified_single_plane"},
            }
        ],
    }
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path),
        "LEVEL MAP\n  L4-L5: axial frames 1-6",
        structured,
        None,
        mode="focused-v5-level-cards",
    )

    assert len(package.images) == 1
    card = package.images[0]
    assert card.evidence_mode == "focused-v5-level-cards"
    assert "ATOMIC DIAGNOSTIC CARD: disc" in card.caption
    assert "SUBJECT LEVEL L4-L5" in card.caption
    assert "attention-07" in card.caption
    assert "AX frames 1-6" in card.caption

    manifest = _manifest(package.session_dir, "focused-v5-level-cards")
    assert manifest["overview_image_count"] == 0
    assert manifest["focus_image_count"] == 1
    assert "parasagittal_supplements" not in manifest
    focus = manifest["focuses"][0]
    assert focus["attention_ids"] == ["attention-07"]
    assert 1 <= len(focus["axial_capture_frames"]) <= 3
    assert len([
        slot for slot in focus["card_slots"] if slot["role"] == "axial_t2"
    ]) == 3
    assert all(1 <= frame <= 6 for frame in focus["axial_capture_frames"])
    assert len(focus["sagittal_t2_source_slices"]) == 3
    assert len(focus["sagittal_t1_source_slices"]) == 0
    binding = manifest["card_bindings"][0]
    assert binding["image_index"] == 1
    assert binding["focus_id"] == "focus-01"
    assert binding["attention_ids"] == ["attention-07"]
    assert binding["subject_level"] == "L4-L5"
    assert binding["allowed_axial_frames"] == focus["axial_capture_frames"]
    assert binding["card_kind"] == "atomic_structure_card"
    assert binding["structure_group"] == "disc"
    assert binding["card_metadata"] == focus["card_metadata"]
    card_json_path = card.path.with_suffix(".card.json")
    assert focus["card_json_file"] == card_json_path.name
    assert binding["card_json_file"] == card_json_path.name
    assert card_json_path.is_file()
    card_payload = json.loads(card_json_path.read_text(encoding="utf-8"))
    assert card_payload == card.card_payload
    assert card_payload["image_index"] == 1
    assert card_payload["image_file"] == card.path.name
    assert card_payload["card_metadata"] == focus["card_metadata"]
    assert (
        "IMAGE 1 = focus-01 = attention-07 = SUBJECT LEVEL L4-L5 = STRUCTURE disc"
        in package.header
    )


def test_disc_card_uses_three_t2_sagittal_planes_and_three_axials(
    tmp_path, patched_volumes
):
    """A disc decision must not carry unused foraminal or sagittal T1 pixels."""
    slot_names = (
        "sagittal_t2.right_foraminal_plane",
        "sagittal_t2.right_paracentral_plane",
        "sagittal_t2.midline_plane",
        "sagittal_t2.left_paracentral_plane",
        "sagittal_t2.left_foraminal_plane",
        "sagittal_t1.right_foraminal_plane",
        "sagittal_t1.right_paracentral_plane",
        "sagittal_t1.midline_plane",
        "sagittal_t1.left_paracentral_plane",
        "sagittal_t1.left_foraminal_plane",
        "axial_t2.disc_level_plane",
        "axial_t2.max_abnormality_plane",
        "axial_t2.caudal_extent_plane",
    )
    structured = {
        "schema_version": "2.4.0",
        "atomic_pipeline_version": "2.3.0",
        "findings": [{
            "attention_id": "attention-03",
            "structure": "disc", "assessment": "abnormal", "level": "L5-S1",
            "laterality": "indeterminate", "confidence": "high",
            "visual_salience": "marked", "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "locations": [], "key_frames": {"axial": [3], "sagittal": []},
            "geometry": {"status": "verified_single_plane"},
        }],
        "level_card_template_version": "1.0.0",
        "level_card_templates": [{
            "level": "L5-S1", "status": "complete",
            "slots": [
                {
                    "slot": name,
                    "role": name.split(".", 1)[0],
                    "source_slice": (
                        (1, 3, 5, 7, 9)[index % 5]
                        if name.startswith("sagittal") else index - 9
                    ),
                    "capture_frame": (None if name.startswith("sagittal") else index - 9),
                    "selection": "gemini_atlas_proposal",
                    "geometry_group_id": (
                        "axial-group-06"
                        if name.startswith("axial")
                        else "sagittal-group-01"
                        if "right_foraminal" in name
                        else "sagittal-group-03"
                        if "left_foraminal" in name
                        else "sagittal-group-02"
                    ),
                }
                for index, name in enumerate(slot_names)
            ],
        }],
    }
    structured["group_integrity"] = {
        "version": "1.0.0",
        "status": "validated",
        "groups": [
                {
                    "group_id": "sagittal-group-01",
                    "series_role": role,
                    "member_kind": "source_slice",
                    "original_members": [1, 2],
                    "anatomical_role": "right_lateral",
            }
            for role in ("sagittal_t2", "sagittal_t1")
        ] + [
            {
                "group_id": "sagittal-group-02",
                "series_role": role,
                "member_kind": "source_slice",
                    "original_members": [3, 4, 5, 6, 7],
                    "anatomical_role": "central",
            }
            for role in ("sagittal_t2", "sagittal_t1")
        ] + [
            {
                "group_id": "sagittal-group-03",
                "series_role": role,
                "member_kind": "source_slice",
                    "original_members": [8, 9],
                    "anatomical_role": "left_lateral",
            }
            for role in ("sagittal_t2", "sagittal_t1")
        ] + [{
            "group_id": "axial-group-06",
            "series_role": "axial_t2",
            "member_kind": "capture_frame",
            "original_members": [1, 2, 3, 4, 5, 6],
        }],
    }
    parent_members = {
        ("sagittal-group-01", "sagittal_t2"): [1, 2],
        ("sagittal-group-01", "sagittal_t1"): [1, 2],
        ("sagittal-group-02", "sagittal_t2"): [3, 4, 5, 6, 7],
        ("sagittal-group-02", "sagittal_t1"): [3, 4, 5, 6, 7],
        ("sagittal-group-03", "sagittal_t2"): [8, 9],
        ("sagittal-group-03", "sagittal_t1"): [8, 9],
        ("axial-group-06", "axial_t2"): [1, 2, 3, 4, 5, 6],
    }
    for slot in structured["level_card_templates"][0]["slots"]:
        slot["parent_group_id"] = slot["geometry_group_id"]
        slot["parent_group_members"] = parent_members[
            (slot["geometry_group_id"], slot["role"])
        ]

    package = focus_evidence.prepare_verification_package(
        _package(tmp_path),
        "LEVEL MAP\n  L5-S1: axial frames 1-6",
        structured,
        None,
        mode="focused-v5-level-cards",
    )

    assert len(package.images) == 1
    with Image.open(package.images[0].path) as card:
        assert card.size == (1152, 798)
        assert card.width * card.height == 919_296
        assert card.width * card.height * 8 <= focus_evidence.DEFAULT_BUDGET.max_pixels
    manifest = _manifest(package.session_dir, "focused-v5-level-cards")
    focus = manifest["focuses"][0]
    assert focus["card_template_version"] == "2.0.0"
    assert focus["layout_kind"] == "atomic-structure-card-v1"
    assert focus["structure_group"] == "disc"
    assert focus["sagittal_sampling_policy"] == "anatomical-midline-spaced-v1"
    assert focus["tile_sizes"] == {
        "sagittal": [320, 224],
        "axial": [384, 384],
    }
    expected_visual_order = [
        "sagittal_t2.right_paracentral_plane",
        "sagittal_t2.midline_plane",
        "sagittal_t2.left_paracentral_plane",
        "axial_t2.disc_level_plane",
        "axial_t2.max_abnormality_plane",
        "axial_t2.caudal_extent_plane",
    ]
    assert [slot["slot"] for slot in focus["card_slots"]] == expected_visual_order
    assert [slot["geometry_group_id"] for slot in focus["card_slots"]] == [
        "sagittal-group-02",
        "sagittal-group-02",
        "sagittal-group-02",
        "axial-group-06",
        "axial-group-06",
        "axial-group-06",
    ]
    assert focus["card_metadata"]["geometry_group_ids"] == {
        "sagittal": ["sagittal-group-02"],
        "axial": ["axial-group-06"],
    }
    integrity = focus["card_metadata"]["group_integrity"]
    assert integrity["status"] == "validated"
    axial_parent = next(
        row for row in integrity["groups"]
        if row["group_id"] == "axial-group-06"
    )
    assert axial_parent["original_members"] == [1, 2, 3, 4, 5, 6]
    assert axial_parent["selected_members"] == [1, 2, 3]
    assert axial_parent["selection_kind"] == "focused_subset"
    assert all(
        slot["parent_group_id"] == slot["geometry_group_id"]
        for slot in focus["card_metadata"]["slots"]
    )
    assert focus["visual_reading_order"] == expected_visual_order
    assert focus["visual_groups"] == [
        {
            "group_id": "sagittal-pair-right-paracentral",
            "column": 1,
            "patient_plane": "right_paracentral_plane",
            "same_patient_plane": True,
            "reading_order": "top_to_bottom",
            "slots": ["sagittal_t2.right_paracentral_plane"],
        },
        {
            "group_id": "sagittal-pair-midline",
            "column": 2,
            "patient_plane": "midline_plane",
            "same_patient_plane": True,
            "reading_order": "top_to_bottom",
            "slots": ["sagittal_t2.midline_plane"],
        },
        {
            "group_id": "sagittal-pair-left-paracentral",
            "column": 3,
            "patient_plane": "left_paracentral_plane",
            "same_patient_plane": True,
            "reading_order": "top_to_bottom",
            "slots": ["sagittal_t2.left_paracentral_plane"],
        },
        {
            "group_id": "axial-level-sequence",
            "column": None,
            "patient_plane": "level_bound_axial_slab",
            "same_patient_plane": False,
            "reading_order": "left_to_right",
            "slots": [
                "axial_t2.disc_level_plane",
                "axial_t2.max_abnormality_plane",
                "axial_t2.caudal_extent_plane",
            ],
        },
    ]
    assert focus["sequence_border_legend"] == {
        "sagittal_t2": "cyan",
        "sagittal_t1": "amber",
        "axial_t2": "violet",
        "diagnostic_meaning": False,
    }
    assert len(focus["sagittal_t2_source_slices"]) == 3
    assert focus["sagittal_t2_source_slices"] == [3, 5, 7]
    assert focus["sagittal_t1_source_slices"] == []
    assert focus["axial_capture_frames"] == [1, 2, 3]
    assert "FOCUSED V5 ATOMIC STRUCTURE CARDS" in package.header
    assert "VOL labels are source-volume indices" in package.header
    assert "Read the printed sagittal groups first" in package.header
    assert "sequence identity only, never diagnostic meaning" in package.header
    assert "Only the printed disc question is under review" in package.images[0].caption
    payload_order = package.images[0].card_payload["card_metadata"]["layout"][
        "visual_reading_order"
    ]
    assert payload_order[:3] == expected_visual_order[:3]


def test_five_plane_fallback_orders_distinct_sagittal_slices_by_patient_lps():
    z, y, x = np.indices((11, 64, 64), dtype=np.float32)
    volume = SeriesVolume(
        pixels=z + y + x,
        origin=(-24.0, 0.0, 0.0),
        spacing=(1.0, 1.0, 4.8),
        direction=(0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0),
        plane="sagittal",
    )
    point = volume.continuous_index_to_patient((32.0, 32.0, 5.0))

    indices = focus_evidence._fallback_sagittal_indices(volume, point)

    assert indices == (1, 3, 5, 7, 9)
    patient_x = [
        volume.continuous_index_to_patient((32.0, 32.0, index))[0]
        for index in indices
    ]
    assert patient_x == sorted(patient_x)
    assert len(set(indices)) == 5


def test_diagnostic_subset_rejects_a_member_outside_its_parent_group():
    with pytest.raises(
        focus_evidence.FocusedEvidenceError,
        match="outside immutable group axial-group-01",
    ):
        focus_evidence._diagnostic_group_integrity([{
            "slot": "axial_t2.max_abnormality_plane",
            "role": "axial_t2",
            "source_slice": None,
            "capture_frame": 4,
            "geometry_group_id": "axial-group-01",
            "parent_group_id": "axial-group-01",
            "parent_group_members": [1, 2, 3],
        }])


def test_five_plane_fallback_does_not_follow_a_lateral_lesion_anchor():
    z, y, x = np.indices((11, 64, 64), dtype=np.float32)
    volume = SeriesVolume(
        pixels=z + y + x,
        origin=(-24.0, 0.0, 0.0),
        spacing=(1.0, 1.0, 4.8),
        direction=(0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0),
        plane="sagittal",
    )
    lateral_lesion_point = volume.continuous_index_to_patient((32.0, 32.0, 1.0))

    indices = focus_evidence._fallback_sagittal_indices(
        volume, lateral_lesion_point
    )

    assert indices == (1, 3, 5, 7, 9)


def test_level_card_fallback_uses_distinct_same_slab_axials_and_binds_card_json(
    tmp_path, patched_volumes
):
    """A missing Gemini template must not relabel one axial frame three times."""
    structured = {
        "schema_version": "2.5.0",
        "findings": [{
            "attention_id": "attention-01",
            "structure": "disc", "assessment": "abnormal", "level": "L5-S1",
            "laterality": "indeterminate", "confidence": "high",
            "visual_salience": "marked", "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "observable_features": {"contour_change": "marked"},
            "locations": [], "key_frames": {"axial": [6], "sagittal": []},
            "geometry": {"status": "verified_single_plane"},
        }],
    }
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path),
        "LEVEL MAP\n  L5-S1: axial frames 1-6",
        structured,
        None,
        mode="focused-v5-level-cards",
    )

    manifest = _manifest(package.session_dir, "focused-v5-level-cards")
    focus = manifest["focuses"][0]
    assert len(focus["axial_capture_frames"]) == 3
    assert all(1 <= frame <= 6 for frame in focus["axial_capture_frames"])
    assert focus["card_metadata"]["structures"][0]["structure"] == "disc"
    assert "observable_features" not in focus["card_metadata"]["structures"][0]
    assert focus["card_metadata"]["structures"][0]["abnormality_magnitude"] == "marked"
    assert package.images[0].caption.count("CARD_METADATA_JSON") == 1
    assert "CARD_METADATA_JSON: {" not in package.images[0].caption
    card_metadata = package.images[0].card_payload["card_metadata"]
    assert card_metadata == focus["card_metadata"]
    assert card_metadata["template_id"] == "mri.lumbar_spine.diagnosis.disc"
    assert card_metadata["tile_scores_are_diagnostic_severity"] is False
    assert card_metadata["structure_checklist"]["disc"] == (
        "abnormal_screening_attention"
    )
    assert set(card_metadata["structure_checklist"]) == {"disc"}
    assert card_metadata.get("required_companion_assessments") in (None, [])
    assert all(
        "markers" not in slot["reference_locator"]
        for slot in card_metadata["slots"]
    )


def test_unclear_abnormality_becomes_one_additional_findings_card(
    tmp_path, patched_volumes
):
    """An abnormal focus outside a named disc interval must not be discarded."""
    structured = {
        "schema_version": "2.5.0",
        "findings": [{
            "attention_id": "attention-09",
            "structure": "bone_marrow", "assessment": "abnormal", "level": "unclear",
            "vertebra": "L2", "laterality": "not_applicable", "confidence": "moderate",
            "visual_salience": "definite", "within_study_priority": "secondary",
            "slice_persistence": "two_adjacent_slices",
            "observable_features": {"signal_change": "definite"},
            "locations": [{
                "pane": "sagittal_t2", "source_slice": 5,
                "capture_frame": None, "box_2d": [400, 400, 500, 500],
            }],
            "key_frames": {"axial": [], "sagittal": []},
            "geometry": {"status": "verified_single_plane"},
        }],
    }
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), "LEVEL MAP", structured, None,
        mode="focused-v5-level-cards",
    )

    assert len(package.images) == 1
    assert "ADDITIONAL FINDINGS CARD" in package.images[0].caption
    manifest = _manifest(package.session_dir, "focused-v5-level-cards")
    assert manifest["focuses"][0]["card_kind"] == "additional_findings_card"
    assert manifest["focuses"][0]["attention_ids"] == ["attention-09"]
    card = package.images[0]
    card_json_path = card.path.with_suffix(".card.json")
    assert card_json_path.is_file()
    additional_payload = json.loads(card_json_path.read_text(encoding="utf-8"))
    assert additional_payload == card.card_payload
    assert additional_payload["image_index"] == 1
    assert additional_payload["card_metadata"]["card_kind"] == "additional_findings"
    assert additional_payload["card_metadata"]["subject_level"] is None
    assert "screening_focus_without_allowlisted_level" not in manifest["warnings"]


def test_t1_slots_are_geometry_synchronized_to_the_selected_t2_planes(
    tmp_path, patched_volumes
):
    slot_names = (
        "sagittal_t2.right_foraminal_plane",
        "sagittal_t2.right_paracentral_plane",
        "sagittal_t2.midline_plane",
        "sagittal_t2.left_paracentral_plane",
        "sagittal_t2.left_foraminal_plane",
        "sagittal_t1.right_foraminal_plane",
        "sagittal_t1.right_paracentral_plane",
        "sagittal_t1.midline_plane",
        "sagittal_t1.left_paracentral_plane",
        "sagittal_t1.left_foraminal_plane",
    )
    structured = {
        "findings": [{
            "attention_id": "attention-01", "structure": "endplate",
            "assessment": "abnormal", "level": "L5-S1", "confidence": "high",
            "visual_salience": "marked", "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "locations": [], "key_frames": {"axial": [3]},
        }],
        "level_card_templates": [{
            "level": "L5-S1", "slots": [
                {
                    "slot": name, "role": name.split(".", 1)[0],
                    "source_slice": (
                        (3, 4, 5, 6, 7)[index] if index < 5 else 1
                    ),
                    "capture_frame": None,
                }
                for index, name in enumerate(slot_names)
            ],
        }],
    }
    package = focus_evidence.prepare_verification_package(
        _package(tmp_path), "LEVEL MAP\n  L5-S1: axial frames 1-6",
        structured, None, mode="focused-v5-level-cards",
    )

    focus = _manifest(package.session_dir, "focused-v5-level-cards")["focuses"][0]
    assert len(focus["sagittal_t1_source_slices"]) == 3
    assert focus["sagittal_t1_source_slices"] == focus["sagittal_t2_source_slices"]
    assert any(
        slot["selection"] == "local_geometry_t1_t2_sync"
        for slot in focus["card_slots"] if slot["role"] == "sagittal_t1"
    )


def test_edge_locator_draws_only_bounded_ticks_not_an_interior_reference_line():
    z, y, x = np.indices((5, 128, 128), dtype=np.float32)
    sagittal = SeriesVolume(
        pixels=z + y + x,
        origin=(-2.0, 0.0, 0.0),
        spacing=(1.0, 1.0, 1.0),
        direction=(0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        plane="sagittal",
        frame_of_reference_uid="1.2.3",
        source_geometry_verified=True,
    )
    axial_source = DicomSlice(
        pixels=np.ones((128, 128), dtype=np.float32),
        position_lps=(-64.0, -64.0, 64.0),
        orientation_lps=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        pixel_spacing=(1.0, 1.0),
        source_ordinal=1,
        frame_of_reference_uid="1.2.3",
    )
    axial = focus_evidence._CapturedAxialSlice(
        capture_frame=7,
        capture_position_lps=axial_source.position_lps,
        source=axial_source,
    )

    markers, audit = focus_evidence._edge_locator(
        sagittal, 2, (0, 0, 128, 128), axial
    )

    assert audit["status"] == "included"
    assert audit["diagnostic_interior_line_drawn"] is False
    assert len(markers) == 2
