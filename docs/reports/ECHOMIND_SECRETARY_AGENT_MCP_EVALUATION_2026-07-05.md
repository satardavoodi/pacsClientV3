# EchoMind Secretary Agent and MCP Evaluation

Date: 2026-07-05

Scope:
- `modules/EchoMind/secretary`
- `tools/testing/aipacs_control_mcp`
- related agent-control docs and tests

Purpose:
Evaluate the current "Secretary EchoMind" agent/control module, the existing MCP server,
and the path to continue development into a safe, useful AI-PACS workstation agent.

2026-07-06 architecture update:

- Secretary EchoMind is the required user-facing voice/chat/AI entry point.
- The external EchoMind LLM backend / company GapGPT connection is the reasoning
  brain.
- The CommandBus and adapters are the shared execution/action layer.
- The MCP server is an external automation transport over that same action
  layer, not a second independent agent.
- See `docs/agent_control/secretary_mcp_unified_entrypoint.md`.

## Executive Summary

AI-PACS already has the most important foundation: a structured command plane.
The EchoMind Secretary package owns a `CommandBus`, `AdapterRegistry`, action envelopes,
permission classification, natural-language parsing/planning, and adapters that call real
application functions.

There is also already a real MCP server:

- `tools/testing/aipacs_control_mcp/server.py`
- implemented with `mcp.server.fastmcp.FastMCP`
- exposes 26 MCP tools
- connects to the running app through `modules/EchoMind/secretary/test_server.py`
- reaches the EchoMind `CommandBus`

Current chain:

```text
User voice/text
  -> Secretary EchoMind UI
  -> SttRouter / transcript
  -> SecretaryOrchestrator
  -> AgentBrain / EchoMind LLM backend / GapGPT
  -> SecretaryExecutor
  -> CommandBus
  -> AdapterRegistry
  -> app adapters
  -> real AI-PACS UI/functions

External MCP client
  -> tools/testing/aipacs_control_mcp/server.py
  -> tools/testing/aipacs_control_mcp/client.py
  -> modules/EchoMind/secretary/test_server.py
  -> same CommandBus
  -> same AdapterRegistry
  -> same app adapters
  -> same real AI-PACS UI/functions
```

The current MCP server is connected to Secretary EchoMind infrastructure, but it is a
QA/test-control surface, not the productized end-user voice entry point. It sends direct
structured actions such as `open_patient`, `change_series`, and `list_patients` to the
same CommandBus. It should remain a thin transport and must not grow a duplicate
natural-language brain.

Overall readiness:

| Area | Current state | Readiness |
|---|---|---|
| CommandBus architecture | Strong and reusable | High |
| MCP server existence | Implemented, FastMCP-based | High for QA |
| Main page control | Search/open/download mostly wired | Medium-high |
| Patient tab series/stack control | Real code path exists, planner contract mismatch remains | Medium |
| Browser control | Strong CommandBus actions, weak MCP first-class wrappers | Medium-high |
| Screen capture and OCR | Screenshot utilities exist, OCR helper exists, no agent action yet | Low-medium |
| Safety for clinical assistant use | Permission model exists, assistant mode is opt-in | Medium |
| Documentation/contracts | Useful docs exist, but some are stale or incomplete | Medium |

## Verified Current Inventory

Commands run with the repo venv:

```text
.venv\Scripts\python.exe -m pytest tests\code\echomind\test_test_server.py -q
Result: 4 passed

.venv\Scripts\python.exe -m pytest modules\EchoMind\secretary\tests -q
Result: 8 passed
```

The existing MCP server declares 26 `@mcp.tool()` tools:

```text
ping
list_actions
raw_command
open_patient
select_patient
list_patients
drag_series
open_mpr
close_patient_tab
switch_tab
trigger_download
query_download_state
wait_for_download
query_viewport_state
query_thumbnail_state
snapshot_health
burst
run_scenario
launch_app
stop_app
app_status
wait_app_ready
dismiss_startup_dialogs
login
list_monitors
move_app_to_monitor
```

With production-like wiring supplied to `build_command_bus`, the bus registers 66 actions,
including home, download, viewer, browser, education, EchoMind report, and system actions.
With no GUI objects, it intentionally registers only the four system probes.

## Current Architecture

### 1. Secretary Core

Important files:

- `command_bus.py`: parse/execute/dispatch entry point
- `registry.py`: action name to adapter method dispatch
- `command_envelope.py`: `CommandPlan`, `CommandRequest`, `CommandResult`
- `bus_factory.py`: production wiring of adapters
- `permissions.py`: side-effect classification and mode policy
- `audit.py`: bus/action audit helper

The bus is not inherently tied to natural language. Direct structured callers can build a
`CommandPlan` and call `bus.execute`.

### 2. Secretary Natural-Language Agent

Important files:

- `orchestrator.py`: session state, confirmation turns, brain/rule/LLM parsing
- `brain/agent.py`: two-phase LLM route and plan pipeline
- `brain/router.py`: module routing
- `parser_rules.py`: deterministic command parser
- `parser_llm.py`: fallback single-shot LLM parser
- `validator.py`: plan validation
- `workflow.py`: multi-step execution and verification
- `memory/memory_store.py`: conversation/action memory
- `stt/*`: speech-to-text providers

This path is the user-facing "Secretary EchoMind" experience: voice or text command in,
action plan out, then execution.

### 3. In-App Test Control Server

Important file:

- `modules/EchoMind/secretary/test_server.py`

This is a Qt `QLocalServer` JSON-lines bridge. It is enabled only when
`AIPACS_TEST_SERVER=1`, refuses frozen builds, and dispatches requests to the live
CommandBus. It defaults external requests to `agent_mode="qa"`.

This is the local app-side server that the MCP server talks to.

### 4. External MCP Server

Important files:

- `tools/testing/aipacs_control_mcp/server.py`
- `tools/testing/aipacs_control_mcp/client.py`
- `tools/testing/aipacs_control_mcp/lifecycle.py`
- `tools/testing/aipacs_control_mcp/scenarios/*.json`

This server is real MCP over stdio using FastMCP. It wraps the app-side test server
with agent-friendly tools, lifecycle helpers, burst testing, and scenario replay.

## What Works Well Today

### Main page: search, open, download

Supported through both Secretary and MCP paths:

- `list_patients`
- `select_patient`
- `open_patient`
- `download_patient`
- `select_and_download` in the Secretary executor

The home panel wires the CommandBus during startup and supplies the live home widget,
module launchers, active patient tab getter, tab widget getter, and background task engine.

### Patient tab: series and stack

Implemented actions:

- `get_active_tab`
- `list_open_tabs`
- `get_thumbnails_data`
- `get_active_series`
- `get_multistudy_info`
- `get_series_info`
- `query_viewport_state`
- `change_series`
- `scroll_slices`
- `switch_tab`

The important part: `change_series` calls the same viewer method used by the real drop path,
so it is a high-fidelity structured substitute for drag/drop.

### Browser and web module

Implemented CommandBus actions include:

- `open_browser`
- `web_search`
- `open_url`
- `browser_get_url`
- `browser_get_text`
- `browser_get_html`
- `browser_dom_summary`
- `browser_find_element`
- `browser_get_links`
- `browser_extract_table`
- `browser_screenshot`
- `browser_fill_field`
- `browser_click`
- `browser_submit_form`
- navigation aliases such as `browser_navigate`, `browser_reload`, `browser_go_back`

These are strong enough to support an agent controlling the embedded browser without
synthetic mouse movement.

### Permissions

`permissions.py` classifies actions as:

- `read_only`
- `ui_navigation`
- `local_write`
- `server_write`
- `destructive`

Modes include:

- `unrestricted`
- `read_only`
- `assistant`
- `qa`
- `server_write`
- `destructive`

This is a good safety foundation, but the default paths matter:

- MCP/test server defaults to `qa`, so it can run everything without confirmation.
- Secretary bus bridge only stamps `assistant` mode when `AIPACS_AGENT_ASSISTANT_MODE=1`.
- No `agent_mode` means legacy unrestricted behavior.

## Key Gaps and Risks

### 1. MCP server is QA-oriented, not product-agent-oriented

The existing MCP server is intentionally documented as a testing control surface.
It requires `AIPACS_TEST_SERVER=1` and exposes powerful tools such as:

- `raw_command`
- `burst`
- `run_scenario`
- `close_patient_tab`
- lifecycle launch/stop

This is excellent for development and regression testing. For a clinical assistant,
we should either:

