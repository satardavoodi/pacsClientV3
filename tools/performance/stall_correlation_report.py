"""Parse viewer/download diagnostics and report stall correlation buckets.

Usage:
  .venv/Scripts/python.exe tools/performance/stall_correlation_report.py
  .venv/Scripts/python.exe tools/performance/stall_correlation_report.py --top 15
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
VIEWER_LOG = ROOT / "user_data" / "logs" / "viewer_diagnostics.log"
DOWNLOAD_LOG = ROOT / "user_data" / "logs" / "download_diagnostics.log"

TAG_RE = re.compile(r"\[(?P<tag>[A-Z0-9_]+)\]")
KV_RE = re.compile(r"(?P<k>[a-zA-Z0-9_]+)=(?P<v>[^\s]+)")


def _parse_ts_ms(line: str) -> Optional[float]:
    try:
        stamp = line.split(" | ", 1)[0].strip()
        if "." in stamp:
            d = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S.%f")
        else:
            d = dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        return d.timestamp() * 1000.0
    except Exception:
        return None


def _to_float(raw: Optional[str], default: float = 0.0) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _to_bool(raw: Optional[str]) -> bool:
    if raw is None:
        return False
    v = str(raw).strip().lower()
    return v in {"1", "true", "yes", "y"}


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * (p / 100.0)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(ordered[lo])
    weight = pos - lo
    return float(ordered[lo] * (1.0 - weight) + ordered[hi] * weight)


def _parse_file(path: Path) -> List[Dict]:
    events: List[Dict] = []
    if not path.exists():
        return events
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            ts_ms = _parse_ts_ms(line)
            if ts_ms is None:
                continue
            tag_m = TAG_RE.search(line)
            if not tag_m:
                continue
            tag = tag_m.group("tag")
            fields = {m.group("k"): m.group("v") for m in KV_RE.finditer(line)}
            events.append({"ts_ms": ts_ms, "tag": tag, "fields": fields, "line": line.rstrip("\n")})
    return events


def _nearest_prior(events: List[Dict], ts_ms: float, tags: Tuple[str, ...], window_ms: float = 1000.0) -> Optional[Dict]:
    nearest = None
    nearest_age = 10**18
    for ev in events:
        if ev["tag"] not in tags:
            continue
        age = ts_ms - ev["ts_ms"]
        if age < 0.0 or age > window_ms:
            continue
        if age < nearest_age:
            nearest_age = age
            nearest = ev
    return nearest


def _build_drag_intervals(events: List[Dict]) -> List[Tuple[float, float]]:
    intervals: List[Tuple[float, float]] = []
    open_starts: List[float] = []
    for ev in events:
        if ev["tag"] == "FAST_DRAG_SESSION" and ev["fields"].get("phase") == "start":
            open_starts.append(ev["ts_ms"])
        elif ev["tag"] == "FAST_DRAG_KPI":
            if open_starts:
                start = open_starts.pop(0)
                intervals.append((start, ev["ts_ms"]))
    return intervals


def _bucket_for_stall(ev: Dict, all_events: List[Dict]) -> Tuple[str, Optional[Dict]]:
    ts = ev["ts_ms"]
    candidates = [
        ("DM_REBUILD", _nearest_prior(all_events, ts, ("DM_REBUILD",))),
        ("VIEWER_SWITCH", _nearest_prior(all_events, ts, ("VIEWER_SWITCH",))),
        ("PROGRESSIVE_GROW", _nearest_prior(all_events, ts, ("PROGRESSIVE_GROW", "PROGRESSIVE_APPEND"))),
        ("TABLE_REFRESH", _nearest_prior(all_events, ts, ("DM_REFRESH_QUEUE", "TABLE_REFRESH"))),
        ("SIGNAL_FANOUT", _nearest_prior(all_events, ts, ("SIGNAL_FANOUT",))),
    ]
    best_bucket = "UNKNOWN"
    best_event: Optional[Dict] = None
    best_age = 10**18
    for bucket, cand in candidates:
        if cand is None:
            continue
        age = ts - cand["ts_ms"]
        if 0.0 <= age < best_age:
            best_age = age
            best_bucket = bucket
            best_event = cand
    return best_bucket, best_event


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--viewer-log", default=str(VIEWER_LOG))
    parser.add_argument("--download-log", default=str(DOWNLOAD_LOG))
    parser.add_argument("--top", type=int, default=10)
    args = parser.parse_args()

    viewer_events = _parse_file(Path(args.viewer_log))
    download_events = _parse_file(Path(args.download_log))
    all_events = sorted(viewer_events + download_events, key=lambda x: x["ts_ms"])

    stalls = [e for e in all_events if e["tag"] == "MAIN_THREAD_STALL"]
    dm_rebuild_exit = [
        _to_float(e["fields"].get("duration_ms"))
        for e in all_events
        if e["tag"] == "DM_REBUILD" and e["fields"].get("event") == "exit"
    ]
    dm_rebuild_events = [e for e in all_events if e["tag"] == "DM_REBUILD" and e["fields"].get("event") == "enter"]

    drag_intervals = _build_drag_intervals(all_events)

    stalls_enriched = []
    overlap_interaction = 0
    for s in stalls:
        duration = _to_float(s["fields"].get("stall_duration_ms"), _to_float(s["fields"].get("gap_ms")))
        interaction = _to_bool(s["fields"].get("interaction_active") or s["fields"].get("drag_active"))
        if interaction:
            overlap_interaction += 1
        bucket, nearest = _bucket_for_stall(s, all_events)
        stalls_enriched.append({
            "stall": s,
            "duration": duration,
            "interaction": interaction,
            "bucket": bucket,
            "nearest": nearest,
        })

    stalls_enriched.sort(key=lambda x: x["duration"], reverse=True)

    dm_during_drag = 0
    for dm in dm_rebuild_events:
        for start, end in drag_intervals:
            if start <= dm["ts_ms"] <= end:
                dm_during_drag += 1
                break

    print("=== Stall Correlation Report ===")
    print(f"viewer_log={args.viewer_log}")
    print(f"download_log={args.download_log}")
    print(f"total_stalls={len(stalls_enriched)}")
    print(f"stalls_overlapping_interaction={overlap_interaction}")
    print(f"dm_rebuild_events_during_active_drag={dm_during_drag}")
    print(
        "dm_rebuild_duration_ms p50={:.3f} p95={:.3f} max={:.3f}".format(
            _percentile(dm_rebuild_exit, 50),
            _percentile(dm_rebuild_exit, 95),
            max(dm_rebuild_exit) if dm_rebuild_exit else 0.0,
        )
    )

    print("\n=== Top MAIN_THREAD_STALL Events ===")
    for idx, item in enumerate(stalls_enriched[: max(1, int(args.top))], start=1):
        stall = item["stall"]
        near = item["nearest"]
        near_desc = "none"
        if near is not None:
            near_desc = f"{near['tag']} age_ms={stall['ts_ms'] - near['ts_ms']:.1f}"
        print(
            f"{idx}. duration_ms={item['duration']:.1f} interaction={item['interaction']} "
            f"bucket={item['bucket']} nearest={near_desc}"
        )

    print("\n=== Likely Attribution Per Stall (Top Ordered) ===")
    for idx, item in enumerate(stalls_enriched[: max(1, int(args.top))], start=1):
        print(f"{idx}. {item['bucket']}")

    if not stalls_enriched:
        print("No MAIN_THREAD_STALL events found.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
