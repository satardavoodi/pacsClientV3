# Hybrid Socket / REST Communication Model — Architecture Analysis

> **Type:** Design-analysis deliverable (no implementation)
> **Status:** For review — wait for approval before any code change
> **Date:** 2026-05-23
> **Scope:** AI-PACS client networking; Hermes used only as a reference architecture
> **Companion doc:** `docs/architecture/network-architecture.md` (existing, v2.3.3 — partially outdated)

This document analyzes how AI-PACS currently talks to the PACS/server, compares it
with Hermes, and proposes a deliberate hybrid model. It is evidence-based: every
claim points to a concrete file/function or an observed log behavior. It proposes
**no code changes** — only a target architecture and a staged roadmap.

---

## 1. Current-State Analysis

### 1.1 AI-PACS uses three overlapping transports

| Transport | Where | Port source | Role today |
|-----------|-------|-------------|------------|
| **Socket** (TCP + 4-byte length + JSON) | `modules/network/socket_client.py`, `socket_patient_service.py`, `socket_report_status_service.py`, `modules/download_manager/network/socket_client.py` | `config/socket_config.json` → `get_socket_server_settings()` → `50052` | Patient list, thumbnails, study/series metadata, DICOM download, **and** report-status workflow |
| **gRPC** (HTTP/2 + Protobuf) | `modules/network/grpc_client.py`, `dicom_service_pb2_grpc.py`, `dicom_downloader.py`, `multi.py`, `dicom_downloader_client_help.py` | `50051` (`DEFAULT_GRPC_PORT`) | Legacy; largely superseded. `grpc_client.py` was already refactored to resolve a **socket** client internally (`_get_socket_client()`) |
| **REST** (`requests` → JSON) | `_hp_search.py`, `patient_table_widget.py`, `modules/ai_imaging/.../reception_data_service.py` | `http://81.16.117.196:8080` (env-overridable) | Reception/admission data, report metadata, reporting physician, comments, user/doctor lookup |

The existing `network-architecture.md` documents only **socket + gRPC**. The **REST
layer is undocumented** there, and that doc still claims the socket carries
"Admission data" — which is no longer accurate. The reception/admission/report
metadata is fetched over REST.

### 1.2 Socket endpoint inventory (observed in code)

| Endpoint | Domain | Notes |
|----------|--------|-------|
| `Login` | auth | fail-fast, no retry |
| `GetPatientList` | imaging | patient/study list |
| `GetStudyThumbnails` | imaging | series thumbnails + metadata (post-migration primary path) |
| `GetStudyInfo` | imaging | lightweight study metadata — **observed to time out**; mitigated by 15s→3s probe timeout, falls back to `GetStudyThumbnails` |
| `QuerySeriesThumbnails` | imaging | per-series thumbnails |
| `GetStudyAttachments` / `UploadAttachment` | mixed | attachments |
| `UpdateReportStatus` | **workflow** | report status write — workflow data on the imaging channel |
| `GetReportStatus` | **workflow** | report status read — **observed to time out** in `download_diagnostics.log` |
| `GetReportStatusHistory` | **workflow** | audit trail |
| `GetStudiesByReportStatus` | **workflow** | status-filtered query |
| `GetInstanceBatch` / `DownloadDicomImages` | imaging | batched DICOM transfer (download path) |

### 1.3 REST endpoint inventory (observed in code)

| Endpoint | Domain | Caller |
|----------|--------|--------|
| `GET /api/pacs/patients/{id}` | admission + report metadata + `pacsComment` | `_hp_search.py::_fetch_reception_patient_payload`, `patient_table_widget.py::_fetch_reception_patient_payload`, `reception_data_service.py` |
| `GET /api/pacs/users/{id}` (and `/api/users/...` variants) | doctor/user name lookup | `patient_table_widget.py::_fetch_server_user_full_name` |
| `POST /api/pacs/patients/{id}/comment` | reception comment write | reception data service |

### 1.4 Realtime

AI-PACS has **no dedicated realtime channel**. `socket_client.py::send_request()`
treats `type == "broadcast"` frames as **noise to skip** (loops up to
`max_broadcast_retries = 200` waiting for the "real" response). So AI-PACS pays the
cost of broadcast traffic without getting the benefit of live updates.

### 1.5 Summary of current state

The socket layer is doing **two unrelated jobs**: imaging transport (its natural
job) and report/workflow CRUD (`*ReportStatus*` endpoints). The REST layer owns the
real admission/report metadata but is wired in ad-hoc — partly as a click-time
fallback, partly through an enrichment path that is **defined but never called**
(`_hp_search.py::_sync_completed_reporting_physicians_after_search`). gRPC is a
third, mostly-dead transport still present in the tree.

