"""Guards for source-grounded, geometry-correlated lumbar screening."""

from __future__ import annotations

import json
import math
import sys
from dataclasses import replace
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
    EvidenceBudget,
    SeriesVolume,
)
from modules.ai_imaging.eagle_eye_lumbar import (  # noqa: E402
    analysis_store,
    clinical_context,
    llm_package,
    llm_backend,
    protocols,
    screening_attention,
    screening_evidence,
)
from modules.ai_imaging.eagle_eye_lumbar.evidence_request import build_evidence_plan  # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar.evidence_request import EvidenceFocus  # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import focus_evidence  # noqa: E402


def _volume(role: str, depth: int = 3) -> SeriesVolume:
    z, y, x = np.indices((depth, 96, 80), dtype=np.float32)
    return SeriesVolume(
        pixels=z * 25.0 + y * 0.7 + x * 0.3,
        origin=(10.0, 20.0, 30.0),
        spacing=(1.0, 1.0, 5.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane="sagittal",
        frame_of_reference_uid="synthetic-frame",
        source_geometry_verified=True,
    )


def _screening_sagittal_volume(depth: int = 11) -> SeriesVolume:
    y = np.arange(700, dtype=np.float32)[None, :, None]
    x = np.arange(400, dtype=np.float32)[None, None, :]
    z = np.arange(depth, dtype=np.float32)[:, None, None]
    return SeriesVolume(
        pixels=z * 25.0 + y * 0.7 + x * 0.3,
        origin=(10.0, 20.0, 30.0),
        spacing=(0.390625, 0.390625, 4.8),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane="sagittal",
        frame_of_reference_uid="synthetic-frame",
        source_geometry_verified=True,
    )


def _axial_stack(depth: int = 4) -> DicomSliceStack:
    slices = []
    for ordinal in range(1, depth + 1):
        y, x = np.indices((96, 80), dtype=np.float32)
        slices.append(
            DicomSlice(
                pixels=ordinal * 20.0 + y * 0.6 + x * 0.2,
                position_lps=(10.0, 20.0, 35.0 + ordinal * 5.0),
                orientation_lps=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
                pixel_spacing=(1.0, 1.0),
                source_ordinal=ordinal,
                frame_of_reference_uid="synthetic-frame",
            )
        )
    return DicomSliceStack(tuple(slices), plane="axial")


def _package(tmp_path: Path) -> llm_package.AnalysisPackage:
    root = tmp_path / "session"
    root.mkdir()
    images = []
    for frame in range(1, 5):
        path = root / f"axial_{frame:03d}.png"
        Image.fromarray(np.full((32, 32), frame * 20, dtype=np.uint8)).save(path)
        images.append(
            llm_package.PackagedImage(
                path,
                f"Synthetic axial frame {frame}",
                "axial",
                frame,
                capture={
                    "panes": {
                        "axial_t2": {
                            "role": "primary",
                            "slice_index": frame - 1,
                            "position": [10.0, 20.0, 35.0 + frame * 5.0],
                        }
                    }
                },
            )
        )
    protocol = protocols.get_protocol("lumbar_mri")
    return llm_package.AnalysisPackage(
        root,
        "synthetic-correlated-screening",
        protocol.id,
        protocol.analysis,
        "SYNTHETIC LUMBAR CAPTURE",
        images,
        source_series={
            role: {
                "index": index,
                "series_uid": f"synthetic-{index}",
                "series_number": index,
                "series_description": role,
                "modality": "MR",
                "plane": "axial" if role == "axial_t2" else "sagittal",
                "slice_count": 4 if role == "axial_t2" else 3,
                "series_path": str(tmp_path / role),
                "assigned_by": "automatic",
                "confidence": "high",
            }
            for index, role in enumerate(
                ("sagittal_t2", "sagittal_t1", "axial_t2"), start=1
            )
        },
    )


def test_correlated_screening_atlas_resolves_multiplanar_boxes_to_one_lps_anchor(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    volumes = {"sagittal_t2": _volume("sagittal_t2"), "sagittal_t1": _volume("sagittal_t1")}
    axial = _axial_stack()
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (volumes, axial),
    )

    prepared = screening_evidence.prepare_screening_package(package)

    assert prepared.evidence_audit["schema_version"] == "1.6.0"
    assert prepared.evidence_audit["coordinate_space"] == "tile_content_0_1000"
    assert prepared.evidence_audit["series_contract"]["sagittal-series-a"][
        "semantic_label"
    ] == "sagittal_t2"
    assert prepared.image_count == 3
    assert sum(len(page["tiles"]) for page in prepared.evidence_audit["pages"]) == 10
    assert all(image.evidence_mode == "focused-v4-correlated-screening" for image in prepared.images)
    manifest_text = json.dumps(prepared.evidence_audit)
    assert str(tmp_path) not in manifest_text
    assert "synthetic-1" not in manifest_text

    by_role = {}
    for page in prepared.evidence_audit["pages"]:
        for tile in page["tiles"]:
            by_role.setdefault(tile["role"], []).append((page["image_index"], tile))
    sagittal_image, sagittal_tile = by_role["sagittal_t2"][1]
    axial_image, axial_tile = by_role["axial_t2"][1]
    structured = {
        "findings": [
            {
                "structure": "disc",
                "assessment": "abnormal",
                "level": "L5-S1",
                "laterality": "right",
                "confidence": "high",
                "locations": [
                    {
                        "image": sagittal_image,
                        "tile_id": sagittal_tile["tile_id"],
                        "box_2d": [450, 450, 550, 550],
                    },
                    {
                        "image": axial_image,
                        "tile_id": axial_tile["tile_id"],
                        "box_2d": [450, 450, 550, 550],
                    },
                ],
            }
        ]
    }

    attention = screening_attention.normalize_attention(structured, prepared)
    finding = attention["findings"][0]

    assert finding["geometry"]["status"] == "verified_multiplanar"
    assert finding["geometry"]["roles"] == ["sagittal_t2", "axial_t2"]
    assert len(finding["geometry_anchor_lps"]) == 3
    assert all(math.isfinite(value) for value in finding["geometry_anchor_lps"])
    assert finding["key_frames"]["axial"] == [axial_tile["capture_frame"]]

    plan = build_evidence_plan(
        "LEVEL MAP\n  L5-S1: axial frames 1-4", attention, None
    )
    assert plan.focuses[0].geometry_anchor_lps == tuple(finding["geometry_anchor_lps"])
    assert plan.focuses[0].attention_ids == (finding["attention_id"],)


def test_correlated_atlas_keeps_uncertain_series_and_slabs_semantically_neutral(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    for source in package.source_series.values():
        source["assigned_by"] = "automatic"
        source["confidence"] = "low"
    package.evidence_audit["measured_slabs"] = [[1, 2], [3, 4]]
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {
                "sagittal_t2": _volume("sagittal_t2"),
                "sagittal_t1": _volume("sagittal_t1"),
            },
            _axial_stack(),
        ),
    )

    prepared = screening_evidence.prepare_screening_package(package)

    assert set(prepared.evidence_audit["series_contract"]) == {
        "sagittal-series-a",
        "sagittal-series-b",
        "axial-series-a",
    }
    assert all(
        record["semantic_label"] is None
        for record in prepared.evidence_audit["series_contract"].values()
    )
    axial_tiles = [
        tile
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["series_id"] == "axial-series-a"
    ]
    assert [tile["geometry_group_id"] for tile in axial_tiles] == [
        "axial-group-01",
        "axial-group-01",
        "axial-group-02",
        "axial-group-02",
    ]
    assert all(tile["tile_id"].startswith("axial-series-a:") for tile in axial_tiles)
    sagittal_groups = prepared.evidence_audit["geometry_groups"]["sagittal"]
    assert [group["group_id"] for group in sagittal_groups] == [
        "sagittal-group-01",
        "sagittal-group-02",
        "sagittal-group-03",
    ]
    sagittal_tiles = [
        tile
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["series_id"].startswith("sagittal-series-")
    ]
    assert all(tile.get("geometry_group_id") for tile in sagittal_tiles)
    assert {
        tile["geometry_group_id"] for tile in sagittal_tiles
    } == {group["group_id"] for group in sagittal_groups}
    assert all(
        group["meaning"] == "geometry_only_unlabelled_sagittal_region"
        for group in sagittal_groups
    )
    sent_text = "\n".join(
        [prepared.header, *(image.caption for image in prepared.images)]
    ).lower()
    assert "axial group 1 = l1-l2" not in sent_text
    assert "sagittal_t1:" not in sent_text
    assert "sagittal_t2:" not in sent_text


