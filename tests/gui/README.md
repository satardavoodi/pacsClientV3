# tests/gui/ — Live-driver test scaffolding

These tests interact with a real running **AI-PACS source build** (the
Python window, never the frozen `aipacs.exe`). They cannot run in CI.
Use them for local validation, KPI capture, and demos.

## Three drivers, three sub-folders

| Folder | Driver | When to reach for it |
|---|---|---|
| `pywinauto/` | [pywinauto](https://pywinauto.readthedocs.io/) (Windows UI Automation) | **Default for new scripted tests.** Pure Python, fast, reliable on Qt windows. Targets by control name and accessibility role. |
| `echomind_driven/` | EchoMind Secretary (`modules/EchoMind/secretary/`) | When the assertion is about *what the app does in response to a natural-language command*. The Secretary already has adapters (`HomeWidgetAdapter`) that drive the live `home_widget` in-process. |
| `live_walkthroughs/` | Anthropic computer-use MCP (or pyautogui fallback) | One-off agentic walkthroughs — what was used in the 2026-05-27 session to drive Scenarios 1/2/3 from chat. Slowest, costliest; reserve for ad-hoc work. |

### Why pywinauto is the default

- Native Windows UI Automation API — sees Qt widgets via accessibility names
  set in the AI-PACS code (`setObjectName`, `setAccessibleName`).
- No model round-trips per click (unlike computer-use MCP).
- Works fine alongside the running app — it attaches, doesn't relaunch.
- Compatible with `pytest` markers (e.g. `@pytest.mark.gui_live`) so the
  same test file can also expose a CLI entry point.

Install once:

```bash
pip install pywinauto
```

### EchoMind as a driver

`modules/EchoMind/secretary/adapters/home_widget_adapter.py` exposes a
`HomeWidgetAdapter` that binds to the live `home_widget` instance — the
Secretary calls into the SAME Python objects the GUI is rendering, so
mutations and reads are race-free without UI clicks. The cost is that
the test must run **inside** the AI-PACS Python process (or attach to
it via an IPC shim — currently not supplied).

For the cleanest tests, an EchoMind-driven test should:

1. Use the existing Secretary action protocol (`SecretaryActionPlan`).
2. Run alongside the launched app (e.g. via a `--secretary-test` flag
   on `main.py` that triggers the test plan after startup completes).

Future: scaffold an in-process `pytest --aipacs-attach` plugin that
discovers a running PID and attaches the Secretary adapter.

### computer-use MCP

Useful when you're inside Claude / Cowork and want to record a
walkthrough or capture a KPI mid-conversation. The 2026-05-27 session
used this for Scenarios 1 & 2 — clicks were driven from chat. See
`live_walkthroughs/extract_2026_05_27_kpis.py` for the log-parsing
side of that flow.

## Pre-flight check

Every gui test must first verify it's talking to the **source build**.
The shared check is in `live_walkthroughs/_verify_source_build.py`
(also re-exported from `pywinauto.utils`). It looks at:

- `user_data/logs/download_diagnostics.log` mtime — must be < 60 s old
  *after the app has done at least one click*.
- The window's owning process name — must be `python.exe`, never
  `ai pacs viewer.exe` or `aipacs.exe`.

Refuse to drive scenarios if either check fails — testing the frozen
exe never validates the latest fixes.

## Running

```bash
# Live KPI extract after a manual session
python tests/gui/live_walkthroughs/extract_2026_05_27_kpis.py

# Scripted patient-open smoke via pywinauto (requires running source build)
python tests/gui/pywinauto/run_patient_open_smoke.py

# Optional: bind pywinauto tests to pytest with a custom marker
pytest tests/gui/pywinauto/ -m gui_live --gui-live
```

