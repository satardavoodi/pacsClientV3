# aipacs-control — direct application control for testing agents

Bridges MCP tools → in-app **Test Control Server** (QLocalServer) → EchoMind
**CommandBus** → real application functions. Agents invoke `OpenPatient`,
`DragSeries`, `OpenMPR`, … directly instead of driving the mouse — at queue
pressure a human can't produce, with seeded, replayable scenarios.

Architecture: `TESTING_AUTOMATION_ARCHITECTURE_REVIEW_2026-06-04.md` (repo root).

## Components

| Piece | Path |
|---|---|
| In-app server (env-gated) | `modules/EchoMind/secretary/test_server.py` (started from `home_panel/widget.py` when `AIPACS_TEST_SERVER=1`) |
| Test-only write adapter | `modules/EchoMind/secretary/adapters/viewer_write_adapter.py` (registered ONLY in test mode) |
| MCP server | `tools/testing/aipacs_control_mcp/server.py` |
| Python client + CLI | `tools/testing/aipacs_control_mcp/client.py` |
| Scenarios | `tools/testing/aipacs_control_mcp/scenarios/*.json` |
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
action — see `MCP_VS_REAL_WORKFLOW_FIDELITY_2026-06-04.md`):**
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
`query_thumbnail_state`, `snapshot_health`. `change_layout` is a typed
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
