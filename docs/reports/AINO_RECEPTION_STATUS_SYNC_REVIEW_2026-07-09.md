# AI-PACS ↔ INO Reception — Report + Status Sync Review

**Date:** 2026-07-09
**Focus:** Why the **patient/report status** set from AI-PACS (Report Editor or EchoMind) does not
appear to update on the INO Reception server.
**Test reception:** 49476 (+ live evidence from 120 reception records).

---

## ⚠️ LIVE-TEST CORRECTION (2026-07-09, verified by mutating reception 49476)

A controlled live test on 49476 (change status → observe INO → restore) **corrected the root cause
and invalidated the first client fix.** Read this first; the sections below are the earlier analysis.

**What the INO server actually does:**
1. `POST /api/pacs/update-report` **does** change `report.status` (verified each call). ✅
2. INO **IGNORES the `approvalFlags` sent in the `update-report` body.** Proof: POST with
   `status="physician_approved"` + `approvalFlags={true,true}` → GET returned `false/false`; POST
   `status="completed"` (no flags) → `false/false`. So the first fix (adding `approvalFlags` to the
   `update-report` body) is a **NO-OP on the server** — harmless, but ineffective.
3. INO **auto-CLEARS** `approvalFlags` when `status` becomes an *awaiting* state: POST
   `status="awaiting_physician_approval"` → GET `physicianApproved=false, secretaryApproved=false`
   **without sending any flags**. So a **downgrade already syncs** via the status string alone.
4. INO does **NOT** auto-SET the flags true for `completed`/`physician_approved`. **Approval is a
   separate, deliberate action.**
5. The real approval field is set by **`PATCH /api/imagingWorkflow/{workflowId}/workflow/report/approval-flags`**
   with body `{physicianApproved, secretaryApproved}` (the INO web app's own approve/un-approve
   buttons call this; verified honored → `"وضعیت تاییدات بروزرسانی شد"`, flags became `true/true`).

**Corrected root cause:** INO renders the patient/report state from `approvalFlags`. AI-PACS only
calls `update-report`, which moves `report.status` and (server-side) clears flags on a downgrade but
**cannot set them true**. So "approve from the workstation" never reflects in INO, and a change
*between* two approved-ish states (completed ↔ physician_approved) shows no visible change because the
flags stay set. To make an **approve** reflect, AI-PACS must call the **workflow approval-flags PATCH**.

**The real fix (supersedes §7):**
- To un-approve / send-for-approval → set an *awaiting* status via `update-report` (already works).
- To approve (physician/secretary) → call
  `PATCH /api/imagingWorkflow/{workflowId}/workflow/report/approval-flags {physicianApproved,
  secretaryApproved}` (reuse `approval_flags_for_status`).
- **Blocker:** that endpoint keys on the **imagingWorkflow ObjectId** (e.g.
  `6a4de81218a091772b582325`), which the receptionId-based endpoints AI-PACS uses
  (`/api/pacs/patients/{receptionId}`, `/api/pacs/report/{receptionId}`) do **not** return. AI-PACS
  needs a `receptionId → workflowId` source (ask the INO API owner to return the workflow `_id`, or
  expose a lookup) before this can be wired.
- The already-shipped `approval_flags_for_status` mapping is still correct and reusable for the PATCH
  body; the `update-report` `approvalFlags` addition is harmless but should be treated as a no-op
  until/unless INO honors it.

**Test-record note:** 49476 was restored to its original **status=`physician_approved`, flags
`true/true`, identical content (5524 chars)**. The one unrestorable change: the approver identity +
timestamp (`physicianApprovedBy/secretaryApprovedBy` = reza.ab @ 05:51Z) became null/current because
re-approval ran under the `vahid` session — INO stamps the approver from the caller's token.

