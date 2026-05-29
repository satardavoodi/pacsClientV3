# Unified Command Layer — Architecture Plan (2026-05-27)

> **One pipeline serves every caller:** text chat, voice (STT), AI agent,
> GUI tests, future external API. EchoMind Secretary stays as the engine;
> we extract a thin, typed Command-Bus façade on top and add adapters that
> cover everything beyond the home widget.

---

## 1. The problem

AI-PACS has three caller types today, each touching the GUI from a different
direction:

| Caller             | Today's path                                       | Pain                                              |
|--------------------|----------------------------------------------------|---------------------------------------------------|
| User text/voice    | Secretary orb → Secretary orchestrator → adapter   | Limited to `home_widget` actions                  |
| AI agent (chat)    | (none)                                             | Can only operate via OS-level computer-use clicks |
| GUI tests          | pywinauto / computer-use MCP                       | Slow, brittle, can't bypass UI                    |

Every caller eventually wants the same thing — "open the MRI patients from
yesterday and start downloading the first five" — but they each speak a
different dialect. Three pipelines → three sets of bugs.

## 2. The decision in one paragraph

**Keep EchoMind Secretary as the engine** (parser → validator → executor →
adapter), but expose it as a generic `CommandBus`. Replace `TypedDict`
with **Pydantic** models for runtime-validated command envelopes. Replace
the ad-hoc JSON parser in `parser_llm.py` with **PydanticAI** so the LLM
returns a typed `CommandPlan` directly (with automatic retry on schema
violation). Add **adapters for every domain** (home, viewer, downloads,
modules), not just the home widget. Tests skip the parser entirely and
call `bus.execute(plan)` with a hand-built plan — same path the agent
uses. Keep **qasync** as the asyncio-Qt bridge so commands don't block
the GUI thread. **Don't** add LangGraph — the current two-phase routing
is enough; revisit only if you need multi-step orchestration with cycles.
**Ollama is optional** behind PydanticAI's model adapter — flip it on
when offline / privacy mode is required.

## 3. What EchoMind Secretary already provides

This isn't a rewrite — it's an extraction. The Secretary already has every
component the unified layer needs. The audit:

```
modules/EchoMind/secretary/
├── orchestrator.py        ← entry point: parse → validate → execute
├── parser_rules.py        ← deterministic rule parser
├── parser_llm.py          ← LLM fallback (ad-hoc JSON; replace w/ PydanticAI)
├── validator.py           ← schema check on plan
├── confirm.py             ← yes/no flow for needs_confirmation actions
├── executor.py            ← dispatches plan → adapter method
├── adapters/
│   └── home_widget_adapter.py  ← ~600 LOC, search/open/download on home
├── brain/
│   ├── router.py          ← Phase 1: which module(s) is this about?
│   ├── agent.py           ← Phase 2: produce a typed ModuleActionPlan
│   └── catalog_loader.py  ← loads catalog/modules/*.md per-domain docs
├── catalog/
│   ├── catalog.yaml
│   └── modules/{download,eagle_ai,homepage,mpr_zeta,patient_viewer,
│                printing,advanced_analysis,echomind}.md
├── memory/memory_store.py ← session memory store
├── stt/                   ← voice → text providers (Iran-Nobat, OpenAI, Google)
├── repair_loop.py         ← retry on LLM produces invalid plan
├── execution_repair.py    ← retry on runtime execution error
├── contracts.py           ← TypedDicts: SecretaryCommand, ...ActionPlan, ...Result
└── tests/                 ← parser + executor unit tests
```

What this means: **~80% of the unified layer already exists.** The work is
re-typing the contracts, broadening the adapter surface, and wiring tests.

## 4. Library decisions

Researched via web search (PydanticAI 1.x is GA as of 2026-Q1) plus a
project-code audit:

| Library | Verdict | Why |
|---|---|---|
| **Pydantic** | **Adopt — phase 1** | Replace TypedDict in `contracts.py` with `BaseModel`. Free runtime validation, IDE autocomplete, JSON schema export. Mechanical migration. No dep changes (Pydantic is a transitive dep already in many places). |
| **PydanticAI** | **Adopt — phase 2** | Replaces hand-rolled JSON parsing in `parser_llm.py`. The LLM returns a typed `CommandPlan` directly; framework retries on schema violation, drives multi-model fallback (OpenAI/Anthropic/Ollama) through one interface. Tool/function calling included if we later want the LLM to invoke adapters directly. Add `pydantic-ai` to `requirements-core.txt`. |
| **qasync** | **Keep — already in use** | `requirements.txt` and `requirements-core.txt` already list it. Used by `main.py` for the asyncio↔Qt bridge. The CommandBus exposes `dispatch()` (sync, blocks Qt) and `dispatch_async()` (await-able under qasync). |
| **LangGraph** | **Defer** | Right tool for stateful multi-agent workflows with cycles. Today's Secretary brain (router → planner → executor) is linear and short-lived; LangGraph would be overkill and obscure the simple flow. Revisit if/when we add long-running agentic workflows that span multiple turns and require explicit state graphs. |
| **Ollama** | **Optional backend** | Plug behind PydanticAI's model adapter (`OllamaModel`). Useful for offline / on-premise (clinical) deployments where API calls to OpenAI/Anthropic aren't allowed. Make it a runtime config (`config/llm.yaml: provider: ollama`) — no code changes needed when adopted via PydanticAI. |

