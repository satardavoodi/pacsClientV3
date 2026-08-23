"""One-off: prove the MPR-lifecycle guards FAIL on the pre-fix codebase.

Repo rule (REGRESSION_CATALOG.md): "Guard test must FAIL on the pre-fix
codebase." Reconstructs HEAD with `git show` — the working tree is never
touched (it also carries unrelated in-flight EchoMind work).

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\verify_mpr_lifecycle_guard_fails_prefix.py
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
FAILS: list[str] = []
UNEXPECTED: list[str] = []

LAYOUT = "modules/mpr/zeta_mpr/mpr_viewer/_mpr_layout.py"
SERIES = "modules/mpr/zeta_mpr/mpr_viewer/_mpr_series.py"
VIEWS = "modules/mpr/zeta_mpr/mpr_viewer/_mpr_views.py"
LIFECYCLE = "modules/mpr/zeta_mpr/mpr_viewer/_mpr_lifecycle.py"
UTILS = "PacsClient/pacs/patient_tab/utils/utils.py"
PWLIFE = ("PacsClient/pacs/patient_tab/ui/patient_ui/patient_widget_core/"
          "_pw_lifecycle.py")


def show(rel: str):
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO,
                         capture_output=True)
    return out.stdout.decode("utf-8") if out.returncode == 0 else None


def check(name: str, failed_prefix: bool, detail: str) -> None:
    mark = "FAILS pre-fix (good)" if failed_prefix else "PASSES pre-fix (BAD)"
    print(f"  [{mark}] {name}: {detail}")
    (FAILS if failed_prefix else UNEXPECTED).append(name)


def _func(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    return None


def main() -> int:
    print(f"repo: {REPO}\n")

    print("1. THE LIFECYCLE HELPER DID NOT EXIST")
    missing = show(LIFECYCLE) is None
    check("import of _mpr_lifecycle.py", missing,
          "absent at HEAD" if missing else "already present")
    print("   -> every release_mpr_children / mpr_memory_probe guard fails at "
          "import on the pre-fix tree\n")

    print("2. NO closeEvent ON THE MPR WIDGET")
    layout = show(LAYOUT)
    ltree = ast.parse(layout)
    ce = _func(ltree, "closeEvent")
    check("test_the_layout_mixin_defines_closeevent", ce is None,
          f"closeEvent defined: {ce is not None}")
    check("test_closeevent_calls_cleanup_and_then_super", ce is None,
          "no closeEvent to call cleanup from")
    check("test_closeevent_reruns_nothing_on_an_already_closed_viewer",
          ce is None, "no closeEvent to bind")

    cl = _func(ltree, "cleanup")
    cl_src = ast.unparse(cl) if cl else ""
    check("test_cleanup_measures_what_it_freed",
          "mpr_memory_probe" not in cl_src,
          f"cleanup emits a memory probe: {'mpr_memory_probe' in cl_src}")

    print("\n3. THE OWNERS ORPHANED THE MPR WITHOUT TEARDOWN")
    utils = show(UTILS)
    utree = ast.parse(utils)
    for fname in ("delete_widgets_in_layout", "delete_layout"):
        fn = _func(utree, fname)
        src = ast.unparse(fn) if fn else ""
        has = "_release_mpr_before_drop" in src or "release_mpr_children" in src
        check(f"test_layout_teardown_releases_before_orphaning[{fname}]",
              not has, f"{fname} releases MPR children: {has}")

    pw = show(PWLIFE) or ""
    check("test_patient_close_releases_the_mpr_child",
          "release_mpr_children" not in pw,
          f"patient close releases the MPR child: "
          f"{'release_mpr_children' in pw}")

    check("test_the_helper_is_the_single_implementation",
          "_mpr_lifecycle" not in utils and "_mpr_lifecycle" not in pw,
          "neither owner referenced a shared helper")

    print("\n4. THE 3D MAPPER KEPT THE PREVIOUS VOLUME")
    stree = ast.parse(show(SERIES))
    rl = _func(stree, "_reload_with_series")
    rl_src = ast.unparse(rl) if rl else ""
    has_3d = "'3d'" in rl_src or '"3d"' in rl_src
    check("test_series_switch_repoints_the_3d_mapper_source", not has_3d,
          f"_reload_with_series mentions the 3d view: {has_3d}")
    check("test_series_switch_actually_repoints_the_3d_mapper", not has_3d,
          "the orthogonal loop covers axial/sagittal/coronal only, so the "
          "GPU mapper stayed on the OLD volume")

    print("\n5. NO MEMORY NUMBER ANYWHERE IN THE MPR OPEN PATH")
    vtree = ast.parse(show(VIEWS))
    su = _func(vtree, "_setup_ui")
    su_src = ast.unparse(su) if su else ""
    check("open-side memory probe", "mpr_memory_probe" not in su_src,
          f"_setup_ui probes memory: {'mpr_memory_probe' in su_src}")

    print("\n" + "=" * 70)
    print(f"guards that FAIL pre-fix (as required): {len(FAILS)}")
    for n in FAILS:
        print(f"  - {n}")
    if UNEXPECTED:
        print(f"\nGUARDS THAT ALREADY PASS PRE-FIX ({len(UNEXPECTED)}):")
        for n in UNEXPECTED:
            print(f"  - {n}")
    return 1 if UNEXPECTED else 0


if __name__ == "__main__":
    sys.exit(main())
