# AI-PACS `Identity` Module + Google Drive Physician-Consultation Layer — Implementation Plan

**Status:** PLAN / design proposal (no production code yet — pending approval)
**Date:** 2026-05-31
**Author:** AI-PACS engineering agent
**Scope:** Add a separate, extensible **`modules/Identity`** layer that lets a
signed-in AI-PACS user attach **external identities** (Google first; Telegram /
Instagram / others later) to their existing account, and use a connected Google
identity to drive a **Google Drive–backed physician-consultation workflow** that
reuses the existing Offline Server / Offline Folder package engine.

### Revision history
- **R2 (2026-05-31) — this document.** Corrected per stakeholder direction:
  - The **existing AI-PACS server login is preserved and untouched.** It remains the
    primary identity bound to the center/server connection. `app_handler.py` is **not**
    modified for identity, and no "Sign in with Google" button is added to the login
    dialog.
  - External accounts now live in a dedicated, pluggable **`modules/Identity`** module
    and **link to (never replace)** the AI-PACS user.
  - Google is **identity provider #1**; the abstraction is generalized beyond cloud
    storage so **Telegram / Instagram / future providers** slot in without rework.
  - Consultation **assignment to a specific physician** and **in-app notification of
    the assignee** are elevated to first-class requirements.
- **R1 (2026-05-31).** Initial plan (Google sign-in integrated into the account
  area). Superseded by R2.

> **North star for the first milestone:** connect a **Google identity** inside the
> new Identity module (link it to the current AI-PACS user, store it securely, show
> connected status) — all *alongside* the unchanged server login.

---

## 0. TL;DR — two ideas that de-risk the whole project

**(1) Two independent identity layers, not one.**
```
  PRIMARY (existing, UNCHANGED)                 SECONDARY (new, additive)
  ┌──────────────────────────────┐             ┌─────────────────────────────────┐
  │ AI-PACS server login          │  link by    │ modules/Identity                │
  │ app_handler.AppHandler        │  username   │  external identities attached    │
  │ socket auth → {username,      │ ◀─────────▶ │  to the AI-PACS user:            │
  │   full_name, role}            │             │   • Google  (profile + Drive)    │
  │ → center/server connection    │             │   • Telegram (future)            │
  │   *** stays exactly as-is ***  │             │   • Instagram (future)           │
  └──────────────────────────────┘             └─────────────────────────────────┘
```
The server login keeps owning "who you are to your center." The Identity module
owns "which external accounts you've connected." They are linked, never merged.

**(2) The package format is already transport-agnostic.**
The Offline Cloud package (`PacsClient/utils/offline_cloud.py`,
`OFFLINE_CLOUD_FORMAT="aipacs-offline-cloud"`, v2) is a *plain folder*
(`manifest.json` + `package.db` + `patients/{dicom,attachments,thumbnails}/<study_uid>/`),
**not** a zip; an "offline cloud server" is literally a named **folder path**. So
**Google Drive is just a transport** that mirrors a local package folder to/from a
remote folder — the export/import/validate engine and manifest schema are reused
**unchanged**. A connected Google identity (from the Identity module) supplies the
Drive credentials the transport needs.

```
   EXISTING (unchanged)                  modules/Identity            NEW consultation
 ┌────────────────────────┐   creds   ┌───────────────────┐  uses ┌──────────────────┐
 │ export/validate/import │ ◀──────── │ GoogleIdentity     │ ────▶ │ GoogleDrive      │
 │ manifest / package.db  │           │  Provider          │       │  Transport       │
 └────────────────────────┘           │ (profile + Drive)  │       │ CloudSyncEngine  │
                                       └───────────────────┘       │ Assignment+Notify│
                                                                    └──────────────────┘
```

---

## 1. Current-state architecture (as-built, grounded in the code)

### 1.1 Server login & identity (today) — **PRESERVE UNCHANGED**
- **Login dialog:** `PacsClient/app_handler.py` → `AppHandler(QDialog)`.
  `login()` → `_complete_login()` branches **local login** → **socket auth**
  (`_authenticate_with_socket()` → `client.login()` → `token, user`, stored via
  `get_socket_token_manager().set_token()`) → **demo fallback**. Produces
  `auth_user = {username, full_name, role}` bound to the center/server connection.
