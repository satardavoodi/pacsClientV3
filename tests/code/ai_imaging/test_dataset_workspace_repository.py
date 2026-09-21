"""Synthetic dataset template/case persistence; never uses the PACS database."""
import copy
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.ai_imaging.eagle_eye.datasets.definitions import lumbar_template, validate_template
from modules.ai_imaging.eagle_eye.datasets.repository import DatasetRepository, DatasetError


@pytest.fixture
def repo(tmp_path):
    return DatasetRepository(tmp_path)


def context(uid="1.2.826.0.1.1", patient="SYNTHETIC-001"):
    return {"study_uid": uid, "patient_id": patient, "patient_name": "Synthetic example",
            "modality": "MR", "study_date": "20260913", "source_namespace": "local-pacs"}


def test_template_and_case_reopen_use_separate_objects(repo):
    definition = repo.create_dataset(lumbar_template())
    first = repo.add_case(definition["id"], context())
    second = repo.add_case(definition["id"], context("1.2.826.0.1.2", "SYNTHETIC-002"))
    values = {"L5-S1/disc_extrusion": "present"}
    saved = repo.save_case(first["id"], values, "draft", "", first["revision"])
    assert saved["values"] == values
    assert DatasetRepository(repo.root).get_case(first["id"])["values"] == values
    assert repo.get_case(second["id"])["values"] == {}
    assert repo.list_datasets()[0]["case_count"] == 2
    assert repo.list_cases(definition["id"])[0]["patient_id"]


def test_concurrent_add_is_idempotent_and_preserves_draft(repo):
    definition = repo.create_dataset(lumbar_template())
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: repo.add_case(definition["id"], context()), range(2)))
    assert rows[0]["id"] == rows[1]["id"]
    saved = repo.save_case(rows[0]["id"], {"L4-L5/disc_protrusion": "present"}, "draft", "", 1)
    assert repo.add_case(definition["id"], context())["values"] == saved["values"]


def test_schema_versions_preserve_removed_fields_and_old_cases(repo):
    template = lumbar_template()
    definition = repo.create_dataset(template)
    first = repo.add_case(definition["id"], context())
    updated = copy.deepcopy(template)
    updated["fields"] = [f for f in updated["fields"] if f["id"] != "disc_extrusion"]
    updated["fields"].append({"id": "custom_score", "label": "Custom score", "type": "number",
                              "scope": "case", "required": True, "options": []})
    repo.update_dataset(definition["id"], updated, 1)
    second = repo.add_case(definition["id"], context("1.2.826.0.1.2"))
    assert first["template_version"] == 1 and second["template_version"] == 2
    assert any(f["id"] == "disc_extrusion" for f in repo.get_case(first["id"])["template"]["fields"])
    assert any(f["id"] == "custom_score" for f in second["template"]["fields"])
    saved = repo.save_case(first["id"], {"L5-S1/disc_extrusion": "present"}, "draft", "", 1)
    assert saved["template_version"] == 1


def test_stale_writes_and_schema_updates_are_rejected(repo):
    definition = repo.create_dataset(lumbar_template())
    case = repo.add_case(definition["id"], context())
    repo.save_case(case["id"], {}, "draft", "", 1)
    with pytest.raises(DatasetError, match="changed"):
        repo.save_case(case["id"], {}, "draft", "", 1)
    repo.update_dataset(definition["id"], lumbar_template(), 1)
    with pytest.raises(DatasetError, match="changed"):
        repo.update_dataset(definition["id"], lumbar_template(), 1)


def test_required_and_invalid_values_are_not_silently_accepted(repo):
    template = lumbar_template()
    template["fields"] = [{"id": "score", "label": "Score", "type": "number",
                           "scope": "case", "required": True, "options": []}]
    definition = repo.create_dataset(template)
    case = repo.add_case(definition["id"], context())
    with pytest.raises(DatasetError, match="required"):
        repo.save_case(case["id"], {}, "complete", "Synthetic reviewer", 1)
    for value in (True, float("nan"), float("inf"), "not a number"):
        with pytest.raises(DatasetError):
            repo.save_case(case["id"], {"case/score": value}, "draft", "", 1)
    saved = repo.save_case(case["id"], {"case/score": 0}, "complete", "Synthetic reviewer", 1)
    assert saved["status"] == "complete"
    assert saved["training_eligible"] is False
    with pytest.raises(DatasetError):
        repo.save_case(case["id"], {"case/unknown": "x"}, "draft", "", 2)


def test_mismatched_identity_and_modality_are_rejected(repo):
    definition = repo.create_dataset(lumbar_template())
    case = repo.add_case(definition["id"], context())
    with pytest.raises(DatasetError, match="identity"):
        repo.add_case(definition["id"], context(patient="SYNTHETIC-OTHER"))
    with pytest.raises(DatasetError, match="modality"):
        repo.add_case(definition["id"], dict(context(), modality="CT"))
    with pytest.raises(DatasetError):
        repo.add_case(definition["id"], dict(context(), study_uid=""))
    assert repo.get_case(case["id"])["revision"] == 1


def test_same_study_can_belong_to_two_datasets(repo):
    first = repo.create_dataset(lumbar_template())
    second = repo.create_dataset(dict(lumbar_template(), name="Second collection"))
    assert repo.add_case(first["id"], context())["id"] != repo.add_case(second["id"], context())["id"]


def test_template_validation_rejects_ambiguous_fields():
    template = lumbar_template()
    template["fields"].append(copy.deepcopy(template["fields"][0]))
    with pytest.raises(ValueError):
        validate_template(template)


def test_history_survives_completion_and_later_draft(repo):
    definition = repo.create_dataset(lumbar_template())
    case = repo.add_case(definition["id"], context())
    repo.save_case(case["id"], {"L5-S1/disc_extrusion": "present"}, "complete", "Synthetic reviewer", 1)
    repo.save_case(case["id"], {}, "draft", "", 2)
    history = repo.case_history(case["id"])
    assert [row["revision"] for row in history] == [1, 2, 3]
    assert history[1]["values"]["L5-S1/disc_extrusion"] == "present"
    assert history[2]["values"] == {}
