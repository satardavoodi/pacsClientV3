# Eagle Eye server/client phase 1

Date: 2026-09-21. Status: source implementation and synthetic transport/model
verification; not deployed, not a qualified installer or clinical acceptance.

## Live hosted-server check (2026-09-22)

### Corrective execution pass

The subsequent owner-authorized fix identified the shared startup failure: the
development venvs referenced a user-profile `uv` interpreter path virtualized by
the Codex MSIX package. The desktop-launched workstation could not see that alias.
Both launchers exited 103 before model initialization. `prepare_breast_bone.py`
now records the resolved physical base-interpreter home before sealing the bundle.
Both private bundles were rebuilt and hash-sealed; their weights were not changed.
They remain development venvs, not portable release payloads.

The engine service now retains at most 64 KiB of failed child output in a private
server diagnostic file, outside completed artifacts. The failure remains explicit
and no failed result is published. Bone Age accepts selected HAND/WRIST acquisition
tags, preserves the original DICOM and verified sex, and returns a coverage-review
warning for WRIST rather than treating the tag as proof of complete anatomy.

Both authorized studies subsequently succeeded through the already-running,
desktop-owned authenticated API. The actual client downloaded and validated the
derived artifacts: one Bone Age prediction and four-image Breast detection output.
Breast classification remains unavailable because of the previously documented
incompatible stacker schema; successful transport/detection is not full classifier
qualification. No negative classification is fabricated.

The native Bone Age Choose Function workflow was also exercised after loading its
image into the Eagle Eye viewport. Its server job succeeded and the completion
dialog and Bone Age review tab displayed the returned prediction. No reviewer
validation, correction, training submission or PACS report publication was made.
The native Breast Choose Function workflow also completed. Its first result exposed
a review-binding defect: exporting only a SOP filename discarded the series-parent
identity used by the existing viewer. The worker now prepares verified portable
`SeriesInstanceUID/SOPInstanceUID.dcm` references before publication; the publisher
also validates that contract. No server disk paths or source pixels are transferred.
A synthetic export guard failed before this correction. Idempotent preparation and
foreign-source rejection are covered. A fresh native rerun then displayed the two
returned detection rectangles and selectable findings on the corresponding image.
The classification-unavailable message remained explicit; no clinical classification
or reviewer approval was fabricated.

Both native workflows ran against the existing human-launched workstation without
restart or hot reload: each job imports its model adapter in a new owned process.
Standalone Standard on another PC, LAN/TLS deployment, other model runs and clinical
equivalence remain separate gates. The revised Bone bundle passed a fresh actual-
model synthetic smoke and received a revision-matching qualification receipt;
Breast full classifier qualification remains blocked.

Final focused verification: 60 tests passed, exit 0; 470 existing mirror pairs matched
with no mirrored source drift. Synthetic fail-before checks reproduced WRIST
rejection and lost child diagnostics; the runtime-home guard verifies canonical
base resolution and rejects a missing interpreter. Tests use no clinical inputs.

### Initial failed observations, superseded by the corrective pass above

This inspection supersedes the earlier missing-source and unreachable-control
observations below. The human-launched source workstation owns the authenticated
loopback listener on port 8042. Documented control-client ping/action discovery
succeeded; capabilities advertise the seven implemented adapters. Both desktop
launchers exist with their respective Standard and Eagle Eye Server arguments.
Only the Server launcher enables the explicitly authorized test control endpoint.
The workstation was not restarted or duplicated by the agent.

The authorized studies were opened through the existing PACS workflow. Server-side
cache inventories became complete and study identity was checked before submitting
reference-only requests through the real hosted API. No identifiers or clinical
results are retained in this report.

- Breast: two hosted API attempts failed in the isolated engine subprocess; neither
  published completed artifacts. The current service discards child output, so the
  underlying child exception remains unknown. Separate private diagnostic runs of
  the same validated source inputs succeeded, including the actual engine service
  with an offscreen Qt application. These runs processed four inputs but returned
  `classification_status=unavailable`. They do not prove the hosted API or viewer
  result-display path works. The previously recorded classifier schema mismatch
  remains unresolved.
- Bone Age: the hosted request failed before inference because source metadata
  identifies `BodyPartExamined=WRIST`, while `validate_sources` requires `HAND`.
  No metadata was rewritten and the anatomical validation was not bypassed. The
  intended input/confirmation contract needs correction and verification before
  this workflow can pass.
- Request queuing and explicit failure propagation were observed. A functioning
  listener and capability listing are not model-readiness or clinical acceptance.
  The other five models were not run during this inspection. No separate Standard
  GUI, remote-PC/LAN exchange, or successful analysis-button/result-display workflow
  was verified. No runtime fix, release build or Reception deployment was performed.

