"""Editing a prompt must be reversible, and must actually reach the model.

The prompt store layers a writable override directory over the packaged
defaults. Three things have to hold for that to be safe to put in front of an
administrator:

* the packaged text is never modified, so "restore" always works;
* what the interpreter reads is what the screen shows;
* the editable list follows the mode registry, so a future mode appears on its
  own — the promise ``core/modes.py`` already makes to the mobile client.
"""

from __future__ import annotations

import json

import pytest

from reception_crm.core import modes
from reception_crm.llm import interpreter, prompt_store


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Point the override directory at a temp dir, never the real APPDATA."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield tmp_path


# --------------------------------------------------------------------------- #
# the catalog
# --------------------------------------------------------------------------- #
def test_every_mode_prompt_is_editable():
    filenames = {item.filename for item in prompt_store.catalog()}
    for mode in modes.all_modes():
        assert mode.prompt_file in filenames, f"mode {mode.id} has no editable prompt"


def test_the_base_prompt_comes_first():
    catalog = prompt_store.catalog()
    assert catalog[0].key == "base"


def test_every_entry_is_described_in_persian():
    persian = set("ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی")
    for item in prompt_store.catalog():
        assert persian & set(item.title_fa), f"{item.key} title is not Persian"
        assert persian & set(item.description_fa), f"{item.key} description is not Persian"


def test_keys_are_unique():
    keys = [item.key for item in prompt_store.catalog()]
    assert len(keys) == len(set(keys))


def test_packaged_defaults_all_exist():
    """A prompt in the catalog with no shipped file would be an empty editor."""
    for item in prompt_store.catalog():
        assert item.packaged_path.is_file(), f"{item.filename} is missing from the package"


def test_lookup_by_key_and_filename():
    item = prompt_store.by_key("mode_report")
    assert item is not None
    assert prompt_store.by_filename(item.filename) is item or prompt_store.by_filename(item.filename).key == item.key
    assert prompt_store.by_key("no-such-prompt") is None


# --------------------------------------------------------------------------- #
# override, read, restore
# --------------------------------------------------------------------------- #
def test_reads_the_packaged_default_when_untouched():
    assert prompt_store.read("mode_report.md") == prompt_store.read_default("mode_report.md")
    assert not prompt_store.is_overridden("mode_report.md")
    assert not prompt_store.differs_from_default("mode_report.md")


def test_an_override_shadows_the_default():
    prompt_store.write("mode_report.md", "CUSTOM REPORTING PROMPT")
    assert prompt_store.read("mode_report.md") == "CUSTOM REPORTING PROMPT"
    assert prompt_store.is_overridden("mode_report.md")
    assert prompt_store.differs_from_default("mode_report.md")


def test_the_packaged_file_is_never_modified():
    before = prompt_store.read_default("mode_report.md")
    prompt_store.write("mode_report.md", "CUSTOM")
    assert prompt_store.read_default("mode_report.md") == before


def test_restore_brings_the_default_back():
    prompt_store.write("mode_report.md", "CUSTOM")
    prompt_store.restore("mode_report.md")
    assert not prompt_store.is_overridden("mode_report.md")
    assert prompt_store.read("mode_report.md") == prompt_store.read_default("mode_report.md")


def test_restore_is_safe_when_nothing_was_overridden():
    prompt_store.restore("mode_report.md")  # must not raise


def test_saving_the_default_text_clears_the_override():
    """Opening a prompt and pressing save must not badge it as customised."""
    default = prompt_store.read_default("mode_analysis.md")
    prompt_store.write("mode_analysis.md", default)
    assert not prompt_store.is_overridden("mode_analysis.md")


def test_restore_all_reports_how_many_it_removed():
    prompt_store.write("mode_report.md", "A")
    prompt_store.write("mode_analysis.md", "B")
    assert prompt_store.restore_all() == 2
    assert prompt_store.restore_all() == 0


def test_unknown_prompt_cannot_be_written():
    with pytest.raises(prompt_store.PromptError):
        prompt_store.write("../evil.md", "x")


# --------------------------------------------------------------------------- #
# the agent actually uses the override
# --------------------------------------------------------------------------- #
def test_the_interpreter_reads_the_edited_mode_prompt():
    prompt_store.write("mode_report.md", "SENTINEL MODE TEXT")
    assert interpreter.load_mode_prompt(modes.REPORT) == "SENTINEL MODE TEXT"


def test_the_interpreter_reads_the_edited_base_prompt():
    prompt_store.write("crm_command_interpretation.md", "SENTINEL BASE TEXT")
    assert interpreter.load_prompt() == "SENTINEL BASE TEXT"


def test_the_interpreter_reads_the_edited_analysis_prompt():
    prompt_store.write("crm_data_analysis.md", "SENTINEL ANALYSIS TEXT")
    assert interpreter.load_analysis_prompt() == "SENTINEL ANALYSIS TEXT"


def test_the_base_writer_defers_formatting_to_the_mode_contract():
    """The base prompt used to forbid headings while Analysis required them.

    A stochastic model could obey either instruction, so the same cashier
    question alternated between a scan-friendly answer and a wall of prose.
    """
    text = prompt_store.read_default("crm_data_analysis.md")
    assert "Follow the mode-specific answer contract appended below" in text
    assert "no markdown headings" not in text


