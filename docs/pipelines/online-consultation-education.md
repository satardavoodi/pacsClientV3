# Online Consultation (Education submodule) — as-built record (2026-06-06)

**Status:** implemented + unit-verified (72/72 in `tests/code/cloud_consultation`,
`tests/code/identity`, `tests/code/education_online_consultation`); plugin mirrors
307/307. Live A→B→A round-trip QA pending (needs two machines / two Google accounts).

Builds on `docs/plans/cloud-consultation/GOOGLE_DRIVE_CONSULTATION_PLAN_2026-05-31.md`
(R2) — Phases 0–6 were already implemented; this records **Phase 7: the production
wiring + the Education ▸ Online Consultation submodule**.

## 1. What changed (2026-06-06)

| Area | Change |
|---|---|
| `modules/education/online_consultation/` | **NEW submodule**: `consultation_page.py` (the tab: Google chip + New consultation… + Inbox / Sent / Notifications), `study_select.py` (multi-select local-study picker + `build_export_callable` staging via the EXISTING `export_studies_to_offline_cloud`), `respond_dialog.py` (assignee opinion → `record_and_upload_response`), `status_labels.py` (direction-aware Pending/Sent/Received/Answered/Closed mapping), `launcher.py` (open the tab from anywhere), `__init__.py` (`online_consultation_available()` = Identity flag AND cloud flag). |
| `modules/education/education_module_redesigned.py` | Adds the "Online Consultation" tab — **only when both flags are on**; guarded `try/except`; `last_instance()` weakref + `show_online_consultation()` for the launcher. Flag-off ⇒ Education renders byte-identically. |
| `modules/cloud_consultation/notifications/autostart.py` | **NEW** `ensure_consultation_poller(auth_user)` — idempotent app-level poller singleton (parented to `QApplication`), restarts on identity change, no-ops when flag off / no Google identity. |
| `modules/cloud_consultation/notifications/detect.py` | **NEW** `find_response_updates(transport, outgoing_rows, known_ids)` — originator-side: detects responses uploaded into my sent consultations. |
| `modules/cloud_consultation/notifications/poller.py` | Scan thread now also checks outgoing `uploaded/downloaded/reviewed` rows → `response_received` notification + local status `answered`. Assigned-scan unchanged; also stashes `from_handle` on incoming rows. |
| `modules/cloud_consultation/consultation/workflow.py` | Best-effort `_notify()` hooks: sent (`upload_done`), downloaded (`download_done`), response sent / **NEW `close_consultation()`** (`consultation_updated`, state-machine-guarded `… → closed`). |
| `modules/cloud_consultation/ui/account_popup.py` | "New consultation" now routes to Education ▸ Online Consultation (falls back to the bare dialog); new "Open Online Consultation (Education)" entry. |
| `modules/cloud_consultation/ui/account_hook.py` | Calls `ensure_consultation_poller()` at attach time (guarded). |
| `config/cloud_consultation/cloud_consultation.json` | **NEW — flag ON** (`{"enabled": true}`): consultation leaves test mode for this source build. Identity flag was already on; OAuth Desktop-app client config already at `config/identity/google_oauth.json`. |

## 2. Architecture (unchanged boundaries)

```
account pill ▸ AccountPopup ──link──▶ Education ▸ Online Consultation tab
                                         │ picker → export engine (UNCHANGED offline_cloud)
                                         │ compose → seal envelope → CloudSyncEngine.upload → share
                                         ▼
modules/Identity (creds only)  ──vends──▶ GoogleDriveTransport (drive.file scope)
ConsultationPoller (QApplication-level): assigned→inbox+notify · responses→answered+notify
```

* Identity owns credentials; consultation never sees tokens. Server login untouched.
* The Offline Cloud package engine is reused **unchanged**; the envelope is a sibling
  `consultation.json` (integrity = SHA-256 of every package file).

## 3. Invariants (keep)

1. **Double-flag gate:** the Education tab and poller must remain inert when either
   `AIPACS_IDENTITY_MODULE` / `config/identity/identity.json` or
   `AIPACS_CLOUD_CONSULTATION` / `config/cloud_consultation/cloud_consultation.json`
   is off. `online_consultation_available()` is the single gate — don't bypass it.
2. **Internal statuses are frozen** (`pending|uploaded|downloaded|reviewed|answered|closed|conflict`,
   state machine in `sync/state_machine.py`). The clinical labels
   (Pending/Sent/Received/Answered/Closed) are **display-only**, direction-aware, in
   `status_labels.py`. Never persist a display label.
3. **Engine reuse, not forks:** study staging goes through
   `export_studies_to_offline_cloud` (a staging dir is just a folder-path "server");
   `build_export_callable` must keep raising on `ok=False` so a broken package can
   never upload.
4. **All blocking work off the UI thread** (connect / export+upload / download /
   respond run in QThread workers; poller scans in `_ScanThread`).
5. **Poller is a singleton** on `QApplication` (`_aipacs_consultation_poller`),
   restarted only when the Google identity changes; `ensure_consultation_poller`
   must never raise into callers (title bar / Education construction).
6. **`close_consultation` validates via `assert_transition`** — keep the terminal
   `closed` semantics; notifications are best-effort (`_notify` swallows).
7. Education flag-off rendering stays byte-identical (guarded import + `try/except`
   around the tab block).

## 4. Tests

```
python -m pytest tests/code/cloud_consultation tests/code/identity tests/code/education_online_consultation -q -p no:debugging
```
New guards: `tests/code/cloud_consultation/test_response_detection_and_close.py`
(response detection, close lifecycle + illegal-transition, workflow notifications)
and `tests/code/education_online_consultation/test_online_consultation_submodule.py`
(flag gating, label mapping completeness, export staging incl. failure paths).

## 5. Known limits / next steps

* **PHI:** consumer Gmail is NOT HIPAA-eligible — real patient data requires Google
  Workspace + BAA (plan §10.1). Current client config is suitable for
  de-identified/teaching cases and pilots.
* Viewer ingest of a downloaded package still goes through the existing Offline
  Server import flow (the page points the user there after a verified download);
  one-click "ingest + open in viewer" is a future step.
* OAuth client in *Testing* mode expires test-user grants every 7 days (plan §9) —
  move the consent screen to *In production* (or Workspace *Internal*) for real use.
* Same-account multi-provider (Telegram/Instagram) slots into
  `modules/Identity/providers/` + `registry.py`; consultation code needs no changes.

## 6. Purchasable-module integration + PHI gate + one-click ingest (2026-06-10, ADR-0003)

Implemented per `D:\work space AI-Pacs company\docs\decisions\0003-consultation-as-purchasable-module.md`:

| Area | Change |
|---|---|
| `aipacs_runtime.py` | `MODULE_CATALOG` gains `identity` (tier basic/core, ships `modules/Identity`) and `consultation` (tier optional, `bundled_unlock`, ships `modules/cloud_consultation`, `default_enabled: False`). |
| `builder/plugin package/definitions/{identity,consultation}/` | NEW plugin package definitions (registry parity test enforces them). |
| `builder/installer/AIPacs_Setup.iss` | NEW `optional\consultation` component + file-copy line. |
| `modules/education/online_consultation/__init__.py` | **Gate is now TRIPLE:** Identity flag AND cloud flag AND `is_module_enabled("consultation")`. The registry check FAILS OPEN; dev/source runs unchanged (dev defaults enable all modules). `online_consultation_available()` remains the single gate. |
| `modules/cloud_consultation/consultation/deidentify.py` | NEW in-place package de-identifier (B3). Policy mirrors `cd_burner/dicom_prepare.py` (names/IDs/dates/physicians/institution blanked; UIDs preserved so package metadata stays consistent; sidecar json scrubbed; `deidentification.json` summary). **Failure deletes the file — an identified file never uploads.** Does NOT import cd_burner (separate package). |
| `modules/education/online_consultation/study_select.py` | `build_export_callable(..., deidentify=True)` — de-identification runs after staging, before sealing; raises if no clean image survives. `deidentify=False` reserved for BAA-grade Workspace deployments. |
| `modules/education/online_consultation/package_import.py` + `consultation_page.py` | NEW one-click "Import to library" (B4): reuses `sync_offline_cloud_study_to_local` (no fork) on a QThread worker. |
| `launcher.py` | Friendly "module not installed" notice when the gate is off (printing-module pattern). |

Updated invariants: (1) in §3 reads "double-flag" — it is now **flags AND module registry**, registry failing open; (2) **de-identification is default-ON in the compose path** — never disable it silently; an upload of identified PHI on consumer-Gmail transport is a clinical/compliance violation. Tests: 114 green (`tests/code/cloud_consultation`, `identity`, `education_online_consultation`, `builder/test_plugin_package_registry.py`); mirrors 309 pairs.

## 7. Hub-account mode + lifecycle completion (2026-06-10 evening, ADR-0004)

Closes the R1 §4.4 cross-account gap for v1 and finishes the respond/close lifecycle:

| Area | Change |
|---|---|
| `feature_flags.py` | NEW `hub_mode_enabled()` (env `AIPACS_CONSULTATION_HUB_MODE` / `hub_mode` in the flag file) and `consultation_address(default)` (env `AIPACS_CONSULTATION_ADDRESS` / `consultation_address` key / fallback = Google handle, lowercased). |
| `notifications/autostart.py` | Poller inbox matching now uses `consultation_address(default=handle)` — hub mode routes per physician while both workstations poll the SAME hub Drive. Personal-account mode is byte-compatible (fallback). |
| `consultation/assignment.py` | Persists `share_permission_id` (new `consultations` column + in-place ALTER migration in `consultation_db`). Share failure is **non-fatal in hub mode only** (`share_failed` event); personal mode still raises. |
| `consultation/workflow.py` | NEW `revoke_consultation_access(transport, cid)` — best-effort, never raises, audits `share_revoked` / `share_revoke_failed`, clears the stored permission. Wired fire-and-forget after close in `consultation_page._revoke_after_close` (close itself stays local/DB-only). |
| `consultation/service.py` | NEW `stage_response_attachments(package_root, paths)` — copies response files INTO the package (`responses/<id>/`) BEFORE `record_response` re-seals, so the envelope hash covers them and the upload mirrors them. Copy failure raises (a response never silently loses its attachment). |
| `respond_dialog.py` | "Attach files…" + count label; worker stages attachments then `record_and_upload_response(attachments_ref=…)`. |
| `transport/google_drive.py` | NEW `revoke()` (permissions.delete); ALL Drive calls now pass `num_retries=3` (googleapiclient exponential backoff on 5xx/429). `transport/base.py` gains optional `revoke` (default NotImplementedError). |
| `consultation_page.py` | Google chip shows the routing address in hub mode and warns when `consultation_address` is missing. |

Invariants added: **share revocation and hub-mode share are best-effort** — they must never block or fail the local clinical action (close/send); **`stage_response_attachments` must run BEFORE `record_response`** (re-seal coverage); keep `num_retries` on every Drive `execute()`/`next_chunk()`. Hub deployment per workstation: connect the hub Google account + set `hub_mode` + unique `consultation_address`. Known trade-off (ADR-0004): hub-connected workstations can technically read all consultations — mitigated by default-ON de-identification; structurally fixed by R2 P4. Tests: 128 green; mirrors 309 pairs.

## 8. Per-physician Drive structure + quota gate (2026-06-10 night, ADR-0005)

Hub Drive layout is now **`AI-PACS Consultations/<consultation_address>/<cid>/`** with a
`physician.json` control file per physician folder. **Laravel is authoritative** for
quota/sharing/ownership (its `physician_storage` table + `physician:quota`,
`drive:sync-usage`, `physician:push-meta` commands + admin/share APIs); the file is its
pushed snapshot.

| Area | Change |
|---|---|
| `consultation/physician_store.py` | NEW (Qt-free): `ensure_physician_folder` (address lowercased), `read/write_physician_meta` (create-or-replace), `check_quota` (pure), `bump_usage`, `local_tree_size`, `count_consultation_folders`. |
| `consultation/workflow.py` | Hub-mode upload: physician folder ensured → quota gate → `make_child_folder(phys, cid)` → `engine.upload(root_remote_id=…)` → approximate usage bump (best-effort). Quota block raises BEFORE any byte moves, records `quota_blocked` event, leaves status `pending`. Layout failure falls back to the legacy path (warn) — never blocks a send. Personal mode byte-identical. |
| `notifications/detect.py` | `find_assigned_consultations` is layout-aware: bounded two-level scan (legacy `app/<cid>` AND `app/<address>/<cid>`); `_check_consultation_folder` helper. |

Key invariants (§8): **quota gate FAILS OPEN without `physician.json`** (unconfigured admin
must never block clinical work) and blocks ONLY on explicit excess; **the workstation
never writes quota values** (only the approximate usage bump, `approximate: true` —
server recompute is exact); detection must keep supporting BOTH layouts until all
pre-ADR-0005 consultations are closed. Laravel-side counterpart lives in
`consult-form/laravel-back` (P1-slice: `physician_storage`, `item_permissions.grantee_address`
app-level sharing — in hub mode there are NO per-physician Drive ACLs; the Laravel grants
are the authority). Tests: 137 green workstation; 27 new Laravel tests green.

## 9. Internal/external consultations + aipacs_web pairing + Assign popup (2026-06-10, ADR-0006)

The local Laravel backend (`http://localhost:8080/consult-form`, Sanctum API at
`/api/v1`) owns **consultant profiles** and the **consultation registry**:
*internal* consultations are registry records only (NO image upload, no Drive);
*external* ones run the existing Drive package flow plus a best-effort registry
record carrying the `drive_folder_id`.