---

## 2. Hermes Comparison

Hermes is a sibling client against the **same** PACS/server. Its transport split is
clean and deliberate. **Hermes is a reference for boundaries only** — its ports,
retry constants, config, and workflows must not be copied (prior regressions came
from literal copying).

### 2.1 Hermes socket layer (`ui/network/pacs_socket_client.py`)

Endpoints: `Login`, `GetPatientList`, `GetStudyThumbnails`, `SubscribeToEvents`.
**That is the entire socket surface.** Socket = imaging + auth + realtime
subscription. No report endpoints exist on Hermes' socket at all.

### 2.2 Hermes realtime is a *separate* channel (`BroadcastListener`)

Hermes runs a dedicated persistent socket (`BroadcastListener`) that issues
`SubscribeToEvents` for `patient_list_updated` / `study_created` and emits Qt
signals, with auto-reconnect every 5s. Realtime is **architecturally separate**
from request/response — it never interleaves with a `send_request` round-trip.

### 2.3 Hermes REST layer (`ui/viewer/reception_data/reception_data_service.py`)

`GET /api/pacs/patients/{id}` and `POST /api/pacs/patients/{id}/comment`, run on
`QThread` workers (non-blocking), 30s timeout, `Bearer` auth, base URL from
`config/reception_api.json`. The report metadata shape is authoritative:

```
report (or imagingWorkflow.report)
  ├─ status            "pending" | "in_progress" | "completed"
  ├─ approvalFlags     { physicianApproved: bool, secretaryApproved: bool }
  ├─ reportDate
  ├─ radiologist       { FullName, ... }      ← reporter name lives here
  └─ content / findings
```

### 2.4 Side-by-side

| Dimension | Hermes | AI-PACS |
|-----------|--------|---------|
| Patient list | socket `GetPatientList`, imaging fields only | socket `GetPatientList`, imaging fields + attempts report fields |
| Report status / physician | **REST only** (`report` object in patient detail) | **socket** `GetReportStatus` (times out) **+ REST** fallback — mixed |
| Realtime | dedicated `BroadcastListener` + `SubscribeToEvents` | none — broadcasts skipped as noise |
| Metadata hydration | lazy, viewer-scoped, on tab activation | partly click-time; the list-level enrichment fn is **disconnected** |
| Async enrichment | `QThread` workers, signal-based | background daemon threads, signal-based (where wired) |
| Endpoint separation | strict: socket=imaging, REST=workflow | blurred: socket carries workflow CRUD too |
| Caching | minimal; viewer re-fetches per patient | per-patient `_reporting_physician_cache`, comment cache, thumbnail file cache |
| Timeout strategy | uniform (socket cfg; REST 30s) | mixed; some socket probes tuned down (`GetStudyInfo` 3s) after timeouts |
| Payload structure | `report` **or** `imagingWorkflow.report` | reads only top-level `report` (misses the nested form) |
| Fallback behavior | none needed (single source per domain) | layered fallbacks (socket→REST, REST→socket) — fragile |
| Responsiveness philosophy | imaging never waits on workflow metadata | imaging path has waited on workflow/imaging probes (the ~17s enqueue delay) |

**Key takeaway:** Hermes is not "more featured" — for report status it is *less*
featured (it has no in-list reporter, no status-change dialog). What Hermes does
better is **discipline**: one domain → one transport, imaging never blocks on
workflow, realtime is its own channel. That discipline is the thing worth adopting;
the code is not.

---

## 3. Identified Architectural Problems

Evidence-based, ordered by impact.

**P1 — Workflow data on the imaging transport.** `GetReportStatus`,
`UpdateReportStatus`, `GetReportStatusHistory`, `GetStudiesByReportStatus` run over
the socket. `download_diagnostics.log` shows `GetReportStatus: timed out`. These are
report/workflow concerns riding the imaging channel; the server side appears to not
service them reliably.

**P2 — Dead/slow endpoints still probed.** `GetStudyInfo` (imaging) and
`GetReportStatus` (workflow) both time out. `GetStudyInfo` was mitigated by cutting
its probe timeout 15s→3s and falling back to `GetStudyThumbnails`; it is still
probed every time. Each dead probe is latency the user pays for nothing.

**P3 — Imaging path coupled to a metadata probe.** The double-click → Download
Manager enqueue delay (~17s, later ~6.7s after the timeout fix) came from the
patient-open path waiting on a study-metadata socket probe. Imaging actions should
never block on a metadata call — the coupling, not just the timeout, is the defect.

