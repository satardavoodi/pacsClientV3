# B30: Directional exterior-background evidence

Date: 2026-10-05. Status: implemented and tested as a research feature; no deletion
enabled, no clinical promotion. Extends B29 following the owner's observation that
the exterior side of a skin boundary differs from internal fat.

## Hypothesis and implementation

Use directional context rather than distance alone: border-connected low signal in
one direction, sustained tissue signal in the opposite direction. Internal dark
regions disconnected from the image perimeter do not count as exterior. Out-of-image
samples are unavailable, never fabricated air. This is an image-background proxy;
normalized mammography pixel values are not calibrated air density or CT HU.

Sixteen rays use physical row/column spacing. At least three rays must consistently
sample exterior background, with opposite rays consistently sampling tissue.
The background threshold is 0.01 on the existing canonical native high-byte input.
A separate experimental compactness guard checks whether the center exceeds every
sample on a 0.14 mm ring by more than 0.006. Both are fixed exploratory rules,
not trained classifiers. Connected padding/background may confound actual air;
no DICOM padding-aware anatomical mask or scanner-independent cutoff is claimed.

V1 uses 0.5/1/2 mm rays and found zero flagged points. Inspection showed no qualifying
rays at the three reported errors. V2 changes only the ray distances to 1/2/4 mm,
with the opposite intensity step measured at 4 mm. This adaptive follow-up used the
same exposed examples; it is not independent validation. Both receipts are retained.

## Actual results

Frozen B25 manifest and B28 feedback hashes were checked. All eight original source
hashes and polarity/rescale assumptions were checked before reading native pixels.
No neural inference or model fitting occurred. Denominator is 1,519 displayed model
points with 116 original matched supports and three physician-reported wrong marks.

| Rule | Flagged points | Reported wrong points flagged | Original matched supports flagged | Other points flagged |
|---|---:|---:|---:|---:|
| V1 directional exterior context | 0 | 0/3 | 0/116 | 0 |
| V2 directional exterior context | 16 | 3/3 | 0/116 | 13 |
| V2 context plus noncompact response | 5 | 1/3 | 0/116 | 4 |

V1 had 19 unavailable points. Unavailable is not normal. The compactness restriction
misses two of the three reported errors, illustrating that some erroneous boundary
predictions also have compact local peaks. Exact feature arrays and per-case counts
stay on protected storage. Counts concern original fixed point pairing, not lesion
sensitivity, cluster specificity or a recalculated matching endpoint.

The directional feature separates these three reported errors from the original
matched positives better than B29's simple 1 mm band, which flagged one matched
support. However, the other 13 points are not proven false positives. B26 judged
most additional detections real, so removing them conflicts with the preservation
objective until directly adjudicated. Three points from one region do not represent
three independent negative cases. No generalized improvement percentage is justified.

## Verification and artifacts

Under protected root P (`C:/AI-PACS-Datasets/breast-review/point-review-20261003`)
and the established Linux research root R:

- `air_context_20261005.py`, `test_air_context_20261005.py`,
  `audit_air_context_20261005.py`, `air-context-audit-20261005/`.
- `air_context_v2_20261005.py`, `test_air_context_v2_20261005.py`,
  `audit_air_context_v2_20261005.py`, `air-context-v2-audit-20261005/`.

Each output directory contains protocol/code/manifest/feedback hash bindings,
aggregate results and private feature arrays. Five synthetic tests passed for each
version: directional edge response, near-skin compact peak preservation, internal
dark-region rejection, image-boundary unavailability, anisotropic axis consistency
and invalid input checks (some checks share a test method). Linux system Python was
used with existing dependencies. V1/V2 CPU audits took 6.50/6.56 seconds respectively;
these are feature-audit runtimes, not end-to-end model latency. No production code,
GUI, original annotation, checkpoint or detection threshold changed.

## Decision

### B31 follow-up: narrow band AND directional evidence

On 2026-10-05 the owner clarified that only a 1-2 mm edge band should be considered,
and only with a strong air/tissue difference. The cached B29 distance and B30 V2
directional flags were intersected at both 1 mm and 2 mm; both yield exactly 16
flags: three reported errors, zero original matched supports, and 13 other points.
All 16 existing directional flags already lie within the 1 mm approximate silhouette
band. Narrowing to these distances therefore does not resolve the remaining 13.
This tests the existing relative-signal rule, not a newly calibrated contrast cutoff.

Protected P artifacts: `audit_air_band_intersection_20261005.py` and
`air-band-intersection-20261005.json`. Exact input hashes, case IDs and array lengths
were checked; no new inference, fitting or original-data changes occurred. The result
does not establish that removal is harmless. Keep review-only status until the other
points are assessed and broader near-boundary positives are preserved.

Intensity caveat: do not apply CT's air HU value (-1000) to mammography. Mammography
pixel relationships, polarity and presentation processing must be respected; use
source-appropriate relative signal evidence. See the DICOM
[Mammography Image Module](https://dicom.nema.org/medical/dicom/2026a/output/chtml/part03/sect_C.8.11.7.html).

Retain directional exterior context as an additional second-stage review feature.
Do not enable automatic suppression. Do not increase compactness thresholds on this
single error region. Next compare true near-skin calcifications and confirmed edge
artifacts in a broader reviewed training set; review the 13 additional flagged points
if a suppression experiment is pursued. Continue morphology preparation separately.
