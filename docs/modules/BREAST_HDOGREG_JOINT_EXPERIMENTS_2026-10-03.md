# HDoGReg joint supervision experiments

Two actual decoder/head training runs completed. Neither passed the fixed point-retention development gate. The original comparator remains retained; no Eagle Eye production weights or services changed.

## Supervision and execution

Both runs started independently from the checksum-verified original state-only FPN checkpoint, loaded with `weights_only=True` into a fresh FPN/Inception-v4. The encoder stayed frozen and in evaluation mode. AdamW updated the decoder and segmentation head for 400 successful steps per run; gradients remained finite, clipping was applied at norm 5, and saved checkpoint reload produced identical probe outputs.

The first run sampled 256 public training point patches and selected the 256 highest-scoring negative patches from the existing 1,792-patch training-only negative pool, plus 128 random negative patches. Some random negatives can overlap the hard selection; these counts are draws, not necessarily distinct examples. Of the negative pool, 896 patches had an original maximum probability of at least 0.5. This is patch-pool mining, not completed full-image hard-negative mining.

All eight physician training cases and 16 green regions entered both runs as weak region bags. Four native 128-pixel patches sampled each region; a maximum inside the permitted region supplied the weak positive objective. Other pixels remained unknown. No rectangle was converted into a dense positive mask and no area outside a rectangle was automatically labeled negative. Source hashes and training-group membership were checked. This objective can still select an unrelated bright structure inside a positive region.

The second run used all 1,643 public positive patches, reduced LR from 1e-5 to 3e-6, and changed point/negative/region loss weights from 1/1/0.25 to 5/0.1/0.25. Both used native detail channel zero and the same label-blind nonzero percentile 1/99.5 rendering, mapped to FPN input range -1 to 1. No calibration or test data entered training or hard-negative selection.

## Patch development results

Calibration support: 157 provisional point-positive patches and 256 conservative negative patches. A point hit is a maximum around the point center; a negative patch counts if any pixel exceeds the stated threshold. These are component diagnostics, not clinical screening metrics.

| Weights | Threshold | Point hits / 157 | Negative patches marked / 256 |
| --- | ---: | ---: | ---: |
| Original | 0.01 | 142 | 134 |
| First joint run, step 400 | 0.01 | 140 | 108 |
| Sensitivity-weighted run, diagnostic step 100 | 0.01 | 141 | 134 |
| Original | 0.5 | 137 | 132 |
| First joint run, step 400 | 0.5 | 128 | 9 |
| Sensitivity-weighted run, diagnostic step 100 | 0.5 | 136 | 132 |

The first run's strong negative suppression at 0.5 also lost nine point hits. The second did not resolve this tradeoff. The scripts retain the best diagnostic adapted checkpoint even when none qualifies; that saved checkpoint is explicitly rejected in the decision receipt. It must not be mistaken for an accepted model. The original checkpoint is the retained comparator. Training loss alone does not establish better localization or generalization.

## Full-image comparison

Before prediction, two distinct calibration groups were selected by point-reference support, one image per group, totaling 31 provisional red centers. Two additional distinct conservative negative calibration groups supplied one image each. Both original and sensitivity-weighted models ran on the same full native images with identical percentile rendering and candidate generation. Every reconstructed pixel had tile coverage; no reference ROI filtered inference. Four diagnostic thresholds were inspected, not an optimized clinical operating point.

| Weights | Threshold | Point hits within 8 native pixels / 31 | Components on two negative images | Boxes over 5% of image |
| --- | ---: | ---: | ---: | ---: |
| Original | 0.0003162 | 25 | 106 | 0 |
| Sensitivity-weighted | 0.0003162 | 25 | 103 | 0 |
| Original | 0.01 | 25 | 70 | 0 |
| Sensitivity-weighted | 0.01 | 25 | 67 | 0 |
| Original | 0.1 | 24 | 57 | 0 |
| Sensitivity-weighted | 0.1 | 24 | 54 | 0 |
| Original | 0.5 | 24 | 49 | 0 |
| Sensitivity-weighted | 0.5 | 24 | 47 | 0 |

The marginal burden reduction does not establish a useful screening improvement. Six references remain missed at the lower thresholds. The reference centers are provisional, the negative publisher-count discrepancy remains unresolved, and four development images cannot establish clinical sensitivity, PPV/NPV, or cluster FROC. Components are individual candidate objects, not independently adjudicated clusters. Earlier standard-window diagnostics are not directly comparable with this percentile-rendered run.

The first full-image attempt failed before producing metrics because NumPy percentile arithmetic promoted input to float64. The adapter now casts normalized image input to float32 and checks the dtype; the complete rerun passed. The native cache preparation initially lacked the isolated pydicom runtime path; rerunning with the existing isolated dependency path completed. Neither failed attempt counts as a successful evaluation.

## Next discriminating steps

1. Measure candidate-only coverage of the six misses. A point absent from the candidate mask cannot be recovered by merely retraining the downstream filter. A finer/lower-contrast candidate proposal must also be tested on negatives before selection.
2. Test context-matched training. Native 128-pixel training patches differ from the 512-pixel inference tiles in available context. This is a plausible cause to test, not an established diagnosis.
3. A protected native 512-pixel training cache now contains 65 point-positive tiles and 56 negative tiles from 14 conservative negative training groups. Source hashes and native tile shapes passed; no calibration/test sources entered this cache. It is prepared, not yet trained, and its negative tiles are a mining pool rather than already model-mined hard negatives.
4. Preserve physician boxes and existing window corrections. No additional broad annotation task is warranted yet. If ambiguity prevents distinguishing an actual missed calcification from an imperfect reference, prepare a small targeted queue and explicitly version its changed split eligibility.

The full-image finer-scale candidate audit was interrupted after several minutes without a completed image comparison. The observed stack was inside scikit-image peak-coordinate spacing, not network inference. It produced no accepted full-image coverage result. A reference-centered native 256-pixel candidate diagnostic was substituted to test local visibility; it cannot be reported as autonomous detection or full-image candidate recall. Full-image tiling with candidate overlap and measured border behavior remains necessary before selecting a finer-scale proposal.

The completed local diagnostic covered 31/31 reference centers with both the original candidates and the finer/lower-contrast candidates. Across the 31 correlated point-centered tiles, component count increased from 17,464 to 33,789 with the finer proposal, without additional reference support. This does not justify selecting that proposal. Local candidate availability makes scorer/context behavior a stronger hypothesis for the misses, but local crops do not prove whole-image candidate availability or isolate a full-image cause. The next controlled experiment should preserve native inference context and compare candidate and scorer coverage separately.

Aggregate receipts are under `generated-files/eagle-eye/calcification-candidate-20261001/hdog-joint-*.json` and `hdog-native512-preparation-20261003.json`. Source images, private manifests, reviewed annotations, research scripts and weights remain on protected research storage. This work made no workstation runtime change and claims no live GUI acceptance pass.
