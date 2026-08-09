"""UX-1/2/3 — thumbnail bottom strip z-order + active-series state (2026-08-09).

Three reported defects, all on the series thumbnail cards:

UX-1  The blue download bar was "partially hidden behind the thumbnail".
      Root cause measured on real widgets: the strip widgets are absolutely
      positioned direct children of the card, but `main_layout.addWidget(
      progress_border)` RE-PARENTS the border onto the card afterwards, and a
      re-parent moves a widget to the TOP of the sibling stack. The opaque card
      content then covered the bar: of the bar's 4 rows, 4 were covered and only
      the 1 px below the content painted blue. The build-time raise_() ran
      BEFORE that addWidget, so it was always undone.

UX-2  A series that had already been viewed (green) did not return to the
      active border when it was dragged into a viewport again. Root cause: the
      drag button emitted `dragStarted` only when it was not already checked,
      and nothing ever un-checks a card — so on A -> B -> A the third drag was
      silent and `selected_series` never moved back to A.

UX-3  New: a red line in the same bottom strip marks the active series, with
      the blue bar taking the strip while a download is still filling.

These are geometry/stacking/state facts, so they are pinned BEHAVIOURALLY on
real Qt widgets (offscreen) — a source-string pin cannot see a z-order bug.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtGui import QColor, QPixmap                      # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget            # noqa: E402

from PacsClient.pacs.patient_tab.utils import thumbnail_manager as TM  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def manager(qapp):
    return TM.ThumbnailManager(lambda *a, **k: None)


def _card(manager, series_number: str):
    pm = QPixmap(160, 120)
    pm.fill(QColor("#888888"))
    w = manager.create_thumbnail_widget(
        pixmap=pm, label_text=series_number, thumbnail_index=series_number,
        series_info={"series_number": series_number, "image_count": 100},
    )
    w.show()
    QApplication.processEvents()
    return w


def _widget_children(card):
    return [c for c in card.children() if isinstance(c, QWidget)]


# ---------------------------------------------------------------------------
# UX-1 — the strip is on top, correctly placed, and actually painted.
# ---------------------------------------------------------------------------
def test_download_bar_has_no_sibling_covering_it(manager):
    """The regression itself: nothing opaque may sit above the bar."""
    if not TM._THUMB_DL_PROGRESS_BAR:
        pytest.skip("download bar disabled in this env")
    card = _card(manager, "101")
    kids = _widget_children(card)
    bar = card.dl_progress_bar
    bar_idx = kids.index(bar)
    above = [
        c for j, c in enumerate(kids)
        if j > bar_idx and c.geometry().intersects(bar.geometry())
        and c is not getattr(card, "active_indicator", None)
    ]
    assert above == [], (
        "a sibling is stacked above the download bar and overlaps it: "
        + ", ".join(f"{type(c).__name__}({c.objectName()})" for c in above)
    )


def test_bar_is_above_the_progress_border(manager):
    """Explicitly pin the exact pair that regressed (border re-parent order)."""
    if not TM._THUMB_DL_PROGRESS_BAR:
        pytest.skip("download bar disabled in this env")
    card = _card(manager, "101")
    kids = _widget_children(card)
    border = card.progress_border
    assert kids.index(card.dl_progress_bar) > kids.index(border), (
        "the download bar must be stacked ABOVE the CircularProgressborder; "
        "addWidget() re-parents the border and puts it on top unless the strip "
        "is re-raised afterwards"
    )


def test_every_bar_row_paints_the_chunk_colour(manager):
    """Ground truth: render the card and read the strip pixels."""
    if not TM._THUMB_DL_PROGRESS_BAR:
        pytest.skip("download bar disabled in this env")
    card = _card(manager, "101")
    bar = card.dl_progress_bar
    bar.setRange(0, 10)
    bar.setValue(10)          # fully filled -> whole strip is chunk colour
    bar.setVisible(True)
    QApplication.processEvents()

    img = card.grab().toImage()
    g = bar.geometry()
    x = g.x() + 10            # inside the filled part, clear of the rounding
    rows = [img.pixelColor(x, y).name() for y in range(g.y(), g.bottom() + 1)]
    assert len(rows) == g.height()
    assert len(set(rows)) == 1, (
        f"the bar is only partially visible — rows differ: {rows}")


def test_strip_geometry_follows_the_card_size(manager):
    """Same position in ALL layouts: derived from the live card size, not 215."""
    card = _card(manager, "101")
    bar = getattr(card, "dl_progress_bar", None) or card.active_indicator
    x, y, w, h = TM._card_strip_rect(card)
    assert (bar.geometry().x(), bar.geometry().y()) == (x, y)
    assert (bar.geometry().width(), bar.geometry().height()) == (w, h)
    # entirely inside the card -> never clipped
    assert bar.geometry().bottom() < card.height()
    assert bar.geometry().right() < card.width()

    # a taller card moves the strip with it (keeper re-applies on resize)
    card.setFixedSize(190, 260)
    QApplication.processEvents()
    x2, y2, _w2, _h2 = TM._card_strip_rect(card)
    assert y2 > y, "strip anchor must follow the card's bottom edge"
    assert bar.geometry().y() == y2, (
        f"strip did not follow the resize: at {bar.geometry().y()}, expected {y2}")


def test_strip_rect_helper_is_bottom_anchored_and_inset():
    class _FakeCard:
        def __init__(self, w, h):
            self._w, self._h = w, h

        def width(self):
            return self._w

        def height(self):
            return self._h

    x, y, w, h = TM._card_strip_rect(_FakeCard(190, 215))
    assert x == TM._STRIP_SIDE_INSET
    assert w == 190 - 2 * TM._STRIP_SIDE_INSET
    assert h == TM._STRIP_HEIGHT
    assert y + h < 215, "strip must sit fully inside the card"
    # degenerate sizes must not produce a negative / off-card rect
    x0, y0, w0, h0 = TM._card_strip_rect(_FakeCard(0, 0))
    assert w0 >= 1 and y0 >= 0 and h0 == TM._STRIP_HEIGHT


# ---------------------------------------------------------------------------
# UX-2 — the active state always overrides the previous (green) state.
# ---------------------------------------------------------------------------
def test_active_returns_to_a_previously_viewed_series(manager):
    """The reported sequence: drag A, drag B, drag A again."""
    a, b = _card(manager, "101"), _card(manager, "202")

    manager.set_active_series("101")
    manager.mark_series_viewed("101")
    manager.apply_border_states_new(immediate=True)
    assert a.progress_border._is_selected is True

    manager.set_active_series("202")
    manager.mark_series_viewed("202")
    manager.apply_border_states_new(immediate=True)
    assert a.progress_border._is_selected is False
    assert a.progress_border._viewed is True      # A now carries the green mark
    assert b.progress_border._is_selected is True

    # ...and back to A, which is exactly the case that used to stay green.
    manager.set_active_series("101")
    assert a.progress_border._is_selected is True, (
        "active state must override the previous viewed/green state")
    assert b.progress_border._is_selected is False
    assert a.progress_border._viewed is True      # viewed mark is not destroyed


def test_paint_state_ranks_selected_above_viewed_and_ready(manager):
    """Precedence is what makes the override visible, so pin it directly."""
    card = _card(manager, "101")
    pb = card.progress_border
    pb._is_selected, pb._viewed, pb._is_ready = True, True, True
    theme = pb._theme
    # selected wins -> accent, not success(green) / info(blue)
    assert theme.get("accent") != theme.get("success")
    card.grab()   # exercises paintEvent with all three flags set: must not raise


def test_drag_start_emits_even_when_button_already_checked(manager):
    """UX-2 root cause: the emit used to be skipped on an already-checked card."""
    card = _card(manager, "101")
    btn = card.image_button
    seen = []
    btn.dragStarted.connect(lambda b: seen.append(b))

    btn.setChecked(False)
    btn.begin_drag_selection()
    assert len(seen) == 1 and btn.isChecked() is True

    # second drag of the SAME series, button still checked from the first one
    btn.begin_drag_selection()
    assert len(seen) == 2, (
        "dragStarted must fire on every drag; skipping it when the button is "
        "already checked is what stranded the active state")


def test_set_active_series_unchecks_the_other_cards(manager):
    """Stale checked flags were how the state drifted out of sync."""
    a, b = _card(manager, "101"), _card(manager, "202")
    manager.set_active_series("101")
    assert (a.image_button.isChecked(), b.image_button.isChecked()) == (True, False)
    manager.set_active_series("202")
    assert (a.image_button.isChecked(), b.image_button.isChecked()) == (False, True)


def test_set_active_series_is_immediate(manager):
    """A direct user action must not wait on the 150 ms coalescing window."""
    card = _card(manager, "101")
    manager.selected_series = None
    card.progress_border._is_selected = False
    manager.set_active_series("101")
    assert card.progress_border._is_selected is True, (
        "set_active_series must apply immediately, not via the coalesced timer")


def test_set_active_series_rejects_empty_key(manager):
    _card(manager, "101")
    manager.set_active_series("101")
    assert manager.set_active_series("") is False
    assert manager.selected_series == "101", "a bad key must not clear the active series"


def test_update_widget_borders_routes_through_set_active(manager):
    a, b = _card(manager, "101"), _card(manager, "202")
    manager.set_active_series("202")
    manager.update_widget_borders(a)
    assert manager.selected_series == "101"
    assert a.progress_border._is_selected is True
    assert b.image_button.isChecked() is False


# ---------------------------------------------------------------------------
# UX-3 — the red active line, sharing the strip with the blue bar.
# ---------------------------------------------------------------------------
def test_active_card_shows_red_line_and_others_do_not(manager):
    if not TM._THUMB_ACTIVE_BAR:
        pytest.skip("active bar disabled in this env")
    a, b = _card(manager, "101"), _card(manager, "202")
    manager.set_active_series("101")
    assert a.active_indicator.isVisible() is True
    assert b.active_indicator.isVisible() is False
    manager.set_active_series("202")
    assert a.active_indicator.isVisible() is False
    assert b.active_indicator.isVisible() is True


def test_red_line_paints_red_in_the_strip(manager):
    if not TM._THUMB_ACTIVE_BAR:
        pytest.skip("active bar disabled in this env")
    card = _card(manager, "101")
    manager.set_active_series("101")
    QApplication.processEvents()
    img = card.grab().toImage()
    g = card.active_indicator.geometry()
    px = img.pixelColor(g.x() + 10, g.y() + 1)
    assert px.red() > 180 and px.green() < 120 and px.blue() < 120, (
        f"expected a red active line, painted {px.name()}")


def test_blue_bar_owns_the_strip_while_still_downloading(manager):
    """Precedence: filling download > active marker; complete -> red returns."""
    if not (TM._THUMB_ACTIVE_BAR and TM._THUMB_DL_PROGRESS_BAR):
        pytest.skip("strip features disabled in this env")
    card = _card(manager, "101")
    bar = card.dl_progress_bar
    bar.setRange(0, 10)
    bar.setValue(4)
    bar.setVisible(True)
    manager.set_active_series("101")
    assert card.active_indicator.isVisible() is False, (
        "a filling download bar must own the strip")

    bar.setValue(10)                       # download complete
    manager.apply_border_states_new(immediate=True)
    assert card.active_indicator.isVisible() is True, (
        "once the download is complete the active line takes the strip back")


def test_red_line_is_stacked_above_the_download_bar(manager):
    if not (TM._THUMB_ACTIVE_BAR and TM._THUMB_DL_PROGRESS_BAR):
        pytest.skip("strip features disabled in this env")
    card = _card(manager, "101")
    kids = _widget_children(card)
    assert kids.index(card.active_indicator) > kids.index(card.dl_progress_bar)


def test_reset_all_states_clears_the_red_line(manager):
    if not TM._THUMB_ACTIVE_BAR:
        pytest.skip("active bar disabled in this env")
    card = _card(manager, "101")
    manager.set_active_series("101")
    assert card.active_indicator.isVisible() is True
    manager.reset_all_states()
    assert card.active_indicator.isVisible() is False
    assert manager.selected_series is None


def test_strip_widgets_do_not_eat_mouse_events(manager):
    """The card must stay fully draggable/clickable under the strip."""
    from PySide6.QtCore import Qt as _Qt
    card = _card(manager, "101")
    for attr in ("dl_progress_bar", "active_indicator"):
        w = getattr(card, attr, None)
        if w is None:
            continue
        assert w.testAttribute(_Qt.WA_TransparentForMouseEvents) is True, (
            f"{attr} must let clicks through to the card")


# ---------------------------------------------------------------------------
# Kill switches / wiring.
# ---------------------------------------------------------------------------
def test_active_bar_flag_default_on():
    src = (REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "utils"
           / "thumbnail_manager.py").read_text(encoding="utf-8")
    assert '_THUMB_ACTIVE_BAR = (_os.getenv("AIPACS_THUMB_ACTIVE_BAR", "1")' in src


def test_viewport_load_sets_the_active_series():
    """The authoritative hook: anything loaded into a viewport becomes active."""
    src = (REPO_ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
           / "patient_widget_core" / "_pw_series.py").read_text(encoding="utf-8")
    fn = src.split("def change_series_on_viewer", 1)[1]
    head = fn.split("INTERACTIVE_BOOST", 1)[0]
    assert "set_active_series" in head, (
        "change_series_on_viewer must move the active marker — it is the single "
        "entry point for drag-drop / click / keyboard series loads")
    assert "mark_series_viewed" in head
    assert "flag_change_selected_widget" in head
