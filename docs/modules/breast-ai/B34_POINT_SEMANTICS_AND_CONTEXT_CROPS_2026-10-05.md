# B34: Model-point semantics and context crops

Date: 2026-10-05. Status: physician interpretation and implementation contract
recorded; source inspected. Documentation only, no inference, fit or runtime change.

## Owner clarification

The physician accepts multiple marks on and around a calcification as useful region
localization. Each displayed model dot is not necessarily an independent microscopic
calcification, its exact center or its boundary. Nearby points may describe support
around one focus. A crop containing that neighborhood can help assess morphology.
Do not prioritize eliminating these accepted surrounding marks merely to make the
overlay smaller. This clarification does not reverse B33's explicit false-mark
adjudication for the 13 cyan edge flags or the three earlier reported errors.

## Observed implementation versus hypothesis

Inspected protected research sources under P:
`build_eight_case_point_comparison_20261005.py` and
`physical_peak_extraction_20261005.py`.

The frozen generator subtracts a Gaussian-smoothed image (sigma 3 pixels) from its
canonical native input. It extracts regional maxima above 0.006 in that residual,
within the existing valid-intensity mask, applies 0.1 mm physical peak suppression,
then retains proposals using the frozen FPN score cutoff 0.000316227766. Plateau
handling and suppression do not prove one candidate per anatomical calcification.

Thus the proposal stage explicitly uses local intensity contrast/high-frequency
response, not a direct spatial-gradient magnitude threshold. The physician's idea
that signal transitions contribute to surrounding marks is plausible, but the exact
cause is not established. Multiple local residual peaks, image processing/texture and
the learned score could contribute. Source inspection cannot reveal what every learned
feature represents. No causal attribution or contour-oversegmentation claim is made.

Separately, the viewer's circles and squares are display glyphs, not segmentation
masks. This display fact does not exclude multiple actual model coordinates around a
single focus. Keep those two effects distinct.

## Consequences for morphology and evaluation

- Model-point count is candidate/output burden, not a count of independent lesions.
- An unmatched prediction is not automatically a false positive or a new lesion.
- Existing one-to-one 0.2 mm point matching remains a reproducible localization
  endpoint; do not relabel its historical denominator as lesion-level sensitivity.
- Retain native pixels around each candidate and broader neighboring-candidate context
  for morphology. Preserve crop origin, pixel spacing, input identity and candidate
  membership; do not rescale away fine detail or infer anatomy from marker geometry.
- If points are grouped to propose a crop, grouping is a region proposal, not a claim
  that every included point is one lesion or shares one morphology. Avoid automatically
  merging adjacent distinct calcifications or discarding accepted neighboring support.
- Exact punctum segmentation can be a later auxiliary experiment when evidence shows
  it helps. It is not a mandatory prerequisite to crop-based morphology classification.
- Learn morphology from reviewed image/cluster descriptor labels with missing/mixed
  classes handled explicitly. The original location dots alone do not supply those
  labels, and brightness profiles alone do not establish a BI-RADS morphology.

## Next action

Continue the B29 source/label crosswalk and native context-crop preparation, using the
existing accepted localization as input. Compare compact detail-plus-context descriptor
models when labels are ready. Preserve the detector and its accepted neighborhood
marks; add contour refinement only as an evidence-driven comparator. All prior
patient-level split, independent validation and deployment gates remain unchanged.
