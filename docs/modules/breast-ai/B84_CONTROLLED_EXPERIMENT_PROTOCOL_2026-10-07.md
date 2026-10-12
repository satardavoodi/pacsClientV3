# B84: Controlled experiments for presence, appearance and suspicion

Date: 2026-10-07. Status: protocol and feasibility review; not a completed data
audit, executable evaluation harness, training run or clinical validation.
Parent decisions: B82 data readiness and B83 owner-approved separate outputs and
calcium/tissue branches. This protocol operationalizes those decisions.

## Evidence and readiness

Reviewed B72, B76, B82, B83 and the repository evaluation entry points. B72 has
272 reference ROIs, only18 AD ROIs from10 studies, and no normal-reference class.
B76 provides full-image detection/matching evidence but lacks all benign findings
and verified person-level independence. Its benchmark is already exposed.
Repository evaluate_breast_detector.py and summarize_breast_cascade.py contain
calcium-specific metrics; they are not an already qualified generic tissue verifier
benchmark. Reuse B76's documented one-to-one matching contract after inspecting its
protected implementation, rather than silently substituting those older scripts.

| Requirement | Present status | Deliverable before fitting |
|---|---|---|
| Incumbent reproducibility | Historical B76 source/weight binding exists; live CPU parity unverified | Bind exact comparator and replay on development inputs |
| Normal candidate supervision | Missing from B72; prior reviews exist but reconciliation incomplete | Reviewed candidate-level normal/real/unknown manifest |
| Benign finding retention | VinDr boxes do not cover all BI-RADS2 findings | Explicit benign ROI references with source/provenance |
| Rare morphology | Small AD support; unknown usable support after reconciliation | Unique-person/study counts and class-specific uncertainty |
| Unexposed confirmation | Not verified; old TEST repeatedly inspected | Exposure ledger and reserved eligible cohort |
| Outcome supervision | Lesion-linked completeness not verified | Pathology/follow-up linkage and adjudication rules |
| Compute/runtime | A10040GB training resource known historically | Refresh host/VRAM, pin environment, measure target CPU |

Do not report these historical counts as a fresh inventory. The proposed200-region
audit in B82 is for feasibility, not a powered model assessment. Add only unresolved
or genuinely new cases to physician review; retain all completed annotations.

## Reference and split contract

Each protected row binds person linkage status, study/view, source hash, pixel
transform, detector/checkpoint/box identity, three separate targets and known-label
masks, reference provenance, reviewer confidence, dataset exposure and partition.
Normal needs explicit appropriate review; no box is not proof of normality. Case
malignancy must not propagate to every ROI. If reference revisions occur, freeze a
new version and reevaluate all comparators on it; do not credit label correction
as model improvement. Keep uncertain/coexisting appearance labels explicit.

Group patients and known repeat studies before crops/augmentation. If linkage is
unavailable, report study grouping and unresolved leakage rather than claim patient
independence. Audit duplicates and missing files. Use TRAIN for mining/fitting,
development for model selection, calibration for thresholds, and one locked
confirmation set for the selected candidate. Grouped folds may support development
when support is small; they do not make previously inspected data unexposed.

## Sequential experiment matrix

| ID | Question and controlled change | Controls | Measured outcome / trap |
|---|---|---|---|
| E0 | Is geometry and scoring trustworthy? Replay fixed detector and mapping | Identical pixels, normalization, NMS and box transforms | Candidate ceiling, missed identities, explicit normal marks; do not repair geometry only for one arm |
| E1 | Do reviewed detector false alarms help? Compare ordinary reviewed negatives with a mixture containing hard negatives | Same positives, unique negative budget, per-person cap, architecture, crop recipe, seeds and optimizer updates | Normal-mark reduction at retained finding recall; extra training volume must not explain the gain |
| E2 | Does training on deployment crops help? Replace reference-only crops with matched detector crops | Same people and underlying lesions, labels, training budget and negative mix | Reference-crop versus detector-crop typing gap; match only TRAIN for training assignments |
| E3 | Can shared learning improve type or cost? Compare separate presence/type models against shared encoder with masked heads | Same labels, input information and fixed tuning budget; disclose parameter/compute differences | Per-class metrics, presence retention, CPU cost; watch negative transfer |
| E4 | Is malignancy scoring meaningful? Fit only with eligible linked outcomes, then calibrate | Separate calibration data; preserve benign presence/type labels | Discrimination, Brier/log loss, reliability and clinical population applicability |
| E5 | Does learned view context add value? Local versus local+paired-view inputs | Same eligible studies, labels and comparator; sham pairing diagnostic | Incremental benefit, correspondence failures, latency; not another NCC threshold sweep |

Execute E0 then E1; do not launch all arms at once. E2 addresses a different
failure mechanism and needs reconciled type labels. E3/E4/E5 are conditional, not
mandatory additions. An eligible domain encoder is optional under B82; unavailable
weights/rights do not justify another generic backbone sweep.

For E1 replace a prespecified fraction of ordinary negatives with TRAIN-mined hard
negatives at equal data/update budget (initial protocol choice:50%, frozen before
fitting). Retain the same positives. Freeze mining scores and identities; no evolving
test-driven negative selection. If later testing additional data, add an equal-size
ordinary-negative control to separate quantity from hardness. Duplicates count as
sampling repetitions, not independent support. Balanced batches may aid learning,
but evaluation keeps its actual composition and reports prevalence.

## Measurement and success rules

