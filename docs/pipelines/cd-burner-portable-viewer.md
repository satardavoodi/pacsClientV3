# CD Burner + Portable Lite Viewer — As-Built (2026-06-06)

Design + integration record for the patient CD/DVD export pipeline and the
bundled **AI-PACS Lite Viewer**. Read this before editing
`modules/cd_burner/` or `PacsClient/.../settings_ui/lightviewer_settings.py`.

## 1. Architecture

```
modules/cd_burner/
├── cd_writer.py            IMAPI2 burn engine (comtypes; WMI/GetDriveType fallbacks)
├── dicomdir_builder.py     pydicom FileSet → DICOMDIR + PT/ST/SE/IM tree, validated
├── cd_burn_manager.py      CDBurnWorker (QThread pipeline) + CDBurnManager façade
├── cd_burn_dialog.py       Write-to-CD dialog (drive, label, viewer, progress, log)
├── viewer_locator.py       DEFAULT viewer resolution (lite → legacy fallback)
├── portable_viewer/        AI-PACS Lite Viewer source (self-contained!)
│   ├── viewer_meta.py      version/name constants (no Qt)
│   ├── media_scan.py       DICOMDIR-first scan, recursive fallback (no Qt)
│   ├── render.py           pixel pipeline: rescale, W/L, MONO1/RGB/palette → QImage
│   ├── viewer_app.py       QMainWindow: series list, scroll/zoom/pan/WL, toolbar
│   └── aipacs_lite_viewer.py  Nuitka standalone entry
├── lightViewer_dist/       BUILD OUTPUT (gitignored): AIPacsLiteViewer/ bundle
└── lightViewer/            legacy 75 MB AiPacs.exe — fallback only
```

## 2. Burn pipeline (CDBurnWorker.run)

collect studies → DICOMDIR build (+validation) → viewer copy → support files
(`START_HERE.txt`, `RUN_VIEWER.cmd`, `OPEN_DICOM_FOLDER.cmd`, `autorun.inf`,
`AIPACS_MEDIA_INFO.json`) → staging verification → free-space check (16 MB
margin) → IMAPI2 burn (ISO9660 for CD media, +Joliet otherwise,
ForceMediaToBeClosed) → eject. All stages emit `progress(int, str)`;
failures emit `completed(False, message)` — the dialog re-enables Burn for
retry. The worker is a QThread: the GUI never blocks.

## 3. Viewer selection (Settings → burn)

* `lightviewer_settings.json` (roaming config) now has `viewer_mode`:
  `"default"` (bundled AI-PACS viewer) or `"custom"` (user .exe).
  **Back-compat:** configs without `viewer_mode` mean *custom if a path was
  configured, else default* (`_normalize_mode`).
* `LightViewerSettingsWidget.get_viewer_selection()` → `{mode, path,
  display_name, kind}`; `kind ∈ lite|legacy|override|custom|none`.
* Default resolution (`viewer_locator.resolve_default_viewer()`):
  1. env `AIPACS_LITE_VIEWER_PATH` (tests/power users)
  2. `lightViewer_dist/AIPacsLiteViewer/AIPacsLiteViewer.exe` (built lite)
  3. legacy `lightViewer/*.exe` (prefers `AiPacs.exe`)
* The dialog resolves via settings; if the settings package is unavailable
  (plugin-only deployment) it falls back to `viewer_locator` directly.

## 4. Viewer staging rules (cd_burn_manager._copy_light_viewer)

* `inspect_viewer_portability()` decides `bundle_mode`:
  * `single_exe` → copy **only the exe** into `VIEWER/` (never the parent
    folder — a Downloads-dir pick must not drag junk onto the disc).
  * `portable_bundle` → copytree the exe's folder into `VIEWER/`, ignoring
    `__pycache__`, logs/tmp/bak, **and archives (`*.rar`, `*.zip`, `*.7z`)** —
    the legacy folder contains a 75 MB `lightViewer.rar` that must never be
    burned.
