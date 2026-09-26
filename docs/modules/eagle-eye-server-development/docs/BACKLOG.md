# Execution backlog

## Smooth-band follow-up acceptance (2026-09-26)

Source implementation and 157 automated tests complete. Complete fresh native GUI run/export, clinician review of retained and separated candidates, scoped versioned Razi candidate/API acceptance, and separate installer/clinical qualification. Preserve small lesions and explicitly evaluate false negatives; one exploratory case cannot set universal normal-signal thresholds. See [2D owner record](LESIONS_2D_2026-09-26.md#reversible-smooth-band-review-follow-up).

## 2026-09-26: Native 2D lesion pilot

See [2D lesion development and evidence](LESIONS_2D_2026-09-26.md). Local source GUI, isolated Razi inference and the authenticated Razi service/API run passed. The service completed in 160.85 s with an identical native mask. Customer redistribution and clinical qualification remain pending. Earlier dated inventory below is historical.


This is the local execution view of the existing Eagle Eye Server/Client plan and
OPT-51, not a separate architecture roadmap. Update state and evidence as work completes.

| ID | Work | Owner | State / completion evidence |
|---|---|---|---|
|D1|Dedicated source environment and authenticated loopback API|Eagle Eye|Verified pilot|
|D2|New custom Slicer target startup with app-local CRT|Build|Synthetic startup verified; clinical models separate|
|D3|Graceful owned stop/drain and no orphan listener|Eagle Eye|Empty SCM stop/recovery verified on 8043; loaded drain and original task gap open|
|D4|Complete reviewed source/import closure and isolated model assets|Eagle Eye|Full UI source/environment plus 126,380 model payload files verified; full service-source binding and target inference unqualified|
|D5|Authoritative local PACS storage/authentication mapping|Eagle Eye + Unify|Open; allowed_roots remains empty|
|D6|Uncached acquisition, cache leases and completion manifests|Unify producer / Eagle Eye consumer|Open; use existing handoff|
|D7|Measured CPU/RAM/disk/GPU admission and module readiness|Eagle Eye|Open; capability names are insufficient|
|D8|Razi Bone Age and Breast detection, then remaining models|Eagle Eye|Open; resource and source gates first|
|D9|Transactional queue recovery, attempts and result publication|Eagle Eye|Open; restart currently interrupts work|
|D10|Client recovery UI, native result acceptance|Client/Eagle Eye|API resume exists; UI acceptance open|
|D11|Production listener limits/TLS, protected config, retention/backup|Server|Open; pilot is loopback over SSH|
|D12|SCM service/account/reboot/update/installer parity|Server + Build|LocalService installed; recovery verified; reboot, real account and installer gates open|
|D13|Replace legacy8002 and qualify updated clients/rollback|Server + Client|Not performed; requires prior acceptance|
|D14|Interactive annotation revisions and recomputation|Client + Server|Phase two|
|D15|Breast stacked-classifier feature compatibility/optimization|Breast|Deferred by owner; never label classification ready|

## Immediate acceptance blocker

The full-workstation source GUI gate failed after human sign-in on Razi. Diagnose
the session-scoped Advanced SetInputData native fault with the Viewer owner and
Home Reception-breaker stall with the shared UI owner before repeating viewer
acceptance. DICOM receipt exists, but successful rendering is not certified.
Do not patch another owner's runtime, change its feature flags or relaunch a
crashed clinical-source UI without the documented owner/human workflow.
See [full-workstation evidence](FULL_WORKSTATION.md).

See [service acceptance](SERVICE_AUTH.md) for completed D3/D12 work. Next are
real-account/UI acceptance, pilot consolidation, D4/D5 and actual model tests.
Build owner continues shared CRT/cache parity independently. Do not make native
packaging edits in parallel with that workstream or copy another task's unfinished
assets. Do not promote to8002 merely because the API or Slicer startup responds.
