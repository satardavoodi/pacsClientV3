# Secretary EchoMind / "EchoBand" Command Pipeline — End-to-End Review (2026-06-06)

Scope: can the user-command assistant actually control the software end-to-end?
This is a code-truth audit (every claim cites file:line); it does not depend on a
live click-through, because the limiting factors are structural and provable from
the code.

## TL;DR

The assistant works **reliably for home-panel commands** (list / open / download /
select / sort / import / font) and **cannot execute anything else by voice or
text** — module launches, viewer control, report generation, EagleEye, and
send-to-PACS all **fail at the validator**. The richer 24-action **CommandBus**
that *can* do those things exists and is well-built, but it sits on a **separate
execution path** reachable only by the automation/MCP test server
(`AIPACS_TEST_SERVER=1`), not by the voice/text assistant. The two halves were
built in different phases and were never connected.

There is **no widget named "EchoBand."** The user-facing surface is the **EchoMind
Secretary** orb/mic button (`SecretaryOrbButton` in `secretary_button_widget.py`,
brand label "EchoMind Secretary" at :682). "EchoBand" = that mic band, informally.

## The pipeline, as actually wired

```
                 ┌─────────────────────────── VOICE / TEXT PATH (production) ───────────────────────────┐
 user speaks →  SecretaryOrbButton ─ STT (stt/router.py) ─ orchestrator.handle()
                 (secretary_button_widget.py:1715)            │
                                                              ├─ _parse_plan: AgentBrain (use_brain=True,
                                                              │   secretary_bridge.py:16-19) → rule parser
                                                              │   → single-shot LLM → repair loop
                                                              ├─ validate_plan()  ◄── HARD CAP: 9 actions
                                                              │   (validator.py:18-28)
                                                              └─ _run_plan → SecretaryExecutor.execute()
                                                                  (executor.py:288-314) → HomeWidgetAdapter
                                                                  → real HomePanel methods
                 └──────────────────────────────────────────────────────────────────────────────────────┘

                 ┌─────────────────── AUTOMATION / MCP PATH (AIPACS_TEST_SERVER=1 only) ──────────────────┐
 MCP / tests →  test_server.py (QLocalServer) → CommandBus.execute()  ◄── 24 actions across 5 adapters
                 (test_server.py:3, :139)         (bus_factory.py:76-158)
                                                   home · download · modules · viewer(read) · system
                 └──────────────────────────────────────────────────────────────────────────────────────┘
```

The orchestrator is constructed with **only `home_widget`** (`secretary_bridge.py:16-19`);
it is never given `dm_widget`, `module_launchers`, or the viewer getters, and it
never calls `build_command_bus`. So the voice path literally has no handle to the
download manager, the module launchers, or the viewer.

### Why "the brain plans it but nothing happens"

`AgentBrain` (`brain/agent.py`) is created with `executor=self.executor` — the same
9-action `SecretaryExecutor` — and its `_IMPLEMENTED_ACTIONS` is the 3 core actions;
the other ~12 it advertises (`open_mpr`, `toggle_eagle`, `generate_report`,
`run_analysis`, `print_series`, …) are **dry-run / unimplemented**. Even if the
brain emits one, `validate_plan` rejects it (`ERR_INVALID_ACTION`) because
`_ALLOWED_ACTIONS` (validator.py:18-28) is exactly:

```
list_patients, open_patient, download_patient, set_source_mode,
import_dicom, select_patient, change_font_size, sort_patients, select_and_download
```

Result for any non-home command: **"Plan validation failed"** or
**"UNSUPPORTED_ACTION"**, then the repair loop tries (and fails) to re-fit it into
the 9 allowed actions.

## Per-command verdicts (the 8 test categories)

Legend: ✅ works by voice · 🟡 partial · ❌ fails by voice · 🔌 works via MCP/bus only · ⛔ missing everywhere

### 1. Patient list  — ✅ WORKS
| Command | Verdict | Evidence |
|---|---|---|
| "Show me today's patient list" | ✅ | rule parser → `list_patients{date:today}` (parser_rules.py:61-87,148); `_list_patients` runs real search (executor.py:68-122) |
| "Show me MRI patients from today" | ✅ | modality `MR` extracted in rules (parser_rules.py:70,153) |
| "Show me CT patients from yesterday" | ✅ (LLM) | rule parser hard-codes only MRI; "CT" resolves via LLM parser (parser_llm allows `list_patients`+modality), validator allows `modality` for list (validator.py:32). Date "yesterday" handled (executor.py:34-36) |

