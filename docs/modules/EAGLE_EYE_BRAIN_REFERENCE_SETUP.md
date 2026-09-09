# Eagle Eye Brain reference runtime

## Current workstation default: published volBrain intervals (2026-09-06)

The normal UI now selects `volbrain`; earlier reference adapters are retained only
for reproducibility of historical research jobs. The completed-job report worker
and segmentation worker both attach the same local reference implementation.
Original measurements and existing reports are preserved.

Source: https://github.com/volBrain-net/AssemblyNet#normative-ranges
Pinned revision: `6bc4383c812314879aa22e96781936e2cb21a298`.
Scientific reference: Coupe et al. (2017), https://doi.org/10.1002/hbm.23743.

The three publisher files `bounds_female.csv`, `bounds_male.csv`, and
`bounds_general.csv` are installed in writable User Data under
`ai/eagle_eye/brain/references/volbrain`, with README, license and manifest.
They total approximately 1.55 MB. The reference operation needs no FreeSurfer,
R, Docker or Linux. Source-code SHA-256 constants reject modified tables.
To provision another authorized local installation, obtain these files from the
pinned revision, retain the accompanying notices, and place them in that same
User Data directory. Missing tables produce an unavailable reference, never a
fallback to the previous scores. The ordinary GUI performs no file/network I/O
when a reference is selected; reading happens in the worker.

There are 27 explicit name correspondences: brainstem, third/fourth ventricles,
and bilateral deep nuclei, ventricular labels and white matter labels. A name
correspondence is not proof that the two segmentation protocols have identical
boundaries. No speculative cortical crosswalk or aggregate interval is used.
Ranges are displayed next to measurements, including medial temporal regions.

Ages 1-90 are supported; fractional ages linearly interpolate adjacent rows.
Website interpolation equivalence is unverified. Outside this domain or with
missing age, no adult substitution is made. Recorded unknown sex uses the
publisher's general table. Percent-ICV intervals are converted using this job's
own ICV, never the other service's ICV. These are published 95% intervals, not
90% intervals. Lower/median/upper values cannot supply exact centiles or Z/T
scores; prior scores are cleared, not repurposed. Outside-interval labels are
comparison results, not diagnoses. Cross-method qualification remains pending.

Private comparison audits reproduced the supplied report's 54 rounded bounds
for 27 mapped regions. This validates table extraction for that report, not
population validity or segmentation accuracy. The prior local CentileBrain
adapter showed unresolved compatibility problems; this is not a finding that
the underlying published CentileBrain study is invalid.

### Packaging boundary

Only adapter code is part of the source change. Reference CSVs stay in local
User Data and are not included in installer assets. The AssemblyNet repository
states research/non-commercial restrictions for its software; separate rights
to redistribute its CSVs commercially have not been established. This local
implementation does not establish customer redistribution permission. Consult
the retained upstream notices before a commercial release.

### Measurement review boundary

A PDF's few MNI-space colored slices do not permit full voxelwise overlap or
boundary accuracy assessment. A paired review needs the exact submitted T1,
native-space volBrain structures labelmap, label dictionary and any transforms.
Agreement between axial/coronal reconstructions measures consistency, not
independent accuracy. Do not adjust volumes to force a normal interval.


## Independent numerical audit: reference interpretation unresolved (2026-09-06)

The local unharmonized MFPR path was checked using the publisher's 30-row public
synthetic female subcortical demonstration workbook, not patient uploads. All 420
predictions matched both CRAN mfp's predict.mfp link method and an independent
model-matrix/coefficient multiplication (maximum observed difference zero).
Template feature order matches the adapter's interleaved left/right order.

Nevertheless, 414/420 demo observations fall outside the computed Gaussian 90%
residual bands. For example, the demo's median left hippocampal observation is
4039.40 mm3 while the median raw model prediction is 1781.147 mm3. Synthetic demo
data are not a healthy validation cohort, so these counts are a reproducible
compatibility warning, not a measured false-positive rate. The audit rules out a
simple disagreement with predict.mfp; it does not establish equivalence with the
publisher's complete portal preprocessing/harmonization and scoring pipeline.

