from pathlib import Path
from statistics import median

viewer = Path("user_data/logs/viewer_diagnostics.log")
download = Path("user_data/logs/download_diagnostics.log")

vlines = viewer.read_text(encoding="utf-8", errors="ignore").splitlines() if viewer.exists() else []
dlines = download.read_text(encoding="utf-8", errors="ignore").splitlines() if download.exists() else []

def get_num(line, key):
    marker = key + "="
    i = line.find(marker)
    if i < 0:
        return None
    j = i + len(marker)
    k = j
    while k < len(line) and (line[k].isdigit() or line[k] in ".-"):
        k += 1
    try:
        return float(line[j:k])
    except Exception:
        return None

def p95(vals):
    if not vals:
        return None
    s = sorted(vals)
    return s[int(round((len(s)-1)*0.95))]

def fm(x):
    return "n/a" if x is None else f"{x:.3f}"

hits_41189_v = sum(1 for ln in vlines if "41189" in ln)
hits_41189_d = sum(1 for ln in dlines if "41189" in ln)

v203 = [ln for ln in vlines if "series=203" in ln]
d203 = [ln for ln in dlines if "series=203" in ln or "series-summary series=203" in ln]

drag = [ln for ln in v203 if "[FAST_DRAG_KPI]" in ln]
pacing = [ln for ln in v203 if "[FAST_EVENT_PACING]" in ln]
fg = [ln for ln in v203 if "[FAST_FG_DISK]" in ln]
retro_cap = [ln for ln in v203 if "[RETRO_META_SYNC_CAPPED]" in ln]
retro_thr = [ln for ln in v203 if "[RETRO_META_SYNC_THROTTLED]" in ln]
old_def = [ln for ln in v203 if "phase=deferred_meta_sync" in ln]

ui_lag_max = [x for x in (get_num(ln, "ui_lag_max_ms") for ln in drag) if x is not None]
handler_p95 = [x for x in (get_num(ln, "handler_p95_ms") for ln in drag) if x is not None]
ej_p95 = [x for x in (get_num(ln, "event_jitter_p95_ms") for ln in pacing) if x is not None]
fp_p95 = [x for x in (get_num(ln, "frame_present_interval_p95_ms") for ln in pacing) if x is not None]
iq_p95 = [x for x in (get_num(ln, "implied_queue_wait_p95_ms") for ln in pacing) if x is not None]
fg_ui_lag = [x for x in (get_num(ln, "ui_lag_ms") for ln in fg) if x is not None]
fg_frame_total = [x for x in (get_num(ln, "frame_total_ms") for ln in fg) if x is not None]

rebuild_exit = [ln for ln in dlines if "series=203" in ln and "[DM_REBUILD]" in ln and "event=exit" in ln]
rebuild_dur = [x for x in (get_num(ln, "duration_ms") for ln in rebuild_exit) if x is not None]
sum_lines = [ln for ln in dlines if "series-summary series=203" in ln]
sum_downloaded = [x for x in (get_num(ln, "downloaded") for ln in sum_lines) if x is not None]
sum_total = [x for x in (get_num(ln, "total") for ln in sum_lines) if x is not None]

print("41189_viewer_hits", hits_41189_v)
print("41189_download_hits", hits_41189_d)
print("viewer_series203_line_count", len(v203))
print("download_series203_line_count", len(d203))
print("drag_kpi_count", len(drag))
print("event_pacing_count", len(pacing))
print("fg_disk_count", len(fg))
print("ui_lag_max_ms_p50_p95_max", fm(median(ui_lag_max) if ui_lag_max else None), fm(p95(ui_lag_max)), fm(max(ui_lag_max) if ui_lag_max else None))
print("handler_p95_ms_p50_p95_max", fm(median(handler_p95) if handler_p95 else None), fm(p95(handler_p95)), fm(max(handler_p95) if handler_p95 else None))
print("event_jitter_p95_ms_p50_p95_max", fm(median(ej_p95) if ej_p95 else None), fm(p95(ej_p95)), fm(max(ej_p95) if ej_p95 else None))
print("frame_present_interval_p95_ms_p50_p95_max", fm(median(fp_p95) if fp_p95 else None), fm(p95(fp_p95)), fm(max(fp_p95) if fp_p95 else None))
print("implied_queue_wait_p95_ms_p50_p95_max", fm(median(iq_p95) if iq_p95 else None), fm(p95(iq_p95)), fm(max(iq_p95) if iq_p95 else None))
print("fg_ui_lag_ms_p50_p95_max", fm(median(fg_ui_lag) if fg_ui_lag else None), fm(p95(fg_ui_lag)), fm(max(fg_ui_lag) if fg_ui_lag else None))
print("fg_frame_total_ms_p50_p95_max", fm(median(fg_frame_total) if fg_frame_total else None), fm(p95(fg_frame_total)), fm(max(fg_frame_total) if fg_frame_total else None))
print("retro_capped_count", len(retro_cap))
print("retro_throttled_count", len(retro_thr))
print("old_deferred_count", len(old_def))
print("dm_rebuild_exit_count", len(rebuild_exit))
print("dm_rebuild_duration_max", fm(max(rebuild_dur) if rebuild_dur else None))
print("series203_downloaded_last_max", (int(sum_downloaded[-1]), int(max(sum_downloaded))) if sum_downloaded else "n/a")
print("series203_total_last_max", (int(sum_total[-1]), int(max(sum_total))) if sum_total else "n/a")
