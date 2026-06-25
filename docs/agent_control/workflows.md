# Agent-Control Workflows (multi-step task execution)

**Status:** 2026-06-23. Engine implemented + offscreen-verified
(`tests/code/echomind/test_workflow.py`, 7 tests). Live wiring into the voice assistant is
**staged** (flag-gated) — see "Wiring" below.

## The problem it fixes

The brain plans ONE action per utterance and `orchestrator._run_plan` runs one plan, so a compound
command like *"download this patient and open it"* only downloaded (observed live 2026-06-23,
patient 47734 — the LLM logged *"only one action is allowed so I prioritized download"*). The
workflow engine adds the missing **sequencing + per-step verification** layer.

## Engine (`modules/EchoMind/secretary/workflow.py`, pure stdlib)

- `WorkflowPlan(goal, steps)`, `WorkflowStep(tool, args, verify, capture)`, `VerifySpec(...)`.
- `WorkflowExecutor(run_step, sleep).run(plan)`:
  1. resolve args (`"$key"` → value captured from an earlier step's result),
  2. execute the step via the injected `run_step(action, entities)`,
  3. if the result is not `ok` → **stop**, report `failed_index`,
  4. capture configured result fields into the shared context,
  5. if the step has a `verify` → probe a **read-only** action and re-check until it passes
     (bounded `retries`/`delay_s` for async effects like download); if it never passes → **stop**,
  6. otherwise advance to the next step.
- Returns `WorkflowResult(ok, goal, steps=[StepResult...], failed_index, message)`.

The engine is injectable (no Qt/VTK/bus import), so the SAME engine drives the voice path
(`run_step` = `executor.execute(..., confirmed=True)`) and the MCP path (`run_step` = `bus.execute`).

## Verification kinds (probe existing read actions)

| `verify.kind` | Probe action | Passes when |
|---|---|---|
| `download_complete` | `check_download_status` | status ∈ {complete, downloaded, …} or received ≥ total |
| `patient_open` | `get_active_tab` | active `patient_id` == expected |
| `thumbnails_loaded` | `get_thumbnails_data` | non-empty series/thumbnail list |
| `viewport_has_series` | `query_viewport_state` | target viewport holds the expected series number/UID |

These map 1:1 to the requested verification resources (`resource://patient/download-status`,
`/current`, `/thumbnail-state`, `resource://viewer/active-viewports`). Today they are read **tools**;
exposing them as first-class MCP `resource://` URIs is a staged P1 item.

## Example plans

**"Download this patient and open it"**
```json
{"goal": "download + open", "steps": [
  {"tool": "download_patient", "args": {},
   "verify": {"kind": "download_complete", "probe_action": "check_download_status", "retries": 30, "delay_s": 2.0},
   "capture": {"patient_id": "patient_id", "study_uid": "study_uid"}},
  {"tool": "open_patient", "args": {"patient_code": "$patient_id"},
   "verify": {"kind": "patient_open", "probe_action": "get_active_tab", "expect": {"patient_id": "$patient_id"}}}
]}
```

**"Download this patient, open it, and load the first series"** adds:
```json
  {"tool": "get_thumbnails_data", "args": {},
   "verify": {"kind": "thumbnails_loaded", "probe_action": "get_thumbnails_data"}},
  {"tool": "change_series", "args": {"series_index": 0, "viewport": 0},
   "verify": {"kind": "viewport_has_series", "probe_action": "query_viewport_state", "expect": {"viewport": 0}}}
```

## Failure handling

- A step that returns `ok=false` (e.g. `NO_HOME_WIDGET`, `CONFIRM_REQUIRED`, `PERMISSION_DENIED`)
  stops the workflow; `WorkflowResult.failed_index` + `message` say which step and why. Later steps
  do NOT run.
- A step that runs but never verifies stops with `error_code="VERIFY_FAILED"` (e.g. download timed
  out). The assistant should report the partial progress, not pretend success.
- The engine never raises into the caller (a crashing step is captured as `STEP_CRASHED`).

## Decomposition

`decompose(text)` is a deterministic first layer for the documented English compound commands
(returns `None` for single-action input, which falls through to the legacy path). **The general,
language-agnostic solution** (handles Persian, the primary UI language) is to let the brain emit a
multi-step plan; the engine then executes it. That brain/prompt change is staged for live
verification.

## Wiring (IMPLEMENTED, flag-gated `AIPACS_SECRETARY_WORKFLOWS`; needs live verification)

The brain now produces multi-step plans and the orchestrator executes them:

1. **Phase-2 prompt** (`prompts/agent_phase2_prompt.txt`) instructs the LLM to emit
   `{"goal": ..., "steps": [<action>, ...]}` for genuinely sequential requests (EN + FA examples),
   single action otherwise.
2. **Brain** (`brain/agent.py` `_normalize_multistep` + `brain/multistep.py`): when the LLM emits
   steps AND the flag is on → a `__workflow__` plan; **flag OFF → collapses to the FIRST action**
   (byte-identical to today, so the prompt change is safe regardless of the flag). `plan()`
   validates the steps via `validator.validate_steps`.
3. **Orchestrator** (`orchestrator.py`): a flag-gated early branch detects the `__workflow__` plan,
   confirms ONCE up front (reusing the existing yes/no turn via a `confirm_workflow` pending state),
   then runs `WorkflowExecutor` with `run_step` bound to `executor.execute(..., confirmed=True)`.
   The single-action path is untouched when the flag is off (the brain never emits `__workflow__`).

**Offscreen-verified:** `build_plan` + `multistep` parsing/aggregation (4 tests) and the engine
(7 tests). `validate_steps` logic confirmed; brain/orchestrator wiring **compiles on Windows** but
its end-to-end behavior (LLM emitting steps + execution + confirm-once) needs the source build.

**To verify live:** set `AIPACS_SECRETARY_WORKFLOWS=1`, then say *"download this patient and open
it"* → expect one confirm prompt, then both actions run with per-step verification. Kill switch:
unset the flag (legacy single-action behavior returns immediately).
