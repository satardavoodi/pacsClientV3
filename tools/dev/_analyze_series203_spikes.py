import re
from pathlib import Path
from datetime import datetime, timedelta

VIEWER_LOG = Path("user_data/logs/viewer_diagnostics.log")
DOWNLOAD_LOG = Path("user_data/logs/download_diagnostics.log")

TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{6})")
FLOAT_RE = re.compile(r"([a-zA-Z0-9_]+)=(-?\d+(?:\.\d+)?)")
BOOL_RE = re.compile(r"([a-zA-Z0-9_]+)=(True|False)")
STR_RE = re.compile(r"([a-zA-Z0-9_]+)=([^\s|]+)")


def parse_ts(line):
    m = TS_RE.match(line)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S.%f")


def parse_kv(line):
    d = {}
    for k, v in STR_RE.findall(line):
        d[k] = v
    for k, v in FLOAT_RE.findall(line):
        try:
            d[k] = float(v)
        except Exception:
            pass
    for k, v in BOOL_RE.findall(line):
        d[k] = (v == "True")
    return d


def read_lines(path):
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="ignore").splitlines()


vlines = read_lines(VIEWER_LOG)
dlines = read_lines(DOWNLOAD_LOG)

# Parse relevant viewer events
fast_drag = []
fast_pacing_by_id = {}
fg_by_drag_id = {}
stall_events = []
progressive_events = []

for ln in vlines:
    ts = parse_ts(ln)
    if ts is None:
        continue

    if "series=203" in ln and "[FAST_DRAG_KPI]" in ln:
        kv = parse_kv(ln)
        fast_drag.append({"ts": ts, "line": ln, "kv": kv})

    if "series=203" in ln and "[FAST_EVENT_PACING]" in ln:
        kv = parse_kv(ln)
        dsid = kv.get("drag_session_id")
        if dsid:
            fast_pacing_by_id[dsid] = {"ts": ts, "line": ln, "kv": kv}

    if "series=203" in ln and "[FAST_FG_DISK]" in ln:
        kv = parse_kv(ln)
        dsid = kv.get("drag_session_id")
        if dsid:
            fg_by_drag_id.setdefault(dsid, []).append({"ts": ts, "line": ln, "kv": kv})

    if "[MAIN_THREAD_STALL]" in ln:
        kv = parse_kv(ln)
        stall_events.append({"ts": ts, "line": ln, "kv": kv})

    if "series=203" in ln and ("[PROGRESSIVE_GROW_SPLIT]" in ln or "[RETRO_META_SYNC_" in ln):
        kv = parse_kv(ln)
        progressive_events.append({"ts": ts, "line": ln, "kv": kv})

# Parse DM_REBUILD from download log
dm_rebuild = []
for ln in dlines:
    ts = parse_ts(ln)
    if ts is None:
        continue
    if "series=203" in ln and "[DM_REBUILD]" in ln:
        kv = parse_kv(ln)
        dm_rebuild.append({"ts": ts, "line": ln, "kv": kv})


def nearest(events, target_ts):
    if not events:
        return None
    return min(events, key=lambda e: abs((e["ts"] - target_ts).total_seconds()))


def nearest_before(events, target_ts):
    c = [e for e in events if e["ts"] <= target_ts]
    if not c:
        return None
    return max(c, key=lambda e: e["ts"])


def nearest_after(events, target_ts):
    c = [e for e in events if e["ts"] >= target_ts]
    if not c:
        return None
    return min(c, key=lambda e: e["ts"])


def within(events, start_ts, end_ts):
    return [e for e in events if start_ts <= e["ts"] <= end_ts]


def summarize_fg(fg_events):
    out = {}
    out["count"] = len(fg_events)
    src_counts = {}
    cache_hit_true = 0
    cache_hit_false = 0
    max_disk_wait = 0.0
    max_decode_wait = 0.0
    max_frame_total = 0.0
    max_ui_lag = 0.0
    max_disk_reads = 0.0
    max_bytes = 0.0
    for e in fg_events:
        kv = e["kv"]
        src = str(kv.get("source", "?"))
        src_counts[src] = src_counts.get(src, 0) + 1
        if kv.get("cache_hit") is True:
            cache_hit_true += 1
        if kv.get("cache_hit") is False:
            cache_hit_false += 1
        max_disk_wait = max(max_disk_wait, float(kv.get("disk_wait_ms", 0.0) or 0.0))
        max_decode_wait = max(max_decode_wait, float(kv.get("decode_wait_ms", 0.0) or 0.0))
        max_frame_total = max(max_frame_total, float(kv.get("frame_total_ms", 0.0) or 0.0))
        max_ui_lag = max(max_ui_lag, float(kv.get("ui_lag_ms", 0.0) or 0.0))
        max_disk_reads = max(max_disk_reads, float(kv.get("foreground_disk_reads", 0.0) or 0.0))
        max_bytes = max(max_bytes, float(kv.get("foreground_bytes_read", 0.0) or 0.0))
    out["src_counts"] = src_counts
    out["cache_hit_true"] = cache_hit_true
    out["cache_hit_false"] = cache_hit_false
    out["max_disk_wait_ms"] = max_disk_wait
    out["max_decode_wait_ms"] = max_decode_wait
    out["max_frame_total_ms"] = max_frame_total
    out["max_ui_lag_ms"] = max_ui_lag
    out["max_foreground_disk_reads"] = max_disk_reads
    out["max_foreground_bytes_read"] = max_bytes
    return out


