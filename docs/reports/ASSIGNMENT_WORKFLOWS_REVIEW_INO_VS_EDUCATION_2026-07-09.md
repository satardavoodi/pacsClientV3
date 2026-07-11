# Assignment Workflows — INO Reception (internal) vs Education/Consultation (external)

**Date:** 2026-07-09
**Type:** Review only — **no code merged or modified.** Purpose: understand both assignment systems
before deciding how internal-center vs external-center assignment should be separated/implemented.
**Sources:** the attached `ASSIGN_CLIENT_GUIDE_FA.md` (INO/Aino assignment) + a full code trace of the
existing Education/Consultation assignment in this repo.

---

## 0. One-line distinction

* **INO Reception assignment = "who reports this case", inside one center.** Assign a **radiologist**
  or **typist** (an INO/RIS user) to a reception's studies, over INO's own PACS channels, with a
  realtime socket notification. **Full patient data, same center.** — *Not implemented in AI-PACS yet.*
* **Education/Consultation assignment = "send this case to another physician", across centers/users.**
  Hand a **de-identified** case to another AI-PACS physician (possibly a different center or someone
  who doesn't use INO at all), via the AI-PACS Identity + Google Drive hub (external) or a Laravel
  registry (internal), with its own state machine. — *Already implemented.*

They solve different problems and must stay **separate**.

---

## 1. Education / Consultation assignment (EXISTING — reviewed)

Two engines under one feature, **both independent of INO** (`modules/cloud_consultation/`,
`modules/education/online_consultation/`, `modules/Identity/`). Route chosen per consultant by
`assign_core.decide_route()`.

| Question | Finding (file evidence) |
|---|---|
| **How assigned/sent** | **External** → Google Drive hub: `create_and_upload_consultation` (`consultation/workflow.py`) seals a `consultation.json` envelope (`service.py`), uploads via `GoogleDriveTransport` (Drive v3 resumable), then `assign()` shares the folder with the assignee (`assignment.py`). **Internal** → `AipacsWebClient.create_consultation` → `POST /api/v1/consultations` (Laravel; **no images**). |
| **Sender/receiver identity** | Receiver = a `consultation_address` (app-level routing string), resolved `consultation_address > address > email`. Sender's address from `feature_flags.consultation_address()` (env → flag → linked aipacs_web Gmail → Google handle). Sender picks receiver from `GET /api/v1/consultants`. Identity via the **Identity module** (a linked `aipacs_web` Laravel identity + a Google identity). The AI-PACS/INO login is never touched. |
| **Cross-center** | **Yes, by design.** Hub-account mode (ADR-0004): all workstations share ONE Google account; routing is by `consultation_address`, not the Drive account. Per-physician Drive layout `AI-PACS Consultations/<address>/<cid>/` + `physician.json`. Optional `center_id` tags the originating center. |
| **Depends on INO?** | **No.** Zero references to `receptionId` / `imagingWorkflow` / `reception_api` / `:8080/api/pacs`. The internal backend is a separate Laravel "consult-form" app; the external path is Google Drive. |
| **API / DB / transport** | Google Drive v3 (`transport/google_drive.py`, scope `drive.file`), Laravel Sanctum REST `/api/v1/*` (pair, me, consultants, consultations, storage), local SQLite `database.consultation_db` for state + audit events. |
| **States / permissions** | Internal enum (`consultation/models.py`): `pending, uploaded, downloaded, reviewed, answered, closed, conflict`; transitions enforced by `sync/state_machine.py::assert_transition`; display labels (Pending/Sent/Received/Answered/Closed) are direction-aware + display-only. Registry (Laravel) has its own `pending→accepted/declined→answered→closed`. Gated by `online_consultation_available()` = triple gate (identity + cloud_consultation + module `consultation`). |
| **Reassign / unassign / history** | **Revoke** = `revoke_consultation_access` → Drive `revoke(permission_id)` (best-effort, never blocks close). **Close** = `close_consultation` (validated transition). **History** = `consultation_db.add_event` audit trail (`assigned`, `share_revoked`, `closed`…). **Multi-assign** (one POST per physician) exists; a dedicated **A→B reassign** primitive does **not**. |
| **De-identification** | **Default ON** — `build_export_callable(..., deidentify=True)` runs `deidentify_package` in place before sealing; un-de-identifiable files are dropped; if nothing remains, the send is blocked. UIDs preserved (pseudonymous) so ingest resolves. |

---

## 2. INO Reception internal assignment (from the guide — reviewed, NOT yet in AI-PACS)

| Question | Finding (from `ASSIGN_CLIENT_GUIDE_FA.md`) |
|---|---|
| **How internal assignment works** | Assign a **radiologist** or **typist** to a reception's studies. Two routes: **A)** from INO/RIS UI (`PATCH /Reports/reception/{mongoId}/radiologist` → RIS auto-calls PACS `PUT /api/patients/{ReceptionID}/assign`); **B)** directly from a PACS client via REST `PUT /api/patients/{patient_id}/assign` **or** the socket `AssignStudy`. Applies to **all studies** of the reception unless a `study_uid` is given. |
| **Endpoints** | REST (**PACS HTTP :8000**): `GET /api/assign/users`, `PUT /api/patients/{id}/assign`, `GET /api/patients/{id}/assign`, legacy `PUT /api/patients/{id}/radiologist`. Socket (**:50052**): `GetAssignUsers`, `AssignStudy`, event `study_assigned`. User lists also from `GET /api/personnel`, `GET /api/AdminUser/getCenterUsers`. |
| **User/physician identity** | `assign_type` ∈ {`radiologist`, `typist`}. `assignee_source` ∈ {`pacs` (Mongo `users`), `ris_personnel` (`Personnel._id`, usually radiologist), `ris_user` (`AdminUser._id`, usually typist)}. `patient_id` = the numeric **ReceptionID** (PatientID on the study == ReceptionID in RIS). |
| **Center membership** | Users come from **that center's** RIS/PACS directory (`getCenterUsers`, `personnel`); assignment is inherently intra-center. RIS auth via Bearer token or `ris_api_settings.api_token`. |
| **Who may assign** | The guide doesn't enumerate role rules explicitly, but assignment writes to `studies.*` and is gated by the authenticated PACS/RIS user; realtime targeting binds to `user_id`/`personnel_id`/`ris_user_id`. (Role enforcement is server-side, same as INO's other endpoints.) |
| **Status storage** | On Mongo `studies`: `radiologistId/Name/Source`, `typistId/Name/Source`, `lastAssignedAt`, `lastAssignedBy`. Read current via `GET /api/patients/{id}/assign`. |
| **Realtime** | Socket **`study_assigned`** (targeted first to the assignee's logged-in socket via `assignee_id` match on bind fields; falls back to broadcast-all) + `patient_list_updated`. Requires `Login` + `SubscribeToEvents` on the socket. |
| **Reassign / unassign / history** | Reassign = call `assign` again (overwrites the `radiologist`/`typist` fields); no explicit "unassign"/history endpoint documented beyond `lastAssignedAt/By` and the legacy `radiologist_changed` event. |
| **De-identification** | **None** — same center, full patient data (it's a work-routing action, not a data handoff). |

**Important:** the INO assign channels are INO's **PACS** endpoints — REST on **:8000** and the socket
on **:50052** (the *same* socket port AI-PACS already logs into). This is distinct from the INO
**reception REST on :8080** used for report/status/approval. AI-PACS currently implements **none** of
these assign endpoints (verified: no `AssignStudy`/`GetAssignUsers`/`study_assigned`/`/assign` in the
codebase).

---

## 3. Side-by-side

| Dimension | INO Reception assignment (internal) | Education/Consultation (external) |
|---|---|---|
| **Intent** | Route reporting/typing work within a center | Second opinion / case handoff to another physician or center |
| **Scope** | Same center only | Cross-center / independent AI-PACS users |
| **Who is assigned** | Radiologist / typist (RIS/PACS user) | Consulting physician (AI-PACS Identity) |
| **Identity source** | INO/RIS users (`pacs`/`ris_personnel`/`ris_user`) | AI-PACS Identity (`aipacs_web` + Google), routed by `consultation_address` |
| **Transport** | INO PACS REST **:8000** or socket **:50052** (`AssignStudy`) | Google Drive hub (external) / Laravel `/api/v1` (internal) |
| **Auth** | INO login token (socket/RIS) | Identity-linked accounts (NOT the INO/PACS login) |
| **Case key** | numeric `ReceptionID` (= PatientID) | `consultation_id` + `study_uids`, de-identified |
| **Patient data** | Full (same center) | **De-identified** before send |
| **State model** | study fields (`radiologistId`/`typistId`, `lastAssignedAt/By`) | 7-state machine + registry statuses + audit events |
| **Realtime** | socket `study_assigned` (targeted) + `patient_list_updated` | Drive poller (`find_assigned_consultations` / `find_response_updates`) |
| **Reassign / revoke** | re-assign overwrites; no explicit unassign | revoke Drive share; close; multi-assign; no A→B primitive |
| **INO dependency** | Yes (it IS INO) | None |
| **In AI-PACS today** | **Not implemented** | **Implemented** |

---

## 4. Separation guidance (for the later implementation — not done here)

1. **Keep them as two independent routes; do NOT merge.** A single "Assign" UI can offer two clearly
   labelled actions: **"Assign within center (INO)"** and **"Send to external physician
   (Consultation)"** — but they must call **different** back-ends and never share identity/transport.
2. **INO internal assignment is new work.** Natural home: a new INO-side client (e.g.
   `modules/network/ino_assignment.py`) reusing the **existing** infrastructure — `SocketTokenManager`
   token, `reception_api_config` for host, and either the socket client (`AssignStudy` /
   `GetAssignUsers` / subscribe to `study_assigned`) or REST `:8000`. Confirm with INO whether the
   center exposes `:8000` REST, the `:50052` socket assign endpoints, or both. Reuse the numeric
   `ReceptionID` the app already has (the same id used for report status/approval).
3. **Do not route external identity through INO or vice-versa.** The consultation `consultation_address`
   / Identity accounts must never be used to pick an INO radiologist, and INO `ris_personnel` ids must
   never be used as a consultation assignee.
4. **De-identification stays external-only.** Internal INO assignment must send full data (same center);
   the de-id pipeline is exclusively for the cross-center consultation path.
5. **Realtime:** INO assignment can reuse the existing socket connection (add a `study_assigned`
   handler → toast + worklist refresh); the consultation path keeps its Drive poller. Keep the two
   notification handlers separate.
6. **Roles:** for INO assignment, gate the physician-vs-typist choice per INO permissions (ties into
   the access-control review — `docs/reports/INO_CONFIG_ACCESS_CONTROL_REVIEW_2026-07-09.md`); for
   consultation, keep the existing triple-gate + capability matrix.

---

### Related
* `docs/pipelines/online-consultation-education.md` — the consultation as-built.
* `docs/pipelines/ino-reception-connection.md` — INO connection topology.
* `docs/reports/INO_CONFIG_ACCESS_CONTROL_REVIEW_2026-07-09.md` — INO roles/permissions.
* `ASSIGN_CLIENT_GUIDE_FA.md` (attached) — INO assignment client protocol.