These are proposed engineering continuation rules, not clinical acceptance criteria.
Freeze numerical settings in the executable run card before observing outcomes.

- Primary localization: one-to-one class-agnostic IoU0.3 matching; secondary IoU0.5,
  following B76. Report all reference lesions in the end-to-end denominator and
  separately report verifier retention among baseline-detected lesions. A verifier
  cannot recover lesions that have no candidate. Retain lost/gained identities.
- E1 target: at least20% relative reduction in marks on explicitly normal images
  against detector-only, with no point-estimate recall decrease at the locked
  operating point. Also compare hard-negative against ordinary-negative verifier;
  otherwise benefit cannot be attributed to mining. On calibration choose the
  highest rejection threshold retaining all baseline-matched reviewed findings,
  then lock it. If no nontrivial threshold qualifies, record failure to improve.
- Report full FROC and sensitivity at0.5,1,2 and4 marks per normal image when
  achievable. Distinguish normal-image marks from all unmatched positive-image
  predictions, which may be unannotated true findings. Never select a test threshold
  just to achieve matched recall; test curves are descriptive after lock.
- For a continuation claim require paired patient-bootstrap95% intervals supporting
  mark reduction, and lower recall-difference bound above -2 percentage points.
  This tolerance is a research uncertainty margin, not permission to hide lesion
  loss. Zero observed losses on a tiny set cannot demonstrate zero population loss.
  Unsupported intervals mean inconclusive, not success. Review every new missed
  reference and report benign and suspicious subgroups separately.
- E2/E3 typing target: at least5 absolute macro-F1 points over the matched control,
  paired interval excluding zero improvement, and no class recall decrease greater
  than2 points by point estimate. Also show per-class intervals; sparse support
  prevents a robustness claim. Compare against always-Mass and retained B50 on the
  SAME new cohort; historical49.06 is not a universal comparison denominator.
- Show conditional ROI typing AND end-to-end correctly detected-and-typed recall.
  Normal candidates belong to presence evaluation, not silently to a morphology
  class. If abstention is used, report coverage, remaining errors and all-case
  performance; use prespecified coverage points rather than discarding hard cases.
- E4: AUROC/AUPRC assess ranking; Brier/log loss and reliability assess calibration.
  A class-balanced case-control set alone does not establish screening risk. No
  probability/BI-RADS qualification without appropriate prevalence/outcome evidence.
- Bootstrap paired people with2000 draws and frozen seed; use studies only when
  patient grouping is unavailable and disclose it. Undefined rare-class replicates
  and missing-class folds are reported, not replaced by zeros. Seeds are repeated
  fits, not extra patients; report seeds17/29/43 separately and their average.

Do a precision/feasibility assessment from unique group counts before training.
If the planned minority-class or recall intervals cannot answer the question, use
the work as a pilot and request targeted additional references. Do not prescribe
a universal sample count from a desired percentage alone.

## Engineering checks, resource bounds and failure diagnosis

Before fitting: synthetic fixtures for duplicate predictions, whole-image boxes,
empty normal images, uncertain labels, out-of-bounds transforms, mixed findings,
missing heads, and one patient spanning views. Demonstrate tiny TRAIN-subset fit,
real parameter updates, finite logits, correct class order and checkpoint reload.
These are required future checks; no such new harness was executed in B84.

Use the existing compact model/input recipe first. Record exact optimizer, LR,
augmentation, batch size and normalization from the chosen implementation; do not
invent a supposedly optimal default here. Pin equal update caps for paired arms.
Select checkpoints on development constrained metrics, not training loss. Start
with one paired seed to catch failure; if usable, complete the other two seeds
before selecting a winner. Record unsuccessful trials too.

Capture per-task loss, gradient/update health, unique groups sampled, per-class
confusion, score distributions, development FROC, wall time and peak VRAM. Flat
training plus failed tiny-fit suggests pipeline trouble; improving training with
worsening held-group performance suggests overfit or shift and requires diagnosis.
Do not remedy low AD support with unlimited oversampling or test-driven tuning.

Keep calcium weights/processing fixed. Preserve physical pixel scale and deterministic
DICOM photometry; UI window adjustments and colored annotation overlays must not
be baked into training inputs. Context/margin preservation and realistic crop jitter
are hypotheses to isolate, not a bundle to add invisibly to E1.

Measure complete-study CPU latency (decode, detector, all candidates, verifier,
postprocessing), median/p95, memory and candidate-count distribution on the target
host. The owner's approximately one-minute preference is an engineering target;
no present pass is claimed. GPU ROI timing is not equivalent. High candidate counts
must not be hidden by an unreported top-k cap that loses lesions.

## Deliverables and decision

Next execution artifact is a protected readiness manifest plus aggregate audit,
followed by the E0 evaluator and frozen E1 run card. The reconciliation is still
incomplete. Each run must bind code/data/splits/checkpoint hashes and save private
paired predictions plus aggregate results. A new finding may justify a subsequent
arm; a null result stops that recipe. Inconclusive precision requests data, not a
claim that the model works or can never work. No production change is authorized
by a favorable research metric alone.

Reporting basis: [CLAIM2024](https://pubs.rsna.org/doi/10.1148/ryai.240300) for
transparent imaging-AI partitions and references; [TRIPOD+AI](https://www.bmj.com/content/385/bmj-2023-078378)
for prediction-model discrimination/calibration reporting. Neither specifies our
20%,5-point or2-point research thresholds. Those are explicit project proposals.
