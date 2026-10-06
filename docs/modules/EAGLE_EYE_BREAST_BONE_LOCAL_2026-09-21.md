# Breast and Bone Age: server-edition engine integration

## Mandatory patient review before Bone Age analysis (2026-10-04)

Owner-authorized follow-up: every Bone Age submission opens a patient review dialog,
including cases with complete metadata. Reception fields Name, Gender and BD take
priority after exact receptionId matching; valid DICOM fields fill missing values.
The background worker fetches bounded Reception data. Unknown or ambiguous birth
date formats remain unavailable. Gregorian dates are supported for DICOM. The
Reception BD Jalali contract was verified in the existing worklist server parser;
12xx-15xx Reception dates are converted with Qt's Jalali calendar, including valid
leap-day checks. The same year range is never accepted as a DICOM Gregorian date.
Completed years/months are computed at the imaging date, never the current date.
Missing name, sex and age are blank and require physician entry and confirmation.
Manual age edits clear the derived birth date from the confirmed snapshot.

The modal review is GUI-thread-owned and study/patient-bound. Cancellation or case
switch invalidates the answer before inference. A new physician-review provenance
allows explicitly confirmed sex to supersede DICOM only after server-side study and
PatientID checks; legacy physician/reception fallback behavior remains unchanged.
Older servers reject the new provenance rather than silently using different sex.
The confirmed snapshot is retained in bone_age.json without modifying source DICOM.
The confirmed snapshot supplies the PDF and reference calculations described below.

Validation: focused synthetic worker/form/source/contract and payload checks pass.
Live GUI acceptance is blocked: the documented client ping reports unavailable
QLocalSocket Test Control Server. No application launch, login, restart or deployment
was performed. Native source GUI testing is still required after human bootstrap.
Guards: tests/code/ai_imaging/test_bone_age_review.py and test_bone_age_demographics.py.

## Bone Age PDF and reference bands (2026-10-04)

Owner-authorized report implementation uses the historical Brush/Greulich-Pyle
mean and SD tables reproduced in Gaskin et al. (2011), Tables 1-2, printed pages 8-9.
`bone_age_reference.py` owns a versioned numeric reference; male chronological ages
3-204 months and female ages 3-192 months are supported. Mean and SD are linearly
interpolated between rows. No extrapolation is performed. This is explicitly a
historical reference, not a validated contemporary Iranian population reference.

The report shows chronological age at imaging, estimated skeletal age, difference
in months, reference mean/SD, +/-2 SD interval, Z=(BA-reference mean)/SD and an
estimated normal-distribution percentile. Values exactly at +/-2 SD remain within
the reference range. No mild/moderate/severe diagnosis is invented. The plot separates
the reference mean and +/-1/2 SD bands from the BA=CA equality line. Population
variation is not model uncertainty or height percentile. No adult-height estimate
or model confidence interval is reported. Dates supply fractional chronological
months via elapsed days/365.2425*12; manual age retains completed-month precision.

`bone_age_report.py` validates confirmed patient/study identity, finite model ages
and matching model-input sex. A sex change requires new inference. Missing reference
coverage produces an unavailable reference section while preserving the measured
age. The two-page unsigned report is published through a temporary PDF. Optional
local source evidence is displayed on a third page with preserved aspect ratio.
The report record retains demographic confirmation, reference version and available
engine/checkpoint provenance; legacy checkpoint metadata remains explicitly missing.
New authenticated engine results expose the already-verified weight SHA256 from the
bundle manifest. No model weights or inference preprocessing were changed here.

New inference attempts generate the PDF in the existing background worker. A rendering
failure preserves the successful age result and exposes a review-needed PDF status.
Owner follow-up: every confirmed successful analysis uses the same report template,
including the locally verified original image page, and automatically opens its PDF
through the default PDF viewer after returning to the result workspace. Presentation
checks the current study/patient identity and confirmed snapshot; a switched case
does not automatically open the previous patient's report. The background worker
reuses its confirmed demographic snapshot without another Reception lookup.
The result panel's Create Bone Age PDF action also supports prior results: background
attachment/header/Reception reads, mandatory physician review, matching model sex and
background PDF creation. Original source study/series/patient identity and evidence
hash are checked. Changed result bytes during review abort publication. Independent
report revisions use separate private study attachment subdirectories. Corrected-age
feedback remains separate; it does not silently replace the AI estimate in a report.

Private example output was generated and all three pages rendered locally for layout
review. Patient text and source pixels were masked before tool-side inspection.
Source GUI acceptance remains blocked by the unavailable documented Test Control
Server. This is source implementation, not server rollout or clinical qualification.
Tests: `test_bone_age_report.py`, `test_bone_age_report_ui.py`, and adjacent demographic,
engine, result-tab and builder guards. Twenty initial guards failed before implementation.
Final focused selection after automatic PDF presentation: 97 passed with pytest exit code 0.
`test_bone_age_automatic_pdf.py` verifies missing/unconfirmed/stale-report refusal and
the actual analysis worker's fixed-template generation with source evidence; five
presentation guards failed before implementation. The owned viewer mirror
matches; global mirror verification still reports the unrelated pre-existing
EchoMind ai_chat_pages.py mismatch (1 of 509 files checked). No full build was run.
See the separate [model/training inventory](../reports/BONE_AGE_MODEL_TRAINING_REVIEW_2026-10-04.md)
for checkpoint identity and development-metric limitations.

Date: 2026-09-21. Scope: source integration and isolated CPU execution on the
development PC, before server deployment and Standard-client migration.

## Ownership and behavior

`modules/ai_imaging/eagle_eye_engines` owns the service adapter, subprocess worker
and imported inference implementations. Existing MG/DX QThread workers select a
prepared local bundle only after a successful full synthetic smoke for the same
manifest revision; without that qualification they retain the existing remote
route. A selected local engine failure is reported rather than silently retried
on the remote server. No test-only launch flag enables the local engine.

The caller uses complete, counted local study series; it does not request images
from the old API. The standalone CLI accepts an explicit list of DICOM files for
future server staging. Input identity, modality, single-frame dimensions, duplicate
instances, source hashes and Bone Age demographics are validated. Full-hand input
is required for Bone Age. The initial worker implementation is explicitly CPU-only.

Each job has its own directory and owned process tree, deadline, cancellation and
atomic result file. No model framework is imported into the workstation process.
The Breast adapter preserves FCOS preprocessing, original-coordinate boxes, lesion
features and XGBoost classification. It requires a strict verified state dictionary
and disables backbone downloads and random-weight fallback. Bone Age preserves the
EVA02 implementation and preprocessing without importing the API or its automatic
fine-tuning collector. Legacy diagnostic output stays inside the private job.

MG result CSVs are published under unique names in the existing study attachment
directory so the current manifest/review widgets continue to find them. Bone Age
retains its existing JSON result interface. Neither route enables dataset collection.

## Provenance

Allowlisted originals were read from `pacs:D:/FCOS_AR` and
`wina100:D:/Bone/BoneInference`. SHA-256 comparison verified 25 Breast files and four
Bone Age files against their remote originals. No dataset, clinical result, runtime
log, credential or patient image was intentionally acquired as an input dataset.
The private snapshot remains under ignored `generated-files/eagle-eye/`.

`vendor/provenance.json` records original source hashes. The repeatable import tool
removes source comments/docstrings, demonstration entry points and machine-specific
absolute paths, and translates the one non-English diagnostic. FCOS loading is
delegated to the strict adapter. Source acquisition is not evidence that the frozen
server applications contain identical code, nor a clinical equivalence result.

## Development preparation

Tools:

- `tools/eagle_eye/import_breast_bone_sources.py`: explicit source allowlist only.
- `tools/eagle_eye/prepare_breast_bone.py`: stage weights/source and seal all runtime
  files in the manifest after dependency installation finishes.
- `tools/eagle_eye/run_engine.py`: explicit DICOM input or actual-model synthetic
  smoke execution. Smoke outputs are tagged synthetic and have no clinical meaning.

