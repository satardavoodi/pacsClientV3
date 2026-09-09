# Eagle Eye Brain volumetry

Current policy (2026-09-07): Brain and Lumbar are Eagle Eye features, with shared
Slicer supplied by the existing Advanced MPR runtime component. Brain now has a
portable Windows asset candidate. Only volBrain is an active reference. Consult
[active reference policy](EAGLE_EYE_BRAIN_REFERENCE_SETUP.md) and
[customer delivery](EAGLE_EYE_BRAIN_CUSTOMER_DELIVERY.md) before using any historical
setup or acceptance details below.

Implementation review: 2026-09-05. Version 0.1.0, source-development integration.
This is an embedded tool of the existing Eagle Eye application, not a new
installer-selectable module, configuration family or separately shipped model package.

## Scope and actual readiness

### Source-build end-to-end acceptance (2026-09-06)

Live-verified in the user-restarted development workstation: open a local brain
study, load original sagittal T1 MPRAGE, click Eagle Eye, enter the Brain chooser
directly, choose Whole Brain Segmentation, select/confirm the study's T1 series,
run SynthSeg and dedicated headless Slicer, generate the report, and export it
through Save PDF As to Downloads. Lesion Detection remains disabled/Coming soon.

The successful run produced 101 posterior-volume rows, 98 independently verified
Slicer binary segments, 8 QC values and a 10-page PDF in patient/study-scoped User
Data. From prepared T1 to completed result took 6.28 minutes on this workstation.
Exported PDF bytes match the stored report exactly. Patient, study, selected series,
age and sex match the selected DICOM source. Every page carries the brand, patient
ID and correct page count; all ten rendered pages were visually inspected. The
Brainstem numeric value and its column header have identical horizontal centers.
This verifies the application workflow, not clinical segmentation accuracy.

The first retry exposed Python launcher exit 103 (No Python at the external uv
base), despite that executable being readable from the agent environment. The
existing Python 3.8.20 base was copied into the ignored model bundle's
`python-base/`; `runtime/pyvenv.cfg` now points there. Its base files and changed
configuration are included in the integrity manifest. Original configuration and
manifest are backed up in `installation-backup-20260906/`. Local model imports
passed and the same running workstation then completed the full workflow. This
is a source-development runtime repair, not a release or installer validation.
Preserve the base files in future bundle manifests; relocating the source bundle
requires updating its interpreter home before revalidating the manifest.

The report retains review-required status. Normal ranges, centiles and Z/T scores
remain unavailable for the current SynthSeg estimator; the successful export does
not qualify the separate research reference providers. Earlier failed jobs remain
marked FAILED and were not substituted for the successful new run.

Organized DICOM report follow-up: complete jobs now use a deliberately paginated
report with running AI-PACS header, patient name/ID, page X of Y and review-status
footer. Sections cover patient/examination, global tissue volumes, image evidence,
subcortical/ventricular structures, cortical parcels, medial temporal review and
quality/reference/reviewer sign-off. Binary-mask measurements remain in the local
analysis artifacts as a separate estimator, rather than duplicating every row in
the patient-oriented summary. Oversized page content fails export instead of clipping.

DICOM input now supplies local report context from PatientName, PatientID,
PatientBirthDate, PatientSex, PatientAge, StudyDate, AccessionNumber and InstitutionName.
Age uses examination date, with PatientAge as an approximate fallback; available
DICOM values take precedence over manual entries. Mixed per-series demographics
or conflicting T1/FLAIR identities are rejected. Identifiers remain separate from
clean model inputs and are not logged or sent externally. NIfTI-only inputs do not
acquire an invented identity. This is local DICOM binding, not automatic active-PACS
patient binding or report insertion.

Older completed jobs can acquire DICOM report context only after exact pixel and
geometry agreement with their stored T1 input, plus agreement with any previously
bound examination identity. Regeneration preserves the original job and creates a
separate report. All seven pages of a real local regenerated report were inspected;
synthetic tests cover identity consistency, exam-age arithmetic and every-page
header/footer. The report remains marked pending review/signature; no clinical
validation or automatic patient release is implied.

