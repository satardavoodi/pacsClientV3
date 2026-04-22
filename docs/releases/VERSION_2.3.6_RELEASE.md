# AIPacs Version 2.3.6 Release
**Date:** April 20, 2026
**Version:** 2.3.6
**Type:** Stable Release
**Status:** Published
**Tag:** `v2.3.6`

---

## Summary

Version **2.3.6** promotes the current repository state to the next stable
checkpoint and synchronizes the release metadata for publication to both GitHub
repositories.

## Included Version Updates

- `main.py` -> application version `2.3.6`
- `pyproject.toml` -> package version `2.3.6`
- `build_nuitka.py` -> Windows product version `2.3.6`
- `builder/plugin package/packages/module_package_feed.json` -> feed version `2.3.6`
- `builder/plugin package/packages/*/module_package.json` -> module versions `2.3.6`
- `README.md`, `docs/README.md`, and `docs/releases/RELEASE_NOTES.md` -> current stable release references updated to `v2.3.6`
- `builder/docs/WINDOWS_RELEASE_FLOW.md` and `builder/docs/INSTALLER_QA_CHECKLIST.md` -> build/install publication target refreshed for `v2.3.6`
- `.github/copilot-instructions.md` -> current stable marker and local backup path refreshed for the new checkpoint

## Intent

- Publish `2.3.6` as the current stable workspace version
- Keep application, build, package, and release metadata synchronized
- Prepare the workspace for Git tag `v2.3.6` and GitHub sync to both configured remotes

## Validation

- Version metadata updated consistently across app, builder, package, and release docs
- Repository prepared for publication from the current workspace state

## Notes

- Earlier stable releases remain documented in `docs/releases/`.
- This release note records the repository publication state for the `v2.3.6` checkpoint; external binary artifacts should still be rebuilt and validated from the current workspace before distribution.
