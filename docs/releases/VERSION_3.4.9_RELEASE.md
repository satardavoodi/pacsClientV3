# AIPacs v3.4.9 Release Notes

**Release date:** 2026-07-12
**Branch:** beta-version
**Previous stable:** v3.4.8

---

## Summary

v3.4.9 is a patch release on the 3.4 line that publishes the full current
beta-version source state to all configured remotes. The headline fix is a
clinical one: radiography studies from devices that omit `SeriesNumber` (legal —
DICOM type 2) no longer fail to download or display. It also adds drag-and-drop
DICOM import to the patient-CD Lite Viewer, corrects CD workflow defaults on a
fresh install, and carries the large-frame download timeout fix.

---

## Version Alignment

The following canonical version markers are set to `3.4.9`:

- `pyproject.toml` -> `version = "3.4.9"`
- `main.py` -> `app.setApplicationVersion("3.4.9")`
- `builder/spec/appA_version_info.txt` -> file/product version `3.4.9`
- `docs/README.md` -> current stable `v3.4.9`
- `docs/releases/RELEASE_NOTES.md` -> current stable `v3.4.9`
- `.github/copilot-instructions.md` -> current stable `v3.4.9`
- `PacsClient/pacs/workstation_ui/home_ui/home_info_panel.py` -> UI version strings `3.4.9` (English + Farsi)

LICENSE unchanged.

---

## Included In This Release

### Radiography not displaying — missing SeriesNumber (OPT-25)
A radiography device at a new centre omitted `SeriesNumber` (0020,0011), which is
legal (DICOM type 2). The server serialized the absent value as the literal string
`"None"`, and an `int("None")` aborted the metadata build for the **whole study** —
so the study never downloaded and its images could never be displayed. Series
identity is now normalized **once** at the single socket ingestion boundary:

- Healthy data is untouched (same value, same type) — no centre regresses
- Synthetic numbers use a reserved, non-colliding, deterministic band
- Images are fetched by `series_uid`, so no server change is required
- One malformed series can no longer abort an entire study

### Lite Viewer (patient CD) — external drag-and-drop import
Dropping DICOM files, folders, a disc root, or a `DICOMDIR` from File Explorer onto
the Lite Viewer now imports them (previously the drop was silently ignored).

- Single content-based discovery entry point (extension-less `IM000000` supported)
- Runs off the GUI thread; never writes to the read-only media
- Re-dropping merges by `series_uid` rather than duplicating

### CD workflow defaults on a fresh install
- The viewer never scans its own program folder (it previously could surface
  pydicom's bundled sample DICOMs as another patient's study)
- A missing or stale custom viewer now falls back to the recommended viewer
  instead of burning a disc with no viewer at all
- The Lite Viewer logs to a file, so diagnostics survive a windowed frozen build

### Networking / performance
- Large-frame (PX / MG / XA / RF) download timeout fix — 20–100 MB single-frame
  images no longer hit the 30s socket timeout
- Shutdown-safe socket logging (Qt teardown guards)
- Warm socket connection-pool reuse across patient searches (OPT-24c)

---

## Publication

- Built/packaged from latest `beta-version` working state
- Version line aligned to `v3.4.9` across canonical metadata files
- Force-pushed to main + beta-version on all configured remotes (ai-pacs, PacsClientV2, pacsClientV3)
