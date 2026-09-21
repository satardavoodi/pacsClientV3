# Eagle Eye workspace-first entry

Status: implemented and automated-verified; live source-build acceptance pending.

## Requested behavior

Opening Eagle Eye from the viewer toolbar, legacy image tool, or sidebar opens
the existing study workspace. The user selects **Choose Function** inside that
workspace before any analysis configuration or execution. Cancel leaves the
viewer, Data Set, Model Training and Reception Data available.

The function labels are Mammography Pathology Analysis, Bone Age AI, and Lumbar
Pathology Analysis. Brain offers Whole Brain Segmentation and the explicitly
disabled Lesion Detection placeholder. No new diagnostic capability was added.

## Implementation and ownership

- `eagle_eye_workspace.py` owns navigation and the in-workspace function action.
  Entry uses the active series' study UID before the primary patient-tab UID;
  it does not resolve a protocol, probe files, or submit a model request.
- `AiMainWindow` constructs Imaging Tools for Brain as well as MG/DX/Lumbar.
  Secondary data/training/reception tabs remain lazy. The function button becomes
  available on the existing imaging-ready signal. Tab reuse only refreshes saved
  results; it never prompts or starts a run.
- Brain uses a single-pane independent VTK viewer. Its existing volumetry widget
  is created lazily in a reusable, scrollable owned dialog. Selecting segmentation
  continues to the existing explicit T1 series/protocol confirmation. Closing
  the popup requests cancellation, including pending series enumeration, so a
  late result cannot unexpectedly raise a sequence picker. The lesion option
  remains unavailable. PDF, reference and segmentation algorithms are unchanged.
- MG/DX retain their existing native workers, sensitivity/re-run configuration,
  storage and overlays after explicit selection. A completion callback refreshes
  the current workspace rather than creating another tab.
- Lumbar retains its DICOM resolver and validated one-shot session handoff, but
  runs them after function selection. First paint no longer starts capture.
  Completion starts capture only when the resolved study matches the workspace.
  A new run cannot replace a running capture/probe/analysis.
- Legion Consult retains its source-owned Fast Viewer ROI workflow. The workspace
  stores a weak source reference and an identity tuple; choosing Legion validates
  that study/series identity before returning to the source viewer. This does not
  share VTK objects or move its ROI implementation into the VTK domain.
- The workstation removes tabs using `deleteLater`, without `closeEvent`.
  Workspace destruction therefore explicitly invokes existing controller teardown
  before child workers are destroyed. This extends the OPT-51 lifecycle boundary.

The new ai_imaging module is internal application source, covered by existing
package collection. Only `modules/viewer/interactor_styles/ai_chat_interactorstyle.py`
has a changed plugin payload mirror; it was synchronized with the canonical tool.

## Verification

- Seven initial guards failed against the original navigation, first-paint and
  Brain-tab behavior before production changes (exit 1).
- Additional pre-fix checks reproduced the alternate image-tool entry and missing
  parent-destruction teardown. A synthetic visual check also found the Brain popup
  expanding to 1816 pixels; its width guard failed before wrapping and scrolling.
- `tests/code/ai_imaging/test_eagle_eye_workspace_entry.py`: 27 passing synthetic
  behavior/UI/ownership guards. No live database or server is used by these guards.
- Entire ai_imaging selection plus viewer dialog-liveness, UI-stall boundaries and
  MPR interaction guards: 1165 passed, 8 existing xfails, process exit 0.
- After final popup layout adjustments: 99 related workspace/Brain/catalog tests
  passed. Three synthetic Qt screenshots were rendered and visually reviewed with
  a placeholder image area, not clinical images or a live viewer session.
- Plugin mirror verification: 462 pairs match. Four builder inclusion/parity
  guards passed with process exit 0; no installer was built.

Obsolete tests requiring pre-entry function selection or a separate Brain page
were updated to assert the requested navigation boundary. DICOM protocol, identity,
Brain confirmation, worker and result-history guards remain active.

## Deferred work and live acceptance

This is a workflow/UI correction, not a responsiveness optimization. Native run
overlays remain modal; existing synchronous lumbar preflight, viewer construction
and dataset refresh costs are not claimed fixed. Keep subsequent blocking work in
the existing OPT-01/OPT-27/OPT-58 plan. Frame/window-level/zoom transfer is not a new
contract in this change; study loading and in-workspace image selection are retained.

