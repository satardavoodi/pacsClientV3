"""Guard: the physician's Normal Template library (2026-08-01).

Before this, templates lived in a Python list on one widget: re-uploaded from a
JSON file on EVERY launch, unsearchable, unrenameable, undeletable, and with no
metadata to filter by. A file whose entries were malformed imported silently
with the bad ones dropped.

`modules/EchoMind/normal_templates.py` is the library behind the tab. It is
PURE stdlib on purpose — that is what lets all of this run offscreen, and it is
why the UI can change without any of these rules moving.

The compatibility promise these tests exist to keep: **a template file the
physician authored before today must import with no warning and no edit.**
"""

import json

import pytest

from modules.EchoMind import normal_templates as nt

LEGACY_FILE = json.dumps([
    {"Name": "12 - MRI Knee Right",
     "Html": "<p>Both menisci demonstrate normal morphology and signal intensity.</p>"
             "<p>The ACL and PCL are intact.</p>"},
    {"Name": "CT Abdomen and Pelvis", "Html": "<p>Liver: normal size and attenuation.</p>"},
    {"Name": "Thyroid US", "Html": "Normal thyroid."},
])

EXTENDED_FILE = json.dumps({"templates": [{
    "Name": "MRI Knee — Left",
    "Number": "7",
    "Modality": "mr",
    "BodyRegion": "Knee",
    "ExamType": "Non-contrast",
    "Sections": [
        {"Title": "Menisci", "Normal": "Both menisci are normal."},
        {"Title": "Ligaments", "Normal": "ACL and PCL intact."},
    ],
    "Impression": "Normal MRI of the left knee.",
}]})


@pytest.fixture
def library(tmp_path, monkeypatch):
    path = tmp_path / "library.json"
    monkeypatch.setattr(nt, "library_path", lambda: str(path))
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 1. Backward compatibility — the promise
# ─────────────────────────────────────────────────────────────────────────────

def test_a_legacy_name_html_file_imports_cleanly():
    records, problems = nt.parse_templates(LEGACY_FILE, source_file="mine.json")
    assert problems == [], f"a legacy file must import with no complaints: {problems}"
    assert [r["name"] for r in records] == [
        "12 - MRI Knee Right", "CT Abdomen and Pelvis", "Thyroid US",
    ]


def test_a_legacy_template_reaches_the_model_exactly_as_before():
    """The body is the template. No header, no metadata, no reflow."""
    records, _ = nt.parse_templates(LEGACY_FILE)
    body = nt.template_body_text(records[0])
    assert body == (
        "Both menisci demonstrate normal morphology and signal intensity.\n"
        "The ACL and PCL are intact."
    )


@pytest.mark.parametrize("wrapper", ["templates", "items", "data", "reports"])
def test_wrapped_payloads_are_accepted(wrapper):
    payload = json.dumps({wrapper: [{"Name": "X", "Html": "<p>ok</p>"}]})
    records, problems = nt.parse_templates(payload)
    assert [r["name"] for r in records] == ["X"] and problems == []


def test_a_single_template_object_is_accepted():
    records, problems = nt.parse_templates(json.dumps({"Name": "One", "Html": "ok"}))
    assert [r["name"] for r in records] == ["One"] and problems == []


def test_python_literal_single_quotes_still_load():
    """Some shipped template files use single quotes. `ast.literal_eval` takes
    LITERALS only — it cannot execute anything from the file."""
    records, _ = nt.parse_templates("[{'Name': 'Legacy', 'Html': 'body'}]")
    assert [r["name"] for r in records] == ["Legacy"]


# ─────────────────────────────────────────────────────────────────────────────
# 2. Validation is REPORTED, never silent
# ─────────────────────────────────────────────────────────────────────────────

def test_every_unusable_entry_is_named():
    payload = json.dumps([
        {"Name": "Good", "Html": "<p>fine</p>"},
        {"Name": "", "Html": "<p>x</p>"},
        {"Html": "<p>no name</p>"},
        {"Name": "Empty body", "Html": "<p><br></p>"},
        "not an object",
    ])
    records, problems = nt.parse_templates(payload)
    assert [r["name"] for r in records] == ["Good"]
    assert len(problems) == 4, "a dropped entry must be reported, not swallowed"
    joined = " ".join(problems)
    assert "Empty body" in joined, "the problem should name the template it is about"
    assert "entry #5" in joined, "the problem should say WHERE in the file"


def test_broken_json_reports_why():
    records, problems = nt.parse_templates('{"Name": "x", ')
    assert records == []
    assert problems and "Not valid JSON" in problems[0]


def test_a_non_list_payload_is_explained():
    records, problems = nt.parse_templates("[1, 2, 3]")
    assert records == []
    assert len(problems) == 3


