"""Guard test for OPT-12 — startup single-instance sweep uses the CHEAP name.

STALL_TRACE (2026-07-04) showed the startup single-instance takeover sweep
(`SingleInstanceLock._force_close_other_instances`) blocking the main thread ~1.3 s
inside `proc.name()` → `proc.exe()` (an OpenProcess/PEB read on Windows) — and it was
called ONLY to build a log-description string, even though the cheap Toolhelp
(pid, name) was already fetched during enumeration.

The fix stores the cheap name alongside each candidate `(proc, name)` and reuses it
for the description, so the kill loop never re-derives the name via the slow
exe()-based path. This is a pure logging/plumbing change — the protect-set and
kill/terminate logic are untouched. These are source-pins (the real path needs a
live Windows process tree; the takeover behaviour is covered by
`test_single_instance_takeover.py`).
"""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SRC = REPO / "PacsClient" / "utils" / "single_instance_lock.py"


def _src() -> str:
    best = ""
    for _ in range(8):
        b = SRC.read_bytes()
        if len(b) > len(best.encode("utf-8", "ignore")):
            best = b.decode("utf-8-sig", errors="ignore")
    return best


def test_candidate_stores_cheap_name_tuple():
    assert "candidates[pid] = (proc, name)" in _src()


def test_kill_loop_unpacks_and_reuses_cheap_name():
    s = _src()
    assert "for pid, (proc, cand_name) in candidates.items():" in s
    assert "desc = f\"PID {pid} ({cand_name or '?'})\"" in s


def test_kill_loop_no_longer_calls_proc_name_for_description():
    # the slow proc.name()/.exe() call that blocked the startup thread is gone
    s = _src()
    assert "proc.name() or '?'" not in s


def test_toplevel_membership_check_still_keys_on_pid():
    # candidates is still a dict keyed by pid, so the top-level parent check is intact.
    # (The top-level test was refactored into a fast/legacy branch in OPT-12's fast
    # sweep: `_parent_pid` comes from the snapshot or proc.ppid(), then membership on
    # the pid-keyed candidates dict.)
    s = _src()
    assert "candidates[pid] = (proc, name)" in s
    assert "if _parent_pid in candidates:" in s
