# EchoMind Secretary Clinical Agent Validation Pipeline

**Status:** Implemented 2026-07-05 as a live end-to-end runner.

This pipeline validates that the Secretary/EchoMind agent path can operate AI-PACS like a user: patient-list search, modality switch, patient open, series import, stack navigation, OCR capture, and measurement validation.

## Architecture Rule

This script is a validation harness, not a second product agent.

Production user control must stay on the single EchoMind app-control spine:

```text
Secretary EchoMind voice/text
  -> EchoMind LLM backend / GapGPT
  -> SecretaryExecutor
  -> CommandBus
  -> adapters
  -> AI-PACS
```

The validation runner wraps that same execution layer to prove the workflow can
be completed end to end. It must not become a parallel command system.

Inside the harness, responsibilities are separated like this:

- **Local orchestrator / executor:** controls AI-PACS, collects CommandBus state, captures screenshots, runs OCR, validates returned IDs/actions, logs evidence, and executes approved actions.
- **External GPT brain:** receives the current workflow context through `modules.EchoMind.llm_client`, decides which patient/series/slice/measurement strategy to use, and returns compact JSON decisions.

For this project, the external brain must use the same EchoMind Secretary connection. In the AI-PACS company deployment this is the company backend / GapGPT. OpenAI is only an alternate backend when EchoMind settings explicitly select it.

The default scenario sets:

```json
"external_brain": {
  "enabled": true,
  "required": true,
  "allow_local_fallback": false
}
```

If the EchoMind company backend / GapGPT connection is not configured, the pipeline should fail loudly instead of silently making intelligent local choices. A deterministic local fallback may be enabled only for QA plumbing tests.

Any new reusable workstation behavior discovered while building this harness
must be promoted into a CommandBus action and adapter. Do not leave it as
private workflow logic in the validation script.

## Entry Point

Run from the repository root:

```powershell
& '.\.venv\Scripts\python.exe' 'tools\testing\aipacs_control_mcp\clinical_agent_validation.py' `
  --launch-app `
  --config 'tools\testing\aipacs_control_mcp\scenarios\clinical_agent_validation.default.json'
```

Use a fixed patient if the first CT row is not clinically useful:

```powershell
& '.\.venv\Scripts\python.exe' 'tools\testing\aipacs_control_mcp\clinical_agent_validation.py' `
  --config 'tools\testing\aipacs_control_mcp\scenarios\clinical_agent_validation.default.json' `
  --patient-id 12345
```

The app must run with the in-app test server enabled. `--launch-app` does that through `tools/testing/aipacs_control_mcp/lifecycle.py`. Without `--launch-app`, the runner connects to an already-running app with `AIPACS_TEST_SERVER=1`.

## Smooth Visual Operation

When a human is watching the agent work, do not repeatedly call OS-level
restore/maximize/focus around every action. That causes visible blinking and
Qt repaint hiccups.

Use these rules:

- Focus or move the `AIPacs` window once at the start only.
- Execute workflow steps through the CommandBus, not mouse/focus loops.
- Wait for state probes such as `get_series_info` and `query_viewport_state`.
- Add small human-observable pauses only between major clinical actions.
- Use `smooth_visible_agent_demo.py` for demonstrations.

Command:

```powershell
& '.\.venv\Scripts\python.exe' 'tools\testing\aipacs_control_mcp\smooth_visible_agent_demo.py' --launch-app --monitor A --pause-s 2.5
```

Smooth-demo artifacts are written to:

```text
user_data/echomind/agent_runs/smooth_visible_demo/<timestamp>/
```

## What It Produces

Each run writes to:

```text
user_data/echomind/agent_runs/clinical_validation/<timestamp>/
```

Artifacts:

- `report.json`: structured machine-readable final report.
- `report.md`: human-readable summary for the next agent.
- `commands.jsonl`: every CommandBus request/reply.
- `conversation.jsonl`: local orchestrator timeline, stage notes, and action transcript.
- `external_brain_decisions.jsonl`: GPT context and returned JSON decisions.
- `error_logs.json`: relevant app/viewer/download log lines from the run window.
- Per-step `UiProbe` folders such as `01_patient_list_mri/`, `06_import_series/`, and `07_stack_middle_slice/` containing `before.png`, `first_change.png`, `stable.png`, `tab_strip.png`, and `clip.gif`.

