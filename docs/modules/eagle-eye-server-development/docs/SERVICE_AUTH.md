# Unattended service and PACS authentication

Verified on Razi Reception, 2026-09-23. Isolated development acceptance, not
clinical model qualification or production cutover.

## Installed state

- Service: `AIPacsEagleEye`, display name `AI-PACS Eagle Eye Server`.
- Account: `NT AUTHORITY\LocalService`; independent of desktop login.
- Startup: automatic delayed start. Failure recovery: restart after 15, 60 and
  120 seconds; one-day counter reset; non-crash failures also trigger recovery.
- Source: `revisions/20260923-service/source`.
- Interpreter: `runtime-service/Scripts/python.exe`, Python 3.13.3, pywin32 311.
  Private base: `python313-service`; no shared Python installation was changed.
- Configuration: `config/server-service.json`; job storage: `jobs-service/`.
- Listener: **127.0.0.1:8043**. Original development task still owns **8042** with
  separate job storage. Legacy Breast remains on 8002.
- PACS metadata: `http://127.0.0.1:8000`; DICOM: 105; patient/download socket: 50052.
  These ports are separate protocols. DICOM port edits do not change HTTP routing.
- Slicer: previously verified `20260923-vc143-candidate` custom runtime.

Automatic approval review rejected the attempted replacement of the 8042 task:
`blocked by policy`, with no detailed reason. The replacement command did not run.
Do not claim that this service owns 8042 or the original task was disabled.

## Authentication

Eagle Eye client access uses a deployment token independent of workstation login.
The new PACS account is a separate service identity, entered once through Settings.
Windows machine-bound DPAPI encrypts it outside source. Its protected file ACL
grants Administrators/SYSTEM full access and LocalService read access. Do not copy
it to another host or commit it. Access tokens remain in memory.

The adapter signs in through the existing `/api/auth/login` contract. HTTP 401
closes the rejected response, triggers login and retries the read once. Metadata
calls serialize renewal. Bad credentials or repeated rejection impose a 30-second
cooldown. HTTP 403 is not treated as expiry. No credential forwarding to another
origin or redirect following is permitted. Credentials bind to the saved origin;
changing it requires saving the account again. HTTP credentials require loopback.

**A real PACS service account has not been provisioned or tested yet.** PACS health
returned HTTP 200 locally. Synthetic expiry/retry/restart/redaction and actual DPAPI
endpoint-binding tests passed. Save the authorized account through the UI, test it
and perform a controlled empty service restart before claiming real account
acceptance. Never send passwords through chat or put them into command arguments.

## Settings UI

The Eagle Eye tab now provides a local PACS preset, separate DICOM/socket ports,
masked password entry, encrypted account save, patient-free connection test,
service status and explicit administrator-only installation. File/network/SCM
operations use the existing settings worker, not the GUI thread.

The independent source settings console uses the same widget:

```powershell
& 'D:\Eagle Eye Server\runtime-service\Scripts\python.exe' `
  'D:\Eagle Eye Server\revisions\20260923-service\source\tools\eagle_eye\settings.py' `
  'D:\Eagle Eye Server\config\server-service.json'
```

Open `Open-EagleEye-Service-Settings.cmd` on this server. Run as administrator when
saving protected account files or installing services. The console neither opens
a second listener nor requires workstation login. Settings apply after restart;
the connection test uses the saved configuration. Reload after external changes.
The installer refuses an existing service name and never changes PACS/Breast/CRM.
An administrator must provision service storage permissions before first start.

## Evidence and limitations

Authenticated protocol 1 and an empty queue passed on 8043. A normal SCM stop
removed the listener; start restored it. Terminating only the verified empty
candidate listener caused automatic recovery and a new listener PID. During that
bounded test delays were temporarily three seconds, then restored to 15/60/120.
Automatic delayed startup is configured; Windows was not rebooted on this clinical
host. Interrupted analyses are not automatically resumed or reported successful.

