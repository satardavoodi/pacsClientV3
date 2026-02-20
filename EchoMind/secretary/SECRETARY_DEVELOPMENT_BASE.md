# EchoMind Secretary — Development Base Reference

**Last updated:** 2026-02-20  
**Codebase scope reviewed:**
- `EchoMind/*`
- `EchoMind/secretary/*`
- `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`
- `PacsClient/pacs/patient_tab/viewers/secretary_bridge.py`
- `PacsClient/utils/database.py` (Secretary audit parts)
- External API note: `C:\Users\vahid\OneDrive\Desktop\GAPGPT_API_USAGE.md`

---

## 1) Purpose of this document

This document is the **authoritative base** for future Secretary module development.  
It captures:
- current architecture and file responsibilities,
- runtime data flow,
- contracts and action lifecycle,
- LLM/GapGPT integration details,
- known integration gaps and technical debt,
- extension and testing guidance.

---

## 2) High-level architecture

Secretary is split into three major layers:

1. **UI + interaction layer (Home Sidebar Orb)**
   - `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`
   - Records mic input, performs STT, runs orchestration, shows compact log and detailed popup.

2. **Secretary core (domain logic)**
   - `EchoMind/secretary/*`
   - Includes parser(s), orchestrator, executor, resolver, adapter, audit logging.

3. **PACS host integration layer**
   - `EchoMind/secretary/adapters/home_widget_adapter.py`
   - `PacsClient/pacs/patient_tab/viewers/secretary_bridge.py`
   - Bridges Secretary actions to real `HomePanelWidget` operations:
     - patient search,
     - open patient,
     - queue download.

---

## 3) Current file map and responsibilities

## 3.1 Secretary package

- `EchoMind/secretary/contracts.py`
  - Defines typed contracts:
    - `SecretaryCommand`
    - `SecretaryActionPlan`
    - `SecretaryResult`
  - Action set is currently restricted to:
    - `list_patients`
    - `open_patient`
    - `download_patient`

- `EchoMind/secretary/parser_rules.py`
  - Fast deterministic parser (EN + FA keyword/rule based).
  - Handles:
    - list intent + optional date/modality extraction,
    - open intent + patient code extraction,
    - download intent + patient code or context hint.

- `EchoMind/secretary/parser_llm.py`
  - LLM fallback parser (GapGPT chat completions).
  - Uses prompt template + module map to return strict JSON action plan.
  - Requires API key from `EchoMind.settings_store.get_echomind_api_key()`.

- `EchoMind/secretary/prompts/secretary_action_prompt.txt`
  - System prompt template for parser-LLM conversion.
  - Enforces strict JSON and confirmation rules.

- `EchoMind/secretary/module_map.yaml`
  - Action capability declaration consumed by prompt.
  - Documents allowed adapter calls per action.

- `EchoMind/secretary/orchestrator.py`
  - Core runtime coordinator:
    - parse text,
    - enforce pending states,
    - handle confirmation/selection loops,
    - call executor,
    - call audit logging start/end.

- `EchoMind/secretary/executor.py`
  - Executes concrete actions against adapter.
  - Performs candidate resolution + ambiguity handling.
  - Confirmation gate is applied for side-effect actions.

- `EchoMind/secretary/resolver.py`
  - Patient code normalization and matching logic:
    - exact patient id,
    - exact study uid,
    - fallback contains match.

- `EchoMind/secretary/confirm.py`
  - Yes/No and numbered selection parsing (EN + FA).

- `EchoMind/secretary/audit.py`
  - Thin wrapper around DB audit functions.

## 3.2 STT submodule

- `EchoMind/secretary/stt/router.py`
  - Route controller for transcription providers.
  - Primary route (`native`/`v2t`) + optional fallback route.

- `EchoMind/secretary/stt/providers/native_irannobat.py`
  - Calls `EchoMind.ai_chat_config.URL_GEN_TRANSCRIPT` with multipart audio upload.

- `EchoMind/secretary/stt/providers/v2t_google.py`
  - Local pipeline using `speech_recognition` + Google Web Speech API.
  - Persian default (`fa-IR`), chunked transcription.

## 3.3 Integration and host files

