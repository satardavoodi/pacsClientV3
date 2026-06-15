# AI-PACS — Workflow Mode Separation: Live-Server vs Local/Offline Sync (as-built + policy, 2026-06-15)

Authoritative reference for the **mode-aware synchronization** rule: the client must
clearly distinguish workflows that depend on **live-server** synchronization from
workflows that rely only on **local/offline** data, and must never mix the two sets of
assumptions.

The single source of this policy in code is **`modules/storage/sync_mode_policy.py`**
(`WorkflowMode`, `resolve_workflow_mode`, and the `requires_*` / `*_is_source_of_truth`
predicates). Every sync/open/download decision that depends on "is this a live-server
workflow?" must ask the policy — never re-derive an ad-hoc `source == DB` check.

---

## 1. The modes (data-entry workflows)

The patient-load source lives on the home widget as `self.source_of_patient_load`
(`SourceOfPatientLoad` in `home_panel/widget.py`): `SERVER | DB | IMPORT |
OFFLINE_CLOUD` (initial `None`). CD burning is a separate **action**, not a load source.
The policy maps these onto explicit workflow modes:

| `SourceOfPatientLoad` | Workflow mode | Set where |
|---|---|---|
| `SERVER` (`'server'`) | **LiveServer** | `_hp_search` server search (`:165`, `:189`) |
| `DB` (`'db'`) | **LocalDatabase** | `_hp_search` local search (`:160`); `_hp_import` after import (`:98`) |
| `IMPORT` (`'import'`) | **Import** | `_hp_search` import (`:169`) |
| `OFFLINE_CLOUD` (`'offline_cloud'`) | **OfflineServer** | `home_search_service` (`:360`) |
| (n/a — action) | **CDBurn** | `modules/cd_burner/*` (no patient-load source) |

> Note: a freshly **imported** study is promoted to `DB` once it is in the local
> database (`_hp_import.py:98`), so `IMPORT` is the *transient* in-flight import context;
> after that the patient is a normal **LocalDatabase** entry.

---

## 2. Per-mode contract (source of truth + sync rules)

| Mode | Source of truth | Live-server sync required? | Server **version** check? | Trust local cache? | Missing files → server download? | Server unavailable → |
|---|---|---|---|---|---|---|
| **LiveServer** (`SERVER`) | **Server** | **Yes (mandatory)** | **Yes** (`contentVersion`) | Display only — never authoritative | **Yes** | Degrade: show cache, log, retry; never crash the open |
| **LocalDatabase** (`DB`) | Local DB + disk for **display**; server `contentVersion` governs growth | **Yes** — background, non-blocking contentVersion check (default on; `AIPACS_LOCALDB_AUTO_SERVER_SYNC=0` for strict local) | **Yes** (`contentVersion`) | For fast paint — but a higher server `contentVersion` wins | **Yes** (the detected delta only) | Degrade: keep local, never block the open or mark it stale |
| **Import** (`IMPORT`) | **Provided local files** | **No** | **No** | Yes (just imported) | No | Irrelevant — import is local-only |
| **OfflineServer** (`OFFLINE_CLOUD`) | **Offline-cloud package + metadata** | No live-server sync; offline-cloud sync only | No live-server version check | Yes | No (live); offline-cloud rules govern | Follow offline-cloud availability, not live-server rules |
| **CDBurn** (action) | **Local selected data** | **No** | **No** | Yes | No — missing file = **local** missing-file error | Irrelevant — never a live-server error |

**The core rule:** only **LiveServer** treats the server as the source of truth and runs
mandatory, version-aware sync. Every other mode is local/offline-first and must NOT be
forced to verify against the live ai-pacs server.

---

## 3. Live-server sync mechanism (LiveServer mode only)

Strong but efficient, version-first (implemented this engagement):

1. **`contentVersion` fast-gate** (`content_version_store` + the resync): the server's
   monotonic per-study `contentVersion` is the primary signal. Store the last
   *confirmed-complete* version per study; on a live-server open/refresh compare
   server vs local. Equal ⇒ skip the DB query + disk scan entirely. Higher/unknown ⇒
   fall through to the disk-aware manifest.
