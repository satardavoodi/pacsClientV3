---
mode: agent
description: Inspect AI-PACS runtime logs and summarize errors, races, timeouts, and threading issues.
---

# Inspect logs

Primary log directory: `user_data/logs/`

Key files:
- `app.log` — general application log (with rotations `app.log.1`, `.2`, …)
- `viewer_diagnostics.log` — viewer / rendering / stack-drag
- `download_diagnostics.log` — socket download + thumbnail pipeline
- `db_diagnostics.log` — database access
- `com_trace.log` — COM / native interop
- `native_fault.log`, `native_fault_crashes.log` — native crashes
- Terminal session logs from `run_app.ps1` live in `log/` (`latest_terminal_log.txt`
  points to the newest).

Scan for: exceptions and tracebacks, race conditions, stale-cache behaviour, threading
issues, socket failures/timeouts (e.g. ~45123 ms), and unusual delays.

Use the **"Logs: Tail …"** VS Code tasks to follow a log live while reproducing an issue.

Summarize: what failed, the first error in the chain, the timestamp/correlation, and the
single most likely root cause. Do **not** edit code in this prompt — report findings only.
