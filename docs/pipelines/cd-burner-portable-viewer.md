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
* **No VTK / MPR / AI / reporting.** v1.1 toolset (final, per clinical spec
  2026-06-07): stack scrolling, **cross-pane reference lines** (IPP/IOP
  plane intersection, FoR-matched, `render.reference_line_segment` — pure
  math, unit-tested), **ruler** (mm via the CP-586 spacing chain
  PixelSpacing→ImagerPixelSpacing→NominalScanned; shows *px* when
  uncalibrated — never fabricates mm; rulers are per-image and clear on
  slice change), plus W/L, zoom, pan. **Default layout = 2 views**
  (1-view toggle); series-list click loads the ACTIVE pane; first two
  series auto-distribute on open. Single-file multi-frame (cine) series
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

## 10. Burn-image filesystem — NEVER ISO9660-only (fixed 2026-06-06 night)

First cross-PC test of a burned disc failed with the PyInstaller bootloader
error **"Failed to start embedded python interpreter!"**. Root cause
(reproduced locally via `tools/analysis/oneoff/Make-TestIso.ps1` + mounted
ISOs): CD media burns used `FileSystemsToCreate = 1` (ISO9660 only) and
IMAPI silently mangles every non-8.3 name to DOS form — `_internal` →
`_INTER~1`, `AIPacsLiteViewer.exe` → `AIPACS~1.EXE` — so the exe runs but
its `_internal` runtime is unreachable. With `= 3` (ISO9660 + Joliet) names
survive and the viewer was verified RUNNING from a mounted read-only ISO.

Invariant: `cd_writer.filesystems_for_media()` returns **3 for all media**.
DICOM conformance is unaffected — the DICOMDIR/PT000000 layout is 8.3-safe,
so legacy readers use the ISO9660 layer while Joliet carries the real names.
Guard test: `test_burn_image_always_includes_joliet`. Discs burned BEFORE
this fix have valid DICOM but a non-functional viewer copy → re-burn.

## 11. Bundle completeness — the missing-PySide6 incident (fixed 2026-06-07)

