# Full workstation development deployment

Updated: 2026-09-23. This supplements the earlier headless pilot.

## Product and installed layout

Eagle Eye Server includes the complete DICOM Workstation UI, patient catalog,
PACS download path, local storage, viewers and ordinary tools. A separate Windows
service runs the long-lived AI listener. The Standard edition uses remote AI.

The full development source is installed at
`D:/Eagle Eye Server/revisions/20260923-workstation/source`.
The source transfer verified 5,525 SHA256 entries before target PACS configuration.
This is a development source snapshot, not a signed release or a complete Git clone.
The old subset revisions remain for the existing headless processes.

The full-source `.venv/Scripts/python.exe` uses private Python 3.13.3.
The pinned 89-package build environment and pywin32 311 were installed offline.
A post-install `pip check` passed. Canonical development Python is 3.13.5;
full interpreter parity has not been claimed.

## Start and configuration

Open `D:/Eagle Eye Server/Open-EagleEye-Workstation.cmd` in the signed-in desktop.
It calls `Run-EagleEye-Workstation.ps1`, then source `run_app.ps1` in Server mode.
Do not open another copy while the development task is running.
The manual interactive task is `AI-PACS Eagle Eye Workstation Development`.
It has no startup trigger. The independent `AIPacsEagleEye` service owns automatic
startup/recovery and port 8043. `service_managed` prevents a second UI listener.
The service still uses its separate service revision; full-source worker alignment
is an outstanding acceptance step, not implied by the UI transfer.

Target-only PACS settings: host 127.0.0.1, DICOM port 105, AE title aipacs;
metadata/download socket host 127.0.0.1, port 50052. Do not substitute DICOM port
105 for the socket transport. The source `config/servers.json` was corrected after
source manifest verification; the receipt is therefore a transfer baseline.
Saved workstation credentials and the clinical database were not transferred.

The launcher selects `slicer/20260923-vc143-candidate` through the service config.
It sets the explicit Brain bundle path and keeps `AIPACS_TEST_SERVER=0`.
No production LAN test-control gateway was enabled.

## Acceptance status

- Full source transferred and hashes verified; offline dependency check passed.
- UI startup executed in Razi interactive session 1; source startup reached
  `window.show()`. This is not visual acceptance or successful sign-in.
- Main-window and socket-client imports passed. Session-0 application import
  encountered PortAudioError; interactive startup progressed beyond that check.
- Advanced Analysis startup logged a warmup RuntimeError; visual viewer and
  Slicer integration acceptance remains open.
- The owner confirmed sign-in, then reported a freeze opening the patient list.
  Session PID 9472 records a native Advanced access violation at
  `viewer_2d.py:342 SetInputData`. A separate 6050.9 ms Home sample reaches
  the Reception breaker. **GUI acceptance FAILED**, not pending/pass. Study
  download/display is not certified. No restart or viewer workaround was applied.
- Model transfer/portability and target-host qualification are tracked separately.
  Local model receipts must not be imported as proof of Razi inference.
- Do not report end-to-end AI or clinical readiness based on source presence.

## Next checks

Complete target inference qualification after the GUI blocker is resolved. Align the independent
AI service with the verified full worker source in a controlled empty-queue change.
After the human signs in, verify the current patient catalog, authorized MRI
study download, local database/files and viewer output. Keep patient details and
images out of development documents. Then qualify each AI module under measured
RAM/CPU limits; Breast classification remains explicitly deferred by the owner.

## Model runtime deployment corrections

Breast and Bone Age development venvs originally referenced developer-machine
Python homes. Private base runtimes 3.10.20 and 3.12.13 were transferred under
`D:/Eagle Eye Server/model-python`, with 4,570 verified file hashes. Target-only
`pyvenv.cfg` files and model manifests/revisions were updated; original manifests
and relocation receipts are preserved under `logs/`. No external Python path is
required for these two models. No old qualification receipts were transferred.

Breast imports passed: torch 2.5.1+cpu, torchvision 0.20.1+cpu, pydicom 3.0.1.
Bone Age initially failed importing c10.dll with WinError 1114. A process-local
DLL search probe against the verified Slicer CRT candidate passed. The ten
hash-verified official CRT libraries were then copied only into Bone Age's own
Torch library directory; system/shared DLLs were not replaced. Its manifest and
revision were updated with a before/after receipt. Ordinary imports subsequently
passed: torch 2.12.1+cpu, torchvision 0.27.1+cpu, pydicom 3.0.2. These are runtime
import checks, not model inference or clinical qualification.

## Read-only PACS cache evidence after the failed GUI test

Header-only verification found 128 valid MR DICOM files, 128 distinct SOPs, one
study and five series in this instance's local DICOM cache; no partial files were
present. Patient identities and images were not exported to documents. This proves
local receipt of DICOMs, not source-inventory completeness, correct requested-study
selection or successful rendering. The failed main process was later absent;
no automatic or manual agent relaunch was attempted.