| Area | Change |
|---|---|
| `modules/Identity/providers/aipacs_web.py` | NEW provider `aipacs_web` (pair via `POST /auth/workstation/pair` with email+password or pairing_code; token → secure_store; handle = account email) + `AipacsWebClient` (`me/consultants/create_consultation/list_consultations/update_consultation`, thread-guarded, clean `AipacsWebError`s) + `get_aipacs_web_client()` convenience. Config: `config/identity/aipacs_web.json` `{base_url, enabled}`, env `AIPACS_WEB_BASE_URL`. Registered in `registry.py`; `Capability.CONSULTATION` added; `IdentityService.connect_with_credentials()` added. |
| `modules/Identity/ui/aipacs_web_dialog.py` | NEW sign-in dialog (email+password OR pairing code, QThread worker). |
| `modules/cloud_consultation/ui/account_popup.py` | "Consultation system" section (sign-in / handle + Disconnect), guarded by `aipacs_web_configured()` so the popup renders unchanged otherwise. |
| `modules/Identity/providers/google/oauth_flow.py` | Best-effort embedded-browser OAuth: when `is_module_enabled("web_browser")` AND the module imports AND a QApplication exists, the consent URL opens in `WebBrowserWidget` (loopback redirect server unchanged, split run_local_server pattern); ANY failure falls back silently to the system browser. |
| `modules/education/online_consultation/assign_core.py` | NEW Qt-free routing/payload/merge logic (internal default for unknown consultant types — no images leave by default; `patient_ref = "<PatientID> <name>"`; registry merge dedupes external rows against Drive rows by folder id; per-status actions accept/decline/answer/close). |
| `modules/education/online_consultation/assign_dialog.py` | NEW `ConsultationAssignDialog` — consultant list (badge/specialty/availability), note, Send. Internal → registry POST; external → existing `ConsultationComposeDialog` preselected to the row's studies with assignee prefilled, then best-effort registry record (never blocks the Drive flow). |
| `PacsClient/.../patient_table_widget.py` | Assign column cell-click → the dialog, wired EXACTLY like the Report column popup (cell-widget `mousePressEvent`); gate cached per widget (`_assign_consultation_enabled`); **click-debounce logic untouched**. |
| `consultation_page.py` | NEW "Consultants" sub-tab + "Assign consultation…" header action; Inbox/Sent additionally show registry rows (tagged "Internal — no image upload") fetched on a worker (`_AipacsRegistryWorker`); registry actions PATCH on a worker. Drive rows/statuses/poller untouched. |
| `compose_dialog.py` | Additive: `created_consultation_id` recorded on success (lets the Assign flow look up the Drive folder id). |

Invariants added: the **internal route must never carry Drive fields**; the
post-upload registry record for external consultations is **best-effort only**
(the Drive flow must never block/fail on it); the Assign popup is gated by
`online_consultation_available()`; embedded-browser OAuth must keep the silent
system-browser fallback. Tests: 179 green (same four suites); mirrors 311 pairs.

### 9.1 Local integration verification (2026-06-10, real HTTP)

`tools` script (workspace repo: `D:\work space AI-Pacs company\tools\integration_test_consultation_registry.py`)
ran the REAL `aipacs_web` provider/client against the live local Laravel
(http://localhost:8080/consult-form): **14/14 passed** � pair (both users), /me,
consultant directory, internal lifecycle requested?accepted?answered?closed across two
paired accounts, role guard (requester cannot accept), external registration with
`drive_folder_id`, unpair cleanup. Two contract fixes landed in
`modules/Identity/providers/aipacs_web.py` (keep): the pair endpoint returns **201**
(accept 200/201), and list/object responses unwrap resource-named envelopes
(`consultants`/`consultations`/`consultation`/`profile`) in `_rows`/`_row`.
DB isolation: the script patches `DATABASE_FILE` + clears the real pool (test-pollution
invariant respected). Suites after fixes: 179 green + patient-table guards 8 green.

## 10. ADR-0007 UX restructure — hub + single management destination (2026-06-11)

Presentation-layer-only restructure (owner-approved ADR-0007): the **account popup is
the identity & notification hub**; **Education ▸ Online Consultation is the single
management destination** with six sections; entry points (Assign column, popup buttons)
only *create* and *deep-link*. NO engine/transport/state-machine/poller changes.

| Area | Change |
|---|---|
| `consultation_page.py` | Tab bar is now SIX sections — Directory / My Profile / My Consultations / Requests / Storage & Usage / Shared (`SECTION_IDS`, aliases for legacy names, lazy per-section activation). `show_section(id)` is the deep-link target; page class name + launcher contract unchanged. The pre-ADR-0007 Inbox/Sent action rows moved VERBATIM into the Requests section (same `_row_actions`, registry merge, workers). Notifications: header bell + dialog kept; the PRIMARY list lives in the account popup. |
| `sections_common.py` | NEW — `ConsultationSection` base (lazy first-load on activation, worker bookkeeping, signed-out/error empty states) + `ClientCallWorker` (runs `fn(client)` off the UI thread, `not_signed_in` signal). |
| `dashboard_core.py` | NEW Qt-free logic (the "ux_core"): 5-bucket grouping (Pending / Awaiting response / Awaiting review / Answered / Closed) for Drive rows (frozen statuses READ only, direction-aware) + registry rows (dedupe via `assign_core.registry_rows_to_display`); directory filtering (`filter_consultants` query/kind/availability/specialty, `consultant_specialties`); storage helpers (`storage_summary` warn ≥80 % / alert ≥95 %, `format_bytes`, `storage_cache_fresh` 5-min TTL). |
| `sections_directory.py` | Directory: search (client-side) + type + specialty (populated from rows) + availability filters, profile cards/dialog, "Request consultation…" → existing Assign flow with the consultant preselected. |
| `sections_profile.py` | My Profile: GET/PUT `/me/profile` on workers; address/type read-only (client strips them); sign-in empty state. |
| `sections_storage.py` | Storage & Usage: quota cards (`/me/storage`), category bars + largest folders + cleanup candidates with closed/stale badges (`/me/storage/breakdown`); READ-ONLY (Drive links only, no delete in v1); result reused on tab re-entry within 5 min (`storage_cache_fresh`). |
| `sections_shared.py` | Shared Content: shared-by-me (grants) + shared-with-me (capability) from `/education/shared`; read-only. |
| `modules/Identity/providers/aipacs_web.py` | Additive client methods: `my_profile` (envelope preserved — `profile` may be null), `update_my_profile` (strips server-controlled `address`/`type`), `my_storage`, `storage_breakdown` (marker-key tolerant unwrap), `shared_content` (normalizes both lists), `consultants(type=, specialty=, search=)` — type/specialty go to the server as query params, search filters client-side; no args = byte-identical legacy call. |
| `modules/cloud_consultation/ui/account_popup.py` | The hub: server login header (untouched), AI-PACS Consultation + Google status cards, **Notifications** (top-5 unread, mark-read, deep link), **storage line** (QApplication-cached, worker-refreshed, TTL 300 s ≥ the 60 s throttle; warning style ≥80 %, alert style ≥95 %), Inbox/Sent count chips + "New consultation" + "Open Education ▸ Consultation" deep links. No inline management. |
| `assign_dialog.py` | Entry-point funnel: after a successful internal/external send, a one-line success box offers "Open Education ▸ Consultation" (launcher → Requests); no further inline UI. External best-effort registry record worker is parented to the QApplication so dialog accept() can't kill it. |
| `launcher.py` / `education_module_redesigned.py` | `open_online_consultation(section=…)` / `show_online_consultation(section=…)` deep-link into a specific section (legacy no-arg calls still work). |

**Invariants (kept + new):** the triple gate `online_consultation_available()` is never
bypassed (page constructs safely with nothing configured; sections show sign-in/empty
states); frozen Drive statuses are read-only inputs to the bucket mapping — display
labels/buckets are never persisted; ALL network (registry, profile, storage, shared,
Google) stays on QThread workers — the dashboard/Requests read the local
`consultation_db` synchronously exactly as before; poller singleton, dedupe logic,
de-identification, and the AI-PACS server login are untouched. The My Consultations
dashboard is read-only ("Open in Requests" affordance only); Storage offers no delete
(Laravel stays the storage authority, quota gate still fails open per ADR-0005).

Tests: `tests/code/education_online_consultation/test_dashboard_core.py` (buckets,
dedupe, filters, storage thresholds + TTL) + ADR-0007 client-method tests in
`tests/code/identity/test_aipacs_web_provider.py`. Suites: **214 green** (the four
consultation suites) + patient-table guards 8 green; mirrors **317 pairs OK**.

## 11. ADR-0008 identity bridge — transient Gmail attestation (2026-06-11)

The workstation side of the ADR-0008 identity bridge (server user ↔ attested
Gmail ↔ admin-defined consultation profile). **Gmail never replaces the server
login.** The user, already logged into the workstation, enters their Gmail once;
a TRANSIENT Google OAuth proves ownership; the resulting **ID token** goes to
the local Laravel backend (`POST /api/v1/auth/workstation/link-google`), which
verifies it and returns a Sanctum token — stored exactly like the ADR-0006
pairing token.

**Flow:** Gmail field → `attest_gmail(gmail)` (scopes `openid` +
`userinfo.email` ONLY — never Drive; `prompt='select_account'`; same
embedded-web_browser-or-system-browser opening as the Google provider via the
new `auth_url_kwargs`/`open_url_cb` parameters on
`oauth_flow.run_installed_app_flow`) → ID-token payload decoded LOCALLY
(base64, no verification — the server verifies signature/audience/expiry) to
sanity-check `email`/`sub` → `link_google(...)` → 201 `{token, user, link,
profile}` → `AipacsWebIdentityProvider.connect_via_google_attestation` builds
the same identity shape as `connect()` with `extra={"base_url", "link":
{gmail_email, status, consultation_profile_id, profile_name, …}}` and stores
ONLY the Sanctum token in secure_store.

**Invariants (keep):**
- **No personal Google credential is ever stored.** The attestation OAuth
  credentials are discarded after the ID token is extracted — no
  `save_secret("google", …)`, no Google identity row. The standing Google
  identity remains the shared hub Drive account (ADR-0004). The guard test
  asserts zero secure_store writes during `attest_gmail`.
- **Attestation scopes are frozen** at `["openid",
  "https://www.googleapis.com/auth/userinfo.email"]` — adding Drive here would
  silently turn the attestation into a personal-Drive grant.
- An ID-token `email` ≠ entered Gmail (case-insensitive) raises a clean
  account-mismatch `AipacsWebError`; the server's 422 messages
  (admin-not-registered / id_token verification) surface verbatim in the
  dialog.
- **Address fallback chain (`feature_flags.consultation_address`)** is now
  env → flag file → (NEW) `linked_consultation_address(aipacs_user)` — the
  linked identity's attested `link.gmail_email`, else its handle — → caller
  default (Google handle). The Identity import is lazy (inside the helper) and
  never raises; `autostart.py` passes `aipacs_user=` so a linked physician
  routes by their Gmail with no env/flag-file edit. Pre-ADR-0008 callers
  (no `aipacs_user`) behave byte-identically.
- The legacy email+password / pairing-code exchange keeps working — it lives
  under the dialog's collapsed "Advanced (admin) sign-in" section and its
  tests are unchanged.
- ALL of it stays off the UI thread (`_AttestWorker` QThread; `attest_gmail`/
  `link_google` keep `assert_off_gui_thread`).

**Files:** `modules/Identity/providers/aipacs_web.py` (`ATTEST_SCOPES`,
`_decode_id_token_payload`, `attest_gmail`, `link_google`,
`connect_via_google_attestation`),
`modules/Identity/providers/google/oauth_flow.py` (additive `auth_url_kwargs` +
`open_url_cb`), `modules/Identity/identity_service.py`
(`connect_aipacs_web_via_google`), `modules/Identity/ui/aipacs_web_dialog.py`
(Google-first dialog), `modules/cloud_consultation/feature_flags.py`
(`linked_consultation_address`, extended `consultation_address`),
`modules/cloud_consultation/notifications/autostart.py` (wiring),
`modules/cloud_consultation/ui/account_popup.py` ("Linked: <gmail> (Dr. X)").

Tests: `tests/code/identity/test_gmail_attestation.py` (17) + 3 linked-address
fallback guards in
`tests/code/cloud_consultation/test_hub_mode_and_close_lifecycle.py`.
Suites: **234 green** (the four consultation suites) + patient-table guards
8 green; mirrors **317 pairs OK** (education untouched).

### 11.1 Embedded-browser default + live-bridge findings (2026-06-11)

**Policy (owner):** the internal Web Browser module is the DEFAULT surface for ALL
identity verification/connection flows; the system browser is only the fallback
(module unavailable / headless CLI). Implemented in
`modules/Identity/providers/google/oauth_flow.py` � `run_installed_app_flow`
prefers the embedded browser for Drive connect AND Gmail attestation; new flows
must use it or `open_verification_url()` (never `webbrowser.open` directly).

Live-bridge validation findings (both fixed): (1) the `identity_links` migration
existed but was not applied to the live local DB � `php artisan migrate` is part
of every slice rollout, tests on :memory: do not cover it; (2) `pair_workstation`
and `link_google` did not send `Accept: application/json` � Laravel turned
validation errors into 302?HTML and the client reported "Unexpected response";
both now send the header (keep it on any new endpoint helper). Google attestation
itself verified live: the user's real Gmail was attested (email+subject extracted,
credentials discarded). The final in-app link runs in the GUI session via the
embedded browser. Suites: 234 green after fixes.

