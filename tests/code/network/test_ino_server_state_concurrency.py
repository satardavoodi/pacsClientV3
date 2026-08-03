"""Guard: the ino assignment snapshot survives concurrent readers and writers.

THE DEFECT (found in a live app.log, 2026-07-31 — nine occurrences in one day,
three of them within 280 ms on three different threads):

    [ino-assignment] could not write server state: [WinError 5] Access is
    denied: 'server_state.json.part' -> 'server_state.json'

`ino_assignment_server_state` HAS a `_LOCK`, and `set_state` / `clear` both take
it — but `get_state` read the file OUTSIDE it. On Windows `os.replace` fails
with ERROR_ACCESS_DENIED when the DESTINATION has an open handle that was not
opened with FILE_SHARE_DELETE, and CPython's `open()` does not request it. So a
reader merely holding the file open defeated the writer's atomic replace. The
lock protected writer-vs-writer; the case that actually bit was
writer-vs-reader.

Second defect in the same function: the temp file was a FIXED `path + ".part"`,
shared by every writer, so two writers could interleave into one scratch file
and the "atomic" replace could publish a half-merged document.

The failure is logged at WARNING and swallowed, so nothing surfaced — the
snapshot just silently stopped persisting.
"""
from __future__ import annotations

import ast
import importlib
import json
import os
import threading

import pytest


@pytest.fixture()
def state(tmp_path, monkeypatch):
    mod = importlib.import_module("modules.network.ino_assignment_server_state")
    monkeypatch.setattr(mod, "_base_dir", lambda: str(tmp_path))
    # start from a clean snapshot for every test
    mod.clear()
    return mod


def _snapshot_path(tmp_path) -> str:
    return os.path.join(str(tmp_path), "server_state.json")


def _code_only(fn) -> str:
    """Source of `fn` with its docstring and comment lines removed.

    These guards document the defect they guard against by quoting the old
    code, so a naive substring match would trip on its own explanation.
    """
    import inspect
    tree = ast.parse(inspect.getsource(fn).lstrip())
    node = tree.body[0]
    body = node.body[1:] if (node.body and isinstance(node.body[0], ast.Expr)
                             and isinstance(node.body[0].value, ast.Constant)
                             and isinstance(node.body[0].value.value, str)) else node.body
    return "\n".join(ast.unparse(n) for n in body)


# ── the behavioural guard ────────────────────────────────────────────────────

def test_concurrent_readers_do_not_break_writers(state, tmp_path, caplog):
    """The real-world shape: a refresh thread writing while worklist rows read.

    Every write must report success and the file must stay parseable. Before the
    fix this produced `could not write server state` on Windows.
    """
    caplog.set_level("WARNING")
    failures: list[str] = []
    stop = threading.Event()

    def reader():
        while not stop.is_set():
            try:
                state.get_state("R-0")
            except Exception as exc:            # pragma: no cover - defensive
                failures.append("reader: %r" % (exc,))

    def writer(n: int):
        for i in range(25):
            ok = state.set_state(
                "R-%d" % n, assigned=True, assignee_name="dr%d" % n,
                assignee_id="id%d" % n, mine=(n == 0),
            )
            if not ok:
                failures.append("writer %d lost write %d" % (n, i))

    readers = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    writers = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in readers:
        t.start()
    for t in writers:
        t.start()
    for t in writers:
        t.join(timeout=30)
        assert not t.is_alive(), "writer deadlocked — is _load taking _LOCK?"
    stop.set()
    for t in readers:
        t.join(timeout=5)

    assert not failures, failures
    warnings = [r.message for r in caplog.records if "could not write server state" in r.getMessage()]
    assert not warnings, "atomic replace still failing under concurrency: %s" % warnings

    # every writer's last value survived, and the document is not half-merged
    with open(_snapshot_path(tmp_path), encoding="utf-8") as fh:
        data = json.load(fh)
    for n in range(4):
        assert data["R-%d" % n]["assignee_id"] == "id%d" % n


def test_no_part_files_are_left_behind(state, tmp_path):
    """A failed or interrupted write must not litter the data dir."""
    for i in range(10):
        state.set_state("X-%d" % i, assigned=True, assignee_name="a")
    leftovers = [p for p in os.listdir(str(tmp_path)) if p.endswith(".part")]
    assert not leftovers, "temp files left behind: %s" % leftovers


def test_writers_do_not_share_one_temp_file(state, tmp_path):
    """Two writers must never scribble into the same scratch path.

    Structural, because the interleaving that corrupts the document is timing
    dependent and would make a flaky test.
    """
    code = _code_only(state._save)
    assert 'p + ".part"' not in code, (
        "the temp file name is fixed again — every writer shares one scratch "
        "file and the 'atomic' replace can publish a half-merged document"
    )
    assert "get_ident" in code or "getpid" in code, "temp name is not per-writer"


def test_get_state_takes_the_lock(state):
    """The actual fix, pinned. `get_state` reading unlocked is what made the
    writer's `os.replace` fail on Windows."""
    code = _code_only(state.get_state)
    assert "_LOCK" in code, "get_state reads without the lock again"


def test_load_must_not_take_the_lock(state):
    """`set_state` already holds `_LOCK` when it calls `_load`, and
    threading.Lock is NOT reentrant — locking inside `_load` would deadlock
    every write. The concurrency test above would hang; this says why."""
    code = _code_only(state._load)
    assert "_LOCK" not in code, "_load takes _LOCK — set_state will deadlock"


def test_round_trip_still_works(state):
    assert state.get_state("nope") is None
    state.set_state("R-1", assigned=True, assignee_name="Dr A", assignee_id="7", mine=True)
    got = state.get_state("R-1")
    assert got["assigned"] is True
    assert got["assignee_id"] == "7"
    assert got["mine"] is True
    state.clear()
    assert state.get_state("R-1") is None
