# Other-PC (Production Frozen Build) Log Evaluation — 2026-06-05

Source: `C:\Users\Dr.Alizadeh\Desktop\log on other pc` — 5 log files, 41.5 MB,
**frozen build** (`build_mode=frozen`, version=unknown), real clinical use
2026-05-27 → 2026-06-05 with very long sessions (uptimes 12 h and 55 h).

Goal: find problems evidenced in production that the current source version has
NOT solved — and confirm which of our recent fixes that machine is missing.

## 1. Problems CONFIRMED in production and FIXED here but NOT YET SHIPPED

| Production evidence | Our fix (source tree, this week) |
|---|---|
| **Dead sidebar: 28 `series_info_inactive_skip` events over 3 days** (patients 44640…44991) — every one is an open whose series-info/right-panel leg was discarded → "0 series", nothing to drag | Open now marks the active selection (`_hp_patient_open.py`, 2026-06-05) — live-verified |
| **34 `GetStudyInfo` timeouts across 6 days** — every affected open paid the full dead-probe wait (3–6 s in that build) | Probe timeout 1.2 s + persisted 7-day capability cache (`server_capabilities.json`) |
| Cold subprocess spawn before every fresh study's first request | §14 pre-warm pool (config-enabled) |
| Post-`POST_DOWNLOAD` booster stall; open-path `servers.json`/DB reads on GUI thread | Issue-6 fixes (2026-06-04) |
| 6× "Application initialization canceled - another instance running" bursts — users re-launching repeatedly (window likely not raising in that build) | QLocalServer ACTIVATE→raise (2026-06-02) — if the frozen build predates it |

**Action: these alone justify shipping the next build** — the dead-sidebar fix is
the single highest-impact item (28 production hits in 3 days).

## 2. Problems in production that are STILL UNSOLVED in the current version

### U1 — "Response too large" download failures (REAL data-loss-of-service) · HIGH
16 failures (`series 8 - Response too large` ×12, generic ×4): a series whose
batch response exceeds the client's socket response limit fails outright — the
adaptive batch sizing evidently did not shrink far enough (or a single instance
already exceeds the cap). Nothing in the current tree changes this path.
*Recommended fix:* on `Response too large`, halve the batch (down to 1) and
retry within the same series pass; if a single instance still exceeds the cap,
raise the per-response limit for that request or stream-chunk it. Add the
failure reason to the DM badge so users see why a series is missing.

### U2 — Native crashes in the ADVANCED (VTK) viewer path · HIGH
6 access violations in `native_fault.log`, faulting threads:
- `viewer_2d.py:276 __init__` ×4 — `SetInputData(self.image_reslice.GetOutput())`
  during Advanced-viewer construction (VTK object/GPU context lifecycle);
- `loading_overlay.py:441 _start_fade` ×1 — fade animation on a dying widget
  (Qt teardown UAF family);
- `thumbnail_manager.py:53 __init__` ×1.
Notably **zero 0x8001010d** on that PC — the drag/COM family does not occur
there; their crash profile is the VTK init/teardown family instead, which we
have NOT addressed. *Recommended:* guard `image_reslice.GetOutput()` readiness
in `viewer_2d.__init__`, stop overlay animations in widget close/teardown, and
reproduce under the GUI test tier on a similar GPU.

### U3 — Tab-CLOSE stalls (`exit_patient_widget`) · MEDIUM
22 user-facing stalls in the close path — a family we have never profiled (all
our work targeted open/scroll/download). *Recommended:* trace one close on the
source build; likely synchronous cache/booster/VTK teardown that can reuse the
deferred patterns we applied elsewhere.

### U4 — The styling/notify stall family remains the production #1 · MEDIUM
Of 498 user-facing stalls (0.4–60 s; median 462 ms, p95 6.6 s, 119 over 2 s),
**305 land in `main.py:notify`** — the theme/styling construction bursts
(post-login home build, per-tab styling). We fixed neighbours but deliberately
deferred this family (guarded V2 styling layer). Production data now shows it
is the dominant remaining lag source. *Recommended:* the deferred-styling pass
(apply theme after first paint) as its own carefully-soaked change.

### U5 — Assorted GUI-thread blocking (smaller, repeated) · LOW-MEDIUM
`reception_data_service.fetch_patient_data` ×7 (sync fetch on GUI),
`_dm_details._add_download_row_to_table` ×7, `subprocess.py:_wait` ×5 (someone
waits on a child process from the GUI thread — find the caller),
`iconic_font.load_font` ×4, `patient_table_widget.add_patient_data` ×4.

### U6 — Frozen-build-only: PyInstaller archive extraction stalls · LOW
`pyimod01_archive.py:extract` ×8 — runtime module extraction from the frozen
archive blocks the GUI on first-touch imports. Invisible in source-build
testing. *Recommended:* onedir packaging or pre-extracting hot modules at
splash time in the build config.

### Network robustness notes (handled, but worth watching)
8× `NetworkError: Connection closed by server` + 104× `GetReportStatus`
timeouts — their server/link is flakier than ours; reconnect-with-backoff and
bounded timeouts did their job (no hangs), but report-status UX degrades
silently.

## 3. Confirmations (problems absent on the other PC)
No DB locks, no port-105 misroutes, no 45 s socket timeouts, no WinError 5
(no Proxifier there), no `UnboundLocalError` grow bugs in this period, and —
notably — no COM/OLE drag faults. Preemption ("Paused for higher priority")
fired 27× and behaved.

## 4. Priority order
1. **Ship the current fixes** (dead sidebar + probe cache + prewarm + Issue-6) —
   §1 shows them biting production daily.
2. **U1 Response-too-large retry** — small, contained, prevents silently
   missing series.
3. **U2 VTK init/teardown AV guards** — production's actual crash family.
4. **U3 close-path profile + fix**, then **U4 deferred styling** (the big lag).
5. U5 callers off-threaded opportunistically; U6 at next build.

*Method: signature sweep + stack aggregation over app/viewer/download/db/native
logs; stall magnitudes filtered to the 0.4–60 s user-facing band (sleep/lock
gaps excluded — raw max was 5.6 h of machine sleep).*
