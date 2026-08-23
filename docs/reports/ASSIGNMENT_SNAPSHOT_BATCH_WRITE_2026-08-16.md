# The 10.79 s freeze: one file rewrite per reception

**Date:** 2026-08-16
**Reported as:** *"Check that there is a small freeze now."*
**Status:** fixed, guarded, reversible
**Files touched:** `modules/network/ino_assignment_server_state.py`,
`modules/network/ino_assignment_refresh.py`
**Guard test:** `tests/code/network/test_ino_state_batch_write.py` (28 guards)
**Kill switch:** `AIPACS_INO_STATE_FSYNC=1` restores the forced disk flush
**Measured result:** a 91-reception refresh went from **12.8 s to 13 ms** of
lock-held time — **990×**

---

## 1. What was measured

Live process pid 239928 (up 233 min). One clear event:

| Time | Stall |
|---|---|
| **17:19:41.195** | **10,792.8 ms** |
| 17:19:30.272 | 1,566.1 ms |
| 17:19:20.431 | 349.3 ms |

13.7 s of blocked GUI time inside a single minute. Everything else in the
previous two hours was under 500 ms.

**10 of the 12 sampled stack traces in that window landed on the same line:**

```
patient_table_widget.py:6271 _update_report_status_in_table
  -> :5131 refresh_assign_icon_for_patient
  -> :4878 _assign_icon_state
  -> :5110 assignment_display_for
  -> ino_assignment_server_state.py:240 get_state
       with _LOCK:            <-- the GUI thread parked here
```

The GUI thread was not computing anything. It was waiting for a lock.

## 2. Root cause

`ino_assignment_refresh._one()` — the per-reception worker — called
`set_state(rid, ...)`. Every one of those calls rewrote the **entire**
snapshot while holding the store's global `_LOCK`:

```python
with _LOCK:
    data = _load()          # whole file
    data[rid] = {...}       # ONE reception
    return _save(data)      # json.dump(whole) -> flush -> fsync -> replace
```