- `PacsClient/pacs/patient_tab/viewers/secretary_bridge.py`
  - `create_secretary_orchestrator(...)` factory.
  - `get_runtime_home_widget()` lookup helper.

- `EchoMind/secretary/adapters/home_widget_adapter.py`
  - Maps Secretary actions to `HomePanelWidget` behavior.
  - Handles source tab switching, search payload, modality checkbox sync.

- `PacsClient/pacs/workstation_ui/home_ui/secretary_button_widget.py`
  - **Current active UI entrypoint for Secretary runtime.**
  - Also performs direct GapGPT response generation from transcript.

- `PacsClient/utils/database.py`
  - Persists Secretary action audit in `ai_secretary_actions`.

---

## 4) Runtime flow (as currently implemented)

1. User toggles Orb ON in `SecretaryButtonWidget`.
2. Widget ensures EchoMind login (`APIKeyManager` + saved key).
3. Widget records microphone audio to temp WAV.
4. Widget calls `SttRouter.transcribe_files(...)` using settings route.
5. If transcript exists:
   - logs transcript in UI,
   - sends transcript to GapGPT (direct chat response) for assistant-like text,
   - calls `SecretaryOrchestrator.handle(...)` with structured payload.
6. Orchestrator:
   - parses command (`rules` first, then `llm` fallback if enabled),
   - handles pending confirmation/selection state,
   - executes action via `SecretaryExecutor`,
   - writes start/end audit record.
7. Executor calls `HomeWidgetAdapter` methods to affect PACS UI.
8. Result is rendered in widget log popup/line output.

---

## 5) Command and result contracts

## 5.1 `SecretaryCommand`

Current expected command payload:

- `text`: str
- `language`: str (usually `auto`)
- `session_id`: `str | None`
- `source_scope`: `active_tab | local | server`
- `stt_route`: `native | v2t`
- `stt_fallback`: bool

Note: `SecretaryButtonWidget` currently includes `stt_route_used` too when calling orchestrator; orchestrator reads it opportunistically.

## 5.2 `SecretaryActionPlan`

- `action`: one of 3 allowed actions
- `entities`: dict
- `confidence`: float 0..1
- `needs_confirmation`: bool
- `reason`: parse rationale

## 5.3 `SecretaryResult`

- `ok`: bool
- `action`: str
- `message`: str
- `data`: list|dict|None
- `error_code`: str|None

---

## 6) LLM parsing path and GapGPT integration

## 6.1 GapGPT API contract (from provided markdown)

- Endpoint: `https://api.gapgpt.app/v1/chat/completions`
- Auth: `Authorization: Bearer <API_KEY>`
- Payload: `model` + `messages[]`
- Response: assistant text in `choices[0].message.content`
- Usage: token info under `usage`

## 6.2 How Secretary uses GapGPT now

- In `parser_llm.py`, GapGPT is used for **intent parsing** fallback.
- In `secretary_button_widget.py`, GapGPT is also used for **direct transcript assistant response** (`_send_transcript_to_gapgpt`) before orchestration output.

This means there are currently **two distinct GapGPT touchpoints**:
1. parse-level (structured JSON plan),
2. user-facing chat-level (free-form summary/response).

## 6.3 Model defaults in code

- `parser_llm.py`: `gpt-4.1-mini`
- `secretary_button_widget.py` (transcript assistant): `gpt-4.1-mini`

---

## 7) Settings and authentication behavior

- Settings UI: `PacsClient/pacs/workstation_ui/settings_ui/echomind_settings.py`
  - stores and validates EchoMind key,
  - shows usage summaries,
  - persists Secretary STT model route.

- Persistent store: `EchoMind/settings_store.py`
  - file: `%APPDATA%/PacsClient/config/echomind_settings.json`
  - keys:
    - `api_key`
    - `secretary_stt_provider`
    - `secretary_stt_fallback`

---

## 8) Important current-state findings (very important for next dev)

## 8.1 Integration drift after recent edits

The Secretary backend is present and functional in isolation, but runtime wiring is currently split:

- `secretary_button_widget.py` **does use**:
  - `SttRouter`,
  - `create_secretary_orchestrator`,
  - settings-based STT route,
  - orchestrator handle flow.

