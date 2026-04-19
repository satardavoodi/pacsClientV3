"""
Shared fixtures for tests/fast/ — pure-DICOM geometry test suite.

All fixtures create synthetic DICOM instance dicts (no real files).
"""
import sys
import os

# Ensure this test directory is on sys.path so test files can do
# `from helpers import ...` (same pattern as tests/fast_viewer/).
sys.path.insert(0, os.path.dirname(__file__))

import pytest
from fast_helpers import (
    _make_axial_instances as _axial_h,
    _make_sagittal_instances as _sagittal_h,
    _make_coronal_instances as _coronal_h,
)


@pytest.fixture
def axial_instances():
    return _axial_h()


@pytest.fixture
def sagittal_instances():
    return _sagittal_h()


@pytest.fixture
def coronal_instances():
    return _coronal_h()



# ─────────────────────────────────────────────────────────────────────────────
# Thumbnail-state mock (Qt-free)
# Mirrors the fixed ThumbnailManager state logic for unit testing without Qt.
# ─────────────────────────────────────────────────────────────────────────────

class _MockProgressBorder:
    """Tracks progress border state changes without any Qt dependency."""

    def __init__(self):
        self._is_ready = False
        self._downloading = False
        self._progress = 0.0

    def setReady(self, val: bool) -> None:
        self._is_ready = val

    def setDownloading(self, val: bool) -> None:
        self._downloading = val

    def setProgress(self, val: float) -> None:
        self._progress = val


class _MockWidget:
    """Minimal thumbnail-card widget (Qt-free)."""

    def __init__(self):
        self.progress_border = _MockProgressBorder()
        self.count_label_text = None


class _ThumbnailManagerState:
    """Qt-free mirror of ThumbnailManager state logic.

    Exposes the same public API surface used by tests:
    * register_series(sn)          — simulate thumbnail widget creation
    * start_series_download(sn)    — blue border, deferred if widget absent
    * update_series_progress(sn, pct)
    * complete_series_download(sn) — green border (Gap-1 fix path)
    * apply_border_states_new()     — coalesced repaint counter
    """

    def __init__(self):
        self.series_widgets: dict = {}
        self.ready_series: set = set()
        self._pending_download_series: set = set()
        self._pending_download_totals: dict = {}
        self._apply_count: int = 0
        self._series_uid_to_number: dict = {}
        self._series_projection_state: dict = {}
        self._series_total_images: dict = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_series(self, sn) -> _MockWidget:
        """Simulate thumbnail widget creation for series *sn*."""
        key = self._resolve_series_key(sn)
        widget = _MockWidget()
        self.series_widgets[key] = widget
        # Replay deferred download start if DM fired before widget existed (Gap-4)
        if key in self._pending_download_series:
            self._pending_download_series.discard(key)
            self.start_series_download(sn, total_images=self._pending_download_totals.pop(key, None))
        if key in self.ready_series or self._series_projection_state.get(key) == "completed":
            self.complete_series_download(sn, total_images=self._series_total_images.get(key))
        return widget

    def start_series_download(self, sn, total_images=None) -> None:
        key = self._resolve_series_key(sn)
        total_images = self._remember_total_images(key, total_images)
        if key not in self.series_widgets:
            self._pending_download_series.add(key)
            if total_images is not None:
                self._pending_download_totals[key] = total_images
            return
        if self._series_projection_state.get(key) == "downloading":
            if total_images is not None:
                self.series_widgets[key].count_label_text = f"{total_images} images"
            return
        self._series_projection_state[key] = "downloading"
        self.ready_series.discard(key)
        self.series_widgets[key].progress_border.setDownloading(True)
        self.series_widgets[key].progress_border.setReady(False)
        if total_images is not None:
            self.series_widgets[key].count_label_text = f"{total_images} images"
        self.apply_border_states_new()

    def update_series_progress(self, sn, pct: float, text: str = "") -> None:
        key = self._resolve_series_key(sn)
        if key in self.series_widgets:
            self.series_widgets[key].progress_border.setProgress(pct)

    def complete_series_download(self, sn, total_images=None) -> None:
        key = self._resolve_series_key(sn)
        total_images = self._remember_total_images(key, total_images)
        if self._series_projection_state.get(key) == "completed":
            if key in self.series_widgets:
                widget = self.series_widgets[key]
                changed = False
                if widget.progress_border._downloading:
                    widget.progress_border.setDownloading(False)
                    changed = True
                if not widget.progress_border._is_ready:
                    widget.progress_border.setReady(True)
                    changed = True
                if total_images is not None:
                    new_text = f"{total_images}/{total_images}"
                    if widget.count_label_text != new_text:
                        widget.count_label_text = new_text
                        changed = True
                if changed:
                    self.apply_border_states_new()
            return
        self._series_projection_state[key] = "completed"
        self.ready_series.add(key)
        if key in self.series_widgets:
            widget = self.series_widgets[key]
            widget.progress_border.setDownloading(False)
            widget.progress_border.setReady(True)
            if total_images is not None:
                widget.count_label_text = f"{total_images}/{total_images}"
        self.apply_border_states_new()

    def apply_border_states_new(self) -> None:
        self._apply_count += 1

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _resolve_series_key(self, series_identifier) -> str:
        key = str(series_identifier)
        if key in self.series_widgets:
            return key
        mapped = self._series_uid_to_number.get(key)
        if mapped:
            return str(mapped)
        return key

    def _remember_total_images(self, key: str, total_images=None):
        try:
            if total_images is None:
                return self._series_total_images.get(key)
            value = int(total_images)
            if value <= 0:
                return self._series_total_images.get(key)
            self._series_total_images.setdefault(key, value)
            return self._series_total_images.get(key)
        except Exception:
            return self._series_total_images.get(key)


@pytest.fixture
def tm() -> _ThumbnailManagerState:
    """Lightweight ThumbnailManagerState fixture (Qt-free)."""
    return _ThumbnailManagerState()
