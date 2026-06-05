# MCP/Test Structure vs Real Application Workflow — Fidelity Audit (2026-06-04)

**Question:** does the new testing structure (Test Control Server + `aipacs-control` MCP +
test files) behave like the real, live software workflow — or does it bypass logic that real
users exercise? Evidence: code-path tracing done while building the framework, plus the two
live storm runs (12:41, 12:57) cross-checked against logs of real mouse-driven sessions
(01:15 stress test, 10:39 manual repro).

**Verdict in one line:** the bus commands call the *same production functions* the GUI
handlers call (verified per path below); the deliberate, documented gap is the **input layer**
(Qt mouse events, debounce timers, OLE drag loop), which is exactly where tiering (T2/T3)
must stay in the plan — plus four concrete divergences to correct, listed in §4.

---

## 1. Path-by-path alignment

| Real user action | Real code path | MCP action | Same path? | Gaps |
|---|---|---|---|---|
| **Double-click patient** | QTabBar row press×2 → `patient_table_widget._on_patient_double_clicked` → cancels pending single-click (debounce) → home `_on_patient_double_clicked(pid, name, uid, report_status)` → async open, tab creation, STEP 3.5 download enqueue | `open_patient` → home `_on_patient_double_clicked(...)` directly | **YES from the home handler down** — live-verified identical: `open_request → tab_created → FAST-SERIES-DOWNLOAD-QUEUE priority=High → dm_started=True`, same as mouse runs | Skips the table-widget click/debounce layer (where BUG-3 lives); passes `report_status="pending"` and **empty patient_name** (real rows carry both → "N/A" tab titles) |
| **Single-click patient → thumbnails** | debounced `patientClicked`+`thumbnailRequested` → `_on_patient_single_clicked` → `_mark_active_patient_selection` → reconcile + `show_patient_studies` fast-cache gate → right panel | **NO COMMAND EXISTS** | **— (missing)** | The 44113 fast-cache gate, reconcile persistence, and right-panel race surface are untested by the bus. Biggest single fidelity hole. |
| **Drag series → viewport** | thumbnail `mouseMoveEvent` → `dragStarted` + setChecked → `QDrag.exec` (OLE loop, protected latch) → viewport `dropEvent` (payload/dwell checks, spinner, `_pending_action_id` stamp) → `QTimer(0)` → `method_change_series_on_viewer(series_index, flag_change_selected_widget=False, vtk_widget, slider)` | `change_series` → spinner → `method_change_series_on_viewer(...)` with the **same argument shape** | **YES from the drop handoff down** — storm: drops → expected first-load FAILs → awaiting → progressive display, byte-identical log signature to mouse drops | Skips OLE (intentional — T3/pywinauto only), dropEvent payload/dwell, the thumbnail `setChecked`/`dragStarted`, and the `_pending_action_id` stamp (KPI correlation differs) |
| **Download starts on open** | STEP 3.5 `add_study_downloads(start_immediately=True)` unless local | identical (runs inside the same open) | **YES** (run-1 “no downloads” was a false alarm — queue had drained) | none |
| **Drag-of-undownloaded escalates priority** | drop → load fails → `_trigger_download_if_needed` → intent coordinator CRITICAL → preempt | identical via `change_series` | **YES** (INTENT_PRIORITY/preemption observed in both modes) | none |
| **Search** | filters → Search button → `set_search_data` + modality checkboxes + `patient_list_function_identifier(src)` | `list_patients` → `HomeWidgetAdapter.search()` → **the same calls**, incl. `_set_modalities` | **YES** (real server socket search; 18 CT/39 DX live) | adapter also *waits* on `_search_task` pumping `processEvents` — slightly more synchronous than a user click (acceptable; documented) |
| **Tab switch** | tab header click → QTabBar → `setCurrentIndex` → `currentChanged` → `on_tab_activated` (resync) | `switch_tab` → `setCurrentIndex` | **YES at signal level** | skips QTabBar mouse handling (no known logic there) |
| **Tab close** | X button → `tabCloseRequested` → `close_tab` teardown | `close_patient_tab` → `tabCloseRequested.emit(idx)` | **YES** (same signal, full teardown ran live) | none |
| **MPR open** | toolbar button → `toolbar_manager.toggle_zeta_mpr` | `open_mpr` → module launcher → same route | **YES** | toggle-close semantics not modelled as a distinct command |
| **Viewer interaction (stack drag, wheel, W/L)** | Qt mouse/wheel events in viewport | **no commands** | — | T2 territory (posted QMouseEvent/QWheelEvent), not yet built — by design (P3) |
| **App start/login/dialogs** | user clicks OK + Sign In | lifecycle tools via UIA `.invoke()` on the **real buttons** | **YES** (Invoke pattern = the accessibility path, same slots fire) | no synthetic typing of credentials when prefilled (matches real saved-login use) |

