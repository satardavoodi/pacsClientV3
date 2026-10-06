# Breast AI training and evaluation reporting contract

Version: 1.0, 2026-10-05. This is the project adaptation of the installed
`aipacs-radiology-model-development` skill, not another model-development skill.
Use with [current state](BREAST_AI_DEVELOPMENT.md), the
[ledger](BREAST_AI_EXPERIMENT_LEDGER.md) and the
[completed B19 review](breast-ai/B19_TRAINING_REVIEW_2026-10-05.md).

## Basis and scope

Skill source root:
`C:/Users/Dr.Alizadeh/.codex/skills/aipacs-radiology-model-development`.
Read `SKILL.md`, `assets/model-project-dossier.md`,
`assets/training-review-template.md`, and the relevant references for model selection,
population design, data/evaluation, training supervision and metric interpretation.
Training template SHA256 at adoption:
`1e4ea142f798c25e55f6086dfdb5639aef584423a5c9a745b4445231ef648e3f`.

External reporting sources checked 2026-10-05:

- [CLAIM 2024 update](https://pubs.rsna.org/doi/10.1148/ryai.240300): medical-imaging
  AI reporting, transparency and reproducibility. Use reference-standard terminology
  and disclose data partition roles precisely.
- [TRIPOD+AI 2024](https://www.bmj.com/content/385/bmj-2023-078378): reporting clinical
  prediction models. Assess applicability when defining patient-level diagnostic or
  prognostic outputs; do not treat every item as automatically applicable to a point localizer.
- [PROBAST+AI 2025](https://pmc.ncbi.nlm.nih.gov/articles/11931409/): appraisal of
  prediction-model quality, bias and applicability, not a reporting certificate.

The mapping below is our engineering implementation, not a verbatim checklist or
item-number compliance assessment. A complete formal checklist and external appraisal
have NOT been performed. Documentation conformity is distinct from model qualification.

## Mapping and present gaps

| Skill requirement | Project location | Current coverage / missing evidence |
|---|---|---|
| Portfolio/task identity and gate ledger | Current-state document, sections 1-3 | Intended use/stages explicit; clinical operating requirements still need adjudication |
| Landscape, build/adapt choice, source and rights | Current-state lineage table and historical research reports | Exact comparative evidence preserved; no new landscape search in this documentation task; weight redistribution rights unresolved |
| Cohort readiness and reference standard | Current-state section 4 and detailed run review | Group/image counts known; authoritative person linkage, age/density/site spectrum and independent sample precision incomplete |
| Code/data/environment/config/run binding | Per-run identity and artifact table | B19 backfilled from receipts; complete environment-lock binding not yet reconciled here |
| Optimization and telemetry | Per-run configuration and interpretation tables | B19 solver objective/iterations and native checks known; conventional epoch/LR/AMP fields inapplicable to that solver |
| Metric/selection contract and uncertainty | Per-run evaluation section | Point matching and gate fixed; no meaningful population interval from only two exposed positive groups |
| Model comparison and resources | Ledger plus per-run comparison | Count units and timing scopes distinguished; full Razi CPU latency absent |
| Physician feedback and qualification | Current-state section 5 and per-run next decision | Importance opinions separate from reference corrections; no independent clinical qualification |
| Reporting/bias appraisal | This mapping and per-run limitations | Known concerns recorded; no formal low-risk or standards-compliant certification |

## Required run record

Create `breast-ai/<B-ID>_TRAINING_REVIEW_<date>.md` for each new training/fine-tuning
run; use the headings below. Linked immutable evidence may supply long configurations
or curves, but the summary must state their identity and the decision they support.
For an evaluation-only run, mark fitting fields not applicable with a reason.
Historical ledger rows are summaries, not retroactively complete run cards. Backfill
a historical card before reusing its checkpoint as a new primary comparator.

Use these field states: **recorded**, **not recorded**, **not verified**, **not
applicable (reason)**. Do not invent plausible defaults. Distinguish retrospective
reconstruction from a protocol frozen before running. Incomplete evidence blocks only
claims that require it; it does not erase a documented failed experiment.

### 1. Objective and evidence identity

Run/B-ID; reporting date; purpose and hypothesis; modality/task/output unit; technical
owner and clinical-review status; model lineage; code/config/data/reference/split/
checkpoint hashes; trainer/host; environment versions and lock; parent checkpoint;
fresh fit versus warm start versus exact resume. A weight reload alone is not resume.

### 2. Cohort readiness

| Split / source | People and linkage status | Studies/groups | Images/tiles | Positive / negative / unknown support | View/device/site/age/density coverage | Exposure and gaps |
|---|---|---|---|---|---|---|

Record inclusion/exclusion, label author and scope, adjudication, prevalence/sampling,
duplicate and patient overlap checks, missingness, source release and rights. Distinguish
enriched training from intended screening population. Never count patches as patients.

### 3. Training configuration and telemetry

Architecture and trainable/frozen parameters; input pixel/spacing/polarity/normalization;
tile reconstruction; losses and reduction/weights; optimizer and parameter-group LR;
scheduler units; precision/scaler; batch/accumulation; sampler/augmentation; seed;
update/epoch budget; checkpoint frequency/selection; stopping conditions and resume state.

For actual runs capture loss components, comparable development measurements, successful
updates/gradient health, nonfinite/skipped steps, LR, unique source support, elapsed time,
throughput and peak RAM/VRAM where measured. Link raw curves/telemetry and note gaps.
Do not manufacture neural-learning telemetry for deterministic constrained optimization.

### 4. Metric and selection contract

Prediction and evaluation units; reference-standard version; known/unknown mask;
matching rule; denominator; candidate/threshold selection data and access history;
checkpoint selection/patience/evaluation frequency; failure/abstention accounting;
patient-group uncertainty plan; final-test lock. Different model scores may require
different TRAIN-selected cutoffs: report them explicitly instead of implying a fixed cutoff.

### 5. Training interpretation

| Observation and run segment | Evidence / denominator | Competing explanation | Confidence / limitation | Discriminating check | Action |
|---|---|---|---|---|---|

Loss alone does not establish good clinical learning or prove overfitting. Separate
proposal misses, scorer losses and output/matching effects before attributing failure.

### 6. Candidate comparison and resources

| Candidate / checkpoint | Primary count and interval status | Important/rare-focus recall | Unwanted outputs / calibration | Subgroups | Training / full inference cost | Decision |
|---|---|---|---|---|---|---|

Include failed variants and per-case losses/gains; distinguish points, connected
components and adjudicated clusters. State whether timing is cached, incremental,
GPU inference or full target-CPU operation. Record seed variation or its absence.

### 7. Decision and next experiment

Continue/reject/diagnose/retain with reason; what actually ran; what remains proposed;
one next hypothesis and fallback, data prerequisites, frozen comparison, resource/time
cap and stopping rule. Missing approval, rights, data or clinical acceptance must be named.
No retrospective threshold rescue on development failures presented as independent success.

### 8. Sources, limitations and qualification

Protected artifact paths/hashes and official methodology sources; privacy-safe summaries;
relevant reporting coverage and bias concerns; model versus pipeline issue; code, data,
GUI, physician-review, independent evaluation and deployment states separately.

## Maintenance and review gate

Before a run, save the prospective fields and identify unknowns. After a run, fill
actual telemetry/outcome and preserve failures/protocol amendments. Update the ledger
and current-state document in the same session. Verify links, counts, model lineage,
thresholds, denominators and unchanged reference files. Never label missing metadata as
passed simply because a file was created. Documentation-only edits need document checks,
not a claimed application GUI or training test.
