# VS Code Agent Mode — setup & optimization (2026-06-02)

Configuration of GitHub Copilot **Agent Mode** for the AI-PACS Beta Viewer
(`E:\ai-pacs\ai-pacs codes\ai-pacs beta version`). Goal: let the agent navigate the
project, understand the architecture, run tests, debug, inspect logs, and optimize code
safely — without indexing the ~450k generated/backup files that previously slowed search.

All edits are additive and reversible. The three pre-existing config files were backed up
to `.vscode/_backup_2026-06-02/` before editing (and are git-tracked).

## What changed

### `.vscode/settings.json` (merged — original keys preserved)
- **Search / watcher / Pylance excludes** for the heavy trees: `user_data` (~188k files),
  `backups` (~132k), `.venv` + `.venv_build` (~34k), `.claude/worktrees` (~40k),
  `generated-files`, `builder*`, `_recovery`, `Fonts`, caches. This is the single biggest
  responsiveness win for both VS Code and Copilot's codebase search.
- **pytest** enabled (`python.testing.pytestEnabled`), auto-discover-on-save off (large tree).
- **Pylance** scoped to open files (`diagnosticMode: openFilesOnly`, `typeCheckingMode: basic`).
- **Ruff** set as the Python formatter (config already in `pyproject.toml`); format-on-save
  left **off** to avoid noisy diffs on clinical code.
- **Copilot Agent wiring**: `chat.agent.enabled`, `chat.promptFiles`,
  `github.copilot.chat.codeGeneration.useInstructionFiles`.
- **Git/Explorer**: don't auto-scan the many `.claude` worktrees; file-nesting for the
  cluttered root; `*.qss` → CSS association.
- Untouched: the existing `chat.tools.terminal.autoApprove` rule for `main.py`, the
  interpreter path, code-runner, and gitProtocol.

### `.vscode/launch.json` (3 configs added, 2 originals kept)
- *Python: Debug Current File (.venv)*
- *Python: Debug Tests (pytest)* — used by the Test Explorer (`justMyCode: false`)
- *Run AIPacs (legacy V1 UI)* — sets `AIPACS_UI_VARIANT=v1` for V1/V2 regression testing

### `.vscode/tasks.json` (7 tasks added, originals kept)
`AIPacs: Run App (logged)`, `AIPacs: Run Tests (run_test.ps1)`, `Pytest: Collect only`,
`Pytest: Run tests/code`, `Lint: Ruff check`, `Logs: Tail download_diagnostics.log`,
`Logs: Tail app.log`.

### `.vscode/extensions.json` (new)
Recommends the Python stack, **Ruff** (missing today), TOML/YAML, PowerShell, autoDocstring,
Qt-for-Python, and Copilot/Copilot-Chat.

### `.vscode/mcp.json` (new)
Copilot Agent Mode MCP servers: `filesystem` (repo-scoped) and `sequential-thinking`, via
`npx`. An optional read-only SQLite server over a **copy** of `dicom.db` is documented but
disabled — never point MCP at the live clinical database.

### `.github/prompts/*.prompt.md` (new)
`/root-cause-fix`, `/debug-thumbnails`, `/inspect-logs`, `/run-tests`, `/regression-guard` —
one-click Agent Mode workflows encoding this project's hard-won procedures.

`.github/copilot-instructions.md` (967 lines) was **not** modified — it is already a complete
architecture/file/signal-flow/debugging reference.

## One-time follow-ups (need you)
1. Install the **Ruff** extension (`charliermarsh.ruff`) — VS Code will prompt on next open.
2. Warm up the MCP servers once while online:
   `npx -y @modelcontextprotocol/server-filesystem --help`
   then Start them from the Chat → Agent → tools panel. If `npx` isn't found, use
   `C:\Program Files\nodejs\npx.cmd` in `mcp.json`.
3. Reload the window (Developer: Reload Window) so the new settings/excludes take effect.