def test_sagittal_group_ids_share_patient_space_when_series_order_is_reversed(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    depth = 9
    t2 = _volume("sagittal_t2", depth=depth)
    t1 = replace(
        t2,
        pixels=t2.pixels[::-1].copy(),
        origin=(t2.origin[0], t2.origin[1], t2.origin[2] + (depth - 1) * t2.spacing[2]),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, -1.0),
    )
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: ({"sagittal_t2": t2, "sagittal_t1": t1}, _axial_stack()),
    )

    prepared = screening_evidence.prepare_screening_package(package)
    first_group = prepared.evidence_audit["geometry_groups"]["sagittal"][0]

    assert first_group["series_members"]["sagittal-series-a"]["source_slices"] == [
        1,
        2,
        3,
    ]
    assert set(
        first_group["series_members"]["sagittal-series-b"]["source_slices"]
    ) == {7, 8, 9}


def test_gate1_atlas_uses_spaced_geometry_blocks_for_sagittal_and_axial_groups(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    package.evidence_audit["measured_slabs"] = [[1, 2], [3, 4]]
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {
                "sagittal_t2": _volume("sagittal_t2", depth=11),
                "sagittal_t1": _volume("sagittal_t1", depth=11),
            },
            _axial_stack(),
        ),
    )

    prepared = screening_evidence.prepare_screening_package(package)

    assert prepared.evidence_audit["schema_version"] == "1.6.0"
    for series_id, expected_groups in {
        "sagittal-series-a": {
            "sagittal-group-01", "sagittal-group-02", "sagittal-group-03"
        },
        "sagittal-series-b": {
            "sagittal-group-01", "sagittal-group-02", "sagittal-group-03"
        },
        "axial-series-a": {"axial-group-01", "axial-group-02"},
    }.items():
        pages = [
            page for page in prepared.evidence_audit["pages"]
            if page["series_id"] == series_id
        ]
        assert pages
        assert all(page["layout_kind"] == "geometry-group-blocks-v1" for page in pages)
        blocks = [block for page in pages for block in page["group_blocks"]]
        assert {block["geometry_group_id"] for block in blocks} == expected_groups
        assert all(block["primary_grouping_signal"] == "physical_spacing" for block in blocks)
        assert all(len(block["tile_ids"]) >= 1 for block in blocks)
        for page in pages:
            ordered = sorted(page["group_blocks"], key=lambda block: block["box"][1])
            assert all(
                current["box"][1] - previous["box"][3] >= 24
                for previous, current in zip(ordered, ordered[1:])
            )
            assert all(tile.get("page_box") for tile in page["tiles"])


