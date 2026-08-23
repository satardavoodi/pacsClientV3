"""One-off: did yesterday's list-streamer fix actually remove its freeze in the
LIVE app, and what is stalling instead?

Counts, per day, how often each GUI-thread disk path appears in the sampled
stall stacks.  The fix shipped on 2026-08-21 ~15:40 local; sessions from
15:52 onward run it.  Read-only.
"""
import collections
import io
import os
import re
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = r"E:\ai-pacs\ai-pacs codes\ai-pacs beta version"
LOGS = os.path.join(ROOT, "user_data", "logs")

TS = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")

PATHS = {
    "FIXED 2026-08-21: list render -> _resolve_renderable_study_path":
        "_resolve_renderable_study_path",
    "FIXED 2026-08-21: streamer     -> _progressive_render_next":
        "_progressive_render_next",
    "OPEN A: download badge  -> _refresh_statuses_chunked":
        "_refresh_statuses_chunked",
    "OPEN A: download badge  -> _check_study_download_status":
        "_check_study_download_status",
    "OPEN A: download badge  -> sync_manifest":
        "sync_manifest.py",
    "OPEN B: server search   -> _add_socket_patient_to_table":
        "_add_socket_patient_to_table",
    "OPEN B: server search   -> add_data2patient_list_table":
        "add_data2patient_list_table",
    "OPEN C: storage cleanup -> local_storage_cleanup_manager":
        "local_storage_cleanup_manager",
    "OPEN C: storage cleanup -> shutil rmtree":
        "_rmtree_unsafe",
}


def main():
    per_day = collections.defaultdict(collections.Counter)
    totals = collections.Counter()
    for name in sorted(os.listdir(LOGS)):
        if not name.startswith(("app.log", "viewer_diagnostics.log")):
            continue
        with open(os.path.join(LOGS, name), "r", encoding="utf-8",
                  errors="replace") as fh:
            for line in fh:
                if "MAIN_THREAD_STALL_TRACE" not in line:
                    continue
                m = TS.match(line)
                if not m:
                    continue
                day = m.group(1)[:10]
                totals[day] += 1
                for label, needle in PATHS.items():
                    if needle in line:
                        per_day[day][label] += 1

    days = sorted(totals)[-4:]
    print("Sampled stall traces per day: " +
          "  ".join("%s=%d" % (d, totals[d]) for d in days))
    print()
    header = "%-62s" % "path present in the stall stack"
    print(header + "".join("%12s" % d[5:] for d in days))
    print("-" * (62 + 12 * len(days)))
    for label in PATHS:
        row = "".join("%12d" % per_day[d].get(label, 0) for d in days)
        print("%-62s%s" % (label, row))


if __name__ == "__main__":
    main()
