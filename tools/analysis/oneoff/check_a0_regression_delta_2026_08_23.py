"""Did the A0 change break these 11 tests, or were they already broken? (2026-08-23)

The A0 sweep over tests/code/{system,runtime,utils,builder} ended
``11 failed, 580 passed``. Eleven failures is not a result until we know whether
they are OURS. This repo has burned time on that question before (the four
``test_b41_*`` failures on 2026-08-22 turned out to be pre-existing run-order
pollution), so the answer has to be measured, not argued.

Method: run exactly the same file set twice -- once as the tree stands, once
with ONLY the A0 additions removed (reusing the anchor-based transforms from
``verify_close_path_guard_fails_prefix_2026_08_23.py``; a blanket
``git show HEAD:`` would revert 389 lines of unrelated uncommitted work) -- and
diff the two failure sets. Anything in both was already broken.

The two A0 guard files are excluded from the comparison: they do not exist in
the pre-fix world, so including them would just add 26 known failures.

Usage:  python tools/analysis/oneoff/check_a0_regression_delta_2026_08_23.py
"""

from __future__ import annotations

import importlib.util
import io
import re
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[3]
_VERIFY = Path(__file__).with_name("verify_close_path_guard_fails_prefix_2026_08_23.py")

SUSPECTS = [
    "tests/code/system/test_local_search_progressive.py",
    "tests/code/builder/test_nuitka_arm64_parity.py",
    "tests/code/builder/test_release_parity_guards.py",
]


def _load_verify():
    spec = importlib.util.spec_from_file_location("_a0_verify", _VERIFY)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run() -> set[str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *SUSPECTS, "-q", "-p", "no:randomly",
         "--no-header", "--tb=no"],
        cwd=str(ROOT), capture_output=True, text=True, errors="replace",
    )
    out = proc.stdout + proc.stderr
    tail = re.search(r"^\d+ (?:failed|passed).*$", out, re.M)
    print("   ", tail.group(0) if tail else "(no summary line)")
    return {
        line.split(" ")[1].split("[")[0]
        for line in out.splitlines()
        if line.startswith("FAILED ") or line.startswith("ERROR ")
    }


def main() -> int:
    verify = _load_verify()

    print("run 1: tree as it stands (A0 applied)")
    with_fix = _run()

    staged = []
    for path, transform in verify.PLAN:
        original = path.read_text(encoding="utf-8")
        staged.append((path, original, transform(original)))

    try:
        for path, _, modified in staged:
            path.write_text(modified, encoding="utf-8")
        print("run 2: A0 additions removed")
        without_fix = _run()
    finally:
        for path, original, _ in staged:
            path.write_text(original, encoding="utf-8")
        print("    (restored)")

    pre_existing = with_fix & without_fix
    caused = with_fix - without_fix
    healed = without_fix - with_fix

    print(f"\npre-existing (fail both ways): {len(pre_existing)}")
    for name in sorted(pre_existing):
        print(f"    {name}")
    print(f"\nCAUSED BY A0 (fail only with the fix): {len(caused)}")
    for name in sorted(caused):
        print(f"    {name}")
    if healed:
        print(f"\nfixed by A0 (failed only without it): {len(healed)}")
        for name in sorted(healed):
            print(f"    {name}")

    print("\nRESULT:", "PASS - A0 caused no regression" if not caused
          else "FAIL - A0 broke the tests listed above")
    return 0 if not caused else 1


if __name__ == "__main__":
    raise SystemExit(main())
