import re
from pathlib import Path
from statistics import median

root = Path("user_data/logs")
viewer = root / "viewer_diagnostics.log"
download = root / "download_diagnostics.log"

vtxt = viewer.read_text(encoding="utf-8", errors="ignore") if viewer.exists() else ""
dtxt = download.read_text(encoding="utf-8", errors="ignore") if download.exists() else ""

def fnums(pattern, text):
    vals = []
    for m in re.finditer(pattern, text):
        try:
            vals.append(float(m.group(1)))
        except Exception:
            pass
    return vals

def p95(values):
    if not values:
        return None
    s = sorted(values)
    idx = int(round(0.95 * (len(s) - 1)))
    return s[idx]

def fmt(x):
    return "n/a" if x is None else f"{x:.3f}"

# Exact code checks
c41189_viewer = len(re.findall(r"41189", vtxt))
c41189_download = len(re.findall(r"41189", dtxt))

# Series 203 generic counts
series203_viewer = len(re.findall(r"series=203\\b", vtxt))
series203_download = len(re.findall(r"series=203\\b", dtxt))

# KPIs from FAST_DRAG_KPI / FAST_EVENT_PACING for series 203
drag_ui_lag_max = fnums(r"series=203.*?\\[FAST_DRAG_KPI\\].*?ui_lag_max_ms=([0-9.]+)", vtxt)
drag_handler_p95 = fnums(r"series=203.*?\\[FAST_DRAG_KPI\\].*?handler_p95_ms=([0-9.]+)", vtxt)
pace_event_jitter_p95 = fnums(r"series=203.*?\\[FAST_EVENT_PACING\\].*?event_jitter_p95_ms=([0-9.]+)", vtxt)
pace_frame_interval_p95 = fnums(r"series=203.*?\\[FAST_EVENT_PACING\\].*?frame_present_interval_p95_ms=([0-9.]+)", vtxt)
pace_queue_wait_p95 = fnums(r"series=203.*?\\[FAST_EVENT_PACING\\].*?implied_queue_wait_p95_ms=([0-9.]+)", vtxt)

# Foreground frame data
fg_ui_lag = fnums(r"series=203.*?\\[FAST_FG_DISK\\].*?ui_lag_ms=([0-9.]+)", vtxt)
fg_frame_total = fnums(r"series=203.*?\\[FAST_FG_DISK\\].*?frame_total_ms=([0-9.]+)", vtxt)

# Progressive/retro tags for series 203
retro_capped = len(re.findall(r"series=203.*?\\[RETRO_META_SYNC_CAPPED\\]", vtxt))
retro_throttled = len(re.findall(r"series=203.*?\\[RETRO_META_SYNC_THROTTLED\\]", vtxt))
retro_flush = len(re.findall(r"series=203.*?\\[RETRO_META_SYNC_FINAL_FLUSH\\]", vtxt))
old_deferred = fnums(r"series=203.*?phase=deferred_meta_sync.*?post_grow_signal_ms=([0-9.]+)", vtxt)

# DM rebuild overlap for series 203
dm_rebuild_enter = len(re.findall(r"series=203.*?\\[DM_REBUILD\\].*?event=enter", dtxt))
dm_rebuild_exit_dur = fnums(r"series=203.*?\\[DM_REBUILD\\].*?event=exit.*?duration_ms=([0-9.]+)", dtxt)

# Download progress summary
sum_downloaded = fnums(r"series-summary series=203 downloaded=([0-9.]+)", dtxt)
sum_total = fnums(r"series-summary series=203 .*? total=([0-9.]+)", dtxt)

print("=== CODE CHECK ===")
print(f"41189 hits in viewer log: {c41189_viewer}")
print(f"41189 hits in download log: {c41189_download}")
print()
print("=== SERIES 203 PRESENCE ===")
print(f"series=203 lines in viewer log: {series203_viewer}")
print(f"series=203 lines in download log: {series203_download}")
print()
print("=== SERIES 203 FAST KPI ===")
print(f"FAST_DRAG_KPI count: {len(drag_ui_lag_max)}")
print(f"ui_lag_max_ms p50/p95/max: {fmt(median(drag_ui_lag_max) if drag_ui_lag_max else None)} / {fmt(p95(drag_ui_lag_max))} / {fmt(max(drag_ui_lag_max) if drag_ui_lag_max else None)}")
print(f"handler_p95_ms p50/p95/max: {fmt(median(drag_handler_p95) if drag_handler_p95 else None)} / {fmt(p95(drag_handler_p95))} / {fmt(max(drag_handler_p95) if drag_handler_p95 else None)}")
print(f"event_jitter_p95_ms p50/p95/max: {fmt(median(pace_event_jitter_p95) if pace_event_jitter_p95 else None)} / {fmt(p95(pace_event_jitter_p95))} / {fmt(max(pace_event_jitter_p95) if pace_event_jitter_p95 else None)}")
print(f"frame_present_interval_p95_ms p50/p95/max: {fmt(median(pace_frame_interval_p95) if pace_frame_interval_p95 else None)} / {fmt(p95(pace_frame_interval_p95))} / {fmt(max(pace_frame_interval_p95) if pace_frame_interval_p95 else None)}")
print(f"implied_queue_wait_p95_ms p50/p95/max: {fmt(median(pace_queue_wait_p95) if pace_queue_wait_p95 else None)} / {fmt(p95(pace_queue_wait_p95))} / {fmt(max(pace_queue_wait_p95) if pace_queue_wait_p95 else None)}")
print(f"FAST_FG_DISK ui_lag_ms p50/p95/max: {fmt(median(fg_ui_lag) if fg_ui_lag else None)} / {fmt(p95(fg_ui_lag))} / {fmt(max(fg_ui_lag) if fg_ui_lag else None)}")
print(f"FAST_FG_DISK frame_total_ms p50/p95/max: {fmt(median(fg_frame_total) if fg_frame_total else None)} / {fmt(p95(fg_frame_total))} / {fmt(max(fg_frame_total) if fg_frame_total else None)}")
print()
print("=== SERIES 203 RETRO/PROGRESSIVE ===")
print(f"RETRO_META_SYNC_CAPPED count: {retro_capped}")
print(f"RETRO_META_SYNC_THROTTLED count: {retro_throttled}")
print(f"RETRO_META_SYNC_FINAL_FLUSH count: {retro_flush}")
if old_deferred:
    print(f"Old deferred_meta_sync post_grow_signal_ms max: {max(old_deferred):.3f}")
else:
    print("Old deferred_meta_sync post_grow_signal_ms: not found for series 203")
print()
print("=== SERIES 203 DOWNLOAD/DM ===")
if sum_downloaded and sum_total:
    print(f"series-summary downloaded last/max: {int(sum_downloaded[-1])} / {int(max(sum_downloaded))}")
    print(f"series-summary total last/max: {int(sum_total[-1])} / {int(max(sum_total))}")
print(f"DM_REBUILD enter count (series 203): {dm_rebuild_enter}")
if dm_rebuild_exit_dur:
    print(f"DM_REBUILD duration_ms p50/p95/max: {fmt(median(dm_rebuild_exit_dur))} / {fmt(p95(dm_rebuild_exit_dur))} / {fmt(max(dm_rebuild_exit_dur))}")
else:
    print("DM_REBUILD duration_ms: n/a")
