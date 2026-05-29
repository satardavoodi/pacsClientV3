# AI-PACS Application Audit — Stage 8 Report (MPR / Printing / Education / Advanced Analysis)

**Date:** 2026-05-28
**Scope:** Module launchers other than Eagle Eye — MPR, Printing, Education, Advanced Analysis. Audit each one's launch architecture, API stability, scope (per-home vs per-patient-tab), and what's needed before safe CommandBus wiring.
**Method:** Static code inspection + the existing `test_module_catalog_coverage.py` drift report. **Documentation stage — no refactor applied.** Per the plan: *"do not force CommandBus wiring if the module API is not stable."*

---

## 1. Headline numbers — catalog vs CommandBus

`test_module_catalog_coverage.py` reports the live drift between the documented module catalog and the wired CommandBus actions:

```
bus action count: 24

module              cat  wired  missing
advanced_analysis    2     0    export_report, run_analysis
download             1     1
eagle_ai             3     1    explain_finding, show_findings
echomind             3     0    ai_chat, generate_report, generate_summary
homepage             0     0
mpr_zeta             3     1    apply_preset, measure
patient_viewer       1     1
printing             2     0    export_pdf, print_series

Coverage: 4 / 15 catalog actions wired (27 %)
```

**These 11 unwired catalog actions are the work surface of Phase D.3** (per-tab module launchers). Stage 8 documents what each one needs.

---

## 2. Per-module audit

### 2.1 Eagle Eye — already wired

| Attribute | Value |
|---|---|
| Catalog file | `modules/EchoMind/secretary/catalog/modules/eagle_ai.md` (3 actions) |
| Production entry point | `_launcher_eagle_ai_from_home(entities)` in `PacsClient/pacs/workstation_ui/home_ui/home_panel/widget.py:249` |
| Scope | Per-home (singleton service tab) |
| API shape | Clean callable, takes `entities: dict`, no Qt widget args |
| Adapter wiring | **DONE** — registered via `build_command_bus(module_launchers={"eagle_ai": ...})` |
| Test coverage | `test_factory_wires_modules_when_launchers_passed`, structural Eagle Eye crash guards (Stage 7) |
| Remaining catalog gap | `explain_finding`, `show_findings` — these are downstream features inside Eagle Eye, not launchers; they require Eagle Eye to expose a callable API for findings inspection |

**Verdict:** Reference implementation. The pattern other modules can follow.

---

### 2.2 Education — easy adapter win (one-liner remaining)

| Attribute | Value |
|---|---|
| Catalog file | (no dedicated `education.md` — referenced indirectly) |
| Production entry point | `open_education_module()` in `PacsClient/pacs/workstation_ui/home_ui/home_panel/_hp_modules.py:77` |
| Scope | Per-home (singleton service tab; uses `activate_or_create_module_tab` pattern with `tab_flag_key='is_education_tab'`) |
| API shape | **Clean parameter-less callable on the HomeWidget.** Returns nothing; opens a tab. |
| Adapter wiring | **NOT WIRED.** The ModuleAdapter has an `open_education` action stub that returns `module_not_registered`. |
| Test coverage | The `_hp_modules.py` mixin has no dedicated unit test, but the launcher is exercised by manual GUI use today. |
| Refactor needed | **One line** — add `"education": self.open_education_module` to the `module_launchers={...}` dict in `widget.py:241`. No API change required. |

**Verdict:** Adapter-ready. Wire-up is trivially safe; deferred only by Phase D.3 scope discipline.

---

### 2.3 Printing — easy adapter win with one caveat

| Attribute | Value |
|---|---|
| Catalog file | `modules/EchoMind/secretary/catalog/modules/printing.md` (2 actions: `export_pdf`, `print_series`) |
| Production entry point | `open_printing_module()` in `_hp_modules.py:97` |
| Scope | Per-home (singleton service tab) but **requires patient selection from the home table** (collects `get_selected_patient_data_list()` before launching) |
| API shape | Clean parameter-less callable, but with a **state dependency**: needs at least one patient checked in the home table. Currently shows `QMessageBox.warning(..., "Please select at least one patient in the list.")` when called with no selection. |
| Adapter wiring | **NOT WIRED.** `ModuleAdapter.open_printing` returns `module_not_registered`. |
| Test coverage | None dedicated. |
| Refactor needed | **One line** to wire (`"printing": self.open_printing_module`) **plus** a decision: should the bus path pass explicit `patient_ids` via `entities`, or should it require pre-selection like the toolbar path does? The catalog's `print_series` action implies the former (action carries the data) — that means a small adapter-side widening of the call: `open_printing_module(selected_ids=entities.get("patient_ids"))`. |

