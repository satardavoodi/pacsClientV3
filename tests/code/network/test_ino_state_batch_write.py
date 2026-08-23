"""Guards for the BATCHED assignment-snapshot write (2026-08-16).

THE DEFECT (live, pid 239928, 17:19:41 — a 10.79 s frozen clinical UI)

`refresh_assignments` called `set_state` once per reception. Each call rewrites
the ENTIRE snapshot under the store's global `_LOCK`:

    json.dump(whole file) -> flush -> os.fsync -> os.replace

and `get_state` — which the patient list calls PER ROW on the GUI thread — takes
that same lock. So every row the refresh fetched blocked the GUI for one full
file write. The stall sampler caught the GUI thread parked on `with _LOCK:` in
`get_state` in 10 of 12 samples.

Measured on the reporting workstation (336,590-byte / 1,279-reception snapshot,
two real-time AV engines):

    one write WITH fsync    median 118 ms, p90 162 ms
    one write WITHOUT fsync median  13 ms
    json.dumps alone          3.3 ms
    get_state cached read     0.025 ms   <- the read was never the problem

10793 ms / 118 ms = 91 writes. That is one refresh batch.

Two fixes, both pinned here:
  1. `set_many` — one lock acquisition, one file write, for a whole batch.
  2. the fsync is opt-in (`AIPACS_INO_STATE_FSYNC=1`), because this file is a
     re-fetchable display cache and `os.replace` is already atomic.

Note the scaling, which is why "just make it faster" was not enough: the write
is O(all receptions) for ONE reception's update, so the per-row design got
worse as the worklist grew. At 1,279 entries a full refresh was ~2.5 minutes of
lock-held time.
"""
from __future__ import annotations

import ast
import importlib
import inspect
import json
import os
import threading

import pytest


# ── fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def state(tmp_path, monkeypatch):
    mod = importlib.import_module("modules.network.ino_assignment_server_state")
    monkeypatch.setattr(mod, "_base_dir", lambda: str(tmp_path))
    mod.clear()
    return mod


@pytest.fixture()
def counted(state, monkeypatch):
    """Count writer-side lock acquisitions and physical saves."""
    counters = {"merge": 0, "save": 0, "fsync": 0}
    real_merge, real_save, real_fsync = state._merge_and_save, state._save, os.fsync

    def merge(built):
        counters["merge"] += 1
        return real_merge(built)

    def save(data):
        counters["save"] += 1
        return real_save(data)

    def fsync(fd):
        counters["fsync"] += 1
        return real_fsync(fd)

    monkeypatch.setattr(state, "_merge_and_save", merge)
    monkeypatch.setattr(state, "_save", save)
    monkeypatch.setattr(os, "fsync", fsync)
    return counters


def _parsed(rid: str, *, assigned=True, mine=False):
    """The shape `fetch_assignment` returns."""
    return {
        "assigned": assigned,
        "assignee_name": "Dr %s" % rid,
        "assignee_id": "id-%s" % rid,
        "mine": mine,
        "assign_type": "manual",
        "assignee_source": "server",
        "last_assigned_by": "boss-%s" % rid,
        "last_assigned_at": "2026-08-16T10:00:00",
        "reception_id": rid,
    }


@pytest.fixture()
def refresh(state, monkeypatch):
    """`refresh_assignments` with the network stubbed out."""
    mod = importlib.import_module("modules.network.ino_assignment_refresh")
    monkeypatch.setattr(mod, "fetch_assignment", lambda rid: _parsed(str(rid)))
    monkeypatch.setattr(mod, "current_user_identities", lambda: {"me"})
    monkeypatch.setattr(mod, "assignment_is_mine", lambda aid, ids=None: False)
    return mod


# ── 1. one write per batch — the fix itself ──────────────────────────────────

def test_set_many_writes_the_file_once(state, counted):
    ok = state.set_many({
        "R-%d" % i: {"assigned": True, "assignee_name": "dr", "assignee_id": str(i)}
        for i in range(50)
    })
    assert ok is True
    assert counted["save"] == 1, (
        "50 receptions must cost ONE file write, got %d — the per-row rewrite "
        "is back" % counted["save"]
    )
    assert counted["merge"] == 1, "one lock acquisition per batch, not per row"
    assert state.get_state("R-49")["assignee_id"] == "49"


