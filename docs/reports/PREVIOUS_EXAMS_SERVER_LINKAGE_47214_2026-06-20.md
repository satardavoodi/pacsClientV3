# Previous Exams — live server probe for patient 47214 (2026-06-20)

**Server:** Razi `192.168.2.222:50052` (socket). **No auth token required** for
`GetPatientStatus` / `GetPatientReceptionHistory` on this deployment.
**Patient:** 47214 — RAHMATI^JAVAD, National ID **0491341911**.
**Expected prior exam:** Patient/Reception **43373**.

## Question
Does the server return the previous exam (43373) when the workstation opens 47214?

## Answer: NO — not when queried by 47214.

The previous-exam DATA exists and is correctly linked under the national code, but
the server only returns it when queried by 43373 or 44030 — **not** when queried by
47214 (the reception the workstation actually opens).

### `GetPatientReceptionHistory` grouping (same national code 0491341911 throughout)
| query `reception_id` | receptions returned |
|---|---|
| **47214** (current) | **[47214] only** ❌ |
| 44030 | [47214, 44030, 43373] ✅ |
| 43373 | [47214, 44030, 43373] ✅ |

The three real exams of this person:
- **47214** — MR `SPIN^New Exam.M.` (20260618) + DOC `Documents`
- **44030** — DX `Foot` (20260530)
- **43373** — MR `BRAIN^BRAIN` (20260524, 16 series / 343 images)

### `GetPatientStatus`
- `GetPatientStatus(47214)` → 2 studies, **both belonging to 47214** (MR + DOC). Single-PatientID only; never crosses to 43373. (Working as documented.)
- `GetPatientStatus(43373)` → 1 study (BRAIN MR). Confirms 43373 exists.

### `GetPatientList` national-code filter
`GetPatientList` with `national_code` / `nationalCode` / `national_id` is **ignored**
(returns the default full list; patient rows carry no national_code). So the client
cannot enumerate same-person receptions by national code as a workaround.

## Root cause (server-side)
Reception **47214 is not joined into the shared patient / national-code group** that
44030 and 43373 belong to. The server's reception grouping (risPatientId / national
linkage) clearly works — 44030 and 43373 each return all three receptions — but the
newest reception (47214, 20260618) is isolated: its own history returns only itself,
even though its national code (0491341911) is correctly resolved.

This is a **server-side reception-linkage/sync gap**, not a workstation bug. The
client "Previous Exams" feature queries `GetPatientReceptionHistory(current_patient_id)`
and will display the priors the moment the server returns them for 47214 — exactly as
it already does for 43373 / 44030.

## Recommended fix (server)
Ensure the newest reception is linked to the existing national-code patient group so
`GetPatientReceptionHistory(47214)` returns all three receptions (symmetric with the
43373 / 44030 results). Candidates:
- Re-run the reception sync for 47214 (server doc §error-table: `POST /api/receptions/{id}/sync`).
- Fix `reception_sync` so a new reception attaches to the existing risPatientId/national
  group at ingest (the grouping that already works for 43373/44030).

## Client status
The workstation feature is implemented and correct. No client change makes 43373 appear
for 47214 with the current server endpoints (no national-code enumeration is exposed).
Once the server links 47214, the red "Previous Exam" button will light up and list
44030 + 43373 automatically.

### Optional client hardening (only if the server cannot be made symmetric)
If the server later exposes a national-code → receptions lookup (or makes
`GetPatientReceptionHistory(current)` symmetric), no further client work is needed.
A client-only fan-out is **not** possible today because national-code enumeration is
not exposed.