**Verdict:** Adapter-ready with a 1–2 hour patch. The current launcher works as a fallback (no `patient_ids` provided → use home selection); the bus path can pass the IDs explicitly.

---

### 2.4 MPR — NOT adapter-ready; toolbar refactor required first

| Attribute | Value |
|---|---|
| Catalog file | `modules/EchoMind/secretary/catalog/modules/mpr_zeta.md` (3 actions: `open_mpr`, `apply_preset`, `measure`) |
| Production entry point | `_show_mpr_dropdown(button)` in `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py:3069`, invoked from a button click at line 7308 |
| Scope | **Per-patient-tab** — each viewer has its own toolbar with its own MPR button |
| API shape | **Requires a Qt `button` widget argument** (to position the dropdown menu next to the button). Not a clean callable. |
| Adapter wiring | `ModuleAdapter.open_mpr` exists but returns `module_not_registered` because no production launcher matches its signature. |
| Test coverage | None dedicated for MPR launch. |
| Refactor needed | **MEDIUM:** extract the launch logic out of `_show_mpr_dropdown(button)` into a button-less `launch_mpr_for_active_series()` method on the patient tab. The dropdown can be a separate UI concern; the headless launch needs to: (a) read the active series, (b) construct the MPR widget/window, (c) wire it into the per-tab subwindow area. This is non-trivial because the current implementation is intertwined with the button's geometry. |

**Verdict:** Documented gap. Per the plan: *"If launcher wiring requires refactoring toolbar methods such as `_show_mpr_dropdown(button)`, document the gap rather than doing a rushed fix."* — exactly this case. Phase D.3 territory.

---

### 2.5 Advanced Analysis — per-tab callable, adapter pattern available

| Attribute | Value |
|---|---|
| Catalog file | `modules/EchoMind/secretary/catalog/modules/advanced_analysis.md` (2 actions: `export_report`, `run_analysis`) |
| Production entry point | `launch_advanced_analysis_for_active_series() -> bool` in `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_advanced.py:23` (mixin on the patient widget) |
| Scope | **Per-patient-tab** — each patient tab can launch its own Advanced Analysis on its active series |
| API shape | **Clean parameter-less callable, returns bool**, lives on the patient widget |
| Adapter wiring | Not wired. The ViewerAdapter is currently read-only; an `AdvancedAnalysisAdapter` would need the same per-tab handle pattern (`get_active_patient_tab`) the ViewerAdapter uses. |
| Test coverage | None for the adapter; the underlying `_pw_advanced.py` has a comment about a `QMessageBox` error path that hides exceptions today. |
| Refactor needed | **SMALL:** add an `AdvancedAnalysisAdapter` mirroring `ViewerAdapter`'s read-only structure; thread it through `bus_factory` with `get_active_patient_tab`. Same constructor pattern as ViewerAdapter. The action `run_analysis` maps directly to `launch_advanced_analysis_for_active_series()`. The `export_report` action needs a callable that doesn't yet exist — that's a deeper module change. |

**Verdict:** Adapter-friendly in shape but per-tab scope means it needs the ViewerAdapter-style construction helper. Phase D.3, but easier than MPR.

---

### 2.6 Web Browser (bonus — out of plan but discovered)

| Attribute | Value |
|---|---|
| Production entry point | `open_web_browser()` in `_hp_modules.py:58` |
| Scope | Per-home (singleton) |
| API shape | Clean parameter-less callable |
| Adapter wiring | Not wired. No catalog file. |
| Refactor needed | Add to launchers dict if/when a user-facing intent ("open the browser") is desired. Otherwise leave alone. |

---

## 3. Summary table

| Module | Production scope | API shape | Adapter wiring | Refactor effort |
|---|---|---|---|---|
| **Eagle Eye** | per-home | clean | **wired** | — |
| **Education** | per-home | clean | not wired | trivial (1 line) |
| **Printing** | per-home | clean (state-dep) | not wired | small (1–2 hours: decide on `entities.patient_ids` shape) |
| **Advanced Analysis** | per-patient-tab | clean | not wired | small–medium (mirror ViewerAdapter construction) |
| **MPR** | per-patient-tab | needs Qt button | not wired | **medium** (extract launcher from `_show_mpr_dropdown(button)`) |
| Web Browser | per-home | clean | not wired | trivial (1 line) — if desired |