- **Credential persistence:** `%APPDATA%\AIPacs\login_config.json`
  (`username`, `password`, `remember_me`). Session token in-memory
  (`modules/network/socket_token_manager.SocketTokenManager`).
- **Account widget (top-right):** `…/workstation_ui/mainwindow_ui.py` →
  `MainWindowWidget.window_buttons()` builds `QFrame#UserInfoContainer` (~684–712):
  `fa5s.user` icon (36×36), `QLabel#UserNameLabel` (`auth_user['full_name']`),
  `QLabel#UserRoleLabel` (`● ROLE`); styled by `_user_info_stylesheet()` from theme
  tokens (`accent`, `accent_soft`, `accent_hover`, `text_primary`, `text_secondary`).
- **R2 rule:** none of the above changes. The Identity module only **reads**
  `auth_user` to know which AI-PACS user to attach external identities to, and only
  **adds** a secondary, optional control to the account-area menu.

### 1.2 Offline Cloud package engine (today) — **REUSE UNCHANGED**
- `PacsClient/utils/offline_cloud.py` (facade: `modules/offline_cloud_server/service.py`).
  Constants `OFFLINE_CLOUD_FORMAT`, `OFFLINE_CLOUD_VERSION=2`,
  `PACKAGE_DB_NAME="package.db"`, `MANIFEST_NAME="manifest.json"`;
  `_PACKAGE_REQUIRED_FOLDERS=(patients, patients/dicom, patients/attachments, patients/thumbnails)`.
- Rich, backward-compatible manifest (`_normalize_manifest()` fills defaults):
  `format/version/package_id/status`, `actors[]`, `timeline[]`, `sync_events[]`,
  `validation{}`, `studies[]` (each with provenance + `sync.record_hash` SHA-256).
- Public API reused as-is: `export_studies_to_offline_cloud()`,
  `sync_offline_cloud_study_to_local()`, `sync_offline_cloud_study_preview_to_local()`
  (metadata/thumbnails only — ideal for lightweight review),
  `validate_offline_cloud_package()`, `list_offline_cloud_studies()`.
  Servers are folder records in `config/offline_cloud_servers.json`.

### 1.3 Database (today)
- SQLite `user_data/database/dicom.db`; pool `database/_pool.py` (WAL, FK on,
  busy_timeout 120 s). Schema bootstrap = `init_database()` in `database/dicom_db.py`;
  domain modules re-exported via `database/core.py`. Migrations are **idempotent
  inline** `CREATE TABLE IF NOT EXISTS` + `PRAGMA table_info` guards.
- Reuse templates: `database/ai_reception_db.py` (notification-queue, status
  pending→read→archived), `ai_secretary_actions` (audit log),
  `token_usage_db._hash_api_key()/_mask_api_key()` (secret hashing).

### 1.4 Background I/O, notifications, theme (today)
- **Off-thread pattern (mature, reuse):** `download_manager/workers/download_process_worker.py`
  runs work in a `multiprocessing.Process`, bridged to Qt via a `Queue` polled by a
  lightweight `QThread`; `WorkerPool` caps concurrency;
  `modules/network/upload_task_manager.py` adds retry/back-off; `download_manager/state`
  gives a resumable, observer-backed state store (`DatabaseObserver`).
- **Notifications:** none today except `modules/storage/disk_alert_service.py`
  (`DiskUsageAlertService(QObject)`, QTimer poll + QMessageBox). We build a real
  center on this shape.
- **Theme/variant:** `PacsClient/utils/ui_variant.py` (`get_ui_variant()` → default
  `"v2"`), `v2_style.py`, `theme_manager.py` (singleton + `themeChanged`). All new UI
  is V2 and subscribes to `themeChanged`.

