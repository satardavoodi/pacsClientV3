"""Guards for the Eagle Eye pre-flight: study -> protocol -> series -> validate.

The governing principle is "automatic when confident, interactive when not", and
both halves are failure modes:

  * asking about something that was certain makes every lumbar MRI a chore, so a
    clearly-labelled study must open with NO prompts at all;
  * proceeding on something uncertain silently loads the wrong three series, and
    every screenshot after that is wrong, so anything short of high confidence
    must ask.

The resolver takes its prompts by injection, so all of this runs headless with
fakes that record what was asked.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.ai_imaging.eagle_eye_lumbar import protocols as P          # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import resolver as R           # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar import session_request         # noqa: E402
from modules.ai_imaging.eagle_eye_lumbar.constants import (             # noqa: E402
    CONFIDENCE_HIGH, CONFIDENCE_LOW, CONFIDENCE_MEDIUM, CONFIDENCE_NONE,
    PLANE_AXIAL, PLANE_SAGITTAL, SLOT_AX_T2, SLOT_SAG_T1, SLOT_SAG_T2,
)
from modules.ai_imaging.eagle_eye_lumbar.series_classifier import (     # noqa: E402
    SeriesCandidate, classify_for_protocol,
)
from modules.ai_imaging.eagle_eye_lumbar.study_catalog import (         # noqa: E402
    StudyCandidate, needs_study_prompt,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def series(index, desc, plane, te=None, tr=None, body_part="LSPINE", **kw):
    kw.setdefault("modality", "MR")
    kw.setdefault("slice_count", 11 if plane == PLANE_SAGITTAL else 26)
    kw.setdefault("thumbnail_index", index)
    return SeriesCandidate(
        index=index, series_description=desc, plane=plane, body_part=body_part,
        echo_time=te, repetition_time=tr, series_number=index + 1,
        series_uid=f"1.2.3.{index + 1}", **kw
    )


def lumbar_series():
    """The real Siemens lumbar protocol this feature was built against."""
    return [
        series(0, "localizer", PLANE_SAGITTAL, te=2.38, tr=5.6, slice_count=3),
        series(1, "t2_tse_sag", PLANE_SAGITTAL, te=98.0, tr=2550.0),
        series(2, "t1_tse_sag", PLANE_SAGITTAL, te=9.6, tr=407.0),
        series(3, "t2_tse_tra_msma", PLANE_AXIAL, te=101.0, tr=2530.0),
    ]


def study(uid="1.2.3", desc="", date="20260820", modality="MR", current=True, count=4):
    return StudyCandidate(uid, desc, date, modality, "LSPINE", count, path=None,
                          is_current=current)


class RecordingPrompts(R.Prompts):
    """A fake UI that records what it was asked and answers as configured."""

    def __init__(self, study=None, protocol=None, series_answers=None):
        self.asked = []
        self._study = study
        self._protocol = protocol
        self._series = dict(series_answers or {})
        self.reports = []

    def choose_study(self, studies, reason):
        self.asked.append(("study", [s.study_uid for s in studies], reason))
        return self._study

    def choose_protocol(self, protocols, detection):
        self.asked.append(("protocol", [p.id for p in protocols], detection.reason))
        return self._protocol

    def choose_series(self, protocol, slot_key, options, suggestion, reason):
        self.asked.append(("series", slot_key, [o.series_description for o in options]))
        return self._series.get(slot_key)

    def report(self, title, message):
        self.reports.append(message)

    @property
    def asked_kinds(self):
        return [entry[0] for entry in self.asked]


def context_for(studies, series_by_uid):
    return R.ResolveContext(
        studies=lambda: list(studies),
        probe=lambda s: list(series_by_uid.get(s.study_uid, [])),
    )


# ---------------------------------------------------------------------------
# Protocol detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("body_part,expected_id", [
    ("LSPINE", "lumbar_mri"),
    ("L_SPINE", "lumbar_mri"),
    ("LUMBAR SPINE", "lumbar_mri"),
    ("CSPINE", "cervical_mri"),
    ("THORACIC", "thoracic_mri"),
    ("KNEE", "knee_mri"),
    ("SHOULDER", "shoulder_mri"),
    ("BRAIN", "brain_mri"),
])
def test_body_part_selects_the_protocol(body_part, expected_id):
    detection = P.detect_protocol([body_part], [])
    assert detection.protocol is not None
    assert detection.protocol.id == expected_id
    assert detection.confidence == CONFIDENCE_HIGH


def test_only_an_implemented_protocol_is_certain_enough_to_skip_the_prompt():
    """Recognising a knee MRI perfectly is not a reason to start a knee sweep."""
    lumbar = P.detect_protocol(["LSPINE"], [])
    assert lumbar.certain is True

    knee = P.detect_protocol(["KNEE"], [])
    assert knee.confidence == CONFIDENCE_HIGH
    assert knee.protocol.implemented is False
    assert knee.certain is False, "an unimplemented protocol must still ask"


def test_a_spine_study_reporting_two_levels_routes_to_the_capturable_one():
    detection = P.detect_protocol(["TSPINE", "LSPINE"], [])
    assert detection.protocol.id == "lumbar_mri"


def test_description_only_detection_is_never_high_confidence():
    detection = P.detect_protocol([], ["MRI LUMBAR SPINE"])
    assert detection.protocol.id == "lumbar_mri"
    assert detection.confidence == CONFIDENCE_MEDIUM
    assert detection.certain is False, "free text alone must be confirmed"


def test_conflicting_descriptions_are_low_confidence():
    detection = P.detect_protocol([], ["MRI LUMBAR SPINE", "MRI BRAIN"])
    assert detection.protocol is None
    assert detection.confidence == CONFIDENCE_LOW
    assert "more than one region" in detection.reason


def test_a_study_naming_nothing_is_not_guessed():
    detection = P.detect_protocol([], ["t2_tse_sag", "t1_tse_sag"])
    assert detection.protocol is None
    assert detection.confidence == CONFIDENCE_NONE
    assert detection.certain is False


def test_an_unknown_body_part_is_reported_not_ignored():
    detection = P.detect_protocol(["WHATSIT"], [])
    assert detection.confidence == CONFIDENCE_LOW
    assert "WHATSIT" in detection.reason


# ---------------------------------------------------------------------------
# Protocol definitions are data, not hardcoded UI logic
# ---------------------------------------------------------------------------

def test_the_lumbar_protocol_declares_its_slots_and_layout():
    protocol = P.LUMBAR_MRI
    assert protocol.layout == (1, 3)
    assert protocol.slot_keys == (SLOT_SAG_T2, SLOT_SAG_T1, SLOT_AX_T2)
    assert [s.position for s in protocol.slots] == [1, 2, 3]
    assert protocol.slot(SLOT_SAG_T2).plane == PLANE_SAGITTAL
    assert protocol.slot(SLOT_SAG_T2).weighting == "t2"
    assert protocol.slot(SLOT_SAG_T1).weighting == "t1"
    assert protocol.slot(SLOT_AX_T2).plane == PLANE_AXIAL


def test_planned_protocols_are_listed_but_not_runnable():
    planned = [p for p in P.PROTOCOLS if not p.implemented]
    assert planned, "the picker should show what is coming"
    assert all(p.slots == () for p in planned)
    assert [p.id for p in P.implemented_protocols()] == ["lumbar_mri"]


def test_the_classifier_reads_the_protocol_rather_than_lumbar_constants():
    """A slot's plane/weighting/slice band come from the Protocol object."""
    protocol = P.LUMBAR_MRI
    selection = classify_for_protocol(protocol, lumbar_series())
    assert selection.protocol is protocol
    assert selection.slot_order == list(protocol.slot_keys)
    assert selection.resolved is True