Do not interpret the previous single-case agreement in interval position as
normative validity. Both measurement pipelines can receive similarly biased
reference predictions. Existing research scores and bands remain unqualified and
must not become clinical normal/abnormal flags. No arithmetic correction or
patient-specific adjustment was made to force scores into a normal range.

Audit artifacts are in ignored User Data under ai/eagle_eye/brain/validation:
public-demo-reference-audit.csv, audit_reference.R, and the publisher's synthetic
demo workbook. No patient data were sent to an external service. The remaining
task is parity with the full source scoring workflow or a separately validated
reference implementation, not changing measured regional volumes.

Sources: https://github.com/CentileBrain/centilebrain and
https://github.com/cran/mfp/blob/master/R/predict.mfp.R.

## Explicit SynthSeg exploratory route (2026-09-06)

The optional selector `SynthSeg + CentileBrain (exploratory; unvalidated)` now
calculates 14 subcortical model projections from source-verified SynthSeg 2.0
posterior volumes and SynthSeg ICV without invoking FreeSurfer or requiring its
license. It is wired into both new analyses and report regeneration; automatic
age routing is unchanged. Age 3-90 and recorded sex remain required.

The output explicitly identifies unvalidated cross-pipeline use and disables
diagnostic flags. Original measurement rows retain unavailable clinical scores.
The separate research report gives projected ranges, Z, standardized 50+10Z and
Gaussian approximate percentiles with the actual estimator, not a false native
FreeSurfer attribution. The model is still unharmonized and not clinically
qualified; redistribution rights remain independent of this development route.

A direct local invocation completed for the selected examination (14 regions).
The independent native FreeSurfer reconstruction remains in progress. No final
customer build or new patient PDF was produced in this step. R and the pinned
models are still runtime dependencies. Deep patient output paths are handled by
running R in a short private User Data cache directory and copying the resulting
artifacts to the patient destination. Temporary cache files are removed afterward.

## Verified FreeSurfer installation (2026-09-06)

Ubuntu-22.04 is installed. The user-supplied Ubuntu22 FreeSurfer DEB was
verified against the publisher's MD5 bfe85dd76677cfb7ca2b247b9ac6148e.
FreeSurfer 7.4.1 was installed with apt/dpkg at /usr/local/freesurfer/7.4.1.
The older Ubuntu-18.04 FreeSurfer installation was not modified.

Ubuntu could not reach package repositories directly. Windows downloaded the
official Ubuntu InRelease and package indexes; gpgv verified repository signatures
with Ubuntu's archive keyring. Index SHA-256 values and all 141 dependency package
SHA-256 values were checked before offline installation. Following interruption,
dpkg --configure -a completed pending package configuration successfully.

The user's license is stored in the ignored Eagle Eye brain runtime directory,
referenced by reference-runtime.json, and passed through FS_LICENSE by the worker.
License contents were not logged. AI-PACS check_runtime passed. recon-all -version
reported freesurfer-linux-ubuntu22_x86_64-7.4.1-20230614-7eb8460. mri_convert
successfully converted the bundled mni305 template with the configured license;
this check used no patient images. Setup logs and verification helpers are in the
user's Downloads/freesurfer-dependencies directory.

This supersedes the missing-package/license prerequisites below. It verifies
installation and licensed execution, not a completed patient reconstruction or
clinical qualification of normative scores. The customer server architecture
remains proposed, not deployed.

## Windows runtime prerequisite repair (2026-09-06)

The signed Microsoft WSL 2.7.13 MSI was successfully installed through an
administrator-approved helper. Its first attempt failed with MSI code 1622
(installation log creation); staging the signed MSI and log under a dedicated
Windows Temp directory resolved this. VirtualMachinePlatform enabling returned
success without a restart indication. `wsl --version` now succeeds and reports
2.7.13.0 with kernel 6.18.33.2-2. No automatic restart or AI-PACS restart occurred.

