# AIPacs v3.1.1 Release Notes

**Release date:** 2026-05-26
**Branch:** beta-version
**Previous stable:** v3.1.0

---

## Summary

v3.1.1 is a patch release on top of v3.1.0. It consolidates the final production
installer build, installer metadata, and minor stability refinements identified
during build verification.

All v3.1.0 codebase features are carried forward unchanged:
- Stable v3.0.9 core (multi-study viewer, crash hardening, EULA)
- Production-ready executables (687 MB Inno Setup installer)
- Crash-diagnostics tooling
- Release documentation and distribution manifests

---

## Version Alignment

The following canonical version markers are set to `3.1.1`:

- `pyproject.toml` -> `version = "3.1.1"`
- `main.py` -> `app.setApplicationVersion("3.1.1")`
- `docs/README.md` -> current stable `v3.1.1`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.1.1`
- `.github/copilot-instructions.md` -> current stable `v3.1.1`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Codebase

All v3.1.0 features carried forward unchanged:

- **Stable v3.0.9 core:** Multi-study viewer, thumbnail pipeline, database test
  isolation, Zeta Download Manager review, crash hardening, AI-PACS EULA
- **Production distributable:** 687 MB Inno Setup executable installer
- **Crash-diagnostics tooling:** faulthandler native-fault logging, diagnostic
  scripts, analysis documentation
- **Plugin packages:** download_manager, viewer, printing, advanced_mpr, echomind
  (optional payloads)

### Distributions

#### Core Executable Installer
- **File:** `builder/output/installer/ai-pacs installer v3.1.1.exe`
- **Size:** 687 MB (compressed)
- **Format:** Inno Setup 6 installer
- **Platform:** Windows (tested on Windows 11 Pro)
- **Content:** AIPacs.exe core + Advanced MPR runtime + plugin packages
- **Includes:** Crash hardening, all UI patches, EULA
- **Ready for:** Production deployment

#### Checksums and Metadata
- **SHA256:** (see `builder/output/installer/SHA256.txt`)
- **Installation notes:** `INSTALL_NOTES.txt` (English), `INSTALL_NOTES_FA.txt`
  (Farsi)
- **Versioned copy:** `ai-pacs installer.exe` (generic) and
  `ai-pacs installer v3.1.1.exe` (versioned archive)

#### Staged Outputs
- **Core bundle:** `builder/output/stage/core/AIPacs.exe` (23.4 MB, PyInstaller)
- **Plugin packages:** `builder/output/packages/` (all modules)
- **Update feed:** `builder/output/updates/update_feed.json`
- **Release manifest:** `builder/output/stage/manifest/release_manifest.json`

### License and Legal

- **AI-PACS End User License Agreement (EULA) v3.0.9**
  - Proprietary software license
  - Effective date: 2026-05-25
  - Clinical-use disclaimers, AI limitations, patient-data responsibility
  - Included in installer and LICENSE file at repo root

### Documentation

- `docs/releases/VERSION_3.1.1_RELEASE.md` (this file)
- `docs/releases/RELEASE_NOTES.md` (consolidated release history)
- `docs/releases/VERSION_3.1.0_RELEASE.md` (previous v3.1.0 notes)
- All prior audits, architecture, and troubleshooting docs available

---

## Publication

- All v3.1.0 codebase changes + version bump to 3.1.1 committed
- Tag `v3.1.1` created for release traceability
- Pushed to all three configured remotes:
  - `origin` → https://github.com/Vahid-INO/ai-pacs
  - `p2`     → https://github.com/satardavoodi/PacsClientV2
  - `satar`  → https://github.com/satardavoodi/pacsClientV3

---

## Installation Instructions

### Quick Start (End Users)

1. Download `ai-pacs installer v3.1.1.exe` (687 MB)
2. Verify SHA256: compare with `SHA256.txt`
3. Right-click installer → **Run as Administrator**
4. Follow wizard:
   - Choose setup type: **Core** (essential only) or **Custom** (select modules)
   - Review graphics acceleration detection (auto-probe or manual override)
   - Confirm installation path
5. Complete and launch
6. Verify in "About" → Application Version shows "3.1.1"

### Advanced / Deployment

- Installer supports silent mode (see `INSTALL_NOTES.txt`)
- `installation_profile.json` stores module choices and graphics preference
- Automatic upgrade/repair/downgrade handling for existing installations
- Optional modules can be customized per workstation

---

## Quality Gates / Verification

- ✅ Version markers aligned to 3.1.1 across all sources
- ✅ PyInstaller bundle: complete, all source files included
- ✅ Inno Setup: successful compile, 687 MB installer EXE
- ✅ SHA256 checksums: generated and ready for verification
- ✅ Crash hardening: faulthandler + native-fault logging enabled
- ✅ EULA: bundled in installer and source
- ✅ Documentation: full release notes and install instructions

---

## Known Items / Out of Scope

- Advanced MPR: optional payload, test separately on target systems
- Nuitka builder: experimental (PyInstaller used for releases)
- Installer exit code 1 on PrivilegesRequired: expected Inno Setup warning
  (installer itself is valid)