On the human-launched source build, verify toolbar and sidebar entry for MG, DX,
Lumbar and Brain; cancel Function and use the other tabs; run/reopen each supported
analysis; close the workspace during processing; verify Brain sequence confirmation
and completed PDF controls. No model request or clinical acceptance was performed
by this task.

Rollback must remove only this change's navigation, controller, UI and matching
viewer-mirror hunks together. Preserve unrelated worktree changes. No configuration
or database migration is involved.

## Presentation amendment (2026-09-12)

User screenshot review identified a low-prominence primary action, a duplicated
Home group title overlapping the import toolbar, and Patient-only Eagle Eye /
Advanced Analysis navigation beside thumbnails. Choose Function now has a
240 x 52 logical-pixel minimum, bold 16px text and accent styling, retaining its
existing ready-state gate. Imaging Home/Segment groups omit their redundant
titles; AbstractTab defaults remain unchanged for other tabs. The embedded
Patient navigation is hidden as a whole. Its controls remain owned and alive
for inherited callbacks; thumbnails and the normal Patient page are unaffected.

Pre-fix guards failed for all four primary-action modes, the duplicated title,
and visible navigation (exit 1). A synthetic offscreen Qt render verified the
header and import toolbar without clinical data or model execution. Live source
acceptance remains pending. No analysis, decode, rendering or blocking-work
behavior changed. Rollback is scoped to these presentation changes in
ai_mainwindow.py, abstract_tab.py and imaging_tab.py.

Validation: direct `pytest -p no:debugging tests/code/ai_imaging -q --tb=short
--reruns 0` completed with 1136 passed, 8 existing xfails and exit 0.

## Background interaction amendment (2026-09-14)

Analysis popups are explicitly nonmodal. Continue working in PACS or closing a running popup hides it while its study-owned computation/export continues. Reopen the same Eagle Eye function to see the same progress/result. Cancel stops the computation; closing the owning study/workspace or exiting the application still tears it down. Pending input scans are cancelled on dismissal so selectors cannot appear over another patient. Existing Brain analysis and server-worker locks still prevent incompatible duplicate jobs.

MG/DX server jobs use compact nonmodal progress. Lumbar results already use nonmodal panels. This does not promise zero CPU contention, nor does it offload the remaining synchronous preflight/VTK preparation identified by OPT-58. Six regression guards, 93 related tests and 3 builder guards pass; 462 mirrors match. Fresh-source live acceptance of this amendment is pending: the active older process is retained to finish its real lesion job. Native Home navigation and image viewing while that job runs were observed successfully, independently of the new code.

## Active series and background activity (2026-09-20)

Choose Function now carries the exact SeriesInstanceUID from the loaded Eagle Eye
viewport, falling back to the immutable 2D-viewer entry selection only when the
workspace has no loaded viewport. A mismatched study cannot supply that fallback.
Review sessions are retained per function and selected series; switching input
series does not overwrite an earlier reader correction or show its result as the
new analysis. A late Total Spine result cannot activate a different series tab.

Total Spine selects and loads a single available radiograph in that series.
DICOM ViewPosition determines AP/PA versus lateral; missing or ambiguous tags
prompt only for projection. SeriesDescription is not used to infer projection.
The reader still marks a thoracolumbar ROI, then coronal inference starts directly.
Multiple images within one series require image selection. Missing local inputs
never silently fall back to another series. Lateral opens the manual/SAM review
route because the installed automatic landmark checkpoint is coronal-only.

Lower-limb Alignment selects the same input series, loads a sole image, and starts
AI proposals without falsely marking orientation or landmarks as reader-reviewed.
Brain preselects the active primary T1; lesion analysis preselects an identifiable
T1/FLAIR role while retaining the required second input and protocol confirmation.
After the required input confirmation and DICOM demographics preparation, these
Function-launched Brain workflows start without another Run click. Explicit
standalone/manual Brain workflows keep their existing behavior.

The common Brain/lesion/Alignment/Total Spine preparation popup now shows current
worker status and an indeterminate activity bar during work. Lumbar capture and
analysis have one reusable nonmodal progress popup, updated by actual stage events
and disposed on terminal status or teardown. MG/DX and Legion retain their existing
progress windows. No invented completion percentages are displayed. Model/file work
remains in its existing worker domain.

Validation: `test_eagle_eye_selected_series.py` contains 12 synthetic Qt guards.
Seven targeted requirement guards were observed failing before their respective
changes; all 12 now pass. The focused workspace, background, alignment, spine,
Brain/lesion, lumbar workflow and builder selection passed 197 tests (exit 0;
six third-party deprecation warnings). All 468 existing plugin mirror pairs match;
none of the changed files has an existing payload mirror. No live database or
patient fixtures were added.

