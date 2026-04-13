# AIPacs Version 2.3.3 Release
**Date:** April 14, 2026
**Version:** 2.3.3
**Type:** Stable Release
**Status:** Published
**Tag:** `v2.3.3`

---

## Summary

Version **2.3.3** publishes the current AIPacs workspace and aligns the app,
package, build, installer, update-feed, and release documentation metadata to
the same release number.

## Included Version Updates

- `main.py` -> application version `2.3.3`
- `pyproject.toml` -> package version `2.3.3`
- `build_nuitka.py` -> Windows product version `2.3.3`
- `builder/plugin package/packages/module_package_feed.json` -> feed version `2.3.3`
- `builder/plugin package/packages/*/module_package.json` -> module versions `2.3.3`
- `README.md`, `docs/README.md`, and `docs/releases/RELEASE_NOTES.md` -> current stable release references updated to `v2.3.3`
- `builder/docs/WINDOWS_RELEASE_FLOW.md` and `builder/docs/INSTALLER_QA_CHECKLIST.md` -> build/install publication target refreshed for `v2.3.3`
- Current docs, tests, and active plan documents included with the published workspace

## Intent

- Publish `2.3.3` as the current stable workspace version
- Keep application, build, package, and update metadata synchronized
- Keep installer/build instructions aligned with the current release target
- Preserve the current documentation, tests, and planning artifacts in GitHub

## Installer and Deployment Scope

`v2.3.3` continues the installer-first delivery model for cross-PC deployment.

- `Core` setup keeps the workstation shell and basic modules available on every PC.
- `Custom` setup allows the installer operator to choose optional modules for that workstation.
- The installer stores those choices in `installation_profile.json`.
- First launch bootstraps the selected bundled packages automatically.
- GPU preference is suggested from an installer probe and confirmed again at runtime, with CPU-safe fallback when required.

## Notes

- The previous stable releases remain documented in `docs/releases/`.
- This release note records the repository publication state. Rebuilt installer or update artifacts should be validated from the current workspace before shipping binaries externally.
