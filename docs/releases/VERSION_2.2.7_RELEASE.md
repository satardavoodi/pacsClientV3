# AIPacs Version 2.2.7 Release
**Date:** March 21, 2026
**Version:** 2.2.7
**Type:** Stable Release / Install and Build Alignment
**Status:** Ready for Git publication
**Tag:** `v2.2.7`

---

## Summary

Version **2.2.7** captures the current stable workspace and aligns the release metadata, environment setup, build helpers, and top-level documentation with the repository's current dependency and packaging model.

## Included Release Updates

- `main.py` -> application version `2.2.7`
- `pyproject.toml` -> package version `2.2.7`
- `build_nuitka.py` -> Windows product version `2.2.7`
- `builder/plugin package/packages/module_package_feed.json` -> feed version `2.2.7`
- `builder/plugin package/packages/*/module_package.json` -> module versions `2.2.7`
- `setup_env.ps1` -> runtime-first setup flow with optional `-IncludeDev`
- `builder/scripts/_common.ps1` -> build dependency install aligned with `requirements-core.txt`
- `README.md` and active docs -> install/build/release instructions refreshed for this stable version

## Install and Build Notes

- Runtime setup now defaults to `requirements-core.txt`
- Developer setup can be enabled with `.\setup_env.ps1 -IncludeDev`
- Release builds should use `builder/requirements/build_requirements.txt` plus `requirements-core.txt`
- Legacy `requirements.txt` remains a fallback path for older tooling, but it is no longer the primary setup path

## Release Intent

- Save the current stable codebase as release `v2.2.7`
- Create a local backup artifact before publication
- Commit, tag, and push the release state to the configured Git remotes

## Notes

- This release is intended to represent the current stable working tree rather than a narrow single-feature change.
- The consolidated release history continues in `docs/releases/RELEASE_NOTES.md`.
