# `modules/Identity` — external identity framework (Phase 0/1)

Additive, **feature-flagged** layer that lets a signed-in AI-PACS user attach
*external* accounts (Google now; Telegram / Instagram later) to their profile. It
**does not touch the AI-PACS server/center login** — it only *links* external
identities to the current user and stores their credentials securely.

Full design: `docs/plans/cloud-consultation/GOOGLE_DRIVE_CONSULTATION_PLAN_2026-05-31.md`.

## What ships in Phase 0/1
- Provider abstraction (`providers/base.IdentityProvider`) + `registry`.
- `GoogleIdentityProvider` — OAuth 2.0 **Auth-Code + PKCE + loopback** (Desktop app),
  profile via OIDC userinfo, `drive.file` scope requested for the upcoming Phase-2
  Drive transport.
- `secure_store` — refresh tokens in the OS keychain (`keyring` → Windows Credential
  Manager); encrypted-file fallback (`cryptography.Fernet`).
- `database/identity_db.py` — `external_identities` table, self-initializing.
- `IdentityService` — connect / disconnect / list, linked to the current user.
- UI — `IdentityPanel` ("Connected Accounts") + an additive account-area menu hook.

Phase 2+ (not yet implemented): Google Drive transport, consultation packaging,
sync engine, assignment, notifications.

## Enabling it
Default is **OFF** (the account area and login are byte-identical). Turn it on by:
- Environment: `set AIPACS_IDENTITY_MODULE=1`, **or**
- Config file `config/identity/identity.json`:
  ```json
  { "enabled": true }
  ```

## Google OAuth client config
Create a **Desktop app** OAuth client in Google Cloud Console (see the plan §9),
then save its JSON to `config/identity/google_oauth.json`. Either the Console
download shape or a flat shape works:
```json
{ "installed": {
    "client_id": "XXXX.apps.googleusercontent.com",
    "client_secret": "....",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "redirect_uris": ["http://localhost"]
} }
```
For a Desktop client the secret is **not** a true secret; PKCE + the loopback
redirect protect the exchange. Until this file exists, the panel shows "Google OAuth
client not configured" and the Connect button is disabled (the rest of AI-PACS is
unaffected).

## Security notes
- No Google password is ever stored. Only OAuth tokens, in the OS keychain.
- `drive.file` is the least-privilege scope (app touches only files it creates/opens).
- **PHI on Drive requires Google Workspace + a signed BAA** — consumer Gmail is not
  HIPAA-eligible. (Relevant from Phase 2 when DICOM packages are uploaded.)

## Tests
Hermetic unit tests (no Qt, no network, no live DB) in `tests/code/identity/`:
```
python -m pytest tests/code/identity -q
```
