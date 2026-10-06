# Calcification supervision recipe

Decision: combine public point/mask supervision with physician region corrections and task-matched hard negatives. Neither training solely on the eight physician cases nor repeating generic public-patch training addresses the measured full-image failure sufficiently. This is a prepared recipe, not a completed larger training run.

## Available supervision and its role

| Source | Current usable material | Appropriate role | Unsupported interpretation |
| --- | --- | --- | --- |
| Frozen KIOS training partition | 74 groups; 1,643 positive and 1,792 negative native-detail patches | Existing provisional red-center positive supervision and conservatively empty-group negatives | Patches are not independent patients; red dots are not dense masks; blue circles are not individual calcification centers |
| New physician review | Eight existing training cases, 16 valid region rectangles | Positive region bags and local-domain adaptation | Every enclosed pixel positive, or every outside pixel negative |
| Earlier physician review | Existing protected supervision already split into training/development | Reviewed positive regions and reviewed empty crops within their stated scope | Whole-image negativity from an empty crop, or independent holdout after adding a case to training |
| Detector-generated candidates | High-scoring objects mined only from accepted negative training images/crops | Task-matched hard negatives for the confirmation network and staged decoder adaptation | Automatically negative predictions outside coarse positive rectangles |

The existing training cache is based on a label-blind percentile renderer, whereas recent original-weight HDoGReg tests used standard DICOM windowing. Do not mix these contracts silently. Rebuild or explicitly compare the training/mining renderer before a larger joint run. Native detail, context and contrast channels are different inputs; the HDoGReg FPN uses its own one-channel mean/std 0.5 contract.

## Ordered training

1. Version source hashes, native coordinates and scope. Audit identity/source overlap when combining older and newer reviews; do not simply add their apparent patient counts. Retain calibration/test exclusions and all unknown labels.
2. Mine current HDoG/FPN false-mark candidates from accepted negative training scope. Include high-scoring and diverse negatives; remove redundant neighboring samples. Positive-patch unreviewed tissue is not a negative source.
3. Train decoder/head with actual point supervision and hard negatives, maintaining native detail. Monitor gradients, point retention and negative activation; the previous 16-patch fit verified execution but was already easy for the original model.
4. Jointly adapt with physician region bags while retaining public positive examples. Test selected encoder unfreezing only when the decoder route fails to generalize. Use a region-level objective instead of converting rectangles into filled masks. Sampling balance and loss weights are development hypotheses, not fixed optimal settings.
5. Evaluate the whole candidate-confirmation-grouping pipeline at matched false-mark budgets. Expand reference-point support beyond the two-point pilot. Do not report region occupancy as complete calcification recall, or individual-component counts as cluster FROC.

The two data sources complement each other: public labels teach individual-object evidence, while the physician rectangles teach where clinically reviewed calcification regions exist in the local task. A pretrained model is the initialization, not a substitute for matching supervision and input contracts.

## Physician effort

Use all existing completed annotations first. Additional expert work is justified only for a small targeted set of missed real calcifications or ambiguous false marks that prevents a decision. Do not ask the physician to trace every punctum or repeat quality/window adjustments. Cluster rectangles remain acceptable supervision; a small separately reviewed point/mask subset can support precise evaluation if needed later.

## Execution status

The protected `joint-supervision-recipe.json` was created and its eight-case/16-region manifest validated. It preserves all marks and creates no fabricated dense masks. No larger joint training was started by this recipe preparation, and no production weight was replaced. Independent grouped qualification and unresolved commercial reuse rights remain separate from authorized research training.
