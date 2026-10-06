# Secretary and MCP settings implementation receipt

Date: 2026-10-01. Owner request: implement improved workstation control, including routine patient workflows and settings requests about storage, image quality, personal AI configuration and themes. Terminology: EGLI means Eagle Eye.

## Implemented source behavior

The shared CommandBus now exposes open_settings, get_settings_capabilities, get_theme, set_theme, diagnose_resources, settings_operation_status, request_storage_cleanup, get_storage_cleanup_status, configure_personal_ai and configure_image_quality. Production Gateway tools/list enumerates these actions; the existing stdio bridge also has settings_control. Home wiring injects the existing settings host after its construction, without eagerly constructing every settings page.

Settings navigation selects the correct lazy root and child page for server, viewer, tools, image filters, storage, EchoMind, Eagle Eye, Agent, installation and consultation/education. Module gating still applies. No generic configuration writer, arbitrary path, code or credential argument is accepted.

Theme control lists actual presets and validates exact names before writing. Persistence occurs off the GUI thread through an atomic replacement; Qt applies the theme and emits the existing theme signal only after successful persistence. Poll the returned operation_id. A concurrent manual theme change supersedes the assistant operation and restores the latest manual settings off-thread before terminal status. Unknown themes and failed writes do not change the active palette.

Resource diagnosis asynchronously returns RAM usage and free space for the application's storage drive, without scanning study folders, exposing paths, closing viewers or deleting files. RAM pressure is distinguished from disk pressure. Poll settings_operation_status for completion.

Cleanup requests are restricted to cache and printing. The existing storage panel owns active-work safeguards, local human confirmation, cleanup workers, database consistency and normal UI result presentation. MCP dispatch returns before the modal confirmation. Duplicate pending requests are blocked. get_storage_cleanup_status reports awaiting confirmation, running, cancellation/blocking, failure, or completion counters from the actual worker result. No patient, course or offline-package deletion action was added.

configure_personal_ai opens EchoMind settings and reveals the existing local OpenAI password/prompt forms without selecting or persisting a provider. The user enters credentials locally, supplies their own prompt and uses the existing save/test flow. Responses explicitly say awaiting_local_input and connected:false. No actual key was accessed, changed or tested by this task. Recognizable API-key-bearing Secretary input is rejected before local session history and remote planning; the voice transcript callback checks before logging/displaying it. The server Request also rejects recognizable credentials in text/memory. This does not certify removal of legacy secrets or prevent a key spoken into an already transmitted STT recording; use the local password field.

configure_image_quality opens the requested existing viewer/tools/filter page and reports that settings have not changed. Ambiguous quality complaints must be clarified before changing a clinical display/filter setting. No new decoder/filter algorithm, diagnostic preset inference, original-pixel mutation or automatic image-quality analysis was introduced.

## Shared control corrections

Client and headless server Secretary allowlists now include current detailed Eagle Eye actions, viewport observation/capture/measurement actions, routine read/search aliases and settings actions. New settings proposals cannot contain credential/path arguments. Mutating theme/cleanup/personal-AI and detailed Eagle Eye proposals normalize confirmation before execution; local policy remains authoritative. Eagle Eye module instructions now describe the actual study-scoped action surface instead of claiming unsupported finding/explanation commands.

The test transport now carries an explicit boolean confirmation to the existing registry gate. Omitted confirmation remains false and non-boolean confirmation is rejected. settings_control uses assistant permissions; it never silently selects QA privileges to perform a mutation. Existing production Gateway confirmation semantics remain intact.

ModuleCommandAdapter previously returned ok:true when a launcher returned None. It now returns MODULE_LAUNCH_FAILED, avoiding a false workspace-open claim.

## Evidence and ownership

Fail-before selection: seven failures and one pass demonstrated missing settings registration, Secretary allowlist gaps, absent strict settings schemas, and false-positive module launch. A separate test-control guard failed before confirmation propagation was implemented. Final combined direct pytest selection: 194 passed, exit 0, with nine existing TLS/SWIG deprecation warnings. The selection includes the three new assistant-settings test files, Secretary server/remote planner, module/browser/education adapters, Eagle Eye commands, Gateway, command bus, execution contracts, MCP inventory, storage-panel async, lazy settings startup, app-theme enforcement and package registry. No live clinical database or model/API call was used by the new tests.

The scoped synchronizer add_paths entry point was used with dry-run then write for owned EchoMind Python files. Owned catalog assets were copied separately because that tool only handles Python. Whole-tree mirror verification checked 499 pairs and found one pre-existing unrelated viewer_chat/ai_chat_pages.py mismatch; it was preserved. The server snapshot manifest records hashes of this task's changed server-owned files/assets. UI/service files remain in the existing PacsClient base payload. No release build, installer, Git commit/push or deployment was performed.

Read-only documented client.py ping remains unavailable. The human was asked to start one source instance with -TestServer and sign in outside clinical use. No restart, launch flag change, login, cleanup, credential change or production Gateway enablement was performed by the agent. Live affected-workflow acceptance is pending and is not a pass. The new server catalog/validator/credential guards are staged source only; the active Eagle Eye Server requires a separately coordinated deployment before natural-language planning can use these controls in normal company operation.

Advanced Analysis execution and full Education authoring/presentation control remain outside this implemented settings slice. Existing Advanced Analysis runtime ownership, immutable source identity and completion contracts must be qualified through the owning workstream before exposing analysis tasks. Remote image delivery and a server-owned multimodal Secretary analysis contract also remain open, as recorded in the earlier image/mobile review. No full-software-control claim is made.

## Next live acceptance

After human source bootstrap, probe ping then list_actions. Verify native Settings navigation, select a known theme and observe terminal operation status plus visible recoloring, exercise resource diagnosis, cancel one cleanup confirmation without deletion, inspect local personal-AI entry without saved-key disclosure or provider mutation, and inspect image-quality Settings without altering clinical data. Perform permitted actions through both the shared Secretary execution path and MCP. A later coordinated server deployment must separately qualify planning/correlation/confirmation; paired mobile acceptance is separate.
