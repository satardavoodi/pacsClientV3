# EchoMind Secretary Agent Handoff

Date: 2026-07-05

Use this file when another AI agent continues the Secretary/MCP work.

## Current Objective

Continue turning the existing EchoMind Secretary control plane and the existing
`aipacs-control` FastMCP server into a safer, more complete workstation agent.

Primary reference:

- `docs/reports/ECHOMIND_SECRETARY_AGENT_MCP_EVALUATION_2026-07-05.md`

## Architecture Snapshot

The repo already has the control spine:

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
  -> real AI-PACS functions

External MCP client
  -> tools/testing/aipacs_control_mcp/server.py
  -> tools/testing/aipacs_control_mcp/client.py
  -> modules/EchoMind/secretary/test_server.py
  -> same CommandBus
  -> same AdapterRegistry
  -> same app adapters
  -> same real AI-PACS functions
```

Important: do not split this into two independent agents. Secretary EchoMind
is the user-facing voice/chat/AI entry point. The MCP server is an external
transport over the same execution/action layer. Add new workstation functions
as CommandBus actions and expose thin MCP wrappers only when external tools
need them.

There is only one product app-control structure:

```text
intent -> EchoMind reasoning -> CommandPlan -> CommandBus -> adapter -> app
```

GUI automation scripts and MCP scenarios are validation harnesses. They must
not become a parallel product command path.

See `docs/agent_control/secretary_mcp_unified_entrypoint.md`.

## Implemented in This Slice

1. `ViewerWriteCommandAdapter.change_series` now accepts:
   - `series_number`
   - `series_index` (0-based ordinal from active tab series rows)
   - `series_uid`

2. `get_series_info` now includes `series_uid` in rows, so callers can resolve by UID.

3. The patient viewer module catalog now documents:
   - `get_active_tab`
   - `list_open_tabs`
   - `get_series_info`
   - `query_viewport_state`
   - `change_series`
   - `scroll_slices`
   - `switch_tab`
   - `change_layout` as currently not implemented

4. The FastMCP server now exposes first-class browser tools:
   - `browser_open`
   - `web_search`
   - `browser_open_url`
   - `browser_get_url`
   - `browser_get_text`
   - `browser_get_html`
   - `browser_get_links`
   - `browser_dom_summary`
   - `browser_find_element`
   - `browser_extract_table`
   - `browser_screenshot`
   - `browser_fill_field`
   - `browser_click`
   - `browser_submit_form`

5. `AipacsControlClient.send` and `fire` can carry an optional `mode` field to
   the in-app test server. The MCP `raw_command` also accepts `mode`.

6. The live end-to-end clinical validation runner now exists:
   - `tools/testing/aipacs_control_mcp/clinical_agent_validation.py`
   - `tools/testing/aipacs_control_mcp/scenarios/clinical_agent_validation.default.json`
   - runbook: `docs/agent_control/clinical_agent_validation_pipeline.md`

7. `UiProbe` now persists the full command reply with each visual probe record,
   allowing one step to provide both GUI screenshots and code-level data.

8. The clinical validation runner now follows the required two-layer agent
   architecture:
   - local runner = orchestrator/executor only
   - external GPT brain = patient/series/slice/measurement decision maker
   - brain calls go through `modules.EchoMind.llm_client.chat_completion`, using
     the same EchoMind Secretary connection. In AI-PACS company deployment this
     is GapGPT by default, not a separate OpenAI-only client.
   - decisions are logged to `external_brain_decisions.jsonl`
   - default scenario has `external_brain.enabled=true`,
     `required=true`, `allow_local_fallback=false`

9. Agent runtime artifacts are stored under EchoMind user data:
   - `user_data/echomind/agent_runs/clinical_validation/<timestamp>/`
   - `user_data/echomind/agent_runs/smooth_visible_demo/<timestamp>/`
   - screenshot PNGs are mirrored to
     `user_data/echomind/agent_artifacts/`, matching the Secretary screenshot
     convention.
   - each run writes `report.json`, `commands.jsonl`, and `conversation.jsonl`;
     clinical validation also writes screenshots/OCR artifacts, GPT decisions,
     and error-log extracts.

## Verification Commands

Run these from the repo root:

```powershell
& ".\.venv\Scripts\python.exe" -m pytest modules\EchoMind\secretary\tests -q
& ".\.venv\Scripts\python.exe" -m pytest tests\code\echomind\test_test_server.py tests\code\echomind\test_mcp_server_inventory.py tests\code\echomind\test_clinical_agent_validation_pipeline.py -q
```

Optional inventory check:

```powershell
@'
from pathlib import Path
import ast
p = Path("tools/testing/aipacs_control_mcp/server.py")
mod = ast.parse(p.read_text(encoding="utf-8"))
tools = []
for node in mod.body:
    if isinstance(node, ast.FunctionDef):
        for dec in node.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr == "tool":
                tools.append(node.name)
print(len(tools))
print("\n".join(tools))
'@ | & ".\.venv\Scripts\python.exe" -
```

## Next Best Work

Priority order:

1. Configure the EchoMind company backend / GapGPT connection for the external brain:
   - `modules.EchoMind.settings_store`
   - active backend should normally remain `company`
   - secretary model from EchoMind settings or scenario `external_brain.model`
   - no API keys should be committed to scenario files.

2. Run the clinical validation pipeline on a live Windows source build:
   - `clinical_agent_validation.py --launch-app --config scenarios/clinical_agent_validation.default.json`
   - inspect `report.json`, `report.md`, `commands.jsonl`, and screenshots.
   - inspect `external_brain_decisions.jsonl` to confirm GPT made the workflow decisions.
   - confirm artifacts are under `user_data/echomind/agent_runs/`, not `tools/testing`.

3. Add viewer measurement commands:
   - `activate_tool`
   - `measure_distance`
   - `get_measurements`
   - then update `clinical_agent_validation.py` so measurement no longer needs
     workstation-specific coordinates.

4. Add MCP resources:
   - actions
   - active tab
   - viewport state
   - series list
   - download state
   - latest artifacts/logs

5. Add screen capture and OCR CommandBus actions:
   - active app window screenshot
   - active viewport screenshot
   - OCR from screenshot
   - typed `OCR_UNAVAILABLE` when Tesseract/pytesseract is absent

6. Add assistant-safe MCP profile:
   - default `mode="assistant"` or `mode="read_only"`
   - hide or deny `raw_command`, `burst`, `run_scenario`, `close_patient_tab`,
     `stop_app` in assistant mode
   - keep current QA behavior available under `aipacs-control-qa`

7. Add browser MCP tests:
   - static wrapper inventory test
   - fake client/send tests for action names and entities

8. Decide whether to split generic control code out of
   `modules/EchoMind/secretary` into `modules/agent_control`.
   Do this only after behavior is stable, with re-export shims.

## Known Sharp Edges

- `change_layout` is still a typed `NOT_IMPLEMENTED` stub.
- Browser read tools may open/activate the browser because the underlying adapter resolves
  a live browser widget for every browser action.
- The existing MCP server is QA-oriented and defaults to the in-app server's QA mode unless
  a tool passes `mode`.
- `raw_command` is powerful and should not be exposed in a clinical assistant profile.
- The app-side test server requires `AIPACS_TEST_SERVER=1` and refuses frozen builds.
- Main diagnostic viewer measurement is still not exposed through CommandBus.
  The clinical pipeline marks that stage `blocked` unless a coordinate-based
  measurement scenario is supplied.
