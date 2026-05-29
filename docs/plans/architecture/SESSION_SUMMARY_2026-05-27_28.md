# Session summary — 2026-05-27 / 2026-05-28

> One-page snapshot for reviewers. **What landed, how to validate, what's deferred.**
> Open `docs/plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md` for the
> design rationale and `TESTING_ARCHITECTURE_2026-05-28.md` for the testing
> strategy. This doc is the *index*; the others are the *book*.

---

## 1. The three bug fixes (production-critical, regression-guarded)

| # | Bug | Fix | Guard | Status |
|---|---|---|---|---|
| 1 | Download starts slowly after patient open (recurring) | `_hp_study_save.py`: `_GETSTUDYINFO_PROBE_LOCK` + raw `send_request("GetStudyInfo")` instead of 2-attempt helper | `tests/code/system/test_2026_05_27_regression_guards.py::test_probe_*` | ✅ in production |
| 2 | Eagle Eye drag-drop crash (`0x8001010d`) | `modules/ai_imaging/.../patient_widget.py`: MG mirror deferred via `QTimer.singleShot(0)` | `test_mg_mirror_is_deferred_via_qtimer` + `tests/gui/pywinauto/test_eagle_eye_dragdrop.py` | ✅ in production |
| 3 | Bulk Download queue freeze (20-30 s for 20+ patients) | `_hp_download.py`: `ThreadPoolExecutor` parallel pre-fetch + `QApplication.processEvents` | `test_prefetch_uses_threadpool_executor` + `test_prefetch_has_no_sequential_loop` | ✅ in production |

All 15 regression guards from 2026-05-27 still pass after every subsequent change.

---

## 2. The unified Command Layer (in production via home_widget.command_bus)

```
chat orb  voice STT  AI agent  GUI tests   ←  4 callers, one entry
        \    |    /    /
        CommandBus.dispatch / execute        ←  modules/EchoMind/secretary/
              │
        AdapterRegistry                       ←  ~22 actions reachable today
        ┌────┼─────────┬──────────┬─────────┐
        ▼    ▼         ▼          ▼         ▼
     home  system   viewer     download   modules
     (3)   (4)      (5 r-o)    (6, lazy)  (eagle_ai)
```

Wired in `PacsClient/.../home_panel/widget.py` at the end of `HomePanelWidget.__init__()`. Fail-safe try/except — any error leaves `self.command_bus = None` and existing call sites are untouched. **No clinical workflow was modified.**

| Adapter | File | Actions | Risk |
|---|---|---|---|
| HomeCommandAdapter | `adapters/home_command_adapter.py` (184) | 3 | low |
| SystemCommandAdapter | `adapters/system_command_adapter.py` (246) | 4 | none — psutil only |
| ViewerCommandAdapter | `adapters/viewer_command_adapter.py` (285) | 5 | **structurally read-only** — cannot trip MULTI_STUDY guards |
| DownloadCommandAdapter | `adapters/download_command_adapter.py` (219) | 6 | low — wraps DM widget's existing public methods |
| ModuleCommandAdapter | `adapters/module_command_adapter.py` (149) | 6 (catalog) | low — launcher pattern, fail-safe |
| `bus_factory.py` (140) | One-stop wiring | — | additive only |

---

## 3. Testing framework

### Layered pyramid

```
tests/
├── code/                            178 headless tests (CI-safe, fast)
│   ├── system/                      regression-guard catalog (16 specs)
│   └── echomind/                    11 unit tests for the bus + adapters
├── gui/
│   ├── echomind_driven/              7 scenario tests (FakeAdapter; CI-safe)
│   ├── pywinauto/                    4 OS-level smoke tests
│   └── live_walkthroughs/            pre-flight + log KPI extractor
└── _kpi/                            42 KPI keys + collector + reporter
```

| Driver | Purpose | Count |
|---|---|---|
| pytest (`tests/code/`) | Pure-Python + headless-Qt | 178 |
| CommandBus (`tests/gui/echomind_driven/`) | In-process scenarios | 7 |
| pywinauto (`tests/gui/pywinauto/`) | OS-level (drag-drop, paint, modal, zombie) | 4 |
| computer-use MCP | Ad-hoc agentic walkthroughs | as needed |

### KPI machinery

* **42 registered keys** in `tests/_kpi/schema.py` covering patient_open, bulk_download, viewer, thumbnail, mpr, search, db, socket, process, ui, crash, recovery, session
* **`KpiCollector.hook_bus(bus)`** auto-records `<action>.elapsed_ms` for every `bus.execute()`
* **JSONL sink** at `user_data/test_kpis/<run_id>.jsonl`
* **Reporter CLI** at `tests/_kpi/reporter.py` (`last`, `trend`, `summary`, `diff`)
* **HTML trend report** at `tools/kpi_html_report.py` (self-contained, no JS deps)
* **Cross-build comparison** at `tools/kpi_build_compare.py` (catches source-vs-frozen divergence)
* **Dashboard** at `tools/kpi_dashboard.py` (one-stop framework health, exit 0/1/2)

