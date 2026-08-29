# AI-PACS Pre-Development System Map

**Verified:** 2026-08-27

**Purpose:** durable orientation for coding agents and engineers before changing AI-PACS

**Scope:** source architecture, runtime connections, data ownership, packaging, skills, MCPs, and development gates

**Change policy:** this document records the current system; its creation did not change application code or runtime configuration.

## 1. Read order and source-of-truth hierarchy

Before editing, read these in order:

1. `AGENTS.md` — short repository-wide operating rules.
2. `CLAUDE.md` — detailed historical invariants and recently fixed failure modes.
3. This system map — current cross-subsystem connections and task routing.
4. `docs/INDEX_BY_SUBSYSTEM.md` — subsystem-specific documentation.
5. `tests/INDEX_BY_GUARD.md` and `docs/plans/architecture/REGRESSION_CATALOG.md` — guards that must move with a change.
6. `docs/reports/CODEX_REPOSITORY_READINESS_2026-08-27.md` — verified environment, test baseline, and release blockers.

When sources disagree, use this precedence:

1. current runtime code and configuration resolution;
2. executable tests and release gates;
3. current as-built documents;
4. historical plans, audit snapshots, and old counts.

The repository contains valuable history, but several version numbers, test counts, module-coverage percentages, and workflow descriptions are stale. Do not implement from a historical plan without reconciling it against current code.

## 2. System context

AI-PACS is a Windows desktop DICOM workstation. It is a modular monolith rather than a collection of independently deployed services.

```text
Radiologist / operator
        |
        v
PySide6 workstation shell (main.py -> AppHandler -> MainWindowWidget)
        |
        +-- Home/search/reception UI
        |       +-- PACS socket service (primary imaging protocol)
        |       +-- Workflow REST API (admission/report/status metadata)
        |       `-- SQLite local index and workflow state
        |
        +-- Patient tab
        |       +-- Thumbnail and series pipeline
        |       +-- Download Manager subprocess pipeline
        |       +-- Fast / lazy viewer domain
        |       +-- VTK viewer domain
        |       `-- MPR / AI / printing / education launchers
        |
        +-- EchoMind and CommandBus
        |       +-- AI provider transport
        |       +-- in-app voice/chat agent
        |       +-- source-only Test Control Server
        |       `-- paired-device Agent Gateway MCP
        |
        `-- Runtime module/update layer
                +-- installation profile and feature flags
                +-- packaged Python payload overrides
                +-- optional external runtimes
                `-- core delta updater and rollback
