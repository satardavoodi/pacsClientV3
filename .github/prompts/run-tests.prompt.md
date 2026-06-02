---
mode: agent
description: Run AI-PACS tests the correct way and report pass/fail with the failing assertions.
---

# Run tests

## How tests run here
- **Blessed path:** `python main.py --run-tests <pytest args>` (wrapped by `run_test.ps1`).
  Use this for anything that needs the app bootstrap. VS Code task:
  **"AIPacs: Run Tests (run_test.ps1, default smoke)"**.
- **Direct pytest** (fast, for pure unit tests) via the venv:
  `\.venv\Scripts\python.exe -m pytest <args>`. VS Code tasks:
  **"Pytest: Collect only (sanity)"** and **"Pytest: Run tests/code (fast unit)"**.
- pytest config is in `pyproject.toml`. The `addopts` include **`-p no:debugging`** —
  required because `tests/code/` shadows the stdlib `code` module under prepend import
  mode. Never strip that flag.
- `testpaths = ["tests", "EchoMind/secretary/tests"]`. Suites live under `tests/code`,
  `tests/gui`, `tests/_kpi`, and per-subsystem folders (e.g. `tests/download_manager`).

## Steps
1. Start with **collect-only** to confirm the tree imports cleanly.
2. Run the targeted suite for the area you changed (don't run everything blindly).
3. Report: command used, pass/fail counts, and the exact failing assertions/tracebacks.
4. After a code fix, re-run the **same** suite and compare before/after.

Database-touching tests must redirect `PacsClient.utils.data_paths.DATABASE_FILE` and
clear the pool — never write to the live `user_data/database/dicom.db` (see `CLAUDE.md`).
