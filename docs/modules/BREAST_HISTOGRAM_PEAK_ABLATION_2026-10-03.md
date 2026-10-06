# Histogram and spatial peak feature experiment

Status: twelve controlled research runs and additional development evaluation completed. No candidate promoted. This extends the [19-feature pilot](BREAST_CANDIDATE_FEATURE_EXPERIMENT_2026-10-03.md) and [histogram review](BREAST_HISTOGRAM_FEATURE_REVIEW_2026-10-03.md).

## Outcome

Spatial peak features recovered additional provisional references when thresholds preserved the original comparator's detections. The price was substantially more negative-image components and some oversized objects. At the previous low negative-component budget, the feature additions did not outperform the incumbent. This is evidence to retain the feature hypothesis for broader training, not evidence of a qualified improvement.

The earlier 59.7% reduction describes negative-image components, not diagnostic accuracy. Its incumbent scorer exchanged one previously covered point for another. Requiring exact original point-identity preservation changes the operating threshold and exposes the false-positive tradeoff.

## Controlled design

- The same 3,649 candidate samples, labels and groups were reconstructed. Original 19 columns matched the prior cache numerically. Fitting used 52 positive and 3,072 provisional negative candidates; internal group validation used 13 positives and 512 negatives.
- Four arms: original 19 features; original plus 10 histogram features; original plus eight spatial peak features; all 37 features. Each arm ran seeds 103, 107 and 109 with identical sampling schedules within each seed.
- Each model used a 64/32-unit ReLU MLP, AdamW learning rate 0.001, weight decay 0.01, balanced batches of 32 positive and 32 negative candidates, and 1,000 actual optimizer updates. Fitting-group normalization only. Highest internal validation AUROC at 200-update intervals selected the checkpoint; earliest tie won.
- The newly retrained 19-feature controls are distinct from the historical incumbent: this experiment resets the sampling RNG for each run. The historical checkpoint is separately included in matched-burden comparisons.
- On the first four development images, each checkpoint received the highest threshold retaining every original comparator-hit reference. All twelve thresholds and checkpoint hashes were recorded before evaluation on the additional six images. No threshold was retuned afterward.
- The six additional images were previously examined in earlier work. They are development confirmation, not an untouched test. Four positive groups differ from threshold-fitting groups; negative views belong to the same two previously inspected negative groups.

The histogram block uses eight fixed bins of locally standardized residual intensity, component histogram entropy and Jensen-Shannon distance to the surrounding 21-pixel window, excluding candidate pixels. Small components receive a numerical pseudocount, not invented observations. Such histograms may be poorly estimated for tiny objects and are not morphology subtype templates.

The spatial block measures residual peak height, prominence above Gaussian background, Hessian curvature and eigenvalue isotropy at sigma 1 and 2, and four-direction intensity drop/asymmetry at radius four pixels. Peak location uses maximum component residual with deterministic first-index ties. Sobel derivatives are divided by four. These native-pixel scales are not yet physically calibrated. No rendered 3D chart, synthetic illustration or Internet histogram is used as training truth.

## Results

All rows below cover the same ten development images and 62 provisional point references, using eight-pixel matching. Negative component counts are totals over four images from only two groups. Ranges span three seeds, not confidence intervals.

| Method / operating rule | Reference hits | Previously original-hit references lost | Negative components | Oversized objects across all images |
| --- | ---: | ---: | ---: | ---: |
| Original HDoG/FPN comparator | 56/62 | 0 | 144 | 0 |
| Historical 19-feature scorer, previous strict threshold | 56/62 | 1 | 58 | 0 |
| Retrained 19-feature controls, identity-preserving thresholds | 58-60/62 | 0 | 326-1,781 | 5-9 |
| Histogram additions, identity-preserving thresholds | 57-58/62 | 0 | 184-559 | 3-7 |
| Spatial peak additions, identity-preserving thresholds | 59/62 in all three seeds | 0 | 245-428 | 2-4 |
| Combined additions, identity-preserving thresholds | 58-59/62 | 0 | 201-344 | 3-6 |

An oversized object has a bounding rectangle exceeding 5% of the image area. Component counts are not cluster-level false-positive FROC. More recovered points with more marks is not proof of superior discrimination, and these small development counts do not establish screening sensitivity or NPV.

The stricter matched-burden check on the first four images is particularly informative. At 28 negative components, the incumbent covers 25/31 references; histogram arms cover 21-24, peak arms 22-24, and combined arms 15-22. At 70 negative components, peak and combined arms each cover 26/31 but still lose one original-hit identity. Thus the additions have not solved the earlier false rejection at an acceptable matched burden.

## Failure audit and data coverage

The incumbent's one newly missed reference has candidate objects within the matching neighborhood. Its best candidate is rejected by the confirmation score. Its individual original features are inside the pooled positive training ranges; this does not exclude multivariate distribution shift or inadequate training coverage. Increasing candidate brightness alone cannot be assumed to repair this failure.

The earlier native-context preparation intentionally stopped after at least 64 positive tiles: first eligible view per group and first two available points. It produced 65 positive tiles from 37 groups and 37 source images. The existing training partition contains 60 red-reference-eligible groups with 240 associated images. These are inventory counts, not a promise that every associated image supplies valid usable point supervision.

Next intervention: broaden candidate-centered positive examples across eligible training groups, views, tissue backgrounds and point sizes, paired with scorer-mined negatives within verified negative training scopes. Preserve the existing patient-group boundaries and physician region annotations. Do not relabel development misses as new independent training examples or fabricate dense masks from broad rectangles. Compare the original feature set and spatial block again on the same enlarged training pool before adding further complexity.

No broad repeat physician quality/window annotation is needed for this step. Any required adjudication should be restricted to ambiguous training candidates or negative-label uncertainty, with explicit split roles.

## Verification and artifacts

Synthetic empty, constant, peak and boundary inputs passed finite-output and original-column parity checks. All twelve runs performed finite-gradient optimizer updates and exact checkpoint reload comparisons. Full-image map coverage was checked, and the additional six maps/features were cached privately for reproducible follow-ups. Training/first-image comparison took 117.25 seconds; additional evaluation took 297.94 seconds. These are end-to-end experiment times, not clinical inference latency.

Aggregate receipts in `generated-files/eagle-eye/calcification-candidate-20261001/`:

- `augmented-feature-ablation-20261003.json`
- `augmented-feature-additional-20261003.json`
- `augmented-feature-matched-burden-20261003.json`
- `augmented-feature-pool-inventory-20261003.json`
- `augmented-feature-provenance-20261003.json`

The provenance receipt records code/data hashes, package versions and verification controls. Case-level maps, features, coordinates, source identities and checkpoints stay in protected research storage. No workstation runtime, clinical weights, service environment or GUI was changed. Clinical GUI acceptance was not applicable to this isolated experiment.