```

The public `ai-pacs.com` website is a separate repository and deployment boundary. Workstation integrations such as Identity, consultation, and AiPacs Chat are clients of website/backend APIs; they do not make this repository the website source.

## 3. Startup and shutdown lifecycle

### Startup

1. `main.py` establishes graphics/environment fallbacks before Qt or VTK-heavy imports.
2. Legacy data migration is attempted through `PacsClient.utils.data_paths.migrate_legacy_data()`.
3. A `QApplication` subclass is created and integrated with `qasync.QEventLoop`.
4. `PacsClient.app_handler.AppHandler` owns login and creates the workstation shell.
5. `PacsClient/pacs/workstation_ui/mainwindow_ui.py::MainWindowWidget` calls `init_database()` once.
6. The home panel constructs application services and the unified EchoMind `CommandBus`.
7. Optional services are installed lazily. The Agent Gateway service object is cheap to install and only binds when its flag is enabled.

### Shutdown ownership

- `main.py` owns top-level application shutdown and the hard-exit failsafe.
- Patient-tab close must release viewers, timers, workers, and VTK/OpenGL resources before widgets are orphaned.
- Download and warm-up subprocesses, network pools, async logging, and the Agent Gateway must be stopped by their owning service.
- Qt widgets are main-thread objects. Background work may return immutable results, but it must not mutate widgets directly.

Any feature that adds a timer, thread, process, socket, VTK object, or external client must define creation, cancellation, close, restart, and error ownership before code is written.

## 4. Runtime subsystem boundaries

### Workstation shell and presentation

- `main.py`: process bootstrap, graphics policy, event loop, top-level shutdown.
- `PacsClient/app_handler.py`: login-to-main-window transition.
- `PacsClient/pacs/workstation_ui/`: main shell, home/search, settings, reception, tab management.
- `PacsClient/pacs/patient_tab/`: patient-study workspace, thumbnails, viewer coordination, toolbar and progressive-display orchestration.

New business or network logic should live behind a service/repository boundary. The largest UI controllers already combine many responsibilities and should not absorb another independent workflow.

### Imaging domains

- `modules/viewer/fast/`: Fast Qt/pydicom rendering, lazy volumes, decoding, scheduling, caches.
- `modules/viewer/advanced/`: advanced viewer implementation.
- `PacsClient/.../vtk_widget/`: legacy/VTK container and backend selection bridge.
- `modules/mpr/`: standard Zeta MPR and external Advanced MPR/Slicer integration.
- `modules/zeta_boost/`: image/cache acceleration.
- `modules/zeta_sync/`: cross-viewport synchronization and geometry mapping.
- `modules/ai_imaging/`: Eagle Eye and modality-specific AI workflows.
- `modules/dental_imaging/`, `modules/stitching/`: specialized imaging domains.

Hard invariant: Fast, Advanced, MPR, and other VTK domains do not share mutable render objects, transforms, cameras, or VTK image instances. Share immutable, identity-keyed inputs only. A cache shared across domains must be explicitly designed for that contract; it is not an incidental optimization.

Progressive display is a Fast-viewer workflow. It must preserve series identity, DICOM ordering, current slice, and main-thread widget lifecycle. Never re-sort a clinical stack by a convenient but incomplete field.

### Download Manager

`modules/download_manager/` is a stateful subsystem with distinct responsibilities:

- state store: authoritative queue/item state;
- coordinator and rule engine: admission, priority, retry, and intent decisions;
- worker subprocess: blocking download work;
- UI observer/widget: Qt projection of state;
- patient/viewer integration: progress, completion, and critical-series intent.

The patient tab can mark the series being viewed as critical. Download events update thumbnails and can grow a progressive Fast-viewer series. ZetaBoost must not compete with active download-critical work and resumes after the blocking condition clears.

Do not bypass the coordinator by adding a second downloader in UI code. Do not reconnect the retired gRPC download route.

### EchoMind, AI, and command execution

- `modules/EchoMind/echomind_http.py` is the transport authority for EchoMind AI/voice HTTP behavior.
- `modules/EchoMind/viewer_chat/` owns report/chat workflows and prompt assembly.
- `modules/EchoMind/secretary/` owns parsing, orchestration, adapters, permission classification, audit, and `CommandBus`.
- `modules/ai_imaging/eagle_eye_lumbar/` owns the current lumbar LLM pipeline and its model routing.
- `database/ai_sessions_db.py` and related repositories persist AI sessions, messages, reports, and workflow metadata.

Every external AI call must be off the GUI thread, cancellable or timeout-bounded, correlated to the originating patient/study/session, and prevented from painting a stale result after the user changes context.

Clinical data sent to an AI provider is a separate disclosure boundary. Before extending payloads, document exactly which DICOM fields, images, prompts, or reports leave the workstation and why.

### Identity, consultation, and AiPacs Chat

- `modules/Identity/`: account providers and token ownership.
- `modules/cloud_consultation/`: online consultation workflow.
- `modules/aipacs_chat/`: operator console for the shared Laravel patient-chat backend; it depends on Identity.

AiPacs Chat is a second client of the existing backend, not a second chat system. Conversation, message, case, and read-state identity remain server-owned. Local storage is a cache for files/thumbnails, not the authority for conversation history.

Network calls in these modules must stay off the GUI thread. Tokens must remain in the owning identity/session layer and must not be copied into widgets, logs, fixtures, or package templates.

### Agent Gateway

`modules/agent_gateway/` is a production product subsystem, not the developer test MCP server.

```text
Paired external client
  -> LAN HTTPS or outbound relay
  -> bearer device authentication (+ optional E2E secure channel)
  -> Streamable-HTTP-style MCP JSON-RPC subset
  -> GUI-thread dispatcher
  -> existing EchoMind CommandBus
  -> existing adapters and permission gate
