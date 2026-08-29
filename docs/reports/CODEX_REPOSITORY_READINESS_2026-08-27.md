# AI-PACS Repository Readiness Evaluation — 2026-08-27

## Executive verdict

The repository has strong domain documentation, extensive regression coverage, healthy Python
environments, and a coherent architecture for a large Windows medical-imaging application. The
current Eagle Eye lumbar/LLM, overlay-reentrancy, and EchoMind changes pass their focused suite.

The repository is **ready for careful, subsystem-scoped development**, but it is **not ready for
a release or for trusting the repository-wide merge gate**. Two blockers outrank feature work:

1. API-key-shaped values are committed in runtime source and packaged mirrors.
2. The full fast test lane is red, while `run_test.ps1 -Fast` returns success after pytest fails.

No source implementation was changed during this evaluation. One tracked package-feed file that
the test suite mutated was restored to its exact pre-run state.

## Scope and evidence

Verified locally on branch `beta-version` at tagged commit `v3.6.3` (`5deb8ee7`), with a pre-existing
dirty worktree preserved.

- Python: `3.13.5` in both `.venv` and `.venv_build`.
- Dependency consistency: `pip check` passed in both environments.
- Build prerequisites: the three software-OpenGL fallback DLLs are present.
- Tracked repository: 7,127 files, approximately 267.9 MiB in the working tree; Git packs are
  approximately 423 MiB.
- Test inventory observed: more than 9,600 collected cases, substantially newer than several
  documents that still describe 167 or 2,270 tests.
- Focused active-work test: 294 passed, 3 warnings, in 7.48 seconds.
- Repository fast lane: 9,476 passed, 61 failed, 1 collection error, 69 skipped, 76 xfailed,
  10 xpassed, 187 reruns, and 1,477 warnings in 14 minutes 8 seconds.
- Not run: frozen application, live/clinical workflows, network-dependent tests, full installer
  build, property lane, coverage lane, or an online dependency-vulnerability audit.

## Architecture assessment

The application is organized into five useful layers:

1. PySide6 presentation and workstation shell (`main.py`, `PacsClient/`).
2. Workflow orchestration, download coordination, and EchoMind services.
3. Imaging domains: Fast Viewer, Advanced Viewer, MPR, dental, and AI imaging.
4. Network and persistence: socket services, SQLite, local data paths, and caches.
5. Packaging: installer/build tooling plus mirrored module payloads.

The most important architectural rule is sound: Fast Viewer, Advanced Viewer, and VTK modules
remain separate execution domains and share only immutable, identity-keyed inputs. The repository
also has a valuable bug-fix discipline: code, a pre-fix failing guard, and a regression-catalog row
ship together.

The main structural weakness is concentration of responsibility. Examples include a 9,916-line
toolbar manager, an 8,080-line patient-table widget, 7,584-line EchoMind page implementations,
and several 4,000–5,700-line viewer/MPR modules and tests. The packaged mirrors double several of
these files. Future work should extract services and repositories at behavior seams, not attempt
broad rewrites.

## Critical blockers

### P0 — committed credential material

A redacted signature scan found 18 high-confidence OpenAI-key-shaped occurrences in runtime
EchoMind source and its packaged copies, plus five occurrences in documentation/test files. The
runtime locations include:

- `modules/EchoMind/api_manager.py` and its packaged mirror;
- `modules/EchoMind/voice_transcription.py` and its packaged mirror;
- connection/error tests under `tests/code/echomind/`.

The strings are not marked as placeholders. They may already be expired, but committed secrets
must be treated as compromised until proved otherwise.

Required response:

1. Revoke or rotate every non-fixture credential outside Git.
2. Replace literals with runtime loading from an ignored local configuration or the existing
   secure settings/keyring layer.
3. Sanitize package mirrors and tests; use unmistakably fake fixture values.
4. Remove real values from Git history and any published artifacts.
5. Add automated secret scanning locally and in CI.

Never paste the values into an issue, report, commit message, test output, or chat.

### P0 — the test wrapper masks failure

`run_test.ps1` defines a `[switch]$Fast` parameter and later assigns the pytest result to `$fast`.
PowerShell variable names are case-insensitive, so a failing integer exit code cannot be assigned
to the switch parameter. The script emits a conversion error and, in the observed `-Fast` run,
returned process exit code 0 after pytest reported 61 failures and one collection error.

This invalidates the documented claim that the wrapper is the merge gate. Rename the result
variable (for example, `$fastExitCode`), make wrapper errors terminating, add a self-test that
uses an intentionally failing pytest target, and verify that every failing mode returns non-zero.