- `EchoMind/ai_chat_pages.py` currently appears reverted to older mode picker behavior:
  - modal API key prompt is active again,
  - no Secretary mode branch in `ModePickerPage` and `OneChatPage` in currently reviewed sections.

- `EchoMind/ai_chat_widgets.py` currently appears reverted regarding secretary-specific route controls:
  - no current `get_stt_config`/secretary mode API found in reviewed file,
  - no evident route button state in the current version.

## 8.2 Consequence

Secretary is currently strongest in **Home Sidebar Orb flow**, not in `OneChatPage` mode flow.

For next development, decide explicitly whether Secretary should be:
1. **Home-sidebar-first** (current effective route),
2. **AI-chat-mode-first** (reintegrate into `ModePickerPage`/`OneChatPage`),
3. or both with shared orchestration core.

---

## 9) Database and observability

- Table: `ai_secretary_actions`
  - start record includes: sid, source tab, command text, route requested/used, intent, entities/action payload, confirmation flag.
  - end update includes: confirmed, status, error, result count, latency.

This supports:
- postmortem debugging,
- action analytics,
- latency/error trend analysis.

Recommended next step: add a small in-app audit viewer for this table.

---

## 10) Extension guide for next features

## 10.1 Add a new action (example: `open_latest_study`)

1. Update `contracts.py` (`ActionName` literal).
2. Add parser logic in `parser_rules.py` (+ prompt examples if needed).
3. Update `module_map.yaml` and `secretary_action_prompt.txt`.
4. Add execution branch in `executor.py`.
5. Ensure adapter supports required host calls.
6. Add tests for parse -> execute -> result and confirmation behavior.

## 10.2 Add another STT provider

1. Create provider class under `stt/providers/` with `transcribe_files(...)`.
2. Register provider in `router.py` selection logic.
3. Surface route in settings UI combo if user-selectable.
4. Add fallback policy and error normalization.

## 10.3 Harden LLM parse reliability

- Keep strict JSON contract and fenced JSON extraction.
- Add schema validation and confidence threshold handling.
- Add retry with parser-specific system instruction when JSON fails.

---

## 11) Security and compliance notes

- Current `EchoMind/api_manager.py` contains hardcoded center keys. This is operationally convenient but high-risk.
- Recommended migration:
  - move key material to encrypted server-side registry,
  - keep only center IDs and runtime tokens in client.

- Avoid storing full plaintext command transcript if policy requires minimization.
  - currently `command_text` is logged in audit table.

---

## 12) Known technical debt

1. **UI integration split** between sidebar secretary and chat pages.
2. **Potential duplicate signal bindings / duplicate methods** in larger EchoMind UI files (observed generally in current code style).
3. **Mixed concerns in `secretary_button_widget.py`**:
   - recording, STT, GapGPT response, orchestration, rendering all inside one class.
   - recommend extraction into service classes.
4. **Adapter time-wait polling loop** uses `QApplication.processEvents()` + sleep; workable, but should be converted to explicit async signal completion path where possible.

---

## 13) Suggested roadmap (practical)

Phase 1 (stability):
- freeze and unify one runtime path (sidebar +/or chat mode),
- add automated tests for parser/orchestrator/executor,
- normalize error objects.

Phase 2 (feature growth):
- new actions (context-aware, filtered operations),
- richer entity extraction (date ranges, modality sets, fuzzy names),
- safe multi-step confirmation UX.

Phase 3 (production hardening):
- secure key management refactor,
- audit dashboard,
- metrics and alerting on failure rates.

---

## 14) Quick test checklist for developers

- Authentication
  - saved key valid -> no prompt loops in target flow
  - invalid key -> clear actionable message

- STT
  - native route success
  - v2t route success
  - fallback behavior works as configured

- Parsing
  - rule parser for EN/FA commands
  - LLM parser JSON parse resilience

- Execution
  - list/open/download each path
  - ambiguous candidate -> choose flow
  - confirmation yes/no flow

- Audit
  - start/end rows inserted
  - latency + status + error_code captured

---

## 15) Bottom line

The Secretary core (`EchoMind/secretary`) is structurally solid and modular.  
The biggest next-development priority is **runtime integration unification** (chat-mode vs sidebar-mode) and then incremental expansion of actions and reliability.

This document should be treated as the starting baseline for upcoming refactors and feature additions.
