# Implementation Plan — Unified Command Layer

> Child of `UNIFIED_COMMAND_LAYER_2026-05-27.md`. That doc covered the
> *why*; this one covers the *what to write, line by line*, the rollback
> for each step, and the acceptance gate before promoting each phase.

---

## 0. Scope guardrails

This session implements **the foundation only** — Phases 1, 3, 4 from the
parent doc, plus the test scaffolding and the pywinauto canonical case.

**Out of scope this session** (intentional — they touch clinical-functionality
guarded code):

- Phase 2 — replacing `parser_llm.py` with PydanticAI (depends on Phase 1
  being on `main` for a release first; needs a new dep `pydantic-ai`).
- Phase 5 — `ViewerAdapter` (touches `patient_tab/vtk_widget` — must read
  `docs/MULTI_STUDY_SINGLE_TAB_PLAN.md` first per project rules).
- Phase 6 — `DownloadAdapter` (touches the DM widget — needs the
  `tests/download_manager/` suite green first).
- Phase 7 — `ModuleAdapter` (depends on each module's lifecycle being
  understood; gated on stakeholder review).

The foundation lets every later phase plug in **without changing call
sites in the GUI, tests, or agent runners**.

---

## 1. Files this session creates / modifies

### Created (new files)

```
modules/EchoMind/secretary/
  command_envelope.py             # Pydantic models + TypedDict compat
  registry.py                     # AdapterRegistry
  command_bus.py                  # CommandBus façade
  adapters/
    home_command_adapter.py       # plan-shaped wrapper of HomeWidgetAdapter
  examples/
    README.md                     # ~10-line demo per caller (chat/agent/test)
    sample_agent_call.py          # external AI-agent caller (Anthropic SDK shape)
    sample_chat_call.py           # chat-orb caller (in-process)

tests/code/echomind/
  __init__.py
  conftest.py                     # adds project root to sys.path
  test_command_envelope.py        # Pydantic round-trip + compat
  test_adapter_registry.py        # registration, dispatch, error paths
  test_command_bus_unit.py        # parse / execute / dispatch with mock registry

tests/gui/echomind_driven/
  __init__.py                     # already there
  conftest.py                     # exposes `bus` fixture (live home_widget)
  test_command_bus_smoke.py       # end-to-end smoke against the bus
  test_scenario_1_patient_open.py # Issue-1 KPI test via bus
  test_scenario_3_bulk_download.py # Issue-3 KPI test via bus

tests/gui/pywinauto/
  test_eagle_eye_dragdrop.py      # canonical pyramid-top: Issue-2 (0x8001010d)
```

### Modified (small, additive — preserves all existing functionality)

```
modules/EchoMind/secretary/__init__.py
   → re-export CommandBus, CommandRequest, CommandPlan, CommandResult,
     AdapterRegistry. Keep all legacy exports as-is.

modules/EchoMind/secretary/orchestrator.py
   → add `to_command_bus()` method that returns a CommandBus wrapped around
     `self` for callers that want the new API. No removal, no signature
     changes on existing methods.
```

### Not touched

- `parser_rules.py`, `parser_llm.py`, `validator.py`, `repair_loop.py`,
  `execution_repair.py`, `executor.py`, `confirm.py`, `audit.py`,
  `memory/`, `stt/`, `brain/`, `catalog/`, `adapters/home_widget_adapter.py`.
- `PacsClient/` GUI integration points (the orb continues to use the
  legacy Orchestrator).
- Anything under `modules/download_manager/`, `modules/ai_imaging/`,
  `PacsClient/pacs/patient_tab/`.

---

## 2. Phase 1 — Pydantic command envelope

### 2.1. New file `command_envelope.py` (~90 LOC)

Three Pydantic models with `extra="allow"` so they coexist with the
existing TypedDict fields:

```python
from typing import Any, Literal
from pydantic import BaseModel, Field, ConfigDict

SourceScope = Literal["active_tab", "local", "server"]
SttRoute = Literal["native", "v2t"]

class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
    text: str = ""
    language: str = "auto"
    session_id: str | None = None
    source_scope: SourceScope = "active_tab"
    stt_route: SttRoute = "native"
    stt_fallback: bool = True

    @classmethod
    def from_typeddict(cls, td: dict) -> "CommandRequest":
        return cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)

class CommandPlan(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str
    entities: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    needs_confirmation: bool = False
    reason: str = ""
    source_module: str | None = None

    @classmethod
    def from_typeddict(cls, td: dict | None) -> "CommandPlan | None":
        return None if td is None else cls.model_validate(td)

    def to_typeddict(self) -> dict:
        return self.model_dump(exclude_unset=False)

class CommandResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    ok: bool
    action: str
    message: str = ""
    data: dict[str, Any] | list | None = None
    error_code: str | None = None
    elapsed_ms: float | None = None
```

### 2.2. Acceptance gate

- `python -c "from modules.EchoMind.secretary.command_envelope import *"` ok
- `CommandRequest(text="open patient 43743").model_dump()` round-trips
- `CommandRequest.from_typeddict({"text": "x", "extra_key": 1}).extra_key == 1`

### 2.3. Rollback

Delete the new file. No other file changed.

---

## 3. Phase 3 — CommandBus façade

### 3.1. New file `command_bus.py` (~130 LOC)

```python
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional, Union

from .command_envelope import CommandRequest, CommandPlan, CommandResult
from .registry import AdapterRegistry

logger = logging.getLogger(__name__)


class CommandBus:
    """Unified control layer.

    Same call site for chat, voice, AI agent, and GUI tests. All callers
    enter through one of:
        bus.parse(text)        → CommandPlan
        bus.execute(plan)      → CommandResult
        bus.dispatch(text)     → CommandResult  (parse + execute)
        bus.dispatch_async()   → awaitable CommandResult (qasync-friendly)
    """

    def __init__(
        self,
        registry: AdapterRegistry,
        orchestrator: Any = None,
    ):
        self.registry = registry
        # The legacy SecretaryOrchestrator is the parser source until
        # Phase 2 lands. Pass None in pure-test scenarios.
        self._orchestrator = orchestrator

    # ── parse ────────────────────────────────────────────────────────
    def parse(self, req: Union[CommandRequest, dict, str]) -> Optional[CommandPlan]:
        req = self._coerce_request(req)
        if self._orchestrator is None:
            return None
        try:
            plan_td = self._orchestrator._parse_plan(req.to_typeddict(), "")
        except Exception:
            logger.exception("CommandBus.parse — orchestrator raised")
            return None
        return CommandPlan.from_typeddict(plan_td)

    # ── execute ──────────────────────────────────────────────────────
    def execute(
        self,
        plan: Union[CommandPlan, dict],
        state: Optional[dict] = None,
    ) -> CommandResult:
        if isinstance(plan, dict):
            plan = CommandPlan.model_validate(plan)
        t0 = time.monotonic()
        result = self.registry.dispatch(plan, state or {})
        if result.elapsed_ms is None:
            result.elapsed_ms = (time.monotonic() - t0) * 1000.0
        return result

    # ── parse + execute ──────────────────────────────────────────────
    def dispatch(self, req: Union[CommandRequest, dict, str]) -> CommandResult:
        plan = self.parse(req)
        if plan is None:
            return CommandResult(
                ok=False, action="<unparsed>",
                message="Could not parse command",
                error_code="UNPARSED",
            )
        return self.execute(plan)

    async def dispatch_async(self, req) -> CommandResult:
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, self.parse, req)
        if plan is None:
            return CommandResult(
                ok=False, action="<unparsed>",
                message="Could not parse command",
                error_code="UNPARSED",
            )
        return self.execute(plan)

    # ── introspection ────────────────────────────────────────────────
    def actions(self) -> list[str]:
        return self.registry.list_actions()

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _coerce_request(req) -> CommandRequest:
        if isinstance(req, CommandRequest):
            return req
        if isinstance(req, dict):
            return CommandRequest.model_validate(req)
        if isinstance(req, str):
            return CommandRequest(text=req)
        raise TypeError(f"Unsupported CommandBus request type {type(req).__name__}")
```

