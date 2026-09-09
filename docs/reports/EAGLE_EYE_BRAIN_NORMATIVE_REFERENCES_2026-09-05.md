# Eagle Eye Brain: age/sex reference evidence and integration

Reviewed 2026-09-05. This document contains no examination identifiers or measurements.

## Decision

Published, age- and sex-conditioned normative brain models exist. A single table
of normal volumes is not an adequate substitute for an applicable conditional
distribution. None of the references reviewed here has been qualified as a direct
adapter for our current SynthSeg 2 standard-profile posterior measurements.

The UI/report integration is implemented, but numeric normative scoring and age
curves remain unavailable. Selecting a published candidate does not enable it.
No claim is made that downloading its weights establishes clinical compatibility.

## Sources and suitability

| Reference | Published evidence / capability | Implementation consequence |
|---|---|---|
| [CentileBrain, Ge et al.](https://pubmed.ncbi.nlm.nih.gov/38076938/) | Published framework used 37,407 healthy individuals, ages 3-90, with sex-specific models. The study evaluated nonlinear age and global covariates. | Strong candidate for regional subcortical volumes using its expected FreeSurfer pipeline; cortical thickness and surface area are separate outputs, not our cortical parcel volumes. |
| [CentileBrain source and weights](https://github.com/CentileBrain/centilebrain) | Public R model objects and instructions. Instructions require FreeSurfer >=5, DK cortical thickness/surface area and Aseg subcortical volumes. The current instructions describe over 40,000 individuals, whereas the cited publication reports 37,407; do not silently treat these as the same version. | Pin model revision, verify transformations, covariates, residual distribution, feature order and age domain. Shared anatomical names are insufficient for substituting SynthSeg posterior estimates. |
| [Lifespan BrainChart, Bethlehem et al., Nature 2022](https://doi.org/10.1038/s41586-022-04554-y) | Sex-stratified lifespan centiles using distributional GAMLSS models; public fit objects and out-of-sample procedures. | Useful for precisely defined global phenotypes and curves, with site effects. Does not automatically provide a compatible reference for every current regional parcel. |
| [BrainChart implementation](https://github.com/brainchart/Lifespan) | FIT/BOOT objects for GMV, WMV, subcortical GMV and ventricles; transformations and population versus study-specific curves are explicit. | Preserve age/volume transformations and handle new-site uncertainty. Repository states CC BY-NC-ND 4.0; commercial redistribution/adaptation is not assumed authorized. |
| [Brain MoNoCle, Imaging Neuroscience 2025](https://doi.org/10.1162/imag_a_00438) | Normative morphology platform with individual/group centiles and z-scores, regional/hemispheric metrics and multi-site handling; published age range 5-95. | Its feature extraction and site adaptation must be matched. It is not a drop-in SynthSeg posterior-volume calculator. |
| [SLIP pediatric clinical charts](https://pmc.ncbi.nlm.nih.gov/articles/PMC10623207/) | Published pediatric clinical-control charts include SynthSeg+ processing and GAMLSS out-of-sample centiles. | Particularly relevant evidence for clinical MRI, but pediatric domain, SynthSeg+ settings, phenotype definitions and scanner handling must be reproduced. Not a validated adult reference for this tool. |

Additional emerging pediatric application:
[leukodystrophy normative modeling](https://www.medrxiv.org/content/10.64898/2026.05.22.26353512v1.full.pdf)
uses recon-all-clinical/FreeSurfer 7.4.1, SynthSeg+ QC and scanner-conditioned
GAMLSS. Treat this preprint as supporting research, not an installed clinical model.

## Download evidence

The following official CentileBrain files were downloaded for local research at
revision `a532b6ff89ccd5fba3846b77b13a175fb9283c68`:

- `models/MFPmodels_subcorticalvolume_female.rds`: 2,725,781 bytes;
  SHA256 `9a5b9bd5bb68e03ab19d4fc41794ba1e6c31ac1fcc2d677933c3dfd547a8a110`.
- `models/MFPmodels_subcorticalvolume_male.rds`: 2,393,816 bytes;
  SHA256 `eaecda1cd6701c3b0129f9ddee89761e1bcb11407964fd0c7e116a5579ca0883`.
- Official instructions PDF and README.

Files and the download manifest reside in ignored
`generated-files/brain-volumetry/normative-research/`. Hashes identify the downloaded
bytes; they are not an independent publisher signature. R objects were not executed,
installed as runtime providers or redistributed in an installer. The repository API
did not identify a CentileBrain license; downstream product-use terms still need
resolution. Patient data were not uploaded to any site.

## What is implemented in the workstation source

- Immutable `BrainDemographics`: age at examination in years, sex or unknown.
  No assumed age, no automatic sex inference, no substitution from a reference PDF.
- Published candidate inventory and explicit unavailable/applicability reasons.
  Scores remain null and curve arrays empty for every unqualified candidate.
- GUI context is captured before dispatch to the existing background worker.
  Normative selection/demographics are stored in the job result and PDF/HTML.
- Default report now includes local orthogonal image evidence, bilateral volume,
  % ICV and signed asymmetry tables alongside separate posterior/binary tables.
  Montage uses physical orientation, handles oblique grids and never fetches images.
- `Report from completed analysis` regenerates PDF/HTML into a separate folder.
  It verifies the original source checksum, preserves the measurement job and never
  reruns segmentation. Failed exports do not publish `report_result.json`.
- `Open PDF report` is enabled only when the worker reports an existing PDF.

This is an internal tool of existing Eagle Eye, not a new installer module or
configuration family. No new package dependency was introduced. Automatic PACS
identity binding, live source-workstation acceptance and release delivery remain
outstanding.

## Remaining work for numeric centiles and age curves

1. Select a specific provider/version with usable product terms. For the near-term
   adult route, reproduce the required FreeSurfer feature pipeline instead of
   silently relabeling SynthSeg volumes; alternatively establish a paired-data
   calibration or train a representative SynthSeg-specific reference.
2. Implement the pinned provider in an isolated local worker and compare against
   upstream examples using nonpatient fixtures. Record features, units, model
   transformations, age domain, global covariates and new-scanner policy.
3. Qualify distributional calibration on representative data. ICV percentage is
   not interchangeable with statistical ICV covariate adjustment. Three correlated
   reconstructions of one examination cannot train or validate a normative model.
4. Generate conditional centile curves from the actual fitted distribution and
   plot the observed value only after applicability succeeds. Compute Z using
   the provider's documented method; do not assume all distributions are Gaussian.
5. Define any T-score's reference and convention explicitly. Do not confuse an
   age-adjusted Z, a standardized 50+10Z display, a young-adult T-score, or brain age.

## Verification

63 focused synthetic tests pass (43 existing + 20 new), including age validation,
missing/out-of-domain context, unqualified reference rejection, asymmetry sign and
zero denominator, local PNG embedding, oblique evidence, and report regeneration
immutability/failure behavior. All 462 plugin mirror pairs match; no AI Imaging
mirror additions were required. The actual local examination was rendered through
the updated report writer and all eight PDF pages inspected. No repeat inference,
live workstation launch, full-suite pass, release or clinical validation is claimed.

## Subsequent implementation update

The earlier unavailable-only state is superseded for an explicit native FreeSurfer **research** route. Clinical qualification remains false. The pinned R models were executed with synthetic data; separate tables and age curves are implemented. Current portal instructions require CombatGAM site correction, which is not implemented here, and portal numerical parity is unverified. See [reference setup](../modules/EAGLE_EYE_BRAIN_REFERENCE_SETUP.md) for current status, prerequisites and limitations. This update does not qualify the SynthSeg estimator or enable clinical patient centiles.

## Region-specific adult norms and requested 90% interval

[Potvin et al. 2016](https://pubmed.ncbi.nlm.nih.gov/27165761/) provides 26 regional
subcortical outcomes including brainstem, with age/sex/eTIV/scanner covariates.
The public workbook from [PMC5094268](https://pmc.ncbi.nlm.nih.gov/articles/PMC5094268/)
was downloaded, hash-pinned and extracted without macros. Its local numerical
adapter and adjacent PDF range/score/flag rows are implemented. The compatible
estimator is FreeSurfer 5.3, adult ages 18-94; this is not a SynthSeg adapter.
The [2019 correction](https://pmc.ncbi.nlm.nih.gov/articles/PMC6660460/) changes
predictor-importance estimates, not regression coefficients. See the setup document
for source equations, distinction between Z_OP and Student t, and the deliberate
use of percentile-consistent P5/P95 rather than the workbook's original 95% limits.

The [cortical companion study](https://pubmed.ncbi.nlm.nih.gov/28512057/) also models
cortical volumes, thickness and surface area in 2,713 healthy adults (18-94) using
FreeSurfer 5.3. Its coefficients and mapping are not installed in this adapter.
Cerebellar and pediatric norms remain unresolved for the current estimator.

A recent [brainstem-containing lifespan resource](https://zenodo.org/records/22035817)
was downloaded for research review (CC BY 4.0; examples excluded from extraction).
Its associated manuscript is a preprint; it has not been substituted for the
peer-reviewed Potvin reference or qualified for patient reports.
