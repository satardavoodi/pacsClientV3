# Online Consultation (Education submodule) — as-built record (2026-06-06)

**Status:** implemented + unit-verified (72/72 in `tests/code/cloud_consultation`,
`tests/code/identity`, `tests/code/education_online_consultation`); plugin mirrors
307/307. Live A→B→A round-trip QA pending (needs two machines / two Google accounts).

Builds on `docs/plans/cloud-consultation/GOOGLE_DRIVE_CONSULTATION_PLAN_2026-05-31.md`
(R2) — Phases 0–6 were already implemented; this records **Phase 7: the production
wiring + the Education ▸ Online Consultation submodule**.

## 1. What changed (2026-06-06)

| Area | Change |
|---|---|
| `modules/education/online_consultation/` | **NEW submodule**: `consultation_page.py` (the tab: Google chip + New consultation… + Inbox / Sent / Notifications), `study_select.py` (multi-select local-study picker + `build_export_callable` staging via the EXISTING `export_studies_to_offline_cloud`), `respond_dialog.py` (assignee opinion → `record_and_upload_response`), `status_labels.py` (direction-aware Pending/Sent/Received/Answered/Closed mapping), `launcher.py` (open the tab from anywhere), `__init__.py` (`online_consultation_available()` = Identity flag AND cloud flag). |
| `modules/education/education_module_redesigned.py` | Adds the "Online Consultation" tab — **only when both flags are on**; guarded `try/except`; `last_instance()` weakref + `show_online_consultation()` for the launcher. Flag-off ⇒ Education renders byte-identically. |
| `modules/cloud_consultation/notifications/autostart.py` | **NEW** `ensure_consultation_poller(auth_user)` — idempotent app-level poller singleton (parented to `QApplication`), restarts on identity change, no-ops when flag off / no Google identity. |
| `modules/cloud_consultation/notifications/detect.py` | **NEW** `find_response_updates(transport, outgoing_rows, known_ids)` — originator-side: detects responses uploaded into my sent consultations. |
| `modules/cloud_consultation/notifications/poller.py` | Scan thread now also checks outgoing `uploaded/downloaded/reviewed` rows → `response_received` notification + local status `answered`. Assigned-scan unchanged; also stashes `from_handle` on incoming rows. |
| `modules/cloud_consultation/consultation/workflow.py` | Best-effort `_notify()` hooks: sent (`upload_done`), downloaded (`download_done`), response sent / **NEW `close_consultation()`** (`consultation_updated`, state-machine-guarded `… → closed`). |
| `modules/cloud_consultation/ui/account_popup.py` | "New consultation" now routes to Education ▸ Online Consultation (falls back to the bare dialog); new "Open Online Consultation (Education)" entry. |
| `modules/cloud_consultation/ui/account_hook.py` | Calls `ensure_consultation_poller()` at attach time (guarded). |
| `config/cloud_consultation/cloud_consultation.json` | **NEW — flag ON** (`{"enabled": true}`): consultation leaves test mode for this source build. Identity flag was already on; OAuth Desktop-app client config already at `config/identity/google_oauth.json`. |

## 2. Architecture (unchanged boundaries)

```
account pill ▸ AccountPopup ──link──▶ Education ▸ Online Consultation tab
                                         │ picker → export engine (UNCHANGED offline_cloud)
                                         │ compose → seal envelope → CloudSyncEngine.upload → share
                                         ▼
modules/Identity (creds only)  ──vends──▶ GoogleDriveTransport (drive.file scope)
ConsultationPoller (QApplication-level): assigned→inbox+notify · responses→answered+notify
```

* Identity owns credentials; consultation never sees tokens. Server login untouched.
* The Offline Cloud package engine is reused **unchanged**; the envelope is a sibling
  `consultation.json` (integrity = SHA-256 of every package file).

## 3. Invariants (keep)

1. **Double-flag gate:** the Education tab and poller must remain inert when either
   `AIPACS_IDENTITY_MODULE` / `config/identity/identity.json` or
   `AIPACS_CLOUD_CONSULTATION` / `config/cloud_consultation/cloud_consultation.json`
   is off. `online_consultation_available()` is the single gate — don't bypass it.
2. **Internal statuses are frozen** (`pending|uploaded|downloaded|reviewed|answered|closed|conflict`,
   state machine in `sync/state_machine.py`). The clinical labels
   (Pending/Sent/Received/Answered/Closed) are **display-only**, direction-aware, in
   `status_labels.py`. Never persist a display label.
3. **Engine reuse, not forks:** study staging goes through
   `export_studies_to_offline_cloud` (a staging dir is just a folder-path "server");
   `build_export_callable` must keep raising on `ok=False` so a broken package can
   never upload.
4. **All blocking work off the UI thread** (connect / export+upload / download /
   respond run in QThread workers; poller scans in `_ScanThread`).
5. **Poller is a singleton** on `QApplication` (`_aipacs_consultation_poller`),
   restarted only when the Google identity changes; `ensure_consultation_poller`
   must never raise into callers (title bar / Education construction).
6. **`close_consultation` validates via `assert_transition`** — keep the terminal
   `closed` semantics; notifications are best-effort (`_notify` swallows).
7. Education flag-off rendering stays byte-identical (guarded import + `try/except`
   around the tab block).

## 4. Tests

```
python -m pytest tests/code/cloud_consultation tests/code/identity tests/code/education_online_consultation -q -p no:debugging
```
New guards: `tests/code/cloud_consultation/test_response_detection_and_close.py`
(response detection, close lifecycle + illegal-transition, workflow notifications)
and `tests/code/education_online_consultation/test_online_consultation_submodule.py`
(flag gating, label mapping completeness, export staging incl. failure paths).

## 5. Known limits / next steps

* **PHI:** consumer Gmail is NOT HIPAA-eligible — real patient data requires Google
  Workspace + BAA (plan §10.1). Current client config is suitable for
  de-identified/teaching cases and pilots.
* Viewer ingest of a downloaded package still goes through the existing Offline
  Server import flow (the page points the user there after a verified download);
  one-click "ingest + open in viewer" is a future step.
* OAuth client in *Testing* mode expires test-user grants every 7 days (plan §9) —
  move the consent screen to *In production* (or Workspace *Internal*) for real use.
* Same-account multi-provider (Telegram/Instagram) slots into
  `modules/Identity/providers/` + `registry.py`; consultation code needs no changes.
