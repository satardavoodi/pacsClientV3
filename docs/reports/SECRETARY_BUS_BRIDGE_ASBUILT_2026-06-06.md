# Secretary → CommandBus Bridge — As-Built (2026-06-06)

Implements the priority fixes from `SECRETARY_ECHOMIND_PIPELINE_REVIEW_2026-06-06.md`.
The voice/text assistant is no longer capped at the 9 home-panel actions: validated
plans it cannot execute itself now route to the app's 24-action CommandBus.

## What changed (all gated / additive — the 9 home actions are untouched)

| File | Change |
|---|---|
| `secretary/validator.py` | New `_BUS_ALLOWED_ACTIONS` (modules, download control, viewer read, safe viewer writes). Bus actions validate leniently (adapters own entity typing). `close_patient_tab` deliberately excluded (destructive → test-server only). |
| `secretary/executor.py` | `SecretaryExecutor(adapter, command_bus_getter=…)`. Unknown actions now try `_try_command_bus()`: resolve bus lazily → `registry.has_action` → build `CommandPlan` → `bus.execute()` → convert `CommandResult`→`SecretaryResult`. Never raises; falls back to legacy `UNSUPPORTED_ACTION`. Kill-switch: `AIPACS_SECRETARY_BUS=0`. |
| `secretary/orchestrator.py` | Accepts `command_bus_getter`; **auto-derives it from `home_widget.command_bus`** when omitted — so the existing orb-button path (`secretary_bridge.create_secretary_orchestrator`) gains the bridge with no caller change. `_run_plan` no longer stores bus payloads as `last_patient` (would have poisoned "download this patient" after "open mpr"). |
| `secretary/parser_rules.py` | Module-open fast path BEFORE the open-patient branch: "open echomind / echo mind / eagle eye / eagleeye / mpr / printing / report module / education" (+ Persian variants) → `open_module{module}` — kills the old `open_patient` misparse. Only fires for open-verbs WITHOUT a patient code; "open patient 123" byte-identical. |
| `secretary/parser_llm.py` | `_ALLOWED_ACTIONS` now = validator's home set ∪ bus set (single source of truth) — the LLM fallback can plan module/viewer/download commands. |
| `secretary/bus_factory.py` | New `enable_viewer_write=` opt-in registering the SAFE viewer-write subset: `change_series`, `query_viewport_state`, `switch_tab`, `get_series_info`, `change_layout`. Not `close_patient_tab`. |
| `home_panel/widget.py` (PacsClient) | Production bus now passes `enable_viewer_write=True` and registers launchers for **echomind** (active tab → `ai_chat_layout_ui()`), **mpr** (active tab → `toolbar_manager.toggle_zeta_mpr()` — same as the MPR button), **printing** (`open_printing_module()`), **education** (`open_education_module()`), alongside the existing eagle_ai. All fail-safe (None → typed `MODULE_LAUNCH_FAILED`). |

## What now works by voice/text (was ❌ in the review)

- "Open EchoMind" → opens the chat window on the active patient tab (patient context = the open tab).
- "Open EagleEye" / "Open MPR" / "Open the report module" / "Open education".
- Viewer navigation: `change_series` ("load/show series N"), `switch_tab`, viewport/series queries, `change_layout`.
- Download control: pause/resume/cancel/status/list/statistics.
- Everything that worked before (list/open/download/select/sort/import) — unchanged, including the 2-turn confirmation on open/download.

## Phase 2 (same day): the previously-missing parts, now covered

**New `EchoMindCommandAdapter`** (`adapters/echomind_command_adapter.py`,
registered by bus_factory whenever `get_active_patient_tab` is wired — no
PacsClient change needed). Every action drives the SAME UI objects the user
clicks; all failures are typed envelopes:

