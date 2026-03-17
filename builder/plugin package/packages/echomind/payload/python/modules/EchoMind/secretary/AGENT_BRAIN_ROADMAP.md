# AIPacs Agent Brain — Roadmap & Pipeline Reference
**Version:** 1.0  |  **Date:** 2026-02-20  |  **Status:** Active Development

---

## 1. Overview and Goal

The AIPacs workstation is evolving from a *command-driven secretary*  
(one fixed action per utterance) into a **multi-module LLM agent brain**  
that can understand complex user intents, decide which workstation modules  
to activate, and produce executable action plans.

The key insight is:

> The LLM does not need to know everything up front.  
> It first chooses **which documents to read**, then **what to do**.

This two-phase design keeps individual prompts small, focused, and  
maintainable — one catalog document + one or two module documents per request.

---

## 2. Architecture: The Two-Phase Pipeline

```
 ┌─────────────────────────────────────────────────────────────────────────┐
 │                       User Input (text or voice)                        │
 └───────────────────────────────────┬─────────────────────────────────────┘
                                     │
                             ┌───────▼────────┐
                             │ SecretaryOrchestrator │
                             │  use_brain=True │
                             └───────┬────────┘
                                     │
              ╔══════════════════════╪══════════════════════╗
              ║         PHASE 1 — Module Routing            ║
              ║                                             ║
              ║  Input sent to LLM:                         ║
              ║  ┌────────────────────────────┐             ║
              ║  │  user_text                 │             ║
              ║  │  + catalog.yaml (Doc 1)    │  ──► LLM   ║
              ║  └────────────────────────────┘             ║
              ║                                             ║
              ║  LLM response:                              ║
              ║  { "modules": ["homepage"], "reason": "…" } ║
              ╚══════════════════════╪══════════════════════╝
                                     │
                             load module docs
                         (catalog/modules/homepage.md)
                                     │
              ╔══════════════════════╪══════════════════════╗
              ║         PHASE 2 — Action Planning            ║
              ║                                             ║
              ║  Input sent to LLM:                         ║
              ║  ┌────────────────────────────┐             ║
              ║  │  user_text                 │             ║
              ║  │  + homepage.md (Doc 2)     │  ──► LLM   ║
              ║  └────────────────────────────┘             ║
              ║                                             ║
              ║  LLM response (JSON):                       ║
              ║  {                                          ║
              ║    "action": "list_patients",               ║
              ║    "entities": { "date": "today" },         ║
              ║    "confidence": 0.95,                      ║
              ║    "needs_confirmation": false,             ║
              ║    "reason": "User asked for today's list"  ║
              ║  }                                          ║
              ╚══════════════════════╪══════════════════════╝
                                     │
                              validate_plan()
                                     │
                              (on failure: repair_loop)
                                     │
                               dispatch() ──► executor method
                                     │
                               SecretaryResult
```

---

## 3. File Structure after This Redesign

```
EchoMind/secretary/
│
├── brain/                          ◄ NEW: two-phase agent brain
│   ├── __init__.py                 # exports AgentBrain, RouteDecision
│   ├── agent.py                    # AgentBrain class (Phase 2 + dispatch)
│   ├── router.py                   # Phase 1: module routing via LLM
│   └── catalog_loader.py           # loads catalog.yaml + per-module .md files
│
├── catalog/                        ◄ NEW: document store
│   ├── catalog.yaml                # Document 1: module catalogue (all modules)
│   └── modules/                    # Document 2: one .md per module
│       ├── homepage.md
│       ├── patient_viewer.md
│       ├── download.md
│       ├── mpr_zeta.md
│       ├── advanced_analysis.md
│       ├── printing.md
│       ├── echomind.md
│       └── eagle_ai.md
│
├── adapters/
│   └── home_widget_adapter.py      # binds HomePanelWidget (unchanged)
│
├── tests/
│   ├── test_validator.py
│   ├── test_parser_and_executor_date.py
│   └── test_orchestrator_repair.py (planned)
│
├── contracts.py          ◄ UPDATED: added AgentRouteRequest/Response, ModuleActionPlan
├── orchestrator.py       ◄ UPDATED: use_brain flag + _get_brain() + _parse_plan() brain path
├── executor.py           # unchanged — handles list/open/download
├── validator.py          # unchanged — validates SecretaryActionPlan schema
├── parser_rules.py       # unchanged — Persian/English rule-based parser
├── parser_llm.py         # unchanged — single-shot LLM fallback parser
├── prompt_context.py     # unchanged — legacy context builder for single-shot LLM
├── repair_loop.py        # unchanged — used as post-Phase-2 repair if validation fails
├── confirm.py            # unchanged — yes/no confirmation handlers
├── audit.py              # unchanged
├── resolver.py           # unchanged
├── errors.py             # unchanged
└── module_map.yaml       # unchanged — original YAML (pre-catalog)
```

