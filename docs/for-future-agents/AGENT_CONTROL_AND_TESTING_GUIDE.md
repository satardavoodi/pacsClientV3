# AI-PACS — Agent Control & Testing Abilities

**Audience:** an AI agent (Claude Desktop/Cowork, Claude Code, Copilot, etc.) that needs to
**control and test** the AI-PACS workstation. This is the single capability overview: what you
can do, with which tool, and how the pieces fit. Read it with [`../../CLAUDE.md`](../../CLAUDE.md),
this folder's [`README.md`](./README.md), and the
[Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md).

> **Golden rule:** preserve clinical behaviour and the source-build discipline. Empowerment
> here means *knowing your tools*, not bypassing the safety rules in §6.

---

## 1. TL;DR — there are two testing lanes

| | **Verify lane** (fast, agent-autonomous) | **Clinical lane** (real, human-assisted) |
|---|---|---|
| Where | Linux **sandbox** (headless) | **Windows source build** (the actual app) |
| Runs | offscreen `pytest`, ruff, import/syntax checks | the real PySide6/VTK GUI |
| Speed | seconds–minutes | full app startup |
| Use it to | catch import/logic/**regression** breakage before a live pass | verify GUI, thumbnails, viewer, real workflows |
| Setup | `bash tools/dev/sandbox_setup.sh` (see §4.1) | human bootstraps; you drive (see §3) |
| Cannot | open the GUI, render, VTK windows, Windows-only COM | — |

Most fixes should pass the **Verify lane first**, then get a **Clinical lane** GUI check.

**To drive the live app, prefer the in-app command surface — the `aipacs-control` MCP (§3.1) —
over pixel-clicking.** It is the path the maintainers built specifically to control the
workstation faster and more reproducibly than Windows-MCP / computer-use.

---

## 2. Your toolbelt — what each tool can and cannot do here

The exact tools depend on your harness; this is the model for a **desktop-control + sandbox**
agent (the default Cowork setup). A Copilot-in-VS-Code agent instead drives the integrated
terminal directly (see [`../VSCODE_AGENT_MODE_SETUP_2026-06-02.md`](../VSCODE_AGENT_MODE_SETUP_2026-06-02.md)).

- **File tools (Read / Write / Edit)** — the primary way to inspect and patch code in the repo
  (`E:\ai-pacs\ai-pacs codes\ai-pacs beta version`). They read the real filesystem and are
  reliable. *Caveat:* the agent's Linux **bash mount** of the repo occasionally returns null
  bytes for a few very large files — when bash output looks truncated/garbled, **trust the Read
  tool** (or `rsync` the source to local fs); it is a mount artifact, not a code bug.

- **Linux sandbox shell** (`bash`) — runs the **Verify lane**: offscreen `pytest`, `ruff`,
  Python scripts, `git`. It **cannot** launch or kill Windows processes or open the GUI, and
  each call has a **~45 s limit** (for long jobs, start them and poll; see
  [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md)).

- **In-app command surface — the FASTEST way to drive the GUI** (preferred over pixel-clicking,
  and the path the maintainers built to beat Windows-MCP). The app exposes its real functions via
  the EchoMind **CommandBus**; with `AIPACS_TEST_SERVER=1` (source build only) that bus is
  reachable over a `QLocalServer` pipe wrapped by the **`aipacs-control` MCP**
  (`tools/testing/aipacs_control_mcp/`). Call tools like `open_patient`, `drag_series`, `open_mpr`,
  `query_viewport_state`, `burst`, `run_scenario` — each runs the *same production code path* a
  click/drop would, at ms-latency. Full how-to in §3.1.

- **Desktop control** (computer-use: screenshot + mouse/keyboard on the real desktop) — the
  **fallback**: visual verification (screenshots of what actually rendered) and actions outside
  the command vocabulary. Apps are granted at a **tier**:
  - **Browsers → "read"**: visible in screenshots, no clicks/typing.
  - **Terminals & IDEs (VS Code, terminal) → "click"**: you can *see* and *click* (e.g. a Run
    button) but **cannot type** into them. So you cannot type a launch command into a terminal.
  - **Everything else (the AI-PACS GUI, File Explorer) → "full"**: clicks + typing.
  - You must `request_access` for an app before controlling it. **Look before you assert** —
    take a screenshot to check state rather than guessing.

- **Native / web control MCPs** (Windows-MCP, Chrome MCP) — may be present for native-Windows or
  browser tasks. Prefer a dedicated MCP or VS Code/terminal when available; the §6 discipline
  still applies.

### Why the human usually launches the app
Your shell is Linux (can't start the Windows app) and Windows terminals/VS Code are tier
**"click"** (no typing). The only fully-agent launch path is **double-clicking a `.bat` in File
Explorer**. If that's unreliable, **ask the user** to launch — don't fight window management or
open the frozen exe. This is why **human-assisted bootstrap is the default** (§3).

---

## 3. Controlling the running app

Two ways to drive the live app. **Prefer the command surface; fall back to pixel control only for
what it can't do.**

### 3.1 Fastest path — the in-app command surface (`aipacs-control` MCP)
Built specifically to control the workstation faster and more reproducibly than mouse automation.
Reference: [`../../tools/testing/aipacs_control_mcp/README.md`](../../tools/testing/aipacs_control_mcp/README.md)
· architecture [`../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md`](../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md)
· fidelity [`../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md`](../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md).

**Chain:** MCP tool → in-app **Test Control Server** (`QLocalServer`, `modules/EchoMind/secretary/test_server.py`)
→ EchoMind **CommandBus** → the real application function. Every command runs the production code
path, so cross-patient isolation and multi-study guards stay enforced (fidelity tier **T1**;
commands queue one-per-event-loop-turn — impatient-user pressure a human can't reproduce).

**Enable (source build only — NEVER during clinical reading):**
1. `& "<repo>\.venv\Scripts\python.exe" -m pip install mcp` (once).
2. Launch the source build with `AIPACS_TEST_SERVER=1` (restore the full env first so the per-user
   socket name resolves — see the README's PowerShell block). Banner confirms
   `[TEST_SERVER] LISTENING on local socket 'AIPACS_TEST_<user>'`.
3. Register the MCP (stdio) in your client (`aipacs-control` → the `.venv` python running
   `tools/testing/aipacs_control_mcp/server.py`) — works for Claude Desktop, Cowork, and Claude
   Code. Or skip MCP and use the CLI:
   `& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\client.py open_patient '{\"patient_id\": \"44704\"}'`.

**Tool vocabulary** (each = a real UI action):
- *Lifecycle:* `launch_app` (launches the source build with the test server, dismisses startup
  dialogs, clicks Sign In, moves to a monitor, waits ready), `stop_app`, `app_status`,
  `wait_app_ready`, `login`, `list_monitors`, `move_app_to_monitor`.
- *Workflow:* `list_patients`, `select_patient` (single-click + thumbnails), `open_patient`
  (double-click open), `drag_series` (the exact `change_series_on_viewer` a real drop defers to),
  `open_mpr`, `switch_tab`, `close_patient_tab`, `trigger_download`, `query_download_state`,
  `wait_for_download`, `query_viewport_state`, `query_thumbnail_state`, `snapshot_health`.
- *Pressure / repro:* `burst` (N commands as fast as the pipe allows), `run_scenario` (seeded JSON
  timelines + JSONL session recording). `list_actions` / `raw_command` reach anything else the bus
  exposes.

In a **normal** clinical run (no test server) only read + safe-navigation actions exist; the full
write surface (`change_series`, `close_patient_tab`, …) is registered **only** when the test
server is on. `change_layout` is a typed NOT_IMPLEMENTED stub for now. Contract guard:
`tests/code/echomind/test_adapter_contracts.py` — run it whenever adapters change.

### 3.2 Fallback — desktop control (computer-use)
Use pixel control only for what the command surface can't do: **visual verification** (screenshot
the viewport to confirm what actually rendered) and actions not in the vocabulary. Tiers + the
"look before you assert" rule are in §2. Manual sanity loop: tick **MR/CT** → set the date →
**Search Patients** → single-click patients (thumbnails auto-load) → open a study. Identify the
source build by its **Python (snake) taskbar icon**, not the black AI-PACS icon.

### 3.3 Launch & positioning
**Default = human-assisted bootstrap** ([`../../CLAUDE.md`](../../CLAUDE.md) → "Human-assisted bootstrap
mode"): the human launches the source build, logs in, and moves it to **Monitor 1**; you drive
from the open app. When the test server is enabled, the `aipacs-control`
`launch_app` / `login` / `move_app_to_monitor` tools can do this end-to-end; otherwise follow the
[Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md) (deterministic monitor switch =
`Win+Shift+←/→`). **If the GUI stops responding, ask the user** — never random-relaunch and never
open the frozen exe.

---

## 4. Testing the app

### 4.1 Verify lane — offscreen tests in the Linux sandbox (added 2026-06-21)
Full recipe and caveats: [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md).

```bash
bash tools/dev/sandbox_setup.sh      # installs everything in requirements.txt (idempotent, resumable)
source tools/dev/sandbox_env.sh      # LD_LIBRARY_PATH (vendored libEGL/PortAudio) + QT_QPA_PLATFORM=offscreen
python3 -m pytest tests/code/<target> -p no:debugging -q
```

- **Covers:** ~1955 collectable tests — pure-Python logic **and** Qt widgets under
  `QT_QPA_PLATFORM=offscreen` (PySide6/vtk/SimpleITK/DICOM stack all import).
- **Does not cover:** the real GUI, actual rendering, VTK render windows, or Windows-only
  `comtypes` (inert on Linux). Those need the Clinical lane.
- Sandbox installs **do not persist** between sessions — re-run `sandbox_setup.sh` each session.

### 4.2 Tests on Windows — the blessed path
See [`.github/prompts/run-tests.prompt.md`](../../.github/prompts/run-tests.prompt.md) and
[`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md).
- Bootstrap-aware: `python main.py --run-tests <args>` (wrapped by `run_test.ps1`).
- Direct unit tests: `.venv\Scripts\python.exe -m pytest <args>`.
- **Always keep `-p no:debugging`** (`tests/code` shadows the stdlib `code` module).
- **Never** let a DB test write to the live `user_data/database/dicom.db` — patch
  `PacsClient.utils.data_paths.DATABASE_FILE` and clear the pool (CLAUDE.md → DB isolation).

### 4.3 GUI / live verification
Drive the patient → thumbnail → viewer workflow per §3, then confirm against the logs (§5).
This is the only lane that proves clinical behaviour; the Verify lane is a pre-filter, not a
substitute.

---

## 5. Logs — your control feedback loop

Primary directory: `user_data/logs/` — inventory and scan guidance in
[`.github/prompts/inspect-logs.prompt.md`](../../.github/prompts/inspect-logs.prompt.md).

- `app.log` — general application log (+ rotations).
- `download_diagnostics.log` — socket download + thumbnail pipeline. Thumbnail success =
  `right_panel_socket_start` → `right_panel_socket_done thumbnail_count=N` within ~1–3 s; failure
  = `right_panel_socket_error`, a ~45123 ms timeout, or port `105` usage.
- `viewer_diagnostics.log` — viewer / rendering / stack-drag (note: some viewer traces route
  here, **not** `app.log`).
- `db_diagnostics.log`, `com_trace.log`, `native_fault*.log` — DB, COM interop, native crashes.

**Analyze logs before major changes** — it's a project rule (CLAUDE.md).

---

## 6. Hard rules — never (recap; full list in CLAUDE.md & README §4)

- **Source build only.** Never run the frozen `d:\ai-pacs\aipacs\aipacs.exe`, the desktop icon,
  or the black taskbar icon — they ignore source edits. The source build = the **Python icon**.
- **One instance.** Never spawn multiple AI-PACS instances (the single-instance guard would just
  raise the old window, so your new code never loads).
- **Human-assisted bootstrap is default.** Don't burn cycles automating launch/login/monitor
  moves/process recovery — ask the user.
- **Preserve functionality.** No unrelated refactors; minimal safe edits; respect the
  regression-guard discipline (guard test that fails-before/passes-after + a
  `REGRESSION_CATALOG.md` row).
- **Testing rails.** Keep `-p no:debugging`; never write to the live `dicom.db`.

---

## 7. Start-of-session checklist

1. Read [`../../CLAUDE.md`](../../CLAUDE.md), this guide, and (for GUI work) the
   [Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md).
2. **Code/logic change?** Verify lane: `bash tools/dev/sandbox_setup.sh` →
   `source tools/dev/sandbox_env.sh` → run the **targeted** suite for what you changed.
3. **GUI/workflow change?** Confirm the app is open on Monitor 1 (human-assisted bootstrap, or
   `aipacs-control launch_app` when the test server is on), then drive it via the **command
   surface (§3.1)** — falling back to desktop control for visual checks — and confirm via logs (§5).
4. Ship the fix the framework's way: minimal edit **+ guard test + catalog row**, tasks tracked.

---

## 8. Cross-references

- [`../../CLAUDE.md`](../../CLAUDE.md) — project rules, subsystem regression guards, bootstrap mode.
- [`./README.md`](./README.md) — first-five-minutes onboarding + the four rituals.
- [Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md) — launch / login / monitor control.
- [`../../tools/testing/aipacs_control_mcp/README.md`](../../tools/testing/aipacs_control_mcp/README.md) — **the in-app control surface** (`aipacs-control` MCP / CommandBus / Test Control Server). Architecture: [`../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md`](../reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md); fidelity vs. real clicks: [`../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md`](../reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md).
- [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md) — Verify-lane setup (this session's addition).
- `.github/prompts/` — [`root-cause-fix`](../../.github/prompts/root-cause-fix.prompt.md),
  [`debug-thumbnails`](../../.github/prompts/debug-thumbnails.prompt.md),
  [`inspect-logs`](../../.github/prompts/inspect-logs.prompt.md),
  [`run-tests`](../../.github/prompts/run-tests.prompt.md),
  [`regression-guard`](../../.github/prompts/regression-guard.prompt.md).
- [`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md) · [`../INDEX_BY_SUBSYSTEM.md`](../INDEX_BY_SUBSYSTEM.md) · [`../../tests/INDEX_BY_GUARD.md`](../../tests/INDEX_BY_GUARD.md).

*Created 2026-06-21 alongside the sandbox Verify-lane setup; the in-app command-surface control
path (§3.1) was documented the same day.*
