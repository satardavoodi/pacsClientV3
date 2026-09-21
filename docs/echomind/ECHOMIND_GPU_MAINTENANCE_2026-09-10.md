# EchoMind A100 maintenance and MONAI training-capacity verification

## Latest update: runtime repair and isolated training environment

The later 2026-09-11 operation fixed the health and chat-closure defects, created
an isolated training environment, passed full synthetic optimizer/checkpoint
tests and restored EchoMind with health/status ok and zero sessions. See
[the current runtime and environment runbook](ECHOMIND_RUNTIME_AND_TRAINING_ENV_2026-09-11.md).
Earlier degraded-health and unresolved-defect descriptions below are historical.

## Driver alignment completed: 2026-09-11

After the owner requested repair, the Linux guest was restarted with a one-time
GRUB selection of the existing kernel **5.15.0-186-generic**. DKMS had already
installed NVIDIA **595.91.07** for this kernel. No driver package, Python package,
EchoMind source file or VM hardware was changed during the repair. The loaded
driver and NVML now agree; `nvidia-smi` succeeds.

Before restart, only the captured EchoMind process tree held GPU devices; Docker
and rootless Podman had no running containers, SSH was enabled, disk space was
adequate and the private restart recipe existed. A one-time systemd recovery unit
restored EchoMind automatically. Recovery succeeded at **09:35:49 UTC** with
`/status=ok`, GPU 0 loaded and 28,005 MiB used / 12,437 MiB free. The temporary
`echomind-maintenance-recovery.service` is now **disabled without stopping it**;
its existing process group still hosts the restored application. Do not stop that
unit casually. The existing manual control remains the supported recovery route.

Post-repair checks:

- No failed system services. PackageKit and UPower were inactive after boot;
  these were previously running on-demand services, not failed application units.
- All 20 EchoMind Python source hashes matched the pre-reboot baseline.
- Startup reported `unified_model`, `transcription` and `database` ready, with no
  startup traceback or ERROR marker. The prior `/health=degraded` result remains.
- A synthetic chat request returned HTTP 200 and generated 256 completion tokens.
- Locally synthesized speech returned HTTP 200, a nonempty transcript and about
  2.30 seconds of transcription work. This tests execution, not language accuracy.
- A fresh CUDA matrix/reference check and convolution passed.
- Three newly prepared patient input packets passed full DenseNet121 forward
  execution across all 15 heads; peak allocated GPU memory was about 125 MiB.
  No supervised optimizer steps or clinical predictions were produced.

A separate existing application defect was exposed when closing the synthetic
chat at its ten-message boundary: `KeyError: 'assistant_output'` returns HTTP 500
for a chat-only session. The unchanged source constructs its session dump using
that optional key directly. The synthetic session can remain in the session
counter until normal pruning (default four-hour TTL). Do not bypass the control's
session guard. This repair does not claim that all application API workflows are
error-free. No existing patient session or database record was edited; the
synthetic API probes may persist their own test records through normal application
behavior.

Aggregate evidence is in
`C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\infrastructure-readiness-20260911`:
`driver-alignment-verification.json`, `post-driver-chat-probe.json`,
`post-driver-asr-probe.json`, and `candidate-input-probe-result.json`.
The baseline and one-time repair state remain protected on the Linux host at
`/var/lib/aipacs-driver-alignment-20260911`.

The repair follows the documented kernel/userspace mismatch explanation in the
[Ubuntu NVIDIA driver guide](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/).
This host-specific successful test is the compatibility evidence; no claim of
universal driver compatibility is made.

## Earlier preflight before repair: 2026-09-11

**A new maintenance window was not started.** EchoMind remains running with
`/status=ok`, GPU 0 loaded and zero active sessions at the check. The previously
observed `/health=degraded` state persists. Clinical training has not started.

