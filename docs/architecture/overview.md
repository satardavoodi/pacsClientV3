# Architecture Overview

## Purpose

AIPacs is a desktop DICOM workstation composed of a workstation shell plus several semi-independent modules:

- fast viewer
- advanced viewer
- download manager
- MPR and advanced imaging
- education
- web viewing
- printing
- EchoMind assistant

The current architecture is serviceable, but the repository had drifted away from a clean separation between runtime code, historical notes, and generated artifacts. This document describes the cleaned-up structure as it exists now.

## System Layers

### Presentation Layer

- `main.py`
- `PacsClient/app_handler.py`
- `PacsClient/pacs/workstation_ui/`
- `PacsClient/pacs/patient_tab/ui/`
- `printing/ui/`

This layer owns Qt widgets, tab management, user actions, and view composition.

### Application and Orchestration Layer

- `PacsClient/components/`
- `PacsClient/zeta_download_manager/`
- `EchoMind/secretary/`
- `printing/data/`

This layer coordinates workflows, turns UI actions into tasks, and mediates access to database and filesystem resources.

### Imaging and Domain Layer

- `PacsClient/pacs/patient_tab/viewers/`
- `PacsClient/pacs/patient_tab/orthogonal_mpr/`
- `PacsClient/pacs/patient_tab/zeta mpr/`
- `PacsClient/pacs/patient_tab/zeta_boost/`
- `PacsClient/pacs/patient_tab/zeta_sync/`
- `printing/render/`

This layer contains DICOM viewing, rendering, image transformation, sync, and printing logic.

### Infrastructure Layer

- `PacsClient/utils/database.py`
- `PacsClient/utils/db_manager.py`
- `config/`
- `database/`
- `generated-files/`
- `logs/`

This layer handles persistence, configuration, diagnostics, migrations, and local runtime state.

## Module Catalog

### Viewer Modules

- Fast viewer: `lightweight_2d_pipeline.py` and related pydicom backends
- Advanced viewer: `viewer_2d.py`, advanced rendering helpers, AI overlays, and heavy viewer controllers
- Orthogonal MPR: `orthogonal_mpr/`
- Zeta MPR: `zeta mpr/`

The practical rule is:

- use the fast viewer for lightweight browsing and download-time interaction
- use the advanced viewer and MPR stack for richer tools, measurements, and reconstruction workflows

### Download and Cache Modules

- `PacsClient/zeta_download_manager/`
- `PacsClient/pacs/patient_tab/zeta_boost/`
- thumbnail and study caches under `generated-files/`, `thumbnails/`, and database-backed state

Download orchestration, progress tracking, resumability, and warmup caching are concentrated here.

### Education Module

- UI integration under `PacsClient/pacs/education/`
- persistent course content under `Education/`
- static assets under `education_assets/`

### Web Viewing Module

- `PacsClient/pacs/workstation_ui/web_browser_ui.py`

This module is part of the workstation shell rather than a separate package.

### Printing Module

- `printing/ui/`
- `printing/render/`
- `printing/printers/`
- `printing/data/`

The missing data-access layer has now been restored so the printing UI does not depend on absent imports.

### EchoMind and Secretary

- `EchoMind/`
- `EchoMind/secretary/`

This module owns conversational AI, routing, module selection, and assistant execution plans.

## Database and Cache Responsibilities

### Database

- Primary local database: `dicom.db`
- schema and low-level connection logic: `PacsClient/utils/database.py`
- query helpers and migration-style helpers: `PacsClient/utils/db_manager.py`
- operational scripts: `database/`

The database stores the DICOM hierarchy, download state, filming metadata, reception reports, and AI-related session data.

### Cache and Local Storage

- image thumbnails: `thumbnails/`
- attachments and filming output: `attachment/`
- generated logs and temp outputs: `generated-files/`
- viewer warmup and boosted image caching: `PacsClient/pacs/patient_tab/zeta_boost/`

The repository previously mixed cache discussions across many notes; these responsibilities are now documented centrally here.

## Current Integration Path

The standard module-to-data path should be:

1. UI widget triggers an action.
2. Application layer validates state and selects the correct service or repository.
3. Repository or service talks to the database or filesystem.
4. Domain layer renders or processes DICOM data.
5. UI updates through the owning widget, not through direct cross-module state mutation.

## Active Architectural Risks

- `PacsClient.utils` is still acting as a broad re-export hub. That makes imports convenient but increases coupling and import-order risk.
- `PacsClient/pacs/patient_tab/zeta mpr/` still uses a space in the directory name, forcing dynamic import workarounds.
- Several very large UI/controller files still carry too many responsibilities.
- Historical notes inside packages are inconsistent in encoding and freshness.

## Recommended Next Refactors

1. Split large UI controllers into presentation, services, and repositories.
2. Replace broad `PacsClient.utils` imports with direct module imports over time.
3. Rename `zeta mpr/` to `zeta_mpr/` only when imports and packaging can be migrated safely.
4. Expand targeted tests around printing, database repositories, and module orchestration.
