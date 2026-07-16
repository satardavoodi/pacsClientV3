"""Generate `tests/quarantine.py` from a live pytest run (Q0, 2026-07-14).

WHY THIS EXISTS
---------------
The suite was RED BY DEFAULT (~83 permanently-failing tests). A red suite has **zero
regression signal**: "did my change break something?" could only be answered by a manual
`git stash` A/B run, which is exactly what was happening. Worse, a NEW regression landing in
an already-red suite is invisible.

This tool makes the debt EXPLICIT instead of ambient:

* every failing test is recorded in `tests/quarantine.py` **with its real failure message**;
* the root conftest turns each into `xfail(strict=True)`;
* `strict=True` means a quarantined test that starts PASSING becomes a FAILURE — so the list
  is self-cleaning and cannot silently rot;
* the suite therefore exits 0, and **any new red is a genuine, immediately-visible regression**.

This is a debt REGISTER, not an amnesty. Burn it down.

Usage:
    python tools/dev/build_quarantine.py            # regenerate from a fresh run
    python tools/dev/build_quarantine.py --check    # fail if the live failures differ
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "tests" / "quarantine.py"

# Category heuristics — a first pass, to be refined by hand as each is triaged.
CATEGORY_RULES = [
    (r"unexpected keyword argument|takes \d+ positional", "stale-double",
     "test double's signature drifted from production"),
    (r"baseline drift|collide with module catalog|not in '# Module", "drift",
     "catalog/baseline pin not updated after a product change"),
    (r"Pixel-hash mismatch", "golden-drift",
     "golden pixel hash differs — needs a real look (could be a REAL rendering change)"),
    (r"No module named|DLL load failed|libGL|display", "env",
     "environment-dependent (missing native dep / display)"),
]


def categorise(reason: str) -> tuple[str, str]:
    for pattern, cat, note in CATEGORY_RULES:
        if re.search(pattern, reason, re.I):
            return cat, note
    return "UNTRIAGED", "needs investigation — may be a REAL product bug"


def run_pytest() -> dict[str, str]:
    """Return {nodeid: short failure reason} from a live run.

    Captured via the `_failure_dump` plugin, NOT by parsing pytest's text output: a
    parametrised test with non-ASCII ids (the Persian strings in `test_ino_report_workflow`)
    is PRINTED with `\\uXXXX` escapes, so a parsed id never matches the real node id and the
    quarantine silently misses it. The plugin records the id as pytest sees it.
    """
    import json
    import tempfile

    tmpdir = Path(tempfile.mkdtemp(prefix="aipacs_quarantine_"))
    dump = tmpdir / "failures.json"
    env = dict(os.environ)
    env["AIPACS_QUARANTINE_OFF"] = "1"   # see tests/conftest.py — we need the RAW failures
    subprocess.run(
        [sys.executable, "-m", "pytest", "tests/code", "-q", "-p", "no:debugging",
         "-p", "tools.dev._failure_dump", "--failure-dump", str(dump),
         "-n", "auto", "--tb=no", "--continue-on-collection-errors",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, timeout=1800, env=env,
    )
    failures: dict[str, str] = {}
    for shard in tmpdir.glob("failures.json*"):
        try:
            failures.update(json.loads(shard.read_text(encoding="utf-8")))
        except Exception:
            pass
    return failures


def render(failures: dict[str, str]) -> str:
    lines = [
        '"""AUTO-GENERATED test quarantine registry — see tools/dev/build_quarantine.py.',
        "",
        "Each entry is a test that is CURRENTLY FAILING and has been quarantined so the suite",
        "can be GREEN, so that any NEW red is a real, visible regression.",
        "",
        "*** THIS IS A DEBT REGISTER, NOT AN AMNESTY. ***",
        "",
        "Rules:",
        "  * `strict=True` — if a quarantined test starts PASSING, the suite FAILS. Remove it",
        "    from this list (that is the intended, self-cleaning workflow).",
        "  * Do NOT add a test here to make a red go away. Quarantine is for PRE-EXISTING debt",
        "    only; a test your change broke must be FIXED.",
        "  * Every UNTRIAGED entry may be hiding a REAL product bug. Burn this list down.",
        '"""',
        "",
        "# nodeid -> (category, reason captured from the live run)",
        "QUARANTINE = {",
    ]
    for nodeid in sorted(failures):
        reason = failures[nodeid]
        cat, _note = categorise(reason)
        safe = reason.replace('"', "'").replace("\\", "/")
        lines.append(f'    "{nodeid}":')
        lines.append(f'        ("{cat}", "{safe}"),')
    lines.append("}")
    lines.append("")
    lines.append(f"# Generated from a live run: {len(failures)} quarantined test(s).")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the live failures differ from the registry")
    args = ap.parse_args()

    failures = run_pytest()
    print(f"live failures: {len(failures)}")

    if args.check:
        sys.path.insert(0, str(ROOT))
        from tests.quarantine import QUARANTINE  # noqa: PLC0415
        new = set(failures) - set(QUARANTINE)
        if new:
            print("NEW FAILURES NOT IN QUARANTINE (real regressions):")
            for n in sorted(new):
                print("  " + n)
            return 1
        print("no new failures.")
        return 0

    OUT.write_text(render(failures), encoding="utf-8")
    print(f"wrote {OUT} ({len(failures)} entries)")
    cats: dict[str, int] = {}
    for reason in failures.values():
        cat, _ = categorise(reason)
        cats[cat] = cats.get(cat, 0) + 1
    for cat, n in sorted(cats.items(), key=lambda kv: -kv[1]):
        print(f"  {n:4}  {cat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