The now-visible pre-existing Ubuntu-18.04 distribution contains an incomplete
FreeSurfer 7.1.1 CentOS build at /usr/local/freesurfer, lacking /bin/tcsh and with
no license in either standard FreeSurfer location. It was inspected read-only;
it is not a replacement for the pinned 7.4.1 runtime. Ubuntu-22.04 installation
was launched with --web-download and --no-launch; it has not yet been verified
as ready. Installation logs and status are under the user's LocalAppData
AI-PACS/BrainReference/setup directory.

The official 7.4.1 Ubuntu22 DEB endpoint timed out on this host, including an
IPv4 retry; the registration page also timed out in Chrome. The package was
not downloaded. A valid user FreeSurfer license.txt is still required. These
facts supersede the earlier statement that WSL itself remains unavailable;
native reconstruction and normative patient scoring are still not ready.

## Age-based reference priority (2026-09-06)

The first/default UI reference selection is now `Automatic age priority
(reference review)`: ages 3-90 inclusive select the CentileBrain candidate;
outside that interval select BrainChart for applicability review. Missing age
selects no reference. The original DICOM examination age is preserved. This
policy does not start reconstruction or activate either unqualified scorer.
BrainChart remains unavailable until its model-specific age domain, regional
definition, measurement pipeline and site calibration are verified. Downloaded
weights and age routing alone are not evidence of clinical validity.

The supplied examination age is within CentileBrain's domain. Its unavailable
scores arise from pipeline/qualification prerequisites, not age. A fallback
must not be used to bypass those prerequisites. Explicit existing research
routes remain separately selectable. Six boundary/missing-age guards fail
before the policy and pass after it.

## Pediatric reference investigation (2026-09-06)

SLIP (Radiology 2023, doi:10.1148/radiol.230096, PMC10623207) includes
532 clinical controls aged 28 days to 22 years and evaluates SynthSeg+ alongside
FreeSurfer. A 17-year-old is within that reported cohort; being outside Potvin's
adult domain does not mean no pediatric literature exists. Cohort limits alone
do not establish a fitted model's valid scoring domain for every region.

The publisher repository `BGDlab/clinical_brain_analysis` was pinned at
`41af9be3f454b6af71f6e066e5a94dd3f10d247c`. All 17 source files were downloaded
and verified by Git blob hash, with SHA-256 recorded in the ignored local
`user_data/ai/eagle_eye/brain/references/slip/<revision>/manifest.json`.
The repository contains extraction, training and evaluation scripts but no
fitted R model objects. Its build-your-own workflow requires cohort data; one
patient cannot supply a normative training cohort. Obtain the publisher's fitted
SynthSeg+ models, verify exact phenotype/estimator, age conversion, scanner
handling and numerical parity before enabling scoring. The README contains a
days-per-year conversion inconsistent with standard chronology; do not copy it
uncritically into the application. No author contact or patient upload occurred.

The existing SLIP selector now explains the verified cohort and missing fitted
models. Actual DICOM examination age remains unchanged. No age-15 cutoff and no
20-30-year surrogate age band were introduced. An out-of-domain source remains
unavailable until a compatible source exists. Pediatric norms are not inferred
from puberty or adult mean volumes. No new patient PDF or scores were generated.

## Combined applicability report (2026-09-06)

The reference selector now includes `Regional reference applicability review
(no scoring)`. This lists CentileBrain, Potvin subcortical and cortical references,
BrainChart, and pediatric cerebellar models with their sources and current
compatibility limitations. It explicitly rejects age extrapolation and never
turns reference discovery into a clinical qualification flag. It does not run
new segmentations or activate missing adapters.

The completed local ten-page report was regenerated from its verified source job,
preserving DICOM identity and all measured volumes. Its reference page records
the adult age-domain exclusion and SynthSeg/native-FreeSurfer incompatibility.
No new normal range or Z/T score was attached. All ten pages were rendered and
visually checked; the generated PDF remains an unsigned review report.

