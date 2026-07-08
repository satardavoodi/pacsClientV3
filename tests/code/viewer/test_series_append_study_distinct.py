"""Guard: a DISTINCT series that shares a series_name + instance count with an
already-present series (the multi-study / previous-exam case) must still be placed.

Root cause (OPT-20 slot-3 residual, 49317): the study-blind name+count dedup in
``_PWMetadataMixin.add_new_data_to_lst_thumbnails_data`` treated a distinct
secondary-study series (its own patient-unique offset ``series_number``, e.g.
``3000001``) as a duplicate of a primary/other-study series that happened to
share the same ``series_name`` and instance count (scout / localizer / DX /
same-protocol repeat), so it was never appended.  ``replace_series_data`` then
returned ``-1`` -> the async apply render loop was gated off (``series_idx < 0``)
-> the previous-exam series never displayed.

Fix (flag ``AIPACS_SERIES_APPEND_STUDY_DISTINCT``, default on; ``=0`` = legacy):
only skip as a TRUE duplicate when the incoming ``series_number`` is already
present; a distinct, not-yet-present ``series_number`` is appended.

These tests exercise the REAL mixin methods (no Qt / VTK / pydicom) so they run
in the offscreen verify lane.
"""

import os

import pytest

from PacsClient.pacs.patient_tab.ui.patient_ui.patient_widget_core import (
    _pw_metadata as _pw_metadata_mod,
)

try:  # SimpleNamespace-style stubbing, matches test_fast_viewer_pipeline.py
    from types import SimpleNamespace
except Exception:  # pragma: no cover
    SimpleNamespace = None


class _DummyVtkImage:
    def __init__(self, dims=(32, 32, 1)):
        self._dims = dims

    def GetDimensions(self):
        return self._dims


def _series_item(number, name, count, study_uid="", preview=False):
    return {
        "vtk_image_data": _DummyVtkImage(),
        "metadata": {
            "series": {
                "series_number": str(number),
                "series_name": name,
                "series_path": f"C:/study/{study_uid or 'S'}/{number}",
                "study_uid": study_uid,
            },
            "preview_only": preview,
            "instances": [{} for _ in range(count)],
        },
        "file_path": f"thumb-{number}.png",
    }


def _make_widget(initial_items):
    widget = _pw_metadata_mod._PWMetadataMixin.__new__(_pw_metadata_mod._PWMetadataMixin)
    widget.lst_thumbnails_data = list(initial_items)
    widget.unique_elements_index = len(widget.lst_thumbnails_data)
    widget.thumbnail_manager = SimpleNamespace(
        set_series_pending=lambda sn: None,
        set_series_ready=lambda sn: None,
        update_series_image_count=lambda sn, count: None,
    )
    widget.viewer_controller = SimpleNamespace(
        _series_cache={},
        _hot_series_cache={},
        _series_name_cache={},
        _series_number_to_index={},
        _metadata_flat_cache={},
        _paired_series_map={},
        _rebuild_series_index=lambda: None,
    )
    widget._server_series_info = {}
    return widget


def _numbers(widget):
    return [
        str(it.get("metadata", {}).get("series", {}).get("series_number"))
        for it in widget.lst_thumbnails_data
    ]


@pytest.fixture(autouse=True)
def _default_flag_on(monkeypatch):
    # Ensure a clean default-on environment unless a test overrides it.
    monkeypatch.delenv("AIPACS_SERIES_APPEND_STUDY_DISTINCT", raising=False)
    yield


# ---------------------------------------------------------------------------
# The bug: distinct cross-study series sharing name + count must be appended
# ---------------------------------------------------------------------------
def test_distinct_offset_series_with_same_name_and_count_is_appended():
    # Primary study series 1 ("SCOUT", 1 image) already present.
    widget = _make_widget([_series_item(1, "SCOUT", 1, study_uid="STUDY_A")])
    # Previous-exam (slot 3) series 3000001 — SAME name + count, DIFFERENT study.
    widget.add_new_data_to_lst_thumbnails_data(
        _series_item(3000001, "SCOUT", 1, study_uid="STUDY_B")
    )
    nums = _numbers(widget)
    assert "1" in nums and "3000001" in nums, nums
    assert len(widget.lst_thumbnails_data) == 2


