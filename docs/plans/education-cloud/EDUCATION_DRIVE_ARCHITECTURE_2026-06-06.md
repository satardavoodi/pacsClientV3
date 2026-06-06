# Education ↔ Google Drive — Cloud Library Architecture (proposal)

> **R1 — PARTIALLY SUPERSEDED (same day):** the control-plane design here
> (Drive-only management, `library/index.json`, per-workstation `__org__` hub
> credential, app-side role checks) is replaced by the **three-tier R2**:
> `EDUCATION_CLOUD_THREE_TIER_R2_2026-06-06.md` (Drive = storage, Laravel/WordPress
> = management, workstations = clients). Still valid from this doc: §1 current-state
> review, §3 item folder + `item.json` format, §4.4 drive.file finding, §5 sync
> mechanics/local state tables, §7 local layout, course-export gap.

**Status:** DESIGN PROPOSAL (no code yet — pending approval)
**Date:** 2026-06-06
**Hub account:** `AI.pacs.medical@gmail.com` (consumer Gmail — see §9 limits)
**Builds on:** `modules/Identity` + `modules/cloud_consultation` (as-built:
`docs/pipelines/online-consultation-education.md`) and the Education module's local
storage (`PacsClient/utils/data_paths.py` Education block).

---

## 0. TL;DR

1. **One organization "hub" Google account** (`AI.pacs.medical@gmail.com`) owns the
   whole Education tree on Drive. Every workstation connects it **once** through the
   existing Identity module (a reserved `__org__` link key). Users are mapped by
   **metadata, not by Google accounts** — each uploaded item records its
   AI-PACS `auth_user` owner.
2. **Everything on Drive is an "item folder" with a sealed `item.json`** — the same
   manifest+SHA-256 pattern the consultation envelope already proved. Four kinds:
   `case_of_day`, `course`, `video`, `textbook` (consultations keep their existing
   separate root, unchanged).
3. **Sync = the proven consultation machinery, generalized**: resumable per-file
   state in SQLite, `.part`+`os.replace` atomic writes, integrity verify before
   ingest, poller-style background pull, explicit Publish for push. Offline-first:
   the local Education module keeps working with zero connectivity.
4. **Bonus:** the hub model *fixes a latent cross-account gap* in the current
   consultation design (§4.4): under the `drive.file` scope, user B's app cannot
   see a folder user A merely *shared* with B. With one shared hub account both
   sides list the same Drive, so detection always works.

---

## 1. What exists today (grounded in code)

### 1.1 Local Education storage (workstation-global, NOT per-user)
```
USER_DATA_ROOT/
  education/
    courses/                  EDUCATION_COURSES_DIR
      course_<pk>/assets/     per-course asset trees (save_course_asset[_tree])
      MyCourse/               EDUCATION_MY_COURSE_DIR (legacy nest)
    assets/                   EDUCATION_ASSETS_DIR
    Case of the Day/          CASE_OF_DAY_DIR — one package dir per case:
      <case>/dicom/           ← DB dicom_folder_path points here
      <case>/metadata.json    PACKAGE_METADATA_FILE
      <case>/reception.json   PACKAGE_RECEPTION_FILE
      <case>/attachments/
  cloud_consultation/{outgoing,incoming}/<consultation_id>/   (existing)
  database/dicom.db           courses / slides / slide_contents /
                              case_of_day_entries tables (SHARED by all users)
```
- `courses.resource_type ∈ {Course, Book, Video}` — **videos and textbooks are
  already course rows**; a "media library" is a filtered view, not a new system.
- Import bundles exist (`education-import-v1`, `education-folder-import-v1` in
  `course_database.py`); **there is no course export yet** — publishing needs one.
- `case_of_day_widget.CaseOfDayLocalServerPage` already renders a **"Server"
  placeholder section** — the Drive library is exactly the feed it was reserved for.
- **No per-user scoping anywhere**: `author_name` is free text; `is_my_course` is a
  workstation-global flag. User mapping must be added (additively) by this design.

