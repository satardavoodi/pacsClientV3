# Education Cloud — Three-Tier Architecture (R2)

**Status:** DESIGN R2 — supersedes the control-plane parts of
`EDUCATION_DRIVE_ARCHITECTURE_2026-06-06.md` (R1). R1's storage format, integrity
model, local layout, and workstation sync mechanics **remain valid**; what changes
is *who controls the cloud*.
**Date:** 2026-06-06 (same day as R1; revised after stakeholder direction)
**Implementation home:** the **Umbrella project** (it has both the workstation repo
and the WordPress/Laravel platform; this repo only contains the workstation).

## 0. What changed from R1 → R2

| Topic | R1 (Drive-only) | **R2 (three-tier)** |
|---|---|---|
| Control plane | `library/index.json` on Drive + app-side role checks | **Laravel backend**: authoritative catalog DB, AuthN/AuthZ, audit |
| Drive credentials | Hub account connected on **every workstation** (`__org__`) | **Server-side only** — refresh token lives encrypted in Laravel; workstations never hold org Drive tokens |
| Permissions | All-or-nothing (shared account), app-side enforcement | **Per-user/role/visibility, enforced server-side** |
| User mapping | `item.json.owner` metadata only | **Website accounts are authoritative**; workstation links via a new `aipacs_web` identity provider |
| Catalog refresh | Poll `index.json` + Drive change cursor | Poll Laravel REST (`updated_since`/ETag); Drive never listed by clients |
| Consultations routing | Google-email assignment + Drive shares | **Assignment by website user id**; server owns Drive I/O → R1 §4.4 `drive.file` cross-account gap disappears entirely |
| Quota | 15 GB consumer concern | **Google Pro, 5 TB** — quota de-risked; website storage stays small (metadata only) |

Drivers: 5 TB hub storage confirmed; the website (WordPress + Laravel) already has
user management, dashboards, and processing; management belongs in one place.

## 1. The three tiers

```
┌─────────────────────────────  PRESENTATION  ─────────────────────────────┐
│ WordPress (site UX): public/member Case-of-the-Day pages, course pages,  │
│ video/textbook library, user dashboards. Renders via Laravel API.        │
├─────────────────────────────  CONTROL PLANE  ────────────────────────────┤
│ Laravel core: users/roles/groups · education catalog DB · permissions &  │
│ visibility · publish approval · consultation lifecycle · audit · the     │
│ ONLY holder of the hub Drive credential (AI.pacs.medical@gmail.com).     │
├─────────────────────────────  DATA PLANE  ───────────────────────────────┤
│ Google Drive (5 TB): item folders with sealed item.json + payload bytes  │
│ (DICOM packages, course bundles, videos, textbooks). No control logic.   │
└──────────────────────────────────────────────────────────────────────────┘
        ▲  REST (catalog/auth/intents, small JSON)        ▲ bulk bytes only
        │                                                 │ (brokered, §5)
┌───────┴──────────────┐  ┌──────────────────────┐  ┌─────┴────────────────┐
│ Workstation client A │  │ Workstation client B │  │ Browser users (WP)   │
│ (Education module)   │  │                      │  │                      │
└──────────────────────┘  └──────────────────────┘  └──────────────────────┘
```

Separation rule: **Drive stores, Laravel decides, WordPress shows, workstations
consume/produce.** No client talks to Drive on its own authority.

## 2. Storage layer (unchanged from R1 where it matters)

- Folder tree, `item_id`-named item folders, sealed `item.json`
  (`aipacs-education-item-v1`, SHA-256 file map, version, owner) — **as R1 §3**.
  The manifest stays *inside the package* so any package is self-describing and
  verifiable even if the catalog DB is rebuilt (disaster recovery = walk Drive).
- `library/index.json` is **dropped** (the Laravel DB replaces it).
- Case-of-Day packages keep the existing local layout (`dicom/`, `metadata.json`,
  `reception.json`, `attachments/`); courses use the (to-be-built) export bundle;
  media = file + sidecar. Anonymize-on-publish for case DICOM stays default-ON
  (reuse `modules/cd_burner/dicom_prepare.py`).

## 3. Identity & user mapping (R2)