def test_screening_normalizes_one_bounded_level_card_template_per_abnormal_level(
    tmp_path, monkeypatch
):
    """Gemini proposes source tiles; the orchestrator retains only valid slots."""
    package = _package(tmp_path)
    volumes = {
        "sagittal_t2": _volume("sagittal_t2", depth=9),
        "sagittal_t1": _volume("sagittal_t1", depth=9),
    }
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (volumes, _axial_stack()),
    )
    prepared = screening_evidence.prepare_screening_package(package)
    by_role = {}
    for page in prepared.evidence_audit["pages"]:
        for tile in page["tiles"]:
            by_role.setdefault(tile["role"], []).append(
                {"image": page["image_index"], "tile_id": tile["tile_id"]}
            )
    slots = {
        "sagittal_t2.right_foraminal_plane": by_role["sagittal_t2"][0],
        "sagittal_t2.right_paracentral_plane": by_role["sagittal_t2"][2],
        "sagittal_t2.midline_plane": by_role["sagittal_t2"][4],
        "sagittal_t2.left_paracentral_plane": by_role["sagittal_t2"][6],
        "sagittal_t2.left_foraminal_plane": by_role["sagittal_t2"][8],
        "sagittal_t1.right_foraminal_plane": by_role["sagittal_t1"][0],
        "sagittal_t1.right_paracentral_plane": by_role["sagittal_t1"][2],
        "sagittal_t1.midline_plane": by_role["sagittal_t1"][4],
        "sagittal_t1.left_paracentral_plane": by_role["sagittal_t1"][6],
        "sagittal_t1.left_foraminal_plane": by_role["sagittal_t1"][8],
        "axial_t2.disc_level_plane": by_role["axial_t2"][0],
        "axial_t2.max_abnormality_plane": by_role["axial_t2"][1],
        "axial_t2.caudal_extent_plane": by_role["axial_t2"][2],
    }
    structured = {
        "schema_version": "2.4.0",
        "findings": [{
            "structure": "disc",
            "assessment": "abnormal",
            "level": "L5-S1",
            "laterality": "indeterminate",
            "confidence": "high",
            "visual_salience": "marked",
            "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "locations": [],
        }],
        "level_card_templates": [{"level": "L5-S1", "slots": slots}],
    }

    attention = screening_attention.normalize_attention(structured, prepared)

    assert attention["schema_version"] == "2.9.0"
    assert attention["level_card_template_version"] == "1.6.0"
    templates = attention["level_card_templates"]
    assert len(templates) == 1
    assert templates[0]["level"] == "L5-S1"
    assert templates[0]["status"] == "complete"
    assert templates[0]["group_integrity"]["status"] == "legacy_unavailable"
    source_tiles = {
        tile["tile_id"]: tile
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
    }
    assert [item["slot"] for item in templates[0]["slots"]] == list(slots)
    for item in templates[0]["slots"]:
        source = source_tiles[slots[item["slot"]]["tile_id"]]
        assert item["role"] == item["slot"].split(".", 1)[0]
        assert item["source_slice"] == source["source_slice"]
        assert item["capture_frame"] == source.get("capture_frame")
        assert item["selection"] == "gemini_atlas_proposal"
        assert item["abnormality_conspicuity"] is None
        assert item["attention_ids"] == []
        assert item["geometry_group_id"] == source.get("geometry_group_id")
        assert item["parent_group_id"] == source.get("geometry_group_id")
        if source.get("geometry_group_id"):
            assert (
                item["capture_frame"] if item["role"] == "axial_t2"
                else item["source_slice"]
            ) in item["parent_group_members"]
    plan = build_evidence_plan(
        "LEVEL MAP\n  L5-S1: axial frames 1-4", attention, None
    )
    assert len(plan.focuses[0].card_slots) == 13
    assert plan.focuses[0].card_slots[0].slot == "sagittal_t2.right_foraminal_plane"
    assert all(slot.geometry_group_id for slot in plan.focuses[0].card_slots[:10])


