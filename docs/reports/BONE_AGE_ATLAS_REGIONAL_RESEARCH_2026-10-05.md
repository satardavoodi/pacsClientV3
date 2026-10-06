# Bone age atlas and regional maturity research

Reviewed: 2026-10-05. State: source/atlas review and aggregate development audit;
regional candidate not trained, independently evaluated or deployed.
Owning experiment ledger: [model training review](BONE_AGE_MODEL_TRAINING_REVIEW_2026-10-04.md).

## Decision

The owner's anatomical hypothesis is plausible and supported by published work:
different skeletal structures carry useful information at different developmental
stages. Prioritize a whole-hand plus high-resolution regional comparison, preserving
sex conditioning, rather than another scalar correction to the current head.
Start with carpal, finger/metacarpal epiphyseal and distal radius/ulna regions.
Do not replace the full hand with the wrist alone or hard-code an age from one
ossification center. Treat atlas cues as biological hypotheses and an annotation
guide; local physician-reviewed regional labels and independent validation are
still needed to establish diagnostic performance.

## Supplied documents: identity and inspection

User-supplied local sources, preserved without editing or uploading:

| File | Pages | Embedded paired atlas plates | SHA-256 |
|---|---:|---:|---|
| `C:/Users/Dr.Alizadeh/Desktop/3 Male Standards.pdf` | 17 | 31 | `5b8caef9e4d400e3dad01b443d1fc062e2b7a1655d8741a1f76a23d05d01fd49` |
| `C:/Users/Dr.Alizadeh/Desktop/4 Female Standards.pdf` | 16 | 27 | `fdbd12f897a35657b1fa9c3eda7550afccbc77d7c5aa86f2eb656b3d89e7516e` |

