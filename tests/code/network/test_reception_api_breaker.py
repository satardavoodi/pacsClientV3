"""Guard: Reception/Workflow REST API circuit breaker (2026-06-26).

When a center's reception endpoint is unreachable (e.g. Mehr's report service on
http://5.57.36.202:8800 over a poor link), the post-search reporting-physician hydration
re-hits the dead endpoint on every search — 426 ConnectionError/timeout failures in one
session, wasting the thin link and spamming logs. The breaker short-circuits REST callers
after a few consecutive CONNECTION failures, per base_url, and self-heals on the next success.
Background/non-clinical only — never touches the imaging socket or download path.
Kill switch: AIPACS_RECEPTION_BREAKER=0.
"""
import time

import pytest

from modules.network import reception_api_config as rc

MEHR = "http://5.57.36.202:8800"
RAZI = "http://81.16.117.196:8080"


@pytest.fixture(autouse=True)
def _reset_breaker():
    with rc._reception_breaker_lock:
        rc._reception_breaker_state.clear()
    yield
    with rc._reception_breaker_lock:
        rc._reception_breaker_state.clear()


def test_closed_by_default():
    assert rc.reception_api_breaker_open(MEHR) is False


def test_opens_only_after_threshold(monkeypatch):
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_ENABLED", True)
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_THRESHOLD", 3)
    rc.record_reception_api_failure(MEHR)
    rc.record_reception_api_failure(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is False   # 2 < 3 → still closed
    rc.record_reception_api_failure(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is True     # 3rd consecutive → OPEN


def test_success_self_heals(monkeypatch):
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_ENABLED", True)
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_THRESHOLD", 3)
    for _ in range(3):
        rc.record_reception_api_failure(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is True
    rc.record_reception_api_success(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is False


def test_per_base_url_isolation(monkeypatch):
    """A sick center must not penalise a healthy sibling (Razi <-> Mehr)."""
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_ENABLED", True)
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_THRESHOLD", 3)
    for _ in range(3):
        rc.record_reception_api_failure(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is True
    assert rc.reception_api_breaker_open(RAZI) is False


def test_half_open_probe_then_reopen(monkeypatch):
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_ENABLED", True)
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_THRESHOLD", 2)
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_COOLDOWN_S", 0.2)
    rc.record_reception_api_failure(MEHR)
    rc.record_reception_api_failure(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is True
    time.sleep(0.25)
    assert rc.reception_api_breaker_open(MEHR) is False   # cooldown elapsed → half-open probe
    rc.record_reception_api_failure(MEHR)                  # probe failed → re-open
    assert rc.reception_api_breaker_open(MEHR) is True


def test_kill_switch_disables(monkeypatch):
    monkeypatch.setattr(rc, "_RECEPTION_BREAKER_ENABLED", False)
    for _ in range(20):
        rc.record_reception_api_failure(MEHR)
    assert rc.reception_api_breaker_open(MEHR) is False   # disabled → never opens
