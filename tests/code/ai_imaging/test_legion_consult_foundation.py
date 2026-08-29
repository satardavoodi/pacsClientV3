"""Guards for the first Legion Consult implementation slice.

These tests stay Qt-free. They protect the clinical selection contract before
the launcher and dialogs are allowed to depend on it.
"""

from __future__ import annotations

import json

import pytest

from modules.ai_imaging.eagle_eye_function_catalog import (
    FUNCTION_LEGION_CONSULT,
    FUNCTION_NATIVE_ANALYSIS,
    function_options_for_modality,
)
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import SeriesCandidate
from modules.ai_imaging.legion_consult.models import (
    AttentionAnchor,
    LegionConsultRequest,
)
from modules.ai_imaging.legion_consult.series_selection import (
    SelectionError,
    build_selection_plan,
    default_candidate_for_role,
    series_key,
)
from modules.ai_imaging.legion_consult.session_store import (
    save_configured_request,
    update_request_state,
)


def _series(
    number: int,
    description: str,
    *,
    uid: str = "",
    plane: str = "axial",
    slices: int = 20,
    te: float | None = None,
    tr: float | None = None,
) -> SeriesCandidate:
    return SeriesCandidate(
        index=number,
        series_uid=uid or f"1.2.840.{number}",
        series_number=number,
        series_description=description,
        modality="MR",
        plane=plane,
        slice_count=slices,
        echo_time=te,
        repetition_time=tr,
        series_path=f"series-{number}",
    )


def test_launcher_offers_native_and_legion_consult_for_supported_modalities():
    expected_native_labels = {
        "MG": "Mammography Analysis",
        "DX": "Bone Age Analysis",
        "MR": "Lumbar MRI Analysis",
    }

    for modality, native_label in expected_native_labels.items():
        options = function_options_for_modality(modality)
        assert [option.key for option in options] == [
            FUNCTION_NATIVE_ANALYSIS,
            FUNCTION_LEGION_CONSULT,
        ]
        assert options[0].label == native_label
        assert options[0].enabled is True
        assert options[1].label == "Legion Consult"
        assert options[1].enabled is (modality == "MR")


def test_default_t1_and_t2_prefer_the_source_plane_and_reuse_the_source_role():
    source = _series(10, "AX T2 FSE", plane="axial", te=95, tr=4000)
    axial_t1 = _series(11, "AX T1", plane="axial", te=12, tr=550)
    sagittal_t1 = _series(12, "SAG T1", plane="sagittal", te=12, tr=550)

    candidates = [source, axial_t1, sagittal_t1]

    assert default_candidate_for_role(candidates, "t2", source) is source
    assert default_candidate_for_role(candidates, "t1", source) is axial_t1


def test_selection_plan_always_contains_source_t1_t2_and_deduplicates_them():
    source_t2 = _series(20, "AX T2", te=100, tr=4200, slices=30)
    t1 = _series(21, "AX T1", te=10, tr=500, slices=28)
    flair = _series(22, "AX FLAIR", te=110, tr=9000, slices=28)

    plan = build_selection_plan(
        study_uid="study-1",
        candidates=[source_t2, t1, flair],
        source=source_t2,
        t1=t1,
        t2=source_t2,
        optional_keys=[series_key(flair)],
    )

    assert plan.source_series_key == series_key(source_t2)
    assert plan.t1_series_key == series_key(t1)
    assert plan.t2_series_key == series_key(source_t2)
    assert plan.selected_series_keys == (
        series_key(source_t2),
        series_key(t1),
        series_key(flair),
    )
    assert plan.estimated_image_count == 86


def test_select_all_includes_every_eligible_diagnostic_mr_series():
    source = _series(30, "AX T2", te=100, tr=4000)
    t1 = _series(31, "AX T1", te=10, tr=500)
    dwi = _series(32, "DWI B1000")
    localizer = _series(33, "3 PLANE LOCALIZER")

    plan = build_selection_plan(
        study_uid="study-2",
        candidates=[source, t1, dwi, localizer],
        source=source,
        t1=t1,
        t2=source,
        select_all=True,
    )

    assert plan.select_all is True
    assert series_key(dwi) in plan.selected_series_keys
    assert series_key(localizer) not in plan.selected_series_keys


@pytest.mark.parametrize("missing", ["source", "t1", "t2"])
def test_selection_plan_fails_closed_when_a_required_assignment_is_missing(missing):
    source = _series(40, "AX T2", te=100, tr=4000)
    t1 = _series(41, "AX T1", te=10, tr=500)
    values = {"source": source, "t1": t1, "t2": source}
    values[missing] = None

    with pytest.raises(SelectionError):
        build_selection_plan(
            study_uid="study-3",
            candidates=[source, t1],
            source=values["source"],
            t1=values["t1"],
            t2=values["t2"],
        )


def test_attention_anchor_expands_two_diagonal_points_into_four_lps_corners():
    anchor = AttentionAnchor.from_rectangle(
        source_series_key="uid:1.2.3",
        source_slice_index=7,
        diagonal_points=((30.0, 50.0), (10.0, 20.0)),
        image_to_patient=lambda x, y, k: (x * 0.5, y * 0.5, float(k)),
    )

    assert anchor.image_corners == (
        (10.0, 20.0),
        (30.0, 20.0),
        (30.0, 50.0),
        (10.0, 50.0),
    )
    assert anchor.patient_lps_corners == (
        (5.0, 10.0, 7.0),
        (15.0, 10.0, 7.0),
        (15.0, 25.0, 7.0),
        (5.0, 25.0, 7.0),
    )


def test_configured_request_is_written_atomically_and_records_no_remote_send(tmp_path):
    source = _series(50, "AX T2", te=100, tr=4000)
    t1 = _series(51, "AX T1", te=10, tr=500)
    plan = build_selection_plan(
        study_uid="study-4",
        candidates=[source, t1],
        source=source,
        t1=t1,
        t2=source,
    )
    anchor = AttentionAnchor.from_rectangle(
        source_series_key=series_key(source),
        source_slice_index=3,
        diagonal_points=((1.0, 2.0), (5.0, 8.0)),
        image_to_patient=lambda x, y, k: (x, y, float(k)),
    )
    request = LegionConsultRequest.create(plan=plan, anchor=anchor)

    path = save_configured_request(request, root=tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["status"] == "configured"
    assert payload["remote_send_status"] == "not_sent"
    assert payload["slice_padding"] == 5
    assert payload["selection"]["study_uid"] == "study-4"
    assert not list(path.parent.glob("*.tmp"))

    update_request_state(
        path,
        status="analyzing",
        remote_send_status="pending",
    )
    updated = json.loads(path.read_text(encoding="utf-8"))
    assert updated["status"] == "analyzing"
    assert updated["remote_send_status"] == "pending"
    assert updated["attention_anchor"] == payload["attention_anchor"]
    assert not list(path.parent.glob("*.tmp"))