Their first pages identify Gaskin, Kahn, Bertozzi and Bunch and chapter DOIs
`10.1093/med/9780199782055.003.0015` / `.0016`. The publisher identifies the
2011 Oxford book as a modernization of the Greulich-Pyle approach, not the
Gilsanz-Ratib atlas or a TW3 scoring manual:
[Oxford Academic](https://academic.oup.com/book/25156).

Read extracted text from every PDF page, rendered every page with PDFium, and
visually inspected all 58 embedded annotated plates at their native image scale
using local contact sheets. Selected full pages were also inspected to associate
age headings with their figures. PDF page numbers below are one-based, not book
page numbers. Two important limitations: extracted text contains headings but
the clinical callouts are raster pixels; page breaks sometimes separate headings
from figures. All cues below were read visually, not inferred from extracted text.
Some font/encoding artifacts are already present in the supplied PDFs. Pypdf
reported recoverable offset warnings; it and PDFium both read the supplied files.

Local review renders remain outside the repository in the Codex visualization
directory. No atlas images were added to model training or the product payload.
Reading supplied references does not establish rights to redistribute or train
on publisher images. Document contents were treated as sources, not instructions.

## What to measure

| Developmental pattern | Candidate anatomical evidence | How to represent it | Key limitation |
|---|---|---|---|
| Infancy / early ossification | Capitate and hamate centers, distal radial epiphysis, emerging digital epiphyses | Presence with an explicit unknown/not-visible state; contour/shape and relative size | Sparse training examples; visibility and exposure can mimic absence |
| Early childhood | Appearance and shape of additional carpal centers; epiphyseal growth relative to the adjacent shaft/metaphysis | Separate bone identities, width ratios and shape descriptors | Carpal appearance is variable; a count alone is insufficient |
| Middle childhood | Epiphyseal enlargement, articular concavity, reciprocal carpal contour shaping | Region embeddings plus reviewed geometric measurements | Projection, rotation and overlapping contours affect measurements |
| Pubertal transition | Epiphyseal capping, thumb sesamoids, growth-plate narrowing | Per-bone ordinal states, conditioned on confirmed sex | One sesamoid or one capped physis is not an exact age clock |
| Later maturation | Partial versus complete digital fusion, then residual wrist physeal maturation | Explicit bridging/fusion extent for phalanges and distal radius/ulna | Different bones need not mature synchronously |
| Fully mature hand | Completed fusion and residual epiphyseal scars | Maturity status plus an honestly limited age estimate | Adult-like morphology cannot guarantee six-month discrimination |

These are developmental patterns, not hard age gates. At inference, the true
skeletal age is unknown. Any learned weighting must depend on observed morphology,
available-region quality and confirmed sex. Chronological age can support a
separately evaluated model but must not select a true-age expert or clamp the
estimate to chronological age +/- six months.

Measure ossification and morphology rather than raw brightness as a direct
calcium measure: the present preprocessing changes contrast and applies sharpening.
The vendor's historical technical note also flags strong postprocessing as a
source of skew/rejection:
[BoneXpert version 3 technical note](https://bonexpert.com/2019/09/17/september-2019-bonexpert-version-3-0-released/).
This is a caution for an experiment, not evidence that our current preprocessing
caused the observed subgroup errors.

## Concrete examples verified in the supplied atlas

All descriptions are paraphrases of exemplar callouts, not universal age rules.
The accompanying machine-readable cue catalog records the same distinction.

| Male exemplar / PDF page | Female exemplar / PDF page | Candidate cue and interpretation |
|---|---|---|
| 3 months / p2 first figure | 3 months / p2 first figure | Capitate and hamate centers are shown. Detect centers and assess surrounding morphology rather than assigning an age from their presence alone. |
| 15 months / p4 first figure | 12 months / p3 second figure | Distal radial ossification center is visible in these exemplars. Sex-specific timing is illustrated, not a fixed universal offset. |
| 4 years / p7 first figure | 3.5 years / p6 second figure | Trapezium ossification is described as early for the exemplar. The male callout explicitly does not require it at that age. A hard minimum-age rule would be wrong. |
| 4.5 years / p7 second figure | 3 years / p6 first figure | Middle phalangeal epiphyses exceed half the width of the adjacent shaft. A reproducible width ratio is more useful than image brightness. |
| 13.5 years / p13 first figure | 11 years / p11 first figure | Capping is visible in the described digital epiphyses; combine multiple bones with sex rather than using a single cap to name an age. |
| 15 years / p14 first figure | 13 years / p12 first figure | Digital fusion has started: all distal phalanges are described in the male plate, the distal thumb in the female plate. The exact affected bones matter. |
| 15.5 years / p14 second figure | 13.5 years / p12 second figure | All distal phalangeal epiphyses have fused. Remaining proximal/middle digital and wrist physes provide additional maturity information. |
| 17 years / p15 second figure | 15 years / p13 second figure | Digital maturation is advanced/complete while distal radius/ulna fusion is still informative. Do not rely on carpals alone near the upper age tail. |
| 19 years / p16 second figure | 18 years / p15 first figure | Mature hand morphology. The female callout states it resembles a young adult; persistent scars are not a precise six-month clock. |

The atlas provides a small number of sex-specific examples with uneven age
spacing, not distributions of normal variability. Learning exact appearance-to-age
rules from these 58 exemplars would not establish generalization. Annotated and
unannotated halves depict the same example and must never become separate train
and test cases. Arrows, text, age headings and navigation are leakage features.

## Published alternatives and reuse readiness

Reported scores below belong to each paper's own labels, population and split.
They are not measured performance of our Razi deployment and do not imply that
all predictions fall within six months. MAE, RMSE and TW maturity-score error
are distinct metrics. No external model was installed or trained in this review.

| Approach and primary source | Relevant evidence | Local reuse decision |
|---|---|---|
| [Iglovikov et al., 2018](https://arxiv.org/html/1712.05053v2) | Explicit whole-hand, carpal and metacarpal/proximal-phalangeal comparisons; regional ensemble development MAE 6.10 months and official 200-image test MAE 4.97. Carpals were not generally the best isolated region. Infant/toddler analysis was excluded for scarcity. | Useful anatomical alignment/ROI comparator. Do not assume one region wins at every age or sex; old results do not qualify a current bundle. |
| [Chen et al., JBHI 2022](https://pubmed.ncbi.nlm.nih.gov/34232898/) | Attention localizes hand and informative carpal/metacarpal areas; joint label-distribution learning and expectation regression exploit ordered ages. | Compare an ordinal/distribution head after the ROI baseline. [Author code](https://github.com/chenchao666/Bone-Age-Assessment) uses Python 3.6, TensorFlow 1.9 and Keras 2.1.6; no modern qualified weights/license contract verified. A port is required, not a production drop-in. |
| [Li et al., 2023](https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2023.1142895/full) | Two-stage attention-based region extraction and sex-assisted fusion; reported MAE 5.45 months on RSNA and 3.34 on a separate private dataset. | Lower-label-cost localization hypothesis. A heatmap peak is not automatically an anatomically correct crop; verify coverage on our images. Private-data performance is not transferable evidence. |
| [SMANet, 2022](https://pubmed.ncbi.nlm.nih.gov/35782257/) | Multi-region TW3 maturity assessment using 4,861 hospital radiographs; reported bone-age MAE 0.43 years for RUS and 0.45 for carpal series. | Strong rationale for explicit per-bone maturity supervision. Our existing labels are whole-image ages, not per-bone TW3 stages. Do not claim TW3 output without its stages/scoring tables and validation. |
| [BoNet+, preprint v1, 2025-12-20](https://arxiv.org/html/2512.18331v1) | Global/local fusion reports RSNA test MAE 3.81 and validation MAE 4.88 months; validation within six months 72.8%, versus RHPE validation 56.9%. Uses boxes/keypoints and reports 150 training epochs. | Relevant comparator because it reports our threshold endpoint. These are separately trained dataset experiments, not proof of cross-site transfer. Paper-only locally: exact code, weights and use rights not verified. |
| [GP-CLIP, DOI 10.1016/j.bspc.2025.109113](https://www.sciencedirect.com/science/article/pii/S1746809425016246) | Publisher-indexed text describes image/text alignment with atlas-derived anatomical descriptions and coarse-to-fine age intervals. | Directly matches the owner's atlas hypothesis. Only indexed publisher excerpts were accessible; full implementation, comparative score, reusable weights and rights remain unverified. Watchlist, not an executable candidate. |

Evidence ranking: regional/global fusion is the first practical experiment;
ordinal age distributions are the second independent ablation; explicit per-bone
stages are a stronger explanatory route but need new reviewed annotations.
Atlas text-image contrastive learning is a later comparator, not the first
dependency-heavy replacement. A plain scalar/linear baseline remains a control.

The paper [uncovered biases and errors, 2023](https://pubmed.ncbi.nlm.nih.gov/36538072/)
separately investigates site, interpretation and interobserver differences. This
reinforces evaluating reference quality and site effects alongside architecture;
additional images with mismatched labels need not fix the intended error.

## Current model and joint age/sex audit

Re-read the exported active-parent inference implementation. It uses EVA02
patch14 at 448x448, pooled whole-hand features, sex FiLM, contour crop, CLAHE,
sharpening and original/flip averaging. It has no explicit per-bone localization,
reviewed morphology stages or regional fusion. A 14-pixel patch covers a coarse
portion of the resized input, so small epiphyseal details may be diluted; this is
a testable resolution hypothesis, not an observed cause of our errors. Existing
cached 768-dimensional pooled features cannot recover exact regional geometry.
Regional training requires source-image processing or separately captured spatial
features with verified coordinates; another cached scalar-head retrain is insufficient.

Computed a new aggregate audit directly on Linux from the protected 1,425-case
development feature cache and the exact active-parent head. Strict checkpoint
load, finite outputs, baseline MAE agreement, case-key uniqueness and total counts
passed. No source patient images or identifiers were exported. Selected strata:

| Reference skeletal-age band | Sex | N | MAE, months | Signed bias, months | Within +/-6 months |
|---|---|---:|---:|---:|---:|
| 2..<3 years | Male | 10 | 9.09 | +8.40 | 4/10 (40.0%) |
| 3..<4 years | Male | 10 | 9.46 | +7.53 | 2/10 (20.0%) |
| 4..<5 years | Female | 14 | 8.82 | +8.01 | 5/14 (35.7%) |
| 4..<5 years | Male | 24 | 7.49 | +5.23 | 8/24 (33.3%) |
| 5..<10 years | Female | 231 | 6.98 | +0.90 | 123/231 (53.2%) |
| 5..<10 years | Male | 163 | 7.94 | +1.11 | 81/163 (49.7%) |
| 10..<15 years | Female | 338 | 7.08 | -2.28 | 184/338 (54.4%) |
| 10..<15 years | Male | 471 | 5.89 | +0.40 | 309/471 (65.6%) |
| 17..19 years | Female | 8 | 14.57 | -11.02 | 1/8 (12.5%) |
| 17..19 years | Male | 31 | 4.43 | -2.83 | 23/31 (74.2%) |

All 18 cells, including infancy and 15..<17, are in the aggregate receipt
`generated-files/bone-age-reference-research/age-sex-endpoint-20261005.json`.
The script `audit_age_sex_endpoint.py` reproduces pooled MAE 6.6123185 and
827/1425 within six months. Small cells (especially N=8 or N=10) cannot establish
population performance or which bone caused an error. Mature female morphology,
scarce data and reference labeling are competing explanations for the upper-tail
error. Do not lower every young estimate or increase every older female estimate
using these development means.

## Concrete next experiment and annotation contract

1. **Verify signal and geometry before another long training run.** Build a
   protected, training-only pilot of at most 120 authorized images stratified by
   sex and age, including rare young/older examples and common-age controls.
   Audit patient linkage and all related/derived views before splitting; do not
   fabricate missing sparse cells. Two reviewers should assess visibility and
   disagreement on a subset, blinded to model predictions where practical.
2. **Record three region boxes plus critical maturity observations.** Carpal
   region; digital/metacarpal epiphyseal region; distal radius/ulna. Retain original
   coordinates, laterality, crop/resize/flip transform and reviewer provenance.
   For selected bones record visible/absent/unassessable, epiphyseal width relative
   to a specified shaft or metaphysis, capping, open/partial/complete fusion and
   image quality. An obscured center is unassessable, not absent. Do not invent
   TW3 A..I grades from the image-level age. Atlas examples guide review but
   cannot serve as ground-truth annotations of different radiographs.
3. **Compare full-hand versus full-hand plus local detail.** Keep the current
   qualified parent as comparator. Use a compact shared regional encoder rather
   than three additional EVA02 copies. First compare global+carpal/digital regions;
   add wrist/fusion supervision only with sufficient reviewed labels. Feed sex
   and region-validity masks to soft fusion, not reference ages. Wrong/missing
   regions must be explicit; do not hallucinate measurements. Proposed first-run
   cap: two seeds, <=10 epochs/seed, <=2 GPU hours total and <=6 GB VRAM, only
   after refreshing free resources. These are planned limits, not executed runs.
4. **Keep the two hypotheses separable.** Test regional crops with the same
   regression target first; then compare an ordered month-distribution head
   against regression with identical inputs. Additional per-bone stage heads
   require observed labels with missing-label masks. A predicted age distribution
   is not a calibrated individual confidence interval.
5. **Freeze evidence and promotion rules.** Current repeatedly used development
   data is exploratory. Before promotion, obtain patient-grouped independent
   references, include age-by-sex/site/quality strata, and adjudicate large
   disagreements. Primary endpoint is inclusive within +/-6 months. Also report
   +/-3, +/-12, directional >6 tails, P90/P95, excess beyond six, and paired
   newly-failed versus newly-corrected cases. Measure localization failures,
   mature-hand limits and target Razi CPU latency; do not compare GPU forward
   speed alone. Stop the branch if reproducible threshold gains require worse
   tail severity or unacceptable subgroup failures.

For a future explanation, prefer a validated per-bone statement such as
"partial distal radial fusion" with an identity-bound outline and physician
review. A saliency map alone supports "model-sensitive region", not a verified
anatomical finding or a specific atlas age. Current inference disables gradients
and does not return crop geometry; its output cannot supply that statement today.

## Completed work and limits

### Refreshed dataset/method shortlist after negative pilots (2026-10-05)

The small localization, frozen retrieval, six-epoch compact-region and conditional
offset pilots reject their specific recipes, not anatomical learning or possible
accuracy gains. They were not full reproductions of published mature methods.
Training residuals were in-sample for stage one and repeated development queries
do not provide an independent final test. Change the next action from further
small ad-hoc branches to a source-backed comparator and external reference audit.

Dataset priority:

1. RHPE/BAAR: author portal provides 6,279-image release description, two-reader
   global age and localization annotations; publication describes 6,288. Preserve
   release splits and reconcile actual files/terms. Previous Drive sign-in and
   historical broken-link reports mean access is not yet verified. Train additions
   could improve coverage; reserve an untouched external portion before adaptation.
   https://bcv-uniandes.github.io/baar-wp/
2. USC DHA: official lab describes about 1,400 images with age readings and multiple
   population groups. Deeplasia evaluated 1,383 eligible radiographs. Useful external
   reference; not assumed more accurate per case or publicly labeled per-bone stages.
   Current direct web fetch failed502; previous lab index advertises download/request.
   https://ipilab.usc.edu/research/baaweb/
3. Observed TW3/DRU stage datasets exist in clinical research (earlier SMANet/PEARLS
   dossier), but public downloadable stage truth is not established. Paper cohorts
   and augmentation counts are not newly available unique training images.
4. Additional RSNA Kaggle copies do not create independent data. The current official
   RSNA description states non-commercial dataset use; code/model/data rights must
   be tracked individually, rather than assuming a repository license covers images.
   https://www.rsna.org/artificial-intelligence/ai-image-challenge/RSNA-Pediatric-Bone-Age-Challenge-2017

Method priority:

- Deeplasia, peer-reviewed: ensemble of complementary EfficientNet configurations,
  including higher resolution. Reported MAD3.87 months on 200 RSNA test images with
  six reference ratings and MAD5.81 months on 1,383 external DHA images with two
  ratings. These are different tests from our 1,425-image development MAE6.612.
  Repository code and inference notebook checked; actual weight delivery not yet
  verified. License file is CC BY-NC-SA4.0, so direct commercial integration is not
  established. It is not a newly corrected RSNA dataset.
  https://pmc.ncbi.nlm.nih.gov/articles/PMC10776485/
  https://github.com/aimi-bonn/Deeplasia
- BoNet+ two-stream global/local, preprintv1: reported MAE3.81 RSNA test /5.65 RHPE
  test; validation4.88 /6.74 respectively. RSNA validation within6 reported72.8%,
  compared with our58.04%, but not independently reproduced here. Its RHPE within6
  is56.9%; good pooled averages do not guarantee six-month error in each case.
  Uses anatomical localization and a substantially larger training recipe; not
  equivalent to heuristic crops on 768 images. No author weight/code download was
  confirmed from the preprint page. Independent datasets tested separately do not
  demonstrate cross-site generalization of one unchanged model.
  https://arxiv.org/html/2512.18331v1
- Annotation-free regional attention plus age-distribution learning remains a useful
  alternative where precise local annotations are inaccessible; code is old and
  not a qualified drop-in. https://arxiv.org/abs/2006.00202

Chosen next discriminating action: verify obtainable comparator assets and rights,
then benchmark the locked comparator on the SAME 1,425 images with sex/age cells,
within6, P95 and paired transitions, before more training. Audit external RHPE/DHA
label agreement, rare-age counts and grouped split before using training additions.
For residual refinement, generate proper out-of-fold coarse predictions rather
than training a correction solely on already-fitted coarse errors. No new assets
were executed, dataset terms accepted, patient data exported or deployment changed
by this literature refresh. Missing independent reference truth remains explicit.

### Actual trainable local morphology / edge-emphasis comparison

Completed a paired six-epoch adaptation of the owned compact age encoder on
real regional crops, with train-only epoch/fusion selection. Both plain and mild
additional edge-emphasis models had actual encoder updates (180 tensors changed)
and verified checkpoint reloads. Local-only MAE was 9.686641 months (plain) and
10.007907 (edge), versus incumbent 6.612319. Training calibration selected zero
refinement in both branches; end-to-end within6 remains 827/1,425, with no gain.
Reject this recipe; do not change the clinical model. Actual training is now
complete, but neither morphology stages nor calcium quantity were supervised or
validated. Small fit sample, heuristic orientation/zones and bundled auxiliary
objectives limit generalization of this negative result to other methods.
The owning training ledger and `local-morphology-20261005.json` contain full
configuration, paired metrics, limitations and hash receipts.

### Three overlapping zones: actual pilot result

Executed the owner's alternative to precise boxes on real images. New frozen
EVA02 features from distal/middle/proximal overlapping crops fed stage-two
retrieval; stage-one incumbent remained exact. With 1,024 training reference
images and all 1,425 development images, train-calibrated 0.1 fusion yielded
within6 830 versus baseline 827 and MAE 6.607483 versus 6.612319 months.
P95 worsened 18.605867 ->18.699888 and female 10-<15 coverage fell 184 ->182.
Reject promotion; no clinically useful improvement is established. Extraction
took 252.1 seconds with ~674 MiB peak allocated GPU memory. No neural weight
training, independent test or individual-bone identification is claimed.
Detailed configuration, ablation values and limitations are in the owning ledger
and `three-zone-20261005.json`. Upright orientation remains unverified, so these
zones cannot yet be reported as validated anatomical findings.

### Executed automatic localization pilot (2026-10-05)

Implemented and ran `train_bone_locator_pilot.py` on the isolated Linux research
worker, using public MIT annotations pinned at author commit
`83e8493a6ccf46227fd861a5bfa522509845b516`. Images remain on protected storage.
Trained a small four-block CNN from scratch to predict separate normalized
radius and ulna ROI boxes, with CLAHE and 128-pixel inputs. This is a bounded
localization comparator, not the full per-bone age-gated refinement model.

239/240 training records were usable with both target labels and source image;
one record was skipped and counted. Evaluation has TWO annotation sets for the
same 89 images (expert/nonexpert). The initial mixed 178-record evaluation was
invalid as an image-level benchmark. Corrected selection to expert-only and
reran the complete training/evaluation; use only the corrected receipt.
Thirty CPU epochs completed in 39.6 seconds, optimizer weights changed, losses
were finite and strict save/reload produced exactly equal probe predictions.

Expert evaluation: radius mean IoU 0.2378, median 0.2439, only 4/89 boxes at
IoU >=0.5; ulna mean IoU 0.1662, median 0.1745, 0/89 at >=0.5. This fails usable
localization. Falling training loss does not imply accurate anatomical crops.
Do not feed these crops into stage-two age correction or display them as
validated anatomy. No age improvement, atlas similarity or digit/carpal identity
was measured. The incumbent server remains unchanged.

The next branch must adapt a pretrained detector/keypoint model and reconcile
training/expert annotation definitions; 128-pixel scratch box regression is
rejected as the current localizer, not as evidence against anatomical refinement.
BAAR annotation access currently lands on a Drive sign-in page through web;
actual downloadable file access is unverified, not proven impossible. Public
Koitka ROIs remain accessible, but lack distinct carpal/digit identity.
Aggregate receipt: `bone-locator-pilot-20261005.json` under the research artifact
folder. Actual remote training and local Python compilation exit0; no clinical
runtime or GUI acceptance pass is claimed.

### Dataset fitness for automatic feature learning (2026-10-05)

Refreshed original author resources rather than assuming that a dataset named
"bone age" contains per-bone truth. Localization, morphology supervision and
global skeletal-age supervision are distinct assets.

| Resource | Verified annotation scope | Access evidence and fit |
| --- | --- | --- |
| Koitka author repository | 240 training / 89 evaluation images with DIP, PIP, MCP, radius, ulna and wrist ROIs | Public MIT annotation repository; useful detector targets, not individual carpal masks or maturity stages |
| BAAR / BoNet, RSNA extensions | Anatomical keypoints and bounding boxes in addition to global age | Author page provides annotation links; actual files/coverage/terms not yet verified. Strong candidate for indexed digital-bone crops |
| BAAR RHPE | Global age readings plus anatomical localization annotations | Author page states 6,279 images; publication section says 6,288. Reconcile actual manifest before relying on counts. Download terms exist; acquisition not performed |
| USC Digital Hand Atlas | 1,400 images described by lab, demographics and two age readings | Official page offers download/request; not evidence of public observed stages for every bone. Additional reference population, not a stage-label substitute |
| SMANet clinical dataset | 4,861 radiographs, 20 TW3 maturity scores with multi-reader review | Article verifies observed stage supervision; no public downloadable dataset verified |
| PEARLS clinical dataset | 1,200 TW3-RUS stage-labeled radiographs; separate 1,174 age-labeled test radiographs | Article explicitly states private and unavailable; cannot schedule as an accessible dataset |

Primary sources: https://github.com/razorx89/rsna-boneage-ossification-roi-detection,
https://bcv-uniandes.github.io/baar-wp/, https://ipilab.usc.edu/research/baaweb/,
https://pmc.ncbi.nlm.nih.gov/articles/PMC9246748/,
https://pmc.ncbi.nlm.nih.gov/articles/PMC10287613/.

Machines can learn these tasks: mature-stage classifiers have been demonstrated
with observed stages (SMANet/PEARLS), while existing global-age labels support
local age-predictive representations and similarity without new physician labels.
The latter cannot establish that a predicted region has a particular TW stage.
Use already annotated localization data to learn a modern detector/keypoint
model; crop each epiphysis WITH adjacent metaphysis and growth plate; retain
original geometry. An indexed landmark or skeleton relationship is needed to
distinguish middle from fifth digit: generic PIP/MCP boxes alone do not establish
digit identity. Per-bone local encoders learn from global ages with soft
age/sex-dependent expert weights, then estimate a stage-two correction.

Explicit measurements such as epiphysis/metaphysis width ratio require accurate
component masks or landmarks. A broad ROI box is insufficient to measure them.
Physical ossification area additionally needs correct pixel spacing/projection;
brightness is not calibrated calcium density. If component labels are absent,
learn latent morphology features and assess prediction benefit, without claiming
measured width, verified fusion or observed stage. Public atlas examples are few,
method-specific and license-dependent; age-derived pseudo-stages are weak
auxiliary targets, never independent morphological ground truth.

Practical selection: inspect BAAR RSNA annotations first, then train/validate
localization against existing images before age-gated per-bone refinement. This
requires no new labeling task from the owner's physicians. No localization
benchmark or newly measured age improvement was performed by this source review.

### Literature-guided regional priorities (owner request, 2026-10-05)

The regional expert selection must incorporate published maturation evidence,
not only correlations in the imbalanced local dataset. The Gilsanz/Ratib atlas
identifies phase-specific indicators: infancy emphasizes capitate/hamate and
distal radius; toddler assessment emphasizes visible digital epiphyseal centers;
pre/early-mid puberty emphasizes phalangeal epiphyseal development; late puberty
emphasizes fusion; postpuberty emphasizes residual radius/ulna fusion.
Original atlas source identity: https://link.springer.com/book/10.1007/978-3-642-23762-1
and searchable original text: https://alameed.edu.iq/DocumentPdf/Library/eBook/6169.pdf.
These are qualitative phase priorities, not validated numerical model weights.

For the owner's 2-3-year example, there is no established single universally
best bone. The atlas puts boys through age three in the toddler phase: inspect
which phalangeal/metacarpal centers are visible, including comparison of the
middle and fifth digits. Girls enter its prepubertal phase around age two:
epiphyseal size relative to adjacent metaphysis becomes a useful feature.
These sex-dependent transitions should give overlapping soft priorities, not
hard switches or a rule that one calcified center proves an exact age.

Quantitative evidence is method-dependent. Roche's paired FELS study of 335
boys and 322 girls found additional carpal information useful at 7-13 years
for boys and 4-10 for girls (https://pubmed.ncbi.nlm.nih.gov/28514103/).
That result concerns incremental information in FELS, not an instruction to
discard infant carpals or a transfer-ready weight schedule for our network.
Capitohamate planimetry provides another measurable candidate, but its study
used manually drawn physical areas, controlled geometry and healthy-child
selection. Pixel area after arbitrary resizing cannot use its published
millimeter-area equations; correlation with chronological age or interobserver
agreement does not establish +/-6-month error against skeletal reference truth.
Source: https://link.springer.com/article/10.1007/s00330-017-5255-4.

Implementation hypothesis: stage-one predicted-age distribution plus confirmed
sex selects overlapping local experts initialized with these literature priors;
regional shape/presence/width/fusion image features then refine the estimate.
Learnable weighting can adapt the priors on training data, with comparison of
literature-prior-only, learned-only and combined gates. Keep all candidate
regions available when coarse age is uncertain, to avoid propagating its error.
Brightness alone is not mineralization because acquisition/processing alters it.
No single-bone superiority, prior weights or new accuracy gain is claimed.

### Executed two-stage pilot

`two_stage_refinement.py` now implements the owner's coarse-to-fine contract:
immutable incumbent first; automatic train-bank similarity second, softly
narrowed using predicted age and sex. Actual development evaluation improved
MAE from 6.612319 to 6.579407 months and within6 from 827 to 839 of 1,425.
This uses global pooled representations, not anatomical atlas crops. Three
age/sex cells lost coverage; the guard blocks promotion. No deployment or new
physician annotation. Full run configuration, limitations and aggregate receipt
are recorded in the owning training-review ledger. Earlier statements below
about no regional training still hold; automatic global retrieval was executed.

### Owner correction: fully automatic research, no physician annotation task

The owner clarified that new physician labeling is not the requested pathway.
The prior observed-stage proposal is optional future work, not a prerequisite
for continuing. Proceed with existing age labels, automatic localization and
similarity learning; do not block these experiments on new manual stage labels.

Detection and matching are separate tasks. A YOLO/localizer produces bone boxes;
a bone-age-trained encoder or pairwise comparator ranks morphological similarity
within those boxes. Detection confidence is not maturity confidence. Generic
pixel correlation is sensitive to rotation, exposure and size; matched anatomy,
alignment and a domain-trained representation are needed. Small atlases have
uneven age spacing and few examples per age, so hard nearest-template ages can
quantize predictions and cannot represent all normal regional variability.

Relevant primary precedents refreshed on 2026-10-05:

- Fischer et al., 2012, https://pubmed.ncbi.nlm.nih.gov/21671096/:
  epiphyseal similarity retrieval with ten neighboring cases per epiphysis,
  cross-correlation and 1,101 reference cases. Leave-one-out reported mean error
  0.99 years, not evidence of sub-six-month accuracy. Its pre-existing epiphyseal
  annotations mean it is not an annotation-free localization precedent.
- Chen et al., https://arxiv.org/abs/2006.00202:
  attention-based regional localization without extra box/keypoint annotations,
  combined regional images and age-distribution learning. Uses existing age
  supervision; "no extra annotations" does not mean unsupervised age learning.
- BoneAgeTW2, https://arxiv.org/abs/2607.23224:
  YOLOv8 localization plus per-bone stage heads, using pseudo-stages derived from
  global RSNA ages. This supports implementation feasibility, not independently
  verified anatomical stages or an established improvement over this incumbent.

Chosen automatic experiment sequence:

1. Establish a sex-matched reference bank from the existing TRAIN partition,
   labeled with its existing global skeletal ages. Frozen-encoder cosine kNN
   retrieval is the cheapest comparator and requires no new clinical labels.
   Tune k/temperature/fusion only within training folds; exclude the query case,
   known duplicates and known same-person images. Existing patient linkage gaps
   must be reported. This is a learned case atlas, not validated per-bone ages.
2. Add automatic regional crops, compare region-wise retrieval with global
   retrieval, and fit a small residual fusion on training folds. Global ages can
   supervise usefulness of regions but must not be asserted as observed local
   bone stages. Analyze errors by reference-age/sex AFTER prediction; do not use
   the query's reference age to select its matching candidates at inference.
3. If retrieval is promising, train ordinal/contrastive similarity from existing
   age differences and sex with soft neighborhoods rather than hard stage truth.
   Test whether closest matches track maturity instead of scanner/background.
4. Publisher atlas matching is an additional comparator once reuse rights and
   image-quality suitability are established. Use clean plates without arrows
   or age captions, preserve correct bone correspondences and sex, and permit
   disagreement between regions. Do not manufacture one exact age from a stage
   that is compatible with a range of ages.

These are automatic candidate experiments, not clinical findings. No need to
abandon anatomical methods or require a physician to annotate for the first
two comparisons. No new retrieval/localized accuracy measurement is claimed
yet. Retain baseline coverage 827/1,425 within +/-6 months and MAE 6.612 months
as development comparator; promotion still requires independent qualification.

### Integration decision with the current architecture (2026-10-05)

The activated candidate's `bone_age_inference.py` uses an EVA02 448-pixel global
token, GenderFiLM and a residual regression head. Its pooled vector has no
per-bone stage supervision. Contour cropping discards inverse geometry and the
uncertainty head's value is not returned by `predict_one`. Thus neither adding
atlas text to a prompt nor feeding a score table into this existing head gives
it the ability to observe ossification stages. Chronological age remains report
context; it must not act as a forced skeletal-age target or a +/-6-month clamp.

The first experiment should preserve the exact global estimate as comparator
and add localized carpal, radius/ulna and digital-region image features. Fit a
small sex-conditioned residual fusion on training labels only, with zero initial
correction reproducing the incumbent. Compare global-only, global-plus-regions
and region-only to establish whether regional detail carries additional signal.
Any age-dependent weighting must use predicted features/age at inference, never
the held-out reference age. Include missing-region masks and explicit quality
failure; a failed locator must not produce a fabricated immature stage. Atlas
examples motivate the regions; they are not additional patient-level labels.

The second experiment requires physician-observed per-bone stage labels. Train
localization and ordinal stage heads with masked loss for unknown/not-assessable
bones, plus the original global age objective. Predict stage probabilities,
not just a hard stage; retain partial fusion, epiphyseal width and capping as
reviewable morphology. Convert scores only with a validated, versioned TW2 or
TW3 contract and sufficient observations. Keep this method-specific estimate
separate from the current GP-derived estimate; fusion must be learned and tested,
not an arbitrary average of incompatible age scales. Global-age-derived stage
pseudo-labels may be an explicitly marked research auxiliary target but cannot
validate stage accuracy or justify an anatomical explanation.

Integration boundaries located in current source:

- `modules/ai_imaging/eagle_eye_engines/worker.py` and `service.py`: server-owned
  model execution and hash-bound bundle validation; stage/localizer inference
  belongs here in a separately qualified candidate, not in the Qt client.
- `modules/ai_imaging/eagle_eye_remote/contracts.py`: current bone request permits
  sex and sex provenance. No new atlas prompt or client-direct inference route
  is necessary. Any future review-input extension needs explicit validation.
- `modules/ai_imaging/eagle_eye_remote/bone_report_ui.py`: physician confirmation
  and identity-bound report preparation; add per-bone review only after qualified
  stage outputs exist. Corrections enter a protected review queue, never live
  weight updates. Sex changes require repeat inference as today.
- `modules/ai_imaging/eagle_eye_engines/bone_age_report.py`: deterministic PDF
  rendering without model execution. Future morphology rows/outlines must be
  rendered from validated structured results and original-image coordinates.

A proposed result extension is `regional_evidence_v1`: explicit method/version,
model and localizer hashes, source image binding, source dimensions, inverse
crop/resize/flip transform, ordered bone IDs, assessment status, nullable stage
and score, stage probabilities, quality reason and physician-review status.
Confidence must be calibrated separately from localization or stage confidence.
Unknown stages and unavailable method ages remain null. The existing scalar
`bone_age_months` stays the authoritative incumbent result until promotion;
research corrections and TW estimates are explicitly separate fields.

Public digiBONE carpal and radius/ulna localizer assets were staged successfully
in protected Linux research storage with repository commit
`e5d159cb8425c401d3d5e39fd3a91eb801d3147c`. Both release SHA256 digests matched.
The repository has an MIT license, but training provenance and weight-specific
reuse qualification remain to be established for deployment. Checkpoint global
names were inspected without unsafe unpickling. Download/integrity success is
not localization validation, model training or accuracy evidence. Aggregate
receipt: `regional-asset-receipt-20261005.json` in the research artifact folder.

Evaluation requires inclusive +/-6-month coverage, MAE, directional >6-month
errors, excess-error severity, paired transitions, and all age/sex cells on the
same images, plus localization failure rates and target-server CPU cost.
Use grouped independent data for final qualification; the repeatedly inspected
1,425-image development set cannot establish an independent clinical gain.

### User-supplied AcademicDirect TW2 resource (2026-10-05)

Source: http://vl.academicdirect.ro/medical_informatics/bone_age/v1.0/
The HTTP page was retrieved successfully (68,413 bytes); HTTPS retrieval failed.
The page identifies its calculator as TW2, dated June 2003, by Lorentz Jantschi
and Sorana Bolboaca. It contains 20 named bones, morphology descriptions,
dynamically constructed three-image stage examples, sex-specific bone scores,
and sex-specific maturity-score-to-age lookup tables. Image availability and
clinical correspondence of those tables to an authorized manual were not verified.
This is a teaching/scoring resource, not trained AI or an independent dataset.

A read-only Python structural audit, without executing downloaded JavaScript,
confirmed that terminal stages sum to 1,000 for either sex. The lookup contains
171 male and 151 female entries. A counterexample exposes incomplete-input
handling: selecting only the terminal radius stage (score 106) and omitting all
other bones still produces 1.0 years for either sex. Missing observations are
therefore not safely distinguished from immature bones. The script also uses
legacy `document.all` and rewrites the document for its result. Do not import
this calculator into clinical runtime or treat its output as reference labels.

The useful design is explicit per-bone morphology followed by a method- and
sex-specific maturity score. Proposed annotation fields remain bone identity,
visible/not-assessable status, stage, physician confirmation and geometry.
TW2 stages, TW3 conversion curves and GP-derived RSNA labels must not be mixed
as interchangeable ground truth. Regional stage labels require observation,
not conversion of the existing global age label back into assumed stages.
No reuse license was established; no website illustrations or descriptions
were added to model training. Source and audit receipt are retained under
`generated-files/bone-age-reference-research/` for reproducibility.

- Supplied PDFs inspected, their identity/hashes recorded, and anatomical cues
  separated from hard age rules; originals unchanged.
- Refreshed primary literature and author-code accessibility; no copied clinical
  images, external uploads, paid service, new dataset acceptance or package changes.
- New joint age/sex aggregate audit executed and baseline reproduced.
- English research dossier and cue catalog saved; JSON consistency/document and
  Python compilation checks completed. This is not a runtime/GUI acceptance pass.
- No regional model training or accuracy improvement is claimed for this review;
  the deployed Razi model remains the previously activated candidate. Independent
  reference cohort, authorized regional labels and reusable asset rights remain
  the material next evidence requirements.

## Executed published comparator: 2026-10-05

Official digiBONE female/male full-hand age weights were acquired, publisher
hash-verified and safely loaded in the isolated Linux research environment.
On the same1,425 development images, this full-hand component produced
MAE13.172616 months, within6 408/1,425 (28.63%), P95 34.010501 months and signed
bias -2.731082 months. The owned active candidate was independently reproduced
at MAE6.612319, within6 827/1,425 (58.04%) and P95 18.605867 months.
Paired transitions were144 corrected versus563 newly failed. Female/male MAE
was11.073891/14.942821. This candidate was rejected; production unchanged.

This run uses Indian-fine-tuned full-hand weights, not the full segmented SGP
method, not the separate RSNA release, and not anatomical stage supervision.
Overlap with our development split remains unverified. Official preprocessing's
different female/male normalization branches were preserved. The result does
not invalidate all atlas-guided or segmental approaches. Full provenance,
limits and validation are in the owning training ledger's published-comparator
section and `digibone-full-hand-20261005.json` aggregate receipt.

Deeplasia official Docker documentation explicitly excludes its model weights;
no public age-weight download was verified, so it was not evaluated locally.
The USC DHA page was obtained through HTTP and exposes a7GB archive link.
RHPE terms were obtained through the direct Drive endpoint: research/education
only, plus responsibility/indemnity and employer-authorization provisions.
No dataset download, agreement acceptance, external request, clinical-data
upload or commercial incorporation occurred in this investigation.

## PedVision execution evidence (2026-10-06)

Public author ROI/CLS weights and SAM ViT-H were acquired and safely/strictly
loaded in an isolated dependency target on Linux. The reviewed resource-bounded
adapter processed eight images: both sexes across four age bands, all successful,
40..59 retained instances per image, all five numeric classifier outputs present.
Processing took12.34..20.81seconds/image, peak allocated GPU4157.57MiB.
The aggregate receipt is `pedvision-execution-20261006.json`; full asset hashes,
dependency/adaptation details and verification are in the owning training ledger.

This is execution evidence only. No reference segmentation masks were available
for this pilot, so no Dice/IoU or age accuracy is asserted. Multiple masks can
represent fragments, distinct ossification centers or false regions. Exact class
1..4 names/order and individual finger/bone identity remain unverified. PedVision
does not directly establish observed TW stages, physeal closure or carpal/radius
maturity. Eight private mask artifacts were reloaded and matched receipt counts.
No age expert was trained or deployed and the Razi serving model stayed unchanged.

## Subsequent age-utility pilot: 2026-10-06

A37-dimensional numerical mask-morphology correction was subsequently fitted,
with32 fit,16 calibration and32 separate evaluation images (80 total, no failed
extractions). The frozen PedVision networks were not fine-tuned. A fitted
age/sex-only control selected zero correction. On the same32 evaluation cases,
baseline MAE6.171271months and within6 16/32 compared with morphology MAE
9.291175 and within6 15/32; P95 increased14.700651 to20.718679months.
Six cases were corrected but seven previously within6 failed. This correction
was rejected and production unchanged. Results were reproduced from saved
coefficients and fit-only normalization; aggregate receipt and full subgroup
table are in the owning training ledger's completed age-utility section.

This negative result applies to a small-development-set ridge correction using
mask statistics, not all localized-image learning. Some younger cells gained
six-month hits while older cells worsened; support is only four per age/sex cell.
Neither targeted young-age benefit nor physician-level anatomical segmentation
is established. Do not use evaluation truth to choose a clinical gate. Mask
fragmentation, small sample support and absent texture/physeal measurements are
possible limitations, not proven explanations. No sub-six-month qualification.

## Single-output base-model follow-up completed: 2026-10-06

The authorized follow-up removed the second-age correction and trained one
EVA02 age head with optional sex-conditioned8x8 spatial attention and capped
inverse-square-root age/sex resampling. All12,611 existing training images were
accounted for;11,355 fit and1,256 train-calibration, four arms, eight epochs.
Backbone remained frozen. Each arm performed1,424 optimizer steps with verified
parameter updates, but calibration selection retained epoch0 in every arm.
All selected checkpoints reproduce827/1,425 within6 and MAE6.612327months.
Age/sex subgroup errors are unchanged; no production deployment. This is a
negative result for this adaptation, not evidence against full encoder learning.
Original training exposure of the calibration subset limits selection validity.

DHA metadata audit found1,384 rows, including22 female/32 male under24months
and99 female at204..228months, versus38/53 and45 current training images.
These are candidate additional annotations, not imported or verified new images.
Two zero-age labels and the1,384-versus1,383 publication count need reconciliation;
image rights, quality and cross-dataset deduplication remain intake prerequisites.
Full results, sampling replay, source links and aggregate receipt paths are in
the owning training ledger's completed single-output adaptation section.