def test_the_import_report_tells_the_physician_what_happened():
    from modules.EchoMind.viewer_chat.normal_template_dialog import import_report

    msg = import_report(3, ["entry #2: no \"Name\"."], ["\"A\" is already in your library — skipped."])
    assert "Imported 3 templates" in msg
    assert "already in your library" in msg
    assert "1 entry could not be used" in msg
    assert "no \"Name\"" in msg
    assert "No new templates" in import_report(0, [], [])


# ─────────────────────────────────────────────────────────────────────────────
# 3. Metadata — declared wins, inference only fills a gap
# ─────────────────────────────────────────────────────────────────────────────

def test_declared_metadata_is_never_overwritten_by_a_guess():
    records, _ = nt.parse_templates(EXTENDED_FILE)
    rec = records[0]
    assert rec["modality"] == "MRI" and rec["modality_inferred"] is False
    assert rec["body_region"] == "Knee" and rec["body_region_inferred"] is False
    assert rec["number"] == "7" and rec["exam_type"] == "Non-contrast"


def test_metadata_is_inferred_from_the_name_when_absent_and_flagged_as_such():
    records, _ = nt.parse_templates(LEGACY_FILE)
    knee = records[0]
    assert knee["modality"] == "MRI" and knee["modality_inferred"] is True
    assert knee["body_region"] == "Knee" and knee["body_region_inferred"] is True
    assert knee["number"] == "12"


@pytest.mark.parametrize("name,expected", [
    ("CT Chest", "CT"), ("MR Brain", "MRI"), ("Thyroid US", "SONOGRAPHY"),
    ("Chest X-ray", "RADIOLOGY"), ("Mammography Screening", "MAMOGRAPHY"),
    ("Bilateral Mammogram", "MAMOGRAPHY"), ("DEXA Spine", "RADIOLOGY"),
    ("Knee", ""),
])
def test_modality_inference(name, expected):
    assert nt.infer_modality(name) == expected


def test_modality_inference_does_not_match_inside_a_word():
    """'us' must not fire inside 'sinus' — a wrong guess hides a template
    behind a filter the physician did not expect to be filtering."""
    assert nt.infer_modality("Paranasal sinus study") == ""


@pytest.mark.parametrize("name,expected", [
    ("12 - MRI Knee", "12"), ("MRI Knee #12", "12"), ("MRI Knee (12)", "12"),
    ("T-014 Chest", "T-014"), ("MRI Knee 12", "12"), ("MRI Knee", ""),
])
def test_number_extraction(name, expected):
    assert nt.extract_number(name) == expected


@pytest.mark.parametrize("declared,canon", [
    ("mr", "MRI"), ("MRI", "MRI"), ("ultrasound", "SONOGRAPHY"),
    ("mamography", "MAMOGRAPHY"), ("x-ray", "RADIOLOGY"), ("PET", ""),
])
def test_declared_modality_is_normalised_to_the_ui_vocabulary(declared, canon):
    assert nt.canonical_modality(declared) == canon


# ─────────────────────────────────────────────────────────────────────────────
# 4. Search — the point of the whole exercise
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def records():
    a, _ = nt.parse_templates(LEGACY_FILE)
    b, _ = nt.parse_templates(EXTENDED_FILE)
    return a + b


def test_search_by_name(records):
    assert [r["name"] for r in nt.search_templates(records, "knee")] == [
        "12 - MRI Knee Right", "MRI Knee — Left",
    ]


def test_search_by_number(records):
    """A physician who numbers their templates types the number."""
    assert [r["name"] for r in nt.search_templates(records, "12")] == ["12 - MRI Knee Right"]
    assert [r["name"] for r in nt.search_templates(records, "7")] == ["MRI Knee — Left"]


def test_search_by_modality_filter(records):
    got = nt.search_templates(records, "", modality="MRI")
    assert {r["name"] for r in got} == {"12 - MRI Knee Right", "MRI Knee — Left"}


def test_search_by_body_region_filter(records):
    assert {r["name"] for r in nt.search_templates(records, "", body_region="Knee")} == {
        "12 - MRI Knee Right", "MRI Knee — Left",
    }


def test_search_terms_are_ANDed(records):
    assert [r["name"] for r in nt.search_templates(records, "mri left")] == ["MRI Knee — Left"]


def test_search_is_case_insensitive(records):
    assert nt.search_templates(records, "KNEE") == nt.search_templates(records, "knee")


def test_empty_query_returns_everything(records):
    assert len(nt.search_templates(records, "")) == len(records)


def test_filter_vocabularies_come_from_the_library(records):
    assert nt.available_modalities(records) == ["CT", "MRI", "SONOGRAPHY"]
    assert "Knee" in nt.available_body_regions(records)


def test_display_label_carries_number_modality_and_region(records):
    assert nt.display_label(records[0]) == "#12 · 12 - MRI Knee Right · MRI · Knee"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Structure reaches the model when the template has it
# ─────────────────────────────────────────────────────────────────────────────

def test_sections_are_rendered_with_their_titles():
    records, _ = nt.parse_templates(EXTENDED_FILE)
    body = nt.template_body_text(records[0])
    assert body == (
        "Menisci:\nBoth menisci are normal.\n\n"
        "Ligaments:\nACL and PCL intact.\n\n"
        "Impression:\nNormal MRI of the left knee."
    )


