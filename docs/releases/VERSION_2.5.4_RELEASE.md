# AIPacs v2.5.4 Release Notes
**Date**: May 12, 2026  
**Branch**: beta-version  
**Release Type**: Stable maintenance rollup

---

## Summary

v2.5.4 is a maintenance release that promotes the latest integrated FAST viewer and download-manager hardening updates to a stable version and aligns project documentation and version markers.

This release is intended for production handoff and end-user packaging.

---

## Included in v2.5.4

- FAST viewer interaction and progressive grow hardening updates currently in the beta-version branch
- Download manager and UI performance/robustness updates currently in the beta-version branch
- Documentation refresh and release metadata alignment
- Version bump from `2.5.3` to `2.5.4`

---

## Versioning Updates

- `pyproject.toml` -> `version = "2.5.4"`
- `docs/releases/RELEASE_NOTES.md` -> current stable set to `v2.5.4`
- `.github/copilot-instructions.md` -> current stable set to `v2.5.4`

---

## Build and Distribution

This release is intended to be built via the PyInstaller release pipeline from the project root/builder flow and delivered as an executable + installer for end users.

### Build System Improvements (v2.5.4)

- **PyInstaller Version Auto-Detection**: Build system now detects and enforces PyInstaller version consistency between build and development environments. Mixed versions are automatically corrected via clean-build forcing. See [BUILD_PYINSTALLER_VERSIONING.md](../architecture/BUILD_PYINSTALLER_VERSIONING.md) for details.
- **Installer Artifact Cleanup**: Old timestamp build artifacts are automatically cleaned up to reduce folder size and remove ambiguity about the deliverable file.
- **Installer File Lock Hardening**: Unique compile-time basenames prevent ISCC.exe from locking previous builds during incremental pipelines.

---

## Upgrading to v2.5.4

### For End Users

Simply download and run the installer (`ai-pacs installer.exe`). The versioned copy `ai-pacs installer v2.5.4.exe` is identical and is provided for release tracking.

### For Multi-PC Deployments / Build Environments

If building v2.5.4 on multiple machines:

1. Ensure both `.venv_build` and `.venv` have the **same PyInstaller version**
2. If you see `[WARN] PyInstaller cache version mismatch detected`, the build system will automatically correct it (via clean-build)
3. See [BUILD_PYINSTALLER_VERSIONING.md](../architecture/BUILD_PYINSTALLER_VERSIONING.md) for diagnosis and prevention

---

## Notes

- Previous stable: `v2.5.3`
- This release tag: `v2.5.4`
