# B27: Separate clinician click feedback

Date: 2026-10-05. Status: implemented and code-verified; human GUI acceptance pending.
This is a review-tool update, not training or a new model evaluation.

## Purpose and preserved evidence

Following B26, let the physician locate the single reported skin error without
repeating the eight-case review. Add separate incorrect-model and missed-calcification
feedback. Unmatched red predictions remain unknown until reviewed; they are not
automatically negatives. B26 remains bound to the previously reviewed HTML.

The same eight exposed cases (six TRAIN, two development), original 143 reference
points, predictions, preprocessing and matching are unchanged. No checkpoint or
threshold changed; no new inference, training, clinical metric or deployment occurred.

## Interaction and data contract

- Inspect is the default mode, including after case changes.
- Incorrect model mark records a magenta cross at the exact native click position.
  It optionally links a visible prediction within six native pixels. Otherwise it
  remains standalone. This UI radius is separate from the 0.2 mm evaluation rule.
- Missed calcification records a separate blue plus without automatic pairing.
- Undo removes the latest feedback mark in the current case. Notes and display
  settings save alongside feedback; original annotations remain immutable.
- Dragging over five CSS pixels or scrolling during a press suppresses annotation.
- Manifest-bound browser autosave checks competing revisions. JSON export/import
  validates exact manifest, source annotation and checkpoint bindings, native bounds,
  mark types, IDs and optional links. Export before closing or changing browsers.
- A separate dry-run intake validator creates proposals only; no automatic truth
  merge or learning from clicks is enabled.

## Artifacts and checks

Protected research root:
`C:/AI-PACS-Datasets/breast-review/point-review-20261003`.
Viewer: `eight-case-point-comparison-20261005/offline-review.html`.
Current HTML SHA256:
`222a9d4ecdf0a6e1a8405c2e4b12024151f9c8642b3c50dc164b0eec231313e6`.
Previous HTML is retained in `backup-before-click-feedback` with SHA256
`62d9c58dd866f8626d591853e828744aa47f991c23566aea7adac81db7701e15`.
Intake guide: `EIGHT_CASE_FEEDBACK_INTAKE_2026-10-05.md`.

Root reran the viewer partition tests, actual eight-case manifest checks, synthetic
feedback tests, embedded JavaScript syntax check and six Python validator tests:
all passed. Original annotation and manifest hashes remain unchanged. Tests cover
native coordinate projection, edge precision, zoom/scroll geometry, visible-only
linking, import/export validation and immutable source arrays.

GUI interaction remains unverified: existing file-protocol browser automation is
blocked. No workaround listener or alternate rendering route was used. The physician
opens the offline file manually. Code tests are not GUI acceptance.

## Next action

Physician marks the erroneous skin region using Incorrect model mark and exports
`eight-case-model-feedback.json`. Validate that export before any annotation revision.
Retain the B26-approved research candidate; independent cohort assessment and the
paired Razi comparator remain outstanding.
