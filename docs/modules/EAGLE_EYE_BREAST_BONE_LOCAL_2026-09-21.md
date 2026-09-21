# Breast and Bone Age: server-edition engine integration

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