Second cross-PC failure after the Joliet fix: the viewer launched but died
with a ModuleNotFoundError dialog on every machine. Root cause (from
`pyi_work/.../warn-AIPacsLiteViewer.txt`: *"missing module named
viewer_app"*): **PyInstaller's static analysis does not honor the entry
script's runtime `sys.path.insert`** — `from viewer_app import main`
resolved to nothing, so the ENTIRE viewer chain (viewer_app, media_scan,
render, viewer_meta → PySide6, Qt plugins) was silently dropped. The
"successful" 64.9 MB bundle contained only the explicitly-passed codec
hidden-imports; the fixed bundle is **158.1 MB**.

Fixes + release gates (all in `tools/build/build_lite_viewer.py`):
* `--paths <portable_viewer dir>` + `--hidden-import` for viewer_app /
  media_scan / render / viewer_meta.
* `CRITICAL_BUNDLE_FILES` assertion before publish: python313.dll,
  base_library.zip, VCRUNTIME140.dll, PySide6/QtCore.pyd,
  PySide6/plugins/platforms/qwindows.dll.
* **Frozen self-test gate**: the built exe must pass `--selftest`
  (Qt offscreen init + render pipeline + pydicom + all 4 codecs) or the
  build refuses to publish. `run_selftest()` lives in viewer_app.
* Burn-time guard: `_verify_staging_output` fails the burn if
  `VIEWER/_internal` is missing python313.dll / base_library.zip /
  VCRUNTIME140.dll / qwindows.dll on the staged media.

Verified: stripped-environment run (PATH=System32 only, no Python/Qt env,
neutral cwd) of the new bundle FROM A MOUNTED READ-ONLY ISO →
`SELFTEST OK — qt | render | pydicom 2.4.5 | 4 codecs` exit 0. The bundle
carries its own CRT (VCRUNTIME140*, ucrtbase + api-ms shims) → no VC++
redist needed on target PCs. **Lesson: "process stayed alive" is NOT a
viewer health check — windowed PyInstaller apps show an error dialog and
keep running; always use `--selftest` exit codes.**

Follow-up caught BY the new staging guard on the very next burn attempt:
the viewer-staging archive exclusion (`*.zip`, meant for junk like the
legacy rar) was stripping `_internal\base_library.zip` — the PyInstaller
runtime itself. `*.zip` is no longer excluded (only `*.rar`/`*.7z`); guard
test `test_bundle_copies_tree_but_never_junk_archives` pins it, and an
end-to-end pre-flight (real 158 MB bundle through the worker, burn_to_disc
=False) confirms all critical files reach the staged media.

## 12. v1.1 startup diet (2026-06-07)

CD startup cost ≈ bytes + file count read from optical media. Measures:
* New module excludes (cryptography/certifi/charset_normalizer/psutil/
  urllib3/requests/idna — optional-chain stowaways, not viewer deps).
* Post-build `PRUNE_PATTERNS` (build script): Qt translations,
  opengl32sw/d3dcompiler, Qt6Network/OpenGL/Svg/Pdf/Qml/Quick DLLs,
  imageformats/iconengines/tls/networkinformation/generic plugins.
  platforms (qwindows+qoffscreen) and styles stay. Completeness assert +
  `--selftest` run AFTER pruning and gate the publish.
* Result: 343 → **204 files**, 158.1 → **96.6 MB** (−39%), selftest
  wall-time 6.3 s → 3.3 s on the dev machine; CD gains scale with the
  byte/seek reduction. The media scan was already off the UI thread; the
  window appears as soon as Qt is up.

## 13. Imaging-center identity (v1.2 — 2026-06-07)

The Write CD dialog has an "Imaging Center" section (name / address /
phone). Entered once → persisted via `center_identity.py` into the shared
`lightviewer_settings.json` (per-system; save preserves all other keys) →
auto-reloaded on every later burn. `_build_options()` saves on use and
carries the values in `BurnOptions.center_*`.

On the media: `_write_portable_support_files` stamps a `center` object
into `AIPACS_MEDIA_INFO.json` and "Created by / Address / Phone" lines into
`START_HERE.txt` (only when at least one field is set; center info is
included even when patient anonymization is ON — it identifies the center,
not the patient). The viewer (`media_scan.load_media_info` +
`LiteViewerWindow._apply_media_info`) shows a banner above the panes —
"NAME · ADDRESS · ☎ PHONE" — and appends the center name to the window
title. No identity on the media → banner hidden, fully backward compatible.

## 14. Branded welcome page (v1.3 — 2026-06-07)

`portable_viewer/welcome.py` — full-window Persian (RTL) landing page shown
BEFORE the viewer: AI-PACS logo (`assets/aipacs_logo.png`, copied from
`Qss/images/aiLogo.png`; shipped via `--add-data` → `_internal/assets`,
asserted in `CRITICAL_BUNDLE_FILES`), Iran Nobat / INO724 wordmarks, the
exclusive-representative statement (`COMPANY_STATEMENT_FA`), clickable
links (`COMPANY_LINKS` — irannobat.ir, ino724.com; product links get
appended there when provided), the burning center's identity from the
media manifest, and a primary «مشاهده تصاویر» / Open Viewer button.

Flow: `LiteViewerWindow` central widget is a QStackedWidget — index 0
welcome (toolbar hidden), index 1 viewer. The media scan keeps running
under the welcome page, so series are typically ready on click-through.
Enter/Space also proceeds. `--no-welcome` skips it (QA/tests). Autorun
already targets the viewer exe, so inserted CDs land on the welcome page;
RUN_VIEWER.cmd / START_HERE.txt remain the visible manual fallbacks.
Gotcha: the viewer's global QSS paints every QWidget dark — welcome labels
need `background: transparent` or they show banding. Offscreen preview
renders need `QT_QPA_FONTDIR=C:\Windows\Fonts` (offscreen QPA has no GDI
font database; without it every glyph is tofu).

## 15. Series drag-and-drop to a pane (v1.4 — 2026-06-07)

**Click vs drag are fully separated (v1.4.1 — 2026-06-07).** The original
bug: load was wired to the list's selection-change, which fires on
mouse-PRESS, so the press that starts a drag loaded the series into the
active pane before the drag began (and looked like Layout 1 "stealing" a
drop meant for Layout 2). Fix: `SeriesListWidget` drives the drag itself
(`setDragEnabled(False)`, `NoDragDrop`) —
* press records position + the row's series index, loads NOTHING;
* move past `QApplication.startDragDistance()` with the button held starts
  a `QDrag` carrying `_SERIES_MIME` and a **ghost-thumbnail preview**
  (`preview_provider` → window renders first-slice thumb + label band;
  text-chip fallback) — and emits no click;
* release with no drag, on the same row, emits `seriesClicked` → load into
  the ACTIVE pane.
Headers (no UserRole) are inert. Each `ImageCanvas` is the drop target
(`setAcceptDrops`): `dragEnterEvent` shows a cyan border + "Drop series
here", `dropEvent` decodes the index → `on_series_dropped` → loads into
THAT pane and activates it. Import happens ONLY on the final drop; panes
the cursor merely crosses get nothing. Test seam `_exec_drag` makes the
modal QDrag non-modal under pytest; synthetic QMouseEvents prove press
doesn't load, drag suppresses the click, and headers are inert.
`tests/.../test_viewer_dragdrop.py` (7) — suite total 81.

## 16. Reliable/efficient CD reads + 32-bit policy (v1.5 — 2026-06-07)

**Robust optical reads** (`portable_viewer/optical_io.py`): `read_bytes`
reads a whole file into RAM in one sequential pass with bounded retries
(CRC / seek-timeout glitches on CD/DVD usually succeed on retry); the
viewer parses DICOM from that stable in-memory buffer instead of seeking
the disc repeatedly. Wired into `render.load_slice` / `peek_frame_count`
(`_dcmread_robust`) and the media scan (`_dcmread_header`), each with a
direct-read fallback so a buffered-read failure never blocks viewing.
`is_optical_path` (GetDriveTypeW) and `stage_files_to_temp` are available
for future "copy series to temp" staging. Combined with the existing
worker-thread prefetch + LRU cache, scrolling masks optical latency.
Hidden-import `optical_io` in the build.

**Architecture / Windows-version policy (decided 2026-06-07):** Qt 6 has
NO 32-bit Windows build, so the viewer is 64-bit only — and a 64-bit
PyInstaller bundle that ships its own UCRT (already present:
ucrtbase + api-ms-win-crt shims + VCRUNTIME140) runs on **Windows 7 SP1
through 11, 64-bit, with no install**. For genuine 32-bit Windows the disc
**degrades gracefully**: `RUN_VIEWER.cmd` detects 32-bit
(`PROCESSOR_ARCHITECTURE==x86` && no `PROCESSOR_ARCHITEW6432`), prints a
clear message and opens the DICOM folder so DICOMDIR works with any
installed viewer — no cryptic "not a valid Win32 application". AutoRun now
routes through `RUN_VIEWER.cmd` (not the exe) so the guard runs on autorun
too; START_HERE states the 64-bit requirement + fallback. Building a
separate 32-bit viewer (PyQt5/tkinter) was considered and declined — 32-bit
Windows is effectively end-of-life (Win11 is 64-bit only).

## 17. Empty-DICOMDIR bug — image missing directory fields (2026-06-15)

Patient 46419 (single 8 MB image) prepared a folder with DICOMDIR + viewer
but **no PT/ST/SE/IM image tree**. Root cause: the image lacked
StudyDate/StudyTime/StudyID/AccessionNumber, so pydicom's default STUDY
record creator raised in `FileSet.add()` ("missing a required element or
value"); `build_from_study_folders` caught and merely *logged* it, wrote a
0-instance DICOMDIR, and validation PASSED because expected-uids and
actual-uids were both empty → the burn reported success with no images.

Fixes (`dicomdir_builder.py`):
* `_ensure_dicomdir_fields(ds)` backfills the directory-record-required
  elements when absent OR empty (pydicom treats an empty Type-1 value as
  missing): StudyDate/StudyTime from the image's own Series/Content/
  Acquisition date-time (placeholder 19000101/000000 only as last resort),
  StudyID/SeriesNumber/InstanceNumber→"1", Modality→"OT", PatientID→
  "ANONYMOUS", AccessionNumber→"0", PatientName present. UIDs/pixels never
  touched; existing values never overwritten.
* Zero added instances now **fails the build loudly** (returns False) and
  the validation rejects an empty expected-uid set — a silent empty disc is
  impossible. Guard tests: `test_dicomdir_required_fields.py` (8), incl. the
  exact 46419 case (all four fields dropped) and a real end-to-end prepare
  that confirms the image lands at PT000000/ST000000/SE000000/IM000000.
  Suite total 97.

## 18. Installed-client viewer guarantee + module cleanup (2026-06-15)

**Guarantee the viewer ships in the installed app.** The CD module is the
optional `run_cd` plugin; its payload must carry the default lite viewer or
an installed client clicking "Write CD" gets "viewer not found".
* `builder/materialize_plugin_packages.py::_validate_run_cd_lite_viewer`
  now FAILS the build if the run_cd payload lacks a complete lite viewer
  (exe + `_internal/base_library.zip` + python313.dll + qwindows.dll).
  Escape hatch: `AIPACS_ALLOW_MISSING_LITE_VIEWER=1`. So you can't
  accidentally ship the CD module without its viewer.
* `viewer_locator.resolve_default_viewer` is now frozen-robust: it searches
  `_candidate_roots()` — the module dir AND, when `sys.frozen`, the
  `_MEIPASS` / exe-dir / `_internal` `modules/cd_burner` locations — so the
  bundled viewer resolves under PyInstaller, Nuitka, and source identically.
* PyInstaller engine still ships `modules/cd_burner/lightViewer_dist` via
  `spec_utils.common_app_datas`; the installer ships the run_cd plugin
  payload (Inno `[Files]` → `%ProgramData%\AIPacs\module_packages\run_cd`).

**Cleanup / optimization.**
* Retired the obsolete legacy viewer (`modules/cd_burner/lightViewer/`
  AiPacs.exe ~72 MB + `lightViewer.rar` ~71 MB) to
  `_recovery/legacy_lightviewer_20260615/` — the lite viewer is the default
  and always shipped, so the legacy binary was ~143 MB of dead weight (and
  its asymmetric presence tripped the plugin shadow guard once excluded).
  The `viewer_locator` legacy fallback code stays as harmless defence.
* `materialize._copy_source_tree` now also ignores `lightViewer` + `*.rar`
  so no plugin payload re-accretes that bloat.
* Removed dead `DicomDirBuilder` methods (`build_simple`,
  `create_folder_structure`, its private `_copy_light_viewer`,
  `_sanitize_name`, `_sanitize_folder_name`) and unused imports across the
  module. cd_burner suite: 104 green; with builder+runtime: 153 green.

## 19. Auto-build viewer in release + installer auto-enable (2026-06-15)

**Release builds always build the lite viewer.** Both release pipelines now
build it before staging the run_cd payload, so a release can never ship a
stale/absent viewer:
* `tools/build/build_lite_viewer.py::ensure_built(force=True)` — importable
  entry; `--if-missing` for build-if-absent.
* `materialize_plugin_packages(build_lite_viewer=True)` runs
  `_ensure_lite_viewer_built()` (subprocesses the build script) before the
  loop; CLI `--build-lite-viewer`; skip with
  `AIPACS_SKIP_LITE_VIEWER_BUILD=1`.
* Wired: Nuitka `stage_08_plugin_staging` (build_lite_viewer=True) and
  PyInstaller `build_release.build_module_packages` (calls
  `_ensure_lite_viewer_built()` + `_validate_run_cd_lite_viewer` on the
  run_cd package). build_release has its OWN staging copy — its
  `PACKAGE_IGNORE_PATTERNS` also now drops `lightViewer` + `*.rar`.

**Installer tick ⇒ auto-enabled (already wired, confirmed).** run_cd is
`bundled_unlock`, NOT license-gated — ticking the "Run CD" component is the
only gate. `AIPacs_Setup.iss::WriteInstallationProfile` writes
`run_cd` into BOTH `modules` (`OptionalModuleSelected` → enables
`is_module_enabled("run_cd")`) and `module_packages`
(status=selected_for_install), and `[Files]` copies the payload to
`%ProgramData%\AIPacs\module_packages\run_cd`. At runtime
`activate_optional_module_runtime` adds the payload to `sys.path`, the home
panel shows the CD button, and `viewer_locator` finds the bundled viewer in
the payload. So: tick → installed → enabled → viewer used, automatically.

GOTCHA: running `materialize_plugin_packages.py` standalone REGENERATES the
committed `builder/plugin package/packages/` mirrors (full copytree) and can
desync them from canonical for hand-curated plugins — always run
`tools/dev/sync_plugin_mirrors.py` afterward (restores 389-pair match).
Tests: `test_lite_viewer_autobuild.py` (6); cd_burner 110, builder+runtime 49.

## 20. PyInstaller builder path — verified + slimmed (2026-06-15)

The PyInstaller `builder/build_release.py` is the primary release path.
Verified end-to-end (no full compile needed): `build_module_packages` (main
@1415) calls `_ensure_lite_viewer_built()` then stages run_cd via its OWN
`_copy_package_source_tree` (full copytree, `_package_ignore_filter`), runs
`_validate_run_cd_lite_viewer`, and `run_release_gate_post_stage` runs after.
Proven: the STAGED viewer exe `--selftest` exits 0 after the staging copy's
filters apply — i.e. the copy doesn't break it. `lightViewer`/`*.rar` are in
`PACKAGE_IGNORE_PATTERNS` so the 143 MB legacy never stages.

**Key architecture fact:** `appA_workstation.spec` `optional_prefixes`
EXCLUDES `modules.cd_burner` from the engine (hiddenimports filter), so in
the PyInstaller build the CD code loads ONLY from the installed run_cd
plugin payload (`%ProgramData%\AIPacs\module_packages\run_cd\payload\python\
modules\cd_burner`), never from engine datas. Therefore the engine-datas
copy of `lightViewer_dist` (~97 MB, 180 files) was **dead weight shipped in
EVERY installer** (even non-CD customers) — removed from
`spec_utils.common_app_datas` (assets stay; patient_table_widget reads them
via BASE_PATH). The viewer now ships once, via the run_cd payload (build-
asserted present). `viewer_locator._candidate_roots` also adds the installed
payload path (`bundled_module_packages_search_roots()` → run_cd/payload/...)
as a resolution backstop, so the viewer resolves regardless of which channel
loads cd_burner. Guard tests: `test_installed_payload_root_resolves_viewer`,
engine-datas-has-0-viewer assertion. cd_burner 111 green, mirrors 389.

## 21. Adopted from external lite-viewer eval report (2026-06-16)

Reviewed an external eval report; adopted the two points that apply to our
code, confirmed one already-done, and deferred the rest as out-of-scope:

* **ADOPTED — hermetic frozen sys.path** (`portable_viewer/_hermetic.py`,
  called from `aipacs_lite_viewer.py` BEFORE importing the viewer). On a
  customer PC a host Python / `PYTHONPATH` / user site-packages could leak
  onto `sys.path` and load a *different* numpy whose compiled extension
  clashes with the bundled one → startup crash. When frozen we now keep only
  bundle-internal `sys.path` entries (drop `''`/CWD and any external dir).
  Pure filter `compute_hermetic_path` is unit-tested; `_hermetic` is a build
  hidden-import; frozen `--selftest` still passes after the change.
* **ADOPTED — shadow validators ignore non-Python folders.** Both
  `_validate_*_no_namespace_shadow` (build_release + materialize) now count a
  dir as a subpackage only if it has `__init__.py` or a `.py` file. Pure data
  folders (`lightViewer_dist`, `assets`) no longer trip a false "partial
  shadow" when present in one tree but not the other — the principled fix for
  the 2026-06 lightViewer case (we'd previously worked around it by deleting
  the legacy dir). Real missing Python subpackages are still caught (tested).
* **ALREADY PRESENT — windowed self-test fallback.** `run_selftest` already
  writes `%TEMP%\aipacs_lite_selftest_failed.txt` for no-console diagnosis.
* **ADOPTED (2026-06-16, after investigation) — DM image-count
  normalization.** Our `grpc_client.py` DID have the bug: line ~113 read
  only `series.get("image_count")`, so a server variant key collapsed the
  series to 0 images. Added `_normalize_image_count()` (tries image_count /
  ImageCount / number_of_instances / NumberOfInstances / instance_count /
  num_images …, safe non-negative int, default 0 = same as before so it can
  only fix, never regress). Tests: `test_image_count_normalization.py` (7).
  File is plugin-mirrored (download_manager payload) — synced.
* **NOT APPLICABLE — MPR PYZ-gate markers.** Investigated: every marker the
  report calls "missing" (`_view_axes`, `_anat_look_axis`,
  `_anatomical_camera`, `_force_crosshair_on_top`,
  `_apply_native_plane_interpolation`, `layout_views`, `slab_mode`) is
  ALREADY present in our `modules/mpr/zeta_mpr/mpr_viewer/*` source, and
  `builder/audit/scripts/verify_mpr_in_pyz.py` checks exactly those — our
  gate passes. The report's MPR fix was for its own divergent branch;
  re-adding markers to our source would be wrong. No change.

## 22. Known limitations / deferred

* IMAPI2 `Write()` is synchronous — no fine-grained burn % (progress jumps
  50→95) and mid-write cancel is not possible. Event-sink progress is a
  possible future improvement.
* Post-burn disc read-back verification ("Verify" in some commercial tools)
  is not implemented; staging-level verification + `ForceMediaToBeClosed` only.
* Same-machine GUI QA of the dialog and a real burn on physical media still
  pending (needs a writer drive + blank disc).
* ~~The Lite Viewer exe is NOT built yet~~ — built 2026-06-06 (PyInstaller,
  64.9 MB); `resolve_default_viewer()` now returns kind="lite" on this machine.

## 23. Build self-test gate — robustness (recurring build failures fixed 2026-06-17)

**Symptom:** nearly every release build died at *"Building module packages →
Lite viewer build failed (exit 5)"*. Two different tracebacks were seen:
a numpy `ImportError: cannot load module more than once per process`, and an
`AssertionError` at `run_selftest` (`assert image.width() > 0 …`).

**Root cause — the GATE was flaky, the BUNDLE was sound.** Diagnosis on
2026-06-17: the freshly rebuilt bundle has exactly one
`numpy/_core/_multiarray_umath*.pyd` (no duplicate) and the frozen
`--selftest` passes **12/12** when run warm/idle. The build-time failures are
environmental:
1. A freshly written, unsigned ~99 MB bundle is slow on its **first**
   execution while **Windows Defender scans every bundled DLL**, and the host
   is still saturated from the main-app PyInstaller pass → the single 300 s
   selftest **timed out**, then the contended retry tripped the render check.
2. The render check built a **1×1** `QImage` from `error_slice` — a degenerate
   scanline that can intermittently construct as a null (0×0) image under load.
3. The numpy double-load came only from the *pre-rebuild* bundle whose
   `run_selftest` imported numpy directly; current source imports numpy ONLY
   through the already-loaded `render` module (see below). A `--clean` rebuild
   clears it.

**Fix (minimal, two parts):**
- **Deterministic self-test.** `render.SliceData.selftest_slice(16)` builds a
  16×16 gradient through the real windowing math; `run_selftest` asserts the
  resulting QImage is exactly 16×16. Well-formed scanlines remove the 1×1 edge
  case. numpy is touched ONLY via `render` (the entry must never `import numpy`
  a second time — that re-triggers "load module more than once" in the frozen
  bundle). Guards: `test_selftest_slice_is_well_formed`,
  `test_run_selftest_returns_zero` in `tests/code/cd_burner/test_lite_viewer_core.py`.
- **Resilient gate** (`tools/build/build_lite_viewer.py::_run_selftest`):
  (1) a **warm-up** run absorbs the AV scan + OS file-cache (a pass here already
  greens the gate), then (2) up to `AIPACS_LITE_SELFTEST_ATTEMPTS` (default 3)
  attempts on the warm bundle. Only a **consistent clean failure** (bundle runs
  but the check fails) fails the build — a real defect. A **timeout-only**
  outcome is environment, not a defect, so it degrades to the source self-test
  instead of nuking the release. Tunables: `AIPACS_LITE_SELFTEST_WARMUP_SEC`
  (300), `AIPACS_LITE_SELFTEST_TIMEOUT_SEC` (per-attempt, 180),
  `AIPACS_LITE_SELFTEST_ATTEMPTS` (3). `_assert_bundle_complete` (critical-file
  check) still runs BEFORE the selftest, so a genuinely incomplete bundle is
  caught regardless.
- **Escape hatch unchanged:** `AIPACS_SKIP_LITE_VIEWER_BUILD=1` skips the build
  for fast local iteration; the release still refuses to ship run_cd without a
  viewer unless `AIPACS_ALLOW_MISSING_LITE_VIEWER=1`.

Validated 2026-06-17: cold rebuild passes the gate on the warm-up run (exit 0,
published to `lightViewer_dist`); 13/13 `test_lite_viewer_core.py` green;
mirrors 389/389. `render.py` + `viewer_app.py` are plugin-mirrored — re-run
`tools/dev/sync_plugin_mirrors.py` after editing them.

## 24. Burned viewer must run from LOCAL disk, not off the disc (2026-06-17)

**Symptom (after burning):** double-clicking `E:\VIEWER\AIPacsLiteViewer.exe`
on the burned disc shows *"Could not load PyInstaller's embedded PKG archive
from the executable"*.

**Root cause — NOT corruption.** Diagnosed: the source exe is a valid
PyInstaller bundle (MEI cookie at tail, 6,640,951 B = 6,485 KB, which MATCHES
the size shown on the disc → not truncated), and the burn verifies with SHA-256
(`cd_writer.compare_folder_trees`). The failure is PyInstaller's onedir
**bootloader reading its own embedded PKG archive directly off optical media**:
the bootloader does random reads of the exe tail/TOC, and a single CD read
glitch (optical media is unreliable for random access; some target PCs / AV make
it worse) aborts with that error. Running a 99 MB onedir bundle (the exe + ~430
files in `_internal`) straight off a DVD is inherently fragile.

**Fix — `RUN_VIEWER.cmd` copies the bundle to local disk first**
(`cd_burn_manager._write_portable_support_files`). When the launcher sees a real
onedir bundle (the viewer dir contains `_internal`) it `robocopy`s
(`/E /R:3 /W:1` — the retries also ride out flaky optical reads) the VIEWER
folder to `%TEMP%\AIPacsLiteViewer` and runs the exe from there with
`--import-folder "%~dp0"` (the DICOM images STAY on the disc and are read via
the viewer's existing robust/retrying optical reads). Goto-based structure (no
fragile nested parens). Fallbacks preserved: 32-bit Windows guard → opens the
DICOM folder; copy failed / single-exe custom viewer (no `_internal`) → runs in
place; exe missing → clear message. `autorun.inf` already routes through
`RUN_VIEWER.cmd`, so autorun benefits too. `START_HERE.txt` now tells users to
launch via `RUN_VIEWER.cmd` and NOT run `VIEWER\*.exe` directly off the disc.

**To pick up the fix the user must RE-BURN** from an app build that has this
`cd_burn_manager.py` (it generates the launcher at burn time) — the exe itself
is unchanged and does NOT need rebuilding. Quick manual confirmation on the
*existing* failing disc: copy `E:\VIEWER` to the hard drive and run the exe from
there — it launches fine (proves the optical-read root cause + the fix).

`cd_burn_manager.py` is plugin-mirrored (run_cd) — synced (393/393). Guard:
`tests/code/cd_burner/test_cd_burner_portability.py::test_run_viewer_copies_onedir_bundle_to_local_disk`;
119/119 cd_burner tests green.

## 25. Branded, console-free launcher — no CMD window (2026-06-17)

**Symptom:** clicking the disc's viewer entry briefly showed a raw black CMD
window reading *"Preparing the viewer, please wait…"* — that is the §24
`RUN_VIEWER.cmd` (a `.cmd` ALWAYS opens a console). Unprofessional on a patient
disc.

**Fix — `RUN_VIEWER.hta` is now the PRIMARY launcher**
(`cd_burn_manager._write_portable_support_files`). An HTA runs under
`mshta.exe` (a GUI host present on every Windows XP→11), so it shows an
AI-PACS-branded splash with **NO console**, matching the viewer's welcome page
(dark navy `#0d1320`, card `#172133`, accent `#3b82f6`, `AI-PACS` wordmark, CSS
spinner). Its JScript:
- shows **"Preparing viewer, please wait."** (the exact requested text);
- finds its own folder (`location.pathname`, fallback `aipacsApp.commandLine`);
- 32-bit-Windows guard → opens the images folder + branded message;
- if the viewer dir has `_internal` (real onedir), runs `robocopy` **hidden**
  (`WScript.Shell.Run(cmd, 0, false)` — window style 0 = no console) to
  `%TEMP%\AIPacsLiteViewer`, polls a `.copydone` marker, then launches the
  **copied** exe with `--import-folder` at the disc root and `window.close()`s;
- single-exe viewer (no `_internal`) → runs in place;
- any failure → branded in-app error (`fail()`, red text) + a Close button
  (e.g. "Could not prepare the viewer", "needs Windows Script Host → use
  RUN_VIEWER.cmd").

`autorun.inf` now routes through it (`open=mshta.exe RUN_VIEWER.hta` +
`shellexecute=RUN_VIEWER.hta`), so AutoPlay is console-free too. `RUN_VIEWER.cmd`
is kept as a FALLBACK for locked-down PCs that block `.hta` (its message is now
also "Preparing viewer, please wait."). `START_HERE.txt` + the manifest
(`viewer_launcher_primary`, `portable_launchers`) point at the HTA first.
`_verify_staging_output` now requires `RUN_VIEWER.hta` whenever a viewer is
included.

The HTA is generated from a raw-string template with `__VIEWER_SUBDIR__` /
`__VIEWER_EXE__` tokens; JScript syntax validated with `node --check`, paths/
escaping confirmed by generating it. **Re-burn required** to get the HTA (the
exe is unchanged). Acceptance criteria met: click → no CMD window → branded
"Preparing viewer, please wait." splash → closes when the viewer opens → branded
error on failure. Guard:
`tests/code/cd_burner/test_cd_burner_portability.py::test_branded_hta_launcher_is_generated_and_console_free`;
121/121 cd_burner green; mirror 393/393. NEEDS live re-burn verify (mshta can't
be tested headlessly).

## 26. Launcher is a branded EXE — no console, no "open with" prompt (2026-06-17) — SUPERSEDES §25

**Symptom:** double-clicking the disc launcher showed a Windows *"how do you
want to open this .hta file?"* (open-with) prompt on PCs where `.hta` is not
associated with `mshta` (locked-down / hijacked association). The §25 HTA fixed
the console but introduced this association problem.

**Root cause:** the only file types that double-click DIRECTLY with **no console
window AND no "open with" prompt** are real `.exe`s. `.cmd` → console; `.hta` /
`.vbs` → association/"open with" prompt + AV flags; `.lnk` → breaks on
removable media (stored drive letter). So the launcher must be an exe.

**Fix — a tiny branded launcher EXE (`AIPacsViewer.exe`) at the media root.**
- Source: `modules/cd_burner/portable_viewer/cd_launcher.py` — standalone,
  stdlib + tkinter only (never imports `modules.cd_burner…`), built as a
  **onefile, --windowed** exe by `build_lite_viewer.build_launcher()` (NON-FATAL;
  if it can't build, discs fall back to RUN_VIEWER.cmd). Published to
  `lightViewer_dist/AIPacsViewer.exe` next to the viewer dist.
- Behaviour: GUI exe → no console; shows a branded tkinter splash (dark navy
  `#0d1320` / card `#172133` / accent `#3b82f6` / "AI-PACS" + indeterminate
  progressbar) saying **"Preparing viewer, please wait."**; reads
  `AIPACS_MEDIA_INFO.json` → `viewer_launcher` (so it works for any viewer
  name); 32-bit guard → opens the images folder; if the viewer dir has
  `_internal` (onedir) it `robocopy`s it to `%TEMP%\AIPacsLiteViewer` (retries,
  hidden via `CREATE_NO_WINDOW`) and launches the **copied** exe with
  `--import-folder` at the disc root; single-exe viewer runs in place; any
  failure shows a branded in-app error + Close button (no Windows dialog).
  Onefile = sequential read from CD (the launcher itself is CD-safe); it's tiny
  (~10.6 MB) so its own extraction is fast.
- Wiring (`cd_burn_manager`): `_stage_cd_launcher` copies the exe to the media
  root; autorun → `open=AIPacsViewer.exe` + `shellexecute=AIPacsViewer.exe` (no
  mshta); the **`.hta` is no longer generated at all**; `RUN_VIEWER.cmd` remains
  a last-resort fallback; manifest `viewer_launcher_primary` + START_HERE point
  at the exe; `_verify_staging_output` requires the manifest's primary launcher
  to exist on the media.
- Release/installed builds: the launcher rides along in `lightViewer_dist`
  (materialize regenerates the run_cd payload), so the installed app stages it
  onto every disc automatically.

Validated: launcher builds (10.6 MB, exit 0); 126/126 cd_burner tests green incl.
headless launcher logic (`test_cd_launcher.py`: copy-to-temp + launch-from-copy,
single-exe in place, 32-bit guard) + `test_exe_launcher_is_primary_and_no_open_with_prompt`
(no `.hta` shipped, autorun → exe); mirror 394/394 (cd_launcher.py added).
**Re-burn required** (launcher is generated/staged at burn time). NEEDS live
double-click verify on the burned disc.

## 27. Local study cache — smooth viewing, no repeated CD reads (2026-06-17)

**Problem:** even after the launcher copied the *viewer* to temp, it still ran
the viewer with `--import-folder` pointed at the **CD**, so every image was read
off optical media at runtime → slow scrolling + repeated spinners.

**Fix (all inside `cd_launcher.py` — burn side unchanged):** during the branded
"Preparing viewer, please wait." popup the launcher now copies BOTH the viewer
runtime AND the study DICOM to a managed per-user local cache, then launches the
viewer with `--import-folder` pointed at the **local cache** (`discover_media_root`
accepts any folder with a DICOMDIR). The CD is the source, never the runtime read
path.

Cache layout — `%LOCALAPPDATA%\AI-PACS\CDViewerCache` (fallback
`%TEMP%\AIPacsCDViewerCache`; per-user, **no admin**):
- `viewer/` — the onedir runtime, shared across discs (skipped if already cached;
  single-exe viewers run from the CD, no copy).
- `studies/<key>/` — one folder per study (DICOMDIR + image tree + manifest).
  `<key>` = sha1 of the study's `(relpath, size)` set (metadata only, no content
  reads) → the SAME disc reopens to the SAME key.

Key behaviours (pure, unit-tested helpers): `compute_study_signature` (excludes
`VIEWER/` + launcher infra from both the key and the copy), `is_study_cache_valid`
(completion marker `.aipacs_cache.json` + on-disk count/bytes must match → catches
partial copies), `prune_studies` (LRU: keep newest `_KEEP_STUDIES`=6 and under
`_MAX_CACHE_BYTES`=8 GB, **never deletes the study in use**), `free_bytes`
(pre-copy disk check with a 300 MB margin; prunes then re-checks). Copy via
`_robocopy` (incremental `/E`, retries `/R:2` ride out flaky reads, hidden via
`CREATE_NO_WINDOW`) with a pure-python `_py_copy_tree` fallback. Splash shows a
live "Copying images… N files" detail line.

**Graceful degradation (never blocks):** any cache failure — low disk, read-only
target, robocopy missing, incomplete copy — falls back to opening straight from
the CD (`mode="cd"`, `--import-folder` = CD root), exactly the pre-cache
behaviour. 32-bit guard and the branded error+Close path are unchanged. Reopen
of the same disc reuses the valid cache (no copy → fast).

Validated: 134/134 cd_burner tests green incl. `test_cd_launcher.py` cache suite
(signature determinism + exclusions, marker validity/tamper, LRU prune keeps
current, cache→launch-from-cache, reuse-on-reopen, single-exe study-cached,
CD fallback, 32-bit guard); launcher rebuilt (10.7 MB, exit 0); mirror 394/394.
`cd_launcher.py` is plugin-mirrored. **Re-burn required.** NEEDS live verify
(double-click on the burned disc; confirm smooth scrolling + a `studies/<key>`
folder appears under `%LOCALAPPDATA%\AI-PACS\CDViewerCache`).

## 28. CD drive shows the AI-PACS icon + the patient's name (2026-06-17)

When a burned disc is inserted, Explorer should show the **AI-PACS icon** on the
drive and **name the drive after the patient**. Windows honours `autorun.inf`
`icon=` and `label=` for display on optical media (this is the display behaviour,
not the disabled auto-*run*), and the filesystem **volume label** is the backstop.

**Drive icon:** a dedicated `AIPACS.ico` (multi-res, generated from
`assets/cd_icon.png` → committed `modules/cd_burner/assets/aipacs_drive.ico`) is
staged to the disc root by `_stage_drive_icon` (inside `_write_portable_support_files`,
so BOTH the viewer and no-viewer paths get it), and `autorun.inf` uses
`icon=AIPACS.ico` (falls back to the launcher/viewer exe icon if the asset is
missing). A root `.ico` is far more reliable for drive icons than the previous
`icon=VIEWER\…exe,0`.

**Patient name = CD name:** `_resolve_labels` now also returns the DICOM
`PatientName`; `_cd_display_label` turns it into a clean volume label
(`Family^Given` → `FAMILY GIVEN`, `normalize_volume_label`: uppercase, ASCII,
≤32) → `cd_name`. `run()` uses `cd_name` for (a) the burn **volume label**
(`burner.burn(..., cd_name, ...)`), (b) `autorun.inf` `label=`, and (c)
START_HERE/manifest. The DICOM File-set ID is still the normalized disc/auto
label (interop unaffected). **Privacy:** when `options.anonymize` is on,
`_cd_display_label` returns the fallback label — the real name never lands on an
anonymized disc. `_copy_light_viewer` now takes the resolved
`fileset_label`/`volume_label` (was inconsistently re-deriving from the raw
`disc_label`).

Manifest gains `drive_icon` + `patient_label`. Validated: 138/138 cd_burner
tests green incl. `test_cd_drive_label.py` (display label from PatientName,
anonymize hides it, `_resolve_labels` returns the name, autorun has
`icon=AIPACS.ico` + `label=<patient>` and `AIPACS.ico` is staged); mirror
394/394 (+`aipacs_drive.ico` copied into the run_cd payload). `cd_burn_manager.py`
is plugin-mirrored. **Re-burn required.** NOTE: Windows aggressively caches
drive icons — a fresh disc on a PC that hasn't seen it shows the new icon/name;
an already-cached drive letter may need a reinsert/icon-cache refresh. Non-ASCII
(e.g. Persian) names fall back to the ASCII-normalized form in the label.