## 5. The unified architecture

```
                          CommandRequest  (Pydantic)
                                  ▲
        ┌─────────────┬───────────┴───────────┬──────────────────┐
        │ chat box    │ STT (voice)           │ AI agent SDK     │ pytest / pywinauto
        │ (orb)       │ (Iran-Nobat /         │ (anthropic,      │ (tests/gui/echomind_driven/)
        │             │  OpenAI / Google)     │  openai)         │
        └──────┬──────┴───────────┬───────────┴────────┬─────────┴──────────────┬──────────
               │ raw text         │ raw text           │ pre-built plan         │ pre-built plan
               ▼                  ▼                    ▼                        ▼
                            ┌──────────────────────────────────────────────┐
                            │              CommandBus                       │
                            │                                               │
                            │  text → ParserPipeline → CommandPlan          │
                            │  CommandPlan → Validator → ConfirmationFlow   │
                            │  CommandPlan → Executor → AdapterRegistry     │
                            │                                               │
                            │  Exposes:                                     │
                            │   .parse(text) → CommandPlan                  │
                            │   .execute(plan) → CommandResult              │
                            │   .dispatch(text) → CommandResult             │
                            │   .dispatch_async(text) → awaitable           │
                            │   .catalog → list[ModuleDoc]                  │
                            └────────────────────────┬─────────────────────┘
                                                     │
                                                     ▼
                            ┌──────────────────────────────────────────────┐
                            │           AdapterRegistry                     │
                            │                                               │
                            │  by action_name → adapter.method              │
                            └─┬──────────────┬──────────────┬──────────────┬┘
                              ▼              ▼              ▼              ▼
                        HomeAdapter   ViewerAdapter   DownloadAdapter  ModuleAdapter
                        (search,      (scroll, stack, (enqueue, pause, (open Eagle,
                         filter,      WL, ruler,      cancel, status,  MPR, Print,
                         open click,  ROI, sync,      priority)        Advanced)
                         dbl-click)   layouts)
                              │              │              │              │
                              ▼              ▼              ▼              ▼
                        live home_     live patient_   live DM widget   live module
                        widget,        tab vtk_widget  + state store    main windows
                        patient_table
```

### 5.1. Why this is one pipeline, not three

Compare against the bypass paths today:

| Today | After |
|---|---|
| Chat text → Secretary.orchestrate(text) | Chat text → bus.dispatch(text) |
| Test pywinauto.click_input() at pixel | Test bus.execute(CommandPlan(action="open_patient", ...)) |
| Agent screenshot → click ÷ retry | Agent bus.execute(plan) — returns typed result |
| Voice → STT → Secretary.orchestrate(text) | Voice → STT → bus.dispatch(text) |

Same `execute()` call site. The only thing that changes is whether the
caller has a raw `text` (uses `dispatch`) or a pre-built `CommandPlan`
(uses `execute` directly).

### 5.2. Typed envelopes (Pydantic)

```python
# modules/EchoMind/secretary/contracts.py — phase 1 rewrite
from pydantic import BaseModel, Field
from typing import Any, Literal

class CommandRequest(BaseModel):
    """Untrusted input from chat / voice / agent / test."""
    text: str = ""
    language: str = "auto"
    session_id: str | None = None
    source_scope: Literal["active_tab", "local", "server"] = "active_tab"
    stt_route: Literal["native", "v2t"] = "native"
    stt_fallback: bool = True

class CommandPlan(BaseModel):
    """Validated plan ready for execution."""
    action: str                       # e.g. "open_patient", "scroll_series"
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    needs_confirmation: bool = False
    reason: str = ""
    source_module: str | None = None  # filled by AgentBrain when known

class CommandResult(BaseModel):
    ok: bool
    action: str
    message: str = ""
    data: dict[str, Any] | list[dict[str, Any]] | None = None
    error_code: str | None = None
    elapsed_ms: float | None = None   # NEW — KPI extraction off this field
```