# Isolate target sessions
selected = []
for d in fast_drag:
    kv = d["kv"]
    ui_lag_max = float(kv.get("ui_lag_max_ms", 0.0) or 0.0)
    stall = bool(kv.get("main_thread_stall_during_drag", False))
    rebuild = bool(kv.get("dm_rebuild_during_drag", False))
    if ui_lag_max > 300.0 or stall or rebuild:
        selected.append(d)

selected.sort(key=lambda x: x["ts"])

print("Selected sessions:", len(selected))
print("=" * 100)

for idx, d in enumerate(selected, 1):
    kv = d["kv"]
    dsid = kv.get("drag_session_id", "-")
    duration_s = float(kv.get("duration_s", 0.0) or 0.0)
    end_ts = d["ts"]
    start_ts = end_ts - timedelta(seconds=duration_s)

    # nearest stalls
    stall_before = nearest_before(stall_events, start_ts)
    stall_during = nearest(within(stall_events, start_ts, end_ts), end_ts) if within(stall_events, start_ts, end_ts) else None
    stall_after = nearest_after(stall_events, end_ts)

    # nearest rebuild
    rb_before = nearest_before(dm_rebuild, start_ts)
    rb_during = nearest(within(dm_rebuild, start_ts, end_ts), end_ts) if within(dm_rebuild, start_ts, end_ts) else None
    rb_after = nearest_after(dm_rebuild, end_ts)

    # pacing
    pacing = fast_pacing_by_id.get(dsid)

    # fg disk
    fg_events = fg_by_drag_id.get(dsid, [])
    fg_sum = summarize_fg(fg_events)

    # nearby progressive/retro events (+/- 2s)
    near_prog = [e for e in progressive_events if abs((e["ts"] - end_ts).total_seconds()) <= 2.0]

    print(f"[{idx}] drag_session_id={dsid}")
    print(f"  timestamp_range={start_ts.strftime('%Y-%m-%d %H:%M:%S.%f')} .. {end_ts.strftime('%Y-%m-%d %H:%M:%S.%f')}")
    print(
        "  drag_flags="
        f"ui_lag_max_ms={float(kv.get('ui_lag_max_ms', 0.0) or 0.0):.3f}, "
        f"main_thread_stall_during_drag={bool(kv.get('main_thread_stall_during_drag', False))}, "
        f"dm_rebuild_during_drag={bool(kv.get('dm_rebuild_during_drag', False))}, "
        f"targets={int(float(kv.get('targets', 0.0) or 0.0))}"
    )

    def print_evt(prefix, evt, key_hint=None):
        if not evt:
            print(f"  {prefix}=none")
            return
        line = evt["line"]
        extra = ""
        if key_hint and key_hint in evt["kv"]:
            extra = f" {key_hint}={evt['kv'][key_hint]}"
        print(f"  {prefix}={evt['ts'].strftime('%Y-%m-%d %H:%M:%S.%f')}{extra}")

    print_evt("nearest_MAIN_THREAD_STALL_before", stall_before, "stall_duration_ms")
    print_evt("nearest_MAIN_THREAD_STALL_during", stall_during, "stall_duration_ms")
    print_evt("nearest_MAIN_THREAD_STALL_after", stall_after, "stall_duration_ms")

    print_evt("nearest_DM_REBUILD_before", rb_before, "duration_ms")
    print_evt("nearest_DM_REBUILD_during", rb_during, "duration_ms")
    print_evt("nearest_DM_REBUILD_after", rb_after, "duration_ms")

    if pacing:
        pk = pacing["kv"]
        print(
            "  FAST_EVENT_PACING="
            f"event_jitter_p95_ms={float(pk.get('event_jitter_p95_ms', 0.0) or 0.0):.3f}, "
            f"frame_present_interval_p95_ms={float(pk.get('frame_present_interval_p95_ms', 0.0) or 0.0):.3f}, "
            f"implied_queue_wait_p95_ms={float(pk.get('implied_queue_wait_p95_ms', 0.0) or 0.0):.3f}, "
            f"queue_wait_classification={pk.get('queue_wait_classification', '-')}, "
            f"pending_set_slice_queue_depth_max={float(pk.get('pending_set_slice_queue_depth_max', 0.0) or 0.0):.1f}, "
            f"same_slice_ratio_pct={float(pk.get('same_slice_ratio_pct', 0.0) or 0.0):.1f}, "
            f"coalesce_ratio_pct={float(pk.get('coalesce_ratio_pct', 0.0) or 0.0):.1f}"
        )
    else:
        print("  FAST_EVENT_PACING=not_found")

    print(
        "  FAST_FG_DISK="
        f"count={fg_sum['count']}, src_counts={fg_sum['src_counts']}, "
        f"cache_hit_true={fg_sum['cache_hit_true']}, cache_hit_false={fg_sum['cache_hit_false']}, "
        f"max_disk_wait_ms={fg_sum['max_disk_wait_ms']:.3f}, max_decode_wait_ms={fg_sum['max_decode_wait_ms']:.3f}, "
        f"max_frame_total_ms={fg_sum['max_frame_total_ms']:.3f}, max_ui_lag_ms={fg_sum['max_ui_lag_ms']:.3f}, "
        f"max_foreground_disk_reads={fg_sum['max_foreground_disk_reads']:.0f}, "
        f"max_foreground_bytes_read={fg_sum['max_foreground_bytes_read']:.0f}"
    )

    if near_prog:
        print("  nearby_PROG_RETRO_events:")
        for e in near_prog[:8]:
            print(f"    - {e['ts'].strftime('%Y-%m-%d %H:%M:%S.%f')} | {e['line'].split('|')[-1].strip()}")
    else:
        print("  nearby_PROG_RETRO_events:none")

    # Classification heuristic for this session
    cause = "UNKNOWN"
    dm_overlap = bool(kv.get("dm_rebuild_during_drag", False)) or (rb_during is not None)
    stall_overlap = bool(kv.get("main_thread_stall_during_drag", False)) or (stall_during is not None)
    pacing_bad = False
    if pacing:
        pk = pacing["kv"]
        pacing_bad = (
            float(pk.get("implied_queue_wait_p95_ms", 0.0) or 0.0) >= 120.0 or
            float(pk.get("event_jitter_p95_ms", 0.0) or 0.0) >= 120.0
        )
    prog_near = len(near_prog) > 0

    if dm_overlap:
        cause = "DM_REBUILD-related"
    elif stall_overlap:
        cause = "main-thread stall unrelated to DM"
    elif pacing_bad:
        cause = "event delivery/pacing jitter"
    elif prog_near:
        cause = "progressive/grow side effect"

    print(f"  session_classification={cause}")
    print("-" * 100)

