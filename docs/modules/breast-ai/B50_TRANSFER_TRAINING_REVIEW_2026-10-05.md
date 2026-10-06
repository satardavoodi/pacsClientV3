# B50: Actual two-source morphology transfer pilot

Date: 2026-10-05. Completed: 12 real fits and paired development analysis.
Research only, not a clinical qualification. Continues [B49](B49_TWO_DATASET_BALANCE_2026-10-05.md).

## Objective and task boundary

Compare VinDr-only local/context appearance learning with CBIS shape/margin auxiliary
pretraining, then test one bounded group-class weighting intervention. Three source
appearance labels: Mass, Architectural Distortion (AD), and FA/Asymmetry family.
This is reference-ROI typing, not autonomous detection, normal-tissue specificity,
malignancy classification or view-confirmed final terminology. Ambiguous/mixed and
Global Asymmetry labels are retained for review outside the primary task.
The source-annotation experiment does not replace pending clinical adjudication.

Protected research root `P`:
`C:/AI-PACS-Datasets/breast-review/point-review-20261003`.
Linux root `R`:
`/home/gadmin/Mammography/candidates/calcification-pilot-20261001`.
New inputs/results use `b50-vindr-20261005`, `b50-cbis-qc-20261005` and
`b50-transfer-20261005`, preserving prior experiments and production weights.

## Target cohort and partition verification

VinDr original TRAIN source hash remains
`59cae3a856026b8b5822ed545e5150efce43f8f2f8aca991ce69d1fd221e4cbc`.
Native file/header/box audit selects 1,270 ROIs / 624 studies / 1,150 images:
923 Mass rows, 87 AD rows and 260 FA/Asymmetry-family rows. Class study support
is 443, 48 and 166 respectively; class study counts overlap.
Exclusions: 20 Global Asymmetry rows, eight mixed-family rows, 20 out-of-bounds
rows and 71 rows with missing files (62 images). No original box was clipped to
make it pass. AD specifically has six mixed rows and two missing rows excluded.
103 selected ROIs retain suspicious-calcium coannotations; absence of a calcium
label is not used as negative truth. No normal reference cohort is introduced.

| Seed | Fitting rows / studies | Development rows / studies | Development Mass / AD / family |
|---|---|---|---|
| 17 | 1,022 / 502 | 248 / 122 | 197 / 16 / 35 |
| 29 | 1,044 / 501 | 226 / 123 | 170 / 20 / 36 |
| 43 | 1,014 / 501 | 256 / 123 | 188 / 16 / 52 |

Saved before decoding: first five-fold StratifiedGroupKFold split per seed. Primary
independent check verified no study/image crossing and exact row partition coverage.
Private rows hash: `f6182604b484542939f85255a41d52a9af887e117a7b84d73dcdb3a114c01a0b`.
Splits hash: `924228bd4d7f4c794a572912593ddb991a45d61695ee62229247fe4441769303`.
VinDr study IDs do not prove patient independence. Repeated development splits
overlap and earlier project exposure remains; no pooling as independent patients.
AD support is small and primarily density C; density-A AD is unsupported.

## Actual input readiness

VinDr staging decoded all 1,150 selected images with no failure, producing
`(1270,2,1,224,224)` float32 tensors in 552.10 seconds. Source bindings and
serialization were verified across hosts. All 1,183 rows shared with B45 retain
exact local pixel and source-hash parity; 87 AD rows are new. No local ROI was
clipped; 379 expanded context crops reached the source image boundary. Maximum
1.0000004768 is float interpolation roundoff within the declared 1e-6 tolerance,
not repaired by new clipping. Nine local/context pairs passed visual input sanity,
not diagnostic adjudication. Replicated-border stripes remain a potential shortcut.

CBIS all 1,092 nonreserved standard-shape candidate masks were decoded and checked:
1,027 pass; **65 mask/full geometry mismatches are excluded**, not resized into
assumed alignment. A further 12 rows / six people with historical nontraining
membership are reserved. Actual staged source support: **1,015 ROIs / 553 people /
958 full images**, four original shape and five original margin targets known.
Candidate masks are lossy JPEG region references, not verified fine contours.
All candidate full files had byte/hash/header checks; full pixel decoding applies
to staged images, not a claim that every reserved full image was decoded.
Source QC/staging took 726.12 seconds. Eighteen sampled source crops were visually
inspected for input sanity; varying brightness, padding and one radiopaque marker
remain potential confounders. No input change was made after inspection.
148/1,015 expanded CBIS context crops reach image boundaries; minimum retained
requested context area is 56.30%, median 100%. All local regions remain contained.

