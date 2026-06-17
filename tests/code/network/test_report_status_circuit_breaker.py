# -*- coding: utf-8 -*-
"""Regression guard for the GetReportStatus circuit breaker (added 2026-06-16).

Root cause it protects against: report-status calls reuse the SHARED
PatientListSocketClient, and the server does not answer GetReportStatus, so each
call held that client's RLock for up to the ~30s socket timeout -> GUI-thread
patient/thumbnail socket calls blocked (1.3-1.7s main-thread stalls) plus
~30s-cadence ERROR log spam. The breaker short-circuits the call once the server
has clearly stopped answering, so the shared lock is never held for it.

These tests use a fake client and never touch a real socket.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import time
import pytest
from PySide6.QtWidgets import QApplication

import modules.network.socket_report_status_service as rss_mod
from modules.network.socket_report_status_service import SocketReportStatusService


@pytest.fixture(scope="module", autouse=True)
def _qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeClient:
    """Stand-in for the shared PatientListSocketClient."""

    def __init__(self, response=None):
        self.response = response
        self.calls = 0

    def get_report_status(self, study_uid):
        self.calls += 1
        return self.response


def _make_service(monkeypatch, client):
    # Never create a real connection pool or touch a socket on construction.
    monkeypatch.setattr(SocketReportStatusService, "_setup_connection_pool", lambda self: None)
    svc = SocketReportStatusService()
    svc.connection_pool = None
    monkeypatch.setattr(svc, "_get_client", lambda: client)
    monkeypatch.setattr(svc, "_return_client", lambda c: None)
    return svc


def test_breaker_opens_after_threshold_and_stops_calling_client(monkeypatch):
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_ENABLED", True)
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_THRESHOLD", 3)
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_COOLDOWN_S", 300.0)

    client = _FakeClient(response=None)  # server never answers
    svc = _make_service(monkeypatch, client)

    # The first THRESHOLD calls reach the client (each returns None == failure).
    for _ in range(3):
        assert svc.get_report_status("S1") is None
    assert client.calls == 3

    # Breaker is now OPEN: further calls must NOT touch the shared client at all
    # (this is what prevents the ~30s lock hold + GUI stall).
    for _ in range(25):
        assert svc.get_report_status("S1") is None
    assert client.calls == 3, "breaker must short-circuit without calling the client"


def test_breaker_half_open_recovers_on_success(monkeypatch):
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_ENABLED", True)
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_COOLDOWN_S", 300.0)

    client = _FakeClient(response=None)
    svc = _make_service(monkeypatch, client)

    for _ in range(2):
        svc.get_report_status("S1")
    assert client.calls == 2
    svc.get_report_status("S1")  # breaker open -> skipped
    assert client.calls == 2

    # Simulate cooldown expiry (half-open) and a server that now answers.
    svc._rs_breaker_open_until = time.monotonic() - 1.0
    client.response = {"report_status": "completed"}
    out = svc.get_report_status("S1")
    assert out == {"report_status": "completed"}
    assert client.calls == 3, "half-open trial call must go through"

    # Success fully resets the breaker -> normal calls continue.
    svc.get_report_status("S1")
    assert client.calls == 4


def test_breaker_disabled_preserves_legacy_behavior(monkeypatch):
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_ENABLED", False)
    client = _FakeClient(response=None)
    svc = _make_service(monkeypatch, client)
    for _ in range(8):
        assert svc.get_report_status("S1") is None
    assert client.calls == 8, "with breaker disabled every call must reach the client (legacy)"


def test_successful_status_still_emits_and_returns(monkeypatch):
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_ENABLED", True)
    monkeypatch.setattr(rss_mod, "_RS_BREAKER_THRESHOLD", 3)
    client = _FakeClient(response={"report_status": "physician_approved", "updated_at": "x"})
    svc = _make_service(monkeypatch, client)

    received = []
    svc.statusReceived.connect(lambda uid, data: received.append((uid, data)))
    out = svc.get_report_status("S9")
    assert out == {"report_status": "physician_approved", "updated_at": "x"}
    assert received and received[0][0] == "S9"
    assert received[0][1]["report_status"] == "physician_approved"
