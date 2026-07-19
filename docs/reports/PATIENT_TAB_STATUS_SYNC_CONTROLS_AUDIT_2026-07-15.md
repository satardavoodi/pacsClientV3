# Patient-Tab status-sync controls — audit (Cloud button + Status dropdown)

**Date:** 2026-07-15
**Scope:** the two status controls in the Patient-Tab toolbar — the cloud
**"Sync Patient Data with Server, Close Patient, and Return Home"** button, and the
**Status dropdown** + its Sync action.
**Method:** code trace of the full flow of each control to the server status model.

> **Status = FIX IMPLEMENTED (flag-gated default-on) 2026-07-15.** User confirmed: cloud button →
> Awaiting Secretary with BOTH flags false; the flag mapping changed GLOBALLY; dropdown stays at 6.
> See §7. Audit findings are §1–§5. Needs a source-build restart + live verify (§8).

---

## 1. Headline

| Control | Requirement | Implemented today | Match |
|---|---|---|---|
| **Cloud** | status → **Awaiting Secretary** | status → **`physician_approved`** | ❌ |
| **Cloud** | physicianApproved = **false** | maps to physicianApproved = **true**, and is **never sent to the INO reception** | ❌ |
| **Cloud** | secretaryApproved = **false** | false (but never sent to the reception) | ⚠️ |
| **Cloud** | sync data, close tab, return home | ✅ all three | ✅ |
| **Dropdown** | options = server statuses | 6 of the 8 server statuses (all valid) | ⚠️ |
| **Dropdown** | selected status sent + stored | ✅ socket **+** INO approval-flags PATCH | ✅ |
| **Dropdown** | approval states consistent | ✅ one shared `approval_flags_for_status` map | ✅ |
| **Dropdown** | UI reflects server-confirmed result | ✅ reads the socket response status (falls back to requested) | ✅ |

**The core issue:** the two controls take **different paths to the server**, and the cloud button
uses the wrong status value *and* skips the INO approval-flags path that every other status write
uses.

---

## 2. Cloud "Sync + Close + Home" button — as implemented

Flow: `toolbar_manager._sync_and_go_home` → `_start_patient_sync(close_after_sync=True)` →
`patient_sync_service.sync_patient_data` → worker thread:

1. Upload attachments (`upload_attachments_for_study`), then a **non-destructive** reconcile
   pull. ✅ (this is the "sync patient data" part, and it is solid — local files are never deleted.)
2. **`report_service.update_report_status(study_uid, new_status=SYNC_REPORT_STATUS)`** — the **PACS
   socket** status update, keyed by `study_uid`.
3. On success: `patient_widget.report_status = SYNC_REPORT_STATUS`; refresh the home row; then
   `close_and_remove_patient_tab()` (closes the tab and returns to Home). ✅✅

**Two problems, both in the status half:**