Bundles are `generated-files/eagle-eye/breast` and `generated-files/eagle-eye/bone-age`.
The isolated Python environments use 3.10 and 3.12 respectively. They do not alter
the application's Python 3.13 environment. These development venvs reference their
local base interpreters and are NOT portable release payloads. Dependency freeze,
model execution receipts and final verification status must be recorded below.

Example synthetic execution from the repository root:

```powershell
.\.venv\Scripts\python.exe tools\eagle_eye\run_engine.py breast --smoke --output generated-files/eagle-eye/smoke-breast
.\.venv\Scripts\python.exe tools\eagle_eye\run_engine.py bone-age --smoke --output generated-files/eagle-eye/smoke-bone
```

## Verification and outstanding gates

- Focused code verification: 53 tests passed, covering the new boundary and
  existing MG, DX, lifecycle and evidence-package workflows. The new local-worker
  routing guard failed before adding the routing branches, then passed.
- Targeted viewer mirror synchronization: 470/470 existing pairs match.
- Live GUI: initial `aipacs-control` CLI ping could not connect. Human source
  bootstrap requested; this is not a GUI pass.
- Bone Age actual-model smoke: passed on this PC, CPU, isolated Python 3.12.13;
  one generated DICOM image, strict model loading and finite inference result.
  The job receipt is tagged synthetic. No patient image was used.
  Repeated successfully after the final worker update; the revision-bound local
  qualification receipt was written. Bone Age is selectable locally; Breast is not.
- Breast actual-model smoke: FAILED at stacked classification. The real detector
  forward, lesion extraction, single-view and multi-view feature stages executed.
  LightGBM and CatBoost dependencies embedded in serialized classifiers were added.
  The supplied final estimators require nine features, whereas the supplied
  inference implementation constructs four. All four final estimators report nine
  input features. The inspected training source also constructs four; the wrapper
  calls the same inference module. No verified nine-feature construction/order was
  found. Matching inference/training source or a compatible weight set is required.
  Breast is deliberately unqualified for automatic local UI selection and keeps
  the existing remote route. The local CLI rejects the incompatible schema.
- Clinical parity with the running server executables, GPU qualification, portable
  runtime packaging, installer inclusion, server service and Standard-client network
  protocol remain explicit later gates in the server/client plan.

The current installers are unchanged. Do not claim these models ship in an existing
Eagle Eye installer. The later packaging slice must include the complete verified
engine runtimes, weights, manifests and notices in Eagle Eye only, exclude them
from Standard/ARM, and pass both backend content/clean-machine gates.

See [server/client plan](../plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md).

## Runtime qualification notes

The allowlisted dependency closures were read from the existing remote venvs over
the control-node connection, with no remote changes. Exact installed versions are
recorded in `tools/eagle_eye/requirements-breast-cpu.txt` and
`tools/eagle_eye/requirements-bone-age-cpu.txt`. These are observed environment
snapshots, not cross-platform lock files. Breast's inherited SymPy mismatch was
corrected to 1.13.1 for Torch 2.5.1. Bone uses Torch 2.12.1 CPU and timm 1.0.27.
Both environments pass dependency compatibility checks after preparation.

Breast's supplied weight file contains the FCOS detector only: all 319 keys match
the plain detector strictly. It does not contain the auxiliary classification head.
The adapter reports `auxiliary_head_available=false`; the final detector decision
and lesion classifier are used. Legacy auxiliary diagnostics are not evidence of
a trained auxiliary model. Frozen-executable clinical parity remains unverified.

The synthetic Breast smoke runs the real FCOS forward. If it detects no lesion,
the smoke alone supplies a synthetic ROI to exercise the four classification
stages. This cannot establish detection performance or clinical equivalence.
Compressed transfer syntax coverage and representative multi-view study validation
remain outstanding. Bone Age rejects inputs not explicitly tagged as full-hand
images and requires consistent DICOM sex. Inputs outside this initial contract
produce an error, not a guessed result.

The base-classifier files also store `(name, estimator)` tuples inside each label
ensemble. A tested adapter unwraps those tuples while preserving every member and
ensemble grouping. This resolves object-format compatibility only, not the missing
nine-feature stacker contract. The schema preflight rejects that separate mismatch
before inference. No zero padding, guessed ordering or partial ensemble fallback
is used. The private reference copies of `XGBOOST_CLASSIFIER.py` and
`run_classification_subprocess.py` were inspected as code only, never executed or
added to the runtime. Their embedded demonstration paths are not copied into docs.

Source-study attachment routing was checked against the actual `ATTACHMENTS_DIR`
definition. Its regression guard failed with the incorrect legacy constant and
passed after correction. No test reads the live database.

## Installed Reception server investigation (2026-09-21)

Read-only inspection confirmed that TCP 8002 belongs to the child process of
`D:/FCOS_AR/dist/AI_PACS_Mammo.exe`. Its loaded Python DLL is inside the active
PyInstaller extraction directory. The bundled API source, FCOS source, detector
weight and stacked-classifier artifact hashes match their counterparts under
`D:/FCOS_AR`; the loose classifier source under `dist/XGBoost_AR` also constructs
four stacker inputs. This does not assert bytecode equivalence for every module.

The running application's log identifies classification jobs under
`%LOCALAPPDATA%/AI_PACS_Mammo/.cache_models/classify_jobs`, rather than the empty
`dist/classify_jobs` folder. Inspection was performed on the server and returned
only aggregate counters. No patient IDs, images, CSV rows or raw clinical logs
were downloaded or copied into this report.

In the 20 most recently modified job directories sampled from the installed
application cache:

- All 20 contain a classification CSV with all four probability columns.
- Across 200 result rows, all 800 probability cells are missing/nonfinite.
- All 200 rows have zero abnormal-class flags and `pred_No Finding=1`.
- Their Stage 4 logs contain 80 nine-feature mismatch indicators, 80 stacking
  failure indicators, and named-tuple prediction failures. A file can contain
  repeated log indicators; these counts are not patient or independent-failure counts.
- Sample CSV modification timestamps range from 2026-08-04 14:40 UTC through
  2026-09-20 20:56 UTC. This is a bounded historical-output sample, not a newly
  submitted inference request or an exhaustive audit of all server outputs.

The behavior follows the inspected error path: the classifier catches a failed
stacker prediction and fills its probability with NaN. Threshold comparisons then
evaluate false, and the fallback sets `No Finding`. The pipeline considers the
existence of `classification.csv` sufficient for success. Separately,
`run_full_analysis` returns HTTP 200 and top-level `status=ok` with detection results
even when its nested classification status is an error. The current client
downloads output links without validating probability completeness. Consequently,
receiving a response or a classification file does not establish successful
classification; the sampled `No Finding` labels are failure artifacts, not valid
negative classifier findings. Detection performance was not assessed here.

No server process was restarted, no configuration or clinical output was changed,
and no new study was submitted. The local engine's fail-closed qualification gate
remains necessary. Follow-up work must preserve classification failure through
server and client result handling, validate finite complete classifier outputs,
and obtain the matching nine-feature inference contract before qualifying Breast.

## Phase-1 transport follow-up

The [server/client source implementation](EAGLE_EYE_SERVER_PHASE1_2026-09-21.md)
now runs both imported engines behind the common PACS-reference job service.
Actual synthetic loopback transport passed for both. Bone Age full model smoke
passed again; Breast publishes detection with explicit unavailable classification
and remains unqualified for complete classification. The missing-classification UI
message no longer states a normal case. No existing clinic server was modified.
The earlier network-service deferral above is superseded by that implementation
ledger; portable packaging, GUI acceptance and server deployment remain open.

## Standalone Windows build inputs for v3.6.9 (2026-09-28)

`tools/eagle_eye/prepare_portable_breast_bone.py` now creates new, sealed Server
build inputs from the verified development bundles plus complete relocatable
Windows Python bases. It does not rewrite the development venvs. The exact
sources used here were the existing `generated-files/eagle-eye/{breast,bone-age}`
bundles and the local uv-managed CPython 3.10.20 and 3.12.13 bases, respectively.
The source manifests were hash-validated before copying. Compile-time PyTorch
headers and interpreter development headers/libs/scripts are excluded; the
runtime dependency and model files are inventoried and SHA-256 sealed. Neither
bundle contains `pyvenv.cfg` or requires the developer's interpreter launcher.

