"""Guards for the no-Google-dependency hardening (2026-06-07).

Contract — the workstation must behave identically with no internet:
  1. assert_off_gui_thread: any Google/Drive operation entered on the Qt GUI
     thread raises RuntimeError immediately (fail fast, never freeze).
     Inert under pytest unless AIPACS_FORCE_GUI_GUARD=1;
     AIPACS_ALLOW_MAINTHREAD_GOOGLE=1 is the emergency kill-switch.
  2. Every GoogleDriveTransport network method enters the guard.
  3. ConsultationPoller backs off (×2 up to 10 min) while scans fail and
     restores the base cadence on the first success.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from modules.cloud_consultation.notifications.poller import ConsultationPoller  # noqa: E402
from modules.cloud_consultation.transport.google_drive import GoogleDriveTransport  # noqa: E402
from modules.Identity.thread_guard import assert_off_gui_thread  # noqa: E402


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture()
def forced_guard(qapp, monkeypatch):
    """Re-arm the guard inside pytest (it is inert under pytest by default)."""
    monkeypatch.setenv("AIPACS_FORCE_GUI_GUARD", "1")
    monkeypatch.delenv("AIPACS_ALLOW_MAINTHREAD_GOOGLE", raising=False)
    return qapp


# ── 1: the guard itself ─────────────────────────────────────────────────────
def test_guard_raises_on_gui_thread(forced_guard):
    with pytest.raises(RuntimeError, match="GUI thread"):
        assert_off_gui_thread("unit-test op")


def test_guard_passes_on_worker_thread(forced_guard):
    result: list = []

    def worker():
        try:
            assert_off_gui_thread("unit-test op")
            result.append("ok")
        except Exception as exc:  # pragma: no cover
            result.append(exc)

    t = threading.Thread(target=worker)
    t.start()
    t.join(5)
    assert result == ["ok"]


def test_guard_inert_under_pytest_by_default(qapp, monkeypatch):
    monkeypatch.delenv("AIPACS_FORCE_GUI_GUARD", raising=False)
    assert_off_gui_thread("unit-test op")  # must not raise


def test_guard_kill_switch(forced_guard, monkeypatch):
    monkeypatch.setenv("AIPACS_ALLOW_MAINTHREAD_GOOGLE", "1")
    assert_off_gui_thread("unit-test op")  # must not raise


# ── 2: every transport network method is guarded ───────────────────────────
_NETWORK_METHODS = [
    ("ensure_app_folder", ()),
    ("find_child", ("p", "n")),
    ("make_child_folder", ("p", "n")),
    ("list_folder", ("f",)),
    ("upload_file", ("x.bin", "p")),
    ("download_file", ("fid", "out.bin")),
    ("delete", ("fid",)),
    ("share", ("fid", "a@b.c")),
    ("start_change_cursor", ()),
    ("changes_since", ("tok",)),
]


@pytest.mark.parametrize("method,args", _NETWORK_METHODS)
def test_transport_methods_guarded_on_gui_thread(forced_guard, method, args):
    transport = GoogleDriveTransport(service=object())  # never reached
    with pytest.raises(RuntimeError, match="GUI thread"):
        getattr(transport, method)(*args)


# ── 3: poller offline backoff ───────────────────────────────────────────────
def test_poller_backs_off_while_offline_and_recovers(qapp):
    poller = ConsultationPoller(lambda: None, "me@example.com", interval_ms=120000)
    assert poller._timer.interval() == 120000

    poller._on_scan_error("offline")
    assert poller._timer.interval() == 240000
    poller._on_scan_error("offline")
    assert poller._timer.interval() == 480000
    poller._on_scan_error("offline")
    assert poller._timer.interval() == 600000, "backoff must cap at 10 min"
    poller._on_scan_error("offline")
    assert poller._timer.interval() == 600000

    poller._on_found([])  # first successful scan
    assert poller._timer.interval() == 120000, "success must restore base cadence"


def test_offline_poll_cycle_is_silent_and_fast(qapp, monkeypatch):
    """End-to-end offline cycle: provider fails (no internet) → no exception,
    no GUI blocking, backoff applied after the error signal lands."""

    def offline_provider():
        raise OSError("getaddrinfo failed")  # what a dead network looks like

    poller = ConsultationPoller(offline_provider, "me@example.com", interval_ms=120000)
    monkeypatch.setattr(poller, "_outgoing_awaiting_response", lambda: [])

    t0 = time.monotonic()
    poller.poll_once()
    assert time.monotonic() - t0 < 0.1

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        qapp.processEvents()
        if poller._timer.interval() > 120000:
            break
        time.sleep(0.01)
    assert poller._timer.interval() == 240000, "scan error must trigger backoff"
