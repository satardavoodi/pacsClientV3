# AI-PACS — Test-Suite Health & KPI Baseline

**Date:** 2026-07-23 · **App version:** 3.5.4 · **Machine:** dralizadeh (Windows)
**Toolchain:** Python 3.13.5 · pytest 9.0.3 · PySide6 6.10.2
**Scope run:** headless lanes (unit / integration / offscreen-Qt / property / CI-safe GUI / performance) + a new dedicated re-sync guard.
**Deferred (by request):** the `-m live` clinical lane (MCP-connected, server-sync, pywinauto) and the `-m build` lane.

> ⚠️ **Working tree was DIRTY at run time.** `git status` showed uncommitted work (OPT-39 `_vc_progressive.py`, offline-cloud files, `builder/release_gate.py`, `config/patient_table_sort.json`) and untracked new files. Some results below reflect in-progress changes, not a clean release — this is called out where it matters. HEAD = `79b28137 release(v3.5.4)`.

---

## 1. Overall status

| Lane | Command | Result | Time |
|---|---|---|---|
| **Fast (merge gate)** | `pytest tests/code -q -n auto` | 🔴 **28 failed**, 1 error, 6145 passed, 58 skipped, 79 xfailed, 7 xpassed, 85 rerun | 9m 25s |
| Property (hypothesis) | `pytest tests/code -m property` | 🟢 7 passed, 5 skipped | 17s |
| GUI CI-safe (echomind) | `pytest tests/gui/echomind_driven` | 🟢 16 passed | 63s |
| Flaky-parallel (serial) | `pytest tests/code -m flaky_parallel -p no:xdist` | 🔴 **native crash** (exit `0xC0000409`, stack-buffer-overrun) | — |
| Re-sync guard (new + existing) | targeted | 🟢 28 passed (incl. 6 new) | <1s |
| Build lane | — | ⏭️ skipped (per request) | — |
| Live / MCP / server-sync | — | ⏭️ deferred (needs running app + server) | — |

**Bottom line:** the suite is broadly healthy (≈6,300 tests, 99.5% green) but **the merge gate is currently RED**. The 28 failures are **deterministic and cluster into three coherent root causes**, none of them random flakiness. Separately there are real **stability signals** (native crash in one lane, 4 worker crashes, a process leak, an import-order circular import) that deserve attention.

---

## 2. Test inventory & coverage

- **~604 test files / 6,378 test items** under `tests/`, split by *how they execute*:
  - `tests/code/` — pure-Python + offscreen-Qt (CI-safe). The bulk: **viewer (161), system (53), ui_services (53), download_manager (43), echomind (34), cd_burner (23), diagnostics (23), cloud_consultation (21), performance (20), fast_viewer (20)**, plus ~20 more domains.
  - `tests/gui/` — live-driver: `echomind_driven/` (CI-safe, CommandBus), `pywinauto/` (needs running app), `live_walkthroughs/` (agentic KPI extract).
  - `tests/_kpi/` — KPI schema + collector + reporter + baseline.
- **Collection is clean** in the full run: 6,312 collected, 66 marker-deselected, **0 import/collection errors** at `-n auto`.
- **Lane discipline is good:** default `addopts` excludes `build/slow/live/flaky_parallel/property`; a `--timeout=120` prevents hangs; `--reruns 3` absorbs timing flakiness; a **quarantine registry** (`tests/quarantine.py` auto-generated + `quarantine_manual.py`) xfails ~79 known-failing tests so the suite exits 0 by design and any *new* red is a real regression.

**Coverage gaps / stale docs (low severity):**
- `tests/README.md` & `QUICKSTART.md` still say "167 tests" — the suite has grown to ~6,300 items. Docs are stale.
- 5 tests are permanently skipped as **"stale spec"** (reference APIs removed from `clearcanvas_aipacs_kpi_harness` / `main.py` / `mainwindow_ui`): `test_dm_plan_step_cli_payload`, `test_dm_plan_step_gates`, `test_dm_rebuild_latest_session_kpi`, `test_import_warmup`, `test_mainwindow_drag_gate`. These should be updated or deleted.
- 58 real skips this run (VTK GUI-tier native-AV stress ×15; `_validate_report_json not importable` ×12; perf-tier gated behind `AIPACS_PERF_TESTS=1` ×6; specific studies "not present on this machine" — 46630 ×6, 46382 ×3, 44534 ×2; `scipy` missing ×2; socket-env ×3).

