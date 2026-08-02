"""The reusable per-series selection widget (2026-07-30)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from PacsClient.pacs.workstation_ui.home_ui.series_selection_widget import (
    SeriesSelectionWidget,
    normalize_series_number,
)


@pytest.fixture(scope="module")
def _app():
    return QApplication.instance() or QApplication([])


def _studies():
    return [
        {"study_uid": "S1", "title": "CT CHEST", "series": [
            {"series_number": "1", "description": "Scout", "modality": "CT", "image_count": 2},
            {"series_number": "02", "description": "Axial", "modality": "CT", "image_count": 320},
            {"series_number": 3, "description": "Bone", "modality": "CT", "image_count": 320},
        ]},
        {"study_uid": "S2", "title": "MRI", "series": [
            {"series_number": "1", "description": "T1", "modality": "MR", "image_count": 24},
        ]},
    ]


def test_all_checked_returns_none(_app):
    w = SeriesSelectionWidget()
    w.set_studies(_studies())
    assert w.get_selection() is None  # legacy path
    assert w.total_series_count() == 4
    assert w.selected_series_count() == 4


def test_uncheck_one_series_returns_map(_app):
    w = SeriesSelectionWidget()
    w.set_studies(_studies())
    s1 = w.tree.topLevelItem(0)
    s1.child(2).setCheckState(0, Qt.Unchecked)  # S1 / series 3
    sel = w.get_selection()
    assert sel == {"S1": {"1", "2"}, "S2": {"1"}}
    assert s1.checkState(0) == Qt.PartiallyChecked
    assert w.selected_series_count() == 3


def test_series_numbers_are_normalized(_app):
    w = SeriesSelectionWidget()
    w.set_studies(_studies())
    s1 = w.tree.topLevelItem(0)
    # leave only the '02' one unchecked → it should appear as '2' when kept elsewhere
    s1.child(0).setCheckState(0, Qt.Unchecked)  # series 1
    sel = w.get_selection()
    assert sel["S1"] == {"2", "3"}  # '02' normalized to '2', int 3 to '3'


def test_select_all_toggle(_app):
    w = SeriesSelectionWidget()
    w.set_studies(_studies())
    # Starts all-checked → a master click clears everything.
    w._on_select_all_clicked(False)
    assert w.selected_series_count() == 0
    assert w.has_any_selection() is False
    # Another master click selects everything again.
    w._on_select_all_clicked(False)
    assert w.selected_series_count() == 4
    assert w.get_selection() is None


def test_study_without_series_is_always_included(_app):
    w = SeriesSelectionWidget()
    w.set_studies([{"study_uid": "S9", "title": "No metadata", "series": []}])
    assert w.get_selection() is None  # nothing to restrict
    assert w.has_any_selection() is True  # whole study included


def test_normalize_helper():
    assert normalize_series_number("02") == "2"
    assert normalize_series_number(3) == "3"
    assert normalize_series_number("2.0") == "2"
    assert normalize_series_number("SCOUT") == "SCOUT"