Shape positive token counts (round/oval/lobulated/irregular): 118/287/285/335;
margin counts (circumscribed/microlobulated/obscured/ill-defined/spiculated):
306/104/187/273/219. Multi-token rows mean these are not exclusive class counts.
Preserved historical partition provenance: 980 previously unassigned TRAIN rows
and 35 historical fitting rows. Publisher-test and historical nontraining reserves
are excluded from source fitting. Complete prior use outside inspected manifests
and cross-source pixel-level deduplication are not proven.

Target NPZ SHA256: `57ff3973ae806953e3848d6b3509284a41dd25393b34243a1a555eb7e82f3712`.
Source NPZ SHA256: `fb2e9211ad08a57477d7b5ce8abce97eacb4dd23ec107e908c74005af3d8bd8f`.
CBIS normalizes JPEG pixels including image background while VinDr excludes defined
DICOM padding; domain/photometry equivalence is not assumed. Downsampling to 224
may lose fine AD structure. This is a compact feasibility experiment.

## Prespecified training comparison

Shared ResNet18 initialized from the existing ImageNet checkpoint; local ROI and
2x surrounding context each fit to 224 with aspect preservation and replicate padding.
Their shared-encoder features concatenate to 1,024 values. Layer4 and heads train;
earlier blocks and BatchNorm running statistics remain frozen. No augmentation.
All target arms use the same split, initial target head, batch order and five final
epochs; no development-based checkpoint selection. Five epochs is a bounded pilot,
not a convergence claim. AdamW: head LR 0.001, layer4 LR 0.00001, decay 0.01,
batch eight local/context pairs, float32, two CPU threads, 3 GiB GPU allocation cap,
one-hour training cap. Fresh GPU availability must pass before fitting.

Arms: target-only; five CBIS auxiliary epochs then target adaptation; the same
pretrained encoder then weighted target adaptation. CBIS uses original four shape
and five margin tokens, including legacy MICROLOBULATED, with known-target masks.
Its region masks derive/QC crops, not a segmentation decoder. No modern clinical
AD labels are invented from CBIS descriptors. Auxiliary heads are discarded.

Loss gives equal total base weight to each fitting group. The weighted arm adds
fitting-only square-root inverse class-group factors capped at three, then normalizes
mean row weight. This intentionally changes group totals by label; no simultaneous
weighted sampling is added. Additional source compute is counted separately.
Transfer versus target-only is not a total-compute-matched comparison.

## Verification and interpretation contract

Verify source/target receipt hashes, row order, known masks, actual gradient updates,
intended parameter changes, unchanged BatchNorm buffers and checkpoint reload parity.
Record per-epoch objective and comparable unaugmented fitting metrics, final
development confusion, class precision/recall/AP, log loss and multiclass Brier.
Undefined precision is null when no positives are predicted; macro F1 uses zero
for unpredicted classes. Preserve failures and excluded counts.

Primary prepared a separate paired study bootstrap with 2,000 draws per comparison
and seed. Synthetic guards cover perfect prediction, majority collapse, absent
support and identical paired predictions. Case-sampling intervals are exploratory
development uncertainty, separate from seed variation and clinical qualification.

## Completed fits and results

All 12 fits completed with exit code zero: three auxiliary source fits and nine
target fits. 7,695 successful optimizer updates; all intended layer4/head parameter
delta, unchanged BatchNorm and exact checkpoint-reload probability guards passed.
Initial target heads match within each seed. Receipt/row-order/known-mask checks
passed before fitting. PyTorch 2.11.0+cu130, NumPy 2.2.6 on Linux A100.

Arithmetic means across the three repeated development splits, percentages except
log loss. These are not pooled independent patient estimates.

| Arm | Macro F1 | Mass recall | AD recall | Family recall | Fitting macro F1 | Development log loss |
|---|---:|---:|---:|---:|---:|---:|
| Target-only | 46.49 | 84.39 | 10.42 | 46.86 | 86.25 | 0.6955 |
| CBIS transfer | 52.12 | 84.03 | 22.50 | 50.30 | 90.29 | 0.6814 |
| Transfer plus weights | 52.23 | 78.34 | 29.17 | 52.48 | 91.68 | 0.7058 |

