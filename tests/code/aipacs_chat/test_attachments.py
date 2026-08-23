"""Receiving an attachment: storage, the chip, and the download slot.

THE CASE THAT IS EASY TO MISS, and which has its own test below: a WITHDRAWN
file message keeps its row and loses its ``meta`` — the server nulls it on the
tombstone. Rendering a chip for it would offer the operator a download the
server answers with a 404.

Nothing here touches the network. The repository is handed a fake client, the
delegate is measured offscreen, and storage is pointed at a tmp_path.
"""

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.aipacs_chat.qt import workers  # noqa: E402
from modules.aipacs_chat.qt.repository import ChatRepository  # noqa: E402
from modules.aipacs_chat.services import storage  # noqa: E402
from modules.aipacs_chat.services.models import ChatMessage  # noqa: E402
from modules.aipacs_chat.ui.message_view import (  # noqa: E402
    ATTACH_H,
    attachment_of,
    human_size,
)


@pytest.fixture
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _wait_until(app, predicate, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return predicate()


def _file_message(**overrides):
    raw = {
        "id": 11,
        "sender_type": "patient",
        "type": "file",
        "body": "Here is the referral.",
        "at": "2026-08-22T09:00:00Z",
        "meta": {
            "file_id": 501,
            "file_name": "referral.pdf",
            "file_size": 240_000,
            "mime": "application/pdf",
            "is_image": False,
        },
    }
    raw.update(overrides)
    return ChatMessage.parse(raw)


# ── what counts as an attachment ─────────────────────────────────────────────


def test_a_file_message_carries_its_attachment():
    found = attachment_of(_file_message())
    assert found is not None
    assert found["file_id"] == 501
    assert found["file_name"] == "referral.pdf"
    assert found["size_text"]


def test_a_withdrawn_file_message_has_no_chip():
    """The server nulls ``meta`` on the tombstone. No meta, no download."""
    withdrawn = _file_message(meta=None, removed=True, body="")
    assert attachment_of(withdrawn) is None


def test_a_file_message_without_a_file_id_has_no_chip():
    assert attachment_of(_file_message(meta={"file_name": "x.pdf"})) is None


def test_a_text_message_has_no_chip():
    assert attachment_of(_file_message(type="text")) is None


def test_human_size_says_nothing_rather_than_zero():
    assert human_size(None) == ""
    assert human_size(0) == ""
    assert human_size("not a number") == ""
    assert human_size(900).endswith("B")
    assert "KB" in human_size(2048)
    assert "MB" in human_size(5 * 1024 * 1024)


# ── the chip takes room in the bubble ────────────────────────────────────────


def test_a_file_bubble_is_taller_than_the_same_text_bubble(qapp):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem

    from modules.aipacs_chat.ui.message_view import MessageDelegate, MessageModel

    model = MessageModel()
    delegate = MessageDelegate()

    option = QStyleOptionViewItem()
    option.rect = QRect(0, 0, 600, 80)

    # Three messages, all on the same day. ROW 0 CARRIES THE DAY BAND — the
    # first message of a transcript always opens a day — so the comparison is
    # made between rows 1 and 2, which differ only in the attachment.
    model.replace([
        _file_message(id=10, type="text", meta=None, body="anchor"),
        _file_message(id=11, type="text", meta=None),
        _file_message(id=12),
    ])
    without = delegate.sizeHint(option, model.index(1, 0)).height()
    with_file = delegate.sizeHint(option, model.index(2, 0)).height()

    assert with_file - without == ATTACH_H


# ── storage: untrusted names, and never a truncated cache hit ────────────────


@pytest.fixture
def chat_files(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "files_dir", lambda case_id=None: _mk(tmp_path, case_id))
    return tmp_path


def _mk(root, case_id):
    path = root / (f"case_{int(case_id)}" if case_id else "files")
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_a_patient_filename_never_escapes_the_case_folder():
    assert "/" not in storage.safe_name("../../etc/passwd")
    assert "\\" not in storage.safe_name(r"..\..\windows\system32\cmd.exe")
    assert storage.safe_name("  ") == "attachment"


def test_a_windows_device_name_is_defused():
    assert storage.safe_name("CON.txt").lower().startswith("_con")
    assert storage.safe_name("lpt1").lower().startswith("_lpt1")


def test_the_file_id_prefixes_the_name_so_two_patients_cannot_collide(chat_files):
    first = storage.attachment_path(7, 100, "report.pdf")
    second = storage.attachment_path(7, 101, "report.pdf")
    assert first != second
    assert first.name.startswith("100_")


def test_a_written_attachment_is_found_again_and_an_empty_one_is_not(chat_files):
    written = storage.write_attachment(7, 100, "report.pdf", b"%PDF-1.4 ...")
    assert written.exists()
    assert storage.cached_attachment(7, 100, "report.pdf") == written

    empty = storage.attachment_path(7, 200, "blank.pdf")
    empty.write_bytes(b"")
    assert storage.cached_attachment(7, 200, "blank.pdf") is None


# ── the repository slot ──────────────────────────────────────────────────────


class _FileClient:
    def __init__(self):
        self.calls = []
        self.threads = []

    def download_file(self, case_id, file_id):
        self.calls.append((case_id, file_id))
        self.threads.append(threading.current_thread())
        return b"bytes-for-%d" % file_id


def test_download_does_nothing_without_an_open_case(qapp):
    client = _FileClient()
    repo = ChatRepository("drv", client=client)
    repo.downloadFile(501, "referral.pdf")
    qapp.processEvents()
    assert client.calls == []


def test_download_runs_off_the_gui_thread_and_reports_the_path(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "files_dir", lambda case_id=None: _mk(tmp_path, case_id))

    client = _FileClient()
    repo = ChatRepository("drv", client=client)
    repo._engine.set_open_case(7)

    seen = []
    repo.fileDownloaded.connect(lambda fid, path: seen.append((fid, path)))

    repo.downloadFile(501, "referral.pdf")
    assert _wait_until(qapp, lambda: bool(seen))

    assert client.calls == [(7, 501)]
    assert client.threads and client.threads[0] is not threading.main_thread()

    file_id, path = seen[0]
    assert file_id == 501
    assert path and os.path.exists(path)

    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_a_cached_copy_is_not_downloaded_a_second_time(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "files_dir", lambda case_id=None: _mk(tmp_path, case_id))
    storage.write_attachment(7, 501, "referral.pdf", b"already here")

    client = _FileClient()
    repo = ChatRepository("drv", client=client)
    repo._engine.set_open_case(7)

    seen = []
    repo.fileDownloaded.connect(lambda fid, path: seen.append((fid, path)))

    repo.downloadFile(501, "referral.pdf")
    assert _wait_until(qapp, lambda: bool(seen))
    assert client.calls == [], "the bytes were already on disk; the server was asked anyway"

    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_a_second_click_while_the_first_is_in_flight_is_ignored(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "files_dir", lambda case_id=None: _mk(tmp_path, case_id))

    class _SlowFileClient(_FileClient):
        def download_file(self, case_id, file_id):
            time.sleep(0.25)
            return super().download_file(case_id, file_id)

    client = _SlowFileClient()
    repo = ChatRepository("drv", client=client)
    repo._engine.set_open_case(7)

    seen = []
    repo.fileDownloaded.connect(lambda fid, path: seen.append(fid))

    repo.downloadFile(501, "referral.pdf")
    repo.downloadFile(501, "referral.pdf")
    assert _wait_until(qapp, lambda: bool(seen))

    assert len(client.calls) == 1, "one chip, two clicks, two downloads of the same bytes"

    _wait_until(qapp, lambda: workers.live_worker_count() == 0)


def test_a_failed_download_frees_the_chip_for_another_try(qapp):
    class _BrokenClient:
        def download_file(self, case_id, file_id):
            raise RuntimeError("connection reset")

    repo = ChatRepository("drv", client=_BrokenClient())
    repo._engine.set_open_case(7)

    failures = []
    repo.writeFailed.connect(lambda kind, message: failures.append(kind))

    repo.downloadFile(501, "referral.pdf")
    assert _wait_until(qapp, lambda: bool(failures))
    assert failures == ["file"]
    assert not repo._downloading, "the chip would stay unclickable for the rest of the session"

    _wait_until(qapp, lambda: workers.live_worker_count() == 0)
