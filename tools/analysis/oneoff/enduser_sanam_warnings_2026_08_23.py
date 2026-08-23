"""One-off: what are the 1,360 WARNINGs on 3.6.2, and the full text of the
current-build ERRORs?  Read-only."""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

LOGS = r"C:\Users\Dr.Alizadeh\Desktop\log on other pc\pc user 2 sanam\logs\logs"
CUTOFF = "2026-08-23 00:08:54"          # first run of 3.6.2

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
LEVEL = re.compile(r"\|\s*(WARNING|ERROR|CRITICAL)\s*\|")
LOGGER = re.compile(r"\|\s*component=\S+\s+role=\S+\s*\|\s*([\w.<>_]+)\s*\|")


def ordered(prefix):
    names = [n for n in os.listdir(LOGS) if n.startswith(prefix)]

    def key(n):
        tail = n[len(prefix):].lstrip(".")
        return -int(tail) if tail.isdigit() else 0
    return [os.path.join(LOGS, n) for n in sorted(names, key=key)]


def stream(prefix):
    for path in ordered(prefix):
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                yield line.rstrip("\n")


def main():
    warn = collections.Counter()
    warn_msg = collections.defaultdict(collections.Counter)
    errors = []
    for line in stream("app.log"):
        m = TS.match(line)
        if not m or m.group(1) < CUTOFF:
            continue
        ml = LEVEL.search(line)
        if not ml:
            continue
        mg = LOGGER.search(line)
        who = mg.group(1) if mg else "?"
        body = line.split("result=- |", 1)[-1].strip() if "result=- |" in line \
            else line.split("|")[-1].strip()
        if ml.group(1) == "WARNING":
            warn[who] += 1
            warn_msg[who][re.sub(r"\d{3,}", "N", body)[:120]] += 1
        else:
            errors.append((m.group(1), who, body[:200]))

    print("=" * 82)
    print("3.6.2 WARNINGS BY SOURCE (app.log, since %s)" % CUTOFF)
    print("=" * 82)
    for who, n in warn.most_common(15):
        print("   %5d  %s" % (n, who))
        for msg, k in warn_msg[who].most_common(2):
            print("            %4d x  %s" % (k, msg))

    print()
    print("=" * 82)
    print("3.6.2 ERRORS — full text")
    print("=" * 82)
    for stamp, who, body in errors:
        print("   %s  %s" % (stamp, who))
        print("        %s" % body)


if __name__ == "__main__":
    main()
