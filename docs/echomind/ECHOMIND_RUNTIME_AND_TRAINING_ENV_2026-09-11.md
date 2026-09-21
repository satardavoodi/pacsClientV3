# EchoMind runtime repair and isolated MONAI environment — 2026-09-11

## Current verified result

The owner authorized the necessary Linux-host changes. EchoMind on `lina100:8082`
is running with **health ok**, **status ok**, the main model, transcription and
database ready, and **zero active sessions** at final restoration. MedGemma remains
disabled by the existing configuration. NVIDIA 595.91.07 is aligned with the
loaded kernel module; no additional driver or OS changes were made in this phase.

This supersedes the earlier degraded-health and chat-closure defect notes in
`ECHOMIND_GPU_MAINTENANCE_2026-09-10.md`.

## Application fixes

Only `/home/gadmin/EchoMind/MedicalReporterS.py` changed on the Linux application.
No packaged workstation source or unrelated dirty worktree change was edited.

1. New chat sessions initialize optional `assistant_output`. The ten-message
   closure reads optional report/assistant fields safely, including historical
   chat-only sessions. Previously the closure raised KeyError and left a read-only
   session in the counter.
2. Health checks the current `llm_main` backend and the actual enabled component
   flags. It no longer requires the obsolete `standardize_llm` attribute. Failed
   enabled components still produce degraded status; disabled MedGemma does not.
   `models_loaded` is now declared in the response schema so Pydantic does not
   discard those component results. A failed GPU memory query is reported as
   degraded rather than an unhandled health endpoint exception.

Seven isolated endpoint regression tests passed. Before the patch, three failed
assertions and one endpoint exception reproduced the defects. The tests execute
the actual endpoint ASTs with synthetic model/session state and stub database
functions; they do not import model weights or touch the application database.

The source was staged, compiled and tested before atomic replacement. Backups
remain protected on the Linux host at:

```text
/home/gadmin/monai-lumbar/ops/gpu-window/runtime-fix-20260911T100217Z/
```

Before SHA256: `17e2fc3419d6575e100dfb0bd8e2339942325adb32133b4f87d59cac4cf901c4`.
After SHA256: `79a2f1c3cd489b0751bd3b92dec4cd0e383f532222d9a662497ee5485df87e98`.
Do not export the full source backup or private restart environment into reports
or repositories. To roll back, restore the protected before-file after verifying
the current after-hash, then use a controlled restart and verify API readiness.

The first restart was explicitly authorized after confirming the only server
session was the owned synthetic ten-message probe. No unrelated session was
interrupted. After restart, one actual text generation and nine greeting requests
all returned HTTP 200; the tenth request closed and removed the session. A synthetic
audio request returned HTTP 200 and nonempty transcription. The final session
count was zero. These execution checks do not measure language or diagnostic
accuracy; synthetic API probes may retain their own normal test records.

## Isolated training environment

Use this interpreter for the lumbar worker:

```text
/home/gadmin/monai-lumbar/env-training-20260911/bin/python
```

Verified Python 3.10.12, Torch 2.11.0+cu130, MONAI 1.6.0, NumPy 2.2.6,
SimpleITK 2.5.2 and pytest 8.4.2. The environment has no system-site inheritance,
user site is disabled, and `/home/gadmin/.local` is absent from its import path.
`pip check` reports no broken requirements. Packages came from the official
PyTorch wheel index and PyPI; EchoMind's shared Python packages were not modified.

Exact installed dependency pins:
`/home/gadmin/monai-lumbar/ops/gpu-window/training-environment.lock.txt`.
The old `/home/gadmin/monai-lumbar/env` remains available as a historical development
overlay. Its unrelated dependency conflicts were not repaired in place. Existing
model-acquisition tools may still use that overlay; this new environment is for
the verified lumbar training worker, not every tool in the estate.

The maintenance controller now dispatches its bounded training test through the
isolated interpreter and refuses a test window if that interpreter is missing.
Eight existing controller guards and eight MONAI input/loss guards passed.

## GPU training-path verification and restoration

A bounded full DenseNet121 and spatial-fusion test ran in the isolated environment
with synthetic pixels/targets, float32 and 27 planes per sample at 224 x 224.
Real forward/backward/AdamW updates passed at all tested batches:

| Batch | Peak allocated GiB | Peak reserved GiB |
|---|---:|---:|
| 1 | 3.44 | 3.55 |
| 2 | 6.78 | 6.90 |
| 4 | 13.48 | 13.61 |

Batch 1 also saved and reloaded a checkpoint. Five original pilot inputs separately
passed inference. These are the historical pilot shape and a short capacity test,
not the maximum shape of the new cohort or a convergence/accuracy result. There
were **zero supervised patient optimizer steps** and no clinical predictions.

EchoMind stopped at **10:06:06 UTC**, GPU allocation reached zero, the test exited
0, and restoration was verified at **10:06:53 UTC**. The controller receipt records
`restored=true`. Health/status returned ok with the main model, transcription and
database ready; GPU memory was 28,005 MiB used and 12,437 MiB free.

## Dataset boundary and evidence

The 291-case, 1,885-candidate, 5,859-volume review dataset remains on C. Anatomy and
image-reference labels still require review; no train/validation release is
qualified merely by these infrastructure tests. Use
`C:\AI-PACS-Datasets\REGIONAL_DATASET_REVIEW.html` and the review-to-release guide.

Aggregate receipts and the dependency lock are retained under:

```text
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\infrastructure-readiness-20260911\
```

Key files: `runtime-fix-receipt.json`, `runtime-fix-live-verification.json`,
`runtime-fix-asr-verification.json`, `isolated-environment-verification.json`,
`training-environment.lock.txt`, `isolated-training-window.json`, and
`isolated-training-profile.json`. A matching runbook is maintained in control-node
documentation. No patient data or credentials are embedded in this document.
