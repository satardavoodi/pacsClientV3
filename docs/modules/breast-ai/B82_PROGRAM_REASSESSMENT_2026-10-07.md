# B82: Breast model program reassessment and data-first decision

Date: 2026-10-07. Status: retrospective evidence synthesis and refreshed primary-source
review. No training, model download, new patient evaluation or production change.
This decision supersedes the immediate learned-verifier fitting action in B81.

## Decision

Neither general soft-tissue finding typing nor clinically useful false-mark reduction
is qualified. The evidence does not establish a technology ceiling. It does establish
that repeating short encoder swaps, scalar features and NCC filters on the same
incomplete supervision is a poor next investment. Pause that experiment queue.
First close reference and candidate-dataset gaps, then permit one controlled
data-versus-representation experiment. Preserve the accepted calcium research branch.

Review scope: B01-B81 ledger, historical phase summaries, detailed pivotal records
B50/B62-B65/B69/B72/B74/B78-B81, plus primary sources below. Historical receipts
were not all rerun or rehashed. Report IDs include reviews, engineering and annotation
work: 81 records do not mean 81 independently optimized competing models. This is
a targeted technical reassessment, not an exhaustive systematic literature review.

## Separate the two targets and the definition of a false positive

1. Finding presence: distinguish a real finding from normal tissue or artifact in
   a detector-proposed box. A real benign mass remains a real finding.
2. Finding appearance: Mass, distortion, asymmetry-family or unresolved; retain
   multilabel/uncertain cases rather than forcing every region to one confident class.
3. Descriptors and BI-RADS assessment are further targets. They require their own
   reference and input context; a breast-level assessment cannot simply label every
   box. View confirmation is separate from single-view appearance.

Do not optimize cancer-screening false recalls by quietly deleting benign masses
when the product is expected to describe them. Maintain separate finding-presence,
suspicion/assessment and normal-tissue marking endpoints. A normal breast, a benign
lesion and an uncertain unboxed region are not one interchangeable negative class.

## What the accumulated evidence says

| Evidence | Established | Not established |
|---|---|---|
| B14-B34 calcium | Native proposal/scorer work and physician review identified useful retained behavior; edge false marks were adjudicated | Independent population sensitivity, morphology grading or improvement percentage versus Razi |
| B38-B45, B50-B52, B57, B64-B70 | Numerous real compact fits; weighting, transfer, features, resolution and encoder changes tested under recorded budgets | That each architecture was optimized to convergence, or that all public models were reproduced |
| B50 | 923 Mass,87 AD,260 family reference ROIs; only48 AD studies; local/context inputs and source descriptor pretraining | Normal-tissue rejection: no normal-reference class in that typing cohort |
| B72 | 272 test ROIs; highest observed macro-F1 49.06%, weak minority typing; constant-Mass accuracy73.16% | A roughly70% raw accuracy is not strong three-way classification or autonomous detection |
| B74 | Copied Razi classifier schema gate mismatch; corrected precomputed-feature diagnostic has many Mass overcalls | Successful live clinical classification or clinically validated corrected stacker |
| B78 | Threshold0.20 matches285/362 references (78.73%) but yields137005 marks on2258 normal images (60.68/image) | Useful screening at that operating point; high proposal sensitivity alone does not solve specificity |
| B79/B81 | Simple bilateral and geometry+NCC screens show only small burden changes | Failure of a fully trained multi-view mammography model; no such complete verifier was evaluated |

At threshold0.20,77 reference lesions remain unmatched under the fixed box/IoU
contract. A reranker cannot recover them. Inspect geometry and missed examples
before deciding whether these are true absence of candidates or localization failures.
Do not merge per-view IoU recall with case-level cancer sensitivity from papers.

## Most plausible bottlenecks, ranked by evidence