---

## 3. Failed scenarios & reproducible bugs

All 28 failures are **deterministic** (they did *not* recover on rerun — distinct from the timing-flaky viewer cluster, which did). They fall into three groups plus one worker crash.

### Bug A — `agent_gateway` config not wired into migration / seed / release  ·  Severity: **HIGH**
The v3.5.4 "Agent Gateway" feature shipped new config files that were never registered in the config-plumbing:

| Test | Failure |
|---|---|
| `runtime/test_config_migration::test_migrate_records_versions_and_is_idempotent` | `KeyError: 'agent_gateway/agent_gateway.json'` |
| `builder/test_release_parity_guards::test_every_config_template_is_seed_reachable` | `config/agent_gateway/devices.json` is neither seed-reachable nor on the exclude list |
| `builder/test_release_parity_guards::test_release_gate_stage_config_parity_against_current_stage` | staged templates ≠ sanitized expectation: `['patient_table_sort.json']` — stage stale |

- **Root cause:** the Agent Gateway module added `config/agent_gateway/agent_gateway.json` and `.../devices.json`, but (a) the config migration version-map doesn't know them, and (b) the release-gate seed/template list doesn't include them. The `patient_table_sort.json` stage mismatch is caused by an **uncommitted local edit** to `config/patient_table_sort.json` (rebuild the stage or commit it).
- **Impact:** a fresh install / migration path can `KeyError` on the new config; release packaging can ship without the Agent Gateway config → the feature is broken on a clean machine.
- **Recommended fix:** register both `agent_gateway/*.json` in the migration version map **and** in `builder/release_gate.py`'s `CONFIG_TEMPLATES` (seed-reachable) or its documented exclude list; rebuild the stage so `patient_table_sort.json` matches.

### Bug B — Portable "Lite Viewer" external drag-drop import is ABSENT (lost/reverted fix)  ·  Severity: **HIGH** (feature) / confirmed
18 tests in `cd_burner/test_lite_viewer_external_drop.py` (+2 in `test_cd_defaults_on_fresh_install.py`) fail with `AttributeError`/`ImportError` for `media_scan.scan_paths`, `media_scan._is_viewer_bundle_dir`, `viewer_app.local_paths_from_mime`, `viewer_app._drop_payload_kind`, `LiteViewerWindow._import_dropped_paths`.

- **Verified against source:** the current `modules/cd_burner/portable_viewer/media_scan.py` exposes `scan_media` / `discover_media_root` / `load_media_info` — **no `scan_paths`**; and `viewer_app.py` still calls `setAcceptDrops(True)  # series drag-and-drop target` accepting **only** the internal `application/x-aipacs-series-index` mime, with **no** external-drop handler. This is *exactly the pre-fix state* the test header documents (the "Roshana CT test CD, 2026-07-12" bug: dropping a file/folder from Explorer onto the viewer did nothing).
- **Conclusion:** the 2026-07-12 fix that added external Explorer drag-and-drop import to the disc/USB portable viewer is **not present in current source** — a lost or reverted fix, **not** a stale test. Media *discovery* (CLI/probe) still works, so a burned CD still opens via auto-discovery; only drag-drop import is gone.
- **Recommended fix:** restore the external-drop implementation (`_import_dropped_paths` on `LiteViewerWindow`, `local_paths_from_mime`/`_drop_payload_kind` in `viewer_app`, `scan_paths`/`_is_viewer_bundle_dir` in `media_scan`) — or, if it was intentionally deferred, mark these guards `xfail` with a tracking note so the gate reflects reality.

