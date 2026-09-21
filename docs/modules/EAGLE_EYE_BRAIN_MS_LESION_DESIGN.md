# Eagle Eye Brain MS lesion analysis: candidate evaluation

Updated 2026-09-14. LST-AI development integration is implemented. Clinical
qualification, live source-app acceptance and customer installation acceptance
remain separate gates; this document does not certify clinical use.

LST-AI is a relevant first candidate for T1-weighted plus 3D FLAIR MS lesion
segmentation. Its published evaluation measures lesion number and volume. This
is distinct from SynthSeg anatomical volumetry, and FLAIR hyperintensity alone
must not be labeled a confirmed MS lesion or diagnosis.

Primary scientific source: Wiltgen et al., LST-AI: A deep learning ensemble for
accurate MS lesion segmentation (2024),
https://pmc.ncbi.nlm.nih.gov/articles/PMC11088188/
Official implementation: https://github.com/CompImg/LST-AI

The current official README describes a PyTorch 2.0 release-candidate implementation,
T1 and FLAIR input, automatic model downloads and optional FastSurfer annotation.
The repository advertises MIT code licensing and explicitly describes research-only
use without clinical approval. Pin and review code, weights and transitive assets
separately before customer packaging; do not add an unpinned pip install to the
existing SynthSeg environment. A version-dependent dependency change is not a
validated clinical model update.

Proposed separate workflow: choose T1 and 3D FLAIR from the active study; verify
identity, coverage, contrast, spacing and registration; run an isolated, pinned
lesion runtime; return probability and binary masks in native FLAIR geometry;
measure volume from voxel geometry and connected-component counts with explicit
connectivity/minimum-size rules; show editable overlays and a separate review PDF.
Report total lesion burden and regional distribution only where the atlas mapping
is qualified. Longitudinal new/enlarged lesions require their own validated method.

Before activation: test Windows headless support and portable runtime, prefetch and
hash every asset for offline use, verify inverse transforms and mask geometry,
compare with neuroradiologist-reviewed lesion masks, and measure false positives,
lesion-wise sensitivity, Dice and volume bias across scanners and protocols.
## Implemented development contract

- Function: Eagle Eye Brain -> White-matter Lesions. `lesion_widget.py` reuses the
  Brain asynchronous progress/export shell and selects two distinct, downloaded
  study series. T1 and 3D FLAIR are mandatory; conventional T2 SPACE is not FLAIR.
- `lesions.py` checks Study/Series UID, patient/examination identity, protocol and
  geometry before inference. Inputs are clean local NIfTI copies. Spacing is
  limited to 2 mm in this initial 3D workflow. Demographics are read from DICOM.
- Independent embedded Python 3.10, LST-AI 2.0.0rc1 and CPU PyTorch 2.5.1,
  torchvision 0.20.1. No TensorFlow environment mutation, FreeSurfer, WSL or
  user-installed Python requirement. LST-AI runs `--segment_only`, threshold 0.5,
  no small-object removal, two CPU threads, five-fold HD-BET extraction.
- The adapter quotes Windows paths for Greedy and denies socket connections
  during inference. All three LST-AI models, MNI atlas and five HD-BET weights
  must be present and hash-verified before processing. HD-BET files were checked
  against the published Zenodo MD5 checksums, not just a locally generated hash.
- Output is a binary native-FLAIR mask, component count using 26-connectivity,
  mm3/cm3 volume, largest component and separate review PDF with mask previews.
  Geometry mismatch/nonbinary output prevents publication. Source images remain
  unchanged. Failed jobs are marked and never presented as completed reports.
- Results live under the existing Eagle Eye patient/study hash directories in
  User Data, in `lesions-*` jobs. Save PDF copies the completed report locally.
- No volBrain range, MS diagnosis, anatomical lesion-region claim, cortical
  volumetry or longitudinal change is inferred. Full mask review remains required;
  selected PDF slices cannot establish segmentation correctness.

## Reproducible payload and edition ownership

Canonical source: `generated-files/eagle-eye/brain-lesions`, override
`AIPACS_EAGLE_EYE_LESION_SOURCE` for packaging or `AIPACS_BRAIN_LESION_BUNDLE`
for explicit development runtime selection. Install only the independent
portable environment. `install-report.json` records package URLs/hashes and
`requirements-lock.txt` records all 59 resolved versions. Preserve both when
rebuilding the candidate; do not resolve new versions silently.

