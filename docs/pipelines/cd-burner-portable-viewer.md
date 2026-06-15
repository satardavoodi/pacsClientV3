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

## 19. Known limitations / deferred

* IMAPI2 `Write()` is synchronous — no fine-grained burn % (progress jumps
  50→95) and mid-write cancel is not possible. Event-sink progress is a
  possible future improvement.
* Post-burn disc read-back verification ("Verify" in some commercial tools)
  is not implemented; staging-level verification + `ForceMediaToBeClosed` only.
* Same-machine GUI QA of the dialog and a real burn on physical media still
  pending (needs a writer drive + blank disc).
* ~~The Lite Viewer exe is NOT built yet~~ — built 2026-06-06 (PyInstaller,
  64.9 MB); `resolve_default_viewer()` now returns kind="lite" on this machine.
