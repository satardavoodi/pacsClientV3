# B19 constrained-head training review

Recorded retrospectively on 2026-10-05 from immutable experiment receipts.
Format: [Breast reporting contract v1.0](../BREAST_AI_REPORTING_STANDARD.md).
Status: **evaluated and rejected**. This card does not start or modify a run.

## 1. Objective and evidence identity

Task: native mammographic point-candidate confirmation; reduce unwanted accepted points
without losing reference identities retained by the research comparator. This is not
malignancy classification or the original deployed Eagle Eye detector.
Technical owner: Breast AI research workstream. Clinical importance review: pending.
Trainer: float64 constrained optimization on Linux A100 host CPU, two threads; native
verification/inference on that host's GPU. Initialization: retained native512 head-only
candidate, with frozen FPN/Inception-v4 encoder/decoder and 128 native features.
Only 128 head weights plus bias were optimized. There was no new encoder training.

| Bound artifact | SHA256 |
|---|---|
| Starting checkpoint | `00392b28a3dc8a725a2657c810f413219df19f6fd2e0e76661891c5daed8e436` |
| Candidate checkpoint | `f969ec2d176fb96681319e5e311cc1106dd26b5b654ccaaa758b41a72252a3fd` |
| Corrected supervision manifest | `6a8276bed54510994d22bcb7bd1e436de908403eb63fe955f7189084953fc521` |
| Frozen candidate selection | `3113cc806870c5af57f671bc34d8e859ae0034656f0116a8cdda52a2eb305720` |
| Original optimization protocol | `ccd1dfd4daf60264711320d59e5a5a3f52628127a361b059e41643e47001291a` |
| Additive deployment-validation protocol | `c798152ac6c555f086b2493452501a1134a990f165e58d2915ecac0c269dc97b` |
| Development evaluation script | `ffc2ad391317716e8bff18de1a7f016474a385c164e8b3d248001486895bc433` |
| Development evaluation protocol | `ade5215ca5237ba7fb238be0d4d684d152b4c85dafd74f17139d43bdc12fc83d` |

Full optimizer-code/environment-lock hashes and exact library versions are **not verified
in this card**; retrieve the bound experiment directory before reproduction. Seeds are
not recorded here; the solver uses deterministic baseline initialization, not a reported
multi-seed study. A separately saved replay reproduced all 118 iterations after a validator
roundoff failure; this was not an additional hyperparameter trial or exact-resume claim.

## 2. Cohort readiness

| Role | Group support | Image/tile or point support | Coverage and limitations |
|---|---:|---|---|
| TRAIN positive anchors | 6 | 75 physician references; 63 raw assignments; 62 baseline-accepted constraints; 16 selected positive tiles | CC only; constraints protect selected identities, not every positive pattern |
| Fitting normal | 8 | 24 selected tiles; 126,904 eligible candidates | Source-balanced objective; selected tile population, not natural-prevalence screening |
| Unfitted TRAIN normal sentinels | 2 | 6 tiles; baseline 55 accepted outputs | Not fitted in B19 but previously inspected; not a pristine test |
| Development positive | 2 | 2 images, 68 references (61 and 7) | CC/Lorad; excluded from this fit but repeatedly exposed development groups |
| Planned development normal | 4 | 16 images | Not run for B19 because positive gate failed |

Patient/study identity beyond documented source/group linkage, age, density, site spectrum
and adequate independent sample size are **not established by this card**. Reference
standard: original physician dots with protected geometry; unknown tissue is excluded from
negative labeling. VinDr weak positive boxes do not enter this objective. Selected negative
group provenance maps to publisher BI-RADS 1 with documented version-crosswalk limitations.
Rights for commercial upstream-weight distribution remain unverified.

## 3. Training configuration and telemetry

| Field | Recorded value or applicability |
|---|---|
| Input/inference | Existing source-range/high-byte 8-bit mapping; native512 tiles, stride256, trim128 with original last-writer reconstruction; frozen feature contract |
| Negative objective | Equal mean over 8 sources of mean softplus(negative logit minus fixed cutoff logit) |
| Regularization | 0.01 times mean squared head displacement from starting head |
| Positive constraint | Each of 62 baseline-assigned candidate logits at least cutoff logit plus 0.0001 |
| Optimizer | SLSQP, analytic gradient and linear constraint Jacobian, float64, max200 iterations, ftol1e-9 |
| Batching/sampling | All eligible cached negatives, source-balanced; no stochastic batch/accumulation |
| LR/scheduler/AMP | Not applicable to this deterministic float64 constrained solver |
| Augmentation | None in this cached-feature optimization |
| Selection | Final feasible solution; no intermediate-iterate selection or threshold search |
| Actual optimization | 118 iterations / 119 evaluations; objective 0.03669621 to 0.000836523 |
| Gradients/numerics | Synthetic objective/gradient/feasibility checks, float64 roundoff bounds, float32 margin and actual native masks checked |
| Conventional epoch curves | Not applicable; optimizer trace preserved. No paired per-epoch validation-loss curve exists |
| Throughput/host peak RAM | Not recorded in this summary; do not infer from iteration count |