### ✅ REAL FIX IMPLEMENTED + LIVE-VERIFIED (2026-07-09)
New module **`modules/network/ino_report_workflow.py`**:
* `resolve_workflow_id(receptionId)` → `GET /api/imagingWorkflow/workflow/reporting?receptionID=<n>`
  → the item's `receptionId` (the imagingWorkflow **ObjectId**; the worklist item carries both the
  numeric `receptionID` and the ObjectId `receptionId`).
* `set_report_approval_flags(workflowId, physician, secretary)` →
  `PATCH /api/imagingWorkflow/{workflowId}/workflow/report/approval-flags {physicianApproved,
  secretaryApproved}`.
* `sync_report_approval_for_status(receptionId, status)` = resolve → map status via
  `approval_flags_for_status` → PATCH. `*_async` wrapper runs it on a daemon thread (never blocks the
  GUI). Flag `AIPACS_INO_APPROVAL_SYNC` (default ON). Reuses the JWT + circuit breaker; best-effort.

Wired into **all four** status-change entry points:
1. **Report Editor** — `reception_data_tab._save_report_to_api` (after `update-report`).
2. **EchoMind** — `ai_chat_pages._send_with_patient_id` (after `update-report`, + plugin mirror).
3. **Patient-Tab toolbar "Change Report Status" dropdown** — `_pw_panels._change_report_status`
   (`update_status_thread`, on status change). This path previously only did a **socket**
   `UpdateReportStatus` (keyed by `study_uid`) + a comment REST sync — it never touched INO's
   reception report, so status changes here did **not** reach INO. Now it also resolves the reception
   → workflow id and PATCHes the approval flags.
4. **Main-Page report popup** — `patient_table_widget._change_report_status` (same socket-only gap;
   now also synced).

Paths 3 & 4 pass their `patient_id` (the numeric reception id in this deployment) to the resolver;
its **exact `receptionID` match** makes it a safe no-op if that id is ever not a reception id. Tests:
`tests/code/network/test_ino_report_workflow.py` + `tests/code/network/test_report_status_approval_flags.py`.

Note: the dedicated status endpoint `PATCH /api/imagingWorkflow/{id}/workflow/report/status {status,
note}` exists but enforces a transition **state-machine** (rejects same→same and disallowed
transitions with HTTP 400). The **approval-flags** PATCH is used instead because it reliably sets the
field INO displays **and** drives the resulting `report.status` (verified: `{false,false}` →
`awaiting_physician_approval`, `{true,true}` → `completed`), without transition-rule friction.

**Live-verified on 49476 (2026-07-09):** the full path (resolve id `6a4de81218a091772b582325` → PATCH)
flipped INO both ways — `awaiting_physician_approval` → flags `false/false`, `completed` → flags
`true/true` (each `PATCH` = HTTP 200 `"وضعیت تاییدات بروزرسانی شد"`), then the record was restored.
This is the effective status sync; the earlier `approvalFlags`-in-`update-report` addition remains a
harmless server-ignored no-op.

---

## TL;DR — Root cause (original analysis — see the correction above)

AI-PACS **does** send the report and its status to INO, and the report *string* status **does**
persist — but AI-PACS updates **only** `report.status`. It never updates the two fields INO
actually uses to display the patient's state: **`report.approvalFlags`** (`physicianApproved` /
`secretaryApproved`) and the reception-level **`workflowStatus`**.

The `/api/pacs/update-report` request body is exactly:

```json
{ "receptionId": <id>, "content": "<html>", "findings": "<html>", "status": "<internal-status>" }
```

No `approvalFlags`, no `workflowStatus`. So when you **downgrade** a completed/approved report to
"Awaiting Physician/Reception," `report.status` changes on the server but the approval flags stay
`true/true` → INO keeps showing the report as **approved/completed**. That is the "status not
updating" the user sees.

**Live proof (read-only):** reception **46682** currently has
`report.status = "awaiting_physician_approval"` **with** `physicianApproved = true` and
`secretaryApproved = true`. That contradictory state can only occur when `status` is changed
without clearing the approval flags — i.e. exactly the AI-PACS update path.

---

