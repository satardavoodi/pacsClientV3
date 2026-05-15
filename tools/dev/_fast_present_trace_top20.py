import re
import json
from pathlib import Path

log_path = Path(r"user_data/logs/viewer_diagnostics.log")
if not log_path.exists():
    raise SystemExit("viewer_diagnostics.log not found")

line_meta_re = re.compile(r"\| action=(?P<action>[^|]+?) \|")
series_re = re.compile(r"series=(?P<series>[^ ]+)")
session_re = re.compile(r"sess-[a-f0-9]+")
kv_re = re.compile(r"([a-zA-Z0-9_]+)=([^ ]+)")

rows = []

with log_path.open('r', encoding='utf-8', errors='replace') as f:
    for raw in f:
        if "[FAST_PRESENT_TRACE] phase=paint_present" not in raw:
            continue

        action = None
        m_action = line_meta_re.search(raw)
        if m_action:
            action = m_action.group('action')
        series = None
        m_series = series_re.search(raw)
        if m_series:
            series = m_series.group('series')
        sess = None
        if action:
            m_sess = session_re.search(action)
            if m_sess:
                sess = m_sess.group(0)

        idx = raw.find("[FAST_PRESENT_TRACE]")
        payload = raw[idx:] if idx >= 0 else raw
        data = {}
        for k, v in kv_re.findall(payload):
            data[k] = v

        def f(name, default=0.0):
            try:
                return float(data.get(name, default))
            except Exception:
                return float(default)
        def i(name, default=0):
            try:
                return int(float(data.get(name, default)))
            except Exception:
                return int(default)
        def s(name, default=""):
            return str(data.get(name, default))
        def b(name, default=False):
            val = str(data.get(name, str(default))).lower()
            return val in ("true", "1", "yes")

        requested = i("requested_slice_index", 0)
        nav = i("navigation_visible_slice_index", 0)
        presented = i("actual_presented_slice_index", 0)
        source = i("source_slice_index", presented)

        req_to_present = f("request_to_present_ms", 0.0)
        frame_ready_to_present = f("frame_ready_to_present_ms", 0.0)
        paint_time = f("paint_time_ms", 0.0)

        row = {
            "request_id": i("request_id", 0),
            "session_id": sess or s("drag_session_id", "-"),
            "series": series or "-",
            "requested_slice_index": requested,
            "navigation_visible_slice_index": nav,
            "actual_presented_slice_index": presented,
            "source_slice_index": source,
            "cache_source": s("cache_source", "-"),
            "cache_hit": b("cache_hit", False),
            "request_to_present_ms": req_to_present,
            "frame_ready_to_paint_ms": frame_ready_to_present,
            "paint_time_ms": paint_time,
            "queue_depth": i("queue_depth", 0),
            "oldest_pending_request_age_ms": f("oldest_pending_age_ms", 0.0),
            "render_clock_tick_id": i("render_clock_tick_id", 0),
            "clock_generation": i("clock_generation", 0),
            "requested_to_presented_slice_delta": abs(requested - presented),
            "requested_to_source_slice_delta": abs(requested - source),
        }

        surrogate = row["cache_source"].startswith("surrogate") or row["requested_to_source_slice_delta"] > 0
        large_qt_delay = row["frame_ready_to_paint_ms"] >= 15.0
        if surrogate and row["requested_to_presented_slice_delta"] > 0:
            cause = "surrogate_mismatch"
        elif large_qt_delay:
            cause = "qt_paint_delay"
        else:
            cause = "normal"
        row["likely_visual_jump_cause"] = cause
        rows.append(row)

if not rows:
    raise SystemExit("No FAST_PRESENT_TRACE paint_present rows found")

rows_sorted = sorted(rows, key=lambda r: r["request_to_present_ms"], reverse=True)
top20 = rows_sorted[:20]

n = len(top20)
surrogate_count = sum(1 for r in top20 if r["cache_source"].startswith("surrogate"))
qt_delay_count = sum(1 for r in top20 if r["frame_ready_to_paint_ms"] >= 15.0)
queue_gt1_count = sum(1 for r in top20 if r["queue_depth"] > 1)
old_pending_gt10_count = sum(1 for r in top20 if r["oldest_pending_request_age_ms"] > 10.0)
render_clock_inactive_count = sum(1 for r in top20 if r["render_clock_tick_id"] == 0 and r["clock_generation"] == 0)

surrogate_jump_count = sum(1 for r in top20 if r["cache_source"].startswith("surrogate") and r["requested_to_presented_slice_delta"] > 0)
pure_qt_delay_count = sum(1 for r in top20 if r["frame_ready_to_paint_ms"] >= 15.0 and r["requested_to_presented_slice_delta"] == 0)

out = {
    "log_path": str(log_path),
    "total_paint_present_rows": len(rows),
    "top20": top20,
    "summary": {
        "top20_count": n,
        "surrogate_usage_count": surrogate_count,
        "qt_delay_ge_15ms_count": qt_delay_count,
        "queue_depth_gt1_count": queue_gt1_count,
        "old_pending_age_gt10ms_count": old_pending_gt10_count,
        "render_clock_inactive_count": render_clock_inactive_count,
        "surrogate_with_presented_mismatch_count": surrogate_jump_count,
        "pure_qt_delay_with_no_presented_mismatch_count": pure_qt_delay_count,
        "top20_request_to_present_ms_max": max(r["request_to_present_ms"] for r in top20),
        "top20_request_to_present_ms_p50": sorted([r["request_to_present_ms"] for r in top20])[n//2],
    }
}

out_path = Path("generated-files/fast_present_trace_top20_latest.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
out_path.write_text(json.dumps(out, indent=2), encoding='utf-8')

print(f"Wrote {out_path}")
print(json.dumps(out["summary"], indent=2))
