"""Prove the A0 guards FAIL on the pre-fix codebase (2026-08-23).

Repo rule: a guard test that passes before the fix guards nothing. Normally we
check that by restoring the file from HEAD -- but that is WRONG here:
``aipacs_runtime.py`` and ``_pw_lifecycle.py`` both carry unrelated uncommitted
work in this tree (389 and 17 lines of it), so ``git show HEAD:`` would revert
far more than the A0 change and the guards would "fail" for the wrong reason.

So this script removes EXACTLY the A0 additions -- anchor-based, and every
anchor is asserted present before anything is written -- runs the two guard
files against that pre-fix state, and restores from backup in a finally.

Read-only with respect to git. Backups go to a temp dir whose path is printed
before any file is touched, so a crash is always recoverable by hand.

Usage:  python tools/analysis/oneoff/verify_close_path_guard_fails_prefix_2026_08_23.py
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

NFL = ROOT / "PacsClient" / "utils" / "native_fault_log.py"
LIFECYCLE = (ROOT / "PacsClient" / "pacs" / "patient_tab" / "ui" / "patient_ui"
             / "patient_widget_core" / "_pw_lifecycle.py")
RUNTIME = ROOT / "aipacs_runtime.py"

GUARDS = [
    "tests/code/system/test_close_path_hang_visibility.py",
    "tests/code/runtime/test_seed_config_once.py",
]

# Guards that must still PASS pre-fix would mean the guard is not pinned to the
# fix at all. We expect every one of these to fail.
EXPECT_FAIL_AT_LEAST = 10


def _cut(text: str, start_anchor: str, end_anchor: str, *, label: str) -> str:
    """Delete [start_anchor, end_anchor) -- both must exist, start before end."""
    i = text.find(start_anchor)
    j = text.find(end_anchor)
    assert i != -1, f"{label}: start anchor not found: {start_anchor!r}"
    assert j != -1, f"{label}: end anchor not found: {end_anchor!r}"
    assert i < j, f"{label}: anchors out of order"
    return text[:i] + text[j:]


def _sub(text: str, old: str, new: str, *, label: str) -> str:
    n = text.count(old)
    assert n == 1, f"{label}: expected exactly 1 occurrence of {old!r}, found {n}"
    return text.replace(old, new)


def prefix_native_fault_log(src: str) -> str:
    lbl = "native_fault_log"
    src = _sub(src, "import contextlib\n", "", label=lbl)
    src = _sub(src, "from typing import Iterator, Optional",
               "from typing import Optional", label=lbl)
    src = _cut(
        src,
        "\nAlso provides :func:`hang_watchdog` (A0, 2026-08-23)",
        "\nINVARIANTS\n",
        label=lbl,
    )
    # Everything from reset_for_tests onward is A0-modified; restore the original.
    i = src.index("def reset_for_tests() -> None:")
    return src[:i] + (
        'def reset_for_tests() -> None:\n'
        '    """Test hook: forget the handle so a test can re-enable into a tmp dir."""\n'
        "    global _handle\n"
        "    _handle = None\n"
    )


def prefix_lifecycle(src: str) -> str:
    lbl = "_pw_lifecycle"
    src = _cut(
        src,
        "# ── A0: make the close path visible (2026-08-23) ─",
        "def _run_deferred_close_gc():",
        label=lbl,
    )
    src = _cut(
        src,
        "def _run_deferred_close_gc():",
        "def _schedule_deferred_close_gc():",
        label=lbl,
    )
    src = _sub(
        src,
        "def _schedule_deferred_close_gc():",
        "def _run_deferred_close_gc():\n"
        "    _CLOSE_GC_PENDING[0] = False\n"
        "    try:\n"
        "        gc.collect()\n"
        "    except Exception:\n"
        "        pass\n"
        "\n"
        "\n"
        "def _schedule_deferred_close_gc():",
        label=lbl,
    )
    # Collapse the wrapper back into the original single method.
    i = src.index("    def exit_patient_widget(self):")
    j = src.index("    def _exit_patient_widget_impl(self):")
    assert i < j, f"{lbl}: wrapper/impl out of order"
    return (src[:i]
            + '    def exit_patient_widget(self):\n'
              '        """تمام resources را با سرعت تمیز کن"""\n'
            + src[j + len("    def _exit_patient_widget_impl(self):\n"):])


def prefix_runtime(src: str) -> str:
    lbl = "aipacs_runtime"
    src = _cut(
        src,
        "# ── A0 (2026-08-23): seed once per (src, dst), not once per caller ─",
        "def seed_user_config_defaults() -> None:",
        label=lbl,
    )
    src = _cut(
        src,
        "\n    _seed_key = (str(src_root), str(dst_root))",
        "\n    if not src_root.exists():",
        label=lbl,
    )
    src = _cut(
        src,
        "\n    # Recorded only after a COMPLETE pass",
        "\n\n# ── Versioned user-config migration",
        label=lbl,
    )
    return src


PLAN = [
    (NFL, prefix_native_fault_log),
    (LIFECYCLE, prefix_lifecycle),
    (RUNTIME, prefix_runtime),
]


def main() -> int:
    # Wrapped here, not at import: this module is also imported by
    # check_a0_regression_delta_2026_08_23.py, and re-wrapping sys.stdout at
    # import time closes the caller's wrapper out from under it.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    backup_dir = Path(tempfile.mkdtemp(prefix="a0_prefix_backup_"))
    print(f"backups -> {backup_dir}")

    # Compute every pre-fix variant BEFORE writing anything, so a bad anchor
    # aborts with the tree untouched.
    staged = []
    for path, transform in PLAN:
        original = path.read_text(encoding="utf-8")
        modified = transform(original)
        assert modified != original, f"{path.name}: transform was a no-op"
        staged.append((path, original, modified))
        print(f"  computed pre-fix {path.name}: "
              f"{len(original)} -> {len(modified)} chars")

    failed = 0
    try:
        for path, original, modified in staged:
            shutil.copy2(path, backup_dir / path.name)
            path.write_text(modified, encoding="utf-8")
        print("\n--- running guards against the PRE-FIX tree ---")
        proc = subprocess.run(
            # Do NOT disable rerunfailures: pyproject's addopts pass --reruns,
            # and pytest rejects the option if the plugin is unloaded.
            [sys.executable, "-m", "pytest", *GUARDS, "-q", "-p", "no:randomly",
             "--no-header", "--tb=no"],
            cwd=str(ROOT), capture_output=True, text=True, errors="replace",
        )
        out = proc.stdout + proc.stderr
        print(out[-4000:])
        # Count distinct FAILED/ERROR lines; reruns repeat a test, they do not
        # add one, and an import-time collapse shows up as errors not failures.
        failed = len({
            line.split(" ")[1].split("[")[0]
            for line in out.splitlines()
            if line.startswith("FAILED ") or line.startswith("ERROR ")
        })
        match = re.search(r"(\d+) (?:failed|error)", out)
        if match:
            print(f"\nSUMMARY: {match.group(0)}")
    finally:
        for path, original, _ in staged:
            path.write_text(original, encoding="utf-8")
        print(f"\nrestored {len(staged)} files from memory; backups kept at {backup_dir}")

    print(f"\nguard tests failing pre-fix: {failed} (need >= {EXPECT_FAIL_AT_LEAST})")
    ok = failed >= EXPECT_FAIL_AT_LEAST
    print("RESULT:", "PASS - the guards are pinned to the fix" if ok
          else "FAIL - guards do not discriminate; they guard nothing")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
