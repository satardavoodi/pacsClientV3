# `modules/cloud_consultation` — Drive-backed physician consultation (Phases 2–3)

Moves AI-PACS **Offline Cloud package folders** to/from a cloud provider so studies
can be shared between physicians. Reuses the existing package format unchanged
(`PacsClient.utils.offline_cloud`) — the cloud is just a transport.

## Boundaries
- Owns the `CloudTransport` abstraction + the package mirror engine.
- Depends on `modules/Identity` **only** for authenticated credentials (it performs
  no OAuth and never touches the AI-PACS server login).
- Default **OFF** (`AIPACS_CLOUD_CONSULTATION` / `config/cloud_consultation/cloud_consultation.json`).
  Phase 2 adds no app-startup wiring, so it is inert until the Phase-6 UI lands.

## What ships in Phase 2
- `transport/base.py` — `CloudTransport` ABC + `RemoteEntry` / `ShareInfo` /
  `RemoteChange` / `TransferProgress`.
- `transport/google_drive.py` — `GoogleDriveTransport` (Drive v3): ensure/find/make
  folder, list, **resumable upload**, **atomic download** (`.part` + `os.replace`),
  delete, share, change-cursor. Plus `build_google_drive_transport(aipacs_user, subject_id)`.
- `package_sync.py` — transport-agnostic `mirror_folder_to_remote` /
  `mirror_remote_to_folder` and `upload_offline_package` / `download_offline_package`.

## Typical use (once a Google identity is connected via the Identity module)
```python
from modules.cloud_consultation.transport.google_drive import build_google_drive_transport
from modules.cloud_consultation.package_sync import upload_offline_package, download_offline_package

transport = build_google_drive_transport(aipacs_user="dr_a", subject_id="<google sub>")

# Physician A: push an exported package folder to Drive
remote_folder_id = upload_offline_package(transport, r"...\\user_data\\cloud_consultation\\outgoing\\<id>")
transport.share(remote_folder_id, "dr.b@hospital.org", role="reader")

# Physician B: pull it back into a local package dir, then ingest with the existing engine
download_offline_package(transport, remote_folder_id, r"...\\incoming\\<id>")
```

## Adding another provider later
Implement `CloudTransport` (e.g. `OneDriveTransport`); `package_sync` and the future
sync engine/UI are unchanged.

## What ships in Phase 3 (consultation envelope)
- `consultation/models.py` — `ConsultationEnvelope` / `ConsultationParty` /
  `ConsultationResponse` + `ConsultationStatus` (pending → uploaded → downloaded →
  reviewed → answered → closed, plus conflict).
- `consultation/envelope.py` — `build_envelope` / `seal_envelope` / `read_envelope` /
  `verify_integrity` / `add_response`. The envelope is a **sibling `consultation.json`**;
  the clinical `manifest.json` / `package.db` / `patients/` are never modified, so the
  guarded offline engine stays byte-identical. Integrity = SHA-256 of every package
  file except the envelope itself, so DICOM/DB/manifest tampering is detected.
- `consultation/service.py` — `seal_package_as_consultation`,
  `open_consultation_package` (read + verify), `record_response`.
- Backward compatible: an ordinary offline package (no `consultation.json`) reads as
  "not a consultation".

## What ships in Phase 4 (resumable sync engine)
- `database/consultation_db.py` — `consultations`, `consultation_files`
  (per-file resume state) and `consultation_events` (audit) tables, self-initializing.
- `sync/engine.py` — `CloudSyncEngine.upload` / `.download`: drives any
  `CloudTransport`, records each file's state, and **resumes** by skipping files
  already `done` with a matching SHA-256 (covered by a forced-failure test).
- `sync/state_machine.py` — allowed status transitions + `detect_conflict`
  (same version + divergent content fingerprint = conflict).
- `sync/worker.py` — a `QThread` wrapper so transfers run off the UI thread.

## What ships in Phase 5 (assignment + notifications)
- `consultation/assignment.py` — `assign(transport, consultation_id, assignee_email)`:
  shares the uploaded remote folder with the assignee and records assignee + audit event.
- `database/notifications_db.py` + `notifications/inbox.py` — an unread/read/archived
  notification queue (kinds: consultation_assigned/updated, response_received,
  upload/download_done, sync_error).
- `notifications/detect.py` — `find_assigned_consultations`: the assignee's side reads
  each remote `consultation.json` and returns the ones assigned to them (drives the poller).
- `notifications/service.py` (`NotificationService` QObject) + `notifications/poller.py`
  (`ConsultationPoller` — QTimer + off-thread scan) — thin Qt, wired in Phase 6.

## What ships in Phase 6 (UI + workflow)
- `consultation/workflow.py` — `create_and_upload_consultation` (seal → DB → upload →
  share), `download_and_open_consultation` (download → verify → read → record),
  `record_and_upload_response` (re-seal → upload into the shared folder).
- `ui/account_popup.py` — `AccountPopup`: opens under the top-right user pill (server
  identity + connected Google + consultations + notifications); replaces the Phase-1 menu.
- `ui/compose_dialog.py` — `ConsultationComposeDialog` (compose + upload + assign, on a
  worker thread). Needs the caller to pass the selected studies as
  `selection={label, study_uids, export_callable|package_root}` (the patient-list
  "New consultation" action wires this).
- `ui/inbox_widget.py` — `ConsultationInbox` (download & review with an integrity gate).
- `ui/account_hook.py` + a guarded, flag-gated call in `mainwindow_ui.py`.

Ingesting a verified package into the local DB reuses the existing
`validate_offline_cloud_package` / `sync_offline_cloud_study_to_local`, invoked from the
patient list once `download_and_open` reports integrity OK.

## Status
Phases 0–6 implemented. Authoritative test run (Windows venv, no FUSE mount):

    python -m pytest tests/code/cloud_consultation tests/code/identity -q

## Tests
`tests/code/cloud_consultation/` and `tests/code/identity/` (hermetic — fakes only):

    python -m pytest tests/code/cloud_consultation tests/code/identity -q