The resulting ignored immutable inputs are
`generated-files/eagle-eye/breast-portable-3.6.9` (18,796 manifested files) and
`generated-files/eagle-eye/bone-age-portable-3.6.9` (12,667 files). Both passed
isolated interpreter/import probes and full bundle hash validation. From a
separate `C:\b` working directory, the sealed Bone Age interpreter completed a
real-model synthetic job. The sealed Breast interpreter loaded its detector and
base classifiers and completed synthetic-image detection; the known nine-versus-
four feature mismatch was truthfully returned as
`classification_status=unavailable`. These are relocation/functional input
checks, not clinical accuracy, clean-host, frozen Server, or redistribution
acceptance.

`builder/eagle_eye_engine_payload.py`, both backend materializers, the Server
distribution profile, and the existing Inno installer now stage these two
standalone assets only for Eagle Eye. Standard and ARM keep excluding all
`eagle_eye` assets. Missing interpreter/model manifests fail closed; actual
server staging validates the complete file hashes and a bound runtime probe.
Release-mode staging additionally requires a real, manifest-bound rights
approval for each engine; no such approval was fabricated here. The compile-only
synthetic installer probe passed all three editions and missing-engine rejection.
Both installed backends use the shared frozen detector, so Nuitka cannot accept
a development venv where PyInstaller rejects it.

To prepare a *new* bundle version, use the same tool with new destination paths,
the verified source bundle and an actual standalone Python base of the required
minor version. Never overwrite these completed inputs. Select the two paths via
`AIPACS_EAGLE_EYE_BREAST_SOURCE` and
`AIPACS_EAGLE_EYE_BONE_AGE_SOURCE`, or let the canonical build coordinator use
its `generated-files/eagle-eye/<engine>-portable-<version>` defaults. Do not
copy patient jobs, probe outputs, credentials or development venv directories
into a staged payload. The only full-build entry point remains root `BUILD.md`.

Remaining Server promotion gates: complete installer/SCM lifecycle and rollback,
both frozen backends on a clean Windows host, model rights evidence, current
security incident closure, and clinical acceptance. The Breast classifier is
not qualified and must not be presented as a normal finding.

## Hosted execution correction and native acceptance (2026-09-22)

The [phase-1 execution receipt](EAGLE_EYE_SERVER_PHASE1_2026-09-21.md) supersedes the historical local-selection and unreachable-UI notes above. Both owner-selected studies now run through the desktop-owned local server and return results to the actual UI. Bone Age displays its prediction; Breast displays returned detection rectangles and selectable findings, with unavailable classification explicitly reported. Development venv homes use physical interpreter paths to avoid the Codex MSIX profile alias. WRIST-tagged inputs retain unchanged DICOM and a coverage-review warning. No model weights were changed and the nine-feature classifier mismatch remains unresolved. Final focused execution/transport checks: 60 passed; 470 mirrors match. No server deployment or installer qualification is claimed.

### Additional training-source investigation (2026-09-22)

Read-only inspection of `lina100:~/Mammography/Enhanced Mammography/XGBoost_AR`
found the older four-kind trainer and a separate enhanced multi-engine trainer.
The latter writes differently named artifacts, trains LogisticRegression meta
learners for abnormal labels only, and concatenates engine probabilities across
available kinds. It does not establish provenance or feature ordering for the
currently supplied stackers. No training, model replacement or remote service
change was performed.

Local inspection of the already acquired artifacts confirms four used kinds,
nine-feature stackers and a nine-feature imputer. The supplied stackers comprise
two LogisticRegression and two LGBMClassifier objects, including No Finding;
their saved feature-name arrays are absent. Base ensembles have three engines for
two labels and four for the other two. Neither flattening these ensembles nor
padding four probabilities to nine is a verified inference contract. The matching
training/inference source or compatible qualified weight set remains required.

Owner decision (2026-09-22): defer further Breast optimization and classifier
reconciliation. Continue Brain and server/client work. Detection output remains
available; unavailable classification must remain explicit, without guessed
features, padding or substituted model weights.

## Three-host Breast audit refresh (2026-10-01)

The owner requested renewed review of the workstation, Razi Eagle Eye deployment,
Windows A100 datasets and Linux A100 training. This section supersedes the earlier
statement that no nine-feature construction source was found. Review was read-only
on all remote hosts; no clinical request, training, deployment, service restart,
model replacement or configuration change was performed. Patient images, identifiers,
CSV rows and clinical response bodies are excluded from this report.

### Verified locations and active source

| Role | Verified location |
|---|---|
| Windows dataset | `wina100:F:/Aisan-Rahimi-part2/MammoDicomData/{original data,modified}` |
| Windows working code | `wina100:D:/Enhanced Mammography`, especially `XGBoost_AR` |
| Additional Windows projects | `wina100:D:/AisanRahimi/{FCOS_AR,mamography,ClassificationModule,SegmentationModule}`; directories discovered, not exhaustively audited |
| Final delivery | Windows dataset `modified/FINAL_MAMMOPROJECT_DELIVERY/Final_Delivery` |
| Linux training | `lina100:/home/gadmin/Mammography` and its `Enhanced Mammography/XGBoost_AR` |
| Legacy Razi assets | `pacs:D:/FCOS_AR` |
| Active Razi source | `pacs:D:/Eagle Eye Server/revisions/20260930-echomind/source` |
| Local engine | `generated-files/eagle-eye/breast`; source adapter in `modules/ai_imaging/eagle_eye_engines` |

SSH identities matched WIN-I5E5QM7V2R2, gpu and WIN-CTBQPS2GSM3. Razi's
`AIPacsEagleEye` service is Running as LocalService. Port 8002 is owned by the
observed process using the 20260930-echomind source and the dedicated Python 3.13.5
runtime. This refresh establishes process/source ownership, not a fresh authenticated
Breast inference or clinical acceptance pass.

### Artifact lineage: two different classifier generations

SHA-256 checks found the same stacker, imputer, used-kind and SINGLE base-model
artifacts in the Windows dataset `modified/XGBoostData_STACK/models_stacked`,
legacy Razi assets and the active Razi source bundle. Local stacker/imputer hashes
also match. The stacker hash is
`9a2a0f02475c602140c5d605a9bf375881945cb770c1650f7961747dce9da32a`;
the imputer hash is
`1c35030ebef44132775c0de0ccc08440a1b0c589e08a7ebfae88ebbf587a5af6`.
Local, legacy Razi and active Razi detector files also match:
`9f8746666dccb5e22840a8bfdcb22b9eacb1e3a4b31b61b6b2ec6cd005679901`.
These comparisons cover selected artifacts, not every byte in every installation.

Windows `D:/Enhanced Mammography/XGBoost_AR/models_stacked` instead matches
the inspected Linux stacker and SINGLE base-model artifacts. Its stacker hash is
`2f8fcd28f27fd8958cee4e81bcaa8027f475f4cc6f7edd3b6822c10530e7c9fc`.
It has no `stack_imputer.joblib` at the checked path. Linux detector hashes differ
from the delivered detector: root checkpoint `25752d8aa0679921ed32c344777114cffac3a345da0cb7074cce18684bc82b3a`,
Enhanced checkpoint `9dd16a3bbd3b1917091d79ed2be54f816d4bd9b581b6374c24547fd25a1b622e`.
Do not treat these generations as interchangeable or infer training provenance from
their filenames.

### Recovered feature contract and remaining execution defects

Windows `D:/Enhanced Mammography/XGBoost_AR/XGBOOST_CLASSIFIER.py`
(SHA-256 `749fa8cc6566a82952458fe831e91446d8885cbe02b12f7bd1f723e658e30721`)
contains an enriched stacker at lines 1158-1192. For each label it orders base
probabilities as SINGLE, MV, BL, BOTH, then appends nanmean, nanstd, nanmax, nanmin
and max-minus-min. It applies a constant-0.5 SimpleImputer. This produces nine
features and matches the delivered artifacts' dimensions and estimator families:
LogisticRegression for No Finding/Mass, LightGBM for Suspicious Calcification/Focal
Asymmetry. It is strong compatibility evidence, not a saved run-to-source receipt.
The trainer's source hash does not establish that this exact revision generated
the deployed artifacts.

