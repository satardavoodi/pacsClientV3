"""One-off: prove the Text-tool guards FAIL on the pre-fix codebase.

Repo rule (docs/plans/architecture/REGRESSION_CATALOG.md): "Guard test must
FAIL on the pre-fix codebase."  This reconstructs the pre-fix sources with
`git show HEAD:<path>` — the working tree is never touched, which matters
here because it carries unrelated in-flight EchoMind work.

Two kinds of proof:

  1. BEHAVIOURAL — the whole pre-fix `modules/viewer/tools` package is checked
     out into a temp dir and imported under a throw-away name, then the same
     scenario the guard tests run is replayed against it.
  2. STRUCTURAL — the pre-fix `qt_viewer_bridge.py` and
     `text_interactorstyle.py` are AST-checked with the exact predicates the
     guard tests use.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\verify_text_guard_fails_prefix.py
"""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FAILS: list[str] = []
UNEXPECTED: list[str] = []


def show(rel: str) -> str:
    out = subprocess.run(
        ["git", "show", f"HEAD:{rel}"],
        cwd=REPO, capture_output=True, check=True,
    )
    return out.stdout.decode("utf-8")


def ls(rel: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "HEAD", rel],
        cwd=REPO, capture_output=True, check=True,
    )
    return [p for p in out.stdout.decode("utf-8").splitlines() if p.endswith(".py")]


def check(name: str, failed: bool, detail: str) -> None:
    """`failed` = the guard would fail pre-fix, which is what we WANT."""
    mark = "FAILS pre-fix (good)" if failed else "PASSES pre-fix (BAD)"
    print(f"  [{mark}] {name}: {detail}")
    (FAILS if failed else UNEXPECTED).append(name)


# ── 1. Behavioural: replay the scenario against the pre-fix controller ──────

def behavioural() -> None:
    print("\n1. BEHAVIOURAL — pre-fix modules/viewer/tools")
    paths = ls("modules/viewer/tools")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for rel in paths:
            dest = root / "prefix_tools" / Path(rel).relative_to("modules/viewer/tools")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(show(rel), encoding="utf-8")
        print(f"   checked out {len(paths)} files from HEAD")

        sys.path.insert(0, str(root))
        try:
            spec = importlib.util.find_spec("prefix_tools.controller")
            if spec is None:
                raise ImportError("prefix_tools.controller not importable")
            from prefix_tools.controller import ToolController  # type: ignore
            from prefix_tools.enums import ToolType             # type: ignore
            from prefix_tools.models import TextModel            # type: ignore
            from prefix_tools.store import ToolStore             # type: ignore

            class _NoOp:
                def render_tool(self, *a, **kw):
                    return None

                def render_preview(self, *a, **kw):
                    return None

            # test_the_typed_text_is_what_lands_on_the_image
            store = ToolStore()
            ctrl = ToolController(store, _NoOp())
            asked = {"n": 0}

            def _prompt():
                asked["n"] += 1
                return "L4-L5 disc"

            try:
                ctrl._text_prompt_fn = _prompt
                wired = True
                wire_err = ""
            except AttributeError as exc:
                wired = False
                wire_err = str(exc)

            ctrl.activate(ToolType.TEXT)
            ctrl.on_mouse_press(100.0, 200.0, 0)
            items = [m for m in store.get_for_slice(0) if isinstance(m, TextModel)]
            got = items[0].text if items else "<nothing placed>"

            if not wired:
                check(
                    "test_the_typed_text_is_what_lands_on_the_image",
                    True,
                    f"pre-fix ToolController.__slots__ has no _text_prompt_fn "
                    f"({wire_err}); text placed = {got!r}",
                )
            else:
                check(
                    "test_the_typed_text_is_what_lands_on_the_image",
                    got != "L4-L5 disc",
                    f"prompt asked {asked['n']}x, text placed = {got!r} "
                    f"(expected 'L4-L5 disc')",
                )

            check(
                "test_cancel_places_nothing",
                not wired,
                "cancel cannot even be expressed pre-fix — no _text_prompt_fn"
                if not wired else "prompt slot exists",
            )

            # The one thing that MUST still hold after the fix:
            store2 = ToolStore()
            ctrl2 = ToolController(store2, _NoOp())
            ctrl2.activate(ToolType.TEXT)
            ctrl2.on_mouse_press(1.0, 2.0, 0)
            legacy = [m for m in store2.get_for_slice(0) if isinstance(m, TextModel)]
            legacy_text = legacy[0].text if legacy else "<nothing>"
            print(
                f"  [back-compat] pre-fix bare controller places {legacy_text!r} "
                f"— test_without_a_prompt_the_legacy_placeholder_is_kept must "
                f"keep passing BOTH before and after (it does: expects 'Text')"
            )
        finally:
            sys.path.remove(str(root))
            for mod in [m for m in sys.modules if m.startswith("prefix_tools")]:
                del sys.modules[mod]


# ── 2. Structural: AST predicates from the guard tests ─────────────────────

def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def structural() -> None:
    print("\n2. STRUCTURAL — pre-fix qt_viewer_bridge.py")
    tree = ast.parse(show("modules/viewer/fast/qt_viewer_bridge.py"))

    fn = _func(tree, "_init_tool_controller")
    wired = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Attribute) and t.attr == "_text_prompt_fn"
            for t in n.targets
        )
    ] if fn is not None else []
    check(
        "test_the_bridge_wires_the_prompt",
        not wired,
        f"_init_tool_controller assigns _text_prompt_fn: {bool(wired)}",
    )

    has_method = _func(tree, "_prompt_annotation_text") is not None
    check(
        "test_the_bridge_exposes_the_prompt_method",
        not has_method,
        f"_prompt_annotation_text defined: {has_method}",
    )

    print("\n3. STRUCTURAL — pre-fix text_interactorstyle.py")
    vtree = ast.parse(show("modules/viewer/interactor_styles/text_interactorstyle.py"))
    vfn = _func(vtree, "on_left_button_press")
    guards = [
        n for n in ast.walk(vfn)
        if isinstance(n, ast.If)
        and any(isinstance(x, ast.Name) and x.id == "ok" for x in ast.walk(n.test))
        and any(isinstance(b, ast.Return) for b in n.body)
    ] if vfn is not None else []
    check(
        "test_the_vtk_text_tool_honours_cancel",
        not guards,
        f"cancel guard on `ok` present: {bool(guards)}",
    )

    ftree = ast.parse(show("modules/viewer/fast/qt_viewer_bridge.py"))
    same = _func(ftree, "_prompt_annotation_text") is not None
    check(
        "test_both_backends_ask_the_same_question",
        not same,
        f"FAST has no getText call at all pre-fix: {not same}",
    )


if __name__ == "__main__":
    print(f"repo: {REPO}")
    behavioural()
    structural()
    print("\n" + "=" * 70)
    print(f"guards that FAIL pre-fix (as required): {len(FAILS)}")
    for n in FAILS:
        print(f"  - {n}")
    if UNEXPECTED:
        print(f"\nGUARDS THAT ALREADY PASS PRE-FIX ({len(UNEXPECTED)}) — investigate:")
        for n in UNEXPECTED:
            print(f"  - {n}")
    sys.exit(1 if UNEXPECTED else 0)
