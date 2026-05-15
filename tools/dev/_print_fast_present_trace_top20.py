import json
from pathlib import Path

p = Path("generated-files/fast_present_trace_top20_latest.json")
obj = json.loads(p.read_text(encoding='utf-8'))
rows = obj["top20"]

headers = [
    "rank","request_id","session_id","series","req","nav","presented","source",
    "cache_source","cache_hit","req2present_ms","frameReady2paint_ms","paint_ms",
    "q_depth","oldest_age_ms","tick_id","clock_gen","delta_req_presented","delta_req_source","jump_cause"
]

print("\t".join(headers))
for idx, r in enumerate(rows, 1):
    print("\t".join([
        str(idx),
        str(r.get("request_id", "")),
        str(r.get("session_id", "")),
        str(r.get("series", "")),
        str(r.get("requested_slice_index", "")),
        str(r.get("navigation_visible_slice_index", "")),
        str(r.get("actual_presented_slice_index", "")),
        str(r.get("source_slice_index", "")),
        str(r.get("cache_source", "")),
        str(r.get("cache_hit", "")),
        f"{float(r.get('request_to_present_ms',0.0)):.3f}",
        f"{float(r.get('frame_ready_to_paint_ms',0.0)):.3f}",
        f"{float(r.get('paint_time_ms',0.0)):.3f}",
        str(r.get("queue_depth", "")),
        f"{float(r.get('oldest_pending_request_age_ms',0.0)):.3f}",
        str(r.get("render_clock_tick_id", "")),
        str(r.get("clock_generation", "")),
        str(r.get("requested_to_presented_slice_delta", "")),
        str(r.get("requested_to_source_slice_delta", "")),
        str(r.get("likely_visual_jump_cause", "")),
    ]))
