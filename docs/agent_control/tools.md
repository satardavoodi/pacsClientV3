# Agent-Control Tools

**Status:** 2026-06-23. Companion to `docs/reports/AGENT_CONTROL_ARCHITECTURE_REVIEW_2026-06-23.md`.
This document is the authoritative inventory of agent-callable tools, with an honest
**Available / Partial / Staged** status for each requested capability.

## How a tool reaches the app

```
MCP tool (tools/testing/aipacs_control_mcp/server.py, FastMCP, stdio)
  → client.py (QLocalSocket, JSON-lines)
  → test_server.py (QLocalServer, per-user pipe; AIPACS_TEST_SERVER=1; refuses frozen build)
  → bus.execute(CommandPlan(action, entities), state={"agent_mode": mode})
  → registry.dispatch  ── permission gate (permissions.py) + audit (audit.record_bus_action)
  → adapter method → REAL app function (production code path; clinical guards enforced)
```

The voice/chat assistant (Secretary EchoMind) reaches the SAME bus via
`orchestrator → executor → _try_command_bus → bus.execute`.

## Permission modes (permissions.py)

Every dispatch is classified by **side-effect** (`read_only`, `ui_navigation`, `local_write`,
`server_write`, `destructive`) and gated by the session **mode** carried in `state["agent_mode"]`:

| Mode | Allowed | Confirmation |
|---|---|---|
| `unrestricted` (default/unscoped) | all | none (legacy-equivalent; gate inert) |
| `read_only` | read_only only | — |
| `assistant` (voice) | read/nav/local/server-write | server-write + destructive require confirm |
| `qa` (Test Control Server default) | all | none (automated) |
| `server_write` | read/nav/local/server | server-write/destructive confirm |
| `destructive` | all | destructive confirm |

Kill switch: `AIPACS_AGENT_PERMISSIONS=0`. The Test Control Server stamps `qa` by default and
accepts a per-request `{"mode": "..."}` override (e.g. `read_only` for safe exploration).

## Currently registered bus actions (production wiring, ~50 across 11 adapters)

| Group | Actions | Side-effect |
|---|---|---|
| system | `snapshot_resources`, `count_aipacs_processes`, `count_native_faults_since`, `probe_idle_cpu` | read_only |
| home | `list_patients`, `open_patient`, `select_patient`, `download_patient` | read / local / server |
| download | `check_download_status`, `list_downloads`, `download_statistics`, `pause_download`, `resume_download`, `cancel_download` | read / local / server / destructive |
| modules | `open_module`, `list_modules`, `toggle_eagle`, `open_mpr`, `open_printing`, `open_education` | ui_navigation |
| viewer (read-only) | `get_active_tab`, `list_open_tabs`, `get_thumbnails_data`, `get_active_series`, `get_multistudy_info` | read_only |
| viewer_write (safe subset) | `change_series`, `query_viewport_state`, `switch_tab`, `get_series_info`, `scroll_slices`, `change_layout`*(stub)* | local / read / ui-nav |
| echomind | `start_report`, `transcribe_voice`, `generate_report`, `send_report_to_pacs` | local / server-write |
| browser / education / agent | web nav, education nav, background tasks | ui-nav / server |
| viewer_write (TEST-ONLY) | `close_patient_tab` | destructive — only when `AIPACS_TEST_SERVER=1` |

## Requested tools → status map

✅ Available · 🟡 Partial (works via a near-equivalent) · 🟧 Staged (designed, needs live wiring + verification)

| Requested | Status | Backed by / note |
|---|---|---|
| `patient.search` | ✅ | `list_patients` |
| `patient.download` | ✅ | `download_patient` (MCP `trigger_download`, `wait_for_download`) |
| `patient.open` | ✅ | `open_patient` |
| `patient.open_after_download` | ✅ (new) | **workflow engine** (`workflow.py`): `download_patient` → verify `download_complete` → `open_patient`. See `workflows.md`. |
| `patient.load_thumbnails` | ✅ | `select_patient` (triggers load) + `get_thumbnails_data` (verify) |
| `patient.get_current` | ✅ | `get_active_tab` |
| `patient.get_series_list` | ✅ | `get_series_info` / `get_thumbnails_data` |
| `viewer.load_series_to_viewport(series_index)` | ✅ | `change_series` (series_number/index + viewport) — MCP `drag_series` |
| `viewer.drop_series_to_viewport(series_number, viewport)` | ✅ | `change_series` — structured, runs the real drop logic (no mouse) |
| `viewer.drop_series_to_viewport(series_uid, viewport)` | 🟧 | needs uid→series_number resolution in `viewer_write_adapter` (reads `_server_series_info`); see `patient_tab_viewer.md` |
| `viewer.get_loaded_series` | ✅ | `get_active_series` / `query_viewport_state` |
| `viewer.get_active_viewport` | 🟡 | `query_viewport_state` (per-viewport state; no single "focused id" field yet) |
| `viewer.select_viewport` | 🟧 | no focus-setter action today |
| `viewer.open_mpr` | ✅ | `open_mpr` |
| `viewer.open_dental_curve_mpr` | 🟧 | only the standard Zeta MPR launcher is wired; add a `curved_mpr` launcher |
| `viewer.set_layout` / `viewer.get_layout` | 🟧 | `change_layout` is a typed `NOT_IMPLEMENTED` stub |
| `viewer.apply_window_preset` | 🟧 | not exposed |
| `viewer.set_window_level_width` / `get_window_level_width` | 🟧 | not exposed (viewer has W/L internally) |
| `viewer.capture_screenshot` | 🟧 | only the external `ui_probe.py` (mss) captures today; add a viewport-grab action |
| `toolbar.list_tools` / `activate_tool` / `deactivate_tool` / `get_active_tool` | 🟧 | not exposed |
| `layout.set` / `get` / `reset` | 🟧 | same as `viewer.set_layout` (stub) |

**Drag/drop is already structured, not mouse-based:** `change_series` (a.k.a.
`drop_series_to_viewport`) calls the same `method_change_series_on_viewer(...)` the real drop uses —
reliable and testable. The only gap is the *by-UID* variant (🟧).

Staged items are specified in `patient_tab_viewer.md`. Each must be flag-gated and verified on the
Windows source build before default-on (they touch clinical viewer code).
