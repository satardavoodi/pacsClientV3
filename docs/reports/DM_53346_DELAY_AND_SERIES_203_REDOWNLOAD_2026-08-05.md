# Patient 53346 — download start delay + series 203 re-download storm

**Date:** 2026-08-05
**Study:** `1.2.840.1.99.1.47.1.1785905807241.87153` (current exam; previous exam `…1785905069223.87152` enqueued together)
**Logs:** `download_diagnostics.log` (all line refs `dl:` below), session 11:29–11:35
**Status:** Root-caused from logs + code. No code changed yet.

---

## Context that shapes everything: this is a LIVE, GROWING study

The acquisition was still arriving at the server while the user opened it:

| time | server state (resync) |
|---|---|
| 11:29:17 | 1 series (203) — `content_version=37` |
| 11:30:21 | 3 series (203 **grown**, 204 + 9001 new) — `content_version=84` |
| 11:33:33 | series 203 = **191** images |
| 11:35:01 | series 203 = **260** images |

Series 203 went 71 → 191 → 260 during the session. That growth is the trigger of both symptoms.

---

## 1. The start delay: 27.5 s from double-click to first pixel — 18.3 s of it a scheduler stall

Timeline (all `dl:` lines):

| time | event |
|---|---|
| 11:29:16.8 | Single click. Resync sees the study but **by design does not download** (`resync_enqueue_skipped_single_click reason=single_click_auto_no_download`, dl:11132) |
| 11:30:24.2 | **Double-click open** (`PatientOpenDoubleClick`, dl:11162) |
| 11:30:24.700 | Worker started for study 87153 (dl:11169-70) — enqueue itself was fast (478 ms after click) |
| 11:30:24.742 | Worker start for the OTHER study 87152 (previous exam, enqueued by the same open): **"Cannot start - pool at capacity (1)"** (dl:11177) |
| 11:30:24.7→25.1 | Study 87153 status flips **Downloading → Paused → Pending** within 400 ms (DM-CONVERGE-MISS 1..3, dl:11174/11194/11207) — the two studies' mutual priority negotiation parks the one the user is looking at |
| 11:30:25.09 | 87152 grabs the pool (`status=Downloading`, dl:11211) |
| 11:30:30.8 | Viewer's critical intent for series 203 begins (`attempt=0/90 state=Pending`, dl:11213); this pauses 87152 too (dl:11216) |
| 11:30:30.9 → 11:30:49.1 | Both studies show Paused/Pending, but the pool slot is STILL HELD by 87152's worker — its subprocess is stuck in boot and cannot see the cancel. The intent chain ticks 90 × ~200 ms against the full pool = **18.33 s** (dl:11222 `tag=recover attempt=90/90 elapsed_ms=18330`) |
| 11:30:51.85 | 87152's child (pid 146640) FINALLY boots — 26.8 s after its worker start — sees the cancel, exits in 45 ms; slot freed (dl:11223-11226, ZetaBoost "Download stopped" at 51.893) |
| 11:30:51.97 | `on_worker_removed → _start_next_pending` starts the 87153 worker (dl:11229) — before the recovery chain's first tick (would have been 54.1) |
| 11:30:52.06 | First bytes of series 203 (dl:11236). Transfer itself: 71 images in **2.2 s** (~100 MB/s link) |

**Root cause D1 — a zombie pool slot, NOT a lost wakeup (corrected after deeper analysis).**
An earlier draft of this report blamed a lost wakeup ("both parked while the pool is free"). The
timer math disproves that: 90 ticks × 200 ms from the chain's `begin` at 11:30:30.80 lands at
11:30:48.8 — `recover` fired at 11:30:49.13, so **the retry chain ran exactly on schedule and every
tick found the pool genuinely full.** What held the slot: the 87152 worker started at 11:30:25.09,
and its download subprocess took **26.8 s to boot** (child pid 146640's first log: 11:30:51.85 —
`[SPAWN-TIMING] Imports OK (0.001s)` shows the child itself was fast once up; the time went to
process creation/interpreter boot under the concurrent multi-study open load). The pause issued at
11:30:30.8 (`_pause_all_active_downloads` → `worker.request_cancel()`) only sets a
`multiprocessing.Event` that the **child** checks — a child stuck in boot never sees it, and the
parent bridge's poll loop had **no escalation**: it waited for the child indefinitely while
`is_alive()` stayed True. The moment the child finally booted (51.85) it saw the cancel, exited
within 45 ms, the slot freed, and `on_worker_removed → _start_next_pending` started the critical
study (51.97) — *before* the recovery chain's first tick would have run (54.1).