Transfer increases macro F1 by 5.63 percentage points (not 5.63% relative), AD recall
by 12.08 points, family recall by 3.44 points; Mass recall changes by -0.37 points.
Mass precision rises from 83.79% to 85.56%; mean AD average precision rises from
31.72% to 46.59%. These are source-ROI typing measures, not normal-study specificity.
The apparent small average Mass loss masks a gain in seed17 and losses in29/43.

| Seed | Target-only / transfer macro F1 | Correct AD: target-only / transfer / weighted | AD support |
|---|---|---|---:|
| 17 | 47.10 / 50.91 | 3 / 4 / 4 | 16 |
| 29 | 39.69 / 43.95 | 0 / 1 / 5 | 20 |
| 43 | 52.68 / 61.50 | 2 / 6 / 6 | 16 |

AD false positive labels for target-only/transfer/weighted are 7/7/17 in seed17,
0/0/1 in seed29 and 1/4/9 in seed43. In seed29 the transfer's 100% AD precision
means just one correct AD prediction, not strong clinical performance. Target-only
has undefined AD precision there because it predicts none. Preserve these counts
rather than averaging undefined precision into an apparently robust number.

The weighted arm adds only 0.11 macro-F1 points over transfer but loses 5.69 Mass
recall points. Its seed17 macro F1 is below the target-only control. It is not
selected as the preferred tradeoff. This supports limiting automatic rebalancing,
not a conclusion that every future weighting strategy must fail.

Paired study-bootstrap 95% intervals for transfer-minus-control macro F1, in points:
seed17 [-1.13, 9.70], seed29 [-1.18, 11.18], seed43 [-1.67, 20.35]. Each includes
zero. Improvement direction is consistent across seeds but uncertainty remains
large; repeated exposed development comparisons do not establish independent gain.
One seed43 resample has no AD and is explicitly invalid for its AD-recall interval.
No thresholds were tuned, and probabilities were not calibrated.

## Training interpretation, resources and decision

The transfer hypothesis has an encouraging measured signal; retain unweighted
CBIS transfer as a research candidate. Do not deploy or call it clinically adequate:
AD recall is still low, fitting/development gaps remain large, mixed cases and
normal controls are absent, and clinical label adjudication remains pending.
The short run does not prove that more epochs will improve this gap. Architectural
Distortion and spiculated Mass need targeted error review, not just further oversampling.

Training/evaluation/checkpoint reload total: 93.54 seconds, peak allocated GPU
605,842,432 bytes (about 578 MiB). Target fits total 67.70 seconds; extra CBIS fits
22.19 seconds; the remainder covers guards/overhead. Separate input staging times
above exclude neither their own decode nor compression, but are not GPU-training
or full-study Razi CPU inference latency. No service was interrupted.

Next priority: preserve these matched predictions, review missed AD and AD-versus-
spiculated-Mass confusions with full-resolution local/context and companion views,
then test one input/context improvement against this locked candidate. Padding,
224-resolution detail loss and source photometry are explicit hypotheses to resolve;
do not silently combine their changes or rescue this result with test-set tuning.
If transfer remains useful after reference review, a compute-matched target-only
control is required to isolate extra updates from source-supervision benefit.
Full-image localization/normal false-positive evaluation remains a separate gate.

## Reproducibility and qualification

Primary artifacts: `P/b50-transfer-20261005/{protocol.json,results.json,summary.json,
predictions-private.json,paired-bootstrap.json,synthetic-guard.json,training.log}`.
Per-seed fitting weights/group counts/head hashes are in `split-17.json`,
`split-29.json`, and `split-43.json`. Checkpoints remain in the corresponding R
directory; none replaces the incumbent. Source/target readiness and private
geometry/source bindings live in their separate b50 directories.

Results SHA256: `bf86c344f44850d2ea8d49aba91bda5b432031a2979e6bb39aad821d737672d6`.
Trainer SHA256: `78fe16bebf4a6e23149c019621ef99516edacf549a3d3fbf3358b687b9204118`.
Prepared bootstrap script: `P/b50-paired-bootstrap-20261005.py`.
Actual code/data/update/reload checks passed; sampled input sanity is not physician
acceptance. No runtime UI changed, no live GUI acceptance or production deployment
is claimed. No independent clinical evaluation or optimized CPU latency measured.
