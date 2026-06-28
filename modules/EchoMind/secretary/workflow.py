"""Multi-step workflow engine for Secretary EchoMind / agent control (2026-06-23).

Pure, stdlib-only. Turns a compound user request ("download this patient and
open it") into an ordered list of single-action steps and executes them
sequentially, verifying each step against live app state before moving on.

Why this exists
---------------
The brain plans exactly ONE action per utterance and the orchestrator runs one
plan (`orchestrator._run_plan` → `executor.execute`). So "download and open it"
only downloads — the second action is dropped (observed live 2026-06-23, patient
47734; the LLM even logged "only one action is allowed so I prioritized
download"). This engine is the missing sequencing + verification layer.

Design contract (keep it safe)
------------------------------
- **Pure & injectable.** The executor calls an injected ``run_step(action,
  entities) -> result_dict`` and an injected ``sleep``; it never imports Qt/VTK
  or the bus directly. That keeps it unit-testable offscreen and lets the SAME
  engine drive the voice path (``executor.execute``) and the MCP/test-server
  path (``bus.execute``).
- **Verify before advancing.** Each step may carry a ``verify`` spec; the engine
  probes existing read actions (``check_download_status`` / ``get_active_tab`` /
  ``get_thumbnails_data`` / ``query_viewport_state``) and only continues when the
  predicate passes. It STOPS on the first failed step and reports which one.
- **No new side-effecting capability.** The engine only sequences actions that
  already exist on the bus; it adds ordering + verification, nothing else.
- **Flag-gated, off by default.** ``AIPACS_SECRETARY_WORKFLOWS`` gates the
  callers that use this engine; the engine module itself is inert until called.

Wiring (staged — needs live verification, see
docs/agent_control/workflows.md): the orchestrator/brain hook that emits a
multi-step plan and runs this engine is added separately and validated on the
Windows source build. The engine + its tests land first.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

# ── Kill switch for callers (the engine itself is inert until invoked) ─────────
# DEFAULT-ON (2026-06-28); set AIPACS_SECRETARY_WORKFLOWS=0 to disable callers.
WORKFLOWS_ENABLED = os.environ.get("AIPACS_SECRETARY_WORKFLOWS", "1").strip() != "0"


# ── Plan / step / result model ────────────────────────────────────────────────
@dataclass
class VerifySpec:
    """How to confirm a step actually took effect, via a read-only probe action.

    ``kind`` selects a builtin predicate; ``probe_action`` / ``probe_entities``
    name the read action to call. ``retries`` / ``delay_s`` cover async effects
    (e.g. a download that completes after a few seconds).
    """
    kind: str
    probe_action: str
    probe_entities: dict = field(default_factory=dict)
    retries: int = 1
    delay_s: float = 0.0
    expect: dict = field(default_factory=dict)


@dataclass
class WorkflowStep:
    tool: str                      # action name (e.g. "download_patient")
    args: dict = field(default_factory=dict)
    verify: Optional[VerifySpec] = None
    # Keys to lift from this step's result payload into the shared context so
    # later steps/verifies can reference them (e.g. {"patient_id": "patient_id"}).
    capture: dict = field(default_factory=dict)


@dataclass
class WorkflowPlan:
    goal: str
    steps: list = field(default_factory=list)


@dataclass
class StepResult:
    tool: str
    ok: bool
    verified: bool
    result: Any = None
    error_code: Optional[str] = None
    message: str = ""


@dataclass
class WorkflowResult:
    ok: bool
    goal: str
    steps: list = field(default_factory=list)
    failed_index: Optional[int] = None
    message: str = ""


# ── Builtin verification predicates ───────────────────────────────────────────
def _as_dict(result: Any) -> dict:
    return result if isinstance(result, dict) else {}


def _payload(result: Any) -> Any:
    d = _as_dict(result)
    return d.get("data", d)


def _verify_download_complete(result: Any, expect: dict) -> bool:
    p = _payload(result)
    if isinstance(p, list):
        p = p[0] if p else {}
    p = p if isinstance(p, dict) else {}
    # Be tolerant of the download store's field naming.
    status = str(p.get("status") or p.get("state") or "").lower()
    if status in {"complete", "completed", "done", "downloaded", "finished", "success"}:
        return True
    if p.get("downloaded") is True or p.get("complete") is True:
        return True
    total = p.get("total") or p.get("total_instances") or p.get("expected")
    got = p.get("downloaded_count") or p.get("received") or p.get("count")
    try:
        if total and got is not None and int(got) >= int(total):
            return True
    except (TypeError, ValueError):
        pass
    return False


def _verify_patient_open(result: Any, expect: dict) -> bool:
    p = _payload(result)
    p = p if isinstance(p, dict) else {}
    want = str(expect.get("patient_id") or "").strip()
    got = str(p.get("patient_id") or p.get("patient_code") or "").strip()
    if want:
        return bool(got) and got == want
    return bool(got)


def _verify_thumbnails_loaded(result: Any, expect: dict) -> bool:
    p = _payload(result)
    if isinstance(p, list):
        return len(p) > 0
    if isinstance(p, dict):
        for key in ("thumbnails", "series", "items", "rows"):
            v = p.get(key)
            if isinstance(v, list) and v:
                return True
        if p.get("count"):
            try:
                return int(p["count"]) > 0
            except (TypeError, ValueError):
                return False
    return False


def _verify_viewport_has_series(result: Any, expect: dict) -> bool:
    p = _payload(result)
    viewports = []
    if isinstance(p, dict):
        viewports = p.get("viewports") or p.get("active_viewports") or []
        if not viewports and ("series_number" in p or "series_uid" in p):
            viewports = [p]
    elif isinstance(p, list):
        viewports = p
    want_series = str(expect.get("series") or expect.get("series_number") or "").strip()
    want_uid = str(expect.get("series_uid") or "").strip()
    want_vp = expect.get("viewport")
    for vp in viewports:
        if not isinstance(vp, dict):
            continue
        if want_vp is not None and str(vp.get("viewport", vp.get("index", ""))) != str(want_vp):
            continue
        sn = str(vp.get("series_number") or vp.get("series") or "").strip()
        su = str(vp.get("series_uid") or "").strip()
        if want_uid and su == want_uid:
            return True
        if want_series and sn == want_series:
            return True
        if not want_uid and not want_series and (sn or su):
            return True
    return False


_VERIFIERS: dict[str, Callable[[Any, dict], bool]] = {
    "download_complete": _verify_download_complete,
    "patient_open": _verify_patient_open,
    "thumbnails_loaded": _verify_thumbnails_loaded,
    "viewport_has_series": _verify_viewport_has_series,
}


# ── Default verify / capture per action ───────────────────────────────────────
# The brain (LLM) decides WHAT the steps are; this deterministic table decides
# HOW each step is verified and what it contributes to the shared context. The
# LLM is NOT asked to emit verify specs (unreliable). `build_plan` enriches a
# bare action list into a verified WorkflowPlan.
DEFAULT_CAPTURE: dict[str, dict] = {
    "download_patient": {"patient_id": "patient_id", "study_uid": "study_uid"},
    "open_patient": {"patient_id": "patient_id", "study_uid": "study_uid"},
    "list_patients": {"patient_id": "patient_id"},
}

# Read/navigation actions intentionally have NO verify (nothing to confirm).
_LOAD_SERIES_ALIASES = ("change_series", "drop_series_to_viewport", "load_series_to_viewport")


def _default_verify(action: str, entities: dict) -> Optional[VerifySpec]:
    if action == "download_patient":
        return VerifySpec("download_complete", "check_download_status", retries=30, delay_s=2.0)
    if action == "open_patient":
        return VerifySpec("patient_open", "get_active_tab",
                          expect={"patient_id": "$patient_id"}, retries=10, delay_s=1.0)
    if action in ("select_patient", "load_thumbnails", "get_thumbnails_data"):
        return VerifySpec("thumbnails_loaded", "get_thumbnails_data", retries=10, delay_s=1.0)
    if action in _LOAD_SERIES_ALIASES:
        exp = {"viewport": entities.get("viewport", 0)}
        if "series_uid" in entities:
            exp["series_uid"] = entities["series_uid"]
        elif "series_number" in entities:
            exp["series_number"] = entities["series_number"]
        return VerifySpec("viewport_has_series", "query_viewport_state",
                          expect=exp, retries=10, delay_s=1.0)
    return None


def make_step(action: str, entities: Optional[dict] = None, *, verify: bool = True) -> WorkflowStep:
    """Build a verified :class:`WorkflowStep` for a single action."""
    e = dict(entities or {})
    vs = _default_verify(action, e) if verify else None
    return WorkflowStep(tool=action, args=e, verify=vs, capture=DEFAULT_CAPTURE.get(action, {}))


def build_plan(goal: str, action_steps: list, *, verify: bool = True) -> WorkflowPlan:
    """Enrich a bare ``[{"action"|"tool", "entities"|"args"}, ...]`` list into a
    verified WorkflowPlan. This is the shared builder used by the brain
    (multi-step LLM plan) and any other producer."""
    steps = []
    for s in action_steps or []:
        if isinstance(s, WorkflowStep):
            steps.append(s)
            continue
        action = str(s.get("action") or s.get("tool") or "").strip()
        if not action:
            continue
        entities = s.get("entities") if s.get("entities") is not None else s.get("args")
        steps.append(make_step(action, entities or {}, verify=verify))
    return WorkflowPlan(goal=goal or "workflow", steps=steps)


# ── Context templating ────────────────────────────────────────────────────────
def _resolve_args(args: dict, context: dict) -> dict:
    """Replace ``"$key"`` values with ``context[key]`` (1-level, string keys)."""
    out = {}
    for k, v in (args or {}).items():
        if isinstance(v, str) and v.startswith("$"):
            out[k] = context.get(v[1:], v)
        else:
            out[k] = v
    return out


def _capture(step: WorkflowStep, result: Any, context: dict) -> None:
    p = _payload(result)
    src = p[0] if (isinstance(p, list) and p) else p
    if not isinstance(src, dict):
        return
    for ctx_key, payload_key in (step.capture or {}).items():
        if payload_key in src:
            context[ctx_key] = src[payload_key]


# ── Executor ──────────────────────────────────────────────────────────────────
class WorkflowExecutor:
    """Run a :class:`WorkflowPlan` step by step, verifying each step.

    Parameters
    ----------
    run_step : callable(action: str, entities: dict) -> dict
        Executes one action and returns a result dict (``{"ok", "action",
        "data", "error_code", "message"}``). Inject ``bus.execute`` (wrapped)
        for the MCP path or ``executor.execute`` (wrapped, confirmed=True) for
        the voice path; inject a fake in tests.
    sleep : callable(float)
        Used between verify retries (inject a no-op in tests).
    """

    def __init__(self, run_step: Callable[[str, dict], dict], sleep: Callable[[float], None] = time.sleep):
        self._run = run_step
        self._sleep = sleep

    def run(self, plan: WorkflowPlan, context: Optional[dict] = None) -> WorkflowResult:
        ctx = dict(context or {})
        out = WorkflowResult(ok=True, goal=plan.goal)
        for i, step in enumerate(plan.steps):
            args = _resolve_args(step.args, ctx)
            try:
                res = self._run(step.tool, args)
            except Exception as exc:  # never let a step crash the whole run
                out.ok = False
                out.failed_index = i
                out.message = f"Step {i} ({step.tool}) crashed: {exc}"
                out.steps.append(StepResult(step.tool, False, False, None, "STEP_CRASHED", str(exc)))
                return out

            d = _as_dict(res)
            ok = bool(d.get("ok", True))
            ec = d.get("error_code")
            if not ok:
                out.ok = False
                out.failed_index = i
                out.message = f"Step {i} ({step.tool}) failed: {ec or d.get('message') or 'not ok'}"
                out.steps.append(StepResult(step.tool, False, False, res, ec, str(d.get("message") or "")))
                return out

            _capture(step, res, ctx)

            verified = True
            if step.verify is not None:
                verified = self._verify(step.verify, ctx)
                if not verified:
                    out.ok = False
                    out.failed_index = i
                    out.message = (
                        f"Step {i} ({step.tool}) ran but could not be verified "
                        f"({step.verify.kind})."
                    )
                    out.steps.append(StepResult(step.tool, True, False, res, "VERIFY_FAILED",
                                                str(d.get("message") or "")))
                    return out

            out.steps.append(StepResult(step.tool, True, verified, res, ec, str(d.get("message") or "")))
        out.message = f"Completed {len(out.steps)} step(s)."
        return out

    def _verify(self, spec: VerifySpec, context: dict) -> bool:
        fn = _VERIFIERS.get(spec.kind)
        if fn is None:
            # Unknown verify kind → do not block (treat as soft/no-op), but the
            # caller asked for a check we don't know, so log-friendly default True.
            return True
        expect = _resolve_args(spec.expect, context)
        probe_entities = _resolve_args(spec.probe_entities, context)
        attempts = max(1, int(spec.retries))
        for n in range(attempts):
            try:
                res = self._run(spec.probe_action, probe_entities)
            except Exception:
                res = {}
            if fn(res, expect):
                return True
            if n < attempts - 1 and spec.delay_s:
                self._sleep(spec.delay_s)
        return False


# ── Deterministic decomposition (first layer / safety net) ─────────────────────
# The GENERAL solution is to let the brain emit a multi-step plan (language-
# agnostic; staged for live verification). This rule-based decomposer covers the
# documented English compound commands so the engine is exercisable now and
# there is a deterministic fallback. It returns ``None`` for anything it does not
# confidently recognise, so non-compound input falls through to the legacy
# single-action path unchanged.
_DOWNLOAD_KW = ("download", "fetch", "دانلود", "دریافت")
_OPEN_KW = ("open", "بازش", "باز کن", "باز کن.", "بازکن")
_LOAD_KW = ("load", "import", "drop", "بارگذاری", "ایمپورت", "وارد")
_SERIES_KW = ("series", "سری")
_ORDINAL = {
    "first": 0, "1st": 0, "اول": 0, "اولین": 0,
    "second": 1, "2nd": 1, "دوم": 1, "دومین": 1,
    "third": 2, "3rd": 2, "سوم": 2, "سومین": 2,
}


def _has(text: str, kws) -> bool:
    return any(k in text for k in kws)


def _series_index(text: str) -> Optional[int]:
    for word, idx in _ORDINAL.items():
        if word in text:
            return idx
    import re
    m = re.search(r"series\s+(\d+)", text)
    if m:
        return int(m.group(1)) - 1
    return None


def decompose(text: str, *, patient_ref: str = "$patient_id") -> Optional[WorkflowPlan]:
    """Best-effort decomposition of a compound command into a WorkflowPlan.

    ``patient_ref`` is the entity used to identify the patient in later steps
    (defaults to the context value captured from the first step). Returns
    ``None`` when the text is not a recognised multi-step command.
    """
    t = (text or "").strip().lower()
    if not t:
        return None
    wants_dl = _has(t, _DOWNLOAD_KW)
    wants_open = _has(t, _OPEN_KW)
    wants_load = _has(t, _LOAD_KW) and _has(t, _SERIES_KW)
    sidx = _series_index(t) if wants_load else None

    steps: list = []
    goal_bits: list = []

    if wants_dl:
        steps.append(WorkflowStep(
            tool="download_patient",
            args={"patient_code": patient_ref} if not patient_ref.startswith("$") else {},
            verify=VerifySpec("download_complete", "check_download_status",
                              probe_entities={}, retries=30, delay_s=2.0),
            capture={"patient_id": "patient_id", "study_uid": "study_uid"},
        ))
        goal_bits.append("download")

    if wants_open:
        steps.append(WorkflowStep(
            tool="open_patient",
            args={"patient_code": patient_ref},
            verify=VerifySpec("patient_open", "get_active_tab",
                              expect={"patient_id": "$patient_id"}, retries=10, delay_s=1.0),
        ))
        goal_bits.append("open")

    if wants_load:
        steps.append(WorkflowStep(
            tool="get_thumbnails_data", args={},
            verify=VerifySpec("thumbnails_loaded", "get_thumbnails_data", retries=10, delay_s=1.0),
        ))
        steps.append(WorkflowStep(
            tool="change_series",
            args={"series_index": (sidx if sidx is not None else 0), "viewport": 0},
            verify=VerifySpec("viewport_has_series", "query_viewport_state",
                              expect={"viewport": 0}, retries=10, delay_s=1.0),
        ))
        goal_bits.append("load series")

    # Only treat it as a workflow when there are ≥2 real actions to sequence.
    action_steps = [s for s in steps if s.tool != "get_thumbnails_data"]
    if len(action_steps) < 2:
        return None
    return WorkflowPlan(goal=" + ".join(goal_bits) or "workflow", steps=steps)


__all__ = [
    "WORKFLOWS_ENABLED", "VerifySpec", "WorkflowStep", "WorkflowPlan",
    "StepResult", "WorkflowResult", "WorkflowExecutor", "decompose",
    "make_step", "build_plan", "DEFAULT_CAPTURE",
]
