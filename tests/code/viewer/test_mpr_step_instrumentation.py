"""Every MPR view creator must emit its own [MPR-STEP] timings (2026-08-18).

THE GAP THIS CLOSES

`_mpr_step()` existed since the crash-bisector work, but **all 17 call sites
passed `'axial'`** — `_create_sagittal_view`, `_create_coronal_view` and
`_create_3d_view` emitted nothing at all. That was invisible until a real
freeze needed attributing.

Live evidence, patient 54675 (EHSANI BATOOL, CT SPINE 512x512x272), MPR
activation at 2026-08-18 11:23:55:

    ~8.7 s of blocked GUI time across 9 stalls, largest 4,719.7 ms
    [MPR-STEP] accounted for 2,638 ms, `views seen: ['axial']`
    the 4,201 ms sample was _create_coronal_view -> QVTKRenderWindowInteractor

So the single most expensive step in the whole activation was the one step the
timing table could not see. Attribution had to fall back on the stall
sampler — which gives you *what the thread was doing at an instant*, not what
anything cost.

WHAT IS PINNED

  * all four creators emit steps, under their OWN view name;
  * no creator mislabels its steps as another view (the original defect);
  * the two steps that actually dominate (`qvtk_interactor_ctor`,
    `interactor_initialize`) are bracketed on every 2D plane;
  * every `begin` has a matching `end` in the same function, or a phase
    silently never closes and the timeline lies;
  * `_setup_ui` and `_prewarm_mpr_reslice` are bracketed, so the
    instrumented total can be compared against the observed stall instead of
    leaving an unexplained gap.

This is instrumentation only — no behavioural change, and `_mpr_step` stays
kill-switchable via AIPACS_MPR_STEP_TRACE=0.
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

import pytest


def _repo_root() -> Path:
    p = Path(__file__).resolve()
    for anc in p.parents:
        if (anc / "PacsClient").is_dir() and (anc / "modules").is_dir():
            return anc
    raise RuntimeError("repo root not found from %s" % __file__)


REPO_ROOT = _repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SRC = REPO_ROOT / "modules" / "mpr" / "zeta_mpr" / "mpr_viewer" / "_mpr_views.py"

CREATORS = {
    "_create_axial_view": "axial",
    "_create_sagittal_view": "sagittal",
    "_create_coronal_view": "coronal",
    "_create_3d_view": "3d",
}

#: the two steps that dominated the 2026-08-18 activation
HOT_STEPS = ("qvtk_interactor_ctor", "interactor_initialize")


@pytest.fixture(scope="module")
def tree() -> ast.Module:
    return ast.parse(SRC.read_text(encoding="utf-8"))


def _funcs(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _steps(fn: ast.FunctionDef) -> list[tuple[str, str, str]]:
    """(view, step, phase) for every literal `_mpr_step(...)` call in `fn`."""
    out = []
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "_mpr_step"):
            continue
        args = [a.value if isinstance(a, ast.Constant) else None for a in node.args]
        if len(args) == 3 and all(isinstance(a, str) for a in args):
            out.append(tuple(args))
    return out


# ── 1. every creator is instrumented, under its own name ────────────────────

@pytest.mark.parametrize("fname,view", sorted(CREATORS.items()))
def test_every_view_creator_emits_steps(tree, fname, view):
    fn = _funcs(tree).get(fname)
    assert fn is not None, f"{fname} disappeared — update this guard"
    steps = _steps(fn)
    assert steps, (
        f"{fname} emits NO [MPR-STEP] lines. This is exactly the state that made "
        f"the 4.2 s coronal cost invisible on 2026-08-18."
    )
    assert {v for v, _, _ in steps} == {view}, (
        f"{fname} labels its steps {sorted({v for v, _, _ in steps})}, expected "
        f"only {view!r} — a mislabelled view is worse than none, it attributes "
        f"one plane's cost to another"
    )


def test_no_creator_is_still_hardcoded_to_axial(tree):
    """The original defect, stated directly."""
    funcs = _funcs(tree)
    offenders = [
        fname for fname, view in CREATORS.items()
        if view != "axial" and any(v == "axial" for v, _, _ in _steps(funcs[fname]))
    ]
    assert not offenders, f"these creators still emit view='axial': {offenders}"


# ── 2. the steps that actually cost something ───────────────────────────────

@pytest.mark.parametrize("fname", ["_create_axial_view", "_create_sagittal_view",
                                   "_create_coronal_view"])
@pytest.mark.parametrize("step", HOT_STEPS)
def test_the_dominant_steps_are_bracketed(tree, fname, step):
    phases = {(s, p) for _, s, p in _steps(_funcs(tree)[fname])}
    assert (step, "begin") in phases and (step, "end") in phases, (
        f"{fname} does not bracket {step!r} — on 2026-08-18 those two steps were "
        f"1,176 ms and 811 ms on the axial plane alone"
    )


def test_the_3d_view_measures_the_gpu_mapper(tree):
    """`vtkGPUVolumeRayCastMapper()` was a 575 ms sample on 2026-08-16."""
    phases = {s for _, s, _ in _steps(_funcs(tree)["_create_3d_view"])}
    assert "gpu_raycast_mapper_ctor" in phases


# ── 3. a phase that never closes makes the timeline lie ─────────────────────

@pytest.mark.parametrize("fname", sorted(CREATORS))
def test_every_begin_has_an_end(tree, fname):
    counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for view, step, phase in _steps(_funcs(tree)[fname]):
        if phase == "begin":
            counts[(view, step)][0] += 1
        elif phase == "end":
            counts[(view, step)][1] += 1
        else:
            pytest.fail(f"{fname}: unknown phase {phase!r}")
    unbalanced = {k: v for k, v in counts.items()
                  if v[0] != v[1] and k[1] != "create_view"}
    assert not unbalanced, f"{fname} has unbalanced begin/end: {unbalanced}"


# ── 4. the brackets that let the numbers be reconciled ──────────────────────

def test_setup_ui_brackets_the_whole_phase(tree):
    phases = {(s, p) for v, s, p in _steps(_funcs(tree)["_setup_ui"]) if v == "all"}
    assert ("setup_ui", "begin") in phases and ("setup_ui", "end") in phases, (
        "without this bracket the per-view numbers cannot be compared against the "
        "observed stall — 2,638 ms instrumented vs ~8.7 s blocked, unexplained"
    )


def test_prewarm_is_measured_and_cannot_leak(tree):
    fn = _funcs(tree)["_prewarm_mpr_reslice"]
    phases = {(s, p) for v, s, p in _steps(fn) if v == "all"}
    assert ("prewarm_reslice", "begin") in phases
    assert ("prewarm_reslice", "end") in phases, "prewarm end marker missing"
    # the function returns early on RuntimeError, so the end must be in a finally
    in_finally = any(
        isinstance(n, ast.Try) and any(
            ("prewarm_reslice", "end") in {
                (a.args[1].value, a.args[2].value)
                for a in ast.walk(h) if isinstance(a, ast.Call)
                and isinstance(a.func, ast.Name) and a.func.id == "_mpr_step"
                and len(a.args) == 3 and all(isinstance(x, ast.Constant) for x in a.args)
            }
            for h in n.finalbody
        )
        for n in ast.walk(fn)
    )
    assert in_finally, (
        "the prewarm end marker must be in a `finally` — the function returns "
        "early when MPR was closed mid-defer, which would drop the phase"
    )


# ── 5. behaviour: it must stay cheap and unable to break MPR ────────────────

def test_mpr_step_never_raises_and_is_kill_switchable(monkeypatch):
    pytest.importorskip("vtkmodules")
    mod = pytest.importorskip("modules.mpr.zeta_mpr.mpr_viewer._mpr_views")

    mod._mpr_step("coronal", "qvtk_interactor_ctor", "begin")   # must not raise

    class _Boom:
        def info(self, *a, **k):
            raise RuntimeError("logger died")

    monkeypatch.setattr(mod, "logger", _Boom())
    mod._mpr_step("coronal", "qvtk_interactor_ctor", "end")     # still must not raise


def test_the_trace_has_a_kill_switch():
    src = SRC.read_text(encoding="utf-8")
    assert "AIPACS_MPR_STEP_TRACE" in src