**P4 — Disconnected enrichment path.** `_sync_completed_reporting_physicians_after_search()`
is fully implemented (throttled, async, REST-backed) but **never called**.
`search_server()` returns without invoking it. The mechanism that would fill the
Report column is orphaned.

**P5 — Three transports, overlapping duties.** `GetPatientList` and
`GetStudyThumbnails` exist on **both** gRPC and socket. gRPC (`50051`) is mostly
dead but still in the tree; `grpc_client.py` already routes through a socket client
internally. Ambiguity about "which client do I use" is itself regression risk
(historically a wrong port — `105` DICOM vs `50052` socket vs `50051` gRPC — was
fed into the socket client).

**P6 — No realtime channel; broadcasts are pure cost.** `send_request()` can loop
up to 200 times skipping broadcast frames. AI-PACS absorbs broadcast traffic but
gains no live patient-list/study updates from it.

**P7 — Layered fallbacks create fragile coupling.** Report physician resolution
chains socket→REST and REST→socket with many key variants. The click dialog reads
only top-level `report`, missing Hermes' `imagingWorkflow.report` nesting. Multiple
fallbacks across two transports make behavior hard to reason about and easy to
regress.

**P8 — UI-thread exposure.** A `[MAIN_THREAD_STALL_TRACE]` was observed through
`search_server → _add_socket_patient_to_table → add_patient_data` — list parsing /
row build runs on the UI thread. Network fetches are mostly offloaded, but
per-row table construction and any synchronous enrichment on the event loop is a
stall risk.

**P9 — Documentation drift.** `network-architecture.md` (v2.3.3) omits the REST
layer entirely and still attributes "admission data" to the socket. The mental
model in the docs no longer matches the code.

---

## 4. Proposed Hybrid Architecture

The goal is **deliberate separation**, not a rewrite, and explicitly **not** merging
the layers.

### 4.1 Three channels, three jobs

```
┌─────────────────────────── AI-PACS Client ───────────────────────────┐
│                                                                       │
│   IMAGING DOMAIN              WORKFLOW DOMAIN          REALTIME        │
│   (socket, req/resp)          (REST, req/resp)         (socket, sub)   │
│                                                                       │
│   • patient/study list        • admission/reception    • patient_list_ │
│   • series enumeration        • report status/physician   updated      │
│   • thumbnails                • approval flags          • study_created │
│   • study imaging metadata    • comments / findings     • status change │
│   • DICOM transfer            • workflow state                         │
│   • progressive download      • user/doctor lookup     (separate       │
│   • download manager          • business metadata       persistent     │
│                                                          connection)   │
│        :50052 socket               :8080 REST           :50052 socket  │
└───────────────────────────────────────────────────────────────────────┘
```

### 4.2 Socket layer responsibilities (A)

**Owns:** patient search/list, study list, series enumeration, thumbnails, DICOM
transfer, progressive/batched download, the Download Manager transport, and
**imaging-only** study metadata (series counts, modality, instance counts) needed to
render imaging UI. Socket retries/health monitoring stay where they are
(download-path `health_monitor.py`, R30–R34).

**Should give up:** report-status CRUD (`*ReportStatus*` endpoints). These are
workflow, not imaging. They may remain callable as a *last-resort* fallback but must
not be the primary path and must not be on any imaging-critical code path.