### Bug C — ARM64 / x64 dual-build parity markers missing from build scripts  ·  Severity: **MEDIUM** (release infra)
6 tests in `builder/test_nuitka_arm64_parity.py` fail: `build_nuitka.py` lacks `"--arch"`; the Inno Setup `.iss` lacks `#ifdef ARM64_BUILD`, `ResolvedInstallPackageKind()`, `#define InstallPackageKind "x64"`, `#ifdef WOA_EMULATED_BUILD`, and the WOA best-effort helper.

- **Confirmed:** `build_nuitka.py` has essentially no arch handling (1 incidental match for `arch|ARM64|WOA`).
- **Root cause:** the documented **ARM64/x64 dual-build requirement** (PyInstaller + Nuitka on both arches; installer auto-detects) is not implemented in these build/installer scripts. Either not-yet-implemented or lost.
- **Impact:** ARM64 (Windows-on-ARM) builds/installer auto-detection won't be produced; guards correctly block a release that claims dual-build.
- **Recommended fix:** implement `--arch` in `build_nuitka.py` and the `ARM64_BUILD`/`WOA_EMULATED_BUILD`/`InstallPackageKind` conditionals in the `.iss`, per the dual-build requirement doc.

### Error — `builder/test_build_gpu_profile::test_publish_update_bundle_writes_core_and_module_feed`  ·  Severity: **MEDIUM**
Reported as an ERROR, not a failure: **worker `gw12` crashed** during this test's setup (see §4). Needs isolation to see whether the test logic or the crash is at fault.

---

## 4. Stability findings (crashes / freezes / leaks)

| # | Finding | Evidence | Severity |
|---|---|---|---|
| S1 | **Native interpreter crash in the flaky-parallel serial lane** | `pytest -m flaky_parallel -p no:xdist` exited `0xC0000409` (STATUS_STACK_BUFFER_OVERRUN) — the `upload_manager` queue set hard-crashes Python even run serially | **HIGH** |
| S2 | **4 xdist worker crashes** in the fast lane | `[gw2]/[gw5]/[gw11]/[gw12] node down: Not properly terminated`, clustered around the viewer fast-interaction cluster and `test_build_gpu_profile` | HIGH |
| S3 | **Decode-service hard failure under test** | `[B3.11] Decode service hard failure (hard_failure_streak) — restarting pool (1/2)` surfaced mid-run — the app's subprocess decode pool crashed and self-restarted | MEDIUM |
| S4 | **Process leak** | After the fast lane, 2 `.venv` python workers were left orphaned ("not properly terminated") and had to be killed manually — maps directly to the `proc.zombie_after_close` KPI (hard=0) | MEDIUM |
| S5 | **Import-order-dependent circular import** | `viewer/test_series_append_study_distinct.py` fails collection in isolation (`cannot import name 'PatientWidget' … partially initialized`) via `patient_widget → toolbar → ai_chat_interactorstyle → ai_imaging.ai_module_ui.overrides → patient_widget`. Masked at `-n auto` only because another test imports `PatientWidget` first | MEDIUM |

S1/S2/S3 likely share a native root cause (VTK/decode subprocess under headless parallel load). S5 is latent fragility that will bite whenever collection order changes.

---

## 5. KPI results & baseline

A machine-readable baseline is stored at **`tests/_kpi/kpi_baseline_2026-07-23.json`** (compare future runs against it). Highlights:

**Measured this run (test-execution & stability KPIs):**

| KPI | Value |
|---|---|
| Total test items (code lane) | 6,378 |
| Passed / Failed / Errored (fast lane) | 6,145 / 28 / 1 |
| Skipped / xfailed / xpassed | 58 / 79 / 7 |
| Reruns (flaky absorbed) | 85 |
| Fast-lane duration | 565 s (9m 25s) |
| Collection time | 24.6 s |
| xdist worker crashes | 4 |
| Native-crash lanes | 1 (flaky-parallel) |
| Orphaned processes after run | 2 |
| New regressions vs quarantine baseline | **28** |
| Quarantined tests now passing (xpass) | 7 |
| Slowest test | `test_no_silent_drop_violations` — 112 s |