2. **Disk-aware manifest** (`sync_manifest.evaluate_sync`): disk is the read authority;
   download only **missing/partial** series, never a full re-download; de-duplicate.
3. **Off the UI thread**: the resync is fire-and-forget and throttled (5-min TTL/study);
   opening, switching, thumbnails, and drag-drop stay responsive.
4. **Atomic version commit**: stamp `synced_version = server_version` only once disk is
   confirmed complete — never on mere enqueue.

This is exactly the "lightweight version check first, download only the delta, no
duplicate downloads, no full rescan, no UI block" the policy requires — and it runs for
**LiveServer** workflows. (Status/report/reception refresh ride the same open path.)

---

## 4. The problem this addresses (scattered, inconsistent mode checks)

Before this policy, "is this a live-server workflow?" was re-derived ad-hoc with
**different source-sets** at each site, an open invitation to cross-mode bugs:

- `_hp_patient_open.py:709` → `is_local = source in (DB, OFFLINE_CLOUD)`
- `_hp_series.py:838` → `source == DB`
- `_hp_series.py:882` → `source != DB`
- `_hp_priority.py` / `_hp_series.py` (LOCAL_GUARD, p2 55b7770) → `(DB, OFFLINE_CLOUD, IMPORT)`
- resync IMPORT guard → `== IMPORT`

`sync_mode_policy` replaces these with **one** documented mapping + named predicates so
every site asks the same question and gets the same, logged answer.

---

## 5. Cross-mode bugs the policy prevents

- A **LiveServer** patient must not be treated as a purely local import (it must
  version-check + sync).
- A **LocalDatabase**/**Import** patient must not be marked *stale* just because the live
  server is unavailable or doesn't have it — local is the source of truth.
- **Server version checks must not run** for CDBurn / Import / local-only workflows.
- **CDBurn** missing-file errors are **local** ("file not found on disk"), never a
  live-server sync error.
- **Clearing** patient data updates the local DB/cache/thumbnails + forgets the synced
  `contentVersion` (so a cleared LiveServer study re-syncs; a cleared local study just
  disappears).
- "Downloaded" means different things by mode (LiveServer: present *and* version-current;
  Local: present on disk) — and is documented here, not assumed.

---

## 6. Logging (mode-aware)

Every sync/open/download/import/CD entry point logs, via the policy's
`log_mode_decision(...)`:
`mode` (LiveServer/LocalDatabase/Import/OfflineServer/CDBurn), the chosen **source of
truth**, the **local version** and **server version** (when applicable), and **whether
sync was skipped and why** / **what changed**. Never log tokens, passwords, or
credentials.

---

## 7. Validation checklist (acceptance)

**LiveServer:** open checks `contentVersion`; changed version → delta sync; new
series/instances detected; status/report/reception refreshed; cache not blindly trusted;
UI responsive; no duplicate downloads.
**LocalDatabase:** opens without a live server; not marked stale when the server is down;
list reflects local DB/files; manual "Refresh from server" still available on demand.
**Import:** processed from local files; no live-server version check; stored consistently.
**OfflineServer:** follows offline-cloud availability/metadata; not forced into
live-server sync.
**CDBurn:** uses local selected data; no live-server resync; missing local file → local
error.

---

## 8. Rollout

`sync_mode_policy` is additive and behavior-preserving on adoption: each predicate
returns the value matching the **current correct** behavior for that mode, so swapping an
ad-hoc check for the policy is a no-op refactor that only centralizes + documents + logs.

**Synchronization is preserved — no regression.** The auto contentVersion resync still
runs for **LiveServer**, **OfflineServer**, and **LocalDatabase** (a DB study is a
locally-cached *server* study, so its `contentVersion` must be checked — §4.3/§7;
default on, `AIPACS_LOCALDB_AUTO_SERVER_SYNC=0` for strict local). The **only** intended
behavior change vs. before this work is that the auto resync no longer fires for
**Import / CD / Unknown** sources — those studies do not exist on the server, so the
server has no `contentVersion` for them and the call was a wasteful no-op (a manual
refresh still works for any source). Remaining ad-hoc sites migrate to the policy
incrementally; this doc is the guard.