### 11.2 Unified login (owner directive, 2026-06-11)

ONE Google sign-in is the entire user-facing Consultation login: the dialog's
single "Sign in with Google" button runs the transient attestation
(`attest_gmail` — the `gmail` argument is now OPTIONAL/empty in the primary
path, so there is NO Gmail pre-typing and no entered-vs-signed-in comparison);
Laravel authorizes the VERIFIED email against the consultation database. A
not-registered/not-accepting profile returns the EXACT 422 message
"Your email is not registered for the Consultation module. Please contact
AI-PACS.com to activate/register your Consultation access." which the dialog
shows verbatim in a QMessageBox. The admin email+password / pairing-code path
is demoted to the collapsed "Administrator sign-in options…" fallback. The
account popup presents the Consultation section as the primary identity action
("Sign in with Google…" / "Consultation: <gmail> (Dr. X)"); the Google/Drive
hub section is relabeled "Cloud storage (hub)" + "Set up hub storage…"
(labels/ordering only — connect engine, transport, poller all unchanged;
embedded-browser default stays).

### 11.3 Account-dropdown redesign + Manage Account + derived modes (owner directive, 2026-06-11)

**Dropdown shape** (`modules/cloud_consultation/ui/account_popup.py`), top to bottom:

1. Workstation account header (unchanged AI-PACS server identity card).
2. **Connected Identity** (only when `aipacs_web_configured()`):
   - *not connected* → a single **"Connect Google Account"** button (the existing
     one-button `AipacsWebSignInDialog` flow);
   - *connected* → identity card: profile display name (`extra.link.profile_name`,
     fallback handle), the gmail, "Status: Connected ✓ (verified)", the derived
     consultation status line, and a small "Manage" affordance only (disconnect
     moved to Manage Account).
3. **Manage Account** button → `ManageAccountDialog`.
4. **Notifications** (when `cloud_consultation_enabled()`): top-5 unread +
   mark-read + the Education ▸ Requests deep link — unchanged. The storage line
   renders ONLY as a compact warning row at ≥80 % (warn) / ≥95 % (alert); normal
   usage no longer shows in the dropdown.
5. Footer hint. No Sign Out row: the popup never had a workstation sign-out, and
   the directive says omit rather than invent one.

