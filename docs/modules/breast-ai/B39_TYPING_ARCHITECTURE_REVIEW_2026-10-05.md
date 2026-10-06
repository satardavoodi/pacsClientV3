# B39: Reopen lesion-typing architecture selection

Reviewed 2026-10-05 under the radiology-model-development skill. Owner explicitly
requests comparison of methods before further commitment to the current model.
No architecture has earned a best/optimal claim. B38 establishes only that two
imbalance interventions on one handcrafted representation failed the Mass gate.

## Correct task and evidence scope

Task: type an already localized non-calcification finding as Mass, Focal Asymmetry
or Asymmetry, preserving ambiguity and missing-view states. Cancer risk, malignancy,
breast density and BI-RADS assessment are different targets. High scores for those
tasks cannot establish performance for this three-way task. Retain current detection
as the first controlled comparator; evaluate native versus reference ROIs separately.

The [2023 DenseNet asymmetry study](https://pubmed.ncbi.nlm.nih.gov/37448557/) assesses
benign versus malignant asymmetries in 460 women, reporting AUC 0.778. It does not
establish Mass-versus-FA-versus-Asymmetry accuracy. Similarly, the
[2023 four-view radiomics/deep-feature study](https://pubmed.ncbi.nlm.nih.gov/37083190/)
reports malignancy discrimination: four-view AUC 0.876 versus single-projection
0.817/0.792. This supports a context hypothesis, not a transferable accuracy target.

## Shortlist: source-verified facts and local decisions

| Route | Verified evidence/access | Fit and decision |
|---|---|---|
| Existing FCOS + stacked features | Locally recovered; label-dependent/row-order pairing and missing Asymmetry head documented in B35 | Freeze localization; keep as lineage comparator, not default winning typing model |
| Handcrafted local/context + compact boosting | B38 actual grouped fits; current native-context experiment is an ablation | Low-cost hypothesis test; stop blind weighting sweeps, do not select by training loss |
| Shared ResNet-18 encoder, local ROI + larger context, then optional view fusion | [Official TorchVision weights and preprocessing](https://docs.pytorch.org/vision/main/models/generated/torchvision.models.resnet18.html); about 11.7M parameters, generic ImageNet pretraining | Preferred practical image baseline; new supervised three-type head required. Not a ready breast model; no measured local accuracy or CPU latency yet |
| GMIC global/local multiple-instance route | [Author repo](https://github.com/nyukat/GMIC) provides five ResNet-18-based weights and preprocessing; outputs benign/malignant image scores; repository lists AGPL-3.0 | Useful global/local design comparator; not drop-in typing. Exact weight rights and training overlap need review before reuse |
| Mammo-CLIP B2/B5 | [Author repo](https://github.com/batmanlab/Mammo-CLIP) links weights; B2 lightweight option; configurations distinguish image-text from VinDr-augmented pretraining | Domain encoder candidate, not ready three-class head. CC BY-NC-SA restriction prevents assuming commercial Eagle Eye use. Do not download/adapt as a product dependency without resolving rights; VinDr pretraining may contaminate evaluation |
| Mammo-FM | [Author repo](https://github.com/batmanlab/Mammo-FM) separates Apache-2.0 code from custom academic model-weight license | Newer does not mean deployable or best; license/access and task fit block immediate product reuse |
| GLAM geometry-guided CC/MLO alignment | [MICCAI 2025 paper](https://papers.miccai.org/miccai-2025/paper/2415_paper.pdf) models patch-to-slice relationships; [author repo](https://github.com/XYPB/GLAM) has Apache-2.0 code but explicitly no released pretrained weights | Strong method reference for deformation-aware view context; not a ready checkpoint. Full pretraining is not the quickest first experiment |
| LAS-GAM four-view global/local reasoning | [2026 publication record](https://pubmed.ncbi.nlm.nih.gov/40924534/) describes patient-level cancer diagnosis with contralateral lesion screening | Supports comparing global and local evidence; exact reusable assets not verified, and target differs |

Upstream README/model documentation was inspected on the review date; no external
weights were downloaded, licenses accepted, or source revisions installed. Main-branch
pages are not pinned dependency receipts. Pin revision, weights and preprocessing
before execution. Framework names MONAI/YOLO do not specify a qualified typing model.
Replacing localization with another detector is secondary until detection errors are
shown to cause the typing failures on the matched cohort.

## What transfers from the calcification work

Reuse candidate-then-verifier organization, source-preserving native crops, multiple
scales, local-versus-surrounding contrast features, explicit failure attribution,
physician adjudication and paired lost/gained-case review. Preserve mixed findings:
calcification presence is an auxiliary attribute, not a mutually exclusive lesion type.

Do not transfer the bright-peak proposal rule as a mass candidate gate: diffuse
asymmetries need not contain punctate peaks. Do not transfer the trained calcium
head as a validated mass classifier. Reusing an encoder is a separate controlled
adaptation, with checkpoint/data exposure tracked. The accepted skin filter is not
evidence that peripheral non-calcification lesions can be suppressed. Eight-case
physician acceptance is not population-wide qualification for any branch.

## Selected next experiment and fallback

Execution update: the native-context ablation finished during this review. It
adds 27 intensity/gradient descriptors (ROI, surrounding ring, differences) to
the 59 cached features, using raw DICOM decoding, rescale slope/intercept,
MONOCHROME1 inversion, padding exclusion and per-image percentile normalization.
The reference region and its twice-width/height neighborhood are analyzed at
stride 4. This is coarse context, not native-resolution boundary morphology;
no VOI LUT or display window is applied. No masks or CNN features are learned.

Three paired fits give mean macro F1 36.86%, Mass recall 93.72%, FA recall 18.29%,
Asymmetry recall 0%, versus B38 A0 38.28% / 94.31% / 21.08% / 0%. Reject this
specific descriptor addition. It does not disprove image encoders or multi-view
context. All 1,083 selected images decoded without recorded failure, producing
features for 1,189 rows in 148.03 seconds (decode/extraction, not full serving latency); saved models
reloaded with identical predictions. No patient images were externally transmitted.
Receipts and private outputs: P/typing-context-pilot-20261005; implementation:
P/typing_context_pilot_20261005.py. Feature and script hashes are in results.json.
This is development evidence only, with the same exposed reference-ROI limitations.

1. Completed: finish the native local/context statistics ablation against B38
   on identical row identities and splits. This tests information content, not the
   superiority of CNNs or multi-view reasoning. Preserve failures explicitly.
2. Next image experiment: generic pretrained ResNet-18, shared weights for local
   and two-times context crops, frozen encoder plus regularized three-class head.
   Compare local-only versus local+context before adding view complexity. Confirm
   padding, aspect ratio, grayscale channel mapping and resolution preserve margins;
   do not blindly center-crop away the finding. No diagnosis from saliency alone.
3. Then add full ipsilateral view context with missing-view masks and label-blind
   attention. Use deformable/patch-to-region correspondence as a hypothesis; never
   pair by target label or first CSV row. Compare contralateral context separately.
4. If frozen features fail, permit one bounded staged fine-tuning experiment, then
   reassess data/labels or a rights-cleared domain encoder. No unlimited model sweep.

Proposed budget (not executed): first 32 eligible fitting studies for decode/geometry,
load/update/reload and resource smoke; then fixed development cohorts. At most one
GPU-hour for initial feature extraction/probes, followed by at most three GPU-hours
for a predeclared fine-tuning comparison, only after fresh Linux GPU availability.
Use the A100; no H200 assumption or interruption of unrelated services. CPU serving
must be timed for complete studies; small parameter count alone is not a latency pass.

Keep seed list and groups from B38 for exploratory comparisons; reserve calibration
and an unexposed qualification cohort before final claims. Report macro F1, each
class recall/PPV, coverage/abstention and paired Mass losses. Initial acceptance:
improved typing without observed Mass recall loss in each paired development split;
later qualification needs uncertainty and independent clinically reviewed cases.
If a fixed threshold or subgroup metric is selected after seeing these splits,
record that additional development exposure rather than calling it test performance.

Decision: local+context image representation is the next practical candidate;
multi-view reasoning is the strongest task-informed extension. Neither is yet a
measured winner. Changing the scientific question or accepting a larger training
budget cannot substitute for demonstrating improvement against a matched baseline.