The loaded NVIDIA kernel module reports **595.84**, while the installed module
and compute package are **595.91.07**. `nvidia-smi` now exits 18 with an NVML
driver/library mismatch. A fresh Torch process still enumerates one CUDA device,
but warns that NVML cannot initialize; this does not establish that a stopped
vLLM process can safely restart. No driver reload, host reboot or service stop
was performed. Driver alignment and successful GPU monitoring must precede the
next controlled maintenance window; a host restart has broader impact than an
EchoMind-only interruption and was not performed under that authorization.

The external controller now reports `gpu_query_ok` and `gpu_query_exit` and
rejects `stop` and `test-window` before process targeting if the GPU query fails
or its numeric response is invalid. The restart operation remains available.
The updated controller was copied to the Linux operations directory. Eight
focused tests passed, including both interruption entry points and malformed
NVML results. The missing guard in the previous controller was reproduced with
isolated AST execution and fake process functions; no live stop was used to test
this defect. Guard: `C:\AI-PACS-Datasets\lumbar-mri\v0.1\tools\test_echomind_gpu_preflight.py`.

The dataset gate is also unchanged: 1,460 level records, five regional input
packets, zero active reviewed training labels, and no released train/validation
split. Five levels remain development-only and 1,455 unassigned. The successful
synthetic capacity test below is historical evidence, not supervised training.

Driver evidence: `C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\infrastructure-readiness-20260911\gpu-driver-preflight.json`.

## Previous successful maintenance window

Verified operation: **2026-09-10**. The owner authorized a temporary EchoMind stop,
a bounded training-path test, and restoration immediately afterwards. EchoMind
was restored successfully. This is an operational record, not a clinical model
validation or an authorization to interrupt future unrelated work.

Maintain this document in both project locations:

- AI-PACS: `docs/echomind/ECHOMIND_GPU_MAINTENANCE_2026-09-10.md`.
- Control node: `D:\control pc node\docs\infrastructure\ECHOMIND_GPU_MAINTENANCE_2026-09-10.md`.

## Machine and process identity

| Item | Verified value |
|---|---|
| GPU machine | `lina100`, hostname `gpu`, `192.168.3.92` |
| VMware identity | `Ubuntu-22.04-new`, physical host `192.168.5.201` |
| GPU | NVIDIA A100-SXM4-40GB |
| EchoMind entry point | `/home/gadmin/EchoMind/MedicalReporterS.py` |
| Working directory | `/home/gadmin/EchoMind` |
| Original launch | `python3 MedicalReporterS.py`, detached direct process |
| Restart interpreter | `/usr/bin/python3`, Python 3.10.12 |
| API | TCP 8082; `/status` and `/health` |
| GPU occupants | EchoMind parent and its vLLM EngineCore child |
| Service management before this work | No corresponding systemd service or tmux session found |

The machine named **Windows A100** (`wina100`, `192.168.99.59`, VMware name
`A100 gpu`) has no NVIDIA GPU. Its EchoMind endpoint on 8085 is separate and was
not stopped. Windows PACS listeners on 104 and 8000 were not changed. Do not
restart either VM to release GPU memory.

## Verified resource and execution context

- Linux: 16 vCPU, 96 GiB configured RAM (94.3 GiB visible), about 84.4 GiB
  available and 356.5 GiB free filesystem space at the preceding audit.
- Windows: 16 vCPU, 96 GiB RAM, about 50 GiB available; D had 132.3 GiB free.
- Both AI VMs use `datastore1 (1)`, with about 1,068.6 GiB free at that audit.
- Their physical host had about 92% memory usage; the Windows VM had 755 MiB
  hypervisor-swapped memory. Do not increase VM RAM or start broad RAM caches
  based only on guest free-memory figures. High host allocation is intentional.
- The full-capacity test used MONAI 1.6.0 and Torch 2.11.0+cu130 in
  `/home/gadmin/monai-lumbar/env`. This is a development overlay inheriting
  system packages; its dependency check remains red. No shared packages were
  changed for this operation. Long reproducible training still requires a
  pinned isolated environment.

