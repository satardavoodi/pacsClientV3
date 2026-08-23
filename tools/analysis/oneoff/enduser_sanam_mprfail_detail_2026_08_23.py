"""One-off: which of the 12 MPR oblique checks is failing on 3.6.2?

The validator logs a multi-line record: a summary line, then one indented
"FAIL <view>.<check>: val=… thr=… — message" per failure.
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"
FAIL = re.compile(r"FAIL\s+([\w.]+):\s*val=([-\d.]+)\s*thr=([-\d.]+)\s*[—-]\s*(.*)")


def ordered(prefix):
    names = [n for n in os.listdir(LOGS) if n.startswith(prefix)]

    def key(n):
        t = n[len(prefix):].lstrip(".")
        return -int(t) if t.isdigit() else 0
    return [os.path.join(LOGS, n) for n in sorted(names, key=key)]


def main():
    checks = collections.Counter()
    samples = {}
    total = 0
    for prefix in ("app.log", "viewer_diagnostics.log"):
        for path in ordered(prefix):
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = FAIL.search(line)
                    if not m:
                        continue
                    total += 1
                    key = m.group(1)
                    checks[key] += 1
                    if key not in samples:
                        samples[key] = (m.group(2), m.group(3), m.group(4).strip()[:150])
    print("FAIL detail lines found: %d" % total)
    print()
    for key, n in checks.most_common(20):
        val, thr, msg = samples[key]
        print("   %6d  %-34s val=%-10s thr=%-8s %s" % (n, key, val, thr, msg))


if __name__ == "__main__":
    main()
