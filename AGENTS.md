# AI-PACS Codex Working Agreement

This file is the short, Codex-native entry point for work in this repository. It does not
replace the detailed project history in `CLAUDE.md` or `docs/`.

Recovered Cloud Desktop conversations, generated files, memory, skills, and tool mappings are
indexed at `D:\_RECOVERY\restored\projects\ai-pacs-workstation`.

## Language policy

- The user may communicate with Codex in Persian, and Codex may report progress and results
  directly to the user in Persian.
- Everything created, edited, or applied in the repository or on the system must be written
  in English. This includes source code, comments, documentation, commit messages, logs,
  configuration, generated artifacts, test names and fixtures, developer-facing text, and
  end-user-visible interface text.
- Do not introduce Persian text into project files or system changes unless the user explicitly
  overrides this policy for a specific artifact.

## Project identity

- Product: Windows desktop DICOM workstation built with Python, PySide6, VTK, SimpleITK,
  pydicom, SQLite, and packaged plugin payloads.
- Source entry point: `main.py`.
- Canonical current version: `3.6.8` in `pyproject.toml`, `main.py`, and release docs.
- Supported interpreter in this checkout: Python `3.13.5` from `.venv`.
- The public AI-PACS website is a separate project. Read `WORKSPACE.md` before adding a
  website endpoint, shared identity/licensing work, Case-of-the-Day publishing, or ATI work.

## Read before editing

1. `CLAUDE.md` for runtime, testing, and subsystem invariants.
2. `docs/release-and-build/README.md` for the Git/build documentation map.
3. `RELEASE.md` before any versioned commit, tag, push, or full release build.
4. `BUILD.md` before any packaging or installer work.
5. `docs/for-future-agents/README.md` for the repository discipline.
6. `docs/INDEX_BY_SUBSYSTEM.md` to locate the subsystem-specific design and tests.
7. `tests/INDEX_BY_GUARD.md` to understand the existing regression guards.
8. `docs/architecture/PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md` for the verified startup,
   subsystem, network, storage, packaging, skill, and MCP connection map.
9. `docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md` for the latest verified baseline
   and unresolved repository-level blockers.

