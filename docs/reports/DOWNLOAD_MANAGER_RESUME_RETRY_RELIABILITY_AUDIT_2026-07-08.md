# Download Manager — Resume / Retry Reliability Audit (2026-07-08)

**Scope:** Why the download queue does not continue correctly after the internet is
lost for several minutes and then returns — for both automatic resume and the two manual
control layers. **This is an audit + fix plan only. No code was changed.** Live validation
requires the Windows source build (clinical lane, human-assisted).

**Method:** Read-only exploration of `modules/download_manager/` (backend, network,
workers, UI control wiring), the authoritative design docs, and the current
`user_data/logs/`. Grounded in code paths and log evidence, not assumption.

**Anchor docs reconciled:**
`docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`,
`docs/reports/AUDIT_THUMBNAIL_DOWNLOAD_PIPELINE_2026-06-01.md`,
`docs/reports/STABILITY_FIXES_TAKEOVER_AND_LARGE_BATCH_2026-06-05.md`,
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` (OPT-04, OPT-05, OPT-09).

---

## 1. Root-cause analysis

The reported symptom ("queue does not resume after a multi-minute outage") is produced by
**two distinct defects that compound**. One is a genuine resume gap; the other is a
completion-convergence bug that the current logs show firing right now.

### Defect A — the temporary-failure retry budget drains *while still offline*, and nothing revives the study when the network returns (the primary resume gap)

The lower socket/series layers are actually resilient: `connect_with_retry`
(`network/socket_client.py:569`, 5 reconnects, backoff cap 30 s), per-request retries
(`REQUEST_MAX_RETRIES=3`), batch-halving on "Response too large", and the series-level
re-queue (`download/series_downloader.py`, `MAX_SERIES_RETRIES=3`). When those inner
retries are all consumed the study is marked **`FAILED`** in the state store
(`ui/widget/_dm_workers.py:794`, `_on_worker_error`). `FAILED` is **non-terminal** by
design (`state/state_machine.py`: `FAILED → {PENDING, DOWNLOADING, CANCELLED}`).

Recovery from `FAILED` is driven by `_check_auto_retry()` (`_dm_workers.py:889`) plus the
5-second sweep `_pipeline_health_check()` (`_dm_workers.py:1031`, timer armed in
`widget.py:323`). Both re-queue a failed study **only while `retry_count < cap`**, where
`cap = MAX_RETRIES_TEMPORARY = 10` for a network/temporary failure
(`_effective_retry_cap`, classified by `core/constants.py::classify_download_failure`).
The backoff is `min(30000, 3000 * (retry_count + 1))` ms.

The arithmetic is the bug: ten temporary attempts span
`3+6+9+12+15+18+21+24+27+30 = 165 s ≈ 2.75 min` of wall-clock. **An outage longer than
~3 minutes exhausts all ten retries before the link comes back.** Once `retry_count >= cap`:

- `_check_auto_retry` logs *"exceeded max retries … requires manual intervention"* and
  stops re-queuing.
- `_pipeline_health_check` (the anti-stuck backup) excludes it via the same
  `retry_count < cap` filter (`_dm_workers.py:~1085`).
- **`retry_count` is never reset** on partial progress or on connectivity return — only
  the manual "Reset All" / force paths call `state_store.reset()`.
- **There is no connectivity monitor.** Both classes named `ConnectionHealthMonitor`
  (`download_manager/network/health_monitor.py`, `modules/network/connection_health_monitor.py`)
  are passive tallies of past attempts — no ping, no socket probe, no OS online/offline
  event, no timer. Nothing detects that the network returned, so nothing flips the
  exhausted `FAILED` study back to `PENDING`.

Aggravating factor: because `retry_count` is never reset after a good stretch, intermittent
drops **accumulate** the count across the whole session, so a study can burn its entire
budget without a single sustained outage.

Blocked auto re-trigger: `add_downloads()` (`ui/widget/_dm_queue.py:62`) is idempotent — if
a state already exists (including `FAILED`) it skips creating a task
(`[DownloadTaskReused]`). Callers only pre-reset **terminal** `COMPLETED`/`CANCELLED`
states (`_hp_patient_open.py:541`), not an exhausted `FAILED`. So re-opening the patient
does not restart it either.

### Defect B — completion never converges to the queue rows, so a *succeeding* download is re-spawned forever (visible in today's logs)

The current `download_diagnostics.log` (2026-07-07 23:26–23:27) shows a single 16 MB
series downloaded to `progress=100.0% … retries=0` repeatedly by a chain of fresh
subprocess PIDs (25100 → 41948 → 32072 → 16608 → 43088 → 43980 → 31232). The cause is a
completion-convergence failure, not a network drop:

- `_do_update_status_badge | study_uid …0.83 not in download_rows during status update`
  — **216 occurrences**. The completed study is never matched to its UI row, so its status
  never settles to done.
- `_pipeline_health_check | ⚠️ Health check: 1 pending downloads but no workers! Starting
  next pending...` — **24 occurrences**. Seeing "pending but idle", the sweep re-spawns a
  subprocess and re-downloads the same, already-complete series.

This is the master-plan **OPT-04 "completion-by-notification, not by convergence"**
reliability defect (§1 of `CLAUDE.md`; the #1 reliability item). It makes the queue *look*
stuck/not-progressing to the user even though bytes are moving, and it directly undermines
manual retry (see §3).

### What is NOT the cause (ruled out with evidence)

- **Queue not lost/abandoned.** The task list is preserved on failure by design
  (`_cleanup_task_state` keeps `self._tasks[study_uid]`); logs show 93 recovered
  "connection lost" events, not dropped work.
- **Worker not leaked.** `WorkerPool._remove_worker` + `ensure_subprocess_dead` (DM-H4)
  free the slot cleanly on failure and fire `_start_next_pending`.
- **Cancellation tokens not reused.** Each retry constructs a **new** worker with a fresh
  `multiprocessing.Event` cancel flag — no stale-token carryover.
- **Partial files handled correctly.** Atomic `.part` → `os.replace`, resume scan rejects
  `.part` and sub-128-byte files, per-instance file-level skip (`rules/resume_rules.py`).
  Residual: resume integrity rests on a size ≥ 128 B check, not a DICOM-magic check
  (known, accepted in the ZETA plan).
- **Breakers not implicated.** The reception/API and report-status breakers auto half-open
  after a 180 s cooldown and, by explicit design, never touch the imaging download socket.
- **DB lock not implicated.** Zero `database is locked` events in the current logs.

### Answers to the ten critical questions

1. **Why no auto-continue after the net returns?** The 10-attempt temporary budget drains
   during the outage; `retry_count` is never reset and there is no connectivity monitor to
   re-arm the study. (Defect A)
2. **Why does manual resume "not work reliably"?** Manual **Retry** *is* wired and does
   flip the study back to `PENDING`, but Defect B means the re-run downloads to 100% and
   still never converges to "done", so the user sees perpetual churn; and the right-side
   **Start** button is a drifted duplicate that no-ops on some states (§3).
3. **Is the queue lost / stuck / wrongly completed?** Not lost. **Stuck** in `FAILED`
   (Defect A) or churning without converging (Defect B). Not wrongly marked completed.
4. **Is the worker still alive after failure?** No — it is torn down cleanly; a new one is
   spawned by the 5 s sweep (until the budget is exhausted).
5. **Cancellation tokens reused incorrectly?** No. Fresh event per retry.
6. **Is resume connected to the active queue service?** Yes — global/selected/row controls
   all reach the same `state_store` + `WorkerPool`; the gap is the missing network-recovery
   trigger, not a disconnected command.
7. **Global vs individual = different logic?** Partly. Cancel/Retry/Pause share
   `_on_per_patient_*`, but global **Start-All** (`_on_play`) and right-side **Start**
   (`_on_start_selected`) reimplement resume inline and have **drifted** (§3).
8. **UI resumable while backend terminal?** The reverse is the real drift: the backend
   `FAILED` is non-terminal but *stranded*, and a completed study is stuck showing
   non-done because it is "not in download_rows" (Defect B).
9. **Partial files correct?** Yes (see above).
10. **Race between pause/fail/reconnect/resume?** The dangerous window is Defect B's
    convergence gap (complete-but-unrendered → health-check re-spawn) and the optimistic
    global-pause badge that leads the real worker state. No corruption race (atomic writes).

---

## 2. Download queue state — current vs. desired

### Current status enum (`core/enums.py`)

```
PENDING · DOWNLOADING · PAUSED · VALIDATING · COMPLETED · FAILED · CANCELLED
terminal = { COMPLETED, CANCELLED }        (FAILED is recoverable)
```

### Current transitions (as implemented)

```
                enqueue
        ┌────────────────────────► PENDING ◄───────────────┐
        │                             │                      │ _check_auto_retry / health sweep
        │                       start worker                 │ (only while retry_count < cap)
        │                             ▼                      │
        │        ┌───────────── DOWNLOADING ───────────┐     │
        │        │                 │  │  │              │     │
        │   request_cancel    success│ │cancel      error│    │
        │   (pause)               ▼  │ ▼                ▼     │
        │        ▼            COMPLETED CANCELLED     FAILED ─┘
        │     PAUSED            (term.)  (term.)        │
        │        │                                      │ retry_count >= cap
        └────────┘                                      ▼
      resume/start                              FAILED (stranded — no revive,
                                                 no connectivity trigger)  ◄── the bug