- **Website account = the person.** Laravel's users table is authoritative;
  WordPress and Laravel already share the account system (verify bridge in
  Umbrella).
- **Workstation link:** new `AipacsWebIdentityProvider` (`provider="aipacs_web"`) in
  `modules/Identity/providers/` — fits the existing `IdentityProvider` ABC exactly
  like Google did. Connect = website login (or pairing code) → Laravel issues a
  long-lived **API token (Sanctum)** stored in the OS keychain via the existing
  `secure_store`. Link key = current `auth_user` username, as today.
- One person, several hats: the same website account may be linked from several
  workstation logins; the server keys everything by website user id.
- The org Google identity (`__org__` on workstations, R1 §2) is **no longer needed**
  on clients. The existing *personal* Google identity flow stays only if external
  Drive-share consultations are kept (optional, see §7).

## 4. Permissions & visibility (server-side, finally real)

Laravel tables (sketch): `education_items`, `education_item_files`,
`item_permissions` (user/group → view), `roles` (admin, instructor/uploader,
physician, member, guest), `audit_log`.

| Capability | Enforced by |
|---|---|
| Who can upload (per kind) | role `instructor`/`admin` (per-kind grants possible) |
| Who can view | item `visibility`: `public` (WP anonymous) / `members` / `group:<id>` / `private` / `unlisted-link` |
| Who can delete/replace | owner or admin; versions are append-preferred |
| Consultation access | strictly the two parties + admins |
| Audit | every publish/fetch/share/assign logged server-side |

This removes R2's predecessor weakness: clients can no longer bypass policy,
because they never possess Drive authority at all.

## 5. Transfers — how bytes move (the key engineering decision)

Bulk payloads must NOT consume website storage; ideally not even website
bandwidth. Options:

| Option | How | Pros / Cons |
|---|---|---|
| **A. Laravel proxy** | client ⇄ Laravel ⇄ Drive streams | Simplest, full control, Range support · VPS bandwidth ×2, large-file load on PHP workers |
| **B. Brokered resumable-session upload** ⭐ | Laravel calls Drive `files.create (uploadType=resumable)` with its own token, returns the **session URI**; the workstation PUTs bytes straight to `googleusercontent.com` | Tokenless client upload scoped to exactly one file; resumable; zero VPS payload bandwidth · upload only |
| **C. Short-lived access token to client** | Laravel mints a Drive access token | Direct down/up · token is account-wide for app files → over-grants; avoid |
| **D. Temporary link-share download** | server sets `anyoneWithLink` for N minutes | CDN-ish, cheap · public-ish exposure window; only for de-identified media |

**Recommendation:** **uploads = B** (elegant, secure, proven Drive feature);
**downloads = A first** (Laravel streaming proxy with HTTP Range + per-item
authorization; measure VPS bandwidth), with **D as an optimization** for big
public library media (videos/textbooks) only. Revisit C never, unless Workspace +
finer scopes arrive. DICOM consultations always go A (never D).

