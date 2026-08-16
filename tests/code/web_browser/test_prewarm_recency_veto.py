"""IMP-3 — construct-time input-recency re-check (stale idle verdict).

Live evidence 2026-08-07 21:28 (pid 288604): the idle gate fired correctly
("idle 6062ms >= 5000ms after first interaction") at 21:27:57, but kick()'s
background phase (QtWebEngine DLL import + 152 MB file warm) ran until
21:28:01.8 — and the user double-clicked patient 53516 inside that window.
`_on_construct` had no input check (and the OLD `_finish_watch` had already
REMOVED the input filter), so the Chromium construct landed on the GUI
thread with the double-click already queued behind it: one contiguous
19.0 s MAIN_THREAD_STALL (`prewarm.py:492 view.setUrl`), the patient open
processed only after (`_on_patient_double_clicked_async` at 21:28:21.8).

Pins (same harness as test_prewarm_busy_veto.py — offscreen Qt, REAL
controller from schedule_prewarm, heavy work stubbed):

  * recent discrete input at construct time DEFERS the construct;
  * a genuinely stale last-input (>= idle_ms ago) still constructs;
  * the legacy fixed-delay path (never any tracked input) still constructs;
  * kill switch AIPACS_BROWSER_PREWARM_RECENCY_VETO=0 reproduces the
    2026-08-07 collision;
  * _finish_watch(warm=True) KEEPS the input filter installed (the fix's
    load-bearing half) and _on_construct removes it on construct/skip;
  * the deferral shares the bounded IMP-1 deadline (never warms forever);
  * the input filter refreshes _last_input_ms while deferring.
"""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from modules.web_browser import prewarm


@pytest.fixture()
def controller(tmp_path, monkeypatch):
    """A REAL _PrewarmController from schedule_prewarm, heavy work stubbed."""
    app = QApplication.instance() or QApplication([])

    monkeypatch.setattr(prewarm, "_state_dir", lambda: tmp_path)
    (tmp_path / prewarm._MARKER_NAME).write_text("1", encoding="utf-8")

    monkeypatch.setattr(prewarm, "_scheduled", False)
    monkeypatch.setattr(prewarm, "_warm_view", None)
    monkeypatch.setattr(prewarm, "_warm_ctl", None)

    # IMP-4 (2026-08-16): the prewarm is opt-in now, so these tests of the
    # scheduling machinery must enable it explicitly. The default-off policy
    # itself is pinned in tests/code/system/test_browser_prewarm_idle_gate.py.
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM", "1")
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM_BUSY_VETO", raising=False)
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM_RECENCY_VETO", raising=False)
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_DELAY_MS", "3600000")

    assert prewarm.schedule_prewarm() is True
    ctl = prewarm._warm_ctl
    assert ctl is not None

    kicks = []
    ctl.kick = lambda: kicks.append(1)
    ctl._kicks = kicks
    yield ctl
    try:
        ctl._finish_watch(warm=False)
    except Exception:
        pass


def _recent_input_state(ctl, ms_ago: float = 1_000.0):
    """The 2026-08-07 collision state: input seen ms_ago, idle gap 5 s."""
    now = prewarm._now_ms()
    ctl._seen_input = True
    ctl._last_input_ms = now - ms_ago
    ctl._idle_ms = 5_000.0
    ctl._construct_deadline_ms = 0.0


# ── the 2026-08-07 defect and its fix ────────────────────────────────────
def test_recent_input_defers_construct(controller, monkeypatch):
    """A click 1 s ago must DEFER the Chromium construct, not eat it."""
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    _recent_input_state(ctl, ms_ago=1_000.0)

    ctl._on_construct()
    assert built == [], "construct ran 1 s after user input (IMP-3 defect)"
    assert ctl._construct_deadline_ms > 0, "deferral deadline must be armed"


def test_stale_input_still_constructs(controller, monkeypatch):
    """Input idle_ms+ ago = a genuine idle gap at construct time -> warm."""
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    _recent_input_state(ctl, ms_ago=6_000.0)

    ctl._on_construct()
    assert built == [1]


