#!/usr/bin/env python3
"""
process_soak_sampler.py - live per-cycle resource sampler for AI-PACS soak testing.

Attach this to the RUNNING AI-PACS source build (the python.exe instance) while
you drive the repeated workflow (click patient -> download -> open -> view ->
close, repeat). It samples RSS / threads / handles / child-process count on an
interval and, on exit, prints whether the process is leaking and how much per
cycle. No app code changes required.

Typical use (human-assisted; run in a second terminal on Windows):
  1. Launch AI-PACS from VS Code (source build) and note its PID
     (or let --name find the python.exe running main.py).
  2. python tools/reliability/process_soak_sampler.py --name python --csv soak.csv --cycles-from-stdin
  3. Do one open/view/close cycle, press Enter (marks cycle 1), repeat N times.
  4. Press Ctrl-C to stop -> prints the leak verdict + per-cycle growth.

Options:
  --pid PID            attach to an explicit PID
  --name SUBSTR        attach to the first process whose name/cmdline contains SUBSTR
  --interval SECONDS   sample period (default 3.0)
  --duration SECONDS   auto-stop after N seconds (default: until Ctrl-C)
  --csv PATH           write per-sample CSV
  --cycles-from-stdin  press Enter in the terminal to mark the end of each cycle
  --leak-mb-per-cycle  per-cycle RSS growth (MB) above which we flag a leak (default 8)
"""
from __future__ import annotations
import argparse, csv, sys, threading, time
from datetime import datetime

try:
    import psutil
except ImportError:
    print("psutil is required (pip install psutil).", file=sys.stderr); sys.exit(2)


def find_pid(name_substr):
    name_substr = name_substr.lower()
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            nm = (proc.info.get("name") or "").lower()
            cl = " ".join(proc.info.get("cmdline") or []).lower()
            if name_substr in nm or name_substr in cl:
                # prefer a process whose cmdline references main.py / aipacs
                if "main.py" in cl or "aipacs" in cl or name_substr in nm:
                    return proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def sample(proc):
    rec = {"rss_mb": None, "threads": None, "handles": None, "children": None, "cpu": None}
    try:
        rec["rss_mb"] = round(proc.memory_info().rss / (1024 * 1024), 1)
    except Exception:
        pass
    try:
        rec["threads"] = proc.num_threads()
    except Exception:
        pass
    try:
        rec["handles"] = proc.num_handles() if hasattr(proc, "num_handles") else proc.num_fds()
    except Exception:
        pass
    try:
        rec["children"] = len(proc.children(recursive=True))
    except Exception:
        pass
    try:
        rec["cpu"] = proc.cpu_percent()
    except Exception:
        pass
    return rec


def main():
    ap = argparse.ArgumentParser(description="AI-PACS live per-cycle resource sampler")
    ap.add_argument("--pid", type=int)
    ap.add_argument("--name", default=None)
    ap.add_argument("--interval", type=float, default=3.0)
    ap.add_argument("--duration", type=float, default=None)
    ap.add_argument("--csv", default=None)
    ap.add_argument("--cycles-from-stdin", action="store_true")
    ap.add_argument("--leak-mb-per-cycle", type=float, default=8.0)
    a = ap.parse_args()

    pid = a.pid or (find_pid(a.name) if a.name else None)
    if not pid:
        print("Could not find target process. Pass --pid or --name.", file=sys.stderr); sys.exit(2)
    try:
        proc = psutil.Process(pid)
    except psutil.NoSuchProcess:
        print(f"No process with PID {pid}.", file=sys.stderr); sys.exit(2)
    print(f"Sampling PID {pid} ({proc.name()}) every {a.interval}s. Ctrl-C to stop.")
    try:
        proc.cpu_percent()  # prime cpu_percent
    except Exception:
        pass

    cycle = {"n": 0}
    if a.cycles_from_stdin:
        def _reader():
            for _ in sys.stdin:
                cycle["n"] += 1
                print(f"  -- marked cycle {cycle['n']} --")
        threading.Thread(target=_reader, daemon=True).start()
        print("  (press Enter after each open/view/close cycle to mark it)")

    rows, cycle_rss = [], {}   # cycle_rss: cycle_index -> last rss seen in that cycle
    writer = fcsv = None
    if a.csv:
        fcsv = open(a.csv, "w", newline="", encoding="utf-8")
        writer = csv.writer(fcsv)
        writer.writerow(["wall", "elapsed_s", "cycle", "rss_mb", "threads", "handles", "children", "cpu_pct"])

    t0 = time.time()
    baseline = None
    try:
        while True:
            if not proc.is_running():
                print("\n[!] Target process exited (possible crash/fail-fast).")
                break
            r = sample(proc)
            el = round(time.time() - t0, 1)
            if baseline is None and r["rss_mb"] is not None:
                baseline = r
            rows.append((el, cycle["n"], r))
            if r["rss_mb"] is not None:
                cycle_rss[cycle["n"]] = r["rss_mb"]
            if writer:
                writer.writerow([datetime.now().isoformat(timespec="seconds"), el, cycle["n"],
                                 r["rss_mb"], r["threads"], r["handles"], r["children"], r["cpu"]])
                fcsv.flush()
            print(f"  t={el:>7}s cyc={cycle['n']:>3} rss={r['rss_mb']}MB "
                  f"thr={r['threads']} hnd={r['handles']} child={r['children']} cpu={r['cpu']}%")
            if a.duration and (time.time() - t0) >= a.duration:
                break
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print("\nStopping (Ctrl-C).")
    finally:
        if fcsv: fcsv.close()

    # summary / verdict
    last = rows[-1][2] if rows else None
    print("\n" + "=" * 60 + "\nSOAK SUMMARY\n" + "=" * 60)
    if baseline and last and baseline["rss_mb"] and last["rss_mb"]:
        net = last["rss_mb"] - baseline["rss_mb"]
        print(f"RSS:     {baseline['rss_mb']} -> {last['rss_mb']} MB   (net {net:+.1f} MB)")
        if baseline["threads"] is not None and last["threads"] is not None:
            print(f"Threads: {baseline['threads']} -> {last['threads']}   (net {last['threads']-baseline['threads']:+d})")
        if baseline["handles"] is not None and last["handles"] is not None:
            print(f"Handles: {baseline['handles']} -> {last['handles']}   (net {last['handles']-baseline['handles']:+d})")
        ncyc = cycle["n"]
        if ncyc >= 2:
            per = net / ncyc
            verdict = "LEAK SUSPECTED" if per > a.leak_mb_per_cycle else "OK"
            print(f"Cycles marked: {ncyc} | per-cycle RSS growth: {per:+.1f} MB/cycle -> {verdict}")
            print(f"(threshold {a.leak_mb_per_cycle} MB/cycle; a healthy loop returns near baseline after close)")
        else:
            verdict = "LEAK SUSPECTED" if net > 150 else "inconclusive (mark cycles for a per-cycle verdict)"
            print(f"Net growth verdict: {verdict}")
    else:
        print("Insufficient samples for a verdict.")
    if a.csv:
        print(f"Per-sample CSV: {a.csv}")


if __name__ == "__main__":
    main()
