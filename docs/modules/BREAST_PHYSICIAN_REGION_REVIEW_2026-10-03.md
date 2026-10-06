# Completed physician region review

The physician directly confirmed completion of all eight new review cases. The protected live feedback contains 16 valid region rectangles and no individual point annotations. Its unfinished UI flags were retained in the live file; an immutable snapshot records completion by physician attestation. No repeat review is required.

The protected training manifest maps crop rectangles to native source coordinates, retains all eight existing training groups, and treats rectangles as positive region bags. Individual pixels inside rectangles and unmarked areas remain unknown; no dense masks or automatic negative labels were generated.

## Baseline localization audit

Full-source inference used the original DeepMiCa checkpoint and standard DICOM modality/window/polarity/padding rendering. Source hashes were checked. At threshold 0.5, all 16 rectangles contained at least three positive output pixels, but only one rectangle contained a proposal center and none achieved proposal IoU of at least 0.25. Seventeen proposal centers in the reviewed crops lay outside reference rectangles; those locations were not independently adjudicated as false positives. Large merged proposals make positive-pixel occupancy unsuitable as detection evidence.

These eight groups are training material, not an independent sensitivity estimate. The audit does not establish individual calcification recall or clinical screening performance. No weights were changed or promoted.

## Input contract check

The pinned upstream SegmentationDataset normalizes image tensors by division by 255, consistent with the adapted inference. Gamma correction functions are defined in the inspected upstream Python source, but no calls were found. Neither finding supports claiming a missing normalization or gamma transform as the cause.

Next training should use native-resolution region supervision with established point labels and separately verified negative training examples. Existing calibration and test groups remain frozen. Acceptance must assess localization and negative-image activation together; region occupancy alone is insufficient.

Aggregate execution evidence: `generated-files/eagle-eye/calcification-candidate-20261001/new-physician-region-baseline-20261003.json`. Private annotation and source manifests remain outside the repository.
