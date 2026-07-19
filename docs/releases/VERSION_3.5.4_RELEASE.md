# AI-PACS v3.5.4 — Release Record

**Version:** 3.5.4
**Release date:** 2026-07-19
**Previous stable:** v3.5.3 (2026-07-16)
**Branch:** `beta-version` (force-published to `main` + `beta-version` on all remotes)
**Type:** Minor — auto-update system, Agent Gateway, image-identity overlay, demographic editor, sortable columns

---

## 1. Headline

Four mostly-independent pieces of work land together.

Two are new infrastructure: an **automatic incremental update system** so clients
can pull deltas from the AI-PACS website instead of reinstalling, and an **Agent
Gateway** so a phone or MCP client can pair with and drive the workstation.

One is a **clinical-safety** fix: the viewport overlay now takes patient identity
from the image on screen rather than a per-tab database row — which is what a
correct identity source should always have been.

The rest is workflow polish: a demographic DICOM-tag editor, sortable Status/Report
columns, an "Imported On" column, and the series-sidebar overlap-on-open fix.

---

## 2. Automatic incremental update system (OPT-38)

Clients detect, download (delta only), and install new releases from a static
website feed, extending the pre-existing manual update seam rather than forking a
second checker.

The safety model is the point:

- **Consent-gated.** Nothing downloads or installs without the user agreeing;
  `required` feeds only nag. The startup check is delayed and off-thread.