* `autorun.inf` `open=`/`shellexecute=` point at `VIEWER\<exe>` with
  `--import-folder .`; `RUN_VIEWER.cmd` is the manual fallback (AutoRun is
  blocked on modern Windows). `AIPACS_MEDIA_INFO.json` records the launcher;
  staging verification fails the burn if the manifest/launcher disagree.

## 5. Lite Viewer invariants

* **Self-contained:** `portable_viewer/` must never import `PacsClient` or
  other `modules.*` — it compiles standalone and runs from read-only media.
  Allowed deps: PySide6 (Core/Gui/Widgets), pydicom, numpy (+pylibjpeg).
* **No VTK / MPR / AI / reporting.** Basic 2D only (open, series list,
  scroll, zoom, pan, W/L, toolbar). Single-file multi-frame (cine) series
  are expanded to frames at selection time.
* Imports use the `try: from .x import … except ImportError: from x import …`
  pattern so both repo-package and standalone-script modes work.
* Slice cache: LRU 96 entries; ±3 neighbour prefetch on a 2-thread pool —
  decoded arrays only cross threads; QImage is built on the GUI thread.
* MONOCHROME1 renders inverted; missing/invalid WindowCenter/Width falls
  back to 1–99 percentile; RescaleSlope/Intercept always applied.

## 6. Building the Lite Viewer

```
tools\build\build_lite_viewer.bat        (or .venv python tools/build/build_lite_viewer.py)
tools\build\build_lite_viewer.py --builder nuitka     (slower C-compiled alternative)
```
**Default builder is PyInstaller** (user decision 2026-06-06): onedir,
`--windowed`, builds in ~30 s, bundle ≈ 65 MB with codecs. Nuitka remains
available via `--builder nuitka` (20+ min compile). Both are ONEDIR on
purpose — onefile would unpack to %TEMP% on patient PCs; slow/fragile from
CD. Publishes to `modules/cd_burner/lightViewer_dist/AIPacsLiteViewer/` +
`viewer_info.json`. First build done 2026-06-06 (pyinstaller-onedir, 64.9 MB,
all 4 codec dists verified in `_internal`, live launch smoke-tested).
**Codec gotcha:** pylibjpeg plugins import as `rle`/`openjpeg`/`libjpeg` and
are found via entry-point metadata — BOTH the import name AND the dist
metadata must ship (PyInstaller: `--hidden-import` + `--copy-metadata`;
Nuitka: `--include-package` + `--include-distribution-metadata`); dropping
either ships a viewer that can't decode compressed DICOM.
**Entry-script gotcha:** `aipacs_lite_viewer.py` must import `viewer_app`
as a PLAIN module only — never `modules.cd_burner...`, not even in a
try/except fallback. Freeze tools follow that import statically and drag the
workstation chain (qtawesome/comtypes/extra Qt) into the bundle.

## 7. Packaging

* PyInstaller spec: `builder/spec/spec_utils.py::common_app_datas` ships
  `modules/cd_burner/lightViewer_dist` (no-op until built).
* Nuitka/plugin build: `builder/materialize_plugin_packages.py` re-copies the
  whole `modules/cd_burner` tree into the `run_cd` payload, so the built
  bundle ships automatically.
* Plugin mirror: `.py` changes under `modules/cd_burner/` MUST be mirrored to
  `builder/plugin package/packages/run_cd/payload/python/modules/cd_burner/`.
  Use `tools/dev/sync_plugin_mirrors.py` (new) then
  `tools/dev/verify_plugin_mirrors.py` (gate; 299 pairs as of 2026-06-06).
* `lightViewer_dist/` is gitignored in both locations (build artifact).

## 8. Tests (all headless, `QT_QPA_PLATFORM=offscreen`)

`tests/code/cd_burner/` — 33 green (2026-06-06):
* `test_cd_burner_portability.py` — labels, support files, verification (pre-existing)
* `test_viewer_locator.py` — lite>legacy preference, AiPacs.exe preference, env override
* `test_viewer_selection_settings.py` — mode persistence + back-compat + resolution
* `test_copy_light_viewer_modes.py` — single-exe vs bundle staging, archive exclusion
* `test_lite_viewer_core.py` — synthetic-DICOM scan (filescan + DICOMDIR), sorting,
  rescale/W-L mapping, MONOCHROME1 inversion, RGB passthrough, corrupt-file error
  slice, window smoke test (series load, scroll, W/L adjust/reset)

