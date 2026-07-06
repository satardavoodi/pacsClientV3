# AIPacs v3.4.6 Release Notes

**Release date:** 2026-07-06
**Branch:** beta-version
**Previous stable:** v3.4.5

---

## Summary

v3.4.6 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. It continues the
Optimization/Stability/Reliability plan and hardens multi-study series identity,
and adds an EchoMind secretary unified MCP entrypoint plus a clinical-agent
validation pipeline.

---

## Version Alignment

The following canonical version markers are set to `3.4.6`:

- `pyproject.toml` -> `version = "3.4.6"`
- `main.py` -> `app.setApplicationVersion("3.4.6")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.6`
- `docs/README.md` -> current stable `v3.4.6`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.6`
- `.github/copilot-instructions.md` -> current stable `v3.4.6`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.6` (English + Farsi), realigned from a reverted 3.4.2 state

LICENSE unchanged.

---

## Included In This Release

- Series identity: cache study-identity, grow-lane study-number binding (OPT-06), and viewport study-identity guards (multi-study / previous-exam correctness)
- Startup/perf (OPT-01/OPT-12): single-instance fast sweep and cheap-name reuse, study-downloaded status cache, telemetry log-level downgrade (log hygiene)
- EchoMind secretary: unified MCP entrypoint, clinical-agent validation pipeline, viewer-write adapter, browser/education adapter refinements
- Web browser: page-tools and widget improvements
- Nuitka build refinements and aipacs_control_mcp testing-harness updates
- Stable version bump to v3.4.6 across canonical metadata files

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.6` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