- **Path guard is a clinical rule.** The applier may only write manifest paths
  accepted by `is_safe_manifest_path` — a top-level file, `engine/**`, or `Qss/**`.
  That makes `User Data\`, `%APPDATA%\AIPacs\config` (all center settings and
  credentials), the ProgramData profile, and module packages untouchable *by
  construction*, not by convention.
- **Wait-never-kill + auto-rollback.** The helper waits for a clean app exit (abort
  untouched on timeout); any copy failure restores every backed-up file and
  relaunches the old exe. Backups persist for two prior versions with a rollback
  script.
- **Full-installer fallback preserved** — a feed without a delta is byte-identical
  legacy behaviour.

`modules/auto_update/`, `tools/build/` (generator + publisher), `website_update_service/`,
`config/update_sources.json`, `builder/publish_targets.template.json`. Remote
publishing is incremental (content-addressed store; only missing blobs upload; feed
last). Design doc: `docs/plans/architecture/AUTO_UPDATE_SYSTEM_2026-07-16.md`.

**Status:** needs a real vN→vN+1 cycle on an installed build, and a first publish
against the live host.

---

## 3. Agent Gateway — mobile / MCP connectivity

A new subsystem letting phone / MCP clients pair with and drive the workstation via
a **second transport onto the existing EchoMind command bus** — no fork of the
command layer, so every action still runs the production code path and the
cross-patient / multi-study guards stay enforced.

- QR pairing, self-signed TLS with certificate pinning, per-device tokens.
- LAN or relay reachability, for sites with no static IP / no port forwarding.
- **Default-OFF** (`AIPACS_AGENT_GATEWAY`); the Settings ▸ Agent tab shows the
  pairing QR (or the URI as text if `segno` is absent).

`modules/agent_gateway/`, `config/agent_gateway/`, `tools/agent_relay/`,
`PacsClient/.../agent_settings.py`. Soft deps `segno` + `websocket-client`, both
with fallbacks. Design: `docs/plans/architecture/REMOTE_CONNECTIVITY_ARCHITECTURE_2026-07-17.md`,
`docs/pipelines/agent-gateway.md`. The Android client ships separately.

---

## 4. Viewport overlay reads the displayed image's identity (clinical safety)

**The bug.** The four-corner overlay (Patient Name / ID / Sex / Age, Study
Date/Time, Institution) was read from a per-tab `metadata_fixed` dict — a local DB
`patients`/`studies` row copied once per tab and keyed by `patient_pk`, which
resolves from the DICOM Patient ID (a `UNIQUE` column). So **two different people
accidentally sent under one Patient ID collapsed to a single DB row**, and the
overlay painted the same name on *both* patients' images.

**The fix.** The overlay now reads identity from the displayed series' own
first-instance DICOM header. Precedence is image → DB (`metadata_fixed`) → NA; the
DB fills only a tag genuinely absent from the image, and the image tag is never
overridden by a mismatched DB value.

- **Two viewers, one read-only trunk.** FAST and Advanced each read their own series
  header through the shared `overlay_identity_source.read_series_identity_from_instances`
  and resolve text through the pure `overlay_metadata.build_overlay_metadata` — they
  unify only through this trunk, respecting the Fast/Advanced/VTK separation rule.
- **No I/O on the paint path.** The header read is `stop_before_pixels`, limited to
  the identity tags, and cached by `(path, mtime)`; reads never raise (fall back to
  DB on any failure).
- **Scope is descriptive text only** — never UIDs, geometry, slice order, or the
  slice counter (a guard test forbids those tags in the reader).

Flag `AIPACS_OVERLAY_IMAGE_IDENTITY` (default-on; `=0` = byte-identical legacy).
Both viewer files are plugin-mirrored.

---

## 5. Demographic DICOM-tag editor (right-click ▸ Edit patient / study info)

Corrects six demographic tags — PatientName, PatientID, InstitutionName, StudyDate,
StudyTime, PatientAge — across every series and every image of every study on the
row.

**The hard rule: identity is never rewritten.** Study / Series / SOP InstanceUID
(and every other UI-VR element) stay byte-identical, because the disk layout,
thumbnails, DB rows, and the fail-closed viewport identity gate are all keyed on
those UIDs — regenerating one orphans every layer at once. The guarantee is
verified, not assumed: each file is re-read as written and the study rolls back on
any mismatch. Writes are atomic (`.part` → `os.replace`) with a full study backup
first. Local-only — the server has no demographic-write endpoint, and the dialog
says so.

`PacsClient/utils/dicom_demographics_edit.py` (pure stdlib + pydicom),
`patient_edit_dialog.py`, `_hp_patient_edit.py`, `database/manager.py`.

---

## 6. UI

- **Sortable Status / Report columns.** They were unsortable because each renders a
  cell *widget*, which carries no item data for `sortItems` to compare. Each cell
  now also holds a hidden `SortableItem` (rank + a `(date, time)` tie-break). The
  tie-break is direction-compensating (Qt reverses one comparator wholesale for
  descending), and one pre-sort re-sync mutates the keys in place — no `dataChanged`,
  no repaint, no DB hit. Cell-widget ↔ row alignment is verified at 50/500/2000 rows
  (a sorted row must never show another patient's report status). ~7 ms at 500 rows.
- **"Imported On" column** (`studies.imported_at`). When a study first entered the
  local DB on this computer, distinct from the acquisition Date — the two diverge on
  a CD/external import. Hidden by default; new columns are *appended* (index 15), so
  saved per-workstation layouts (keyed by column index) are not scrambled.
  `imported_at` is stamped once on insert, never on the refresh UPDATE (or it would
  degrade into "last refreshed"); pre-existing rows stay blank.
- **Series-sidebar overlap-on-open fixed.** The chunked render path appended cards
  while yielding to the event loop with the container visible and painting enabled,
  so a just-added card painted once at the origin before the `QGridLayout` moved it —
  cards briefly overlapped, then snapped into rows. Each chunk's adds are now
  bracketed `setUpdatesEnabled(False)` → add → `activate()` (compute geometry with
  paint off) → `setUpdatesEnabled(True)`, matching the other two render paths.
- **Admission Reports dashboard** in Data Analysis; Cloud "Sync + Close" now sets
  Awaiting-Secretary approval flags (physician + secretary both false).

---

## 7. Verification status

Offscreen (test lane): new guard suites for the overlay image identity, demographic
editor, sortable columns, imported-on column, sidebar overlap, agent gateway, and
auto-update all live under `tests/code/`.

**Still required — live source-build verification** (cannot be done from the test
lane):

1. **Auto-update:** a real vN→vN+1 delta cycle on an installed build, and a first
   publish against the live website.
2. **Agent Gateway:** pair a phone/MCP client over TLS and drive an action.
3. **Overlay identity:** drag a series → overlay matches that series' DICOM; the
   two-patients-one-ID case shows each image's own name.
4. **Demographic editor:** edit a study → files rewritten, UIDs unchanged, series
   still display.

---

## 8. Publication

Force-published to `main` + `beta-version` on all three remotes, with an annotated
`v3.5.4` tag:

- https://github.com/Vahid-INO/ai-pacs
- https://github.com/satardavoodi/PacsClientV2
- https://github.com/satardavoodi/pacsClientV3