The existing `SecretaryCommand` / `SecretaryActionPlan` / `SecretaryResult`
TypedDicts stay as aliases for one release, then deprecate. Migration is
mechanical (`from_typeddict` / `to_typeddict` helpers ship in the same
PR).

### 5.3. PydanticAI for the LLM parser

```python
# modules/EchoMind/secretary/parser_llm.py — phase 2 rewrite
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.ollama import OllamaModel  # optional
from .contracts import CommandPlan

def make_parser_agent(*, provider: str = "openai", model: str = "gpt-4o-mini"):
    if provider == "ollama":
        m = OllamaModel(model_name=model)
    else:
        m = OpenAIModel(model_name=model)
    return Agent(
        model=m,
        result_type=CommandPlan,         # ← framework enforces this shape
        system_prompt=_LOAD_FROM_CATALOG,  # existing prompt_context.py
        retries=3,                       # auto-retry on schema fail
    )

def parse_command_llm(text: str, *, language: str = "auto") -> CommandPlan | None:
    agent = make_parser_agent()
    try:
        return agent.run_sync(text, language=language).output  # typed!
    except Exception:
        return None
```

The PydanticAI runtime:
- Validates the LLM's JSON response against `CommandPlan` automatically.
- Retries (up to 3 times) when the LLM returns a malformed plan, feeding
  the validation error back into the next prompt — the same job
  `repair_loop.py` does manually today, but with one less moving part.
- Switches models via config: `parser: provider: ollama; model: qwen2.5`.

### 5.4. Adapter registry (the broadening)

Today there's exactly one adapter (`HomeWidgetAdapter`) with three actions
wired (`list_patients`, `open_patient`, `download_patient`). The Brain
catalog already names 12 more across 8 modules. The plan:

```python
# modules/EchoMind/secretary/registry.py — NEW
class AdapterRegistry:
    def __init__(self):
        self._adapters: dict[str, Any] = {}
        self._actions: dict[str, tuple[str, Callable]] = {}  # action → (adapter_name, fn)

    def register(self, name: str, adapter: Any, *, actions: dict[str, Callable]):
        self._adapters[name] = adapter
        for action_name, fn in actions.items():
            self._actions[action_name] = (name, fn)

    def dispatch(self, plan: CommandPlan, state: dict) -> CommandResult:
        if plan.action not in self._actions:
            return CommandResult(ok=False, action=plan.action,
                                 message="Unknown action",
                                 error_code="UNKNOWN_ACTION")
        _, fn = self._actions[plan.action]
        return fn(plan, state)
```

Wire-up in `main.py` (or wherever the home widget is constructed):

```python
registry = AdapterRegistry()
registry.register(
    "home",
    HomeAdapter(home_widget),
    actions={
        "list_patients": adapter.list_patients,
        "open_patient":  adapter.open_patient,
    },
)
registry.register(
    "viewer",
    ViewerAdapter(),               # binds to active patient_tab lazily
    actions={
        "scroll_series":   adapter.scroll_series,
        "stack_images":    adapter.stack_images,
        "set_window_level":adapter.set_window_level,
        "ruler":           adapter.draw_ruler,
        "toggle_sync":     adapter.toggle_sync,
        "set_layout":      adapter.set_layout,
    },
)
registry.register(
    "download",
    DownloadAdapter(),
    actions={
        "download_patient":     adapter.enqueue,
        "check_download_status":adapter.status,
        "pause_download":       adapter.pause,
        "cancel_download":      adapter.cancel,
        "set_priority":         adapter.set_priority,
    },
)
registry.register(
    "modules",
    ModuleAdapter(),               # opens Eagle Eye, MPR, Printing, etc.
    actions={
        "toggle_eagle":     adapter.toggle_eagle,
        "open_mpr":         adapter.open_mpr,
        "print_series":     adapter.print_series,
        "run_analysis":     adapter.run_analysis,
        # ... full list per catalog/modules/*.md
    },
)
```

Each adapter is a thin wrapper around the existing GUI Python objects.
No GUI rewiring; just expose methods.

### 5.5. CommandBus public API

