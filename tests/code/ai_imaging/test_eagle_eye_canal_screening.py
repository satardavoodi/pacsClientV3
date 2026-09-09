"""Canal-only decision and optional MR-myelography regression guards."""

from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, MRImageStorage, generate_uid

from modules.ai_imaging.eagle_eye_lumbar import atomic_pipeline, anatomy_cards
from modules.ai_imaging.eagle_eye_lumbar.llm_package import AnalysisPackage, PackagedImage
from test_eagle_eye_anatomy_gate import _atlas_package, _anatomy_map
from test_eagle_eye_neural_contract import compartment_rows


def _request():
    return next(r for r in atomic_pipeline.SCREENING_REQUESTS if r.key == "canal_neural")


def _current_anatomy_map():
    mapping = deepcopy(_anatomy_map())
    mapping["schema_version"] = anatomy_cards.ANATOMY_CARD_SCHEMA_VERSION
    return mapping


def _observation(level="L4-L5", group="axial-group-05"):
    return {
        "level": level, "axial_group_id": group, "assessment": "normal",
        "caliber": "preserved", "csf_visibility": "preserved",
        "visual_basis": "minor_impression_only",
        "myelographic_correlation": "not_available",
        "axial_tile_ids": ["axial-series-a:0013"],
        "reason": "Small ventral indentation with preserved overall thecal sac caliber.",
    }


def _outcome(observation, findings=()):
    return {"structured": {
        "schema_version": atomic_pipeline.ATOMIC_SCREENING_SCHEMA_VERSION,
        "screening_request": "canal_neural", "findings": list(findings),
        "central_canal_observations": [observation],
        "compartment_observations": compartment_rows("canal_neural", [observation], findings),
    }}


def test_minor_impression_cannot_be_forwarded_as_abnormal_central_canal():
    finding = {"structure": "central_canal", "level": "L4-L5",
               "assessment": "abnormal", "laterality": "not_applicable"}
    errors = atomic_pipeline.screening_outcome_errors(
        _request(), _outcome(_observation(), [finding]))
    assert "canal_observation_finding_conflict:L4-L5" in errors


def test_preserved_csf_alone_does_not_veto_reduced_caliber_or_other_pathology():
    observation = _observation()
    observation.update(assessment="abnormal", caliber="reduced",
                       visual_basis="reproducible_caliber_reduction")
    finding = {"structure": "central_canal", "level": "L4-L5",
               "assessment": "abnormal", "laterality": "not_applicable"}
    assert atomic_pipeline.screening_outcome_errors(
        _request(), _outcome(observation, [finding])) == []
    observation.update(caliber="preserved", visual_basis="other_intracanal_abnormality")
    assert atomic_pipeline.screening_outcome_errors(
        _request(), _outcome(observation, [finding])) == []


def test_canal_observation_must_cover_every_group_and_cite_its_own_axial(tmp_path):
    package = anatomy_cards.prepare_anatomy_cards(_atlas_package(tmp_path), _current_anatomy_map())
    package = anatomy_cards.screening_package_for(package, "canal_neural")
    observation = _observation()
    observation["axial_tile_ids"] = ["axial-series-a:0016"]
    errors = atomic_pipeline.screening_outcome_errors(
        _request(), _outcome(observation), package=package)
    assert "canal_observation_level_coverage" in errors
    assert "canal_observation_wrong_group_evidence:L4-L5" in errors


def test_lateral_recess_positive_does_not_require_central_positive():
    finding = {"structure": "lateral_recess", "level": "L4-L5",
               "assessment": "abnormal", "laterality": "right"}
    assert atomic_pipeline.screening_outcome_errors(
        _request(), _outcome(_observation(), [finding])) == []


def test_included_myelography_must_be_acknowledged_in_the_canal_audit(tmp_path):
    path = tmp_path / "card.png"
    path.write_bytes(b"synthetic")
    package = AnalysisPackage(
        tmp_path, "session", "lumbar_mri", None, "header",
        [PackagedImage(path, "canal", "anatomy-card-canal_neural", 1,
                       card_payload={"anatomy_card": {"myelographic_context": {
                           "status": "included",
                       }}})],
    )
    errors = atomic_pipeline.screening_outcome_errors(
        _request(), _outcome(_observation()), package=package)
    assert "canal_observation_myelography_status:L4-L5" in errors


def test_canal_prompt_has_specificity_and_observation_contract_only_for_canal():
    base = SimpleNamespace(model_feature="screening", model_default="test")
    prompt = atomic_pipeline.screening_stage_for(base, _request()).text
    assert "central_canal_observations" in prompt
    assert "minor impression" in prompt.lower()
    assert "myelographic" in prompt.lower()
    for request in atomic_pipeline.SCREENING_REQUESTS:
        if request.key != "canal_neural":
            assert "central_canal_observations" not in atomic_pipeline.screening_stage_for(base, request).text


