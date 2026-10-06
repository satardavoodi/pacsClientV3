# B64: Native contextual detail matched experiment

Date: 2026-10-06. Completed: twelve fits across matched five/ten-epoch experiments.
Decision: reject the tested replacement; retain B50. No deployment.
Parent decision B62; B63 supplemental inference remains separate.

## 1. Objective and evidence identity

Hypothesis: native-source context384 improves reference-ROI Mass/AD/asymmetry-family
classification over context224, with local224 unchanged. Source shape/margin pretraining
is reused identically within seed; this is not a new multitask-supervision intervention.
Protected P scripts b64-stage.py and b64-train.py; Windows source staging under
D:/Enhanced Mammography/candidates/20261001-calcification/b64-context384-20261006;
Linux R/b64-native-context-training-20261006. Protocol hashes bind exact artifacts.

## 2. Cohort readiness and pre-fit amendment

Attempted original 1,270-ROI staging stopped on a missing native source. A bounded
source audit found117 missing images among1,150, affecting123 rows. No stem-matching
alternative exists under the audited original dataset root; this does not prove
absence across all disks/backups. Linux dataset inventory did not identify a VinDr
native copy. Cached224 pixels cannot regenerate genuine native384 detail.

Before fitting, amend to a common available-source cohort: exclude an entire study
if any original selected ROI source is missing. Retain1,147 rows: Mass834, AD79,
asymmetry family234; exclude63 studies. Both arms use exactly these rows and the
original seed-specific partition assignment. No physician corrections or unknown
negative labels imported. This is a different cohort from B50; compare freshly fitted
matched arms, not B64 accuracy directly against B50's52.12%.

Native source hash, geometry, polarity, normalization and fit224 input parity must
pass for all retained rows before training. Unavailable staging rows are NaN and must
never be indexed by fitting/evaluation. Eligible indices and original splits hashed.
Study grouping remains distinct from proven person linkage. No independent test used.

## 3. Configuration and telemetry contract

Seeds17/29/43, same verified B50 CBIS auxiliary encoder within each pair; same target
head initialization seed+991. ResNet18 local/context features; separate branch forwards
for both arms with frozen BN. AdamW head0.001/layer4 0.00001, decay0.01, batch8,
FP32, no augmentation or scheduler, five target epochs, final fixed checkpoint only.
Inverse-study row weights normalized within fitting split. No source retraining.
Changing target context resolution is the only intended paired intervention.

Discarded real synthetic update/reload at224+384 before fits. Monitor finite gradients,
actual parameter changes, BN invariance, comparable train/development metrics each
epoch, exact checkpoint reload, time and peak VRAM. Five epochs is a bounded pilot,
not a convergence claim. Four-hour total training cap, five-GiB process allocation cap;
fresh free-memory gate, no service interruption. Full environment lock not recorded.

## 4. Metric and selection contract

Mean seed macro-F1 primary; per-class recalls/confusions/log loss and paired study
bootstrap uncertainty. Predeclared retention: >=3 percentage-point macro-F1 gain,
Mass recall loss <=2 points, no AD/family recall decline. All conditions required.
Any improvement with interval spanning zero is provisional. No threshold rescue,
epoch selection from observed development results or independent accuracy claim.

## 5. Results and interpretation

All1,033 available native images staged;2,294 branch reconstructions exactly match
the previous224 tensors. Final range check initially rejected a floating-point
interpolation maximum1.0000003576; the documented B50 range tolerance1e-6 was restored
without clipping pixels or changing input-parity tolerance. The finalizer receipt
records this amendment. Original staging elapsed total was not recorded after this
terminal assertion; progress logs reached398.4seconds at image1,000.

Retained561 studies. Seed17/29/43 development rows224/208/226; corresponding AD support
12/20/14. All six actual five-epoch fits and synthetic/checkpoint guards completed.

