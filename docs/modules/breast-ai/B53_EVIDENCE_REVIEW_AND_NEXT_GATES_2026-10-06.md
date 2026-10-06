# B53: Evidence reconciliation and next decision gates

Date: 2026-10-06. Documentation and retrospective evidence review only; no new fit,
dataset relabeling, threshold selection or deployment. This is the decision receipt
for the existing [current-state document](../BREAST_AI_DEVELOPMENT.md), not another
master plan. Historical next-action paragraphs remain dated evidence, not parallel
instructions. Reviewed B35-B52 and the separate calcium lineage/physician decisions.

## What the evidence supports

| Route | Observed evidence | Current decision |
|---|---|---|
| Reviewed calcium localization | Positive physician review on eight exposed cases; B33 adjudicates 16 selected edge flags | Preserve checkpoint, original references and feedback. General screening sensitivity/specificity and external qualification remain unproven. |
| Shared preparation | B43 median eight-image preparation 2.1156->1.8963 seconds with exact parity | Retain reuse; not a whole-study CPU latency claim. |
| Old Mass/FA/Asymmetry experiments | B38 weighting, B39 descriptors, B40 generic encoder, B44 feature/auxiliary fusion and B45 adaptation show tradeoffs or overfit | Do not repeat blind fusion/epoch/weighting sweeps. These use a different task/cohort from B50. |
| CBIS morphology transfer | B50 matched macro F1 46.49->52.12%, AD recall10.42->22.50%, family46.86->50.30%, Mass84.39->84.03% | Preferred research comparator. All paired macro-F1 intervals include zero; no clinical promotion. |
| Additional class weighting | B50 macroF1 52.23%, Mass78.34% | Not preferred over unweighted transfer; minority gain costs substantial Mass recall. |
| Neutral target padding | B51 macroF1 51.21%, AD17.50% | Reject this tested change. Extreme padding does not explain most held-out AD misses. |
| Fully frozen source encoder | B52 macroF1 40.78%, AD2.08% | Reject this five-epoch candidate; smaller fitting gap alone is not success. |

B50-B52 contain 18 actual fits (three source auxiliary and 15 target fits).
They do not establish the best possible architecture. Fixed short budgets, selected
ROIs, uncertain references and limited minority groups constrain interpretation.
No percentages from calcium points, old three-way typing and new AD-inclusive
typing should form a single improvement curve. No Razi whole-image >90% finding
performance was established by these ROI experiments.

## Corrected understanding of the bottleneck

1. **Target semantics are unresolved in some cases.** Mass appearance, standalone AD,
   asymmetric tissue, mixed descriptors and view-confirmed terminology differ.
   A source label is not a freshly adjudicated reference. Most AD false calls in
   the weighted experiment originate from Mass, but this does not prove those are
   spiculated masses: VinDr lacks margin truth. Do not assign the mechanism by guess.
2. **AD-specific support is small and was not supplied by the CBIS auxiliary task.**
   B50 trained shape/margin heads on 1,015 standard-mass-shape CBIS ROIs. The 73
   nonreserved pure legacy AD rows /46 people were not used for that pretraining.
   Their presence is a data opportunity, not evidence they are already QC-ready or
   clinically equivalent to VinDr AD. VinDr target has only87 AD ROIs /48 studies;
   development support is16/20/16 ROIs.
3. **Imbalance alone is not the demonstrated root cause.** Weighting trades errors;
   it cannot add patient diversity or repair labels. Repeated views are not independent
   people. Four CBIS lymph-node people cannot qualify a node classifier by oversampling.
4. **Input-detail loss is plausible, not established.** AD median native short side
   is188pixels, so merely upsampling all224inputs cannot recover missing information.
   Examine actual downsampling factors, clipping and context before selecting higher
   native-source resolution. Black/replicated padding changes are not tissue recovery.
5. **Evaluation exposure is a separate limitation.** Repeated inspected development
   groups cannot become an independent test. Most cases have no reviewed normal
   reference, so these confusions cannot measure normal-study specificity.

## Ordered next actions

### Gate 1: Targeted reference and source readiness before another broad fit

Prepare a small source-bound review pool of up to24 distinct fitting studies, balanced
across source AD, Mass and asymmetric-family examples where feasible. Include relevant
mixed/uncertain examples and confounders; do not discard ambiguity to make an easy cohort.
Use full-resolution local/context and available companion views. The physician should
first see images without model answers, then the disagreement overlay. Record dominant
finding, coexistence, certainty, view evidence and region adequacy separately. This is
clinical morphology adjudication, not another request to dot every calcification.