- **`SYNC_REPORT_STATUS = "physician_approved"`** (`socket_report_status_service.py:59`, the default
  since **2026-06-22**, with the explicit rationale *"the workstation user is the reading physician,
  so a sync marks the report Physician Approved… NEVER awaiting_secretary_approval"*). This is the
  **opposite** of the requirement (Awaiting Secretary). It is a single shared constant and is
  **pinned by a guard test** (`tests/code/system/test_patient_sync_report_status.py` →
  `test_central_defines_shared_sync_constant_default_physician_approved`), so it is a deliberate,
  guarded decision — not an accidental value.
- **The cloud button never touches the INO reception approvalFlags.** Unlike the dropdown and the
  Report-Editor/EchoMind paths, `patient_sync_service._sync_worker` calls **only** the socket
  `update_report_status`. It does **not** call `sync_report_approval_for_status` (the
  reception→workflow-id resolve → `PATCH …/approval-flags`). So on the INO reception —
  the server you verify on — the cloud sync sets **no** `physicianApproved` / `secretaryApproved`
  at all. Even the status it does choose (`physician_approved`) maps to
  `physicianApproved=true` (see §3), the opposite of the requirement.

So the cloud button today: syncs data ✅, closes ✅, returns home ✅ — but sets the **wrong status**
and does **not** drive the reception's approval flags.

---

## 3. The status → approvalFlags map (the model both controls should share)

`socket_report_status_service.approval_flags_for_status(status)` (the one pure mapping):

| status | physicianApproved | secretaryApproved |
|---|:---:|:---:|
| pending / awaiting_physician_approval / awaiting_approval | ❌ | ❌ |
| **awaiting_secretary_approval** | **✅** | ❌ |
| physician_approved | ✅ | ❌ |
| secretary_approved / completed / archived | ✅ | ✅ |

**Note the tension with the requirement:** the requirement is *Awaiting Secretary with BOTH flags
false*, but `awaiting_secretary_approval` currently maps to **physicianApproved = true** (it means
"physician is done, now the secretary's turn"). So meeting the requirement needs a decision (§4):
either the cloud action sends an explicit both-false, or the mapping of `awaiting_secretary_approval`
itself changes (which would also change what the dropdown sends for that status).

---

## 4. Status dropdown — as implemented

Flow: pick a status → `toolbar_manager._change_status_from_dropdown` →
`patient_widget._change_report_status(study_uid, old, new, comment)` → background thread:

1. **Socket** `update_report_status(study_uid, new_status, comment)` (when the status changed).
2. **INO reception** `sync_report_approval_for_status(patient_id, new_status)` — resolves the
   reception→workflow id and `PATCH`es the approval flags from `approval_flags_for_status`. ✅ This
   is the same INO path the Report Editor / EchoMind use.
3. REST comment sync.
4. UI: `_handle_status_update_result` reads the **server** status from the socket response
   (`report_status` / `reportStatus` / …), falling back to the requested value — so the badge and
   home row reflect the server-confirmed status. ✅

Findings:

- **Options:** the dropdown offers **6** statuses — pending, awaiting_physician_approval,
  awaiting_secretary_approval, physician_approved, secretary_approved, completed. All 6 are valid
  server statuses, but the server enum (`VALID_STATUSES`) has **8** — `awaiting_approval` and
  `archived` are **not** offered. Not wrong, but not a full match to "the statuses supported by the
  server." Confirm whether those two should appear.
- **Sent / stored / consistent / UI:** all correct. The dropdown goes through the **shared** model
  (`approval_flags_for_status`) and the INO approval-flags PATCH, and reflects the socket-confirmed
  status. The dropdown is the **reference** implementation the cloud button should match.
- One nuance: the dropdown (like the cloud button) does **not** call `/api/pacs/update-report`
  (which writes `report.status` + content) — it relies on the approval-flags PATCH to drive INO's
  displayed state. That is consistent with how INO renders status (from flags), but the raw
  `report.status` string on the reception is only moved by the workflow PATCH, not by update-report.
  Worth one live confirmation on a test reception.

---

## 5. Root cause & proposed fix (needs your confirmation on §3's tension)

**Root cause:** the cloud button and the dropdown were wired to the server **differently**. The
dropdown uses the shared status model + the INO approval-flags PATCH; the cloud button uses only the
PACS socket with a hard-coded `physician_approved`. So the cloud button neither sends the required
status nor drives the reception approval flags.

**Proposed fix (once semantics confirmed):**

1. Make the cloud "Sync + Close + Home" action set **status = `awaiting_secretary_approval`**
   (change `SYNC_REPORT_STATUS`, or scope a distinct value to the cloud path), flag-gated.
2. Route the cloud sync through the **same** INO approval-flags path the dropdown uses
   (`sync_report_approval_for_status`), so the reception's `physicianApproved`/`secretaryApproved`
   are actually written — instead of being left untouched.
3. Make the flags come out **false/false** as required — either by sending an explicit both-false
   for the cloud action, or by changing `awaiting_secretary_approval`'s mapping (which also affects
   the dropdown — a decision, see §3).
4. Update the guard test `test_patient_sync_report_status.py` to the new contract (it currently
   pins `physician_approved`).
5. Optionally add `awaiting_approval` / `archived` to the dropdown for a full match to the server
   enum.