## Explicit desktop roles (2026-09-22)

This section supersedes the earlier inspection's missing desktop-service binding.
Two explicit source launch modes are implemented:

```powershell
# Eagle Eye workstation plus its owned local analysis service
.\run_app.ps1 -EagleEyeServer

# Standard workstation using the configured Eagle Eye service
.\run_app.ps1 -Standard
```

Both accept `-EagleEyeConfig PATH`. The default private configuration files are
`generated-files/eagle-eye/deployment/server.json` and `client.json`, prepared on
this PC using `tools/eagle_eye/prepare_local_server.py`. They contain file references
to a private token, not embedded credentials. Existing configuration is preserved.
These are local PC settings, not files to commit or copy blindly to Reception.

For authorized live automation, the human launches
`.\run_app.ps1 -EagleEyeServer -TestServer` and signs in. Normal launches still keep
the test endpoint disabled. No existing workstation instance is automatically
closed, relaunched, hot-reloaded or duplicated.

Server mode starts a loopback listener owned by the workstation before Qt startup.
Its UI and Slicer use that listener through the same reference-only client as
Standard. Model subprocesses execute locally without recursively calling the API.
Explicit shutdown closes the listener and cancels its jobs before the workstation's
hard-exit path. A occupied listener is rejected before job-store recovery. Desktop
hosting is loopback-only in this phase; the standalone server command remains the
TLS/LAN deployment path for Reception. Standard does not start a model service.

Breast and Bone Age UI workers now exclusively use the common job client. The legacy
Breast/Bone URL branches and their configuration prechecks are removed. Unavailable
configuration or an incomplete server source fails explicitly, never by calling the
old services. The endpoint settings for unrelated features were not modified.

Local desktop deployment uses `pacs.type=workstation-cache`, an explicitly configured
read-only server catalogue and allowed source directory. Inputs must already be
completely downloaded by the existing PACS workflow on the server PC. The adapter
checks series identity, expected file count and the existing staging checks before
inference. It does not create a new downloader, upload client pixels, modify the live
database or guess completeness when the expected count is zero. Reception can use
the existing `pacs-storage` adapter against its authoritative accessible storage.

Verification: both legacy-network guards failed before the edit and passed after.
The broader runtime/edition selection passed 255 tests (exit 0); after the final
listener-order correction, the 26 role/transport guards passed (exit 0). Four stale
packaging fixtures were updated to meet the concurrently introduced Slicer startup
parity contract; no other workstream's runtime implementation was changed.
470 plugin mirrors matched and the launch script parsed successfully.

Actual CPU Breast and Bone Age inference both passed through the new desktop-hosted
service and synthetic server-cache adapter (`smoke_remote.py --hosted`). Receipts
are private under `generated-files/eagle-eye/hosted-smoke-20260922/`. There were no
legacy service calls and no source-DICOM client upload/download. Breast returned
detection with unavailable classification; its full qualification is still blocked.

The owner selected two clinical cases in the conversation. A bounded read-only
catalogue check found the Breast source absent and the Bone source count incomplete.
No clinical job was submitted. Live acceptance awaits the human's fresh Server-mode
source launch/sign-in, complete server-side PACS cache and the documented control
ping/action discovery. No Reception deployment or final installer build was done.

## Implemented boundary

Standard sends protocol-1 requests containing Study/Series/SOP references, counted
series and allowlisted model parameters. It never uploads DICOM, source pixels,
NIfTI volumes, local filenames or arbitrary URLs. Eagle Eye obtains the original
images through the configured PACS storage adapter, checks identities/counts and
hashes, stages them inside the server job, runs an owned process and returns derived
artifacts. Ordinary local workstation viewing and MPR remain available.

`modules/ai_imaging/eagle_eye_remote` owns contracts, deployment settings, client,
PACS source resolution, job service, model adapters and artifact publication.
Existing UI workers delegate to it before loading model bundles. Configured remote
operation and packaged Standard fail closed on missing connection settings or a
server failure; they do not silently start local inference. Source development and
the Eagle Eye edition retain their local engines when no remote endpoint is set.

| Analysis | Server adapter | Phase-1 result |
|---|---|---|
| Breast | Imported FCOS and classification pipeline | Detection CSV/overlays; explicit classification availability |
| Bone Age | Imported EVA02 model | Age measurements and existing result fields |
| Brain | Existing SynthSeg/Slicer service | Measurements, segmentation labels, report |
| Brain lesions | Existing single-study LST-AI service | Native FLAIR mask, metrics, report |
| Lumbar | Existing offline anatomy worker | Labels, segment metadata and affine; exact client geometry check |
| Alignment | Existing alignment service | Landmarks and model revision |
| Total Spine | Existing region prediction workflow | ISBI or ScolioVis proposals in original image coordinates |

