"""Synthetic Reception template contracts; no live patient data or database."""
import pytest

from modules.EchoMind import normal_templates as nt


def test_reception_dx_is_radiology():
    assert nt.canonical_modality("DX") == "RADIOLOGY"


def test_download_resolves_modality_and_verified_owner():
    from modules.EchoMind.reception_templates import ReceptionTemplates
    calls = []

    def get(path, params=None):
        calls.append((path, params))
        if path.endswith("verify-token"):
            return {"success": True, "user": {"id": "user-a"}}
        if path.endswith("getAll"):
            return [{"_id": "mod-a", "Modality": "MR"}]
        return {"success": True, "data": [{"_id": "sample-a", "Name": "Knee",
                "Html": "<p>No joint effusion.</p>", "Modality": "mod-a",
                "User": "user-a", "Personnel": {"_id": "person-a", "FirstName": "Example"}}],
                "pagination": {"current": 1, "pages": 1, "total": 1}}

    result = ReceptionTemplates("http://example.test", "synthetic", "profile-a", get=get).fetch()
    assert result["records"][0]["modality"] == "MRI"
    assert result["records"][0]["reception"]["owner_id"] == "user-a"
    assert result["user_id"] == "user-a"
    assert result["records"][0]["text"] == "No joint effusion."
    assert len(calls) == 3


def test_import_keeps_personal_edits_and_separates_sources(tmp_path, monkeypatch):
    from modules.EchoMind.reception_templates import import_selected
    monkeypatch.setattr(nt, "library_path", lambda: str(tmp_path / "library.json"))
    record, _ = nt.normalize_record({"Name": "Knee", "Html": "No joint effusion."})
    record.update(id="remote-a", reception={"scope": "a", "source_id": "one"})
    assert import_selected(record)[1] == 1
    saved = nt.load_library()
    assert saved[0]["reception"]["scope"] == "a"
    saved[0]["name"] = "My edited name"
    assert nt.save_library(saved)
    assert import_selected(record)[1] == 0
    assert nt.load_library()[0]["name"] == "My edited name"


def test_template_prompt_has_no_uncovered_normal_escape():
    from modules.EchoMind.viewer_chat.openai_reporter import build_report_system_prompt
    for modality in nt.CANONICAL_MODALITIES:
        prompt = build_report_system_prompt(modality, "No joint effusion.")
        assert "any normal content the template does" not in prompt
        assert "TEMPLATE NORMALS ARE EXHAUSTIVE" in prompt


def test_invalid_pagination_fails_instead_of_partial_success():
    from modules.EchoMind.reception_templates import ReceptionTemplates, TemplateError
    def get(path, params=None):
        if path.endswith("verify-token"):
            return {"user": {"id": "one"}}
        if path.endswith("getAll"):
            return []
        return {"success": True, "data": [], "pagination": {"pages": 10000, "total": 99999}}
    with pytest.raises(TemplateError):
        ReceptionTemplates("http://example.test", "synthetic", "a", get=get).fetch()


def test_profile_and_body_revision_have_distinct_copy_ids():
    from modules.EchoMind.reception_templates import ReceptionTemplates
    body = "No joint effusion."
    def get(path, params=None):
        if path.endswith("verify-token"):
            return {"user": {"id": "one"}}
        if path.endswith("getAll"):
            return [{"_id": "mr", "Modality": "MR"}]
        return {"success": True, "data": [{"_id": "one", "Name": "Knee", "Html": body, "Modality": "mr"}],
                "pagination": {"pages": 1, "total": 1}}
    def record(profile):
        return ReceptionTemplates("http://example.test", "synthetic", profile, get=get).fetch()["records"][0]
    first = record("one")
    assert first["id"] != record("two")["id"]
    body = "Ligaments are intact."
    assert first["id"] != record("one")["id"]


def test_multiple_pages_and_unknown_modality_are_not_guessed():
    from modules.EchoMind.reception_templates import ReceptionTemplates
    pages = []
    def get(path, params=None):
        if path.endswith("verify-token"):
            return {"user": {"id": "one"}}
        if path.endswith("getAll"):
            return []
        page = params["page"]
        pages.append(page)
        return {"success": True, "data": [{"_id": str(page), "Name": "MRI name", "Html": "Normal.", "Modality": "unknown"}],
                "pagination": {"pages": 2, "total": 2}}
    result = ReceptionTemplates("http://example.test", "synthetic", "one", get=get).fetch()
    assert pages == [1, 2]
    assert all(r["modality"] == "" for r in result["records"])


def test_cancelled_download_makes_no_request():
    from modules.EchoMind.reception_templates import ReceptionTemplates, TemplateError
    def never(*args):
        pytest.fail("Cancelled download must not call Reception")
    with pytest.raises(TemplateError, match="cancelled"):
        ReceptionTemplates("http://example.test", "synthetic", "one", get=never, cancelled=lambda: True).fetch()


def test_unknown_remote_modality_stays_unknown_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(nt, "library_path", lambda: str(tmp_path / "library.json"))
    record, _ = nt.normalize_record({"Name": "MRI name", "Html": "Normal."})
    record.update(modality="", reception={"source_id": "one", "scope": "a"})
    assert nt.save_library([record])
    assert nt.load_library()[0]["modality"] == ""


def test_verified_owner_and_personnel_priority():
    from modules.EchoMind.reception_templates import ordered_records
    records = [
        {"name": "A other", "modality": "MRI", "reception": {"owner_id": "other"}},
        {"name": "Z assigned", "modality": "MRI", "reception": {"personnel_id": "person"}},
        {"name": "B own", "modality": "MRI", "reception": {"owner_id": "me"}},
    ]
    assert [r["name"] for r in ordered_records(records, "me", "person", "MRI")] == ["B own", "Z assigned", "A other"]
    assert ordered_records(records, "", "", "MRI")[0]["name"] == "A other"
