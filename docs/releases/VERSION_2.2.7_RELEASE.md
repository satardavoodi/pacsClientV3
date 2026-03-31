# AIPacs Version 2.2.7 Release
**Date:** March 31, 2026
**Version:** 2.2.7
**Type:** Stable Release / Build, Installer, and Documentation Refresh
**Status:** Stable snapshot prepared for backup and GitHub publication
**Tag:** `v2.2.7`

---

## Summary

Version **2.2.7** captures the current stable workspace and refreshes the release-facing build, installer, and documentation surfaces so the local backup, staged output, and GitHub state all match the same stable line.

## Included Release Updates

- `main.py` -> application version `2.2.7`
- `pyproject.toml` -> package version `2.2.7`
- `build_nuitka.py` -> Windows product version `2.2.7`
- `builder/plugin package/packages/module_package_feed.json` -> feed version `2.2.7`
- `builder/plugin package/packages/*/module_package.json` -> module versions `2.2.7`
- `setup_env.ps1` -> runtime-first setup flow with optional `-IncludeDev`
- `builder/scripts/_common.ps1` -> build dependency install aligned with `requirements-core.txt`
- `builder/build_release.py` -> installer notes and SHA256 metadata generated per release run
- `build.bat`, `README.md`, and active docs -> install/build/release instructions refreshed for this stable version

## Install and Build Notes

- Runtime setup now defaults to `requirements-core.txt`
- Developer setup can be enabled with `.\setup_env.ps1 -IncludeDev`
- Release builds should use `builder/requirements/build_requirements.txt` plus `requirements-core.txt`
- Successful installer builds now regenerate `INSTALL_NOTES*.txt` and `SHA256*.txt` in `builder/output/installer/`
- Legacy `requirements.txt` remains a fallback path for older tooling, but it is no longer the primary setup path

## Release Intent

- Save the current stable codebase as release `v2.2.7`
- Create a local backup artifact before publication
- Commit and push the refreshed stable snapshot to the configured Git remotes without rewriting the existing `v2.2.7` tag

## Notes

- This release is intended to represent the current stable working tree rather than a narrow single-feature change.
- The consolidated release history continues in `docs/releases/RELEASE_NOTES.md`.
