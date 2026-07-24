"""Guard: the browser pre-warm must never freeze the user's FIRST interactions.

Root cause (live session 2026-07-23 13:51, pid 36612): OPT-22's idle gate
measured "idle" as *no input since the watch started*. Right after startup the
user has not clicked yet, so the quiet moment while the home page paints
satisfied the 5 s idle gap and the synchronous GUI-thread Chromium boot
(gap_ms=17031 in `_construct_warm_view` / `view.setUrl("about:blank")`) landed
exactly as the user began clicking patients — the reported "small lag and
freezing when I click on the patient".

These tests pin the hardened gate (prewarm.py, 2026-07-23):

  * pre-input quiet does NOT warm (idle counts only BETWEEN interactions);
  * after the first discrete input, a real idle gap warms as before (OPT-22);
  * a session with zero input warms only after the long `untouched_ms` grace
    (user genuinely away), and `untouched_ms=0` restores the legacy pre-input
    behaviour;
  * the busy-cap give-up still skips the warm entirely;
  * the input filter marks `_seen_input` on a click.

Headless: offscreen Qt, no QtWebEngine — `kick` is stubbed so nothing heavy
ever runs; tests drive the REAL `_check_idle` state machine directly.
"""
from __future__ import annotations

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
    """A REAL _PrewarmController from schedule_prewarm, with heavy work stubbed."""
    app = QApplication.instance() or QApplication([])

    # Isolate the adaptive marker in a temp state dir and mark browser-used.
    monkeypatch.setattr(prewarm, "_state_dir", lambda: tmp_path)
    (tmp_path / prewarm._MARKER_NAME).write_text("1", encoding="utf-8")

    # Fresh module state per test.
    monkeypatch.setattr(prewarm, "_scheduled", False)
    monkeypatch.setattr(prewarm, "_warm_view", None)
    monkeypatch.setattr(prewarm, "_warm_ctl", None)

    monkeypatch.delenv("AIPACS_BROWSER_PREWARM", raising=False)
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_DELAY_MS", "3600000")  # never auto-fires in test

    assert prewarm.schedule_prewarm() is True
    ctl = prewarm._warm_ctl
    assert ctl is not None

    # Stub the heavy work: record kicks instead of importing QtWebEngine.
    kicks = []
    ctl.kick = lambda: kicks.append(1)
    ctl._kicks = kicks
    # Detach the app-wide event filter timer noise; tests drive state directly.
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


def test_pre_input_quiet_does_not_warm(controller):
    """The reported bug: idle-by-silence BEFORE any interaction must NOT warm."""
    ctl = controller
    now = prewarm._now_ms()
    ctl._seen_input = False
    ctl._start_ms = now - 30_000          # watch running 30s
    ctl._last_input_ms = ctl._start_ms    # no input ever
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    _stop_poll(ctl)
    assert ctl._kicks == [], "pre-input silence must never trigger the Chromium boot"


def test_idle_after_first_interaction_warms(controller):
    """OPT-22 behaviour preserved: a real pause BETWEEN interactions warms."""
    ctl = controller
    now = prewarm._now_ms()
    ctl._seen_input = True
    ctl._start_ms = now - 60_000
    ctl._last_input_ms = now - 6_000      # 6s pause after clicking around
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    assert ctl._kicks == [1]


def test_busy_user_after_interaction_does_not_warm(controller):
    ctl = controller
    now = prewarm._now_ms()
    ctl._seen_input = True
    ctl._start_ms = now - 60_000
    ctl._last_input_ms = now - 1_000      # clicked 1s ago — busy
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    _stop_poll(ctl)
    assert ctl._kicks == []


def test_untouched_grace_warms_when_user_truly_away(controller):
    ctl = controller
    now = prewarm._now_ms()
    ctl._seen_input = False
    ctl._start_ms = now - 130_000         # untouched for >120s → user away
    ctl._last_input_ms = ctl._start_ms
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    assert ctl._kicks == [1]


def test_untouched_zero_restores_legacy_pre_input_warm(controller):
    """Kill switch: AIPACS_BROWSER_PREWARM_UNTOUCHED_MS=0 → legacy behaviour."""
    ctl = controller
    now = prewarm._now_ms()
    ctl._seen_input = False
    ctl._start_ms = now - 30_000
    ctl._last_input_ms = ctl._start_ms
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 0.0               # legacy mode
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    assert ctl._kicks == [1]


def test_busy_cap_still_gives_up(controller):
    ctl = controller
    now = prewarm._now_ms()
    ctl._seen_input = True
    ctl._start_ms = now - 700_000         # past the 600s cap
    ctl._last_input_ms = now - 1_000      # still busy
    ctl._idle_ms = 5_000.0
    ctl._untouched_ms = 120_000.0
    ctl._max_wait_ms = 600_000.0

    ctl._check_idle()
    assert ctl._kicks == [], "past the cap the warm is skipped, never forced"


def test_event_filter_marks_first_interaction(controller):
    from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    ctl = controller
    ctl._seen_input = False
    ev = QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(QPoint(1, 1)),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier)
    ctl.eventFilter(None, ev)
    assert ctl._seen_input is True


# ── off-thread file warm (measured cold-boot fix, 2026-07-23) ────────────

def test_file_warm_reads_webengine_aux_files(tmp_path):
    """The warm must read exactly the engine-init files (exe/ICU/pak/snapshot),
    skip unrelated files, and report the byte count."""
    (tmp_path / "QtWebEngineProcess.exe").write_bytes(b"x" * 1000)
    (tmp_path / "icudtl.dat").write_bytes(b"y" * 500)
    sub = tmp_path / "resources"
    sub.mkdir()
    (sub / "qtwebengine_resources.pak").write_bytes(b"z" * 2000)
    (tmp_path / "unrelated.dll").write_bytes(b"n" * 9999)  # must NOT be counted

    total = prewarm._warm_webengine_files(root=tmp_path)
    assert total == 1000 + 500 + 2000


def test_file_warm_kill_switch(tmp_path, monkeypatch):
    (tmp_path / "icudtl.dat").write_bytes(b"y" * 500)
    monkeypatch.setenv("AIPACS_BROWSER_PREWARM_FILE_WARM", "0")
    assert prewarm._warm_webengine_files(root=tmp_path) == 0


def test_file_warm_never_raises_on_missing_root(tmp_path):
    assert prewarm._warm_webengine_files(root=tmp_path / "does-not-exist") == 0


def test_file_warm_wired_off_thread_and_release_waits_for_ready():
    """Source pins: (a) the file warm runs inside the DAEMON-thread _bg_import
    (never on the GUI thread); (b) the warm view is released on loadFinished
    with a failsafe — not the old fixed 2.5 s timer that killed a cold boot
    mid-init."""
    import inspect
    src = inspect.getsource(prewarm)
    bg = src.split("def _bg_import", 1)[1].split("threading.Thread", 1)[0]
    assert "_warm_webengine_files()" in bg
    construct = src.split("def _construct_warm_view", 1)[1]
    assert "loadFinished.connect(_release_once)" in construct
    assert "QTimer.singleShot(60000, _release_once)" in construct