Prefer fitting-only nominees. Existing development errors remain diagnostic audit data;
if their reference is corrected, version it and repeat the comparison transparently.
Never move them into fitting while retaining the same independent-evaluation claim.
No extra physician input has been received for this task yet; the pool above is proposed,
not a fabricated completed review or a ready browser page.

Independently audit the73 candidate CBIS AD rows, retaining original descriptors and
all publisher-test/historical nontraining person reserves. Check full/crop/mask role,
native geometry, source hashes and duplicates. B50's65 mask-size failures concern its
standard-mass cohort; do not extrapolate that pass rate to AD or stretch failed masks
into alignment. Determine whether an original source/mapping repair is possible.
Keep unresolved rows quarantined. Missing images and normal truth remain explicit.

**Exit evidence:** source-bound review records or explicitly unchanged source-only
targets; exact available AD person/ROI counts; geometry/known-label masks and partition
receipt. Proceed as source-label research only if clinical adjudication remains absent,
and do not present such a fit as resolving the medical distinction.

### Gate 2: Test task-matched AD supervision against the preserved comparator

If Gate1 supports it, prioritize an AD-specific auxiliary task or a source-aware AD
training stage, with masks for unknown labels and source vocabulary preserved. Do not
blindly concatenate every CBIS mass-folder row with VinDr or treat all unmentioned
findings as negatives. Decide the exact target mapping before fitting.

Compare B50-style morphology pretraining with the added reviewed/eligible AD supervision
on the same target task and groups. Match target updates and account for extra source
compute; include a compute-matched control before attributing gain to data content.
Keep one intervention at a time; retain partial target adaptation unless new evidence
justifies changing it. This has higher priority than another generic attention layer
because the existing source training did not directly teach the weak target.

### Gate 3: One justified input-detail experiment

In parallel with readiness, measure native-to224 scaling, intensity saturation and
available context on source images without changing labels or training on holdouts.
Only if this shows a recoverable input limitation, freeze one native-resolution or
context-extent comparison; do not upscale cached224 tensors and call it new detail.
Preserve split, initialization, source supervision and comparable update budget;
report added GPU/CPU cost. This ordering supersedes an automatic 'higher resolution
next' interpretation of B51/B52. Larger input/model size has no guaranteed benefit.

### Gate 4: Qualification independent of model selection

Prepare a genuinely unused person/study cohort, with exposure history and reviewed
normal/hard-negative cases. Keep all views/repeats of a person together where linkage
exists. Lock the candidate and thresholds before final assessment. Evaluate finding
localization on full images and typing on predicted as well as reference ROIs.
Preserve mixed/uncertain outputs and report coverage, per-class precision/recall,
AD false calls, missed findings and population-appropriate calibration. Normal
specificity, malignancy assessment and CPU serving each need their own evidence.

## Advance, stop and defer rules

Keep B50 research weights unchanged. Advance a candidate only on paired per-class
benefit with acceptable Mass/family tradeoffs, known uncertainty and no missing-case
concealment; a higher mean macro F1 alone is insufficient. Freeze numerical operating
requirements with the protocol before the next fit, not after seeing outcomes.
If adjudication or source QC changes the cohort, rebuild the matched comparator.
Stop that route when it fails its fixed protocol; do not rescue it with test thresholds.

Defer large architecture sweeps, extra hardware, unconditional density rules, global
asymmetry naming from crops, blind multi-view pairing, and production replacement.
Calcium-feature transfer failed its tested forms; preserve useful shared preparation
without assuming calcium signals distinguish AD. Published source methods in B39/B46/B48
are task-specific context, not transferable accuracy claims. No fresh literature search
or new source-performance claim was made in this documentation review.

## Documentation corrections and verification

Current-state front matter now owns one active priority order. Its long dated entries
are explicitly historical snapshots. Calcium scope, edge-review completion and timing
are separated from current soft-tissue typing work; obsolete pending-review wording is
marked superseded. The ledger heading/date reflect October6. Run reports retain original
results and failures; no result file or clinical reference was changed.
Document link/language checks and source result hashes are verified separately from
training, GUI or clinical acceptance. This turn performs no fit or runtime acceptance.