### 1.5 Dependencies (today)
Present: `PySide6==6.10.2`, `google==3.0.0`, `google-api-python-client==2.168.0`,
`requests[socks]`, `grpcio`. **Add:** `google-auth`, `google-auth-oauthlib`,
`keyring`, `cryptography`.

---

## 2. The `modules/Identity` module (the heart of this revision)

### 2.1 Goal
A self-contained, extensible framework for **external identities** that attach to the
current AI-PACS user. It does **not** authenticate the user to AI-PACS (the server
login already does that). It manages *additional* accounts and the capabilities they
unlock (cloud storage, messaging, profile).

### 2.2 Proposed layout
```
modules/Identity/
  __init__.py
  feature_flags.py                 # identity_module.enabled (default OFF)
  models.py                        # ExternalIdentity, Capability, ProviderInfo
  registry.py                      # provider discovery/registration
  identity_service.py              # link/unlink/list, resolve current AI-PACS user
  secure_store.py                  # keyring (Windows Credential Manager) + DPAPI/Fernet
  providers/
    base.py                        # IdentityProvider ABC (+ Capability enum)
    google/
      provider.py                  # GoogleIdentityProvider
      oauth_flow.py                # Auth-Code + PKCE, loopback redirect
      drive_capability.py          # vends a Drive client / CloudTransport
    telegram/   (future stub)
    instagram/  (future stub)
  ui/
    identity_panel.py              # "Connected Accounts" management panel/dialog
    provider_cards.py              # per-provider connect/disconnect cards
    account_menu_hook.py           # adds a menu entry to the existing account area
```

### 2.3 The provider abstraction (extensible to Telegram/Instagram/…)
```python
class Capability(enum.Enum):
    PROFILE       = "profile"        # name, email/handle, avatar
    CLOUD_STORAGE = "cloud_storage"  # Drive / OneDrive / Dropbox / S3
    MESSAGING     = "messaging"      # Telegram, etc. (future notify/transport)
    PHONE         = "phone"

class IdentityProvider(ABC):
    id: str                          # "google", "telegram", "instagram"
    display_name: str
    capabilities: set[Capability]
    def connect(self, aipacs_user_key: str) -> ExternalIdentity: ...
    def disconnect(self, identity_id: str) -> None: ...
    def is_connected(self, aipacs_user_key: str) -> bool: ...
    def get_profile(self, identity_id: str) -> ExternalIdentity: ...
    def get_capability_client(self, identity_id: str, cap: Capability): ...
```
- **`GoogleIdentityProvider`** → `capabilities = {PROFILE, CLOUD_STORAGE}`.
  `get_capability_client(id, CLOUD_STORAGE)` returns a Drive-backed `CloudTransport`
  (see §4) — this is how the consultation engine gets Drive access *through* the
  Identity module, never reaching for credentials itself.
- **Future** `TelegramIdentityProvider` → `{PROFILE, MESSAGING, PHONE}` (could later
  back an in-app notify channel or an alternate transport);
  `InstagramIdentityProvider` → `{PROFILE}`. They register in `registry.py` and the
  management UI renders them automatically — **no changes to consultation code.**

### 2.4 Linkage to the existing AI-PACS user
- The link key is the current login's `auth_user['username']` (optionally namespaced
  by center/server id if you run multiple centers — open question §13). The Identity
  service reads `auth_user` from the running `MainWindowWidget`/session; it never
  writes to it.
- One AI-PACS user may link several external identities (e.g., a Google work account
  + a personal one); exactly one Google identity can be marked **active for Drive**.

### 2.5 UI — additive only
- **Account area (`mainwindow_ui.py`):** keep the server `UserNameLabel`/`UserRoleLabel`
  exactly as-is. Add a small, optional **"Connected Accounts"** entry to a popup menu
  opened from `UserInfoContainer` (and a tiny status dot if a Google identity is
  connected). When the Identity module is flag-off, the account area is byte-identical
  to today.
- **Identity management panel (`modules/Identity/ui/identity_panel.py`):** a V2-styled
  dialog listing providers as cards — *Google: Connect / Connected as
  name·email / Disconnect / Set active for Drive*; *Telegram (coming soon)*; etc.
  Launchable from the account menu and (optionally) embeddable into the existing
  settings surface (`ServerSettingsDialog` in `modules/network/server_settings_dialog.py`)
  as a new tab — without altering the server-settings logic.