And `get_state()` — which the patient list calls **once per row on the GUI
thread** — takes that same `_LOCK` (added 2026-07-31 to stop reader handles
breaking the writer's `os.replace` on Windows).

So the refresh and the repaint were serialised against each other, one full
file write at a time.

### The cost, measured on this machine

Benchmarked against the real snapshot
(`tools/analysis/oneoff/ino_state_write_bench_2026_08_16.py`), which grew from
336,590 bytes / 1,279 receptions to **356,972 bytes / 1,360 receptions** over
the 40 minutes this investigation took — the file is still growing:

| | |
|---|---|
| one write **with fsync** (as shipped) | **median 141 ms**, p90 210 ms |
| one write **without fsync** | median **13 ms** |
| `json.dumps` alone, no disk | 3.4 ms |
| `os.stat` — `get_state`'s cached fast path | **0.023 ms** |

The read was never the problem. **The lock was**, and the fsync was 90 % of
what the lock was held for.

The arithmetic matches the observation: **10,793 ms ÷ ~118 ms ≈ 91 writes** —
one refresh batch of the visible worklist.

### Why it was getting worse

The write is **O(all receptions) for one reception's update**. As the snapshot
grew, every single row update got more expensive. At 1,360 entries a full
refresh would be **192 s** of lock-held time.

## 3. The fix

**(a) One write per batch.** New `set_many()` on the store: build every entry
first, then take `_LOCK` **once**, `_load` once, merge, `_save` once.
`refresh_assignments` now persists after the fan-out instead of per row.

**(b) The fsync is opt-in.** `AIPACS_INO_STATE_FSYNC`, default off.

Both paths build their record through one shared `_entry()` helper, so
`set_state` and `set_many` cannot drift apart — pinned by
`test_both_paths_go_through_the_same_builder`.

### Result

```
--- one 91-reception refresh, lock-held time ---
  BEFORE  91 writes x 141 ms =     12848 ms
  AFTER    1 write  x  13 ms =        13 ms
  improvement: 990x   (12.8 s -> 0.013 s)

--- worst case, a full 1360-reception refresh ---
  BEFORE     192.0 s
  AFTER        0.013 s
```

## 4. Why dropping the fsync is safe *here*

This is the part worth being precise about, because "remove the fsync" is
usually the wrong answer.

It is safe for **this file specifically** because of what it is — the module's
own docstring: *"a plain last-known-server-state cache, so it can be rewritten
freely"*. Concretely:

- `os.replace` is **still atomic** on NTFS. A reader always sees a whole
  document, old or new, never a spliced one. That property came from the
  temp-file-plus-replace pattern, not from the fsync.
- fsync only adds durability across a **power loss**. The worst case without it
  is a stale or unparseable snapshot — and `_load()` already swallows a parse
  error and returns `{}`, after which the next refresh repopulates from the
  server.
- **No assignment can be lost.** The server is the source of truth; this file
  is a display cache that exists so the Assign column survives a restart.

If a site wants the durability back, `AIPACS_INO_STATE_FSYNC=1` costs them
~128 ms per refresh — now once per batch instead of once per row.

## 5. What deliberately did *not* change

- **`get_state` still takes `_LOCK`.** That was the 2026-07-31 fix for
  `[WinError 5] Access is denied` on `os.replace`; removing it would bring back
  silently-failing writes. With writers no longer hammering the lock, the
  reader now hits its 0.023 ms cached path.
- **`on_row` still fires per row, at the same point.** Only the *persist*
  moved. The docstring now states that persistence happens once at the end, so
  an `on_row` handler must use the `parsed` dict it is handed rather than
  calling `get_state`. Every caller in this repo reads `summary["rows"]` after
  the function returns — which is after the write — so this is safe today.
- **A failed fetch still leaves the stored snapshot alone.** An unreachable
  server must never wipe a known assignment. Pinned.
- **An interrupted refresh still keeps what it fetched.** The batch write runs
  even when `should_stop` fired, so cancelling is not a total loss. Pinned.
- **`_load` stays lock-free** — `_merge_and_save` holds `_LOCK` when it calls
  it, and `threading.Lock` is not reentrant.

## 6. One subtle thing that had to be right

`_merge_and_save` does `_load()` **inside the same lock acquisition** as the
save. If it had loaded first and locked later, a `set_state` landing in between
— the Assign dialog, the internal assignment panel — would be silently rolled
back by the batch. `test_a_concurrent_single_write_is_not_rolled_back` covers
it.

It also copies the loaded dict before mutating, because `_load` may hand back
the shared read cache; mutating that in place would make a change visible to
readers before it was saved, and keep it if the save failed.

## 7. Guard tests

`tests/code/network/test_ino_state_batch_write.py` — 28 tests, grouped:

| Group | What it pins |
|---|---|
| One write per batch | 50 receptions = 1 `_save` and 1 lock acquisition; a 40-row refresh writes once; lock acquisitions do not scale with row count |
| No drift | `set_state` and `set_many` produce byte-identical records; both go through `_entry` |
| Merge semantics | existing rows survive a batch; a concurrent single write is not rolled back; no `.part` files; snapshot stays valid JSON |
| The fsync gate | off by default, forceable back on, only a literal `1` counts (7 params), data still lands without it |
| Bad input | blank ids skipped, an unknown key does not lose the other rows, empty batch is a no-op |
| Unchanged contracts | `on_row` per row, summary shape, failed fetch does not wipe, interrupted refresh still persists |

**Verified to fail on the pre-fix codebase.** With `_one` restored to its
per-row `set_state` and the fsync forced on, **11 of 28 fail**, including every
load-bearing one. The 17 that still pass are the invariants that must hold in
*both* modes — which is the point of having them.

## 8. Regression run

`pytest tests/code/network tests/code/ui_services` → **959 passed, 10 failed**.

All 10 failures are the known pre-existing set, none in a file this change
touches:

- `test_field_icon_chip` ×5 and `test_local_incremental_and_import_date` ×3 —
  `qtawesome` cannot resolve the Windows fonts directory in this environment
  (`os.path.join(windows_dir, "Fonts")` with `windows_dir=None`)
- `test_report_assign_rendering::test_login_carries_the_user_identity_ids` —
  inspects `download_manager/network/socket_client.py`
- `test_status_report_sorting::test_status_flags_are_stashed_on_the_widget...`
  — inspects a status-rendering function

## 9. Still open — the second offender in the same freeze

The other two sampled traces in that window were a different problem:

```
_hp_search.py:1553 add_data2patient_list_table
  -> utils.py:1618 get_study_download_status
  -> utils.py:923  count_subfolders_with_dicom
  -> pathlib _local.py:515 stat        (worst sample 1,454 ms)
```

An `os.stat` per series subfolder, on the GUI thread, once per row of server
search results. Same disease — filesystem work on the paint path — but a
different module, and caching it has clinical-display implications (the
download-status indicator would go stale). Not touched here. Written up in
[`OPEN_FINDINGS_2026-08-16.md`](OPEN_FINDINGS_2026-08-16.md) §3.

## 10. How to confirm it live

The running app (pid 239928, started 13:26) predates this change, so it must be
restarted to pick it up. Afterwards, press **Refresh Status** on a full
worklist and check `viewer_diagnostics.log`: there should be no
`[MAIN_THREAD_STALL]` correlated with `[ino-refresh] assignments checked=N`.
Before the fix, a 91-row refresh reliably produced one.
