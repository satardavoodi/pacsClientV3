# Implemented calcification candidate feature scorer

Status: implemented, trained and evaluated on ten full development mammograms. False-mark burden improved in an additional-image check, but one baseline-covered reference was lost in the initial subset. The strict no-additional-reference-miss gate is not passed. No production model is replaced.

## Executed method

The first implementation of the selected hybrid direction uses native DoG/Hessian candidates and a small trainable confirmation model. Nineteen features describe component geometry, intensity, local residual contrast, locally normalized contrast, surrounding mean/variance at two scales, and original FPN probability evidence. A 19-to-64-to-32-to-1 MLP has 3,393 parameters. This is a candidate-feature model with context statistics, not an implemented two-image-branch CNN.

The original FPN remains frozen and supplies one set of features. The new model learns to score candidates instead of using a hard local-contrast rejection threshold. Source input follows the existing native percentile 1/99.5 contract; features are normalized with fitting-group statistics only. The exact feature function used in training and additional-image inference passed AST equality and syntax checks.

Native 512-pixel training tiles supplied 65 provisional point-positive candidates and 3,584 negative candidates selected from a pool of 59,562 interior negative objects. High-FPN and randomly sampled candidates were combined. All positive tiles had a compatible candidate within four native pixels. Unmatched candidates in positive images remained unknown; no filled positive rectangles or automatic outside-box negatives were created.

These are pool counts: 52 positive and 3,072 negative samples entered parameter fitting; 13 positive and 512 negative samples from nine other training-partition groups selected the checkpoint and initial threshold. Fitting used 42 groups. No original calibration/test groups entered parameter fitting or internal group validation. Negatives remain conservatively selected publisher negatives, subject to the existing count/label ambiguity. The physician's 16 broad regions were preserved but were not converted into point labels or used by this feature-only pilot.

AdamW ran 1,000 finite optimizer steps at LR 0.001 and weight decay 0.01 with balanced sampled batches. Step 400 had the highest internal group-holdout AUROC, approximately 0.9946; subsequent checkpoints did not improve it. This small internal result is not clinical accuracy. The selected state was saved and reloaded with identical probe outputs. The checkpoint SHA256 is `4866553fbd2c846d3089c271efa0a5550157073db5baf2999c1ec2f6c9c7f967`.

## First four full images: threshold development

The initial threshold derived from the training-group holdout was 0.36935. It retained 26/31 references but produced 240 components on two conservative negative images and one giant box over 5% of an image. It failed as an operating setting.

A descriptive threshold curve on the existing four-image development subset identified 0.9834797382354736 as a stricter operating point. It retained 25/31 references and reduced negative components to 28, versus 25/31 and 70 for the original HDoG/FPN threshold 0.01. The feature route produced no box over 5% at this stricter setting. This threshold was selected on these images, so the result is optimistic development evidence.

Lower thresholds recovered more references at substantial cost: retaining 26 references required 84 negative components; 30 required 623; all 31 required 1,122. None of those counts can be described as cluster-level false-positive rates.

## Fixed-weight, fixed-threshold check on six additional images

Weights and the stricter threshold were fixed before inference on six additional images, with no image-hash overlap with the initial subset. Four positive images came from four groups absent from initial threshold selection; two negative images were other views of the same two negative groups already seen. These images remain within the previously used calibration partition and do not constitute a fresh independent final test.

| Measurement | Original HDoG/FPN | Candidate feature model |
| --- | ---: | ---: |
| Reference points covered within eight native pixels | 31/31 | 31/31 |
| Components on two conservative negative images | 74 | 30 |
| Predicted pixels on those negative images | 13,748 | 12,048 |
| Components across all six images | 675 | 231 |
| Boxes larger than 5% of an image | 0 | 0 |

The component reduction on negatives is 59.5%, while negative pixel footprint improves by only 12.4%. The model removes many small objects; this is not equivalent to eliminating all clinically distracting structures. The images contain provisional publisher references, and point-proximity coverage is not exact segmentation or a guarantee that all calcifications were detected.

Training plus initial full-image evaluation took 90.15 seconds, with 0.282 GiB peak allocated GPU memory. The additional-image run took 274.80 seconds and 0.332 GiB peak allocated GPU memory. Candidate generation is a material CPU cost. The existing A100 was used after a free-memory check; services and environments were not altered.

## Point identities change the acceptance decision

Equal hit counts on the first subset concealed a substitution. Cached full-image masks and feature scores were compared reference by reference:

| First subset outcome | Points |
| --- | ---: |
| Covered by both methods | 24 |
| Covered only by the original method | 1 |
| Covered only by the feature model | 1 |
| Covered by neither | 5 |

The additional subset has all 31 references covered by both methods. Across all ten images, both methods therefore cover 56/62 references, but they do not cover the same set. Negative components total 144 for the comparator and 58 for the feature model, a 59.7% reduction. Those four negative images represent only two groups. Aggregating the subsets does not erase threshold-selection bias or the newly missed point.

Decision: retain this implementation as a promising research candidate for confirmation-stage improvement, but reject deployment or a claim that baseline findings are all preserved. The secondary threshold was not adjusted after observing the six additional images.

## Next corrective work

Follow-up execution: [histogram and spatial peak ablation](BREAST_HISTOGRAM_PEAK_ABLATION_2026-10-03.md) completed twelve controlled runs. The additions did not preserve the low negative burden while fixing the lost original reference. The data audit confirmed that this pilot used only 65 positive tiles from 37 of 60 eligible training groups; broader candidate-centered training remains the next intervention.

The next training intervention should target the confirmation model's false rejections and its own high-scoring training negatives, with a larger and more representative candidate-centered positive pool. The present 52 fitting positives cannot establish population coverage. Inspect the one newly missed reference and analogous training candidates before assuming that additional epochs will repair it. Any new clinical adjudication must remain versioned and preserve the distinction between training and evaluation material.

Full-image versus 512-tile component geometry, float16 training-cache versus float32 inference input, physical spacing, negative label validity, and suspicious-region/benign-point coverage remain explicit gates. Complete the common full development cohort before an external/temporal test. Candidate clustering and physician-facing boxes require separate verification; component reductions alone do not qualify a screening system. Broad repeat physician annotation is not requested by this experiment.

## Reproducible artifacts

Research scripts, feature pools, private maps, and checkpoint reside in the protected calcification research workspace. Aggregate repository receipts are under `generated-files/eagle-eye/calcification-candidate-20261001/`:

- `candidate-feature-scorer-experiment-20261003.json`
- `candidate-feature-matched-burden-20261003.json`
- `candidate-feature-first-locked-20261003.json`
- `candidate-feature-additional-evaluation-20261003.json`
- `candidate-feature-point-identity-20261003.json`
- `candidate-feature-candidate-manifest-20261003.json`

The manifest pins code hashes, checkpoint identity, threshold and qualification status. This executes the first feature-based confirmation pilot from the [route decision](BREAST_CALCIFICATION_ROUTE_DECISION_2026-10-03.md). No application runtime or clinical GUI acceptance is claimed.