---

## 4. Document 1: Module Catalog (`catalog/catalog.yaml`)

Sent with **every** user request in Phase 1.  
It is intentionally short — just module IDs, descriptions, and intent hints.

**Key fields per module entry:**

| Field | Purpose |
|---|---|
| `module_id` | Unique identifier (used to load Doc 2) |
| `display_name` | Human-readable name |
| `description` | 2–3 sentence description for the LLM |
| `typical_intents` | Example user phrases that map to this module |
| `side_effects` | Whether the module can change state (e.g. open, download) |
| `doc_file` | Relative path to the module's Document 2 |

**Current modules in catalog:**

| module_id | category | confirmation needed |
|---|---|---|
| `homepage` | navigation | no |
| `patient_viewer` | viewing | yes |
| `download` | data_transfer | yes |
| `mpr_zeta` | imaging | no (open_mpr) |
| `advanced_analysis` | analysis | no |
| `printing` | output | yes |
| `echomind` | ai_assistant | no |
| `eagle_ai` | ai_assistant | no |

---

## 5. Document 2: Per-Module Docs (`catalog/modules/*.md`)

Each module document tells the LLM **exactly** how to produce a valid JSON  
action plan for that module.  It contains:

1. **What this module does** — plain-language description
2. **Available actions** — name, entity schema table, confirmation policy
3. **Output contract** — exact JSON example with all required fields
4. **Synonym / phrase maps** — Persian ↔ English entity mappings
5. **Example interactions** — input → expected JSON pairs

The LLM reads only the Document 2(s) that Phase 1 selected.

---

## 6. Phase 1 — Module Routing

**File:** `brain/router.py`  
**Class:** -  (module-level function `route_request()`)

```python
from EchoMind.secretary.brain.router import route_request

decision = route_request(user_text="لیست بیماران امروز", language="fa")
# -> RouteDecision(modules=["homepage"], reason="User wants patient list")
```

**LLM System Prompt (Phase 1):**
- Role: "Module Router"
- ONLY job: read catalog + user text → return `{"modules": [...], "reason": "..."}`
- Max 3 modules, temperature 0, max_tokens 256 (very cheap call)

**Fallback:** If Phase 1 returns `modules=[]`, the orchestrator falls back to  
the legacy `parse_command_rule → parse_command_llm → repair_loop` path.

---

## 7. Phase 2 — Action Planning

**File:** `brain/agent.py`  
**Class:** `AgentBrain`

```python
from EchoMind.secretary.brain.agent import AgentBrain

brain = AgentBrain(executor=executor_instance)
plan = brain.plan(user_text="...", language="fa")
result = brain.dispatch(plan)
```

**LLM System Prompt (Phase 2):**
- Role: "Action Planner"
- Input context: one or more module `.md` documents
- Output: exactly one JSON action plan
- Temperature 0, max_tokens 512

**Validation:** After Phase 2, the plan is passed to `validate_plan()`.  
If it fails, `repair_loop.retry_plan_with_llm()` is called once before giving up.

---

## 8. Dispatch Map

The `AgentBrain` maintains a registry of `action → executor_method_name`.

| action | executor method | status |
|---|---|---|
| `list_patients` | `_list_patients` | ✅ implemented |
| `open_patient` | `_open_patient` | ✅ implemented |
| `download_patient` | `_download_patient` | ✅ implemented |
| `open_mpr` | `_open_mpr` | 🔲 stub (returns plan only) |
| `apply_preset` | `_apply_preset` | 🔲 stub |
| `run_analysis` | `_run_analysis` | 🔲 stub |
| `export_report` | `_export_report` | 🔲 stub |
| `print_series` | `_print_series` | 🔲 stub |
| `generate_summary` | `_generate_summary` | 🔲 stub |
| `toggle_eagle` | `_toggle_eagle` | 🔲 stub |

Stub actions return the validated plan dict as `data` in `SecretaryResult`  
so the calling UI can inspect them during development.

---

## 9. Enabling the Brain

### Option A — Use brain only
```python
orchestrator = SecretaryOrchestrator(home_widget=widget, use_brain=True)
```

### Option B — Hybrid (brain first, legacy fallback)
```python
# This is the default when use_brain=True.
# On brain failure, falls back to rule+LLM path automatically.
orchestrator = SecretaryOrchestrator(home_widget=widget, use_brain=True, llm_fallback=True)
```