So the fixed cost per such open = however long the paused worker's child takes to boot, invisible
and unbounded. The user-visible "download starts with delay" = 64 s of single-click (by design,
worth confirming the user knows) + 27.5 s of which ~21 s is this zombie-slot window.

---

## 2. The series-203 re-download storm: 8 rounds, 5 of them full wipes

Rounds observed (`download_series` in the subprocess, one pid per round):

| # | time | pid | result | note |
|---|---|---|---|---|
| 1 | 11:30:52 | 171536 | 71 downloaded, **0 skipped** | first real download |
| 2 | 11:30:56 | 166348 | 71 downloaded, **0 skipped** | full re-transfer |
| 3 | 11:31:03 | 169484 | 71 downloaded, **0 skipped** | full re-transfer |
| 4 | 11:31:06 | 171580 | 71 downloaded, **0 skipped** | full re-transfer |
| 5 | 11:31:21 | 173784 | 71 downloaded, **0 skipped** | full re-transfer |
| 6 | 11:31:27 | 170412 | 33 downloaded, **38 skipped** | rmtree failed mid-way (WinError 32) → survivors got skipped |
| 7 | 11:33:33 | 133012 | 194 downloaded, 2 skipped | server now reports 191 |
| 8 | 11:35:01 | 176008 | 68 downloaded, **194 skipped** | count refreshed → incremental resume finally engaged |

≈ **230 MB transferred where ~40 MB + increments would have sufficed.** On a slow clinic link this is exactly the reported symptom.

**Root cause D2 — the retry path deletes a "complete-looking" series before re-downloading.**
`modules/download_manager/ui/widget/_dm_retry.py`, `_bg_series_retry` (≈ line 534-553):

```python
if expected_count > 0 and existing_count < expected_count:
    # incremental resume — keep files
else:
    shutil.rmtree(series_path)     # ← wipes all 71 instances
```

`expected_count` comes from the **stale in-memory task** (`_task.series_list[...].image_count` = 71), while the retry was triggered precisely because the **server count had grown past it**. So for a growing series the comparison inverts: disk(71) >= stale-expected(71) → "must be corrupt" → wipe → full re-download with `skipped=0`. Five consecutive times, until the task's count refreshed (rounds 7-8 then skipped correctly).

**The trigger loop** is `request_object` (`_dm_priority.py:59-96`) — the viewer's stack navigator requests any missing slice, debounced to one call per **250 ms** per series. A growing series always has missing tail slices — and the wipe itself creates 71 more missing files — so `request_critical_series(203)` fired continuously (intent tokens 2→19+ in the log; "[INTENT] Series yield … viewer requested series 203" dozens of times), each round scheduling another retry-with-wipe.

**Root cause D3 — Windows file lock breaks the wipe midway.**
dl:11604-11617: `shutil.rmtree` hit `PermissionError [WinError 32]` on `203\Instance_0193.dcm` — the viewer had the displayed instance open. The exception aborted the delete after 33 files (round 6's "38 skipped" is the accidental proof that resume works whenever the wipe doesn't). Deleting a series out from under the viewer that is rendering it is dangerous independent of the bandwidth cost.

On disk now: 262 `.dcm`, 0 `.part`, DB says image_count=260 — consistent with a study that kept growing past the last round.

---

## 3. Fixes