Brain runtime imports passed on Razi: TensorFlow 2.12.0 and nibabel 5.0.1.
Brain-lesion runtime imports passed: torch 2.5.1+cpu, nibabel 5.4.2 and
SimpleITK 2.5.6. No actual Brain inference was started on the live reception VM.
The independent 8043 API returned authenticated HTTP 200 for capabilities and jobs
after the GUI failure; this does not qualify its still-separate worker source.

## Completed model transfer inventory

All seven archives were installed under the full source revision and their 126,380
manifest-listed file payloads were verified on Razi. Receipts are in
`D:/Eagle Eye Server/logs/workstation-<bundle>-transfer.json`. Breast/Bone Age
subsequent target relocation/CRT manifests are separately recorded above.

| Bundle | Source-relative target | Verified payload files |
|---|---|---|
| Breast | generated-files/eagle-eye/breast | 24,445 |
| Bone Age | generated-files/eagle-eye/bone-age | 19,575 |
| Brain | generated-files/eagle-eye/brain-tf212-py310/model | 15,972 |
| Brain lesions | generated-files/eagle-eye/brain-lesions | 23,187 |
| Alignment | generated-files/eagle-eye/alignment | 16,887 |
| Total Spine | generated-files/eagle-eye/total-spine | 10 |
| Lumbar | generated-files/offline-lumbar/bundle | 26,304 |

The archives include standard pydicom/nibabel package test fixtures, not source-PC
patient studies. The source-PC clinical database, saved account secrets and model
qualification receipts were excluded. Target-host inference is still unqualified.
Total Spine uses Alignment's runtime; the small payload is intentional.

Final ordinary import probes passed: Alignment torch 2.8.0+cpu, torchvision
0.23.0+cpu, numpy 2.2.6 and SimpleITK 2.5.2; Lumbar torch 2.6.0+cpu and
SimpleITK 2.5.6. Receipt: `logs/workstation-final-runtime-probes.json`.
An initial Alignment probe mistakenly requested pydicom, which its isolated
array-only worker does not require; that probe was corrected to the worker's
actual imports. No unnecessary dependency was added to that bundle.
The transfer/extraction processes completed; no model-transfer background job
remains. Existing clinical PACS, DICOM, Breast and CRM listener PIDs were unchanged
at the final check. The SCM API remains on loopback 8043, not the legacy 8002 port.


## 2026-09-23 correction: confirmed native drag/drop crash sequence

The owner clarified that patient double-click opened the tab and images downloaded;
the freeze/crash/exit happened after dragging a series into the viewport. Fresh
read-only review of terminal_20260923_165457.log confirms PROTECTED_DRAG at
17:08:04.296 and 17:08:05.025, DROP at 17:08:05.042, RENDER-DROP at 17:08:07.543,
and VIEWER_SWITCH/_perform_series_switch_optimized at 17:08:08.785 (Razi local
log timestamps). The session-scoped PID 9472 native fault file was last written
at 17:08:09.082 and contains Windows fatal exception: access violation.
The current-thread chain reaches Advanced viewer_2d.py:342 SetInputData through
switch_series -> _perform_series_switch_optimized -> _apply_loaded_series_data.
The fault-file modification time brackets the event; it is not an embedded
exception timestamp. This identifies the failing drag/drop-to-Advanced workflow,
not the underlying native memory/lifetime cause. The earlier Home breaker stall
is separate evidence and must not be presented as the reported terminal crash.
No new reproduction, runtime change or restart was performed for this correction.


## 2026-09-23 native graphics diagnosis and guarded development correction

Windows Application Error 1000 records c0000005 with instruction address zero.
The crash dump was parsed on Razi only, without exporting clinical content. Its
top native return address maps to vtkOpenGLRenderWindow::GetDepthBufferSize;
the remaining candidate frames include ResetCameraClippingRange,
UpdateDisplayExtent and vtkResliceImageViewer::SetInputData. Local and Razi
OpenGL DLL hashes match. This supports an execute-at-zero graphics fault,
not a PACS transport failure or demonstrated invalid pixel payload.