| Voice command | Action | What it does |
|---|---|---|
| "Start a report for this patient" | `start_report` | Opens EchoMind on the report page for the ACTIVE patient tab (`ai_chat_layout_ui()` → `_open_mode_page('report')`); auto-attaches the newest voice recording when one exists. |
| "Transcribe this voice report" | `transcribe_voice` | Same open + REQUIRES the newest audio attachment (`ATTACHMENT_PATH/<study_uid>`), hands it to the composer (`_choose_file`) and selects the Transcribe tab. Typed `NO_AUDIO` when none. |
| "Generate the report" | `generate_report` | Presses the report composer's Send button (identical to the user click; `NOT_READY` when there is nothing to generate). |
| "Send this patient's report to PACS" | `send_report_to_pacs` | Finds the newest AI report bubble and invokes the SAME `_send_to_reception` flow as the bubble's send button. **Two human gates:** the Secretary confirm turn (executor returns `CONFIRM_REQUIRED` until the user says yes — enforced in `_try_command_bus` via `_BUS_CONFIRM_REQUIRED_ACTIONS`) **and** the interactive reception dialog with server-side patient validation. Voice can never silently push a report. `NO_REPORT` when nothing was generated. |

**Per-slice stack navigation** — `scroll_slices` on the viewer-write adapter
(production-registered): absolute `index`, signed `delta`, or `direction`
next/previous/first/last; clamps to the stack and calls the wheel path's own
`set_slice`. Parser maps "scroll/stack this series", "next/previous slice",
"scroll to the last image" (+ Persian) with direction detection.

**Module-context tracking** — `state["last_module"]` now records the last
module opened (open_module/toggle_eagle/open_mpr/… and the report actions) for
future follow-up references.

**Parser fast paths** added for all five commands (send → transcribe →
generate → start ordering so "transcribe this voice report" wins); "open the
report module" still resolves to the printing module, not `start_report`.

## Still deliberately NOT voice-automated

- The reception dialog inside `send_report_to_pacs` (clinical human gate — by design).
- `close_patient_tab` (destructive; test-server only).
- Brain catalog reconciliation (cosmetic — the validator now accepts what the
  brain plans, so the dry-run mismatch is moot on the voice path).

## Safety

- Additive only: every pre-existing action takes the exact same code path.
- `AIPACS_SECRETARY_BUS=0` disables the bridge wholesale.
- Bus adapters keep their typed, recoverable error envelopes (e.g.
  `MODULE_NOT_REGISTERED`, `MISSING_MODULE`); a launcher failure can't crash the app.
- Destructive `close_patient_tab` remains unreachable by voice.

## Verification

| Check | Result |
|---|---|
| `tests/code/echomind/test_secretary_bus_bridge.py` (21 = 13 phase-1 + 8 phase-2: confirm gate fires-then-executes, reporting/scroll parser paths, echomind adapter typed errors, scroll clamping via fake viewer, module-context tracking, report-module-vs-start_report precedence, registration) | **21/21 passed** |
| Full `tests/code/echomind` regression | **102 passed** |
| `modules/EchoMind/secretary/tests` (legacy validator/parser suites) | **8 passed** (the `-p no:debugging` failures there are the known pre-existing unittest/option quirk — they pass without the flag) |
| `py_compile` all 7 edited files | OK |
| `tools/dev/verify_plugin_mirrors.py` (secretary files + new adapter re-synced to echomind payload) | **290/290** |

## Live QA checklist (next launch)

1. Say/type "open mpr" with a patient tab open → MPR opens (same as the toolbar button); without a tab → polite MODULE_LAUNCH_FAILED message, no crash.
2. "open echomind" → chat window for the active patient.
3. "open eagle eye" → Eagle Eye window.
4. "show today's MRI patients" → unchanged behavior (regression check).
5. "open patient <id>" → still asks confirm → opens (regression check).
6. After "open mpr", say "download this patient" → must still target the previously-opened PATIENT (context-poisoning guard).
7. **Phase 2:** with a patient open: "start a report" → EchoMind report page (newest voice file auto-attached if present); "transcribe this voice report" → file loaded on the Transcribe tab (or a clear "no recording" message); "generate the report" → same as pressing Send; "send the report to PACS" → Secretary asks to confirm → "yes" → the reception dialog appears pre-filled with the current patient.
8. **Phase 2:** with a series loaded: "scroll through this series" / "next slice" / "previous slice" / "scroll to the last image" → the stack moves exactly like wheel scrolling.
