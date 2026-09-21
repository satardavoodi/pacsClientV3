# Report-assisted lumbar reference review - 2026-09-11

The owner requested that the saved reception reports populate the review form,
leaving corrections and image confirmation to the clinician. This is now active
at `http://127.0.0.1:8841/`. Refresh the page to load the updated interface.

## Completed population

All **291 reports** were processed locally. **722 target fields across 261 cases**
were populated and persisted in their existing case candidate directories. The
other 30 cases have no assignable proposal under the current extraction rules;
they must not be interpreted as normal. No existing human draft or reviewed file
was overwritten. Original reports, images and training partitions were retained.

| Suggested target | Fields |
|---|---:|
| Disc bulge | 201 |
| Disc extrusion | 91 |
| Disc protrusion | 88 |
| Annular fissure | 87 |
| Disc desiccation | 68 |
| Unspecified disc herniation | 54 |
| Left foraminal stenosis | 43 |
| Right foraminal stenosis | 42 |
| Disc height loss | 21 |
| Left recess stenosis | 12 |
| Left root effect | 7 |
| Right recess stenosis | 4 |
| Right root effect | 2 |
| Central canal stenosis | 2 |

These are overlapping level/target proposals, not distinct diagnoses or patients.
Report extraction is an offline bilingual rule system, not validated clinical
interpretation. No external model calls or report transfers were performed.
Unrecognized wording and ambiguous associations can remain unfilled even when
a clinician could resolve them from the full report.

## Updated form

- The form opens at the first level with populated values and initially shows
  proposed or manually entered targets. **Show all targets** exposes the remaining
  fields, including explicit normal observations or findings absent from the report.
- Each proposal has the matching source report excerpt and **Use report suggestion**
  to restore the proposal after an edit. Source excerpts render as plain text.
- **Report details that still need clarification** lists level, side, grade,
  compartment, assertion and association ambiguities. Findings outside the current
  15-target model remain visible as report context instead of invented model labels.
- A per-level counter shows outstanding image confirmation, evidence, coverage and
  input checks. Complete image-group selection still requires anatomical review.
- **Finding confirmed on images** is independent for each target. Saving reviewed
  labels activates only confirmed targets with coverage, image evidence and the
  existing numbering/geometry/identity checks. Other proposals remain masked.
- Saving a draft activates no supervision. Human edits, including deliberately
  clearing a proposal, are preserved on reload and subsequent prefill generation.

The initial report work list contains 1,413 items: 963 without an explicit local
level, 149 without a specific canal compartment, 94 without a side, 69 without a
single supported grade, 59 requiring assertion/association review, 41 with multiple
levels/findings requiring association, and 38 outside current model targets.
These are parser review items, not counts of errors or independent missing labels.
Unmentioned targets remain unknown, and generic canal narrowing is not automatically
assigned to central canal stenosis. Negative root compression does not imply absence
of all other root effects. Conflicting, qualified-negative, historical and uncertain
statements are not converted into definitive target values.

## Stored data and provenance

Each candidate directory now contains:

- `report_prefill.json`: proposals, report/dataset SHA-256 hashes, exact decoded-text
  character spans, method version and unresolved report items.
- `report_prefilled_review.json`: a populated review template; all supervision masks
  remain zero, with `reference_status=report_suggested` and confirmation false.
- `report_prefill_history/`: content-hashed earlier generated versions when rerun.

The read precedence is human draft, human reviewed file, current report-prefilled
form, then blank template. Proposals remain available beside human edits. A changed
report or dataset invalidates automatic prefill; a stale report-backed save is
rejected instead of silently attaching outdated source evidence. Source snippets
are read from the saved report at display time, not duplicated into repository files.

Implementation: `C:\AI-PACS-Datasets\lumbar-mri\v0.1\review_app\report_prefill.py`
plus the existing review server and frontend. Regenerate with the source virtual
environment's Python interpreter. Generated data stays under the existing protected
C-drive dataset. The Linux image-only staging manifest was not relabeled or changed.

## Verification

**51 focused tests passed**, including the existing geometry/export checks and new
report tests for subtype/level association, explicit bilateral findings, negation,
uncertainty, historical context, conflicting values, missing side/grade/compartment,
bilingual spans, preserved human corrections and stale source rejection.

A browser test with synthetic data confirmed the preselected report values, source
excerpt, remaining-work counters, selective image confirmation, saved evidence and
reload. One confirmed synthetic target was activated while two other populated
proposals stayed masked. The synthetic case is outside the clinical cohort.

A read-only check against the updated live API loaded every real case: **291 valid
prefill records, 722 populated values, zero invalid records, zero activated clinical
targets**. JavaScript syntax validation passed. EchoMind and the MONAI runtime were
not restarted or modified for this form update; only the local review server was
reloaded, preserving its existing browser write token and revision checks.

Aggregate receipts are beside the current candidate run:
`report_prefill_summary.json` and `report_prefill_verification.json`.
This document is mirrored in the control-node infrastructure documentation.
