# AIPacs v3.2.4 Release Notes

**Release date:** 2026-06-07
**Branch:** beta-version
**Previous stable:** v3.2.3

---

## Summary

v3.2.4 is a minor release consolidating the latest stable beta-version source state with
merged Home Page, Settings, Viewer, CD module, and Browser improvements into a new
production package line.

---

## Version Alignment

The following canonical version markers are set to `3.2.4`:

- `pyproject.toml` -> `version = "3.2.4"`
- `main.py` -> `app.setApplicationVersion("3.2.4")`
- `docs/README.md` -> current stable `v3.2.4`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.2.4`
- `.github/copilot-instructions.md` -> current stable `v3.2.4`

LICENSE unchanged (AI-PACS EULA v3.0.9, effective 2026-05-25).

---

## Included In This Release

### Home Page Updates

- Main Page column sizing changes
- Patient Name sizing adjustments
- Patient ID sizing adjustments
- Body Part sizing adjustments
- Status and Report column updates
- Adaptive-to-screen-size improvements
- Column resize behavior improvements

### Settings Updates

- Tool Settings integration fixes
- Viewer Configuration fixes
- Modality Grid updates
- Modality filter synchronization
- Default layout configuration support
- Settings persistence improvements

### Viewer Updates

- Modality-specific layout handling
- MPR-related fixes already merged
- Annotation/tool configuration connections
- Local settings application

### CD Module Updates

- Portable viewer fixes
- Viewer startup fixes
- Welcome page infrastructure
- Imaging-center information support
- CD writer improvements

### Browser Updates

- UI consistency changes
- Loading-bar jump fix
- Toolbar styling improvements

---

## Publication

- Built from latest stable `beta-version` source state on 2026-06-07
- Version line bumped to `v3.2.4` across canonical metadata files
- Release package generated via the PyInstaller release pipeline under `builder/output`