**Why I'm asking before changing it:** the current `physician_approved` behaviour is a deliberate,
documented, test-pinned decision from 2026-06-22, and the requested "Awaiting Secretary with
physicianApproved=false" is internally unusual (awaiting-secretary normally means the physician has
already approved). This is a clinical-workflow choice only you should make.

---

## 7. Fix as implemented (2026-07-15, per your confirmation)

Decisions taken: **Awaiting Secretary + both-false**, mapping changed **globally**, dropdown kept
at 6.

1. **`modules/network/socket_report_status_service.py`**
   - `SYNC_REPORT_STATUS` default `physician_approved` → **`awaiting_secretary_approval`** (kill
     switch `AIPACS_SYNC_REPORT_STATUS=physician_approved`). Invalid-env fallback also updated.
   - `awaiting_secretary_approval` removed from `_PHYSICIAN_APPROVED_STATES`, so
     `approval_flags_for_status("awaiting_secretary_approval")` → **`{physician:false, secretary:false}`**.
     Gated by `AIPACS_AWAITING_SECRETARY_BOTH_FALSE` (default on; `=0` restores physician=true).
     Applied globally — the dropdown and Report Editor use the same map.
2. **`PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py`**
   - Cloud `on_sync_completed` success branch now also calls
     `sync_report_approval_for_status_async(<reception_id>, SYNC_REPORT_STATUS)` off-thread, so the
     cloud button **writes the INO reception approvalFlags** (both-false) — the same INO path the
     dropdown/editor use. It no longer only touches the PACS socket.
3. **`PacsClient/pacs/patient_tab/utils/patient_sync_service.py`** — stale `physician_approved`
   comments corrected (behaviour is driven by the shared `SYNC_REPORT_STATUS`; no logic change here).
4. **Tests updated:** `test_report_status_approval_flags.py` (awaiting_secretary → both-false),
   `test_patient_sync_report_status.py` (default now awaiting_secretary_approval + env contract).
   The real module's constants + mapping were validated in-sandbox; run the full files on Windows via
   `run_test.ps1` (the FUSE mount fakes a SyntaxError on an unrelated `try/except` deeper in the file).

**Net cloud-button behaviour now:** sync attachments ✅ → status `awaiting_secretary_approval`
(socket) ✅ → INO reception `physicianApproved=false, secretaryApproved=false` (approval-flags PATCH)
✅ → close tab ✅ → return home ✅. Badge shows `SC…` (awaiting secretary), distinct from approved.

**One honest consequence to note:** with both flags false, `awaiting_secretary_approval` now has the
same approvalFlags signature as pending / awaiting_physician on the INO side (INO renders state from
flags). The distinction lives in `report.status`. If you later want Awaiting-Secretary to look
distinct on INO, that needs an INO-side status field, not just flags.

## 8. Live verification (needs a source-build restart)

1. Restart the source build (VS Code Play). 2. Open a test patient, click the cloud
   **Sync + Close + Home**. 3. On the INO reception (or `GET :8080/api/pacs/report/<id>`), confirm
   `report.approvalFlags` = `physicianApproved:false, secretaryApproved:false` and the status reads
   Awaiting Secretary. 4. The tab closes and Home is shown. 5. Dropdown: pick each status and confirm
   the flags follow §3 (with awaiting_secretary now both-false).

## 9. Files

| Concern | File |
|---|---|
| Shared status enum + `SYNC_REPORT_STATUS` + `approval_flags_for_status` | `modules/network/socket_report_status_service.py` |
| Cloud sync worker (attachments + socket status) | `PacsClient/pacs/patient_tab/utils/patient_sync_service.py` |
| Cloud button handler + close/home + dropdown UI | `PacsClient/pacs/patient_tab/ui/patient_ui/patient_toolbar/toolbar_manager.py` |
| Dropdown status change → socket + INO approval-flags | `PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/_pw_panels.py` |
| INO approval-flags PATCH | `modules/network/ino_report_workflow.py` |
| Guard test (pins `physician_approved`) | `tests/code/system/test_patient_sync_report_status.py` |
