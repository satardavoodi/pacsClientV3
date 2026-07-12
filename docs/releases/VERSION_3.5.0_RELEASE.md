# AIPacs v3.5.0 Release Notes

**Release date:** 2026-07-12
**Branch:** beta-version
**Previous stable:** v3.4.9

---

## Summary

v3.5.0 advances the stable version line to the 3.5 series and publishes the full
current beta-version source state to all configured remotes. The headline fix is
responsiveness: opening Eagle Eye no longer freezes the application for roughly a
minute. It also introduces a shared DICOMDIR builder for interchange media
(patient CD + Offline Sync), an internal-assignment panel for the reception
workflow, release-build config sanitization, and a multi-study series-display fix.

---

## Version Alignment

The following canonical version markers are set to `3.5.0`:

- `pyproject.toml` -> `version = "3.5.0"`
- `main.py` -> `app.setApplicationVersion("3.5.0")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.5.0` (tuple `(3, 5, 0, 0)`)
- `docs/README.md` -> current stable `v3.5.0`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.5.0`
- `.github/copilot-instructions.md` -> current stable `v3.5.0`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.5.0` (English + Farsi)

LICENSE unchanged.

---

## Included In This Release

### Eagle Eye open freeze (OPT-27)
Clicking Eagle Eye froze the whole application for ~1 minute. The AI-module tab
eagerly built the Model-Training settings widget, which auto-detected the
mammography image size by walking the **entire** DICOM store with `pydicom`
**on the GUI thread**. Its file cap counted only MG hits, so on a CT/MR-heavy
store the cap never tripped and it read every file on disk.

- The scan is now **bounded** (files actually opened + a wall-clock deadline) and
  runs **off-thread**, applied back to the UI safely
- No viewer, VTK, geometry, or download path is touched — it only seeds a training
  spinbox default
- Measured: worst stall on Eagle Eye open **~54.8 s -> ~1.4 s**

### Multi-study series will not display (OPT-26)
On a patient with several studies sharing series numbers, loading a **secondary**
study's series repointed the tab's `import_folder_path` to that study. A later
**primary** load then resolved `study_path/<n>` to the wrong study's folder, and
the viewport identity gate correctly refused to paint it — so the series stayed
blank. The tab path is now pinned to the **primary** study; a secondary series
loads from its own resolved path and can never redirect the tab.

### DICOMDIR on interchange media
A single shared DICOMDIR builder now lives in core (`modules/dicom_media`) and is
used by both the patient-CD burner and Offline Sync; the CD burner becomes a thin
shim over it rather than carrying its own implementation.

### Reception / INO
- New internal-assignment panel for the reception workflow

### Build / release safety
- `builder/config_sanitizer.py` ensures machine-generated and local state never
  ships inside an installer
- Download-manager instance payload-key variants and net-monitor import-path fixes

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.5.0` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