```python
# modules/EchoMind/secretary/command_bus.py — NEW (renamed from orchestrator)
class CommandBus:
    def __init__(self, registry: AdapterRegistry, *, llm_fallback=True, use_brain=True):
        self.registry = registry
        self.parser_rules = parse_command_rule
        self.parser_llm = parse_command_llm if llm_fallback else None
        self.brain = AgentBrain(...) if use_brain else None
        self.validator = validate_plan
        self.repair = retry_plan_with_llm

    def parse(self, req: CommandRequest) -> CommandPlan | None: ...
    def execute(self, plan: CommandPlan, state: dict | None = None) -> CommandResult: ...
    def dispatch(self, req: CommandRequest) -> CommandResult:
        plan = self.parse(req)
        if plan is None:
            return CommandResult(ok=False, action="<unparsed>",
                                 message="Could not understand command")
        return self.execute(plan, state=self._state_for(req.session_id))

    async def dispatch_async(self, req: CommandRequest) -> CommandResult:
        """qasync-aware. Runs parse off the Qt thread; execute on it."""
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, self.parse, req)
        if plan is None:
            return CommandResult(...)
        return self.execute(plan, state=self._state_for(req.session_id))
```

## 6. How each caller uses it

### 6.1. User text (chat orb)

```python
# PacsClient/.../secretary_orb_widget.py
async def on_send_clicked(self, text: str):
    result = await self.bus.dispatch_async(
        CommandRequest(text=text, language=self._lang, source_scope="server",
                       session_id=self._session_id)
    )
    self._render_result(result)
```

### 6.2. Voice

```python
# modules/EchoMind/secretary/stt/router.py — unchanged; just calls bus
async def on_voice_blob(self, audio_bytes):
    text = await self._stt_provider.transcribe(audio_bytes)
    result = await self.bus.dispatch_async(
        CommandRequest(text=text, language=self._lang, stt_route=self._route)
    )
```

### 6.3. AI agent (Anthropic / OpenAI SDK)

The agent already speaks Pydantic. Give it `CommandPlan` as the tool
schema and let it call `bus.execute()` directly — bypassing the parser
since the agent already knows the structured shape it wants:

```python
# Some external orchestration script
plan = CommandPlan(action="open_patient",
                   entities={"patient_id": "43743", "modality": "MR"})
result = bus.execute(plan)
```

### 6.4. GUI tests (the unified test driver)

```python
# tests/gui/echomind_driven/test_scenario_2_bulk_download.py
def test_bulk_download_queue_populates_under_3s(bus):
    plan = CommandPlan(
        action="download_patient",
        entities={"patient_ids": [f"4365{i}" for i in range(20)],
                  "modality": "MR", "date": "yesterday"},
    )
    t0 = time.monotonic()
    result = bus.execute(plan)
    elapsed = (time.monotonic() - t0) * 1000

    assert result.ok, result.message
    assert result.data["queue_size"] == 20
    assert elapsed < 3000, f"queue took {elapsed:.0f}ms (>3s threshold)"
    assert result.elapsed_ms is not None  # bus fills this in
```

No clicks. No screenshots. No pixel coordinates. Same `bus.execute()`
path the production GUI uses, so a regression in `home_widget` shows
up here.

### 6.5. Future: external API (FastAPI)

```python
# (sketch) PacsClient/api/server.py
@app.post("/v1/commands")
def http_dispatch(req: CommandRequest) -> CommandResult:
    return bus.dispatch(req)
```

`CommandRequest` and `CommandResult` are already Pydantic — FastAPI
automatically validates input and serializes output. Zero glue.

## 7. Migration plan (phased, each phase ships independently)

| Phase | Scope | Risk | Effort |
|---|---|---|---|
| **0. Now** (no code change) | Decide. Land this doc in `docs/plans/`. Build buy-in. | 0 | 0 |
| **1. Typed envelopes** | `contracts.py` → Pydantic. Compat shims kept. `requirements-core.txt`: add `pydantic>=2.0`. | Low — TypedDict→BaseModel is mechanical. | 1 day |
| **2. PydanticAI parser** | `parser_llm.py` → PydanticAI agent. Drop `repair_loop.py` (PydanticAI does it internally). | Medium — exercise with all 8 module catalogs. | 2 days |
| **3. CommandBus façade** | Rename `Orchestrator` → `CommandBus`. Public API per §5.5. Old name as alias for one release. | Low | 0.5 day |
| **4. Adapter registry** | New `registry.py`. Migrate `HomeWidgetAdapter` to register. | Low | 0.5 day |
| **5. ViewerAdapter** | New. Wraps `patient_tab.vtk_widget` and toolbar manager. | Medium — touches the viewer that the project explicitly guards. Read `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` before touching. | 2 days |
| **6. DownloadAdapter** | New. Wraps `modules.download_manager.ui.widget`. | Low — DM is well-isolated. | 1 day |
| **7. ModuleAdapter** | New. Opens Eagle Eye / MPR / Printing on demand. | Low | 1 day |
| **8. Test integration** | `tests/gui/echomind_driven/conftest.py` exposes a `bus` fixture. Migrate the 2026-05-27 scenarios to use it. | Low | 1 day |
| **9. (Optional) Ollama** | Config flag, no code path change. Just `provider: ollama` in `config/llm.yaml`. | Low | 0.5 day |

