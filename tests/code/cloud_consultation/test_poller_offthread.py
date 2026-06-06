"""Guards for the ConsultationPoller GUI-thread stall fix (2026-06-07).

Contract:
  1. poll_once() must stay cheap on the calling (GUI) thread — the transport
     build (OAuth refresh) and ensure_app_folder (Drive round-trip) run
     INSIDE the scan thread. Running them on the GUI thread froze the app
     3–20 s per poll (MAIN_THREAD_STALL_TRACE, 2026-06-07 session).
  2. ConsultationPoller.start() defers the first poll — no immediate network
     work in the app-startup window.
  3. Scan results still arrive via the existing signals.
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

from ._fakes import FakeTransport


@pytest.fixture()
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


class _ThreadRecordingTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.ensure_threads: list = []

    def ensure_app_folder(self):
        self.ensure_threads.append(threading.current_thread())
        # Simulate slow connectivity: on the GUI thread this WOULD be a
        # visible freeze; off-thread it must not block poll_once's caller.
        time.sleep(0.15)
        return super().ensure_app_folder()


def _wait_until(qapp, predicate, timeout_s: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_poll_once_never_blocks_calling_thread(qapp, monkeypatch):
    transport = _ThreadRecordingTransport()
    provider_threads: list = []

    def provider():
        provider_threads.append(threading.current_thread())
        return transport

    poller = ConsultationPoller(provider, "me@example.com", interval_ms=999999)
    monkeypatch.setattr(poller, "_outgoing_awaiting_response", lambda: [])

    t0 = time.monotonic()
    poller.poll_once()
    elapsed = time.monotonic() - t0
    assert elapsed < 0.1, (
        f"poll_once blocked for {elapsed * 1000:.0f} ms — transport/Drive work "
        "leaked back onto the calling thread"
    )

    assert _wait_until(qapp, lambda: poller._scan is not None and poller._scan.isFinished())
    main = threading.main_thread()
    assert provider_threads and all(t is not main for t in provider_threads), (
        "transport provider (OAuth refresh) ran on the GUI thread"
    )
    assert transport.ensure_threads and all(t is not main for t in transport.ensure_threads), (
        "ensure_app_folder (Drive round-trip) ran on the GUI thread"
    )


def test_start_defers_first_poll(qapp, monkeypatch):
    calls = []
    poller = ConsultationPoller(lambda: None, "me@example.com", interval_ms=999999)
    monkeypatch.setattr(poller, "poll_once", lambda: calls.append(1))

    poller.start()
    qapp.processEvents()
    assert not calls, "start() must not poll synchronously in the startup window"
    poller.stop()


def test_scan_results_still_flow(qapp, monkeypatch):
    transport = FakeTransport()
    poller = ConsultationPoller(lambda: transport, "me@example.com", interval_ms=999999)
    monkeypatch.setattr(poller, "_outgoing_awaiting_response", lambda: [])

    received = []
    monkeypatch.setattr(poller, "_on_found", lambda items: received.append(items))
    poller.poll_once()
    assert _wait_until(qapp, lambda: bool(received)), "found signal never delivered"
    assert received == [[]]  # empty cloud → empty scan, delivered on GUI thread


def test_failed_provider_is_silent_and_nonblocking(qapp):
    def provider():
        raise RuntimeError("no identity linked")

    poller = ConsultationPoller(provider, "me@example.com", interval_ms=999999)
    t0 = time.monotonic()
    poller.poll_once()  # must not raise, must not block
    assert time.monotonic() - t0 < 0.1
    assert _wait_until(qapp, lambda: poller._scan is not None and poller._scan.isFinished())