**Runtime app KPIs — NOT captured this run (require the live lane).** The registry (`tests/_kpi/schema.py`) defines thresholds for all of them; the only measured runtime datum available is a **historical** `patient_open.elapsed_ms` ≈ **175–190 ms** (PASS, hard 400) from a prior source-run sink. The following remain **unmeasured** and are carried forward for the live run: application startup / restart-to-ready, search server round-trip, viewer first-render & scroll-fps & stack-rebuild, thumbnail load/leak, first-download-chunk, `GetSeriesImages` socket time, steady RSS & RSS growth/hour, idle CPU %, UI freeze ms/session, native-fault count, zombie-after-close.

> ⚠️ **The prior `tests/_kpi/baseline.json` has `last_known_good: null` for every KPI** — i.e. before today no measured baseline existed at all. `kpi_baseline_2026-07-23.json` is the first populated snapshot; runtime numbers still need a live-lane pass to fill in.

**Slowest tests (perf signal, headless):** `test_no_silent_drop_violations` 112s (source-wide lint), `test_ocr_probe_never_raises` 76s, `test_discover_media_root_prefers_cli_then_probes` 62s, decode-service benchmarks 44/40/34s, disk-pixel-cache benchmark 32s. These dominate wall-clock and are candidates for a `slow` marker or optimization.

---

## 6. The re-synchronisation / study-grows-on-server scenario (your headline concern)

**What I did:** ran the existing sync/grow guards and authored a new dedicated headless regression test.

**New test — `tests/code/storage/test_resync_study_grows_on_server.py` (6 tests, all GREEN).** It drives the *real* disk-vs-server read-model `modules.storage.sync_manifest.evaluate_sync` — the same decision the open-viewer back-fill uses (`_hp_patient_open._enqueue_missing_series_for_open_study`) to "download only missing". It models your exact scenario end-to-end on a temp disk (no server, no DB):

1. Initial study (series 1=3 img, 2=2 img) reads **up-to-date**.
2. Server grows (series 2: 2→4, new series 3=5) → re-sync **detects** series 3 *missing* + series 2 *partial* (`up_to_date=False`). ← the core guard for your bug.
3. After fetching **only** the delta → up-to-date, and series 1 is **untouched** (exact counts, **no duplication/inflation**); a repeat re-sync is idempotent.
4. An interrupted `.dcm.part` write is **never** counted as present (stays missing → re-fetched).
5. A series with pixels but no thumbnail is reported for **thumbnail refresh**.
6. The decision contract keys are pinned so a refactor can't silently drop them.

**Finding:** the **delta computation itself is correct** — `evaluate_sync` properly detects grown/new series and computes only-missing without duplication. So the field symptom ("newly added series not detected/downloaded") is **most likely not a delta-math bug** but the **growth-trigger / re-arm path** and a **release-parity gap**, per existing project memory:
- **OPT-39** (memory, 2026-07-20): a previous-exam series dragged mid-download won't grow until a layout switch, because the grow watchdog is armed only from the awaiting path. Fixed in current source (`AIPACS_PROGRESSIVE_ARMS_WATCHDOG`) but its guard `test_grow_previous_exam_offset_key.py` is **still untracked/uncommitted** in the working tree.
- **Release-parity gap:** the field laptop build **predates OPT-35/36/39**, so the fixes exist in source but not in the installed build. Ship a build carrying OPT-35/36/39 to the field machine.

**Existing sync guards status:** the viewer/download-manager sync family (offset-key, grow, multi-study, batch-growth, pagination-completeness, r17 disk-aware, retroactive-metadata) all **passed inside the full `-n auto` run**. Verified directly: `test_batch_growth` (5), `test_pagination_completeness` (9), `test_r17_disk_aware_completed` (8) all green.

---

## 7. Additional validation checklist (requested)

