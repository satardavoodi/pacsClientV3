# B41: Shared processing and calcium context for lesion typing

Date: 2026-10-05. Source audit, three actual ablation fits and architecture proposal.
No production changes, joint training or measured speedup. Bone-age files are excluded.

## Source evidence

worker.py decodes DICOM for detection; CREATE_LESION reads the original DICOM using
ITK for ROI preparation. Separate image-read paths exist, but their runtime burden
has not been profiled. SINGLEVIEW_FEATURES.py already supplies four feat_calc_*
features: bright-component count, radius mean/std, nearest-neighbor distance.
Its calcification_proxy thresholds the masked ROI at percentile 99 and retains
components <=30 pixels. These are pixel-scale proxies, not the accepted native
residual-peak/FPN calcium pipeline, physical lesion counts or validated morphology.
B34 explains why several calcium model dots can support the same anatomical focus.

## Executed ablation

Remove those four columns only; fit B38 A0 with 55 features on the identical
1,189 rows / 594 studies and exact study partitions for seeds 17/29/43. Same
boosting parameters, study weights and argmax; no threshold tuning. Three fits,
reload checks and exact partition checks passed. Cached fitting/serialization
took 1.71 seconds, excluding loading. No real calcium-head inference was run.

Means across repeated development splits, percent:

| Features | Macro F1 | Mass recall | FA recall | Asymmetry recall |
|---|---:|---:|---:|---:|
| B38 including proxies | 38.28 | 94.31 | 21.08 | 0.00 |
| Without four proxies | 41.41 | 95.20 | 23.51 | 3.33 |

Removal improves mean macro F1 by 3.13 points and preserves/improves Mass recall
in all splits. However, FA recall falls in two of three splits and Asymmetry gains
just one correct row in one split. Retain as an exploratory comparator, not a
qualified upgrade. This does not prove calcium is unhelpful; it shows unvalidated
brightness proxies can fail to help. Repeated development exposure limits inference.
Private evidence: P/typing-no-calc-proxy-20261005 and
P/typing_no_calc_proxy_20261005.py, including model/code/source hashes and predictions.

## Proposed architecture and additional outputs

1. Decode once per authenticated Eagle Eye server job into immutable native pixels
   plus padding, spacing, polarity, orientation and coordinate transforms. Bind
   cache entries to input content, frame and preprocessing version; expire per job.
   Preserve branch-specific preprocessing until numerical parity is demonstrated.
2. Share compatible crops, masks and derived scales. Keep native detail for calcium;
   coarse context and native ROIs serve soft-tissue analysis. Never replace calcium
   input with the detector's low-resolution or 8-bit image merely to share work.
   Calcium skin suppression must not silently suppress peripheral masses.
3. Associate frozen calcium outputs with soft-tissue ROIs: support inside/around
   the ROI, cluster footprint, dispersion, distance from border, local contrast,
   score summaries and explicit availability. This is an auxiliary signal, not a
   rule that calcium implies mass or malignancy. No calcium does not imply normal.
4. Only later compare a shared multi-scale encoder with separate task heads.
   Different existing checkpoint feature maps cannot simply be reused interchangeably.
   Shared training requires checking negative transfer for both tasks.

Near-term output: soft-tissue location/type, calcium support and their spatial
association, each with separate scores/status. A mass may contain calcium; these
are not mutually exclusive labels. Candidate point count is not calcification count.
Morphology, distribution, density and distortion outputs require their own labels
and validation; localization dots alone cannot teach BI-RADS morphology.

## Discriminating experiments

- Efficiency: shared decode/cache versus independent pipelines. Require prediction
  and coordinate equivalence, then measure full-study CPU latency and peak RAM.
  Running two separate decodes sequentially is not a single-pass improvement.
- Accuracy: same soft-tissue model with/without actual calcium-branch predictions.
  Audit upstream checkpoint exposure; use cross-fitted training predictions and
  fitting-only upstream training for held evaluation. Reference calcium labels must
  not become inference features. Missing branch output is unavailable, not a zero
  negative. Preserve normal and mixed-finding reference semantics.
- Joint encoder: only after evidence of value; retain both independent branches as
  comparators. Track per-type recall/PPV, calcium point/cluster recall and reviewed
  false marking, paired lost/gained cases and full inference cost. Eight reviewed
  calcium cases do not qualify broader performance.

## Primary sources checked 2026-10-05

[Mammo-CLIP author code](https://github.com/batmanlab/Mammo-CLIP) provides classifier
and RetinaNet adapters around its encoder. This supports component reuse, not a
claim of one-pass execution for our tasks. Its noncommercial restriction remains.

[Multi-task DETR preprint, August 2026](https://arxiv.org/abs/2608.09801) studies
shared representations for malignancy prediction and localization. Its reported
metrics do not validate our three-way typing or microscopic calcium endpoint.

Decision: share compatible image preparation first; separately test actual
cross-task features. No blanket shared-backbone replacement or new clinical outputs.
