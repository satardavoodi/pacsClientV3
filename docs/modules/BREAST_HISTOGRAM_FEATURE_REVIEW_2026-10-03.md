# Histogram and texture features for calcification confirmation

Status: primary-source review followed by an executed histogram/spatial-peak ablation. See [controlled results](BREAST_HISTOGRAM_PEAK_ABLATION_2026-10-03.md) for twelve runs and additional development evaluation. Histogram and Hessian/radial peak features were tested; LBP/GLCM additions below remain unexecuted proposals. The existing candidate feature checkpoint is preserved.

## Supported interpretation

The current 19-feature scorer includes mean/max intensity, residual contrast, normalized contrast, context means/variances and FPN evidence. It does not contain intensity histogram bins, LBP histograms or GLCM features. Adding a compact histogram/texture block is a distinct hypothesis, not a description of work already completed.

A first-order gray-level histogram discards spatial arrangement. Images containing the same intensity values arranged into different shapes have identical histograms. Thus an intensity histogram alone cannot uniquely identify punctate, fine pleomorphic, or coarse calcification morphology. Scanner processing, display transforms, ROI size, background tissue, and quantization further limit transfer of a published histogram as a universal template.

Relevant primary evidence:

- [Texture analysis for clustered microcalcification detection](https://pubmed.ncbi.nlm.nih.gov/23060416/) uses second-order histograms in surrounding regions to derive texture features for positive versus normal ROIs. This supports local spatial texture testing, not a universal subtype histogram dictionary.
- [Quantitative assessment of amorphous calcifications](https://pmc.ncbi.nlm.nih.gov/articles/PMC9839357/) combines local radiomic features, object measurements and spatial distributions for benign versus actionable findings among selected amorphous-calcification ROIs. It uses HDoGReg segmentation and excludes ROIs with no overlapping segmented calcifications. Its classification results therefore do not establish autonomous detection performance or separation of multiple morphology types.
- [Morphological analysis of microcalcifications](https://pubmed.ncbi.nlm.nih.gov/9486066/) studies explicit shape measurements and variation of calcification size. It supports preserving morphology alongside intensity rather than treating histogram shape as a substitute.

No validated portable histogram library mapping each requested morphology to a unique template was established by this focused search. This is a bounded search finding, not proof that no such resource exists.

## Proposed ablation

Keep the current candidate generator, source images, group partitions, labels, comparator weights and point-identity evaluation fixed. Compare:

1. Existing 19-feature confirmation model.
2. Existing features plus a small first-order/local histogram block: bright-tail proportion, entropy, selected quantiles, and normalized candidate-versus-surrounding histogram distance.
3. The same additions plus a compact spatial texture block, such as selected GLCM measures or an LBP histogram. Compare the blocks separately before combining them.

Use native DICOM-derived input under a versioned normalization contract. Choose fixed spatial ROI scales with documented pixel-spacing behavior and training-only quantization/bin definitions. User-adjusted review brightness must not silently change model features. Avoid attempting to estimate rich histograms or texture matrices from a one- or two-pixel object; surrounding patches provide context, with object shape retained separately. Small-sample, homogeneous, empty and near-zero-variance cases require explicit handling rather than hidden NaNs.

If prototype matching is tested, derive positive and negative prototypes solely from fitting groups, with group-aware weighting. Learn feature selection and normalization only there. No Internet diagram is imported as medical ground truth. Keep feature dimension modest relative to the present 52 fitting positives; do not equate adding features with increasing accuracy.

Freeze checkpoint and threshold before the next additional-image evaluation. Measure reference identities, not just hit counts, at a matched negative-object burden; include footprint and giant-object checks. The existing model exchanged one previously covered reference for another. An augmentation must explicitly report whether that loss persists, whether it introduces new losses, and whether negative burden improves. The repeatedly accessed development cohort remains unsuitable as final independent qualification.

## Morphology labels and physician contribution

First target remains calcification presence/localization. Current publisher red points and physician green region boxes do not, by themselves, supply verified punctate/pleomorphic/coarse subtype labels. Do not infer subtype or benign/malignant labels from brightness or the shape of a coarse review rectangle.

A later morphology classifier needs reviewed subtype labels, actual object/cluster shape and distribution, and sufficiently resolved images. Any physician request should be a small targeted set with clear label definitions and uncertainty/mixed-pattern options, preserving existing boxes and window corrections. No broad repeat annotation is needed merely to test histogram features for presence detection.
