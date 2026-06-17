# AI-PACS — Live Impatient-User Stress Runbook

Run on the **source build** (monitor A) after a **restart** (to activate the F1 report-status fix). Keep VS Code on monitor 2. **Stop the concurrent `--clean-build`** first so KPIs aren't starved. Watch these logs live (UTF-8):

```
.venv\Scripts\python.exe C:\Temp\aipacs_stress\log_scan.py        # error/timeout/lock/crash tallies
.venv\Scripts\python.exe C:\Temp\aipacs_stress\stall_mine.py      # main-thread stall distribution
.venv\Scripts\python.exe C:\Temp\aipacs_stress\run_tool.py tools\performance\stall_correlation_report.py --top 5
```
**Pass bar per step:** no freeze > 1 s on interaction; no new `right_panel_socket_error`; no duplicate download task; correct patient's images only; memory returns toward baseline after closing tabs.

---

## S1 — Multi-study pressure (Patient ID **1**, 20 studies)
1. Search → single-click Patient 1 repeatedly/fast → confirm thumbnails load, no stale set, row highlight instant.
2. Double-click to open; switch between the 20 studies rapidly; refresh.
3. **F1 check:** during opens, `download_diagnostics.log` should show the breaker WARNING **once**, then **no** repeating `GetReportStatus: timed out`; `stall_mine.py` should show fewer/shorter `interaction=False` stalls than the pre-fix baseline (p95 was 1.5 s).
- Watch: cross-patient leakage (only Patient 1 studies), thumbnail↔series correctness.

## S2 — High-slice CT (pt **562346**, 802 slices)
1. Open; drag series 3 into a viewport; **scroll aggressively** top↔bottom.
2. Drag-drop the same series again; replace an occupied viewport; scroll immediately after drop.
3. Watch: `viewer_diagnostics.log` `headers_only_build` (H1 — expect ~0.8–1.4 s on first open), `[MAIN_THREAD_STALL]` during scroll, memory. No stale stack after viewport replacement.

## S3 — Many-series / cardiac (pt **40921**, 135 series; then **46030** server-only)
1. 40921: fast-switch across many series; confirm series-list + thumbnails keep up; drag several different series into viewports.
2. 46030: search on **server**, open (not-downloaded) → confirm download starts, switch patient mid-download, **reopen 46030** → **no duplicate task**, resume correct; missing/new server series synced.

## S4 — X-ray / DX large image (pt **44876** = 55 MP, **42275** = 47 MP)
1. Open; zoom/pan/window-level; length measurement; drag-drop.
2. Watch: no freeze decoding the 55 MP image; WL/zoom stay responsive; large dimensions don't hang the viewer.

## S5 — Mammography (pt **42552** + others, MG)
1. Open; test hanging/layout if available; zoom/pan/WL; switch views; measurements.
2. Watch: memory + render responsiveness on large MG images; view switching has no stale image.

## S6 — Viewer-widget lifecycle
Drag into empty viewport → replace occupied → drag same series again → drag a series already open elsewhere → scroll immediately after each drop → use length/WL after repeated replacements. Confirm: no stale image stack, stale metadata, stale events.

## S7 — Tools & MPR
1. Length, window/level, zoom/pan, scroll, layout switching; switch tools **while images load**.
2. MPR: open MPR-capable series; rotate/reformat; scroll planes; switch away mid-MPR; open another patient after MPR. Watch VTK memory across repeated MPR opens (B7).
3. **Invariant:** FAST viewer must never instantiate a VTK render window (confirm in logs).

## S8 — Download-manager switching pressure
Open 3–4 not-downloaded patients in quick succession; start downloads; switch patients while active; reopen a downloading patient. Confirm: no duplicate task starts (`test_download_task_dedup` covers the unit case), state stays reliable, partial studies fetch only the missing tail.

---

### After the session
- Re-run the three watchers above; diff stall p95 / timeout count vs the pre-fix baselines in `IMPATIENT_USER_STRESS_REPORT_2026-06-16.md §3`.
- File any new freeze/dup/stale finding into `TECH_DEBT_REGISTRY_2026-06-16.md` (Part A format: where / observation / risk / related case).