### 1.2 Cloud building blocks (reuse as-is)
- `modules/Identity` — OAuth PKCE, secure token store, `get_capability_client(CLOUD_STORAGE)`
  → Drive v3 service. Link key = `aipacs_user`.
- `modules/cloud_consultation` — `CloudTransport` ABC + `GoogleDriveTransport`
  (resumable upload, atomic download, share, change cursor), `CloudSyncEngine`
  (per-file resume state), envelope seal/verify, poller pattern, status state machine.
- Offline Cloud package engine — folder packages with manifest + `package.db`.

---

## 2. Identity & user mapping (hub-account model)

```
AI-PACS server login (per user, UNCHANGED)          Google identities
┌──────────────────────────────┐     link      ┌──────────────────────────────────┐
│ auth_user = {username, role} │◀──────────────│ per-user personal Google accounts │
└──────────────┬───────────────┘   (existing)  │ (external consultations, optional)│
               │ reads username                 ├──────────────────────────────────┤
               ▼                                │ ORG HUB: AI.pacs.medical@gmail.com│
   item.json owner = {aipacs_user,             │ link key "__org__" — connected    │
   display_name}  ← user mapping is            │ ONCE per workstation (admin role) │
   METADATA, not Drive ACLs                    └──────────────────────────────────┘
```

- **Connect once per workstation:** Identity panel gets an "Organization Drive"
  card; connecting stores the hub identity under the reserved link key `__org__`
  (`identity_db` row `aipacs_user="__org__"`). `IdentityService.get_org_identity()`
  (new, ~10 lines) returns it for any logged-in user. Admin-only connect/disconnect
  (gate on `auth_user["role"]`).
- **Per-user attribution:** every published item embeds
  `owner: {aipacs_user, display_name}` in `item.json`; the Education UI derives
  "Library" (everything) vs "Mine" (owner == current login). Additive nullable
  `owner_user` column on `courses` / `case_of_day_entries` for local filtering
  (idempotent `PRAGMA table_info` migration — same pattern as existing migrations).
- **Why not one Google account per user?** Under `drive.file` cross-account shares
  are invisible to the receiving app (§4.4); consumer Gmail has no Shared Drives;
  and a center-wide library should not depend on any individual's account. Personal
  accounts remain supported for *external* consultations exactly as today.

## 3. Drive folder hierarchy (cloud side)

A **new root**, sibling of the untouched `AI-PACS Consultations` folder (the
consultation poller and its guards are not perturbed):

```
AI-PACS Education/                         ← created/owned by the app (drive.file)
  library/                                 ← center-wide published content
    index.json                             ← cheap catalog (see §5.3)
    cases-of-day/<item_id>/                ← Case-of-Day package, EXISTING layout:
        dicom/… , metadata.json, reception.json, attachments/, item.json
    courses/<item_id>/                     ← course bundle:
        course.json (course+slides+contents), assets/…, thumbnail.png, item.json
    media/
      videos/<item_id>/    file.mp4 + item.json
      textbooks/<item_id>/ file.pdf + item.json
  users/<aipacs_user>/                     ← per-user personal cloud space
    drafts/<item_id>/…                     (same item format; not in library index)
  exchange/                                ← optional later: center-to-center shares
```

Rules:
- **Folder names are stable ids** (`item_id` = uuid4 hex), never titles — rename-safe;
  display names live in `item.json`. One item = one folder = one atomic unit.
- `item.json` (sealed last, like `consultation.json`):
```json
{
  "schema": "aipacs-education-item-v1",
  "item_id": "…", "kind": "case_of_day|course|video|textbook",
  "title": "…", "description": "…", "tags": [], "modality": "MRI",
  "owner": {"aipacs_user": "vahid", "display_name": "Dr. Alizadeh"},
  "version": 3, "created_at": "…", "updated_at": "…",
  "integrity": {"algo": "sha256", "files": {"<rel_path>": "<sha256>", "...": "..."}},
  "source": {"workstation": "<hostname>", "app_version": "3.2.2"}
}
```
- Integrity is **our** SHA-256 map (Drive's `md5Checksum` is used only as a cheap
  change hint); verify before any local ingest — same contract as consultations.

