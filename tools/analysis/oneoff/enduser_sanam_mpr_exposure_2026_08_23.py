"""A1 sanity check: is "0 MPR_DIAG failures on 3.5.9" a PASS or an ABSENCE? (2026-08-23)

The stability review reported 1 175 `[MPR_DIAG] ... FAILED` lines on 3.6.2 and
zero on 3.5.9, and read that as a regression. That reading is only valid if the
validator RAN on 3.5.9 and said PASS. If 3.5.9 simply never exercised the code
path -- MPR never opened, or oblique never engaged -- then "zero" means "not
measured" and there is no regression to chase.

Same trap as always: absence of evidence is not evidence of absence.

Counts per session: MPR opens, MPR_DIAG PASS vs FAILED, and which checks. Reads
rotated logs OLDEST FIRST (.3, .2, .1, base) -- name order corrupts the
first/last timestamps of a session.

Usage:  python tools/analysis/oneoff/enduser_sanam_mpr_exposure_2026_08_23.py
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = Path(r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs")

# From the review's version timeline (auto_update.log).
VERSION_AT = [
    ("2026-08-23 00:08:54", "3.6.2"),
    ("2026-08-22 21:56:00", "3.6.1"),
    ("2026-08-10 10:57:00", "3.5.9"),
    ("2026-08-02 21:46:00", "3.5.7"),
    ("2026-07-27 14:46:00", "3.5.6"),
]

TS = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})")
PID = re.compile(r"\bpid[=:\s]+(\d+)", re.I)


def version_for(ts: str) -> str:
    norm = ts.replace("T", " ")
    for cutoff, ver in VERSION_AT:
        if norm >= cutoff:
            return ver
    return "pre-3.5.6"


def ordered(stem: str) -> list[Path]:
    """Rotated logs oldest first: .3, .2, .1, then the live file."""
    out = []
    for suffix in ("3", "2", "1"):
        p = LOGS / f"{stem}.{suffix}"
        if p.exists():
            out.append(p)
    base = LOGS / stem
    if base.exists():
        out.append(base)
    return out


def main() -> int:
    if not LOGS.exists():
        print(f"log folder not found: {LOGS}")
        return 2

    files = []
    for stem in ("app.log", "viewer_diagnostics.log"):
        files.extend(ordered(stem))
    if not files:
        print("no app.log / viewer_diagnostics.log found")
        print("present:", sorted(p.name for p in LOGS.iterdir())[:40])
        return 2

    per_ver_open = Counter()
    per_ver_pass = Counter()
    per_ver_fail = Counter()
    per_ver_lines = Counter()
    per_ver_oblique = Counter()
    fail_checks = defaultdict(Counter)
    pass_checks = defaultdict(Counter)
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}

    for path in files:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = TS.search(line)
                if not m:
                    continue
                ver = version_for(m.group(1))
                per_ver_lines[ver] += 1
                first_seen.setdefault(ver, m.group(1))
                last_seen[ver] = m.group(1)

                if "MPR VIEWER INITIALIZATION STARTED" in line.upper():
                    per_ver_open[ver] += 1
                low = line.lower()
                if "oblique" in low:
                    per_ver_oblique[ver] += 1

                if "[MPR_DIAG]" not in line:
                    continue
                check = ""
                cm = re.search(r"(\w+\.\w+)\s", line.split("[MPR_DIAG]")[-1])
                if cm:
                    check = cm.group(1)
                if "FAILED" in line:
                    per_ver_fail[ver] += 1
                    if check:
                        fail_checks[ver][check] += 1
                elif "PASS" in line.upper():
                    per_ver_pass[ver] += 1
                    if check:
                        pass_checks[ver][check] += 1

    print(f"read {len(files)} files: {[p.name for p in files]}\n")
    header = f"{'ver':<10} {'lines':>9} {'mpr_open':>9} {'oblique':>8} {'DIAG_PASS':>10} {'DIAG_FAIL':>10}"
    print(header)
    print("-" * len(header))
    for ver in sorted(per_ver_lines, key=lambda v: first_seen.get(v, "")):
        print(f"{ver:<10} {per_ver_lines[ver]:>9} {per_ver_open[ver]:>9} "
              f"{per_ver_oblique[ver]:>8} {per_ver_pass[ver]:>10} {per_ver_fail[ver]:>10}")
        print(f"{'':<10} window {first_seen.get(ver,'?')} -> {last_seen.get(ver,'?')}")

    print("\nFAILED checks by version:")
    for ver, counts in fail_checks.items():
        print(f"  {ver}: {counts.most_common(8)}")
    print("\nPASSED checks by version:")
    for ver, counts in pass_checks.items():
        print(f"  {ver}: {counts.most_common(8)}")

    print("\n--- verdict ---")
    for ver in ("3.5.9", "3.6.1", "3.6.2"):
        p, f, o = per_ver_pass[ver], per_ver_fail[ver], per_ver_open[ver]
        if p == 0 and f == 0:
            note = ("NOT MEASURED - the validator produced nothing on this build, "
                    f"so 'zero failures' says nothing. MPR opens seen: {o}")
        elif f == 0:
            note = f"MEASURED AND CLEAN - {p} passes, 0 failures"
        else:
            note = f"{f} failures against {p} passes"
        print(f"  {ver}: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
