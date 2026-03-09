# Module Catalog

## Active Modules

| Module | Purpose | Primary Code | Notes |
| --- | --- | --- | --- |
| Workstation shell | Main PACS desktop shell, auth, settings, home tab | `PacsClient/app_handler.py`, `PacsClient/pacs/workstation_ui/` | Entry from `main.py` |
| Viewer, fast | Lightweight 2D viewing path for responsiveness | `PacsClient/pacs/patient_tab/viewers/lightweight_2d_pipeline.py` | Optimized for software rendering and active download cases |
| Viewer, advanced | Full viewer path with richer tools and overlays | `PacsClient/pacs/patient_tab/viewers/viewer_2d.py` | Backed by `viewers/backends/` |
| Zeta Download Manager | Download queueing, resumability, progress, worker orchestration | `PacsClient/zeta_download_manager/` | Local guide: `PacsClient/zeta_download_manager/ZETA_DOWNLOAD_MANAGER_IMPLEMENTATION_GUIDE.md` |
| Zeta MPR | Advanced MPR implementation | `PacsClient/pacs/patient_tab/zeta mpr/` | Local guide: `PacsClient/pacs/patient_tab/zeta mpr/README.md` |
| Orthogonal MPR | Focused orthogonal MPR widget and helpers | `PacsClient/pacs/patient_tab/orthogonal_mpr/` | Used alongside toolbar workflows |
| Advanced imaging and AI | Imaging tabs, service tabs, analysis workflows | `PacsClient/pacs/patient_tab/ui/ai_module_ui/` | Includes service-driven imaging workflows |
| Education | Course browsing and educational case workflows | `PacsClient/pacs/education/`, `Education/` | Static assets in `education_assets/` |
| Web viewing | Embedded browser or web tab | `PacsClient/pacs/workstation_ui/web_browser_ui.py` | Integrated into workstation UI |
| Printing | Film layout, DICOM rendering, print dispatch | `printing/` | Data layer restored under `printing/data/` |
| EchoMind | AI chat, assistant orchestration, secretary routing | `EchoMind/` | Secretary docs under `EchoMind/secretary/` |

## Supporting Layers

### Database

- connection and schema management: `PacsClient/utils/database.py`
- higher-level query helpers: `PacsClient/utils/db_manager.py`
- scripts and migration helpers: `database/`

### Cache and Storage

- thumbnails: `thumbnails/`
- attachments and filming pages: `attachment/`
- generated performance output: `generated-files/`
- boosted viewer cache logic: `PacsClient/pacs/patient_tab/zeta_boost/`

## Module-to-Database Contract

The expected dependency direction is:

1. module UI
2. module application service or repository
3. database or filesystem
4. render or business logic output back to UI

Direct UI-to-database code still exists in older areas, but new work should prefer repository-style modules like `printing/data/`.

## Local Documentation Policy

- Keep package-local docs only when they explain a package that is independently complex.
- Prefer linking local docs from this catalog instead of duplicating architecture notes in multiple places.
- Archive time-bound investigation notes under `docs/archive/` when they stop being operationally useful.
