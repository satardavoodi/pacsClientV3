# AIPacs Version 2.3.4 Release
**Date:** April 18, 2026
**Version:** 2.3.4
**Type:** Stable Release
**Status:** Published
**Tag:** `v2.3.4`

---

## Summary

Version **2.3.4** publishes the current AIPacs workspace and promotes the FAST
viewer protected-UI deadlock fix to the new stable checkpoint.

## Included Version Updates

- `main.py` -> application version `2.3.4`
- `pyproject.toml` -> package version `2.3.4`
- `build_nuitka.py` -> Windows product version `2.3.4`
- `builder/plugin package/packages/module_package_feed.json` -> feed version `2.3.4`
- `builder/plugin package/packages/*/module_package.json` -> module versions `2.3.4`
- `README.md`, `docs/README.md`, and `docs/releases/RELEASE_NOTES.md` -> current stable release references updated to `v2.3.4`
- `builder/docs/WINDOWS_RELEASE_FLOW.md` and `builder/docs/INSTALLER_QA_CHECKLIST.md` -> build/install publication target refreshed for `v2.3.4`

## Functional Fix in This Release

- Fixed a protected-UI self-deadlock in `modules/viewer/fast/system_load_controller.py`
- The deadlock was triggered when repeated `PREFETCH` admissions for the same
  series key were deferred while the controller was in protected-UI mode due to
  high UI lag
- The failure surfaced as a second FAST viewer startup stall/crash after the
  first series had already loaded in the layout
- Added a regression test to ensure deferred prefetch admissions return cleanly
  without deadlocking

## Intent

- Publish `2.3.4` as the current stable workspace version
- Preserve the FAST second-viewer startup fix as a named rollback point
- Keep application, build, package, and update metadata synchronized
- Keep installer/build instructions aligned with the current release target

## Validation

- `python -m pytest tests/viewer/test_system_load_controller.py -q`
  - **21 passed**
- Offscreen two-viewer FAST startup repro
  - series `4` loaded in viewer 1
  - series `7` loaded in viewer 2
  - second viewer completed `set_slice(mid)` and `apply_default_window_level(mid)` successfully

## Notes

- The previous stable releases remain documented in `docs/releases/`.
- This release note records the repository publication state. Rebuilt installer
  or update artifacts should be validated from the current workspace before
  shipping binaries externally.