**Observed supervision mismatch:** soft-tissue typing mostly learned from publisher
reference crops without a normal class. It was not trained to reject the actual
mistakes made by the detector. This differs from the earlier calcium hard-negative
experiments B11/B17-B19, which did run and often failed. Hard-negative learning is
not a newly invented universal solution; its task-matched soft-tissue implementation
has not been demonstrated by the reviewed records.

**Observed data limitations:** few independent AD studies; missed source files;
VinDr omitted BI-RADS2 finding boxes; CBIS film-to-digital shift and mask exclusions;
model-assisted physician review includes unresolved region scope and export-field
differences. B63 found17 cases requiring conservative reconciliation; these are
not17 proven physician disagreements. Reuse completed reviews, preserve alternatives,
and ask only about unresolved fields or new relevant cases.

**Observed evaluation limitations:** repeated development selection, exposed TEST,
incomplete historical training provenance, and no fresh independent multi-site cohort.
Different units and reference types produced misleading headline comparisons.

**Plausible representation/optimization limitation:** generic pretrained encoders,
224 crops, short partial adaptation and sometimes no augmentation. B64's tested
384-context variant did not solve it. B45 overfit strongly, so simply training longer
is not supported. Neither resolution nor longer fitting is a proven remedy.

## Refreshed external evidence and reuse readiness

Checked 2026-10-07; primary papers and author resources only.