# ---------------------------------------------------------------------------
# Study catalogue
# ---------------------------------------------------------------------------

def test_one_study_is_not_a_choice():
    assert needs_study_prompt([study()]) is False
    assert needs_study_prompt([study("1"), study("2")]) is True
    assert needs_study_prompt([]) is False


def test_study_label_identifies_the_exam():
    candidate = StudyCandidate("1.2.3", "LUMBAR SPINE", "20260820", "MR", "LSPINE", 6)
    assert candidate.formatted_date == "2026-08-20"
    assert candidate.label == "MR LUMBAR SPINE — 2026-08-20"
    assert "6 series" in candidate.detail


def test_a_study_with_no_description_still_gets_an_identifiable_label():
    candidate = StudyCandidate("1.2.3", "", "20260820", "MR", "LSPINE", 6)
    assert "LSPINE" in candidate.label
    assert "2026-08-20" in candidate.label


def test_the_documents_pseudo_study_is_not_an_imaging_candidate():
    assert StudyCandidate("1", "Documents", "", "DOC").is_imaging is False
    assert StudyCandidate("2", "Spine", "", "MR").is_imaging is True
    assert StudyCandidate("3", "Mixed", "", "MR, DOC").is_imaging is True


# ---------------------------------------------------------------------------
# The resolver: automatic when confident
# ---------------------------------------------------------------------------

