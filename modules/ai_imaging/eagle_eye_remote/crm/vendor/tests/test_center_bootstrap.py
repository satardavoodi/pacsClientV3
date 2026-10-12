"""Per-centre catalogue discovery and the reviewed LLM-candidate boundary."""

from __future__ import annotations

import json

import pytest

from reception_crm import center_bootstrap as bootstrap


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, _filter):
        return iter(self.rows)


class FakeDatabase:
    def __init__(self, *, empty: bool = False):
        self.collections = {
            "Modality": FakeCollection([] if empty else [
                {
                    "_id": "2", "Modality": "MR", "FullName": "MRI",
                    "PerFullName": "ام آر آی", "Disabled": False,
                },
                {
                    "_id": "9", "Modality": "Mammo", "FullName": "Mammography",
                    "PerFullName": "ماموگرافی", "Disabled": True,
                },
            ]),
            "ServicesGroupInfo": FakeCollection([] if empty else [
                {"_id": "g1", "Modality": 2, "Name": "ستون فقرات"},
            ]),
            "ServicesInfo": FakeCollection([] if empty else [
                {
                    "_id": "s1", "Service": "MRI ناحیه لومبار بدون کنتراست",
                    "Modality": "2", "Group": "g1", "ServiceGroup": "ستون فقرات",
                },
                {
                    "_id": "s2", "Service": "MRI کانال spinal ناحیه لومبر",
                    "Modality": "2", "Group": "g1", "ServiceGroup": "ستون فقرات",
                },
            ]),
        }

    def __getitem__(self, name):
        return self.collections[name]


def candidate_reply(_messages, **kwargs):
    assert kwargs["response_format_json"] is True
    return {
        "provider": "test",
        "usage": {"model": "test-model", "prompt_tokens": 10, "completion_tokens": 20},
        "content": json.dumps({
            "concepts": [{
                "id": "lumbar_spine",
                "label_fa": "ستون فقرات کمری",
                "aliases": ["کمر", "لومبر", "lumbar"],
                "match_terms": ["لومبر", "لومبار"],
                "evidence_services": [
                    "MRI ناحیه لومبار بدون کنتراست",
                    "MRI کانال spinal ناحیه لومبر",
                ],
                "confidence": 0.98,
                "reason_fa": "دو نوشتار برای یک ناحیه آناتومیک در خدمات MRI.",
            }]
        }, ensure_ascii=False),
    }


def test_bootstrap_discovers_this_center_and_keeps_llm_candidates_inactive(tmp_path):
    result = bootstrap.bootstrap_center(
        center="TEST CENTER",
        database=FakeDatabase(),
        database_name="ClinicWebsite",
        output_root=tmp_path,
        chat=candidate_reply,
    )

    generated = json.loads((tmp_path / "center_config.json").read_text(encoding="utf-8"))
    candidates = json.loads(
        (tmp_path / "service_concepts.candidates.json").read_text(encoding="utf-8")
    )
    assert generated["center"] == "TEST CENTER"
    assert generated["counts"]["services"] == 2
    assert generated["service_concepts"] == [], "model output must not become query authority"
    assert candidates["status"] == "review_required"
    assert candidates["concepts"][0]["id"] == "lumbar_spine"
    assert result["llm"]["status"] == "review_required"
    assert "patient" not in json.dumps(generated).lower()
    assert (tmp_path / "center_profile.md").exists()
    catalog = (tmp_path / "service_catalog.csv").read_text(encoding="utf-8-sig")
    assert "service_name" in catalog
    assert "MRI ناحیه لومبار بدون کنتراست" in catalog
    assert "lumbar_spine" in (tmp_path / "center_profile.md").read_text(encoding="utf-8")


def test_explicit_promotion_is_the_only_path_from_candidate_to_active(tmp_path):
    bootstrap.bootstrap_center(
        center="TEST CENTER",
        database=FakeDatabase(),
        database_name="ClinicWebsite",
        output_root=tmp_path,
        chat=candidate_reply,
    )

    result = bootstrap.promote_candidate_concepts(
        ["lumbar_spine"], output_root=tmp_path, center="TEST CENTER"
    )

    active = json.loads((tmp_path / "service_concepts.json").read_text(encoding="utf-8"))
    generated = json.loads((tmp_path / "center_config.json").read_text(encoding="utf-8"))
    assert result["promoted"] == ["lumbar_spine"]
    assert active["concepts"][0]["id"] == "lumbar_spine"
    assert generated["service_concepts"][0]["id"] == "lumbar_spine"