Table padding is now four pixels to accommodate the longer regional tables with
the report worker's fallback font metrics. The expanded synthetic full-atlas PDF
guard fails with the old six-pixel padding in an isolated offscreen process and
passes with the change. Combined reference and PDF checks: 70 passed, including
the local R acceptance lane. Explicit Arial font loading was used for the local
standalone regeneration so text is embedded and extractable.

## Persistent offline library (2026-09-06)

The primary selected reference remains CentileBrain MFPR, based on the published
37,407-participant benchmark and subsequent population validation
(https://pubmed.ncbi.nlm.nih.gov/38076938/ and
https://pmc.ncbi.nlm.nih.gov/articles/PMC13187733/). No single downloaded reference
has been established as valid for every current SynthSeg report volume.

All six sex-specific MFPR model files, templates, instructions and harmonization
scripts (21 files, 53,496,678 bytes) are now archived under the ignored persistent
`user_data/ai/eagle_eye/brain/references/centilebrain/<revision>/` directory.
Each download was verified against the pinned Git blob and recorded with SHA-256.
R successfully opened all six files: 14 subcortical, 68 thickness and 68 area
models per sex. Only the existing subcortical adapter is active.

`references/runtime-models/` holds the existing hash-pinned runtime models and
the separate Potvin calculator assets. The development reference configuration
now points there; a backup, configuration copy and installation README are stored
in `references/`. Scoring uses local files, with no online reference lookup or
automatic updates. Include this directory in data backups; update absolute paths
when relocating and use `AIPACS_BRAIN_REFERENCE_CONFIG` for explicit configuration.

Verification: 39 CentileBrain/Potvin tests passed with
`AIPACS_TEST_REFERENCE_RUNTIME=1`, including real R calculations. No runtime
source code, patient score, clinical qualification flag or report was changed.
The native FreeSurfer, harmonization and qualification limitations below remain.

## Current state (2026-09-05)

The workstation source includes a selectable `CentileBrain with native FreeSurfer
(research)` route. It reconstructs a fresh copy of the verified job T1 with native
FreeSurfer 7.4.1, reads 14 bilateral Aseg volumes and native eTIV, and runs pinned
CentileBrain MFPR models locally. R is installed for the current Windows user;
the two model objects are downloaded and hash-checked on every scoring invocation.

This is **not a clinically qualified reference provider**. The current upstream
portal applies CombatGAM harmonization. Our provider does not reproduce that
step or claim numerical equivalence to the portal. Its optional research pages
explicitly identify unharmonized estimates as unsuitable for patient interpretation.
The public synthetic demo produces large positive residual scores, which is further
reason to require upstream numerical parity and site calibration before clinical use.
Do not explain those deviations as disease or assume harmonization alone explains
them. No patient reference scores have been generated in this checkout.

## Model definition

- Revision: `a532b6ff89ccd5fba3846b77b13a175fb9283c68`.
- Source: <https://github.com/CentileBrain/centilebrain>.
- Model files: `MFPmodels_subcorticalvolume_female.rds` and male equivalent.
- Ages: 3 through 90 inclusive; sex must be recorded female or male.
- Features in publisher template order: L/R thalamus, caudate, putamen, pallidum,
  hippocampus, amygdala and accumbens. FreeSurfer 7.4.1 LUT calls label 10
  `Left-Thalamus` and label 49 `Right-Thalamus`.
- Predictions use the stored GLM formula and coefficients with `type='link'`.
  The saved fit omits its family object; identity-link Gaussian models make link
  and response predictions equal. Do not refit, substitute an intercept or guess
  fractional-polynomial transformations.
- Z: observed native volume minus prediction, divided by the root mean square
  of the model's stored training residuals.
- T: `50 + 10 * Z`; not a young-adult reference score.
- Gaussian-approximation percentile: `100 * pnorm(Z)`; not a verified portal centile.
- Curves: every integer age 3-90 at fixed sex and eTIV; prediction plus/minus
  `qnorm(.975) * RMSE` is a residual reference band, not a confidence interval.
- No scores for cortical parcel volumes, ventricles, cerebellum or brainstem.
  Cortical thickness and surface-area models require a separate implementation.

## Runtime configuration

The local file `generated-files/brain-volumetry/reference-runtime.json` is ignored.
Installed deployments must set `AIPACS_BRAIN_REFERENCE_CONFIG` to their local
configuration file. Its fields are:

```json
{
  "rscript": "C:/path/to/R/bin/Rscript.exe",
  "models": "E:/path/to/pinned/reference/models",
  "distribution": "Ubuntu-22.04",
  "freesurfer_home": "/usr/local/freesurfer/7.4.1",
  "license": "C:/path/to/license.txt"
}
```

The R worker uses base R only; no additional package is needed at runtime.
On this host R 4.6.1 was installed under the user's local AI-PACS BrainReference
directory from the official, validly signed CRAN installer. `mfp` and `numDeriv`
were also installed for development inspection; neither is required by the worker.
The WSL 2.7.13 x64 MSI was downloaded and its Authenticode signature was valid.
Its silent installation returned 1603. The shell was not elevated. WSL remains
unavailable; a restart was not attempted. Check the installation logs if elevated
installation also fails; exit 1603 alone does not identify a unique cause.

## Complete the Linux prerequisite

1. Follow Microsoft's administrator installation procedure:
   <https://learn.microsoft.com/en-us/windows/wsl/install>.
   Use Ubuntu 22.04 for the pinned FreeSurfer package. Schedule any required
   restart with the workstation operator; never restart the clinical workstation
   automatically. The signed MSI is staged in the ignored normative-research folder.
2. Install the official Ubuntu 22 FreeSurfer 7.4.1 DEB using Ubuntu's package
   manager, including its dependencies. Package extraction is not a supported
   substitute for installation. Official page:
   <https://surfer.nmr.mgh.harvard.edu/fswiki/rel7downloads>.
   Download: <https://surfer.nmr.mgh.harvard.edu/pub/dist/freesurfer/7.4.1/freesurfer_ubuntu22-7.4.1_amd64.deb>.
   Publisher MD5: `bfe85dd76677cfb7ca2b247b9ac6148e` (download integrity, not a
   cryptographic publisher signature). The server timed out from this host and
   Chrome during this session; the DEB is not downloaded or installed.
3. Obtain the user's FreeSurfer license from
   <https://surfer.nmr.mgh.harvard.edu/registration.html> and set its local path.
   A license path was requested from the user and is still pending. Never copy
   license contents into a repository, report or log.
4. Verify the actual distribution name, installation path, Python 3 and
   `recon-all -version`. Update the local configuration to match. The worker
   rejects a FreeSurfer version other than 7.4.1.
5. From the Brain tab, choose the native FreeSurfer research reference and either
   run a new analysis or regenerate a report from its original `result.json`.
   DICOM demographics take precedence. Reconstruction may take hours, uses two
   threads and stays headless. Review its own reconstruction before interpretation;
   the existing Slicer scene depicts SynthSeg, not the new FreeSurfer segmentation.

## Isolation and failure handling

Reference work runs in the existing background executor. The source T1 hash is
checked before and after copying. FreeSurfer uses a fresh subdirectory and fixed
argument lists; source jobs are not changed by report regeneration. Scores retain
source, Aseg and reference-model hashes plus FreeSurfer/model versions.
Windows updates a heartbeat while a dedicated Linux process group runs. Cancel,
controller loss or timeout ends that group. Linux watchdog execution still needs
live WSL acceptance; synthetic Windows guards do not establish that behavior.
R execution uses the existing Windows owned-process abstraction and timeout.
Failed exports publish a FAILED marker and never publish a successful report result.

## Verification and release boundary

Run the five focused Brain test files directly with pytest. Set
`AIPACS_TEST_REFERENCE_RUNTIME=1` to additionally execute both real pinned R models
on synthetic inputs at ages 3, 40 and 90. This verifies numerical execution,
range/order/unit contracts, Z/T arithmetic and curve consistency, not upstream
portal parity or clinical accuracy. The official female synthetic example also
ran locally and produced a six-page research PDF whose pages were rendered and
inspected. The real patient report was not rescored.

Before release: verify real FreeSurfer execution and cancellation; resolve product
use terms for reference weights; establish exact upstream preprocessing/scoring
parity and local calibration; package the `.R` worker, Linux `.py` worker and
external runtime configuration; complete installer/runtime parity and clinical
validation. No installed AI-PACS executable or release package was changed.

Focused verification completed: 92 tests passed, including six actual R-model runs. All 462 existing plugin mirror pairs match. No full repository suite or release build was run.

## Adjacent reference ranges

The PDF places a normal-range availability column beside global, regional and medial temporal SynthSeg measurements. These remain unavailable because no matching clinically validated reference exists. Separate native FreeSurfer research tables now use the requested central 90% Gaussian residual band (P5-P95) at the exact examination age, in cm3, next to the measured volume. The band is calculated from the stored prediction and residual RMSE, not interpolated from integer-age curves or combined across hemispheres. Invalid/nonphysical bounds are unavailable. It is explicitly not a clinical normal range or confidence interval. Earlier 95% PDF artifacts are historical previews; regenerate to obtain the revised threshold.

## Potvin adult regional reference (2026-09-05)

The peer-reviewed [Potvin subcortical reference](https://pubmed.ncbi.nlm.nih.gov/27165761/)
contains 26 outcomes, including brainstem, bilateral hippocampi/amygdalae/thalamus,
basal ganglia, ventral diencephalon, ventricles, corpus callosum and subcortical GM.
It does not provide cerebellar or cortical parcel norms. Ages are 18-94; the
measurement pipeline is native FreeSurfer 5.3 default recon-all. Age, sex, native
eTIV, scanner vendor (GE/Philips/Siemens) and field strength (1.5T/3T) enter the model.
DICOM report context now retains Manufacturer and MagneticFieldStrength alongside
examination age/sex. Missing values are not guessed; raw vendor strings require
explicit normalization before a future automatic scoring integration.

The [public calculator](https://pmc.ncbi.nlm.nih.gov/articles/PMC5094268/), supplementary
mmc2.xlsm, was downloaded from Europe PMC and read without executing macros.
`tools/dev/prepare_potvin_reference.py` verifies its SHA-256, extracts the 26 coefficient
vectors and inverse design matrices, and writes a local model JSON. The runtime pins
that JSON hash. Data article attribution: Potvin, Mouiha, Dieumegarde and Duchesne,
2016, CC BY 4.0. [The 2019 corrigendum](https://pmc.ncbi.nlm.nih.gov/articles/PMC6660460/)
corrects predictor-importance estimates, explicitly leaving regression models unchanged.

Local preparation (requires openpyxl; use the bundled document Python):

```text
python tools/dev/prepare_potvin_reference.py <downloaded-mmc2.xlsm> <local-models.json>
```

`potvin.score_research` accepts exact native region keys, explicit estimator, age,
sex, native eTIV, vendor, field strength, local JSON, Rscript, and a new output folder.
It is an internal research calculator, not an automatic FreeSurfer reconstruction
path. The UI lists it as a candidate; selecting it alone produces no patient scores.
Neither SynthSeg nor FreeSurfer 7.4.1 is silently accepted. No clinical adapter is
qualified, and the actual supplied examination has not been rescored with this model.

### Statistical contract

Use the workbook centering, polynomial/interaction terms, coefficient vector and
inverse design matrix. Prediction SE is sqrt(MSE * (1 + leverage)). The source
percentile uses Student t with n-2 degrees of freedom. Requested P5/P95 limits invert
that same distribution, ensuring score and flag agreement. This deliberately differs
from the original workbook's 95% prediction limits, whose critical t uses n-11.
Z_OP = residual / sqrt(MSE), the source standardized effect size. T = 50 + 10 Z_OP
is a display rescaling, not a young-adult reference score or the Student t statistic.
The six log models operate on log10(volume); inverse-transformed prediction is a
central prediction/median, not an arithmetic mean. Flags use unrounded percentiles
below 5 or above 95 and mean outside-reference-range, not a disease diagnosis.

Hypothetical illustration only: age 56, Siemens 3T, native eTIV 1500 cm3, brainstem
21 cm3. Female P5-P95: 17.983-24.068 cm3, Z_OP -0.0138, T 49.8621,
percentile 49.4507. Male: 18.428-24.514 cm3, Z_OP -0.2550, T 47.4504,
percentile 39.9510. These are assumed inputs, not data from the user's examination.

Verification: 111 focused Brain tests passed, including local R execution of all
26 Potvin outcomes, log-scale interval checks, P5/P95 inversion, outside-range
flags, incompatible pipeline/age rejection, and existing CentileBrain tests.
The hypothetical two-page PDF uses the application report renderer. Both final
pages were visually reviewed. No actual patient score, installed app or release was changed.


## Current verification record (2026-09-06)

The 73 focused reference, report, medial-temporal and study-workflow guards pass
with Qt's Windows platform. The headless offscreen platform on this host renders
Arial as missing-glyph squares; its PDF text guard fails. Repeating the same
guard with the native Windows font platform passes. This is recorded rather
than weakening the readable-PDF assertion. Private completed-job regeneration
produced 12 pages with 27 references, visible evidence, readable text, running
header/footer and no blank pages. All pages were rendered for visual inspection.
462 existing mirror pairs match; this source module has no pre-existing payload
mirror, so the canonical mirror tool added no files. No production build or live
workstation UI acceptance was performed in this change.


The broader Brain suite is not green: 153 passed, 8 optional local-model checks
skipped, and 2 PDF guards failed in the combined process (organized furniture /
normal-range text and legacy multipage header extraction). Windows COM diagnostic
0x8001010d also appeared during combined Qt tests. The focused 73-guard run and
the independently generated/read/rendered 12-page report pass. Do not describe
this as full-suite or live-app acceptance; combined-process Qt/font isolation
remains unresolved. No assertion was relaxed and no production release was made.

## Expanded published coverage (2026-09-07)

The default remains volBrain. The prior local research models are not used as a
fallback. Coverage is now 57 native measurements: 29 existing tissue/deep-region
cross-method comparisons (including newly added left/right cerebellar GM), and
28 explicitly contextual cortical analogues. The latter are 14 bilateral DK
regions: pars opercularis, pars triangularis, pars orbitalis, frontal pole,
temporal pole, inferior temporal, transverse temporal, superior parietal,
precuneus, cuneus, lingual, pericalcarine, entorhinal and parahippocampal.

Cortical ranges have an asterisk in the measurement table and an `Atlas analogue
only` position in the reference appendix. They are NOT matched SynthSeg normal
limits and receive no below/within/above classification, Z/T score or percentile.
The exact publisher source row and mapping status are retained per assessment.
The final source suffix determines side; publisher `Left ..._right` naming is
retained verbatim rather than silently corrected.

Protocol review sources:
- https://mindboggle.info/braincolor/docs/BrainCOLOR_cortical_parcellation_protocol.pdf
- https://surfer.nmr.mgh.harvard.edu/pub/articles/desikan06-parcellation.pdf

These sources support candidate anatomical counterpart names, not validated
interchangeability of measurements. Split/merged territories (including superior
frontal, middle frontal subdivisions, insula, cingulate subdivisions and lobar
sums) are not assigned partial-region or summed-endpoint intervals. Marginal
reference endpoints cannot be added to obtain a reference interval for a union.
Existing numerical measurements are never changed to fit reference bounds.

Cortical report lookup now uses native `ctx-lh/rh-*` keys rather than the deep
structure `left/right ...` convention. Entorhinal/parahippocampal contextual ranges
also appear in the medial temporal section. Unsupported cortical entries display
`Atlas differs`; missing global references remain unavailable.

Verification: two pre-change guards failed; 21 focused report/reference tests pass.
All three installed sex tables validate with 57 unique required source rows each.
Two private reports were regenerated without segmentation, each 19 pages; all
pages rendered and layout reviewed. All 462 existing mirror pairs match. No live
app restart, clinical qualification or release build was performed.

## Large-deviation highlighting and scientific citation (2026-09-07)

Measured values are red only when more than 25% beyond the nearest published
interval endpoint: (value-upper)/upper above, or (lower-value)/lower below.
Exactly 25%, 10% departures and in-range values are not red. This user-selected
attention threshold is not statistical significance or a validated diagnostic
cutoff. Contextual cortical analogues may also be highlighted, retaining the
asterisk and explicit atlas-mismatch limitation. Missing intervals cannot flag.
Regional measured cells, reference appendix and medial temporal values share the
same helper. Original volumes and reference endpoints are not changed.

The scientific-method page now names Coupe, Catheline, Lanuza and Manjon (2017),
Towards a unified analysis of brain maturation and aging across the entire
lifespan: A MRI analysis. Human Brain Mapping 38:5501-5518,
doi:10.1002/hbm.23743. The publisher explicitly identifies this as the paper
covering the images used for its CSV reference ranges. Numerical endpoints still
come from publisher CSVs, not a reconstructed curve from the paper. AssemblyNet
(2020) and Desikan (2006) are cited separately for segmentation and atlas
provenance, without claiming validation of SynthSeg against these intervals.

Seven threshold/scientific-render guards failed before implementation. The focused
reference, patient report, lobar and medial-temporal selection passes 28 tests.
Three individual reports and a serial comparison were regenerated from preserved
measurements; no inference rerun or clinical diagnosis was introduced.
# Current policy: volBrain only (2026-09-07)

This section supersedes every historical setup instruction below. Do not install
or reactivate retired reference adapters. The active implementation is
`volbrain_reference.py`; its three CSV hashes and publisher revision are pinned.
The workstation selector exposes only volBrain. Old reference IDs are rejected,
and saved research scores are suppressed by the current renderer until the report
is regenerated. Original measurement jobs and PDFs remain unchanged.

The numeric source is the published AssemblyNet age/sex interval tables at revision
`6bc4383c812314879aa22e96781936e2cb21a298`. The population citation is Coupe et al.,
Human Brain Mapping (2017), https://doi.org/10.1002/hbm.23743. The associated
segmentation paper is https://doi.org/10.1016/j.neuroimage.2020.117026.

Use actual age 1-90, recorded sex (publisher general table when unknown), linear
interpolation for fractional ages and the current job's ICV to convert percent
ICV to cm3. Never clamp age, sum marginal bounds or infer Z/T scores from bounds.
29 noncortical mappings and 28 explicitly marked cortical anatomical analogues
are available. Analogue bounds do not provide matched cortical normal cutoffs.
Red is strictly more than 25% beyond the nearest endpoint, not a significance test.

Retired scorer source files and their dedicated tests have been removed. Dedicated
old reference data/configuration were moved to a reversible non-runtime archive
after execution review rejected permanent folder deletion. R and FreeSurfer were
removed through their official uninstall/package managers after Windows inference
succeeded. Only volBrain remains in active reference storage. Retired assets are excluded from the new
payload allowlist. Their retirement does not establish that the original research
publications were scientifically invalid.

Customer calculation uses portable Windows SynthSeg, shared headless Slicer and
volBrain CSV files; it does not invoke FreeSurfer reconstruction, R or WSL.
Redistribution rights for the CSV files and clean Windows acceptance still need
documented evidence before commercial packaging. See
[customer delivery](EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md).

## Historical record below: not an installation guide
