"""The tool's vocabulary must be the lexicon's vocabulary.

Caught by the Persian benchmark, not by any unit test: question 15
(«چند تا سونوگرافی دیروز پذیرش شده؟») was answered correctly in one run and
refused in the next, because the model said "Sonography" the first time and
"ultrasound" the second. `local/datamodel.py` knew only the vendor's own four
strings; `reception_crm/lexicon` knew the synonyms. Two vocabularies, one of
them documented and tested, and the tool was wired to the other.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reception_crm import lexicon as L
from reception_crm.local import datamodel as dm


#: Every one of these was UnknownValue before the bridge, and every one is a
#: word a person actually uses.
BRIDGED = [
    ("ultrasound", "3"),
    ("Ultrasound", "3"),
    ("echo", "3"),
    ("sonogram", "3"),
    ("x-ray", "4"),
    ("xray", "4"),
    ("radiography", "4"),
    ("magnetic resonance", "2"),
    ("CAT scan", "1"),
    ("DEXA", "5"),
]


@pytest.mark.parametrize("term,code", BRIDGED)
def test_lexicon_synonyms_reach_the_tool(term, code):
    assert dm.resolve_modality(term).code == code


#: The vendor's own strings must keep working — the bridge adds, never replaces.
VENDOR = [("Sonography", "3"), ("US", "3"), ("MRI", "2"), ("MR", "2"),
          ("CT", "1"), ("Radiology", "4"), ("سونوگرافی", "3"), ("رادیولوژی", "4"),
          ("2", "2"), ("3", "3")]


@pytest.mark.parametrize("term,code", VENDOR)
def test_vendor_vocabulary_still_resolves(term, code):
    assert dm.resolve_modality(term).code == code


def test_genuine_nonsense_still_raises():
    """The bridge must not turn 'unknown' into 'guess'."""
    with pytest.raises(dm.UnknownValue):
        dm.resolve_modality("پیتزا")
    with pytest.raises(dm.UnknownValue):
        dm.resolve_modality("Brain MRI")   # a SERVICE, not a modality


def test_the_lexicon_file_is_bundled_by_the_installer_spec():
    """The frozen build shipped WITHOUT lexicon.json and every test still passed.

    PyInstaller follows imports, not data files. `resolve_modality` caught the
    FileNotFoundError, fell through, and the deployed server answered
    «ultrasound» is not a modality — while the suite, which runs from source
    where the file simply exists, was green. A test that only runs from source
    cannot see a packaging fault, so this one reads the spec.
    """
    spec = (Path(__file__).resolve().parent.parent
            / "scripts" / "ReceptionCrmServer.spec").read_text(encoding="utf-8")
    assert "lexicon.json" in spec, "the installer must bundle the lexicon"
    assert "refusing to build" in spec, "and must REFUSE to build without it, not warn"


def test_the_data_files_are_bundled_by_the_wheel_too():
    """The installer was fixed; the wheel had the same hole and was not.

    `scripts/build_wheel.ps1` builds through setuptools, which ships only what
    `package-data` names. `lexicon.json` and `reports_catalog.json` were not
    named, so a wheel install reproduced the original defect exactly — a server
    that starts, answers, and is quietly missing its vocabulary.

    Fixing one packaging path and not the other is the easy version of this
    mistake to make twice.
    """
    pyproject = (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text(encoding="utf-8")
    assert "lexicon/*.json" in pyproject, "the wheel must ship the lexicon"
    assert "reports_catalog.json" in pyproject, "the wheel must ship the report catalogue"


def test_a_missing_lexicon_is_loud_and_an_unknown_term_is_quiet(monkeypatch, caplog):
    """One `except Exception: pass` covered both, which is why this shipped."""
    import logging

    dm._lexicon_warned = False
    caplog.set_level(logging.ERROR, logger="reception_crm.local.datamodel")

    # An unknown TERM: quiet, and still raises UnknownValue.
    with pytest.raises(dm.UnknownValue):
        dm.resolve_modality("پیتزا")
    assert "LEXICON UNAVAILABLE" not in caplog.text, "a normal negative must not shout"

    # A missing FILE: loud, once.
    caplog.clear()
    dm._lexicon_warned = False
    monkeypatch.setattr(L, "load", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("lexicon.json")))
    L.resolve.cache_clear() if hasattr(L.resolve, "cache_clear") else None
    L._index.cache_clear()
    with pytest.raises(dm.UnknownValue):
        dm.resolve_modality("ultrasound")
    assert "LEXICON UNAVAILABLE" in caplog.text
    assert "PACKAGING" in caplog.text, "the message must name the real fault"
    L._index.cache_clear()


def test_lexicon_available_reports_the_truth():
    assert dm.lexicon_available() is True


def test_the_two_vocabularies_now_agree_on_every_lexicon_term():
    """No term the lexicon accepts may be rejected by the tool.

    Asserted over the whole table rather than a sample, so a synonym added to
    the lexicon later cannot silently fail to reach the tool.
    """
    disagreements = []
    for concept in L.load()["value_sets"]["modality"]["concepts"]:
        if concept.get("status") == "disabled":
            continue                      # DisabledValue is a different answer
        for lang in ("en", "fa"):
            for term in (concept.get("acceptable") or {}).get(lang, []) or []:
                try:
                    got = dm.resolve_modality(term).code
                except dm.UnknownValue:
                    disagreements.append((term, "REJECTED by the tool"))
                    continue
                if got != concept["code"]:
                    disagreements.append((term, f"tool says {got}, lexicon says {concept['code']}"))
    assert not disagreements, f"tool and lexicon disagree: {disagreements}"
