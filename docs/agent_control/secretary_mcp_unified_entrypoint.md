# Secretary EchoMind and MCP Unified Entry Point

Date: 2026-07-06

Status: architecture rule and current-code review.

## Required Architecture

Secretary EchoMind is the primary user-command entry point.

Most user commands should enter through the Secretary voice UI, pass through
the existing transcription pipeline, then use the existing EchoMind LLM/agent
structure to decide what action is needed. The action execution must go
through the shared CommandBus action layer that is also exposed by the MCP
server.

There must be one agentic app-control structure:

```text
intent -> EchoMind reasoning -> CommandPlan -> CommandBus -> adapter -> app
```

Every caller must join this structure instead of building a parallel route.

Approved shape:

```text
User voice
  -> PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py
  -> SttRouter.transcribe_files(...)
  -> SecretaryOrchestrator.handle(...)
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

This keeps one agent pipeline and one execution spine:

- Secretary EchoMind = user-facing voice/chat/AI entry point.
- EchoMind LLM backend / GapGPT = reasoning brain.
- CommandBus and registered adapters = execution/action layer.
- MCP server = external transport and automation surface over that same
  execution layer.

## Important Rule

Do not build two independent agents:

- no independent MCP planner/brain that duplicates Secretary EchoMind;
- no separate Secretary action implementation that duplicates MCP behavior;
- no second command registry with different action names or semantics.
- no GUI automation workflow that becomes the product command path when a
  CommandBus action can exist.

New workstation capabilities should be added as CommandBus actions and
adapter methods. Secretary can call them through `SecretaryExecutor` and MCP
can expose thin wrappers for the same action names.

Validation scripts under `tools/testing/aipacs_control_mcp/` are allowed to
drive the app for QA, screenshots, and demos. They are not a second product
agent. When they need real application behavior, they should call the same
CommandBus actions and produce evidence that the unified path works.

## Current-Code Review

### Voice entry point is already Secretary EchoMind

`secretary_button_widget.py` handles recorded voice, calls
`SttRouter.transcribe_files(...)`, appends the transcript, and sends a payload
to `SecretaryOrchestrator.handle(...)`.

That means voice commands already enter through the existing Secretary
transcription and response pipeline.

### LLM decision layer is already in Secretary EchoMind

`SecretaryOrchestrator` lazy-loads `AgentBrain`. `AgentBrain` uses
`modules.EchoMind.llm_client`, including the company backend / GapGPT path.

The local executor should remain an orchestrator and validator. The advanced
interpretation belongs in the external LLM backend configured by EchoMind.

### Secretary execution already reaches the shared action layer

`SecretaryExecutor.execute(...)` owns a small set of home-panel actions
directly. For non-home actions it calls `_try_command_bus(...)`, builds a
`CommandPlan`, and executes it through the live `CommandBus`.

This is the correct integration point for viewer, browser, download, OCR,
measurement, and future workstation commands.

### MCP is connected to the same execution layer

`tools/testing/aipacs_control_mcp/server.py` is a FastMCP server. Its tools call
`AipacsControlClient`, which connects to
`modules/EchoMind/secretary/test_server.py`. The in-app test server dispatches
JSON actions to the same live `CommandBus`.

The MCP server is therefore not a separate brain. It is a transport layer for
external automation, QA, and agent validation.

## Literal MCP Loopback Decision

The current in-app Secretary does not call the external FastMCP stdio server.
It calls the shared in-process `CommandBus` directly.

That is intentional and should stay the default. Looping the in-app Secretary
out through FastMCP and back into the same process would add transport
fragility and can make visible control less smooth. The architectural goal is
still satisfied because Secretary and MCP share the same execution contracts
and action registry.

If a future deployment strictly requires "Secretary -> MCP -> CommandBus", add
a small transport interface such as `SecretaryActionTransport` with the default
implementation backed by the in-process CommandBus and an optional MCP-backed
implementation for external deployments. Do not duplicate planning or action
logic in that interface.

## Development Rules for Future Agents

1. Add new executable functions as CommandBus actions.
2. Put real UI/workstation behavior in adapters, not in MCP wrapper code.
3. Let Secretary invoke those actions through `SecretaryExecutor`.
4. Let MCP expose thin wrappers that only validate arguments and forward the
   same action names.
5. Keep external GPT/GapGPT calls inside the EchoMind LLM layer, not inside the
   MCP server.
6. Treat GUI automation and MCP scenarios as validation harnesses, not as
   production command implementations.
7. Store screenshots, OCR text, conversations, and run reports under
   `user_data/echomind/`.
8. For visible demos, use smooth CommandBus actions and avoid repeated
   OS-level focus/maximize loops.

## Current Gaps

- Viewer measurement actions are not yet first-class CommandBus actions.
  Required next actions: `activate_tool`, `measure_distance`,
  `get_measurements`.
- Viewport-only screenshot and OCR are not yet first-class CommandBus actions.
- MCP remains QA-oriented by default because it exposes powerful tools like
  `raw_command`, `burst`, and lifecycle launch/stop helpers. A product
  assistant profile should hide or deny those.
- Assistant permission mode is opt-in with `AIPACS_AGENT_ASSISTANT_MODE=1`.
  Product use should enable and validate this mode.

## Verification

The architecture is guarded by:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest tests\code\echomind\test_secretary_mcp_unified_entrypoint.py -q
```