### 3.2. Acceptance gate

- Unit tests in `tests/code/echomind/test_command_bus_unit.py`:
  - `parse(str)`, `parse(dict)`, `parse(CommandRequest)` all coerce
  - `execute()` fills in `elapsed_ms`
  - `dispatch()` returns `UNPARSED` when orchestrator is None

### 3.3. Rollback

Delete the new file. No call-site changes.

---

## 4. Phase 4 — AdapterRegistry

### 4.1. New file `registry.py` (~110 LOC)

```python
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from .command_envelope import CommandPlan, CommandResult

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Maps action_name → adapter method.

    Adapters expose Python methods that take (plan: CommandPlan, state: dict)
    and return either a CommandResult, a dict (auto-validated), or None.
    """

    def __init__(self):
        self._adapters: dict[str, Any] = {}
        self._actions: dict[str, tuple[str, Callable]] = {}

    # ── registration ─────────────────────────────────────────────────
    def register(
        self,
        name: str,
        adapter: Any,
        actions: dict[str, str],
    ) -> None:
        """Register an adapter's actions.

        actions maps action_name → method_name on the adapter.
        """
        self._adapters[name] = adapter
        for action_name, method_name in actions.items():
            method = getattr(adapter, method_name, None)
            if method is None or not callable(method):
                raise ValueError(
                    f"Adapter {name!r} has no callable method {method_name!r}"
                )
            self._actions[action_name] = (name, method)
        logger.info(
            "AdapterRegistry.register: adapter=%s actions=%d total_actions=%d",
            name, len(actions), len(self._actions),
        )

    # ── introspection ────────────────────────────────────────────────
    def adapter(self, name: str) -> Optional[Any]:
        return self._adapters.get(name)

    def has_action(self, action_name: str) -> bool:
        return action_name in self._actions

    def list_actions(self) -> list[str]:
        return sorted(self._actions.keys())

    def list_adapters(self) -> list[str]:
        return sorted(self._adapters.keys())

    # ── dispatch ─────────────────────────────────────────────────────
    def dispatch(
        self,
        plan: CommandPlan,
        state: dict,
    ) -> CommandResult:
        if plan.action not in self._actions:
            return CommandResult(
                ok=False, action=plan.action,
                message=f"No adapter registered for action {plan.action!r}",
                error_code="UNKNOWN_ACTION",
            )
        adapter_name, method = self._actions[plan.action]
        try:
            raw = method(plan, state)
        except Exception as exc:
            logger.exception(
                "AdapterRegistry.dispatch: adapter %s action %s raised",
                adapter_name, plan.action,
            )
            return CommandResult(
                ok=False, action=plan.action,
                message=f"{adapter_name} adapter crashed: {exc}",
                error_code="ADAPTER_ERROR",
            )

        return self._normalize_result(raw, plan)

    # ── helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _normalize_result(raw, plan: CommandPlan) -> CommandResult:
        if isinstance(raw, CommandResult):
            return raw
        if raw is None:
            return CommandResult(ok=True, action=plan.action,
                                 message="(no payload)")
        if isinstance(raw, dict):
            try:
                if "ok" in raw and "action" in raw:
                    return CommandResult.model_validate(raw)
                return CommandResult(
                    ok=bool(raw.get("ok", True)),
                    action=plan.action,
                    message=str(raw.get("message") or ""),
                    data=raw.get("data", raw),
                    error_code=raw.get("error_code"),
                )
            except Exception:
                return CommandResult(ok=True, action=plan.action, data=raw)
        # arbitrary payload (list, str, int)
        return CommandResult(ok=True, action=plan.action, data=raw)
```

