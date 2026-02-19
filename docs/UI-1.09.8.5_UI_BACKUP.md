# UI Backup: UI-1.09.8.5

**Date:** 2026-02-10  
**Tag:** `UI-1.09.8.5`  
**Scope:** UI-only changes (Settings, Sidebar, Viewer toolbars, Education module snapshot).  
**Important:** This backup intentionally **does not** include any DICOM files (`*.dcm`).

## What this backup contains

### 1) Workstation sidebar (Home panel left menu)
Files:
- `PacsClient/pacs/workstation_ui/AIPacs_ui.py`

Changes:
- Sidebar menu icons increased ~30% (22px → 29px) and button hit-target increased.
- When the menu button is clicked and the sidebar expands, each item now shows a visible label:
  - Home, Print, Settings, Download Manager, Web Browser, Educational Courses
  - Theme, Information, Get Help
- Theme / Information / Help now open the correct center-menu page (instead of just toggling visibility).
- Information page text updated to include the statement:
  - “This software is related to the AI Pacs company, which has been registered in the European Union for more than ten years.”

### 2) Title-bar “AI Pacs” logotype (text-based)
Files:
- `PacsClient/pacs/patient_tab/ui/patient_ui/custom_tab_manager.py`

Changes:
- Styled the title-bar `LogoButton` to behave like a text logotype (Roboto Black, letter spacing, gradient).
- **Fix:** Prevented the logotype from reverting to older sizes/styles when opening system tabs (Education, Download Manager, etc.).
  - Root cause was `set_logo_active()` re-applying an older stylesheet each time.
  - The logotype style is now a single source of truth and `set_logo_active()` only toggles the `active` property and repolishes.

### 3) Viewer toolbar “AI Pacs” header (text logotype)
Files:
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`

Changes:
- Replaced icon-style branding with a text-based logotype layout: “AI” accent + “Pacs” white.

### 4) Settings + Viewer UI readability scaling (fonts/icons)
Files (high-level):
- `PacsClient/pacs/workstation_ui/settings_ui/settings_ui.py` (Settings tab label font scaling)
- `PacsClient/pacs/workstation_ui/settings_ui/filter_config.py` (Image Filter accordion UI)
- `PacsClient/pacs/workstation_ui/settings_ui/lightviewer_settings.py` (Light Viewer fonts)
- `PacsClient/pacs/workstation_ui/home_ui/data_access_panel.py` (Server Selection fonts)
- `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py` (tool icons scaling)

Notes:
- Image Filter settings are organized into collapsible sections for lower clutter.
- Various fonts and icon sizes were increased for readability (per UI requests).

### 5) Education module snapshot
Directory snapshot:
- `PacsClient/pacs/education/`

This is a point-in-time snapshot for the Education section so it can be restored if later changes regress it.

## Where the backup is stored

A file snapshot is stored in:
- `backups/UI-1.09.8.5/`

This folder preserves a copy of the key UI source files and the Education module code.

## Restore instructions (manual)

To restore from this backup:
1. Copy the corresponding files from `backups/UI-1.09.8.5/` back into the project root, preserving paths.
2. Restart the application.

## Exclusions

- No DICOM files were backed up.
- Cache folders like `__pycache__` and `*.pyc` are excluded.