There is a second missing contract: all four delivered base-model feature lists
include 60 `feat_inter_*` arithmetic interaction columns. Total feature counts are
119 SINGLE, 149 MV, 148 BL and 178 BOTH. The trainer constructs product, difference
and ratio columns from selected pairs. Current imported inference does not construct
these interactions: its reindex step supplies NaN for absent columns. Both
interaction generation and nine-feature stacking must match training before
classification can be qualified. Tuple ensemble unwrapping alone is insufficient.

The Linux `XGBOOST_CLASSIFIER.py` and final delivery
`XGBoost_DrAlizadeh/Code/XGBoost_AR/XGBOOST_CLASSIFIER.py` have the same source hash
`fbb42d5d906e7692615009b3ba8008d5c8301fe1208c14761532b9be50a2b36b`.
They are the older four-feature trainer. Inspected Windows and final-delivery
inference implementations also construct four stack inputs. The active Razi worker
retains the schema guard requiring `len(used_kinds)` inputs, so nine-feature
classification is rejected and detection can return explicit unavailable
classification. The historical silent No Finding failure described above must
not be conflated with this current fail-closed behavior.

A local isolated synthetic probe constructed the recovered nine-feature matrix
and applied the saved imputer. No Finding and Mass stackers returned finite,
bounded probabilities. The first LightGBM stacker raised an OSError/native access
violation in `LGBM_BoosterPredictForMat`; process exit was 1. No clinical input was
used. Root cause is unresolved; this is a separate runtime blocker, not evidence
that the feature formula is wrong or that Razi exhibits the same native failure.
Observed local versions: numpy 2.0.2, scikit-learn 1.4.2, lightgbm 4.7.0,
catboost 1.2.10, xgboost 2.1.4, torch 2.5.1, torchvision 0.20.1.

### Dataset integrity and evaluation limits

Original breast annotations contain 20,000 image rows across 5,000 study IDs,
with 16,000 training and 4,000 test rows. Finding annotations contain 20,486 rows.
Original metadata has a duplicate `SOP Instance UID` header; dictionary-based CSV
loading can overwrite a column and needs explicit schema handling.

The prepared `modified/CSV-PNG-full` splits were compared locally on Windows,
returning aggregate counts only:

| Split | Annotation rows | Distinct study IDs |
|---|---:|---:|
| train.csv | 16,391 | 4,000 |
| valid.csv | 3,745 | 1,000 |
| test.csv | 350 | 292 |

Training has zero study/image-ID overlap with either other split. Validation and
test overlap in all 292 test study IDs and 39 image IDs, despite zero PNG-path
string overlap. These prepared splits do not provide an independent study-level
test set. Patient-level independence remains unverified because these tables lack
an authoritative patient key; study IDs are not proof of distinct people.

`modified/XGBoostData/output_multiview_features.csv` has 20,486 rows, 159 columns
and 5,000 study groups, with zero engineered interaction columns. Explicit label
occurrences are No Finding 18,232, Mass 1,226, Suspicious Calcification 543 and
Focal Asymmetry 269; categories can overlap and these are not patient counts.
This table spans the original study population. Exact training-input/run lineage
must therefore be proven rather than assuming the classifier used only train.csv.

Inspected old and new stacker trainers fit a meta-learner on base OOF predictions,
then fit calibration and choose thresholds on those same meta-training rows.
Their resulting stacked scores are not an independent evaluation of the full
pipeline. The separate Linux neural trainer fits imputation/scaling before outer
CV and uses a row-level inner split; the enhanced multi-engine trainer also uses
row-level stratified CV. These are method defects in inspected candidate sources,
not proof that those candidates are the deployed model.

Linux FCOS training builds one dataset item per CSV annotation row and does not
consolidate all boxes for an image in the inspected loader. Multiple annotations
can consequently present the same image with incomplete targets. Its configured
`/home/gadmin/Mammography/CSV-PNG-full` directory is absent now, as is the historical
`original data` directory. The surviving script is not currently reproducible from
those configured paths alone; no relocation or deletion history was established.

Historical Linux detector reports contain, at IoU 0.5, Swin precision 0.3198 and
recall 0.1741; ConvNeXt precision 0.0440 and recall 0.5095. Both lack COCO mAP.
These are archived metrics with unverified checkpoint/data/threshold binding, not
current deployed-model accuracy. No fresh detection-quality measurement was run.

### Verification and ordered follow-up

Focused existing engine/detection-only guards: **28 passed**, pytest exit 0.
Synthetic meta-model execution: **FAILED** at LightGBM as described above.
Live GUI/clinical acceptance: **not run** for this read-only review. No runtime
fix, regression-catalog entry, model qualification or release is claimed.

Follow-up should first preserve explicit unavailable classification, establish an
immutable artifact/source/feature manifest for the recovered generation, reproduce
interaction and meta-feature construction in an isolated candidate, and diagnose
the LightGBM native failure. Next, establish patient/study-disjoint development,
calibration and final evaluation sets; audit full-resolution preprocessing,
multi-view pairing and multiple-lesion target completeness. Only after those gates
should a held-out detection-plus-classification evaluation, affected-workflow GUI
pass and separately authorized Razi rollout be considered. Adding five columns or
retraining before resolving lineage would not close these findings.

## Priority review: calcification discovery and lesion typing (2026-10-01)

Owner priority: first discover calcifications with and without an associated mass;
then improve Mass/Focal Asymmetry/Asymmetry typing. Calcification morphology/risk
classification is a later, separate target. This review is read-only for runtimes,
weights and datasets. No training, clinical evaluation or deployment was performed.

### Newly verified evidence

The local worker, FCOS inference and XGBoost inference SHA-256 hashes match files
in the previously identified Razi revision
`D:/Eagle Eye Server/revisions/20260930-echomind/source`. This binds the inspected
source to that server revision, not a newly observed clinical invocation.

- `vendor/breast/FCOS_INFERENCE.py` sets `IMG_SIZE=(512,512)` and resizes the
  whole mammogram with antialiasing. The worker also sets detector transform limits
  to 512. This loses fine spatial information and distorts aspect ratio; increasing
  display size later cannot recover it. This is a strong mechanism hypothesis for
  small-calcification misses, not measured causal attribution.
- After detection/TTA, `filter_tiny_boxes` rejects area fractions below 0.002.
  At 512 square this is 524.288 pixels of box area, equivalent to a square about
  22.9 pixels wide. The filter acts before final confidence-threshold selection.
  Removing it cannot recover boxes never proposed by the network.
- Detection input is min/max-normalized 8-bit PNG from DICOM, while lesion feature
  extraction reads DICOM crops separately. Audit contrast/photometric presentation
  and source/training equivalence; quantization is a candidate contributor, not
  proof that all calcification contrast is lost.
- The classifier's literal labels are No Finding, Mass, Suspicious Calcification
  and Focal Asymmetry. It has no independent Asymmetry class. Generic Asymmetry
  cannot be reliably obtained by tuning these four class thresholds.
- The inspected Linux `FCOS_TRAIN.py` also uses 512-square input and one-class
  abnormal boxes. Its annotation-row indexing with at most one box per item
  remains a target-completeness defect. Binding this surviving trainer to the
  delivered checkpoint is still required before attributing weight behavior.
- `TWO_VIEW_FEATURES.py` can select opposite-view ROIs using overlap of
  `finding_categories` when present, otherwise the first opposite-view row.
  Contralateral ROI selection also uses the first available ROI. These are not
  validated anatomical lesion correspondences. Label-assisted training pairing
  versus label-free inference is a potential leakage/distribution mismatch;
  inspect the actual training feature lineage before claiming it occurred.
