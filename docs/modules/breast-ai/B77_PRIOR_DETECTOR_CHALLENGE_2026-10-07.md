# B77: Prior YOLOX detector challenge and external-model access audit

## Objective and scope

Date2026-10-07. Owner asks whether previously investigated models perform better on
the full-image benchmark. Replayed two available calcification-specific YOLOX pilots
on the calcification stratum, with an identical-image Razi comparator. This is not
an all-lesion comparison or a result for every internet architecture. B50/B64/B65/B69
are reference-ROI classifiers; they cannot supply independent full-image detection.

Protected artifacts: local point-review root, Windows candidate root and Linux
candidate root, directory `b77-external-detectors-20261007`. Scripts stage.py, run.py,
operating.py; protocol.json, manifest-private.json, results.json, exposure.json,
per-model predictions-private.json and operating-diagnostic.json. Images/IDs remain
on authorized research hosts. No live-server changes or fitting in this experiment.

## Cohort and preprocessing

All75 eligible B76 images with Suspicious Calcification annotations:80 cluster boxes.
128 explicit BI-RADS1/No Finding images selected by smallest SHA256(B77:image_id),
without looking at predictions.203 complete images, not reference-guided crops.
Same native DICOM-to-uint8 routine as B76; 1024-pixel windows,768 stride, edge padding,
native coordinates and whole-image NMS0.5.3716 tiles per model. Independent reference
coordinates used only by evaluation. No annotation-derived candidate filtering.

Zero source-hash intersection with the hash-matched historical pilot manifest,
including training rows, but hash representation parity and person independence
remain unverified. Earlier VinDr exposure cannot be universally ruled out.
Prior pilot photometry parity is unverified; failure here does not isolate training,
domain shift and preprocessing. Sampled128 negatives are not the full2258-negative
benchmark; results are not a screening-prevalence estimate.

## Models and execution

- YOLOX-Tiny pilot,512 prior updates, frozen-BN recipe. SHA256
  `2ceb6b7d2525f6d32c35bca0f52ac276b4bc75e40eb804ced86679cb9fa7e350`.
- YOLOX-Tiny pilot,1024 prior updates, adapted-BN recipe. SHA256
  `4144bf66ceaaf20906b51d584645a46753b864c950609275063d7c1c510e82fe`.
- B76 Razi source predictions on precisely these selected images, area0.002 and
  score0.45. Reused predictions, not a new clinical-service run.

Official YOLOX input BGR0..255, FP32, strict state reload, finite-output assertions,
proposal floor0.01, NMS0.5/top100 per tile. Two prior checkpoints were limited-fit
research pilots, initialized from COCO with a replaced classification head, not
published fully qualified mammography models. Upstream commit
6ddff4824372906469a7fae2dc3206c7aa4bbaee; existing local runtime reused. A100 execution
99.58s for both models excludes56.15s native staging and transfer. No new fitting.

## Results

One-to-one IoU0.3 matching to calcification boxes only, independently of class output.
IoU0.5 sensitivity check retained. Frozen thresholds0.01/0.1/0.45 recorded before run.
Scores from different models are not calibrated to the same meaning.

| Model / threshold | Calcification clusters found | Marks on128 normal images | Marks per normal image |
|---|---:|---:|---:|
| Razi source /0.45 | 22/80 (27.5%) | 67 | 0.523 |
| YOLOX512 /0.01,0.1,0.45 | 0/80 | 0 | 0 |
| YOLOX1024 adapted BN /0.01 | 54/80 (67.5%) | 4405 | 34.414 |
| YOLOX1024 adapted BN /0.1 | 19/80 (23.75%) | 436 | 3.406 |
| YOLOX1024 adapted BN /0.45 | 0/80 | 0 | 0 |

At IoU0.5, Razi matches9/80, adapted YOLOX matches39/80 at0.01 and8/80 at0.1.
Normal images with marks:55/128 Razi;116/128 YOLOX at0.01;100/128 at0.1.
The lower-threshold YOLOX finds32 more clusters, but generates roughly66 times as
many normal-image marks. At0.1 it finds fewer clusters than Razi with more false marks.
Post-test descriptive thresholds0.15,0.2,0.25,0.3,0.35,0.4 all yield zero predictions;
this is exploratory operating-point inspection, not independent threshold calibration.
No comparable-false-positive-rate superiority or paired uncertainty established.

Why Razi22 here versus17 in B76: B76's class-agnostic assignment competes across all
reference lesion types before counting hits by label. B77 matches only calcification
references, allowing matches previously assigned to another coexisting finding.
Both use the same original predictions. This is a changed endpoint, not a model gain.
Do not compare27.5% or67.5% directly with B76's all-lesion44.48%.

## External detector audit

[Mammogram Mass Analyzer author repository](https://github.com/vbookshelf/Mammogram-Mass-Analyzer)
describes two trained YOLOv5L mass detectors and links Kaggle weights. Public Kaggle
metadata lists exp50_best.pt and exp51_best.pt; metadata receipt saved. Actual download
of app/training-fold files returned AccessDenied with a location restriction. No
weights downloaded, no execution, no claim of external-model performance. Training
overlap with this VinDr TEST remains unknown. Do not bypass the access restriction.

[NYU breast classifier](https://github.com/nyukat/breast_cancer_classifier) outputs
breast-level cancer scores and optional heatmaps; it is not an interchangeable
all-lesion bounding-box detector without a separately qualified localization rule.
These sources were checked2026-10-07. Access, task and training provenance must be
resolved before published headline scores become local comparators.

## Decision and next action

No promotion. Prior YOLOX pilots do not demonstrate a useful sensitivity/false-mark
improvement at tested operating points. More detections alone are insufficient.
This does not establish that YOLO architectures or all public models are ineffective.
Next prioritize the retained high-resolution calcium verifier pipeline on the same
native images, including its fixed clustering rule, and obtain an accessible trained
mass detector with auditable training exposure for the separate general-lesion arm.
Do not replace that general-lesion comparison with these calcification-only numbers.
No GUI/clinical acceptance, deployment, or new model training performed.