def test_no_metadata_is_smuggled_into_the_template_text():
    """What the physician sees in the editor is what the model receives."""
    records, _ = nt.parse_templates(EXTENDED_FILE)
    body = nt.template_body_text(records[0])
    for leak in ("Modality:", "MRI Knee — Left", "#7", "Non-contrast", "Body region"):
        assert leak not in body, f"metadata leaked into the prompt text: {leak!r}"


def test_html_to_text_keeps_the_line_structure():
    html = "<p>Line one.</p><ul><li>Bullet</li></ul><p>Line&nbsp;two &amp; more.</p>"
    assert nt.html_to_text(html) == "Line one.\n• Bullet\nLine two & more."


def test_html_to_text_drops_style_blocks():
    """Qt's toHtml() ships a whole <style> block; none of it is clinical."""
    html = "<html><head><style>p { color: red; }</style></head><body><p>Liver normal.</p></body></html>"
    assert nt.html_to_text(html) == "Liver normal."


# ─────────────────────────────────────────────────────────────────────────────
# 6. Persistence — templates survive a restart
# ─────────────────────────────────────────────────────────────────────────────

def test_the_library_round_trips(library, records):
    assert nt.save_library(records)
    back = nt.load_library()
    assert [r["name"] for r in back] == [r["name"] for r in records]
    assert [r["id"] for r in back] == [r["id"] for r in records], "ids must be stable"
    assert nt.template_body_text(back[0]) == nt.template_body_text(records[0])


def test_a_missing_library_is_simply_empty(library):
    assert nt.load_library() == []


def test_a_corrupt_library_never_raises(library):
    library.write_text("{ this is not json", encoding="utf-8")
    assert nt.load_library() == []


def test_the_library_is_written_atomically(library, records, monkeypatch):
    """os.replace, never shutil.move — the project has been bitten by both the
    non-atomic fallback and Windows' rename-onto-existing failure."""
    import modules.EchoMind.normal_templates as mod
    calls = []
    real_replace = mod.os.replace
    monkeypatch.setattr(mod.os, "replace", lambda a, b: (calls.append((a, b)), real_replace(a, b))[1])
    nt.save_library(records)
    assert calls and calls[0][0].endswith(".part")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Merge / rename / delete
# ─────────────────────────────────────────────────────────────────────────────

def test_reimporting_the_same_file_adds_nothing(records):
    merged, notes, added = nt.merge_into_library(records, list(records))
    assert added == 0 and len(merged) == len(records)
    assert all("already in your library" in n for n in notes)


def test_a_name_collision_never_overwrites_a_template(records):
    incoming = dict(records[0])
    incoming["text"] = "COMPLETELY DIFFERENT"
    incoming["html"] = "COMPLETELY DIFFERENT"
    incoming["sections"] = []
    merged, notes, added = nt.merge_into_library(records, [incoming])
    assert added == 1
    names = [r["name"] for r in merged]
    assert "12 - MRI Knee Right" in names and "12 - MRI Knee Right (2)" in names
    assert any("imported as" in n for n in notes)
    original = nt.find_by_id(merged, records[0]["id"])
    assert "Both menisci" in nt.template_body_text(original), "the original was overwritten"


def test_rename_and_retag_clears_the_inferred_flags(records):
    out = nt.update_record(records, records[0]["id"], name="Knee protocol A", modality="ct")
    rec = nt.find_by_id(out, records[0]["id"])
    assert rec["name"] == "Knee protocol A"
    assert rec["modality"] == "CT" and rec["modality_inferred"] is False


def test_update_ignores_fields_it_does_not_own(records):
    out = nt.update_record(records, records[0]["id"], html="<p>hacked</p>", id="other")
    rec = nt.find_by_id(out, records[0]["id"])
    assert rec is not None, "the id must not be editable"
    assert "Both menisci" in nt.template_body_text(rec), "the body must not be editable here"


def test_delete_removes_exactly_one(records):
    out = nt.delete_record(records, records[1]["id"])
    assert len(out) == len(records) - 1
    assert nt.find_by_id(out, records[1]["id"]) is None


# ─────────────────────────────────────────────────────────────────────────────
# 8. Purity — the property that makes all of the above testable
# ─────────────────────────────────────────────────────────────────────────────

def test_the_library_module_imports_no_qt_and_no_network():
    import ast
    import os as _os

    path = _os.path.join(
        _os.path.dirname(_os.path.abspath(__file__)),
        "..", "..", "..", "modules", "EchoMind", "normal_templates.py",
    )
    with open(_os.path.normpath(path), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    for banned in ("PySide6", "requests", "numpy", "sounddevice"):
        assert banned not in imported, (
            f"normal_templates.py imported {banned} — it must stay pure stdlib so "
            f"parsing, search and prompt rendering remain testable offscreen"
        )
