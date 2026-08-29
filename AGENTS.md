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
- Canonical current version: `3.6.3` in `pyproject.toml`, `main.py`, and release docs.
- Supported interpreter in this checkout: Python `3.13.5` from `.venv`.
- The public AI-PACS website is a separate project. Read `WORKSPACE.md` before adding a
  website endpoint, shared identity/licensing work, Case-of-the-Day publishing, or ATI work.

## Read before editing

1. `CLAUDE.md` for runtime, testing, and subsystem invariants.
2. `docs/for-future-agents/README.md` for the repository discipline.
3. `docs/INDEX_BY_SUBSYSTEM.md` to locate the subsystem-specific design and tests.
4. `tests/INDEX_BY_GUARD.md` to understand the existing regression guards.
5. `docs/architecture/PRE_DEVELOPMENT_SYSTEM_MAP_2026-08-27.md` for the verified startup,
   subsystem, network, storage, packaging, skill, and MCP connection map.
6. `docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md` for the latest verified baseline
   and unresolved repository-level blockers.

For optimization, stability, or reliability work, also read
`docs/OPTIMIZATION_STABILITY_RELIABILITY_MASTER_PLAN.md` and update its existing `OPT-*`
item rather than creating a disconnected plan.

## Non-negotiable engineering rules

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

- Several runtime trees have packaged mirrors under `builder/plugin package/packages/*/payload`.
  When a mirrored source changes, use `tools/dev/sync_plugin_mirrors.py`, verify with
  `tools/dev/verify_plugin_mirrors.py`, and run the relevant builder parity guards.
- New modules and feature-flag configuration must satisfy the full checklist in `CLAUDE.md`:
  runtime catalog, package definition, installer component/profile writers, config-family
  versioning, mirror sync, and builder/runtime tests.
- Do not edit generated build output as source. Release builds are heavyweight and should not
  be run casually on a dirty worktree.

## Verification baseline and commands

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
