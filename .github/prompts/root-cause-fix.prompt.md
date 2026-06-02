---
mode: agent
description: AI-PACS root-cause workflow — understand, inspect logs, find the cause, make a minimal safe fix, retest once, report.
---

# Root-cause and minimal fix

Follow the AI-PACS engineering workflow. **Do not start with refactoring.**

1. **Understand the issue.** Restate the symptom and the expected vs. actual behaviour.
2. **Inspect relevant files.** Use `.github/copilot-instructions.md` (architecture map,
   file map, signal-flow) and `CLAUDE.md` (regression guards) to locate the code.
3. **Inspect logs before editing.** Read `user_data/logs/` —
   `app.log`, `viewer_diagnostics.log`, `db_diagnostics.log`, `download_diagnostics.log`,
   `native_fault.log`. Look for exceptions, race conditions, stale-cache behaviour,
   threading issues, socket failures, and timing.
4. **Identify the root cause** and state it plainly before touching code.
5. **Check the regression guards** in `CLAUDE.md` for any subsystem you are about to
   touch (multi-study viewer, thumbnail pipeline, DB isolation, Zeta download manager,
   FAST stack-drag, V2 design). Respect every listed invariant.
6. **Make the smallest safe, reversible edit.** No unrelated refactors. Preserve all
   clinical functionality (metadata, overlays, measurements, sync, reference lines,
   sidebars, patient workflows).
7. **Retest once** — run the relevant tests (`run_test.ps1` or the `Pytest:` tasks) and,
   if it is a GUI/workflow issue, verify in the already-running source build.
8. **Report**: root cause, the exact change, test result, and any remaining risks.

If interaction with the running app becomes unreliable, **stop and ask for a specific
human action** — never relaunch the frozen installed exe, never spawn a second instance.
