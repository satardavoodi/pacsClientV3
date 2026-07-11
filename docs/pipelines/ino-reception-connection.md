# AI-PACS ⇄ INO Reception — Connection Guide

**Scope:** How the AI-PACS workstation connects to the **INO reception software** (the
web-based admission / reception / reporting system) — the transport channels, the
authentication model, the endpoints used, configuration, and error handling.

**Audience:** engineers integrating or maintaining any INO-backed feature (patient
reception data, report write-back, and the Data Analysis “گزارش پذیرش” dashboard).

---

## 1. Overview

INO is the reception/admission system that owns patient reception records, insurance,
reporting-physician workflow, and admission analytics. AI-PACS talks to the **same INO
server host** over **two logical channels**, kept deliberately separate from the DICOM
imaging channel:

| # | Channel | Default port | Transport | Purpose |
|---|---------|--------------|-----------|---------|
| 1 | **Socket protocol** | `50052` | length-prefixed socket (JSON messages) | Login (mints the JWT), patient list, thumbnails, DICOM metadata, download/workflow |
| 2 | **Reception / Workflow REST API** | `8080` | HTTP + JSON | Reception/patient data, report write-back, comments, user info, admission reports |
| — | *(DICOM, for reference — not INO)* | `104` / `105` | DICOM (C-ECHO/C-MOVE) | Image transfer only |

These three are **different services** and must not be mixed. The socket port (`50052`)
and the reception REST port (`8080`) are separate endpoints on the (possibly same) INO
host; the DICOM port is a third service.

```
                       ┌──────────────────────── INO server host (e.g. 81.16.117.196) ─────────┐
  AI-PACS workstation  │                                                                        │
  ┌───────────────┐    │   ┌──────────────┐   ┌──────────────────────┐   ┌──────────────────┐   │
  │ Login screen  │────┼──▶│ Socket :50052│   │ Reception REST :8080  │   │ DICOM :104/:105  │   │
  │ (user/pass)   │    │   │  "Login" →   │   │ /api/auth/login       │   │ (images only)    │   │
  └──────┬────────┘    │   │  JWT + user  │   │ /api/pacs/...         │   └──────────────────┘   │
         │             │   └──────┬───────┘   │ /api/Reports/...      │                          │
         ▼             │          │           └──────────┬───────────┘                          │
  ┌───────────────┐    │          │  JWT                 │  Authorization: Bearer <JWT>          │
  │SocketTokenMgr │◀───┼──────────┘                      │                                       │
  │(single JWT)   │────┼─────────────────────────────────┘                                       │
  └───────────────┘    └────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Authentication model (single shared JWT)

INO authenticates with a **JWT bearer token**. There is **one token per session**, minted
at login and reused by every INO channel:

1. **Login mints the token.** At the workstation login screen the app sends the user's
   credentials to the INO **socket** server (`send_request('Login', {username, password})`
   in `modules/download_manager/network/socket_client.py`). On success the server returns a
   JWT (`token`, at the response root or under `data.token`) plus a `user` object
   (`full_name`, `username`, `role`, …).
2. **The token is stored once.** It is written into the process-wide singleton
   `SocketTokenManager` (`modules/network/socket_token_manager.py`) via `set_token(token, user)`.
   No password is retained; only the token + user object live in memory.
3. **Every REST call reuses it.** Reception REST callers read the token with
   `get_socket_token_manager().get_token()` and send it as `Authorization: Bearer <JWT>`.
   The **same** token authenticates the socket channel and the port-8080 REST API.
4. **Equivalent REST login exists.** The REST endpoint `POST /api/auth/login`
   (`{username, password}` → `{success, message, token, user}`) mints an equivalent JWT and
   is used as a fallback re-login path (see §5).

**Token properties** (as observed): standard JWT (`header.payload.signature`); payload
claims `id`, `username`, `fullName`/`Name`, `role`, `iat`, `exp`; **lifetime 24 hours**.
There is no server-side logout/revocation on the reception REST service — logout is
client-side (discard the token); a token stays valid until `exp`, after which the user must
re-authenticate. Credentials are the same as the main software / PACS login; the AI-PACS
user is linked to the INO user (the login `user` object also carries the INO user code).

**Security:** the token is a full-access bearer credential. It is held only in memory
(`SocketTokenManager`); the app never puts it in a URL. In the browser build of the INO app
it also appears in a `token` cookie — treat it as a secret everywhere.

---

## 3. Reception REST API (port 8080)

**Base URL resolution** — `modules/network/reception_api_config.get_reception_api_base_url()`,
precedence:

1. Env override `AIPACS_RECEPTION_BASE_URL` / `RECEPTION_API_BASE_URL`.
2. Active **server profile** endpoint for the `reception_api` module (multi-center;
   `PacsClient/utils/server_profiles.py`).
3. `config/reception_api_config.json` (`reception_api_base_url`, else composed
   `scheme://host:port`).
4. Hard-coded default `http://81.16.117.196:8080`.

Request timeout comes from the same config (`request_timeout`, default 8 s). All calls send
`Authorization: Bearer <JWT>` and `Accept: application/json`.

### Endpoints used by AI-PACS