Actual startup exposed a viewer-package dependency in process ownership. The
server now has its own headless Windows Job Object helper. Its import-blocking
guard failed before the fix; descendant cleanup and real headless child tests pass.
Lifecycle logs rotate across four 1-MB files at `logs/service-lifecycle.log*`.
Failures record type/code/frame positions without passwords, response bodies or PHI.

Canonical focused tests: **66 passed**, direct exit 0, retries disabled. Plugin
parity: **470 pairs passed**; these server files have no pre-existing payload mirror.
Live workstation GUI acceptance is **blocked**: documented MCP ping could not reach
the source app. Offscreen widget tests do not replace this gate. Reboot, real-account
renewal, loaded crash recovery, source mapping and full model tests remain open.

## Operation and rollback

Inspect using Windows Services or `Get-Service AIPacsEagleEye`. Check the authenticated
queue before planned stop and let active work finish. `Stop-Service` was verified
on an empty queue. Closing settings does not stop the service.

To roll back this isolated candidate, stop only `AIPacsEagleEye` and set its startup
to Disabled. Preserve files and verify 8043 is free. The original 8042 task remains
unchanged. Never identify a process by port alone or alter Breast 8002, PACS
105/8000/50052 or CRM 8770. Prepare a stopped new source revision for future edits.

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

## Git-free Brain asset discovery (2026-09-26)

The actual service worker failed before image conversion because lesion bundle discovery required an ancestor `.git`. The deployed source export intentionally has no Git metadata, but its model manifests are present. The anatomy fallback had the same dependency. Source fallback now anchors to `Path(__file__).resolve().parents[3]`; explicit overrides and installed asset roots retain precedence, and frozen builds never use this fallback. Model hashes and the anatomy full-inference qualification remain mandatory.

Only the discovery blocks in `eagle_eye_brain/lesions.py` and `runtime.py`, plus extended Windows paths inside `runtime.sha256`, are in this deployment scope. Do not copy whole dirty local files: other lesion/report changes are separate work. The remote candidate is derived from each current remote file with exact-block assertions and before/after SHA256 receipts under `validation/brain-bundle-discovery-20260926`. Backups are the corresponding `.before` files. Rollback restores these two exact backups when no jobs are active. No PACS database, authentication, source retrieval, report, threshold, or geometry policy changes.

Regression: two tests fail before (two protection checks pass); the five new guards and adjacent Brain/lesion/execution suites give 93 passes, exit 0. Mirror dry run has no drift and verification reports 472 matches. Standard/ARM clients do not contain inference assets; frozen Server discovery is unchanged on both build backends. No installer was built. Source-GUI bridge is unavailable; actual GUI acceptance must be reported separately from worker/API validation.

The anatomy manifest check exposed a second path defect: 146 existing TensorFlow include files exceed ordinary Windows path limits on this host. All match their expected hashes when opened with extended paths. The hashing function now handles local and UNC extended paths without changing machine policy. A synthetic path-limit guard failed before and passes after. No model files were modified. The missing anatomy qualification receipt is the original local receipt bound to the identical manifest; copying it does not assert a new server inference pass.

Deployment preflight passed: all lesion and anatomy manifest hashes matched, and the copied qualification receipt is bound to that exact unchanged anatomy manifest. The scoped repair was activated only after checking every stored service job was terminal and asserting current remote source hashes still matched the backups. The source service launches a fresh adapter subprocess for every job; neither the listener nor supervisor imports these model modules. Therefore new jobs consume the repair without restarting or interrupting the service. A new authenticated request using the original selected study/series reached the running state. Final worker outcome is recorded below; GUI acceptance is still separate.

Final service verification: a new request through the paired authenticated Python Client completed its PACS retrieval and lesion manifest validation under the actual LocalService worker. After 32.38 seconds it stopped in images.read_volume with `This protocol requires a 3D MR acquisition.` This is the expected unchanged input gate, replacing the previous bundle-not-installed failure. No segmentation or PDF was produced, and no completed inference/clinical accuracy is claimed. Service remains Running under LocalService. Actual source-GUI click acceptance remains pending because its documented control bridge was unavailable. The repair is server/worker verified, not GUI- or installer-verified.