1. add a separate safe MCP profile/server, or
2. add mode-gated tool groups to the existing server.

### 2. Series command contract mismatch

Current adapter:

```text
change_series requires entities.series_number
```

But prompt/workflow examples use:

```text
entities.series_index
```

This can cause natural-language planned "load the third series" workflows to validate but
fail at runtime with `BAD_ARGS`.

Required fix:

- Either accept both `series_number` and `series_index` in `ViewerWriteCommandAdapter`, or
- standardize all prompts/docs/workflows on `series_number`.

Preferred fix:

- Support both names.
- Treat `series_number` as the authoritative display/drop key.
- If `series_index` is provided, resolve it through `get_series_info` rows, not by blindly
  assuming index equals series number.

### 3. Patient viewer catalog is incomplete

`catalog/modules/patient_viewer.md` currently documents `open_patient` but does not fully
document:

- `get_series_info`
- `change_series`
- `query_viewport_state`
- `scroll_slices`
- `switch_tab`
- `change_layout` limitations

The code can perform many viewer actions, but the LLM planner is not reliably taught the
available patient-tab control vocabulary.

### 4. Screen capture and OCR are not agent tools yet

Existing utilities:

- browser screenshot through `browser_screenshot`
- background screenshot helper in `background/verification.py`
- OCR helper `ocr_image`

Missing agent-facing tools:

- capture active workstation window
- capture active patient viewport
- OCR current screen/window/viewport
- OCR last browser screenshot
- return image artifact path plus extracted text

### 5. Browser CommandBus actions are richer than MCP wrappers

The MCP server has `raw_command`, so it can call browser actions indirectly.
But it does not expose first-class MCP tools for:

- `browser_get_text`
- `browser_click`
- `browser_fill_field`
- `browser_extract_table`
- `browser_screenshot`
- `web_search`

For an agent, first-class wrappers with typed arguments are better than `raw_command`.

### 6. Safety mode should be explicit for assistant use

For clinical assistant work, defaulting to `qa` or unrestricted is too broad.
Assistant-facing transports should default to:

- `read_only` for inspection
- `assistant` for user-directed actions
- explicit confirmation for server-write/destructive actions

### 7. MCP resources and prompts are still missing

Current MCP is tools-only. For an agent, useful resources would be:

- `aipacs://actions`
- `aipacs://state/active-tab`
- `aipacs://state/viewports`
- `aipacs://state/downloads`
- `aipacs://logs/latest`
- `aipacs://artifacts/latest`

Useful prompts/workflows:

- "search, download, open, load series"
- "inspect current viewport and summarize state"
- "browser lookup and read current page"
- "OCR screen and summarize visible error"

### 8. Lifecycle path is hardcoded

`tools/testing/aipacs_control_mcp/lifecycle.py` hardcodes:

```text
E:\ai-pacs\ai-pacs codes\ai-pacs beta version
```

That is acceptable for the current workstation setup, but it should be made configurable
before broader reuse.

## Development Plan

### Phase 0: Stabilize the Current Understanding

Goal:
Make sure the current control surface is documented and reproducible.

Tasks:

1. Keep this report as the current map.
2. Add/update a short `docs/agent_control/current_status.md` that points to:
   - existing MCP server
   - Secretary CommandBus
   - browser tools
   - permission modes
3. Add a small inventory script or test that asserts:
   - MCP tool count and names
   - production-like bus actions
   - browser actions are registered when `web_browser` launcher exists
   - viewer write actions are registered when `enable_viewer_write=True`

Exit criteria:

- Focused tests pass.
- Tool inventory can be regenerated without manual reading.

### Phase 1: Fix Viewer Series Control

Goal:
Make patient-tab "drag/drop/import series to viewport" reliable through both MCP and
natural-language Secretary.

Tasks:

1. Update `ViewerWriteCommandAdapter.change_series` to accept:
   - `series_number`
   - `series_index`
   - eventually `series_uid`
2. Implement index-to-series resolution using `get_series_info` order.
3. Update `workflow.py` to emit `series_number` or resolve `series_index`.
4. Update `agent_phase2_prompt.txt`.
5. Expand `catalog/modules/patient_viewer.md`.
6. Add tests:
   - `change_series` with `series_number`
   - `change_series` with `series_index`
   - bad viewport
   - no active tab
   - multi-study opaque display keys preserved