```

Properties verified in source:

- default product behavior is OFF, and packaged config forcibly ships OFF;
- LAN and relay transports feed one transport-independent core;
- pairing codes are short-lived and single-use;
- device tokens are stored hashed and returned once;
- TLS identity, device state, and channel private keys live in ignored roaming/source-runtime config and are excluded from packaged templates;
- permission modes map to `read_only`, end-user `assistant`, or unrestricted QA/full execution;
- network I/O runs outside the GUI thread; CommandBus execution is marshalled onto it;
- every call uses the existing CommandBus action catalog instead of a duplicate implementation.

Current local-development warning: the ignored source-run Agent Gateway configuration is enabled and assigns newly paired devices `full` mode. Even though no relay endpoint is configured, starting the source app can bind the LAN listener. Unless the task explicitly tests paired-device/MCP behavior, launch with the gateway disabled (for example, the operator kill switch) and do not expose it on a clinical network.

The gateway is core source, not one of the 15 installer-managed `MODULE_CATALOG` entries. `ai_imaging`, `network`, `auto_update`, and several other source packages are similarly internal subsystems rather than selectable installer modules. Do not mistake the installation catalog for a complete source-module inventory.

## 5. Primary data and workflow flows

### Patient search and study open

1. Home search builds a request from the selected server/profile and filters.
2. The socket patient service executes the blocking request in an executor, using the shared connection pool and JWT token manager.
3. Results populate the home table; reception/workflow data may enrich them independently.
4. Opening a patient creates/selects a patient tab and resolves local study/series state.
5. Thumbnail metadata and cached thumbnails appear first; missing clinical data is queued through Download Manager.
6. Viewer selection loads a series through the configured backend and records critical-series intent.

The multi-server feature partitions the database and DICOM tree by active profile. Runtime profile switching is restart-only because many modules bind path constants at import time while the DB pool resolves the path dynamically. A socket-only live switch can split the database from the image tree.

### Download-to-viewer flow

```text
PatientWidget request
 -> Download Manager coordinator/rules/state
 -> worker subprocess -> PACS socket protocol
 -> DICOM files + DB rows + progress events
 -> thumbnail refresh
 -> Fast progressive grow or normal series completion
 -> ZetaBoost/cache work after critical download pressure clears
```

Identity must remain based on patient/study/series identifiers, not only a display number or path. UI progress is a projection of the state store; it is not authoritative state.

### Reporting and reception flow

1. Viewer/EchoMind builds a report against the active study/session.
2. AI generation uses the EchoMind transport authority and preserves prompt/source-fidelity rules.
3. Local AI session/report state is stored in SQLite.
4. Report HTML is normalized for the workflow backend; embedded images travel as bounded bytes, not local file paths.
5. Workflow REST owns admission/report lifecycle metadata, while the socket status service synchronizes the PACS-facing status path.

The report editor is Qt rich text, not a browser. Its supported HTML and image-normalization rules are documented and guarded; web-CSS assumptions will silently lose formatting or images.

### Module install/update flow

```text
MODULE_CATALOG + package definition
 -> materialized package/zip + manifest
 -> optional SHA-256 verification
 -> extract and validate manifest/path/dependencies
 -> copy/register runtime payload
 -> update installation profile
 -> health check
 -> apply feature flag
 -> restart when required
```

Installed plugin Python paths can precede the frozen engine on `sys.path`. Therefore the package payload is production runtime code and can override the source frozen into the executable.

### Core application update flow

```text
update_sources.json
 -> update_feed.json
 -> hashed delta manifest
 -> safe-path validation and local diff
 -> content-addressed download + per-file SHA-256
 -> staging
 -> external apply helper after app exits
 -> backup + boot marker + retained rollback script