Real call chain: `adapter.search()` → `home.patient_list_function_identifier()` →
the actual home search, then results filtered by date/modality. The list loads.

### 2. Patient open — ✅ / 🟡 (resolves to a real open + tab + thumbnails + download)
| Command | Verdict | Evidence |
|---|---|---|
| "Open the patient with this ID" | 🟡 needs a literal code | no code in text → `MISSING_CODE`, assistant asks for it (executor.py:189-196) |
| "Open patient number X" | ✅ (with confirm) | code extracted (parser_rules.py:12-16); resolve → `CONFIRM_REQUIRED` → "yes" → opens |
| "Open the suggested patient" | 🟡 | works only if a candidate is in session memory/`last_list` (executor.py:124-145, orchestrator memory) |

When it opens, it calls the **real** `_on_patient_double_clicked(...)`
(home_widget_adapter), so the patient tab appears, thumbnails load, and download
starts through the normal path. Open is the assistant's strongest non-trivial
capability. Every open/download requires a **2-turn confirmation** (validator
enforces, validator.py ~:262).

### 3. Viewer (stack / scroll / open image / drag to viewport) — ❌ FAILS by voice
No viewer action exists in `_ALLOWED_ACTIONS` or `SecretaryExecutor`. The bus has
**read-only** viewer actions (`get_active_series`, …, bus_factory.py:143-149) and a
**write** adapter (`viewer_write_adapter.py`: `change_series`, …) that is
**test-mode only** and not registered in production. So "stack/scroll/drag this
series" → validation failure. The real stacking/scrolling/drag still work as manual
UI gestures; the assistant simply cannot drive them. *(Programmatic series-change
exists for the MCP harness only.)*

### 4. Module launch (EchoMind / EagleEye / report / MPR) — ❌ by voice · 🔌 via MCP
The bus implements `open_module`, `toggle_eagle`, `open_mpr`, `open_printing`,
`open_education` (bus_factory.py:124-131) — but the voice path can't reach them.
By voice, "open MPR/EagleEye/report" is either rejected (validator) or, worse,
"open echomind/eagleeye" is **misparsed by the rule parser as `open_patient`** with
no code (parser_rules.py:88-95) → "patient code required." Module launch works
**only** through the aipacs-control MCP / test server.

### 5. EchoMind reporting (open for patient / start report / transcribe / generate) — 🟡 capability exists, NOT command-driven
The EchoMind chat module *does* transcription and report generation through its own
UI + backend (`URL_GEN_TRANSCRIPT`, `URL_GEN_REPORT` in `viewer_chat/ai_chat_pages.py`),
and the audio attachment "Report" button passes patient context via
`open_report_in_echo_mind`. So the **workflow works manually** and the patient
context is passed correctly — but none of it is reachable as a *Secretary command*
("start a report", "transcribe", "generate the report" all fail validation). STT
"transcribe" is a pre-step of command parsing, not an action.

### 6. EagleEye (analyze / open for mammo / load image) — ❌ by voice · 🔌 module-open via MCP
`toggle_eagle` opens the module via the bus; image load + CSV/AI overlay happen
inside the module (the drag-drop path hardened on 2026-06-05). By voice: no action.
There is no parameterized "analyze *this* image" command anywhere — opening the
module is the closest existing capability, and only via MCP.

### 7. PACS send / report — ⛔ MISSING everywhere
There is **no send-to-PACS action** in the validator, the executor, or the bus.
Sending a report exists only inside module UIs; the command layer cannot trigger
it. This is the one capability missing from *every* path.