def test_replace_series_data_returns_valid_index_for_colliding_offset_series():
    # This is the exact gate that returned -1 (series_idx<0) before the fix.
    widget = _make_widget([_series_item(1, "OBL", 1, study_uid="STUDY_A")])
    idx = widget.replace_series_data(
        series_number="3000001",
        vtk_image_data=_DummyVtkImage(),
        metadata={
            "series": {
                "series_number": "3000001",
                "series_name": "OBL",
                "series_path": "C:/study/B/1",
                "study_uid": "STUDY_B",
            },
            "instances": [{}],
        },
        file_path="thumb-3000001.png",
        allow_append_if_missing=True,
    )
    assert idx is not None and idx >= 0, f"expected a valid placement index, got {idx}"
    assert "3000001" in _numbers(widget)


def test_two_previous_exam_studies_same_name_all_present():
    # Primary + two previous-exam studies (slots 2 and 3), all "CHEST" 1-image DX.
    widget = _make_widget([_series_item(1, "CHEST", 1, study_uid="STUDY_A")])
    widget.add_new_data_to_lst_thumbnails_data(_series_item(2000001, "CHEST", 1, study_uid="STUDY_B"))
    widget.add_new_data_to_lst_thumbnails_data(_series_item(3000001, "CHEST", 1, study_uid="STUDY_C"))
    nums = _numbers(widget)
    for expected in ("1", "2000001", "3000001"):
        assert expected in nums, nums
    assert len(widget.lst_thumbnails_data) == 3


# ---------------------------------------------------------------------------
# Isolation / no-regression: a TRUE duplicate is still deduped
# ---------------------------------------------------------------------------
def test_true_duplicate_same_number_is_not_double_added():
    widget = _make_widget([_series_item(1, "SCOUT", 1, study_uid="STUDY_A")])
    widget.add_new_data_to_lst_thumbnails_data(_series_item(1, "SCOUT", 1, study_uid="STUDY_A"))
    # same series_number -> no second entry
    assert _numbers(widget).count("1") == 1
    assert len(widget.lst_thumbnails_data) == 1


def test_same_name_different_count_still_appends():
    # The different-count pairing-append path (unchanged by the fix).
    widget = _make_widget([_series_item(1, "SERIES", 1, study_uid="STUDY_A")])
    widget.add_new_data_to_lst_thumbnails_data(_series_item(2, "SERIES", 5, study_uid="STUDY_A"))
    nums = _numbers(widget)
    assert "1" in nums and "2" in nums, nums


# ---------------------------------------------------------------------------
# Kill switch: legacy behavior restored with the flag off
# ---------------------------------------------------------------------------
def test_flag_off_restores_legacy_drop(monkeypatch):
    monkeypatch.setenv("AIPACS_SERIES_APPEND_STUDY_DISTINCT", "0")
    widget = _make_widget([_series_item(1, "SCOUT", 1, study_uid="STUDY_A")])
    # Legacy: the distinct same-name+count series is dropped (return False).
    widget.add_new_data_to_lst_thumbnails_data(_series_item(3000001, "SCOUT", 1, study_uid="STUDY_B"))
    nums = _numbers(widget)
    assert "3000001" not in nums, nums
    assert len(widget.lst_thumbnails_data) == 1


def test_flag_off_replace_series_data_returns_minus_one(monkeypatch):
    monkeypatch.setenv("AIPACS_SERIES_APPEND_STUDY_DISTINCT", "0")
    widget = _make_widget([_series_item(1, "OBL", 1, study_uid="STUDY_A")])
    idx = widget.replace_series_data(
        series_number="3000001",
        vtk_image_data=_DummyVtkImage(),
        metadata={
            "series": {
                "series_number": "3000001",
                "series_name": "OBL",
                "series_path": "C:/study/B/1",
                "study_uid": "STUDY_B",
            },
            "instances": [{}],
        },
        file_path="thumb.png",
        allow_append_if_missing=True,
    )
    assert idx == -1, f"legacy path should return -1, got {idx}"
