"""Guard: per-series download progress bar inside each thumbnail card (2026-06-28).

A thin themed ``QProgressBar`` at the bottom of each series/thumbnail card (INSIDE
the card frame) fills left->right from the EXISTING throttled per-image
download-progress events. It updates ONLY the affected card (O(1) dict lookup + a
single ``setValue`` repaint), never rebuilds the list, does no I/O, starts no
download, and leaves the card's status border ring (blue->green) untouched.

Lifecycle: hidden when not downloading -> visible/filling while downloading -> full
on completion. Driven from ``home_download_service``'s ``on_series_progress`` via the
viewport-independent ``_feed_thumb_bar`` helper (so a card fills whether or not a
viewport shows the series), with cross-patient-safe admission and a ~1% throttle.

Flag ``AIPACS_THUMB_DL_PROGRESS_BAR`` (default ON; ``=0`` = byte-identical legacy, no bar).

Source-pins both ends of the wiring + a behavioral check of the card-update method
against a fake bar (no QApplication required).
"""
import re
import types
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


def _tm_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "patient_tab" / "utils"
        / "thumbnail_manager.py"
    ).read_text(encoding="utf-8")


def _hds_src() -> str:
    return (
        _repo_root() / "PacsClient" / "pacs" / "workstation_ui" / "home_ui"
        / "home_download_service.py"
    ).read_text(encoding="utf-8")


# ----------------------------------------------------------------------------
# Flag — default ON, kill switch preserved.
# ----------------------------------------------------------------------------
def test_flag_default_on():
    src = _tm_src()
    assert '_THUMB_DL_PROGRESS_BAR = (_os.getenv("AIPACS_THUMB_DL_PROGRESS_BAR", "1")' in src
    # default-on: absent env resolves truthy
    assert '!= "0"' in src[src.find("_THUMB_DL_PROGRESS_BAR ="):src.find("_THUMB_DL_PROGRESS_BAR =") + 200]


# ----------------------------------------------------------------------------
# Card creation — the bar is thin, text-less, hidden, gated, and inside the frame.
# ----------------------------------------------------------------------------
def test_card_adds_thin_hidden_bar_above_glass():
    """2026-07-29: the bar is created before the glass overlay, but as a DIRECT
    child of the card `widget` (not content_layout) and raised ABOVE the glass so
    it stays crisp (the glass dims only the image). Legacy in-layout path kept
    behind AIPACS_THUMB_BAR_ABOVE_GLASS=0."""
    src = _tm_src()
    fn = src.find("def create_thumbnail_widget(")
    assert fn != -1
    block = src[fn:src.find("# Glass overlay for progress", fn)]
    assert "if _THUMB_DL_PROGRESS_BAR:" in block            # gated
    assert 'AIPACS_THUMB_BAR_ABOVE_GLASS' in block          # z-order flag
    assert "QProgressBar(widget if _bar_above else None)" in block  # child of card when above
    assert "setFixedHeight(4)" in block                      # thin
    assert "setTextVisible(False)" in block                  # minimal, no % text
    assert "setVisible(False)" in block                      # hidden until downloading
    assert "content_layout.addWidget(dl_bar)" in block       # legacy path preserved
    assert "widget.dl_progress_bar = dl_bar" in block        # stored per-card
    # the bar is raised above the glass, both at creation and on each glass re-raise
    assert "_bar.raise_()" in src
    assert "def _raise_dl_bar_above_glass" in src
    assert src.count("self._raise_dl_bar_above_glass(widget)") >= 2


# ----------------------------------------------------------------------------
# Update method — single affected card, no rebuild, gated, deleted-widget safe.
# ----------------------------------------------------------------------------
def test_update_method_targets_single_card_no_rebuild():
    src = _tm_src()
    fn = src.find("def update_series_download_progress(self, series_number, downloaded, total):")
    assert fn != -1
    body = src[fn:fn + 1400]
    assert "if not _THUMB_DL_PROGRESS_BAR:" in body          # gated -> no-op when off
    assert "self._resolve_series_key(series_number)" in body  # resolve to the card key
    assert "self._series_dl_bar(series_key)" in body          # only that card's bar
    assert "bar.setValue(" in body                            # a single cheap repaint
    # must not trigger a full rebuild / re-render of the thumbnail list
    assert "render" not in body.lower()
    assert "rebuild" not in body.lower()
    # the complete helper pins to the bar maximum (a finished series shows a full bar)
    comp = src.find("def _set_series_dl_bar_complete(self, series_key):")
    assert comp != -1
    assert "bar.setValue(top)" in src[comp:comp + 700]


# ----------------------------------------------------------------------------
# start reveals the bar; complete pins it full.
# ----------------------------------------------------------------------------
def test_start_reveals_and_complete_pins_full():
    src = _tm_src()
    start = src.find("def start_series_download(self, series_number, total_images=None):")
    assert start != -1
    sblock = src[start:start + 1200]
    assert "self._series_dl_bar(series_key)" in sblock
    assert "setVisible(True)" in sblock                       # revealed on download start

    comp = src.find("def complete_series_download(self, series_number, total_images=None):")
    assert comp != -1
    cblock = src[comp:comp + 600]
    assert "self._set_series_dl_bar_complete(series_key)" in cblock  # pinned full on completion


