# Calcification execution plan

Status: authorized research comparison; asset preparation started. No deployment-qualified candidate exists. Literature basis: `BREAST_MICROCALCIFICATION_METHODS_REVIEW_2026-10-03.md`; local failure basis: `BREAST_CALCIFICATION_FAILURE_DIAGNOSIS_2026-10-03.md`.

## Objective and measurement contract

Detect real calcifications and localize their clusters without covering normal tissue with large boxes. Measure full-image behavior, not just patch classification or presence of a few positive pixels in a large reference region. No 100% clinical sensitivity claim or guarantee is permitted.

Report reference-point recall where actual point labels exist, region/cluster localization where physician rectangles exist, full-image FROC at 0.5/1/2 independently adjudicated FP marks per image, known-negative-image output burden, predicted-pixel footprint, box area, and latency/VRAM. FROC levels are research comparison points, not physician-approved deployment limits. Where negative truth is incomplete, report unmatched proposals rather than falsely labeling them all FP. Individual small-object boxes are not required to match the IoU of an enclosing cluster rectangle; cluster geometry and individual points are scored separately.

## Fixed data rules

- Keep the existing KIOS grouping and partitions: 74 training, 13 calibration, 13 test groups; all views/repeat images of a group stay together.
- The eight newly reviewed cases/16 rectangles are already training groups. Use them for training diagnostics, never as independent accuracy evidence.
- Physician rectangles provide positive region bags, not filled positive masks. Unknown individual pixels and unreviewed outside regions remain unknown. Use actual publisher point labels or reviewed masks for point/pixel objectives.
- Only independently justified negative groups/crops are negative supervision; preserve the unresolved publisher-negative-count discrepancy. Never mine calibration/test examples into training.
- Existing calibration has been repeatedly inspected. The reserved test groups also had their patch-test result inspected in prior work. Do not call them pristine for future architecture selection: keep them excluded from tuning and acquire a separate untouched grouped full-image cohort for final qualification.
- Preserve original sources, feedback, rendering settings, source hashes and all physician marks. No repeat annotation request for the completed eight cases.

## Routes

**A: Native multiscale candidates plus learned confirmation.** Reproduce HDoGReg's bright-object/proximity components where compatibility and rights allow, then compare explicit local-detail/context scoring. Motivation: physically small objects should be proposed independently of broad region activation. Audit candidate recall before adding a scorer; downstream confirmation cannot recover absent candidates.

**B: Native segmentation with staged adaptation.** Retain the original DeepMiCa comparator and unfreeze decoder, followed by selected encoder stages only when justified. Use online hard-negative mining and appropriately masked point/region losses. Motivation: previous compact-verifier and 65-parameter output-head interventions did not demonstrate backbone adaptation.

The owned FCOS/YOLO route remains a comparator whose weak bounded results do not establish global architecture inferiority. New architectures require sufficient task-matched training; this plan does not simply repeat an identically short run and name a winner.

## Ordered gates and stopping rules

| Stage | Concrete work | Budget / continuation gate | Failure response |
| --- | --- | --- | --- |
| 0. Assets and contracts | Pin code/weights; inspect format, dependencies, grayscale normalization, tiles, spacing and output units | CPU inspection and load/update/reload smoke before accuracy work; no clinical services modified | Port only necessary components or use an independently implemented native candidate baseline; record unavailable assets explicitly |
| 1. Geometry and input | Synthetic asymmetric landmarks, border tiles, coordinate round-trip; compare label-blind native rendering contracts | Every source-to-crop transform must match; no ground-truth ROI filtering during inference | Fix geometry/rendering before training; keep label-dependent cleanup excluded |
| 2. Tiny training fit | A few training-only point/region positives plus verified negatives; disable unnecessary augmentation; inspect gradients in intended layers | Initial cap 500 successful updates; finite outputs, demonstrable loss improvement, positive localization and no broad negative collapse | Diagnose target, loss, frozen layers and feature construction; do not extend epochs blindly |
| 3. Candidate comparison | Native original-segmentation objects versus multiscale DoG/Hessian at matched reference coverage | Up to three development operating settings per route; measure candidate burden before scorer | Reject a candidate source that loses reference coverage without an offsetting validated operating point |
| 4. Bounded training | Route A detail/context confirmation versus Route B staged adaptation; hard negatives from training only | Initial 1 GPU-hour per route, two development-selected seeds if a route merits retention; best checkpoint chosen without test access | Stop branch for numerical failure, persistent no-learning or unacceptable miss/burden tradeoff; extend only with a stated correctable cause |
| 5. Cluster output | Group confirmed objects with physical spacing and bounds; test chain-joining and tile-border cases | Compare full-image output, not cosmetic clipping; do not discard large true clusters by arbitrary area limits | Rework grouping independently from network; retain individual candidate evidence |
| 6. Independent qualification | Freeze weights/rendering/threshold/grouping; assess untouched grouped images, uncertainty and density/vendor subgroups | Better sensitivity at matched adjudicated FP burden, or fewer FP at matched sensitivity, with acceptable localization and resource use | No promotion; targeted adjudication/additional training coverage and a fresh evaluation cycle |

These are initial experiment caps, not a promise that one hour is sufficient to train either model. Logs must record successful updates, LR, loss components, known-label support, gradients, checkpoint selection, peak memory and wall time. A model that cannot satisfy quality constraints is not selected merely for low cost.

## Physician follow-up

First run computational gates without further physician work. If label gaps prevent discrimination, send a small queue of genuinely uncertain misses and model-generated false-mark candidates. Show original image and individual evidence; preserve existing green rectangles. Do not send another page dominated by giant boxes or repeatedly ask for completed quality corrections. New adjudications remain versioned, and adding them to training changes their future evaluation eligibility.

## Infrastructure and preparation receipt

Verified A100-SXM4-40GB with 12,147 MiB free at plan preparation. Start with an 8 GiB research process cap and recheck memory before each GPU run. No service eviction or H200 expenditure is needed for current preparation.

HDoGReg source was fetched into protected Linux research storage at commit `86c34ce415401cffcfdd3a78cc1032a9711fd850`. Its public `trainedFPN.pth` release asset was downloaded (174,826,521 bytes), SHA256 `fcf7d8a570aa87c7fb52de34ee3b0d593a12ddd79c40689a794a13c0eed97e7f`. Static opcode inspection identified a legacy serialized FPN/Inception-v4 object with old segmentation-models-pytorch/pretrainedmodels classes. It has not been executed or loaded. Do not use unrestricted pickle loading or quietly replace architecture/classes. No license file was found in the cloned repository; commercial weight/code rights remain unverified, and no production redistribution is authorized by this preparation.

The upstream FPN input preprocessing explicitly uses mean/std 0.5; this is a distinct model contract from DeepMiCa's division by 255. Preserve that distinction when adapting inputs. Upstream inference runs breast delineation, bright-object segmentation, FPN inference and hybrid combination as separate steps: [author pipeline](https://github.com/cmarasinou/HDoGReg/blob/master/pipeline_infer.sh).

Aggregate asset receipt: `generated-files/eagle-eye/calcification-candidate-20261001/hdogreg-asset-inspection-20261003.json`. Current next action is compatible safe checkpoint loading and native candidate smoke; completed asset download is not a quality result.
