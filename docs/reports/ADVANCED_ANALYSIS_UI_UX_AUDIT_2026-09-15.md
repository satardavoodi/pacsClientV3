# Advanced Image Analysis UI/UX audit

Date: 2026-09-15. Tracking: OPT-56; manual-review boundary also relates to OPT-51/OPT-58.
Scope: requested initial review of documentation, source, branding assets, executable
discovery and existing guards. No runtime changes, application launch or release.

## Verdict

The resident viewer/headless separation is established, but consistent geometry,
complete visible branding and all-entry-point startup behavior are not yet verified.
The source-linked AIPacsAdvancedViewer.exe exists and is selected by current discovery.
This does not prove its embedded resources match the current C++ source.

## Execution map

| Entry | Current behavior | Evidence |
|---|---|---|
| Workstation warmup | Optional viewer starts in background, main window suppressed, real authenticated readiness | `PacsClient/utils/advanced_analysis_startup.py`, `resident_service.py` |
| Advanced Analysis user launch | Reuses viewer, restores suppressed dialogs and shows normal window; DICOM import then runs in the external GUI process | `slicer_launcher.py`, `AIPacsBackgroundRuntime.py::viewer_command` |
| Resident analysis | Separate lazy process with `--no-main-window`, immutable snapshots, owned process job | `resident_service.py::LocalRuntime.start` |
| Brain computation | Separate no-main-window execution with both splash switches | `modules/ai_imaging/eagle_eye_brain/runtime.py::run_slicer` |
| Manual correction | Separate visible process and Segment Editor; launch options differ from resident viewer | `manual_review.py::prepare_review`, `manual_slicer.py` |
| Resident disabled | Legacy cold launcher remains reachable | `slicer_launcher.py::SlicerLauncherWorker.run` |

The current extension guide explicitly separates implemented offline lumbar support
from research-only extension entries. Its inventory must not be presented as proof
that every researched extension is installed. Extension Manager defaults OFF in the
custom application's CMake configuration.

## Findings and priorities

1. **P1: geometry policy differs between launch paths (source-confirmed).**
   Native `qNewMPR2SlicerAppMainWindow.cxx:148` scales the supplied viewer rectangle
   to 70%; resident `AIPacsBackgroundRuntime.py:216` applies the supplied rectangle
   directly. The native fallback is 940x620 and centers using width/height without
   adding the available screen rectangle's x/y origin. Resident geometry checks
   bound numbers but do not clamp the window to an actual screen. Define a single
   screen-aware sizing policy and test secondary monitors, taskbar offsets,
   small screens and mixed DPI. These are source findings, not measured live clipping.

2. **P1: manual correction bypasses common launch safeguards (source-confirmed).**
   `manual_review.py:32` passes `--no-splash` but omits `--launcher-no-splash` and
   the resident path's Windows startup/console flags. It copies the parent environment
   and discards the Popen handle. The interactive editor should remain a separate
   scene, but share deliberate splash, environment and lifetime policy. A console
   or splash flash is a risk; it was not observed live in this audit.

3. **P1: custom-only executable contract is not enforced for overrides.**
   `launch_slicer.py::find_slicer_executable` documents custom-only selection but
   accepts any existing file supplied through the explicit environment/config path.
   It only prints whether the filename resembles the custom executable. The current
   selection is correctly named; a stock executable override can defeat branding.
   Add a synthetic rejection guard and validate approved runtime identity.

4. **P2: branding is present, but not complete evidence of every visible surface.**
   `Main.cxx` assigns AI-PACS application identity and loads the embedded theme
   before window creation; the main window uses the custom DesktopIcon resource.
   Visible titles still say `AI-PACS Advanced Viewer v0.1`, while the workstation
   calls this Advanced Image Analysis. Decide whether this distinct module version
   is intentional. The About handler still uses `qSlicerAboutDialog` with a custom
   logo, so its remaining content needs live inspection. No explicit Windows
   AppUserModelID assignment was found in this module. PowerShell VersionInfo
   returned blank description/product/original-filename/version fields for the
   inspected launcher and matching inner executable. Taskbar grouping, Alt-Tab,
   file properties and embedded icon parity therefore remain acceptance work.

5. **P2: icon legibility needs a small-size design.**
   Both inspected PNG assets contain the AI-PACS mark, not a Slicer logo. The 48px
   DesktopIcon includes the full tagline, which is not legible at this size. Use a
   simplified brand mark for small icons and verify 16/24/32/48/256px ICO frames.
   This audit did not replace assets or inspect every embedded ICO frame.

