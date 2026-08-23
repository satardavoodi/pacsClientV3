"""One-off: prove the report-image guards FAIL on the pre-fix codebase.

Repo rule (docs/plans/architecture/REGRESSION_CATALOG.md): "Guard test must
FAIL on the pre-fix codebase." Reconstructs HEAD with `git show` — the working
tree is never touched, which matters because it also carries unrelated
in-flight EchoMind work.

Two classes of proof:
  1. The helper modules did not exist at HEAD, so every listing/encoding/
     round-trip guard would fail at import.
  2. The editor at HEAD has no image button, no connections and no
     data-URI install — checked with the exact AST predicates the guards use.

Run:  .venv\\Scripts\\python.exe tools\\analysis\\oneoff\\verify_report_image_guard_fails_prefix.py
"""
from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
EDITOR = "modules/ai_imaging/ai_module_ui/service_tab/widgets/report_editor_dialog.py"
NEW_MODULES = [
    "modules/ai_imaging/ai_module_ui/service_tab/widgets/report_capture_images.py",
    "modules/ai_imaging/ai_module_ui/service_tab/widgets/report_image_picker_dialog.py",
]

FAILS: list[str] = []
UNEXPECTED: list[str] = []


def show(rel: str):
    out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=REPO, capture_output=True)
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

    print("1. THE HELPER MODULES DID NOT EXIST AT HEAD")
    for rel in NEW_MODULES:
        missing = show(rel) is None
        check(
            f"import of {Path(rel).name}",
            missing,
            "absent at HEAD" if missing else "already present at HEAD",
        )
    print("   -> every listing / encoding / round-trip guard fails at import "
          "on the pre-fix tree\n")

    print("2. THE EDITOR HAD NO IMAGE SUPPORT AT HEAD")
    src = show(EDITOR)
    if src is None:
        print("   !! could not read the editor from HEAD")
        return 1
    tree = ast.parse(src)

    toolbar = _func(tree, "_create_format_toolbar")
    assigned = set()
    if toolbar is not None:
        assigned = {
            t.attr for node in ast.walk(toolbar) if isinstance(node, ast.Assign)
            for t in node.targets if isinstance(t, ast.Attribute)
        }
    check(
        "test_the_toolbar_gains_an_insert_image_button",
        "btn_image" not in assigned,
        f"btn_image built in the toolbar: {'btn_image' in assigned}",
    )
    check(
        "test_the_resize_buttons_exist",
        not {"btn_img_smaller", "btn_img_larger", "btn_img_fit"} <= assigned,
        f"resize buttons present: "
        f"{sorted({'btn_img_smaller', 'btn_img_larger', 'btn_img_fit'} & assigned)}",
    )

    connections = _func(tree, "_setup_connections")
    conn_src = ast.unparse(connections) if connections is not None else ""
    check(
        "test_the_image_buttons_are_connected",
        "self.btn_image.clicked.connect" not in conn_src,
        f"btn_image connected: {'self.btn_image.clicked.connect' in conn_src}",
    )

    insert = _func(tree, "_insert_captured_image")
    check(
        "test_insert_goes_through_the_picker_and_the_encoder",
        insert is None,
        f"_insert_captured_image defined: {insert is not None}",
    )
    check(
        "test_a_cancelled_picker_inserts_nothing",
        insert is None,
        "no insert handler to cancel out of" if insert is None else "handler exists",
    )

    editor_area = _func(tree, "_create_editor_area")
    area_src = ast.unparse(editor_area) if editor_area is not None else ""
    check(
        "test_the_editor_installs_data_uri_support_before_content_loads",
        "install_data_uri_image_support" not in area_src,
        f"install call present: {'install_data_uri_image_support' in area_src}",
    )

    resolver = _func(tree, "_report_study_uid")
    check(
        "test_the_study_uid_uses_the_same_keys_as_the_history_lookup",
        resolver is None,
        f"_report_study_uid defined: {resolver is not None}",
    )

    print("\n3. WHAT THE PRE-FIX EDITOR COULD INSERT")
    inserts = sorted(
        n.name for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name.startswith("_insert_")
    )
    print(f"   {inserts}")
    print("   -> link, table and horizontal line. No way to place an image.")

    print("\n" + "=" * 70)
    print(f"guards that FAIL pre-fix (as required): {len(FAILS)}")
    for n in FAILS:
        print(f"  - {n}")
    if UNEXPECTED:
        print(f"\nGUARDS THAT ALREADY PASS PRE-FIX ({len(UNEXPECTED)}) — investigate:")
        for n in UNEXPECTED:
            print(f"  - {n}")
    return 1 if UNEXPECTED else 0


if __name__ == "__main__":
    sys.exit(main())
