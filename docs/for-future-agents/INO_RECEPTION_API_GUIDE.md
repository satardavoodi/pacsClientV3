# INO Reception / PACS API — Integration Guide

**Audience:** any agent or developer who needs to talk to the **INO** reception (RIS)
system and the PACS backend that AI-PACS integrates with.
**Status:** written 2026-07-10 from **live verification** against a production center
(`81.16.117.196`) plus the vendor doc `ASSIGN_CLIENT_GUIDE_FA.md`. Every endpoint below
is marked **VERIFIED** (observed working live) or **PER-SPEC** (documented by the vendor,
not yet exercised from this workstation).

> **Read §2 (identifiers) and §8 (traps) before writing any code.** Almost every bug in
> this integration comes from those two sections — especially the **port** and the
> **two different reception ids**.

---

## 1. Mental model — three services, three ports

INO is **not one server**. It is three distinct services, and they do not share routes.
Sending a request to the right path on the wrong port is the single most common failure.

| # | Service | Default port | Protocol | What lives here |
|---|---------|--------------|----------|-----------------|
| **A** | **RIS / Reception REST** (the web app's API) | **8080** | HTTP + JSON | Users & personnel, imaging worklists, report content, report approval flags, admission/financial reports |
| **B** | **PACS HTTP** | **8000** | HTTP + JSON | **Study assignment** (`/api/patients/{id}/assign`), assignable-user aggregation |
| **C** | **PACS Socket** | **50052** | TCP + length-framed JSON | Login, realtime broadcasts (`study_assigned`, `patient_list_updated`), `AssignStudy`, image/thumbnail transport |

The INO **web frontend** (port 80, e.g. `http://81.16.117.196/reportReception`) is a
Next.js SPA that calls service **A**. It is a useful oracle: when you don't know an
endpoint, open the page and read its network traffic or JS bundle.

```
                 ┌─────────────────────────┐
  Browser  ─────►│  INO web app  (:80)     │
                 └───────────┬─────────────┘
                             │ REST
                 ┌───────────▼─────────────┐         ┌──────────────────────┐
  AI-PACS ──────►│  A: RIS Reception :8080 │────────►│  B: PACS HTTP :8000  │
        │        └─────────────────────────┘ internal└──────────┬───────────┘
        │                                                       │
        └──────────────── C: PACS Socket :50052 ────────────────┘
                          (framed JSON, broadcasts)
```

**Important:** the RIS assign action (`PATCH /api/Reports/reception/{id}/radiologist`
on **A**) is only a *bridge* — RIS itself then calls **B**'s
`PUT /api/patients/{ReceptionID}/assign`. A PACS client (like AI-PACS) should talk to
**B** or **C** directly, not go through the RIS bridge.

---

## 2. Identifiers — the #1 trap

A reception has **two different ids**, and they are not interchangeable.

| Name | Type | Example | Used by |
|------|------|---------|---------|
| `receptionID` | **numeric** (5 digits) | `49628` | PACS `PatientID`, `/api/pacs/*`, `/api/Reports/reception/{id}/*`, PACS `/api/patients/{id}/assign`, socket `patient_id` |
| `receptionId` | **ObjectId** (24 hex) | `6a4de81218a091772b582325` | `/api/imagingWorkflow/{id}/...` (the **workflow** id), `singleReportPatient?id=` |

Rules of thumb:

* **`PatientID` in PACS == `ReceptionID` in RIS** — the same 5-digit number.
* Anything under **`/api/imagingWorkflow/`** wants the **ObjectId workflow id**.
* Anything under **`/api/pacs/`**, **`/api/Reports/reception/`**, or PACS
  **`/api/patients/`** wants the **numeric receptionID**.
* Worklist rows return **both** (`receptionID` numeric and `receptionId` ObjectId), so
  the worklist is how you convert one to the other (see §5.2).

Also: never confuse a **personnel `_id`** (24-hex, the assignee) with a reception id.

---

## 3. Authentication

One JWT covers service **A**; service **C** (socket) issues/accepts the same style of
token. Get it once, reuse it, refresh on 401.

### 3.1 Login (VERIFIED)

```http
POST http://{host}:8080/api/auth/login
Content-Type: application/json

{ "username": "<user>", "password": "<password>" }
```

**Response 200:**

```json
{
  "success": true,
  "message": "...",
  "token": "eyJhbGciOi...",
  "user": { "id": "...", "username": "...", "full_name": "...", "role": "..." }
}
```

### 3.2 Using the token

Every subsequent call to **A** (and **B**):

```http
Authorization: Bearer {token}
Accept: application/json
Content-Type: application/json
```

Optional on writes: `X-User-Id: {assigner_user_id}` (who performed the action).

### 3.3 Lifetime & failure modes

* The token is a stateless JWT, ~**24 h**. There is **no server-side logout**.
* An expired/garbage token gives **401**, or a **403 with `jwt malformed`**.
  **A 403 here almost always means a stale token, not a permissions problem.**
  Re-login and retry before concluding the user lacks a role.
* In AI-PACS, do **not** log in again yourself — reuse the app's token via
  `modules/network/socket_token_manager.py` → `get_socket_token_manager().get_token()`.

> **Never hard-code credentials.** In AI-PACS the token comes from the logged-in
> session. For ad-hoc scripts, take user/password from env vars.

---

## 4. Base-URL resolution (how AI-PACS does it)

| Base | Source of truth | Helper |
|------|-----------------|--------|
| **A** RIS `:8080` | `config/reception_api_config.json` (Settings → *Reception / Workflow API*) | `modules/network/reception_api_config.py` → `get_reception_api_base_url()` |
| **B** PACS `:8000` | `config/ino_assignment_config.json` → `assignment_api_base_url`; **empty ⇒ auto-derived** as `http://{reception-host}:8000` | `modules/network/ino_assignment.py` → `get_ino_assignment_base_url()` |
| **C** Socket `:50052` | `config/socket_config.json` | `modules/network/socket_config.py` → `get_socket_config()` |

> **Do NOT take the port from `config/servers.json`** — that `port` field is the **DICOM**
> port (e.g. `105`). Feeding it to a REST/socket client makes calls hang until timeout.

---

## 5. Service A — RIS Reception REST (`:8080`)

### 5.1 Users & personnel

INO exposes eligible users through **two** endpoints (there is no single unified one on
this port — see §8.2).

#### `GET /api/personnel` — physicians / staff  **(VERIFIED)**

Returns the center's personnel (mostly physicians/radiologists).

```json
[
  {
    "_id": "69f314c684663b7ae6e6318a",
    "PersonnelCode": "...",
    "FirstName": "وحید",
    "LastName": "علیزاده",
    "PersonnelType": "پزشک",
    "Speciality": "...",
    "Position": "...",
    "Department": "...",
    "IsActive": true,
    "ContactInfo": { "Email": "..." }
  }
]
```

* Use `_id` as the **assignee id** (`assignee_id` / `radiologistId`).
* Display name = `FirstName + " " + LastName`.
* Filter on `IsActive`.

#### `GET /api/AdminUser/getCenterUsers` — center users  **(VERIFIED)**

Returns all center user accounts (physicians **and** secretaries/typists).

```json
[
  {
    "_id": "687e...",
    "User": "reza",
    "FullName": "رضا ...",
    "EnglishName": "...",
    "PersonnelID": "...",
    "roles": { "Name": "typist" },
    "NID": "...",
    "InoUserCode": "...",
    "Deactive": false
  }
]
```

* Active = `Deactive == false` (note the inverted flag).
* Role name at `roles.Name`.

> These are two **different populations**. Show them as two groups (Physicians vs
> Users/Secretaries) — that's what the AI-PACS assign dialog does.

### 5.2 Imaging worklists

#### `GET /api/imagingWorkflow/workflow/reporting`  **(VERIFIED)**

The reporting worklist. **This is also the `receptionID` → `receptionId` (workflow id)
converter.**

Optional filter: `?receptionID={numeric}`

Row shape:

```json
{
  "receptionId":  "6a4de81218a091772b582325",   // ObjectId = workflow id
  "receptionID":  49628,                         // numeric reception number
  "date": "...", "time": "...",
  "modality": { ... },
  "patient":  { ... },
  "registeredBy": { "id": "...", "fullName": "...", "username": "..." },
  "typingUser": { ... },
  "referrerPhysician": { ... },
  "services": [ ... ],
  "voiceAttachmentsCount": 0,
  "workflowStatus": "...",
  "report": { "status": "...", "reportDate": "...", "radiologist": null }
}
```

Also available: `GET /api/imagingWorkflow/workflow/waiting-appointment`.

#### Resolving a workflow id (the pattern AI-PACS uses)

```python
GET {A}/api/imagingWorkflow/workflow/reporting?receptionID=49628
# → pick the item whose numeric `receptionID` matches exactly, take its `receptionId`
```

Implementation: `modules/network/ino_report_workflow.py::resolve_workflow_id()`.

### 5.3 Report content

| Endpoint | Method | Notes |
|---|---|---|
| `/api/pacs/report/{receptionID}` | GET | **VERIFIED** — returns `{ success, data }`; report body lives under `data` |
| `/api/pacs/patients/{receptionID}` | GET | patient/reception detail |
| `/api/pacs/update-report` | POST | **VERIFIED** — writes report content + status |

```http
POST {A}/api/pacs/update-report
{ "receptionId": 49628, "content": "...", "findings": "...", "status": "completed" }
```

> ⚠️ **`update-report` writes only `report.status`. It IGNORES `approvalFlags` in the
> body.** This is the cause of "I changed the status in AI-PACS but INO still shows the
> old one." See §6.

### 5.4 Report approval flags — what INO actually displays

`PATCH /api/imagingWorkflow/{workflowId}/workflow/report/approval-flags` **(VERIFIED)**

```http
PATCH {A}/api/imagingWorkflow/6a4de81218a091772b582325/workflow/report/approval-flags
{ "physicianApproved": true, "secretaryApproved": false }
```

Related (present in the frontend, PER-SPEC for us):

* `PATCH /api/imagingWorkflow/{id}/workflow/report/status` — transition state machine
* `GET  /api/imagingWorkflow/{id}/workflow/report/logs`
* `GET  /api/imagingWorkflow/{id}/workflow/report/status/history`
* `POST /api/imagingWorkflow/{id}/workflow/report/revert`

### 5.5 Assignment bridge (RIS side)

`PATCH /api/Reports/reception/{receptionID}/radiologist` **(VERIFIED — read from the
frontend's own code)**

```http
PATCH {A}/api/Reports/reception/49628/radiologist
{ "radiologistId": "69f314c684663b7ae6e6318a", "radiologistName": "دکتر وحید علیزاده" }
```

This is what the INO web worklist calls. RIS then internally calls PACS **B**'s
`PUT /api/patients/{ReceptionID}/assign`.

* Radiologist **only** — there is **no typist endpoint** in the RIS worklist.
* **A PACS client should prefer B/C directly** (they support both roles + `study_uid`
  scoping + the targeted `study_assigned` broadcast).

### 5.6 Admission / financial reports

`GET /api/Reports/patients-by-service-insurance` **(VERIFIED)** — powers the AI-PACS
Data-Analysis "گزارش پذیرش" dashboard. Jalali dates; modality codes `1=CT 2=MRI 3=US 4=XR`.
Client: `modules/data_analysis/admission_api.py`.

---

## 6. Report status ⇄ approvalFlags (the big gotcha)

**INO renders the patient/report status from `report.approvalFlags`, not from the raw
`report.status` string.** So writing only `status` via `update-report` changes nothing
visible on the INO side.

To make a status change actually appear in INO you must do **both**:

1. `POST /api/pacs/update-report` — writes the content + `report.status`.
2. `PATCH /api/imagingWorkflow/{workflowId}/workflow/report/approval-flags` — writes the
   booleans INO displays. Requires resolving the **workflow ObjectId** first (§5.2).

### Status → flags mapping (as implemented)

`modules/network/socket_report_status_service.py::approval_flags_for_status()`

| Internal status | `physicianApproved` | `secretaryApproved` |
|---|:---:|:---:|
| `pending` | ❌ | ❌ |
| `awaiting_physician_approval` | ❌ | ❌ |
| `awaiting_approval` | ❌ | ❌ |
| `physician_approved` | ✅ | ❌ |
| `awaiting_secretary_approval` | ✅ | ❌ |
| `secretary_approved` | ✅ | ✅ |
| `completed` | ✅ | ✅ |
| `archived` | ✅ | ✅ |
| *(unknown)* | ❌ | ❌ (safe default) |

A **downgrade** must *clear* the flags — that's why the mapping is computed from the
target status rather than only ever setting flags true.

**Client:** `modules/network/ino_report_workflow.py` →
`sync_report_approval_for_status(reception_id, status)` (resolves the workflow id, then
PATCHes the flags). Flag: `AIPACS_INO_APPROVAL_SYNC` (default ON).

---

## 7. Service B & C — Study assignment

### 7.1 PACS HTTP (`:8000`) — REST  **(PER-SPEC; the port is the fix for the 404)**

```http
PUT  http://{pacs-host}:8000/api/patients/{ReceptionID}/assign
Authorization: Bearer {token}
X-User-Id: {assigner_id}          # optional

{
  "assign_type":     "radiologist",   // or "typist"
  "assignee_id":     "69f314c684663b7ae6e6318a",
  "assignee_name":   "دکتر وحید علیزاده",
  "assignee_source": "ris_personnel", // pacs | ris_personnel | ris_user
  "study_uid":       ""               // "" = all studies of the reception
}
```

**Response:**

```json
{ "success": true, "patient_id": "49628", "assign_type": "radiologist",
  "assignee_id": "...", "modified_count": 2, "timestamp": "..." }
```

Other routes on **B**:

| Endpoint | Purpose |
|---|---|
| `GET /api/patients/{ReceptionID}/assign` | read current assignment `{ assignment: { radiologist: {...}, typist: {...} } }` |
| `GET /api/assign/users?source=all&assign_type=radiologist&search=&limit=200` | unified assignable-user list (aggregates PACS users + RIS personnel + RIS AdminUser) |

**Unassign:** there is **no dedicated unassign endpoint**. Clear an assignment by sending
the same `PUT` with an **empty `assignee_id`**. Treat the server's answer as
authoritative — if it rejects the clear, do **not** show the UI as unassigned.

`assignee_source` values:

| Value | Meaning |
|---|---|
| `pacs` | local PACS MongoDB `users` |
| `ris_personnel` | RIS `Personnel._id` (usually a radiologist) → from `/api/personnel` |
| `ris_user` | RIS `AdminUser._id` (usually a typist) → from `/api/AdminUser/getCenterUsers` |

### 7.2 PACS Socket (`:50052`) — framed JSON  **(PER-SPEC)**

**Framing:** `[4-byte big-endian length][UTF-8 JSON]`. This is the same socket AI-PACS
already uses for images, so a client that is logged in can assign **without** the PACS
HTTP service being exposed. **AI-PACS defaults to this transport.**

```jsonc
// assign
{ "endpoint": "AssignStudy", "token": "<jwt>",
  "params": { "patient_id": "49628", "assign_type": "radiologist",
              "assignee_id": "...", "assignee_name": "...",
              "assignee_source": "ris_personnel", "study_uid": "" } }

// list assignable users
{ "endpoint": "GetAssignUsers", "token": "<jwt>",
  "params": { "source": "all", "assign_type": "radiologist", "limit": 200 } }

// subscribe to realtime events
{ "endpoint": "SubscribeToEvents", "token": "<jwt>",
  "params": { "event_types": ["study_assigned", "patient_list_updated"] } }
```

### 7.3 Realtime broadcasts

After any assignment the server emits **`study_assigned`**, targeted at the clients where
the **assignee** is logged in (falls back to a broadcast to everyone if the assignee is
offline — so **filter by `assignee_id` client-side**):

```json
{ "type": "broadcast", "event_type": "study_assigned", "targeted": true,
  "data": { "patient_id": "49628", "patient_name": "...", "assign_type": "radiologist",
            "assignee_id": "...", "assignee_name": "...", "assigned_by": "...",
            "modified_count": 2 } }
```

Plus `patient_list_updated` to everyone (refresh the row/list).

---

## 8. Traps — read this before debugging

### 8.1 The port mistake (cost us the most time)

`PUT /api/patients/{id}/assign` and `GET /api/assign/users` **do not exist on `:8080`**.
Hitting them there returns an Express HTML 404 page:

```
Cannot PUT /api/patients/49639/assign
```

They live on **`:8000`** (service B). If you see `Cannot <VERB> <path>` in an HTML body,
you are on the **wrong port**, not looking at a missing feature.

### 8.2 `/api/assign/users` 404s on `:8080` — and the frontend knows it

On the reporting worklist the INO frontend probes a **fallback chain** to find users:

```
/api/assign/users → /api/personnel → /api/AdminUser/getCenterUsers
                  → /api/users → /api/pacs/radiologists
                  → /api/pacs/reporting-physicians → /api/pacs/physicians
```

Don't be fooled into thinking `/api/assign/users` is "the" endpoint on the RIS port. On
`:8080` use `/api/personnel` + `/api/AdminUser/getCenterUsers`.

### 8.3 `update-report` silently ignores `approvalFlags`

See §6. Symptom: status changes in AI-PACS, INO web still shows the old state. Proof
observed live: a reception with `report.status = awaiting_physician_approval` **while**
`physicianApproved = secretaryApproved = true`.

### 8.4 403 `jwt malformed` is usually a **stale token**

`/api/personnel` and `/api/AdminUser/getCenterUsers` returned **403** with an old token
and **200** immediately after a fresh login. Re-authenticate before blaming permissions.

### 8.5 The two reception ids

See §2. `/api/imagingWorkflow/{...}` needs the **ObjectId**; everything else needs the
**numeric**. Passing the wrong one gives 400/404 or silently matches nothing.

### 8.6 Don't use the DICOM port

`config/servers.json` `port` (e.g. `105`) is **DICOM**. REST is `:8080`/`:8000`, socket is
`:50052` (`config/socket_config.json`).

### 8.7 Discovering unknown endpoints

The INO frontend is the best oracle. Open the relevant page (e.g. `/reportReception`) and
either read its network traffic or grep its JS bundle for the call — that is exactly how
`PATCH /api/Reports/reception/{id}/radiologist` was found:

```js
await axiosConfig.axiosClient.patch(
  "/Reports/reception/".concat(selectedReceptionId, "/radiologist"),
  { radiologistId: selectedRadiologist.value, radiologistName: selectedRadiologist.label });
```

---

## 9. Recipes

### 9.1 Minimal Python client

```python
import os, requests

BASE = "http://81.16.117.196:8080"          # service A

def login() -> str:
    r = requests.post(f"{BASE}/api/auth/login", json={
        "username": os.environ["INO_USER"],
        "password": os.environ["INO_PASS"],
    }, timeout=10)
    r.raise_for_status()
    return r.json()["token"]

def H(tok): return {"Authorization": f"Bearer {tok}",
                    "Content-Type": "application/json"}

tok = login()

# 1) assignable physicians
people = requests.get(f"{BASE}/api/personnel", headers=H(tok), timeout=10).json()
people = people if isinstance(people, list) else people.get("data", [])

# 2) numeric receptionID -> workflow ObjectId
wl = requests.get(f"{BASE}/api/imagingWorkflow/workflow/reporting",
                  params={"receptionID": 49628}, headers=H(tok), timeout=10).json()
rows = wl if isinstance(wl, list) else wl.get("data", [])
wid = next(r["receptionId"] for r in rows if str(r["receptionID"]) == "49628")

# 3) make a status actually show up in INO (content + the flags it renders)
requests.post(f"{BASE}/api/pacs/update-report", headers=H(tok), timeout=10, json={
    "receptionId": 49628, "content": "...", "findings": "...", "status": "completed"})
requests.patch(f"{BASE}/api/imagingWorkflow/{wid}/workflow/report/approval-flags",
               headers=H(tok), timeout=10,
               json={"physicianApproved": True, "secretaryApproved": True})
```

### 9.2 Assign a radiologist (PACS REST, service B)

```python
PACS = "http://81.16.117.196:8000"
requests.put(f"{PACS}/api/patients/49628/assign", headers=H(tok), timeout=10, json={
    "assign_type": "radiologist",
    "assignee_id": "69f314c684663b7ae6e6318a",
    "assignee_name": "دکتر وحید علیزاده",
    "assignee_source": "ris_personnel",
    "study_uid": "",
})
# unassign = same call with "assignee_id": ""
```

### 9.3 Assign over the socket (service C)

```python
import json, socket, struct

def call(host, port, payload, timeout=8):
    with socket.create_connection((host, port), timeout=timeout) as s:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        s.sendall(struct.pack(">I", len(body)) + body)
        n = struct.unpack(">I", s.recv(4))[0]
        buf = b""
        while len(buf) < n:
            buf += s.recv(min(65536, n - len(buf)))
        return json.loads(buf.decode("utf-8"))

call("81.16.117.196", 50052, {
    "endpoint": "AssignStudy", "token": tok,
    "params": {"patient_id": "49628", "assign_type": "radiologist",
               "assignee_id": "69f31...", "assignee_name": "…",
               "assignee_source": "ris_personnel", "study_uid": ""}})
```

---

## 10. Where AI-PACS implements this

| Concern | File |
|---|---|
| RIS base URL + timeout | `modules/network/reception_api_config.py` |
| Session token (reuse — don't re-login) | `modules/network/socket_token_manager.py` |
| Socket host/port | `modules/network/socket_config.py` |
| Report status → approvalFlags mapping | `modules/network/socket_report_status_service.py::approval_flags_for_status` |
| Workflow-id resolve + approval-flags PATCH | `modules/network/ino_report_workflow.py` |
| Assignment REST/socket client + façade | `modules/network/ino_assignment.py` |
| Socket `AssignStudy` transport | `modules/network/ino_assignment_socket.py` |
| Assignment state model / statuses | `modules/network/ino_assignment_models.py` |
| Local assignment history (`server_ok`) | `modules/network/ino_assignment_history.py` |
| Assignment notifications | `modules/network/ino_notifications.py` |
| Admission/financial reports client | `modules/data_analysis/admission_api.py` |
| Settings UI (bases, transport, enable) | `PacsClient/pacs/workstation_ui/settings_ui/server_settings.py` |

**Isolation rule:** the `ino_assignment*` modules import only `reception_api_config`,
`socket_token_manager`, `socket_config` and their own siblings — **never** the
consultation / Google-Drive / payment / Identity stack. This is enforced by an AST guard
in `tests/code/network/test_ino_assignment.py`. Keep it that way.

**Config files:** `config/reception_api_config.json`, `config/ino_assignment_config.json`
(`enabled`, `assignment_api_base_url`, `transport: socket|rest`), `config/socket_config.json`.

---

## 11. Verified vs. not

| Item | Status |
|---|---|
| `POST /api/auth/login` → token | ✅ VERIFIED live |
| `GET /api/personnel` (10 rows) | ✅ VERIFIED live |
| `GET /api/AdminUser/getCenterUsers` (43 rows) | ✅ VERIFIED live |
| `GET /api/imagingWorkflow/workflow/reporting` (+ `?receptionID=`) | ✅ VERIFIED live |
| `GET /api/pacs/report/{id}` | ✅ VERIFIED live |
| `POST /api/pacs/update-report` | ✅ VERIFIED live |
| `PATCH .../workflow/report/approval-flags` | ✅ VERIFIED live |
| `GET /api/Reports/patients-by-service-insurance` | ✅ VERIFIED live |
| `PATCH /api/Reports/reception/{id}/radiologist` | ✅ VERIFIED (read from the live frontend code) |
| `/api/assign/users` + `PUT /api/patients/{id}/assign` **on `:8080`** | ❌ **404 — they are NOT here** |
| PACS **`:8000`** assign endpoints | ⚠️ **PER-SPEC** — documented by the vendor; **not yet exercised** from this workstation (a browser can't reach `:8000` cross-port). Confirm with one live assign. |
| Socket `AssignStudy` / `GetAssignUsers` on `:50052` | ⚠️ **PER-SPEC** — implemented and default-on in AI-PACS; needs one live confirmation. |
| Assignment **lifecycle status** (active/completed/deactivated) | ❌ **No INO endpoint exists.** Only assign / reassign / clear are server-backed. AI-PACS records the other states locally and labels them as local — do not present them as server-confirmed. |

---

## 12. Quick checklist for a new integration

1. Get the base URLs right — **A `:8080`**, **B `:8000`**, **C `:50052`**. Never
   `servers.json`'s DICOM port.
2. `POST /api/auth/login` once; reuse the token; on **401/403 `jwt malformed`**, re-login.
3. Know which id you hold — **numeric `receptionID`** vs **ObjectId workflow id** (§2).
4. Users: `/api/personnel` (physicians) **and** `/api/AdminUser/getCenterUsers`
   (users/secretaries) — two groups, not one list.
5. Changing a report status? Do **both** `update-report` **and** the `approval-flags`
   PATCH, or INO won't show it (§6).
6. Assigning? Prefer PACS **`:8000`** REST or the **`:50052`** socket. Clear an assignment
   with an empty `assignee_id`. Trust only the server's answer.
7. Want realtime? `SubscribeToEvents` → handle `study_assigned` (filter on `assignee_id`)
   and `patient_list_updated`.
8. Stuck on an unknown endpoint? Read the INO web app's network traffic / JS bundle (§8.7).

---

### Related docs

* `docs/pipelines/internal-assignment-foundation.md` — the AI-PACS internal-assignment
  feature as built (UI, statuses, notifications, build/packaging).
* `docs/reports/AINO_RECEPTION_STATUS_SYNC_REVIEW_2026-07-09.md` — the status-sync
  root-cause investigation.
* `ASSIGN_CLIENT_GUIDE_FA.md` (vendor) — the assign + socket contract.
