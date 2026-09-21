# Lumbar reference workbench and training export - 2026-09-11

## Delivered

The later [report-assisted prefill update](LUMBAR_REPORT_PREFILL_2026-09-11.md)
populates 722 fields across 261 cases, shows source report excerpts and outstanding
review items, and supports per-target image confirmation. It supersedes the initial
blank-form workflow below. Report proposals remain masked until actual review.

The control PC now runs a loopback-only image-reference workbench at
`http://127.0.0.1:8841/`. Start it again with
`C:\AI-PACS-Datasets\Start-Lumbar-Review.cmd`. The launcher reuses a healthy existing
instance and refuses to stop an unrelated process occupying its port.

The application reads the current **291 cases / 1,885 candidate regions** directly
from the protected C-drive dataset. It prioritizes the existing 12-case review queue.
It is independent of the installed and developer AI-PACS workstation processes.
No PACS credentials, external model calls or patient uploads are used by this tool.

Implementation and synthetic tests are under
`C:\AI-PACS-Datasets\lumbar-mri\v0.1\review_app`. Clinical data remains outside Git.
This operational document is mirrored in the control-node documentation directory.

## Review workflow

1. Select a case and level, and enter the reviewing clinician's identifier.
2. Inspect paired axial and sagittal native images. Sagittal T2 is selected first;
   T1 remains selectable when present. Sliders retain native slice membership.
3. Use **Whole acquisition context** to inspect numbering and coverage against the
   uncropped source. Return to regional images before attaching target evidence.
4. The separate sagittal locator shows the current axial intersection, clipped to
   both acquired fields of view. It never changes the diagnostic image. Shared
   geometry does not independently establish absence of patient motion.
5. Select the complete acquisition packets belonging to the current level. Multiple
   packets may belong to one level; packet order does not establish anatomy.
6. Verify numbering, geometry/crop coverage and report-to-study identity. The local
   reception report is available as text. Report retrieval candidates remain separate
   from image-reference observations.
7. Record each observed target, its coverage assessment and the displayed native
   evidence planes. Central canal, right/left recess and right/left foramen are
   distinct targets. Unreviewed and inadequately covered targets remain unknown.
8. **Save draft** stores choices with every supervision mask zero. **Save reviewed
   labels** requires reviewer identity, all input checks, target coverage and valid
   image evidence. Priority image-quality holds require explicit resolution.

Axial display runs patient R to L horizontally and A to P vertically; sagittal
display runs A to P horizontally and S to I vertically. Flips/transposes preserve
an exact pixel-to-RAS transform and do not interpolate native slices. Physical pixel
aspect is retained. Oblique planes remain oblique. The initial viewer uses a fixed
1st/99th percentile intensity window; an affine-aware viewer such as 3D Slicer is
still appropriate for additional windowing or detailed volumetric inspection.

The workbench is an annotation aid, not a validated diagnostic viewer or an automatic
label adjudicator. Reviewer identifiers record provenance; they are not authenticated
clinical signatures. Contradictory morphology labels still require clinical review.

## Files and overwrite protection

Each existing case candidate directory gains files only after a user save:

- `review_draft.json`: editable observations, masks zero.
- `reviewed.json`: explicit image-reviewed labels and evidence provenance.
- `review_history/`: previous reviewed versions and superseded drafts.

Writes are atomic. Dataset hashes, packet/group membership, native slice bounds
and an optimistic revision token protect against stale or incorrectly associated
annotations. Evidence capture waits for the current image and geometry to finish
loading. Whole-context images cannot be accidentally attached as regional evidence.
The server binds only to `127.0.0.1`; it validates Host, Origin and a per-session
write token. Responses are not cached, reports render as text, and request access
logging is disabled. No LAN binding or firewall exposure was added.

## Frozen person-level partitions

`tools/prepare_patient_split_plan.py` generated `patient_splits.v1.json` and its hash
receipt beside the current candidate run. A seeded SHA-256 ordering assigns:

| Partition | Person groups |
|---|---:|
| Train | 232 |
| Validation | 29 |
| Test | 29 |
| Existing development-only pilot | 1 |

These assignments were frozen before image-reference review; they do not activate
clinical labels. Every level and repeat study from the same person must retain the
same partition. Do not move patients after examining model results. The curated
cohort is not prospective external validation. Reviewed class coverage and patient
identity linkage still need auditing before interpreting training metrics.

## Export to the existing MONAI worker

`C:\AI-PACS-Datasets\Prepare-Reviewed-Training.cmd` discovers current human-reviewed
case files and invokes `tools/export_current_reviews.py --export`. It excludes the
development-only pilot and cases with newer unsaved-as-reviewed drafts. It requires
reviewed samples in both train and validation partitions. It creates a new release
under `research/releases` only after the review contract passes, and records the
release in `research/releases/latest.json`. No GPU training starts from this command.

The existing exporter was corrected to skip mapped but entirely unreviewed levels
inside a partially reviewed case. Reviewed sibling levels can now be exported;
unknown levels are neither promoted to normal nor included in training.

The output remains native NIfTI groups plus RAS geometry, image-reference targets,
loss masks and patient partitions. It matches the existing MONAI worker contract.
The worker uses the isolated Linux interpreter
`/home/gadmin/monai-lumbar/env-training-20260911/bin/python`. Transfer/worker validation
and a controlled GPU training window follow creation of a real reviewed release.
EchoMind restoration remains governed by the existing GPU maintenance runbook.

## Verification and actual readiness

- **38 focused synthetic tests passed**, including 16 display-axis combinations,
  exact pixel/world-coordinate preservation, full-source context, separate locator,
  draft masking, annotation evidence, stale-write rejection, person partitions,
  HTTP request protections and partial-review export to train/validation sections.
- The partial-review regression failed before the fix with `no_reviewed_targets`.
- JavaScript syntax check passed. Browser interaction on a synthetic phantom saved
  a draft with zero active labels, saved a reviewed observation with axial/sagittal
  evidence, reloaded it, and exercised the whole-context evidence guard.
- Read-only loading of all **291 real case contracts** reported zero errors. Image
  routes for one real candidate's axial T2, sagittal T1 and sagittal T2 groups were
  checked in regional and whole-context modes without exposing patient images.
- Real cohort counts at handoff: **zero reviewed cases, zero drafts**. The export
  readiness check correctly reports `ready=false`; clinical training has not started.
- Linux EchoMind was checked at **2026-09-11 11:12 UTC**: health/status `ok`, main
  model and transcription model loaded, zero active sessions. It was not stopped
  during workbench development.

The remaining dependency is actual clinician image-reference review. The first
12 cases provide a practical protocol calibration batch; that batch alone is not
evidence of adequate clinical training size or diagnostic performance.
