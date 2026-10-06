# Bone Age model and training review - 2026-10-04

Status (updated 2026-10-05): bounded research experiments complete; selected
candidate locked, independent evaluation blocked by missing authorized reference data.
The initial Razi checkpoint was verified against the research baseline on 2026-10-05.
Later the same day, the owner expressly reiterated activation on the Razi Developer
Eagle Eye server after the pending GUI gate was reported. The selected candidate
is now active on its 8002 service; see the activation receipt section below.
The research-phase statements about unchanged weights/services remain historical.
Patient records and image identifiers are
excluded from this record.

Latest consolidated results and the live Razi checkpoint identity evidence are in
[the before/after consolidation](#beforeafter-consolidation-and-razi-baseline-verification---2026-10-05).
Earlier run updates below are chronological observations, not current job status.

## Hosts and actual locations

| Host | Role and observed assets |
|---|---|
| wina100 / WIN-I5E5QM7V2R2 | Windows AI management/serving node, no GPU. Current standalone inference source and checkpoint: `D:\Bone\BoneInference\bone_age_inference.py`, `D:\Bone\BoneInference\final_model.pth`. Older assets exist in `D:\EnhancedBoneAge` and `D:\Bone\outputs*`. |
| lina100 / gpu | Linux training host. NVIDIA A100-SXM4-40GB, 40960 MiB; sampled memory used 28295 MiB and utilization 0%. Training tree `/home/gadmin/EnahancedBoneAge` (existing spelling). |
| Workstation source | Eagle Eye imported inference under `modules/ai_imaging/eagle_eye_engines/vendor/bone_age`; authenticated jobs own company inference. Report calculation/rendering is deterministic local presentation, not an alternate provider/model route. |

Linux assets include `main.py`, `main_v15.py`, the saved
`outputs_v15/main_v16.py`, older two-stage training files, `outputs_v15`,
`outputs_v16`, and 12 runs in `outputs_sweep_v16`. The existence of an old
two-stage directory does not establish that the currently served model is two-stage.
Current Windows inference is a single-step EVA02 regression model using sex conditioning.

## Checkpoint identity

| Checkpoint | Bytes | SHA256 |
|---|---:|---|
| Windows `BoneInference/final_model.pth` | 350806623 | `4266a30b0f1aeeae2cdc65e49f4b5f5cd54f00137e4ad7a8606b2ae12ae95390` |
| Linux `outputs_v15/final_model.pth` | 350806623 | `a8ace52944d74f62ed315481fd6d42d43918cd909095b847d8a19d6f3ace01ac` |
| Linux `outputs_sweep_v16/trial_05/final_model.pth` | 350806623 | `cffabcc57e5a9f1fff675f84206b2388705f382019f02542f6f5ac6620e97a25` |
| Linux `outputs_v16/final_model.pth` | 354624747 | `63fb2dc8c36646704bace78538ae7912c4deb0a90453073532acb1640c125d10` |

All 12 sweep final checkpoints were hashed; none matches the Windows checkpoint.
No byte-identical final checkpoint was found in the inspected Linux output trees.
Read-only CPU comparison now excludes identical tensor states for v15 and all
12 sweep finals. The fingerprint includes sorted tensor keys, dtype, shape and
contiguous raw bytes, loaded with `weights_only=True`. The workstation bundle,
whose file hash matches the Windows serving checkpoint, has tensor SHA256
`c519f94b0f199fd12117a40a3b26dbf825e281e18ef054191e50579d4da2e64f`.
V15 has `607fa78fd9f0b3fe8ffa81e7afd3cf6794e21252bc6993d66566d55fabc2b46e`;
trial 05 has `f9330d6ab063bc96f0251701231d0fe9d3a95fe9f4a6d4150df36fc01b7d6d3c`.
Each has 488 tensor entries. V16 uses a different container schema and was not
assigned a tensor fingerprint. Broader archive search remains necessary to bind
the active weights to their training receipt. This check executes no model and
allocates no GPU tensors.
The original Windows inference source hash matched its previously imported provenance.

Linux `main.py` and `outputs_v15/main_v16.py` share source SHA256
`fa046f329ee0a7f81f869c456dccae00f36c385d030c0901d23052c9d4e41e1b`.
That saved source still names `outputs_v14` in Config; a directory name alone is
not a run-bound code/config receipt. `main_v15.py` hashes to
`490696c8d078dedc4e61deeaaf4deaec74e3cb0568d88515d458d5418c0a8cfc`.

## Cohort readiness

| Annotation source | Images | Sex annotation | Skeletal-age range | Image-ID duplicates | Important limits |
|---|---:|---|---|---:|---|
| `Bone+Age+Training+Set+Annotations/train.csv` | 12611 | 6833 male / 5778 female | 1-228 months | 0 | Only id, boneage, male; no chronological age or person/group key |
| `Bone+Age+Validation+Set/Bone Age Validation Set/Validation Dataset.csv` | 1425 | 773 male / 652 female | 3-228 months | 0 | Only Image ID, male, Bone Age (months); no chronological age or person/group key |

Normalized image-ID overlap between the two annotation files is zero. This does
not prove patient-level separation or absence of duplicated pixels. The youngest
age group is sparse: training has 13 skeletal-age labels below 12 months and
validation has 2. Grouped split, image-content duplication, reference-reader
reliability, rights/provenance receipts and contemporary local-population coverage
are not established by these CSVs.

These label distributions are not normal-population growth or skeletal-maturity
percentile references: chronological age is absent. The PDF uses a separately
identified historical reference instead.

## Development metrics and curves

| Run | Recorded evaluation | Within 6 / 12 months | Recorded history | Interpretation limit |
|---|---|---|---|---|
| outputs_v15 | Calibrated final MAE 6.844 months, RMSE 9.1518, R2 0.951851 | 55.65% / 84.56% | 59 rows; minimum epoch-validation MAE 6.8575 at row 48; final row 6.889 | Best selected checkpoint epoch 19; aggregate age-group checkpoint score differs from minimum overall MAE |
| sweep trial_05 | Calibrated final MAE 6.7104, R2 0.953426 | 57.19% / 83.93% | 97 rows; minimum epoch-validation MAE 6.7984 at row 57; final row 6.883 | Worst coarse-group MAE 10.059 months despite lowest overall sweep MAE |
| outputs_v16 | Raw final MAE 8.322917, RMSE 11.081326, R2 0.929408 | 47.7193% / 76.7719% | 35 rows; minimum epoch-validation MAE 8.041991 at row 34; final row 8.058503 | Different checkpoint size/metric contract; not a paired claim of deterioration |

The 12 sweep MAEs range from 6.7104 to 7.2173 months in their saved summary.
Trial 06 has a lower recorded worst coarse-group MAE (8.480) than trial 05,
illustrating the tradeoff between aggregate and subgroup performance. No confidence
intervals, independent locked test receipt or deployed-checkpoint paired evaluation
were established. These are recovered development metrics, not active clinical accuracy.

## Serving versus training contract

Observed training code uses EVA02 base patch14 at 448 pixels, sex conditioning,
normalized ages divided by 228, weighted sampling, EMA/SWA evaluation, a
multi-term uncertainty loss, six augmentation views including rotations, and
out-of-fold bias correction over validation predictions. The inspected training
transform stretches to a 448x448 square; current serving preserves aspect ratio
with letterboxing, uses only original/horizontal-flip views with uncertainty
weighting, and clips predictions to 0-228 months. Training augmentation uses
stronger CLAHE for samples with target age below 60 months. In the inspected code,
validation disables that stronger CLAHE; the helper's age_months parameter is
otherwise unused. This is not evidence of validation target leakage. Training and
validation additionally crop via contours and sharpen the image; these preprocessing
differences require a deployment-parity audit before assigning saved metrics to the
deployed pipeline.

The saved final checkpoint is a state dictionary; corrected validation predictions
do not by themselves establish a deployed calibration artifact. A K-fold mean-bias
correction on validation predictions is not a calibration of model confidence.
The model's log-variance/TTA weights are not a validated patient confidence interval.

A numerical failure-path concern is present in imported inference: Python min/max
clipping can turn a raw NaN into the upper age bound before the outer worker's
finite check. This source-level risk was identified without altering the inference
code or claiming an observed patient failure. It should be guarded before the next
qualified engine rebuild. The trainer also substitutes black pixels after a failed
image decode; the next dataset audit should count/reject these samples explicitly.

## Next discriminating work

1. Establish lineage for the Windows checkpoint by archived source/config/logs and
   normalized CPU state-dictionary fingerprints. Bind serving code, preprocessing,
   normalization, TTA and checkpoint into one immutable manifest.
2. Evaluate that exact serving pipeline on the existing reviewed validation source,
   preserving raw and calibrated results separately. Audit image preprocessing
   and calibration artifacts before comparing against training metrics.
3. Audit patient grouping and pixel duplicates; lock a separate test set and report
   sex/age/site subgroup support, MAE/bias and tolerance coverage with intervals.
4. Guard nonfinite raw predictions and unreadable inputs, then qualify a separate
   candidate bundle. Retain the current weights during comparison.

No further optimizer run is justified solely by the recovered aggregate metrics.
Host inspection and CSV/history reads did not start Torch training or evict GPU jobs.

## Accuracy improvement decision and comparators

The recovered curves approach a plateau. They do not establish that simply running
more epochs will improve generalization. Trial 05 versus v15 differs by only
0.1336 months of recorded MAE (about four days); this is not a paired significant
gain, and their corrected development scores cannot qualify the active checkpoint.
Prioritize the 2-5-year group and sparse infant coverage rather than optimizing
the overall average alone.

| Comparator | Rationale | Readiness / limitation |
|---|---|---|
| Exact incumbent EVA02 plus its current serving pipeline | Establish actual baseline; compare one preprocessing/TTA difference at a time | Assets exist locally; training-run identity and independent accuracy not established |
| Compact ConvNeXt-Tiny with sex-conditioned regression | Practical cost/quality comparator using the existing label schema | Proposed owned training baseline, not a claim to reproduce another paper or an available qualified checkpoint |
| Deeplasia EfficientNet/Inception plus hand segmentation | Task-matched public code and documented local inference/service route; useful robustness comparator | Official code license is CC BY-NC-SA 4.0; commercial inclusion is not cleared, and weights/dependency compatibility are not locally qualified |
| Hand ROI / ensemble candidate | Test whether background removal and complementary errors improve subgroup accuracy | Requires reviewed ROI coverage and independent evaluation; additional latency must be measured |

Current primary-source review checked on 2026-10-04:

- [Bram et al., 2025](https://journals.sagepub.com/doi/10.1177/03635465251359618)
  reports a ConvNeXt ensemble MAE of 3.68 months on the RSNA 200-image test set
  and 5.66 on DHA for the initial RSNA-trained model. Those cohorts and ensemble
  differ from our reused 1425-image development validation. This motivates an
  experiment, not a promise of a 3.68-month local result.
- [Deeplasia official implementation](https://github.com/aimi-bonn/Deeplasia)
  documents EfficientNet/Inception, sex input, hand masks and local inference.
  Its [code license](https://github.com/aimi-bonn/Deeplasia/blob/master/LICENSE.md)
  is noncommercial; code and checkpoint permissions must be checked separately.

Recommended first experiment: evaluate the active checkpoint on a fixed private
development cohort, comparing current serving to the recovered training evaluation
contract, with raw predictions retained before clipping/calibration. Use an isolated
worker, fixed ordering and case keys, bootstrap paired differences, sex/age support,
bias, MAE, RMSE and coverage within 6/12 months. Record decode failures separately.
Fit any bias correction on a separate calibration partition. Continue to a compact
architecture or ROI experiment only if parity does not resolve the main errors.
Select on subgroup performance and measured target-host latency as well as overall
MAE; qualify only once on an untouched, independently reviewed test cohort.

Chronological age is absent from the owned annotation CSVs. Adding it to the current
model input requires new data and retraining; reception availability alone does not
make that valid. Because the product measures delayed/advanced skeletal maturation,
any chronological-age-conditioned candidate must be tested specifically in those
groups for suppression of the clinically relevant discrepancy.

This review does not include a new inference benchmark, optimizer update, duplicate
pixel audit or local external-test result. No runtime source or active model changed.

## Sub-six-month objective: proposed experiment contract

### 2026-10-05: bounded adaptation job started

Owner requested continued execution toward the target. A frozen-incumbent feature
and regression-head adaptation experiment is running in the existing isolated
Linux research directory, outputs `head-research-20261005`. Source helper:
`generated-files/bone-age-reference-research/train_frozen_head.py`.
It loads the verified incumbent, extracts original/flip shared features with the
current letterbox pipeline for 12611 training and 1425 development images, and
checks decoded-pixel SHA256 overlap before any optimizer update. Missing/decode
failures and cross-split exact duplicates fail closed. Near duplicates and patient
independence remain unproven; this is development research, not final qualification.

After the input gate, the existing regression head is adapted with AdamW, LR 1e-4,
L1 loss, batch 128 and a maximum of 30 epochs. The backbone and sex-conditioning
parameters remain frozen. Best development checkpoint, history, optimizer-step
count, changed-parameter assertion and strict checkpoint reload are recorded.
This first low-cost screen uses natural sampling; balanced variants follow if
justified. It is not the compact alternative comparator or full-backbone training.

Resource bounds: 15% GPU memory cap, two CPU threads, feature budget 1800 seconds,
total internal budget 2400 seconds and process timeout 2700 seconds. The observed
initial status was 200/14036 feature inputs completed, with no logged failure.
Research PID returned by launch was 1897749 (shell launch identity; verify the
actual child before any cancellation). Status is in `head-research-20261005/status.json`;
diagnostics in `head-20261005.log`. No active clinical model/service was changed.
The job's eventual result has not yet been observed and the below-six objective
remains active. Anonymous historical prediction tables were not used for training.

Continuation inspection confirmed the actual Python child PID 1897751 and timeout
PID 1897750 are live, with feature status advancing from 1000 to 2100/14036.
No restarted or duplicate job was launched. The CPU-only evaluator
`generated-files/bone-age-reference-research/evaluate_frozen_head.py` was compiled
and staged next to the owned engine. It requires terminal training success before
reading the best checkpoint, strictly reloads the head, joins baseline by actual
case keys and checks reference equality, then reports raw/clipped metrics,
age-by-sex support, tolerance coverage and paired exploratory image-bootstrap
intervals. It retains private prediction rows on Linux and prints only aggregates.
No result from that evaluator has yet been claimed. Selection uses the same
development cohort, so its interval cannot qualify an independent accuracy claim.

Further continuation confirmed Python PID 1897751 remains live and reached
3800/14036 images. A separate CPU synthetic guard demonstrated finite L1 loss,
an actual AdamW parameter update and exact prediction equality after strict
checkpoint reload. No GPU allocation or clinical rows were used by that guard.
This verifies the head-training mechanics, not anatomical learning or accuracy.

RHPE's publisher-linked `LICENSE.txt` was read through its public download URL on
2026-10-05. It restricts use to noncommercial research/education, includes researcher
responsibility/indemnification and binds a commercial employer when applicable.
The owner was asked to explicitly authorize accepting those terms for research;
no acceptance, image/annotation download or leaderboard submission occurred.
Existing-data work continues independently. Publisher license reference:
https://drive.google.com/file/d/1GcgGn5nbPcyOmgXp_2CWzjLhxCT9fAQf/view

The frozen-head job subsequently completed in 873.90 seconds with 2970 actual
optimizer steps and strict checkpoint reload verified. All 12611 training and
1425 validation images decoded successfully; each split has that many distinct
decoded-pixel hashes and exact cross-split overlap is zero. This does not establish
patient or near-duplicate independence. CPU case-keyed evaluation selected epoch
29, checkpoint SHA256 `3d7e5fa4e02bfe90a8eaf4443daf6f0b13130dd27d9d0ab33bc867d5103065a6`.
Candidate raw/clipped MAE is 7.40235 months, RMSE 9.77861, bias +0.09348;
within +/-6 months 51.86%, within +/-12 months 81.26%. Baseline was MAE 7.67353,
48.98% and 79.37%. Paired exploratory image-bootstrap MAE difference is -0.27118
months with interval [-0.38328,-0.16309]; same-cohort selection remains a limitation.

Important subgroup tradeoffs: 2-<3-year MAE improved 8.826 to 5.890 and 3-<4 years
6.546 to 5.369, but 5-<10 years worsened 8.360 to 8.858 and 17-19 years worsened
6.836 to 8.030. Do not promote this candidate on overall MAE. The below-six goal
is unmet. This head uses arithmetic two-view averaging, whereas the baseline uses
uncertainty weights; the comparison is a complete candidate difference, not an
isolated attribution of the gain to optimization alone.

A bounded full validation comparison of the historical trial 05 weights was
started next, output directory `trial05`, preserving incumbent/head artifacts.
Python child PID 1900041 was verified live at 111/1425 cases. It uses the same
three preprocessing variants and two-view contract as the incumbent parity screen,
to separate checkpoint improvement from incompatible saved development scores.
No clinical promotion or new provider route occurred.

Trial 05 comparison completed over all 1425 rows in 191.32 seconds, weight SHA256
`cffabcc57e5a9f1fff675f84206b2388705f382019f02542f6f5ac6620e97a25`, peak allocated
CUDA memory 706861056 bytes. Raw uncalibrated two-view pipeline MAE: letterbox
7.09320, square 6.93214, square-plus-sharpen 6.93661 months. The historical
checkpoint is stronger than the current checkpoint in this research comparison,
but below-six is still unachieved. Do not equate these with its corrected saved
6.7104-month metric. This is repeatedly used development data.

The next bounded job `run_crop_comparison.py` compares current/trial05 weights
using the recovered contour crop (Otsu, morphology, 5% contour cutoff, 10% padding,
30% minimum retained area), CLAHE and Gaussian sigma-3 sharpening, followed by
square resize and the current two-view uncertainty weighting. It does not claim
full six-view training evaluation reproduction. Outputs are separate under
`crop-comparison-20261005`, timeout 720 seconds, internal budget 600 seconds.
No optimizer run, service restart or active checkpoint replacement occurs here.

Crop comparison completed in 191.79 seconds over all 1425 development rows for
both checkpoints: current MAE 7.52366, trial05 MAE 6.79733 months. Trial05 bias
was -0.30812 months. The fixed-weight crop improvement is insufficient for the
goal and remains development-only; neither checkpoint was promoted.

The compact comparator is now an actual research implementation rather than a
proposal. Official `timm/convnext_tiny.fb_in1k` model card identifies ImageNet-1k
pretraining and Apache-2.0; a 111351205-byte feature-backbone state dictionary
was obtained through timm 1.0.27, with 27820128 feature-backbone parameters.
Source: https://huggingface.co/timm/convnext_tiny.fb_in1k (checked 2026-10-05).
No patient input was uploaded to obtain weights. Local reuse rights of the owned
bone-age training data remain the existing project assumption, not a new legal claim.

`train_compact_candidate.py --smoke` passed a finite synthetic CPU loss, actual
optimizer update and exactly equal predictions after strict checkpoint reload.
A separate real training job was launched next, directory `compact-20261005`:
ConvNeXt-Tiny, 224-square CLAHE inputs, ImageNet normalization, sex embedding and
256-unit regression head, L1 loss, AdamW backbone LR 2e-5/head LR 3e-4, capped
sqrt-frequency age sampling [0.5,2.0], batch 8, up to 12 epochs. Entire model is
adapted, with original/flip arithmetic TTA for development evaluation. Best state,
private keyed predictions, optimizer counts and epoch history are persisted.
GPU cap 15%, two CPU threads, internal budget 3600 seconds/process timeout 3900.
Input failures and nonfinite outputs fail closed. No separate final-test accuracy
or speed claim is made, and downsampling may limit anatomical detail: this compact
screen is a comparator, not a conclusive test of every CNN architecture.

Actual compact Python PID 1901155 was subsequently verified live at 600 optimizer
steps in epoch 1, elapsed 174.45 seconds. No duplicate job was launched.
Case-keyed CPU comparison of all 1425 images also screened two fixed arithmetic
ensembles: trial05 crop plus adapted incumbent head MAE 6.77242; trial05 crop plus
trial05 square MAE 6.78463. These modest gains do not justify increased serving
complexity or satisfy the target. Trial05 crop female MAE 7.11932 versus male
6.52574; the sex gap persists. Full age-by-sex results are in the private aggregate
`keyed_candidate_comparison.json`, with no IDs printed or exported.

A fixed five-fold, sex-specific affine least-squares cross-fit was evaluated next:
inputs are predicted age and recorded sex only; correction fitting uses each
fold's other 80% of reference labels, never its own held-out labels. Raw crop MAE
6.79733 became 6.75204 months, bias -0.00577, +/-6 coverage 57.12%. This is an
exploratory development calibration result, with prior checkpoint selection on
the same cohort and image-only folds; it is not independent validation. No final
calibrator was deployed, no confidence interval was inferred from uncertainty
weights, and no correction based on the unknown true skeletal-age band was used.
Results: `crossfit_affine_analysis.json`; helpers `compare_keyed_candidates.py`
and `crossfit_affine.py`. The remaining gap calls for substantive training/data
improvement rather than presenting bias correction as a below-six achievement.

Compact run provenance was bound in `compact-20261005/run_receipt.json`:
trainer SHA256 `08431823d73ab0ccc7485d0b8eb7db7407c5854dbab052d80fa4717883337684`,
upstream feature-weight SHA256 `7eb3d7fdb4b13b486a0d08e03657f2e4bea1f84c0d26d8cbaf8e42c270b34ebc`,
training annotation SHA256 `9459296c0fca3e3cd908e79002914d0d90c7f5e46936eefd34b11261468ce209`,
development annotation SHA256 `fdfeff3e7351f0bdc629f34c01803291c57c1198bc3376076bb4934daa334fec`.
Runtime is Python 3.10.12/Torch 2.11.0+cu130/timm 1.0.27/OpenCV 4.11.0.
This receipt identifies the experiment inputs; it does not establish final
training completion, independent accuracy or commercial clinical qualification.

First complete compact epoch: sampled training MAE 16.15605 months and development
MAE 10.90420. Training and validation transforms/sampling differ, so the gap alone
is not evidence of overfitting. At inspection, the real Python process 1901155 was
live in epoch 2 at 1600 optimizer steps, elapsed 508.41 seconds. Continue the
prespecified bounded run; an undertrained first epoch cannot fairly rank the
architecture. No pretrained image-classification accuracy is used as a bone-age
accuracy claim. The current best research candidate remains the historical EVA02
pipeline, and no clinical model was replaced.

`summarize_compact_checkpoint.py` now validates completed-epoch prediction
snapshots against case-keyed incumbent references, matching sex/labels and the
best recorded development MAE. It checks file version stability during observation
and emits epoch-specific aggregate receipts without interfering with checkpoint
writes or allocating GPU memory. This is evaluation of persisted predictions,
not a claim of model reload equivalence while training is still active.

Second compact epoch completed: sampled training MAE 11.52554, development MAE
9.32067 months (down from 10.90420), bias +3.45694; +/-6-month coverage 42.11%,
+/-12-month coverage 70.81%. Female MAE 9.60821 (n=652), male MAE 9.07813 (n=773).
`epoch-2-aggregate.json` binds prediction SHA256
`a102cbb9eb30ccab169999ddabb77e117333838486d720e4616a5cca1086af97` and includes
age-by-sex cells. Python PID 1901155 was verified live in epoch 3 at 3200 steps,
elapsed 1007.93 seconds. This is continued learning, not a satisfactory comparator
result yet; its positive bias and worse overall MAE prevent promotion. The bounded
run continues unchanged and the independent below-six target remains unmet.

The existing `modified/test` folder was checked as a possible independent
evaluation source using an aggregate-only inventory. It contains zero PNG/JPEG
images, so its name is not evidence of a usable test cohort. No independent
reference or patient linkage was established there. The helper
`audit_existing_test_pool.py` emits only counts and overlap totals. RHPE acquisition
still awaits the owner's explicit terms authorization; no terms were accepted
by an automatic continuation. This does not stop the existing-data training run.

### Execution started under owner authorization

The owner authorized beginning improvements after reviewing the experiment ladder.
An isolated research directory was created on lina100 at
`/home/gadmin/bone-age-research/20261004-parity-pilot`. Active services and model
assets were not altered. An isolated virtual environment inherits existing pinned
host packages (Torch 2.11.0+cu130, timm 1.0.27, OpenCV 4.11.0, Albumentations 2.0.8);
no package upgrade was performed. This is a research environment, not a serving
parity qualification of dependencies. GPU memory is capped at 15% of device memory,
with two CPU threads, one-image batches, a 600-second inference budget and a
720-second process timeout. Preflight showed 12147 MiB free and 300 GiB disk free.

The active checkpoint was copied and its SHA256 verified as
`4266a30b0f1aeeae2cdc65e49f4b5f5cd54f00137e4ad7a8606b2ae12ae95390`.
Strict loading and actual forward passes succeeded. The first deterministic
age-enriched 30-image pilot completed in 4.39 seconds, peak allocated GPU memory
706861056 bytes. Pilot MAE: current letterbox 6.5577, square 6.1892,
square-plus-sharpen 6.2734 months. This selected pilot is execution evidence and
a hypothesis screen, not representative clinical accuracy. All variants use
CLAHE and the current two-view uncertainty weighting; the square variants do not
claim complete reproduction of the training preprocessing.

A full 1425-image development-validation comparison was then launched, preserving
pilot artifacts. Raw finite predictions and case keys stay in private Linux outputs.
No optimizer run or active model promotion occurred during this first experiment.

Full comparison completed: all 1425 cases, three variants, 192.30 seconds inference,
peak allocated GPU memory 706861056 bytes; all selected inputs loaded and raw
outputs passed finite checks. This uses benchmark PNG loading and the copied engine,
not an end-to-end DICOM/authenticated-server benchmark or serving dependency parity.

| Variant | MAE months | Bias months | Female MAE (n=652) | Male MAE (n=773) |
|---|---:|---:|---:|---:|
| Incumbent letterbox + current two-view TTA | 7.6735 | -0.5331 | 8.054 | 7.352 |
| Square + same TTA | 7.6137 | -0.5847 | 7.869 | 7.399 |
| Square plus sharpening + same TTA | 7.6533 | -0.6117 | 7.908 | 7.439 |

Paired square-minus-letterbox absolute-error difference is -0.0598 months;
1000-resample image bootstrap interval [-0.1871, +0.0637] includes zero. Authoritative
patient groups are unavailable, so this is an image-level exploratory interval.
Do not promote a geometry change from this result. The initial enriched pilot's
apparent benefit did not generalize to a convincing full-cohort improvement.

Incumbent group MAE: <2 years 7.131 (n=13), 2-<5 years 8.544 (n=81),
5-<10 years 8.360 (n=394), 10-<15 years 7.442 (n=809), 15-19 years
6.526 (n=128). The active checkpoint has now been measured in this research
runtime; it must not inherit trial 05's 6.7104-month corrected score. Relative to
this 7.6735-month baseline, reaching 6.0 needs at least 21.81% reduction, rather
than the 10.59% planning calculation based on a different checkpoint.

Private results: `full/private_predictions.json`; aggregate results and status:
`full/summary.json`, `full/aggregate_analysis.json`, `full/status.json` under the
Linux research directory. No real clinical records were read or exported.
Next training decision: preserve this keyed baseline, complete pixel/group and
reference QC before freezing research train/development partitions, then compare
the compact sex-conditioned candidate and incumbent fine-tuning with an explicit
age/sex selection contract. Training execution is authorized by the owner but no
optimizer run has yet been started. No process is left training in the background.

Owner objective: investigate a mean absolute error below six months. This is a
population average, not a guarantee that every prediction lies within six months.
An additional requirement of <6-month MAE in every supported age/sex band must
be reported separately; infant performance currently cannot be estimated reliably.

Using trial 05's recovered development MAE 6.7104, the improvement needed to reach
6.0 is 0.7104 months (10.59% relative). At least this improvement is required, with
additional margin for uncertainty and external-site shift. These calculations
are planning arithmetic, not measured candidate gains:

| Counterfactual on the current validation distribution | Approximate overall MAE reduction |
|---|---:|
| Reduce 2-<5-year MAE from recorded 10.059 to 6.0 (81/1425 rows) | 0.231 months |
| Reduce <1-year MAE from 14.862 to 6.0 (2/1425 rows) | 0.012 months |
| Reduce 5-<15-year MAE by 0.6 (1203/1425 rows) | 0.507 months |

Thus young-age enrichment alone would not attain the aggregate target. An
approximately 0.6-month reduction across the large middle-age cohort together
with the hypothesized 2-<5-year gain would cross six on this distribution, but
neither effect is established and evaluation prevalence can change the result.

### Sequential experiment ladder

| Stage | Candidate / controlled comparison | Evidence and stopping decision |
|---|---|---|
| E0 | Exact current weights and serving pipeline; restore case keys and raw outputs | Recover active baseline, decode failures, age/sex errors and uncertainty. No architecture ranking before valid paired inputs. |
| E1 | Fixed weights: compare crop/geometry/sharpening and 2 versus 6-view TTA one factor at a time; compare precision-weighted versus arithmetic TTA | Retain only reproducible development improvements within measured serving latency. Do not presume recovered training preprocessing is optimal for current weights. |
| E2 | Fixed data/pipeline: compact ConvNeXt-Tiny sex-conditioned regression versus incumbent; plain MAE/Huber versus existing composite objective; separately ablate MixUp/CutMix | Current trainer already includes sampler boosts, adaptive age-group weighting, uncertainty loss and EMA/SWA. More of these mechanisms is not an untested simple fix. Avoid a large grid; retain candidates on prespecified subgroup and overall metrics. |
| E3 | Targeted independent <5-year/late-maturity additions; reviewed hand ROI or local feature candidate | Count unique patients and labels by sex/site; preserve locked holdout before adaptation; compare staged sample-size learning curves. Source histogram/rights review precedes acquisition. |
| E4 | Small ensemble of candidates with genuinely complementary case-keyed residuals | Cross-fit ensemble/calibration selection. Never average anonymous prediction files merely because their label sequences look similar. Measure full CPU-serving cost. |

Research precedent checked 2026-10-04:
[a 2026 global/local study](https://www.nature.com/articles/s41598-026-54051-9)
reports RSNA validation MAE 4.88 months and RHPE validation MAE 6.74, illustrating
both a below-six development result and source-dependent performance. Its
RSNA test MAE 3.81 is a different cohort. Public code/checkpoint availability was
not established during this review; classify this as a methodological comparator,
not a ready qualified bundle. The [RSNA ensemble study](https://pubs.rsna.org/doi/10.1148/ryai.2019190053)
reports improvement from 4.55 to 3.79 months on its test evaluation; that does not
establish the same gain for our correlated sweep models or clinical population.

### Qualification and resource boundary

Proposed primary success gate: the upper 95% patient-bootstrap confidence limit
for overall MAE is below 6.0 months on an untouched independently reviewed cohort.
Also report per-band MAE and intervals, macro-average age-band MAE, bias, failure
rate, 90th-percentile error and coverage within +/-6 and +/-12 months. Overall
success does not qualify unsupported infant subgroups or establish a six-month
error bound for an individual. Prespecify acceptable subgroup degradation and
target-host latency before comparing candidates rather than selecting them after
viewing the final test. Preserve delayed/advanced maturation cases in qualification.

Start E0/E1 in an isolated existing runtime; refresh current hardware usage and
bind dependencies/code/weights before scheduling. Use a small prespecified QC
cohort to test execution, followed by the fixed development cohort if loading and
failure accounting pass. E2/E3 optimizer runs remain a separate execution phase;
this investigation did not start training, evict GPU jobs, acquire new datasets,
replace weights or claim that the six-month objective has been achieved.

## Age-stratified follow-up

Read-only follow-up recomputed statistics from saved prediction CSVs. Bands use
reference **skeletal age**, not chronological age (the latter is unavailable).
Bounds are lower-inclusive and upper-exclusive, except the final band includes
228 months. Floating-point reference labels within 0.0001 month of an integer were
snapped for bin assignment only: saved normalized float32 labels otherwise move
some boundary cases into the preceding band. Errors retain saved numeric values.
Each run has 1425 predictions and its snapped label multiset matches validation.
There are no case IDs in these files; sex-specific joins and paired significance
claims remain unsupported. These are calibrated development predictions, not
the active model's independent test accuracy or individual confidence intervals.

| Reference skeletal age | Training n | Validation n | v15 MAE, months | Trial 05 MAE, months | Trial 06 MAE, months | Trial 05 within +/-6 months |
|---|---:|---:|---:|---:|---:|---:|
| <1 year | 13 | 2 | 13.70 | 14.86 | 14.22 | 0.0% |
| 1-<2 years | 78 | 11 | 5.38 | 4.38 | 4.55 | 72.7% |
| 2-<3 years | 175 | 17 | 10.09 | 10.37 | 9.84 | 29.4% |
| 3-<4 years | 231 | 26 | 8.03 | 9.15 | 6.92 | 42.3% |
| 4-<5 years | 304 | 38 | 9.95 | 10.55 | 8.94 | 23.7% |
| 5-<10 years | 3487 | 394 | 7.30 | 7.04 | 7.70 | 55.3% |
| 10-<15 years | 7224 | 809 | 6.64 | 6.49 | 6.83 | 59.0% |
| 15-<17 years | 790 | 89 | 4.98 | 4.54 | 5.03 | 73.0% |
| 17-19 years | 309 | 39 | 5.69 | 6.17 | 5.36 | 56.4% |

Infant and toddler denominators are too small for reliable accuracy claims.
Training below five years totals 801/12611 (6.35%); 10-<15 years alone accounts
for 57.28%. In trial 05, bias is +10.37 months at 2-<3 years, +8.73 at 3-<4,
+10.10 at 4-<5 and -4.37 at 17-19. This pattern is consistent with regression
toward common ages, but does not prove that imbalance is the only cause. Label
quality, crop, acquisition and anatomical maturity can contribute. Late maturity
can offer little remaining anatomical information; additional examples do not
guarantee discrimination of precise ages after complete fusion.

The recovered age-band differences do not identify the owner's first and second
teams: team/run/checkpoint lineage is missing. Trial 06's lower young-group errors
and higher overall MAE demonstrate a tradeoff, not a verified team comparison.

### Complementary dataset assessment

| Source | Evidence and potential contribution | Remaining constraint / proposed role |
|---|---|---|
| RHPE / BAAR | Official resource describes about 6.3k Colombian hand radiographs, two expert bone-age readers, bounding boxes/keypoints and a 0-240-month range | Published/released counts differ (original paper 6288; current resource 6279). Audit the acquired release and age-by-sex histogram before claiming tail coverage. Distribution is also centered near 126 months, so merging all images may preserve imbalance. Terms require review; no download or acceptance performed. Reserve independent external subjects before adapting. |
| USC Digital Hand Atlas | Collectors describe about 1400 normal left-hand/wrist radiographs with demographics and radiologist readings, recruited across newborn and ages 1-18, sex and population categories | Promising targeted coverage source, but actual available age/sex counts, duplicates, reference method and usage rights must be verified. Preserve a held-out portion; normal subjects alone cannot validate delayed/advanced maturation. |
| Local reviewed bone-age examinations | Closest match to deployed acquisition/population, can deliberately enrich <5 years and late maturity, delayed/advanced cases | Reception DOB provides chronological age, not bone-age truth. Obtain blinded expert skeletal-age labels and adjudication; group repeat studies by person. No patient extraction or relabeling performed in this review. |
| GRAZPEDWRI-DX | Public wrist-trauma images and chronological age, useful for possible representation pretraining or stress evaluation | Original dataset is not an expert bone-age regression label set; do not substitute chronological age for skeletal age. Trauma, lateral views and incomplete hand coverage limit direct use. |

Sources checked 2026-10-04:
[RHPE official resource](https://bcv-uniandes.github.io/baar-wp/),
[original RHPE paper](https://cinfonia.uniandes.edu.co/wp-content/uploads/2021/06/Hand_Pose_Estimation_for_Pediatric_Bone_Age_Assessment.pdf),
[USC collectors](https://ipilab.usc.edu/bone-age-assessment/),
[GRAZPEDWRI-DX original publication](https://pmc.ncbi.nlm.nih.gov/articles/PMC9122976/).

### Ranked interventions and decision criteria

1. Recover case-keyed raw predictions for the exact serving model. Evaluate both
   skeletal-age and chronological-age bands separately, crossed with sex where
   support permits. Include n, MAE, median/90th-percentile absolute error, signed
   bias, +/-6 and +/-12-month coverage and patient-bootstrap intervals. Until
   case keys exist, do not fabricate sex metrics from repeated age labels.
2. Target collection to <1, 2-<5 and 17-19 years by sex and maturation stage.
   Audit new sources first; duplicate copies of RSNA on Kaggle are not new data.
   Use staged additions of independent patients and repeated grouped learning
   curves to measure gain per added sample. No fixed image count guarantees
   a required MAE; choose test support from desired interval precision.
3. Compare capped age/sex-balanced sampling with the current weighted sampler
   and group loss. The trainer already includes balancing; stacking larger
   sampler and loss weights may amplify noisy rare labels. Training augmentation
   adds views, not independent patients, and must preserve ossification anatomy.
4. Compare a common shared model with hand/region attention before separate
   age-specific experts. A model cannot route on the unknown true skeletal age.
   Any learned gating or chronological-age routing needs validation specifically
   in delayed/advanced patients to avoid reinforcing an age prior.
5. Qualify on prespecified subgroup requirements and macro-average age-band MAE
   alongside natural-distribution overall MAE. Retain the current model until a
   candidate improves target groups with acceptable uncertainty and without
   material degradation in other supported groups. Fit residual corrections only
   on a separate calibration cohort using available inference-time inputs; never
   subtract a correction based on the patient's unknown reference skeletal age.

The age-stratified audit itself did not change clinical report wording or the active
model. Later authorized training is recorded in the execution sections above.
Audit helpers are private generated research tooling, not runtime code.

### Compact epoch 3 observation

Completed-epoch training MAE 10.65231 and development MAE 9.13874 months;
aggregate bias changed from +3.45694 at epoch 2 to -2.82086, so modest MAE
improvement does not establish stable calibration. Female MAE 10.59367/bias
-7.04375 (n=652) versus male MAE 7.91156/bias +0.74100 (n=773).
Female performance degraded despite the better overall average. The checkpoint
is not eligible for promotion; the bounded training comparator continues before
judging architecture capacity. `epoch-3-aggregate.json` records prediction SHA256
`eb2627d4aa95f0d225a0063e35ca1568fa8a11336ff14c12fadee9c9b92cdaec`.
Python PID 1901155 was verified live in epoch 4 at 4800 optimizer steps, elapsed
1505.45 seconds. No duplicate optimizer run, active model change or final-test
claim occurred. The independent below-six objective remains unmet.

### Compact sampler exposure audit

The actual capped square-root age sampler was recomputed from the owned training
CSV. Natural male share 54.18% becomes expected sampled male share 54.95%, so a
large overall sex-count distortion is not established as the cause of the epoch-3
sex error gap. Conditional age/sex effects and output-head instability remain
hypotheses; this aggregate calculation does not identify a causal failure.
Expected exposure changes: <2 years 0.72% to 1.89%, 2-<5 years 5.63% to 10.53%,
5-<10 years 27.65% to 30.05%, 10-<15 years 57.28% to 43.36%, 15-19 years
8.71% to 14.17%. Late-age male share increases from 70.34% to 72.68%.
Replacement sampling does not create additional independent patients: <2-year
support stays 91 training images and 2-<5-year support stays 710.
`sampling_audit.json` records aggregate evidence; `audit_compact_sampling.py`
does not modify the live trainer or dataset. The observed epoch-4 Python process
1901155 remains the sole compact training job, with no duplicate restart.

Compact epoch 4 completed at 6308 optimizer steps: training MAE 10.09935,
development MAE 8.96654, bias -3.07010 months; +/-6-month coverage 41.40%,
+/-12-month coverage 72.98%. Female MAE 9.52751/bias -4.04939, male MAE
8.49338/bias -2.24410. Female performance improved from epoch 3 while male
performance worsened, despite a lower overall MAE. This is not uniform subgroup
improvement or qualification. The actual Python child 1901155 was verified live
at elapsed 33:06 and the prespecified bounded run continues; no restart occurred.
`epoch-4-aggregate.json` prediction SHA256:
`4badc8a0b153b81c080c7ad1c1f18bdb540b1723e80ab8370de56a2ed923d3d3`.

Compact epoch 5 completed: sampled training MAE 9.61837, development MAE
8.03721, bias +0.94163; +/-6-month coverage 48.49%, +/-12 coverage 77.33%.
Female MAE 8.62584/bias +2.47267 and male MAE 7.54072/bias -0.34976 both
improved versus epoch 4. Bias continues to change direction across epochs;
do not infer calibrated confidence or uniform age-band adequacy from the lower
mean. `epoch-5-aggregate.json` records keyed prediction SHA256
`aa0f9adb5765b0b798a00e1256936fd921b22add4213be8df3212ad7efc62690`.
Python child 1901155 was verified live in epoch 6 at 8000 optimizer steps,
elapsed 2512.60 seconds. No restart occurred; existing budgets remain in force.
The compact comparator still trails the best EVA02 development route and does
not satisfy the independent below-six objective.

Compact epoch 6 completed with sampled training MAE 9.19046 and development
MAE 8.46316 months. Training error improved while development error worsened;
epoch 5 remains the selected checkpoint. This single fluctuation does not prove
overfitting or justify changing the running protocol. Python child 1901155 was
verified live at epoch 7, 9600 optimizer steps and elapsed 3015.64 seconds.
An independent CPU integrity check strictly loaded every epoch-5 state key,
verified finite parameters and a deterministic finite synthetic forward pass.
Checkpoint SHA256 is
`7221f8b8e398693e9ac157f88d3dc092d0118760ef39f3fcf85f135f6a30f7b5`.
This verifies file/model integrity, not clinical accuracy or real-image prediction
equivalence. The verifier does not import or execute the training entry point.

The bounded compact run is terminal: Python child 1901155 disappeared and its
log records the explicit 3600-second research-budget TimeoutError. Seven epochs
completed; epoch 7 training/development MAE was 8.50961/8.56980 months. Epoch 8
was partial and is not reported as a completed evaluation. The persisted status
file can remain stale after this exception; process/log evidence controls.
Post-stop strict CPU reload and keyed aggregate verification both passed for
the retained epoch-5 checkpoint. No clinical model or service was changed.

Post-stop unaugmented training-fit diagnostic used 320 training images, 32
deterministically SHA256-ordered rows in each of five coarse age bands by sex.
Original/flip arithmetic TTA and preprocessing matched development evaluation.
MAE was 6.32953 months and bias +1.40396. This age/sex-balanced subset has a
different distribution from all 1425 development images; the difference from
8.03721 is not an unbiased full-cohort generalization-gap estimate. It shows
nonzero training fit error and does not establish one definitive cause for the
development plateau. Development subgroup MAE remains heterogeneous: ages
5-<10 years 9.43925 (n=394), 10-<15 years 7.38169 (n=809), 17-19 years 9.38712
(n=39); the oldest female subset has MAE 14.39596 (n=8). Below one year, MAE
18.50877 is based on only two cases and cannot support a stable age-band claim.
This compact run is not promoted over the better EVA02 research candidate.

Controlled low-LR warm-start experiment launched after the first compact run
terminated. It retains preprocessing, split, sampler, batch, loss and architecture;
backbone LR is reduced from 2e-5 to 1e-5 and head/sex LR from 3e-4 to 3e-5.
Parent is the verified epoch-5 checkpoint; optimizer/RNG are newly initialized,
so this is explicitly a warm start, not an exact resume. Budget is three epochs
or 1800 internal seconds (1950-second outer timeout), with minimum development
MAE selection. The parent is retained as epoch 0; a worse trained checkpoint is
not selected. Output directory is `compact-low-lr-20261005`; actual Python child
1910206 was verified live. Synthetic finite-loss optimizer-update and exact CPU
reload checks passed before launch. The run receipt binds parent/source hashes,
annotation versions and revised budgets. This experiment probes optimizer
stabilization, without establishing it as the cause of the preceding plateau.

Independent-pool access follow-up: a bounded search of the existing training
project found no test CSV/XLSX/archive or DHA/RHPE-named file within five directory
levels. This is a scoped inventory, not proof of absence on every host/volume.
Local/browser fetches of USC failed, but Linux fetched the official public page
`https://ipilab.usc.edu/research/baaweb/` successfully (HTTP 200, 39863 bytes).
Its download link points to Google Drive file
`1dVkT4EgxTtgJtUDh28bkHR_aWd8tESO5`; public Drive metadata names
`Digital Hand Atlas.zip`. The page advertises a 7GB download. No explicit usage
license/terms were found in the inspected page, and no archive or subject record
was downloaded. A public link alone does not establish reuse/commercial rights.
The original RHPE agreement question remains pending; unrelated existing-data
training continues. Metadata-page access does not establish a usable independent
test, its reference labels or patient independence.

Low-LR warm-start epoch 1 completed: sampled training MAE 7.62013,
development MAE 7.83687 (n=1425), bias +0.30532 months. This improves mean error
over the parent 8.03721, but +/-6-month coverage decreases from 48.49% to 48.14%;
female MAE improves to 8.17238 while male MAE changes to 7.55387 (previously
7.54072). Lower pooled MAE is not uniform improvement. Keyed target/sex checks
and strict CPU checkpoint reload passed. Prediction SHA256 is
`d3177ffb327aa1ab0288ab9974ca66bf4ebab23ad5bb4ae132be6181843c58a3`;
checkpoint SHA256 is
`dd86f723a4fcafea83dafa960920f5b202e4d2eb8cdc13f26ce780328058f3cf`.
Python child 1910206 was verified live in epoch 2; original budgets persist.
This is development selection evidence, not an independent below-six result.

Fixed equal-weight exploratory ensemble of low-LR epoch 1 and trial05 crop
was evaluated with exact case/target/sex matching on all 1425 development images.
MAE was 6.85494 months (female 7.23514, male 6.53426), compared with crop alone
6.79733. Thus arithmetic averaging improved the weaker compact model but did
not improve the stronger crop comparator. No fitted weights, reference-age-based
routing or test-cohort optimization was used. The evolving compact run can still
change this result; this snapshot does not justify an ensemble promotion.

Low-LR epoch 2 completed with training MAE 7.05053 and development MAE
7.78081 months, bias -1.13058. +/-6-month coverage improved to 50.39%, while
+/-12-month coverage declined to 77.68%. Female MAE worsened to 8.50858
(bias -3.00952), male MAE improved to 7.16696 (bias +0.45425). The pooled
improvement does not resolve sex-specific bias. Prediction SHA256 is
`1738f91d80463f82958c006408395b227ee7d5e241f0da09a2290ae4229bb880`.
Actual Python child 1910206 remained live after evaluation, at 3154 optimizer
steps; one prespecified epoch remains. This candidate still trails EVA02 research
results and does not meet the independent below-six objective.

Prepared next experiment, not yet launched: trial05 crop-preprocessed frozen
features with regression-head-only adaptation. Feature extractor, sex FiLM,
shared layers and uncertainty head remain fixed. Natural training sampling,
original/flip cached features, L1 loss, AdamW LR 1e-4, weight decay .01,
batch 128, maximum 30 head epochs and 2400 total seconds are prescribed.
Feature extraction has an 1800-second limit; failed images/nonfinite outputs
fail the run. The unadapted parent is retained as epoch 0 in minimum-development
MAE selection. Train losses are sample-weighted, including the short last batch.
Both parent and trained head use arithmetic two-view inference in this experiment;
the earlier 6.79733 crop result used uncertainty weighting, so that number is not
silently substituted for the new experiment's matched baseline. Synthetic CPU
finite-loss, optimizer-update and exact reload checks passed. Future execution
must first verify that the current compact child has terminated.

Low-LR run completed all three epochs in 1491.55 seconds, with 4731 optimizer
steps; its actual Python child disappeared and status records complete. Final
epoch training MAE was 6.80126; selected development raw MAE 7.70615, clipped
MAE 7.70609. Female clipped MAE was 8.04082, male 7.42375; male bias remains
+2.06887 months. +/-6-month coverage is 49.75%, clipped +/-12-month 79.86%.
Strict CPU reload, finite parameters and deterministic synthetic forward passed.
Checkpoint SHA256:
`6edeb7e295e7163e345da8cc82a1a1adcc2a4798a836db6f685c550cb1ca558b`;
private prediction SHA256:
`7c7c4257b3b64f70edf9bca42e9db780457e747da15df77eb3f5ebdaafe06a65`.
The compact candidate improves its own parent but remains inferior to the better
EVA02 development route; neither independent accuracy nor clinical promotion is
established. After terminal verification the prepared crop-head research protocol
was dispatched with its 2500-second outer timeout. No active clinical weights,
services or routes were changed.

Exploratory monotone L1 calibration screen completed on fixed trial05 crop
predictions: five fixed image-level folds, separate sex fits, knots at predicted
60/120/180 months, nonnegative segment slopes, bounded endpoints and .005 L1
penalty toward identity. Held-out image references were not used in their own
fit; patient grouping and prior model-selection independence remain unavailable.
All ten constrained solvers converged. Raw MAE 6.79733 became 6.78931 months;
+/-6-month coverage decreased from 56.56% to 56.42%. This tiny change does not
improve over the existing affine cross-fit 6.75204 and does not justify added
calibration complexity or promotion. No coefficients were fitted/deployed for
clinical serving. Crop-head feature extraction continues as a separate live run.

DHA archive metadata was inspected with bounded HTTP ranges after the public
Drive virus-scan interstitial, without accepting a legal agreement or downloading
images. Archive length is 7270275966 bytes; ZIP64 central directory is 310068
bytes with 3103 entries. Only one conventional terms/readme basename was found:
`readme.txt`. Its 547-byte contents were fetched separately and CRC/length checked;
no explicit license/permission/noncommercial/redistribution terms were found.
This is not evidence of unrestricted rights. File count is not patient/image
count, and reference labels/patient independence remain unaudited. Bulk acquisition
and model use of this dataset have not occurred. Private metadata receipts remain
on the research host; no subject names or records are emitted.

Crop-head experiment completed in 970.21 seconds with 2970 optimizer updates;
actual Python child 1917427 disappeared and its status is complete. Independent
CPU strict head reload reproduced the selected epoch-26 development MAE within
1e-4 months. Matched arithmetic-TTA parent MAE was 6.79733, adapted head MAE
6.61232 (n=1425), bias +0.03335. +/-6-month coverage increased to 58.04%,
+/-12-month to 84.70%. Female MAE is 6.96814 (n=652), male 6.31219 (n=773).
Checkpoint SHA256:
`a081c7925b497a26c9a79dcb8496c7b29d791af1326ab6d558f7574f1855be50`.
The paired exploratory image-bootstrap difference was -0.18501 months, interval
[-0.28127,-0.09098]; repeated development selection and unavailable patient
grouping mean this is not an independent qualification interval. The refreshed
decode audit verified all 12611 training/1425 development images, unique hashes
within each cohort and zero exact cross-split pixel overlap; near duplicates and
authoritative patient linkage remain unresolved.

| Reference skeletal-age band | Development n | Matched parent MAE | Adapted-head MAE, months |
|---|---:|---:|---:|
| <1 year | 2 | 14.86588 | 11.96255 |
| 1-<2 years | 11 | 4.77556 | 5.09190 |
| 2-<3 years | 17 | 10.19774 | 6.97836 |
| 3-<4 years | 26 | 8.51741 | 6.61738 |
| 4-<5 years | 38 | 10.43980 | 7.97576 |
| 5-<10 years | 394 | 7.02118 | 7.37630 |
| 10-<15 years | 809 | 6.63323 | 6.38529 |
| 15-<17 years | 89 | 4.87011 | 4.75372 |
| 17-19 years | 39 | 6.31636 | 6.50796 |

This is the best pooled development result from the current controlled research
experiments, but improvements are not uniform: 5-<10 and 17-19 years worsen.
Rare-band counts are too small for stable claims, and the objective remains unmet:
no independently evaluated MAE below six months has been established. Clinical
weights and serving remain unchanged.

Full unaugmented training diagnostic for the selected crop head, using the same
arithmetic two-view inference as development, gave MAE 5.34305 (n=12611),
female 5.62213 and male 5.10706. Unlike the earlier balanced compact subset,
this uses the entire training cohort; differing reference/cohort composition and
prior checkpoint selection still prevent a causal generalization diagnosis.

A bounded cached-feature low-LR warm start then tested LR 3e-5 versus 1e-4,
keeping architecture, dropout, loss, natural sampling and features fixed. Maximum
60 epochs/300 seconds, patience 10 with .01-month minimum improvement were
prespecified. It stopped by patience after ten epochs/990 updates; only 2.25
seconds of cached-head optimization were needed (feature extraction was reused,
not rerun). Selected development MAE 6.61069 versus parent 6.61232 is a negligible
-0.00163-month difference; exploratory paired image interval [-0.01521,+0.01219]
includes zero. Female MAE slightly worsened to 6.97849, male improved to 6.30046.
Strict prediction reload parity and independent CPU history/MAE checks passed.
Checkpoint SHA256:
`8843fc2576de39bc4b70acd752fd073c14f20a95646119f274331c3abe0d12ff`.
Output `crop-head-low-lr-20261005` retains source/parent/cache hashes, all epoch
history, selected head and last optimizer/RNG state. This is a new warm-start run,
not an exact continuation of the preceding optimizer. No meaningful pooled gain
or independent below-six result is established; it is not promoted clinically.

Next controlled experiment dispatched: unfreeze only the final EVA02 backbone
block and regression head, initialize from trial05 full weights plus the selected
crop-head epoch-26 state. All other parameters remain frozen. Crop preprocessing,
float32 arithmetic original/flip validation, L1 and natural training sampling
remain fixed. Final-block LR 1e-6, head LR 3e-5, batch 2 with four-batch gradient
accumulation (nominal effective batch 8) are prescribed; the final short window
is weighted by actual image support. Maximum three epochs/2400 seconds, outer
2500-second timeout, patience two with .01-month improvement anchor. Epoch-0
full-image evaluation must reproduce the prior cached baseline within .001 month
before training. Selection retains that parent if trained epochs are worse.
Synthetic GPU backward/update confirmed finite gradients, an actual last-block
weight change and unchanged SHA256 across every frozen parameter. No clinical
accuracy claim follows from this guard. Output is `eva-last-block-20261005`.
Final checks include strict full-state reload, first development-batch prediction
parity and all-frozen-parameter hash equality; full-cohort independent evaluation
will still be required. Source compilation passed and the real run is separate
from every active clinical service.

Last-block parent full-image evaluation completed: MAE 6.61232594 over 1425
images, reproducing the cached-head result 6.61231852 within .00001 month.
The actual research child is 1924492; 7815681 parameters are trainable. Trainer
SHA256 is `eaeb644e3aebae25466d3fb00e37e5bd51d815004c2c2332ac3b78bc63ef75a6`.
Epoch-0 full checkpoint strict CPU reload, finite-parameter inspection and
deterministic synthetic forward passed; checkpoint SHA256 is
`2b457ad86f02e285f8e1c9bd168dee95ef3f48e1b2ae395ca46b5fd8f2315548`.
This verifies baseline reproducibility and checkpoint integrity, not a new
training benefit or independent accuracy.

Windows independent-pool follow-up: bounded four-level CSV inventory under
`D:\Bone`, excluding virtual environments, found two three-column files with
reference-age columns. SHA256 and row-count comparison identified exact copies
of the existing 12611 training and 1425 development annotation files. Neither
constitutes a new independent evaluation pool. No patient records/identifiers,
file names containing subject information or image pixels were displayed. This
scoped inventory does not establish absence elsewhere on the Windows host.
The owner was asked for an authorized physician-referenced independent cohort
location; no response is assumed from automatic goal continuations. Existing
last-block training remains active and independent of that pending information.

Last-block epoch 1 completed at 1577 optimizer steps. Sampled/augmented training
MAE was 5.43964 and development MAE 6.66310 months, worse than the matched
parent 6.61233 by .05077 month. The parent remains selected; the worse epoch
does not replace it. The training metric includes dropout, random horizontal
augmentation and an unfrozen last block, so it is not directly comparable to
the earlier unaugmented cached-training diagnostic. One evaluation does not
establish persistent overfitting or benefit. Actual child 1924492 was verified
live in epoch 2, 1600 steps; the prespecified budget/patience remain unchanged.

CPU-only sex-specific cached-head screen completed: two regression heads each
initialized from the shared crop-head epoch 26; frozen features, dropout .3,
L1, natural within-sex sampling, AdamW LR 1e-4 and weight decay .01 remained
fixed. Thirty epochs/300-second cap were prespecified, selecting minimum pooled
development MAE including the shared parent. Synthetic updates/reload guard
passed; actual run completed 3000 updates in 27.96 seconds, selected epoch 18,
with strict serialized-checkpoint prediction parity. Development MAE 6.60289
versus parent 6.61232 is only a .00943-month decrease, not a useful accuracy
breakthrough. Female MAE 6.96126 and male 6.30061 still differ; +/-6-month
coverage is 58.46%. Private prediction SHA256:
`a3c3318f5ce257efe58bcf75abf71acd17f22ac3eba95d3ed3905a039d01c63d`.
Exact keyed targets/sex matched all 1425 development images. This extra head
complexity is not clinically promoted; no independent qualification follows.
Separate last-block GPU child 1924492 remained live in epoch 2 at 2100 steps.

Last-block run is terminal: child 1924492 disappeared, status records complete
with patience stop after two evaluations/3154 updates in 2261.70 seconds.
Epoch-2 training MAE 5.42423 and development MAE 6.63844 still trail the matched
parent 6.61233; epoch 0 remains selected. All frozen-parameter SHA256 checks
passed and strict full-state reload reproduced the first development batch.
Post-stop independent CPU integrity and keyed-cohort aggregate checks passed;
selected checkpoint SHA256 remains
`2b457ad86f02e285f8e1c9bd168dee95ef3f48e1b2ae395ca46b5fd8f2315548`.
No third epoch was started: the prescribed no-improvement patience was reached.
The local original clinical weight file SHA256 still matches the original
`4266a30b0f1aeeae2cdc65e49f4b5f5cd54f00137e4ad7a8606b2ae12ae95390`.
No research run proved independent below-six MAE. Repeatedly inspecting these
development labels cannot substitute for the missing authorized independent
physician-referenced cohort; neither pending source question has been answered.

Independent-evaluation preparation now retains a locked private candidate under
`locked-crop-head-20261005` on the research host: full shared-head candidate,
exact engine/crop source and aggregate development metrics. All four copied
assets were SHA256 verified; model/source/metrics/manifest/card are owner-read-only.
Manifest SHA256:
`b4d8c2b171c83925e2f2c4461b91c051fe354bc188f71888ff6605d2c37f7a00`.
The model SHA256 remains the independently integrity-checked full candidate
`2b457ad86f02e285f8e1c9bd168dee95ef3f48e1b2ae395ca46b5fd8f2315548`.
The shared head is retained rather than adding negligible-gain sex-specific
heads. A model card and empty protected independent-cohort CSV contract specify
subject linkage, independently reviewed skeletal-age references, source/rights,
duplicate/QC audit, complete failure denominators and a no-test-tuning rule.
The empty template is not a test cohort and contains no subject records.
Idempotent rerun verified the lock without replacing any existing file. This
preparation does not close the missing independent dataset or below-six target.

See [the owning module record](../modules/EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md)
for reference assumptions, physician review, PDF publication, focused guards and
the separately pending live source GUI gate. Model evaluation, report rendering,
packaging parity and native acceptance are separate evidence categories.

## Before/after consolidation and Razi baseline verification - 2026-10-05

### Scope and comparison contract

The initial comparator is the delivered incumbent checkpoint, not the historical
trial05 score. The selected research candidate combines the recovered trial05
checkpoint, contour-crop/CLAHE/sharpening preprocessing, arithmetic original/flip
TTA, and the shared regression head selected at epoch 26. The complete candidate
is locked privately as `locked-crop-head-20261005/model.pt`; SHA256 is
`2b457ad86f02e285f8e1c9bd168dee95ef3f48e1b2ae395ca46b5fd8f2315548`.
This is a comparison of complete pipelines; the total gain cannot be attributed
solely to newly trained weights or a single preprocessing change.

The comparison joins all 1425 development predictions by case key and asserts
unique keys, identical reference ages and identical sex labels. Initial predictions
come from `full/private_predictions.json`, variant `incumbent_letterbox`; selected
predictions come from `crop-head-research-20261005/private_predictions.json`.
Both files remain on the protected Linux research host. Candidate predictions
are clipped to 0-228 months, matching the documented output range. The initial
comparator uses its saved clipped `predicted_months` field. Reference ages within
0.0001 month of an integer are snapped only for age-bin assignment; errors use
the original reference values. No patient records are included in this document.

### Direct initial-to-selected results

MAE is mean absolute error against reference skeletal age, in months; lower is
better. Bands describe reference skeletal age, not chronological age. The source
annotations do not provide chronological age or authoritative subject grouping.

| Reference skeletal-age band | Development n | Initial incumbent MAE | Selected candidate MAE | MAE reduction, months |
|---|---:|---:|---:|---:|
| <1 year | 2 | 16.21487 | 11.96255 | 4.25232 |
| 1-<2 years | 11 | 5.47952 | 5.09190 | 0.38762 |
| 2-<3 years | 17 | 8.82568 | 6.97836 | 1.84732 |
| 3-<4 years | 26 | 6.54601 | 6.61738 | -0.07137 |
| 4-<5 years | 38 | 9.78433 | 7.97576 | 1.80858 |
| 5-<10 years | 394 | 8.36020 | 7.37630 | 0.98390 |
| 10-<15 years | 809 | 7.44228 | 6.38529 | 1.05699 |
| 15-<17 years | 89 | 6.38986 | 4.75372 | 1.63614 |
| 17-19 years | 39 | 6.83640 | 6.50795 | 0.32845 |
| All | 1425 | 7.67353 | 6.61232 | 1.06121 |

The pooled MAE reduction is 13.8295%. Predictions within +/-6 months increase
from 48.9825% to 58.0351%, a 9.0526 percentage-point gain. This coverage measure
is distinct from an average error below six months: neither metric says every
prediction is within six months.

| Sex | Development n | Initial MAE, months | Selected MAE, months | Initial within +/-6 months | Selected within +/-6 months |
|---|---:|---:|---:|---:|---:|
| Female | 652 | 8.05445 | 6.96814 | 45.2454% | 54.2945% |
| Male | 773 | 7.35224 | 6.31219 | 52.1345% | 61.1902% |

Direct comparison improves eight of nine age bands; 3-<4 years worsens slightly.
The <1-year estimate has only two images and cannot support a generalizable claim.
Other younger/older bands are also sparse. The substantial 5-<15-year support
accounts for most of the pooled improvement. Female error remains higher.

The earlier adapted-head table compares against the intermediate trial05 crop
parent, not the initial incumbent. Relative to that stronger intermediate parent,
head adaptation worsened 5-<10 and 17-19 years; relative to the initial delivered
incumbent, both bands improved. These statements use different comparators and
must not be conflated. The <1-year initial error is 16.21487 months; 14.86588 is
the intermediate crop-parent error, not the initial incumbent error.

### Completed stages and decisions

| Stage | Measured development MAE, months | Result and decision |
|---|---:|---|
| Recover serving checkpoint and full keyed baseline | 7.67353 | Incumbent letterbox, current two-view uncertainty-weighted TTA; retain as initial comparator. |
| Fixed incumbent square resize | 7.61373 | Small paired gain with exploratory interval including zero; not retained as sufficient improvement. |
| Adapt incumbent regression head | 7.40235 | Modest pooled gain, with subgroup regressions; superseded by stronger recovered checkpoint. |
| Recover trial05 with current letterbox / square preprocessing | 7.09320 / 6.93214 | Better existing owned checkpoint; distinct from the delivered incumbent. |
| Recover trial05 crop preprocessing | 6.79733 | Stronger intermediate parent; arithmetic-TTA matched baseline independently reproduced before head training. |
| Bounded ConvNeXt-Tiny training and low-LR follow-up | 8.03721 / 7.70615 | Inferior to crop parent; not retained. |
| Affine / monotone cross-fit calibration screens | 6.75204 / 6.78931 | Exploratory reuse of development cohort; no final calibration promoted. |
| Train shared crop regression head, 30 epochs | 6.61232 | Best useful retained improvement; epoch 26 selected, strict CPU checkpoint reload reproduced predictions. |
| Lower shared-head LR follow-up | 6.61069 | Approximately .00163-month gain; negligible, not retained. |
| Separate female/male head screen | 6.60289 | Approximately .00943-month gain, exploratory paired interval includes zero; added complexity not retained. |
| Unfreeze EVA final block, bounded fine-tuning | 6.66310 / 6.63844 | Both trained epochs worse than 6.61233 parent; patience stop, parent retained. |
| Lock selected candidate and independent-test contract | No independent result | Immutable asset hashes/model card and empty cohort template prepared; target remains unmet. |

Training/development inventories contain 12611/1425 images. All decoded images
were audited for exact pixel duplicates: none across the two cohorts. Near
duplicates and patient-level leakage remain unqualified. Data-source research
identified potential RHPE/Digital Hand Atlas follow-ups, but unresolved rights,
reference provenance and missing authorized independent cohort prevent qualifying
them. No new external image dataset was acquired for these experiments.

### Fresh verification of the actual Razi Eagle Eye baseline

Read-only checks completed at 2026-10-05 06:30:20 UTC (10:00:20 Asia/Tehran).
The host is `pacs`, `WIN-CTBQPS2GSM3`, not the separate Windows A100 host.
`AIPacsEagleEye` is Running with exactly one TCP 8002 listener. The service/process
chain selects `D:/Eagle Eye Server/revisions/20261004-secretary-help-ticket/source`
and `D:/Eagle Eye Server/config/server-20260930-echomind.json`. Only allowlisted
launch paths were inspected; credentials/configuration values were not displayed.

The active source adapter dispatches `bone-age` to `eagle_eye_engines.service.run`.
Resolving `bundle_root('bone-age')` in that revision's Python environment selects:

`D:/Eagle Eye Server/revisions/20261004-secretary-help-ticket/source/generated-files/eagle-eye/bone-age`

The manifest revision is
`b742802d3a41c10e8991667a00908d7b29bc573af453419eddc1c3a9db65f963`;
manifest file SHA256 is
`7ab827520041782fafb80ed052797f05df64dca0d4534c028a7a069d2af3124a`.
The runner imports this bundle's worker. The worker explicitly calls
`infer.load_model(root / 'weights/final_model.pth', torch.device('cpu'))`
for each job; it does not use the inference module's optional environment-selected
default weight path. The request launches an isolated worker process rather than
depending on an unverified older model cached in the server process.

| Active Razi bundle file | Actual SHA256 | Matches manifest and local initial bundle |
|---|---|---|
| `weights/final_model.pth` (350806623 bytes) | `4266a30b0f1aeeae2cdc65e49f4b5f5cd54f00137e4ad7a8606b2ae12ae95390` | Yes |
| `source/bone_age_inference.py` | `76bdec83a6dab07ddd3b8ca5ebe2f5f69065d4e5b847563f625b0619d17cf196` | Yes |
| `source/worker.py` | `ea9e6627a203d152b143939e973951de14a35f68ed15dfe186ff3e899bc75dba` | Yes |
| `runner.py` | `a5849c1f4c8d1ad7a774dc912f0cabd34c807a5a9ebea47e41b5da4bc138c6cd` | Yes |

All four files were hashed directly; size/mtime remained stable during the read.
The serving checkpoint hash also equals the research baseline receipt in
`full/summary.json`. Thus the initial 7.67353-month comparator uses exactly the
current Razi serving weight file, rather than merely an older Windows A100 copy.
No different newly improved checkpoint was found on this active serving route.

This confirms checkpoint identity and the configured serving code path at the
verification time. It does not turn the PNG development benchmark into measured
performance on Razi patients or establish DICOM/dependency end-to-end equivalence.
No patient inference, clinical file access, service restart, deployment or model
replacement was performed by this verification. Future server/model changes must
repeat this identity check before reusing the initial baseline claim.

### Current limits and next required evidence

The locked candidate is research-only. Overall MAE remains above six months;
several age bands and both sex groups remain above six months. Repeated candidate
selection on the same development cohort can favor that cohort. No independent
test was completed, and clinical adoption is not authorized by these results.
The next requirement is an authorized independent physician-referenced cohort,
with source rights, patient linkage, duplicate/near-duplicate audit, predefined
QC/failure accounting and fixed evaluation rules. No further blind development
tuning or a clinical promotion is implied by this document update.

## Owner-authorized replacement preparation and next improvement plan - 2026-10-05

The owner subsequently requested using the improved pipeline in place of the old
model while acknowledging the remaining performance limits. This authorizes
replacement work, not a claim of independent clinical qualification. The rollout
authorization need not be requested again. Inactive staging is now prepared;
the complete alternate bundle has been sealed and executed through the actual
server service function. Activation remains blocked by affected GUI acceptance.
See the [deployment safety record](../../generated-files/eagle-eye/bone-candidate-20261005/deploy-record-aipacs-2026-10-05.md).

### Concrete preparation and execution evidence

- `prepare_serving_candidate.py` verifies all four locked research assets, retains
  the exact owned architecture/constants/sex mapping/normalization, extracts the
  exact contour-crop preprocessing function and exports the full selected state.
  The serving wrapper uses arithmetic original/flip TTA and clips to 0-228 months.
  Simply replacing the old weights while keeping its letterbox/uncertainty TTA
  would not reproduce the selected candidate's measured performance.
- Exported weight SHA256:
  `4b75c68ca83d223a2694ac791edaf53371ea410119fc8978860c68964f4de903`.
  It differs from the locked full checkpoint container hash because only its
  state dictionary is serialized; every tensor was compared exactly after reload.
- Serving inference source SHA256:
  `bf9a0c7913949b35d62e1d3cbdad54cd7323bff401904817cce13aee06a0b3c9`.
- Nine private development images, one per skeletal-age band, reproduced selected
  predictions through the exported full CPU model: maximum difference .0000202656
  month, below .001-month tolerance. No images or case records were exported.
- Isolated Razi staging path: `D:/Eagle Eye Server/staging/bone-candidate-20261005`.
  Original worker/DICOM conversion/runner were retained for contract testing.
  The active dedicated runtime (`runtime/Scripts/python.exe`, manifest format 1)
  loaded the candidate strictly, verified finite parameters and deterministic
  outputs, rejected unknown sex and constant images, and completed a synthetic
  DICOM worker request with preserved review warning and image count.
- Linux Torch 2.11.0 and target Windows Torch 2.12.1+cpu synthetic predictions
  differed by at most .0000033975 month. Windows probe elapsed 24.58 seconds,
  including repeated inference and synthetic worker model reload; this is not
  routine clinical request latency or concurrency qualification.
- Prior weights/inference source/worker/runner/manifest were copied to a separate
  baseline backup and matched against the active hashes. Original runtime and
  current selected service bundle remain unchanged. No service/client restart,
  live patient inference or clinical activation was performed.
- Current existing Test Control Server client `ping` failed. Native source GUI
  request/result/PDF acceptance is pending human launch/login outside clinical
  work. Synthetic execution is reported separately from this missing live pass.
- Full inactive serving bundle is now sealed: 19585 directly verified assets,
  including copied runtime dependencies; revision
  `67d46506fd875e58eef2dab9e1f88a0e54f07015f70b58ec275180824fcbdbcb`,
  manifest SHA256
  `3429daa4beca276e366bba0a6943a955cabe043211d6ef61a52774022d26e6e1`.
  Actual installed `service.validate_bundle` and `service.run(..., root=STAGE,
  smoke=True)` completed via the staged bundle's own runtime/runner. Synthetic
  study identity, image count, returned engine revision and manifest-bound
  weights were verified; elapsed contract execution 31.14 seconds. Baseline
  active weight hash remained unchanged. No service route was switched.
- This contract probe exposed an existing server/local source difference: the
  installed service returns engine revision but not `checkpoint_sha256`.
  The probe checks the actual manifest-bound file rather than assuming that
  field exists. PDF code represents absent checkpoint provenance as unrecorded;
  it must not substitute an invented or old checkpoint hash. No live backend
  source patch is included in this model staging work.

### Will more images improve accuracy?

More unique, relevant, correctly referenced images can help; our experiments do
not establish a learning curve or guarantee a particular gain from a larger
dataset. Repeating/augmenting existing rare examples changes exposure but does
not add independent patients or solve wrong reference ages. Adding mostly
10-<15-year images can increase the total count while leaving rare-age and
sex-specific limitations unresolved. Unqualified external labels/domain mixing
can also reduce accuracy.

Current training support is 13 images below one year, 78 at 1-<2, 175 at 2-<3,
231 at 3-<4, 304 at 4-<5, 3487 at 5-<10, 7224 at 10-<15, 790 at 15-<17,
and 309 at 17-19 years. These are image counts, not verified unique-person counts.
Collection should address the rare bands and their sex cells, while also covering
the large 5-<10-year band whose selected MAE remains 7.38 months. Girls retain
higher pooled error. Coverage should include delayed/advanced maturation and the
target acquisition setting, not only normal healthy children.

Development-cohort arithmetic illustrates why collection cannot focus only on
rare young ages: the 94 images below five years contribute .47277 month to the
pooled MAE. If their errors hypothetically became zero while every other band's
errors stayed fixed, pooled MAE would still be 6.13955 months. The 1203 images at
5-<15 years are 84.4211% of this development cohort. Improving only those bands
would require about .72531 month average reduction to reach pooled 6.0, holding
other bands fixed. These are accounting scenarios, not predictions of training
benefit or a justification to ignore rare-age clinical performance; new young-age
examples can also change the learned function in other bands.

The [RSNA challenge report](https://pmc.ncbi.nlm.nih.gov/articles/PMC6358027/)
describes expert-curated reference data. A later
[external generalizability study](https://pubs.rsna.org/doi/10.1148/radiol.220505)
reported similar overall internal/external error while identifying age/sex/maturity
bias and clinically consequential errors. These studies support reviewing subgroup
and reference quality rather than relying on total dataset size or pooled MAE alone;
their metrics are not evidence for this candidate's clinical performance.

### Ordered improvement work and measurement contract

1. Keep an independent physician-referenced test cohort separate before selecting
   further experiments. Obtain authoritative patient/source linkage and usage
   rights; chronological age or this AI's own answer cannot substitute for skeletal
   age labels. Keep all identifiers/images on approved private infrastructure.
2. Review errors and reference disagreement by age/sex and maturity. Prefer blinded
   independent readers with adjudication of disagreements using a consistent
   reference method. Collect additional unique examples in underrepresented and
   high-error cells; do not attach automatic AI answers as new ground truth.
3. Measure a genuine data-size learning curve with prespecified patient-stratified
   nested training subsets (25%, 50%, 75%, 100%, then added data), fixed untouched
   test cohort, same architecture/preprocessing/optimizer budget and multiple
   seeds. All subset models must start from the same generic pretrained backbone,
   not this final bone-age checkpoint already trained on all existing images.
   A cached-head-only subset experiment would not estimate the benefit of more
   backbone training data and must not be presented as that learning curve.
4. Compare existing-only, existing-plus-new and capped balanced sampling with
   identical evaluation rules. Report MAE, bias, +/-6/12-month coverage, failures,
   age/sex/maturity support and patient-clustered uncertainty; preserve source/site
   external evaluation. Do not trade rare-band regressions for a lower pooled score
   without explicitly reporting and reviewing that tradeoff.
5. After label/data qualification, test anatomically targeted global/local hand
   features or a complementary ensemble as bounded alternatives. Existing blind
   fine-tuning, lower LR and separate sex heads already produced no useful further
   gain; do not restart those unchanged trials. No prediction correction may use
   the unknown true age band. A chronological-age prior requires separate review
   for delayed/advanced maturation and cannot hide clinically relevant discrepancy.

No fixed image count or guaranteed below-six result is asserted. Resource and
dataset access requirements must be established before the learning-curve runs.

## Razi Developer Eagle Eye activation receipt - 2026-10-05

The owner reiterated that the new complete pipeline must be operational for new
Bone Age requests on the Razi computer's Developer Eagle Eye Server. This followed
the explicit report that the GUI gate was still pending; it was treated as owner
direction to activate with that known gate outstanding. It does not count as a
GUI pass or independent model qualification. No further rollout authorization
was requested.

Target verified: `pacs` / `WIN-CTBQPS2GSM3`, owned SCM service `AIPacsEagleEye`,
source revision `20261004-secretary-help-ticket`, port 8002. Actual selected bundle:

`D:/Eagle Eye Server/revisions/20261004-secretary-help-ticket/source/generated-files/eagle-eye/bone-age`

Fresh complete baseline/candidate manifest validation and baseline-backup checks
preceded the change. Durable inference states and read-only EchoMind/Secretary
request inventories showed zero active requests; established 8002 connections
were also required absent. Only the owned Eagle Eye service was stopped. Four
assets were replaced using temporary files and atomic file replacement while
admissions were stopped: weight file, inference source, manifest, qualification.
Runtime dependency contents, other module weights, source backend files,
configuration and credentials were preserved.

| Activated asset | Identity |
|---|---|
| Engine revision | `67d46506fd875e58eef2dab9e1f88a0e54f07015f70b58ec275180824fcbdbcb` |
| Weight SHA256 | `4b75c68ca83d223a2694ac791edaf53371ea410119fc8978860c68964f4de903` |
| Inference source SHA256 | `bf9a0c7913949b35d62e1d3cbdad54cd7323bff401904817cce13aee06a0b3c9` |
| Manifest SHA256 | `3429daa4beca276e366bba0a6943a955cabe043211d6ef61a52774022d26e6e1` |

Actual installed `bundle_root('bone-age')` resolved to the live target. Strict
manifest validation and synthetic DICOM execution through `service.run` using
that selected root passed with the new engine revision before admissions resumed.
The service restarted successfully; exactly one 8002 listener and Running CRM
were verified. An authenticated mutual-TLS capabilities request to the actual
8002 endpoint returned HTTP 200 and demographic-confirmation capability 1.
No TLS verification bypass, configuration edit, credential exposure or patient
inference was used. New Bone Age jobs load this selected weight file and crop/
arithmetic-TTA source through the existing server-owned isolated worker.

Rollback remains available from the hash-verified prior tuple in
`D:/Eagle Eye Server/staging/bone-candidate-20261005/baseline-backup`; activation
helper restores the four prior assets and restarts only the owned service on
failure. No rollback was required. Aggregate activation and authenticated endpoint
receipts are copied under `generated-files/eagle-eye/bone-candidate-20261005`.

Automated/target-server execution: passed. Real affected source GUI/PDF workflow:
not performed, not a pass. Independent clinical accuracy test: not performed.
The 7.67353-to-6.61232 development comparison retains the prior checkpoint as its
historical initial comparator; it must not describe that checkpoint as currently
active after this activation. Further improvement/testing retains these limits.

## Rare-age improvement and regional explanation audit - 2026-10-05

### Current high-error groups and direction of error

All measurements below describe the selected/current pipeline on the same
development cohort; skeletal-age reference bands are not chronological-age bands.
Bias is prediction minus reference. Counts refer to images, not verified persons.

| Reference band | Training images | Development images | Current MAE, months | Current bias, months | Priority interpretation |
|---|---:|---:|---:|---:|---|
| <1 year | 13 | 2 | 11.96 | +11.96 | Highest observed error and weakest support; two images cannot establish stable performance. |
| 1-<2 years | 78 | 11 | 5.09 | -0.88 | Sparse but already below six on this sample; preserve rather than assume poor performance. |
| 2-<3 years | 175 | 17 | 6.98 | +6.08 | Rare, predominantly overestimated; review references, anatomy coverage and large residuals. |
| 3-<4 years | 231 | 26 | 6.62 | +3.78 | Near-six result with some overestimation; preserve uncertainty. |
| 4-<5 years | 304 | 38 | 7.98 | +6.26 | Strongest supported rare-young improvement target. |
| 5-<10 years | 3487 | 394 | 7.38 | +0.98 | High-error but not the sparsest band; substantial influence on pooled error. |
| 10-<15 years | 7224 | 809 | 6.39 | -0.72 | Near-six, plentiful; monitor for collateral regression. |
| 15-<17 years | 790 | 89 | 4.75 | -0.42 | Already comparatively strong. |
| 17-19 years | 309 | 39 | 6.51 | -4.51 | Sparse older band, predominantly underestimated. |

These patterns are compatible with several explanations, including imbalance,
reference disagreement and features inadequately representing maturation. They
do not establish a cause. The current regression head has an unrestricted linear
output, not a sigmoid; the final clip is 0-228 months. Avoid attributing the older
bias to sigmoid saturation. No correction can select a branch using unknown true
skeletal age at inference.

### Bounded rare-age/sex replay experiment

An additional CPU-only research screen used the verified deployed-parent crop
features and epoch-26 shared head, preserving backbone/FiLM/shared feature layers.
12611 training and 1425 development keys were checked unique and disjoint.
Sampling cells are nine reference-age bands crossed with sex; inverse-square-root
cell-frequency weights are clipped to .5-2.0. L1 loss, AdamW LR 3e-5, decay .01,
batch 128, six epochs for each of seeds 20261005/20261006 and a 120-second epoch
budget were fixed. No GPU allocation, new dataset or serving modification occurred.

Both seeds completed 594 updates. Initial screen elapsed 13.41 seconds. Baseline
MAE was reproduced within .0001 month. Strict selected-checkpoint reload passed.
Best trained pooled MAE was 6.63852/6.63348, worse than 6.61232 baseline; the
prespecified minimum-pooled-error selection therefore retained epoch zero for
both seeds. This is not a pooled improvement or a promoted replacement.

For the owner's rare-band question, these post-hoc illustrative epochs show a
consistent rare-band/bulk-band tradeoff. They were chosen after reading the
development results by lowest macro MAE across 2-<3, 3-<4, 4-<5 and 17-19 years.
The <1-year group is excluded from this diagnostic ranking because n=2 is unstable.
This diagnostic choice is not a prospectively validated selection criterion.

| Reference band | Current MAE | Replay seed 20261005, epoch 5 | Replay seed 20261006, epoch 3 |
|---|---:|---:|---:|
| <1 year | 11.96 | 11.90 | 11.19 |
| 1-<2 years | 5.09 | 4.71 | 5.06 |
| 2-<3 years | 6.98 | 6.01 | 5.74 |
| 3-<4 years | 6.62 | 6.30 | 6.25 |
| 4-<5 years | 7.98 | 6.98 | 6.82 |
| 5-<10 years | 7.38 | 7.54 | 7.61 |
| 10-<15 years | 6.39 | 6.50 | 6.51 |
| 15-<17 years | 4.75 | 4.81 | 4.76 |
| 17-19 years | 6.51 | 5.98 | 6.11 |
| All 1425 images | 6.61 | 6.66 | 6.68 |

Thus modest replay can move some sparse bands toward six months without adding
images, while slightly worsening common bands and pooled/sex MAE. This does not
prove independent benefit, solve <1-year scarcity or mean additional pictures are
unnecessary. The next controlled optimization should constrain common-band/sex
regressions, retain a current-model teacher or agreement penalty, and use reviewed
new young/older examples before broader fine-tuning. Do not merely increase epochs
or silently exchange the active model for these diagnostic candidates.

Private experiment paths on Linux are `rare-age-replay-20261005` and its exact-seed
replay retention directory `rare-age-replay-retained-20261005`. Model tensors and
keyed predictions remain private; aggregate history is `summary.json`. Seed replay
retains all six epoch heads per seed and asserts per-band/pooled metrics against
the original screen within 1e-5 month. This second run retains evidence, not a new
hyperparameter search. No independent cohort or patient grouping became available.

Retained illustrative checkpoints were independently strict-reloaded on CPU and
all 1425 outputs matched their saved keyed prediction tensors exactly. Seed
20261005 epoch 5 SHA256 is
`e2fc3e08fcb59a11831afaebfd710a67b9e1af3fd69a4b46f2709b3dafba168f`;
seed 20261006 epoch 3 SHA256 is
`7745b45f738abcb3b157fccb680504fc5f34bfc7cbda790b72dcaa330f18d6d6`.
The exact-seed retention rerun completed in 12.95 seconds and reproduced every
logged per-band/pooled epoch metric within 1e-5 month. Verification is recorded
privately in `retention-verification.json`; it does not validate clinical accuracy.

### Does the existing code mark why an age was predicted?

Scoped source audit covered the local Bone Age vendor/candidate/research helpers,
Linux `/home/gadmin/EnahancedBoneAge` Python sources to five directory levels, and
Windows `D:/Bone` / `D:/EnhancedBoneAge` Python sources to six levels, excluding
virtual environments/site-packages. No implemented Grad-CAM, Score-CAM, saliency,
attention-map display, Captum attribution or age-specific anatomical region
explanation was found in these reviewed sources. This is not an exhaustive search
of other repositories, notebooks, executables or historical archives.

Specific false positives:

- `main.py`, `main_v15.py`, `outputs_v15/main_v16.py`: "Explained Variance" is an
  aggregate regression statistic, not an image explanation.
- Linux/Windows `bone_age_eda.py:619`: heatmap is monthly dataset-count distribution,
  not anatomical activation on a hand radiograph.
- Windows packaged PIL `MspImagePlugin.py`: "attribution" is library text, unrelated
  to Bone Age interpretation.

The active EVA02 architecture has internal attention and a pooled image feature,
followed by sex conditioning and a single age regression head. It has no distinct
carpal/phalangeal/radius-ulna scoring heads. The existing worker returns aggregate
and per-image predicted ages, not region coordinates or heatmaps. Contour cropping
is an input-preparation operation; its rectangle does not explain the prediction.

The requested capability does exist in published approaches:
[gradient saliency for bone-age regression](https://www.nature.com/articles/s41598-021-90157-y)
investigates image sensitivity, while
[attention-guided region localization and label-distribution learning](https://pubmed.ncbi.nlm.nih.gov/34232898/)
learns discriminative hand/local regions and fuses their evidence. These are
external research methods, not capabilities already installed in this model.
No third-party weights/code/license acceptance or new clinical image export occurred.

The authors' [public code repository](https://github.com/chenchao666/Bone-Age-Assessment)
was also inspected. Its README explicitly describes generating attention/heatmaps,
cropping whole-hand and two local regions, and aggregating local patches. It lists
Python 3.6, TensorFlow 1.9 and Keras 2.1.6, so it is not a drop-in module for the
current PyTorch EVA02 runtime. Usage rights and weight/data readiness have not been
qualified; no code import or framework downgrade was performed.

### Appropriate explanation implementation boundary

First implement a separate, explicit research diagnostic for the actual deployed
model: input-gradient attribution or validated ViT-compatible Grad-CAM plus
occlusion checks. Explain the raw regression output with fixed known sex and eval
mode. The live `predict_one` is decorated with `torch.inference_mode()`; a separate
gradient-enabled path is required. Do not claim that enabling inference hooks alone
provides gradients or that ordinary last-layer CNN Grad-CAM directly applies to
this token-pooled transformer.

Any map must track the exact crop bounds, resizing and inverse flip of both TTA
views back to original image coordinates, and match study/series/SOP identity.
The current preprocessing function returns only the cropped RGB array; geometry
must be recorded explicitly before overlay publication. Compare maps under small
perturbations and check whether occluding highlighted versus control regions
changes the estimate consistently. Readers should review whether highlights
cover useful bone anatomy or background/text/soft tissue artifacts.

An attribution map shows model sensitivity, not proof that an anatomical region
matches a particular atlas age. It cannot itself assert "this epiphysis is 8 years"
without an independently trained/referenced anatomical scoring method. The saliency
study above also describes sensitivity outside informative bone structures,
supporting this distinction. Anatomical age-specific scores require region detection,
bone/atlas or TW-style stage labels and separate physician validation. Keep them
unavailable until such evidence exists. A diagnostic heatmap by itself does not
improve MAE; it may reveal failure mechanisms and guide data/model changes.

No explanation overlay, new report statement or further model replacement was
deployed by this investigation. Next work is a protected, geometry-verified
diagnostic pilot and common-band-constrained rare-age training, with independent
reference-data requirements still outstanding.

## Inclusive six-month endpoint screen - 2026-10-05

### Owner endpoint and current decision

The owner clarified that errors in either direction within six months are
acceptable for this engineering target; prioritize the fraction of predictions
with `abs(predicted skeletal age - reference skeletal age) <= 6 months`, then
the frequency and severity of errors beyond that interval. This owner target
does not establish clinical acceptability or guarantee accuracy for an individual
patient. Chronological age is not the reference skeletal-age label: do not clip
bone age to chronological age +/- six months, which would suppress actual advanced
or delayed skeletal maturation. Reception demographics remain separately confirmed.

Completed a bounded CPU-only development screen with the frozen deployed-parent
features: 36 fixed replay/blend evaluations (two seeds, six retained epochs,
raw-output blend weights 0.25/0.5/1.0) and 12 new head-training evaluations (two
seeds, six epochs). No candidate satisfied all predeclared aggregate/subgroup
guards. Keep the currently activated Razi model unchanged. No further replacement,
clinical request, report change or GUI workflow was performed by this screen.

### Method, safeguards and reproducibility

- Exact parent head SHA-256:
  `a081c7925b497a26c9a79dcb8496c7b29d791af1326ab6d558f7574f1855be50`.
- Same 12,611 training and 1,425 development cases, unique/disjoint cached case
  keys, sex labels and fixed crop/TTA features. No new or independent data.
- Blends combine predictions with fixed weights before clipping to 0..228 months;
  inference does not require the unknown reference age or choose a specialist
  using a true-age band. No development-label calibration or age-dependent oracle.
- New training: AdamW learning rate 1e-5, weight decay 0.01, batch 128,
  inverse-square-root age/sex sampling clipped 0.5..1.5. Loss in month units is
  `mean(softplus(abs(error)-6)) + 0.1*mean(abs(error))` plus a 0.1-weighted
  squared-output consistency penalty against the deployed parent for training
  reference ages 5..<15. The parent is evaluated with dropout disabled; the
  student trains with its existing dropout. This is a soft training constraint,
  not a guaranteed no-regression bound. Final loss is divided by 228 and gradients
  are clipped at norm 1. No backbone or production runtime was changed.
- Two CPU threads, no GPU allocation, 120-second cap; completed in 14.65 seconds.
- Selection guards: strictly more cases within six months; no increase in pooled
  MAE, mean excess beyond six months, or P95 absolute error; no reduction in
  within-six count in any of nine age bands or either sex. Zero of 48 evaluations
  passed. Subgroup count guards on very small bands are noisy; passing them would
  still not prove that no individual case became worse.
- Independently reloaded both illustrative heads with strict state-dict checking;
  interval saved raw predictions and case order reproduced exactly. Earlier replay
  output reconstruction differs only by float multiplication/averaging order,
  validated at absolute tolerance 0.00003 months. The nearest six-month threshold
  distance in either illustrative prediction set is >=0.00164 months, so this
  numerical tolerance cannot explain their threshold transitions.
- Scripts: `generated-files/bone-age-reference-research/screen_six_month_endpoint.py`
  and `verify_six_month_endpoint.py`. Trainer SHA-256:
  `5e546345aa34c234b6e863f3d0fb943e8ce890c8eb425ae91dca9eccc308a3aa`.
  First attempt stopped at a deliberately strict replay equality assertion before
  new training; retained failed directory for traceability. Corrected floating-point
  tolerance and reran in a new output directory; no deletion or serving mutation.

### Aggregate results and individual transitions

| Development endpoint | Deployed parent | Best observed six-month replay | Best observed six-month interval head |
|---|---:|---:|---:|
| Cases within +/-6 months | 827/1425 | 843/1425 | 834/1425 |
| Coverage | 58.04% | 59.16% | 58.53% |
| MAE, months | 6.6123 | 6.6385 | 6.6177 |
| P95 absolute error, months | 18.6059 | 18.4768 | 18.5383 |
| Mean excess beyond six months, months | 2.4740 | 2.4835 | 2.4663 |
| Previously outside, now within six | - | 47 | 19 |
| Previously within, now outside six | - | 31 | 12 |
| Net additional cases within six | - | 16 | 7 |

Replay example: seed 20261005 epoch 4, alpha 1.0. Interval example: seed 20261006
epoch 6. Both are illustrative post-screen development maxima, not qualified
selections. Replay loses coverage in 10..<15; interval loses coverage in 1..<2,
15..<17 and females. Paired case bootstrap with 2,000 resamples gives coverage
gain intervals of -0.14..+2.32 and -0.28..+1.26 percentage points, respectively;
both include zero. These are not selection-adjusted, not patient-grouped, and
not independent-test confidence statements. The 31/12 new threshold failures
make explicit why an aggregate gain cannot be described as preventing other errors.

For the deployed parent, 315 cases overestimate reference skeletal age by more
than six months and 283 underestimate by more than six months. Pooled signed bias
is only +0.033 months, but these opposite errors cancel in that mean. Young bands
2..<3 and 4..<5 have positive signed biases +6.08 and +6.26 months, whereas
17..19 has -4.51 months. A single global age offset is therefore unsupported.
Within +/-3 months is 441/1425 (30.95%); within +/-12 is 1207/1425 (84.70%).

Aggregate-only receipts are saved locally as
`generated-files/bone-age-reference-research/six-month-endpoint-summary-20261005.json`
and `six-month-endpoint-verification-20261005.json`. Private keyed predictions and
trained heads remain under
`/home/gadmin/bone-age-research/20261004-parity-pilot/six-month-endpoint-20261005-v2`;
no case identifiers or images were transferred into repository documentation.

### Next evidence required

Small changes to this frozen head can move cases across the threshold but have
not produced a reliable, no-subgroup-regression improvement. Avoid repeatedly
selecting more variants on this same development cohort and reporting the best
one as clinical progress. Next run should use a locked patient-grouped evaluation
cohort, audit reference-label disagreement and near-duplicate leakage, and obtain
authorized additional images for sparse ages. A subsequent region/label-distribution
model comparison must use the same locked splits and six-month/tail endpoints.
No external dataset terms were accepted and no new dataset was acquired here;
independent reference data and data-use authorization remain outstanding.

A future high-error warning requires separately calibrated, validated uncertainty
or out-of-distribution detection. Current model disagreement/dropout outputs do
not establish an individual six-month bound and must not be presented as one in
the PDF. Continue to report an estimate for physician review without promising
that every prediction falls within the owner target.

## Atlas-guided regional research update - 2026-10-05

Reviewed the owner's male/female standards PDFs, visually inspected all 58
embedded annotated atlas plates, and refreshed primary regional/ordinal and
atlas-text research. The PDFs are Gaskin et al.'s 2011 Oxford modernization of
GP standards, not a TW3 scoring manual. Recorded source hashes, page-specific
exemplar cues, variability and mature-hand limitations without copying atlas
images into training or production.

The full source comparison and bounded next experiment are in
[atlas and regional research dossier](BONE_AGE_ATLAS_REGIONAL_RESEARCH_2026-10-05.md).
Reference-only observations and draft annotation fields are in
`generated-files/bone-age-reference-research/bone-age-regional-cue-catalog-20261005.json`.
This catalog is not a deterministic age lookup, a trained regional predictor or
official TW3 stages. Missing morphology must remain unassessable.

Executed a new aggregate-only joint age/sex audit of the exact active-parent head
on the protected development cache. Pooled MAE and 827/1425 within-six count
reproduced. Male 2..<3 and 3..<4 cells have MAE 9.09/9.46 months, but N=10 each;
female 10..<15 has MAE 7.08 months (N=338); female 17..19 has MAE 14.57 months
but only N=8. These are priorities for reviewed regional failure analysis, not
validated population bias corrections or evidence of a particular causal bone.
All 18 cells are in
`generated-files/bone-age-reference-research/age-sex-endpoint-20261005.json`;
script `audit_age_sex_endpoint.py` ran with strict loading and aggregate/count
checks. Private case identities/features stayed on Linux.

Current decision: compare full-hand with higher-resolution local regions first,
then an independent ordinal/distribution-head ablation. An explicit anatomical
explanation needs reviewed per-bone morphology and verified inverse geometry;
the current pooled cache and inference-only API cannot supply it. The research
dossier specifies annotation, grouped splits, threshold/tail metrics, two-seed
budget, target CPU cost and stopping rules. No regional model has yet been
trained or deployed and no new clinical accuracy is claimed. The active Razi
model remains unchanged; independent reference data and appropriate use rights
are still needed before qualification.

### AcademicDirect TW2 resource supplied by owner (2026-10-05)

Retrieved the owner's HTTP link and audited its calculator structurally without
executing downloaded JavaScript. It is a June 2003 TW2 teaching/scoring page with
20 bones and sex-specific maturity tables. Terminal-stage sums equal 1,000 for
both sexes, but a radius-only terminal selection (all other bones omitted)
still returns 1.0 years: incomplete input is not rejected. The page therefore
informs the per-bone annotation design, not runtime scoring or reference labels.
Neither official-table clinical validation nor illustration reuse rights were
established. No website content entered training and no accuracy gain is claimed.
Details and source receipt: `BONE_AGE_ATLAS_REGIONAL_RESEARCH_2026-10-05.md` and
`generated-files/bone-age-reference-research/academicdirect-tw2-audit-20261005.json`.

### Regional integration design (2026-10-05)

Mapped the current global EVA02/GenderFiLM head to the existing server worker,
request contract, physician-review UI and deterministic PDF renderer. Chosen
first ablation: localized image features with zero-initialized residual fusion,
trained against existing global reference labels; chosen subsequent ablation:
masked, physician-observed ordinal per-bone supervision. Atlas text or tables
alone cannot supply missing stage truth. Preserve method-specific TW and current
GP-derived estimates separately. Record geometry, unknown masks, asset hashes
and review provenance before displaying anatomical evidence. No runtime edits.
Two public digiBONE segmentation assets completed staging with matching upstream
digests; safe checkpoint-global inspection completed. They have not yet been
loaded, validated on local images, trained or deployed. Detailed integration
contract and qualification metrics are in the existing atlas research dossier.

### Owner clarification: automatic atlas/case similarity (2026-10-05)

New physician annotation is not required for the requested research pathway.
The selected automatic shortlist is train-only reference-bank retrieval,
automatic regional localization plus retrieval/residual fusion, and age-supervised
ordinal/contrastive learning. Published epiphyseal retrieval and annotation-free
attention localization establish feasibility; neither establishes an accuracy
gain here. Global-age-derived local pseudo-stages are not observed stage truth.
Updated the atlas dossier with source evidence, leakage controls and the separate
roles of object detection and morphological matching. No new training or
accuracy result is represented by this design update.

### Executed two-stage automatic refinement pilot (2026-10-05)

Owner requested that the existing estimate remain stage one and that stage two
narrow/refine it. Implemented `two_stage_refinement.py` and executed it on Linux
CPU with two Torch threads using existing frozen original/flip pooled features.
The incumbent head is strictly loaded and baseline coverage reproduced (827).
Stage two performs sex-matched cosine retrieval from TRAIN only with a soft
age-neighborhood penalty based on stage-one predictions for query AND references.
No query reference age, chronological age or physician labels enters inference.
Soft narrowing allows recovery from an incorrect coarse prediction, unlike a
hard age window. This pilot is global-feature retrieval, not anatomical atlas
matching, and does not ingest publisher plates or change serving weights.

Configuration selected on a seeded 2,000-image training calibration subset against
the remaining training bank: neighborhood width 24 months, 32 neighbors, 0.05
similarity temperature and 0.5 fusion. Selection includes zero correction.
The encoder previously learned from all training images, so this calibration is
optimistic; subject grouping is unavailable. Development labels did not select
this configuration. Full training bank then queried the 1,425 development images.

Observed baseline -> refined: MAE 6.612319 -> 6.579407 months; inclusive within6
827 -> 839 (58.04% -> 58.88%); over6 315 -> 298; under6 283 -> 288; P95
18.605867 -> 18.286135; mean excess beyond6 2.473977 -> 2.467154 months.
34 previously failing cases corrected, 22 previously passing cases failed.
Subgroup coverage regressed in females 4-<5 (5->4), females 10-<15 (184->181)
and males 15-<17 (42->41). Therefore it does not meet the no-subgroup-regression
promotion guard; no deployment. Rare subgroups remain too small for firm claims.
Aggregate receipt saved locally as `two-stage-retrieval-20261005.json`; private
predictions and IDs remain protected on Linux. Actual execution exit0 and local
Python compilation pass; no runtime/GUI acceptance is claimed. Next substantive
comparison is automatic local-region features within the same two-stage contract.

### Actual radius/ulna localization training (2026-10-05)

Executed the automatic localization prerequisite using existing images and
public pinned Koitka ROI annotations, without new physician labeling. A scratch
four-block CNN trained on 239 usable source images for 30 CPU epochs; one record
was skipped. Optimizer update, finite losses and exact strict checkpoint reload
were verified. Corrected evaluation to 89 expert-annotated images after finding
that expert/nonexpert folders describe the same images; an initial mixed 178-row
readout is not valid image-level evidence. Corrected mean IoU: radius 0.2378,
ulna 0.1662; boxes with IoU >=0.5: 4/89 and 0/89 respectively. Training loss
decreased but held-out anatomical localization failed. This localizer is rejected
for age refinement; no skeletal-age improvement or per-bone atlas matching claim.
Do not interpret this compact failed comparator as failure of all detection
methods. Next required work is pretrained detection/keypoint adaptation and
annotation-definition alignment. Source, aggregate receipt, asset hashes and
limitations are recorded in the atlas dossier and research artifact directory.
No serving change, no patient image export and no GUI acceptance claim.

### Owner-directed three-zone alternative (2026-10-05)

The owner requested broader proximal/middle/distal focus instead of exact boxes.
Implemented `three_zone_refinement.py` as an isolated bounded research branch.
Preserves exact stage-one head predictions; extracts overlapping top 0-45%,
middle 25-75% and bottom 60-100% of the owned hand-preprocessed image, each resized
to 448. It assumes fingers-up/wrist-down; orientation/anatomical correspondence
is not yet validated. Three zones do not constitute individual bone detection.
Uses the frozen owned EVA02 encoder with sex conditioning to compute new regional
features, not the old pooled cache as a substitute. Uses 1,024 seeded training
images and all 1,425 development images; training-only calibration selects fusion
strength including zero. Soft predicted-age/sex-dependent regional weights are
literature-inspired hypotheses, not proven numerical clinical weights. Source
images and derived features stay on Linux, GPU budget capped at 15% of A100.
The existing clinical server/model is unchanged. Result receipt follows the run;
implementation/extraction alone is not evidence of improved skeletal-age accuracy.

Completed run: 252.1 seconds, peak allocated GPU memory 706,861,056 bytes. New
regional features extracted from real protected source images for 1,024 training
and 1,425 development images. Reference bank/calibration split 768/256; sex-matched
16-neighbor cosine retrieval with predicted-age soft penalty, then hypothetical
age/sex-dependent zone fusion. Training calibration chose 0.1 refinement strength;
development labels were not used to choose that strength. No extra physician
labels or neural optimizer updates in this frozen-feature retrieval experiment.

Baseline -> three-zone refinement: MAE 6.612319 -> 6.607483 months; within6
827 -> 830 /1,425 (58.04% -> 58.25%); over6 315 -> 312; under6 283 -> 283;
excess6 mean 2.473977 -> 2.466483 months; P95 18.605867 -> 18.699888 months.
10 cases newly within6, 7 newly outside. Female 10-<15 coverage fell 184 -> 182
of 338; other joint cells did not lose coverage. Thus the no-tail/no-subgroup
regression guard rejects promotion. Broad-zone extraction executes successfully,
but this specific refinement has no demonstrated useful accuracy gain.

Raw regional-only retrieval MAEs distal/middle/proximal were 6.887568/6.871586/
7.116511 months, with within6 counts 809/808/793. This is not a ranking of true
diagnostic value per bone: upright orientation is assumed, ROI boundaries are
heuristic, encoder is globally trained and sample is limited. A larger regional
training experiment would be a different hypothesis. Current result supports
feasibility of coarse spatial focus, not clinical superiority or exact anatomy.
Aggregate receipt: `generated-files/bone-age-reference-research/three-zone-20261005.json`.
Local compilation and actual remote execution exit0; clinical serving unchanged.

### Local morphology and boundary-emphasis paired training (2026-10-05)

Owner authorized an actual learning experiment targeting epiphyseal/physeal
detail. Implemented `train_local_morphology.py`: adapt the owned compact bone-age
ConvNeXt encoder and age head on real overlapping regional crops, instead of
using frozen pooled features alone. The incumbent EVA02 stage one is immutable.
Two branches share seed, starting checkpoint, 768 fit images, 256 training-only
calibration images, six epochs, horizontal flips and optimization. The edge
branch adds mild 5-pixel local-contrast emphasis to already enhanced crops;
the plain branch retains current enhancement. This isolates extra emphasis,
not all preprocessing or multi-region versus global training.

Both branches use local and fused global skeletal-age objectives plus a small
same-sex, age-affinity embedding objective (weight .01). Per-region targets are
global skeletal ages, not observed fusion stages, calcium density or epiphyseal
width ratios. Age/sex regional gates are the previous pilot's explicit hypotheses.
Full encoder updates use AdamW 1e-5, head/sex/projection 1e-4. Crop input is 224
pixels per region; this increases local sampling relative to fitting the whole
hand into 224, but is not a resolution ablation or superiority claim over EVA02
448. GPU memory is capped at 15%; wall-time budget 1,500 seconds. Train-only
calibration selects epoch and blend including zero before final development
evaluation. All 1,425 development images are retained; person grouping and
independent reference cohort are still unavailable.

The experiment compares end-to-end stage-one-plus-refinement predictions with
baseline within6 827/1,425 and MAE 6.612319 months. A lowered fit loss alone is
not success. Clinical weights/routes, physician workflow and PDFs are unchanged.
Aggregate results and strict reload checks are recorded after run completion.

Completed paired experiment: 253.98 seconds, six epochs and 576 optimizer steps
per variant. Checkpoint verification independently confirmed 180 changed encoder
tensors versus the starting owned checkpoint, strict state loading, exactly equal
synthetic reload outputs and finite predictions for all 1,425 development cases.
This is actual neural training, unlike the previous frozen-feature retrieval.

Train-calibrated selection chose epoch1 and ZERO fusion strength in BOTH branches.
Thus end-to-end results equal the incumbent: MAE 6.612319 months, within6 827/1,425;
no corrected/failed transitions and no deployment. Do not present identical
end-to-end metrics as a successfully improving morphology model. The selected
local predictor alone had MAE 9.686641 and within6 599/1,425 for plain crops;
extra boundary emphasis had MAE 10.007907 and within6 576/1,425. Their P95 values
were 27.195467 and 28.596083 months, versus incumbent 18.605867. This bounded
recipe does not improve accuracy; extra sharpening also did not rescue it.

This does not refute anatomy-aware learning: training was small, one-seed,
short-budget and on upright heuristic zones, with global age supervision rather
than observed morphology. The compact parent and crop distribution differ from
the production EVA02. Multiple objectives were bundled, so contrastive learning
and local training cannot individually be credited/blamed; only the paired extra
emphasis has a matched comparator. No physical calcium or width measurement
was validated. Next discriminating branch should use reliable local geometry
and a controlled resolution/representation ablation, with a larger authorized
training partition and training-only validation, rather than applying further
blind contrast boosts. No physician annotation task was requested or assigned.

Aggregate source/weights hashes, per-epoch calibration and subgroup metrics:
`generated-files/bone-age-reference-research/local-morphology-20261005.json`.
Execution verification:
`generated-files/bone-age-reference-research/local-morphology-verification-20261005.json`.
Private image tensors, predictions, case identities and trained weights remain
protected on Linux. Local Python compilation and remote training/verification
all exited0; this is research execution evidence, not clinical GUI acceptance.

### Continuous predicted-age-centered +/-12-month offset pilot (2026-10-05)

Owner clarified a dynamically centered interval, not fixed year bands. Implemented
and executed `train_dynamic_offset.py`: immutable stage-one prediction in exact
months plus image features and sex feeds a trainable 770->128->1 conditional
offset network, output `12*tanh(logit)` months. It learns signed continuous
reference-minus-stage-one residuals; targets are not clipped. No calendar-year
classes, chronological age, physician labels or query reference age enter inputs.
Correction is bounded +/-12, not final reference error; large initial errors
can remain. This pilot shares existing frozen pooled features rather than
training a new image encoder or distinct expert per moving window.

Fit/calibration split 10,611/2,000 within TRAIN; normalization fitted on fit only.
Two seeds, 20 epochs each, SmoothL1 beta3, AdamW 1e-4, zero-initialized correction
with epoch0 included. Calibration selected epochs1 and5. Actual optimizer updates,
finite outputs and exact strict checkpoint reload confirmed. Training stage-one
predictions are in-sample, so residual fitting/calibration is optimistic; proper
out-of-fold first-stage predictions remain required for a stronger experiment.

Development results: baseline within6 827/1,425 and MAE 6.612319; both seeds
within6 829. Seed20261005 MAE6.616697, P95 18.708872; seed20261006 MAE6.617262,
P95 18.663120 (baseline P95 18.605867). Paired newly-corrected/newly-failed counts
7/5 and10/8. Learned selected corrections were small: maximum absolute offsets
0.900643 and0.536584 months, despite permitted +/-12. Both candidates worsen
MAE and P95, so neither is promoted. No clinical serving change. This proves
execution of a continuous conditional correction, not a useful fine-grained
expert or sub-six-month accuracy. Aggregate receipt:
`generated-files/bone-age-reference-research/dynamic-offset-20261005.json`.
Private prediction/normalization/checkpoint artifacts remain on Linux. Compilation
and actual training exited0; no runtime/GUI acceptance is claimed.

### Published comparator execution: digiBONE full-hand (2026-10-05)

The requested comparison was executed, not merely proposed. Deeplasia's official
code was inspected at `b010cff8693f64712e65dfba2c817438f2da09f5`; no public
age-checkpoint acquisition URL was verified. Its service at
`05acf0364afae9c7f8345729c8b721b760945a29` explicitly states that its Docker
image excludes model weights. The official repository has no GitHub releases.
BoNet and i-pan/boneage advertise trained models, but a downloadable age-weight
asset was not verified in the inspected repository trees/readmes. These models
were not executed and no local accuracy is attributed to them.

An obtainable comparator was digiBONE, source commit
`e5d159cb8425c401d3d5e39fd3a91eb801d3147c`, official release
`boneage_prediction_models-v1.0`. The female and male full-hand weights matched
the publisher SHA256 digests respectively
`16eb0697f6f295fc23606610915a60e3cc503a151bf7c5c86d1e234bdceffa2a` and
`ea88051e3e8e787b968afbce35f3363aeb0d7d7d37dc97c24b70fb579ab0ab3d`.
Both loaded with `weights_only=True` and strict DenseNet161 state matching.
The upstream application was not executed. A reviewed isolated adapter preserved
RGB conversion, symmetric black square padding, PIL bilinear resize to 256 and
the actual upstream sex-specific calls: male `fhm=True` (0/1 normalization),
female default (0.1925/0.1435 normalization). Continuous predictions in months
were evaluated without GP rounding, post-hoc calibration or validation fitting.

This is the Indian-fine-tuned **full-hand component only**, not the complete SGP
pipeline, not the separate RSNA baseline release, and not a new regional training
experiment. Training overlap with our 1,425 development images is unverified.
Consequently this cannot establish independent generalization or disprove the
paper's segmental method. Domain differences and upstream preprocessing remain
possible causes of the poor result.

| Metric, same 1,425 development images | Owned active candidate | digiBONE full-hand |
|---|---:|---:|
| MAE, months | 6.612319 | 13.172616 |
| Absolute error <=6 months | 827 (58.04%) | 408 (28.63%) |
| Absolute error <=12 months | 84.70% | 55.02% |
| P95 absolute error, months | 18.605867 | 34.010501 |
| Signed bias, months | +0.03335 | -2.731082 |

Female comparator: n652, MAE11.073891, within6 224 (34.36%). Male comparator:
n773, MAE14.942821, within6 184 (23.80%). Paired transitions: 144 previously
outside six months become correct, but 563 previously correct become incorrect.
The owned baseline was reproduced from its locked head/features; labels and sex
arrays were checked for exact equality with the new prediction artifact.
All outputs were finite. Inference took66.69 seconds, peak CUDA allocation236.15
MiB, torch2.11.0+cu130, two CPU threads and a 15% per-process GPU cap. Download
was moved from slow Linux HTTP to Windows then SSH transfer; both final Linux
files were hash-verified. No shared service or production model changed.

Aggregate receipt:
`generated-files/bone-age-reference-research/digibone-full-hand-20261005.json`.
Reproducible adapters: `evaluate_digibone_full_hand.py` and
`compare_digibone_receipt.py` in the same directory. Private images, IDs and
predictions remain on Linux under `digibone-full-hand-20261005`; weight staging
is outside the repository. No clinical GUI acceptance is claimed for this
research-only run. Candidate rejected for replacement.

External-data access was also checked. USC's current DHA page was successfully
retrieved by HTTP and includes a direct 7GB Google Drive archive and a request
form; no archive was downloaded or request sent. RHPE's terms were successfully
retrieved through Drive's direct download endpoint (the web preview showed only
sign-in). They limit use to non-commercial research/education and include
responsibility, indemnity and employer-authorization clauses. Bulk acquisition
and commercial model incorporation were not performed. Dataset availability
alone does not demonstrate permission for the product or improved accuracy.

Sources: [digiBONE code and release](https://github.com/goellab/digiBONE),
[Deeplasia service requirements](https://github.com/bone2gene/deeplasia-service),
[USC DHA](https://ipilab.usc.edu/research/baaweb/),
[RHPE portal](https://bcv-uniandes.github.io/baar-wp/).

### Remaining-source usefulness review (2026-10-05)

The negative full-hand digiBONE comparator does not settle the remaining methods.
Ranked by the evidence gap they can address:

1. **PedVision: anatomical extraction candidate.** The full primary paper
   (doi10.1016/j.bspc.2025.108569) and official repository were inspected. Source
   commit `b28e38c0dcf4f74a17c0d2969265c73ce374caa3`, MIT code, README links
   SAM ViT-H, final-round ROI and instance-classifier weights. These links were
   found; downloaded/loadable assets were not established in this review.
   It segments19 tubular hand bones into metacarpal/proximal/middle/distal
   phalanx classes plus irrelevant instances, not20 TW2 maturity stages.
   It was assessed on552 selected images from RSNA/DHA. Its endpoint is
   segmentation quality, not bone-age MAE. It does not directly identify
   carpal maturity, distal radius/ulna stages or epiphyseal fusion. Training
   initialization includes point/class annotation and later human acceptance
   of masks; routine inference is automated. Thus 'manual-annotation-free'
   should not be represented as a training process with no human involvement.
   Best next check: isolated asset loading and an age/sex-stratified localization
   audit before training an anatomical age expert. Mask quality must precede
   age gains; no production integration or accuracy improvement is claimed.
2. **RHPE/BAAR: new population and anatomical landmarks.** Official portal lists
   6,279 images, two expert age readings and hand keypoint/bounding-box labels.
   This addresses site diversity and actual localization supervision. It does
   not provide observed TW maturity/fusion stages. Obtain authorized use and
   reconcile split manifests/count discrepancy before any incorporation.
   Preserve an untouched external partition rather than immediately using all
   new images for training. Non-commercial terms were retrieved previously.
3. **DHA: external generalization and reference disagreement audit.** The official
   USC page offers a7GB archive and request option. Two readings and demographic
   coverage can expose label variability/site shift. It is not a dedicated
   per-bone epiphyseal dataset. Audit actual rare-age/sex counts and duplicate
   linkage before claiming that it enriches the deficient age bands; counts
   differ across publications and must come from the obtained manifest.
4. **Deeplasia / BoNet+: method recipes with missing runnable age assets.**
   Multi-resolution global ensembles and anatomical local/global feature fusion
   remain hypotheses supported by published evaluations. They require faithful
   reproduction or obtainable qualified weights and matched evaluation. Our
   short regional pilots are not full reproductions of those methods. Published
   results must not be transferred to the active model or our development split.
5. **BoneAgeTW2: accessible but low-priority maturity comparator.** New preprint
   arXiv2607.23224v1, submitted25July2026, and author model card were inspected.
   Card exposes a72MB EfficientNet-B3/20-head checkpoint and reports end-to-end
   RUS MAE14.71months on its own1,262-image validation. Stage targets were
   constructed by Gaussian inversion from global RSNA age/sex rather than
   observed individual-bone maturation. Its reported stage agreement is against
   those derived labels, not proof of physician-level stage recognition or
   epiphyseal calcification measurement. It supplies no independent new images.
   Do not use its inferred stages as truth to train our correction or populate
   clinical report findings. Checkpoint was not executed here.

Preferred development direction: keep the qualified first stage, test a real
anatomical extractor, then train a sex- and continuous-age-conditioned local
expert using actual localized views. Fit first-stage residuals from out-of-fold
predictions; do not train against optimistic in-sample residuals or use query
reference age to select an expert at inference. Compare baseline, local-only
and fused variants on fixed partitions. Stop if localization fails or six-month
coverage gains are accompanied by material age/sex or tail regressions. This
ranking is a feasibility/relevance decision, not measured model improvement.

Sources: [PedVision primary paper](https://pure.eur.nl/ws/files/219409013/PedVision.pdf),
[PedVision official code/weight links](https://github.com/mohofar/PedVision),
[RHPE](https://bcv-uniandes.github.io/baar-wp/),
[DHA](https://ipilab.usc.edu/research/baaweb/),
[BoneAgeTW2 preprint](https://arxiv.org/abs/2607.23224),
[author checkpoint card](https://huggingface.co/maktub83/BoneAgeTW2).

### PedVision actual execution pilot (completed 2026-10-06 local time)

Source remains official commit `b28e38c0dcf4f74a17c0d2969265c73ce374caa3`.
All three public weights were acquired on authorized local infrastructure:

| Asset | Recorded SHA256 |
|---|---|
| Final ROI | `182170924467e7fe8ef32f8ff27e2334bc450257b5396435eaa446655ffd089c` |
| Final CLS | `124b3eff1740b000516d52dda645539671508d013a25ea1747007bfda90ddc6a` |
| SAM ViT-H | `a7bf3b02f3ebf1267aba913ff637d9a2d5c33d3173bb679e46d9f338c26f262e` |

These are observed provenance hashes, not publisher-supplied digest validation.
Google Drive large-file confirmation pages were distinguished from checkpoints.
Final ROI size25,341,483bytes and CLS size114,410,061bytes; four CLS byte ranges
were checked against Content-Range and assembled in order. Interrupted partial
downloads were not loaded. SAM download resumed successfully; its safe tensor
loading returned594 tensors. All task networks then passed `weights_only=True`
loading and strict state matching, without unnecessary ImageNet initialization.
The ROI also produced a finite synthetic256x256 output.

Dependencies were installed with `--target` under the protected experiment,
not into the existing environment: segmentation-models-pytorch0.3.3,
efficientnet-pytorch0.7.1, pretrainedmodels0.7.4 and segment-anything1.0.
Existing torch2.11.0+cu130, torchvision0.26.0, timm1.0.27 and skimage0.25.2
were used. The reviewed PedVision SAM generator differs from the PyPI generator
in three category-device corrections and docstrings; that upstream generator
was used. No upstream CLI, training UI, pickle loader or committed pyc executed.

The adapter preserves ROI sigmoid threshold0.5, image masking, SAM32-point grid,
IoU threshold0.86, stability0.92, one crop layer/downscale2, minimum area100,
upstream removal of larger fully covering instances, and three-channel classifier
input (image, individual mask, union mask). Resource adaptations: SAM FP16
autocast, point batch8, classifier CPU FP32 batch16, ROI CPU FP32, two torch
threads, one OpenCV thread and CUDA allocation cap15%. This is an exploratory
adaptation, not exact FP32 reproduction of the paper.

Eight development images were deterministically selected, one female and one
male within each reference-age band0..<60,60..<120,120..<180,180..<229months.
Age/sex are used for sampling/audit only, not SAM/ROI/CLS inference. All eight
processed successfully, with finite classifier logits and nonempty masks:

| Reference age, months | Female retained instances | Male retained instances |
|---|---:|---:|
| 0..<60 | 46 | 52 |
| 60..<120 | 50 | 59 |
| 120..<180 | 53 | 50 |
| 180..<229 | 42 | 40 |

All five numerical classifier outputs occurred in every sample. Annotation code
reserves0 for unassigned/background; the exact naming/order of classes1..4 is
not established by its interactive numeric labeler. Thus numerical class masks
must not be exposed as verified named bones. Excluding class0 yields22..35
instances; these are not guaranteed to correspond one-to-one with19 tubular
bones. Fragmentation, separate ossification centers and false regions remain
possible explanations, and have not been resolved by a ground-truth audit.
The method also does not label specific finger identity, TW maturity stages,
epiphyseal fusion or radius/ulna/carpal maturity.

Wall time130.85seconds including loading; individual image processing12.34..
20.81seconds; peak allocated CUDA4157.57MiB. Eight protected mask NPZ artifacts
were reloaded and their instance/class counts matched the aggregate receipt.
After completion GPU free memory returned to its original12,147MiB. Images,
identifiers, coordinates and masks stayed on Linux; no external clinical upload.
No age prediction, training, production change or clinical GUI acceptance occurred.

Conclusion: **execution feasible; segmentation accuracy and age benefit unmeasured**.
This run is not a Dice/IoU pass or evidence of a sub-six-month age estimator.
Before broad feature extraction or a correction model, establish class semantics
and a held-out anatomical quality check; then compare fixed first-stage baseline
with a trained local/fused candidate using out-of-fold residual targets. Preserve
the current serving model. Aggregate receipt:
`generated-files/bone-age-reference-research/pedvision-execution-20261006.json`.
Adapter and validated-range downloader are in the same directory. Protected
assets/output remain at Linux ROOT `pedvision-20261005` (folder naming retained
across the local midnight boundary).

### PedVision age-utility experiment: 2026-10-06

User requested actual diagnostic usefulness after the execution-only pilot.
An isolated bounded experiment was started with80 distinct development images:
32 fit,16 calibration and32 evaluation, stratified across four reference-age
bands and both sexes. The eight previously processed images are included only
in evaluation; their masks are reused without fitting to their age labels.
Additional choices use seed20261006, with disjoint index assertions and a
protected partition receipt. Original first-stage training images are not used
to fit this small second-stage correction, avoiding in-sample training residuals
from that original cohort. However, the first-stage checkpoint was previously
selected on development data; this remains a development experiment with prior
selection optimism and unavailable person-level linkage, not independent testing.

Hypothesis: numerical morphology from PedVision masks contains useful
information beyond the exact continuous first-stage age and sex. Thirty-seven
mask descriptors encode ROI fraction plus per-class count, union area, average
relative area/bounding dimensions/aspect/centroid and normalized perimeter.
Numeric classes1..4 are used consistently without assigning unverified bone names.
These descriptors do not claim to measure calcification or observed physeal fusion.

Three comparators: unchanged first-stage baseline, age/sex-only ridge correction,
and the same correction augmented by morphology. Both learned models fit only
the32 fit images. Normalization is fit-only; ridge strengths1/10/100 and blends
0/.25/.5/1 are selected on16 calibration images by within-six-month count then
MAE. Zero correction is eligible. Corrections are limited to+/-12months around
the exact first-stage result; output is clipped to the existing0..228 range.
This is closed-form ridge fitting with no image encoder updates or claimed SGD
training. Strict saved coefficient replay, paired transitions, MAE, six-month
coverage, signed bias, P95, age/sex results and a paired bootstrap MAE interval
are required before interpreting the completed result. Four cases per evaluation
age/sex cell are insufficient to establish subgroup safety or clinical qualification.

Adapter: `generated-files/bone-age-reference-research/pedvision_age_utility_pilot.py`.
Private masks/features/partitions/coefficients remain on Linux under
`pedvision-age-utility-20261006`. The same reviewed PedVision assets, FP16 SAM
adaptation and15% allocation cap are used; no source GUI or production change.
At start, the full-cohort cached baseline reproduced827/1,425 within six months.
Missing/failed anatomical extraction withholds the comparison rather than
fabricating measurements or silently reducing its denominator. Results pending
at experiment start; this paragraph is not an accuracy claim.

#### Completed age-utility result: rejected correction

All80 images produced finite37-dimensional morphology features with zero
extraction failures. Both ridge models were fitted and their saved coefficients
reloaded exactly. A synthetic evaluation-isolation guard also confirmed that
changing evaluation features cannot alter fit coefficients or calibration
selection. Actual replay verified disjoint image indices, fit-only normalization,
all aggregate metrics and the full-cohort first-stage827/1,425 receipt.
Patient-level independence remains unverified.

| Same32 evaluation images | First stage | Age/sex control | With morphology |
|---|---:|---:|---:|
| MAE, months | 6.171271 | 6.171271 | 9.291175 |
| Within6 months | 16 (50.00%) | 16 (50.00%) | 15 (46.875%) |
| Signed bias, months | +0.525649 | +0.525649 | +1.457619 |
| P95 absolute error, months | 14.700651 | 14.700655 | 20.718679 |

The age/sex control selected blend0, so its differences below1e-5 are only
float precision. Morphology selected alpha1/blend1 on calibration: within6
improved7/16 to9/16, but calibration MAE worsened7.913261 to9.721609 and P95
16.405027 to22.470774. This is an important failure of selecting primarily on a
small within6 count: it can favor a candidate despite larger overall/tail errors.
The existing clinical promotion rule requiring no material tail/subgroup harm
rejects this candidate; nothing was deployed. Do not retune using these32
evaluation labels and represent the result as a fresh test.

On evaluation, six formerly incorrect cases enter the six-month band and seven
formerly correct cases leave it. MAE increases3.119904months. The paired image
bootstrap95% interval for that increase is+0.846889..+5.477197months; the same
interval applies against the zero-blend control. This describes this small
development subset, not an independent population conclusion.

| Reference age, months | Sex | n | First-stage MAE | Morphology MAE | Within6 before/after |
|---|---|---:|---:|---:|---:|
| 0..<60 | Female | 4 | 5.47 | 5.92 | 2 / 3 |
| 0..<60 | Male | 4 | 9.18 | 8.69 | 1 / 2 |
| 60..<120 | Female | 4 | 9.26 | 10.48 | 0 / 2 |
| 60..<120 | Male | 4 | 13.45 | 13.47 | 1 / 2 |
| 120..<180 | Female | 4 | 2.21 | 10.22 | 3 / 1 |
| 120..<180 | Male | 4 | 2.38 | 8.26 | 3 / 2 |
| 180..<229 | Female | 4 | 3.77 | 11.45 | 2 / 1 |
| 180..<229 | Male | 4 | 3.64 | 5.84 | 4 / 2 |

The younger cells gain some six-month hits while older cells deteriorate, but
four cases per cell cannot establish that a young-age expert is beneficial.
Any age-gating experiment must be selected on calibration using predicted age
at inference and assessed on new held-out data. This observed pattern must not
be used to gate by reference age or to claim an improved clinical model.

Interpretation: the tested numerical mask-shape correction does not add useful
age accuracy under this fit/calibration recipe. It does not disprove image-based
learning from correctly localized epiphyses or joint regions. Possible causes
include the small fit/calibration sets, mask fragmentation/background confusion,
FOV/position-dependent descriptors and missing texture/physeal cues. They are
hypotheses, not demonstrated causes. PedVision's four tubular-bone groups also
do not cover the carpal or distal radius/ulna maturity cues. No named-bone,
calcification or TW stage recognition was established by this experiment.

Runtime825.25seconds excluding initial network loading; peak allocated CUDA
4158.21MiB. After completion free GPU memory returned to12,147MiB. No clinical
service, first-stage weights, source GUI or report template changed. The current
Razi model remains active. This was a bounded feasibility/utility experiment;
no further tuning is justified on these same evaluation cases.

### Single-output base-model adaptation started: 2026-10-06

Owner approved testing balanced exposure of rare ages and local image attention
inside one model, without the prior two-stage correction. This experiment uses
the active candidate's EVA02 backbone and locked regression head, not the weaker
compact comparator. It uses all12,611 existing training images; no new external
images or agreements were added. Frozen FP32 EVA02 features are extracted for
original and flipped views. Global CLS tokens stay FP32; spatial tokens are
averaged from32x32 to8x8 cells and cached FP16 in protected Linux storage.
This pooling is not identified individual bones or observed physeal stages.

The single network learns sex-conditioned spatial attention, positional weights
and a zero-initialized latent fusion gate before the same regression head. There
is one predicted age and no first-age input or external residual correction.
Existing GenderFiLM/shared normalization remain fixed, and the backbone remains
frozen for this first experiment. Attention and the age head genuinely train.
Any claim of full image-encoder fine-tuning would be incorrect.

Four fixed arms: uniform/global, balanced/global, uniform/attention and
balanced/attention. Within TRAIN, ten percent per age/sex cell is held for
checkpoint selection; seed20261006. Sex-specific age bands are0..<24,24..<60,
60..<120,120..<180,180..<204,204..<229months. Sampling weight is inverse square
root of fit-cell count, normalized and capped3; balanced arms sample with
replacement. This increases exposure, not the number of unique rare images.
Eight epochs plus incumbent epoch0, AdamW2e-5, batch64, SmoothL1 beta6months.
Checkpoint selection uses train-calibration MAE with within6 tie-break, never
development metrics. All1,425 development images are evaluated after selection.
Original pretrained backbone/head previously saw TRAIN, including this new
calibration subset; its selection is optimistic. Prior development reuse and
missing patient linkage also prevent independent clinical qualification.

Before fitting, global-token inference must reproduce827/1,425 within6 and
match the previous feature baseline to less than0.01months maximum discrepancy.
Real head updates, attention parameter updates, strict saved-state loading,
finite gradients/predictions and subgroup/paired results are required.
No production change, clinical GUI acceptance or new accuracy is claimed at start.

Preparation was initially serial. Observed GPU utilization58% and CPU-limited
processing motivated stopping only this owned research process and restarting
with four image-preparation threads and16-view forward batches, preserving
FP32 transforms and the15% allocation cap. Throughput approximately doubled
from768 images/79seconds to1536/81seconds. Clinical services were untouched.
Experiment source: `train_single_model_spatial_attention.py` under the existing
reference-research folder. Protected caches/checkpoints/partitions stay on Linux
under `single-model-attention-20261006`. Results pending at experiment start.

### Completed single-output adaptation and external coverage audit: 2026-10-06

All four arms completed eight epochs, with 11,355 fit images and 1,256
train-calibration images. Each arm performed 1,424 optimizer steps; head updates
were verified, and attention arms also updated spatial parameters and the gate.
All four nevertheless selected epoch0 by the preregistered calibration-MAE rule.
Selected attention gates are zero: the retained checkpoints reproduce the
incumbent, rather than demonstrating a benefit from learned attention.

| Selected arm | Development MAE months | Within6 /1425 | P95 months | Selected epoch |
|---|---:|---:|---:|---:|
| Uniform/global |6.612327|827|18.604778|0|
| Balanced/global |6.612327|827|18.604778|0|
| Uniform/attention |6.612327|827|18.604778|0|
| Balanced/attention |6.612327|827|18.604778|0|

Coverage is58.0351%; all selected arms correct zero new cases and lose zero
previously correct cases. Every age/sex subgroup remains unchanged. Baseline
subgroup MAE and within6 counts are recorded below; intervals are in months,
upper bound exclusive except the final bound229 covers228.

| Age band | Female n / MAE / within6 | Male n / MAE / within6 |
|---|---|---|
|0..<24|7 /7.43 /3|6 /4.66 /4|
|24..<60|37 /6.18 /21|44 /8.30 /14|
|60..<120|231 /6.98 /123|163 /7.94 /81|
|120..<180|338 /7.08 /184|471 /5.89 /309|
|180..<204|31 /4.51 /22|58 /4.88 /42|
|204..<229|8 /14.57 /1|31 /4.43 /23|

The sparse female204+ cell remains a priority, but its eight development cases
cannot establish a stable population error. Balanced sampling demonstrably
increased exposure: female0..<24 draws280 to883, male0..<24 draws384 to1218,
and female204+ draws328 to1011 across eight epochs. These are repeated draws,
not new images. Sampling replay accounted for11,318 distinct fit examples.

The initial maximum parity threshold0.01months stopped the run before fitting.
Diagnosis found batched FP32 extraction versus the earlier feature cache differed
by maximum0.023277months (about0.7days), mean0.002147months; aggregate MAE
changed by0.000009months and within6 classification count remained827.
The explicit tolerance was revised to0.03months, with MAE drift below0.001months
and unchanged within6 count. This numerical adjustment is not an accuracy gain.
Training after cached extraction took54.50seconds, peak allocated CUDA674.12MiB;
this excludes the earlier full-image extraction time and peak.

Independent script execution verified code/checkpoint hashes, strict state loads,
saved predictions and aggregate metrics for all four arms, zero-gate equivalence,
disjoint fit/calibration indices, finite outputs and deterministic sampler replay.
Paired bootstrap intervals for selected prediction differences are[0,0], since
the retained models are identical. No production change or clinical GUI pass.
This rejects this eight-epoch frozen-encoder adaptation, not full encoder
fine-tuning or anatomically supervised learning. The original head already saw
the new calibration subset; selection favors its in-sample performance, so a
fresh patient-separated training/validation design is needed for stronger claims.

Aggregate receipts under `generated-files/bone-age-reference-research/`:
`single-model-attention-20261006.json`,
`single-model-attention-verification-20261006.json`, and
`dha-age-coverage-20261006.json`. Trainer SHA256:
`0ea3537366142d7c3a8a39fd3c0ca3f1a3b7230a247a14a39702bc3a74e4bd8e`.
Private token caches, image keys, partitions and predictions remain on Linux.

The pinned [Deeplasia DHA metadata](https://github.com/aimi-bonn/Deeplasia/blob/b010cff8693f64712e65dfba2c817438f2da09f5/data/la_dha.csv)
contains1,384 image annotation rows, female688/male696, age0..228months.
Image and patient keys are unique within that metadata, but patient-key semantics,
actual image matching and cross-dataset duplication are not verified. Two zero-age
rows need inspection; the paper's1,383 external-image count is not reconciled.

| Age months | Current female / DHA rows | Current male / DHA rows |
|---|---:|---:|
|0..<24|38 /22|53 /32|
|24..<60|337 /79|373 /62|
|60..<120|2063 /157|1424 /166|
|120..<180|3014 /200|4210 /247|
|180..<204|281 /131|509 /62|
|204..<229|45 /99|264 /127|

DHA could therefore add meaningful coverage for older girls and infants if image
access, labels, licensing and deduplication pass intake. No DHA images were
downloaded or added to this training experiment; external images added=0.
Metadata SHA256:e41e21074cbe6308436a1050d303a03e3a03885725087b0b1179e2cf6a145881.
Protected metadata location: Linux `external-data-audit-20261006`; only aggregate
coverage is stored here. Repository metadata licensing does not establish separate
image usage rights. Next useful experiment is qualified rare-age image intake and
a genuinely held-out, patient-separated full/partial encoder fine-tune comparison,
rather than reporting repeated sparse-image draws as dataset expansion.

### DHA public archive intake: 2026-10-06

Following the owner's instruction to continue, the publisher-linked public Drive
archive was received into protected Linux research staging, without authentication,
a legal-agreement acceptance, a request-form submission or a clinical import.
Transfer:7,270,275,966bytes in195.51seconds; observed SHA256
`5247f77efcb8d34dcdb67e38a3b6b155f915455ba119540899a0239617660b8a`.
This is an observed transport fingerprint, not a publisher-signed checksum.
Storage was286GiB free before transfer. No GPU or clinical service was interrupted.

ZIP inventory contains2,781 file entries:1,390 DICOM,1,390 JPEG and one547-byte
readme. The earlier3,103-entry directory total includes322 directory entries.
The DICOM/JPEG counts do not represent2,780 independent subjects. Member paths
pass traversal checks. The readme describes anatomy/demographic folders, with no
explicit dataset license or permitted-use clauses; commercial/clinical reuse rights
remain unverified. Do not substitute Deeplasia's software license for image rights.

Crucially, none of the1,384 pinned Deeplasia annotation image filenames match an
archive JPEG/DICOM basename. Numeric-token and substring diagnostics also yield
zero unique image matches. No row-order, sex/age similarity or name-based join was
performed. This archive cannot yet be paired with that annotation release safely.
The metadata coverage table above therefore remains a candidate-release inventory,
not verified coverage of newly acquired images or an expanded training cohort.

Next required artifact: a publisher-provided original image-to-reference table or
an explicit verified conversion map from the archive IDs to the Deeplasia IDs.
It must include reference skeletal age, units/method, reader1/reader2 where
available, sex, person linkage and exclusions explaining1,390 versus1,384/1,383.
Chronological age or DICOM PatientAge must not silently become skeletal-age truth.
Usage scope must be clarified before model-training incorporation. No request or
email was sent on the owner's behalf. Training import remains zero.

Protected archive: Linux
`/home/gadmin/bone-age-research/20261004-parity-pilot/external-data-audit-20261006/dha-archive.bin`.
Aggregate receipts in `generated-files/bone-age-reference-research/`:
`dha-download-20261006.json` and `dha-archive-inventory-20261006.json`.
Reproducible sources: `probe_dha_access.py`, `download_dha_archive.py`,
`audit_dha_archive.py`, `diagnose_dha_linkage.py`, `qc_dha_pixels.py`.
Full CRC and independent JPEG decode checks were started; completed status must
be recorded separately. No new accuracy, eligibility or patient independence is
claimed from successful archive access.

Completed intake QC: all1,390 publisher JPEGs decode, have nonconstant grayscale
pixels and at least64pixels per side; zero decode failures and zero exact JPEG
decoded-pixel duplicates within DHA. The full ZIP CRC check passed for every
archive member, including DICOM. DICOM pixel decoding, cross-RSNA and near-duplicate
checks remain pending; CRC is not DICOM decode or anatomical quality acceptance.
Zero images were linked to the pinned annotation release. Therefore no skeletal
age range, rare-age image count or subgroup benefit is established for this archive.
Aggregate receipt: `dha-pixel-qc-20261006.json` in the reference-research folder.
State: research archive received and technically inspected; label-linkage/data-use
blocked for training. Current production model and accuracy remain unchanged.

### Original-ID label candidate found and audited: 2026-10-06

The owner requested a further search for original labels/mapping. All1,390 DICOM
headers load without error. No exact PatientID, StudyID or SOPInstanceUID match
to the pinned Deeplasia image keys was found. Metadata filenames uniformly use
the pattern `la_dha_#####`; they do not retain the original numeric filenames.
Stripping zero padding and deterministic filename MD5/SHA1/SHA256 checks found
no linkage. No identity inference by sex, age, names or row order was attempted.
Header field presence does not establish a skeletal-age reference; the standard
PatientAge values examined were empty, and private UN fields remain uninterpreted.

The legacy ipilab.org BAAweb.html query returns HTTP200 but an identical empty
table after a dataset-query POST. Four alternate publisher query endpoints failed
with connection errors or timeout in this environment. The authored
[DHA downloader](https://github.com/razorx89/digital-hand-atlas-downloader)
expects12-column publisher query records containing two reader values, but its
repository contains no saved original metadata CSV. The Deeplasia author's old
repository redirects to the same current tree, not an independent original map.
This failure is not proof that the publisher's reference data no longer exists.

A new [original-ID CSV candidate](https://github.com/mhdi002/bone-age-prediction/blob/26c111c3fc143a7800629f7ca85fbd514cab60d9/Digital-Hand-Atlas-Train.csv)
was found in authored bone-age training code. Frozen source commit:
`26c111c3fc143a7800629f7ca85fbd514cab60d9`; CSV SHA256:
`02699dd76317dd7a13e370e5a02e725ba7f36ca19b25ade7173457cedc9231c7`.
Columns: id, boneage, male, subjects, location. There are1,391 rows;
1,390 row IDs occur in the archive basename set, but this loose count includes
nonunique joins. Strict unique-basename/label parsing gives1,388 rows representing
1,387 distinct IDs, with three missing-or-ambiguous image rows. One sex value
disagrees with its matched publisher folder; duplicate IDs need adjudication.
Supplied location fields did not validate against archive paths/parent suffixes.

The1388 linked labels span1..242, with235 distinct integer values. They are not
simply folder-year or folder-year-times12 labels: only92 equal the folder's month
center. Among1,386 uniquely keyed DICOM comparisons,1,366 labels lie within12 of
the folder center, with mean absolute difference5.08369months. These are source
consistency checks, not prediction accuracy or proof that folder age is reference BA.

For1,383 valid birth/exam-date comparisons, candidate labels differ from calculated
chronological age by mean absolute4.71320months;96 lie within0.5month and185
within1month. Thus they are not simply identical to that date-derived chronology.
This does not prove expert skeletal-age provenance. Training code uses the CSV's
boneage column directly but does not document the two reader assessments, their
combination, units or CSV construction. No random-age assignment was identified
in the reviewed training scripts; absence there cannot establish label authenticity.

Result: a potentially useful linked numeric-label source was located, but reader
provenance, units, duplicate/sex corrections and image/data-use terms remain open.
No new data were trained and no model accuracy or clinical change is claimed.
Do not substitute the similarly named CSV for validated labels merely because
its IDs overlap. Raw CSV/header records stay protected on Linux.

Aggregate receipts in `generated-files/bone-age-reference-research/`:
`dha-candidate-source-20261006.json`,
`dha-candidate-label-validation-20261006.json`, and
`dha-candidate-age-semantics-20261006.json`.
Reproducible audit scripts are stored alongside them. A concrete, PHI-free
provenance request is prepared in `dha-label-provenance-request.md`. User approval
to send that public issue was requested; no message has been sent at this entry.
This is an external-message authorization boundary, not a required permission for
the completed read-only data investigation. Next step is confirmation from the
CSV author or publisher, followed by corrected linkage and duplicate audits.

### Owner-authorized provisional-label augmentation pilot started: 2026-10-06

The owner explicitly declined contacting the author and requested an empirical
test of whether the candidate dataset helps sparse ages. No external message will
be sent. Research-only use of these provisional labels is authorized; no clinical
import or commercial qualification is implied. Labels are assumed months for the
experiment and retain unverified provenance, rather than being promoted to truth.

Exclude duplicated CSV IDs, missing/ambiguous archive links, sex/folder conflicts,
nonfinite/zero/out-of-range labels outside0<age<=228, and cells with original
TRAIN counts600 or greater. Age boundaries remain24/60/120/180/204months, crossed
with sex. Exact decoded-grayscale SHA256 overlap is checked against all14,036
original train/development images; duplicate images are excluded. Near duplicates
and patient linkage remain unverified. Protected features/manifests stay on Linux
under `dha-augmentation-20261006`; no patient data are copied into the repository.

Protocol locked before evaluation: three seeds20261006/7/8, two matched arms,
six fixed epochs, AdamW2e-5, SmoothL1 beta6months, original/flip views, incumbent
regression-head initialization with frozen EVA02 encoder. Each update uses51
uniform existing training examples and13 source examples from matched rare
age/sex cells. Control uses existing rare images; augmentation uses new DHA rare
images. Both sample identical source-cell sequences and perform equal updates.
This distinguishes new-image effect from increased minority exposure. Original
train fit11,355/calibration1,256 partitions are preserved; calibration is logged
but not used for checkpoint selection. Fixed epoch6 prevents repeated-development
selection and avoids epoch0 selection on previously seen calibration examples.

Evaluate all1,425 existing development images, per-cell and combined sparse-cell
metrics; compare MAE, within6, bias and P95, plus paired image-bootstrap intervals.
Original development has been reused extensively; patient-independent confirmation
remains required for promotion. Three seed results are sensitivity checks, not
three independent clinical datasets. Require real gradients/parameter changes,
strict saved-state replay and finite outputs. Test result pending at this entry.
Preflight A100 free12,147MiB, disk279GiB; keep15% allocation cap and clinical
services untouched. No GPU service stop or clinical model change is authorized.

### Provisional DHA augmentation completed: 2026-10-06

No author/publisher message was sent, as explicitly directed by the owner.
The research dataset now contains479 retained candidate-labelled DHA images:

| Age months | Female current / new | Male current / new |
|---|---:|---:|
|0..<24|38 /29|53 /34|
|24..<60|337 /60|373 /60|
|180..<204|281 /70|509 /80|
|204..228|45 /66|264 /80|

Of1,391 candidate CSV rows,895 are outside sparse cells, four belong to duplicated
CSV IDs, one has missing/ambiguous linkage and12 are outside the model age range.
No additional sex conflict remains after duplicate exclusion. All479 retained
images decode and have finite features. Against14,036 existing decoded-grayscale
images, zero exact pixel duplicates were found. This does not close near-duplicate
or patient-linkage risk. Feature extraction/intake took130.19seconds and peak
allocated CUDA1,039.48MiB. Source/head caches and private manifests remain on Linux.

All six matched-exposure runs completed1,068 optimizer updates each. Regression
head parameters changed with finite gradients; frozen encoder was unchanged.
Fixed epoch6 checkpoints were used without development selection. Calibration
was monitored only. Independent strict reload reproduced every saved prediction,
all subgroup metrics and paired MAE bootstrap intervals exactly.

| Seed | Existing-rare control MAE / within6 | New-DHA MAE / within6 | DHA-minus-control MAE bootstrap95 |
|---|---|---|---|
|20261006|6.613215 /834|6.644375 /828|[-0.000925,0.062923]|
|20261007|6.619666 /841|6.642322 /835|[-0.009244,0.053018]|
|20261008|6.631637 /842|6.642483 /837|[-0.014194,0.035233]|

All MAEs/intervals are months; within6 denominator1,425. Incumbent MAE6.612319,
within6 827/1,425(58.0351%), P9518.605864months. New-DHA within6 is58.1053% to
58.7368%, versus matched control58.5263% to59.0877%. Adding DHA loses five or
six within6 cases relative to its corresponding control in every seed and gives
slightly higher overall MAE. Global intervals span zero: no meaningful superiority
from these data was demonstrated. Improvements over the untouched incumbent must
not be attributed to new data when the matched existing-data control does better.

Combined sparse development cells n222: incumbent MAE6.083736, within6 130.
Control MAE5.879..5.925, within6 134/136/139; DHA MAE5.930..6.115, within6
131/137/136. DHA-minus-control sparse MAE intervals are[0.03999,0.32663],
[-0.14797,0.19266],[-0.03921,0.22561]. The first shows worse sparse aggregate
performance in that seed; no consistent aggregate benefit is established.

Full-addition subgroup signals, three seeds:

| Group | n | Incumbent MAE | Control MAE range | DHA MAE range |
|---|---:|---:|---:|---:|
|Female0..<24|7|7.427|7.012..7.163|7.290..7.938|
|Male0..<24|6|4.657|4.411..4.451|4.502..4.586|
|Female24..<60|37|6.180|5.904..6.006|5.922..5.987|
|Male24..<60|44|8.298|7.558..7.768|7.340..7.705|
|Female180..<204|31|4.513|4.536..4.607|4.906..5.103|
|Male180..<204|58|4.882|4.886..4.921|4.925..5.127|
|Female204..228|8|14.570|14.231..14.391|13.156..13.578|
|Male204..228|31|4.427|4.339..4.407|4.579..5.194|

Some male24..<60 and female204+ signals motivated an exploratory follow-up, not
post-hoc clinical gating. Training replacement was restricted to those two cells,
using126 candidate images(60 male24..<60 plus66 female204+). All other rare-cell
draws use existing images; source-cell sequences and1,068 update counts match the
controls. Fixed six epochs and all three seeds were retained. Initial comparison
guard hit a CPU/CUDA device mismatch after the first fit; CPU mapping of the
initial state was corrected and the deterministic experiment rerun. No failed-run
checkpoint was evaluated or selected.

| Seed | Targeted DHA MAE / within6 | Targeted-minus-control MAE bootstrap95 |
|---|---|---|
|20261006|6.626876 /835|[-0.015679,0.043026]|
|20261007|6.631697 /836|[-0.015508,0.039928]|
|20261008|6.649171 /838|[-0.013927,0.047747]|

The targeted follow-up still offers no consistent overall superiority to the
matched controls. Female204+ MAE improves14.570 to12.684..13.021months and
within6 rises1/8 to3/8 in all seeds, but female180..<204 MAE worsens4.513 to
5.271..5.587 and within6 decreases22/31 to19..20/31. Male24..<60 MAE becomes
7.576..7.842, which is slightly worse than its corresponding existing-rare control.
These small, development-selected subgroup observations do not establish a
population benefit or sub-six-month accuracy. No targeted inference gate was
implemented; this remains one age output with research-only training changes.

Decision: retain the clinical incumbent. Adding this provisional DHA source to a
frozen-encoder regression head did not provide meaningful overall improvement,
even when restricted to apparently promising cells. The older-girl signal is a
hypothesis for future anatomically informed/partial-encoder adaptation, with
label quality and a genuinely independent cohort still required. More images
alone do not prove benefit; this experiment does not rule out better labels or
full/partial encoder fine-tuning. Clinical software data import and rollout remain
zero; no GUI acceptance is claimed for these standalone research runs.

Aggregate receipts in `generated-files/bone-age-reference-research/`:
`dha-augmentation-intake-20261006.json`, `dha-augmentation-20261006.json`,
`dha-augmentation-verification-20261006.json`,
`dha-targeted-augmentation-20261006.json`, `dha-targeted-verification-20261006.json`.
All nine checkpoints were independently replayed. Training after feature caching
took28.08seconds for the six full-addition/control runs and15.36seconds for the
three targeted runs; each training process peak allocated CUDA33.04MiB. These
figures exclude feature-extraction time/peak and do not describe clinical latency.
Full pilot source SHA256:
`8f22da3002e8144e702661828539e402f64f96c384362e2ea8c0b6810e26f86d`.
Targeted pilot source SHA256:
`0c72ea1873d6f851b8680448e5b4c994a5640b99dead0fa262140ad3b721a354`.
Protected feature-cache SHA256:
`4f702caf6575fe1f637fd844f7f604459877c49b43609e4a45812235299f0fde`.

### Consolidated owner decision: retain current Eagle Eye model, 2026-10-06

The owner requested a review of the entire completed research history and to
retain the current serving model if no practical, defensible replacement exists.
Review covered the initial recovered checkpoints/preprocessing, shared-head
adaptation, compact alternatives, sex-specific heads, calibration, actual final
EVA-block fine-tuning, six-month endpoint screens, kNN/regional/continuous-window
refinement, locator/morphology/atlas work, external comparator, spatial attention,
balancing, and full/targeted provisional DHA augmentation.

Conclusion: no later candidate has adequate evidence for replacing the current
epoch26 crop/shared-head model. Small aggregate improvements or subgroup gains
remain exploratory, sometimes worsen adjacent groups/tails, and do not establish
independent patient-level superiority. This is a decision based on available
evidence, not a claim that all possible architectures or training methods are
exhausted. The useful initial improvement is already retained: historical starting
pipeline MAE7.67353 to current6.61232months, reduction1.06121months(13.83%) on the
same1,425 development images. Within6 is827/1,425(58.04%); maximum per-case error
below6months was never achieved or established. Independent clinical qualification
and the real source-GUI acceptance limitation remain as recorded previously.

Fresh read-only Razi verification,2026-10-06: SCM `AIPacsEagleEye` Running;
exactly one TCP8002 listener, PID19056. Its command-line revision matches
`20261004-secretary-help-ticket` (only a boolean was reported, no raw command-line
or credential output). Live bundle files:

- `weights/final_model.pth` SHA256
  `4b75c68ca83d223a2694ac791edaf53371ea410119fc8978860c68964f4de903`.
- `source/bone_age_inference.py` SHA256
  `bf9a0c7913949b35d62e1d3cbdad54cd7323bff401904817cce13aee06a0b3c9`.

Both match the previously activated and evaluated model tuple. An initial probe
used the bundle-root inference path instead of its source subdirectory; that
read-only path error was corrected before the source-hash comparison. No asset
replacement, configuration change, service restart, new patient inference or
clinical deployment was performed. Existing jobs continue using the already
activated model; there is no need to redeploy the identical tuple. New research
variants remain separate and inactive. No author contact, age-based routing or
automatic online learning is introduced. Routine experimental changes end here
unless the owner requests a materially new data/evaluation approach.

Aggregate receipt: `generated-files/bone-age-reference-research/pedvision-age-utility-20261006.json`.
Replay verifier: `verify_pedvision_age_utility.py` in the same directory.
Experiment source SHA256:
`0e7ccadf07b8cb0844048f2a467fa82eafb3c728386f5db7dcc6f14afd08b20c`.
Private features, partitions, coefficients and replayed predictions remain on
Linux. Verification is code/data replay only; no runtime/GUI acceptance is claimed.