**INVARIANT: the dropdown carries exactly ONE identity action** (the Connect
button or the connected-identity card). The hub section was REMOVED from the
dropdown entirely — no "Cloud storage (hub)" block, no "Set up hub storage…"
there, and the Consultations stats / "New consultation" block was retired
(creation lives in the Assign column + Education; deep links remain).

**ManageAccountDialog** (`modules/cloud_consultation/ui/manage_account_dialog.py`):
Identity (gmail + profile name + Disconnect — its new home), Hub Configuration
("Current Hub: AI-PACS Cloud Hub (Google Drive)", status or "Not configured —
managed by your AI-PACS representative during installation", relocated
"Set up hub storage…" / "Disconnect hub" actions, note "Configured by AI-PACS
during installation/activation."), Storage Usage (cached `/me/storage` summary +
bar + "Open storage dashboard" → Education ▸ Storage), Profile Settings
("Edit my consultant profile" → Education ▸ My Profile). Worker-loaded
(`_ConnectWorker`/`_StorageWorker` shared with the popup), guarded, renders fine
with nothing configured. Presentation + derived state only — the Identity
engine, transport, poller and state machine are untouched.

**Derived modes** (`modules/cloud_consultation/ui/derived_status.py`, Qt-free):
`consultation_capabilities(aipacs_user)` → `identity_linked` (aipacs_web
identity exists), `consultation_active` (= linked; the Laravel link implies an
authorized profile), `hub_available` (a Google/Drive identity exists),
`internal_enabled` = `online_consultation_available()` AND linked (**license +
identity only — NO hub requirement**), `external_enabled` = internal AND hub,
plus `status_text` ("Consultation: Active" / "Consultation: Active (internal
only — no cloud hub)" / "Consultation: Not enabled"). All probes lazy + guarded;
never raises; overrides injectable for tests.

**External gate when no hub:** `assign_dialog.py` disables external consultant
rows (gray, tooltip) and `sections_directory.py` grays external cards with the
reason; the send path goes through `assign_core.ensure_route_allowed(consultant,
external_enabled)` which raises `ValueError(EXTERNAL_DISABLED_REASON)` =
"External consultation requires the AI-PACS Cloud Hub (not configured)".
Internal consultants stay fully functional; with the hub available behaviour is
byte-identical to before (the UI capability checks fail OPEN). Guards:
`tests/code/cloud_consultation/test_derived_status.py` + the
`ensure_route_allowed` tests in `test_assign_core.py` (suites: 251 green).

### 11.4 Docked-OAuth surface chain + notification severity tiers (owner directive, 2026-06-11)

**OAuth surface chain** (`modules/Identity/providers/google/oauth_flow.py`): the
consent URL now opens in the **docked Web Browser module tab** — the same
home-page container the Web module button uses — instead of a floating window.
`_open_url_on_gui_thread` runs a three-step fallback chain on the GUI thread:

1. **docked** — `_find_home_panel()` (the education-launcher widget-tree lookup,
   no PacsClient import) → `HomePanelWidget.open_web_browser(show_unavailable_dialog=False)`
   → `web_view.setUrl(consent_url)`, plus a 250 ms `QTimer.singleShot` URL
   re-assert (defeats a deferred home/session load on a freshly created tab);
2. **floating** — the pre-existing standalone `WebBrowserWidget` window, on ANY
   docked failure;
3. **system** — `webbrowser.open`, on ANY floating failure.

The loopback redirect server, PKCE handling, worker-thread wait, and
`open_verification_url()` are unchanged (same chain via the same entry point).
After the loopback hit + token exchange, `_reset_docked_browser_after_auth()`
best-effort navigates the docked tab back to its home page (weakref; guarded;
never required; no-op for floating/system). **Live QA:** the chosen surface is
logged as `[OAUTH_SURFACE] consent URL opened via surface=docked|floating|system`
(and `... docked browser reset to home after auth`). With the web_browser module
unavailable the behaviour is byte-identical to before (chain falls through).

**Notification severity tiers** (`modules/cloud_consultation/notifications/`):
`models.NotificationPriority` (LOW/NORMAL/HIGH/CRITICAL) + `priority_for(kind)`
+ `category_for(kind)` — **derived at render, NO schema change** (every source
maps deterministically from its kind; a future source needing a different tier
adds a kind, which also carries title + category; `notify(priority=...)` exists
as an override hook but a mismatch is advisory-only and logged).

| Kind | Priority | Category chip |
|---|---|---|
| CONSULTATION_ASSIGNED, RESPONSE_RECEIVED | HIGH | Consultation |
| CONSULTATION_UPDATED | NORMAL | Consultation |
| UPLOAD_DONE, DOWNLOAD_DONE | NORMAL | Transfer |
| SYNC_ERROR, UPLOAD_FAILED, AUTH_FAILED, QUOTA_EXCEEDED | CRITICAL | Urgent |
| SYSTEM_INFO, BROWSER_INFO, EDUCATION_INFO | LOW | System/Browser/Education |

`inbox.latest_notifications(limit=4)` feeds the account popup (unread first,
newest first, read fill, archived excluded, rows decorated with
`priority`/`category`); `inbox.clear_all()` → `notifications_db.mark_all_read()`
("cleared" = all unread become read history; new ones appear after). The popup
shows the latest 4 with per-tier styling (CRITICAL = danger border/bold/`●`
badge; HIGH = accent + bold + chip; LOW = muted/smaller) and a **Clear all**
button in the section header (visible only with unread). `unread_count()` and
the consultation-page bell chip are unchanged. CRITICAL wiring is **UI-side
only** (engine/poller untouched): compose/respond/assign failure handlers add a
guarded `inbox.notify(UPLOAD_FAILED | AUTH_FAILED-when-"sign in")`; the popup's
≥95 % storage alert fires a one-shot QUOTA_EXCEEDED deduped per usage-pct via a
QApplication property. Guards: `tests/code/cloud_consultation/test_notifications.py`
(tier-table completeness, clear-all semantics, limit-4 ordering — suites: 256 green).

### 11.5 Assignment workflow v2 — tabbed popup, multi-assign, metadata, pill badge, source page (2026-06-12)

