# EchoMind restart test and native MONAI input staging - 2026-09-11

## Explicitly requested restart test

The owner requested a fresh EchoMind off/on test before starting lumbar training.
The existing detached `test-window` controller was used on Linux `lina100` only.
The Windows AI node and production PACS were not changed. No driver, application
source, shared Python dependency, model weight or boot configuration was changed.

| Event | UTC / observation |
|---|---|
| Baseline | 12:26:05; health/status ok, zero sessions, 28,005 MiB GPU allocation |
| Stop verified | 12:26:08; API unreachable, GPU allocation 0 MiB |
| Training-path test | Exit 0; synthetic forward/backward/AdamW updates passed |
| Restore verified | 12:26:55; approximately 47 seconds after confirmed stop |
| Restored service | Health/status ok, GPU 0 loaded, zero sessions |
| Restored components | Main model, transcription and database ready |
| GPU after restore | 28,005 MiB used / 12,437 MiB free |

The receipt records `restored=true` and `test_exit=0`. The newly generated startup
log contains zero traceback markers and zero ERROR lines. The main application
source hash remains
`79a2f1c3cd489b0751bd3b92dec4cd0e383f532222d9a662497ee5485df87e98`.
MedGemma remains disabled by the existing configuration. No new text/audio API
acceptance probe was performed in this cycle; the evidence covers restart,
component loading and the existing synthetic GPU training path.

The full DenseNet121/spatial-fusion test used the isolated environment, float32,
27 synthetic planes per sample and a 224-pixel canvas. Optimizer updates passed
at batches 1, 2 and 4; peak allocated memory was 3,520 / 6,947 / 13,803 MiB.
The batch-1 checkpoint reloaded successfully. Five original pilot inputs also
passed forward execution. There were zero supervised patient optimizer steps.

The stop/start controls and restoration procedure remain documented in
[the maintenance runbook](ECHOMIND_GPU_MAINTENANCE_2026-09-10.md). The service was
restored immediately after this bounded test; it was not left stopped while
waiting for clinical labels.

## Image-only dataset staging

All **291 prepared cases / 1,885 candidate regions** were packaged from C and
transferred over the existing authenticated SSH connection to:

```text
/home/gadmin/monai-lumbar/staged-candidates-20260911T122940Z/
```

The directory is mode 0700. The archive includes only native NIfTI images and an
allowlisted geometric candidate manifest. Reception reports, earlier LLM outputs,
original DICOM headers and local source-linkage records are not in this archive.
Native-image headers had already been stripped during candidate preparation.
Frame identifiers are hashed, and person groups remain pseudonymous.

There are **5,859 group references to 5,858 unique image files**. The one repeated
file is deduplicated by content hash. Identical-image checks found zero hashes
shared across different person groups or assigned partitions. This check does not
replace clinical identity adjudication or detect every possible near-duplicate.

Archive size: **4,978,944,000 bytes**. SHA-256:
`ca44fe4a9e920c91588016acb61e07d020660e60e0a3d3288c0286dd0b59fc2a`.
Manifest SHA-256:
`d9ed383dfe95edc447b3680ebefe5e8c2d9b650b12afba9392a85ca880917a13`.
Linux had 351.59 GiB free before staging. Source images on C were not modified.

The staged manifest explicitly uses `candidate_only` samples with unassigned
anatomical levels, empty targets and empty training/validation/test sections.
Assigned patient partitions are retained separately: 232 train, 29 validation,
29 test and one development-only patient. Staging does not promote any candidate
to an anatomically reviewed region or a reference label.

## Worker validation

The archive checksum and member allowlist are checked before extraction. The
isolated Linux interpreter then runs the existing `LumbarDataset` loader on CPU,
with four Torch threads and two SimpleITK threads, while EchoMind remains running.
The loader checks every image hash, native array shape, slice count, RAS affine,
shared reference and required axial T2 / sagittal T2 views; it applies the actual
worker's in-plane resize/padding and target-mask encoding.

Validation completed successfully in **165.35 seconds**: all **1,885 samples**
loaded, including **49,001 native planes**, with zero activated patient targets
and zero optimizer steps. The largest candidate contained **137 planes**. The
manifest checksum after transfer matches the local checksum. All 291 person
partitions were consistent, and the worker correctly rejected clinical training
on this unreviewed manifest. The final receipt is `validation.json`; a protected
local copy is `remote_validation.json` in the staging receipt directory.

The earlier synthetic GPU test used 27 planes, so its batch-memory figures do
not qualify the largest candidate or a reviewed union of multiple packets.
Profile the largest actual reviewed release input before selecting the final
training batch size. CPU loading is not model convergence or diagnostic accuracy.
EchoMind health/status remained ok with zero sessions at the final check.

## Actual training prerequisite

The fresh local review check found **zero reviewed case files and zero drafts**.
The staged manifest is deliberately rejected by `validate_training_manifest` with
`reviewed_train_and_validation_splits_required`. No clinical training job or
diagnostic checkpoint has been created.

The next required input is clinician image-reference review using the local
workbench at `http://127.0.0.1:8841/`. Map complete groups to anatomy, record observed
targets and native image evidence, then save reviewed labels. The existing
`Prepare-Reviewed-Training.cmd` exports only eligible reviewed regions. Start
training after that release passes worker validation in an authorized GPU window.
The initial 12-case review queue is a protocol calibration batch, not proof of
adequate diagnostic model performance. Do not activate report-only or unmentioned
findings as image-reviewed targets to bypass the empty-label gate.

## Protected evidence and tools

Local restart receipt:
`C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\restart-training-preflight-20260911\restart-window.json`.

Local input staging receipts and original-to-staged linkage:
`C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\linux-input-staging\20260911T122940Z\`.
The linkage file stays on C; it was not included in the remote archive.

Tools under the protected dataset's `tools` directory:

- `read_current_gpu_window.ps1`: aggregate restart and synthetic profile receipt.
- `package_native_input_staging.py`: immutable image-only staging archive.
- `stage_native_inputs.ps1`: scoped directory creation, transfer and detached validation.
- `validate_staged_native_inputs.py`: integrity, native loader and supervision checks.
- `read_staged_input_validation.ps1`: progress and sanitized EchoMind startup/health.

This document is mirrored in the control-node infrastructure documentation. No
patient images, reports, identifiers, private launch environments or credentials
are embedded in either repository document.