Until fixed, call pytest directly and trust the pytest process exit code.

## Test-baseline findings

The red suite is not caused primarily by the current Eagle Eye work. Most failing source areas are
unchanged from `HEAD`. Failure clusters include:

- download-manager socket payload keys, first-image prime, pagination, poor-connectivity, and
  tolerant decoding;
- CD Lite Viewer external-drop/import behavior;
- progressive local-search batch behavior;
- report assignment identity and status/report sorting guards;
- Nuitka ARM64 and release-parity guards;
- profile-switch restart expectations;
- one collection error importing `_INSTANCE_PAYLOAD_KEYS`.

Three xdist workers terminated improperly, and 187 cases were rerun. Ten quarantined tests passed,
so the quarantine register is also stale. The current quarantine files contain roughly 86 entries
across automatic and manual lists.

Recommended recovery sequence:

1. Fix the wrapper and add its exit-code guard first.
2. Run the direct suite serially by failing domain to distinguish real product drift from xdist
   teardown instability.
3. Repair the collection error, then release-parity and download-integrity failures.
4. Reconcile or remove obsolete guards only with code/history evidence; do not simply quarantine
   the 61 failures.
5. Regenerate and audit the quarantine register, then restore a reproducible full-suite baseline.

## Tooling and release readiness

### Working environment

- Runtime and build virtual environments resolve installed dependencies successfully.
- Python matches the package requirement (`>=3.13.5`).
- Software OpenGL fallback assets required by the build are present.

### Gaps

- Ruff is configured but not installed, and `requirements-dev.txt` does not include it. There is
  therefore no reproducible lint command in the documented development setup.
- Ruff targets Python 3.11 while the project requires Python 3.13.5; this should be made explicit
  and consistent.
- No GitHub Actions workflow exists. Tests, secret scans, lint, and packaging parity depend on
  local discipline only.
- The `external/itksnap` submodule is registered but uninitialized.
- Several runtime dependencies are only lower-bounded or unpinned, reducing build reproducibility.
- No configured dependency-vulnerability scanner was found.
- A broad test run mutates the tracked `module_package_feed.json`; tests should use a temporary
  output path and leave the worktree unchanged.

## Repository and documentation hygiene

- The worktree began with 32 modified and 40 untracked entries. They include active Eagle Eye,
  EchoMind, overlay, build-output, generated-data, documentation, and one-off analysis work.
  Do not reset or broadly format this checkout.
- Generated/runtime areas still contain hundreds of tracked files, and build output is mixed into
  the current diff. This makes reviews noisy and increases accidental-release risk.
- `README.md` advertises stable `v3.0.6`, while code and canonical release docs say `v3.6.3`.
- Architecture/KPI pages contain older version snapshots, and testing quickstarts substantially
  undercount the current suite.
- `CLAUDE.md` contains adjacent contradictory statements about whether quarantine uses strict or
  non-strict xfail. The actual test configuration must be made the single source of truth.
- Only nine TODO/FIXME-style comments were found in non-generated Python source; the debt is
  documented mostly in plans and quarantine rather than inline comments.

## Known product risks to retain in memory

The existing open-findings report identifies two unresolved performance risks:

- MPR activation blocks the GUI for roughly 4–5.5 seconds. Instrument all view creators and the
  volume build before choosing a fix, and keep any warmup strictly inside the MPR/VTK domain.
- Server-result population performs per-series filesystem status work on the GUI thread. Prefer an
  off-thread status calculation that preserves clinical freshness.

These are measurement-first items. Do not optimize them from sampled stack traces alone.

## Recommended development order

1. Credential incident response and secret-scanning guard.
2. Test-wrapper exit-code fix and a trustworthy direct baseline.
3. Repair collection, release-parity, and download-integrity failures by subsystem.
4. Add CI for secret scan, lint, focused tests, full code lane, and packaging parity.
5. Make lint/dependency tooling reproducible and initialize or explicitly retire the ITK-SNAP
   submodule.
6. Reconcile version/test documentation and generated-artifact policy.
7. Continue feature development in small guarded slices; the current Eagle Eye slice is locally
   healthy.

## Readiness decision

- **Targeted development:** yes, with direct subsystem tests and careful dirty-worktree handling.
- **Repository-wide regression confidence:** no.
- **Release build/publish:** no, until credentials and the test gate are fixed.
- **Live clinical validation:** not assessed in this audit.