---

## 3. Google identity (provider #1) & secure storage

- **OAuth flow** (`providers/google/oauth_flow.py`): **Authorization Code + PKCE** with
  a **loopback redirect** (`http://127.0.0.1:<ephemeral>/`) — Google's recommended
  flow for **Desktop-app** clients (verified 2026-05; see §9). Opens the system
  browser, runs a one-shot local `http.server`, exchanges code→tokens with PKCE,
  fetches userinfo (`openid email profile`). Triggered **only** from the Identity
  panel, after the user is already logged into AI-PACS.
- **Scopes:** `openid`, `userinfo.email`, `userinfo.profile`, and **`drive.file`**
  (non-sensitive — the app only ever touches files it creates/opens; avoids the heavy
  restricted-scope verification).
- **Secure store** (`secure_store.py`): refresh token in **Windows Credential Manager**
  via `keyring`; fallback `cryptography.Fernet` with the key sealed by **DPAPI**.
  Access tokens in memory. **Never stores the Google password.** Tokens are keyed by
  `(aipacs_user_key, provider, subject_id)`.
- **Profile cache:** display name, email, and avatar (downloaded once, cached on disk);
  shown in the Identity panel and optionally as a secondary chip in the account menu —
  **not** in place of the server user.

---

## 4. Google Drive transport & consultation packaging

> **Module placement (clean separation):** `modules/Identity` owns **identities and
> credentials** only. The **consultation engine** — `CloudTransport` interface,
> `CloudSyncEngine`, `ConsultationService`, `NotificationService`, and consultation UI
> — lives in a **separate `modules/cloud_consultation/`** module (it may extend
> `modules/offline_cloud_server`). The Google provider in `modules/Identity` simply
> **vends an authenticated client** (`get_capability_client(CLOUD_STORAGE)`) that
> satisfies the consultation module's `CloudTransport` interface. Thus identity is
> swappable (Google→OneDrive→…) and consultation never holds raw credentials.

### 4.1 Transport abstraction (fed by the Identity module)
```python
class CloudTransport(ABC):           # transport, distinct from IdentityProvider
    name: str                        # "google_drive"
    def ensure_app_folder(self) -> str: ...           # "AI-PACS Consultations"
    def make_child_folder(self, parent_id, name) -> str: ...
    def list_folder(self, folder_id) -> list[RemoteEntry]: ...
    def upload_file(self, local_path, parent_id, name, *, resume_token=None, progress_cb=None) -> RemoteEntry: ...
    def download_file(self, file_id, local_path, *, resume_token=None, progress_cb=None) -> None: ...
    def share(self, file_id, recipient_email, role="reader") -> ShareInfo: ...
    def revoke_share(self, file_id, recipient_email) -> None: ...
    def changes_since(self, cursor) -> tuple[list[RemoteChange], str]: ...
```
- `GoogleDriveTransport` (under `providers/google/drive_capability.py`) maps to Drive
  v3 (`files.*`, resumable uploads, `permissions.create`, `changes.list`). It is
  obtained via `GoogleIdentityProvider.get_capability_client(id, CLOUD_STORAGE)` — the
  consultation layer asks the Identity module, never Google directly.
- Future `OneDriveTransport`/`DropboxTransport`/`S3Transport` implement the same ABC.

### 4.2 Reusing the offline package engine (unchanged)
- **Export:** `export_studies_to_offline_cloud()` writes to a **local staging folder**
  `user_data/cloud_consultation/outgoing/<consultation_id>/`; the sync engine mirrors it
  to Drive. **No engine change.**
- **Import:** the sync engine pulls a remote package folder into
  `…/incoming/<consultation_id>/`; then `validate_offline_cloud_package()` +
  `sync_offline_cloud_study_to_local()` ingest it. **No engine change.**

