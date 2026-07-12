# Internal-Center (INO) Assignment — Foundation (as-built, 2026-07-09)

**Status (2026-07-10): feature is now DEFAULT-ON** (`is_enabled()` returns True unless
`AIPACS_INO_ASSIGNMENT=0`/`false`/`off`/`no` or config `{"enabled": false}`; shipped
`ino_assignment_config.json` has `"enabled": true`). The historical notes below say
"default OFF" — that was the original rollout posture; the switch is now ON.

Original note — No UI wired yet (the button/dialog
comes in the next step). The external **Consultation / External Assignment** workflow is **untouched**.

This establishes the **separate path** for INO's *internal, same-center* assignment (assign a
radiologist/typist to a reception), fully isolated from the AI-PACS Consultation/Drive/payment flow —
per the separation requirement. Review background:
`docs/reports/ASSIGNMENT_WORKFLOWS_REVIEW_INO_VS_EDUCATION_2026-07-09.md`.

## New, isolated modules

| File | Role |
|---|---|
| `modules/network/ino_assignment_models.py` | State model + constants + **Persian/English labels** (distinct "Internal Assignment" terminology, never "consultation"). Pure stdlib. |
| `modules/network/ino_assignment.py` | Isolated **API service**: `InoAssignmentClient` (REST) + `InternalAssignmentService` façade + config resolver + **permission handling** + dedicated logging. |
| `modules/network/ino_assignment_history.py` | **Separate history** store (per-center JSONL under the profile data root) — never shares storage with consultation records. |
| `config/ino_assignment_config.json` | Center-specific config: `enabled` (default false) + `assignment_api_base_url`. |
| `tests/code/network/test_ino_assignment.py` | Model/client/history tests + an **AST isolation guard**. |

## Separation guarantees (the Important Rule)

* **Zero coupling.** The internal modules import only `reception_api_config`, `socket_token_manager`,
  and their own siblings — **nothing** from `cloud_consultation` / `education` / `Identity` / Google /
  Drive / payment. Enforced by `test_internal_assignment_imports_are_isolated` (AST-parses the imports).
* **Cannot trigger the external flow.** No image upload, no Drive, no website submission, no payment,
  no cross-center — none of that code is reachable from here.
* **Default OFF.** `is_enabled()` is false unless `AIPACS_INO_ASSIGNMENT=1` or the config `enabled:true`.
  While off, the service returns `{"disabled": true}` and does nothing — so it can never fire before the
  UI + live endpoint verification land.

## The separate concerns, delivered

* **Separate API service** — `InternalAssignmentService` / `InoAssignmentClient` hitting INO's assign
  endpoints (`GET /api/assign/users`, `GET|PUT /api/patients/{receptionId}/assign`) per
  `ASSIGN_CLIENT_GUIDE_FA.md`. Center-specific base URL: env → `ino_assignment_config.json`
  (`assignment_api_base_url`) → reception base fallback (assign endpoints may run on a different port,
  e.g. :8000).
* **Separate state model** — `ASSIGN_TYPES` (radiologist/typist), `ASSIGNEE_SOURCES`
  (pacs/ris_personnel/ris_user), local actions (assigned/reassigned/unassigned/failed),
  `AssignableUser`, `AssignmentRecord`. Distinct from the consultation state machine.