```

The reviewed update path provides hash integrity and path allowlisting, but no publisher-signature verification was found. The Windows installer also has no Authenticode signing step. Treat distribution authenticity as an open release-security gap.

## 6. Storage and configuration ownership

### Clinical and user data

`PacsClient/utils/data_paths.py` is the path registry. In source development, user data is under `user_data/`. Installed builds prefer a writable `User Data` directory beside the engine and fall back to the user profile.

Major trees:

- clinical: DICOM images, attachments, thumbnails, SQLite database;
- shared: education, AI/segments, EchoMind memory/logs, reports, caches, browser state, application logs;
- lazy/default-off: AiPacs Chat local files/thumbnails are created only when used.

Never add a second path scheme. Import paths from the registry or its documented re-exports.

### SQLite

The shared SQLite database uses WAL, foreign keys, a bounded connection pool, busy timeout, and explicit commits for writes. Core hierarchy is `patients -> studies -> series -> instances`; the database also owns download progress, education, AI sessions/messages/reports, consultation, notifications, identity links, and overrides.

Rules:

- use `with get_db_connection()`;
- bind parameters rather than interpolate SQL;
- commit writes explicitly;
- do not carry a connection across an async boundary;
- add indexes for new filter/join paths;
- keep migrations forward-only and idempotent;
- tests must patch `PacsClient.utils.data_paths.DATABASE_FILE`, clear the pool, and prove the live DB was not opened.

### Configuration layers

- Source run: repository `config/` is active development configuration.
- Frozen install: sanitized templates are seeded into roaming user configuration.
- Machine/runtime state: hardware probe, Agent Gateway keys/devices/certificates, and similar artifacts are not package templates.
- Installer module selection: `config/installation_profile.json`.
- Installed module payloads/manifests: runtime module package area (ProgramData/install layout).

`builder/config_sanitizer.py` is the packaging authority for center-specific values. Any new endpoint, credential, machine identity, or default-enabled network listener must be added to its explicit sanitization/exclusion policy and covered by a release-parity test.

## 7. Network boundary map

| Boundary | Owner | Purpose | Development rule |
|---|---|---|---|
| PACS custom socket | `modules/network/socket_*` | patient/study lists, metadata, thumbnails, DICOM download, report-status operations | Primary imaging route; use service singleton/pool/token manager; never call raw sockets from UI |
| Legacy gRPC | legacy client code | older compatibility paths | Do not use for new download or imaging work |
| Workflow REST | reception/report/assignment services | admission, reception, report and workflow metadata | Separate from socket; timeout-bounded and off GUI thread |
| EchoMind AI HTTP | `modules/EchoMind/echomind_http.py` | report/chat/STT provider traffic | One transport authority; runtime credentials only; redact logs |
| Identity/web REST | `modules/Identity/` | authentication and account session | Identity owns tokens; locally decoded JWT claims are not signature validation |
| AiPacs Chat REST | `modules/aipacs_chat/` | manager-side consultation conversations | Uses Identity backend/session; server state is authoritative |
| Cloud consultation | `modules/cloud_consultation/` | consultation exchange and attachments | Feature-gated; separate workflow state; bounded background I/O |
| Agent Gateway LAN/relay | `modules/agent_gateway/` | external paired MCP clients | Default-off product feature; TLS/pair/token/mode gate; audit all commands |
| Update source | `aipacs_runtime.py`, `modules/auto_update/` | module packages and core deltas | Hash and safe-path checks; no release until origin authenticity/signing is solved |
| External Advanced MPR | `modules/mpr/advanced_3d_slicer/` | Slicer-based runtime | Separate process/runtime package; validate payload and startup script |

The socket framing contract is a four-byte big-endian length followed by UTF-8 JSON. Use exact reads, `sendall`, response-size bounds, timeouts, and pooled reconnect behavior. The usual imaging socket port is not the DICOM association port.

## 8. Installer-managed module catalog

This is the current runtime catalog, not every directory under `modules/`.

| ID | Tier/kind | Default | Dependency / special boundary |
|---|---|---:|---|
| `viewer` | basic/core | on | patient viewer surface and backend domains |
| `download_manager` | basic/core | on | socket download, state store, subprocess worker |
| `zeta_boost` | basic/core | on | cache/boost scheduling around viewer/download pressure |
| `education` | basic/core | on | local courses, cases, assets |
| `stitching` | basic/core | on | specialized VTK/image output |
| `offline_cloud_server` | basic/core | on | offline export/server workflow |
| `identity` | basic/core | on | feature flag; account/token owner |
| `data_analysis` | optional/bundled unlock | on | installer classification is optional despite default enabled |
| `advanced_mpr` | optional/runtime payload | off | external `AIPacsAdvancedViewer.exe`/Slicer payload |
| `printing` | optional/bundled unlock | off | production payload can override frozen module |
| `run_cd` | optional/bundled unlock | off | maps to `modules/cd_burner` |
| `web_browser` | optional/bundled unlock | off | QtWebEngine lifecycle and browser CommandBus adapter |
| `echomind` | optional/bundled unlock | off | AI/reporting/voice/CommandBus; mirrored payload |
| `consultation` | optional/bundled unlock | off | maps to `modules/cloud_consultation` |
| `aipacs_chat` | optional/bundled unlock | off | requires `identity`; feature flag |

For a new selectable module, update all of: runtime catalog, package definition, installer components/types, profile writer, config-family versioning/sanitizer, feature flag, payload mirror, health check, dependency rules, and runtime/builder guards.

## 9. Packaging and release boundaries

### Dual-location rule

For catalog modules with packaged Python payloads, edits under `modules/<name>/` may require an identical production copy under `builder/plugin package/packages/<id>/payload/python/modules/<name>/`.

Use the repository mirror tools; do not hand-edit only one side. A plain sync updates known pairs, while a newly added mirrored file requires the documented add flow. Verify mirror parity after every mirrored change.

### Release path

1. prove release branch/source freshness;
2. resolve the dirty worktree intentionally;
3. sanitize config and verify no patient/secret/machine state is staged;
4. sync and verify plugin mirrors;
5. build clean from `.venv_build`;
6. require pre-build and post-stage release gates;
7. inspect frozen bytecode/catalog and staged package parity;
8. compile installer;
9. hash artifact and complete install-time QA on a clean machine;
10. use the deployment safety skill before any production promotion.

Never use generated build output as source and never bypass a red release gate to produce an artifact.

## 10. Development skills routing

Skills encode repeatable reasoning/workflow instructions; MCP provides live resources or controlled actions. They solve different problems and can be combined.

| Skill | Use when | AI-PACS rule |
|---|---|---|
| `titan-engineering-system` | any non-trivial feature, refactor, API, database, security, performance, or test change | Default engineering workflow: architecture, threat/data/thread analysis, narrow implementation, verification, self-review |
| `deploy-safety-check` | build is about to be shipped, deployed, released, or promoted | Mandatory final safety gate for workstation or production website work |
| `alizadeh-infrastructure` | touching PACS, wina100, lina100, VMware/vCenter/ESXi, clinical DICOM services, or A100 inference | Use only for the explicitly scoped machines; separate infrastructure evidence from local code evidence |
| `openai-docs` | choosing/configuring OpenAI APIs, models, Codex, skills, MCP, or current platform behavior | Use current official documentation; do not rely on remembered API details |
| `openai-developers:openai-platform-api-key` | building/running/debugging an OpenAI-backed feature or configuring credentials | Credential gate; reuse-or-create decision; never expose plaintext |
| `openai-developers:openai-api-troubleshooting` | OpenAI/AI provider requests fail | Classify auth/quota/rate/network/model failures before changing product logic |
| `computer-use:computer-use` | a change needs visual validation in the Windows app | Use source build only and pair with deterministic state/tests; visual evidence does not replace guards |
| `browser:control-in-app-browser` or `chrome:control-chrome` | testing website/embedded-browser behavior that depends on a browser session | Use only for the browser/web boundary; do not substitute it for application CommandBus tests |
| `aipacs-conference-loop` | owner explicitly asks to run the named adversarial conference loop | Never invoke by default; it stops at a reviewed plan before coding |
| `seo-aipacs` | work is in the separate public website/SEO/CRO boundary | Not for workstation feature work merely because the product name is AI-PACS |
| artifact skills (`pdf`, `documents`, `spreadsheets`, `presentations`) | a feature or deliverable specifically needs that artifact type | Task-specific only; they are not general workstation-development dependencies |

A dedicated project skill is not required yet because `AGENTS.md`, this map, the subsystem index, and regression catalog already provide layered repository memory. Create one later only if a stable, repeated AI-PACS workflow needs executable scripts/templates beyond repository instructions.

## 11. MCP and control-surface routing

| MCP/control surface | Verified state | Use | Safety boundary |
|---|---|---|---|
| `aipacs-control` (`tools/testing/aipacs_control_mcp`) | server code exists; Python `mcp` package is installed; not registered in this Codex session or `.vscode/mcp.json` | deterministic source-app lifecycle, patient/viewer/download/browser workflows, pressure scenarios | Source-only; requires `AIPACS_TEST_SERVER=1`; never enable during clinical reading; `change_layout` remains not implemented |
| In-app Agent Gateway MCP (`modules/agent_gateway`) | product code and tests exist; local source config currently enabled; not a local Codex stdio server | paired mobile/AI clients over LAN/relay using the production CommandBus | Separate production trust boundary; pairing, token, TLS/E2E, device mode, audit; disable for routine local work |
| GitHub connector | callable in current Codex environment | remote issues, PRs, reviews, CI, releases when explicitly in scope | Local Git remains source for uncommitted work; external writes need user intent |
| Filesystem MCP | configured in `.vscode/mcp.json`, not needed by Codex here | editor clients lacking native workspace access | Codex already has native file tools; avoid duplicate write paths |
| Sequential-thinking MCP | configured in `.vscode/mcp.json`, not needed by Codex here | clients that need an explicit reasoning helper | Titan + normal agent reasoning already cover this workflow |
| SQLite MCP (`sqlite_recovered`) | named in user Codex config but not exposed in this session | optional read-only schema/data diagnostics | Never point at the live clinical DB for routine development; isolated test DB and repository code are safer |
| Infrastructure/analytics/browser MCPs | some are configured or available globally | only when their external system is explicitly part of the task | Do not send patient data to generic analytics, website, messaging, or browser tools |

Before the first live automation task, register `aipacs-control` with the current Codex MCP configuration and verify only `ping`/`list_actions` first. Registration is an environment setup action, not a product-code change. Keep pywinauto tests for real OLE drag/drop and use visual inspection for rendered-output defects; CommandBus-level testing does not cover those surfaces.

## 12. Pre-code gate for every future task

Before editing:

1. classify the task: UI, viewer, network, DB, AI, module, packaging, infrastructure, or release;
2. read the matching subsystem docs and guard index;
3. inspect `git status` and the relevant dirty diff;
4. state the authoritative identities and data owner;
5. map threads/processes/timers and teardown ownership;
6. map every network/storage trust boundary and credential source;
7. determine whether a plugin mirror or packaged runtime overrides the source;
8. identify the regression test that should fail before the change;
9. choose the smallest implementation seam and rollback/kill switch;
10. use direct pytest, not `run_test.ps1`, until its failure-masking defect is fixed.

After editing:

1. run the focused guard and subsystem suite directly;
2. run cross-boundary tests for every affected connection;
3. sync/verify packaged mirrors if applicable;
4. verify no live database, patient data, secret, generated runtime state, or unrelated dirty file changed;
5. perform source-app visual/live validation only when the defect surface requires it;
6. update the regression catalog and indexes;
7. self-review security, concurrency, lifecycle, compatibility, and operational observability;
8. stop before deployment unless the deployment safety gate passes.

## 13. Current blockers and unresolved decisions

Do not erase these from memory during feature work:

1. **Credential incident:** API-key-shaped values remain committed in EchoMind source, mirrors, and tests. Treat them as compromised and do not display them.
2. **Untrustworthy merge wrapper:** the full direct suite is red and `run_test.ps1 -Fast` can return success after pytest fails.
3. **No CI:** secret scan, lint, tests, and package parity rely on local execution.
4. **Lint gap:** Ruff is configured but absent from the development requirements/environment.
5. **Distribution authenticity:** hashes exist, but the updater and installer do not establish publisher authenticity/code signing.
6. **Agent Gateway dev exposure:** ignored source config currently enables a LAN-capable gateway with `full` default device mode; disable it for unrelated runs.
7. **Catalog boundary ambiguity:** internal product subsystems such as Agent Gateway and AI Imaging are outside the selectable module catalog; preserve that distinction or document a deliberate migration.
8. **Runtime profile switching:** server/profile changes require restart; do not implement a socket-only half-switch.
9. **Known performance risks:** MPR activation and per-series filesystem status work require measurement-first fixes.
10. **Repository hygiene:** active work and generated build/runtime artifacts coexist in a large dirty tree; never reset or broadly format it.

## 14. Evidence captured for this map

- Startup wiring verified in `main.py`, `PacsClient/app_handler.py`, and `PacsClient/pacs/workstation_ui/mainwindow_ui.py`.
- Runtime module catalog verified directly from `aipacs_runtime.MODULE_CATALOG` (15 entries).
- Agent Gateway startup/shutdown wiring verified in the home panel and `main.py`.
- Agent Gateway, test-server, and CommandBus focused validation: **104 passed**, 3 deprecation warnings, direct pytest, 2026-08-27.
- The source virtual environment can import the `mcp` Python package.
- `.vscode/mcp.json` contains only filesystem and sequential-thinking servers; current Codex callable MCP tools do not include `aipacs-control`.
- Source Agent Gateway runtime state is ignored by Git; build sanitization explicitly excludes device/key/certificate material and forces the shipped gateway off.
- Packaging/update behavior verified from `aipacs_runtime.py`, `builder/config_sanitizer.py`, builder runbooks/gates, and `modules/auto_update/`.
- Repository-wide health and security baseline remains the separate readiness report.

## 15. External protocol references

- OpenAI skills concept: <https://developers.openai.com/plugins/concepts/skills>
- OpenAI MCP server concept: <https://developers.openai.com/plugins/concepts/mcp-server>
- Codex `AGENTS.md` behavior: <https://learn.chatgpt.com/docs/agent-configuration/agents-md>
- Codex MCP configuration: <https://learn.chatgpt.com/docs/extend/mcp>
