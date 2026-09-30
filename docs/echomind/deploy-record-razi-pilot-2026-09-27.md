# Deployment Safety Record - Razi configuration pilot - 2026-09-27

Change: additive pilot account and previously absent EchoMind provider configuration;
workstation/server source changes remain undeployed.
Gate result: configuration pilot verified; source release/native acceptance BLOCKED.

- CONFIRMED - Owner explicitly authorized the Razi pilot and direct external IP.
- CONFIRMED - Added one named pilot account with generate_reports only; no existing
  users, studies or reports changed. Dedicated credentials are encrypted in client
  registry and handed off through a restricted private access-code file.
- CONFIRMED - Only two absent EchoMind configuration files were created; directory
  ACL inheritance is disabled for Administrators/SYSTEM. Staging secret copies removed.
- CONFIRMED - Rollback helper at D:/EchoMind-Pilot-20260927/rollback.py verifies
  file hashes/account ownership before disabling the account and archiving new files.
- CONFIRMED - Text, modality, template and gate context boundary documented in
  RAZI_SERVER_PILOT_2026-09-27.md. No audio/system prompts/provider keys in report payloads.
- CONFIRMED - Actual synthetic report/Turbo/correction/translation completed through
  public IP. No patient material used; this is not clinical QA.
- N/A - Viewer, DICOM, thumbnails, service lifecycle and installed executable changes:
  none were made by this pilot configuration action.
- BLOCKED - Native source GUI/Reception acceptance: documented control ping unavailable.
- BLOCKED - Turbo Correction source extension not installed; no server binary deployment.
- CONFIRMED - Existing eight center records and current local Razi settings preserved.

Manual authorization: user in this task. No approval inferred for a production release,
installer build or deployment of the Turbo Correction source extension.
