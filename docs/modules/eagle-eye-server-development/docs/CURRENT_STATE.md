# Current state and inventory

## 2026-09-26: Smooth-band follow-up (source candidate)

MS-only native 2D paired-band separation is implemented with raw/retained/amber review masks and PDF provenance. Related automated gate: 157 passed; 472 mirrors match. Thresholds remain exploratory, not clinically qualified. The fresh source test bridge responds, but new native GUI acceptance and Razi activation are pending. Earlier unfiltered 2D acceptance does not close these gates. See [method and evidence](LESIONS_2D_2026-09-26.md#reversible-smooth-band-review-follow-up).

## 2026-09-26: Native 2D lesion pilot

See [2D lesion development and evidence](LESIONS_2D_2026-09-26.md). Local source GUI, isolated Razi inference and the authenticated Razi service/API run passed. The service completed in 160.85 s with an identical native mask. Customer redistribution and clinical qualification remain pending. Earlier dated inventory below is historical.


**Full UI update:** [Full workstation deployment](FULL_WORKSTATION.md) records the
complete source, dedicated environment and interactive launch. Human sign-in passed,
but the subsequent source GUI workflow FAILED with a native Advanced fault.

**Latest:** [Independent service acceptance](SERVICE_AUTH.md) adds a LocalService
SCM candidate on 8043 with automatic startup and tested recovery. The inventory
below describes the preserved 8042 task, which was not replaced.

Status checked on 2026-09-23: task running and listener bound to127.0.0.1:8042.
Read-only refresh also confirmed the selected source and VC143 Slicer in deployment.json.
Other evidence below is dated pilot evidence, not continuous monitoring.

| Item | Installed location or state |
|---|---|
| Workspace | D:/Eagle Eye Server |
| Active source | revisions/20260923-dev/source |
| Main environment | runtime/Scripts/python.exe; Python3.13.3, isolated venv |
| Current Slicer | slicer/20260923-vc143-candidate |
| Configuration | config/server.json; config/pilot.token is private |
| Data/logs | jobs/ and logs/ |
| Manual launch | Start-EagleEye.ps1 starts task AI-PACS Eagle Eye Development |
| Task action | Run-EagleEye.ps1 runs tools/eagle_eye/serve.py with explicit config |
| Current scheduling | One computation by default, per-client quota1 |
| Inactive extraction | revisions/20260923-pilot is incomplete; never execute it |
| Historical native runtime | slicer/20260923; fails native startup on Razi |
| Historical runner | Run-EagleEye.before-vc143.ps1; selects that failing runtime |
| Transfer evidence | revisions/20260923-dev/transfer-manifest.json; incoming archive |
| Native correction receipt | logs/slicer-vc143-candidate-receipt.json |

Dependencies installed offline in the dedicated environment: requests2.34.0,
pydicom2.4.5, numpy2.4.4, PySide6 6.10.2, SimpleITK2.5.3 and their wheel dependencies.
pip check passed. The canonical workstation uses Python3.13.5; do not claim complete
environment parity. Model runtimes require their own versions and packages.

The task uses the existing administrator user's S4U token with limited run level.
It has no boot trigger. It survives the SSH session, but is not the final least-
privilege service design. Shared Python and global Visual C++ runtimes were not changed.

## Network roles

| Port | Role | Status |
|---|---|---|
|105|PACS DICOM|Existing clinical listener; preserve|
|50052|PACS socket protocol|Separate metadata/download path; preserve|
|8000|Local PACS API|Required study lookup route observed|
|8002|Legacy Breast API|Still active; not replaced|
|8042|Eagle Eye development API|Loopback only; credentials required|
|8770|Reception CRM|Existing clinical listener; preserve|

PACS source URL is http://127.0.0.1:8000. allowed_roots is currently empty, so
clinical source staging cannot succeed. No remote clinical inference has passed.
The VM has32GB RAM; about8.3GB was free at the earlier pilot sampling. Refresh capacity
before workloads. Heavy Brain execution is not authorized by that capacity evidence.
Windows firewall profiles were observed disabled during preflight; do not rely on
rule scoping as active protection. No LAN HTTP listener was opened for this pilot.
