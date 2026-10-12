# Brain paired review UI - 2026-10-11

## Behavior

The existing isolated manual Slicer script now opens axial, coronal and sagittal
raw/segmentation pairs. Raw is left; overlay is right. Slice position, orientation,
pan and field of view synchronize within each pair. Segment visibility is restricted
to the three overlay views. All labels start hidden.

An embedded checkbox tree groups native region names into medial temporal,
cerebellum, basal ganglia, thalamus/diencephalon, brainstem, CSF/ventricles,
cerebral white matter and cortical lobar/cingulate/insular groups. Selecting a
leaf shows it and sets the native Segment Editor target. Group checkboxes toggle
children; Hide all regions resets visibility. Native editor visibility changes
are reflected in the tree. Unknown names remain under Other structures.

Grouping changes presentation only: no union, relabeling, lobar measurement,
resampling, threshold or mask erosion is applied. The existing sparse numeric
label-preserving export and Apply mask on server workflow remain authoritative.
Binary lesion results use the same paired views with a single White-matter lesion
candidates group; this does not invent anatomical lesion classes.

## Model versus mask adjustment

SynthSeg offers a robust inference variant, not an amygdala-specific margin knob.
Slicer Margin/Smoothing modify mask geometry and require reviewed recalculation;
opacity changes presentation only. Do not tune volumes to a comparator's numbers.
Sources: https://surfer.nmr.mgh.harvard.edu/fswiki/SynthSeg and
https://slicer.readthedocs.io/en/5.8/user_guide/modules/segmenteditor.html .

## Evidence and limits

- Three new presentation guards failed before implementation (missing behavior).
- Focused manual-review/presentation guards: 18 passed before teardown guard;
  final count recorded in the session receipt.
- Brain/lesion builder guards: 13 passed. Mirror dry-run: zero drift;
  verifier: 529 pairs match. This script is explicitly shipped as App A data by
  builder/spec/spec_utils.py and staged by prepare_review; no new dependency.
- In the existing source-built Slicer session: 98 native segments in 13 groups,
  all initially hidden, group checkbox, leaf selection, and paired slice scrolling
  exercised. Raw views remained without segmentation. No masks were edited/saved.
- The source PACS control probe failed (listener unavailable). A fresh end-to-end
  PACS launch -> correction -> save -> Apply mask on server remains pending.
- Current live Slicer contains the tested helper functions added to the existing
  review panel to preserve unsaved edits; this is not a fresh launcher acceptance.
- Existing custom Slicer font warnings and the pre-existing MaskVolume effect
  setup warning were observed; this patch does not claim to repair them.

## Developer and build handoff

Affected canonical script matched Razi r10 SHA-256 before editing:
24ea03a6d154fa8ffea254a5ed970406a8ade239f6563763950b7b8473cfada8.
The Eagle Eye coordinator is reconciling a concurrent r11 snapshot. Stage this
scoped delta separately; do not overwrite executing r10 or an owned r11 snapshot.
Complete Developer inventory parity and activation remain pending reconciliation.
Do not claim build readiness from a scoped hash match.

Standard Client, ARM64-emulated Client and Server GUI use this same review source;
PyInstaller/Nuitka produced-artifact acceptance remains pending for all applicable
profiles. Headless Server service UI is not applicable. No build or restart run.
Rollback is limited to this presentation change in manual_slicer.py; preserve
pre-existing working-tree edits and all review data.

## Follow-up: native segment-list placement

The duplicate browser previously inserted above the native editor was rejected
by the physician. The grouped Name tree now occupies the existing
SegmentsTableView slot below Add / Remove / Show 3D, beside native effects.
The hidden native table and its MRML model stay alive for the editor's existing
selection/operation contract. Segment icons use their native display colors.
The tree inherits the native SegmentsTableResizableFrame height grip; its old
220-pixel maximum was removed. No extra region list is added above the editor.

The placement guard failed before this follow-up and passes afterward. Focused
manual/presentation checks: 20 passed, exit 0. Source Slicer was closed at the
live check; fresh native placement/height acceptance is pending human opening
Manual Correction. The prior paired-view live pass does not certify this update.
Razi r12/source report and manual-script base hashes were inspected and matched
before these follow-up edits. New immutable scoped staging is required; no
executing source is overwritten.

