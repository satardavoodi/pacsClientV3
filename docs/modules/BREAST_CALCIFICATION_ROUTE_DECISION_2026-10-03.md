# Breast calcification development route decision

> Historical route decision. Current stage, later rejected experiments and physician
> review are reconciled in [Breast AI development](BREAST_AI_DEVELOPMENT.md) and its
> [experiment ledger](BREAST_AI_EXPERIMENT_LEDGER.md), updated 2026-10-05.

Status: research direction selected from current evidence; no qualified screening model, new production weights, or claim of best architecture.

## Decision

Develop a dedicated calcification path inside the breast module: native multiscale bright-object candidates, candidate-centered detail/context scoring, then separately verified object-to-cluster output. Use local contrast, spatial scale and shape as evidence for the scorer. Keep mass/asymmetry classification a separate task with its own labels and evaluation.

Retain HDoG/FPN as the current reproducible research comparator. Prioritize repairing candidate confirmation and training/inference context alignment. Do not fund another broad model search, simply lengthen the rejected runs, or select a finer candidate scale without a measured benefit. A100 capacity is adequate for these bounded experiments; no H200 requirement has been demonstrated. Commercial rights to the downloaded HDoG checkpoint remain unverified, so selecting this research route does not authorize distributing that checkpoint.

This decision addresses the requested evidence-based choice of direction. Training the next candidate and qualifying an Eagle Eye screening module remain subsequent work, not achievements claimed by this decision.

## Fresh comparison on complete native images

The same frozen calibration selection supplied two distinct point-rich groups (31 provisional red centers) and two conservative negative groups, one complete mammogram each. Source hashes were verified. Original state-only FPN weights, input normalization and 512-pixel tile reconstruction were held fixed. Every image pixel had coverage. No reference location or ROI restricted inference. Reference-centered crop results were not substituted for whole-image inference.

Classical local contrast was explicitly defined as `(image - Gaussian(image, sigma=3)) / sqrt(local_variance(sigma=9) + 1e-6)`, in native pixel units. Diagnostic contrast thresholds 2 and 3 retained candidate objects with more than 30% mask overlap. These are two particular tested rules, not an exhaustive search or evidence that all classical methods fail.

| Route | Reference hits within 8 native pixels / 31 | Components on two conservative negative images | Interpretation |
| --- | ---: | ---: | --- |
| HDoG candidates only | 31 | 53,818 | High proposal coverage but unusable burden without confirmation |
| Candidates plus local contrast >=2 | 5 | 59 | This rule loses most reference support |
| Candidates plus local contrast >=3 | 0 | 1 | Suppression alone creates a misleadingly clean result |
| Candidates plus original FPN, threshold 0.01 | 25 | 70 | Better tradeoff among these settings, still unqualified |

Candidate-only output also contained five boxes exceeding 5% of an image across the four images. The learned branch had none. Component counts are individual connected objects, not adjudicated false cluster marks. The negative publisher-count discrepancy remains unresolved; do not describe these as clinical specificity measurements. Total stage-audit time was 142.82 seconds, peak allocated VRAM 0.332 GiB. Current A100 free memory was checked at 12,147 MiB before the run; existing services were not stopped.

## Exact location of the six lost references

The protected full-image candidate mask and probability map were cached. At FPN threshold 0.01, their stage attribution is:

- Candidates cover 31/31 references.
- The raw learned map covers 26/31: five candidate-covered references have no learned output within the matching radius.
- Candidate/prediction pixel intersection also covers 26/31.
- The requirement that over 30% of each candidate object overlap the learned map reduces coverage to 25/31: one additional reference is lost by this output rule.

This identifies output stages responsible for these misses, not the biological truth of every reference or the training cause of model rejection. It replaces the earlier crop-only hypothesis with direct full-image evidence on this small cohort.

Matching sensitivity was also checked. Candidate coverage was 19/31 at the exact reference pixel, 30/31 within two pixels, and 31/31 within four or eight pixels. Raw learned-map coverage was 25/31 at zero, two and four pixels and 26/31 at eight. Thus the 31/31 count is proximity coverage, not exact segmentation or a promise of 100% screening sensitivity.

A controlled postprocessing-only experiment replaced whole-object overlap filtering with pixel intersection. It recovered the extra reference (26/31), but negative components increased from 70 to 180 and negative predicted pixels from 15,616 to 22,426. The intervention is rejected as a ready correction. Merely weakening the output gate is insufficient.

## Evidence carried forward from the existing experiments

