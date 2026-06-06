# Education Cloud — Umbrella CURRENT_STATE — 2026-06-07

Findings from the §3 verification checklist in
`UMBRELLA_HANDOFF_PROMPT_2026-06-07.md`. Run from the Umbrella project,
read-only pass over `D:\laragon-www\` (website) and this repo.
No code was changed.

## 1. Existing website-side Google Drive integration — NONE [CURRENT]

Searched all of `public_html` (PHP/JSON/JS) for `Google\Client`,
`google/apiclient`, `Google_Client`, `drive.file`, `drive.google.com`:
**zero matches**. Laravel `composer.json` has no Google package. No
Drive plugin in `wp-content/plugins/`. The only hits are W3TC's empty
`cdn.google_drive.*` config placeholders (feature unused) and Google
Fonts preconnects.

**Conclusion:** the previously-remembered "Drive work" is the
*workstation's* `GoogleDriveTransport` (modules/cloud_consultation),
not website code. **Decision: build the Laravel `DriveService` fresh in
P0; nothing to reuse server-side.** Its design can mirror the proven
workstation transport (resumable sessions, md5/size verify).

## 2. Laravel stack [CURRENT]

- App: `public_html/consult-form/laravel-back/` (serves `/consult-form/`).
- `laravel/framework ^12.0`, PHP `^8.1`, Livewire `^3.6`,
  `stevebauman/location`; dev: PHPUnit 11, Pint, Sail.
- **No Sanctum, no Passport.** No `routes/api.php` — only `web.php`
  (Livewire consultation form + `forms-panel` session-auth admin).
- Models: `User`, `FormSubmission` only. Services: `NotificationService`
  (mail + Telegram).
- `.env` (local clone of production): `DB_CONNECTION=mysql`, DB
  `u120371228_consult_form`; `QUEUE_CONNECTION=sync`;
  `SESSION_DRIVER=file`; `CACHE_DRIVER=file`; `FILESYSTEM_DISK=local`;
  SMTP via the hub Gmail account.
- ⚠ The clone `.env` holds live secrets in plaintext (DB password,
  Gmail app password, Telegram bot token). Do not add the Drive refresh
  token to this pattern — R2's encrypted-at-rest custody is mandatory.
  Recommend rotating the Gmail app password + Telegram token at a
  convenient moment and keeping clone `.env`s sanitized.

## 3. WordPress ⇄ Laravel user bridge — NONE [CURRENT]

Separate MySQL databases (`u120371228_aipacs` for WP vs
`u120371228_consult_form` for Laravel), separate user tables, no SSO,
no REST bridge, no shared sessions. WP defines the
`radiology_case_author` role (custom plugin); Laravel `users` exists
only for the forms-panel admin. → P0/P1 must introduce the canonical
user + `aipacs_web` pairing exactly as R2 specifies; nothing exists yet.

## 4. Hosting ("VPS") ceilings — OPEN, blocking for the download proxy

Production is **Hostinger** (`ai-pacs.com`). All on-disk evidence says
**shared hosting**, not a VPS: `u120371228_*` account-prefixed DB
names, semi-manual File Manager deploys (no SSH push policy), LiteSpeed,
`QUEUE_CONNECTION=sync` (no worker processes).

Unverifiable from disk: plan tier, disk/inode quota, bandwidth policy,
PHP `max_execution_time`, whether long-running streaming responses and
`queue:work` (or cron-driven `queue:work --stop-when-empty`) are viable.

**Risk:** R2's Laravel download proxy streams multi-GB media through
PHP. On shared hosting this may hit execution-time and fair-use limits.
Options (decide with the owner): (a) confirm Hostinger plan is
Cloud/VPS-class and proceed; (b) host the Laravel control plane / proxy
on the company server `81.16.117.196` instead; (c) keep Hostinger for
control plane + small files and pull the temp-link optimization (R2
"later") forward for big public de-identified media only.

## 5. Hub Google account — OPEN (console check required)

`AI.pacs.medical@gmail.com` is operational (SMTP in use). Cannot verify
from disk: OAuth client type (needs a **Web application** client for
Laravel) and consent-screen publishing status (**must be In
production** — Testing mode expires refresh tokens after 7 days).
Owner action in Google Cloud Console before P0 finalize.

## 6. Website Case-of-the-Day schema [CURRENT]

Plugin `radiology-case-widgets` renders CPT **`r-case`**
(public listing at `/r-cases/`):

- Taxonomy: `system` (body system).
- Post meta: `featured_case` ('1'), `feature_date` (`Y-m-d`),
  `feature_priority` (numeric), `diagnosis_certainty`, `date`.
- ACF: `gallery` (image array; widget shows max 2) + featured image.
- Authoring is manual in WP admin; no inbound API.

P3 mapping note: `item.json` (kind=case_of_day) must carry
title/diagnosis/system/certainty/feature_date equivalents so the WP
publisher can fill `r-case` fields without manual editing.

## 7. Contract adjustments

None to the R2 API shape. Additions required by findings:

1. P0 must install `laravel/sanctum`, create `routes/api.php`, and add
   `google/apiclient` — none exist today.
2. Queue: `sync` today. P0 ships with `database` queue driver +
   cron-driven worker (shared-hosting-safe); revisit if §4 lands on a
   real VPS.
3. The Laravel app is the live consultation-form app. All P0 work must
   be additive (new routes/tables); zero changes to the Livewire form,
   `forms-panel`, or `form_submissions`.

## 8. Relation to workspace docs

`workspace-docs/03-shared-user-model.md` and
`05-case-of-the-day-bridge.md` are [PROPOSED] designs that R2 now
partially supersedes (Drive tier instead of `storage/cases/{uid}`;
Sanctum pair instead of password+fingerprint activate; `education_items`
instead of `cases`). Laravel-as-authority is unchanged. ADR drafted at
`D:\work space AI-Pacs company\docs\decisions\0002-adopt-education-cloud-r2-contract.md`
(status: proposed) to record this supersession and the doc-home rule.

## Status

- 2026-06-07 — §3 verification checklist executed (items 1, 2, 5
  resolved; 3, 4 OPEN pending owner answers). This file written.
  P0 work order proposed to owner; awaiting approval. No code changed
  on either side.
- 2026-06-07 — **P0 approved by owner.** Hosting decision: confirm
  Hostinger plan tier/limits before production placement; P0 proceeds
  on local Laragon meanwhile. Hub OAuth: owner will verify consent
  screen is In production in Cloud Console before `drive:connect`
  stores the refresh token. **Next step:** implement P0 in
  `consult-form/laravel-back` — begin with
  `composer require laravel/sanctum google/apiclient`, then api.php,
  migrations (`education_items`, `education_item_files`,
  `item_permissions`, `audit_log`, `workstation_pairings`), encrypted
  hub-credential custody, DriveService (faked in tests), pair endpoint,
  database queue + cron worker. Additive only; no edits to the live
  consultation form.
