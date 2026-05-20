# AIPacs v3.0.8 Release Notes

**Release date:** 2026-05-20  
**Branch:** beta-version  
**Previous stable:** v3.0.7

---

## Summary

v3.0.8 is the stable hardening checkpoint on top of the v3.0.7 baseline.

This release consolidates DM retry/queue/worker-pool hardening, socket client
stabilization, and UI/viewer-side fixes into a new stable conservative branch
target.

---

## Version Alignment

The following canonical version markers are set to `3.0.8`:

- `pyproject.toml` -> `version = "3.0.8"`
- `main.py` -> `app.setApplicationVersion("3.0.8")`
- `docs/README.md` -> current stable `v3.0.8`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.0.8`
- `.github/copilot-instructions.md` -> current stable `v3.0.8`

---

## Included In This Release

- Download Manager retry/queue/worker-pool hardening updates
- Socket client reliability and related network path updates
- FAST viewer / interactor / bridge fixes
- Home UI service and workstation integration updates
- Plugin package mirror synchronization for modified canonical modules
- Runtime/config/database artifact updates bundled in this checkpoint

---

## Publication

- All pending workspace changes committed as the v3.0.8 consolidation checkpoint
- Force-push performed to conservative branch target on `origin`
- Tag `v3.0.8` retained/pushed for release traceability