- Broad DeepMiCa activation and 65-pixel dilation chains both contributed to poor boxes. Removing dilation alone exposed thousands of proposals. See [failure diagnosis](BREAST_CALCIFICATION_FAILURE_DIAGNOSIS_2026-10-03.md).
- The compact classifier's strong patch results did not transfer to full images. The full-image verifier lost references, including after hard-negative training. See [expanded training](BREAST_KIOS_EXPANDED_TRAINING_2026-10-03.md). That experiment used a different candidate path; it does not establish that a scorer trained on current HDoG candidate centers will succeed.
- Both recent FPN decoder/head adaptations failed the fixed point-retention gate. Their finite updates and checkpoint reload checks establish execution, not a qualified improvement. See [joint experiments](BREAST_HDOGREG_JOINT_EXPERIMENTS_2026-10-03.md).
- The eight completed physician cases contain 16 positive regions, not individual-punctum masks. Their value is region supervision and case review; treating every enclosed pixel as positive is invalid. See [physician review](BREAST_PHYSICIAN_REGION_REVIEW_2026-10-03.md).
- Published local-detail/context and HDoG approaches support testing a hybrid architecture; their reported endpoints do not prove performance in this dataset. See the [primary-study review](BREAST_MICROCALCIFICATION_METHODS_REVIEW_2026-10-03.md). Previously stale asset-unverified statements in that historical review are superseded by the load/hash receipts and [initial execution](BREAST_HDOGREG_INITIAL_EXECUTION_2026-10-03.md).

## Concrete next implementation contract

1. Build candidate-centered training examples from the same native candidate generator used at inference. Retain a high-resolution detail branch and a larger surrounding context branch. The existing 512-pixel cache (65 positive and 56 negative tiles) is preparation material; it has not been trained and must not be called a finished candidate-centered dataset. Record physical spacing and input polarity/rendering explicitly.
2. Assign provisional point supervision only to compatible nearby candidate objects, preserve unknown pixels, and use physician rectangles as weak region bags. Mine hard negatives only within training images or crop scopes known to be negative. Resolve/audit the publisher-negative ambiguity before treating that pool as definitive truth. Review source/person linkage and candidate-center distribution rather than assuming more examples repair label errors.
3. Compare candidate-centered detail/context scoring with context-matched 512-pixel FPN adaptation as one bounded fallback. Keep the original comparator. Use local contrast, gradient, size and shape as features rather than unvalidated hard rejection rules. Preserve individual-object evidence and test grouping separately from scoring.
4. First run the common full-image development cohort, including all 52 existing calibration mammograms where supported, with identical candidate/matching definitions. Existing patch-test results have already been inspected and are not a fresh final test. Report candidate coverage, scorer losses, output-rule losses, negative burden, footprint, and physically calibrated size strata separately. Do not compare 25/31 from this subset directly with 151/157 from a different full cohort as an architecture ranking.
5. Continue a candidate only if it preserves the comparator's reference coverage while reducing adjudicated false-mark burden, or improves coverage at a matched burden. Use the existing research FROC budgets of 0.5, 1 and 2 false clusters/image as development comparisons, not owner-approved clinical thresholds. Cluster truth/adjudication is required before calling the curve clinical FROC. Freeze configuration before independent external/temporal qualification and uncertainty estimates.

No broad repeat physician annotation is needed for the present direction decision. If candidate identity or negative status remains ambiguous during training preparation, assemble a small versioned queue of those exact cases, with zoomed native evidence. A newly reviewed case must retain its documented split role; if used for training it cannot remain an independent evaluation case. Completed window/quality corrections and green rectangles must be preserved.

## Evidence and completion boundary

Aggregate receipts are in `generated-files/eagle-eye/calcification-candidate-20261001/`:

- `hdog-stage-audit-20261003.json`: complete-image classical/learned comparison.
- `hdog-stage-attribution-20261003.json`: exact cached-map stage losses.
- `hdog-matching-tolerance-20261003.json`: matching-radius dependence.
- `hdog-postprocessing-ablation-20261003.json`: rejected output-rule replacement.
- `breast-route-decision-20261003.json`: research decision and code hashes.

The decision is supported by direct current experiments, prior rejection evidence and task-matched literature. It is sufficient to select the next bounded development route. It does not prove generalization, high clinical PPV/NPV, a universal optimal model, or readiness for deployment. Private images, annotation coordinates, source paths, maps and weights remain in protected research storage; no application runtime or live GUI acceptance was changed or claimed.
