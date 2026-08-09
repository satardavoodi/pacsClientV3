# Series 202 slow to viewport (patient 53417) — cold header scan (WU-1)

**Symptom.** Patient 53417 (previously downloaded, 444/444 files on disk):
after double-click open, series 202 took ~15.7 s to show in the viewport
(user report + `first_series_visible t_ms=15654.6`). No freeze — the GUI
stayed responsive (max stall 240 ms); this was async pipeline latency.

## Evidence (2026-08-08 13:57, pid 324372)

| t (from open 13:57:30.6) | Event |
|---|---|
| +0.6 s | patient opens, first series visible |
| +6.6 s | tab restores last-viewed series 202 → stub switch (206 ms, placeholder) |
| +6.8 s | `FAST:meta_cache source=miss ... cache_size=0` → header scan starts |
| +6.8 → +15.5 s | `header_scan_parallel files=444 workers=8 probe_per_file_ms=40.5` — **8.6 s** |
| +15.5 s | `DB_METADATA_AUTOVERIFY ... geometry_match=True -> DB trusted` (db_lookup=16 ms) |
| +15.7 s | real switch (×2 — VS-1 duplicate pattern, task #24) → images visible |

## Root cause

First-touch-after-boot per-file cost is **AV on-open scan + cold I/O**, not
parsing: the probe is already header-only with `specific_tags`, and the
adaptive pool caps at ~2.3× regardless of thread count.

Bench on this machine (cold month-old series, production probe, 100 files/arm):
`seq 23.1 ms/file · t8 9.8 · t16 31.0 (series noise) · t24 9.8` — and WARM:
**0.88 ms/file sequential** (whole 444-file series ≈ 0.4 s). More workers are
a dead end; warmth is everything.

## Fix (WU-1) — chosen: "speed up the probe, keep full verification"

`PacsClient/pacs/patient_tab/utils/series_file_warm.py` (new) +
one hook in `_hp_patient_open._background_setup_thread`:

At patient open (+0.9 s, already off the GUI thread), a fire-and-forget
daemon thread opens + reads the head (256 KB) of every on-disk instance file
of the opened studies — paying the one-time AV verdict and pulling header
bytes into the OS cache while the open pipeline and the user's think time run.
The switch-time scan is **unchanged**: it still reads and fully verifies every
file — it just hits warm caches (~0.4 s instead of ~8.6 s for 444 files).

Guards: read-only; blank-path guard (empty string would walk the CWD);
budgets (4000 files / 30 s / 256 KB head, env-tunable); one concurrent warm
per study set; every failure swallowed. Kill switch:
`AIPACS_SERIES_FILE_WARM=0`.

## Tests

`tests/code/viewer/test_series_file_warm.py` — 12 pins (reads all series
files, chunk semantics, missing/blank-path safety, file+time budgets, kill
switch, duplicate-warm refusal, async lifecycle, flag parsing, source pin on
the open hook). Full run with the two existing header-scan suites:
**31 passed**. `py_compile` clean on both edited files.

## Expected effect & residuals

* Warm ≈ 444 files × ~10 ms / 8 threads ≈ 2–4 s starting at +0.9 s → done
  before the +6.6 s tab restore → series 202 to viewport ≈ **~7 s total,
  ~0.5 s after the switch** (vs 15.7 / 8.6 s). Repeat opens same boot: fast
  regardless (AV verdict + OS cache persist).
* If the user clicks a big series within ~3 s of open on a cold boot, the
  benefit is partial (scan overlaps the remaining warm; adaptive pool still applies).
* Requires app restart. Verify live via `[SERIES_FILE_WARM] files=... MB=...`
  then `probe_per_file_ms` < 8 on the next cold open.
* Untouched candidates: VS-1 duplicate switch (#24), VS-2 cv2/viewer prewarm
  (#25); `utils._safe_dcmread` mutates global `warnings` filters per call —
  thread-unsafe wart worth a look someday (not the bottleneck).
* 2026-08-07 note: yesterday's IMP-3 prewarm fix validated live today —
  "Chromium engine warmed (construct+setUrl 219/227 ms)" with no collisions.