```

Key gap: **network loss and permanent error both collapse into one `FAILED` value.**
The UI and the recovery loops cannot tell a *waiting-for-network* study from a
*truly-dead* one; they distinguish only by the hidden `retry_count`, which the badge does
not surface and which is never reset.

### Desired state machine (maps the requested design onto the codebase)

```
Pending ─────────────► Downloading ─┬─► Completed        (terminal)
   ▲   ▲                            │
   │   │ (auto, on net-up)          ├─► Paused ───────────► Pending      (manual resume)
   │   │                            │
   │   └── WaitingForNetwork ◄──────┤   network-class failure enters here,
   │            │                   │   NOT Failed
   │            │ connectivity      │
   │            │ monitor: net up   ├─► FailedRecoverable ─► Pending      (retryable error,
   │            ▼                   │        │                             budget/time left)
   └──────── (auto re-arm)          │        └─► FailedTerminal           (budget/time gone —
                                    │                (terminal-ish,        only manual retry
                                    └─► Cancelled     manual retry OK)      or net-up revives)
                                          (terminal)
```

Concrete mapping (no new enum churn required for phase 1):
- **WaitingForNetwork** = new sub-state or `FAILED` + `is_waiting_for_network` flag, set
  when `classify_download_failure` returns temporary. Excluded from the attempt-count cap;
  re-armed by the connectivity monitor.
- **FailedRecoverable** = `FAILED` + retryable (network budget/time remaining).
- **FailedTerminal** = `FAILED` + permanent classification OR non-network budget exhausted.
  Surface it distinctly in the badge so the user knows Retry is the only path.

---

## 3. Broken / divergent control paths

Three control surfaces exist (not two): **(A)** global toolbar, **(B)** right-side
"Controls" acting on the selected study, **(C)** inline per-row action buttons.

| Path | Wiring | Backend | Verdict |
|---|---|---|---|
| Global **Start All** | `_dm_ui_setup.py:163 → _dm_controls._on_play` | inline loop: PAUSED→PENDING, CANCELLED→reset, then `_start_download_worker` per item | **Divergent** — reimplements resume instead of calling `_on_per_patient_resume`; can drift |
| Global **Pause All** | `_dm_ui_setup.py:172 → _on_pause` | `worker_pool.cancel_all_non_blocking()` + loop set PAUSED | Works; **optimistic badge** leads real worker stop |
| Global **Stop All** | — | — | **Missing** — no dedicated Stop-All; Pause-All is the stop-equivalent (blocking `stop_all()` is intentionally not on the GUI thread) |
| Global **Refresh** | `_on_refresh` | updates label only | **Cosmetic no-op** (misleading — looks like it re-drives the queue) |
| Right **Start** (selected) | `_dm_controls._on_start_selected` | inline copy of resume, **missing the COMPLETED branch** the row Resume has | **Drifted duplicate** — no-ops on a completed study |
| Right **Pause / Cancel / Retry** | delegate to `_on_per_patient_*` | same as row buttons | **Consistent** ✓ |
| Right **Reset All** | `_on_reset_all` | global loop `state_store.reset()` | Global op mislabeled among per-item controls |
| Row **Pause / Resume / Cancel / Retry** | `action_buttons.py` signals → `_dm_retry._on_per_patient_*` | canonical implementations | **Consistent** ✓; button visibility derived from backend status |

Summary of the control problems:
1. **Two parallel resume implementations** (`_on_play`, `_on_start_selected`) hand-copied
   from `_on_per_patient_resume` and already drifted (missing COMPLETED handling). This is
   the "global and individual call different logic" concern — confirmed for Start/resume.
2. **No true global Stop-All** and a **cosmetic Refresh** button mislead the operator.
3. UI state itself is *not* a separate source of truth (good — it is derived from
   `state_store` via the observer pattern), so the drift is in the **command** paths, not
   in a divergent UI status store.

---

## 4. Fix plan — automatic resume (the core fix)

**Principle (per the request): one queue-resume mechanism; UI only sends commands; the DM
service owns state.** Do not add separate auto/manual patches. All three resume entry
points must converge on a single `resume_study(uid, reason)` service method.

**A1 — Add a real connectivity monitor (default-off flag `AIPACS_DM_NET_MONITOR`).**
A lightweight periodic reachability probe (`socket.create_connection((host, socket_port))`
against the resolved socket-protocol endpoint, every ~10–15 s, off the GUI thread) that
emits an `online→offline→online` transition signal. On the offline→online edge, call the
unified re-arm (A3). This is the missing piece — everything else already exists.

**A2 — Introduce `WaitingForNetwork` semantics.** When
`classify_download_failure()` returns temporary, mark the study waiting-for-network
(sub-state or `FAILED + is_waiting_for_network=True`) instead of letting it count down to a
hard stop. A waiting study is **excluded from the attempt-count cap** and is revived by A1,
not by the 10-attempt ladder.

**A3 — Re-arm on connectivity return / successful progress.** On net-up (A1) or on any
successful instance/batch, reset `retry_count` for waiting/temporary-failed studies and
flip them `→ PENDING`, then let the existing 5 s sweep (`_pipeline_health_check` →
`_start_next_pending`) drive them. Prefer this over an ever-growing attempt count.

**A4 — Make the temporary budget time-based, not count-based.** Replace/augment the fixed
10-attempt cap with "keep retrying a temporary failure every N seconds for up to T
minutes (or indefinitely while waiting-for-network)". Keep the permanent-error cap
(`MAX_RETRIES=3`) unchanged so a real 404/decode error still terminates.

**A5 — Fix the convergence bug (Defect B) — highest priority, it is firing now.** Resolve
why a completed study is *"not in download_rows during status update"* so completion
settles to done and the health sweep stops re-spawning it. This is master-plan **OPT-04**
work (re-key DM rows by canonical identity; off-GUI convergence sweep). Until A5 lands,
A1–A4 will resume correctly but the queue can still churn on the convergence gap. **Extend
OPT-04, do not open a new plan** (per `CLAUDE.md`).

All of A1–A4 must be flag-gated default-off with the legacy path preserved as a kill
switch, and guard-tested, per the master-plan process.

## 5. Fix plan — manual global resume

**G1 — Unify Start-All onto the shared service.** Replace `_on_play`'s inline loop with a
loop that calls the same `resume_study(uid, reason="global_resume")` used by the row
Resume, so global and individual can never drift again. Same for Pause-All → per-item pause
primitive.

**G2 — Add a real global Stop-All** (or relabel). Either wire a non-blocking "Stop All"
that cancels every active/pending study through the shared per-item cancel, or rename the
current control so operators are not looking for a Stop that isn't there.

**G3 — Make Refresh do something or remove it.** Have Refresh trigger a state
re-reconciliation (re-derive rows from `state_store`, useful for Defect B recovery) instead
of only updating a label — or drop it to avoid the false affordance.

## 6. Fix plan — manual individual resume

**I1 — Delete the drifted duplicate.** Make right-side **Start** (`_on_start_selected`)
delegate to `_on_per_patient_resume` (which already handles PAUSED/FAILED/CANCELLED **and**
COMPLETED), eliminating the missing-COMPLETED-branch bug. One resume implementation only.

**I2 — Surface FailedTerminal vs WaitingForNetwork in the badge + button visibility.**
Today Retry shows only on `FAILED` and Resume only on `PAUSED/FAILED`. With A2/A4 the badge
should read "Waiting for network" (auto, no action needed) vs "Failed — retry" (manual), so
the operator isn't left guessing whether a stalled study will self-heal.

**I3 — Confirm no cross-conflict.** Because per-item and right-side controls already share
`_on_per_patient_*`, once G1/I1 route global + selected Start through the same service, all
three layers invoke one mechanism — satisfying "both control layers must not conflict."

## 7. Logging improvements

The logs already recover well but hide the two defects behind noise:

- **L1 — Log every state transition once, structured.** Emit
  `[DM-STATE] uid=… series=… old=PENDING new=WAITING_NET reason=net_drop retry_count=…`
  from the single `state_store.update` choke point (it already fires observer events —
  add a structured line). This makes the state machine auditable end-to-end (deliverable
  requirement #10) and directly shows the Defect-A stranding and Defect-B churn.
- **L2 — Log connectivity transitions** from A1: `[DM-NET] online→offline` /
  `offline→online → re-arming N studies`.
- **L3 — Escalate the convergence symptom.** `"not in download_rows during status update"`
  is at WARNING and fired 216× — tie it to the study uid + a `[DM-CONVERGE-MISS]` marker
  and a counter so the re-spawn storm is one grep, not 216 lines. (Complements OPT-09 log
  hygiene.)
- **L4 — Log retry-budget exhaustion distinctly:** `[DM-RETRY-EXHAUSTED] uid=… class=temporary
  retry_count=10 waiting_for_network=…` so the "requires manual intervention" moment is
  greppable and separable from permanent failures.

## 8. Validation test results

**Not run — this is an audit-only pass, and full validation requires the Windows source
build (clinical lane, human-assisted).** The validation matrix to run after the fix lands
(each must show the structured `[DM-STATE]` transitions from L1):

1. Start a multi-patient queue; confirm sequential single-slot progress.
2. Disconnect internet for **> 5 minutes** (longer than the current ~3-min budget — this is
   the exact repro window).
3. Confirm active/queued studies move to **WaitingForNetwork**, *not* stranded `FAILED`.
4. Reconnect; confirm **automatic** resume fires from the connectivity edge (A1/A3) with no
   click, and downloads continue from partial files (no duplicate re-fetch).
5. Repeat and exercise **Resume-All** from the left toolbar (G1) — same underlying service.
6. Repeat and exercise **Resume** from the right/row controls (I1) — same service.
7. Confirm already-downloaded files are **not** re-downloaded (resume scan) — and that the
   Defect-B churn (repeated 100% re-download of one series) is gone (A5).
8. Confirm partial series resume incrementally; complete series are not re-fetched.
9. Confirm the badge distinguishes **Waiting-for-network** (auto) from **Failed-terminal**
   (manual) (I2).
10. Confirm `download_diagnostics.log` shows clean state transitions and **zero**
    `not in download_rows` / "no workers" re-spawn storms over a 10-minute soak.

**Pre-fix log evidence captured this session** (baseline to beat):
`not in download_rows` ×216, `no workers` re-spawn ×24, recovered "connection lost" ×93,
"Response too large" halving ×48 (all recovered), 0 `database is locked`.

---

## Recommended sequencing (extend the master plan, don't fork)

1. **A5 / OPT-04 convergence fix first** — it is actively firing and undermines every other
   resume path. Extend OPT-04 in the master plan §9/§15.
2. **A1 connectivity monitor + A2/A3 waiting-for-network re-arm** — closes the reported
   "won't resume after a multi-minute outage" gap.
3. **A4 time-based temporary budget** — hardens against long/intermittent outages.
4. **G1 / I1 control unification** — one `resume_study` service; deletes the drifted
   Start duplicates; adds real Stop-All / fixes Refresh.
5. **L1–L4 logging** — land alongside each of the above so validation (#10) is greppable.

Every code change: flag-gated default-off, legacy path preserved as kill switch,
guard-tested, and validated on the source build before default-on — per `CLAUDE.md` and the
master-plan process. After implementation, update
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` §9 (status) and §15 (validation).