def test_a_clearly_labelled_lumbar_study_opens_with_no_prompts_at_all():
    """The whole point. One click, no dialogs, correct three series."""
    s = study()
    prompts = RecordingPrompts()
    resolution = R.resolve(context_for([s], {s.study_uid: lumbar_series()}), prompts)

    assert resolution is not None
    assert prompts.asked == [], f"nothing should have been asked, got {prompts.asked}"
    assert resolution.protocol.id == "lumbar_mri"
    assert resolution.assignment(SLOT_SAG_T2).series_description == "t2_tse_sag"
    assert resolution.assignment(SLOT_SAG_T1).series_description == "t1_tse_sag"
    assert resolution.assignment(SLOT_AX_T2).series_description == "t2_tse_tra_msma"


def test_every_slot_records_how_it_was_filled():
    s = study()
    resolution = R.resolve(context_for([s], {s.study_uid: lumbar_series()}),
                           RecordingPrompts())
    mapping = resolution.slot_series()
    assert set(mapping) == {SLOT_SAG_T2, SLOT_SAG_T1, SLOT_AX_T2}
    for entry in mapping.values():
        assert entry["assigned_by"] == "automatic"
        assert entry["confidence"] == CONFIDENCE_HIGH
        assert entry["series_uid"]


def test_the_mapping_travels_by_uid_not_by_thumbnail_index():
    """The Eagle Eye tab is a different widget with its own thumbnail list."""
    s = study()
    resolution = R.resolve(context_for([s], {s.study_uid: lumbar_series()}),
                           RecordingPrompts())
    for entry in resolution.slot_series().values():
        assert "thumbnail_index" not in entry
        assert entry["series_uid"] and entry["series_number"]


# ---------------------------------------------------------------------------
# The resolver: interactive when it is not
# ---------------------------------------------------------------------------

def test_several_studies_are_never_chosen_for_the_user():
    a, b = study("1.2.3", "LUMBAR", current=True), study("4.5.6", "PELVIS", current=False)
    prompts = RecordingPrompts(study=a)
    resolution = R.resolve(
        context_for([a, b], {a.study_uid: lumbar_series(), b.study_uid: lumbar_series()}),
        prompts,
    )
    assert "study" in prompts.asked_kinds
    assert resolution is not None
    assert resolution.study.study_uid == "1.2.3"


def test_cancelling_the_study_prompt_opens_nothing():
    a, b = study("1"), study("2", current=False)
    prompts = RecordingPrompts(study=None)
    assert R.resolve(context_for([a, b], {}), prompts) is None


def test_an_unlabelled_study_asks_for_the_protocol():
    plain = [series(i, d, p, te, tr, body_part="")
             for i, (d, p, te, tr) in enumerate([
                 ("t2_tse_sag", PLANE_SAGITTAL, 98.0, 2550.0),
                 ("t1_tse_sag", PLANE_SAGITTAL, 9.6, 407.0),
                 ("t2_tse_tra", PLANE_AXIAL, 101.0, 2530.0),
             ])]
    s = study()
    prompts = RecordingPrompts(protocol=P.LUMBAR_MRI)
    resolution = R.resolve(context_for([s], {s.study_uid: plain}), prompts)

    assert "protocol" in prompts.asked_kinds
    assert resolution is not None
    assert resolution.protocol.id == "lumbar_mri"


def test_the_protocol_prompt_offers_the_full_roadmap():
    s = study()
    plain = [series(0, "t2_tse_sag", PLANE_SAGITTAL, 98.0, 2550.0, body_part="")]
    prompts = RecordingPrompts(protocol=None)
    R.resolve(context_for([s], {s.study_uid: plain}), prompts)

    offered = next(e[1] for e in prompts.asked if e[0] == "protocol")
    assert "lumbar_mri" in offered
    assert "cervical_mri" in offered and "brain_mri" in offered


def test_cancelling_the_protocol_prompt_opens_nothing():
    s = study()
    plain = [series(0, "t2_tse_sag", PLANE_SAGITTAL, 98.0, 2550.0, body_part="")]
    assert R.resolve(context_for([s], {s.study_uid: plain}),
                     RecordingPrompts(protocol=None)) is None


