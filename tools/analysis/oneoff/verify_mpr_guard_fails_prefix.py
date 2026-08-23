"""Prove the new instrumentation guard FAILS on the pre-fix source.

Runs the guard's own logic against `git show HEAD:_mpr_views.py` instead of the
working copy, so nothing in the tree is touched.
"""
from __future__ import annotations

import ast
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REL = "modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py"
CREATORS = {"_create_axial_view": "axial", "_create_sagittal_view": "sagittal",
            "_create_coronal_view": "coronal", "_create_3d_view": "3d"}
HOT = ("qvtk_interactor_ctor", "interactor_initialize")


def steps(fn):
    out = []
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "_mpr_step" and len(n.args) == 3
                and all(isinstance(a, ast.Constant) for a in n.args)):
            out.append(tuple(a.value for a in n.args))
    return out


def check(label: str, src: str) -> None:
    tree = ast.parse(src)
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    fails = []
    for fname, view in CREATORS.items():
        fn = funcs.get(fname)
        s = steps(fn) if fn else []
        if not s:
            fails.append(f"{fname}: emits NO steps")
            continue
        seen = {v for v, _, _ in s}
        if seen != {view}:
            fails.append(f"{fname}: labels {sorted(seen)}, expected ['{view}']")
        if fname != "_create_3d_view":
            ph = {(st, p) for _, st, p in s}
            for h in HOT:
                if (h, "begin") not in ph or (h, "end") not in ph:
                    fails.append(f"{fname}: {h} not bracketed")
    for special, fn_name in (("setup_ui", "_setup_ui"),
                             ("prewarm_reslice", "_prewarm_mpr_reslice")):
        fn = funcs.get(fn_name)
        ph = {(st, p) for v, st, p in (steps(fn) if fn else []) if v == "all"}
        if (special, "begin") not in ph or (special, "end") not in ph:
            fails.append(f"{fn_name}: '{special}' not bracketed")

    print(f"\n--- {label} ---")
    if fails:
        print(f"  GUARD FAILS ({len(fails)} violations):")
        for f in fails:
            print("    x", f)
    else:
        print("  GUARD PASSES")
    per_view = defaultdict(int)
    for fname in CREATORS:
        if funcs.get(fname):
            for v, _, _ in steps(funcs[fname]):
                per_view[v] += 1
    print(f"  step call sites per view: {dict(per_view) or '(none)'}")


head = subprocess.run(["git", "show", f"HEAD:{REL}"], cwd=ROOT,
                      capture_output=True, text=True, encoding="utf-8")
if head.returncode != 0:
    print("git show failed:", head.stderr[:300])
else:
    check("PRE-FIX (git HEAD)", head.stdout)
check("WORKING COPY (after instrumentation)",
      (ROOT / REL).read_text(encoding="utf-8"))
