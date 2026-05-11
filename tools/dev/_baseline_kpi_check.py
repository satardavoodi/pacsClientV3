"""Quick baseline KPI check for Phase 1A evaluation."""
import re, statistics
from tools.performance.clearcanvas_aipacs_kpi_harness import (
    parse_dm_rebuild_log_text,
    parse_dm_priority_transition_log_text,
)

with open("user_data/logs/download_diagnostics.log", encoding="utf-8", errors="replace") as f:
    text = f.read()

r = parse_dm_rebuild_log_text(text)
t = parse_dm_priority_transition_log_text(text)

sessions = {}
for m in re.finditer(
    r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+).*?pid=(\d+).*?\[DM_REBUILD\] event=exit.*?duration_ms=([\d.]+)",
    text,
):
    pid = m.group(2)
    ts = m.group(1)
    sessions.setdefault(pid, {"durations": [], "first": ts, "last": ts})
    sessions[pid]["durations"].append(float(m.group(3)))
    sessions[pid]["last"] = ts

print("=== DM_REBUILD BASELINE (pre-Phase 1A) ===")
print(f"Total rebuilds      : {r['dm_rebuild_count']}")
print(f"Recursive           : {r['dm_rebuild_recursive_count']} (target=0)")
print(f"Reenter-skip        : {r['dm_rebuild_reenter_skip_count']} (target=0)")
print(f"Max depth           : {r['dm_rebuild_max_depth']} (target=1)")
p50 = r.get("dm_rebuild_duration_p50_ms", 0)
p95 = r.get("dm_rebuild_duration_p95_ms", 0)
mx  = r.get("dm_rebuild_duration_max_ms", 0)
tot = r.get("dm_rebuild_per_session_total_ms", 0)
print(f"p50={p50:.1f}ms  p95={p95:.1f}ms  max={mx:.1f}ms")
print(f"Total blocking      : {tot:.0f}ms  (across all sessions)")
ghost = t.get("priority_combo_signal_during_rebuild_count", 0)
print(f"Ghost signal (G8.1) : {ghost} (target=0)")
print()
print("Per-session breakdown:")
for pid, s in sorted(sessions.items()):
    d = s["durations"]
    p50s = statistics.median(d)
    p95s = sorted(d)[max(0, int(len(d)*0.95)-1)]
    print(f"  pid={pid}  n={len(d):3d}  p50={p50s:6.0f}ms  p95={p95s:6.0f}ms  max={max(d):6.0f}ms  total={sum(d):7.0f}ms  [{s['first'][11:19]} → {s['last'][11:19]}]")

print()
print("=== KPI TARGETS ===")
print(f"  p95 < 80ms   : {'PASS' if p95 < 80 else 'FAIL'}  ({p95:.0f}ms)")
print(f"  max < 200ms  : {'PASS' if mx < 200 else 'FAIL'}  ({mx:.0f}ms)")
print(f"  recursive=0  : {'PASS' if r['dm_rebuild_recursive_count']==0 else 'FAIL'}")
print(f"  ghost=0      : {'PASS' if ghost==0 else 'FAIL'}")
print()
print("NOTE: This log is PRE-Phase 1A (last entry 09:59, changes applied after).")
print("Run the app and perform drag-drop to generate post-Phase 1A data.")