def test_analysis_answer_contract_is_scannable_and_cashier_safe():
    """Hold the user-visible contract, not a model's lucky sample response."""
    text = prompt_store.read_default("answer_analysis.md")

    headings = [
        "## وضعیت کلی",
        "## اعداد کلیدی",
        "## تطبیق و مغایرت‌ها",
        "## نیازمند بررسی",
        "## جمع‌بندی",
    ]
    assert all(heading in text for heading in headings)
    assert [text.index(heading) for heading in headings] == sorted(
        text.index(heading) for heading in headings
    )
    assert "One bullet = one claim" in text
    assert "one labelled bullet for each relevant quantity" in text
    assert "Insurance credit" in text
    assert "money physically" in text and "received by the cashier" in text
    assert "classification mismatch or a real shortage/surplus" in text
    assert "this is only a classification mismatch" in text


def test_staff_activity_answer_contract_requires_the_complete_roster():
    text = prompt_store.read_default("answer_analysis.md")

    assert "Exactly one compact bullet for every matching named row" in text
    assert "never stop after the first few people" in text
    assert "events`/`count` into reports" in text
    assert "transaction-only account does not belong" in text


def test_analysis_answer_contract_reaches_the_answer_writing_call():
    captured = {}

    def chat(messages, response_format_json=False):
        captured["messages"] = messages
        captured["json"] = response_format_json
        return {"content": "پاسخ"}

    result = interpreter.summarize(
        "فعالیت صندوق امروز را تحلیل کن",
        "cashier-report",
        {"totals": {"net": 10}},
        chat=chat,
        mode=modes.ANALYSIS,
    )

    system = captured["messages"][0]["content"]
    assert result == "پاسخ"
    assert captured["json"] is False
    assert system.index("# Reception data analysis") < system.index(
        "# HOW TO WRITE THE ANSWER — Analysis mode"
    )
    assert "## Cashier analysis has a fixed visual order" in system


def test_restoring_returns_the_agent_to_the_shipped_prompt():
    prompt_store.write("mode_report.md", "SENTINEL")
    prompt_store.restore("mode_report.md")
    assert "SENTINEL" not in interpreter.load_mode_prompt(modes.REPORT)


# --------------------------------------------------------------------------- #
# export / import
# --------------------------------------------------------------------------- #
def test_export_captures_every_prompt(tmp_path):
    target = prompt_store.export_all(tmp_path / "prompts.json")
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["kind"] == "reception-crm-prompts"
    assert len(payload["prompts"]) == len(prompt_store.catalog())


def test_export_marks_which_ones_were_customised(tmp_path):
    prompt_store.write("mode_report.md", "CUSTOM")
    payload = json.loads(prompt_store.export_all(tmp_path / "p.json").read_text(encoding="utf-8"))
    by_key = {entry["key"]: entry for entry in payload["prompts"]}
    assert by_key["mode_report"]["customised"] is True
    assert by_key["mode_analysis"]["customised"] is False


def test_round_trip_between_machines(tmp_path):
    prompt_store.write("mode_report.md", "TUNED AT HEAD OFFICE")
    exported = prompt_store.export_all(tmp_path / "p.json")

    prompt_store.restore_all()
    assert not prompt_store.differs_from_default("mode_report.md")

    applied = prompt_store.import_all(exported)
    assert applied  # something changed
    assert prompt_store.read("mode_report.md") == "TUNED AT HEAD OFFICE"


def test_import_reports_nothing_when_already_identical(tmp_path):
    exported = prompt_store.export_all(tmp_path / "p.json")
    assert prompt_store.import_all(exported) == []


def test_import_skips_prompts_this_build_does_not_have(tmp_path):
    """A file from a newer build may name a mode this one lacks."""
    payload = {
        "version": 1,
        "kind": "reception-crm-prompts",
        "prompts": [
            {"key": "mode_report", "filename": "mode_report.md", "text": "KEPT"},
            {"key": "mode_from_the_future", "filename": "mode_future.md", "text": "IGNORED"},
        ],
    }
    path = tmp_path / "p.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    applied = prompt_store.import_all(path)
    assert len(applied) == 1
    assert prompt_store.read("mode_report.md") == "KEPT"
    assert not (prompt_store.override_dir() / "mode_future.md").exists()


def test_import_rejects_a_file_that_is_not_ours(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"kind": "something-else", "prompts": []}), encoding="utf-8")
    with pytest.raises(prompt_store.PromptError):
        prompt_store.import_all(path)


def test_import_rejects_unreadable_json(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(prompt_store.PromptError):
        prompt_store.import_all(path)


def test_import_ignores_blank_prompt_text(tmp_path):
    """An empty prompt would silently lobotomise the agent."""
    payload = {
        "kind": "reception-crm-prompts",
        "prompts": [{"key": "mode_report", "filename": "mode_report.md", "text": "   "}],
    }
    path = tmp_path / "p.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert prompt_store.import_all(path) == []
    assert not prompt_store.is_overridden("mode_report.md")
