# AIPacs v3.1.0 Release Notes

**Release date:** 2026-05-25
**Branch:** beta-version
**Previous stable:** v3.0.9

---

## Summary

v3.1.0 is a release-packaging checkpoint. It stabilizes the v3.0.9 codebase
(all workspace fixes, crash hardening, EULA) and pairs it with production
installers (687 MB Inno Setup `.exe`), full crash-diagnostics tooling, and
ready-to-distribute plugin packages and update feeds.

This release is distribution-ready: the core codebase, all intermediate modules,
installation artifacts, checksums, and legal documentation are versioned,
tested, and ready for deployment across all three mirrored remotes.

---

## Version Alignment

The following canonical version markers are set to `3.1.0`:

- `pyproject.toml` -> `version = "3.1.0"`
- `main.py` -> `app.setApplicationVersion("3.1.0")`
- `docs/README.md` -> current stable `v3.1.0`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.0`
- `.github/copilot-instructions.md` -> current stable `v3.1.0`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Codebase

All v3.0.9 features carried forward:

- **Multi-study viewer fix** (single-tab grouped sidebar, offset-keyed series,
  repaint-suppressed rebuild) — `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md`
- **Thumbnail pipeline** (canonicalized disk path, DB hint-only columns,
  ThumbnailImageSourceService + disk fallback) —
  `docs/pipelines/thumbnail-pipeline.md`
- **Database test isolation** (production `dicom.db` cleanup tooling, test
  redirection to correct pool) — `COPILOT_REPORT_db_cleanup.md`,
  `tools/maintenance/cleanup_test_pollution.py`
- **Zeta Download Manager** (atomic writes, single GetStudyInfo probe,
  dead-gRPC quarantine) —
  `docs/plans/performance/ZETA_DOWNLOAD_MANAGER_REVIEW_AND_FIX_PLAN_2026-05-24.md`
- **Crash hardening** (`faulthandler` native-fault logging, viewer/UI stability
  patches, crash-diagnostics tooling) — `CRASH_ANALYSIS_2026-05-25.md`,
  `crash-diagnostics/`

### Distributions

#### Core Executable Installer
- **File:** `builder/output/installer/ai-pacs installer v3.1.0.exe`
- **Size:** 687 MB (compressed)
- **Format:** Inno Setup 6 installer
- **Platform:** Windows (tested on Windows 11 Pro)
- **Content:** AIPacs.exe core bundle + Advanced MPR runtime + plugin packages
- **Includes:** faulthandler native-fault logging, crash hardening, all UI patches
- **Ready for:** Production deployment, end-user installation, multi-workstation rollout

#### Checksums and Metadata
- **SHA256:** (see `builder/output/installer/SHA256.txt`)
- **Installation notes:** `INSTALL_NOTES.txt` (English), `INSTALL_NOTES_FA.txt` (Farsi)
- **Versioned copy:** `ai-pacs installer.exe` (generic) and `ai-pacs installer v3.1.0.exe`
  (versioned for archive/tracking)

#### Staged Outputs (Artifacts)
- **Core bundle:** `builder/output/stage/core/AIPacs.exe` (23.4 MB, PyInstaller
  compiled executable)
- **Plugin packages:** `builder/output/packages/` (download_manager, viewer,
  printing, advanced_mpr, echomind)
- **Update feed:** `builder/output/updates/update_feed.json` (manifest for live
  module updates)
- **Release manifest:** `builder/output/stage/manifest/release_manifest.json`
  (plugin status, optional payloads, version record)

### License and Legal

- **AI-PACS End User License Agreement (EULA) v3.0.9**
  - Proprietary software license
  - Effective date: 2026-05-25
  - Covers clinical use, AI limitations, patient-data responsibility,
    export control
  - Replaces MIT template
  - Included in installer and `LICENSE` file at repo root

### Documentation Added/Updated

- `docs/releases/VERSION_3.1.0_RELEASE.md` (this file)
- `docs/releases/RELEASE_NOTES.md` (consolidated release history)
- `docs/releases/VERSION_3.0.9_RELEASE.md` (previous stable notes)
- All prior audits, plans, and architecture docs from v3.0.9 carried forward

---

## Publication

- All v3.0.9 codebase changes + version bump to 3.1.0 committed
- Tag `v3.1.0` created for release traceability
- Pushed to all three configured remotes:
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3

---

## Installation Instructions

### End User / IT Staff

1. Download `ai-pacs installer v3.1.0.exe` (687 MB)
2. Verify SHA256 against `SHA256.txt`
3. Right-click installer → Run as Administrator
4. Follow setup wizard:
   - Choose installation type (Core or Custom with optional modules)
   - Review graphics acceleration probe (automatic or manual override)
   - Confirm installation folder
5. Complete wizard and launch AIPacs
6. Verify in "About" → Application Version should show "3.1.0"

### Advanced Setup / Deployment

- Installer supports silent mode (see `INSTALL_NOTES.txt` for command-line flags)
- `installation_profile.json` records the modules and graphics mode chosen
- Previous version detection and upgrade/repair/downgrade handling built-in
- Optional modules (Advanced MPR, EchoMind, etc.) can be selected per workstation

---

## Quality Gates

- ✅ PyInstaller bundle: successful compile, all source files included
- ✅ Inno Setup: successful installer compile, 687 MB archive
- ✅ SHA256 checksums: generated and verified
- ✅ FAST viewer: crash hardening + memory stability patches
- ✅ Home panel: UI fixes and thumbnails pipeline integration
- ✅ Crash diagnostics: faulthandler logging enabled, native-fault tracing ready
- ✅ License: AI-PACS EULA baked into installer and source repo

---

## Known Issues / Not in Scope for v3.1.0

- Advanced MPR module: optional payload (test separately on target systems)
- Nuitka builder: legacy PyInstaller build used; Nuitka workflow in `builder nuitka/`
  remains experimental
- Installer exit code 1 on PrivilegesRequired: known Inno Setup false alarm (installer
  is valid)
