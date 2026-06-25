# Download/view optimization — review + KPIs (2026-06-24, revised)

Target poor-network server: **mehr** (`5.57.36.202`, the only `poor_connectivity:true`
server; no "Abadan" server exists in config — mehr stands in for it). Fast-network
reference: **razi** (LAN). Per-server data root in use: `user_data/servers/<id>/...`.

## 0. Direction (corrected per user, 2026-06-24)

Two earlier ideas are **explicitly rejected** and must NOT be implemented:
- **No auto-load of the first series on Patient-Tab open.** The first series is often
  a localizer/scout/planning/non-diagnostic series; the physician chooses. On open we
  load thumbnails / the series list only and wait for an explicit drag-drop / select.
- **No middle-slice default.** A dropped series shows the **first slice in correct
  stack order** and continues loading in normal order — never jumps to the middle.

Optimization effort is centered on: (a) the **user-selected** series path (fast first
image after the user picks a series), (b) **series-switch** performance, and (c) the
**network-independent** file-arrival→render path + controlled CPU/RAM.

## 1. Method

Reviewed the pipeline in code, then captured **fresh live KPIs** by driving the running
source build (Windows-MCP) against a non-cached mehr patient (15452, US) and reading the
live logs. Download-only; no clinical data modified.

## 2. Fresh measured KPIs — mehr, patient 15452

| Stage | Measured |
|---|---|
| Single-click → thumbnails (non-cached) | ~430 ms |
| mehr server latency / request | ~122–146 ms (razi LAN ≈ 45 ms) |
| Open → download starts (`[POOR_CONN] batch_size=1`) | ~1.08 s |
| First image on disk (TTFI) | ~7 s after dl start (~8 s after open) |
| Per-image rate on mehr | ~2.2–5 s/image |
| Series complete, 7 img (TTFC) | 17.3 s (~2.5 s/img) |
| First image render once loaded | 960 ms (render-bound) |
| Main-thread stall during series load | **2.4 s UI freeze** |

## 3. Findings vs the corrected acceptance criteria

- **#1 (no auto-load on open) — ALREADY CORRECT.** Viewports stay empty
  ("Drop a series here…") on open; a downloaded-but-unviewed series is
  `load_series_on_demand_background_skip`'d (confirmed in the live log). My earlier
  auto-load idea is dropped.
- **#2 (first slice, not middle) — ALREADY CORRECT in code.** `qt_viewer_bridge.
  reset_image_viewer` sets `target_slice = 0` on a fresh load; a non-zero start only
  happens via `preserve_slice` (switch-back state preservation, which is desirable —
  #4). The live "slice 7" was preserved state from a prior interaction, not a
  middle-default. (To be re-confirmed live with a clean fresh drop.)
- **#3 (optimize the user-selected series) — in place.** A drag promotes that series
  (`request_critical_series_download`) and the progressive display grows it as slices
  arrive; per-slice atomic cache (`.part`→`os.replace`) is immediate.
- **#4 (series-switch / cache reuse) — architecture present, needs live measurement.**
  ZetaBoost full-series cache (decoded volume, keyed by series, guarded by
  `_cache_entry_study_matches` so a multi-study/previous-exam key can't return another
  study's volume) + viewer-widget reuse + `preserve_slice` ⇒ switch-back should reuse
  the decoded volume with no re-decode. The new **TTSSD** KPI measures it.
- **#6 (file→render path) / #7 (CPU/RAM):** decode (`decode_ms`) + render are logged
  per first-image; the **2.4 s `MAIN_THREAD_STALL`** is the concrete network-independent
  bottleneck (synchronous full-series build on the GUI thread — scales badly to large CT/MR).

## 4. Shipped this pass (flag-gated, additive logging, regression-clean)

KPI markers (default ON; kill switch `AIPACS_POOR_NETWORK_KPIS=0`):
- `[KPI] kind=TTFI/TTFS/TTFC scope=download` — first/second/full image on disk anchored
  to series-download start, fresh-series only, + `avg_slice_ms` (`socket_client.py`,
  mirrored).
- `[KPI] kind=TTFI scope=viewer` with `ttd_ms` (decode) + `ttr_ms` (render) +
  `total_ms` — the file→render decomposition (`qt_viewer_bridge.py`, mirrored).
- `[KPI] kind=TTSSD scope=viewer` — Time To Series Switch Display: user drop/select →
  first visible image of the requested series (`_vc_switch.py`, not mirrored).
- Umbrella flag `is_poor_network_progressive_load_enabled()` /
  `AIPACS_POOR_NETWORK_PROGRESSIVE_LOAD` (auto-on for mehr; existing poor-connectivity
  resolver untouched).
- Tests: `tests/code/download_manager/test_poor_network_kpis.py` (7). Full
  `tests/code/download_manager` = 280 passed. The rejected middle-slice helper was removed.

## 5. Remaining work (needs the two-network live runs below)

- **Series-switch review (#4)** — measure TTSSD across: loaded→loaded, cached→cached,
  cached→non-cached, large CT/MR, switching during background download; confirm prior
  state preserved + no unnecessary re-decode + cache reused. Mostly a **measurement**
  task on razi; fix only what the numbers expose.
- **2.4 s main-thread stall (#6/#7)** — confirm the synchronous full-series build on the
  GUI thread and move it off-thread / chunk it (bounded concurrency, no uncontrolled
  parallel decode). Preserve the FAST-no-VTK rule.
- **CPU/RAM peaks (#7)** — sample with the existing `_emit_resource_probe` (RSS/RAM) +
  `MAIN_THREAD_STALL`; do NOT add synchronous psutil on the viewer hot path (banned by
  the FAST stack-drag fix).

## 6. Two-network test strategy

**A. Poor (mehr).** Open a non-cached patient, drag a *user-selected* multi-slice series.
Capture from the logs: `[KPI] TTFI/TTFS/TTFC` (after selection), per-slice cache writes,
retry/`[POOR_CONN]`, background continuation, UI feedback. Verify the first displayed
slice is slice 1 (stack order) and no unrequested series is preloaded.

**B. Fast (razi).** Switch the active server to razi. Open a cached + a non-cached
CT/MR. Drag/select series and switch repeatedly. Capture: `[KPI] TTSSD`, `ttd_ms`
(TTD), `ttr_ms` (TTR), `MAIN_THREAD_STALL` (UI freeze), resource probes (CPU/RAM). The
question is whether decode/render is the bottleneck **even when the network is fast**.

Grep helper (either server): `Select-String '\[KPI\] kind=' user_data\logs\*.log`.
