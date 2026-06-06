"""Guard tests for the scanned-document drag-drop fit fix (2026-06-06).

Series 100000 (scanned reception/history pages, single-instance DICOM) showed
zoomed/cropped (only the page top visible) on a repeat drag-drop. Three
compounding defects are pinned here:

  1. `_sync_qt_viewer_presentation(refit_view=True)` deduped on HOST SIZE
     alone — a different-sized image landing at an unchanged host size
     skipped the refit and inherited the previous image's zoom/pan.
     The dedupe signature now includes the displayed image dimensions.
  2. `_refresh_qt_series_inplace` (same-series rebind) preserved zoom/pan/WL
     by design (anti-jump for mid-drag progressive stacks) — but a
     SINGLE-IMAGE series has no stack to protect, so it now forces default
     W/L + fit-to-viewport deterministically on every switch.
  3. `switch_series` treated equal series NUMBERS as identity. Scanned
     documents use a synthetic number (100000) in every study, so a
     cross-study drop could reuse the pane's presentation/slice for
     different content. The in-place path now requires `series_path`
     identity when both sides provide it (source-pinned).

Headless: plain fakes, no QApplication, no VTK render windows.
"""
import inspect
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_series import (  # noqa: E402
    _VWSeriesMixin,
)


# ---------------------------------------------------------------- fakes ----

class _FakeQtViewer:
    def __init__(self, img_w=0, img_h=0):
        self._image_width = img_w
        self._image_height = img_h
        self._display_scale_x = 1.0
        self._display_scale_y = 1.0
        self._zoom = 1.0

    # duck methods used inside try/except blocks
    def setGeometry(self, *a):
        pass

    def raise_(self):
        pass

    def updateGeometry(self):
        pass

    def update(self):
        pass

    def repaint(self):
        pass


class _FakeBridge:
    def __init__(self, slice_count=1, img_w=2200, img_h=1598):
        self.qt_viewer = _FakeQtViewer(img_w, img_h)
        self.slice_count = slice_count
        self.zoom_to_fit_calls = 0
        self.default_wl_calls = []
        self.set_slice_calls = []
        self.metadata = {}

    def zoom_to_fit(self):
        self.zoom_to_fit_calls += 1
        return 123.0  # parallel-scale-equivalent

    def reset_image_viewer(self, vtk_image_data, metadata, preserve_slice=None, **kw):
        self.metadata = metadata or {}

    def GetSlice(self):
        return 0

    def apply_default_window_level(self, idx):
        self.default_wl_calls.append(idx)

    def set_slice(self, idx):
        self.set_slice_calls.append(idx)


class _FakeRect:
    pass


class _Host(_VWSeriesMixin):
    """Minimal host exercising the real mixin methods on fakes."""

    def __init__(self, slice_count=1, host=(700, 800)):
        self.image_viewer = _FakeBridge(slice_count=slice_count)
        self._qt_viewer_widget = _FakeQtViewer()
        self._qt_bridge_active = True
        self._host = host
        self.slider = None
        self._progressive_mode = False
        self.last_series_show = None
        self._qt_switch_refit_applied = None
        self.saved_camera = False

    # geometry plumbing used by _sync_qt_viewer_presentation
    def width(self):
        return self._host[0]

    def height(self):
        return self._host[1]

    def rect(self):
        return _FakeRect()

    def get_count_of_slices(self):
        return self.image_viewer.slice_count

    def save_status_camera(self, bridge):
        self.saved_camera = True


# ------------------------------------------------ dedupe signature (1) ----

def test_refit_dedupes_on_same_host_and_image():
    host = _Host()
    host.image_viewer.qt_viewer._image_width = 512
    host.image_viewer.qt_viewer._image_height = 512
    host._sync_qt_viewer_presentation(refit_view=True)
    host._sync_qt_viewer_presentation(refit_view=True)
    assert host.image_viewer.zoom_to_fit_calls == 1  # burst dedupe preserved


def test_refit_runs_again_when_image_dims_change():
    host = _Host()
    qv = host.image_viewer.qt_viewer
    qv._image_width, qv._image_height = 512, 512
    host._sync_qt_viewer_presentation(refit_view=True)
    # same host size, NEW image (scanned page) — must NOT be deduped away
    qv._image_width, qv._image_height = 2200, 1598
    host._sync_qt_viewer_presentation(refit_view=True)
    assert host.image_viewer.zoom_to_fit_calls == 2


def test_refit_runs_after_signature_cleared():
    host = _Host()
    host._sync_qt_viewer_presentation(refit_view=True)
    host._last_refit_signature = None  # _queue_qt_startup_refit contract
    host._sync_qt_viewer_presentation(refit_view=True)
    assert host.image_viewer.zoom_to_fit_calls == 2


# ------------------------------------- in-place refresh, documents (2) ----

def test_single_slice_inplace_refresh_forces_default_wl_and_fit():
    host = _Host(slice_count=1)
    ok = host._refresh_qt_series_inplace(None, {'series': {'series_number': '100000'}}, 3)
    assert ok
    assert host.image_viewer.zoom_to_fit_calls >= 1   # fit forced
    assert 0 in host.image_viewer.default_wl_calls    # default W/L re-applied
    assert host.last_series_show == 3
    assert host._qt_switch_refit_applied is False     # controller follow-up stays armed


def test_multi_slice_inplace_refresh_preserves_presentation():
    host = _Host(slice_count=120)
    # pane was already fitted at this host size for this image
    host.image_viewer.qt_viewer._image_width = 512
    host.image_viewer.qt_viewer._image_height = 512
    host._sync_qt_viewer_presentation(refit_view=True)
    calls_before = host.image_viewer.zoom_to_fit_calls
    ok = host._refresh_qt_series_inplace(None, {'series': {'series_number': '7'}}, 5)
    assert ok
    # anti-jump contract: same-series multi-slice rebind must NOT refit
    assert host.image_viewer.zoom_to_fit_calls == calls_before
    assert host.image_viewer.default_wl_calls == []   # W/L untouched (slice kept)


# ---------------------------------------- series identity in switch (3) ----

def test_switch_series_same_number_requires_same_series_path():
    src = inspect.getsource(_VWSeriesMixin.switch_series)
    code = '\n'.join(line.split('#', 1)[0] for line in src.splitlines())
    assert "series_path" in code, (
        "switch_series must verify series_path identity before reusing the "
        "pane presentation for an equal series NUMBER (scanned documents use "
        "the same synthetic number, e.g. 100000, in every study)"
    )
    assert "_same_series_refresh = False" in code
