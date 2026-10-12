# Advanced Image Analysis: function-specific startup presentations

Owner acceptance recorded: 2026-10-11. Tracking: OPT-56 (interactive lifecycle)
and OPT-51 (brain review). This is a reusable implementation contract, not a
replacement build procedure or a customer installation qualification receipt.

## One native runtime, separate presentation profiles

Reuse the existing customized Slicer native baseline. A function-specific Python
presentation defines its layout, editing controls, anatomical groups and input
artifacts. Brain volumetry and white-matter review use the paired raw/segmented
axial, coronal and sagittal layout. Other modules may define different layouts;
they must preserve their own scene, process ownership and editing contracts.
Do not create another native executable merely to change a layout.

The resident Advanced MPR viewer and headless computation remain separate
execution domains. The brain correction launcher is an on-demand interactive
session; its lifecycle must not be substituted for resident MPR warmup.
See [resident runtime](ADVANCED_ANALYSIS_RESIDENT_RUNTIME.md).

## Prepare before exposing the first window

1. A PACS background worker validates the session and runtime, stages physical
   Python startup files, and launches one owned interactive process. File IO,
   process checks and preparation must not block the PACS Qt GUI thread.
2. Pass a directory containing only the early scripted bootstrap through
   `--additional-module-paths`. Its constructor installs the Qt event filter
   before the native main window is constructed/shown. Gate the bootstrap on
   explicit session intent, rather than changing global user settings.
3. On `Polish`/`Show` of `qSlicerMainWindow`, apply
   `Qt.WA_DontShowOnScreen` and zero opacity while preparation is incomplete.
   Retain the guard on the Slicer Python module so its callbacks stay alive.
4. The presentation script loads the image and mask, builds the final layout,
   binds editing controls and initializes segment visibility while off desktop.
5. Only after preparation, mark the guard ready, remove its event filter, hide
   the window, clear `WA_DontShowOnScreen`, restore opacity and show it once.
   Release the guard before reporting initialization failure too. If no main
   window exists, terminate with a clear failure rather than leaving a hidden
   process indefinitely.

The implemented reference is
[`AIPacsBrainReviewStartup.py`](../../modules/ai_imaging/eagle_eye_brain/AIPacsBrainReviewStartup.py),
with the worker launcher in
[`manual_review.py`](../../modules/ai_imaging/eagle_eye_brain/manual_review.py)
and presentation/release logic in
[`manual_slicer.py`](../../modules/ai_imaging/eagle_eye_brain/manual_slicer.py).
Future functions should reuse this lifecycle pattern with their own explicit
session/profile contract; they should not inherit brain-specific mask semantics.

`--no-splash` and `--launcher-no-splash` suppress two splash layers; Windows
`SW_HIDE` is supplementary. These alone do not suppress the default main window.
Hiding in `--python-script` is too late for the first native show. Opacity alone
can leave an invisible taskbar entry. Do not use `--no-main-window` for an
interactive editor: it prevents the required main window from being constructed.
That flag remains appropriate for separate headless computation.

## Editing and process lifecycle

Brain starts with segments hidden and uses anatomical grouping inside the native
Segment Editor list below Show 3D, retaining its resizable frame. Raw panels stay
unmasked beside their segmented counterparts. Do not add a duplicate region
selector above the native list or automatically alter labels to match a reference.

A saved session path is not proof that an editor is running. Check the owned
process handle and session-specific PID/script identity on the worker. Reject a
duplicate live editor; after close, reopen the same session and validated saved
correction. Preserve original image, original mask, label identities and manifest.
Saving and applying a correction to the authenticated server remain explicit
actions. Product controls say Manual Correction / Advanced Image Analysis;
technical dependencies and required acknowledgements remain documented.

## Packaging contract for both backends

The native runtime does not need recompilation for these Python changes. However,
the new application payload must be built and installed: an older installer is
not updated by source changes.

Both backend inputs explicitly include the physical bootstrap alongside
`manual_slicer.py` and `slicer_worker.py` under
`modules/ai_imaging/eagle_eye_brain`:

- PyInstaller: `builder/spec/spec_utils.py::app_a_datas`.
- Nuitka: `builder nuitka/AIPacs_nuitka.spec.py::OPTIONAL_DATA`.

Python import discovery is insufficient because the external runtime reads these
files from disk. Keep the isolated bootstrap directory separate from the main
correction script so the module scanner cannot import it as a scripted module.
Resolve installed paths through the application runtime; do not hardcode a
developer checkout, host drive, patient path or saved Slicer settings. Staged
runtime scripts are application code; patient images, masks, sessions, credentials
and reports never belong in installer assets.

Before build handoff, reconcile local/Razi Developer sources with hash evidence,
verify required mirrors, and follow [BUILD.md](../../BUILD.md) and RELEASE.md.
Use a fresh selected asset cache where required by the native baseline runbook.
Inspect each backend's extracted/installed payload for all three physical scripts
and verify their hashes against the candidate source. Source declarations and
unit tests are necessary but do not prove frozen installation behavior.

## Acceptance evidence and next-candidate checks

On 2026-10-11 the physician reported a fresh source test with no initial default
window flash and no temporary taskbar application appearance. This accepts those
two observed startup behaviors. It does not establish installed portability or
the separate same-PACS close/reopen acceptance gate.

Automated guards cover early off-desktop preparation, successful/error release,
physical bootstrap packaging, isolated module staging and process/session reopen:
`test_brain_startup_visibility.py`, `test_manual_brain_review.py`,
`test_brain_review_views.py`, and `test_brain_review_reopen.py` under
`tests/code/ai_imaging`. The last related focused suite passed 48 tests.
See [implementation evidence](../reports/BRAIN_PAIRED_REVIEW_UI_2026-10-11.md).

For the exact newly built candidate on the qualification PC, record independently:

- First launch shows only the final presentation, with no default frame or
  temporary taskbar entry; loading and error states remain understandable.
- Images load; paired panels navigate together; groups, resize grip and editing
  controls work for both volumetry and white-matter sessions.
- Save, close and reopen within one PACS lifetime retain corrections; applying a
  mask returns to the authenticated server and produces the updated result.
- PACS remains usable during preparation; the normal Advanced MPR presentation
  and unrelated module launch paths still work.
- Both installed backend payloads resolve their bundled files without a source
  checkout or another host's settings. Record hardware/rendering and candidate
  identity. Do not count an offscreen Qt test as Windows taskbar acceptance.

Current customer-installation acceptance and full Developer reconciliation remain
pending. No native rebuild or release installer was produced for this change.


## Readiness acknowledgement and immediate reopen follow-up

The client preparation future must remain pending until the presentation reports
ready, rather than completing on Popen. Brain uses a unique per-launch token in
launch-request.json and an atomic editor-state.json acknowledgement, published
after the final window is revealed and slice views reset. A stale acknowledgement
from a previous launch cannot complete a new request. Errors publish error for the
same token; a bounded 180-second wait reports loading uncertainty without killing
an editor. These session files stay private and are not installer assets.

Before reopening, the worker allows up to five seconds for the preceding process
to exit. It never forces closure or launches a duplicate if still alive. This
readiness/exit-grace follow-up requires fresh source GUI acceptance separately
from the physician's earlier flash/taskbar acceptance.


## Settle initial layout constraints before desktop exposure

Do not release the guard and then perform initial layout activation or slice
fitting. The Brain presentation now logically shows its prepared window while
WA_DontShowOnScreen is active, activates the native layout on queued event turns,
and waits for three unchanged size/minimumSizeHint/sizeHint samples at 50-ms
intervals, bounded at two seconds. It then resets slice views, releases the early
guard and acknowledges readiness. This avoids exposing pending initial layout
size propagation; it does not impose a fixed window size or prevent manual resize.
The actual Windows outer-frame growth acceptance remains pending. Offscreen Qt
verification is separate from native desktop behavior.


## Editor artwork without another native rebuild

The shared viewer_chrome.py companion draws original AI-PACS tool icons using
Qt QPainter/QPainterPath, with an explicit QBrush for PythonQt compatibility.
No separate SVG/PNG files or developer font installation are needed. Both Client
backend mappings ship that physical companion; the packaging guard checks
its exact source/destination alongside bootstrap and worker files.