### 4.3 CloudSyncEngine (resumable, off-thread)
Mirrors the proven download-manager architecture: a `multiprocessing.Process` worker
+ `WorkerPool` + a `CloudSyncStateStore` with a `DatabaseObserver` (resume on
restart), `*.part` + `os.replace()` atomic writes, retry/back-off. UI receives Qt
signals only — **never blocks the UI thread.**

---

## 5. Consultation workflow, **assignment**, and state machine

**Round-trip (all inside AI-PACS):**
```
Physician A (Identity: Google connected): select patient(s) ▶ Compose consultation
  (title, clinical question, ASSIGN to Dr. B by Google email) ▶ export package
  (existing engine) ▶ CloudSyncEngine uploads to Drive ▶ share with B ▶ status=Uploaded
Physician B (Identity: Google connected): in-app NOTIFICATION of assignment ▶ download
  package ▶ open case ▶ review ▶ write opinion/report ▶ upload response ▶ status=Answered
Physician A: in-app NOTIFICATION (response) ▶ download response ▶ review ▶ Close
```

### 5.1 Assignment & routing (new, first-class)
- **Assignee identity = a Google email** (the identity Dr. B will use to download).
  v1: manual email entry plus an optional saved **"colleagues"** list
  (`config/consultation_colleagues.json`); future: a center directory.
- On assign: `GoogleDriveTransport.share(folder_id, assignee_email, role="reader")`
  **and** record `consultation.assignee` in the manifest + `consultations` row
  (`assignee_email`, `assigned_by`, `assigned_at`).
- **Routing model** (open question §13): start with **direct Drive shares** to the
  assignee's email (simplest); optionally evolve to a shared per-pair/group
  "Consultations" folder for threaded cases.

### 5.2 Notification of the assignee (new, first-class)
- Dr. B's AI-PACS, via **his own connected Google identity**, polls the shared
  consultations area (`changes_since(cursor)` / folder listing) on a timer (off-thread).
- On detecting a package **assigned to his email**, it writes a `notifications` row
  (`kind="consultation_assigned"`) → badge on the account area + entry in the
  Notification Center. Same mechanism raises `response_received`, `upload_done`,
  `download_done`, `sync_error`.
- Requires both physicians to have connected Google identities in their respective
  Identity modules — which is exactly the Phase-1 capability.

### 5.3 State machine (persisted, resumable)
```
Pending ─upload→ Uploaded ─assignee-download→ Downloaded ─open→ Reviewed
Reviewed ─respond+upload→ Answered ─originator-download→ (review) ─→ Closed
Any divergent edit at the same version ─→ Conflict ─resolve→ (chosen version)
```
Conflict detection compares `package_version` + `manifest_sha256` + per-study
`record_hash` (already SHA-256 in the manifest).

---

## 6. Notification system
- `NotificationService(QObject)`: `notify(kind, title, body, consultation_id)` writes to
  the `notifications` table and emits `notificationAdded`.
- Polling uses the `DiskUsageAlertService` QTimer shape + provider `changes_since()`,
  all off-thread.
- Surfaces: a **badge** on the account container (`mainwindow_ui.py`, additive), a
  dropdown **Notification Center**, and optional future email/Telegram (via a future
  MESSAGING-capable identity).

---

## 7. Database / storage schema (additive, idempotent, isolated)

New modules `database/identity_db.py`, `database/consultation_db.py`,
`database/notifications_db.py`; each exposes `*_ensure_schema()` called from
`init_database()` and re-exported from `database/core.py`. **No existing column
changes.**