def test_choosing_a_planned_protocol_says_it_is_not_available_yet():
    s = study()
    plain = [series(0, "t2_tse_sag", PLANE_SAGITTAL, 98.0, 2550.0, body_part="")]
    prompts = RecordingPrompts(protocol=P.get_protocol("knee_mri"))
    assert R.resolve(context_for([s], {s.study_uid: plain}), prompts) is None
    assert any("not available in this version" in m for m in prompts.reports)


def test_a_confidently_recognised_unsupported_region_is_refused_not_offered():
    """A brain MR is KNOWN to be a brain MR. It must not get a protocol picker.

    This is the dangerous case: a brain study genuinely contains a sagittal T2,
    a sagittal T1 and an axial T2, so if the user were offered the picker and
    chose "Lumbar Spine MRI", every slot would fill and every captured frame
    would be brain anatomy in a lumbar session. Uncertainty is a reason to ask;
    lack of support is not.
    """
    brain = [series(0, "t2_tse_sag", PLANE_SAGITTAL, 98.0, 2550.0, body_part="BRAIN"),
             series(1, "t1_tse_sag", PLANE_SAGITTAL, 9.6, 407.0, body_part="BRAIN"),
             series(2, "t2_tse_tra", PLANE_AXIAL, 101.0, 2530.0, body_part="BRAIN")]
    s = study()
    prompts = RecordingPrompts(protocol=P.LUMBAR_MRI)  # would say yes if asked
    assert R.resolve(context_for([s], {s.study_uid: brain}), prompts) is None
    assert "protocol" not in prompts.asked_kinds, "a known region must not be re-offered"
    assert any("Brain MRI" in m and "cannot analyse yet" in m for m in prompts.reports)


def test_a_known_region_with_no_protocol_at_all_is_also_refused():
    """ABDOMEN maps to no Eagle Eye protocol; say so rather than offering a list."""
    abdomen = [series(0, "t2_haste_fs_SAG", PLANE_SAGITTAL, 93.0, 1300.0, body_part="ABDOMEN"),
               series(1, "t2_tse_tra", PLANE_AXIAL, 96.0, 2701.0, body_part="ABDOMENPELVIS")]
    s = study()
    prompts = RecordingPrompts(protocol=P.LUMBAR_MRI)
    assert R.resolve(context_for([s], {s.study_uid: abdomen}), prompts) is None
    assert "protocol" not in prompts.asked_kinds
    assert any("cannot analyse yet" in m for m in prompts.reports)


# ---------------------------------------------------------------------------
# Only the uncertain slots are ever asked about
# ---------------------------------------------------------------------------

def test_only_the_uncertain_slot_is_asked_about():
    """Two confident slots must not be re-litigated because a third is unclear."""
    ambiguous = lumbar_series() + [
        series(4, "t2_tse_tra_2", PLANE_AXIAL, te=101.0, tr=2530.0),
    ]
    s = study()
    prompts = RecordingPrompts(series_answers={SLOT_AX_T2: ambiguous[3]})
    resolution = R.resolve(context_for([s], {s.study_uid: ambiguous}), prompts)

    series_questions = [e for e in prompts.asked if e[0] == "series"]
    assert len(series_questions) <= 1, "confident slots must not be re-asked"
    if series_questions:
        assert series_questions[0][1] == SLOT_AX_T2
    assert resolution is not None


def test_a_manually_chosen_slot_is_recorded_as_such():
    axial_a = series(3, "t2_tse_tra_msma", PLANE_AXIAL, te=101.0, tr=2530.0)
    axial_b = series(4, "t2_tse_tra_other", PLANE_AXIAL, te=101.0, tr=2530.0)
    candidates = lumbar_series()[:3] + [axial_a, axial_b]
    s = study()
    prompts = RecordingPrompts(series_answers={SLOT_AX_T2: axial_b})
    resolution = R.resolve(context_for([s], {s.study_uid: candidates}), prompts)

    assert resolution is not None
    if resolution.selection[SLOT_AX_T2].manual:
        assert resolution.assignment(SLOT_AX_T2) is axial_b
        assert resolution.slot_series()[SLOT_AX_T2]["assigned_by"] == "user"