* **Separate permission checks** — auth uses the logged-in user's JWT; responses are classified
  (`permission` on 403 / Persian "مجاز نیست"…, `auth` on 401) and returned structured for the UI, plus
  a `can_assign()` **client-side gating hook** (single place to add INO permission-id checks later,
  mirroring INO's own web UI). Server-side INO enforcement stays authoritative.
* **Separate labels/messages** — `FEATURE_LABEL_FA = "ارجاع داخلی مرکز"`, type/source/action labels,
  and dedicated messages (`MSG_PERMISSION_DENIED_FA`, …).
* **Separate logs** — dedicated `logging.getLogger("ino_assignment")`, tag `[ino-assignment]`.
* **Separate assignment history** — `ino_assignment_history` JSONL, per-center, independent of the
  consultation DB.
* **Isolated entry point** — `get_internal_assignment_service()` (+ `assign_async`) is the single
  callable the future internal-assignment UI drives. Nothing is wired into a button yet.

## Where the next step plugs in (UI — not done here)

1. A **separate action/button** ("ارجاع داخلی مرکز" / "Assign within center") — distinct from the
   Consultation action — calls `get_internal_assignment_service()`: `list_users(assign_type)` to
   populate a picker, `assign(reception_id, assign_type, assignee_id, …)` to assign, `history()` to show
   past actions. Use `assign_async(..., on_result=…)` to stay off the GUI thread and show the returned
   `permission_denied` / message.
2. Add the `enabled` + base-URL fields to Settings (next to the existing "Reception / Workflow API"
   card) so a center can turn it on and point it at its assign endpoint.
3. Reuse the numeric `ReceptionID` the app already has (same id as report status/approval); realtime
   `study_assigned` handling (socket) is a later, optional enhancement.

## UI increment (2026-07-09) — wired into the existing Report Status popup

The internal-assignment UI is added to the **existing** popup (Patient List → Report column →
`ReportStatusDialog`), NOT a new consultation-style window. New/edited pieces:

* `PacsClient/.../patient_toolbar/internal_assign_ui.py` — `InternalAssignRow` (+ `build_internal_assign_row`
  factory): a compact "ارجاع داخلی مرکز" field in the popup's upper section (alongside Status/Comment)
  showing the **current assignment (loaded live from INO)**, an **eligible-users dropdown** (from INO's
  assign-users endpoint — center/roles/permissions enforced server-side), and an **Assign** button that
  submits via `InternalAssignmentService` off-thread. On success it turns the name **red**, records a
  local notification, and emits back to refresh the row. Permission/auth/disabled results are shown.
* `report_status_dialog.py` — inserts the assign row after the comment (flag-gated: `build_...` returns
  None when the feature is off → popup unchanged) + an `assigned(reception_id, name)` signal.
* `patient_table_widget.py` — (1) connects `dialog.assigned` → `update_reporting_physician_for_patient`
  to refresh the reporter cell immediately (no full reload); (2) `_apply_report_status_display` now shows
  an assigned-but-not-completed name in **RED** (`reporter_display`) — GREEN completed name unchanged.
  Both flag-gated; OFF = byte-identical legacy.
* `modules/network/ino_notifications.py` — local notification store + `NotificationCenter` (Qt signals) +
  `attach_profile_badge(icon_widget)` (red unread dot) + `on_study_assigned(event)` socket entry point +
  `notify_local_assignment(...)`.
* `modules/network/ino_assignment_models.py` — added pure `reporter_display()` + the red/green colours.
* Tests: `test_ino_assignment.py` (+ `reporter_display`), `test_ino_notifications.py`.

### Done vs. staged
**Done:** deliverables 1–8 — Assign field in the popup; eligible-users dropdown; server-side
role/permission enforcement + clear denial messages; current-assignment display; submit through the
INO internal workflow; immediate reporter-cell refresh on success; **red** while pending; **green** when
completed. Notification *infrastructure* (store + center + badge helper + socket entry point).

**Staged (needs the header widget + live socket, do on Windows):**
1. **Profile-icon red badge wiring** — call `ino_notifications.attach_profile_badge(<user/profile icon
   widget>)` once where the top-right user icon is built, and connect its click to a small
   notifications list + `mark_all_read()`. (Badge/store are ready; only the one-line attach + a click
   handler remain — the exact header widget must be identified in the running UI.)
2. **Cross-machine delivery** — subscribe the socket client to `study_assigned` and call
   `ino_notifications.on_study_assigned(event)` for this user (per `ASSIGN_CLIENT_GUIDE_FA.md` §5). Until
   then, only the assigner's own local mirror notification is created.
3. Optional: clicking an assignment notification navigates to / selects the patient row.

## Data-source separation fix (2026-07-09) — Internal tab = INO, External = registry

The Assign column opens the Consultation `ConsultationAssignDialog` (Internal/External tabs). Its
**Internal** tab was showing the **consultation registry** physicians (`consultants(type=internal)`),
not INO center users. Corrected:

* **Live-discovered the real INO eligible-user endpoints** (reception `:8080`, reception token —
  same realm as report status; the guide's `/api/assign/users` returns **404** here):
  * `GET /api/personnel` → radiologists/physicians (→ `assign_type=radiologist`, `ris_personnel`).
  * `GET /api/AdminUser/getCenterUsers` → center users/typists (→ `typist`, `ris_user`).
* **`ino_assignment.py`** `list_assignable_users` now calls those two endpoints (merging for "all"),
  mapped via new `AssignableUser.from_personnel` / `from_center_user`. (Earlier `/api/assign/users`
  path removed.)
* **`assign_dialog.py`** Internal tab now sources users from **INO** via
  `InternalAssignmentService.list_users("all")` and submits selected users through the INO
  internal-assignment API (`_send_ino_internal`) — **not** the consultation registry. The **External**
  tab is unchanged (registry / Drive). Flag-gated: when INO assignment is disabled the Internal tab
  falls back to the previous consultation-internal behaviour (no regression).
* Auth: uses the logged-in reception JWT (no separate token needed — the "jwt malformed" seen while
  probing was only a stale token; a fresh reception token returns 200 on both endpoints).

Tests updated: `test_list_radiologists_from_personnel`, `test_list_typists_from_center_users`,
`test_personnel_mappers`. Minor cosmetic follow-up: the INO card sub-line currently shows the user's
ObjectId as the "address" — can be hidden later (display-only).

## Internal grouping + External source correction (2026-07-10)

Two list corrections in `modules/education/online_consultation/assign_dialog.py`
(+ pure helper in `assign_core.py`):

* **Internal tab now shows INO's TWO user groups SEPARATELY.** INO returns eligible
  internal-assignment users as two distinct groups that must be visually
  distinguished so a reader can tell physicians from secretaries:
  * `GET /api/personnel` → **Physicians** (Personnel / Staff Management, `ris_personnel`).
  * `GET /api/AdminUser/getCenterUsers` → **Users / Secretaries + other** (`ris_user`).
  `list_users("all")` still merges both (each row keeps its `_ino_source`), and the
  renderer now partitions them via the pure `assign_core.partition_ino_groups(rows)`
  → ordered `(group_key, title, rows)` (physicians first, empty groups omitted,
  unknown source → "other"). `_render_internal` draws a bold section header per
  group then the member cards. Non-INO rows (feature-OFF fallback) still render flat.
* **External tab = the AI-PACS WEBSITE registered users.** It previously filtered the
  consultation registry to `consultant_kind == external`; the center's registered
  users are registered as `type=internal` (registry-only delivery), so after the
  Internal tab moved to INO the External list looked **empty**. Fixed: `_on_consultants`
  now sets `_external_rows = list(rows)` — **all** `/consultants` rows (the AI-PACS
  website registered-user source). The registry `type` remains a per-consultant
  DELIVERY detail resolved at send time (`decide_route`), not a display filter, so the
  external send/hub gate is unchanged.

### UI/UX polish (2026-07-10)
Same `assign_dialog.py` + `assign_core.py`:
* **Roomier dialog** — min size 640×720 (default 720×800) and the user list has a
  320 px minimum height, so several cards show at once and none are clipped.
* **Readable cards** — larger name (14 px, 600), role/specialty on a secondary
  muted line, `View profile` on the right. The raw **ObjectId is never shown** as
  an "address" (`assign_core.is_objectid_like`); a real e-mail/hub address still is.
* **Clean error messages** — `assign_core.humanize_server_error()` turns a raw
  server error (e.g. the Express `Cannot PUT /api/patients/{id}/assign` **HTML 404
  page** seen when the write endpoint isn't configured) into one plain sentence;
  the status line now colours info/error/success (`_set_state`). The
  `Cannot PUT …/assign` in the screenshot is the *write* endpoint being absent on
  this center — feature stays OFF until that assign endpoint is confirmed.

Pure/unit-tested: `tests/code/education_online_consultation/test_assign_core.py`
(`test_partition_ino_groups_*`, `test_is_objectid_like`,
`test_humanize_server_error_*`). `modules/education` is **plugin-mirrored** — run
`tools/dev/sync_plugin_mirrors.py` (+ `verify_plugin_mirrors.py`) on Windows after
these edits. `tools/dev/test_internal_assignment.ps1` enables the feature, syncs the
mirror, runs the targeted tests, and launches the source build for GUI verification.

## Real assign WRITE endpoint — the PACS :8000 service (2026-07-10, per ASSIGN_CLIENT_GUIDE_FA)

**Correction of a port detour.** The assign endpoints 404'd earlier because they
were probed on the **RIS reception REST (:8080)**. The authoritative guide
(`ASSIGN_CLIENT_GUIDE_FA.md`) shows the assign REST API lives on a **separate PACS
HTTP service, port 8000** — the same PACS server AI-PACS already reaches over the
socket (:50052). So there are **two services**:

| Concern | Base | Endpoint |
|---|---|---|
| Eligible-USER lists (verified 200) | RIS `:8080` | `GET /api/personnel`, `GET /api/AdminUser/getCenterUsers` |
| ASSIGN write | PACS `:8000` | `PUT /api/patients/{ReceptionID}/assign` `{assign_type, assignee_id, assignee_name, assignee_source, study_uid}` |
| ASSIGN read | PACS `:8000` | `GET /api/patients/{ReceptionID}/assign` → `{assignment:{radiologist,typist,…}}` |

`ReceptionID` = the **numeric** reception number (= PACS `PatientID`, what AI-PACS
already holds). Assign supports **both** `radiologist` and `typist`, honours
`study_uid` (empty = all studies of the reception), and fires the targeted
`study_assigned` socket event. The RIS-side `PATCH /api/Reports/reception/{mongoId}/radiologist`
seen in the web worklist is only the RIS→PACS bridge (radiologist-only) that itself
calls this PACS endpoint — a PACS client (AI-PACS) uses the PACS path directly.
Socket `AssignStudy` on :50052 is the documented alternative (deeper integration, later).

`ino_assignment.py` now:
* two bases — `_ris_base` (:8080, user lists) and the assign base
  (`get_ino_assignment_base_url()` → env/config → **derived PACS `:8000`** → reception);
* `assign()` = `PUT {pacs:8000}/api/patients/{rid}/assign` with the full body (both types);
* `get_assignment()` = `GET {pacs:8000}/api/patients/{rid}/assign` → `assignment`;
* the dialog assigns each selected user by their own role (physician→radiologist,
  center user→typist).
* Config: `assignment_api_base_url` sets the PACS base; empty auto-derives `:8000`.

Tests: `test_assign_puts_to_pacs_patients_endpoint`,
`test_assign_typist_supported_defaults_source`, `test_assign_missing_assignee_id`,
`test_get_assignment_reads_pacs_assignment`, `test_derive_pacs_http_base_swaps_port_to_8000`.

**NOT yet done — one live confirm on the source build (feature ON):** confirm the
PACS `:8000` service is reachable from the workstation and a `PUT …/assign`
succeeds (the browser can't reach :8000 cross-port; AI-PACS/Python can). The live
write test was also declined by the write-safety classifier here. If `:8000` is not
exposed at a center, set `assignment_api_base_url` or switch to the socket transport.

## Socket transport + Server-Settings config (2026-07-10)

**Socket is the DEFAULT transport (guide §4).** `modules/network/ino_assignment_socket.py`
(pure stdlib) sends `AssignStudy` over the PACS imaging socket (`:50052`) using
framed JSON `[4-byte BE len][UTF-8 JSON]`, reusing the app's existing socket token
(no re-Login). `ino_assignment.assign()` picks the transport via
`get_ino_assignment_transport()` (env `AIPACS_INO_ASSIGNMENT_TRANSPORT` → config
`transport` → **default `socket`**). The fallback is **bidirectional on a
connection-level failure**: `socket` (default) assigns over the socket and falls
back to REST `:8000` only if the socket can't deliver; `rest` assigns over `:8000`
and falls back to the socket if `:8000` is unreachable. A real server answer
(2xx/4xx/5xx) is never overridden by a fallback. Socket is preferred because it's
the same authenticated socket AI-PACS already holds and needs no extra HTTP service
exposed. The socket module is in the isolation-guard file list.

**Server Settings (per-center/server config).** `settings_ui/server_settings.py`
now has an **Internal Assignment (INO)** subsection under the Reception/Workflow
API card: an enable checkbox, an **Assign base URL** field (PACS `:8000`; empty =
auto-derive from the reception host), and a **Transport** dropdown (REST `:8000` /
Socket `:50052`), with Save/Load. It persists via
`ino_assignment.save_ino_assignment_config()` (merges keys into
`ino_assignment_config.json`, preserving the rest). So any location/server can be
pointed at the right host from the UI without editing config files.

New config keys: `transport` (`rest`|`socket`). Tests:
`test_transport_defaults_to_rest`, `test_transport_socket_uses_socket_not_rest`,
`test_rest_falls_back_to_socket_on_connection_error`, `test_save_config_merges_keys`
(+ the isolation guard now covers `ino_assignment_socket.py`). Verified in the
sandbox: **65 pass** (the lone humanize-error failure was FUSE mount staleness —
the on-disk regex is correct and a fresh import produces clean output).

## Making it work in the FROZEN / installed build (2026-07-10)

Two things are needed for the installed (non-source) build to run this feature:

1. **Education plugin mirror synced.** The dialog/core live in the plugin-mirrored
   `modules/education/online_consultation/` → their payload copies under
   `builder/plugin package/packages/education/payload/python/...` must match. Ran
   `tools/dev/sync_plugin_mirrors.py` (only `assign_core.py` + `assign_dialog.py`
   drifted); `verify_plugin_mirrors.py` → **412 pairs match, 0 drift**. Re-run the
   sync after any future edit to those two files.
2. **INO modules pinned as hidden imports.** `modules/network/ino_assignment*.py`,
   `ino_report_workflow.py`, `ino_notifications.py` are imported **lazily** (inside
   functions) from core UI, so PyInstaller's static analysis of `main.py` never
   discovers them — without help they'd be **absent from the frozen build** and the
   feature would die with `ModuleNotFoundError` (the classic "works in source,
   missing in installed build"). `imports_summary.json` did not capture them.
   Fixed by adding the six modules to `load_hiddenimports(extra=[…])` in
   `builder/spec/appA_workstation.spec`. Keep that list in sync with
   `modules/network/ino_*`. (Nuitka path, if used, follows lazy imports more
   deeply, but verify the six modules are present after a Nuitka build too.)

After both, rebuild the installer (`builder/build_release.py`) — the release gate
runs the frozen-PYZ probe. The feature stays **default-OFF** until enabled in
Settings. **As of 2026-07-10 the feature is DEFAULT-ON**, so a fresh install runs it
active; a center can turn it off in Settings or via `AIPACS_INO_ASSIGNMENT=0`.

## End-to-end assign → red icon → notification → navigate (2026-07-10)

An audit of the "Assign column" flow found the **entire post-assign chain was
unwired** (each stage below was missing or local-only). Fixed so the workflow is
server-derived and persistent, not locally forced:

1. **Assign-column dialog emits success.** `ConsultationAssignDialog` now has an
   `internal_assigned(reception_id, name)` signal, emitted from `_on_ino_assign_done`
   only when `svc.assign` returned `ok` (a real server 2xx / socket accept, which
   also wrote a `server_ok` history row). Previously it only called `self.accept()`.
2. **Assign icon = server-confirmed red, persistent.** New
   `ino_assignment_history.current_assignee(reception_id)` returns the latest
   `server_ok` assignee (unassign clears; `failed`/local-only never count). The
   Assign-column render reads it → red `fa5s.user-check` (`#ef4444`) when assigned;
   because history is on disk, the red **survives refresh/reopen** and is never a
   local-only flag. `patient_table_widget._on_assign_clicked` connects
   `internal_assigned` → `_on_internal_assigned_confirmed` →
   `refresh_assign_icon_for_patient` (O(1), no server call — reads the `server_ok`
   record). The assigned icon colour changed blue→**red**.
3. **Notification created for the assignee.** On confirmed assign the dialog calls
   `ino_notifications.notify_assignment(reception_id, assignee_name, patient_name)`
   → an `assignment_in` (internal) record carrying `reception_id`. `_center_emit`
   bumps `unread_changed` → the badge.
4. **Profile badge + click.** `mainwindow_ui` now calls
   `ino_notifications.attach_profile_badge(user_icon_label)` (red unread dot) and
   makes the icon open `open_notifications_popup(...)` on click. Previously
   `attach_profile_badge` was never called.
5. **Notification click → navigate (internal only).** The popup lists notifications;
   clicking one `mark_read`s it and calls `navigate_to(reception_id)` →
   `set_navigate_callback` (registered in `mainwindow_ui` to
   `PatientTableWidget.select_patient_by_id`) which `search_in_table` + selects +
   scrolls to the row. It never opens the consultation / Drive flow.

Files: `modules/network/ino_assignment_history.py` (+`current_assignee`),
`modules/network/ino_notifications.py` (+`notify_assignment`, `set_navigate_callback`/
`navigate_to`, `open_notifications_popup`, click-to-open badge, `patient_name` field),
`modules/education/online_consultation/assign_dialog.py` (+`internal_assigned` signal,
notify on success), `PacsClient/.../home_ui/patient_table_widget.py` (icon bound to
history, `_on_internal_assigned_confirmed`, `refresh_assign_icon_for_patient`,
`select_patient_by_id`), `PacsClient/.../mainwindow_ui.py` (badge + navigate callback).
Tests: `test_ino_notifications.py` (`notify_assignment`, `navigate_to`),
`test_ino_assignment.py::test_current_assignee_is_server_confirmed`.

**Mirror + verify:** `assign_dialog.py` changed → re-run `tools/dev/sync_plugin_mirrors.py`
on Windows before building. NEEDS live source-build verification of the full 49628
flow (assign → red icon → unread badge → click → patient selected).

## Consultation UI: separation + assignment details (2026-07-10)

Two UI refinements (both in plugin-mirrored `modules/education/online_consultation/`):

* **Internal vs External clearly separated in the Online Consultation list.**
  `consultation_page._registry_row` now draws a coloured **badge** ("Internal"
  blue `#3b82f6` / "External" amber `#f59e0b`) and a matching **left-accent
  border** on every row, driven by `assign_core.consultant_kind(row)`. The
  distinction is immediate and consistent across Inbox/Sent.
* **Assignment details in the Assign popup.** `ConsultationAssignDialog` upper
  section gained a "Current assignment" panel (`_load_assignment_details`) that
  reads the actual assignment record (`ino_assignment_history.read_for_reception`,
  latest `server_ok`) and shows **Assigned to · Type (Internal/External) ·
  Assigned by · When · Comment**. Hidden when there's no assignment. The
  "Assigned by" id is resolved to the logged-in user's name when it's the current
  user (`_resolve_assigner_name`). **Comment capture** was plumbed through: the
  dialog's note is passed as `svc.assign(..., comment=...)`; `AssignmentRecord`
  gained a `comment` field and the façade records it, so the popup can show it.

Files: `consultation_page.py`, `assign_dialog.py` (both mirrored — resync),
`modules/network/ino_assignment.py` (façade `comment=`),
`modules/network/ino_assignment_models.py` (`AssignmentRecord.comment`).

## Assignment details card + lifecycle status actions (2026-07-10)

**Structured card.** The Assign popup's "Current assignment" area is now a proper
card: a header with a **status badge**, then **labeled rows** (👤 Assigned to · ✍️
Assigned by · 🏷️ Assignment type · 🕒 Assigned at · 💬 Comment — the comment row
hides when empty), then the status actions. No more one-line sentence.

**Lifecycle status (`ino_assignment_models`).** `STATUS_ACTIVE / COMPLETED /
DEACTIVATED / CANCELLED` with labels + colours, and the pure
`resolve_assignment_status(rows)` derived from the real history:

| history | status |
|---|---|
| `failed` only, or a `server_ok=False` assign | **""** (never "assigned" from a local-only record) |
| server-confirmed `assigned`/`reassigned` | `active` (amber) |
| + local `status_changed: completed` | `completed` (green) |
| + local `status_changed: deactivated` | `deactivated` (gray) |
| + server-confirmed `unassigned` | `cancelled` (red) |

**Which transitions are real (be honest in the UI).** `SERVER_BACKED_STATUSES =
(active, cancelled)`:
* **Cancel / Unassign → SERVER.** `InternalAssignmentService.unassign()` reuses
  `PUT /api/patients/{id}/assign` with an **empty `assignee_id`** (the contract has
  no dedicated unassign endpoint; `InoAssignmentClient.assign(..., allow_empty=True)`).
  The server's real answer is returned — a rejection records a `failed` row and the
  UI does **not** show it as cancelled. Only a confirmed clear records `unassigned`
  (→ `current_assignee` returns None → the patient-list Assign icon goes back to gray).
* **Mark Active / Completed / Deactivate → LOCAL.** INO exposes **no endpoint** for
  these, so `set_assignment_status()` records them in the internal history
  (`server_ok=False`, `action=status_changed`) and returns `local: True`. The card's
  hint text says so plainly; they are never presented as server-confirmed.

**Interaction contract.** Actions run off-thread, the UI updates **only after the
result returns** (`_ino_status_done`), the card reloads from the record, the
patient-list indicator refreshes (via `internal_assigned`), and every change/error
is logged under `[ino-assignment]`. Allowed transitions are gated per current status.
Assigning over an existing assignment is recorded as a **reassign**
(`is_reassignment=True`).

Tests: `test_resolve_assignment_status` (6 cases), `test_status_labels_and_colors`,
`test_unassign_sends_empty_assignee_and_records`,
`test_set_status_local_states_are_marked_local` — **47 network + 37 core tests green.**

## Assign-column icon reflects the lifecycle status (2026-07-10)

The Assign icon is no longer just red/gray ("assigned / not assigned") — it renders the
**current lifecycle status**. One pure mapping,
`ino_assignment_models.assign_icon_for_status(status, assignee_name)`, is used by **both**
the initial row render (`add_patient_data`) and the post-change repaint
(`refresh_assign_icon_for_patient`) via the shared
`PatientTableWidget._assign_icon_state()`, so they cannot drift.

| Lifecycle status | Icon (fa5s) | Colour | Meaning |
|---|---|---|---|
| `active` | `user-check` | **#ef4444 red** | assigned, action needed |
| `completed` | `check-circle` | **#10b981 green** | done (shape **and** colour differ) |
| `deactivated` | `user-minus` | #6b7280 gray | inactive |
| `cancelled` | `user-slash` | #9ca3af gray | crossed-out |
| *(never assigned)* | `user-times` | #6b7280 gray | neutral |

Tooltips follow the state ("Assigned (active) — Dr. X", "Assignment completed — …", …).

**Where the state comes from (the important rule).** The icon is derived from the
**persisted** assignment record — `ino_assignment_history.current_assignment_details()` →
`resolve_assignment_status()` — whose assign/unassign rows are **`server_ok`-gated**. So:

* a **local-only / failed** assign (`server_ok=False`) yields **no** status → the icon
  stays neutral. The icon can never be driven by transient UI state.
* the state is read from disk on every render → it **persists across refresh and reopening**
  the patient list.
* after a status change the dialog emits `internal_assigned` → the table calls
  `refresh_assign_icon_for_patient()` → repaint from the record.

**Honest caveat (unchanged):** only `active` (assign/reassign) and `cancelled` (unassign)
are *server-backed*. INO exposes **no endpoint** for `completed` / `deactivated`, so those
are persisted local workflow states. The icon reflects the record; it does not claim INO
confirmed a state INO has no concept of.

When the INO assignment feature is disabled, `_assign_icon_state()` returns None and the
column keeps its legacy `is_assigned`/`assign_to` kwargs behaviour unchanged.

Tests: `test_assign_icon_for_status` (6 states, each asserted visually distinct from active
red) and `test_assign_icon_end_to_end_from_history` (server assign → red; local completed →
green; server unassign → gray cancelled). **46 network tests green.**

## ONE internal-assignment engine, TWO entry points (2026-07-10)

**The bug.** Internal assignment had **two UI implementations** of the same engine.
Both called `InternalAssignmentService`, but the Reporting-Physician path was a
thinner, older re-implementation:

| | Assign column | Reporting Physician (old) |
|---|---|---|
| User list | `list_users("all")` → personnel **+** center users, grouped | `list_users("radiologist")` → **physicians only**, flat combo |
| Assign call | `assign(..., comment, is_reassignment)` | `assign_async(...)` — **no comment, no reassign flag** |
| Current assignment | local history record (assignee/assigner/when/comment/status) | server `current_assignment()` — **name only** |
| Lifecycle actions | Active / Completed / Deactivate / Cancel | **none** |
| Notification | `notify_assignment` (`assignment_in`) | `notify_local_assignment` (`assignment_out`) — **different kind** |
| Patient-list refresh | Assign icon **+** reporter | reporter only — **icon never refreshed** |

**The fix — one component in CORE.**
`PacsClient/pacs/workstation_ui/home_ui/internal_assignment_panel.py` is now **THE**
internal-assignment component: `InternalAssignmentPanel` (grouped INO users, comment,
assign/reassign, current-assignment card with status badge, lifecycle actions,
notification, `assigned` signal) + `InternalAssignmentDialog` wrapping it.

```
Assign column → ConsultationAssignDialog → Internal tab ─┐
                                                         ├─► InternalAssignmentPanel
Reporting Physician → Report popup → "مدیریت ارجاع…" ────┘      (one engine:
                                                                InternalAssignmentService,
External → ConsultationAssignDialog → External tab (UNCHANGED)   INO users, same API,
                                                                 status model, permissions,
                                                                 notifications, history)
```

* It lives in **core**, not the education plugin — internal assignment is an INO/core
  feature and must not depend on the purchasable consultation module. Dependency
  direction is **education → core**, never core → education.
* `internal_assign_ui.py` (Report popup) is now an **entry point only**: a summary line
  + "مدیریت ارجاع…" button that opens the shared dialog. **All** of its legacy logic
  (physicians-only combo, `assign_async`, `notify_local_assignment`) was deleted.
* `assign_dialog._build_internal_tab()` **embeds the same panel** when INO assignment is
  enabled and re-emits `internal_assigned`; the legacy internal renderers are guarded to
  no-op (`_render_internal`, `_update_internal_state`, `_load_assignment_details`,
  `_on_consultants`). The legacy consultation-internal tab remains only as the
  feature-OFF fallback.
* User grouping moved to **core** (`ino_assignment_models.partition_user_groups`) so both
  entry points group identically; `assign_core.partition_ino_groups` stays for the
  feature-OFF path.
* **External is untouched** and stays entirely in the education module.

**Regression guard:** `test_reporting_physician_path_has_no_own_assignment_logic` fails if
`assign_async` / `list_users(` / `svc.assign(` / `notify_local_assignment` /
`set_assignment_status` ever reappear in `internal_assign_ui.py`. Plus
`test_partition_user_groups_is_in_core`.

**Validate both paths on the same patient/physician** — they must produce the same
assignee, type, status, comment, notification, history row and patient-list icon, and both
must offer the same lifecycle actions.

## FALSE RED in the Report column — 49868 / 49836 (root cause + fix, 2026-07-10)

**Symptom.** Two patients showed the reporting physician's name in **RED** in the Report
column although **no internal assignment existed** for them.

**Root cause — the colour was derived from the WRONG FIELD.**
`patient_table_widget._apply_report_status_display` called

```python
reporter_display(report_status, physician_text)   # ← the bug
```

and `reporter_display` returned **RED for ANY non-completed report that merely had a
reporting physician set** (in the RIS report workflow). It **never consulted the
assignment record**. So every patient with a reporter and a non-completed status turned
red — and the tooltip even falsely read *"Assigned to …"*.

It only became visible when the feature was flipped **default-ON** (2026-07-10); while
`is_enabled()` was False that branch never ran. So: not stale state, not a cache, not the
report status being mistaken for an assignment — simply the wrong source field.

**The rule now.** RED in the Report column means **exactly one** thing:

> the reception has an **ACTIVE** internal assignment **and** the name displayed **is the
> assignee**.

Implemented as: the reception id is stamped on the report label at creation
(`report_label.reception_id`, so *every* re-render path — initial, refresh, hydration,
status change — can resolve it), then

```python
rec = ino_assignment_history.current_assignment_details(reception_id)
if rec and rec["assignment_status"] == STATUS_ACTIVE:
    if same_person_name(rec["assignee_name"], displayed_physician) or not displayed_physician:
        → RED (assignee name)
# anything else → the ORIGINAL pre-feature status-icon colour scheme
```

* Derived from the **persisted, `server_ok`-gated record** — a local-only/failed assign
  can never colour a row.
* A **different** physician than the assignee → **not** red (new pure
  `ino_assignment_models.same_person_name`, tolerant of titles «دکتر»/«Dr.», case,
  whitespace and an `(ID: …)` suffix).
* `completed` / `deactivated` / `cancelled` are not `active` → **not** red.
* Green "completed reporter" and all other states keep the **original** colour scheme.

**`reporter_display` was DELETED** (it had no remaining callers). Guard test
`test_reporter_display_is_gone` fails if it comes back; `test_same_person_name` and
`test_report_red_requires_active_assignment_of_that_physician` pin the 49868/49836
scenario (reporter present + no assignment ⇒ never red).

## Verification note
Sandbox was offline this session, so pytest wasn't run here — run `tests/code/network/test_ino_assignment.py`
and `tests/code/education_online_consultation/test_assign_core.py` on the Windows build.
The assign endpoints themselves were **not** live-verified (feature is OFF and the
guide's `:8000`/socket contract needs confirmation per center) — enable + verify before shipping the UI.
