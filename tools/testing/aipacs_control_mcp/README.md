# aipacs-control — direct application control for testing agents

Bridges MCP tools → in-app **Test Control Server** (QLocalServer) → EchoMind
**CommandBus** → real application functions. Agents invoke `OpenPatient`,
`DragSeries`, `OpenMPR`, … directly instead of driving the mouse — at queue
pressure a human can't produce, with seeded, replayable scenarios.

Architecture: `docs/reports/TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md` (repo root).

## Components

| Piece | Path |
|---|---|
| In-app server (env-gated) | `modules/EchoMind/secretary/test_server.py` (started from `home_panel/widget.py` when `AIPACS_TEST_SERVER=1`) |
| Test-only write adapter | `modules/EchoMind/secretary/adapters/viewer_write_adapter.py` (registered ONLY in test mode) |
| MCP server | `tools/testing/aipacs_control_mcp/server.py` |
| Python client + CLI | `tools/testing/aipacs_control_mcp/client.py` |
| Scenarios | `tools/testing/aipacs_control_mcp/scenarios/*.json` |
| Clinical validation runner | `tools/testing/aipacs_control_mcp/clinical_agent_validation.py` |
| Session recordings | `tools/testing/aipacs_control_mcp/sessions/*.jsonl` (auto) |

## Requirements

- The **source build** venv (`<repo>\.venv`) — PySide6 already present.
- The MCP package, installed once into that venv:
  ```powershell
  & "<repo>\.venv\Scripts\python.exe" -m pip install mcp
  ```
- The app launched **with the test server enabled** (source build only; the
  server refuses frozen builds and is OFF without the env var):
  ```powershell
  # restore full env (agent-shell launches miss WINDIR/COMPUTERNAME — see memory)
  foreach ($s in 'Machine','User') { [Environment]::GetEnvironmentVariables($s).GetEnumerator() | ForEach-Object { [Environment]::SetEnvironmentVariable($_.Key, $_.Value, 'Process') } }
  $env:COMPUTERNAME = [System.Environment]::MachineName
  $env:USERNAME     = [System.Environment]::UserName   # Machine scope sets USERNAME=SYSTEM — restore it, the socket name derives from it
  $env:AIPACS_TEST_SERVER = '1'
  Start-Process "<repo>\.venv\Scripts\python.exe" -ArgumentList "main.py" -WorkingDirectory "<repo>"
  ```
  Startup banner confirms: `[TEST_SERVER] LISTENING on local socket 'AIPACS_TEST_<user>'`.

## Connect to Claude Desktop

Add to `%APPDATA%\Claude\claude_desktop_config.json` (merge into existing
`mcpServers`), then fully restart Claude Desktop:

```json
{
  "mcpServers": {
    "aipacs-control": {
      "command": "E:\\ai-pacs\\ai-pacs codes\\ai-pacs beta version\\.venv\\Scripts\\python.exe",
      "args": ["E:\\ai-pacs\\ai-pacs codes\\ai-pacs beta version\\tools\\testing\\aipacs_control_mcp\\server.py"]
    }
  }
}
```

The same entry works for Cowork/Claude Code as a custom MCP server (stdio).

## Tools