The first release of this boundary supports PACS-backed original DICOM only.
Lumbar requires regular single-frame MR slices with consistent orientation. Local
imports that are unavailable to the server are rejected. No upload fallback exists.
PACS-source access currently uses `/api/ai-patient/by-study/{StudyInstanceUID}` and
its `storage_info.study_path`/`dicom_file_path`; the server must have direct or mapped
access to that storage. This is not yet a DICOMweb/C-MOVE retrieval adapter.

## Job and result behavior

- Authenticated HTTPS outside loopback, administrator-provided certificate trust,
  per-client tokens and owner-scoped job lookup/download/cancel.
- `GET /v1/capabilities`, `POST /v1/jobs`, `GET /v1/jobs/{id}`,
  `POST /v1/jobs/{id}/cancel`, `GET /v1/jobs/{id}/artifacts`.
- Capabilities lists implemented adapters, not qualified model readiness.
- Durable states, idempotent request identity, bounded queue of 16 with one active
  inference worker, owned process termination, two-hour model timeout, restart
  interruption and no completed artifacts after failure/cancellation.
- ZIP and individual artifact hashes; request/study/module binding; constrained
  extraction; masks/reports/tables/overlays only. Source DICOM/volumes, runtime files,
  weights and worker logs are excluded. Source hashes accompany results.
- Server job folders retain staged images and internal logs. They require the same
  restricted storage access as PACS data; automated retention is a deployment gate.
- Annotation synchronization, server recomputation after edits, interactive SAM and
  remote two-study lesion comparison are outside phase 1. Unsupported remote heavy
  operations report that limitation instead of falling back to a client model.

## Source operation

Create deployment JSON outside tracked source. Example server configuration below
contains placeholders, not discovered clinic settings:

```json
{
  "host": "0.0.0.0",
  "port": 8042,
  "certificate": "C:/EagleEye/config/server.crt",
  "private_key": "C:/EagleEye/config/server.key",
  "job_root": "D:/EagleEye/jobs",
  "clients": {"workstation-01": "C:/EagleEye/config/workstation-01.token"},
  "pacs": {
    "url": "http://127.0.0.1:8000",
    "allowed_roots": ["D:/PacsStorage"],
    "path_mappings": []
  }
}
```

Token files must contain at least 32 characters of independently generated secret
material. PACS may additionally use `token_env` and `ca_file`. A storage mapping is
`{"pacs_prefix":"E:/Images","server_root":"D:/PacsStorage"}`; it is configured only
on the server and must stay inside `allowed_roots`. Replace every example endpoint
and storage path with verified infrastructure configuration before use.

Run the source service with the workstation environment:

```powershell
.\.venv\Scripts\python.exe tools/eagle_eye/serve.py --config C:/EagleEye/config/server.json
```

The equivalent explicit entry point is `main.py --eagle-eye-server CONFIG`.
It dispatches before interactive workstation startup. The frozen entry point exists
but has not been build-verified. Production service supervision is still required.

Client deployment JSON:

```json
{
  "url": "https://eagle-eye.example:8042",
  "token_file": "C:/EagleEye/config/workstation-01.token",
  "ca_file": "C:/EagleEye/config/clinic-ca.crt"
}
```

Set `AIPACS_EAGLE_EYE_CLIENT_CONFIG` to this file, or use
`config/eagle_eye_client.json` for source operation. Frozen operation defaults to
`roaming_config_root()/eagle_eye_client.json`. Slicer receives the same configuration
location. This is normal deployment configuration; it does not require
`AIPACS_TEST_SERVER`. No persistent client endpoint was enabled on this PC during
development, and no clinic listener or existing Breast/Bone service was changed.

## Edition packaging

The canonical coordinator now selects Client (four Standard/ARM installers) by
default and Server (two Eagle Eye installers) only when explicitly requested.
The latter is local install-QA only: its current model payloads do not yet prove
portable Breast/Bone execution, Windows service installation, GPU qualification,
or clean-host operation. See `BUILD.md`; no new server installer is claimed here.

Standard/ARM staging excludes Eagle Eye model payloads while retaining the Lumbar
review UI and a four-file standard-library client inside Slicer. All shared staging
paths install that thin client, including reused release payloads. Eagle Eye staging
retains model ownership. No new module entitlement or test-only feature flag is used.