**Tabbed Assign popup** (`assign_dialog.py` rework; logic stays Qt-free in
`assign_core.py`): the popup is now a QTabWidget — **Internal | External**.
The Internal tab lists center physicians (`consultants(type=internal)` split
client-side by `consultant_kind`) with a search box and **multi-select
checkboxes** ("one or more"), a shared note, and per-row "View profile";
Submit posts ONE registry record PER selected physician on a worker loop
(`_MultiCreateRegistryWorker` — sequential POSTs, a failed send never aborts
the loop; partial failures keep the dialog open and list the failed
addresses). The External tab is single-select (radio), shows availability, a
**quota status line** (worker `my_storage` → "Cloud storage: X used of Y
(N%)"), a note, and runs the EXISTING Drive compose flow + best-effort
registry record. The External tab is disabled with
`EXTERNAL_DISABLED_REASON` when `external_enabled` is False (same derived hub
gate); `ensure_route_allowed` still guards the send path. **Quota note (by
design):** the package size is NOT computable before the export stages
files, so the popup never pre-blocks on storage — the quota line is
informational and the compose-path gate (`physician_store.check_quota`,
ADR-0005, fails open) remains the enforcement point at upload.

**Creation-only metadata:** `POST /consultations` (backend extension) accepts
optional `center_id`, `patient_id`, `study_date`, `modality` — sent only when
non-empty (`AipacsWebClient.create_consultation` kwargs;
`assign_core.assignment_metadata` + `metadata=` on both payload builders, so
metadata-less calls stay byte-identical to pre-v2). `patient_id` /
`study_date` / `modality` come from the clicked patient row: the Assign-column
cell click (`patient_table_widget.py::_on_assign_clicked`) now forwards the
row's `date_text` + `modality` into the dialog constructor — purely additive;
**the single/double-click row-selection debounce and the guarded open paths
are untouched.** `center_id` comes from the new optional `center_id` key in
`config/cloud_consultation/cloud_consultation.json`
(`feature_flags.center_id()`, env `AIPACS_CONSULTATION_CENTER_ID` wins,
defaults ""); the config family version bumped to 2.

**Shared ProfileDialog:** `profile_dialog.py::ConsultantProfileDialog` is the
ONE read-only profile dialog (name/specialty/expertise/interests/resume/
description/availability/address). The Directory's dialog is now a thin
subclass wiring `request_callback` to the assign flow; the Assign popup opens
it without the request button.

**Account-pill badge** (`account_hook.py` + Qt-free
`ui/badge_core.py::count_pending_received(rows, notifications)`): a small red
numeric badge on the user pill = registry INBOX rows in
pending/requested/accepted + unread HIGH/CRITICAL notifications (the
2026-06-11 tier table); `badge_text` caps at "9+". Computed on a throttled
QThread worker with a QApplication-level cache (≥60 s TTL, 90 s re-check
timer — the popup's storage-cache pattern); renders NOTHING when zero or not
signed in; the badge label is `WA_TransparentForMouseEvents` so the pill's
click → popup behaviour is byte-identical.

**Requests pane:** the incoming tab is titled **"Received / Assigned to Me"**
(`INCOMING_TAB_TITLE`). Internal registry rows render a patient-metadata line
(`assign_core.patient_metadata_summary` → "ID … · modality · date", empty for
pre-v2 rows) and a **"Patient details"** action →
`patient_details_dialog.py::PatientDetailsDialog` (requester, patient_id,
study_uid, study_date, modality, note, status + "Copy patient ID" + the hint
"Open this patient from the main patient list"). **Deliberately NOT wired
into the guarded patient-open machinery** (`_hp_patient_open.py` /
`_hp_search.py` cross-patient isolation) — the physician opens the patient
through the normal guard-protected search flow. External rows keep
Download & review / Import to library unchanged.

**Consultation source page — module-tab decision (rationale):** the owner's
"Consultation server" is implemented as
`source_page.py::ConsultationSourcePage` ("AI-PACS Consultation"), opened as a
HOME-PANEL MODULE TAB via `HomePanelWidget.open_consultation_source()`
(`_hp_modules.py`, the EXACT `open_web_browser` /
`activate_or_create_module_tab` pattern, flag `is_consultation_source_tab`,
new `CustomTabManager.add_consultation_source_tab` mirroring the web-browser
adder) — **NOT as a PACS server entry: the server-selection/socket pipeline
is untouched by design** (a Drive/registry "server" in that list would feed
the DICOM socket clients a non-socket endpoint and violate the
`socket_config` port invariant). Sections (all worker-loaded, reusing
existing pieces, safe when unsigned/unconfigured): **My cloud folder**
(read-only transport listing of `AI-PACS Consultations/<address>/` — name /
file count / size, bounded at 50 folders, nothing created), **Assigned to me**
(registry inbox merged with Drive-detected incoming rows; reuses the
`consultation_page` `_DownloadWorker`/`_ImportWorker`, not forks), **Internal
records** (internal registry rows, both boxes, with Patient details). Entry
points: "Open Consultation source" in the Education ▸ Consultation header,
the account-popup deep link under Manage Account, and
`launcher.open_consultation_source()`.

Tests: `test_assign_core.py` (+12: metadata payloads byte-identical /
carried, multi-assign one-per-physician + dedupe + raises, summary line),
`test_aipacs_web_provider.py` (+2: metadata kwargs sent / omitted),
`tests/code/cloud_consultation/test_pill_badge.py` (16: count contract +
badge text + `center_id` flag). Suites: **284 green** (four consultation
suites; baseline 256 + 28 new) + patient-table guards **12 green** + builder/
runtime **49 green**; mirrors **332 pairs OK** (new files `--add`-ed:
`profile_dialog.py`, `patient_details_dialog.py`, `source_page.py`;
`badge_core.py` has no payload mirror — `modules/cloud_consultation` ships
whole). The staged engine config template was refreshed for the `center_id`
key (stage parity green); the next release build re-stages it normally.

### 11.6 OAuth surface crash (0x8001010d) — system browser is the safe default (2026-06-12)

**Symptom (captured live):** the app *closes* (hard process kill, not a Python
exception) during the Consultation Google sign-in when the consent flow runs in
the DOCKED embedded QtWebEngine browser. `user_data/logs/native_fault.log`:
`Windows fatal exception: code 0x8001010d`
(= `RPC_E_CANTCALLOUT_ININPUTSYNCCALL`) on the Qt GUI event-loop thread
(`main.py notify` → qasync `run_forever`). `app.log` shows
`[OAUTH_SURFACE] surface=docked` → `docked browser reset to home after auth` →
`[OAUTH_SURFACE] surface=docked` (a SECOND attempt) → crash.

**Root cause.** `0x8001010d` is raised when a COM call is made while Windows is
dispatching an **input-synchronous** message. QtWebEngine performs COM work
(GPU/clipboard/accessibility) during the consent page lifecycle; when that
collides with an input-sync dispatch on the GUI thread the process dies. The
desktop **loopback** OAuth (`InstalledAppFlow`) is *designed for the system
browser* — routing it through the embedded surface (the 2026-06-11 "embedded is
the default for all verification flows" directive) introduced the hazard. The
second `surface=docked` in the log is a user re-click after the first attempt
surfaced an error ("could not connect to the identity"); the flow open is
single-shot per attempt (the embedded path opens the URL exactly once —
`_run_flow_embedded` makes ONE `(open_url or _open_url_on_gui_thread)(auth_url)`
call and does NOT call `flow.run_local_server`, so there is no library
double-open), but a stale deferred reset/re-assert from a prior attempt could
still touch the docked browser a new attempt was using.

**Fix (additive; the only behavioural change is the surface default flip).**
`modules/Identity/providers/google/oauth_flow.py`:
- **System browser is now the DEFAULT for the loopback OAuth.**
  `run_installed_app_flow` uses the embedded QtWebEngine surface **only** when
  the operator explicitly opts in via env `AIPACS_OAUTH_EMBEDDED=1`
  (`_oauth_embedded_opt_in()`, OFF by default) AND the embedded surface is
  actually usable; otherwise it runs `flow.run_local_server(open_browser=True)`
  (system browser) exactly as before the 2026-06-11 change. This removes the
  COM-in-input-sync hazard from the default clinical path — the process can no
  longer COM-crash on the GUI thread during sign-in.
- An **explicit caller-supplied `open_url_cb`** is still honoured verbatim (the
  caller is choosing the surface on purpose).
- `open_verification_url()` (plain, non-OAuth navigation — no loopback) still
  MAY use the embedded Web Browser module: a simple page open has no
  COM-in-input-sync hazard, so in-app navigation is unchanged.
- **Race hardening for the opt-in embedded path:** a `_DOCKED_FLOW_GEN`
  generation counter is bumped on every docked open; the deferred 250 ms URL
  re-assert and the post-auth `_reset_docked_browser_after_auth` both no-op when
  a newer flow has taken over the docked browser, so a stale callback can never
  navigate the surface a newer attempt is using.

**Connect-button wiring (verified correct, no change needed).** The account
popup's "Connect Google Account" (`account_popup.py::_sign_in_aipacs_web`) opens
`AipacsWebSignInDialog`, whose "Sign in with Google" runs the **identity
attestation/link** path (`_AttestWorker` →
`IdentityService.connect_aipacs_web_via_google` →
`provider.connect_via_google_attestation` → `attest_gmail` + `link_google`) — it
is NOT wired to the hub Drive connect (`provider.connect("google")`, used only by
`ManageAccountDialog`). The earlier 2026-06-11 link-google fixes (Accept header,
200/201, envelope unwrap, empty-Gmail attestation) remain in place; the "logged
in but no identity connection" the user saw is the expected error surface when
`link_google` returns 422 (e.g. email not registered) or when the crash aborted
the attempt mid-flight — not a misrouted button.

**Guards.** `tests/code/identity/test_oauth_surface_policy.py` and
`tests/code/identity/test_connect_button_routing.py` (the connect button routes
to the attestation/link path, never the Drive connect).
`modules/Identity` is not plugin-mirrored, so no mirror sync is required.

#### Resolution (owner directive 2026-06-12) — embedded is the DEFAULT again, crash-hardened

The system-browser default above was an **over-correction**: the owner requires
the Google sign-in / consent to open inside OUR embedded Web Browser module
(the docked QtWebEngine tab), NOT the external system browser. The genuine
0x8001010d trigger was the **double-open + reset-race** interacting with
QtWebEngine during input-synchronous dispatch — that is now fixed directly, so
the embedded surface is safe to be the default.

**Surface-resolution logic now** (`run_installed_app_flow` →
`_resolve_oauth_surface()`):

| Condition | Surface | `[OAUTH_SURFACE]` reason |
|---|---|---|
| explicit `open_url_cb` supplied | embedded (caller's opener) | `explicit-open-url-cb` |
| kill-switch ON (env `AIPACS_OAUTH_EMBEDDED` ∈ {0,off,false,no,disabled} — wins — OR config `oauth_embedded: false`) | system | `kill-switch` |
| embedded not usable (web_browser module off / no live QApplication / headless) | system | `not-usable` |
| otherwise (default; env truthy or config `oauth_embedded:true` also land here) | embedded docked tab | `default-embedded` |
| embedded attempt raised a Python-level error | system (auto-fallback) | `fallback-after-failure` |

Env wins over config. The kill-switch only forces system on FALSEY values; a
truthy env value re-asserts embedded even when config says `oauth_embedded:false`.

**Crash-hardening kept + strengthened (so embedded cannot re-crash):**
- **Single open per flow** — the embedded path makes ONE
  `(open_url or _open_url_on_gui_thread)(auth_url)` call and never calls
  `flow.run_local_server(open_browser=…)`, so the library cannot double-open.
- **Queued open** — `_open_url_on_gui_thread` marshals the open onto the GUI
  thread via `_call_on_gui_thread`/`postEvent`; the QtWebEngine view is never
  created/navigated synchronously inside the input-sync click dispatch.
- **Clean-turn navigate (NEW)** — inside `_open_docked_browser` the actual
  `web_view.setUrl(...)` is deferred one more clean event-loop turn with
  `QTimer.singleShot(0, …)`, so the COM-triggering navigate does not run inside
  the `postEvent` handler that may itself be mid-input-dispatch. This is the
  standard `RPC_E_CANTCALLOUT_ININPUTSYNCCALL` mitigation. Guarded +
  generation-checked; never raises.
- **Generation guard** — `_DOCKED_FLOW_GEN` is bumped on every docked open; the
  deferred clean-turn navigate, the 250 ms re-assert, and the post-auth
  `_reset_docked_browser_after_auth` all no-op when a newer flow has taken over
  the docked browser.
- **System fallback always exists** — not-usable / kill-switch / any Python-level
  embedded failure routes to `flow.run_local_server(open_browser=True)`.

A module-level comment in `oauth_flow.py` documents the contract: synchronous
COM-triggering calls (QtWebEngine view creation/navigation, clipboard, file
dialogs, modal loops) must NEVER run inside the input-sync click dispatch — only
queued on the GUI thread (and the navigate deferred one more clean turn).

**Config:** `config/cloud_consultation/cloud_consultation.json` does NOT contain
`oauth_embedded` (key absent = default embedded — the active behaviour on this
machine). Set `oauth_embedded: false` (or env `AIPACS_OAUTH_EMBEDDED=0`) to force
the system browser.

**Updated guards.** `tests/code/identity/test_oauth_surface_policy.py` now pins:
default (no flag) → embedded WHEN usable; env/config kill-switch → system; env
truthy overrides config-off → embedded; not-usable → system; embedded
Python-failure → system fallback; explicit `open_url_cb` always honoured (even
with the kill-switch on); consent URL opened exactly once.

#### Sign-in dialog is MODELESS (live bug 2026-06-12)

`AipacsWebSignInDialog` is now constructed **non-modal** (`setModal(False)` +
`Qt.NonModal`) and every caller opens it via the modeless launcher
`open_signin_dialog(service, parent, on_success=…, on_finished=…)` —
**never `dlg.exec()`**. A modal `exec()` grabbed input application-wide while
the embedded surface renders the Google consent page in the **docked Web
Browser module** (the same top-level window), so the user could not click their
Google account behind the dialog — the live "it freezes / I can't click the web
browser" report. The launcher shows the dialog with `show()`, keeps a strong
reference on the QApplication (`_aipacs_live_signin_dialog`, dropped on
`finished`) so it isn't GC'd, repositions it to the parent window's top-right so
it does not cover the account chooser, and delivers the result via the
`on_success(identity)` / `on_finished(accepted)` callbacks instead of `exec()`'s
return value. The dialog's copy is **surface-aware** (reuses
`_resolve_oauth_surface()`): for the embedded/docked surface it tells the user to
complete consent in the AI-PACS browser tab and return — the window updates
automatically; the system-browser fallback keeps the generic wording. Cancel /
close `reject()`s and **abandons** the running OAuth/pairing worker
(`_abandon_workers()` disconnects its `done`/`failed` signals; the loopback
thread can't be hard-killed so it is orphaned to be reaped) — closing never
crashes and never leaves a modal grab; on success the dialog still auto-closes.
The embedded-default + crash-hardening contract (§11.6) is unchanged. Callers:
`account_popup._sign_in_aipacs_web`, `manage_account_dialog._connect_identity`,
`consultation_page.OnlineConsultationPage._sign_in_aipacs_web`,
`assign_dialog.ConsultationAssignDialog._sign_in`. Guard:
`tests/code/identity/test_connect_button_routing.py` (dialog constructed
non-modal; launcher uses `show()` not `exec()`; every caller routes through
`open_signin_dialog`). `modules/education` callers are plugin-mirrored — run
`sync_plugin_mirrors.py` + `verify_plugin_mirrors.py` after editing them.

## 12. Install-time staleness: mechanism + migration (2026-06-11)

**Symptom:** Education ▸ Online Consultation present in source runs, MISSING in the
installed (frozen) build — even a build produced AFTER the consultation work
(verified on the 3.2.7 install of 2026-06-11: `D:\AIPacs\engine` contained all six
consultation-page files and the staged `consultation` package, yet the tab was gone).

**Three independent mechanisms (all fixed):**

1. **Seeder never copied config SUBDIRECTORIES.** `aipacs_runtime.seed_user_config_defaults`
   iterated only top-level FILES of the bundled `config/`, so
   `config/identity/identity.json`, `config/cloud_consultation/cloud_consultation.json`,
   `config/identity/aipacs_web.json` (and `google_oauth.json`) were NEVER seeded into the
   roaming root (`%APPDATA%\AIPacs\config`). Both feature flags default OFF → triple gate
   fails on gates 1+2 in EVERY frozen install, fresh or upgraded.
   **Fix:** `_seed_config_subdirectories()` (create-if-missing recursion; skips
   `secrets/`, `.gitignore`) + **versioned key-level migration**
   `migrate_user_config_defaults()` driven by `CONFIG_FAMILY_VERSIONS`
   (`config_migrations.json` in the roaming root records applied versions; logs
   `[CONFIG_MIGRATE] file=… added_keys=… version a→b`). Key-level merge ADDS missing
   default keys (e.g. `hub_mode`) and NEVER overwrites a user value — an explicit
   `"enabled": false` stays false. Idempotent, memoized per process, guarded
   (never raises into startup), dev/source runs untouched (`is_frozen()` gate).
   To push a new default key to existing installs: add it to the bundled template AND
   bump that family's version in `CONFIG_FAMILY_VERSIONS`.

2. **Installer profile writer predated the catalog.** `AIPacs_Setup.iss
   WriteInstallationProfile()` had the `optional\consultation` component (Files/Components,
   2026-06-10) but its `modules`/`module_packages` JSON still listed only the OLD ids — so
   selecting Online Consultation in setup copied the package but never enabled the module
   (gate 3, `is_module_enabled("consultation")`, stayed false).
   **Fix:** the .iss now writes `consultation` (selection-driven), plus the basic-tier
   `identity` and `offline_cloud_server` entries, in both maps and in the setup summary.

3. **Old runtime profiles lacked the new ids on disk.** The in-memory merge
   (`configured_module_map`) already falls back to catalog defaults, but the persisted
   `runtime_profile.json` is what Settings/store/support read.
   **Fix:** `sync_runtime_profile_with_catalog()` (called at the top of
   `bootstrap_installer_selected_module_packages`, frozen only) materializes missing
   catalog ids with their defaults via an **empty** `save_runtime_profile({})` patch —
   deliberately empty so it cannot override installer state such as a pending
   `selected_for_install`. Logs `[MODULE_REGISTRY_SYNC]`. It does NOT auto-enable
   optional modules — the commercial gate stays; the fix is visibility only.

**Related (no code change):** already-installed `bundled_unlock` runtime packages in
`%LOCALAPPDATA%\AIPacs\modules_runtime` are never version-refreshed by the bootstrap
(`if record["installed"]: continue`) — observed: echomind 2.4.5 of 2026-04-26 next to the
staged 3.2.7. Harmless for behavior because optional payload paths are APPENDED after the
engine (R24: the fresh frozen `engine/modules/<X>` always wins for module names it ships),
but the stale runtime copy remains on disk.

**Rebuild requirement (operator):** the installer/stage must be rebuilt AFTER any
plugin-mirror sync (`tools/dev/sync_plugin_mirrors.py`) — the stage snapshot, not the
source tree, is what ships. The 2026-06-11 17:47 installer was correct because it was
built after the mirrors; the missing tab was config/profile staleness, not stale code.

Tests: `tests/code/runtime/test_config_migration.py` (10) — key-merge adds/preserves/
idempotency/version record, subdir seeding, frozen seed end-to-end, profile sync
(new ids, idempotent, no auto-enable). Suites after the change: runtime+module_system+
builder 49 green; the four consultation suites 234 green.

## 13. Prevention system — release-parity guards (2026-06-11)

§12's three mechanisms are now guarded by four ADDITIVE layers so the
"works in source, missing in installed build" class fails a test run or the
build itself, never a customer install:

1. **Repo-level parity tests** — `tests/code/builder/test_release_parity_guards.py`:
   * **A1** every `MODULE_CATALOG` id appears in BOTH JSON writers
     (`modules` + `module_packages`) of the Pascal `WriteInstallationProfile()`
     in `builder/installer/AIPacs_Setup.iss` (would have caught mechanism #2;
     the failure message says exactly what to add and where).
   * **A2** config seeding coverage: every `config/` template is seed-reachable
     (functionally verified by running `_seed_config_subdirectories` against a
     temp root) or on the documented exclude list
     (`builder/release_gate.py::CONFIG_TEMPLATE_EXCLUDES` — currently only
     `installation_profile.json`, installer-owned); every `CONFIG_FAMILY_VERSIONS`
     family exists in `config/`; the three feature-flag files
     (`identity/identity.json`, `cloud_consultation/cloud_consultation.json`,
     `identity/aipacs_web.json`) are version-managed; `identity/google_oauth.json`
     ships.
   * **A3** plugin-mirror freshness (`tools/dev/verify_plugin_mirrors.py` logic)
     fails the TEST run on drift, plus an education file-SET parity check that
     catches a NEW canonical file never synced (invisible to the hash check,
     which only walks payload→canonical).
   * **B** unit tests for the release gate; the frozen-PYZ probe runs against the
     current `builder/output/stage` and skips cleanly when no stage exists.

2. **Build-time release gate** — `builder/release_gate.py`, wired into
   `builder/build_release.py` (PRE-BUILD: mirror freshness before PyInstaller;
   POST-STAGE: before ISCC). Post-stage checks: the staged `AIPacs.exe`'s
   embedded PYZ carries the CURRENT `aipacs_runtime` (catalog ids == source ids
   via an exec probe of the frozen bytecode, generalized from the 2026-06-11
   `verify_frozen_runtime.py`; config-migration sentinels present), every
   shippable `config/` template is byte-identical under
   `stage/core/engine/config` (and no `secrets/` file leaked), every optional
   catalog id is staged under `stage/plugin_packages` (advanced_mpr respected
   as conditional via the feed), education payload file-set parity. Prints
   `RELEASE_GATE: PASS/FAIL [checks]`; non-zero exit fails the build. Escape
   hatch `--skip-release-gate` is EMERGENCIES ONLY. Stand-alone:
   `python builder/release_gate.py [--pre-build|--stage-check]`. Fast by design
   (hashes only config templates + `.py` payload files).

3. **Install doctor** — `tools/maintenance/install_doctor.py` (READ-ONLY,
   `--json` for machine output): installed exe/version/mtimes; roaming config vs
   the installed engine's bundled templates (missing seedable files, missing
   keys per `CONFIG_FAMILY_VERSIONS`); `installation_profile`/`runtime_profile`
   module maps vs the INSTALLED engine's catalog (probed from the frozen PYZ,
   source-catalog fallback); ProgramData `module_packages` feed vs app version;
   dormant-stale `modules_runtime` copies (the known §12 residual — reports WARN,
   harmless per R24). PASS/WARN/FAIL table; exit 1 only on FAIL.

4. **Process guardrail** — the "New module / new feature-flag checklist" section
   in the repo `CLAUDE.md` (enforced automatically by A1–A3).

Verified 2026-06-11 against the real outputs: parity suite 11 green
(builder+runtime suites 49 green total), `release_gate` full run PASS on
tonight's stage (14 catalog ids matched via exec probe), `install_doctor` on the
installed `D:\AIPacs` 3.2.7 → 4 PASS + the expected `modules_runtime` WARN.