For optimization, stability, or reliability work, also read
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` and update its existing `OPT-*`
item rather than creating a disconnected plan.

## Non-negotiable engineering rules

- Workstream ownership (user decision, 2026-09-16): Unify work owns shared identity,
  catalog/thumbnail presentation, download/file/state coordination and cache invalidation
  contracts, not viewer-specific decoding, filters, rendering or decoded-cache internals.
  Route Advanced/VTK findings to `docs/reports/VTK_DOMAINS_GEOMETRY_PERFORMANCE_REVIEW_2026-09-16.md`
  and shared-pipeline findings to `docs/reports/UI_STALL_EVIDENCE_AND_FIX_2026-09-02.md`.
  Use the handoff protocol in `docs/plans/architecture/UNIFIED_PIPELINE_BOUNDARY_2026-06-27.md`
  section 0.2; do not implement another workstream's fix or sync its in-progress payloads.
- Preserve unrelated and pre-existing worktree changes. This repository is often developed
  with a large dirty worktree; inspect `git status` and the relevant diff before every edit.
- Every bug fix ships with a regression guard that fails before the fix, the minimal code
  change, and a row in `docs/plans/architecture/REGRESSION_CATALOG.md`.
- Keep Fast Viewer, Advanced Viewer, and each VTK module as separate execution domains.
  Share only immutable, identity-keyed data through the documented read-only trunk.
- Do not perform blocking filesystem, network, AI, decode, or VTK construction work on the
  Qt GUI thread.
- Test database work must patch `PacsClient.utils.data_paths.DATABASE_FILE` and clear the
  connection pool. Never allow tests to touch the live `dicom.db`.
- Treat patient identifiers, DICOM data, images, prompts, reports, and logs as sensitive.
  Do not print or move them into reports, analytics, external tools, or committed fixtures.
- Use the source build only for live testing. The human launches and logs in once; never open
  the installed executable, never start multiple instances, and never improvise live login or
  process recovery.
- Prefer services/repositories over adding logic to the already oversized UI controllers.
- Do not reconnect the retired gRPC download path. Thumbnail and patient traffic uses the
  socket protocol configuration, not the DICOM port.
- Voice-to-text must use `modules/EchoMind/voice_transcription.py::VoiceTranscriptionService`.

## Mirrors, packaging, and release parity

- `RELEASE.md` is the only supported multi-remote release route. A full build
  requires its fresh Git synchronization receipt for the exact clean commit.
- `BUILD.md` is the single authoritative build entry point for humans and AI agents.
  A role-selected PyInstaller plus Nuitka candidate (four Client or two Server)
  must use the isolated
  `tools/build/build_local_candidate.py` workflow documented there. Backend-specific
  scripts and older runbooks are diagnostic/detail paths, not alternate release entry points.
- Several runtime trees have packaged mirrors under `builder/plugin package/packages/*/payload`.
  When a mirrored source changes, use `tools/dev/sync_plugin_mirrors.py`, verify with
  `tools/dev/verify_plugin_mirrors.py`, and run the relevant builder parity guards.
- New modules and feature-flag configuration must satisfy the full checklist in `CLAUDE.md`:
  runtime catalog, package definition, installer component/profile writers, config-family
  versioning, mirror sync, and builder/runtime tests.
- Do not edit generated build output as source. Release builds are heavyweight and should not
  be run casually on a dirty worktree.

## Verification baseline and commands

### Default launch preference (user decision, 2026-09-20)

- Eagle Eye changes must work in normal default operation without test-only feature flags.
- Normal user-requested launches keep `AIPACS_TEST_SERVER=0`. `run_app.ps1` enforces
  this default; `run_app.ps1 -TestServer` is an explicit opt-in for an authorized
  automation test session. Do not silently enable it on routine launches.
- Do not interrupt active voice recording or clinical work merely to change a
  launch flag. A running process retains its launch environment until restarted.

### Mandatory code and live GUI gates (user decision, 2026-09-14)

- Every runtime fix/Unify slice requires both automated code verification and an affected-workflow
  live GUI pass. Report them separately; blocked/skipped GUI work is not a pass. Documentation-only
  edits require document checks, not a fabricated application acceptance run.
- Before asking the human to perform the workflow, discover and use the existing `aipacs-control`
  MCP (`tools/testing/aipacs_control_mcp/server.py`). If unavailable in the current tool inventory,
  its `client.py` uses the same local Test Control Server; do not invent another control path.
  Read `docs/for-future-agents/AGENT_CONTROL_AND_TESTING_GUIDE.md` section 0 first.
- The human launches/logs into one source app with `AIPACS_TEST_SERVER=1` outside clinical reading.
  Probe `ping`, then `list_actions`; never enable the production LAN Agent Gateway for this purpose.
- Startup preference (2026-09-14): acknowledge the observed disk-space notice with **OK**, not
  **Don't show again**; this does not authorize cleanup or disabling warnings. Keep this step in
  GUI preflight. Never record/reveal saved credentials. The current Computer Use skill prohibits
  authentication automation, so hand off **Sign In** to the human and resume after Home is ready.
- MCP `drag_series` is a downstream series-switch test, not a real mouse/OLE drag or Home-card click.
  Cover the changed input boundary with actual GUI input and verify rendered output, identity,
  counts, and session-scoped logs. An accepted command or offscreen QWidget test is insufficient.
- Discover multi-study cases through bounded current PACS/reception reads: MG+US, spine radiography
  + lumbar MR, and repeat brain MR are candidate patterns, not proof of identity. Verify authoritative
  person/admission linkage and distinct StudyInstanceUIDs; never join people by name alone.
  Keep real identifiers/images out of memory, docs, committed fixtures, and external AI services.

- The focused 2026-08-27 active-work suite is green: 294 tests covering Eagle Eye lumbar/LLM,
  overlay reentrancy, and EchoMind pipeline scoping.
- The repository-wide fast lane is currently red and its wrapper can mask failure. Until the
  blocker in the readiness report is fixed, do not use `run_test.ps1` as proof of success.
  Invoke pytest directly and check its process exit code, for example:

  ```powershell
  $env:QT_QPA_PLATFORM = "offscreen"
  $env:PYTHONPATH = "."
  .\.venv\Scripts\python.exe -m pytest -p no:debugging tests/code/<subsystem> -q
  ```

- Runtime and build virtual environments currently pass `pip check`.
- Ruff is configured in `pyproject.toml` but is not installed by the current development
  requirements. Do not claim a lint pass unless the tooling gap has first been resolved.
- Live, build, slow, property, and clinical lanes are opt-in and require their documented
  prerequisites.

## Security stop condition

The 2026-08-27 audit found committed API-key-shaped strings in EchoMind runtime source,
packaged mirrors, and test files. Never display their values. Before editing those credentials,
publishing packages, or preparing a release, read the security section of the readiness report
and coordinate revocation/rotation, replacement with runtime secret loading, history cleanup,
and secret-scanning guards.
