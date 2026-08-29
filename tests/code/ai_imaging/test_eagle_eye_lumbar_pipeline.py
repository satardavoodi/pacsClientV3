"""Guards for the Eagle Eye lumbar MRI capture pipeline (stage 1).

What is being protected here, in the order the pipeline runs:

  1. PLANE comes from ImageOrientationPatient, never from a description. A
     coronal T2 must never be accepted as the "Sagittal T2".
  2. CAPTURE ORDER is anatomical and its direction is recorded explicitly.
     `InstanceNumber == 1` is NOT assumed to mean right (or superior) - the
     same stack fed in reversed order must still sweep right-to-left.
  3. SAG T2 <-> T1 MATCHING is by physical position, so it survives the two
     series having different slice counts and spacing.
  4. SELECTION never silently picks an arbitrary series: a slot that cannot be
     resolved stays unresolved and every runner-up is recorded with its score.
  5. SESSION manifests and the files on disk agree - gapless 1..N indices, no
     orphan images, no manifest entry without a file.

Everything here is headless: no Qt, no VTK, no DICOM files. The Qt-side sweep
controller is source-pinned rather than imported, so this file stays fast and
runnable in CI.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging import eagle_eye_modes as modes                    # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import constants as C             # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import geometry as geo            # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import lock_sync as ls            # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import protocols as protos        # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import reference_lines as reflines  # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import session_store as store     # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import (        # noqa: E402
    SeriesCandidate,
    classify_lumbar_series,
    resolve_weighting,
    score_candidate,
)

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------

IOP_AXIAL = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
IOP_SAGITTAL = [0.0, 1.0, 0.0, 0.0, 0.0, -1.0]
IOP_CORONAL = [1.0, 0.0, 0.0, 0.0, 0.0, -1.0]
IOP_OBLIQUE = [0.0, 1.0, 0.0, -0.7071, 0.0, -0.7071]


def _instance(iop, ipp, sop, number=1, rows=256, cols=256, spacing=(1.0, 1.0)):
    return {
        "image_orientation_patient": list(iop),
        "image_position_patient": list(ipp),
        "pixel_spacing": list(spacing),
        "rows": rows,
        "columns": cols,
        "sop_uid": sop,
        "instance_number": number,
        "instance_path": f"/fake/{sop}.dcm",
    }


def sagittal_stack(count=9, first_x=-20.0, step=5.0, prefix="sag"):
    """Sagittal slices marching from patient RIGHT (-x) to LEFT (+x)."""
    return [
        _instance(IOP_SAGITTAL, [first_x + k * step, -50.0, 60.0], f"{prefix}.{k}", k + 1)
        for k in range(count)
    ]


def axial_stack(count=12, first_z=40.0, step=-4.0, prefix="ax"):
    """Axial slices marching from SUPERIOR (+z) downwards."""
    return [
        _instance(IOP_AXIAL, [-100.0, -100.0, first_z + k * step], f"{prefix}.{k}", k + 1)
        for k in range(count)
    ]


# ---------------------------------------------------------------------------
# 1. Plane classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("iop,expected", [
    (IOP_AXIAL, C.PLANE_AXIAL),
    (IOP_SAGITTAL, C.PLANE_SAGITTAL),
    (IOP_CORONAL, C.PLANE_CORONAL),
    (IOP_OBLIQUE, C.PLANE_OBLIQUE),
    (None, C.PLANE_UNKNOWN),
    ([0, 0, 0, 0, 0, 0], C.PLANE_UNKNOWN),
    (["a", "b"], C.PLANE_UNKNOWN),
])
def test_plane_comes_from_orientation_not_text(iop, expected):
    assert geo.classify_plane(iop) == expected


def test_disc_angled_axial_is_still_axial():
    """A lumbar axial angled to a disc space (~15 deg) must stay 'axial'."""
    import math
    a = math.radians(15.0)
    iop = [1.0, 0.0, 0.0, 0.0, math.cos(a), -math.sin(a)]
    assert geo.classify_plane(iop) == C.PLANE_AXIAL


def test_series_plane_skips_instances_without_geometry():
    instances = [{"sop_uid": "x"}, _instance(IOP_SAGITTAL, [0, 0, 0], "y")]
    assert geo.series_plane(instances) == C.PLANE_SAGITTAL
    assert geo.series_plane([]) == C.PLANE_UNKNOWN


# ---------------------------------------------------------------------------
# 2. Capture ordering
# ---------------------------------------------------------------------------

def test_sagittal_order_runs_right_to_left_and_says_so():
    order = geo.build_capture_order(sagittal_stack(), C.PLANE_SAGITTAL)
    assert order.direction == C.ORDER_RIGHT_TO_LEFT
    assert order.from_geometry is True
    assert order.indices == list(range(9))
    # positions must increase along +x (right -> left)
    assert order.positions_mm == sorted(order.positions_mm)


def test_instance_number_one_is_not_assumed_to_be_the_right_side():
    """The SAME anatomy stored in reverse order must sweep the same way."""
    forward = sagittal_stack()
    backward = list(reversed(forward))

    order_f = geo.build_capture_order(forward, C.PLANE_SAGITTAL)
    order_b = geo.build_capture_order(backward, C.PLANE_SAGITTAL)

    assert order_f.direction == order_b.direction == C.ORDER_RIGHT_TO_LEFT
    # Different index permutations...
    assert order_f.indices != order_b.indices
    # ...but the same anatomical sequence of slices.
    assert [forward[k]["sop_uid"] for k in order_f.indices] == \
           [backward[k]["sop_uid"] for k in order_b.indices]


def test_axial_order_runs_superior_to_inferior():
    order = geo.build_capture_order(axial_stack(), C.PLANE_AXIAL)
    assert order.direction == C.ORDER_SUPERIOR_TO_INFERIOR
    assert order.positions_mm[0] > order.positions_mm[-1]
    assert len(order) == 12


def test_order_without_positions_falls_back_and_admits_it():
    """No IPP -> stack order, direction 'unknown'. It must not claim a side."""
    instances = [{"image_orientation_patient": IOP_SAGITTAL, "sop_uid": f"s{k}"} for k in range(5)]
    order = geo.build_capture_order(instances, C.PLANE_SAGITTAL)
    assert order.direction == C.ORDER_UNKNOWN
    assert order.from_geometry is False
    assert order.indices == [0, 1, 2, 3, 4]


def test_empty_stack_is_not_an_error():
    order = geo.build_capture_order([], C.PLANE_SAGITTAL)
    assert len(order) == 0
    assert order.direction == C.ORDER_UNKNOWN


def test_capture_order_serialises_direction_for_the_manifest():
    payload = geo.build_capture_order(axial_stack(), C.PLANE_AXIAL).as_dict()
    assert payload["direction"] == C.ORDER_SUPERIOR_TO_INFERIOR
    assert payload["slice_count"] == 12
    assert payload["from_geometry"] is True


# ---------------------------------------------------------------------------
# 3. Sagittal T2 <-> T1 matching
# ---------------------------------------------------------------------------

def test_t1_match_is_physical_not_index_based():
    """T2 has 9 slices at 5 mm; T1 has 5 slices at 10 mm over the same span."""
    t2 = sagittal_stack(count=9, first_x=-20.0, step=5.0, prefix="t2")
    t1 = sagittal_stack(count=5, first_x=-20.0, step=10.0, prefix="t1")

    # T2 index 0 (x=-20) -> T1 index 0 (x=-20)
    assert geo.match_slice_across_series(t2, 0, t1).index == 0
    # T2 index 4 (x=0) -> T1 index 2 (x=0), NOT index 4
    match_mid = geo.match_slice_across_series(t2, 4, t1)
    assert match_mid.index == 2
    assert match_mid.matched is True
    assert match_mid.distance_mm < 1e-6
    # T2 index 8 (x=+20) -> last T1 slice
    assert geo.match_slice_across_series(t2, 8, t1).index == 4


def test_t1_match_flags_a_weak_correspondence():
    """A T1 stack covering a different level is still shown, but flagged."""
    t2 = sagittal_stack(count=5, first_x=0.0, step=5.0, prefix="t2")
    t1 = sagittal_stack(count=5, first_x=200.0, step=5.0, prefix="t1")
    match = geo.match_slice_across_series(t2, 0, t1, max_distance_mm=12.0)
    assert match.matched is False
    assert match.distance_mm > 100.0


def test_match_survives_missing_or_broken_input():
    t2 = sagittal_stack(count=3)
    assert geo.match_slice_across_series(t2, 0, []).matched is False
    assert geo.match_slice_across_series([], 0, t2).matched is False
    assert geo.match_slice_across_series(t2, 99, t2).matched is False
    no_geometry = [{"sop_uid": "a"}, {"sop_uid": "b"}]
    assert geo.match_slice_across_series(t2, 0, no_geometry).matched is False


# ---------------------------------------------------------------------------
# 4. Spatial context labels
# ---------------------------------------------------------------------------

def test_sagittal_context_names_side_and_region():
    assert geo.sagittal_context(0.0, 0.0)["region"] == "central_canal"
    assert geo.sagittal_context(0.0, 0.0)["side"] == "midline"

    right = geo.sagittal_context(-16.0, 0.0)
    assert right["side"] == "right"
    assert right["region"] == "neural_foraminal"

    left = geo.sagittal_context(9.0, 0.0)
    assert left["side"] == "left"
    assert left["region"] == "paracentral_lateral_recess"

    far = geo.sagittal_context(40.0, 0.0)
    assert far["region"] == "extraforaminal"

    unknown = geo.sagittal_context(None, 0.0)
    assert unknown["side"] == "unknown" and unknown["offset_mm"] is None


def test_midline_estimated_from_the_axial_field_of_view():
    axial = axial_stack(count=3)
    midline = geo.estimate_midline_x(axial, sagittal_stack())
    # FOV centre = IPP.x + (cols/2)*spacing = -100 + 128 = 28
    assert midline == pytest.approx(28.0, abs=1e-6)


def test_midline_falls_back_to_the_sagittal_span():
    sag = sagittal_stack(count=9, first_x=-20.0, step=5.0)
    assert geo.estimate_midline_x([], sag) == pytest.approx(0.0)
    assert geo.estimate_midline_x([], []) is None


def test_axial_context_reports_depth_below_the_top_slice():
    positions = [40.0, 36.0, 32.0]
    assert geo.axial_context(32.0, positions)["mm_below_top"] == pytest.approx(8.0)
    assert geo.axial_context(None, positions)["z_lps"] is None


# ---------------------------------------------------------------------------
# 5. Series classification
# ---------------------------------------------------------------------------

def _series(index, desc, plane, **kw):
    kw.setdefault("modality", "MR")
    kw.setdefault("slice_count", 15 if plane == C.PLANE_SAGITTAL else 20)
    kw.setdefault("thumbnail_index", index)
    kw.setdefault("series_number", index + 1)
    kw.setdefault("series_uid", f"1.2.3.{index + 1}")
    return SeriesCandidate(index=index, series_description=desc, plane=plane, **kw)


def lumbar_study():
    """A realistic lumbar protocol, including the traps."""
    return [
        _series(0, "LOCALIZER", C.PLANE_SAGITTAL, slice_count=3),
        _series(1, "SAG T2 TSE LUMBAR", C.PLANE_SAGITTAL, echo_time=100.0, repetition_time=3500.0),
        _series(2, "SAG T1 TSE LUMBAR", C.PLANE_SAGITTAL, echo_time=10.0, repetition_time=600.0),
        _series(3, "SAG STIR LUMBAR", C.PLANE_SAGITTAL, echo_time=60.0, inversion_time=150.0),
        _series(4, "AX T2 TSE LUMBAR", C.PLANE_AXIAL, echo_time=110.0, repetition_time=4000.0),
        _series(5, "COR T2 TSE", C.PLANE_CORONAL, echo_time=100.0, repetition_time=3500.0),
    ]


def test_the_three_slots_resolve_to_the_right_series():
    selection = classify_lumbar_series(lumbar_study())
    assert selection.resolved is True
    assert selection.candidate_for(C.SLOT_SAG_T2).series_description == "SAG T2 TSE LUMBAR"
    assert selection.candidate_for(C.SLOT_SAG_T1).series_description == "SAG T1 TSE LUMBAR"
    assert selection.candidate_for(C.SLOT_AX_T2).series_description == "AX T2 TSE LUMBAR"
    assert selection.uncertain_slots == []


def test_no_series_is_used_for_two_slots():
    selection = classify_lumbar_series(lumbar_study())
    chosen = [selection.candidate_for(slot).index for slot in C.SLOT_ORDER]
    assert len(set(chosen)) == 3


def test_a_coronal_t2_never_fills_the_sagittal_t2_slot():
    coronal = _series(0, "COR T2 TSE LUMBAR", C.PLANE_CORONAL, echo_time=100.0)
    result = score_candidate(coronal, C.SLOT_SAG_T2)
    assert result.rejected and "plane" in result.rejected

    selection = classify_lumbar_series([coronal])
    assert selection.candidate_for(C.SLOT_SAG_T2) is None
    assert selection.slots[C.SLOT_SAG_T2].uncertain is True


def test_a_localizer_is_never_selected():
    selection = classify_lumbar_series(lumbar_study())
    for slot in C.SLOT_ORDER:
        chosen = selection.candidate_for(slot)
        assert chosen is None or "LOCALIZER" not in chosen.series_description
    rejected = selection.slots[C.SLOT_SAG_T2].rejected
    assert any("non-diagnostic" in entry["reason"] for entry in rejected)


def test_stir_is_not_mistaken_for_t2():
    stir = _series(0, "SAG STIR", C.PLANE_SAGITTAL, echo_time=60.0, inversion_time=150.0)
    t2 = _series(1, "SAG T2 TSE", C.PLANE_SAGITTAL, echo_time=100.0, repetition_time=3500.0)
    selection = classify_lumbar_series([stir, t2])
    assert selection.candidate_for(C.SLOT_SAG_T2).series_description == "SAG T2 TSE"


def test_echo_time_overrules_a_mislabelled_description():
    """A series called 'SAG T2' whose TE says T1 is treated as T1."""
    mislabelled = _series(0, "SAG T2 TSE", C.PLANE_SAGITTAL, echo_time=9.0, repetition_time=500.0)
    evidence = resolve_weighting(mislabelled)
    assert evidence["weighting"] == "t1"
    assert evidence["conflict"] is True
    assert evidence["source"] == "timings_over_text"


def test_proton_density_is_not_called_t1():
    pd = _series(0, "SAG PD TSE", C.PLANE_SAGITTAL, echo_time=15.0, repetition_time=3000.0)
    assert resolve_weighting(pd)["weighting"] == "pd"


def test_an_unresolvable_slot_stays_unresolved_and_explains_itself():
    """Nothing sagittal in the study: the slot must NOT borrow an axial."""
    selection = classify_lumbar_series([
        _series(0, "AX T2 TSE", C.PLANE_AXIAL, echo_time=110.0, repetition_time=4000.0),
    ])
    sag = selection.slots[C.SLOT_SAG_T2]
    assert sag.chosen is None
    assert sag.uncertain is True
    assert sag.reasons, "an unresolved slot must say why"
    assert selection.resolved is False
    assert C.SLOT_SAG_T2 in selection.uncertain_slots


def test_alternatives_and_scores_are_recorded_for_later_tuning():
    selection = classify_lumbar_series(lumbar_study())
    payload = selection.as_dict()
    slot = payload["slots"][C.SLOT_SAG_T2]
    assert slot["selected"]["series_description"] == "SAG T2 TSE LUMBAR"
    assert slot["confidence"] in (C.CONFIDENCE_HIGH, C.CONFIDENCE_MEDIUM)
    assert slot["score"] > 0
    assert isinstance(slot["alternatives"], list)
    assert isinstance(slot["rejected"], list)
    assert all("reason" in entry for entry in slot["rejected"])


def test_non_mr_series_are_gated_out():
    ct = _series(0, "SAG T2", C.PLANE_SAGITTAL, modality="CT", echo_time=100.0)
    assert "not MR" in (score_candidate(ct, C.SLOT_SAG_T2).rejected or "")


def test_a_series_without_geometry_is_penalised():
    with_geo = _series(0, "SAG T2 TSE", C.PLANE_SAGITTAL, echo_time=100.0,
                       instances=sagittal_stack(count=5))
    without = _series(1, "SAG T2 TSE", C.PLANE_SAGITTAL, echo_time=100.0,
                      instances=[{"sop_uid": "a"}])
    assert score_candidate(with_geo, C.SLOT_SAG_T2).score > \
           score_candidate(without, C.SLOT_SAG_T2).score


def test_classifier_tolerates_an_empty_study():
    selection = classify_lumbar_series([])
    assert selection.resolved is False
    assert set(selection.uncertain_slots) == set(C.SLOT_ORDER)


# ---------------------------------------------------------------------------
# 6. Eagle Eye mode resolution
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("MG", modes.MODE_MAMMOGRAPHY),
    ("mammography", modes.MODE_MAMMOGRAPHY),
    ("DX", modes.MODE_BONE_AGE),
    ("bone-age", modes.MODE_BONE_AGE),
    ("lumbar_mri", modes.MODE_LUMBAR_MRI),
    ("lumbar", modes.MODE_LUMBAR_MRI),
    ("", None),
    (None, None),
    ("nonsense", None),
])
def test_mode_normalisation_is_stable(value, expected):
    assert modes.normalize_eagle_eye_mode(value) == expected


def test_the_three_delegating_copies_agree_with_the_authority():
    """ai_mainwindow / imaging_tab / patient_widget must not drift again."""
    from modules.ai_imaging.ai_module_ui.ai_mainwindow import normalize_eagle_eye_mode as a
    from modules.ai_imaging.ai_module_ui.service_tab.imaging_tab import normalize_eagle_eye_mode as b
    from modules.ai_imaging.ai_module_ui.overrides.patient_widget import _normalize_eagle_eye_mode as c
    for value in ("MG", "DX", "lumbar_mri", "breast", "boneage", "", None, "junk"):
        expected = modes.normalize_eagle_eye_mode(value)
        assert a(value) == expected
        assert b(value) == expected
        assert c(value) == expected


@pytest.mark.parametrize("text", [
    "MRI LUMBAR SPINE", "L-SPINE MR", "LSPINE", "MR LUMBOSACRAL SPINE", "SAG T2 LUMBAR",
])
def test_lumbar_studies_are_recognised(text):
    assert modes.looks_like_lumbar(text) is True


@pytest.mark.parametrize("text", [
    "MRI CERVICAL SPINE", "MR BRAIN", "MRI KNEE RIGHT", "C-SPINE MR", "MRI THORACIC SPINE", "",
])
def test_other_regions_are_not_opened_in_the_lumbar_layout(text):
    assert modes.looks_like_lumbar(text) is False


def test_resolve_mode_keeps_mg_and_dx_unconditional():
    assert modes.resolve_eagle_eye_mode("MG", []) == modes.MODE_MAMMOGRAPHY
    assert modes.resolve_eagle_eye_mode("DX", []) == modes.MODE_BONE_AGE
    assert modes.resolve_eagle_eye_mode("MR", ["MRI LUMBAR SPINE"]) == modes.MODE_LUMBAR_MRI
    assert modes.resolve_eagle_eye_mode("MR", ["MRI BRAIN"]) is None
    assert modes.resolve_eagle_eye_mode("CT", ["LUMBAR"]) is None


# ---------------------------------------------------------------------------
# 7. Session store and manifests
# ---------------------------------------------------------------------------

def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")


def _populated_session(tmp_path, sagittal=3, axial=4):
    session = store.create_session("1.2.826.0.1.99", root=tmp_path)
    session.set_study_context(patient_id="P1", study_date="20260101", region="lumbar_spine")
    session.set_selection({"resolved": True, "slots": {}})
    session.set_pass_geometry(store.PASS_SAGITTAL, {"direction": C.ORDER_RIGHT_TO_LEFT})
    session.set_pass_geometry(store.PASS_AXIAL, {"direction": C.ORDER_SUPERIOR_TO_INFERIOR})
    for k in range(sagittal):
        _write_png(session.next_capture_path(store.PASS_SAGITTAL))
        session.add_capture(store.PASS_SAGITTAL, {"t2_sagittal_instance": f"t2.{k}"})
    for k in range(axial):
        _write_png(session.next_capture_path(store.PASS_AXIAL))
        session.add_capture(store.PASS_AXIAL, {"axial_instance": f"ax.{k}"})
    return session


def test_session_layout_matches_the_specified_folder_shape(tmp_path):
    session = _populated_session(tmp_path)
    session.write()

    assert (session.path / C.SESSION_JSON).is_file()
    assert (session.path / C.SAGITTAL_DIR / C.MANIFEST_JSON).is_file()
    assert (session.path / C.AXIAL_DIR / C.MANIFEST_JSON).is_file()
    assert (session.path / C.SAGITTAL_DIR / "sagittal_001.png").is_file()
    assert (session.path / C.AXIAL_DIR / "axial_004.png").is_file()
    # session folder lives under <root>/<StudyUID>/<session_id>
    assert session.path.parent.name == "1.2.826.0.1.99"


def test_capture_indices_are_gapless_and_zero_padded(tmp_path):
    session = _populated_session(tmp_path, sagittal=12)
    names = [record["image"] for record in session.captures(store.PASS_SAGITTAL)]
    assert names[0] == "sagittal_001.png"
    assert names[-1] == "sagittal_012.png"
    assert [record["index"] for record in session.captures(store.PASS_SAGITTAL)] == list(range(1, 13))


def test_manifest_records_direction_source_uids_and_counts(tmp_path):
    session = _populated_session(tmp_path)
    session.write()

    manifest = json.loads((session.path / C.SAGITTAL_DIR / C.MANIFEST_JSON).read_text(encoding="utf-8"))
    assert manifest["session_type"] == C.SESSION_TYPE_SAGITTAL
    assert manifest["capture_order"]["direction"] == C.ORDER_RIGHT_TO_LEFT
    assert manifest["capture_count"] == len(manifest["captures"]) == 3
    assert manifest["captures"][0]["t2_sagittal_instance"] == "t2.0"
    assert manifest["layout"]["columns"] == 3
    assert [v["slot"] for v in manifest["layout"]["viewports"]] == list(C.SLOT_ORDER)


def test_session_json_carries_the_study_and_version_context(tmp_path):
    session = _populated_session(tmp_path)
    session.write()

    doc = json.loads((session.path / C.SESSION_JSON).read_text(encoding="utf-8"))
    assert doc["session_kind"] == "lumbar_mri"
    assert doc["study_instance_uid"] == "1.2.826.0.1.99"
    assert doc["eagle_eye_version"] == C.EAGLE_EYE_LUMBAR_VERSION
    assert doc["patient_id"] == "P1"
    assert doc["passes"]["sagittal"]["capture_count"] == 3
    assert doc["passes"]["axial"]["capture_count"] == 4
    assert doc["created_at"] and doc["completed_at"]


def test_validate_is_clean_when_disk_and_manifest_agree(tmp_path):
    session = _populated_session(tmp_path)
    session.write()
    assert session.validate() == []


def test_validate_catches_a_missing_image(tmp_path):
    session = _populated_session(tmp_path)
    (session.path / C.SAGITTAL_DIR / "sagittal_002.png").unlink()
    problems = session.validate()
    assert any("sagittal_002.png" in p and "missing" in p for p in problems)


def test_validate_catches_an_orphan_image(tmp_path):
    session = _populated_session(tmp_path)
    _write_png(session.path / C.AXIAL_DIR / "axial_099.png")
    problems = session.validate()
    assert any("not in the manifest" in p for p in problems)


def test_two_sessions_for_one_study_do_not_collide(tmp_path):
    a = store.create_session("1.2.3", root=tmp_path, session_id="20260101T000000Z")
    b = store.create_session("1.2.3", root=tmp_path, session_id="20260101T000000Z")
    assert a.path != b.path
    assert a.path.parent == b.path.parent


def test_a_malformed_study_uid_cannot_escape_the_session_root(tmp_path):
    session = store.create_session("../../etc/passwd", root=tmp_path)
    assert tmp_path in session.path.parents
    assert ".." not in session.path.parts


def test_session_root_defaults_under_user_data_ai():
    root = store.default_session_root()
    assert root.name == "eagle_eye"
    assert root.parent.name == "ai"


# ---------------------------------------------------------------------------
# 8. Capture controller wiring (source-pinned - importing it needs Qt)
# ---------------------------------------------------------------------------

CONTROLLER_SRC = (REPO_ROOT / "modules" / "ai_imaging" / "eagle_eye_lumbar"
                  / "capture_controller.py").read_text(encoding="utf-8")


def test_controller_captures_the_whole_layout_not_one_pane():
    """The frame must be the 3-panel container, never a single viewport."""
    assert "grab_widget_pixmap" in CONTROLLER_SRC
    assert "self.capture_widget" in CONTROLLER_SRC


def test_controller_runs_the_protocols_sessions_in_order():
    """One loop over protocol.sessions, not two hardcoded passes.

    The moment this becomes `if sagittal: ... else: ...` again, adding Brain
    MRI means editing the engine instead of adding a configuration.
    """
    assert "self._begin_session(0)" in CONTROLLER_SRC
    assert "self.sessions[index]" in CONTROLLER_SRC
    assert "nxt < len(self.sessions)" in CONTROLLER_SRC
    assert "_position_sagittal_frame" not in CONTROLLER_SRC
    assert "_position_axial_frame" not in CONTROLLER_SRC


def test_controller_refuses_to_start_without_all_three_series():
    assert "no series resolved for" in CONTROLLER_SRC


def test_controller_never_blocks_the_event_loop():
    """One frame per timer tick: no worker thread, no inline sweep loop.

    Checked against the parsed AST rather than the raw text, so the prose in
    the module docstring (which explains WHY there is no QThread) cannot make
    this guard pass or fail for the wrong reason.
    """
    import ast
    tree = ast.parse(CONTROLLER_SRC)

    assert "QTimer.singleShot" in CONTROLLER_SRC

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert "QThread" not in imported, "the sweep must stay on the GUI thread"

    loops = [n for n in ast.walk(tree) if isinstance(n, (ast.While, ast.AsyncFor))]
    assert not loops, "a blocking sweep loop would freeze the workstation"


def test_controller_uses_the_shared_geometry_authority():
    """Instances must come from _geometry_instances_for_viewer, not metadata."""
    assert "_geometry_instances_for_viewer" in CONTROLLER_SRC


def test_controller_refreshes_reference_lines_before_each_capture():
    assert "manage_reference_line" in CONTROLLER_SRC
    assert "_refresh_reference_lines" in CONTROLLER_SRC


def test_controller_validates_the_session_before_reporting_success():
    assert "self.session.validate()" in CONTROLLER_SRC


def test_stage_one_does_not_touch_an_llm():
    """Milestone 1 stops at the images: no upload, no model call."""
    forbidden = ("openai", "OpenAI", "anthropic", "requests.post", "upload_", "chat/completions")
    for token in forbidden:
        assert token not in CONTROLLER_SRC, f"stage 1 must not reference {token!r}"


# ---------------------------------------------------------------------------
# 8a. Lock Sync: the workstation's, borrowed and handed back
# ---------------------------------------------------------------------------
#
# The requirement is that the two sagittal stacks scroll together during the
# sagittal pass, using the Lock Sync the reader already has rather than a
# second synchroniser living inside Eagle Eye. `lock_sync.py` is pure Python
# (its one Qt-adjacent import is lazy), so these are real behaviour tests
# against a fake widget, not source pins.


class _FakeSyncManager:
    def __init__(self):
        self.mode = None

    def set_mode(self, mode):
        self.mode = mode


class _FakePatientWidget:
    """Just enough PatientWidget to exercise the enable/restore contract."""

    def __init__(self, lock_sync=False, sync_point=False):
        self._lock_sync_enabled = bool(lock_sync)
        self._sync_enabled = bool(sync_point)
        self.target_mode_enabled = bool(sync_point)
        self._lock_sync_updating = False
        self.sync_manager = _FakeSyncManager()
        self.calls = []

    def _register_sync_viewers_pipeline_only(self):
        self.calls.append("register_pipeline_only")

    def set_lock_sync(self, enabled):
        self.calls.append(f"set_lock_sync({bool(enabled)})")
        self._lock_sync_enabled = bool(enabled)

    def toggle_sync_point(self, enabled):
        self.calls.append(f"toggle_sync_point({bool(enabled)})")
        self._sync_enabled = bool(enabled)
        self.target_mode_enabled = bool(enabled)


def test_lock_sync_turns_on_for_the_session():
    pw = _FakePatientWidget()
    session = ls.LockSyncSession(pw)

    assert session.enable() is True
    assert session.active is True
    assert pw._lock_sync_enabled is True
    assert pw._sync_enabled is True


def test_lock_sync_uses_the_pipeline_only_registration_like_the_toolbar():
    """Eagle Eye must not install the click-to-target interactor or red cursor.

    `_register_sync_viewers_pipeline_only` is what the toolbar calls for Lock
    Sync precisely because it leaves the interactor styles alone, so the other
    tools keep working. Registering the full click-to-target path instead would
    also bake a red target dot into every screenshot.
    """
    pw = _FakePatientWidget()
    ls.LockSyncSession(pw).enable()

    assert "register_pipeline_only" in pw.calls
    assert pw.calls.index("register_pipeline_only") < pw.calls.index("set_lock_sync(True)")


def test_lock_sync_restores_an_off_state():
    """The reader had it off: they get it back off, pipeline torn down."""
    pw = _FakePatientWidget(lock_sync=False, sync_point=False)
    session = ls.LockSyncSession(pw)
    session.enable()
    session.restore()

    assert pw._lock_sync_enabled is False
    assert pw._sync_enabled is False
    assert session.active is False
    # set_lock_sync(False) must precede the teardown, or toggle_sync_point
    # takes its keep-the-pipeline-alive branch and leaves sync half-running.
    assert pw.calls.index("set_lock_sync(False)") < pw.calls.index("toggle_sync_point(False)")


def test_lock_sync_restores_an_on_state_without_tearing_it_down():
    """The reader already had Lock Sync on: leave it on, touch nothing else."""
    pw = _FakePatientWidget(lock_sync=True, sync_point=True)
    session = ls.LockSyncSession(pw)
    session.enable()
    session.restore()

    assert pw._lock_sync_enabled is True
    assert "toggle_sync_point(False)" not in pw.calls


def test_lock_sync_restore_is_idempotent():
    pw = _FakePatientWidget()
    session = ls.LockSyncSession(pw)
    session.enable()
    session.restore()
    before = list(pw.calls)
    session.restore()
    assert pw.calls == before


def test_lock_sync_suspension_holds_the_engines_own_reentrancy_flag():
    """Suspension must reuse `_lock_sync_updating`, not invent a second flag.

    That flag is what `_auto_sync_on_slice_change` already checks before
    running, so holding it is how a controller-driven move is kept from
    cascading — the parked sagittals during the axial pass depend on it.
    """
    pw = _FakePatientWidget()
    session = ls.LockSyncSession(pw)
    session.enable()

    assert pw._lock_sync_updating is False
    with session.suspended():
        assert pw._lock_sync_updating is True
    assert pw._lock_sync_updating is False


def test_lock_sync_suspension_restores_a_flag_that_was_already_held():
    pw = _FakePatientWidget()
    session = ls.LockSyncSession(pw)
    session.enable()
    pw._lock_sync_updating = True

    with session.suspended():
        assert pw._lock_sync_updating is True
    assert pw._lock_sync_updating is True, "an outer hold must survive the inner one"


def test_lock_sync_degrades_instead_of_failing_on_a_viewer_without_it():
    """No Lock Sync support is a downgrade, never a dead sweep."""

    class _Bare:
        pass

    session = ls.LockSyncSession(_Bare())
    assert session.enable() is False
    assert session.active is False
    assert "Lock Sync" in session.detail
    # And suspension must still be a no-op context rather than an AttributeError.
    with session.suspended():
        pass


def test_lock_sync_records_the_geometric_basis_for_the_manifest():
    pw = _FakePatientWidget()
    session = ls.LockSyncSession(pw)
    session.enable()
    payload = session.as_dict()

    assert payload["enabled"] is True
    assert payload["mechanism"] == "workstation_lock_sync"
    assert payload["correspondence"] == "dicom_ipp_iop"
    assert payload["previous"]["lock_sync"] is False


@pytest.mark.parametrize("active,landed,expected", [
    (True, True, "lock_sync"),
    (True, False, "lock_sync_corrected"),
    (False, True, "controller"),
    (False, False, "controller"),
])
def test_follower_source_names_how_the_pane_got_there(active, landed, expected):
    """A manifest reader must be able to tell sync from correction."""
    assert ls.follower_source(active, landed) == expected


def test_controller_enables_lock_sync_before_the_first_sweep():
    """ON when the layout is ready, not before the panes carry their series."""
    assert "self.lock_sync = LockSyncSession(patient_widget)" in CONTROLLER_SRC
    enable_at = CONTROLLER_SRC.index("self._enable_lock_sync()")
    sweep_at = CONTROLLER_SRC.index("self._begin_session(0)")
    assert enable_at < sweep_at


def test_lock_sync_stays_on_after_a_successful_run():
    """The Eagle Eye SESSION is the layout on screen, not the sweep.

    Restoring at the end of the sweep is what left the reader looking at Sag T2
    on 5/9 and Sag T1 on 9/9 with nothing following (2026-08-26). The panes have
    to keep moving together while the reader scrolls back through them, so a
    successful `_finish` must NOT restore.
    """
    context_at = CONTROLLER_SRC.index("self.session.set_study_context(lock_sync=")
    write_at = CONTROLLER_SRC.index("self.session.write()", context_at)
    assert "self._restore_lock_sync()" not in CONTROLLER_SRC[context_at:write_at], \
        "a successful run must leave Lock Sync on for review"
    assert "Lock Sync left ON for review" in CONTROLLER_SRC


def test_a_failed_run_still_restores_lock_sync():
    """A run that died must not leave behind a setting nobody asked for."""
    fail_at = CONTROLLER_SRC.index("def _fail")
    restore_in_fail = CONTROLLER_SRC.index("self._restore_lock_sync()", fail_at)
    emit_at = CONTROLLER_SRC.index("self.failed.emit(reason)")
    assert restore_in_fail < emit_at, "restore before anything that can throw"


def test_controller_does_not_let_lock_sync_move_the_parked_panes():
    """A parked-reference sweep drives quietly, or the parked panes walk away."""
    frame_at = CONTROLLER_SRC.index("def _position_frame")
    frame_src = CONTROLLER_SRC[frame_at:CONTROLLER_SRC.index("def _spatial_context")]
    assert "if parked:" in frame_src
    assert "self._set_slice_quietly(session.primary, driver_index)" in frame_src
    assert "self._set_slice(session.primary, driver_index)" in frame_src
    park_at = CONTROLLER_SRC.index("def _park_reference_panes")
    park_src = CONTROLLER_SRC[park_at:park_at + 1400]
    assert "_set_slice_quietly(slot" in park_src


def test_readiness_requires_the_WHOLE_series_not_just_one_slice():
    """The 2026-08-26 "1 sagittal + 8 axial frames" session.

    The tab decodes progressively. `get_count_of_slices() > 0` was the readiness
    test, so a pane holding one slice of nine passed it; the capture order was
    then built from that one-entry snapshot, the sweep ran to completion, and a
    session covering a ninth of the study was written and reported as a success.
    Readiness must compare against the count the probe took from disk.
    """
    ready_at = CONTROLLER_SRC.index("def _slot_ready")
    ready_src = CONTROLLER_SRC[ready_at:CONTROLLER_SRC.index("def _wait_until_ready")]
    assert "_expected_slices" in ready_src
    assert "decoded >= expected" in ready_src
    assert "def _expected_slices" in CONTROLLER_SRC
    assert "slice_count" in CONTROLLER_SRC, "the probe's on-disk count is the authority"


def test_a_partial_stack_is_refused_rather_than_swept():
    """Second line of defence: a short capture order must never run.

    Every frame of a partial sweep is individually valid, so nothing downstream
    can tell that two thirds of the study is missing — which is exactly why the
    bad session reported `0 problem(s)`. The count is checked again after the
    instance lists are read, and a short one fails the run.
    """
    prep_at = CONTROLLER_SRC.index("def _prepare_geometry")
    prep_src = CONTROLLER_SRC[prep_at:CONTROLLER_SRC.index("def _enable_lock_sync")]
    assert "refusing to capture a partial series" in prep_src
    refuse_at = prep_src.index("refusing to capture a partial series")
    order_at = prep_src.index("build_capture_order")
    assert refuse_at < order_at, "the check must precede the capture order it protects"


def test_a_still_decoding_pane_is_not_re_asserted():
    """Re-issuing at a pane on the right series restarts the load it waits on."""
    wait_at = CONTROLLER_SRC.index("def _wait_until_ready")
    wait_src = CONTROLLER_SRC[wait_at:CONTROLLER_SRC.index("def _pending_detail")]
    assert 'showing != self._series_keys.get(slot, "")' in wait_src


def test_the_timeout_says_how_far_the_decode_got():
    """"timed out" alone sent the last debugging session down the wrong path."""
    assert "images decoded" in CONTROLLER_SRC
    assert "def _pending_detail" in CONTROLLER_SRC


def test_a_stalled_decode_is_refused_early_not_waited_out():
    """Same verdict as the 90 s timeout, delivered in ten seconds.

    Requiring the full on-disk count would otherwise turn a series whose file
    count and decodable slice count disagree into a minute and a half of
    waiting before the same refusal.
    """
    assert "_STALL_TIMEOUT_S" in CONTROLLER_SRC
    assert "def _decode_stalled" in CONTROLLER_SRC
    assert "loading stopped short for" in CONTROLLER_SRC
    stall_at = CONTROLLER_SRC.index("def _decode_stalled")
    stall_src = CONTROLLER_SRC[stall_at:CONTROLLER_SRC.index("def _pending_detail")]
    assert "if decoded <= 0" in stall_src, "a pane yet to start is waiting, not stalled"


def test_controller_still_verifies_the_follower_against_geometry():
    """Lock Sync is the mechanism; DICOM geometry stays the verdict.

    `_map_sync_cursor` returns None when the source point falls outside the
    target stack and `_do_lock_sync` then leaves that pane where it was.
    Trusting it blindly would pair a T2 slice with a stale T1 one, which no
    reader of the screenshot could detect.
    """
    assert "_settle_follower" in CONTROLLER_SRC
    assert "match_slice_across_series" in CONTROLLER_SRC
    assert 'record["followed_by"] = source' in CONTROLLER_SRC


# ---------------------------------------------------------------------------
# 8b. Reference-line policy: the pane being evaluated is captured CLEAN
# ---------------------------------------------------------------------------
#
# A reference line is context for a pane you look FROM and an obstruction on a
# pane you look AT — it can lie across exactly the disc or canal the frame
# exists to show, and once it is in the PNG no later stage can remove it. Which
# panes are which is the SESSION's business, never the engine's.


class _FakeQtViewer:
    def __init__(self):
        self.cleared = 0

    def clear_overlay_lines(self):
        self.cleared += 1


class _FakeOverlayViewer:
    IS_QT_BRIDGE = True

    def __init__(self):
        self.qt_viewer = _FakeQtViewer()


class _FakeVtkWidget:
    def __init__(self):
        self.updates = 0

    def update(self):
        self.updates += 1


def _policy_for(roles):
    viewers = {r: _FakeOverlayViewer() for r in roles}
    widgets = {r: _FakeVtkWidget() for r in roles}
    redraws = []
    policy = reflines.ReferenceLinePolicy(
        viewer_for=viewers.get, widget_for=widgets.get,
        redraw=lambda: redraws.append(1),
    )
    return policy, viewers, widgets, redraws


def test_the_sagittal_sweep_captures_both_sagittals_clean():
    """VP1 + VP2 clean, VP3 keeps its line as the spatial reference."""
    session = protos.LUMBAR_MRI.session("sagittal")
    policy, viewers, _, _ = _policy_for(protos.LUMBAR_MRI.slot_keys)

    hidden = policy.apply_for(session)

    assert hidden == (C.SLOT_SAG_T2, C.SLOT_SAG_T1)
    assert viewers[C.SLOT_SAG_T2].qt_viewer.cleared == 1
    assert viewers[C.SLOT_SAG_T1].qt_viewer.cleared == 1
    assert viewers[C.SLOT_AX_T2].qt_viewer.cleared == 0, \
        "the axial pane is the reference here and must keep its line"


def test_the_axial_sweep_captures_the_axial_clean():
    """VP3 clean; both sagittals keep the line that shows the level."""
    session = protos.LUMBAR_MRI.session("axial")
    policy, viewers, _, _ = _policy_for(protos.LUMBAR_MRI.slot_keys)

    hidden = policy.apply_for(session)

    assert hidden == (C.SLOT_AX_T2,)
    assert viewers[C.SLOT_AX_T2].qt_viewer.cleared == 1
    assert viewers[C.SLOT_SAG_T2].qt_viewer.cleared == 0
    assert viewers[C.SLOT_SAG_T1].qt_viewer.cleared == 0


def test_reference_lines_are_drawn_before_they_are_selectively_cleared():
    """Draw-then-clear: the engine has no per-viewport switch to draw with."""
    session = protos.LUMBAR_MRI.session("sagittal")
    policy, _, widgets, redraws = _policy_for(protos.LUMBAR_MRI.slot_keys)

    policy.apply_for(session)

    assert len(redraws) == 1, "one full all-pairs repaint per frame"
    assert widgets[C.SLOT_SAG_T2].updates == 1, "a cleared pane must be repainted"
    assert widgets[C.SLOT_AX_T2].updates == 0, "an untouched pane must not be"


def test_restoring_gives_every_pane_its_lines_back():
    session = protos.LUMBAR_MRI.session("sagittal")
    policy, _, _, redraws = _policy_for(protos.LUMBAR_MRI.slot_keys)
    policy.apply_for(session)

    policy.restore()

    assert policy.active_session is None
    assert len(redraws) == 2, "restore is one unsuppressed redraw"
    policy.restore()
    assert len(redraws) == 2, "restore is idempotent"


def test_the_policy_never_touches_a_global_reference_line_setting():
    """Nothing to save because nothing global is changed — say so honestly.

    Eagle Eye does not flip AIPACS_REFERENCE_LINES_ALL_PAIRS, the line style or
    a toolbar toggle; the only state it changes is which overlays are painted.
    A guard here stops someone "improving" restore() into a fake save/restore
    of a setting that was never touched.
    """
    src = (REPO_ROOT / "modules" / "ai_imaging" / "eagle_eye_lumbar"
           / "reference_lines.py").read_text(encoding="utf-8")
    assert "AIPACS_REFERENCE_LINES_ALL_PAIRS" not in src.split('"""', 2)[2], \
        "the policy must not read or write the global all-pairs flag"
    assert "set_reference_line_style" not in src


