# EchoMind Secretary — LLM Command System Implementation Plan

**Date:** 2026-02-20  
**Scope:** LLM NLP→JSON command generation + internal JSON validation/execution + error feedback loop

---

## 1) Goal (what we are building)

We need a **two-part command system**:

1. **LLM Brain (NLP → JSON)**
   - Converts user natural language into a strict JSON command.

2. **Internal Commander (JSON → Action)**
   - Validates JSON against software structure and runtime constraints.
   - Executes mapped action in PACS UI/backend.
   - Returns structured success/error.
   - If invalid, returns machine-readable errors that can be re-sent to LLM for correction.

This is exactly aligned with your requested flow:

- User request → LLM JSON
- Internal validate
- Execute if valid
- If invalid → error to LLM → corrected JSON

---

## 2) What already exists in the codebase (important)

From current `EchoMind/secretary` implementation:

- `contracts.py`
  - Already defines typed structures:
    - `SecretaryCommand`
    - `SecretaryActionPlan`
    - `SecretaryResult`

- `parser_rules.py`
  - Rule parser for EN/FA intents.

- `parser_llm.py`
  - LLM fallback parser (currently calls GapGPT API and tries to parse JSON).

- `orchestrator.py`
  - Existing commander-like runtime:
    - parse,
    - pending selection/confirmation state,
    - execute,
    - audit logging.

- `executor.py`
  - Action executor for:
    - `list_patients`
    - `open_patient`
    - `download_patient`

- `adapters/home_widget_adapter.py`
  - Binds execution to PACS `HomePanelWidget` methods.

- `audit.py` + `database.py`
  - Persist command lifecycle into `ai_secretary_actions`.

✅ **Conclusion:** Core architecture already exists. We do **not** need to start from zero; we need to harden and formalize.

---

## 3) Required canonical JSON protocol (new standard)

Current structures are close, but we should formalize a **single canonical schema** for LLM output.

## 3.1 LLM output schema (proposal v1)

```json
{
  "action": "list_patients | open_patient | download_patient",
  "entities": {
    "source": "active_tab | local | server",
    "date": "today | yyyy-mm-dd | yyyy-mm-dd..yyyy-mm-dd",
    "modality": "MR | CT | US | ...",
    "patient_code": "string",
    "use_context_patient": true
  },
  "confidence": 0.0,
  "needs_confirmation": false,
  "reason": "short explanation"
}
```

Notes:
- Keep `entities` open, but validate allowed keys per action.
- `confidence` should be float in `[0,1]`.
- `needs_confirmation` must be enforced by internal logic for side-effect actions.

## 3.2 Internal normalized command (post-validation)

After validation, commander should build a normalized structure:

```json
{
  "action": "list_patients",
  "entities": {...},
  "meta": {
    "source_scope": "active_tab",
    "language": "auto",
    "sid": "secretary-session-id",
    "stt_route_requested": "native",
    "stt_route_used": "native"
  }
}
```

This prevents executor from relying on raw LLM payload shape.

---

## 4) Internal commander responsibilities (strict split)

The commander (currently `orchestrator.py`) should explicitly own:

1. **Plan intake**
   - from rules parser OR LLM parser.

2. **Schema validation**
   - required fields,
   - type checks,
   - allowed action names,
   - allowed entity keys per action.

3. **Business validation**
   - side-effect action requires confirmation.
   - missing required entities for action.
   - source scope constraints.

4. **Execution dispatch**
   - call executor only when validation succeeds.

5. **Error feedback object generation**
   - return structured errors that can be used as LLM repair prompt.

6. **Session/pending state machine**
   - `choose` and `confirm` loops (already present).

7. **Audit logging**
   - start/end records with latency and result.

---

## 5) JSON validation model (what to add)

Add a dedicated validator module:

- **New file proposal:** `EchoMind/secretary/validator.py`

Functions:
- `validate_plan_shape(plan) -> list[ValidationError]`
- `validate_plan_semantics(plan) -> list[ValidationError]`
- `normalize_plan(plan, cmd_meta) -> NormalizedPlan`

ValidationError model:

```json
{
  "code": "INVALID_ACTION | MISSING_FIELD | INVALID_TYPE | INVALID_ENTITY | ...",
  "field": "entities.date",
  "message": "Expected yyyy-mm-dd or 'today'",
  "hint": "Use date='today' for today's patients"
}
```

If errors exist:
- commander returns `error_code="PLAN_VALIDATION_FAILED"`
- includes `validation_errors` in `data`.

---

## 6) Error feedback loop to LLM (required by your spec)

## 6.1 Loop behavior

When invalid plan is detected:

1. Commander returns structured errors.
2. LLM repair prompt receives:
   - original user request,
   - invalid JSON,
   - validation error list,
   - allowed schema/action docs.
3. LLM returns corrected JSON.
4. Commander re-validates.
5. Max retries (e.g., 2-3) then fail safe.

## 6.2 New module proposal

- **New file:** `EchoMind/secretary/repair_loop.py`
- Functions:
  - `build_repair_prompt(...)`
  - `retry_plan_with_llm(...)`