The committed dependency lock is `tools/eagle_eye/requirements-lesions.lock`.
Bootstrap a fresh Python 3.10 embedded directory with `python310._pth` containing
`python310.zip`, `.`, `Lib/site-packages`, and `import site`. Install with an
external pip using `--python <bundle>/python/python.exe`, the committed lock and
the CPU wheel index `https://download.pytorch.org/whl/cpu`. Do not reuse the
SynthSeg site-packages. Preserve Python and wheel license files. Extract the LST
archive's `atlas`/`model` folders into `<bundle>/data`; install the five verified
HD-BET files into `python/Lib/site-packages/brainles_hd_bet/model_weights`.

Official model archive:
https://github.com/CompImg/LST-AI/releases/download/v2.0.0-data/lst_data.zip

HD-BET published files/checksums and CC-BY-4.0 metadata:
https://zenodo.org/records/2540695

After installing dependencies and downloading all assets, run
`tools/eagle_eye/finalize_lesion_bundle.py <bundle>`. It copies the versioned
Windows runner and hashes the runtime/assets. Rerun after any adapter change.
This operation does not create an acceptance or licensing approval receipt.

`builder/eagle_eye_lesion_payload.py` stages only manifest-listed files under
`advanced_mpr/payload/eagle_eye/brain-lesions`. Both build backends share this
materialization path; the isolated coordinator passes the canonical source path.
Standard and ARM editions exclude the entire `eagle_eye` asset subtree before
copying. They retain shared Slicer. Eagle Eye identity includes `brain_lesions`.

Distribution requires `acceptance.json` bound to the current manifest SHA256,
with actual offline inference and live GUI passes and completed distribution
rights review. Do not fabricate this record. LST-AI's research-only statement
and transitive asset terms must be reflected in product qualification; a code
MIT license alone is not evidence for every bundled asset or clinical approval.

Verification: synthetic identity, geometry, component-volume, UI, payload hash,
Standard exclusion and existing adjacent workflow guards pass. A synthetic real
Greedy transform with spaced Windows paths also passed. Full pipeline and PDF
acceptance are recorded separately; source live MCP was unavailable at this edit.

Final focused code gate: 72 Brain/lesion/workspace/payload tests pass. Mirror
verification: 462 pairs match. The expanded cross-feature suite reported 108
passes and five failures after concurrent Alignment payload integration; those
failures requested Alignment fixtures/assets and are not a lesion-model pass.
Do not report repository-wide or six-installer acceptance from this result.

## Source acceptance follow-up (2026-09-14)

The complete local CPU pipeline finished on a real paired 3D T1/FLAIR examination,
including registration, five HD-BET models, LST-AI inference, inverse mapping,
native-mask measurements and a seven-page PDF. All seven pages were rendered
with Poppler and visually reviewed. An independent nibabel/scipy calculation
confirmed the affine/shape, binary labels, 26-connected component count and all
component/total volumes against the SimpleITK measurements. This is technical
execution evidence, not lesion-detection accuracy or clinical validation.

The user-authorized source process was started with `AIPACS_TEST_SERVER=1`; the
user signed in. Documented client ping and action discovery passed. Native GUI
input opened the local study, Eagle Eye, Choose Function, White-matter Lesions,
and the paired series selector. The original T1 and FLAIR were selected from the
19 available examination series. DICOM age and sex populated the visible fields.
The native Analyze click started a new job. The activity bar, elapsed timer and
transition from model verification to processing were observed in the real app.
The new in-app inference remains running at this checkpoint; completed result
presentation, native Save PDF and installed-client acceptance are still pending.
Do not turn this partial GUI receipt into a full `live_gui: passed` declaration.

Private input/output receipts and independent checks remain in User Data under
`ai/eagle_eye/brain/validation/lesions-20260914`; they must not enter the model
payload, documentation fixtures or installer. The completed direct-service run
predated the final provenance/cancellation wrapper changes; the fresh in-app job
uses that updated wrapper. The focused 72-test suite was rerun successfully on
the source-launch revision. Distribution-rights review and release prerequisites
remain separate gates. CPU latency needs optimization and hardware benchmarking
before promising routine clinical turnaround.


## Clinician context and longitudinal candidates (2026-09-15)

The lesion input form now requires Primary disease / report context: MS,
Small-vessel disease, or Other / undetermined cause. This is a clinician
statement, never inferred pathology or a change to the segmentation weights.
The optional note is bounded to 500 characters and escaped in HTML. Context is
snapshotted before background execution and retained in result.json and PDF.
SVD reports explicitly leave Fazekas and age/sex percentiles unassessed; the
current MS model has not been qualified for complete vascular WMH detection.

