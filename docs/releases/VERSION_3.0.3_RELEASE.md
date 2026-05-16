# AIPacs v3.0.3 Release Notes
**Date**: May 16, 2026  
**Branch**: beta-version  
**Release Type**: Release snapshot (FAST-to-MPR route hardening)

---

## Summary

v3.0.3 packages the current beta snapshot with FAST-to-MPR launch routing fixes, audit-safe full-volume loading, and the latest geometry boundary guard coverage.

---

## Included in v3.0.3

1. FAST-mode MPR route resolution from the current viewer state
2. Audit-safe full-volume loading for orthogonal and curved MPR
3. Structured `[MPR_LAUNCH_ROUTE]` diagnostics for launch visibility
4. Geometry boundary guard coverage and boundary-audit reporting
5. Release marker alignment for the beta branch snapshot

---

## Validation Suite

- `tests/viewer/test_mpr_launch_route.py`
- `tests/viewer/test_mpr_vtk_load_bridge.py`
- `tests/architecture/test_backend_geometry_boundary_guards.py`
- `tests/viewer/test_fast_viewer_pipeline.py`

---

## Versioning Updates

- `pyproject.toml` -> `version = "3.0.3"`
- `main.py` -> `app.setApplicationVersion("3.0.3")`
- `docs/releases/RELEASE_NOTES.md` -> current stable set to `v3.0.3`
- `docs/README.md` -> current stable set to `v3.0.3`
- `.github/copilot-instructions.md` -> current stable set to `v3.0.3`

---

## Notes

- Previous stable: `v3.0.2`
- This release tag: `v3.0.3`
- Purpose: beta snapshot with MPR launch fixes and release packaging