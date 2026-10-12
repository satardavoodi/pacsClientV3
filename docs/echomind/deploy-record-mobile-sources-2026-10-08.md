# Mobile EchoMind source compatibility and deployment gate

Date: 2026-10-08. Gate result: **BLOCKED**. No service activation or build handoff.

## Verified source and transport contract

The selected Developer revision is `20261008-reconciled-developer/source` on
Razi. It already implements the same attachment and Correction source contracts
as the local Developer checkout; duplicating or reverting them is unnecessary.
The 362 declared EchoMind source/mirror files match SHA-256 in this audit.
The new mobile-shaped HTTP regression test was applied and hash-verified on both
Developer sides. On each host, 65 focused tests passed. These tests exercise the
real HTTP handler, authentication, host dispatcher and document parsing with a
stubbed model. They are not real-provider or simulator acceptance.

Report/Turbo accepts `attachments: [{name, data}]` (base64 original bytes).
Correction accepts `correction_source: {name, data}` and `correction_note`.
Advertised feature names are `report_attachments_v1` and `correction_sources_v1`.
Limits remain six report files, 1 MiB combined input, 100,000 extracted document
characters and 30 PDF pages. PDF support is readable text only. Neither workflow
submits an imaging job. Company prompts, model selection and parsing remain in
EchoMind on the Eagle Eye server. The independent Reception route is unchanged.

## Activation blocker confirmed on the host

SCM still runs `20261008-lumbar-marrow-r4/source`, using the existing
`server-20260930-echomind.json` configuration. Its active capabilities do not
provide the two source features, consistent with the mobile HTTP 422 receipt.
The candidate's actual `server_manager(config).check_license()` returned false:
`No license found. Generate an activation request.` Activating the new source
would introduce its admission gate and reject AI requests. No license bypass,
configuration replacement, pairing edit or service restart was performed.

The existing desktop registrations and independently issued Android pairing are
preserved. Keys, tokens, patient history and host configuration are excluded from
source synchronization. The source candidate is non-executing. A new immutable
activation revision, fresh idle-queue preflight, preserved registration check and
rollback receipt are required after license provisioning and reconciliation.

## Developer parity is not complete

The declared inventory has 8,164 files. Concurrent settings, packaging, server,
requirements and shared-document deltas remain outside this EchoMind slice.
The protected `generated-files/eagle-eye/mobile-echo-20261008/parity-pending.json`
records actual hashes and pending paths; it is a pending-delta receipt, not a
full parity certificate. The equivalent receipt and test evidence are retained
on Razi. Do not overwrite another workstream or claim build readiness. Recheck
the complete source inventory, additional files and model/native payload hashes
after reconciliation; historical payload receipts do not certify current parity.

## PACS execution pairing remains separate

Read-only inspection found listeners 8002 (AI) and 8770 (Reception), but no 8760
or 8775 PACS execution listener. Secretary planning is not command execution.
Execution must pair with a running native Client or full Server workstation using
its Agent Gateway, permissions, confirmation and case identity. A headless AI
listener is not that adapter. Human source launch/sign-in and authorized pairing
remain required; no alternate execution endpoint was improvised. Reception uses
its independent gateway/session and was not moved behind Secretary.

## Remaining acceptance

1. Provision the independent signed Eagle Eye Server license normally.
2. Reconcile concurrent Developer deltas; verify complete source and payload
   manifests with a fresh parity receipt on both hosts.
3. Stage a new immutable revision, confirm idle queues and rollback, then activate.
4. Repeat actual simulator PDF/PNG/TXT Report and saved-source Correction against
   the authenticated active feature declarations, with synthetic content only.
5. Pair the selected native PACS execution workstation and verify permissions and
   completion independently of Secretary planning.

No attachment/Correction provider inference from the simulator was accepted in
this session. Prior mobile acceptance remains accurately limited to planning and
text workflows. The user was asked to provision the missing server license.