6. **P2: responsiveness remains a measurement task.**
   Resident DICOM import/load executes synchronously in the external viewer's Qt
   handler. This isolates the workstation but can stall the analysis window on
   large inputs. Existing 4.385s cold / 0.471s warm timings in OPT-56 are historical
   synthetic observations, not current measurements. Benchmark cold/warm launch,
   time to rendered data, cancellation and idle RAM before selecting optimizations.

7. **Verification debt: Qt test ordering.**
   Running resident tests first exited 1 after 15 dots without a pytest summary.
   The resident file creates QCoreApplication; the subsequent window tests need
   QApplication and reuse an existing instance. Each file passed alone; placing
   the QApplication window tests first made the combined 23 cases pass. This
   supports a harness ordering problem; do not classify it as a production crash
   or silently count the first invocation as successful.

## Verification on this date

- Direct pytest, Python 3.13.5, QT_QPA_PLATFORM=offscreen, PYTHONPATH=.,
  `-p no:debugging --reruns 0`.
- `test_slicer_resident.py`: 15 passed, exit 0.
- `test_slicer_window_promotion.py`: 3 passed, exit 0.
- `test_advanced_launch_safeguard.py`: 5 passed, exit 0.
- Combined in window/resident/safeguard order: 23 passed, six SWIG warnings,
  exit 0. These tests do not execute the real Slicer binary.
- Live control: existing `tools/testing/aipacs_control_mcp/client.py ping`
  failed to connect, exit 1. No connected MCP alternative was in the tool inventory.
  Action discovery and live GUI acceptance could not follow.
- No patient data, clinical database or installed executable was used. Existing
  dirty runtime work was preserved. No speedup, complete rebranding or release
  readiness is claimed.

## Next implementation slices under OPT-56

1. Guard and repair custom executable validation and common launch options,
   preserving separate manual-review and analysis scenes.
2. Consolidate geometry calculation and add synthetic multi-monitor/DPI cases.
3. Unify visible product naming and small icons, then verify native build parity.
4. After human source startup/sign-in with AIPACS_TEST_SERVER=1, use the existing
   control bridge plus actual GUI input to inspect startup, modal dialogs, About,
   extension panels, taskbar/Alt-Tab icons, resize/maximize and close/reopen.
5. Measure comparable cold/warm and large-series workloads; retain distinct code
   and live acceptance receipts. Source/native changes require their respective
   regression and build workflows; this review does not authorize a release.

Primary references: `docs/modules/ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md`,
`ADVANCED_ANALYSIS_SLICER_CONTROL_RUNBOOK.md`,
`SLICER_EXTENSIONS_INSTALL_AND_CONTROL_GUIDE.md`, and OPT-56 in the master plan.

## Live follow-up and version correction, 2026-09-15

The owner launched and signed into one source workstation. The existing control
client still failed ping (exit 1), but the supported Windows Computer Use API
could operate the native UI. A cached local MR series was opened through a real
Home card double-click, then Advanced Analysis through its sidebar button.
The external viewer rendered the selected series with 384x384x11 dimensions.
No patient identities, images or screenshots are retained in this report.
Exact UID inspection through the test bridge remains unavailable.

### Observed UI

- Startup overlay used the AI-PACS logo. The external window appeared and showed
  an informational modal with version 0.1.0; OK dismissed it without changing the
  Don't-show-again preference. Startup responsiveness was not quantitatively timed.
- Main title repeated the product/version after case metadata. About used the
  correct AI-PACS logo and heading, but displayed 0.1.0 and visible Slicer text.
  Settings also exposed upstream documentation URLs and the startup-script path.
  This disproves complete visible rebranding. Attribution and engine provenance
  require a deliberate About/licensing presentation, not indiscriminate removal.
- File, Edit, View/Layout, Help and module-selection menus opened. File exposed
  Add Data/DICOM, Save, Close Scene and Exit; View exposed stock layout choices,
  Python Console and Error Log. These entries were inspected, not all executed.
  Application Settings opened and was cancelled without saving.
- The live module menu included Data, Markups, Models, Segment Editor,
  Segmentations, Transforms, Volume Rendering, Volumes, registration and other
  categories. Segmentation exposed AI-PACS Offline Lumbar and Segment Editor.
  Both panels opened with the source selected. No inference, painting, report,
  data export, remote request or installation was initiated. Segment Editor
  initialized an empty in-memory segmentation; source data was not saved/changed.
- Cross-sectional lines were toggled off and disappeared from the views.
  Native wheel input changed the external sagittal image. Separately, native
  PACS wheel input changed its slice from 6/11 to 7/11 while the external viewer
  remained open. This verifies sampled independent interaction, not all startup,
  large-study, model-computation or modal states.