def test_unchanged_catalog_does_not_call_the_llm_again(tmp_path):
    bootstrap.bootstrap_center(
        center="TEST CENTER",
        database=FakeDatabase(),
        database_name="ClinicWebsite",
        output_root=tmp_path,
        chat=candidate_reply,
    )

    def must_not_run(*_args, **_kwargs):
        raise AssertionError("unchanged catalogue should reuse its candidates")

    result = bootstrap.bootstrap_center(
        center="TEST CENTER",
        database=FakeDatabase(),
        database_name="ClinicWebsite",
        output_root=tmp_path,
        chat=must_not_run,
    )
    assert result["llm"]["status"] == "unchanged"


def test_llm_cannot_invent_an_evidence_service():
    payload = {
        "concepts": [{
            "id": "lumbar_spine",
            "label_fa": "کمر",
            "aliases": ["کمر"],
            "match_terms": ["لومبر"],
            "evidence_services": ["MRI service that does not exist"],
            "confidence": 1,
            "reason_fa": "ساختگی",
        }]
    }
    with pytest.raises(bootstrap.ConceptProposalError, match="invented evidence"):
        bootstrap.validate_candidate_concepts(
            payload,
            service_names=["MRI کانال spinal ناحیه لومبر"],
        )


def test_medical_short_alias_is_allowed_but_not_as_a_match_term():
    service_names = ["CT Abdomen"]
    base = {
        "id": "ct_scan",
        "label_fa": "سی تی",
        "aliases": ["CT"],
        "match_terms": ["Abdomen"],
        "evidence_services": service_names,
        "confidence": 1,
        "reason_fa": "مخفف دقیق و رایج",
    }

    validated = bootstrap.validate_candidate_concepts(
        {"concepts": [base]}, service_names=service_names,
    )
    assert validated[0]["aliases"] == ["CT"]

    unsafe_term = dict(base, match_terms=["CT"])
    with pytest.raises(bootstrap.ConceptProposalError, match="unsafe value"):
        bootstrap.validate_candidate_concepts(
            {"concepts": [unsafe_term]}, service_names=service_names,
        )


def test_invalid_llm_candidate_does_not_discard_valid_review_candidates(tmp_path):
    def mixed_reply(_messages, **_kwargs):
        payload = json.loads(candidate_reply([], response_format_json=True)["content"])
        payload["concepts"].append({
            "id": "invented_service",
            "label_fa": "نامعتبر",
            "aliases": ["نامعتبر"],
            "match_terms": ["ساختگی"],
            "evidence_services": ["service that is not in the catalogue"],
            "confidence": 1,
            "reason_fa": "باید رد شود",
        })
        return {
            "provider": "test",
            "usage": {"model": "test-model"},
            "content": json.dumps(payload, ensure_ascii=False),
        }

    result = bootstrap.bootstrap_center(
        center="TEST CENTER",
        database=FakeDatabase(),
        database_name="ClinicWebsite",
        output_root=tmp_path,
        chat=mixed_reply,
    )
    candidates = json.loads(
        (tmp_path / "service_concepts.candidates.json").read_text(encoding="utf-8")
    )
    generated = json.loads((tmp_path / "center_config.json").read_text(encoding="utf-8"))

    assert [row["id"] for row in candidates["concepts"]] == ["lumbar_spine"]
    assert candidates["rejected_candidates"][0]["id"] == "invented_service"
    assert result["llm"]["candidate_count"] == 1
    assert result["llm"]["rejected_count"] == 1
    assert generated["service_concepts"] == []


def test_failed_discovery_preserves_the_last_known_center_config(tmp_path):
    target = tmp_path / "center_config.json"
    target.write_text('{"center":"OLD","marker":"keep"}', encoding="utf-8")

    with pytest.raises(bootstrap.CenterBootstrapError, match="Modality"):
        bootstrap.bootstrap_center(
            center="TEST CENTER",
            database=FakeDatabase(empty=True),
            database_name="ClinicWebsite",
            output_root=tmp_path,
            with_llm=False,
        )

    assert json.loads(target.read_text(encoding="utf-8"))["marker"] == "keep"


def test_active_alias_conflicts_are_rejected():
    with pytest.raises(bootstrap.CenterBootstrapError, match="assigned to both"):
        bootstrap.validate_active_concepts([
            {
                "id": "lumbar_spine", "label_fa": "کمر",
                "aliases": ["کمر"], "match_terms": ["لومبر"],
            },
            {
                "id": "abdomen", "label_fa": "شکم",
                "aliases": ["کمر"], "match_terms": ["شکم"],
            },
        ])