Age/sex report integration (2026-09-05): the Brain tab now captures optional age at
examination and sex, exposes published reference candidates with explicit
applicability limitations, and exports bilateral/asymmetry tables plus local
orthogonal segmentation evidence. Completed jobs can be reported again without
rerunning segmentation or changing their original measurements. See
[`Normative reference evidence and integration`](../reports/EAGLE_EYE_BRAIN_NORMATIVE_REFERENCES_2026-09-05.md)
for verified sources, downloaded CentileBrain weights, 63 passing focused tests
and the remaining provider/calibration work. Numeric centiles and age curves are
still unavailable; no published candidate is qualified for current SynthSeg volumes.

The requested protocol is full-head **3D T1-weighted / MPRAGE plus 3D FLAIR**,
confirmed by the user. Quantitative T1 maps are not this protocol. FLAIR is optional
for the current anatomy-volume workflow and does not drive a lesion model.

Implemented:

- A lazy **Brain Volumetry** tab in Eagle Eye. Opening the tab does not scan files,
  import TensorFlow/VTK or launch Slicer. Selected input paths and profile are
  snapshotted before work is dispatched to a single background worker.
- Explicit NIfTI or one-series classic DICOM input. Geometry validation rejects
  missing/duplicated slices, unsupported shear, non-finite/constant images and
  non-3D input. The operator confirms sequence identity and full-head coverage.
  This confirmation is not an automated QC measurement.
- Metadata-free local image staging, optional rigid FLAIR-to-T1 registration,
  an isolated SynthSeg 2.0 CPU command with parcellation and QC, and model-bundle
  integrity checking. No patient images are sent to an external model or website.
- A fixed, dedicated headless Slicer operation that imports the model labelmap,
  runs Segment Statistics, checks each volume against an independent voxel-count
  calculation in the labelmap geometry, and saves `.seg.nrrd` and `.mrb` artifacts.
- Separate posterior and binary-mask measurement tables, absolute units, posterior
  ICV percentages, QC scores, local CSV/JSON/HTML and workstation PDF export.
  Completion is published only after artifacts finish successfully. Errors leave
  a `FAILED` marker; partial outputs must not be used.
- A strict `BrainPlan.from_recommendation` boundary for future LLM proposals:
  standard/robust profile and 1-8 CPU threads only. No arbitrary Python, crop,
  label changes, patient paths, invented measurements or QC approval.

Not implemented or not established:

- Clinical validation of SynthSeg 2 on this machine. The four v2 models are now
  installed and each matches the official pinned FreeSurfer SHA256 and size.
  Bundle preparation exited 0. See the download recovery and verification sections
  below for the separate inference-test status.
- Automatic source-series selection from the active PACS study, patient identity
  binding or automatic report insertion into PACS. The tool intentionally produces
  standalone local review artifacts; it does not attach them to a patient record.
- Enhanced MR conversion: export with a qualified dcm2niix installation and choose
  NIfTI. The initial direct DICOM reader explicitly rejects multiframe objects.
- WMH/lesion segmentation, cortical thickness, longitudinal change analysis,
  automated coverage/motion QC, registration acceptance or clinical accuracy.
- Live LLM provider/tool dispatch. The typed recommendation boundary exists;
  no actual LLM is called and no claim is made that profile changes improve accuracy.
- A qualified normative reference model: **percentiles and Z-scores remain null**.
- Installer/model distribution, release promotion and live source-workstation UI
  acceptance. No installed AI-PACS executable was launched.

## Architecture and estimator identity

### Medial temporal report section (2026-09-05)