- Current display inventory: DELL 1920x1080 (available 1920x1032), LCD1970NXp
  1280x1024 (available 1280x976), both DPR 1 / 96 logical DPI. The owner moved the
  window to the smaller display after automation dragging failed. The normal
  window was partially outside the visible area. Native Maximize produced a
  fully visible 1280x976 capture at (1920,0). Main MPR controls fit vertically.
- The MPR panel consumed approximately 480/1280 pixels, the offline panel about
  514/1280 and Segment Editor about 605/1280. Four-up images therefore become
  narrow. Several controller icons/spinbox labels have poor dark-theme contrast;
  the 3D background retains a purple gradient. The MPR information panel labels
  a series description as Patient and leaves Modality/Sequence blank.
- Windows activation through the automation helper restored the normal size;
  it was maximized again. Do not interpret that helper-induced transition as a
  spontaneous application resize. Taskbar displayed the small AI-PACS mark;
  complete Alt-Tab/ICO-frame and mixed-DPI acceptance remains open.

### Authorized version correction

The owner explicitly requested alignment with workstation version 3.6.6. Native
CMake application version fields, the C++ display title, Python startup and both
legacy launcher title declarations now match 3.6.6. Case metadata precedes the
brand in the title so a matching Qt display name need not be appended again.

`tests/code/mpr/test_advanced_analysis_brand_version.py` failed all seven cases
before the change (exit 1). It executes the real title function with synthetic
metadata and structurally checks native/launcher declarations against pyproject.
The final adjacent launch/window/package selection passed **34 tests**, four
deselected, six existing SWIG warnings, direct exit 0. Both Python payload mirrors
were synchronized with the supported script; **462 pairs match**.

**Native rebuild and fresh version acceptance are pending.** The running executable
is still the pre-existing 0.1 runtime. No hot reload, binary patch or installed
application launch was performed. The documented C:/S/NB native build cache is
absent; this audit does not claim a compiled 3.6.6 runtime. The live UI observations
above predate the source correction and cannot count as its live acceptance.
Full small-screen, theme, About and nonblocking-startup repairs remain open under
OPT-56. Rollback of this slice is limited to the four source version/title hunks,
the two synchronized Python mirrors and their seven-case guard.

## Header, module icons and compact title implementation

The subsequent owner request authorized a cleaner header/module menu and a short
window title. `slicer_custom_app/presentation.py` now provides an in-process,
scene-independent presentation adapter. Resident viewer initialization installs it
while the window is still hidden; the analysis/headless role does not install it.
The legacy startup entry also installs the header adapter. No global polling,
process restart loop, network call or patient-data access is added.

- Original cyan line symbols replace module-action icons for Markups, Models,
  Segment Editor, Segmentations, volumes and other common tools. Unmapped modules
  receive the same family of generic tools icon. SVG is rendered from memory.
- The original QAction objects, module data, names, enabled state and dispatch
  connections remain intact. Existing nested menus/history are retained; menu
  opening decorates newly populated module entries.
- The header reads `AI-PACS / Analysis`; module menus use a navy/cyan palette and
  larger item spacing. The MPR banner uses the shorter `MPR / Multiplanar views`.
- The window title is always `AI-PACS Advanced Viewer v3.6.6`. Patient/study UIDs
  are no longer included. The Qt display name is aligned at runtime, preventing
  the old native display suffix from reappearing on the main title.
- Resident load geometry is clamped to the requested monitor's available area,
  with margins for window chrome; negative origins and taskbar offsets are covered.
  No-request launches use bounded default geometry. This does not make every
  third-party extension panel responsive or replace native About metadata.

Verification: the compact-title requirement failed two existing behavioral cases
before repair. Six presentation cases initially failed because the adapter was
absent. The final focused header/title/window/resident/safeguard/package selection
passes 40 tests, four deselected, six existing SWIG warnings, direct exit 0.
The tests render distinct small icons, preserve nested action dispatch/disabled
state, check screen containment, and verify idempotent installation without showing
a suppressed window. The new helper and updated Python payloads are synchronized;
463 mirror pairs match. These Qt tests use PySide6, not the embedded PythonQt runtime.

The first fresh launch exposed a PythonQt incompatibility: assigning an arbitrary
`_aipacsPresentation` attribute to the native main window raises AttributeError,
preventing the resident ready handshake. Ownership now lives in the Python module.
A restricted-window regression guard failed before the fix; the focused suite now
passes 41 tests (four deselected). All 463 mirror pairs match.

