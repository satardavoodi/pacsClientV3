"""Regression guards for the anatomy-only gate before pathology screening."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from PIL import Image

from modules.ai_imaging.eagle_eye_lumbar import anatomy_cards, atomic_pipeline, capture_controller
from modules.ai_imaging.eagle_eye_lumbar.llm_package import AnalysisPackage, PackagedImage


def _mapping_record(role: str, source_slice: int) -> dict:
    return {
        "kind": "volume" if role.startswith("sagittal") else "dicom_slice",
        "origin": [float(source_slice), 0.0, 0.0],
        "spacing": [1.0, 1.0, 1.0],
        "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        "slice_index": source_slice - 1,
        "position_lps": [0.0, 0.0, float(source_slice)],
        "orientation_lps": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0],
        "pixel_spacing": [1.0, 1.0],
    }


def _atlas_package(tmp_path, axial_group_count=6) -> AnalysisPackage:
    images = []
    pages = []
    specs = (
        ("sagittal_t2", "sagittal-series-a", 11, (320, 555), 6),
        ("sagittal_t1", "sagittal-series-b", 11, (320, 555), 6),
        ("axial_t2", "axial-series-a", axial_group_count * 3, (256, 256), 5),
    )
    image_index = 0
    for role, series_id, count, tile_size, columns in specs:
        rows = (count + columns - 1) // columns
        page = Image.new(
            "RGB", (columns * tile_size[0], 42 + rows * (tile_size[1] + 28)), "black"
        )
        image_index += 1
        path = tmp_path / f"{role}.png"
        page.save(path)
        tiles = []
        for index in range(1, count + 1):
            record = {
                "tile_id": f"{series_id}:{index:04d}",
                "role": role,
                "series_id": series_id,
                "source_role": role,
                "source_slice": index,
                "capture_frame": index if role == "axial_t2" else None,
                "source_crop_box": [0, 0, tile_size[0], tile_size[1]],
                "mapping": _mapping_record(role, index),
            }
            if role == "axial_t2":
                record["geometry_group_id"] = f"axial-group-{((index - 1) // 3) + 1:02d}"
            else:
                if index <= 3:
                    group_number = 1
                elif index <= 8:
                    group_number = 2
                else:
                    group_number = 3
                record["geometry_group_id"] = f"sagittal-group-{group_number:02d}"
            tiles.append(record)
        images.append(PackagedImage(path, f"{role} atlas", f"screening-{role}", image_index))
        pages.append({
            "image_index": image_index,
            "role": role,
            "page": 1,
            "tile_size": list(tile_size),
            "page_columns": columns,
            "page_header": 42,
            "cell_label": 28,
            "tiles": tiles,
        })
    return AnalysisPackage(
        tmp_path,
        "session",
        "lumbar_mri",
        SimpleNamespace(as_dict=lambda: {}),
        "atlas header",
        images,
        evidence_audit={
            "schema_version": "1.5.0",
            "pages": pages,
            "coordinate_space": "tile_content_0_1000",
            "measured_slabs": [[i * 3 + 1, i * 3 + 3] for i in range(axial_group_count)],
            "series_contract": {
                "sagittal-series-a": {
                    "plane": "sagittal", "semantic_label": "sagittal_t2",
                    "semantic_confidence": "high",
                },
                "sagittal-series-b": {
                    "plane": "sagittal", "semantic_label": "sagittal_t1",
                    "semantic_confidence": "high",
                },
                "axial-series-a": {
                    "plane": "axial", "semantic_label": "axial_t2",
                    "semantic_confidence": "high",
                },
            },
            "geometry_groups": {
                "sagittal": [
                    {
                        "group_id": f"sagittal-group-{index:02d}",
                        "spatial_order": index,
                        "meaning": "geometry_only_unlabelled_sagittal_region",
                        "series_members": {
                            series_id: {"source_slices": list(range(first, last + 1))}
                            for series_id in (
                                "sagittal-series-a",
                                "sagittal-series-b",
                            )
                        },
                    }
                    for index, (first, last) in enumerate(
                        ((1, 3), (4, 8), (9, 11)), start=1
                    )
                ],
                "axial": [
                    {
                        "group_id": f"axial-group-{index:02d}",
                        "axial_frames": [index * 3 - 2, index * 3],
                    }
                    for index in range(1, axial_group_count + 1)
                ],
            },
            "screening_sampling": {"sagittal-series-a": {"tile_count": 11}},
            "budget": {"image_count": 3},
            "capacity_notes": [],
        },
    )


def _anatomy_map(level_names=None) -> dict:
    sagittal = {}
    indices = {
        "right_foraminal": 2,
        "right_paracentral": 4,
        "midline": 6,
        "left_paracentral": 8,
        "left_foraminal": 10,
    }
    series_for_role = {
        "sagittal_t2": "sagittal-series-a",
        "sagittal_t1": "sagittal-series-b",
    }
    for role in ("sagittal_t2", "sagittal_t1"):
        sagittal[role] = {
            plane: f"{series_for_role[role]}:{index:04d}"
            for plane, index in indices.items()
        }
    levels = []
    names = level_names or ("T12-L1", "L1-L2", "L2-L3", "L3-L4", "L4-L5", "L5-S1")
    for number, level in enumerate(names):
        first = number * 3 + 1
        levels.append({
            "axial_group_id": f"axial-group-{number + 1:02d}",
            "level": level,
            "axial_frames": [first, first + 2],
            "axial_planes": {
                "disc_level": f"axial-series-a:{first:04d}",
                "subarticular": f"axial-series-a:{first + 1:04d}",
                "infrapedicular": f"axial-series-a:{first + 2:04d}",
            },
        })
    return {
        "schema_version": atomic_pipeline.ANATOMY_MAPPING_SCHEMA_VERSION,
        "sequence_assignments": {
            "sagittal_t2": {"series_id": "sagittal-series-a", "confidence": "high"},
            "sagittal_t1": {"series_id": "sagittal-series-b", "confidence": "high"},
            "axial_t2": {"series_id": "axial-series-a", "confidence": "high"},
        },
        "sagittal_group_assignments": [
            {
                "group_id": "sagittal-group-01",
                "anatomical_role": "right_lateral",
                "confidence": "high",
            },
            {
                "group_id": "sagittal-group-02",
                "anatomical_role": "central",
                "confidence": "high",
            },
            {
                "group_id": "sagittal-group-03",
                "anatomical_role": "left_lateral",
                "confidence": "high",
            },
        ],
        "sagittal_planes": sagittal,
        "axial_levels": levels,
    }


def test_anatomy_mapping_prompt_is_separate_and_diagnosis_free():
    stage = atomic_pipeline.anatomy_mapping_stage_for(SimpleNamespace(
        model_feature="eagle_eye_screening",
        model_default="gemini-3.1-pro-preview",
        temperature=1.0,
    ))

    assert stage.name == "anatomy_mapping"
    assert stage.temperature == 1.0
    assert "Do not decide whether anything is normal or abnormal" in stage.text
    assert '"sagittal_planes"' in stage.text
    assert '"axial_levels"' in stage.text
    assert '"sagittal_t2:0002"' not in stage.text
    assert '"axial_t2:0025"' not in stage.text


def test_anatomy_mapping_contract_assigns_semantics_to_neutral_geometry_groups():
    stage = atomic_pipeline.anatomy_mapping_stage_for(SimpleNamespace(
        model_feature="eagle_eye_screening",
        model_default="gemini-3.1-pro-preview",
        temperature=1.0,
    ))

    assert '"sequence_assignments"' in stage.text
    assert '"sagittal_group_assignments"' in stage.text
    assert '"axial_group_id"' in stage.text
    assert "neutral axial group" in stage.text.lower()
    assert "the workstation does not assign a lumbar level" in stage.text.lower()
    assert "Map all six measured axial slabs from T12-L1 through L5-S1" not in stage.text


def test_anatomy_gate_preserves_neutral_sagittal_groups_before_assigning_roles(tmp_path):
    atlas = _atlas_package(tmp_path)
    reply = _anatomy_map()

    normalized = anatomy_cards.normalize_anatomy_map(atlas, reply)

    assert normalized["sagittal_group_assignments"] == reply[
        "sagittal_group_assignments"
    ]
    cards = anatomy_cards.prepare_anatomy_cards(atlas, reply)
    assert all(
        tile.get("geometry_group_id")
        for page in cards.evidence_audit["pages"]
        for tile in page["tiles"]
        if tile["role"].startswith("sagittal")
    )


def test_capture_provenance_retains_sequence_assignment_confidence():
    candidate = SimpleNamespace(
        index=1,
        series_uid="synthetic-series",
        series_number="2",
        series_description="Synthetic sagittal series",
        protocol_name="Synthetic protocol",
        modality="MR",
        plane="sagittal",
        slice_count=11,
        echo_time=100.0,
        repetition_time=4000.0,
        series_path="synthetic/path",
    )
    slot = SimpleNamespace(manual=False, confidence="low")

    class Selection:
        def candidate_for(self, role):
            return candidate if role == "sagittal_t2" else None

        def __getitem__(self, role):
            assert role == "sagittal_t2"
            return slot

    sources = capture_controller._local_series_sources_for_selection(
        Selection(), ("sagittal_t2",)
    )

    assert sources["sagittal_t2"]["assigned_by"] == "automatic"
    assert sources["sagittal_t2"]["confidence"] == "low"


def test_anatomy_gate_accepts_llm_level_labels_independent_of_group_order(tmp_path):
    atlas = _atlas_package(tmp_path)
    groups = atlas.evidence_audit["geometry_groups"]["axial"]

    source = _anatomy_map()
    group_for_level = {
        "T12-L1": "axial-group-03",
        "L1-L2": "axial-group-01",
        "L2-L3": "axial-group-02",
        "L3-L4": "axial-group-06",
        "L4-L5": "axial-group-04",
        "L5-S1": "axial-group-05",
    }
    bounds_by_group = {
        row["group_id"]: row["axial_frames"] for row in groups
    }
    source["sequence_assignments"] = {
        "sagittal_t2": {"series_id": "sagittal-series-a", "confidence": "high"},
        "sagittal_t1": {"series_id": "sagittal-series-b", "confidence": "high"},
        "axial_t2": {"series_id": "axial-series-a", "confidence": "high"},
    }
    source["axial_levels"] = []
    for level, group_id in group_for_level.items():
        first, last = bounds_by_group[group_id]
        source["axial_levels"].append({
            "axial_group_id": group_id,
            "level": level,
            "axial_frames": [first, last],
            "axial_planes": {
                "disc_level": f"axial-series-a:{first:04d}",
                "subarticular": f"axial-series-a:{first + 1:04d}",
                "infrapedicular": f"axial-series-a:{last:04d}",
            },
        })

    normalized = anatomy_cards.normalize_anatomy_map(atlas, source)

    assert {
        row["level"]: row["axial_group_id"] for row in normalized["axial_levels"]
    } == group_for_level
    assert normalized["sequence_assignments"]["sagittal_t2"]["series_id"] == (
        "sagittal-series-a"
    )


def test_pathology_screening_uses_the_anatomy_card_without_level_map_conflict():
    stage = atomic_pipeline.screening_stage_for(
        SimpleNamespace(
            model_feature="eagle_eye_screening",
            model_default="gemini-3.1-pro-preview",
            temperature=1.0,
        ),
        atomic_pipeline.SCREENING_REQUESTS[0],
    )

    assert "printed on the supplied anatomy card" in stage.text
    assert "Do not return a level map" in stage.text
    assert "Keep the level map inside the JSON" not in stage.text


def test_anatomy_gate_builds_five_cards_and_one_card_per_screen(tmp_path):
    atlas = _atlas_package(tmp_path)

    cards = anatomy_cards.prepare_anatomy_cards(atlas, _anatomy_map())

    assert [image.card_payload["anatomy_card"]["request_key"] for image in cards.images] == [
        "disc",
        "canal_neural",
        "foraminal",
        "endplate_marrow",
        "posterior_elements",
    ]
    assert all(image.path.is_file() for image in cards.images)
    assert all(
        image.card_payload["anatomy_card"]["template_id"].startswith(
            "mri.lumbar_spine.screening."
        )
        for image in cards.images
    )
    assert (tmp_path / ".evidence" / "anatomy-gate-v4" / "anatomy_manifest.json").is_file()
    assert cards.evidence_audit["source_atlas"] == {
        "schema_version": "1.5.0",
        "series_contract": atlas.evidence_audit["series_contract"],
        "geometry_groups": atlas.evidence_audit["geometry_groups"],
        "screening_sampling": {"sagittal-series-a": {"tile_count": 11}},
        "budget": {"image_count": 3},
        "capacity_notes": [],
    }

    for request in atomic_pipeline.SCREENING_REQUESTS:
        package = anatomy_cards.screening_package_for(cards, request.key)
        assert package.image_count == 1
        assert package.images[0].index == 1
        assert package.evidence_audit["anatomy_card_request"] == request.key
        assert package.evidence_audit["pages"][0]["image_index"] == 1
        assert all(
            tile["image_index"] == 1
            for tile in package.evidence_audit["pages"][0]["tiles"]
        )
        sent = package.request_document(
            atomic_pipeline.screening_stage_for(
                SimpleNamespace(
                    model_feature="eagle_eye_screening",
                    model_default="gemini-3.1-pro-preview",
                    temperature=1.0,
                ),
                request,
            )
        )["sent"]
        assert sent["image_count"] == 1
        assert "ANATOMY_MAP_JSON" in sent["header"]


def test_gate1_to_2_cards_use_task_specific_spaced_geometry_blocks(tmp_path):
    cards = anatomy_cards.prepare_anatomy_cards(
        _atlas_package(tmp_path), _anatomy_map()
    )
    payloads = {
        image.card_payload["anatomy_card"]["request_key"]:
            image.card_payload["anatomy_card"]
        for image in cards.images
    }

    assert payloads["disc"]["layout_contract"]["strategy"] == (
        "central-sagittal-separated-axial-groups-v1"
    )
    assert payloads["canal_neural"]["layout_contract"]["strategy"] == (
        "central-sagittal-separated-axial-groups-v1"
    )
    assert payloads["foraminal"]["layout_contract"]["strategy"] == (
        "bilateral-lateral-sagittal-separated-axial-groups-v1"
    )
    assert payloads["posterior_elements"]["layout_contract"]["strategy"] == (
        "lateral-central-lateral-separated-axial-groups-v1"
    )
    assert payloads["endplate_marrow"]["layout_contract"]["strategy"] == (
        "paired-sagittal-grid-v1"
    )

    for key in ("disc", "canal_neural", "foraminal", "posterior_elements"):
        contract = payloads[key]["layout_contract"]
        assert contract["primary_grouping_signal"] == "physical_spacing"
        assert contract["secondary_grouping_signal"] == "section_headers"
        assert contract["tertiary_grouping_signal"] == "color"
        axial = [
            block for block in contract["blocks"]
            if block["section_kind"] == "axial_geometry_group"
        ]
        assert len(axial) == 6
        assert all(len(block["tile_ids"]) == 3 for block in axial)
        ordered = sorted(axial, key=lambda block: block["box"][1])
        assert all(
            current["box"][1] - previous["box"][3] >= 24
            for previous, current in zip(ordered, ordered[1:])
        )

    foramen = [
        block for block in payloads["foraminal"]["layout_contract"]["blocks"]
        if block["section_kind"] == "sagittal_geometry_group"
    ]
    assert {
        (block["sequence_role"], block["anatomical_role"]): len(block["tile_ids"])
        for block in foramen
    } == {
        ("sagittal_t2", "right_lateral"): 3,
        ("sagittal_t2", "left_lateral"): 3,
        ("sagittal_t1", "right_lateral"): 3,
        ("sagittal_t1", "left_lateral"): 3,
    }

    posterior = [
        block
        for block in payloads["posterior_elements"]["layout_contract"]["blocks"]
        if block["section_kind"] == "sagittal_geometry_group"
    ]
    assert {
        (block["sequence_role"], block["anatomical_role"]): len(block["tile_ids"])
        for block in posterior
    } == {
        ("sagittal_t2", "right_lateral"): 3,
        ("sagittal_t2", "central"): 5,
        ("sagittal_t2", "left_lateral"): 3,
        ("sagittal_t1", "right_lateral"): 3,
        ("sagittal_t1", "central"): 5,
        ("sagittal_t1", "left_lateral"): 3,
    }


def test_anatomy_gate_rejects_an_unknown_or_cross_role_tile(tmp_path):
    atlas = _atlas_package(tmp_path)
    document = json.loads(json.dumps(_anatomy_map()))
    document["sagittal_planes"]["sagittal_t2"]["midline"] = "axial-series-a:0001"

    try:
        anatomy_cards.prepare_anatomy_cards(atlas, document)
    except anatomy_cards.AnatomyCardError as exc:
        assert exc.code == "anatomy_map_role_conflict"
    else:
        raise AssertionError("A cross-role anatomy tile must be rejected.")


def test_anatomy_gate_rejects_conflict_with_high_confidence_sequence_metadata(tmp_path):
    atlas = _atlas_package(tmp_path)
    document = json.loads(json.dumps(_anatomy_map()))
    document["sequence_assignments"]["sagittal_t2"]["series_id"] = (
        "sagittal-series-b"
    )
    document["sequence_assignments"]["sagittal_t1"]["series_id"] = (
        "sagittal-series-a"
    )

    with pytest.raises(anatomy_cards.AnatomyCardError) as caught:
        anatomy_cards.normalize_anatomy_map(atlas, document)

    assert caught.value.code == "anatomy_map_high_confidence_sequence_conflict"


def test_anatomy_gate_corrects_sagittal_side_labels_from_physical_order(tmp_path):
    atlas = _atlas_package(tmp_path)
    for page in atlas.evidence_audit["pages"]:
        for tile in page["tiles"]:
            if tile["role"].startswith("sagittal"):
                tile["mapping"]["origin"][0] = -float(tile["source_slice"])

    normalized = anatomy_cards.normalize_anatomy_map(atlas, _anatomy_map())

    expected_indices = {
        "right_foraminal": 10,
        "right_paracentral": 8,
        "midline": 6,
        "left_paracentral": 4,
        "left_foraminal": 2,
    }
    for role in ("sagittal_t2", "sagittal_t1"):
        assert normalized["sagittal_planes"][role] == {
            plane: f"{('sagittal-series-a' if role == 'sagittal_t2' else 'sagittal-series-b')}:{index:04d}"
            for plane, index in expected_indices.items()
        }
        audit = normalized["geometry_canonicalization"][role]
        assert audit["model_role_order_differs_from_physical_order"] is True
        assert audit["physical_patient_right_to_left_tile_ids"] == [
            f"{('sagittal-series-a' if role == 'sagittal_t2' else 'sagittal-series-b')}:{index:04d}"
            for index in (10, 8, 6, 4, 2)
        ]
    assert normalized["sagittal_order_policy"] == (
        "dicom_lps_x_side_authority_v3"
    )


def test_anatomy_gate_records_axial_physical_order_without_relabelling_roles(tmp_path):
    atlas = _atlas_package(tmp_path)
    for page in atlas.evidence_audit["pages"]:
        for tile in page["tiles"]:
            if tile["role"] == "axial_t2":
                # DICOM patient Z increases superiorly. Capture order is
                # deliberately superior-to-inferior, matching a reversed
                # source-instance acquisition without trusting filenames.
                tile["mapping"]["position_lps"][2] = -float(tile["capture_frame"])

    first_reply = _anatomy_map()
    permuted_reply = json.loads(json.dumps(first_reply))
    for level in permuted_reply["axial_levels"]:
        planes = level["axial_planes"]
        planes["disc_level"], planes["subarticular"], planes["infrapedicular"] = (
            planes["subarticular"],
            planes["infrapedicular"],
            planes["disc_level"],
        )

    first = anatomy_cards.normalize_anatomy_map(atlas, first_reply)
    second = anatomy_cards.normalize_anatomy_map(atlas, permuted_reply)

    assert first["axial_levels"] != second["axial_levels"]
    assert first["axial_order_policy"] == "dicom_lps_z_record_only_no_semantic_relabel_v1"
    assert second["geometry_canonicalization"]["axial_levels"]["axial-group-06"][
        "physical_superior_to_inferior_tile_ids"
    ] == [
        "axial-series-a:0016",
        "axial-series-a:0017",
        "axial-series-a:0018",
    ]


def test_anatomy_gate_rejects_repeated_axial_patient_positions(tmp_path):
    atlas = _atlas_package(tmp_path)
    for page in atlas.evidence_audit["pages"]:
        for tile in page["tiles"]:
            if tile["role"] == "axial_t2" and tile["capture_frame"] in {1, 2, 3}:
                tile["mapping"]["position_lps"][2] = 100.0

    with pytest.raises(
        anatomy_cards.AnatomyCardError,
        match="repeated axial patient-space positions",
    ) as caught:
        anatomy_cards.normalize_anatomy_map(atlas, _anatomy_map())

    assert caught.value.code == "anatomy_map_duplicate_axial_position"


def test_screening_cards_preserve_complete_geometry_group_membership(tmp_path):
    """Gate 1-to-2 cards must carry whole groups, not silent three-slice rewrites."""
    atlas = _atlas_package(tmp_path)
    axial_page = next(
        page for page in atlas.evidence_audit["pages"]
        if page["role"] == "axial_t2"
    )
    extra = json.loads(json.dumps(axial_page["tiles"][-1]))
    extra.update({
        "tile_id": "axial-series-a:0019",
        "source_slice": 19,
        "capture_frame": 19,
        "geometry_group_id": "axial-group-06",
        "mapping": _mapping_record("axial_t2", 19),
    })
    axial_page["tiles"].append(extra)
    atlas.evidence_audit["measured_slabs"][-1] = [16, 19]
    atlas.evidence_audit["geometry_groups"]["axial"][-1]["axial_frames"] = [16, 19]

    reply = _anatomy_map()
    reply["axial_levels"][-1]["axial_frames"] = [16, 19]
    package = anatomy_cards.prepare_anatomy_cards(atlas, reply)
    disc = anatomy_cards.screening_package_for(package, "disc")
    metadata = disc.images[0].card_payload["anatomy_card"]
    axial_tiles = [
        tile for tile in disc.evidence_audit["pages"][0]["tiles"]
        if tile.get("geometry_group_id") == "axial-group-06"
    ]
    central_t2 = [
        tile for tile in disc.evidence_audit["pages"][0]["tiles"]
        if tile.get("geometry_group_id") == "sagittal-group-02"
        and tile.get("role") == "sagittal_t2"
    ]

    assert [tile["capture_frame"] for tile in axial_tiles] == [16, 17, 18, 19]
    assert [tile["source_slice"] for tile in central_t2] == [4, 5, 6, 7, 8]
    assert metadata["group_integrity"]["status"] == "validated"
    axial_contract = next(
        row for row in metadata["group_integrity"]["groups"]
        if row["group_id"] == "axial-group-06"
    )
    assert axial_contract == {
        "group_id": "axial-group-06",
        "series_role": "axial_t2",
        "member_kind": "capture_frame",
        "original_members": [16, 17, 18, 19],
        "current_members": [16, 17, 18, 19],
        "selection_kind": "complete_group",
        "status": "intact",
    }