The default PDF/HTML retains general brain measurements and adds a dedicated
medial temporal / Alzheimer's-related imaging review section for complete results.
It lists bilateral hippocampus, entorhinal cortex, parahippocampal cortex, amygdala
and inferior lateral ventricle posterior volumes, side-specific % ICV and signed
asymmetry. Missing labels remain unavailable. Inferior lateral ventricle volume
is not treated as temporal-horn width. MTA scores remain explicitly not rated;
neither a volume-to-MTA conversion nor an Alzheimer's probability is implemented.

Three coronal levels are selected from the labeled hippocampal extent. Display-only
crops enlarge the region, with T1 above and hippocampal masks below. Original
measurements and masks remain unchanged. These are orthogonal LPS views, not
hippocampal-axis oblique MTA reformats. Full-volume review and appropriately oriented
coronal visual MTA assessment remain necessary. Atrophy is not disease-specific;
clinical context, cognition and appropriate biomarkers are outside this volume report.
Methods: [MRI dementia / MTA review](https://radiologyassistant.nl/neuroradiology/dementia/update)
and [2024 Alzheimer's Association criteria](https://doi.org/10.1002/alz.13859).

The existing authenticated local Slicer control bridge was found in
`resident_service.py`; the runbook still identifies LLM-facing MCP dispatch as
unimplemented/unverified, and no directly callable Slicer tool was exposed to this
agent session. This does not establish that no separate MCP installation exists.
No LLM provider or automatic adaptive rerun was added. The existing `BrainPlan`
allowlist remains the proposed boundary for model recommendations; an LLM must not
edit measured volumes, invent norms, assign MTA from volume, or self-approve QC.

Verification: 65 focused synthetic tests passed; 462 mirror pairs match. The
completed local examination was reported again without repeat segmentation, and
all nine rendered PDF pages were inspected. No clinical diagnosis, normative
qualification, live workstation acceptance or release is claimed.

`modules/ai_imaging/eagle_eye_brain/` owns planning, image preparation, orchestration,
process ownership, reporting and UI. `AiMainWindow` adds only a lazy tab factory.
The tool uses the current Slicer executable locator and Windows process-job owner;
it does not mutate the resident interactive Slicer scene, the Fast viewer, or the
Advanced viewer's in-process VTK state. It exposes no general execution server.
One Brain job runs at a time in the workstation process. Cancel/timeout closes only
the owned model/Slicer process tree. Registration stops on an iteration callback.

SynthSeg 2 output is at 1 mm isotropic resolution. Its `--vol` output estimates
volume from posterior probabilities and includes `total intracranial`; its final
parcellated labelmap has a different binary-mask estimator. Both are retained and
named. Do not silently substitute one for the other, multiply labels by input
voxel spacing, or add parent cortical totals to their own cortical parcels.
The FLAIR registration does not deform the T1 image used for volume inference.

The review scene uses the resampled T1 and result labelmap in matching geometry;
registered FLAIR is an additional review volume. A transform's numerical convergence
does not establish acceptable alignment, and the report states that review is needed.

Job directories use random IDs under `<user_data>/brain-volumetry`. The result
records cleaned-source SHA256, exact model source revision, bundle-manifest SHA256,
profile, Slicer revision and separate estimator tables. These local artifacts are
still sensitive medical images, even after metadata removal. Do not commit them,
upload them to research services or include them in diagnostics.

## Prepare the development model environment

The application remains on Python 3.13.5. Upstream SynthSeg's pinned legacy stack
is isolated under `generated-files/brain-volumetry/runtime`; it is never installed
into `.venv` or Slicer's embedded Python. This is a compatibility experiment, not
a qualified distribution of the legacy dependency stack.

Source revision: `BBillot/SynthSeg@2a2aa3bbfccb83f8253a51ca8b329b9938a2646d`.
Model identity source: official FreeSurfer annex pointers at
`8c1d37cb14593ec06931bbdfea7c955a4b584163`.

Preparation sequence (commands use already installed `uv`):

```powershell
uv python install 3.8
uv venv --python 3.8 generated-files/brain-volumetry/runtime
git clone https://github.com/BBillot/SynthSeg.git generated-files/brain-volumetry/SynthSeg
git -C generated-files/brain-volumetry/SynthSeg checkout 2a2aa3bbfccb83f8253a51ca8b329b9938a2646d
uv pip install --python generated-files/brain-volumetry/runtime/Scripts/python.exe -r tools/slicer/brain_requirements.lock
.\.venv\Scripts\python.exe tools/slicer/prepare_brain_volumetry.py --download-models
```

Do not rerun clone or overwrite an existing environment blindly. The present
checkout already has the source and Python environment. `uv python install` initially
reported a Windows minor-version-link error after extracting Python; directly
selecting the extracted `python.exe` successfully created the isolated venv.
The lock retains upstream pins but selects `tensorflow-cpu==2.2.0` instead of the
439 MiB GPU wheel because this initial adapter explicitly runs on CPU. GPU
qualification is a separate step; no CUDA capability is claimed.

Alternatively pass `--models <local-FreeSurfer-model-directory>` to copy the four
model files. The preparation tool checks their sizes and SHA256 against official
annex pointers, probes dependency imports, then hashes source, models, labels and
the isolated runtime into `manifest.json`. The application fails closed without
that manifest. There are no runtime downloads or automatic dependency installs.
For a separately prepared directory, `AIPACS_BRAIN_BUNDLE` selects the local bundle;
no new JSON feature-flag family is introduced.

After provisioning, first run a non-patient model smoke test and the full pipeline
on an approved de-identified validation dataset. A successful installation/import
does not establish a successful prediction or clinical accuracy.

## Normative reference decision

There is no universal fixed normal hippocampal-volume table transferable between
all segmentation engines. A qualified provider must pin population and age range,
sex coding, structure/atlas definitions, pipeline version, volume estimator, ICV
adjustment, scanner/site handling, model coefficients, license and validation record.
Missing covariates, out-of-range age or incompatible estimator must yield unavailable.
An LLM must not fill the gaps or choose a percentile that looks plausible.

Brain Charts is an important source for lifespan reference modelling. Its GAMLSS
centiles and site/study effects must be implemented using the published model and
the corresponding measurement definitions, not approximated with a global normal
distribution. Availability of its code does not qualify every SynthSeg subcortical
structure or an individual local scanner. The reference provider remains a separate
required research/calibration step; no coefficients were invented in this change.

## Extension selection and sources

Primary sources inspected on 2026-09-05:

- [SynthSeg source and usage](https://github.com/BBillot/SynthSeg): automatic anatomy,
  parcellation, QC, 1 mm output, robust option and optional preprocessing. HD-BET is
  not automatically prepended because SynthSeg accepts unstripped inputs.
- [FreeSurfer SynthSeg documentation](https://surfer.nmr.mgh.harvard.edu/fswiki/SynthSeg).
- [FastSurfer](https://github.com/Deep-MI/FastSurfer): alternative T1w engine; not
  installed, benchmarked or treated as interchangeable with SynthSeg.
- [SlicerNeuro](https://github.com/Slicer/SlicerNeuro): collection/meta-extension,
  not itself a segmentation engine or normative database.
- [SlicerFreeSurfer](https://github.com/PerkLab/SlicerFreeSurfer): import and review
  of FreeSurfer outputs; does not itself make a FreeSurfer reconstruction available.
- [SlicerNeuroSegmentation](https://github.com/HOA-2/SlicerNeuroSegmentation):
  editing and surface-guided cortical parcellation tools, not a one-click normative engine.
- [HDBrainExtraction](https://github.com/lassoan/SlicerHDBrainExtraction): HD-BET
  skull stripping wrapper, not hippocampal/basal-ganglia parcellation.
- [Slicer Segment Statistics](https://github.com/Slicer/Slicer/blob/main/Docs/user_guide/modules/segmentstatistics.md).
- [Brain Charts paper](https://www.nature.com/articles/s41586-022-04554-y) and
  [published code](https://github.com/brainchart/Lifespan).
- [volBrain tutorial](https://volbrain.net/tutorial): ICV-normalized measurements
  and age/sex-dependent normative bounds, used as product context rather than a
  downloadable interchangeable normative coefficient source.
- [Official FreeSurfer annex setup](https://freesurfer.net/fswiki/GitAnnex).

The custom Slicer extension manager is disabled by default. The existing
[extension compatibility guide](SLICER_EXTENSIONS_INSTALL_AND_CONTROL_GUIDE.md)
documents that extension computation and GUI compatibility are separate checks.
This Brain adapter uses verified core Segment Statistics and does not advertise
SlicerNeuro, HD-BET or NeuroSegmentation as installed.

## Verification and next acceptance steps

- `tests/code/ai_imaging/test_eagle_eye_brain.py`: **37 passed**, synthetic-only,
  including invalid plans, units/ICV, invalid CSV, image geometry, cancellation,
  no premature completion, lazy UI, escaped reports and actual PDF rendering/text.
  Classic MR, CT/2D rejection, slice gaps and identical-phantom FLAIR registration
  are exercised. The focused Brain/UI/startup/build-inclusion selection passed
  54 tests before the final additional FLAIR phantom guard.
- `tools/dev/run_brain_volumetry_probe.py`: real source-linked Slicer operation,
  oblique synthetic masks: **172.800009 and 86.400005 mm3**, expected 172.8 and
  86.4 mm3. `.seg.nrrd` and `.mrb` saved; process exit 0. Evidence:
  `generated-files/brain-volumetry/probes/synthetic-7w_efbel/slicer_result.json`.
- Existing Slicer control probe: load synthetic image and DICOM, threshold parameter
  changes, save/reload and measurements all passed, exit 0. Evidence:
  `generated-files/slicer-control-probe/a91992eb43334359b760ff016685db69/result.json`.
- Expanded first check: **58 passed, 1 failed**. Existing staged-build config parity
  fails for `patient_table_sort.json`; this change did not edit that file or stage.
  No release build was attempted to mask the unrelated stale-stage condition.
- Plugin mirror verification: **462 pairs match**. The mirror tool's add dry-run
  found no existing plugin parent for this core Eagle Eye subpackage. This is not
  a new optional catalog entry; no model bundle is included in an installer.
- Isolated CPU environment: **51 packages pass `uv pip check`**. TensorFlow 2.2.0,
  Keras 2.3.1, nibabel 5.0.1 and h5py 2.10.0 imports were verified. The GPU package
  was removed and the CPU stack installed cleanly to avoid overlapping modules.
- `tools/dev/run_brain_model_probe.py --legacy-v1`: a real neural inference smoke
  test passed on a generated 128-cubed phantom using upstream's included SynthSeg 1
  model. Output shape, finite labels and label vocabulary were checked (4 unique
  labels). Evidence: `generated-files/brain-volumetry/probes/model-smoke-7_618to3/probe.json`.
  This verifies engine execution only, not SynthSeg 2, parcellation, QC or anatomy
  accuracy. There is **no v1 fallback in the product workflow**. Without the flag,
  the probe requires the fully provisioned v2 bundle and exercises the Brain service.
- The standalone tab was rendered offscreen with no patient context. A synthetic
  PDF was visually inspected after rendering and contained extractable text.

Remaining acceptance: verify real model output and
all CSV label definitions; test T1/FLAIR pairs with known geometry and overlays;
validate on manual references/test-retest scans; connect a qualified normative
provider; wire restricted LLM tool dispatch; qualify active-study identity binding
and enhanced MR conversion; package the complete isolated runtime intentionally.
The human launches/logs into the source workstation for live UI acceptance.

### Chrome download follow-up (2026-09-05)

The user authorized using Chrome when direct downloads fail. The official
SynthSeg README's UCL model-folder link was opened through the Chrome connector;
Chrome returned `ERR_BLOCKED_BY_CLIENT`. The pinned standard-model FreeSurfer
annex URL was also opened in Chrome and returned `ERR_TIMED_OUT`. No browser
security controls were changed, and no new model download was found in the
user's Downloads directory. The four-model prerequisite remains unresolved;
this follow-up does not establish a successful SynthSeg 2 execution. A reachable
official source or locally supplied checksum-matching model directory is needed
to continue bundle provisioning.

### Model download recovery (2026-09-05)

The original author's replacement MIT ZIP link is published in
[SynthSeg issue 114](https://github.com/BBillot/SynthSeg/issues/114), also explained
in [PR 120](https://github.com/BBillot/SynthSeg/pull/120). Chrome opened this link,
but a completed browser download was not found locally. Direct MIT access reset
the connection. Issue 114 also describes recovering the four models from
`pwesp/synthseg:py38`. Only its four model layers were downloaded; the container
was not installed or executed. Each compressed layer's content hash was checked,
then only its exact regular model-file member was copied (no archive-wide extraction).
The existing preparation command subsequently verified all four extracted model
files against official FreeSurfer annex references and created `manifest.json`.

| Model | Bytes | Verified SHA256 |
| --- | ---: | --- |
| synthseg_2.0.h5 | 53079152 | f190bfd742f450ef3ca2c9df9ed4d2e0232b3a74471da5e51b7770bacdf80c3e |
| synthseg_robust_2.0.h5 | 214606800 | 7bc30bf5c3d204f20c4a6cb5a283aedbcab6af1de927cda783f59b67d19cb01c |

All four official reference hashes, including parcellation and QC, are recorded in
`generated-files/brain-volumetry/manifest.json`. Local model-download staging is
`generated-files/brain-volumetry/model-downloads`.

[SlicerFreeSurferCommands](https://github.com/SlicerCBM/SlicerFreeSurferCommands)
can run `mri_synthseg` through Slicer, but requires a separately installed FreeSurfer
7.3.2 or newer; its README documents testing on Debian with Slicer 5.2.2. This
does not establish Windows compatibility or replace model provisioning. The
current adapter uses native Windows isolated SynthSeg and headless Slicer, with
the report embedded in the workstation Qt UI. Full FreeSurfer and WSL were not
installed. WSL was confirmed absent. Neither is required for this current workflow.

Normative research follow-up: Potvin's subcortical norms use FreeSurfer 5.3 default
segmentation (2790 controls, ages 18-94), while CentileBrain uses specified
FreeSurfer-derived morphometry. Those estimators cannot be silently replaced with
SynthSeg posterior volumes. A complete normative route needs the matching feature
extraction protocol and applicability/calibration validation. Downloading software
alone cannot establish these requirements. T-score semantics remain unspecified;
no conversion or young-adult reference is invented.

### Successful v2 integration probe (2026-09-05)

`tools/dev/run_brain_model_probe.py` completed with exit 0 using the installed v2
models, standard profile, parcellation and eight QC outputs. The service produced
101 posterior-table entries, the Slicer binary table, a review MRB, segmentation
NRRD, CSV, JSON and HTML. Evidence:
`generated-files/brain-volumetry/probes/model-smoke-vuo1sxyn/probe.json`.
The result directory is `workflow/brain-auwifl8p` within that probe.

The generated ellipsoid is deliberately not an anatomical brain. Its output has
only one nonbackground binary structure (CSF) and low QC values. This is evidence
of pipeline execution, NOT anatomical accuracy, a clinically acceptable scan or
validation of every structure. No real patient scan was processed.

A four-page PDF was then generated from that actual synthetic result using the
workstation report writer and rendered with Poppler. Table widths and repeating
header semantics were corrected after visual inspection. The new Qt layout guard
failed before the header fix; the complete Brain test file now passes 38 tests.
The full model probe was not repeated for the report-only formatting change.

The user's complete requested outcome remains unfinished: active-study selection
and identity binding, representative real MRI acceptance, qualified normative
Z-scores/centiles, and installer delivery still require implementation/qualification.
The download blocker is resolved; it must no longer be reported as outstanding.

### User-supplied examination follow-up (2026-09-05)

A user-authorized local examination was processed successfully with its original
3D MPRAGE and original 3D FLAIR after checking patient/study/frame identity and
geometry locally. The initially supplied T1 folder was identified as T2 SPACE
from image contrast and DICOM metadata; that run was stopped and explicitly marked
failed. The actual MPRAGE and original FLAIR were found within the same authorized
study. No patient identifiers, input paths, images or measurements are stored in
this repository documentation or test fixtures.

The corrected headless execution completed through SynthSeg, rigid registration,
Slicer Segment Statistics and local report/scene generation. Sampled registration
and segmentation overlays were inspected. This is one-examination execution and
visual review evidence, not clinical qualification or a normative reference.
All examination artifacts remain under the local user-data Brain job directory.

The DICOM reader now rejects explicit sequence-description/protocol-name
contradictions for T1 and FLAIR input roles. Unknown metadata is not proof of a
valid protocol. Two synthetic mismatch guards failed before the correction;
positive FLAIR and inverse mismatch cases also pass. The report writer now sets
its printable page size before HTML layout. The full Brain suite passes 43 tests,
including a multi-page PDF check; 462 plugin mirror pairs match.

### Anatomical report organization (2026-09-05)

The integrated report separates basal ganglia, diencephalon, subcortical limbic structures, brainstem, cerebellum, cerebral tissue compartments and ventricles. The 34 native DK cortical parcels are grouped into frontal, parietal, temporal, occipital, cingulate and insular sections using the approximate FreeSurfer lobe mapping (https://freesurfer.net/fswiki/CorticalParcellation). Grouping changes presentation only; no lobar GM+WM totals or new segmentation are inferred. Unassigned paired labels remain visible. Medial temporal measurements and image review have explicit separate pages when images are present. The local report was regenerated from existing results and all 10 pages visually checked. Focused Brain tests: 70 passed.

### Native FreeSurfer research reference implementation (2026-09-05)

The source now includes a separate optional headless FreeSurfer 7.4.1 route and pinned local R scoring for 14 subcortical measurements. Research Z/T scores, Gaussian-approximation percentiles and conditional age curves appear on separate pages. SynthSeg values are never passed to this provider. Runtime setup, exact formulas, unresolved harmonization and clinical limitations are documented in [Reference setup](EAGLE_EYE_BRAIN_REFERENCE_SETUP.md). WSL installation failed and the FreeSurfer license is pending; no patient reference run or clinical qualification is claimed.

### Study-bound workstation workflow (2026-09-05)

The shared Eagle Eye mode resolver now recognizes MR brain/head/MPRAGE metadata.
The viewer Eagle Eye action routes identified brain studies to a dedicated Brain
window without constructing the mammography/lumbar imaging layout. Explicit spine,
neck/orbit context is not routed to Brain. Unknown anatomy retains the existing
resolver behavior; metadata recognition is a routing aid, not image-based diagnosis.

The first dialog offers Whole Brain Segmentation. Lesion Detection is disabled and
marked Coming soon (planned 3D T2 SPACE/FLAIR workflow). The series picker loads MR
series for the current study in a background worker, highlights T1 candidates and
requires explicit full-brain T1 confirmation before running. Unavailable local series
must first be opened/downloaded through the existing viewer. No new network transfer
path is introduced. On execution, DICOM StudyInstanceUID/SeriesInstanceUID must match
the selected examination; image geometry/protocol checks remain in the pipeline.

New DICOM jobs and regenerated reports use:

```text
<User Data>/ai/eagle_eye/brain/patients/<patient-key>/studies/<study-key>/brain-<job>/
<User Data>/ai/eagle_eye/brain/patients/<patient-key>/studies/<study-key>/reports/report-<job>/
```

Keys are deterministic SHA-256 path components, not literal patient names/IDs.
NIfTI-only manual work has no verified identity and uses the unidentified branch.
Historical jobs are not moved. Save PDF As exports a complete PDF using a temporary
file and atomic replacement, outside the GUI thread; the original report remains
with its job. No report is represented as clinically signed or reference-qualified.

This is a feature within the existing AI Imaging module, not a new independently
installed module or feature-flag family. The changed viewer payload is mirrored.
Synthetic tests cover routing, study identity, private path construction, series
selection/confirmation, disabled lesion mode, and successful/failed PDF exports.
The 2026-09-05 source-build live test opened the supplied local study and original
sagittal T1, entered the Brain chooser, selected the matching MR series and started
the pipeline. It exposed an extra generic MR picker labelled Lumbar before the
correct Brain chooser. The launcher now resolves the active viewer's anatomy and
bypasses that generic picker for brain MR. Other MR retains Legion Consult.
The corrected first-click flow was subsequently live-verified on 2026-09-06 above.

The first live computation failed after preparing T1; no completed PDF was offered.
The old process runner discarded stderr and its exit code. The runner now binds
stdin to DEVNULL, retains stdout/stderr in private job-local `process.log` and shows
only the exit code with a safe operator message. A separate captured inference
probe exited with Windows native code 3221226505; this is diagnostic evidence, not
a confirmed root cause or successful workstation run. Full live computation and
Save PDF As were pending at that point; the 2026-09-06 acceptance above supersedes
that pending status.

The subsequent unbuffered local inference probe completed with exit code 0 and
produced 101 valid posterior-volume rows plus 8 QC values. After preparing the same
label dictionary and resampled-source fallback used by the service, dedicated
headless Slicer completed successfully and independently verified 98 binary
segments. These are component-level checks on the supplied study; the failed
workstation job remains marked FAILED and was not promoted to a completed report.
No PDF or in-app Save PDF As success is claimed from these diagnostic probes.

Follow-up verification: 37 adjacent launcher/UI tests passed; the Brain/reference/
lumbar selection passed 265 tests with 8 optional local-reference acceptance skips.
The additional real Windows child-process failure guard failed before diagnostics
were retained and passed afterward; 20 study-workflow tests now pass. All 462
packaged mirror pairs match. No clinical database is accessed by these tests.

Verification: 14 focused study-workflow guards pass, including real Qt dialog
selection/cancel behavior. The adjacent Brain/reference/lumbar lane passed 175
tests; Brain/viewer reuse/startup checks passed 71 tests (overlapping selections,
not additive totals). Viewer mirror verification passes all 462 pairs. Builder
parity selection: 25 passed, one pre-existing-stage configuration mismatch failed
for echomind_settings.json and patient_table_sort.json. Neither configuration nor
staged build output was edited; no release build was attempted.

## Lobar cortical report summary (2026-09-07)

The organized report now adds a dedicated summary before the detailed cortical
pages. Frontal, parietal, temporal, occipital, cingulate and insular groups show
right/left cortical gray matter volume, bilateral sum, percent ICV and measured
parcel coverage. These are explicit report-defined sums of the native DK parcels,
not full lobar GM+WM volumes. Cingulate and insula remain separate. Paracentral is
assigned to frontal; fusiform and parahippocampal parcels to temporal, as stated
on the report. Parent cortex volumes are not counted again.

Incomplete sides are unavailable rather than silently treated as zero; a bilateral
sum requires both complete sides. Hemisphere white matter is shown separately,
with its existing mapped intervals where available. Lobar white matter, full lobar
parenchyma and cortical thickness remain unmeasured. No lobar normative range,
Z-score, percentile or atrophy classification is inferred from these group sums.

Validation: three new synthetic guards failed before implementation; the focused
lobar-summary, patient-report and volBrain selection passed 16 tests. Both existing
axial jobs were regenerated locally without rerunning segmentation, producing
13-page reports. All rendered pages and the new summary layout were inspected.
All 462 existing mirror pairs match; this Brain tree has no existing payload mirror.
No production build or live application restart was performed for this report change.
