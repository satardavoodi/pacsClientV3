# B60: Localize physician-reported additional findings

Date: 2026-10-06. The physician requests drawing boxes for additional masses reported
in the B55 feedback. This is supplemental annotation, not a correction inferred for
the existing reference box or an automatic model-training action.

## Scope and coordinate contract

Extend the existing protected B55 page in place, preserving case IDs, bundle identity,
model outputs, original reference boxes, clinical answers and finished flags. Provide
direct navigation to the two requested cases. Permit multiple numbered rectangles
on the full primary and companion views, retaining B59 native window/level controls.

Store coordinates in the selected full image's native pixel space, with case, view,
image dimensions and native signal identity. Pointer positions must map correctly
after fit/native scaling and viewport scrolling. Retain separate identities for
marks in different views; do not infer that two rectangles describe the same lesion.
Do not use local/context crop coordinates as full-image positions without explicit
crop-offset mapping; drawing is restricted to the full images in this version.

Use a separate versioned storage record and explicit supplementary JSON export.
Drawing, undo and display changes must not reset diagnostic fields or Finish.
Unmarked regions and absent supplementary boxes remain unspecified, not normal.
Preserve source exports; new annotations require subsequent review before training.

## Verification

Implemented in B55 `bundle/additional-boxes.js`, integrated with native display and
the existing review page. Full and companion panels offer a draw toggle, numbered
green rectangles, selected/last deletion, undo and confirmed clear. The yellow source
reference box remains unchanged. Case16/18 links and validated hash navigation allow
direct access. Separate additional-box JSON import/export validates bundle, source
signal hash and geometry; a failed import does not replace the in-memory collection.

Primary reran all 20 supplementary guards successfully: fit/native/scroll mapping,
reversed/clamped/minimum rectangles, pointer drag/cancel, multiple boxes, selected
deletion, undo, draw-off scrolling, storage/provenance failures, clinical/display
preservation and repeated same-hash navigation. The existing 13 native-window and
14 feedback guards also pass. Five case/model/validation identity hashes remain
unchanged. Original UI sources were backed up before editing.

Protected receipt: `P/b55-model-assisted-review-20261006/additional-boxes-test-receipt.json`;
guard: `test-additional-boxes.js` in the same directory. These use synthetic DOM/pointer
and storage fixtures. Live file-page browser automation remains restricted, so actual
browser GUI acceptance is not claimed. No physician boxes have yet been received.

## Physician box intake: 2026-10-06

Superseding the no-boxes-yet state above: two user exports were received, validated
against the unchanged bundle/model provenance and native signal index, and preserved
byte-for-byte under protected `additional-boxes-intake-20261006/` in B55. Their SHA256
values are identical: duplicate snapshots, not independent annotations.

Four rectangles are present across two cases: one primary and one companion rectangle
per case. These are four view-specific regions, not evidence of four distinct lesions.
Empty records for other visited views are unspecified, not negative. Cross-view lesion
identity and lesion count within a rectangle remain unconfirmed.

Actual decoded native signal hashes and bounds were verified for all four regions.
Both primary rectangles have zero intersection with their original reference ROI.
Thus existing B50 reference-ROI scores do not describe these additional regions; this
intake does not prove an autonomous detector miss or classifier failure there.
One primary rectangle touches the image edge; retain that flag when considering
boundary supervision. Rectangles are region annotations, not precise lesion masks.

An offline contact sheet of native-signal crops with green rectangles was generated
and visually inspected for coordinate placement. This is image/annotation inspection,
not a browser GUI pass or clinical diagnosis. Evidence: `intake-receipt.json`,
`geometry-verification.json`, and `additional-boxes-crops.png` in the protected intake
folder. Do not automatically train on these regions or score them as independent
test data. Next apply the frozen classifier to these specific inputs before comparing
their outputs with physician feedback, preserving the original reference-ROI results.

## Benign-finding annotation scope clarification

The physician subsequently describes the additional masses as BI-RADS 2. Retain this
as physician-reported assessment, not an inferred dataset label. The official
[VinDr-Mammo release](https://physionet.org/content/vindr-mammo/1.0.0/) explicitly
omits bounding boxes for BI-RADS 2 findings; finding boxes cover BI-RADS 3-5.
This was already noted in B49 and provides a plausible source-annotation explanation
for these additional regions being absent from the reference boxes. It does not prove
the publisher's individual assessment of either additional region.

Inspected `b50-vindr-stage-20261005.py`: target crops originate from TRAIN finding
rows, eligible appearance families, valid source paths and valid boxes. There is no
explicit BI-RADS threshold in this target staging selection. B54 selection chooses
one existing reference ROI per distinct common-fitting study by appearance class;
B55 displays that supplied reference box and classifier scores, not full-image
detector predictions. Therefore this form cannot demonstrate that a runtime model
recognized BI-RADS 2 and suppressed it. Production Razi filtering was not audited
by this check, and autonomous detection on the additional regions has not run.

For an all-mass typing target, benign masses remain Mass appearance examples, and
unboxed VinDr tissue must not be treated as exhaustive negative truth. Keep appearance
classification separate from BI-RADS assessment and report-presentation policy.
