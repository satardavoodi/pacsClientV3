# Eagle Eye Mammography Intelligent Analysis Merge — 2026-09-02

## Decision

The mammography Intelligent AI Analyze capability from
`satardavoodi/PacsClientV2` `main` was reviewed at commit `7cec3d5b` and
selectively ported onto the current AI-PACS 3.6.4 architecture. The remote branch
was not merged wholesale. The useful clinical workflow was retained while the
unsafe, generated, unrelated, or architecturally conflicting changes were left
out.

The reviewed remote history after the shared base was:

- `cce774a9` — intelligent-analysis changes
- `3323c9aa` — project update
- `2f155945` — intelligent analysis with edit mode
- `cdc526b3` — mammography and bone-age update
- `7cec3d5b` — merge commit on remote `main`

## Included scope

- A mammography-only `Intelligent AI Analyze` action in the existing Eagle Eye
  imaging toolbar.
- Direct main-toolbar routing for MG into the native Eagle Eye workflow while
  retaining the MRI-only Legion Consult choice and leaving the lumbar pipeline
  unchanged.
- A dedicated controller and runner instead of placing the complete workflow in
  the oversized imaging-tab controller.
- Worker-thread CSV discovery, DICOM decoding, image rendering, package
  construction, and network submission. The Qt GUI thread only updates state and
  presents review UI.
- Immutable MG instance hints are copied from the current viewer catalogue so a
  result produced with a path from another workstation can be rebound to the
  local DICOM object by unique SOP, series, filename, or instance identity.
- Reuse of the current EchoMind/GapGPT backend selection and company entitlement
  boundary.
- A mandatory editable physician-review step before accepted text is handed to
  the existing EchoMind Report composer.
- Explicit, self-cleaning temporary image ownership.

## Safety and data boundary

The remote implementation sent or exposed more information than the current
architecture permits. The port therefore constructs a new bounded transport
package rather than forwarding the raw CSV.

- Only DICOM objects with `Modality == MG` and an explicit, exact match to the
  requested `StudyInstanceUID` are accepted. Missing study identity fails closed.
- At most eight 2D source images and 32 detections per image are accepted.
- CSV input is limited to 2 MB and 5,000 rows.
- Result discovery is confined to the configured attachments root; a study value
  cannot traverse to another directory.
- Each source file is capped at 256 MB and declared pixel dimensions are capped
  at 64 million single-frame grayscale pixels before pixel decoding.
- Only allowlisted finding labels, bounded scores, approximate boxes, laterality,
  and view position reach the transport package.
- Patient identifiers, study identifiers, source paths, arbitrary CSV columns,
  and raw CSV text are not included in the model-facing header or captions.
- Viewer source hints remain private to the worker. Ambiguous rebinding is
  rejected rather than selecting a potentially wrong image.
- Detection and classification rows remain joined by their original result
  identity after the pixel source is rebound, so a different local filename
  cannot silently discard an existing finding label.
- Images receive request-local aliases such as `MG-01`.
- Existing DICOM windowing and MONOCHROME1 handling are reused.
- The prompt describes decision support, requires uncertainty to remain visible,
  and forbids a final BI-RADS assignment from this bounded package.

This reduces casual exposure and prevents arbitrary CSV text from becoming model
instructions. It does not make a client-side secret impossible to recover from a
machine controlled by an attacker. Credential authority remains with the current
EchoMind/GapGPT configuration and dashboard.

## Remote changes intentionally excluded

- API-key-shaped configuration values and generated runtime profiles.
- `.freebuff/project-id` and generated Slicer application resources.
- Unrelated EchoMind settings, usage-popup, and network-retry changes.
- Bone-age and DX intelligent-analysis additions.
- The remote monolithic imaging-tab implementation.
- Any packaged output, installer, or plugin payload generated from the remote
  tree.

## Known limits and release gates

- This integration supports bounded 2D mammography evidence only. It is not a
  tomosynthesis reconstruction or multiframe diagnostic pipeline.
- The image and finding limits intentionally fail closed instead of silently
  analyzing an incomplete study.
- Regression tests use synthetic DICOM and mocked transport. No live model call,
  real patient data, installed-application launch, clinical accuracy validation,
  installer build, deployment, or release was performed by this merge.
- A radiologist must review and edit the generated text before report handoff.
- A clean release checkout, secret-rotation gate, full installer verification,
  and source-build clinical acceptance remain required before distribution.

## Regression evidence

`tests/code/ai_imaging/test_mammography_intelligent_analysis.py` failed with four
errors before the dedicated package, runner, controller, and toolbar route
existed. A sixth guard then failed against the first port because a DICOM object
without study identity was accepted. Security review found two additional
fail-before cases for study-directory traversal and oversized declared pixel
dimensions. A ninth guard showed that corrupt pixel-decoder details escaped the
package boundary; those errors are now converted to a stable safe message. The
first live source attempt then exposed a stale-path compatibility gap: the box
viewer could correlate a remote CSV path by series/instance identity, while the
new package builder required that raw path to exist locally. The stale-path guard
failed at import before a viewer-source snapshot contract existed. The final
boundary fails closed. It guards:

- study/modality binding, transport redaction, input limits, and temporary-file
  cleanup;
- rejection of cross-study or missing-study-identity DICOM objects;
- attachment-root containment and pre-decode source-size/dimension limits;
- safe handling of corrupt pixel payloads without leaking decoder internals;
- unique stale-path rebinding through an immutable viewer snapshot, rejection of
  ambiguous identity, preservation of detection/classification association, and
  exclusion of Qt/VTK objects from the worker input;
- off-GUI-thread construction and the remote runner's undefined-package defect;
- delegation from the imaging tab to the dedicated controller; and
- direct MG routing without changing the MRI-only Legion Consult branch.

The complete non-live AI Imaging lane passes 903 tests with eight pre-existing
xfails and three existing SWIG warnings. The default-build inclusion guard passes
three tests and all 462 plugin mirror pairs match.

## Rollback

Remove `modules/ai_imaging/mammography_ai_analyze`, its imaging-tab controller
binding and button, and the MG-specific toolbar route. The existing lumbar Eagle
Eye implementation does not depend on this package and remains independently
testable.
