# AI-PACS Tests

**For navigation by intent, see:**
- [**INDEX_BY_GUARD.md**](INDEX_BY_GUARD.md) — every guard test and what it protects
- [**QUICKSTART.md**](QUICKSTART.md) — 5-minute onboarding (how to run, where to add tests, the hard rules)
- [**../docs/AUDIT_2026-05-28_OVERVIEW.md**](../docs/AUDIT_2026-05-28_OVERVIEW.md) — what the staged audit added

---

Tests are split into two top-level categories by **how they execute**:

| Folder | What it contains | How to run |
|---|---|---|
| `tests/code/` | Pure-Python + headless-Qt tests. No visible window required. Safe in CI. **The 167 existing tests live here.** | `pytest tests/code/` |
| `tests/gui/` | Live-driver tests that interact with a real running AI-PACS window via UI automation (pywinauto, EchoMind Secretary, or Anthropic computer-use MCP). | See `tests/gui/README.md` |

This split is binary on purpose: if a test can run from a CI pipeline without a display, it is *code*; if it needs a real desktop UI in front of it, it is *gui*.

---

## tests/code/

Subdivided by domain — same hierarchy that existed before the split:

```
tests/code/
├── architecture/    # cross-module constraints, signal hygiene, layering
├── build/           # PyInstaller / Nuitka build checks
├── builder/         # plugin packaging
├── cd_burner/
├── connection_between_modules/
├── database/        # SQLite isolation, pollution cleanup
├── diagnostics/
├── download_manager/  # Zeta DM internals
├── fast/            # FAST viewer non-UI bits
├── fast_viewer/     # FAST viewer with offscreen Qt
├── load/
├── manual_archive/  # legacy test snapshots
├── module_system/   # module registry & loader
├── network/         # socket + (retired) gRPC
├── offline_cloud_server/
├── performance/     # perf benchmarks
├── printing/
├── runtime/         # aipacs_runtime helpers
├── smoke/           # quick app-start smoke
├── startup/
├── storage/         # cleanup panel
├── system/          # cross-cutting regression guards (e.g. 2026-05-27)
├── ui_services/     # UI-thread dispatch, lifecycle
├── utils/           # logging lint, config helpers
├── viewer/          # main viewer + VTK + drag-drop (headless)
└── web_browser/
```

Some tests under `code/` import `PySide6` but never show a window — they construct
QWidgets in offscreen mode and only assert on object state. Set the Qt platform
to `offscreen` before running on a headless box:

```bash
export QT_QPA_PLATFORM=offscreen   # macOS/Linux
$env:QT_QPA_PLATFORM = "offscreen" # PowerShell
pytest tests/code/
```

### Recurring regression guards

`tests/code/system/test_2026_05_27_regression_guards.py` is the structural
guard for the three fixes shipped 2026-05-27. It fails the build if any of
them regresses:

- `client.get_study_info(` reappears in the GetStudyInfo probe path
  (`_hp_study_save.py` — would re-introduce the 6.8 s download-start stall).
- The Eagle Eye MG mirror loses its `QTimer.singleShot(0, _do_mirror)`
  defer (would re-introduce the 0x8001010d COM crash on drag-drop).
- The multi-patient Download metadata pre-fetch loses its
  `ThreadPoolExecutor` (would re-introduce the 6-30 s UI freeze when
  selecting 20-30 patients).

Run just these:

```bash
pytest tests/code/system/test_2026_05_27_regression_guards.py -v
```

---

## tests/gui/

Tests under `tests/gui/` need a running AI-PACS source build (the Python
window — never the frozen `aipacs.exe`). They are not run in CI; they're for
local validation and KPI extraction.

See `tests/gui/README.md` for which driver to use and how to extend.

---

## Running everything

| Command | What it does |
|---|---|
| `pytest tests/code/` | Run the full code-only suite. Required for PRs. |
| `pytest tests/code/<dir>/` | Run one domain (e.g. `tests/code/download_manager/`). |
| `pytest tests/code/system/test_2026_05_27_regression_guards.py -v` | Regression guards only — fast smoke for the 2026-05-27 fixes. |
| `python tests/gui/live_walkthroughs/extract_2026_05_27_kpis.py` | Parse the live log files and print KPI PASS/CHECK for the 2026-05-27 fixes. Run after a live session. |
| `python tests/gui/pywinauto/run_patient_open_smoke.py` | Drive a real AI-PACS window through the patient-open path (pywinauto). Requires source build running. |
