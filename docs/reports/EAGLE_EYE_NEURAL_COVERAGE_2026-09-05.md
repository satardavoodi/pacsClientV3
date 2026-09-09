# Eagle Eye physical side and neural compartment coverage

Status: source fixed and automatically verified; live clinical validation pending.
Pipeline 8.5.0; atomic contract 2.6.0; anatomy schema 1.10.0; screening schema 3.4.0.
Tracked work item: OPT-55.

## Defect and cause

The paired neural structures had no mandatory per-level negative/positive audit.
A screen could return no recess/root findings while documenting only central
canal patency. Those omitted targets then received no diagnostic card. This
prevented distinguishing an inspected negative from a skipped compartment.
Separately, sagittal model side labels were retained even when opposite to DICOM
LPS X order. Diagnostic requests also inherited an obsolete capture-panel layout
that could contradict the actual supplied card.

## Corrected behavior

- Axial screening pixels must have verified radiological display orientation:
  patient right at viewer left (R), patient left at viewer right (L). Unverified
  or reversed source orientation stops the atomic anatomy gate with an explicit
  error. Pixels are not silently flipped, preserving the source-coordinate map.
  Screening and diagnosis prompts state the same patient-side convention.
- DICOM LPS X determines sagittal side labels. The selected midline, source-tile
  set, immutable group memberships and axial level identities remain unchanged.
  Ambiguous ordering, a displaced midline or conflicting T1/T2 groups fails.
  Both original model assignments and the physical order remain auditable.
- Canal/neural screening requires right and left lateral-recess and nerve-root
  observations at every diagnostic level. Foraminal screening independently
  requires both neural foramina. Central-canal observations retain their existing
  caliber/CSF specificity contract. A normal central canal cannot substitute for
  recess/root/foraminal assessment; recess narrowing does not assign a central
  stenosis grade.
- Each observation records normal, abnormal or not_assessable, a bounded reason,
  level/group identity and source tile IDs. Recess/root evidence must be axial
  and belong to the same level. Foraminal sagittal evidence must match patient
  side; axial evidence must match level. Missing/duplicate rows, contradictory
  findings and invalid citations reject the screen. Every abnormal observation
  requires a matching finding for the downstream diagnostic-card path.
- The merged and persisted `neural_compartment_coverage` contains seven separate
  observations per level. Not-assessable rows produce a report-review warning.
  They are never backfilled as normal. The five independent screening tasks and
  structure-specific diagnostic cards remain in place.
- Screening headers describe their anatomy card. Diagnostic headers use actual
  card identity/layout authority and retain the bounded clinical-context section,
  without inheriting obsolete capture layouts or localizer descriptions.

## Verification

Initial new guards: 11 failed, 1 passed, exit 1 before implementation.
The final dedicated contract file has 16 guards. The integration guard additionally
checks that a recess positive reaches its own diagnosis and that all seven
compartment observations persist in the result artifact.

Full AI Imaging, direct pytest with reruns disabled: **1,063 passed, 8 skipped,
8 existing xfails**, exit 0. Six existing SWIG deprecation warnings remain.
The skips are explicitly opt-in local reference-model/R acceptance tests.
Three default-build inclusion guards pass. Mirror synchronization dry run reports
zero drift; verification passes all 462 source/payload pairs. These lumbar files
have no separate payload mirror requiring a write.

A read-only replay of the latest saved anatomy response corrected side labels in
both sagittal series, retained all six lumbar levels and the selected midlines,
and preserved both input objects and all selected source-tile sets. No model call
or patient artifact was copied into this report or the tests.

## Remaining acceptance and rollback

After the operator restarts the source build, re-run the test study and inspect
the seven-per-level coverage, right/left image labels, emitted candidate cards and
final diagnostic response. A new schema response is required; old omitted rows
cannot be converted into normal observations. This change does not establish
stable extrusion classification or clinical sensitivity. Those require repeated
adjudicated inference with the corrected evidence and prompt contracts.

No installed executable, deployment, model/provider configuration or live database
was changed. Roll back only this scoped side/coverage/header contract together
with its version constants and guards; do not revert the unrelated worktree or
the earlier extended-coverage and explicit-provider fixes.