def test_a_viewport_without_an_overlay_backend_is_skipped_not_crashed():
    policy, _, _, _ = _policy_for(())
    hidden = policy.apply_for(protos.LUMBAR_MRI.session("sagittal"))
    assert hidden == ()


def test_the_controller_applies_the_policy_every_frame_and_restores_at_the_end():
    assert "self.reference_lines = ReferenceLinePolicy(" in CONTROLLER_SRC
    assert "self.reference_lines.apply_for(self._session)" in CONTROLLER_SRC
    refresh_at = CONTROLLER_SRC.index("def _refresh_reference_lines")
    capture_at = CONTROLLER_SRC.index("QTimer.singleShot(_STEP_SETTLE_MS")
    apply_at = CONTROLLER_SRC.index("self.reference_lines.apply_for(self._session)")
    assert refresh_at < apply_at, "the policy is applied inside the pre-capture refresh"
    assert "self.reference_lines.restore()" in CONTROLLER_SRC
    assert capture_at > 0


# ---------------------------------------------------------------------------
# 8c. Protocol-driven architecture: lumbar is a configuration, not the engine
# ---------------------------------------------------------------------------


def test_lumbar_declares_its_two_sweeps_as_protocol_data():
    sessions = protos.LUMBAR_MRI.sessions
    assert [s.name for s in sessions] == ["sagittal", "axial"]

    sag, ax = sessions
    assert sag.primary == C.SLOT_SAG_T2
    assert sag.synced == (C.SLOT_SAG_T1,)
    assert sag.reference == (C.SLOT_AX_T2,)
    assert sag.park_reference is False

    assert ax.primary == C.SLOT_AX_T2
    assert ax.synced == ()
    assert ax.reference == (C.SLOT_SAG_T2, C.SLOT_SAG_T1)
    assert ax.park_reference is True