def test_level_card_slots_keep_bounded_per_tile_conspicuity_and_attention_bindings(
    tmp_path, monkeypatch
):
    """Tile scores route attention; they are never a diagnosis or disease grade."""
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {
                "sagittal_t2": _volume("sagittal_t2"),
                "sagittal_t1": _volume("sagittal_t1"),
            },
            _axial_stack(),
        ),
    )
    prepared = screening_evidence.prepare_screening_package(package)
    tile = next(
        (page, tile)
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["role"] == "sagittal_t2"
    )
    attention = screening_attention.normalize_attention({
        "schema_version": "2.5.0",
        "findings": [{
            "structure": "disc", "assessment": "abnormal", "level": "L5-S1",
            "confidence": "high", "visual_salience": "marked",
            "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "locations": [{
                "image": tile[0]["image_index"],
                "tile_id": tile[1]["tile_id"],
                "box_2d": [400, 400, 500, 500],
            }],
        }],
        "level_card_templates": [{
            "level": "L5-S1",
            "slots": {
                "sagittal_t2.midline_plane": {
                    "image": tile[0]["image_index"],
                    "tile_id": tile[1]["tile_id"],
                    "abnormality_conspicuity": 3,
                    "attention_ids": ["attention-01", "attention-99"],
                }
            },
        }],
    }, prepared)

    slot = attention["level_card_templates"][0]["slots"][0]
    assert slot["abnormality_conspicuity"] == 3
    assert slot["attention_ids"] == ["attention-01"]
    assert "screening_card_slot_attention_unbound" in attention["warnings"]

    plan = build_evidence_plan(
        "LEVEL MAP\n  L5-S1: axial frames 1-4", attention, None
    )
    assert plan.focuses[0].card_slots[0].abnormality_conspicuity == 3
    assert plan.focuses[0].card_slots[0].attention_ids == ("attention-01",)