```sql
-- database/identity_db.py  — external identities LINKED to the AI-PACS user
CREATE TABLE IF NOT EXISTS external_identities (
  id            INTEGER PRIMARY KEY,
  aipacs_user   TEXT NOT NULL,           -- link key = current login username (+center)
  provider      TEXT NOT NULL,           -- 'google' | 'telegram' | 'instagram' | …
  subject_id    TEXT NOT NULL,           -- provider stable id (Google 'sub', etc.)
  handle        TEXT,                     -- email / @handle / phone
  display_name  TEXT, avatar_cache TEXT,
  capabilities  TEXT,                     -- JSON: ["profile","cloud_storage",…]
  is_active_for TEXT,                     -- JSON: capabilities this identity is active for
  linked_at     TEXT, last_used_at TEXT,
  UNIQUE(aipacs_user, provider, subject_id)
);  -- refresh tokens are NOT here; they live in the OS keychain (secure_store)

-- database/consultation_db.py
CREATE TABLE IF NOT EXISTS consultations (
  id INTEGER PRIMARY KEY, consultation_id TEXT NOT NULL UNIQUE,
  direction TEXT NOT NULL,                -- 'outgoing' | 'incoming'
  status TEXT NOT NULL,                   -- pending|uploaded|downloaded|reviewed|answered|closed|conflict
  provider TEXT NOT NULL DEFAULT 'google_drive',
  remote_folder_id TEXT, local_path TEXT,
  owner_identity_id INTEGER,              -- which external_identities row owns transport
  from_handle TEXT,
  assignee_email TEXT, assigned_by TEXT, assigned_at TEXT,   -- assignment
  case_title TEXT, clinical_question TEXT, priority TEXT,
  package_version INTEGER NOT NULL DEFAULT 1, manifest_sha256 TEXT,
  study_uids TEXT, created_at TEXT, updated_at TEXT, due_at TEXT, last_synced_at TEXT
);
CREATE TABLE IF NOT EXISTS consultation_files (    -- resumable transfer state
  id INTEGER PRIMARY KEY, consultation_id TEXT NOT NULL,
  rel_path TEXT NOT NULL, remote_file_id TEXT, sha256 TEXT,
  bytes_total INTEGER, bytes_done INTEGER, resume_token TEXT, state TEXT, updated_at TEXT,
  UNIQUE(consultation_id, rel_path)
);
CREATE TABLE IF NOT EXISTS consultation_events (   -- audit trail
  id INTEGER PRIMARY KEY, consultation_id TEXT NOT NULL,
  event_type TEXT NOT NULL,               -- created|assigned|uploaded|shared|downloaded|reviewed|responded|closed|conflict|error
  actor_handle TEXT, actor_subject TEXT, details TEXT, created_at TEXT
);

-- database/notifications_db.py  (mirrors ai_reception_db queue)
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL,   -- consultation_assigned|updated|response_received|upload_done|download_done|sync_error
  title TEXT, body TEXT, consultation_id TEXT,
  status TEXT NOT NULL DEFAULT 'unread', created_at TEXT
);
```

---

## 8. Consultation **envelope** (additive manifest block)
One new optional top-level block; absence = a normal offline package (still validates):
```json
"consultation": {
  "consultation_id": "uuid", "schema_version": 1,
  "case_title": "…", "clinical_question": "…", "priority": "routine|urgent",
  "from_user":  {"provider":"google","subject":"…","email":"…","name":"…"},
  "assignee":   {"email":"…","name":"…"},          // who it is assigned to
  "status": "pending|uploaded|downloaded|reviewed|answered|closed",
  "created_at": "…", "due_at": "…",
  "responses": [ {"response_id":"uuid","from_user":{…},"created_at":"…",
                  "kind":"opinion","report_ref":"patients/attachments/<uid>/report.html"} ],
  "integrity": {"manifest_sha256":"…","files_sha256":{"<rel_path>":"sha256", …}}
}
```
Additive + backward compatible (`_normalize_manifest()` ignores it on old builds).
`integrity` is verified on download **before** import; mismatch → quarantine +
`sync_error` notification.

---

## 9. Google Cloud Console setup (step-by-step; verified 2026-05)

> Use **`drive.file`** (non-sensitive) → lighter verification; the app only touches its
> own consultation folders.

1. **Create/select a project** — Console → project picker → *New Project*
   (e.g. `AI-PACS-Consultation`).
2. **Enable the Google Drive API** — *APIs & Services → Library*. (Profile/email come
   from the OIDC userinfo scopes; People API only if you want richer org fields.)