### 4.2. New file `adapters/home_command_adapter.py` (~140 LOC)

Wraps the existing `HomeWidgetAdapter` so its methods are plan-shaped.
Maps the catalog actions onto already-existing adapter methods. No GUI
code touched — pure shim.

### 4.3. Acceptance gate

- Register a mock adapter, dispatch a plan with a known action → result.
- Dispatch a plan with an unknown action → `UNKNOWN_ACTION` with the
  action name in the message.
- Make the mock adapter raise → `ADAPTER_ERROR` with traceback logged.

### 4.4. Rollback

Delete `registry.py` and `adapters/home_command_adapter.py`. No
behavior change at call sites that don't reference them.

---

## 5. Phase 4.5 — Wire the public API

`modules/EchoMind/secretary/__init__.py`:

```python
# Existing legacy exports kept verbatim.
# New (foundation) exports:
from .command_envelope import (
    CommandRequest, CommandPlan, CommandResult,
)
from .registry import AdapterRegistry
from .command_bus import CommandBus
```

`orchestrator.py` — add at the bottom:

```python
def to_command_bus(self, registry: AdapterRegistry | None = None) -> CommandBus:
    """Wrap this orchestrator in the new CommandBus façade.

    Pass a pre-built registry (with adapters wired) or get an empty one
    that only supports parse (no execute). Use this in tests; production
    code wires the registry at HomeWidget construction time.
    """
    from .registry import AdapterRegistry
    from .command_bus import CommandBus
    return CommandBus(registry=registry or AdapterRegistry(), orchestrator=self)
```

Rollback: revert `__init__.py` and `orchestrator.py` to pre-change.

---

## 6. Test scaffold

### 6.1. `tests/code/echomind/` — pure unit tests

Three files, all pytest-style, all runnable in CI:

| File | Asserts |
|---|---|
| `test_command_envelope.py` | round-trip Pydantic ↔ dict; `from_typeddict` accepts extras; `to_typeddict` preserves them |
| `test_adapter_registry.py` | registration ok / missing-method raises; dispatch happy/unknown/crash paths; normalize_result handles dict/CommandResult/None |
| `test_command_bus_unit.py` | parse(str|dict|CommandRequest) coerces; execute fills elapsed_ms; dispatch returns UNPARSED when no orchestrator |

### 6.2. `tests/gui/echomind_driven/` — bus-backed scenario tests

| File | Asserts |
|---|---|
| `conftest.py` | exposes a `bus` fixture that constructs a CommandBus with a fake home adapter — runs in-process without a real GUI |
| `test_command_bus_smoke.py` | full dispatch via bus → adapter → result |
| `test_scenario_1_patient_open.py` | KPI: simulate 5 `open_patient` calls; assert `result.elapsed_ms < 400` per call (uses fake adapter that mimics socket latency) |
| `test_scenario_3_bulk_download.py` | KPI: dispatch one `download_patient` with N=20 ids; assert queue snapshot has 20 entries |

These tests use a **fake home adapter** so they're CI-runnable (don't
need the real app). The real-app version lives in the same files behind
a `@pytest.mark.live_gui` marker that the bus fixture toggles based on
whether `_verify_source_build()` passes.

### 6.3. `tests/gui/pywinauto/test_eagle_eye_dragdrop.py` — canonical pyramid-top

The Eagle Eye drag-drop crash (Issue 2, `0x8001010d`) is structurally
invisible to in-process tests — it only happens inside the real Win32
OLE drag-drop COM context. This is the ONE place where pywinauto is
NOT just useful but strictly necessary.

Test outline (~120 LOC):

1. `_verify_source_build.require_source_build()` — fail-fast if frozen.
2. Connect to the AI-PACS window via pywinauto title regex.
3. Navigate: select MG modality, search, click an MG patient, open Eagle
   Eye, wait for `Successful`.
