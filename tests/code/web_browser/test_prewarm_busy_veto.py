"""IMP-1 — browser prewarm busy-app veto (modal open = mid-workflow).

Live evidence 2026-08-05 (pid 193888): the idle gate counts only discrete
input, so a user WAITING on the import scan/preview/copy modals looked
"idle"; the warm kicked at 20:36:17 mid-import, `_warm_webengine_files`
read 152 MB against the copy's disk I/O, and `_construct_warm_view` landed
on the GUI thread at 20:36:23 — ONE contiguous 39.7 s MAIN_THREAD_STALL
covering the whole 40.9 s import copy (66 MB at ~1.6 MB/s from the same
contention).

Pins (same harness as test_prewarm_idle_gate.py — offscreen Qt, REAL
controller from schedule_prewarm, heavy work stubbed):

  * a busy app (modal open) never warms, even on a perfect idle gap;
  * the untouched-away branch also respects the veto (zero-input CD
    auto-import path);
  * kill switch AIPACS_BROWSER_PREWARM_BUSY_VETO=0 reproduces the legacy
    warm-under-modal defect;
  * _on_construct defers while busy (bounded), skips past the deadline,
    constructs normally when not busy;
  * _app_is_busy is False with no modal and honours the kill switch;
  * source pins: veto consulted before idle math and in the away branch.
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


def _stop_poll(ctl):
    try:
        if ctl._poll_timer is not None:
            ctl._poll_timer.stop()
            ctl._poll_timer = None
    except Exception:
        pass


def _perfect_idle_after_input(ctl):
    """State that WOULD warm under OPT-22: seen input, 6s idle gap."""
    now = prewarm._now_ms()
    ctl._seen_input = True
    ctl._start_ms = now - 60_000
    ctl._last_input_ms = now - 6_000
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0


# ── the 2026-08-05 defect and its fix ────────────────────────────────────
def test_busy_app_never_warms_even_on_idle_gap(controller, monkeypatch):
    """The import-copy scenario: modal open + no clicks = NO warm."""
    ctl = controller
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: True)
    _perfect_idle_after_input(ctl)

    ctl._check_idle()
    _stop_poll(ctl)
    assert ctl._kicks == [], "warm kicked while a modal was open (IMP-1 defect)"


def test_kill_switch_reproduces_warm_under_modal(controller, monkeypatch):
    """AIPACS_BROWSER_PREWARM_BUSY_VETO=0 → legacy OPT-22 behaviour."""
    ctl = controller
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_BUSY_VETO", "0")
    # Even with a "modal open", the disabled veto reports not-busy.
    assert prewarm._app_is_busy() is False
    _perfect_idle_after_input(ctl)

    ctl._check_idle()
    assert ctl._kicks == [1], "kill switch must restore the legacy warm"


def test_not_busy_still_warms_on_idle_gap(controller, monkeypatch):
    """OPT-22 behaviour preserved when nothing is modal."""
    ctl = controller
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    _perfect_idle_after_input(ctl)

    ctl._check_idle()
    assert ctl._kicks == [1]


def test_untouched_away_branch_respects_veto(controller, monkeypatch):
    """Zero-input CD auto-import: `waited` grows past untouched_ms while the
    copy modal is up — must NOT warm (the away branch keys on `waited`, not
    idle_for, so it needs its own veto)."""
    ctl = controller
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: True)
    now = prewarm._now_ms()
    ctl._seen_input = False
    ctl._start_ms = now - 130_000          # "away" grace exceeded
    ctl._last_input_ms = ctl._start_ms
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    _stop_poll(ctl)
    assert ctl._kicks == []


def test_untouched_away_still_warms_when_not_busy(controller, monkeypatch):
    ctl = controller
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)
    now = prewarm._now_ms()
    ctl._seen_input = False
    ctl._start_ms = now - 130_000
    ctl._last_input_ms = ctl._start_ms
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    assert ctl._kicks == [1]


def test_busy_cap_still_gives_up_while_busy(controller, monkeypatch):
    """Past max_wait with a permanently-busy app: skip, never force."""
    ctl = controller
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: True)
    now = prewarm._now_ms()
    ctl._seen_input = True
    ctl._start_ms = now - 700_000
    ctl._last_input_ms = now - 6_000
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    assert ctl._kicks == []


# ── construct-time guard (the 39.7 s hammer) ─────────────────────────────
def test_on_construct_defers_while_busy(controller, monkeypatch):
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: True)

    ctl._on_construct()
    assert built == [], "Chromium construct ran while a modal was open"
    assert ctl._construct_deadline_ms > 0, "deferral deadline must be armed"


def test_on_construct_skips_past_deadline(controller, monkeypatch):
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: True)

    ctl._construct_deadline_ms = prewarm._now_ms() - 1.0  # deadline passed
    ctl._on_construct()
    assert built == [], "past the deadline the warm is skipped, never forced"


def test_on_construct_runs_when_not_busy(controller, monkeypatch):
    ctl = controller
    built = []
    monkeypatch.setattr(prewarm, "_construct_warm_view", lambda: built.append(1))
    monkeypatch.setattr(prewarm, "_app_is_busy", lambda: False)

    ctl._on_construct()
    assert built == [1]


def test_construct_defer_constants_sane():
    assert 250 <= prewarm._CONSTRUCT_DEFER_POLL_MS <= 10_000
    assert prewarm._CONSTRUCT_DEFER_MAX_MS >= 60_000


# ── _app_is_busy itself ──────────────────────────────────────────────────
def test_app_is_busy_false_with_no_modal(monkeypatch):
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM_BUSY_VETO", raising=False)
    QApplication.instance() or QApplication([])
    assert prewarm._app_is_busy() is False


def test_app_is_busy_true_with_real_modal_dialog(monkeypatch):
    monkeypatch.delenv("AIPACS_BROWSER_PREWARM_BUSY_VETO", raising=False)
    QApplication.instance() or QApplication([])
    from PySide6.QtWidgets import QDialog

    dlg = QDialog()
    dlg.setModal(True)
    dlg.show()
    try:
        if QApplication.activeModalWidget() is None:
            pytest.skip("offscreen platform does not track modal widgets")
        assert prewarm._app_is_busy() is True
    finally:
        dlg.close()
        dlg.deleteLater()


@pytest.mark.parametrize("val,expected", [
    (None, True), ("", True), ("1", True), ("junk", True),
    ("0", False),
])
def test_busy_veto_flag_parsing(monkeypatch, val, expected):
    if val is None:
        monkeypatch.delenv("AIPACS_BROWSER_PREWARM_BUSY_VETO", raising=False)
    else:
        monkeypatch.setenv("AIPACS_BROWSER_PREWARM_BUSY_VETO", val)
    assert prewarm._busy_veto_enabled() is expected


# ── source pins ──────────────────────────────────────────────────────────
def test_veto_wired_before_idle_math_and_in_away_branch():
    src = inspect.getsource(prewarm.schedule_prewarm)
    check_idle = src.split("def _check_idle", 1)[1].split("def _finish_watch", 1)[0]
    busy_at = check_idle.find("if _app_is_busy():")
    idle_at = check_idle.find("idle_for = now - self._last_input_ms")
    assert 0 <= busy_at < idle_at, "veto must refresh last-input BEFORE idle math"
    assert "not _app_is_busy()" in check_idle, "away branch must respect the veto"
    construct = src.split("def _on_construct", 1)[1].split("# ── idle gating", 1)[0]
    assert "_app_is_busy()" in construct
    assert "_CONSTRUCT_DEFER_POLL_MS" in construct
    assert "_construct_warm_view()" in construct