MS exposes a previous/current examination selector. Worker-only repository
reads enumerate studies linked by patient_fk, not by name. Each study supplies
one original full-brain 3D T1 and one 3D FLAIR. Conventional T2 SPACE is not an
acceptable substitute. DICOM patient ID and birth date must match; dates must
be valid and strictly increasing, and study UIDs must differ. Identity checks
precede model work. Missing historical T1 is presently unsupported: the local
LST-AI path needs T1 plus FLAIR for both timepoints.

`lesion_longitudinal.py` holds the shared Brain lock over both independent
LST jobs and comparison. A rigid mutual-information FLAIR registration maps
previous masks with nearest-neighbour interpolation into the current grid.
Native total volumes remain separately measured. Both lesion sets must have
coverage in the opposite acquisition. Review artifacts include the transform,
registered prior FLAIR/mask, matching table and combined PDF. New/enlarged are
EXPERIMENTAL spatial candidates, not confirmed clinical activity. The 1 mm
boundary tolerance is a documented technical heuristic, not a guideline or
validated growth threshold. Merge/split and near-boundary cases remain review
items. A finite registration metric does not establish anatomical correctness;
real longitudinal registration, acquisition-change robustness, false positives,
missed lesions and reader agreement remain clinical validation requirements.
No enhancement is inferred and no MS activity diagnosis is generated.

`lesion_indication.regenerate_lesion_report` creates a new revision below the
original job, recomputes burden from the preserved mask, and keeps the original
PDF/result unchanged. Private review PDFs stay in User Data, never the payload.

Verification: 64 focused context/lesion/background/progress/workspace guards
and 3 lesion-builder guards passed. Tests include real rigid registration on
an identical synthetic phantom, cancellation, identity/date conflicts,
zero-baseline arithmetic, stable/new/growing/merging masks and revised PDFs.
The native source test-server ping was unavailable. Offscreen widget inspection
is not a live pass; fresh-source input, real longitudinal cases, native export
and installed-client acceptance remain pending. No release or acceptance receipt
was created. Existing 462 plugin mirrors match; no new third-party dependency
was introduced (SimpleITK and NumPy are used).


## SVD spatial review and clinician Fazekas (2026-09-15)

SVD reports now include clinician-supplied overall Fazekas 0-3 (optional,
not copied into separate deep/periventricular scores), native candidate burden,
other SVD markers explicitly unassessed, and an explanation of the missing
qualified individual percentile. Visual severity is not inferred from volume.
`svd_assessment.py` can use an existing completed same-study SynthSeg anatomy,
validated by patient ID, birth date and Study UID. Rigid T1-to-FLAIR registration
maps anatomy with nearest-neighbour resampling. Periventricular WM uses a stated
10 mm lateral-ventricle distance band; other cerebral WM, brainstem, cerebellum
and outside/boundary-review voxels are mutually exclusive. Cerebral WM lobar
estimates use nearest ipsilateral DK cortical-group seeds in physical space;
these are proximity territories, not validated lobar WM atlas labels.
Registration overlays and masks must be reviewed. No fresh anatomy model is
silently run if absent; localization is reported unavailable. Clinical validation
of WMH sensitivity and an age-compatible normalization model are outstanding.

The de Kort 2025 reference (doi:10.1016/j.neurobiolaging.2024.11.006) uses
head-size-normalized MNI152 WMH with a 30% probabilistic WM mask. The present LST
MNI step is rigid 6-DOF and is NOT equivalent normalization. Do not insert native
volume into its centile table. A newer LST-AI/neuGRID norm publication was found;
the inspected preprint (doi:10.20944/preprints202606.1568.v1) uses SPM12 TIV
normalization to 1409 mL and GAMLSS; downloadable fitted coefficients were not
obtained. Its age/sex percentile is not implemented or claimed.

Verification: 34 focused indication/spatial/lesion/background tests pass; all
462 mirror pairs match. Tests protect volume conservation, outside-compartment
retention, explicit grading and anatomy geometry. A private 12-page SVD draft was
rendered and reviewed. Age supplied verbally conflicted with DICOM, so the draft
retains DICOM age and flags reconciliation; do not silently replace patient age.
Live source ping remains unavailable; GUI and installed acceptance are pending.


## MS topography / conditional McDonald review (2026-09-15)

`ms_assessment.py` is called only for clinician-selected MS. It reuses completed
same-study anatomy after patient ID/birth date/Study UID checks, or invokes the
existing private Brain analysis inside the already-owned Brain lock to obtain
T1 anatomy. This requires the existing Brain model/Slicer bundle in addition to
LST-AI and increases processing time. No new external runtime is introduced.
Anatomical images are rigidly registered to native FLAIR and labels resampled
with nearest neighbour interpolation. Real-image registration acceptance is
mandatory before clinical interpretation; finite registration alone is not QC.