Run: `.venv\Scripts\python.exe -m pytest tests/code/cd_burner -p no:debugging -q`

## 9. Professional burn options (added 2026-06-06 evening)

The dialog now exposes the full professional workflow; every UI option has
backend behavior. New modules: `dicom_prepare.py`, `content_collectors.py`.

* **BurnOptions** (`cd_burn_manager.BurnOptions`) carries: anonymize+seed,
  include_report/images/attachments, dicom_format, write_speed_sectors,
  finalize_disc, verify_after_burn. Defaults reproduce legacy behavior;
  callers without options are unchanged.
* **Anonymization** (`DicomPreparer`): PatientName→`ANONYMOUS^<seed>`,
  PatientID/Accession→`ANON<seed>`, identifying tags blanked, UIDs
  (study/series/SOP/FoR + referenced) remapped CONSISTENTLY across the whole
  export via a cached map. Anonymization failure EXCLUDES the file (never
  leaks); transcode failure FALLS BACK to the previous form (never drops
  images). Every written file is validated by re-read + pixel decode.
* **Formats**: original (pass-through — and the whole prepare stage is a
  zero-copy passthrough when no anonymize+original), uncompressed (ELE via
  ds.decompress), lossless = RLE (pydicom ds.compress), JPEG 2000
  lossless/lossy via `openjpeg.encode_array` + `pydicom.encaps.encapsulate`
  (lossy ~10:1, sets LossyImageCompression tags). GOTCHA: openjpeg's
  encoder has 6 fixed DWT resolutions and rejects tiny images (<~32 px) —
  they fall back to original syntax by design (tests use 64×64).
* **Extras on disc**: `REPORTS/<pid>/report_<id>.html` (from
  `ai_reception_reports` via `database.ai_reception_db`), `JPEG/` (image
  files from `ATTACHMENT_PATH/<study_uid>`), `ATTACHMENTS/` (non-image files
  from the same folder — captures and attachments share that folder).
  When anonymize is ON these are auto-disabled/skipped (identifying data).
* **Disc settings**: drive combo + Refresh; write speeds from
  `IDiscFormat2Data.SupportedWriteSpeeds` (labels like "24x (3.6 MB/s)",
  empty → Auto only); disc label empty/[Auto Label] → auto label
  `<patient-or-ANONxxxx> <study date> <today>`; capacity line compares
  estimated size (studies + viewer bundle + 8% overhead) against inserted
  media free space — the worker still enforces the exact-size check
  (16 MB margin) before writing.
* **Finalize** maps to `ForceMediaToBeClosed`. **Verify** burns without
  eject, waits for remount, then `compare_folder_trees` (existence + size +
  SHA-256, case-insensitive names for ISO9660 folding), then ejects;
  failures list examples in the error dialog.
* Worker stage map: collect 2-5 → prepare 5-28 → DICOMDIR 28-50 → viewer
  50-56 → extras 56-60 → staging verify 60-62 → burn 62-90/100 → disc
  verify 90-99. `cancel()` reaches the preparer and burner too.
* Tests: `tests/code/cd_burner/test_professional_burn_options.py` (17) —
  suite total 50 green as of 2026-06-06 evening. Live burn QA of the new
  options pending.

## 10. Known limitations / deferred

* IMAPI2 `Write()` is synchronous — no fine-grained burn % (progress jumps
  50→95) and mid-write cancel is not possible. Event-sink progress is a
  possible future improvement.
* Post-burn disc read-back verification ("Verify" in some commercial tools)
  is not implemented; staging-level verification + `ForceMediaToBeClosed` only.
* Same-machine GUI QA of the dialog and a real burn on physical media still
  pending (needs a writer drive + blank disc).
* ~~The Lite Viewer exe is NOT built yet~~ — built 2026-06-06 (PyInstaller,
  64.9 MB); `resolve_default_viewer()` now returns kind="lite" on this machine.