| Five-epoch development metric | Matched224 | Native384 | Difference, percentage points |
|---|---:|---:|---:|
| Macro-F1 | 50.87% | 51.70% | +0.83 |
| Mass recall | 76.31% | 76.95% | +0.64 |
| AD recall | 23.10% | 25.32% | +2.22 |
| Asymmetry-family recall | 58.13% | 58.93% | +0.80 |

Gate fails: macro gain below3points. Study bootstrap macro difference95% interval
[-2.46,+3.96]points; all recall intervals also include zero. Bootstrap shares study
weights across seed partitions;1,994 valid replicates of2,000, excluding resamples
without all class supports. Seed-specific macro differences -1.01,+4.78,-1.27points
show inconsistent benefit. These are repeated development experiments.

Pre-extension decision: both arms still improve in fitting performance through epoch5,
and development behavior is not a stable plateau. Freeze one matched ten-epoch
extension for BOTH arms, same source initialization/labels/splits/optimizer, final
epoch10 only. Fresh fitting, not exact optimizer resume. No additional sweep or
post-hoc best-epoch choice. This extension tests budget sensitivity; the five-epoch
result remains recorded even if the extension is better. Separate protected directory
R/b64-native-context-10epoch-20261006 and script b64-train-10epoch.py.

### Completed ten-epoch extension

| Ten-epoch development metric | Matched224 | Native384 | Difference, percentage points |
|---|---:|---:|---:|
| Macro-F1 | 47.83% | 44.88% | -2.95 |
| Mass recall | 88.04% | 89.92% | +1.88 |
| AD recall | 13.65% | 11.98% | -1.67 |
| Asymmetry-family recall | 39.03% | 30.24% | -8.79 |

Gate fails again. Macro difference95% study-bootstrap interval[-6.30,+0.22]points;
family recall difference[-17.77,-0.91]points. All three seeds lose family recall.
Both ten-epoch arms are worse in macro-F1 than their corresponding five-epoch arms.
Training macro-F1 approaches100% while development deteriorates; consistent with
overfitting/majority preference, not evidence that simply adding epochs will fix typing.
This does not isolate all causes of the label/domain/generalization gap.

The first five epochs of every extension exactly reproduce the original paired run's
training/development metrics and objective. All twelve checkpoint reloads and update
guards passed. We did not pick a favorable intermediate epoch after seeing results.

## 6. Resources

Windows management/data host stages native pixels; Linux A100 trains. CPU deployment
latency is a separate gate. Existing GPU services remain running. Input transfer
stays within authorized infrastructure; no external image upload.
Five-epoch six-fit execution67.74seconds; peak allocated GPU633,117,696bytes. This
excludes input preparation/transfer and is not end-to-end serving latency.
Ten-epoch six-fit execution129.85seconds, same peak allocation. Fresh post-run GPU
free memory12,147MiB and utilization0%; processes exited successfully. No existing
service was stopped. Total fitting about198seconds, below the four-hour cap.

## 7. Decision and next action

Retain B50. Reject this native-context384 adaptation as a replacement at the tested
budgets. Preserve staged native detail for other controlled hypotheses, but do not
repeat the same resolution/epoch sweep or claim every high-resolution method fails.

Next bounded experiment is B62's independent compact representation challenge
(DINOv2-S), after exact-artifact rights/exposure and runtime checks. Keep an adequate
matched compact control, the same available-source cohort and unknown labels. A
frozen embedding probe is a low-cost first comparison, not a substitute for testing
the chosen model's adaptation. Reference-scope reconciliation continues separately;
missing native files and ambiguous physician fields are not invented training data.
No DINOv2 training/download occurred in B64. Do not expand to BI-RADS output yet.

## 8. Limitations and qualification

Available-source selection may introduce bias. Digital source references imperfect,
rare AD support limited, clinical feedback unresolved, and independent qualification
absent. No production model, clinical UI or accepted calcium branch changes.
