# tests/gui/live_walkthroughs/

One-off agentic walkthroughs and post-mortem KPI extractors. These are
run BY HAND (or by a chat agent) against a real running source build.

## Contents

| File | Purpose |
|---|---|
| `_verify_source_build.py` | Pre-flight check: confirms the running window is the source build (not the frozen aipacs.exe). Imported by every gui-driver. Has a CLI entry point: `python _verify_source_build.py` returns 0/2. |
| `extract_2026_05_27_kpis.py` | Parses `user_data/logs/download_diagnostics.log` + `native_fault.log` and prints PASS/CHECK for the three 2026-05-27 fixes. Run after a live session. |

## Adding a new walkthrough

Each walkthrough should be a single script that:
1. Calls `_verify_source_build.require_source_build()` first.
2. Records the start time (for `--since` filtering in the KPI step).
3. Drives the scenario (via pywinauto, EchoMind, or computer-use MCP).
4. Runs a domain-specific KPI extractor at the end.

The 2026-05-27 example shows both halves: the walkthrough lives in
`pywinauto/run_patient_open_smoke.py` (which forwards to the extractor
here), and the extractor lives in this folder.
