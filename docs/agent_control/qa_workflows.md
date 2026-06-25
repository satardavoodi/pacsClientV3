# QA / coding-agent workflows

**Status:** 2026-06-23. How a QA/coding agent drives and verifies the workstation through the
agent-control surface (state-based verification first; screenshots are a supplement, not the
primary signal).

## Two lanes

- **Verify lane (offscreen, autonomous):** pure / Qt-offscreen pytest in the Linux sandbox
  (`tools/dev/sandbox_setup.sh` → `sandbox_env.sh` → `pytest tests/code/... -p no:debugging -q`).
  Use for the workflow engine, permissions, and any pure logic. Does NOT run the real GUI/VTK.
- **Clinical lane (real):** the Windows **source build** with `AIPACS_TEST_SERVER=1`, driven by the
  `aipacs-control` MCP. The only lane that proves GUI/rendering/clinical behavior. Source build
  only — never the frozen exe; never enable the test server during real clinical reading.

The Test Control Server runs in `qa` mode (every action allowed, no confirmation pause), so the
permission gate is exercised + audited (`aipacs.agent_control.audit`, mode=qa) without changing
harness behavior.

## The standard QA loop (state-verified)

| # | Step | Tool | Verify (read action) |
|---|---|---|---|
| 1 | Launch app | `launch_app` (source build, `AIPACS_TEST_SERVER=1`) | `app_status` / `wait_app_ready` |
| 2 | Search patient | `list_patients {modality, date}` | rows non-empty |
| 3 | Open patient | `open_patient {patient_id}` | `get_active_tab` patient matches |
| 4 | Load thumbnails | `select_patient {patient_id}` | `query_thumbnail_state` / `get_thumbnails_data` non-empty |
| 5 | Drop series → viewport | `change_series {series_index, viewport}` | `query_viewport_state` target viewport holds series |
| 6 | Open MPR | `open_mpr` | `list_open_tabs` |
| 7 | Open Dental Curve MPR | `viewer.open_dental_curve_mpr` 🟧 staged | — |
| 8 | Screenshot | `viewer.capture_screenshot` 🟧 staged (today: `ui_probe.py` mss) | image saved |
| 9 | Verify state | `query_viewport_state`, `get_active_tab`, `snapshot_health` | matches expectation |
| 10 | Read logs | `user_data/logs/app.log`, `download_diagnostics.log`, EchoMind `session_logs/<date>.jsonl` | no Traceback / native fault |
| 11 | Pass/fail | scenario assertions (`run_scenario` `assert_health`) | all steps verified |

Multi-step commands are best driven as a **WorkflowPlan** (`workflows.md`) so each step is verified
before the next — this is the structured replacement for "type a sentence and hope".

## Verification resources (read-only state)

| Resource (conceptual) | Backed by | Use |
|---|---|---|
| `resource://patient/download-status` | `check_download_status` | download complete? |
| `resource://patient/current` | `get_active_tab` | which patient is open |
| `resource://patient/thumbnail-state` | `get_thumbnails_data` | thumbnails loaded |
| `resource://viewer/active-viewports` | `query_viewport_state` | viewport ↔ series |
| `resource://app/health` | `snapshot_health` (`snapshot_resources` + `count_native_faults_since`) | crashes / RSS |
| `resource://capabilities` | `list_actions` | what the agent can call |

(First-class MCP `resource://` URIs are a staged P1 item; today these are read **tools**.)

## Existing scenarios

`tools/testing/aipacs_control_mcp/scenarios/`:
- `bug1_drop_before_download.json` — drop not-yet-downloaded series; assert both viewports bind, no
  native faults.
- `impatient_full_loop.json` — high-pressure open/drop/switch/MPR/close under download, 5 loops.

Add new scenarios as JSON and run with `run_scenario {path, seed, loops}`.

## Failure handling

- A workflow step that fails verification stops the run and reports `failed_index` + reason — the
  agent reports the partial state, never a false pass.
- Read logs on failure: `app.log` for tracebacks, `download_diagnostics.log` for the socket path,
  EchoMind `session_logs/<date>.jsonl` for the per-command plan/result/error trail.
- Reading the live machine from a stale sandbox view fails silently — prefer Desktop Commander
  (`get_file_info` to confirm the real mtime) or run on the box itself.

## Offscreen test commands

```
bash tools/dev/sandbox_setup.sh && source tools/dev/sandbox_env.sh
python3 -m pytest tests/code/echomind/test_workflow.py tests/code/echomind/test_agent_permissions.py -p no:debugging -q
```