### 8. Full workflow chain — breaks after step 2
"today's patients" ✅ → "open this patient" ✅ → "load the first series" 🟡 (the
open already shows the first series/thumbnails; there's no series-load *command*) →
"open EchoMind" ❌ → "generate report" ❌ → "send to PACS" ⛔. Patient context is
tracked across turns (session `last_patient`/`last_list` + memory store); **module
context is not tracked** (the assistant has no model of open module windows).

## What's solid (keep)

- The **3–9 home actions execute against real live widgets**, marshalled on the Qt
  main thread (home_widget_adapter pumps `QApplication.processEvents()` while the
  search task runs).
- **Hybrid parse + repair**: rule → LLM → validation-repair (≤2) and
  execution-repair (≤5) (orchestrator.py:25, execution_repair.py).
- **Bilingual** (English + Persian) at the lexical level, incl. Persian digit
  normalization (parser_rules.py).
- **Confirmation gating** on side-effectful actions (open/download) — correct for a
  clinical tool.
- **Logging**: per-command `SessionLog` JSONL at `data/echomind_logs/<date>.jsonl`
  + DB audit (`audit.log_start/finish`) with STT route, intent, entities, latency.
- The **CommandBus itself is well-designed** (24 actions, clean adapters, read-only
  viewer guardrails, main-thread dispatch) — it just isn't wired to voice.

## Pipeline weaknesses (ranked)

1. **W1 — Two disconnected execution paths (root cause).** The voice/text assistant
   is hard-capped at 9 home actions by `validator._ALLOWED_ACTIONS`; the 24-action
   CommandBus is only reachable via `AIPACS_TEST_SERVER`. The assistant therefore
   controls the home panel and nothing else.
2. **W2 — Misleading brain capability.** `AgentBrain` advertises ~15 actions, the
   validator allows 9, the executor implements 9, the brain implements 3; the rest
   dry-run. Users get confident routing then a validation failure.
3. **W3 — No viewer control in the live path** (stack/scroll/series/drag) despite a
   working write adapter that is test-only.
4. **W4 — No report / transcribe / analyze command actions**; those capabilities
   live in module UIs the command layer can't call.
5. **W5 — No module-context tracking**; no notion of which module window is open.
6. **W6 — Rule parser has no module-name awareness**; "open echomind/eagleeye/mpr"
   misparses as `open_patient`.
7. **W7 — Send-to-PACS missing entirely** (no action anywhere).
8. **W8 — Rule coverage gaps**: only MRI hard-coded (CT/US/CR rely on LLM); dates
   limited to today/yesterday/N-days/range.

## Recommended fixes (prioritized, minimal-safe first)

1. **Bridge the orchestrator to the CommandBus (unlocks ~70% of the failing
   commands in one contained change).** Pass `dm_widget`, `module_launchers`, and
   the viewer getters into `create_secretary_orchestrator` (today it passes only
   `home_widget`), have the orchestrator build/hold a `CommandBus`, add the bus
   action names to `_ALLOWED_ACTIONS`, and in `SecretaryExecutor.execute()` route
   any non-home action to `bus.execute(plan)`. This makes "open EchoMind / EagleEye
   / MPR / report module", download pause/resume/cancel, and viewer reads work by
   voice — reusing code that already exists and is main-thread-safe. *Highest value,
   moderate size; I'd do this behind a flag with guard tests.*
2. **Promote the viewer write actions to production (gated, non-destructive):**
   stack/scroll/series-change via the existing `viewer_write_adapter`, so
   "stack/scroll this series" works. Confirm-free, main-thread.
3. **Add `generate_report` / `transcribe` / `open_report` actions** that call the
   EchoMind module backend and pass the tracked patient context.
4. **Add a `send_to_pacs` action** wrapping the module's existing send path — with
   mandatory confirmation (clinical safety).
5. **Teach the rule parser module names** ("open <echomind|eagleeye|mpr|report>" →
   `open_module`) to stop the `open_patient` misparse.
6. **Track module context** in session state once module actions exist.
7. **Reconcile the brain catalog** — implement or remove the advertised-but-dead
   actions so planning stops promising what it can't do.

## Verdict

As a **PACS home-panel controller**, the assistant is functional and reasonably
robust. As the **end-to-end software controller** the prompt envisions — viewer,
modules, reporting, EagleEye, PACS send — it is **not** wired up: those commands are
understood-ish but blocked at the validator, and the capable CommandBus is parked on
the automation path. The good news is that fix #1 is mostly *connection*, not new
capability — the bus, adapters, and main-thread dispatch already exist.

---
*Method: full read of `modules/EchoMind/secretary/**` (orchestrator, executor,
validator, parser_rules/llm, brain, adapters, bus_factory, command_bus, test_server,
secretary_bridge, session_log, audit) + the UI invocation in
`secretary_button_widget.py` and `home_panel/widget.py`. No files modified.*
