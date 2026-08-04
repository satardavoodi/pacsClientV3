"""MG-PAIR-1 regression tests.

Root cause under test
---------------------
`series_name` is NULL in the DB `series` rows for some MG studies (e.g. patient
52795 / study 2.16.840.1.113669.632.20.20260802.113626638.6.18, whose four MG
series are R-CC / L-CC / R-MLO / L-MLO with series_name IS NULL).

Call sites read it as `str(series_info.get('series_name', ''))`.  `str(None)` is
the truthy literal 'None', so `_rebuild_series_index()` bucketed all four MG
series under one key and the switch path combined CC into the MLO viewport.
"""
import os

import pytest

from PacsClient.utils.series_pairing import (
    can_pair_series_names,
    normalize_series_name,
    pairing_guard_enabled,
)


# --------------------------------------------------------------------------
# normalize_series_name
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "None", "none", "NONE", "", "   ", "null",
                                   "nan", "Unknown", "unknown", "N/A", "-"])
def test_placeholder_series_names_normalize_to_empty(value):
    assert normalize_series_name(value) == ""


@pytest.mark.parametrize("value,expected", [
    ("R-CC", "R-CC"),
    ("  L-MLO  ", "L-MLO"),
    ("2", "2"),
    (7, "7"),
    ("Tomo_Combo", "Tomo_Combo"),
])
def test_real_series_names_survive_normalization(value, expected):
    assert normalize_series_name(value) == expected


def test_str_none_sentinel_is_the_exact_regression():
    """`str(None)` is truthy — that is what created the bad pairing bucket."""
    raw = str(None)
    assert raw == "None" and bool(raw) is True, "precondition of the bug"
    assert normalize_series_name(raw) == ""


# --------------------------------------------------------------------------
# can_pair_series_names
# --------------------------------------------------------------------------

def test_two_null_series_names_never_pair():
    assert can_pair_series_names(None, None) is False


def test_two_str_none_series_names_never_pair():
    assert can_pair_series_names(str(None), str(None)) is False


def test_two_empty_series_names_never_pair():
    assert can_pair_series_names("", "") is False


def test_two_unknown_defaults_never_pair():
    """_vc_layout used 'Unknown' as its .get() default for the primary."""
    assert can_pair_series_names("Unknown", "Unknown") is False


def test_genuine_shared_series_name_still_pairs():
    assert can_pair_series_names("Tomo_Combo", "Tomo_Combo") is True


def test_different_real_series_names_do_not_pair():
    assert can_pair_series_names("R-CC", "R-MLO") is False


def test_pairing_is_whitespace_insensitive_for_real_names():
    assert can_pair_series_names("R-CC", "  R-CC ") is True


# --------------------------------------------------------------------------
# kill switch
# --------------------------------------------------------------------------

def test_guard_is_enabled_by_default(monkeypatch):
    monkeypatch.delenv("AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD", raising=False)
    assert pairing_guard_enabled() is True


def test_kill_switch_restores_legacy_behaviour(monkeypatch):
    monkeypatch.setenv("AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD", "1")
    assert pairing_guard_enabled() is False
    # Legacy: `str(None)` was accepted as a real name and therefore paired.
    assert normalize_series_name(None) == "None"
    assert normalize_series_name("None") == "None"
    assert can_pair_series_names(None, None) is True
    assert can_pair_series_names("None", "None") is True


# --------------------------------------------------------------------------
# _rebuild_series_index — the index builder that created the bad bucket
# --------------------------------------------------------------------------

class _StubController:
    """Minimal stand-in exercising the real _rebuild_series_index body."""

    def __init__(self, thumbnails):
        import logging
        from types import SimpleNamespace

        self._series_number_to_index = {}
        self._paired_series_map = {}
        self._metadata_flat_cache = {}
        self.logger = logging.getLogger("stub")
        self.parent_widget = SimpleNamespace(lst_thumbnails_data=thumbnails)


def _rebuild(thumbnails):
    from PacsClient.pacs.patient_tab.ui.patient_ui._vc_backend import _VCBackendMixin

    stub = _StubController(thumbnails)
    _VCBackendMixin._rebuild_series_index(stub)
    return stub


def _mg_thumb(number, description, name):
    return {
        "vtk_image_data": object(),
        "metadata": {
            "series": {
                "series_number": number,
                "series_name": name,
                "series_description": description,
                "modality": "MG",
            },
            "instances": [{}],
        },
    }


PID_52795_SERIES = [
    _mg_thumb("2", "R-CC", None),
    _mg_thumb("4", "L-CC", None),
    _mg_thumb("6", "R-MLO", None),
    _mg_thumb("8", "L-MLO", None),
]


def test_null_series_names_produce_no_paired_bucket():
    """The exact PID 52795 shape: 4 MG series, all series_name NULL."""
    stub = _rebuild(PID_52795_SERIES)
    assert stub._paired_series_map == {}, (
        "NULL series_name must never create a pairing bucket; the legacy code "
        "produced {'None': ['2', '4', '6', '8']} and combined CC into MLO"
    )


def test_series_number_index_still_built_for_null_named_series():
    """The guard must not disturb the unrelated fast lookup index."""
    stub = _rebuild(PID_52795_SERIES)
    assert stub._series_number_to_index == {"2": 0, "4": 1, "6": 2, "8": 3}


def test_flat_metadata_cache_keeps_the_raw_series_name():
    """Only the pairing key is normalised; the flat cache is untouched."""
    stub = _rebuild(PID_52795_SERIES)
    assert stub._metadata_flat_cache["2"]["series_name"] == "None"


def test_genuinely_shared_series_name_still_creates_a_bucket():
    stub = _rebuild([
        _mg_thumb("2", "R-CC", "Combo"),
        _mg_thumb("4", "L-CC", "Combo"),
    ])
    assert stub._paired_series_map == {"Combo": ["2", "4"]}


def test_distinct_series_names_create_separate_buckets():
    stub = _rebuild([
        _mg_thumb("2", "R-CC", "R-CC"),
        _mg_thumb("6", "R-MLO", "R-MLO"),
    ])
    assert stub._paired_series_map == {"R-CC": ["2"], "R-MLO": ["6"]}


def test_kill_switch_reproduces_the_original_defect(monkeypatch):
    """Proves the env var really does restore pre-fix behaviour."""
    monkeypatch.setenv("AIPACS_DISABLE_SERIES_NAME_PAIRING_GUARD", "1")
    stub = _rebuild(PID_52795_SERIES)
    assert stub._paired_series_map == {"None": ["2", "4", "6", "8"]}
