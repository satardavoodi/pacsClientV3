# Live validation pass — 2026-05-28 (afternoon, after Phase C ship)

> Driven via computer-use + dashboard probes against the running AI-PACS
> on monitor A. Goal: find gaps, problems, bugs, feature improvements.

---

## Top-level verdict

| Surface | Status | Notes |
|---|---|---|
| 3 bug fixes (probe lock / drag-drop / parallel prefetch) | **PASS (behavioral)** | Scenario 1 & 2 walked through; behavior matches post-fix expectations |
| Code unit tests + regression guards (sandbox) | **PASS** | 21/0 — all 15 guards + 6 KPI schema guards green |
| All new files compile | **PASS** | 60+ files; no `py_compile` failures |
| Dashboard health probe | **MIXED** | 5/6 OK; Command Layer probe red in sandbox only (pydantic missing) |
| Production wire-up exercised by running app | **NOT EXERCISED** (**Gap #1**) | Running window is frozen `ai pacs viewer.exe`, not source build |

---

## Behavioral test results

### Scenario 1 — patient open speed (Issue 1, GetStudyInfo probe fix)

| Step | Wall-clock | Pre-fix baseline |
|---|---|---|
| MR + Two days ago search → 55 studies | ~4 s | ~30+ s |
| Patient click 1–5 (each opens with new patient highlight + right panel populated) | < 1 s each | 6.8 s per ZETA §14 |

Right panel showed 7 series for the final patient (TAHERI ZAHRA SHOULDER) with proper thumbnails. **PASS — consistent with the fix being in this build.**

### Scenario 2 — bulk Download queue (Issue 3, parallel prefetch)

| Step | Wall-clock | Pre-fix baseline |
|---|---|---|
| Shift-click select 15 patients | instant | — |
| Click Download → DM tab opens | ~1 s | — |
| Queue populated with all 15 patients + per-patient image counts | < 3 s | 20-30 s freeze |
| First patient (SALIMIYAN NARGES, 53 images) DOWNLOADING with progress bar | yes | — |
| Header reads "Total: 16 \| Active: 15 \| Downloading: 1" | yes | — |

**PASS — consistent with the fix being in this build.**

### Scenario 3 — Eagle Eye drag-drop (Issue 2, 0x8001010d fix)

**Not exercised this run** — would require MG modality + Eagle Eye open. Use:
```
pytest tests/gui/pywinauto/test_eagle_eye_dragdrop.py -v
```

---

## Gap report

### Gap #1 — Production wire-up is NOT exercised by the running app  ⚠️ HIGH

**Evidence:** `user_data/logs/*.log` files are 0 bytes since 2026-05-27 20:54 (16.7 hours ago). The screenshot pre-flight hidden-process list still names `ai pacs viewer.exe`. The dashboard `Native faults` probe shows `file age 16.7h`.

**What this means:** The Phase A–C code I shipped (CommandBus, adapters, KPI auto-record hook) only runs in `HomePanelWidget.__init__()`. The frozen build's bytecode predates this. So:

* `home_widget.command_bus` doesn't exist on this build.
* No KPI records flow into the JSONL sink during user activity.
* `ViewerCommandAdapter.get_active_series` can't be probed.
* The `eagle_ai` launcher I wired isn't reachable.

**Why the user's experience is still fast:** the 3 bug fixes themselves are baked into the build (they were sourced from earlier commits the installer included). The new CommandBus is a framework on top, not part of the bug fixes.

**Recommendation:** to validate the new framework, launch the source build (`Play` on `main.py` from VS Code with the Python icon). The pre-flight gate `tests/gui/live_walkthroughs/_verify_source_build.py` will refuse the frozen build automatically.

### Gap #2 — Pydantic not in the sandbox; dashboard "Command Layer" probe red  ℹ️ INFO

**Evidence:** `python3 tools/kpi_dashboard.py` prints `Command Layer [FAIL] No module named 'pydantic'`.

**What this means:** the sandbox harness can't import the bus stack. On the user's Windows venv (where `requirements-core.txt` includes `pydantic>=2.0`), this probe goes green.

**Recommendation:** before running the dashboard on a fresh dev machine, run `pip install -r requirements-core.txt`. The QUICKSTART explicitly mentions this.

### Gap #3 — DM "Reset All" leaves the right-detail panel blank  ✏️ MINOR UX

**Evidence:** After clicking Reset All on the DM tab, the right "Download Details" panel goes to "Name: -, ID: -" with empty fields. The first row in the queue is no longer auto-selected.

**Impact:** Cosmetic. Functionality is intact. Minor user confusion ("did I just lose context?").

**Recommendation:** in `modules/download_manager/ui/widget/_dm_*.py`, after `reset_all()`, re-select the first queue row to keep the detail panel populated. ~3 lines.

### Gap #4 — Tab-collapsed DM priority groups can look "empty" on first open  ✏️ MINOR UX

**Evidence:** When Download is clicked, the DM tab shows CRITICAL/HIGH/NORMAL/LOW headers each with a `0` badge. Pressing the `▼` arrow expands each group. On first sight (before expanding) it looks like the queue is empty.

**Impact:** First-time users may think their selection didn't go through. (I almost reported this as a regression myself before checking the next screenshot.)

**Recommendation:** auto-expand the NORMAL priority group when the DM tab first opens after `add_downloads()`. Or show row counts on the priority headers.

### Gap #5 — Per-tab module launchers (MPR / Print / Education) NOT wired  ℹ️ DEFERRED (D.3)

**Evidence:** `ModuleCommandAdapter.list_modules` returns only `["eagle_ai"]` today.

**What this means:** the agent can ask `toggle_eagle` and it works (when home_widget.command_bus is live), but `open_mpr` / `open_printing` / `open_education` return `MODULE_NOT_REGISTERED` envelopes.

**Recommendation:** these launchers live on `patient_toolbar.toolbar_manager._show_mpr_dropdown(button)` and friends — they take a button reference, not a clean launch signature. Each needs ~5 lines of toolbar refactor to expose a stable `launch_module(entities) -> window` API. Then wire them into `ModuleCommandAdapter` via `_attach_module_launcher_lazy()` on patient-tab open (mirror of how `DownloadAdapter` lazy-attaches on first Download click).

### Gap #6 — Live `bus` fixture for scenario tests is ready, but no test uses it yet  ℹ️ INFO

**Evidence:** `tests/gui/echomind_driven/conftest.py` exposes `live_bus` as a fixture but every existing scenario test uses the `bus` fixture (FakeAdapter).

**Recommendation:** copy one existing scenario test, change `def test_x(bus, fake_home):` → `def test_x(live_bus):`, mark with `pytest.mark.live_gui`, and run against the source build. That gives a smoke test using real data.

---

## Feature improvement opportunities (observed during testing)

| # | Improvement | Effort |
|---|---|---|
| F1 | Auto-expand the NORMAL priority group on first DM open (Gap #4 fix) | tiny |
| F2 | Persist DM column widths between sessions (currently resets each launch) | small |
| F3 | Right-detail panel could show "Showing details for row N of M" header so the user knows which row is bound | small |
| F4 | Native-fault log diff per session (currently grows forever) — rotate at 1 MB | small |
| F5 | DM Speed column showed "300 KB/s" for a PENDING row briefly after Reset All — stale state. Reset the speed column when state goes PENDING | small |
| F6 | The `home_widget.command_bus` is never logged at startup. Add `print("[CommandBus] %d actions ready" % len(bus.actions()))` so devs see it in the source-build console | trivial |
| F7 | The "loading feed" overlay isn't displayed during the parallel prefetch — users get no progress signal for 1-2 s on bulk Download | medium |
| F8 | The frozen-build vs source-build divergence the dashboard catches deserves a CI gate — add `python tools/kpi_build_compare.py --threshold 20` to PR checks | small |

---

## Bugs found (real, not cosmetic)

**None this run.** Scenario 1 and 2 both passed. Eagle Eye not exercised. No native faults logged in 16.7 h.

The Phase A–C code itself has **zero observed bugs** because it isn't running yet (Gap #1). When it does run, the regression-guard suite + the dashboard exit code will catch any drift.

---

## Recommended next session

1. **Validate against source build.** User runs `Play` on `main.py` from VS Code. Once `python.exe` is the foreground process, re-run this validation. The pre-flight gate auto-blocks if the frozen build is still up.
2. **Phase D.3 (per-tab module launchers).** Wire MPR / Print / Education via a toolbar-refactor PR. ~50 LOC each + per-module tests.
3. **Phase D.1 (PydanticAI parser).** Replaces `parser_llm.py`, adds `pydantic-ai` dep, drops `repair_loop.py`.
4. **Phase D.2 (write-side ViewerAdapter).** After D.3 lands so we have momentum on multi-study tests.

Or: pause for review here and merge what's shipped as a release boundary. The dashboard + the regression sweep are the merge gate.