Exit criteria:

- "load third series into viewport 0" can be planned and executed.
- MCP `drag_series` still works.
- No regression to existing viewer identity guards.

### Phase 2: Add First-Class MCP Browser Tools

Goal:
Expose browser control as typed MCP tools, not only via `raw_command`.

Tasks:

1. Add wrappers to `tools/testing/aipacs_control_mcp/server.py`:
   - `web_search`
   - `browser_open_url`
   - `browser_get_text`
   - `browser_get_html`
   - `browser_get_links`
   - `browser_dom_summary`
   - `browser_find_element`
   - `browser_fill_field`
   - `browser_click`
   - `browser_submit_form`
   - `browser_extract_table`
   - `browser_screenshot`
2. Pass explicit `mode` when needed, or add mode support to `_send`.
3. Add tests or smoke checks using fake/local app-side server where possible.

Exit criteria:

- An MCP client can control the embedded browser without using `raw_command`.
- Read-only tools can run under `read_only` mode.
- Form submission/navigate tools are classified as server-write.

### Phase 3: Add Capture and OCR Agent Tools

Goal:
Let the agent see what the workstation or browser shows when structured state is not enough.

Tasks:

1. Add app-side CommandBus actions:
   - `capture_active_window`
   - `capture_active_viewport`
   - `ocr_image`
   - `ocr_active_window`
   - `ocr_active_viewport`
2. Reuse existing artifact directory logic from `background/verification.py`.
3. Use `pytesseract` only when available; return typed `OCR_UNAVAILABLE` otherwise.
4. Add MCP wrappers:
   - `screen_capture`
   - `screen_ocr`
   - `viewport_capture`
   - `viewport_ocr`
5. Include artifact paths in `CommandResult.data`.

Exit criteria:

- Agent can request screenshot path and OCR text.
- OCR absence is a recoverable typed result, not a crash.

### Phase 4: Productize Safety Modes

Goal:
Make this usable as an assistant control surface, not only a QA harness.

Tasks:

1. Add explicit mode handling to MCP `_send` and tools.
2. Create safe tool groups:
   - read-only inspection
   - UI navigation
   - local viewer manipulation
   - server write
   - destructive QA tools
3. Default assistant-facing MCP calls to `assistant` or `read_only`.
4. Keep QA defaults only under a clearly named QA profile.
5. Consider splitting into:
   - `aipacs-control-qa`
   - `aipacs-secretary-agent`
6. Disable or hide `raw_command`, `burst`, `run_scenario`, `close_patient_tab`, and `stop_app`
   in assistant mode.

Exit criteria:

- A safe MCP profile cannot silently run server-write or destructive actions.
- QA profile remains available for development.

### Phase 5: Add MCP Resources and Prompts

Goal:
Make the MCP server more agent-native and less tool-spam driven.

Tasks:

1. Add MCP resources:
   - actions list
   - active patient tab state
   - viewport state
   - thumbnails/series state
   - download state
   - latest logs/artifacts
2. Add MCP prompts:
   - patient search-download-open
   - load series into viewport
   - browser lookup and summarize
   - OCR visible error and suggest next step
3. Promote scenario JSON files into reusable prompts where appropriate.

Exit criteria:

- Agent can inspect state via resources.
- Reusable workflows are discoverable by the host MCP client.

### Phase 6: Decide Ownership and Package Layout

Goal:
Separate generic control infrastructure from EchoMind assistant implementation.

Recommended long-term layout:

```text
modules/agent_control/
  command_bus.py
  command_envelope.py
  registry.py
  permissions.py
  audit.py
  adapters/
  test_server.py

modules/EchoMind/secretary/
  orchestrator.py
  brain/
  parser_rules.py
  parser_llm.py
  validator.py
  workflow.py
  prompts/
  catalog/
  stt/
  memory/

tools/testing/aipacs_control_mcp/
  QA MCP transport

tools/agent/aipacs_secretary_mcp/
  assistant-safe MCP transport, if split
```

Do not start with a large move. First add shims/re-exports and tests so existing imports stay
stable.

Exit criteria:

- EchoMind consumes the control plane.
- QA MCP consumes the control plane.
- Imports remain backward compatible.

## Recommended Immediate Backlog

Priority order:

1. Fix `series_index` vs `series_number`.
2. Expand `patient_viewer.md` with real viewer actions.
3. Add first-class MCP wrappers for browser actions.
4. Add capture/OCR CommandBus actions and MCP wrappers.
5. Add explicit MCP mode support and assistant-safe defaults.
6. Add MCP resources for read-only state.
7. Add prompt/workflow resources.
8. Consider package split after the behavior is stable.

## Implementation Progress

Started on 2026-07-05:

- `change_series` now accepts `series_number`, `series_index`, and `series_uid`.
- `get_series_info` now returns `series_uid` for follow-up resolution.
- `patient_viewer.md` now documents the real viewer-state and viewer-control actions.
- `aipacs-control` now has first-class MCP browser wrappers instead of requiring
  `raw_command` for common browser actions.
- `AipacsControlClient` can pass a per-request `mode` to the in-app test server.
- Continuation handoff added at `docs/agent_control/echomind_secretary_agent_handoff.md`.
- Live clinical validation pipeline added at
  `tools/testing/aipacs_control_mcp/clinical_agent_validation.py`, with default
  scenario `tools/testing/aipacs_control_mcp/scenarios/clinical_agent_validation.default.json`.
- Pipeline handoff/runbook added at
  `docs/agent_control/clinical_agent_validation_pipeline.md`.
- `UiProbe` now persists the full CommandBus reply in each visual probe record,
  so screenshots and code-level validation share the same step evidence.
- The validation runner now encodes the required two-layer architecture:
  local orchestrator/executor plus external GPT brain. The local runner
  collects state and validates returned IDs; GPT chooses patient, series,
  slice, and measurement strategy. The brain call uses the shared EchoMind
  Secretary LLM connection (`modules.EchoMind.llm_client`), so AI-PACS company
  deployments use GapGPT by default. Decisions are logged in
  `external_brain_decisions.jsonl`.
- Runtime artifacts now route to EchoMind user data:
  `user_data/echomind/agent_runs/clinical_validation/<timestamp>/` and
  `user_data/echomind/agent_runs/smooth_visible_demo/<timestamp>/`, including
  screenshots, command logs, conversation logs, OCR text, GPT decisions, and
  reports. Screenshot PNGs are also mirrored to
  `user_data/echomind/agent_artifacts/`, matching the existing Secretary
  artifact convention.

## Test Strategy

Fast/offscreen:

```text
.venv\Scripts\python.exe -m pytest modules\EchoMind\secretary\tests -q
.venv\Scripts\python.exe -m pytest tests\code\echomind\test_test_server.py -q
```

Recommended additions:

- unit tests for `ViewerWriteCommandAdapter.change_series` entity aliases
- unit tests for permission decisions for new capture/OCR/browser actions
- FastMCP tool inventory test
- browser wrapper tests using fake client/send
- OCR unavailable test
- static contract test for the live clinical validation runner/scenario

Live/source-build:

1. Launch with `AIPACS_TEST_SERVER=1`.
2. MCP `ping`.
3. `list_actions`.
4. `list_patients`.
5. `select_patient`.
6. `open_patient`.
7. `get_series_info`.
8. `drag_series`.
9. `query_viewport_state`.
10. `scroll_slices`.
11. Browser open/search/read screenshot.
12. Capture/OCR smoke after implemented.
13. Clinical validation runner:
    `tools/testing/aipacs_control_mcp/clinical_agent_validation.py --launch-app --config tools/testing/aipacs_control_mcp/scenarios/clinical_agent_validation.default.json`.
14. Confirm `external_brain_decisions.jsonl` exists and contains GPT decisions
    for patient, series, slice, and measurement strategy. The default scenario
    should fail if the EchoMind company backend / GapGPT connection is not configured.
15. Confirm run artifacts are written under `user_data/echomind/agent_runs/`.

## Current Conclusion

Do not build a new agent stack from scratch. The repo already has the right spine:

- Secretary CommandBus
- adapter registry
- permission classification
- app-side test server
- FastMCP wrapper
- browser structured tools
- viewer structured series/stack controls

The right next move is to harden and complete it:

1. make viewer commands planner-safe,
2. expose browser and OCR as first-class MCP tools,
3. make assistant safety modes explicit,
4. add resources/prompts,
5. then consider moving generic control code out of EchoMind.