def test_hidden_reference_lines_default_to_the_panes_being_evaluated():
    """Derived, so the rule and the configuration cannot drift apart."""
    for session in protos.LUMBAR_MRI.sessions:
        assert session.hide_reference_lines_on == session.evaluation_roles
        assert session.evaluation_roles == (session.primary,) + session.synced


def test_a_session_may_override_which_panes_stay_clean():
    """The default is a default, not a law — a protocol can say otherwise."""
    session = protos.CaptureSession(
        name="axial", primary=C.SLOT_AX_T2, plane=C.PLANE_AXIAL,
        synced=(C.SLOT_AX_FLAIR,), reference=(C.SLOT_SAG_T1,),
        hide_reference_lines_on=(C.SLOT_AX_T2,),
    )
    assert session.evaluation_roles == (C.SLOT_AX_T2, C.SLOT_AX_FLAIR)
    assert session.hide_reference_lines_on == (C.SLOT_AX_T2,)


def test_sync_groups_are_derived_from_the_sweeps_that_do_the_moving():
    assert protos.LUMBAR_MRI.sync_groups == ((C.SLOT_SAG_T2, C.SLOT_SAG_T1),)


def test_a_protocol_without_sessions_is_not_implemented():
    """Slots alone are not a pipeline — offering it would fail mid-sweep."""
    for protocol in protos.PROTOCOLS:
        if protocol.id == "lumbar_mri":
            assert protocol.implemented is True
        else:
            assert protocol.implemented is False


