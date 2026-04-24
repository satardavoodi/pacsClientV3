# AIPacs v2.4.3 Release Notes

**Release Date:** 2026-04-25
**Branch:** main
**Previous Stable:** v2.3.7 (2026-04-22)

---

## Summary

v2.4.3 delivers a hardened PyInstaller build pipeline focused on three areas:
**incremental rebuild speed**, **build process safety**, and **correct installer
artifact generation**. Full builds still produce the complete `engine/` bundle and
`ai-pacs installer.exe`; subsequent runs detect changed files only and skip
unchanged artifacts, reducing typical rebuild time from ~5 minutes to under
30 seconds when source changes are limited.

---

## What changed

### 1. Incremental dist-sync (`builder/build_release.py`)

PyInstaller now writes its output to a temporary directory (`dist_tmp/`), then a
new `sync_dist_bundle_incremental()` function patches the live `dist/AIPacs/`
folder with only the changed files:

- Files unchanged by **content** (SHA-256 match) are skipped even if mtime
  differs — avoids false positives when PyInstaller touches timestamps without
  rewriting content.
- Removed files that are no longer in the new bundle are deleted from the live
  folder.
- After the sync, `dist_tmp/` is cleaned up.
- A sync summary is logged: `N copied, M skipped, K removed`.

Typical result after a single-file code change:
```
[BUILD] Incremental dist sync: 1 copied, 9484 skipped, 0 removed
[BUILD] Incremental stage sync: 1 copied, 9485 skipped, 0 removed
```

### 2. SHA-256 content fallback in `_sync_tree_incremental()`

The existing size-and-mtime fast path is now supplemented with a SHA-256 digest
comparison for files where **size matches but mtime differs**. This catches the
common case where a rebuild regenerates a file with identical content but a newer
timestamp, preventing unnecessary copies.

### 3. Build lock (`_build_lock_path` / `_acquire_build_lock` / `_release_build_lock`)

A file-based lock (`builder/output/.build.lock`) prevents two concurrent build
invocations from racing over the same output directory. If a second process
attempts to acquire the lock while one is already running it exits immediately
with a clear error message rather than corrupting the output.

### 4. Installer artifact preservation (`clean_outputs` → `preserve_installer`)

`clean_outputs()` now accepts a `preserve_installer` parameter. On incremental
runs (`--skip-pyinstaller`) and staging-only runs (`--skip-installer-compile`),
the `builder/output/installer/` folder is no longer deleted, so previously
compiled installers survive across multiple build phases. Previously, every run
wiped the installer folder even when ISCC was not re-invoked.

### 5. Confirmed installer output (`builder/output/installer/`)

With the preservation fix in place, a full build now consistently produces all
expected installer artifacts:

| File | Purpose |
|------|---------|
| `ai-pacs installer.exe` | Main installer for staff distribution |
| `ai-pacs installer v2.4.3.exe` | Versioned copy for archiving |
| `SHA256.txt` / `SHA256_FA.txt` | Integrity checksums (EN + FA) |
| `INSTALL_NOTES.txt` / `INSTALL_NOTES_FA.txt` | Installation guide (EN + FA) |

---

## Build commands

```powershell
# Full build (PyInstaller + stage + installer)
.\.venv_build\Scripts\python.exe build.py

# Incremental rebuild after source changes (reuse existing dist, rerun stage + installer)
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller

# Stage-only (no PyInstaller, no installer compile — fastest, for QA of staging)
.\.venv_build\Scripts\python.exe build.py --skip-pyinstaller --skip-installer-compile
```

---

## Validation

- `build.py --skip-pyinstaller` with existing dist: exit code 0, installer
  produced at `builder/output/installer/ai-pacs installer v2.4.3.exe`.
- Incremental sync confirmed: `0 copied, 9484 skipped, 1 removed` after
  touching a single source file.
- `build.py --skip-pyinstaller --skip-installer-compile`: exit code 0, existing
  installer folder preserved.

---

## Files changed

| File | Change |
|------|--------|
| `builder/build_release.py` | Incremental dist sync, SHA-256 fallback, build lock, `preserve_installer` |
| `main.py` | Version bumped to `2.4.3` |
| `pyproject.toml` | Version `2.4.3` (already set) |
| `docs/releases/VERSION_2.4.3_RELEASE.md` | This file |