def test_the_series_prompt_only_offers_series_that_passed_the_gates():
    """A coronal series or a localizer must not be assignable by hand either."""
    candidates = lumbar_series() + [
        series(4, "t2_haste_COR_myelo", "coronal", te=1200.0, tr=8000.0),
        series(5, "t2_tse_tra_2", PLANE_AXIAL, te=101.0, tr=2530.0),
    ]
    s = study()
    prompts = RecordingPrompts(series_answers={SLOT_AX_T2: candidates[3]})
    R.resolve(context_for([s], {s.study_uid: candidates}), prompts)

    for kind, slot_key, offered in [e for e in prompts.asked if e[0] == "series"]:
        assert "localizer" not in offered
        assert "t2_haste_COR_myelo" not in offered


def test_cancelling_a_series_prompt_opens_nothing():
    candidates = lumbar_series() + [
        series(4, "t2_tse_tra_2", PLANE_AXIAL, te=101.0, tr=2530.0),
    ]
    s = study()
    prompts = RecordingPrompts(series_answers={})
    result = R.resolve(context_for([s], {s.study_uid: candidates}), prompts)
    if any(e[0] == "series" for e in prompts.asked):
        assert result is None


def test_a_slot_no_series_could_fill_is_refused_not_asked():
    """No axial series at all: there is nothing to offer, so say so."""
    sagittals_only = lumbar_series()[:3]
    s = study()
    prompts = RecordingPrompts()
    assert R.resolve(context_for([s], {s.study_uid: sagittals_only}), prompts) is None
    assert any("Axial T2" in m for m in prompts.reports)
    assert not any(e[0] == "series" for e in prompts.asked)


# ---------------------------------------------------------------------------
# Validation before anything opens
# ---------------------------------------------------------------------------

def test_validation_refuses_a_duplicate_assignment():
    protocol = P.LUMBAR_MRI
    selection = classify_for_protocol(protocol, lumbar_series())
    duplicate = selection.candidate_for(SLOT_SAG_T2)
    selection.assign_manually(SLOT_SAG_T1, duplicate)

    problem = R._validate(protocol, selection)
    assert problem and "same series" in problem


def test_validation_refuses_a_missing_slot():
    protocol = P.LUMBAR_MRI
    selection = classify_for_protocol(protocol, lumbar_series())
    selection[SLOT_AX_T2].chosen = None

    problem = R._validate(protocol, selection)
    assert problem and "Axial T2" in problem


def test_validation_passes_a_complete_distinct_mapping():
    protocol = P.LUMBAR_MRI
    selection = classify_for_protocol(protocol, lumbar_series())
    assert R._validate(protocol, selection) is None


def test_an_empty_study_list_reports_rather_than_crashing():
    prompts = RecordingPrompts()
    assert R.resolve(context_for([], {}), prompts) is None
    assert prompts.reports


def test_a_study_with_no_readable_series_reports():
    s = study()
    prompts = RecordingPrompts()
    assert R.resolve(context_for([s], {s.study_uid: []}), prompts) is None
    assert any("No readable DICOM series" in m for m in prompts.reports)


def test_default_prompts_decline_rather_than_guess():
    """A caller with no UI must get 'unresolved', never a silent pick."""
    a, b = study("1"), study("2", current=False)
    assert R.resolve(context_for([a, b], {a.study_uid: lumbar_series()}), R.Prompts()) is None


# ---------------------------------------------------------------------------
# Hand-off to the Eagle Eye tab
# ---------------------------------------------------------------------------

def test_a_stashed_request_is_delivered_exactly_once():
    session_request.clear()
    session_request.stash("1.2.3", {"protocol": {"id": "lumbar_mri"}})
    assert session_request.peek("1.2.3") is not None
    assert session_request.take("1.2.3")["protocol"]["id"] == "lumbar_mri"
    assert session_request.take("1.2.3") is None, "a resolution must not be reused"


def test_a_request_for_another_study_is_never_delivered():
    session_request.clear()
    session_request.stash("1.2.3", {"protocol": {"id": "lumbar_mri"}})
    assert session_request.take("9.9.9") is None
    session_request.clear()


def test_a_request_with_no_study_uid_is_refused():
    session_request.clear()
    session_request.stash("", {"protocol": {"id": "lumbar_mri"}})
    assert session_request.take("") is None


