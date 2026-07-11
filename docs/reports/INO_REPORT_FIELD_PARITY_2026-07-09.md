# AI-PACS ↔ INO — Report Field Parity (send / get / sync)

**Date:** 2026-07-09
**Question:** Do AI-PACS and INO **completely match** in exchanging a report — send, get, and sync of
the different fields?
**Evidence:** live INO report object for reception 49476 via `GET :8080/api/pacs/report/{receptionId}`
(the endpoint behind the INO `singleReportPatient` page); AI-PACS read/send code in
`reception_data_tab.py` + `ai_chat_pages.py`.

## Short answer

**No — not a complete field-for-field match, but the clinically essential fields now do match.**
Report **content/findings** and **status**, and (after today's fix) the **approvalFlags booleans**,
are exchanged both ways. Several INO report fields are **not** fully synced: the **approver identity
and timestamps** (`physicianApprovedBy/At`, `secretaryApprovedBy/At`), the **radiologist**, and the
INO-managed extras (`typist`, `pacsVoice`, `approvedBy`, `reportDate`).

## INO report object (source of truth)

`GET /api/pacs/report/{receptionId}` → `data.report`:

| Field | Type | Notes |
|---|---|---|
| `content` | string (HTML) | the report body |
| `findings` | string (HTML) | mirror of content |
| `status` | string | `completed` / `physician_approved` / `awaiting_physician_approval` / … |
| `approvalFlags.physicianApproved` | bool | |
| `approvalFlags.secretaryApproved` | bool | |
| `approvalFlags.physicianApprovedBy` | id | **who** approved (user id) |
| `approvalFlags.secretaryApprovedBy` | id | |
| `approvalFlags.physicianApprovedAt` | ISO datetime | **when** |
| `approvalFlags.secretaryApprovedAt` | ISO datetime | |
| `radiologist` | object | reading physician (`FullName`, …) |
| `typist` | string | |
| `pacsVoice` | object | voice-note reference |
| `approvedBy` | object | approver profile |
| `reportDate` / `date` | datetime | server-set |

## Parity matrix

| INO field | AI-PACS **sends** (update-report) | AI-PACS **reads/uses** | Sync |
|---|---|---|---|
| `content` | ✅ | ✅ (editor) | **two-way** |
| `findings` | ✅ (= content) | ✅ (fallback) | **two-way** |
| `status` | ✅ | ✅ (status combo) | **two-way** |
| `approvalFlags.physicianApproved` | ✅ (since 2026-07-09 fix) | ✅ (display) | **two-way (bool)** |
| `approvalFlags.secretaryApproved` | ✅ (since fix) | ✅ (display) | **two-way (bool)** |
| `approvalFlags.*ApprovedBy` (who) | ❌ | ❌ | **gap** — relies on INO to fill from the auth token |
| `approvalFlags.*ApprovedAt` (when) | ❌ | ❌ | **gap** — relies on INO to timestamp |
| `radiologist` | ❌ | ✅ read-only (display) | **one-way (INO → AI-PACS)** |
| `reportDate` / `date` | ❌ | ✅ read-only | **one-way**, server-set |
| `typist` | ❌ | ❌ | not exchanged |
| `pacsVoice` | ❌ | ❌ | not exchanged (voice is a separate attachment channel) |
| `approvedBy` (profile) | ❌ | ❌ | not exchanged |

AI-PACS **send body** = `{receptionId, content, findings, status, approvalFlags:{physicianApproved,
secretaryApproved}}`. AI-PACS **reads** the report embedded in `GET /api/pacs/patients/{id}.report`
(status, approvalFlags, reportDate, radiologist, content/findings) — it does **not** call the richer
`/api/pacs/report/{id}` (which additionally carries `typist`, `pacsVoice`, `approvedBy`, and the
approver ids/timestamps).

## Gaps that matter (and whether they need a fix)

1. **Approver identity + timestamps (`*ApprovedBy` / `*ApprovedAt`).** AI-PACS sends only the two
   approval booleans. INO must derive *who/when* from the authenticated JWT + server clock. **Confirm
   with the INO API owner** that `update-report` stamps `physicianApprovedBy/At` (and clears them on a
   downgrade). If it does **not**, the approval audit on INO will be blank/stale for reports approved
   from AI-PACS — then AI-PACS should send these explicitly (the login user id + now).
2. **`radiologist`.** AI-PACS displays it but never sets it when sending a report authored on the
   workstation. If INO does not set the reading radiologist from the JWT user, reports written in
   AI-PACS will show no/again-stale radiologist on INO. **Confirm** whether INO fills it from the token;
   if not, add `radiologist` to the send body.
3. **`typist`, `pacsVoice`, `approvedBy` profile, `reportDate`.** Server/INO-managed; **no fix needed**
   — these are owned by the reception workflow, not the workstation. (Voice notes have their own
   attachment channel.)

## Verdict

- **Report send/get for content + status + approval booleans: matched** (status-sync bug fixed today).
- **Complete field parity: not yet.** The only *functional* gaps are the **approver identity/timestamp**
  and the **radiologist** — and both are only real gaps *if* INO does not auto-fill them from the
  authenticated user. That single server-behaviour question decides whether any further client change is
  needed.

## Recommended next step (safe, decisive)

Confirm INO's `update-report` server behaviour for two things: (a) does it set/clear
`approvalFlags.*ApprovedBy/At` from the JWT + clock when it receives the booleans; (b) does it set
`radiologist` from the JWT user. Fastest check: from AI-PACS (or a reversible API call on a test
reception) change a report's status, then `GET /api/pacs/report/{id}` and inspect whether
`*ApprovedBy/At` and `radiologist` populated correctly. If yes → parity is functionally complete. If no
→ extend the send body with those fields (small, flag-gated follow-up).

_Related: `docs/reports/AINO_RECEPTION_STATUS_SYNC_REVIEW_2026-07-09.md` (status-sync root cause + the
approvalFlags fix), `docs/pipelines/ino-reception-connection.md` (connection topology)._