**Realtime** should become a *dedicated subscription* on its own connection
(conceptually like Hermes' `BroadcastListener`), so request/response round-trips
never interleave with broadcast frames. This is a **future** item, not now.

### 4.3 REST layer responsibilities (B)

**Owns:** admission/reception data, report status, reporting physician, approval
flags, comments/findings, workflow state, business/administrative metadata,
user/doctor lookup, and any non-imaging workflow data. REST calls **always run off
the UI thread** and **never block** an imaging action.

### 4.4 Boundary rules

1. An imaging action (open viewer, load thumbnails, enqueue download) **never
   awaits** a workflow/REST call or a non-imaging socket probe.
2. Workflow metadata (reporter, status, approvals, comments) is **enrichment**:
   fetched async after the imaging UI is already usable, then merged in.
3. Each data domain has **one primary owner**. Cross-transport fallback is allowed
   only as an explicit, last-resort, time-boxed step — never the default.
4. Port/config discipline is preserved: socket host/port always via
   `get_socket_server_settings()` (`50052`); REST base URL via its own config. The
   two are never conflated. (This protects the existing socket-port corrections.)
5. FAST vs Advanced viewer separation is untouched — this analysis is about the
   network layer beneath both, not the viewers.

---

## 5. Data Ownership Map

For each data type: **owner layer**, **why**, **blocking vs async**, **cache**,
**retry**, **fallback**, **UI update strategy**. "Async" = off the UI thread, UI
stays interactive.

| Data / workflow | Owner | Why | Blocking? | Cache | Retry | Fallback | UI update |
|-----------------|-------|-----|-----------|-------|-------|----------|-----------|
| **Thumbnails** | Socket | Image data; bulk binary | Async (background) | Local file cache (`get_all_series_thumbnail_from_study_folder`) | Short, bounded | Local cache → socket; show cache first | Progressive render as they arrive |
| **DICOM transfer** | Socket | Core imaging payload | Async (download subprocess) | On-disk study folder | Full R30–R34 retry (keep as-is) | Per-series retry rounds | Progress signals → DM |
| **Study imaging metadata** (series/instance counts, modality) | Socket | Needed to render imaging UI | Async; must not block open | Per-study in-memory + DB | 1 attempt, short timeout | `GetStudyThumbnails` payload carries it | Fill when available; UI usable before |
| **Patient / study list** | Socket | Imaging catalog | Async (search task) | Replace-on-success (atomic swap) | Standard socket retry | Keep prior rows visible during fetch | Bulk insert in chunks |
| **Report status** | REST | Workflow state, not imaging | Async enrichment | Short-TTL per study | REST retry (1–2), time-boxed | Socket `GetReportStatus` only as last resort | Lazy-fill column/badge |
| **Reporting physician** | REST | Admission/workflow metadata | Async enrichment | Per-patient (`_reporting_physician_cache`) | REST retry (1–2) | `report.radiologist` → `imagingWorkflow.report.radiologist` → user-id lookup | Lazy-fill after list renders |
| **Report approval flags** | REST | Workflow metadata | Async enrichment | With report-status entry | REST retry (1–2) | none (single source) | Render in report dialog/detail |
| **Report comments / findings** | REST | Business/reception data | Async; on demand (dialog open) | Local comment cache (offline writes) | REST retry (1–2) | Local cache when offline | Prefill dialog, refresh in place |
| **Admission / reception metadata** | REST | Non-imaging business data | Async; on demand | Short-TTL per patient | REST retry (1–2) | none | Reception tab / detail view |
| **User / doctor lookup (ID→name)** | REST | Directory data | Async enrichment | **Add** small ID→name cache | REST retry (1) | leave ID shown if unresolved | Replace ID with name when resolved |
| **Download status** | Local (DM state store) | Client-side derived state | Sync local read | DM state store | n/a | derive from on-disk files | Live DM signals (already fixed) |
| **Viewer metadata** (window/level, geometry) | Local + DICOM headers | From files already downloaded | Sync local | In viewer model | n/a | DICOM header defaults | Viewer render |
| **Workflow status** (broad) | REST | Workflow domain | Async enrichment | Short-TTL | REST retry (1–2) | none | Badge/column refresh |
| **Realtime ops** (new study, status change) | Socket *subscription* (dedicated) | Push channel | Async, event-driven | n/a | Auto-reconnect (bounded) | Periodic manual refresh if channel down | Signal-driven incremental update |

---

## 6. Recommended Conservative Next Steps

Small, reversible, evidence-backed. Each is independently shippable. **None is
implemented in this deliverable.**

**N1 — Reconnect the orphaned enrichment path.** Call
`_sync_completed_reporting_physicians_after_search()` once after `search_server()`
completes. ~1–2 lines; the function is already async, throttled, and REST-backed.
Directly fixes the visible "Report column shows N/A" symptom. *Risk: very low.*

**N2 — Add the `imagingWorkflow.report` fallback** to the REST report-metadata
extractors (`_extract_reporting_physician_name_from_patient_payload`,
`_extract_reporting_user_id_from_patient_payload`, and the `_hp_search.py` reception
extractor). Additive key path; mirrors the Hermes-confirmed payload shape.
*Risk: very low — additive only.*

**N3 — Demote socket report-status to last-resort.** Keep `GetReportStatus` etc.
callable, but make the REST patient-detail the primary source for report
status/physician/approvals, and ensure the socket call is never on an imaging
path. *Risk: low — REST is already the working source.*

**N4 — Confirm the raw `GetPatientList` payload.** One low-noise capture (no
PHI-heavy dump) to verify the socket list genuinely lacks reporter fields and to
see whether report status is present. Settles an inference still open from the
prior investigation. *Risk: none — read-only.*

**N5 — Refresh `network-architecture.md`.** Add the REST/workflow layer, correct
the "admission data = socket" claim, and note gRPC as legacy. Documentation only.
*Risk: none.*

**N6 — Add a small ID→name cache** for `_fetch_server_user_full_name` so repeated
doctor lookups don't re-hit REST. *Risk: low.*

Do **N1 + N2 + N4** together as the report-column fix (the subject of the prior two
investigations); treat **N3, N5, N6** as independent hygiene.

---

## 7. High-Risk Areas — Do Not Touch Carelessly

- **Socket port resolution.** `get_socket_server_settings()` → `50052` is the
  corrected, working path. Do **not** reintroduce `servers.json` `port` (105, DICOM)
  or `50051` (gRPC) into the socket client. This regression already happened once.
- **Download Manager subprocess + state store.** The spawn-based downloader, the
  `progress_queue` IPC, and the recently fixed live status sync are fragile and
  clinical-critical. Architecture changes must not refactor the DM transport.
- **FAST vs Advanced viewer split.** Out of scope; the deferral/`should_defer_*`
  logic in the open flow interacts with networking — leave its behavior intact.
- **`send_request` framing.** 4-byte length prefix, `sendall`, `_recv_exact`,
  broadcast skipping, size guards — protocol-correct and must be preserved
  byte-for-byte if any code near it is edited.
- **gRPC removal.** gRPC looks dead but `grpc_client.py` is still imported and now
  proxies to a socket client. Removing gRPC is a *separate, later* effort with its
  own verification — not a side effect of this work.
- **The reception REST base URL / auth.** Bearer-token flow and the
  `81.16.117.196:8080` base (env-overridable) are shared with reception features;
  changing them affects comments and admission data, not just reporter name.
- **Files with BOM + CRLF + Persian text** (`_hp_search.py`, `_hp_study_save.py`,
  `patient_table_widget.py`, …). Edit with byte-safe tooling; the Edit tool
  truncated these before.

---

## 8. Suggested Staged Roadmap

Each stage is independently valuable, independently revertable, and gated on
verification before the next.

**Stage 0 — Documentation & confirmation (no behavior change).**
N4 (capture one `GetPatientList` payload) + N5 (update `network-architecture.md`
with the REST layer and the data ownership map from §5). Establishes the agreed
mental model.

**Stage 1 — Fix the visible symptom (smallest safe patch).**
N1 (reconnect the enrichment fn) + N2 (`imagingWorkflow.report` fallback). Resolves
the Report column N/A. Verify live via the human-assisted bootstrap workflow.

**Stage 2 — Clarify the workflow boundary.**
N3 (REST becomes primary for report status/physician/approvals; socket
`*ReportStatus*` demoted to last-resort, removed from imaging paths) + N6 (ID→name
cache). No new transport; just routing discipline.

**Stage 3 — Decouple imaging from metadata.**
Make every imaging action (viewer open, thumbnail load, DM enqueue) complete
without awaiting any workflow/REST call or non-imaging probe. Workflow metadata
becomes pure post-hoc enrichment. Builds on the already-applied `GetStudyInfo`
timeout fix and the queue-first DM behavior; this stage finishes the decoupling.

**Stage 4 — Introduce a real realtime channel (optional, larger).**
A dedicated broadcast subscription on its own connection (conceptually like
Hermes' `BroadcastListener`, **not** copied) so the list/status update live and
`send_request` stops loop-skipping broadcast frames. Largest effort; do last; gate
behind a feature flag.

**Stage 5 — Retire gRPC (optional cleanup).**
Once Stages 1–3 confirm socket fully covers patient list + thumbnails, remove the
gRPC stack (`dicom_service_pb2*`, `grpc_client.py` gRPC paths) and its `50051`
config. Separate effort with its own regression pass.

### Roadmap at a glance

| Stage | Theme | Risk | Depends on |
|-------|-------|------|------------|
| 0 | Docs + payload capture | none | — |
| 1 | Report-column fix | very low | 0 |
| 2 | Workflow boundary | low | 1 |
| 3 | Imaging/metadata decoupling | medium | 2 |
| 4 | Dedicated realtime channel | medium–high | 3 |
| 5 | Retire gRPC | medium | 1–3 |

---

## Honest Limitations

- The claim "the socket `GetPatientList` does not carry reporter fields" is a strong
  inference (Hermes reads no reporter from it; AI-PACS built a REST fallback;
  the column shows N/A) but is **not yet confirmed from a raw payload** — that is
  step N4.
- Hermes was read read-only as a reference; none of its code, ports, retry
  constants, or config were copied into this proposal.
- This document proposes architecture and sequencing only. No networking code,
  ports, or layer boundaries were changed.