def test_refresh_persists_once_for_the_whole_batch(refresh, counted):
    summary = refresh.refresh_assignments([f"R{i}" for i in range(40)], force=True)
    assert summary["updated"] == 40
    assert counted["save"] == 1, (
        "the refresh wrote %d times for 40 receptions; each write holds the "
        "lock the GUI thread needs in get_state" % counted["save"]
    )


def test_refresh_lock_acquisitions_do_not_scale_with_row_count(refresh, counted):
    """The GUI-starvation factor, stated directly."""
    refresh.refresh_assignments([f"R{i}" for i in range(75)], force=True)
    assert counted["merge"] == 1


def test_one_refresh_still_persists_everything_it_fetched(refresh, state):
    refresh.refresh_assignments([f"R{i}" for i in range(10)], force=True)
    for i in range(10):
        got = state.get_state("R%d" % i)
        assert got is not None, "row R%d never reached the snapshot" % i
        assert got["assignee_id"] == "id-R%d" % i
        assert got["assigned"] is True


# ── 2. the two write paths must not drift ────────────────────────────────────

def test_set_many_and_set_state_produce_identical_entries(state):
    kwargs = dict(assigned=True, assignee_name=" Dr A ", assignee_id=" 7 ",
                  mine=True, assign_type="auto", assignee_source="ris",
                  assigned_by=" boss ", assigned_at="2026-08-16T09:00:00")
    state.set_state("VIA-ONE", **kwargs)
    state.set_many({"VIA-MANY": dict(kwargs)})

    one = state.get_state("VIA-ONE")
    many = state.get_state("VIA-MANY")
    one.pop("ts", None)
    many.pop("ts", None)
    assert one == many, "set_state and set_many disagree on the record shape"
    # and the normalisation really happened (not just equal-because-both-raw)
    assert many["assignee_name"] == "Dr A"
    assert many["assignee_id"] == "7"
    assert many["mine"] is True


def test_both_paths_go_through_the_same_builder():
    """Structural companion — stop the shapes drifting by construction."""
    mod = importlib.import_module("modules.network.ino_assignment_server_state")
    for fn in (mod.set_state, mod.set_many):
        src = ast.unparse(ast.parse(inspect.getsource(fn).lstrip()))
        assert "_entry(" in src, f"{fn.__name__} builds its entry by hand again"


# ── 3. merge semantics ───────────────────────────────────────────────────────

def test_set_many_merges_and_does_not_clobber_other_rows(state):
    state.set_state("KEEP", assigned=True, assignee_name="old", assignee_id="k")
    state.set_many({"NEW-%d" % i: {"assigned": False} for i in range(5)})
    assert state.get_state("KEEP")["assignee_id"] == "k", "batch wiped an existing row"
    assert state.get_state("NEW-3") is not None


def test_a_concurrent_single_write_is_not_rolled_back(state):
    """`_load` must happen INSIDE the same lock as `_save`.

    If a batch loaded the snapshot, then took the lock to save, a `set_state`
    landing in between (the Assign dialog, the internal panel) would be silently
    reverted by the batch.
    """
    done = threading.Event()

    def other():
        state.set_state("DIALOG", assigned=True, assignee_name="clicked",
                        assignee_id="dlg")
        done.set()

    t = threading.Thread(target=other)
    t.start()
    done.wait(timeout=10)
    t.join(timeout=10)
    state.set_many({"BATCH-%d" % i: {"assigned": True} for i in range(30)})

    assert state.get_state("DIALOG")["assignee_id"] == "dlg", \
        "the batch rolled back a concurrent single write"
    assert state.get_state("BATCH-29") is not None


def test_batch_never_leaves_part_files(state, tmp_path):
    state.set_many({"R-%d" % i: {"assigned": True} for i in range(20)})
    leftovers = [p for p in os.listdir(str(tmp_path)) if p.endswith(".part")]
    assert not leftovers, "temp files left behind: %s" % leftovers