### Option C — Legacy only (current stable behaviour)
```python
orchestrator = SecretaryOrchestrator(home_widget=widget)  # use_brain defaults to False
```

---

## 10. Development Roadmap

### Phase A — Foundation ✅ (this PR)
- [x] `catalog/catalog.yaml` — Document 1 with 8 modules
- [x] `catalog/modules/*.md` — Document 2 for each module
- [x] `brain/catalog_loader.py` — load docs at runtime
- [x] `brain/router.py` — Phase 1 LLM routing
- [x] `brain/agent.py` — Phase 2 LLM planning + dispatch
- [x] `contracts.py` — `AgentRouteRequest/Response`, `ModuleActionPlan`
- [x] `orchestrator.py` — `use_brain` flag, `_get_brain()`, brain-first `_parse_plan()`
- [x] `__init__.py` — export new symbols

### Phase B — Executor stubs → real implementations
- [ ] `executor.py` — add `_open_mpr()` wiring to Zeta MPR tab
- [ ] `executor.py` — add `_run_analysis()` wiring to advanced analysis panel
- [ ] `executor.py` — add `_print_series()` wiring to print dialog
- [ ] `executor.py` — add `_generate_summary()` wiring to EchoMind chat

### Phase C — Conversation memory
- [ ] `brain/memory.py` — short-term session context (last patient, last list, last action)
- [ ] `brain/router.py` — include memory summary in Phase 1 prompt
- [ ] Multi-turn clarification: if `confidence < 0.6`, ask a follow-up question

### Phase D — Voice pipeline integration
- [ ] `v2t.py` → `SecretaryOrchestrator.handle()` STT input path using `AgentBrain`
- [ ] Streaming partial transcript → debounce → brain.plan()

### Phase E — Proactive suggestions
- [ ] `brain/watcher.py` — monitor viewer state changes, proactively suggest actions
- [ ] Integration with Eagle AI findings → trigger EchoMind summarise suggestion

### Phase F — Tests
- [ ] `tests/test_router.py` — mock LLM, assert routing decisions
- [ ] `tests/test_agent_brain.py` — Phase 1+2 integration with mocked HTTP
- [ ] `tests/test_orchestrator_brain_mode.py` — orchestrator with use_brain=True

---

## 11. Design Decisions and Rationale

| Decision | Rationale |
|---|---|
| Two-phase (route then plan) | Keeps each LLM call small; the catalog is tiny compared to all module docs concatenated |
| Separate `.md` files per module | Easy to update without touching Python code; LLM reads markdown naturally |
| `use_brain=False` default | Zero risk to existing stable behaviour; brain is opt-in |
| Lazy-load `AgentBrain` | No import cost when brain is disabled; avoids httpx import at startup |
| Repair loop reused in Phase 2 | Existing battle-tested repair path; not duplicated |
| Dispatch map in agent.py | Single place to register new actions; avoids scattered if/else |
| Stub not error for unimplemented actions | Returns plan dict so UI can show "coming soon" without crashing |

---

## 12. Example End-to-End Flows

### 12.1 "لیست بیماران امروز رو به من نشون بده"

```
Phase 1:
  input   → catalog.yaml + above text
  LLM out → {"modules": ["homepage"], "reason": "User wants today's patient list"}

Phase 2:
  input   → homepage.md + above text
  LLM out → {"action":"list_patients","entities":{"date":"today"},"confidence":0.95,"needs_confirmation":false,"reason":"Today's patient list requested"}

dispatch → executor._list_patients(plan)
result   → SecretaryResult(ok=True, message="Found 12 patient(s) from server.")
```

### 12.2 "باز کردن بیمار P-10042 را تایید کن"

```
Phase 1:
  LLM out → {"modules": ["homepage","patient_viewer"], "reason": "Need to find then open a patient"}

Phase 2 (combined docs):
  LLM out → {"action":"open_patient","entities":{"patient_code":"P-10042"},"needs_confirmation":true,...}

orchestrator detects needs_confirmation=true
  → sends confirmation request to UI
  → user confirms → executor._open_patient(plan)
```

### 12.3 "show me the 3D bone reconstruction"

```
Phase 1:
  LLM out → {"modules": ["mpr_zeta"], "reason": "User wants 3D MPR with bone preset"}

Phase 2:
  LLM out → {"action":"open_mpr","entities":{"layout":"3d","preset":"bone"},"needs_confirmation":false,...}

dispatch → _open_mpr stub (not yet wired)
result   → SecretaryResult(ok=True, message="Plan for 'open_mpr' produced. Executor for this module is not yet wired.", data={"plan":...})
```