def _myelo(tmp_path, study_uid, series_uid, *, actual_study=None):
    directory = tmp_path / "myelo"
    directory.mkdir(exist_ok=True)
    meta = FileMetaDataset()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    meta.MediaStorageSOPClassUID = MRImageStorage
    meta.MediaStorageSOPInstanceUID = generate_uid()
    ds = FileDataset(str(directory / "image.dcm"), {}, file_meta=meta, preamble=b"\0" * 128)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = MRImageStorage
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = actual_study or study_uid
    ds.SeriesInstanceUID = series_uid
    ds.Modality = "MR"
    ds.SeriesDescription = "T2 MR myelography"
    ds.EchoTime = 1000
    ds.Rows, ds.Columns = 96, 64
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 0
    ds.PixelData = np.arange(96 * 64, dtype=np.uint16).reshape(96, 64).tobytes()
    ds.save_as(ds.filename, write_like_original=False)
    return {"series_path": str(directory), "series_uid": series_uid,
            "plane": "coronal", "selection_basis": "explicit_mr_myelography_metadata"}


def test_myelography_is_canal_only_context_not_a_localization_tile(tmp_path):
    atlas = _atlas_package(tmp_path)
    baseline = anatomy_cards.prepare_anatomy_cards(atlas, _current_anatomy_map())
    original = {i.session: i.path.read_bytes() for i in baseline.images}
    atlas.study_instance_uid = generate_uid()
    atlas.source_series["canal_myelographic_01"] = _myelo(
        tmp_path, atlas.study_instance_uid, generate_uid())
    cards = anatomy_cards.prepare_anatomy_cards(atlas, _current_anatomy_map())
    for image in cards.images:
        if image.session != "anatomy-card-canal_neural":
            assert image.path.read_bytes() == original[image.session]
            assert "myelographic_context" not in image.card_payload["anatomy_card"]
    canal = anatomy_cards.screening_package_for(cards, "canal_neural")
    metadata = canal.images[0].card_payload["anatomy_card"]
    context = metadata["myelographic_context"]
    assert context["status"] == "included"
    assert len(context["images"]) == 1
    assert context["images"][0]["localization_allowed"] is False
    private_sources = json.loads(canal.images[0].path.with_name(
        "canal_context_sources.local.json").read_text(encoding="utf-8"))
    selected = private_sources["selected_images"][0]
    assert selected["source_file"].endswith("image.dcm")
    assert selected["source_frame_index"] == 0
    assert selected["source_key"] == context["images"][0]["source_key"]
    assert "source_file" not in json.dumps(context)
    assert selected["series_uid"] not in json.dumps(context)
    assert all(t["role"] != "myelographic_context" for t in canal.evidence_audit["pages"][0]["tiles"])
    assert metadata["group_integrity"]["status"] == "validated"
    assert len(canal.images) == 1


def test_wrong_study_myelogram_is_excluded_with_explicit_status(tmp_path):
    atlas = _atlas_package(tmp_path)
    atlas.study_instance_uid = generate_uid()
    atlas.source_series["canal_myelographic_01"] = _myelo(
        tmp_path, atlas.study_instance_uid, generate_uid(), actual_study=generate_uid())
    cards = anatomy_cards.prepare_anatomy_cards(atlas, _current_anatomy_map())
    canal = anatomy_cards.screening_package_for(cards, "canal_neural")
    context = canal.images[0].card_payload["anatomy_card"]["myelographic_context"]
    assert context["status"] == "unavailable"
    assert "identity_mismatch" in context["warnings"]
    assert context["images"] == []


def test_myelography_selection_is_bounded_and_does_not_guess_from_t2_name():
    from modules.ai_imaging.eagle_eye_lumbar.canal_evidence import select_context_sources
    def candidate(name, te=90, plane="sagittal"):
        return SimpleNamespace(series_description=name, protocol_name="", sequence_name="",
                               echo_time=te, modality="MR", plane=plane,
                               series_path="synthetic", series_uid=name, slice_count=1)
    sources = select_context_sources([
        candidate("T2 sagittal"), candidate("T2 myelo", 1000),
        candidate("T2 myelo cor", 1000, "coronal"), candidate("extra myelo", 1000),
    ])
    assert len(sources) == 2
    assert all(value["selection_basis"] == "explicit_mr_myelography_metadata" for value in sources.values())