The documented synthetic resident probe passes with exit 0 after the correction:
hidden startup, show/hide, exact DICOM series selection, scene preservation and
separate headless analysis all succeed. Cold startup was 4.56 seconds; warm show
0.77 seconds; maximum controller heartbeat gap 0.63 seconds. One preceding probe
hit a ready.json cleanup PermissionError; its exit was not counted as a pass.
Synthetic logs also retain an unrelated delayed geometry logger NameError for vtk.

Fresh native GUI acceptance: the existing source workstation's Advanced MPR button
opened the corrected viewer and rendered the selected local MR in MPR views.
The compact 3.6.6 title and shortened header were visible. The startup notice was
acknowledged with OK. Module-menu icons were visibly replaced; selecting Models
opened its panel with the rendered scene retained. No patient identifiers or
images are included in this report. The native Previous arrow resets its stock
icon after module selection, so complete navigation branding remains open.
The existing test-control ping is still unavailable. Native About version,
full extension-theme review, launch-overlay blocking and native rebuild remain
separate open items. Preserve the earlier source version correction on rollback;
revert only this presentation adapter, its startup/resident hooks, compact-title
changes and matching mirrors/guards.

## Home and module dropdown workflow correction

Live symptom: selecting Home leaves an empty sidebar and hides the menu bar.
The source Home.ui contains only an empty layout. HomeWidget.setup also applies
template-wide styling and hides native controls. It is a scaffold, not the MPR
landing page. The real landing module is NewMPR2MPR.

The resident presentation now promotes the original NewMPR2MPR action as
`Home / MPR` and exposes only installed Data, Volumes, Markups, Models,
VolumeRendering, SegmentEditor and Segmentations actions in a flat dropdown.
The empty Home scaffold, DICOM import, developer categories and specialized
pipelines are hidden from this menu. The stock module finder is hidden because it
bypasses this curated list. Modules are not unloaded or disabled; owning Eagle Eye
workflows retain programmatic access. Segment Editor is retained because the
brain manual-correction entry point explicitly selects it. This patch does not
alter that separate entry point or its correction/export contract.

A new guard failed before implementation and passes after: the real MPR action
retains its data and callback, nested required tools are promoted without duplicate
entries on repeated refresh, disabled tools retain their state, and specialized
actions remain owned by their original menus. Focused verification: 42 passed,
four deselected, six existing SWIG warnings, direct pytest exit 0; 463 mirrors match.
The owner authorized repeated native close/reopen and discarding this test scene.
The first fresh-process pass exposed broken dispatch after removeAction/addAction:
the selector label changed to Data but its panel remained MPR. The correction
keeps existing native actions attached and shares nested actions without removal.
A new guard fails if native actions are removed. The finder toolbar action is
hidden as well as its widget so promotion cannot restore it.

Final code gate: 44 focused tests pass, four deselected, six existing SWIG warnings,
direct exit 0; 463 mirror pairs match. The second fresh source-workstation launch
passes native menu acceptance: Data, Markups, Models, Segment Editor,
Segmentations, Volume Rendering and Volumes each display their corresponding
panel, and Home / MPR returns to the populated MPR panel with the menu bar intact.
Eight flat options remain on repeated opening; the finder is absent. The source
volume remains rendered throughout. Segment Editor creates an empty in-memory
segmentation; no painting, inference, export or patient-file save was performed.
This is module-navigation acceptance, not validation of every editing operation.
The viewer is left open on Home / MPR. Broad panel contrast, native version notice,
navigation-arrow styling and small-screen extension sizing remain separate items.

The existing test-control client remains unavailable; native UI inspection
reproduced the original symptom. Rollback: revert curated dropdown additions in presentation.py
and synchronize its mirror; preserve the preceding PythonQt startup fix.

## Module panel appearance follow-up

All eight curated tools now have a common AI-PACS heading, concise title and
purpose caption. A module-scoped navy/cyan stylesheet improves labels, numeric
inputs, tables, buttons and collapsible sections. Measurements has seven original
line-style creation icons. Dropdown labels match the panel headings. The image
viewports and scene values are outside the styling scope.

Two fail-before guards cover idempotent headings, preserved callbacks/disabled
states/values and intact grid positions, spans and stretch. Native Data uses a
grid: the final adapter moves that grid intact into a body below the heading.
Fresh native testing confirmed the heading and existing controls are both visible.
Code gate: 46 focused/adjacent tests passed, four deselected, six existing SWIG
warnings, direct pytest exit 0. All 463 plugin mirror pairs match.