An isolated synthetic vtkWin32OpenGLRenderWindow.SupportsOpenGL probe failed in
both the remote command session and the actual interactive desktop. VTK could
not select a valid pixel format or initialize OpenGL functions. The software
runtime had incorrectly been considered ready solely because its DLLs existed.
Qt software GL and VTK Win32 GL are separate contexts. The implicated upstream
path is in [VTK 9.6.1](https://github.com/Kitware/VTK/blob/v9.6.1/Rendering/OpenGL2/vtkOpenGLRenderWindow.cxx).

The shared Standard/Server GUI bootstrap now runs an isolated native probe before
Qt UI startup, once per launch with a 15-second limit, using only synthetic 8x8x2
pixels. Native crashes, timeout, missing dependencies and invalid receipts deny
VTK admission. A private JSON receipt supports source and windowed frozen builds.
Headless Eagle Eye service dispatch still exits before graphics initialization.

On failure, VTK-free Fast is authoritative for empty and populated viewports,
including legacy-backend settings, metadata fallback and per-widget Advanced
overrides. MPR cannot reuse a stale PASS or disable this fresh native safety
decision. This does not repair/install the machine's graphics driver: Advanced
and native MPR remain unavailable there. AI calculations and PACS/download
protocols are unchanged. The real local synthetic probe succeeds and preserves
Advanced admission on this development computer.

Verification: the admission guard failed before correction (10 failed, 2 passed,
exit 1). After correction, 71 graphics/backend/runtime/ARM guards and 15
mirror/service-boundary guards passed with exit 0. All 471 mirror pairs match.
The actual Razi interactive post-change probe exited 0, rejected native GL and
verified Fast routing for empty/populated viewers and blocked MPR. These checks
do not replace the original clinical drag/drop workflow.

Seven scoped source/payload files were baseline/hash-checked and updated only in
the existing Razi development source. Original files and exact manifest:
backups/native-graphics-20260923. Receipt: logs/native-graphics-fix-20260923.json.
For rollback with the source UI closed, restore baseline entries from that
backup and remove only manifest-listed new files. No clinical service, installed
executable or driver was changed. Surviving Python processes were output-capture
wrappers, not an active workstation UI; they were not terminated.

Status: guarded source correction and isolated desktop verification completed;
human fresh-source launch/native drag/drop plus fresh Windows/native-log review
remain pending. Normal launches retain AIPACS_TEST_SERVER=0. No release-readiness
claim is made.

## 2026-09-23 Razi patient-open / viewport acceptance receipt

The user confirmed opening a patient and importing a series into the viewport.
Fresh remote log review ties this to the existing source UI PID 17424 (normal
AIPACS_TEST_SERVER=0 session), not the isolated diagnostic probe or a frozen build.
Open request: 19:56:07.217; tab created: 19:56:08.384; actual first-image marker:
19:56:17.617 (Razi local time), backend pydicom_qt. The earlier first_series_visible
marker is not used as proof of actual pixels. The UI remained responding.

For the 19:55-19:59 workflow interval, app/viewer/download/database logs contain
zero ERROR/CRITICAL records. Windows Application events 1000/1001/1002 since 19:55:30
were absent at inspection. The main PID's session-scoped native file contains only
its session header, no native fatal exception. Worker headers are not crashes.
The download log reports 12 completed series totalling 111 downloaded files and
zero skipped, matching its authoritative total of 111. This is a log-level count,
not a new on-disk/SOP audit. One socket reconnection warning recovered before the
series completions. Human visual confirmation plus first-image/liveness evidence
passes this scoped patient-open-to-viewport source workflow, including the earlier
native-crash path now routed to VTK-free Fast.

Remaining findings: a 1251.1 ms UI stall during first Fast pipeline import/source
compilation; Download Manager DM-CONVERGE-MISS at Downloading and Completed and
missing-row/status warnings, so the progress-row acceptance is not clean. The
FAST_GEOMETRY_ORDER_MISMATCH entries are INFO diagnostics for InstanceNumber vs
IPP order; existing code uses a separately ordered copy for sync/reference lines.
They are not proof of corrupted images or a new geometry correctness pass.

No runtime modification or restart was performed for this verification. The
input-observation source update has not been loaded into this still-running UI.
Advanced/MPR on Razi, concurrent AI requests, model inference, standard-client
round trips and frozen/service deployment remain separate acceptance gates.

## Role-specific settings update (2026-09-23)

Server desktops now hide legacy outbound Breast, Bone Age, Segmentation and
Mammography endpoint editors in both global and per-PACS-profile settings. PACS
and Reception connections remain available. The Eagle Eye page hides client
connection credentials and save controls, and labels its health probe as local
service verification. PACS source/storage, resource policy and Windows service
management remain in that page. Standard/client settings retain their existing
connection controls. Hidden saved endpoint values are preserved.

Explicit launch role takes precedence; frozen edition metadata provides a cached
UI-only fallback loaded before QApplication. This does not alter inference routing.
Automated verification: 33 focused tests passed; 471 mirror pairs matched. Four
runtime files were deployed only to the development workstation source, with
baseline/hash validation, compilation and backup under
`D:/Eagle Eye Server/backups/role-settings-20260923`. The receipt is
`D:/Eagle Eye Server/logs/role-settings-20260923.json`. No service or open UI was
restarted. A fresh source launch and live Settings workflow remain pending; this
is not a frozen-build or production acceptance claim. To roll back, close the
development UI and restore the four paths listed in the backup manifest to the
workstation source, then launch normally.

## Local Reception and client listener preparation (2026-09-24)

The Razi development workstation now points its Reception/Workflow configuration
to `http://127.0.0.1:8080`. The on-host D:/api/index.js mounts /api/pacs and
PACSRouter.js implements /patients/:receptionId. A synthetic absent resource
returned HTTP 404; no patient was fetched. This establishes routing/source
compatibility, not authenticated reception-data acceptance. Port 8770 is a
different CRM application and was not substituted. The AI service PACS source
was already local: metadata 8000, DICOM 105, imaging socket 50052.

Eagle Eye settings now expose bind IP, request/result port and TLS certificate/key
paths. Saved changes are validated off the GUI thread and take effect only on a
controlled restart. Stale revisions, invalid ports, non-IPv4 binds, missing or
mismatched certificates and non-service-managed network hosting are rejected.
No process or router setting is changed by Save. Clients submit requests and
retrieve derived results on the same port; this is not a callback listener on
the client. The server desktop can now use a service-managed HTTPS endpoint
without trying to bind a second listener. Certificate SANs must cover the
client-facing address and loopback when binding all interfaces. Local Reception
preset controls retain the entered port; an empty field uses product port 8080.

Verification: seven new guards failed before implementation. The expanded suite
passed 41 tests including real synthetic authenticated TLS/artifact round trip;
471 existing mirror pairs match. Four source files were backed up, hash-checked
and compiled on Razi under backups/listener-settings-20260924. The Reception
configuration backup is in that same directory. No open desktop, AI service,
Breast or Bone Age process was restarted. Fresh source Settings UI acceptance
and authenticated Reception workflow are pending.

### Remaining 8002 cutover gate

Legacy owner is D:/FCOS_AR/dist/AI_PACS_Mammo.exe (PID 11236 at inspection).
Eagle Eye SCM still runs the separate 20260923-service revision on loopback 8043.
Port 8002 has NOT been migrated. The user requested reuse of its existing forward.
Before replacement: confirm the client-facing IP/DNS name (requested), provision
TLS covering it plus loopback, align the actual SCM runtime/model environment
with the qualified workstation source, verify an updated Standard client with a
separate authorized credential, and pass the outstanding source/frozen and model
acceptance gates appropriate to the deployment. Then drain active work, record
the legacy executable's actual launch/auto-start owner and rollback command,
stop only that owner, switch the Eagle Eye listener to 8002 and verify auth,
capabilities and a real analysis/result round trip. Restore the original listener
and legacy executable if cutover fails. Existing mammography callers do not
automatically implement Eagle Eye's /v1 protocol. Bone Age stays running until
the user-requested post-test migration phase.

## Active service alignment and transport receipt (2026-09-24)

The actual AIPacsEagleEye SCM ImagePath now uses the complete workstation source
and its .venv interpreter under revisions/20260923-workstation/source. This
supersedes older references to the 20260923-service runtime. The same service
identity, delayed startup/recovery settings, job storage and loopback 8043 remain.
The queue was empty before controlled stops. Startup and authenticated protocol-1
capabilities passed after the switch and after the PACS storage configuration.
Exact previous/new commands and source hashes: logs/service-alignment-20260924.json.
Rollback: stop only AIPacsEagleEye on an empty queue, restore the old command from
that receipt and start it; restore the backed-up server configuration if reverting
storage too. No legacy 8002, 8003, original 8042 task or PACS service was changed.

PACS allowed_roots is now populated from the installed PACS configuration's
actual dicom_storage_path, not guessed from a patient file or the entire D drive.
Backup: backups/service-alignment-20260924/server-service.json. Metadata source
remains local :8000, DICOM 105 and imaging socket 50052. A persistent PACS account
is still absent; the human was asked to save/test it through the masked Settings
fields. Desktop sign-in is not a substitute for this service identity.

The actual Python Client on the control workstation authenticated to the new
SCM service through a temporary SSH tunnel, received protocol 1, pacs_references,
seven advertised operations and an empty job list. The tunnel was closed after
the test; no token was printed or persisted on the control PC. This is transport
acceptance, not a Standard GUI, public 8002 or clinical analysis pass.

Real model synthetic probes on Razi: Bone Age passed and wrote its qualification;
Breast failed the known classifier-weight/feature-schema guard. Detection-only
clinical behavior is not certified by this failed full smoke. The owner-deferred
classifier reconciliation remains open, without guessed features or changed weights.
Reports: logs/service-alignment-model-probes-20260924.json and the local generated
service-alignment-20260924/client-transport.json. Probe execution was under the
maintenance administrator; LocalService model inference still needs a real job.

### Mandatory follow-through for subsequent server changes

Owner instruction, 2026-09-24: server-affecting changes must update the actual
service as well as source files. Before a controlled restart, inspect the real SCM
command, preserve backup/source hashes and check all authorized clients' queued
and running jobs. Do not interrupt active work. Stage the scoped change, restart
only Eagle Eye when drained, verify the new process/source identity and authenticated
API, then exercise the affected client-to-PACS-to-analysis-to-artifact workflow.
Record code, deployment, transport and model/GUI outcomes separately. Transferred
files alone are not completion. If credentials or a human GUI step are pending,
name that gate explicitly. Never bypass model qualification or broaden storage
permissions to manufacture a pass. Future immutable releases can replace this
shared development source using the same receipt and rollback discipline.

## Unified Standard client settings and Razi development launch (2026-09-24)

The owner now requests one Eagle Eye connection on Standard too. This supersedes
earlier statements that Standard retains visible Breast/Bone Age/Segmentation
editors: both roles hide legacy global/profile AI endpoints, while preserving
their saved values and Reception/PACS controls. Standard links to the Eagle Eye
connection page; server links to local management. The client still uses the
authenticated shared protocol and sends study/series references.

The control-PC desktop AIPacs Standard Client.cmd now invokes the private,
development-only generated-files/eagle-eye/run_razi_client.py helper. It opens an
owned SSH tunnel on loopback 18043 to the real Razi SCM listener 8043, verifies
authenticated capabilities, then runs run_app.ps1 -Standard with deployment/
razi-client.json. Normal AIPACS_TEST_SERVER=0 is preserved. SSH host identity
is checked against the existing control-node known_hosts; no other configured
forwards are started. The existing development desktop credential is obtained
over SSH and held only in the launcher/child environment, never stored in this
repository. This identity is shared with the server development desktop, so
per-client isolation acceptance still needs a separate production credential.
The tunnel ends when this client invocation ends. An occupied local port fails
the launch rather than killing another process. This helper is not a shipped
SSH dependency or the final public 8002 endpoint.

The --check-only launch path authenticated against the actual server successfully
and closed its tunnel. It did not launch a second workstation. Fresh human
source launch/Settings GUI and real analysis remain pending. Desktop backup:
generated-files/eagle-eye/deployment/Standard-client-before-razi.cmd. Server
backend was not changed by this client-only slice and was not restarted.

## Paired client/server on existing port 8002 (2026-09-24)

Current verified state supersedes the earlier 8043/tunnel instructions. The actual
AIPacsEagleEye SCM service runs the full workstation source on 0.0.0.0:8002 using
TLS and mandatory client certificates. Legacy AI_PACS_Mammo processes are stopped;
8043 has no listener. Existing PACS 105/8000/50052 and Reception 8080 owners remained
unchanged. The retired original 8042 development task is outside this cutover.
No router forwarding was changed or additional permanent listener created.

Two distinct pairings exist: server development desktop and control workstation.
The private CA stays on Razi; its private key ACL excludes LocalService. Server
keys are readable only by Administrators/SYSTEM/LocalService. The control-PC
private key was created in protected LOCALAPPDATA/AIPACS/EagleEye/RaziPairing and
never sent to Razi; only its CSR was signed. Tokens are separate per client and
remain outside source. Server checks TLS trust and the exact certificate SHA256
bound to the bearer-token owner. Client checks CA trust and server IP/SAN; no
verification bypass or software-name/User-Agent check is used. This authorizes
paired installations. It is NOT online verification of the commercial license or
a guarantee against a local administrator extracting credentials. Existing app
license enforcement is unchanged. Provision each additional center separately;
never distribute one universal private key/token. Revoke a client by removing
its token owner and fingerprint together, then restart the drained service.
Leaf certificates expire after one year; renew and replace pins before expiry.

The first cutover failed TLS validation because newly issued leaf certificates
lacked Authority Key Identifier. Automatic config rollback restored SCM8043 and
requested the manual legacy rollback task; legacy model loading had not yet
restored its listener. Certificates were reissued with AKI/SKI, then authenticated
TLS200 was verified on the existing8043 before retry. The retry stopped the
identified legacy processes and successfully placed Eagle Eye on8002. Private
verification remained enabled throughout. Receipts: logs/mtls-8002-cutover.json,
logs/mtls-8002-cutover-retry.json; backups/mtls-8002-20260924 holds source/config
baselines. Manual rollback task: AI-PACS Legacy Mammography Rollback (no trigger).
For rollback, drain/stop Eagle Eye, restore server-service-retry.json to the live
config, start Eagle Eye on8043 and invoke the rollback task; verify legacy8002
has actually returned after model startup. Never count task dispatch as readiness.

Live transport verification from the control PC passed against
https://192.168.2.222:8002. Missing client certificate, incorrect token and missing
server trust were rejected. A request through the existing public address
81.16.117.196:8002 also passed from this control PC; this is not an independent
outside-network test. Synthetic mTLS regression also rejects a trusted certificate
with a different registered owner fingerprint and verifies job/artifact transport.
36 focused tests passed; 471 mirrors match. No real-patient inference acceptance
is claimed. PACS service-account setup, fresh GUI acceptance and the known deferred
Breast classification mismatch remain separate gates.

The local Standard desktop launcher now invokes run_app.ps1 -Standard with the
paired deployment/razi-client.json directly: no SSH tunnel or temporary18043.
The server desktop-client.json was regenerated for local HTTPS8002 with its own
certificate, without launching a duplicate UI/listener. Existing running UIs may
need Reload or a normal fresh launch. Source Settings exposes paired certificate
and private-key file locations; contents are never shown. Restoring old client
configs without pairing cannot access this service.

## Grouped Settings navigation (2026-09-24)

Both Standard and Server now share this hierarchy: Server Settings first; Viewer
Configuration containing Viewer Configuration, Tools Settings, Image Filter and
module-enabled Light Viewer; AI containing module-enabled EchoMind, Eagle Eye and
Agent. Installation & Updates and Consultation & Education remain top-level.
Existing leaf widgets, attributes, saved settings and module gates are preserved.
Nested content is constructed once on first display. Server Settings' Eagle Eye
shortcut selects AI/Eagle Eye directly without initializing EchoMind. The original
viewerConfigReady signal still originates from the viewer configuration leaf.

40 focused startup/role/Agent/build tests passed; 471 mirror pairs match. The shared
settings_ui.py was hash-verified, backed up and compiled in Razi development source
(backups/settings-groups-20260924; logs/settings-groups-20260924.json). This is a UI
change: the headless service does not import this page and was not restarted.
Fresh local/server desktop Settings inspection is pending. Existing control MCP
is unavailable and its documented client ping failed; no test flag was enabled
and no running workstation was restarted. Offscreen behavior is not live GUI
acceptance. Restore the single backed-up file with the desktop closed to roll back.

### Navigation visual hierarchy follow-up

The user confirmed the grouping in the running UI but reported that both rows
looked like peers. Child navigation now uses compact flat labels, a cyan selected
underline, a subtle divider and a 16px inset below the filled primary tabs.
Styling is owned by the child bar so both parent theme variants retain it. Full
child labels are preserved, with scroll buttons available for narrow windows.
Nine focused grouping/startup tests passed and a synthetic Qt navigation preview
was inspected; this is not a live GUI pass. The single source file was backed up,
hash-verified and compiled on Razi (backups/settings-hierarchy-20260924;
logs/settings-hierarchy-20260924.json). The headless service was not restarted.
Fresh desktop inspection remains pending; changes appear after a normal restart.

## Live client-to-server test blocked (2026-09-24)

The human opened three authorized cases for sequential Alignment, Bone Age and
Breast testing. Native client navigation selected the complete stitched AP image
and invoked Alignment AI. The running source client had the standard role and
the paired Razi client configuration. HTTPS8002 capabilities initially passed.
The server persisted an Alignment job in retrieving state; no source directory,
source manifest or inference worker log was created. The client eventually showed
a generic operation failure, and a subsequent authenticated jobs read timed out.

A read-only py-spy stack sample of the existing service child localized the stall:
the retrieval thread was importing pydicom, then NumPy's native multiarray module;
the listener main thread was waiting for a request thread to start. This is evidence
of a native import/thread-start stall, not a completed PACS retrieval or model run.
The underlying native locking cause is not yet proven. A separate interpreter
completed the same import, so dependency presence alone does not qualify SCM use.
Local PACS health returned HTTP200. The service configuration also has no PACS
credential_file; this independent authentication prerequisite remains unresolved.

Bone Age navigation reached the explicit requirement to load a viewport image.
The automated drag did not complete and was cancelled with Escape. No Bone Age
request or Breast request was submitted after the listener stall was established.
No results were returned, no clinical report was approved and no service or UI was
restarted during this diagnostic lap. Next: reproduce and guard service startup
initialization before request threads, qualify it under SCM, configure PACS service
authentication, then repeat all three UI-to-server-to-result checks. Preserve the
durable request handle and reconcile the first job before issuing a duplicate.

## Live request corrections (2026-09-24)

Two minimal source corrections were deployed with SHA256 baseline checks, backups
and bytecode compilation; only AIPacsEagleEye was restarted. First, pydicom/NumPy
initialization now runs on the service child main thread before listener/control
threads. The repeated native client Alignment action no longer stalls HTTPS8002.
Second, real metadata returned HTTP200 with the canonical study_instance_uid
matching the request, while administrative study_id differed. Source resolution
now compares the canonical UID and retains DICOM file identity validation.
Do not fall back to the administrative ID.

Regression guards: two startup cases and three identity cases failed before their
corresponding fixes. Focused selections passed 25 and 40 tests respectively
(overlapping selections); plugin verification passed 471 pairs. Backups/receipts:
backups/service-import-fix-20260924, backups/pacs-identity-fix-20260924 and
corresponding logs/*.json. These are development source updates, not release builds.

The live retry retrieved the selected image and reached model execution; capabilities
remained responsive at 0.02 seconds. The earlier missing-credential observation is
not the cause of this metadata failure: this PACS endpoint returned HTTP200 without
authentication. Service credential configuration and renewal should still be
qualified separately where authentication is required. Result acceptance follows.

Live Alignment acceptance: the final retry reached succeeded on Razi and the
existing standard client displayed returned landmarks, overlays and measurement
rows on the selected image. The application also reported its generated PDF ready.
No calibration/review checkbox was attested by the operator or agent. This is a
transport/execution/UI pass, not clinical validation of model measurements.

## Bone Age and Breast live qualification (2026-09-24)

The same authorized cases were tested from the standard client PC through the
production Client/routing code and paired HTTPS8002 service. Requests contained
DICOM references only. Razi staged PACS images, ran the models and returned
identity-bound, hash-verified artifacts. Both models returned real results
(synthetic=false, remote_analysis=true). No server/runtime code changed in this lap.

Bone Age: one image, prediction returned. The initial submission lost observation
before a durable server job appeared; retry/resume used the same saved request
identity, avoiding a duplicate backend request. A separate, intentional native UI
run then completed, showed its completion dialog and populated the Bone Age tab.
The model result carries low_confidence and input_coverage_confirmation_required;
transport/UI acceptance does not establish clinical validity. Review status was
left pending_review, with no manual correction or clinical approval.

Breast: the transport run completed in approximately 73 seconds, processed four
MG images and returned the detection CSV. classification_status=unavailable and
auxiliary_head_available=false remain expected limitations of the previously
deferred classifier/weights mismatch. No classification output was invented.
A subsequent explicit UI run was started with the unchanged 0.45 threshold;
its UI acceptance is recorded below.

Native drag automation required starting the drag inside the thumbnail and then
completing the drop at the observed viewport; the main viewer and Eagle Eye own
separate viewports. No test-only flag, duplicate app, or GUI restart was used.

Native Breast UI repetition completed successfully on Razi and returned to the
Mammography tab. Its notification explicitly states that detections are available
and missing classification is not a negative classification. The received table
contains all four views, including a detection on the left oblique view.

The final overlay check exposed a separate display defect: MG viewport startup
and series switching required BOTH detection and classification paths, discarding
a valid detection-only manifest. Four synthetic behavioral cases reproduced this
for startup/switch and manifest/fallback. The four conditions now require only
the detection path; optional classification remains None. Sixteen focused tests
and one mirror parity guard passed; all 471 mirror pairs match. The one changed
UI source was deployed with baseline/backup/hash/compile verification to Razi
(backups/mg-detection-only-20260924, logs/mg-detection-only-20260924.json).
No inference service restart was needed because this file belongs to desktop UI.
Fresh-process overlay acceptance is PENDING the human's normal source-client
restart/login; the current process still holds the old class. Do not call this
final overlay gate passed. Runtime tests did not approve/correct clinical findings.

## Lower Limb Alignment review tab (2026-09-24)

The user reported that successful Alignment analysis was only reachable through
a separate popup, unlike Bone Age and Mammography tabs. `open_alignment` now
embeds the same study/series-owned AlignmentWidget in a scrollable tab named
Lower Limb Alignment. Returning through Choose Function selects the existing
tab without replacing measurements, points or report state. Distinct series
retain distinct sessions; no rendering domain, input identity or model changes.
The existing measurement editing, review gates and PDF save actions are retained.
This preserves state during the open workspace; it does not introduce automatic
restoration of a previously closed application session or approve measurements.

The new real-Qt regression failed before the change (no added tab), then passed.
It guards tab creation, reuse, selected-series preference, retained measurements
and separation of series sessions. Focused workspace/alignment suite: 51 passed;
extended session guard: 1 passed. Mirror dry run reported no drift. The single
source file was deployed to Razi with baseline, backup, hash and compile checks:
backups/alignment-tab-20260924 and logs/alignment-tab-20260924.json. No inference
service restart is needed for this desktop-only change. Live GUI acceptance is
pending a human source-client restart/login; no live tab pass is claimed yet.

## Lumbar, Total Spine and saved Brain investigation (2026-09-24)

The user accepted the Lower Limb Alignment tab in their running application.
Next investigation: Lumbar MRI, Total Spine radiographs and reopening an existing
Brain result. Server model locations for all three exist; this alone is not
model qualification. Focused remote/Brain workflow/report suite: 60 passed.
Lumbar and Brain real-case identity is awaiting user selection; do not infer it
from patient names or choose an arbitrary saved result. Local completed Brain
results/PDFs exist. The Brain UI can regenerate a report from a selected completed
result with examination identity checking. No automatic server-result discovery
UI was found; client resume requires its durable paired request handle.

For the previously authorized Total Spine case, both stitched projections were
visually inspected because series descriptions incorrectly described both as LAT.
The coronal image was submitted using the normal paired client bridge and a
full-image region for technical execution testing. Razi succeeded and returned
17 candidate vertebrae with verified downloaded artifacts. The bridge then
rejected applying the result because the complete source-file SHA256 differed
between cache and PACS. Study/series identity matched; independent comparison
also found identical decoded pixel SHA256, dimensions, PixelSpacing and transfer
syntax. The differing file bytes therefore do not establish differing pixels.
The existing conservative guard was retained. End-to-end Total Spine application
acceptance is NOT passed, and no angles or candidate labels were clinically
approved. Follow-up requires a guarded content/geometry identity contract, not
blind suppression of the mismatch or an unverified claim that re-download fixes it.

### Equivalent radiograph return and external Brain source (2026-09-24)

The Total Spine failure described above is corrected in both development sources.
File SHA remains the immutable staging/provenance key; an additional versioned
semantic fingerprint permits equivalent DICOM encodings only when decoded raw
pixels, preprocessing, valid mask, spacing/calibration, orientation and exact
Study/Series/SOP identity match. Server review shape/projection/hash are verified
before rebinding to the client's loaded copy. No DICOM pixel uploads or guard
bypass were introduced. The paired real client bridge returned 17 candidates in
35.48 seconds and matched the local review binding. The four-file deployment has
a verified baseline and backup under `backups/radiograph-binding-fix-20260924`.
Only AIPacsEagleEye was restarted; normal desktop processes were not interrupted.
Fresh-source GUI rendering and anatomical/angle review remain pending.

The Brain conversation's external study was found in the existing private
benchmark workspace. Six prepared inputs exist on both hosts and all six file
hashes match; three remote runs are complete and their masks remain available.
The client also has the original DICOM folder and a completed identity-bound PDF.
These are benchmark artifacts, not a `/v1/jobs` result: finding them does not prove
a PACS-backed remote request or automatic result discovery in the patient tab.
No new inference or PACS import was performed. Patient paths and identifiers are
intentionally excluded from this runbook. Lumbar testing awaits the user's case.

### PACS-first local cache fallback (2026-09-24)

The service's `pacs-storage` provider now uses the configured `pacs.database`
when PACS explicitly responds HTTP 404. This must be the Eagle Eye server's own
workstation database; no client DB or path is submitted. `pacs.allowed_roots` must
include its actual image roots. The Razi service is configured with its source
workstation database and patients/cache directories, alongside existing PACS
storage. PACS success takes priority. Authentication, connection, server and
identity failures do not trigger fallback. Missing/incomplete local data remains
a controlled failure. The original completeness, Study/Series/SOP, file-hash and
root-confinement guards run before inference.

The real external Brain request now reaches the local cache lookup, but that
study is not registered in the current server workstation DB. Its benchmark
NIfTI inputs do not substitute for an imported DICOM study. Import original
DICOMs through the server workstation before repeating the client request. No
new successful Brain analysis or GUI acceptance is claimed. Source/config backup:
`backups/cache-fallback-20260924`. Dedicated guards: 11 passed; combined focused
coverage: 49 unique passes. Mirror verification: 471 matches.


### Alignment remote revision implementation (2026-09-25)

Status: Alignment vertical slice implemented and automated/paired-bridge verified;
fresh-source GUI acceptance pending. Total Spine and Brain corrections remain design
work, not delivered features. No broad editable-mask upload endpoint exists yet.

`reviews.py` validates bounded Alignment corrections and checks owner, completed
parent, exact study/series references and active/successful child conflicts under
the existing job lock. A correction is a new job using immutable copied parent
sources, without PACS retrieval or AI inference. Its measurements/PDF are produced
headlessly by the existing Alignment functions. Original artifacts remain unchanged.
Parent links persist across service restart; a stale parent returns HTTP 409.
Existing durable client handles provide retry identity. The source UI sends report
requests to the server, updates the accepted parent ID, and offers Resume server
result after a detached connection while locking its editing draft. The client
requires server capability `correction_modules` to include `alignment`.

API shape: existing POST /v1/jobs, module alignment, parameters.correction with
parent_job_id, complete landmarks, spacing/calibrated, flipped, acquisition_reviewed,
landmarks_reviewed and bounded notes. No new port or endpoint family. Jobs retain
owner/device authentication; clinical operator identity/signature is not asserted.
Initial automatic draft generation also becomes a child report job. Local preview
remains provisional; full cross-user sharing and revision browser are not delivered.
A closed/restarted client retains disk handles, but automatic UI reattachment across
application restart remains pending; in-session Resume is implemented.

Evidence: revision requirement failed before implementation. Fifty focused tests
passed, including HTTP correction/conflict, synthetic calculation with an edited
point, ownership, immutable parent, restart/idempotency, and Qt pending-draft lock.
Existing Alignment payload guards passed; 471 mirrors match. This verifies build
inputs, not a new Standard/Server installer. No release build was run.

Razi development deployment: eight files, verified pre-update hashes and backups
under backups/alignment-reviews-20260925; only AIPacsEagleEye restarted after zero
active jobs. The real paired client bridge submitted an unreviewed technical draft
with a one-pixel landmark change. Returned landmark matched exactly, measurement
changed, PDF arrived, parent remained successful: 8.01 seconds. This does not certify
clinical accuracy or a live GUI interaction. Human fresh source launch requested.
Rollback: restore the seven replaced files and remove the new reviews.py using the
backup manifest, then restart only the inference service. Do not overwrite unrelated
subsequent changes. GUI verification is the next gate before expanding to Total Spine.
