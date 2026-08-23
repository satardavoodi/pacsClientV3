"""Sending files: the pre-flight, the wire format, and what the composer does.

THE PRE-FLIGHT IS ALL-OR-NOTHING. Four files arriving and a fifth failing is
worse than nothing arriving, because the operator has no way to tell the
difference from their side of the conversation.

NOTHING IS LOST TO A FAILED SEND. The composer holds the text AND the files
until the server confirms, and puts both back if it does not.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.services import attachments  # noqa: E402
from modules.aipacs_chat.ui.composer import Composer  # noqa: E402


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _file(tmp_path, name, size=16):
    path = tmp_path / name
    path.write_bytes(b"x" * size)
    return path


# ── the pre-flight ───────────────────────────────────────────────────────────


def test_nothing_selected_is_not_an_error(tmp_path):
    items, error = attachments.inspect([])
    assert items == ()
    assert error == ""


def test_a_normal_selection_is_read_whole(tmp_path):
    items, error = attachments.inspect([_file(tmp_path, "a.pdf"), _file(tmp_path, "b.png")])
    assert error == ""
    assert [i.name for i in items] == ["a.pdf", "b.png"]
    assert all(i.data for i in items)
    assert items[1].mime == "image/png"


def test_too_many_files_refuses_the_whole_selection(tmp_path):
    picked = [_file(tmp_path, f"f{n}.pdf") for n in range(attachments.MAX_FILES + 1)]
    items, error = attachments.inspect(picked)
    assert items == ()
    assert str(attachments.MAX_FILES) in error


def test_one_oversized_file_refuses_the_whole_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 32)
    small = _file(tmp_path, "small.pdf", 8)
    big = _file(tmp_path, "big.pdf", 64)

    items, error = attachments.inspect([small, big])
    assert items == (), "the small file would have been sent on its own"
    assert "big.pdf" in error


def test_the_total_is_checked_as_well_as_each_file(tmp_path, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_TOTAL_BYTES", 40)
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 40)
    items, error = attachments.inspect(
        [_file(tmp_path, "a.pdf", 30), _file(tmp_path, "b.pdf", 30)]
    )
    assert items == ()
    assert "together" in error


def test_an_empty_file_is_refused(tmp_path):
    items, error = attachments.inspect([_file(tmp_path, "nothing.pdf", 0)])
    assert items == ()
    assert "empty" in error


def test_a_missing_file_is_refused_by_name(tmp_path):
    items, error = attachments.inspect([tmp_path / "gone.pdf"])
    assert items == ()
    assert "gone.pdf" in error


# ── the wire format ──────────────────────────────────────────────────────────


class _RecordingWebClient:
    base_url = "https://example.invalid/consult-form"

    def __init__(self):
        self.calls = []

    def request_json(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return {"message": {"id": 1, "sender_type": "staff", "type": "file", "body": ""}}


def _chat_client(web):
    from modules.aipacs_chat.services.chat_client import ChatClient

    return ChatClient(web, aipacs_user="drv")


def test_a_text_only_send_is_still_json(tmp_path):
    web = _RecordingWebClient()
    _chat_client(web).send(41, "hello")

    method, path, kwargs = web.calls[0]
    assert (method, path) == ("POST", "/chat/cases/41/send")
    assert kwargs.get("json_body") == {"body": "hello"}
    assert "files" not in kwargs, "a plain reply must not become a multipart upload"


def test_a_send_with_files_is_multipart_and_carries_the_caption(tmp_path):
    web = _RecordingWebClient()
    items, error = attachments.inspect([_file(tmp_path, "report.pdf")])
    assert error == ""

    _chat_client(web).send(41, "the report", attachments=items, is_report=True)

    _, _, kwargs = web.calls[0]
    assert kwargs.get("json_body") is None
    assert kwargs["data"]["body"] == "the report"
    assert kwargs["data"]["is_report"] == "1", "Laravel's boolean rule reads '1', not 'True'"
    assert [name for name, _ in kwargs["files"]] == ["files[]"]
    assert kwargs["timeout"] == attachments.UPLOAD_TIMEOUT_SEC


# ── the composer ─────────────────────────────────────────────────────────────


def test_attaching_enables_send_without_any_text(qapp, tmp_path):
    composer = Composer()
    composer.set_enabled_for_case(True)
    assert not composer.send_button.isEnabled()

    composer.add_attachments([str(_file(tmp_path, "a.pdf"))])
    assert composer.send_button.isEnabled(), "a file with no caption is a message"
    assert composer.tray.isVisible() or composer.tray.isVisibleTo(composer)


def test_the_final_report_box_needs_a_file(qapp, tmp_path):
    composer = Composer()
    composer.set_enabled_for_case(True)
    assert not composer.report_check.isEnabled()

    composer.add_attachments([str(_file(tmp_path, "a.pdf"))])
    assert composer.report_check.isEnabled()

    composer.clear_attachments()
    assert not composer.report_check.isEnabled()
    assert not composer.report_check.isChecked()


def test_the_sixth_file_is_refused_with_a_sentence(qapp, tmp_path):
    composer = Composer()
    composer.set_enabled_for_case(True)
    said = []
    composer.attachmentRejected.connect(said.append)

    composer.add_attachments(
        [str(_file(tmp_path, f"f{n}.pdf")) for n in range(attachments.MAX_FILES + 1)]
    )

    assert len(composer.attachments()) == attachments.MAX_FILES
    assert said and str(attachments.MAX_FILES) in said[0]


def test_the_same_file_twice_is_attached_once(qapp, tmp_path):
    composer = Composer()
    composer.set_enabled_for_case(True)
    path = str(_file(tmp_path, "a.pdf"))

    composer.add_attachments([path, path])
    assert composer.attachments() == [path]


def test_sending_with_files_emits_the_files_signal_not_the_plain_one(qapp, tmp_path):
    composer = Composer()
    composer.set_enabled_for_case(True)
    plain, rich = [], []
    composer.sendRequested.connect(plain.append)
    composer.sendWithFilesRequested.connect(lambda b, p, r: rich.append((b, list(p), r)))

    path = str(_file(tmp_path, "a.pdf"))
    composer.add_attachments([path])
    composer.editor.setPlainText("please see attached")
    composer.report_check.setChecked(True)
    composer._on_send()

    assert plain == []
    assert rich == [("please see attached", [path], True)]
    assert composer.attachments() == [], "the tray must empty when the send starts"


def test_a_failed_send_puts_the_files_back_too(qapp, tmp_path):
    composer = Composer()
    composer.set_enabled_for_case(True)
    path = str(_file(tmp_path, "a.pdf"))
    composer.add_attachments([path])
    composer.editor.setPlainText("here")
    composer._on_send()

    assert composer.attachments() == []
    composer.restore_pending()

    assert composer.text() == "here"
    assert composer.attachments() == [path], "the operator would have to find them again"


def test_leaving_a_conversation_drops_its_attachments(qapp, tmp_path):
    """One patient's files must never follow the operator into another thread."""
    composer = Composer()
    composer.set_enabled_for_case(True)
    composer.add_attachments([str(_file(tmp_path, "a.pdf"))])

    composer.set_enabled_for_case(False)
    assert composer.attachments() == []
