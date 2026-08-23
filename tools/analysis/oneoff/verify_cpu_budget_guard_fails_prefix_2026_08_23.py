"""Prove the [CPU_BUDGET] priority guards FAIL on the pre-fix codebase (2026-08-23).

Repo rule: a guard test that passes before the fix guards nothing.

Covers BOTH landings in this file's history:
  1. the ctypes pseudo-handle fix (the boost never applied), and
  2. the build-type default (frozen/installed -> HIGH, source -> ABOVE_NORMAL).

Unlike the A0 verification, this one can use git directly \u2014 but it PROVES that
it may rather than assuming it: every hunk of `git diff -- main.py` must fall
inside the CPU BUDGET block as it exists at HEAD. If any edit lands outside the
block, `git show HEAD:main.py` would revert unrelated work and the guards would
"fail" for the wrong reason, so the script refuses to run.

The two Win32 probes (test_*_pseudo_handle_is_*_by_windows) are EXPECTED to pass
pre-fix \u2014 they test Windows' semantics, not our source.

Backup goes to a temp dir whose path is printed before main.py is touched, so a
crash is always recoverable by hand.

Usage:  python tools/analysis/oneoff/verify_cpu_budget_guard_fails_prefix_2026_08_23.py
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MAIN = ROOT / "main.py"
GUARD = "tests/code/system/test_cpu_budget_priority_boost.py"

BLOCK_START = "CPU BUDGET: Raise main process priority"
BLOCK_END = "except Exception as _pri_exc:"

# Guards that MUST flip. Not the full failing set \u2014 just the ones whose failure
# is the point. The script prints everything it observed either way.
LOAD_BEARING = {
    # (1) the ctypes fix
    "test_getcurrentprocess_restype_is_pointer_sized",
    "test_setpriorityclass_argtypes_declare_a_handle",
    "test_setpriorityclass_restype_declared",
    "test_restype_is_set_before_the_handle_is_taken",
    "test_argtypes_are_set_before_setpriorityclass_is_called",
    # (2) the build-type default
    "test_frozen_builds_default_to_high",
    "test_source_runs_default_to_above_normal",
    "test_unknown_value_falls_back_to_the_machine_default_not_a_constant",
    "test_high_is_the_default_only_for_installed_builds",
    "test_frozen_detection_uses_the_canonical_helper",
}

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? ")


def _git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True, check=True)
    return out.stdout.decode("utf-8", errors="replace")


def _head_block_lines(head_src: str) -> tuple[int, int]:
    lines = head_src.splitlines()
    start = end = None
    for i, line in enumerate(lines, 1):
        if start is None and BLOCK_START in line:
            start = i
        elif start is not None and BLOCK_END in line:
            end = i
            break
    assert start and end, "CPU BUDGET block not found at HEAD"
    return start, end


def _diff_stays_inside(head_src: str) -> bool:
    """Every hunk of the working diff must touch only the CPU BUDGET block."""
    lo, hi = _head_block_lines(head_src)
    print(f"HEAD CPU BUDGET block: lines {lo}-{hi}")
    ok = True
    for line in _git("diff", "-U0", "--", "main.py").splitlines():
        m = HUNK.match(line)
        if not m:
            continue
        start = int(m.group(1))
        count = int(m.group(2) or "1")
        # count==0 means a pure insertion after `start`; it touches nothing.
        end = start + count - 1 if count else start
        inside = lo <= start and end <= hi
        print(f"  hunk old lines {start}-{end}: {'inside' if inside else 'OUTSIDE'}")
        ok = ok and inside
    return ok


def main() -> int:
    head_src = _git("show", "HEAD:main.py")

    if not _diff_stays_inside(head_src):
        print("REFUSING: main.py has edits outside the CPU BUDGET block; "
              "git show HEAD: would revert unrelated work.")
        return 2

    assert "GetCurrentProcess.restype" not in head_src, "HEAD already has fix (1)"
    assert "_pri_default" not in head_src, "HEAD already has fix (2)"
    assert "SetPriorityClass" in head_src, "HEAD does not contain the block at all"

    tmpdir = Path(tempfile.mkdtemp(prefix="cpu_budget_prefix_"))
    backup = tmpdir / "main.py.bak"
    print(f"backup -> {backup}")
    shutil.copy2(MAIN, backup)

    try:
        MAIN.write_text(head_src, encoding="utf-8", newline="")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", GUARD, "-q", "-p", "no:cacheprovider",
             "--no-header", "-rf", "--timeout", "120"],
            cwd=str(ROOT), capture_output=True,
        )
        text = proc.stdout.decode("utf-8", errors="replace")
        print(text[-1500:])
    finally:
        shutil.copy2(backup, MAIN)
        print(f"restored {MAIN} from backup")

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
        [sys.executable, "-m", "pytest", GUARD, "-q", "-p", "no:cacheprovider",
         "--no-header"],
        cwd=str(ROOT), capture_output=True,
    )
    tail = proc2.stdout.decode("utf-8", errors="replace").strip().splitlines()
    print("\npost-restore:", tail[-1] if tail else "(no output)")

    ok = not missing and proc2.returncode == 0
    print("\nRESULT:", "OK - guards fail pre-fix and pass post-fix" if ok else "PROBLEM")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