| Method | Path | Used for |
|--------|------|----------|
| `POST` | `/api/auth/login` | REST login → JWT (fallback re-auth) |
| `GET`  | `/api/pacs/patients` | Patient/reception list |
| `GET`  | `/api/pacs/patients/{patientId}` | One patient's reception record (demographics, national ID, insurance, reception details, attachments) |
| `POST/PUT` | `/api/pacs/patients/{id}/comment` | Reception comments |
| `POST` | `/api/pacs/update-report` | Push report / report-status back to INO |
| `GET`  | `/api/pacs/user/{uid}` · `/api/pacs/users/{uid}` | Reporting-physician / user info |
| `GET`  | `/api/Reports/patients-by-service-insurance` | Admission analytics (Data Analysis dashboard) |

**Admission-reports endpoint (Data Analysis):**
`GET /api/Reports/patients-by-service-insurance?startDate=&endDate=&page=&limit=&sortBy=&sortOrder=[&modality=&insuranceType=]`
— Jalali dates `YYYY/MM/DD`; returns `{ success, data:{ receptions[], summary{overall,byModality,byInsurance,…}, pagination }, metadata }`.
See `docs/reports/WEB_ADMISSION_REPORTS_API_DISCOVERY_2026-07-09.md` for the full field map.

---

## 4. Configuration files

| File | Fields | Channel |
|------|--------|---------|
| `config/reception_api_config.json` | `reception_api_base_url`, `reception_api_scheme/host/port`, `request_timeout` | Reception REST (8080) |
| `config/socket_config.json` | `socket_host`, `socket_port` (50052), timeouts, retries | Socket (login/JWT + workflow) |
| `config/servers.json` | `host`, `port` (104/105), `ae_title` | DICOM (images) — **not** INO |
| `config/server_profiles.json` | per-center endpoints incl. `reception_api` | Multi-center routing |

> **Port hygiene (critical):** the socket/reception client must use the socket port
> (`socket_config.json` → `50052`) / the reception base URL (`8080`), **never** the DICOM
> `port` (`105`) from `servers.json`. Feeding the DICOM port into a socket/REST client makes
> the call connect to the wrong service and hang until timeout.

The Settings UI (Server settings) edits the reception base URL via
`ReceptionApiConfig.set_base_url()`; `reload_reception_api_config()` picks up changes.

---

## 5. Resilience & error handling

* **Circuit breaker** (`reception_api_config.py`) — keyed by base URL. After a few
  consecutive failures it opens for a cooldown (default 180 s), then half-opens to probe and
  self-heals on the next success, so a dead/slow INO REST endpoint is not hammered on every
  action. Independent per center (Razi vs Mehr). Disable with `AIPACS_RECEPTION_BREAKER=0`.
* **Session expiry (401/403)** — REST callers surface an auth error. The Data Analysis client
  additionally attempts **one silent re-login** from the saved "remember me" credentials
  (`%APPDATA%/AIPacs/login_config.json` → `POST /api/auth/login`), updates `SocketTokenManager`,
  and retries once; if that fails it shows a clear "session expired — log in again" message.
* **Timeouts / connection errors** — raised as a structured error, logged (`[admission-api]`,
  `[reception-breaker]`), and shown to the user with a retry affordance; the workstation is
  never blocked (all reception I/O runs off the GUI thread).

---

## 6. How the Data Analysis dashboard uses this connection

The Admission Reports tab (`modules/data_analysis/admission_api.py` +
`admission_reports.py`) is a concrete consumer of channel 2:

1. Resolves the base URL via `get_reception_api_base_url()` (INO reception, port 8080).
2. Reads the JWT via `get_socket_token_manager().get_token()` — **reuses** the login token,
   stores nothing.
3. Calls `GET /api/Reports/patients-by-service-insurance` on a **background thread**, with the
   circuit breaker and the 401 re-login fallback above.
4. Renders the returned summary/receptions as Persian KPI cards, charts, and tables.

This is the reference pattern for any new INO-backed feature: **resolve base URL from
`reception_api_config` → attach the shared `SocketTokenManager` JWT as a Bearer header → call
off the GUI thread → honour the breaker and the 401 re-auth path.**

---

## 7. Quick reference

* **Host:** configured INO server (default `81.16.117.196`).
* **Login:** socket `Login` on `:50052` (or REST `POST /api/auth/login` on `:8080`) → JWT (24 h).
* **Token store:** `SocketTokenManager` singleton (in-memory only).
* **Auth header:** `Authorization: Bearer <JWT>` on every `:8080` REST call.
* **Base URL:** `reception_api_config.get_reception_api_base_url()` (env → profile → file → default).
* **Never** use the DICOM port (`105`) for socket/REST; **never** persist the token to disk.

### Related documents
* `docs/reports/WEB_ADMISSION_REPORTS_API_DISCOVERY_2026-07-09.md` — Reports API field map.
* `docs/reports/WEB_ADMISSION_AUTH_TOKEN_TEST_2026-07-09.md` — login/token flow test.
* `docs/reports/ADMISSION_REPORTS_DATA_ANALYSIS_2026-07-09.md` — Data Analysis integration.
* `modules/network/reception_api_config.py` — base-URL resolution + circuit breaker.
* `modules/network/socket_token_manager.py` — shared JWT store.
