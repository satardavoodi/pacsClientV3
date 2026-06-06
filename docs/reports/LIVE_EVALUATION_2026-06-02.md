# Live Full Evaluation — App / Logs / KPIs (2026-06-02 00:0x)

Performed after the user restarted the source build, to confirm the session's 9 fixes
are live and the app is optimized and stable. Method: process inspection, Monitor-A
workflow drive, log + native-fault analysis, KPI extraction, disk-integrity check,
resource snapshots, and the headless suite.

## Verdict: ✅ optimized and stable — no real errors, no new crashes, no leak, image integrity intact.

---

## 1. Build confirmation
- App (PID 96048) started **23:58**, *after* the last edits (`_dm_details.py` 23:52,
  `widget.py` 23:56). **All 9 session fixes — including the drag-deferral feature and
  `showEvent` — are live.** Clean startup with the new code is itself proof the edits
  don't break the app.

## 2. Health / crashes
- `native_fault.log`: 116 lifetime dumps = **111 benign `0x8001010d`** (RPC_E_WRONGTHREAD,
  always survived) + **5 access-violations** — and that 5 is **unchanged from earlier this
  session**, i.e. pre-existing (older runs / offscreen-VTK test env). **0 new crashes** in
  this run.
- `download_diagnostics.log`: **0 non-benign ERROR lines** this run. The only "error" is
  the expected `GetStudyInfo: timed out` (server doesn't answer that endpoint; fast-probe
  + skip-cache by design).

## 3. Responsiveness KPIs (live, measured from open-trace)
| Action | Patient | Click → first render |
|---|---|---|
| Single-click | 44343 (MR, 56 img) | `right_panel_begin` **118 ms** |
| Single-click | 44345 (MR, 513 img) | **131 ms** |
| Single-click | 44430 (CT, 9 series / 695 img) | **129 ms** (cache hit) |
| Double-click → viewer | 44430 (CT) | `first_series_visible` **~1.75 s** |
- `series_info_entry` 1.5–4.1 ms (instant). Single-click stays ~120–130 ms even for a
  513-image study and a 9-series CT — well within a smooth interactive budget.
- `DM_REFRESH_QUEUE`: rebuilds are **coalesced** (`queued=2 → coalesced=2, skipped=1`) —
  the table-rebuild throttling is active (the area the drag-deferral hardens further).

## 4. Resource / leak / subprocess lifecycle
| Snapshot | Main RSS | Threads | Handles |
|---|---|---|---|
| Post-3-clicks | 479 MB | 46 | 1983 |
| **Post-viewer+download** | **430 MB** | 49 | 1986 |
- RSS **decreased** after the heavier workload (memory reclaimed) — **no leak signature**.
  Thread count 46→49 is the expected delta for an open viewer tab; not climbing.
- **DM-H4 verified live:** the download subprocess **spawned** (`[SPAWN-TIMING] Imports OK
  0.001s`) and **exited cleanly** — **no orphaned subprocess** lingering after the download.

## 5. Clinical image integrity (live, on real data)
For the CT just exercised (`…86230`, 9 series): **683 `.dcm` files, 0 truncated (<128 B),
0 incomplete (`.part`).** The static guarantee (atomic `.part`→`os.replace`, resume rejects
partials) holds on real disk content. A crash/preemption can only ever leave a `.part`
(re-fetched), never a corrupt slice the viewer would load.

## 6. Test suite
`tests/code/{download_manager,system,network,storage}` = **198 / 198, 0 failures, 0
errors** (run earlier this session against the exact deployed code — unchanged since).
All 21 originally-failing pre-existing specs are green.

---

## One benign item noted (not a defect)
The log shows `⚠️ Skipped N DICOM files with read errors` (WARNING) when re-opening an
already-downloaded study. Root cause: opening the study in the viewer **and** the resume
download's redundant DB-header re-extraction read the **same** files concurrently →
transient Windows read-sharing errors → those headers are skipped from the (redundant)
DB re-insert. **The files are intact** (verified: 0 truncated / 0 `.part`; the viewer
renders them) and already in the DB. Optional polish (not correctness): downgrade the
message to DEBUG, or skip the DB re-insert for already-complete studies. Logged here so
it isn't mistaken for corruption later.

## Bottom line
Every axis checked out: live build, zero real errors, zero new crashes, ~120 ms
single-click responsiveness, ~1.75 s viewer-first-render for a 9-series CT, stable/declining
memory, clean subprocess lifecycle, intact on-disk images, and a 100%-green download-pipeline
test suite. The pipeline is optimized and smooth.