# Overall classification for 618ms spike
spike = None
for d in selected:
    if float(d["kv"].get("ui_lag_max_ms", 0.0) or 0.0) >= 600.0:
        spike = d
        break

print("OVERALL_618MS_SPIKE_DECISION:")
if not spike:
    print("  No >=600ms ui_lag_max session found in selected set")
else:
    sk = spike["kv"]
    dsid = sk.get("drag_session_id", "-")
    pacing = fast_pacing_by_id.get(dsid)
    rb = bool(sk.get("dm_rebuild_during_drag", False))
    st = bool(sk.get("main_thread_stall_during_drag", False))
    pacing_bad = False
    if pacing:
        pk = pacing["kv"]
        pacing_bad = (
            float(pk.get("implied_queue_wait_p95_ms", 0.0) or 0.0) >= 120.0 or
            float(pk.get("event_jitter_p95_ms", 0.0) or 0.0) >= 120.0
        )

    if rb:
        decision = "1) DM_REBUILD-related"
    elif st:
        decision = "2) main-thread stall unrelated to DM"
    elif pacing_bad:
        decision = "3) event delivery/pacing jitter"
    else:
        decision = "5) UNKNOWN"

    print(f"  drag_session_id={dsid}")
    print(f"  ui_lag_max_ms={float(sk.get('ui_lag_max_ms', 0.0) or 0.0):.3f}")
    print(f"  dm_rebuild_during_drag={rb}")
    print(f"  main_thread_stall_during_drag={st}")
    print(f"  decision={decision}")
