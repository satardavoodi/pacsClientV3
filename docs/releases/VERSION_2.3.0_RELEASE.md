# AIPacs Version 2.3.0 Release
**Date:** April 4, 2026
**Version:** 2.3.0
**Type:** Stable Release
**Status:** Published
**Tag:** `v2.3.0`

---

## Summary

Version **2.3.0** publishes the next stable AIPacs release after **v2.2.7** and aligns the application, package metadata, build metadata, plugin-package metadata, installer flow, and release documentation to the same release number.

## Included Version Updates

- `main.py` -> application version `2.3.0`
- `pyproject.toml` -> package version `2.3.0`
- `build_nuitka.py` -> Windows product version `2.3.0`
- `builder/plugin package/packages/module_package_feed.json` -> feed version `2.3.0`
- `builder/plugin package/packages/*/module_package.json` -> module versions `2.3.0`
- `README.md`, `docs/README.md`, and `docs/releases/RELEASE_NOTES.md` -> stable release references updated to `v2.3.0`
- `docs/modules/README.md`, `docs/pipelines/download-pipeline.md`, and architecture references -> aligned to the `2.3.0` install and module-delivery model
- Release build outputs under `builder/output/` -> regenerated for `2.3.0`
- Local backup snapshot under `backups/` -> created for `2.3.0`

## Intent

- Publish `2.3.0` as the current stable release
- Keep application, build, and package metadata synchronized
- Ship a Windows installer that can be used on other PCs with clear module-selection and GPU-preference steps
- Preserve a local backup and Git tag for release recovery

## Installer and Deployment Scope

`v2.3.0` is the release where the Windows installer is treated as the default cross-PC delivery path.

- `Core` setup keeps the workstation shell and basic modules available on every PC.
- `Custom` setup allows the installer operator to choose optional modules for that workstation.
- The installer stores those choices in `installation_profile.json`.
- First launch bootstraps the selected bundled packages automatically.
- GPU preference is suggested from an installer probe and confirmed again at runtime, with CPU-safe fallback when required.

## Notes

- The previous stable release remains documented in `docs/releases/VERSION_2.2.7_RELEASE.md`.
- Future development can continue from this tagged `v2.3.0` baseline.
