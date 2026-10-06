# B58: Inspect spatial intensity surfaces before another classifier

Date: 2026-10-06. User requests a direct comparison of the intensity pattern inside
source-annotated Mass, Focal Asymmetry and Asymmetry boxes, retaining image X/Y
coordinates and signal as a third axis. This is descriptive source-data inspection,
not a new classifier, training result or independent accuracy evaluation.

## Purpose and distinction from B57

[B57](B57_SPATIAL_MORPHOLOGY_EXPERIMENT_2026-10-06.md) compressed source regions into
32 proxies and failed its improvement gate. B58 first preserves the spatial signal
and inspects it alongside the source crop. A one-dimensional histogram describes
value frequency but cannot show whether bright pixels form a coherent central body,
separate islands or a traversing ridge. Signal height is not anatomical depth or
calibrated tissue density. No class template is assumed correct before inspection.

The original source labels Focal Asymmetry and Asymmetry are kept distinct for this
analysis, rather than the pooled family target used in B50-B57. Those labels remain
publisher annotations, not new physician adjudication or proof of view correspondence.

## Selection and display contract

Select up to six distinct common-fitting studies per group before looking at their
surfaces or model outcomes. Restrict the first comparison to VinDr to reduce source
processing confounding; CBIS is not assumed to have interchangeable photometry or
label semantics. This small sample is an exploratory inspection, not an exhaustive
audit of either dataset or a representative clinical population.

Bind native DICOM bytes, original reference box and row identity. Preserve native
analysis arrays and validity masks. Derive display signal using a fixed image-wide
normalization and shared plot limits, not separate ROI contrast stretching that
would force unlike regions to appear alike. Surface plotting may reduce sample
density for rendering, but must disclose it and keep X/Y aspect and pixel axes.
Show the two-dimensional crop, contour view and row/column signal profiles alongside
the surface to avoid interpreting perspective occlusion as anatomy.

## Descriptive analysis contract

No classifier, optimized cutoff or development-case selection. Use simple declared
spatial measurements alongside intensity quantiles: X/Y correlation at native and
relative lags, robustly normalized adjacent variation, upper-quartile adjacency,
and box-centered central/peripheral contrast. The box center is not a segmented
mass center. Record group ranges and overlap rather than treating a median difference
in a small selected pool as a diagnostic rule. Preserve size, processing and masking
limitations. Pixel spacing must be verified before making physical-scale claims.

An exact pixel-permutation control retains the histogram while changing spatial
arrangement. This demonstrates why the proposed spatial representation contains
information missing from a plain histogram; it does not prove class separation.

## Evidence and result

Protected artifacts: `P/b58-spatial-surfaces-20261006/`, with source staging under R.
Completed 18 native boxes from 18 distinct common-fitting studies, six per source
label. Seed58 selection preferred native long axes of 150-600 pixels before viewing
model outcomes or surfaces. Source hashes and all 36 array/panel hashes verified.
Rendering took 27.35 seconds; this is not a serving benchmark. No fitting ran.
The `index.html` gallery includes all crop/surface/contour/profile panels and three
contact sheets. Native arrays are retained. Plot strides are disclosed; measures use
native arrays. B50 image-wide 1st/99th percentile normalization and common 0-1 limits
are used, not independent ROI stretching.

| Median descriptive measure | Mass | Focal Asymmetry | Asymmetry |
| --- | ---: | ---: | ---: |
| Box-center minus annulus signal | 0.137 | 0.051 | 0.097 |
| Adjacent X variation / IQR | 0.095 | 0.132 | 0.138 |
| Adjacent Y variation / IQR | 0.094 | 0.132 | 0.150 |

Some Mass examples have stronger, smoother central bodies, compatible with the user
hypothesis. However all observed class ranges overlap (57/57 pairwise comparisons
across 19 measures including size/validity). This establishes no diagnostic cutoff
and does not rule out multivariate discrimination.

Visual inspection of all contact sheets found broad raised centers in Mass
002/005/006 but more complex patterns in 003/004. Focal Asymmetry 007-010 show
ridges/valleys, while 011 also has a broad bright center; Asymmetry 016 supplies
another counterexample to bright-plateau-equals-Mass. These are source annotations,
not new clinical adjudication.

Exact shuffling preserved all 18 histograms while reducing X neighbor correlation
from approximately 0.927-0.990 to -0.007..0.008. Spatial arrangement adds information
missing from histograms; this does not demonstrate diagnostic class separation.

All sources are FOR PRESENTATION, not calibrated cross-image density. Upper clipping
reaches 7.91%, 9.51% and 12.50% in individual Mass, FA and Asymmetry crops. Flat tops
may reflect normalization. Pixel spacing is mostly absent; units remain pixels.
View counts differ (Mass 3 CC/3 MLO, FA 1 CC/5 MLO, Asymmetry 2 CC/4 MLO); density C
dominates. Box center is not a segmented core; tight boxes can truncate the boundary.
This small size-selected cohort is not representative of all lesion presentations.

Next compare these same boxes with unclipped native signal and surrounding context
before another classifier. Retain B50 splits and a matched baseline for subsequent
experiments. No accuracy or improvement claim is made. B55 review remains pending;
B50 weights and clinical/calcium inference remain unchanged.

Evidence: `aggregate.json`, `descriptive-summary.json`,
`independent-descriptive-review.md`, `synthetic-histogram-receipt.json` and protected
source receipts. Protocol SHA256:
`00954f8c6302914b172dda6f0700a6d82d113ca37bb083194508f2064e53979a`.
