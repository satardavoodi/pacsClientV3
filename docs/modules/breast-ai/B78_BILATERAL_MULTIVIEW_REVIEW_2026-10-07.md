# B78: Bilateral and ipsilateral context for candidate verification

## Question and decision

Date2026-10-07. Owner proposes using contralateral tissue and ipsilateral CC/MLO
evidence to distinguish tissue superposition from lesions. Prioritize a label-blind
multi-view candidate verifier, with a cheap bilateral-feature baseline before a
large new model. Normal fibroglandular structure is anatomical background, not
independent additive noise; direct subtraction is not a validated lesion mask.
No verifier trained or multi-view performance result produced in B78.

## Primary research inspected

- [Wu et al., Medical Physics2007](https://pmc.ncbi.nlm.nih.gov/articles/PMC2742209/):
  bilateral regional registration, texture/morphology features, LDA fusion after
  candidate detection.341 cases,276 with masses and65 normal. At matched malignant
  case sensitivity70/80/85%, reported false positives decrease approximately40/44/42%.
  Digitized-film, limited twofold study; not evidence that our FFDM pipeline will
  gain those percentages, nor a lesion-typing accuracy result.
- [Four-view CAD study2011](https://pmc.ncbi.nlm.nih.gov/articles/PMC3069993/): supports
  evaluating contralateral and ipsilateral evidence jointly rather than assuming
  one view alone settles abnormality. No numerical claim imported here.
- [CEN, MICCAI2024 author project](https://mammo-iitd-aiims.github.io/CEN): explicitly
  argues that CC/MLO correspondence is geometrically ambiguous; uses morphological
  cross-view cues to refine detector proposals. Authors report sensitivity gains
  of5% on INbreast at0.3 false positives/image, with smaller gains elsewhere. These
  are author-reported results, not local reproductions or percentage guarantees.
  [Official code](https://github.com/Mammo-IITD-AIIMS/CEN) exists; inspected README
  has no operational checkpoint/preprocessing instructions. Downloadable task weights,
  dependencies, license and complete reproduction remain unverified.
- [Four-image transformer2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9320758/):
  case-classification AUC improvement is evidence of complementary information, not
  directly comparable to B76 lesion recall. Do not substitute AUC for detection.

## Existing implementation audit

Read `modules/ai_imaging/eagle_eye_engines/vendor/breast/TWO_VIEW_FEATURES.py`:

- `_pick_cc_mlo_opposite` can select the opposite-view row by overlap of
  `finding_categories`; without that evidence it selects the first row. Reference
  labels must not guide pairing in a blind evaluator. Presence of this branch is
  an audit concern, not proof every historical run executed it.
- `_pick_contralateral_roi_row` selects the first available ROI on the opposite
  side in the same study/view, not a spatially registered corresponding region.
- `_mirror_crop_from_contra` falls back to raw pixel-coordinate mirroring using
  the other image width. It does not establish breast-shape/nipple/chest-wall
  alignment under different sizes, compression and positioning.
- Existing SSIM/NCC and texture deltas therefore do not establish that a robust
  contralateral/CC-MLO verifier has already been tested and failed. B50 local/context
  crop branches are also not genuine paired mammographic views.

## Data readiness and actual diagnostic computation

CSV metadata audit confirms all843 available B75 studies have exactly one each of
L-CC/R-CC/L-MLO/R-MLO (3372 images). This proves pairing metadata availability, not
correct physical registration or lesion-level cross-view correspondence.

Recomputed B76 saved predictions with the unchanged area0.002 rule, class-agnostic
IoU0.3 and fixed native reference boxes. This is a post-test candidate-ceiling
diagnostic, not a newly calibrated operating point or verifier result:

| Score threshold | Matched/362 lesions | Recall | Marks/2258 normal images | Marks per normal image |
|---|---:|---:|---:|---:|
| 0.45 | 161 | 44.48% | 1305 | 0.578 |
| 0.40 | 198 | 54.70% | 3751 | 1.661 |
| 0.20 | 285 | 78.73% | 137005 | 60.676 |

At0.40 there are37 additional net matches with2446 additional normal marks. At0.20,
all2258 normal images are marked. Even perfect reranking of these fixed proposals
cannot recover reference lesions without a matching candidate:77/362 remain unmatched
at0.20 under this box geometry and area rule. A verifier can improve the tradeoff,
but cannot alone guarantee near-total detection; separate proposal/geometry work
remains necessary. Do not infer the owner's stage-one tissue-area reduction target
from box count; union tissue coverage has not been measured here.

Protected diagnostic: point-review root and Linux candidate root,
`b78-multiview-evidence-20261007/threshold-diagnostic.json`; local thresholds.py and
Linux parent b78-thresholds.py. No source images or identifiers in this report.

## Proposed controlled implementation

1. Generate predicted candidates on TRAIN using the frozen detector; include explicit
   normal-image hard negatives. Keep all views per study together. Unknown/unboxed
   BI-RADS2 regions remain unknown, not automatic hard negatives. Use adjudication
   for ambiguous unmatched candidates. Do not train on B76/B77 TEST outputs.
2. Build a minimal same-view bilateral comparator: verified orientation, breast mask,
   chest-wall/nipple-relative normalized location and a bounded correspondence search.
   Compare ROI and surrounding context at multiple scales using local brightness
   residuals, texture, gradients, edge organization and morphology. Retain original
   images and features alongside any difference map; do not subtract away evidence.
3. Add ipsilateral-view support separately: broad anatomically plausible search and
   appearance correspondence, not exact CC-to-MLO pixel mapping. A missing counterpart
   is uncertainty, not proof of normality. Pairing must ignore labels and must also
   work when only one view's detector supplies a proposal.
4. Fit a small regularized reranker first. Compare identical candidates with local
   features only, local+bilateral, local+ipsilateral and all three. A shared encoder
   or cross-attention module is a later hypothesis if simple features improve the
   development tradeoff. Add a shuffled-opposite-study negative control to test whether
   pairing contributes beyond generic extra context or model capacity.
5. Preserve a single-view fallback for missing/poorly aligned views, surgery, implants
   or uncertain matching. Symmetry must not hard-delete a suspicious finding; bilateral
   abnormalities and benign asymmetry are possible. Local lesion morphology remains
   part of the score. Keep calcium high-resolution cues separate from tissue symmetry.
6. Select operating points on grouped development/calibration data. Compare normal
   marks at matched lesion recall and recall at matched false-mark burden, with paired
   study intervals. Report proposal recall and verifier losses separately, including
   lesions present on only one view. Audit matching quality, tissue coverage and CPU
   latency before a frozen TEST replay. A proposed engineering target is at least20%
   fewer normal marks with no more than2 percentage points lesion-recall loss versus
   the same candidate baseline, subject to uncertainty; not a clinical qualification.

## Status and next action

Evidence review, current-code audit, quartet readiness and threshold diagnostic
complete. No learned registration, trained verifier, measured bilateral benefit or
clinical change yet. Next build the label-blind paired development manifest and
check registration/correspondence visually on a small development set before fitting.
This is a stronger task-matched hypothesis than another unrelated ROI backbone, but
the claimed advantage must come from the controlled ablation, not the literature alone.
