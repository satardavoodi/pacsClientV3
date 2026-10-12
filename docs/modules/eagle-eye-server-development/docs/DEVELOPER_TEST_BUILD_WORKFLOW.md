# Developer test and local build workflow

Owner decision: 2026-10-09. This records the standing workflow, not a build request.

| Responsibility | Host and source |
|---|---|
| Client development and source GUI | Control PC, canonical workstation repository |
| Eagle Eye Server development | Same canonical source and role-specific entry points |
| Server Function Tester and function scenarios | Razi, reviewed Developer source snapshot |
| Client-to-Server integration | Local source Client to authenticated Razi Developer Server |
| Client and Eagle Eye Server candidate builds | Control PC only, after tests and acceptance |
| Installed candidate qualification | WinA100, before any customer installation |

The canonical local root is E:/ai-pacs/ai-pacs codes/ai-pacs beta version.
Razi revisions live under D:/Eagle Eye Server. Resolve the selected revision from
fresh parity and activation receipts; never assume the latest folder is executing.

1. Inspect local and Razi changes and preserve concurrent owners' work.
2. Reconcile source, tests, documentation, mirrors and required asset revisions.
   Record complete declared inventories and hashes on both hosts.
3. Stage immutable source before activation. Confirm the same owned service,
   model queues, active text requests, license, TLS identity and rollback command.
   Activate only after work drains; no installed executable, blind process kill,
   automatic hot reload or edits to executing source.
4. Verify the real child process uses the selected source and authenticated APIs.
5. Run server function scenarios/Function Tester on Razi. Test local source Client
   connectivity, modes, typed commands, actual completion and relevant GUI flow.
   Keep synthetic checks, actual model runs and physician acceptance distinct.
6. Only after required acceptance, use BUILD.md/RELEASE.md on the control computer
   for role-selected Client and Server candidates. No build was requested merely
   by saving this standing workflow. Do not bypass fresh clean-commit receipts.
7. Install the exact locally built candidate on WinA100 and record its artifact
   hashes, installation/service behavior, functional checks, stability/KPIs and
   rollback result. Customer installation requires successful WinA100 acceptance.

## Stability and qualification clarification (owner decision, 2026-10-10)

The local canonical repository and the Razi Developer snapshot are the same
development line. Razi is the running, loaded Developer environment; matching
files alone do not prove that its process is executing the reviewed revision.
Build locally only after reconciliation and the required tests. Qualify that
exact artifact on WinA100 before customer installation. WinA100 is the owner's named
qualification computer, corrected explicitly from WinA7 on 2026-10-10. Verify
its identity and access before installed acceptance; preserve its existing demo
services and use the documented isolated qualification workflow.

Use the existing server regression, resource scheduling, lifecycle, recovery and
KPI/load test infrastructure first. Coordinate Razi load windows and isolated
synthetic workloads with the Eagle Eye Server owner. Record workload, concurrency,
duration, source/configuration identity, queue and terminal counts, latency
percentiles, CPU/RAM/handle trends, disk/log growth and cleanup/recovery separately.
An idle resource sample or successful capabilities request is not a load test.
Preserve clinical PACS/Reception work and private data; never infer model/provider
capacity or long-running stability from unit tests. This standing workflow does
not itself request a build, customer deployment or uncontrolled stress of shared
clinical services.

## Former Client installations

The old Razi source accepted a legacy Client entitlement. The current Server role
uses a separate machine-protected signed Server store. A Client license is not a
Server entitlement; path changes or key renaming cannot perform role migration.
For this owner-authorized internal Developer transition, the official company
issuer records a same-device Server activation bounded by the verified remaining
whole days of the existing valid entitlement, without a customer payment/order
or additional validity beyond that entitlement. The Client license remains intact.
No signing material is copied to Razi; public-root verification and request/base
binding remain enabled. This individual internal migration is not a general
Client-to-Server licensing fallback or permission to grant commercial products.

Private request, issuance, original Client hash, protected Server state and
activation/rollback receipts remain outside repository source. Never put codes,
fingerprints, account credentials or patient content in documentation or fixtures.

The current private readiness/activation receipts are under
local generated-files/eagle-eye/parity-20261008 and the corresponding protected
Razi staging directory. Source parity, running-source identity, function tests,
GUI acceptance and frozen artifact acceptance must be reported separately.

## Native Secretary shutdown and update order (2026-10-12)

Keep the authenticated old source GUI attached while the owning service performs
its reviewed cooperative transition. The service must obtain the native hold
receipt and certify zero accepted work before closing the old backend. Closing
the GUI first loses that proof: an unverified detach intentionally poisons
admission, even when the operator believes the application is idle.

After the backend transition qualifies and its source/configuration identity is
verified, close the old GUI and let the human launch and log into one matching
new source GUI. Do not start a second GUI or reuse the old attachment as evidence
of acceptance for the new backend.

If the GUI has already closed or cooperative stop refuses, preserve the refusal
journal and inspect the existing bounded diagnostics. Do not retry blindly,
clear uncertainty, unregister a guard, or bypass the admission fence. Recovery
requires the reviewed, generation-bound owned-SCM maintenance procedure and
explicit approval for the interruption and possible cancellation of unfinished
Eagle Eye work. PACS and Reception services remain outside that scope.

The connection-convergence candidate with manifest prefix `bbd4b471` retains the
active `c26abd5c` lifecycle implementation. It does not repair or relax the
closed-GUI fence. This ordering clarification is documentation only; stage it
separately from that frozen candidate and record its later Developer parity.
