"""Notifications and filter chips — the two "built but unreachable" wins.

The sync engine has de-duplicated events, persisted the cursor and kept a slow
watch on a hidden tab since day one, and `eventsArrived` was connected to
nothing: the console only worked while somebody was staring at it. The `Filters`
model was complete and only `term` was reachable.

Named after the failures they prevent, per the module's own test register.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from modules.aipacs_chat.services.models import ConsoleEvent  # noqa: E402
from modules.aipacs_chat.ui.notifications import (  # noqa: E402
    MAX_VISIBLE,
    NotificationStack,
)


@pytest.fixture
def qapp():
    yield QApplication.instance() or QApplication([])


def _event(key: str, kind: str = "message", case: int = 7) -> ConsoleEvent:
    return ConsoleEvent(key=key, kind=kind, case=case, who="A patient",
                        title="New message", body="Hello",
                        url="https://ai-pacs.com/consult-form/forms-panel/inbox/7")


# ── banners ──────────────────────────────────────────────────────────────────
def test_a_message_event_raises_one_banner(qapp):
    host = QWidget()
    stack = NotificationStack(host)
    try:
        stack.show_events([_event("e1")])
        assert len(stack._banners) == 1
    finally:
        host.deleteLater()


def test_a_status_event_raises_no_banner(qapp):
    """`status` is usually the operator's own click echoing back, and
    `unsubmitted` is a standing condition. Neither may interrupt."""
    host = QWidget()
    stack = NotificationStack(host)
    try:
        stack.show_events([_event("e2", kind="status"),
                           _event("e3", kind="unsubmitted")])
        assert stack._banners == []
    finally:
        host.deleteLater()


def test_banners_are_capped_so_a_burst_is_not_a_wall(qapp):
    host = QWidget()
    stack = NotificationStack(host)
    try:
        stack.show_events([_event(f"e{i}") for i in range(MAX_VISIBLE + 4)])
        assert len(stack._banners) == MAX_VISIBLE
    finally:
        host.deleteLater()


def test_clicking_a_banner_opens_the_case_BY_ID_not_by_url(qapp):
    """`ConsoleEvent.url` is an absolute WEB console address. Following it
    would throw the operator out of the workstation into a browser session
    they are not signed in to."""
    host = QWidget()
    stack = NotificationStack(host)
    seen = []
    stack.caseRequested.connect(seen.append)
    try:
        stack.show_events([_event("e9", case=42)])
        banner = stack._banners[0]
        banner.activated.emit(banner._case)
        assert seen == [42]
    finally:
        host.deleteLater()


def test_a_banner_never_steals_focus(qapp):
    """A modal — or anything focusable — interrupting a radiologist mid-report
    is worse than not announcing at all."""
    from PySide6.QtCore import Qt

    host = QWidget()
    stack = NotificationStack(host)
    try:
        stack.show_events([_event("e10")])
        banner = stack._banners[0]
        assert banner.focusPolicy() == Qt.NoFocus
        assert banner.testAttribute(Qt.WA_ShowWithoutActivating)
    finally:
        host.deleteLater()


def test_dismissing_retires_the_banner(qapp):
    host = QWidget()
    stack = NotificationStack(host)
    try:
        stack.show_events([_event("e11")])
        stack._banners[0]._dismiss()
        assert stack._banners == []
    finally:
        host.deleteLater()


# ── the widget wiring ────────────────────────────────────────────────────────
def test_the_widget_actually_connects_eventsArrived():
    """The bug this file exists for: the signal fired into nothing."""
    import inspect

    from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget

    src = inspect.getsource(AiPacsChatWidget._connect_repository)
    assert "eventsArrived" in src
    assert "setNotificationsEnabled" in src


def test_notification_click_handler_uses_case_not_url():
    import inspect

    from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget

    src = inspect.getsource(AiPacsChatWidget._on_notification_activated)
    assert "_on_case_activated" in src
    # Compare CODE, not prose — the docstring names `event.url` deliberately,
    # to stop a future reader "fixing" the module by following it.
    doc = inspect.getdoc(AiPacsChatWidget._on_notification_activated) or ""
    code = src
    for line in doc.splitlines():
        code = code.replace(line, "")
    assert ".url" not in code


# ── filter chips ─────────────────────────────────────────────────────────────
def test_chips_are_checkable_and_and_together(qapp, monkeypatch):
    """Faceted, not mutually exclusive — "unread AND online" is the most
    useful question an operator can ask, and the old chips could not ask it."""
    from dataclasses import replace

    from modules.aipacs_chat.services.models import Filters

    filters = Filters()
    filters = replace(filters, attention=("unread",))
    filters = replace(filters, presence="online")
    pairs = filters.as_query_pairs()
    assert ("attn[]", "unread") in pairs
    assert ("presence", "online") in pairs


def test_unpriced_chip_uses_the_servers_own_value():
    """The server calls it `none`; the label says "No price" for humans."""
    from dataclasses import replace

    from modules.aipacs_chat.services.models import Filters

    pairs = replace(Filters(), price="none").as_query_pairs()
    assert ("price", "none") in pairs


def test_defaults_are_omitted_from_the_query():
    from modules.aipacs_chat.services.models import Filters

    assert Filters().as_query_pairs() == []


def test_search_and_chips_do_not_overwrite_each_other():
    """Both must go through the one `_set_filters`, or typing in the search
    box would silently clear the chips (and vice versa)."""
    import inspect

    from modules.aipacs_chat.ui.chat_widget import AiPacsChatWidget

    search = inspect.getsource(AiPacsChatWidget._apply_search)
    assert "_set_filters" in search
    for name in ("_toggle_attention", "_toggle_online", "_toggle_unpriced"):
        assert "_set_filters" in inspect.getsource(getattr(AiPacsChatWidget, name))