- The percentile-bright-blob calcification proxy in SINGLEVIEW_FEATURES is a
  hand-engineered ROI feature, not an independent full-image calcification detector.
  It cannot discover calcifications outside detector-generated ROIs.

Windows source annotation audit used `original data/finding_annotations.csv`,
only aggregate outputs, and exact category membership. All audited target boxes
had positive dimensions. Counts are annotation rows and study groups, not patients.

| Target | Annotation rows | Distinct study groups | Reference boxes below 0.002 full-image area |
|---|---:|---:|---:|
| Suspicious Calcification | 543 | 220 | 196 (36.1%) |
| Mass | 1,226 | 584 | 200 (16.3%) |
| Focal Asymmetry | 269 | 134 | 6 (2.2%) |
| Asymmetry | 97 | 96 | 13 (13.4%) |

These are reference-box filter simulations, not detector outputs or recall. A
predicted box may be larger/smaller than its reference; no recall ceiling is inferred.
The resized box-area fraction is preserved by the current separate x/y scaling.

Of 543 calcification rows, 90 also name Mass in the same annotation and 453 do not.
When Mass anywhere in the same image is considered, 234 calcification rows are
in mass-containing images and 309 are not. Neither definition proves spatial
association; a reviewer must establish whether the mass and calcifications belong
to the same lesion. Preserve both definitions and add reviewed association status.
Suspicious Calcification labels do not exhaustively annotate every benign macro/
microcalcification or provide individual speck masks. Do not score absent labels
as proof of calcification absence.

### Ordered experiment plan

1. Freeze a reviewed, grouped development cohort with calcification clusters,
   calcification-with-associated-mass, calcification-without-associated-mass,
   benign calcifications, difficult normals and mass/asymmetry mimics. Separate
   unknown association and missing views. Fix the prior validation/test overlap
   before claiming independent evaluation. Preserve private patient linkage.
2. Reproduce the current detector with immutable weights and record proposals
   before/after internal score/NMS, TTA, area filter and final threshold. Measure
   cluster sensitivity at prespecified FP/image or study and stratify size,
   density, association and views. Audit DICOM-to-PNG appearance on reviewed inputs.
3. On development data compare current postprocessing with disabling/replacing
   the area cutoff, and a confidence sweep below/above the current operating point.
   Log increased false positives. The model's internal score floor (0.2 in the
   inspected source) limits what a later threshold sweep can recover.
4. Compare a spatially faithful higher-resolution baseline and a dedicated native-
   resolution overlapping-tile calcification branch. Define tile scale in physical
   units when metadata supports it, border coverage, coordinate mapping and merging.
   Retain whole-breast context for masses/asymmetry. Tile experiments require
   appropriate training/qualification; changing inference size alone is not a fix.
5. Consolidate all reviewed boxes per image in an isolated training candidate.
   Correct train-only sampling/label masks and validate label/box transformations.
   Compare reuse of the detector against task-specific patch segmentation/detection
   candidates below; add masks only with sufficient reviewed mask supervision.
6. For lesion typing first close recovered feature/stacker/runtime mismatches from
   the earlier audit. Run classifier-only evaluation with reference ROIs to isolate
   typing errors, then detector-ROI and full-cascade evaluation. Add Asymmetry only
   with a versioned target/head and reviewed examples; preserve coexisting Mass and
   calcification outputs rather than forcing one exclusive lesion label.
7. Compare reviewed ROI plus whole-breast/multiview context against current handcrafted
   features. Validate view/laterality and anatomical correspondence, missing-view
   masks and training/inference parity. Report per-class confusion and sensitivity,
   calibration and missing/unavailable classification separately. More layers are
   justified only by controlled improvement evidence.

Profile each candidate on actual available GPU memory and representative image
sizes. Use small feasibility pilots before full high-resolution training. Retain
the deployed revision; package improvements separately and require target/GUI
qualification before any authorized rollout. No clinical accuracy is claimed here.

### Task-matched research shortlist (checked 2026-10-01)

