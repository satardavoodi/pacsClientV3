"""One-off: print the COMPLETE sampled stack of the worst server-search stall,
so the glob() caller is identified rather than guessed."""
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOGS = os.path.join(ROOT, "user_data", "logs")
TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
GAP = re.compile(r"gap_ms=([\d.]+)")
FRAME = re.compile(r'File "([^"]+)", line (\d+), in (\S+)')


def short(path):
    p = path.replace(ROOT.lower(), "").replace(ROOT, "")
    return p.lstrip("\\/").replace("\\", "/")


def main():
    best = []
    for name in sorted(os.listdir(LOGS)):
        if not name.startswith(("app.log", "viewer_diagnostics.log")):
            continue
        with open(os.path.join(LOGS, name), "r", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                if "MAIN_THREAD_STALL_TRACE" not in line:
                    continue
                m = TS.match(line)
                if not m or not m.group(1).startswith("2026-08-22"):
                    continue
                if "_add_socket_patient_to_table" not in line:
                    continue
                g = GAP.search(line)
                best.append((float(g.group(1)) if g else 0.0, m.group(1),
                             FRAME.findall(line)))
    best.sort(reverse=True)
    print("matching traces: %d" % len(best))
    for gap, ts, frames in best[:3]:
        print()
        print("== %s  gap=%.0f ms  (%d frames) ==" % (ts, gap, len(frames)))
        for p, l, fn in frames:
            print("   %-70s:%-6s %s" % (short(p), l, fn))


if __name__ == "__main__":
    main()