## 4. Permissions model

| Concern | Mechanism |
|---|---|
| Who can see the library | Everyone whose workstation has the org hub connected (single account ⇒ Drive-side it's all-or-nothing). |
| Who can publish/delete | **App-side enforcement** by `auth_user.role` (e.g. publish: physician+, delete others' items: admin). Recorded in `item.json.owner` + an audit table. |
| External sharing of one item | `transport.share(folder_id, email, role)` on that item folder only (existing API). |
| Revocation | Disconnect org identity (keychain cleared + token revoke); Google security page can revoke the app for the hub account centrally. |
| PHI | Education/library content must be **de-identified on publish** — reuse the CD-burner anonymizer (`modules/cd_burner/dicom_prepare.py`) for `case_of_day` DICOM before upload (default ON, like the burn pipeline's "anonymize excludes on failure" invariant). Consumer Gmail is never BAA-covered (§9). |

**Honest limitation:** with one shared account there are no true per-user Drive
ACLs — any workstation with the hub connected can technically read everything via
Drive directly. Per-user hard isolation requires Google Workspace (Shared Drives +
per-member roles); the proposed `item.json`/role model is forward-compatible with
that migration (§10 P6).

### 4.4 Finding: cross-account consultations under `drive.file` (pre-existing)
`find_assigned_consultations` lists the **user's own** app folder. A folder that
Dr. A *shared* to Dr. B lands in B's "Shared with me", which the `drive.file` scope
does **not** expose to B's app (it only sees files the app created or the user
explicitly opened with the app). So A→B detection across two personal accounts
likely fails silently — consistent with "live A→B→A QA pending". Options:
(a) **hub model (this proposal): both sides poll the same Drive — gap disappears** for
intra-center consultations; (b) for external consultations keep personal accounts but
have the assignee open the shared folder once via a Drive picker, or widen scope —
decide only if/when external flow is prioritized.

## 5. Synchronization model

### 5.1 Principles
Offline-first (local is the working copy; cloud is a library/transport), explicit
**Publish** for push (no silent uploads of clinical material), background **pull**
of the catalog with on-demand payload fetch, everything resumable + integrity-gated,
and **no UI-thread blocking** (QThread workers, poller pattern).

### 5.2 State (new `database/education_cloud_db.py`, mirrors consultation tables)
```sql
education_items(item_id PK, kind, title, owner_user, version,
                remote_folder_id, local_path, status,        -- local|published|stale|fetching|synced|conflict
                manifest_sha256, updated_at, last_synced_at)
education_item_files(item_id, rel_path, remote_file_id, sha256,
                     bytes_total, bytes_done, state, UNIQUE(item_id, rel_path))
education_sync_meta(key PK, value)   -- drive change cursor, library index etag/version
```
Self-initializing, lazy `_db_conn`, temp-DB-patchable — identical discipline to
`consultation_db` (test isolation rules apply).

### 5.3 Catalog: `library/index.json` + change cursor
Listing hundreds of item folders per refresh is slow and rate-limited. Instead:
- On every publish/remove the store **rewrites `library/index.json`**
  (`{index_version, generated_at, items: [item.json summaries]}`).
- Pull = download one small file, diff against `education_items`, mark new/changed
  items `stale`. `transport.changes_since(cursor)` (already implemented) is the
  cheap invalidation trigger between timer ticks.
- Index corruption/missing ⇒ fall back to a full folder walk (the consultation
  poller's listing approach) and regenerate.
- Concurrent publishers: last index write wins, but the index is **derived data** —
  a nightly/`force_refresh` walk self-heals (index never the source of truth).

### 5.4 Flows
```
PUBLISH (user action, worker thread)
  adapter.export_bundle(local entity) → staging dir
    (courses: NEW export_course_bundle — course.json+assets;
     case_of_day: copy existing package dir, anonymize dicom/ on the copy;
     media: file + sidecar)
  seal item.json (sha256 map, version = prev+1)
  EducationSyncEngine.upload(item_id, staging)        ← resumable, per-file state
  update index.json · status=published · notify(upload_done)

PULL (timer, off-thread — EducationLibraryPoller, clone of ConsultationPoller)
  read index.json (or changes cursor) → upsert education_items, mark stale
  UI badge "N updates available" · auto-fetch only small metadata, never payloads

FETCH (user opens a stale/remote item, worker thread)
  EducationSyncEngine.download(item_id, dest) → verify integrity (reject+quarantine
  on mismatch, sync_error notification) → adapter.import_bundle(dest)
    (courses: existing import_course_folder_to_my_courses;
     case_of_day: insert_case + copy into CASE_OF_DAY_DIR → feeds the "Server" tab;
     media: register course row resource_type=Video/Book)
```

### 5.5 Conflicts & versions
Reuse the consultation fingerprint logic (`sync/state_machine.py::fingerprint` /
`detect_conflict`): same `version` + different content fingerprint = **conflict** →
keep both (loser saved locally as `<title>.conflict-<ts>`), status `conflict`, user
resolves by re-publishing (version bumps). Different versions = normal update
(higher wins). Personal `users/<me>/drafts` = last-writer-wins (single writer in
practice). Deletes = move to Drive trash + drop from index (recoverable 30 days).

## 6. API layer design (new `modules/education/cloud_store/`)

```python
# models.py  (Qt-free)
class ItemKind(str, Enum): CASE_OF_DAY="case_of_day"; COURSE="course"; VIDEO="video"; TEXTBOOK="textbook"
@dataclass class EducationItemMeta: item_id, kind, title, owner, version, integrity, …
    to_dict / from_dict   # == item.json

# layout.py (Qt-free) — folder conventions + ensure
class DriveLayout:
    ROOT="AI-PACS Education"
    def ensure(transport) -> LayoutIds          # idempotent folder ids (cached)
    def kind_folder(ids, kind) -> str
    def user_folder(ids, aipacs_user) -> str

# store.py (Qt-free; the API the rest of the app calls) — transport injected,
# obtained via Identity: get_org_identity() → get_capability_client(CLOUD_STORAGE)
class EducationCloudStore:
    def __init__(self, transport, *, progress_cb=None)
    def list_library(kind=None, *, force_refresh=False) -> list[EducationItemMeta]
    def publish(kind, staging_dir, meta) -> EducationItemMeta      # seal+upload+index
    def fetch(item_id, dest_dir) -> Path                           # download+verify
    def remove(item_id) -> None                                    # trash+index
    def share_external(item_id, email, role="reader") -> ShareInfo
    def publish_user_draft(aipacs_user, staging_dir, meta) -> …    # users/<u>/drafts

# sync_engine.py (Qt-free) — CloudSyncEngine's algorithm re-targeted at
# education_item_files (small sibling class; do NOT modify the guarded
# consultation engine)

# adapters/ (Qt-free) — bridge local entities ↔ bundles
case_of_day.py: export_case_bundle(case_pk, *, anonymize=True) / import_case_bundle(dir)
courses.py:     export_course_bundle(course_pk)  [NEW capability] / import = existing engine
media.py:       export_media(file)/import_media(dir)

# service.py (Qt) — EducationCloudService(QObject): publish/fetch queues on QThreads,
# signals (publishProgress/published/fetched/conflict/error),
# EducationLibraryPoller (index poll + notifications via existing inbox.notify)
```
UI wiring (later phase): "Publish to cloud library" on course cards / Case-of-Day
entries; "Cloud Library" view in Education listing `list_library()` with per-kind
filters; Case-of-Day **Server** section = `list_library(kind=CASE_OF_DAY)`.

## 7. Local-side organization (evolution, additive)

```
USER_DATA_ROOT/education/
  courses/ , assets/ , Case of the Day/      ← UNCHANGED working copies
  cloud/                                     ← NEW, all sync-related disk state
    staging/<item_id>/                       outgoing bundles (publish)
    incoming/<item_id>/                      fetched bundles pre-ingest
    cache/index.json                         last library catalog
```
Local DB stays the catalog of *usable* content; `education_items` tracks the cloud
relationship. No existing folder moves; no schema changes beyond additive columns.

## 8. What this reuses vs adds

| Reused unchanged | Added new |
|---|---|
| Identity OAuth/keychain, `get_capability_client` | `__org__` link + `get_org_identity()` |
| `GoogleDriveTransport` (upload/download/share/changes) | `DriveLayout` (folder conventions) |
| Sync algorithm (resume, atomic writes) | `EducationSyncEngine` sibling + new state tables |
| Envelope seal/verify pattern | `item.json` schema + store/adapters |
| Poller + notifications inbox | `EducationLibraryPoller` + index.json catalog |
| Course import engine, Case-of-Day package layout | **Course export bundle** (gap today) |
| CD-burner anonymizer | anonymize-on-publish for case DICOM |

## 9. Constraints & risks (consumer Gmail hub)

1. **15 GB quota** shared with Gmail/Photos — videos/textbooks will consume it
   first. Mitigate: show quota (`about.get`) in the Education cloud view; plan
   Workspace upgrade (also unlocks Shared Drives + BAA).
2. **No BAA on consumer Gmail** ⇒ the library must hold **de-identified** content
   only; anonymize-on-publish is default-ON for case DICOM (§4). Consultations with
   real PHI remain the existing, separate flow and policy.
3. **Shared credentials** = shared blast radius: any workstation with the hub
   connected has full library access; role checks are app-side only (§4 limitation).
4. **OAuth consent in Testing mode** expires grants after 7 days — move the consent
   screen to *In production* before rollout (one-time, no code).
5. **Rate limits** (~12k queries/min/user shared across workstations): index.json
   catalog + change cursor keep steady-state traffic to ~1 small GET per tick;
   exponential backoff on 403/429 in the engine.
6. **Large uploads** are resumable already; cap concurrent transfers (1–2) so the
   DM/socket stack and UI stay smooth (DM-harmony rule).

## 10. Phased delivery (each phase shippable, flag-gated `AIPACS_EDUCATION_CLOUD`)

| Phase | Deliverable | Notes |
|---|---|---|
| **P0** | `__org__` identity + Identity-panel "Organization Drive" card; `DriveLayout.ensure`; state tables | hub connect demo |
| **P1** | Media (videos/textbooks): publish/fetch/list + Cloud Library view | simplest payloads prove the loop |
| **P2** | Courses: `export_course_bundle` + publish/fetch (import reuses existing engine) | closes the export gap |
| **P3** | Case of the Day: anonymize-on-publish + fetch → **lights up the "Server" section** | clinical value |
| **P4** | index.json + change-cursor poller, notifications, conflict UI, quota display | scale + polish |
| **P5** | (optional) move intra-center consultations to the hub root — closes §4.4 for internal cases | decision point |
| **P6** | Workspace migration: Shared Drive + per-user ACLs + BAA | when org is ready |

## 11. Open questions
1. Confirm the hub model vs per-user accounts for the *library* (this doc assumes
   hub; consultations keep personal accounts until P5).
2. Publish rights: which `auth_user.role`s may publish / delete others' items?
3. Anonymize-on-publish for Case-of-Day DICOM: confirm default-ON (recommended).
4. Auto-pull payloads (e.g. new Case of the Day downloads itself) vs metadata-only
   with manual fetch (recommended default: metadata-only).
5. Quota plan: stay on 15 GB Gmail for the pilot, or move to Workspace before P1?
