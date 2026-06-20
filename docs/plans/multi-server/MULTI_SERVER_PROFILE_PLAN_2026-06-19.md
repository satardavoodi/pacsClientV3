# Multi-Server Profile Management — Investigation & Implementation Plan

**Date:** 2026-06-19
**Status:** Investigation complete; awaiting scope confirmation before implementation.
**Author:** AI-PACS engineering agent (read-only investigation; no source changed yet).

This document is the as-investigated record and design plan for letting a doctor who works
across multiple imaging centers (e.g. **Razi**, **Mehr**) define server *profiles*, pick one at
login, and switch between them safely on the Main Page — with module endpoints, sessions, and
local data kept separate per center.

It is investigation + plan **only**. No production code has been modified.

---

## 0. TL;DR — the most important findings

1. **Why Mehr fails today (root cause).** The entire live workflow — *login, patient search,
   thumbnails, downloads* — runs over the **socket protocol on a single GLOBAL host/port read
   from `config/socket_config.json`** (currently `192.168.2.222:50052`, i.e. Razi's LAN IP).
   - **Login is hard-pinned to that global host.** The login screen has no server selector; the
     "Center" field is only saved as metadata. So you *always authenticate against Razi*, never
     Mehr.
   - When you later pick Mehr and search, the code repoints the socket host to Mehr's IP **but
     reuses the global socket port 50052** (`home_search_service.py:431`). It never uses Mehr's
     `port` from `servers.json` (104) — that field is the **DICOM** port, used only by the
     "Verify" button's C-ECHO, *not* by the real app.
   - So Mehr can only ever work if **`5.57.36.202:50052` is reachable and running the AI-PACS
     socket server**, AND if Mehr accepts the session that was minted by Razi at login. At least
     one of those is almost certainly false. (See §3 for the exact failure modes and the one log
     line we need to confirm which one.)

2. **"Verify" tests the wrong port.** The Verify button does a DICOM C-ECHO to the `servers.json`
   port (104/105). The app does **not** use that port. A green Verify does **not** mean the
   server is usable, and a red Verify does **not** mean it is broken. This is a major source of
   confusion and must be fixed as part of this work.

3. **Module endpoints are global, not per-server.** AI services (breast/boneage/segmentation in
   `servers_address.json`), the Reception API (`reception_api_config.json`), and EchoMind
   (`echomind_settings.json`, whose `api_key` is literally `Ai-pacs/razi245608`) are all single
   global values pinned to Razi.

4. **"Bonj" does not exist in the codebase.** There is no Bonj module or endpoint anywhere.
   "Mammography" and "Eagle Eye" are **local viewer layouts**, not networked services with
   endpoints. So "per-center Bonj / Mammography endpoints" is largely **greenfield** — it is new
   infrastructure, not a re-wiring of something that exists.

5. **Local data would collide between centers.** The DB and all on-disk stores
   (dicom/thumbnails/attachments) are keyed by `PatientID` / `StudyInstanceUID` /
   `series_number` with **no server/source identifier**. Two centers that share a PatientID
   (very common — small integer MRNs) or a StudyInstanceUID will silently overwrite/merge each
   other. This is the single highest-risk area and needs an explicit decision (see §6).

---

## 1. Current architecture (as-built)

### 1.1 The two-port model (critical to understand)

There are **two completely different network paths**, on two different ports:

| Path | Port source | Port today | Protocol | Used by |
|------|-------------|-----------|----------|---------|
| **Socket protocol** | `socket_config.json` → `socket_port` | **50052** (global) | Custom AI-PACS socket | **Login, patient list, thumbnails, downloads — the whole live app** |
| **DICOM** | `servers.json` → `port` | 105 (Razi) / 104 (Mehr) | DIMSE C-ECHO/C-MOVE | **Only the "Verify" button** |

`config/socket_config.json` holds exactly **one** host and **one** port for the socket path:

```json
{ "socket_host": "192.168.2.222", "socket_port": 50052, ... }
```

`config/servers.json` is the *list* the Settings UI manages, but its `port` is the DICOM port:

```json
[ { "name": "razi", "host": "192.168.2.222", "port": "105", "ae_title": "aipacs", "poor_connectivity": false },
  { "name": "mehr", "host": "5.57.36.202",  "port": "104", "ae_title": "aipacs" } ]
```

> There is **no per-server socket port** anywhere. Every server is assumed to expose the socket
> server on the same global 50052.

### 1.2 Login flow

- `PacsClient/login/ui/login_ui.py` — `LoginWindow`. Fields: username, password, **center**,
  Remember Me. No server selector.
- `authenticate_with_socket()` (`login_ui.py:132`) → `socket_service._ensure_client()` →
  `ResumableDicomSocketClient(host=get_socket_host(), port=get_socket_port())` — i.e. **the
  global socket host/port** (Razi).
- On success the token is stored globally via `get_socket_token_manager().set_token(token, user)`.
  There is **one** token manager, not one per server.
- The "Center" string is saved to `%APPDATA%/AIPacs/login_config.json` as metadata only
  (`save_credentials()`, `login_ui.py:169`); it does not affect which host is contacted.

### 1.3 Server switch (post-login, Main Page)

- `PacsClient/pacs/workstation_ui/home_ui/home_search_service.py:430-432`:
  ```python
  socket_port = get_socket_server_settings()['port']           # current global = 50052
  update_socket_server_settings(host=server['host'], port=int(socket_port))  # reuse 50052
  ```
  → mutates the global singleton in `modules/network/socket_config.py`
  (`update_server_settings()`), optionally persisting to `socket_config.json`.
- Consumers that then read the updated global:
  - Patient list / thumbnails: `modules/network/socket_client.py`
    (`PatientListSocketClient.__init__` reads `get_socket_config()`).
  - Download subprocess: `download_process_worker._build_config_dict()` reads
    `get_socket_server_settings()`, and `download_process_entry.py` patches
    `constants.DEFAULT_SOCKET_HOST/PORT` before any `SocketDicomClient` is built.
- `poor_connectivity` is resolved by **matching the active socket host** against `servers.json`
  (`socket_config.is_poor_connectivity_enabled()`), so it already follows the selected server's
  host correctly.

### 1.4 Settings → Server Management UI

- `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py` — the unified Settings page.
  - "AI-PACS Servers" table loads via `get_all_servers()` (`PacsClient/utils/utils.py`), writes
    back with `save_to_json()` → `config/servers.json`.
  - **Verify** = `pynetdicom` C-ECHO to the row's host + **DICOM** port (104/105), *not* the
    socket port. (This is the misleading test from §0.2.)
  - "Poor connectivity" checkbox is stored on the server record in `servers.json`.
  - "AI Service URL" card reads/writes `config/servers_address.json`
    (`servers_config.py`) — **global**, Approve only validates URL format, no network test.
  - "External PACS" card reads/writes `config/external_pacs_servers.json` (separate DIMSE/
    DICOMWeb list + local SCP AE/port). Independent subsystem.
- **There is no concept of an "active server"** in `servers.json`. The active server is simply
  "whatever host is currently in the global `socket_config` singleton."

### 1.5 Module endpoints (all global today)

| Module | Config | Value today | Consumed? | Scope |
|--------|--------|-------------|-----------|-------|
| AI: breast/boneage/segmentation | `servers_address.json` | `192.168.2.222:8002/8003/9000` | Referenced in data-analysis/reporting; **not** called as live inference endpoints in the paths we found | Global |
| Reception API | `reception_api_config.json` | `http://81.16.117.196:8080` (+ env override) | **Yes** — patient data + report update | Global |
| EchoMind | `echomind_settings.json` | `api_key="Ai-pacs/razi245608"`, external LLM | Yes (LLM only) | Global, Razi-stamped |
| Mammography (MG) | none (local manifest `mg_ai_manifest.json`) | n/a | Local files | n/a |
| Eagle Eye | none (viewer layout) | n/a | Local UI | n/a |
| **Bonj** | **not found** | — | — | **Does not exist** |

### 1.6 Local data keying (collision surface)

Path constants in `PacsClient/utils/data_paths.py` (all under one `USER_DATA_ROOT`):

| Store | Path layout | Key | Server in key? |
|-------|-------------|-----|----------------|
| SQLite DB (`dicom.db`) | `USER_DATA_ROOT/database/dicom.db` | `patients.patient_id` UNIQUE, `studies.study_uid` UNIQUE, `series.series_uid` UNIQUE | **No** |
| DICOM downloads (`SOURCE_PATH`) | `patients/dicom/<study_uid>/<series_number>/` | `(study_uid, series_number)` | **No** |
| Thumbnails (`THUMBNAIL_PATH`) | `patients/thumbnails/<study_uid>/<series_number>.png` | `(study_uid, series_number)` | **No** |
| Attachments (`ATTACHMENT_PATH`) | `patients/attachments/<study_uid>/` | `study_uid` | **No** |

**Collision verdict:** Razi and Mehr data **will collide** on any shared `PatientID` or
`StudyInstanceUID`. DICOM Study/Series UIDs are *meant* to be globally unique, so true UID
collisions are rare — but **PatientID collisions are likely** (centers reuse small MRNs), and the
DB's `patient_id UNIQUE` constraint plus `insert_study()` re-association means a same-MRN patient
from Mehr can merge into / overwrite the Razi patient record. This is the core data-separation
risk.

---

## 2. Target design

### 2.1 The `ServerProfile` model (single source of truth)

Introduce one canonical config file, `config/server_profiles.json`, holding a list of profiles.
Each profile owns *everything* that is center-specific:

```jsonc
{
  "active_profile_id": "razi",
  "profiles": [
    {
      "id": "razi",                         // stable, opaque; used as the data-namespace key
      "display_name": "Razi",
      "enabled": true,
      "main": {
        "host": "192.168.2.222",
        "socket_port": 50052,               // the REAL app port (was global)
        "dicom_port": 105,                   // DICOM/C-ECHO (was servers.json "port")
        "ae_title": "aipacs",
        "poor_connectivity": false
      },
      "modules": {                           // optional, per-center endpoints
        "ai_breast":   "192.168.2.222:8002",
        "ai_boneage":  "192.168.2.222:8003",
        "ai_segmentation": "192.168.2.222:9000",
        "reception_api": "http://81.16.117.196:8080",
        "mammography": null,
        "bonj": null
      },
      "status": { "last_checked": null, "reachable": null }
      // auth/session/token is NOT stored here — see §7 (kept in the OS keychain).
    }
    // ...mehr...
  ]
}
```

Key points:
- **`socket_port` becomes per-profile.** This is the fix that lets Mehr live on a different port.
- `dicom_port` is kept distinct and clearly labelled so the Verify/port confusion ends.
- `modules` is a per-profile map; a `null`/absent value = "module not available for this center"
  → shown disabled in the UI.
- `id` is the per-server namespace key for data separation (§6).

### 2.2 A `ServerContext` accessor (the injection point)

Add a small, pure-ish accessor (e.g. `PacsClient/utils/server_context.py`) that all consumers go
through instead of reading globals directly:

- `get_active_profile()` → the current `ServerProfile`.
- `set_active_profile(id)` → switches, updates the socket singleton, resets session/token, emits a
  signal so the UI and module clients re-read.
- `get_socket_target()` → `(host, socket_port)` from the active profile (replaces the global
  `get_socket_server_settings()` read at every call site).
- `get_module_endpoint(name)` → per-profile module URL or `None`.

This is the seam the whole feature hangs on: **change the resolvers, keep the call sites.**

---

## 3. Mehr failure — diagnosis & what to confirm live

**Root cause (architectural, certain):** there is no per-server socket configuration. Login is
pinned to the global socket host (Razi), and switching to Mehr reuses port 50052. Mehr therefore
requires `5.57.36.202:50052` to be open *and* running the socket server *and* to accept a
Razi-minted session.

**Concrete failure modes (one of these is what the user actually hits):**

1. **Login can't even reach Mehr.** You authenticate against Razi's `192.168.2.222` (a private
   LAN IP). From outside Razi's LAN this fails outright; you can never get to a Mehr session.
2. **Port 50052 not open on Mehr's public IP.** Mehr's `5.57.36.202` likely only forwards the
   DICOM port (104) and/or a web port — not the socket 50052. The search then fails with
   "Failed to connect to Socket server at 5.57.36.202:50052" (`home_search_service.py:451-457`).
3. **Mehr's socket server is on a different port.** Even if reachable, if Mehr runs the socket
   server on a port other than 50052, the reused-global-port assumption breaks.
4. **Session/token mismatch.** TCP connects but Mehr rejects the Razi token (one global
   `socket_token_manager`), so requests fail auth after "connecting."

**To confirm which one (single live step):** with the source build running, select Mehr, click
Search, then read the tail of `user_data/logs/app.log` and `download_diagnostics.log`. The
distinguishing evidence:
- `Creating ResumableDicomSocketClient → 5.57.36.202:50052` followed by a **connect timeout /
  refused** ⇒ mode 2/3 (port). 
- Connects but server returns an **auth/permission error** ⇒ mode 4 (token).
- Never even repoints (stays `192.168.2.222`) ⇒ the switch path wasn't taken / wrong entry point.

(In the logs captured 2026-06-19 every socket target was `192.168.2.222:50052`, so a successful
Mehr attempt was never recorded — consistent with "Mehr has never connected.")

**The fix is part of this feature, not a separate patch:** give Mehr its own `socket_port`, make
login able to target the selected profile, and re-authenticate per profile on switch.

---

## 4. Phased implementation plan

Each phase is independently shippable, flag-gated, and preserves the current single-server path
byte-for-byte when only one profile exists. Risk noted per phase.

### Phase 0 — Foundations (low risk, no behavior change)
- Add `config/server_profiles.json` template + `CONFIG_FAMILY_VERSIONS` entry (see §8 build
  rules).
- Add `ServerProfile` dataclass + loader/saver and the `ServerContext` accessor
  (`server_context.py`), pure stdlib, unit-tested in isolation.
- **Migration:** on first run, if `server_profiles.json` is absent, synthesize it from the
  existing `servers.json` + `socket_config.json` + `servers_address.json` so existing users are
  unchanged. Default `active_profile_id` = the host currently in `socket_config.json`.
- Flag `AIPACS_SERVER_PROFILES` (default off in this phase) so nothing reads the new model yet.

### Phase 1 — Route the socket layer through the active profile (medium risk)
- Replace the global `get_socket_server_settings()` reads in the **socket host/port resolution**
  with `ServerContext.get_socket_target()` (host **and** per-profile `socket_port`).
- Keep `update_socket_server_settings()` working (it writes the active profile's live target).
- Verify the 3 consumers still work: patient list, thumbnails, download subprocess.
- Single-profile users: identical behavior (one profile, same host/port).

### Phase 2 — Login server dropdown (medium risk)
- Add a profile **dropdown** to `LoginWindow` (above username), populated from
  `server_profiles.json`, default = `active_profile_id`. Manual entry still possible via Settings.
- Selecting a profile sets the active profile **before** `authenticate_with_socket()` so login
  targets the chosen center.
- Clear messaging if the chosen server is unreachable ("Could not connect to <Razi> at host:port").

### Phase 3 — Settings → Server Profiles (medium risk)
- Extend the existing Server Management card to edit a full profile: name, host, **socket port**,
  **DICOM port** (clearly separated), AE title, connectivity profile, enabled/disabled.
- **Fix Verify:** test the **socket port** (the real app path) as the primary check, and keep the
  DICOM C-ECHO as a secondary, clearly-labelled "DICOM C-ECHO" test. Never present one as the
  other.
- Per-profile **module endpoints** sub-section (AI breast/boneage/seg, reception, mammography,
  bonj). Writing these updates the active profile's `modules` map.

### Phase 4 — Module endpoint routing (medium risk; partly greenfield)
- Make the consumers that *exist* read per-profile: AI service URLs (`servers_address.json`
  consumers), Reception API (`reception_api_config.py` resolver), EchoMind center/api_key.
- For modules that **don't exist yet** (Bonj; networked Mammography): define the endpoint slot in
  the profile now, mark "unavailable" in the UI, and wire the client when/if the module is built.

### Phase 5 — Main Page server switching (medium/high risk)
- Add a visible **active-server indicator + switcher** on the Main Page.
- On switch: set active profile → reset session/token → repoint socket → refresh patient list →
  re-resolve module endpoints. Must be deliberate (confirm if a download is in flight).
- Reuse the existing connection-indicator UI.

### Phase 6 — Per-server data separation (HIGH risk — needs decision in §6)
- Implement the chosen separation strategy (namespace key = profile `id`).
- This is the only phase that touches the clinical data layer; gate it hard, migrate carefully,
  and validate that single-server users' existing on-disk data is untouched.

### Phase 7 — Build / installer / release-parity (required, not optional)
- Ship the new config template, bump `CONFIG_FAMILY_VERSIONS`, add to the installer's
  `[Files]` + installation-profile writers, mirror any plugin-mirrored files, and pass
  `tests/code/builder` + `tests/code/runtime` parity guards (see §8).

---

## 5. Auth / session handling

- Replace the single global token with a **per-profile session store**, keyed by profile `id`.
- On `set_active_profile`: drop the in-memory active token, load that profile's stored session if
  still valid, else prompt login for that center with a clear message ("Sign in to <Mehr>").
- **Credentials/tokens stored safely:** reuse the existing `secure_store` (OS keychain/DPAPI) used
  by the Identity module — *not* the DB, *not* plaintext JSON. Profiles JSON holds no secrets.
- Switching servers must never reuse the wrong token — the token is fetched *through* the active
  profile, never from a process-global.

---

## 6. Data separation — DECISION REQUIRED

The same PatientID/StudyUID can exist on two centers. Options, cheapest → safest:

- **Option A — Namespace everything by profile `id` (recommended, safest).**
  - DB: add a `source_profile_id` column to `patients`/`studies` (+ index); make uniqueness
    `(source_profile_id, patient_id)` / `(source_profile_id, study_uid)`.
  - Disk: prefix all stores with the profile id →
    `patients/<profile_id>/dicom/<study_uid>/...`, same for thumbnails/attachments.
  - Pro: no collisions ever. Con: schema migration + path migration for existing data; highest
    effort; touches the clinically-protected data layer (must be gated + golden-compared).

- **Option B — Lightweight tag, shared paths (medium).**
  - Add `source_profile_id` to DB rows for *filtering/ownership* but keep disk paths keyed by UID.
  - Pro: smaller change, fixes the "whose patient is this" ambiguity in lists. Con: on-disk files
    still collide if UIDs actually clash (rare for true DICOM UIDs, but PatientID-derived paths
    would need care).

- **Option C — Assume global UID uniqueness, separate PatientID only (cheapest).**
  - Rely on DICOM Study/Series UID global uniqueness for disk; only disambiguate the *patient
    list* view by profile. Con: leaves a latent overwrite risk if two centers ever share a UID;
    does not fully satisfy acceptance criterion "Same PatientID from different servers does not
    collide."

> Recommendation: **Option A**, implemented in Phase 6 behind a flag, with a migration that moves
> existing (single-server) data under its profile id namespace and a golden before/after compare.
> This is the only option that fully meets the stated acceptance criteria, but it is also the
> riskiest and should be its own carefully-validated work item.

---

## 7. Connection testing (redesign)

For each profile, "Test Connection" should test what the app actually uses:
1. **Socket** (primary): open the socket to `host:socket_port`, attempt a lightweight handshake.
   Success here is what predicts a working login/search/download.
2. **DICOM C-ECHO** (secondary, optional): the existing pynetdicom test to `host:dicom_port`,
   clearly labelled as DICOM.
3. **Module endpoints** (optional): reachability of each configured module URL.
- Show per-target success/failure. Log the reason (timeout/refused/auth) **without** secrets.

---

## 8. Build / installer / release-parity requirements (hard rules)

Per `CLAUDE.md` "New module / new feature-flag checklist":
- New config file `config/server_profiles.json`: ship the template under `config/`, add the family
  to `CONFIG_FAMILY_VERSIONS`, and bump it whenever the schema grows.
- Add the file to `AIPacs_Setup.iss` `[Files]` and any installation-profile writers.
- If any edited file is plugin-mirrored (`modules/education`, run_cd, download-manager socket
  client), run `tools/dev/sync_plugin_mirrors.py` then `verify_plugin_mirrors.py`.
- Run `python -m pytest tests/code/builder tests/code/runtime -q -p no:debugging` — the parity
  tests enforce the above. Build on `E:` / a fresh `main` (see the stale-branch guard) so the
  installer actually contains these changes.

---

## 9. Validation checklist (maps to the request's acceptance criteria)

- [ ] Add Razi + Mehr profiles in Settings; both persist to `server_profiles.json`.
- [ ] Login dropdown lists profiles; selecting Razi logs in against Razi.
- [ ] Select Mehr → Test Connection shows socket result for `5.57.36.202:<mehr socket port>`.
- [ ] Mehr failure reason is logged (timeout/refused/auth) without secrets; documented here.
- [ ] Configure Razi/Mehr Mammography + Mehr Bonj endpoints; stored on the right profile.
- [ ] Main Page switch Razi↔Mehr: patient list refreshes from the selected center; module
      endpoints follow; active server name visible.
- [ ] Same PatientID on both centers does not collide (Phase 6 / Option A).
- [ ] Single-server user with only the migrated default profile behaves exactly as before.

---

## 10. Risks & guardrails

- **Clinical data layer (Phase 6)** is the highest risk — gate it, migrate carefully, golden
  compare, never delete existing data.
- **Do not break the current login** — Phases 0-1 keep single-profile behavior identical;
  the dropdown defaults to the migrated profile.
- **FAST viewer / VTK, downloads, overlays, measurements** are untouched by this feature; it is a
  config/identity/networking change, not a viewer change.
- **Verify-port confusion** must be fixed early (Phase 3) or users will keep mis-reading server
  health.
- **Greenfield modules (Bonj, networked Mammography)** — set the config slots now, but be explicit
  with the user that the clients don't exist yet.

---

## 11. Open questions for the user (decisions needed before building)

1. **Scope/sequencing:** start with the smallest useful slice (Phase 1-3: per-profile socket port
   + login dropdown + fixed Settings/Verify — which directly unblocks Mehr), or design/build the
   full system through Main-Page switching first?
2. **Data separation (§6):** Option A (full per-profile namespacing — safest, biggest), B
   (DB tag only), or C (cheapest, latent risk)? This drives Phase 6 size.
3. **Mehr specifics:** what port does Mehr's **socket** server actually listen on, and is it open
   on `5.57.36.202` from where the doctor connects? (Needed to verify the fix end-to-end.)
4. **Bonj / Mammography:** are these real networked services with endpoints we should integrate,
   or just labels for now? (Codebase has neither today.)
