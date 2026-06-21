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

- **Desktop control** (computer-use: screenshot + mouse/keyboard on the real desktop) — how you
  drive and observe the running GUI. Apps are granted at a **tier**:
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

**Default workflow = human-assisted bootstrap** ([`../../CLAUDE.md`](../../CLAUDE.md) → "Human-assisted
bootstrap mode"). The human handles launch, login, popups, and moving the app to Monitor 1; you
**test from the already-open app**.

- **Procedure & monitor mechanics:** [Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md)
  (source-build launch, login = click **Sign In**, deterministic monitor switching via
  `Win+Shift+←/→`, the "what the middle title-bar button really does" investigation).
- **Layout:** AI-PACS on **Monitor 1** (larger), VS Code/terminal/logs on **Monitor 2**.
- **Drive it:** screenshot first → tick **MR/CT** → set the date (last 2–3 days) →
  **Search Patients** → single-click several patients (thumbnails should auto-load in the
  sidebar) → open a patient / study to verify the viewer. Identify the **source build by its
  Python (snake) taskbar icon**, not the black AI-PACS icon.
- **If the GUI stops responding to control:** stop and ask the user for a short, specific action.
  Do **not** do random relaunches and do **not** open the installed exe.

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
3. **GUI/workflow change?** Ask the human to bootstrap the app (or confirm it's open on
   Monitor 1), then drive + observe via desktop control (§3) and confirm via logs (§5).
4. Ship the fix the framework's way: minimal edit **+ guard test + catalog row**, tasks tracked.

---

## 8. Cross-references

- [`../../CLAUDE.md`](../../CLAUDE.md) — project rules, subsystem regression guards, bootstrap mode.
- [`./README.md`](./README.md) — first-five-minutes onboarding + the four rituals.
- [Launch & Control Runbook](../AIPACS_LAUNCH_CONTROL_RUNBOOK.md) — launch / login / monitor control.
- [`../../tools/dev/SANDBOX_TESTING.md`](../../tools/dev/SANDBOX_TESTING.md) — Verify-lane setup (this session's addition).
- `.github/prompts/` — [`root-cause-fix`](../../.github/prompts/root-cause-fix.prompt.md),
  [`debug-thumbnails`](../../.github/prompts/debug-thumbnails.prompt.md),
  [`inspect-logs`](../../.github/prompts/inspect-logs.prompt.md),
  [`run-tests`](../../.github/prompts/run-tests.prompt.md),
  [`regression-guard`](../../.github/prompts/regression-guard.prompt.md).
- [`../../tests/QUICKSTART.md`](../../tests/QUICKSTART.md) · [`../INDEX_BY_SUBSYSTEM.md`](../INDEX_BY_SUBSYSTEM.md) · [`../../tests/INDEX_BY_GUARD.md`](../../tests/INDEX_BY_GUARD.md).

*Created 2026-06-21 alongside the sandbox Verify-lane setup.*