Live GUI gate: after authorized close/reopen from the existing source PACS,
Scene Data, Measurements, 3D Surfaces, Segmentation Editor, Segmentation Manager,
3D Rendering, Image Display and Home / MPR each opened with the new heading and
styled controls. Image Display numeric fields were readable. Returning Home
retained its populated controls and rendered source volume without a duplicate
heading. The viewer remains open on Home. No painting, inference or file export
was performed; this is appearance/navigation acceptance, not editing accuracy.

Remaining scope: some internal segmentation/tree/preset icons and the native
Previous arrow retain upstream styling. The native 0.1 version notice still
requires the documented native rebuild. This final panel theme was checked on
the primary display; a complete repeat on monitor B remains pending. No claim of
complete upstream-brand removal, universal small-screen fit or measured startup
speedup is made. Rollback this slice by removing PANEL_STYLE, PANEL_LABELS,
style_panel and its scheduling hooks/custom measurement symbols, restoring the
prior dropdown labels, and syncing the mirror; preserve the earlier launch and
native-action routing fixes.

## Default window size and shared numeric controls

User requirement: launch in a normal window at 70% of the destination screen's
available width and height; leave Maximize to the user. The native constructor
previously scaled a supplied viewport only, with a fixed-size fallback. Resident
promotion then replaced that geometry with an almost full-screen rectangle; the
legacy standby path explicitly maximized. C++ now uses the destination monitor's
availableGeometry for both branches, including negative screen origins. Resident
presentation uses the same 70% rule and standby promotion uses showNormal.

Four geometry cases failed before the change. Native close/reopen from the source
PACS then showed a normal 1344x722 client on a 1920x1032 work area (window capture
1346x755 including decoration). Real Maximize and Restore returned to this size.
The C++ source was edited, but no native rebuild was performed: this live receipt
verifies resident presentation, not a newly compiled C++ executable.

Numeric controls previously styled buttons without defining arrow artwork and
reserved input space consistently. Qss/numeric_controls.py now supplies a pure
Qt-independent stylesheet with four local SVG chevrons, separate 26px button
targets, reserved text space, hover/pressed/focus and disabled/limit states.
The same helper is used by the base application theme, both Settings variants,
Filter Configuration, storage-cleanup numeric inputs, printing, report editor
and the eight Advanced module panels. Only immutable style/assets are shared;
no Qt widgets, scenes or database dependencies cross runtime boundaries. The
Advanced payload includes the helper/assets and its definition lists them.

The initial border-triangle candidate passed PySide pixel contrast but rendered
as bars under native Qt; it was replaced with explicit SVGs and re-tested after
another authorized viewer restart. Native Home arrows were clearly visible;
real Up changed Sharpness 1.0 to 1.1 and Down restored 1.0. No values were saved.
The zero-value Edge down arrow appeared disabled. Qt tests cover visible target
contrast, stepping, limits, disabled state, fractional steps, NoButtons and SVG
validity/parity. Reference: [Qt stylesheet examples](https://doc.qt.io/qt-6.8/stylesheet-examples.html).

Verification: final launch/theme/package selection 60 passed, four deselected,
six existing SWIG warnings; adjacent settings/storage/report/printing selection
150 passed with six existing SWIG warnings, both direct pytest exit 0. All 464
Python mirror pairs match; the four SVG mirrors are checked by a separate guard.
The documented control client ping remains unavailable. Base Settings live
acceptance requires a fresh human-launched source process and sign-in; the current
main process predates these changes. Monitor B remains deferred as requested.
This is not a blanket audit of every numeric widget or a native build acceptance.

Rollback only this slice: restore prior native/resident default geometry and
standby promotion, remove numeric-style call sites and its shared helper/assets
plus package source entries, then synchronize mirrors. Preserve earlier branding,
Home routing, panel appearance and unrelated storage/printing behavior changes.

## Startup welcome text correction

The known native welcome line is now presented as `Welcome to AI-PACS Advanced
Viewer v3.6.6.` by the existing presentation adapter. The clinical-use disclaimer,
OK action and suppression checkbox state are preserved. Only QMessageBox dialogs
with the exact product greeting and disclaimer are eligible; unrelated errors are
untouched. Existing hidden notices and later Show events are covered without
polling, accepting, hiding or showing any dialog. This corrects the displayed
notice in existing runtimes; it does not rebuild or change native engine metadata.

A fail-before guard verifies text, warning retention, untouched buttons/checkbox
and unrelated error isolation. Final focused code gate: 51 passed, four deselected,
six existing SWIG warnings, direct exit 0; 465 Python mirrors match. Live gate is
pending: native window discovery returned no source PACS or Advanced Viewer.
Rollback only correct_startup_notice, StartupNoticeFilter and installation hooks,
then sync the presentation mirror. Preserve prior panel/numeric/geometry changes.