1. **D2 — APPLIED (DM-R1, 2026-08-05, default-on, kill switch `AIPACS_DM_RETRY_KEEP_FILES=0`).**
   `_dm_retry.py`: new module flag `_DM_RETRY_KEEP_FILES`; the `existing >= expected` branch of
   `_bg_series_retry` now KEEPS the files (file-level resume fetches only the tail) unless the new
   explicit `force_clean=True` parameter is passed — which no production caller does (the DM panel's
   retry button is per-patient; every per-series caller is a fetch intent). Verified by 10 new guard
   tests in `tests/code/download_manager/test_dm_retry_keep_files.py`, including a behavioural
   harness that drives the real `_on_series_retry` with the background job inline: the
   complete-looking series survives, `force_clean=True` still wipes, the kill switch reproduces the
   legacy behaviour, and the worker still restarts after keeping the files.
   Regression: `tests/code/download_manager` 260 passed / 29 failed — all 29 are pre-existing
   source-pin tests for `socket_client.py` features not present in the working tree
   (`_POOR_NET_KPIS` etc.; `socket_client.py` unmodified since v3.5.5, my diff touches only
   `_dm_retry.py`), plus the known `test_instance_payload_key_variants.py` collection error.
   D3 is covered by the same change: the wipe no longer runs on the hot path, so the
   WinError-32 race with the viewer disappears with it.
2. **D1 — APPLIED (DM-D1, 2026-08-05, default-on, tune/kill via `AIPACS_DM_CANCEL_ESCALATE_S`,
   `<=0` disables).** After the root cause was corrected to a **zombie pool slot** (see §1), the fix
   landed in the worker bridge, not the scheduler: `DownloadProcessWorker._maybe_escalate_cancel()`
   — the poll loop arms a timer when it observes the cancel event set, and if the child has not
   delivered a terminal message within the grace period (default 8 s), the bridge terminates the
   subprocess itself (same ladder philosophy as DM-H4). The exit is reaped by the existing
   dead-process handling as a deliberate preemption (state already PAUSED+`is_auto_paused` →
   classic-preemption path; `completed(False)`, **no error signal**), the slot frees through the
   normal removal path, and `on_worker_removed → _start_next_pending` starts the critical study.
   On the 53346 timeline this converts the ~21 s zombie window into ~8.5 s worst-case (grace + reap)
   — and healthy cancels are untouched (a booted child acknowledges within milliseconds). Instance
   writes are atomic (DM-H2) and retries keep files (DM-R1), so an escalated terminate loses at most
   in-flight network work. **16 guard tests** in
   `tests/code/download_manager/test_dm_cancel_escalation.py`, including a replay of the measured
   53346 timeline (escalation fires at the first tick past 8 s, terminate exactly once, latched),
   disabled/negative-threshold/no-process/dead-process safety, and wiring pins (escalation runs in
   the queue-timeout branch before the liveness check; the escalated exit emits `completed(False)`
   without `error`). Neither touched file is plugin-mirrored.
3. **Intent storm — OPEN (mitigated by #1):** `request_object` still fires `request_critical_series`
   once per 250 ms while slices are missing; with the wipe gone this no longer causes re-transfers
   (the retried series skips existing files), but a stronger debounce keyed on "already downloading
   this series" would quiet the log and the queue.

**Live verify checklist:** open a growing study (acquisition in progress), watch
`download_diagnostics.log`: retries must log `DM-R1 no-wipe` and `skipped>0`; never a repeated
`downloaded=N skipped=0` round for the same series; no `WinError 32`; scrolling the viewed series
while it downloads must stay stable. For DM-D1: double-click-open a patient with a previous exam —
the viewed study's first series must start within ~10 s even when the preempted worker's subprocess
stalls in boot; if escalation fires, the log shows `DM-D1 cancel unacknowledged … terminating`
followed by `reaped after cancel escalation`, and NO error toast appears for the paused study.

Also worth telling the operator: single click deliberately never downloads (`single_click_auto_no_download`); the first 64 s of "delay" in this session was waiting between the single click and the double click.