Tool code remains under `tools/testing`. Runtime artifacts, screenshots,
conversation logs, command logs, OCR text, GPT decisions, and reports belong
under `user_data/echomind/agent_runs/`.

Screenshot PNG artifacts are also mirrored to the shared EchoMind Secretary
artifact folder:

```text
user_data/echomind/agent_artifacts/
```

This matches the existing Secretary screenshot convention and makes the latest
agent captures easy to find outside a specific run folder.

If an old app instance is already open without `AIPACS_TEST_SERVER=1`, use:

```powershell
& '.\.venv\Scripts\python.exe' 'tools\testing\aipacs_control_mcp\smooth_visible_agent_demo.py' --stop-existing --launch-app --monitor A --pause-s 2.5
```

## Validation Stages

The runner checks:

- app open / test-server ping
- live GUI capture availability
- yesterday MRI patient list loaded
- modality switch to CT returned refreshed rows
- GPT selected/approved a patient from the candidate rows
- patient search found the selected patient
- patient row selection completed
- patient tab opened and became active
- series metadata / thumbnails loaded
- GPT selected/approved the series to import
- selected series imported into viewport 0
- viewport reported a loaded image stack
- GPT selected/approved the slice for OCR/measurement context
- stack navigation reached the middle slice
- OCR ran against the `07_stack_middle_slice/stable.png` screenshot
- GPT selected/approved the measurement strategy
- measurement completed or is explicitly blocked with reason

## GPT Backend Configuration

The external brain uses the existing EchoMind LLM settings:

- `modules.EchoMind.settings_store`
- `modules.EchoMind.llm_client.chat_completion`
- secretary feature model from EchoMind settings unless overridden in the scenario

Configure the EchoMind Secretary company backend / GapGPT key using the existing EchoMind settings path. The local runner does not store API keys in the scenario.

Implementation detail: `chat_completion()` resolves the active EchoMind backend. The default settings use `llm_backend="company"`, so GapGPT is used unless the application settings have deliberately switched to `openai`.

## Measurement Reality

As of 2026-07-05, the main diagnostic viewer does not expose first-class CommandBus tools for:

- `activate_tool`
- `measure_distance`
- `get_measurements`

Therefore `measurement` is a required stage and will be `blocked` unless the scenario provides coordinate automation.

To automate a GUI measurement now, edit the scenario:

```json
{
  "measurement": {
    "mode": "coordinate_drag",
    "tool_click": [120, 80],
    "start": [700, 420],
    "end": [850, 420],
    "after_tool_s": 0.4,
    "after_drag_s": 1.0
  }
}
```

Coordinates are absolute screen coordinates on the test workstation. After the drag, the runner captures the GUI again, runs OCR, and extracts values matching units like `mm`, `cm`, `px`, or `deg`.

## OCR Requirements

OCR uses `modules.EchoMind.secretary.background.verification`:

- Python package: `pytesseract`
- Binary lookup order: bundled `tools/vendor/tesseract/tesseract.exe`, then `AIPACS_TESSERACT`, then `PATH`

If OCR is unavailable, `ocr_capture` fails with `OCR_UNAVAILABLE` but still leaves the screenshot artifact for review.

## Code-Level Validation Hooks

The script validates through the app CommandBus where available:

- `list_patients` for MRI and CT lists
- `select_patient` and `open_patient`
- `get_active_tab`
- `get_series_info`
- `change_series`
- `query_viewport_state`
- `scroll_slices`
- `list_actions`

The key GUI transitions are wrapped with `UiProbe`, so the same step has both a command reply and visual evidence.

## Recommended Next Development

1. Add a viewer measurement adapter with `activate_tool`, `measure_distance`, and `get_measurements`.
2. Add a viewport-only screenshot CommandBus action so OCR can target the image pane instead of the whole window.
3. Add a `select_viewport` action and active viewport reporting.
4. Add image/screenshot payload support to `ExternalGPTBrain` after viewport capture is available, so GPT can reason over visual context as well as OCR/state.
5. Promote this runner into CI only for a Windows machine with an attached display, PACS server access, stable test data, and a test GapGPT/company backend key.
6. Keep PHI-safe run retention rules for screenshots, OCR text, and GPT decision logs.
