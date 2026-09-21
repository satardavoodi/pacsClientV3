# Eagle Eye WMH percentile readiness

## Outcome

The current source workflow can open the brain lesion input form. This does
not mean that age/sex WMH percentiles are available. No patient percentile was
calculated in this investigation, and no clinical release was validated.

## Preferred matching reference

Boccali et al., Diagnostics 2026;16:2460,
https://doi.org/10.3390/diagnostics16152460.
The full article and supplement are retained in the local research directory.
The public materials describe acquisition-specific GAMLSS/Johnson SU models
and SPM12 TIV normalization but do not provide the fitted objects or the full
numerical CDF needed by the current implementation. No downloadable fitted
model was located in the public searches on 2026-09-15. This is an availability
finding, not proof that the authors cannot provide one.

Required implementation inputs: fitted model/quantile grid, preprocessing and
sex coding, exact SPM12 TIV procedure, LST-AI threshold/version compatibility,
synthetic reference outputs, and distribution terms. The author request draft
is `generated-files/wmh-reference-research/model-request-email.md`; it is not
sent. Author correspondence address was verified in the publication XML.

## Alternative with published numeric quantiles

de Kort et al., Neurobiology of Aging,
https://doi.org/10.1016/j.neurobiolaging.2024.11.006.
Table 2 publishes total WMH p5/p10/p25/p50/p75/p90/p95 values for males and
females at five-year ages from 40 to 85. These are normalized MNI-152-space
volumes, not native lesion volumes. The methods remove voxels outside a
30-percent probabilistic white-matter mask after spatial normalization.

The local LST-AI rigid registration does not perform head-size normalization.
Its output filename containing `mni` is insufficient evidence of compatibility.
Do not apply Table 2 directly to native volume, replace the transformation
with a scalar assumed ICV, infer an exact percentile from sparse quantiles,
or extrapolate ages outside the supported numeric table.

The authors' public registration implementation was located at
https://github.com/Meta-VCI-Map/RegLSM, commit
`b53b017720df3f46fb7423b870feaec5aeb371e9`. Its tree was inspected and retained
locally; its executables were not installed or run. It contains registration
parameters and templates, but locating it alone does not reproduce the
normative image-processing contract or validate a patient percentile.

## Completion gates

1. Acquire a reproducible reference and preserve its provenance/version.
2. Implement compatible normalization in a cancellable background worker.
3. Verify output against reference-author synthetic cases and image geometry.
4. Review segmentation and normalization for the current private test case.
5. Wire reference status and results into the report, keeping unsupported
   ages/protocols explicit rather than substituting adult or other models.
6. Test the live source workflow and offline installed asset resolution.

No PHI, real patient fixtures, or clinical results belong in this document.

## Reference extraction update

The user accepts explicitly identified cross-method reference estimates; this
does not establish calibration or permit presenting estimates as exact scores.

Table 2 of de Kort was extracted to
`generated-files/wmh-reference-research/de-kort-table2.csv`: 20 sex/age rows,
140 numeric quantiles, with source and CSV SHA-256 provenance in the adjacent
metadata JSON. Rows were checked for completeness, unique sex/age keys, and
monotonic quantiles. These values are research inputs, not yet wired into the
patient-report runtime. Prefer this large multicohort reference for a compatible
spatially normalized volume; do not equate a simple ICV ratio with its nonlinear
spatial normalization and WM atlas filtering.

Kilinc et al., Stroke 2024;55:2863-2871,
https://doi.org/10.1161/STROKEAHA.124.046731, supplies a complementary reference
for WMH fraction (100 times WMH volume divided by ICV). The study includes
5,402 participants and 11,465 scans, not 11,465 independent participants.
The PDF was retrieved through Chrome at the university repository and saved
locally as `rotterdam-svd.pdf`; Figure 3 was rendered and visually inspected.
The methods specify natural logarithms and sex-stratified curves. Differences
in segmentation and ICV estimation remain relevant when using SynthSeg ICV.
Visual curve comparison can support an approximate percentile band, not a
machine-calculated exact percentile. A graph-derived grid of 112 values (two
sexes, eight ages from 50 to 85, seven quantiles) is now stored in
`rotterdam_curve_data.py`. These are traced Figure 3 values, not fitted model
coefficients. The source PDF is retained for research;
do not redistribute its copyrighted figures as product assets.

Reference priority depends on the metric: de Kort has the larger and more
diverse cohort, while Rotterdam matches the WMH/ICV ratio definition more
directly. Cohort size alone is not evidence that a reference is better calibrated
for the current population or algorithm. Routine runtime implementation and
clinical acceptance remain pending for exact calibrated percentiles.

## Implemented approximate SVD reporting

`wmh_fraction.py` computes candidate volume / same-examination SynthSeg ICV,
and candidate volume / disjoint posterior parenchymal volume. `enrich_svd`
retains the denominator measurements with the spatial assessment. The report
recomputes the ICV fraction and rejects stale volumes before reference lookup.
The graph uses linear interpolation in natural-log units between five-year
age knots, with no age extrapolation. A 0.1 log-unit reading allowance widens
bands near boundaries; this is not a confidence interval or a bound on method
bias. No exact percentile, Z-score, diagnosis or automated Fazekas grade is
generated. LST/SynthSeg versus Rotterdam method differences remain explicit.

Verification: 57 focused reference/lesion/context tests passed. A saved-case
12-page PDF was regenerated using the production report writer and Windows
fonts. Plugin parity: 462 pairs match. The running source test server responds,
but a refreshed live GUI acceptance pass for this new reporting branch remains
pending; a service-level PDF run is not a live GUI pass.