- [VinDr original paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10182079/): BI-RADS2
  findings were deliberately not boxed. Its consensus references lack pathology
  confirmation. This supports an annotation-scope gap, not a claim that all labels
  are wrong. [Publisher dataset](https://physionet.org/content/vindr-mammo/1.0.0/)
  separates breast-level and finding-level assessments.
- [Local-view finding classification](https://pmc.ncbi.nlm.nih.gov/articles/PMC12500588/)
  reports Mass recall75.95%, asymmetry recall17.72%, AD recall4.17%. AD binary
  accuracy99.41% therefore does not establish successful AD recognition. This close
  task match supports the difficulty of rare-class typing, not a general ceiling.
- [Commercial AI-CAD comparison](https://pmc.ncbi.nlm.nih.gov/articles/PMC6646646/)
  reports69% fewer false marks in245 cases, but only three cancer cases. Its endpoint
  treats some benign findings as unwanted cancer-screening marks, unlike describing
  all true lesions. It shows substantial reduction can occur elsewhere, not that
  its sensitivity or effect transfers to our cohort. No reusable weights verified.
- [Mammo-FM preprint](https://arxiv.org/html/2512.00198v1) reports pretraining on821326
  mammograms/140677 patients and mass localization mAP0.58 at IoU0.5. This is a
  genuinely different domain-pretraining scale, not a demonstrated Mass/AD/asymmetry
  ROI classifier or FROC result matching ours. No local inference performed.
- [Author repository](https://github.com/batmanlab/Mammo-FM) and
  [weight listing](https://huggingface.co/batmanLab/Mammo-FM/tree/main) are available;
  listed CLIP archive approximately2.15GB. Download/load success and exact artifact
  provenance were not verified. Code is Apache2.0; weights have a separate
  [academic license](https://raw.githubusercontent.com/batmanlab/Mammo-FM/main/LICENSE_WEIGHTS.txt)
  prohibiting industry evaluation without written permission, clinical use and
  distillation. Thus it is not currently an eligible product or internal-company
  experiment candidate merely because weights are listed. No download or outreach.
- [MammoVQA study](https://www.nature.com/articles/s41467-025-66507-z) documents
  limitations of general medical/general-purpose VLMs on its mammogram question
  benchmark. This is not a reason to replace the pixel pipeline with a generic
  chatbot, and VQA scores do not qualify lesion localization.

A mammography-specific pretrained representation is a credible distinct route,
conditional on task suitability, lawful asset access and local evidence. There is
no verified plug-in game changer ready for these two targets in this review.
Commercial licensed CAD is a separate buy-versus-build comparator if later requested;
we have not verified a procurement/API/CPU deployment option or sent any data.

## Complete evidence before another fit

Deliver one source-bound development manifest, not another disconnected model pilot.
Each candidate must bind examination/view, source signal and box transform, detector
version/score, native/context crops, reference source, reviewer certainty, and exposure.
Keep private records outside the repository; publish aggregate coverage only.

| Data bucket | Required reference | Use |
|---|---|---|
| Real benign and suspicious masses | Exact lesion box, morphology; assessment stored separately | Presence and type; do not label benign as normal |
| Asymmetry family | Full available views and exact ROI; uncertainty when view confirmation insufficient | Appearance and separate view-confirmed naming |
| Architectural distortion | Exact region, broader native context, reviewer confidence | Rare-class supervision and failure audit |
| Detector false alarms on normal tissue | Review actual detector proposals with full-view context | Soft-tissue false-positive reduction |
| Unboxed/ambiguous/discordant | Unknown/review-required | Exclude from supervised negatives; preserve for review |

First audit batch: target200 distinct candidate regions, approximately50 per first
four buckets, sampled across studies, density, size, site/device and detector score.
This is an annotation-feasibility/error-analysis budget, not a powered training or
qualification cohort. Existing reviewed examples count; do not fabricate rare-class
support or repeat the same lesion as independent data. If too few reliable AD cases
exist, report that shortfall and acquire relevant data rather than oversample blindly.
Review model outputs after an initial independent impression where practical; record
assisted exposure. Obtain second-reader/adjudication for unresolved type disagreements
when available. Agreement, uncertainty and exact-region consistency are outputs of
the audit, not assumptions.

Reserve new studies before review-driven fitting; group all views/crops and known
repeat patients. The already exposed VinDr TEST cannot become the new untouched
confirmation set. No clinical-data export is implied. New dataset access/rights
must be verified independently; dataset names alone do not create rare-class labels.

## One subsequent experiment and stop rules

After reference readiness, use the same frozen detector candidates for a factorial
comparison: current eligible encoder versus a task-matched eligible domain encoder,
and old supervision versus reviewed presence/type supervision. If no domain encoder
is eligible, run only the data ablation; do not replace it with another arbitrary
backbone. Learned bilateral evidence is conditional on correspondence quality and
comes after the local verifier earns benefit. Retain local fallback and uncertainty.

Separate a presence score (real finding versus reviewed normal/artifact) from type
outputs. Compare source-reference crops and actual detector crops to quantify the
deployment crop gap. Use prespecified development/calibration partitions, converged
or transparently capped training, sensible augmentation, train/development curves,
and a matched compute-budget control. An A10040GB is sufficient for a bounded probe;
need for larger hardware is unproven. CPU full-study cost remains an explicit gate.

Proposed research continuation gates, not clinical acceptance criteria:
- False marks: at least20% reduction at matched lesion recall, with paired study
  uncertainty and lost-lesion identities. Report the full FROC curve; do not hide
  low sensitivity behind sparse marks.
- Typing: at least5 absolute macro-F1 points over the matched control, per-class
  recall/precision and confusion, with prespecified class-retention guardrails.
  Abstention must report coverage and errors among answered cases; it cannot inflate
  apparent accuracy by silently dropping difficult examples.
- If gains disappear on held studies, stop that candidate. If reviewer disagreement
  dominates the target, revise the output contract instead of training harder.
- If adjudicated data, adequate fitting and one meaningfully different eligible
  representation still fail, declare the current resources/data insufficient for
  the intended automatic typing/rejection use. Keep descriptive/uncertain assistance
  or pursue licensed alternatives; do not promise an eventual successful model.

## Current conclusion and verification

Our deployed-quality objectives remain unmet. Our data/experiment design is not yet
sufficient to prove that no better solution is possible. The next deliverable is a
reconciled reference and candidate-data audit, not another immediate training job.
Historical numerical findings above were checked against their project reports;
web claims remain source-specific. Documentation link/whitespace checks only apply
to this turn; no code, GUI, new accuracy or clinical validation is claimed.
