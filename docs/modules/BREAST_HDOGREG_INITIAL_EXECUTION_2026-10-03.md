# HDoGReg initial execution

Status: research component executed; no clinical qualification or production weight change. This implements the first diagnostic stages of `BREAST_CALCIFICATION_EXECUTION_PLAN_2026-10-03.md`.

## Runtime and checkpoint verification

Dependencies were installed into an isolated research target directory; existing service environments and processes were not modified. Original source commit and checkpoint SHA remain those in the asset receipt. A100 research processes used an 8 GiB allocator cap after checking free memory.

The old checkpoint contains serialized module records unsupported by the modern weights-only loader. A restricted loader resolves only the 34 explicitly inspected checkpoint globals and rejects unknown globals; it does not use unrestricted class resolution. The resulting original FPN has 43,570,017 parameters. Synthetic inference, one head update, finite gradients, strict state reload and output equality passed.

A fresh segmentation-models-pytorch 0.2.0 FPN/Inception-v4 accepted the original state with strict key matching and produced exactly identical output on the synthetic parity input. A state-only original-weight artifact was saved for future restricted weights-only loading. Fourteen historical source-change warnings were observed; synthetic parity does not establish exact reproduction of the historical software or published clinical results.

## Native physician-region diagnostic

The original checkpoint, not synthetic or adapted weights, ran on all eight native 1024-pixel physician training crops. Standard DICOM modality/window/polarity/padding rendering was used. Synthetic bright-object detection, the empty-peak adapter and tile reconstruction checks passed. The upstream empty-peak function returns an empty coordinate array rather than an image mask; the adapter maps that explicit no-peak condition to a correctly shaped empty mask.

| Variant | Components | Regions containing a component center | Centers outside reviewed regions | Positive pixels outside reviewed regions | Boxes larger than quarter crop |
| --- | ---: | ---: | ---: | ---: | ---: |
| Bright candidates only | 62,493 | 16/16 | 58,504 | 3,008,390 | 1 |
| Hybrid, threshold 0.0003162 | 341 | 16/16 | 48 | 1,867 | 0 |
| Hybrid, threshold 0.001 | 319 | 16/16 | 47 | 1,849 | 0 |
| Hybrid, threshold 0.01 | 283 | 16/16 | 33 | 943 | 0 |

The inspected upstream threshold was 0.00031622776601683794; candidate overlap acceptance was 0.3. Total reviewed crop area was 8,388,608 pixels. No physician-region filtering entered inference. Component-center coverage is not individual-calcification recall. Outside-region components remain unmatched rather than automatically adjudicated false positives. Individual-object IoU with a large cluster rectangle is not a suitable individual-point endpoint.

This is a promising geometry/footprint change relative to broad activation, not proof of sensitivity preservation. Candidate-only behavior is excessively noisy. Elapsed crop diagnostic time: 31.61 seconds; peak allocated VRAM: 0.285 GiB.

## Actual training-subset diagnostic

Eight point-positive and eight conservatively negative native 128-pixel detail patches were selected solely from the existing training cache. No calibration/test patch entered this run. Decoder and segmentation head (2,427,777 parameters) received 120 successful AdamW updates at LR 1e-4; encoder weights/statistics remained frozen. Positive loss used a nearby maximum around a provisional point center; other positive-patch pixels were unknown. Known negative patches supplied high-scoring negative pixels. No physician rectangle was filled into a dense mask.

The original model already scored all eight training-positive points above 0.5 and no negative patch above 0.5. The final counts were unchanged, although the objective decreased and parameters changed. This verifies executable optimization/reload, not a newly demonstrated accuracy gain or generalization. Elapsed updates/evaluation: 1.79 seconds, peak VRAM 0.356 GiB. The diagnostic checkpoint is kept separate and never substituted for original-weight evaluation or production.

## Full-image pilot

An initial four-group calibration pilot used two conservative negative images and two images selected from groups with red annotations. The selected positive-group views had zero eligible red point annotations, so that run cannot estimate point retention. This limitation was detected from actual support counts. A subsequent diagnostic selects two distinct calibration groups with genuinely point-eligible images before inference, without selecting by prediction outcome. It uses full native images and tile coverage verification; label information is used for reference scoring only.

On the two conservatively negative full images in the initial run, original hybrid threshold 0.0003162 produced 70 individual components, 13,281 positive pixels out of 27,262,976 pixels, and no component box above 5% of image area. Threshold 0.01 produced 54 components and 12,783 positive pixels. Small false-mark burden remains unresolved; component counts are not cluster FROC and publisher-negative group counts have a known discrepancy. No clinical operating threshold is selected by this pilot.

The subsequent two point-eligible full images contained only two eligible provisional red centers in total. Both were covered within eight native pixels by candidates and by each of the three hybrid settings. This support is far too small for a sensitivity claim. Hybrid components on those two full images numbered 83/70/64 at the three respective thresholds. Execution took 95.03 seconds and 0.332 GiB peak allocated VRAM. The initial four-image run took 134.27 seconds. No final test or clinical image interpretation was performed.

## Evidence locations and next gate

Aggregate receipts reside under `generated-files/eagle-eye/calcification-candidate-20261001/`: `hdog-smoke-20261003.json`, `hdog-state-parity-20261003.json`, `hdog-native-region-diagnostic-20261003.json`, `hdog-tiny-fit-20261003.json`, `hdog-bounded-full-image-calibration-20261003.json`, `hdog-point-full-image-calibration-20261003.json`, and `hdog-lineage-20261003.json`. Source/data/weights remain in protected research storage.

Next decision: combine genuine point-retention evidence with known-negative burden before proceeding to larger training. If candidate generation loses reference points, correct source/scale/threshold coverage first; a confirmation network cannot recover missing candidates. If retention is satisfactory but false marks persist, train with task-matched hard negatives and evaluate cluster grouping independently. The reserved patch-test results are not reused for tuning. Exact acquisition/preprocessing transfer and independent full-image clinical qualification remain open.