These are dated measurements, not current reservations. Recheck resources before
each run. The successful test does not integrate the MON-AI dashboard: its
simulated training executor and its default-port conflict remain separate work.

## Controls and saved locations

On the control PC, open these files in Windows Explorer:

| File | Effect |
|---|---|
| `C:\AI-PACS-Datasets\EchoMind-GPU-Status.cmd` | Read service and GPU status |
| `C:\AI-PACS-Datasets\EchoMind-GPU-Stop.cmd` | Stop the identified EchoMind process tree; leave it stopped |
| `C:\AI-PACS-Datasets\EchoMind-GPU-Start.cmd` | Start EchoMind with the saved configuration and wait for readiness |

Their PowerShell entry point is:

```powershell
& 'C:\AI-PACS-Datasets\EchoMind-GPU-Control.ps1' -Action status
& 'C:\AI-PACS-Datasets\EchoMind-GPU-Control.ps1' -Action stop
& 'C:\AI-PACS-Datasets\EchoMind-GPU-Control.ps1' -Action start
```

Use `stop` and `start` only for the intended maintenance window. Manual `stop`
does not schedule an automatic restart. For the same bounded synthetic capacity
test with an automatic restoration attempt:

```powershell
& 'C:\AI-PACS-Datasets\EchoMind-GPU-Control.ps1' -Action test-window
```

The wrapper uses `D:\control pc node\bin\cssh.cmd`, the existing SSH key and
the `lina100` alias, with automatic port forwards disabled. Do not substitute
the built-in Windows OpenSSH executable; its redirected-output behavior is a
known control-node problem.

Remote directory: `/home/gadmin/monai-lumbar/ops/gpu-window`.

| Remote file | Purpose |
|---|---|
| `echomind_gpu_control.py` | Scoped status, stop, start and test-window supervisor |
| `profile_training.py` | Synthetic full-backbone training-capacity test |
| `restart-private.json` | Saved launch arguments, working directory and process environment |
| `control.lock` | Prevent overlapping maintenance commands |
| `last-start.json` | Most recent launched PID and timestamped startup-log path |
| `window-result.json` | Before/stop/after evidence, test exit and restoration result |
| `training-profile.json` | Memory measurements and test scope |
| `restore-verification.json` | Component startup and unchanged-source verification |

The private restart recipe remains on the GPU host, mode **0600**, under a
**0700** directory. Never copy its contents into either repository, a report,
chat, issue or shared artifact. Startup logs can contain application data and
must also remain protected. Only aggregate receipts were copied off the host.

Local source copies of the two Python tools remain in
`C:\AI-PACS-Datasets\lumbar-mri\v0.1\tools`. The scripts are external operational
tools, not AI-PACS runtime modules or installer payloads.

## Stop, restoration and recovery contract

1. Before the measured interruption, save the actual process launch/environment,
   record source hashes and API/GPU baseline, and check restart dependencies.
   The import preflight succeeded before the process was stopped. The old
   process executable was marked deleted in `/proc`; the replacement Python
   executable and required imports were checked before relying on a restart.
2. Stop refuses reported active sessions or ambiguous EchoMind roots. It
   identifies the entry point and working directory, records PID start times
   and descendants, and signals only that captured tree. No broad `pkill`
   or machine-wide GPU reset is used.
3. Graceful termination is attempted first; the controller has a bounded
   escalation for still-matching captured processes. Before testing, the API
   must be down and residual GPU allocation must be below the controller's
   1,024 MiB guard. Unknown GPU workloads are not killed.
4. Start avoids duplicating a known EchoMind root. It uses the saved environment
   and working directory, starts a detached process and preserves a new
   timestamped log instead of truncating the old application log.
5. Readiness requires `/status` to return `ok` and GPU 0 to be loaded, with a
   600-second startup timeout. Inspect component startup as well: a listener
   alone is not proof of model readiness.
