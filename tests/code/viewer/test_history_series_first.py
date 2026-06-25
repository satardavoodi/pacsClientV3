"""Guard: DICOMized clinical-history series sort FIRST in the Patient-Tab
thumbnail list, with regular series keeping their existing numeric order.

Server-DICOMized clinical/patient-history series are saved with very high series
numbers (~100000). The thumbnail list now applies a PRIORITY rule:
  SortKey = 0 for clinical-history series, 1 for regular — then the existing
  ordering inside each group. Flag AIPACS_HISTORY_SERIES_FIRST (default on).

`series_is_clinical_history` + `_history_first_enabled` are pure (only need
`os`), so they're exec'd from source without importing the Qt-heavy mixin.
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_PW = (_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
       / "patient_widget_core" / "_pw_thumbnails.py")


def _load_history_helpers():
    src = _PW.read_text(encoding="utf-8", errors="ignore")
    start = src.index("_HISTORY_SERIES_NUMBER = ")
    end = src.index("class _PWThumbnailsMixin")
    ns = {"os": os}
    exec(src[start:end], ns)  # noqa: S102 — pure helpers, only need os
    return ns


_H = _load_history_helpers()
series_is_clinical_history = _H["series_is_clinical_history"]
_history_first_enabled = _H["_history_first_enabled"]


# ── detection ────────────────────────────────────────────────────────────────
def test_detect_only_exact_100000():
    assert series_is_clinical_history({"series_number": "100000"}) is True
    # other large / 100000-range numbers must NOT match (2026-06-22 narrowing)
    assert series_is_clinical_history({"series_number": "100001"}) is False
    assert series_is_clinical_history({"series_number": "100123"}) is False
    assert series_is_clinical_history({"series_number": "200000"}) is False
    assert series_is_clinical_history({"series_number": "999999"}) is False
    assert series_is_clinical_history({"series_number": "5"}) is False
    assert series_is_clinical_history({"series_number": "9999"}) is False


def test_detect_uses_orig_number_not_offset_key():
    # multi-study OFFSET key 1000005 but ORIGINAL series 5 -> NOT history
    assert series_is_clinical_history(
        {"series_number": "1000005", "_orig_series_number": "5"}) is False
    # offset key 1100000 but original 100000 -> IS history
    assert series_is_clinical_history(
        {"series_number": "1100000", "_orig_series_number": "100000"}) is True


def test_modality_and_description_do_not_match():
    # narrowed (2026-06-22) to the EXACT series number 100000 only — DOC modality
    # and history wording no longer trigger the exception.
    assert series_is_clinical_history({"series_number": "3", "modality": "DOC"}) is False
    assert series_is_clinical_history({"series_number": "3", "series_description": "Patient History"}) is False
    assert series_is_clinical_history({"series_number": "4", "series_name": "Clinical History scan"}) is False
    assert series_is_clinical_history({"series_number": "3", "modality": "MR", "series_description": "AX T2 FLAIR"}) is False
    assert series_is_clinical_history({}) is False
    # series 100000 still matches regardless of modality (by exact number)
    assert series_is_clinical_history({"series_number": "100000", "modality": "MR"}) is True


def test_flag_default_on_and_off(monkeypatch):
    monkeypatch.delenv("AIPACS_HISTORY_SERIES_FIRST", raising=False)
    assert _history_first_enabled() is True
    monkeypatch.setenv("AIPACS_HISTORY_SERIES_FIRST", "0")
    assert _history_first_enabled() is False


# ── ordering behaviour ───────────────────────────────────────────────────────
def _entries_sort_key(item, hist_on=True):
    # mirrors _render_thumbnails_from_entries._sort_key
    hist = 0 if (hist_on and series_is_clinical_history(item)) else 1
    try:
        return (hist, int(item.get('series_number', 0)))
    except (TypeError, ValueError):
        return (hist, 0)


def test_history_first_then_existing_order():
    series = [
        {"series_number": "2", "modality": "MR"},
        {"series_number": "100000", "modality": "DOC"},     # clinical history
        {"series_number": "1", "modality": "MR"},
        {"series_number": "10", "modality": "MR"},
    ]
    ordered = [s["series_number"] for s in sorted(series, key=_entries_sort_key)]
    assert ordered == ["100000", "1", "2", "10"]            # history first, regular ascending


def test_regular_order_unchanged_when_no_history():
    series = [{"series_number": str(n)} for n in (3, 1, 22, 4, 2)]
    ordered = [s["series_number"] for s in sorted(series, key=_entries_sort_key)]
    assert ordered == ["1", "2", "3", "4", "22"]            # plain ascending, unchanged


def test_flag_off_restores_pure_numeric_order():
    series = [
        {"series_number": "2", "modality": "MR"},
        {"series_number": "100000", "modality": "DOC"},
        {"series_number": "1", "modality": "MR"},
    ]
    ordered = [s["series_number"] for s in sorted(series, key=lambda s: _entries_sort_key(s, hist_on=False))]
    assert ordered == ["1", "2", "100000"]                 # history sinks to its numeric place


# ── source pins: all three sort points use the helper ────────────────────────
def test_all_sort_points_use_history_first():
    s = _PW.read_text(encoding="utf-8", errors="ignore")
    assert "def series_is_clinical_history" in s
    assert "AIPACS_HISTORY_SERIES_FIRST" in s
    assert "hist = 0 if (_hist_on and series_is_clinical_history(s)) else 1" in s      # multi-study group
    assert "hist = 0 if (_hist_on and series_is_clinical_history(item)) else 1" in s   # entries
    assert "_file_sort_key" in s and "series_is_clinical_history(det)" in s            # files path