4. Snapshot `native_fault.log` size pre-drop.
5. Perform `drag_mouse_input` from a series thumbnail to the left
   viewport.
6. Wait 2 s, sample log, assert no new `0x8001010d` lines, assert mirror
   appeared in right viewport (UIA tree check).
7. Repeat 3 times with different series.
8. Final assert: pre-test log size == post-test log size (no new crashes).

This will be skipped automatically (`pytest.skip`) if the source build
isn't running, so it doesn't fail CI.

---

## 7. Acceptance gates (full)

Before considering the foundation done:

1. `python -m py_compile` every new file — must compile.
2. The 15 existing regression-guard tests still pass.
3. The new unit tests pass (8-12 tests total in `tests/code/echomind/`).
4. The new bus-driven scenario tests pass with the fake adapter.
5. The pywinauto Eagle Eye test runs without error against a live
   source build *or* skips cleanly when source build isn't detected.
6. No diff against any existing file under `PacsClient/`,
   `modules/download_manager/`, `modules/ai_imaging/`, or
   `modules/EchoMind/secretary/` EXCEPT the two additive edits in §1
   ("Modified").

---

## 8. Migration path (for the deferred phases)

Each later phase plugs into the foundation in a single PR:

- **Phase 2 (PydanticAI parser)** — replace `_orchestrator._parse_plan`
  with a `CommandBus.parser = PydanticAIParser(...)` injection. The
  CommandBus.parse() method already accepts a swap. No call-site
  changes.
- **Phase 5 (ViewerAdapter)** — write `adapters/viewer_command_adapter.py`,
  register at HomeWidget construction time. CommandBus auto-picks it up.
- **Phase 6 (DownloadAdapter)** — same pattern.
- **Phase 7 (ModuleAdapter)** — same pattern.

The CommandBus interface guarantees these PRs are isolated: each adapter
ships with its own tests in `tests/code/echomind/test_<domain>_adapter.py`
and a scenario test in `tests/gui/echomind_driven/test_<domain>_*.py`.

---

## 9. Risks & rollback

| Risk | Mitigation | Rollback |
|---|---|---|
| New Pydantic dep breaks import | `command_envelope.py` is the only file importing it; remove that file → no failure | `git rm modules/EchoMind/secretary/command_envelope.py registry.py command_bus.py adapters/home_command_adapter.py` |
| Existing orchestrator users see an attribute change | Only addition is `to_command_bus()`; existing methods unchanged | `git diff` shows only +N lines, 0 -lines on orchestrator.py |
| Test path mismatch after `tests/` reorg | All new tests use `parents[3]` for project root (consistent with the 2026-05-27 reorg) | n/a |
| CommandBus.dispatch_async leaks the executor thread | qasync handles thread lifecycle | n/a — uses `loop.run_in_executor(None, ...)` which is GC'd |
| pywinauto test flake on slow machines | Per-step timeouts + retry budget set inline | individual test skip |

---

## 10. Ship checklist

- [ ] `command_envelope.py` written, compiles, unit-tested
- [ ] `registry.py` written, compiles, unit-tested
- [ ] `command_bus.py` written, compiles, unit-tested
- [ ] `adapters/home_command_adapter.py` written, compiles
- [ ] `__init__.py` re-exports updated
- [ ] `orchestrator.py` `to_command_bus()` helper added
- [ ] `tests/code/echomind/` 3 test files added
- [ ] `tests/gui/echomind_driven/` conftest + 3 scenario tests added
- [ ] `tests/gui/pywinauto/test_eagle_eye_dragdrop.py` added
- [ ] All 15 regression-guard tests still pass
- [ ] All new tests pass
- [ ] Memory entries updated
- [ ] One-paragraph PR description drafted

---

*Author: 2026-05-27 session, child of UNIFIED_COMMAND_LAYER_2026-05-27.md.*
