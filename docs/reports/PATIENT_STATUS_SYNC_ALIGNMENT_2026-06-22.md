# Patient Status Synchronization — Audit & Alignment (2026-06-22)

Source of truth for the server contract:
`PATIENT_STATUS_RIS_CLIENT_GUIDE_FA.md` (uploaded). Scope chosen by the user:
**targeted fix + guards** (not a broad label-centralization refactor).

---

## 1. Official server status model

Two independent layers (do not conflate):

| Layer | Stored | Field | Used by this app |
|-------|--------|-------|------------------|
| **Report Status** | PACS `studies.reportStatus` / RIS `imagingWorkflow.report.status` | the enum below | ✅ yes |
| Workflow Status | RIS only | `imagingWorkflow.workflowStatus` | ❌ no (RIS-internal) |

**Report Status enum (the only accepted `new_status` values):**

`pending`, `awaiting_physician_approval`, `awaiting_secretary_approval`,
`awaiting_approval`, `physician_approved`, `secretary_approved`, `completed`,
`archived`.

**Transition rule that matters here:** a `pending` report may legally move only
to an `awaiting_*` state. `pending → physician_approved` is **rejected unless
`force`** on the RIS path. The PACS **socket** `UpdateReportStatus` validates
against the enum and saves directly (the Patient‑Tab dropdown already sets
`physician_approved` through it successfully), so the Cloud‑sync change below
uses the same already‑supported socket path.

Client send/receive contract: send via socket `UpdateReportStatus`
(`study_uid`, `new_status`, `comment`, `token`); receive via `GetPatientStatus`
/ `GetPatientList.latest_study_report_status` and the `report_status_changed`
broadcast.

---

## 2. UI label → server value mapping (verified)

| Server value | English (central `REPORT_STATUSES`) | Persian (report editor `status_options`) |
|---|---|---|
| `pending` | Pending | در انتظار |
| `awaiting_physician_approval` | Awaiting Physician Approval | در انتظار تایید پزشک |
| `awaiting_secretary_approval` | Awaiting Secretary Approval | در انتظار تایید منشی |
| `awaiting_approval` | Awaiting Approval | در انتظار تایید |
| `physician_approved` | Physician Approved | تایید شده توسط پزشک |
| `secretary_approved` | Secretary Approved | تایید شده توسط منشی |
| `completed` | Completed | تکمیل شده |
| `archived` | Archived | آرشیو شده |

All UI dropdowns store the **server key** in the item's `data` and read it back
with `currentData()` — no fragile label→value reverse lookup anywhere. The Main
Page additionally normalizes server variants (`awaiting_secretary` →
`awaiting_secretary_approval`, `reported` → `physician_approved`, etc.) before
display.

---

## 3. Every place the app SENDS status to the server

| # | Trigger | Value sent | Path |
|---|---------|-----------|------|
| S1 | **Patient‑Tab Cloud "Sync Patient Data with Server"** | **`physician_approved`** (was `awaiting_secretary_approval`) | `toolbar._start_patient_sync` → `patient_sync_service._sync_worker` → `update_report_status` |
| S2 | Patient‑Tab status **dropdown** | the selected key | `toolbar._change_status_from_dropdown` → `_pw_panels._change_report_status` → `update_report_status` |
| S3 | Main‑Page **Report popup** (`ReportStatusDialog`) | `currentData()` key | `patient_table_widget._change_report_status` → `update_report_status` |
| S4 | **Report editor** (Reception Data → View Report) | `currentData()` key | `report_editor_dialog._save_report` → `reception_data_tab._propagate_status_to_pacs` (+ RIS PATCH) |

All four send canonical enum keys through the one service
`SocketReportStatusService.update_report_status`, which validates against
`VALID_STATUSES`. **No path sends `secretary_approved` on sync.**

## 4. Every place the app RECEIVES / DISPLAYS status

| # | Where | Source |
|---|-------|--------|
| R1 | Main‑Page patient list pill/icon | `GetPatientList.latest_study_report_status` → `_extract_report_status_from_reception_payload` → `_apply_report_status_display` (central `REPORT_STATUSES`/`STATUS_COLORS`) |
| R2 | Live updates | `report_status_changed` broadcast → `_update_report_status_in_table` |
| R3 | Patient‑Tab badge | `_update_report_status_display` (central labels) |
| R4 | Report editor combo + footer "وضعیت:" | `report.get("status")` via Persian `status_options` |