3. **OAuth consent screen** — *External* (or *Internal* if one Google Workspace org is
   the only audience — Internal needs no verification and is ideal for a single
   hospital). Add scopes `openid`, `userinfo.email`, `userinfo.profile`, `drive.file`.
   Add each physician as a **test user**. ⚠️ **In Testing mode a test user's grant
   expires after 7 days** (re-consent weekly) and the cap is 100 test users — move to
   *In production* (or use Internal) to remove both.
4. **Create OAuth client ID** — *Credentials → Create credentials → OAuth client ID →
   Application type: **Desktop app***. For installed apps the **client secret is not
   confidential**; **PKCE** + the **loopback** redirect (no fixed redirect URI to
   register) are what protect the exchange.
5. **(Later, >100 users / public)** Submit for verification — with `drive.file`+userinfo
   this is the lighter brand-verification path, not the heavy restricted-scope CASA
   assessment full-Drive would trigger.
6. **Record config** — non-secret client config in
   `config/identity/google_oauth.json` (client_id, project_id, auth/token URIs, scopes).

On your go-ahead I can drive steps 1–6 live in the open Chrome window and validate the
client/scopes before any code is written.

---

## 10. Security model (medical-grade)

| Requirement | Approach |
|---|---|
| **Server login untouched** | Identity module never writes to `auth_user`/`SocketTokenManager`; it only reads the username to link. |
| **No external password storage** | OAuth only; Google password never seen. |
| **Encrypted token storage** | Refresh token in Windows Credential Manager (`keyring`); fallback DPAPI-sealed `Fernet`. Access tokens in memory. |
| **Least privilege** | `drive.file` only — never the whole Drive. |
| **Audit logging** | `consultation_events` + identity link/unlink/refresh events (reuse `ai_secretary_actions` pattern). |
| **Consent-based sharing** | Explicit assignee + confirmation dialog naming the patient(s)/studies leaving the workstation; recorded in events + manifest `actors[]`. |
| **Integrity** | SHA-256 manifest + per-file hashes verified before import. |
| **Revocable access** | `revoke_share()` removes the Drive permission; "Disconnect identity" calls Google's token **revoke** endpoint and clears the keychain entry. |
| **Ownership tracking** | `from_user.subject` + `owner_identity_id` + `actors[]` provenance. |