| Candidate/source | Potential use | Current evidence and limits |
|---|---|---|
| Current owned FCOS plus controlled postprocessing/resolution experiments | Cheapest causal baseline | Actual source/checkpoint available; cannot assume threshold changes solve lost detail |
| [Resolution-preserved patch study](https://www.mdpi.com/1999-4893/16/10/483) and author MMGpatchCL repository | Patch-scale strategy comparator | Published patch approach; repository fetch failed in this review, weights/license/readiness unverified |
| [DeepMiCa](https://github.com/ales-git/DeepMiCa) | Calcification segmentation/classification research comparator | Public staged code and license file observed; exact license, pretrained asset access and local reproducibility still need qualification |
| [Microcalcification detection/classification](https://github.com/AliceQLin/Microcalcification-detection-and-classification) | Dedicated calcification pipeline comparator | Public FPNNet code observed and linked by the original study; usable weights/license/configuration not established |
| Native-resolution tile detector/segmenter with whole-image context | Owned candidate implementation strategy | Engineering hypothesis; requires pilot, reviewed targets and resource/accuracy comparison |

The [VinDr-Mammo publisher](https://physionet.org/content/vindr-mammo/1.0.0/)
provides relevant finding labels, not universal calcification morphology truth.
Similar local counts do not replace an exact provenance/license receipt. None of
the above is selected as globally best or ready for clinical deployment. The next
decision should use local development evidence rather than published headline scores.

### Review verification

Read-only SSH inspections succeeded on Windows data host, Linux training host and
the Razi revision. Source hashes matched for the three files above. Box/co-label
statistics were computed on the Windows host without exporting image data or IDs.
Document/numerical checks passed. Runtime/GUI/clinical tests were not run because
this step changes documentation only. Causal ablations and reviewed image-level
evaluation remain pending; this report separates those from observed code defects.

## Implemented candidate and diagnostic dataset evaluation (2026-10-01)

The owner requested correction and dataset checks. Work produced source corrections
and an isolated candidate under
`wina100:D:/Enhanced Mammography/candidates/20261001-calcification`.
The Razi service, its environment, weights and production revision were not changed.
No new model weights were trained. The detector remains unqualified for reliable
calcification discovery; the numerical evidence below must not be summarized as
complete resolution of the owner's clinical complaint.

### Corrections and causal verification

- Removed the unconditional 0.002 area cutoff from FCOS postprocessing. A behavioral
  test running the actual function with a confident 4x4 synthetic box failed before
  and passed after. The input remains 512 square because higher-resolution inference
  was tested and rejected as an operating-point replacement below.
- Added `vendor/breast/feature_contract.py` to reconstruct the recovered product,
  absolute difference and zero-masked ratio interactions in the saved feature order.
  Missing raw features are errors, not silently inserted NaNs. This closes the
  missing engineered-column construction gap without selecting new features.
- Reconstructed the saved base probabilities plus mean/std/max/min/range meta
  contract and applied the saved nine-column imputer. Unknown widths, incomplete
  predictions or a mismatched imputer remain unavailable. Base-only four-column
  contracts remain supported. The nine-column guard failed before and passed after.
- Fixed `PlattCalibrator.transform` to invoke the saved `logistic_model` on the
  raw scalar probability as in the recovered trainer. The imported wrapper ignored
  this saved state and returned identity scores. This specifically inflated Focal
  Asymmetry positives at the saved threshold. The guard failed before and passed
  after; thresholds and weights were not retuned.
- Nonfinite/out-of-range final outputs and missing required base predictions fail
  before No Finding generation. Existing worker failure/unavailable semantics remain.
- LightGBM 4.7.0 still failed the serialized stacker prediction in the existing local
  runtime. Identical artifacts executed in the Windows dataset host's existing
  LightGBM 3.3.5 environment, then in a local isolated 3.3.5 overlay. Updated the
  Breast candidate requirements pin to 3.3.5. No live runtime was upgraded/downgraded.
  No model reserialization, native handle workaround or tree reinterpretation was
  retained. All real base ensembles, interactions, stackers and calibrators passed
  a local synthetic end-to-end feature inference check under the compatible overlay.

### Detector paired ablation

`tools/eagle_eye/evaluate_breast_detector.py` ran on the Windows data host using the
actual delivered `best_fcos_csv_delivery.pth`, strict load, CPU Torch 2.5.1 and
Torchvision 0.20.1, the current hflip/NMS convention and prepared PNG inputs.
It selected all 105 publisher-test images containing Suspicious Calcification
(115 reference annotation boxes) plus the first 100 sorted publisher-test No Finding
images. No input failed. This is an enriched diagnostic development cohort, not
a population-wide or clinically independent study. Reference matching was one-to-one
at IoU >=0.5. Only aggregate JSON left the data host.

| Input / area cutoff | Score threshold | Calcification reference boxes matched | Boxes on 100 annotated normal images |
|---|---:|---:|---:|
| 512 / prior 0.002 | 0.45 | 10/115 (8.7%) | 42 |
| 512 / removed | 0.45 | 10/115 (8.7%) | 42 |
| 512 / prior 0.002 | 0.30 | 28/115 (24.3%) | 1,057 |
| 512 / removed | 0.30 | 28/115 (24.3%) | 1,057 |
| 512 / removed | 0.20 | 44/115 (38.3%) | 6,604 |
| 1024 / prior 0.002 | 0.45 | 13/115 (11.3%) | 207 |
| 1024 / removed | 0.45 | 13/115 (11.3%) | 286 |
| 1024 / removed | 0.30 | 42/115 (36.5%) | 4,322 |
| 1024 / removed | 0.20 | 51/115 (44.3%) | 12,075 |

At 512/0.45, 8/41 calcification targets in mass-containing images were matched,
versus 2/74 in images without a Mass annotation. At 1024/0.45, the corresponding
counts were 10/41 and 3/74. These groups describe image-level co-occurrence, not
reviewed spatial association. Detector boxes are class-agnostic abnormal proposals;
their match is localization evidence, not successful calcification typing.

The 512 ablation took 130.25 seconds; 1024 took 424.11 seconds. Higher resolution
increased proposal burden substantially for little sensitivity gain at the existing
operating point, and was not promoted. Lower thresholds were also rejected as an
unqualified fix. Removing the area cutoff fixes a demonstrated postfilter defect
but did not recover additional reference matches in this 512 cohort. This falsifies
the hypothesis that the cutoff alone explains the measured detection failure.

### Classifier diagnostic evidence

`tools/eagle_eye/evaluate_breast_classifier.py` evaluated 4,095 existing reference-ROI
feature rows from 1,000 publisher-test study groups. It reconstructed all saved
features/meta inputs and used the delivered ensembles, calibrators and thresholds.
This separates typing execution from detector misses. It does not regenerate ROIs
or view-pair features and does not measure deployed full-cascade performance.

| Target | TP / FN | FP / TN | Sensitivity | Specificity | PPV |
|---|---|---|---:|---:|---:|
| Mass | 227 / 10 | 74 / 3,784 | 95.8% | 98.1% | 75.4% |
| Suspicious Calcification | 107 / 8 | 70 / 3,910 | 93.0% | 98.2% | 60.5% |
| Focal Asymmetry, corrected calibration | 45 / 8 | 75 / 3,967 | 84.9% | 98.1% | 37.5% |

Before applying the recovered logistic calibration, the executable feature-corrected
candidate produced Focal Asymmetry TP=53, FN=0, FP=1,222, TN=2,820. Correct calibration
reduces FP to 75 at the unchanged threshold 0.30, trading sensitivity for the
intended calibrated probability scale. It does not make Focal Asymmetry classification
clinically adequate by itself. Mass threshold=0.35; calcification threshold=0.275.
Asymmetry remains unsupported by the delivered four-label model; no invented
class or relabelled Focal Asymmetry output was added.

Training-source/checkpoint independence is still unverified, prior prepared
validation/test overlap remains, and precomputed multiview features may contain
label-assisted pairing. Consequently these numbers are diagnostic, potentially
optimistic, and do not substantiate clinical accuracy or a new independent-test
claim. The inspected publisher-test data has now been used for engineering
comparisons; preserve a fresh reviewed qualification cohort for later selection.

### Verification and remaining work

Focused automated code/engine/transport checks: 60 passed, direct pytest exit 0.
Real serialized classifier synthetic execution: passed with isolated LightGBM 3.3.5.
Dataset detector and classifier runs: completed with aggregate results above.
`git diff --check` and new-script compilation: passed.
Plugin sync dry-run identified no owned Breast mirror update; global parity reports
unrelated EchoMind drift that was preserved rather than synchronized.
The existing source Test Control Server ping was unavailable, so no live GUI pass
is claimed. No source launch/login or production rollout was improvised.

Next model work must build a dedicated resolution-preserving calcification branch,
consolidate all reviewed targets per image, and compare it with the owned detector
on grouped development data and an independent reviewed qualification cohort.
Use full-breast/multiview context separately for Mass/Focal Asymmetry/Asymmetry.
The existing classifier is now executable under its recovered contract, but absent
Asymmetry supervision/head and weak detector weights cannot be repaired by schema
padding, threshold changes or postprocessing alone. Retain these as explicit open
model-quality gates rather than marking the whole Breast module fixed.
# Calcification cascade diagnostic at detector threshold 0.40 (2026-10-01)

The isolated corrected candidate was evaluated on 105 publisher-test calcification-positive images (115 reference regions) and 100 selected normal images, using 512-pixel FCOS inputs. No production deployment was performed. Detector localization at IoU >= 0.5 matched 15/115 regions (9/41 with mass present in the image; 6/74 without mass), and generated 139 boxes on the 100 normal images. All 349 candidate boxes completed ROI extraction, feature extraction and classification.

With the saved calcification classification threshold of 0.275, only 10/115 reference regions were both localized and typed as Suspicious Calcification (7 with mass and 3 without); 26 false calcification boxes appeared on 19/100 normal images. Raising the classification threshold also to 0.40 left 8/115 correctly localized and typed regions, with 20 false calcification boxes on 15/100 normal images. This measures structured predicted labels and reference-box overlap, rather than report text. These figures do not support acceptable calcification detection.

Classification rows were joined using row_index, with source paths and box geometry verified against normalized proposals. The initial scoring attempt required this recovery because the classification export omits image_id; completed model stages were reused without rerunning inference. Aggregate evidence: generated-files/eagle-eye/calcification-candidate-20261001/detector-040-cascade.json. Private intermediate data remains on the dataset host. Training independence remains unverified; companion views outside the selected cohort were not added, so this is a diagnostic subset and not a clinical qualification or complete-study acceptance test.
# Calcification repair investigation and data candidate (2026-10-01)

Status: development diagnostics and protected data preparation; no new trained weights or production rollout. The first priority is a dedicated suspicious-calcification detector, including findings coannotated with Mass. Broader benign calcification discovery and individual-punctum segmentation require additional reviewed labels; they are not represented completely by the current VinDr-Mammo suspicious-region boxes.

## Observed causes and unresolved lineage

- All 543 calcification annotation rows had accessible PNG sources and zero annotation/PNG dimension mismatches. At 512 pixels, reference-region width/height medians were 36.69/29.99 pixels; the tenth percentiles were 11.13/8.65 pixels. These are cluster-region dimensions, not individual calcification diameters. Downsampling is a plausible signal-loss mechanism, not a sufficient explanation proven by these dimensions.
- The surviving Linux FCOS_TRAIN.py defines 512-square inputs and one generic abnormal class. Its build_image_index_from_csv loops over annotation rows and assigns at most one box per image occurrence. Other lesions in the same image therefore receive incomplete targets. Of 543 calcification rows, 300 occur in images with multiple annotations. Delivered checkpoint lineage to this exact trainer remains unverified.
- Eight calcification reference boxes exceed image bounds, with maximum overflow 26.845 pixels; none are nonfinite or degenerate before clipping. The new preparation tool rejects them by default. An explicit candidate-only clipping option retains original coordinates and correction records for review; it does not discard these rows or relabel them as normal.

## Actual label-blind tiling experiment

tools/eagle_eye/evaluate_breast_tiling.py selected one image per study for 12 calcification-positive and 12 normal training-split studies, using deterministic hash ordering. It compared the same checkpoint on full-image 512 inputs against native 1536-pixel windows, stride 1152, resized to 512. Both variants used flip augmentation and NMS 0.5. Window selection never used reference boxes. This is development localization evidence, not independent testing or structured calcification-label accuracy.

| Detector threshold | Full-image matches / 13 targets | Window matches / 13 targets | Full-image normal boxes / 12 images | Window normal boxes / 12 images |
|---|---:|---:|---:|---:|
| 0.30 | 5 | 8 | 134 | 370 |
| 0.40 | 4 | 5 | 16 | 66 |
| 0.45 | 4 | 2 | 6 | 26 |

All 24 images completed, with 201 windows and 115.17 seconds of CPU execution. Do not promote this inference-only tiling configuration: the small localization gain at 0.40 is accompanied by much greater false-positive burden. Fine-tuning with matched window inputs and hard negatives is the next discriminating experiment, rather than assuming a larger input fixes the delivered model. Aggregate receipt: generated-files/eagle-eye/calcification-candidate-20261001/development-tiling.json.

## Prepared complete image targets

tools/eagle_eye/breast_training_targets.py prepares one protected record per image, retains every suspicious-calcification box, merges duplicate geometry without dropping coannotated Mass, and partitions all views of each study together. Source annotation SHA-256 is bound into the aggregate receipt. A first hash-only allocation was rejected because its calibration cohort contained zero coannotated Mass boxes. Version 2 stratifies training studies into calcification with coannotated mass, calcification without coannotated mass, other findings and normal.

| Partition | Images | Calcification-positive images | Calcification boxes | Boxes coannotated with Mass |
|---|---:|---:|---:|---:|
| Training | 12800 | 268 | 337 | 59 |
| Validation | 1600 | 34 | 46 | 8 |
| Calibration | 1600 | 35 | 45 | 8 |
| Previously inspected publisher test | 4000 | 105 | 115 | 15 |

The version 2 private manifest remains on Windows A100 under the isolated candidate's protected-data directory; only calcification-image-targets-v2.aggregate.json was copied locally. This is prepared data, not training readiness certification: review the eight geometry corrections, scanner/site balance and patient linkage. Study-level grouping is a proxy and cannot prove patient independence. The publisher test has already influenced development diagnostics and must not be described as a new untouched qualification set.

## Resource-bounded improvement sequence

1. Audit preservation of native DICOM bit depth, photometric inversion, intensity windowing, orientation and physical spacing. Train and serve the identical transform; compare normalization choices on development data rather than selecting them on publisher test.
2. Train a dedicated binary suspicious-calcification region detector using complete image targets and overlapping high-resolution windows. Preserve coannotated Mass positives. Record crop coordinates and target clipping; avoid treating partly observed clusters as clean negatives. Start with the known FCOS/FPN family to isolate data and input corrections; compare a P2/high-resolution feature detector only after this baseline is reproducible. For large clusters, retain whole-image context in a parallel branch.
3. Sample positive windows, normal tissue and hard negatives from vessels, skin, dense tissue and non-calcification findings. Candidate initial sampler fractions are 50/25/25; they are an experiment, not a validated optimum. Mine false positives only from training data and review them before reusing them. Keep all derived patches and study views in the same partition.
4. Evaluate on complete validation images without reference-guided crop selection. Track lesion sensitivity at preset false-positive operating budgets (candidate 0.5, 1 and 2 boxes/image), FROC, precision-recall and inference time. Report calcification with/without mass separately, plus size, density and scanner subgroups. Choose thresholds on validation/calibration data; bootstrap uncertainty by study until patient linkage is available.
5. If detection improves, re-evaluate the actual predicted-ROI classifier. Reference-ROI classification performance cannot qualify this cascade. Add a learned local morphology branch and CC/MLO/bilateral context as separate ablations; explicit Mass, Focal Asymmetry and Asymmetry outputs require their own supported training labels. The current classifier lacks an Asymmetry head.
6. For individual puncta or benign calcifications, inspect complementary datasets and licenses before acquisition, harmonize annotation semantics, and validate domain transfer. Do not train dense segmentation with rectangular region annotations as if they were exact punctum masks. Clinician-reviewed corrections become versioned training labels; they do not update live weights automatically.

The A100 read-only snapshot showed 40960 MiB total, 28577 MiB used and 11865 MiB free at 0% utilization. Existing services must retain their allocations. Pilot one-image mixed-precision updates and measure peak VRAM before any longer run; do not assume a batch size or H200 entitlement. Windows A100 has no GPU. No finding_annotations.csv or prepared train.csv was found under the known Linux /home/gadmin/Mammography workspace, so the current Windows manifest cannot yet be treated as a runnable Linux training dataset. Training requires a verified authorized data path/mount and a compatible isolated environment; no training job was launched by this investigation.

## Primary research references and task fit

- [VinDr-Mammo official release](https://physionet.org/content/vindr-mammo/1.0.0/) and [dataset paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC10182079/): suspicious region boxes; BI-RADS 2 findings are not comprehensively annotated, and the release has research/education access conditions. Review commercial use before product qualification.
- [Resolution-preserved patch division study](https://www.mdpi.com/1999-4893/16/10/483) motivates preserving small calcification detail; it does not demonstrate superiority on our checkpoint or cohort.
- [SAHI documentation](https://obss.github.io/sahi/) provides slicing/merging engineering patterns. Our observed inference-only tiling false positives prevent treating slicing as a ready fix.
- [CBIS-DDSM official collection](https://www.cancerimagingarchive.net/collection/cbis-ddsm/) provides calcification-related data and ROI information to inspect for complementary supervision. Digitized-film transfer and precise mask semantics need auditing.
- [NYU GMIC author repository](https://github.com/nyukat/GMIC) is a high-resolution global/local architecture reference, whose weakly supervised breast-cancer classification output is not a replacement for calcification detection or lesion typing.

Verification: 15 focused tests passed for complete targets, duplicate/coannotated labels, geometry policy, study stratification, previous feature/calibration repairs and small-lesion retention. Syntax and whitespace checks passed for the new preparation and evaluation tools. No runtime deployment or live GUI acceptance is claimed.
# Additional Windows/Dropbox mammography dataset inventory (2026-10-01)

## Implemented data structure follow-up

The later owner-authorized A100 run completed a 100-step BF16 research pilot and
digital transfer evaluation. Its paired results, caveats and saved candidate are
in the execution receipt at the end of
[the training workflow](BREAST_CALCIFICATION_TRAINING_WORKFLOW.md). This supersedes
the preparation-only status recorded below; production qualification remains pending.

The owner authorized arranging the calcification training structure. The protected
CBIS adapter processed all 1872 annotations: 1868 resolved, four quarantined, and
323 missing-role rows recovered using geometry/near-binary pixel checks. Combined
Mass/Calcification original train/test splits share 31 people; the new partition
reserves their test identity across tasks, including 18 calcification-training
people with 56 accepted annotations outside training/development. Source CSV and
manifest hashes are recorded in the aggregate receipt. This is candidate region
supervision, not clinical alignment approval or individual-punctum masks.

The proposed branch and experiment configuration is
`tools/eagle_eye/configs/calcification-region-v1.json`. A strict FCOS load, real
synthetic optimizer update, finite loss/gradients and exact checkpoint restore
passed using Torch 2.5.1+cpu. Nineteen focused guards passed. No new medical weights,
GPU clinical training job, MON-AI submission, runtime registration or deployment
was performed. The real patch-training executor is still to be implemented.

See [the training workflow](BREAST_CALCIFICATION_TRAINING_WORKFLOW.md) for data
partitions, runnable preparation/synthetic commands, task harmonization, quality
gates, resource preflight, evaluation and the proposed two-branch server contract.
Aggregate receipts are in
`generated-files/eagle-eye/calcification-candidate-20261001/cbis-calcification-v1.aggregate.json`
and `cbis-training-smoke.json`; all private records remain on Windows A100.

The owner requested a read-only search for other mammography datasets, particularly Dropbox. Searches covered the known data/project roots, user Dropbox locations and a bounded additional directory scan on C, D and F; this is not a claim of exhaustive disk imaging. No patient images, annotation rows or identifiers were exported, and no dataset was moved, converted or trained.

## Confirmed independent collection

CBIS-DDSM is present at `D:/AisanRahimi/mamography/mamographic data set/CBIS-DDSM/archive`. Its local tree contains eight CSVs, 22067 JPEGs and 1593 PNGs totaling 11.827 GiB. Those file counts include copies and derived data, not unique original examples. `jpeg` and `jpeg -original` each contain 10237 files; three sampled counterpart hashes were identical. `modified-jpg` contains 3186 JPEG/PNG files. There are no DICOM files within this inspected collection tree.

Original CSV annotations are under `csv - original`; the processed `csv` directory contains only two Mass CSVs with added `bbx` fields, and no processed calcification CSV. This establishes incomplete calcification preparation in this local copy, not proof of which collections contributed to the delivered Eagle Eye weights.

| Original subset | Annotation rows | Unique patient_id values | Malignant | Benign including benign without callback |
|---|---:|---:|---:|---:|
| Calcification training | 1546 | 602 | 544 | 1002 |
| Calcification test | 326 | 151 | 129 | 197 |
| Mass training | 1318 | Not counted in this audit | 637 | 681 |
| Mass test | 378 | Not counted in this audit | 147 | 231 |

Calcification CSVs include calc type, calc distribution, assessment, pathology and subtlety. Types include pleomorphic, amorphous, fine linear branching, punctate, coarse, vascular and skin categories. The 1872 calcification rows must not be described as 1872 unique patients, independent lesions or exclusively microcalcifications. Calcification train/test patient_id intersection was zero; a subsequent combined Mass/Calcification manifest must still audit person overlap across categories and aliases.

## Availability and mapping hazards

All 10237 dicom_info image_path entries resolve exactly to a file in `jpeg` when using the terminal directory/file components. All 1546 training and 326 test calcification full-image annotation series have local image/metadata matches. Sampled full images decoded as grayscale mode L at dimensions including 2761x5056, 2836x5386 and 3016x4616. This proves sampled readability and aggregate path availability, not complete pixel-level validation.

Calcification training crop/mask annotation series mapped for 1545/1546 rows. Explicit SeriesDescription matching identified the correct crop and mask role for 1544/1546 training rows. In the test annotations, only 44/326 full images have the expected full-image role string; the other 282 have an empty role string. All 326 crop references include a cropped-image metadata record, while 320 mask references have an empty role string and six have ROI mask images. Cropped and mask references often share a series directory containing more than one image. A naive first-file or role-string-only resolver is invalid.

Sampled test crop records decoded as small textured regions, whereas their associated empty-role records decoded as full-size sparse masks with 13-14 unique grayscale values and about 99.7% zero pixels. Sampled training masks had 15 grayscale levels. These are JPEG-converted masks, not preserved binary arrays; thresholding, dimensions, alignment and intended ROI semantics require explicit validation against original data before use. Do not treat region masks as exact individual-punctum truth.

## Other located material

- Dropbox mammography data root: `F:/Dropbox/Family Room/Ai-pacs share folder/mamography/mamographic data set`; its listed child collection is VinDr. The separate `FINAL_MAMMOPROJECT_DELIVERY` directory is also present in the share. The focused Dropbox file search found no CBIS/DDSM/INBreast/CMMD/CSAW archive or calc_case_description CSV matching the searched patterns.
- `D:/AisanRahimi/mamography/mamographic data set/MedgemmaMamography` has three JSONs and one 103-row test-mass CSV; no independent image collection was found within that tree. It is derivative evaluation material, not a second calcification dataset.
- `D:/monai/server/storage/datasets/vindr_breast_density` was located by directory name. Its content and lineage were not audited; the name alone does not establish additional calcification labels.
- Other Breast project directories include Final_BreastUpgrade/BreastVersion1/BreastVersion2 and MixedAPIBreast. They are project candidates, not evidence of new datasets or better qualified weights.

## Next data preparation decision

Use CBIS-DDSM as a complementary candidate for calcification discovery and morphology/distribution supervision, with benign and malignant labels retained separately. Build a protected person-grouped manifest resolving image/crop/mask roles by annotation linkage, metadata, geometry and pixel checks; quarantine unresolved rows rather than guess. Bind derived copies and views to the same person partition, inspect native source preservation and JPEG conversion, and evaluate transfer to digital VinDr/clinical mammography separately. Existing local data availability does not prove training readiness or clinical improvement. No training was launched.

Primary reference: [official TCIA CBIS-DDSM collection](https://www.cancerimagingarchive.net/collection/cbis-ddsm/) documents the separate mass/calcification subsets and original DICOM release. The downloaded local converted copy is distinct from that native release. The official release lists CC BY 3.0; preserve attribution and audit the provenance of local conversions and annotations before reuse.

## Bone Age demographic fallback (2026-10-04)

A Bone Age request with unknown DICOM sex previously reached the server and failed
before inference. The worker now uses valid DICOM sex first, then the configured
Reception endpoint on its background thread. Reception Gender is accepted only for
a single exact receptionId match; numeric sex values and names are never guessed.
If neither source is usable, a GUI-thread dialog requires an explicit Male/Female
choice. Cancel, stale study/patient context, and a five-minute unanswered prompt
submit no analysis. The original DICOM is not rewritten.

The authenticated request carries sex_provenance (source, study_uid, patient_id).
The server validates that binding against the staged DICOM, rejects conflicting
valid DICOM sex, and independently verifies Reception overrides through its own
configured Reception endpoint. Physician confirmations remain explicit authenticated
client assertions. Request files, result receipts and the client Bone Age JSON retain
provenance privately. The server advertises bone_age_demographic_confirmation=1;
older servers are rejected with an update message before an override is submitted.
This contract currently covers Bone Age sex, not arbitrary missing demographic fields.

Guard: tests/code/ai_imaging/test_bone_age_demographics.py. Five original guards
failed before implementation. Focused code, Qt dialog and packaging checks are
recorded below after completion. Live source GUI and Razi activation remain pending;
no service restart or patient rerun was performed. Existing MCP ping could not reach
the local Test Control Server. A human fresh-source launch/login was requested.

Verification receipt: 76 focused engine/remote/demographic/Qt and builder guards
passed (exit 0). The separate shared Slicer demographic-payload guard failed before
adding its lightweight validation dependency to builder/eagle_eye_client_payload.py.
Demographic helpers live under eagle_eye_remote, available to both editions without
model imports. The owned viewer mirror matches; global verification initially reported
one pre-existing EchoMind ai_chat_pages.py drift. The final check reports four
EchoMind drifts (three additional Secretary adapter changes occurred during this
shared-worktree session); all are outside this workstream and were preserved.
No installer was built, no Razi service was changed, and no live patient was re-run.
Next source/artifact acceptance: missing DICOM sex with exact Reception match; missing
Reception sex with explicit physician selection; Cancel; case switch; valid DICOM
conflict; receive and privately persist the completed result provenance. Both client
(Standard/ARM) and Eagle Eye Server builds need the updated shared contract.

### Razi developer-service activation (2026-10-04)

Owner explicitly requested the service update after the client's capability check
reported an old server. Deployed only the five backend files from a narrow delta
against the actual active 20261004-secretary-help-ticket revision, preserving its
recent Secretary/Help Ticket behavior. Twelve synthetic candidate checks passed
in the target environment. Restricted backup: bone-demographics-20261004.

The existing authenticated workstation client now receives
bone_age_demographic_confirmation=1 on 8002. Active file hashes and installed
validator/contract imports match; service and CRM are Running with one 8002 listener.
Configuration, models, weights, prompts, clinical data and GUI processes were not
changed. This closes the backend update requirement only; no real-patient inference
or source/artifact GUI acceptance is claimed. See the private deployment receipt
under generated-files/eagle-eye/bone-demographics-20261004.