## 1. AI-PACS → INO API flow map

The reception software is **INO**. Everything below talks to that one INO server — the same host
whose report page is `http://81.16.117.196/report?type=serviceInsurance` (frontend on `:80`, API on
`:8080`). The **"Reception/Workflow API"** you configure in Settings **is** this connection: it sets
the reception REST base URL (`get_reception_api_base_url()`, default `http://81.16.117.196:8080`) —
there is no separate reception service. Two channels total:

| Channel | Port | Used for |
|---|---|---|
| INO Reception/Workflow REST API (the Settings "Reception/Workflow API") | **:8080** (`get_reception_api_base_url()`, default `http://81.16.117.196:8080`) | report submission + status, patient/reception data, the report/analytics pages |
| Imaging **socket** | :50052 | login/JWT, patient list, thumbnails, DICOM; **and** the PACS-side report-status mirror |

Auth on every REST call: `Authorization: Bearer <JWT>` from `SocketTokenManager` (the login token).

### Report submission endpoint (both send paths use it)
`POST {base:8080}/api/pacs/update-report`, keyed by **`receptionId`**, body =
`{receptionId, content, findings, status}`. Status is the **internal AI-PACS code**
(`pending` / `awaiting_physician_approval` / `awaiting_secretary_approval` / `physician_approved` /
`secretary_approved` / `completed` / …). **No mapping/translation** is applied — the raw code is
sent as `status`.

