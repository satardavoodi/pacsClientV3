"""Guard: web-browser Chromium prewarm gating + idle policy (OPT-22, 2026-07-08).

The GUI-thread ``QWebEngineView`` construction blocks the main thread for the
Chromium cold boot (up to ~21 s). The prewarm must (a) stay marker-gated + kill
switchable, and (b) default to IDLE-gated scheduling (not a fixed 4 s delay that
lands during patient-list load). This pins the pure, Qt-free policy helpers and
the idle/legacy routing decision.

NOTE: importing ``modules.web_browser.prewarm`` needs no Qt at module top level
(Qt is imported lazily inside ``schedule_prewarm``), so these run headless.
"""

import importlib

import pytest

prewarm = importlib.import_module("modules.web_browser.prewarm")


# ── kill switch + marker gate (safety) ─────────────────────────────────
def test_kill_switch_disables_prewarm(monkeypatch):
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM", "0")
    assert prewarm.should_prewarm() is False


def test_prewarm_is_opt_in_by_default(monkeypatch, tmp_path):
    """IMP-4 (2026-08-16): default OFF, even with the used-marker present.

    Live that day the warm froze the GUI thread for 72.1 s inside the Chromium
    construct while every scheduling guard behaved correctly (the user really
    had been idle 12.7 s). The construct must run on the GUI thread and its
    cost is unbounded, so no idle window makes it safe — the boot is now paid
    when the user actually opens the browser.
    """
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM", raising=False)
    marker = tmp_path / ".browser_used"
    monkeypatch.setattr(prewarm, "_marker_path", lambda: marker)
    marker.write_text("1", encoding="utf-8")
    assert prewarm.should_prewarm() is False, (
        "the browser prewarm must not run unless explicitly opted in")


def test_marker_gate_applies_on_top_of_the_opt_in(monkeypatch, tmp_path):
    """Opted in, the adaptive marker still gates it."""
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM", "1")
    marker = tmp_path / ".browser_used"
    monkeypatch.setattr(prewarm, "_marker_path", lambda: marker)
    # No marker -> never warm (workstation that never opened the browser).
    assert prewarm.should_prewarm() is False
    # After the user opened the browser once -> eligible.
    marker.write_text("1", encoding="utf-8")
    assert prewarm.should_prewarm() is True


@pytest.mark.parametrize("val", ["0", "", "yes", "true", "on", "2", "junk"])
def test_only_an_explicit_1_enables_the_prewarm(monkeypatch, tmp_path, val):
    """Anything other than "1" leaves the freeze-prone warm disabled."""
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM", val)
    marker = tmp_path / ".browser_used"
    monkeypatch.setattr(prewarm, "_marker_path", lambda: marker)
    marker.write_text("1", encoding="utf-8")
    assert prewarm.should_prewarm() is False


# ── idle-only routing (default on) ─────────────────────────────────────
def test_idle_only_default_on(monkeypatch):
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM_IDLE_ONLY", raising=False)
    assert prewarm._idle_only() is True


def test_idle_only_legacy_off(monkeypatch):
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_IDLE_ONLY", "0")
    assert prewarm._idle_only() is False


# ── tunable parsing ────────────────────────────────────────────────────
def test_env_int_parsing(monkeypatch):
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_DELAY_MS", "12345")
    assert prewarm._env_int("AIPACS_BROWSER_PREWARM_DELAY_MS", 20000) == 12345
    # unset -> default
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM_DELAY_MS", raising=False)
    assert prewarm._env_int("AIPACS_BROWSER_PREWARM_DELAY_MS", 20000) == 20000
    # garbage -> default (never raises)
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_DELAY_MS", "abc")
    assert prewarm._env_int("AIPACS_BROWSER_PREWARM_DELAY_MS", 20000) == 20000


def test_schedule_noop_when_disabled(monkeypatch):
    # Disabled -> schedule_prewarm is a no-op (returns False), never touches Qt.
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM", "0")
    monkeypatch.setattr(prewarm, "_scheduled", False, raising=False)
    assert prewarm.schedule_prewarm() is False


# ── idle decision (pure, mirrors _check_idle) ──────────────────────────
@pytest.mark.parametrize(
    "idle_for,waited,idle_ms,max_wait_ms,expected",
    [
        (5000, 8000, 5000, 600000, "warm"),   # idle gap reached
        (5000, 5000, 5000, 600000, "warm"),   # boundary == idle_ms
        (1200, 8000, 5000, 600000, "poll"),   # busy, under cap
        (1000, 600001, 5000, 600000, "skip"),  # never idle past cap -> skip
    ],
)
def test_idle_decision(idle_for, waited, idle_ms, max_wait_ms, expected):
    def decide(i, w, im, mw):
        if i >= im:
            return "warm"
        if w >= mw:
            return "skip"
        return "poll"

    assert decide(idle_for, waited, idle_ms, max_wait_ms) == expected
