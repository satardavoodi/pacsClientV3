# AIPacs Version 2.2.2

**Release date:** 2026-02-19
**Branch:** `DR.vahid`
**Type:** Portability + path refactor release

## Summary

This release finalizes dynamic path handling so the project can be cloned and run on different machines without machine-specific path breakage.

## Key changes

- Replaced hardcoded local filesystem paths with dynamic/project-relative resolution in runtime and launcher scripts.
- Updated launcher path discovery to support environment-driven and relative lookup.
- Removed machine-specific defaults from import/open helpers.
- Set app version to `2.2.2` in `main.py`.
- Updated project instructions version metadata to `v2.2.2 (2026-02-19)`.
- Updated `.gitignore` to avoid accidentally excluding required config/doc artifacts.

## Verification checklist

- Runtime source files scanned for absolute machine paths (`C:\...`, `/Users/...`) in active code paths.
- No local absolute path reintroduced in updated portability files.
- All modified files prepared for commit and push.

## Notes

If custom local binaries are needed (for example, custom Slicer/Qt builds), use environment variables instead of hardcoded paths:

- `AIPACS_ADVANCED_VIEWER_EXE`
- `AIPACS_SLICER_BUILD_DIR`
- `AIPACS_QT_BIN` / `QT_BIN_DIR` / `QTDIR` / `Qt5_DIR`
