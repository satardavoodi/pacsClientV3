# Deployment Safety Record — Eagle Eye Razi — 2026-10-08

Change: Activate the scoped experimental lumbar marrow candidate on the existing Razi service.
Gate result: Authorized experimental activation; clinical acceptance remains BLOCKED.

- CONFIRMED: Owner explicitly requested the existing Razi server update.
- CONFIRMED: Scoped immutable candidate hashes checked, server guards previously passed.
- CONFIRMED: All client durable job states terminal before controlled restart.
- CONFIRMED: Prior SCM command and protected config backed up on server.
- CONFIRMED: Authenticated normal HTTPS8002 capabilities and jobs API passed after activation.
- CONFIRMED: Existing EchoMind/Secretary/case capability sections preserved.
- N/A: Viewer rendering changes; this activation changes server source only.
- CONFIRMED: Existing paired TLS and credential references retained; no patient data exported.
- BLOCKED: Real patient inference and full affected GUI acceptance pending first authorized test.

Rollback: Check all client queues, stop AIPacsEagleEye, restore original_binpath from
D:/Eagle Eye Server/backups/marrow-service-20261008/activation.json using structured
Win32_Service.Change, start and verify authenticated TLS. Prior source/config preserved.
No general release, clinical qualification, or patient report acceptance is claimed.