6. `test-window` runs in a detached supervisor, limits the test to 240 seconds,
   terminates its own timed-out test group, and attempts restoration in
   `finally` on success, failure, timeout or handled interruption. SSH
   disconnection does not own the supervisor lifecycle.
7. Completion requires **`restored: true` and `test_exit: 0`** in
   `window-result.json`. A returned supervisor PID only proves dispatch.

This is not a boot service or a guarantee against host failure or an uncatchable
process kill. If restoration fails, inspect `last-start.json` and its protected
log, then use `start` to recover after resolving the stated cause. Do not create
a second server or kill an unrelated port owner. Recheck source, launcher,
environment and dependencies and refresh the private recipe before another
window if that configuration has changed. The saved recipe is a launch snapshot,
not a pinned backup of every dependency or model.

## Completed window and restoration evidence

| Event | UTC time / result |
|---|---|
| Baseline | 13:38:14; zero active sessions; `/status=ok`, GPU 0 loaded |
| Stop confirmed | 13:38:17; API down, GPU allocation 0 MiB |
| Restart launched | 13:38:29 |
| Restoration verified | 13:39:14; approximately 57 seconds after confirmed stop |
| Before GPU memory | 28,141 MiB used; 12,301 MiB free |
| After GPU memory | 28,005 MiB used; 12,437 MiB free |
| Components after startup | Main model, transcription and database loaded |
| MedGemma | Disabled in the existing launch configuration; remained disabled |
| Startup log | No tracebacks or ERROR markers in the new startup log |
| Application source | Python source hashes unchanged |

`/health` returned **degraded before and after** this operation while `/status`
returned **ok**. This pre-existing health-reporting issue was not repaired or
treated as a new regression. Component-startup logs supplied additional evidence.
No synthetic request was sent through the clinical API; this is startup and
model-load verification, not a complete user-workflow acceptance test.

## Full training-path test

Full MONAI DenseNet121 plus spatial fusion, **float32**, AdamW, 224 x 224 canvas,
27 synthetic planes per sample (5 axial, 11 sagittal T1 and 11 sagittal T2).
All 15 heads contributed to the synthetic loss. Forward, backward, finite
geometry gradients and actual optimizer weight updates passed at all sizes.
Batch 1 also saved and reloaded a state dictionary.

| Batch | Peak allocated GPU GiB | Peak reserved GPU GiB | Optimizer update |
|---|---:|---:|---|
| 1 | 3.44 | 3.55 | Passed |
| 2 | 6.78 | 6.90 | Passed |
| 4 | 13.48 | 13.61 | Passed |

MiB and GiB are binary units. These are single-step synthetic capacity
measurements, not steady-state throughput, accuracy or convergence. Five real
regional inputs separately passed inference; there were **zero supervised
patient optimizer steps** and no clinical predictions saved. The synthetic
checkpoint is explicitly non-diagnostic and must not be registered as a trained
lumbar model.

Batch 4 fits the tested shape with EchoMind stopped. Start reviewed-data training
conservatively and profile the largest intended input; more slices or higher
resolution can change peak memory substantially. This test does not qualify
concurrent training alongside EchoMind. Reviewed per-target labels, patient-level
split isolation, input coverage, a reproducible environment and real application
worker integration remain prerequisites for the clinical development pipeline.

## Evidence and navigation

Aggregate receipts are retained at:

```text
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\gpu-maintenance-20260910\window-result.json
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\gpu-maintenance-20260910\training-profile.json
C:\AI-PACS-Datasets\lumbar-mri\v0.1\research\gpu-maintenance-20260910\restore-verification.json
```

Human-readable local entry points:

- `C:\AI-PACS-Datasets\ECHOMIND_GPU_MAINTENANCE.html`
- `C:\AI-PACS-Datasets\MONAI_COMPUTE_READINESS.html`
- `C:\AI-PACS-Datasets\MONAI_FIRST_CASE.html`

No patient identifiers, images, reports, private environments or model weights
are embedded in this repository document. Documentation updates do not rerun
the maintenance window or change the current service state.