---

## 5. Single source of truth

`modules/network/socket_report_status_service.py` is canonical: `VALID_STATUSES`
(enum), `REPORT_STATUSES` (English labels), `STATUS_COLORS`, and now
`SYNC_REPORT_STATUS` (the one Cloud‑sync value). Every send/display site listed
above already imports from it. Persian labels remain a second (correct but
duplicated) map in the report editor — intentionally left as‑is under the
chosen "targeted" scope (see §8).

---

## 6. Findings

1. **Cloud sync did not mark physician approval.** It set
   `awaiting_secretary_approval`. Per the user's decision the workstation user is
   the reading physician, so a sync must mark **`physician_approved`**.
2. **Ambiguous compact badge (root of the "Secretary Approved" perception).**
   The active Patient‑Tab badge rendered both `awaiting_secretary_approval` and
   `secretary_approved` as **"SC"** (and both physician states as **"MD"**), so a
   synced "Awaiting Secretary" report *looked* like "Secretary Approved".
3. **Two‑site drift risk.** The sync value was hardcoded in two files
   (`patient_sync_service` and `toolbar_manager`) that could diverge.
4. **`physician_approved` vs `secretary_approved` are already distinct** — separate
   enum keys, colors (green vs cyan), and icons. Confirmed never both‑triggered.

## 7. Fixes applied (minimal, flag‑gated)

| File | Change |
|------|--------|
| `modules/network/socket_report_status_service.py` | Added `SYNC_REPORT_STATUS` (default `physician_approved`, validated; env kill‑switch `AIPACS_SYNC_REPORT_STATUS`). |
| `PacsClient/.../patient_tab/utils/patient_sync_service.py` | Sync worker now sends `new_status=SYNC_REPORT_STATUS`; docstring updated. |
| `PacsClient/.../patient_toolbar/toolbar_manager.py` | Post‑sync local status reads `SYNC_REPORT_STATUS` (no hardcode); badge map disambiguated: `MD…`/`SC…` (awaiting) vs `MD✓`/`SC✓` (approved). |
| `tests/code/system/test_patient_sync_report_status.py` | New guard: sync sends `physician_approved`/never `secretary_approved`; states distinct; badge unambiguous; env contract. |

Kill‑switch / revert: `set AIPACS_SYNC_REPORT_STATUS=awaiting_secretary_approval`
restores the pre‑fix value with zero code change.

---

## 8. Out of scope / notes

- **Persian labels not centralized** (chosen scope = targeted). The editor's
  `status_options` is correct but duplicated; centralizing English+Persian into
  the shared service is the natural next step if you want one canonical label map.
- **`reception_reports_viewer.py`** uses a *separate, local* `pending/read/archived`
  model (local DB, not the server enum) — a different feature; left untouched.
- **Dead duplicate** `_update_report_status_display` exists twice in
  `toolbar_manager.py` (the later, active one was the ambiguous badge that was
  fixed; the earlier emoji version is overridden/dead). Not removed (minimal edits).

## 9. Verification

- Pure env‑resolution contract test: **passed** deterministically.
- Central + sync source‑pins: passed during a healthy sandbox window; re‑confirmed
  via direct grep (`SYNC_REPORT_STATUS` default `physician_approved`;
  `new_status=SYNC_REPORT_STATUS`).
- Toolbar edits confirmed via the authoritative editor (post‑sync block + badge map).
- The 9.8k‑line `toolbar_manager.py` cannot be mirrored intact by the Linux test
  mount (known FUSE truncation); its source‑pin **auto‑skips** there and **runs for
  real on the Windows source build**. No existing test pins the old value
  (`test_refresh_report_column`, `test_report_status_circuit_breaker` unaffected).

**Run on Windows:**
`python -m pytest tests/code/system/test_patient_sync_report_status.py -q -p no:debugging`

**Live GUI check:** open a patient → click the Cloud "Sync Patient Data with
Server" → confirm the report status becomes **Physician Approved** (badge `MD✓`),
on the Patient Tab, the Main Page pill, and the report editor.