**Intentional, documented deviations (keep, don't "fix"):** (a) commands queue one-per-event-
loop-turn — a pressure model, *more* hostile than human input pacing, never less; (b) no OS
cursor → hover states/tooltips unexercised; (c) OLE/native drag exclusively via the pywinauto
tier (`tests/gui/pywinauto/test_eagle_eye_dragdrop.py`) — the storm's one non-fatal
`0x8001010d` proves the COM surface also exists *outside* OLE, so T3 must keep running.

## 2. Where the framework already caught real divergence (evidence it works)

Building the bridge exposed **five latent command-layer bugs** where the "automation path"
silently differed from production: (1) `open_patient` arg dispatch could never call the live
adapter (missing `study_uid`); (2) `list_patients` never returned rows (no `read_patient_rows`);
(3) DownloadAdapter attached only from the download-button path → `download.*` dead after
open-created DMs; (4) `get_thumbnails_data` is study-level — unusable for series work;
(5) viewer write surface absent. 1–4 fixed, 5 added test-gated. Each was invisible to the
existing test suites because **fakes had drifted from the live adapters** — the central
test-hygiene lesson of this audit.

## 3. Test-file audit (outdated / artificial)

| Item | Problem | Action |
|---|---|---|
| `tests/gui/echomind_driven/conftest.py` fakes (`FakeHomeAdapter` etc.) | Signatures drifted from live adapters — hid bugs §2.1/§2.2 (fake `open_patient` takes 1-2 args; live takes 4) | **Add a contract test**: `inspect.signature` of every fake method must match the live adapter method; run in CI |
| `tests/code/viewer/test_b34_interaction_aware_policy.py` | 21/36 failing — specs drifted from evolved settle/prefetch code (pre-existing, re-verified 2026-06-04) | Update specs to as-built behaviour or split into `xfail(reason="spec drift, tracked")`; currently noise that masks real regressions |
| `tests/code/download_manager` (~21 failures) | Specs for **deferred ZETA drag-hardening features that were never built** — validating behaviour that doesn't exist in production | Mark `xfail(reason="P2.x deferred feature")` so red = real |
| `tests/code/viewer/test_overlap_pixel_quality_drag.py` | imports `tests.viewer` (module gone) — breaks collection of the whole folder | Fix import or quarantine; it currently blocks `tests/code/viewer` as a unit |
| `tests/gui/pywinauto/run_patient_open_smoke.py` | Clicks 5 rows ~3 s apart — *politer than real users*; predates the impatient-user findings | Keep as smoke; rely on bus storms for pressure (already the case) |
| Diagnostics harness scenarios (s01–s11) | Inject signals *below* the input/debounce layer | Fine for state-machine coverage; do not count them as workflow coverage (document) |
| `tests/code/echomind/*` (77 pass) | Healthy, now includes the test-server suite | Extend with: open_patient **live-arg** shape test (regression for §2.1), `read_patient_rows` contract |

## 4. Corrections required (prioritized)

1. **Add `select_patient` (single-click) command** → `_on_patient_single_clicked(pid, name, uid)`
   — closes the biggest hole (thumbnail fast-cache gate, reconcile, right-panel races; the
   BUG-3 surface at T1 level). Small: one method on the write adapter.
2. **Carry real row data into opens**: extend the `_server_patient_meta_by_pid` stash with
   `patient_name` + `report_status` and make `read_patient_rows` expose them; the MCP then
   opens with production-identical arguments (kills the "N/A" tab divergence).
3. **Stamp `_pending_action_id` in `change_series`** exactly as `dropEvent` does — restores
   KPI/log correlation parity between bus drops and mouse drops.
4. **Fake↔live adapter contract test** (§3 row 1) — prevents the entire class of silent drift
   that produced bugs §2.1–2.4.
5. **T2 input tier (posted `QMouseEvent`/`QDropEvent`/`QWheelEvent`)** — the planned P3; the
   only way the debounce window, drop dwell, and wheel/stack interaction get automated
   coverage without OS mouse.
6. **Keep the T3 OLE lap in every nightly** — the storm proved COM faults occur even without
   OLE; OLE remains its own regression surface.
7. Test-suite hygiene: the two `xfail` conversions + the broken-import quarantine (§3) so a
   red suite means a real regression again.

## 5. Bottom line

The MCP layer is **not a parallel implementation** — every write command terminates in the
same production function its GUI counterpart reaches, verified live by identical log
signatures for open/enqueue/drop/escalate/close. What it bypasses is precisely catalogued
(input layer + OLE) and assigned to tiers that exist (T3) or are scheduled (T2). The riskiest
fidelity threat found was not in the MCP at all but in the **fakes drifting from live
adapters** — addressed by the contract-test recommendation. With corrections 1–4 (≈half a
day) the bus tier becomes argument-for-argument identical to real user actions from the
handler level down.
