"""The case panel's two actions, and where its links open.

THE INTERNAL BROWSER IS NOT OPTIONAL. Every http(s) link the workstation shows
opens inside the workstation. A QLabel with ``setOpenExternalLinks(True)``
hands the URL to the operating system without ever telling the application, so
the flag itself is the bug — asserted against below, because it is one word
and it is invisible in review.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from modules.aipacs_chat.ui.case_panel import CasePanel  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _detail(**overrides):
    detail = {
        "display_label": "Maria Rossi",
        "reference": "9400123",
        "status": "awaiting_images",
        "status_tone": "wait",
        "stage": {"label": "Waiting for images"},
        "summaries": {},
        "files": [
            {
                "id": 7,
                "original_name": "study.zip",
                "external_url": "https://ai-pacs.com/consult-form/f/abc",
                "short_url": "ai-pacs.com/f/abc",
                "storage_kind": "upload",
            }
        ],
        "email": "maria@example.com",
    }
    detail.update(overrides)
    return detail


def _buttons(panel):
    return panel._bodies["actions"].findChildren(QPushButton)


def test_the_actions_section_offers_pin_and_a_fresh_link(qapp):
    panel = CasePanel()
    panel.set_case(_detail())

    labels = [b.text() for b in _buttons(panel)]
    assert any("Pin this case" in text for text in labels)
    assert any("access link" in text for text in labels)


def test_a_pinned_case_offers_to_unpin(qapp):
    panel = CasePanel()
    panel.set_case(_detail(pinned=True))

    labels = [b.text() for b in _buttons(panel)]
    assert any("Unpin" in text for text in labels)


def test_the_pin_button_emits_the_signal_that_was_declared_and_never_used(qapp):
    panel = CasePanel()
    panel.set_case(_detail())
    seen = []
    panel.pinCaseRequested.connect(lambda: seen.append(True))

    for button in _buttons(panel):
        if "Pin this case" in button.text():
            button.click()
    assert seen == [True]


def test_the_rotate_button_emits_its_signal(qapp):
    panel = CasePanel()
    panel.set_case(_detail())
    seen = []
    panel.rotateLinkRequested.connect(lambda: seen.append(True))

    for button in _buttons(panel):
        if "access link" in button.text():
            button.click()
    assert seen == [True]


def test_no_row_opens_a_link_behind_the_applications_back(qapp):
    """setOpenExternalLinks hands the URL straight to the OS browser."""
    from PySide6.QtWidgets import QLabel

    panel = CasePanel()
    panel.set_case(_detail())

    for body in panel._bodies.values():
        for label in body.findChildren(QLabel):
            assert not label.openExternalLinks(), (
                "this link would leave the workstation without the application "
                "ever hearing about it"
            )


def test_an_activated_link_is_reported_for_the_internal_browser(qapp):
    panel = CasePanel()
    panel.set_case(_detail())
    seen = []
    panel.linkActivated.connect(seen.append)

    panel._bodies["imaging"].linkActivated.emit("https://ai-pacs.com/consult-form/f/abc")
    assert seen == ["https://ai-pacs.com/consult-form/f/abc"]
