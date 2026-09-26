# Deployment Safety Record — Eagle Eye Razi Development Pilot — 2026-09-22

**Change:** Prepare a source-development Eagle Eye server on Razi; replace legacy
Breast on TCP 8002 only after candidate and rollback validation.
**Gate result:** BLOCKED for deployment/cutover. Read-only preflight completed.

## Workstation/server boundary

- [x] CONFIRMED — Target identity and live listener baseline obtained through the
  documented control-node SSH route; no remote state changed.
- [ ] BLOCKED — Target runtime is not provisioned/qualified: Python 3.13.3 observed,
  missing SimpleITK and win32service; the development checkout uses Python 3.13.5.
- [ ] BLOCKED — Selected-model capacity not measured on target; only 7.6 GB of
  32 GB RAM was free. Heavy Brain execution is not admitted by this evidence.
- [ ] BLOCKED — Updated-client result workflow and clinical continuity on the
  proposed target have not been exercised.
- [ ] BLOCKED — Legacy restart context and successful restoration are not verified;
  parent/child identity and executable path alone are not a complete rollback.
- [–] N/A — No viewer/rendering change is proposed in this deployment slice.
- [x] CONFIRMED — Source service/client tests are recorded in plan section 13;
  they do not substitute for target acceptance.

## Cross-project

- [x] CONFIRMED — API incompatibility documented: legacy `/api/v1/run_*` versus
  unified `/v1/jobs`. Port reuse does not migrate clients.
- [x] CONFIRMED — Local metadata API on 8000 exposes the required study route;
  DICOM 105 and socket 50052 remain distinct. No patient metadata was queried.
- [ ] BLOCKED — PACS storage/authentication mapping, protected source asset closure,
  target credentials and client transport still require verification/provisioning.
- [x] CONFIRMED — Proposed isolation, code/model receipts, restricted data roots,
  staged loopback testing and cutover rollback sequence documented in plan section 14.

## Blocking items

Provision the isolated reviewed environment and model assets; confirm target resource
budgets; validate source mappings and new-client results; establish exact legacy
restart and rollback. Until these pass, keep Breast on 8002 running.

## Sign-off

Manual authorization: the user explicitly requested the Razi development deployment
and eventual Breast replacement in this task. No repeated permission request is
needed for that scope. Authorization does not supply missing technical acceptance.

Reference: `docs/plans/architecture/EAGLE_EYE_SERVER_CLIENT_PLAN_2026-09-21.md`,
sections 13-14. Applied skills: `alizadeh-infrastructure` and `deploy-safety-check`.

## 2026-09-23 authorized isolated-development update

User explicitly authorized staging/execution in `D:/Eagle Eye Server`. The isolated
source pilot is now running on loopback8042 through a manual-only scheduled task;
8,096 transferred files passed target hashing and isolated dependencies passed pip
check. Authenticated actual-client access through SSH succeeded; unauthenticated
access returned401. Breast/PACS/CRM listeners remained unchanged. No clinical job
was run and no LAN endpoint was opened.

**Gate remains BLOCKED for clinical analysis and8002 replacement.** New Slicer
native startup failed with0xC0000142 despite verified binary hashes. The finding
was handed to the build owner. Model assets/environments and PACS storage mapping
remain unqualified; allowed source roots are empty. This staged development pilot
does not override the production acceptance gate or establish installed-service
readiness. Section16 of the existing plan and the target README contain operation
paths, known inactive extraction and the bounded test evidence.

### Later native-startup correction

The separately receipted app-local VC143 candidate passed ordinary launcher and
synthetic headless startup on Razi. The empty pilot was switched to that candidate,
with original runtime/runner retained, then authenticated actual-client connectivity
was reverified. Global CRT and clinical listener processes were unchanged. Native
startup is no longer blocked; model/PACS qualification and8002 cutover remain blocked.
Stopping the scheduled task alone left its Python listener alive; only the verified
empty pilot process was terminated. Production lifecycle qualification remains open.
