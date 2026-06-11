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