---

## 4. Concrete refactor recommendations (NOT applied in this stage)

These are documented for the future Phase D.3 PR; the plan is explicit that Stage 8 does NOT apply them.

1. **Add Education + Web Browser to `module_launchers` dict** (widget.py:241) — 2 lines, no API change. Wires `open_education` and a new `open_browser` action to existing clean callables. Effort: 5 minutes.

2. **Add Printing to `module_launchers` dict** + tighten the action contract — decide whether `entities.patient_ids` overrides the home selection or supplements it. The cleanest path: adapter call passes `patient_ids` via `entities`; `open_printing_module()` gets a new optional `selected_ids=None` parameter that falls back to current behavior. Effort: 30 minutes + a test.

3. **Build `AdvancedAnalysisAdapter` mirroring `ViewerAdapter`** — same construction helper (`get_active_patient_tab`), wraps `launch_advanced_analysis_for_active_series()` and the existing per-tab handles. Effort: 1–2 hours + 5–8 unit tests (same shape as `test_viewer_adapter.py`).

4. **Refactor `_show_mpr_dropdown(button)`** into a `launch_mpr_for_active_series()` method (button-less) + a thin `_show_mpr_dropdown(button)` shim that just sets up the dropdown geometry and calls the new method. Effort: 4–6 hours + tests. **Highest-risk of the four** because MPR initialization is intertwined with VTK setup; needs care to not break the per-tab subwindow plumbing.

---

## 5. Tests run

- `tests/code/echomind/test_module_adapter.py` — **7 / 7 PASS**
- `tests/code/echomind/test_bus_factory.py` — **5 / 5 PASS**
- `tests/code/echomind/test_module_catalog_coverage.py` — **2 / 2 PASS** (the drift soft-warning is informational, not failing — and that's exactly the design)
- Total runnable sandbox surface still **106 / 0** from Stage 2.

---

## 6. Fixes applied

**None.** This was a pure documentation stage per the plan.

---

## 7. KPI / dashboard impact

- KPI schema unchanged (42 keys, baseline in sync).
- Regression catalog unchanged at 34 rows.
- `Coverage: 4 / 15 catalog actions wired (27 %)` — the catalog-coverage report keeps this number visible per run, so any future PR that wires Education, Printing, or Advanced Analysis can be measured directly.

---

## 8. Remaining risks

1. **The 27 % wire-up coverage means most catalog-documented user intents (`run_analysis`, `print_series`, `apply_preset`, `measure`, `ai_chat`, etc.) cannot be invoked via the bus today.** Voice/agent/test paths will get `module_not_registered`. This is expected — Phase D.3 work — but should be documented in the testing QUICKSTART so contributors know what isn't yet bus-driveable.

2. **MPR's refactor risk is non-trivial.** Touching toolbar code can ripple into series-switch behavior; `MULTI_STUDY_SINGLE_TAB_PLAN.md` invariants must be respected. Any MPR-extraction PR should add multi-study regression tests before landing.

3. **The catalog drift soft-warning could promote to a hard rule once Phase D.3 wires the four obvious ones** — currently the test reports drift but doesn't fail; that's the right design for now.

---

## 9. Verdict

**STRONG PASS as a documentation stage.** The module-launcher landscape is now clearly mapped:

- **Wired today:** Eagle Eye.
- **Wireable tomorrow (1-day PR):** Education, Web Browser, Printing.
- **Wireable with a per-tab adapter (1-week PR):** Advanced Analysis.
- **Wireable after toolbar refactor (multi-week PR):** MPR.

The plan's "documented gap" outcome is achieved — no rushed wire-ups, no broken invariants, every module has a defined next step.

**Recommended next stage:**
- **Stage 9 — Layout and responsive UI audit.** Three known gaps already documented: the `QScrollArea.setHorizontalScrollMode` regression (Stage 1 finding, task #90), the `SARKHOSHI ABOLFAZL` `ABDOMEN, ABDOMENPEL...` body-part elision (Stage 6 finding), and any chip-overlap / Settings-overflow / Light Viewer issues the user has flagged. Stage 9 is the right home for fixing them with proper Qt-native primitives (`QScrollArea`, `setMinimum*`, `QFontMetrics.elidedText()`, etc.).
