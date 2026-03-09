# Repository Layout

## Standardized Top-Level Structure

### Runtime Code

- `PacsClient/`: workstation shell, PACS UI, viewer stack, download integration, shared utilities
- `EchoMind/`: AI assistant and secretary subsystem
- `printing/`: filming, rendering, printer integrations, and printing repositories

### Runtime Configuration and Data Contracts

- `config/`: editable runtime configuration
- `database/`: schema maintenance scripts and report storage helpers

### Documentation

- `docs/`: canonical project documentation
- `docs/archive/`: superseded release notes, guides, and delivery snapshots
- `builder/docs/`: builder-specific operational documentation

### Build and Packaging

- `builder/`
- `hooks/`
- `AIPacs.spec`
- build scripts in the repository root

### Tests

- `tests/`: repository-level automated tests
- `EchoMind/secretary/tests/`: module-local tests kept near the secretary package

### Generated or Local Runtime Output

- `generated-files/`
- `logs/`
- `thumbnails/`
- `attachment/`
- `source/`

These paths should stay out of the architectural source tree and remain ignored or treated as runtime state.

## Directory Ownership

### `PacsClient/`

Use for workstation functionality that is part of the main desktop app:

- authentication and shell
- PACS tabs and viewers
- download manager adapters
- shared services and database helpers

### `EchoMind/`

Use for assistant-specific runtime code, prompts, and orchestration. Do not mix EchoMind-specific contracts into generic workstation utilities without a clear shared API.

### `printing/`

Use for printing-only concerns:

- `core/`: print models and validation
- `data/`: study and series repositories for printing
- `render/`: DICOM to film rendering
- `printers/`: OS and DICOM print backends
- `ui/`: printing widgets

### `docs/`

Use for stable, maintained project documentation only. Time-bound investigation notes should be archived or clearly marked.

## Folder Rules

- Keep historical release documents out of the repository root.
- Keep generated runtime outputs out of package directories.
- Prefer module-local `README.md` files only when they explain a specific package that the main docs link to.
- Add new data-access code in dedicated repository modules instead of directly inside UI widgets.
- Add new tests under `tests/` unless they are tightly coupled to a single package and easier to keep local.

## Current Exceptions

- `PacsClient/pacs/patient_tab/zeta mpr/` retains its legacy name because the application currently uses dynamic imports against that path.
- `Education/` stores end-user content rather than source code, so it remains separate from `PacsClient/pacs/education/`.