| Area | Result |
|---|---|
| Old-study downloads | Delta logic sound (new test); field gap is build-parity (OPT-35/36/39 not in installed build) |
| Partial / interrupted downloads | ✅ `.part` files correctly excluded; series stays "missing" (new test S4 case) |
| Duplicate series / instances | ✅ No duplication — counts stay exact across re-sync (new test) |
| Missing thumbnails | ✅ Reported via `missing_thumbnails` (new test) |
| Incorrect image counts | ✅ Disk-first count is source of truth; DB is a hint |
| Stale patient/study metadata | Guarded (`test_retroactive_metadata_sync_fix` etc.) — passing |
| Open tabs not refreshing | Covered by open-back-fill path; live-verify recommended |
| DB ↔ filesystem inconsistency | Guarded; pixel-less-stub enforce mode active (`AIPACS_SYNC_VERIFY_PIXELS=enforce`) |
| Server/local count mismatch | ✅ `partial_series` detection (new test) |
| GUI lag during sync | Not measurable headless — **needs live lane** |
| Freezes under load | S1/S2/S3 crashes are the load-stability signal to chase |

---

## 8. Severity-ranked action list

| Sev | Item | Action |
|---|---|---|
| 🔴 HIGH | **Bug A** agent_gateway config unwired | Register `agent_gateway/*.json` in migration + `release_gate.py`; rebuild stage / commit `patient_table_sort.json` |
| 🔴 HIGH | **Bug B** Lite-Viewer external drag-drop absent | Restore the 2026-07-12 external-drop import, or `xfail` the guards with a tracking issue |
| 🔴 HIGH | **S1** native crash in flaky-parallel lane | Diagnose the `upload_manager` 0xC0000409 (likely thread/global teardown); it is a real product/test bug |
| 🟠 MED | **Bug C** ARM64/x64 build parity | Implement `--arch` + `.iss` ARM64/WOA conditionals per dual-build requirement |
| 🟠 MED | **S2/S3** worker + decode-pool crashes | Isolate `test_build_gpu_profile` + decode-service under headless; add teardown guards |
| 🟠 MED | **S4** process leak after run | Ensure xdist workers / decode subprocesses terminate; ties to `proc.zombie_after_close` KPI |
| 🟠 MED | **S5** import-order circular import | Break the `patient_widget ↔ ai_imaging.overrides` cycle (lazy import) |
| 🟡 LOW | 7 xpass — quarantine now-passing | Run `python tools/dev/build_quarantine.py --check` and prune |
| 🟡 LOW | 5 stale-spec skips + stale README/QUICKSTART | Update or delete |
| 🟡 LOW | Slow tests (112s/76s/…) | Add `slow` marker or optimize |

---

## 9. Tests that should be added / improved

- **Keep the new `test_resync_study_grows_on_server.py`** as the permanent re-sync-grow guard (commit it; it's currently untracked).
- **Commit the untracked OPT-39 guard** `test_grow_previous_exam_offset_key.py` so the previous-exam grow fix is protected in CI.
- **Add a live-lane end-to-end re-sync test** (send study → download → add series on server → resync → assert DB/list/thumbnails/viewer update, no dup) — the piece this headless run can't cover.
- **Add an import-hygiene guard** that imports `test_series_append_study_distinct`'s chain in isolation (would have caught S5).
- **Stabilise, don't quarantine:** burn down the manual flaky list (viewer fast-interaction timing tests) by driving a deterministic clock instead of wall-time; fix the `upload_manager` parallel-unsafe crash at the source.

---

## 10. How to reproduce & compare next time

```powershell
# Fast lane (merge gate)
.\run_test.ps1 -Fast
# Property + serial flaky advisory
.\run_test.ps1
# The new re-sync guard alone
.\.venv\Scripts\python.exe -m pytest tests/code/storage/test_resync_study_grows_on_server.py -v
# KPI reporter
.\.venv\Scripts\python.exe tests\_kpi\reporter.py summary
```

Compare future runs against `tests/_kpi/kpi_baseline_2026-07-23.json` (this run) and re-run the deferred `-m live` lane once the app + PACS server are available to populate the runtime KPIs.

*Artifacts from this run:* `user_data/test_reports/2026-07-23/` (fast.xml/.log, property/gui/sync junit, parse scripts).
