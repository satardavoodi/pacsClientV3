# Deployment safety record - Eagle Eye reference reporting - 2026-10-07

Change: dedicated echocardiography Report/Turbo support and server-owned Add Reference workflow.
Gate result: PASSED for the owner-requested server trial; activated; final receipt reference-r2-20261007-cutover.json.

- CONFIRMED: owner explicitly requested deployment to Razi in this conversation, after the prior response identified source-only status and missing client GUI acceptance. No additional client installation or release is authorized by this record.
- CONFIRMED: candidate `20261007-echo-reference` derives from active `20261007-case-realtime`. Overlay paths and SHA-256 hashes are enumerated in `incoming/reference-manifest.json`. Reporter baseline whitespace is preserved; normalized source matches the canonical implementation.
- CONFIRMED: 27 target reference/history and 22 target case/TLS tests passed; pip check clean. Four actual-provider synthetic cases passed and their outputs were reviewed for retained measurements and calculated comparisons. Local focused suite: 209 passes before final presentation refinement.
- CONFIRMED: no PACS/CRM, DICOM, renderer, FAST, VTK, model weights or acquisition changes. These viewer-specific deployment checks are N/A to this text-service overlay; existing processes must retain listener ownership.
- CONFIRMED: API/data boundary documented in REFERENCE_REPORTS.md. Authenticated existing endpoint and request history retained. Server owns prompts, credentials and references; client owns explicit context and display. No new provider destination or clinical logging path.
- CONFIRMED: transferred overlay contains code and synthetic tests only; no configuration credentials or patient records. Existing credential stores are preserved. This is not a public package release or credential migration.
- CONFIRMED: previous source remains intact. Activation helper writes an ACL-restricted configuration/SCM backup, checks exact baseline/service/listener ownership, repeats authenticated idle checks and restores the previous SCM command on failed post-start acceptance. Shared clinical stores are never rolled back.
- PLANNED: activate only AIPacsEagleEye; verify authenticated capabilities, retained case synchronization and unchanged PACS/CRM listener owners; send synthetic requests from this workstation through its configured paired TLS client.
- PENDING SEPARATE ACCEPTANCE: actual source-client Add Reference dialog, rendered reply and reception export. Existing Test Control is unavailable; human launch/sign-in is required by AGENTS.md. Offscreen widget checks are not live GUI acceptance.

Rollback: stop only AIPacsEagleEye after verifying it owns the candidate listener and there is no active work; restore `old_command` from `D:/Eagle Eye Server/backups/reference-20261007/transition.json` using SCM Change, start the same service and verify authenticated capabilities. Preserve shared history and job data. The activation helper implements this automatically if its acceptance checks fail.

Manual approval: GIVEN by the user for this server trial in the current request.

## 2026-10-07: Echocardiography and reference review activated

Razi AIPacsEagleEye now runs `20261007-echo-reference-r2`, derived from the
active case-realtime baseline. It adds the ECHOCARDIOGRAPHY Report/Turbo prompt
and server-owned `add_reference` workflow. Registry 2026-10-07.2 provides
INTERGROWTH fetal centiles and ASE adult echo limits; missing context and
unsupported parameters remain unclassified. Signed unsupported values (GLS)
remain in the review. It is a measurement review, not automatic clinical grading.

The target passed 28 reference/history and 22 adjacent case/TLS tests; pip check
passed. Four actual-provider synthetic examples passed. Authenticated activation
retained seven model routes, case synchronization and 15 EchoMind workflows;
PACS, DICOM and CRM listener owners were unchanged. Workstation-to-Razi requests
for echo reports and both reference families passed; the final request confirmed
registry .2 and retained negative GLS. Restricted rollback configuration/SCM
backup and immutable prior source are retained. Receipts are server validation/
reference-r2-20261007-stage.json, reference-r2-20261007-provider.json and
reference-r2-20261007-cutover.json. Actual fresh-source client GUI and reception
export acceptance remain pending. No installer or full clinical qualification.
See docs/echomind/REFERENCE_REPORTS.md in the canonical workstation repository.

Final local verification: 260 passed, two frozen-stage checks skipped (no build); 513 plugin mirror pairs matched.