def test_a_future_protocol_needs_configuration_not_engine_code():
    """The brain example from the spec, assembled from existing vocabulary.

    Nothing here touches the controller: if this can be declared and read back,
    a new protocol is a configuration change.
    """
    brain = protos.Protocol(
        id="brain_mri_demo", name="Brain MRI", modality="MR",
        regions=(protos.REGION_BRAIN,), layout=(1, 3), capture=True,
        slots=(
            protos.ProtocolSlot(C.SLOT_AX_T2, "Axial T2", 1, C.PLANE_AXIAL, protos.WEIGHTING_T2),
            protos.ProtocolSlot(C.SLOT_AX_FLAIR, "Axial FLAIR", 2, C.PLANE_AXIAL, protos.WEIGHTING_T2),
            protos.ProtocolSlot(C.SLOT_SAG_T1, "Sagittal T1", 3, C.PLANE_SAGITTAL, protos.WEIGHTING_T1),
        ),
        sessions=(
            protos.CaptureSession(
                name="axial", primary=C.SLOT_AX_T2, synced=(C.SLOT_AX_FLAIR,),
                reference=(C.SLOT_SAG_T1,), plane=C.PLANE_AXIAL,
            ),
        ),
    )
    assert brain.implemented is True
    assert brain.slot_keys == (C.SLOT_AX_T2, C.SLOT_AX_FLAIR, C.SLOT_SAG_T1)
    # The two axial evaluation panes are clean; the sagittal reference keeps its line.
    assert brain.sessions[0].hide_reference_lines_on == (C.SLOT_AX_T2, C.SLOT_AX_FLAIR)
    assert brain.sync_groups == ((C.SLOT_AX_T2, C.SLOT_AX_FLAIR),)
    assert brain.as_dict()["sessions"][0]["primary"] == C.SLOT_AX_T2


