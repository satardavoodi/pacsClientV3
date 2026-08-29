# Legion Consult Foundation — 2026-08-28

## Decision

`Legion Consult` is a new Eagle Eye function, initially limited to MRI. It is
an attention-directed radiology consultation workflow: the reader selects the
diagnostically relevant series and draws one rectangular ROI around the
suspicious finding. The ROI identifies where analysis should concentrate; it
is not a manual three-dimensional segmentation.

The original foundation ended after a versioned local request manifest was
saved. The 2026-08-29 completion connects that manifest to an off-GUI-thread
evidence builder and the existing Eagle Eye two-stage model transport.

## Entry flow

One click on the existing Eagle Eye toolbar button now opens a function picker.
The first choice preserves the current modality-native behavior:

| Active modality | Native function | Legion Consult |
|---|---|---|
| MG | Mammography Analysis | Visible, disabled |
| DX | Bone Age Analysis | Visible, disabled |
| MR | Lumbar MRI Analysis | Visible, enabled |

Cancel starts nothing. Selecting the native function invokes the unchanged
Eagle Eye pipeline. Selecting Legion Consult starts its separate coordinator.
No Legion state is injected into the existing mammography, bone-age, or lumbar
controllers.

## Series-selection contract

Each configured request must contain these semantic roles:

1. The active source series on which the reader will draw the ROI.
2. One T1 series.
3. One T2 series.

One physical series may fill more than one role. For example, when the source
series is T2-weighted it is not duplicated in the selected series list or image
estimate. Default T1/T2 suggestions use header timing and description evidence,
reuse the source when appropriate, and otherwise prefer the source plane. The
reader can override a suggestion when protocol labels are incomplete or wrong.

All other eligible diagnostic MRI series are optional. The reader may select
individual series or enable `Include all eligible diagnostic series`.
Localizers, scouts, reports, dose/screen captures, calibration/field-map series,
and projection images are excluded. DWI and ADC remain eligible because they
may be diagnostically essential, especially for brain MRI.

The dialog displays the de-duplicated series count and approximate image count.
This is the first cost-control surface; a later capture policy must enforce a
separate image/request budget rather than treating the estimate as a guarantee.

## ROI and geometry contract

The current slice supports the Fast Viewer rectangular ROI tool. Advanced
Viewer support is deliberately deferred until it has its own adapter because
its ROI interaction and geometry domain differ from Fast Viewer.

The completed ROI contributes:

- the source series identity;
- the source slice index;
- four ordered image-pixel corners;
- the same four corners mapped through the Fast Viewer geometry backend into
  DICOM patient LPS coordinates.

The source study and series identities are checked again before ROI activation
and after ROI completion. A series change fails closed. The default attention
corridor is recorded as five slices above and five slices below the source
slice. This is a capture hint, not a lesion-volume claim.

Future plane/oblique mapping must consume the LPS corners through the existing
image synchronization geometry. It must not estimate cross-series locations
from screen coordinates.

## Local request schema

Requests are saved under the workstation AI data root in
`legion_consult/<study>/<session>/request.json` using an atomic temporary-file
replacement. The schema records:

- schema version and UTC session identity;
- `status = configured`;
- `remote_send_status = not_sent`;
- the mandatory role assignments and de-duplicated selected series manifest;
- estimated image count and select-all decision;
- image and LPS ROI corners;
- `slice_padding = 5`.

The manifest contains no image pixels. Logs avoid patient identifiers, study
identifiers, series identifiers, and filesystem paths.

The lifecycle fields are updated atomically when the completed workflow runs:
`configured/not_sent` becomes `analyzing/pending`, then `complete/sent` only
after a successful final response. A failed request records
`failed/not_confirmed`; evidence preparation that fails before dispatch remains
`failed/not_sent`. This avoids leaving a live request falsely marked as never
sent.

## Threading and lifecycle

DICOM header probing and request persistence run in a bounded worker pool.
Qt objects are snapshotted on the GUI thread and are not passed to workers.
Results are polled by a coordinator-owned timer. Cancel detaches the pending
result and returns the coordinator to idle state. A second lifecycle guard
detects when another toolbar action disarms the pending ROI and returns the
workflow to idle instead of leaving it stuck. The coordinator is parented to
the patient widget so it cannot outlive its tab.

## Completed evidence and analysis flow — 2026-08-29

After request persistence, `LegionAnalysisRunner` performs all DICOM decode,
image composition, and model I/O outside the Qt GUI thread. The LPS rectangle
is projected through each selected series' origin, spacing, and direction,
including orthogonal and oblique acquisitions. Every selected stack is covered
exactly once by overview contact-sheet tiles. The projected center slice plus
up to five slices on either side is also emitted as a context-and-ROI-zoom
image. This preserves full-stack screening coverage while bounding request
size and retaining high-detail evidence around the reader's target.

The derived evidence manifest contains safe role, plane, coverage, and image
captions but no source DICOM path, series UID, patient identifier, or raw
series description. Structured request identity remains anonymous (`PID 0`).
A series that explicitly declares `BurnedInAnnotation = YES` fails closed
before rendering or provider dispatch.

The analysis pipeline is versioned and sequential:

1. Gemini `gemini-3.1-pro-preview` performs sensitivity-oriented lesion
   screening with the radiologist-supplied `RADIOLOGY LESION SCREENING — LLM 1`
   prompt.
2. GPT `gpt-5.6-sol` receives the same evidence plus the complete screening
   answer as hypotheses, independently verifies the target, discriminates the
   leading differential, and returns radiologist-facing recommendations and
   limitations.

The existing Eagle Eye → EchoMind/GapGPT transport and credential authority is
reused. No provider endpoint, API key, or direct network path was added. The
non-modal result panel preserves separate tabs for the final consultation and
Step 1 response. Failure leaves the ROI and derived evidence on disk; Retry
reuses that package without rereading source DICOM or requiring another ROI.
Stable `[LEGION-CONSULT] event=...` logs record lifecycle events using only the
random session identity and counts.

## Verification surface

- `tests/code/ai_imaging/test_legion_consult_foundation.py`
- `tests/code/ai_imaging/test_legion_consult_ui_contract.py`
- `tests/code/ai_imaging/test_legion_consult_analysis.py`

The guards cover the launcher catalog, MRI-only availability, mandatory and
optional selection rules, source-role de-duplication, localizer exclusion,
input-size estimation, deterministic four-corner LPS mapping, atomic local
persistence with no remote-send claim, source identity matching, and toolbar
routing through the function picker.
The analysis guards additionally pin the exact Step 1 prompt fingerprint,
Gemini/GPT-5.6 stage routing, clipped ±5 focus corridor, complete-stack page
coverage, patient-space projection, anonymous and path-free evidence manifest,
retry package reconstruction, sequential screening-context handoff, and the
post-ROI transition into analysis.