def test_screening_rejects_a_level_card_slot_bound_to_the_wrong_sequence(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    volumes = {
        "sagittal_t2": _volume("sagittal_t2"),
        "sagittal_t1": _volume("sagittal_t1"),
    }
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (volumes, _axial_stack()),
    )
    prepared = screening_evidence.prepare_screening_package(package)
    axial_page = next(
        (page, tile)
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["role"] == "axial_t2"
    )
    structured = {
        "schema_version": "2.4.0",
        "findings": [{
            "structure": "disc", "assessment": "abnormal", "level": "L4-L5",
            "confidence": "high", "visual_salience": "marked",
            "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices",
            "locations": [],
        }],
        "level_card_templates": [{
            "level": "L4-L5",
            "slots": {
                "sagittal_t2.midline_plane": {
                    "image": axial_page[0]["image_index"],
                    "tile_id": axial_page[1]["tile_id"],
                }
            },
        }],
    }

    attention = screening_attention.normalize_attention(structured, prepared)

    assert attention["level_card_templates"][0]["slots"] == []
    assert attention["level_card_templates"][0]["status"] == "unavailable"
    assert "screening_card_slot_role_mismatch" in attention["warnings"]
    public_context = screening_attention.attention_context(attention)
    assert '"status": "degraded"' in public_context
    assert "screening_card_slot_role_mismatch" in public_context


def test_screening_rejects_reversed_patient_right_to_left_sagittal_slots(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    sagittal = replace(
        _volume("sagittal_t2", depth=5),
        direction=(0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0),
    )
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: ({"sagittal_t2": sagittal}, _axial_stack()),
    )
    prepared = screening_evidence.prepare_screening_package(package)
    tiles = [
        (page["image_index"], tile["tile_id"])
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["role"] == "sagittal_t2"
    ]
    structured = {
        "schema_version": "2.4.0",
        "findings": [{
            "structure": "disc", "assessment": "abnormal", "level": "L5-S1",
            "confidence": "high", "visual_salience": "marked",
            "within_study_priority": "dominant",
            "slice_persistence": "three_or_more_adjacent_slices", "locations": [],
        }],
        "level_card_templates": [{
            "level": "L5-S1",
            "slots": {
                "sagittal_t2.right_foraminal_plane": {
                    "image": tiles[4][0], "tile_id": tiles[4][1],
                },
                "sagittal_t2.right_paracentral_plane": {
                    "image": tiles[3][0], "tile_id": tiles[3][1],
                },
                "sagittal_t2.midline_plane": {
                    "image": tiles[2][0], "tile_id": tiles[2][1],
                },
                "sagittal_t2.left_paracentral_plane": {
                    "image": tiles[1][0], "tile_id": tiles[1][1],
                },
                "sagittal_t2.left_foraminal_plane": {
                    "image": tiles[0][0], "tile_id": tiles[0][1],
                },
            },
        }],
    }

    attention = screening_attention.normalize_attention(structured, prepared)

    assert attention["level_card_templates"][0]["slots"] == []
    assert "screening_card_slot_sagittal_order_mismatch" in attention["warnings"]