Integrity: client computes SHA-256 per file (already in `item.json`); on finalize
Laravel cross-checks Drive's `md5Checksum`+size per file and spot-verifies; catalog
row commits only after verification (mirrors the consultation "verify before
ingest" invariant on the server side).

## 6. API design (Laravel, `/api/v1`, Sanctum bearer)

```
# auth / linking
POST /auth/workstation/pair          {pairing_code|credentials} → {token, user}
GET  /me                             profile, roles, groups

# education catalog
GET  /education/items?kind=&updated_since=&visibility=&owner=me   (delta sync)
GET  /education/items/{id}                       meta + files manifest
POST /education/items                            publish intent:
                                                 {kind, meta, files:[{rel,sha256,size}]}
                                                 → 201 {item_id, upload_plan:[{rel, session_uri}]}
POST /education/items/{id}/finalize              → server verifies vs Drive, commits
GET  /education/items/{id}/download              → {plan:[{rel, url}]} (proxy URLs)
DELETE /education/items/{id}                     (soft delete/trash)
POST /education/items/{id}/permissions           visibility/grants (admin/owner)

# consultations (v2 — assignment by user, server-held Drive)
POST /consultations                              {assignee_user_id, meta, files[]} → upload_plan
POST /consultations/{id}/finalize
GET  /consultations?box=inbox|sent&status=…&updated_since=…
GET  /consultations/{id}/download                → proxy plan
POST /consultations/{id}/responses               {text, files[]} → upload_plan
POST /consultations/{id}/close
GET  /notifications?since=…                      (workstation poll; web push later)
```

Workstation client changes (this repo, later phase):
- `EducationCloudStore`/`EducationSyncService` keep their **public API from R1 §6**
  but their internals swap `CloudTransport`-direct calls for the Laravel REST plan
  (upload via session URIs, download via proxy URLs). Local state tables
  (`education_items` etc., R1 §5.2) and resumable per-file logic stay.
- `ConsultationPoller` gains (eventually: is replaced by) a Laravel
  `GET /notifications` backend — fixes cross-account detection structurally.
- The Education ▸ Online Consultation tab UI is reused as-is; only workers change.

WordPress consumes the same Laravel API (server-to-server or plugin), so the site's
Case-of-the-Day page, course library, and dashboards are views over one catalog.

## 7. What survives, what moves, what dies

| As-built piece (this repo) | R2 fate |
|---|---|
| `item.json` format, SHA-256 integrity, package layouts | **Survives unchanged** (data plane contract) |
| `GoogleDriveTransport`, `CloudSyncEngine` | Algorithm/reference for the **Laravel Drive service** (PHP re-implementation server-side); workstation copies remain for the personal-account external-consultation flow if kept |
| Identity module | **Survives**; gains `aipacs_web` provider; org `__org__` Drive link NOT rolled out to clients |
| Education tab, compose/respond/inbox UI | **Survives**; backend swapped to REST |
| Local education layout + `education_cloud_db` tables (R1 §5.2/§7) | **Survives** (client-side sync state) |
| `library/index.json`, client-side role checks, per-client hub credential | **Dropped** |
| Course export bundle (gap) | Still needed (workstation side, P2) |
| R1 §4.4 drive.file cross-account gap | Structurally eliminated (server owns Drive) |

## 8. Phasing (revised; U = Umbrella/server work, W = workstation work)

| Phase | Deliverable |
|---|---|
| **P0 (U)** | Laravel: hub Drive credential storage + Drive service (folders, resumable sessions, verify); catalog migrations; Sanctum pairing endpoint. Verify WP⇄Laravel auth bridge + VPS bandwidth budget |
| **P1 (U+W)** | Media (videos/textbooks): publish intent→session-URI upload→finalize; library list + download proxy; workstation `aipacs_web` provider + Cloud Library view; WP library page |
| **P2 (U+W)** | Courses: `export_course_bundle` (W) + publish/fetch; WP course pages |
| **P3 (U+W)** | Case of the Day: anonymize-on-publish (W) → site CoD page (U/WP) + workstation "Server" section fed by the API |
| **P4 (U+W)** | Consultations v2 on the platform (user-id assignment, notifications endpoint); workstation workers swapped; deprecate Google-email routing for internal cases |
| **P5 (U)** | Dashboards, groups, fine-grained grants, usage/quota admin, audit UI |
| **P6** | Optional: CDN/cache in front of download proxy; Workspace/Shared-Drive migration if org policy ever requires BAA-grade PHI handling |

## 9. To verify in the Umbrella project (first session there)

1. Laravel version, auth stack (Sanctum?), queue/worker setup (needed for finalize
   verification + future webhooks), where the existing "Google Drive API already
   implemented" code lives (website side? which scopes/account?).
2. WordPress ⇄ Laravel account bridge (single sign-on? shared users table?).
3. VPS bandwidth/disk ceilings → confirms download strategy (A vs A+D).
4. TLS/domain for the workstation API + token rotation policy.
5. Whether any existing website "Case of the Day" schema exists to align with
   `item.json` fields before P3.

## 10. Recommendation

**Yes — move implementation to the Umbrella project.** The control plane (P0/P1
server work) lives in Laravel/WordPress code this repo cannot see. Keep THIS doc in
the workstation repo as the shared contract (Umbrella mounts this repo too);
workstation-side phases (provider, export bundles, UI swaps) continue to be built
and tested here under the existing guards (`tests/code/education_online_consultation`,
plugin-mirror sync for `modules/education/`).