def test_legacy_fixed_delay_path_unaffected(controller, monkeypatch):
    """kick() via the legacy fixed-delay schedule never saw input tracking
    (_seen_input False) — the recency veto must stay inert there."""
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    ctl._seen_input = False
    ctl._last_input_ms = prewarm._now_ms()  # would look "recent" if consulted

    ctl._on_construct()
    assert built == [1]


def test_kill_switch_reproduces_collision(controller, monkeypatch):
    """AIPACS_BROWSER_PREWARM_RECENCY_VETO=0 -> construct despite fresh input."""
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_RECENCY_VETO", "0")
    _recent_input_state(ctl, ms_ago=100.0)

    ctl._on_construct()
    assert built == [1], "kill switch must restore pre-IMP-3 behaviour"


def test_recency_defer_respects_shared_deadline(controller, monkeypatch):
    """Past the IMP-1 deadline the warm is skipped, never forced."""
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    _recent_input_state(ctl, ms_ago=100.0)
    ctl._construct_deadline_ms = prewarm._now_ms() - 1.0  # deadline passed

    ctl._on_construct()
    assert built == [], "past the deadline the warm is skipped, never forced"


# ── input-filter lifetime (the fix's load-bearing half) ──────────────────
class _FakeFilterTarget:
    def __init__(self):
        self.removed = 0

    def removeEventFilter(self, _obj):
        self.removed += 1


def test_finish_watch_keeps_filter_when_warming(controller):
    ctl = controller
    tgt = _FakeFilterTarget()
    ctl._filter = tgt

    ctl._finish_watch(warm=True)
    assert ctl._kicks == [1]
    assert ctl._filter is tgt, "filter must SURVIVE _finish_watch(warm=True)"
    assert tgt.removed == 0


def test_finish_watch_removes_filter_on_give_up(controller):
    ctl = controller
    tgt = _FakeFilterTarget()
    ctl._filter = tgt

    ctl._finish_watch(warm=False)
    assert ctl._kicks == []
    assert ctl._filter is None
    assert tgt.removed == 1


def test_filter_removed_after_successful_construct(controller, monkeypatch):
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    _recent_input_state(ctl, ms_ago=6_000.0)
    tgt = _FakeFilterTarget()
    ctl._filter = tgt

    ctl._on_construct()
    assert built == [1]
    assert ctl._filter is None and tgt.removed == 1


def test_filter_removed_on_deadline_skip(controller, monkeypatch):
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: True)
    ctl._construct_deadline_ms = prewarm._now_ms() - 1.0
    tgt = _FakeFilterTarget()
    ctl._filter = tgt

    ctl._on_construct()
    assert built == [] and ctl._filter is None and tgt.removed == 1


def test_filter_keeps_refreshing_last_input_while_deferring(controller):
    """Input arriving during the defer window must push the construct out."""
    ctl = controller
    ctl._seen_input = True
    before = prewarm._now_ms() - 60_000.0
    ctl._last_input_ms = before

    ctl.eventFilter(None, QEvent(QEvent.Type.MouseButtonPress))
    assert ctl._last_input_ms > before, "eventFilter must refresh last-input"


@pytest.mark.parametrize("val,expected", [
    (None, True), ("", True), ("1", True), ("junk", True),
    ("0", False),
])
def test_recency_veto_flag_parsing(monkeypatch, val, expected):
    if val is None:
        monkeypatch.delenv("AIPACS_BROWSER_PREWARM_RECENCY_VETO", raising=False)
    else:
        monkeypatch.setenv("AIPACS_BROWSER_PREWARM_RECENCY_VETO", val)
    assert prewarm._recency_veto_enabled() is expected


# ── source pins ──────────────────────────────────────────────────────────
def test_recency_wired_into_construct_and_filter_survives_warm():
    src = inspect.getsource(prewarm.schedule_prewarm)
    construct = src.split("def _on_construct", 1)[1].split("# ── idle gating", 1)[0]
    assert "_recency_veto_enabled()" in construct, "recency veto must gate construct"
    assert "self._last_input_ms" in construct, "construct must consult last input"
    assert "self._remove_input_filter()" in construct, "construct must clean up filter"
    finish = src.split("def _finish_watch", 1)[1].split("def _remove_input_filter", 1)[0]
    assert "if not warm:" in finish, "warm path must KEEP the input filter"