Periventricular and juxtacortical contact candidates require cerebral-WM-side
six-face adjacency to lateral ventricle or cortical labels. This is a voxel-grid
proxy subject to partial volume and registration error, NOT proof of anatomical
contact. There is no 10 mm dilation or nearest-cortex shortcut. Connected
components receive stable IDs, whole-component volume, Feret diameter and
region tags. Contact candidates overlapping ventricular/cortical labels are
kept but excluded from the conservative support calculation. A 3 mm Feret screen
is documented; it does not assess shape, multiplanar confirmation, perivascular
orientation or alternative causes. Small candidates are retained in the report.

Two DISTINCT screened components across two of the three assessed brain DIS
categories flag only potential topographic support. No automated MS diagnosis,
lesion-typicality decision or complete McDonald adjudication is produced. The
2024 five-region framework includes cord and optic nerve, which remain unassessed
by this brain-only workflow. Cortical-only lesions, enhancement, CVS, PRL, CSF,
clinical context and full DIT remain outside this module. Callosal and
supratentorial tags do not add DIS regions. Corpus callosum is unavailable unless
an explicit callosal label exists; ordinary SynthSeg maps do not provide one.
Counts and whole-component volumes can overlap across tags; total unique count
is reported separately. `ms-candidate-ids.nii.gz`, registered anatomy and transform
are retained for physician review. All conclusions require physician confirmation.

PDF pages include the summary table, criteria scope, scientific references and
per-component review list. Existing reports do not fabricate a new assessment:
regeneration can explicitly request spatial analysis and otherwise says not
assessed. SVD reports do not include the MS criteria pages.

Verification: 48 focused topography/context/lesion/background/builder guards pass.
Synthetic cases cover direct contact vs intervening WM, no border wrapping,
ambiguous overlap, one-component double counting, missing masks, small candidates,
context routing and PDF generation. Three newly added PDF pages were rendered and
visually reviewed using synthetic data. Existing test-control MCP was absent and
its documented local client ping failed. Source live GUI, real MS cases, clinical
accuracy, automatic anatomy-fallback full inference and installed-client acceptance
remain unverified; this is an experimental review aid, not a released diagnostic
classifier. No distribution acceptance receipt was issued.


## WMH reference acquisition and normalization groundwork (2026-09-15)

The final peer-reviewed paper is Boccali et al., Diagnostics 2026;16:2460,
doi:10.3390/diagnostics16152460 (PMC13464935), superseding the preprint-only
identification above. The full XML and supplementary archive were retrieved
from Europe PMC. Local research copies and SHA-256 receipt are under
`generated-files/wmh-reference-research/`; these are research evidence, not a
redistributable normative model or patient data.

The reference covers ages 40-95, separate 2D/3D FLAIR models, and age/sex
GAMLSS Johnson SU distributions. Normalization is native total lesion volume
in mL divided by SPM12 TIV in mL, multiplied by 1409 mL. Supplement S2 gives
conditional medians and covariate shifts, not the spline model, distribution
parameters or reproducible individual CDF. Supplement S3 contains validation
cohort percentile summaries, not age-specific calibration. Neither supplies a
legitimate replacement CDF. No curve digitization, Gaussian approximation,
Fazekas-to-percentile conversion or default patient TIV is permitted.

`wmh_reference.py` implements the scalar normalization with finite/unit-domain
checks and structured reference readiness. The helper does NOT run SPM12 or
establish input identity; it is not called with a guessed TIV. SVD report
creation records readiness in `wmh_reference` and explains age eligibility
separately from missing model/normalization. Cached percentiles are not trusted.
This is partial infrastructure, NOT a working offline percentile feature.

Remaining implementation dependencies: obtain the original fitted R model or
verified age/sex/FLAIR-specific distribution parameters with usable terms;
implement same-input SPM12 TIV with provenance and QC; validate installed LST
version/filtering against the reference pipeline; cross-check CDF outputs
against author-provided numerical examples. Then connect inference and report
values. neuGRID web-service availability does not imply that its server-side
model is downloadable or licensed for client redistribution. No patient data
were uploaded and no author message was sent.

Verification: 47 focused normalization/context/lesion tests pass (three existing
SWIG warnings). Live source-control ping failed with Invalid name; GUI and
installed-client acceptance remain pending. No patient percentile was generated.
