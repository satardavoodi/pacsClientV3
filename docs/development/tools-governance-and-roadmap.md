# Tools Governance and Roadmap

This document defines rules and a practical improvement plan for `tools/` so scripts remain discoverable, safe, and maintainable as the repository grows.

## Purpose

- Keep utility scripts easy to find.
- Prevent path breakage during refactors.
- Standardize quality and lifecycle expectations.
- Reduce "temporary script" sprawl over time.

## Scope

Applies to everything under:

- `tools/dev/`
- `tools/diagnostics/`
- `tools/git/`
- `tools/performance/`
- `tools/slicer/`
- `tools/vtk/`

## Folder Ownership Rules

Use the folder that matches the script's **primary purpose**:

- `tools/diagnostics/` — investigation and troubleshooting scripts, diagnostic notebooks, captured output snapshots.
- `tools/performance/` — benchmark runners, instrumentation, and performance analysis.
- `tools/slicer/` — Slicer runtime setup, verification, and integration helpers.
- `tools/git/` — Git/GitHub workflow automation and connectivity checks.
- `tools/vtk/` — VTK comparison artifacts, merge scratch files, local experimentation.
- `tools/dev/` — temporary or migration helpers used by developers.

If a script has mixed responsibilities, either:

1. Split it into two scripts in separate folders, or
2. Keep it where most of the behavior belongs and clearly document cross-domain behavior in the header.

## Naming and Metadata Standards

### File naming

- Use descriptive names by default (for example, `verify_slicer_build.py`).
- Prefix with `_` only for intentionally temporary or internal-only utilities.
- For one-off diagnostics that should be retained, include context in the filename (for example, patient/study IDs or ticket IDs).

### Required script header (Python)

Every new Python tool script should include:

- Short purpose statement
- Expected inputs/arguments
- Side effects (DB writes, file deletion, network calls)
- Safe execution mode (dry-run support when applicable)
- Owner/contact (team or module)

## Path and Portability Rules

- Never hardcode machine-specific absolute paths.
- Resolve repository root from `__file__` and parent directories.
- Prefer project-relative paths from computed repo root.
- Keep Windows compatibility first, but avoid shell assumptions where possible.

## Safety Rules

For scripts that modify data/files:

- Provide a `--dry-run` option when feasible.
- Require explicit confirmation for destructive operations unless running in CI.
- Log what will be changed before change execution.
- Write outputs to predictable locations under `tools/` or `generated-files/`.

For DB-impacting diagnostics:

- Default to read-only behavior.
- If mutation is required, add explicit "write mode" flag and warning banner.

## Task Integration Rules

When exposing a script through VS Code tasks:

- Add/update the matching entry in `.vscode/tasks.json`.
- Keep task labels clear and action-oriented.
- If the script moved, update all task and documentation references in the same change.

## Lifecycle Management

Classify each script as one of:

- **Stable**: actively used and documented.
- **Experimental**: valid but under iteration.
- **Temporary**: short-lived helper; candidate for deletion.
- **Archived**: historical artifact kept only for traceability.

Minimum lifecycle expectations:

- Review `tools/dev/` monthly.
- Delete or promote temporary scripts after validation.
- Move historical outputs to clearly named diagnostic snapshots.

## Quality Checklist for New or Moved Tools

Before merge, verify:

1. Script is in the right folder.
2. No absolute local path remains.
3. Existing tasks/docs references are updated.
4. Basic usage notes exist (in-script or folder README).
5. Destructive actions are guarded.

## 90-Day Improvement Plan

### Phase 1 (Week 1-2): Baseline and hygiene

- Add this governance doc and keep `tools/README.md` as quick map.
- Tag existing scripts by lifecycle class.
- Identify scripts with unclear ownership or no longer used.

### Phase 2 (Week 3-6): Standardization

- Rename cryptic temporary files to descriptive names where appropriate.
- Add argument parsing (`argparse`) to scripts currently requiring manual edits.
- Add dry-run mode to destructive scripts.

### Phase 3 (Week 7-10): Reliability

- Add lightweight smoke checks for critical scripts.
- Add a CI lint step for `tools/**/*.py` (syntax + import sanity).
- Ensure every VS Code task points to current script paths.

### Phase 4 (Week 11-13): Consolidation

- Retire stale temporary scripts.
- Archive old diagnostic outputs with timestamps and context.
- Publish a short quarterly tools health summary in `docs/development/`.

## Proposed Success Metrics

- 0 broken task paths after script moves.
- 100% of destructive scripts provide safe preview or confirmation.
- Reduced count of ambiguous `_temp_*` scripts quarter-over-quarter.
- Faster onboarding: new contributor can locate the right tool folder in under 2 minutes.

## Maintenance Responsibility

- Primary maintainers: module owners for scripts in their domain.
- Cross-cutting enforcement: reviewers of build/tooling changes.
- Any script move PR must include path-reference verification.

## Related Documents

- `tools/README.md`
- `docs/development/setup-and-tooling.md`
- `docs/performance/CROSS_PC_IMPROVEMENT_WORKFLOW.md`
