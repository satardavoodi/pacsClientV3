# Secretary AI panel settings controls

## Diagnosis

The owner reported that Ruler color worked but changing speech recognition did not. The latest local session routed correctly to Settings and proposed open_settings(section=echomind). Its successful navigation receipt did not change or save the transcription provider. The gap was a missing executable AI preferences contract, not evidence of a transcription failure.

## Implemented controls

- get_ai_settings: credential-free snapshot of Voice to Text, proxy, personal model preferences and Eagle Eye connection role/address.
- set_voice_to_text_preferences: explicit existing provider selection and bounded timeout, merged with all existing custom/secret fields, persisted and read back. Google Speech maps to v2t. Applies to new recordings in both Chat and Secretary; does not interrupt active recording.
- set_ai_proxy_preferences: existing direct/SOCKS5 loopback choices and existing ports 2080/2081/2082.
- set_personal_ai_preferences: personal model/effort/temperature/token budget/timeout fields; allowed only with configured personal mode, the user's credentials and explicitly defined prompt. Patches exact fields, preserves other settings and zero temperature.
- verify_eagle_eye_connection: existing authenticated TLS/capability probe without an inference job or configuration change.
- set_eagle_eye_connection: an explicit HTTPS target, with existing pairing/trust preserved; probes before saving, uses existing revision conflict protection and checks readback. Server-role listener edits remain the local administrator form.

All controls are typed shared CommandBus actions with a thin MCP wrapper. Mutations require confirmation, deny read-only execution and produce asynchronous operation IDs verified by settings_operation_status. Workers own I/O. Existing AI form fields refresh only changed values from the verified receipt; no credential reload occurs on the GUI thread. Prompts, keys, arbitrary private paths and credential-bearing URLs cannot be entities or receipts.

Company prompts/model selection remain owned by authenticated Eagle Eye. These controls do not add a client-direct company inference route. Existing shared transcription provider preferences remain a legacy path; this slice does not claim an Eagle Eye audio migration. Credential, custom endpoint and prompt entry stay in local forms. Remote server listener/resource/prompt administration is not represented as a completed client setting change.

## Verification and deployment scope

Four initial implementation guards failed before the missing contracts were added. The focused suite subsequently passed 208 tests covering prior Settings controls, strict client/server schemas, permissions, polling, isolated persistence, preservation of secrets, personal-mode prerequisites, TLS probe-before-save and actual MCP stdio inventory.

Final form checks exposed and corrected two related display defects: zero temperature was rendered as 0.2 on reload, and the Eagle Eye personal model fields have different widget names from the other model combos. Both form guards failed before correction. Final test count is recorded below after verification.

Final focused run: 210 passed, exit code zero. Scoped client mirrors and server snapshot hashes match. Retrieved activation receipt confirms activated=true, authenticated_contract_passed=true, config_preserved=true, gui_acceptance=false. A fresh documented ping again returned an unavailable local test socket; native GUI acceptance remains pending, not passed.

Razi developer activation passed 37 staged server guards and pip check, checked zero active jobs/text requests and preserved private configuration. Authenticated Act/Ask/Guide/Help Ticket and twelve typed-settings planning scenarios passed. Google selection proposed set_voice_to_text_preferences with provider=v2t and confirmation; Voice timeout, proxy, Eagle Eye verification and safe AI snapshot proposed their actual controls. No workstation command was executed by these server probes.

Native source acceptance remains separate: the documented local test socket was unavailable in the previous probe. No source restart, authentication automation, live provider switch, clinical mutation or workstation release is performed by these tests.

The authorized target for the server-owned catalog is the existing Razi developer AIPacsEagleEye service only. Candidate source tests and authenticated synthetic planning are required before acceptance. Previous source and exact SCM command are retained for rollback; the activation script checks host, service owner, configuration hashes and idle jobs/requests, then automatically rolls back on authenticated acceptance failure. Private configuration and pairing files remain unchanged. No PACS service or website is updated.

Candidate: `D:/Eagle Eye Server/revisions/20261004-secretary-ai-settings/source`.
Previous: `D:/Eagle Eye Server/revisions/20261003-secretary-settings-controls/source`.
Receipts: `D:/Eagle Eye Server/incoming/secretary-ai-settings-20261004/`.