def test_sagittal_screening_uses_bounded_submillimetric_pages(tmp_path, monkeypatch):
    package = _package(tmp_path)
    volumes = {
        "sagittal_t2": _screening_sagittal_volume(),
        "sagittal_t1": _screening_sagittal_volume(),
    }
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (volumes, _axial_stack()),
    )

    prepared = screening_evidence.prepare_screening_package(package)
    audit = prepared.evidence_audit
    pages_by_role = {
        role: [page for page in audit["pages"] if page["role"] == role]
        for role in ("sagittal_t2", "sagittal_t1", "axial_t2")
    }

    assert [len(page["tiles"]) for page in pages_by_role["sagittal_t2"]] == [8, 3]
    assert [len(page["tiles"]) for page in pages_by_role["sagittal_t1"]] == [8, 3]
    assert len(pages_by_role["axial_t2"]) == 1
    assert prepared.image_count == 5
    for role in ("sagittal_t2", "sagittal_t1"):
        records = [tile for page in pages_by_role[role] for tile in page["tiles"]]
        assert [tile["source_slice"] for tile in records] == list(range(1, 12))
        assert all(tile["sampling"]["tile_size"] == [320, 555] for tile in records)
        assert all(tile["sampling"]["fitted_content_size"] == [320, 555] for tile in records)
        assert all(
            max(tile["sampling"]["effective_mm_per_pixel"]) <= 0.47
            for tile in records
        )


def test_screening_manifest_records_sampling_and_actual_request_budget(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {"sagittal_t2": _screening_sagittal_volume()},
            _axial_stack(),
        ),
    )

    prepared = screening_evidence.prepare_screening_package(package)
    audit = prepared.evidence_audit
    actual_pixels = 0
    for image in prepared.images:
        with Image.open(image.path) as opened:
            actual_pixels += opened.width * opened.height

    assert audit["budget"] == {
        "image_count": prepared.image_count,
        "pixel_count": actual_pixels,
        "byte_count": sum(image.path.stat().st_size for image in prepared.images),
        "max_images": 8,
        "max_pixels": 12_000_000,
        "max_bytes": 12 * 1024 * 1024,
    }
    assert audit["screening_sampling"]["sagittal-series-a"] == {
        "tile_size": [320, 555],
        "tiles_per_page": 8,
        "pagination_policy": "geometry_group_boundary",
        "primary_grouping_signal": "physical_spacing",
        "page_count": 2,
        "tile_count": 11,
        "effective_mm_per_pixel": {"minimum": [0.4688, 0.4688], "maximum": [0.4688, 0.4688]},
    }
    assert audit["screening_sampling"]["axial-series-a"]["tile_size"] == [256, 256]
    assert "capacity_notes" in audit


def test_screening_budget_excess_fails_closed_before_dispatch(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {"sagittal_t2": _screening_sagittal_volume()},
            _axial_stack(),
        ),
    )
    monkeypatch.setattr(
        screening_evidence,
        "DEFAULT_SCREENING_BUDGET",
        EvidenceBudget(max_images=1, max_pixels=12_000_000, max_bytes=12 * 1024 * 1024),
    )

    with pytest.raises(screening_evidence.ScreeningEvidenceError) as captured:
        screening_evidence.prepare_screening_package(package)
    assert captured.value.code == "screening_atlas_budget_exceeded"


def test_screening_quality_failure_uses_the_layout_fallback_contract(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: ({"sagittal_t2": _volume("sagittal_t2")}, _axial_stack()),
    )

    def reject(_path):
        raise ValueError("Synthetic unusable screening page")

    monkeypatch.setattr(screening_evidence, "inspect_image_quality", reject)
    with pytest.raises(screening_evidence.ScreeningEvidenceError) as captured:
        screening_evidence.prepare_screening_package(package)
    assert captured.value.code == "screening_atlas_quality_failed"