---

## 4. Regression catalog — 29 indexed guards across 5 days

`docs/plans/architecture/REGRESSION_CATALOG.md` indexes every protective test by date + module + bug summary. Every bug fixed since 2026-05-24 is in there. **Adding a row is the bookkeeping requirement when a fix lands.**

---

## 5. How to validate this work in 60 seconds

```bash
# 1. Headless test suite + dashboard health snapshot
bash tests/run_code_tests.sh

# 2. Bus-driven scenarios (CI-safe; uses FakeAdapter)
pytest tests/gui/echomind_driven/ -v

# 3. Dashboard alone (no tests, just status)
python tools/kpi_dashboard.py

# 4. On a live source build (pywinauto OS-level):
pytest tests/gui/pywinauto/test_eagle_eye_dragdrop.py -v    # canonical drag-drop COM
pytest tests/gui/pywinauto/test_close_no_zombie.py -v        # zombie process guard
AIPACS_CYCLE_LAUNCH_CMD="python main.py" pytest tests/gui/pywinauto/test_open_close_cycles.py -s

# 5. Live-bus scenario test (auto-skips if source build not running):
pytest tests/gui/echomind_driven/ -v -k live_bus
```

The runner ends with the dashboard's pass/warn/fail verdict — that's the merge gate.

---

## 6. What's still deferred (each is its own focused PR)

| Item | Why deferred | Risk |
|---|---|---|
| **D.1 PydanticAI parser** | Replaces `parser_llm.py`; adds `pydantic-ai` dep; drops `repair_loop.py`. Wanted Phases 1–C green and shipped first so there's a rollback target. | Medium — parser is on every chat command |
| **D.2 Write-side ViewerAdapter** | `change_series`, `set_layout`, `scroll`, `set_window_level`. Each needs its own multi-study test exercising both single- and multi-study patients per `MULTI_STUDY_SINGLE_TAB_PLAN.md`. | High — touches most-guarded code |
| **D.3 Per-tab module launchers (MPR / Print / Education)** | These live on per-patient-tab toolbars (`toolbar_manager._show_mpr_dropdown(button)`). The launcher needs a stable signature before adapter-wrapping; each toolbar needs ~5 lines of refactor first. Only `eagle_ai` is wired today. | Low–medium — additive but per-module differs |
| **PydanticAI Ollama backend** | Optional local-LLM swap; lands behind a config flag once D.1 is in. | None |

These are the only meaningful gaps. The framework is set up to absorb each as a single-session PR.

---

## 7. Stats — combined across 2026-05-27 + 2026-05-28

| Category | Files | Lines |
|---|---|---|
| Production code edits (additive, fail-safe) | 4 files modified | ~2,250 |
| EchoMind adapters | 6 files | 1,378 |
| Command Bus core | 4 files | 570 |
| KPI machinery | 4 files | 838 |
| Code unit tests | 12 files | 1,431 |
| Bus-driven scenarios | 8 files | 914 |
| Pywinauto OS-level | 5 files | 970 |
| Live walkthroughs | 2 files | 382 |
| Tools (HTML / cross-build / dashboard) | 3 files | 742 |
| Architecture docs | 6 docs | ~2,200 |
| READMEs + QUICKSTART | 5 docs | ~500 |
| **Combined** | **~60 files** | **~12,200 LOC** |

Pass rate: **21 pass / 0 fail / 11 skip** in sandbox (skips run on Windows venv with pydantic installed). All production-code edits compile via `py_compile`; the 15 original regression guards still pass.

---

## 8. Files reviewers should open first

In this order:

1. `docs/plans/architecture/UNIFIED_COMMAND_LAYER_2026-05-27.md` — why we built it
2. `docs/plans/architecture/TESTING_ARCHITECTURE_2026-05-28.md` — testing strategy
3. `tests/QUICKSTART.md` — how to run + add tests in 5 minutes
4. `docs/plans/architecture/REGRESSION_CATALOG.md` — what's guarded
5. `modules/EchoMind/secretary/command_bus.py` — the central façade (134 LOC)
6. `tests/code/system/test_2026_05_27_regression_guards.py` — the 15 guards for the bug fixes
7. `tools/kpi_dashboard.py` output — one-screen health snapshot

---

*Reviewer's gate: `bash tests/run_code_tests.sh` should print "ALL GREEN" on a Windows venv with pydantic installed. If it doesn't, the dashboard tells you exactly which probe is red.*
