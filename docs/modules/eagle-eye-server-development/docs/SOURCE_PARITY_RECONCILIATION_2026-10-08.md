# Developer source reconciliation — 2026-10-08

## Selected implementation and deployment boundary

The local Developer checkout is the selected source for the complete, non-running
Razi candidate at `D:/Eagle Eye Server/revisions/20261008-reconciled-developer/source`.
The active SCM service remains on `20261008-lumbar-marrow-r4/source`; candidate
parity must not be described as active-service parity. No release build was run.

The prior audit's 201 content differences were reviewed individually against Git
history, source behavior and focused tests. The resolution ledger retains hashes
and reasons in the protected parity workspace. Remote-only alternatives were
preserved before reconciliation. No newer, correct reverse-only implementation
was identified. The selected code preserves licensing, bounded requests, marrow
review, artifact identity, Home workflow and EchoMind correction/attachment work.
Remote mojibake and older source equivalents were not copied over newer code.

The full source inventory includes database Python modules, build definitions,
tests, documentation and UI resources. Configuration, credentials, patient state,
databases, logs, virtual environments and model/native payloads are intentionally
outside source equality. Private Razi state remains preserved. Final file hashes
and changed-file upload evidence are saved in the protected parity workspace;
equality is a snapshot, not a promise about later edits by another workstream.

## Correctness fixes found during reconciliation

EchoMind text-widget imports initialized PortAudio in a headless server session.
The optional audio backend now loads on the first recording/device operation.
The new import guard failed before the fix; 43 affected local guards passed after
it. The same 43 passed on Razi. Recording behavior and its error handling remain
in the existing path. Canonical and packaged EchoMind source are synchronized.

Razi Breast inference crashed during ITK image loading with Windows exception
`0xC0000005` in System32 `msvcp140.dll` version 14.31.31103.0. A private candidate
Python base uses the existing approved Slicer app-local Visual C++ 14.44 runtime.
The active Python base and Windows system DLLs were not modified. True synthetic
DICOM decoding and the complete Breast model smoke passed in the repaired base.
Portable Breast preparation now includes the approved app-local runtime, probes
ITK's GDCM binding, and build validation requires three sealed essential DLLs.
The packaging guard failed before this change; 15 focused builder guards pass.

Prepared local Breast/Bone worker sources were refreshed from canonical source,
with old bundles backed up and manifests resealed. Breast weights matched Razi.
Bone weights differed in all 488 tensors; the selected local weight exactly
matches the authoritative Windows A100 `D:/Bone/BoneInference/final_model.pth`.
The candidate uses that weight; the active Razi bundle was preserved. Both local
and candidate Breast/Bone complete synthetic model smokes passed. This is runtime
qualification, not clinical validation or a new Breast research result.

## Verification and remaining acceptance

- Initial focused local gate: 243 passed. Final Razi gate including the new audio
  guard: 244 passed. Separate affected local audio gate: 43 passed.
- Initial build-input gate: 42 passed; native runtime packaging gate: 15 passed.
- Plugin mirror verification: 517/517 pairs identical.
- The two configured native Slicer executable hashes match local and Razi. This
  is not a complete native-tree hash or a frozen-build acceptance run.
- The wider diagnostic run had 46 failures, 5257 passes, 16 skips, 15 deselections
  and 12 expected failures. It is not green. Remaining failures include legacy
  direct-provider, role-routing, capability-count, launcher and source-inspection
  expectations; their full repair/acceptance remains separate work. Do not rerun
  synthetic default-client tests against the live configured service blindly.
- Existing control MCP ping has no available local listener. No live GUI or real
  patient workflow acceptance was performed in this reconciliation.
- Razi has no independent signed Eagle Eye Server license for the new admission
  gate. License provisioning and controlled service activation remain pending.
- Other model clinical paths, complete client/server correction roundtrips and
  frozen installers still need their documented acceptance tests.

## Build handoff

Use the canonical BUILD.md candidate coordinator and RELEASE.md clean-commit Git
receipt workflow. Do not build from the dirty working tree or edit generated
installer output. Include the refreshed sealed engine sources/weights, app-local
Visual C++ runtime and the approved current native Slicer payload. Runtime roots
and private server credentials differ by host and must not be copied as source.
The installed service must eventually select the reconciled revision explicitly;
staging a folder does not update SCM or the already-running process.

Protected evidence: local `generated-files/eagle-eye/parity-20261008/` and Razi
`D:/Eagle Eye Server/staging/parity-20261008/`, with candidate test/runtime receipts
beside its `source` directory. No patient identifiers or clinical content belong
in this report or its committed fixtures.
