# Fast UI Validation (ui_probe) — Build + First Run Report (2026-06-04 18:14–18:19)

## 1. What was built

**`tools/testing/aipacs_control_mcp/ui_probe.py`** — a sub-second UI observer that external
screenshots cannot match: a local capture thread (mss) records the app window continuously at
~17–25 fps into a downscaled ring buffer. Every bus command run through `UiProbe.run()` gets:

- **before.png / first_change.png / worst_event.png / stable.png** — the exact frames around
  the command (pre-state, first UI response, biggest transient, settled state);
- **clip.gif** — a short recording (≈0.5 s before → stable) per command — the "optional screen
  recording" requirement, implemented;
- **tab_strip.png + tab_strip_std** — automatic crop + content metric of the patient-tab
  header (detects the intermittently-missing small tab thumbnail);
- **records.json** — per-region (full / tab strip / right panel / viewport) frame-diff series
  with computed `first_response_ms`, `stable_ms`, **flicker events** (A→B→A transients),
  **blank dips** (luma collapse/recovery), plus bus `elapsed_ms` and capture fps.

**`ui_validation_run.py`** — drives the full checklist through the probe (thumbnail clicks ×5
incl. a repeat, CT open, CT drops ×2, progressive watch window, DX open, DX drop) and joins
the app logs (`INTENT_PRIORITY`, `UX_FIRST_IMAGE_VISIBLE`, `PROGRESSIVE_GROW`, preempts,
`load-on-demand FAILED`) into the same timeline. Artifacts: `ui_probe_runs/<ts>/` (this run:
`20260604_181405`, 58 files).

## 2. Run results vs the checklist

| Check | Measured | Verdict |
|---|---|---|
| §4 Thumbnail clicks (44915, 44868, 44734, 44942 + repeat 44915) | first response 219–594 ms (cached), settle ≤774 ms; repeat click 494/561 ms; **0 flicker events, 0 blank dips in the right panel across all 5** | ✅ smooth, no flicker/jump; **⚠ fresh patient 44734: 3,497 ms to first response and not settled within 4 s** — the slow path is the server round-trip on first-ever click (cache-gate then socket fetch), not a render glitch |
| §5 Double-click open (44734 CT, 44829 DX) | tab content first visible 968 ms / 785 ms; settled 2.1 s / 0.8 s; **small tab thumbnail PRESENT both times** (tab_strip_std 21.4/20.3, crop shows patient image beside "elena iranshahi ID: 44734") | ✅ opens immediate, name + mini-thumbnail correct. The 4 "blank dips" per open are the dark viewport area replacing the bright home table — expected content change, correctly classified by region (right-panel/viewport series show no anomalous dips). The missing-thumbnail bug did **not reproduce**; the detector now exists to catch it when it does |
| §6 Drag-drop CT | loader visible in **70 ms**, viewport stable 125 ms; second drop (vp1) produced no measurable change — series was already displayed there (idempotent re-drop, render-coalescing working as designed) | ✅ no freeze, loader correct |
| §6 Drag-drop DX (heavy single images) | first response 102 ms, stable 546 ms | ✅ |
| §7 Priority escalation | `INTENT_PRIORITY` fired on drop; 0 preemptions needed (slot free); 0 `load-on-demand FAILED` | ✅ escalation path exercised; under contention see the 12:57 storm (preempt verified there) |
| §8 Progressive sync | 19 `PROGRESSIVE_GROW phase=start` events; `UX_FIRST_IMAGE_VISIBLE`: series 202 at 161 ms, 201 at 65 ms, DX at 94 ms after load; progressive watch window stable | ✅ first images fast, growth running, no stuck-on-first-batch |
| §9 KPI capture | per command: send time, bus elapsed, first-response ms, stable ms, per-region diff series, screenshot timestamps; log-joined priority/first-image/grow marks | ✅ all captured in records.json/summary.json |

**Glitches detected this run: none** (0 flicker, 0 anomalous dips, no missing tab thumbnail,
no drop failures). **Real finding:** the fresh-patient first-click latency (3.5 s, unsettled at
4 s) is the dominant visible lag — root cause is the known first-fetch path (server thumbnail
round-trip on a never-clicked patient), now precisely measurable per run.

## 3. How to use it

```powershell
# app running with AIPACS_TEST_SERVER=1, then:
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\ui_validation_run.py
# artifacts: tools\testing\aipacs_control_mcp\ui_probe_runs\<ts>\<step>\{before,first_change,stable,worst_event,tab_strip}.png + clip.gif
```
Or wrap any command ad-hoc: `UiProbe(client, out_dir).run("label", "change_series", {...})`.
Requires `mss` (installed). Capture ≈17–25 fps ⇒ ~40–60 ms temporal resolution — an order of
magnitude finer than MCP screenshots, with the recording requirement covered by per-command GIFs.

## 4. Known limits / next steps

- 06_ct_drop_vp1-style no-op steps yield empty metrics by design (no pixels changed); the
  runner could pre-check viewport state to choose a differing series.
- Open-transition dips are expected content change; per-region verdicts (right panel,
  viewport) are authoritative — full-window dips during opens should be read with that lens.
- For >30 fps or HDR-accurate color, DXcam would replace mss (only if a glitch ever escapes
  this resolution). Channel order fixed (mss RGB) for future runs; this run's PNG/GIF colors
  are channel-swapped cosmetically — metrics unaffected.
- Missing-tab-thumbnail hunt: run `ui_validation_run.py` in a loop (5–10 opens of varied
  patients) — `tab_strip_std < ~8` flags an absent thumbnail automatically.