**Total uncertain effort: ~9.5 days for a complete migration.** Phases 1–4
can ship in one PR (no behavior change visible to users) and unlock all
the rest.

## 8. CommandBus vs pywinauto — pyramid layering

CommandBus is the in-process driver. pywinauto is the external one.
They're **complementary, not competitive** — each catches a class of bug
the other can't.



**pywinauto catches** what CommandBus structurally can't:
button labels and accessible names, drag-drop COM-context bugs
(e.g. the Eagle Eye 0x8001010d crash — that one is **only** observable
via real Win32 OLE drag-drop, not via a direct method call), VTK paint
regressions, layout collapse on resize, keyboard shortcut bindings,
modal dialogs blocking input.

**CommandBus catches** what pywinauto structurally can't:
typed result data (queue size, elapsed_ms, status), concurrent state
races, dedup correctness, adapter API contract drift, internal state
machine transitions.

**Applied to our 2026-05-27 fixes:**

| Fix | Best test driver | Why |
|---|---|---|
| Issue 1 — GetStudyInfo probe stall | CommandBus | Need precise per-call `elapsed_ms` + parallel concurrent opens |
| Issue 2 — Eagle Eye drag-drop crash | **pywinauto only** | Bug lives in the real OLE drag-drop COM state — invisible to in-process calls |
| Issue 3 — bulk Download queue speed | CommandBus | Need typed `result.data[queue_size]` + precise timing |

So pywinauto **stays in the architecture as the top GUI-smoke layer**:
the existing `tests/gui/pywinauto/run_patient_open_smoke.py` + the
`_verify_source_build.py` pre-flight + a planned
`tests/gui/pywinauto/test_eagle_eye_dragdrop.py` (canonical use case)
all live above CommandBus, not below it.

## 9. What we explicitly do NOT do

- **No LangGraph.** The Brain router/planner is already two phases linear.
  LangGraph wins on stateful cyclical workflows; we don't have those.
- **No replacing qasync.** It already does the asyncio↔Qt bridge we need.
- **No rewriting STT.** The STT router stays; it just hands `text` to
  the bus.
- **No removing pywinauto.** It owns the top GUI-smoke layer of the
  pyramid (drag-drop, paint, modal dialogs) — see §8.
- **No removing computer-use MCP support.** Live walkthroughs still have
  value for ad-hoc workflows where no adapter exists yet. They become
  the *ad-hoc* tool, not part of the CI test suite.

## 10. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Adapter methods drift from the actual GUI widgets they wrap. | Unit tests in `tests/code/<adapter>/` that mock the widget and assert the method call shape. |
| LLM returns a `CommandPlan` for an action no adapter has registered. | `AdapterRegistry.dispatch` returns `error_code=UNKNOWN_ACTION` — the orchestrator's existing repair loop already handles this. |
| PydanticAI breaking changes between minor versions. | Pin `pydantic-ai==1.x.x` until a major-version review. PydanticAI is GA as of 2026-Q1. |
| Test-driven `bus.execute(plan)` bypasses the parser, so a parser regression goes unnoticed by tests. | Keep a tier of tests under `tests/code/echomind/` that exercise `bus.dispatch(text)` (full pipeline) with deterministic rule-parser inputs. |

## 11. Decision summary

1. **Adopt** Pydantic and PydanticAI.
2. **Extract** `CommandBus` as the unified façade in front of EchoMind.
3. **Broaden** adapters to cover viewer, downloads, and modules — not just home.
4. **Wire** *scenario* GUI tests at the `bus.execute(plan)` level (race
   conditions, state, timing) — same call site as the live app.
5. **Keep pywinauto** as the top GUI-smoke layer (drag-drop, paint,
   modal dialogs, accessibility names). The Eagle Eye 0x8001010d crash
   is the canonical pywinauto-only test case.
6. **Defer** LangGraph until a stateful multi-agent workflow appears.
7. **Keep** qasync; Ollama is an optional backend.
8. **Keep** computer-use MCP for ad-hoc walkthroughs / new-scenario discovery.

The end state: one shared control layer. User commands, AI-agent
commands, and GUI tests all enter through `CommandBus`, validate
through Pydantic, dispatch through `AdapterRegistry`, and return a
typed `CommandResult`.

---

*Author: 2026-05-27 session. Sources: PydanticAI 1.x docs, LangGraph 2026
comparisons, internal `modules/EchoMind/secretary/` audit.*
