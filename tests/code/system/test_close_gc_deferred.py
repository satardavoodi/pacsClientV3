"""Guard: patient-close GUI-freeze fix — defer + coalesce the teardown gc.collect() (2026-06-27).

Live evidence (stall traces, pid 246292/167060): `exit_patient_widget` ran a SYNCHRONOUS full
`gc.collect()` on the GUI thread (stall trace pinned `_pw_lifecycle.py` at the collect line), a heap
walk over hundreds of MB of volumes + VTK wrappers → up to ~3.7s freeze on EVERY patient close.

Fix (flag AIPACS_DEFER_CLOSE_GC default-on; `=0` = synchronous legacy): the collect must STAY on the
GUI thread (VTK render windows can only be destroyed there), so it is DEFERRED to an idle
`QTimer.singleShot` and COALESCED — a burst of closes collapses to one sweep; the close returns
instantly and the cycle collection happens a moment later when idle.

Source-pin (the close path needs the full PySide6 + VTK widget tree to import); behaviour validated
live + by the coalescing-flag logic below.
"""
from __future__ import annotations

from pathlib import Path

_SRC = (Path(__file__).resolve().parents[3]
        / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
        / "patient_widget_core" / "_pw_lifecycle.py")


def _src() -> str:
    return _SRC.read_text(encoding="utf-8")


def test_flag_default_on_with_kill_switch():
    s = _src()
    assert '_DEFER_CLOSE_GC = (_os.getenv("AIPACS_DEFER_CLOSE_GC", "1") or "1").strip() != "0"' in s


def test_close_defers_instead_of_synchronous_collect():
    s = _src()
    body = s[s.index("def exit_patient_widget"):]
    head = body[:s[s.index("def exit_patient_widget"):].index("def closeEvent")] \
        if "def closeEvent" in body else body[:6000]
    # the teardown routes through the deferred scheduler when the flag is on
    assert "if _DEFER_CLOSE_GC:" in head
    assert "_schedule_deferred_close_gc()" in head
    # the legacy synchronous collect is preserved only behind the `=0` else-branch
    assert "else:" in head and "gc.collect()" in head


def test_scheduler_coalesces_and_defers():
    """The scheduler must (a) defer via QTimer.singleShot, (b) coalesce via a pending flag so a
    burst of closes collapses to ONE sweep, (c) actually call gc.collect in the deferred run."""
    s = _src()
    assert "def _schedule_deferred_close_gc():" in s
    sched = s[s.index("def _schedule_deferred_close_gc():"):]
    assert "if _CLOSE_GC_PENDING[0]:" in sched and "return" in sched   # coalesce
    assert "_CLOSE_GC_PENDING[0] = True" in sched
    assert "QTimer.singleShot(" in sched                               # idle-deferred
    run = s[s.index("def _run_deferred_close_gc():"):]
    assert "_CLOSE_GC_PENDING[0] = False" in run and "gc.collect()" in run


def test_collect_stays_on_gui_thread_not_a_worker():
    """The fix must NOT move gc.collect to a background thread (VTK render windows can only be
    destroyed on the GUI thread) — it defers within the Qt event loop only."""
    s = _src()
    sched = s[s.index("def _schedule_deferred_close_gc():"): s.index("def _schedule_deferred_close_gc():") + 800]
    assert "Thread(" not in sched and "QThread" not in sched and "ThreadPool" not in sched