def test_the_engine_names_no_body_part():
    """No lumbar role, pass name or literal in the engine's CODE.

    Checked against the AST rather than the raw text, so the prose that explains
    the lumbar history (and the historical class alias) cannot fail this, while
    a real `SLOT_SAG_T2` or a `"lumbar_mri"` default would.
    """
    import ast
    tree = ast.parse(CONTROLLER_SRC)

    forbidden_names = {"SLOT_SAG_T2", "SLOT_SAG_T1", "SLOT_AX_T2", "SLOT_ORDER",
                       "PASS_SAGITTAL", "PASS_AXIAL"}
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update(a.name for a in node.names)
    offenders = (used | imported) & forbidden_names
    assert not offenders, \
        f"the capture engine still references {sorted(offenders)}; that belongs in protocols.py"

    # Docstrings are string constants too, and the ones here deliberately
    # explain the lumbar history. Exclude them: this guard is about VALUES the
    # engine computes with, not about what it says.
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = (node.body or [None])[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

    literals = {n.value.lower() for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings}
    body_parts = {s for s in literals
                  if "lumbar" in s or "sagittal_t" in s or s in ("axial_t2", "sagittal")}
    assert not body_parts, \
        f"the capture engine hardcodes {sorted(body_parts)}; that belongs in protocols.py"


def test_the_engine_class_is_not_named_after_one_body_part():
    """With a back-compat alias, so this rename breaks no caller."""
    assert "class EagleEyeCaptureController" in CONTROLLER_SRC
    assert "LumbarCaptureController = EagleEyeCaptureController" in CONTROLLER_SRC


def test_the_store_takes_its_folders_from_the_protocol():
    """Output structure is protocol data: Sagittal/ and Axial/ are lumbar's."""
    specs = [store.PassSpec.from_capture_session(s) for s in protos.LUMBAR_MRI.sessions]
    assert [s.directory for s in specs] == ["Sagittal", "Axial"]
    assert [s.prefix for s in specs] == ["sagittal", "axial"]
    assert [s.session_type for s in specs] == ["lumbar_sagittal", "lumbar_axial"]

    other = store.PassSpec.from_capture_session(
        protos.CaptureSession(name="perfusion", primary=C.SLOT_AX_T2, plane=C.PLANE_AXIAL)
    )
    assert other.directory == "Perfusion" and other.prefix == "perfusion"


def test_a_session_written_with_protocol_passes_validates(tmp_path):
    protocol = protos.LUMBAR_MRI
    session = store.create_session(
        "1.2.3", root=tmp_path,
        passes=[store.PassSpec.from_capture_session(s) for s in protocol.sessions],
        protocol_id=protocol.id,
    )
    session.set_layout(protocol.layout[0], protocol.layout[1], protocol.slot_keys)
    assert session.pass_names == ["sagittal", "axial"]

    for name in session.pass_names:
        path = session.next_capture_path(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        session.add_capture(name, {"session": name, "panes": {}})
    session.write()

    assert session.validate() == []
    doc = json.loads((session.path / "session.json").read_text(encoding="utf-8"))
    assert doc["session_kind"] == "lumbar_mri"
    assert doc["eagle_eye_version"] == C.EAGLE_EYE_VERSION
    assert set(doc["passes"]) == {"sagittal", "axial"}


def test_frames_are_keyed_by_role_not_by_lumbar_field_names():
    """A manifest reader must not need to know what viewport 2 happened to be."""
    assert '"panes": panes' in CONTROLLER_SRC
    assert 'def _pane_record' in CONTROLLER_SRC
    assert '"role": role' in CONTROLLER_SRC
    for dead in ('"t2_sagittal_instance"', '"t1_sagittal_slice_index"',
                 '"axial_reference_instance"'):
        assert dead not in CONTROLLER_SRC, f"{dead} is a lumbar-shaped manifest key"


# ---------------------------------------------------------------------------
# 9. The 2026-08-26 live-study regression: the gate read the wrong source
# ---------------------------------------------------------------------------
#
# A real Siemens lumbar study was REFUSED by the Eagle Eye button. What it
# actually carried:
#
#   studies.study_description   = ''        (empty in the local DB)
#   series.body_part_examined   = NULL      (every series)
#   SeriesDescription           = 't2_tse_sag' / 't1_tse_sag' / 't2_tse_tra_msma'
#   BodyPartExamined (on disk)  = 'LSPINE'  <- the ONLY region signal anywhere
#
# The gate was reading GUI metadata and matching free text. Free text alone can
# never be the gate; the coded DICOM body part is.

LIVE_STUDY_SERIES = ("t2_tse_sag", "t1_tse_sag", "t2_tse_tra_msma",
                     "localizer", "t2_haste_COR_myelo_512")


def test_regression_siemens_lumbar_study_is_recognised():
    verdict, reason = modes.lumbar_verdict(["LSPINE"], LIVE_STUDY_SERIES)
    assert verdict == modes.VERDICT_LUMBAR
    assert "LSPINE" in reason


def test_regression_those_series_names_alone_prove_nothing():
    """Guards the lesson: this is why the body part must be consulted."""
    assert modes.looks_like_lumbar(*LIVE_STUDY_SERIES) is False
    verdict, _ = modes.lumbar_verdict([], LIVE_STUDY_SERIES)
    assert verdict == modes.VERDICT_UNKNOWN, "unknown, never a silent yes"


@pytest.mark.parametrize("value,expected", [
    ("LSPINE", modes.VERDICT_LUMBAR),
    ("L_SPINE", modes.VERDICT_LUMBAR),
    ("l spine", modes.VERDICT_LUMBAR),
    ("LUMBAR SPINE", modes.VERDICT_LUMBAR),
    ("LUMBOSACRAL", modes.VERDICT_LUMBAR),
    ("ABDOMEN, ABDOMENPELVIS", modes.VERDICT_OTHER),
    ("HEAD, BRAIN", modes.VERDICT_OTHER),
    ("BREAST", modes.VERDICT_OTHER),
    ("PROSTATE", modes.VERDICT_OTHER),
    ("CSPINE", modes.VERDICT_OTHER),
    ("TSPINE", modes.VERDICT_OTHER),
    ("", modes.VERDICT_UNKNOWN),
    ("WHATSIT", modes.VERDICT_UNKNOWN),
])
def test_body_part_verdict(value, expected):
    assert modes.body_part_verdict([value]) == expected


def test_a_lumbar_code_anywhere_wins_over_a_neighbouring_level():
    """A spine protocol legitimately reports more than one level."""
    assert modes.body_part_verdict(["TSPINE", "LSPINE"]) == modes.VERDICT_LUMBAR
    assert modes.body_part_verdict(["LSPINE, SPINE"]) == modes.VERDICT_LUMBAR


def test_body_part_beats_a_misleading_description():
    verdict, reason = modes.lumbar_verdict(["BRAIN"], ["MRI LUMBAR SPINE"])
    assert verdict == modes.VERDICT_OTHER
    assert "BRAIN" in reason


def test_text_is_used_only_when_the_body_part_is_silent():
    verdict, reason = modes.lumbar_verdict([""], ["MRI LUMBAR SPINE"])
    assert verdict == modes.VERDICT_LUMBAR
    assert "description" in reason

    verdict, reason = modes.lumbar_verdict([], ["MRI CERVICAL SPINE"])
    assert verdict == modes.VERDICT_OTHER

    verdict, reason = modes.lumbar_verdict([], [])
    assert verdict == modes.VERDICT_UNKNOWN


def test_study_verdict_reads_the_candidates_own_headers():
    from modules.ai_imaging.eagle_eye_lumbar.series_probe import study_lumbar_verdict

    lumbar = [
        SeriesCandidate(index=0, series_description="t2_tse_sag", body_part="LSPINE",
                        plane=C.PLANE_SAGITTAL, modality="MR"),
        SeriesCandidate(index=1, series_description="t1_tse_sag", body_part="LSPINE",
                        plane=C.PLANE_SAGITTAL, modality="MR"),
    ]
    assert study_lumbar_verdict(lumbar)[0] == modes.VERDICT_LUMBAR

    abdomen = [
        SeriesCandidate(index=0, series_description="t2_tse_tra_p2_trig_512",
                        body_part="ABDOMENPELVIS", plane=C.PLANE_AXIAL, modality="MR"),
        SeriesCandidate(index=1, series_description="t2_haste_fs_SAG_p2_mbh",
                        body_part="ABDOMEN", plane=C.PLANE_SAGITTAL, modality="MR"),
    ]
    assert study_lumbar_verdict(abdomen)[0] == modes.VERDICT_OTHER


def test_series_files_are_counted_once_per_file(tmp_path):
    """Windows globs are case-insensitive: *.dcm and *.DCM hit the same files.

    Before the fix an 11-slice sagittal was probed as 22 slices, which feeds the
    classifier's plausibility scoring.
    """
    from modules.ai_imaging.eagle_eye_lumbar.series_probe import _dicom_files

    (tmp_path / "Instance_0001.dcm").write_bytes(b"x")
    (tmp_path / "Instance_0002.DCM").write_bytes(b"x")
    files = _dicom_files(tmp_path)
    assert len(files) == 2, f"each file must be counted once, got {files}"
    assert len({str(p).lower() for p in files}) == 2


def test_probe_falls_back_to_extensionless_exports(tmp_path):
    from modules.ai_imaging.eagle_eye_lumbar.series_probe import _dicom_files

    (tmp_path / "IM0001").write_bytes(b"x")
    assert len(_dicom_files(tmp_path)) == 1


def test_button_gate_reads_disk_headers_not_gui_metadata():
    """Source-pinned: the regression was reading the GUI's in-memory metadata.

    The gate now lives in the resolver, which probes the study's headers via
    ``ResolveContext.for_widget`` -> ``probe_study_series``. What must never
    come back is a decision made from ``image_viewer.metadata`` /
    ``metadata_fixed``, which is what refused a real lumbar study.
    """
    src = (REPO_ROOT / "modules" / "viewer" / "interactor_styles"
           / "ai_chat_interactorstyle.py").read_text(encoding="utf-8")
    assert "ResolveContext.for_widget" in src
    assert "ee_resolver.resolve" in src

    lumbar_block = src[src.index("def _open_lumbar_eagle_eye"):]
    lumbar_block = lumbar_block[:lumbar_block.index("\n    def ", 10)]
    for banned in ("metadata_fixed.get", "image_viewer, 'metadata'"):
        assert banned not in lumbar_block, (
            f"the region decision must not read GUI metadata ({banned!r})")


def test_probe_still_exposes_the_region_verdict_helper():
    """study_lumbar_verdict stays available - protocols.py now generalises it."""
    from modules.ai_imaging.eagle_eye_lumbar.series_probe import study_lumbar_verdict
    assert callable(study_lumbar_verdict)


def test_capture_context_snapshots_the_full_pacs_series_catalog():
    from modules.ai_imaging.eagle_eye_lumbar.capture_controller import build_study_context

    selection = classify_lumbar_series(lumbar_study())

    class Widget:
        study_uid = "1.2.3.4"
        patient_id = "test-reception-id"
        metadata_fixed = {}
        lst_thumbnails_data = [
            {
                "metadata": {
                    "series": {
                        "series_number": "9",
                        "modality": "MR",
                        "series_description": "T1 FS post contrast lumbar spine",
                        "body_part": "LSPINE",
                    },
                    "instances": [{}, {}, {}],
                }
            },
            {
                "metadata": {
                    "series": {
                        "series_number": "100000",
                        "modality": "DOC",
                        "series_description": "Clinical history",
                    },
                    "instances": [{}],
                }
            },
        ]

    context = build_study_context(Widget(), selection)

    assert context["study_series_inventory_scope"] == "pacs_series_catalog"
    inventory = context["study_series_inventory"]
    assert any(item["contrast_evidence"] == "postcontrast" for item in inventory)
    assert any(item["kind"] == "clinical_document" for item in inventory)
    assert all("series_uid" not in item for item in inventory)


def test_preflight_handoff_snapshots_patient_id_and_the_complete_catalog():
    from modules.ai_imaging.eagle_eye_lumbar import session_request

    candidates = lumbar_study()
    selection = classify_lumbar_series(candidates)

    class OriginalPatientWidget:
        patient_id = "reception-patient-42"
        metadata_fixed = {}
        lst_thumbnails_data = [
            {
                "metadata": {
                    "series": {
                        "series_number": str(number),
                        "modality": "DOC" if number == 100000 else "MR",
                        "series_description": (
                            "Clinical history" if number == 100000 else f"MRI series {number}"
                        ),
                        "body_part": "LSPINE",
                        "series_uid": f"1.2.840.{number}",
                    },
                    "instances": [{}] * (1 if number == 100000 else number),
                }
            }
            for number in (1, 2, 3)
        ]

    original_payload = {"protocol": {"id": "lumbar_mri"}}
    payload = session_request.with_study_context(
        original_payload,
        OriginalPatientWidget(),
        selection,
        candidates=candidates,
    )

    assert original_payload == {"protocol": {"id": "lumbar_mri"}}
    snapshot = payload["study_context"]
    assert snapshot["patient_id"] == "reception-patient-42"
    assert snapshot["study_series_inventory_scope"] == "pacs_series_catalog"
    assert len(snapshot["study_series_inventory"]) == 6
    assert all("series_uid" not in item for item in snapshot["study_series_inventory"])


def test_capture_context_uses_complete_handoff_when_the_ai_widget_is_reduced():
    from modules.ai_imaging.eagle_eye_lumbar.capture_controller import build_study_context

    selection = classify_lumbar_series(lumbar_study())
    full_inventory = [
        {
            "series_number": str(number),
            "modality": "DOC" if number == 100000 else "MR",
            "description": "Clinical history" if number == 100000 else f"MRI series {number}",
            "protocol": "",
            "body_part": "LSPINE",
            "plane": "unknown",
            "slice_count": 1 if number == 100000 else number,
            "contrast_evidence": "none",
            "kind": "clinical_document" if number == 100000 else "imaging",
        }
        for number in (1, 2, 3, 4, 5, 100000)
    ]

    class ReducedAIWidget:
        study_uid = "1.2.3.4"
        patient_id = None
        metadata_fixed = {}
        lst_thumbnails_data = []

    context = build_study_context(
        ReducedAIWidget(),
        selection,
        handoff_context={
            "patient_id": "reception-patient-42",
            "study_series_inventory_scope": "pacs_series_catalog",
            "study_series_inventory": full_inventory,
        },
    )

    assert context["patient_id"] == "reception-patient-42"
    assert context["study_series_inventory_scope"] == "pacs_series_catalog"
    assert len(context["study_series_inventory"]) == 6
    assert any(item["kind"] == "clinical_document" for item in context["study_series_inventory"])