**Plumbing:** `ping`, `list_actions`, `raw_command`.
**Workflow (each terminates in the same production function as the real UI
action — see `docs/reports/MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md`):**
`list_patients` (real server search incl. modality checkboxes; rows carry
`patient_id`/`study_uid`/`patient_name`/`report_status`/`series_count`),
`select_patient` (single-click → selection + right-panel thumbnails; name/uid
auto-resolve from the last search), `open_patient` (real double-click handler),
`drag_series` (T1 `change_series_on_viewer` — the exact function a real drop
defers to, incl. the dropEvent `_pending_action_id` KPI stamp), `raw_command
get_series_info` (per-series numbers/counts of the active tab), `open_mpr`,
`close_patient_tab` (real `tabCloseRequested`), `switch_tab` (0=Home,
1=Download Manager, patients from 2), `trigger_download`,
`query_download_state`, `wait_for_download`, `query_viewport_state`
(series/slices/awaiting/progressive/spinner per viewport),
`query_thumbnail_state`, `snapshot_health`. **Browser:** `browser_open`,
`web_search`, `browser_open_url`, `browser_get_url`, `browser_get_text`,
`browser_get_html`, `browser_get_links`, `browser_dom_summary`,
`browser_find_element`, `browser_extract_table`, `browser_screenshot`,
`browser_fill_field`, `browser_click`, `browser_submit_form`. `change_layout` is a typed
NOT_IMPLEMENTED stub until the toolbar layout route is mapped (P1).
**Lifecycle:** `launch_app` (source build only, full env restore, auto-dismiss
startup notifications, auto Sign In, readiness ping), `stop_app`, `app_status`,
`wait_app_ready`, `dismiss_startup_dialogs`, `login`, `list_monitors`,
`move_app_to_monitor` (A/B letters or index).
**Pressure:** `burst` (N commands, 0 ms apart if desired — they queue
one-per-event-loop-turn inside the app), `run_scenario` (seeded JSON timelines,
`[min,max]` jittered delays, loops, JSONL session recording).
**Contract guard:** `tests/code/echomind/test_adapter_contracts.py` pins the
live-adapter API these tools depend on — run it whenever adapters change.

## CLI quick check (no MCP needed)

```powershell
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\client.py ping
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\client.py list_actions
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\client.py open_patient '{\"patient_id\": \"44704\"}'
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\client.py change_series '{\"series_number\": 201, \"viewport\": 0}'
```

## Clinical agent validation run

The live end-to-end workflow requested for Secretary/EchoMind validation is:

```powershell
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\clinical_agent_validation.py `
  --launch-app `
  --config tools\testing\aipacs_control_mcp\scenarios\clinical_agent_validation.default.json
```

It loads yesterday's MRI/MR list, switches to CT, searches/opens a patient,
imports a series into a viewport, navigates the stack, captures/OCRs the GUI,
and attempts measurement. Output lands in
`user_data/echomind/agent_runs/clinical_validation/<timestamp>/`.
See `docs/agent_control/clinical_agent_validation_pipeline.md`.

Architecture requirement: this runner is only the local orchestrator/executor.
The default scenario requires the external GPT brain (`external_brain.enabled=true`,
`required=true`) for patient, series, slice, and measurement-strategy decisions.
The brain call goes through the same EchoMind Secretary connection
(`modules.EchoMind.llm_client`), so the AI-PACS company backend / GapGPT is the
default. Those decisions are logged to `external_brain_decisions.jsonl`.

## Smooth visible demo

For watching the agent operate the UI without blink/hiccup, use the paced demo:

```powershell
& "<repo>\.venv\Scripts\python.exe" tools\testing\aipacs_control_mcp\smooth_visible_agent_demo.py `
  --launch-app --monitor A --pause-s 2.5
```

This demo focuses the `AIPacs` window once, then sends only in-app CommandBus
actions. It avoids repeated restore/maximize/foreground calls, which were the
main cause of visible blinking during manual demonstrations.
Output lands in `user_data/echomind/agent_runs/smooth_visible_demo/<timestamp>/`
with `report.json`, `commands.jsonl`, and `conversation.jsonl`.
If an old app is already running without the test server, add `--stop-existing`.

## Safety

- OFF by default; only `AIPACS_TEST_SERVER=1` + source build starts it.
- Write-side viewer commands exist ONLY while the server is enabled.
- Every command runs the production code path — cross-patient isolation and
  multi-study guards stay enforced.
- Never enable on a workstation during clinical reading.

## Fidelity tiers (when choosing a tool)

- **T1 (these tools):** state-level race hunting at max rate.
- **T2 (P3 roadmap):** posted QMouseEvent/QDropEvent — debounce/dwell coverage.
- **T3:** `tests/gui/pywinauto` — real OLE drag (Crash-A surface). Keep running
  it as a regression lap; T1 speed never replaces it.