## Follow-up: interactive initialization

The fresh source UI confirmed the grouped tree in the native table slot, with
no duplicate anatomy list. Live initialization exposed a PythonQt exception:
arbitrary attributes are forbidden on QWidget. Callback ownership now belongs
to the Python slicer module. A synthetic guard failed before this fix.

The volume and six slice composites were loaded, and the background and final
RGBA pipeline contained nonzero image pixels, while the displayed panes were
black. The process inherited workstation software-GL overrides and used Mesa
12.0.0-rc2 llvmpipe. This is evidence of a rendering problem, not missing data;
renderer causation remains pending a fresh desktop-GL acceptance run.

Interactive manual review now defaults to its own desktop OpenGL environment;
the explicit AIPACS_MANUAL_REVIEW_SOFTWARE_RENDERING=1 override preserves software
mode for hosts that require it. This does not change headless analysis settings.
Launch uses --no-main-window; the existing packaged Python script reveals the
window only after setup, or displays an initialization error. No native Slicer
recompilation is required. The next Client build must include these scripts.

Combined focused checks: 47 passed, exit 0. Plugin mirrors: 529 pairs match.
Fresh launch, resize-handle interaction and produced Client artifact acceptance
remain pending. Do not label current black-pane runtime as a GUI pass.

## Follow-up: no-window launch regression

Fresh physician retest failed before the editor could open. The private launch
trace confirmed that --no-main-window prevents main-window construction in this
custom Slicer. selectModule therefore raised "Could not find main window"; the
error path then incorrectly attempted None.show(). The previous r2 launch
candidate is superseded and must not be activated.

The interactive launch now omits that headless flag and uses Windows
STARTF_USESHOWWINDOW / SW_HIDE. The staged script hides the constructed window
during image import, then reveals the prepared review. If no window exists,
failure handling exits rather than raising a second NoneType error. These changes
affect both volumetry and lesion manual review; headless analysis is unchanged.
The launch regression guard failed before the correction. Fresh source GUI
verification and complete Developer reconciliation remain pending.

## Follow-up: launcher flash and reference colour audit

The physician observed a brief startup flash before the prepared six-view editor.
The launch command suppressed the application splash but omitted CTK's separate
--launcher-no-splash option. Both are now supplied; the single-Popen guard failed
before this correction. This addresses launcher splash only. The initial native
main-window show can precede the Python script; a fresh visual launch is required
to determine whether a remaining main-window flash needs a native startup hook.
Do not describe splash suppression as proof of a flicker-free main window.

A separate reference audit found that adding numeric position labels changed the
red rule from >25% beyond the nearest endpoint to every outside-interval value.
The >25% rule is restored while retaining the textual position. Exactly 25% and
smaller departures stay uncoloured. Cortical analogues are never red. The chart
uses amber for unconfirmed departures, blue within interval and purple analogues.
These are comparison/review flags, never a pathological diagnosis. Same-patient
volBrain comparisons and private review PDFs are retained outside this repository.
Synthetic guards failed before correction; focused checks: 69 passed, exit 0.
Fresh affected-workflow GUI acceptance, new scoped Razi staging and full Developer
reconciliation remain pending. No release or native Slicer rebuild was performed.

## Confirmed follow-up: generic main-window flash

The fresh physician retest still displayed the generic custom Slicer window
before the paired brain review. Suppressing either splash did not address this.
Upstream qSlicerApplicationHelper.hxx shows the main window before scheduling
handleCommandLineArguments, so --python-script hides it only after exposure.

A session-only hidden scripted module, AIPacsBrainReviewStartup, is staged beside
the correction script and supplied through --additional-module-paths. Slicer
instantiates additional modules before constructing the main window. Its Qt
application event filter makes only qSlicerMainWindow transparent on Polish/Show,
prior to preparation. The correction script releases the guard and restores full
opacity when ready, or before displaying an initialization error. Normal MPR and
headless inference receive no module path or review environment and are unchanged.
There is one Popen, no close/relaunch cycle, no polling, no native core recompilation.
Both PyInstaller and Nuitka ship the physical bootstrap script.

