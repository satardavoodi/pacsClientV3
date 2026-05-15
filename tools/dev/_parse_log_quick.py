"""Quick log aggregator — run from workspace root."""
import re, sys

log = "user_data/logs/viewer_diagnostics.log"
dl_log = "user_data/logs/download_diagnostics.log"

def tail(path, n=4000):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception as e:
        print(f"  [ERROR reading {path}]: {e}")
        return []

vlines = tail(log)
dlines = tail(dl_log)

# ── Viewer ──────────────────────────────────────────────────────────────
drag = [l for l in vlines if "[FAST_DRAG_KPI]" in l]
stall = [l for l in vlines if "[MAIN_THREAD_STALL]" in l and "TRACE" not in l]
stall_tr = [l for l in vlines if "[MAIN_THREAD_STALL_TRACE]" in l]
dm_reb = [l for l in vlines if "[DM_REBUILD]" in l]
overlap = [l for l in vlines if "[OVERLAP_SCENARIO]" in l]

print(f"=== VIEWER (last 4000 lines) ===")
print(f"  FAST_DRAG_KPI       : {len(drag)}")
print(f"  MAIN_THREAD_STALL   : {len(stall)}")
print(f"  MAIN_THREAD_STALL_TRACE: {len(stall_tr)}")
print(f"  DM_REBUILD          : {len(dm_reb)}")
print(f"  OVERLAP_SCENARIO    : {len(overlap)}")

if drag:
    ev95, uimax, hp95, bgd = [], [], [], 0
    for l in drag:
        m = re.search(r"event_p95=([\d.]+)", l); ev95.append(float(m.group(1))) if m else None
        m = re.search(r"ui_lag_max=([\d.]+)", l); uimax.append(float(m.group(1))) if m else None
        m = re.search(r"handler_p95=([\d.]+)", l); hp95.append(float(m.group(1))) if m else None
        m = re.search(r"bg_decode_total=(\d+)", l); bgd += int(m.group(1)) if m else 0
    if ev95:
        print(f"\n  DRAG AGG: event_p95_avg={sum(ev95)/len(ev95):.1f}ms  "
              f"ui_lag_max={max(uimax):.1f}ms  handler_p95_avg={sum(hp95)/len(hp95):.1f}ms  "
              f"bg_decode_total={bgd}")
        print(f"  Last drag line:\n    {drag[-1].strip()[:220]}")

if stall:
    sv = [float(m.group(1)) for l in stall for m in [re.search(r"stall_ms=([\d.]+)", l)] if m]
    if sv:
        sv.sort()
        p95 = sv[int(len(sv)*0.95)]
        print(f"\n  STALL: count={len(sv)}  p95={p95:.1f}ms  max={max(sv):.1f}ms")
    heavy = [l.strip() for l in stall if float((re.search(r"stall_ms=([\d.]+)", l) or type('', (), {'group': lambda s,x: '0'})()).group(1) or 0) > 200]
    if heavy:
        print(f"  Stalls >200ms ({len(heavy)}):")
        for l in heavy[-5:]: print(f"    {l[:180]}")

if stall_tr:
    print(f"\n  Last 5 STALL_TRACE:")
    for l in stall_tr[-5:]: print(f"    {l.strip()[:200]}")

if dm_reb:
    enter = [l for l in dm_reb if "event=enter" in l]
    reenter = [l for l in dm_reb if "event=reenter_skip" in l]
    exits = [l for l in dm_reb if "event=exit" in l]
    dur = [float(m.group(1)) for l in exits for m in [re.search(r"duration_ms=([\d.]+)", l)] if m]
    print(f"\n  DM_REBUILD: total={len(dm_reb)} enter={len(enter)} reenter_skip={len(reenter)} exit={len(exits)}")
    if dur:
        dur.sort()
        p95 = dur[int(len(dur)*0.95)]
        print(f"  DM_REBUILD dur: p95={p95:.1f}ms  max={max(dur):.1f}ms")

# ── Download ─────────────────────────────────────────────────────────────
intent = [l for l in dlines if "[INTENT_PRIORITY]" in l]
print(f"\n=== DOWNLOAD (last 4000 lines) ===")
print(f"  INTENT_PRIORITY     : {len(intent)}")
if intent:
    exhaust = [l for l in intent if "tag=exhaust" in l]
    started = [l for l in intent if "tag=started" in l]
    print(f"    exhaust={len(exhaust)}  started={len(started)}")
    for l in intent[-3:]: print(f"    {l.strip()[:180]}")

print("\n=== DONE ===")