def test_snapshot_stays_valid_json_after_a_batch(state, tmp_path):
    state.set_many({"R-%d" % i: {"assigned": bool(i % 2)} for i in range(100)})
    with open(os.path.join(str(tmp_path), "server_state.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    assert len(data) == 100


# ── 4. the fsync gate ────────────────────────────────────────────────────────

def test_fsync_is_off_by_default(state, counted, monkeypatch):
    monkeypatch.delenv("AIPACS_INO_STATE_FSYNC", raising=False)
    state.set_many({"R-1": {"assigned": True}})
    assert counted["fsync"] == 0, (
        "the snapshot write still forces a physical flush — that was 105 of the "
        "118 ms, paid on the lock the GUI thread waits on"
    )


def test_fsync_can_be_forced_back_on(state, counted, monkeypatch):
    monkeypatch.setenv("AIPACS_INO_STATE_FSYNC", "1")
    state.set_many({"R-1": {"assigned": True}})
    assert counted["fsync"] == 1, "the durability escape hatch does not work"


@pytest.mark.parametrize("val", ["0", "", "true", "yes", "on", "2", "01"])
def test_only_a_literal_1_forces_fsync(state, counted, monkeypatch, val):
    monkeypatch.setenv("AIPACS_INO_STATE_FSYNC", val)
    state.set_many({"R-1": {"assigned": True}})
    assert counted["fsync"] == 0


def test_data_still_lands_on_disk_without_fsync(state, tmp_path, monkeypatch):
    """Dropping fsync must not mean dropping the write."""
    monkeypatch.delenv("AIPACS_INO_STATE_FSYNC", raising=False)
    state.set_many({"R-9": {"assigned": True, "assignee_id": "99"}})
    with open(os.path.join(str(tmp_path), "server_state.json"), encoding="utf-8") as fh:
        assert json.load(fh)["R-9"]["assignee_id"] == "99"


# ── 5. bad input must not lose the batch ─────────────────────────────────────

def test_blank_ids_are_skipped_not_fatal(state):
    assert state.set_many({"": {"assigned": True}, "  ": {"assigned": True},
                           "GOOD": {"assigned": True}}) is True
    assert state.get_state("GOOD") is not None


def test_an_unknown_key_does_not_lose_the_other_rows(state):
    ok = state.set_many({
        "BAD": {"assigned": True, "not_a_field": "boom"},
        "GOOD": {"assigned": True, "assignee_id": "g"},
    })
    assert ok is True
    assert state.get_state("GOOD")["assignee_id"] == "g"
    assert state.get_state("BAD") is not None, "one bad key dropped a whole row"


def test_empty_batch_is_a_no_op(state, counted):
    assert state.set_many({}) is True
    assert counted["save"] == 0, "an empty batch still rewrote the file"


# ── 6. refresh-side contracts that must NOT have changed ─────────────────────

def test_on_row_still_fires_once_per_row(refresh):
    seen = []
    refresh.refresh_assignments(["A", "B", "C"], on_row=lambda rid, p: seen.append(rid),
                                force=True)
    assert sorted(seen) == ["A", "B", "C"]


def test_summary_shape_is_unchanged(refresh):
    s = refresh.refresh_assignments(["A", "B"], force=True)
    assert set(s) >= {"ok", "checked", "updated", "failed", "rows"}
    assert s["checked"] == 2 and s["updated"] == 2 and s["failed"] == 0
    assert s["ok"] is True


def test_a_failed_fetch_does_not_wipe_a_known_assignment(refresh, state, monkeypatch):
    state.set_state("KNOWN", assigned=True, assignee_name="Dr Prior", assignee_id="p")
    monkeypatch.setattr(refresh, "fetch_assignment", lambda rid: None)
    s = refresh.refresh_assignments(["KNOWN"], force=True)
    assert s["failed"] == 1 and s["updated"] == 0
    assert state.get_state("KNOWN")["assignee_id"] == "p", \
        "an unreachable server wiped a known assignment"


def test_interrupted_refresh_still_keeps_what_it_fetched(refresh, state):
    """`should_stop` used to leave per-row writes behind; a batched write must
    not turn a cancelled refresh into a total loss."""
    fetched: list = []
    real = refresh.fetch_assignment

    def counting(rid):
        fetched.append(rid)
        return real(rid)

    refresh.fetch_assignment = counting
    try:
        refresh.refresh_assignments(
            [f"S{i}" for i in range(20)],
            should_stop=lambda: len(fetched) >= 5,
            force=True,
        )
    finally:
        refresh.fetch_assignment = real

    kept = [i for i in range(20) if state.get_state("S%d" % i) is not None]
    assert kept, "a stopped refresh persisted nothing at all"


def test_the_per_row_write_is_gone(refresh):
    """AST pin: the comment at the call site names `set_state` on purpose, so a
    substring check would pass forever. Parse instead."""
    src = inspect.getsource(refresh.refresh_assignments)
    tree = ast.parse(src.lstrip())
    one = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "_one")
    body = ast.unparse(one)
    assert "set_state" not in body, "the per-reception snapshot write is back in _one"
    assert "set_many" in ast.unparse(tree), "the batch write disappeared"
