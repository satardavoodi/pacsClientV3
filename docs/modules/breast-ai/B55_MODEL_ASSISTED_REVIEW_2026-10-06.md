# B55: Model-assisted morphology correction

Date: 2026-10-06. User requests one-pass review of the existing 24-study B54 pool,
with the model's actual outputs visible and editable physician judgments alongside.
This supersedes the default blinded-first workflow for the new review version.
The original B54 bundle and any responses remain unchanged.

## Scope and interpretation

Use B50 unweighted morphology transfer, seed17 selected before inference, as the
current research comparator. This is not a claim to reproduce the original Razi
production model. Run frozen inference only: no optimizer, new training, threshold
selection or clinical deployment. These 24 studies belong to the fitting partitions;
their assisted review cannot estimate independent performance.

Present the three actual model scores for Mass, architectural distortion and
asymmetric appearance, together with the selected class. Scores are uncalibrated
model outputs, not clinical disease probabilities. Do not fabricate shape, margin,
malignancy, BI-RADS or multiview correspondence from these three scores. The displayed
reference region is dataset geometry, not a newly predicted detector box.

## Physician feedback contract

Show model outputs immediately, per the user's request, and record model exposure.
Keep source annotations separate. Allow correct, incorrect and uncertain judgments,
with a physician-selected corrected appearance, coexistence, confidence, view
evidence, region adequacy and notes. Permit no lesion, mixed and indeterminate
interpretations rather than forcing every correction into the three model classes.
No unanswered field or untouched checkbox implies clinical absence.

Use a separate bundle identifier, storage key and versioned export. Bind predictions
to checkpoint, source inputs and neutral case identifiers. Retain feedback as model-
assisted physician opinion, not blinded adjudication or automatic training truth.
JSON import must reject mismatched bundles and preserve existing work before replacement.

## Delivery and verification

Protected work root: `P/b55-model-assisted-review-20261006/`.
Actual frozen inference completed for all 24 cases using the original B50 cached
reference-ROI inputs. Predicted classes count 7 Mass, 8 AD and 9 asymmetric-tissue
appearance; these counts do not measure correctness. Exact reload, finite outputs
and unit probability sums passed. CPU inference/reload verification took 2.59 seconds;
this is not full-study image preparation or serving latency.

Checkpoint SHA256:
`d9fc9a80e6db04a9f898fb37f8f68bc32a845c7a57bab044e1596e024e6cefab`.
Input SHA256:
`57ff3973ae806953e3848d6b3509284a41dd25393b34243a1a555eb7e82f3712`.
The protected `inference.json` binds neutral case IDs, original row references,
three scores and predicted class. Source shape/margin attributes are unavailable
for this target checkpoint. No physician correctness decisions have been inferred.

Delivered entry point: `P/b55-model-assisted-review-20261006/bundle/index.html`.
All 24 predictions are bound into the bundle; all 96 native-spatial image hashes
match. Fourteen logic guards and JavaScript syntax checks passed, including normal
and mixed corrections, required fields, JSON round-trip, exposure and tampered-model
rejection. B54 remains unchanged. Model exposure is saved upon rendering; medical
edits invalidate completion. Export/import uses its own versioned storage identity.
Primary verification confirmed six bundle hashes plus the inference hash, and 83
local links across this report, the current-state guide and ledger. These documents
also passed the English-language check.

Inference SHA256:
`35f348e1e6a41be2af96546923abe6f10c3f9df63afa4b180b2b0bcbd1a81a13`.

The B54 execution-policy rejection and local-file browser restriction remain in force;
do not retry a server or browser workaround. Live browser acceptance is separate from
automated logic checks and is not claimed by file creation.

## Next use

### Physician export intake: 2026-10-06

Two user-supplied exports passed the unchanged B55 provenance/model/schema validator
and were copied byte-for-byte into protected `physician-feedback-20261006/` beneath
the B55 work root. The earlier export has 11 records/10 finished; the later has 24
records/23 finished. All earlier IDs remain in the later file, with one existing
record changed. Originals and both snapshots are preserved; no browser import ran.

Two comments report additional masses (three total). The protected intake receipt
records counts and verbatim comments separately from the reference-ROI diagnosis.
Locations and correspondence to existing boxes are unknown. One record marks the
AD prediction correct while choosing Mass as dominant appearance; clarification is
pending about an AD reference ROI plus separate masses versus a corrected ROI type.
Do not resolve this conflict automatically, infer detector misses from a classifier
review, or admit these supplemental findings to training without localization.
No accuracy estimate is derived from this intake. Individual references/comments
remain in protected storage rather than this repository document.

Review corrections for consistency and uncertainty, version the reference changes,
then decide whether source mapping, training supervision or region geometry needs
repair. Preserve the matched comparator and unused qualification cohorts. Do not
use these same fitting-case corrections as independent proof of an accuracy increase.
