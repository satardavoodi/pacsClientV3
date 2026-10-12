# Eagle Eye case synchronization activation record

**Change:** Enable authenticated same-center saved EchoMind/Eagle Eye discovery,
case notifications and PACS workflow bridging for open Patient tabs.
**Gate result:** APPROVED and activated; actual Patient GUI acceptance remains pending.
**Active source:** 20261007-case-realtime; prior baseline retained for rollback.
**Verified candidate:** 20261007-case-realtime, activated after explicit owner authorization.

- CONFIRMED: isolated baseline-derived candidate, 16 hash-verified overlay files;
  no private configuration or clinical records in the transferred overlay.
- CONFIRMED: 80 target tests passed, retries disabled, direct exit zero, pip check
  clean. Includes paired TLS, owner-private cancellation, same-center history,
  exact patient/study authorization, saved-result reads without new inference,
  real wire events and PACS bridge recovery. The older TLS fixture required the
  newly mandatory synthetic case identity; production authorization was retained.
- CONFIRMED: 59 local case/Patient/network tests passed; 45 adjacent local server,
  TLS, service-host and EchoMind tests passed; 513 mirrors match.
- CONFIRMED: no renderer/model/weight changes. Existing private TLS identity,
  provider settings, source account and seven advertised model routes retained.
  The candidate retains the active baseline's Secretary request-size limit.
- CONFIRMED: authenticated read-only preflight reports protocol 1, paired TLS,
  seven modules, zero active model jobs and zero active EchoMind history requests.
  Counts are a point-in-time observation; activation must repeat them.
- CONFIRMED: protected configuration and exact rollback command backed up under
  the server's backups/case-realtime-20261007-prepared. Prior source remains intact.
- CONFIRMED: reviewed activation helper verifies source hashes, exact SCM account,
  listener ownership and empty work, preserves config, and restores the prior SCM
  command automatically if post-start authenticated acceptance fails. Syntax
  verified; approved helper executed successfully. Shared result/history stores are not restored
  over newer clinical records by automatic rollback.
- CONFIRMED: API/data ownership is the existing three-node contract: PACS owns
  identity/workflow; Eagle Eye owns saved jobs/text; events carry invalidations.
  Same-center membership is server-owned and exact case reads reverify PACS.
- CONFIRMED: Patient capability retry waits interruptibly for 15 seconds when the
  server has not yet been upgraded. Its fail-before guard passed after correction;
  an open tab can reconnect after activation without a new inference request.
- PLANNED: immediately after approved cutover verify existing authenticated
  capabilities and case capability; then source Patient red availability, selected
  saved-result retrieval and second-client updates for all six module families.
  Actual Patient GUI acceptance and clinical inference qualification are separate;
  neither is claimed by staging or synthetic acceptance.
- BLOCKED: human approval to stop/restart only AIPacsEagleEye and point it at the
  staged source. PACS/CRM and clinical imaging listeners are outside this change.

Manual approval: GIVEN by the owner on 2026-10-07. Only AIPacsEagleEye was restarted. The activation receipt supersedes staging-time planned/blocked entries above.


## 2026-10-07: Razi Eagle Eye case synchronization activated

The owner explicitly authorized the prepared Razi update. AIPacsEagleEye now runs
20261007-case-realtime under its existing LocalService identity and private config.
Authenticated paired-TLS acceptance passed: protocol 1, case_realtime enabled,
seven model routes and fourteen EchoMind workflows. The post-start preflight
observed zero active model jobs and history requests. Existing PACS 50052/8000,
DICOM 105 and CRM 8770 listeners retained their prior process owners.
Restricted configuration/SCM backup and immutable baseline remain available.
Receipt: server validation/case-realtime-20261007-cutover.json, activated=true.
The 80 candidate tests passed before activation. Actual source Patient red
availability, saved-result retrieval and second-client updates remain pending;
transport acceptance does not establish clinical or GUI acceptance.