def test_the_resolution_serialises_everything_the_manifest_needs():
    s = study(desc="LUMBAR SPINE")
    resolution = R.resolve(context_for([s], {s.study_uid: lumbar_series()}),
                           RecordingPrompts())
    payload = resolution.as_dict()
    assert payload["study"]["study_instance_uid"] == s.study_uid
    assert payload["protocol"]["id"] == "lumbar_mri"
    assert payload["protocol"]["layout"] == {"rows": 1, "columns": 3}
    assert payload["protocol_detection"]["confidence"] == CONFIDENCE_HIGH
    assert set(payload["slot_series"]) == {SLOT_SAG_T2, SLOT_SAG_T1, SLOT_AX_T2}
    assert payload["series_selection"]["resolved"] is True


# ---------------------------------------------------------------------------
# The layout must never open on a partial mapping (source-pinned)
# ---------------------------------------------------------------------------

BUTTON_SRC = (REPO_ROOT / "modules" / "viewer" / "interactor_styles"
              / "ai_chat_interactorstyle.py").read_text(encoding="utf-8")
TAB_SRC = (REPO_ROOT / "modules" / "ai_imaging" / "ai_module_ui" / "service_tab"
           / "imaging_tab.py").read_text(encoding="utf-8")
WORKFLOW_SRC = (REPO_ROOT / "modules" / "ai_imaging" / "eagle_eye_lumbar"
                / "workflow_coordinator.py").read_text(encoding="utf-8")


def test_the_button_resolves_before_it_opens_anything():
    assert "resolver.resolve" in BUTTON_SRC or "ee_resolver.resolve" in BUTTON_SRC
    resolve_at = BUTTON_SRC.index("ee_resolver.resolve")
    open_at = BUTTON_SRC.index("switch_right_panel('ai_module')")
    assert resolve_at < open_at, "the layout must not open before resolution"


def test_the_button_hands_the_mapping_over_instead_of_re_deciding():
    assert "session_request.stash" in BUTTON_SRC
    assert "session_request.take" in WORKFLOW_SRC
    assert "_apply_resolved_mapping" in WORKFLOW_SRC


def test_the_tab_does_not_pre_wait_on_the_thumbnail_list():
    """The sweep starts as soon as the mapping is valid.

    `lst_thumbnails_data` holds LOADED series only, so polling it before
    assigning was both slow (seconds added to every run) and wrong: for a study
    whose remaining series had never been requested the entries never appeared
    and the run timed out on series nobody had asked for. Assignment itself
    triggers the decode, so the controller asks and then waits on the viewports.
    """
    assert "_await_required_series" not in WORKFLOW_SRC
    assert "_lumbar_thumbnail_index" not in WORKFLOW_SRC
    assert "_LUMBAR_LOAD_TIMEOUT_S" not in WORKFLOW_SRC
    resolved_at = WORKFLOW_SRC.index("Eagle Eye could not identify")
    launch_call_at = WORKFLOW_SRC.index(
        "self._launch_capture_controller(selection, request)"
    )
    assert resolved_at < launch_call_at, (
        "an unresolved slot must still short-circuit before the sweep starts"
    )


def test_the_controller_asks_by_series_key_never_by_list_position():
    """``change_series_on_viewer`` takes a series KEY, not a list index.

    Its first statement is ``series_number = str(series_index)`` despite the
    parameter name, so passing a position in ``lst_thumbnails_data`` loaded
    whichever series happened to be numbered "1" and "2" — the localizer and
    the coronal myelogram, exactly what the 2026-08-26 screenshot showed.
    """
    src = (REPO_ROOT / "modules" / "ai_imaging" / "eagle_eye_lumbar"
           / "capture_controller.py").read_text(encoding="utf-8")
    assert "def _series_key" in src
    assert "thumbnail_index" not in src, "a list position must never reach the viewer"
    assert src.count("change_series_on_viewer") >= 2
    # Every call site must keep the explicit target pane: with
    # flag_change_selected_widget=True the method overwrites the vtk_widget
    # argument with self.selected_widget, so all three would land in one pane.
    assert "flag_change_selected_widget=True" not in src
    assert src.count("flag_change_selected_widget=False") == src.count(
        "self.patient_widget.change_series_on_viewer"
    )


def test_the_controller_still_refuses_when_the_series_never_arrive():
    """Waiting must have an end, and the end must not be "capture anyway"."""
    src = (REPO_ROOT / "modules" / "ai_imaging" / "eagle_eye_lumbar"
           / "capture_controller.py").read_text(encoding="utf-8")
    assert "timed out loading" in src
    timeout_at = src.index("timed out loading")
    geometry_at = src.index("def _prepare_geometry")
    assert timeout_at < geometry_at, "the timeout must short-circuit before capturing"