Two reproduction guards failed before implementation. Updated focused suite:
39 passed, exit 0 (three existing SWIG deprecation warnings). Existing PACS test
control listener is unavailable; fresh source GUI launch acceptance remains
pending. This supersedes the r4 splash-only explanation. Do not claim a final
flicker-free acceptance until the physician's fresh launch is observed.

## Follow-up: taskbar exposure during preparation

Physician acceptance confirms r5 removed the visible generic-layout flash, but
Windows still exposed a transient taskbar entry during the opacity-only phase.
A transparent top-level window is still a desktop window. The startup event
filter now sets WA_DontShowOnScreen during Polish/Show. Release hides the logical
preparation window, clears that attribute, restores opacity and exposes the final
window. The failure path uses the same release operation. The guard is scoped to
qSlicerMainWindow and the session-only additional module; other Slicer workflows
are unchanged. The strengthened synthetic guard failed before this change;
39 focused/builder checks pass afterward. Windows taskbar acceptance is pending.

Architecture: retain one custom native Slicer runtime with per-function Python
startup/presentation profiles. Brain volumetry and white-matter review share this
profile; other functions retain theirs. Separate native executables per anatomy
are unnecessary for this correction. A native startup lifecycle hook may be a
future improvement if an independently verified platform-specific gap remains;
no native change/rebuild was made or claimed. PyInstaller/Nuitka both already
include the physical bootstrap file. The open source Client need not restart for
this bootstrap-only update: prepare_review copies the external script on each
new launch. Preserve edits and close only the prior Slicer before testing again.

## Follow-up: reopening an exited editor and product-facing naming

The Client's _manual_open returned whenever _manual_session was populated. That
field identifies retained draft data, not a live editor. Closing Advanced Image
Analysis therefore permanently blocked reopening until the Client restarted.
The UI now dispatches existing-session reopening to its existing worker executor.
A locked launch service checks the owned Popen and a private editor PID/script
marker; a reused PID with unrelated command line is not treated as that editor.
Running editors remain protected against duplicate launches. Closed editors use
the same session; a validated saved corrected mask is copied to editor-input.nii.gz,
leaving the original mask, manifest and inference untouched. Recalculation remains
server-owned for remote results. No file/process checks run on the PACS GUI thread.

The button is now "Manual Correction — Advanced Image Analysis" for volumetry and
its inherited lesion workflow. Related status/error/progress text uses the same
product name; technical identifiers and required third-party notices are retained.
Two regression reproductions failed before the fix; 48 focused/history/builder
guards pass. The test control listener is unavailable. Fresh source acceptance
must cover open, close, reopen in one PACS lifetime and the renamed button; it is
pending. Source Client restart is required for this UI/worker logic change.
No native build or release was performed. Scoped staging is not full-source
Developer reconciliation or customer-installation acceptance.


## Physician startup acceptance, 2026-10-11

The physician reports that the fresh source test no longer exposes the initial
default viewer frame or a temporary taskbar application entry. This supersedes
the pending acceptance status for those two startup observations only. Same-PACS
close/reopen and the exact installed-candidate acceptance remain separate gates.
The reusable architecture and next-build checklist are in
[Advanced Image Analysis startup profiles](../modules/ADVANCED_IMAGE_ANALYSIS_STARTUP_PROFILES.md).
No native runtime rebuild or installer build was performed.


## Immediate reopen and readiness activity, 2026-10-11

The physician confirmed reopening after a short delay, but immediate reopening
failed while the prior editor was still shutting down. The client also stopped
its preparation indicator immediately after Popen, before images/layout were
ready. This is a lifecycle/readiness boundary, not another native splash defect.

The launch worker now allows up to five seconds for the previous owned process
to exit, without terminating it or creating a duplicate. A still-open process
produces an explicit bounded error. The Brain widget dispatches open_review_ready;
its future remains pending until a launch-token-bound, atomically written ready
acknowledgement follows presentation and slice reset. Initialization failures
publish error instead. A 180-second readiness limit ends with an honest loading
message; it does not kill the editor. PACS IO/waiting remains on its executor.
The existing activity indicator remains visible for this pending future.

Three new guards failed before implementation; focused readiness/reopen, startup
and editing checks passed afterward. Source GUI acceptance for this new delta is
pending: the documented test-control ping currently reports Invalid name. Prior
physician flash/taskbar acceptance remains valid for its tested revision, not
proof of this readiness change. Both Client backend physical-script mappings
remain unchanged. Scoped inactive staging does not activate Razi or establish
full Developer reconciliation. No native build or installer was produced.

