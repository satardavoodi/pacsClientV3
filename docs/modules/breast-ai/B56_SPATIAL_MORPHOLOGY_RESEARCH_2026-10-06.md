# B56: Central density continuity and radial tissue architecture

Date checked: 2026-10-06. Literature review and experiment design, not a model fit
or implemented feature extractor. User proposes intensity-surface patterns to
separate a coherent mass core, interspersed tissue and architectural distortion.
Continue the [B55 review](B55_MODEL_ASSISTED_REVIEW_2026-10-06.md); its model outputs
remain unchanged. Keep B50 as the research comparator.

## Evidence and limits

| Primary source / method | Relevant evidence | Transfer limit |
|---|---|---|
| [Huo et al., 1995, radial edge-gradient analysis](https://aapm.onlinelibrary.wiley.com/doi/abs/10.1118/1.597626) | Quantifies spiculation around an approximate mass outline; reported mass classification Az 0.88 for one measure | Mass lesion classification, not our Mass/AD/asymmetric-family task; publisher abstract/search evidence, full text not inspected |
| [Banik et al., 2010, Gabor/phase portraits](https://pmc.ncbi.nlm.nih.gov/articles/PMC3046672/) | Orientation fields, curvilinear structures and convergent pattern analysis characterize AD; texture/fractal analysis adds context | Historical interval-cancer images; not a ready three-class checkpoint |
| [Rangayyan et al., 2013, oriented patterns](https://pubmed.ncbi.nlm.nih.gov/24022326/) and [method/results](https://pmc.ncbi.nlm.nih.gov/articles/PMC3856936/) | 106 prior mammograms from 56 interval-cancer cases plus 52 images from 13 normal cases, leave-one-patient-out; 80% sensitivity at 5.6 false positives/patient in the detailed result | Detection FROC, not typing accuracy; false-positive burden remains substantial. This is related methodological lineage, not independent modern replication |
| [Vijapura et al., 2018, DBT morphology](https://pubmed.ncbi.nlm.nih.gov/30240306/) | Central lucency, central mass and symmetric/asymmetric spiculation were examined as separate features | DBT benign-versus-malignant AD study; cannot transport its endpoint or rates to 2D typing |
| [Local-view deep classifier, 2025](https://www.frontiersin.org/journals/oncology/articles/10.3389/fonc.2025.1601929/full) | VinDr ROI results report AD recall 0.0417 on 24 examples despite per-label accuracy 0.9941; asymmetric-label recall 0.1772 on 79 | Different model, splits and label set; not a paired comparison or evidence our model is superior |

Search included older explicit morphology methods and recent mammography work.
No licensed model assets were acquired, no external clinical images were uploaded,
and no paper's accuracy was claimed as locally reproduced. Some full-text retrievals
returned access checks; rely only on retrieved primary abstract/result text for
those entries. Reusable code/checkpoint/license readiness has not been established.

The [2024 RSNA AD review](https://pubs.rsna.org/doi/10.1148/rg.240024) describes
radiating strands and focal retraction, with overlapping tissue affecting visibility.
The relevant distinction is not a universal short-spicule/long-spicule cutoff.
Preserve central mass and distortion as potentially coexisting attributes.
Fat does not universally exclude a mass: [RSNA fat-containing lesion review](https://pubs.rsna.org/doi/abs/10.1148/rg.342135082)
describes encapsulated fat-containing masses. Dense normal overlap can also appear
coherent on a projection. Treat these signatures as probabilistic evidence.

## Translation of the user's idea into measurements

An intensity surface z=I(x,y) retains spatial arrangement; a one-dimensional
histogram loses it. The third plotting axis is signal, not anatomical depth.
Feeding a rendered perspective chart to the model introduces viewpoint artifacts;
compute descriptors or aligned maps directly from the image instead.

| Feature family | Candidate measurements | Intended question |
|---|---|---|
| Central support | Robust central-to-annulus contrast; high-signal connected-component persistence across thresholds; plateau occupancy | Is there a coherent central body rather than isolated brightness? |
| Internal organization | Multiscale local variance, spatial co-occurrence/run-length texture; low-signal channel connectivity | Is the center interrupted by lower-signal tissue-like channels? These are not validated fat segmentation |
| Radial architecture | Multiscale Gabor or Hessian ridge orientations, convergence toward candidate centers, angular dispersion, radial persistence/length | Are lines converging abnormally rather than simply crossing the ROI? |
| Core and surrounding ring | Central support jointly with radial-line strength, continuity and angular coverage | Distinguish a spiculated mass-like body from distortion without a definite core |

Use ridge tangents for line convergence; raw intensity gradients are normally
perpendicular to ridges. Do not confuse those orientations. Test possible centers
within the region rather than assume the annotation-box center is the lesion core.
Bounding boxes are not segmentation masks. Show the proposed core and line maps to
the physician before interpreting their anatomical meaning.

Use verified pixel spacing for physical scales and flag missing spacing; otherwise
report scale relative to ROI size. Respect valid tissue, source polarity and image
processing. [DICOM mammography modules](https://dicom.nema.org/medical/dicom/current/output/chtml/part03/sect_c.8.31.html)
and [ACR/AAPM/SIIM image-quality guidance](https://pmc.ncbi.nlm.nih.gov/articles/PMC3553374/)
distinguish image/display processing. Pixel signal is not a calibrated CT-like
tissue-density scale. Do not infer fat from a universal intensity cutoff or physician
window/level settings. Derive analysis from source images, not the review PNGs.

## Why this is not repeating the failed generic feature addition

B39 added coarse local/ring intensity and gradient summaries and reduced macro F1
from 38.28% to 36.86% on its older task. B44 tested calcium-feature transfer without
establishing a benefit. Neither result supports simply adding more histogram features.
The new hypothesis specifically retains spatial topology and radial orientation,
with separate core/ring evidence on the current AD-inclusive task. It remains untested.

## Selected bounded experiment

1. First implement a small deterministic extractor and inspect only fitting examples.
   Synthetic controls should separate a smooth bright core, interspersed channels,
   radial ridges, parallel ridges and a bright core with radial ridges. Check rotation,
   scale, monotonic intensity changes, boundary masking and center perturbation.
   Synthetic success is an implementation guard, not medical evidence.
2. On the fixed B50 groups, compare a compact regularized feature-only classifier,
   a matched B50 embedding classifier and that same classifier plus the small
   spatial-feature set. Fit all standardization/selection inside fitting partitions.
   Retain the original B50 checkpoint as an additional comparator; do not train
   a stacker on in-sample model scores without grouped cross-fitting.
3. Isolate core features, radial features and their joint contribution. Keep native
   input policy fixed; do not simultaneously introduce context384 or new CBIS AD
   supervision. Freeze feature list, regularization budget and operating tradeoffs
   before viewing development performance.
4. Report per-class precision/recall, AD-to-Mass and Mass-to-AD confusions, macro F1,
   paired patient/study uncertainty and CPU extraction latency. Audit dependence on
   scanner/density, calcifications/clips, vessel/skin edges and ROI geometry. No
   normal-study specificity can be inferred from these selected positive ROIs.
5. Stop if gain is inconsistent across grouped splits or trades away unacceptable
   Mass/family performance. Only then consider a learned morphology branch. The
   24 exposed physician cases are for explanation/correction, not the final test.

This low-cost discriminating experiment now precedes a broader architecture sweep.
It does not remove the need for B54 source-label adjudication or native-context
testing; those remain separate interventions. No new accuracy or CPU serving claim.

## Focused follow-up: an object-like body with partially visible boundary

User clarification on October 6 prioritizes the mass body and its boundary over
generic texture statistics. The proposed signature is a spatially persistent core,
partially traceable boundary and surrounding/interspersed lower-signal channels.
The owner's suggested 30-40% visible boundary is a hypothesis, not a verified
BI-RADS cutoff or measured fraction in our cohort. No hard threshold is adopted.

The [HL7 breast-radiology mass profile](https://hl7.org/fhir/us/breast-radiology/2020May/StructureDefinition-AbnormalityMass.html)
reproduces an ACR-attributed definition involving complete or partial outward
convexity and, for radiodense masses, greater central than peripheral density.
This is a historical implementation profile, not a claim to have inspected the
full current licensed ACR manual. The [ESR teaching examples](https://epos.myesr.org/poster/esr/ecr2015/C-1026/findings%20and%20procedure%20details)
illustrate focal asymmetry lacking a mass-like convex outline and containing
interspersed fat. These appearances support the hypothesis but do not define
histological fat from pixel values. A non-mass finding still occupies physical
tissue; 'no volume' means no demonstrated discrete space-occupying mass, not
literally zero anatomical volume or a proof based only on fat. Preserve the
two-projection requirement for a final focal-asymmetry designation.

### More directly applicable computational precedents

- [Eltonsy et al., 2007: multiple concentric layers](https://impact.ornl.gov/en/publications/a-concentric-morphology-model-for-the-detection-of-masses-in-mamm/).
  Layers around a focal region progressively decrease in average intensity.
  The study used CC views of 270 DDSM malignant cases, half for optimization
  and half testing. Reported malignant detection was 88% at 2.4 false marks/image;
  benign detection at that operating point was only 58.3% with 2.8 false marks/image.
  Its malignancy-oriented selectivity must not become our definition of all masses.
  This is mass detection, not validated Mass/AD/FA typing.
- [Gao et al., 2010: morphological component analysis plus concentric morphology](https://pubmed.ncbi.nlm.nih.gov/19906595/).
  Separates piecewise-smooth and texture components, then applies concentric-layer
  criteria. The published experiment used 100 malignant and 50 benign DDSM cases.
  This motivates a body/texture decomposition. For our task retain BOTH components:
  discarding texture could erase the lines needed to recognize AD. Do not borrow
  its sensitivity without matched false-positive and validation evidence.
- [Multilayer topographic mass analysis](https://pubmed.ncbi.nlm.nih.gov/9419667/).
  A Gaussian-bandpass candidate stage followed by multilayer topographic analysis
  is another precedent for interpreting the intensity surface as structured regions,
  rather than a single intensity threshold. Historical digitized-image detection
  results do not establish present three-way typing performance.
- [Rangarajan et al., 2023: isodense/obscure masses](https://pubmed.ncbi.nlm.nih.gov/37209125/).
  Combines explicit architectural/spiculation learning, opposite-breast information
  and intensity transformation. Supports retaining alternative evidence when the
  core or boundary is obscured. Its bundled cancer-detection intervention does not
  isolate the benefit of a core feature. A [correction record](https://pubmed.ncbi.nlm.nih.gov/37347431/)
  exists; no implementation or accuracy transfer is claimed from the abstract.

### Refined first experiment

Add an explicitly named **core-boundary-channel** block to the B56 prototype design:

1. Build a component tree from relative local intensity levels. Measure whether a
   connected body survives across levels, how its area grows, and whether its center
   remains stable. Nested components arise mathematically from thresholding, so their
   mere existence is not mass evidence; stability, shape and growth must discriminate.
2. Measure candidate boundary support as the fraction of contour arc with consistent
   normal-direction contrast across scales; retain obscured arcs as unknown. Record
   partial convexity, curvature changes and contour fragmentation without requiring
   a complete sharp ring or forcing an active contour to close around normal tissue.
3. Measure lower-signal channels inside and across the candidate body, separately
   from small noise holes, calcifications and external background. Call this channel
   topology, not a fat segmentation, until physician/source validation supports it.
4. Combine those measurements with the existing proposed radial-line block. A core
   with radial strands and strands without a definite core are distinct observable
   patterns; mixed or unresolved cases remain allowed.

Use native DICOM-derived inputs, robust relative signal normalization and physical
scale where reliable. Inspect candidate contours over the original image, not only
a 3D rendering. No unconditional bright-center gate: isodense/obscured and
fat-containing masses must stay eligible. Benchmark core-only, radial-only and joint
features under the existing fixed grouped protocol. Do not change the B55 physician
answers, model predictions or form in this literature-only follow-up. No extractor,
new predictions or performance gain has yet been produced by this refinement.