brand_review_editor changes only named native action buttons and effect buttons
inside EffectsGroupBox. Preserve text/tooltips, object names, connected actions,
selected/enabled states and editing semantics. Its scoped icon guard survives
native icon refresh; retain its Python wrapper for the session lifetime. Apply
branding before initial layout settling, never through a delayed post-show theme
change. Keep legal notices and dependency acknowledgements intact. Future profiles
may reuse the artwork and styling pattern without inheriting brain mask logic.

For installed acceptance, verify first presentation, native Show 3D toggle/icon
refresh, tool selection, disabled states, editing/save/reopen and server apply on
the exact customer candidate. Source declarations and synthetic native Qt checks
are not a substitute for installed qualification.

### Review navigation and hover states

The dedicated review process calls brand_review_chrome before settling its first
frame. It hides the menu bar, decorates the native module selector, module menus,
history and Previous/Next buttons in place, and retains a parent-owned guard.
Do not remove/recreate native module actions: their connections maintain module
selection and history. Menu Show and button Paint events restore presentation
after native refresh. This profile does not alter the general viewer menus.

Artwork supplies all eight Qt mode/state combinations explicitly. Active,
selected and checked artwork is violet; disabled artwork is muted. Button-local
styles override native class styles, retain constant border widths across states,
and keep help text readable. No delayed theme swap or external image asset is
needed. The native PythonQt probe must cover QIcon variants as well as editor
and navigation controls; PySide6 alone cannot prove PythonQt compatibility.

### Common chrome versus function-specific layout (owner clarification)

All customized Advanced Viewer entry points use viewer_chrome.py: the general
presentation adapter installs it at startup, and Brain correction stages the
same physical file beside its space-free script. Artwork, hover states, native
module navigation and hidden top menus belong to this common layer. Pin,
maximize/restore, fit field of view, linking, orientation/image selectors,
visibility, interpolation, slab/ruler/options and slice-slider styling are common
too. Native labels, tooltips, callbacks, values, checked/enabled states and MRML
bindings remain authoritative. Never rename or rebuild native actions to style them.

An application event filter covers late-created module tools and view controllers
on Polish/Show; existing icon guards restore artwork after native refresh. It is
owned by the main window and retained by the presentation adapter. No polling,
scene changes, layout selection or image processing belongs in this layer.
Brain's paired raw/segmented views and grouped anatomy list remain in
manual_slicer.py and must not be installed by general presentation.

For direct launches from paths containing spaces, a unique space-free runpy
bootstrap executes the original startup path, preserving __file__ and companion
resolution. Resident launches already resolve the original startup source.
The shared companion is checked in both physical installer data mappings and
PRESENTATION_COMPANIONS; the Advanced MPR mirror ships it as source. This applies
to Client Standard/ARM whenever the Advanced Viewer payload is installed. Server
headless analysis does not gain a GUI; only interactive viewer sessions use it.
Next installed qualification must cover both a general MPR session and Brain
correction, module switching, view controls, editing/save/reopen and server apply.


### Compact viewport controls

Viewport buttons use 14 px artwork without the editor accent stroke, transparent
borders at rest and 1 px padding. Effects/navigation remain 20 px. Compact styling
is selected by view-controller ancestry, not by Brain layout name. Slider handles
are smaller; orientation/image selectors keep their native text/data and use
14 px icons. Controller labels use explicit readable foreground colors. Keep
borders constant across hover/checked states and do not fix the outer window size.


### Segment actions, module symbols and position readout

Common segment actions (Add, Remove, Show 3D, manager switch and source-volume
SpecifyGeometryButton) use 16 px compact artwork and a lighter action strip.
Native geometry behavior/help is retained. Core module names and menu categories
map to distinct original symbols; module selector combo items use the same mapping.
Do not replace native QAction objects or item data to brand their presentation.
View-controller spin boxes/line edits explicitly style foreground, background and
selection contrast, keeping slice position, suffix, decimals and range untouched.
These rules apply in general MPR and function-specific sessions alike.