# ----------------------------------------------------------------------------
# Bridge feed — viewport-independent, cross-patient safe, throttled, wired in.
# ----------------------------------------------------------------------------
def test_bridge_feed_is_cross_patient_safe_and_throttled():
    src = _hds_src()
    fn = src.find("def _feed_thumb_bar(uid, series_uid, current, total):")
    assert fn != -1
    body = src[fn:fn + 1600]
    # admission: primary study OR a sibling that belongs to THIS patient's own map
    assert "if uid != study_uid and not _belongs_to_open_thumbnails(series_uid):" in body
    assert "return" in body
    # ~1% throttle keyed per card
    assert "_last_thumb_bar_pct" in body
    assert "pct = int(cur_i * 100 / total_i)" in body
    # drives the card bar via the thumbnail manager
    assert "tm.update_series_download_progress(key, cur_i, total_i)" in body


def test_on_series_progress_feeds_bar_before_grow_lane_return():
    src = _hds_src()
    fn = src.find("def on_series_progress(uid, series_uid, current, total):")
    assert fn != -1
    body = src[fn:fn + 600]
    feed = body.find("_feed_thumb_bar(uid, series_uid, current, total)")
    grow = body.find("_grow_lane_display_key(uid, series_uid)")
    assert feed != -1 and grow != -1
    # the bar feed must run BEFORE the grow-lane early-return (which skips
    # series that no viewport shows) so background/sibling cards still fill.
    assert feed < grow


# ----------------------------------------------------------------------------
# Behavioral — the real card-update code fills/clamps/shows the right bar only.
# ----------------------------------------------------------------------------
def test_update_progress_behavioral():
    pytest.importorskip("PySide6")
    try:
        from PacsClient.pacs.patient_tab.utils import thumbnail_manager as TM
    except Exception as exc:  # pragma: no cover - import env dependent
        pytest.skip(f"thumbnail_manager import unavailable: {exc}")

    # Feature must be on for the behavioral path (default on).
    if not getattr(TM, "_THUMB_DL_PROGRESS_BAR", False):
        pytest.skip("AIPACS_THUMB_DL_PROGRESS_BAR disabled in this env")

    class FakeBar:
        def __init__(self):
            self._max, self._val, self._vis = 1, 0, False

        def maximum(self):
            return self._max

        def setRange(self, a, b):
            self._max = b

        def value(self):
            return self._val

        def setValue(self, v):
            self._val = v

        def isVisible(self):
            return self._vis

        def setVisible(self, v):
            self._vis = v

    bar = FakeBar()
    widget = types.SimpleNamespace(dl_progress_bar=bar)
    fake = types.SimpleNamespace(series_widgets={"7": widget})
    fake._resolve_series_key = lambda x: str(x)
    fake._series_dl_bar = TM.ThumbnailManager._series_dl_bar.__get__(fake)
    upd = TM.ThumbnailManager.update_series_download_progress.__get__(fake)
    comp = TM.ThumbnailManager._set_series_dl_bar_complete.__get__(fake)

    # hidden until the first progress
    assert bar.isVisible() is False
    upd("7", 3, 7)
    assert (bar.maximum(), bar.value(), bar.isVisible()) == (7, 3, True)

    # only the affected card: an unknown key is a no-op, never crashes, never
    # disturbs the existing bar.
    upd("999", 5, 10)
    assert bar.value() == 3

    # clamps over-count to the total
    upd("7", 99, 7)
    assert bar.value() == 7

    # completion pins to full even after a stale low value
    bar.setValue(2)
    comp("7")
    assert bar.value() == bar.maximum() == 7


def test_update_progress_disabled_is_noop(monkeypatch):
    pytest.importorskip("PySide6")
    try:
        from PacsClient.pacs.patient_tab.utils import thumbnail_manager as TM
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"thumbnail_manager import unavailable: {exc}")
    monkeypatch.setattr(TM, "_THUMB_DL_PROGRESS_BAR", False, raising=False)

    class FakeBar:
        def __init__(self):
            self._val, self._vis = 0, False

        def maximum(self):
            return 1

        def setRange(self, a, b):
            pass

        def value(self):
            return self._val

        def setValue(self, v):
            self._val = v

        def isVisible(self):
            return self._vis

        def setVisible(self, v):
            self._vis = v

    bar = FakeBar()
    widget = types.SimpleNamespace(dl_progress_bar=bar)
    fake = types.SimpleNamespace(series_widgets={"7": widget})
    fake._resolve_series_key = lambda x: str(x)
    fake._series_dl_bar = TM.ThumbnailManager._series_dl_bar.__get__(fake)
    upd = TM.ThumbnailManager.update_series_download_progress.__get__(fake)

    upd("7", 3, 7)
    # flag off => byte-identical legacy: the bar is never touched
    assert (bar.value(), bar.isVisible()) == (0, False)
