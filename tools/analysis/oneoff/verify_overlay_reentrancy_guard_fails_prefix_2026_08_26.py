"""Prove the overlay-re-entrancy guards FAIL on the pre-fix codebase (2026-08-26).

Repo rule: a guard test that passes before the fix guards nothing.

`git show HEAD:` is safe for these TWO files specifically - it is asserted, not
assumed. This working tree carries unrelated uncommitted work in other files
(`toolbar_manager.py`, `_pw_panels.py`, builder outputs, ...), so the script
restores ONLY `loading_overlay.py` and `qt_fast_container.py` and leaves
everything else alone. It also refuses to run if HEAD already contains the fix.

Some guards are EXPECTED to pass pre-fix and that is correct rather than weak:
the prior-art anchor (the 2026-06-05 fade liveness check) and the kill-switch
default both describe properties that must hold on BOTH sides.

Backups go to a temp dir whose path is printed before anything is written.

Usage:  python tools/analysis/oneoff/verify_overlay_reentrancy_guard_fails_prefix_2026_08_26.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
GUARD = "tests/code/system/test_overlay_reentrancy_crash.py"

FILES = {
    "PacsClient/components/loading_overlay.py": ("_overlay_sync_paint_enabled",),
    "PacsClient/pacs/patient_tab/ui/patient_ui/vtk_widget/qt_fast_container.py":
        ("_in_switch_series",),
}

LOAD_BEARING = {
    "test_show_overlay_does_not_unconditionally_reenter_the_event_loop",
    "test_sync_paint_kill_switch_defaults_on",
    "test_overlay_init_refuses_a_destroyed_anchor",
    "test_anchor_guard_runs_before_anything_touches_the_anchor",
    "test_switch_series_has_a_reentrancy_guard",
    "test_the_reentrancy_flag_is_cleared_in_a_finally",
    "test_a_nested_switch_is_refused",
    "test_the_flag_clears_when_the_switch_raises",
}


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def main() -> int:
    head = {}
    for rel, markers in FILES.items():
        src = _git("show", f"HEAD:{rel}")
        for m in markers:
            if m in src:
                print(f"REFUSING: HEAD:{rel} already contains {m!r} - nothing to prove.")
                return 2
        head[rel] = src
        print(f"HEAD:{rel} lacks {markers} - good")

    tmp = Path(tempfile.mkdtemp(prefix="overlay_reentrancy_prefix_"))
    print(f"backups -> {tmp}")
    backups = {}
    for rel in FILES:
        dst = tmp / Path(rel).name
        shutil.copy2(ROOT / rel, dst)
        backups[rel] = dst

    text = ""
    try:
        for rel, src in head.items():
            (ROOT / rel).write_text(src, encoding="utf-8", newline="")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", GUARD, "-q", "-p", "no:cacheprovider",
             "--no-header", "-rf", "-p", "no:randomly"],
            cwd=str(ROOT), capture_output=True,
        )
        text = proc.stdout.decode("utf-8", errors="replace")
        print(text[-1400:])
    finally:
        for rel, bak in backups.items():
            shutil.copy2(bak, ROOT / rel)
            print(f"restored {rel}")

    failed = {
        line.split("::")[-1].split()[0]
        for line in text.splitlines()
        if line.startswith("FAILED ")
    }
    print(f"\npre-fix failures ({len(failed)}): {sorted(failed)}")
    missing = LOAD_BEARING - failed
    if missing:
        print(f"NOT GUARDED (passed pre-fix): {sorted(missing)}")

    proc2 = subprocess.run(
        [sys.executable, "-m", "pytest", GUARD, "-q", "-p", "no:cacheprovider", "--no-header"],
        cwd=str(ROOT), capture_output=True,
    )
    tail = proc2.stdout.decode("utf-8", errors="replace").strip().splitlines()
    print("post-restore:", tail[-1] if tail else "(no output)")

    ok = not missing and proc2.returncode == 0
    print("\nRESULT:", "OK - guards fail pre-fix and pass post-fix" if ok else "PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