Verification receipt: 53 focused editing/history/startup/backend guards passed;
529 plugin mirror pairs match with zero drift. No installed GUI result claimed.


## Outer-frame growth follow-up, 2026-10-11

The physician accepted the readiness indicator and reopening behavior, then
reported slight growth of the outer editor frame several seconds after opening.
They explicitly distinguished this from slice-image zoom. No explicit delayed
resize was found in the Brain presentation or inspected native customization.
The current source reveals the frame before queued layout activation and slice
reset; late Qt size-hint/minimum-size propagation is a supported hypothesis, not
an exact Windows trace of the reported event.

prepare_presentation now logically shows the complete editor with
WA_DontShowOnScreen still set, activates its layout over queued event turns and
samples window size, minimumSizeHint and sizeHint. Three unchanged samples at
50-ms intervals precede slice reset, guard release and the ready acknowledgement.
Preparation is bounded at two seconds; no fixed-size constraint or recurring
post-show geometry correction is imposed. Errors use the visible error path.
The absence-of-bootstrap fallback explicitly clears the off-desktop attribute.

A synthetic deferred-size guard failed before implementation. Both a behavioral
ordering test and an actual offscreen QMainWindow test with a deferred minimum
width update now pass. The complete focused suite passed 55 tests with three
existing SWIG deprecations. This is not Windows visual acceptance: the exact
reported outer-frame growth must be retested. The documented control socket is
currently unavailable. New manual_slicer.py is staged from source at each launch,
so a newly opened correction session receives it without another PACS restart.
Preserve any unsaved edits before closing the current editor.

Both backend physical-script declarations already include the modified file;
no native core recompilation or installer build was performed. Full Developer
reconciliation and exact installed-candidate qualification remain pending.


## Physician layout acceptance and editor artwork, 2026-10-11

The physician confirmed the off-desktop layout settling works correctly. This
closes the reported source outer-frame growth scenario for the tested session;
it is not installed-candidate acceptance. They requested original AI-PACS artwork
for Add, Remove, Show 3D, the module-navigation arrow and editing effects.

manual_slicer.py now draws cyan/violet line icons with Qt's painter inside the
already packaged physical presentation script. It targets named native buttons
and EffectsGroupBox descendants, including Paint, Erase, Draw, Scissors, Smoothing,
threshold/contour/region tools and Undo/Redo. Native object names, text, help,
signals, checkable state, enabled state and segmentation logic are retained.
A parent-owned, module-retained event filter restores branded icons when native
Show 3D refresh replaces them. Checked/disabled states keep distinct styling.
Styling is scoped to branded editor buttons and installed before layout settling;
no global native theme, acknowledgement or licensing information is removed.

The behavioral guard failed before implementation, then passed with preserved
click callbacks, tooltip/state, unique artwork and native icon-refresh recovery.
The real customized runtime synthetic probe found 21 native tools. Its first
attempt exposed PythonQt's lack of automatic NoBrush-to-QBrush conversion; explicit
QBrush construction corrected it. Native rendering setup passed afterward.
This native binding probe is separate from live patient-workflow acceptance.
No patient images or identifiers were used in the synthetic probe.

Build inclusion uses the existing physical manual_slicer.py, startup module and
slicer_worker.py mappings. The guard now parses Nuitka OPTIONAL_DATA and checks
all three exact source/destination pairs, as well as actual PyInstaller data input
files. Icons require no additional file assets, network or developer font path.
The next exact installed candidate must qualify these controls in both backends,
normal startup, retained corrections and server apply. Full Developer parity and
installed artifact acceptance remain pending; no release or native rebuild.

Artwork verification receipt: 56 focused guards passed, native icon refresh probe
passed, and 529 plugin mirror pairs match. Source visual acceptance remains pending.

## R12: hover and module navigation presentation