def test_screening_render_failure_uses_the_layout_fallback_contract(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: ({"sagittal_t2": _volume("sagittal_t2")}, _axial_stack()),
    )

    def reject(*_args, **_kwargs):
        raise OSError("Synthetic screening page write failure")

    monkeypatch.setattr(screening_evidence, "_render_page", reject)
    with pytest.raises(screening_evidence.ScreeningEvidenceError) as captured:
        screening_evidence.prepare_screening_package(package)
    assert captured.value.code == "screening_atlas_render_failed"


def test_result_persists_screening_sampling_and_budget_summary(tmp_path, monkeypatch, configured_direct_eagle_models):
    package = _package(tmp_path)
    monkeypatch.delenv("AIPACS_EAGLE_EYE_EVIDENCE_MODE", raising=False)
    monkeypatch.delenv("AIPACS_EAGLE_EYE_ALLOW_LEGACY_EVIDENCE", raising=False)
    monkeypatch.setenv("AIPACS_EAGLE_EYE_ATOMIC_STRUCTURE_PIPELINE", "0")
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {"sagittal_t2": _screening_sagittal_volume()},
            _axial_stack(),
        ),
    )
    monkeypatch.setattr(
        focus_evidence,
        "prepare_verification_package",
        lambda source, *_args, **_kwargs: source,
    )
    context = clinical_context.empty_context_package(
        package.study_instance_uid, package.session_dir
    )

    def send(_package, _backend, _model, stage, _header):
        if stage.name == "screening":
            return {"content": '{"schema_version":"2.2.0","findings":[]}'}
        return {"content": "FINAL REPORT\nNo pathological finding."}

    record = llm_backend.run_analysis(
        package.session_dir,
        backend=llm_backend.BACKEND_OPENAI,
        package=package,
        context_package=context,
        call=send,
    )

    assert record.state == analysis_store.STATE_COMPLETE
    summary = record.document["screening_atlas"]
    assert summary["schema_version"] == "1.6.0"
    assert summary["screening_sampling"]["sagittal-series-a"]["tile_size"] == [320, 555]
    assert summary["series_contract"]["sagittal-series-a"]["semantic_label"] == (
        "sagittal_t2"
    )
    assert "axial" in summary["geometry_groups"]
    assert summary["budget"]["image_count"] == record.document["screening_image_count"]
    assert "pages" not in summary


def test_correlated_screening_rejects_unknown_tile_identity(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: (
            {"sagittal_t2": _volume("sagittal_t2")},
            _axial_stack(),
        ),
    )
    prepared = screening_evidence.prepare_screening_package(package)
    attention = screening_attention.normalize_attention(
        {
            "findings": [
                {
                    "structure": "disc",
                    "assessment": "abnormal",
                    "level": "L4-L5",
                    "confidence": "high",
                    "locations": [
                        {
                            "image": 1,
                            "tile_id": "another-session:axial:0001",
                            "box_2d": [100, 100, 200, 200],
                        }
                    ],
                }
            ]
        },
        prepared,
    )

    assert attention["status"] == "degraded"
    assert attention["findings"][0]["locations"] == []
    assert attention["findings"][0]["geometry"]["status"] == "unavailable"
    assert "geometry_anchor_lps" not in attention["findings"][0]
    assert "screening_tile_not_in_inventory" in attention["warnings"]


