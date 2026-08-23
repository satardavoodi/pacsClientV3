"""The transcript, the composer and the case panel.

The behaviours pinned here are the ones a screenshot cannot show: that a patch
lands on the right row, that a tick means what the server means, that Copy
copies the whole message and not the clamped text, and that a failed send puts
the operator's words back.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.services.models import ChatMessage, Reactions  # noqa: E402
from modules.aipacs_chat.ui.case_panel import CasePanel  # noqa: E402
from modules.aipacs_chat.ui.composer import Composer  # noqa: E402
from modules.aipacs_chat.ui.message_view import ChatView  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


NOW = datetime(2026, 8, 19, 14, 0, tzinfo=timezone.utc)


def _msg(mid, body="hello", sender="patient", at=None, **overrides):
    fields = {
        "id": mid,
        "sender_type": sender,
        "type": "text",
        "body": body,
        "at": at or NOW,
        "sender": "Dr Alizadeh" if sender == "staff" else None,
        "reactions": Reactions(),
    }
    fields.update(overrides)
    return ChatMessage(**fields)


# --- the transcript ---------------------------------------------------------


def test_messages_are_held_in_id_order_however_they_arrive(qapp):
    view = ChatView()
    view.replace([_msg(9), _msg(3), _msg(7)])

    ids = [view._model.message_at(view._model.index(i, 0)).id for i in range(3)]

    assert ids == [3, 7, 9]


def test_appending_a_message_the_model_already_holds_does_not_double_it(qapp):
    view = ChatView()
    view.replace([_msg(1), _msg(2)])

    view.append([_msg(2), _msg(3)])

    assert view.message_count() == 3


def test_a_revision_patches_the_row_in_place_rather_than_appending(qapp):
    """An edit is the same message, not a new one."""
    view = ChatView()
    view.replace([_msg(1, "typo"), _msg(2)])

    view.apply_revised([_msg(1, "fixed", edited=True)])

    assert view.message_count() == 2
    assert view.message_by_id(1).body == "fixed"
    assert view.message_by_id(1).edited is True


def test_a_revision_for_a_message_not_on_screen_is_ignored(qapp):
    view = ChatView()
    view.replace([_msg(1)])

    view.apply_revised([_msg(99, "from another conversation")])

    assert view.message_count() == 1


def test_a_cold_answer_replaces_rather_than_merges(qapp):
    view = ChatView()
    view.replace([_msg(1), _msg(2), _msg(3)])

    view.replace([_msg(10)])

    assert view.message_count() == 1
    assert view.message_by_id(1) is None


def test_read_at_drives_the_whole_tick_column(qapp):
    """One timestamp, not a per-message flag.

    The client already knows when each message was written, so one number
    re-derives every tick — including for messages that arrived earlier.
    """
    view = ChatView()
    view.replace([_msg(1, sender="staff", at=NOW - timedelta(minutes=5)),
                  _msg(2, sender="staff", at=NOW)])

    view.set_read_at(NOW - timedelta(minutes=1))

    assert view._model.read_at == NOW - timedelta(minutes=1)


def test_a_long_message_is_clamped_and_can_be_expanded(qapp):
    view = ChatView()
    long_body = "\n".join(f"line {i}" for i in range(60))
    view.replace([_msg(1, long_body)])

    from modules.aipacs_chat.ui.message_view import EXPANDED_ROLE

    index = view._model.index(0, 0)

    # Not expanded to begin with.
    assert view._model.data(index, EXPANDED_ROLE) is False

    view._model.toggle_expanded(1)
    assert view._model.data(index, EXPANDED_ROLE) is True


def test_the_model_keeps_the_whole_body_even_while_clamped(qapp):
    """Copy must copy everything.

    A "Read more" that silently truncates what you paste into a report is
    worse than no clamp at all.
    """
    view = ChatView()
    long_body = "\n".join(f"line {i}" for i in range(60))
    view.replace([_msg(1, long_body)])

    assert view.message_by_id(1).body == long_body
    assert view.message_by_id(1).body.count("\n") == 59


def test_a_withdrawn_message_stops_being_expandable(qapp):
    view = ChatView()
    long_body = "\n".join(f"line {i}" for i in range(60))
    view.replace([_msg(1, long_body)])
    view._model.toggle_expanded(1)

    view.apply_revised([_msg(1, "This message was deleted", removed=True)])

    from modules.aipacs_chat.ui.message_view import EXPANDED_ROLE

    assert view._model.data(view._model.index(0, 0), EXPANDED_ROLE) is False


# --- the composer -----------------------------------------------------------


def test_the_composer_keeps_the_text_until_the_send_is_confirmed(qapp):
    """There is no `sending` state on the wire — the composer owns it."""
    composer = Composer()
    composer.set_enabled_for_case(True)
    composer.editor.setPlainText("Your report is ready.")

    composer._on_send()
    assert composer.text() == "", "the box clears so the operator can keep typing"

    composer.restore_pending()
    assert composer.text() == "Your report is ready.", "a dropped packet must not eat a reply"


def test_a_confirmed_send_drops_the_pending_copy(qapp):
    composer = Composer()
    composer.set_enabled_for_case(True)
    composer.editor.setPlainText("hello")
    composer._on_send()

    composer.confirm_sent()
    composer.restore_pending()

    assert composer.text() == ""


def test_typing_state_is_reported_only_when_it_changes(qapp):
    composer = Composer()
    seen = []
    composer.hasTextChanged.connect(seen.append)

    composer.editor.setPlainText("a")
    composer.editor.setPlainText("ab")
    composer.editor.setPlainText("")

    assert seen == [True, False]


def test_only_manual_statuses_are_offered(qapp):
    """The flow service moves the rest; offering those invites a fight with it."""
    composer = Composer()
    composer.set_statuses([
        {"key": "paid", "label": "Paid", "manual_only": False},
        {"key": "in_reporting", "label": "In reporting", "manual_only": True},
        {"key": "spam", "label": "Spam", "manual_only": True},
    ])

    offered = [composer.status_box.itemData(i) for i in range(composer.status_box.count())]

    assert offered == [None, "in_reporting", "spam"]


def test_a_saved_reply_is_inserted_not_sent(qapp):
    """A template is a starting point; an operator almost always adds a line."""
    composer = Composer()
    composer.set_enabled_for_case(True)
    sent = []
    composer.sendRequested.connect(sent.append)

    composer.set_saved_replies([{"title": "Upload", "body": "Please send your study."}])
    composer.saved_reply_box.setCurrentIndex(1)
    composer._on_saved_reply(1)

    assert sent == []
    assert "Please send your study." in composer.text()


def test_the_price_picker_emits_a_tier_not_an_amount(qapp):
    """The amount-to-link pairing is owner-confirmed and lives on the server."""
    composer = Composer()
    tiers = []
    composer.priceRequested.connect(tiers.append)

    composer.set_pricing({"currency": "EUR", "tiers": [
        {"key": "basic", "label": "Basic Report", "amount": 49, "money": "€49"},
    ]})
    composer._on_price(1)

    assert tiers == ["basic"]


# --- the case panel ---------------------------------------------------------


def _detail(**overrides):
    payload = {
        "id": 41,
        "reference": "9400123",
        "display_label": "Maria Rossi",
        "status": "awaiting_images",
        "status_tone": "wait",
        "stage": {"label": "Waiting for your images", "note": "", "needs_action": True},
        "email": "maria@example.com",
        "phone": "+30 210 000 0000",
        "patient_online": True,
        "summaries": {
            "imaging": "Google Drive + 2 more",
            "drive": "Folder + 3 files",
            "location": "Athens, Greece",
            "case": "MRI · second opinion",
            "source": "Google Search → Brain MRI Second Opinion",
            "visit": "/mri · 4 pages · 6 min on site",
        },
        "location": {"line": "Athens, Attica", "country_code": "GR", "approximate": True},
        "files": [],
        "drive": {"linked": False, "suggested_name": "#9400123 — Maria Rossi"},
        "email_sends": [],
        "journey_steps": [],
    }
    payload.update(overrides)
    return payload


def test_every_section_keeps_its_answer_while_collapsed(qapp):
    """A collapsed section still answers its own question."""
    panel = CasePanel()
    panel.set_case(_detail())

    assert "Athens, Greece" in panel._sections["location"].text()
    assert "Google Drive" in panel._sections["imaging"].text()
    assert "MRI" in panel._sections["case"].text()


def test_the_panel_clears_between_conversations(qapp):
    """Leaving one patient's details up while the next loads is the one
    mistake this module must never make."""
    panel = CasePanel()
    panel.set_case(_detail())

    panel.clear()

    assert "Athens" not in panel._sections["location"].text()
    assert panel.header.text() == "No conversation selected"


def test_a_display_name_containing_markup_is_escaped(qapp):
    """Names are patient-supplied and these labels render rich text."""
    panel = CasePanel()
    panel.set_case(_detail(display_label="<b>injected</b>"))

    assert "&lt;b&gt;injected&lt;/b&gt;" in panel.header.text()


def test_mail_summarises_sent_versus_opened(qapp):
    panel = CasePanel()
    panel.set_case(_detail(email_sends=[
        {"kind_label": "Message sent by hand", "state": "opened", "state_label": "Opened"},
        {"kind_label": "Update notification", "state": "sent", "state_label": "Sent — not opened yet"},
    ]))

    assert panel._sections["mail"].text().endswith("2 sent · 1 opened")
