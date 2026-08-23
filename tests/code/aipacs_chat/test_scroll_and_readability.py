"""Scrolling that stays where it was put, and a transcript that can be read.

THE SCROLLBAR BUG THIS PINS DOWN. sizeHint and paint have to measure a bubble
against the SAME width. When they do not, every row is reserved several times
the height it draws into: the content looks like it has holes in it, the
scrollbar's range is a multiple of the real document, and the thumb jumps a
screenful at a time instead of settling in the middle. The first test below
fails the moment those two numbers can disagree again.

THE LIST BUG THIS PINS DOWN. The conversation model used to call
beginResetModel on every poll — up to five times a minute — and a reset throws
away the view's scroll position. It read as "the list keeps jumping to the top"
and it was not a scrolling bug at all.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem  # noqa: E402

from modules.aipacs_chat.services.models import ChatMessage, ConversationRow  # noqa: E402
from modules.aipacs_chat.ui.conversation_list import ConversationListView  # noqa: E402
from modules.aipacs_chat.ui.message_view import (  # noqa: E402
    DAY_BREAK_ROLE,
    DAY_H,
    STATUS_DELIVERED,
    STATUS_SEEN,
    STATUS_SENT,
    ChatView,
    MessageDelegate,
    MessageModel,
)


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
LONG = " ".join(["the quick brown fox jumps over the lazy dog"] * 12)


def _message(mid=1, body="hello", *, outbound=True, at=NOW, **extra):
    raw = {
        "id": mid,
        "sender_type": "staff" if outbound else "patient",
        "type": "text",
        "body": body,
        "at": at.isoformat(),
    }
    raw.update(extra)
    return ChatMessage.parse(raw)


def _row(case_id, **overrides):
    fields = {
        "id": case_id,
        "label": f"Patient {case_id}",
        "ref": str(9400000 + case_id),
        "unread": 0,
        "online": False,
        "ago": "2m",
        "preview": "hello",
        "sender": "patient",
        "status": "awaiting_images",
        "tone": "wait",
    }
    fields.update(overrides)
    return ConversationRow.parse(fields)


# ── the transcript measures what it draws ────────────────────────────────────


def test_a_bubble_is_measured_against_the_viewport_not_the_item_rect(qapp):
    """The whole scrollbar problem, in one assertion.

    sizeHint is asked before a row has a laid-out rectangle. If it falls back
    to option.rect it measures a long message against a width the paint pass
    will never use, and reserves a row far taller than the bubble drawn in it.
    """
    model = MessageModel()
    delegate = MessageDelegate()
    model.replace([_message(1, LONG)])

    delegate.set_viewport_width(900)

    wide = QStyleOptionViewItem()
    wide.rect = QRect(0, 0, 900, 40)
    narrow = QStyleOptionViewItem()
    narrow.rect = QRect(0, 0, 120, 40)   # what a pre-layout call can hand over

    index = model.index(0, 0)
    assert delegate.sizeHint(wide, index).height() == delegate.sizeHint(narrow, index).height(), (
        "the row's height still depends on option.rect, so sizeHint and paint "
        "can disagree and the scrollbar will jump again"
    )


def test_a_wider_transcript_makes_shorter_bubbles(qapp):
    """Sanity on the other side: the width must still matter."""
    model = MessageModel()
    delegate = MessageDelegate()
    model.replace([_message(1, LONG)])
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 900, 40)
    index = model.index(0, 0)

    delegate.set_viewport_width(1200)
    wide = delegate.sizeHint(option, index).height()
    delegate.set_viewport_width(400)
    narrow = delegate.sizeHint(option, index).height()

    assert narrow > wide


def test_the_view_hands_the_delegate_its_real_width(qapp):
    view = ChatView()
    view.resize(880, 500)
    view.show()
    qapp.processEvents()

    assert view._delegate._viewport_width == view.viewport().width()
    assert view._delegate._viewport_width > 0

    view.close()


# ── following, and not being dragged ─────────────────────────────────────────


def test_new_messages_do_not_move_a_reader_who_scrolled_up(qapp):
    view = ChatView()
    view.resize(600, 260)
    view.show()
    qapp.processEvents()

    view.replace([_message(n, LONG, at=NOW) for n in range(1, 15)])
    qapp.processEvents()

    bar = view.verticalScrollBar()
    bar.setValue(0)                       # the operator reads the beginning
    qapp.processEvents()

    view.append([_message(99, "a new reply", at=NOW)])
    qapp.processEvents()

    assert bar.value() == 0, "the view yanked the reader back to the bottom"
    assert view._pending_new == 1
    assert view._jump.isVisible()
    assert "1 new message" in view._jump.text()

    view.close()


def test_a_reader_at_the_bottom_keeps_following(qapp):
    view = ChatView()
    view.resize(600, 260)
    view.show()
    qapp.processEvents()

    view.replace([_message(n, LONG, at=NOW) for n in range(1, 15)])
    qapp.processEvents()

    view.append([_message(99, "a new reply", at=NOW)])
    qapp.processEvents()

    assert view._pending_new == 0
    assert not view._jump.isVisible()

    view.close()


def test_the_jump_button_takes_the_reader_to_the_end(qapp):
    view = ChatView()
    view.resize(600, 260)
    view.show()
    qapp.processEvents()

    view.replace([_message(n, LONG, at=NOW) for n in range(1, 15)])
    qapp.processEvents()
    view.verticalScrollBar().setValue(0)
    view.append([_message(99, "new", at=NOW)])
    qapp.processEvents()

    view._on_jump_clicked()
    qapp.processEvents()

    assert view._pending_new == 0
    assert not view._jump.isVisible()

    view.close()


# ── the conversation list stays put ──────────────────────────────────────────


def test_an_unchanged_page_does_not_reset_the_list(qapp):
    view = ConversationListView()
    rows = [_row(n) for n in range(1, 40)]
    view.set_rows(rows)

    reset = []
    view._model.modelReset.connect(lambda: reset.append(True))

    # The same conversations again, with a message count changed on one — the
    # shape of an ordinary poll.
    view.set_rows([_row(n, unread=3 if n == 5 else 0) for n in range(1, 40)])

    assert reset == [], "a poll reset the model, which is what loses the scroll position"


def test_the_scroll_position_survives_a_page_that_did_change(qapp):
    view = ConversationListView()
    view.resize(320, 300)
    view.show()
    qapp.processEvents()

    view.set_rows([_row(n) for n in range(1, 60)])
    qapp.processEvents()

    bar = view.verticalScrollBar()
    bar.setValue(bar.maximum() // 2)
    parked = bar.value()
    assert parked > 0

    # A genuinely different page: one conversation arrived at the top.
    view.set_rows([_row(999)] + [_row(n) for n in range(1, 60)])
    qapp.processEvents()

    assert abs(bar.value() - parked) <= 4, "the list jumped when a row arrived"

    view.close()


def test_the_open_conversation_stays_selected_across_a_poll(qapp):
    view = ConversationListView()
    view.set_rows([_row(n) for n in range(1, 10)])
    view.select_case(4)

    view.set_rows([_row(n) for n in reversed(range(1, 10))])

    assert view.current_case_id() == 4


# ── status, day bands, readability ───────────────────────────────────────────


def test_the_three_message_states_come_from_the_two_receipts(qapp):
    model = MessageModel()
    message = _message(1, "hello", at=NOW)
    model.replace([message])

    assert model.status_of(message) == STATUS_SENT

    model.set_receipts(NOW + timedelta(seconds=5), None)
    assert model.status_of(message) == STATUS_DELIVERED

    model.set_receipts(NOW + timedelta(seconds=5), NOW + timedelta(seconds=9))
    assert model.status_of(message) == STATUS_SEEN


def test_a_receipt_older_than_the_message_does_not_promote_it(qapp):
    model = MessageModel()
    message = _message(1, "hello", at=NOW)
    model.replace([message])
    model.set_receipts(NOW - timedelta(minutes=1), NOW - timedelta(minutes=1))

    assert model.status_of(message) == STATUS_SENT


def test_a_message_without_a_timestamp_is_never_promoted(qapp):
    model = MessageModel()
    message = _message(1, "hello", at=NOW)
    object.__setattr__(message, "at", None)
    model.replace([message])
    model.set_receipts(NOW, NOW)

    assert model.status_of(message) == STATUS_SENT


def test_a_day_band_opens_each_day_and_only_the_first_message_of_it(qapp):
    yesterday = NOW - timedelta(days=1)
    model = MessageModel()
    model.replace([
        _message(1, "one", at=yesterday),
        _message(2, "two", at=yesterday + timedelta(minutes=5)),
        _message(3, "three", at=NOW),
    ])

    labels = [model.data(model.index(r, 0), DAY_BREAK_ROLE) for r in range(3)]
    assert labels[0]
    assert labels[1] == ""
    assert labels[2]
    assert labels[0] != labels[2]


def test_a_day_band_adds_its_own_height_to_the_row(qapp):
    model = MessageModel()
    delegate = MessageDelegate()
    delegate.set_viewport_width(800)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 800, 40)

    model.replace([
        _message(1, "one", at=NOW),
        _message(2, "one", at=NOW + timedelta(minutes=1)),
    ])
    banded = delegate.sizeHint(option, model.index(0, 0)).height()
    plain = delegate.sizeHint(option, model.index(1, 0)).height()

    assert banded - plain == DAY_H


def test_the_two_sides_of_the_conversation_are_visibly_different(qapp):
    """Not a taste question — a measured one.

    The patient's bubble was painted one step off the pane background, which is
    why it read as no bubble at all. Both surfaces must now be clearly clear of
    the background AND clearly clear of each other.
    """
    from PySide6.QtGui import QColor

    from modules.aipacs_chat.ui.message_view import _bubble_palette

    tokens = {"panel_bg": "#232830", "accent_soft": "#1d3a63"}
    palette = _bubble_palette(tokens)

    panel = QColor(tokens["panel_bg"])
    inbound = QColor(palette["inbound"])
    outbound = QColor(palette["outbound"])

    assert abs(inbound.lightness() - panel.lightness()) >= 12, (
        "the patient's bubble still disappears into the background"
    )
    # Different hue families, not just different lightness.
    assert abs(inbound.hue() - outbound.hue()) > 10 or abs(
        inbound.saturation() - outbound.saturation()
    ) > 40


def test_hovering_changes_a_bubble_without_changing_its_size(qapp):
    model = MessageModel()
    delegate = MessageDelegate()
    delegate.set_viewport_width(800)
    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 800, 40)
    model.replace([_message(1, LONG)])

    before = delegate.sizeHint(option, model.index(0, 0)).height()
    delegate.set_hovered(1)
    after = delegate.sizeHint(option, model.index(0, 0)).height()

    assert before == after, "a hover that reflows the transcript is a jumping transcript"
