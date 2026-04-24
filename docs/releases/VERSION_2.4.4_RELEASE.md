# v2.4.4 - Nuitka Pipeline Sync After Docs Reorganization (2026-04-25)

## Summary

This release captures the post-pull synchronization of the staged Nuitka build work after repository documentation reorganization.

## Included Changes

- Pulled latest upstream `main` updates that reorganized documentation structure and updated Python build flow under `builder/`.
- Confirmed Nuitka canonical plan remains in `builder/docs/NUITKA_BUILD_PLAN.md`.
- Added operator/agent handoff document to canonical build docs:
  - `builder/docs/NUITKA_BUILD_AGENT_HANDOFF.md`
- Updated build docs index (`builder/docs/README.md`) to include both Nuitka docs.
- Preserved separation of build systems:
  - PyInstaller flow in `builder/`
  - Nuitka staged/resumable flow in `builder nuitka/`

## Notes For Next Build

- Use `builder/docs/NUITKA_BUILD_PLAN.md` for canonical pipeline commands and stage behavior.
- Use `builder/docs/NUITKA_BUILD_AGENT_HANDOFF.md` for operational continuity and quick recovery guidance.
- Keep all Nuitka artifacts under `builder nuitka/output/`.

## Validation

- Documentation paths align with the new repository organization.
- No PyInstaller build scripts were modified in this release.