Breast/Bone development bundles run on this PC but still reference local Python
bases. Their portable runtime sealing, dedicated installer payload inclusion and
clean-machine qualification are unfinished. Existing model acceptance requirements
are not bypassed. A complete server installer is therefore not claimed by this change.

## Verification and remaining gates

- 240 focused tests passed, exit 0, with retry disabled: remote protocol/source/
  artifacts, local Breast/Bone contracts, Brain/study/progress, Alignment, Total
  Spine/assist/actions, offline Lumbar, resident Slicer and both edition staging
  suites. Ten existing dependency deprecation warnings remain.
- Real loopback HTTP + synthetic PACS metadata + actual CPU model execution passed
  for Bone Age and Breast. Client source-DICOM upload/download was absent in both
  receipts. The server copied synthetic DICOM from its own PACS storage fixture.
  Private synthetic receipts are under `generated-files/eagle-eye/remote-smoke/`.
- Bone Age full synthetic model qualification passed again after worker resealing.
- Breast transport/detection passed with `classification_status=unavailable`.
  The imported stacker expects nine features while the current source supplies
  four. Full Breast qualification still fails; no classification or negative
  clinical inference is fabricated. The UI no longer calls missing classification
  a normal case. See the [investigation](EAGLE_EYE_BREAST_BONE_LOCAL_2026-09-21.md).
- 470 plugin mirror pairs matched. Packaging tests now use synthetic model fixtures
  rather than accidentally discovering private development bundles.
- Live GUI gate **BLOCKED**: the documented control client's ping could not reach
  `AIPACS_TEST_Dr_Alizadeh`. Human source launch/login in an authorized test session
  remains required. Offscreen tests and loopback model execution are not GUI passes.
- Brain, lesions, Lumbar, Alignment and Total Spine adapters still require actual
  model runs through this transport, displayed-overlay/identity verification, and
  source-versus-remote result comparison. GPU selection/performance is unqualified.
- No server deployment, clinical inference, full release build, commit or push.

Next acceptance sequence: source UI on this PC with a configured loopback service;
each model's identity/overlay/error/cancel workflow; portable Breast/Bone packaging;
clean server installation with verified PACS access and TLS; Standard client LAN
acceptance; only then phase-2 versioned edit and segmentation synchronization.

## Running workstation inspection (2026-09-22)

The human opened the source workstation at 00:39 local time, after the route edits.
Windows Computer Use found and inspected the existing workstation controls without
relaunching it. The visible list included recent MG examinations; no clinical
analysis was submitted and no patient identifiers are retained in this report.

The documented control-client ping failed. The running source process has no
`AIPACS_TEST_SERVER`, remote client configuration, client-only flag, worker flag or
model-bundle overrides. The default client configuration file is absent. No
dedicated Eagle Eye server process or listener on 8042 was active. Merely opening
the workstation does not activate the explicit server command.

Most importantly, the current Breast button is **not a local execution pass**:
`MamoWorker` sees neither a remote configuration nor full local Breast qualification,
so it falls through to the legacy Breast HTTP endpoint. This was established from
current configuration, qualification receipts and the worker branch; it was not
tested by sending a patient's examination to the legacy endpoint. Full qualification
must not be fabricated to force that branch. Bone Age's local qualification is valid;
its patient-specific workflow awaits the case supplied by the owner.

A fresh synthetic Breast test used real loopback HTTP, synthetic server-side PACS
storage, the actual CPU detector and result ZIP publication/download. It passed with
`classification_status=unavailable`, with no client DICOM upload/download. Receipt:
`generated-files/eagle-eye/remote-smoke-20260922/smoke-83c5b2f96ee345b19264ba753c72d947/receipt.json`.
The test service closed afterward. This proves the headless path, not the current
Breast UI binding, complete classification, a permanent listener or LAN deployment.

Required follow-up: make the Eagle Eye server UI select an explicitly qualified
local detection/partial-result mode or report unavailable status without silently
using the legacy endpoint; add/configure service lifecycle and verify the UI through
the loopback endpoint; retain the unresolved classification gate. Do not claim that
all Eagle Eye features in the running desktop already implement the server role.

Current bundle-integrity checks passed for Brain, brain lesions, Alignment and
Total Spine. No inference was run for those four modules in this inspection.
The full Lumbar hash audit (26,304 files) remained incomplete after more than six
minutes; only the explicitly identified audit process was stopped. This is an
uncompleted check, not a failed or passed Lumbar model test. The workstation and
its Advanced Viewer were left running. No runtime source or deployment setting
was changed in this inspection.