Numerical corrections preserved failed receipts: roundoff-scale feasibility error was
handled with bounded arithmetic allowance, still requiring strict actual score cutoff.
Float32 deployment required half the nominal optimization buffer. Native comparison used
the original grid-sampling contract plus exact native decision masks. These changes did
not rescue the later clinical-reference retention failure.

## 4. Metric and selection contract

Both arms: fixed cutoff `0.000316227766`, raw proposals unchanged, one-to-one matching
within 0.2 mm on reviewed support. Unknown positive-image regions are not scored as
verified negatives. Training gate: preserve all 62 baseline identities and reduce normal
burden; sentinel gate: total below55, neither group worse. Development gate: preserve
total/per-image reference retention. Evaluate normal16 only after passing positives.

No final independent test was used. Development access history is repeated; describe this
as a development check, not pristine internal or external testing. Population confidence
intervals are not estimated: 68 correlated points from only two positive groups cannot be
treated as 68 independent patients. Independent evaluation must use appropriate grouped
uncertainty after obtaining a suitable cohort. Missing inputs fail explicitly; this card
does not infer a population inference-failure rate from successful selected runs.

## 5. Training interpretation

| Observation | Evidence | Interpretation / competing explanation | Check and action |
|---|---|---|---|
| Training normal outputs collapse | 330 to7; all62 anchors preserved | Anchor retention is enforced, not proof of generalized learning | Run frozen native and positive development gates |
| Sentinel suppression succeeds | 55 to0 | Supports rejection on these selected normal tiles only | Do not promote without positives |
| Development retention fails | 54 to34,20lost/0gained | Scorer change harms true support; limited positive coverage and objective mismatch remain hypotheses | Reject candidate; no threshold rescue |
| Lost points were already localized | All20 had available proposals, at most0.15653mm from their reference | Proposal absence does not explain these20 losses; simple feature distances do not prove global domain shift | Retain comparator; use physician review and broader precise supervision |

## 6. Candidate comparison and resources

| Endpoint | Starting head-only | B19 constrained head | Scope |
|---|---:|---:|---|
| TRAIN retained identities | 62/75 | 62/75 | Enforced anchor property |
| Fitting-normal tile points | 330 | 7 | Output burden, not clinical specificity |
| Sentinel points | 55 | 0 | Previously exposed normal groups |
| Development points | 54/68 | 34/68 | Two positive groups; no population interval |
| Development per-image hits | 48/61;6/7 | 30/61;4/7 | 18 and2 losses |
| Important/rare-focus recall | Not yet adjudicated | Not yet adjudicated | Do not substitute all-point retention |
| Calibration, PPV/NPV, cluster FROC | Not established | Not established | Point burden is not adjudicated cluster FP |

Optimization was CPU-based; native fit verification took5.41s and sentinel verification
2.53s. Two-image development GPU inference took8.1282s with303,196,160 peak allocated GPU
bytes. These separate timings exclude full serving overhead and do not benchmark Razi CPU.
No total training GPU-hour claim or seed-variability estimate is made.

## 7. Decision and next experiment

Reject B19; retain starting checkpoint unchanged for research review. Normal16 expansion,
coefficient rescue and production replacement were not performed. The current next action
is physician adjudication of the retained candidate's14misses and unwanted marks, plus
validated broader typed-point data when available. No new fit is specified or launched by
this card. A subsequent run must freeze its hypothesis, comparison and compute/time cap
from that evidence; these values are pending, not silently copied from B19.

## 8. Sources, limitations and qualification

Evidence root P is defined in [current state](../BREAST_AI_DEVELOPMENT.md).
Read `CONSTRAINED_HEAD_TRAIN_SENTINEL_RESULTS_2026-10-05.md`,
`CONSTRAINED_HEAD_DECISION_ROUND_2026-10-05.md`,
`constrained-head-held-results-20261005.json`, and
`CONSTRAINED_REPRESENTATION_ATTRIBUTION_2026-10-05.md` there.
Original protocol binding and replay are recorded in
`constrained-head-readiness-20261005.json` and
`constrained-head-roundoff-replay-results-20261005.json`.
R directory: `constrained-head-slsqp200-20261005`, including original failures,
attempt2 replay, protocols, selection, native and sentinel receipts.

Reporting appraisal: task/reference/optimization/endpoint/failed outcome disclosed;
environment-lock completeness, patient linkage, representative population, independent
testing and uncertainty remain gaps. This is an engineering review guided by the skill
and reporting sources, not formal CLAIM/TRIPOD compliance or PROBAST low-risk assessment.
Code/numerical checks passed for the recorded experiment; development gate failed;
clinical acceptance, review-page GUI acceptance and deployment remain unproven.
