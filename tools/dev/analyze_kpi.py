#!/usr/bin/env python3
"""Extract and analyze FAST_DRAG_KPI metrics from diagnostic log."""

import sys
from pathlib import Path

log_file = Path("user_data/logs/viewer_diagnostics.log")
if not log_file.exists():
    print(f"❌ Log file not found: {log_file}")
    sys.exit(1)

kpis = []
with open(log_file) as f:
    for line in f:
        if '[FAST_DRAG_KPI]' in line:
            try:
                data = {}
                for part in line.split():
                    if '=' in part:
                        k, v = part.split('=', 1)
                        try:
                            data[k] = float(v)
                        except ValueError:
                            data[k] = v
                if 'event_p95_ms' in data:
                    kpis.append(data)
            except Exception as e:
                print(f"⚠️ Parse error: {e}", file=sys.stderr)

print(f"\n[KPI] FAST_DRAG_KPI Analysis ({len(kpis)} entries)\n")
print("| # | event_p95 | handler_p95 | ui_lag_max | prefetch/s | bg_decode | paint | status |")
print("|---|-----------|-------------|------------|-----------|-----------|-------|--------|")

for i, d in enumerate(kpis, 1):
    ep95 = d.get('event_p95_ms', 0)
    hp95 = d.get('handler_p95_ms', 0)
    lag = d.get('ui_lag_max_ms', 0)
    prefetch = d.get('prefetch_per_s', 0)
    bg_decode = int(d.get('background_decode_count', 0))
    paint = int(d.get('paint_count', 0))
    
    if ep95 < 50:
        status = "✅ Good"
    elif ep95 < 100:
        status = "⚠️  Warn"
    elif ep95 < 200:
        status = "❌ Bad"
    else:
        status = "💥 Critical"
    
    print(f"|{i:2d}| {ep95:7.1f}ms | {hp95:9.1f}ms | {lag:8.1f}ms | {prefetch:9.1f} | {bg_decode:7d} | {paint:4d} | {status} |")

print("\n🔍 Key Observations:")
print(f"• Baseline event_p95: {kpis[0].get('event_p95_ms', 0):.1f}ms")
print(f"• Final event_p95: {kpis[-1].get('event_p95_ms', 0):.1f}ms")
print(f"• Degradation: {(kpis[-1].get('event_p95_ms', 0) / max(0.1, kpis[0].get('event_p95_ms', 1))):.1f}× worse")
print(f"• Handler p95 (all): {[d.get('handler_p95_ms', 0) for d in kpis]}")
print(f"• Pattern: {'PROGRESSIVE' if kpis[-1].get('event_p95_ms', 0) > kpis[0].get('event_p95_ms', 0) else 'STABLE'}")