def test_correlated_focus_crop_uses_lesion_anchor_instead_of_slice_center(tmp_path):
    package = _package(tmp_path)
    z, y, x = np.indices((3, 300, 300), dtype=np.float32)
    sagittal = SeriesVolume(
        pixels=z * 30.0 + y * 0.5 + x * 0.2,
        origin=(0.0, 0.0, 30.0),
        spacing=(1.0, 1.0, 5.0),
        direction=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        plane="sagittal",
        frame_of_reference_uid="synthetic-frame",
        source_geometry_verified=True,
    )
    axial = _axial_stack()
    sequence = focus_evidence._captured_axial_sequence(package, axial)
    focus = EvidenceFocus(
        focus_id="focus-01",
        level="L5-S1",
        family="disc",
        confidence="high",
        sources=("screening_candidate",),
        questions=(),
        key_axial_frames=(1,),
        attention_ids=("attention-01",),
        geometry_anchor_lps=(200.0, 180.0, 35.0),
        correspondence_status="verified_multiplanar",
        visual_salience="marked",
        within_study_priority="dominant",
        slice_persistence="three_or_more_adjacent_slices",
    )

    _path, _caption, manifest = focus_evidence._focus_image(
        {"sagittal_t2": sagittal},
        sequence,
        {
            "sagittal_t2": (0.0, 250.0),
            "axial_t2": (0.0, 250.0),
        },
        focus,
        (1, 4),
        tmp_path / "focused",
        focus_evidence._RenderProfile.for_mode("focused-v4-correlated"),
    )

    crop = manifest["sampling"]["sagittal"][0]["crop_box"]
    assert crop == [150, 130, 250, 230]
    assert manifest["anchor_source"] == "screening_geometry"
    assert manifest["attention_ids"] == ["attention-01"]
    assert manifest["visual_salience"] == "marked"
    assert manifest["within_study_priority"] == "dominant"
    assert manifest["slice_persistence"] == "three_or_more_adjacent_slices"


def test_unverified_frame_of_reference_cannot_drive_cross_series_focus_anchor(
    tmp_path, monkeypatch
):
    package = _package(tmp_path)
    volume = replace(_volume("sagittal_t2"), frame_of_reference_uid="")
    stack = DicomSliceStack(
        tuple(replace(item, frame_of_reference_uid="") for item in _axial_stack().slices),
        plane="axial",
    )
    monkeypatch.setattr(
        screening_evidence, "_load_required_sources", lambda _package: ({"sagittal_t2": volume}, stack)
    )
    prepared = screening_evidence.prepare_screening_package(package)
    tiles = {
        tile["role"]: (page["image_index"], tile)
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["source_slice"] == 2
    }
    attention = screening_attention.normalize_attention(
        {
            "findings": [{
                "structure": "disc", "assessment": "abnormal", "level": "L5-S1",
                "locations": [
                    {"image": tiles[role][0], "tile_id": tiles[role][1]["tile_id"],
                     "box_2d": [450, 450, 550, 550]}
                    for role in ("sagittal_t2", "axial_t2")
                ],
            }]
        },
        prepared,
    )

    finding = attention["findings"][0]
    assert finding["geometry"]["status"] == "frame_of_reference_unverified"
    assert "geometry_anchor_lps" not in finding
    assert "screening_correspondence_geometry_unverified" in attention["warnings"]


def test_repeated_rows_merge_only_when_geometry_supports_one_focus(tmp_path, monkeypatch):
    package = _package(tmp_path)
    monkeypatch.setattr(
        screening_evidence,
        "_load_required_sources",
        lambda _package: ({"sagittal_t2": _volume("sagittal_t2")}, _axial_stack()),
    )
    prepared = screening_evidence.prepare_screening_package(package)
    tiles = {
        tile["role"]: (page["image_index"], tile)
        for page in prepared.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["source_slice"] == 2
    }

    def row(role, box):
        image_index, tile = tiles[role]
        return {
            "structure": "disc", "assessment": "abnormal", "level": "L5-S1",
            "confidence": "high",
            "locations": [{"image": image_index, "tile_id": tile["tile_id"], "box_2d": box}],
        }

    same_focus = screening_attention.normalize_attention(
        {"findings": [
            row("sagittal_t2", [450, 450, 550, 550]),
            row("axial_t2", [450, 450, 550, 550]),
        ]},
        prepared,
    )
    assert len(same_focus["findings"]) == 1
    assert same_focus["findings"][0]["geometry"]["status"] == "verified_multiplanar"

    distinct_foci = screening_attention.normalize_attention(
        {"findings": [
            row("sagittal_t2", [0, 0, 100, 100]),
            row("sagittal_t2", [900, 900, 1000, 1000]),
        ]},
        prepared,
    )
    assert len(distinct_foci["findings"]) == 2
    assert [item["attention_id"] for item in distinct_foci["findings"]] == [
        "attention-01", "attention-02",
    ]
    assert "screening_spatially_distinct_focus_split" in distinct_foci["warnings"]
