# Eagle Eye Developer server and EchoMind - 2026-09-30

This checkpoint supersedes historical 8042/8043 inventory below other documents.
It is a Developer deployment, not an installer or clinical qualification receipt.

## Active service

`AIPacsEagleEye` runs under LocalService, using
`D:\Eagle Eye Server\revisions\20260930-echomind\source` and
`D:\Eagle Eye Server\config\server-20260930-echomind.json`.
The existing authenticated, certificate-paired TLS listener remains port 8002.
PACS 8000/105/50052 and CRM 8770 were not changed. Seven model adapters and four
interactive correction families remain advertised; this is not proof of their
inference or rendered-result acceptance.

The client sends initial text plus allowlisted workflow context to
`/v1/echomind/process`. The server owns prompts, provider configuration, reference
tools and model choices. Registered RAZI_SERVER aliases select this route; merely
typing a C prefix does not authorize access. Credentials remain protected,
target-local and excluded from source archives, output bodies and installers.
The private directory is `config/echomind-20260930-echomind` with administrator/
SYSTEM control and LocalService read access. Existing authorized Razi clients use
the configured Razi provider identity; this is not arbitrary center impersonation.
See the canonical [routing contract](../../../echomind/EAGLE_EYE_SERVER_ROUTING_2026-09-30.md).

## Verification and source binding

- Endpoint/transport fail-before guards reproduced the old PACS dependency.
- Two additional fail-before guards reproduced lost Turbo Correction modality.
- Final affected local selection: 252 passed, exit 0; 495 mirrors match.
- Target staging selection: 94 passed, exit 0; pip check clean.
- Actual isolated Razi hosting: all 15 synthetic requests passed across 14
  workflows, including ordinary/Turbo Correction and cited Web Search.
- After empty active queues and exact SCM/listener/source ownership checks,
  the versioned candidate replaced the baseline Developer service command.
- Actual paired Client-to-Razi service acceptance: all 15 synthetic requests
  passed. Web Search returned four sources. No response bodies are in receipts.
- The freshly launched source GUI responds to the existing Test Control
  `ping` and `list_actions`. Workflow rendering/inference acceptance is pending;
  a bridge response alone does not close it.

Razi receipts live under `D:\Eagle Eye Server\validation`:
`echomind-20260930-echomind-stage.json`,
`echomind-candidate-workflows-final-20260930.json`, and
`echomind-cutover-20260930.json`. The client receipt is in the ignored canonical
`generated-files/eagle-eye/echomind-20260930/client-razi-workflows.json`.
These contain statuses and provenance, not clinical request/response text.

## Native graphics and hidden warm-up

Razi exposes Microsoft Basic Display Adapter, not an OpenGL 3.2-capable device.
The current prepared Slicer viewer failed WGL pixel-format initialization. Merely
preserving QT_OPENGL or adding OSMesa to PATH did not close that failure.

A separate copy of the current prepared runtime at
`revisions/20260930-echomind/slicer-software-probe` received one app-local delta:
`bin/Release/opengl32.dll`, byte-identical to the existing project
`graphics_runtime/opengl32sw.dll`. The launcher scopes software Qt/PATH choices
to its own process tree. No System32, global driver, previous canonical native
runtime, model weights or installed workstation executable was altered.
An offline_lumbar junction points to the preserved model bundle.

The owned synthetic resident probe reached READY and returned viewer status:
window exists, window_visible=false, hidden_before_show=true, volume_nodes=0.
Its earlier failure after READY was a diagnostic protocol error (status is a
queued command, not a direct operation), corrected before the final receipt.
This proves native startup and hidden warm-up, not clinical pixels, GPU speed,
volume rendering, model accuracy or frozen packaging.

Target receipts: `software-slicer-applocal-final-20260930.json` and
`slicer-applocal-graphics-delta-20260930.json`. Build owners must verify the
app-local software path through their canonical packaging route; do not silently
overwrite or relabel the prepared native payload as already qualified.

## GUI launch and rollback

Human-authorized test launch:

```powershell
& 'D:\Eagle Eye Server\Run-EagleEye-EchoMind-20260930.ps1' -TestServer
```

The existing interactive Developer task was backed up and updated to this
launcher. It refuses another source workstation; the human signs in. The test
flag is explicit for this acceptance session. Normal launches omit TestServer.
Desktop shortcuts were not rewritten in this checkpoint, so they still select
the prior GUI launcher unless separately updated after acceptance.

Service backup: `backups/echomind-cutover-20260930/scm-transition.json`.
The preserved baseline is `revisions/20260930-developer/source` with
`config/server-developer-20260930.json`. Restore its exact saved SCM command only
after checking ownership/empty queues; then start and authenticate the listener.
`previous-gui-task.xml` preserves the task action. Canonical native files remain
untouched. Automatic startup-failure rollback is implemented, but a successful
full rollback drill has not been claimed.

## Remaining gates

Exercise actual Home/viewer/Eagle Eye inputs, all required model executions,
results, annotations/corrections and exports with owner-approved studies. Breast
detection remains available; the previously deferred nine-versus-four stacked
classifier schema is still unavailable and must never appear as a normal finding.
Retain this limitation or obtain the matching qualified training/inference
contract and weights; do not pad features or invent a model mapping.

Complete Developer acceptance before starting the role-selected Server installer
workflow in root BUILD.md. No new version, Git release, installer, full model
acceptance or whole-server clinical readiness is claimed here.
