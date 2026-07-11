"""Unit tests for the canonical viewport-overlay metadata provider.

Pure stdlib module (PacsClient/utils/overlay_metadata.py) — no Qt/VTK/pydicom/DB,
so these run headless anywhere. Pins the chosen policy (2026-07-09):
DICOM->DB->server precedence, prefer-English PersonName component, and "NA" only
when a field is truly missing everywhere.
"""
import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from PacsClient.utils.overlay_metadata import (  # noqa: E402
    build_overlay_metadata, normalize_person_name, first_present, MISSING,
)


# ── PersonName component selection ──────────────────────────────────────────
def test_person_name_prefers_english_alphabetic_group():
    # str(PersonName) form: alphabetic=ideographic
    raw = "SMITH^JOHN=نام^فامیل"
    assert normalize_person_name(raw, prefer="english") == "SMITH JOHN"


def test_person_name_persian_pref_picks_persian_group():
    raw = "SMITH^JOHN=نامخانوادگی"
    out = normalize_person_name(raw, prefer="persian")
    assert out == "نامخانوادگی"


def test_person_name_english_falls_back_to_persian_when_no_latin():
    # Only a Persian group present; english preference falls back to it.
    raw = "علی^رضا"
    out = normalize_person_name(raw, prefer="english")
    assert out == "علی رضا"


def test_person_name_english_group_second_still_chosen():
    # Some senders put Persian in group0 and Latin in group1 -> english pref must
    # still find the Latin group.
    raw = "علی^رضا=ALI^REZA"
    assert normalize_person_name(raw, prefer="english") == "ALI REZA"


def test_person_name_caret_becomes_space_and_collapses():
    assert normalize_person_name("DOE^JANE^^DR", prefer="english") == "DOE JANE DR"


def test_person_name_missing_returns_empty():
    for v in ("", "  ", "N/A", "na", None, "None", "-"):
        assert normalize_person_name(v) == ""


# ── missing-token handling ──────────────────────────────────────────────────
def test_first_present_skips_missing_tokens():
    assert first_present("", "N/A", "na", None, "Hospital X") == "Hospital X"
    assert first_present("", "N/A", None) == ""


# ── source precedence + NA sentinel ─────────────────────────────────────────
def test_dicom_beats_db_beats_server():
    m = build_overlay_metadata(
        dicom={"patient_id": "D1"},
        db={"patient_id": "DB1"},
        server={"patient_id": "S1"},
    )
    assert m["patient_id"] == "D1"


def test_falls_through_to_db_then_server_when_dicom_missing():
    m = build_overlay_metadata(
        dicom={"patient_id": "N/A"},   # treated as missing
        db={"patient_id": ""},          # missing
        server={"patient_id": "S1"},
    )
    assert m["patient_id"] == "S1"


def test_na_only_when_truly_missing_everywhere():
    m = build_overlay_metadata(
        dicom={"patient_name": "N/A"}, db={}, server={},
    )
    assert m["patient_name"] == MISSING == "NA"


def test_name_uses_dicom_source_and_english_component():
    # DICOM has the bilingual name; server has a Persian-only display name.
    m = build_overlay_metadata(
        dicom={"patient_name": "SMITH^JOHN=نام^فام"},
        server={"patient_name": "نام فام"},
    )
    assert m["patient_name"] == "SMITH JOHN"


def test_db_sex_age_column_aliases_accepted():
    # DB schema columns are `sex`/`age`, overlay historically read patient_sex/age.
    m = build_overlay_metadata(db={"sex": "M", "age": "045Y"})
    assert m["patient_sex"] == "M"
    assert m["patient_age"] == "045Y"


def test_series_description_and_modality_and_thickness():
    m = build_overlay_metadata(
        series={"series_description": "AX T2", "modality": "MR", "series_thk": "5.0"},
    )
    assert m["patient_name"] == "NA"  # no name source -> NA
    assert m["series_description"] == "AX T2"
    assert m["modality"] == "MR"
    assert m["slice_thickness"] == "5.0"


def test_all_fields_present_are_strings_never_none():
    m = build_overlay_metadata()
    assert set(m) >= {
        "patient_name", "patient_id", "patient_sex", "patient_age",
        "study_date", "study_time", "institution_name",
        "series_description", "modality", "slice_thickness",
    }
    assert all(isinstance(v, str) and v for v in m.values())  # empty -> "NA", never ""


def test_study_time_falls_back_to_series_time():
    m = build_overlay_metadata(series={"series_time": "101500"})
    assert m["study_time"] == "101500"


# ── FAST wiring source-pin ──────────────────────────────────────────────────
def test_fast_bridge_wires_canonical_provider_behind_flag():
    """The FAST overlay must route through the canonical provider, gated by the
    default-off flag (so flag-off is byte-identical legacy)."""
    bridge = os.path.join(_ROOT, "modules", "viewer", "fast", "qt_viewer_bridge.py")
    if not os.path.exists(bridge):
        return
    src = open(bridge, encoding="utf-8", errors="replace").read()
    assert "AIPACS_CANONICAL_OVERLAY_METADATA" in src
    assert "_CANONICAL_OVERLAY_METADATA" in src
    assert "from PacsClient.utils.overlay_metadata import build_overlay_metadata" in src
    # it must NOT overwrite series identity (series_number) from the provider
    assert "series[\"series_number\"] = canon" not in src