Live gate: documented local Test Control `ping` and `list_actions` succeeded.
The running source session predates these changes; native acceptance of the new
handoff/progress flow remains pending a fresh human source launch and login.
No hot reload or unrequested restart was performed. Required live cases: entry
from 2D and Eagle Eye, exact input series, unknown projection, coronal ROI-to-run,
series switch preserving prior edits, dismiss/reopen progress and cancellation.
Rollback: remove only this amendment's selected-series/session, activity display,
and automatic continuation hunks plus its new guard; preserve unrelated work.

## Preparation and result tabs (2026-09-20)

Imaging Tools now contains the existing viewing and preparation tools, without
Bone Age or Mammography review forms in its left sidebar. No new ROI, segmentation
or future lesion-annotation feature was introduced by this presentation change.

`eagle_eye_result_tabs.AnalysisResultTabs` appends a Mammography or Bone Age tab
when an actual run/result is available. Saved results add a tab without stealing
the initial Imaging Tools selection. Explicitly completed MG/DX Function runs
activate their result tab. Empty/error Bone Age payloads do not create results.
Panels are constructed once and retained, preserving unsaved reader corrections.
The existing Mammography run selector and feedback actions remain connected.

Each result page places its review panel beside the existing image viewport.
The same toolbar and viewport container move between preparation and the active
result page; no extra viewer, decoder, render domain, or copied mutable image state
is created. Result-page activation keeps the existing patient viewer active.
Switching to another workspace tab returns the viewport to Imaging Tools.
This Qt reparenting still needs native VTK rendering acceptance on a fresh source
run; synthetic widget ownership tests are not native image-rendering evidence.

Bone Age result/feedback loading uses the existing background JSON worker.
The result panel applies that payload without rereading files on the GUI thread,
and a new result refresh does not overwrite unsaved reader corrections. Bone Age
loading no longer clears the Mammography feature editor.

Validation: two presentation guards failed before the implementation; all six
new guards now pass, including a real ImagingToolsTab/MG panel build with a
synthetic patient widget. Focused result refresh, module routing, workspace,
background and related UI tests: 94 passed, exit 0 (six third-party deprecation
warnings). Existing 468 plugin mirror pairs match; the changed UI/helper files
have no existing payload mirrors. Diff whitespace checks passed.

Live gate: local Test Control ping/action discovery succeeds, but the running
source application predates this presentation change. Native MG and Bone Age
result refresh, viewport preservation/rendering and correction persistence across
tab switches remain pending fresh-source launch/login. No restart or hot reload
was performed. Rollback only the result-tab helper/integration, sidebar routing,
Bone Age payload application and associated guards; retain earlier workspace work.

## Segment preparation investigation (2026-09-20; proposal, not an installed tool)

Current Segment exposes Polygon only. `ImagingToolsTab.toggle_tool` targets
`lst_nodes_viewer[0]`, not the selected viewport. The polygon interactor routes a
closed contour through the configured segmentation-server path, unless an explicit
local callback handles it. It is not currently local intensity-based region growing.
Do not describe the existing button as the proposed semi-automatic tool.

A bounded local seed+intensity workflow is available in installed VTK 9.6.1:
`vtkImageThresholdConnectivity` supports lower/upper intensity limits, seed points,
and slice bounds/stencils. SimpleITK ConnectedThreshold is also installed.
A synthetic two-component image test selected exactly the seeded 25-pixel component
in both libraries. No patient data, network inference or model download was used.

Proposed first increment: active image/series/frame binding; a reader ROI and seed;
lower/upper intensity controls; cancellable background mask generation; colored
preview; explicit Apply/Discard and subsequent brush/erase/Undo. Process original
scalar values before display windowing; label DX/MG/MR as image intensity. HU labels
require validated CT modality conversion and units. Keep masks independent of the
source image and bind them to source identity/geometry. Initial scope is 2D; a 3D
extension needs separate volume/geometry and resource acceptance. This investigation
does not implement the new segmentation UI or authorize a server request.

Primary references:
- https://vtk.org/doc/nightly/html/classvtkImageThresholdConnectivity.html
- https://simpleitk.org/doxygen/latest/html/classitk_1_1simple_1_1ConnectedThresholdImageFilter.html
- https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_c.8.2.html

Viewer integration findings are handed off in the existing VTK domains review;
do not alter the shared download/cache pipeline to implement this tool.
