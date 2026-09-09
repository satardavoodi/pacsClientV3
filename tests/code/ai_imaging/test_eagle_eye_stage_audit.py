"""Regression guards for the stored Eagle Eye stage-image audit."""

from __future__ import annotations

import json
from pathlib import Path

from modules.ai_imaging.eagle_eye_lumbar.stage_audit import build_stage_audit


def _write_json(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def test_stage_audit_shows_screening_inputs_and_diagnostic_cards(tmp_path):
    atlas = tmp_path / ".evidence" / "screening" / "sagittal.png"
    anatomy_card = (
        tmp_path / ".evidence" / "anatomy-gate-v4" / "anatomy_01_disc.png"
    )
    card = tmp_path / ".evidence" / "cards" / "focus-01_L5_S1.png"
    atlas.parent.mkdir(parents=True)
    anatomy_card.parent.mkdir(parents=True)
    card.parent.mkdir(parents=True)
    atlas.write_bytes(b"atlas")
    anatomy_card.write_bytes(b"anatomy-card")
    card.write_bytes(b"card")

    atomic = tmp_path / ".atomic_analysis" / "stage1"
    _write_json(
        atomic / "anatomy_mapping_request.json",
        {
            "sent": {
                "image_count": 1,
                "images": [{
                    "file": ".evidence/screening/sagittal.png",
                    "caption": "Sagittal anatomy-mapping atlas",
                }],
            }
        },
    )
    _write_json(
        atomic / "anatomy_mapping_structured.json",
        {
            "stage": "anatomy_mapping",
            "parsed": True,
            "truncated": False,
            "data": {
                "sagittal_planes": {"sagittal_t2": {}, "sagittal_t1": {}},
                "axial_levels": [{"level": "L5-S1", "axial_frames": [21, 25]}],
            },
        },
    )
    _write_json(
        anatomy_card.parent / "anatomy_manifest.json",
        {
            "schema_version": "1.0.0",
            "cards": [{
                "image_index": 1,
                "request_key": "disc",
                "image_file": anatomy_card.name,
                "tile_count": 21,
            }],
        },
    )
    _write_json(
        atomic / "screening_disc_request.json",
        {
            "sent": {
                "image_count": 1,
                "images": [{
                    "file": ".evidence/anatomy-gate-v4/anatomy_01_disc.png",
                    "caption": "Disc anatomy card",
                }],
            }
        },
    )
    _write_json(
        atomic / "screening_disc_structured.json",
        {
            "stage": "screening_disc",
            "parsed": False,
            "truncated": True,
            "completion_tokens": 5996,
            "max_output_tokens": 6000,
            "data": None,
        },
    )
    _write_json(
        tmp_path / "llm_stage1_structured.json",
        {
            "parsed": True,
            "truncated": False,
            "data": {
                "level_map": [{
                    "level": "L5-S1", "axial_frames": [21, 25]
                }]
            },
        },
    )
    _write_json(
        tmp_path / ".evidence" / "cards" / "evidence_manifest.json",
        {
            "evidence_mode": "focused-v5-level-cards",
            "warnings": [],
            "budget": {"image_count": 1, "max_images": 8},
            "card_bindings": [{
                "image_index": 1,
                "focus_id": "focus-01",
                "subject_level": "L5-S1",
                "structure_group": "disc",
                "allowed_axial_frames": [22, 23, 24],
                "card_json_file": "focus-01_L5_S1.card.json",
            }],
        },
    )
    _write_json(
        tmp_path / ".evidence" / "cards" / "focus-01_L5_S1.card.json",
        {
            "image_index": 1,
            "image_file": "focus-01_L5_S1.png",
            "card_metadata": {
                "card_id": "focus-01",
                "subject_level": "L5-S1",
                "structure_group": "disc",
                "slots": [{
                    "slot": "axial_t2.max_abnormality_plane",
                    "capture_frame": 23,
                }],
            },
        },
    )
    _write_json(
        tmp_path / ".atomic_analysis" / "stage3" / "card_01_disc_request.json",
        {
            "sent": {
                "image_count": 1,
                "images": [{
                    "file": ".evidence/cards/focus-01_L5_S1.png",
                    "caption": "Diagnostic card",
                }],
            }
        },
    )
    _write_json(
        tmp_path / ".atomic_analysis" / "stage3" / "card_01_disc_structured.json",
        {
            "stage": "verification_disc",
            "parsed": True,
            "truncated": False,
            "data": {"verifications": []},
        },
    )

    audit = build_stage_audit(tmp_path)
    sections = {section.key: section for section in audit.sections}

    assert sections["anatomy_map"].status == "ready"
    assert "L5-S1" in sections["anatomy_map"].summary
    assert [item.path for item in sections["anatomy_map"].images] == [atlas.resolve()]
    assert sections["anatomy_cards"].status == "ready"
    assert [item.path for item in sections["anatomy_cards"].images] == [
        anatomy_card.resolve()
    ]
    screening = sections["screening_disc"]
    assert screening.status == "truncated"
    assert [item.path for item in screening.images] == [anatomy_card.resolve()]
    cards = sections["diagnostic_cards"]
    assert cards.status == "ready"
    assert [item.path for item in cards.images] == [card.resolve()]
    assert "frames 22, 23, 24" in cards.images[0].details
    verification = sections["diagnostic_model_input"]
    assert [item.path for item in verification.images] == [card.resolve()]
    assert "Atomic diagnostic requests: 1" in verification.summary
    assert "card_01_disc" in verification.images[0].details


def test_stage_audit_rejects_image_paths_outside_the_session(tmp_path):
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"outside")
    _write_json(
        tmp_path / ".atomic_analysis" / "stage1" / "screening_endplate_marrow_request.json",
        {
            "sent": {
                "images": [{"file": "../outside.png", "caption": "Outside"}]
            }
        },
    )
    _write_json(
        tmp_path / ".atomic_analysis" / "stage1" / "screening_endplate_marrow_structured.json",
        {"parsed": True, "truncated": False, "data": {"findings": []}},
    )

    audit = build_stage_audit(tmp_path)
    section = next(
        item for item in audit.sections if item.key == "screening_endplate_marrow"
    )

    assert section.images == ()


def test_stage_audit_keeps_historical_combined_screening_artifacts_readable(tmp_path):
    atomic = tmp_path / ".atomic_analysis" / "stage1"
    _write_json(
        atomic / "screening_foraminal_posterior_elements_request.json",
        {"sent": {"image_count": 0, "images": []}},
    )
    _write_json(
        atomic / "screening_foraminal_posterior_elements_structured.json",
        {"parsed": True, "truncated": False, "data": {"findings": []}},
    )

    sections = {item.key: item for item in build_stage_audit(tmp_path).sections}

    assert sections["screening_foraminal_posterior_elements"].status == "ready"
    assert "Historical screening" in sections[
        "screening_foraminal_posterior_elements"
    ].title
