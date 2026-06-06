# AI-PACS Education Cloud — Umbrella Project Kickoff (copy-paste prompt)

You are the engineering agent for the **AI-PACS Education Cloud** program inside the
Umbrella project, which has access to BOTH codebases:

1. **DICOM Workstation** (Python/PySide6): `E:\ai-pacs\ai-pacs codes\ai-pacs beta version\`
2. **AI-PACS web platform**: WordPress (presentation) + **Laravel core/backend** (control plane)

Your mission: implement the approved **three-tier architecture** — Google Drive
(5 TB, `AI.pacs.medical@gmail.com`) as the storage layer, **Laravel as the management/
control layer**, WordPress as the presentation layer, and the workstations as REST
clients — for Education content (Case of the Day, courses, videos, textbooks) and
Online Consultations.

## 0. Read these first (in the workstation repo — authoritative, do not skip)

1. `docs/plans/education-cloud/EDUCATION_CLOUD_THREE_TIER_R2_2026-06-06.md` — **the
   architecture you are implementing** (R2: tiers, credential custody, transfer
   brokering, API sketch, phases, §9 verification list).
2. `docs/plans/education-cloud/EDUCATION_DRIVE_ARCHITECTURE_2026-06-06.md` — R1;
   partially superseded, but still authoritative for: current local Education
   storage layout, the `item.json` package format (§3), the `drive.file`
   cross-account finding (§4.4), client sync-state tables (§5.2), local layout (§7).
3. `docs/pipelines/online-consultation-education.md` — as-built record of what
   already runs on the workstation today.
4. Workstation repo `CLAUDE.md` → section "Online Consultation — Identity + Drive +
   Education submodule" — regression guards you must never break.

## 1. Architecture you are implementing (summary — R2 is the full contract)

- **Drive stores, Laravel decides, WordPress shows, workstations consume/produce.**
  No client ever talks to Drive on its own authority.
- **Credential custody:** the hub Google account's OAuth refresh token lives ONLY in
  Laravel (encrypted at rest, never in git). Workstations never hold org Drive
  tokens. (The workstation's per-user personal Google identity flow continues to
  exist for legacy/external consultations only.)
- **Data plane contract (FROZEN):** every stored unit is an `item_id`-named Drive
  folder containing a sealed `item.json` (`aipacs-education-item-v1`: kind, title,
  owner `{aipacs_user}`, version, SHA-256 map of every file). Packages are
  self-describing — the catalog DB can always be rebuilt by walking Drive.
- **Catalog & permissions:** Laravel DB is authoritative (items, files, visibility
  `public|members|group|private|unlisted`, roles admin/instructor/physician/member,
  per-item grants, audit log). Server-side enforcement only.
- **Transfers:** uploads = Laravel-brokered **Drive resumable-session URIs** (client
  PUTs bytes straight to googleusercontent.com, tokenless, one file per URI);
  downloads = **Laravel streaming proxy** with HTTP Range (temp `anyoneWithLink` is
  a later optimization for big de-identified public media ONLY; never DICOM/
  consultations). Finalize = server cross-checks Drive md5/size against the client's
  sha256 manifest before the catalog row commits.
- **User mapping:** website (Laravel) accounts are the person. Workstations link via
  a new `aipacs_web` IdentityProvider → Sanctum bearer token stored in the OS
  keychain (the workstation Identity module already supports pluggable providers +
  secure_store).
- **Consultations v2:** created/assigned by **website user id** (not Google email);
  server owns all Drive I/O; workstation polls `GET /notifications`. This
  structurally fixes the `drive.file` shared-with-me gap (R1 §4.4) AND retires
  client-side Drive polling, which already needed an off-thread hardening fix on
  2026-06-07 (transport build + `ensure_app_folder` froze the GUI 3–20 s per poll
  when on the main thread — see `modules/cloud_consultation/notifications/poller.py`
  docstrings). Treat that as evidence: **client Drive polling is fragile; REST
  notifications from Laravel are the design goal.**
- **API surface (v1, Sanctum):** see R2 §6 — `POST /auth/workstation/pair`,
  `GET/POST /education/items` (+ `/finalize`, `/download`, `/permissions`),
  `POST /consultations` (+ `/responses`, `/close`, `/download`),
  `GET /notifications?since=…`, `GET /me`. Keep this shape unless you document why.

## 2. What already exists (do not rebuild)

**Workstation (all tested, flags ON, 72 green in
`tests/code/cloud_consultation|identity|education_online_consultation`):**
- `modules/Identity/` — OAuth PKCE, keychain secure_store, pluggable providers,
  `get_capability_client(CLOUD_STORAGE)` → Drive v3 service.
- `modules/cloud_consultation/` — `CloudTransport` ABC + `GoogleDriveTransport`
  (resumable upload, atomic `.part` download, share, change cursor),
  `CloudSyncEngine` (per-file resumable state), sealed envelope + SHA-256 verify,
  state machine (`pending|uploaded|downloaded|reviewed|answered|closed|conflict`),
  notifications inbox + poller, account popup.
- `modules/education/online_consultation/` — the Education ▸ "Online Consultation"
  tab (study picker → compose → inbox/sent with Pending/Sent/Received/Answered/
  Closed display labels → respond → close → notifications). Its **UI survives R2**;
  only the worker internals will swap from Drive-direct to Laravel REST.
- Local Education storage: `user_data/education/{courses,assets,Case of the Day}`;
  courses/books/videos = rows in `courses` table (`resource_type`); Case-of-Day
  packages = `<case>/{dicom/,metadata.json,reception.json,attachments/}`;
  import bundles exist (`education-import-v1`); **course EXPORT does not exist yet**
  (you build it in P2); `CaseOfDayLocalServerPage` has a "Server" placeholder
  section waiting for this feed.
- Reuse for anonymize-on-publish: `modules/cd_burner/dicom_prepare.py`.

**Website:** the user states Google Drive API work already exists somewhere on the
platform side — FIND IT before writing new Drive code (§3 step 1).

## 3. First session — verification checklist (do this before any code)

1. Locate and read the existing website-side Google Drive integration (which
   account, scopes, library, where credentials are stored). Decide reuse vs replace.
2. Identify Laravel version, auth stack (Sanctum? Passport?), queue/worker setup,
   DB engine, deployment layout, and how WordPress and Laravel share users (SSO?
   shared table? REST bridge?). Document in a short CURRENT_STATE note.
3. Confirm VPS bandwidth/disk ceilings → validates the download-proxy choice.
4. Confirm the hub account `AI.pacs.medical@gmail.com` OAuth client type and that
   the consent screen is **In production** (Testing mode expires grants in 7 days).
5. Check for an existing website "Case of the Day" schema to align field names with
   `item.json` before P3.
6. Write the findings + any contract adjustments back into a new
   `docs/plans/education-cloud/UMBRELLA_CURRENT_STATE_<date>.md` in the workstation
   repo (it is the shared documentation home).

## 4. Implementation order (each phase shippable; U=server, W=workstation)

- **P0 (U):** Laravel: encrypted hub-credential storage + DriveService (ensure
  folder tree `AI-PACS Education/…`, create resumable sessions, verify md5/size,
  proxy download); migrations: `education_items`, `education_item_files`,
  `item_permissions`, `audit_log`; `POST /auth/workstation/pair`.
  *Accept:* a CLI/tinker script publishes + fetches a test item end-to-end.
- **P1 (U+W):** Media (videos/textbooks) publish/fetch/list + workstation
  `aipacs_web` provider + Cloud Library view; WP library page.
  *Accept:* workstation A publishes a video; workstation B and a browser user see
  and fetch it per visibility rules.
- **P2 (U+W):** Courses — build `export_course_bundle` on the workstation
  (course.json + slides + assets; import already exists), publish/fetch; WP course
  pages. *Accept:* full course round-trip A→cloud→B with slide fidelity.
- **P3 (U+W):** Case of the Day — anonymize-on-publish (reuse `dicom_prepare.py`,
  default ON, failure⇒exclude file, never leak PHI), feed the workstation "Server"
  section + WP CoD page. *Accept:* a published case appears on the website and in
  workstation B's Server tab; DICOM headers verified anonymized.
- **P4 (U+W):** Consultations v2 — user-id assignment, `GET /notifications`,
  workstation workers swapped to REST; keep internal statuses + display labels
  exactly as-is. *Accept:* A→B→A round-trip with notifications on both sides and
  correct lifecycle labels; legacy Drive-direct path still works behind its flag.
- **P5 (U):** dashboards, groups, quota admin, audit UI. **P6:** CDN/caching,
  optional Workspace/Shared-Drive migration.

## 5. Hard rules (carry over from the workstation project — they still apply)

- Preserve all existing workstation functionality; minimal safe edits; no unrelated
  refactors; FAST viewer never instantiates VTK render windows.
- Never break the workstation guards in `CLAUDE.md` (Online Consultation section):
  internal statuses are frozen; display labels are display-only; double-flag gating
  stays; offline package engine is reused, never forked; no UI-thread blocking —
  all network in workers (the 2026-06-07 poller stall is the cautionary tale).
- `modules/education/` is plugin-mirrored: after workstation edits run
  `tools/dev/sync_plugin_mirrors.py` (use `--add` for new files) then
  `verify_plugin_mirrors.py`.
- Run workstation tests after workstation changes:
  `python -m pytest tests/code/cloud_consultation tests/code/identity tests/code/education_online_consultation -q -p no:debugging`.
  Add Laravel-side tests (Pest/PHPUnit) for every new endpoint; never test against
  the live hub Drive — fake the DriveService.
- Secrets: hub refresh token encrypted at rest server-side; never in git, logs, or
  client payloads. Workstation client tokens only in the OS keychain.
- PHI: the education library holds de-identified content only (consumer account =
  no BAA). Consultations carry PHI — proxy-only transfers, strict two-party access.
- Documentation lives in the workstation repo under `docs/plans/education-cloud/`
  (shared contract home); write/update an as-built doc per phase, plus
  `## Status` lines so the next session can resume.

## 6. Working style

Understand before editing (read the existing code paths first); explain root causes
before large changes; phase-by-phase delivery with tests green at every step; report
risks and remaining work honestly at the end of each session; keep a short progress
ledger in the plan doc so any future session can continue exactly where you stopped.

**Start now with §3 (verification checklist), report findings, then propose the P0
work order for approval before writing server code.**