The loop should be optional and controlled by config flag.

---

## 7) What the LLM must know (preface/context package)

Per your request, this is the exact context payload the LLM needs.

## 7.1 Mandatory preface blocks

1. **Action registry**
   - allowed actions and brief descriptions.

2. **Entity schema by action**
   - allowed fields + types + examples.

3. **Confirmation policy**
   - `open_patient`, `download_patient` always confirmation-required.

4. **Source model**
   - `active_tab`, `local`, `server` meaning.

5. **Date/modality normalization rules**
   - e.g., MRI synonyms → `MR`, Persian today → `today`.

6. **Strict output contract**
   - JSON only, no markdown, no prose.

## 7.2 Context source of truth in code

Use these files as preface generation source:

- `module_map.yaml`
- `contracts.py`
- parser constraints in `parser_rules.py`
- adapter capability in `home_widget_adapter.py`

## 7.3 Recommended implementation

- **New file:** `EchoMind/secretary/prompt_context.py`
- Build prompt context dynamically from source files/constant definitions.

This avoids drift between implementation and prompt docs.

---

## 8) Execution mapping (JSON → software actions)

Current mapping is already valid and should remain the base:

- `list_patients`
  - adapter: `search(...)`, `list_rows()`

- `open_patient`
  - resolver: code → candidate
  - adapter: `open_patient(...)`

- `download_patient`
  - resolver/context candidate
  - adapter: `download_studies([...])`

Commander should remain responsible for non-execution logic (state/validation/repair).

---

## 9) Exact implementation work required

## Phase A — Protocol hardening (must do first)

1. Add `validator.py`.
2. Add error taxonomy constants (`errors.py`).
3. Update `orchestrator.py` to call validator before executor.
4. Extend `SecretaryResult.data` with validation payload on failures.

## Phase B — LLM command quality + repair loop

5. Refactor `parser_llm.py` to use:
   - generated context package,
   - strict schema post-check,
   - consistent parsing fallback.
6. Add `repair_loop.py` for invalid JSON correction retries.

## Phase C — Prompt context management

7. Add `prompt_context.py` to produce preface from current software structure.
8. Replace static-only prompt assumptions with dynamic capability rendering.

## Phase D — Reliability and observability

9. Log validation failures in audit table with clear error codes.
10. Add metrics counters:
   - parse success rate,
   - validation fail rate,
   - repair success rate,
   - execution success rate.

## Phase E — Tests

11. Unit tests:
   - parser_rules
   - validator
   - resolver
   - orchestrator state transitions
12. Integration tests:
   - NLP -> JSON -> validation -> execution for all actions.

---

## 10) Recommended files to create/modify

### New files
- `EchoMind/secretary/validator.py`
- `EchoMind/secretary/errors.py`
- `EchoMind/secretary/repair_loop.py`
- `EchoMind/secretary/prompt_context.py`
- `EchoMind/secretary/tests/test_validator.py`
- `EchoMind/secretary/tests/test_orchestrator_flow.py`

### Existing files to update
- `EchoMind/secretary/orchestrator.py`
- `EchoMind/secretary/parser_llm.py`
- `EchoMind/secretary/contracts.py` (optional: extend result payload typing)
- `EchoMind/secretary/prompts/secretary_action_prompt.txt`
- `EchoMind/secretary/module_map.yaml`

---

## 11) Example validation/feedback cycle

User: “Search today’s patients”

1) LLM output:

```json
{
  "action": "list_patients",
  "entities": {"date": "today"},
  "confidence": 0.92,
  "needs_confirmation": false,
  "reason": "User asked for today's patients"
}
```

2) Commander validation: ✅

3) Executor runs adapter search/list. Returns rows.

---

If LLM outputs invalid JSON:

```json
{
  "action": "search_patient"
}
```

Commander returns:

```json
{
  "ok": false,
  "action": "unknown",
  "error_code": "PLAN_VALIDATION_FAILED",
  "data": {
    "validation_errors": [
      {
        "code": "INVALID_ACTION",
        "field": "action",
        "message": "Allowed: list_patients, open_patient, download_patient",
        "hint": "Use action='list_patients' for search requests"
      }
    ]
  }
}
```

Then repair-loop asks LLM to regenerate valid JSON.

---

## 12) Final answer to your requested items

### 12.1 What info must be provided to LLM as preface/context?

- Action registry + semantics.
- Strict JSON schema with allowed keys/types.
- Entity constraints by action.
- Confirmation policy.
- Source/tab model.
- Date/modality normalization rules.
- Examples (valid + invalid + corrected).
- Output-only-JSON requirement.

### 12.2 What internal work is required overall?

- Formal validator layer.
- Structured error taxonomy.
- LLM repair feedback loop.
- Prompt-context generator from software structure.
- Orchestrator integration with validation+repair.
- Expanded tests and metrics.

### 12.3 What is the implementation status today?

- Core architecture exists and is usable.
- Missing pieces are mainly:
  - strict formal validation layer,
  - standardized error-to-LLM repair loop,
  - dynamic context generation to avoid prompt/implementation drift.

This plan is the blueprint to complete those pieces.