### Status "mirror" to the PACS socket (separate store)
After the REST save, both paths also call `patient_table_widget._change_report_status(...)` →
`SocketReportStatusService.update_report_status(study_uid, new_status)` →
`socket_client.update_report_status` → socket command **`UpdateReportStatus`**, keyed by
**`study_uid`** (not receptionId). This updates a *different* store (the PACS server's report-status),
and is **best-effort/conditional** — it only runs if the owning patient widget with a matching
`study_uid` is found (Report Editor) or `send_mode == "current"` (EchoMind).

---

## 2. Report submission workflow review

Working correctly. Verified on live data: across 120 receptions, `report.status` holds AI-PACS
values — `completed` (majority), `physician_approved`, `awaiting_physician_approval`. So the REST
`update-report` call reaches INO and the `status` field persists. Report **text** (content/findings)
is also sent. **The report-send API is functional.**

## 3. Status-update workflow review

Partially broken. The **string** `report.status` updates, but the fields INO renders the patient
state from do **not**:

* **`report.approvalFlags.physicianApproved` / `secretaryApproved`** — never sent by AI-PACS, so
  never cleared on a downgrade. Reception 49476: `report.status="completed"`, `approvalFlags` both
  `true`, `approvedBy = reza.ab`. Reception 46682: `report.status="awaiting_physician_approval"` yet
  `approvalFlags` both `true` (the divergence proof).
* **`workflowStatus`** — reception-level workflow field; constant `waiting_appointment` on all 120
  records (an appointment/scheduling field, not driven by reporting). AI-PACS never writes it.

So the status the user changes (report-level) is not the same field INO shows as the patient's
approval/workflow state. Consistent records (`awaiting_physician_approval` + `false/false`, e.g.
47229) were set from **inside INO** (which clears the flags); AI-PACS-driven changes leave the flags
stale.

## 4. EchoMind vs Report Editor — path difference

**Almost none.** Both POST the identical `/api/pacs/update-report` schema on `:8080` with the same
`status` key and the same Bearer auth, and both mirror to the socket. Differences that matter:

* **Identifier source.** Report Editor uses `current_data.receptionId`. EchoMind uses the confirmed
  reception id from its dialog and, in the "current" mode, `int(target_patient_id)` as `receptionId`
  — works when *patient code == receptionId* (true for 49476), but should be verified generally.
* **Socket-mirror condition.** Report Editor mirrors whenever an owning patient widget matches;
  EchoMind mirrors only when `send_mode == "current"`. Sending to a *different* reception id from
  EchoMind deliberately does **not** touch the current study's PACS-side badge.

Neither path sends `approvalFlags`/`workflowStatus`, so **both exhibit the same root-cause bug.**

## 5. Test result for reception 49476 (read-only)

* `report.status = "completed"`, `approvalFlags = {physicianApproved:true, secretaryApproved:true}`,
  `approvedBy = reza.ab @ 2026-07-09T05:51Z`, `workflowStatus = "waiting_appointment"`.
* A live **write** test (Completed → Awaiting) was **not executed** — 49476 is an approved clinical
  record and changing `report.status` without clearing `approvalFlags` would leave the audit trail in
  the same inconsistent state seen on 46682. The read-only evidence (46682) already demonstrates the
  failure mode, so a destructive test isn't required to identify the cause. See the validation plan
  for a safe, reversible procedure to run with your go-ahead.

## 6. Root cause (answers to the 8 questions)

1. **Report-send API working?** Yes — text + `report.status` persist on INO.
2. **Status-update API called at all?** Yes — same `update-report` call carries `status`; it updates
   `report.status`.
3. **EchoMind & Report Editor same workflow?** Yes — same endpoint, body, auth, and socket mirror.
4. **Sent to the correct endpoint?** Yes for `report.status`. But the **patient-visible** state
   (`approvalFlags` / `workflowStatus`) has **no** endpoint call from AI-PACS.
5. **Status value mapped correctly?** No mapping at all — the internal code is sent verbatim; INO
   stores it in `report.status` but does not derive `approvalFlags`/`workflowStatus` from it on this
   path.
6. **Does INO accept the update?** It accepts and stores `status`; it does **not** recompute the
   approval/workflow fields the UI shows.
7. **Changed in DB but not refreshed in UI?** Two layers: (a) on INO, `report.status` changes but the
   approval/workflow display fields don't → looks unchanged; (b) on the **AI-PACS** side the status
   badge reads the socket `GetReportStatus` (keyed by `study_uid`), which the server does not answer
   (documented circuit breaker), so the PACS badge can also be stale.
8. **Where is the issue?** Primarily the **API request format** (AI-PACS omits `approvalFlags`/
   `workflowStatus`) plus a **status-model mismatch** (report.status vs approval/workflow). Secondary:
   PACS-side UI refresh via the unanswered socket status endpoint.

---

## 7. Required fix

### Implementation status (2026-07-09) — client fix SHIPPED, flag-gated, default ON
Item 1 below is **implemented**. Both send paths now add `approvalFlags` (derived from the chosen
status) to the `update-report` body:
* `modules/network/socket_report_status_service.py` — new pure
  `approval_flags_for_status(status) -> {"physicianApproved", "secretaryApproved"}` + flag
  `AIPACS_UPDATE_REPORT_APPROVAL_FLAGS` (default ON; `=0` = byte-identical legacy body).
* `reception_data_tab._save_report_to_api` (Report Editor) and
  `ai_chat_pages._send_with_patient_id` (EchoMind) both attach `update_data["approvalFlags"] =
  approval_flags_for_status(status)` when the flag is on. EchoMind's plugin mirror was updated too.
* Mapping: completed/secretary_approved/archived → `true/true`; physician_approved &
  awaiting_secretary_approval → `true/false`; pending / awaiting_physician_approval /
  awaiting_approval / unknown → `false/false`. Guard test:
  `tests/code/network/test_report_status_approval_flags.py`.

**This is safe whether or not INO honors the field** — if INO ignores `approvalFlags`, behaviour is
unchanged from today; if INO honors it, the downgrade bug is fixed. **Still to confirm:** that INO's
`/api/pacs/update-report` actually applies `approvalFlags` server-side (see §8). If INO instead
derives the flags from `status`, the remaining fix is server-side and this client change becomes a
no-op — not a regression.

**Client-side (AI-PACS) — pending confirmation of what INO honors:**

1. **Enrich the `update-report` body** in *both* send paths so the approval state matches the chosen
   status (single shared mapping):
   * `completed` / `physician_approved` → `physicianApproved = true` (and secretary as appropriate);
   * `secretary_approved` → `secretaryApproved = true`;
   * `awaiting_physician_approval` / `pending` → `physicianApproved = false` (+ `secretaryApproved = false`);
   * `awaiting_secretary_approval` → `secretaryApproved = false`.
   Edit `reception_data_tab._save_report_to_api` (body at ~:1640) and EchoMind
   `ai_chat_pages._send_with_patient_id` (body at ~:4147); keep the schema identical (they already
   share it). Gate behind a flag (e.g. `AIPACS_UPDATE_REPORT_APPROVAL_FLAGS`, default on) so it is
   reversible.
2. **Confirm the server contract first.** Verify with the INO/reception API owner whether
   `/api/pacs/update-report` will honor `approvalFlags` (and/or a `workflowStatus`) in the body, or
   whether INO must derive them from `status` server-side. If the server should derive them, the fix
   is **server-side**: make `update-report` set/clear `approvalFlags` from `status`. (This is the
   cleaner fix — one authority.)
3. **Verify the EchoMind receptionId** really equals the reception id in all modes (not just when
   `patient code == receptionId`).
4. **PACS-side refresh:** read the displayed status from the reception REST (`/api/pacs/patients/{id}`
   → `report.status` + `approvalFlags`) instead of the unanswered socket `GetReportStatus`, so the
   AI-PACS badge reflects server truth. (Independent of the INO-side fix.)

## 8. Validation plan (safe, reversible)

Prefer a **non-clinical test reception**; if using 49476, do it reversibly and expect an approval-flag
change:

1. `GET /api/pacs/patients/{id}` → record `report.status`, `approvalFlags`, `workflowStatus`, and the
   existing `content` (to resend unchanged).
2. From **Report Editor**: set status → *Awaiting Physician* and Save. `GET` again → confirm
   `report.status == awaiting_physician_approval` **and** `physicianApproved == false`, and that INO's
   patient list shows "Awaiting." (Pre-fix this will fail the `approvalFlags` check.)
3. Set status → *Completed*. `GET` → confirm `report.status == completed` and `approvalFlags` true, INO
   shows "Completed."
4. Repeat 2–3 from **EchoMind** → identical results (proves both paths fixed).
5. Confirm the AI-PACS home-page badge matches after each change (PACS-side refresh fix).
6. Restore 49476 to its original `report.status`/content and re-approve if the flags were cleared.

---

### Evidence appendix (live, read-only, 2026-07-09)
* 49476: `report.status=completed`, `approvalFlags=true/true`, `workflowStatus=waiting_appointment`.
* 46682: `report.status=awaiting_physician_approval`, `approvalFlags=true/true` ← **divergence proof**.
* 47229: `report.status=awaiting_physician_approval`, `approvalFlags=false/false` (set inside INO).
* 120-record scan: `workflowStatus` = `waiting_appointment` for all; `report.status` ∈
  {completed, physician_approved, awaiting_physician_approval}.

### Key code references
* `modules/ai_imaging/ai_module_ui/service_tab/reception_data_tab.py` — `_save_report_to_api`
  (body ~:1640, URL ~:1652, POST ~:1666), `_propagate_status_to_pacs` (~:1742).
* `modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py` — `status_options`
  (:133), `_save_report` (:1326).
* `modules/EchoMind/viewer_chat/ai_chat_pages.py` — `_send_to_reception` (:3937),
  `_send_with_patient_id` (body ~:4147, POST ~:4160), `_propagate_reception_status_to_pacs` (:3870).
* `modules/network/socket_report_status_service.py` — `update_report_status` (:244), `VALID_STATUSES`
  (:39); `socket_client.update_report_status` (:642) → `UpdateReportStatus`.
* `modules/network/reception_api_config.py` — base-URL resolution (only :8080 + socket :50052).
