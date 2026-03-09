# Documentation Guide

This directory is now the canonical entrypoint for project documentation.

## Start Here

- [Architecture Overview](architecture/overview.md): system layers, module boundaries, database and cache responsibilities
- [Repository Layout](architecture/repository-layout.md): standardized folder responsibilities
- [Module Catalog](modules/README.md): active workstation modules and local implementation docs
- [Development Setup](development/setup-and-tooling.md): dependencies, tooling, and day-to-day commands
- [Release Notes](releases/RELEASE_NOTES.md): current consolidated release status

## Documentation Rules

- `docs/architecture/`: source-of-truth architecture and structure docs
- `docs/modules/`: active module catalog and integration notes
- `docs/development/`: setup, tooling, and contributor workflow
- `docs/releases/`: current release notes and version history
- `docs/archive/`: historical documents that may reference old code, old paths, or superseded designs

## What Changed

- Root-level documentation was reduced to a single `README.md`.
- Legacy module framework notes and one-off implementation guides were moved into `docs/archive/`.
- Current architecture is documented against the code that exists now, not older delivery snapshots.

## Known Documentation Debt

- Some package-local notes still contain mojibake or time-bound implementation details.
- `PacsClient/pacs/patient_tab/zeta mpr/` still uses a folder name with a space because the runtime currently relies on dynamic imports there.
- A future pass should convert surviving package-local notes to UTF-8-clean ASCII where possible.