### 10.1 ⚠️ PHI / compliance decision (verified 2026-05)
Packages contain PHI. **Consumer Gmail accounts are *not* HIPAA-eligible and can never
be made compliant** — a paid **Google Workspace + signed BAA** is required, and Drive
is a BAA-covered service. For real patient data, physicians must connect **Workspace**
Google identities (or your jurisdiction's equivalent under GDPR/DPA). Consumer Gmail is
acceptable only for **de-identified/teaching** cases. I also recommend an optional
**client-side package encryption** step and an optional **de-identification** pass
before upload (designed-in; policy choice — see §13).

---

## 11. Extensibility: future identity providers & web reuse
- **Telegram** (`{PROFILE, MESSAGING, PHONE}`): connect via phone/bot token; could later
  back an in-app/notification channel or an alternate package-transport. Slots into
  `IdentityProvider` + `registry.py`; the Identity panel renders it automatically.
- **Instagram** (`{PROFILE}`): profile-only link; no consultation role unless a
  capability is added.
- **Web / WordPress reuse:** the portable identity claim (`provider`, `subject_id`,
  verified email, name) is provider-stable, so the AI-PACS website / LMS /
  Case-of-the-Day / licensing can later trust the **same Google `sub`** via their own
  OAuth — the workstation never ships tokens to the web. `external_identities` is a
  clean subset of a future server-side `accounts` table.

---

## 12. Regression guards & invariants (must hold)
1. **The existing AI-PACS server login is unchanged.** `app_handler.py` identity flow,
   `SocketTokenManager`, and the account-area server-user labels behave exactly as
   today. The Identity module is read-only with respect to them.
2. **Feature flag `identity_module.enabled` (default OFF) ⇒ zero behavioral change**;
   the account area and Offline Server are byte-identical when off (mirrors the
   existing V1/V2 `home_is_v2()` no-op discipline).
3. **FAST viewer never instantiates VTK render windows** — untouched here.
4. **DICOM stays on the socket stack; Drive is HTTP for packages only** — do not cross
   them; thumbnail/patient sockets keep using the socket-protocol port per `CLAUDE.md`.
5. **DB additions are new tables only**, idempotent, isolated, called from
   `init_database()`; tests keep patching `PacsClient.utils.data_paths.DATABASE_FILE`.
6. **No UI-thread blocking** — all transfer/poll work uses the
   `multiprocessing.Process` + `WorkerPool` pattern; UI gets Qt signals only.
7. **Reuse, don't fork, the package engine**; the envelope is additive.
8. **All new UI is V2**, token-styled, subscribes to `themeChanged`.

---

## 13. Open questions (need your decision)
1. **PHI account type:** Google **Workspace + BAA** (required for real patient data) vs
   consumer Gmail (de-identified/teaching pilots only)? *(Blocks production, not the
   Phase-1 connect capability.)*
2. **Link key:** is the AI-PACS user uniquely identified by `username` alone, or do you
   run multiple centers/servers where I should namespace by `center/server id`?
3. **Token storage:** confirm `keyring` → Windows Credential Manager (recommended), else
   DPAPI-sealed encrypted file.
4. **Scope:** confirm `drive.file` (recommended) vs broader Drive access.
5. **Assignment routing:** direct Drive shares to the assignee's email (v1) vs a shared
   per-pair/group consultations folder (threaded)?
6. **Colleague directory:** manual email entry + saved list (v1) vs a managed center
   directory of physicians?
7. **Client-side encryption / de-identification:** default-on, optional, or out of v1?

---

## 14. Phased delivery plan (regression-first)

All phases gated by `identity_module.enabled` (default OFF). The server login is never
modified.

| Phase | Deliverable | Risk | Touches clinical/login paths? |
|------|-------------|------|-------------------------------|
| **0** | Scaffold `modules/Identity` (flag, `IdentityProvider` ABC, registry, `secure_store`, `external_identities` table) — all dormant | Very low | No |
| **1 ⭐** | **Google identity connect + management UI**: OAuth PKCE, secure store, link to current AI-PACS user, Identity panel + account-menu entry, connected status. **Login untouched.** | Low | No |
| **2** | `GoogleDriveTransport` via the connected identity + manual package move to/from Drive | Low–med | No |
| **3** | Consultation **envelope** + export-to-consultation + import-from-consultation (reuse engine) | Med | Reuses export/import |
| **4** | **CloudSyncEngine** (resumable, off-thread, state machine + conflict) | Med | No |
| **5** | **Assignment + Notification Center** (assign to physician by Google email; assignee notified in-app) | Med | No |
| **6** | Full A→B→A UI (inbox/outbox, compose+assign, review, respond), conflict resolution, consent dialogs, audit | Med | No |
| **7** | Future providers (Telegram/Instagram stubs), web-identity reuse, docs/dev guides, hardening | Low | No |

### 14.1 Phase 0+1 work order (on approval)
1. Add deps; create `modules/Identity/` with `feature_flags.py` (OFF), `models.py`,
   `providers/base.py`, `registry.py`.
2. `database/identity_db.py` (`external_identities`) wired into `init_database()`; test
   patches `DATABASE_FILE`.
3. `secure_store.py` (keyring/DPAPI) + `providers/google/oauth_flow.py` (PKCE/loopback)
   + `providers/google/provider.py` + `identity_service.py`, with unit tests vs mocks.
4. `ui/identity_panel.py` + `ui/account_menu_hook.py`; add the "Connected Accounts"
   entry to the existing account area — additive, V2-styled, flag-gated.
5. Run existing + new tests; prove flag-off = no change and the **server login is
   identical**; demo: log in as today → open Connected Accounts → connect Google →
   see name/email/avatar + Disconnect, with the server user untouched.

> On approval I can also walk the Google Cloud Console setup (§9) live in your open
> Chrome window and validate the OAuth client/scopes before writing code.