The physician accepted the original replacement editor artwork. Remaining native
hover artwork, module navigation icons and the top menu were requested for change.
Explicit QIcon mode/state pixmaps now prevent native synthesized blue variants;
active/checked artwork and button borders use violet. Border width stays constant.
The review-only menu bar is hidden. Native module/menu actions are decorated in
place, including Home, Data, import, finder, history and Previous/Next; signals,
enabled states, module selection and history remain native. Save correction stays
in the existing inline panel. Legal acknowledgements are preserved.

The new guard failed before implementation (missing chrome decorator), then the
focused matrix passed 57 tests. A synthetic native PythonQt probe passed 21 editor
icons, four navigation icons and eight explicit icon states. No patient data was
used. These are code/binding checks; fresh source workflow visual acceptance and
exact installed candidate acceptance remain separate gates. No release build or
server activation is included. Scoped inactive Razi staging is not full Developer
reconciliation or permission for a build handoff.

## R13: shared Advanced Viewer chrome, with Brain layout kept separate

Owner clarified that editor/module icons, hover states and hidden top menus apply
to every customized viewer, not just Brain. The original artwork moved to the
independent viewer_chrome.py companion; manual_slicer.py retains compatibility
delegates and Brain-only paired views/grouping. General presentation installs the
same common profile. No Brain imaging or anatomy logic is imported by general MPR.

Common styling covers native viewport pin, maximize/restore, fit field of view,
link/visibility, orientation and image selectors, interpolation, slab, ruler,
advanced options and slice slider. Native widget/action identities, text, tooltip,
checked/enabled state, selected item data, slider ranges/values and callbacks are
preserved. Polish/Show handles late module/view creation; Paint guards restore
icons after native refresh. No timer polling or scene/layout mutation is introduced.

The late-controller/editor regression failed before the change (missing icons).
A separate direct-launch guard reproduced lost sibling resolution when a
space-containing startup path was copied to TEMP. A unique runpy bootstrap now
executes the original startup path and retains companion resolution.
Both installer backend mappings, source materialization companion hash checks
and the Advanced MPR mirror include the new file; correction launch stages it.
No native C++ rebuild or release build was run. Fresh source workflow and exact
installed acceptance remain separate required gates. Scoped inactive staging
does not establish full Developer parity or authorize a build handoff.

R13 verification receipt: 104 focused tests passed (exit 0); native PythonQt
probe passed with 33 artwork keys and 20 actual slice-controller buttons;
530 plugin mirror pairs match. Test control ping is unavailable. Fresh source
GUI and exact installed acceptance remain pending. Scoped inactive staging only;
no clinical process/source was overwritten or activated.


## R14: compact viewport headers

Physician screenshot showed oversized boxed controls crowding view titles, with
low-contrast native title labels. View-controller-only styling now uses 14 px
icons, no decorative accent stroke, transparent resting borders and 1 px padding.
Editor effects/navigation remain 20 px. Slider handles/selectors are compact and
controller labels have explicit light foregrounds. No action, scene or geometry
operation was changed. The expanded guard failed before (20 versus required 14)
and passes after. Focused matrix: 104 passed; 530 mirror pairs match. Native
PythonQt probe confirms 14 px Pin/Maximize/Fit icons and 27 px native size hints.
Fresh source screenshot/input acceptance remains pending: no target viewer window
was returned by native window discovery; Test Control Server ping is unavailable.
Installed candidate acceptance and full Developer parity remain separate gates.


## R15: segment action strip, module symbols and slice-position contrast

Physician accepted compact viewport headers. The next screenshot identified the
remaining native source-volume geometry icon, repeated generic module icons and
dark slice-position text. Shared chrome now styles SpecifyGeometryButton, uses
16 px compact segment action artwork, maps core module/menu categories to distinct
symbols, and brands module-selector combo icons. Controller spin boxes/line edits
retain their native position/range/suffix but use explicit readable colors.

The new regression failed before (six module entries shared one symbol), then
passed with distinct artwork, geometry icon, action size, combo data and numeric
position preservation. Focused matrix: 105 passed; 530 mirror pairs match. Native
PythonQt probe passed 39 artwork keys including geometry and 20 viewport controls.
Native window discovery returned no current target, so fresh source screenshot and
input acceptance remain pending, separate from native binding verification.
Both backend physical companion guards remain green. No native rebuild/release
or clinical service activation. Scoped inactive source parity is not full Developer
reconciliation or exact installed-candidate acceptance.
